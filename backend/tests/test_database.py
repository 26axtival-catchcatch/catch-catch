from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from customer_signal.data import database
from customer_signal.data.database import seed_database
from customer_signal.data import repository as repository_module
from customer_signal.data.repository import (
    DatabaseNotFoundError,
    DuckDBRepository,
    EntityNotFoundError,
)
from customer_signal.domain.models import (
    CustomerEvent,
    EvidenceRecord,
    IdentityEdge,
    SyntheticDataset,
)
from customer_signal.synthetic.generator import generate_dataset
from customer_signal.synthetic.manifest import SYNTHETIC_MANIFEST_VERSION


SEOUL = ZoneInfo("Asia/Seoul")
START_AT = datetime(2026, 7, 20, tzinfo=SEOUL)
END_AT = datetime(2026, 8, 19, tzinfo=SEOUL)
ALL_SOURCES = [
    "search_history",
    "search_feedback",
    "digital_behavior",
    "subscription",
    "voc",
]


def _edge_key(edge: IdentityEdge) -> tuple[str, str, str, str, str]:
    return (
        edge.left.namespace,
        edge.left.value,
        edge.right.namespace,
        edge.right.value,
        edge.link_type,
    )


def _connected_edges(events: list[CustomerEvent], edges: list[IdentityEdge]) -> list[IdentityEdge]:
    graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for edge in edges:
        left = (edge.left.namespace, edge.left.value)
        right = (edge.right.namespace, edge.right.value)
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    connected = {
        (identity.namespace, identity.value) for event in events for identity in event.identities
    }
    pending = list(connected)
    while pending:
        node = pending.pop()
        for neighbor in graph.get(node, set()) - connected:
            connected.add(neighbor)
            pending.append(neighbor)
    return sorted(
        [
            edge
            for edge in edges
            if (edge.left.namespace, edge.left.value) in connected
            and (edge.right.namespace, edge.right.value) in connected
        ],
        key=_edge_key,
    )


def test_seed_database_atomically_creates_expected_schema_and_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    dataset = generate_dataset(seed=20260819)
    database_path = tmp_path / "nested" / "customer-signal.duckdb"
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        replacements.append((source_path, destination_path))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(database.os, "replace", recording_replace)

    seed_database(database_path, dataset)

    assert database_path.is_file()
    assert len(replacements) == 1
    temporary_path, final_path = replacements[0]
    assert temporary_path.parent == database_path.parent
    assert temporary_path != database_path
    assert final_path == database_path
    assert not temporary_path.exists()
    assert set(database_path.parent.iterdir()) == {database_path}

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        row_counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "database_metadata",
                "customers",
                "events",
                "evidence",
                "identity_edges",
            )
        }
        database_version = connection.execute(
            "SELECT schema_version, dataset_version, manifest_version FROM database_metadata"
        ).fetchone()
        event_types = {row[0]: row[1] for row in connection.execute("DESCRIBE events").fetchall()}
        evidence_types = {
            row[0]: row[1] for row in connection.execute("DESCRIBE evidence").fetchall()
        }
    finally:
        connection.close()

    assert row_counts == {
        "database_metadata": 1,
        "customers": 30,
        "events": 199,
        "evidence": 199,
        "identity_edges": 150,
    }
    assert database_version == (
        database.DATABASE_SCHEMA_VERSION,
        database.SYNTHETIC_DATASET_VERSION,
        SYNTHETIC_MANIFEST_VERSION,
    )
    assert event_types["occurred_at"] == "TIMESTAMP WITH TIME ZONE"
    assert event_types["identities"] == "JSON"
    assert event_types["attributes"] == "JSON"
    assert event_types["dimensions"] == "JSON"
    assert event_types["measures"] == "JSON"
    assert evidence_types["occurred_at"] == "TIMESTAMP WITH TIME ZONE"
    assert evidence_types["raw_fields"] == "JSON"


def test_seed_database_refuses_to_publish_over_destination_wal(tmp_path: Path) -> None:
    database_path = tmp_path / "destination-with-wal.duckdb"
    seed_database(database_path, generate_dataset(seed=20260819))
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import duckdb, os, sys; "
                "connection = duckdb.connect(sys.argv[1]); "
                "connection.execute('CREATE TABLE wal_marker (value INTEGER)'); "
                "connection.commit(); os._exit(0)"
            ),
            str(database_path),
        ],
        check=True,
    )
    wal_path = Path(f"{database_path}.wal")
    main_before = database_path.read_bytes()
    wal_before = wal_path.read_bytes()

    with pytest.raises(RuntimeError, match="WAL|checkpoint"):
        seed_database(database_path, generate_dataset(seed=20260820))

    assert database_path.read_bytes() == main_before
    assert wal_path.read_bytes() == wal_before
    assert list(tmp_path.glob(f".{database_path.name}.*.tmp")) == []


def test_seed_database_rolls_back_when_wal_appears_during_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wal_source_path = tmp_path / "wal-source.duckdb"
    database_path = tmp_path / "destination.duckdb"
    seed_database(wal_source_path, generate_dataset(seed=20260819))
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import duckdb, os, sys; "
                "connection = duckdb.connect(sys.argv[1]); "
                "connection.execute('CREATE TABLE old_generation (value INTEGER)'); "
                "connection.execute('INSERT INTO old_generation VALUES (19)'); "
                "connection.commit(); os._exit(0)"
            ),
            str(wal_source_path),
        ],
        check=True,
    )
    wal_source = Path(f"{wal_source_path}.wal")
    old_main = wal_source_path.read_bytes()
    old_wal = wal_source.read_bytes()
    database_path.write_bytes(old_main)
    destination_wal = Path(f"{database_path}.wal")
    real_replace = os.replace
    injected = False

    def inject_wal_before_publish(source: str | Path, destination: str | Path) -> None:
        nonlocal injected
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            not injected
            and source_path.suffix == ".tmp"
            and destination_path == database_path
        ):
            destination_wal.write_bytes(old_wal)
            injected = True
        real_replace(source_path, destination_path)

    monkeypatch.setattr(database.os, "replace", inject_wal_before_publish)

    with pytest.raises(RuntimeError, match="WAL|publish|checkpoint"):
        seed_database(database_path, generate_dataset(seed=20260820))

    assert injected is True
    assert database_path.read_bytes() == old_main
    assert destination_wal.read_bytes() == old_wal
    assert list(tmp_path.glob(f".{database_path.name}.*.tmp")) == []
    assert list(tmp_path.glob(f".{database_path.name}.backup-*")) == []
    assert not (tmp_path / f".{database_path.name}.publish.lock").exists()

    connection = duckdb.connect(str(database_path))
    try:
        assert connection.execute("SELECT * FROM old_generation").fetchall() == [(19,)]
    finally:
        connection.close()


@pytest.mark.parametrize("artifact_kind", ["backup", "lock"])
def test_seed_database_fails_closed_when_publication_recovery_artifacts_exist(
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    database_path = tmp_path / "destination.duckdb"
    seed_database(database_path, generate_dataset(seed=20260819))
    main_before = database_path.read_bytes()
    if artifact_kind == "backup":
        recovery_path = tmp_path / f".{database_path.name}.backup-interrupted"
        recovery_path.write_bytes(main_before)
    else:
        recovery_path = tmp_path / f".{database_path.name}.publish.lock"
        recovery_path.write_text("interrupted publication\n")

    with pytest.raises(RuntimeError, match="recovery|publication|publish"):
        seed_database(database_path, generate_dataset(seed=20260820))

    assert database_path.read_bytes() == main_before
    assert recovery_path.exists()
    if artifact_kind == "backup":
        assert recovery_path.read_bytes() == main_before
        assert not (tmp_path / f".{database_path.name}.publish.lock").exists()
    else:
        assert recovery_path.read_text() == "interrupted publication\n"
        assert list(tmp_path.glob(f".{database_path.name}.backup-*")) == []
    assert list(tmp_path.glob(f".{database_path.name}.*.tmp")) == []


def test_database_readiness_accepts_only_a_current_managed_database(tmp_path: Path) -> None:
    readiness = getattr(database, "is_database_ready", None)
    assert callable(readiness), "database readiness validation must be explicit"

    missing_path = tmp_path / "missing.duckdb"
    malformed_path = tmp_path / "malformed.duckdb"
    current_path = tmp_path / "current.duckdb"
    malformed_path.write_bytes(b"not-a-duckdb-file")
    seed_database(current_path, generate_dataset())

    assert readiness(missing_path) is False
    assert not missing_path.exists()
    assert readiness(malformed_path) is False
    assert malformed_path.read_bytes() == b"not-a-duckdb-file"
    assert readiness(current_path) is True


@pytest.mark.parametrize(
    "alter_statement",
    [
        "ALTER TABLE events ALTER COLUMN occurred_at SET DATA TYPE VARCHAR",
        "ALTER TABLE evidence ALTER COLUMN occurred_at SET DATA TYPE VARCHAR",
        "ALTER TABLE events ALTER COLUMN identities SET DATA TYPE VARCHAR",
        "ALTER TABLE events ALTER COLUMN attributes SET DATA TYPE VARCHAR",
        "ALTER TABLE events ALTER COLUMN dimensions SET DATA TYPE VARCHAR",
        "ALTER TABLE events ALTER COLUMN measures SET DATA TYPE VARCHAR",
        "ALTER TABLE evidence ALTER COLUMN raw_fields SET DATA TYPE VARCHAR",
        "ALTER TABLE identity_edges ALTER COLUMN confidence SET DATA TYPE VARCHAR",
    ],
)
def test_database_readiness_rejects_wrong_required_column_types(
    tmp_path: Path,
    alter_statement: str,
) -> None:
    database_path = tmp_path / "wrong-type.duckdb"
    seed_database(database_path, generate_dataset())
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(alter_statement)
    finally:
        connection.close()

    assert database.is_database_ready(database_path) is False


@pytest.mark.parametrize(
    "alter_statement",
    [
        "ALTER TABLE events DROP COLUMN dimensions",
        "ALTER TABLE events ALTER COLUMN measures SET DATA TYPE VARCHAR",
    ],
)
def test_seed_database_atomically_replaces_outdated_generic_event_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alter_statement: str,
) -> None:
    database_path = tmp_path / "outdated.duckdb"
    seed_database(database_path, generate_dataset())
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(alter_statement)
    finally:
        connection.close()
    assert database.is_database_ready(database_path) is False

    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        replacements.append((source_path, destination_path))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(database.os, "replace", recording_replace)

    seed_database(database_path, generate_dataset())

    assert len(replacements) == 1
    temporary_path, final_path = replacements[0]
    assert temporary_path.parent == database_path.parent
    assert final_path == database_path
    assert not temporary_path.exists()
    assert database.is_database_ready(database_path) is True

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        event_types = {row[0]: row[1] for row in connection.execute("DESCRIBE events").fetchall()}
    finally:
        connection.close()
    assert event_types["dimensions"] == "JSON"
    assert event_types["measures"] == "JSON"


def test_agent_database_contains_identity_provenance_but_not_evaluation_truth(
    database_path: Path,
    synthetic_dataset: SyntheticDataset,
):
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        identity_edge_count = (
            connection.execute("SELECT count(*) FROM identity_edges").fetchone()[0]
            if "identity_edges" in tables
            else 0
        )
        persisted_link_types = (
            {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT link_type FROM identity_edges"
                ).fetchall()
            }
            if "identity_edges" in tables
            else set()
        )
    finally:
        connection.close()

    assert "ground_truth" not in tables
    assert "identity_edges" in tables
    assert identity_edge_count == len(synthetic_dataset.identity_edges)
    assert persisted_link_types == {"EXACT", "DECLARED", "SYNTHETIC"}


def test_seed_database_cleans_temporary_file_and_preserves_destination_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_path = tmp_path / "customer-signal.duckdb"
    original_bytes = b"existing-database-placeholder"
    database_path.write_bytes(original_bytes)

    def fail_to_connect(*args, **kwargs):
        raise RuntimeError("simulated seed failure")

    monkeypatch.setattr(database.duckdb, "connect", fail_to_connect)

    with pytest.raises(RuntimeError, match="simulated seed failure"):
        seed_database(database_path, generate_dataset())

    assert database_path.read_bytes() == original_bytes
    assert set(tmp_path.iterdir()) == {database_path}


def test_repository_round_trips_canonical_events_and_evidence(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
):
    for source_id in ALL_SOURCES:
        assert repository.list_events(
            start_at=START_AT,
            end_at=END_AT,
            enabled_sources=[source_id],
        ) == [event for event in synthetic_dataset.events if event.source_id == source_id]

    requested = list(reversed(synthetic_dataset.evidence))
    assert repository.get_evidence([record.evidence_id for record in requested]) == requested
    assert all(isinstance(event, CustomerEvent) for event in synthetic_dataset.events)
    assert all(
        isinstance(record, EvidenceRecord)
        for record in repository.get_evidence([requested[0].evidence_id])
    )


def test_catalog_sources_reports_actual_time_ranges_and_counts(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
):
    catalog = repository.catalog_sources(start_at=START_AT, end_at=END_AT)

    assert [entry.source_id for entry in catalog] == ALL_SOURCES
    for entry in catalog:
        expected = [
            event for event in synthetic_dataset.events if event.source_id == entry.source_id
        ]
        assert entry.row_count == len(expected)
        assert entry.start_at == min(event.occurred_at for event in expected)
        assert entry.end_at == max(event.occurred_at for event in expected)


def test_list_events_applies_half_open_time_source_customer_filters_and_limit(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
):
    start_at = synthetic_dataset.events[20].occurred_at
    end_at = synthetic_dataset.events[70].occurred_at
    enabled_sources = ["voc", "search_history"]
    expected = [
        event
        for event in synthetic_dataset.events
        if start_at <= event.occurred_at < end_at and event.source_id in enabled_sources
    ]

    actual = repository.list_events(
        start_at=start_at,
        end_at=end_at,
        enabled_sources=enabled_sources,
        limit=100,
    )

    assert actual == expected
    assert actual == sorted(actual, key=lambda event: (event.occurred_at, event.event_id))
    assert repository.list_events(
        start_at=START_AT,
        end_at=END_AT,
        enabled_sources=ALL_SOURCES,
        customer_id="CUST-003",
    ) == [event for event in synthetic_dataset.events if event.canonical_customer_id == "CUST-003"]
    assert (
        repository.list_events(
            start_at=START_AT,
            end_at=END_AT,
            enabled_sources=ALL_SOURCES,
            limit=7,
        )
        == synthetic_dataset.events[:7]
    )


def test_list_identity_edges_uses_the_same_ordered_limited_event_selection(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    selected_events = repository.list_events(
        start_at=START_AT,
        end_at=END_AT,
        enabled_sources=["search_history"],
        limit=1,
    )

    edges = repository.list_identity_edges(
        start_at=START_AT,
        end_at=END_AT,
        enabled_sources=["search_history"],
        limit=1,
    )

    assert edges == _connected_edges(selected_events, synthetic_dataset.identity_edges)
    assert [_edge_key(edge) for edge in edges] == sorted(_edge_key(edge) for edge in edges)


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_list_events_rejects_limit_outside_integer_range(
    repository: DuckDBRepository,
    limit,
):
    with pytest.raises(ValueError, match="limit must be an integer between 1 and 100"):
        repository.list_events(
            start_at=START_AT,
            end_at=END_AT,
            enabled_sources=ALL_SOURCES,
            limit=limit,
        )


@pytest.mark.parametrize(
    "enabled_sources",
    [[], ["voc", "voc"], ["unknown"], "voc"],
)
def test_list_events_rejects_empty_duplicate_or_unknown_sources(
    repository: DuckDBRepository,
    enabled_sources,
):
    with pytest.raises(ValueError, match="enabled_sources"):
        repository.list_events(
            start_at=START_AT,
            end_at=END_AT,
            enabled_sources=enabled_sources,
        )


@pytest.mark.parametrize(
    ("start_at", "end_at"),
    [
        (datetime(2026, 7, 20), END_AT),
        (START_AT, datetime(2026, 8, 19)),
        (END_AT, END_AT),
        (END_AT, START_AT),
    ],
)
def test_repository_rejects_naive_or_non_increasing_time_ranges(
    repository: DuckDBRepository,
    start_at: datetime,
    end_at: datetime,
):
    with pytest.raises(ValueError, match="timezone-aware and start_at must be before end_at"):
        repository.catalog_sources(start_at=start_at, end_at=end_at)
    with pytest.raises(ValueError, match="timezone-aware and start_at must be before end_at"):
        repository.list_events(
            start_at=start_at,
            end_at=end_at,
            enabled_sources=ALL_SOURCES,
        )


def test_repository_raises_typed_error_for_missing_database(tmp_path: Path):
    repository = DuckDBRepository(tmp_path / "missing.duckdb")

    with pytest.raises(DatabaseNotFoundError, match="missing.duckdb"):
        repository.catalog_sources(start_at=START_AT, end_at=END_AT)
    with pytest.raises(DatabaseNotFoundError, match="missing.duckdb"):
        repository.list_events(
            start_at=START_AT,
            end_at=END_AT,
            enabled_sources=ALL_SOURCES,
        )
    with pytest.raises(DatabaseNotFoundError, match="missing.duckdb"):
        repository.get_evidence(["EVD-unknown"])


def test_repository_raises_typed_error_for_missing_customer_or_evidence(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
):
    with pytest.raises(EntityNotFoundError, match="customer.*CUST-999"):
        repository.list_events(
            start_at=START_AT,
            end_at=END_AT,
            enabled_sources=ALL_SOURCES,
            customer_id="CUST-999",
        )
    with pytest.raises(EntityNotFoundError, match="evidence.*EVD-unknown"):
        repository.get_evidence([synthetic_dataset.evidence[0].evidence_id, "EVD-unknown"])


@pytest.mark.parametrize("evidence_ids", [[], "EVD-unknown"])
def test_get_evidence_rejects_empty_or_non_sequence_ids(
    repository: DuckDBRepository,
    evidence_ids,
):
    with pytest.raises(ValueError, match="evidence_ids"):
        repository.get_evidence(evidence_ids)


def test_get_evidence_preserves_duplicate_requested_ids(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
):
    first, second = synthetic_dataset.evidence[:2]
    requested_ids = [first.evidence_id, second.evidence_id, first.evidence_id, first.evidence_id]

    assert repository.get_evidence(requested_ids) == [first, second, first, first]


def test_repository_returns_only_masked_evidence(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
):
    records = repository.get_evidence([record.evidence_id for record in synthetic_dataset.evidence])
    payload = json.dumps(
        [record.model_dump(mode="json") for record in records],
        ensure_ascii=False,
    )

    assert all("***" in record.masked_customer_id for record in records)
    assert all(customer_id not in payload for customer_id in synthetic_dataset.customers)


def test_each_repository_operation_uses_fresh_closed_read_only_connection(
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
    monkeypatch: pytest.MonkeyPatch,
):
    connections = []
    real_connect = duckdb.connect

    def recording_connect(path, *, read_only=False):
        assert read_only is True
        connection = real_connect(path, read_only=read_only)
        connections.append(connection)
        return connection

    def reject_global_sql(*args, **kwargs):
        raise AssertionError("global duckdb.sql must not be used")

    monkeypatch.setattr(repository_module.duckdb, "connect", recording_connect)
    monkeypatch.setattr(repository_module.duckdb, "sql", reject_global_sql)

    repository.catalog_sources(start_at=START_AT, end_at=END_AT)
    repository.list_events(
        start_at=START_AT,
        end_at=END_AT,
        enabled_sources=ALL_SOURCES,
        limit=1,
    )
    repository.get_evidence([synthetic_dataset.evidence[0].evidence_id])

    assert len(connections) == 3
    assert len({id(connection) for connection in connections}) == 3
    for connection in connections:
        with pytest.raises(duckdb.Error, match="closed"):
            connection.execute("CREATE TABLE forbidden (value INTEGER)")


def test_repository_has_no_public_raw_sql_write_or_ground_truth_api(
    repository: DuckDBRepository,
):
    public_methods = {
        name
        for name, member in inspect.getmembers(DuckDBRepository, inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {
        "catalog_sources",
        "get_evidence",
        "list_event_page",
        "list_events",
        "list_identity_edges",
        "list_identity_page",
        "snapshot_token",
    }
    assert set(vars(repository)) == {"_path"}


def test_snapshot_token_includes_committed_wal_without_checkpointing(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "wal-snapshot.duckdb"
    connection = duckdb.connect(str(database_path))
    connection.execute("CREATE TABLE marker (value INTEGER)")
    connection.execute("INSERT INTO marker VALUES (1)")
    connection.close()
    repository = DuckDBRepository(database_path)
    main_digest = sha256(database_path.read_bytes()).hexdigest()
    before = repository.snapshot_token()

    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import duckdb, os, sys; "
                "connection = duckdb.connect(sys.argv[1]); "
                "connection.execute('INSERT INTO marker VALUES (2)'); "
                "connection.commit(); os._exit(0)"
            ),
            str(database_path),
        ],
        check=True,
    )
    wal_path = Path(f"{database_path}.wal")

    assert wal_path.is_file()
    assert sha256(database_path.read_bytes()).hexdigest() == main_digest
    after = repository.snapshot_token()
    assert after != before

    read_only = duckdb.connect(str(database_path), read_only=True)
    try:
        assert read_only.execute("SELECT count(*) FROM marker").fetchone() == (2,)
    finally:
        read_only.close()
    assert repository.snapshot_token() == after
    assert wal_path.is_file()


def test_snapshot_token_is_deterministic_without_wal_or_content_changes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "stable-snapshot.duckdb"
    connection = duckdb.connect(str(database_path))
    connection.execute("CREATE TABLE marker (value INTEGER)")
    connection.execute("INSERT INTO marker VALUES (1)")
    connection.close()
    repository = DuckDBRepository(database_path)

    assert not Path(f"{database_path}.wal").exists()
    token = repository.snapshot_token()
    assert repository.snapshot_token() == token

    os.utime(database_path, None)

    assert repository.snapshot_token() == token


def test_snapshot_token_retries_one_stat_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "one-race.duckdb"
    database_path.write_bytes(b"stable database content")
    repository = DuckDBRepository(database_path)
    real_stat = DuckDBRepository._snapshot_file_stat
    calls = 0

    def race_once(path: Path):
        nonlocal calls
        calls += 1
        state = real_stat(path)
        if calls == 3 and state is not None:
            return (*state[:-1], state[-1] + 1)
        return state

    monkeypatch.setattr(repository, "_snapshot_file_stat", race_once)

    assert repository.snapshot_token()
    assert calls == 8


def test_snapshot_token_retries_a_transient_main_file_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "transient-gap.duckdb"
    database_path.write_bytes(b"stable database content")
    repository = DuckDBRepository(database_path)
    real_stat = DuckDBRepository._snapshot_file_stat
    calls = 0

    def missing_once(path: Path):
        nonlocal calls
        calls += 1
        if calls == 1 and path == database_path:
            return None
        return real_stat(path)

    monkeypatch.setattr(repository, "_snapshot_file_stat", missing_once)

    assert repository.snapshot_token()
    assert calls == 6


def test_snapshot_token_fails_closed_after_repeated_stat_races(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "repeated-race.duckdb"
    database_path.write_bytes(b"changing database content")
    repository = DuckDBRepository(database_path)
    real_stat = DuckDBRepository._snapshot_file_stat
    database_stat_calls = 0

    def always_racing(path: Path):
        nonlocal database_stat_calls
        state = real_stat(path)
        if path == database_path and state is not None:
            database_stat_calls += 1
            return (*state[:-1], state[-1] + database_stat_calls)
        return state

    monkeypatch.setattr(repository, "_snapshot_file_stat", always_racing)

    with pytest.raises(RuntimeError, match="changed while computing snapshot token"):
        repository.snapshot_token()
    assert database_stat_calls == 6


def test_database_cli_requires_explicit_path_and_seeds_requested_file(tmp_path: Path):
    project_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root / "src")
    database_path = tmp_path / "explicit" / "seeded.duckdb"

    seeded = subprocess.run(
        [
            sys.executable,
            "-m",
            "customer_signal.data.cli",
            "--database",
            str(database_path),
            "--seed",
            "20260819",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert seeded.returncode == 0, seeded.stderr
    assert database_path.is_file()

    missing_path = subprocess.run(
        [sys.executable, "-m", "customer_signal.data.cli", "--seed", "20260819"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_path.returncode != 0
    assert "--database" in missing_path.stderr
    assert sorted(tmp_path.rglob("*.duckdb")) == [database_path]


def test_database_cli_requires_explicit_seed(tmp_path: Path):
    project_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root / "src")
    database_path = tmp_path / "must-not-be-created.duckdb"

    missing_seed = subprocess.run(
        [
            sys.executable,
            "-m",
            "customer_signal.data.cli",
            "--database",
            str(database_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert missing_seed.returncode != 0
    assert "--seed" in missing_seed.stderr
    assert not database_path.exists()
