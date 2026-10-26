"""This app's three workflows: the dry run, the apply, the retention sweep. Deterministic (rule 9).

A server cancel closes the import and its run `cancelled` and re-raises (ADR workflows-7).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow

from apps.core.determinism import (
    CANCELLED,
    COMPLETED,
    FAILED,
    cancelled_by_the_server,
    finish_run,
    reason_of,
    retry_policy,
)
from apps.djb_imports.types import (
    APPLY_WORKFLOW,
    CHECK_WORKFLOW,
    PURGE_WORKFLOW,
    ApplyImport,
    CheckImport,
    ImportFailed,
    ImportSettled,
    PurgeImports,
    PurgeOutcome,
)

#: Reading and judging up to ten thousand rows: minutes, bounded.
CHECK_TIMEOUT = timedelta(minutes=30)
CHECK_ATTEMPTS = 5

#: Applying up to ten thousand rows, each through a noun's services.
APPLY_TIMEOUT = timedelta(hours=2)
#: The activity heartbeats after every row, so a gap this long means its worker is gone.
APPLY_HEARTBEAT = timedelta(seconds=20)
APPLY_ATTEMPTS = 10

FAILURE_TIMEOUT = timedelta(minutes=5)
PURGE_TIMEOUT = timedelta(minutes=30)
CLOSE_ATTEMPTS = 5

#: What a cancelled import says on its row and on its run's: somebody stopped it.
CANCELLED_REASON = "cancelled"


async def _record_reason(
    import_id: str, reason: str, floor: float | None, *, cancelled: bool = False
) -> None:
    # Default cancellation type: a closing activity is scheduled after the cancel was taken.
    await workflow.execute_activity(
        "record_import_failure",
        ImportFailed(import_id=import_id, reason=reason, cancelled=cancelled),
        start_to_close_timeout=FAILURE_TIMEOUT,
        retry_policy=retry_policy(initial_seconds=floor, maximum_attempts=CLOSE_ATTEMPTS),
        result_type=str,
    )


async def _close_cancelled(import_id: str, floor: float | None) -> None:
    await _record_reason(import_id, CANCELLED_REASON, floor, cancelled=True)
    await finish_run(
        status=CANCELLED,
        error=CANCELLED_REASON,
        retry=retry_policy(initial_seconds=floor, maximum_attempts=CLOSE_ATTEMPTS),
    )


async def _close_failed(import_id: str, failure: BaseException, floor: float | None) -> None:
    reason = reason_of(failure)
    await _record_reason(import_id, reason, floor)
    await finish_run(
        status=FAILED,
        error=reason,
        retry=retry_policy(initial_seconds=floor, maximum_attempts=CLOSE_ATTEMPTS),
    )


@workflow.defn(name=CHECK_WORKFLOW)
class ValidateImportWorkflow:
    """The dry run: judge every row of the staged file, write the preview."""

    @workflow.run
    async def run(self, request: CheckImport) -> ImportSettled:
        floor = request.retry_floor
        try:
            # why-not WAIT_CANCELLATION_COMPLETED: the check never heartbeats, so it could not
            # learn of a cancel; the preview write refuses a run that is no longer `checking`.
            settled: ImportSettled = await workflow.execute_activity(
                "check_import",
                request,
                start_to_close_timeout=CHECK_TIMEOUT,
                retry_policy=retry_policy(initial_seconds=floor, maximum_attempts=CHECK_ATTEMPTS),
                result_type=ImportSettled,
            )
        except asyncio.CancelledError as cancel:
            if not cancelled_by_the_server(cancel):
                raise
            await asyncio.shield(_close_cancelled(request.import_id, floor))
            raise
        except Exception as failure:
            if cancelled_by_the_server(failure):
                await asyncio.shield(_close_cancelled(request.import_id, floor))
                raise
            await _close_failed(request.import_id, failure, floor)
            raise
        await finish_run(
            status=COMPLETED,
            retry=retry_policy(initial_seconds=floor, maximum_attempts=CLOSE_ATTEMPTS),
        )
        return settled


@workflow.defn(name=APPLY_WORKFLOW)
class ApplyImportWorkflow:
    """The apply: every clean row through the importer, the refused ones listed."""

    @workflow.run
    async def run(self, request: ApplyImport) -> ImportSettled:
        floor = request.retry_floor
        try:
            # WAIT_CANCELLATION_COMPLETED: the import is closed only once no row is being written.
            settled: ImportSettled = await workflow.execute_activity(
                "apply_import_rows",
                request,
                start_to_close_timeout=APPLY_TIMEOUT,
                heartbeat_timeout=APPLY_HEARTBEAT,
                retry_policy=retry_policy(initial_seconds=floor, maximum_attempts=APPLY_ATTEMPTS),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                result_type=ImportSettled,
            )
        except asyncio.CancelledError as cancel:
            if not cancelled_by_the_server(cancel):
                raise
            await asyncio.shield(_close_cancelled(request.import_id, floor))
            raise
        except Exception as failure:
            if cancelled_by_the_server(failure):
                await asyncio.shield(_close_cancelled(request.import_id, floor))
                raise
            await _close_failed(request.import_id, failure, floor)
            raise
        await finish_run(
            status=COMPLETED,
            retry=retry_policy(initial_seconds=floor, maximum_attempts=CLOSE_ATTEMPTS),
        )
        return settled


@workflow.defn(name=PURGE_WORKFLOW)
class PurgeImportsWorkflow:
    """Delete settled runs past their retention; schedule-started, so it owns no row."""

    owns_no_run = True

    @workflow.run
    async def run(self, window: PurgeImports) -> PurgeOutcome:
        # why-not a cancel arm: it owns no row, and the next day's sweep finishes a cancelled one.
        purged: PurgeOutcome = await workflow.execute_activity(
            "purge_expired_imports",
            window,
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=PurgeOutcome,
        )
        return purged


WORKFLOWS: list[type] = [ValidateImportWorkflow, ApplyImportWorkflow, PurgeImportsWorkflow]
