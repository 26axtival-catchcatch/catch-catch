"""Run-scoped DuckDB storage for immutable derived exploration results."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import struct
import threading
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel

from customer_signal.domain.models import CustomerEvent
from customer_signal.exploration.cursor import canonical_json


_REF_PATTERN = re.compile(
    r"^(?P<kind>result|query|page|cohort|customer)\."
    r"(?P<run>[0-9a-f]{16})\.(?P<generation>\d+)\.(?P<identifier>[0-9a-f]{24,64})$"
)


class MaterializationError(ValueError):
    """Base class for run-scoped reference and lifecycle failures."""


class ForeignRunReferenceError(MaterializationError):
    """A reference was minted by another run."""


class StaleSnapshotReferenceError(MaterializationError):
    """A reference belongs to a previous materialization generation."""


class UnknownMaterializationReferenceError(MaterializationError):
    """A syntactically valid current-run reference does not exist."""


class DisposedMaterializationError(RuntimeError):
    """The run materialization has already reached terminal cleanup."""


class _CustomerKey(str):
    """Tagged run-HMAC value, distinct from an untrusted canonical id string."""


def _sortable_tuple_token(values: tuple[object, ...]) -> str:
    """Encode supported stable-key scalars so lexical DuckDB order is semantic."""

    return "/".join(_sortable_component(value) for value in values)


def _sortable_component(value: object) -> str:
    if value is None:
        return "0!"
    if type(value) is bool:
        return f"1{int(value)}!"
    if type(value) is int:
        if not -(2**63) <= value < 2**63:
            raise ValueError("integer sort key is outside signed 64-bit range")
        return f"2{value + 2**63:016x}!"
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("float sort key must be finite")
        bits = struct.unpack(">Q", struct.pack(">d", value))[0]
        sortable = (~bits & ((1 << 64) - 1)) if bits >> 63 else bits ^ (1 << 63)
        return f"3{sortable:016x}!"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime sort key must include timezone")
        micros = int(value.astimezone(UTC).timestamp() * 1_000_000)
        return f"4{micros + 2**63:016x}!"
    if isinstance(value, str):
        return f"5{value.encode('utf-8').hex()}!"
    if isinstance(value, tuple):
        return f"6{_sortable_tuple_token(value)}!"
    raise TypeError(f"unsupported derived sort-key type: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class CustomerAnchor:
    canonical_customer_id: str
    anchor_at: datetime
    anchor_source_id: str
    anchor_event_id: str


@dataclass(frozen=True, slots=True)
class PreparedCohort:
    cohort_ref: str
    canonical_customer_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedResultEntry:
    sort_key: tuple[object, ...]
    item: BaseModel | dict[str, object]
    customer_anchors: tuple[CustomerAnchor, ...] = ()
    cohorts: tuple[PreparedCohort, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthorizedCustomer:
    customer_ref: str
    canonical_customer_id: str
    anchor_at: datetime
    anchor_source_id: str
    anchor_event_id: str


@dataclass(frozen=True, slots=True)
class AuthorizedCustomerSelection:
    """A bounded, explainable selection authorized by one parent result."""

    customers: tuple[AuthorizedCustomer, ...]
    strategy: str
    rationale: str


@dataclass(frozen=True, slots=True)
class MaterializedResult:
    result_ref: str
    query_ref: str
    result_kind: str
    query_fingerprint: str
    snapshot_id: str
    source_ids: tuple[str, ...]
    generation: int
    matched_count: int | None
    scan_complete: bool
    row_count: int
    partial_message: str | None
    remaining_branches: tuple[str, ...]
    retry_action: str | None
    parent_result_ref: str | None


@dataclass(frozen=True, slots=True)
class StoredResultRow:
    ordinal: int
    sort_key: str
    item: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WorkEvent:
    canonical_customer_id: str
    occurred_at: datetime
    source_id: str
    event_id: str
    evidence_id: str
    event_type: str
    action: str
    topic: str
    outcome: str
    dimensions: dict[str, object]
    measures: dict[str, object]


def _authorized_customer_from_row(row: Sequence[object]) -> AuthorizedCustomer:
    return AuthorizedCustomer(
        customer_ref=str(row[0]),
        canonical_customer_id=_CustomerKey(str(row[1])),
        anchor_at=datetime.fromisoformat(str(row[2])),
        anchor_source_id=str(row[3]),
        anchor_event_id=str(row[4]),
    )


def _evidence_stratum(
    result_kind: str,
    item: dict[str, object],
    customer: AuthorizedCustomer,
) -> tuple[object, ...]:
    """Project safe derived metadata into a bounded representative stratum."""

    if result_kind == "sequence_funnel":
        completed = item.get("completed_step_count")
        dropoff = item.get("dropoff_after_step_id")
        if type(completed) is int:
            return (
                "funnel",
                completed,
                "completed" if dropoff is None else "dropoff",
            )
    if result_kind == "sequence_repetition":
        occurrence = item.get("occurrence_count")
        span = item.get("span_minutes")
        if type(occurrence) is int:
            return (
                "repetition",
                _occurrence_bucket(occurrence),
                _span_bucket(span),
            )
    if result_kind == "sequence_sequence":
        completed = item.get("completed_step_count")
        span = item.get("span_minutes")
        if type(completed) is int:
            return ("sequence", completed, _span_bucket(span))
    return ("source", customer.anchor_source_id)


def _occurrence_bucket(value: int) -> str:
    if value <= 2:
        return "2_or_less"
    if value <= 5:
        return "3_to_5"
    return "6_or_more"


def _span_bucket(value: object) -> str:
    if type(value) not in {int, float}:
        return "unknown"
    numeric = float(value)
    if numeric <= 0:
        return "instant"
    if numeric <= 60:
        return "within_hour"
    if numeric <= 1_440:
        return "within_day"
    return "over_day"


def _spread_values(
    values: Sequence[tuple[object, ...]], limit: int
) -> list[tuple[object, ...]]:
    if len(values) <= limit:
        return list(values)
    if limit == 1:
        return [values[len(values) // 2]]
    denominator = limit - 1
    return [
        values[(index * (len(values) - 1) + denominator // 2) // denominator]
        for index in range(limit)
    ]


class RunMaterializationStore:
    """Own one disposable DuckDB database and every opaque run reference."""

    def __init__(self, root: Path, *, run_id: str) -> None:
        if not run_id or len(run_id) > 128:
            raise ValueError("run_id must be a non-empty bounded string")
        self._run_id = run_id
        self._run_tag = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
        self._ref_secret = os.urandom(32)
        self._customer_secret = os.urandom(32)
        self._generation = 0
        self._disposed = False
        self._connection_closed = False
        self._last_work_projection_field_count = 0
        self._lock = threading.RLock()
        root.mkdir(parents=True, exist_ok=True)
        self.run_directory = root / f"exploration-{self._run_tag}-{uuid.uuid4().hex}"
        os.mkdir(self.run_directory, mode=0o700)
        os.chmod(self.run_directory, 0o700)
        self.database_path = self.run_directory / "materialization.duckdb"
        creating_path = self.run_directory / f".{uuid.uuid4().hex}.creating"
        try:
            self._connection = duckdb.connect(str(creating_path))
            self._create_schema()
            self._connection.close()
            os.chmod(creating_path, 0o600)
            os.replace(creating_path, self.database_path)
            os.chmod(self.database_path, 0o600)
            self._connection = duckdb.connect(str(self.database_path))
        except BaseException:
            try:
                creating_path.unlink()
            except FileNotFoundError:
                pass
            shutil.rmtree(self.run_directory, ignore_errors=True)
            raise

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def customer_key(self, canonical_customer_id: str) -> str:
        """Return an idempotent run-scoped key safe for temporary persistence."""

        if isinstance(canonical_customer_id, _CustomerKey):
            return canonical_customer_id
        digest = hmac.new(
            self._customer_secret,
            b"customer\0" + canonical_customer_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return _CustomerKey(f"ck_{digest}")

    @property
    def result_count(self) -> int:
        with self._lock:
            self._ensure_active()
            value = self._connection.execute(
                "SELECT count(*) FROM exploration_results WHERE state = 'ready'"
            ).fetchone()
            return int(value[0])

    @property
    def work_row_count(self) -> int:
        with self._lock:
            self._ensure_active()
            value = self._connection.execute(
                "SELECT count(*) FROM exploration_work_events"
            ).fetchone()
            return int(value[0])

    @property
    def staging_row_count(self) -> int:
        """Observable invariant: no derived staging row survives atomic publish."""

        with self._lock:
            self._ensure_active()
            value = self._connection.execute(
                "SELECT count(*) FROM exploration_result_staging"
            ).fetchone()
            return int(value[0])

    @property
    def last_work_projection_field_count(self) -> int:
        """Largest query-required dynamic projection persisted for one work event."""

        with self._lock:
            return self._last_work_projection_field_count

    def make_ref(self, kind: str, *, stable_value: str | None = None) -> str:
        if kind not in {"result", "query", "page", "cohort", "customer"}:
            raise ValueError("unknown exploration reference kind")
        seed = stable_value.encode("utf-8") if stable_value is not None else uuid.uuid4().bytes
        identifier = hmac.new(
            self._ref_secret,
            kind.encode("ascii") + b"\0" + str(self._generation).encode("ascii") + b"\0" + seed,
            hashlib.sha256,
        ).hexdigest()[:32]
        return f"{kind}.{self._run_tag}.{self._generation}.{identifier}"

    def store_result(
        self,
        *,
        query_ref: str,
        result_kind: str,
        query_fingerprint: str,
        snapshot_id: str,
        source_ids: Sequence[str],
        rows: Iterable[
            tuple[tuple[object, ...], BaseModel | dict[str, object]]
        ] = (),
        entries: Iterable[DerivedResultEntry] | None = None,
        matched_count: int | None,
        scan_complete: bool,
        matched_count_from_rows: bool = False,
        customer_anchors: Iterable[CustomerAnchor] = (),
        cohorts: Iterable[PreparedCohort] = (),
        partial_message: str | None = None,
        remaining_branches: Sequence[str] = (),
        retry_action: str | None = None,
        parent_result_ref: str | None = None,
    ) -> str:
        """Atomically publish a derived result after every row and anchor is stored."""

        if result_kind == "evidence":
            if parent_result_ref is None:
                raise ValueError("evidence results require parent_result_ref")
            self.read_result(parent_result_ref)
        elif parent_result_ref is not None:
            raise ValueError("only evidence results may bind parent_result_ref")
        if matched_count is not None and matched_count < 0:
            raise ValueError("matched_count cannot be negative")
        if matched_count_from_rows and matched_count is not None:
            raise ValueError("row-derived matched_count cannot also be supplied")
        if not scan_complete and matched_count is not None:
            raise ValueError("partial scans cannot claim matched_count")
        normalized_branches = tuple(sorted(remaining_branches))
        has_partial_state = (
            partial_message is not None
            or bool(normalized_branches)
            or retry_action is not None
        )
        if scan_complete and has_partial_state:
            raise ValueError("complete scans cannot retain partial state")
        if not scan_complete:
            if matched_count_from_rows:
                raise ValueError("partial scans cannot derive a complete matched_count")
            if (
                not partial_message
                or not normalized_branches
                or len(normalized_branches) != len(set(normalized_branches))
                or retry_action != "restart_query_without_cursor"
            ):
                raise ValueError("partial scans require actionable remaining branch state")
        normalized_sources = tuple(sorted(source_ids))
        if not normalized_sources or len(normalized_sources) != len(set(normalized_sources)):
            raise ValueError("source_ids must be non-empty and unique")
        if not set(normalized_branches) <= set(normalized_sources):
            raise ValueError("partial branches must belong to the result source selection")
        self._validate_ref(query_ref, "query", require_exists=False)
        result_ref = self.make_ref("result")
        with self._lock:
            self._ensure_active()
            self._connection.execute("BEGIN TRANSACTION")
            try:
                self._connection.execute(
                    """
                    INSERT INTO exploration_results VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        result_ref,
                        query_ref,
                        result_kind,
                        query_fingerprint,
                        snapshot_id,
                        canonical_json(normalized_sources),
                        self._generation,
                        matched_count,
                        scan_complete,
                        "building",
                        0,
                        partial_message,
                        canonical_json(normalized_branches),
                        retry_action,
                        parent_result_ref,
                    ],
                )
                count = self._insert_result_rows(
                    result_ref,
                    rows,
                    entries=entries,
                )
                self._insert_customer_anchors(result_ref, customer_anchors)
                self._insert_prepared_cohorts(result_ref, cohorts)
                effective_matched_count = count if matched_count_from_rows else matched_count
                self._connection.execute(
                    """
                    UPDATE exploration_results
                    SET state = 'ready', row_count = ?, matched_count = ?
                    WHERE result_ref = ? AND state = 'building'
                    """,
                    [count, effective_matched_count, result_ref],
                )
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
        return result_ref

    def read_result(self, result_ref: str) -> MaterializedResult:
        self._validate_ref(result_ref, "result")
        with self._lock:
            self._ensure_active()
            row = self._connection.execute(
                """
                SELECT result_ref, query_ref, result_kind, query_fingerprint,
                       snapshot_id, source_ids_json, generation, matched_count,
                       scan_complete, row_count, partial_message,
                       remaining_branches_json, retry_action, parent_result_ref
                FROM exploration_results
                WHERE result_ref = ? AND state = 'ready'
                """,
                [result_ref],
            ).fetchone()
        if row is None:
            raise UnknownMaterializationReferenceError("result reference is unknown")
        return MaterializedResult(
            result_ref=str(row[0]),
            query_ref=str(row[1]),
            result_kind=str(row[2]),
            query_fingerprint=str(row[3]),
            snapshot_id=str(row[4]),
            source_ids=tuple(json.loads(row[5])),
            generation=int(row[6]),
            matched_count=int(row[7]) if row[7] is not None else None,
            scan_complete=bool(row[8]),
            row_count=int(row[9]),
            partial_message=str(row[10]) if row[10] is not None else None,
            remaining_branches=tuple(json.loads(row[11])),
            retry_action=str(row[12]) if row[12] is not None else None,
            parent_result_ref=str(row[13]) if row[13] is not None else None,
        )

    def read_result_page(
        self,
        result_ref: str,
        *,
        after_ordinal: int | None,
        page_size: int,
    ) -> tuple[tuple[StoredResultRow, ...], bool]:
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
        self.read_result(result_ref)
        after = -1 if after_ordinal is None else after_ordinal
        if after < -1:
            raise ValueError("after_ordinal cannot be below -1")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT ordinal, sort_key_json, item_json
                FROM exploration_result_rows
                WHERE result_ref = ? AND ordinal > ?
                ORDER BY ordinal
                LIMIT ?
                """,
                [result_ref, after, page_size + 1],
            ).fetchall()
        has_more = len(rows) > page_size
        selected = rows[:page_size]
        return (
            tuple(
                StoredResultRow(
                    ordinal=int(row[0]),
                    sort_key=str(row[1]),
                    item=json.loads(row[2]),
                )
                for row in selected
            ),
            has_more,
        )

    def store_cohort(
        self,
        parent_result_ref: str,
        canonical_customer_ids: Iterable[str],
        *,
        stable_label: str,
    ) -> str:
        self.read_result(parent_result_ref)
        customers = tuple(
            sorted({self.customer_key(customer) for customer in canonical_customer_ids})
        )
        cohort_ref = self.make_ref(
            "cohort", stable_value=f"{parent_result_ref}\0{stable_label}"
        )
        with self._lock:
            self._connection.execute("BEGIN TRANSACTION")
            try:
                self._connection.execute(
                    "INSERT OR IGNORE INTO exploration_cohorts VALUES (?, ?, ?)",
                    [cohort_ref, parent_result_ref, self._generation],
                )
                if customers:
                    self._connection.executemany(
                        "INSERT OR IGNORE INTO exploration_cohort_members VALUES (?, ?)",
                        [(cohort_ref, customer) for customer in customers],
                    )
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
        return cohort_ref

    def resolve_cohort(self, cohort_ref: str) -> frozenset[str]:
        self._validate_ref(cohort_ref, "cohort")
        with self._lock:
            exists = self._connection.execute(
                "SELECT 1 FROM exploration_cohorts WHERE cohort_ref = ?",
                [cohort_ref],
            ).fetchone()
            if exists is None:
                raise UnknownMaterializationReferenceError("cohort reference is unknown")
            rows = self._connection.execute(
                """
                SELECT customer_key
                FROM exploration_cohort_members
                WHERE cohort_ref = ?
                ORDER BY customer_key
                """,
                [cohort_ref],
            ).fetchall()
        return frozenset(_CustomerKey(str(row[0])) for row in rows)

    def authorize_customers(
        self,
        parent_result_ref: str,
        *,
        customer_refs: Sequence[str] = (),
        limit: int = 3,
    ) -> tuple[AuthorizedCustomer, ...]:
        """Compatibility wrapper returning only the authorized customer rows."""

        return self.select_authorized_customers(
            parent_result_ref,
            customer_refs=customer_refs,
            limit=limit,
        ).customers

    def select_authorized_customers(
        self,
        parent_result_ref: str,
        *,
        customer_refs: Sequence[str] = (),
        limit: int = 3,
    ) -> AuthorizedCustomerSelection:
        """Choose explicit customers or deterministic representatives across result strata."""

        if not 1 <= limit <= 3:
            raise ValueError("evidence customer limit must be between 1 and 3")
        parent = self.read_result(parent_result_ref)
        requested = tuple(customer_refs)
        if len(requested) != len(set(requested)) or len(requested) > limit:
            raise MaterializationError("customer selection is invalid")
        for customer_ref in requested:
            self._validate_ref(customer_ref, "customer", require_exists=False)
        with self._lock:
            if requested:
                placeholders = ",".join("?" for _ in requested)
                rows = self._connection.execute(
                    f"""
                    SELECT customer_ref, customer_key, anchor_at,
                           anchor_source_id, anchor_event_id
                    FROM exploration_result_customers
                    WHERE result_ref = ? AND customer_ref IN ({placeholders})
                    """,  # noqa: S608 - placeholders are generated, not user supplied
                    [parent_result_ref, *requested],
                ).fetchall()
                if len(rows) != len(requested):
                    raise MaterializationError(
                        "customer_ref is not authorized by parent_result_ref"
                    )
                by_ref = {
                    str(row[0]): _authorized_customer_from_row(row) for row in rows
                }
                return AuthorizedCustomerSelection(
                    customers=tuple(by_ref[customer_ref] for customer_ref in requested),
                    strategy="explicit",
                    rationale=(
                        "explicit customer_refs authorized by the immutable parent result; "
                        "request order preserved"
                    ),
                )

            # Joining by the public opaque customer_ref lets DuckDB stream parent
            # row metadata without exposing canonical ids or materializing raw events.
            cursor = self._connection.execute(
                """
                SELECT c.customer_ref, c.customer_key, c.anchor_at,
                       c.anchor_source_id, c.anchor_event_id, r.item_json
                FROM exploration_result_customers AS c
                LEFT JOIN exploration_result_rows AS r
                  ON r.result_ref = c.result_ref
                 AND json_extract_string(r.item_json, '$.customer_ref') = c.customer_ref
                WHERE c.result_ref = ?
                QUALIFY row_number() OVER (
                    PARTITION BY c.customer_ref ORDER BY r.ordinal NULLS LAST
                ) = 1
                ORDER BY c.anchor_at, c.anchor_source_id, c.anchor_event_id,
                         c.customer_ref
                """,
                [parent_result_ref],
            )
            first_by_stratum: dict[tuple[object, ...], AuthorizedCustomer] = {}
            stable_fallback: list[AuthorizedCustomer] = []
            while batch := cursor.fetchmany(200):
                for row in batch:
                    customer = _authorized_customer_from_row(row)
                    if len(stable_fallback) < limit:
                        stable_fallback.append(customer)
                    item = json.loads(str(row[5])) if row[5] is not None else {}
                    stratum = _evidence_stratum(parent.result_kind, item, customer)
                    first_by_stratum.setdefault(stratum, customer)

        ordered_strata = sorted(first_by_stratum, key=_sortable_tuple_token)
        selected_strata = _spread_values(ordered_strata, limit)
        chosen = [first_by_stratum[stratum] for stratum in selected_strata]
        chosen_refs = {customer.customer_ref for customer in chosen}
        for customer in stable_fallback:
            if len(chosen) >= limit:
                break
            if customer.customer_ref not in chosen_refs:
                chosen.append(customer)
                chosen_refs.add(customer.customer_ref)
        return AuthorizedCustomerSelection(
            customers=tuple(chosen),
            strategy="representative",
            rationale=(
                "representative strata coverage selected "
                f"{len(chosen)} customers across {len(selected_strata)} of "
                f"{len(ordered_strata)} derived-result strata with stable anchor tie-breaks"
            ),
        )

    def authorized_customer_count(self, parent_result_ref: str) -> int:
        self.read_result(parent_result_ref)
        with self._lock:
            row = self._connection.execute(
                """
                SELECT count(*) FROM exploration_result_customers
                WHERE result_ref = ?
                """,
                [parent_result_ref],
            ).fetchone()
        return int(row[0])

    def begin_work(self) -> str:
        with self._lock:
            self._ensure_active()
            return f"work-{self._generation}-{uuid.uuid4().hex}"

    def append_work_event(
        self,
        work_ref: str,
        event: CustomerEvent,
        *,
        dimensions: Mapping[str, object],
        measures: Mapping[str, object],
    ) -> None:
        """Persist only the validated semantic projection required by this query."""

        with self._lock:
            self._ensure_active()
            self._last_work_projection_field_count = max(
                self._last_work_projection_field_count,
                len(dimensions) + len(measures),
            )
            self._connection.execute(
                """
                INSERT INTO exploration_work_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    work_ref,
                    self.customer_key(event.canonical_customer_id),
                    event.occurred_at.astimezone(UTC).isoformat(),
                    event.source_id,
                    event.event_id,
                    event.evidence_id,
                    event.event_type,
                    event.action,
                    event.topic,
                    event.outcome,
                    canonical_json(dict(dimensions)),
                    canonical_json(dict(measures)),
                ],
            )

    def iter_work_events(self, work_ref: str, *, batch_size: int = 200) -> Iterator[WorkEvent]:
        if not 1 <= batch_size <= 1_000:
            raise ValueError("work batch_size must be between 1 and 1000")
        with self._lock:
            self._ensure_active()
        # A dedicated read connection keeps this streaming cursor valid while the
        # primary connection stages derived rows inside its publish transaction.
        connection = duckdb.connect(str(self.database_path))
        try:
            cursor = connection.execute(
                """
                SELECT customer_key, occurred_at, source_id, event_id,
                       evidence_id, event_type, action, topic, outcome,
                       dimensions_json, measures_json
                FROM exploration_work_events
                WHERE work_ref = ?
                ORDER BY customer_key, occurred_at, source_id, event_id
                """,
                [work_ref],
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    return
                for row in rows:
                    yield WorkEvent(
                        canonical_customer_id=_CustomerKey(str(row[0])),
                        occurred_at=datetime.fromisoformat(str(row[1])),
                        source_id=str(row[2]),
                        event_id=str(row[3]),
                        evidence_id=str(row[4]),
                        event_type=str(row[5]),
                        action=str(row[6]),
                        topic=str(row[7]),
                        outcome=str(row[8]),
                        dimensions=json.loads(row[9]),
                        measures=json.loads(row[10]),
                    )
        finally:
            connection.close()

    def clear_work(self, work_ref: str) -> None:
        with self._lock:
            if self._disposed:
                return
            self._connection.execute(
                "DELETE FROM exploration_work_events WHERE work_ref = ?", [work_ref]
            )

    def invalidate_snapshot(self) -> None:
        """Advance generation and make every previous result/reference unresolvable."""

        with self._lock:
            self._ensure_active()
            self._connection.execute("BEGIN TRANSACTION")
            try:
                for table in (
                    "exploration_result_rows",
                    "exploration_result_staging",
                    "exploration_result_customers",
                    "exploration_cohort_members",
                    "exploration_cohorts",
                    "exploration_results",
                    "exploration_work_events",
                ):
                    self._connection.execute(f"DELETE FROM {table}")
                self._generation += 1
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def dispose(self) -> None:
        """Idempotently close and remove the run database and sidecars."""

        with self._lock:
            if self._disposed:
                return
            if not self._connection_closed:
                self._connection.close()
                self._connection_closed = True
            for suffix in ("", ".wal", ".tmp"):
                path = Path(f"{self.database_path}{suffix}")
                if path.parent != self.run_directory:
                    raise RuntimeError("refusing cleanup outside the owned run directory")
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
            self.run_directory.rmdir()
            self._disposed = True

    def _insert_result_rows(
        self,
        result_ref: str,
        rows: Iterable[tuple[tuple[object, ...], BaseModel | dict[str, object]]],
        *,
        entries: Iterable[DerivedResultEntry] | None,
    ) -> int:
        if entries is not None:
            row_iterator: Iterable[DerivedResultEntry] = entries
        else:
            row_iterator = (
                DerivedResultEntry(sort_key=sort_key, item=item)
                for sort_key, item in rows
            )
        pending: list[tuple[str, str, str, str]] = []
        count = 0
        for entry in row_iterator:
            if not isinstance(entry.sort_key, tuple):
                raise TypeError("derived result sort key must be a tuple")
            serialized_key = canonical_json(entry.sort_key)
            serialized_item = canonical_json(
                entry.item.model_dump(mode="json")
                if isinstance(entry.item, BaseModel)
                else entry.item
            )
            pending.append(
                (
                    result_ref,
                    _sortable_tuple_token(entry.sort_key),
                    serialized_key,
                    serialized_item,
                )
            )
            count += 1
            self._insert_customer_anchors(result_ref, entry.customer_anchors)
            self._insert_prepared_cohorts(result_ref, entry.cohorts)
            if len(pending) >= 200:
                self._connection.executemany(
                    "INSERT INTO exploration_result_staging VALUES (?, ?, ?, ?)", pending
                )
                pending.clear()
        if pending:
            self._connection.executemany(
                "INSERT INTO exploration_result_staging VALUES (?, ?, ?, ?)", pending
            )
        self._connection.execute(
            """
            INSERT INTO exploration_result_rows
            SELECT result_ref,
                   row_number() OVER (ORDER BY sort_token) - 1,
                   sort_key_json,
                   item_json
            FROM exploration_result_staging
            WHERE result_ref = ?
            ORDER BY sort_token
            """,
            [result_ref],
        )
        self._connection.execute(
            "DELETE FROM exploration_result_staging WHERE result_ref = ?", [result_ref]
        )
        return count

    def _insert_customer_anchors(
        self, result_ref: str, anchors: Iterable[CustomerAnchor]
    ) -> None:
        rows: dict[str, tuple[object, ...]] = {}
        for anchor in anchors:
            customer_key = self.customer_key(anchor.canonical_customer_id)
            customer_ref = self.make_ref(
                "customer", stable_value=customer_key
            )
            candidate = (
                result_ref,
                customer_ref,
                customer_key,
                anchor.anchor_at.astimezone(UTC).isoformat(),
                anchor.anchor_source_id,
                anchor.anchor_event_id,
            )
            existing = rows.get(customer_ref)
            if existing is None or candidate[3:] < existing[3:]:
                rows[customer_ref] = candidate
        if rows:
            self._connection.executemany(
                "INSERT OR IGNORE INTO exploration_result_customers VALUES (?, ?, ?, ?, ?, ?)",
                list(rows.values()),
            )

    def _insert_prepared_cohorts(
        self, result_ref: str, cohorts: Iterable[PreparedCohort]
    ) -> None:
        seen: set[str] = set()
        for cohort in cohorts:
            self._validate_ref(cohort.cohort_ref, "cohort", require_exists=False)
            if cohort.cohort_ref in seen:
                raise ValueError("prepared cohort_ref values must be unique")
            seen.add(cohort.cohort_ref)
            self._connection.execute(
                "INSERT INTO exploration_cohorts VALUES (?, ?, ?)",
                [cohort.cohort_ref, result_ref, self._generation],
            )
            customers = tuple(
                sorted(
                    {
                        self.customer_key(customer)
                        for customer in cohort.canonical_customer_ids
                    }
                )
            )
            if customers:
                self._connection.executemany(
                    "INSERT INTO exploration_cohort_members VALUES (?, ?)",
                    [(cohort.cohort_ref, customer) for customer in customers],
                )

    def _validate_ref(
        self,
        reference: str,
        expected_kind: str,
        *,
        require_exists: bool = True,
    ) -> None:
        del require_exists  # existence is table-specific; this validates ownership/lifetime.
        match = _REF_PATTERN.fullmatch(reference) if isinstance(reference, str) else None
        if match is None or match.group("kind") != expected_kind:
            raise UnknownMaterializationReferenceError(
                f"{expected_kind} reference is malformed or has the wrong kind"
            )
        if match.group("run") != self._run_tag:
            raise ForeignRunReferenceError("reference belongs to a foreign run")
        if int(match.group("generation")) != self._generation:
            raise StaleSnapshotReferenceError("reference belongs to a stale snapshot")

    def _ensure_active(self) -> None:
        if self._disposed or self._connection_closed:
            raise DisposedMaterializationError("run materialization has been disposed")

    def _create_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE exploration_results (
                result_ref VARCHAR PRIMARY KEY,
                query_ref VARCHAR NOT NULL,
                result_kind VARCHAR NOT NULL,
                query_fingerprint VARCHAR NOT NULL,
                snapshot_id VARCHAR NOT NULL,
                source_ids_json VARCHAR NOT NULL,
                generation BIGINT NOT NULL,
                matched_count BIGINT,
                scan_complete BOOLEAN NOT NULL,
                state VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                partial_message VARCHAR,
                remaining_branches_json VARCHAR NOT NULL,
                retry_action VARCHAR,
                parent_result_ref VARCHAR
            );
            CREATE TABLE exploration_result_rows (
                result_ref VARCHAR NOT NULL,
                ordinal BIGINT NOT NULL,
                sort_key_json VARCHAR NOT NULL,
                item_json VARCHAR NOT NULL,
                PRIMARY KEY (result_ref, ordinal),
                UNIQUE (result_ref, sort_key_json)
            );
            CREATE TABLE exploration_result_staging (
                result_ref VARCHAR NOT NULL,
                sort_token VARCHAR NOT NULL,
                sort_key_json VARCHAR NOT NULL,
                item_json VARCHAR NOT NULL,
                PRIMARY KEY (result_ref, sort_token),
                UNIQUE (result_ref, sort_key_json)
            );
            CREATE TABLE exploration_result_customers (
                result_ref VARCHAR NOT NULL,
                customer_ref VARCHAR NOT NULL,
                customer_key VARCHAR NOT NULL,
                anchor_at VARCHAR NOT NULL,
                anchor_source_id VARCHAR NOT NULL,
                anchor_event_id VARCHAR NOT NULL,
                PRIMARY KEY (result_ref, customer_ref)
            );
            CREATE TABLE exploration_cohorts (
                cohort_ref VARCHAR PRIMARY KEY,
                parent_result_ref VARCHAR NOT NULL,
                generation BIGINT NOT NULL
            );
            CREATE TABLE exploration_cohort_members (
                cohort_ref VARCHAR NOT NULL,
                customer_key VARCHAR NOT NULL,
                PRIMARY KEY (cohort_ref, customer_key)
            );
            CREATE TABLE exploration_work_events (
                work_ref VARCHAR NOT NULL,
                customer_key VARCHAR NOT NULL,
                occurred_at VARCHAR NOT NULL,
                source_id VARCHAR NOT NULL,
                event_id VARCHAR NOT NULL,
                evidence_id VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                action VARCHAR NOT NULL,
                topic VARCHAR NOT NULL,
                outcome VARCHAR NOT NULL,
                dimensions_json VARCHAR NOT NULL,
                measures_json VARCHAR NOT NULL
            );
            CREATE INDEX exploration_result_rows_index
                ON exploration_result_rows(result_ref, ordinal);
            CREATE INDEX exploration_customer_index
                ON exploration_result_customers(result_ref, customer_ref);
            CREATE INDEX exploration_work_index
                ON exploration_work_events(work_ref, customer_key, occurred_at,
                                           source_id, event_id);
            """
        )


__all__ = [
    "AuthorizedCustomer",
    "AuthorizedCustomerSelection",
    "CustomerAnchor",
    "DisposedMaterializationError",
    "DerivedResultEntry",
    "ForeignRunReferenceError",
    "MaterializationError",
    "MaterializedResult",
    "PreparedCohort",
    "RunMaterializationStore",
    "StaleSnapshotReferenceError",
    "StoredResultRow",
    "UnknownMaterializationReferenceError",
    "WorkEvent",
]
