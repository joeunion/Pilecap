"""Reads are permissions in `connections`: reach before capability on the REST door (ADR core-27).

The selector census is rule 54 (d)/(e).
why-not a `DOOR_PAIR` case: rule 17 records this app's REST-only exemption, so no twin answers.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.connections.models import Connection, InboundWebhook
from apps.connections.selectors import (
    get_connection,
    get_connection_for_webhook,
    list_connections,
    list_inbound_webhooks,
)
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import refusal_sentence
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/connections/"

#: A literal long enough for Django's validators, spelled HERE rather than
#: imported from `apps/conftest.py`: that module imports `apps.workflows`, so
#: an import of it from this app's tests is this app importing a SIBLING —
#: which the layer contract refuses, and which the hook catches at the commit.
BRANCH_PASSWORD = "a-long-enough-password-for-validators"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret


@dataclass(frozen=True)
class Reads:
    """One tenant with a connection and a stored delivery, and a plain member."""

    tenant: Tenant
    other_tenant: Tenant
    reader: User
    reader_membership: Membership
    connection: Connection
    foreign_connection: Connection
    inbound: InboundWebhook

    def actor(self) -> Actor:
        """A fresh actor — fresh because the memo's TTL is the instance."""
        return actor_for(user=self.reader, tenant=self.tenant)


@pytest.fixture
def reads(tenant: Tenant, other_tenant: Tenant, member: User) -> Reads:
    connection = Connection.objects.create(
        tenant=tenant, provider="acme", name="Ours", status=Connection.Status.CONNECTED
    )
    foreign = Connection.objects.create(
        tenant=other_tenant, provider="acme", name="Theirs", status=Connection.Status.CONNECTED
    )
    inbound = InboundWebhook.objects.create(
        tenant=tenant, connection=connection, body="{}", headers={}, event_type="acme.thing"
    )
    return Reads(
        tenant=tenant,
        other_tenant=other_tenant,
        reader=member,
        reader_membership=Membership.objects.get(user=member, tenant=tenant),
        connection=connection,
        foreign_connection=foreign,
        inbound=inbound,
    )


def withhold(membership: Membership, permission: str) -> Grant:
    """A raw `withhold` row. Legal until the hand-out services land."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- the population, derived from the module ----------------------------------


def test_the_pre_auth_lookup_stays_open_and_still_scopes_by_the_row(reads: Reads) -> None:
    """The valve is not a hole: what it drops is the PERSON, not the narrowing.

    `get_connection_for_webhook` runs before any principal exists, so there is
    nobody to ask for `connection.read`. What it still does is resolve exactly
    one row by an unguessable id, through `for_webhook`, which refuses anything
    that is not `connected` — and the receiver checks an HMAC made with that
    row's own secret immediately afterwards. An id that names nothing is `None`
    (the receiver answers it as a bad signature), never some other row.
    """
    import uuid

    found = get_connection_for_webhook(connection_id=reads.connection.pk)
    assert found is not None and found.pk == reads.connection.pk
    assert get_connection_for_webhook(connection_id=uuid.uuid4()) is None


def test_a_list_without_the_key_is_forbidden_and_says_the_keys_own_sentence(reads: Reads) -> None:
    """A list has no row to hide, so the only honest answers are the page and 403."""
    withhold(reads.reader_membership, "connection.read")

    with pytest.raises(Forbidden) as refused:
        list_connections(tenant=reads.tenant, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence("connection.read")

    Grant.objects.filter(membership=reads.reader_membership, permission="connection.read").delete()
    assert list_connections(tenant=reads.tenant, actor=reads.actor()).exists()


def test_the_receipt_log_asks_its_own_kind(reads: Reads) -> None:
    """`inbound_webhook.read` and not `connection.read` — rule 54 (e)'s question.

    The two kinds are separate on purpose: the receipt log carries the bodies
    other people's servers sent, and a tenant that wants its support staff to
    read connections without reading payloads needs two words to say it with.
    """
    withhold(reads.reader_membership, "inbound_webhook.read")

    with pytest.raises(Forbidden) as refused:
        list_inbound_webhooks(tenant=reads.tenant, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence("inbound_webhook.read")

    # The sibling kind is untouched: a withhold of one read is not a withhold of
    # the other, which is the whole reason the selector asks for its own kind.
    assert list_connections(tenant=reads.tenant, actor=reads.actor()).exists()


def test_a_connection_in_another_tenant_is_not_found_and_one_here_without_the_key_is_forbidden(
    reads: Reads,
) -> None:
    """Reach before capability, asserted by the two exception TYPES (§C8)."""
    withhold(reads.reader_membership, "connection.read")

    with pytest.raises(NotFound):
        get_connection(
            tenant=reads.tenant, connection_id=reads.foreign_connection.pk, actor=reads.actor()
        )

    with pytest.raises(Forbidden) as refused:
        get_connection(tenant=reads.tenant, connection_id=reads.connection.pk, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence("connection.read")

    Grant.objects.filter(membership=reads.reader_membership, permission="connection.read").delete()
    assert (
        get_connection(
            tenant=reads.tenant, connection_id=reads.connection.pk, actor=reads.actor()
        ).pk
        == reads.connection.pk
    )


def test_the_system_actor_reads_everything_the_scope_shows(reads: Reads) -> None:
    """`system` passes at step 1, so the providers and the receiver are untouched.

    Asserted with a withhold on the reader in place, so the pass is the actor
    KIND and not an accident of there being nothing to refuse.
    """
    for key in ("connection.read", "inbound_webhook.read"):
        withhold(reads.reader_membership, key)
    system = system_actor(reads.tenant)
    assert list_connections(tenant=reads.tenant, actor=system).exists()
    assert list_inbound_webhooks(tenant=reads.tenant, actor=system).exists()
    assert (
        get_connection(tenant=reads.tenant, connection_id=reads.connection.pk, actor=system).pk
        == reads.connection.pk
    )


# --- the flat product observes nothing, and the wire says the same words ------


def test_the_plain_member_still_reads_every_connection_route(api: Client, reads: Reads) -> None:
    """Principle 13: a product that customised nothing sees the answers it saw.

    The member holds `("*.read",)` by declaration, so both read routes answer
    200 with no permission row anywhere. This is the half that would catch a
    flip that refused everybody — a seam test whose every case is a refusal
    cannot tell "asks correctly" from "asks and always says no".
    """
    api.force_login(reads.reader)
    listed = api.get(LIST_URL)
    assert listed.status_code == 200, listed.content
    assert [row["id"] for row in listed.json()["items"]] == [str(reads.connection.pk)]

    detail = api.get(f"{LIST_URL}{reads.connection.pk}/")
    assert detail.status_code == 200, detail.content


def test_a_withheld_read_is_forbidden_on_the_wire_with_the_keys_own_sentence(
    api: Client, reads: Reads
) -> None:
    """The refusal a real client meets, not the one the selector raises.

    There is no MCP twin to compare against (the module docstring says why the
    exemption is a ruling rather than a gap), so what this asserts instead is
    that the door renders the selector's refusal rather than inventing one: the
    code is `forbidden` and the detail is `refusal_sentence("connection.read")`,
    byte for byte.

    A connection in another tenant stays 404 — the half Phase R does not touch.
    """
    withhold(reads.reader_membership, "connection.read")
    sentence = refusal_sentence("connection.read")
    api.force_login(reads.reader)

    listed = api.get(LIST_URL)
    assert listed.status_code == 403, listed.content
    assert listed.json()["code"] == "forbidden"
    assert listed.json()["detail"] == sentence

    detail = api.get(f"{LIST_URL}{reads.connection.pk}/")
    assert detail.status_code == 403, detail.content
    assert detail.json()["detail"] == sentence

    foreign = api.get(f"{LIST_URL}{reads.foreign_connection.pk}/")
    assert foreign.status_code == 404, foreign.content


# --- the branch member, and the one population a sweep SHRINKS ----------------


@dataclass(frozen=True)
class Branch:
    """A member whose only membership is at a branch of the tenant's tree."""

    tenant: Tenant
    reader: User
    membership: Membership
    a1: Organization
    connection: Connection


@pytest.fixture
def branch(tenant: Tenant, owner: User) -> Branch:
    hq = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=hq)
    a1 = create_organization(tenant=tenant, parent=hq, name="Leaf A1", slug="leaf-a1", actor=acting)
    reader = create_user(email="branch-member@example.com", password=BRANCH_PASSWORD)
    add_membership(
        user=reader,
        tenant=tenant,
        organization=a1,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    connection = Connection.objects.create(
        tenant=tenant, provider="acme", name="Ours", status=Connection.Status.CONNECTED
    )
    InboundWebhook.objects.create(
        tenant=tenant, connection=connection, body="{}", headers={}, event_type="acme.thing"
    )
    return Branch(
        tenant=tenant,
        reader=reader,
        membership=Membership.objects.get(user=reader, tenant=tenant),
        a1=a1,
        connection=connection,
    )


def test_a_branch_member_reads_the_tenants_connections_at_their_hat(
    api: Client, branch: Branch
) -> None:
    """**The 403 population SHRINKS**, one app over from `events`.

    A `member` whose one membership is at `leaf-a1` holds `("*.read",)` there and
    nothing at the tenant's root. Sight is the hat's: they see the tenant's
    connections and its receipt log — never a credential, which no `Out` carries
    (rule 38's class) — and they still cannot create, re-credential or revoke
    one, because those writes are asked at the root (the write sweep landed
    before this and is untouched here).

    *States driven:* the branch member at their own hat, through the selector and
    over the wire · the same person with `connection.read` withheld · a
    connection in another tenant (still 404 — reach before capability, the half
    this does not move) · `system`. *Not driven:* a person with two memberships.
    """
    actor = actor_for(user=branch.reader, tenant=branch.tenant, org=branch.a1)

    assert list_connections(tenant=branch.tenant, actor=actor).exists()
    assert list_inbound_webhooks(tenant=branch.tenant, actor=actor).exists()
    assert (
        get_connection(tenant=branch.tenant, connection_id=branch.connection.pk, actor=actor).pk
        == branch.connection.pk
    )

    api.force_login(branch.reader)
    hat = {"x-org": branch.a1.slug}
    listed = api.get(LIST_URL, headers=hat)
    assert listed.status_code == 200, listed.content
    assert [row["id"] for row in listed.json()["items"]] == [str(branch.connection.pk)]
    detail = api.get(f"{LIST_URL}{branch.connection.pk}/", headers=hat)
    assert detail.status_code == 200, detail.content

    withhold(branch.membership, "connection.read")
    closed = api.get(LIST_URL, headers=hat)
    assert closed.status_code == 403, closed.content
    assert closed.json()["detail"] == refusal_sentence("connection.read")
    Grant.objects.filter(membership=branch.membership).delete()

    assert list_connections(tenant=branch.tenant, actor=system_actor(branch.tenant)).exists()
