"""A branch hat and the one member who holds it, for the tests that revoke a run's hat."""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, revoke_membership

MEMBER_PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret

#: The refusal's `type`, spelled rather than imported: a rename is a break this pins.
HAT_REVOKED = "HatRevoked"


@pytest.fixture
def branch(tenant: Tenant, owner: User, root_org: Organization) -> Organization:
    """One branch under the root: the hat the run is started under."""
    return create_organization(
        tenant=tenant,
        parent=root_org,
        name="Branch",
        slug="branch",
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )


@pytest.fixture
def branch_membership(tenant: Tenant, branch: Organization) -> Membership:
    """Somebody whose ONLY role in the tenant is on the branch.

    Not `owner`: the root covers the branch, so revoking an owner's branch row leaves the hat.
    """
    user = create_user(email="branch-member@example.com", password=MEMBER_PASSWORD)
    return add_membership(
        user=user,
        tenant=tenant,
        organization=branch,
        role=Membership.Role.MEMBER,
        is_default=True,
        actor=system_actor(tenant=tenant),
    )


def revoke(tenant: Tenant, owner: User, root_org: Organization, membership: Membership) -> None:
    revoke_membership(
        tenant=tenant,
        membership=membership,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
