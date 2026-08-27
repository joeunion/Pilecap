"""This app's one workflow, driven the way the schedule drives it.

Separate from `test_lifecycle.py` because of one word: `transaction=True`. A
time-skipping `WorkflowEnvironment` runs the worker on other threads with other
connections, so rows a test's own transaction is still holding are invisible to
it — the seed has to be COMMITTED. That marker truncates between tests, which is
the right price for one test and the wrong one for a module of fifteen, so the
fast declaration tests keep their own file.

What is proved here is the wiring nobody can see from a diff: that the
`ScheduleDeclaration` this app exports, taken as-is and started against a worker
holding exactly this app's declared `WORKFLOWS` and `ACTIVITIES`, deletes the
rows the declaration on `InboundWebhook` promises it deletes — and leaves the
open promise alone.

**The worker is built here rather than borrowed from `apps.workflows.client`,
and that is the layer contract rather than a preference**: `apps.connections`
may not import the platform app, in tests any more than in production (the
exemption `apps.events.tests` carries lives in `pyproject.toml`, which this
rung's territory does not include). What is lost is the assertion that the
platform's discovery finds this app's lists; what stands in for it is
`test_lifecycle.py`'s check that the three conventional attributes are exported
under the names `_discover` looks for, the platform app's own
`test_machinery_lifetime.py`, and house rule 31's tooth, which walks the whole
chain through the live registry on every gate run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from apps.connections import activities
from apps.connections import workflows as connections_workflows
from apps.connections.models import Connection, InboundWebhook
from apps.connections.tests.test_lifecycle import TASK_QUEUE, WELL_PAST, store
from apps.connections.types import PurgeOutcome
from apps.core.asyncdb import run_db
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_the_declared_machine_driven_end_to_end(
    tenant: Tenant, connection: Connection
) -> None:
    """The schedule's own action, started against a real worker. Nothing hand-written.

    The workflow name, the argument, the deterministic id and the task queue are
    all read off `PURGE_INBOUND_WEBHOOKS.schedule(...)` — the one value both
    lifetime classes read the machine out of — so this test cannot pass while
    the declaration points somewhere else. A structural assertion about the
    source would miss exactly that.

    The worker holds this app's own `WORKFLOWS` and `ACTIVITIES` lists rather
    than a hand-written pair, so a class that fell out of either one takes this
    test with it.

    A `ThreadPoolExecutor` because the activity is a plain `def`: the ORM is
    synchronous and a sync activity is a sync query on a thread where one
    belongs. This is what `apps.workflows.client.build_worker` does for the
    deployment.
    """
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    def seed() -> None:
        store(
            tenant=tenant,
            connection=connection,
            delivery_id="old-processed",
            status=InboundWebhook.Status.HANDED_OFF,
            handed_off_days=WELL_PAST,
        )
        store(
            tenant=tenant,
            connection=connection,
            delivery_id="old-unprocessed",
            status=InboundWebhook.Status.RECEIVED,
            handed_off_days=None,
        )

    await run_db(seed)

    action: Any = activities.PURGE_INBOUND_WEBHOOKS.schedule(TASK_QUEUE).action

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="temporal-activity-") as pool:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=connections_workflows.WORKFLOWS,
                activities=activities.ACTIVITIES,
                activity_executor=pool,
            ):
                result: PurgeOutcome = await env.client.execute_workflow(
                    action.workflow,
                    *action.args,
                    id=action.id,
                    task_queue=action.task_queue,
                    result_type=PurgeOutcome,
                )

    assert result == PurgeOutcome(inbound_webhooks=1)
    remaining = await run_db(
        lambda: list(
            InboundWebhook.objects.for_tenant(tenant).values_list("delivery_id", flat=True)
        )
    )
    assert remaining == ["old-unprocessed"]
