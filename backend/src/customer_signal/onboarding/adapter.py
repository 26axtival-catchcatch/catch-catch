"""Streaming table adapter projecting raw rows onto canonical source contracts."""

from __future__ import annotations

import json
import re
from bisect import insort
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from customer_signal.domain.models import (
    CustomerEvent,
    EvidenceRecord,
    IdentityEdge,
    IdentityLinkType,
    IdentityRef,
)
from customer_signal.domain.primitive_catalog import all_capabilities
from customer_signal.domain.sources import (
    DimensionDescriptor,
    EventScope,
    IdentityQualityDescriptor,
    MaskingPolicy,
    MeasureDescriptor,
    SourceManifest,
    TimeRange,
)
from customer_signal.domain.types import GenericPrimitiveName
from customer_signal.exploration.contracts import (
    EventSortKey,
    ExplorationSourceScope,
    IdentityEdgeSortKey,
    IdentityPage,
    IdentityPageRequest,
    SourceEventPage,
    SourcePageRequest,
)
from customer_signal.onboarding.profiler import TableProfile, profile_table
from customer_signal.onboarding.spec import FieldRule, SourceMappingSpec
from customer_signal.onboarding.table_pages import TablePageReader, open_table_page_reader


ONBOARDED_ADAPTER_VERSION = "1"
_ALL_CAPABILITIES: frozenset[GenericPrimitiveName] = all_capabilities()
_TRUTHY = {"true", "t", "yes", "y", "1"}
_FALSY = {"false", "f", "no", "n", "0"}
_SIGNED_INTEGER = re.compile(r"^[+-]?\d+$")


class MappingError(ValueError):
    """A raw row could not be projected onto the canonical contract."""


def _apply_rule(rule: FieldRule, row: Mapping[str, object], field: str) -> str:
    if rule.const is not None:
        return rule.const
    column = cast(str, rule.column)
    raw = row.get(column)
    if raw is None:
        if rule.default is not None:
            return rule.default
        raise MappingError(f"{field}: column {column!r} is null and no default is set")
    value = str(raw)
    if rule.value_map is not None:
        mapped = rule.value_map.get(value, rule.default)
        if mapped is None:
            raise MappingError(f"{field}: value {value!r} is not covered by value_map")
        return mapped
    return value


def _as_bool(raw: object, column: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str) and raw.casefold() in _TRUTHY | _FALSY:
        return raw.casefold() in _TRUTHY
    raise MappingError(f"boolean dimension column {column!r} has non-boolean value {raw!r}")


def _as_integer(raw: object, column: str) -> int:
    if isinstance(raw, bool):
        raise MappingError(f"integer measure column {column!r} has value {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, Decimal) and raw == raw.to_integral_value():
        return int(raw)
    if isinstance(raw, str) and _SIGNED_INTEGER.fullmatch(raw):
        return int(raw)
    raise MappingError(f"integer measure column {column!r} has value {raw!r}")


def _as_number(raw: object, column: str) -> float:
    if isinstance(raw, bool):
        raise MappingError(f"number measure column {column!r} has value {raw!r}")
    try:
        value = float(raw) if isinstance(raw, (int, float, Decimal, str)) else float("nan")
    except ValueError as error:
        raise MappingError(
            f"number measure column {column!r} has value {raw!r}"
        ) from error
    if not isfinite(value):
        raise MappingError(f"number measure column {column!r} has value {raw!r}")
    return value


def _as_timestamp(raw: object, column: str, timezone: str) -> datetime:
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as error:
            raise MappingError(
                f"timestamp column {column!r} has unparsable value {raw!r}"
            ) from error
    else:
        raise MappingError(f"timestamp column {column!r} has non-timestamp value {raw!r}")
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        except ZoneInfoNotFoundError as error:
            raise MappingError(f"unknown mapping timezone: {timezone}") from error
    return parsed


def _project_row(
    spec: SourceMappingSpec, row: Mapping[str, object]
) -> tuple[datetime, dict[str, object]]:
    occurred_at = _as_timestamp(
        row.get(spec.timestamp_column), spec.timestamp_column, spec.timezone
    )
    customer_raw = row.get(spec.identity.customer_column)
    if customer_raw is None:
        raise MappingError(f"customer column {spec.identity.customer_column!r} is null")
    customer = str(customer_raw)
    if not customer:
        raise MappingError(f"customer column {spec.identity.customer_column!r} is empty")

    dimensions: dict[str, object] = {}
    for name, item in spec.dimensions.items():
        raw = row.get(item.column)
        if raw is None:
            dimensions[name] = None
        elif item.semantic_type == "boolean":
            dimensions[name] = _as_bool(raw, item.column)
        else:
            dimensions[name] = str(raw)

    measures: dict[str, object] = {}
    for name, item in spec.measures.items():
        raw = row.get(item.column)
        if raw is None:
            continue
        if item.semantic_type == "integer":
            measures[name] = _as_integer(raw, item.column)
        else:
            measures[name] = _as_number(raw, item.column)

    return occurred_at, {
        "event_type": _apply_rule(spec.event_type, row, "event_type"),
        "action": _apply_rule(spec.action, row, "action"),
        "topic": _apply_rule(spec.topic, row, "topic"),
        "outcome": _apply_rule(spec.outcome, row, "outcome"),
        "text": _apply_rule(spec.text, row, "text"),
        "identities": [IdentityRef(namespace=spec.identity.namespace, value=customer)],
        "canonical_customer_id": customer,
        "dimensions": dimensions,
        "measures": measures,
    }


def _event_identifier(source_id: str, ordinal: int) -> str:
    digest = sha256(f"{source_id}:{ordinal}".encode()).hexdigest()[:24]
    return f"{source_id}-{digest}"


def _event_from_row(
    spec: SourceMappingSpec,
    ordinal: int,
    row: Mapping[str, object],
) -> CustomerEvent:
    try:
        occurred_at, fields = _project_row(spec, row)
    except MappingError as error:
        raise MappingError(f"row {ordinal}: {error}") from error
    event_id = _event_identifier(spec.source_id, ordinal)
    return CustomerEvent(
        event_id=event_id,
        evidence_id=f"ev-{event_id}",
        source_id=spec.source_id,
        occurred_at=occurred_at,
        **fields,
    )


def _edge_from_event(spec: SourceMappingSpec, event: CustomerEvent) -> IdentityEdge:
    link_type = cast(IdentityLinkType, spec.identity.link_method.upper())
    return IdentityEdge(
        left=event.identities[0],
        right=IdentityRef(
            namespace="canonical_customer",
            value=event.canonical_customer_id,
        ),
        link_type=link_type,
        confidence=spec.identity.confidence,
        provenance=f"onboarded:{spec.source_id}",
    )


def _evidence_record(event: CustomerEvent) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=event.evidence_id,
        source_id=event.source_id,
        occurred_at=event.occurred_at,
        masked_customer_id="masked",
        summary=f"{event.event_type} event: topic={event.topic}; outcome={event.outcome}",
        raw_fields={},
    )


class _OnDemandEvidenceView(Mapping[str, EvidenceRecord]):
    """Compatibility mapping that never stores every evidence record."""

    def __init__(self, adapter: MappedTableAdapter) -> None:
        self._adapter = adapter

    def __getitem__(self, evidence_id: str) -> EvidenceRecord:
        try:
            return self._adapter.get_evidence([evidence_id])[0]
        except ValueError as error:
            raise KeyError(evidence_id) from error

    def __iter__(self) -> Iterator[str]:
        for ordinal, _ in self._adapter._reader.iter_rows():
            yield f"ev-{_event_identifier(self._adapter._spec.source_id, ordinal)}"

    def __len__(self) -> int:
        return self._adapter._profile.row_count


class MappedTableAdapter:
    """Expose one table through legacy and native paged source contracts."""

    def __init__(
        self,
        spec: SourceMappingSpec,
        reader: TablePageReader,
        profile: TableProfile,
    ) -> None:
        self._spec = spec
        self._reader = reader
        self._profile = profile
        self._manifest = self._build_manifest()
        self._evidence_view = _OnDemandEvidenceView(self)

    @classmethod
    def from_file(cls, spec: SourceMappingSpec, path: Path) -> MappedTableAdapter:
        profile = profile_table(path)
        return cls(spec, open_table_page_reader(path), profile)

    @property
    def evidence_prefix(self) -> str:
        return f"ev-{self._spec.source_id}-"

    @property
    def evidence_by_id(self) -> Mapping[str, EvidenceRecord]:
        """Legacy lazy view retained for callers that only inspect its size."""

        return self._evidence_view

    def describe(self) -> SourceManifest:
        return self._manifest

    def snapshot_token(self) -> str:
        spec_json = json.dumps(
            self._spec.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = sha256(spec_json.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self._reader.snapshot_token().encode("ascii"))
        return digest.hexdigest()

    def load_event_page(self, request: SourcePageRequest) -> SourceEventPage:
        self._validate_native_scope(request.scope)
        if request.after is not None and request.after.source_id != self._spec.source_id:
            raise ValueError("event page key belongs to another source")
        after = request.after.as_tuple() if request.after is not None else None
        candidate_limit = request.page_size + 1
        candidates: list[tuple[tuple[datetime, str, str], CustomerEvent]] = []
        for ordinal, row in self._reader.iter_rows():
            event = _event_from_row(self._spec, ordinal, row)
            if not request.scope.start_at <= event.occurred_at < request.scope.end_at:
                continue
            key = EventSortKey.from_event(event).as_tuple()
            if after is not None and key <= after:
                continue
            insort(candidates, (key, event))
            if len(candidates) > candidate_limit:
                candidates.pop()

        has_more = len(candidates) > request.page_size
        items = [event for _, event in candidates[: request.page_size]]
        return SourceEventPage(
            items=items,
            has_more=has_more,
            next_key=EventSortKey.from_event(items[-1]) if has_more else None,
        )

    def load_identity_page(self, request: IdentityPageRequest) -> IdentityPage:
        self._validate_native_scope(request.scope)
        after = request.after.as_tuple() if request.after is not None else None
        candidate_limit = request.page_size + 1
        candidates: dict[tuple[str, str, str, str, str], IdentityEdge] = {}
        for ordinal, row in self._reader.iter_rows():
            event = _event_from_row(self._spec, ordinal, row)
            if not request.scope.start_at <= event.occurred_at < request.scope.end_at:
                continue
            edge = _edge_from_event(self._spec, event)
            key = IdentityEdgeSortKey.from_edge(edge).as_tuple()
            if after is not None and key <= after:
                continue
            candidates[key] = edge
            if len(candidates) > candidate_limit:
                del candidates[max(candidates)]

        ordered = sorted(candidates.items())
        has_more = len(ordered) > request.page_size
        items = [edge for _, edge in ordered[: request.page_size]]
        return IdentityPage(
            items=items,
            has_more=has_more,
            next_key=IdentityEdgeSortKey.from_edge(items[-1]) if has_more else None,
        )

    def load_events(self, scope: EventScope) -> list[CustomerEvent]:
        self._validate_legacy_scope(scope)
        native_scope = ExplorationSourceScope(
            source_ids=[self._spec.source_id],
            start_at=scope.start_at,
            end_at=scope.end_at,
            native_page_size=min(scope.max_events, 200),
        )
        events: list[CustomerEvent] = []
        after = None
        while len(events) < scope.max_events:
            page_size = min(200, scope.max_events - len(events))
            page = self.load_event_page(
                SourcePageRequest(scope=native_scope, after=after, page_size=page_size)
            )
            events.extend(page.items)
            if not page.has_more:
                break
            after = page.next_key
        return events

    def load_identities(self, scope: EventScope) -> list[IdentityEdge]:
        self._validate_legacy_scope(scope)
        selected_customers = {event.canonical_customer_id for event in self.load_events(scope)}
        native_scope = ExplorationSourceScope(
            source_ids=[self._spec.source_id],
            start_at=scope.start_at,
            end_at=scope.end_at,
            native_page_size=200,
        )
        edges: list[IdentityEdge] = []
        after = None
        while True:
            page = self.load_identity_page(
                IdentityPageRequest(scope=native_scope, after=after, page_size=200)
            )
            edges.extend(
                edge
                for edge in page.items
                if edge.right.namespace == "canonical_customer"
                and edge.right.value in selected_customers
            )
            if not page.has_more:
                return edges
            after = page.next_key

    def get_evidence(self, allowed_evidence_ids: Sequence[str]) -> list[EvidenceRecord]:
        requested = list(allowed_evidence_ids)
        if any(
            not isinstance(evidence_id, str)
            or not evidence_id.startswith(self.evidence_prefix)
            for evidence_id in requested
        ):
            raise ValueError("evidence does not belong to this source")
        needed = set(requested)
        records: dict[str, EvidenceRecord] = {}
        for ordinal, row in self._reader.iter_rows():
            evidence_id = f"ev-{_event_identifier(self._spec.source_id, ordinal)}"
            if evidence_id not in needed:
                continue
            records[evidence_id] = _evidence_record(_event_from_row(self._spec, ordinal, row))
            if records.keys() >= needed:
                break
        missing = needed - records.keys()
        if missing:
            raise ValueError("evidence does not belong to this source")
        return [records[evidence_id] for evidence_id in requested]

    def _validate_native_scope(self, scope: ExplorationSourceScope) -> None:
        if scope.source_ids != (self._spec.source_id,):
            raise ValueError("mapped adapter scope must select its source only")

    def _validate_legacy_scope(self, scope: EventScope) -> None:
        if scope.source_ids != [self._spec.source_id]:
            raise ValueError("mapped adapter scope must select its source only")

    def _build_manifest(self) -> SourceManifest:
        missing = self._spec.referenced_columns() - {
            column.name for column in self._profile.columns
        }
        if missing:
            raise MappingError(f"spec references missing columns: {sorted(missing)}")

        minimum: datetime | None = None
        maximum: datetime | None = None
        event_types: set[str] = set()
        topics: set[str] = set()
        outcomes: set[str] = set()
        for ordinal, row in self._reader.iter_rows():
            event = _event_from_row(self._spec, ordinal, row)
            minimum = event.occurred_at if minimum is None else min(minimum, event.occurred_at)
            maximum = event.occurred_at if maximum is None else max(maximum, event.occurred_at)
            event_types.add(event.event_type)
            topics.add(event.topic)
            outcomes.add(event.outcome)
            if len(event_types) > 128 or len(topics) > 512 or len(outcomes) > 512:
                raise MappingError("mapped source semantic vocabulary exceeds manifest bounds")
        if minimum is None or maximum is None:
            raise MappingError("table has no rows to onboard")

        dimensions = {
            name: DimensionDescriptor(
                semantic_type=item.semantic_type,
                description=item.description,
                pii_classification=item.pii_classification,
            )
            for name, item in self._spec.dimensions.items()
        }
        measures = {
            name: MeasureDescriptor(
                semantic_type=item.semantic_type,
                description=item.description,
                unit=item.unit,
            )
            for name, item in self._spec.measures.items()
        }
        masking_rules = {
            name: item.masking
            for name, item in self._spec.dimensions.items()
            if item.masking is not None
        }
        return SourceManifest(
            source_id=self._spec.source_id,
            label=self._spec.label,
            description=self._spec.description,
            adapter_version=ONBOARDED_ADAPTER_VERSION,
            manifest_version="1",
            data_interval=TimeRange(
                start_at=minimum,
                end_at=maximum + timedelta(microseconds=1),
            ),
            refresh_cadence="static_demo",
            supported_event_types=frozenset(event_types),
            supported_topics=frozenset(topics),
            supported_outcomes=frozenset(outcomes),
            dimensions=dimensions,
            measures=measures,
            capabilities=_ALL_CAPABILITIES,
            masking_policy=MaskingPolicy(rules=masking_rules),
            identity_quality=IdentityQualityDescriptor(
                namespace=self._spec.identity.namespace,
                link_method=self._spec.identity.link_method,
                confidence=self._spec.identity.confidence,
            ),
        )


class CompositeEvidenceProvider:
    """Route deterministic evidence prefixes without materializing a merged index."""

    def __init__(self, base, adapters: Sequence[MappedTableAdapter]) -> None:
        self._base = base
        self._routes: dict[str, MappedTableAdapter] = {}
        for adapter in adapters:
            if adapter.evidence_prefix in self._routes:
                raise ValueError("mapped evidence prefixes must be unique")
            self._routes[adapter.evidence_prefix] = adapter

    def get_evidence(self, allowed_evidence_ids: Sequence[str]) -> list[EvidenceRecord]:
        requested = list(allowed_evidence_ids)
        by_adapter: dict[MappedTableAdapter, list[str]] = {}
        base_ids: list[str] = []
        ordered_routes = sorted(self._routes.items(), key=lambda item: len(item[0]), reverse=True)
        for evidence_id in requested:
            adapter = next(
                (
                    candidate
                    for prefix, candidate in ordered_routes
                    if evidence_id.startswith(prefix)
                ),
                None,
            )
            if adapter is None:
                base_ids.append(evidence_id)
            else:
                by_adapter.setdefault(adapter, []).append(evidence_id)

        records: dict[str, EvidenceRecord] = {}
        for adapter, evidence_ids in by_adapter.items():
            records.update(
                (record.evidence_id, record) for record in adapter.get_evidence(evidence_ids)
            )
        if base_ids:
            if self._base is None:
                raise ValueError("evidence does not belong to a registered source")
            records.update(
                (record.evidence_id, record)
                for record in self._base.get_evidence(base_ids)
            )
        try:
            return [records[evidence_id] for evidence_id in requested]
        except KeyError as error:
            raise ValueError("evidence provider did not return every requested ID") from error


def load_onboarded_adapters(directory: Path) -> list[MappedTableAdapter]:
    """Build reader-backed adapters for every approved spec under ``directory``."""

    if not directory.exists():
        return []
    adapters = []
    for spec_path in sorted(directory.glob("*/spec.json")):
        spec = SourceMappingSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        if spec.status != "approved":
            continue
        data_files = [
            candidate
            for candidate in spec_path.parent.iterdir()
            if candidate.suffix.lower() in (".csv", ".parquet", ".pq")
        ]
        if len(data_files) != 1:
            raise ValueError(f"{spec_path.parent} must contain exactly one data file")
        adapters.append(MappedTableAdapter.from_file(spec, data_files[0]))
    return adapters


__all__ = [
    "CompositeEvidenceProvider",
    "MappedTableAdapter",
    "MappingError",
    "ONBOARDED_ADAPTER_VERSION",
    "load_onboarded_adapters",
]
