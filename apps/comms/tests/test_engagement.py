"""Opened and clicked: witnessed history, in its own population.

ADR comms-9's engagement half (ING-4 T1). Four claims, and every test here is
one of them:

* **an engagement never mutates `Message.status`.** An "open" is a provider's
  *inference* — Apple's Mail Privacy Protection fetches every image in every
  message a user receives, so a false open is not an edge case, it is the
  default on one of the two biggest mail clients. Delivery truth and read
  inference are two populations on purpose, and folding them would launder an
  inference into a fact;
* **it is witnessing, not consent.** Recording an engagement never suppresses,
  never sends, and is recorded even for a recipient who has since been
  suppressed. A fact about the past is not permission for the future;
* **it is append-only, by declaration** (house rules 20 and 31). The runtime
  belt (`apps.core.lifecycle.AppendOnlyViolation`) refuses an update or a
  delete at the last possible moment, and this module plants both;
* **a redelivered webhook records one row** (architect C4). The provider's own
  event id is the key, and the unique constraint is what makes "once" true
  under a retry rather than under a promise.

**And the fifth claim is about a mapping that is NOT an engagement.** An SMS
`STOP` maps to `complained`, and after ADR comms-9's complaint/bounce split
that mapping **suppresses the recipient and leaves the message row's status
exactly where it was** — the queue.md F1-comms note, restated here as a test
rather than inherited from the ADR's older sentence. `test_a_stop_*` below is
that pin, and it also asserts the shape of what a STOP is NOT: it writes no
engagement row, because `opened` and `clicked` are the whole of that
vocabulary and a complaint is neither.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.comms import providers, services
from apps.comms.models import (
    Channel,
    ChannelPreference,
    Message,
    MessageEngagement,
    MessageTemplate,
    Recipient,
)
from apps.comms.providers import STATUS_PROVIDER
from apps.comms.tests.conftest import Branches, make_template
from apps.comms.tests.test_esp_webhook import (
    RESEND_BACKEND,
    post_resend,
    resend_event,
    whsec,
)
from apps.connections.models import Connection, InboundWebhook
from apps.connections.services import create_connection
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Forbidden, Invalid, NotFound
from apps.core.lifecycle import AppendOnlyViolation, LifecycleKind
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.events.models import Event

pytestmark = pytest.mark.django_db

JSON = "application/json"


# --- helpers --------------------------------------------------------------------
#
# The ESP door machinery — Resend's body shape, Svix's own signing, the post
# through the real receiver — is `test_esp_webhook.py`'s and is IMPORTED rather
# than re-written here. A second copy of a vendor's signature scheme is a second
# thing that can drift from the door it is meant to be proving. The two fixtures
# below are this module's own because a fixture imported into another module
# shadows the parameter that names it.


@pytest.fixture
def signing_secret() -> str:
    """A Svix signing secret, generated per run rather than pinned."""
    return whsec()


@pytest.fixture
def esp(tenant: Tenant, owner_actor: Actor, signing_secret: str) -> Connection:
    """The tenant's Resend connection, holding the signing secret on its row."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Resend",
        credentials={"webhook_secret": signing_secret, "access_token": "an-esp-key"},
    )


def a_sent_message(
    *,
    tenant: Tenant,
    actor: Actor,
    recipient: Recipient,
    handle: str,
    channel: str = Channel.EMAIL,
) -> Message:
    """One message a transport has accepted, recorded under `handle`.

    Through the services, never the manager: a message row written by hand can
    be a message the product could not have produced, and every assertion after
    it would be about a state that cannot happen.
    """
    queued = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=channel,
        tenant=tenant,
        actor=actor,
    )
    return services.record_message_sent(
        tenant=tenant,
        actor=actor,
        message=queued,
        provider="anymail:resend",
        provider_message_id=handle,
    )


def webhook_actor(tenant: Tenant) -> Actor:
    """The hat a signed provider webhook acts under: the system, at the root.

    The same one `providers.handle_status_webhook` builds. A provider status is
    a fact about the tenant and not about the branch that pressed send — the ESP
    has no idea a branch exists.
    """
    return system_actor(tenant, root_organization(tenant=tenant))


def engagements(tenant: Tenant, message: Message) -> list[MessageEngagement]:
    return list(
        MessageEngagement.objects.for_tenant(tenant).filter(message=message).order_by("created_at")
    )


def reread(tenant: Tenant, message: Message) -> Message:
    return Message.objects.for_tenant(tenant).get(pk=message.pk)


def events_named(tenant: Tenant, name: str) -> list[Event]:
    return list(Event.objects.for_tenant(tenant).filter(name=name))


def preference_for(tenant: Tenant, recipient: Recipient, channel: str) -> ChannelPreference | None:
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=channel)
        .first()
    )


# --- the declaration, and the belt behind it ------------------------------------


def test_the_model_is_born_declared_append_only() -> None:
    """House rules 20 and 31, in one assertion each. **No yaml edit anywhere.**

    Rule 20's population is the discovered set of models declaring
    `append_only = True`, and rule 31's is every concrete model's `lifecycle`.
    Both are read off the class, so this table joined both populations the
    moment it existed — which is the property `quality/rules.yaml` staying
    untouched here is the evidence for.

    *Absent:* the class carries neither declaration and the gate says nothing,
    because a model that never declared is not in either population.
    """
    assert MessageEngagement.append_only is True
    assert MessageEngagement.lifecycle.kind is LifecycleKind.APPEND_ONLY
    assert MessageEngagement.derive_org_from == "message"


def test_updating_an_engagement_raises(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The runtime belt, planted on a stored row.

    `BaseModel.save` refuses when `_state.adding` is False for a member of the
    declared population, so the one legitimate write — the create — is untouched
    and every rewrite after it raises where it stands.

    *Absent:* `engagement.save()` succeeds and witnessed history is editable.
    """
    message = a_sent_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-belt-1"
    )
    engagement = services.record_engagement(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="esp-belt-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-belt-1",
    )
    stored = MessageEngagement.objects.for_tenant(tenant).get(pk=engagement.pk)
    stored.url = "https://example.com/rewritten"
    with pytest.raises(AppendOnlyViolation):
        stored.save()
    with pytest.raises(AppendOnlyViolation):
        stored.delete()
    assert engagements(tenant, message)[0].url == "", "nothing was rewritten"


# --- recording ------------------------------------------------------------------


def test_recording_an_open_writes_a_row_and_announces_it(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The service, its row, and `comms.message.opened`.

    The row lands in the MESSAGE's branch — `derive_org_from = "message"` — and
    not in the acting hat's, which for a webhook is the tenant root. That is C9
    and it is the whole reason the declaration exists: an engagement filed at the
    root would be invisible to the branch whose message it is about.

    *Absent:* no row, no event, or a row in the root's organization.
    """
    message = a_sent_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-open-1"
    )
    engagement = services.record_engagement(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="esp-open-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-open-1",
        occurred_at=datetime(2026, 8, 24, 9, 30, tzinfo=UTC),
    )
    assert engagement.message_id == message.pk
    assert engagement.kind == MessageEngagement.Kind.OPENED
    assert engagement.url == ""
    assert engagement.occurred_at == datetime(2026, 8, 24, 9, 30, tzinfo=UTC)
    assert engagement.organization_id == message.organization_id

    announced = events_named(tenant, "comms.message.opened")
    assert len(announced) == 1
    payload = announced[0].payload
    assert payload["id"] == str(engagement.pk)
    assert payload["message_id"] == str(message.pk)
    assert payload["organization_id"] == str(message.organization_id), (
        "house rule 38: the socket fan-out narrows on this key and nothing else"
    )


def test_recording_a_click_keeps_the_url(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """A click is an open with a destination, and the destination is the point.

    *Absent:* the link is dropped and "which link" is unanswerable.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-click-1")
    engagement = services.record_engagement(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="esp-click-1",
        kind=MessageEngagement.Kind.CLICKED,
        url="https://example.com/invoices/1042",
        provider_event_id="evt-click-1",
    )
    assert engagement.url == "https://example.com/invoices/1042"
    assert len(events_named(tenant, "comms.message.clicked")) == 1


def test_an_engagement_never_moves_the_message_row(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """**The claim the whole split exists for.** Two populations, one untouched.

    The message was reported `delivered` by the transport. An open arrives after
    it, and the row still reads `delivered` with the same timestamps: nothing
    about an engagement is a statement about whether the message arrived.

    *Absent:* a status column that moves on an inference, and a `Message` log
    that reports Apple's image proxy as a customer action.
    """
    message = a_sent_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-still-1"
    )
    acting = webhook_actor(tenant)
    delivered = services.record_delivery_status(
        tenant=tenant,
        actor=acting,
        provider_message_id="esp-still-1",
        status=Message.Status.DELIVERED,
    )
    before = (delivered.status, delivered.delivered_at, delivered.bounced_at)

    services.record_engagement(
        tenant=tenant,
        actor=acting,
        provider_message_id="esp-still-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-still-1",
    )
    after = reread(tenant, message)
    assert (after.status, after.delivered_at, after.bounced_at) == before
    assert after.status == Message.Status.DELIVERED


def test_an_engagement_is_witnessing_and_not_consent(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """A suppressed person's open is still recorded, and suppresses nothing more.

    ADR comms-9: "a fact about the past is not permission for the future" — and
    the mirror of it, which is what this asserts: a fact about the past is not a
    *punishment* either. The suppression that was already there is unchanged, and
    the engagement did not add one.

    *Absent:* an engagement path that touches the consent wall in either
    direction.
    """
    message = a_sent_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-supp-1"
    )
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )
    before = preference_for(tenant, recipient, Channel.EMAIL)
    assert before is not None and before.suppressed_at is not None

    services.record_engagement(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="esp-supp-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-supp-1",
    )
    after = preference_for(tenant, recipient, Channel.EMAIL)
    assert after is not None
    assert after.suppressed_at == before.suppressed_at, "the wall did not move"
    assert len(engagements(tenant, message)) == 1, "and the fact was still recorded"


def test_a_redelivered_engagement_records_one_row(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """Architect C4, at the service rather than at the door.

    The unique constraint is `(message, provider_event_id, kind)` and the service
    hands the first row back rather than raising, so a caller that retried cannot
    tell the difference — which is what makes a retry safe rather than merely
    survivable.

    *Absent:* two rows for one open, and every engagement count doubles under a
    provider that retries.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-twice-1")
    acting = webhook_actor(tenant)
    first = services.record_engagement(
        tenant=tenant,
        actor=acting,
        provider_message_id="esp-twice-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-twice-1",
    )
    second = services.record_engagement(
        tenant=tenant,
        actor=acting,
        provider_message_id="esp-twice-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-twice-1",
    )
    assert second.pk == first.pk
    assert MessageEngagement.objects.for_tenant(tenant).count() == 1
    assert len(events_named(tenant, "comms.message.opened")) == 1, "announced once, too"


def test_a_click_and_an_open_from_one_provider_event_are_two_rows(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """`kind` is in the key, so the two facts do not collapse into one.

    *Absent:* a provider that reuses one event id across an open and a click
    silently loses the second.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-both-1")
    acting = webhook_actor(tenant)
    services.record_engagement(
        tenant=tenant,
        actor=acting,
        provider_message_id="esp-both-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-both-1",
    )
    services.record_engagement(
        tenant=tenant,
        actor=acting,
        provider_message_id="esp-both-1",
        kind=MessageEngagement.Kind.CLICKED,
        url="https://example.com/x",
        provider_event_id="evt-both-1",
    )
    assert MessageEngagement.objects.for_tenant(tenant).count() == 2


# --- the walls ------------------------------------------------------------------


def test_a_person_may_not_assert_an_engagement(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """Observed, never asserted — the same door `can_record_status` nails shut.

    An owner is the most privileged membership there is and is refused, because
    the predicate returns `False` for every actor with a membership at all. The
    system actor a verified webhook builds is let through by `authz.allows`
    before this app's policies are consulted.

    *Absent:* a client that can mint "they opened it" facts about somebody.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-authz-1")
    with pytest.raises(Forbidden):
        services.record_engagement(
            tenant=tenant,
            actor=owner_actor,
            provider_message_id="esp-authz-1",
            kind=MessageEngagement.Kind.OPENED,
            provider_event_id="evt-authz-1",
        )
    assert MessageEngagement.objects.for_tenant(tenant).count() == 0


def test_an_engagement_for_another_tenants_handle_finds_nothing(
    tenant: Tenant,
    other_tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """The cross-tenant wall, inherited whole from `get_message_by_provider_id`.

    A provider id is a string somebody else's server chose, so the read is
    scoped to the tenant whose connection the report arrived at and to nothing
    the payload claims.

    *Absent:* one tenant's webhook writing an engagement onto another's message.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-wall-1")
    with pytest.raises(NotFound):
        services.record_engagement(
            tenant=other_tenant,
            actor=system_actor(other_tenant, root_organization(tenant=other_tenant)),
            provider_message_id="esp-wall-1",
            kind=MessageEngagement.Kind.OPENED,
            provider_event_id="evt-wall-1",
        )
    assert MessageEngagement.objects.count() == 0


def test_an_unknown_kind_is_refused_before_a_row_exists(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The vocabulary is closed, the way `STATUS_VALUES` is.

    *Absent:* a provider inventing a third word and a column the rest of the
    product cannot read.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-kind-1")
    with pytest.raises(Invalid, match="engagement"):
        services.record_engagement(
            tenant=tenant,
            actor=webhook_actor(tenant),
            provider_message_id="esp-kind-1",
            kind="hovered",
            provider_event_id="evt-kind-1",
        )
    assert MessageEngagement.objects.for_tenant(tenant).count() == 0


def test_engagements_are_read_through_both_halves(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """`for_tenant(t).visible_to(org)` on the new table, both halves fail-closed.

    House rule 24's shape, asserted on the model added here rather than
    assumed from the base class: an unresolved tenant and an unresolved hat each
    read an empty table rather than the table.

    *Absent:* a scoped model whose manager chain was never exercised, and the
    first door that lists it discovers the answer.
    """
    a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle="esp-read-1")
    services.record_engagement(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="esp-read-1",
        kind=MessageEngagement.Kind.OPENED,
        provider_event_id="evt-read-1",
    )
    root = root_organization(tenant=tenant)
    assert MessageEngagement.objects.for_tenant(tenant).visible_to(root).count() == 1
    assert MessageEngagement.objects.for_tenant(None).visible_to(root).count() == 0
    assert MessageEngagement.objects.for_tenant(tenant).visible_to(None).count() == 0


# --- the STOP mapping's row-effect (queue.md's F1-comms note, as criteria) -------


# The SMS transport here is the SHIPPED `FakeSmsChannel`, registered at import
# in `providers.py`, and this module deliberately registers nothing of its own.
# A fixture that swapped the `sms` slot and unregistered it afterwards is how
# this module briefly took the fake transport away from `test_policies.py` — the
# registry is process-global and the teardown restored an empty slot rather than
# the previous occupant. Using what ships is both the smaller test and the one
# that cannot leak: the STOP row-effect is `record_delivery_status`'s contract
# and is the same whichever adapter set `is_complaint`, so nothing here needs a
# transport of its own.


def an_sms_recipient(*, tenant: Tenant, actor: Actor) -> Recipient:
    """A contact with a phone, because the fake transport fails closed without one."""
    return services.create_recipient(
        tenant=tenant,
        actor=actor,
        email="texted@example.com",
        display_name="A Reader",
        phone="+15550001111",
    )


def an_sms_template(*, tenant: Tenant, actor: Actor) -> None:
    """The template both opt-out tests send under."""
    services.create_template(
        tenant=tenant,
        actor=actor,
        name="sms-receipt",
        subject="",
        body="Your receipt, {{ name }}.",
        channel=Channel.SMS,
        category="transactional",
        context_schema={"required": ["name"], "properties": {"name": {"type": "string"}}},
    )


def test_a_stop_suppresses_the_recipient_and_leaves_the_message_row_alone(
    tenant: Tenant,
    owner_actor: Actor,
) -> None:
    """**The F1-comms note, as a test.** `queue.md`, 2026-08-23.

    An inbound SMS `STOP` maps to `complained` in `record_delivery_status`, and
    after ADR comms-9's complaint/bounce split that mapping does exactly two
    things and no third: it **suppresses the recipient**, and it **announces
    `comms.message.complained`**. It does NOT transition the message row — the
    row was `sent` before the STOP and reads `sent` after it, with no
    `bounced_at`, no `bounce_kind` and no `error`.

    The note existed because the ADR's older sentence said the STOP "fires the
    auto-suppression" without saying what happened to the row, and the earlier
    behaviour — which the split removed — was a `Conflict` on a delivered row
    with nobody suppressed at all.

    *Absent:* `status` reads `bounced` after a STOP, which is a log saying a
    message failed that the transport in fact carried.
    """
    an_sms_template(tenant=tenant, actor=owner_actor)
    recipient = an_sms_recipient(tenant=tenant, actor=owner_actor)
    queued = services.send(
        recipient=recipient,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=owner_actor,
    )
    message = services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=queued,
        provider=providers.FAKE_SMS_PROVIDER,
        provider_message_id="sms-stop-1",
    )
    before = (message.status, message.bounced_at, message.bounce_kind, message.error)
    assert before[0] == Message.Status.SENT

    services.record_delivery_status(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="sms-stop-1",
        status=Message.Status.BOUNCED,
        is_complaint=True,
    )

    after = reread(tenant, message)
    assert (after.status, after.bounced_at, after.bounce_kind, after.error) == before, (
        "a STOP is consent news; the message row is delivery news and is untouched"
    )
    preference = preference_for(tenant, recipient, Channel.SMS)
    assert preference is not None and preference.suppressed_at is not None, (
        "and the person who said STOP is suppressed on the channel they said it on"
    )
    assert len(events_named(tenant, "comms.message.complained")) == 1
    assert MessageEngagement.objects.for_tenant(tenant).count() == 0, (
        "a complaint is not an engagement: `opened` and `clicked` are the whole "
        "of that vocabulary, and the fact is carried by the suppression, the "
        "audit row and `comms.message.complained`"
    )


def test_the_next_send_after_a_stop_is_refused(
    tenant: Tenant,
    owner_actor: Actor,
) -> None:
    """The comms-8 chain, re-proven over SMS. The suppression has teeth.

    *Absent:* a STOP that records a preference row nothing reads, which is the
    finding made about hard bounces one channel over.
    """
    an_sms_template(tenant=tenant, actor=owner_actor)
    recipient = an_sms_recipient(tenant=tenant, actor=owner_actor)
    queued = services.send(
        recipient=recipient,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=owner_actor,
    )
    services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=queued,
        provider=providers.FAKE_SMS_PROVIDER,
        provider_message_id="sms-stop-2",
    )
    services.record_delivery_status(
        tenant=tenant,
        actor=webhook_actor(tenant),
        provider_message_id="sms-stop-2",
        status=Message.Status.BOUNCED,
        is_complaint=True,
    )
    refused = services.send(
        recipient=recipient,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=owner_actor,
    )
    assert refused.status == Message.Status.SUPPRESSED
    assert refused.suppressed_reason == Message.SuppressedReason.SUPPRESSED


# --- the receiver, over the wire ------------------------------------------------


def resend_open(email_id: str) -> dict[str, Any]:
    """`email.opened` in the shape Resend actually posts one."""
    return resend_event("email.opened", email_id=email_id, to="ada@example.com")


def resend_click(email_id: str, *, link: str) -> dict[str, Any]:
    """`email.clicked`, with Resend's own `click` block."""
    return resend_event(
        "email.clicked",
        email_id=email_id,
        to="ada@example.com",
        click={"link": link, "userAgent": "Mozilla/5.0", "timestamp": "2026-08-22T02:00:00.000Z"},
    )


@pytest.mark.django_db(transaction=True)
def test_a_signed_open_at_the_real_door_records_one_engagement(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    esp: Connection,
    signing_secret: str,
    settings: Any,
) -> None:
    """The wiring, end to end: Resend's own body, this template's own door.

    Nothing here hand-writes an Anymail key — the translation is Anymail's,
    driven through `providers.esp_normalized`, exactly as `test_esp_webhook.py`
    drives the bounce path. What the rung adds is the branch after
    `normalize_status` answers `None`: the same body is offered to
    `normalize_engagement`, and an open is recorded instead of being logged as a
    non-terminal drop.

    *Absent:* a 202 with nothing behind it, which is what every open and click
    got before this fix.
    """
    settings.EMAIL_BACKEND = RESEND_BACKEND
    handle = "resend-open-1"
    message = a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle=handle)
    response = post_resend(
        api, esp, resend_open(handle), secret=signing_secret, msg_id="msg_open_1"
    )
    assert response.status_code == 202

    rows = engagements(tenant, message)
    assert len(rows) == 1
    assert rows[0].kind == MessageEngagement.Kind.OPENED
    assert rows[0].provider_event_id == "msg_open_1", (
        "the provider's own event id, which the receiver read off `svix-id` and "
        "stored as `delivery_id` before this handler ever ran"
    )
    assert reread(tenant, message).status == Message.Status.SENT, "the row did not move"


@pytest.mark.django_db(transaction=True)
def test_a_signed_click_at_the_real_door_keeps_the_link(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    esp: Connection,
    signing_secret: str,
    settings: Any,
) -> None:
    """Resend's `click.link`, through Anymail's `click_url`, onto the row.

    *Absent:* the click is recorded and "which link" is lost at the adapter.
    """
    settings.EMAIL_BACKEND = RESEND_BACKEND
    handle = "resend-click-1"
    message = a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle=handle)
    response = post_resend(
        api,
        esp,
        resend_click(handle, link="https://example.com/invoices/1042"),
        secret=signing_secret,
        msg_id="msg_click_1",
    )
    assert response.status_code == 202

    rows = engagements(tenant, message)
    assert len(rows) == 1
    assert rows[0].kind == MessageEngagement.Kind.CLICKED
    assert rows[0].url == "https://example.com/invoices/1042"


@pytest.mark.django_db(transaction=True)
def test_a_redelivered_open_at_the_door_is_still_one_row(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    esp: Connection,
    signing_secret: str,
    settings: Any,
) -> None:
    """C4 at the door: the same `svix-id` twice, one engagement.

    Two belts and they are both real: the receiver refuses a second delivery
    with the same id before any handler runs, and the unique constraint under
    the service would refuse it if the receiver ever stopped.

    *Absent:* an ESP's ordinary retry doubling every open count in the product.
    """
    settings.EMAIL_BACKEND = RESEND_BACKEND
    handle = "resend-open-2"
    message = a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle=handle)
    body = resend_open(handle)
    first = post_resend(api, esp, body, secret=signing_secret, msg_id="msg_open_2")
    second = post_resend(api, esp, body, secret=signing_secret, msg_id="msg_open_2")
    assert (first.status_code, second.status_code) == (202, 202)
    assert len(engagements(tenant, message)) == 1
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_deferral_is_still_a_drop_and_not_an_engagement(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    esp: Connection,
    signing_secret: str,
    settings: Any,
) -> None:
    """The drop path survives the new branch. **The negative that keeps it honest.**

    `email.delivery_delayed` normalises to `DEFERRED`: read, understood, not
    terminal, and not an engagement either. It must still fall through to
    `comms.status.ignored` rather than being swallowed by the engagement branch
    or recorded as an open.

    *Absent:* an engagement branch that answers for every non-terminal event and
    the three-way drop vocabulary ADR comms-13 built goes dark.
    """
    settings.EMAIL_BACKEND = RESEND_BACKEND
    handle = "resend-defer-1"
    message = a_sent_message(tenant=tenant, actor=owner_actor, recipient=recipient, handle=handle)
    response = post_resend(
        api,
        esp,
        resend_event("email.delivery_delayed", email_id=handle),
        secret=signing_secret,
        msg_id="msg_defer_1",
    )
    assert response.status_code == 202
    assert engagements(tenant, message) == []
    assert reread(tenant, message).status == Message.Status.SENT


@pytest.mark.django_db(transaction=True)
def test_an_open_naming_an_unknown_message_records_nothing(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    settings: Any,
) -> None:
    """A body naming a handle no row here holds. The 202 stands; nothing is written.

    The receiver's contract is that a handler's refusal never becomes a 500 on
    the shared inbound door — the body is stored and a human can replay it.

    *Absent:* an unknown handle raising through the receiver and taking every
    other provider's deliveries down with it.
    """
    settings.EMAIL_BACKEND = RESEND_BACKEND
    response = post_resend(
        api,
        esp,
        resend_open("a-handle-nobody-here-recorded"),
        secret=signing_secret,
        msg_id="msg_open_3",
    )
    assert response.status_code == 202
    assert MessageEngagement.objects.for_tenant(tenant).count() == 0
    assert json.loads(InboundWebhook.objects.for_tenant(tenant).get().body)["type"] == (
        "email.opened"
    ), "stored, and replayable"


# --- the read door ----------------------------------------------------------
#
# "engagement has NO door — declared for later, but
# nothing a builder reads says so." A table that only the webhook writes and only
# a shell reads is a table a product cannot use, and every claim above it is
# unobservable from outside the process. This section is that door.
#
# The write half stays door-less and this section proves it stays door-less,
# which is the pair that matters: a read door on a witnessed population is only
# safe while there is no write door beside it.

ENGAGEMENT_URL = "/api/v1/messages/{}/engagement/"

# Measured, not guessed, at ten rows: the session row + the user row (session
# authentication) + 1 SAVEPOINT (ATOMIC_REQUESTS) + the membership lookup
# TenantMiddleware makes for the tenant + the membership lookup for the acting
# org + the message the route resolves first + the page + 1 RELEASE SAVEPOINT.
# The message read is the one this route has that the message list does not, and
# it is deliberate: it is what makes a message this hat cannot see a `not_found`
# before any engagement is touched.
# PR4.b (ADR core-27) adds exactly THREE: a read is a permission now, so the
# selector behind this door calls `require(actor, "<kind>.read", ...)` once,
# and the first `require` of a request reads the actor's three permission
# tables — the memberships on the chain, their grants, and the delta rows for
# the role keys those name. Three and not six because PR0's memo rides on the
# actor: a second `require` in the same request costs nothing, which is what a
# route that fetches through a `get_` and then calls a service is standing on.
ENGAGEMENT_LIST_QUERY_BUDGET = 11


def _engagement_body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def a_witnessed_message(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, handle: str, count: int = 2
) -> Message:
    """One sent message with `count` engagements on it, through the services.

    The engagements are recorded as the SYSTEM at the tenant root, which is the
    hat a signed provider webhook really acts under — so the rows land with the
    message's branch through `derive_org_from` rather than with the root, and
    the branch assertions below are about the shape the product produces.
    """
    message = a_sent_message(tenant=tenant, actor=actor, recipient=recipient, handle=handle)
    for index in range(count):
        services.record_engagement(
            tenant=tenant,
            actor=webhook_actor(tenant),
            provider_message_id=handle,
            kind="opened",
            occurred_at=datetime(2026, 9, 1, 9, 30 + index, tzinfo=UTC),
            provider_event_id=f"{handle}-evt-{index}",
        )
    return message


def test_the_engagement_door_exists_and_is_discoverable(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """The stranger-lens item, as a test rather than as a docs note.

    Two halves, because a route that answers is not the same as a route anybody
    can FIND: it answers over the wire, and it is in the published OpenAPI
    document under the family a reader would look in.

    *Absent:* `404` (which is what this answered on the tree before this fix),
    or a working route nobody can discover without reading `api.py`.
    """
    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="witnessed-1"
    )
    api.force_login(owner)

    response = api.get(ENGAGEMENT_URL.format(message.pk))

    assert response.status_code == 200, response.content
    body = _engagement_body(response)
    assert len(body["items"]) == 2
    assert {row["kind"] for row in body["items"]} == {"opened"}

    from config.api import api as ninja_api

    document = ninja_api.get_openapi_schema()
    operation = (document.get("paths") or {})["/api/v1/messages/{message_id}/engagement/"]["get"]
    assert operation["tags"] == ["messaging"]
    assert operation["summary"].strip()
    assert operation["description"].strip()


def test_the_list_is_newest_first_by_the_providers_moment(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """`occurred_at`, not `created_at`, and the two differ on purpose.

    A webhook that arrived an hour late must not sort as an hour-late open: the
    provider's moment is the fact, ours is when we heard. Both rows here are
    written in one loop milliseconds apart, so a default of `-created_at` would
    order them the other way round — which is what makes this able to fail.
    """
    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="witnessed-2"
    )
    api.force_login(owner)

    body = _engagement_body(api.get(ENGAGEMENT_URL.format(message.pk)))

    moments = [row["occurred_at"] for row in body["items"]]
    assert moments == sorted(moments, reverse=True)
    assert moments[0].startswith("2026-09-01T09:31")


def test_an_unaccepted_ordering_is_refused_and_says_what_is_allowed(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """A declared allow-list, not `.order_by()` over whatever a client sent."""
    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="witnessed-3"
    )
    api.force_login(owner)

    response = api.get(ENGAGEMENT_URL.format(message.pk) + "?ordering=message__recipient__email")

    assert response.status_code == 400, response.content
    assert _engagement_body(response)["code"] == "invalid"


def test_a_message_this_hat_cannot_see_is_not_found(
    api: Client,
    tenant: Tenant,
    owner: User,
    stranger_actor: Actor,
    other_tenant: Tenant,
) -> None:
    """The refusal happens on the MESSAGE, before any engagement is read.

    Which is the whole reason `list_engagements` takes a resolved `Message`
    rather than an id: the decision is made once, in the door, where its absence
    would be noticed.

    *Absent:* an empty list for another tenant's message id, which tells the
    caller the id is valid and just has no opens — an oracle.
    """
    theirs = services.create_recipient(
        tenant=other_tenant, actor=stranger_actor, email="theirs@example.com"
    )
    # The other tenant needs its own template: `MessageTemplate` is
    # tenant-scoped, so the `receipt` fixture is ours and never theirs — which
    # is the isolation this test is about, one table up.
    make_template(actor=stranger_actor)
    their_message = a_sent_message(
        tenant=other_tenant, actor=stranger_actor, recipient=theirs, handle="theirs-1"
    )
    api.force_login(owner)

    response = api.get(ENGAGEMENT_URL.format(their_message.pk))

    assert response.status_code == 404, response.content
    assert _engagement_body(response)["code"] == "not_found"


def test_a_sibling_branch_cannot_read_the_engagements(
    branches: Branches, receipt: MessageTemplate
) -> None:
    """The org sibling, which the tenant sibling above cannot see.

    A1's message and A1's engagements; Seller B is in the same tenant and holds
    no membership over A1. Driven at the selector because the branch wall is
    what is being asserted, and the door's own half is the `not_found` above.
    """
    from apps.comms.selectors import list_engagements

    in_branch = actor_for(user=branches.clerk, tenant=branches.tenant, org=branches.sub_a1)
    contact = services.create_recipient(
        tenant=branches.tenant, actor=in_branch, email="in-a1@example.com"
    )
    message = a_witnessed_message(
        tenant=branches.tenant, actor=in_branch, recipient=contact, handle="branch-1", count=1
    )

    assert (
        list_engagements(
            tenant=branches.tenant,
            message=message,
            org=branches.seller_b,
            actor=actor_for(user=branches.owner, tenant=branches.tenant, org=branches.seller_b),
        ).count()
        == 0
    )
    # And the branch itself, and its parent, do see it — otherwise the line
    # above passes on a read that returns nothing to anybody.
    assert (
        list_engagements(
            tenant=branches.tenant,
            message=message,
            org=branches.sub_a1,
            actor=in_branch,
        ).count()
        == 1
    )
    assert (
        list_engagements(
            tenant=branches.tenant,
            message=message,
            org=branches.seller_a,
            actor=actor_for(user=branches.owner, tenant=branches.tenant, org=branches.seller_a),
        ).count()
        == 1
    )


def test_the_list_query_budget(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    django_assert_num_queries: Any,
) -> None:
    """Ten rows, and the count must not move with them (house rule 5)."""
    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="budget-1", count=10
    )
    api.force_login(owner)
    with django_assert_num_queries(ENGAGEMENT_LIST_QUERY_BUDGET):
        api.get(ENGAGEMENT_URL.format(message.pk))


def test_the_count_is_null_unless_it_is_asked_for(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """ADR core-18's envelope, on this list like every other."""
    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="counted-1"
    )
    api.force_login(owner)

    assert _engagement_body(api.get(ENGAGEMENT_URL.format(message.pk)))["count"] is None
    with_count = _engagement_body(
        api.get(ENGAGEMENT_URL.format(message.pk) + "?include_count=true")
    )
    assert with_count["count"] == 2


def test_there_is_no_way_to_write_an_engagement_through_a_door(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """Rule 20's spirit at the door: a witnessed population has no write door.

    Driven rather than asserted about the source, and driven as a client would
    hit it: a `POST` at the collection answers `405`, because a route exists at
    that path and it does not take one. The published document is checked too,
    so this cannot pass on a `405` that came from the path not existing at all.

    *Absent:* a client can mint "opened" facts about a person into the one
    table whose entire value is that it was witnessed, and read them back as
    evidence.
    """
    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="readonly-1"
    )
    api.force_login(owner)

    posted = api.post(
        ENGAGEMENT_URL.format(message.pk),
        data=json.dumps({"kind": "opened"}),
        content_type=JSON,
    )
    assert posted.status_code == 405, posted.content

    from config.api import api as ninja_api

    document = ninja_api.get_openapi_schema()
    node = (document.get("paths") or {})["/api/v1/messages/{message_id}/engagement/"]
    assert sorted(node) == ["get"], node
    # And no OTHER operation anywhere writes one either — the census over the
    # whole published document, so a `POST /engagements/` added in some future
    # rung fails here rather than being noticed.
    writers = [
        (method.upper(), path)
        for path, operations in (document.get("paths") or {}).items()
        if "engagement" in path
        for method in operations
        if method.upper() not in {"GET", "HEAD"}
    ]
    assert writers == [], writers


def test_the_machine_door_answers_the_same_rows(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """House rule 17 for the new capability, called as a tool.

    The byte-equal wire comparison is `test_doors_over_the_wire.py`'s; this is
    the cheaper half that belongs beside the surface it is about — the tool
    exists, it is thin over the same selector, and it refuses a message this
    principal cannot see with the same `NotFound` the route does.
    """
    from apps.comms.tests.test_mcp import context_for, tool

    message = a_witnessed_message(
        tenant=tenant, actor=owner_actor, recipient=recipient, handle="mcp-1"
    )
    page = tool("list_engagements")(context_for(owner, tenant), message_id=message.pk)

    assert [row.id for row in page.items] == [
        row.pk
        for row in MessageEngagement.objects.for_tenant(tenant)
        .filter(message=message)
        .order_by("-occurred_at", "-created_at")
    ]
