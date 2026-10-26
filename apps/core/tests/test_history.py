"""`core.selectors.list_history`: a row's own audit rows, newest first, cursor-paged.

The row is an `Organization` — a real noun, written through its real services,
so the audit rows are the ones `@service` really writes (no hand-made trail).
The noun-verb family's per-noun history route is six lines over this selector.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.api.pagination import cursor_page
from apps.core.audit import AuditEntry
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Membership, Organization, Tenant
from apps.core.schemas import HistoryEntryOut
from apps.core.selectors import list_history
from apps.core.services import add_membership, create_organization, rename_organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def tree(tenant: Tenant, owner_actor: Actor, root_org: Organization) -> dict[str, Organization]:
    a = create_organization(tenant=tenant, parent=root_org, name="A", slug="a", actor=owner_actor)
    b = create_organization(tenant=tenant, parent=root_org, name="B", slug="b", actor=owner_actor)
    return {"root": root_org, "a": a, "b": b}


def test_the_history_is_the_rows_ok_entries_newest_first(
    tenant: Tenant, owner_actor: Actor, tree: dict[str, Organization]
) -> None:
    a = tree["a"]
    rename_organization(tenant=tenant, organization=a, name="A, renamed", actor=owner_actor)
    rename_organization(tenant=tenant, organization=a, name="A, again", actor=owner_actor)
    # A refused call on the same row leaves an error entry the history never shows.
    member = actor_for(user=None, tenant=tenant, org=tree["root"])
    with pytest.raises(Forbidden):
        rename_organization(tenant=tenant, organization=a, name="nope", actor=member)

    rows = list(list_history(tenant=tenant, actor=owner_actor, row=a))
    entries = [HistoryEntryOut.model_validate(row) for row in rows]

    assert [e.verb for e in entries] == ["rename", "rename", "create"]
    assert entries[0].at >= entries[1].at >= entries[2].at
    assert entries[0].changed_fields == ["name"]
    assert entries[0].actor.kind == "human"
    assert entries[0].actor.id == owner_actor.user_id
    assert all(row.outcome == AuditEntry.Outcome.OK for row in rows)


def test_the_history_pages_with_the_one_cursor(
    tenant: Tenant, owner_actor: Actor, tree: dict[str, Organization]
) -> None:
    a = tree["a"]
    for n in range(3):
        rename_organization(tenant=tenant, organization=a, name=f"A{n}", actor=owner_actor)
    history = list_history(tenant=tenant, actor=owner_actor, row=a)

    first = cursor_page(history, tenant=tenant, limit=2)
    assert first.has_more and first.next_cursor
    second = cursor_page(history, tenant=tenant, limit=2, cursor=first.next_cursor)
    seen = [row.pk for row in (*first.items, *second.items)]
    assert seen == [row.pk for row in history]
    assert len(seen) == 4 and not second.has_more


def test_a_sibling_branch_row_is_not_found(
    tenant: Tenant, owner: User, owner_actor: Actor, tree: dict[str, Organization]
) -> None:
    from apps.accounts.services import create_user

    user = create_user(email="a-admin@example.com", password="pw-for-tests-only")  # noqa: S106 — a throwaway password a test user is made with
    add_membership(
        user=user,
        tenant=tenant,
        organization=tree["a"],
        role=Membership.Role.ADMIN,
        is_default=True,
        actor=owner_actor,
    )
    a_admin = actor_for(user=user, tenant=tenant, org=tree["a"])

    assert list(list_history(tenant=tenant, actor=a_admin, row=tree["a"]))
    with pytest.raises(NotFound):
        list_history(tenant=tenant, actor=a_admin, row=tree["b"])


def test_another_tenants_row_is_not_found(
    other_tenant: Tenant, owner_actor: Actor, tree: dict[str, Organization]
) -> None:
    with pytest.raises(NotFound):
        list_history(tenant=other_tenant, actor=owner_actor, row=tree["a"])


def test_a_reachable_row_the_actor_may_not_read_is_forbidden(
    tenant: Tenant, tree: dict[str, Organization]
) -> None:
    nobody = actor_for(user=None, tenant=tenant, org=tree["root"])
    with pytest.raises(Forbidden):
        list_history(tenant=tenant, actor=nobody, row=tree["a"])


def test_migration_0019_builds_the_index_concurrently_outside_a_transaction() -> None:
    from importlib import import_module

    from django.contrib.postgres.operations import AddIndexConcurrently

    migration = import_module("apps.core.migrations.0019_audit_trail_reads_a_rows_history")
    assert migration.Migration.atomic is False
    (operation,) = migration.Migration.operations
    assert isinstance(operation, AddIndexConcurrently)
    assert operation.index.name == "auditentry_object_history"
    assert operation.index.fields == ["tenant", "object_id", "-created_at"]
