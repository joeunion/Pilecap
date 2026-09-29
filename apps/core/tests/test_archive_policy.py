"""The system actor's one exception, `may_archive`, and the vocabulary's family keys.

Three claims, each against the real registries:

* `allows(system, key, row)` is still True for every key — EXCEPT a key whose
  predicate declared `@refuses_system`, which gets that predicate's answer.
* `may_archive` is the capability asked where the row lives: an admin of the
  node or an ancestor may, a member may not, the system may not, a branch admin
  may not reach the group's row, and a tenant-wide row is asked at the root.
* An archivable kind derives `<kind>.archive` and `<kind>.restore`, each with
  its own sentence, from `core.verbs.ROADS` — no app writes prose for them.

The planted archivable kind joins the kind registry by the registry's own cache
(`authz._kinds`), because a model built under `isolate_apps` is not in the
global app registry and the vocabulary is derived from that registry.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import models

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import authz
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import allows, refusing_system, reset_policies, vocabulary
from apps.core.models import (
    Archivable,
    Membership,
    Organization,
    OrgScopedModel,
    Tenant,
    TenantScopedModel,
)
from apps.core.policies import may_archive
from apps.core.services import add_membership, create_organization
from apps.core.tests.isolation import isolated_apps
from apps.example import policies as example_policies
from apps.example.models import Widget

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _vocabulary_restored() -> Iterator[None]:
    reset_policies()
    yield
    reset_policies()


@pytest.fixture
def planted() -> Iterator[tuple[Any, Any]]:
    """An org-scoped archivable kind and a tenant-wide one, IN the kind registry."""
    with isolated_apps("apps.core", "apps.accounts") as registry:
        # `archived_by` names the user model by its settings STRING.
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzShelf(OrgScopedModel, Archivable):
            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class ZzzLedgerBook(TenantScopedModel, Archivable):
            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        reset_policies()
        kinds = dict(authz.kind_registry())
        kinds.update({"zzz_shelf": ZzzShelf, "zzz_ledger_book": ZzzLedgerBook})
        authz._kinds = kinds
        yield ZzzShelf, ZzzLedgerBook
        reset_policies()


def _admin_at(tenant: Tenant, org: Organization, email: str) -> Actor:
    user = create_user(email=email, password="x-irrelevant-9")  # pragma: allowlist secret
    add_membership(
        user=user,
        tenant=tenant,
        organization=org,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return actor_for(user=user, tenant=tenant, org=org)


# --- A1.4 · the system actor's exemption yields to a declared refusal --------


def test_may_archive_is_the_first_predicate_that_refuses_the_system() -> None:
    assert may_archive in refusing_system()


def test_the_system_actor_gets_the_predicates_answer_for_a_refusing_key(
    monkeypatch: pytest.MonkeyPatch, tenant: Tenant, root_org: Organization
) -> None:
    monkeypatch.setitem(example_policies.POLICIES, "widget.archive", may_archive)
    reset_policies()
    row = Widget(tenant=tenant, organization=root_org, name="w")
    system = system_actor(tenant=tenant, org=root_org)

    assert allows(system, "widget.archive", row) is False
    # Every other key keeps the exemption, predicate or not.
    assert allows(system, "widget.update", row) is True
    assert allows(system, "widget.delete", row) is True
    assert allows(system, "widget.read", row) is True
    assert allows(system, "no_such_kind.frobnicate", row) is True


# --- may_archive · the capability, asked where the row lives ------------------


def test_an_admin_archives_and_a_member_does_not(
    planted: tuple[Any, Any],
    tenant: Tenant,
    root_org: Organization,
    admin_actor: Actor,
    member_actor: Actor,
) -> None:
    shelf, _ = planted
    row = shelf(tenant=tenant, organization=root_org, label="s")

    assert may_archive(admin_actor, row) is True
    assert may_archive(member_actor, row) is False
    assert may_archive(system_actor(tenant=tenant, org=root_org), row) is False
    assert may_archive(admin_actor, None) is False


def test_a_branch_admin_reaches_down_and_never_up(
    planted: tuple[Any, Any], tenant: Tenant, root_org: Organization, owner: User
) -> None:
    shelf, _ = planted
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    branch = create_organization(tenant=tenant, parent=root_org, name="A", slug="a", actor=acting)
    leaf = create_organization(tenant=tenant, parent=branch, name="A1", slug="a1", actor=acting)
    branch_admin = _admin_at(tenant, branch, "branch-admin@example.com")

    assert may_archive(branch_admin, shelf(tenant=tenant, organization=leaf, label="x"))
    assert may_archive(branch_admin, shelf(tenant=tenant, organization=branch, label="x"))
    assert not may_archive(branch_admin, shelf(tenant=tenant, organization=root_org, label="x"))


def test_a_tenant_wide_row_is_asked_at_the_root(
    planted: tuple[Any, Any],
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    admin_actor: Actor,
) -> None:
    _, book = planted
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    branch = create_organization(tenant=tenant, parent=root_org, name="B", slug="b", actor=acting)
    branch_admin = _admin_at(tenant, branch, "b-admin@example.com")
    row = book(tenant=tenant, label="tenant-wide")

    assert may_archive(admin_actor, row) is True
    assert may_archive(branch_admin, row) is False


# --- A1.7 (vocabulary half) · the family keys are derived ----------------------


def test_an_archivable_kind_derives_archive_and_restore(planted: tuple[Any, Any]) -> None:
    words = vocabulary()

    archive = words["zzz_shelf.archive"]
    restore = words["zzz_shelf.restore"]
    assert archive.decided_by == "derived" and restore.decided_by == "derived"
    assert archive.sentence == "You may not archive this zzz shelf."
    assert restore.sentence == "You may not restore this zzz shelf."
    assert "zzz_ledger_book.archive" in words
    # A kind that did not declare the mixin derives its four and no family verb.
    # `WidgetEntry` is the worked example's ledger: append-only, so it can never
    # declare `Archivable` (D8) — a fixture that stays true whichever nouns adopt.
    assert "widget_entry.archive" not in words
    assert "widget_entry.restore" not in words
    assert {action for action in words if action.startswith("widget_entry.")} >= {
        "widget_entry.create",
        "widget_entry.read",
        "widget_entry.update",
        "widget_entry.delete",
    }
