"""Strict page, cursor-key, and run-reference exploration contracts."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from customer_signal.domain.models import CustomerEvent, IdentityEdge, IdentityRef
from customer_signal.exploration.contracts import (
    CohortRef,
    CustomerRef,
    EventPageState,
    EventSortKey,
    ExplorationSourceScope,
    IdentityEdgeSortKey,
    IdentityPage,
    IdentityPageRequest,
    IdentityPageState,
    PageRef,
    QueryRef,
    ResultRef,
    SourceEventPage,
    SourcePageRequest,
    ToolError,
    ToolStatus,
)


NOW = datetime(2026, 8, 18, 9, tzinfo=UTC)


def _event(*, event_id: str, occurred_at: datetime = NOW) -> CustomerEvent:
    return CustomerEvent(
        event_id=event_id,
        evidence_id=f"evidence-{event_id}",
        source_id="source_a",
        occurred_at=occurred_at,
        event_type="source_event",
        action="recorded",
        topic="test",
        outcome="ok",
        text="",
        identities=[IdentityRef(namespace="source_identity", value="customer-1")],
        canonical_customer_id="customer-1",
    )


def _edge(*, left_value: str) -> IdentityEdge:
    return IdentityEdge(
        left=IdentityRef(namespace="source_identity", value=left_value),
        right=IdentityRef(namespace="canonical_customer", value="customer-1"),
        link_type="EXACT",
        confidence=1.0,
        provenance="test:source_a",
    )


def _scope() -> ExplorationSourceScope:
    return ExplorationSourceScope(
        source_ids=["source_a"],
        start_at=NOW,
        end_at=NOW + timedelta(days=1),
        native_page_size=37,
    )


def test_page_requires_next_key_exactly_when_more_rows_exist() -> None:
    with pytest.raises(ValidationError, match="next_key"):
        EventPageState(has_more=True, next_key=None)
    with pytest.raises(ValidationError, match="next_key"):
        EventPageState(
            has_more=False,
            next_key=EventSortKey(
                occurred_at=NOW,
                source_id="source_a",
                event_id="event-1",
            ),
        )


def test_event_page_uses_last_item_as_next_key() -> None:
    events = [_event(event_id="event-1"), _event(event_id="event-2")]
    page = SourceEventPage(
        items=events,
        has_more=True,
        next_key=EventSortKey.from_event(events[-1]),
    )

    assert page.next_key == EventSortKey.from_event(page.items[-1])

    with pytest.raises(ValidationError, match="last item"):
        SourceEventPage(
            items=events,
            has_more=True,
            next_key=EventSortKey.from_event(events[0]),
        )


def test_identity_page_uses_last_item_as_next_key() -> None:
    edges = [_edge(left_value="a"), _edge(left_value="b")]
    page = IdentityPage(
        items=edges,
        has_more=True,
        next_key=IdentityEdgeSortKey.from_edge(edges[-1]),
    )

    assert page.next_key == IdentityEdgeSortKey.from_edge(page.items[-1])

    with pytest.raises(ValidationError, match="last item"):
        IdentityPage(
            items=edges,
            has_more=True,
            next_key=IdentityEdgeSortKey.from_edge(edges[0]),
        )


def test_scope_and_page_collections_are_deeply_stable_and_serialize_as_arrays() -> None:
    scope = _scope()
    events = [_event(event_id="event-1"), _event(event_id="event-2")]
    edges = [_edge(left_value="a"), _edge(left_value="b")]
    event_page = SourceEventPage(
        items=events,
        has_more=True,
        next_key=EventSortKey.from_event(events[-1]),
    )
    identity_page = IdentityPage(
        items=edges,
        has_more=True,
        next_key=IdentityEdgeSortKey.from_edge(edges[-1]),
    )

    assert scope.source_ids == ("source_a",)
    assert isinstance(event_page.items, tuple)
    assert isinstance(identity_page.items, tuple)
    assert scope.model_dump(mode="json")["source_ids"] == ["source_a"]
    assert isinstance(event_page.model_dump(mode="json")["items"], list)
    assert isinstance(identity_page.model_dump(mode="json")["items"], list)

    with pytest.raises(AttributeError):
        scope.source_ids.append("source_b")
    with pytest.raises(AttributeError):
        event_page.items.append(_event(event_id="event-3"))
    with pytest.raises(AttributeError):
        identity_page.items.append(_edge(left_value="c"))

    events.clear()
    edges.clear()
    assert len(event_page.items) == 2
    assert len(identity_page.items) == 2


def test_event_page_takes_an_immutable_deep_snapshot_of_each_event() -> None:
    event = _event(event_id="event-1")
    event.dimensions["segment"] = "before"
    page = SourceEventPage(
        items=[event],
        has_more=True,
        next_key=EventSortKey.from_event(event),
    )

    event.event_id = "mutated-original"
    event.identities[0].value = "mutated-original"
    event.dimensions["segment"] = "mutated-original"

    assert page.items[0].event_id == "event-1"
    assert page.items[0].identities[0].value == "customer-1"
    assert page.items[0].dimensions["segment"] == "before"
    assert page.next_key == EventSortKey.from_event(page.items[0])
    assert isinstance(page.items[0].identities, tuple)
    assert page.model_dump(mode="json")["items"][0]["identities"] == [
        {"namespace": "source_identity", "value": "customer-1"}
    ]

    with pytest.raises(ValidationError, match="frozen"):
        page.items[0].event_id = "mutated-page"
    with pytest.raises(ValidationError, match="frozen"):
        page.items[0].occurred_at = NOW + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="frozen"):
        page.items[0].identities[0].value = "mutated-page"
    with pytest.raises(TypeError):
        page.items[0].dimensions["segment"] = "mutated-page"


def test_identity_page_takes_an_immutable_deep_snapshot_of_each_edge() -> None:
    edge = _edge(left_value="original")
    page = IdentityPage(
        items=[edge],
        has_more=True,
        next_key=IdentityEdgeSortKey.from_edge(edge),
    )

    edge.left.value = "mutated-original"

    assert page.items[0].left.value == "original"
    assert page.next_key == IdentityEdgeSortKey.from_edge(page.items[0])
    assert page.model_dump(mode="json")["items"][0]["left"] == {
        "namespace": "source_identity",
        "value": "original",
    }

    with pytest.raises(ValidationError, match="frozen"):
        page.items[0].left = IdentityRef(namespace="source_identity", value="other")
    with pytest.raises(ValidationError, match="frozen"):
        page.items[0].left.value = "mutated-page"


def test_immutable_page_snapshots_round_trip_through_public_json() -> None:
    event_page = SourceEventPage(
        items=[_event(event_id="event-1")],
        has_more=False,
        next_key=None,
    )
    identity_page = IdentityPage(
        items=[_edge(left_value="original")],
        has_more=False,
        next_key=None,
    )

    restored_event_page = SourceEventPage.model_validate_json(event_page.model_dump_json())
    restored_identity_page = IdentityPage.model_validate_json(identity_page.model_dump_json())

    assert restored_event_page == event_page
    assert restored_identity_page == identity_page
    with pytest.raises(ValidationError, match="frozen"):
        restored_event_page.items[0].identities[0].value = "mutated"


def test_immutable_event_and_page_support_pydantic_deep_copy() -> None:
    event = _event(event_id="event-1")
    event.attributes["origin"] = "original"
    event.dimensions["segment"] = "control"
    event.measures["score"] = 1.5
    page = SourceEventPage(items=[event], has_more=False, next_key=None)

    copied_event = page.items[0].model_copy(deep=True)
    copied_page = page.model_copy(deep=True)

    assert copied_event == page.items[0]
    assert copied_page == page
    assert copied_event.model_dump(mode="json") == page.items[0].model_dump(mode="json")
    with pytest.raises(ValidationError, match="frozen"):
        copied_event.event_id = "mutated"
    with pytest.raises(TypeError):
        copied_event.dimensions["segment"] = "mutated"
    with pytest.raises(AttributeError):
        copied_page.items[0].measures.update({"score": 9.0})


def test_empty_pages_cannot_claim_more_rows() -> None:
    with pytest.raises(ValidationError, match="items"):
        SourceEventPage(
            items=[],
            has_more=True,
            next_key=EventSortKey(occurred_at=NOW, source_id="source_a", event_id="event-1"),
        )
    with pytest.raises(ValidationError, match="items"):
        IdentityPage(
            items=[],
            has_more=True,
            next_key=IdentityEdgeSortKey(
                left_namespace="a",
                left_value="1",
                right_namespace="b",
                right_value="2",
                link_type="EXACT",
            ),
        )


def test_scope_requires_aware_half_open_range_unique_sources_and_native_page_size() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ExplorationSourceScope(
            source_ids=["source_a"],
            start_at=NOW.replace(tzinfo=None),
            end_at=NOW,
            native_page_size=10,
        )
    with pytest.raises(ValidationError, match="start_at"):
        ExplorationSourceScope(
            source_ids=["source_a"],
            start_at=NOW,
            end_at=NOW,
            native_page_size=10,
        )
    with pytest.raises(ValidationError, match="unique"):
        ExplorationSourceScope(
            source_ids=["source_a", "source_a"],
            start_at=NOW,
            end_at=NOW + timedelta(days=1),
            native_page_size=10,
        )
    with pytest.raises(ValidationError, match="native_page_size"):
        ExplorationSourceScope(
            source_ids=["source_a"],
            start_at=NOW,
            end_at=NOW + timedelta(days=1),
            native_page_size=True,
        )
    assert "max_events" not in ExplorationSourceScope.model_fields


@pytest.mark.parametrize("page_size", [0, 201, True, 1.5])
def test_page_requests_reject_out_of_range_or_coerced_page_sizes(page_size: object) -> None:
    with pytest.raises(ValidationError, match="page_size"):
        SourcePageRequest(scope=_scope(), after=None, page_size=page_size)
    with pytest.raises(ValidationError, match="page_size"):
        IdentityPageRequest(scope=_scope(), after=None, page_size=page_size)


def test_event_and_identity_request_keys_cannot_be_mixed() -> None:
    event_key = EventSortKey(occurred_at=NOW, source_id="source_a", event_id="event-1")
    identity_key = IdentityEdgeSortKey.from_edge(_edge(left_value="a"))

    with pytest.raises(ValidationError, match="after"):
        SourcePageRequest(scope=_scope(), after=identity_key, page_size=10)
    with pytest.raises(ValidationError, match="after"):
        IdentityPageRequest(scope=_scope(), after=event_key, page_size=10)
    with pytest.raises(ValidationError, match="next_key"):
        IdentityPageState(has_more=True, next_key=event_key)


def test_sort_keys_reject_naive_datetime_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        EventSortKey(
            occurred_at=NOW.replace(tzinfo=None),
            source_id="source_a",
            event_id="event-1",
        )
    with pytest.raises(ValidationError, match="extra"):
        EventSortKey.model_validate(
            {
                "occurred_at": NOW,
                "source_id": "source_a",
                "event_id": "event-1",
                "extra": "forbidden",
            }
        )


def test_tool_and_reference_contracts_are_strict() -> None:
    assert TypeAdapter(ToolStatus).validate_python("partial", strict=True) == "partial"
    error = ToolError(category="validation", is_retryable=False, message="invalid cursor")
    assert error.category == "validation"
    assert error.is_retryable is False

    for reference_type, value in (
        (QueryRef, "query-123"),
        (ResultRef, "result-123"),
        (PageRef, "page-123"),
        (CohortRef, "cohort-123"),
        (CustomerRef, "customer-123"),
    ):
        adapter = TypeAdapter(reference_type)
        assert adapter.validate_python(value, strict=True) == value
        with pytest.raises(ValidationError):
            adapter.validate_python(1, strict=True)

    with pytest.raises(ValidationError, match="is_retryable"):
        ToolError(category="validation", is_retryable=0, message="invalid cursor")
    with pytest.raises(ValidationError, match="extra"):
        ToolError.model_validate(
            {
                "category": "validation",
                "is_retryable": False,
                "message": "invalid cursor",
                "extra": "forbidden",
            }
        )
