"""User-selected registration and fixed-definition measurement HTTP API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from customer_signal.observability.langfuse import LangfuseRunContext
from customer_signal.signals.contracts import Measurement, Proposal, Signal, SignalDefinition
from customer_signal.signals.service import MeasurementUnavailable, SignalService


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
    reasons = []
    if len(windows) < 2:
        reasons.append("비교할 관측 기간이 두 개 이상 필요합니다.")
    if any(m.status != "success" for m in windows):
        reasons.append("측정 불가 기간이 포함되어 있습니다. 0건으로 해석하지 마세요.")
    if len({(m.end_at - m.start_at).total_seconds() for m in windows}) > 1:
        reasons.append("관측 기간의 길이가 다릅니다.")
    if len({m.definition_fingerprint for m in windows}) > 1:
        reasons.append("지표 정의가 다릅니다.")
    if len({tuple(m.source_ids) for m in windows}) > 1:
        reasons.append("측정 Source 범위가 다릅니다.")
    if len({str(sorted(getattr(m, "source_versions", {}).items())) for m in windows}) > 1:
        reasons.append("Source 매핑 또는 스키마 버전이 다릅니다.")
    if any(a.end_at > b.start_at for a, b in zip(windows, windows[1:])):
        reasons.append("관측 기간이 겹칩니다.")
    return MeasurementHistory(
        items=items,
        latest_by_window=windows,
        comparable=not reasons,
        comparison_limitations=reasons,
    )


def create_router(*, store, is_completed: Callable[[str], bool], load_data: Callable) -> APIRouter:
    router = APIRouter(tags=["signals"])
    service = SignalService(store=store, load_data=load_data)

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

    @router.get("/api/signals/{signal_id}", summary="등록된 시그널 정의 조회")
    def detail(signal_id: str) -> Signal:
        return signal_or_404(signal_id)

    @router.patch("/api/signals/{signal_id}", summary="시그널 추적 상태 변경")
    def update(signal_id: str, request: UpdateSignal) -> Signal:
        signal_or_404(signal_id)
        return store.set_status(signal_id, request.status)

    @router.post(
        "/api/signals/{signal_id}/measurements", summary="고정 시그널 정의로 지정 기간 재측정"
    )
    def measure(signal_id: str, request: MeasurementRequest, response: Response) -> Measurement:
        signal = signal_or_404(signal_id)
        trace_run_id = str(uuid4())
        response.headers["X-Langfuse-Trace-Id"] = trace_run_id.replace("-", "")
        return service.measure(
            signal, start_at=request.start_at, end_at=request.end_at, trace_run_id=trace_run_id
        )

    @router.get(
        "/api/signals/{signal_id}/measurements", summary="시그널 측정 이력과 기간별 최신 값 조회"
    )
    def history(signal_id: str) -> MeasurementHistory:
        signal_or_404(signal_id)
        return history_response(store.list_measurements(signal_id))

    return router
