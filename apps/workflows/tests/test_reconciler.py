"""The sweep that counts the dead, and the schedule that deploys it.

`start_workflow_on_commit` writes the visibility row inside the caller's
transaction and dials Temporal on commit. Between those two moments a process
can die, and previously the row it left — RUNNING, with an empty `run_id`
— was read by nothing in the product and by no management command either.
The same sweep mops the history left behind from before the
platform app's own workflows closed their own runs.

Driven against the time-skipping server wherever the question is "what does
Temporal say", because the whole decision is the server's answer and a stub
would be a test of the stub. The schedule half uses a stand-in for the
schedules API, which the time-skipping server does not implement — this app's
one `FakeScheduleServer` (`apps/core/tests/fakes.py`).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import override_settings
from django.utils import timezone
from temporalio.client import (
    Client,
    ScheduleOverlapPolicy,
)
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from apps.core.actor import system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.core.tests.fakes import FakeScheduleServer
from apps.workflows import activities
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker, ensure_schedules
from apps.workflows.models import WorkflowRun
from apps.workflows.services import record_run, start_workflow, workflow_id
from apps.workflows.types import EchoOutput, ReconcileRuns

pytestmark = pytest.mark.django_db(transaction=True)

TASK_QUEUE = "djb-tests-reconcile"

#: Comfortably past `RECONCILE_AFTER`, so a planted row is unambiguously old.
LONG_AGO = timedelta(hours=2)
PLATFORM_RUN_ID = "platform:accounts:identity:stranded"


def age(run: WorkflowRun, *, by: timedelta) -> None:
    """Backdate a row's `started_at`. `QuerySet.update`, never a hand-set field.

    `started_at` has a default and `updated_at` is `auto_now`, so assigning and
    saving would move the wrong column as well; the conventions say `update()`
    or `time_machine` for exactly this.
    """
    WorkflowRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - by)


def planted(*, tenant: Tenant | None, key: str, old: bool) -> WorkflowRun:
    """A row recorded through the service, with no execution behind it.

    Which is what `record_run` alone produces — it is `_start_recorded` that
    attaches a `run_id`, and this is precisely the state of a process that died
    before it got there.
    """
    wanted = (
        workflow_id(tenant=tenant, app="workflows", noun="echo", key=key)
        if tenant is not None
        else PLATFORM_RUN_ID
    )
    run = record_run(
        tenant=tenant, workflow_id=wanted, workflow_type="EchoWorkflow", actor=system_actor(tenant)
    )
    if old:
        age(run, by=LONG_AGO)
    return run


def swept(run: WorkflowRun) -> WorkflowRun:
    """The row as it is now, read through its own population's path."""
    if run.tenant_id is None:
        return WorkflowRun.objects.for_platform().get(pk=run.pk)
    return WorkflowRun.objects.for_tenant(run.tenant).get(pk=run.pk)


# --- The sweep -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sweep_closes_both_populations_and_leaves_the_living_alone(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One sweep, because the interference is the interesting part.

    Five rows, one run of the activity: a stranded tenant row and a stranded
    platform row (both closed `failed`, naming never-started), a row whose
    execution really did complete (closed from the real outcome), a row younger
    than the threshold and a row that already has a `run_id` (both untouched).
    Asserting them together is what proves the sweep discriminates rather than
    closing everything it can see.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)

        async def connect() -> Client:
            return client

        monkeypatch.setattr(client_module, "get_client", connect)

        async with build_worker(client, queue=TASK_QUEUE):
            # The one row with a real, finished execution behind it. It is
            # started properly and then dragged back into the stranded shape:
            # old, and with its run_id cleared, which is what a row looks like
            # when the client call died *after* Temporal accepted the start.
            real = await start_workflow(
                workflow="EchoWorkflow",
                arg="alive",
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="real"),
            )
            await client.get_workflow_handle(real.workflow_id, result_type=EchoOutput).result()

            def plant() -> dict[str, WorkflowRun]:
                WorkflowRun.objects.filter(pk=real.pk).update(
                    status=WorkflowRun.Status.RUNNING,
                    run_id="",
                    finished_at=None,
                    started_at=timezone.now() - LONG_AGO,
                )
                rows = {
                    "tenant_stranded": planted(tenant=tenant, key="stranded", old=True),
                    "platform_stranded": planted(tenant=None, key="", old=True),
                    "young": planted(tenant=tenant, key="young", old=False),
                    "dialled": planted(tenant=tenant, key="dialled", old=True),
                }
                WorkflowRun.objects.filter(pk=rows["dialled"].pk).update(run_id="a-real-run-id")
                return rows

            rows = await run_db(plant)

            closed = await run_db(
                activities.reconcile_runs,
                ReconcileRuns(after_seconds=activities.reconcile_after_seconds()),
            )

    # Three closed: two never-started and the one whose execution had finished.
    assert closed == 3

    for name in ("tenant_stranded", "platform_stranded"):
        row = await run_db(swept, rows[name])
        assert row.status == WorkflowRun.Status.FAILED, name
        assert row.finished_at is not None, name
        assert "never started" in row.error, name

    # The row whose execution really did complete takes the server's answer.
    finished = await run_db(swept, real)
    assert finished.status == WorkflowRun.Status.COMPLETED
    assert finished.error == ""

    # Too young to judge, and one that was dialled: both untouched.
    for name in ("young", "dialled"):
        row = await run_db(swept, rows[name])
        assert row.status == WorkflowRun.Status.RUNNING, name
        assert row.finished_at is None, name


@pytest.mark.asyncio
async def test_a_describe_that_errors_is_a_skip_and_never_an_absence(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property: an unanswered question is not a `no`.

    A server that times out, or is briefly unavailable, must not be read as
    "there is no such execution" — that would close live runs whenever the
    network hiccuped. Only `NOT_FOUND` is an absence, and this plants the other
    kind.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)

        async def connect() -> Client:
            return client

        monkeypatch.setattr(client_module, "get_client", connect)

        async def unavailable(_client: Client, _workflow_id: str) -> Any:
            raise RPCError("the server did not answer", RPCStatusCode.UNAVAILABLE, b"")

        monkeypatch.setattr(activities, "describe_execution", unavailable)

        row = await run_db(planted, tenant=tenant, key="unanswered", old=True)
        closed = await run_db(
            activities.reconcile_runs,
            ReconcileRuns(after_seconds=activities.reconcile_after_seconds()),
        )

    assert closed == 0
    untouched = await run_db(swept, row)
    assert untouched.status == WorkflowRun.Status.RUNNING
    assert untouched.error == ""


def test_only_not_found_is_read_as_an_absence() -> None:
    """The same rule at the seam, so the mapping itself is pinned.

    `describe_execution` is the one place that decides what "the server has no
    such execution" means, and the decision is one comparison. A test that only
    drove the sweep would prove the outcome without pinning the rule.
    """

    class Handle:
        def __init__(self, status: RPCStatusCode) -> None:
            self.status = status

        async def describe(self) -> Any:
            raise RPCError("no", self.status, b"")

    class FakeClient:
        def __init__(self, status: RPCStatusCode) -> None:
            self.status = status

        def get_workflow_handle(self, _workflow_id: str) -> Any:
            return Handle(self.status)

        def config(self) -> dict[str, Any]:  # pragma: no cover - never reached
            return {}

    from asgiref.sync import async_to_sync

    absent: Any = FakeClient(RPCStatusCode.NOT_FOUND)
    assert async_to_sync(activities.describe_execution)(absent, "x") is None

    unanswered: Any = FakeClient(RPCStatusCode.UNAVAILABLE)
    with pytest.raises(RPCError):
        async_to_sync(activities.describe_execution)(unanswered, "x")


# --- The schedule --------------------------------------------------------------


# `deployment` declared out loud: the suite runs in `process` mode (ADR
# platform-lifecycle-1), where no Schedule object is created at all, so a test
# about what a durable Schedule does names the class it is proving.
@override_settings(TEMPORAL_MACHINERY_LIFETIME="deployment")
@pytest.mark.asyncio
async def test_the_worker_ensures_the_sweep_at_startup_through_discovery() -> None:
    """The reconciler is deployed with the code, and nothing registers it.

    `ensure_schedules` is what the worker runs at startup; it finds `SCHEDULES`
    in every installed app's `activities.py`. A reconciler that existed as a
    function nobody runs would be the finding closed here, one layer up —
    which is the same sentence the outbox relay's test writes, for the same
    reason.
    """
    server = FakeScheduleServer()
    client: Any = server
    queue = str(django_settings.TEMPORAL_TASK_QUEUE)
    ours = activities.RECONCILE_RUNS.schedule_id(queue)

    await ensure_schedules(client)
    await ensure_schedules(client)

    # Present once, created once, updated once: a restart converges rather than
    # adding a second sweep.
    assert ours in server.present
    assert [schedule_id for schedule_id, _ in server.created if schedule_id == ours] == [ours]
    assert [schedule_id for schedule_id, _ in server.updated if schedule_id == ours] == [ours]


def test_the_schedule_carries_the_threshold_and_skips_on_overlap() -> None:
    """What the schedule actually asks for, read off the value.

    The threshold rides in the action's argument because a workflow may not read
    a clock (house rule 9), and `SKIP` is what stops two sweeps reading the same
    stranded rows.
    """
    schedule = activities.RECONCILE_RUNS.schedule("djb-alpha")
    action: Any = schedule.action

    assert action.workflow == activities.RECONCILE_WORKFLOW
    assert action.args == [ReconcileRuns(after_seconds=activities.reconcile_after_seconds())]
    assert action.id == "platform:workflows:reconcile:djb-alpha"
    assert schedule.policy.overlap is ScheduleOverlapPolicy.SKIP
    assert activities.RECONCILE_AFTER == timedelta(minutes=15)


def test_the_schedule_and_its_runs_are_namespaced_by_task_queue() -> None:
    """Two deployments on one Temporal namespace must not fight over one sweep."""
    machine = activities.RECONCILE_RUNS
    assert machine.schedule_id("djb-alpha") != machine.schedule_id("djb-beta")
    alpha: Any = machine.schedule("djb-alpha").action
    beta: Any = machine.schedule("djb-beta").action
    assert alpha.id != beta.id
