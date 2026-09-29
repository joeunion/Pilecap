"""This app's three workflows. Deterministic code only (house rule 9).

No ORM, no network, no clock and no randomness is imported or called here: every
touch of the world is an activity in `activities.py`, invoked **by name**. The
only module of ours this file imports is its own `types.py`.

* **`ValidateImportWorkflow`** — the dry run, started when a file is staged.
* **`ApplyImportWorkflow`** — the apply, started when a person presses apply
  after reading the preview. A second start, never one run waiting days on a
  human signal. Its activity heartbeats per row, so a dead worker is noticed in
  `APPLY_HEARTBEAT` rather than at the end of `APPLY_TIMEOUT`.
* **`PurgeImportsWorkflow`** — the retention sweep the schedule starts.

The first two decide and close their `WorkflowRun` row either way (house rule
28): on a failure that outlived its retries the run is marked failed with the
activity's own complaint, the visibility row is closed, and the run fails.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.imports.types import (
    APPLY_WORKFLOW,
    CHECK_WORKFLOW,
    PURGE_WORKFLOW,
    ApplyImport,
    CheckImport,
    ImportFailed,
    ImportSettled,
    PurgeImports,
    PurgeOutcome,
    RunFinished,
)

with workflow.unsafe.imports_passed_through():
    # rule-9: one deployment constant, read once at import through Temporal's
    # own passthrough seam — `apps/exports/workflows.py` carries the argument.
    from django.conf import settings

RETRY_INITIAL_INTERVAL = timedelta(seconds=settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS)

#: Reading and judging up to ten thousand rows: minutes, bounded.
CHECK_TIMEOUT = timedelta(minutes=30)
CHECK_RETRY = RetryPolicy(initial_interval=RETRY_INITIAL_INTERVAL, maximum_attempts=5)

#: Applying up to ten thousand rows, each through a noun's services.
APPLY_TIMEOUT = timedelta(hours=2)
#: How long a silent apply is trusted. The activity heartbeats after every row,
#: so a gap this long means the worker is gone and another should take over.
APPLY_HEARTBEAT = timedelta(seconds=20)
APPLY_RETRY = RetryPolicy(initial_interval=RETRY_INITIAL_INTERVAL, maximum_attempts=10)

FAILURE_TIMEOUT = timedelta(minutes=5)
PURGE_TIMEOUT = timedelta(minutes=30)
FINISH_TIMEOUT = timedelta(seconds=30)
FINISH_RETRY = RetryPolicy(initial_interval=RETRY_INITIAL_INTERVAL, maximum_attempts=5)
FINISH_ACTIVITY = "mark_run_finished"

RUN_COMPLETED = "completed"
RUN_FAILED = "failed"

#: How far to walk a cause chain looking for what actually broke.
CAUSE_LINKS = 3


def _reason(failure: BaseException) -> str:
    """What actually went wrong, joined out of the cause chain. Deterministic."""
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


async def _record_failure(import_id: str, failure: BaseException) -> str:
    reason = _reason(failure)
    await workflow.execute_activity(
        "record_import_failure",
        ImportFailed(import_id=import_id, reason=reason),
        start_to_close_timeout=FAILURE_TIMEOUT,
        retry_policy=FINISH_RETRY,
        result_type=str,
    )
    return reason


@workflow.defn(name=CHECK_WORKFLOW)
class ValidateImportWorkflow:
    """The dry run: judge every row of the staged file, write the preview."""

    @workflow.run
    async def run(self, request: CheckImport) -> ImportSettled:
        try:
            settled: ImportSettled = await workflow.execute_activity(
                "check_import",
                request,
                start_to_close_timeout=CHECK_TIMEOUT,
                retry_policy=CHECK_RETRY,
                result_type=ImportSettled,
            )
        except Exception as failure:
            reason = await _record_failure(request.import_id, failure)
            await self._finish(status=RUN_FAILED, error=reason)
            raise
        await self._finish(status=RUN_COMPLETED)
        return settled

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way it ended (house rule 28)."""
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(workflow_id=workflow.info().workflow_id, status=status, error=error),
            start_to_close_timeout=FINISH_TIMEOUT,
            retry_policy=FINISH_RETRY,
            result_type=str,
        )


@workflow.defn(name=APPLY_WORKFLOW)
class ApplyImportWorkflow:
    """The apply: every clean row through the importer, the refused ones listed."""

    @workflow.run
    async def run(self, request: ApplyImport) -> ImportSettled:
        try:
            settled: ImportSettled = await workflow.execute_activity(
                "apply_import_rows",
                request,
                start_to_close_timeout=APPLY_TIMEOUT,
                heartbeat_timeout=APPLY_HEARTBEAT,
                retry_policy=APPLY_RETRY,
                result_type=ImportSettled,
            )
        except Exception as failure:
            reason = await _record_failure(request.import_id, failure)
            await self._finish(status=RUN_FAILED, error=reason)
            raise
        await self._finish(status=RUN_COMPLETED)
        return settled

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way it ended (house rule 28)."""
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(workflow_id=workflow.info().workflow_id, status=status, error=error),
            start_to_close_timeout=FINISH_TIMEOUT,
            retry_policy=FINISH_RETRY,
            result_type=str,
        )


@workflow.defn(name=PURGE_WORKFLOW)
class PurgeImportsWorkflow:
    """Delete settled runs past their retention; schedule-started, so it owns no row."""

    owns_no_run = True

    @workflow.run
    async def run(self, window: PurgeImports) -> PurgeOutcome:
        purged: PurgeOutcome = await workflow.execute_activity(
            "purge_expired_imports",
            window,
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=PurgeOutcome,
        )
        return purged


WORKFLOWS: list[type] = [ValidateImportWorkflow, ApplyImportWorkflow, PurgeImportsWorkflow]
