"""SQLite registry with atomic user registration and immutable measurement history."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import timezone
from threading import RLock
from uuid import uuid4

from customer_signal.signals.contracts import (
    Measurement,
    Proposal,
    Signal,
    SignalDefinition,
    SignalStatus,
)
from customer_signal.signals.measurement import definition_fingerprint


def _measurement_json(measurement: Measurement) -> str:
    value = measurement.model_dump(mode="json")
    value.update(
        cohort_customer_ids=measurement.cohort_customer_ids, query_results=measurement.query_results
    )
    return json.dumps(value, ensure_ascii=False, default=str)


def _proposal_json(proposal: Proposal) -> str:
    value = proposal.model_dump(mode="json")
    value["measurement"] = json.loads(_measurement_json(proposal.measurement))
    return json.dumps(value, ensure_ascii=False)


class SignalStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            self._migrate_nullable_proposal(db)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS signal_proposals (
                    proposal_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    proposal_id TEXT REFERENCES signal_proposals(proposal_id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signal_registrations (
                    proposal_id TEXT PRIMARY KEY REFERENCES signal_proposals(proposal_id),
                    signal_id TEXT NOT NULL REFERENCES signals(signal_id)
                );
                CREATE TABLE IF NOT EXISTS signal_measurements (
                    measurement_id TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL REFERENCES signals(signal_id),
                    fingerprint TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(signal_id, fingerprint, start_at, end_at, snapshot_id, status)
                );
                CREATE INDEX IF NOT EXISTS proposals_by_run ON signal_proposals(run_id);
                CREATE INDEX IF NOT EXISTS measurements_by_signal ON signal_measurements(signal_id);
            """)

    @staticmethod
    def _migrate_nullable_proposal(db):
        columns = db.execute("PRAGMA table_info(signals)").fetchall()
        if not any(column[1] == "proposal_id" and column[3] for column in columns):
            return
        # SQLite cannot alter nullability. Rebuild only this table in one transaction,
        # preserving IDs and all referring rows. Disable FKs before BEGIN, then check
        # them before commit so a failed migration rolls back the original table.
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE signals_nullable (
                signal_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                proposal_id TEXT REFERENCES signal_proposals(proposal_id), payload TEXT NOT NULL
            )""")
            db.execute("INSERT INTO signals_nullable SELECT * FROM signals")
            db.execute("DROP TABLE signals")
            db.execute("ALTER TABLE signals_nullable RENAME TO signals")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("signal schema migration failed foreign key validation")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def _connection(self):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=30)
            db.execute("PRAGMA foreign_keys=ON")
            try:
                with db:
                    yield db
            finally:
                db.close()

    @staticmethod
    def _read(db, table, key, value, contract):
        # table and key only come from constants in this module.
        row = db.execute(f"SELECT payload FROM {table} WHERE {key}=?", (value,)).fetchone()
        if row is None:
            raise KeyError(value)
        return contract.model_validate_json(row[0])

    def save_proposal(self, proposal: Proposal) -> Proposal:
        measurement = proposal.measurement
        if (
            measurement.status != "success"
            or measurement.definition_fingerprint != definition_fingerprint(proposal.definition)
            or set(measurement.source_ids) != set(proposal.definition.source_ids)
        ):
            raise ValueError("proposal requires a successful measurement of its exact definition")
        with self._connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO signal_proposals VALUES (?, ?, ?)",
                (proposal.proposal_id, proposal.run_id, _proposal_json(proposal)),
            )
            saved = self._read(
                db, "signal_proposals", "proposal_id", proposal.proposal_id, Proposal
            )
            if _proposal_json(saved) != _proposal_json(proposal):
                raise ValueError("proposal_id already exists with different content")
            return saved

    def list_proposals(self, run_id: str | None = None) -> list[Proposal]:
        with self._connection() as db:
            return [
                Proposal.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT payload FROM signal_proposals "
                    + ("WHERE run_id=? " if run_id is not None else "")
                    + "ORDER BY rowid",
                    (run_id,) if run_id is not None else (),
                )
            ]

    def get_proposal(self, proposal_id: str) -> Proposal:
        with self._connection() as db:
            return self._read(db, "signal_proposals", "proposal_id", proposal_id, Proposal)

    def register(self, proposal_id: str) -> Signal:
        return self.register_with_measurement(proposal_id)[0]

    def register_with_measurement(self, proposal_id: str) -> tuple[Signal, Measurement]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            proposal = self._read(db, "signal_proposals", "proposal_id", proposal_id, Proposal)
            fingerprint = definition_fingerprint(proposal.definition)
            existing = db.execute(
                "SELECT payload FROM signals WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if existing:
                signal = Signal.model_validate_json(existing[0])
            else:
                signal = Signal(
                    signal_id="signal-" + uuid4().hex,
                    title=proposal.title,
                    description=proposal.description,
                    definition=proposal.definition,
                    proposal_id=proposal_id,
                )
                db.execute(
                    "INSERT INTO signals VALUES (?, ?, ?, ?)",
                    (signal.signal_id, fingerprint, proposal_id, signal.model_dump_json()),
                )
            db.execute(
                "INSERT OR IGNORE INTO signal_registrations VALUES (?, ?)",
                (proposal_id, signal.signal_id),
            )
            persisted = self._insert_measurement(db, signal.signal_id, proposal.measurement)
            return signal, persisted

    def register_definition(
        self,
        *,
        title: str,
        description: str,
        definition: SignalDefinition,
        measurement: Measurement,
    ) -> Signal:
        return self.register_definition_with_measurement(
            title=title,
            description=description,
            definition=definition,
            measurement=measurement,
        )[0]

    def register_definition_with_measurement(
        self,
        *,
        title: str,
        description: str,
        definition: SignalDefinition,
        measurement: Measurement,
    ) -> tuple[Signal, Measurement]:
        fingerprint = definition_fingerprint(definition)
        if (
            measurement.status != "success"
            or measurement.definition_fingerprint != fingerprint
            or set(measurement.source_ids) != set(definition.source_ids)
        ):
            raise ValueError(
                "direct registration requires a successful exact-definition measurement"
            )
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload FROM signals WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if existing:
                signal = Signal.model_validate_json(existing[0])
            else:
                signal = Signal(
                    signal_id="signal-" + uuid4().hex,
                    title=title,
                    description=description,
                    definition=definition,
                    proposal_id=None,
                    origin="user_defined",
                )
                db.execute(
                    "INSERT INTO signals VALUES (?, ?, ?, ?)",
                    (signal.signal_id, fingerprint, None, signal.model_dump_json()),
                )
            persisted = self._insert_measurement(db, signal.signal_id, measurement)
            return signal, persisted

    def list_signals(self) -> list[Signal]:
        with self._connection() as db:
            return [
                Signal.model_validate_json(row[0])
                for row in db.execute("SELECT payload FROM signals ORDER BY rowid")
            ]

    def get_signal(self, signal_id: str) -> Signal:
        with self._connection() as db:
            return self._read(db, "signals", "signal_id", signal_id, Signal)

    def set_status(self, signal_id: str, status: SignalStatus) -> Signal:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            signal = self._read(db, "signals", "signal_id", signal_id, Signal)
            updated = Signal.model_validate({**signal.model_dump(), "status": status})
            db.execute(
                "UPDATE signals SET payload=? WHERE signal_id=?",
                (updated.model_dump_json(), signal_id),
            )
            return updated

    @staticmethod
    def _insert_measurement(db, signal_id: str, measurement: Measurement) -> Measurement:
        signature = (
            signal_id,
            measurement.definition_fingerprint,
            measurement.start_at.astimezone(timezone.utc).isoformat(),
            measurement.end_at.astimezone(timezone.utc).isoformat(),
            measurement.snapshot_id,
            measurement.status,
        )
        db.execute(
            "INSERT OR IGNORE INTO signal_measurements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (measurement.measurement_id, *signature, _measurement_json(measurement)),
        )
        row = db.execute(
            """SELECT payload FROM signal_measurements WHERE
            signal_id=? AND fingerprint=? AND start_at=? AND end_at=? AND snapshot_id=? AND status=?""",
            signature,
        ).fetchone()
        if row is None:
            raise ValueError("measurement_id already belongs to a different measurement")
        return Measurement.model_validate_json(row[0])

    def add_measurement(self, signal_id: str, measurement: Measurement) -> Measurement:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            signal = self._read(db, "signals", "signal_id", signal_id, Signal)
            if definition_fingerprint(
                signal.definition
            ) != measurement.definition_fingerprint or set(signal.definition.source_ids) != set(
                measurement.source_ids
            ):
                raise ValueError("measurement does not match the registered definition")
            return self._insert_measurement(db, signal_id, measurement)

    def list_measurements(self, signal_id: str) -> list[Measurement]:
        with self._connection() as db:
            self._read(db, "signals", "signal_id", signal_id, Signal)
            return [
                Measurement.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT payload FROM signal_measurements WHERE signal_id=? ORDER BY rowid",
                    (signal_id,),
                )
            ]
