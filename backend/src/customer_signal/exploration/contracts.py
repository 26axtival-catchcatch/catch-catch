"""Strict native-page and run-reference contracts used by exploration."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from customer_signal.domain.models import (
    CustomerEvent,
    IdentityEdge,
    IdentityLinkType,
    IdentityRef,
    Scalar,
)
from customer_signal.domain.types import DimensionValue, MeasureValue, SourceId


type ToolStatus = Literal["success", "partial", "error"]
type ToolErrorCategory = Literal["validation", "transient", "permission", "business"]

type QueryRef = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
type ResultRef = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
type PageRef = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
type CohortRef = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
type CustomerRef = Annotated[str, Field(strict=True, min_length=1, max_length=128)]


class ExplorationContract(BaseModel):
    """Immutable strict values exchanged at the native exploration seam."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FrozenScalarMapping(Mapping[str, object]):
    """Copied read-only scalar mapping with deterministic deepcopy support."""

    __slots__ = ("__values",)

    def __init__(self, values: Mapping[str, object]) -> None:
        object.__setattr__(self, "_FrozenScalarMapping__values", dict(values))

    def __getitem__(self, key: str) -> object:
        return self.__values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.__values)

    def __len__(self) -> int:
        return len(self.__values)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise TypeError("FrozenScalarMapping is immutable")

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        copied = type(self)(self.__values)
        memo[id(self)] = copied
        return copied

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__values!r})"


class FrozenIdentityRef(IdentityRef):
    """Deeply immutable copy of one source identity inside a native page."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @classmethod
    def from_identity(cls, identity: IdentityRef) -> Self:
        return cls(namespace=identity.namespace, value=identity.value)


class FrozenIdentityEdge(IdentityEdge):
    """Deeply immutable identity edge snapshot stored by pages and resolvers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    left: FrozenIdentityRef
    right: FrozenIdentityRef

    @classmethod
    def from_edge(cls, edge: IdentityEdge) -> Self:
        return cls(
            left=FrozenIdentityRef.from_identity(edge.left),
            right=FrozenIdentityRef.from_identity(edge.right),
            link_type=edge.link_type,
            confidence=edge.confidence,
            provenance=edge.provenance,
        )


class FrozenCustomerEvent(CustomerEvent):
    """Deeply immutable customer-event snapshot used inside a native page."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    event_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    identities: tuple[FrozenIdentityRef, ...] = Field(default_factory=tuple)
    canonical_customer_id: str = Field(min_length=1)
    attributes: Mapping[str, Scalar] = Field(default_factory=dict)
    dimensions: Mapping[str, DimensionValue] = Field(default_factory=dict)
    measures: Mapping[str, MeasureValue] = Field(default_factory=dict)

    @field_validator("occurred_at", mode="before")
    @classmethod
    def parse_json_timestamp(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value

    @field_validator("identities", mode="before")
    @classmethod
    def freeze_identities(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(
                FrozenIdentityRef.from_identity(identity)
                if isinstance(identity, IdentityRef)
                else identity
                for identity in value
            )
        return value

    @field_validator("attributes", "dimensions", "measures", mode="after")
    @classmethod
    def freeze_scalar_mapping(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        return FrozenScalarMapping(value)

    @field_serializer("attributes", "dimensions", "measures")
    def serialize_scalar_mapping(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)

    @classmethod
    def from_event(cls, event: CustomerEvent) -> Self:
        return cls(
            event_id=event.event_id,
            evidence_id=event.evidence_id,
            source_id=event.source_id,
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            action=event.action,
            topic=event.topic,
            outcome=event.outcome,
            text=event.text,
            identities=tuple(
                FrozenIdentityRef.from_identity(identity) for identity in event.identities
            ),
            canonical_customer_id=event.canonical_customer_id,
            attributes=dict(event.attributes),
            dimensions=dict(event.dimensions),
            measures=dict(event.measures),
        )


class EventSortKey(ExplorationContract):
    """Globally stable event keyset key."""

    occurred_at: AwareDatetime
    source_id: SourceId
    event_id: str = Field(min_length=1)

    @classmethod
    def from_event(cls, event: CustomerEvent) -> Self:
        return cls(
            occurred_at=event.occurred_at,
            source_id=event.source_id,
            event_id=event.event_id,
        )

    def as_tuple(self) -> tuple[datetime, str, str]:
        return (self.occurred_at, self.source_id, self.event_id)


class IdentityEdgeSortKey(ExplorationContract):
    """Stable raw identity-edge key; no graph normalization is applied."""

    left_namespace: str = Field(min_length=1)
    left_value: str = Field(min_length=1)
    right_namespace: str = Field(min_length=1)
    right_value: str = Field(min_length=1)
    link_type: IdentityLinkType

    @classmethod
    def from_edge(cls, edge: IdentityEdge) -> Self:
        return cls(
            left_namespace=edge.left.namespace,
            left_value=edge.left.value,
            right_namespace=edge.right.namespace,
            right_value=edge.right.value,
            link_type=edge.link_type,
        )

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        return (
            self.left_namespace,
            self.left_value,
            self.right_namespace,
            self.right_value,
            self.link_type,
        )


class EventPageState(ExplorationContract):
    """Event-chain continuation state."""

    has_more: bool
    next_key: EventSortKey | None

    @model_validator(mode="after")
    def validate_next_key(self) -> Self:
        if self.has_more != (self.next_key is not None):
            raise ValueError("next_key must exist exactly when has_more is true")
        return self


class IdentityPageState(ExplorationContract):
    """Identity-chain continuation state, intentionally distinct from event state."""

    has_more: bool
    next_key: IdentityEdgeSortKey | None

    @model_validator(mode="after")
    def validate_next_key(self) -> Self:
        if self.has_more != (self.next_key is not None):
            raise ValueError("next_key must exist exactly when has_more is true")
        return self


class ExplorationSourceScope(ExplorationContract):
    """Selected sources and half-open time range for an unbounded native scan."""

    source_ids: tuple[SourceId, ...] = Field(min_length=1, max_length=32)
    start_at: AwareDatetime
    end_at: AwareDatetime
    native_page_size: int = Field(strict=True, ge=1, le=200)

    @field_validator("source_ids", mode="before")
    @classmethod
    def freeze_sources(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_ids")
    @classmethod
    def require_unique_sources(cls, value: tuple[SourceId, ...]) -> tuple[SourceId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return value

    @model_validator(mode="after")
    def require_half_open_interval(self) -> Self:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before exclusive end_at")
        return self


class SourcePageRequest(ExplorationContract):
    """One adapter-local event page request."""

    scope: ExplorationSourceScope
    after: EventSortKey | None = None
    page_size: int = Field(strict=True, ge=1, le=200)


class IdentityPageRequest(ExplorationContract):
    """One adapter-local raw identity page request."""

    scope: ExplorationSourceScope
    after: IdentityEdgeSortKey | None = None
    page_size: int = Field(strict=True, ge=1, le=200)


class SourceEventPage(EventPageState):
    """A bounded native event page with an exact keyset continuation key."""

    items: tuple[FrozenCustomerEvent, ...] = Field(default_factory=tuple, max_length=200)

    @field_validator("items", mode="before")
    @classmethod
    def freeze_items(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(
                FrozenCustomerEvent.from_event(event)
                if isinstance(event, CustomerEvent)
                else event
                for event in value
            )
        return value

    @model_validator(mode="after")
    def bind_next_key_to_last_item(self) -> Self:
        if self.has_more:
            if not self.items:
                raise ValueError("items must not be empty when has_more is true")
            if self.next_key != EventSortKey.from_event(self.items[-1]):
                raise ValueError("next_key must equal the last item event sort key")
        return self


class IdentityPage(IdentityPageState):
    """A bounded raw identity-edge page with an exact continuation key."""

    items: tuple[FrozenIdentityEdge, ...] = Field(default_factory=tuple, max_length=200)

    @field_validator("items", mode="before")
    @classmethod
    def freeze_items(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(
                FrozenIdentityEdge.from_edge(edge)
                if isinstance(edge, IdentityEdge)
                else edge
                for edge in value
            )
        return value

    @model_validator(mode="after")
    def bind_next_key_to_last_item(self) -> Self:
        if self.has_more:
            if not self.items:
                raise ValueError("items must not be empty when has_more is true")
            if self.next_key != IdentityEdgeSortKey.from_edge(self.items[-1]):
                raise ValueError("next_key must equal the last item identity sort key")
        return self


class ToolError(ExplorationContract):
    """Public, actionable exploration Tool failure."""

    category: ToolErrorCategory
    is_retryable: bool
    message: str = Field(min_length=1, max_length=1_000)


__all__ = [
    "CohortRef",
    "CustomerRef",
    "EventPageState",
    "EventSortKey",
    "ExplorationSourceScope",
    "FrozenCustomerEvent",
    "FrozenIdentityEdge",
    "FrozenIdentityRef",
    "FrozenScalarMapping",
    "IdentityEdgeSortKey",
    "IdentityPage",
    "IdentityPageRequest",
    "IdentityPageState",
    "PageRef",
    "QueryRef",
    "ResultRef",
    "SourceEventPage",
    "SourcePageRequest",
    "ToolError",
    "ToolErrorCategory",
    "ToolStatus",
]
