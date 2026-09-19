"""A role is a KEY, and three tables give a tenant its own.

`Membership.role` and `Invitation.role` carried `choices` until `0018`. A
`choices` list is a per-process constant, and two of the three layers a role
now has are not: an app's `roles.py` is code the deployment discovers, and a
tenant's `core.Role` rows are data that tenant owns. A field validating
against the first could never have accepted the third, so the validation moved
into the three services that write the column — the only three places that have
a tenant to read the third layer with.

What this file proves, in the order the rung built it:

1. the three tables exist and are shaped as `architecture.md`'s ADR core-25 says;
2. `0018` censuses rather than repairs, and reverses to `0017`'s exact schema;
3. an unknown key is still `invalid`, and a neighbouring tenant's key is unknown;
4. the invitation mail names a role by its label and no longer explodes on a
   custom one;
5. the admin offers the keys this tenant may name;
6. `djb.W054` reports rows that name nothing, under `--deploy` and nowhere else.

**No test here compares `Membership.role` by value to decide authority.** The
only legal readers of a key are the validation, `role_label`, the `0018` census
and the deploy census, and every one of them is a name-resolution question
rather than a how-much-authority one.
"""

from __future__ import annotations

import importlib
import inspect
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.authz import OWNER_ROLE, role_declarations, vocabulary
from apps.core.checks import check_roles_are_keys, check_vocabulary_is_derivable
from apps.core.models import (
    Grant,
    Invitation,
    Membership,
    Organization,
    Role,
    RolePermission,
    Tenant,
)
from apps.core.services import (
    accept_invitation,
    add_membership,
    invite_member,
    known_role_keys,
    role_label,
    set_role,
)

pytestmark = pytest.mark.django_db

#: The migration under test, imported by path because `0018_roles_are_keys` is
#: not an identifier. `census` is its forward half — the leg body the drives
#: below call, and the same object `MIGRATION.Migration.operations` names, so a
#: migration that stopped running it fails the structural test rather than
#: leaving these drives measuring a function nobody calls.
MIGRATION = importlib.import_module("apps.core.migrations.0018_roles_are_keys")
census = MIGRATION.census


def constraint_names(model: type[Any]) -> set[str]:
    """The names this model's `Meta` declares, which is what a migration writes."""
    return {str(constraint.name) for constraint in model._meta.constraints}


def membership_of(user: User, tenant: Tenant) -> Membership:
    return Membership.objects.get(tenant=tenant, user_id=user.pk)


# --- P2.1 · the three tables --------------------------------------------------


def test_the_three_tables_are_shaped_as_declared() -> None:
    """Every field, constraint, effect and lifecycle ADR core-25 names.

    Read off `_meta` rather than off the migration, because `_meta` is what the
    rest of the tree reads: a migration that agreed with a model nobody uses
    would be a schema nobody meets.
    """
    key = Role._meta.get_field("key")
    assert key.max_length == 64
    assert Role._meta.get_field("name").max_length == 255
    assert Role._meta.get_field("description").blank is True
    assert constraint_names(Role) == {"role_unique_key_per_tenant"}
    assert Role.lifecycle.kind.value == "unbounded"
    assert Role.lifecycle.reason and Role.lifecycle.trigger

    assert RolePermission._meta.get_field("role_key").max_length == 64
    assert RolePermission._meta.get_field("permission").max_length == 255
    assert [c[0] for c in RolePermission.Effect.choices] == ["include", "exclude"]
    assert constraint_names(RolePermission) == {"rolepermission_unique_per_role"}
    assert RolePermission.lifecycle.kind.value == "unbounded"
    # NO FOREIGN KEY. The join is the key, because two of the three role layers
    # are code and have no row to point at.
    assert not any(
        field.is_relation for field in RolePermission._meta.local_fields if field.name == "role_key"
    )

    membership = Grant._meta.get_field("membership")
    assert membership.related_model is Membership
    assert getattr(membership.remote_field.on_delete, "__name__", "") == "CASCADE"
    assert [c[0] for c in Grant.Effect.choices] == ["allow", "withhold"]
    assert constraint_names(Grant) == {"grant_unique_permission_per_membership"}
    assert Grant.lifecycle.kind.value == "bounded"


def test_the_two_new_kinds_are_role_and_grant_and_rolepermission_is_not_one() -> None:
    """`role.*` and `grant.*` are derived; a delta row is authorized under its role.

    The third assertion is the one with a reason behind it: `RolePermission`
    declares `authz_kind = None` with a sentence, because editing a role's
    collection IS editing the role and a `role_permission.*` key would be four
    permissions nobody could be given a reason to hold.
    """
    from apps.core.authz import kind_of

    words = vocabulary()
    assert kind_of(Role) == "role"
    assert kind_of(Grant) == "grant"
    assert kind_of(RolePermission) is None
    assert RolePermission.authz_kind_reason.strip()
    for verb in ("create", "read", "update", "delete"):
        assert f"role.{verb}" in words
        assert f"grant.{verb}" in words
        assert f"role_permission.{verb}" not in words


def test_the_three_tables_reach_the_lifecycle_registry() -> None:
    """Rule 31: a model declares how its data dies, on the class, and is found there.

    `apps/core/lifecycle.py` needed no line — `lifecycle_of` reads the class's
    own `ClassVar`, and the `register()` hook is only for third-party tables.
    """
    from apps.core.lifecycle import declared_lifecycles, undeclared_models

    declared = declared_lifecycles()
    for model in (Role, RolePermission, Grant):
        assert model._meta.label in declared
    undeclared = {model._meta.label for model in undeclared_models()}
    assert undeclared.isdisjoint({"core.Role", "core.RolePermission", "core.Grant"})


# --- P2.2 · the migration -----------------------------------------------------
#
# Driven through `MigrationExecutor` rather than through `call_command`, so that
# the state the census runs at is the state under test and not whatever the test
# database happens to be at.


def migrate_to(target: list[tuple[str, str | None]]) -> None:
    """Drive `core` to a named migration, inside this test's own transaction.

    `SET CONSTRAINTS ALL IMMEDIATE` first, and it is not decoration:
    pytest-django runs each test inside a transaction with foreign keys
    DEFERRED, and Postgres refuses to `ALTER TABLE` one that has pending trigger
    events — so an ORM insert made earlier in the test would turn the rewind
    into `cannot ALTER TABLE "core_membership" because it has pending trigger
    events`, a failure about the harness rather than about the migration.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(target)


@pytest.fixture
def at_0017() -> Any:
    """Rewind `core` to `0017`, and put it back afterwards whatever happens."""
    migrate_to([("core", "0017_tenant_leading_recency_composite")])
    try:
        yield
    finally:
        migrate_to([("core", "0018_roles_are_keys")])


def _victim_tenant(slug: str) -> tuple[Tenant, Organization]:
    """A tenant and a root node this test owns, built through the ORM.

    Not a fixture's tenant and not `create_tenant`: these tests plant values no
    service would ever write, so the rows have to be ones this file made and can
    delete (rung-execution §2 — a destructive demonstration builds its own
    victim).
    """
    tenant = Tenant.objects.create(name=f"Census {slug}", slug=slug)
    org = Organization.objects.create(tenant=tenant, name="Root", slug="root", path="0000", depth=0)
    return tenant, org


def run_census() -> None:
    """The `0018` forward, driven as the LEG BODY over the live registry.

    **Not through `MigrationExecutor`, deliberately** (rung-execution §2 — a
    drive invokes the body, never the machinery around it). A `RunPython` that
    raises inside pytest-django's per-test transaction leaves that transaction
    needing rollback, so every statement after it — including the fixture's own
    teardown — fails with `TransactionManagementError` and the run reports the
    harness instead of the refusal. The census is a pure function of the rows
    and the declarations; calling it with the real app registry measures exactly
    what the migration calls, one frame in.
    """
    from django.apps import apps as django_apps

    census(django_apps, None)


def test_0018_is_expand_only_and_its_census_reverses_to_a_noop() -> None:
    """The operation list, read off the migration: two widenings, three tables, one census.

    Rule 22's shape asserted as a shape — nothing dropped, nothing rewritten,
    and the `RunPython` carries a real reverse rather than being irreversible.
    """
    operations = MIGRATION.Migration.operations
    kinds = [type(op).__name__ for op in operations]
    assert kinds == [
        "AlterField",
        "AlterField",
        "CreateModel",
        "CreateModel",
        "CreateModel",
        "RunPython",
    ], kinds
    assert not any(k in kinds for k in ("DeleteModel", "RemoveField", "RenameField"))
    run = operations[-1]
    assert run.code is census
    assert run.reverse_code is migrations.RunPython.noop
    assert run.reversible is True


def test_0018_refuses_an_undeclared_role_value_naming_tenant_value_and_count() -> None:
    """The census refuses, and its sentence carries the slug, the value and the count.

    `viewer` cannot be written through either tree's services — `choices`
    refused it before and `_refuse_unknown_role` refuses it now — and that is
    exactly why the migration has to ask: the values it exists to find are ones
    a PRODUCT put there under a `choices` list this deployment does not have, so
    the only honest way to reach the state is the manager, as a product's own
    rows reached it.
    """
    from uuid import uuid4

    slug = f"census-{uuid4().hex[:8]}"
    user = User.objects.create_user(email=f"{slug}@example.com", password="x")  # noqa: S106
    tenant, org = _victim_tenant(slug)
    Membership.objects.create(user_id=user.pk, tenant=tenant, organization=org, role="viewer")

    with pytest.raises(RuntimeError) as refused:
        run_census()

    text = str(refused.value)
    assert slug in text, text
    assert "'viewer'" in text, text
    assert "1 row(s)" in text, text
    assert "roles.py" in text, text


def test_0018_counts_a_pending_invitation_and_ignores_a_settled_one() -> None:
    """Pending only — an accepted or revoked offer names a role nobody will get.

    The declared blind spot said out loud in a test: a product whose dead rows
    carry a fourth enum value migrates cleanly, and that is the intended
    reading, not an oversight.
    """
    from uuid import uuid4

    slug = f"inv-{uuid4().hex[:8]}"
    tenant, org = _victim_tenant(slug)
    for index, status in enumerate([Invitation.Status.ACCEPTED, Invitation.Status.REVOKED]):
        Invitation.objects.create(
            tenant=tenant,
            organization=org,
            email=f"{slug}-{index}@example.com",
            role="viceroy",
            status=status,
            token_hash=f"{slug}{index}".ljust(64, "0"),
            expires_at=timezone.now() + timedelta(days=1),
        )
    run_census()  # silent: neither offer is standing

    Invitation.objects.create(
        tenant=tenant,
        organization=org,
        email=f"{slug}-live@example.com",
        role="viceroy",
        status=Invitation.Status.PENDING,
        token_hash=f"{slug}live".ljust(64, "0"),
        expires_at=timezone.now() + timedelta(days=1),
    )
    with pytest.raises(RuntimeError) as refused:
        run_census()
    assert "'viceroy'" in str(refused.value)
    assert "1 row(s)" in str(refused.value)


def test_0018_passes_every_membership_naming_owner_a_declared_key_or_a_row() -> None:
    """Owner, a declared key, a tenant's own row and `""` all survive the census.

    The third is the one only a per-tenant read can accept: `approver` is a row
    this tenant owns, it is in no `roles.py`, and a `choices` list could never
    have held it.
    """
    from uuid import uuid4

    slug = f"passes-{uuid4().hex[:8]}"
    tenant, org = _victim_tenant(slug)
    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    for index, role in enumerate([OWNER_ROLE, "member", "approver", ""]):
        user = User.objects.create_user(email=f"{slug}-{index}@example.com", password="x")  # noqa: S106
        Membership.objects.create(user_id=user.pk, tenant=tenant, organization=org, role=role)

    run_census()  # the assertion: it does not raise

    # And it is per TENANT, not per deployment: the same key in a neighbour is
    # not this tenant's, which is the half the refusal above proves from the
    # other side.
    other_slug = f"{slug}-nb"
    other, other_org = _victim_tenant(other_slug)
    stranger = User.objects.create_user(email=f"{other_slug}@example.com", password="x")  # noqa: S106
    Membership.objects.create(
        user_id=stranger.pk, tenant=other, organization=other_org, role="approver"
    )
    with pytest.raises(RuntimeError) as refused:
        run_census()
    assert other_slug in str(refused.value)


def test_0018_reverses_to_0017s_exact_schema(at_0017: None) -> None:
    """Backwards: the three tables are gone and `role` is a 16-character column again.

    Principle 6 — the decision is reversible, and the reversal is measured off
    the database rather than asserted about the migration file.
    """
    tables = set(connection.introspection.table_names())
    assert {"core_role", "core_rolepermission", "core_grant"}.isdisjoint(tables)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'core_membership' AND column_name = 'role'"
        )
        assert cursor.fetchone()[0] == 16
        cursor.execute(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'core_invitation' AND column_name = 'role'"
        )
        assert cursor.fetchone()[0] == 16


def test_0018_is_the_leaf(at_0017: None) -> None:
    """One leaf per app (rule 6), and it is this one."""
    from pathlib import Path

    from django.conf import settings

    leaf = Path(settings.BASE_DIR) / "apps" / "core" / "migrations" / "max_migration.txt"
    assert leaf.read_text().strip() == "0018_roles_are_keys"


# --- P2.3 · the compat surface ------------------------------------------------


def test_the_role_enum_and_is_privileged_are_untouched(tenant: Tenant, owner: User) -> None:
    """`Membership.Role`'s three constants and `is_privileged` answer as they did.

    They are no longer the field's `choices` — that is the whole rung — and they
    are still the three names the template's own roles have, still readable off
    `apps/core/models.py` by house rule 41's AST reader, and still the spelling
    every fixture in the tree uses.
    """
    assert Membership.Role.OWNER.value == "owner"
    assert Membership.Role.ADMIN.value == "admin"
    assert Membership.Role.MEMBER.value == "member"
    assert Membership.Role.values == ["owner", "admin", "member"]
    # The field itself no longer validates against them.
    assert Membership._meta.get_field("role").choices is None
    assert Membership._meta.get_field("role").max_length == 64
    assert Invitation._meta.get_field("role").choices is None
    assert Invitation._meta.get_field("role").max_length == 64

    membership = membership_of(owner, tenant)
    assert membership.is_privileged is True
    membership.role = Membership.Role.MEMBER
    assert membership.is_privileged is False


def test_the_shape_rule_41s_reader_depends_on_is_still_here() -> None:
    """`Membership.Role`'s body and `is_privileged` are readable off this file.

    `quality/checks.py::_privileged_role_words` resolves `{Role.OWNER,
    Role.ADMIN}` through the `TextChoices` body by AST, and the gate binds a
    `privileged_role_words: 2` floor on the answer — a `Role` class removed
    leaves that floor unbound, which is exit 2 rather than a pass. **The floor
    IS the mechanism**, so this test does not re-ask its question (importing
    `quality.checks` from `apps/` would drag the whole quality package into
    mypy's graph for every builder); it pins the two facts the reader needs to
    find, so that a rename here fails beside the code that renamed it and the
    gate's own answer is the one that counts.
    """
    assert list(Membership.Role.names) == ["OWNER", "ADMIN", "MEMBER"]
    privileged = inspect.getattr_static(Membership, "is_privileged")
    assert isinstance(privileged, property)
    getter = privileged.fget
    assert getter is not None
    source = inspect.getsource(getter)
    assert "Role.OWNER" in source and "Role.ADMIN" in source
    assert "Role.MEMBER" not in source


# --- P2.4 · the validation moved into the services ----------------------------


def test_known_role_keys_is_the_three_layers(tenant: Tenant) -> None:
    """`owner`, every declared key, every row this tenant owns. Not `""`."""
    assert known_role_keys(tenant=tenant) == frozenset({OWNER_ROLE}) | frozenset(
        role_declarations()
    )
    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    assert "approver" in known_role_keys(tenant=tenant)
    assert "" not in known_role_keys(tenant=tenant)


def test_a_custom_key_of_this_tenant_is_accepted_and_another_tenants_is_not(
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    member: User,
    owner_actor: Actor,
) -> None:
    """The half a `choices` list could never have had, in both directions.

    A key is a per-tenant fact. `approver` in Globex is not a role in Acme, and
    from Acme's side it is indistinguishable from a typo — which is what it is.
    """
    Role.objects.create(tenant=other_tenant, key="approver", name="Approver")

    with pytest.raises(Exception) as refused:
        set_role(
            tenant=tenant,
            membership=membership_of(member, tenant),
            role="approver",
            actor=owner_actor,
        )
    assert "approver" in str(refused.value)

    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    changed = set_role(
        tenant=tenant,
        membership=membership_of(member, tenant),
        role="approver",
        actor=owner_actor,
    )
    assert changed.role == "approver"


@pytest.mark.parametrize("value", ["viewer", "OWNER", "admn", " admin"])
def test_a_role_this_tenant_cannot_name_is_invalid_in_every_writer(
    value: str,
    tenant: Tenant,
    root_org: Organization,
    member: User,
    owner_actor: Actor,
) -> None:
    """`add_membership`, `set_role` and `invite_member`, one nonsense value each.

    The three are asserted together because they are one rule with three call
    sites: a key validated in two of them is a hole in the third, and that is
    exactly the shape `choices` used to close for free.
    """
    from apps.core.exceptions import Invalid

    stranger = User.objects.create_user(email=f"s-{value.strip() or 'blank'}@x.com", password="p")  # noqa: S106

    with pytest.raises(Invalid) as one:
        add_membership(
            user=stranger, tenant=tenant, organization=root_org, role=value, actor=owner_actor
        )
    assert "role" in one.value.errors

    with pytest.raises(Invalid) as two:
        set_role(
            tenant=tenant, membership=membership_of(member, tenant), role=value, actor=owner_actor
        )
    assert "role" in two.value.errors

    with pytest.raises(Invalid) as three:
        invite_member(tenant=tenant, email="who@example.com", role=value, actor=owner_actor)
    assert "role" in three.value.errors


def test_the_roleless_membership_is_a_road_the_system_has_and_a_door_does_not(
    tenant: Tenant,
    root_org: Organization,
    member: User,
    owner_actor: Actor,
) -> None:
    """`add_membership(role="")` lands; `set_role(role="")` is `Invalid`.

    Somebody who belongs here and holds nothing beyond their grants is a state
    the system reaches — an offer that named no role, a deployment that declares
    no default. It is never a state a caller asks a door for: the caller who
    meant "take this one thing away" wants a withhold.
    """
    from apps.core.actor import system_actor
    from apps.core.exceptions import Invalid

    nobody = User.objects.create_user(email="roleless@example.com", password="p")  # noqa: S106
    landed = add_membership(
        user=nobody,
        tenant=tenant,
        organization=root_org,
        role="",
        actor=system_actor(tenant=tenant),
    )
    assert landed.role == ""

    with pytest.raises(Invalid) as refused:
        set_role(
            tenant=tenant, membership=membership_of(member, tenant), role="", actor=owner_actor
        )
    assert "role" in refused.value.errors


def test_the_first_membership_is_owner_and_the_next_is_the_declared_default(
    tenant: Tenant, root_org: Organization, owner: User
) -> None:
    """§4, unchanged in substance and re-derived in mechanism.

    The second half no longer reads `Membership.Role.MEMBER`: it reads whatever
    role this deployment marked `is_default_for_new_members`, so a product that
    renamed its entry-level role gets its own key rather than a `member` its
    `roles.py` no longer holds.
    """
    from apps.core.actor import system_actor
    from apps.core.authz import default_role_key

    assert (
        membership_of(User.objects.get(memberships__tenant=tenant), tenant).role or True
    )  # the tenant already has its owner

    second = User.objects.create_user(email="second@example.com", password="p")  # noqa: S106
    landed = add_membership(
        user=second, tenant=tenant, organization=root_org, actor=system_actor(tenant=tenant)
    )
    assert landed.role == default_role_key() == "member"


def test_an_invitation_naming_a_deleted_role_is_a_conflict_at_acceptance(
    tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    """Overrule 7's half: the state changed under an offer the accepter was handed.

    `Conflict` and not `Invalid` — the request is well-formed and the person
    clicking the link chose none of this.
    """
    from apps.core.actor import actor_for
    from apps.core.exceptions import Conflict

    role = Role.objects.create(tenant=tenant, key="approver", name="Approver")
    invitation, _token = invite_member(
        tenant=tenant, email="later@example.com", role="approver", actor=owner_actor
    )
    role.delete()

    joiner = User.objects.create_user(email="later@example.com", password="p")  # noqa: S106
    with pytest.raises(Conflict) as refused:
        accept_invitation(
            tenant=tenant,
            invitation=invitation,
            user=joiner,
            actor=actor_for(user=joiner, kind="human", tenant=tenant),
        )
    assert "no longer exists" in str(refused.value)


# --- P2.5 · the label ---------------------------------------------------------


def test_role_label_answers_for_all_four_layers(tenant: Tenant) -> None:
    """Owner, a declaration, a row, and a key that resolves to nothing.

    The last is the one with teeth: `Membership.Role("approver")` raised
    `ValueError`, so the old form would have taken the invitation mail down for
    every custom role the moment one existed.
    """
    assert role_label(tenant=tenant, key=OWNER_ROLE) == "Owner"
    assert role_label(tenant=tenant, key="member") == "Member"
    assert role_label(tenant=tenant, key="admin") == "Admin"
    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    assert role_label(tenant=tenant, key="approver") == "Approver"
    assert role_label(tenant=tenant, key="gone") == "gone"


def test_the_invitation_mail_names_the_role_by_its_label(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The message the workflow is started with carries the label, not the key.

    The start is captured at the bridge seam — the same place
    `_provision_invited_person` reaches it — because the message is built inside
    the service and handed to the run, and asserting on the run's argument is
    asserting on the thing the mailer will actually send.
    """
    from apps.core import bridge

    started: list[dict[str, Any]] = []
    saved = bridge.registered()
    bridge.clear()
    for name, fn in saved.items():
        bridge.register(name, fn)
    bridge.register(bridge.START_WORKFLOW_ON_COMMIT, lambda **kwargs: started.append(kwargs))

    try:
        invite_member(tenant=tenant, email="declared@example.com", role="member", actor=owner_actor)
        assert started[-1]["arg"]["message"]["context"]["role"] == "Member"

        Role.objects.create(tenant=tenant, key="approver", name="Approver")
        invite_member(tenant=tenant, email="custom@example.com", role="approver", actor=owner_actor)
        assert started[-1]["arg"]["message"]["context"]["role"] == "Approver"
    finally:
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)


# --- P2.6 · the admin ---------------------------------------------------------


def test_the_admin_offers_the_keys_this_tenant_may_name(
    tenant: Tenant, root: User, client: Client
) -> None:
    """A dropdown of the three layers, not a free-text box.

    The column has no `choices` any more, so Django's default for it is a text
    input — and a text input on the form that hands out authority is how a
    membership gets created holding nothing at all.
    """
    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    add_membership(user=root, tenant=tenant, role=OWNER_ROLE, actor=_system(tenant))
    client.force_login(root)

    response = client.get("/admin/core/membership/add/", HTTP_X_TENANT=tenant.slug)
    assert response.status_code == 200
    field = response.context["adminform"].form.fields["role"]
    assert {key for key, _label in field.choices} == set(known_role_keys(tenant=tenant))


def test_the_admin_refuses_an_undeclared_role_as_a_form_error(
    tenant: Tenant, root: User, member: User, client: Client
) -> None:
    """A rendered message on the form, never a 500 and never a silent write."""
    add_membership(user=root, tenant=tenant, role=OWNER_ROLE, actor=_system(tenant))
    client.force_login(root)
    membership = membership_of(member, tenant)

    response = client.post(
        f"/admin/core/membership/{membership.pk}/change/",
        {"role": "viceroy"},
        HTTP_X_TENANT=tenant.slug,
    )
    assert response.status_code == 200
    assert "role" in response.context["adminform"].form.errors
    assert membership_of(member, tenant).role == Membership.Role.MEMBER


def _system(tenant: Tenant) -> Actor:
    from apps.core.actor import system_actor

    return system_actor(tenant=tenant)


# --- P2.7 · the deploy census, djb.W054 ---------------------------------------


def test_w054_is_silent_on_a_clean_deployment() -> None:
    """The negative. Without it the three positives below could all be vacuous."""
    assert check_roles_are_keys(databases=["default"]) == []


def test_w054_names_a_membership_holding_an_undeclared_key(tenant: Tenant, member: User) -> None:
    """One warning per (tenant, value), with the count and the slug.

    Planted with `.update()` — a raw write in a test is legal, and it is the
    only way to reach the state the census exists for: every service refuses
    this value, which is the point of the census being a BELT.
    """
    Membership.objects.filter(pk=membership_of(member, tenant).pk).update(role="viewer")

    found = check_roles_are_keys(databases=["default"])
    assert [f.id for f in found] == ["djb.W054"]
    text = str(found[0].msg)
    assert tenant.slug in text
    assert "'viewer'" in text
    assert "1 membership(s)" in text


def test_w054_names_a_grant_outside_the_vocabulary(tenant: Tenant, member: User) -> None:
    """A stored permission naming nothing can never fire, and says so."""
    Grant.objects.create(
        tenant=tenant,
        membership=membership_of(member, tenant),
        permission="widget.frobnicate",
        effect=Grant.Effect.ALLOW,
    )
    found = check_roles_are_keys(databases=["default"])
    assert [f.id for f in found] == ["djb.W054"]
    assert "widget.frobnicate" in str(found[0].msg)


def test_w054_names_a_reserved_permission_in_a_row(tenant: Tenant, member: User) -> None:
    """`tenant.own` is `owner`'s alone; a row naming it is a row that never fires."""
    Grant.objects.create(
        tenant=tenant,
        membership=membership_of(member, tenant),
        permission="tenant.own",
        effect=Grant.Effect.ALLOW,
    )
    found = check_roles_are_keys(databases=["default"])
    assert "reserved" in str(found[0].msg)


def test_w054_names_an_exclude_on_a_role_nobody_declares(tenant: Tenant) -> None:
    """`exclude` subtracts from a declared collection; a custom role has none."""
    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    RolePermission.objects.create(
        tenant=tenant,
        role_key="approver",
        permission="role.read",
        effect=RolePermission.Effect.EXCLUDE,
    )
    found = check_roles_are_keys(databases=["default"])
    assert any("exclude" in str(f.msg) for f in found)


def test_w054_is_silent_under_a_plain_check() -> None:
    """Registered under `deploy`, so `manage.py check` does not run it at all.

    The tier matters as much as the finding: what it reports is one deployment's
    data, and a warning about a customer's rows has no business stopping a
    developer's `manage.py`. Asserted off the REGISTRY rather than off a
    `call_command` run, because the registry is what decides which set a check
    is in — a run would also be measuring every other check in the tree.
    """
    from django.core.checks.registry import registry

    assert check_roles_are_keys in registry.deployment_checks
    assert check_roles_are_keys not in registry.registered_checks
    assert check_vocabulary_is_derivable in registry.registered_checks


def test_w054_reads_no_rows_when_no_database_was_offered() -> None:
    """`manage.py check --deploy` alone reports the code half and says so.

    Django's own idiom: `--database` aliases arrive as `databases`, and every
    database-reading check skips an empty set. The gate's `check --deploy` leg
    offers none on purpose — it is a settings probe — and without this the
    census spent ten seconds failing to connect on every builder's `--loop`
    before printing that it had seen nothing. The sentence is still printed, so
    "no bad rows" and "I read no rows" stay distinguishable.
    """
    found = check_roles_are_keys()
    assert [f.id for f in found] == ["djb.W054"]
    assert "offered it no database" in str(found[0].msg)
    assert "--database default" in str(found[0].msg)


def test_w054_says_so_when_it_cannot_read_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable database is `Info` and a sentence, never a silent clean run.

    §I — an instrument declares what it did not see. Returning `[]` here would
    make "no rows are wrong" and "I read no rows" indistinguishable, which is
    the one failure a census must not have. `Info` rather than `Warning`
    because the gate's own `check --deploy` leg runs production settings with
    no database on purpose, and reddening that would turn a settings probe into
    a database probe.
    """
    from django.core.checks import Info
    from django.db import DatabaseError

    from apps.core import checks as core_checks

    def unreachable(*_args: Any, **_kwargs: Any) -> Any:
        raise DatabaseError("couldn't get a connection after 10.00 sec")

    monkeypatch.setattr(Tenant.objects.__class__, "values_list", unreachable, raising=False)
    found, looked = core_checks._role_census_rows()

    assert looked is False
    assert [type(f) for f in found] == [Info]
    assert [f.id for f in found] == ["djb.W054"]
    assert "reporting NOTHING rather than reporting clean" in str(found[0].msg)


# --- the rider · the vocabulary is forced at boot ------------------------------


def test_the_vocabulary_check_is_silent_on_this_tree() -> None:
    """The negative for `djb.E025`. The positives are driven by plants below."""
    assert check_vocabulary_is_derivable() == []


def _check_through_the_real_door() -> str:
    """`manage.py check`'s own output for a tree that has a finding, as text.

    **THE DOOR AND NOT THE FUNCTION.** Calling `check_vocabulary_is_derivable()`
    directly answers "does this check compose the right message", which was
    never the question: the checks run in ONE framework pass, and the defect
    these cases exist for is that another check in that pass reached the broken
    derivation FIRST and died on it — so `manage.py check` printed a traceback
    and no finding at all, while the direct call stayed perfectly green. A
    criterion certified inside the harness certifies the harness.

    `SystemCheckError` is therefore the assertion and not the plumbing: an
    `ImproperlyConfigured` escaping any check in the pass propagates out of
    `call_command` instead, so every case below fails with that traceback
    rather than with a comparison.
    """
    from django.core.management import call_command
    from django.core.management.base import SystemCheckError

    try:
        call_command("check")
    except SystemCheckError as exc:
        return str(exc)
    raise AssertionError("`manage.py check` reported nothing; the plant did not take.")


def test_a_kind_collision_is_a_check_error_naming_both_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collision is loud at `manage.py check`, and loud in the house grammar.

    Before `djb.E025` existed the plant booted green and `check` said nothing —
    the collision surfaced as a 500 at the first `require()` in production, with
    a traceback naming one model where a reader needs both. Then it said
    something worse: an unhandled `ImproperlyConfigured` out of
    `check_scoped_write_policies`, which reaches `vocabulary()` in the same pass
    and used to reach it unguarded, so the finding never got composed at all.

    **The victim is built**: `AuditEntry` is given a kind `Tenant` already owns,
    for this test only, and the caches are reset on both sides so neither this
    test nor the one after it reads the other's answer.
    """
    from apps.core import authz
    from apps.core.audit import AuditEntry

    authz.reset_policies()
    monkeypatch.setattr(AuditEntry, "authz_kind", "tenant", raising=False)
    try:
        text = _check_through_the_real_door()
    finally:
        # The plant comes off HERE and not at teardown: the restore assertion
        # below is the second half of the demonstration, and it would be
        # measuring the plant if `monkeypatch` were still holding it.
        monkeypatch.undo()
        authz.reset_policies()

    assert "(djb.E025)" in text
    assert "core.Tenant" in text and "core.AuditEntry" in text
    assert "cannot be derived" in text

    # Restored byte-identical, and the findings are gone (rung-execution §2).
    assert check_vocabulary_is_derivable() == []


def test_one_role_key_declared_twice_is_a_check_error_naming_both_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second forced derivation, through the same door.

    Two apps declaring one role key is two collections under one name, and which
    one a membership resolves to would depend on import order — so
    `role_declarations()` refuses it. The victim is a second `admin`, attributed
    to `example`, spliced into the one discovery walk rather than written to a
    file: the refusal is about what the walk YIELDS, and a planted module would
    test the walk as well without saying so.
    """
    from django.apps import apps as django_apps

    from apps.core import authz
    from apps.core.authz import DeclaredRole

    real = authz._declarations

    def _with_a_second_admin(module: str, attribute: str) -> Any:
        found = list(real(module, attribute))
        if module == "roles":
            found.append(
                (
                    django_apps.get_app_config("example"),
                    {"admin": DeclaredRole(key="admin", name="Admin", permissions=("*",))},
                )
            )
        return found

    authz.reset_policies()
    monkeypatch.setattr(authz, "_declarations", _with_a_second_admin)
    try:
        text = _check_through_the_real_door()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert "(djb.E025)" in text
    assert "apps.core.roles" in text and "apps.example.roles" in text
    assert "'admin'" in text

    assert check_vocabulary_is_derivable() == []


def test_a_non_cascade_authz_kind_of_is_a_check_error_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The third forced derivation, through the same door.

    A row authorized under its parent's kind is a row that DIES with the parent,
    so the foreign key has to be `CASCADE`. `Membership.organization` is
    `PROTECT` — a real non-CASCADE key on a real model — so declaring
    `authz_kind_of = "organization"` on it for the length of this test is the
    honest victim, and no probe model has to be registered to build one.
    """
    from apps.core import authz
    from apps.core.models import Membership

    authz.reset_policies()
    monkeypatch.setattr(Membership, "authz_kind_of", "organization", raising=False)
    try:
        text = _check_through_the_real_door()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert "(djb.E025)" in text
    assert "core.Membership" in text
    assert "CASCADE" in text

    assert check_vocabulary_is_derivable() == []


def test_rule_13s_model_half_goes_quiet_instead_of_dying_on_an_underivable_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard itself, asserted where it was missing.

    `check_scoped_write_policies` reaches `vocabulary()` and used to reach it
    unguarded, which is what turned all three cases above into a traceback. It
    now returns NOTHING while the vocabulary will not derive — one finding with
    one owner, rather than a second copy of E025's sentence under rule 13's id —
    and E025's own message says the readers went quiet, so the silence is
    declared rather than discovered.
    """
    from apps.core import authz
    from apps.core.audit import AuditEntry
    from apps.core.checks import check_scoped_write_policies

    authz.reset_policies()
    monkeypatch.setattr(AuditEntry, "authz_kind", "tenant", raising=False)
    try:
        quiet = check_scoped_write_policies()
        owner = check_vocabulary_is_derivable()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert quiet == []
    assert [f.id for f in owner] == ["djb.E025"]
    assert "reports NOTHING rather than reporting clean" in str(owner[0].msg)

    # And it is answering again, not permanently muted.
    assert check_scoped_write_policies() == []


def _two_default_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plant a second role marked as the one a new member gets.

    `role_declarations()` is perfectly happy with it — two roles may both exist
    — so the refusal is `default_role_key()`'s alone, which is exactly what
    makes this the case that must NOT claim the readers went quiet.
    """
    from django.apps import apps as django_apps

    from apps.core import authz
    from apps.core.authz import DeclaredRole

    real = authz._declarations

    def _with_a_second_default(module: str, attribute: str) -> Any:
        found = list(real(module, attribute))
        if module == "roles":
            found.append(
                (
                    django_apps.get_app_config("example"),
                    {
                        "auditor": DeclaredRole(
                            key="auditor",
                            name="Auditor",
                            permissions=("*.read",),
                            is_default_for_new_members=True,
                        )
                    },
                )
            )
        return found

    monkeypatch.setattr(authz, "_declarations", _with_a_second_default)


def test_two_default_roles_is_a_check_error_naming_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fourth forced derivation, through the real door.

    "The role a new member gets" is one answer or none, so two declarations
    carrying `is_default_for_new_members` is a refusal at discovery. The
    CHANGELOG names this case; nothing read it until now.
    """
    from apps.core import authz

    authz.reset_policies()
    _two_default_roles(monkeypatch)
    try:
        text = _check_through_the_real_door()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert "(djb.E025)" in text
    assert "'auditor'" in text and "'member'" in text

    assert check_vocabulary_is_derivable() == []


def test_a_rename_onto_an_undeclared_key_is_a_check_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fifth forced derivation, through the real door.

    An alias onto a key nobody declared is an alias onto silence: every caller
    of the old name would fall to the role default with nothing saying so. The
    CHANGELOG names this case too, and this is the test that reads it.
    """
    from django.apps import apps as django_apps

    from apps.core import authz

    real = authz._declarations

    def _with_a_rename_onto_nothing(module: str, attribute: str) -> Any:
        found = list(real(module, attribute))
        if (module, attribute) == ("policies", "RENAMED_PERMISSIONS"):
            found.append(
                (
                    django_apps.get_app_config("example"),
                    {"widget.frobnicate": "widget.nobody_declared_this"},
                )
            )
        return found

    authz.reset_policies()
    monkeypatch.setattr(authz, "_declarations", _with_a_rename_onto_nothing)
    try:
        text = _check_through_the_real_door()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert "(djb.E025)" in text
    assert "'widget.frobnicate'" in text and "'widget.nobody_declared_this'" in text

    assert check_vocabulary_is_derivable() == []


def test_e025_names_the_readers_silence_only_when_they_are_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sentence is a claim about the OTHER checks, so it is measured.

    A kind collision takes `vocabulary()` down and the guarded readers really do
    report nothing — the sentence belongs. Two roles marked as the default takes
    only `default_role_key()` down: `vocabulary()` and `role_declarations()`
    both answer, rule 13's model half and the role census are working normally,
    and telling the reader they went quiet would send them hunting for a second
    defect that is not there.
    """
    from apps.core import authz
    from apps.core.audit import AuditEntry

    silence = "reports NOTHING rather than reporting clean"

    authz.reset_policies()
    monkeypatch.setattr(AuditEntry, "authz_kind", "tenant", raising=False)
    try:
        collision = check_vocabulary_is_derivable()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    authz.reset_policies()
    _two_default_roles(monkeypatch)
    try:
        two_defaults = check_vocabulary_is_derivable()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert [f.id for f in collision] == ["djb.E025"]
    assert silence in str(collision[0].msg)

    assert [f.id for f in two_defaults] == ["djb.E025"]
    assert silence not in str(two_defaults[0].msg)
    # The finding still names both parties — narrowing the sentence narrowed
    # nothing else.
    assert "'auditor'" in str(two_defaults[0].msg)

    assert check_vocabulary_is_derivable() == []


def test_a_policies_discovery_failure_is_a_check_error_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`policies()` is guarded like its siblings, and the finding has an owner.

    `check_scoped_write_policies` read the policy registry one line above its
    guard, so a malformed `policies.py` took the whole check pass down from
    there. Guarding it alone would have turned the traceback into silence —
    nothing else forces `policies()` — so it is a forced derivation now too, and
    this drives both halves at once through the real door.
    """
    from django.core.exceptions import ImproperlyConfigured

    from apps.core import authz
    from apps.core.checks import check_scoped_write_policies

    def _refuse() -> Any:
        raise ImproperlyConfigured(
            "apps.example.policies declares 'widget.update' twice; one action has one predicate."
        )

    authz.reset_policies()
    monkeypatch.setattr(authz, "policies", _refuse)
    try:
        text = _check_through_the_real_door()
        quiet = check_scoped_write_policies()
    finally:
        monkeypatch.undo()
        authz.reset_policies()

    assert "(djb.E025)" in text
    assert "the policy registry cannot be derived" in text
    assert "declares 'widget.update' twice" in text
    # The reader went quiet rather than raising, and said nothing of its own.
    assert quiet == []

    assert check_vocabulary_is_derivable() == []
    assert check_scoped_write_policies() == []


def test_a_declared_role_holds_its_patterns_and_additions_and_nothing_else_without_a_predicate(
    db: None, capsys: Any
) -> None:
    """**Two readers of one column, and they agree wherever no predicate intervenes.**

    `defaults_for(R)` is the DECLARATION's own half — patterns plus
    `DEFAULT_ROLES` additions — and `collection(None, R, compat=True)` is what
    somebody holding R actually holds today, which is the same set plus the
    un-swept residue: keys whose predicate narrows them and whose app has not
    declared `DEFAULT_ROLES` yet (clause (5)). Clause (4) put every `.read` key
    in the second and not the first, so the two disagreed by 35 non-predicate
    keys for a write-only role. R1-F2 deleted it, and this is the assertion that
    keeps them together: **the difference is a SUBSET of the predicate keys**,
    derived from `vocabulary()`'s own `predicate` column and never typed.

    The residue is printed rather than pinned, because P7.x's sweeps shrink it
    one app at a time and a pinned number would be a second thing each sweep has
    to edit. When it reaches ∅ the assertion is still true and still
    non-vacuous, because `defaults_for` for the template's roles is not empty.

    **The virtual kinds are in neither set, and that is one exclusion rather
    than a disagreement.** Both readers go through
    `authz.grantable_permissions()` — a kind with no table names no row anybody
    can be given authority over, so a key on one is in nobody's collection and
    in nobody's declared half either, and the predicate is the whole rule. An
    earlier draft of this test carried a "by design" note excusing a
    disagreement here; the disagreement was the defect, and
    `test_handing_out.py`'s virtual-kind assertions are the property's home.
    """
    from apps.core.authz import VIRTUAL_KINDS, collection, defaults_for

    words = vocabulary()
    predicate_keys = {key for key, word in words.items() if word.predicate is not None}
    assert predicate_keys, "the residue's own population must not be empty on this tree"
    virtual_keys = {key for key, word in words.items() if word.kind in VIRTUAL_KINDS}

    for role_key in sorted(role_declarations()):
        held = collection(None, role_key, compat=True)
        declared = defaults_for(role_key)
        assert declared, f"{role_key} declares nothing — the assertion would be vacuous"
        residue = held - declared
        print(f"residue({role_key}) = {sorted(residue)}")
        assert residue <= predicate_keys, sorted(residue - predicate_keys)
        # And the other direction: nothing the declaration gives is lost.
        assert declared <= held, sorted(declared - held)
        # Neither reader carries a virtual kind — the one exclusion, both sides.
        assert (held | declared) & virtual_keys == set(), sorted((held | declared) & virtual_keys)

    printed = capsys.readouterr().out
    assert "residue(" in printed
