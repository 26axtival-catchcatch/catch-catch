import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from customer_signal.signals.scheduling import (
    DailyScheduler,
    ScheduleBusy,
    ScheduleStore,
    next_midnight,
)
from customer_signal.signals.service import SignalService
from customer_signal.signals.store import SignalStore
from test_signals import definition, make_data
from customer_signal.signals.measurement import measure_definition

UTC = timezone.utc
END = datetime(2026, 9, 2, 15, tzinfo=UTC)  # September 3 KST midnight


@pytest.fixture
def setup(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")
    data = make_data()
    try:
        signal = store.register_definition(
            title="daily",
            description="daily",
            definition=definition(),
            measurement=measure_definition(data, definition()),
        )
    finally:
        data.close()
    schedules = ScheduleStore(store)
    schedules.update(signal.signal_id, enabled=True, next_run_at=END)

    def load(request):
        from customer_signal.investigation.data import InvestigationData

        # Use real canonical events for the requested KST window.
        from customer_signal.domain.models import CustomerEvent

        rows = [
            CustomerEvent(
                event_id=f"e-{i}",
                evidence_id=f"ev-{i}",
                source_id="app",
                occurred_at=request.start_at + timedelta(hours=1),
                event_type="menu_view",
                action=action,
                topic="settings",
                outcome="unknown",
                text="",
                canonical_customer_id=customer,
            )
            for i, (customer, action) in enumerate([("a", "close"), ("b", "done")])
        ]
        return InvestigationData(
            request=request, events=rows, manifests=[], snapshot_id="live-test"
        )

    service = SignalService(store=store, load_data=load)
    return store, schedules, signal, service


def test_korean_midnight_is_strictly_next():
    assert next_midnight(END) == END + timedelta(days=1)
    assert next_midnight(END - timedelta(seconds=1)) == END


def test_registration_and_legacy_migration_have_persistent_schedule(setup):
    store, schedules, signal, _ = setup
    assert schedules.get(signal.signal_id).next_run_at == END
    with store._connection() as db:
        db.execute("DELETE FROM signal_schedules")
    reopened = SignalStore(store.path)
    restored = ScheduleStore(reopened).get(signal.signal_id)
    assert restored.enabled and restored.timezone == "Asia/Seoul"
    assert restored.next_run_at > datetime.now(UTC)
    assert len(reopened.list_measurements(signal.signal_id)) == 1


def test_due_windows_catch_up_and_restart_without_duplicate(setup):
    store, schedules, signal, service = setup
    worker = DailyScheduler(schedules, service)
    assert worker.tick(END - timedelta(seconds=1)) == 0
    assert worker.tick(END + timedelta(days=1)) == 1
    assert worker.tick(END + timedelta(days=1)) == 1
    reopened = SignalStore(store.path)
    assert DailyScheduler(ScheduleStore(reopened), service).tick(END + timedelta(days=1)) == 0
    jobs = schedules.results(signal.signal_id)
    assert len(jobs.items) == 2
    assert [j.end_at for j in jobs.items] == [END + timedelta(days=1), END]
    assert all(j.status == "success" and j.measurement for j in jobs.items)
    assert jobs.items[1].start_at == END - timedelta(days=1)
    assert len(store.list_measurements(signal.signal_id)) == 3


def test_paused_disabled_and_archived_resume_without_losing_cursor(setup):
    store, schedules, signal, service = setup
    worker = DailyScheduler(schedules, service)
    for status in ["paused", "archived"]:
        store.set_status(signal.signal_id, status)
        assert worker.tick(END) == 0
    store.set_status(signal.signal_id, "active")
    schedules.update(signal.signal_id, enabled=False)
    assert worker.tick(END) == 0
    schedules.update(signal.signal_id, enabled=True)
    assert worker.tick(END) == 1


def test_measurement_failure_is_recorded_and_next_day_runs(setup):
    store, schedules, signal, service = setup
    good = service.load_data
    service.load_data = lambda r: (_ for _ in ()).throw(RuntimeError("secret provider error"))
    worker = DailyScheduler(schedules, service)
    assert worker.tick(END) == 1
    result = schedules.results(signal.signal_id).items[0]
    assert result.status == "unavailable"
    assert all(v.value is None for v in result.measurement.values)
    assert "secret" not in result.model_dump_json()
    service.load_data = good
    assert worker.tick(END + timedelta(days=1)) == 1
    assert schedules.results(signal.signal_id).items[0].status == "success"


def test_two_workers_and_schedule_mutation_cannot_race(setup):
    store, schedules, signal, service = setup
    entered, release = Event(), Event()
    measure = service.measure

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return measure(*args, **kwargs)

    service.measure = slow
    with ThreadPoolExecutor() as pool:
        future = pool.submit(DailyScheduler(schedules, service).tick, END)
        assert entered.wait(5)
        try:
            other = ScheduleStore(SignalStore(store.path))
            assert DailyScheduler(other, service).tick(END) == 0
            with pytest.raises(ScheduleBusy):
                other.update(signal.signal_id, enabled=False)
        finally:
            release.set()
        assert future.result() == 1
    assert len(schedules.results(signal.signal_id).items) == 1


def test_crash_after_measurement_reuses_job_and_measurement(setup, monkeypatch):
    store, schedules, signal, service = setup
    worker = DailyScheduler(schedules, service)
    finish = schedules.finish

    def crash(*args):
        raise RuntimeError("simulated process crash")

    monkeypatch.setattr(schedules, "finish", crash)
    worker.tick(END)
    interrupted = schedules.results(signal.signal_id).items[0]
    assert interrupted.status == "running"
    count = len(store.list_measurements(signal.signal_id))
    monkeypatch.setattr(schedules, "finish", finish)
    assert worker.tick(END) == 1
    completed = schedules.results(signal.signal_id).items[0]
    assert completed.execution_id == interrupted.execution_id
    assert completed.status == "success"
    assert len(store.list_measurements(signal.signal_id)) == count


@pytest.mark.asyncio
async def test_background_loop_runs_immediately_and_stops(setup):
    _, schedules, signal, service = setup
    worker = DailyScheduler(schedules, service, poll_seconds=0.01, clock=lambda: END)
    task = asyncio.create_task(worker.run())
    for _ in range(200):
        if schedules.results(signal.signal_id).items:
            break
        await asyncio.sleep(0.01)
    worker.stop()
    await asyncio.wait_for(task, 5)
    assert schedules.results(signal.signal_id).items[0].status == "success"


def test_pipeline_revision_persists_new_measurement_for_same_data(setup, monkeypatch):
    from customer_signal.signals import measurement as module

    store, schedules, signal, service = setup
    first = service.measure(signal, start_at=END - timedelta(days=1), end_at=END)
    monkeypatch.setattr(module, "PIPELINE_VERSION", "signal-sql-v2")
    second = service.measure(signal, start_at=END - timedelta(days=1), end_at=END)
    assert first.pipeline_version == "signal-sql-v1"
    assert second.pipeline_version == "signal-sql-v2"
    assert second.measurement_id != first.measurement_id
    assert second.snapshot_id != first.snapshot_id


def test_process_death_releases_lock_and_recovers_running_job(setup):
    import subprocess
    import sys

    store, schedules, signal, service = setup
    code = """
import os, sys
from datetime import datetime
from pathlib import Path
from customer_signal.signals.store import SignalStore
from customer_signal.signals.scheduling import ScheduleStore
schedules = ScheduleStore(SignalStore(Path(sys.argv[1])))
with schedules.lock(sys.argv[2]):
    schedules.start(sys.argv[2], datetime.fromisoformat(sys.argv[3]))
    os._exit(7)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", code, str(store.path), signal.signal_id, END.isoformat()],
        capture_output=True,
        timeout=10,
    )
    assert crashed.returncode == 7
    before = schedules.results(signal.signal_id).items[0]
    assert before.status == "running"
    assert DailyScheduler(schedules, service).tick(END) == 1
    after = schedules.results(signal.signal_id).items[0]
    assert after.status == "success" and after.execution_id == before.execution_id


def test_v1_snapshot_remains_compatible_with_existing_measurements():
    from customer_signal.signals import measurement as module

    payload = {"source_ids": ["app"], "missing": True}
    assert module._snapshot_fingerprint(payload) == module._fingerprint(payload)
