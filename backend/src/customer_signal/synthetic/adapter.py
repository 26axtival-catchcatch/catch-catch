"""DuckDB-backed adapter for one manifest-defined synthetic source."""

from __future__ import annotations

from collections.abc import Sequence

from customer_signal.data.repository import DuckDBRepository
from customer_signal.domain.models import CustomerEvent, EvidenceRecord, IdentityEdge
from customer_signal.domain.sources import EventScope, SourceManifest
from customer_signal.exploration.contracts import (
    ExplorationSourceScope,
    IdentityPage,
    IdentityPageRequest,
    SourceEventPage,
    SourcePageRequest,
)


class SyntheticDuckDBAdapter:
    """Expose one synthetic DuckDB source through the portable adapter contract."""

    def __init__(self, repository: DuckDBRepository, manifest: SourceManifest) -> None:
        self._repository = repository
        self._manifest = manifest

    def describe(self) -> SourceManifest:
        return self._manifest

    def snapshot_token(self) -> str:
        return self._repository.snapshot_token()

    def load_event_page(self, request: SourcePageRequest) -> SourceEventPage:
        self._validate_exploration_scope(request.scope)
        if request.after is not None and request.after.source_id != self._manifest.source_id:
            raise ValueError("synthetic event page key belongs to another source")
        page = self._repository.list_event_page(
            source_ids=[self._manifest.source_id],
            start_at=request.scope.start_at,
            end_at=request.scope.end_at,
            after=request.after,
            page_size=request.page_size,
        )
        for event in page.items:
            self._manifest.validate_event(event)
        return page

    def load_identity_page(self, request: IdentityPageRequest) -> IdentityPage:
        self._validate_exploration_scope(request.scope)
        return self._repository.list_identity_page(
            source_ids=[self._manifest.source_id],
            start_at=request.scope.start_at,
            end_at=request.scope.end_at,
            after=request.after,
            page_size=request.page_size,
        )

    def load_events(self, scope: EventScope) -> list[CustomerEvent]:
        self._validate_scope(scope)
        events = self._repository.list_events(
            scope.start_at,
            scope.end_at,
            [self._manifest.source_id],
            limit=self._repository_limit(scope),
        )
        for event in events:
            self._manifest.validate_event(event)
        return events

    def load_identities(self, scope: EventScope) -> list[IdentityEdge]:
        self._validate_scope(scope)
        return self._repository.list_identity_edges(
            scope.start_at,
            scope.end_at,
            [self._manifest.source_id],
            limit=self._repository_limit(scope),
        )

    def get_evidence(self, allowed_evidence_ids: Sequence[str]) -> list[EvidenceRecord]:
        records = self._repository.get_evidence(allowed_evidence_ids)
        if any(record.source_id != self._manifest.source_id for record in records):
            raise ValueError("evidence does not belong to this source")
        return [record.model_copy(update={"raw_fields": {}}) for record in records]

    def _validate_scope(self, scope: EventScope) -> None:
        if scope.source_ids != [self._manifest.source_id]:
            raise ValueError("synthetic adapter scope must select its source only")

    def _validate_exploration_scope(self, scope: ExplorationSourceScope) -> None:
        if scope.source_ids != (self._manifest.source_id,):
            raise ValueError("synthetic adapter scope must select its source only")

    @staticmethod
    def _repository_limit(scope: EventScope) -> int:
        """Keep the legacy repository's 100-row hard bound in both adapter calls."""

        return min(scope.max_events, 100)


__all__ = ["SyntheticDuckDBAdapter"]
