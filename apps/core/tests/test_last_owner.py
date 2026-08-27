"""A tenant is never left with nobody who can administer it.

`revoke_membership` has refused removing a tenant's last `owner`: a tenant with
no owner is a tenant nobody can invite into, promote in,
or close. **`set_role` did not**, and a demotion reaches exactly the same state
by the other road — the last owner is set to `member`, the door answers `200`,
and nothing anywhere notices until somebody needs to do one of those three
things. Wire-proven and re-driven here as the repro.

The tests assert **one predicate and one sentence**, not merely "both roads
refuse": two guards written separately drift, and a client that branches on the
words gets a different answer depending on which road it took. So the two
refusals are string-compared against each other, and the machine door's message
is string-compared against the human door's body — the same shape
`test_mcp_tenancy.py` uses for the escalation wall.

**This is a floor, not a ceiling.** The escalation wall (`_refuse_escalation`,
house rules 24/29) decides *who may grant what*; this decides that the tenant
keeps somebody who can. They are tested apart because they fail apart, and the
wall's own answers are asserted here to be unchanged.
"""

from __future__ import annotations

import pytest
from django.test import Client
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.exceptions import Conflict, Forbidden, Invalid, refusal_message
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership, revoke_membership, set_role
from apps.core.tests.test_mcp_tenancy import context_for, tool

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The one sentence, written here so a reword has to pass through a test that
#: says what the words are for. Both roads to ownerlessness speak it.
LAST_OWNER = "That is the tenant's last owner; promote somebody else before removing them."


def membership_of(user: User, tenant: Tenant) -> Membership:
    return Membership.objects.get(tenant=tenant, user_id=user.pk)


def role_url(membership: Membership) -> str:
    return f"/api/v1/memberships/{membership.pk}/role/"


# --- the hole, red first ------------------------------------------------------


def test_the_last_owner_cannot_be_demoted(tenant: Tenant, owner: User, owner_actor: Actor) -> None:
    """The repro. Before the guard this returned a `member` membership.

    The `owner` fixture is the tenant's only owner, which is the whole
    condition: one row stands between this tenant and nobody being able to
    administer it, and `set_role` used to move it.
    """
    membership = membership_of(owner, tenant)

    with pytest.raises(Conflict) as refused:
        set_role(
            tenant=tenant,
            membership=membership,
            role=Membership.Role.MEMBER,
            actor=owner_actor,
        )

    assert str(refused.value) == LAST_OWNER
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


def test_both_roads_to_ownerlessness_speak_with_one_voice(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """One predicate, one sentence — asserted by comparing the two, not by hope.

    A client that branched on the words would otherwise learn one answer for a
    revocation and another for a demotion of the same row, for the same reason.
    """
    membership = membership_of(owner, tenant)

    with pytest.raises(Conflict) as demoted:
        set_role(
            tenant=tenant,
            membership=membership,
            role=Membership.Role.MEMBER,
            actor=owner_actor,
        )
    with pytest.raises(Conflict) as revoked:
        revoke_membership(tenant=tenant, membership=membership, actor=owner_actor)

    assert str(demoted.value) == str(revoked.value)
    assert demoted.value.code == revoked.value.code == "conflict"


# --- the doors ----------------------------------------------------------------


def test_the_wire_refuses_the_demotion_as_ft_1_would_drive_it(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The refusal flows out of the service through the one mapper (rule 14).

    Driven the way a caller drives it: log in, PATCH the role, read the body.
    Nothing in `apps/core/api/routes.py` catches this refusal — `config/api.py`
    maps it, which is why the code, the sentence and the remedies arrive without
    the route knowing the guard exists.
    """
    membership = membership_of(owner, tenant)
    api.force_login(owner)

    response = api.patch(
        role_url(membership),
        data={"role": Membership.Role.MEMBER},
        content_type=JSON,
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["detail"] == LAST_OWNER
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


def test_the_machine_door_refuses_it_with_the_same_words(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Rule 17, the strict form: the MCP message IS the REST body, rendered.

    Not "both refuse" — string-compared, so a second refusal grammar cannot grow
    on the machine door for this guard without this failing.
    """
    membership = membership_of(owner, tenant)
    api.force_login(owner)
    rest = api.patch(
        role_url(membership),
        data={"role": Membership.Role.MEMBER},
        content_type=JSON,
    )
    assert rest.status_code == 409

    with pytest.raises(ToolError) as refused:
        tool("update_membership")(
            context_for(owner, tenant),
            membership_id=membership.pk,
            # A plain string, because that is what the transport delivers.
            role=Membership.Role.MEMBER.value,
        )

    assert str(refused.value) == refusal_message(rest.json())
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


# --- what the guard must not touch --------------------------------------------


def test_an_owner_who_is_not_the_last_may_still_be_demoted(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    """The guard is about the *last* owner, not about owners."""
    second = set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role=Membership.Role.OWNER,
        actor=owner_actor,
    )
    assert second.role == Membership.Role.OWNER

    demoted = set_role(
        tenant=tenant,
        membership=membership_of(owner, tenant),
        role=Membership.Role.MEMBER,
        actor=owner_actor,
    )

    assert demoted.role == Membership.Role.MEMBER
    assert Membership.objects.filter(tenant=tenant, role=Membership.Role.OWNER).count() == 1


def test_a_promotion_is_untouched(
    tenant: Tenant, member: User, admin_member: User, owner_actor: Actor
) -> None:
    """Upwards is not a road to ownerlessness and the guard never looks at it."""
    promoted = set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )
    assert promoted.role == Membership.Role.ADMIN

    to_owner = set_role(
        tenant=tenant,
        membership=membership_of(admin_member, tenant),
        role=Membership.Role.OWNER,
        actor=owner_actor,
    )
    assert to_owner.role == Membership.Role.OWNER


def test_setting_the_last_owner_to_owner_again_is_not_a_demotion(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """A lateral move leaves the tenant with exactly the owner it started with."""
    unchanged = set_role(
        tenant=tenant,
        membership=membership_of(owner, tenant),
        role=Membership.Role.OWNER,
        actor=owner_actor,
    )

    assert unchanged.role == Membership.Role.OWNER


def test_a_demotion_in_another_tenant_is_not_this_tenants_business(
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    stranger: User,
    stranger_actor: Actor,
    nomad: User,
) -> None:
    """The predicate counts owners **per tenant**, not across the table.

    Without the `tenant=` filter this tenant's owner would keep another
    tenant's owner alive, and vice versa — the sibling test tenancy owes every
    read, on a guard whose whole job is a count.
    """
    add_membership(
        user=nomad,
        tenant=other_tenant,
        role=Membership.Role.OWNER,
        actor=stranger_actor,
    )

    demoted = set_role(
        tenant=other_tenant,
        membership=membership_of(stranger, other_tenant),
        role=Membership.Role.MEMBER,
        actor=stranger_actor,
    )

    assert demoted.role == Membership.Role.MEMBER
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


# --- the wall still answers first ---------------------------------------------


def test_the_escalation_wall_is_unchanged(tenant: Tenant, member: User, admin_actor: Actor) -> None:
    """A floor, not a ceiling: nobody grants above themselves, still."""
    with pytest.raises(Forbidden):
        set_role(
            tenant=tenant,
            membership=membership_of(member, tenant),
            role=Membership.Role.OWNER,
            actor=admin_actor,
        )


def test_a_role_this_product_does_not_know_is_still_invalid(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Ordering. The last owner sent a nonsense role hears `invalid`, not `conflict`.

    `MembershipRolePatch.role` is a plain `str`, so a value the product does not
    know reaches the service. Answering `conflict` first would teach a caller
    that its typo was a state problem — and the route's own contract promises
    `400 invalid` for exactly this.
    """
    with pytest.raises(Invalid):
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            role="regional-manager",
            actor=owner_actor,
        )
