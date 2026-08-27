"""Widget onboarding, end to end, against a real Temporal server.

`WorkflowEnvironment.start_time_skipping()` gives a real server with a skippable
clock, so the seven-day wait these tests drive takes milliseconds of wall clock
and is otherwise the genuine article: the real worker assembly, the real
interceptors, the real activities writing to the real database.

What is proved here is the part no diff shows:

* creating a widget **starts the run** — on the commit, with the deterministic id
  the row implies, from the service and not from a door;
* the first activity marks the row, through the service, as the system;
* the wait ends **either way** — a signal approves it, or a week passes and
  nobody did — and both are outcomes rather than failures;
* the **product itself can end it**: `approve_widget` derives the id from the
  row and signals on its transaction's commit, so the run finishes now instead
  of in seven simulated days, and asking again afterwards is refused.

`transaction=True` throughout: the activities run on worker threads with their
own connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.workflow import _Definition

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.asyncdb import run_db
from apps.core.exceptions import Conflict
from apps.core.models import Tenant
from apps.example.models import Widget
from apps.example.services import WIDGET_APPROVAL_SIGNAL, approve_widget, create_widget
from apps.example.types import WidgetOnboarded
from apps.example.workflows import WidgetOnboardingWorkflow
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

pytestmark = pytest.mark.django_db(transaction=True)

# The deadline `workflows.APPROVAL_DEADLINE` sets, in days — the number the
# clock has to get past for the timeout path to be the one under test.
APPROVAL_DAYS = 7


def onboarding_id(tenant: Tenant, widget: Widget) -> str:
    """The id `create_widget` will have used — derived, never remembered."""
    return workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk))


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook.

    The hook runs in whichever thread committed, on its own event loop, and dials
    a client of its own — exactly as it does in production. Here that dial has to
    reach the test environment rather than a dev server, so `get_client` is
    replaced with one that connects to the environment's address.
    """
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


@pytest.mark.asyncio
async def test_creating_a_widget_starts_its_onboarding_and_a_signal_finishes_it(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        # The worker polls the queue the service will start the run on — the
        # deployment's own, from settings. Nothing here names a queue by hand.
        async with build_worker(client):
            widget = await run_db(
                create_widget, tenant=tenant, actor=owner_actor, name="Onboard me"
            )
            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            await handle.signal("approve")
            result: WidgetOnboarded = await handle.result()

    assert result.widget_id == str(widget.pk)
    assert result.approved is True
    assert result.onboarded_at

    onboarded = await run_db(lambda: Widget.objects.for_tenant(tenant).get(pk=widget.pk))
    assert onboarded.onboarded_at is not None

    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).filter(type="WidgetOnboardingWorkflow").get()
    )
    assert run.workflow_id == onboarding_id(tenant, widget)


@pytest.mark.asyncio
async def test_nobody_approving_is_an_outcome_and_not_a_failure(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seven simulated days, no signal: the run completes and says nobody did."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(
                create_widget, tenant=tenant, actor=owner_actor, name="Nobody wants me"
            )
            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            # The environment skips time by itself only for a handle it returned
            # from `start_workflow`; this run was started by the service's
            # on-commit hook, so the clock is advanced here instead. Day-sized
            # steps rather than one jump, because the timer is created a moment
            # after the first activity finishes and a single leap could land
            # before it exists.
            for _ in range(APPROVAL_DAYS + 3):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(days=1))
            result: WidgetOnboarded = await handle.result()

    assert result.approved is False
    # It was still onboarded: the mark happens before the wait, which is the
    # whole reason the two are separate activities.
    assert result.onboarded_at
    onboarded = await run_db(lambda: Widget.objects.for_tenant(tenant).get(pk=widget.pk))
    assert onboarded.onboarded_at is not None


@pytest.mark.asyncio
async def test_a_finished_run_closes_its_visibility_row(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row the service wrote stops saying `running` when the run stops.

    `WorkflowRun` is the answer to "what durable work is this tenant waiting
    on", asked from the product's own database rather than from Temporal's UI.
    Until rung A11 the worked example never closed it: the execution reached
    COMPLETED and the row said `running` for ever (queue V6), which made the
    table worse than useless — every finished run looked like a stuck one.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(
                create_widget, tenant=tenant, actor=owner_actor, name="Closes its row"
            )
            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            await handle.signal("approve")
            await handle.result()

    run = await run_db(
        lambda: (
            WorkflowRun.objects.for_tenant(tenant)
            .filter(workflow_id=onboarding_id(tenant, widget))
            .get()
        )
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None
    assert run.error == ""


@pytest.mark.asyncio
async def test_the_workflow_announces_the_outcome_through_the_event_bus(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second activity publishes `example.widget.onboarded`, with the outcome.

    The bus is stood in for, because `apps/events` is a later rung and this test
    is about what the workflow *says*, not about how a delivery is retried. What
    is real is everything else: the workflow, the worker, the activity and the
    service that does the publishing.
    """
    from apps.example import services

    published: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append((name, payload))

    monkeypatch.setattr(services, "_event_bus", lambda: spy)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Heard")
            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            await handle.signal("approve")
            await handle.result()

    names = [name for name, _payload in published]
    assert "example.widget.created" in names
    assert "example.widget.onboarded" in names

    onboarded = next(payload for name, payload in published if name == "example.widget.onboarded")
    # The payload is the read schema plus what is true of the event itself.
    assert onboarded["id"] == str(widget.pk)
    assert onboarded["onboarded_at"] is not None
    assert onboarded["approved"] is True


# --- The approval door, against the real thing -------------------------------


def test_the_constant_matches_the_signal_the_workflow_declares() -> None:
    """One name in two files, held together by a test rather than by hope.

    `services.py` may not import `workflows.py` to read this string — a workflow
    module has to replay identically years from now and nothing outside the
    worker should be importing it — so the name is written twice. This is what
    makes the second copy safe: it reads the signal definition Temporal itself
    built from the decorator, and fails the day the two drift.
    """
    declared = _Definition.must_from_class(WidgetOnboardingWorkflow)
    assert WIDGET_APPROVAL_SIGNAL in declared.signals


@pytest.mark.asyncio
async def test_approving_through_the_service_ends_the_wait(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signal, end to end: a product that can finish its own work.

    Nothing here touches a handle. The service is the whole path — it derives
    the id from the row, authorizes, and hands `signal_workflow` the approval on
    its transaction's commit — and the run ends *now* rather than in seven
    simulated days. Before this there was no door in the product that could
    do this at all; the only way to end the wait was the Temporal CLI.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(
                create_widget, tenant=tenant, actor=owner_actor, name="Approve me"
            )
            await run_db(approve_widget, tenant=tenant, actor=owner_actor, widget=widget)

            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            result: WidgetOnboarded = await handle.result()
            assert (await handle.describe()).status is WorkflowExecutionStatus.COMPLETED

    assert result.approved is True

    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(
            workflow_id=onboarding_id(tenant, widget)
        )
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_approving_after_the_run_has_finished_is_refused(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The liveness wall, with a run that really did finish on a real server.

    The unit tests set the row's status by hand; this one lets the workflow end
    on its own and then asks again. Temporal would have answered a signal to a
    finished execution with an RPC error inside an on-commit hook nobody is
    watching — the refusal reaches the caller instead.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(
                create_widget, tenant=tenant, actor=owner_actor, name="Approve me once"
            )
            await run_db(approve_widget, tenant=tenant, actor=owner_actor, widget=widget)
            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            await handle.result()

            with pytest.raises(Conflict):
                await run_db(approve_widget, tenant=tenant, actor=owner_actor, widget=widget)
