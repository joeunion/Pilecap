"""`current_actor`: the one actor an activity acts as, restored off the run's headers."""

from __future__ import annotations

import pytest
from temporalio.exceptions import ApplicationError

from apps.accounts.models import User
from apps.core.authz import allows
from apps.core.context import current_actor
from apps.core.headers import USER_HEADER
from apps.core.models import Membership, Organization, Tenant
from apps.core.tests import hats
from apps.workflows.context import reset_principal, set_principal

pytestmark = pytest.mark.django_db

#: The hat fixtures' home is `apps.core.tests.hats`; bound here by name so pytest finds them.
branch = hats.branch
branch_membership = hats.branch_membership
_revoke = hats.revoke
HAT_REVOKED = hats.HAT_REVOKED

#: A key a branch member does not hold and the system passes — the negative
#: that tells an `agent` actor carrying the person's permissions from a
#: `system` actor that passes everything.
TENANT_WIDE_KEY = "tenant.update"


def test_current_actor_is_the_system_wearing_the_runs_hat(
    tenant: Tenant, branch: Organization, branch_membership: Membership
) -> None:
    """The default: the work is the system's, under the hat the run started with."""
    tokens = set_principal(
        tenant_id=str(tenant.pk), user_id=str(branch_membership.user_id), org_id=str(branch.pk)
    )
    try:
        acting = current_actor()
    finally:
        reset_principal(tokens)

    assert acting.kind == "system"
    assert acting.user is None
    assert acting.tenant == tenant
    assert acting.org == branch


def test_current_actor_refuses_a_hat_whose_membership_was_revoked(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    branch_membership: Membership,
) -> None:
    """The seam asks the boundary's question: a revoked hat is refused, either kind."""
    _revoke(tenant, owner, root_org, branch_membership)
    tokens = set_principal(
        tenant_id=str(tenant.pk), user_id=str(branch_membership.user_id), org_id=str(branch.pk)
    )
    try:
        for kind in ("system", "agent"):
            with pytest.raises(ApplicationError) as refused:
                current_actor(kind=kind)
            assert refused.value.type == HAT_REVOKED
            assert refused.value.non_retryable is True
    finally:
        reset_principal(tokens)


def test_an_agent_actor_is_the_person_with_the_persons_permissions(
    tenant: Tenant, branch: Organization, branch_membership: Membership
) -> None:
    """`agent`, never `system`: what the person may not do, the run may not do for them."""
    tokens = set_principal(
        tenant_id=str(tenant.pk), user_id=str(branch_membership.user_id), org_id=str(branch.pk)
    )
    try:
        acting = current_actor(kind="agent")
        system = current_actor()
    finally:
        reset_principal(tokens)

    assert acting.kind == "agent"
    assert acting.user_id == branch_membership.user_id
    assert acting.org == branch
    assert allows(system, TENANT_WIDE_KEY), "the negative below needs a key the system holds"
    assert not allows(acting, TENANT_WIDE_KEY)


def test_an_agent_actor_needs_a_person_on_the_headers(tenant: Tenant, branch: Organization) -> None:
    """A run with no acting user has nobody to act as: refused, never written as nobody."""
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=None, org_id=str(branch.pk))
    try:
        with pytest.raises(RuntimeError, match=USER_HEADER):
            current_actor(kind="agent")
    finally:
        reset_principal(tokens)
