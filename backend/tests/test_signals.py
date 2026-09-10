from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from uuid import uuid4

import pytest

from customer_signal.agent.contracts import RunRequest
from customer_signal.domain.models import CustomerEvent
from customer_signal.investigation.data import InvestigationData


def core():
    assert find_spec("customer_signal.signals.contracts"), "Signal contracts are not implemented"
    from customer_signal.signals.contracts import MetricDefinition, Proposal, SignalDefinition
    from customer_signal.signals.measurement import measure_definition
    from customer_signal.signals.store import SignalStore

    return MetricDefinition, Proposal, SignalDefinition, measure_definition, SignalStore


def make_data(*, day=1, sources=None, rows=None):
    start = datetime(2026, 9, day, tzinfo=timezone.utc)
    sources = sources or ["app"]
    if rows is None:
        rows = [("a", "app", "close"), ("a", "app", "close"), ("b", "app", "done")]
    events = [
        CustomerEvent(
            event_id=f"e-{i}",
            evidence_id=f"ev-{i}",
            source_id=source,
            occurred_at=start + timedelta(hours=1),
            event_type="menu_view",
            action=action,
            topic="settings",
            outcome="unknown",
            text="",
            canonical_customer_id=customer,
            measures={"duration": 10},
        )
        for i, (customer, source, action) in enumerate(rows)
    ]
    return InvestigationData(
        request=RunRequest(
            question="test",
            start_at=start,
            end_at=start + timedelta(days=1),
            enabled_sources=sources,
        ),
        events=events,
        manifests=[],
        snapshot_id=str(uuid4()),
    )


def definition(**overrides):
    _, _, Definition, _, _ = core()
    return Definition(
        **dict(
            source_ids=["app"],
            cohort_sql="SELECT customer_id FROM events WHERE action = 'close'",
            denominator_sql="SELECT customer_id FROM events",
            population_description="메뉴 방문 고객",
            normal_comparison="완료 고객과 비교",
        )
        | overrides
    )


def values(measurement):
    return {value.key: value.value for value in measurement.values}


def test_distinct_counts_rate_scalar_and_stable_content_snapshot():
    Metric, _, _, measure, _ = core()
    d = definition(
        metrics=[
            Metric(
                key="duration",
                label="평균 시간",
                sql="SELECT avg(measure_duration) FROM events",
                unit="seconds",
            )
        ]
    )
    first, second = make_data(), make_data()
    try:
        m = measure(first, d)
        assert m.status == "success"
        assert values(m) == {
            "affected_customer_count": 1,
            "denominator_customer_count": 2,
            "affected_customer_rate": 50,
            "duration": 10,
        }
        assert m.snapshot_id == measure(second, d).snapshot_id
        assert "cohort_customer_ids" not in m.model_dump(mode="json")
        assert "query_results" not in m.model_dump(mode="json")
    finally:
        first.close()
        second.close()


def test_source_scope_does_not_expand_with_other_sources():
    *_, measure, _ = core()
    data = make_data(
        sources=["app", "other"], rows=[("a", "app", "close"), ("b", "other", "close")]
    )
    try:
        assert values(measure(data, definition()))["denominator_customer_count"] == 1
        assert (
            measure(data, definition(cohort_sql="SELECT customer_id FROM other")).status
            == "unavailable"
        )
        assert measure(data, definition(source_ids=["missing"])).reason == "missing_source"
    finally:
        data.close()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"denominator_sql": "SELECT customer_id FROM events WHERE false"}, "zero_denominator"),
        (
            {"denominator_sql": "SELECT customer_id FROM events WHERE action = 'done'"},
            "cohort_outside_denominator",
        ),
        ({"cohort_sql": "SELECT 'invented' AS customer_id FROM events"}, "invalid_cohort"),
        ({"cohort_sql": "SELECT missing_column AS customer_id FROM events"}, "query_failed"),
        ({"cohort_sql": "SELECT customer_id FROM events LIMIT 1"}, "non_reusable_sql"),
        (
            {"cohort_sql": "SELECT customer_id FROM events WHERE occurred_at > '2026-09-01'"},
            "non_reusable_sql",
        ),
        (
            {"cohort_sql": "SELECT customer_id FROM events WHERE customer_id = 'customer_abc'"},
            "non_reusable_sql",
        ),
    ],
)
def test_unavailable_is_distinct_from_zero(overrides, reason):
    *_, measure, _ = core()
    data = make_data()
    try:
        m = measure(data, definition(**overrides))
        assert m.status == "unavailable" and m.reason == reason
        assert all(v.value is None for v in m.values)
        zero = measure(
            data,
            definition(
                cohort_sql="SELECT customer_id FROM events WHERE false", denominator_sql=None
            ),
        )
        assert zero.status == "success" and values(zero)["affected_customer_count"] == 0
    finally:
        data.close()


def test_empty_available_source_without_denominator_is_zero():
    *_, measure, _ = core()
    data = make_data(rows=[])
    try:
        assert values(measure(data, definition(denominator_sql=None))) == {
            "affected_customer_count": 0
        }
    finally:
        data.close()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT NULL FROM events",
        "SELECT true FROM events",
        "SELECT 1, 2 FROM events",
        "SELECT measure_duration FROM events",
        "SELECT 'NaN'::DOUBLE FROM events",
    ],
)
def test_extra_metrics_require_one_finite_numeric_scalar(sql):
    Metric, _, _, measure, _ = core()
    data = make_data()
    try:
        m = measure(
            data, definition(metrics=[Metric(key="extra", label="추가", sql=sql, unit="count")])
        )
        assert m.status == "unavailable" and m.reason == "invalid_metric"
    finally:
        data.close()


def test_persistent_registration_and_measurement_idempotency(tmp_path):
    _, Proposal, _, measure, Store = core()
    data, next_data = (
        make_data(),
        make_data(day=2, rows=[("a", "app", "close"), ("b", "app", "close")]),
    )
    try:
        d = definition()
        m = measure(data, d)
        p = Proposal(
            proposal_id="p1",
            run_id="run1",
            candidate_id="c1",
            title="시그널",
            description="설명",
            definition=d,
            measurement=m,
            created_at=datetime.now(timezone.utc),
        )
        store = Store(tmp_path / "signals.sqlite3")
        store.save_proposal(p)
        assert store.list_signals() == []
        signal = store.register("p1")
        store = Store(tmp_path / "signals.sqlite3")
        assert store.register("p1").signal_id == signal.signal_id
        store.save_proposal(p.model_copy(update={"proposal_id": "p2", "title": "같은 정의"}))
        assert store.register("p2").signal_id == signal.signal_id
        assert len(store.list_measurements(signal.signal_id)) == 1
        assert store.list_measurements(signal.signal_id)[0].query_results
        second = store.add_measurement(signal.signal_id, measure(next_data, d))
        assert (
            store.add_measurement(signal.signal_id, measure(next_data, d)).measurement_id
            == second.measurement_id
        )
        assert len(store.list_measurements(signal.signal_id)) == 2
        corrected = make_data(day=2, rows=[("a", "app", "close"), ("b", "app", "done")])
        try:
            store.add_measurement(signal.signal_id, measure(corrected, d))
        finally:
            corrected.close()
        assert len(store.list_measurements(signal.signal_id)) == 3
        assert values(store.list_measurements(signal.signal_id)[0])["affected_customer_count"] == 1
        assert store.set_status(signal.signal_id, "paused").status == "paused"
        assert Store(tmp_path / "signals.sqlite3").get_signal(signal.signal_id).status == "paused"
        assert store.set_status(signal.signal_id, "archived").status == "archived"
        assert len(store.list_proposals("run1")) == 2
        with pytest.raises(ValueError):
            store.add_measurement(signal.signal_id, measure(data, definition(denominator_sql=None)))
        with pytest.raises(KeyError):
            store.get_signal("missing")
    finally:
        data.close()
        next_data.close()


def test_unavailable_load_can_be_persisted_without_blocking_success_retry(tmp_path):
    from customer_signal.signals import measurement as engine

    assert hasattr(engine, "unavailable_measurement"), "load failure factory is missing"
    _, Proposal, _, measure, Store = core()
    data = make_data()
    try:
        d = definition()
        good = measure(data, d)
        store = Store(tmp_path / "retry.sqlite3")
        store.save_proposal(
            Proposal(
                proposal_id="p",
                run_id="r",
                candidate_id="c",
                title="제안",
                description="설명",
                definition=d,
                measurement=good,
            )
        )
        signal = store.register("p")
        failure = engine.unavailable_measurement(
            d, good.start_at, good.end_at, "source_unavailable"
        )
        assert all(value.value is None for value in failure.values)
        failure = failure.model_copy(update={"snapshot_id": good.snapshot_id})
        store.add_measurement(signal.signal_id, failure)
        assert store.add_measurement(signal.signal_id, good).status == "success"
        assert len(store.list_measurements(signal.signal_id)) == 2
        with pytest.raises(ValueError):
            store.save_proposal(
                Proposal(
                    proposal_id="bad",
                    run_id="r",
                    candidate_id="c",
                    title="실패",
                    description="설명",
                    definition=d,
                    measurement=failure,
                )
            )
    finally:
        data.close()


def test_complete_cohort_is_persisted_beyond_public_preview(tmp_path):
    _, Proposal, _, measure, Store = core()
    data = make_data(rows=[(f"c{i}", "app", "close") for i in range(130)])
    try:
        m = measure(data, definition())
        assert values(m)["affected_customer_count"] == 130
        assert len(m.queries[0]["rows"]) == 100
        assert len(m.query_results[0]["rows"]) == 130
        store = Store(tmp_path / "full.sqlite3")
        store.save_proposal(
            Proposal(
                proposal_id="p",
                run_id="r",
                candidate_id="c",
                title="제안",
                description="설명",
                definition=definition(),
                measurement=m,
            )
        )
        assert len(Store(store.path).get_proposal("p").measurement.cohort_customer_ids) == 130
    finally:
        data.close()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "DELETE FROM events",
        "SELECT customer_id FROM events; SELECT customer_id FROM events",
        "SELECT customer_id FROM events WHERE occurred_at > make_date(2026, 9, 1)",
        "SELECT customer_id FROM events FETCH FIRST 1 ROW ONLY",
    ],
)
def test_non_reusable_or_unsafe_sql_cannot_succeed(sql):
    *_, measure, _ = core()
    data = make_data()
    try:
        assert measure(data, definition(cohort_sql=sql)).status == "unavailable"
    finally:
        data.close()


def test_concurrent_registration_uses_one_signal_and_initial_measurement(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    _, Proposal, _, measure, Store = core()
    data = make_data()
    try:
        store = Store(tmp_path / "concurrent.sqlite3")
        store.save_proposal(
            Proposal(
                proposal_id="p",
                run_id="r",
                candidate_id="c",
                title="제안",
                description="설명",
                definition=definition(),
                measurement=measure(data, definition()),
            )
        )
        stores = [Store(store.path) for _ in range(6)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            signals = list(pool.map(lambda instance: instance.register("p"), stores))
        assert len({signal.signal_id for signal in signals}) == 1
        assert len(store.list_signals()) == 1
        assert len(store.list_measurements(signals[0].signal_id)) == 1
    finally:
        data.close()


def test_registration_rolls_back_signal_when_initial_measurement_conflicts(tmp_path):
    _, Proposal, _, measure, Store = core()
    data = make_data()
    try:
        store = Store(tmp_path / "atomic.sqlite3")
        first = measure(data, definition())
        store.save_proposal(
            Proposal(
                proposal_id="p1",
                run_id="r",
                candidate_id="c1",
                title="제안",
                description="설명",
                definition=definition(),
                measurement=first,
            )
        )
        store.register("p1")
        other_definition = definition(denominator_sql=None)
        colliding = measure(data, other_definition).model_copy(
            update={"measurement_id": first.measurement_id}
        )
        store.save_proposal(
            Proposal(
                proposal_id="p2",
                run_id="r",
                candidate_id="c2",
                title="다른 정의",
                description="설명",
                definition=other_definition,
                measurement=colliding,
            )
        )
        with pytest.raises(ValueError, match="measurement_id"):
            store.register("p2")
        assert len(store.list_signals()) == 1
    finally:
        data.close()


def test_same_window_offsets_share_snapshot_and_store_signature(tmp_path):
    _, Proposal, _, measure, Store = core()
    utc_data = make_data()
    kst = timezone(timedelta(hours=9))
    kst_data = InvestigationData(
        request=utc_data.request.model_copy(
            update={
                "start_at": utc_data.request.start_at.astimezone(kst),
                "end_at": utc_data.request.end_at.astimezone(kst),
            }
        ),
        events=[
            event.model_copy(update={"occurred_at": event.occurred_at.astimezone(kst)})
            for event in utc_data._raw_events
        ],
        manifests=[],
        snapshot_id="other",
    )
    try:
        first, second = measure(utc_data, definition()), measure(kst_data, definition())
        assert first.snapshot_id == second.snapshot_id
        store = Store(tmp_path / "offset.sqlite3")
        store.save_proposal(
            Proposal(
                proposal_id="p",
                run_id="r",
                candidate_id="c",
                title="제안",
                description="설명",
                definition=definition(),
                measurement=first,
            )
        )
        signal = store.register("p")
        assert (
            store.add_measurement(signal.signal_id, second).measurement_id == first.measurement_id
        )
    finally:
        utc_data.close()
        kst_data.close()


@pytest.mark.parametrize(
    "sql",
    ["SELECT 999", 'SELECT 999 AS "from events"', "WITH x AS (SELECT 999 AS n) SELECT n FROM x"],
)
def test_scalar_metrics_must_read_selected_data(sql):
    Metric, _, _, measure, _ = core()
    data = make_data()
    try:
        m = measure(
            data, definition(metrics=[Metric(key="extra", label="추가", sql=sql, unit="count")])
        )
        assert m.status == "unavailable"
    finally:
        data.close()


def test_metric_sql_supports_korean_alias_and_valid_source_cte():
    Metric, _, _, measure, _ = core()
    data = make_data()
    try:
        m = measure(
            data,
            definition(
                metrics=[
                    Metric(
                        key="extra",
                        label="평균",
                        sql='WITH x AS (SELECT * FROM "app") SELECT avg(measure_duration) AS "평균" FROM x',
                        unit="seconds",
                    )
                ]
            ),
        )
        assert m.status == "success"
        m = measure(
            data,
            definition(
                metrics=[
                    Metric(
                        key="extra",
                        label="평균",
                        sql='SELECT avg(measure_duration) AS "평균" FROM events',
                        unit="seconds",
                    )
                ]
            ),
        )
        assert m.status == "success"
    finally:
        data.close()


def test_constant_cte_cannot_impersonate_selected_source():
    Metric, _, _, measure, _ = core()
    data = make_data()
    try:
        m = measure(
            data,
            definition(
                metrics=[
                    Metric(
                        key="extra",
                        label="상수",
                        sql="WITH events AS (SELECT 999 AS n) SELECT n FROM events",
                        unit="count",
                    )
                ]
            ),
        )
        assert m.status == "unavailable"
    finally:
        data.close()


def test_table_dependency_inspection_cannot_enable_external_access():
    Metric, _, _, measure, _ = core()
    data = make_data()
    try:
        m = measure(
            data,
            definition(
                metrics=[
                    Metric(
                        key="extra",
                        label="외부",
                        sql="SELECT count(*) FROM events UNION ALL SELECT count(*) FROM \"read_csv\"('/etc/passwd')",
                        unit="count",
                    )
                ]
            ),
        )
        assert m.status == "unavailable"
        assert "/etc/passwd" not in (m.reason or "")
    finally:
        data.close()


def test_actual_manifest_fingerprints_stable_across_fresh_hash_seed_processes():
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent("""
        import json
        import runpy
        import sys
        from customer_signal.domain.sources import SourceManifest
        from customer_signal.signals.measurement import measure_definition

        helpers = runpy.run_path(sys.argv[1])
        data = helpers['make_data']()
        manifest = SourceManifest.model_validate_json(json.dumps({
            'source_id': 'app', 'label': 'App', 'description': 'Synthetic app events',
            'adapter_version': '1', 'manifest_version': '1',
            'data_interval': {'start_at': '2026-09-01T00:00:00Z',
                              'end_at': '2026-09-02T00:00:00Z'},
            'refresh_cadence': 'daily',
            'supported_event_types': ['menu_view', 'search'],
            'supported_topics': ['settings', 'account'],
            'supported_outcomes': ['unknown', 'completed'],
            'dimensions': {'channel': {'semantic_type': 'category',
                'description': 'Channel', 'pii_classification': 'none',
                'allowed_values': ['web', 'app']}},
            'capabilities': ['aggregate_events'],
            'masking_policy': {'rules': {}},
            'identity_quality': {'namespace': 'customer', 'link_method': 'synthetic',
                                 'confidence': 1.0}
        }))
        data.manifests = [manifest]
        try:
            measurement = measure_definition(data, helpers['definition']())
            assert measurement.status == 'success'
            print(json.dumps({'source_versions': measurement.source_versions,
                              'snapshot_id': measurement.snapshot_id}))
        finally:
            data.close()
    """)
    results = []
    for seed in ("1", "3"):
        environment = {
            **os.environ,
            "PYTHONHASHSEED": seed,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        process = subprocess.run(
            [sys.executable, "-c", script, str(Path(__file__).resolve())],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        results.append(json.loads(process.stdout))
    assert results[0] == results[1]
