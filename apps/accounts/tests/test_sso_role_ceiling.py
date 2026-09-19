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

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import SsoConnection, SsoDomain, User
from apps.accounts.services import (
    create_sso_connection,
    disable_sso_connection,
    provision_sso_identity,
    update_sso_connection,
    verify_sso_domain,
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


def _expect(action: str) -> str:
    """The key's own sentence, from the one table that holds it."""
    from apps.accounts.policies import ACTION_PROSE

    return ACTION_PROSE[action]


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

    **The wall this meets moved one step earlier, and the sentence with it**
    (R1). It used to be the CEILING's — `_refuse_role_above_the_configurer`
    reading "no role over that part of the organization" — because `require`
    had already let the branch admin through on the strength of their hat. Now
    `sso_connection.create` is itself measured at the root, so the refusal is
    the key's own sentence and the ceiling is never reached.

    The ceiling still stands behind it and is still driven, by
    `test_a_tenant_admin_may_not_configure_a_connection_that_mints_owners`: a
    ROOT admin who holds the key and asks for more than their own role.
    """
    with pytest.raises(Forbidden) as refused:
        _create(tenant=tenant, actor=branch_admin_actor, role=Membership.Role.MEMBER)

    assert refused.value.detail == _expect("sso_connection.create")


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
    # R2-F1 (a domain claim routes nothing until it is verified): a claim provisions nobody until an
    # operator verifies
    # it — and what this test is about is the ROLE the JIT path mints, which
    # needs the path to run at all. The connection is built here rather than
    # from the swept fixture, so the sweep's one call is repeated here.
    verify_sso_domain(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        domain=DOMAIN,
    )

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


# --- the wall BEFORE the ceiling: whose connection is it? ----------------------
#
# The ceiling above answers "how high may this connection mint"; the wall below
# answers "may this person touch this connection at all", and it is the earlier
# question. A tenant's identity provider is a tenant-wide row: its claims route
# every address at its domains and its `default_role` lands a membership on the
# root. So the keys are measured AT THE ROOT, and an administrator of one branch
# — who administers that branch and nothing above it — is not an administrator
# of the tenant's identity.
#
# The review drove exactly that, over the wire, and got 200/200/200/204: a
# branch admin renamed the owner's connection, re-claimed a domain on it, turned
# `enforced` on and deleted it.


def test_a_branch_admin_may_not_touch_a_tenant_wide_connection(
    tenant: Tenant, owner_actor: Actor, branch_admin_actor: Actor
) -> None:
    """Five acts on somebody else's tenant-wide row, five refusals, five sentences.

    Each refusal is asserted against `ACTION_PROSE[key]` rather than against a
    quoted string, so the test says "the key's own sentence" and cannot come to
    mean "these words". A bare `pytest.raises(Forbidden)` would pass on the
    ceiling wall too, which is the wall this one sits in front of.
    """
    connection = _create(tenant=tenant, actor=owner_actor, role=Membership.Role.MEMBER)

    def _patch(**field: Any) -> None:  # noqa: ANN401 — the point is "whichever field"
        """One `update_sso_connection` call, whichever field it carries."""
        update_sso_connection(
            tenant=tenant, actor=branch_admin_actor, connection=connection, **field
        )

    attempts: tuple[tuple[str, Callable[[], None]], ...] = (
        ("name", lambda: _patch(name="Renamed By A Stranger")),
        ("email_domains", lambda: _patch(email_domains=["captured.example"])),
        ("enforced", lambda: _patch(enforced=True)),
    )
    for describe, attempt in attempts:
        with pytest.raises(Forbidden) as refused:
            attempt()
        assert refused.value.detail == _expect("sso_connection.update"), describe

    with pytest.raises(Forbidden) as disabling:
        disable_sso_connection(tenant=tenant, actor=branch_admin_actor, connection=connection)
    assert disabling.value.detail == _expect("sso_connection.disable")

    with pytest.raises(Forbidden) as verifying:
        verify_sso_domain(
            tenant=tenant, actor=branch_admin_actor, connection=connection, domain=DOMAIN
        )
    assert verifying.value.detail == _expect("sso_domain.verify")

    with pytest.raises(Forbidden) as creating:
        _create(
            tenant=tenant,
            actor=branch_admin_actor,
            role=Membership.Role.MEMBER,
            name="A Second Provider",
        )
    assert creating.value.detail == _expect("sso_connection.create")

    # NOTHING MOVED. A refusal that arrived after the write would leave the
    # branch admin's rename in place and the test green on the sentence alone.
    connection.refresh_from_db()
    assert connection.name == "Acme Okta"
    assert connection.email_domains == [DOMAIN]
    assert connection.enforced is False
    assert connection.status == SsoConnection.Status.ACTIVE
    assert SsoDomain.objects.get(domain=DOMAIN).verified_at is None
    assert SsoConnection.objects.count() == 1


def test_a_branch_admin_may_not_touch_a_tenant_wide_connection_on_the_wire(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor, branch_admin_actor: Actor
) -> None:
    """The same five acts through the door a person actually uses.

    The review's capture was 200/200/200/204 here — a rename, a re-claim, an
    `enforced` flip and a DELETE, all by an administrator of one leaf, on the
    tenant's identity provider. Only `default_role` was refused, because that
    one met the ceiling wall further in.

    **There is no MCP twin to check.** The SSO surface is a recorded rule-17
    exemption (`quality/rules.yaml`, "an IdP-credential surface stays behind the
    session door"), so a verifier should not look for one; the shell door
    (`manage.py verify_sso_domain`) runs as `system` and is unaffected.

    The owner and a ROOT admin are driven on their own victims in the same test,
    because a wall that refuses everybody is not a wall — it is an outage.
    """
    victim = _create(tenant=tenant, actor=owner_actor, role=Membership.Role.MEMBER)
    url = f"/api/v1/auth/sso-connections/{victim.pk}/"
    branch_admin = User.objects.get(pk=str(branch_admin_actor.user_id))

    api.force_login(branch_admin)
    for body in ({"name": "Renamed"}, {"email_domains": ["captured.example"]}, {"enforced": True}):
        response = api.patch(url, body, content_type="application/json")
        assert response.status_code == 403, body
        assert response.json()["code"] == "forbidden"
        assert response.json()["detail"] == _expect("sso_connection.update"), body
    deleted = api.delete(url)
    assert deleted.status_code == 403
    assert deleted.json()["detail"] == _expect("sso_connection.disable")
    api.logout()

    victim.refresh_from_db()
    assert victim.name == "Acme Okta"
    assert victim.status == SsoConnection.Status.ACTIVE

    # The two hats that DO hold it, each on a row of their own.
    api.force_login(owner)
    assert (
        api.patch(
            url, {"name": "Renamed By Its Owner"}, content_type="application/json"
        ).status_code
        == 200
    )
    assert api.delete(url).status_code == 204
