"""Stable autonomous exploration Tool surface."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic import TypeAdapter

from customer_signal.data.database import seed_database
from customer_signal.data.source_registry import SourceRegistry
from customer_signal.data.repository import DuckDBRepository
from customer_signal.domain.models import SyntheticDataset
from customer_signal.domain.sources import DimensionDescriptor
from customer_signal.exploration.contracts import ExplorationSourceScope
from customer_signal.exploration.cursor import CursorCodec, canonical_json
from customer_signal.exploration.materialization import (
    RunMaterializationStore,
    StaleSnapshotReferenceError,
    WorkEvent,
)
from customer_signal.exploration.reader import DataSpaceReader, RetryablePageError
from customer_signal.exploration.tool_contracts import (
    AnalyzeEventSequencesInput,
    ComparisonPredicate,
    CountMetric,
    EvidenceSelection,
    ExplorationFieldRef,
    ExplorationTimeRange,
    FunnelInput,
    InspectFieldsInput,
    InspectSourcesInput,
    InspectValuesInput,
    MembershipPredicate,
    NumericMetric,
    PublicExplorationEvidenceEvent,
    ReadEventEvidenceInput,
    RatioMetric,
    RepetitionInput,
    RepetitionTarget,
    SequenceInput,
    SequenceStep,
    SummarizeEventsInput,
)
from customer_signal.exploration.tools import ExplorationTools, exploration_tool_json_schema
from customer_signal.onboarding.adapter import CompositeEvidenceProvider, load_onboarded_adapters
from customer_signal.synthetic.adapter import SyntheticDuckDBAdapter
from customer_signal.synthetic.manifest import synthetic_source_manifest


SEED_ROOT = Path("data/seeding/hackathon-2week/onboarded-sources")
SOURCE_IDS = (
    "hackathon_app_behavior",
    "hackathon_billing_profile",
    "hackathon_search_feedback",
    "hackathon_search_history",
    "hackathon_vas_subscription",
    "hackathon_voc",
    "hackathon_roaming_usage",
)
TIME_RANGE = ExplorationTimeRange(
    start_at=datetime.fromisoformat("2026-09-04T00:00:00+09:00"),
    end_at=datetime.fromisoformat("2026-09-18T00:00:00+09:00"),
)


class _RetryingPagedAdapter:
    def __init__(self, base: SyntheticDuckDBAdapter, *, fail_on_event_page: int) -> None:
        self._base = base
        self._fail_on_event_page = fail_on_event_page
        self._event_page_calls = 0

    def describe(self):
        return self._base.describe()

    def snapshot_token(self) -> str:
        return self._base.snapshot_token()

    def load_event_page(self, request):
        self._event_page_calls += 1
        if self._event_page_calls == self._fail_on_event_page:
            raise RetryablePageError("temporary source page interruption")
        return self._base.load_event_page(request)

    def load_identity_page(self, request):
        return self._base.load_identity_page(request)

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        return self._base.get_evidence(allowed_evidence_ids)

    def arm_after_event_pages(self, page_count: int) -> None:
        if page_count < 1:
            raise ValueError("page_count must be positive")
        self._fail_on_event_page = self._event_page_calls + page_count


class _ManifestOverrideAdapter:
    def __init__(self, base: SyntheticDuckDBAdapter, *, manifest) -> None:
        self._base = base
        self._manifest = manifest

    def describe(self):
        return self._manifest

    def snapshot_token(self) -> str:
        return self._base.snapshot_token()

    def load_event_page(self, request):
        return self._base.load_event_page(request)

    def load_identity_page(self, request):
        return self._base.load_identity_page(request)

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        return self._base.get_evidence(allowed_evidence_ids)


class _ExternallyMutablePagedAdapter:
    def __init__(self, base: SyntheticDuckDBAdapter) -> None:
        self._base = base
        self._version = 0

    def mutate(self) -> None:
        self._version += 1

    def describe(self):
        return self._base.describe()

    def snapshot_token(self) -> str:
        return f"{self._base.snapshot_token()}:{self._version}"

    def load_event_page(self, request):
        return self._base.load_event_page(request)

    def load_identity_page(self, request):
        return self._base.load_identity_page(request)

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        return self._base.get_evidence(allowed_evidence_ids)


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory) -> ExplorationTools:
    adapters = load_onboarded_adapters(SEED_ROOT)
    registry = SourceRegistry(adapters, CompositeEvidenceProvider(None, adapters))
    scope = ExplorationSourceScope(
        source_ids=SOURCE_IDS,
        start_at=TIME_RANGE.start_at,
        end_at=TIME_RANGE.end_at,
        native_page_size=200,
    )
    store = RunMaterializationStore(tmp_path_factory.mktemp("tools"), run_id="tool-run")
    reader = DataSpaceReader(
        registry=registry,
        prepared_sources=registry.prepare_paged_sources(scope),
        authorized_scope=scope,
        cursor_codec=CursorCodec(b"tool-secret" * 4),
        materializations=store,
    )
    return ExplorationTools(reader=reader, materializations=store)


def _exhaust(method, request):
    items = []
    response = method(request)
    while True:
        assert response.status == "success"
        items.extend(response.result.items)
        if not response.page.has_more:
            assert response.page.next_cursor is None
            return items, response
        assert response.page.next_cursor is not None
        request = request.model_copy(update={"cursor": response.page.next_cursor})
        response = method(request)


def _interruptible_search_tools(
    *,
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
    run_id: str,
) -> tuple[ExplorationTools, _RetryingPagedAdapter, ExplorationSourceScope]:
    source_id = "search_history"
    events = [event for event in synthetic_dataset.events if event.source_id == source_id]
    base = SyntheticDuckDBAdapter(
        repository, synthetic_source_manifest(source_id, synthetic_dataset.events)
    )
    adapter = _RetryingPagedAdapter(base, fail_on_event_page=10**9)
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=(source_id,),
        start_at=min(event.occurred_at for event in events),
        end_at=max(event.occurred_at for event in events) + timedelta(microseconds=1),
        native_page_size=5,
    )
    store = RunMaterializationStore(tmp_path / run_id, run_id=run_id)
    tools = ExplorationTools(
        reader=DataSpaceReader(
            registry=registry,
            prepared_sources=registry.prepare_paged_sources(scope),
            authorized_scope=scope,
            cursor_codec=CursorCodec((f"{run_id}-cursor-secret-" * 4).encode()),
            materializations=store,
        ),
        materializations=store,
    )
    return tools, adapter, scope


def test_tool_schema_is_stable_and_strict() -> None:
    before = exploration_tool_json_schema()
    after = exploration_tool_json_schema()
    assert before == after
    assert set(before) == {
        "inspect_data_space",
        "summarize_events",
        "analyze_event_sequences",
        "read_event_evidence",
    }
    with pytest.raises(ValidationError):
        InspectSourcesInput(view="sources", page_size=10, invented=True)


def test_gemini_json_decoded_arguments_reach_every_tool_variant(
    tools: ExplorationTools,
) -> None:
    source_id = "hackathon_voc"
    field = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    inspect_requests = (
        InspectSourcesInput(view="sources", source_ids=(source_id,), page_size=10),
        InspectFieldsInput(view="fields", source_ids=(source_id,), page_size=10),
        InspectValuesInput(
            view="values",
            source_ids=(source_id,),
            field=field,
            predicates=(),
            page_size=10,
        ),
    )
    for request in inspect_requests:
        response = tools.inspect_data_space(request.model_dump(mode="json"))
        assert response.status == "success"

    summary = SummarizeEventsInput(
        source_ids=(source_id,),
        time_range=TIME_RANGE,
        predicates=(),
        group_by=(field,),
        metrics=(CountMetric(kind="count", operation="event_count"),),
        page_size=10,
    )
    assert tools.summarize_events(summary.model_dump(mode="json")).status == "success"

    step = SequenceStep(step_id="voc", source_ids=(source_id,), event_predicates=())
    steps = (step, step.model_copy(update={"step_id": "voc_again"}))
    sequence_requests = (
        RepetitionInput(
            mode="repetition",
            source_ids=(source_id,),
            time_range=TIME_RANGE,
            target=RepetitionTarget(
                event_predicates=(),
                grouping_fields=(),
                min_occurrences=2,
                max_gap_minutes=10_080,
            ),
            group_by=(),
            page_size=10,
        ),
        SequenceInput(
            mode="sequence",
            source_ids=(source_id,),
            time_range=TIME_RANGE,
            steps=steps,
            max_total_span_minutes=10_080,
            group_by=(),
            page_size=10,
        ),
        FunnelInput(
            mode="funnel",
            source_ids=(source_id,),
            time_range=TIME_RANGE,
            steps=steps,
            max_total_span_minutes=10_080,
            group_by=(),
            page_size=10,
        ),
    )
    for request in sequence_requests:
        response = tools.analyze_event_sequences(request.model_dump(mode="json"))
        assert response.status == "success"

    parent = tools.analyze_event_sequences(sequence_requests[-1])
    assert parent.result.result_ref is not None
    evidence = ReadEventEvidenceInput(
        parent_result_ref=parent.result.result_ref,
        selection=EvidenceSelection(
            strategy="representative",
            customer_refs=(),
            max_customers=1,
            events_before_match=0,
            events_after_match=0,
        ),
        include_fields=(),
        page_size=10,
    )
    assert (
        tools.read_event_evidence(evidence.model_dump(mode="json")).status
        == "success"
    )

    loose = summary.model_dump(mode="json")
    loose["page_size"] = "10"
    assert tools.summarize_events(loose).status == "error"


def test_tool_schema_stays_identical_when_registry_adds_a_real_dynamic_field(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    before = canonical_json(exploration_tool_json_schema())
    source_id = "search_history"
    source_events = [
        event for event in synthetic_dataset.events if event.source_id == source_id
    ]
    base_manifest = synthetic_source_manifest(source_id, synthetic_dataset.events)
    dynamic_manifest = base_manifest.model_copy(
        update={
            "dimensions": {
                **base_manifest.dimensions,
                "new_unknown_dimension": DimensionDescriptor(
                    semantic_type="category",
                    description="Dynamically registered category.",
                    pii_classification="none",
                    allowed_values=frozenset({"alpha", "beta"}),
                ),
            }
        }
    )
    base = SyntheticDuckDBAdapter(repository, base_manifest)
    adapter = _ManifestOverrideAdapter(base, manifest=dynamic_manifest)
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=(source_id,),
        start_at=min(event.occurred_at for event in source_events),
        end_at=max(event.occurred_at for event in source_events)
        + timedelta(microseconds=1),
        native_page_size=17,
    )
    store = RunMaterializationStore(tmp_path / "dynamic", run_id="dynamic-run")
    dynamic_tools = ExplorationTools(
        reader=DataSpaceReader(
            registry=registry,
            prepared_sources=registry.prepare_paged_sources(scope),
            authorized_scope=scope,
            cursor_codec=CursorCodec(b"dynamic-cursor-secret" * 2),
            materializations=store,
        ),
        materializations=store,
    )

    fields, response = _exhaust(
        dynamic_tools.inspect_data_space,
        InspectFieldsInput(view="fields", source_ids=(source_id,), page_size=2),
    )

    assert response.page.scan_complete is True
    assert any(item.name == "new_unknown_dimension" for item in fields)
    assert canonical_json(exploration_tool_json_schema()) == before
    store.dispose()


def test_sources_and_fields_catalog_are_neutral_and_exhaustible(tools: ExplorationTools) -> None:
    sources, source_last = _exhaust(
        tools.inspect_data_space,
        InspectSourcesInput(view="sources", source_ids=(), page_size=2),
    )
    fields, field_last = _exhaust(
        tools.inspect_data_space,
        InspectFieldsInput(view="fields", source_ids=SOURCE_IDS, page_size=3),
    )
    serialized = " ".join(str(item.model_dump(mode="json")) for item in [*sources, *fields])

    assert {item.source_id for item in sources} == set(SOURCE_IDS)
    assert {item.source_id: item.row_count for item in sources} == {
        "hackathon_app_behavior": 9_250,
        "hackathon_billing_profile": 1_550,
        "hackathon_search_feedback": 339,
        "hackathon_search_history": 1_540,
        "hackathon_vas_subscription": 2_070,
        "hackathon_voc": 348,
        "hackathon_roaming_usage": 280,
    }
    source_by_id = {item.source_id: item for item in sources}
    search = source_by_id["hackathon_search_history"]
    assert search.event_types == ("search",)
    assert search.actions == ("repeat_search", "search")
    assert search.topics == ("부가서비스 조회/해지", "소액결제 한도 변경", "해외 로밍 이용")
    assert search.outcomes == ("completed", "failed")
    assert all(item.event_types for item in sources)
    assert all(item.actions for item in sources)
    assert all(item.topics for item in sources)
    assert all(item.outcomes for item in sources)
    assert all(item.vocabulary_limit == 64 for item in sources)
    assert all(item.truncated_fields == () for item in sources)
    assert all("view=values" in item.vocabulary_limitation for item in sources)
    assert any(item.name == "page_stay_seconds" for item in fields)
    session = next(item for item in fields if item.name == "session_id")
    assert session.value_access == "cardinality_only"
    assert session.data_type == "string"
    for prohibited in (
        "개선 전후",
        "개선안 노출",
        "앱 실패 이후",
        "장기 가입",
        "합성",
        "daily_kpis",
        "baseline",
        "intervention",
    ):
        assert prohibited.casefold() not in serialized.casefold()
    assert source_last.page.scan_complete is True
    assert field_last.page.scan_complete is True


def test_occurred_at_is_filterable_but_not_exactly_enumerable_or_groupable(
    tools: ExplorationTools,
) -> None:
    source_id = "hackathon_voc"
    fields, _ = _exhaust(
        tools.inspect_data_space,
        InspectFieldsInput(view="fields", source_ids=(source_id,), page_size=200),
    )
    occurred_at = next(
        item
        for item in fields
        if item.scope == "canonical" and item.name == "occurred_at"
    )
    assert occurred_at.value_access == "cardinality_only"
    field = ExplorationFieldRef(scope="canonical", name="occurred_at", source_id=None)

    values = tools.inspect_data_space(
        InspectValuesInput(
            view="values",
            source_ids=(source_id,),
            field=field,
            predicates=(),
        )
    )
    assert values.status == "error"
    assert values.error is not None
    assert "time_bucket" in values.error.message

    grouped = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=(source_id,),
            time_range=TIME_RANGE,
            predicates=(),
            group_by=(field,),
            metrics=(CountMetric(kind="count", operation="event_count"),),
        )
    )
    assert grouped.status == "error"
    assert grouped.error is not None
    assert "time_bucket" in grouped.error.message

    daily = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=(source_id,),
            time_range=TIME_RANGE,
            predicates=(
                ComparisonPredicate(
                    kind="comparison",
                    field=field,
                    operator="gte",
                    value=TIME_RANGE.start_at.isoformat(),
                ),
            ),
            group_by=(),
            metrics=(CountMetric(kind="count", operation="event_count"),),
            time_bucket="day",
        )
    )
    assert daily.status == "success"
    assert daily.result.items


def test_values_and_summary_scan_all_input_before_result_paging(
    tools: ExplorationTools,
) -> None:
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    values, _ = _exhaust(
        tools.inspect_data_space,
        InspectValuesInput(
            view="values",
            source_ids=SOURCE_IDS,
            field=topic,
            predicates=(),
            page_size=2,
        ),
    )
    assert any("vas" in str(item.value).casefold() for item in values)

    first = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("hackathon_app_behavior",),
            time_range=TIME_RANGE,
            predicates=(),
            group_by=(topic,),
            metrics=(CountMetric(kind="count", operation="event_count"),),
            time_bucket="day",
            page_size=2,
        )
    )
    assert first.status == "success"
    assert first.page.scan_complete is True
    assert first.page.matched_count is not None
    assert first.page.matched_count > len(first.result.items)
    assert first.page.has_more is True


def test_numeric_and_ratio_metrics_use_the_full_scan_and_report_zero_denominator(
    tools: ExplorationTools,
) -> None:
    amount = ExplorationFieldRef(
        scope="measure",
        name="micropayment_amount_krw",
        source_id="hackathon_billing_profile",
    )
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    response = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("hackathon_billing_profile",),
            time_range=TIME_RANGE,
            predicates=(),
            group_by=(),
            metrics=(
                NumericMetric(kind="numeric", operation="sum", field=amount),
                NumericMetric(kind="numeric", operation="average", field=amount),
                NumericMetric(kind="numeric", operation="minimum", field=amount),
                NumericMetric(kind="numeric", operation="maximum", field=amount),
                RatioMetric(
                    kind="ratio",
                    basis="events",
                    numerator_predicates=(),
                    denominator_predicates=(
                        ComparisonPredicate(
                            kind="comparison",
                            field=topic,
                            operator="eq",
                            value="5G 스탠다드",
                        ),
                    ),
                    unit="fraction",
                ),
                RatioMetric(
                    kind="ratio",
                    basis="distinct_customers",
                    numerator_predicates=(),
                    denominator_predicates=(
                        ComparisonPredicate(
                            kind="comparison",
                            field=topic,
                            operator="eq",
                            value="not-a-seeded-topic",
                        ),
                    ),
                    unit="percent",
                ),
            ),
            page_size=10,
        )
    )

    assert response.status == "success"
    assert response.page.scan_complete is True
    assert response.page.matched_count == 1
    summary = response.result.items[0]
    metrics = {metric.name: metric for metric in summary.metrics}
    total = metrics["sum:hackathon_billing_profile.micropayment_amount_krw"].value
    average = metrics[
        "average:hackathon_billing_profile.micropayment_amount_krw"
    ].value
    minimum = metrics[
        "minimum:hackathon_billing_profile.micropayment_amount_krw"
    ].value
    maximum = metrics[
        "maximum:hackathon_billing_profile.micropayment_amount_krw"
    ].value
    assert total == pytest.approx(average * 1_550)
    assert minimum <= average <= maximum
    assert metrics["ratio_5"].value == 1.0
    assert metrics["ratio_6"].value is None
    assert metrics["ratio_6"].limitation == "ratio denominator is zero"


def test_derived_cursor_is_bound_to_query(tools: ExplorationTools) -> None:
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    original = SummarizeEventsInput(
        source_ids=("hackathon_app_behavior",),
        time_range=TIME_RANGE,
        predicates=(),
        group_by=(topic,),
        metrics=(CountMetric(kind="count", operation="event_count"),),
        time_bucket="day",
        page_size=1,
    )
    first = tools.summarize_events(original)
    assert first.page.next_cursor
    changed = original.model_copy(
        update={
            "predicates": (
                ComparisonPredicate(
                    kind="comparison",
                    field=topic,
                    operator="eq",
                    value="payment",
                ),
            ),
            "cursor": first.page.next_cursor,
        }
    )
    error = tools.summarize_events(changed)
    assert error.status == "error"
    assert error.error is not None
    assert error.error.category == "validation"
    assert "query fingerprint" in error.error.message


def test_non_selected_prepared_source_change_invalidates_calculation_and_page(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    source_ids = ("search_history", "voc")
    field = ExplorationFieldRef(scope="canonical", name="action", source_id=None)

    def build(run_id: str):
        search = SyntheticDuckDBAdapter(
            repository,
            synthetic_source_manifest("search_history", synthetic_dataset.events),
        )
        voc = _ExternallyMutablePagedAdapter(
            SyntheticDuckDBAdapter(
                repository,
                synthetic_source_manifest("voc", synthetic_dataset.events),
            )
        )
        registry = SourceRegistry([search, voc], evidence=search)
        selected = [
            event for event in synthetic_dataset.events if event.source_id in source_ids
        ]
        scope = ExplorationSourceScope(
            source_ids=source_ids,
            start_at=min(event.occurred_at for event in selected),
            end_at=max(event.occurred_at for event in selected)
            + timedelta(microseconds=1),
            native_page_size=5,
        )
        store = RunMaterializationStore(tmp_path / run_id, run_id=run_id)
        instance = ExplorationTools(
            reader=DataSpaceReader(
                registry=registry,
                prepared_sources=registry.prepare_paged_sources(scope),
                authorized_scope=scope,
                cursor_codec=CursorCodec((f"{run_id}-secret" * 4).encode()),
                materializations=store,
            ),
            materializations=store,
        )
        request = InspectValuesInput(
            view="values",
            source_ids=("search_history",),
            field=field,
            predicates=(),
            page_size=1,
        )
        return instance, voc, store, request

    calculation_tools, calculation_voc, calculation_store, request = build(
        "full-barrier-calculation"
    )
    calculation_voc.mutate()
    calculation = calculation_tools.inspect_data_space(request)
    assert calculation.status == "error"
    assert calculation_store.generation == 1
    assert calculation_tools.ledger.generation == 1
    assert calculation_tools.ledger.catalog_complete is False
    assert calculation_tools.ledger.public_snapshot().completed_query_refs == ()
    calculation_store.dispose()

    page_tools, page_voc, page_store, request = build("full-barrier-page")
    _exhaust(
        page_tools.inspect_data_space,
        InspectSourcesInput(view="sources", source_ids=(), page_size=10),
    )
    _exhaust(
        page_tools.inspect_data_space,
        InspectFieldsInput(view="fields", source_ids=source_ids, page_size=50),
    )
    assert page_tools.ledger.catalog_complete is True
    first = page_tools.inspect_data_space(request)
    assert first.status == "success"
    assert first.page.next_cursor is not None
    assert first.result.query_ref is not None
    old_query_ref = first.result.query_ref
    page_voc.mutate()
    second = page_tools.inspect_data_space(
        request.model_copy(update={"cursor": first.page.next_cursor})
    )
    assert second.status == "error"
    assert page_store.generation == 1
    assert page_tools.ledger.generation == 1
    assert page_tools.ledger.catalog_complete is False
    assert page_tools.ledger.public_snapshot().completed_query_refs == ()
    with pytest.raises(StaleSnapshotReferenceError):
        page_tools.ledger.require_query(old_query_ref)
    repeated = page_tools.inspect_data_space(
        request.model_copy(update={"cursor": first.page.next_cursor})
    )
    assert repeated.status == "error"
    assert page_store.generation == 1
    assert page_tools.ledger.generation == 1
    page_store.dispose()


def test_derived_cursor_is_bound_to_stored_query_and_result_refs(
    tools: ExplorationTools,
) -> None:
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    request = SummarizeEventsInput(
        source_ids=("hackathon_app_behavior",),
        time_range=TIME_RANGE,
        predicates=(),
        group_by=(topic,),
        metrics=(CountMetric(kind="count", operation="event_count"),),
        time_bucket="day",
        page_size=1,
    )
    first = tools.summarize_events(request)
    assert first.page.next_cursor is not None
    payload = tools.reader.cursor_codec.decode(first.page.next_cursor)

    wrong_query = tools.reader.cursor_codec.encode(
        payload.model_copy(
            update={"query_ref": tools.materializations.make_ref("query")}
        )
    )
    query_error = tools.summarize_events(
        request.model_copy(update={"cursor": wrong_query})
    )
    assert query_error.status == "error"
    assert query_error.error is not None
    assert "query_ref" in query_error.error.message

    unknown_result = tools.reader.cursor_codec.encode(
        payload.model_copy(
            update={"result_ref": tools.materializations.make_ref("result")}
        )
    )
    result_error = tools.summarize_events(
        request.model_copy(update={"cursor": unknown_result})
    )
    assert result_error.status == "error"
    assert result_error.error is not None
    assert "result reference is unknown" in result_error.error.message


def test_dynamic_dimension_values_have_complete_seeded_counts(
    tools: ExplorationTools,
) -> None:
    abtest = ExplorationFieldRef(
        scope="dimension", name="abtest_id", source_id="hackathon_app_behavior"
    )
    items, last = _exhaust(
        tools.inspect_data_space,
        InspectValuesInput(
            view="values",
            source_ids=("hackathon_app_behavior",),
            field=abtest,
            predicates=(),
            page_size=2,
        ),
    )
    assert {item.value: item.count for item in items} == {
        "CONTROL": 7_372,
        "PAYMENT_CONSENT_V1": 1_164,
        "VAS_AI_CTA_V1": 410,
        "ROAMING_PLAN_GUIDE_V1": 304,
    }
    assert last.page.has_more is False


def test_source_bound_negative_predicate_never_matches_another_source(
    tools: ExplorationTools,
) -> None:
    abtest = ExplorationFieldRef(
        scope="dimension", name="abtest_id", source_id="hackathon_app_behavior"
    )
    response = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("hackathon_app_behavior", "hackathon_voc"),
            time_range=TIME_RANGE,
            predicates=(
                MembershipPredicate(
                    kind="membership",
                    field=abtest,
                    operator="not_in",
                    values=("CONTROL",),
                ),
            ),
            group_by=(),
            metrics=(CountMetric(kind="count", operation="event_count"),),
            page_size=10,
        )
    )
    assert response.status == "success"
    summary = response.result.items[0]
    assert summary.item_kind == "summary"
    assert summary.metrics[0].value == 1_878


def test_identifier_dimension_value_enumeration_is_denied(tools: ExplorationTools) -> None:
    response = tools.inspect_data_space(
        InspectValuesInput(
            view="values",
            source_ids=("hackathon_app_behavior",),
            field=ExplorationFieldRef(
                scope="dimension",
                name="session_id",
                source_id="hackathon_app_behavior",
            ),
            predicates=(),
        )
    )
    assert response.status == "error"
    assert response.error is not None
    assert response.error.category == "permission"

def test_free_text_dimension_is_catalogued_but_never_exported_as_values(
    tools: ExplorationTools,
) -> None:
    fields, _ = _exhaust(
        tools.inspect_data_space,
        InspectFieldsInput(
            view="fields",
            source_ids=("hackathon_search_feedback",),
            page_size=50,
        ),
    )
    reason = next(item for item in fields if item.name == "reason")
    assert reason.value_access == "cardinality_only"

    response = tools.inspect_data_space(
        InspectValuesInput(
            view="values",
            source_ids=("hackathon_search_feedback",),
            field=ExplorationFieldRef(
                scope="dimension",
                name="reason",
                source_id="hackathon_search_feedback",
            ),
            predicates=(),
        )
    )
    assert response.status == "error"
    assert response.error is not None
    assert response.error.category == "permission"

    reason_ref = ExplorationFieldRef(
        scope="dimension",
        name="reason",
        source_id="hackathon_search_feedback",
    )
    grouped = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("hackathon_search_feedback",),
            time_range=TIME_RANGE,
            predicates=(),
            group_by=(reason_ref,),
            metrics=(CountMetric(kind="count", operation="event_count"),),
        )
    )
    filtered = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("hackathon_search_feedback",),
            time_range=TIME_RANGE,
            predicates=(
                ComparisonPredicate(
                    kind="comparison",
                    field=reason_ref,
                    operator="eq",
                    value="raw feedback text",
                ),
            ),
            group_by=(),
            metrics=(CountMetric(kind="count", operation="event_count"),),
        )
    )
    for denied in (grouped, filtered):
        assert denied.status == "error"
        assert denied.error is not None
        assert denied.error.category == "permission"


def test_sequence_steps_require_strictly_later_timestamps(tools: ExplorationTools) -> None:
    start = TIME_RANGE.start_at
    request = SequenceInput(
        mode="sequence",
        source_ids=("hackathon_search_history", "hackathon_voc"),
        time_range=TIME_RANGE,
        steps=(
            SequenceStep(
                step_id="search_twice",
                source_ids=("hackathon_search_history",),
                event_predicates=(),
                min_occurrences=2,
            ),
            SequenceStep(
                step_id="voc",
                source_ids=("hackathon_voc",),
                event_predicates=(),
                min_occurrences=1,
            ),
        ),
        max_total_span_minutes=60,
        group_by=(),
    )

    def event(source_id: str, event_id: str, occurred_at: datetime) -> WorkEvent:
        return WorkEvent(
            canonical_customer_id="customer-1",
            occurred_at=occurred_at,
            source_id=source_id,
            event_id=event_id,
            evidence_id=f"evidence-{event_id}",
            event_type="test_event",
            action="test",
            topic="test",
            outcome="test",
            dimensions={},
            measures={},
        )

    first = event("hackathon_search_history", "search-1", start)
    completion = event(
        "hackathon_search_history", "search-2", start + timedelta(minutes=1)
    )
    same_time_next = event("hackathon_voc", "voc-1", completion.occurred_at)
    later_next = event(
        "hackathon_voc", "voc-2", completion.occurred_at + timedelta(microseconds=1)
    )
    query_ref = tools.materializations.make_ref("query")

    assert (
        tools._ordered_sequence_match(
            query_ref,
            "customer-1",
            [first, completion, same_time_next],
            request,
        )
        is None
    )

    match = tools._ordered_sequence_match(
        query_ref,
        "customer-1",
        [first, completion, same_time_next, later_next],
        request,
    )
    assert match is not None
    assert match.item.first_match_at == first.occurred_at
    assert match.item.last_match_at == later_next.occurred_at

    overlapping = request.model_copy(
        update={
            "steps": (
                request.steps[0].model_copy(update={"min_occurrences": 1}),
                request.steps[0].model_copy(
                    update={"step_id": "same_event_again", "min_occurrences": 1}
                ),
            )
        }
    )
    assert (
        tools._ordered_sequence_match(
            query_ref,
            "customer-1",
            [first],
            overlapping,
        )
        is None
    )


def test_retryable_scan_interruption_returns_real_partial_tool_result(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    source_id = "search_history"
    events = [event for event in synthetic_dataset.events if event.source_id == source_id]
    base = SyntheticDuckDBAdapter(
        repository, synthetic_source_manifest(source_id, synthetic_dataset.events)
    )
    adapter = _RetryingPagedAdapter(base, fail_on_event_page=2)
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=(source_id,),
        start_at=min(event.occurred_at for event in events),
        end_at=max(event.occurred_at for event in events) + timedelta(microseconds=1),
        native_page_size=5,
    )
    store = RunMaterializationStore(tmp_path / "partial", run_id="partial-run")
    partial_tools = ExplorationTools(
        reader=DataSpaceReader(
            registry=registry,
            prepared_sources=registry.prepare_paged_sources(scope),
            authorized_scope=scope,
            cursor_codec=CursorCodec(b"partial-cursor-secret" * 2),
            materializations=store,
        ),
        materializations=store,
    )
    response = partial_tools.summarize_events(
        SummarizeEventsInput(
            source_ids=(source_id,),
            time_range=ExplorationTimeRange(
                start_at=scope.start_at,
                end_at=scope.end_at,
            ),
            predicates=(),
            group_by=(
                ExplorationFieldRef(scope="canonical", name="topic", source_id=None),
            ),
            metrics=(CountMetric(kind="count", operation="event_count"),),
            page_size=50,
        )
    )

    assert response.status == "partial"
    assert response.result.items
    assert response.page.returned_count == len(response.result.items)
    assert response.page.matched_count is None
    assert response.page.scan_complete is False
    assert response.error is None
    assert response.partial is not None
    assert response.partial.is_retryable is True
    assert response.partial.remaining_branches == (source_id,)
    assert response.partial.retry_action == "restart_query_without_cursor"
    assert response.result.result_ref is not None
    assert store.read_result(response.result.result_ref).scan_complete is False
    store.dispose()


def test_partial_result_marks_every_unfinished_source_branch(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    source_ids = ("search_history", "voc")
    manifests = {
        source_id: synthetic_source_manifest(source_id, synthetic_dataset.events)
        for source_id in source_ids
    }
    search = _RetryingPagedAdapter(
        SyntheticDuckDBAdapter(repository, manifests["search_history"]),
        fail_on_event_page=2,
    )
    voc = SyntheticDuckDBAdapter(repository, manifests["voc"])
    registry = SourceRegistry([search, voc], evidence=search)
    selected_events = [
        event for event in synthetic_dataset.events if event.source_id in source_ids
    ]
    scope = ExplorationSourceScope(
        source_ids=source_ids,
        start_at=min(event.occurred_at for event in selected_events),
        end_at=max(event.occurred_at for event in selected_events)
        + timedelta(microseconds=1),
        native_page_size=5,
    )
    store = RunMaterializationStore(
        tmp_path / "partial-branches", run_id="partial-branches"
    )
    partial_tools = ExplorationTools(
        reader=DataSpaceReader(
            registry=registry,
            prepared_sources=registry.prepare_paged_sources(scope),
            authorized_scope=scope,
            cursor_codec=CursorCodec(b"partial-branches-secret" * 2),
            materializations=store,
        ),
        materializations=store,
    )

    response = partial_tools.summarize_events(
        SummarizeEventsInput(
            source_ids=source_ids,
            time_range=ExplorationTimeRange(
                start_at=scope.start_at,
                end_at=scope.end_at,
            ),
            predicates=(),
            group_by=(
                ExplorationFieldRef(
                    scope="canonical", name="source_id", source_id=None
                ),
            ),
            metrics=(CountMetric(kind="count", operation="event_count"),),
        )
    )

    assert response.status == "partial"
    assert response.partial is not None
    assert response.partial.remaining_branches == source_ids
    store.dispose()


def test_catalog_and_summary_tools_publish_clean_retryable_prefixes_as_partial(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    partial_tools, adapter, scope = _interruptible_search_tools(
        tmp_path=tmp_path,
        repository=repository,
        synthetic_dataset=synthetic_dataset,
        run_id="partial-catalogs",
    )
    time_range = ExplorationTimeRange(start_at=scope.start_at, end_at=scope.end_at)
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    is_repeat = ExplorationFieldRef(
        scope="dimension", name="is_repeat", source_id="search_history"
    )
    calls = (
        (
            partial_tools.inspect_data_space,
            InspectSourcesInput(
                view="sources", source_ids=("search_history",), page_size=50
            ),
        ),
        (
            partial_tools.inspect_data_space,
            InspectFieldsInput(
                view="fields", source_ids=("search_history",), page_size=50
            ),
        ),
        (
            partial_tools.inspect_data_space,
            InspectValuesInput(
                view="values",
                source_ids=("search_history",),
                field=is_repeat,
                predicates=(),
                page_size=50,
            ),
        ),
        (
            partial_tools.summarize_events,
            SummarizeEventsInput(
                source_ids=("search_history",),
                time_range=time_range,
                predicates=(),
                group_by=(topic,),
                metrics=(CountMetric(kind="count", operation="event_count"),),
                page_size=50,
            ),
        ),
    )

    responses = []
    for method, request in calls:
        adapter.arm_after_event_pages(2)
        responses.append(method(request))

    for response in responses:
        assert response.status == "partial"
        assert response.result.items
        assert response.page.scan_complete is False
        assert response.page.matched_count is None
        assert response.partial is not None
        assert response.partial.remaining_branches == ("search_history",)
    summary = responses[-1].result.items[0]
    assert all(metric.limitation is not None for metric in summary.metrics)
    partial_tools.materializations.dispose()


def test_every_sequence_mode_returns_structured_partial_on_retryable_scan(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    partial_tools, adapter, scope = _interruptible_search_tools(
        tmp_path=tmp_path,
        repository=repository,
        synthetic_dataset=synthetic_dataset,
        run_id="partial-sequences",
    )
    time_range = ExplorationTimeRange(start_at=scope.start_at, end_at=scope.end_at)
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    steps = (
        SequenceStep(
            step_id="first", source_ids=("search_history",), event_predicates=()
        ),
        SequenceStep(
            step_id="second", source_ids=("search_history",), event_predicates=()
        ),
    )
    requests = (
        RepetitionInput(
            mode="repetition",
            source_ids=("search_history",),
            time_range=time_range,
            target=RepetitionTarget(
                event_predicates=(),
                grouping_fields=(topic,),
                min_occurrences=2,
                max_gap_minutes=10_080,
            ),
            group_by=(),
        ),
        SequenceInput(
            mode="sequence",
            source_ids=("search_history",),
            time_range=time_range,
            steps=steps,
            max_total_span_minutes=10_080,
            group_by=(),
        ),
        FunnelInput(
            mode="funnel",
            source_ids=("search_history",),
            time_range=time_range,
            steps=steps,
            max_total_span_minutes=10_080,
            group_by=(),
        ),
    )

    responses = []
    for request in requests:
        adapter.arm_after_event_pages(2)
        responses.append(partial_tools.analyze_event_sequences(request))

    for response in responses:
        assert response.status == "partial"
        assert response.page.scan_complete is False
        assert response.page.matched_count is None
        assert response.partial is not None
    assert responses[0].result.items == ()
    assert responses[1].result.items
    assert responses[-1].result.items == ()
    partial_tools.materializations.dispose()


def test_evidence_tool_preserves_bounded_events_on_retryable_partial_scan(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    partial_tools, adapter, scope = _interruptible_search_tools(
        tmp_path=tmp_path,
        repository=repository,
        synthetic_dataset=synthetic_dataset,
        run_id="partial-evidence",
    )
    time_range = ExplorationTimeRange(start_at=scope.start_at, end_at=scope.end_at)
    parent = partial_tools.analyze_event_sequences(
        RepetitionInput(
            mode="repetition",
            source_ids=("search_history",),
            time_range=time_range,
            target=RepetitionTarget(
                event_predicates=(),
                grouping_fields=(),
                min_occurrences=2,
                max_gap_minutes=10_080,
            ),
            group_by=(),
            page_size=200,
        )
    )
    assert parent.status == "success"
    assert parent.result.result_ref is not None
    adapter.arm_after_event_pages(8)

    response = partial_tools.read_event_evidence(
        ReadEventEvidenceInput(
            parent_result_ref=parent.result.result_ref,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=(),
                max_customers=3,
                events_before_match=1,
                events_after_match=2,
            ),
            include_fields=(),
            page_size=200,
        )
    )

    assert response.status == "partial"
    assert response.result.items
    assert response.page.scan_complete is False
    assert response.page.matched_count is None
    assert response.partial is not None
    assert response.result.candidate_customer_count > 0
    assert response.result.selected_customer_count == 3
    partial_tools.materializations.dispose()


def test_repetition_computes_population_before_paging_and_authorizes_evidence(
    tools: ExplorationTools,
    tmp_path: Path,
) -> None:
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    result = tools.analyze_event_sequences(
        RepetitionInput(
            mode="repetition",
            source_ids=("hackathon_search_history",),
            time_range=TIME_RANGE,
            target=RepetitionTarget(
                event_predicates=(),
                grouping_fields=(topic,),
                min_occurrences=2,
                max_gap_minutes=10_080,
            ),
            group_by=(),
            page_size=2,
        )
    )
    assert result.status == "success"
    assert result.page.scan_complete is True
    assert result.page.matched_count == 459
    assert result.page.matched_count > len(result.result.items)
    parent = result.result.result_ref

    evidence_items, evidence = _exhaust(
        tools.read_event_evidence,
        ReadEventEvidenceInput(
            parent_result_ref=parent,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=(),
                max_customers=1,
                events_before_match=1,
                events_after_match=2,
            ),
            include_fields=(topic,),
            page_size=2,
        ),
    )
    assert evidence.status == "success"
    assert 1 <= len(evidence_items) <= 4
    assert len({item.evidence_id for item in evidence_items}) == len(evidence_items)
    assert evidence.result.candidate_customer_count == 459
    assert evidence.result.selected_customer_count == 1
    assert isinstance(evidence_items[0], PublicExplorationEvidenceEvent)
    payload = evidence_items[0].model_dump()
    assert "canonical_customer_id" not in payload
    assert "identities" not in payload
    assert "raw_fields" not in payload

    template = ExplorationFieldRef(
        scope="dimension",
        name="template",
        source_id="hackathon_search_history",
    )
    bounded_items, bounded = _exhaust(
        tools.read_event_evidence,
        ReadEventEvidenceInput(
            parent_result_ref=parent,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=(),
                max_customers=3,
                events_before_match=5,
                events_after_match=10,
            ),
            include_fields=(topic, template),
            page_size=200,
        ),
    )
    per_customer: dict[str, int] = {}
    for item in bounded_items:
        per_customer[item.customer_ref] = per_customer.get(item.customer_ref, 0) + 1
        assert set(item.model_dump()) == {
            "item_kind",
            "evidence_id",
            "source_id",
            "occurred_at",
            "event_type",
            "action",
            "topic",
            "outcome",
            "customer_ref",
            "semantic_fields",
        }
    serialized = canonical_json([item.model_dump(mode="json") for item in bounded_items])
    assert bounded.result.candidate_customer_count == 459
    assert bounded.result.selected_customer_count == 3
    assert len(per_customer) == 3
    assert all(count <= 16 for count in per_customer.values())
    assert len(bounded_items) <= 48
    for prohibited in (
        "canonical_customer_id",
        "identities",
        "masked_customer_id",
        "raw_fields",
        "session_id",
        "reason",
    ):
        assert prohibited not in serialized

    authorized_customer_ref = result.result.items[0].customer_ref
    forged_customer_ref = tools.materializations.make_ref("customer")
    forged = tools.read_event_evidence(
        ReadEventEvidenceInput(
            parent_result_ref=parent,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=(forged_customer_ref,),
                max_customers=1,
                events_before_match=0,
                events_after_match=0,
            ),
            include_fields=(),
        )
    )
    assert forged.status == "error"
    assert forged.error is not None
    assert forged.error.category == "validation"

    sibling_parent = tools.materializations.store_result(
        query_ref=tools.materializations.make_ref("query"),
        result_kind="summary",
        query_fingerprint="sibling-result-fingerprint",
        snapshot_id=tools.reader.snapshot_id,
        source_ids=("hackathon_search_history",),
        rows=(),
        matched_count=0,
        scan_complete=True,
    )
    sibling = tools.read_event_evidence(
        ReadEventEvidenceInput(
            parent_result_ref=sibling_parent,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=(authorized_customer_ref,),
                max_customers=1,
                events_before_match=0,
                events_after_match=0,
            ),
            include_fields=(),
        )
    )
    assert sibling.status == "error"
    assert sibling.error is not None
    assert sibling.error.category == "validation"

    foreign_store = RunMaterializationStore(tmp_path / "foreign", run_id="foreign-run")
    foreign_parent = foreign_store.store_result(
        query_ref=foreign_store.make_ref("query"),
        result_kind="summary",
        query_fingerprint="foreign-result-fingerprint",
        snapshot_id="foreign-snapshot",
        source_ids=("hackathon_search_history",),
        rows=(),
        matched_count=0,
        scan_complete=True,
    )
    foreign = tools.read_event_evidence(
        ReadEventEvidenceInput(
            parent_result_ref=foreign_parent,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=(),
                max_customers=1,
                events_before_match=0,
                events_after_match=0,
            ),
            include_fields=(),
        )
    )
    assert foreign.status == "error"
    assert foreign.error is not None
    assert foreign.error.category == "permission"
    foreign_store.dispose()

    for denied_field in (
        ExplorationFieldRef(
            scope="dimension",
            name="reason",
            source_id="hackathon_search_feedback",
        ),
        ExplorationFieldRef(
            scope="dimension",
            name="session_id",
            source_id="hackathon_app_behavior",
        ),
    ):
        denied = tools.read_event_evidence(
            ReadEventEvidenceInput(
                parent_result_ref=parent,
                selection=EvidenceSelection(
                    strategy="representative",
                    customer_refs=(),
                    max_customers=1,
                    events_before_match=0,
                    events_after_match=0,
                ),
                include_fields=(denied_field,),
            )
        )
        assert denied.status == "error"
        assert denied.error is not None
        assert denied.error.category == "permission"


def test_source_catalog_bounds_high_cardinality_canonical_vocabularies(
    tmp_path: Path,
    synthetic_dataset: SyntheticDataset,
) -> None:
    before = canonical_json(exploration_tool_json_schema())
    source_id = "search_history"
    template = next(
        event for event in synthetic_dataset.events if event.source_id == source_id
    )
    evidence_by_id = {record.evidence_id: record for record in synthetic_dataset.evidence}
    evidence_template = evidence_by_id[template.evidence_id]
    events = [
        template.model_copy(
            update={
                "event_id": f"bounded-event-{index:03d}",
                "evidence_id": f"bounded-evidence-{index:03d}",
                "occurred_at": template.occurred_at + timedelta(microseconds=index),
                "event_type": f"event_{79 - index:03d}",
                "action": f"action-{79 - index:03d}",
                "topic": f"topic-{79 - index:03d}",
                "outcome": f"outcome-{79 - index:03d}",
            }
        )
        for index in range(80)
    ]
    evidence = [
        evidence_template.model_copy(
            update={
                "evidence_id": f"bounded-evidence-{index:03d}",
                "occurred_at": template.occurred_at + timedelta(microseconds=index),
            }
        )
        for index in range(80)
    ]
    dataset = SyntheticDataset(
        customers=synthetic_dataset.customers,
        events=events,
        evidence=evidence,
        identity_edges=synthetic_dataset.identity_edges,
        ground_truth_customer_ids=synthetic_dataset.ground_truth_customer_ids,
    )
    database_path = tmp_path / "bounded-vocabulary.duckdb"
    seed_database(database_path, dataset)
    repository = DuckDBRepository(database_path)
    adapter = SyntheticDuckDBAdapter(
        repository, synthetic_source_manifest(source_id, events)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=(source_id,),
        start_at=events[0].occurred_at,
        end_at=events[-1].occurred_at + timedelta(microseconds=1),
        native_page_size=7,
    )
    store = RunMaterializationStore(tmp_path / "bounded-run", run_id="bounded-run")
    bounded_tools = ExplorationTools(
        reader=DataSpaceReader(
            registry=registry,
            prepared_sources=registry.prepare_paged_sources(scope),
            authorized_scope=scope,
            cursor_codec=CursorCodec(b"bounded-vocabulary-cursor-secret"),
            materializations=store,
        ),
        materializations=store,
    )

    items, response = _exhaust(
        bounded_tools.inspect_data_space,
        InspectSourcesInput(view="sources", source_ids=(source_id,), page_size=1),
    )

    assert response.page.scan_complete is True
    assert len(items) == 1
    item = items[0]
    assert item.vocabulary_limit == 64
    assert item.truncated_fields == ("event_type", "action", "topic", "outcome")
    assert item.event_types == tuple(f"event_{index:03d}" for index in range(64))
    assert item.actions == tuple(f"action-{index:03d}" for index in range(64))
    assert item.topics == tuple(f"topic-{index:03d}" for index in range(64))
    assert item.outcomes == tuple(f"outcome-{index:03d}" for index in range(64))
    assert "view=values" in item.vocabulary_limitation
    assert canonical_json(exploration_tool_json_schema()) == before
    store.dispose()


@pytest.mark.parametrize(
    "overrides",
    (
        {"max_customers": 4},
        {"events_before_match": 6},
        {"events_after_match": 11},
    ),
)
def test_evidence_selection_rejects_public_window_cap_expansion(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        EvidenceSelection(strategy="representative", **overrides)


def test_cross_source_sequence_uses_greedy_full_population_before_paging(
    tools: ExplorationTools,
) -> None:
    response = tools.analyze_event_sequences(
        SequenceInput(
            mode="sequence",
            source_ids=("hackathon_search_history", "hackathon_voc"),
            time_range=TIME_RANGE,
            steps=(
                SequenceStep(
                    step_id="search",
                    source_ids=("hackathon_search_history",),
                    event_predicates=(),
                    min_occurrences=1,
                ),
                SequenceStep(
                    step_id="voc",
                    source_ids=("hackathon_voc",),
                    event_predicates=(),
                    min_occurrences=1,
                ),
            ),
            max_total_span_minutes=10_080,
            group_by=(),
            page_size=5,
        )
    )
    assert response.status == "success"
    assert response.page.scan_complete is True
    assert response.page.matched_count == 348
    assert response.page.has_more is True


def test_roaming_sequence_links_plan_browsing_exit_to_agent_signup(tools: ExplorationTools) -> None:
    roaming = "hackathon_roaming_usage"
    def action(value):
        return ComparisonPredicate(kind="comparison", operator="eq", value=value,
                                   field=ExplorationFieldRef(scope="canonical", name="action"))
    result = tools.analyze_event_sequences(
        SequenceInput(
            mode="sequence",
            source_ids=("hackathon_app_behavior", "hackathon_voc", roaming),
            time_range=ExplorationTimeRange(
                start_at=TIME_RANGE.start_at,
                end_at=datetime.fromisoformat("2026-09-11T00:00:00+09:00"),
            ),
            steps=(
                SequenceStep(step_id="plans_compared", source_ids=("hackathon_app_behavior",),
                             min_occurrences=3, event_predicates=(action("roaming_plan_detail_viewed"),)),
                SequenceStep(step_id="app_exited", source_ids=("hackathon_app_behavior",),
                             event_predicates=(action("roaming_plan_selection_exited"),)),
                SequenceStep(step_id="agent_signup", source_ids=("hackathon_voc",),
                             event_predicates=(ComparisonPredicate(
                                 kind="comparison", operator="eq", value="상담원 로밍 가입 처리 완료",
                                 field=ExplorationFieldRef(scope="dimension", name="resolution",
                                                           source_id="hackathon_voc"),
                             ),)),
                SequenceStep(step_id="registered_subscription", source_ids=(roaming,),
                             event_predicates=(ComparisonPredicate(
                                 kind="comparison", operator="eq", value="A",
                                 field=ExplorationFieldRef(scope="canonical", name="outcome"),
                             ),)),
            ),
            group_by=tuple(ExplorationFieldRef(scope="dimension", name=name, source_id=roaming)
                           for name in ("departure_date", "service_start_date")),
            max_total_span_minutes=1440,
            page_size=200,
        )
    )
    assert result.status == "success"
    assert result.page.scan_complete is True
    assert result.page.matched_count == 56
    for item in result.result.items:
        assert item.completed_step_count == 4
        dates = {value.field.name: value.value for value in item.group_values}
        assert dates["departure_date"] == dates["service_start_date"]


def test_funnel_computes_every_reached_customer_and_dropoff_before_paging(
    tools: ExplorationTools,
) -> None:
    items, last = _exhaust(
        tools.analyze_event_sequences,
        FunnelInput(
            mode="funnel",
            source_ids=("hackathon_search_history", "hackathon_voc"),
            time_range=TIME_RANGE,
            steps=(
                SequenceStep(
                    step_id="search",
                    source_ids=("hackathon_search_history",),
                    event_predicates=(),
                    min_occurrences=1,
                ),
                SequenceStep(
                    step_id="voc",
                    source_ids=("hackathon_voc",),
                    event_predicates=(),
                    min_occurrences=1,
                ),
            ),
            max_total_span_minutes=10_080,
            group_by=(),
            page_size=7,
        ),
    )

    completed = [item for item in items if item.completed_step_count == 2]
    dropped = [item for item in items if item.dropoff_after_step_id == "search"]
    assert last.page.scan_complete is True
    assert last.page.matched_count == len(items) == 1_081
    assert len(completed) == 348
    assert len(dropped) == 733

    parent_result_ref = last.result.result_ref
    assert parent_result_ref is not None
    parent_by_customer = {item.customer_ref: item for item in items}
    representative_request = ReadEventEvidenceInput(
        parent_result_ref=parent_result_ref,
        selection=EvidenceSelection(
            strategy="representative",
            customer_refs=(),
            max_customers=3,
            events_before_match=0,
            events_after_match=0,
        ),
        include_fields=(),
        page_size=1,
    )
    evidence_pages = []
    evidence_items = []
    response = tools.read_event_evidence(representative_request)
    assert response.result.result_ref is not None
    assert (
        tools.materializations.read_result(response.result.result_ref).parent_result_ref
        == parent_result_ref
    )
    while True:
        assert response.status == "success"
        evidence_pages.append(response)
        evidence_items.extend(response.result.items)
        if not response.page.has_more:
            break
        response = tools.read_event_evidence(
            representative_request.model_copy(
                update={"cursor": response.page.next_cursor}
            )
        )

    selected_strata = {
        (
            parent_by_customer[item.customer_ref].completed_step_count,
            parent_by_customer[item.customer_ref].dropoff_after_step_id,
        )
        for item in evidence_items
    }
    assert len(selected_strata) >= 2
    expected_meta = {
        "candidate_customer_count": 1_081,
        "selected_customer_count": 3,
        "selection_strategy": "representative",
        "events_before_match": 0,
        "events_after_match": 0,
    }
    for page in evidence_pages:
        payload = page.result.model_dump()
        for key, value in expected_meta.items():
            assert payload[key] == value
        assert "strata" in page.result.selection_rationale

    explicit_refs = (completed[0].customer_ref, dropped[0].customer_ref)
    explicit_items, explicit = _exhaust(
        tools.read_event_evidence,
        ReadEventEvidenceInput(
            parent_result_ref=parent_result_ref,
            selection=EvidenceSelection(
                strategy="representative",
                customer_refs=explicit_refs,
                max_customers=2,
                events_before_match=1,
                events_after_match=2,
            ),
            include_fields=(),
            page_size=200,
        ),
    )
    assert {item.customer_ref for item in explicit_items} == set(explicit_refs)
    assert explicit.result.candidate_customer_count == 1_081
    assert explicit.result.selected_customer_count == 2
    assert explicit.result.selection_strategy == "explicit"
    assert explicit.result.events_before_match == 1
    assert explicit.result.events_after_match == 2
    assert "explicit" in explicit.result.selection_rationale


def test_sequence_scan_keeps_native_buffers_bounded_and_clears_temporary_rows(
    tools: ExplorationTools,
) -> None:
    response = tools.analyze_event_sequences(
        SequenceInput(
            mode="sequence",
            source_ids=("hackathon_search_history", "hackathon_voc"),
            time_range=TIME_RANGE,
            steps=(
                SequenceStep(
                    step_id="search",
                    source_ids=("hackathon_search_history",),
                    event_predicates=(),
                ),
                SequenceStep(
                    step_id="voc",
                    source_ids=("hackathon_voc",),
                    event_predicates=(),
                ),
            ),
            max_total_span_minutes=10_080,
            group_by=(),
            page_size=200,
        )
    )

    assert response.status == "success"
    assert response.result.result_ref is not None
    meta = tools.materializations.read_result(response.result.result_ref)
    assert meta.row_count == 348 < 1_888
    assert tools.reader.last_scan_peak_buffered_events <= 2 * 200
    assert tools.materializations.work_row_count == 0
    assert tools.materializations.staging_row_count == 0


def test_empty_match_is_success_and_forbidden_source_is_permission_error(
    tools: ExplorationTools,
) -> None:
    topic = ExplorationFieldRef(scope="canonical", name="topic", source_id=None)
    empty = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("hackathon_voc",),
            time_range=TIME_RANGE,
            predicates=(
                ComparisonPredicate(
                    kind="comparison",
                    field=topic,
                    operator="eq",
                    value="definitely-not-present",
                ),
            ),
            group_by=(topic,),
            metrics=(CountMetric(kind="count", operation="event_count"),),
            page_size=10,
        )
    )
    assert empty.status == "success"
    assert empty.result.items == ()
    assert empty.page.matched_count == 0

    denied = tools.summarize_events(
        SummarizeEventsInput(
            source_ids=("not-authorized",),
            time_range=TIME_RANGE,
            predicates=(),
            group_by=(),
            metrics=(CountMetric(kind="count", operation="event_count"),),
        )
    )
    assert denied.status == "error"
    assert denied.error is not None
    assert denied.error.category == "permission"


def test_sequence_input_is_a_discriminated_union() -> None:
    schema = TypeAdapter(AnalyzeEventSequencesInput).json_schema()
    assert "discriminator" in schema
    FunnelInput,
