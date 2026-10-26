# golden: workflow onboard begin
# golden: workflow remind begin
"""Widget workflows, end to end, against a real Temporal server."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from apps.example.models import Widget
from apps.example.services import create_widget, update_widget
from apps.example.types import WidgetOnboarded, WidgetReminded
from apps.example.workflows import REMIND_BEFORE
from pilecap import Actor
from pilecap.accounts import User
from pilecap.events import EMIT
from pilecap.tenancy import Tenant
from pilecap.testing import (
    WorkflowRun,
    attach_interceptors,
    bridge_registry,
    build_worker,
    replace_workflow_client,
    run_db,
)
from pilecap.workflows import workflow_id

pytestmark = pytest.mark.django_db(transaction=True)


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    replace_workflow_client(monkeypatch, connect)
    return attach_interceptors(env.client)


# golden: workflow remind end
# The deadline `workflows.APPROVAL_DEADLINE` sets, in days.
APPROVAL_DAYS = 7


def onboarding_id(tenant: Tenant, widget: Widget) -> str:
    """The id `create_widget` will have used — derived, never remembered."""
    return workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk))


@pytest.mark.asyncio
async def test_creating_a_widget_starts_its_onboarding_and_a_signal_finishes_it(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        # The worker polls the queue the service will start the run on.
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
            # A run the on-commit hook started: the clock is advanced here, a day at a time.
            for _ in range(APPROVAL_DAYS + 3):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(days=1))
            result: WidgetOnboarded = await handle.result()

    assert result.approved is False
    # It was still onboarded: the mark happens before the wait.
    assert result.onboarded_at
    onboarded = await run_db(lambda: Widget.objects.for_tenant(tenant).get(pk=widget.pk))
    assert onboarded.onboarded_at is not None


@pytest.mark.asyncio
async def test_a_finished_run_closes_its_visibility_row(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row the service wrote stops saying `running` when the run stops."""
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
    """The second activity publishes `example.widget.onboarded`, with the outcome."""

    published: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append((name, payload))

    monkeypatch.setitem(bridge_registry, EMIT, spy)

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


# --- An archived widget, mid-run ---------------------------------------------


@pytest.mark.asyncio
async def test_an_archived_widgets_onboarding_refuses_archived_and_the_run_says_so(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    admin_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archived while the run waits: the next activity refuses `archived`, once."""
    from apps.example.services import archive_widget

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(
                create_widget, tenant=tenant, actor=owner_actor, name="Archived mid-run"
            )
            handle = client.get_workflow_handle(
                onboarding_id(tenant, widget), result_type=WidgetOnboarded
            )
            # The first activity has marked it before the wait begins.
            for _ in range(20):
                marked = await run_db(
                    lambda: Widget.objects.for_tenant(tenant).get(pk=widget.pk).onboarded_at
                )
                if marked is not None:
                    break
                await env.sleep(timedelta(seconds=1))
            await run_db(archive_widget, tenant=tenant, actor=admin_actor, widget=widget)
            for _ in range(APPROVAL_DAYS + 3):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(days=1))
            status = (await handle.describe()).status

    assert status is WorkflowExecutionStatus.FAILED
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(
            workflow_id=onboarding_id(tenant, widget)
        )
    )
    assert run.status == WorkflowRun.Status.FAILED
    # The code once, as the failure's type, then the sentence.
    assert "ApplicationError: archived: This is archived" in run.error, run.error
    assert "archived: archived" not in run.error, run.error


# golden: workflow onboard end
# golden: workflow remind begin
# --- The reminder: asleep until the row's moment, one act, closed ---------------------


def reminder_id(tenant: Tenant, widget: Widget) -> str:
    """The id `update_widget` will have used — derived from the row, never remembered."""
    return workflow_id(tenant=tenant, app="example", noun="widget", key=f"remind-{widget.pk}")


def moment(days: float) -> datetime:
    """A `due_at` this many days from now, past `REMIND_BEFORE`."""
    return datetime.now(UTC) + REMIND_BEFORE + timedelta(days=days)


async def _reminded_at(tenant: Tenant, widget: Widget) -> datetime | None:
    return await run_db(lambda: Widget.objects.for_tenant(tenant).get(pk=widget.pk).reminded_at)


async def _until_closed(env: WorkflowEnvironment, handle: Any, days: int) -> None:
    """Advance the skipped clock a day at a time until the run stops, at most `days` days."""
    for _ in range(days):
        if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
            return
        await env.sleep(timedelta(days=1))


@pytest.mark.asyncio
async def test_the_reminder_fires_once_at_the_moment_and_closes(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[str] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append(name)

    monkeypatch.setitem(bridge_registry, EMIT, spy)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Due")
            widget = await run_db(
                update_widget, tenant=tenant, actor=owner_actor, widget=widget, due_at=moment(3)
            )
            handle = client.get_workflow_handle(
                reminder_id(tenant, widget), result_type=WidgetReminded
            )
            await env.sleep(timedelta(days=2))
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
            assert await _reminded_at(tenant, widget) is None
            await _until_closed(env, handle, 5)
            result: WidgetReminded = await handle.result()

    assert result.widget_id == str(widget.pk) and result.reminded_at
    assert await _reminded_at(tenant, widget) is not None
    assert published.count("example.widget.reminded") == 1
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(workflow_id=reminder_id(tenant, widget))
    )
    assert run.status == WorkflowRun.Status.COMPLETED and run.finished_at is not None


@pytest.mark.asyncio
async def test_the_run_id_is_deterministic(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The id is the row's, so a second write naming a moment asks for the same run."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Once")
            for days in (2, 2.5):
                widget = await run_db(
                    update_widget,
                    tenant=tenant,
                    actor=owner_actor,
                    widget=widget,
                    due_at=moment(days),
                )
            handle = client.get_workflow_handle(
                reminder_id(tenant, widget), result_type=WidgetReminded
            )
            await _until_closed(env, handle, 6)
            await handle.result()

    runs = await run_db(
        lambda: list(
            WorkflowRun.objects.for_tenant(tenant)
            .filter(type="WidgetReminderWorkflow")
            .values_list("workflow_id", flat=True)
        )
    )
    assert runs == [reminder_id(tenant, widget)]


@pytest.mark.asyncio
async def test_a_moment_already_past_reminds_at_once(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Late")
            widget = await run_db(
                update_widget, tenant=tenant, actor=owner_actor, widget=widget, due_at=moment(-2)
            )
            handle = client.get_workflow_handle(
                reminder_id(tenant, widget), result_type=WidgetReminded
            )
            result: WidgetReminded = await handle.result()

    assert result.reminded_at
    assert await _reminded_at(tenant, widget) is not None


@pytest.mark.asyncio
async def test_a_moved_moment_is_slept_to_again(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run re-reads the row when it wakes: a moment moved later is waited for, not missed."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Moved")
            widget = await run_db(
                update_widget, tenant=tenant, actor=owner_actor, widget=widget, due_at=moment(1)
            )
            widget = await run_db(
                update_widget, tenant=tenant, actor=owner_actor, widget=widget, due_at=moment(4)
            )
            handle = client.get_workflow_handle(
                reminder_id(tenant, widget), result_type=WidgetReminded
            )
            await env.sleep(timedelta(days=2))
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
            assert await _reminded_at(tenant, widget) is None
            await _until_closed(env, handle, 6)
            result: WidgetReminded = await handle.result()

    assert result.reminded_at
    assert await _reminded_at(tenant, widget) is not None


@pytest.mark.asyncio
async def test_a_cleared_moment_ends_the_run_without_acting(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Clear")
            widget = await run_db(
                update_widget, tenant=tenant, actor=owner_actor, widget=widget, due_at=moment(2)
            )
            widget = await run_db(
                update_widget, tenant=tenant, actor=owner_actor, widget=widget, clear_due_at=True
            )
            handle = client.get_workflow_handle(
                reminder_id(tenant, widget), result_type=WidgetReminded
            )
            await _until_closed(env, handle, 5)
            result: WidgetReminded = await handle.result()

    assert result.reminded_at == ""
    assert await _reminded_at(tenant, widget) is None
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(workflow_id=reminder_id(tenant, widget))
    )
    assert run.status == WorkflowRun.Status.COMPLETED


# golden: workflow remind end
