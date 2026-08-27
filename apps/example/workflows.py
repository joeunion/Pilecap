"""The worked example of durable work: a widget's onboarding.

It is here because a template needs one honest answer to "where does the thing
that waits go", and this is the smallest shape that shows all of it: an activity
that changes a row, a **wait for a human** that may never come, and a statement
of what happened emitted at the end. None of those three fits in a request.

House rule 9, visible: this module imports the standard library's `timedelta`,
`temporalio.workflow`, and its own `types.py` — and nothing else. **No ORM, no
network, no clock, no randomness, and no import of `activities.py`** — the
activities are invoked **by name**, because importing them would drag the ORM
into a module that has to replay identically years from now. Even the timestamp
this run records is the activity's: a workflow that read a clock could not be
replayed.

The wait is the point. A timer of a week costs nothing while it runs, survives
every restart and deploy in between, and ends in one of exactly two ways —
somebody signalled, or nobody did. Both are outcomes; neither is an error.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.example.types import (
    RunFinished,
    WidgetAnnouncement,
    WidgetOnboarded,
    WidgetOnboarding,
)

# How long one attempt at an activity may take. Both activities are a short
# database write, so a run that has not finished in thirty seconds is a run that
# is not going to.
ACTIVITY_TIMEOUT = timedelta(seconds=30)

# How long somebody has to approve. A week, because that is roughly the span of
# "a person will get to it", and because the number has to be *somewhere* — a
# wait with no deadline is a workflow that stays running until the retention
# policy deletes it, and nobody ever finds out that nobody approved.
APPROVAL_DEADLINE = timedelta(days=7)

# Closing out the `WorkflowRun` row. The row is written by the service that
# started the run and says `running` until somebody says otherwise — and until
# rung A11 nobody did, so the worked example left a row permanently running
# beside an execution Temporal had marked COMPLETED (queue V6). One local
# database write, bounded: a bookkeeping activity that retried forever would
# outlive the thing it is bookkeeping for.
FINISH_TIMEOUT = timedelta(seconds=30)
FINISH_RETRY = RetryPolicy(maximum_attempts=5)
FINISH_ACTIVITY = "mark_run_finished"

# The two terminal values of `apps.workflows.models.WorkflowRun.Status`. Named
# here as strings rather than imported: a workflow module may import its own
# `types.py` and nothing else, because it has to replay identically years from
# now (house rule 9).
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"


@workflow.defn(name="WidgetOnboardingWorkflow")
class WidgetOnboardingWorkflow:
    """Mark a widget onboarded, wait for approval, then say what happened."""

    def __init__(self) -> None:
        self._approved = False

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> WidgetOnboarded:
        try:
            onboarded = await self._onboard(onboarding)
        except Exception as error:
            # The row says what happened, and then the run still fails. A
            # `WorkflowRun` left at `running` beside a Temporal execution that
            # ended is worse than no row at all: it is a row that lies.
            await self._finish(status=RUN_FAILED, error=str(error))
            raise
        await self._finish(status=RUN_COMPLETED)
        return onboarded

    async def _onboard(self, onboarding: WidgetOnboarding) -> WidgetOnboarded:
        """The work itself. Separated so the bookkeeping wraps all of it."""
        onboarded_at: str = await workflow.execute_activity(
            "mark_widget_onboarded",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )

        try:
            await workflow.wait_condition(lambda: self._approved, timeout=APPROVAL_DEADLINE)
        except TimeoutError:
            # Nobody approved in a week. That is an answer, and the announcement
            # carries it — the alternative, failing the run, would turn "nobody
            # got round to it" into an alert somebody has to triage.
            pass

        await workflow.execute_activity(
            "announce_widget_onboarded",
            WidgetAnnouncement(widget_id=onboarding.widget_id, approved=self._approved),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return WidgetOnboarded(
            widget_id=onboarding.widget_id,
            onboarded_at=onboarded_at,
            approved=self._approved,
        )

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way the run ended.

        The same activity `EchoWorkflow` calls, by name, from an app that does
        not import the one that defines it. Idempotent, so a retry rewrites the
        same terminal state.
        """
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(
                workflow_id=workflow.info().workflow_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=FINISH_TIMEOUT,
            retry_policy=FINISH_RETRY,
            result_type=str,
        )

    @workflow.signal(name="approve")
    def approve(self) -> None:
        """Somebody approved this widget.

        A signal rather than an update or a second workflow: it is a fact
        arriving from outside, it needs no answer, and Temporal has already
        durably recorded it by the time the sender's call returns. Setting a flag
        is all a signal handler should ever do — the deciding happens in `run`,
        where the history is.
        """
        self._approved = True


WORKFLOWS: list[type] = [WidgetOnboardingWorkflow]
