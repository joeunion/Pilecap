"""How far an erasure reaches, and who may perform one.

`erase_user` used to authorize through the
*role fallback*: no `policies.py` entry named `accounts.user.erase`, so
`core.authz.allows` fell through to "is this actor's membership privileged",
which is true of an `admin` of one branch of a large tenant. Its own guard was
then a tenant-level belongs-check — the target holds *any* membership in the
acting tenant — so a branch admin could erase a person who belonged only to the
branch next door: anonymise their address, drop their staff flags, revoke every
token, and ask Zitadel to deactivate their platform account.

**The narrowing picked, and why.** Of the two shapes the criterion offered —
subtree-of-the-acting-hat, or admin-at-the-tenant-root — the fix takes the
root. An erasure is not an org-scoped act: it destroys a person's identity
across *every* tenant they belong to and revokes the deployment's own
credential for them. There is no branch of one tenant that owns that. Reading
the ceiling at the root also fails closed where the hat shape would fall open —
an actor with `org=None` (a management command, a service-to-service call) would
have had no subtree to be inside, and "no hat" must not mean "everywhere".
"""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user, erase_user
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Forbidden
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization

pytestmark = pytest.mark.django_db


class Branches:
    """root → left, root → right. Two branches that cannot see each other."""

    def __init__(self, tenant: Tenant, owner_actor: Actor) -> None:
        self.root = root_organization(tenant=tenant)
        self.left = create_organization(
            tenant=tenant, parent=self.root, name="Left", slug="left", actor=owner_actor
        )
        self.right = create_organization(
            tenant=tenant, parent=self.root, name="Right", slug="right", actor=owner_actor
        )


@pytest.fixture
def branches(tenant: Tenant, owner_actor: Actor) -> Branches:
    return Branches(tenant, owner_actor)


def _person_at(
    *, email: str, tenant: Tenant, organization: Organization, role: str, actor: Actor
) -> User:
    user = create_user(email=email, password=None)
    add_membership(
        user=user,
        tenant=tenant,
        organization=organization,
        is_default=True,
        role=role,
        actor=actor,
    )
    return user


# --- the predicate, on its own -----------------------------------------------


def test_the_predicate_is_admin_or_better_at_the_root(
    tenant: Tenant, branches: Branches, owner: User, owner_actor: Actor
) -> None:
    from apps.accounts.policies import administers_the_whole_tenant

    branch_admin = _person_at(
        email="left-admin@example.com",
        tenant=tenant,
        organization=branches.left,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )

    assert administers_the_whole_tenant(owner_actor) is True
    assert (
        administers_the_whole_tenant(actor_for(user=branch_admin, tenant=tenant, org=branches.left))
        is False
    )


def test_the_predicate_fails_closed_with_no_tenant_and_no_membership(
    nomad: User, root: User, tenant: Tenant
) -> None:
    """No tenant is no; a superuser with no membership is also no."""
    from apps.accounts.policies import administers_the_whole_tenant

    assert administers_the_whole_tenant(actor_for(user=nomad, tenant=None)) is False
    assert administers_the_whole_tenant(actor_for(user=root, tenant=tenant)) is False


# --- and through the service --------------------------------------------------


def test_a_branch_admin_may_not_erase_somebody_in_the_branch_next_door(
    tenant: Tenant, branches: Branches, owner: User, owner_actor: Actor
) -> None:
    """The reviewer's reach: privileged, and privileged nowhere near this person."""
    left_admin = _person_at(
        email="left-admin@example.com",
        tenant=tenant,
        organization=branches.left,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )
    right_member = _person_at(
        email="right-member@example.com",
        tenant=tenant,
        organization=branches.right,
        role=Membership.Role.MEMBER,
        actor=owner_actor,
    )
    acting = actor_for(user=left_admin, tenant=tenant, org=branches.left)

    with pytest.raises(Forbidden):
        erase_user(user=right_member, actor=acting, tenant=tenant)

    right_member.refresh_from_db()
    assert right_member.email == "right-member@example.com"
    assert right_member.is_active is True


def test_a_branch_admin_may_not_erase_somebody_in_their_own_branch_either(
    tenant: Tenant, branches: Branches, owner: User, owner_actor: Actor
) -> None:
    """The narrowing is the root, not the subtree — said out loud so it cannot drift.

    An erasure reaches further than any one branch: it takes the person's
    platform credential with it. A branch admin who wants one asks somebody who
    administers the whole tenant.
    """
    left_admin = _person_at(
        email="left-admin@example.com",
        tenant=tenant,
        organization=branches.left,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )
    colleague = _person_at(
        email="left-member@example.com",
        tenant=tenant,
        organization=branches.left,
        role=Membership.Role.MEMBER,
        actor=owner_actor,
    )
    acting = actor_for(user=left_admin, tenant=tenant, org=branches.left)

    with pytest.raises(Forbidden):
        erase_user(user=colleague, actor=acting, tenant=tenant)

    colleague.refresh_from_db()
    assert colleague.email == "left-member@example.com"


def test_an_admin_at_the_root_may_erase_anybody_in_the_tenant(
    tenant: Tenant, branches: Branches, owner: User, owner_actor: Actor, admin_member: User
) -> None:
    """The other side of the line, so the refusals above are not vacuous."""
    right_member = _person_at(
        email="right-member@example.com",
        tenant=tenant,
        organization=branches.right,
        role=Membership.Role.MEMBER,
        actor=owner_actor,
    )
    acting = actor_for(user=admin_member, tenant=tenant, org=branches.root)

    erased = erase_user(user=right_member, actor=acting, tenant=tenant)

    assert erased.email.endswith("@erased.invalid")
    assert erased.is_active is False


def test_the_policy_is_the_one_that_answers_and_not_the_role_fallback(
    tenant: Tenant, branches: Branches, owner: User, owner_actor: Actor
) -> None:
    """The regression this closes, named.

    `core.authz.allows` falls back to `membership.is_privileged` when no policy
    covers the action, and a branch admin's membership *is* privileged. The
    registered predicate is what makes that fallback unreachable here.
    """
    from apps.core.authz import policies

    assert "accounts.user.erase" in policies()
