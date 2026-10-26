"""The hand-out family: nobody gives away, or takes back, what they do not hold.

A grant is bounded by the granter's own effective set — a set, since no rank orders a custom role.
The old rank walls' sentences are asserted against `test_role_ceiling.py`, `test_last_owner.py`.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.management import call_command

from apps.core import authz
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Conflict, Forbidden, Invalid, NotFound
from apps.core.models import (
    Grant,
    Membership,
    Organization,
    Role,
    RolePermission,
    Tenant,
)
from apps.core.services import (
    add_membership,
    create_grant,
    create_role,
    delete_grant,
    delete_role,
    invite_member,
    set_role,
    set_role_collection,
    update_role,
)
from apps.core.tests.permissions_world import World, build_world, platform_keys
from apps.core.tests.test_last_owner import LAST_OWNER, membership_of
from apps.core.tests.test_role_ceiling import NO_ROLE_THERE, assert_ceiling
from apps.core.tests.tree_census import source_text

pytestmark = pytest.mark.django_db


# --- the world these cases drive ----------------------------------------------


@pytest.fixture
def world() -> World:
    """`root → A → A1 → A1X`, a sibling `B`, and one person per named state."""
    return build_world()


def _actor(world: World, membership: Membership, org: Organization) -> Actor:
    """An actor for the person this membership names, wearing `org` as the hat."""
    return actor_for(user=membership.user, tenant=world.tenant, org=org)


def _person(actor: Actor) -> AbstractBaseUser:
    """The user behind an actor this world built. **Never `None` here.**

    `Actor.user` is `AbstractBaseUser | None` because a request can resolve
    nobody; every actor in `permissions_world` is a person the builder created,
    so the narrowing is an assertion rather than a branch.
    """
    assert actor.user is not None
    return actor.user


def _grant(membership: Membership, permission: str, effect: str) -> Grant:
    """A raw grant, for a SET-UP that is not the subject of the test."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=effect,
    )


# --- P4.1 · nobody hands out what they do not hold -----------------------------


def test_an_admin_may_give_what_admin_holds(world: World) -> None:
    """The happy case. `admin` holds `widget.approve`, so an admin may grant it."""
    assert "widget.approve" in authz.effective_permissions(
        world.admin_at_a.user, world.tenant, world.a
    )
    member_at_a = add_membership(
        user=_person(world.member),
        tenant=world.tenant,
        organization=world.a,
        role="member",
        actor=system_actor(tenant=world.tenant),
    )

    handed = create_grant(
        tenant=world.tenant,
        actor=world.admin_at_a,
        membership=member_at_a,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )

    assert handed.permission == "widget.approve"
    assert handed.effect == Grant.Effect.ALLOW
    assert "widget.approve" in authz.effective_permissions(member_at_a.user, world.tenant, world.a)


def test_a_grantee_may_not_pass_on_what_they_do_not_hold(world: World) -> None:
    """**The hole the rank table left, as a refusal.**

    A plain `member` holding `grant.create` by grant may hand out grants — and
    under the rank table there was nothing at all bounding *which* ones, because
    `_refuse_escalation` compared role RANKS and a grant names no role. So a
    member could hand a colleague a capability `member` does not carry.

    The set comparison is the whole fix: `organization.create` is not in the
    granter's own effective set, so it is not theirs to give.
    """
    granter_membership = world.member_membership
    _grant(granter_membership, "grant.create", Grant.Effect.ALLOW)
    held = authz.effective_permissions(world.member.user, world.tenant, world.root)
    assert "grant.create" in held
    assert "organization.create" not in held

    with pytest.raises(Forbidden) as refused:
        create_grant(
            tenant=world.tenant,
            actor=world.member,
            membership=world.approver_root_membership,
            permission="organization.create",
            effect=Grant.Effect.ALLOW,
        )

    assert authz.refusal_sentence("organization.create") in str(refused.value)
    assert "organization.create" not in str(refused.value), "sentences, never keys"
    assert not Grant.objects.filter(
        membership=world.approver_root_membership, permission="organization.create"
    ).exists()


def test_a_custom_role_is_bounded_by_its_collection_and_not_by_a_rank(world: World) -> None:
    """A custom role's collection is what the wrapper measures, key by key.

    `rank("approver")` is `0`, so the rank table let anybody hand this role out
    whatever it contained. The collection says `widget.approve`, and a granter
    who does not hold `widget.approve` may not assign it.
    """
    RolePermission.objects.create(
        tenant=world.tenant,
        role_key="approver",
        permission="organization.create",
        effect=RolePermission.Effect.INCLUDE,
    )
    granter_membership = world.member_membership
    _grant(granter_membership, "membership.create", Grant.Effect.ALLOW)
    assert "organization.create" not in authz.effective_permissions(
        world.member.user, world.tenant, world.root
    )

    with pytest.raises(Forbidden) as refused:
        add_membership(
            user=_person(world.roleless),
            tenant=world.tenant,
            organization=world.root,
            role="approver",
            actor=world.member,
        )

    assert authz.refusal_sentence("organization.create") in str(refused.value)


def test_the_escalation_names_what_the_granter_is_short_of(world: World) -> None:
    """An admin granting `owner` hears the sentences of the keys an owner holds and they do not."""
    admin_actor = world.admin_at_a
    with pytest.raises(Forbidden) as refused_owner:
        add_membership(
            user=_person(world.roleless),
            tenant=world.tenant,
            organization=world.a,
            role="owner",
            actor=admin_actor,
        )
    said = str(refused_owner.value)
    assert refused_owner.value.code == "forbidden"
    assert said.startswith("You may not grant what you do not hold yourself:"), said
    short = authz.collection(world.tenant, "owner") - authz.collection(world.tenant, "admin")
    assert short and all(authz.refusal_sentence(key) in said for key in short), said

    with pytest.raises(Forbidden) as refused_outside:
        add_membership(
            user=_person(world.roleless),
            tenant=world.tenant,
            organization=world.b,
            role="member",
            actor=admin_actor,
        )
    assert str(refused_outside.value) == NO_ROLE_THERE


def test_reach_answers_before_the_capability_and_before_the_hand_out_wall(
    world: World,
) -> None:
    """In `create_grant`, REACH speaks first and `NO_ROLE_THERE` is unreachable.

    Three refusals could fire on this road, and the order is reach before
    capability: a membership
    the actor could not have named is `NotFound` (R1-F4.3), then `require` asks
    the key at the membership's node, then the hand-out wall measures the set.
    `_refuse_handing_out`'s empty-set sentence is therefore `add_membership`'s
    alone — that service puts the escalation wall in front of `require`
    deliberately, so an actor standing outside the subtree hears which problem
    they have. Two services, two orders, and both stated rather than assumed.
    """
    outsider = _actor(world, world.roleless_membership, world.b)

    # Reach: a root membership is not under the B hat.
    with pytest.raises(NotFound):
        create_grant(
            tenant=world.tenant,
            actor=outsider,
            membership=world.member_membership,
            permission="widget.create",
            effect=Grant.Effect.ALLOW,
        )

    # The key: a membership they CAN name, a key they do not hold.
    with pytest.raises(Forbidden) as refused:
        create_grant(
            tenant=world.tenant,
            actor=outsider,
            membership=world.roleless_membership,
            permission="widget.create",
            effect=Grant.Effect.ALLOW,
        )
    assert str(refused.value) == authz.refusal_sentence("grant.create")
    assert str(refused.value) != NO_ROLE_THERE


# --- P4.2 · nobody takes back what they do not hold ----------------------------


def test_the_ceiling_is_a_set_comparison_and_says_the_sentences(
    tenant: Tenant, owner: Any, member: Any, admin_actor: Actor, owner_actor: Actor
) -> None:
    """The take-back refusal names what the owner holds and the admin does not."""
    set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role=Membership.Role.OWNER,
        actor=owner_actor,
    )

    with pytest.raises(Forbidden) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            role=Membership.Role.MEMBER,
            actor=admin_actor,
        )

    assert_ceiling(str(refused.value), tenant)


def test_an_admin_may_not_withhold_from_an_owner(world: World) -> None:
    """A withhold is a take-back, and the ceiling reads with the verb substituted."""
    admin_at_root = add_membership(
        user=_person(world.admin_at_a),
        tenant=world.tenant,
        organization=world.root,
        role="admin",
        actor=system_actor(tenant=world.tenant),
    )
    acting = _actor(world, admin_at_root, world.root)

    with pytest.raises(Forbidden) as refused:
        create_grant(
            tenant=world.tenant,
            actor=acting,
            membership=world.owner_membership,
            permission="widget.create",
            effect=Grant.Effect.WITHHOLD,
        )

    assert_ceiling(str(refused.value), world.tenant, verb="restrict")
    assert not Grant.objects.filter(membership=world.owner_membership).exists()


def test_an_owner_may_withhold_from_another_owner(world: World) -> None:
    """Equal is not above: the comparison is a difference, and it is empty."""
    second = set_role(
        tenant=world.tenant,
        membership=world.member_membership,
        role="owner",
        # A hat, because `set_role` asks `may_be_named` first (R1-F4.2) and it
        # has no system exemption.
        actor=system_actor(tenant=world.tenant, org=world.root),
    )

    withheld = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=second,
        permission="widget.create",
        effect=Grant.Effect.WITHHOLD,
    )

    assert withheld.effect == Grant.Effect.WITHHOLD
    assert "widget.create" not in authz.effective_permissions(second.user, world.tenant, world.root)


def test_a_member_with_grant_create_may_not_withhold_from_an_admin(world: World) -> None:
    """The grantee may hand out grants; they still hold less than their target."""
    _grant(world.member_membership, "grant.create", Grant.Effect.ALLOW)

    with pytest.raises(Forbidden) as refused:
        create_grant(
            tenant=world.tenant,
            actor=world.member,
            membership=world.admin_membership,
            permission="widget.create",
            effect=Grant.Effect.WITHHOLD,
        )

    assert "restrict" in str(refused.value)
    assert not Grant.objects.filter(membership=world.admin_membership).exists()


# --- P4.3 · the root keeps one un-withheld owner -------------------------------


def test_a_withhold_of_the_reserved_key_is_invalid_not_a_floor_question(world: World) -> None:
    """`tenant.own` is reserved, so the floor cannot be reached by grant at all."""
    with pytest.raises(Invalid) as refused:
        create_grant(
            tenant=world.tenant,
            actor=world.owner,
            membership=world.owner_membership,
            permission="tenant.own",
            effect=Grant.Effect.WITHHOLD,
        )

    assert "permission" in refused.value.errors
    assert not Grant.objects.filter(permission="tenant.own").exists()


def test_the_floor_still_refuses_the_last_owner(
    tenant: Tenant, owner: Any, owner_actor: Actor
) -> None:
    """`LAST_OWNER` is `test_last_owner.py`'s own constant, produced by the new floor."""
    with pytest.raises(Conflict) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(owner, tenant),
            role=Membership.Role.MEMBER,
            actor=owner_actor,
        )

    assert str(refused.value) == LAST_OWNER
    assert membership_of(owner, tenant).role == Membership.Role.OWNER


# --- P4.4 · the six services ---------------------------------------------------


def test_create_role_writes_the_row_and_its_include_rows(world: World) -> None:
    role = create_role(
        tenant=world.tenant,
        actor=world.owner,
        key="reviewer",
        name="Reviewer",
        description="reads and approves",
        permissions=frozenset({"widget.approve", "widget.read"}),
    )

    assert role.key == "reviewer"
    assert set(
        RolePermission.objects.for_tenant(world.tenant)
        .filter(role_key="reviewer")
        .values_list("permission", flat=True)
    ) == {"widget.approve", "widget.read"}
    assert authz.collection(world.tenant, "reviewer") == frozenset(
        {"widget.approve", "widget.read"}
    )


def test_create_role_refuses_a_key_the_code_layer_already_owns(world: World) -> None:
    for key in ("owner", "member", "admin"):
        with pytest.raises(Invalid) as refused:
            create_role(
                tenant=world.tenant,
                actor=world.owner,
                key=key,
                name="Nope",
                permissions=frozenset(),
            )
        assert "key" in refused.value.errors


def test_create_role_refuses_an_undeclared_permission(world: World) -> None:
    with pytest.raises(Invalid) as refused:
        create_role(
            tenant=world.tenant,
            actor=world.owner,
            key="reviewer",
            name="Reviewer",
            permissions=frozenset({"gizmo.polish"}),
        )

    assert "permissions" in refused.value.errors
    assert "gizmo.polish" in " ".join(refused.value.errors["permissions"])


def test_create_role_refuses_a_reserved_permission(world: World) -> None:
    with pytest.raises(Invalid) as refused:
        create_role(
            tenant=world.tenant,
            actor=world.owner,
            key="pretender",
            name="Pretender",
            permissions=frozenset({"tenant.own"}),
        )

    assert "permissions" in refused.value.errors


def test_create_role_refuses_a_collection_the_maker_does_not_hold(world: World) -> None:
    _grant(world.member_membership, "role.create", Grant.Effect.ALLOW)

    with pytest.raises(Forbidden) as refused:
        create_role(
            tenant=world.tenant,
            actor=world.member,
            key="reviewer",
            name="Reviewer",
            permissions=frozenset({"organization.create"}),
        )

    assert authz.refusal_sentence("organization.create") in str(refused.value)
    assert not Role.objects.for_tenant(world.tenant).filter(key="reviewer").exists()


def test_create_role_refuses_without_the_key(world: World) -> None:
    with pytest.raises(Forbidden) as refused:
        create_role(
            tenant=world.tenant,
            actor=world.member,
            key="reviewer",
            name="Reviewer",
            permissions=frozenset(),
        )

    assert str(refused.value) == authz.refusal_sentence("role.create")


def test_update_role_renames_without_touching_the_key(world: World) -> None:
    role = Role.objects.for_tenant(world.tenant).get(key="approver")

    renamed = update_role(tenant=world.tenant, actor=world.owner, role=role, name="Reviewer")

    assert renamed.key == "approver"
    assert renamed.name == "Reviewer"


def test_update_role_refuses_a_declared_key(world: World) -> None:
    row = Role.objects.create(tenant=world.tenant, key="member", name="Member")

    with pytest.raises(Invalid) as refused:
        update_role(tenant=world.tenant, actor=world.owner, role=row, name="Nope")

    assert "key" in refused.value.errors


def test_update_role_refuses_without_the_key(world: World) -> None:
    role = Role.objects.for_tenant(world.tenant).get(key="approver")

    with pytest.raises(Forbidden) as refused:
        update_role(tenant=world.tenant, actor=world.member, role=role, name="Nope")

    assert str(refused.value) == authz.refusal_sentence("role.update")


def test_set_role_collection_replaces_a_custom_roles_includes(world: World) -> None:
    set_role_collection(
        tenant=world.tenant,
        actor=world.owner,
        role_key="approver",
        permissions=frozenset({"widget.read", "widget.create"}),
    )

    assert authz.collection(world.tenant, "approver") == frozenset({"widget.read", "widget.create"})
    assert (
        not RolePermission.objects.for_tenant(world.tenant)
        .filter(role_key="approver", permission="widget.approve")
        .exists()
    )


def test_set_role_collection_writes_a_declared_roles_delta(world: World) -> None:
    """A declared role keeps its code layer; the rows are the difference."""
    wanted = authz.defaults_for("member") | {"organization.create"}
    wanted -= {"widget.read"}

    set_role_collection(
        tenant=world.tenant,
        actor=world.owner,
        role_key="member",
        permissions=frozenset(wanted),
    )

    rows = dict(
        RolePermission.objects.for_tenant(world.tenant)
        .filter(role_key="member")
        .values_list("permission", "effect")
    )
    assert rows["organization.create"] == RolePermission.Effect.INCLUDE
    assert rows["widget.read"] == RolePermission.Effect.EXCLUDE


def test_set_role_collection_refuses_owner(world: World) -> None:
    with pytest.raises(Invalid) as refused:
        set_role_collection(
            tenant=world.tenant,
            actor=world.owner,
            role_key="owner",
            permissions=frozenset({"widget.read"}),
        )

    assert "role_key" in refused.value.errors


def test_set_role_collection_refuses_adding_what_the_actor_lacks(world: World) -> None:
    _grant(world.member_membership, "role.update", Grant.Effect.ALLOW)

    with pytest.raises(Forbidden) as refused:
        set_role_collection(
            tenant=world.tenant,
            actor=world.member,
            role_key="approver",
            permissions=frozenset({"organization.create"}),
        )

    assert authz.refusal_sentence("organization.create") in str(refused.value)


def test_set_role_collection_refuses_removing_what_the_actor_lacks(world: World) -> None:
    RolePermission.objects.create(
        tenant=world.tenant,
        role_key="approver",
        permission="organization.create",
        effect=RolePermission.Effect.INCLUDE,
    )
    _grant(world.member_membership, "role.update", Grant.Effect.ALLOW)
    _grant(world.member_membership, "widget.approve", Grant.Effect.ALLOW)

    with pytest.raises(Forbidden) as refused:
        set_role_collection(
            tenant=world.tenant,
            actor=world.member,
            role_key="approver",
            permissions=frozenset({"widget.approve"}),
        )

    assert authz.refusal_sentence("organization.create") in str(refused.value)


def test_delete_role_refuses_while_a_membership_names_it(world: World) -> None:
    role = Role.objects.for_tenant(world.tenant).get(key="approver")

    with pytest.raises(Conflict) as refused:
        delete_role(tenant=world.tenant, actor=world.owner, role=role)

    assert "approver" in str(refused.value)
    assert Role.objects.for_tenant(world.tenant).filter(key="approver").exists()


def test_delete_role_refuses_while_a_pending_invitation_names_it(world: World) -> None:
    set_role(
        tenant=world.tenant,
        membership=world.approver_a_membership,
        role="member",
        actor=world.owner,
    )
    invite_member(
        tenant=world.tenant,
        email="invited@example.com",
        role="approver",
        organization=world.root,
        actor=world.owner,
    )
    role = Role.objects.for_tenant(world.tenant).get(key="approver")

    with pytest.raises(Conflict):
        delete_role(tenant=world.tenant, actor=world.owner, role=role)


def test_delete_role_removes_the_role_and_its_rows(world: World) -> None:
    set_role(
        tenant=world.tenant,
        membership=world.approver_a_membership,
        role="member",
        actor=world.owner,
    )
    role = Role.objects.for_tenant(world.tenant).get(key="approver")

    died = delete_role(tenant=world.tenant, actor=world.owner, role=role)

    assert died.key == "approver"
    assert not Role.objects.for_tenant(world.tenant).filter(key="approver").exists()
    assert not RolePermission.objects.for_tenant(world.tenant).filter(role_key="approver").exists()


def test_create_grant_is_an_upsert(world: World) -> None:
    """Principle 16: the same hand-out twice is one row, and the last effect wins."""
    first = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )
    second = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.approve",
        effect=Grant.Effect.WITHHOLD,
    )

    assert first.pk == second.pk
    assert (
        Grant.objects.for_tenant(world.tenant)
        .filter(membership=world.member_membership, permission="widget.approve")
        .count()
        == 1
    )
    assert second.effect == Grant.Effect.WITHHOLD


def test_create_grant_refuses_an_undeclared_permission(world: World) -> None:
    with pytest.raises(Invalid) as refused:
        create_grant(
            tenant=world.tenant,
            actor=world.owner,
            membership=world.member_membership,
            permission="gizmo.polish",
            effect=Grant.Effect.ALLOW,
        )

    assert "permission" in refused.value.errors


def test_create_grant_refuses_a_membership_of_another_tenant_as_not_found(
    world: World, other_tenant: Tenant, stranger: Any
) -> None:
    """**Not `Invalid`** (R1-F4.3). A refusal that tells another tenant's row
    apart from a nonexistent id is an existence oracle; `may_be_named` folds
    both into `NotFound`, and it runs before `require` — reach before capability.
    """
    foreign = Membership.objects.filter(tenant=other_tenant).first()
    assert foreign is not None

    with pytest.raises(NotFound):
        create_grant(
            tenant=world.tenant,
            actor=world.owner,
            membership=foreign,
            permission="widget.create",
            effect=Grant.Effect.ALLOW,
        )
    assert not Grant.objects.filter(membership=foreign).exists()


def test_create_grant_refuses_a_membership_in_a_sibling_branch_as_not_found(
    world: World,
) -> None:
    """The sibling case the tenancy comparison never saw: an admin at A, a row in B."""
    with pytest.raises(NotFound):
        create_grant(
            tenant=world.tenant,
            actor=world.admin_at_a,
            membership=world.roleless_membership,
            permission="widget.create",
            effect=Grant.Effect.ALLOW,
        )
    assert not Grant.objects.filter(membership=world.roleless_membership).exists()


def test_delete_grant_refuses_a_grant_of_another_tenant_as_not_found(
    world: World, other_tenant: Tenant, stranger: Any
) -> None:
    """A grant is named through its membership, so the membership is what must reach."""
    foreign = Membership.objects.filter(tenant=other_tenant).first()
    assert foreign is not None
    theirs = Grant.objects.create(
        tenant=other_tenant,
        membership=foreign,
        permission="widget.create",
        effect=Grant.Effect.ALLOW,
    )

    with pytest.raises(NotFound):
        delete_grant(tenant=world.tenant, actor=world.owner, grant=theirs)

    assert Grant.objects.filter(pk=theirs.pk).exists()


def test_create_grant_refuses_without_the_key(world: World) -> None:
    with pytest.raises(Forbidden) as refused:
        create_grant(
            tenant=world.tenant,
            actor=world.member,
            membership=world.approver_root_membership,
            permission="widget.create",
            effect=Grant.Effect.ALLOW,
        )

    assert str(refused.value) == authz.refusal_sentence("grant.create")


def test_delete_grant_of_an_allow_is_a_take_back(world: World) -> None:
    handed = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )

    died = delete_grant(tenant=world.tenant, actor=world.owner, grant=handed)

    assert died.permission == "widget.approve"
    assert died.audit_object == (Grant._meta.label, died.grant_id)
    assert not Grant.objects.for_tenant(world.tenant).filter(pk=handed.pk).exists()


def test_delete_grant_of_a_withhold_is_a_hand_out(world: World) -> None:
    """Removing a withhold GIVES the key back, so the hand-out rule applies."""
    withheld = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.create",
        effect=Grant.Effect.WITHHOLD,
    )
    _grant(world.approver_root_membership, "grant.delete", Grant.Effect.ALLOW)
    _grant(world.approver_root_membership, "widget.create", Grant.Effect.WITHHOLD)
    acting = _actor(world, world.approver_root_membership, world.root)

    with pytest.raises(Forbidden) as refused:
        delete_grant(tenant=world.tenant, actor=acting, grant=withheld)

    assert authz.refusal_sentence("widget.create") in str(refused.value)


def test_every_write_leaves_an_audit_row_whose_input_names_the_key_and_the_effect(
    world: World,
) -> None:
    from apps.core.audit import AuditEntry

    create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )

    row = (
        AuditEntry.objects.for_tenant(world.tenant)
        .filter(action="core.create_grant")
        .order_by("-created_at")
        .first()
    )
    assert row is not None
    recorded = row.input
    assert recorded["permission"] == "widget.approve"
    assert recorded["effect"] == "allow"


def test_a_rolled_back_grant_leaves_no_event_row(world: World, monkeypatch: Any) -> None:
    """C2: the emit is INSIDE the transaction, so a failure after it writes nothing.

    The failure is planted on the structured log line that follows `_publish` —
    the last statement in `create_grant`'s body — because that is the only seam
    downstream of the emit and upstream of the commit. Planting it there rather
    than making a production branch failable is the point: nothing in the
    service exists for this test's benefit.
    """
    from apps.core.services import grants
    from apps.core.services._hub import log as real
    from apps.events.models import Event

    class ExplodeAfterThePublish:
        def info(self, name: str, **kwargs: Any) -> None:
            if name == "core.grant.created":
                raise RuntimeError("after the emit")
            real.info(name, **kwargs)

        def __getattr__(self, attribute: str) -> Any:
            return getattr(real, attribute)

    monkeypatch.setattr(grants, "log", ExplodeAfterThePublish())
    before = Event.objects.count()

    with pytest.raises(RuntimeError):
        create_grant(
            tenant=world.tenant,
            actor=world.owner,
            membership=world.member_membership,
            permission="widget.create",
            effect=Grant.Effect.WITHHOLD,
        )

    assert (
        not Grant.objects.for_tenant(world.tenant)
        .filter(membership=world.member_membership)
        .exists()
    )
    assert Event.objects.count() == before


def test_core_emits_through_the_bridge_and_never_imports_events() -> None:
    """The import half is `test_bridge.py`'s; this is the emit half."""
    import pathlib

    package = sorted(pathlib.Path("apps/core/services").glob("*.py"))
    source = "".join(source_text(path) for path in package)
    assert "from apps.events" not in source
    assert "bridge.listener(bridge.EMIT)" in source


def test_set_role_emits_membership_updated_inside_the_transaction(world: World) -> None:
    from apps.core import events

    said: list[tuple[str, dict[str, Any]]] = []

    from apps.core import bridge

    def recorder(*, name: str, tenant: Tenant, payload: dict[str, Any], **rest: Any) -> Any:
        said.append((name, payload))
        return None

    previous = bridge.find(bridge.EMIT)
    bridge.register(bridge.EMIT, recorder)
    try:
        set_role(
            tenant=world.tenant,
            membership=world.member_membership,
            role="admin",
            actor=world.owner,
        )
    finally:
        # Put back exactly what was there. Popping unconditionally UNREGISTERED
        # the real `events.emit` for every test that ran after this one in the
        # same worker — `test_introspect.py::test_it_reports_the_bridge_registry`
        # caught it, which is what that census is for.
        if previous is None:
            bridge._registry.pop(bridge.EMIT, None)
        else:
            bridge.register(bridge.EMIT, previous)

    assert [name for name, _ in said] == [events.MEMBERSHIP_UPDATED]
    assert said[0][1]["role"] == "admin"


def test_the_six_event_names_reach_introspect() -> None:
    from apps.core import events

    names = {
        events.ROLE_CREATED,
        events.ROLE_UPDATED,
        events.ROLE_DELETED,
        events.MEMBERSHIP_UPDATED,
        events.GRANT_CREATED,
        events.GRANT_DELETED,
    }
    assert names == {
        "core.role.created",
        "core.role.updated",
        "core.role.deleted",
        "core.membership.updated",
        "core.grant.created",
        "core.grant.deleted",
    }


# --- ADR core-26 · each payload is its row's `Out`, at v1 -----------------------


def _recorded(world: World, name: str) -> tuple[int, dict[str, Any]]:
    """The newest recorded event of `name`: its `v`, and its payload without the `v` key."""
    from apps.events.models import Event

    row = Event.objects.for_tenant(world.tenant).filter(name=name).order_by("-created_at").first()
    assert row is not None, name
    payload = dict(row.payload)
    payload.pop("v", None)
    return int(row.v), payload


def _published(out: Any) -> dict[str, Any]:
    """`event_payload(out)` as the REST door renders it — what `emit` stores."""
    from apps.core.schemas import event_payload
    from config.api import as_the_door_renders

    rendered: dict[str, Any] = as_the_door_renders(event_payload(out))
    return rendered


def _role_out(world: World, key: str) -> Any:
    """The role as the role doors answer it."""
    from apps.core.schemas import RoleOut
    from apps.core.selectors import get_role

    return RoleOut.of(get_role(tenant=world.tenant, key=key, actor=world.owner))


def _make_role(world: World, key: str) -> Role:
    return create_role(
        tenant=world.tenant,
        actor=world.owner,
        key=key,
        name="Reviewer",
        description="reads and approves",
        permissions=frozenset({"widget.approve", "widget.read"}),
    )


def test_role_created_carries_the_role_out_at_v1(world: World) -> None:
    from apps.core import events

    _make_role(world, "reviewer")

    assert _recorded(world, events.ROLE_CREATED) == (
        1,
        _published(_role_out(world, "reviewer")),
    )


def test_role_updated_by_a_rename_carries_the_role_out_at_v1(world: World) -> None:
    from apps.core import events

    role = Role.objects.for_tenant(world.tenant).get(key="approver")
    update_role(tenant=world.tenant, actor=world.owner, role=role, name="Signer")

    assert _recorded(world, events.ROLE_UPDATED) == (
        1,
        _published(_role_out(world, "approver")),
    )


def test_role_updated_by_a_collection_carries_the_role_out_at_v1(world: World) -> None:
    """A declared role's collection: `default_permissions` and the delta ride on the payload."""
    from apps.core import events

    set_role_collection(
        tenant=world.tenant,
        actor=world.owner,
        role_key="member",
        permissions=authz.defaults_for("member") | {"organization.create"},
    )

    kind, payload = _recorded(world, events.ROLE_UPDATED)
    assert (kind, payload) == (1, _published(_role_out(world, "member")))
    assert _platform_added(payload) == ["organization.create"]


def _platform_added(payload: dict[str, Any]) -> list[str]:
    """The keys a role event's `added` names that no product app declares or owns, sorted."""
    return platform_keys(payload["added"])


def test_a_product_apps_keys_are_outside_the_added_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planted: the worked apps read as a product's, and their key leaves the platform's `added`."""
    from apps.core.tests import permissions_world

    payload = {"added": ["widget.create", "organization.create"]}
    assert _platform_added(payload) == ["organization.create", "widget.create"]
    platform = permissions_world.platform_labels() - {"example", "example_portal"}
    monkeypatch.setattr(permissions_world, "platform_labels", lambda: platform)
    assert _platform_added(payload) == ["organization.create"]


def test_role_deleted_carries_the_role_out_as_it_was_at_v1(world: World) -> None:
    from apps.core import events

    role = _make_role(world, "reviewer")
    before = _published(_role_out(world, "reviewer"))

    delete_role(tenant=world.tenant, actor=world.owner, role=role)

    assert _recorded(world, events.ROLE_DELETED) == (1, before)


MEMBERSHIP_EVENT_KEYS = frozenset(
    {"id", "user_id", "organization_id", "role", "is_default", "created_at", "updated_at"}
)


def test_membership_updated_carries_ids_only_at_v1(world: World) -> None:
    """`MembershipOut` through the strip: its `personal` field gone, the seven keys kept."""
    from apps.core import events
    from apps.core.schemas import MembershipOut

    changed = set_role(
        tenant=world.tenant,
        membership=world.member_membership,
        role="admin",
        actor=world.owner,
    )

    kind, payload = _recorded(world, events.MEMBERSHIP_UPDATED)
    assert set(payload) == MEMBERSHIP_EVENT_KEYS
    assert "user_email" not in payload
    door = _published(MembershipOut.from_orm(changed))
    assert (kind, payload) == (1, {key: door[key] for key in MEMBERSHIP_EVENT_KEYS})


def test_grant_created_carries_the_grant_out_at_v1(world: World) -> None:
    from apps.core import events
    from apps.core.schemas import GrantOut

    grant = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )

    assert _recorded(world, events.GRANT_CREATED) == (
        1,
        _published(GrantOut.of(grant, sentence=authz.refusal_sentence("widget.approve"))),
    )


def test_grant_deleted_carries_the_grant_out_as_it_was_at_v1(world: World) -> None:
    from apps.core import events
    from apps.core.schemas import GrantOut

    grant = create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.create",
        effect=Grant.Effect.WITHHOLD,
    )
    before = _published(GrantOut.of(grant, sentence=authz.refusal_sentence("widget.create")))

    delete_grant(tenant=world.tenant, actor=world.owner, grant=grant)

    assert _recorded(world, events.GRANT_DELETED) == (1, before)


# --- P4.6 · the rename command -------------------------------------------------


def test_rename_permission_rewrites_planted_rows_and_refuses_an_undeclared_target(
    world: World, capsys: Any
) -> None:
    renames = authz.renamed_permissions()
    assert renames, "the tree declares at least one rename"
    old, new = sorted(renames.items())[0]

    RolePermission.objects.create(
        tenant=world.tenant,
        role_key="approver",
        permission=old,
        effect=RolePermission.Effect.INCLUDE,
    )
    Grant.objects.create(
        tenant=world.tenant,
        membership=world.member_membership,
        permission=old,
        effect=Grant.Effect.ALLOW,
    )

    call_command("rename_permission", old, new)
    printed = capsys.readouterr().out

    assert "1" in printed
    assert RolePermission.objects.filter(permission=new).count() == 1
    assert Grant.objects.filter(permission=new).count() == 1

    with pytest.raises(SystemExit) as refused:
        call_command("rename_permission", old, "gizmo.polish")
    assert refused.value.code == 2


# --- P4.8 · the kick from the two new narrowing services -----------------------


def test_a_withheld_read_kicks_that_person(world: World, monkeypatch: Any) -> None:
    kicked = _capture_kicks(monkeypatch)

    create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.read",
        effect=Grant.Effect.WITHHOLD,
    )

    assert kicked == [world.member_membership.user_id]


def test_a_withheld_write_kicks_nobody(world: World, monkeypatch: Any) -> None:
    kicked = _capture_kicks(monkeypatch)

    create_grant(
        tenant=world.tenant,
        actor=world.owner,
        membership=world.member_membership,
        permission="widget.create",
        effect=Grant.Effect.WITHHOLD,
    )

    assert kicked == []


def test_an_exclude_of_a_read_on_a_declared_role_kicks_every_holder_once(
    world: World, monkeypatch: Any
) -> None:
    kicked = _capture_kicks(monkeypatch)
    wanted = authz.defaults_for("member") - {"widget.read"}

    set_role_collection(
        tenant=world.tenant,
        actor=world.owner,
        role_key="member",
        permissions=frozenset(wanted),
    )

    # The clerk holds `member` at A, so it is a holder too.
    assert sorted(kicked) == sorted(
        {
            world.member_membership.user_id,
            world.approver_root_membership.user_id,
            world.clerk_membership.user_id,
        }
    )


def _capture_kicks(monkeypatch: Any) -> list[Any]:
    """Every `close_sockets_on_commit` this test caused, by user id, in order."""
    from apps.core.services import grants, memberships, organizations

    seen: list[Any] = []

    def record(*, user_id: Any, reason: str) -> None:
        seen.append(user_id)

    for module in (organizations, memberships, grants):
        monkeypatch.setattr(module, "close_sockets_on_commit", record)
    return seen


# --- P4.9 · a role may say `"*.read"` ------------------------------------------


def test_a_pattern_expands_to_keys_at_write_time(world: World) -> None:
    reads = {key for key, word in authz.vocabulary().items() if word.is_read}

    create_role(
        tenant=world.tenant,
        actor=world.owner,
        key="reader",
        name="Reader",
        permissions=frozenset({"*.read", "widget.approve"}),
    )

    written = set(
        RolePermission.objects.for_tenant(world.tenant)
        .filter(role_key="reader")
        .values_list("permission", flat=True)
    )
    assert written == reads | {"widget.approve"}
    assert "*.read" not in written


def test_a_pattern_that_matches_nothing_is_invalid(world: World) -> None:
    with pytest.raises(Invalid) as refused:
        create_role(
            tenant=world.tenant,
            actor=world.owner,
            key="reader",
            name="Reader",
            permissions=frozenset({"gizmo.*"}),
        )

    assert "gizmo.*" in " ".join(refused.value.errors["permissions"])


# --- The virtual kind and the ceiling -----------------------------------------


def test_a_virtual_kind_key_is_in_no_role_collection_including_the_declared_ones(
    world: World,
) -> None:
    """**A kind with no row is in NOBODY's collection, and that is one rule.**

    `VIRTUAL_KINDS` names kinds with no table behind them — the installation
    itself — and `collection()` has always excluded them from `owner`, for the
    reason the owner branch states: a virtual kind names no row anybody can be
    given authority over. That reason has nothing to do with WHICH role is
    asking, and the exclusion was wired on the owner branch alone.

    It could not be seen while the kind had no keys on it (it was declared with
    zero, deliberately), and it inverts the ceiling the moment one lands: a
    declared role picks the key up — `admin` by its `("*",)` pattern, every
    declared role by the compat residue when the key carries a predicate — while
    `owner` does not. `_refuse_handing_out` then computes
    `collection(role) - collection(owner)` as NON-EMPTY, and the escalation wall
    refuses **an owner** granting `admin` or `member`: every road that makes a
    membership, in every app.

    So the property is symmetry, asserted over the whole virtual population
    rather than over the one key that found it.
    """
    words = authz.vocabulary()
    virtual = {action for action, word in words.items() if word.kind in authz.VIRTUAL_KINDS}
    assert virtual, "no key on a virtual kind — this test has stopped measuring"

    owner_collection = authz.collection(world.tenant, authz.OWNER_ROLE)
    assert virtual & owner_collection == set()
    for role_key in authz.role_declarations():
        assert virtual & authz.collection(world.tenant, role_key) == set(), role_key


def test_an_owner_may_still_grant_a_declared_role_when_a_virtual_kind_key_exists(
    world: World,
) -> None:
    """The defect's own road, driven: the ceiling refused the person at the top.

    The assertion above is the mechanism; this is what it cost. An owner is the
    most authorized person a tenant has, `admin` is strictly beneath them, and a
    wall that refuses that grant has stopped being a ceiling and become a floor
    nobody can stand on. Driven through `add_membership` rather than through
    `_refuse_handing_out` because the failure reached every caller of the
    service, not the helper.
    """
    membership = add_membership(
        user=_person(world.roleless),
        tenant=world.tenant,
        organization=world.root,
        role="admin",
        actor=world.owner,
    )

    assert membership.role == "admin"
    assert membership.organization_id == world.root.pk


def test_an_owner_may_create_a_role_holding_everything_and_it_holds_no_virtual_key(
    world: World,
) -> None:
    """**`"*"` must not expand onto a kind with no table.** Two failures, one cause.

    `_expand_patterns` turned a pattern into ROWS by matching the whole
    vocabulary minus the reserved keys, so once a virtual kind had a key on it
    `"*"`, `"*.configure"` and `deployment.*` all expanded to include it. Both
    ways out of that were wrong:

    * a person calling this was refused — the expansion held a key
      `collection(OWNER_ROLE)` does not, so `_refuse_handing_out` said an OWNER
      may not hand out what they do not hold, for the most ordinary role there
      is;
    * a `system` actor, which passes the wall by design, WROTE the include row
      — and a stored row carrying a virtual key puts that key back into
      `collection()` for everybody holding the role, which re-inverts the
      escalation wall permanently and outlives the process that made it.

    So the expansion is the fix's home, and the assertion is both halves: the
    call succeeds, and the rows it wrote carry nothing virtual.
    """
    words = authz.vocabulary()
    virtual = {action for action, word in words.items() if word.kind in authz.VIRTUAL_KINDS}
    assert virtual, "no key on a virtual kind — this test has stopped measuring"

    create_role(
        tenant=world.tenant,
        actor=world.owner,
        key="everything",
        name="Everything",
        permissions=frozenset({"*"}),
    )

    written = set(
        RolePermission.objects.for_tenant(world.tenant)
        .filter(role_key="everything")
        .values_list("permission", flat=True)
    )
    assert written, "the pattern expanded to nothing — the test would be vacuous"
    assert written & virtual == set(), sorted(written & virtual)
    assert authz.collection(world.tenant, "everything") & virtual == set()


def test_a_virtual_kind_key_named_literally_in_a_role_is_refused_as_virtual(
    world: World,
) -> None:
    """A pattern may not reach it; a caller who TYPES it gets told why.

    Dropping it silently from the expansion is right — nobody asked for it by
    name. Dropping it silently from a literal list is not: that caller asked a
    question, and a collection that quietly came back one key short is the
    shape somebody debugs for an afternoon. The sentence names the kind as
    virtual and says what decides the key instead.
    """
    virtual_key = sorted(
        action for action, word in authz.vocabulary().items() if word.kind in authz.VIRTUAL_KINDS
    )[0]

    with pytest.raises(Invalid) as refused:
        create_role(
            tenant=world.tenant,
            actor=world.owner,
            key="operator",
            name="Operator",
            permissions=frozenset({virtual_key}),
        )

    sentence = " ".join(refused.value.errors["permissions"])
    assert virtual_key in sentence
    assert "VIRTUAL kind" in sentence
    assert not RolePermission.objects.for_tenant(world.tenant).filter(role_key="operator").exists()


def test_no_declared_roles_defaults_carry_a_virtual_key(world: World) -> None:
    """The declaration's half of the same asymmetry, and the last reader of it.

    `defaults_for` matched patterns against the whole vocabulary, so
    `defaults_for("admin")` yielded a virtual key through `("*",)` while
    `collection()` did not. That is the scopes echo counting a key nobody holds,
    and `set_role_collection` computing a spurious EXCLUDE row against it. Both
    now read `grantable_permissions()`, which is the one place the exclusion
    lives.

    `owner` is deliberately not in this loop: `defaults_for(OWNER_ROLE)` answers
    what the owner role IS — the whole vocabulary — and what an owner may be
    handed is `collection()`, which the test above this one covers.
    """
    virtual = {
        action for action, word in authz.vocabulary().items() if word.kind in authz.VIRTUAL_KINDS
    }
    assert virtual, "no key on a virtual kind — this test has stopped measuring"

    assert authz.role_declarations(), "no declared role — the loop would be vacuous"
    for role_key in sorted(authz.role_declarations()):
        assert authz.defaults_for(role_key) & virtual == set(), role_key
        assert authz.collection(world.tenant, role_key) & virtual == set(), role_key
