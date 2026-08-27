"""Roles are data, policies are code — and silence means no.

The two layers are tested separately because they fail differently: a role
mistake lets the wrong *person* through, a missing policy lets the wrong
*action* through. The last test is the one that matters most: an action nobody
has written a rule for is refused to a member rather than allowed.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import (
    action_prose,
    allows,
    declared_roles,
    is_read,
    membership_for,
    policies,
    refusal_sentence,
    require,
)
from apps.core.exceptions import Forbidden
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership, set_role

pytestmark = pytest.mark.django_db


# --- Roles, as the fallback --------------------------------------------------


def test_the_first_membership_of_a_tenant_is_its_owner(tenant: Tenant, nomad: User) -> None:
    """Otherwise a tenant is created that nobody, including its creator, can run.

    Built here rather than taken from the `owner` fixture: that fixture names
    its role explicitly, so asserting against it would only prove that
    `add_membership` writes down what it is told. The **default** is the thing
    under test, and it is only observable on a tenant with nobody in it yet.
    """
    assert not Membership.objects.filter(tenant=tenant).exists()

    membership = add_membership(user=nomad, tenant=tenant, actor=system_actor(tenant=tenant))

    assert membership.role == Membership.Role.OWNER
    assert membership.is_privileged


def test_everybody_after_the_first_is_a_member(tenant: Tenant, nomad: User, root: User) -> None:
    add_membership(user=nomad, tenant=tenant, actor=system_actor(tenant=tenant))
    second = add_membership(user=root, tenant=tenant, actor=system_actor(tenant=tenant))

    assert second.role == Membership.Role.MEMBER
    assert not second.is_privileged


def test_an_explicit_role_always_wins_over_the_default(tenant: Tenant, nomad: User) -> None:
    """Which is what every fixture in `apps/conftest.py` relies on."""
    membership = add_membership(
        user=nomad, tenant=tenant, role=Membership.Role.MEMBER, actor=system_actor(tenant=tenant)
    )
    assert membership.role == Membership.Role.MEMBER


def test_the_shared_fixtures_do_not_depend_on_the_order_they_are_asked_for(
    member: User, admin_member: User, owner: User, tenant: Tenant
) -> None:
    """`member` is named *first* here, and `owner` is still the owner.

    pytest builds fixtures in the order a signature names them, so while
    `apps/conftest.py` left the role to `add_membership`'s "first membership
    wins" default, this signature produced a member-owner and an owner-member —
    and every authorization test in the repository quietly depended on the
    order its arguments happened to be written in.
    """
    roles = {
        m.user_id: m.role for m in Membership.objects.filter(tenant=tenant).select_related(None)
    }
    assert roles[owner.pk] == Membership.Role.OWNER
    assert roles[admin_member.pk] == Membership.Role.ADMIN
    assert roles[member.pk] == Membership.Role.MEMBER


def test_an_owner_may_do_anything_in_their_tenant(owner_actor: Actor) -> None:
    assert allows(owner_actor, "invoice.void")


def test_an_admin_may_too(admin_actor: Actor) -> None:
    assert allows(admin_actor, "invoice.void")


def test_a_member_may_read_and_may_not_write(member_actor: Actor) -> None:
    assert allows(member_actor, "invoice.view")
    assert allows(member_actor, "invoice.list")
    assert not allows(member_actor, "invoice.void")


def test_somebody_outside_the_tenant_may_do_nothing_in_it(stranger: User, tenant: Tenant) -> None:
    """No membership, no answer — the same rule tenancy fails closed on."""
    outsider = actor_for(user=stranger, tenant=tenant)
    assert membership_for(outsider) is None
    assert not allows(outsider, "invoice.view")


def test_the_system_acts_for_the_product_itself(tenant: Tenant) -> None:
    """A workflow has no membership to consult; the scoped manager still holds."""
    assert allows(system_actor(tenant), "invoice.void")


def test_changing_a_role_changes_the_answer(
    tenant: Tenant, member: User, member_actor: Actor
) -> None:
    membership = Membership.objects.get(user=member, tenant=tenant)
    assert not allows(member_actor, "invoice.void")
    set_role(
        tenant=tenant,
        membership=membership,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    assert allows(member_actor, "invoice.void")


def test_read_verbs_are_the_named_ones_only() -> None:
    assert is_read("widget.view") and is_read("widget.list")
    assert not is_read("widget.update")
    assert not is_read("widget.viewport")


# --- Policies, discovered ----------------------------------------------------


def test_the_example_apps_policies_are_found_without_being_registered() -> None:
    found = policies()
    assert "widget.create" in found
    assert "widget.update" in found
    assert "widget.delete" in found


def test_a_policy_beats_the_role_default(
    tenant: Tenant, member_actor: Actor, owner_actor: Actor
) -> None:
    """`widget.create` is a write, and the policy lets a plain member do it."""
    assert not allows(member_actor, "invoice.create")  # no policy: refused
    assert allows(member_actor, "widget.create")  # policy: allowed


def test_require_raises_rather_than_returning_false(member_actor: Actor) -> None:
    with pytest.raises(Forbidden) as raised:
        require(member_actor, "invoice.void")
    assert raised.value.code == "forbidden"


def test_a_refusal_never_publishes_the_action_name(member_actor: Actor) -> None:
    """The plain-language bar reaches runtime prose too (design-agreements.md,
    2026-08-23; found live by FT-1 as "You may not invitation.create.").

    An action name is how a service asks the question. Publishing it told a
    caller to go and read our source for the answer.
    """
    with pytest.raises(Forbidden) as raised:
        require(member_actor, "invitation.create")
    assert raised.value.detail == "You may not invite people into that organization."
    assert "invitation.create" not in raised.value.detail


def test_an_action_with_no_declared_sentence_still_answers_in_english(
    member_actor: Actor,
) -> None:
    """The fallback humanises rather than leaking the key.

    It is not a substitute for declaring one — it reads badly for a two-word
    verb, which is the nudge — but an undeclared action degrades to a sentence
    and never to a dotted identifier.
    """
    with pytest.raises(Forbidden) as raised:
        require(member_actor, "invoice.void")
    assert raised.value.detail == "You may not void this invoice."


def test_every_declared_action_has_a_sentence() -> None:
    """Discovery on both halves: an app that declares a policy declares its
    prose beside it, in the same file, and `core` owns neither list."""
    missing = sorted(set(policies()) - set(action_prose()))
    assert missing == [], missing


def test_a_three_part_action_drops_the_app_segment() -> None:
    """A caller does not know or care which module the rule lives in."""
    assert refusal_sentence("accounts.user.erase") == "You may not erase that account."
    assert refusal_sentence("zzz.gadget.polish") == "You may not polish this gadget."


def test_require_is_silent_when_it_allows(owner_actor: Actor) -> None:
    require(owner_actor, "invoice.void")  # no exception is the assertion


def test_a_capability_question_with_no_row_needs_a_privileged_role(
    member_actor: Actor, admin_actor: Actor
) -> None:
    """ "Could I edit widgets at all?" cannot be answered yes without a row."""
    assert not allows(member_actor, "widget.update", None)
    assert allows(admin_actor, "widget.update", None)


def test_a_policy_that_says_no_is_final_even_for_an_owner(
    tenant: Tenant, owner_actor: Actor, monkeypatch: Any
) -> None:
    """A policy is not a floor under the role defaults; it replaces them.

    That is what lets a product write "nobody may reopen a closed period, not
    even the owner" and have it mean something.
    """
    from apps.core import authz

    monkeypatch.setitem(policies(), "period.reopen", lambda actor, obj: False)
    try:
        assert not allows(owner_actor, "period.reopen")
    finally:
        authz.reset_policies()


# --- the declaration seam an instrument reads ----------------------------------


def test_an_opaque_predicate_declares_no_roles() -> None:
    """Arbitrary code has no role set to publish, and `None` says so.

    The alternative — inventing one from the verb, which is what `introspect`'s
    old `member_default` column effectively did — publishes a permission that is
    not the one being enforced.
    """
    assert declared_roles(lambda actor, obj: True) is None


def test_a_policy_carrying_a_role_set_publishes_it() -> None:
    """The house form: an app's declaration object, its `can` in `POLICIES`.

    Read through the BOUND METHOD, because that is what the registry holds —
    reading the plain function would find nothing and the seam would report
    every declaration in the tree as opaque.
    """

    class Declaration:
        roles = frozenset({"owner", "admin"})

        def can(self, actor: Any, obj: Any = None) -> bool:
            return True

    assert declared_roles(Declaration().can) == frozenset({"owner", "admin"})


def test_an_attribute_named_roles_that_is_not_a_role_set_is_not_a_declaration() -> None:
    """Strict on purpose.

    A `roles` that is a queryset, a list of rows or a comma-joined string is a
    coincidence of naming and not a declaration; reading one as if it were is
    how an instrument comes to publish a permission nobody declared.
    """

    class JoinedString:
        roles = "owner,admin"

        def can(self, actor: Any, obj: Any = None) -> bool:
            return True

    class ListOfRows:
        roles = [object()]

        def can(self, actor: Any, obj: Any = None) -> bool:
            return True

    assert declared_roles(JoinedString().can) is None
    assert declared_roles(ListOfRows().can) is None


def test_the_live_registry_has_at_least_one_declaring_policy() -> None:
    """Otherwise every assertion above proves a seam nothing in the tree uses.

    Derived from the registry rather than naming `usage.read_report`, so the day
    a second app declares one this keeps meaning what it says.
    """
    declaring = {
        action for action, policy in policies().items() if declared_roles(policy) is not None
    }
    assert declaring, "no policy in this tree declares its roles; the seam is unexercised"
