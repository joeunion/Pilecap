"""Customer SSO: configuration, just-in-time provisioning, and what it refuses.

The properties this module pins, in the order they matter:

* a client secret is **ciphertext in the column**, not merely absent from the
  API — proved by reading the raw column with SQL that the ORM never sees;
* an email domain routes to **exactly one** identity provider, across every
  tenant, enforced by the database and not by a scan;
* a first assertion creates a user, an identity and a membership at the
  connection's `default_role`, **audited**, and a second one creates nothing;
* the same IdP subject through two connections is **two identities**, and
  neither tenant's memberships are visible from the other;
* `enforced` takes password login away from the domains it claims;
* only an owner or an admin may configure any of it.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.db import connection as db_connection

from apps.accounts.models import SsoConnection, SsoDomain, SsoIdentity
from apps.accounts.selectors import get_enforcing_connection_for
from apps.accounts.services import (
    SsoRefused,
    create_sso_connection,
    disable_sso_connection,
    provision_sso_identity,
    update_sso_connection,
)
from apps.accounts.tests.conftest import CLIENT_SECRET, provider_landed
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, Invalid
from apps.core.models import Membership, Tenant

pytestmark = pytest.mark.django_db


# --- Encryption at rest ------------------------------------------------------


def test_the_client_secret_is_ciphertext_in_the_column(sso_connection: SsoConnection) -> None:
    """Read the raw column with SQL. The ORM would decrypt it and prove nothing.

    This is the test that would catch the field being swapped for a plain
    `JSONField` in a hurry: every assertion made through Python would still
    pass, and this one would not.
    """
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT metadata FROM accounts_ssoconnection WHERE id = %s",
            [str(sso_connection.pk)],
        )
        row = cursor.fetchone()

    stored = row[0]
    assert CLIENT_SECRET not in stored
    assert "acme-client-id" not in stored
    # And it is genuinely the same value, not merely a different one.
    assert (
        SsoConnection.objects.for_tenant(sso_connection.tenant)
        .get(pk=sso_connection.pk)
        .client_secret
        == CLIENT_SECRET
    )


def test_no_door_returns_the_client_secret(sso_connection: SsoConnection) -> None:
    """`SsoConnectionOut` has no field for it, so no door can leak it by accident."""
    from apps.accounts.schemas import SsoConnectionOut

    assert "client_secret" not in SsoConnectionOut.model_fields
    body = SsoConnectionOut.from_orm(sso_connection).model_dump(mode="json")
    assert CLIENT_SECRET not in str(body)
    assert body["has_client_secret"] is True


# --- Domains route to exactly one provider -----------------------------------


def test_a_domain_belongs_to_one_connection_across_every_tenant(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor, stranger_actor: Actor
) -> None:
    """The whole reason `SsoDomain` is a row and not an element of a JSON list."""
    create_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        name="Acme",
        issuer="https://a.example",
        client_id="a",
        client_secret="a",  # noqa: S106 — a fake IdP client secret the test world configures
        email_domains=["shared.example"],
    )
    with pytest.raises(Conflict):
        create_sso_connection(
            tenant=other_tenant,
            actor=stranger_actor,
            name="Globex",
            issuer="https://b.example",
            client_id="b",
            client_secret="b",  # noqa: S106 — a fake IdP client secret the test world configures
            email_domains=["shared.example"],
        )


def test_the_database_refuses_it_too_not_only_the_service(
    sso_connection: SsoConnection, other_tenant: Tenant
) -> None:
    """The service's `Conflict` is the polite version; this is the one that holds.

    Two transactions racing past the service's check meet the unique constraint,
    which is the only thing that can be true of both of them at once.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        SsoDomain.objects.create(
            tenant=other_tenant,
            connection=sso_connection,
            domain="acme.com",
        )


def test_a_domain_that_is_not_one_is_refused(tenant: Tenant, owner_actor: Actor) -> None:
    with pytest.raises(Invalid):
        create_sso_connection(
            tenant=tenant,
            actor=owner_actor,
            name="Typo",
            issuer="https://a.example",
            client_id="a",
            client_secret="a",  # noqa: S106 — a fake IdP client secret the test world configures
            email_domains=["someone@acme.com"],
        )


def test_updating_the_domains_replaces_the_set(sso_connection: SsoConnection) -> None:

    actor = actor_for(user=None, tenant=sso_connection.tenant, kind="system")
    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=actor,
        connection=sso_connection,
        email_domains=["acme.com", "acme.co.uk"],
    )
    assert sso_connection.email_domains == ["acme.co.uk", "acme.com"]

    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=actor,
        connection=sso_connection,
        email_domains=["acme.co.uk"],
    )
    assert sso_connection.email_domains == ["acme.co.uk"]
    # The released domain is genuinely free again.
    assert SsoDomain.objects.claim("acme.com") is None


def test_saml_is_refused_with_the_reason(tenant: Tenant, owner_actor: Actor) -> None:
    """A customer who asks for SAML gets a sentence, not a connection that never works."""
    with pytest.raises(Invalid) as raised:
        create_sso_connection(
            tenant=tenant,
            actor=owner_actor,
            name="Acme SAML",
            issuer="https://a.example",
            client_id="a",
            client_secret="a",  # noqa: S106 — a fake IdP client secret the test world configures
            email_domains=["acme.com"],
            protocol=SsoConnection.Protocol.SAML,
        )
    assert "SAML" in raised.value.detail


# --- Just-in-time provisioning -----------------------------------------------


def test_the_first_assertion_creates_user_identity_and_membership(
    sso_connection: SsoConnection,
) -> None:
    """One assertion in; a person who can sign in, at the connection's role, out."""
    identity = provision_sso_identity(
        tenant=sso_connection.tenant,
        actor=system_actor(sso_connection.tenant),
        connection=sso_connection,
        subject="idp-subject-1",
        email="newcomer@acme.com",
        email_verified=True,
    )

    assert identity.user.email == "newcomer@acme.com"
    assert identity.subject == "idp-subject-1"
    assert not identity.user.has_usable_password()

    membership = Membership.objects.get(user_id=identity.user.pk, tenant=sso_connection.tenant)
    assert membership.role == Membership.Role.MEMBER
    assert membership.is_default is True


def test_the_first_login_is_audited_as_the_system(sso_connection: SsoConnection) -> None:
    """`@service` writes the row; this pins that it says *system*, not a person.

    Attributing the creation of an account to the account it just created — or
    to whoever last touched the connection — would make the audit trail fiction.
    """
    provision_sso_identity(
        tenant=sso_connection.tenant,
        actor=system_actor(sso_connection.tenant),
        connection=sso_connection,
        subject="idp-subject-1",
        email="newcomer@acme.com",
        email_verified=True,
    )

    entry = AuditEntry.objects.for_tenant(sso_connection.tenant).get(
        action="accounts.provision_sso_identity"
    )
    assert entry.actor_kind == "system"
    assert entry.actor_user_id is None
    assert entry.outcome == "ok"
    assert entry.object_type == "accounts.SsoIdentity"


def test_the_second_login_reuses_the_identity(sso_connection: SsoConnection) -> None:
    """Idempotent: an IdP that asserts the same person twice is the normal case."""
    first = provision_sso_identity(
        tenant=sso_connection.tenant,
        actor=system_actor(sso_connection.tenant),
        connection=sso_connection,
        subject="idp-subject-1",
        email="newcomer@acme.com",
        email_verified=True,
    )
    second = provision_sso_identity(
        tenant=sso_connection.tenant,
        actor=system_actor(sso_connection.tenant),
        connection=sso_connection,
        subject="idp-subject-1",
        email="newcomer@acme.com",
        email_verified=True,
    )

    assert second.pk == first.pk
    assert SsoIdentity.objects.for_tenant(sso_connection.tenant).count() == 1
    assert Membership.objects.filter(user_id=first.user.pk).count() == 1


def test_an_existing_member_is_linked_rather_than_duplicated(
    sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """Somebody who had a password before the connection existed keeps their account.

    And keeps their **role**: the connection's `default_role` is a statement
    about new people, so an owner does not get demoted by signing in.
    """
    from apps.accounts.services import create_user
    from apps.core.services import add_membership

    existing = create_user(email="veteran@acme.com", password="a-long-enough-password")  # noqa: S106 — a throwaway password a test user is made with
    add_membership(
        user=existing,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )

    identity = provision_sso_identity(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=sso_connection,
        subject="idp-subject-veteran",
        email="veteran@acme.com",
        email_verified=True,
    )

    assert identity.user.pk == existing.pk
    assert Membership.objects.get(user_id=existing.pk, tenant=tenant).role == Membership.Role.ADMIN


def test_an_unverified_address_is_refused(sso_connection: SsoConnection) -> None:
    """The whole of verified-email trust, in one assertion.

    Without this, "the IdP says this is alice@acme.com" would be enough to be
    handed alice's account — and an IdP that has not verified the address is
    repeating whatever somebody typed into a profile field.
    """
    with pytest.raises(SsoRefused):
        provision_sso_identity(
            tenant=sso_connection.tenant,
            actor=system_actor(sso_connection.tenant),
            connection=sso_connection,
            subject="idp-subject-1",
            email="newcomer@acme.com",
            email_verified=False,
        )
    assert SsoIdentity.objects.for_tenant(sso_connection.tenant).count() == 0


def test_an_address_outside_the_claimed_domains_is_refused(
    sso_connection: SsoConnection,
) -> None:
    """A tenant's IdP may not mint identities for a domain it does not own."""
    with pytest.raises(SsoRefused):
        provision_sso_identity(
            tenant=sso_connection.tenant,
            actor=system_actor(sso_connection.tenant),
            connection=sso_connection,
            subject="idp-subject-1",
            email="someone@not-acme.example",
            email_verified=True,
        )


def test_a_refusal_is_audited_too(sso_connection: SsoConnection) -> None:
    """The refusal survives its own rollback — `@service` writes it outside."""
    with pytest.raises(SsoRefused):
        provision_sso_identity(
            tenant=sso_connection.tenant,
            actor=system_actor(sso_connection.tenant),
            connection=sso_connection,
            subject="idp-subject-1",
            email="newcomer@acme.com",
            email_verified=False,
        )
    entry = AuditEntry.objects.for_tenant(sso_connection.tenant).get(
        action="accounts.provision_sso_identity"
    )
    assert entry.outcome == "error"


# --- The cross-tenant collision ----------------------------------------------


def test_one_idp_subject_through_two_connections_is_two_isolated_identities(
    sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """The property that makes `(connection, subject)` the key rather than `subject`.

    Two identity providers are two namespaces. `user-42` at Acme's Okta and
    `user-42` at Globex's Entra are different human beings, and the only reason
    they do not collide is that the uniqueness is per connection.
    """
    subject = "user-42"

    acme = provision_sso_identity(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=sso_connection,
        subject=subject,
        email="person@acme.com",
        email_verified=True,
    )
    globex = provision_sso_identity(
        tenant=other_tenant,
        actor=system_actor(other_tenant),
        connection=other_sso_connection,
        subject=subject,
        email="person@globex.com",
        email_verified=True,
    )

    assert acme.pk != globex.pk
    assert acme.user.pk != globex.user.pk

    # Each identity is visible only inside its own tenant.
    assert list(SsoIdentity.objects.for_tenant(tenant)) == [acme]
    assert list(SsoIdentity.objects.for_tenant(other_tenant)) == [globex]

    # And neither person is a member of the other's workspace.
    assert not Membership.objects.filter(user_id=acme.user.pk, tenant=other_tenant).exists()
    assert not Membership.objects.filter(user_id=globex.user.pk, tenant=tenant).exists()


def test_the_same_subject_lookup_does_not_cross_connections(
    sso_connection: SsoConnection, other_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """`for_subject` narrows by connection, so a hit in one is a miss in the other."""
    provision_sso_identity(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=sso_connection,
        subject="user-42",
        email="person@acme.com",
        email_verified=True,
    )
    assert (
        SsoIdentity.objects.for_subject(connection=other_sso_connection, subject="user-42") is None
    )


# --- `enforced` --------------------------------------------------------------


def test_enforced_takes_password_login_away_from_the_claimed_domains(
    sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    assert get_enforcing_connection_for("anyone@acme.com") is None

    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=owner_actor,
        connection=provider_landed(sso_connection),
        enforced=True,
    )

    assert get_enforcing_connection_for("anyone@acme.com") == sso_connection
    assert get_enforcing_connection_for("ANYONE@ACME.COM") == sso_connection
    assert get_enforcing_connection_for("anyone@elsewhere.example") is None


def test_disabling_a_connection_gives_the_password_back(
    sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    """A disabled connection must not lock its people out of the product.

    `enforced` is a promise that SSO is the way in. The moment SSO is no longer
    a way in at all, keeping the promise means locking a whole customer out —
    which is why disabling releases it, and why the row is kept rather than
    deleted.
    """
    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=owner_actor,
        connection=provider_landed(sso_connection),
        enforced=True,
    )
    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )

    assert get_enforcing_connection_for("anyone@acme.com") is None
    # The row and its claim survive, so nobody else can take the domain.
    assert SsoDomain.objects.claim("acme.com") is not None


# --- Authorization -----------------------------------------------------------


def test_a_member_may_not_configure_the_identity_provider(
    tenant: Tenant, member_actor: Actor
) -> None:
    """The strictest policy in the repository, and the reason is in `policies.py`.

    A member who could edit a connection could point the tenant's login at an
    identity provider they control, and walk back in as an owner.
    """
    with pytest.raises(Forbidden):
        create_sso_connection(
            tenant=tenant,
            actor=member_actor,
            name="Rogue",
            issuer="https://rogue.example",
            client_id="r",
            client_secret="r",  # noqa: S106 — a fake IdP client secret the test world configures
            email_domains=["rogue.example"],
        )


def test_a_member_may_not_change_or_disable_one(
    sso_connection: SsoConnection, member_actor: Actor
) -> None:
    with pytest.raises(Forbidden):
        update_sso_connection(
            tenant=sso_connection.tenant,
            actor=member_actor,
            connection=sso_connection,
            enforced=True,
        )
    with pytest.raises(Forbidden):
        disable_sso_connection(
            tenant=sso_connection.tenant, actor=member_actor, connection=sso_connection
        )


def test_an_admin_may(sso_connection: SsoConnection, admin_actor: Actor) -> None:
    """The other half: `Forbidden` for everyone would be a passing test and a broken product."""
    updated = update_sso_connection(
        tenant=sso_connection.tenant,
        actor=admin_actor,
        connection=provider_landed(sso_connection),
        enforced=True,
    )
    assert updated.enforced is True
