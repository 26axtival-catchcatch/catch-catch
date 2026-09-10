"""Execute fixed signal definitions inside the existing authorized SQL data space."""

from __future__ import annotations

import json
import math
import re
from hashlib import sha256
from datetime import date, datetime, timezone

from uuid import uuid4

from customer_signal.investigation.data import InvestigationData
from customer_signal.signals.contracts import Measurement, MetricValue, SignalDefinition


# Increment when the deterministic SQL measurement semantics change.
PIPELINE_VERSION = "signal-sql-v1"


def _fingerprint(value: object) -> str:
    def canonical(item):
        if isinstance(item, datetime):
            return item.astimezone(timezone.utc).isoformat()
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, (set, frozenset)):
            return sorted(
                (canonical(val) for val in item),
                key=lambda val: json.dumps(
                    val, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":")
                ),
            )
        if isinstance(item, dict):
            return {key: canonical(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [canonical(val) for val in item]
        return item

    value = canonical(value)
    return sha256(
        json.dumps(
            value, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _snapshot_fingerprint(payload: dict) -> str:
    # Preserve pre-scheduler v1 snapshot IDs. Later engine revisions need a distinct
    # identity even if the underlying rows and registered definition stay unchanged.
    if PIPELINE_VERSION != "signal-sql-v1":
        payload = {**payload, "pipeline": PIPELINE_VERSION}
    return _fingerprint(payload)


def definition_fingerprint(definition: SignalDefinition) -> str:
    payload = definition.model_dump(mode="json")
    payload["source_ids"] = sorted(payload["source_ids"])
    payload["metrics"] = sorted(payload["metrics"], key=lambda metric: metric["key"])
    return _fingerprint(payload)


class _Unavailable(ValueError):
    pass


def _validate_sql(sql: str, data: InvestigationData) -> None:
    # Conservative reusable-definition guard, in addition to InvestigationData's
    # SELECT-only/external-access checks. Dates belong to the injected run window.
    uncommented = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.S)
    if re.search(
        r"\b(limit|offset|fetch|sample|tablesample|make_date|make_timestamp|to_timestamp|strptime|using\s+sample|current_date|current_timestamp|now|random|uuid)\b",
        uncommented,
        re.I,
    ):
        raise _Unavailable("non_reusable_sql")
    if re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|'customer_[a-z0-9]+'", uncommented, re.I):
        raise _Unavailable("non_reusable_sql")
    if re.search(
        r"""\bcustomer_id\s*(?:=|!=|<>|in\s*\(|like\b)\s*['"]|['"][^'"]+['"]\s*=\s*(?:\w+\.)?customer_id\b""",
        uncommented,
        re.I,
    ):
        raise _Unavailable("non_reusable_sql")
    # Never permit catalog reads or arbitrary table-producing functions. CTEs and
    # joins over the selected source views remain supported by the original engine.
    if re.search(
        r"\b(information_schema|pg_catalog|sqlite_master)\b|\b(?:from|join)\s+[\w.]+\s*\(",
        uncommented,
        re.I,
    ):
        raise _Unavailable("non_reusable_sql")
    # Inspect real base-table dependencies in the same restricted data space.
    # Binding table functions must retain its disabled external access.
    try:
        tables = data.referenced_tables(uncommented)
    except Exception as exc:
        raise _Unavailable("query_failed") from exc
    selected_tables = {"events", *data.request.enabled_sources}
    if not tables or not tables <= selected_tables:
        raise _Unavailable("non_reusable_sql")
    for customer in data.customer_ids:
        if customer in uncommented:
            raise _Unavailable("non_reusable_sql")


def _empty_values(definition: SignalDefinition) -> list[MetricValue]:
    values = [
        MetricValue(
            key="affected_customer_count", label="대상 고객 수", value=None, unit="customers"
        )
    ]
    if definition.denominator_sql is not None:
        values.extend(
            [
                MetricValue(
                    key="denominator_customer_count",
                    label="모집단 고객 수",
                    value=None,
                    unit="customers",
                ),
                MetricValue(
                    key="affected_customer_rate", label="대상 고객 비율", value=None, unit="percent"
                ),
            ]
        )
    values.extend(
        MetricValue(key=m.key, label=m.label, value=None, unit=m.unit) for m in definition.metrics
    )
    return values


def measure_definition(data: InvestigationData, definition: SignalDefinition) -> Measurement:
    source_ids = sorted(definition.source_ids)
    scoped = None
    versions = {}
    queries, results = [], []
    common = dict(
        measurement_id="measurement-" + uuid4().hex,
        definition_fingerprint=definition_fingerprint(definition),
        pipeline_version=PIPELINE_VERSION,
        start_at=data.request.start_at,
        end_at=data.request.end_at,
        source_ids=source_ids,
    )
    snapshot = _snapshot_fingerprint({"source_ids": source_ids, "missing": True})
    try:
        if not set(source_ids) <= set(data.request.enabled_sources):
            raise _Unavailable("missing_source")
        scoped = data.restrict(source_ids)
        for source_id in source_ids:
            manifest = next((m for m in scoped.manifests if m.source_id == source_id), None)
            versions[source_id] = _fingerprint(
                {
                    "manifest": manifest.model_dump(mode="python")
                    if manifest is not None
                    else None,
                    "columns": scoped.columns,
                }
            )
        snapshot = _snapshot_fingerprint(
            {
                "source_ids": source_ids,
                "versions": versions,
                "start_at": data.request.start_at,
                "end_at": data.request.end_at,
                "events": sorted(scoped.events, key=lambda event: event["event_id"]),
            }
        )

        def execute(sql: str) -> dict:
            _validate_sql(sql, scoped)
            try:
                preview = scoped.query(sql)
            except Exception as exc:
                raise _Unavailable("query_failed") from exc
            record = {**scoped.queries[preview["query_id"]], "snapshot_id": snapshot}
            results.append(record)
            queries.append({**preview, "snapshot_id": snapshot})
            return record

        def cohort(sql: str) -> list[str]:
            record = execute(sql)
            try:
                return scoped.cohort(record["query_id"])
            except (ValueError, TypeError) as exc:
                raise _Unavailable("invalid_cohort") from exc

        ids = cohort(definition.cohort_sql)
        values = _empty_values(definition)
        values[0].value = len(ids)
        if definition.denominator_sql is not None:
            denominator = cohort(definition.denominator_sql)
            if not denominator:
                raise _Unavailable("zero_denominator")
            if not set(ids) <= set(denominator):
                raise _Unavailable("cohort_outside_denominator")
            values[1].value = len(denominator)
            values[2].value = len(ids) / len(denominator) * 100
            values[2].numerator, values[2].denominator = len(ids), len(denominator)
        offset = 3 if definition.denominator_sql is not None else 1
        for index, metric in enumerate(definition.metrics):
            record = execute(metric.sql)
            if record["row_count"] != 1 or len(record["columns"]) != 1:
                raise _Unavailable("invalid_metric")
            scalar = record["rows"][0][record["columns"][0]]
            if (
                isinstance(scalar, bool)
                or not isinstance(scalar, (int, float))
                or not math.isfinite(scalar)
            ):
                raise _Unavailable("invalid_metric")
            values[offset + index].value = scalar
        return Measurement(
            **common,
            snapshot_id=snapshot,
            source_versions=versions,
            status="success",
            values=values,
            queries=queries,
            query_results=results,
            cohort_customer_ids=ids,
        )
    except _Unavailable as exc:
        return Measurement(
            **common,
            snapshot_id=snapshot,
            source_versions=versions,
            status="unavailable",
            reason=str(exc),
            values=_empty_values(definition),
            queries=queries,
            query_results=results,
        )
    finally:
        if scoped is not None:
            scoped.close()


def unavailable_measurement(
    definition: SignalDefinition, start_at: datetime, end_at: datetime, reason: str
) -> Measurement:
    """Record a load failure using a caller-selected public reason, without raw errors."""
    return Measurement(
        measurement_id="measurement-" + uuid4().hex,
        definition_fingerprint=definition_fingerprint(definition),
        pipeline_version=PIPELINE_VERSION,
        start_at=start_at,
        end_at=end_at,
        snapshot_id=_snapshot_fingerprint(
            {
                "unavailable": reason,
                "sources": sorted(definition.source_ids),
                "start_at": start_at,
                "end_at": end_at,
            }
        ),
        status="unavailable",
        reason=reason,
        values=_empty_values(definition),
        source_ids=sorted(definition.source_ids),
    )
