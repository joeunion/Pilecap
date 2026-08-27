"""The service door onto durable work: deterministic ids, start, and signal.

The property under test is the ordering guarantee a service depends on: calling
`start_workflow_on_commit` inside a transaction starts **nothing** until that
transaction commits, and starts the run once it does — and the same for the
signal that ends a wait. Everything runs against a real Temporal server (the
SDK's time-skipping test environment) — a stub could not tell the two moments
apart.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db import connections, transaction
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.asyncdb import run_async, run_db
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound, refusal_for
from apps.core.models import Organization, Tenant
from apps.core.tests import tree_census
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import (
    PLATFORM_SEGMENT,
    finish_run,
    record_run,
    signal_workflow,
    start_workflow,
    start_workflow_on_commit,
    workflow_id,
)
from apps.workflows.types import EchoOutput

# `transaction=True`: on_commit hooks only fire on a real commit, and the whole
# point of these tests is when that happens.
pytestmark = pytest.mark.django_db(transaction=True)

TASK_QUEUE = "djb-tests-on-commit"

#: The repository root, for the two tests that make a claim about the whole
#: tree rather than about one function.
REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_SERVICES = REPO_ROOT / "apps" / "workflows" / "services.py"

#: The worked platform id from ADR workflows-3: four segments, the first one
#: reserved. `workflow_id()` cannot build it, deliberately — it takes a tenant.
PLATFORM_RUN_ID = "platform:accounts:identity:workforce"


#: Re-exported so this module's two censuses read the way every other census in
#: the tree reads. This was the FIRST tolerant read and it was local; the
#: race then fired again in a census that had no local copy, so the tolerance —
#: and the whole argument for it — moved to `apps.core.tests.tree_census` and
#: this became one caller among a dozen.
source_lines = tree_census.source_lines


def test_workflow_id_is_the_house_shape(tenant: Tenant) -> None:
    built = workflow_id(tenant=tenant, app="example", noun="widget", key="42")
    assert built == f"{tenant.slug}:example:widget:42"


@pytest.mark.parametrize("bad", ["", "no-colons", "a:b:c", "acme:example:widget:", "a:b:c:d:e"])
def test_start_workflow_on_commit_refuses_an_id_that_is_not_the_house_shape(
    tenant: Tenant, bad: str
) -> None:
    with pytest.raises(ValueError):
        start_workflow_on_commit(workflow="EchoWorkflow", arg="x", tenant=tenant, id=bad)
    assert WorkflowRun.objects.count() == 0


def test_start_workflow_on_commit_refuses_another_tenants_id(
    tenant: Tenant, other_tenant: Tenant
) -> None:
    borrowed = workflow_id(tenant=other_tenant, app="example", noun="widget", key="1")
    with pytest.raises(ValueError):
        start_workflow_on_commit(workflow="EchoWorkflow", arg="x", tenant=tenant, id=borrowed)


@pytest.mark.asyncio
async def test_the_run_starts_on_commit_and_not_before(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering guarantee, both halves, against a real server."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async def connect() -> Client:
            return attach_interceptors(await Client.connect(target, namespace=namespace))

        # What the on-commit hook will reach for. It runs in whichever thread
        # commits, on its own event loop, so it connects its own client — the
        # same shape as production, where `get_client` dials the real server.
        monkeypatch.setattr(client_module, "get_client", connect)

        started = workflow_id(tenant=tenant, app="workflows", noun="echo", key="committed")
        abandoned = workflow_id(tenant=tenant, app="workflows", noun="echo", key="rolled-back")

        def exists(wanted: str) -> bool:
            async def look() -> bool:
                reader = await Client.connect(target, namespace=namespace)
                try:
                    await reader.get_workflow_handle(wanted).describe()
                except RPCError:
                    return False
                return True

            return run_async(look)

        def commit_one() -> None:
            with transaction.atomic():
                start_workflow_on_commit(
                    workflow="EchoWorkflow",
                    arg="hello",
                    tenant=tenant,
                    user=owner,
                    id=started,
                    task_queue=TASK_QUEUE,
                )
                # Still inside the transaction: nothing durable exists yet.
                assert exists(started) is False

        def roll_one_back() -> None:
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    start_workflow_on_commit(
                        workflow="EchoWorkflow",
                        arg="never",
                        tenant=tenant,
                        id=abandoned,
                        task_queue=TASK_QUEUE,
                    )
                    raise RuntimeError("the caller failed after asking for a workflow")

        await sync_to_async(commit_one, thread_sensitive=False)()
        await sync_to_async(roll_one_back, thread_sensitive=False)()

        # After the commit the run is on the server, with the id it was given.
        description = await env.client.get_workflow_handle(started).describe()
        assert description.status is WorkflowExecutionStatus.RUNNING
        assert description.id == started

        # The rolled-back transaction started nothing and left no row.
        with pytest.raises(RPCError):
            await env.client.get_workflow_handle(abandoned).describe()
        assert await run_db(WorkflowRun.objects.filter(workflow_id=abandoned).count) == 0

        # The visibility row for the committed one survived, with its run id.
        run = await run_db(WorkflowRun.objects.for_tenant(tenant).get, workflow_id=started)
        assert run.status == WorkflowRun.Status.RUNNING
        assert run.run_id != ""


# --- Signalling a run --------------------------------------------------------
#
# The other half of the seam. These tests are about the four walls
# `signal_workflow` puts up and the audit row it leaves; that the signal
# actually reaches a running workflow and ends its wait is proved end to end,
# against a real server, by `apps/example/tests/test_workflows.py` — the only
# place in the tree that holds a workflow with a signal handler.
#
# `recorded_workflow_starts` is the shared opt-in these need: the module runs
# with `transaction=True`, so every `on_commit` hook really fires, and the one
# thing a test cannot want out of it is the dial.


def a_running_run(tenant: Tenant, key: str = "1") -> WorkflowRun:
    """A run this tenant owns, recorded as `running`, through the service."""
    return record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=key),
        workflow_type="WidgetOnboardingWorkflow",
    )


def test_signal_workflow_refuses_an_id_that_is_not_this_tenants(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """The id wall, before anything is read: a borrowed prefix is a caller bug."""
    borrowed = workflow_id(tenant=other_tenant, app="example", noun="widget", key="1")
    with pytest.raises(ValueError):
        signal_workflow(tenant=tenant, actor=owner_actor, workflow_id=borrowed, signal="approve")


def test_signalling_a_run_that_is_not_there_is_not_found(
    tenant: Tenant, owner_actor: Actor
) -> None:
    missing = workflow_id(tenant=tenant, app="example", noun="widget", key="nobody")
    with pytest.raises(NotFound):
        signal_workflow(tenant=tenant, actor=owner_actor, workflow_id=missing, signal="approve")


def test_another_tenants_run_is_not_found_rather_than_forbidden(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """No existence oracle: the same answer as a run that never existed.

    The id has to be the *other* tenant's for their row to exist, so this proves
    the pair of walls together — a caller who guesses both the id shape and the
    slug still learns nothing, because they cannot get past the first one.
    """
    theirs = a_running_run(other_tenant)
    assert theirs.status == WorkflowRun.Status.RUNNING
    with pytest.raises(ValueError):
        signal_workflow(
            tenant=tenant,
            actor=owner_actor,
            workflow_id=theirs.workflow_id,
            signal="approve",
        )
    # And from the other side: acting *as* the other tenant, with an actor who
    # holds nothing there, is a refusal rather than a delivered signal.
    with pytest.raises(Forbidden):
        signal_workflow(
            tenant=other_tenant,
            actor=actor_for(user=owner_actor.user, tenant=other_tenant),
            workflow_id=theirs.workflow_id,
            signal="approve",
        )


def test_a_plain_member_of_the_tenant_may_signal(
    tenant: Tenant, member_actor: Actor, recorded_workflow_starts: None
) -> None:
    """The weakest rule in the tree, said out loud.

    A member may signal, because the question "may this person approve *that*
    widget" is the domain service's and has already been answered by the time
    anything gets here. This test is what makes that a decision rather than an
    accident.
    """
    run = a_running_run(tenant)
    signalled = signal_workflow(
        tenant=tenant, actor=member_actor, workflow_id=run.workflow_id, signal="approve"
    )
    assert signalled.pk == run.pk


def test_somebody_with_no_membership_may_not_signal(
    tenant: Tenant, nomad: User, recorded_workflow_starts: None
) -> None:
    run = a_running_run(tenant)
    with pytest.raises(Forbidden):
        signal_workflow(
            tenant=tenant,
            actor=actor_for(user=nomad, tenant=tenant),
            workflow_id=run.workflow_id,
            signal="approve",
        )


def test_signalling_the_same_run_twice_while_it_runs_is_fine(
    tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """A retried caller must not be refused: a signal is idempotent from here."""
    run = a_running_run(tenant)
    first = signal_workflow(
        tenant=tenant, actor=owner_actor, workflow_id=run.workflow_id, signal="approve"
    )
    second = signal_workflow(
        tenant=tenant, actor=owner_actor, workflow_id=run.workflow_id, signal="approve"
    )
    assert first.pk == second.pk == run.pk


def test_signalling_a_finished_run_is_a_conflict(
    tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """Told now, by the row, rather than by an RPC error nobody is watching."""
    run = a_running_run(tenant)
    finish_run(
        tenant=tenant,
        workflow_id=run.workflow_id,
        status=WorkflowRun.Status.COMPLETED,
    )
    with pytest.raises(Conflict):
        signal_workflow(
            tenant=tenant, actor=owner_actor, workflow_id=run.workflow_id, signal="approve"
        )


def test_a_signal_leaves_an_audit_row_naming_the_run(
    tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """`@service`, and therefore audited — the point of putting this in services."""
    run = a_running_run(tenant)
    AuditEntry.objects.all().delete()

    signal_workflow(tenant=tenant, actor=owner_actor, workflow_id=run.workflow_id, signal="approve")

    entry = AuditEntry.objects.for_tenant(tenant).get(action="workflows.signal_workflow")
    assert entry.outcome == "ok"
    assert entry.actor_user_id == owner_actor.user_id
    assert entry.object_id == run.pk
    # The two structural facts are readable; the signal's payload is not.
    assert entry.input["workflow_id"] == run.workflow_id
    assert entry.input["signal"] == "approve"


def test_a_refused_signal_is_audited_too(
    tenant: Tenant, member_actor: Actor, recorded_workflow_starts: None
) -> None:
    """A refusal is a fact about the tenant, and it is on the record."""
    run = a_running_run(tenant)
    finish_run(tenant=tenant, workflow_id=run.workflow_id, status=WorkflowRun.Status.FAILED)
    AuditEntry.objects.all().delete()

    with pytest.raises(Conflict):
        signal_workflow(
            tenant=tenant, actor=member_actor, workflow_id=run.workflow_id, signal="approve"
        )

    entry = AuditEntry.objects.for_tenant(tenant).get(action="workflows.signal_workflow")
    assert entry.outcome == "error"
    assert entry.error_code == "conflict"


@pytest.mark.asyncio
async def test_the_signal_goes_out_on_commit_and_not_before(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering guarantee again, for the signal half, against a real server.

    `EchoWorkflow` has no signal handler and does not need one: Temporal records
    a signal against a running execution whether or not the workflow declares a
    handler for it, and what is under test here is *when the client call
    happens* — never inside the caller's transaction, always after it commits.
    The signal that actually ends a wait is proved in
    `apps/example/tests/test_workflows.py`.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async def connect() -> Client:
            return attach_interceptors(await Client.connect(target, namespace=namespace))

        monkeypatch.setattr(client_module, "get_client", connect)

        started = workflow_id(tenant=tenant, app="workflows", noun="echo", key="signalled")

        def signals_in_history() -> int:
            async def count() -> int:
                reader = await Client.connect(target, namespace=namespace)
                handle = reader.get_workflow_handle(started)
                return len(
                    [
                        event
                        async for event in handle.fetch_history_events()
                        if event.HasField("workflow_execution_signaled_event_attributes")
                    ]
                )

            return run_async(count)

        def start_and_signal() -> None:
            try:
                with transaction.atomic():
                    start_workflow_on_commit(
                        workflow="EchoWorkflow",
                        arg="hello",
                        tenant=tenant,
                        user=owner,
                        id=started,
                        task_queue=TASK_QUEUE,
                    )
                # The run exists now; the signal is asked for inside a second
                # transaction and must not leave it.
                with transaction.atomic():
                    signal_workflow(
                        tenant=tenant,
                        actor=owner_actor,
                        workflow_id=started,
                        signal="approve",
                    )
                    assert signals_in_history() == 0
            finally:
                # This body ran on a pool thread, which has no request cycle to
                # hand back what it borrowed. Without this the connection
                # outlives the test and pytest-django cannot drop the database.
                connections.close_all()

        await sync_to_async(start_and_signal, thread_sensitive=False)()

        assert await sync_to_async(signals_in_history, thread_sensitive=False)() == 1


# --- Starting the same id twice ----------------------------------------------
#
# A deterministic id is what makes a retried service safe. Previously the
# second ask was refused: `record_run`'s `full_clean` hit the per-tenant unique
# constraint and the caller got `Invalid` — a refusal for the ordinary shape of
# a retry. ADR workflows-2 rules it an idempotent return instead, and these are
# its three answers plus the healing they buy.

# The clauses `record_run`'s docstring owes, one per answer. The contract is
# published prose, so a test greps it: a behaviour that changed without the
# docstring changing is a lie in the file everybody reads first.
CONTRACT_CLAUSES = (
    "running, and the same type",
    "running, and a different type",
    "already finished",
)


def test_the_docstring_states_all_three_answers() -> None:
    doc = " ".join((record_run.__doc__ or "").split())
    for clause in CONTRACT_CLAUSES:
        assert clause in doc, f"record_run's docstring does not state {clause!r}"
    assert "idempotent" in " ".join((start_workflow_on_commit.__doc__ or "").split())


@pytest.mark.asyncio
async def test_starting_the_same_id_twice_returns_the_same_row_and_starts_one_run(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry, end to end — one row, one execution, no refusal."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async def connect() -> Client:
            return attach_interceptors(await Client.connect(target, namespace=namespace))

        monkeypatch.setattr(client_module, "get_client", connect)

        wanted = workflow_id(tenant=tenant, app="workflows", noun="echo", key="asked-twice")

        def ask() -> WorkflowRun:
            try:
                with transaction.atomic():
                    return start_workflow_on_commit(
                        workflow="EchoWorkflow",
                        arg="hello",
                        tenant=tenant,
                        user=owner,
                        id=wanted,
                        task_queue=TASK_QUEUE,
                    )
            finally:
                connections.close_all()

        first = await sync_to_async(ask, thread_sensitive=False)()
        started = await env.client.get_workflow_handle(wanted).describe()
        second = await sync_to_async(ask, thread_sensitive=False)()

        # The same row, and only ever one of them.
        assert second.pk == first.pk
        assert await run_db(WorkflowRun.objects.filter(workflow_id=wanted).count) == 1

        # And one execution. The second start really reached Temporal and was
        # told the id was already live: `describe` answers with the *latest*
        # execution under an id, so a run id that has not moved is a second run
        # that was never created — and the history holds one start event, which
        # is what rules out a continue-as-new wearing the same id.
        handle = env.client.get_workflow_handle(wanted)
        description = await handle.describe()
        assert description.status is WorkflowExecutionStatus.RUNNING
        assert description.run_id == started.run_id
        starts = [
            event
            async for event in handle.fetch_history_events()
            if event.HasField("workflow_execution_started_event_attributes")
        ]
        assert len(starts) == 1

        row = await run_db(WorkflowRun.objects.for_tenant(tenant).get, workflow_id=wanted)
        assert row.status == WorkflowRun.Status.RUNNING
        assert row.run_id == description.run_id


@pytest.mark.asyncio
async def test_a_row_whose_run_never_started_is_healed_by_asking_again(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row landed, the process died before the client call. Re-drive it."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async def connect() -> Client:
            return attach_interceptors(await Client.connect(target, namespace=namespace))

        monkeypatch.setattr(client_module, "get_client", connect)

        wanted = workflow_id(tenant=tenant, app="workflows", noun="echo", key="never-started")

        # Planted: the visibility row, running, with no execution behind it.
        planted = await run_db(
            record_run, tenant=tenant, workflow_id=wanted, workflow_type="EchoWorkflow"
        )
        assert planted.run_id == ""
        with pytest.raises(RPCError):
            await env.client.get_workflow_handle(wanted).describe()

        def ask() -> WorkflowRun:
            try:
                with transaction.atomic():
                    return start_workflow_on_commit(
                        workflow="EchoWorkflow",
                        arg="hello",
                        tenant=tenant,
                        user=owner,
                        id=wanted,
                        task_queue=TASK_QUEUE,
                    )
            finally:
                connections.close_all()

        again = await sync_to_async(ask, thread_sensitive=False)()

        assert again.pk == planted.pk
        description = await env.client.get_workflow_handle(wanted).describe()
        assert description.status is WorkflowExecutionStatus.RUNNING
        row = await run_db(WorkflowRun.objects.for_tenant(tenant).get, workflow_id=wanted)
        assert row.run_id == description.run_id


def test_asking_for_an_id_whose_run_has_finished_is_a_conflict(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """Re-running finished work is a decision, not a retry."""
    run = a_running_run(tenant)
    finish_run(tenant=tenant, workflow_id=run.workflow_id, status=WorkflowRun.Status.COMPLETED)

    with pytest.raises(Conflict) as refused:
        start_workflow_on_commit(
            workflow="WidgetOnboardingWorkflow",
            arg=None,
            tenant=tenant,
            id=run.workflow_id,
        )

    # The code is registered, so a client can branch on it and a reader can look
    # up which layer decided and what to do about it.
    assert refused.value.code == "conflict"
    assert refusal_for(refused.value.code) is not None
    assert WorkflowRun.objects.filter(workflow_id=run.workflow_id).count() == 1


def test_asking_a_live_id_for_a_different_workflow_is_a_conflict(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The id is live and it is somebody else's work."""
    run = a_running_run(tenant)

    with pytest.raises(Conflict) as refused:
        start_workflow_on_commit(
            workflow="EchoWorkflow", arg="x", tenant=tenant, id=run.workflow_id
        )

    assert refused.value.code == "conflict"
    unchanged = WorkflowRun.objects.for_tenant(tenant).get(workflow_id=run.workflow_id)
    assert unchanged.type == "WidgetOnboardingWorkflow"
    assert unchanged.status == WorkflowRun.Status.RUNNING


def test_two_different_ids_are_still_two_runs(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The negative: idempotency is per id, not a blanket refusal to start twice."""
    one = start_workflow_on_commit(
        workflow="EchoWorkflow",
        arg="x",
        tenant=tenant,
        id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="one"),
    )
    two = start_workflow_on_commit(
        workflow="EchoWorkflow",
        arg="x",
        tenant=tenant,
        id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="two"),
    )
    assert one.pk != two.pk
    assert WorkflowRun.objects.for_tenant(tenant).count() == 2


def test_another_tenants_row_under_the_same_id_is_not_reused(
    tenant: Tenant, other_tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The tenant wall, on the new read: the lookup is scoped like every other."""
    theirs = record_run(
        tenant=other_tenant,
        workflow_id=f"{tenant.slug}:workflows:echo:shared",
        workflow_type="EchoWorkflow",
    )
    mine = start_workflow_on_commit(
        workflow="EchoWorkflow",
        arg="x",
        tenant=tenant,
        id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="shared"),
    )
    assert mine.pk != theirs.pk
    assert mine.tenant_id == tenant.pk


# --- The intent digest ---------------------------------------------------------
#
# A deterministic id makes a retry ask for the *same* run. Nobody had asked
# what happens when a caller asks for the same id with *different work*:
# `record_run` returned somebody else's row and `_start_recorded` swallowed
# `WorkflowAlreadyStartedError`, so the new intent was dropped in silence.
# ADR workflows-4 rules the answer a 2x2 over the run's input digest, computed
# inside the starters so no caller can opt out.


def test_a_changed_intent_under_a_live_id_is_refused(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The confirmed hole: a different arg under a live id is a second job."""
    wanted = workflow_id(tenant=tenant, app="workflows", noun="echo", key="changed-intent")
    first = start_workflow_on_commit(workflow="EchoWorkflow", arg="hello", tenant=tenant, id=wanted)

    with pytest.raises(Conflict) as refused:
        start_workflow_on_commit(workflow="EchoWorkflow", arg="goodbye", tenant=tenant, id=wanted)

    assert refused.value.code == "conflict"
    assert "different input" in refused.value.detail.lower()
    # The digest itself is a maintainer's fact and no longer on the wire.
    assert "digest" not in refused.value.detail.lower()
    # The live run is untouched: the refusal did not adopt the new intent.
    unchanged = WorkflowRun.objects.for_tenant(tenant).get(workflow_id=wanted)
    assert unchanged.pk == first.pk
    assert unchanged.input_digest == first.input_digest


# --- The on-commit hook is robust -----------------------------------------------
#
# Django runs the hooks a transaction registered in order, and a NON-robust hook
# that raises takes every hook after it down with it. The start's own hook talks
# to Temporal, which is the least reliable thing in the list — so an unreachable
# server used to cancel the invitation email registered behind it. `robust=True`
# contains the failure to the hook that had it (Django >= 4.2 semantics: robust
# protects the hooks AFTER this one from THIS one).


def test_a_failing_start_hook_does_not_cancel_the_hooks_behind_it(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable Temporal is a lost run, never a lost sibling."""
    from apps.workflows import services as workflow_services

    def unreachable(_coroutine_factory: object) -> None:
        raise RuntimeError("Temporal was unreachable when the hook fired")

    monkeypatch.setattr(workflow_services, "run_async", unreachable)

    ran: list[str] = []
    with transaction.atomic():
        start_workflow_on_commit(
            workflow="EchoWorkflow",
            arg="x",
            tenant=tenant,
            id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="robust"),
        )
        transaction.on_commit(lambda: ran.append("the sibling behind it"))

    assert ran == ["the sibling behind it"]


def test_the_declared_seams_are_the_only_on_commit_registrations_in_the_tree() -> None:
    """The survey of every `on_commit` registration in the tree, executable
    rather than pasted once and left to rot.

    `robust=True` is a per-registration decision, so "we fixed the on-commit
    hooks" is only true if these are all of them. A future registration
    anywhere under `apps/` fails this test and has to answer the question.

    `close_sockets_on_commit` is the third registration: revocation and
    erasure close the person's open sockets (ADR realtime-2 d), and the
    channel layer behind that call is the least reliable thing in the list
    now that Temporal has been contained — so it is `robust=True` for
    exactly the reason the two starters are, and the seam records what that
    costs in its own docstring. It is one entry and not two because every
    caller goes through one registration site, which is also what keeps this
    survey readable.

    That entry lives in `core`, not `accounts`, and did not add a fourth
    line: *authorization* withdrawal — a membership removed, a subtree
    re-parented — never reached an open socket, and those writes live in
    `core`, which may not import `accounts` (rule 7). A second
    `close_sockets` in `core` would have been two hand-kept copies of one
    act on a security seam. So the pair was promoted into `core.services`
    and `accounts` re-exports it. The survey is the check that this stayed a
    *move*: if a copy ever reappears in `accounts`, this list grows a fourth
    line and the copy has to answer for itself here.

    The fourth entry is a start's sibling. `start_replay` asks Temporal to
    reset a failed run, and that RPC is the same least-reliable thing every
    other entry here is about: registered on the caller's commit so a
    rolled-back replay asks for nothing, and `robust=True` so a Temporal
    that cannot be reached does not take the hooks queued behind it with it.
    The row is already committed as RUNNING, so the ask is not lost either —
    the reconciler that reads the row sweeps it.

    The fifth entry is the one that commits nothing. `cancel_run` asks
    Temporal to stop a running execution and writes no row field at all
    (ADR workflows-7), so it is the entry where "the ask is not lost" needs
    its own sentence: a cancel whose hook could not dial leaves a row that
    honestly still says `running`, which is the state the job is genuinely
    in. Nothing has to be swept, because nothing was claimed.

    The sixth entry is that fifth one's mirror image. `cancel_message` asks
    Temporal to stop a delivery run, so the RPC is the same least-reliable
    thing every entry here is about and it carries `robust=True` for the
    same reason: a Temporal that cannot be reached must not take the hooks
    queued behind it down with it. Where `cancel_run`
    commits nothing, this one commits everything first — the row is written
    `cancelled` inside the service's own transaction and the run is only
    *asked* afterwards. That ordering is what makes the ask impossible to lose
    rather than merely swept: a hook that could not dial leaves a row that is
    honestly cancelled, and the run it failed to stop wakes, re-enters
    `deliver_message`, reads a status outside `SENDABLE` and hands nothing to
    any transport. The row decides, not the run — and that belt is driven by
    `apps/comms/tests/test_cancel.py::test_the_delivery_edge_refuses_a_
    cancelled_row` rather than argued, because an entry in this survey
    claiming a belt it had not proven would be the survey vouching for prose.

    The survey matches a *registration* — a line that begins with the call —
    rather than any line mentioning it, because those two seams now explain
    themselves in prose and a docstring quoting the call is not a hook. The
    residual blind spot is a registration buried inside a larger expression,
    which nothing here does: `on_commit` returns `None`, so there is nothing to
    nest it for.
    """
    registrations = [
        (str(path.relative_to(REPO_ROOT)), text.strip())
        for path in sorted((REPO_ROOT / "apps").rglob("*.py"))
        if "tests" not in path.parts
        for text in source_lines(path)
        if text.strip().startswith("transaction.on_commit(")
    ]
    assert [where for where, _ in registrations] == [
        "apps/comms/services.py",
        "apps/core/services.py",
        "apps/workflows/services.py",
        "apps/workflows/services.py",
        "apps/workflows/services.py",
        "apps/workflows/services.py",
    ], registrations
    for where, text in registrations:
        assert "robust=True" in text, f"{where} registers a hook that can cancel its siblings"


# --- The rest of the 2x2, and the supersede -----------------------------------


@pytest.mark.asyncio
async def test_a_finished_run_asked_for_with_different_work_reopens_and_starts_again(
    tenant: Tenant, owner: User
) -> None:
    """The fourth quadrant, and the interlock the whole cycle turns on.

    Once a workflow closes its own row (ADR workflows-5), a deterministic id
    keyed on a row — `<tenant>:core:organization:<pk>` — would be *finished*
    forever after the first run, and the node could never be moved again. The
    supersede is what stops the id fossilising: different work under a
    **finished** id re-opens the row and starts a fresh execution, while
    identical work under it is still refused.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            wanted = workflow_id(tenant=tenant, app="workflows", noun="echo", key="superseded")

            first = await start_workflow(
                workflow="EchoWorkflow",
                arg="hello",
                tenant=tenant,
                user=owner,
                id=wanted,
                client=client,
                task_queue=TASK_QUEUE,
            )
            done: EchoOutput = await client.get_workflow_handle(
                wanted, result_type=EchoOutput
            ).result()
            assert done.message == "hello"
            closed = await run_db(WorkflowRun.objects.for_tenant(tenant).get, workflow_id=wanted)
            assert closed.status == WorkflowRun.Status.COMPLETED

            # Same work under a finished id: still a decision about a new key.
            with pytest.raises(Conflict):
                await start_workflow(
                    workflow="EchoWorkflow",
                    arg="hello",
                    tenant=tenant,
                    user=owner,
                    id=wanted,
                    client=client,
                    task_queue=TASK_QUEUE,
                )

            again = await start_workflow(
                workflow="EchoWorkflow",
                arg="goodbye",
                tenant=tenant,
                user=owner,
                id=wanted,
                client=client,
                task_queue=TASK_QUEUE,
            )
            second: EchoOutput = await client.get_workflow_handle(
                wanted, result_type=EchoOutput
            ).result()

    # One row throughout — re-opened, not duplicated — and a second execution.
    assert again.pk == first.pk
    assert again.input_digest != first.input_digest
    assert again.run_id != first.run_id
    assert again.started_at > first.started_at
    assert second.message == "goodbye"
    assert await run_db(WorkflowRun.objects.filter(workflow_id=wanted).count) == 1


def test_the_digest_is_the_starters_and_never_a_call_sites() -> None:
    """The grammar is not an optional parameter anybody can forget.

    Two halves. Neither starter takes a digest, so there is nothing to pass;
    and nothing under `apps/` passes one, so the ban is a fact about the tree
    rather than a convention. Tests are excluded from the scan because a test
    may legitimately plant a row with a digest on it, which is the opposite of
    a call site opting in.
    """
    for starter in (start_workflow, start_workflow_on_commit):
        assert "input_digest" not in inspect.signature(starter).parameters

    named = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path in sorted((REPO_ROOT / "apps").rglob("*.py"))
        if "tests" not in path.parts and "migrations" not in path.parts
        for lineno, text in enumerate(source_lines(path), start=1)
        if "input_digest=" in text and path != WORKFLOW_SERVICES
    ]
    assert named == [], f"a call site is naming the digest: {named}"


# --- The platform population -------------------------------------------------


@pytest.mark.asyncio
async def test_a_platform_run_is_recorded_and_no_tenant_door_can_see_it(
    tenant: Tenant, other_tenant: Tenant
) -> None:
    """ADR workflows-3, end to end: the deployment's own work gets a ledger row.

    Started with `tenant=None` under a `platform:` id, closed by the same
    activity every other run is closed by — which reads `for_platform()` rather
    than `for_tenant(None)`, and reports an empty tenant slug because that is
    what is true. Neither of the two tenants can see the row through the door
    they read everything else through.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow="EchoWorkflow",
                arg="deployment-wide",
                tenant=None,
                id=PLATFORM_RUN_ID,
                client=client,
                task_queue=TASK_QUEUE,
            )
            result: EchoOutput = await client.get_workflow_handle(
                run.workflow_id, result_type=EchoOutput
            ).result()

    assert run.tenant_id is None
    assert result.tenant_slug == ""

    on_platform = await run_db(
        lambda: list(WorkflowRun.objects.for_platform().values_list("workflow_id", flat=True))
    )
    assert on_platform == [PLATFORM_RUN_ID]

    def runs_visible_to(whose: Tenant) -> int:
        return WorkflowRun.objects.for_tenant(whose).count()

    for whose in (tenant, other_tenant):
        seen = await run_db(runs_visible_to, whose)
        assert seen == 0, f"{whose.slug} can see a platform run through for_tenant"

    closed = await run_db(lambda: WorkflowRun.objects.for_platform().get(pk=run.pk))
    assert closed.status == WorkflowRun.Status.COMPLETED
    assert closed.finished_at is not None


def test_the_platform_segment_and_a_tenant_are_mutually_exclusive(tenant: Tenant) -> None:
    """The fence runs both ways, which is what makes null a *declared* population."""
    borrowed = workflow_id(tenant=tenant, app="accounts", noun="identity", key="workforce")

    with pytest.raises(ValueError):
        start_workflow_on_commit(workflow="EchoWorkflow", arg="x", tenant=None, id=borrowed)
    with pytest.raises(ValueError):
        start_workflow_on_commit(
            workflow="EchoWorkflow", arg="x", tenant=tenant, id=PLATFORM_RUN_ID
        )

    assert PLATFORM_SEGMENT == "platform"
    assert WorkflowRun.objects.count() == 0


# --- The id is required, on both paths -----------------------------------------


def test_start_workflow_declares_its_id_required(tenant: Tenant) -> None:
    """The `uuid4` default is gone from the signature, and cannot come back."""
    from apps.workflows import services as workflow_services

    parameter = inspect.signature(start_workflow).parameters["id"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    # The import left the module too, so there is no `uuid4` in scope for a
    # refactor to reach for. (The prose still names it; the namespace does not.)
    assert "uuid4" not in vars(workflow_services)

    # And the signature is load-bearing, not decorative: omitting it refuses
    # before a coroutine is even created. `Any` rather than a type: ignore —
    # the call is deliberately wrong and mypy is right about it.
    starter: Any = start_workflow
    with pytest.raises(TypeError, match="id"):
        starter(workflow="EchoWorkflow", arg="x", tenant=tenant, client=None)


@pytest.mark.asyncio
async def test_the_async_path_checks_the_id_exactly_as_the_sync_path_does(
    tenant: Tenant,
) -> None:
    """Rule 18's async escape, closed at the code as well as at the check."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        for bad in ("no-colons", "a:b:c", "globex:workflows:echo:1"):
            with pytest.raises(ValueError):
                await start_workflow(
                    workflow="EchoWorkflow",
                    arg="x",
                    tenant=tenant,
                    id=bad,
                    client=client,
                    task_queue=TASK_QUEUE,
                )

    assert await run_db(WorkflowRun.objects.count) == 0


# --- The hat agrees with the tenant --------------------------------------------


def test_a_start_under_another_tenants_hat_is_refused_and_writes_no_row(
    tenant: Tenant, other_root_org: Organization
) -> None:
    """The seam that stamps the hat is the seam that has to check it."""
    with pytest.raises(ValueError):
        start_workflow_on_commit(
            workflow="EchoWorkflow",
            arg="x",
            tenant=tenant,
            org=other_root_org,
            id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="wrong-hat"),
        )
    assert WorkflowRun.objects.count() == 0


def test_a_platform_run_may_not_wear_a_hat(tenant: Tenant, root_org: Organization) -> None:
    """A run that acts for no tenant acts for no part of one either."""
    with pytest.raises(ValueError):
        start_workflow_on_commit(
            workflow="EchoWorkflow", arg="x", tenant=None, org=root_org, id=PLATFORM_RUN_ID
        )
    assert WorkflowRun.objects.count() == 0


def test_a_tenant_wide_run_with_no_hat_is_still_legal(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The negative: `org=None` is the flat product and every platform workflow."""
    run = start_workflow_on_commit(
        workflow="EchoWorkflow",
        arg="x",
        tenant=tenant,
        org=None,
        id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="no-hat"),
    )
    assert run.tenant_id == tenant.pk


def test_the_tenants_own_hat_is_accepted(
    tenant: Tenant, root_org: Organization, recorded_workflow_starts: None
) -> None:
    run = start_workflow_on_commit(
        workflow="EchoWorkflow",
        arg="x",
        tenant=tenant,
        org=root_org,
        id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="right-hat"),
    )
    assert run.tenant_id == tenant.pk


def test_the_on_commit_census_tolerates_a_file_that_vanishes_at_open() -> None:
    """The falsifier for the tolerant read this module has carried.

    It was the FIRST tolerant read in the tree and it was never driven — which is
    part of why the class stayed open: an untested tolerance is a claim. The
    plant registers no hook, so passing means it was skipped.
    """
    with tree_census.vanishing_source_file() as planted:
        for path in sorted((REPO_ROOT / "apps").rglob("*.py")):
            source_lines(path)
        assert not planted.exists(), "the census never opened the plant — this drove nothing"
