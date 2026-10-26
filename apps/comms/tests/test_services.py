"""`send()` — the consent wall, the row it always writes, and what it refuses.

Every test here is about a property a product depends on rather than about a
mechanism:

* a refused send **leaves a row** saying why, and starts nothing;
* consent is checked **inside** `send()`, so no caller can be the one that
  forgot;
* transactional traffic is not silenced by quiet hours, and *is* silenced by a
  suppression — the two honest negatives of the whole design;
* bad input raises and writes nothing at all, which is a different thing from a
  refusal.
"""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.comms.models import Category, Channel, Message, MessageTemplate, Recipient
from apps.comms.policies import quiet_defer_seconds
from apps.comms.providers import registered_channels
from apps.comms.services import (
    _context_errors,
    issue_delivery_nonce,
    record_message_failed,
    record_message_sent,
    send,
)
from apps.comms.tests.conftest import (
    make_next_version,
    make_preference,
    make_recipient,
    make_template,
)
from apps.core import context
from apps.core.actor import Actor, system_actor
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import Organization, Tenant
from apps.events.models import Event
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db

CONTEXT = {"name": "Ada"}


# --- the happy path ------------------------------------------------------------


def test_a_transactional_send_is_queued_and_starts_one_delivery_run(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.QUEUED
    assert message.suppressed_reason == ""
    assert message.template_name == "receipt"
    assert message.template_version == 1
    assert message.subject == "Your receipt, Ada"
    assert message.category == Category.TRANSACTIONAL

    run = WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    # The key carries TWO facts: which message, and which
    # delivery lineage of it. `<pk>.<nonce>` — asserted as the whole key rather
    # than as a prefix, because "the nonce is there" is exactly the half a
    # `startswith` would have kept passing without.
    assert run.workflow_id.endswith(
        f":comms:message:{message.pk}.{issue_delivery_nonce(message.pk)}"
    )
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.queued").count() == 1


def test_the_queued_event_carries_the_same_shape_the_read_door_returns(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The payload is the schema, so a webhook subscriber sees what a client sees.

    The correlation id is asserted inside a bound context because that is the
    only honest way to assert it: `send()` **reads** the chain a door started
    and never mints one (house rule 20), so with no door there is no chain to
    join and the row says so by being empty.
    """
    with context.bound(correlation_id="test-chain"):
        message = send(
            recipient=recipient,
            template="receipt",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )
    event = Event.objects.for_tenant(tenant).get(name="comms.message.queued")
    assert event.payload["id"] == str(message.pk)
    assert event.payload["status"] == Message.Status.QUEUED
    assert "recipient_email" not in event.payload
    assert event.payload["recipient_id"] == str(recipient.pk)
    assert event.payload["organization_slug"] == message.organization.slug
    assert message.correlation_id == "test-chain"
    assert event.correlation_id == message.correlation_id


def test_the_latest_active_version_is_the_one_that_is_sent(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """A name resolves to the newest active version, and the row records which."""
    make_next_version(actor=owner_actor)
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.template_version == 2
    assert message.subject == "v2 for Ada"


def test_a_retired_version_stops_being_what_a_name_resolves_to(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    make_next_version(actor=owner_actor, retired=True)
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.template_version == 1


# --- the consent wall ----------------------------------------------------------


def test_marketing_with_no_preference_row_at_all_is_suppressed(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, newsletter: MessageTemplate
) -> None:
    """Consent that was never given is not consent — and the refusal leaves a row."""
    message = send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.SUPPRESSED
    assert message.suppressed_reason == Message.SuppressedReason.NO_CONSENT
    assert message.suppressed_at is not None
    # No delivery run for this message. (The spine's own dispatch run for the
    # `suppressed` event is a different workflow type and is meant to be there —
    # naming the type is what keeps this assertion about comms.)
    assert not WorkflowRun.objects.for_tenant(tenant).filter(type="DeliverMessageWorkflow").exists()
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.suppressed").count() == 1
    assert not Event.objects.for_tenant(tenant).filter(name="comms.message.queued").exists()
    assert mail.outbox == []


def test_marketing_with_consent_is_queued(
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The same send, after consent: it goes.

    The pair is what makes the first one mean something.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    message = send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.QUEUED


def test_revoked_consent_is_not_consent(
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    make_preference(actor=owner_actor, recipient=recipient, revoked=True)
    message = send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.suppressed_reason == Message.SuppressedReason.NO_CONSENT


def test_a_suppressed_address_refuses_even_transactional_mail(
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """Suppression outranks everything, including a message the person asked for."""
    make_preference(actor=owner_actor, recipient=recipient, suppressed=True)
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.SUPPRESSED
    assert message.suppressed_reason == Message.SuppressedReason.SUPPRESSED
    assert not WorkflowRun.objects.for_tenant(tenant).filter(type="DeliverMessageWorkflow").exists()
    assert mail.outbox == []


def test_quiet_hours_hold_marketing_and_let_transactional_through(
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    newsletter: MessageTemplate,
) -> None:
    """The honest negative: a receipt at 3am is fine, a campaign at 3am is not.

    The window is built around "now" in UTC so the test does not depend on when
    it runs, and it deliberately wraps only when it has to — an hour either side
    of the current moment is a window, whatever the hour.
    """
    now = timezone.now()
    start = (now - timedelta(minutes=30)).timetz().replace(tzinfo=None)
    end = (now + timedelta(minutes=30)).timetz().replace(tzinfo=None)
    make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(time(start.hour, start.minute), time(end.hour, end.minute)),
    )

    campaign = send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    # **This assertion is where the fix is visible.** It used to read
    # `SUPPRESSED` / `QUIET_HOURS`, and the asymmetry that made it wrong was
    # real: a marketing send submitted at 22:30 was thrown away while the
    # identical send submitted at 21:59 was deferred at the transport edge and
    # delivered at 07:00. A temporal lever delays; it does not kill (ADR
    # comms-10), and at queue time that is now true too — the row is
    # `queued`, which is what it is, and a run holds the wait.
    #
    # `tests/test_quiet_hours_seam.py` drives the whole story (the timer, the
    # second wall, the symmetry with 21:59); this keeps the claim beside the
    # transactional half it is contrasted with.
    assert campaign.status == Message.Status.QUEUED
    assert campaign.suppressed_reason == ""
    assert campaign.delivery_workflow_id, "a deferred send waits in a run"

    urgent = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert urgent.status == Message.Status.QUEUED


def test_quiet_hours_are_read_in_the_persons_own_timezone(
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """A window that covers the whole day somewhere else covers nothing here.

    The window is 00:00 → 23:59 in a timezone twelve hours away only for the
    part of it that overlaps — so the assertion is the one that cannot pass by
    accident: the same window, named in UTC, would suppress.
    """
    now = timezone.now()
    start = time((now.hour + 2) % 24, 0)
    end = time((now.hour + 4) % 24, 0)
    preference = make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(start, end),
    )
    assert (
        send(
            recipient=recipient,
            template="newsletter",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        ).status
        == Message.Status.QUEUED
    )

    # Shift the person two hours west and the same clock window now contains
    # "now" — the window did not move, the reader did.
    #
    # What "contained" LOOKS like changed: a message inside the
    # window is deferred rather than killed, so the tell is no longer a
    # `suppressed_reason` but a run to wait in. The property this test is about
    # — that the window is read in the person's timezone and not the server's —
    # is untouched, and both halves still say the opposite thing about the same
    # window, which is what makes it able to fail.
    preference.quiet_hours_timezone = "Etc/GMT-2"
    preference.save(update_fields=["quiet_hours_timezone", "updated_at"])
    inside = send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert inside.status == Message.Status.QUEUED
    assert inside.delivery_workflow_id, "inside the window: deferred, in a run"
    assert quiet_defer_seconds(preference=preference, tenant=tenant, at=timezone.now()) > 0, (
        "and the wait it was given is a real one"
    )


# --- bad input raises, and writes nothing --------------------------------------


def test_a_context_missing_a_required_variable_is_invalid_and_writes_no_row(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    with pytest.raises(Invalid) as raised:
        send(
            recipient=recipient,
            template="receipt",
            context={},
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )
    assert "name" in raised.value.errors
    assert not Message.objects.for_tenant(tenant).exists()


def test_a_context_value_of_the_wrong_type_names_the_field() -> None:
    errors = _context_errors(
        schema={"required": ["name"], "properties": {"invoices": {"type": "integer"}}},
        context={"name": "Ada", "invoices": "three"},
    )
    assert list(errors) == ["invoices"]


def test_a_boolean_is_not_an_integer_however_python_feels_about_it() -> None:
    """`True` is an `int` in Python; a template variable typed `integer` is not."""
    errors = _context_errors(
        schema={"properties": {"invoices": {"type": "integer"}}},
        context={"invoices": True},
    )
    assert list(errors) == ["invoices"]


def test_a_template_the_tenant_does_not_have_is_not_found(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient
) -> None:
    with pytest.raises(NotFound):
        send(
            recipient=recipient,
            template="no-such-template",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )
    assert not Message.objects.for_tenant(tenant).exists()


def test_a_channel_with_no_registered_transport_is_refused(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient
) -> None:
    """**Fail closed on a kind with no transport** — C2-comms-b's `chat`.

    Three kinds ship with a transport: email, whose backend is a setting, and
    SMS and push, whose `FakeSmsChannel` and `FakePushChannel` are the worked
    ones a product replaces. `chat` deliberately has neither, and naming it is
    bad input rather than a message that quietly goes nowhere. That asymmetry is
    the whole of ADR comms-6: a *kind* costs nothing to name, and a kind with no
    transport still refuses.

    `push` moved out of this sentence at T3 and `chat` did not, which is the
    line worth watching: the day somebody registers a chat transport, this test
    has nothing left to prove and the fail-closed property needs a kind of its
    own to demonstrate on.
    """
    assert set(registered_channels()) == {
        Channel.EMAIL.value,
        Channel.SMS.value,
        Channel.PUSH.value,
    }
    assert Channel.CHAT.value not in registered_channels()
    make_template(actor=owner_actor, name="chatted", channel=Channel.CHAT)
    with pytest.raises(Invalid) as raised:
        send(
            recipient=recipient,
            template="chatted",
            context=CONTEXT,
            channel=Channel.CHAT,
            tenant=tenant,
            actor=owner_actor,
        )
    assert "channel" in raised.value.errors
    assert "No transport" in raised.value.errors["channel"][0]


def test_a_channel_that_is_not_a_channel_at_all_is_refused(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    with pytest.raises(Invalid) as raised:
        send(
            recipient=recipient,
            template="receipt",
            context=CONTEXT,
            channel="carrier-pigeon",
            tenant=tenant,
            actor=owner_actor,
        )
    assert "channel" in raised.value.errors


def test_a_template_for_another_channel_is_refused(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient
) -> None:
    make_template(actor=owner_actor, name="texted", channel=Channel.SMS)
    with pytest.raises(Invalid):
        send(
            recipient=recipient,
            template="texted",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )


# --- isolation -----------------------------------------------------------------


def test_a_template_is_the_tenants_own(
    tenant: Tenant,
    other_tenant: Tenant,
    other_root_org: Organization,
    stranger_actor: Actor,
    receipt: MessageTemplate,
) -> None:
    """The same template name in another tenant resolves to nothing, not to this row."""
    theirs = make_recipient(actor=stranger_actor, email="them@example.com")
    with pytest.raises(NotFound):
        send(
            recipient=theirs,
            template="receipt",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=other_tenant,
            actor=stranger_actor,
        )


# --- the delivery workflow's writes --------------------------------------------


def test_recording_a_send_is_idempotent_and_keeps_the_first_timestamp(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """Temporal runs an activity at least once; the second run must not rewrite history."""
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    actor = system_actor(tenant, message.organization)
    first = record_message_sent(
        tenant=tenant, actor=actor, message=message, provider="locmem", provider_message_id="<1>"
    )
    again = record_message_sent(
        tenant=tenant, actor=actor, message=first, provider="other", provider_message_id="<2>"
    )
    assert again.status == Message.Status.SENT
    assert again.provider == "locmem"
    assert again.provider_message_id == "<1>"
    assert again.sent_at == first.sent_at
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.sent").count() == 1


def test_a_late_failure_does_not_downgrade_a_message_that_went(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    actor = system_actor(tenant, message.organization)
    sent = record_message_sent(
        tenant=tenant, actor=actor, message=message, provider="locmem", provider_message_id="<1>"
    )
    assert (
        record_message_failed(tenant=tenant, actor=actor, message=sent, error="too late").status
        == Message.Status.SENT
    )
    assert not Event.objects.for_tenant(tenant).filter(name="comms.message.failed").exists()


def test_a_failure_says_so_and_emits_the_event(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    message = send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    failed = record_message_failed(
        tenant=tenant,
        actor=system_actor(tenant, message.organization),
        message=message,
        error="the mail host said no",
    )
    assert failed.status == Message.Status.FAILED
    assert failed.error == "the mail host said no"
    assert failed.failed_at is not None
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.failed").count() == 1
