"""The workflow seam: what every `workflows.py` may import from the platform.

It imports nothing a workflow may not (stdlib, `temporalio`, `apps.core.roads`): rule 9 admits it.
`apps/core/tests/test_determinism.py` holds the import list and the literals to their rows.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import is_cancelled_exception

from apps.core.roads import road

#: The activity that closes a run's row, invoked by name (house rule 9).
FINISH_ACTIVITY = "mark_run_finished"

#: Its own timeout, not the work's: a long run and a hung bookkeeping write are different failures.
FINISH_TIMEOUT = timedelta(seconds=30)

#: The three terminal words (ADR workflows-7), literals because a workflow may not import `models`.
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

#: How far `reason_of` walks a `__cause__` chain: the wrapper, the activity's error, its complaint.
REASON_DEPTH = 3


@dataclass
class RunFinished:
    """What `mark_run_finished` is told when a run ends: which run, how, and why.

    The worker deserialises it into `apps.workflows.types.MarkRunFinished`, pinned equal.
    """

    workflow_id: str
    status: str
    error: str = ""


def reason_of(failure: BaseException) -> str:
    """The failure and what caused it, as one line for a run row's `error`.

    Walks `__cause__` past Temporal's "Activity task failed" wrapper, bounded by `REASON_DEPTH`.
    """
    said: list[str] = []
    seen: BaseException | None = failure
    while seen is not None and len(said) < REASON_DEPTH:
        said.append(f"{type(seen).__name__}: {seen}")
        seen = seen.__cause__
    return " <- ".join(said)


def cancelled_by_the_server(failure: BaseException) -> bool:
    """A cancel somebody asked for — never a workflow's own inner cancellation.

    `workflow.cancellation_reason()` is set only when the server asked; a timed-out scope is not.
    """
    return is_cancelled_exception(failure) and workflow.cancellation_reason() is not None


def retry_policy(
    *,
    initial_seconds: float | None = None,
    maximum_attempts: int = 0,
    maximum_interval: timedelta | None = None,
) -> RetryPolicy:
    """A retry policy whose first interval is the number the workflow was handed.

    A workflow reads no settings (rule 9): `apps.core.retry.retry_floor_seconds()` does.
    `None` is the SDK's default interval; `maximum_attempts=0` is Temporal's "unbounded".
    """
    if initial_seconds is None:
        return RetryPolicy(maximum_attempts=maximum_attempts, maximum_interval=maximum_interval)
    return RetryPolicy(
        initial_interval=timedelta(seconds=initial_seconds),
        maximum_attempts=maximum_attempts,
        maximum_interval=maximum_interval,
    )


#: Bounded: a bookkeeping write retried for ever would outlive its work; the reconciler sweeps.
FINISH_RETRY = retry_policy(maximum_attempts=5)


async def finish_run(*, status: str, error: str = "", retry: RetryPolicy = FINISH_RETRY) -> str:
    """Close this run's visibility row as `status`. Returns the tenant it acted for."""
    tenant_slug: str = await workflow.execute_activity(
        FINISH_ACTIVITY,
        RunFinished(workflow_id=workflow.info().workflow_id, status=status, error=error),
        start_to_close_timeout=FINISH_TIMEOUT,
        retry_policy=retry,
        result_type=str,
    )
    return tenant_slug


async def run_to_finish[T](
    work: Callable[[], Awaitable[T]], *, retry: RetryPolicy = FINISH_RETRY
) -> tuple[T, str]:
    """Run the work, then close this run's row with one of three words. **The house form.**

    The work runs FIRST; the row says `completed` only after it returned (ADR workflows-5).
    A server cancel closes the row `cancelled` under `asyncio.shield`: its task is cancelled.
    Returns the work's result and the tenant slug `finish_run` answered.
    """
    try:
        result = await work()
    except asyncio.CancelledError as cancel:
        if not cancelled_by_the_server(cancel):
            raise
        await asyncio.shield(finish_run(status=CANCELLED, retry=retry))
        raise
    except Exception as failure:
        if cancelled_by_the_server(failure):
            await asyncio.shield(finish_run(status=CANCELLED, retry=retry))
            raise
        await finish_run(status=FAILED, error=reason_of(failure), retry=retry)
        raise
    return result, await finish_run(status=COMPLETED, retry=retry)


ROAD = road("workflow_seam", example="apps/workflows/workflows.py::EchoWorkflow")(
    sys.modules[__name__]
)
