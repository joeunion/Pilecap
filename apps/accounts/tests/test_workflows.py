"""`SyncIdentityConfigWorkflow`, end to end, against a real Temporal server.

`WorkflowEnvironment.start_time_skipping()` gives the genuine article — the real
worker assembly from the real discovery, the real interceptors carrying the
tenant and the acting hat on the workflow's headers, the real activity writing
to the real database. What is *not* real is Zitadel: the client's socket is a
dictionary, exactly as in `test_zitadel.py`, because ident-5's posture is that
the suite never dials an identity instance.

What is proved here is the part neither the service test nor the activity test
can prove alone: **the service's intent reaches the activity with the tenant and
the hat intact, and the resource id comes home on the row** — the whole
row-is-the-intent loop, once, through the machinery a deployment actually runs.

`transaction=True`: the activities run on worker threads with their own
connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from django.core import mail as django_mail
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from apps.accounts import zitadel
from apps.accounts.models import SsoConnection, User
from apps.accounts.services import (
    SYNC_IDENTITY_CONFIG_WORKFLOW,
    _identity_config_key,
    create_sso_connection,
)
from apps.accounts.tests.conftest import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeZitadel
from apps.accounts.types import IdentityConfigApplied, InvitedPersonProvisioned
from apps.core.actor import Actor, system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.core.services import PROVISION_INVITED_PERSON_WORKFLOW, invite_member
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def instance(monkeypatch: pytest.MonkeyPatch, settings: Any) -> FakeZitadel:
    """The same stubbed socket the client tests use, for the worker's thread."""
    fake = FakeZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"

    @contextmanager
    def stubbed() -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    return fake


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


@pytest.mark.asyncio
async def test_configuring_a_connection_materialises_it_and_records_what_it_became(
    instance: FakeZitadel,
    tenant: Tenant,
    owner_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**`create_sso_connection` is the trigger now** (ADR ident-6).

    Before this, a connection was configured and then, separately, asked to
    be materialised; a door that forgot the second call left a customer with a
    row and no identity provider. The write is the ask, and this is the test that
    says so end to end — through the real worker, the real interceptors carrying
    the tenant and the hat, and the real activity.

    The connection is built **inside** the environment for the same reason: the
    create now commits and fires an on-commit hook, and a hook that fired before
    the test server existed would dial the deployment's own Temporal.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        # The worker polls the queue the service will start the run on — the
        # deployment's own, from settings. Nothing here names a queue by hand.
        async with build_worker(client):
            connection = await run_db(
                create_sso_connection,
                tenant=tenant,
                actor=owner_actor,
                name="Acme Okta",
                # The same three values `conftest.sso_connection` uses, imported
                # rather than retyped: the fixture and this test have to agree
                # about what is being materialised or the assertion is about
                # nothing.
                issuer=ISSUER,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                email_domains=["acme.com"],
            )
            expected = workflow_id(
                tenant=tenant,
                app="accounts",
                noun="identity_config",
                key=_identity_config_key(connection),
            )
            handle = client.get_workflow_handle(expected, result_type=IdentityConfigApplied)
            applied: IdentityConfigApplied = await handle.result()

    assert applied.created is True
    assert applied.resource_id

    synced = await run_db(lambda: SsoConnection.objects.for_tenant(tenant).get(pk=connection.pk))
    assert synced.zitadel_idp_id == applied.resource_id
    assert synced.sync_state == SsoConnection.SyncState.APPLIED

    # A11: the visibility row is closed, not left saying `running` beside an
    # execution Temporal has marked COMPLETED.
    run = await run_db(
        lambda: (
            WorkflowRun.objects.for_tenant(tenant).filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW).get()
        )
    )
    assert run.workflow_id == expected
    assert run.status == WorkflowRun.Status.COMPLETED

    # And the object is really there, under the name the drift report looks for.
    assert len(instance.idps) == 1


@pytest.mark.asyncio
async def test_inviting_somebody_provisions_them_and_mails_them_a_real_link(
    instance: FakeZitadel,
    tenant: Tenant,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invitation-to-account path, end to end through the machinery a deployment actually runs.

    The three things only this test can prove together: `invite_member`'s commit
    reaches `ProvisionInvitedPersonWorkflow`; the workflow's merge puts the link
    the FIRST activity minted into the message the SECOND activity sends; and
    the run row closes (house rule 28). The activity that sends is
    `apps.workflows.activities.send_email` — the existing one, referenced and
    not edited — so what lands in the outbox is what a real deployment's mail
    host would have been handed.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            invitation = await run_db(
                lambda: invite_member(
                    tenant=tenant,
                    email="ada.lovelace@example.com",
                    invited_by=owner,
                    actor=system_actor(tenant=tenant),
                )[0]
            )
            expected = workflow_id(
                tenant=tenant, app="accounts", noun="invite", key=str(invitation.pk)
            )
            handle = client.get_workflow_handle(expected, result_type=InvitedPersonProvisioned)
            provisioned: InvitedPersonProvisioned = await handle.result()

    assert provisioned.created is True
    assert provisioned.delivered == 1
    # The result a person opens in the Temporal UI carries no credential.
    assert "code=" not in json.dumps(dataclasses.asdict(provisioned))

    # The person exists in the identity platform, with no password.
    assert len(instance.users) == 1
    minted = instance.invite_codes[provisioned.zitadel_user_id][-1]

    # And the email carries the link that code is in — the whole point.
    assert len(django_mail.outbox) == 1
    message = django_mail.outbox[-1]
    assert message.to == ["ada.lovelace@example.com"]
    assert "/ui/login/user/invite?userID=" in message.body
    assert minted in message.body
    assert "sign up" not in message.body.lower()

    run = await run_db(
        lambda: (
            WorkflowRun.objects.for_tenant(tenant)
            .filter(type=PROVISION_INVITED_PERSON_WORKFLOW)
            .get()
        )
    )
    assert run.workflow_id == expected
    assert run.status == WorkflowRun.Status.COMPLETED


@pytest.mark.asyncio
async def test_a_provisioning_run_that_fails_still_closes_its_row(
    instance: FakeZitadel,
    tenant: Tenant,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """House rule 28's other half: **the ledger never lies by omission.**

    A `WorkflowRun` left at `running` beside an execution Temporal has marked
    FAILED is worse than no row at all — it is a row that says work is still
    happening.

    The refusal is raised **non-retryable** so the run reaches its terminal
    state on the first attempt. A plain `ZitadelError` would be right about the
    shape and wrong for a test: the workflow's policy would retry it six times
    over half a minute of skipped time, and what is under test here is the
    finish seam, not the backoff. Non-retryable is also a real path — an
    activity that knows the answer will not change says so exactly this way.
    """

    def refuse(**_kwargs: Any) -> Any:
        raise ApplicationError(
            "Zitadel POST /v2/users/human answered 500: boom", non_retryable=True
        )

    monkeypatch.setattr(zitadel, "ensure_invited_user", refuse)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            invitation = await run_db(
                lambda: invite_member(
                    tenant=tenant,
                    email="doomed@example.com",
                    invited_by=owner,
                    actor=system_actor(tenant=tenant),
                )[0]
            )
            expected = workflow_id(
                tenant=tenant, app="accounts", noun="invite", key=str(invitation.pk)
            )
            handle = client.get_workflow_handle(expected)
            with pytest.raises(WorkflowFailureError):
                await handle.result()

    assert django_mail.outbox == []
    run = await run_db(
        lambda: (
            WorkflowRun.objects.for_tenant(tenant)
            .filter(type=PROVISION_INVITED_PERSON_WORKFLOW)
            .get()
        )
    )
    assert run.status == WorkflowRun.Status.FAILED
    assert run.error
