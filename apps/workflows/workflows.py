"""Workflow definitions — deterministic code only.

No ORM, no network, no clock, no randomness is imported or called here; all of
it lives in `activities.py`. That is house rule 9, and it is why the activity is
invoked **by name** rather than by importing the function: importing
`activities` would drag the ORM into a module that has to replay identically
years from now.

`WORKFLOWS` is what `config.temporal` discovers. An app adds a workflow by
adding it to its own list; nothing edits the worker.

**Every workflow here closes its own `WorkflowRun` row, and closes it last.**
That is `_finish` below, and it is a debt this app owed: every *domain* app's
workflow marked its run finished, while the platform app's own `SendEmail` and
`MoveOrganization` never did — so their rows said RUNNING forever, and
`EchoWorkflow` marked itself *completed before doing anything*, which is the
wrong shape published as the template's worked example. A reconciler that
sweeps dead runs cannot tell a lying row from a live one, which is why this had
to land in the same rung as the digest (ADR workflows-5).

**And it closes it with one of three words, not two** (ADR workflows-7):
`completed`, `failed`, or `cancelled` when somebody asked the run to stop. The
third one is what makes `POST /runs/{id}/cancel/` honest — the cancel service
writes no row field at all, so this seam and the reconciler are the only two
places a run is ever recorded as stopped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from apps.workflows.types import (
    EchoOutput,
    MarkRunFinished,
    MoveOrganization,
    PurgeFinishedRuns,
    ReconcileRuns,
    SendEmail,
)

# Closing the row is one short database write in an activity. It is given its
# own timeout rather than the work's, because "the work took an hour" and "the
# bookkeeping hung" are different failures.
FINISH_TIMEOUT = timedelta(seconds=30)

# Bounded, for the reason the four domain apps already bound theirs: a
# bookkeeping activity that retried for ever would outlive the thing it is
# bookkeeping for, holding a completed piece of work open against a database
# that is not coming back. Five attempts, then the run fails saying so and
# the reconciler is what sweeps the row.
FINISH_RETRY = RetryPolicy(maximum_attempts=5)

# The third terminal word (ADR workflows-7), as a literal, because this module
# may not import `models` (house rule 9) and `WorkflowRun.Status.CANCELLED` is
# what it has to equal. `apps/workflows/tests/test_workflows.py` pins the two
# together, which is the seam that would otherwise drift silently: a typo here
# writes a status no door can filter on and nothing else complains.
CANCELLED = "cancelled"

# How far `_reason` walks a `__cause__` chain before it stops. Three links is
# wrapper, activity error, the activity's own complaint — which is all of it.
_REASON_DEPTH = 3

# How long one attempt at handing the message to the mail host may take, and how
# long the whole thing — every retry included — may go on for. The second is the
# reason this is a workflow at all: a mail host that is down for twenty minutes
# costs nothing, and an address that will never accept mail stops being retried
# after an hour instead of at midnight.
ATTEMPT_TIMEOUT = timedelta(seconds=30)
DELIVERY_DEADLINE = timedelta(hours=1)


def _reason(failure: BaseException) -> str:
    """The failure and what caused it, as one line for the row's `error`.

    Temporal wraps an activity's own error in an `ActivityError` whose message
    is "Activity task failed" — true, and useless to whoever is reading the run
    row six weeks later. Walking `__cause__` puts the activity's actual
    complaint on the row. Bounded, because a cause chain is somebody else's
    data structure; deterministic, because it reads nothing but the exception
    it was handed.
    """
    said: list[str] = []
    seen: BaseException | None = failure
    while seen is not None and len(said) < _REASON_DEPTH:
        said.append(f"{type(seen).__name__}: {seen}")
        seen = seen.__cause__
    return " <- ".join(said)


async def _mark(status: str, error: str = "") -> str:
    """Invoke `mark_run_finished` **by name**. Returns the tenant it acted for."""
    tenant_slug: str = await workflow.execute_activity(
        "mark_run_finished",
        MarkRunFinished(
            workflow_id=workflow.info().workflow_id,
            status=status,
            error=error,
        ),
        start_to_close_timeout=FINISH_TIMEOUT,
        retry_policy=FINISH_RETRY,
        result_type=str,
    )
    return tenant_slug


async def _finish[T](work: Callable[[], Awaitable[T]]) -> tuple[T, str]:
    """Run the work, then close this run's visibility row. **The seam.**

    The order is the whole point: the work happens **first**, and the row is
    marked `completed` only after it returned — or `failed`, carrying the error
    string, on the way out of a failure. A workflow that marked itself complete
    and *then* did the work would leave a row saying `completed` for a run that
    failed, and no reader anywhere could tell.

    Deterministic (house rule 9): it invokes one activity by name and touches
    nothing else.

    **Three outcomes, three words** (ADR workflows-7). `completed` and `failed`
    were always here; `cancelled` is the third, and the reason it took a rung is
    that a cancelled workflow's `CancelledError` is a `BaseException` and slips
    past `except Exception` untouched — so a run somebody deliberately stopped
    used to leave a row saying `running` for ever, and the reconciler's only
    honest guess was `failed`. Two things make the third branch work:

    * **`asyncio.shield`**, because the workflow's own task is already cancelled
      and an activity scheduled bare would be cancelled with it before it ran.
      Shielded, it completes, and the row is closed by the same activity that
      closes every other run. (This module's earlier docstring claimed a
      cancelled workflow *cannot* schedule an activity. It can; measured on this
      tree against the time-skipping server.)
    * **`workflow.cancellation_reason()`**, which is not `None` only for a
      cancel that came from the server. An inner `CancelledError` — a timed-out
      scope, a race a workflow lost — is a workflow's own control flow and must
      not be reported to the ledger as somebody having stopped the job. That one
      is re-raised untouched and whatever catches it decides.

    The order still matters everywhere: the work happens **first**, and the row
    is marked only after it has returned, failed or been stopped. A workflow
    that marked itself complete and *then* did the work would leave a row saying
    `completed` for a run that failed, and no reader anywhere could tell.

    Returns the work's own result **and** the tenant slug the closing activity
    acted for. The second half is not decoration: it is what lets
    `EchoWorkflow` prove the tenant survived client → workflow → activity
    without a second activity existing purely to say so.
    """
    try:
        result = await work()
    except asyncio.CancelledError:
        if workflow.cancellation_reason() is None:
            raise
        await asyncio.shield(_mark(CANCELLED))
        raise
    except Exception as failure:
        await _mark("failed", error=_reason(failure))
        raise
    return result, await _mark("completed")


@workflow.defn(name="EchoWorkflow")
class EchoWorkflow:
    """The smallest honest workflow: one activity, one deterministic result.

    It exists so the wiring is provable — the worker discovers it, the tenant
    reaches the activity, and the run's status transitions — without a product
    having to invent a workflow first.

    It refuses an empty message, which is both true (an echo of nothing is not
    a result) and the thing that makes the failure half of `_finish` testable
    from the outside: start it with `""` and the row must end `failed`.
    """

    @workflow.run
    async def run(self, message: str) -> EchoOutput:
        async def echo() -> str:
            if not message:
                raise ApplicationError(
                    "EchoWorkflow was asked to echo an empty message.",
                    non_retryable=True,
                )
            return message

        echoed, tenant_slug = await _finish(echo)
        return EchoOutput(message=echoed, tenant_slug=tenant_slug)


@workflow.defn(name="SendEmailWorkflow")
class SendEmailWorkflow:
    """Hand one email to the mail host, and keep trying until it takes it.

    This is the shape `architecture.md` rules for email: the Django backend is
    called **from an activity**, so a mail host that is refusing connections
    costs a retry rather than the write that asked for the email. The workflow
    itself does nothing but wait — no ORM, no SMTP, no clock (house rule 9).

    Retries are Temporal's default policy, bounded by `schedule_to_close`:
    exponential backoff from a second, for at most an hour in total. There is no
    hand-written `RetryPolicy` because a deadline says the thing that matters
    ("stop trying after an hour") and an attempt count does not.

    Returns how many messages the backend accepted, so a `WorkflowRun` that
    completed with 0 is distinguishable from one that completed with 1 — an
    address the backend silently dropped is a real failure mode.
    """

    @workflow.run
    async def run(self, message: SendEmail) -> int:
        async def deliver() -> int:
            accepted: int = await workflow.execute_activity(
                "send_email",
                message,
                start_to_close_timeout=ATTEMPT_TIMEOUT,
                schedule_to_close_timeout=DELIVERY_DEADLINE,
                result_type=int,
            )
            return accepted

        accepted, _tenant_slug = await _finish(deliver)
        return accepted


# A re-parent touches every row under the moving node. One attempt is bounded
# so a lock held against a large subtree cannot be held forever; the deadline is
# generous because the alternative to finishing is a tree half-moved.
MOVE_ATTEMPT_TIMEOUT = timedelta(minutes=5)
MOVE_DEADLINE = timedelta(hours=1)


@workflow.defn(name="MoveOrganizationWorkflow")
class MoveOrganizationWorkflow:
    """Carry a re-parent through, however long the subtree takes.

    `architecture.md` rules re-parenting a **service plus a workflow**, and this
    is the workflow half. It does nothing itself — no ORM, no clock (house rule
    9) — because the whole job is the one thing a workflow is for: making sure
    that a rewrite which touches every descendant either completes or is
    retried, rather than leaving a tenant's tree half-moved because a worker
    was restarted mid-subtree.

    The activity is idempotent (`core.services.apply_organization_move` returns
    the node untouched when it is already under the new parent), which is what
    makes at-least-once delivery safe here.

    It returns the node's new path, so the run's history says where the subtree
    landed without anybody having to query for it afterwards.

    Closing the row matters more here than anywhere else in this module, and it
    interlocks with the digest: a move's workflow id is keyed on the node, so
    once the first move of a node completes, its row is finished — and only
    `record_run`'s supersede (a second move carries a different `new_parent_id`
    and therefore a different digest) lets that node ever move again.
    """

    @workflow.run
    async def run(self, move: MoveOrganization) -> str:
        async def rewrite() -> str:
            path: str = await workflow.execute_activity(
                "rewrite_organization_paths",
                move,
                start_to_close_timeout=MOVE_ATTEMPT_TIMEOUT,
                schedule_to_close_timeout=MOVE_DEADLINE,
                result_type=str,
            )
            return path

        path, _tenant_slug = await _finish(rewrite)
        return path


# The sweep walks every tenant's rows and asks Temporal about each stranded one,
# so it is minutes rather than seconds — and bounded, because a sweep still
# running when the next one is due is a deployment with a problem the SKIP
# overlap policy should be allowed to surface.
RECONCILE_TIMEOUT = timedelta(minutes=10)


@workflow.defn(name="ReconcileRunsWorkflow")
class ReconcileRunsWorkflow:
    """The other half of "did we start one" — the rows nobody ever started.

    `start_workflow_on_commit` writes the visibility row inside the caller's
    transaction and dials Temporal on commit, and a process that dies in that
    gap leaves a row saying RUNNING with an empty `run_id` for ever. Nothing in
    the product read that shape until this, and `manage.py` had no
    command for it either: the row was a promise with no promise-keeper, which
    is the same finding the outbox relay closed one app over (ADR events-3).

    Started by the declared machinery (`activities.RECONCILE_RUNS`)
    beside the events app's two, for the same reason: a recovery mechanism
    somebody has to remember to run is the finding one layer up.

    The threshold arrives as an argument rather than being read here, because
    subtracting it from the clock is a clock read and a workflow may not make
    one (house rule 9). The activity does it, once, where every non-deterministic
    thing in this app already lives — including the Temporal describe call, which
    is network I/O and therefore could not live in this module either.
    """

    #: House rule 28's marker (ADR workflows-5): this run is started by a
    #: schedule, so no service called `record_run` for it and there is no
    #: `WorkflowRun` row to close — nobody is waiting on a visibility row for
    #: the deployment's own housekeeping. Declaring it is what tells the rule
    #: the missing `_finish` is a decision rather than the omission it exists
    #: to catch.
    owns_no_run = True

    @workflow.run
    async def run(self, window: ReconcileRuns) -> int:
        closed: int = await workflow.execute_activity(
            "reconcile_runs",
            window,
            start_to_close_timeout=RECONCILE_TIMEOUT,
            result_type=int,
        )
        return closed


# Both purges delete by age in one statement per population, so they are
# seconds rather than minutes — and bounded for the reason the reconciler is: a
# sweep still running when the next one is due is a deployment with a problem
# that the SKIP overlap policy should be allowed to surface, not a timeout to
# widen until it stops complaining.
PURGE_TIMEOUT = timedelta(minutes=10)


@workflow.defn(name="PurgeFinishedRunsWorkflow")
class PurgeFinishedRunsWorkflow:
    """The run ledger's retention window, applied. **Rule 31's keeper.**

    `WorkflowRun.lifecycle` declares this table `purged` and names
    `apps.workflows.services.purge_finished_runs`; a declaration whose callable
    nothing ever starts is the poller that was never built, which is the exact
    defect the whole lifecycle vocabulary exists to catch (ADR core-13).
    This class and `activities.PURGE_FINISHED_RUNS` are the other half of that
    declaration, and they land in the same commit as it on purpose — rule 31
    walks from the `purged_by` string to this workflow and would refuse the
    declaration on its own.

    Deterministic (house rule 9): it invokes one activity by name and touches
    nothing else. The **retention window arrives as an argument** rather than
    being subtracted from the clock here, because subtracting from the clock is
    a clock read and a workflow may not make one — the same shape
    `ReconcileRunsWorkflow` takes, for the same reason.

    Returns how many rows went, which is the operator's question: a steady
    trickle is the healthy state, a sudden large number is a retention window
    somebody changed, and zero for ever is a schedule that is not running.
    """

    #: House rule 28's marker (ADR workflows-5). Started by a schedule, so no
    #: service called `record_run` for it and there is no `WorkflowRun` row to
    #: close — the same posture `ReconcileRunsWorkflow` takes, and doubly
    #: right here: a purge of the run ledger that wrote itself a ledger row
    #: would be a table cleaning itself and growing by one every day.
    owns_no_run = True

    @workflow.run
    async def run(self, window: PurgeFinishedRuns) -> int:
        purged: int = await workflow.execute_activity(
            "purge_finished_runs",
            window,
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=int,
        )
        return purged


@workflow.defn(name="PurgeExpiredSessionsWorkflow")
class PurgeExpiredSessionsWorkflow:
    """Expired sessions, cleared daily. **A long-standing gap, closed.**

    `django_session` was never cleared anywhere in this tree — no cron entry, no
    management command in any deployment path, no schedule — so every login
    since day zero left a row nothing would ever remove. `apps/workflows/
    lifecycle.py` declares the table `purged` and argues there why this app owns
    the concern rather than `apps/accounts`; this is the machine that makes the
    declaration true.

    **No argument at all**, and that is the honest shape: expiry is a property
    of each row (`expire_date`), so there is no window to tune and nothing for a
    schedule's action to carry. A retention number here would be a knob that
    changed nothing.

    Deterministic (house rule 9): one activity, by name. The session engine
    lookup, the count and the clear are all I/O and all live in the activity.
    """

    #: House rule 28's marker (ADR workflows-5), same posture as its sibling
    #: above: schedule-started, so nobody called `record_run` and there is no
    #: visibility row for this run to close. Declaring it is what tells the rule
    #: the missing `_finish` is a decision rather than the omission it exists to
    #: catch.
    owns_no_run = True

    @workflow.run
    async def run(self) -> int:
        cleared: int = await workflow.execute_activity(
            "purge_expired_sessions",
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=int,
        )
        return cleared


WORKFLOWS: list[type] = [
    EchoWorkflow,
    SendEmailWorkflow,
    MoveOrganizationWorkflow,
    ReconcileRunsWorkflow,
    PurgeFinishedRunsWorkflow,
    PurgeExpiredSessionsWorkflow,
]
