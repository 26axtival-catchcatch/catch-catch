"""FastAPI application factory for analysis runs and the mounted MCP surface."""

from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from pydantic import BaseModel, ConfigDict, Field

from customer_signal.agent.analysis_loop import AnalysisLoop
from customer_signal.agent.contracts import RunRequest
from customer_signal.agent.fixture import FixtureRunner
from customer_signal.agent.gemini import GeminiRunner
from customer_signal.agent.generic_fixture import GenericFixtureModel
from customer_signal.investigation.data import InvestigationData
from customer_signal.investigation.model import BedrockInvestigationModel, GeminiInvestigationModel
from customer_signal.investigation.runner import InvestigationRunner
from customer_signal.signals.api import create_router as create_signal_router
from customer_signal.signals.store import SignalStore
from customer_signal.signals.service import SignalService
from customer_signal.signals.scheduling import DailyScheduler, ScheduleStore
from customer_signal.signals.alert_recommendations import create_recommender
from customer_signal.analytics.executor import PrimitiveExecutor
from customer_signal.analytics.models import CustomerJourneyResult, EvidenceResult
from customer_signal.analytics.service import AnalyticsService
from customer_signal.config import Settings
from customer_signal.data.database import (
    SYNTHETIC_DATASET_VERSION,
    is_database_ready,
    seed_database,
)
from customer_signal.data.repository import DuckDBRepository
from customer_signal.data.source_registry import SourceRegistry
from customer_signal.domain.models import EvidenceRecord
from customer_signal.domain.sources import PublicSourceList, PublicSourceManifest
from customer_signal.journal.journal import EventJournal
from customer_signal.journal.journal import UnknownRunError as UnknownJournalRunError
from customer_signal.journal.sqlite import SQLiteEventJournal
from customer_signal.mcp_server import create_mcp_server
from customer_signal.packs.customer_signal import CustomerSignalPack
from customer_signal.packs.kernel import PackKernel
from customer_signal.packs.registry import AnalysisPackRegistry
from customer_signal.presentation.generic import GenericRunProjector
from customer_signal.presentation.intents import PresentationIntent
from customer_signal.presentation.projector import fold_intents
from customer_signal.onboarding.adapter import CompositeEvidenceProvider, load_onboarded_adapters
from customer_signal.runtime.coordinator import (
    RunCoordinator,
    RunNotCompletedError,
    RunResourceNotFoundError,
)
from customer_signal.runtime.artifact_store import (
    ArtifactNotFoundError,
    ArtifactStore,
    InvalidRunIdError,
)
from customer_signal.runtime.artifacts import ArtifactListResponse
from customer_signal.runtime.document_renderer import render_document, render_markdown_bytes
from customer_signal.runtime.events import RunEventEnvelope
from customer_signal.runtime.wire_projection import restore_wire_events
from customer_signal.runtime.run_store import (
    InvalidLastEventIdError,
    InvalidRunTransitionError,
    RequestedAgentMode,
    RunSnapshot,
    RunStore,
    UnknownRunError,
)
from customer_signal.synthetic.adapter import SyntheticDuckDBAdapter
from customer_signal.synthetic.generator import generate_dataset
from customer_signal.synthetic.manifest import synthetic_source_manifest


class RunAccepted(BaseModel):
    """Links returned immediately after a run is queued."""

    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str
    status_url: str
    events_url: str


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str = Field(min_length=1, max_length=1_000)


class PresentationReplay(BaseModel):
    """Presentation Intents recomputed from a Run's Canonical Run Events."""

    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str
    pack_id: str | None
    intents: list[PresentationIntent]


_BUILT_IN_SOURCE_IDS = (
    "search_history",
    "search_feedback",
    "digital_behavior",
    "subscription",
    "voc",
)
@dataclass(frozen=True, slots=True)
class ApiDependencies:
    """Injectable application services for deterministic tests and later runners."""

    store: RunStore
    coordinator: RunCoordinator
    mcp_server: FastMCP
    registry: SourceRegistry | None = None
    artifact_store: ArtifactStore | None = None
    source_ids: tuple[str, ...] = ()
    generic_default_mode: RequestedAgentMode = "fixture"
    journal: EventJournal | None = None
    packs: AnalysisPackRegistry | None = None
    refresh_sources: Callable[[], tuple[SourceRegistry, tuple[str, ...]]] | None = None
    signal_store: SignalStore | None = None


class _RepositoryEvidenceProvider:
    def __init__(self, repository: DuckDBRepository) -> None:
        self._repository = repository

    def get_evidence(
        self,
        allowed_evidence_ids: Sequence[str],
    ) -> list[EvidenceRecord]:
        return [
            record.model_copy(update={"raw_fields": {}})
            for record in self._repository.get_evidence(allowed_evidence_ids)
        ]


class _FunctionalFixtureModel(GenericFixtureModel):
    """Bind the three deterministic demo Plans to their authoritative sources."""

    async def create_plan(self, goal, manifests, *, validation_feedback=None):
        plan = await super().create_plan(
            goal,
            manifests,
            validation_feedback=validation_feedback,
        )
        scenario = goal.goal_id.removeprefix("goal-")
        scopes = {
            "negative": {
                "step-profile": ["search_feedback"],
                "step-negative-topic": ["search_feedback"],
            },
            "repeat": {
                "step-repeat-sequence": ["search_history", "voc"],
                "step-repeat-journey": ["search_history", "voc"],
                "step-repeat-evidence": ["search_history", "voc"],
            },
            "signup": {
                "step-signup-sequence": ["subscription"],
                "step-signup-segment": ["subscription"],
            },
        }.get(scenario, {})
        steps = []
        for step in plan.steps:
            parameters = step.parameters
            configured_sources = scopes.get(step.step_id)
            source_ids = step.source_ids
            if configured_sources is not None:
                source_ids = [
                    source_id
                    for source_id in configured_sources
                    if source_id in goal.source_ids
                ] or step.source_ids
            if step.step_id == "step-negative-topic":
                parameters = parameters.model_copy(
                    update={
                        "predicates": [
                            "outcome == 'negative'",
                            "topic == '요금제 변경'",
                        ]
                    }
                )
            steps.append(
                step.model_copy(
                    update={
                        "source_ids": source_ids,
                        "parameters": parameters,
                    }
                )
            )
        return plan.model_copy(update={"steps": steps})


def _default_dependencies(settings: Settings) -> ApiDependencies:
    dataset = generate_dataset()
    if not is_database_ready(settings.database_path):
        seed_database(settings.database_path, dataset)
    repository = DuckDBRepository(settings.database_path)
    analytics = AnalyticsService(repository)
    mcp_server = create_mcp_server(analytics)
    manifests = [
        synthetic_source_manifest(source_id, dataset.events) for source_id in _BUILT_IN_SOURCE_IDS
    ]
    adapters = [SyntheticDuckDBAdapter(repository, manifest) for manifest in manifests]
    onboarded = load_onboarded_adapters(settings.onboarded_sources_dir)
    evidence = _RepositoryEvidenceProvider(repository)
    registry = SourceRegistry(
        [*adapters, *onboarded],
        evidence=CompositeEvidenceProvider(evidence, onboarded) if onboarded else evidence,
    )
    def refresh_sources() -> tuple[SourceRegistry, tuple[str, ...]]:
        current = load_onboarded_adapters(settings.onboarded_sources_dir)
        fresh = SourceRegistry([*adapters, *current],
            evidence=CompositeEvidenceProvider(evidence, current) if current else evidence)
        return fresh, (*_BUILT_IN_SOURCE_IDS, *(a.describe().source_id for a in current))
    executor = PrimitiveExecutor(
        registry=registry,
        dataset_version=str(SYNTHETIC_DATASET_VERSION),
    )
    artifact_store = ArtifactStore.from_settings(settings)
    store = RunStore(artifact_store.list_artifacts())
    api_key = (
        settings.gemini_api_key.get_secret_value() if settings.gemini_api_key is not None else None
    )
    functional_model = _FunctionalFixtureModel()
    generic_fixture_loop = AnalysisLoop(
        model=functional_model,
        executor=executor,
        registry=registry,
    )
    signal_store = SignalStore(settings.artifact_directory / "signals.sqlite3")
    generic_gemini_loop = None
    if api_key and api_key.strip():
        generic_gemini_loop = InvestigationRunner(
            model=GeminiInvestigationModel(
                api_key=api_key,
                primary_model=settings.gemini_model,
                fallback_model=settings.gemini_fallback_model,
            ),
            data_factory=lambda request: InvestigationData.load(refresh_sources()[0], request),
            artifact_directory=settings.artifact_directory,
            signal_store=signal_store,
        )
    generic_bedrock_loop = None
    bedrock_key = settings.aws_bearer_token_bedrock
    # Explicit Bedrock mode also supports the SDK credential chain (EC2 IAM roles).
    if (bedrock_key and bedrock_key.get_secret_value().strip()) or settings.agent_mode == "bedrock":
        generic_bedrock_loop = InvestigationRunner(
            model=BedrockInvestigationModel(
                api_key=bedrock_key.get_secret_value() if bedrock_key else None,
                model=settings.bedrock_model,
                investigator_model=settings.bedrock_investigator_model,
                verifier_model=settings.bedrock_verifier_model,
                region=settings.aws_region,
            ),
            data_factory=lambda request: InvestigationData.load(refresh_sources()[0], request),
            artifact_directory=settings.artifact_directory,
            signal_store=signal_store,
        )
    customer_signal_pack = CustomerSignalPack(
        fixture_loop=generic_fixture_loop,
        gemini_loop=generic_gemini_loop,
        bedrock_loop=generic_bedrock_loop,
    )
    packs = AnalysisPackRegistry([customer_signal_pack])
    journal = SQLiteEventJournal(settings.resolved_journal_path)
    kernel = PackKernel(journal, timeout_seconds=None)
    coordinator = RunCoordinator(
        agent_mode=settings.agent_mode,
        fixture_runner=FixtureRunner(mcp_server),
        gemini_runner=GeminiRunner(
            api_key=api_key,
            mcp_url=f"http://{settings.api_host}:{settings.api_port}/mcp/",
            primary_model=settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
        ),
        analytics=analytics,
        store=store,
        kernel=kernel,
        packs=packs,
        artifact_store=artifact_store,
    )
    return ApiDependencies(
        store=store,
        coordinator=coordinator,
        mcp_server=mcp_server,
        registry=registry,
        artifact_store=artifact_store,
        source_ids=(
            *_BUILT_IN_SOURCE_IDS,
            *(adapter.describe().source_id for adapter in onboarded),
        ),
        generic_default_mode=settings.resolved_agent_mode,
        journal=journal,
        packs=packs,
        refresh_sources=refresh_sources,
        signal_store=signal_store,
    )


_OPENAPI_TAGS = [
    {"name": "system", "description": "서비스 상태 확인"},
    {"name": "sources", "description": "분석에 사용할 수 있는 공개 Source 목록"},
    {"name": "runs", "description": "분석 Run 생성, 상태 조회, SSE 이벤트, 후속 조회"},
    {"name": "signals", "description": "시그널 등록, 일별 측정, 임계점 추천과 알림 이벤트 폴링"},
    {"name": "run-artifacts", "description": "완료된 Run Artifact 조회와 다운로드"},
]


def create_app(
    settings: Settings | None = None,
    dependencies: ApiDependencies | None = None,
) -> FastAPI:
    """Build the complete ASGI app without import-time database writes."""

    resolved_settings = settings or Settings()
    resolved = dependencies or _default_dependencies(resolved_settings)
    mcp_http_app = resolved.mcp_server.http_app(path="/")

    signal_scheduler = None

    @asynccontextmanager
    async def api_lifespan(_app: FastAPI):
        if resolved.journal is not None:
            # The journal is the source of truth: rebuild replayable SSE
            # histories for restored Runs before serving traffic.
            await restore_wire_events(resolved.journal, resolved.store)
        scheduler_task = None
        if signal_scheduler is not None and resolved_settings.signal_scheduler_enabled:
            scheduler_task = asyncio.create_task(signal_scheduler.run(), name="daily-signals")
        try:
            yield {}
        finally:
            if scheduler_task is not None:
                signal_scheduler.stop()
                await scheduler_task
            await resolved.coordinator.close()
            journal_close = getattr(resolved.journal, "close", None)
            if journal_close is not None:
                await journal_close()

    app = FastAPI(
        title="Customer Signal API",
        version="0.1.0",
        description=(
            "합성 고객 신호 분석 데모의 Run API입니다. "
            "전체 엔드포인트 정리는 docs/api-endpoints.md 를 참고합니다. "
            "`/mcp` 경로에는 별도 MCP 서버가 mount 되어 있어 이 문서에는 나타나지 않습니다."
        ),
        openapi_tags=_OPENAPI_TAGS,
        lifespan=combine_lifespans(mcp_http_app.lifespan, api_lifespan),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Langfuse-Trace-Id"],
    )

    def snapshot_or_404(run_id: str) -> RunSnapshot:
        try:
            return resolved.store.get_snapshot(run_id)
        except UnknownRunError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error

    def artifact_or_404(run_id: str):
        if resolved.artifact_store is None:
            raise HTTPException(status_code=404, detail="Run Artifact not found")
        try:
            return resolved.artifact_store.load(run_id)
        except (InvalidRunIdError, ArtifactNotFoundError) as error:
            raise HTTPException(status_code=404, detail="Run Artifact not found") from error

    def event_cursor(
        run_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> int:
        if last_event_id is None:
            cursor = 0
        else:
            try:
                cursor = int(last_event_id)
            except ValueError as error:
                raise HTTPException(
                    status_code=400,
                    detail="Last-Event-ID must be a non-negative integer",
                ) from error
        try:
            resolved.store.validate_last_event_id(run_id, cursor)
        except UnknownRunError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except InvalidLastEventIdError as error:
            raise HTTPException(
                status_code=400,
                detail="Last-Event-ID must name an emitted event or zero",
            ) from error
        return cursor

    if resolved.signal_store is not None:
        def completed_signal_run(run_id: str) -> bool:
            # Persisted Artifact is the completion authority, including after restart.
            if resolved.artifact_store is None:
                return False
            try:
                return resolved.artifact_store.load(run_id).status == "completed"
            except (InvalidRunIdError, ArtifactNotFoundError):
                return False

        def signal_data(request: RunRequest):
            registry = resolved.refresh_sources()[0] if resolved.refresh_sources else resolved.registry
            if registry is None:
                raise ValueError("source registry unavailable")
            return InvestigationData.load(registry, request)

        signal_scheduler = DailyScheduler(
            ScheduleStore(resolved.signal_store),
            SignalService(store=resolved.signal_store, load_data=signal_data),
            poll_seconds=resolved_settings.signal_scheduler_poll_seconds,
        )
        app.state.signal_scheduler = signal_scheduler
        app.include_router(create_signal_router(
            store=resolved.signal_store, is_completed=completed_signal_run, load_data=signal_data,
            recommend=create_recommender(resolved_settings),
        ))

    @app.get("/health", tags=["system"], summary="서비스 상태 확인")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sources", tags=["sources"], summary="공개 Source 목록 조회")
    async def list_sources() -> PublicSourceList:
        if resolved.registry is None:
            return PublicSourceList(items=[])
        registry, source_ids = resolved.refresh_sources() if resolved.refresh_sources else (resolved.registry, resolved.source_ids)
        manifests = registry.manifests(source_ids)
        return PublicSourceList(
            items=[PublicSourceManifest.from_internal(item) for item in manifests]
        )

    @app.post(
        "/api/runs",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["runs"],
        summary="분석 Run 생성",
        description=(
            "Bedrock/Gemini는 스냅샷 전에 질문을 판정합니다. 모호하면 "
            "clarification_required로 답변을 기다리며, 범위 밖 요청은 input_out_of_scope, "
            "인젝션·권한 우회 요청은 input_unsafe, 판정 실패는 intake_failed 오류로 종료합니다. "
            "접수는 202이며 판정 결과는 Run 상태와 SSE로 확인합니다."
        ),
    )
    async def create_run(
        request: RunRequest,
        mode: RequestedAgentMode | None = Query(default=None),
    ) -> RunAccepted:
        if resolved.registry is not None:
            try:
                registry = resolved.refresh_sources()[0] if resolved.refresh_sources else resolved.registry
                registry.manifests(request.enabled_sources)
            except LookupError as error:
                raise HTTPException(
                    status_code=422,
                    detail="enabled_sources contains an unknown source",
                ) from error
        selected_mode = mode or resolved.generic_default_mode
        snapshot = resolved.coordinator.create_run(
            request,
            generic=True,
            mode=selected_mode,
        )
        status_url = f"/api/runs/{snapshot.run_id}"
        return RunAccepted(
            run_id=snapshot.run_id,
            status_url=status_url,
            events_url=f"{status_url}/events",
        )

    @app.post(
        "/api/runs/{run_id}/clarification",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["runs"],
        summary="Clarification 답변 제출",
        description=(
            "같은 Run의 확인 질문에 답합니다. Bedrock/Gemini는 이전 대화와 새 답변을 함께 "
            "다시 판정합니다. 모호하면 재질문하고 범위 밖 요청이나 인젝션은 차단합니다."
        ),
    )
    async def answer_clarification(
        run_id: str,
        answer: ClarificationAnswer,
    ) -> RunAccepted:
        try:
            snapshot = await resolved.coordinator.answer_clarification(
                run_id,
                answer.answer,
            )
        except UnknownRunError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except (InvalidRunTransitionError, ValueError) as error:
            raise HTTPException(
                status_code=409,
                detail="Run is not awaiting clarification",
            ) from error
        status_url = f"/api/runs/{snapshot.run_id}"
        return RunAccepted(
            run_id=snapshot.run_id,
            status_url=status_url,
            events_url=f"{status_url}/events",
        )

    @app.get("/api/runs/{run_id}", tags=["runs"], summary="Run 상태 조회")
    async def get_run(run_id: str) -> RunSnapshot:
        return snapshot_or_404(run_id)

    @app.get(
        "/api/runs/{run_id}/events",
        response_class=EventSourceResponse,
        tags=["runs"],
        summary="Run 이벤트 SSE 스트림",
        responses={200: {"model": RunEventEnvelope,
                         "description": "SSE의 각 data JSON 계약. agent_activity는 역할 토폴로지와 모델/도구 진행을 전달하며 message_kind로 대화 설명·요약을 구분합니다."}},
    )
    async def stream_run_events(
        run_id: str,
        cursor: int = Depends(event_cursor),
    ) -> AsyncIterator[ServerSentEvent]:
        async for event in resolved.store.stream_events(run_id, cursor):
            yield ServerSentEvent(
                id=str(event.id),
                event=event.type,
                data={
                    "run_id": run_id,
                    "type": event.type,
                    "payload": event.payload,
                },
            )

    @app.get(
        "/api/runs/{run_id}/presentation",
        tags=["runs"],
        summary="Run Presentation Intent 재생",
    )
    async def get_run_presentation(run_id: str) -> PresentationReplay:
        if resolved.journal is None:
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            parsed_run_id = UUID(run_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        try:
            events = [event async for event in resolved.journal.read(parsed_run_id)]
        except UnknownJournalRunError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        pack_id: str | None = events[0].pack.pack_id if events else None
        projector = GenericRunProjector()
        if pack_id is not None and resolved.packs is not None and pack_id in resolved.packs:
            pack_projector = getattr(resolved.packs.get(pack_id), "projector", None)
            if pack_projector is not None:
                projector = pack_projector
        return PresentationReplay(
            run_id=run_id,
            pack_id=pack_id,
            intents=fold_intents(projector, events),
        )

    @app.get(
        "/api/runs/{run_id}/customers/{customer_id}/journey",
        tags=["runs"],
        summary="고객 Journey 조회",
    )
    async def get_journey(run_id: str, customer_id: str) -> CustomerJourneyResult:
        try:
            return resolved.coordinator.get_journey(run_id, customer_id)
        except UnknownRunError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except RunResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run resource not found") from error
        except RunNotCompletedError as error:
            raise HTTPException(status_code=409, detail="Run is not completed") from error

    @app.get(
        "/api/runs/{run_id}/evidence/{evidence_id}",
        tags=["runs"],
        summary="마스킹 Evidence 조회",
    )
    async def get_evidence(run_id: str, evidence_id: str) -> EvidenceResult:
        try:
            return resolved.coordinator.get_evidence(run_id, evidence_id)
        except UnknownRunError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except RunResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run resource not found") from error
        except RunNotCompletedError as error:
            raise HTTPException(status_code=409, detail="Run is not completed") from error

    @app.get(
        "/api/run-artifacts",
        response_model=ArtifactListResponse,
        tags=["run-artifacts"],
        summary="Run Artifact 목록 조회",
    )
    async def list_run_artifacts() -> ArtifactListResponse:
        if resolved.artifact_store is None:
            return ArtifactListResponse(artifacts=[])
        return ArtifactListResponse(artifacts=resolved.artifact_store.list_summaries())

    @app.get(
        "/api/run-artifacts/{run_id}",
        tags=["run-artifacts"],
        summary="Run Artifact 단건 조회",
    )
    async def get_run_artifact(run_id: str):
        return artifact_or_404(run_id)

    @app.get(
        "/api/run-artifacts/{run_id}/document",
        tags=["run-artifacts"],
        summary="Run 문서 렌더링 조회",
    )
    async def get_run_document(run_id: str):
        return render_document(artifact_or_404(run_id))

    @app.get(
        "/api/run-artifacts/{run_id}/download.json",
        tags=["run-artifacts"],
        summary="Run Artifact JSON 다운로드",
    )
    async def download_run_json(run_id: str) -> Response:
        artifact = artifact_or_404(run_id)
        return Response(
            content=resolved.artifact_store.load_bytes(run_id),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{artifact.run_id}.json"'},
        )

    @app.get(
        "/api/run-artifacts/{run_id}/download.md",
        tags=["run-artifacts"],
        summary="Run 보고서 Markdown 다운로드",
    )
    async def download_run_markdown(run_id: str) -> Response:
        artifact = artifact_or_404(run_id)
        return Response(
            content=render_markdown_bytes(artifact),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{artifact.run_id}.md"'},
        )

    app.mount("/mcp", mcp_http_app)
    return app

__all__ = ["ApiDependencies", "RunAccepted", "create_app"]
