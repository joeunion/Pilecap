"""The product ending its own onboarding wait: `approve_widget`, against a real Temporal server."""

from __future__ import annotations

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.workflow import _Definition

from apps.example.services import WIDGET_APPROVAL_SIGNAL, approve_widget, create_widget
from apps.example.tests.test_workflows import _local_client, onboarding_id
from apps.example.types import WidgetOnboarded
from apps.example.workflows import WidgetOnboardingWorkflow
from pilecap import Actor, Conflict
from pilecap.accounts import User
from pilecap.tenancy import Tenant
from pilecap.testing import WorkflowRun, build_worker, run_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_the_constant_matches_the_signal_the_workflow_declares() -> None:
    """One name in two files, held together by a test rather than by hope."""
    declared = _Definition.must_from_class(WidgetOnboardingWorkflow)
    assert WIDGET_APPROVAL_SIGNAL in declared.signals


@pytest.mark.asyncio
async def test_approving_through_the_service_ends_the_wait(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signal, end to end: a product that can finish its own work."""
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
    """The liveness wall, with a run that really did finish on a real server."""
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
