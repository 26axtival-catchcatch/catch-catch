"""Native paged adapter protocol and snapshot-scoped validation seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from customer_signal.data.source_registry import SourceAdapter, UnsupportedPaginationError
from customer_signal.domain.models import CustomerEvent, IdentityEdge, IdentityRef
from customer_signal.domain.sources import SourceManifest
from customer_signal.domain.types import SourceId
from customer_signal.exploration.contracts import (
    EventSortKey,
    ExplorationSourceScope,
    FrozenCustomerEvent,
    FrozenIdentityEdge,
    FrozenIdentityRef,
    FrozenScalarMapping,
    IdentityEdgeSortKey,
    IdentityPage,
    IdentityPageRequest,
    SourceEventPage,
    SourcePageRequest,
)


class SnapshotChangedError(ValueError):
    """A source changed while its native page chain was being read."""


@runtime_checkable
class PagedSourceAdapter(SourceAdapter, Protocol):
    """Source adapter that owns stable event and raw-identity keyset pagination."""

    def snapshot_token(self) -> str: ...

    def load_event_page(self, request: SourcePageRequest) -> SourceEventPage: ...

    def load_identity_page(self, request: IdentityPageRequest) -> IdentityPage: ...


def _identity_key(edge: IdentityEdge) -> tuple[str, str, str, str, str]:
    return IdentityEdgeSortKey.from_edge(edge).as_tuple()


def _endpoint_key(edge: IdentityEdge) -> tuple[str, str, str, str]:
    return (
        edge.left.namespace,
        edge.left.value,
        edge.right.namespace,
        edge.right.value,
    )


def _validate_event_page_state(page: SourceEventPage) -> None:
    if type(page.has_more) is not bool:
        raise ValueError("has_more must be a strict boolean")
    if not isinstance(page.items, tuple):
        raise ValueError("event page items must be an immutable tuple")
    if any(
        not isinstance(event, FrozenCustomerEvent)
        or not isinstance(event.identities, tuple)
        or any(not isinstance(identity, FrozenIdentityRef) for identity in event.identities)
        or any(
            not isinstance(values, FrozenScalarMapping)
            for values in (event.attributes, event.dimensions, event.measures)
        )
        for event in page.items
    ):
        raise ValueError("event page items must be immutable snapshots")
    for event in page.items:
        try:
            validated_event = FrozenCustomerEvent.model_validate(
                event.model_dump(mode="python", warnings=False)
            )
        except ValidationError as error:
            raise ValueError("event page item must be a valid event snapshot") from error
        if validated_event != event:
            raise ValueError("event page item must be a valid event snapshot")
    if page.has_more != (page.next_key is not None):
        raise ValueError("next_key must exist exactly when has_more is true")
    if page.has_more:
        if not page.items:
            raise ValueError("event page items must not be empty when has_more is true")
        if page.next_key != EventSortKey.from_event(page.items[-1]):
            raise ValueError("next_key must equal the last item event sort key")


def _validate_identity_page_state(page: IdentityPage) -> None:
    if type(page.has_more) is not bool:
        raise ValueError("has_more must be a strict boolean")
    if not isinstance(page.items, tuple):
        raise ValueError("identity page items must be an immutable tuple")
    if any(
        not isinstance(edge, FrozenIdentityEdge)
        or not isinstance(edge.left, FrozenIdentityRef)
        or not isinstance(edge.right, FrozenIdentityRef)
        for edge in page.items
    ):
        raise ValueError("identity page items must be immutable snapshots")
    for edge in page.items:
        try:
            validated_edge = FrozenIdentityEdge.model_validate(
                edge.model_dump(mode="python", warnings=False)
            )
        except ValidationError as error:
            raise ValueError("identity page item must be a valid identity snapshot") from error
        if validated_edge != edge:
            raise ValueError("identity page item must be a valid identity snapshot")
    if page.has_more != (page.next_key is not None):
        raise ValueError("next_key must exist exactly when has_more is true")
    if page.has_more:
        if not page.items:
            raise ValueError("identity page items must not be empty when has_more is true")
        if page.next_key != IdentityEdgeSortKey.from_edge(page.items[-1]):
            raise ValueError("next_key must equal the last item identity sort key")


def _graph_components(
    edges: Sequence[IdentityEdge],
) -> list[set[tuple[str, str]]]:
    graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for edge in edges:
        left = (edge.left.namespace, edge.left.value)
        right = (edge.right.namespace, edge.right.value)
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    remaining = set(graph)
    components: list[set[tuple[str, str]]] = []
    while remaining:
        root = remaining.pop()
        component = {root}
        pending = [root]
        while pending:
            node = pending.pop()
            for neighbor in graph[node] - component:
                component.add(neighbor)
                remaining.discard(neighbor)
                pending.append(neighbor)
        components.append(component)
    return components


def _canonical_resolution(
    edges: Sequence[IdentityEdge],
) -> dict[tuple[str, str], str]:
    resolution: dict[tuple[str, str], str] = {}
    for component in _graph_components(edges):
        canonical = {
            value for namespace, value in component if namespace == "canonical_customer"
        }
        if len(canonical) != 1:
            raise ValueError(
                "identity graph component must resolve to exactly one canonical customer"
            )
        canonical_customer_id = next(iter(canonical))
        resolution.update(
            (node, canonical_customer_id)
            for node in component
        )
    return resolution


@dataclass(frozen=True, slots=True)
class IdentityResolver:
    """Immutable graph resolution and manifest context for one validated snapshot."""

    edges: tuple[IdentityEdge, ...]
    provenance_sources: Mapping[
        tuple[str, str, str, str, str], frozenset[SourceId]
    ]
    _canonical_by_node: Mapping[tuple[str, str], str] = field(repr=False)
    _manifests: Mapping[SourceId, SourceManifest] = field(repr=False)
    _scope: ExplorationSourceScope = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "edges",
            tuple(FrozenIdentityEdge.from_edge(edge) for edge in self.edges),
        )
        object.__setattr__(
            self,
            "provenance_sources",
            MappingProxyType(
                {
                    key: frozenset(source_ids)
                    for key, source_ids in self.provenance_sources.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "_canonical_by_node",
            MappingProxyType(dict(self._canonical_by_node)),
        )
        object.__setattr__(
            self,
            "_manifests",
            MappingProxyType(
                {
                    source_id: manifest.model_copy(deep=True)
                    for source_id, manifest in self._manifests.items()
                }
            ),
        )
        object.__setattr__(self, "_scope", self._scope.model_copy(deep=True))

    def resolve(self, identities: Sequence[IdentityRef]) -> str:
        if not identities:
            raise ValueError("event must include at least one identity")
        resolved: set[str] = set()
        for identity in identities:
            canonical_customer_id = self._canonical_by_node.get(
                (identity.namespace, identity.value)
            )
            if canonical_customer_id is None:
                raise ValueError(
                    "event identities must resolve to exactly one canonical customer"
                )
            resolved.add(canonical_customer_id)
        if len(resolved) != 1:
            raise ValueError("event identities must resolve to exactly one canonical customer")
        return next(iter(resolved))

    def manifest(self, source_id: SourceId) -> SourceManifest:
        """Return the immutable snapshot's copied semantic manifest."""

        try:
            return self._manifests[source_id].model_copy(deep=True)
        except KeyError as error:
            raise LookupError(f"source {source_id} is not in the validated snapshot") from error

    def validate_event(self, event: CustomerEvent) -> None:
        manifest = self._manifests.get(event.source_id)
        if manifest is None:
            raise ValueError("event source is not part of the validated source set")
        if not self._scope.start_at <= event.occurred_at < self._scope.end_at:
            raise ValueError("event occurred_at is outside the exploration scope")
        manifest.validate_event(event)
        if self.resolve(event.identities) != event.canonical_customer_id:
            raise ValueError("event canonical customer does not match identity resolution")


@dataclass(frozen=True, slots=True)
class ValidatedSourceSet:
    """Identity-validated immutable snapshot issued before event scans."""

    snapshot_tokens: Mapping[SourceId, str]
    identity_resolver: IdentityResolver

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_tokens", MappingProxyType(dict(self.snapshot_tokens)))


@dataclass(slots=True)
class EventValidationSession:
    """Mutable uniqueness/order state belonging to exactly one full event scan."""

    _event_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _evidence_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _scope_by_source: dict[SourceId, ExplorationSourceScope] = field(
        default_factory=dict, init=False, repr=False
    )
    _last_key_by_source: dict[SourceId, tuple] = field(
        default_factory=dict, init=False, repr=False
    )
    _snapshot_signature: tuple[tuple[str, str], ...] | None = field(
        default=None, init=False, repr=False
    )


def prepare_validated_source_set(
    adapters: Mapping[SourceId, SourceAdapter],
    scope: ExplorationSourceScope,
) -> ValidatedSourceSet:
    """Exhaust and validate every selected adapter's raw identity page chain."""

    snapshot_tokens: dict[SourceId, str] = {}
    selected_adapters: dict[SourceId, PagedSourceAdapter] = {}
    manifests: dict[SourceId, SourceManifest] = {}
    merged_edges: dict[tuple[str, str, str, str, str], IdentityEdge] = {}
    provenance_sources: dict[
        tuple[str, str, str, str, str], set[SourceId]
    ] = {}
    endpoint_semantics: dict[tuple[str, str, str, str], tuple[str, float]] = {}

    for source_id in scope.source_ids:
        try:
            adapter = adapters[source_id]
        except KeyError as error:
            raise LookupError(f"source {source_id} is not registered") from error
        if not isinstance(adapter, PagedSourceAdapter):
            raise UnsupportedPaginationError(
                f"unsupported_pagination: source {source_id} has no native page contract"
            )

        manifest = adapter.describe()
        if manifest.source_id != source_id:
            raise ValueError("registered source key does not match adapter manifest")
        manifests[source_id] = manifest
        selected_adapters[source_id] = adapter
        pinned_token = adapter.snapshot_token()
        if not isinstance(pinned_token, str) or not pinned_token:
            raise ValueError("snapshot token must be a non-empty string")
        snapshot_tokens[source_id] = pinned_token

    for source_id in scope.source_ids:
        adapter = selected_adapters[source_id]
        source_scope = scope.model_copy(update={"source_ids": (source_id,)})
        after = None
        previous_key: tuple[str, str, str, str, str] | None = None
        source_edges: list[IdentityEdge] = []
        seen_source_keys: set[tuple[str, str, str, str, str]] = set()
        while True:
            request = IdentityPageRequest(
                scope=source_scope,
                after=after,
                page_size=scope.native_page_size,
            )
            page = adapter.load_identity_page(request)
            if not isinstance(page, IdentityPage):
                raise ValueError("adapter must return an IdentityPage")
            _validate_identity_page_state(page)
            if len(page.items) > request.page_size:
                raise ValueError("adapter returned more identity rows than page_size")
            keys = [_identity_key(edge) for edge in page.items]
            if keys != sorted(keys):
                raise ValueError("identity page must use stable five-tuple order")
            if len(keys) != len(set(keys)) or any(key in seen_source_keys for key in keys):
                raise ValueError("duplicate identity edge in adapter page chain")
            if previous_key is not None and keys and keys[0] <= previous_key:
                raise ValueError("identity page chain must be strictly ordered")
            if after is not None and keys and keys[0] <= after.as_tuple():
                raise ValueError("identity page did not advance beyond its request key")

            source_edges.extend(page.items)
            seen_source_keys.update(keys)
            if keys:
                previous_key = keys[-1]
            if not page.has_more:
                break
            after = page.next_key

        after_snapshot = adapter.snapshot_token()
        if after_snapshot != snapshot_tokens[source_id]:
            raise SnapshotChangedError(
                f"snapshot changed while scanning identity pages for source {source_id}"
            )
        _canonical_resolution(source_edges)

        for edge in source_edges:
            key = _identity_key(edge)
            endpoint = _endpoint_key(edge)
            semantics = (edge.link_type, float(edge.confidence))
            existing_semantics = endpoint_semantics.get(endpoint)
            if existing_semantics is not None and existing_semantics != semantics:
                raise ValueError("conflicting identity edge link semantics across adapters")
            endpoint_semantics[endpoint] = semantics
            existing = merged_edges.get(key)
            if existing is not None and float(existing.confidence) != float(edge.confidence):
                raise ValueError("conflicting identity edge confidence across adapters")
            merged_edges.setdefault(key, edge)
            provenance_sources.setdefault(key, set()).add(source_id)

    for source_id, adapter in selected_adapters.items():
        if adapter.snapshot_token() != snapshot_tokens[source_id]:
            raise SnapshotChangedError(
                "snapshot changed before the selected identity scan barrier completed"
            )

    ordered_edges = tuple(merged_edges[key] for key in sorted(merged_edges))
    canonical_by_node = _canonical_resolution(ordered_edges)
    resolver = IdentityResolver(
        edges=ordered_edges,
        provenance_sources=MappingProxyType(
            {
                key: frozenset(source_ids)
                for key, source_ids in provenance_sources.items()
            }
        ),
        _canonical_by_node=MappingProxyType(canonical_by_node),
        _manifests=MappingProxyType(manifests),
        _scope=scope.model_copy(deep=True),
    )
    return ValidatedSourceSet(snapshot_tokens=snapshot_tokens, identity_resolver=resolver)


def validate_event_page(
    page: SourceEventPage,
    request: SourcePageRequest,
    expected_source_id: SourceId,
    validated_set: ValidatedSourceSet,
    scan_session: EventValidationSession,
) -> None:
    """Validate one page against its request, pinned identity, and scan-local state."""

    if not isinstance(page, SourceEventPage):
        raise ValueError("adapter must return a SourceEventPage")
    if not isinstance(request, SourcePageRequest):
        raise ValueError("request must be a SourcePageRequest")
    try:
        validated_request = SourcePageRequest.model_validate(
            request.model_dump(mode="python", warnings=False)
        )
    except ValidationError as error:
        raise ValueError("request must be a valid SourcePageRequest") from error
    if validated_request != request:
        raise ValueError("request must be a valid SourcePageRequest")
    request = validated_request
    if expected_source_id not in validated_set.snapshot_tokens:
        raise ValueError("expected source is not part of the validated source set")
    if request.scope.source_ids != (expected_source_id,):
        raise ValueError("request scope must select exactly the expected source")
    pinned_scope = scan_session._scope_by_source.get(expected_source_id)
    if pinned_scope is not None and request.scope != pinned_scope:
        raise ValueError("request scope must equal the first page scope for this source scan")
    if request.after is not None and request.after.source_id != expected_source_id:
        raise ValueError("request after key must belong to the expected source")
    if len(page.items) > request.page_size:
        raise ValueError("adapter returned more event rows than request page_size")
    if any(event.source_id != expected_source_id for event in page.items):
        raise ValueError("event page item does not belong to the expected source")
    if page.next_key is not None and page.next_key.source_id != expected_source_id:
        raise ValueError("event page next_key does not belong to the expected source")
    _validate_event_page_state(page)
    signature = tuple(sorted(validated_set.snapshot_tokens.items()))
    if (
        scan_session._snapshot_signature is not None
        and scan_session._snapshot_signature != signature
    ):
        raise ValueError("event validation session cannot cross source snapshots")
    previous = scan_session._last_key_by_source.get(expected_source_id)
    if previous is None:
        if request.after is not None:
            raise ValueError("the first page in a source scan must not include an after key")
    elif request.after is None or request.after.as_tuple() != previous:
        raise ValueError("request after key must equal the previous page last key")

    keys = [EventSortKey.from_event(event).as_tuple() for event in page.items]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError("event page must be strictly sorted by its global event key")
    if any(
        not request.scope.start_at <= event.occurred_at < request.scope.end_at
        for event in page.items
    ):
        raise ValueError("event page item is outside the request time range")
    if request.after is not None and keys and keys[0] <= request.after.as_tuple():
        raise ValueError("event page did not advance beyond its request after key")

    pending_event_ids: set[str] = set()
    pending_evidence_ids: set[str] = set()
    for event in page.items:
        validated_set.identity_resolver.validate_event(event)
        if event.event_id in scan_session._event_ids or event.event_id in pending_event_ids:
            raise ValueError("duplicate event_id within one event scan")
        if (
            event.evidence_id in scan_session._evidence_ids
            or event.evidence_id in pending_evidence_ids
        ):
            raise ValueError("duplicate evidence_id within one event scan")
        pending_event_ids.add(event.event_id)
        pending_evidence_ids.add(event.evidence_id)

    if keys and previous is not None and keys[0] <= previous:
        raise ValueError("event page chain must advance in stable keyset order")

    scan_session._snapshot_signature = signature
    if pinned_scope is None:
        scan_session._scope_by_source[expected_source_id] = request.scope.model_copy(deep=True)
    scan_session._event_ids.update(pending_event_ids)
    scan_session._evidence_ids.update(pending_evidence_ids)
    if keys:
        scan_session._last_key_by_source[expected_source_id] = keys[-1]


__all__ = [
    "EventValidationSession",
    "IdentityResolver",
    "PagedSourceAdapter",
    "SnapshotChangedError",
    "UnsupportedPaginationError",
    "ValidatedSourceSet",
    "prepare_validated_source_set",
    "validate_event_page",
]
