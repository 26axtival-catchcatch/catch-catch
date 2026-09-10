"""Advance registered signals through real daily analysis, with durable request replay."""

from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from customer_signal.signals.alert_contracts import AlertEvent
from customer_signal.signals.contracts import Contract, Measurement
from customer_signal.signals.schedule_contracts import DAY, DailyResult, next_midnight
from customer_signal.signals.scheduling import DailyScheduler, ScheduleStore
from customer_signal.signals.service import SignalService


class FastForwardRequest(Contract):
    request_id: UUID = Field(description="한 번의 빨리감기를 식별하는 UUID, 재시도 시 재사용")
    days: int = Field(default=1, strict=True, ge=1, le=7, description="분석할 다음 일자 수")
    signal_ids: list[str] | None = Field(
        default=None, min_length=1, max_length=100,
        description="대상 시그널 ID, 생략하면 현재 등록 목록을 고정해 처리",
    )

    @field_validator("signal_ids")
    @classmethod
    def unique_ids(cls, value):
        if value is not None:
            if len(value) != len(set(value)) or any(not v or len(v) > 200 for v in value):
                raise ValueError("signal_ids는 비어 있지 않은 고유 ID여야 합니다.")
            return sorted(value)
        return value


class FastForwardItem(Contract):
    signal_id: str
    status: Literal["completed", "skipped"]
    reason: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    baseline_measurement: Measurement | None = None
    daily_results: list[DailyResult] = Field(default_factory=list)
    alert_events: list[AlertEvent] = Field(default_factory=list)


class FastForwardResult(Contract):
    request_id: UUID
    days: int
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    items: list[FastForwardItem]


class FastForwardConflict(ValueError):
    """A request ID was reused for a different operation."""


class FastForwardService:
    def __init__(self, service):
        self.store, self.load_data = service.store, service.load_data
        # Fast-forward can intentionally exceed available dates. A completely empty
        # future window is unknown, including for definitions without a denominator.
        # Normal manual/scheduled measurements retain their established zero semantics.
        self.service = SignalService(store=self.store, load_data=self._observed_data)
        self.schedules = ScheduleStore(self.store)
        self.worker = DailyScheduler(self.schedules, self.service)
        with self.store._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS signal_fast_forwards (
                request_id TEXT PRIMARY KEY, request TEXT NOT NULL,
                plan TEXT NOT NULL, response TEXT
            )""")

    def _observed_data(self, request):
        data = self.load_data(request)
        if not data.events:
            data.close()
            raise ValueError("빨리감기할 날짜의 관측 데이터가 없습니다.")
        return data

    def run(self, request: FastForwardRequest) -> FastForwardResult:
        # All processes share flock. Acquire every signal lock before reserving dates or
        # measuring anything so a 409 busy response never represents partial new work.
        with self.schedules.lock("fast-forward"), ExitStack() as locks:
            with self.store._connection() as db:
                saved = db.execute(
                    "SELECT request, plan, response FROM signal_fast_forwards WHERE request_id=?",
                    (str(request.request_id),),
                ).fetchone()
            if saved:
                if FastForwardRequest.model_validate_json(saved[0]) != request:
                    raise FastForwardConflict("같은 request_id에 다른 입력을 사용할 수 없습니다.")
                if saved[2]:
                    return FastForwardResult.model_validate_json(saved[2])
                plan = [FastForwardItem.model_validate(p) for p in json.loads(saved[1])]
                ids = [p.signal_id for p in plan]
            else:
                ids = request.signal_ids
                if ids is None:
                    ids = sorted(s.signal_id for s in self.store.list_signals())
                # Validate the full selection before any mutation.
                for sid in ids:
                    self.store.get_signal(sid)
            for sid in ids:
                locks.enter_context(self.schedules.lock(sid))
            if not saved:
                plan = [self._plan(sid, request.days) for sid in ids]
                with self.store._connection() as db:
                    db.execute(
                        "INSERT INTO signal_fast_forwards VALUES (?, ?, ?, NULL)",
                        (str(request.request_id), request.model_dump_json(), json.dumps(
                            [p.model_dump(mode="json") for p in plan], ensure_ascii=False,
                        )),
                    )
            items = [self._execute(item) for item in plan]
            result = FastForwardResult(request_id=request.request_id, days=request.days, items=items)
            with self.store._connection() as db:
                db.execute(
                    "UPDATE signal_fast_forwards SET response=? WHERE request_id=?",
                    (result.model_dump_json(), str(request.request_id)),
                )
            return result

    def _inactive_reason(self, signal_id: str) -> str | None:
        schedule = self.schedules.get(signal_id)
        if schedule.signal_status != "active":
            return "일시 중지하거나 보관한 시그널입니다."
        if not schedule.enabled:
            return "일별 자동 측정이 비활성화된 시그널입니다."
        return None

    def _plan(self, signal_id: str, days: int) -> FastForwardItem:
        reason = self._inactive_reason(signal_id)
        measurements = self.store.list_measurements(signal_id)
        if reason or not measurements:
            return FastForwardItem(
                signal_id=signal_id, status="skipped",
                reason=reason or "기준 분석 이력이 없습니다.",
            )
        latest = max(m.end_at for m in measurements)
        # A partial last day is never overlapped by a new daily evaluation.
        midnight = next_midnight(latest) - DAY
        start = latest if latest == midnight else midnight + DAY
        return FastForwardItem(
            signal_id=signal_id, status="completed", start_at=start, end_at=start + days * DAY,
        )

    def _baseline(self, signal_id: str, end_at: datetime) -> Measurement:
        existing = [
            m for m in self.store.list_measurements(signal_id)
            if m.start_at == end_at - DAY and m.end_at == end_at and m.status == "success"
        ]
        if existing:
            return existing[-1]
        # A weekly registration needs a comparable day. Saving that baseline must never
        # retroactively trigger an alert, including when aligning a partial-day query.
        return self.service.measure(
            self.store.get_signal(signal_id), start_at=end_at - DAY, end_at=end_at,
            evaluate_alerts=False,
        )

    def _execute(self, item: FastForwardItem) -> FastForwardItem:
        if item.status == "skipped":
            return item
        reason = self._inactive_reason(item.signal_id)
        if reason:
            return item.model_copy(update={"status": "skipped", "reason": reason})
        baseline = self._baseline(item.signal_id, item.start_at)
        days, events = [], []
        end = item.start_at + DAY
        while end <= item.end_at:
            day = self.schedules.completed_day(item.signal_id, end)
            if day is None:
                day = self.worker.execute_day(item.signal_id, end)
            days.append(day)
            with self.store._connection() as db:
                rows = db.execute(
                    "SELECT sequence, payload FROM signal_alert_events WHERE signal_id=? "
                    "AND measurement_id=? ORDER BY sequence",
                    (item.signal_id, day.measurement.measurement_id),
                ).fetchall()
            events.extend(AlertEvent.model_validate({**json.loads(p), "sequence": seq})
                          for seq, p in rows)
            end += DAY
        return item.model_copy(update={
            "baseline_measurement": baseline, "daily_results": days, "alert_events": events,
        })
