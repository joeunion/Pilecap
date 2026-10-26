"""A receipt's failed handler run, replayed by the tenant's administrator: the ledger replays."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client
from temporalio.api.enums.v1 import WorkflowIdReusePolicy
from temporalio.api.workflowservice.v1 import (
    ResetWorkflowExecutionRequest,
    ResetWorkflowExecutionResponse,
    StartWorkflowExecutionRequest,
)
from temporalio.client import Client as TemporalClient
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from apps.example.integrations import ONBOARDING_SLUG, handle_onboarding_delivery
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.example.tests.test_inbound_webhook import SECRET, _deliver, _run, _status
from pilecap import Actor
from pilecap.connections import create_connection, register_inbound_handler
from pilecap.tenancy import Tenant
from pilecap.testing import (
    WorkflowRun,
    attach_interceptors,
    build_worker,
    replace_workflow_client,
    run_db,
)

JSON = "application/json"
ALLOW_DUPLICATE = WorkflowIdReusePolicy.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE


def _reset_as_a_restart(client: TemporalClient) -> None:
    """The test server has no reset: the failed run's recorded start, started again under its id."""
    service = client.workflow_service

    async def reset(request: ResetWorkflowExecutionRequest, **_: Any) -> Any:
        failed = client.get_workflow_handle(
            request.workflow_execution.workflow_id, run_id=request.workflow_execution.run_id
        )
        async for event in failed.fetch_history_events():
            started = event.workflow_execution_started_event_attributes
            break
        answer = await service.start_workflow_execution(
            StartWorkflowExecutionRequest(
                namespace=request.namespace,
                workflow_id=request.workflow_execution.workflow_id,
                workflow_type=started.workflow_type,
                task_queue=started.task_queue,
                input=started.input,
                header=started.header,
                memo=started.memo,
                request_id=request.request_id,
                workflow_id_reuse_policy=ALLOW_DUPLICATE,
            )
        )
        return ResetWorkflowExecutionResponse(run_id=answer.run_id)

    setattr(service, "reset_workflow_execution", reset)  # noqa: B010 — a test's stand-in


@asynccontextmanager
async def _worker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TemporalClient]:
    """A worker on a time-skipping server; every dial, the replay's too, reaches it."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host

        async def connect() -> TemporalClient:
            dialled = attach_interceptors(
                await TemporalClient.connect(target, namespace=env.client.namespace)
            )
            _reset_as_a_restart(dialled)
            return dialled

        replace_workflow_client(monkeypatch, connect)
        client = attach_interceptors(env.client)
        async with build_worker(client):
            yield client


def _replay(api: Client, user: Any, run: Any) -> Any:
    api.force_login(user)
    return api.post(f"/api/v1/runs/{run.pk}/replay/", content_type=JSON)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_admin_replays_a_failed_receipt_run_and_the_receipt_is_handled(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    admin_member: Any,
    member: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    onboarding = await run_db(
        create_connection,
        tenant=tenant,
        actor=owner_actor,
        provider=ONBOARDING_SLUG,
        name="Onboarding",
        credentials={"webhook_secret": SECRET},
    )
    broken = [True]

    def not_ready_yet(*, received: Any, actor: Actor) -> None:
        if broken[0]:
            raise RuntimeError("the onboarding handler is not ready yet")
        handle_onboarding_delivery(received=received, actor=actor)

    register_inbound_handler(ONBOARDING_SLUG, not_ready_yet)
    try:
        async with _worker(monkeypatch) as client:
            widget = await run_db(create_widget, tenant=tenant, actor=owner_actor, name="Later")
            response = await run_db(_deliver, api, onboarding, widget.pk, delivery=str(uuid4()))
            assert response.status_code == 202, response.content
            receipt = str(response.json()["id"])
            failed = await run_db(_run, tenant, receipt)
            with pytest.raises(WorkflowFailureError):
                await client.get_workflow_handle(failed.workflow_id).result()
            failed = await run_db(_run, tenant, receipt)
            assert failed.status == WorkflowRun.Status.FAILED
            assert failed.started_by_id is None
            assert await run_db(_status, tenant, owner_actor, receipt) == "handler_failed"

            refused = await run_db(_replay, api, member, failed)
            assert refused.status_code == 403, refused.content

            broken[0] = False
            replayed = await run_db(_replay, api, admin_member, failed)
            assert replayed.status_code == 200, replayed.content
            await client.get_workflow_handle(failed.workflow_id).result()
    finally:
        register_inbound_handler(ONBOARDING_SLUG, handle_onboarding_delivery)

    again = await run_db(_run, tenant, receipt)
    assert again.pk == failed.pk
    assert again.run_id not in ("", failed.run_id)
    assert again.status == WorkflowRun.Status.COMPLETED
    assert await run_db(_status, tenant, owner_actor, receipt) == "handled"
    confirmed = await run_db(lambda: Widget.objects.for_tenant(tenant).get(pk=widget.pk))
    assert confirmed.onboarding_confirmed_at is not None
