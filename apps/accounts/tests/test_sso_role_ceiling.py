"""A connection may not mint a role its configurer could not have granted.

`SsoConnection.default_role` is a
standing instruction to `add_membership`, executed later, by the system, with no
granter to measure — so the ceiling has to be applied at the moment a *person*
writes the row. Before this fix any privileged actor could set
`default_role="owner"`, and the next sign-in from a claimed domain minted an
owner the configuring admin could never have granted directly.

The wall is `core.services._refuse_escalation` — the same two refusals
`add_membership` and `set_role` use, measured at the tenant's **root**, because
that is where a connection's grants land (`ensure_membership` takes no
organization, so a JIT membership sits on the root).
"""

from __future__ import annotations

import pytest

from apps.accounts.models import SsoConnection
from apps.accounts.services import (
    create_sso_connection,
    provision_sso_identity,
    update_sso_connection,
)
from apps.accounts.tests.conftest import CLIENT_ID, CLIENT_SECRET, ISSUER
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Forbidden
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization

pytestmark = pytest.mark.django_db

DOMAIN = "acme.com"


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
    """An admin of one branch and of nothing above it.

    The reviewer's actor: privileged enough for `sso_connection.create`
    (`is_privileged` reads the acting membership's role), and holding no role at
    all at the root where the connection's grants would land.
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


def _create(*, tenant: Tenant, actor: Actor, role: str, name: str = "Acme Okta") -> SsoConnection:
    return create_sso_connection(
        tenant=tenant,
        actor=actor,
        name=name,
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=[DOMAIN],
        default_role=role,
    )


# --- create ------------------------------------------------------------------


def test_a_tenant_admin_may_not_configure_a_connection_that_mints_owners(
    tenant: Tenant, admin_actor: Actor
) -> None:
    """The reviewer's probe, as a refusal.

    An admin at the root may grant `admin` and `member` by hand; a connection is
    a grant with a delay, so it may say no more than they could.
    """
    with pytest.raises(Forbidden) as refused:
        _create(tenant=tenant, actor=admin_actor, role=Membership.Role.OWNER)

    assert "nobody grants above themselves" in str(refused.value.detail)
    assert not SsoConnection.objects.for_tenant(tenant).exists()


def test_the_refusal_carries_the_standard_remedies_envelope(
    tenant: Tenant, admin_actor: Actor
) -> None:
    """The registry's envelope, not a bespoke one — `forbidden`'s own remedies."""
    from apps.core.exceptions import wire_refusal

    with pytest.raises(Forbidden) as refused:
        _create(tenant=tenant, actor=admin_actor, role=Membership.Role.OWNER)

    body = wire_refusal(refused.value)
    assert body["code"] == "forbidden"
    assert body["remedies"], body


def test_an_owner_may_still_configure_a_connection_that_mints_owners(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The ceiling is the granter's own role, not a ban on the word."""
    connection = _create(tenant=tenant, actor=owner_actor, role=Membership.Role.OWNER)

    assert connection.default_role == Membership.Role.OWNER


def test_an_admin_may_still_configure_a_connection_at_their_own_ceiling(
    tenant: Tenant, admin_actor: Actor
) -> None:
    connection = _create(tenant=tenant, actor=admin_actor, role=Membership.Role.ADMIN)

    assert connection.default_role == Membership.Role.ADMIN


def test_a_branch_admin_is_measured_at_the_root_where_the_grants_land(
    tenant: Tenant, branch_admin_actor: Actor
) -> None:
    """Holding `admin` of one branch says nothing about the tenant's root.

    `ensure_membership` places a JIT membership on the root, so the root is
    where the ceiling is read — and a branch admin holds no role there at all.
    """
    with pytest.raises(Forbidden) as refused:
        _create(tenant=tenant, actor=branch_admin_actor, role=Membership.Role.MEMBER)

    assert "no role over that part of the organization" in str(refused.value.detail)


# --- update ------------------------------------------------------------------


def test_an_admin_may_not_raise_an_existing_connection_to_owner(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor
) -> None:
    """The same wall on the patch door: a promotion is a grant with an extra step."""
    connection = _create(tenant=tenant, actor=owner_actor, role=Membership.Role.MEMBER)

    with pytest.raises(Forbidden):
        update_sso_connection(
            tenant=tenant,
            actor=admin_actor,
            connection=connection,
            default_role=Membership.Role.OWNER,
        )

    connection.refresh_from_db()
    assert connection.default_role == Membership.Role.MEMBER


def test_an_admin_may_still_change_everything_else_about_a_connection(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor
) -> None:
    """The guard runs only when a role is actually being named."""
    connection = _create(tenant=tenant, actor=owner_actor, role=Membership.Role.MEMBER)

    updated = update_sso_connection(
        tenant=tenant, actor=admin_actor, connection=connection, name="Renamed"
    )

    assert updated.name == "Renamed"
    assert updated.default_role == Membership.Role.MEMBER


# --- and the JIT path that consumes it ---------------------------------------


def test_a_fresh_domain_sign_in_cannot_land_above_the_configurers_ceiling(
    tenant: Tenant, admin_actor: Actor, owner_actor: Actor
) -> None:
    """The reviewer's scenario end to end: configure, sign in, read the role.

    The admin's attempt to write `owner` is refused, so the row that exists says
    `member`, so the membership the JIT path mints says `member`. The wall holds
    at the only place a person acts.
    """
    with pytest.raises(Forbidden):
        _create(tenant=tenant, actor=admin_actor, role=Membership.Role.OWNER)
    connection = _create(tenant=tenant, actor=owner_actor, role=Membership.Role.MEMBER)

    identity = provision_sso_identity(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        subject="okta|newcomer",
        email=f"newcomer@{DOMAIN}",
        email_verified=True,
    )

    membership = Membership.objects.get(user_id=identity.user.pk, tenant=tenant)
    assert membership.role == Membership.Role.MEMBER
    assert not Membership.objects.filter(
        user_id=identity.user.pk, tenant=tenant, role=Membership.Role.OWNER
    ).exists()


def test_the_refused_configuration_is_audited(tenant: Tenant, admin_actor: Actor) -> None:
    """A refused escalation is a fact somebody wants six months from now."""
    with pytest.raises(Forbidden):
        _create(tenant=tenant, actor=admin_actor, role=Membership.Role.OWNER)

    entry = AuditEntry.objects.for_tenant(tenant).get(action="accounts.create_sso_connection")
    assert entry.outcome == AuditEntry.Outcome.ERROR
    assert entry.error_code == "forbidden"
