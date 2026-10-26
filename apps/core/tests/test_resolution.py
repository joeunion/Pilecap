"""Resolution: what one person holds in one place, and the seven steps that read it.

`allows` used to ask two questions — "is there a policy?" and, failing that,
"is this role privileged?" — and a role was one of three words. It is a
COLLECTION now, assembled from three layers that each have one owner: `owner`
is the vocabulary, a declared role is its patterns over it, and a tenant's own
rows are the difference. This file drives the thirteen states the blueprint
names, one case each, over one world built by services.

**The world** (`permissions_world.build_world`): `root → A → A1 → A1X` and a
sibling `B`, with an owner at the root, an admin at A, a member at the root, a
person holding `member` at the root AND a custom `approver` at A, and a
roleless membership at B. Every hat is the node named, because a test that
forgot its hat would pass or fail for a reason it never stated.

**What is not driven here, and why.** A predicate that queries — its cost is
its own, and each app's sweep pins it. `governing()` — untouched here.
A hat outside the subtree — `core.middleware.resolve_org` refuses it before
`require` is ever called, so a case here would be measuring a door that has
already closed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.api.scopes import effective_scopes
from apps.core.authz import (
    RESERVED_PERMISSIONS,
    VIRTUAL_KINDS,
    collection,
    effective_permissions,
    effective_role,
    holds,
    kind_registry,
    policies,
    rank,
    refusal_sentence,
    vocabulary,
    where_of,
)
from apps.core.exceptions import Forbidden
from apps.core.models import Grant, Membership, Organization, Role, RolePermission, Tenant
from apps.core.selectors import list_invitations, list_memberships, list_organizations
from apps.core.services import add_membership, create_organization, set_role
from apps.core.tests.permissions_world import (
    PASSWORD,
    World,
    build_world,
    census,
    declared_action_keys,
    read_action_keys,
)

pytestmark = pytest.mark.django_db

JSON = "application/json"
MEMBERSHIPS = "/api/v1/memberships/"

#: The seven keys `core` used to guard with one "do you administer this node"
#: predicate. They are ordinary capabilities now.
ADMINISTRATIVE_KEYS = (
    "organization.create",
    "organization.update",
    "organization.move",
    "invitation.create",
    "invitation.revoke",
    "tenant.update",
    "membership.delete",
)


@pytest.fixture
def world(db: None) -> World:
    return build_world()


def _grant(membership: Membership, permission: str, effect: str) -> Grant:
    """A raw grant row. Legal until P4 lands the hand-out services (P3.9)."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=effect,
    )


# --- the thirteen states ------------------------------------------------------


def test_state_present(world: World) -> None:
    """A key held via the role at the node it is asked at."""
    assert "organization.create" in effective_permissions(
        world.admin_at_a.user, world.tenant, world.a
    )
    assert holds(world.admin_at_a, "organization.create", world.a)
    # The custom role's own key, held at A because the membership is at A.
    assert "widget.approve" in effective_permissions(world.approver.user, world.tenant, world.a)


def test_state_absent(world: World) -> None:
    """A member asked for a key with no row behind it, and no role carrying it."""
    assert not allows_(world.member, "widget.delete")
    assert "organization.create" not in effective_permissions(
        world.member.user, world.tenant, world.root
    )
    assert not allows_(world.member, "organization.create", world.root)


def test_state_allowed_by_grant(world: World) -> None:
    """One `allow` grant flips exactly one key, and nothing else moves."""
    before = effective_permissions(world.member.user, world.tenant, world.root)
    assert "organization.create" not in before

    _grant(world.member_membership, "organization.create", Grant.Effect.ALLOW)

    after = effective_permissions(world.member.user, world.tenant, world.root)
    assert after - before == {"organization.create"}
    assert before - after == set()
    assert allows_(world.member, "organization.create", world.root)


def test_state_withheld(world: World) -> None:
    """One `withhold` removes exactly one key the role gave, and only that one."""
    before = effective_permissions(world.admin_at_a.user, world.tenant, world.a)
    assert "organization.create" in before

    _grant(world.admin_membership, "organization.create", Grant.Effect.WITHHOLD)

    after = effective_permissions(world.admin_at_a.user, world.tenant, world.a)
    assert before - after == {"organization.create"}
    assert after - before == set()
    assert not allows_(world.admin_at_a, "organization.create", world.a1)


def test_state_inherited(world: World) -> None:
    """Held at A1X through the membership at A. Roles inherit downwards."""
    assert "organization.create" in effective_permissions(
        world.admin_at_a.user, world.tenant, world.a1x
    )
    assert allows_(world.admin_at_a, "organization.create", world.a1x)


def test_state_conflicting_withhold_wins(world: World) -> None:
    """Allowed at the root, withheld at A, asked at A1 → no.

    **"Forbid overrides permit"** (BVB-2, the name the survey gives it): a
    withhold anywhere on the chain beats an allow anywhere on it, because the
    alternative is a subtraction somebody undoes by being given something.
    """
    _grant(world.approver_root_membership, "organization.create", Grant.Effect.ALLOW)
    _grant(world.approver_a_membership, "organization.create", Grant.Effect.WITHHOLD)

    at_a1 = effective_permissions(world.approver.user, world.tenant, world.a1)
    assert "organization.create" not in at_a1
    # And at the root, where only the allow is on the chain, it is held.
    assert "organization.create" in effective_permissions(
        world.approver.user, world.tenant, world.root
    )


def test_state_undeclared(world: World, caplog: pytest.LogCaptureFixture) -> None:
    """An owner's "everything" is the VOCABULARY, not every string somebody types."""
    assert "invoice.void" not in vocabulary()

    with caplog.at_level(logging.WARNING):
        answer = allows_(world.owner, "invoice.void")

    assert answer is False
    lines = [_line(record) for record in caplog.records]
    assert any(
        line.get("event") == "core.authz.undeclared" and line.get("action") == "invoice.void"
        for line in lines
    ), lines


def test_state_renamed(world: World) -> None:
    """The alias resolves before the lookup, so an old key answers as its successor."""
    assert allows_(world.admin_at_a, "organization.rename", world.a1) is allows_(
        world.admin_at_a, "organization.update", world.a1
    )
    assert allows_(world.admin_at_a, "organization.rename", world.a1)
    assert not allows_(world.member, "organization.rename", world.a1)


def test_state_excluded(world: World) -> None:
    """Grant beats role, withhold beats grant — over one key, in three moves.

    **Four questions on one actor across three writes, so each move forgets**
    (PR0.3): the memo's TTL is the actor instance, and this test is four
    "requests" wearing one. `forget_permissions()` is what the next request is,
    and spelling it here rather than making the helper drop the memo keeps the
    stale window observable where it is the subject
    (`test_a_self_withhold_is_seen_after_forget`).
    """
    assert allows_(world.member, "widget.create")

    RolePermission.objects.create(
        tenant=world.tenant,
        role_key="member",
        permission="widget.create",
        effect=RolePermission.Effect.EXCLUDE,
    )
    world.member.forget_permissions()
    assert not allows_(world.member, "widget.create")

    grant = _grant(world.member_membership, "widget.create", Grant.Effect.ALLOW)
    world.member.forget_permissions()
    assert allows_(world.member, "widget.create")

    grant.effect = Grant.Effect.WITHHOLD
    grant.save(update_fields=["effect", "updated_at"])
    world.member.forget_permissions()
    assert not allows_(world.member, "widget.create")


def test_a_roleless_membership_holds_nothing(world: World) -> None:
    """Somebody who belongs here and holds nothing beyond their own grants.

    The blueprint's own name for the case, and P3.9's criterion: the set is
    empty, every non-read key is refused, the subtree is still readable in
    Phase W, and one grant flips exactly one key.
    """
    assert effective_permissions(world.roleless.user, world.tenant, world.b) == frozenset()
    for key in ("widget.create", "organization.create", "membership.create"):
        assert not allows_(world.roleless, key), key

    # PHASE R: the reads are a permission now, so the subtree does not list at
    # all — a list has no row to hide and `forbidden` is the only honest answer.
    with pytest.raises(Forbidden):
        list_organizations(tenant=world.tenant, org=world.b, actor=world.roleless)

    # ...and ONE grant opens exactly one door. The other five selectors are
    # untouched by it, which is the whole claim a per-key grant makes.
    _grant(world.roleless_membership, "organization.read", Grant.Effect.ALLOW)
    world.roleless.forget_permissions()
    assert list_organizations(tenant=world.tenant, org=world.b, actor=world.roleless).exists()
    with pytest.raises(Forbidden):
        list_memberships(tenant=world.tenant, org=world.b, actor=world.roleless)

    _grant(world.roleless_membership, "widget.create", Grant.Effect.ALLOW)
    world.roleless.forget_permissions()
    assert effective_permissions(world.roleless.user, world.tenant, world.b) == frozenset(
        {"widget.create", "organization.read"}
    )


def test_state_owner(world: World) -> None:
    """Every non-virtual key, the reserved one included — and a withhold still bites."""
    held = effective_permissions(world.owner.user, world.tenant, world.root)
    expected = {action for action, word in vocabulary().items() if word.kind not in VIRTUAL_KINDS}

    assert held == expected
    assert set(RESERVED_PERMISSIONS) <= held

    _grant(world.owner_membership, "tenant.update", Grant.Effect.WITHHOLD)
    assert "tenant.update" not in effective_permissions(world.owner.user, world.tenant, world.root)


def test_state_read_is_a_permission(world: World) -> None:
    """Every `.read` key resolves like every other key — held, or not (ADR core-27).

    The seven states the flip is made of, in one case, because they are one
    question asked of seven people: `owner` holds the vocabulary, `admin` holds
    `*`, `member` holds `*.read`; a membership with NO role holds nothing and a
    CUSTOM role holds exactly what its collection names — so `approver`, whose
    only include row is `widget.approve`, reads nothing at all. That last one is
    the consequence a product feels first (Overrule 5), so it is asserted rather
    than mentioned. Then one `allow` grant opens exactly one kind, and one
    `withhold` on a chain closes exactly one, at and below the node it sits on
    and not above it.

    **Not driven here:** a read key carrying a PREDICATE (`export.read`,
    `file.read`, `workflowrun.read`) — the predicate is ANDed exactly as it is
    for any key, and each of those apps' own rungs drives it.
    """
    kinds = sorted(kind_registry())
    for kind in kinds:
        key = f"{kind}.read"
        assert allows_(world.owner, key), f"{key} for owner"
        assert allows_(world.member, key), f"{key} for member"
        # The admin holds it at A and below, by inheritance, and nowhere else.
        assert allows_(world.admin_at_a, key, world.a), f"{key} for admin at A"
        assert allows_(world.admin_at_a, key, world.a1x), f"{key} for admin at A1X"
        # A membership with NO role holds nothing, reads included.
        assert not allows_(world.roleless, key), f"{key} for the roleless membership"
        # ...and `world.approver` DOES read at A, which is not a contradiction:
        # they hold `member` at the ROOT as well, and the root is on A's chain.
        # Inheritance is the whole reason the custom case needs its own person.
        assert allows_(world.approver, key, world.a), f"{key} for approver (via member at root)"

    # OVERRULE 5, asserted on somebody who holds ONLY the custom role: a role
    # reads what its collection names, and `approver`'s collection is one
    # include row (`widget.approve`). This is the consequence a product feels
    # first, and it is why the role services accept `"*.read"` as a pattern.
    custom_only = create_user(email=f"custom-only-{uuid4().hex[:8]}@example.com", password=PASSWORD)
    add_membership(
        user=custom_only,
        tenant=world.tenant,
        organization=world.a,
        role="approver",
        actor=system_actor(tenant=world.tenant),
    )
    custom_actor = actor_for(user=custom_only, tenant=world.tenant, org=world.a)
    # The DATA half, because that is what a collection is: `widget.approve`
    # carries a predicate of the example app's own and `allows` would be
    # answering the predicate's question about an `Organization`, not this one.
    assert "widget.approve" in effective_permissions(custom_only, world.tenant, world.a)
    for kind in kinds:
        assert not allows_(custom_actor, f"{kind}.read", world.a), f"{kind}.read for custom-only"

    # One grant opens exactly one kind for the roleless membership.
    _grant(world.roleless_membership, "widget.read", Grant.Effect.ALLOW)
    world.roleless.forget_permissions()
    assert allows_(world.roleless, "widget.read", world.b)
    for kind in kinds:
        if kind == "widget":
            continue
        assert not allows_(world.roleless, f"{kind}.read", world.b), kind

    # One withhold closes exactly one kind for the admin, at A and below.
    _grant(world.admin_membership, "organization.read", Grant.Effect.WITHHOLD)
    world.admin_at_a.forget_permissions()
    assert not allows_(world.admin_at_a, "organization.read", world.a)
    assert not allows_(world.admin_at_a, "organization.read", world.a1x)
    assert allows_(world.admin_at_a, "membership.read", world.a)
    # ...and not at the root, where the admin holds nothing either way.
    assert not allows_(world.admin_at_a, "organization.read", world.root)


def test_state_derived(world: World) -> None:
    """A key nobody typed: no prose, no predicate, and it behaves like any other."""
    word = vocabulary()["organization.delete"]
    assert word.decided_by == "derived"
    assert word.predicate is None
    assert "organization.delete" not in policies()

    assert allows_(world.owner, "organization.delete", world.a)
    assert allows_(world.admin_at_a, "organization.delete", world.a)
    assert not allows_(world.member, "organization.delete", world.a)


# --- P3.2 · the query budget ---------------------------------------------------


def test_effective_permissions_costs_three_statements_at_scale(
    world: World, django_assert_num_queries: Any
) -> None:
    """Five memberships on the chain, twelve grants, three custom roles, twenty rows.

    `n = 3` because the three tables are read ONCE each — the memberships, their
    grants, and the delta rows for the role keys they name — and the algebra is
    set arithmetic in Python. It is a ceiling and not a floor: a memo would
    lower it, and PM decision 6 says measure before buying one.
    """
    person = create_user(
        email=f"deep-{uuid4().hex[:8]}@example.com",
        password=PASSWORD,
    )
    system = system_actor(tenant=world.tenant)
    nodes = [world.root, world.a, world.a1, world.a1x]
    a1x2 = create_organization(
        tenant=world.tenant, parent=world.a1x, name="A1X2", slug="a1x2", actor=system
    )
    nodes.append(a1x2)

    custom_keys = [f"custom{index}" for index in range(3)]
    for key in custom_keys:
        Role.objects.create(tenant=world.tenant, key=key, name=key.title())
    permissions = sorted(vocabulary())[:20]
    for index, permission in enumerate(permissions):
        RolePermission.objects.create(
            tenant=world.tenant,
            role_key=custom_keys[index % 3],
            permission=permission,
            effect=RolePermission.Effect.INCLUDE,
        )

    memberships = [
        add_membership(
            user=person,
            tenant=world.tenant,
            organization=node,
            role=custom_keys[index % 3],
            actor=system,
        )
        for index, node in enumerate(nodes)
    ]
    assert len(memberships) == 5
    grants = sorted(vocabulary())[20:32]
    assert len(grants) == 12
    for index, permission in enumerate(grants):
        _grant(memberships[index % 5], permission, Grant.Effect.ALLOW)

    with django_assert_num_queries(3):
        effective_permissions(person, world.tenant, a1x2)


def test_a_second_require_in_one_request_pays_nothing_more(
    world: World, django_assert_num_queries: Any
) -> None:
    """**One actor, one fetch** (PR0.1). Lead decision 8, superseded on its own trigger.

    Two capability questions in one request, at two DIFFERENT nodes, on one
    actor: `n = 3`, because the three tables are read once and the second
    question reads none. The nodes differ deliberately — the rows cached are the
    raw rows and the chain filter is Python, so one fetch answers the question
    everywhere in the tree; a memo keyed on `(actor, at)` would pay three again
    here and this test is what would say so.

    It pinned **6** until PR0 (`test_a_second_require_in_one_request_pays_three_more`,
    the measurement PM decision 6 asked for before buying a memo). Phase R makes
    two `require`s per write request the norm, which is the trigger lead
    decision 8 named.
    """
    actor = world.admin_at_a
    with django_assert_num_queries(3):
        assert allows_(actor, "organization.create", world.a)
        assert allows_(actor, "organization.create", world.a1)


def test_two_actors_for_one_person_do_not_share_a_memo(
    world: World, django_assert_num_queries: Any
) -> None:
    """The TTL is the INSTANCE, and one person may hold several (PR0.1).

    Two `actor_for(...)` for one human in one tenant are two calls — two
    requests, a request and an activity — and they pay three statements each.
    The memo is a per-call convenience, not a process-wide cache: a cache that
    outlived the call would be one nobody could invalidate from the write that
    narrowed it.
    """
    person = world.admin_at_a.user
    first = actor_for(user=person, tenant=world.tenant, org=world.a)
    second = actor_for(user=person, tenant=world.tenant, org=world.a)
    assert first is not second

    with django_assert_num_queries(6):
        assert allows_(first, "organization.create", world.a)
        assert allows_(second, "organization.create", world.a)


def test_the_wall_reads_the_target_uncached(world: World) -> None:
    """**A warm memo answers for its own actor and nobody else** (PR0.2).

    The hand-out family P4 builds (`_refuse_handing_out`, `_refuse_taking_back`,
    `_refuse_orphaning_the_tenant`) measures the TARGET's effective set while
    holding the GRANTER's actor. If the memo were consulted by instance rather
    than by identity, the granter's warm rows would answer a question about
    somebody else — a wall reading the wrong person's permissions, which is a
    wall that is not there. `_memo_box`'s identity gate is what forbids it, and
    removing that gate is how this test is driven red.

    **Finding, recorded rather than assumed:** on this tree
    `_refuse_escalation` and `_refuse_acting_above_yourself` read
    `effective_role` — the target's ROLE column and the actor's own chain — and
    call `effective_permissions` not at all, so today's wall is uncached by
    construction. The end-to-end line below pins that a warm granter memo moves
    nothing about `set_role`; the assertion above is the property P4's walls will
    rest on.
    """
    granter = world.admin_at_a
    # Warm the granter's memo on their own question, at their own node.
    assert allows_(granter, "membership.update", world.a)

    # A raw withhold on the TARGET — the owner, who holds everything — planted
    # after the granter's rows were read. The victim is built by this test.
    _grant(world.owner_membership, "membership.update", Grant.Effect.WITHHOLD)

    # The target's set, asked while the granter's memo is warm and at a node
    # where the granter DOES hold the key: with the gate removed this reads the
    # granter's rows and answers True.
    assert "membership.update" not in effective_permissions(
        world.owner.user, world.tenant, world.a, memo=granter
    )
    # ... and the granter's own answer is still their own.
    assert allows_(granter, "membership.update", world.a)

    # The wall end to end: the granter's warm memo changes nothing about what
    # `set_role` reads off the target row.
    changed = set_role(
        tenant=world.tenant,
        membership=world.approver_a_membership,
        role="member",
        actor=granter,
    )
    assert changed.role == "member"


def test_a_self_withhold_is_seen_after_forget(world: World) -> None:
    """The one stale window, driven in both directions (PR0.3).

    An owner withholding a key from their OWN membership inside a request that
    has already asked keeps the pre-write answer until the request ends — the
    window the slot's docstring declares. `forget_permissions()` is the one
    invalidation, and after it the truth is back. A withhold aimed at somebody
    else is not this case: it is a different identity and never touched the memo
    (`test_the_wall_reads_the_target_uncached`).
    """
    owner = world.owner
    assert allows_(owner, "tenant.update", world.root)

    _grant(world.owner_membership, "tenant.update", Grant.Effect.WITHHOLD)

    # Stale, and declared: the rows were read before the row existed.
    assert allows_(owner, "tenant.update", world.root)

    owner.forget_permissions()
    assert not allows_(owner, "tenant.update", world.root)


# --- P3.3 · the seven administrative keys -------------------------------------


def test_the_seven_administrative_keys_have_no_predicate_and_are_held_by_admin(
    world: World,
) -> None:
    """No predicate anywhere, and the declared `admin` holds all seven at its node."""
    registry = policies()
    for key in ADMINISTRATIVE_KEYS:
        assert key in vocabulary(), key
        assert key not in registry, key
        assert vocabulary()[key].predicate is None, key

    held = effective_permissions(world.admin_at_a.user, world.tenant, world.a)
    assert set(ADMINISTRATIVE_KEYS) <= held

    # And nothing of the seven is held at the root, where this admin holds no
    # membership — `tenant.update` is evaluated there, which is why a branch
    # admin still may not rewrite the tenant's settings.
    at_root = effective_permissions(world.admin_at_a.user, world.tenant, world.root)
    assert not set(ADMINISTRATIVE_KEYS) & at_root


# --- P3.4 · a member may no longer add a member -------------------------------


def test_a_member_may_not_add_a_member_and_the_contract_always_said_so(
    api: Client, tenant: Tenant, member: User, owner: User, admin_member: User, root_org: Any
) -> None:
    """Overrule 2, closed: the route has always published this 403.

    `_refuse_escalation` compares the role being granted against the granter's
    own — and for a member granting `member` that is `1 > 1`, false, so the row
    was written. The capability check is the half that was missing.
    """
    outsider = create_user(email=f"joiner-{uuid4().hex[:8]}@example.com", password=PASSWORD)

    api.force_login(member)
    refused = api.post(
        MEMBERSHIPS,
        data=json.dumps({"user_id": str(outsider.pk), "role": "member"}),
        content_type=JSON,
    )
    assert refused.status_code == 403, refused.content
    body = refused.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == refusal_sentence("membership.create")
    assert body["detail"] == "You may not add people to that organization."
    assert not Membership.objects.filter(user=outsider, tenant=tenant).exists()

    # An admin still may, exactly as before.
    api.force_login(admin_member)
    allowed = api.post(
        MEMBERSHIPS,
        data=json.dumps({"user_id": str(outsider.pk), "role": "member"}),
        content_type=JSON,
    )
    assert allowed.status_code == 201, allowed.content


def test_the_machine_door_refuses_the_same_add_with_the_same_words(
    api: Client, tenant: Tenant, member: User, admin_member: User
) -> None:
    """One rule, two doors — and the MCP line is the REST body RENDERED (E9).

    Not "both refuse": the machine door's message is `refusal_message` over the
    human door's own JSON, string-compared, so a second refusal grammar cannot
    grow on one door without this failing.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    from apps.core.exceptions import refusal_message
    from apps.core.tests.test_mcp_tenancy import context_for, tool

    outsider = create_user(email=f"joiner-{uuid4().hex[:8]}@example.com", password=PASSWORD)

    api.force_login(member)
    rest = api.post(
        MEMBERSHIPS,
        data=json.dumps({"user_id": str(outsider.pk), "role": "member"}),
        content_type=JSON,
    )
    assert rest.status_code == 403, rest.content

    with pytest.raises(ToolError) as raised:
        tool("create_membership")(
            context_for(member, tenant), user_id=str(outsider.pk), role="member"
        )
    assert refusal_sentence("membership.create") in str(raised.value)
    assert str(raised.value) == refusal_message(rest.json())

    created = tool("create_membership")(
        context_for(admin_member, tenant), user_id=str(outsider.pk), role="member"
    )
    assert created is not None


def test_a_member_may_not_change_a_members_role(
    tenant: Tenant, member: User, root_org: Organization
) -> None:
    """Today a member may set another member to `member` and get a 200."""
    from apps.core.exceptions import Forbidden

    other = create_user(email=f"other-{uuid4().hex[:8]}@example.com", password=PASSWORD)
    membership = add_membership(
        user=other,
        tenant=tenant,
        organization=root_org,
        role="member",
        actor=system_actor(tenant=tenant),
    )
    acting = actor_for(user=member, tenant=tenant, org=root_org)

    with pytest.raises(Forbidden) as raised:
        set_role(tenant=tenant, membership=membership, role="member", actor=acting)
    assert raised.value.detail == refusal_sentence("membership.update")


# --- P3.5 · where the question is asked ---------------------------------------


def test_where_of_names_the_objects_node(world: World) -> None:
    """Four cases, and the fourth is the one that must not widen."""
    assert where_of(world.member, world.a1) is world.a1

    row = Membership.objects.get(pk=world.admin_membership.pk)
    named = where_of(world.member, row)
    assert named is not None and named.pk == world.a.pk

    assert where_of(world.admin_at_a, None) is world.admin_at_a.org

    hatless = actor_for(user=world.member.user, tenant=world.tenant, org=None)
    assert where_of(hatless, None) is None
    # And `None` is the TENANT-WIDE union for authorization — never for a read.
    assert effective_permissions(hatless.user, world.tenant, None)


def test_nothing_inherits_upward_or_sideways(world: World) -> None:
    """An admin at A is not an admin of the root and never sees B."""
    assert not holds(world.admin_at_a, "organization.create", world.root)
    assert not holds(world.admin_at_a, "organization.create", world.b)
    assert holds(world.admin_at_a, "organization.create", world.a1x)


# --- P3.6 · the echoed scopes read permissions, not rank ----------------------


def test_a_member_with_one_write_grant_echoes_only_that_familys_write_scope(
    tenant: Tenant, member: User, root_org: Organization
) -> None:
    """One granted write key backs the write scope of its own family and no other."""
    asked = ["org-structure:write", "connections:write"]
    assert effective_scopes(user=member, tenant=tenant, org=root_org, scopes=asked) == [
        "connections:read",
        "org-structure:read",
    ]

    membership = Membership.objects.get(user=member, tenant=tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="organization.create",
        effect=Grant.Effect.ALLOW,
    )

    assert effective_scopes(user=member, tenant=tenant, org=root_org, scopes=asked) == [
        "connections:read",
        "org-structure:read",
        "org-structure:write",
    ]


def test_a_roleless_membership_echoes_no_scope_at_all(world: World) -> None:
    """An echo is a claim about what a credential can BACK, and nothing backs this one.

    Phase R is what makes the case reachable: while reads were free, a roleless
    membership could still read, so echoing the read half of what it asked for
    was arguably honest. Now it holds nothing at all, and a token minted for it
    would carry scopes that refuse on every call.

    **Disproved while building PR1.7:** the criterion's "absent" case says the
    read half is echoed for a roleless membership today. It is not —
    `effective_scopes` has answered `[]` on an empty held-set since P3 (the
    `if not held: return []` line), so no code moved for this criterion and this
    test is a regression guard rather than a flip.
    """
    asked = ["connections:read", "connections:write"]
    assert (
        effective_scopes(user=world.roleless.user, tenant=world.tenant, org=world.b, scopes=asked)
        == []
    )
    # And the member beside them still echoes the read half of a family it writes nothing in.
    assert effective_scopes(
        user=world.member.user, tenant=world.tenant, org=world.root, scopes=asked
    ) == ["connections:read"]


def test_a_replaced_actor_starts_cold(world: World, django_assert_num_queries: Any) -> None:
    """`dataclasses.replace` must not carry one person's rows onto another (V-PR0).

    `replace` copies every `init=True` field into the new instance, so a memo
    that arrived through `__init__` would ride along and then pass the identity
    gate on the NEW actor's own identity — the old person's 184 keys answering
    a question about somebody who holds none. `init=False` on the slot is what
    forbids it, and this is the test that says so: nothing reaches for `replace`
    on an `Actor` today, and Phase R's fan-out is exactly the code that would.
    """
    warm = world.owner
    assert allows_(warm, "tenant.update", world.root)

    rebased = replace(warm, user=world.roleless.user, tenant=world.tenant, org=world.b)
    assert rebased._permission_rows == {}
    # `n = 2`, not 3: the roleless membership names no role key, so the delta
    # table is never read (`_delta_rows` is skipped when there are no keys).
    # What matters is that it is not ZERO — a carried memo would have answered
    # without touching the database at all, and with the owner's 184 keys.
    with django_assert_num_queries(2):
        assert not allows_(rebased, "tenant.update", world.b)
    # ...and the original is untouched: two boxes, not one shared dict.
    assert warm._permission_rows != {}


# --- P3.7 · the compat shims --------------------------------------------------


def test_a_custom_role_ranks_zero_and_effective_role_still_names_it(world: World) -> None:
    """The shim answers as it did, and the reason it had to stop being the wall."""
    assert rank("approver") == 0
    assert rank("member") == 1

    # The shim is BEST-RANKED, and a custom key ranks 0 — so the person holding
    # `member` at the root and the custom `approver` at A reads as `member` at
    # both, even though `approver` is the collection that carries `widget.approve`.
    # That is not a bug in the shim; it is the whole reason a rank comparison
    # could not stay the wall, and it is why `holds()` is what a predicate asks.
    assert effective_role(world.approver.user, world.tenant, world.a) == "member"
    assert holds(world.approver, "widget.approve", world.a)
    assert not holds(world.member, "organization.create", world.root)

    # Ties — two custom keys, both rank 0, both on the chain — break to the
    # NEAREST ancestor, which is the honest reading of "best" when the ranks
    # say nothing at all.
    Role.objects.create(tenant=world.tenant, key="reviewer", name="Reviewer")
    approver_user = world.approver.user
    assert approver_user is not None
    add_membership(
        user=approver_user,
        tenant=world.tenant,
        organization=world.a1,
        role="reviewer",
        actor=system_actor(tenant=world.tenant),
    )
    revoke = Membership.objects.get(pk=world.approver_root_membership.pk)
    revoke.delete()
    assert effective_role(world.approver.user, world.tenant, world.a1x) == "reviewer"
    assert effective_role(world.approver.user, world.tenant, world.a) == "approver"


def test_every_retired_seam_says_it_is_deprecated() -> None:
    """A shim that does not say so is a shim somebody builds on."""
    from pathlib import Path

    from django.conf import settings

    base = Path(settings.BASE_DIR)
    marked = sum(
        (base / name).read_text().count("deprecated v2.1")
        for name in ("apps/core/authz.py", "apps/core/models.py")
    )
    assert marked >= 10, marked


# --- P3.8 · the flat-product census -------------------------------------------


def population_diff(baseline: set[str], derived: set[str]) -> tuple[list[str], list[str]]:
    """(added, removed) between a baseline's keys and this tree's.

    One function so the census below and the planted case beside it compare
    populations the same way: a comparison written twice is a comparison that
    can disagree with itself, and the planted case exists precisely to prove
    this one can fire.

    A REMOVED key is the red, whatever the reason it left. The baseline is
    re-derived in place (`test_flat_baseline_document.py` holds the document to
    its writer on this tree), so a rename lands with a re-derivation in the
    same change and there is nothing left for an excuse to excuse — the
    rename table used to be consulted here and, once the document was current,
    excused no key at all. Growth is legal and printed.
    """
    return sorted(derived - baseline), sorted(baseline - derived)


def test_a_key_that_left_the_vocabulary_is_a_red() -> None:
    """The planted removal. **The diff above could not fire.**

    The census used to ask the tree for exactly the keys the document listed,
    so `added` and `removed` were empty by construction — a check that
    returns the same value whether or not the thing exists. This is the case
    that says otherwise, and it needs no scratch tree: a key in the baseline's
    copy that this tree does not derive IS a key that left the vocabulary, which
    is the shape the diff exists for — the red a product meets when a sweep
    drops a word its deployment still holds grants under.
    """
    derived = set(declared_action_keys()) | set(read_action_keys())
    departed = "gadget.polish"
    assert departed not in derived, "the planted key must be one this tree does not derive"

    added, removed = population_diff(derived | {departed}, derived)
    assert (added, removed) == ([], [departed])


def test_the_flat_product_census_equals_the_baseline(db: None) -> None:
    """Every answer a flat product had on the baseline tree, unchanged.

    The baseline is DERIVED — `permissions_world.census` run on a scratch clone
    of the sha its own header names, committed as `flat_product_baseline.json`
    with the command beside it — so this test compares two runs of one function
    rather than a run against somebody's reading of the old code.

    **Every key × 3 roles**, both halves present: the declared keys are the
    write population P3 pinned; the derived `<kind>.read` keys are the
    population Phase R moves, and they are in the document precisely so that "a
    product that customised nothing observes no change" is a measurement rather
    than a claim. The document's SIZE is held by `test_flat_baseline_document.py`
    — the writer-diff, which reds on any key the writer would add or drop — so
    this test asserts equality and the shape of every cell, never a typed
    number: a typed vocabulary count reds on every new key.

    The document was re-derived in place on `e85a5057` by its header's own
    command: 36 keys joined (the notes, tags and imports vocabularies, the
    family's archive and restore keys, the renamed successors) and 17 left
    (every one a pre-rename spelling), and **0 cells moved** across the 81 keys
    both documents share, which is the claim a re-derivation exists to make.
    """
    from pathlib import Path

    from django.conf import settings

    from apps.core.tests.permissions_world import flat_roles, flat_world

    document = json.loads(
        (Path(settings.BASE_DIR) / "apps/core/tests/flat_product_baseline.json").read_text()
    )
    expected: dict[str, dict[str, bool]] = document["answers"]
    reads = [key for key in expected if key.endswith(".read")]
    # Both halves are there — a census that stopped deriving either cannot pass.
    assert reads and len(reads) < len(expected), (len(reads), len(expected))
    assert sum(len(cells) for cells in expected.values()) == len(flat_roles()) * len(expected)

    _tenant, actors = flat_world()
    # **THE KEY SET IS DERIVED ON THIS TREE, never taken from the document.**
    # It used to be `sorted(expected)`, which made the two sets equal by
    # construction and the population diff below unable to fire at all: a key
    # that left the vocabulary would simply not be asked for, and the census
    # would read green over a shrinking one. `declared_action_keys()` and
    # `read_action_keys()` are the two halves the baseline's own writer unions,
    # so what is compared is this tree's answer to the question the document
    # was written from.
    actual = census(sorted(set(declared_action_keys()) | set(read_action_keys())), actors)

    # **The population, before the cells** (R1-F2.3). A diff that only prints moved
    # answers is silent about the one failure it cannot express: a key that left
    # the vocabulary. Its cells do not move — they stop existing — so the
    # comparison above would read green over a shrinking census. The key sets
    # are compared first, and a REMOVED key is the red; growth is legal and
    # printed.
    added, removed = population_diff(set(expected), set(actual))
    print(f"keys added: {added}")
    # Non-vacuity is the sibling's, not an assertion here: a re-derived baseline
    # makes both lists empty and that is the healthy state, so a count asserted
    # here would be a fact about the calendar. What proves the diff can fire is
    # `test_a_key_that_left_the_vocabulary_is_a_red`.
    assert removed == [], removed

    moved = [
        (key, role, expected[key][role], actual[key][role])
        for key in sorted(expected)
        for role in sorted(expected[key])
        if key in actual and expected[key][role] != actual[key][role]
    ]
    assert moved == [], moved


def test_phase_r_leaves_every_template_read_where_it_was(world: World) -> None:
    """**A product that customised nothing observes no change** (principle 13).

    The flip's whole risk is that it narrows somebody who was not supposed to
    be narrowed, and the population that must not move is the one every product
    starts with: the three TEMPLATE roles. So every `<kind>.read` still answers
    True for `owner`, `admin` and `member` — and each of core's list selectors,
    called with an actor, returns exactly the rows the scoped `visible_to` query
    returns, because `require` decides WHETHER and never WHICH (rule 24, BVB-4).

    `roleless` and `approver` LEFT this test at Phase R and live in
    `test_state_read_is_a_permission`: they read nothing, deliberately, and
    keeping them here would have been asserting the bug.
    """
    actors = (world.owner, world.admin_at_a, world.member)
    for kind in sorted(kind_registry()):
        for actor in actors:
            assert allows_(actor, f"{kind}.read"), f"{kind}.read for {actor.user}"

    from django.db.models import Q

    from apps.core.models import PATH_SEPARATOR, Invitation

    for actor in actors:
        org = actor.org
        assert org is not None
        subtree = Q(path=org.path) | Q(path__startswith=org.path + PATH_SEPARATOR)
        assert {
            row.pk for row in list_organizations(tenant=world.tenant, org=org, actor=actor)
        } == {row.pk for row in Organization.objects.for_tenant(world.tenant).filter(subtree)}
        rows = Q(organization__path=org.path) | Q(
            organization__path__startswith=org.path + PATH_SEPARATOR
        )
        assert {row.pk for row in list_memberships(tenant=world.tenant, org=org, actor=actor)} == {
            row.pk for row in Membership.objects.filter(tenant=world.tenant).filter(rows)
        }
        assert {row.pk for row in list_invitations(tenant=world.tenant, org=org, actor=actor)} == {
            row.pk for row in Invitation.objects.for_tenant(world.tenant).visible_to(org)
        }
    # All seven memberships (the clerk's at A among them) — a vacuous pass would make
    # the comparison above true for three empty sets.
    assert list_memberships(tenant=world.tenant, org=world.root, actor=world.owner).count() == 7


# --- the collection, read directly --------------------------------------------


def test_the_collection_reads_the_three_layers(world: World) -> None:
    """`owner` is the vocabulary · a declared key is code + deltas · custom is rows."""
    assert collection(world.tenant, "owner") == {
        action for action, word in vocabulary().items() if word.kind not in VIRTUAL_KINDS
    }
    assert collection(world.tenant, "approver") == frozenset({"widget.approve"})
    assert collection(world.tenant, "nobody-declared-this") == frozenset()
    assert collection(world.tenant, "") == frozenset()

    declared = collection(world.tenant, "member")
    RolePermission.objects.create(
        tenant=world.tenant,
        role_key="member",
        permission="organization.create",
        effect=RolePermission.Effect.INCLUDE,
    )
    assert collection(world.tenant, "member") - declared == {"organization.create"}


def test_a_reserved_key_is_never_added_by_a_row(world: World) -> None:
    """`tenant.own` is the ceiling: only `owner` holds it, and no row hands it over."""
    RolePermission.objects.create(
        tenant=world.tenant,
        role_key="approver",
        permission="tenant.own",
        effect=RolePermission.Effect.INCLUDE,
    )
    _grant(world.member_membership, "tenant.own", Grant.Effect.ALLOW)

    assert "tenant.own" not in collection(world.tenant, "approver")
    assert "tenant.own" not in effective_permissions(world.member.user, world.tenant, world.root)
    assert "tenant.own" in effective_permissions(world.owner.user, world.tenant, world.root)


# --- R1-F4 · a node in another tenant holds nothing ----------------------------


def test_a_node_in_another_tenant_holds_nothing(db: None, django_assert_num_queries: Any) -> None:
    """**Two tenants' trees are unrelated strings, and the path test could not tell.**

    Every tenant's root is path `"0000"`, so `is_descendant_path(root2.path,
    root1_membership.organization.path)` is True and the data half read an
    owner of tenant 1 as an owner of tenant 2's root. `may_be_named` had always
    compared `tenant_id`; `effective_permissions` never did.

    Driven over every named actor of world 1 × every node of world 2, with the
    node set read off the dataclass rather than typed, and the home answers
    asserted in the same test so it cannot pass vacuously.
    """
    import dataclasses

    from apps.core.models import Organization as Org

    here = build_world()
    there = build_world(approver_key="reviewer")
    foreign = [
        getattr(there, field.name)
        for field in dataclasses.fields(there)
        if isinstance(getattr(there, field.name), Org)
    ]
    assert len(foreign) == 5, foreign
    assert there.root.path == here.root.path, "the shared-path case is the whole point"

    for actor in (here.owner, here.admin_at_a, here.member, here.approver, here.roleless):
        for node in foreign:
            assert effective_permissions(actor.user, here.tenant, node) == frozenset()
            assert effective_role(actor.user, here.tenant, node) is None
            assert holds(actor, "organization.update", at=node) is False
    assert allows_(here.owner, "organization.update", there.root) is False

    # Non-vacuity: the same question at home still answers.
    assert allows_(here.owner, "organization.update", here.root) is True
    assert effective_role(here.owner.user, here.tenant, here.root) == "owner"

    # The check is a tenant id, so a foreign node costs nothing and never fills
    # — or consults — the actor's own memo.
    warm = here.owner
    effective_permissions(warm.user, here.tenant, here.root, memo=warm)
    with django_assert_num_queries(0):
        assert effective_permissions(warm.user, here.tenant, there.root, memo=warm) == frozenset()


def test_a_foreign_node_with_no_tenant_still_holds_nothing(db: None) -> None:
    """`tenant=None` was already `frozenset()`; it still is, foreign node or not."""
    there = build_world()
    assert effective_permissions(there.owner.user, None, there.root) == frozenset()
    assert effective_role(there.owner.user, None, there.root) is None


# --- R1-F2 · a declared role with no read pattern reads nothing ----------------


def test_a_declared_role_with_no_read_pattern_reads_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clause (4) said every role holds every `.read`. ADR core-27 says otherwise.

    The victim is planted: a declared role `reviewer` naming one WRITE pattern
    and nothing else, spliced into the one discovery walk (`test_roles_are_keys`'s
    idiom) rather than written to a file, so what is measured is the vocabulary
    the walk yields.

    Before this rider every one of the `.read` assertions below was True and
    `vocabulary()["organization.read"].default_roles` carried `'reviewer'` —
    a role declared to approve widgets read every kind in the deployment.
    """
    from django.apps import apps as django_apps

    from apps.core import authz
    from apps.core.authz import DeclaredRole

    real = authz._declarations

    def _with_a_reviewer(module: str, attribute: str) -> Any:
        found = list(real(module, attribute))
        if module == "roles":
            found.append(
                (
                    django_apps.get_app_config("example"),
                    {
                        "reviewer": DeclaredRole(
                            key="reviewer",
                            name="Reviewer",
                            permissions=("widget.approve",),
                        )
                    },
                )
            )
        return found

    authz.reset_policies()
    monkeypatch.setattr(authz, "_declarations", _with_a_reviewer)
    try:
        reviewer = add_membership(
            user=create_user(email=f"reviewer-{uuid4().hex[:8]}@example.com", password=PASSWORD),
            tenant=world.tenant,
            organization=world.b,
            role="reviewer",
            actor=system_actor(tenant=world.tenant),
        )
        acting = actor_for(user=reviewer.user, tenant=world.tenant, org=world.b)

        for key in ("organization.read", "membership.read", "invitation.read", "widget.read"):
            assert allows_(acting, key) is False, key
        # Non-vacuity: the role still HOLDS exactly what it declares. The data
        # half is the claim — `allows` would also run `example`'s `can_approve`
        # predicate, which answers False for `obj=None` (a question about a row,
        # asked with no row), and that is the predicate's answer rather than the
        # collection's.
        assert holds(acting, "widget.approve") is True
        assert vocabulary()["organization.read"].default_roles == ("admin", "member", "owner")

        with pytest.raises(Forbidden) as refused:
            list_organizations(tenant=world.tenant, org=world.b, actor=acting)
        assert str(refused.value) == refusal_sentence("organization.read")

        # The other states, in the same registry. `approver` is deliberately
        # NOT here: that person holds `member` at the ROOT as well, so at their
        # A hat they inherit `member`'s `*.read` — the custom-role-alone case is
        # `test_state_read_is_a_permission`'s, asked where no ancestor gives it.
        assert allows_(world.member, "organization.read") is True
        assert allows_(world.admin_at_a, "organization.read") is True
        assert allows_(world.roleless, "organization.read") is False
    finally:
        monkeypatch.undo()
        authz.reset_policies()


# --- helpers ------------------------------------------------------------------


def allows_(actor: Actor, action: str, obj: Any = None) -> bool:
    """`authz.allows`, imported at call time so a monkeypatched registry is seen."""
    from apps.core.authz import allows

    return allows(actor, action, obj)


def _line(record: logging.LogRecord) -> dict[str, Any]:
    try:
        parsed = json.loads(record.getMessage())
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
