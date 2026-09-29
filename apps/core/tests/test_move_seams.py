"""Two of `core.verbs.rehome`'s edges: the blocker's door, and an owner nobody can take.

* A ledger that holds a move names the door where a reader finds it — the list
  route the MOUNT carries for that kind, narrowed by the parameter that list
  really declares (`widget_entries-list?widget_id=`), never a name composed from
  the kind (`widget_entry-list?widget=`, which no route answers).
* A move that names an owner for a noun with no `move_owner_field` is refused
  `invalid` naming `owner_id`, with nothing moved — never a 200 that ignored it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection, models, transaction

from apps.accounts.models import User
from apps.core.exceptions import Invalid
from apps.core.models import Movable, Organization, OrgScopedModel, Tenant
from apps.core.services import create_organization
from apps.core.tests.isolation import isolated_apps
from apps.core.verbs import _list_door, mounted_operations, rehome


def test_the_blocker_door_is_the_mounted_list_with_its_declared_parameter() -> None:
    assert "widget_entries-list" in mounted_operations()
    assert _list_door("widget_entry", "widget", "abc") == "route:widget_entries-list?widget_id=abc"


def test_a_kind_with_no_mounted_list_is_named_without_a_query() -> None:
    assert _list_door("zzz_unmounted_log", "crate", "abc") == "route:zzz_unmounted_log-list"


@pytest.fixture
def crate(db: None) -> Iterator[Any]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzOwnerlessCrate(OrgScopedModel, Movable):
            """A movable noun with no owner axis."""

            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzOwnerlessCrate)
        yield ZzzOwnerlessCrate


def test_an_owner_named_for_a_noun_without_one_is_refused_and_nothing_moves(
    crate: Any, tenant: Tenant, root_org: Organization, owner: User, owner_actor: Any
) -> None:
    branch = create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )
    row = crate.objects.create(tenant=tenant, organization=root_org, name="spares")

    with pytest.raises(Invalid) as caught, transaction.atomic():
        rehome(row, branch, owner=owner)

    assert "owner_id" in caught.value.errors
    row.refresh_from_db()
    assert row.organization_id == root_org.pk
