"""The seam: who gets told about a stored delivery, and what it costs when they fail.

`apps/connections` owns the product's one signature-verified inbound route and
**must never learn what a payload means** — an ESP's bounce, a payment
provider's dispute, a calendar's change notification are all somebody else's
vocabulary. So the receiver stores the delivery, hands it to the event spine,
and starts a run for whichever app claimed this provider's slug (ADR comms-4).
`apps/comms` is the first caller; nothing here knows that.

These tests plant a handler of their own rather than driving comms', which is
what makes them tests of the *seam* rather than a second copy of
`apps/comms/tests/test_delivery_status.py`. The two questions they exist for:

* is a registered handler started as a run rather than called in the request,
  and does that run's service call it with the stored row and the system actor;
* **does a handler that blows up leave a receipt that says so?** The savepoint
  is what lets a database error in the handler leave the status write intact.
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
from apps.connections.services import apply_inbound_webhook, create_connection
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.connections.tests.handler_runs import run_handlers_at_the_receipt
from apps.connections.types import HANDLE_WORKFLOW
from apps.core import bridge
from apps.core.actor import Actor, system_actor
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
        is_signature_v2_required=False,
    )


@pytest.fixture
def starts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every handler run the receiver asks the platform's starter for, captured at the bridge."""
    asked: list[dict[str, Any]] = []

    def spy(**kw: Any) -> None:
        if kw["workflow"] == HANDLE_WORKFLOW:
            asked.append(kw)

    monkeypatch.setitem(bridge._registry, bridge.START_WORKFLOW_ON_COMMIT, spy)
    return asked


def _handle(tenant: Tenant, received: InboundWebhook) -> InboundWebhook:
    return apply_inbound_webhook(
        tenant=tenant, actor=system_actor(tenant), inbound_webhook_id=received.pk
    )


def test_a_claimed_delivery_starts_its_handler_run_and_never_calls_it_inline(
    api: Client,
    tenant: Tenant,
    claimed: Connection,
    starts: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setitem(
        providers._inbound, claimed.provider, lambda **kw: called.append(kw["received"].body)
    )

    response = _post(api, claimed)

    assert response.status_code == 202
    assert called == []
    assert [s["workflow"] for s in starts] == [HANDLE_WORKFLOW]
    assert starts[0]["arg"].inbound_webhook_id == response.json()["id"]
    assert starts[0]["id"].endswith(f":connections:inbound_webhook:{response.json()['id']}")


def test_the_run_calls_the_handler_with_the_stored_row_and_the_actor(
    api: Client,
    tenant: Tenant,
    claimed: Connection,
    starts: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def handler(*, received: InboundWebhook, actor: Actor) -> None:
        seen.append((received.body, actor.kind))

    monkeypatch.setitem(providers._inbound, claimed.provider, handler)
    _post(api, claimed, b'{"event": "thing.happened"}')

    handled = _handle(tenant, InboundWebhook.objects.for_tenant(tenant).get())

    assert seen == [('{"event": "thing.happened"}', "system")]
    assert handled.status == InboundWebhook.Status.HANDLED
    assert handled.handed_off_at is not None


def test_the_receipt_seam_runs_the_handler_where_the_receiver_starts_it(
    api: Client, tenant: Tenant, claimed: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`handler_runs` is how a test that drives the door reads a handler's effect at the 202."""
    seen: list[str] = []
    monkeypatch.setitem(
        providers._inbound, claimed.provider, lambda **kw: seen.append(kw["received"].body)
    )
    run_handlers_at_the_receipt(monkeypatch)

    assert _post(api, claimed).status_code == 202

    assert seen == ['{"event": "x"}']
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.status == InboundWebhook.Status.HANDLED


def test_a_provider_nobody_claimed_is_simply_silent(
    api: Client, tenant: Tenant, connection: Connection, starts: list[dict[str, Any]]
) -> None:
    """Outbound-only integrations are the ordinary case, not a misconfiguration."""
    assert providers.inbound_handler(connection.provider) is None
    assert _post(api, connection).status_code == 202
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.status == InboundWebhook.Status.HANDED_OFF, "the spine still took it"
    assert starts == []


def test_a_handler_that_raises_is_recorded_on_the_receipt(
    api: Client,
    tenant: Tenant,
    claimed: Connection,
    starts: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, received: InboundWebhook, actor: Actor) -> None:
        raise RuntimeError("the handler had an opinion")

    monkeypatch.setitem(providers._inbound, claimed.provider, handler)
    assert _post(api, claimed).status_code == 202

    handled = _handle(tenant, InboundWebhook.objects.for_tenant(tenant).get())

    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert handled.status == stored.status == InboundWebhook.Status.HANDLER_FAILED
    assert stored.body == '{"event": "x"}'


def test_a_handler_that_breaks_the_database_still_records_its_failure(
    api: Client,
    tenant: Tenant,
    claimed: Connection,
    starts: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The savepoint: an aborted query in the handler cannot take the status write with it."""

    def handler(*, received: InboundWebhook, actor: Actor) -> None:
        with db_connection.cursor() as cursor:
            cursor.execute("SELECT * FROM a_table_that_is_not_there")

    monkeypatch.setitem(providers._inbound, claimed.provider, handler)
    assert _post(api, claimed).status_code == 202

    _handle(tenant, InboundWebhook.objects.for_tenant(tenant).get())

    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.status == InboundWebhook.Status.HANDLER_FAILED


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
