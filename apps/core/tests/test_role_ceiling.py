"""Nobody acts above themselves — and a demotion is acting on somebody.

`revoke_membership` has always had the ceiling: an `admin` may
remove an `admin` or a `member`, never an `owner`, because an admin who may not
*grant* `owner` could otherwise take the owner's hat away instead — the same
power arriving by subtraction. **`set_role` did not.** `_refuse_escalation`
bounds only the role being *granted*, so an `admin` calling
`set_role(role="member")` on an `owner` membership answered `200`: the power to
strip arrived by subtraction where the power to grant is walled, on the road
that does not even need the owner's row to disappear. This gap was found on
the tree and is re-driven here as the repro.

The tests assert **one predicate and one sentence shape**, not merely "both
roads refuse": the demotion refusal is string-compared against the revocation's
with the verb substituted, so the two cannot drift into two different grammars
for one rule. That is `test_last_owner.py`'s shape, one floor up.

**Three walls stand on this road and only one may ever speak** — the escalation
wall (the role being *granted*), this ceiling (the role being *held*), then the
ownerless floor (`test_last_owner.py`). The order is asserted here by planting
cases where two of them would refuse, because an order that holds by accident
is an order a later edit reverses without anything going red:

* the escalation wall speaks first, and that is what lets this ceiling assume
  the actor holds *some* role there — its sentence quotes that role, and with
  the walls the other way round it would quote `None` at somebody;
* this ceiling speaks before the ownerless floor, because telling an admin
  "that is the tenant's last owner" answers a question about the tenant's owner
  census for somebody who may not touch that row at all.
"""

from __future__ import annotations

import pytest
from django.test import Client
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Conflict, Forbidden, refusal_message
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import revoke_membership, set_role
from apps.core.tests.test_last_owner import LAST_OWNER, membership_of, role_url
from apps.core.tests.test_mcp_tenancy import context_for, tool

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The sentence, written out so a reword passes through a test that says what
#: the words are for. It is `revoke_membership`'s own with one verb changed —
#: which is asserted below rather than trusted.
CEILING = (
    "You may not demote a 'owner': your own effective role there is 'admin', "
    "and nobody demotes above themselves."
)

#: What the escalation wall says to somebody who holds nothing there. Quoted
#: here because the ordering test's whole point is that this is the answer, not
#: a ceiling sentence with `None` in it.
NO_ROLE_THERE = (
    "You hold no role over that part of the organization, so you may not grant one there."
)


@pytest.fixture
def second_owner(tenant: Tenant, owner: User, member: User, owner_actor: Actor) -> User:
    """A second owner, so the ownerless floor is never what refuses below.

    Every test here is about the *ceiling*, and a tenant with one owner has a
    second reason to refuse a demotion. Separating them is what makes the wall
    order provable instead of merely plausible: with two owners only one wall is
    standing, and the tests that plant both say so in their names.
    """
    set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role=Membership.Role.OWNER,
        actor=owner_actor,
    )
    return member


# --- the hole, red first ------------------------------------------------------


def test_an_admin_may_not_demote_an_owner(
    tenant: Tenant, owner: User, second_owner: User, admin_actor: Actor
) -> None:
    """The repro for that gap. Before the ceiling this returned a `member` membership.

    The owner being demoted is not the tenant's last, so nothing else on this
    road refuses: the `200` this used to answer was the whole hole.
    """
    membership = membership_of(owner, tenant)

    with pytest.raises(Forbidden) as refused:
        set_role(
            tenant=tenant,
            membership=membership,
            role=Membership.Role.MEMBER,
            actor=admin_actor,
        )

    assert str(refused.value) == CEILING
    assert refused.value.code == "forbidden"
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


def test_both_roads_above_your_ceiling_speak_with_one_voice(
    tenant: Tenant, owner: User, second_owner: User, admin_actor: Actor
) -> None:
    """One predicate, one sentence shape — asserted by comparing the two.

    Demotion and revocation are the same refusal about the same row for the same
    reason, and they differ in exactly one word: which act was refused. A client
    that branched on the words would otherwise learn one grammar for the road
    that empties the row and another for the road that empties the role.
    """
    membership = membership_of(owner, tenant)

    with pytest.raises(Forbidden) as demoted:
        set_role(
            tenant=tenant,
            membership=membership,
            role=Membership.Role.MEMBER,
            actor=admin_actor,
        )
    with pytest.raises(Forbidden) as revoked:
        revoke_membership(tenant=tenant, membership=membership, actor=admin_actor)

    assert str(demoted.value) == str(revoked.value).replace("remove", "demote")
    assert demoted.value.code == revoked.value.code == "forbidden"


# --- the walls, and which one speaks ------------------------------------------


def test_the_escalation_wall_answers_before_this_ceiling(
    tenant: Tenant, owner: User, second_owner: User, nomad: User, root_org: Organization
) -> None:
    """Two walls would refuse; the one about the actor's standing speaks.

    Somebody holding no role in this tenant at all is refused for holding
    nothing — not for the height of the row they reached for. If this ceiling
    ran first it would quote their effective role at them, and their effective
    role is `None`.
    """
    outsider = actor_for(user=nomad, tenant=tenant, org=root_org)

    with pytest.raises(Forbidden) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            role=Membership.Role.MEMBER,
            actor=outsider,
        )

    assert str(refused.value) == NO_ROLE_THERE
    assert "None" not in str(refused.value)


def test_the_granted_role_is_judged_before_the_held_one(
    tenant: Tenant, owner: User, member_actor: Actor
) -> None:
    """All three walls would refuse; the granted role speaks, as it always did.

    A `member` moving the tenant's last owner to `admin` is over every wall on
    this road at once: above their own grant ceiling, above the role they hold,
    and one demotion away from an ownerless tenant. The escalation wall is the
    older rule and the one the route's contract names first, so this ceiling is
    added *behind* it and the addition is proved not to have moved the answer.

    (No `second_owner` here on purpose — that fixture promotes the `member`
    this actor is, and a test whose actor was quietly an owner would pass for a
    reason it never stated.)
    """
    with pytest.raises(Forbidden) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            # A plain string, because that is what both doors deliver — and
            # because `_refuse_escalation` quotes what it was handed, so an
            # enum member here would put `Membership.Role.ADMIN` in a sentence
            # written for a person.
            role=Membership.Role.ADMIN.value,
            actor=member_actor,
        )

    assert str(refused.value).startswith("You may not grant 'admin':")


def test_this_ceiling_answers_before_the_ownerless_floor(
    tenant: Tenant, owner: User, admin_actor: Actor
) -> None:
    """Two walls would refuse; the ceiling speaks, and the floor stays quiet.

    The tenant's *last* owner, demoted by an admin: the ownerless floor would
    refuse this with `conflict` and a sentence about the owner census. The admin
    may not touch this row at all, and a refusal that told them how many owners
    the tenant has left would be answering a question they may not ask.
    """
    membership = membership_of(owner, tenant)

    with pytest.raises(Forbidden) as refused:
        set_role(
            tenant=tenant,
            membership=membership,
            role=Membership.Role.MEMBER,
            actor=admin_actor,
        )

    assert str(refused.value) == CEILING
    assert LAST_OWNER not in str(refused.value)
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


def test_the_ownerless_floor_still_fires_for_somebody_under_the_ceiling(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The floor is not shadowed: past the ceiling, it is still standing.

    The other half of the ordering claim. An owner demoting the last owner —
    themselves — clears the ceiling (equal rank) and meets the floor, exactly as
    it did before this fix.
    """
    with pytest.raises(Conflict) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            role=Membership.Role.MEMBER,
            actor=owner_actor,
        )

    assert str(refused.value) == LAST_OWNER


def test_a_role_this_product_does_not_know_does_not_get_you_past_the_ceiling(
    tenant: Tenant, owner: User, second_owner: User, admin_actor: Actor
) -> None:
    """Standing is judged before the payload is believed.

    `_refuse_removing_the_last_owner` is gated on the role being one this
    product knows, because answering `conflict` would tell a caller their typo
    was a state problem. This ceiling is deliberately **not** gated the same
    way: it is a question about the actor, and the answer does not depend on
    what they sent. An admin reaching for an owner's row hears the same refusal
    whatever value they put in it, and `role` is a plain `str` on the patch
    schema, so a value like this really does arrive here.
    """
    with pytest.raises(Forbidden) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            role="regional-manager",
            actor=admin_actor,
        )

    assert str(refused.value) == CEILING
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


# --- what the ceiling must not touch ------------------------------------------


def test_an_owner_may_demote_an_owner(
    tenant: Tenant, owner: User, second_owner: User, owner_actor: Actor
) -> None:
    """Equal rank is not above: the ceiling is `>`, not `>=`."""
    demoted = set_role(
        tenant=tenant,
        membership=membership_of(second_owner, tenant),
        role=Membership.Role.MEMBER,
        actor=owner_actor,
    )

    assert demoted.role == Membership.Role.MEMBER


def test_an_admin_may_demote_an_admin(
    tenant: Tenant, admin_member: User, admin_actor: Actor
) -> None:
    """Equal rank again, from the rank the escalation gap was actually about."""
    demoted = set_role(
        tenant=tenant,
        membership=membership_of(admin_member, tenant),
        role=Membership.Role.MEMBER,
        actor=admin_actor,
    )

    assert demoted.role == Membership.Role.MEMBER


def test_an_admin_may_still_move_a_member_either_way(
    tenant: Tenant, member: User, admin_actor: Actor
) -> None:
    """Downward-within-rank and upward-to-your-own-rank, both untouched."""
    promoted = set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role=Membership.Role.ADMIN,
        actor=admin_actor,
    )
    assert promoted.role == Membership.Role.ADMIN

    demoted = set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role=Membership.Role.MEMBER,
        actor=admin_actor,
    )
    assert demoted.role == Membership.Role.MEMBER


def test_the_product_acting_for_itself_is_not_measured(
    tenant: Tenant, owner: User, second_owner: User
) -> None:
    """`actor=None` is nobody acting — the reading `_refuse_escalation` gives it.

    Signup, an invitation being accepted, a management command, a system actor:
    there is no actor to measure, and these paths are the product acting for
    itself rather than a person reaching above their own role.
    """
    demoted = set_role(
        tenant=tenant,
        membership=membership_of(owner, tenant),
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )

    assert demoted.role == Membership.Role.MEMBER


# --- the doors ----------------------------------------------------------------


def test_the_wire_refuses_the_demotion_as_ft_1_would_drive_it(
    api: Client, tenant: Tenant, owner: User, second_owner: User, admin_member: User
) -> None:
    """The refusal flows out of the service through the one composer (rule 14).

    Driven the way a caller drives it: log in as the admin, PATCH the owner's
    role, read the body. Nothing in `apps/core/api/routes.py` catches this —
    `config/api.py` maps it — and the route's contract has promised this refusal
    in prose since before the guard existed ("the membership you are changing is
    already above your own"), which is the drift this closes.
    """
    membership = membership_of(owner, tenant)
    api.force_login(admin_member)

    response = api.patch(
        role_url(membership),
        data={"role": Membership.Role.MEMBER},
        content_type=JSON,
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == CEILING
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


def test_the_machine_door_refuses_it_with_the_same_words(
    api: Client, tenant: Tenant, owner: User, second_owner: User, admin_member: User
) -> None:
    """Rule 17, the strict form: the MCP message IS the REST body, rendered.

    Not "both refuse" — string-compared, so a second refusal grammar cannot grow
    on the machine door for this ceiling without this failing.
    """
    membership = membership_of(owner, tenant)
    api.force_login(admin_member)
    rest = api.patch(
        role_url(membership),
        data={"role": Membership.Role.MEMBER},
        content_type=JSON,
    )
    assert rest.status_code == 403

    with pytest.raises(ToolError) as refused:
        tool("update_membership")(
            context_for(admin_member, tenant),
            membership_id=membership.pk,
            # A plain string, because that is what the transport delivers.
            role=Membership.Role.MEMBER.value,
        )

    assert str(refused.value) == refusal_message(rest.json())
    assert membership_of(owner, tenant).role == Membership.Role.OWNER
