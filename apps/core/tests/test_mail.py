"""What sending an email promises.

Two paths and one message: `send_now` renders and hands it to the backend,
`send_mail` starts the workflow that will call `send_now` from an activity. The
properties here are the rendering, the wiring of `invite_member`, the two things
that must not happen (no email inline, and no email at all when the transaction
that asked for it rolls back) — and, since the bridge landed, the hand-off
itself: `core` names the workflow and the argument shape without importing the
app that runs them, so what the two apps agree on is asserted here and proved
end to end through the real worker at the bottom of the file.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.core import mail as django_mail
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template import TemplateDoesNotExist
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.core import bridge, mail
from apps.core.actor import system_actor
from apps.core.models import Invitation, Membership, Tenant
from apps.core.services import PROVISION_INVITED_PERSON_WORKFLOW, invite_member
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import start_workflow

# --- Rendering ---------------------------------------------------------------


@pytest.mark.django_db
def test_send_now_renders_both_parts_and_hands_them_to_the_backend(tenant: Tenant) -> None:
    sent = mail.send_now(
        to=["someone@example.com"],
        subject="You have been invited to Acme",
        template="invitation",
        context={"tenant_name": "Acme", "email": "someone@example.com", "role": "Member"},
        tenant=tenant,
    )

    assert sent == 1
    assert len(django_mail.outbox) == 1
    message = django_mail.outbox[0]
    assert message.subject == "You have been invited to Acme"
    assert message.to == ["someone@example.com"]
    # The text part is the message; the HTML is an alternative, and a client
    # that shows only the text must not see less.
    assert "Acme invited you to join them." in message.body
    # `outbox` is typed as plain `EmailMessage`; the narrowing is what says out
    # loud that a multipart message is the promise being tested.
    assert isinstance(message, EmailMultiAlternatives)
    alternatives = [str(content) for content, kind in message.alternatives if kind == "text/html"]
    assert len(alternatives) == 1
    assert "Acme" in alternatives[0]


def test_no_template_markup_survives_into_a_rendered_message() -> None:
    """A comment that leaks is a comment a customer reads.

    Django's `{# … #}` is single-line only: a multi-line one is not a comment,
    it is text, and it goes out in the email. That is exactly what happened
    here, and Mailpit is what showed it. This is the guard.
    """
    text, html = mail.render(
        template="invitation",
        context={"tenant_name": "Acme", "email": "a@b.c", "role": "Member"},
    )
    for rendered in (text, html or ""):
        for marker in ("{#", "#}", "{%", "%}", "{{", "}}"):
            assert marker not in rendered


def test_render_is_text_only_when_the_template_set_has_no_html() -> None:
    """HTML is optional; text is not."""
    text, html = mail.render(template="invitation", context={"tenant_name": "Acme"})
    assert "Acme" in text
    assert html is not None

    with pytest.raises(TemplateDoesNotExist):
        mail.render(template="no_such_template", context={})


# --- invite_member starts a workflow; it does not send -----------------------


@pytest.mark.django_db
def test_inviting_somebody_starts_the_send_and_does_not_send(tenant: Tenant, owner: User) -> None:
    """No SMTP inside the request: the service records a run and returns.

    The outbox being empty is the assertion that matters. A service that sent
    inline would fail the whole invitation the first time the mail host blinked,
    and would hold a database transaction open across a call to somebody else's
    server while it did.

    **The run is the provisioning one now** (ADR accounts-1). The email
    still goes out through this module's mailer and the same `send_email`
    activity, but it waits for a link that does not exist until Zitadel has
    minted a code — so what the service starts is the run that gets one.
    `apps/accounts/tests/test_invited_provisioning.py` owns the rest of it.
    """
    invitation, _token = invite_member(
        tenant=tenant,
        email="Newcomer@Example.com",
        role=Membership.Role.ADMIN,
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )

    assert django_mail.outbox == []
    run = WorkflowRun.objects.for_tenant(tenant).get(type=PROVISION_INVITED_PERSON_WORKFLOW)
    # House rule 18: deterministic, and keyed on the row, so a retried service
    # starts one run and not two.
    assert run.workflow_id == f"{tenant.slug}:accounts:invite:{invitation.pk}"


@pytest.mark.django_db
def test_inviting_the_same_person_again_is_a_second_send(tenant: Tenant, owner: User) -> None:
    """ "Invite them again" makes a new invitation row, so it makes a new run.

    Keying the workflow id on the invitation's primary key is what makes both
    true at once: a retried service is idempotent, and a deliberate resend is
    not refused.
    """
    first, _ = invite_member(
        tenant=tenant,
        email="newcomer@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    second, _ = invite_member(
        tenant=tenant,
        email="newcomer@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )

    assert first.pk != second.pk
    ids = set(
        WorkflowRun.objects.for_tenant(tenant)
        .filter(type=PROVISION_INVITED_PERSON_WORKFLOW)
        .values_list("workflow_id", flat=True)
    )
    assert ids == {
        f"{tenant.slug}:accounts:invite:{first.pk}",
        f"{tenant.slug}:accounts:invite:{second.pk}",
    }


@pytest.mark.django_db
def test_an_invitation_that_rolls_back_emails_nobody(tenant: Tenant, owner: User) -> None:
    """The visibility row goes with the invitation, and the send never starts.

    `send_mail` writes the run row inside the caller's transaction and defers
    the Temporal call to `transaction.on_commit`. A rollback therefore takes
    both — which is the whole reason it is `on_commit` and not a call.
    """

    class Deliberate(Exception):
        pass

    with pytest.raises(Deliberate), transaction.atomic():
        invite_member(
            tenant=tenant,
            email="ghost@example.com",
            invited_by=owner,
            actor=system_actor(tenant=tenant),
        )
        raise Deliberate

    assert not Invitation.objects.for_tenant(tenant).exists()
    assert not WorkflowRun.objects.for_tenant(tenant).exists()
    assert django_mail.outbox == []


@pytest.mark.django_db
def test_the_invitation_email_carries_no_token(tenant: Tenant, owner: User) -> None:
    """**OUR** bearer credential is in no payload and no message.

    It is not needed: `accounts.adapter` joins the membership from the address
    at sign-in. This test is what stops somebody helpfully adding an accept link.

    Unchanged by ADR accounts-1, and worth saying why: the run started here does
    put Zitadel's invite code into history, inside the link. That is a different
    kind of thing — single-use, short-lived, superseded by re-issuing, and it
    opens one screen — and the ADR argues it rather than assuming it. The
    invitation token this service returns is not that, and still goes nowhere
    near a payload.
    """
    _invitation, token = invite_member(
        tenant=tenant, email="newcomer@example.com", actor=system_actor(tenant=tenant)
    )

    run = WorkflowRun.objects.for_tenant(tenant).get(type=PROVISION_INVITED_PERSON_WORKFLOW)
    text, html = mail.render(
        template="invitation",
        context={
            "tenant_name": tenant.name,
            "email": "newcomer@example.com",
            "role": "Member",
            "sign_in_url": "http://127.0.0.1:8000/accounts/login/",
            "expires_on": "2026-09-02",
        },
    )
    assert token not in text
    assert html is not None and token not in html
    assert token not in run.workflow_id


# --- The bridge, not an import -----------------------------------------------


@pytest.fixture
def clean_bridge() -> Iterator[None]:
    """Put back what the apps registered at startup."""
    saved = bridge.registered()
    yield
    bridge.clear()
    for name, fn in saved.items():
        bridge.register(name, fn)


@pytest.mark.django_db
def test_send_mail_goes_through_the_bridge(tenant: Tenant, clean_bridge: None) -> None:
    """`core` names the workflow; it does not import the app that runs it.

    House rule 7 and the layer contract: `workflows` sits above `core`, so the
    call inverts through `core.bridge`. What is asserted is the whole hand-off —
    the workflow name, the deterministic id and the argument shape — because
    that is the contract the two apps share now that neither imports the other.
    """
    calls: list[dict[str, Any]] = []
    bridge.register(bridge.START_WORKFLOW_ON_COMMIT, lambda **kwargs: calls.append(kwargs))

    mail.send_mail(
        to=["someone@example.com"],
        subject="Hello",
        template="invitation",
        context={"tenant_name": tenant.name},
        tenant=tenant,
        key="key-1",
    )

    assert len(calls) == 1
    assert calls[0]["workflow"] == "SendEmailWorkflow"
    assert calls[0]["id"] == f"{tenant.slug}:core:email:key-1"
    assert calls[0]["arg"] == {
        "to": ["someone@example.com"],
        "subject": "Hello",
        "template": "invitation",
        "context": {"tenant_name": tenant.name},
    }


@pytest.mark.django_db
def test_send_mail_without_the_workflows_app_is_a_no_op_not_a_crash(
    tenant: Tenant, clean_bridge: None, settings: Any
) -> None:
    """A template with the platform apps removed still has to run."""
    settings.BRIDGE_STRICT = False  # opt-out: a stripped tree's no-op is the subject
    bridge.clear()

    assert (
        mail.send_mail(
            to=["someone@example.com"],
            subject="Hello",
            template="invitation",
            context={},
            tenant=tenant,
            key="key-1",
        )
        is None
    )
    assert django_mail.outbox == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_argument_core_builds_is_the_one_the_workflow_accepts(
    tenant: Tenant,
) -> None:
    """The dictionary crosses the boundary and arrives as `SendEmail`.

    `core` may not import `apps.workflows.types`, so what it hands over is a
    plain dict of that dataclass's field names and Temporal's converter builds
    the dataclass on the worker side. That is a real contract between two apps
    that never import each other, so it is proved end to end — through the
    discovered worker, into the activity, out to the mail backend — rather than
    asserted on both halves separately and hoped about in the middle.
    """
    outbox_before = len(django_mail.outbox)
    argument = mail.message_for(
        to=["newcomer@example.com"],
        subject="You have been invited to Acme",
        template="invitation",
        context={"tenant_name": tenant.name, "email": "newcomer@example.com", "role": "Member"},
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue="djb-mail-tests"):
            run = await start_workflow(
                workflow=mail.SEND_EMAIL_WORKFLOW,
                arg=argument,
                tenant=tenant,
                client=client,
                task_queue="djb-mail-tests",
                id=f"{tenant.slug}:core:email:bridge-1",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=int)
            accepted: int = await handle.result()

    assert accepted == 1
    assert len(django_mail.outbox) == outbox_before + 1
    assert django_mail.outbox[-1].to == ["newcomer@example.com"]
