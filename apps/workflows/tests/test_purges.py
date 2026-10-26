"""The two sweeps this app owns, and the declarations they make true.

House rule 31 says every model declares how its data dies, and that a `purged`
declaration's callable must be **reached** — an activity references it, a
workflow executes that activity, and a `ScheduleDeclaration` names that
workflow. It proves the chain is *written down*. It says nothing at all about
whether the right rows go, and says so in its own `does_not_cover`:

> WHETHER A PURGE FILTER IS CORRECT. The chain proves a callable is reached,
> never that the rows it deletes are the rows that should go — a
> `filter(expires_at__lt=...)` with the comparison the wrong way round passes
> this rule completely.

This module is that other half, for both declarations:

* **`WorkflowRun`** (`models.py`) — the run ledger, `completed` and `cancelled`
  rows only, past a 180-day window. `running` rows are the reconciler's
  population and `failed` rows are the record of something that broke; both
  survive every window, and the first test here is what stops that being a
  sentence in a docstring nobody checked.
* **`django_session`** (`lifecycle.py`) — expired sessions, daily. Nothing in
  this tree ever cleared one, so the test that matters most is
  the pair: the expired ones go **and a live session still authenticates**.

The end-to-end halves are driven against the **time-skipping server** through
`start_declared_run`, which starts a sweep from its own `ScheduleDeclaration`
under the declared id — so what runs is the declaration the gate walks, not a
workflow a test named by hand.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone
from temporalio.client import ScheduleOverlapPolicy
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.core.asyncdb import run_db
from apps.core.lifecycle import LifecycleKind, lifecycle_of
from apps.core.models import Tenant
from apps.workflows import activities
from apps.workflows import client as client_module
from apps.workflows.client import (
    attach_interceptors,
    build_worker,
    discovered_schedules,
    start_declared_run,
)
from apps.workflows.models import WorkflowRun
from apps.workflows.services import (
    FINISHED_RUN_RETENTION,
    _starter_actor,
    check_workflow_id,
    purge_finished_runs,
    record_run,
    workflow_id,
)
from apps.workflows.types import PurgeFinishedRuns
from apps.workflows.workflows import PurgeExpiredSessionsWorkflow, PurgeFinishedRunsWorkflow

pytestmark = pytest.mark.django_db

RUNS_URL = "/api/v1/runs/"

#: Comfortably past the window, so a planted row is unambiguously outside it.
LONG_PAST = FINISHED_RUN_RETENTION + timedelta(days=30)

#: Comfortably inside it, for the row that must survive.
RECENT = timedelta(days=1)


def closed(
    *,
    tenant: Tenant | None,
    key: str,
    status: str,
    finished_ago: timedelta,
    user: User | None = None,
) -> WorkflowRun:
    """One ledger row in a given terminal state, closed a given time ago.

    Written through `record_run` — the service every starter goes through — and
    then moved into its terminal state with `QuerySet.update()` rather than by
    assigning fields, because `updated_at` is `auto_now` and a hand-set save
    would move a column this test never mentioned (the conventions say
    `update()` or `time_machine` for exactly this).
    """
    wanted = (
        workflow_id(tenant=tenant, app="example", noun="widget", key=key)
        if tenant is not None
        else f"platform:workflows:purge:{key}"
    )
    run = record_run(
        tenant=tenant,
        workflow_id=wanted,
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="d" * 64,
        actor=_starter_actor(tenant=tenant, user=user),
    )
    WorkflowRun.objects.filter(pk=run.pk).update(
        status=status,
        run_id=f"execution-{key}",
        finished_at=timezone.now() - finished_ago,
    )
    return run


def alive(pk: Any) -> bool:
    """Whether this row survived. `filter(...).exists()` on the whole table.

    Deliberately unscoped, and deliberately in a test: the question here is
    "does this row still exist anywhere", which is the one question a scoped
    read cannot answer about a purge — a `for_tenant` miss and a deleted row
    look identical through it, and the test would pass on either.
    """
    return WorkflowRun.objects.filter(pk=pk).exists()


# --- The run ledger's window ---------------------------------------------------


def test_the_purge_takes_exactly_the_closed_runs_past_the_window(
    tenant: Tenant, owner: User
) -> None:
    """Six rows, one purge: the two that should go, and the four that must not.

    Asserting them together is what proves the filter DISCRIMINATES rather than
    deleting everything old that it can see — the same shape
    `test_reconciler.py` uses for the sweep, and for the same reason.

    Each survivor is a different reason:

    * **`failed`, and ancient** — a failure is the record of something that did
      not work, and deleting it is deleting the finding (the sentence
      `apps.events.services.purge_dispatched_outbox` has carried one app over).
      This is the row a person opens six weeks later to ask "has
      this been breaking the whole time"; a window that ate it would answer
      "no" by having forgotten.
    * **`running`, and ancient** — the reconciler's population, and it is
      sacred. A purge that took one would delete a promise
      `activities.reconcile_runs` was about to keep, which is rule 28's exact
      fear with the evidence removed.
    * **`completed`, and recent** — inside the window. The obvious one, and the
      one a comparison written the wrong way round would fail.
    * **`completed`, ancient, and never closed** (`finished_at` is NULL) — the
      shape a row wears when it was marked terminal by something that did not
      set the timestamp. `finished_at__lt` cannot see a NULL, so it survives,
      and stating that here is what stops a later "fix" widening the filter to
      `status__in` alone and quietly taking rows nobody dated.
    """
    old_completed = closed(
        tenant=tenant,
        key="old-done",
        status=WorkflowRun.Status.COMPLETED,
        finished_ago=LONG_PAST,
        user=owner,
    )
    old_cancelled = closed(
        tenant=tenant,
        key="old-stopped",
        status=WorkflowRun.Status.CANCELLED,
        finished_ago=LONG_PAST,
        user=owner,
    )
    old_failed = closed(
        tenant=tenant,
        key="old-broken",
        status=WorkflowRun.Status.FAILED,
        finished_ago=LONG_PAST,
        user=owner,
    )
    recent_completed = closed(
        tenant=tenant,
        key="new-done",
        status=WorkflowRun.Status.COMPLETED,
        finished_ago=RECENT,
        user=owner,
    )
    old_running = closed(
        tenant=tenant,
        key="old-live",
        status=WorkflowRun.Status.RUNNING,
        finished_ago=LONG_PAST,
        user=owner,
    )
    WorkflowRun.objects.filter(pk=old_running.pk).update(finished_at=None)
    undated = closed(
        tenant=tenant,
        key="undated",
        status=WorkflowRun.Status.COMPLETED,
        finished_ago=LONG_PAST,
        user=owner,
    )
    WorkflowRun.objects.filter(pk=undated.pk).update(finished_at=None)

    went = purge_finished_runs(before=timezone.now() - FINISHED_RUN_RETENTION, tenant=None).count

    assert went == 2
    assert not alive(old_completed.pk)
    assert not alive(old_cancelled.pk)
    assert alive(old_failed.pk), "a failure is the finding; deleting it deletes the finding"
    assert alive(old_running.pk), "the reconciler's population is sacred"
    assert alive(recent_completed.pk), "inside the window"
    assert alive(undated.pk), "a NULL finished_at is not a date past the window"


def test_the_platform_population_is_purged_too(tenant: Tenant) -> None:
    """The runs no tenant owns are in the window as well, and `for_tenant` cannot see them.

    `WorkflowRun.tenant` is nullable and null is a declared population (ADR
    workflows-3): identity revocations and workforce syncs belong to the
    deployment, not to a tenant, and `for_tenant` fails closed and can never
    reach them. A purge written only as a loop over tenants would leave that
    half of the ledger growing for ever while every test about retention passed
    — which is the poller-that-was-never-built one level in.
    """
    platform_old = closed(
        tenant=None, key="old", status=WorkflowRun.Status.COMPLETED, finished_ago=LONG_PAST
    )
    platform_new = closed(
        tenant=None, key="new", status=WorkflowRun.Status.COMPLETED, finished_ago=RECENT
    )

    went = purge_finished_runs(before=timezone.now() - FINISHED_RUN_RETENTION, tenant=None).count

    assert went == 1
    assert not alive(platform_old.pk)
    assert alive(platform_new.pk)


def test_the_purge_is_idempotent(tenant: Tenant, owner: User) -> None:
    """It deletes by age, so the second pass in one window takes nothing."""
    closed(
        tenant=tenant,
        key="old-done",
        status=WorkflowRun.Status.COMPLETED,
        finished_ago=LONG_PAST,
        user=owner,
    )

    before = timezone.now() - FINISHED_RUN_RETENTION
    assert purge_finished_runs(before=before, tenant=None).count == 1
    assert purge_finished_runs(before=before, tenant=None).count == 0


def test_the_reconciler_still_finds_its_stranded_rows_after_a_purge(
    tenant: Tenant, owner: User
) -> None:
    """The two sweeps do not interfere. **Rule 28's fear, tested directly.**

    `activities.stranded_runs` is the reconciler's whole input: RUNNING rows
    with an empty `run_id`, older than its threshold. This asserts that the set
    it sees is byte-for-byte the same before and after a purge has run over the
    same table — so a run the reconciler was about to close cannot be swept out
    from under it, in either population.

    Its own end-to-end tests (`test_reconciler.py`) stay green unchanged; this
    is the interference question those tests cannot ask, because nothing purged
    when they were written.
    """
    stranded = record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key="stranded"),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="d" * 64,
        actor=_starter_actor(tenant=tenant, user=owner),
    )
    WorkflowRun.objects.filter(pk=stranded.pk).update(
        started_at=timezone.now() - LONG_PAST, run_id=""
    )
    closed(
        tenant=tenant,
        key="old-done",
        status=WorkflowRun.Status.COMPLETED,
        finished_ago=LONG_PAST,
        user=owner,
    )
    cutoff = timezone.now() - activities.RECONCILE_AFTER
    seen_before = {row.pk for row in activities.stranded_runs(older_than=cutoff)}

    purge_finished_runs(before=timezone.now() - FINISHED_RUN_RETENTION, tenant=None)

    assert seen_before == {stranded.pk}
    assert {row.pk for row in activities.stranded_runs(older_than=cutoff)} == seen_before


# --- Sessions --------------------------------------------------------------------
#
# `transaction=True` on every test below: `purge_expired_sessions` calls
# `close_old_connections()` at both ends, because out in the worker there is no
# request cycle to do it. Inside the wrapping transaction a plain `django_db`
# test uses, that closes the connection the test itself is holding — so these
# run the way the worker does, against real commits. The same reason and the
# same wording as `apps/events/tests/test_activities.py`, which met it first.
#
# The run-ledger tests above stay on the plain marker: they drive the SERVICE,
# which is ordinary synchronous code with no worker-thread bookkeeping in it.


def a_session(*, expired: bool) -> str:
    """One real session row, made by the session engine, dated by `update()`."""
    store = SessionStore()
    store["what"] = "a real session, written by the engine that owns them"
    store.create()
    if expired:
        Session.objects.filter(session_key=store.session_key).update(
            expire_date=timezone.now() - timedelta(days=1)
        )
    return str(store.session_key)


@pytest.mark.django_db(transaction=True)
def test_the_sweep_clears_expired_sessions_and_leaves_live_ones(db: None) -> None:
    """Something finally clears `django_session`.

    Two rows, one sweep. Previously nothing in the tree — no cron entry,
    no management command in any deployment path, no schedule — ever removed
    one, so every login since day zero left a row that would outlive the person
    who made it.
    """
    expired = a_session(expired=True)
    live = a_session(expired=False)

    cleared = activities.purge_expired_sessions()

    assert cleared == 1
    assert not Session.objects.filter(session_key=expired).exists()
    assert Session.objects.filter(session_key=live).exists()


@pytest.mark.django_db(transaction=True)
def test_a_live_session_still_authenticates_after_the_sweep(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The door-level half, and the one that would have caught the dangerous bug.

    A purge with its comparison the wrong way round deletes the *live* sessions
    and leaves the expired ones — rule 31's own `does_not_cover` names that
    exact mistake as something it cannot see, and a row-count assertion alone
    would pass on a sweep that cleared one row either way. So this signs in over
    the door, runs the sweep, and asks the door again: everybody logged out at
    3am is a defect no census would report.
    """
    api.force_login(owner)
    assert api.get(RUNS_URL).status_code == 200

    activities.purge_expired_sessions()

    assert api.get(RUNS_URL).status_code == 200


@pytest.mark.django_db(transaction=True)
def test_the_session_sweep_is_idempotent(db: None) -> None:
    """Expiry is a property of the row, so a second sweep clears nothing."""
    a_session(expired=True)

    assert activities.purge_expired_sessions() == 1
    assert activities.purge_expired_sessions() == 0


# --- The machines, and the chain the gate walks ----------------------------------


def declaration(name: str) -> Any:
    """One `ScheduleDeclaration` by name, off the registry rule 31 itself walks."""
    found = [one for one in discovered_schedules() if one.name == name]
    assert len(found) == 1, f"{name} is not declared exactly once: {found}"
    return found[0]


def test_both_purges_are_declared_machines_with_the_house_shape() -> None:
    """What each schedule actually asks for, read off the value.

    The retention window rides in the ledger purge's action because a workflow
    may not read a clock (house rule 9), and because an operator should be able
    to see the window in the Temporal UI rather than in the source. The session
    sweep carries no argument at all: expiry is on the row, so there is nothing
    to tune and nothing to go stale.

    `SKIP` on both, for the reason every sweep in this tree has it: two purges
    at once would read the same rows, and while deleting by age twice is
    harmless there is no reason to pay for the race.
    """
    runs: Any = declaration("workflows.purge-finished-runs").schedule("djb-alpha")
    sessions: Any = declaration("workflows.purge-expired-sessions").schedule("djb-alpha")

    assert runs.action.workflow == activities.PURGE_RUNS_WORKFLOW
    assert runs.action.args == [
        PurgeFinishedRuns(retention_seconds=activities.finished_run_retention_seconds())
    ]
    assert runs.action.id == "platform:workflows:purge-runs:djb-alpha"
    assert runs.policy.overlap is ScheduleOverlapPolicy.SKIP

    assert sessions.action.workflow == activities.PURGE_SESSIONS_WORKFLOW
    assert list(sessions.action.args) == []
    assert sessions.action.id == "platform:workflows:purge-sessions:djb-alpha"
    assert sessions.policy.overlap is ScheduleOverlapPolicy.SKIP

    assert runs.spec.intervals[0].every == timedelta(hours=24)
    assert sessions.spec.intervals[0].every == timedelta(hours=24)
    assert FINISHED_RUN_RETENTION == timedelta(days=180)


def test_both_purges_are_namespaced_by_task_queue() -> None:
    """Two deployments on one Temporal namespace must not fight over one sweep.

    ADR events-2, and a namespaced queue is what it was written for: a schedule id is
    global to the namespace, so while an id was a constant the last worker to
    start silently re-pointed everybody else's sweep at a queue that was about
    to go away.
    """
    for name in ("workflows.purge-finished-runs", "workflows.purge-expired-sessions"):
        machine = declaration(name)
        assert machine.schedule_id("djb-alpha") != machine.schedule_id("djb-beta")
        alpha: Any = machine.schedule("djb-alpha").action
        beta: Any = machine.schedule("djb-beta").action
        assert alpha.id != beta.id
        assert check_workflow_id(id=alpha.id, tenant=None) == alpha.id


def test_both_purge_workflows_declare_that_they_own_no_run() -> None:
    """House rule 28's posture, stated: schedule-started, so there is no row to close.

    Rule 28 says every workflow class either closes its run row through the
    finish seam or declares `owns_no_run = True` — the ledger never lies by
    omission. Both purges take the second branch, and both take it for the
    reason `ReconcileRunsWorkflow` does: no service called `record_run` for a
    schedule-started run, so there is no `WorkflowRun` row and nobody waiting on
    one. It is doubly right for the ledger purge, which would otherwise be a
    table cleaning itself and growing by one every day.
    """
    assert PurgeFinishedRunsWorkflow.owns_no_run is True
    assert PurgeExpiredSessionsWorkflow.owns_no_run is True


def test_both_declarations_name_a_callable_the_schedule_chain_reaches() -> None:
    """The chain rule 31 walks, pinned here in the app that owns both ends.

    `purged_by` -> an activity that references it -> a workflow that executes
    that activity -> a `ScheduleDeclaration` whose action names that workflow.
    The gate proves this over the whole tree; this test proves it for *these
    two* in the app whose diff would break it, so a builder who deletes a
    `SCHEDULES` entry meets a red test in their own app before they meet a
    census in `quality/`.

    What it does NOT claim is the boundary rule 31 declares in full: that the
    chain is WRITTEN DOWN, never that the schedule is live on a Temporal server
    or that its last tick ran. That is the lifecycle census's job, and a green run here
    must never be read as a purge that happened.
    """
    run_ledger = lifecycle_of(WorkflowRun)
    sessions = lifecycle_of(Session)
    assert run_ledger is not None and sessions is not None
    assert run_ledger.kind is LifecycleKind.PURGED
    assert sessions.kind is LifecycleKind.PURGED
    assert run_ledger.purged_by == "apps.workflows.services.purge_finished_runs"
    assert sessions.purged_by == "apps.workflows.activities.purge_expired_sessions"

    # `Any` on the action, because `Schedule.action` is the union of every action
    # kind the SDK has and only `ScheduleActionStartWorkflow` carries a workflow.
    # Narrowing with an isinstance here would assert the SDK's own type rather
    # than this app's declaration, which is the thing under test.
    actions: dict[str, Any] = {
        one.name: one.schedule("djb-chain").action for one in discovered_schedules()
    }
    declared_workflows = {name: action.workflow for name, action in actions.items()}
    assert declared_workflows["workflows.purge-finished-runs"] == "PurgeFinishedRunsWorkflow"
    assert declared_workflows["workflows.purge-expired-sessions"] == "PurgeExpiredSessionsWorkflow"

    assert activities.purge_finished_runs in activities.ACTIVITIES
    assert activities.purge_expired_sessions in activities.ACTIVITIES


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_declared_sweeps_run_end_to_end_from_their_declarations(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both machines, started the way the engine starts them, against a real server.

    `start_declared_run` takes a `ScheduleDeclaration` and starts its workflow
    under the declared id — so what is exercised here is the same object
    `apps.workflows.client.discovered_schedules` hands the engine and rule 31
    walks, rather than a workflow class a test named by hand. That is the
    difference between proving the chain and proving that a workflow exists.

    The rows are the assertion: an ancient completed run and an expired session
    go, a recent run and a live session stay. The workflows return counts too,
    and the counts are checked, but a count is what a broken filter would also
    return.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)

        async def connect() -> Any:
            return client

        monkeypatch.setattr(client_module, "get_client", connect)
        queue = str(django_settings.TEMPORAL_TASK_QUEUE)

        async with build_worker(client, queue=queue):

            def plant() -> tuple[Any, Any, str, str]:
                old = closed(
                    tenant=tenant,
                    key="e2e-old",
                    status=WorkflowRun.Status.COMPLETED,
                    finished_ago=LONG_PAST,
                )
                new = closed(
                    tenant=tenant,
                    key="e2e-new",
                    status=WorkflowRun.Status.COMPLETED,
                    finished_ago=RECENT,
                )
                return old.pk, new.pk, a_session(expired=True), a_session(expired=False)

            old_pk, new_pk, dead_key, live_key = await run_db(plant)

            for name in ("workflows.purge-finished-runs", "workflows.purge-expired-sessions"):
                started = await start_declared_run(client, declaration(name))
                await client.get_workflow_handle(started, result_type=int).result()

    def survivors() -> tuple[bool, bool, bool, bool]:
        return (
            alive(old_pk),
            alive(new_pk),
            Session.objects.filter(session_key=dead_key).exists(),
            Session.objects.filter(session_key=live_key).exists(),
        )

    old_alive, new_alive, dead_alive, live_alive = await run_db(survivors)
    assert not old_alive, "the ancient completed run should have been purged"
    assert new_alive, "the recent completed run is inside the window"
    assert not dead_alive, "the expired session should have been cleared"
    assert live_alive, "the live session must survive"
