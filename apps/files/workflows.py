"""This app's durable work: going and looking at what actually landed, and
taking away what never did.

Deterministic code only (house rule 9). No ORM, no boto3, no clock and no
randomness is imported or called here — all of it is in `activities.py`, invoked
**by name**, because importing the activities module would drag the ORM and the
AWS SDK into code that has to replay identically years from now. The only module
of ours this file imports is its own `types.py`, which is standard library all
the way down.

**Why finalizing is a workflow and not the rest of the confirm request.**
Streaming a document out of an object store to digest it takes as long as the
document is big, over a network that is somebody else's; the client that said "I
have finished uploading" is not going to hold a connection open for it, and a
request that timed out halfway would leave a version stuck `PENDING` beside an
object that is perfectly fine. Retrying from where it stopped, surviving a
deploy, and ending in a row that says which way it went is exactly what durable
execution is for.

**The two activities are split because they fail differently.** `verify_object`
is I/O against a bucket and it is the one that is worth retrying — a bucket is
briefly unreachable, a large object times out. `record_stored` is a local
transaction and it either applies or refuses for a reason a retry will not fix.
Splitting them also means the measurement is in the run's history as a fact of
its own: what this platform saw at that key, at that moment, before anything was
written down about it.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.files.types import (
    FINALIZE_WORKFLOW,
    SWEEP_WORKFLOW,
    FinalizeUpload,
    RunFinished,
    StoreMeasurement,
    SweepOutcome,
    SweepPendingUploads,
    VerifiedObject,
)

#: How long one attempt at heading and digesting an object may take. Generous,
#: because the object may be gigabytes and the digest is a full read of it;
#: bounded, because an activity with no ceiling is a worker thread nobody can get
#: back.
VERIFY_TIMEOUT = timedelta(minutes=30)

#: How many attempts the verification gets. Bounded rather than infinite, and
#: five rather than three: the ordinary failure here is a bucket that is briefly
#: unreachable, which retries out; an object that is not there after five
#: attempts is a confirm for an upload that never happened, and the honest answer
#: to that is a failed run and a version left `PENDING` for the sweep — not a run
#: that stays technically trying until the retention policy deletes it.
VERIFY_RETRY = RetryPolicy(maximum_attempts=5)

#: Writing the measurement down: one local transaction. Short, and retried,
#: because the failures it has are a lock wait and a connection blip. A refusal
#: from the ledger (a measurement that disagrees with one already recorded) is a
#: domain error that will refuse identically on every attempt, and the run fails
#: with the ledger's own sentence on the row.
RECORD_TIMEOUT = timedelta(minutes=2)
RECORD_RETRY = RetryPolicy(maximum_attempts=5)

#: Closing out the `WorkflowRun` row (house rule 28). One local database write,
#: bounded: a bookkeeping activity that retried forever would outlive the thing
#: it is bookkeeping for.
FINISH_TIMEOUT = timedelta(seconds=30)
FINISH_RETRY = RetryPolicy(maximum_attempts=5)
FINISH_ACTIVITY = "mark_run_finished"

#: One pass of the sweep: an indexed read over two columns, a bulk delete, and
#: one small transaction per document it empties. Sized for the FIRST sweep of a
#: deployment that has never had one — where the backlog is everything anybody
#: ever abandoned — rather than for the steady state, which is usually nothing at
#: all. Bounded all the same: an activity with no ceiling is a worker thread
#: nobody can get back.
SWEEP_TIMEOUT = timedelta(minutes=30)

#: The two terminal values of `apps.workflows.models.WorkflowRun.Status`. Named
#: here as strings rather than imported: a workflow module may import its own
#: `types.py` and nothing else, because it has to replay identically years from
#: now (house rule 9).
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"

#: How far to walk a cause chain looking for what actually broke. Three:
#: wrapper -> activity error -> the activity's own complaint. Bounded because a
#: cause chain is somebody else's data structure.
CAUSE_LINKS = 3


def _reason(failure: BaseException) -> str:
    """What actually went wrong, joined out of the cause chain.

    Temporal wraps an activity's own exception in an `ActivityError` whose
    `str()` is "Activity task failed" — true, and useless to whoever reads the
    `WorkflowRun` row six weeks later, which here is somebody asking why a
    customer's document never became downloadable.
    `apps.workflows.workflows::_reason` is the worked form and this is the same
    shape; it is restated rather than imported because a workflow module may
    import only its own `types.py`.

    Deterministic: it reads nothing but the exception it was handed.
    """
    parts: list[str] = []
    seen: BaseException | None = failure
    for _ in range(CAUSE_LINKS):
        if seen is None:
            break
        text = str(seen).strip()
        if text and text not in parts:
            parts.append(text)
        seen = seen.__cause__
    return ": ".join(parts) or type(failure).__name__


@workflow.defn(name=FINALIZE_WORKFLOW)
class FinalizeUploadWorkflow:
    """Look at the object, measure it, write down what was measured. Close the row.

    **This workflow owns a `WorkflowRun` row and therefore closes it** (house
    rule 28): a service started it — `services.confirm_upload` calls
    `start_workflow_on_commit`, which writes the row — so somebody is waiting on
    a visibility row, and a row left saying `running` beside an execution
    Temporal has marked FAILED is worse than no row at all, because it is a row
    that lies. That is the opposite of the `owns_no_run = True` half of the same
    rule, which belongs to schedule-started runs nobody asked for;
    `SweepPendingUploadsWorkflow` below is this app's instance of that half.

    **Nothing here decides whether the object is acceptable.** The workflow
    sequences two facts — what the store holds, and that we wrote it down — and
    the deciding all sits in the service, where the transaction is.
    """

    @workflow.run
    async def run(self, request: FinalizeUpload) -> VerifiedObject:
        try:
            verified: VerifiedObject = await workflow.execute_activity(
                "verify_object",
                request,
                start_to_close_timeout=VERIFY_TIMEOUT,
                retry_policy=VERIFY_RETRY,
                result_type=VerifiedObject,
            )
            await workflow.execute_activity(
                "record_stored",
                StoreMeasurement(
                    version_id=request.version_id,
                    sha256=verified.sha256,
                    size_bytes=verified.size_bytes,
                ),
                start_to_close_timeout=RECORD_TIMEOUT,
                retry_policy=RECORD_RETRY,
                result_type=str,
            )
        except Exception as failure:
            # The run row first, then the failure. The version is deliberately
            # left `PENDING` rather than marked failed: "nothing arrived, or
            # nothing could be measured" is the absence of a transition, and the
            # sweep is what expires it. A `FAILED` status here would be a
            # third state on a two-state model, and it would have to be undone by
            # hand the moment a bucket came back.
            await self._finish(status=RUN_FAILED, error=_reason(failure))
            raise
        await self._finish(status=RUN_COMPLETED)
        return verified

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way the run ended.

        The same activity every other app calls, by name, from an app that does
        not import the one that defines it (house rule 28). Idempotent, so a
        retry rewrites the same terminal state.
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


@workflow.defn(name=SWEEP_WORKFLOW)
class SweepPendingUploadsWorkflow:
    """Expire the uploads that never happened, and archive what they leave empty.

    Started by the declared machinery (`activities.SWEEP_PENDING_UPLOADS`), which
    this deployment's lifetime class turns into either a durable Temporal
    Schedule or a timer on a live worker (ADR platform-lifecycle-1). A schedule
    rather than cron, because a cron entry lives in a place nobody deploys and
    nobody can see the last run of.

    **The complement of `FinalizeUploadWorkflow` above, and the pair is what
    makes house rule 28 readable.** That one owns a `WorkflowRun` row because a
    service started it and somebody is waiting on a visibility row; this one owns
    none, because nobody asked for it. `owns_no_run = True` means "I own no row",
    never "I am exempt" — and the honest place to look for what this run did is
    the platform audit row the service writes, not a row nobody would have gone
    looking for.

    One activity and no decisions: the window arrives on the argument, the
    deciding is all in the service where the transaction is, and this class
    sequences nothing because there is nothing to sequence.
    """

    #: House rule 28 (ADR workflows-5), the schedule-started half — the same one
    #: `PurgeExportsWorkflow`, `PurgeExpiredWorkflow`, `ReconcileOutboxWorkflow`
    #: and `PurgeInboundWebhooksWorkflow` carry.
    owns_no_run = True

    @workflow.run
    async def run(self, window: SweepPendingUploads) -> SweepOutcome:
        swept: SweepOutcome = await workflow.execute_activity(
            "sweep_pending_uploads",
            window,
            start_to_close_timeout=SWEEP_TIMEOUT,
            result_type=SweepOutcome,
        )
        return swept


WORKFLOWS: list[type] = [FinalizeUploadWorkflow, SweepPendingUploadsWorkflow]
