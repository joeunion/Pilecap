"""The push channel: the address is a table, and the wall is still the wall.

ADR comms-9's push half. Four claims:

* **`push` has a transport on a fresh clone, and it is obviously a fake.**
  `FakePushChannel` holds the slot, every row it carries records
  `provider="fake-push"`, and every send logs at warning — the `FakeSmsChannel`
  bargain, so the whole path is exercised with no project, no certificate and no
  network;
* **the address is the contact's `Device` rows**, resolved through the scoped
  selector, fanned out to every live install, and a contact with none is a
  fail-closed refusal rather than a notification that goes nowhere;
* **`DevicePushChannel` is the real shape and it is driven**, against
  `httpx.MockTransport` — the same seam `apps/connections`' own client
  documents and the same one `ConnectionChannel` is tested through. What that
  proves and what it does not is stated in the module docstring of
  `providers.py` and again at the bottom of this file;
* **the consent wall applies unchanged.** A suppressed `push` channel refuses
  before any transport is asked, and a marketing notification with no consent
  is a `suppressed` row — the same machinery, not a second copy of it.

**What is NOT proven here, and is owner-clocked (OG-11):** that a real gateway
accepts the body `DevicePushChannel` builds. There is no Firebase project and no
APNs certificate on this tree. `test_the_body_is_the_shape_fcm_documents` pins
the shape against the vendor's published contract, which is an argument, not a
drive — and the difference is written down rather than blurred.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from apps.comms import providers, services
from apps.comms.models import Channel, Device, Message, Recipient
from apps.comms.providers import (
    FAKE_PUSH_PROVIDER,
    FCM_PROVIDER,
    DevicePushChannel,
    FakePushChannel,
    fake_push_outbox,
    register_channel,
    registered_channels,
)
from apps.comms.tests.conftest import make_recipient
from apps.connections.models import Connection
from apps.connections.services import create_connection
from apps.core.actor import Actor
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

A_TOKEN = "not-a-real-registration-token-0001"
ANOTHER_TOKEN = "not-a-real-registration-token-0002"


# --- fixtures --------------------------------------------------------------------


@pytest.fixture
def push_template(tenant: Tenant, owner_actor: Actor) -> None:
    services.create_template(
        tenant=tenant,
        actor=owner_actor,
        name="nudge",
        subject="Your invoice",
        body="Invoice {{ number }} is due.",
        channel=Channel.PUSH,
        category="transactional",
        context_schema={"required": ["number"], "properties": {"number": {"type": "string"}}},
    )


@pytest.fixture
def notified(tenant: Tenant, owner_actor: Actor) -> Recipient:
    return make_recipient(actor=owner_actor, email="notified@example.com")


@pytest.fixture
def one_device(tenant: Tenant, owner_actor: Actor, notified: Recipient) -> Device:
    return services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=notified,
        platform="ios",
        push_token=A_TOKEN,
        label="Ada's iPhone",
    )


@pytest.fixture
def outbox() -> Any:
    """The fake's outbox, emptied around each test.

    A module-level list is process-global, exactly as `django.core.mail.outbox`
    is, so a test that read it without clearing would be reading whatever ran
    before it in this worker.
    """
    fake_push_outbox.clear()
    yield fake_push_outbox
    fake_push_outbox.clear()


@pytest.fixture
def gateway_slot() -> Any:
    """`DevicePushChannel` in the `push` slot, as a product's `ready()` puts it.

    The teardown **restores the previous occupant** rather than emptying the
    slot — `test_sms_transport.py`'s discipline, and for the reason recorded
    there: the registry is process-global and an unregister-on-teardown breaks
    every later test relying on the shipped fake.
    """
    previous = registered_channels().get(Channel.PUSH.value)
    yield register_channel
    if previous is not None:
        register_channel(previous)


@pytest.fixture
def gateway(tenant: Tenant, owner_actor: Actor) -> Connection:
    """The tenant's push gateway, as a connection row like any other.

    `base_url` sits in the credentials because `fcm` is not a registered
    `apps/connections` provider — `client._base_url_for` falls back to the row's
    own value for exactly this case (a self-hosted instance, a sandbox, a
    gateway this deployment has no adapter class for), and it is a per-project
    URL anyway. The runbook says the same thing where an operator will read it.
    """
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=FCM_PROVIDER,
        name="Firebase",
        credentials={
            "access_token": "not-a-real-gateway-credential",
            "base_url": "https://fcm.example.invalid/v1/projects/a-project",
        },
    )


def _push(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, template: str = "nudge"
) -> Message:
    return services.send(
        recipient=recipient,
        template=template,
        context={"number": "INV-1042"},
        channel=Channel.PUSH,
        tenant=tenant,
        actor=actor,
    )


# --- the slot --------------------------------------------------------------------


def test_a_fresh_clone_has_a_push_transport_and_it_is_the_fake() -> None:
    """The claim, and the reason the next test exists.

    `push` used to be a kind with no transport — `send(channel="push")` refused
    with "No transport is registered". T3 gave it one, and the one it gave is
    deliberately a fake, because a template that shipped a real gateway would be
    a template nobody could run without a project.

    *Absent:* the slot is empty and every push in a product is bad input, or it
    holds something a deployment could mistake for a gateway.
    """
    holder = registered_channels().get(Channel.PUSH.value)
    assert isinstance(holder, FakePushChannel)
    assert holder.slug == Channel.PUSH.value


def test_every_row_the_fake_carries_names_it(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    outbox: Any,
    recorded_workflow_starts: None,
) -> None:
    """The message log tells a deployment which transport it is running.

    That is the whole safety of shipping a working fake: `Message.provider` is
    literally `fake-push`, so `GET /api/v1/messages/?channel=push` answers "is
    this going anywhere" for somebody who cannot shell into the box.
    """
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)
    sent = providers.get_channel(Channel.PUSH.value).send(
        message=message, subject="Your invoice", body="Invoice INV-1042 is due."
    )

    assert sent.provider == FAKE_PUSH_PROVIDER
    assert len(outbox) == 1
    assert outbox[0].device_id == str(one_device.pk)


# --- the address is a table ------------------------------------------------------


def test_one_notification_fans_out_to_every_live_install(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    outbox: Any,
    recorded_workflow_starts: None,
) -> None:
    """The property that makes push different from every other channel here.

    A person has a phone and a laptop. Email, SMS and chat each have one address
    per contact and could be a column; push cannot, and a transport that pushed
    to "the device that registered last" would silently drop the other one.

    *Absent:* one entry in the outbox and a person who never sees the
    notification on the device they were holding.
    """
    services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=notified,
        platform="web",
        push_token=ANOTHER_TOKEN,
    )
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)

    providers.get_channel(Channel.PUSH.value).send(
        message=message, subject="Your invoice", body="Invoice INV-1042 is due."
    )

    assert len(outbox) == 2
    assert {entry.device_id for entry in outbox} == {
        str(device.pk) for device in Device.objects.for_tenant(tenant).filter(recipient=notified)
    }


def test_a_retired_install_is_not_pushed_to(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    outbox: Any,
    recorded_workflow_starts: None,
) -> None:
    """Retiring a device has to mean something at the transport, or it means nothing.

    *Absent:* `retire_device` writes a timestamp nothing reads, which is
    rule 30's defect — a column built for a reader that was never built.
    """
    services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=notified,
        platform="web",
        push_token=ANOTHER_TOKEN,
    )
    services.retire_device(tenant=tenant, actor=owner_actor, device=one_device)
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)

    providers.get_channel(Channel.PUSH.value).send(
        message=message, subject="Your invoice", body="Invoice INV-1042 is due."
    )

    assert len(outbox) == 1
    assert outbox[0].device_id != str(one_device.pk)


def test_a_contact_with_no_device_is_a_refusal_not_a_silent_nothing(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    push_template: None,
    outbox: Any,
    recorded_workflow_starts: None,
) -> None:
    """Fail closed, exactly as `ConnectionChannel` does on a missing phone number.

    *Absent:* the transport returns having done nothing, the delivery activity
    records `sent`, and the message log claims a notification that never
    existed.
    """
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)

    with pytest.raises(Invalid) as raised:
        providers.get_channel(Channel.PUSH.value).send(
            message=message, subject="Your invoice", body="Invoice INV-1042 is due."
        )

    assert "devices" in raised.value.errors
    assert outbox == []


def test_another_tenants_device_is_never_an_address(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    stranger_actor: Actor,
    other_tenant: Tenant,
    push_template: None,
    outbox: Any,
    recorded_workflow_starts: None,
) -> None:
    """The tenant sibling, on the read the transport makes.

    The scoped selector is the whole of it, and it is worth a test of its own
    because this read happens on a worker thread with no request and no
    middleware — the place a bare manager is easiest to reach for.
    """
    theirs = make_recipient(actor=stranger_actor, email="theirs@example.com")
    services.register_device(
        tenant=other_tenant,
        actor=stranger_actor,
        recipient=theirs,
        platform="ios",
        push_token=ANOTHER_TOKEN,
    )
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)

    with pytest.raises(Invalid):
        providers.get_channel(Channel.PUSH.value).send(
            message=message, subject="Your invoice", body="Invoice INV-1042 is due."
        )
    assert outbox == []


# --- the consent wall, unchanged -------------------------------------------------


def test_a_suppressed_push_channel_refuses_before_any_transport_is_asked(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    outbox: Any,
    recorded_workflow_starts: None,
) -> None:
    """House rule 25's promise, said for the new channel rather than assumed.

    The registration says the product CAN reach this handset; suppression says
    it MAY not. A device is not consent, and this is the test that makes that
    sentence enforceable rather than a docstring.

    *Absent:* a suppressed contact is notified, and the push channel is a
    consent bypass built on the same day the consent wall was documented as
    applying to it.
    """
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=notified, channel=Channel.PUSH
    )

    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)

    assert message.status == Message.Status.SUPPRESSED
    assert message.suppressed_reason == "suppressed"
    assert outbox == []


# --- the real shape, driven against a recorded gateway ---------------------------


def test_the_real_adapter_posts_once_per_device_with_a_stable_key(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    gateway: Connection,
    recorded_workflow_starts: None,
) -> None:
    """`DevicePushChannel` through `httpx.MockTransport`. Four claims, one drive.

    One request per device; the idempotency key is `<message>:<device>`, stable
    across every retry of one logical send, so a restarted worker does not
    notify somebody twice; the token that goes on the wire is the DECRYPTED one
    (it round-tripped through the encrypted column); and the handle reported
    back is the gateway's own.
    """
    services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=notified,
        platform="web",
        push_token=ANOTHER_TOKEN,
    )
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "projects/p/messages/0:1600000000"})

    channel = DevicePushChannel(transport=httpx.MockTransport(handler))
    sent = channel.send(message=message, subject="Your invoice", body="Invoice INV-1042 is due.")

    assert len(seen) == 2
    keys = {request.headers.get("idempotency-key") for request in seen}
    devices = Device.objects.for_tenant(tenant).filter(recipient=notified)
    assert keys == {f"{message.pk}:{device.pk}" for device in devices}

    tokens = {json.loads(request.content)["message"]["token"] for request in seen}
    assert tokens == {A_TOKEN, ANOTHER_TOKEN}

    assert sent.provider == FCM_PROVIDER
    assert sent.provider_message_id == "projects/p/messages/0:1600000000"


def test_the_body_is_the_shape_the_gateway_documents(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    gateway: Connection,
    recorded_workflow_starts: None,
) -> None:
    """The vendor contract, pinned as a shape.

    **This is an argument, not a drive**, and it is written down as one: nothing
    on this tree has a Firebase project, so "the body is what FCM's HTTP v1
    reference documents" is checked against the reference and not against
    Google. It is here anyway because the alternative is that the shape is
    checked against nothing at all, and because a future edit that flattened
    `message.notification` would then be invisible until somebody's first live
    push.
    """
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"name": "projects/p/messages/1"})

    DevicePushChannel(transport=httpx.MockTransport(handler)).send(
        message=message, subject="Your invoice", body="Invoice INV-1042 is due."
    )

    assert bodies == [
        {
            "message": {
                "token": A_TOKEN,
                "notification": {
                    "title": "Your invoice",
                    "body": "Invoice INV-1042 is due.",
                },
            }
        }
    ]


def test_a_tenant_with_no_gateway_connection_is_refused(
    tenant: Tenant,
    owner_actor: Actor,
    notified: Recipient,
    one_device: Device,
    push_template: None,
    recorded_workflow_starts: None,
) -> None:
    """No connection, no push. The credential is per TENANT and never a setting.

    *Absent:* the adapter reaches for a deployment-wide credential and one
    tenant's notifications go out over another's project.
    """
    message = _push(tenant=tenant, actor=owner_actor, recipient=notified)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("the adapter dialled a gateway with no connection row")

    with pytest.raises(NotFound):
        DevicePushChannel(transport=httpx.MockTransport(handler)).send(
            message=message, subject="Your invoice", body="Invoice INV-1042 is due."
        )


def test_a_product_replaces_the_fake_under_the_same_slug(
    gateway_slot: Any,
) -> None:
    """The enablement move the runbook documents, driven rather than described.

    `register_channel` keys on the transport's own `slug`, so a product's
    `AppConfig.ready()` REPLACES the fake instead of adding a second transport
    nothing would ever choose.

    *Absent:* the runbook's instruction is wrong and a deployment that followed
    it is still on the fake with no way to tell.
    """
    gateway_slot(DevicePushChannel())

    holder = registered_channels().get(Channel.PUSH.value)
    assert isinstance(holder, DevicePushChannel)
    assert len([slug for slug in registered_channels() if slug == Channel.PUSH.value]) == 1


def test_the_adapter_holds_no_vendor_library() -> None:
    """House rule 44's watch, answered by construction rather than by a census.

    The decomposition expected `firebase-admin`; this app does not add it, and
    the argument is in `DevicePushChannel`'s docstring — the SDK's value is the
    credential lifecycle and the inbound-signature machinery, push has no
    inbound webhook to verify, and the credential here lives per tenant on an
    encrypted `Connection` row rather than in the process-global app the SDK
    wants to own.

    Fails the day somebody adds one, which is the moment that argument has to be
    revisited rather than inherited.

    Read off the module's IMPORT statements by AST rather than by grepping its
    text, and that is not fastidiousness: the argument for not adding the SDK is
    written in this module's own prose, so a text search finds the vendor's name
    in the sentence explaining its absence and fails on the explanation. Prose
    that spells the thing being counted is a phantom registration, and this is
    the shape of it.
    """
    import ast
    import pathlib

    import apps.comms.providers as module

    source = module.__file__
    assert source is not None
    tree = ast.parse(pathlib.Path(source).read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    assert imported, "the walk found no imports at all — this would pass vacuously"
    assert "firebase_admin" not in imported
    assert "google" not in imported
    # The vendor library this module DOES hold, so the assertions above are not
    # passing because the walk is blind: `twilio` is here by ADR comms-9's stack
    # ruling and rule 43's disposition (the SDK validates; we never sign).
    assert "twilio" in imported
