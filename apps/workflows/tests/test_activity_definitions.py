"""A cancelled synchronous activity runs to its end; a stopping worker waits for it.

Two halves of one defect (ADR workflows-8), each with its own witness.

**The injection.** Temporal cancels a synchronous, threaded activity by raising
`CancelledError` INTO its thread (`temporalio/worker/_activity.py`, the
`_ThreadExceptionRaiser` armed unless the definition sets
`no_thread_cancel_exception`). An exception delivered at an arbitrary bytecode
can land anywhere — inside a transaction, or inside `importlib`'s module lock,
which a consumer measured hanging an xdist worker for good. Every activity in
this tree is idempotent and bounded by its `start_to_close_timeout`, so the
honest shape is to let a cancelled one run to its end. The census below holds
EVERY discovered activity to that, a product's own included, because the
population is `discovered_activities()` and not a list written here.

**The shutdown.** `Worker` defaults `graceful_shutdown_timeout` to zero
(`temporalio/worker/_worker.py`), so every `async with build_worker(...)` exit,
and every SIGTERM, cancelled in-flight activities at once. `build_worker` now
waits up to the longest activity timeout the apps declare — derived from their
call sites, never typed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import inspect
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment

from apps.core.models import Tenant
from apps.workflows.client import (
    _PoolClosingWorker,
    attach_interceptors,
    build_worker,
    discovered_activities,
)
from apps.workflows.types import MarkRunFinished

# private-api: temporalio 1.31.0 — `activity._Definition` is the SDK's own record
# of what `@activity.defn` declared; the public decorator writes the flag and
# nothing public reads it back. Pinned HERE, at import: an SDK that renamed or
# dropped the field fails this module loudly at collection rather than letting
# the census below read a default and pass by skipping.
_DEFINITION_FIELDS = {field.name for field in dataclasses.fields(activity._Definition)}
assert "no_thread_cancel_exception" in _DEFINITION_FIELDS, (
    "temporalio's activity._Definition no longer carries no_thread_cancel_exception "
    f"(fields: {sorted(_DEFINITION_FIELDS)}) — the private-api pin (temporalio 1.31.0) "
    "has moved; re-read temporalio/worker/_activity.py before trusting any census here"
)


def _declines_the_injection(fn: Callable[..., Any]) -> bool:
    return bool(activity._Definition.must_from_callable(fn).no_thread_cancel_exception)


def _is_sync(fn: Callable[..., Any]) -> bool:
    return not inspect.iscoroutinefunction(activity._Definition.must_from_callable(fn).fn)


def undeclined(activities: list[Callable[..., Any]]) -> list[str]:
    """Every SYNC activity that still lets Temporal raise into its thread, named.

    An `async def` activity is outside the question by nature: it is cancelled
    as a task, never by an exception planted in a thread.
    """
    return [
        f"{fn.__module__}.{fn.__qualname__} "
        f"(activity {activity._Definition.must_from_callable(fn).name!r})"
        for fn in activities
        if _is_sync(fn) and not _declines_the_injection(fn)
    ]


# --- the census ---------------------------------------------------------------


def test_every_sync_activity_declines_the_thread_cancel_exception() -> None:
    """R3.1: the closed question over the discovered population.

    Absent: every activity in the tree lets Temporal raise `CancelledError`
    into its worker thread, and this names each one. The remedy is one keyword,
    `@activity.defn(..., no_thread_cancel_exception=True)`.
    """
    population = discovered_activities()
    sync = [fn for fn in population if _is_sync(fn)]
    # A floor, so the census cannot pass by discovering nothing.
    assert sync, "discovered_activities() found no synchronous activity to judge"
    offenders = undeclined(population)
    assert not offenders, (
        f"{len(offenders)} of {len(sync)} synchronous activities let Temporal raise "
        "CancelledError into their thread on cancellation — add "
        "no_thread_cancel_exception=True to each @activity.defn:\n  " + "\n  ".join(offenders)
    )


def test_a_products_own_activity_is_in_the_census(monkeypatch: pytest.MonkeyPatch) -> None:
    """The population is discovery, so an activity a product adds is judged too.

    Planted the way a product would add one — appended to an app's
    `ACTIVITIES` — with the decorator's default, and the census names it.
    """
    from apps.example import activities as example_activities

    @activity.defn(name="a_products_own_sync_activity")
    def a_products_own_sync_activity() -> None:
        """A product's activity, written before this census existed."""

    monkeypatch.setattr(
        example_activities,
        "ACTIVITIES",
        [*example_activities.ACTIVITIES, a_products_own_sync_activity],
    )
    offenders = undeclined(discovered_activities())
    assert any("a_products_own_sync_activity" in line for line in offenders), offenders


# --- the graceful value, derived ------------------------------------------------


def test_the_graceful_value_is_the_longest_declared_activity_timeout() -> None:
    """R3.3: `build_worker` waits exactly as long as the longest attempt the apps allow."""
    from apps.exports.workflows import BUILD_TIMEOUT
    from apps.workflows.client import declared_activity_timeouts, worker_graceful_shutdown

    declared = declared_activity_timeouts()
    assert declared, "no activity call site declared a timeout the derivation could read"
    graceful = worker_graceful_shutdown()
    assert graceful == max(declared.values())
    # One site the derivation must have read, named from the app that owns it.
    assert BUILD_TIMEOUT in declared.values()
    assert graceful >= BUILD_TIMEOUT


def test_the_derivation_refuses_a_timeout_it_cannot_read(tmp_path: Any) -> None:
    """A call site whose timeout is not a constant it can resolve is refused, named."""
    from django.core.exceptions import ImproperlyConfigured

    from apps.workflows.client import activity_timeouts_declared_in

    source = tmp_path / "zzz_timeouts_probe.py"
    source.write_text(
        "from datetime import timedelta\n"
        "NAMED = timedelta(seconds=7)\n"
        "def run(execute, pick):\n"
        "    execute('a', start_to_close_timeout=NAMED)\n"
        "    execute('b', start_to_close_timeout=timedelta(minutes=3))\n"
        "    execute('c', schedule_to_close_timeout=timedelta(seconds=9))\n"
    )
    spec = importlib.util.spec_from_file_location("zzz_timeouts_probe", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    read = sorted(activity_timeouts_declared_in(module).values())
    assert read == [timedelta(seconds=7), timedelta(seconds=9), timedelta(minutes=3)]

    source.write_text("def run(execute, pick):\n    execute('a', start_to_close_timeout=pick())\n")
    spec.loader.exec_module(module)
    with pytest.raises(ImproperlyConfigured, match=r"zzz_timeouts_probe\.py:2"):
        activity_timeouts_declared_in(module)


# --- the shutdown drive -------------------------------------------------------

TASK_QUEUE = "djb-tests-activity-shutdown"

#: The probe's work: `find_spec` — the call the consumer's hang sat inside —
#: 200 times, paced so the loop is still running when the worker is told to stop.
PROBE_LOOPS = 200
PROBE_PACE_SECONDS = 0.005


@dataclasses.dataclass
class _ProbeState:
    started: threading.Event = dataclasses.field(default_factory=threading.Event)
    finished: threading.Event = dataclasses.field(default_factory=threading.Event)
    raised: list[BaseException] = dataclasses.field(default_factory=list)


def plant_the_probe(monkeypatch: pytest.MonkeyPatch) -> _ProbeState:
    """Swap the discovered `mark_run_finished` for a slow one, through `ACTIVITIES`.

    Through discovery rather than a hand-built worker, so what stops is
    `build_worker`'s own assembly. The probe keeps the decorator's DEFAULT —
    it does not decline the injection — so this drive measures the shutdown
    half alone: on the old worker it is cancelled mid-loop at 0 s, on the new
    one the worker waits for it.
    """
    from apps.workflows import activities as workflow_activities

    state = _ProbeState()

    @activity.defn(name="mark_run_finished")
    def slow_finish(payload: MarkRunFinished) -> str:
        state.started.set()
        try:
            for _ in range(PROBE_LOOPS):
                importlib.util.find_spec("apps.events.events")
                time.sleep(PROBE_PACE_SECONDS)
        except BaseException as exc:
            state.raised.append(exc)
            raise
        state.finished.set()
        return "probe"

    monkeypatch.setattr(
        workflow_activities,
        "ACTIVITIES",
        [
            slow_finish
            if activity._Definition.must_from_callable(one).name == "mark_run_finished"
            else one
            for one in workflow_activities.ACTIVITIES
        ],
    )
    return state


def test_build_worker_carries_the_derived_value() -> None:
    """The value reaches the worker, and the drive below sits inside its window.

    The probe answers to `mark_run_finished`, whose declared timeout is
    `FINISH_TIMEOUT`; a graceful window shorter than that would make the drive
    prove the cancel, not the wait.
    """
    from apps.workflows.client import worker_graceful_shutdown
    from apps.workflows.workflows import FINISH_TIMEOUT

    assert FINISH_TIMEOUT <= worker_graceful_shutdown()

    async def build() -> Any:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            worker = build_worker(attach_interceptors(env.client), queue=TASK_QUEUE)
            # private-api: temporalio 1.31.0 — Worker._config
            configured = worker._config["graceful_shutdown_timeout"]
            assert isinstance(worker, _PoolClosingWorker)
            worker._activity_pool.shutdown(wait=True)
            return configured

    assert asyncio.run(build()) == worker_graceful_shutdown()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_stopping_worker_lets_a_running_activity_finish(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.2: exit the `async with` while the activity runs; it finishes first.

    Absent: `finished` is unset when `__aexit__` returns and the activity died
    of `CancelledError` raised into its thread — the zero-second shutdown.
    """
    from apps.workflows.services import start_workflow

    state = plant_the_probe(monkeypatch)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        worker = build_worker(client, queue=TASK_QUEUE)
        assert isinstance(worker, _PoolClosingWorker)
        async with worker:
            await start_workflow(
                workflow="EchoWorkflow",
                arg="stop while I work",
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:echo:shutdown-drive",
            )
            assert await asyncio.to_thread(state.started.wait, 30), "the probe never started"
            asked_to_stop = time.monotonic()
        finished_at_exit = state.finished.is_set()
        stopped_after = time.monotonic() - asked_to_stop

    assert finished_at_exit, (
        f"the worker returned from __aexit__ {stopped_after:.3f}s after it was asked to "
        "stop, before the running activity finished; the activity raised "
        f"{[type(exc).__name__ for exc in state.raised]}"
    )
    assert state.raised == []
    # private-api: Python 3.12 concurrent.futures.ThreadPoolExecutor._threads
    # (the pool is ours, client.py:527)
    live = [thread for thread in worker._activity_pool._threads if thread.is_alive()]
    assert live == [], live
