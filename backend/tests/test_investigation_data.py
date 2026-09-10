from datetime import datetime, timezone

import pytest

from customer_signal.agent.contracts import RunRequest
from customer_signal.domain.models import CustomerEvent
from customer_signal.investigation.data import InvestigationData


def event(number, *, source="app", customer="private-id", topic="vas_wandering"):
    return CustomerEvent(
        event_id=f"event-{number}",
        evidence_id=f"evidence-{number}",
        source_id=source,
        occurred_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        event_type="menu_view",
        action="마이",
        topic=topic,
        outcome="vas_unreachable",
        text="메뉴 탐색",
        canonical_customer_id=customer,
        dimensions={"menu": "마이", "abtest_group": "treatment"},
        measures={"page_stay_seconds": 12},
    )


@pytest.fixture(scope="module")
def space():
    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )
    data = InvestigationData(
        request=request,
        events=[event(i) for i in range(10001)],
        manifests=[],
        snapshot_id="test-snapshot",
    )
    yield data
    data.close()


def test_full_scan_masking_and_oracle_exclusion(space):
    result = space.query(
        "SELECT count(*) AS n, count(DISTINCT customer_id) AS customers FROM events"
    )
    assert result["rows"] == [{"n": 10001, "customers": 1}]
    row = space.query("SELECT * FROM events LIMIT 1")["rows"][0]
    assert row["customer_id"].startswith("customer_")
    assert "private-id" not in str(row)
    assert "wandering" not in str(row) and "unreachable" not in str(row)
    assert "abtest" not in str(row)
    assert row["dim_menu"] == "마이" and row["measure_page_stay_seconds"] == 12
    assert result["query_id"] in space.queries


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM events",
        "SELECT 1; SELECT 2",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM sqlite_scan('/tmp/x','t')",
    ],
)
def test_read_only_database_cannot_escape(space, sql):
    with pytest.raises((ValueError, Exception)):
        space.query(sql)


def test_scope_rejected_and_query_results_cannot_invent_cohort(space):
    with pytest.raises(ValueError, match="scope"):
        InvestigationData(
            request=space.request,
            events=[event(1, source="other")],
            manifests=[],
            snapshot_id="bad",
        )
    result = space.query("SELECT DISTINCT customer_id FROM events")
    customers = space.cohort(result["query_id"])
    assert len(customers) == 1
    assert len(space.journey(customers[0])["events"]) == 100
    assert space.journey(customers[0])["total_events"] == 10001
    assert space.journey(customers[0])["events"][-1] == space.events[-1]
    fake = space.query("SELECT 'invented' AS customer_id")
    with pytest.raises(ValueError, match="customer"):
        space.cohort(fake["query_id"])


def test_query_keeps_complete_results_past_old_row_and_sql_length_limits(space):
    sql = "SELECT range AS n FROM range(50001) /*" + "x" * 16001 + "*/"
    result = space.query(sql)
    assert result["row_count"] == 50001
    assert len(result["rows"]) == 100
    assert result["truncated"] is True
    assert len(space.queries[result["query_id"]]["rows"]) == 50001


def test_restrict_uses_only_registered_sources_and_preserves_window(space):
    assert hasattr(space, 'restrict'), 'Signal measurement needs a fixed source scope'
    restricted = space.restrict(['app'])
    try:
        assert restricted.request.start_at == space.request.start_at
        assert restricted.catalog()['event_count'] == 10001
        restricted.query('SELECT DISTINCT customer_id FROM events')
    finally:
        restricted.close()
    with pytest.raises(ValueError, match='scope'):
        space.restrict(['other'])
    assert space.query('SELECT count(*) AS n FROM events')['rows'][0]['n'] == 10001


def test_referenced_tables_uses_external_access_disabled_connection():
    request = RunRequest(question='추적', start_at='2026-09-04T00:00:00Z',
        end_at='2026-09-11T00:00:00Z', enabled_sources=['app'])
    data = InvestigationData(request=request, events=[event(1)], manifests=[], snapshot_id='test')
    try:
        assert hasattr(data, 'referenced_tables'), 'Dependency validation must use scoped database'
        assert data.referenced_tables('SELECT count(*) FROM events') == {'events'}
        assert data.referenced_tables('WITH events AS (SELECT 999) SELECT * FROM events') == set()
        with pytest.raises((ValueError, Exception)):
            data.referenced_tables("SELECT * FROM read_csv_auto('/tmp/not-authorized.csv')")
    finally:
        data.close()
