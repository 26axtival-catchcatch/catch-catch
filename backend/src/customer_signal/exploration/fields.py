"""Capability-safe semantic field compiler for exploration Tool queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from customer_signal.domain.models import CustomerEvent
from customer_signal.domain.sources import DimensionDescriptor, MeasureDescriptor, SourceManifest
from customer_signal.exploration.reader import DataSpacePermissionError, DataSpaceReader
from customer_signal.exploration.tool_contracts import (
    ComparisonPredicate,
    ExistsPredicate,
    ExplorationFieldRef,
    MembershipPredicate,
    Predicate,
    TextPredicate,
)


class FieldValidationError(ValueError):
    """An Agent field reference or predicate is outside its public capability."""


@dataclass(frozen=True, slots=True)
class PublicFieldDefinition:
    source_id: str
    scope: str
    name: str
    data_type: str
    nullable: bool
    value_access: str


@dataclass(frozen=True, slots=True)
class FieldLookup:
    applicable: bool
    value: object


_CANONICAL_FIELDS: Final[dict[str, str]] = {
    "source_id": "string",
    "occurred_at": "timestamp",
    "event_type": "string",
    "action": "string",
    "topic": "string",
    "outcome": "string",
}


class ExplorationFieldCompiler:
    """Compile only catalog-published semantic fields, never storage columns or PII."""

    def __init__(self, reader: DataSpaceReader) -> None:
        self._reader = reader

    def public_fields(self, source_ids: tuple[str, ...]) -> tuple[PublicFieldDefinition, ...]:
        selected = self._reader.validate_source_ids(source_ids)
        items: list[PublicFieldDefinition] = []
        for source_id in selected:
            manifest = self._reader.manifest(source_id)
            items.extend(
                PublicFieldDefinition(
                    source_id=source_id,
                    scope="canonical",
                    name=name,
                    data_type=data_type,
                    nullable=False,
                    value_access=(
                        "cardinality_only" if name == "occurred_at" else "enumerable"
                    ),
                )
                for name, data_type in _CANONICAL_FIELDS.items()
            )
            items.extend(self._public_dimensions(manifest))
            items.extend(self._public_measures(manifest))
        return tuple(sorted(items, key=lambda item: (item.source_id, item.scope, item.name)))

    def validate_field(
        self,
        field: ExplorationFieldRef,
        source_ids: tuple[str, ...],
        *,
        numeric_required: bool = False,
        value_access_required: bool = False,
    ) -> str:
        selected = self._reader.validate_source_ids(source_ids)
        if field.scope == "canonical":
            data_type = _CANONICAL_FIELDS.get(field.name)
            if data_type is None:
                raise FieldValidationError("canonical field is not public or does not exist")
        else:
            assert field.source_id is not None
            if field.source_id not in selected:
                raise DataSpacePermissionError(
                    "source-specific field is outside the query source selection"
                )
            manifest = self._reader.manifest(field.source_id)
            descriptor: DimensionDescriptor | MeasureDescriptor | None
            descriptor = (
                manifest.dimensions.get(field.name)
                if field.scope == "dimension"
                else manifest.measures.get(field.name)
            )
            if descriptor is None:
                raise FieldValidationError("source-specific semantic field does not exist")
            if descriptor.pii_classification != "none":
                raise DataSpacePermissionError("PII-classified fields are not public")
            if isinstance(descriptor, DimensionDescriptor):
                if descriptor.semantic_type == "identifier":
                    raise DataSpacePermissionError(
                        "identifier dimensions are not public exploration fields"
                    )
                data_type = {
                    "boolean": "boolean",
                    "category": "string",
                    "text": "text",
                }[descriptor.semantic_type]
            else:
                data_type = descriptor.semantic_type
        if numeric_required and field.scope != "measure":
            raise FieldValidationError("this operation requires a measure field")
        if (
            value_access_required
            and field.scope == "canonical"
            and field.name == "occurred_at"
        ):
            raise FieldValidationError(
                "occurred_at exact values and group_by are unavailable; "
                "use timestamp predicates or summarize_events time_bucket"
            )
        if value_access_required and data_type == "text":
            raise DataSpacePermissionError(
                "free-text dimensions cannot be filtered, grouped, enumerated, or exported"
            )
        return data_type

    def validate_predicate(
        self, predicate: Predicate, source_ids: tuple[str, ...]
    ) -> None:
        data_type = self.validate_field(
            predicate.field,
            source_ids,
            value_access_required=not (
                predicate.field.scope == "canonical"
                and predicate.field.name == "occurred_at"
            ),
        )
        if isinstance(predicate, TextPredicate) and data_type != "string":
            raise FieldValidationError("text predicates require a string field")
        if isinstance(predicate, ComparisonPredicate):
            if predicate.operator in {"gt", "gte", "lt", "lte"} and data_type not in {
                "integer",
                "number",
                "timestamp",
            }:
                raise FieldValidationError(
                    "ordered comparison requires a numeric or timestamp field"
                )
            self._validate_value_type(predicate.value, data_type)
        if isinstance(predicate, MembershipPredicate):
            for value in predicate.values:
                self._validate_value_type(value, data_type)

    def lookup(self, event: CustomerEvent, field: ExplorationFieldRef) -> FieldLookup:
        if field.scope == "canonical":
            return FieldLookup(True, getattr(event, field.name))
        if event.source_id != field.source_id:
            return FieldLookup(False, None)
        values = event.dimensions if field.scope == "dimension" else event.measures
        return FieldLookup(True, values.get(field.name))

    def matches(
        self,
        event: CustomerEvent,
        predicates: tuple[Predicate, ...],
    ) -> bool:
        return all(self._matches_one(event, predicate) for predicate in predicates)

    def _matches_one(self, event: CustomerEvent, predicate: Predicate) -> bool:
        lookup = self.lookup(event, predicate.field)
        # A source-bound field is NOT_APPLICABLE on every other source.  It must
        # never make ne/not_in/exists(false) accidentally include those events.
        if not lookup.applicable:
            return False
        current = lookup.value
        if isinstance(predicate, ExistsPredicate):
            return (current is not None) == predicate.present
        if current is None:
            return False
        if isinstance(predicate, ComparisonPredicate):
            expected = self._comparison_value(predicate.value, current)
            return {
                "eq": current == expected,
                "ne": current != expected,
                "gt": current > expected,
                "gte": current >= expected,
                "lt": current < expected,
                "lte": current <= expected,
            }[predicate.operator]
        if isinstance(predicate, MembershipPredicate):
            expected_values = tuple(
                self._comparison_value(value, current) for value in predicate.values
            )
            included = current in expected_values
            return included if predicate.operator == "in" else not included
        assert isinstance(predicate, TextPredicate)
        haystack = str(current)
        needle = predicate.value
        if not predicate.case_sensitive:
            haystack = haystack.casefold()
            needle = needle.casefold()
        if predicate.operator == "contains":
            return needle in haystack
        return haystack.startswith(needle)

    @staticmethod
    def _comparison_value(value: object, current: object) -> object:
        if isinstance(current, datetime) and isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as error:
                raise FieldValidationError("timestamp comparison value is invalid") from error
            if parsed.tzinfo is None:
                raise FieldValidationError("timestamp comparison value must include timezone")
            return parsed
        return value

    @staticmethod
    def _validate_value_type(value: object, data_type: str) -> None:
        valid = {
            "string": type(value) is str,
            "boolean": type(value) is bool,
            "integer": type(value) is int,
            "number": type(value) in (int, float),
            "timestamp": type(value) is str,
        }[data_type]
        if not valid:
            raise FieldValidationError("predicate value type does not match field catalog")

    @staticmethod
    def _public_dimensions(manifest: SourceManifest) -> list[PublicFieldDefinition]:
        fields = []
        for name, descriptor in manifest.dimensions.items():
            if descriptor.pii_classification != "none":
                continue
            fields.append(
                PublicFieldDefinition(
                    source_id=manifest.source_id,
                    scope="dimension",
                    name=name,
                    data_type=(
                        {
                            "boolean": "boolean",
                            "category": "string",
                            "text": "text",
                            "identifier": "string",
                        }[descriptor.semantic_type]
                    ),
                    nullable=True,
                    value_access=(
                        "cardinality_only"
                        if descriptor.semantic_type in {"identifier", "text"}
                        else "enumerable"
                    ),
                )
            )
        return fields

    @staticmethod
    def _public_measures(manifest: SourceManifest) -> list[PublicFieldDefinition]:
        return [
            PublicFieldDefinition(
                source_id=manifest.source_id,
                scope="measure",
                name=name,
                data_type=descriptor.semantic_type,
                nullable=True,
                value_access="enumerable",
            )
            for name, descriptor in manifest.measures.items()
            if descriptor.pii_classification == "none"
        ]


__all__ = [
    "ExplorationFieldCompiler",
    "FieldLookup",
    "FieldValidationError",
    "PublicFieldDefinition",
]
