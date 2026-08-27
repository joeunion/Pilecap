"""The ledger's third word, driven end to end. **Is `cancelled` true?**

`apps/workflows/tests/test_api.py` proves what the cancel door answers and that
it stamps nothing; this module proves the other half — that the row ever gets to
say `cancelled` at all. Without it, this door would have shipped a whole
contract sentence ("poll the run; it will say `cancelled`") was a promise
nothing in the tree kept.

Two witnesses, because there are exactly two, and a run reaches one or the other:

* **the finish seam** — `workflows._finish` catches the cancellation from inside
  the workflow and closes the row through the same activity that closes every
  completed and failed run. This is the ordinary path, and it is driven here
  against the real time-skipping server with the real worker: start a waiting
  run, cancel it the way the service does, read the row.
* **the reconciler** — `activities.reconcile_runs` asks Temporal what became of
  a stranded row and now maps `CANCELED` to `cancelled` instead of lumping it
  into `failed`. That is the path for a run whose worker died before its seam
  ran, and for every execution cancelled outside the product entirely.

Driven against the time-skipping server rather than a stub, for the reason
`test_reconciler.py` gives: the decision under test is the server's answer, and
a stub would be a test of the stub.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from apps.accounts.models import User
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.workflows import activities
from apps.workflows import client as client_module
from apps.workflows.client import (
    MAX_CONCURRENT_ACTIVITIES,
    attach_interceptors,
    discovered_activities,
    discovered_workflows,
)
from apps.workflows.models import WorkflowRun
from apps.workflows.services import record_run, start_workflow, workflow_id
from apps.workflows.tests.cancelwork import WaitForeverWorkflow
from apps.workflows.types import ReconcileRuns
from apps.workflows.workflows import CANCELLED

pytestmark = pytest.mark.django_db(transaction=True)

TASK_QUEUE = "djb-tests-cancel"

#: How long to let the worker settle before cancelling. The workflow has to
#: reach its `wait_condition` for there to be anything to cancel — a cancel
#: delivered before the first workflow task is a different test.
SETTLE = 0.2


def worker_with_the_waiter(client: Client) -> Worker:
    """The real assembly, plus the one workflow that waits.

    Built here rather than through `build_worker` for `test_context.py`'s
    reason: a workflow that existed only to be cancelled would be a fixture
    shipped in production's discovery.
    """
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[*discovered_workflows(), WaitForeverWorkflow],
        activities=[*discovered_activities()],
        activity_executor=ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_ACTIVITIES,
            thread_name_prefix="temporal-activity-",
        ),
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )


def status_of(run: WorkflowRun) -> str:
    return str(WorkflowRun.objects.for_tenant(run.tenant).get(pk=run.pk).status)


def finished_at_of(run: WorkflowRun) -> Any:
    return WorkflowRun.objects.for_tenant(run.tenant).get(pk=run.pk).finished_at


# --- witness one: the finish seam ---------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_a_waiting_run_closes_its_row_as_cancelled(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 4: the ledger's third word is TRUE, not just declared.

    A run that waits, a cancel, and then the row — read through the ordinary
    tenant door — says `cancelled` and carries a `finished_at`. The path is the
    production `_finish` seam (rule 28's seam, which `cancelwork.py` wraps
    precisely so this is not a test of a test-only branch).

    Absent: the row says `running` for ever, which is what it did before this
    rung, and the cancel door's contract sentence would have been a promise
    nothing kept.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)

        async def connect() -> Client:
            return client

        monkeypatch.setattr(client_module, "get_client", connect)

        async with worker_with_the_waiter(client):
            run = await start_workflow(
                workflow="WaitForeverWorkflow",
                arg="stop me",
                tenant=tenant,
                user=owner,
                client=client,
                task_queue=TASK_QUEUE,
                id=workflow_id(tenant=tenant, app="workflows", noun="wait", key="seam"),
            )
            handle = client.get_workflow_handle(run.workflow_id)
            await asyncio.sleep(SETTLE)
            assert await run_db(status_of, run) == WorkflowRun.Status.RUNNING

            await handle.cancel()
            with pytest.raises(BaseException):  # noqa: B017,PT011
                # A cancelled execution does not return a result, and WHICH
                # exception the SDK wraps it in is the SDK's business — what
                # this test is about is the row, two lines down.
                await handle.result()

            description = await handle.describe()

    assert description.status is WorkflowExecutionStatus.CANCELED
    assert await run_db(status_of, run) == WorkflowRun.Status.CANCELLED
    assert await run_db(finished_at_of, run) is not None


def test_the_seams_literal_is_the_models_word() -> None:
    """The one seam a typo would break silently, pinned.

    `workflows.py` may not import `models` (house rule 9), so the status it
    writes is a string literal — and a literal that drifted from
    `WorkflowRun.Status.CANCELLED` would write a status no door can filter on,
    no admin can display and nothing would complain about.
    """
    assert CANCELLED == WorkflowRun.Status.CANCELLED


# --- witness two: the reconciler ----------------------------------------------


@pytest.mark.asyncio
async def test_the_reconciler_reads_a_cancelled_execution_as_cancelled(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same word from the other witness — the run that never reached its seam.

    A row stranded RUNNING whose execution the server reports as `CANCELED`.
    Previously the sweep had nowhere to put that and closed it `failed`
    with "The execution closed as CANCELED." in `error` — a deliberate stop
    recorded, permanently, as a breakage.

    `describe_execution` is replaced rather than a real execution cancelled,
    because the subject here is the MAPPING and not the RPC: the RPC's own
    answers are `test_reconciler.py`'s, and the seam test above drives a real
    cancellation end to end.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)

        async def connect() -> Client:
            return client

        monkeypatch.setattr(client_module, "get_client", connect)

        async def stopped(_client: Client, _workflow_id: str) -> Any:
            return WorkflowExecutionStatus.CANCELED

        monkeypatch.setattr(activities, "describe_execution", stopped)

        def plant() -> WorkflowRun:
            from django.utils import timezone

            row = record_run(
                tenant=tenant,
                workflow_id=workflow_id(
                    tenant=tenant, app="workflows", noun="wait", key="stranded"
                ),
                workflow_type="WaitForeverWorkflow",
            )
            WorkflowRun.objects.filter(pk=row.pk).update(
                started_at=timezone.now() - activities.RECONCILE_AFTER * 8
            )
            return row

        row = await run_db(plant)
        closed = await run_db(
            activities.reconcile_runs,
            ReconcileRuns(after_seconds=activities.reconcile_after_seconds()),
        )

    assert closed == 1
    swept = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=row.pk),
    )
    assert swept.status == WorkflowRun.Status.CANCELLED
    # And it explains nothing, because there is nothing to explain: the job
    # ended the way it was asked to.
    assert swept.error == ""
    assert swept.finished_at is not None


def test_the_closed_status_map_says_exactly_which_words_it_knows() -> None:
    """The mapping as a value, so the residue is a decision rather than an accident.

    Everything the server can close an execution as, minus the two words this
    product has: `TERMINATED`, `TIMED_OUT` and `CONTINUED_AS_NEW` fall through
    to `failed` with the real status named in `error`. That is deliberate and
    stated (`activities.CLOSED_AS`); pinning it here is what makes a future
    fourth word a diff somebody reads rather than a default somebody inherited.
    """
    assert activities.CLOSED_AS == {
        WorkflowExecutionStatus.COMPLETED: WorkflowRun.Status.COMPLETED,
        WorkflowExecutionStatus.CANCELED: WorkflowRun.Status.CANCELLED,
    }
