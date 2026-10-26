"""The workflow sandbox: what a run imports, and what the worker hands it from outside."""

from __future__ import annotations

import gc
import inspect
import sys
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import redis.asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions
from temporalio.worker.workflow_sandbox._importer import Importer
from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

from apps.workflows import client as client_module
from apps.workflows.client import (
    SANDBOX_PASSTHROUGH,
    activity_slots,
    attach_interceptors,
    discovered_workflows,
    workflow_runner,
)
from apps.workflows.tests.sandboxwork import CollectInActivation

TASK_QUEUE = "djb-tests-sandbox"

#: The sandbox's own words for an import it did not see at the run's first load.
LATE_IMPORT = "was imported after initial workflow load"

#: First-party packages: their closures are what the census walks, never what it passes through.
FIRST_PARTY = ("apps", "pilecap")

#: A passthrough member that would be the sandbox off by another name.
NEVER_PASSED_THROUGH = ("django", *FIRST_PARTY)

#: The module whose workflow half runs inside every activation (the interceptor).
INTERCEPTOR_MODULE = "apps.workflows.context"

#: The pools the leaking fake push leaves for the collector, kept from being freed early.
LEFT_POOLS: list[Any] = []

#: The `redis` member's contract line, pinned.
BELT_REASON = (
    "#: A finalizer's import, not a workflow's: "
    "a leaked pool's `__del__` run by GC in an activation."
)

#: The one pool the fixed push keeps for the process.
KEPT_POOL: list[Any] = []


@activity.defn(name="load_delivery_targets")
def load_delivery_targets(_event: Any) -> dict[str, Any]:
    """One subscriber, so the fan-out leg runs."""
    return {
        "event_name": "example.widget.created",
        "targets": [{"endpoint_id": "endpoint-1", "url": "https://subscriber.example/hook"}],
    }


@activity.defn(name="deliver_webhook")
def deliver_webhook(_payload: Any) -> dict[str, Any]:
    """The subscriber answered."""
    return {"delivery_id": "delivery-1", "status": "delivered", "code": 200}


def _pool_holding_a_connection() -> Any:
    pool = redis.asyncio.ConnectionPool.from_url("redis://127.0.0.1:1/0")
    pool._available_connections.append(pool.make_connection())  # type: ignore[no-untyped-call]  # redis-py ships it unannotated
    return pool


@activity.defn(name="push_realtime")
def push_realtime(_payload: Any) -> bool:
    """What the fixed push does: one pool for the process, kept, never left for the collector."""
    if not KEPT_POOL:
        KEPT_POOL.append(_pool_holding_a_connection())
    return True


@activity.defn(name="push_realtime")
def push_realtime_leaking(_payload: Any) -> bool:
    """A product's leaking push: a closed loop's pool still holding a connection, in a cycle."""
    pool = _pool_holding_a_connection()
    pool.cycle = pool  # only the collector can free it
    LEFT_POOLS.append(pool)
    return True


@activity.defn(name="index_search")
def index_search(_payload: Any) -> bool:
    """The index confirmed the write."""
    return True


@activity.defn(name="close_outbox")
def close_outbox(_payload: Any) -> None:
    """The outbox row is closed."""


@activity.defn(name="mark_run_finished")
def mark_run_finished(_payload: Any) -> str:
    """The run's row is closed for this tenant."""
    return "acme"


@activity.defn(name="deliver_message")
def deliver_message(_payload: Any) -> dict[str, Any]:
    """The transport took it."""
    return {"provider": "locmem", "provider_message_id": "message-1"}


@activity.defn(name="finish_message")
def finish_message(payload: Any) -> str:
    """The outcome is recorded."""
    return str(payload["status"])


FAKES: list[Callable[..., Any]] = [
    load_delivery_targets,
    deliver_webhook,
    index_search,
    close_outbox,
    mark_run_finished,
    deliver_message,
    finish_message,
]


async def _late_imports(push: Callable[..., Any], runner: SandboxedWorkflowRunner) -> list[str]:
    """A dispatch and a send, the collector run inside each last activation: the late imports."""
    collecting = gc.isenabled()
    gc.disable()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            async with await WorkflowEnvironment.start_time_skipping() as env:
                client = attach_interceptors(env.client)
                async with Worker(
                    client,
                    task_queue=TASK_QUEUE,
                    workflows=discovered_workflows(),
                    activities=[*FAKES, push],
                    workflow_runner=runner,
                    interceptors=[CollectInActivation()],
                    activity_executor=ThreadPoolExecutor(max_workers=4),
                    max_concurrent_activities=4,
                ):
                    LEFT_POOLS.clear()
                    dispatched = await client.execute_workflow(
                        "DispatchEventWorkflow",
                        {"event_id": "event-1"},
                        id="sandbox:events:event:1",
                        task_queue=TASK_QUEUE,
                    )
                    LEFT_POOLS.clear()
                    sent = await client.execute_workflow(
                        "DeliverMessageWorkflow",
                        {"message_id": "message-1"},
                        id="sandbox:comms:message:1",
                        task_queue=TASK_QUEUE,
                    )
    finally:
        if collecting:
            gc.enable()
    assert dispatched["pushed"] is True, dispatched
    assert sent["status"] == "sent", sent
    return sorted({str(one.message) for one in caught if LATE_IMPORT in str(one.message)})


@pytest.mark.asyncio
async def test_a_workflow_run_imports_nothing_after_initial_load() -> None:
    """The fixed push under the worker's own runner: no late import inside an activation."""
    late = await _late_imports(push_realtime, workflow_runner())
    assert late == [], f"{len(late)} module(s) imported inside an activation:\n" + "\n".join(late)


@pytest.mark.asyncio
async def test_the_belt_covers_a_leaked_pool() -> None:
    """A leaking push imports late without the `redis` member, and nothing late with it."""
    assert SANDBOX_PASSTHROUGH == ("redis",), SANDBOX_PASSTHROUGH
    assert BELT_REASON in inspect.getsource(client_module)
    unbelted = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default)
    late = await _late_imports(push_realtime_leaking, unbelted)
    assert any("redis" in line for line in late), late
    assert await _late_imports(push_realtime_leaking, workflow_runner()) == []


def _sandbox_closure(module: str) -> set[str]:
    """Every module the sandbox imports fresh to load `module`, by the worker's own restrictions."""
    importer = Importer(workflow_runner().restrictions, RestrictionContext())
    with importer.applied():
        before = set(sys.modules)
        __import__(module)
        return set(sys.modules) - before


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def test_the_sandbox_closure_is_declared() -> None:
    """Each workflow module's fresh closure is the stdlib, Temporal and first-party code only."""
    modules = sorted({cls.__module__ for cls in discovered_workflows()} | {INTERCEPTOR_MODULE})
    assert len(modules) > 1, modules
    foreign: dict[str, list[str]] = {}
    for module in modules:
        closure = _sandbox_closure(module)
        assert module in closure, f"{module} was not imported fresh: the census measured nothing"
        outside = sorted(
            name
            for name in closure
            if _top(name) not in sys.stdlib_module_names
            and _top(name) not in ("temporalio", *FIRST_PARTY)
        )
        if outside:
            foreign[module] = outside
    assert foreign == {}, (
        f"a workflow module reaches third-party code the sandbox re-imports: {foreign}"
    )


def test_no_passthrough_member_is_workflow_code() -> None:
    """Each member is a third-party package no workflow module imports; none is Django or ours."""
    assert SANDBOX_PASSTHROUGH, "nothing is declared"
    for member in SANDBOX_PASSTHROUGH:
        assert _top(member) not in NEVER_PASSED_THROUGH, member
        assert _top(member) not in sys.stdlib_module_names, member
        assert __import__(member) is not None
    modules = sorted({cls.__module__ for cls in discovered_workflows()} | {INTERCEPTOR_MODULE})
    reached = {
        module: sorted(
            name
            for name in _sandbox_closure(module)
            if any(name == m or name.startswith(f"{m}.") for m in SANDBOX_PASSTHROUGH)
        )
        for module in modules
    }
    assert {m: r for m, r in reached.items() if r} == {}


def test_no_activity_waits_for_a_database_connection(settings: Any) -> None:
    """The worker schedules no more activities at once than its own pool holds."""
    assert settings.DATABASE_POOL_ENABLED
    assert 0 < activity_slots() < settings.DATABASE_POOL_MAX_SIZE
    settings.DATABASE_POOL_MAX_SIZE = activity_slots()
    assert activity_slots() == settings.DATABASE_POOL_MAX_SIZE - 1
    settings.DATABASE_POOL_MAX_SIZE = 1
    assert activity_slots() == 1
