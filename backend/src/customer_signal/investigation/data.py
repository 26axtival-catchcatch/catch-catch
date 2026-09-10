"""An immutable authorized data space shared by all investigation roles."""

from __future__ import annotations

import json
import re
from collections import Counter
from contextvars import ContextVar
from datetime import timezone
from hashlib import sha256
from pathlib import Path
from secrets import token_bytes
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

import duckdb

from customer_signal.agent.contracts import RunRequest
from customer_signal.data.source_registry import SourceRegistry
from customer_signal.domain.models import CustomerEvent
from customer_signal.exploration.contracts import ExplorationSourceScope
from customer_signal.exploration.cursor import CursorCodec
from customer_signal.exploration.materialization import RunMaterializationStore
from customer_signal.exploration.reader import DataSpaceReader
from customer_signal.observability.langfuse import sanitize_trace_value

_ORACLE = re.compile(
    r"wandering|unreachable|incomplete|ground.?truth|abtest|treatment|control_group", re.I
)
_UNSAFE_SQL = re.compile(
    r"\b(read_\w+|\w+_scan|query|query_table|getenv|current_setting|set_config|duckdb_\w+|pragma_\w+)\s*\(",
    re.I,
)
query_owner: ContextVar[str] = ContextVar("investigation_query_owner", default="server")


class InvestigationData:
    def __init__(
        self, *, request: RunRequest, events: list[CustomerEvent], manifests: list, snapshot_id: str
    ):
        if any(
            e.source_id not in request.enabled_sources
            or not request.start_at <= e.occurred_at < request.end_at
            for e in events
        ):
            raise ValueError("event is outside authorized scope")
        self._raw_events = [event.model_copy(deep=True) for event in events]
        self.request = request.model_copy(deep=True)
        self.manifests = manifests
        self.snapshot_id = snapshot_id
        self.queries: dict[str, dict] = {}
        self.journey_reads: dict[str, set[str]] = {}
        self._lock = Lock()
        self.events = []
        for event in events:
            row = {
                key: getattr(event, key)
                for key in (
                    "event_id",
                    "evidence_id",
                    "source_id",
                    "occurred_at",
                    "event_type",
                    "action",
                    "topic",
                    "outcome",
                    "text",
                )
            }
            row["customer_id"] = (
                "customer_" + sha256(event.canonical_customer_id.encode()).hexdigest()[:24]
            )
            for key in ("topic", "outcome"):
                if _ORACLE.search(row[key]):
                    row[key] = "unknown"
            manifest = next((m for m in manifests if m.source_id == event.source_id), None)
            for prefix, values in (("dim_", event.dimensions), ("measure_", event.measures)):
                for key, value in values.items():
                    descriptor = getattr(
                        manifest, "dimensions" if prefix == "dim_" else "measures", {}
                    ).get(key)
                    if _ORACLE.search(key) or _ORACLE.search(str(value)):
                        continue
                    if descriptor is not None and descriptor.pii_classification != "none":
                        continue
                    row[prefix + key] = value
            self.events.append(sanitize_trace_value(row))
        self.events.sort(key=lambda e: (str(e["occurred_at"]), e["event_id"]))
        self.customer_ids = {e["customer_id"] for e in self.events}
        self._db = duckdb.connect(config={"enable_external_access": "false"})
        columns = {key for e in self.events for key in e}
        columns.update(
            (
                "event_id",
                "evidence_id",
                "source_id",
                "occurred_at",
                "event_type",
                "action",
                "topic",
                "outcome",
                "text",
                "customer_id",
            )
        )
        self.columns = sorted(columns)
        types = {
            c: (
                "DOUBLE"
                if c.startswith("measure_")
                else "TIMESTAMP"
                if c == "occurred_at"
                else "VARCHAR"
            )
            for c in self.columns
        }
        self._db.execute(
            "CREATE TABLE events (" + ",".join(f'"{c}" {types[c]}' for c in self.columns) + ")"
        )
        if self.events:
            self._db.execute("BEGIN TRANSACTION")
            self._db.executemany(
                "INSERT INTO events VALUES (" + ",".join("?" for _ in self.columns) + ")",
                [
                    [
                        e[c].astimezone(timezone.utc).replace(tzinfo=None)
                        if c == "occurred_at"
                        else e.get(c)
                        for c in self.columns
                    ]
                    for e in self.events
                ],
            )
            self._db.execute("COMMIT")
        for source_id in request.enabled_sources:
            self._db.execute(
                f"CREATE VIEW \"{source_id}\" AS SELECT * FROM events WHERE source_id = '{source_id}'"
            )

    @classmethod
    def load(cls, registry: SourceRegistry, request: RunRequest) -> InvestigationData:
        scope = ExplorationSourceScope(
            source_ids=tuple(request.enabled_sources),
            start_at=request.start_at,
            end_at=request.end_at,
            native_page_size=200,
        )
        prepared = registry.prepare_paged_sources(scope)
        with TemporaryDirectory(prefix="investigation-") as directory:
            reader = DataSpaceReader(
                registry=registry,
                prepared_sources=prepared,
                authorized_scope=scope,
                cursor_codec=CursorCodec(token_bytes(32)),
                materializations=RunMaterializationStore(Path(directory), run_id=str(uuid4())),
            )
            events = []
            reader.scan_events(scope, consumer=events.append)
            return cls(
                request=request,
                events=events,
                manifests=registry.manifests(request.enabled_sources),
                snapshot_id=reader.snapshot_id,
            )

    def catalog(self) -> dict:
        counts = Counter(e["source_id"] for e in self.events)
        return {
            "snapshot_id": self.snapshot_id,
            "start_at": self.request.start_at.isoformat(),
            "end_at": self.request.end_at.isoformat(),
            "columns": self.columns,
            "tables": [
                {"source_id": s, "event_count": counts[s]} for s in self.request.enabled_sources
            ],
            "event_count": len(self.events),
            "customer_count": len(self.customer_ids),
            "instructions": "DuckDB SELECT. events contains all selected sources; each source_id is also a view. dim_* are strings; measure_* are numeric. occurred_at uses each source mapping; ingestion timestamps may differ from action time. No ground-truth or A/B labels are provided. No data outside this run is available.",
        }

    def referenced_tables(self, sql: str) -> set[str]:
        """Resolve SQL dependencies with the same external-access boundary as execution."""
        if _UNSAFE_SQL.search(sql):
            raise ValueError("only read-only queries of this data space are allowed")
        with self._lock:
            return set(self._db.get_table_names(sql))

    def query(self, sql: str, *, preview_limit: int = 100) -> dict:
        if not 1 <= preview_limit <= 100:
            raise ValueError("invalid query preview limit")
        if _UNSAFE_SQL.search(sql):
            raise ValueError("only read-only queries of this data space are allowed")
        with self._lock:
            statements = self._db.extract_statements(sql)
            if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                raise ValueError("exactly one SELECT is required")
            cursor = self._db.execute(sql)
            columns = [d[0] for d in cursor.description]
            if len(columns) != len(set(columns)):
                raise ValueError("query columns must be uniquely named")
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            query_id = "query-" + uuid4().hex[:24]
            record = {
                "query_id": query_id,
                "sql": sql,
                "columns": columns,
                "row_count": len(rows),
                "rows": json.loads(json.dumps(rows, default=str)),
                "snapshot_id": self.snapshot_id,
                "owner": query_owner.get(),
            }
            self.queries[query_id] = record
            preview = record["rows"][:preview_limit]
            self._credit_journey_rows(record, preview)
            return {**record, "rows": preview, "truncated": len(rows) > preview_limit}

    def _credit_journey_rows(self, record: dict, rows: list[dict]) -> None:
        # Only evidence delivered from this task's own query is independent review.
        if record["owner"] == query_owner.get() and {
            "event_id",
            "customer_id",
            "occurred_at",
            "action",
        } <= set(record["columns"]):
            reviewed = {
                row["customer_id"] for row in rows if row["customer_id"] in self.customer_ids
            }
            self.journey_reads.setdefault(query_owner.get(), set()).update(reviewed)

    def read_query_result(self, query_id: str, *, offset: int = 0, limit: int = 20) -> dict:
        if query_id not in self.queries or offset < 0 or not 1 <= limit <= 20:
            raise ValueError("invalid query page")
        record = self.queries[query_id]
        rows = record["rows"][offset : offset + limit]
        self._credit_journey_rows(record, rows)
        return {k: v for k, v in record.items() if k != "rows"} | {
            "rows": rows,
            "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < record["row_count"] else None,
        }

    def cohort(self, query_id: str) -> list[str]:
        record = self.queries.get(query_id)
        if record is None or "customer_id" not in record["columns"]:
            raise ValueError("cohort requires an executed SELECT with customer_id")
        ids = sorted({r["customer_id"] for r in record["rows"]})
        if not set(ids) <= self.customer_ids:
            raise ValueError("cohort contains an unknown customer")
        return ids

    def journey(self, customer_id: str) -> dict:
        if customer_id not in self.customer_ids:
            raise ValueError("customer is outside this data space")
        events = [e for e in self.events if e["customer_id"] == customer_id]
        self.journey_reads.setdefault(query_owner.get(), set()).add(customer_id)
        return {
            "customer_id": customer_id,
            "total_events": len(events),
            "events": events if len(events) <= 100 else events[:50] + events[-50:],
            "truncated": len(events) > 100,
            "window": "full"
            if len(events) <= 100
            else "first_50_and_last_50; query events for middle rows",
        }

    def restrict(self, source_ids: list[str]) -> InvestigationData:
        """Create an independent space with the registered sources and current window."""
        if not source_ids or not set(source_ids) <= set(self.request.enabled_sources):
            raise ValueError("registered sources are outside authorized scope")
        return InvestigationData(
            request=self.request.model_copy(update={"enabled_sources": sorted(set(source_ids))}),
            events=[e for e in self._raw_events if e.source_id in source_ids],
            manifests=[m for m in self.manifests if m.source_id in source_ids],
            snapshot_id=self.snapshot_id,
        )

    def close(self) -> None:
        self._db.close()
