"""Persistent daily work on the existing measurement pipeline, for a local SQLite deployment."""

from __future__ import annotations

import asyncio
import fcntl
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from customer_signal.signals.contracts import Measurement, now
from customer_signal.signals.schedule_contracts import (
    DAY,
    DailyResult,
    DailyResults,
    DailySchedule,
    ScheduleUpdate,
    next_midnight,
)

logger = logging.getLogger(__name__)


class ScheduleBusy(Exception):
    """An execution owns this signal's schedule until its measurement is committed."""


def initialize_schedules(db, at: datetime) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS signal_schedules (
            signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id),
            enabled INTEGER NOT NULL, next_run_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_daily_runs (
            execution_id TEXT PRIMARY KEY,
            signal_id TEXT NOT NULL REFERENCES signals(signal_id),
            start_at TEXT NOT NULL, end_at TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
            measurement_id TEXT REFERENCES signal_measurements(measurement_id),
            UNIQUE(signal_id, end_at)
        );
        CREATE INDEX IF NOT EXISTS daily_runs_by_signal
            ON signal_daily_runs(signal_id, end_at);
    """)
    db.execute(
        "INSERT OR IGNORE INTO signal_schedules SELECT signal_id, 1, ?, ? FROM signals",
        (next_midnight(at).isoformat(), at.isoformat()),
    )


def ensure_schedule(db, signal_id: str) -> None:
    at = now()
    db.execute(
        "INSERT OR IGNORE INTO signal_schedules VALUES (?, 1, ?, ?)",
        (signal_id, next_midnight(at).isoformat(), at.isoformat()),
    )


class ScheduleStore:
    def __init__(self, store):
        self.store = store
        self.lock_directory = store.path.resolve().parent / (store.path.name + ".locks")
        self.lock_directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self, signal_id):
        # flock is released by the OS on process death; never unlink a lock inode.
        # Hash the ID so paths are safe even for legacy/user-generated identifiers.
        path = self.lock_directory / (sha256(signal_id.encode()).hexdigest() + ".lock")
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ScheduleBusy from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def get(self, signal_id: str) -> DailySchedule:
        signal = self.store.get_signal(signal_id)
        with self.store._connection() as db:
            row = db.execute(
                "SELECT enabled, next_run_at, updated_at FROM signal_schedules WHERE signal_id=?",
                (signal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(signal_id)
        return DailySchedule(
            signal_id=signal_id,
            enabled=bool(row[0]),
            next_run_at=row[1],
            updated_at=row[2],
            signal_status=signal.status,
        )

    def update(self, signal_id: str, *, enabled: bool, next_run_at=None) -> DailySchedule:
        request = ScheduleUpdate(enabled=enabled, next_run_at=next_run_at)
        with self.lock(signal_id):
            current = self.get(signal_id)
            with self.store._connection() as db:
                db.execute(
                    "UPDATE signal_schedules SET enabled=?, next_run_at=?, updated_at=? "
                    "WHERE signal_id=?",
                    (
                        request.enabled,
                        (request.next_run_at or current.next_run_at).isoformat(),
                        now().isoformat(),
                        signal_id,
                    ),
                )
            return self.get(signal_id)

    def due(self, at: datetime) -> list[str]:
        with self.store._connection() as db:
            return [
                row[0]
                for row in db.execute(
                    "SELECT signal_id FROM signal_schedules WHERE enabled=1 AND next_run_at<=? "
                    "ORDER BY next_run_at, signal_id",
                    (at.astimezone(timezone.utc).isoformat(),),
                )
            ]

    def start(self, signal_id: str, end_at: datetime) -> str:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO signal_daily_runs VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
                (
                    str(uuid4()),
                    signal_id,
                    (end_at - DAY).isoformat(),
                    end_at.isoformat(),
                    "running",
                    now().isoformat(),
                ),
            )
            return db.execute(
                "SELECT execution_id FROM signal_daily_runs WHERE signal_id=? AND end_at=?",
                (signal_id, end_at.isoformat()),
            ).fetchone()[0]

    def finish(self, execution_id: str, measurement: Measurement) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            signal_id, end = db.execute(
                "SELECT signal_id, end_at FROM signal_daily_runs WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            db.execute(
                "UPDATE signal_daily_runs SET status=?, completed_at=?, measurement_id=? "
                "WHERE execution_id=?",
                (measurement.status, now().isoformat(), measurement.measurement_id, execution_id),
            )
            db.execute(
                "UPDATE signal_schedules SET next_run_at=?, updated_at=? WHERE signal_id=?",
                ((datetime.fromisoformat(end) + DAY).isoformat(), now().isoformat(), signal_id),
            )

    def results(self, signal_id: str, *, limit=30, before=None, at=None) -> DailyResults:
        schedule = self.get(signal_id)
        at = at or now()
        with self.store._connection() as db:
            rows = db.execute(
                "SELECT execution_id, start_at, end_at, status, started_at, completed_at, "
                "measurement_id FROM signal_daily_runs WHERE signal_id=? "
                + ("AND end_at<? " if before else "")
                + "ORDER BY end_at DESC LIMIT ?",
                (
                    signal_id,
                    *([before.astimezone(timezone.utc).isoformat()] if before else []),
                    limit + 1,
                ),
            ).fetchall()
            items = []
            for execution, start, end, status, started, completed, measurement_id in rows[:limit]:
                measurement = None
                if measurement_id:
                    # A manual retry can recover a failed day or supersede its data snapshot.
                    saved = db.execute(
                        "SELECT payload FROM signal_measurements WHERE signal_id=? "
                        "AND start_at=? AND end_at=? ORDER BY (status='success') DESC, rowid DESC "
                        "LIMIT 1",
                        (signal_id, start, end),
                    ).fetchone()
                    if saved:
                        measurement = Measurement.model_validate_json(saved[0])
                items.append(
                    DailyResult(
                        execution_id=execution,
                        signal_id=signal_id,
                        start_at=start,
                        end_at=end,
                        status=status,
                        started_at=started,
                        completed_at=completed,
                        measurement=measurement,
                    )
                )
        return DailyResults(
            items=items,
            next_before=items[-1].end_at if len(rows) > limit else None,
            pending_days=max(0, int((at - schedule.next_run_at) // DAY) + 1),
        )


class DailyScheduler:
    def __init__(self, schedules: ScheduleStore, service, *, poll_seconds=60, clock=now):
        self.schedules, self.service = schedules, service
        self.poll_seconds, self.clock = poll_seconds, clock
        self._stop = asyncio.Event()

    def tick(self, at: datetime | None = None) -> int:
        at = at or self.clock()
        completed = 0
        for signal_id in self.schedules.due(at):
            try:
                with self.schedules.lock(signal_id):
                    schedule = self.schedules.get(signal_id)
                    if (
                        not schedule.enabled
                        or schedule.signal_status != "active"
                        or schedule.next_run_at > at
                    ):
                        continue
                    end = schedule.next_run_at
                    execution_id = self.schedules.start(signal_id, end)
                    signal = self.schedules.store.get_signal(signal_id)
                    measurement = self.service.measure(
                        signal,
                        start_at=end - DAY,
                        end_at=end,
                        trace_run_id=execution_id,
                    )
                    self.schedules.finish(execution_id, measurement)
                    completed += 1
            except ScheduleBusy:
                continue
            except Exception:
                # Raw provider errors can contain credentials. Keep the persistent running
                # row for crash recovery and report only the public operation identity.
                logger.error("Daily signal execution will retry: %s", signal_id)
        return completed

    async def run(self):
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                logger.error("Daily signal scheduler tick failed; retrying on next poll")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    def stop(self):
        self._stop.set()
