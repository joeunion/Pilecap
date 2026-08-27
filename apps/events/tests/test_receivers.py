"""The inbound door: what is stored, and what is refused.

`verify_and_store` is what `apps.connections`' provider receivers (rung A4) and
any product's own inbound route call. The properties are the ones an attacker
and an outage each test in their own way: an unsigned or wrongly-signed body
changes nothing, a verified one becomes an event that a workflow picks up, and
the event is dispatched onward exactly like one this product emitted itself.

**The source is a row** (ADR connections-1, rung W6). The stand-in below is a
plain object rather than a `Connection`, and deliberately: `apps.events` may not
import `apps.connections`, and what the receiver actually requires is the
`SignedSource` *protocol* — two attributes — not any particular model. A test
that could only be written with the sibling app's row would be testing an import
this app is forbidden to make. The cross-tenant construction proof, which does
need real rows, lives where real rows are: `apps/connections/tests/test_api.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

import pytest

from apps.core.exceptions import Forbidden, Invalid
from apps.core.models import Tenant
from apps.core.time import now
from apps.events import activities, receivers
from apps.events.models import Event, Outbox
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db

SECRET = "the-shared-secret"  # pragma: allowlist secret
NAME = "stripe.invoice.paid"


@dataclass
class Source:
    """The smallest thing that is a `SignedSource`: a tenant and a secret."""

    tenant: Tenant
    webhook_secret: str = SECRET


def signed(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_a_verified_webhook_is_stored_and_handed_to_a_workflow(tenant: Tenant) -> None:
    body = json.dumps({"id": "in_123", "amount": 4200}).encode()

    event = receivers.verify_and_store(body, signed(body), source=Source(tenant), name=NAME)

    assert event.name == NAME
    assert event.payload["amount"] == 4200
    assert Outbox.objects.get(event=event).status == Outbox.Status.PENDING
    # Verify → store → hand to a workflow. Nothing is processed inline.
    assert WorkflowRun.objects.for_tenant(tenant).filter(type="DispatchEventWorkflow").exists()


def test_an_inbound_name_is_not_held_to_this_products_registry(tenant: Tenant) -> None:
    """Somebody else's vocabulary. `emit` validates; this deliberately does not."""
    body = b"{}"
    event = receivers.verify_and_store(
        body, signed(body), source=Source(tenant), name="acme.thing.happened"
    )
    assert event.name == "acme.thing.happened"


def test_a_wrong_signature_stores_nothing(tenant: Tenant) -> None:
    body = b'{"id": "in_123"}'

    with pytest.raises(Forbidden):
        receivers.verify_and_store(
            body, signed(body, "not-the-secret"), source=Source(tenant), name=NAME
        )

    assert not Event.objects.for_tenant(tenant).exists()


def test_a_missing_signature_stores_nothing(tenant: Tenant) -> None:
    with pytest.raises(Forbidden):
        receivers.verify_and_store(b"{}", "", source=Source(tenant), name=NAME)
    assert not Event.objects.for_tenant(tenant).exists()


def test_a_body_that_changed_in_flight_stores_nothing(tenant: Tenant) -> None:
    """The signature is over the bytes; one changed byte is a different body."""
    body = b'{"amount": 4200}'
    signature = signed(body)

    with pytest.raises(Forbidden):
        receivers.verify_and_store(b'{"amount": 9999}', signature, source=Source(tenant), name=NAME)


def test_a_bare_hex_signature_is_accepted(tenant: Tenant) -> None:
    """Senders differ; both spellings verify, and nothing else does."""
    body = b"{}"
    bare = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    event = receivers.verify_and_store(body, bare, source=Source(tenant), name=NAME)
    assert event.pk is not None


def test_a_body_that_is_not_json_is_refused_after_verifying(tenant: Tenant) -> None:
    body = b"<xml/>"
    with pytest.raises(Invalid):
        receivers.verify_and_store(body, signed(body), source=Source(tenant), name=NAME)
    assert not Event.objects.for_tenant(tenant).exists()


def test_a_caller_may_hand_over_an_already_decoded_payload(tenant: Tenant) -> None:
    """Form-encoded senders exist; the signature is still over the raw bytes."""
    body = b"type=charge&amount=1"
    event = receivers.verify_and_store(
        body,
        signed(body),
        source=Source(tenant),
        name=NAME,
        payload={"type": "charge", "amount": "1"},
    )
    assert event.payload == {"type": "charge", "amount": "1"}


def test_an_empty_secret_refuses_a_v2_forgery(tenant: Tenant) -> None:
    """The forgery the empty-secret clause exists to refuse (queue N191a, H4).

    A source whose `webhook_secret` is empty — never minted, revoked, cleared —
    is a source with no key at all. Without the clause, `signature_v2_matches`
    computes an HMAC keyed on the empty string, which is a key anyone who knows
    the secret is empty already has: the forger below holds no shared secret and
    still produces a header the verifier accepts. `compare_digest` is honest
    about the bytes and says nothing about whether there was a key.
    """
    body = b'{"id": "in_forged"}'
    timestamp = int(now().timestamp())
    forged = activities.sign_v2(secret="", body=body, timestamp=timestamp)

    assert receivers.signature_v2_matches(secret="", body=body, signature=forged) is False


def test_an_empty_secret_refuses_a_v1_forgery_through_the_inbound_door(tenant: Tenant) -> None:
    """The same forgery, through `verify_and_store`, which verifies with v1.

    A forged event stored under somebody's tenant is dispatched onward to their
    webhook endpoints and their sockets like any other, so the refusal has to
    land before the store and not merely be reported.
    """
    body = b'{"id": "in_forged"}'

    with pytest.raises(Forbidden):
        receivers.verify_and_store(
            body, signed(body, ""), source=Source(tenant, webhook_secret=""), name=NAME
        )

    assert not Event.objects.for_tenant(tenant).exists()


def test_a_real_secret_still_verifies_under_both_schemes(tenant: Tenant) -> None:
    """The clause refuses no legitimate delivery: the sibling that cannot pass vacuously."""
    body = b'{"id": "in_123"}'
    timestamp = int(now().timestamp())

    assert receivers.signature_matches(secret=SECRET, body=body, signature=signed(body)) is True
    assert (
        receivers.signature_v2_matches(
            secret=SECRET,
            body=body,
            signature=activities.sign_v2(secret=SECRET, body=body, timestamp=timestamp),
        )
        is True
    )
    event = receivers.verify_and_store(body, signed(body), source=Source(tenant), name=NAME)
    assert event.pk is not None


def test_any_row_carrying_the_two_attributes_is_a_source(tenant: Tenant) -> None:
    """`SignedSource` is structural, and that is what makes the seam possible.

    No base class, no registration, and above all no import: the row that
    actually satisfies it in this tree is `apps.connections`' `Connection`, and
    `apps.events` may not import a sibling platform app. A product's own
    provider table joins the same way — by having the two attributes.
    """
    assert isinstance(Source(tenant), receivers.SignedSource)
    assert not isinstance(tenant, receivers.SignedSource), "a tenant is not its own source"
