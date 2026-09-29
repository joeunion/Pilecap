"""Upward config resolution, the link gate, and the landing gate.

Three primitives that arrived together because they are one idea seen from
three sides (ADRs core-3 and core-4, both in `docs/product/architecture.md`,
the ADR home):

* **`governing(org)`** — the rows on the acting organization's
  ancestor chain, nearest first, in one query. "Which policy governs me" is a
  question a branch must be able to answer about a row it can never list.
* **`may_be_named(actor, obj)`** — could this actor have *reached*
  this reference? Downward always; upward only for a model that declared
  `InheritedDownward`, which is the same population `governing` serves, and
  that coupling is why the two land in one rung.
* **The landing gate** — a row whose organization is *derived* from
  something it points at may not disagree with it, at insert or at update.

**The models are built here, in the test, and torn down with it.** `isolate_apps`
plus a `schema_editor` table is what lets `core` prove its own primitives
against a model shaped exactly like the ones a product will write — an
`InheritedDownward` config row, and a row deriving its organization from an FK
— without adding a table to the template that nothing in the template uses, and
without a migration (this module ships zero). The registry is restored on exit,
so `makemigrations --check` and the model system checks never see them.

DOES NOT COVER — declared:

* `governing()` is proven to **depth 4**, not to `PATH_MAX_DEPTH` (12). The
  algorithm is string decomposition and does not know how deep it is, but the
  claim tested is the one made.
* The landing gate runs where something calls `full_clean()`. That is the house
  style for a service and it is what the admin does; it is not a closed
  question, and rule 26's AST check is the belt to that brace.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, models

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import may_be_named
from apps.core.exceptions import Invalid, as_invalid
from apps.core.models import (
    InheritedDownward,
    Organization,
    OrgScopedModel,
    Tenant,
    ancestor_paths,
    is_inherited_downward,
)
from apps.core.services import create_organization, root_organization
from apps.core.tests.isolation import isolated_apps

pytestmark = pytest.mark.django_db


# --- the tree ----------------------------------------------------------------


class Tree:
    """root → A → A1, and a sibling B. Four nodes, three deep."""

    def __init__(self, tenant: Tenant, owner: User) -> None:
        acting = actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))
        self.tenant = tenant
        self.root = root_organization(tenant=tenant)
        self.a = create_organization(
            tenant=tenant, parent=self.root, name="A", slug="a", actor=acting
        )
        self.b = create_organization(
            tenant=tenant, parent=self.root, name="B", slug="b", actor=acting
        )
        self.a1 = create_organization(
            tenant=tenant, parent=self.a, name="A1", slug="a1", actor=acting
        )
        self.a1x = create_organization(
            tenant=tenant, parent=self.a1, name="A1X", slug="a1x", actor=acting
        )


@pytest.fixture
def tree(tenant: Tenant, owner: User) -> Tree:
    return Tree(tenant, owner)


# --- the models, built and torn down with the test ---------------------------


class _Built:
    """The two canary models and the table each of them needs."""

    def __init__(self, config: Any, unmarked: Any, derived: Any) -> None:
        self.config = config
        self.unmarked = unmarked
        self.derived = derived


@pytest.fixture
def built() -> Any:
    """An `InheritedDownward` config model, its unmarked twin, and a derived row.

    The twin is not decoration: "the widening is exactly the marked population"
    is only a claim if there is an identical model on the other side of the
    line, differing in the declaration and in nothing else.
    """
    with isolated_apps("apps.core"):

        class CanaryPolicy(InheritedDownward, OrgScopedModel):
            """Configuration a branch inherits from whoever set it above."""

            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class CanaryPlainRow(OrgScopedModel):
            """The same shape, undeclared. Governs nothing and is named by nobody."""

            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class CanaryDerived(OrgScopedModel):
            """A row whose organization is its parent's, not its own choice."""

            policy = models.ForeignKey(CanaryPolicy, on_delete=models.CASCADE)
            derive_org_from = "policy"

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(CanaryPolicy)
            editor.create_model(CanaryPlainRow)
            editor.create_model(CanaryDerived)
        # No teardown of the tables, deliberately: they were created inside the
        # transaction pytest-django wraps this test in, and Postgres rolls DDL
        # back with everything else. Dropping them by hand would have to happen
        # inside that same transaction, where the foreign keys still hold
        # pending trigger events and the DROP is refused. The registry is what
        # needs restoring, and `isolate_apps` does that on the way out.
        yield _Built(CanaryPolicy, CanaryPlainRow, CanaryDerived)


# --- governing() ---------------------------------------------------------


def test_ancestor_paths_decomposes_without_asking_the_database() -> None:
    """The whole reason `governing` costs no extra query.

    A materialized path already contains its ancestry; reading it back out is
    string work. This is the unit under the claim the query pin makes below.
    """
    assert ancestor_paths("0000") == ("0000",)
    assert ancestor_paths("0000.0001.0002") == ("0000", "0000.0001", "0000.0001.0002")


def test_governing_answers_nearest_first_in_one_query(
    tree: Tree, built: Any, django_assert_num_queries: Any
) -> None:
    """Rows at root and A; A1 is governed by A's, then the root's.

    The order is the answer, not a detail: a caller takes `.first()` and gets
    the nearest ancestor's row, which is what "inherited downwards" means. And
    it is **one** query — the ancestor chain came out of the path in Python.
    """
    at_root = built.config.objects.create(tenant=tree.tenant, organization=tree.root, label="root")
    at_a = built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")

    with django_assert_num_queries(1):
        found = list(built.config.objects.for_tenant(tree.tenant).governing(tree.a1))

    assert [row.pk for row in found] == [at_a.pk, at_root.pk]
    assert found[0].label == "a"


def test_governing_never_answers_with_a_siblings_row(tree: Tree, built: Any) -> None:
    """The leak the panel warned would reopen — asserted as an absence.

    B is not on A1's chain and must not appear. This is the test that would
    catch a `governing` implemented as a bare prefix comparison in the wrong
    direction, which is the mistake this API is one keystroke away from.
    """
    built.config.objects.create(tenant=tree.tenant, organization=tree.root, label="root")
    built.config.objects.create(tenant=tree.tenant, organization=tree.b, label="b")

    for_a1 = built.config.objects.for_tenant(tree.tenant).governing(tree.a1)
    assert [row.label for row in for_a1] == ["root"]

    for_b = built.config.objects.for_tenant(tree.tenant).governing(tree.b)
    assert [row.label for row in for_b] == ["b", "root"]


def test_governing_reaches_the_whole_chain_at_depth_four(tree: Tree, built: Any) -> None:
    """root → A → A1 → A1X, with a row on each: four, nearest first."""
    for org, label in ((tree.root, "root"), (tree.a, "a"), (tree.a1, "a1"), (tree.a1x, "a1x")):
        built.config.objects.create(tenant=tree.tenant, organization=org, label=label)

    found = built.config.objects.for_tenant(tree.tenant).governing(tree.a1x)
    assert [row.label for row in found] == ["a1x", "a1", "a", "root"]


def test_governing_none_resolves_nothing(tree: Tree, built: Any) -> None:
    """Fails closed, exactly as `for_tenant(None)` and `visible_to(None)` do.

    An unresolved hat resolves no configuration — never the root's, which is
    the tempting default and the one that hands a stranger the tenant's own
    settings.
    """
    built.config.objects.create(tenant=tree.tenant, organization=tree.root, label="root")
    assert not built.config.objects.for_tenant(tree.tenant).governing(None).exists()


def test_governing_is_refused_on_a_model_that_did_not_declare_it(tree: Tree, built: Any) -> None:
    """The population is opt-in, and the refusal names the declaration.

    Same shape as `visible_to` on a tenant-scoped model: a `TypeError`, because
    it is a mistake about what the model IS rather than about this call's
    arguments, and it names `InheritedDownward` so the traceback is a signpost.
    """
    assert is_inherited_downward(built.config)
    assert not is_inherited_downward(built.unmarked)

    with pytest.raises(TypeError) as raised:
        built.unmarked.objects.for_tenant(tree.tenant).governing(tree.a1)
    assert "InheritedDownward" in str(raised.value)

    # And the argument does not rescue it: the declaration is checked first,
    # so a `None` hat cannot hide a model that was never meant to be governed.
    with pytest.raises(TypeError):
        built.unmarked.objects.for_tenant(tree.tenant).governing(None)


def test_governing_does_not_widen_visible_to(tree: Tree, built: Any) -> None:
    """Upward config resolution, never upward visibility. Both, side by side.

    A1 resolves A's row through `governing` and still cannot **list** it. If
    this ever stops holding, `governing` has become the hole A5a refused.
    """
    built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")

    scoped = built.config.objects.for_tenant(tree.tenant)
    assert scoped.governing(tree.a1).count() == 1
    assert scoped.visible_to(tree.a1).count() == 0


# --- may_be_named ----------------------------------------------------------


def _hat(user: User, tenant: Tenant, org: Organization) -> Actor:
    return actor_for(user=user, tenant=tenant, org=org)


def test_a_hat_may_name_a_row_beneath_it(tree: Tree, built: Any, owner: User) -> None:
    """Downward: a row A could have listed is a row A may name."""
    beneath = built.unmarked.objects.create(
        tenant=tree.tenant, organization=tree.a1, label="under a"
    )
    assert may_be_named(_hat(owner, tree.tenant, tree.a), beneath)


def test_a_hat_may_not_name_a_siblings_row(tree: Tree, built: Any, owner: User) -> None:
    """A foreign reference handed to a service the actor cannot reach."""
    elsewhere = built.unmarked.objects.create(
        tenant=tree.tenant, organization=tree.b, label="under b"
    )
    assert not may_be_named(_hat(owner, tree.tenant, tree.a), elsewhere)


def test_a_hat_may_name_an_ancestors_row_only_when_it_is_inherited_downward(
    tree: Tree, built: Any, owner: User
) -> None:
    """The link gate, and the line it is drawn on.

    The two rows are in the same organization, hold the same fields and differ
    in one class attribute. A1 may name the declared one — it is the
    configuration governing it — and may not name the other. "The widening is
    exactly the marked population" is what that pair says.
    """
    acting = _hat(owner, tree.tenant, tree.a1)
    governed_by = built.config.objects.create(
        tenant=tree.tenant, organization=tree.a, label="a's policy"
    )
    private_to_a = built.unmarked.objects.create(
        tenant=tree.tenant, organization=tree.a, label="a's own row"
    )

    assert may_be_named(acting, governed_by)
    assert not may_be_named(acting, private_to_a)


def test_the_link_gate_is_still_only_upward_along_the_chain(
    tree: Tree, built: Any, owner: User
) -> None:
    """A marked row in a *sibling* is not on the chain and stays unreachable.

    Otherwise the declaration would be a tenant-wide read of every config row,
    which is a different and much larger decision than the one made.
    """
    siblings_policy = built.config.objects.create(
        tenant=tree.tenant, organization=tree.b, label="b's policy"
    )
    assert not may_be_named(_hat(owner, tree.tenant, tree.a1), siblings_policy)


def test_may_be_named_fails_closed_on_every_unresolved_thing(
    tree: Tree, built: Any, owner: User, other_tenant: Tenant
) -> None:
    """No hat, no tenant, another tenant's row, a row with no organization.

    All four are False, and the last one matters most: `may_be_named` is called
    on whatever a service was handed, and a tenant-scoped row arriving where an
    org-scoped one was expected must not answer "yes, go ahead".
    """
    row = built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")

    hatless = actor_for(user=owner, tenant=tree.tenant, org=None)
    assert not may_be_named(hatless, row)

    tenantless = Actor(user=owner, token=None, kind="human", tenant=None, org=tree.a)
    assert not may_be_named(tenantless, row)

    # A hat in another tenant: two trees' paths are unrelated strings, and
    # "0000" is a prefix of "0000" in both of them.
    elsewhere = root_organization(tenant=other_tenant)
    assert not may_be_named(_hat(owner, other_tenant, elsewhere), row)

    assert not may_be_named(_hat(owner, tree.tenant, tree.a), tree.tenant)


def test_the_system_actor_gets_no_exemption_here(tree: Tree, built: Any) -> None:
    """Unlike `allows()`, and deliberately (see the docstring).

    `allows` asks whether a role permits a verb and the product acting for
    itself has no role to consult. This asks whether a reference was
    *reachable*, and "a workflow started it" is not an answer. A tenant-wide
    run says so at the call site with a `# reach:` comment the gate counts.
    """
    row = built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")
    assert not may_be_named(system_actor(tree.tenant, None), row)
    # With a hat, the system actor is judged like anybody else.
    assert may_be_named(system_actor(tree.tenant, tree.root), row)
    assert not may_be_named(system_actor(tree.tenant, tree.b), row)


# --- the landing gate ------------------------------------------------------


def test_a_derived_organization_that_agrees_passes(tree: Tree, built: Any) -> None:
    parent = built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")
    row = built.derived(tenant=tree.tenant, organization=tree.a, policy=parent)
    with as_invalid():
        row.full_clean()
    row.save()
    assert built.derived.objects.for_tenant(tree.tenant).count() == 1


def test_a_derived_organization_that_disagrees_is_refused_on_insert(tree: Tree, built: Any) -> None:
    """`Invalid`, naming `organization`, before the row exists.

    The house form is `with as_invalid(): row.full_clean()`, which is what a
    service writes and what turns Django's `ValidationError` into the domain's
    refusal. Both are asserted — the domain one because that is what a service
    raises, and Django's underneath because the admin and every ModelForm go
    through the same `clean()` and must keep working.
    """
    parent = built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")
    row = built.derived(tenant=tree.tenant, organization=tree.b, policy=parent)

    with pytest.raises(Invalid) as refused, as_invalid():
        row.full_clean()
    assert "organization" in refused.value.errors
    assert "policy" in " ".join(refused.value.errors["organization"])

    with pytest.raises(DjangoValidationError) as django_raised:
        row.full_clean()
    assert "organization" in django_raised.value.message_dict


def test_a_derived_organization_that_disagrees_is_refused_on_update(tree: Tree, built: Any) -> None:
    """The other half, and the one a check written only for `create` misses.

    The row lands correctly and is then re-pointed at a policy somewhere else —
    which is the same leak arriving a day later. The comparison is against the
    **final** value both times: what the row will hold after this save, not
    what it held when it was made.
    """
    here = built.config.objects.create(tenant=tree.tenant, organization=tree.a, label="a")
    there = built.config.objects.create(tenant=tree.tenant, organization=tree.b, label="b")
    row = built.derived.objects.create(tenant=tree.tenant, organization=tree.a, policy=here)

    row.policy = there
    with pytest.raises(Invalid) as refused, as_invalid():
        row.full_clean()
    assert "organization" in refused.value.errors

    # ...and moving the organization to match is what makes it hold again.
    row.organization = tree.b
    with as_invalid():
        row.full_clean()


def test_a_model_without_the_declaration_is_left_alone(tree: Tree, built: Any) -> None:
    """The gate is opt-in: an undeclared model may put its row where it likes."""
    row = built.unmarked(tenant=tree.tenant, organization=tree.b, label="anywhere")
    with as_invalid():
        row.full_clean()


def test_a_declaration_naming_a_field_that_does_not_exist_is_loud(
    tree: Tree, built: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mistake in the model, refused as one rather than checked as nothing.

    The failure mode this replaces is the worst kind: a typo'd declaration that
    silently guards nothing, on a model whose whole reason for declaring was
    that the guard mattered.
    """
    monkeypatch.setattr(built.derived, "derive_org_from", "no_such_field")
    row = built.derived(tenant=tree.tenant, organization=tree.b)
    with pytest.raises(FieldDoesNotExist):
        row.clean()
