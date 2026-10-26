"""This app's two workflows. Deterministic code only (house rule 9).

No ORM, no `httpx`, no clock and no randomness is imported or called here — all
of it is in `activities.py`, invoked **by name**, because importing the
activities module would drag the ORM into code that has to replay identically
years from now. The only module of ours this file imports is its own `types.py`,
which is standard library all the way down.

**`ExportTenantDataWorkflow`** builds one archive. It is a workflow rather than
the rest of a request for the plain reason: streaming a customer's whole
database into a zip takes minutes, has to survive a deploy, and must be retried
from where it stopped rather than from the beginning of somebody's afternoon.

**`PurgeExportsWorkflow`** is the deployment's housekeeping — the machine that
makes `Export`'s `purged` declaration true. Writing the two in one commit is the
whole point of house rule 31: a table shaped for a sweeper with no sweeper looks
exactly like a table that is finished, and here the rows are complete copies of
customers' databases.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

from apps.core.determinism import reason_of, retry_policy
from apps.exports.types import (
    PURGE_WORKFLOW,
    BuildExport,
    ExportBuilt,
    ExportFailed,
    PurgeExports,
    PurgeOutcome,
    RunFinished,
)

#: How long one attempt at building an archive may take. Generous, because the
#: first export of a large tenant is the big one and a timeout there costs the
#: whole run; bounded, because an activity with no ceiling is a worker thread
#: nobody can get back.
BUILD_TIMEOUT = timedelta(hours=2)

#: How many attempts the build gets before the run gives up and the row says so.
#: Bounded rather than infinite: an export that has failed five times is failing
#: for a reason a retry will not fix, and a customer waiting on an archive is
#: better served by a `failed` row they can see than by a run that is still
#: technically trying.
BUILD_ATTEMPTS = 5

#: Marking the row failed, and deleting expired archives. Both are short local
#: writes; the purge's is longer because it deletes objects from a bucket one at
#: a time on its first sweep of a table nobody has swept.
FAILURE_TIMEOUT = timedelta(minutes=5)
PURGE_TIMEOUT = timedelta(minutes=30)

#: Closing out the `WorkflowRun` row (house rule 28). One local database write,
#: bounded: a bookkeeping activity that retried forever would outlive the thing
#: it is bookkeeping for.
FINISH_TIMEOUT = timedelta(seconds=30)
FINISH_ATTEMPTS = 5
FINISH_ACTIVITY = "mark_run_finished"

#: The two terminal values of `apps.workflows.models.WorkflowRun.Status`. Named
#: here as strings rather than imported: a workflow module may import its own
#: `types.py` and nothing else, because it has to replay identically years from
#: now (house rule 9).
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"


@workflow.defn(name="ExportTenantDataWorkflow")
class ExportTenantDataWorkflow:
    """Build one tenant's — or one branch's — archive, and close the row either way.

    Two things are guaranteed on every path out of `run`: the `Export` row ends
    in a terminal status, and the `WorkflowRun` row is closed. A row left saying
    `running` beside an execution Temporal has marked FAILED is worse than no row
    at all, because it is a row that lies.
    """

    _floor: float | None = None

    @workflow.run
    async def run(self, request: BuildExport) -> ExportBuilt:
        self._floor = request.retry_floor
        try:
            built: ExportBuilt = await workflow.execute_activity(
                "build_export_archive",
                request,
                start_to_close_timeout=BUILD_TIMEOUT,
                retry_policy=retry_policy(
                    initial_seconds=self._floor, maximum_attempts=BUILD_ATTEMPTS
                ),
                result_type=ExportBuilt,
            )
        except Exception as failure:
            # The export row first, so a customer looking at the API sees a
            # failure with a reason on it; then the run row; then the run really
            # fails, because a run that swallowed the error would be a green
            # execution beside an archive that does not exist.
            reason = reason_of(failure)
            await workflow.execute_activity(
                "record_export_failure",
                ExportFailed(export_id=request.export_id, reason=reason),
                start_to_close_timeout=FAILURE_TIMEOUT,
                retry_policy=retry_policy(
                    initial_seconds=self._floor, maximum_attempts=FINISH_ATTEMPTS
                ),
                result_type=str,
            )
            await self._finish(status=RUN_FAILED, error=reason)
            raise
        await self._finish(status=RUN_COMPLETED)
        return built

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
            retry_policy=retry_policy(
                initial_seconds=self._floor, maximum_attempts=FINISH_ATTEMPTS
            ),
            result_type=str,
        )


@workflow.defn(name=PURGE_WORKFLOW)
class PurgeExportsWorkflow:
    """Delete the archives past their retention — the object, then the row.

    Started by the declared machinery (`activities.PURGE_EXPORTS`), which the
    deployment's lifetime class turns into either a durable Temporal Schedule or
    a timer on a live worker (ADR platform-lifecycle-1). A schedule rather than
    cron, because a cron entry lives in a place nobody deploys and nobody can
    see the last run of.
    """

    #: House rule 28 (ADR workflows-5), and the same half its siblings
    #: `PurgeExpiredWorkflow`, `ReconcileOutboxWorkflow` and
    #: `PurgeInboundWebhooksWorkflow` carry: a schedule-started run has no
    #: `WorkflowRun` row to close, because no service asked for it and nobody is
    #: waiting on a visibility row for the deployment's own housekeeping. The
    #: marker means "I own no row" — never "I am exempt".
    owns_no_run = True

    @workflow.run
    async def run(self, window: PurgeExports) -> PurgeOutcome:
        purged: PurgeOutcome = await workflow.execute_activity(
            "purge_expired_exports",
            window,
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=PurgeOutcome,
        )
        return purged


WORKFLOWS: list[type] = [ExportTenantDataWorkflow, PurgeExportsWorkflow]
