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
from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from apps.connections import services
from apps.connections.models import Connection
from apps.connections.policies import ACTION_PROSE
from apps.connections.services import (
    create_connection,
    record_failure,
    record_inbound_webhook,
    revoke_connection,
    update_credentials,
)
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.authz import refusal_sentence
from apps.core.exceptions import Forbidden, Invalid
from apps.core.log import REDACTED
from apps.core.models import Membership, Organization, Tenant
from apps.core.observability import configure
from apps.core.services import add_membership, create_organization, root_organization

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


# --- The tenant's configuration is asked at the tenant's root ------------------
#
# A connection holds one credential that acts as the WHOLE tenant against
# somebody else's system: it is the tenant's configuration and not a branch's.
# Asked at the acting hat — which is what a `require` with no node, or with the
# row itself, resolves to for a row that names no organization — an
# administrator of one leaf held every one of these keys, and could open,
# re-credential and revoke the tenant's connections.
#
# The node is therefore resolved by the caller and handed to `require`, exactly
# as `apps/accounts/services.py`'s SSO sites and `core.services`'
# `update_tenant_settings` do. `record_inbound_webhook` is the one site that
# does not, and it says why on its own line.


@pytest.fixture
def branch(tenant: Tenant, owner_actor: Actor) -> Organization:
    """One node under the root, so "elsewhere in the tree" is a real place."""
    return create_organization(
        tenant=tenant,
        parent=root_organization(tenant=tenant),
        name="Branch",
        slug="branch",
        actor=owner_actor,
    )


@pytest.fixture
def branch_admin_actor(tenant: Tenant, branch: Organization, owner_actor: Actor) -> Actor:
    """An administrator of one branch and of nothing above it.

    Privileged where they stand — `admin` holds `("*",)` — and holding no role
    at all at the root, which is where a connection's authority reaches. The
    shape is `apps/accounts/tests/test_sso_role_ceiling.py`'s fixture of the
    same name, one app over.
    """
    from apps.accounts.services import create_user

    user = create_user(email="branch-admin@example.com", password=None)
    add_membership(
        user=user,
        tenant=tenant,
        organization=branch,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )
    return actor_for(user=user, tenant=tenant, org=branch)


def test_a_branch_administrator_may_not_configure_the_tenants_connections(
    tenant: Tenant,
    owner_actor: Actor,
    admin_actor: Actor,
    member_actor: Actor,
    branch_admin_actor: Actor,
    connection: Connection,
) -> None:
    """Four acts on the tenant's connection, four refusals, four sentences.

    Each refusal is asserted against `ACTION_PROSE[key]` rather than a quoted
    string, so the test says "the key's own sentence" and cannot come to mean
    "these words". A bare `pytest.raises(Forbidden)` would pass on any wall at
    all, including one that refused everybody.

    `record_failure` is here although its ordinary caller is an activity: it has
    no caller in this tree at all today, and the caller its docstring names
    restores the actor from the workflow's headers — which carry a person's hat.
    A site that is system-only *in the ordinary case* is not a site nothing but
    the system can reach, so it asks at the root like the other three rather
    than carrying a valve whose sentence would be a claim about a caller that
    does not exist.
    """
    attempts: tuple[tuple[str, Callable[[], object]], ...] = (
        (
            "connection.create",
            lambda: create_connection(
                tenant=tenant, actor=branch_admin_actor, provider="example", name="A Branch's"
            ),
        ),
        (
            "connection.update",
            lambda: update_credentials(
                tenant=tenant,
                actor=branch_admin_actor,
                connection=connection,
                credentials={"access_token": "captured"},
            ),
        ),
        (
            "connection.revoke",
            lambda: revoke_connection(
                tenant=tenant, actor=branch_admin_actor, connection=connection, reason="captured"
            ),
        ),
        (
            "connection.update",
            lambda: record_failure(
                tenant=tenant, actor=branch_admin_actor, connection=connection, reason="captured"
            ),
        ),
    )
    for key, attempt in attempts:
        with pytest.raises(Forbidden) as refused:
            attempt()
        assert refused.value.detail == ACTION_PROSE[key], key

    # NOTHING MOVED. A refusal that arrived after the write would leave the
    # branch admin's credential in place and the test green on the sentence.
    connection.refresh_from_db()
    assert connection.status == Connection.Status.CONNECTED
    assert connection.access_token == "an-access-token"
    assert connection.webhook_secret == WEBHOOK_SECRET
    assert connection.last_error == ""
    assert Connection.objects.for_tenant(tenant).count() == 1

    # The two hats that DO hold it, each on a victim of its own — a wall that
    # refuses everybody is not a wall, it is an outage.
    assert create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="The Owner's"
    ).pk
    assert create_connection(
        tenant=tenant, actor=admin_actor, provider="example", name="A Root Admin's"
    ).pk
    assert revoke_connection(tenant=tenant, actor=owner_actor, connection=connection).pk

    # And the plain member is refused exactly as before — the branch
    # administrator is the only actor the root narrows.
    with pytest.raises(Forbidden) as refused_member:
        create_connection(tenant=tenant, actor=member_actor, provider="example", name="A Member's")
    assert refused_member.value.detail == ACTION_PROSE["connection.create"]


def test_the_receiver_still_stores_a_delivery_as_the_system(
    tenant: Tenant, connection: Connection
) -> None:
    """The reason `record_inbound_webhook` carries a valve instead of the root.

    Its one caller is the inbound receiver (`api.py`), which authenticates an
    HMAC over the raw body and then builds `system_actor(tenant)` on the spot —
    there is no person on that path and no door that puts one there. `allows`
    answers `system` at step 1, before any node is resolved, so resolving the
    root for it would be a query per delivery for an answer nothing reads: the
    per-delivery write is the hottest path in this app.

    This is the assertion behind that sentence, so the valve's reason is driven
    rather than asserted in a comment.
    """
    received = record_inbound_webhook(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        body='{"hello": "root"}',
        headers={"Content-Type": "application/json"},
        event_type="thing.happened",
    )
    assert received.pk is not None
    assert received.tenant_id == tenant.pk


def test_a_branch_administrator_may_not_configure_the_tenants_connections_on_the_wire(
    api: Client,
    tenant: Tenant,
    owner: Any,
    owner_actor: Actor,
    branch_admin_actor: Actor,
    connection: Connection,
) -> None:
    """The same acts through the door a person actually uses.

    `POST /api/v1/connections/` is the case the root closes: it reaches the
    service with no read in front of it, so at the acting hat it answered
    **201** for an administrator of one leaf.

    The revoke route resolves the row first (`selectors.get_connection`), and
    that read asks `connection.read` at the tenant's ROOT today — so the branch
    admin meets a wall one step earlier than the service's. Which of the two
    tenant-wide walls speaks there is the READ register's question, and the
    read sites are not this module's subject — so the assertion names both and
    pins what the write side owns: 403, `forbidden`, and a row that did not
    move.

    **There is no MCP twin to look for.** `apps/connections` is a recorded rule
    17 exemption (`quality/rules.yaml`: connection management is per-tenant
    configuration done by a person in a browser, and the inbound receiver is a
    machine door with an HMAC credential of its own).
    """
    from apps.accounts.models import User

    branch_admin = User.objects.get(pk=str(branch_admin_actor.user_id))
    revoke_url = f"/api/v1/connections/{connection.pk}/revoke/"

    api.force_login(branch_admin)
    created = api.post(
        "/api/v1/connections/",
        {"provider": "example", "name": "A Branch's"},
        content_type="application/json",
    )
    assert created.status_code == 403
    assert created.json()["code"] == "forbidden"
    assert created.json()["detail"] == ACTION_PROSE["connection.create"]

    revoked = api.post(revoke_url, {"reason": "captured"}, content_type="application/json")
    assert revoked.status_code == 403
    assert revoked.json()["code"] == "forbidden"
    assert revoked.json()["detail"] in {
        refusal_sentence("connection.read"),
        ACTION_PROSE["connection.revoke"],
    }, revoked.json()["detail"]
    api.logout()

    connection.refresh_from_db()
    assert connection.status == Connection.Status.CONNECTED
    assert connection.webhook_secret == WEBHOOK_SECRET
    assert Connection.objects.for_tenant(tenant).count() == 1

    # The owner, through the same two routes, on the same tenant.
    api.force_login(owner)
    mine = api.post(
        "/api/v1/connections/",
        {"provider": "example", "name": "The Owner's"},
        content_type="application/json",
    )
    assert mine.status_code == 201
    assert (
        api.post(revoke_url, {"reason": "done"}, content_type="application/json").status_code == 200
    )
