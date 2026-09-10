"""Fail-closed run ledger for Tool pages and public exploration lineage."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_signal.exploration.contracts import (
    CohortRef,
    CustomerRef,
    PageRef,
    QueryRef,
    ResultRef,
)
from customer_signal.exploration.materialization import (
    MaterializationError,
    RunMaterializationStore,
    StaleSnapshotReferenceError,
    UnknownMaterializationReferenceError,
)
from customer_signal.exploration.tool_contracts import PublicExplorationItem


type ExplorationReadToolName = Literal[
    "inspect_data_space",
    "summarize_events",
    "analyze_event_sequences",
    "read_event_evidence",
]


class ExplorationLedgerError(ValueError):
    """A Tool page cannot be joined to the active run lineage."""


class _LedgerContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ToolPageObservation(_LedgerContract):
    """One cursor-free Tool page retained for validation and audit."""

    tool_name: ExplorationReadToolName
    result_kind: str = Field(min_length=1, max_length=64)
    request_json: str = Field(min_length=2, max_length=100_000)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    query_ref: QueryRef
    result_ref: ResultRef
    page_ref: PageRef
    parent_page_ref: PageRef | None = None
    request_cursor_fingerprint: str | None = Field(
        default=None, min_length=1, max_length=128
    )
    next_cursor_fingerprint: str | None = Field(
        default=None, min_length=1, max_length=128
    )
    page_index: int = Field(strict=True, ge=0)
    page_size: int = Field(strict=True, ge=1, le=200)
    returned_count: int = Field(strict=True, ge=0)
    matched_count: int | None = Field(default=None, strict=True, ge=0)
    has_more: bool
    scan_complete: bool
    snapshot_id: str = Field(min_length=16, max_length=128)
    query_fingerprint: str = Field(min_length=16, max_length=128)
    parent_result_ref: ResultRef | None = None
    items: tuple[PublicExplorationItem, ...] = Field(default_factory=tuple, max_length=200)

    @field_validator("source_ids", "items", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_ids")
    @classmethod
    def normalize_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(value))
        if len(normalized) != len(set(normalized)):
            raise ValueError("source_ids must be unique")
        return normalized

    @field_validator("request_json")
    @classmethod
    def require_cursor_free_request(cls, value: str) -> str:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("request_json must contain valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("request_json must contain a JSON object")
        if "cursor" in decoded:
            raise ValueError("request_json must not retain the raw cursor")
        return value

    @model_validator(mode="after")
    def validate_page_state(self) -> Self:
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must equal the retained item count")
        if self.has_more != (self.next_cursor_fingerprint is not None):
            raise ValueError(
                "next_cursor_fingerprint must exist exactly when has_more is true"
            )
        if self.page_index == 0:
            if self.parent_page_ref is not None or self.request_cursor_fingerprint is not None:
                raise ValueError("first page cannot have a parent page or request cursor")
        elif self.parent_page_ref is None or self.request_cursor_fingerprint is None:
            raise ValueError("continued pages require parent page and request cursor")
        if not self.scan_complete and self.matched_count is not None:
            raise ValueError("partial input scans cannot claim matched_count")
        return self


class ExplorationQueryRecord(_LedgerContract):
    query_ref: QueryRef
    result_ref: ResultRef
    tool_name: ExplorationReadToolName
    result_kind: str
    source_ids: tuple[str, ...]
    snapshot_id: str
    query_fingerprint: str
    request_json: str
    pages: tuple[ToolPageObservation, ...]


class ExplorationPageLineage(_LedgerContract):
    query_ref: QueryRef
    result_ref: ResultRef
    page_ref: PageRef
    parent_page_ref: PageRef | None
    page_index: int = Field(strict=True, ge=0)
    returned_count: int = Field(strict=True, ge=0)
    has_more: bool
    scan_complete: bool


class ExplorationLedgerSnapshot(_LedgerContract):
    ledger_version: Literal["1"] = "1"
    run_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(strict=True, ge=0)
    catalog_sources_complete: bool
    catalog_fields_complete: bool
    catalog_complete: bool
    completed_query_refs: tuple[QueryRef, ...]
    open_query_refs: tuple[QueryRef, ...]
    pages: tuple[ExplorationPageLineage, ...]


class ExplorationLedger:
    """Own ordered, idempotent Tool page lineage for one materialization run."""

    def __init__(
        self,
        run_id: str,
        materializations: RunMaterializationStore,
        *,
        authorized_source_ids: Sequence[str] | None = None,
    ) -> None:
        if run_id != materializations.run_id:
            raise ValueError("ledger and materialization run_id must match")
        self.run_id = run_id
        self.materializations = materializations
        self._generation = materializations.generation
        self._queries: dict[str, list[ToolPageObservation]] = {}
        self._result_to_query: dict[str, str] = {}
        self._page_refs: set[str] = set()
        self._cursor_reads: dict[str, ToolPageObservation] = {}
        self._stale_query_refs: set[str] = set()
        self._customer_refs: dict[str, str] = {}
        self._authorized_source_ids: tuple[str, ...] = ()
        if authorized_source_ids is not None:
            self.bind_active_source_ids(authorized_source_ids)

    @property
    def generation(self) -> int:
        return self._generation

    def assert_current_generation(self) -> None:
        if self.materializations.generation != self._generation:
            raise StaleSnapshotReferenceError(
                "ledger belongs to a stale snapshot generation"
            )

    def record_page(self, observation: ToolPageObservation) -> ToolPageObservation:
        """Validate and append one page, returning an earlier idempotent read as-is."""

        self.assert_current_generation()
        meta = self.materializations.read_result(observation.result_ref)
        is_evidence = observation.result_kind == "evidence"
        if is_evidence != (observation.tool_name == "read_event_evidence"):
            raise ExplorationLedgerError(
                "read_event_evidence and evidence result_kind must be bound together"
            )
        if is_evidence != (observation.parent_result_ref is not None):
            raise ExplorationLedgerError(
                "parent_result_ref must exist exactly for evidence results"
            )
        if meta.parent_result_ref != observation.parent_result_ref:
            raise ExplorationLedgerError(
                "Tool page parent_result_ref does not match its materialized result"
            )
        if meta.parent_result_ref is not None:
            try:
                self.require_result(meta.parent_result_ref)
            except UnknownMaterializationReferenceError as error:
                raise ExplorationLedgerError(
                    "parent_result_ref must identify an observed result in this ledger"
                ) from error
        if (
            meta.query_ref != observation.query_ref
            or meta.result_kind != observation.result_kind
            or meta.query_fingerprint != observation.query_fingerprint
            or meta.snapshot_id != observation.snapshot_id
            or meta.source_ids != observation.source_ids
            or meta.scan_complete != observation.scan_complete
            or meta.matched_count != observation.matched_count
        ):
            raise ExplorationLedgerError(
                "Tool page does not match its immutable materialized result"
            )
        expected_page_ref = self.materializations.make_ref(
            "page", stable_value=f"{observation.result_ref}\0{observation.page_index}"
        )
        if observation.page_ref != expected_page_ref:
            raise ExplorationLedgerError("page reference does not match its result and index")

        cursor_key = observation.request_cursor_fingerprint
        if cursor_key is not None and cursor_key in self._cursor_reads:
            recorded = self._cursor_reads[cursor_key]
            if recorded != observation:
                raise ExplorationLedgerError("same cursor returned a different Tool page")
            return recorded

        pages = self._queries.get(observation.query_ref)
        if pages is None:
            if observation.page_index != 0:
                raise ExplorationLedgerError("page index must start at zero without gaps")
            if observation.parent_page_ref is not None:
                raise ExplorationLedgerError("first page cannot claim a parent page")
            previous_query = self._result_to_query.get(observation.result_ref)
            if previous_query is not None and previous_query != observation.query_ref:
                raise ExplorationLedgerError("result reference is already bound to another query")
            pages = []
            self._queries[observation.query_ref] = pages
            self._result_to_query[observation.result_ref] = observation.query_ref
        else:
            first = pages[0]
            if (
                observation.result_ref != first.result_ref
                or observation.result_kind != first.result_kind
                or observation.tool_name != first.tool_name
                or observation.source_ids != first.source_ids
                or observation.query_fingerprint != first.query_fingerprint
                or observation.request_json != first.request_json
                or observation.parent_result_ref != first.parent_result_ref
            ):
                raise ExplorationLedgerError(
                    "query chain bindings, including parent_result_ref, changed between pages"
                )
            if observation.page_index < len(pages):
                recorded = pages[observation.page_index]
                if recorded == observation:
                    return recorded
                raise ExplorationLedgerError("same page index returned a different Tool page")
            if observation.page_index != len(pages):
                raise ExplorationLedgerError("page index must be continuous without gaps")
            previous = pages[-1]
            if not previous.has_more:
                raise ExplorationLedgerError("a terminal query chain cannot accept another page")
            if observation.parent_page_ref != previous.page_ref:
                raise ExplorationLedgerError("parent page must be the immediately preceding page")
            if observation.request_cursor_fingerprint != previous.next_cursor_fingerprint:
                raise ExplorationLedgerError("continued page does not use the issued cursor")

        if observation.page_ref in self._page_refs:
            raise ExplorationLedgerError("page reference is already bound in this ledger")
        pages.append(observation)
        self._page_refs.add(observation.page_ref)
        if cursor_key is not None:
            self._cursor_reads[cursor_key] = observation
        return observation

    def require_query(self, query_ref: QueryRef) -> ExplorationQueryRecord:
        self.assert_current_generation()
        if query_ref in self._stale_query_refs:
            raise StaleSnapshotReferenceError("query reference belongs to a stale snapshot")
        pages = self._queries.get(query_ref)
        if not pages:
            raise UnknownMaterializationReferenceError("query reference is unknown")
        first = pages[0]
        return ExplorationQueryRecord(
            query_ref=first.query_ref,
            result_ref=first.result_ref,
            tool_name=first.tool_name,
            result_kind=first.result_kind,
            source_ids=first.source_ids,
            snapshot_id=first.snapshot_id,
            query_fingerprint=first.query_fingerprint,
            request_json=first.request_json,
            pages=tuple(pages),
        )

    def require_result(self, result_ref: ResultRef) -> ExplorationQueryRecord:
        query_ref = self._result_to_query.get(result_ref)
        if query_ref is None:
            self.materializations.read_result(result_ref)
            raise UnknownMaterializationReferenceError(
                "result reference has not been observed by this ledger"
            )
        return self.require_query(query_ref)

    def is_complete(self, query_ref: QueryRef) -> bool:
        record = self.require_query(query_ref)
        return bool(
            record.pages
            and not record.pages[-1].has_more
            and all(page.scan_complete for page in record.pages)
        )

    def complete_query_refs(self) -> frozenset[QueryRef]:
        self.assert_current_generation()
        return frozenset(
            query_ref for query_ref in self._queries if self.is_complete(query_ref)
        )

    @property
    def open_query_refs(self) -> frozenset[QueryRef]:
        self.assert_current_generation()
        return frozenset(
            query_ref for query_ref in self._queries if not self.is_complete(query_ref)
        )

    def bind_active_source_ids(self, source_ids: Sequence[str]) -> None:
        normalized = tuple(sorted(source_ids))
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("active source_ids must be non-empty and unique")
        if self._authorized_source_ids and self._authorized_source_ids != normalized:
            raise ValueError("ledger active source_ids are immutable for one run")
        self._authorized_source_ids = normalized

    def _complete_catalog_sources(self, result_kind: str) -> frozenset[str]:
        return frozenset(
            source_id
            for query_ref in self._queries
            if self.require_query(query_ref).result_kind == result_kind
            and self.is_complete(query_ref)
            for source_id in self.require_query(query_ref).source_ids
        )

    def catalog_sources_cover(self, source_ids: Sequence[str]) -> bool:
        return self._complete_catalog_sources("catalog_sources") == frozenset(source_ids)

    def catalog_fields_cover(self, source_ids: Sequence[str]) -> bool:
        return self._complete_catalog_sources("catalog_fields") == frozenset(source_ids)

    @property
    def catalog_sources_complete(self) -> bool:
        return bool(self._authorized_source_ids) and self.catalog_sources_cover(
            self._authorized_source_ids
        )

    @property
    def catalog_fields_complete(self) -> bool:
        return bool(self._authorized_source_ids) and self.catalog_fields_cover(
            self._authorized_source_ids
        )

    @property
    def catalog_complete(self) -> bool:
        return self.catalog_sources_complete and self.catalog_fields_complete

    def authorize_cohort(self, cohort_ref: CohortRef) -> frozenset[str]:
        return self.materializations.resolve_cohort(cohort_ref)

    def public_customer_ref(self, canonical_customer_id: str) -> CustomerRef:
        customer_key = self.materializations.customer_key(canonical_customer_id)
        customer_ref = self.materializations.make_ref(
            "customer", stable_value=customer_key
        )
        self._customer_refs[customer_ref] = customer_key
        return customer_ref

    def resolve_customer_ref(self, customer_ref: CustomerRef) -> str:
        known = self._customer_refs.get(customer_ref)
        if known is not None:
            return known
        for result_ref in self._result_to_query:
            try:
                selected = self.materializations.select_authorized_customers(
                    result_ref, customer_refs=(customer_ref,), limit=1
                )
            except MaterializationError:
                continue
            if selected.customers:
                return str(selected.customers[0].canonical_customer_id)
        raise UnknownMaterializationReferenceError(
            "customer reference is not authorized by an observed result"
        )

    def public_snapshot(self) -> ExplorationLedgerSnapshot:
        self.assert_current_generation()
        completed = tuple(sorted(self.complete_query_refs()))
        open_refs = tuple(sorted(self.open_query_refs))
        pages = tuple(
            ExplorationPageLineage(
                query_ref=page.query_ref,
                result_ref=page.result_ref,
                page_ref=page.page_ref,
                parent_page_ref=page.parent_page_ref,
                page_index=page.page_index,
                returned_count=page.returned_count,
                has_more=page.has_more,
                scan_complete=page.scan_complete,
            )
            for query_ref in sorted(self._queries)
            for page in self._queries[query_ref]
        )
        return ExplorationLedgerSnapshot(
            run_id=self.run_id,
            generation=self._generation,
            catalog_sources_complete=self.catalog_sources_complete,
            catalog_fields_complete=self.catalog_fields_complete,
            catalog_complete=self.catalog_complete,
            completed_query_refs=completed,
            open_query_refs=open_refs,
            pages=pages,
        )

    def reset_for_snapshot_change(self) -> None:
        self._stale_query_refs.update(self._queries)
        if self.materializations.generation == self._generation:
            self.materializations.invalidate_snapshot()
        self._generation = self.materializations.generation
        self._queries.clear()
        self._result_to_query.clear()
        self._page_refs.clear()
        self._cursor_reads.clear()
        self._customer_refs.clear()


__all__ = [
    "ExplorationLedger",
    "ExplorationLedgerError",
    "ExplorationLedgerSnapshot",
    "ExplorationPageLineage",
    "ExplorationQueryRecord",
    "ToolPageObservation",
]
