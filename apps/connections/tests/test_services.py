"""The writes, and the one property this app exists to hold.

**A credential must not be readable anywhere except in the connection it
belongs to.** The encrypted column is half of that (`test_models.py`); the other
half is the two places a service copies its arguments by design — the structured
log line and the `AuditEntry.input` — and those are what the middle of this
module is about.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from apps.connections import services
from apps.connections.models import Connection
from apps.connections.services import (
    create_connection,
    record_failure,
    record_inbound_webhook,
    revoke_connection,
    update_credentials,
)
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Forbidden, Invalid
from apps.core.log import REDACTED
from apps.core.models import Tenant
from apps.core.observability import configure

pytestmark = pytest.mark.django_db

TOKEN = "sk-live-this-must-never-be-readable"


# --- The ordinary write path --------------------------------------------------


def test_create_connection_returns_the_row_it_wrote(tenant: Tenant, owner_actor: Actor) -> None:
    created = create_connection(
        tenant=tenant, actor=owner_actor, provider="Example", name="  Primary  "
    )
    assert isinstance(created, Connection)
    assert created.provider == "example", "the slug is normalised, so two spellings are one row"
    assert created.name == "Primary"
    assert created.status == Connection.Status.CONNECTED
    assert created.has_credentials is False
    assert created.connected_at is None


def test_update_credentials_merges_rather_than_replaces(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    """An OAuth refresh returns one key; it must not take the webhook secret with it."""
    updated = update_credentials(
        tenant=tenant,
        actor=owner_actor,
        connection=connection,
        credentials={"access_token": "a-refreshed-token"},
    )
    assert updated.access_token == "a-refreshed-token"
    assert updated.webhook_secret == WEBHOOK_SECRET
    assert updated.connected_at is not None


def test_update_credentials_refuses_an_empty_mapping(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    with pytest.raises(Invalid):
        update_credentials(tenant=tenant, actor=owner_actor, connection=connection, credentials={})


def test_revoking_takes_the_credentials_with_it(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    """Including the webhook secret, which is what closes the inbound door too."""
    revoked = revoke_connection(
        tenant=tenant, actor=owner_actor, connection=connection, reason="rotated upstream"
    )
    assert revoked.status == Connection.Status.REVOKED
    assert revoked.credentials == {}
    assert revoked.webhook_secret == ""
    assert revoked.revoked_at is not None
    assert revoked.last_error == "rotated upstream"

    assert Connection.objects.for_webhook(connection.pk) is None


def test_record_failure_says_what_broke_without_saying_what_the_token_was(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    failed = record_failure(
        tenant=tenant, actor=owner_actor, connection=connection, reason="upstream returned 401"
    )
    assert failed.status == Connection.Status.ERROR
    assert failed.last_error == "upstream returned 401"
    assert failed.has_credentials is True, "a failure is not a revocation"


# --- Authorization ------------------------------------------------------------


def test_a_plain_member_may_not_open_a_connection(tenant: Tenant, member_actor: Actor) -> None:
    """Stricter than the example app on purpose: a credential acts as the tenant."""
    with pytest.raises(Forbidden):
        create_connection(tenant=tenant, actor=member_actor, provider="example", name="Sneaky")


def test_a_plain_member_may_not_revoke_one(
    tenant: Tenant, connection: Connection, member_actor: Actor
) -> None:
    with pytest.raises(Forbidden):
        revoke_connection(tenant=tenant, actor=member_actor, connection=connection)


def test_an_admin_may(tenant: Tenant, admin_actor: Actor) -> None:
    assert create_connection(
        tenant=tenant, actor=admin_actor, provider="example", name="Admin's"
    ).pk


def test_another_tenants_connections_are_not_in_the_list(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor, stranger_actor: Actor
) -> None:
    mine = create_connection(tenant=tenant, actor=owner_actor, provider="example", name="Mine")
    create_connection(tenant=other_tenant, actor=stranger_actor, provider="example", name="Theirs")
    assert [c.pk for c in Connection.objects.for_tenant(tenant)] == [mine.pk]


# --- The property: a credential is not readable anywhere else ------------------


def _audit_input(action: str) -> dict[str, Any]:
    entry = AuditEntry.objects.filter(action=action).order_by("-created_at").first()
    assert entry is not None, f"no audit row for {action}"
    return dict(entry.input)


def test_the_audit_row_records_the_write_without_recording_the_credential(
    tenant: Tenant, owner_actor: Actor
) -> None:
    create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Audited",
        credentials={"access_token": TOKEN},
    )
    recorded = _audit_input("connections.create_connection")

    assert recorded["name"] == "Audited"
    assert recorded["provider"] == "example"
    assert recorded["credentials"] == REDACTED
    assert TOKEN not in json.dumps(recorded)


def test_the_audit_row_for_a_credential_update_is_redacted_too(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    update_credentials(
        tenant=tenant, actor=owner_actor, connection=connection, credentials={"access_token": TOKEN}
    )
    recorded = _audit_input("connections.update_credentials")
    assert recorded["credentials"] == REDACTED
    assert TOKEN not in json.dumps(recorded)


def test_no_audit_row_in_this_app_ever_contains_a_credential(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    """Every service in the app, in one sweep — including ones added later."""
    update_credentials(
        tenant=tenant, actor=owner_actor, connection=connection, credentials={"access_token": TOKEN}
    )
    record_failure(
        tenant=tenant, actor=owner_actor, connection=connection, reason="upstream said no"
    )
    revoke_connection(tenant=tenant, actor=owner_actor, connection=connection)

    everything = json.dumps([dict(entry.input) for entry in AuditEntry.objects.all()])
    assert TOKEN not in everything
    assert WEBHOOK_SECRET not in everything


def test_the_credential_does_not_reach_a_log_line(
    tenant: Tenant, owner_actor: Actor, caplog: pytest.LogCaptureFixture
) -> None:
    """Read back as it left the process: `@service` logs `.called` with its arguments."""
    configure()
    with caplog.at_level(logging.INFO):
        create_connection(
            tenant=tenant,
            actor=owner_actor,
            provider="example",
            name="Logged",
            credentials={"access_token": TOKEN, "webhook_secret": WEBHOOK_SECRET},
        )

    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert "connections.create_connection.called" in emitted, "the service did log"
    assert TOKEN not in emitted
    assert WEBHOOK_SECRET not in emitted
    assert REDACTED in emitted


# --- Inbound webhooks ----------------------------------------------------------


def test_a_stored_delivery_keeps_the_body_and_drops_the_authorization_header(
    tenant: Tenant, connection: Connection
) -> None:
    received = record_inbound_webhook(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        body='{"hello": "world"}',
        headers={
            "Content-Type": "application/json",
            "X-Signature": "sha256=whatever",
            "Authorization": "Bearer somebody-elses-token",
            "Cookie": "session=abc",
        },
        event_type="thing.happened",
    )
    assert received.body == '{"hello": "world"}'
    assert received.event_type == "thing.happened"
    assert set(received.headers) == {"content-type", "x-signature"}
    assert "Bearer somebody-elses-token" not in json.dumps(received.headers)


def test_a_delivery_is_stored_even_with_no_event_spine_in_the_tree(
    tenant: Tenant, connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store is unconditional: a template without `apps/events` still receives.

    The lookup is made to answer `None` — the state a tree without the spine is
    in — rather than asserting a range of statuses that a tree *with* it would
    also satisfy. What the lookup itself does in either tree is
    `test_discovery`'s.
    """
    monkeypatch.setattr(services, "_events_callable", lambda module, name: None)

    received = record_inbound_webhook(
        tenant=tenant, actor=system_actor(tenant), connection=connection, body="{}", headers={}
    )

    assert received.pk is not None
    assert received.tenant_id == tenant.pk
    assert received.status == received.Status.RECEIVED
    assert received.handed_off_to == ""
    assert received.handed_off_at is None
