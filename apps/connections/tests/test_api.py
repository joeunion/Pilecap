"""The three doors in `api.py`, driven through the mounted API.

Through the real client and the real middleware, so `TenantMiddleware` runs and
`request.tenant` is the one a user would get. The webhook tests are the reason
this module exists: an inbound receiver is the one route in the product with no
authentication, and "does the signature check actually refuse" is not a question
to answer by reading.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import inspect
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.connections import providers
from apps.connections.api import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    SIGNATURE_V2_HEADER,
    receive_webhook,
    signature_matches,
    signature_v2_tolerance,
)
from apps.connections.events import CONNECTION_CREDENTIALS_UPDATED
from apps.connections.models import Connection, InboundWebhook
from apps.connections.services import create_connection
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.core.actor import Actor
from apps.core.exceptions import Forbidden
from apps.core.models import Tenant
from apps.core.time import now

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/connections/"
JSON = "application/json"

# The spine is reached by name and never imported: `test_discovery`'s
# `test_nothing_in_this_app_imports_apps_events` reads every file under
# `apps/connections` — this one included — because the layer contract makes the
# two apps siblings and the coupling a runtime lookup.
EVENTS_RECEIVERS = "apps.events.receivers"


def _events_model() -> Any:
    """`events.Event`, resolved through the registry."""
    return django_apps.get_model("events", "Event")


def _receiver() -> Any:
    """`verify_and_store`, likewise by name."""
    return importlib.import_module(EVENTS_RECEIVERS).verify_and_store


# Measured, not guessed, at ten rows: the session row + the user row (session
# authentication) + 1 SAVEPOINT (ATOMIC_REQUESTS) + the membership lookup
# TenantMiddleware makes for the tenant + the one it makes for the acting org
# (the hierarchy's standing per-request cost) + COUNT + the page + 1 RELEASE
# SAVEPOINT.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
LIST_QUERY_BUDGET = 7


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _signature(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return SIGNATURE_PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _webhook_url(connection: Connection) -> str:
    return f"{LIST_URL}{connection.pk}/webhook/"


# --- The list ------------------------------------------------------------------


def test_the_routes_are_where_the_router_put_them() -> None:
    assert reverse("api:connection-list") == LIST_URL
    assert reverse("api:connection-oauth-callback") == f"{LIST_URL}oauth/callback/"


def test_anonymous_cannot_list(api: Client) -> None:
    assert api.get(LIST_URL).status_code == 401


def test_the_list_is_scoped_and_a_second_tenants_rows_are_absent(
    api: Client,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    stranger_actor: Actor,
) -> None:
    mine = create_connection(tenant=tenant, actor=owner_actor, provider="example", name="Mine")
    create_connection(tenant=other_tenant, actor=stranger_actor, provider="example", name="Theirs")

    api.force_login(owner)
    response = api.get(LIST_URL)

    assert response.status_code == 200
    body = _body(response)
    assert [row["id"] for row in body["items"]] == [str(mine.pk)]
    assert len(body["items"]) == 1


def test_the_list_never_carries_a_credential(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The shape is the enforcement: `ConnectionOut` has no field for it."""
    create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Secretive",
        credentials={"access_token": "sk-live-nope", "webhook_secret": WEBHOOK_SECRET},
    )
    api.force_login(owner)
    response = api.get(LIST_URL)

    raw = response.content.decode()
    assert "sk-live-nope" not in raw
    assert WEBHOOK_SECRET not in raw
    assert '"credentials"' not in raw, "the only mention is the boolean below"
    assert _body(response)["items"][0]["has_credentials"] is True


def test_the_list_query_count_is_pinned(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    django_assert_num_queries: Any,
) -> None:
    for index in range(10):
        create_connection(
            tenant=tenant, actor=owner_actor, provider="example", name=f"Connection {index}"
        )
    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        api.get(LIST_URL)


def test_ordering_outside_the_allow_list_is_refused(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    response = api.get(f"{LIST_URL}?ordering=credentials")
    assert response.status_code == 400
    assert _body(response)["code"] == "invalid"


# --- Create, update, revoke -----------------------------------------------------


def test_creating_a_connection_returns_201_without_echoing_the_credential(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    response = api.post(
        LIST_URL,
        data=json.dumps(
            {"provider": "example", "name": "New", "credentials": {"access_token": "sk-live-nope"}}
        ),
        content_type=JSON,
    )

    assert response.status_code == 201
    assert "sk-live-nope" not in response.content.decode()
    assert _body(response)["has_credentials"] is True
    assert Connection.objects.for_tenant(tenant).get(name="New").access_token == "sk-live-nope"


def test_a_plain_member_is_refused_403_by_the_service_not_the_route(
    api: Client, member: User
) -> None:
    api.force_login(member)
    response = api.post(
        LIST_URL, data=json.dumps({"provider": "example", "name": "Nope"}), content_type=JSON
    )
    assert response.status_code == 403
    assert _body(response)["code"] == "forbidden"


def test_another_tenants_connection_is_404_not_403(
    api: Client, other_tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    """A 403 would confirm the row exists, which is the fact the tenancy hides."""
    theirs = create_connection(
        tenant=other_tenant, actor=stranger_actor, provider="example", name="Theirs"
    )
    api.force_login(owner)
    assert api.get(f"{LIST_URL}{theirs.pk}/").status_code == 404


def test_revoking_through_the_door(
    api: Client, tenant: Tenant, owner: User, connection: Connection
) -> None:
    api.force_login(owner)
    response = api.post(
        f"{LIST_URL}{connection.pk}/revoke/",
        data=json.dumps({"reason": "no longer used"}),
        content_type=JSON,
    )

    assert response.status_code == 200
    assert _body(response)["status"] == "revoked"
    assert _body(response)["has_credentials"] is False


# --- OAuth ----------------------------------------------------------------------


def test_the_oauth_handshake_end_to_end_with_the_bundled_provider(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Start, follow the state, come back, and find the tokens stored."""
    connection = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="OAuth"
    )
    api.force_login(owner)

    started = api.post(
        f"{LIST_URL}{connection.pk}/oauth/start/", data=json.dumps({}), content_type=JSON
    )
    assert started.status_code == 200
    start = _body(started)
    assert start["authorization_url"].startswith("https://example.invalid/oauth/authorize?")
    assert f"state={start['state']}" in start["authorization_url"]
    assert start["connection_id"] == str(connection.pk)

    returned = api.get(f"{LIST_URL}oauth/callback/?code=the-code&state={start['state']}")
    assert returned.status_code == 200
    assert _body(returned)["has_credentials"] is True

    connection.refresh_from_db()
    assert connection.access_token == "example-access-token-for-the-code"
    assert connection.credentials["refresh_token"] == "example-refresh-token-for-the-code"
    assert connection.status == Connection.Status.CONNECTED


def test_a_state_works_exactly_once(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """A callback URL out of a browser history must not store a second set."""
    connection = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Replay"
    )
    api.force_login(owner)
    state = _body(
        api.post(f"{LIST_URL}{connection.pk}/oauth/start/", data=json.dumps({}), content_type=JSON)
    )["state"]

    first = api.get(f"{LIST_URL}oauth/callback/?code=a&state={state}")
    second = api.get(f"{LIST_URL}oauth/callback/?code=b&state={state}")

    assert first.status_code == 200
    assert second.status_code == 400
    connection.refresh_from_db()
    assert connection.access_token == "example-access-token-for-a"


def test_an_unknown_state_is_refused(api: Client, owner: User) -> None:
    api.force_login(owner)
    response = api.get(f"{LIST_URL}oauth/callback/?code=a&state=never-issued")
    assert response.status_code == 400


def test_a_state_issued_for_another_tenant_is_refused(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    """The pair is what the state exists for: a valid one from elsewhere is still no."""
    theirs = create_connection(
        tenant=other_tenant, actor=stranger_actor, provider="example", name="Theirs"
    )
    from apps.connections.api import _state_key

    cache.set(
        _state_key("borrowed"),
        {
            "connection_id": str(theirs.pk),
            "tenant_id": str(other_tenant.pk),
            "redirect_uri": "https://example.invalid/back",
        },
        60,
    )

    api.force_login(owner)
    response = api.get(f"{LIST_URL}oauth/callback/?code=a&state=borrowed")
    assert response.status_code == 400


def test_a_connection_whose_provider_has_no_adapter_cannot_start(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    connection = create_connection(
        tenant=tenant, actor=owner_actor, provider="nobody-implements-this", name="Unknown"
    )
    api.force_login(owner)
    response = api.post(
        f"{LIST_URL}{connection.pk}/oauth/start/", data=json.dumps({}), content_type=JSON
    )
    assert response.status_code == 404


# The tripwire for the ruling (design-agreements.md: `oauth_start` stays
# ungated — the callback is the wall) turns on two facts
# that no other test in this file holds down together: a plain member CAN start
# a handshake, and the same member CANNOT finish one. The clause that
# `update_credentials` loses or valves its require — is invisible to every
# other test here, because every other OAuth test drives the arc as an owner and
# would stay green with the require deleted.
def test_a_member_starts_the_handshake_and_the_callback_is_the_wall(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor, member: User
) -> None:
    """The whole arc as a plain member: start succeeds, the return trip is refused.

    PLANT-VERIFIED, both directions:

    * remove `require(actor, "connection.update", connection)` from
      `services.update_credentials` and this test fails at the callback with
      `200 != 403`, and — with that assertion removed too — goes on to fail on
      the stored credential: observed, in that order,
      `{'access_token': 'example-access-token-for-the-members-code',
      'refresh_token': ..., 'token_type': 'bearer'}` in `connection.credentials`,
      a stamped `connected_at`, and an `Event` row named
      `connections.connection.credentials_updated` beside the `created` one.
      That is the shape of the world the ruling forbids.
    * the positive control is in the test itself, not in a comment: the last
      third drives the identical arc as the owner and asserts the token DOES
      land. The exchange is real (`ExampleProvider.exchange_code` mints a token
      from the code deterministically — `providers.py`), so the member's empty
      credentials cannot be a broken fixture quietly passing.
    """
    connection = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Member arc"
    )
    events = _events_model().objects
    # A dict comparison would pass on a re-ordered re-encode of the same keys;
    # the bytes are what "unchanged" has to mean for a credential blob.
    before = json.dumps(connection.credentials, sort_keys=True).encode()
    assert before == b"{}", "the OAuth shape: created empty, filled by the callback"
    # `status` starts at the model's `connected` default whether or not a
    # credential is held, so it is not the tell on its own — `connected_at`,
    # which only `update_credentials` ever stamps, is.
    before_status = connection.status
    assert connection.connected_at is None

    api.force_login(member)

    # Clause (1) of the ruling: starting stores nothing and is not gated.
    started = api.post(
        f"{LIST_URL}{connection.pk}/oauth/start/", data=json.dumps({}), content_type=JSON
    )
    assert started.status_code == 200, "the ruling: oauth_start stays ungated"
    state = _body(started)["state"]

    # Clause (2): the callback runs as the arriving session's actor, and that
    # actor is refused by `update_credentials` — after a real exchange, which is
    # the residual the ruling recorded and did not book.
    returned = api.get(f"{LIST_URL}oauth/callback/?code=the-members-code&state={state}")

    assert returned.status_code == 403, "the callback is the wall"
    assert _body(returned)["code"] == "forbidden"

    connection.refresh_from_db()
    assert json.dumps(connection.credentials, sort_keys=True).encode() == before
    assert connection.access_token == ""
    assert connection.status == before_status
    assert connection.connected_at is None, "nothing stamped the connection connected"
    assert not events.for_tenant(tenant).filter(name=CONNECTION_CREDENTIALS_UPDATED).exists(), (
        "a refused write that still emitted would be a lie on the spine"
    )

    # The refusal must not burn the connection: the member can try again, and an
    # owner can still finish. A wall that costs the row is a wall nobody keeps.
    again = api.post(
        f"{LIST_URL}{connection.pk}/oauth/start/", data=json.dumps({}), content_type=JSON
    )
    assert again.status_code == 200

    api.force_login(owner)
    owners_state = _body(
        api.post(f"{LIST_URL}{connection.pk}/oauth/start/", data=json.dumps({}), content_type=JSON)
    )["state"]
    finished = api.get(f"{LIST_URL}oauth/callback/?code=the-owners-code&state={owners_state}")

    assert finished.status_code == 200
    assert _body(finished)["has_credentials"] is True
    connection.refresh_from_db()
    assert connection.access_token == "example-access-token-for-the-owners-code"
    assert events.for_tenant(tenant).filter(name=CONNECTION_CREDENTIALS_UPDATED).count() == 1


# --- The inbound receiver --------------------------------------------------------


def test_a_correctly_signed_delivery_is_accepted_and_stored(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    body = b'{"event": "thing.happened"}'
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(body), "X-Event-Type": "thing.happened"},
    )

    assert response.status_code == 202, "accepted, never processed"
    stored = InboundWebhook.objects.for_tenant(tenant).get(pk=_body(response)["id"])
    assert stored.connection_id == connection.pk
    assert stored.body == body.decode()
    assert stored.event_type == "thing.happened"


def test_an_unsigned_delivery_is_refused_and_stores_nothing(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    response = api.post(_webhook_url(connection), data=b'{"event": "x"}', content_type=JSON)
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_wrongly_signed_delivery_is_refused(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    body = b'{"event": "x"}'
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(body, secret="the-wrong-secret")},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_signature_over_a_different_body_is_refused(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """The signature is over the body, so a swapped body must not verify."""
    response = api.post(
        _webhook_url(connection),
        data=b'{"amount": 1000000}',
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(b'{"amount": 1}')},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_revoked_connection_stops_accepting_deliveries(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor, connection: Connection
) -> None:
    """The inbound door closes with the outbound one, in the same service call."""
    from apps.connections.services import revoke_connection

    body = b"{}"
    signature = _signature(body)
    revoke_connection(tenant=tenant, actor=owner_actor, connection=connection)

    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature},
    )
    assert response.status_code == 404


def test_an_unknown_connection_id_is_404_and_says_nothing_else(api: Client) -> None:
    response = api.post(
        f"{LIST_URL}00000000-0000-7000-8000-000000000000/webhook/",
        data=b"{}",
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(b"{}")},
    )
    assert response.status_code == 404


def test_the_receiver_needs_no_session_and_no_token(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """`auth=None` is the point of the route; this is what proves it is really on."""
    body = b"{}"
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(body)},
    )
    assert response.status_code == 202
    assert "_auth_user_id" not in api.session


# --- Redelivery (ADR connections-1) ----------------------------------------------
#
# Providers retry. Stripe, GitHub and every other sender worth integrating with
# resend a delivery they did not get a 2xx for, and many resend one they did —
# a timeout on their side, a redeploy on ours, an operator clicking "resend" in
# a dashboard. Each of those arrives with the **same** `X-Delivery-Id`, which is
# the provider's own claim that this is the same delivery and not a second
# thing that happened.
#
# `x-delivery-id` has been in `KEPT_HEADERS` and stored on every row since the
# app landed, and nothing has ever read it: a redelivery made a second
# `InboundWebhook` row and a second hand-off, so one provider retry became two
# events downstream and whatever the product did with them, twice.


def test_a_redelivery_is_answered_with_the_row_it_already_stored(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """The provider's own id is what says "this is the same delivery".

    Two POSTs, one `X-Delivery-Id`: one row, one hand-off, both answered 202 —
    because a sender that retries must be able to retry safely, and the 202 is
    the contract regardless of which attempt this is.
    """
    body = b'{"event": "invoice.paid", "id": "in_1"}'
    headers = {
        SIGNATURE_HEADER: _signature(body),
        "X-Event-Type": "invoice.paid",
        "X-Delivery-Id": "evt_provider_0001",
    }

    first = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    second = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)

    assert (first.status_code, second.status_code) == (202, 202)
    assert _body(first)["id"] == _body(second)["id"], "the same delivery is the same row"
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


def test_two_deliveries_without_an_id_are_two_deliveries(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """Dedup never invents identity.

    A provider that sends no `X-Delivery-Id` has made no claim about sameness,
    and two byte-identical bodies from such a provider are two things that
    happened — a second `payment.retried` for the same amount is not the first
    one arriving twice. Deduping those would be this product overruling a
    sender about its own events.
    """
    body = b'{"event": "thing.happened"}'
    headers = {SIGNATURE_HEADER: _signature(body)}

    first = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    second = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)

    assert (first.status_code, second.status_code) == (202, 202)
    assert _body(first)["id"] != _body(second)["id"]
    assert InboundWebhook.objects.for_tenant(tenant).count() == 2


# --- the same claim, in the words a real ESP uses ---------------------------
# E1′ drove this door with Resend and found the dedup above did not fire at
# all: Resend signs through Svix, which names its delivery `svix-id` — and
# `webhook-id`, the vendor-neutral Standard Webhooks spelling of the same
# value. Neither was `x-delivery-id`, so every Resend redelivery wrote a second
# row and a second hand-off. Idempotence still held in the services below (a
# bounce recorded once, one event emitted), which is exactly why this was
# invisible: the damage was one extra stored row and one extra hand-off per
# retry, and nothing anywhere said so.


@pytest.mark.parametrize("header", ["Webhook-Id", "Svix-Id"])
def test_a_redelivery_named_the_way_a_real_esp_names_it_is_the_same_row(
    api: Client, tenant: Tenant, connection: Connection, header: str
) -> None:
    """The provider's own id, whichever of the three spellings it uses."""
    body = b'{"type": "email.delivered", "data": {"email_id": "e_1"}}'
    headers = {SIGNATURE_HEADER: _signature(body), header: "msg_2b1c9f"}

    first = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    second = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)

    assert (first.status_code, second.status_code) == (202, 202)
    assert _body(first)["id"] == _body(second)["id"], f"{header} is a delivery id"
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


def test_the_delivery_id_spellings_are_consulted_in_a_declared_order(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """A sender naming two of them gets the declared winner, not a dict's mood.

    Reading whichever spelling the request happened to carry first would make
    the identity of a delivery depend on header ordering — a property no sender
    controls and no reader could reproduce from the row afterwards.
    """
    body = b'{"type": "email.bounced"}'
    both = {
        SIGNATURE_HEADER: _signature(body),
        "X-Delivery-Id": "ours",
        "Svix-Id": "theirs",
    }
    ours_only = {SIGNATURE_HEADER: _signature(body), "X-Delivery-Id": "ours"}

    first = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=both)
    second = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=ours_only)

    assert _body(first)["id"] == _body(second)["id"], "x-delivery-id wins, as declared"
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


def test_a_signed_deliverys_own_signature_headers_survive_on_the_row(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """A stored delivery nobody can re-verify is a body, not evidence.

    *Absent:* the row keeps the payload and drops the three headers that signed
    it, so on the morning a provider says "we sent it" and we say "we refused
    it", the row cannot settle the argument — and no replay of it can either.
    """
    body = b'{"type": "email.complained"}'
    headers = {
        SIGNATURE_HEADER: _signature(body),
        "Svix-Id": "msg_kept",
        "Svix-Timestamp": "1755916800",
        "Svix-Signature": "v1,ZmFrZQ==",
    }

    response = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)

    assert response.status_code == 202
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.headers["svix-id"] == "msg_kept"
    assert stored.headers["svix-timestamp"] == "1755916800"
    assert stored.headers["svix-signature"] == "v1,ZmFrZQ=="
    assert "authorization" not in stored.headers, "the allow-list is still an allow-list"


def test_the_receiver_signature_takes_a_row_and_no_loose_pair() -> None:
    """The instrument is the signature itself (ADR connections-1).

    `verify_and_store` used to take `secret` and `tenant` as two loose values,
    which asked every caller to keep them matched by hand. The fix is not a
    check — it is that there is no longer anything to mismatch. Pinned here
    because the defect can only come back the same way it arrived: somebody
    adding a convenience parameter.
    """
    parameters = inspect.signature(_receiver()).parameters
    assert "source" in parameters
    assert parameters["source"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "secret" not in parameters, "the secret comes off the row, or not at all"
    assert "tenant" not in parameters, "so does the tenant, from the same row"


def test_a_foreign_row_verifies_and_stores_entirely_within_its_own_tenant(
    tenant: Tenant,
    other_tenant: Tenant,
    owner_actor: Actor,
    stranger_actor: Actor,
) -> None:
    """The mismatch is unrepresentable, not refused.

    Two real connections in two tenants, each with its own secret. Hand the
    receiver the *other* tenant's row and the delivery is verified against THAT
    row's secret and stored into THAT row's tenant — one object, both facts, no
    way to pair them wrongly. Under the old loose-pair signature this same call
    site could have verified against one and written into the other, which is a
    forged event in somebody else's tenant with no refusal anywhere.
    """
    event_model = _events_model()
    verify_and_store = _receiver()

    theirs = create_connection(
        tenant=other_tenant,
        actor=stranger_actor,
        provider="example",
        name="Theirs",
        credentials={"webhook_secret": "their-own-secret"},  # pragma: allowlist secret
    )
    body = b'{"id": "evt_cross_tenant"}'
    signature = SIGNATURE_PREFIX + hmac.new(b"their-own-secret", body, hashlib.sha256).hexdigest()

    event = verify_and_store(body, signature, source=theirs, name="example.thing.received")

    assert event.tenant_id == other_tenant.pk, "the row's tenant, and only ever the row's"
    assert event_model.objects.for_tenant(other_tenant).filter(pk=event.pk).exists()
    assert not event_model.objects.for_tenant(tenant).filter(pk=event.pk).exists()

    # And the secret really was that row's: this tenant's connection has a
    # different one, so its signature does not verify against the foreign row.
    mine = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Mine",
        credentials={"webhook_secret": "my-own-secret"},  # pragma: allowlist secret
    )
    mine_signature = SIGNATURE_PREFIX + hmac.new(b"my-own-secret", body, hashlib.sha256).hexdigest()
    with pytest.raises(Forbidden):
        verify_and_store(body, mine_signature, source=theirs, name="example.thing.received")
    assert mine.webhook_secret != theirs.webhook_secret


def test_a_second_connection_may_reuse_a_delivery_id(
    api: Client, tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    """The uniqueness is per connection, because the id is the provider's.

    Two providers — or two accounts of one provider — number their deliveries
    independently, and `evt_1` from Stripe has nothing to do with `evt_1` from
    Slack. A global unique constraint would silently drop the second one.
    """
    second = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Second account",
        credentials={"webhook_secret": WEBHOOK_SECRET},
    )
    body = b'{"event": "thing.happened"}'
    headers = {SIGNATURE_HEADER: _signature(body), "X-Delivery-Id": "shared-id-1"}

    first = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    other = api.post(_webhook_url(second), data=body, content_type=JSON, headers=headers)

    assert (first.status_code, other.status_code) == (202, 202)
    assert _body(first)["id"] != _body(other)["id"]
    assert InboundWebhook.objects.for_tenant(tenant).count() == 2


def test_a_redelivery_hands_off_once(api: Client, tenant: Tenant, connection: Connection) -> None:
    """One hand-off, not two — the whole reason dedup is worth having.

    The row is what a retry would otherwise duplicate, but the *cost* of the
    duplicate is downstream: a second hand-off means a second event on the
    spine and whatever the product did with it, twice.
    """
    body = b'{"event": "invoice.paid"}'
    headers = {SIGNATURE_HEADER: _signature(body), "X-Delivery-Id": "evt_handed_once"}

    events = _events_model().objects
    api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    handed = list(events.for_tenant(tenant).values_list("pk", flat=True))

    api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)

    assert list(events.for_tenant(tenant).values_list("pk", flat=True)) == handed
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.delivery_id == "evt_handed_once"
    assert stored.status == InboundWebhook.Status.HANDED_OFF


# --- The freshness half: `X-Signature-V2` (ADR connections-2) --------------------
#
# An HMAC over a body says *who* signed it and never *when*, so a delivery
# captured off the wire verifies for as long as the secret lives. The template's
# own outbound signer closed that on the way out; these tests are the way in.
#
# The scheme is `apps.events`' — the same envelope the signer in `apps.events.activities` sends —
# and everything about it except the header NAME is read across the border at
# call time (`services._events_attr`). So is everything here: the tolerance the
# assertions use, the signer's own header constant, and the verifier whose
# source the constant-time test reads. Nothing in this file imports the events
# app, for the reason `test_discovery` states.

EVENTS_ACTIVITIES = "apps.events.activities"


def _sign_v2_header(body: bytes, *, timestamp: int, secret: str = WEBHOOK_SECRET) -> str:
    """The header an honest sender builds: `t=<unix>,sha256=<hex over "<t>.<body>">`.

    Written out here rather than borrowed from the signer, deliberately: this is
    the *subscriber's* half, and a test that signed by calling the code under
    test would pass just as happily if both ends were wrong together.
    """
    payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},{SIGNATURE_PREFIX}{digest}"


def _tolerance() -> timedelta:
    """The window, off the one constant that owns it."""
    window = signature_v2_tolerance()
    assert window is not None, "apps.events is installed in this tree, so there is a window"
    return window


def _unix(moment: datetime) -> int:
    return int(moment.timestamp())


def _pinned_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Stop the verifier's clock on a whole second and return the instant it now reads.

    The freshness half of the check compares the verifier's own `now()` against
    the header's `t`, and `t` is **whole seconds by grammar** —
    `parse_signature_v2` refuses anything else, which the "a floating-point
    timestamp" case below pins. So a boundary test that builds its header from a
    live clock is spending its margin on two things it never named: the
    sub-second `int()` drops in `_unix`, and however long the request takes. One
    second does not cover them: the ahead-of-the-window refusal
    read `assert 202 == 401` about one run in three, serially, alone, with no
    edit between the green and the red.

    Pinning makes the margin the whole of the assertion. **Whole seconds**,
    because a pinned instant with a fraction still left in it would put the same
    `int()` back between this test and the window.

    The clock moved is the verifier's, not the sender's, for the reason the
    replay test above gives: it is the only one of the two a test can move
    without also re-signing.
    """
    pinned = now().replace(microsecond=0)
    monkeypatch.setattr("apps.events.receivers.now", lambda: pinned)
    return pinned


def test_a_fresh_v2_delivery_is_accepted_and_stored(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    body = b'{"event": "thing.happened"}'
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={
            SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=_unix(now())),
            "X-Event-Type": "thing.happened",
        },
    )

    assert response.status_code == 202, "accepted, never processed"
    stored = InboundWebhook.objects.for_tenant(tenant).get(pk=_body(response)["id"])
    assert stored.connection_id == connection.pk
    assert stored.body == body.decode()
    assert stored.event_type == "thing.happened"


def test_the_same_delivery_replayed_past_the_window_is_refused_and_stores_nothing(
    api: Client, tenant: Tenant, connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline pair, and the whole reason this scheme exists.

    The *same bytes* and the *same header* — a capture, not a re-signing — sent
    twice, with nothing changed between the two posts except how much time the
    verifier believes has passed. The first is accepted; the second is refused
    and leaves no second row. Under the older scheme the second post is
    byte-identical to a delivery that verified, and there is nothing in the
    scheme to refuse it with.

    The clock is moved on the verifier rather than on the sender because that is
    what a replay *is*: the attacker cannot change the timestamp (it is inside
    the digest) and does not need to — they only need to wait.
    """
    body = b'{"amount": 1000000, "to": "the attacker"}'
    captured = _sign_v2_header(body, timestamp=_unix(now()))
    headers = {SIGNATURE_V2_HEADER: captured}

    first = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    assert first.status_code == 202
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1

    later = now() + _tolerance() + timedelta(seconds=1)
    monkeypatch.setattr("apps.events.receivers.now", lambda: later)

    replayed = api.post(_webhook_url(connection), data=body, content_type=JSON, headers=headers)
    assert replayed.status_code == 401
    assert _body(replayed)["detail"] == "Invalid signature."
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1, "nothing new was stored"


def test_a_delivery_signed_before_the_window_is_refused(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """Stale in the other direction: signed correctly, just too long ago."""
    body = b'{"event": "x"}'
    stale = now() - _tolerance() - timedelta(seconds=1)
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=_unix(stale))},
    )
    assert response.status_code == 401
    assert _body(response)["detail"] == "Invalid signature."
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_delivery_signed_ahead_of_the_window_is_refused(
    api: Client, tenant: Tenant, connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window is symmetric: a sender's clock far *fast* is refused too.

    One second the far side of the edge the test below accepts, against a
    pinned clock (`_pinned_clock` — see its docstring for why it is pinned):
    the second is the whole of the claim, and nothing moves underneath it
    while the request is in flight.
    """
    body = b'{"event": "x"}'
    pinned = _pinned_clock(monkeypatch)
    ahead = _unix(pinned + _tolerance()) + 1
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=ahead)},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_delivery_signed_at_the_ahead_edge_of_the_window_is_accepted(
    api: Client, tenant: Tenant, connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same pinned instant, one second earlier, and it lands.

    The pair is the point. A refusal test alone, against a clock the test itself
    stopped, would still be green if the window had swallowed everything — it
    cannot say the 401 came from the second. This one says it: the same body,
    the same signer, the same frozen `now`, a timestamp exactly `tolerance`
    ahead rather than a second past it, and the delivery is accepted and stored.
    Exactly at the edge is *inside* it, because the verifier's comparison is a
    strict `>` (`apps/events/receivers.py`).
    """
    body = b'{"event": "x"}'
    pinned = _pinned_clock(monkeypatch)
    edge = _unix(pinned + _tolerance())
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=edge)},
    )
    assert response.status_code == 202
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


def test_a_delivery_just_inside_the_window_is_accepted(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """The boundary is a boundary and not a cliff a legitimate sender falls off."""
    body = b'{"event": "x"}'
    edge = now() - _tolerance() + timedelta(seconds=30)
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=_unix(edge))},
    )
    assert response.status_code == 202


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("a garbled timestamp", "t=yesterday,sha256=" + "0" * 64),
        ("a floating-point timestamp", "t=1756000000.5,sha256=" + "0" * 64),
        ("an absurdly long timestamp", "t=" + "9" * 21 + ",sha256=" + "0" * 64),
        ("an empty timestamp", "t=,sha256=" + "0" * 64),
        ("no timestamp at all", "sha256=" + "0" * 64),
        ("no digest at all", "t=1756000000"),
        ("an empty digest", "t=1756000000,sha256="),
        ("neither half", "t=,sha256="),
        ("something that is not the grammar", "just-a-hex-string"),
    ],
)
def test_a_malformed_v2_header_is_refused(
    api: Client, tenant: Tenant, connection: Connection, label: str, value: str
) -> None:
    """Every way the envelope can arrive broken answers the same one sentence.

    A parse failure is a refusal, never a fall-through to the older scheme: the
    header was sent, so the sender chose the scheme, and a verifier that
    shrugged at a header it could not read would be a verifier an attacker could
    disable by sending nonsense.
    """
    response = api.post(
        _webhook_url(connection),
        data=b'{"event": "x"}',
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: value},
    )
    assert response.status_code == 401, label
    assert _body(response)["detail"] == "Invalid signature."
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_fresh_v2_delivery_signed_with_the_wrong_secret_is_refused(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    body = b'{"event": "x"}'
    forged = _sign_v2_header(body, timestamp=_unix(now()), secret="the-wrong-secret")
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: forged},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_v2_signature_over_a_different_body_is_refused(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """The digest covers the body as well as the timestamp."""
    timestamp = _unix(now())
    response = api.post(
        _webhook_url(connection),
        data=b'{"amount": 1000000}',
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: _sign_v2_header(b'{"amount": 1}', timestamp=timestamp)},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_moved_timestamp_does_not_rescue_a_stale_capture(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """`t` is inside the digest, so editing it to be fresh breaks the signature.

    This is the property that makes checking the window *before* the digest
    safe: an unverified timestamp can only ever cause a refusal.
    """
    body = b'{"event": "x"}'
    stale = _sign_v2_header(body, timestamp=_unix(now() - _tolerance() - timedelta(seconds=1)))
    _old, _comma, digest = stale.partition(",")
    forged = f"t={_unix(now())},{digest}"

    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: forged},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_connection_with_no_secret_refuses_a_v2_delivery(
    api: Client, tenant: Tenant, owner_actor: Actor
) -> None:
    """The empty-secret clause covers the new scheme too.

    A connection whose credentials hold no webhook secret signs nothing and
    verifies nothing — and the reading of "no secret configured" that lets
    everything through is how a receiver ends up open. Signed with the empty
    string, which is what an attacker who *knew* the secret was empty would do.
    """
    secretless = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="No secret here",
        credentials={"access_token": "an-access-token"},
    )
    assert secretless.webhook_secret == ""

    body = b'{"event": "x"}'
    response = api.post(
        _webhook_url(secretless),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=_unix(now()), secret="")},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


# --- Expand without downgrade ----------------------------------------------------


def test_a_v1_only_delivery_still_verifies_exactly_as_before(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """The expand half: a sender that never heard of the new scheme is untouched.

    `scripts/mail_demo.py` is one such sender and stays on the v1-only path.
    """
    body = b'{"event": "thing.happened"}'
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(body)},
    )
    assert response.status_code == 202
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


def test_a_valid_v1_cannot_rescue_a_stale_v2_header(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """No downgrade. When the new header is present it is the only one consulted.

    Otherwise the scheme buys nothing: anyone replaying a capture would send the
    header that carries no window and drop the one that does.
    """
    body = b'{"event": "x"}'
    stale = _sign_v2_header(body, timestamp=_unix(now() - _tolerance() - timedelta(seconds=1)))

    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(body), SIGNATURE_V2_HEADER: stale},
    )
    assert response.status_code == 401
    assert _body(response)["detail"] == "Invalid signature."
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_valid_v1_cannot_rescue_a_forged_v2_header(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    body = b'{"event": "x"}'
    forged = f"t={_unix(now())},{SIGNATURE_PREFIX}{'0' * 64}"
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: _signature(body), SIGNATURE_V2_HEADER: forged},
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_a_fresh_v2_is_enough_on_its_own_with_a_wrong_v1_beside_it(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """The other direction of the same rule: v2 present, v2 decides — and it says yes."""
    body = b'{"event": "x"}'
    response = api.post(
        _webhook_url(connection),
        data=body,
        content_type=JSON,
        headers={
            SIGNATURE_HEADER: _signature(body, secret="the-wrong-secret"),
            SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=_unix(now())),
        },
    )
    assert response.status_code == 202
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


# --- The seams the v2 signature scheme must not have moved -----------------


def test_a_registered_verifier_still_decides_ahead_of_both_schemes(
    api: Client, tenant: Tenant, owner_actor: Actor
) -> None:
    """The registered-verifier seam is untouched: a provider's own goes first.

    Proven with a header neither house scheme would accept, so a 202 can only
    have come from the registered verifier.
    """
    claimed = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="a-provider-with-its-own-scheme",
        name="Theirs",
        credentials={"webhook_secret": WEBHOOK_SECRET},
    )

    def their_verifier(
        *, connection: Connection, body: bytes, headers: Mapping[str, str]
    ) -> bool | None:
        return headers.get("X-Their-Scheme") == "correct"

    providers.register_webhook_verifier(claimed.provider, their_verifier)
    try:
        response = api.post(
            _webhook_url(claimed),
            data=b'{"event": "x"}',
            content_type=JSON,
            headers={
                "X-Their-Scheme": "correct",
                SIGNATURE_V2_HEADER: "t=1,sha256=" + "0" * 64,
            },
        )
        assert response.status_code == 202
        assert InboundWebhook.objects.for_tenant(tenant).count() == 1
    finally:
        providers.unregister_webhook_verifier(claimed.provider)


def test_a_verifier_with_no_opinion_falls_through_to_the_v2_check(
    api: Client, tenant: Tenant, owner_actor: Actor
) -> None:
    """`None` still means "no opinion", and the door's own schemes still decide."""
    claimed = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="a-provider-that-abstains",
        name="Theirs",
        credentials={"webhook_secret": WEBHOOK_SECRET},
    )

    def abstains(*, connection: Connection, body: bytes, headers: Mapping[str, str]) -> bool | None:
        return None

    providers.register_webhook_verifier(claimed.provider, abstains)
    try:
        body = b'{"event": "x"}'
        accepted = api.post(
            _webhook_url(claimed),
            data=body,
            content_type=JSON,
            headers={SIGNATURE_V2_HEADER: _sign_v2_header(body, timestamp=_unix(now()))},
        )
        assert accepted.status_code == 202

        old = _sign_v2_header(body, timestamp=_unix(now() - _tolerance() - timedelta(seconds=1)))
        stale = api.post(
            _webhook_url(claimed),
            data=body,
            content_type=JSON,
            headers={SIGNATURE_V2_HEADER: old},
        )
        assert stale.status_code == 401
    finally:
        providers.unregister_webhook_verifier(claimed.provider)


# --- The contract, and the one number ---------------------------------------------


def test_the_v2_header_name_is_the_signers_own() -> None:
    """The one thing this door copies, held to its source by a test.

    The header NAME has to be a literal in `api.py` — the door cannot ask "is
    this header present" without it — so this is the drift that copy could
    cause, and this is what refuses it. Everything else about the scheme (the
    window, the element grammar, the comparison) is read across the border at
    call time.
    """
    signer = importlib.import_module(EVENTS_ACTIVITIES)
    assert SIGNATURE_V2_HEADER == signer.SIGNATURE_V2_HEADER


def test_the_window_is_the_events_constant_and_not_a_second_copy() -> None:
    """`signature_v2_tolerance()` is a read, never a redeclaration."""
    receivers = importlib.import_module(EVENTS_RECEIVERS)
    assert signature_v2_tolerance() is receivers.SIGNATURE_V2_TOLERANCE


def test_the_published_window_is_the_constant_in_minutes() -> None:
    """The contract teaches the number, and the number is derived from the code.

    A docstring is what an honest sender reads before writing a line, so a
    tolerance published as a different number from the one enforced is worse
    than no tolerance published at all.
    """
    minutes = int(_tolerance().total_seconds() // 60)
    published = receive_webhook.__doc__ or ""
    assert f"{minutes} minutes" in published
    assert set(re.findall(r"(\d+) minutes", published)) == {str(minutes)}


def test_the_contract_teaches_the_scheme_the_grammar_and_which_one_wins() -> None:
    """The four things a stranger with an API key needs, in the published half."""
    published = receive_webhook.__doc__ or ""
    assert SIGNATURE_V2_HEADER in published, "the preferred scheme is named"
    assert "t=<seconds>,sha256=<hex>" in published, "the grammar is spelled out"
    assert "preferred" in published
    assert "only header consulted" in published, "no downgrade, said on the wire contract"


def test_the_v2_comparison_is_constant_time() -> None:
    """The comparison this door delegates to is `compare_digest`, not `==`.

    Read off the function actually called rather than asserted about a copy: a
    byte-by-byte comparison that returns early leaks, over enough requests, how
    much of a forged signature was right.
    """
    receivers = importlib.import_module(EVENTS_RECEIVERS)
    assert "hmac.compare_digest" in inspect.getsource(receivers.signature_v2_matches)
    assert "hmac.compare_digest" in inspect.getsource(signature_matches)
