"""Restart daily tracking from an observed day, archiving the previous tracking history."""

import json
from contextlib import ExitStack
from datetime import timezone
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, field_validator

from customer_signal.agent.contracts import RunRequest
from customer_signal.signals.contracts import Contract, Measurement, now
from customer_signal.signals.fast_forward import FastForwardConflict, FastForwardService, SignalSelection
from customer_signal.signals.schedule_contracts import DAY, next_midnight


class FastForwardResetRequest(SignalSelection):
    start_at: AwareDatetime = Field(description="다음 분석을 시작할 한국 시각 자정, 직전 하루가 비교 기준")

    @field_validator("start_at")
    @classmethod
    def midnight(cls, value):
        if value != next_midnight(value) - DAY:
            raise ValueError("시작일은 한국 시각 자정이어야 합니다.")
        return value.astimezone(timezone.utc)


class FastForwardResetItem(Contract):
    signal_id: str
    archived_measurements: int
    baseline_measurement: Measurement


class FastForwardResetResult(Contract):
    request_id: UUID
    start_at: AwareDatetime
    items: list[FastForwardResetItem]


class FastForwardResetService:
    def __init__(self, forward: FastForwardService):
        self.forward, self.store = forward, forward.store
        with self.store._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS signal_tracking_archives (
                    archive_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signal_fast_forward_resets (
                    request_id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL
                );
            """)

    def run(self, request: FastForwardResetRequest) -> FastForwardResetResult:
        with self.forward.schedules.lock("fast-forward"), ExitStack() as locks:
            with self.store._connection() as db:
                saved = db.execute(
                    "SELECT request, response FROM signal_fast_forward_resets WHERE request_id=?",
                    (str(request.request_id),),
                ).fetchone()
            if saved:
                if FastForwardResetRequest.model_validate_json(saved[0]) != request:
                    raise FastForwardConflict("같은 request_id에 다른 입력을 사용할 수 없습니다.")
                return FastForwardResetResult.model_validate_json(saved[1])
            ids = request.signal_ids
            if ids is None:
                ids = sorted(s.signal_id for s in self.store.list_signals()
                             if self.forward._inactive_reason(s.signal_id) is None)
            for sid in ids:
                self.store.get_signal(sid)
                locks.enter_context(self.forward.schedules.lock(sid))
                if self.forward._inactive_reason(sid):
                    raise FastForwardConflict("활성 상태이고 일별 측정이 켜진 시그널만 다시 시작할 수 있습니다.")

            # Validate every source and baseline before changing any signal. Preview
            # measurements are not persisted and never evaluate alerts.
            baselines = {}
            for sid in ids:
                signal = self.store.get_signal(sid)
                data = self.forward._observed_data(RunRequest(
                    question=signal.title, enabled_sources=signal.definition.source_ids,
                    start_at=request.start_at, end_at=request.start_at + DAY,
                ))
                data.close()
                baselines[sid] = self.forward.service.measure(
                    signal, start_at=request.start_at - DAY, end_at=request.start_at,
                    evaluate_alerts=False, require_success=True, persist=False,
                )

            with self.store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                items = []
                for sid in ids:
                    tables = {
                        "measurements": "signal_measurements", "daily_runs": "signal_daily_runs",
                        "schedule": "signal_schedules", "alert_state": "signal_alert_state",
                    }
                    archive = {}
                    for key, table in tables.items():
                        cursor = db.execute(f"SELECT * FROM {table} WHERE signal_id=?", (sid,))
                        columns = [c[0] for c in cursor.description]
                        archive[key] = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    db.execute("INSERT INTO signal_tracking_archives VALUES (?, ?, ?, ?)", (
                        str(uuid4()), sid, now().isoformat(), json.dumps(archive, ensure_ascii=False),
                    ))
                    # Archive first, then replace only active tracking history. Signal
                    # definitions, rule settings, proposals and sent events remain intact.
                    db.execute("DELETE FROM signal_daily_runs WHERE signal_id=?", (sid,))
                    db.execute("DELETE FROM signal_measurements WHERE signal_id=?", (sid,))
                    baseline = self.store._insert_measurement(db, sid, baselines[sid])
                    db.execute(
                        "UPDATE signal_alert_state SET matched=0, last_end_at=? WHERE signal_id=?",
                        (request.start_at.isoformat(), sid),
                    )
                    db.execute(
                        "UPDATE signal_schedules SET next_run_at=?, updated_at=? WHERE signal_id=?",
                        (max(next_midnight(now()), request.start_at + DAY).isoformat(),
                         now().isoformat(), sid),
                    )
                    items.append(FastForwardResetItem(
                        signal_id=sid, archived_measurements=len(archive["measurements"]),
                        baseline_measurement=baseline,
                    ))
                # A process may have died after reserving days but before saving its
                # response. Retrying that old request must not undo this restart.
                reset_ids = set(ids)
                for request_id, raw_plan in db.execute(
                    "SELECT request_id, plan FROM signal_fast_forwards WHERE response IS NULL",
                ).fetchall():
                    plan = json.loads(raw_plan)
                    changed = False
                    for item in plan:
                        if item["signal_id"] in reset_ids:
                            item.update(
                                status="skipped",
                                reason="시작일을 다시 설정해 이전에 중단된 요청을 종료했습니다.",
                            )
                            changed = True
                    if changed:
                        db.execute(
                            "UPDATE signal_fast_forwards SET plan=? WHERE request_id=?",
                            (json.dumps(plan, ensure_ascii=False), request_id),
                        )
                result = FastForwardResetResult(
                    request_id=request.request_id, start_at=request.start_at, items=items,
                )
                db.execute("INSERT INTO signal_fast_forward_resets VALUES (?, ?, ?)", (
                    str(request.request_id), request.model_dump_json(), result.model_dump_json(),
                ))
            return result
