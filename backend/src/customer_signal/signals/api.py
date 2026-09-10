"""User-selected registration and fixed-definition measurement HTTP API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from customer_signal.observability.langfuse import LangfuseRunContext
from customer_signal.signals.briefing import SignalBriefingList, briefing_card
from customer_signal.signals.contracts import Measurement, Proposal, Signal, SignalDefinition
from customer_signal.signals.service import MeasurementUnavailable, SignalService
from customer_signal.signals.comparison import (
    MeasurementComparison, compare_measurements, comparison_limitations,
)
from customer_signal.signals.schedule_contracts import DailyResults, DailySchedule, ScheduleUpdate
from customer_signal.signals.scheduling import ScheduleBusy, ScheduleStore
from customer_signal.signals.alert_api import create_alert_router
from customer_signal.signals.alert_recommendations import measurement_recommendations
from customer_signal.signals.fast_forward import (
    FastForwardConflict, FastForwardRequest, FastForwardResult, FastForwardService,
)
from customer_signal.signals.fast_forward_reset import (
    FastForwardResetRequest, FastForwardResetResult, FastForwardResetService,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterSignal(RequestModel):
    proposal_id: str = Field(min_length=1, max_length=80)


class UpdateSignal(RequestModel):
    status: Literal["active", "paused", "archived"]


class MeasurementRequest(RequestModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def valid_window(self):
        if self.start_at >= self.end_at:
            raise ValueError("start_at must precede exclusive end_at")
        return self


class RegisterDefinedSignal(MeasurementRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=10000)
    definition: SignalDefinition


class ProposalList(BaseModel):
    items: list[Proposal]


class SignalList(BaseModel):
    items: list[Signal]


class MeasurementHistory(BaseModel):
    items: list[Measurement]
    latest_by_window: list[Measurement]
    comparable: bool
    comparison_limitations: list[str]


def history_response(items: list[Measurement]) -> MeasurementHistory:
    latest = {}
    for item in sorted(items, key=lambda m: m.measured_at):
        key = (item.start_at, item.end_at)
        previous = latest.get(key)
        if previous is None or item.status == "success" or previous.status != "success":
            latest[key] = item
    windows = sorted(latest.values(), key=lambda m: (m.start_at, m.end_at))
    reasons = comparison_limitations(windows)
    return MeasurementHistory(
        items=items,
        latest_by_window=windows,
        comparable=not reasons,
        comparison_limitations=reasons,
    )


def create_router(
    *, store, is_completed: Callable[[str], bool], load_data: Callable,
    recommend: Callable = measurement_recommendations,
) -> APIRouter:
    router = APIRouter(tags=["signals"])
    service = SignalService(store=store, load_data=load_data, recommend=recommend)
    schedules = ScheduleStore(store)
    fast_forward_service = FastForwardService(service)
    reset_service = FastForwardResetService(fast_forward_service)
    # Alert router declares the shared tag itself; avoid duplicate inherited tags.
    alert_router = create_alert_router(service=service)

    def signal_or_404(signal_id):
        try:
            return store.get_signal(signal_id)
        except KeyError:
            raise HTTPException(404, "시그널을 찾을 수 없습니다.") from None

    def proposal_or_404(proposal_id):
        try:
            return store.get_proposal(proposal_id)
        except KeyError:
            raise HTTPException(404, "시그널 후보를 찾을 수 없습니다.") from None

    def require_completed(run_id):
        if not is_completed(run_id):
            raise HTTPException(409, "완료된 분석의 검증 후보만 조회·등록할 수 있습니다.")

    @router.get("/api/runs/{run_id}/signal-proposals", summary="분석의 시그널 후보 목록 조회")
    def proposals(run_id: str) -> ProposalList:
        require_completed(run_id)
        return ProposalList(items=store.list_proposals(run_id))

    @router.get(
        "/api/runs/{run_id}/signal-proposals/{proposal_id}", summary="분석의 시그널 후보 상세 조회"
    )
    def proposal_detail(run_id: str, proposal_id: str) -> Proposal:
        require_completed(run_id)
        proposal = proposal_or_404(proposal_id)
        if proposal.run_id != run_id:
            raise HTTPException(404, "이 분석에 속한 후보가 아닙니다.")
        return proposal

    @router.get("/api/signal-proposals", summary="완료된 분석의 전체 시그널 후보 목록 조회")
    def all_proposals(run_id: str | None = None) -> ProposalList:
        if run_id is not None:
            require_completed(run_id)
        return ProposalList(
            items=[
                proposal
                for proposal in store.list_proposals(run_id)
                if is_completed(proposal.run_id)
            ]
        )

    @router.get("/api/signal-proposals/{proposal_id}", summary="시그널 후보 상세 조회")
    def global_proposal_detail(proposal_id: str) -> Proposal:
        proposal = proposal_or_404(proposal_id)
        require_completed(proposal.run_id)
        return proposal

    @router.post("/api/signals", summary="선택한 후보 또는 직접 정의한 시그널 등록")
    def register(request: RegisterSignal | RegisterDefinedSignal, response: Response) -> Signal:
        trace_run_id = str(uuid4())
        response.headers["X-Langfuse-Trace-Id"] = trace_run_id.replace("-", "")
        if isinstance(request, RegisterDefinedSignal):
            try:
                return service.register_definition(
                    title=request.title,
                    description=request.description,
                    definition=request.definition,
                    start_at=request.start_at,
                    end_at=request.end_at,
                    trace_run_id=trace_run_id,
                )
            except MeasurementUnavailable:
                raise HTTPException(
                    422, "시그널 정의를 측정할 수 없어 등록하지 않았습니다."
                ) from None
        proposal = proposal_or_404(request.proposal_id)
        require_completed(proposal.run_id)
        response.headers["X-Langfuse-Trace-Id"] = LangfuseRunContext(
            proposal.run_id, "generic", "", tuple(proposal.definition.source_ids)
        ).trace_id
        try:
            return service.register_proposal(proposal, trace_run_id=trace_run_id)
        except ValueError:
            raise HTTPException(409, "검증된 측정값이 있는 후보만 등록할 수 있습니다.") from None

    @router.get("/api/signals", summary="등록된 시그널 목록 조회")
    def signals() -> SignalList:
        return SignalList(items=store.list_signals())

    @router.get("/api/signals/briefing", summary="메인 브리핑의 시그널 카드 목록과 지표 조회")
    def briefing(
        status: Literal["active", "paused", "archived", "all"] = Query(
            default="active", description="추적 상태 필터, all은 모든 상태",
        ),
        limit: int = Query(default=20, ge=1, le=100, description="페이지당 시그널 수"),
        offset: int = Query(default=0, ge=0, description="등록 역순 목록에서 건너뛸 시그널 수"),
    ) -> SignalBriefingList:
        total, rows = store.list_briefing_data(
            status=None if status == "all" else status, limit=limit, offset=offset,
        )
        next_offset = offset + len(rows)
        return SignalBriefingList(
            items=[briefing_card(signal, measurements) for signal, measurements in rows],
            total=total,
            limit=limit,
            offset=offset,
            next_offset=next_offset if next_offset < total else None,
        )

    @router.post("/api/signals/fast-forward", summary="등록 시그널을 다음 일자로 빨리감기 분석")
    def fast_forward(request: FastForwardRequest) -> FastForwardResult:
        try:
            return fast_forward_service.run(request)
        except KeyError:
            raise HTTPException(404, "시그널을 찾을 수 없습니다.") from None
        except FastForwardConflict as error:
            raise HTTPException(409, str(error)) from None
        except ScheduleBusy:
            raise HTTPException(409, "측정 실행 중입니다. 같은 request_id로 재시도할 수 있습니다.") from None

    @router.post("/api/signals/fast-forward/reset", summary="이력을 보관하고 빨리감기 시작일 재설정")
    def reset_fast_forward(request: FastForwardResetRequest) -> FastForwardResetResult:
        try:
            return reset_service.run(request)
        except KeyError:
            raise HTTPException(404, "시그널을 찾을 수 없습니다.") from None
        except MeasurementUnavailable as error:
            raise HTTPException(422, str(error)) from None
        except FastForwardConflict as error:
            raise HTTPException(409, str(error)) from None
        except ScheduleBusy:
            raise HTTPException(409, "측정 실행 중입니다. 같은 request_id로 재시도할 수 있습니다.") from None

    @router.get("/api/signals/{signal_id}", summary="등록된 시그널 정의 조회")
    def detail(signal_id: str) -> Signal:
        return signal_or_404(signal_id)

    @router.patch("/api/signals/{signal_id}", summary="시그널 추적 상태 변경")
    def update(signal_id: str, request: UpdateSignal) -> Signal:
        signal_or_404(signal_id)
        try:
            with schedules.lock(signal_id):
                return store.set_status(signal_id, request.status)
        except ScheduleBusy:
            raise HTTPException(409, "측정 실행 중에는 추적 상태를 변경할 수 없습니다.") from None

    @router.post(
        "/api/signals/{signal_id}/measurements", summary="고정 시그널 정의로 지정 기간 재측정"
    )
    def measure(signal_id: str, request: MeasurementRequest, response: Response) -> Measurement:
        signal = signal_or_404(signal_id)
        trace_run_id = str(uuid4())
        response.headers["X-Langfuse-Trace-Id"] = trace_run_id.replace("-", "")
        try:
            with schedules.lock(signal_id):
                return service.measure(
                    signal, start_at=request.start_at, end_at=request.end_at,
                    trace_run_id=trace_run_id,
                )
        except ScheduleBusy:
            raise HTTPException(409, "측정 실행 중입니다. 잠시 후 재시도할 수 있습니다.") from None

    @router.get(
        "/api/signals/{signal_id}/measurements", summary="시그널 측정 이력과 기간별 최신 값 조회"
    )
    def history(signal_id: str) -> MeasurementHistory:
        signal_or_404(signal_id)
        return history_response(store.list_measurements(signal_id))

    @router.get("/api/signals/{signal_id}/schedule", summary="시그널 일별 자동 측정 일정 조회")
    def schedule(signal_id: str) -> DailySchedule:
        signal_or_404(signal_id)
        return schedules.get(signal_id)

    @router.put("/api/signals/{signal_id}/schedule", summary="시그널 일별 자동 측정 일정 설정")
    def update_schedule(signal_id: str, request: ScheduleUpdate) -> DailySchedule:
        signal_or_404(signal_id)
        try:
            return schedules.update(signal_id, **request.model_dump())
        except ScheduleBusy:
            raise HTTPException(409, "측정 실행 중에는 일정을 변경할 수 없습니다.") from None

    @router.get("/api/signals/{signal_id}/daily-results", summary="시그널 일별 자동 실행과 측정 누적 조회")
    def daily_results(
        signal_id: str,
        limit: int = Query(default=30, ge=1, le=100),
        before: AwareDatetime | None = None,
    ) -> DailyResults:
        signal_or_404(signal_id)
        return schedules.results(signal_id, limit=limit, before=before)

    @router.get("/api/signals/{signal_id}/comparison", summary="시그널 두 기간의 지표 변화 비교")
    def comparison(
        signal_id: str,
        baseline_measurement_id: str | None = None,
        target_measurement_id: str | None = None,
    ) -> MeasurementComparison:
        signal_or_404(signal_id)
        if (baseline_measurement_id is None) != (target_measurement_id is None):
            raise HTTPException(422, "기준과 비교 측정 ID를 함께 지정하세요.")
        if baseline_measurement_id is not None:
            items = {m.measurement_id: m for m in store.list_measurements(signal_id)}
            if baseline_measurement_id not in items or target_measurement_id not in items:
                raise HTTPException(404, "이 시그널에 속한 측정값을 찾을 수 없습니다.")
            baseline, target = items[baseline_measurement_id], items[target_measurement_id]
        else:
            results = schedules.results(signal_id, limit=2).items
            target = results[0].measurement if results else None
            baseline = results[1].measurement if len(results) > 1 else None
        return compare_measurements(baseline, target)

    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(alert_router)
    return combined
