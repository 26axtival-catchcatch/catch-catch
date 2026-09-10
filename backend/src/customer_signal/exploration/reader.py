"""Snapshot-safe, bounded k-way scan over normalized paged event sources."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from customer_signal.data.source_registry import SourceRegistry
from customer_signal.domain.models import CustomerEvent
from customer_signal.domain.sources import SourceManifest
from customer_signal.exploration.contracts import (
    EventSortKey,
    ExplorationSourceScope,
    SourcePageRequest,
)
from customer_signal.exploration.cursor import (
    CursorCodec,
    CursorValidationError,
    snapshot_fingerprint,
)
from customer_signal.exploration.materialization import RunMaterializationStore
from customer_signal.exploration.source_adapter import (
    EventValidationSession,
    PagedSourceAdapter,
    ValidatedSourceSet,
    validate_event_page,
)


class DataSpacePermissionError(PermissionError):
    """A Tool query attempts to leave its run-authorized source or time scope."""


class SnapshotChangedDuringScanError(CursorValidationError):
    """A native source changed relative to its prepared identity snapshot."""


class RetryablePageError(RuntimeError):
    """A native adapter could not finish a page for a transient reason."""


class ScanInterruptedError(RuntimeError):
    """A stable scan stopped after yielding a safe prefix of the selected space."""

    def __init__(self, message: str, *, remaining_branches: Sequence[str]) -> None:
        bounded_message = message[:1_000] or "source page scan was interrupted"
        super().__init__(bounded_message)
        branches = tuple(sorted(set(remaining_branches)))
        if not branches:
            raise ValueError("an interrupted scan requires a remaining branch")
        self.remaining_branches = branches


class SnapshotBarrierUnavailableError(CursorValidationError):
    """A retryable token failure prevented certification of an otherwise stable prefix."""


@dataclass(slots=True)
class _SourceScanState:
    source_id: str
    after: EventSortKey | None = None
    page_has_more: bool | None = None
    buffered_events: int = 0
    fetching: bool = False
    done: bool = False


class DataSpaceReader:
    """Stream canonical events without exposing raw adapter or native cursor details."""

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        prepared_sources: ValidatedSourceSet,
        authorized_scope: ExplorationSourceScope,
        cursor_codec: CursorCodec,
        materializations: RunMaterializationStore,
    ) -> None:
        if set(authorized_scope.source_ids) != set(prepared_sources.snapshot_tokens):
            raise ValueError(
                "authorized scope sources must exactly equal the prepared source set"
            )
        self.registry = registry
        self.prepared_sources = prepared_sources
        self.authorized_scope = authorized_scope.model_copy(deep=True)
        self.cursor_codec = cursor_codec
        self.materializations = materializations
        self.snapshot_id = snapshot_fingerprint(prepared_sources.snapshot_tokens)
        self._snapshot_valid = True
        # Resolve all adapters up front so a registry mutation cannot broaden a scan.
        self._adapters: dict[str, PagedSourceAdapter] = {
            source_id: registry.get_paged(source_id)
            for source_id in authorized_scope.source_ids
        }
        if set(self._adapters) != set(prepared_sources.snapshot_tokens):
            raise ValueError("resolved paged adapters do not equal the prepared source set")
        self._active_buffered_events = 0
        self._last_scan_peak_buffered_events = 0
        self._assert_snapshots(tuple(self._adapters))

    @property
    def active_source_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    @property
    def last_scan_peak_buffered_events(self) -> int:
        """Largest number of native-page events resident during the last scan."""

        return self._last_scan_peak_buffered_events

    def manifest(self, source_id: str) -> SourceManifest:
        self.validate_source_ids((source_id,))
        return self.prepared_sources.identity_resolver.manifest(source_id)

    def validate_source_ids(
        self, source_ids: Sequence[str], *, allow_empty_as_all: bool = False
    ) -> tuple[str, ...]:
        requested = tuple(sorted(source_ids))
        if not requested and allow_empty_as_all:
            return self.active_source_ids
        if not requested or len(requested) != len(set(requested)):
            raise DataSpacePermissionError("source selection must be non-empty and unique")
        if not set(requested) <= set(self._adapters):
            raise DataSpacePermissionError(
                "source selection is outside this run's authorized data space"
            )
        return requested

    def validate_scope(self, scope: ExplorationSourceScope) -> ExplorationSourceScope:
        if not isinstance(scope, ExplorationSourceScope):
            raise ValueError("scan scope must use ExplorationSourceScope")
        source_ids = self.validate_source_ids(scope.source_ids)
        authorized = self.authorized_scope
        if scope.start_at < authorized.start_at or scope.end_at > authorized.end_at:
            raise DataSpacePermissionError(
                "time range is outside this run's authorized data space"
            )
        return scope.model_copy(update={"source_ids": source_ids})

    def assert_current_snapshot(self, source_ids: Sequence[str] | None = None) -> None:
        if source_ids is not None:
            self.validate_source_ids(source_ids)
        # snapshot_id binds the entire prepared run, so a stored page can only be
        # read while every prepared source token remains current.
        self._assert_snapshots(self.active_source_ids)

    def scan_events(
        self,
        scope: ExplorationSourceScope,
        *,
        consumer: Callable[[CustomerEvent], object],
    ) -> int:
        """Consume every selected event once in global stable-key order.

        Each source holds at most one native page and the merge heap holds one event
        per source.  The raw scan never creates an Agent cursor or materialized result.
        """

        scope = self.validate_scope(scope)
        self._active_buffered_events = 0
        self._last_scan_peak_buffered_events = 0
        session = EventValidationSession()
        states = {
            source_id: _SourceScanState(source_id=source_id)
            for source_id in scope.source_ids
        }
        streams: list[Iterator[CustomerEvent]] = []
        try:
            self._assert_snapshots(self.active_source_ids)
            streams = [
                self._source_stream(source_id, scope, session, states[source_id])
                for source_id in scope.source_ids
            ]
            heap: list[
                tuple[tuple[object, ...], int, CustomerEvent, Iterator[CustomerEvent]]
            ] = []
            for source_ordinal, stream in enumerate(streams):
                try:
                    event = next(stream)
                except StopIteration:
                    continue
                heapq.heappush(
                    heap,
                    (
                        EventSortKey.from_event(event).as_tuple(),
                        source_ordinal,
                        event,
                        stream,
                    ),
                )

            last_key: tuple[object, ...] | None = None
            count = 0
            while heap:
                key, source_ordinal, event, stream = heapq.heappop(heap)
                if last_key is not None and key <= last_key:
                    raise ValueError(
                        "cross-source event keys must be globally unique and ordered"
                    )
                consumer(event)
                count += 1
                last_key = key
                try:
                    next_event = next(stream)
                except StopIteration:
                    continue
                heapq.heappush(
                    heap,
                    (
                        EventSortKey.from_event(next_event).as_tuple(),
                        source_ordinal,
                        next_event,
                        stream,
                    ),
                )

            self._assert_snapshots(self.active_source_ids)
            return count
        except ScanInterruptedError as error:
            # Publish a prefix only after a fresh all-source barrier certifies it.
            # A real token change still takes the SnapshotChanged path and
            # invalidates every prior generation reference.
            try:
                self._assert_snapshots(self.active_source_ids)
            except ScanInterruptedError as confirmation_error:
                raise SnapshotBarrierUnavailableError(
                    "source snapshot barrier is temporarily unavailable; retry the query"
                ) from confirmation_error
            failed_barriers = set(error.remaining_branches)
            if not failed_barriers <= set(scope.source_ids):
                raise SnapshotBarrierUnavailableError(
                    "a non-selected prepared source snapshot barrier is temporarily "
                    "unavailable; retry the query"
                ) from error
            unfinished = tuple(
                source_id
                for source_id in scope.source_ids
                if not states[source_id].done or source_id in failed_barriers
            )
            if not unfinished:
                unfinished = error.remaining_branches
            raise ScanInterruptedError(
                str(error), remaining_branches=unfinished
            ) from error
        finally:
            for stream in streams:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()
            self._active_buffered_events = 0

    def _source_stream(
        self,
        source_id: str,
        scope: ExplorationSourceScope,
        session: EventValidationSession,
        state: _SourceScanState,
    ) -> Iterator[CustomerEvent]:
        adapter = self._adapters[source_id]
        source_scope = scope.model_copy(update={"source_ids": (source_id,)})
        after = None
        while True:
            state.fetching = True
            state.after = after
            self._assert_snapshots((source_id,))
            request = SourcePageRequest(
                scope=source_scope,
                after=after,
                page_size=scope.native_page_size,
            )
            try:
                page = adapter.load_event_page(request)
            except RetryablePageError as error:
                # The adapter owns only its native page.  Attach the public source
                # branch here so Tool callers never need access to adapter internals.
                raise ScanInterruptedError(
                    str(error) or "source page scan was interrupted",
                    remaining_branches=(source_id,),
                ) from error
            self._assert_snapshots((source_id,))
            state.fetching = False
            validate_event_page(
                page,
                request,
                source_id,
                self.prepared_sources,
                session,
            )
            resident = len(page.items)
            state.page_has_more = page.has_more
            state.buffered_events = resident
            self._active_buffered_events += resident
            self._last_scan_peak_buffered_events = max(
                self._last_scan_peak_buffered_events,
                self._active_buffered_events,
            )
            try:
                for event in page.items:
                    yield event
                    state.buffered_events -= 1
            finally:
                self._active_buffered_events -= resident
            if not page.has_more:
                state.done = True
                return
            after = page.next_key
            state.after = after

    def _assert_snapshots(self, source_ids: Sequence[str]) -> None:
        if not self._snapshot_valid:
            raise SnapshotChangedDuringScanError(
                "source snapshot is stale; restart exploration from the catalog"
            )
        for source_id in source_ids:
            expected = self.prepared_sources.snapshot_tokens[source_id]
            try:
                actual = self._adapters[source_id].snapshot_token()
            except RetryablePageError as error:
                raise ScanInterruptedError(
                    str(error) or "source snapshot barrier was interrupted",
                    remaining_branches=(source_id,),
                ) from error
            if actual != expected:
                self._snapshot_valid = False
                self.materializations.invalidate_snapshot()
                raise SnapshotChangedDuringScanError(
                    f"source snapshot changed while scanning {source_id}"
                )


__all__ = [
    "DataSpacePermissionError",
    "DataSpaceReader",
    "RetryablePageError",
    "ScanInterruptedError",
    "SnapshotBarrierUnavailableError",
    "SnapshotChangedDuringScanError",
]
