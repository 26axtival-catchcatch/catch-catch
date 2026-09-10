"""Transactional rule selection, edge detection and durable cursor-based alert feed."""

from __future__ import annotations

import json
import math
import operator
from datetime import datetime
from uuid import uuid4

from customer_signal.signals.alert_contracts import (
    AlertEvent,
    AlertEvents,
    AlertRule,
    AlertRules,
    RecommendationSet,
    RuleSelection,
)
from customer_signal.signals.comparison import comparison_limitations
from customer_signal.signals.contracts import Measurement, Signal, now

_OPERATORS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}


class RuleConflict(ValueError):
    """The caller must reload the rules before overwriting another edit."""


def initialize_alerts(db) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS signal_alert_settings (
            signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id), payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_alert_state (
            rule_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL REFERENCES signals(signal_id),
            matched INTEGER NOT NULL DEFAULT 0, last_end_at TEXT
        );
        CREATE INDEX IF NOT EXISTS alert_state_by_signal ON signal_alert_state(signal_id);
        CREATE TABLE IF NOT EXISTS signal_alert_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            signal_id TEXT NOT NULL REFERENCES signals(signal_id),
            rule_id TEXT NOT NULL, measurement_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(rule_id, measurement_id)
        );
    """)


def validate_threshold(recommendation) -> None:
    if recommendation.kind != "value":
        return
    value = recommendation.threshold
    if recommendation.metric_unit in {"%", "percent"} and not 0 <= value <= 100:
        raise ValueError("percent thresholds must be between 0 and 100")
    if recommendation.metric_key in {"affected_customer_count", "denominator_customer_count"}:
        if value < 0:
            raise ValueError("customer count thresholds cannot be negative")


def _rules(db, signal_id: str) -> AlertRules:
    row = db.execute(
        "SELECT payload FROM signal_alert_settings WHERE signal_id=?",
        (signal_id,),
    ).fetchone()
    return AlertRules.model_validate_json(row[0]) if row else AlertRules(signal_id=signal_id)


class AlertStore:
    def __init__(self, store):
        self.store = store

    def save_recommendations(self, signal_id: str, recommendations: RecommendationSet) -> Signal:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            signal = self.store._read(db, "signals", "signal_id", signal_id, Signal)
            # The first successful recommendation set is immutable: selections reference its IDs.
            current = signal.alert_recommendations
            if current is not None and current.status == "ready":
                return signal
            signal = signal.model_copy(update={"alert_recommendations": recommendations})
            db.execute(
                "UPDATE signals SET payload=? WHERE signal_id=?",
                (signal.model_dump_json(), signal_id),
            )
            return signal

    def get_rules(self, signal_id: str) -> AlertRules:
        with self.store._connection() as db:
            self.store._read(db, "signals", "signal_id", signal_id, Signal)
            return _rules(db, signal_id)

    def replace_rules(self, signal_id: str, request: RuleSelection) -> AlertRules:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            signal = self.store._read(db, "signals", "signal_id", signal_id, Signal)
            existing = _rules(db, signal_id)
            if existing.revision != request.revision:
                raise RuleConflict("alert rules were changed by another request")
            recommendations = {
                r.recommendation_id: r
                for r in (
                    signal.alert_recommendations.items if signal.alert_recommendations else []
                )
            }
            previous = {r.recommendation_id: r for r in existing.items}
            selected = []
            for item in request.items:
                if item.recommendation_id not in recommendations:
                    raise ValueError("unknown recommendation_id for this signal")
                draft = recommendations[item.recommendation_id]
                threshold = draft.threshold if item.threshold is None else item.threshold
                old = previous.get(item.recommendation_id)
                rule = AlertRule(
                    **{
                        **draft.model_dump(),
                        "threshold": threshold,
                        "rule_id": old.rule_id
                        if old and old.threshold == threshold
                        else uuid4().hex,
                    }
                )
                validate_threshold(rule)
                selected.append(rule)
            selected.sort(key=lambda r: r.recommendation_id)
            if selected == existing.items:
                return existing
            latest = db.execute(
                "SELECT MAX(end_at) FROM signal_measurements WHERE signal_id=?",
                (signal_id,),
            ).fetchone()[0]
            keep = {r.rule_id for r in selected}
            for old in existing.items:
                if old.rule_id not in keep:
                    db.execute("DELETE FROM signal_alert_state WHERE rule_id=?", (old.rule_id,))
            for rule in selected:
                db.execute(
                    "INSERT OR IGNORE INTO signal_alert_state VALUES (?, ?, 0, ?)",
                    (rule.rule_id, signal_id, latest),
                )
            result = AlertRules(signal_id=signal_id, revision=existing.revision + 1, items=selected)
            db.execute(
                "INSERT OR REPLACE INTO signal_alert_settings VALUES (?, ?)",
                (signal_id, result.model_dump_json()),
            )
            return result

    def events(self, *, after: int | None = None, limit: int = 100) -> AlertEvents:
        with self.store._connection() as db:
            db.execute("BEGIN")
            latest = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM signal_alert_events"
            ).fetchone()[0]
            if after is None:
                return AlertEvents(
                    items=[], next_cursor=latest, latest_cursor=latest, has_more=False
                )
            rows = db.execute(
                "SELECT sequence, payload FROM signal_alert_events WHERE sequence>? "
                "ORDER BY sequence LIMIT ?",
                (after, limit + 1),
            ).fetchall()
            items = [
                AlertEvent.model_validate({**json.loads(p), "sequence": seq})
                for seq, p in rows[:limit]
            ]
            return AlertEvents(
                items=items,
                next_cursor=items[-1].sequence if items else after,
                latest_cursor=latest,
                has_more=len(rows) > limit,
            )


def evaluate_measurement(db, signal: Signal, measurement: Measurement) -> None:
    """Called inside the measurement write transaction, never from a polling GET."""
    if signal.status != "active" or measurement.status != "success":
        return
    if (measurement.end_at - measurement.start_at).total_seconds() != 86400:
        return
    rules = _rules(db, signal.signal_id)
    if not rules.items:
        return
    values = {v.key: v for v in measurement.values}
    # Latest successful non-overlapping daily period. A changed version is deliberately
    # not bypassed by searching further back: it must not silently become a stale baseline.
    row = db.execute(
        "SELECT payload FROM signal_measurements WHERE signal_id=? AND status='success' "
        "AND end_at<=? AND measurement_id!=? ORDER BY end_at DESC, "
        "(julianday(end_at)-julianday(start_at)=1) DESC, rowid DESC LIMIT 1",
        (signal.signal_id, measurement.start_at.isoformat(), measurement.measurement_id),
    ).fetchone()
    baseline = Measurement.model_validate_json(row[0]) if row else None
    previous_values = {v.key: v for v in baseline.values} if baseline else {}
    comparable = baseline is not None and not comparison_limitations([baseline, measurement])
    for rule in rules.items:
        matched, last_end = db.execute(
            "SELECT matched, last_end_at FROM signal_alert_state WHERE rule_id=?",
            (rule.rule_id,),
        ).fetchone()
        if last_end and measurement.end_at <= datetime.fromisoformat(last_end):
            continue
        metric = values.get(rule.metric_key)
        if metric is None or metric.value is None or metric.unit != rule.metric_unit:
            continue
        if rule.kind == "value":
            observed, before, baseline_id = metric.value, None, None
        else:
            previous_metric = previous_values.get(rule.metric_key)
            if (
                not comparable
                or previous_metric is None
                or previous_metric.value is None
                or previous_metric.unit != metric.unit
            ):
                continue
            before, baseline_id = previous_metric.value, baseline.measurement_id
            try:
                observed = metric.value - before
                if rule.kind == "relative_change_percent":
                    observed = observed / abs(before) * 100 if before else None
            except OverflowError:
                # Finite inputs can still overflow when calculating their change.
                continue
        if observed is None or not math.isfinite(observed):
            continue
        is_matched = _OPERATORS[rule.operator](observed, rule.threshold)
        if is_matched and not matched:
            event = AlertEvent(
                sequence=0,
                event_id=uuid4().hex,
                signal_id=signal.signal_id,
                signal_title=signal.title,
                rule=rule,
                measurement_id=measurement.measurement_id,
                baseline_measurement_id=baseline_id,
                observed_value=observed,
                metric_value=metric.value,
                baseline_value=before,
                start_at=measurement.start_at,
                end_at=measurement.end_at,
                occurred_at=now(),
            )
            db.execute(
                "INSERT INTO signal_alert_events "
                "(event_id, signal_id, rule_id, measurement_id, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    signal.signal_id,
                    rule.rule_id,
                    measurement.measurement_id,
                    event.model_dump_json(exclude={"sequence"}),
                ),
            )
        db.execute(
            "UPDATE signal_alert_state SET matched=?, last_end_at=? WHERE rule_id=?",
            (is_matched, measurement.end_at.isoformat(), rule.rule_id),
        )
