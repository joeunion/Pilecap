"""The key a subscriber is handed verifies a real delivery — over a real socket.

Everything else about the endpoint door can be true and this can still be false:
the create response could hand back a key the delivery does not sign with, or
sign with, and a subscriber would find out by getting nothing it could trust.
So this module does not mock the transport. It stands a real HTTP server up on a
loopback port, registers an endpoint pointing at it **through the REST door as
the persona would**, makes a widget, drives the delivery activity, and asks the
receiver whether the bytes it got verified against the key it was given.

Four properties, and the fourth is the one freshness exists for:

1. the key from `POST /endpoints/` verifies the signature on the delivery;
2. the signature is over the **raw bytes received**, so a receiver that
   re-serialises the body and hashes that gets a different answer — which is why
   the receiver here keeps what it read;
3. after `POST /endpoints/{id}/secret/`, a receiver still holding the old key
   **stops** verifying, and one holding the new key verifies. There is no
   overlap window, and the absence is the contract;
4. every delivery carries **both** `X-Signature` (the body) and
   `X-Signature-V2` (a timestamp and the body), the receiver checks both, and a
   delivery captured and replayed later still passes v1 and is **refused** by
   v2's window. That contrast is asserted rather than described.

`transaction=True` because the delivery activity closes stale connections at
both ends the way it does in the worker, and because `emit`'s dispatch start is
an `on_commit` hook that has to actually fire. `recorded_workflow_starts` is
what keeps that hook from dialling Temporal.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any
from uuid import UUID

import pytest
from django.test import Client
from temporalio.exceptions import ApplicationError

from apps.accounts.models import User
from apps.core.actor import Actor, system_actor
from apps.core.models import Tenant
from apps.core.time import now
from apps.events import activities, receivers, services
from apps.events.models import Delivery, Event, WebhookEndpoint
from apps.events.types import DeliverWebhook
from apps.example.events import WIDGET_CREATED

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def loopback_receiver(settings: Any) -> None:
    """The receiver is a real loopback socket over http: the valve local.py sets."""
    settings.WEBHOOK_PRIVATE_TARGETS_ALLOWED = True


ENDPOINTS_URL = "/api/v1/webhook-endpoints/"
WIDGETS_URL = "/api/v1/widgets/"
JSON = "application/json"

# What the receiver's `/hook` answers when the signature checks out, and what it
# answers when it does not. A subscriber that cannot verify a body has been sent
# something it must not act on, and 401 is what it should say about that.
VERIFIED = 200
REJECTED = 401


class Receiver:
    """A real subscriber on a loopback port, holding one key and checking it.

    It keeps the **raw bytes** it read and verifies against those, not against a
    re-serialisation, because that is the one way to be wrong that a mocked
    transport would never show: two JSON documents can mean the same thing and
    hash differently.
    """

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.received: list[dict[str, Any]] = []
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                offered = self.headers.get("X-Signature", "")
                expected = (
                    "sha256="
                    + hmac.new(receiver.secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
                )
                verified = hmac.compare_digest(offered, expected)
                # v2 is checked through the house verifier rather than
                # hand-rolled beside it, because the freshness half is the part
                # a subscriber gets wrong, and a receiver that reimplemented the
                # window would be testing this file's arithmetic instead of the
                # contract the docs publish.
                offered_v2 = self.headers.get(activities.SIGNATURE_V2_HEADER, "")
                verified_v2 = receivers.signature_v2_matches(
                    secret=receiver.secret, body=raw, signature=offered_v2
                )
                receiver.received.append(
                    {
                        "verified": verified,
                        "verified_v2": verified_v2,
                        "signature": offered,
                        "signature_v2": offered_v2,
                        "event_name": self.headers.get("X-Event-Name", ""),
                        "event_id": self.headers.get("X-Event-Id", ""),
                        "body": json.loads(raw) if raw else None,
                        "raw": raw,
                    }
                )
                self.send_response(VERIFIED if verified else REJECTED)
                self.end_headers()

            def log_message(self, *_args: Any) -> None:
                """Silence: the suite's output is not this server's diary."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> Receiver:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Always shut down, and never swallow: an `__exit__` returning `None`
        propagates whatever the body raised."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host!s}:{port}/hook"

    def rotate_to(self, secret: str) -> None:
        """The subscriber was told the new key. Everything else stays."""
        self.secret = secret


@pytest.fixture
def acting(tenant: Tenant, monkeypatch: pytest.MonkeyPatch) -> Tenant:
    """Pretend the workflow interceptor restored this tenant.

    In production the tenant arrives on the workflow's Temporal headers. Calling
    the activity directly there is no workflow, so the one function that reads it
    is replaced — which is also the proof that it is read in exactly one place.
    """
    monkeypatch.setattr(activities, "current_actor", lambda **_: system_actor(tenant))
    return tenant


def a_widget_event(*, api: Client, tenant: Tenant, name: str) -> Event:
    """Make a widget **through its own door** and hand back the event it emitted.

    Over HTTP rather than by importing `apps.example.services`, and that is not
    a stylistic choice: the layer contract forbids `apps.events` importing a
    domain app, and rightly — the spine must not know what a widget is. Driving
    the public route keeps the whole arc on the wire, which is also what a
    subscriber's world actually looks like: somebody did something in the
    product, and a webhook arrived.
    """
    created = api.post(WIDGETS_URL, data=json.dumps({"name": name}), content_type=JSON)
    assert created.status_code == 201, created.content
    event = (
        Event.objects.for_tenant(tenant).filter(name=WIDGET_CREATED).order_by("-created_at").first()
    )
    assert event is not None, "creating a widget did not emit an event"
    return event


def verified(receiver: Receiver) -> bool:
    """Whether the most recent body this receiver read checked out.

    A function rather than `receiver.received[-1]["verified"]` written out at
    each call site, and that is not only tidiness: mypy narrows a subscript
    expression, so once one line asserts `... is False` every later reading of
    the *same* expression is narrowed to `Literal[False]` and the rest of the
    test is silently unreachable — a green run over statements nothing checks.
    A call is opaque to that narrowing, which is exactly what is wanted here.
    """
    return bool(receiver.received[-1]["verified"])


def deliver(*, event: Event, endpoint: WebhookEndpoint) -> None:
    activities.deliver_webhook(DeliverWebhook(event_id=str(event.pk), endpoint_id=str(endpoint.pk)))


def test_the_secret_the_door_handed_back_verifies_a_real_delivery(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """End to end, over a socket: register, emit, deliver, verify.

    This is the property the whole "shown once" design is in service of. If the
    key the create response returns did not sign the delivery, every other test
    in this app could still be green and no subscriber could trust a byte.
    """
    with Receiver(secret="not-the-key-yet") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        api.force_login(owner)
        created = api.post(
            ENDPOINTS_URL,
            data=json.dumps({"url": receiver.url, "event_names": [WIDGET_CREATED]}),
            content_type=JSON,
        ).json()
        # The subscriber stores the key it was handed. This is the only moment
        # it will ever see it.
        receiver.rotate_to(created["secret"])
        endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])

        event = a_widget_event(api=api, tenant=acting, name="a widget")
        deliver(event=event, endpoint=endpoint)

    assert len(receiver.received) == 1
    landed = receiver.received[0]
    assert landed["verified"], "the key the door returned did not verify the delivery"
    assert landed["signature"].startswith("sha256=")
    assert landed["event_name"] == WIDGET_CREATED
    assert landed["event_id"] == str(event.pk)
    assert landed["body"]["name"] == WIDGET_CREATED
    assert landed["body"]["payload"]["name"] == "a widget"

    delivery = Delivery.objects.get(event=event, endpoint=endpoint)
    assert delivery.status == Delivery.Status.DELIVERED
    assert delivery.last_code == VERIFIED
    assert delivery.attempts == 1


def test_the_signature_is_over_the_bytes_that_arrived(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """A receiver that re-serialises before hashing gets a different answer.

    Not a detail: it is the single most common way a first integration fails,
    and the reason the delivery serialises once and both signs and sends that.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        api.force_login(owner)
        created = api.post(
            ENDPOINTS_URL, data=json.dumps({"url": receiver.url}), content_type=JSON
        ).json()
        receiver.rotate_to(created["secret"])
        endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])
        event = a_widget_event(api=api, tenant=acting, name="bytes matter")
        deliver(event=event, endpoint=endpoint)

    landed = receiver.received[0]
    reserialised = json.dumps(landed["body"]).encode("utf-8")
    assert reserialised != landed["raw"], "the shapes happen to match; pick a harder payload"
    over_the_reserialisation = (
        "sha256="
        + hmac.new(created["secret"].encode("utf-8"), reserialised, hashlib.sha256).hexdigest()
    )
    assert over_the_reserialisation != landed["signature"]
    assert landed["verified"], "and the raw bytes still verified"


def test_after_a_rotation_the_old_key_stops_verifying_and_the_new_one_starts(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """No overlap window, and the absence is the contract.

    The endpoint holds one key and deliveries are signed with whatever it holds,
    so the very next delivery after a rotation is signed with the new one. A
    subscriber that has not been told is rejecting bodies from that moment —
    which is exactly what is wanted when the reason to rotate is that the old key
    is somewhere it should not be.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        api.force_login(owner)
        created = api.post(
            ENDPOINTS_URL, data=json.dumps({"url": receiver.url}), content_type=JSON
        ).json()
        endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])
        old_key = created["secret"]
        receiver.rotate_to(old_key)

        first = a_widget_event(api=api, tenant=acting, name="before")
        deliver(event=first, endpoint=endpoint)
        assert verified(receiver)

        rotated = api.post(f"{ENDPOINTS_URL}{endpoint.pk}/secret/").json()
        new_key = rotated["secret"]
        assert new_key != old_key

        # The subscriber has NOT been told yet, and finds out the hard way.
        endpoint.refresh_from_db()
        second = a_widget_event(api=api, tenant=acting, name="after")
        # A receiver that cannot verify answers 401, and a 4xx is not worth
        # retrying — so this fails terminally on the first attempt rather than
        # six times over an hour, which is the right shape for "your key is
        # wrong" and is what puts it in the dead-letter list quickly.
        with pytest.raises(ApplicationError):
            deliver(event=second, endpoint=endpoint)
        assert verified(receiver) is False

        # Now it is told, and the next one lands.
        receiver.rotate_to(new_key)
        third = a_widget_event(api=api, tenant=acting, name="told")
        deliver(event=third, endpoint=endpoint)
        assert verified(receiver)

    assert Delivery.objects.get(event=second, endpoint=endpoint).status == Delivery.Status.FAILED
    assert Delivery.objects.get(event=third, endpoint=endpoint).status == Delivery.Status.DELIVERED


def test_a_paused_endpoint_is_not_among_the_targets_at_all(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """A pause is not a filter applied at delivery time — it is an absent target.

    Which is why nothing arrives *and* why there is no delivery row saying it was
    skipped: the fan-out loads the active endpoints, and a paused one is not
    loaded. `GET /deliveries/` therefore stops where the pause began, and that
    stopping point is the answer to "since when has this been quiet".
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        api.force_login(owner)
        created = api.post(
            ENDPOINTS_URL, data=json.dumps({"url": receiver.url}), content_type=JSON
        ).json()
        endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])
        receiver.rotate_to(created["secret"])

        before = a_widget_event(api=api, tenant=acting, name="while live")
        deliver(event=before, endpoint=endpoint)

        api.post(f"{ENDPOINTS_URL}{endpoint.pk}/pause/")
        during = a_widget_event(api=api, tenant=acting, name="while paused")

        loaded = activities.load_delivery_targets(_dispatch_of(during))
        assert loaded.targets == []

    assert receiver.received and all(one["verified"] for one in receiver.received)
    assert Delivery.objects.filter(event=during).count() == 0
    listed = api.get("/api/v1/deliveries/").json()
    assert [row["event_id"] for row in listed["items"]] == [str(before.pk)]


def _dispatch_of(event: Event) -> Any:
    """The activity's own argument shape, built the way the workflow builds it."""
    from apps.events.types import DispatchEvent

    return DispatchEvent(event_id=str(event.pk))


def test_a_dead_letter_replayed_over_the_door_is_delivered(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """The whole arc: it failed, it gave up, a human replayed it, it landed.

    The replay itself goes through the door (`POST /dead-letters/{id}/replay/`),
    which re-enqueues the event; what the dispatch run would then do is driven
    here by calling the delivery activity, because the run is the workflow's own
    tested property and the claim under test here is that the door reaches it.

    The lineage is what is asserted at the end: one row, `attempts` at 3 across
    two dispatches, `dead_lettered_at` still where it was, and the status now
    `delivered`. A replay that had written a second row would have lost the fact
    that this pair ever failed.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        api.force_login(owner)
        created = api.post(
            ENDPOINTS_URL, data=json.dumps({"url": receiver.url}), content_type=JSON
        ).json()
        endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])
        event = a_widget_event(api=api, tenant=acting, name="will fail first")

        # It fails twice against a receiver holding the wrong key, and is parked.
        for _ in range(2):
            with pytest.raises(ApplicationError):
                deliver(event=event, endpoint=endpoint)
        services.dead_letter_delivery(
            tenant=acting,
            endpoint_id=endpoint.pk,
            event_id=event.pk,
            error="spent every retry",
        )

        dead = api.get("/api/v1/dead-letters/").json()["items"]
        assert [row["id"] for row in dead] == [
            str(Delivery.objects.get(event=event, endpoint=endpoint).pk)
        ]
        assert dead[0]["attempts"] == 2

        # The subscriber is fixed, and a human asks for it again.
        receiver.rotate_to(created["secret"])
        replayed = api.post(f"/api/v1/dead-letters/{dead[0]['id']}/replay/")
        assert replayed.status_code == 200, replayed.content

        deliver(event=event, endpoint=endpoint)

    delivery = Delivery.objects.get(event=event, endpoint=endpoint)
    assert delivery.status == Delivery.Status.DELIVERED
    assert delivery.attempts == 3, "one row, three attempts — the lineage, not a new row"
    assert delivery.dead_lettered_at is not None, "and the record that it once gave up"
    assert Delivery.objects.filter(event=event).count() == 1


def test_the_event_the_receiver_got_is_the_one_the_door_reports(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """`X-Event-Id` joins the webhook to the delivery row, which is the whole ask.

    A subscriber that received something twice — after a replay, say — needs one
    id to be idempotent on, and needs that id to be the one this product's own
    door reports. Asserted rather than assumed.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        api.force_login(owner)
        created = api.post(
            ENDPOINTS_URL, data=json.dumps({"url": receiver.url}), content_type=JSON
        ).json()
        receiver.rotate_to(created["secret"])
        endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])
        event = a_widget_event(api=api, tenant=acting, name="joinable")
        deliver(event=event, endpoint=endpoint)

    header_id = UUID(receiver.received[0]["event_id"])
    reported = api.get("/api/v1/deliveries/").json()["items"][0]
    assert UUID(reported["event_id"]) == header_id == event.pk
    assert reported["event_name"] == WIDGET_CREATED


# --- Freshness: the fourth property -----------------------------------------
#
# Everything above proves *who* signed. Nothing above proves *when*, and until
# `X-Signature-V2` there was nothing in a delivery that could: a captured body
# and its `X-Signature` verify for as long as the key lives, so anyone who ever
# saw one delivery could send it again a year later and a correct subscriber
# would accept it. The first test below is that finding, standing; the two after
# it are the window that refuses it.


def a_delivery_to_capture(
    *, api: Client, tenant: Tenant, owner: User, receiver: Receiver, name: str
) -> dict[str, Any]:
    """One real delivery, made here so that the replay has its own victim.

    Registered through the door and driven over the socket exactly as the tests
    above do, because a replay proved against a hand-built body would be proving
    something about the test rather than about a delivery.
    """
    api.force_login(owner)
    created = api.post(
        ENDPOINTS_URL, data=json.dumps({"url": receiver.url}), content_type=JSON
    ).json()
    receiver.rotate_to(created["secret"])
    endpoint = WebhookEndpoint.objects.get(pk=created["endpoint"]["id"])
    event = a_widget_event(api=api, tenant=tenant, name=name)
    deliver(event=event, endpoint=endpoint)
    return {"secret": created["secret"], **receiver.received[-1]}


def test_a_year_on_the_old_scheme_still_verifies_and_the_window_refuses(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finding and its close, on one captured delivery.

    `X-Signature` covers the body and nothing else, so bytes captured today
    verify a year from now against the same key — nothing is broken, an HMAC is
    doing exactly what an HMAC does, but a reader who assumed it stopped a
    replay was wrong. `X-Signature-V2` covers a timestamp as well, and a
    verifier that checks it refuses the same capture.

    Both halves are asserted here rather than in two modules because it is the
    *contrast* that is the point, and because the v1 half must keep passing:
    during the expansion window subscribers still on v1 are exactly this
    exposed, and the day that stops being true is the day v1 is dropped.

    The clock is moved by replacing the one function the verifier reads it
    through — the same seam, and the same proof-by-substitution, as `acting`
    above.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        captured = a_delivery_to_capture(
            api=api, tenant=acting, owner=owner, receiver=receiver, name="replay me"
        )
    assert captured["verified"], "the delivery verified when it was made"

    a_year_on = now() + timedelta(days=365)
    monkeypatch.setattr(receivers, "now", lambda: a_year_on)

    assert receivers.signature_matches(
        secret=captured["secret"],
        body=captured["raw"],
        signature=captured["signature"],
    ), "the finding: the old scheme has no notion of when, so the capture still verifies"

    assert (
        receivers.signature_v2_matches(
            secret=captured["secret"],
            body=captured["raw"],
            signature=captured["signature_v2"],
        )
        is False
    ), "and the freshness window refuses the same bytes"


def test_the_window_verifies_fresh_and_refuses_one_second_past_tolerance(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edge, both sides of it, on a delivery that really happened.

    A window nobody has stood at the edge of is a number in a file. One second
    inside is accepted and one second outside is refused, so the tolerance is
    the thing that decides and not the shape of the header.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        captured = a_delivery_to_capture(
            api=api, tenant=acting, owner=owner, receiver=receiver, name="stale soon"
        )
    signed_at = now()

    def verifies() -> bool:
        return receivers.signature_v2_matches(
            secret=captured["secret"],
            body=captured["raw"],
            signature=captured["signature_v2"],
        )

    def verifier_clock_reads(offset: timedelta) -> None:
        """Move the verifier's clock to `offset` away from when this was signed."""
        monkeypatch.setattr(receivers, "now", lambda: signed_at + offset)

    tolerance = receivers.SIGNATURE_V2_TOLERANCE
    a_moment = timedelta(seconds=5)

    assert verifies(), "a delivery verified the moment it arrived"

    verifier_clock_reads(tolerance - a_moment)
    assert verifies(), "inside the window, a slow subscriber is still fine"

    verifier_clock_reads(tolerance + a_moment)
    assert verifies() is False, "past the tolerance is refused"

    verifier_clock_reads(-tolerance - a_moment)
    assert verifies() is False, "and so is a timestamp too far ahead of the verifier's clock"


def test_a_delivery_carries_both_signatures_during_the_expansion_window(
    api: Client,
    acting: Tenant,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """Both headers, both verifying, and v1's bytes exactly what they always were.

    This is what makes the change expand/contract rather than a break: a
    subscriber written against `X-Signature` on the day before this shipped
    keeps working, byte for byte, while one that has moved to `X-Signature-V2`
    gets the freshness the old header cannot carry.
    """
    with Receiver(secret="placeholder") as receiver:  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
        captured = a_delivery_to_capture(
            api=api, tenant=acting, owner=owner, receiver=receiver, name="both headers"
        )

    assert captured["verified"], "v1 verified, as this receiver has always checked it"
    assert captured["verified_v2"], "and v2 verified, window applied"

    # v1 is not merely present, it is *unchanged*: the same computation over the
    # same bytes it signed before v2 existed.
    assert captured["signature"] == activities.sign(secret=captured["secret"], body=captured["raw"])
    # ...and v2 is not v1 with a timestamp pasted on the front: a different
    # digest, because it covers the timestamp too.
    assert captured["signature_v2"].endswith(captured["signature"]) is False
