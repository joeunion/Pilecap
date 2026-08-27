"""The seam: who gets told about a stored delivery, and what it costs when they fail.

`apps/connections` owns the product's one signature-verified inbound route and
**must never learn what a payload means** — an ESP's bounce, a payment
provider's dispute, a calendar's change notification are all somebody else's
vocabulary. So the receiver stores the delivery, hands it to the event spine,
and then asks a registry whether some app claimed this provider's slug (ADR
comms-4). `apps/comms` is the first caller; nothing here knows that.

These tests plant a handler of their own rather than driving comms', which is
what makes them tests of the *seam* rather than a second copy of
`apps/comms/tests/test_delivery_status.py`. The two questions they exist for:

* is a registered handler actually called, with the stored row and the actor
  the receiver authorized as — after the store, so a handler cannot be the
  reason a delivery is lost;
* **does a handler that blows up still leave a 202 and a stored row?** Both
  halves matter, and the second is the one a `try/except` alone does not buy:
  on Postgres a handler whose failure was a database error would leave the
  receipt itself unable to commit.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest
from django.db import connection as db_connection
from django.test import Client

from apps.connections import providers
from apps.connections.api import SIGNATURE_HEADER, SIGNATURE_PREFIX
from apps.connections.models import Connection, InboundWebhook
from apps.connections.services import create_connection
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.core.actor import Actor
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

JSON = "application/json"


def _post(api: Client, connection: Connection, body: bytes = b'{"event": "x"}') -> Any:
    signature = (
        SIGNATURE_PREFIX + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    )
    return api.post(
        f"/api/v1/connections/{connection.pk}/webhook/",
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature},
    )


@pytest.fixture
def claimed(tenant: Tenant, owner_actor: Actor) -> Connection:
    """A connection whose provider slug a test will claim."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="slug-with-a-handler",
        name="Something inbound",
        credentials={"webhook_secret": WEBHOOK_SECRET},
    )


def test_a_registered_handler_is_called_with_the_stored_row_and_the_actor(
    api: Client, tenant: Tenant, claimed: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hand-off happens, and it happens *after* the store.

    `received.pk` being resolvable through the manager inside the handler is the
    load-bearing assertion: it means the row was already written when the
    handler ran, which is what makes a handler unable to lose a delivery.
    """
    seen: list[tuple[str, str]] = []

    def handler(*, received: InboundWebhook, actor: Actor) -> None:
        assert InboundWebhook.objects.for_tenant(received.tenant).filter(pk=received.pk).exists()
        seen.append((received.body, actor.kind))

    monkeypatch.setitem(providers._inbound, claimed.provider, handler)

    response = _post(api, claimed, b'{"event": "thing.happened"}')

    assert response.status_code == 202
    assert seen == [('{"event": "thing.happened"}', "system")]


def test_a_provider_nobody_claimed_is_simply_silent(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    """Outbound-only integrations are the ordinary case, not a misconfiguration."""
    assert providers.inbound_handler(connection.provider) is None
    assert _post(api, connection).status_code == 202
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.status == InboundWebhook.Status.HANDED_OFF, "the spine still took it"


def test_a_handler_that_raises_costs_the_delivery_nothing(
    api: Client, tenant: Tenant, claimed: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store is the durability. One app's bad afternoon is not the door's."""

    def handler(*, received: InboundWebhook, actor: Actor) -> None:
        raise RuntimeError("the handler had an opinion")

    monkeypatch.setitem(providers._inbound, claimed.provider, handler)

    response = _post(api, claimed)

    assert response.status_code == 202
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.body == '{"event": "x"}'
    assert stored.status == InboundWebhook.Status.HANDED_OFF


def test_a_handler_that_breaks_the_database_still_leaves_the_receipt(
    api: Client, tenant: Tenant, claimed: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The savepoint, and why `except Exception` alone is not the promise.

    A `ProgrammingError` inside the receiver's transaction aborts it: without
    the `atomic()` around the hand-off, the receipt row this service already
    wrote could not commit, and the sender would get a 500 from the one route in
    the product that must never give it one. The handler here fails the way a
    real one eventually will — in the middle of a query — rather than by raising
    a tidy `RuntimeError` the transaction never notices.
    """

    def handler(*, received: InboundWebhook, actor: Actor) -> None:
        with db_connection.cursor() as cursor:
            cursor.execute("SELECT * FROM a_table_that_is_not_there")

    monkeypatch.setitem(providers._inbound, claimed.provider, handler)

    response = _post(api, claimed)

    assert response.status_code == 202
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1


def test_the_registry_takes_one_handler_per_slug_and_gives_it_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registration is by slug, case- and whitespace-insensitive, and replaces.

    Replacing rather than stacking is what keeps a dev server's autoreload from
    calling one app's handler twice.
    """
    monkeypatch.setattr(providers, "_inbound", {})

    def first(*, received: InboundWebhook, actor: Actor) -> None: ...

    def second(*, received: InboundWebhook, actor: Actor) -> None: ...

    providers.register_inbound_handler("  Some-Provider ", first)
    assert providers.inbound_handler("some-provider") is first
    assert providers.registered_inbound_handlers() == {"some-provider": first}

    providers.register_inbound_handler("some-provider", second)
    assert providers.inbound_handler("some-provider") is second

    providers.unregister_inbound_handler("some-provider")
    assert providers.inbound_handler("some-provider") is None
    assert providers.registered_inbound_handlers() == {}
