"""Activities: where a workflow is allowed to touch the world.

Everything non-deterministic lives here — the ORM, the network, the clock — and
every activity calls a service rather than a model. `ACTIVITIES` is what
`apps.workflows.client` discovers; an app adds an activity by adding it to its
own list, never by editing the worker.

**Activities are plain `def`.** That is the convention and this is the reference
for it: the ORM is synchronous, and a sync activity runs in the worker's thread
pool where a synchronous query belongs, instead of being wrapped in
`sync_to_async` to be handed back to a thread anyway. An activity is `async def`
only when the I/O it does is genuinely async, and then its docstring says why.

The one thing a sync activity owes the pool it runs in: `close_old_connections`
at both ends. There is no request cycle out here to do it, and a connection left
open per thread is a connection leaked forever.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from importlib import import_module
from typing import Any

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.utils import timezone
from temporalio import activity
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    WorkflowExecutionStatus,
)
from temporalio.service import RPCError, RPCStatusCode

from apps.core import mail
from apps.core.actor import system_actor
from apps.core.asyncdb import run_async
from apps.core.exceptions import NotFound
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.schedules import ScheduleDeclaration
from apps.core.services import apply_organization_move
from apps.workflows import services
from apps.workflows.context import platform_context, workflow_context
from apps.workflows.models import WorkflowRun
from apps.workflows.services import finish_run
from apps.workflows.types import (
    MarkRunFinished,
    MoveOrganization,
    PurgeFinishedRuns,
    ReconcileRuns,
    SendEmail,
)

log = get_logger(__name__)

# --- The reconciler's two numbers (ADR workflows-5) --------------------------
#
# **`RECONCILE_AFTER`** is how old a `RUNNING` row with an empty `run_id` must
# be before the sweep believes nobody is going to start it. The row is written
# inside the caller's transaction and the execution is started on commit, so
# the honest gap is milliseconds; fifteen minutes is not a guess at that gap but
# a wide margin around a worker that is slow, paused or mid-deploy. Sweeping a
# live row would be worse than sweeping late, so the margin errs long.
#
# **`RECONCILE_EVERY`** is the sweep cadence, and it is the sibling of
# `apps.events.activities.RECONCILE_EVERY` on purpose: the two reconcilers in
# this tree should be read as one shape with two subjects.
#
# Module constants rather than settings, exactly as the events relay's pair
# are: a deployment does not tune the shape of its own recovery.
RECONCILE_AFTER = timedelta(minutes=15)
RECONCILE_EVERY = timedelta(minutes=5)

# The sweep's schedule and the runs it starts, namespaced by task queue for the
# reason ADR events-2 gives for the purge: a schedule id is global to the
# Temporal namespace, so a constant one would make every worker's startup a
# fight over where the sweep runs. `system:` rather than `platform:` because
# these runs carry no `WorkflowRun` row at all — `platform:` is the reserved
# first segment of the run *ledger*'s null population (ADR workflows-3), and a
# schedule-started run is not in the ledger to be confused with one.
RECONCILE_SCHEDULE_PREFIX = "workflows-reconcile-runs"
RECONCILE_WORKFLOW_PREFIX = "system:workflows:reconcile"

#: The name the workflow is discovered under, spelled once.
RECONCILE_WORKFLOW = "ReconcileRunsWorkflow"


# --- The two purges (ADR core-13, house rule 31) -----------------------------
#
# Two sweeps, one cadence, and the same id discipline the reconciler above
# already follows: both prefixes are suffixed by task queue, because a schedule
# id is global to the Temporal namespace and a constant one would make every
# worker's startup a fight over where the sweep runs (ADR events-2; observed
# live in production).
#
# **`system:` and not `platform:`**, for the reason spelled out above the
# reconciler: `platform:` is the reserved first segment of the run LEDGER's
# null population (ADR workflows-3), and these runs carry no `WorkflowRun` row
# at all — they declare `owns_no_run = True`. A schedule-started run wearing a
# `platform:` id would be indistinguishable from a ledger row that lost its
# tenant. An early draft wrote these as `platform:` ids; the tree's own
# precedent is `system:`, and following the sibling is what keeps one reader
# able to tell the two populations apart.
#
# **Daily, both of them.** Retention is a window measured in months and expired
# sessions are worthless the moment they expire, so an hour late costs nothing
# either way — and `SKIP` on overlap means a sweep that is still running when
# the next is due surfaces as a skipped tick rather than as two deletes racing.
PURGE_RUNS_SCHEDULE_PREFIX = "workflows-purge-finished-runs"
PURGE_RUNS_WORKFLOW_PREFIX = "system:workflows:purge-runs"
PURGE_RUNS_WORKFLOW = "PurgeFinishedRunsWorkflow"

PURGE_SESSIONS_SCHEDULE_PREFIX = "workflows-purge-expired-sessions"
PURGE_SESSIONS_WORKFLOW_PREFIX = "system:workflows:purge-sessions"
PURGE_SESSIONS_WORKFLOW = "PurgeExpiredSessionsWorkflow"

PURGE_EVERY = timedelta(hours=24)


@activity.defn(name="mark_run_finished")
def mark_run_finished(payload: MarkRunFinished) -> str:
    """Close out a run's visibility row, and report the tenant it acted for.

    The tenant is not an argument: it arrives on the workflow's headers and is
    unpacked into a contextvar by the interceptor, which is what makes it
    impossible for a caller to write into somebody else's tenant by passing the
    wrong id.

    Idempotent: closing an already-closed run rewrites the same status, and a
    run this tenant cannot see returns None rather than touching anything.

    **The one activity in this app that reads `platform_context()`**, and the
    reason the valve exists: it closes rows for a tenant's runs and for the
    platform's alike (ADR workflows-3), so it is the single caller that
    legitimately may have no tenant. `finish_run` routes the read on exactly
    that, and the empty slug it returns is the honest answer for a run nobody
    owns rather than a failure to look.
    """
    close_old_connections()
    try:
        tenant, _user_id, _org = platform_context()
        finish_run(
            tenant=tenant,
            workflow_id=payload.workflow_id,
            status=payload.status,
            error=payload.error,
        )
        return tenant.slug if tenant is not None else ""
    finally:
        close_old_connections()


@activity.defn(name="send_email")
def send_email(payload: SendEmail) -> int:
    """Render one email and hand it to the configured backend.

    The only place in the tree that talks to a mail host. It is an activity
    because that is where I/O belongs, and because Temporal's retries are what
    turn "the SMTP server refused the connection" from a lost invitation into a
    second attempt in a few seconds.

    **Honest about idempotency**: Temporal guarantees an activity runs *at least*
    once, and there is no way to un-send an email, so a retry after a partial
    failure can deliver a second copy. That is the correct trade for this
    payload — a duplicate invitation is a mild annoyance and a missing one is a
    person who never joins — and it is why the id a service starts this with is
    deterministic (`core.mail.send_mail`'s `key`): the *service* being retried
    starts one run, not two, which is where the real duplication risk was.

    The tenant is not an argument; it arrives on the workflow's headers. It is
    read here so the log line can say whose email this was, and for no other
    reason: the recipients are already in the payload.
    """
    close_old_connections()
    try:
        tenant, _user_id, _org = workflow_context()
        return mail.send_now(
            to=payload.to,
            subject=payload.subject,
            template=payload.template,
            context=payload.context,
            tenant=tenant,
        )
    finally:
        close_old_connections()


@activity.defn(name="rewrite_organization_paths")
def rewrite_organization_paths(payload: MoveOrganization) -> str:
    """Re-parent a node and rewrite its subtree's paths. Reports the new path.

    The activity half of `core.services.move_organization`: it restores the
    principal, reads both rows **through the tenant's own manager**, and calls
    the service that takes the locks and does the writing. It writes nothing
    itself (house rule 10) and it takes no tenant argument — the tenant arrives
    on the workflow's headers, which is what makes it impossible for a payload
    to name somebody else's tree.

    It acts as the **system**: the person who asked for the move was authorized
    when `move_organization` ran, days or seconds ago, and attributing the
    rewrite itself to them would make the audit trail read plausibly and be
    false about when it happened. The acting hat still rides along, so the audit
    row says which part of the network the move was ordered from.

    A node that has vanished while the run waited raises `NotFound`; Temporal
    retries, it keeps raising, and the run fails saying so — which is the honest
    outcome rather than quietly succeeding at nothing.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        scoped = Organization.objects.for_tenant(tenant)
        organization = scoped.filter(pk=payload.organization_id).first()
        new_parent = scoped.filter(pk=payload.new_parent_id).first()
        # The tenant is no longer part of this question: `workflow_context()`
        # refuses a run that stamped none, so the only thing left to be gone is
        # one of the two nodes.
        if organization is None or new_parent is None:
            raise NotFound("That organization, or the parent it was moving to, is gone.")
        moved = apply_organization_move(
            tenant=tenant,
            organization=organization,
            new_parent=new_parent,
            actor=system_actor(tenant, org),
        )
        return str(moved.path)
    finally:
        close_old_connections()


# --- The reconciler: rows that were promised an execution and never got one ---


def reconcile_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's run sweep. One per task queue."""
    return f"{RECONCILE_SCHEDULE_PREFIX}:{task_queue}"


def reconcile_workflow_id(task_queue: str) -> str:
    """The id of the run the sweep's schedule starts. Per queue, like the purge.

    The **prefix** Temporal is given; the server appends the scheduled time, so
    an actual run is `system:workflows:reconcile:<queue>-2026-08-21T14:13:48Z`.
    The part this repository chooses is deterministic, which is what house rule
    18 is about.
    """
    return f"{RECONCILE_WORKFLOW_PREFIX}:{task_queue}"


def reconcile_after_seconds() -> int:
    """`RECONCILE_AFTER` as the integer that crosses a Temporal history."""
    return int(RECONCILE_AFTER.total_seconds())


def stranded_runs(*, older_than: datetime) -> list[WorkflowRun]:
    """Every population's rows that claim to be running and name no execution.

    **Read through each population's own path**, never through a bare manager
    (house rule 8): one `for_tenant` per tenant, then `for_platform()` for the
    rows no tenant owns. That is one query per tenant on a five-minute cadence,
    which is the honest cost of a rule that says a scoped model is read scoped —
    and the alternative, a single unscoped scan with an override, would be the
    one read in the tree that is deliberately not narrowed.

    `run_id=""` is the whole signal. A row gets its `run_id` from the client
    call, so an empty one past the threshold means the row committed and the
    process died before it dialled — the exact gap this activity closes.
    """
    found: list[WorkflowRun] = []
    for tenant in Tenant.objects.all().iterator():
        found.extend(
            WorkflowRun.objects.for_tenant(tenant).filter(
                status=WorkflowRun.Status.RUNNING,
                run_id="",
                started_at__lt=older_than,
            )
        )
    found.extend(
        # rule-8: the platform population is the declared null-tenant one (ADR
        # workflows-3); for_tenant stays fail-closed and can never reach it.
        WorkflowRun.objects.for_platform().filter(
            status=WorkflowRun.Status.RUNNING,
            run_id="",
            started_at__lt=older_than,
        )
    )
    return found


#: What Temporal says about an execution, reduced to what this sweep decides on:
#: `None` means the server has no such execution, a status means it has one.
_Outcome = WorkflowExecutionStatus | None


async def describe_execution(client: Client, workflow_id: str) -> _Outcome:
    """Ask the server what became of this id. Raises on anything but absence.

    **A describe error is not an absence**, and the difference is the whole
    safety of this sweep: `NOT_FOUND` means Temporal is certain there is no such
    execution, while a timeout or an unavailable server means it did not answer.
    Marking a row `failed` on the second one would close a live run because the
    network hiccuped, so only `NOT_FOUND` becomes `None` and every other
    `RPCError` propagates to the caller, which skips that row.
    """
    try:
        description = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as error:
        if error.status is RPCStatusCode.NOT_FOUND:
            return None
        raise
    return description.status


#: How a **closed** execution's status becomes the row's word. Everything not
#: named here is `failed`, which is the honest default for a residue of closed
#: states nobody has a word for yet (`TERMINATED`, `TIMED_OUT`,
#: `CONTINUED_AS_NEW`) — the row says failed and names the real status in
#: `error`, so nothing is lost.
#:
#: **`CANCELED` is an added entry** (ADR workflows-7). It used to
#: fall through to `failed`, which meant a run somebody deliberately stopped was
#: indistinguishable, months later, from one that broke — and the cancel door
#: would have shipped a ledger that could not say what had happened to the thing
#: it stopped. Temporal spells it with one `l` and this tree spells it with two;
#: this dict and `workflows._finish` are the only two places the two spellings
#: meet.
CLOSED_AS: dict[WorkflowExecutionStatus, str] = {
    WorkflowExecutionStatus.COMPLETED: WorkflowRun.Status.COMPLETED,
    WorkflowExecutionStatus.CANCELED: WorkflowRun.Status.CANCELLED,
}

NEVER_STARTED = (
    "This run was recorded and never started: no execution exists under its id, and the row "
    "is older than the reconciler's threshold. The process died between the commit that wrote "
    "the row and the client call that would have started the work."
)


@activity.defn(name="reconcile_runs")
def reconcile_runs(window: ReconcileRuns) -> int:
    """Close the rows whose execution was promised and never started.

    `start_workflow_on_commit` writes the visibility row inside the caller's
    transaction and dials Temporal on commit. A process that dies in that gap —
    or a dial that fails, now that the hook is `robust=True` and no longer takes
    its siblings down with it — leaves a row saying RUNNING with an empty
    `run_id` and **nothing that would ever notice**. This is what notices.

    For each stranded row the server decides, and this activity only writes the
    answer down:

    * **no such execution** — `failed`, with an error naming never-started. This
      is also what mops the historical rows left behind, from before the
      platform app's own workflows closed their own runs.
    * **an execution that has closed** — the row is closed from the real
      outcome, through `CLOSED_AS`: `completed` for a completed one,
      **`cancelled` for one somebody stopped** (ADR workflows-7 — the entry that
      makes the cancel door's ledger honest for a run that never reached its own
      finish seam), and `failed` for the rest, with the real status named in
      `error`. The row was behind; it is not wrong now.
    * **an execution still running** — left alone. The hook ran late, the row is
      honest, and there is nothing to reconcile.
    * **a describe that errored** — skipped, and logged. An unanswered question
      is not a `no`.

    Returns how many rows it closed, which is the operator's question: a sweep
    that keeps closing rows every cycle is a deployment losing its on-commit
    hooks, and one that closes none is the healthy steady state.

    It is a plain `def` like every other activity here, and it reaches the async
    client through `apps.core.asyncdb.run_async` — the same seam the on-commit
    hook uses to dial from a synchronous caller, for the same reason: this runs
    on a worker thread that has no event loop of its own.
    """
    close_old_connections()
    try:
        cutoff = timezone.now() - timedelta(seconds=window.after_seconds)
        stranded = stranded_runs(older_than=cutoff)
        if not stranded:
            return 0

        async def ask() -> dict[str, _Outcome]:
            from apps.workflows.client import get_client

            client = await get_client()
            answers: dict[str, _Outcome] = {}
            for row in stranded:
                try:
                    answers[row.workflow_id] = await describe_execution(client, row.workflow_id)
                except RPCError as error:
                    log.warning(
                        "workflows.reconcile.skipped",
                        workflow_id=row.workflow_id,
                        status=str(error.status),
                    )
            return answers

        answers = run_async(ask)
        closed = 0
        for row in stranded:
            if row.workflow_id not in answers:
                continue
            outcome = answers[row.workflow_id]
            if outcome is WorkflowExecutionStatus.RUNNING:
                continue
            if outcome is None:
                finish_run(
                    tenant=row.tenant,
                    workflow_id=row.workflow_id,
                    status=WorkflowRun.Status.FAILED,
                    error=NEVER_STARTED,
                )
            else:
                status = CLOSED_AS.get(outcome, WorkflowRun.Status.FAILED)
                finish_run(
                    tenant=row.tenant,
                    workflow_id=row.workflow_id,
                    status=status,
                    # A run that ended the way it was asked to — completed, or
                    # stopped on purpose — has nothing to explain. Only the
                    # residue does.
                    error=(
                        ""
                        if status != WorkflowRun.Status.FAILED
                        else f"The execution closed as {outcome.name}."
                    ),
                )
            closed += 1
        log.info("workflows.reconcile.swept", status=str(closed))
        return closed
    finally:
        close_old_connections()


@activity.defn(name="purge_finished_runs")
def purge_finished_runs(window: PurgeFinishedRuns) -> int:
    """Apply the run ledger's retention window. Returns how many rows went.

    The clock read is here and not in the workflow, which is the whole reason
    this is an activity: `workflows.py` may not call `timezone.now()` (house
    rule 9), so the window arrives as a number of seconds and the subtraction
    happens once, out here, where every non-deterministic thing in this app
    already lives.

    The delete itself is `services.purge_finished_runs` — this is the door and
    the service owns the write (house rule 10). What that service will and will
    not delete, and why `failed` and `running` rows survive every window, is on
    the service and on `WorkflowRun.lifecycle`; this activity's only opinion is
    what "before" means.

    Idempotent by construction: it deletes by age, so a retried attempt removes
    nothing the first one already took.
    """
    close_old_connections()
    try:
        before = timezone.now() - timedelta(seconds=window.retention_seconds)
        removed = services.purge_finished_runs(before=before)
        log.info("workflows.purge.runs", status=str(removed))
        return removed
    finally:
        close_old_connections()


@activity.defn(name="purge_expired_sessions")
def purge_expired_sessions() -> int:
    """Clear expired sessions. Returns how many rows were eligible when it ran.

    **This is the callable `apps/workflows/lifecycle.py` declares as
    `django_session`'s sweeper**, and it is an activity rather than a service on
    purpose. Every other purge in this tree writes through a `@service` because
    the rows belong to an app in this tree; these rows belong to
    `django.contrib.sessions`, and the only supported way to remove one is the
    **configured session engine's own** `SessionStore.clear_expired()`. Reaching
    past it to `Session.objects.filter(...).delete()` would hard-code the
    database backend into a deployment that may be running a different one, and
    wrapping somebody else's storage backend in a `@service` would claim an
    ownership of the table that the third-party declaration is careful not to
    claim. So: the engine's own door, called from the layer that is allowed to
    do I/O.

    The count is read **before** the clear, off the table this app declared the
    lifecycle for. It is an operator's signal — the same job `reconcile_runs`'s
    return value does — and it is honest about its own edges: a session that
    expires between the count and the clear is removed and not counted (an
    undercount, which is the safe direction), and a deployment on a cache- or
    cookie-backed engine has no `django_session` rows to count, which is also
    the deployment where the declaration in `lifecycle.py` would not apply.

    Idempotent by construction: expiry is a property of each row, so a second
    sweep in the same minute clears nothing the first one left.
    """
    close_old_connections()
    try:
        eligible = Session.objects.filter(expire_date__lt=timezone.now()).count()
        import_module(settings.SESSION_ENGINE).SessionStore.clear_expired()
        log.info("workflows.purge.sessions", status=str(eligible))
        return eligible
    finally:
        close_old_connections()


# --- The schedule ------------------------------------------------------------


def reconcile_schedule(task_queue: str) -> Schedule:
    """The sweep's schedule, as a value so a test can read it.

    A Temporal Schedule and not a cron entry (`architecture.md`): the sweep is
    deployed with the code, its last run is visible where the runs are, and a
    missed one is a fact rather than a silence. `SKIP` on overlap for the reason
    the purge and the outbox relay have it — two sweeps at once would read the
    same stranded rows, and while closing a row twice is harmless there is no
    reason to pay for the race.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            RECONCILE_WORKFLOW,
            ReconcileRuns(after_seconds=reconcile_after_seconds()),
            id=reconcile_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=RECONCILE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The run sweep, declared as data (ADR platform-lifecycle-1).
#:
#: An id builder and a `Schedule` value, and nothing about how either becomes
#: real: whether this is a durable Temporal Schedule the server owns or a run
#: this worker starts on a timer is the engine's decision, taken from the
#: deployment's declared lifetime class. This app used to carry its own
#: create-or-update here, which is how it also carried the unexamined assumption
#: that a declared machine is always a durable object.
#:
#: There is no legacy id to drop; this schedule has never existed un-suffixed.
RECONCILE_RUNS = ScheduleDeclaration(
    name="workflows.reconcile-runs",
    schedule_id=reconcile_schedule_id,
    schedule=reconcile_schedule,
    log_prefix="workflows",
)


def purge_runs_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's ledger purge. One per task queue."""
    return f"{PURGE_RUNS_SCHEDULE_PREFIX}:{task_queue}"


def purge_runs_workflow_id(task_queue: str) -> str:
    """The id of the run the ledger purge's schedule starts. Per queue.

    The **prefix** Temporal is given; the server appends the scheduled time, so
    an actual run is `system:workflows:purge-runs:<queue>-2026-08-24T03:00:00Z`.
    The part this repository chooses is deterministic, which is what house rule
    18 is about.
    """
    return f"{PURGE_RUNS_WORKFLOW_PREFIX}:{task_queue}"


def purge_sessions_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's session sweep. One per task queue."""
    return f"{PURGE_SESSIONS_SCHEDULE_PREFIX}:{task_queue}"


def purge_sessions_workflow_id(task_queue: str) -> str:
    """The id of the run the session sweep's schedule starts. Per queue."""
    return f"{PURGE_SESSIONS_WORKFLOW_PREFIX}:{task_queue}"


def finished_run_retention_seconds() -> int:
    """`services.FINISHED_RUN_RETENTION` as the integer that crosses a history.

    Read here rather than in the workflow, and passed on the schedule's action,
    so an operator can see the window in the Temporal UI and so a change to the
    constant reaches a running deployment the next time the engine writes the
    action — instead of being frozen into a schedule created months ago.
    """
    return int(services.FINISHED_RUN_RETENTION.total_seconds())


def purge_runs_schedule(task_queue: str) -> Schedule:
    """The ledger purge's schedule, as a value so a test can read it.

    A Temporal Schedule and not a cron entry (`architecture.md`): the sweep is
    deployed with the code, its last run is visible where the runs are, and a
    missed one is a fact rather than a silence. `SKIP` on overlap for the reason
    every other sweep in this tree has it — two purges at once would read the
    same rows, and while deleting by age twice is harmless there is no reason to
    pay for the race.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            PURGE_RUNS_WORKFLOW,
            PurgeFinishedRuns(retention_seconds=finished_run_retention_seconds()),
            id=purge_runs_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PURGE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def purge_sessions_schedule(task_queue: str) -> Schedule:
    """The session sweep's schedule, as a value so a test can read it.

    The action carries **no argument**, which is the workflow's own shape: a
    session's expiry is on the row, so there is no window for an operator to
    read off the schedule and none to get stale.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            PURGE_SESSIONS_WORKFLOW,
            id=purge_sessions_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PURGE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The ledger's own retention window, declared as data (ADR
#: platform-lifecycle-1) and **the second half of `WorkflowRun.lifecycle`**.
#: Rule 31 walks from that declaration's `purged_by` to this entry; the two are
#: one change and the rule refuses either on its own.
#:
#: No legacy id: this schedule has never existed un-suffixed.
PURGE_FINISHED_RUNS = ScheduleDeclaration(
    name="workflows.purge-finished-runs",
    schedule_id=purge_runs_schedule_id,
    schedule=purge_runs_schedule,
    log_prefix="workflows",
)

#: The session sweep, declared as data — **the second half of
#: `apps/workflows/lifecycle.py`'s `django_session` declaration**, and the thing
#: that closes the gap: until this line, nothing in any deployment path
#: cleared an expired session.
#:
#: No legacy id: there has never been a session schedule of any name to clean up,
#: which is precisely the finding.
PURGE_EXPIRED_SESSIONS = ScheduleDeclaration(
    name="workflows.purge-expired-sessions",
    schedule_id=purge_sessions_schedule_id,
    schedule=purge_sessions_schedule,
    log_prefix="workflows",
)


# --- The two registries this app exports -------------------------------------


ACTIVITIES: list[Callable[..., Any]] = [
    mark_run_finished,
    send_email,
    rewrite_organization_paths,
    reconcile_runs,
    purge_finished_runs,
    purge_expired_sessions,
]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration per periodic machine this app owns.
SCHEDULES: list[ScheduleDeclaration] = [
    RECONCILE_RUNS,
    PURGE_FINISHED_RUNS,
    PURGE_EXPIRED_SESSIONS,
]
