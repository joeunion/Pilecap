"""`core.verbs.rehome`: a movable row moves with its mutable derived rows, never its ledger.

The owner's ruling: on a move, MUTABLE derived rows follow their parent and
APPEND-ONLY ledger rows do not — a noun whose ledger holds rows answers
`move_blocked` naming the ledger, and nothing moves. The nouns are planted here
(`isolated_apps` + a `schema_editor` table inside the test's transaction), so
core proves its own seam against models shaped like a product's.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.db import connection, models, transaction

from apps.core.actor import actor_for
from apps.core.exceptions import MoveBlocked, NotFound, wire_refusal
from apps.core.models import Movable, Organization, OrgScopedModel, Tenant, is_movable
from apps.core.services import create_organization
from apps.core.tests.isolation import isolated_apps
from apps.core.verbs import derived_children, rehome


@dataclass
class World:
    crate: Any
    label: Any
    log: Any


@pytest.fixture
def world(db: None) -> Iterator[World]:
    with isolated_apps("apps.core"):

        class ZzzCrate(OrgScopedModel, Movable):
            """A noun that changes node through the family's move."""

            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class ZzzLabel(OrgScopedModel):
            """A MUTABLE row that lives wherever its crate lives."""

            derive_org_from = "crate"
            crate = models.ForeignKey(ZzzCrate, on_delete=models.CASCADE, related_name="+")

            class Meta:
                app_label = "core"

        class ZzzLog(OrgScopedModel):
            """An APPEND-ONLY row recorded where its crate was at the time."""

            append_only = True
            derive_org_from = "crate"
            crate = models.ForeignKey(ZzzCrate, on_delete=models.PROTECT, related_name="+")

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            for model in (ZzzCrate, ZzzLabel, ZzzLog):
                editor.create_model(model)
        yield World(ZzzCrate, ZzzLabel, ZzzLog)


@pytest.fixture
def branch(tenant: Tenant, root_org: Organization, owner_actor: Any) -> Organization:
    return create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )


def _crate(world: World, tenant: Tenant, org: Organization) -> Any:
    return world.crate.objects.create(tenant=tenant, organization=org, name="spares")


def test_the_marker_and_the_derivation_are_discovered(world: World) -> None:
    assert is_movable(world.crate)
    assert set(derived_children(world.crate)) == {(world.label, "crate"), (world.log, "crate")}


def test_a_move_carries_its_mutable_derived_rows_in_one_transaction(
    world: World, tenant: Tenant, root_org: Organization, branch: Organization
) -> None:
    crate = _crate(world, tenant, root_org)
    label = world.label.objects.create(tenant=tenant, organization=root_org, crate=crate)
    stamp = label.updated_at

    with transaction.atomic():
        moved, changed = rehome(crate, branch)

    assert changed is True
    assert moved.organization_id == branch.pk
    crate.refresh_from_db()
    label.refresh_from_db()
    assert crate.organization_id == branch.pk
    assert label.organization_id == branch.pk
    assert label.updated_at > stamp  # the carried row takes a new version too


def test_an_append_only_derived_row_blocks_the_move_and_nothing_moves(
    world: World, tenant: Tenant, root_org: Organization, branch: Organization
) -> None:
    crate = _crate(world, tenant, root_org)
    label = world.label.objects.create(tenant=tenant, organization=root_org, crate=crate)
    world.log.objects.create(tenant=tenant, organization=root_org, crate=crate)

    with pytest.raises(MoveBlocked) as caught, transaction.atomic():
        rehome(crate, branch)

    refused = caught.value
    assert refused.code == "move_blocked"
    body = wire_refusal(refused)
    # The door is read off the mount: a planted ledger has no mounted list, so it
    # is named without a query (`test_move_seams.py` holds the mounted case).
    assert body["blocking"][0]["door"] == "route:zzz_log-list"
    assert "recorded where they were written" in body["remedies"][0]["label"]
    # Re-read: nothing moved — not the crate, not the label beside the ledger.
    crate.refresh_from_db()
    label.refresh_from_db()
    assert crate.organization_id == root_org.pk
    assert label.organization_id == root_org.pk


def test_an_empty_ledger_does_not_block(
    world: World, tenant: Tenant, root_org: Organization, branch: Organization
) -> None:
    crate = _crate(world, tenant, root_org)
    with transaction.atomic():
        _moved, changed = rehome(crate, branch)
    assert changed is True


def test_the_same_node_is_unchanged(world: World, tenant: Tenant, root_org: Organization) -> None:
    crate = _crate(world, tenant, root_org)
    before = crate.updated_at
    with transaction.atomic():
        moved, changed = rehome(crate, root_org)
    assert changed is False
    moved.refresh_from_db()
    assert moved.updated_at == before


def test_a_destination_in_another_tenant_is_not_found(
    world: World, tenant: Tenant, root_org: Organization, other_root_org: Organization
) -> None:
    crate = _crate(world, tenant, root_org)
    with pytest.raises(NotFound), transaction.atomic():
        rehome(crate, other_root_org)


def test_a_noun_that_did_not_declare_movable_is_refused(
    world: World, tenant: Tenant, root_org: Organization, branch: Organization
) -> None:
    crate = _crate(world, tenant, root_org)
    label = world.label.objects.create(tenant=tenant, organization=root_org, crate=crate)
    with pytest.raises(TypeError, match="has not declared `Movable`"):
        rehome(label, branch)


def test_the_organization_name_is_the_node_s_name(
    world: World, tenant: Tenant, branch: Organization
) -> None:
    crate = _crate(world, tenant, branch)
    assert crate.organization_name == "Branch A"


def test_a_system_actor_is_refused_the_move_policy(
    tenant: Tenant, branch: Organization, owner_actor: Any
) -> None:
    """`may_move` is `@refuses_system`: the product acting for itself holds nothing."""
    from apps.core.actor import system_actor
    from apps.core.policies import may_move

    assert may_move(system_actor(tenant=tenant), branch) is False
    assert may_move(owner_actor, branch) is True
    assert may_move(actor_for(user=None, tenant=tenant, org=branch), None) is False
