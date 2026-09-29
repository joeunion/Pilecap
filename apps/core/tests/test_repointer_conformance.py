"""Every `"*"` repointer keeps the repointer contract (`core.verbs.Repointer`, its seven promises).

ONE test per promise, run across EVERY discovered attach owner (`attach_world.
star_owners`), each planting its own attachment through its own
`tests/attach_specimen.py` — so an app that joins the population is measured
the day it declares its repointer, and one that ships no specimen fails by name.
Promise 6 (the authorization is the merge's) is the repointer's `# authz:`
sentence, which review reads; 1–5 and 7 are measured here.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import transaction

from apps.core.exceptions import NotFound
from apps.core.tests.attach_world import (  # noqa: F401 — the fixture is used by name
    World,
    attach_world_fixture,
    owners_ids,
    specimen_of,
    star_owners,
)
from apps.core.verbs import Repointer
from apps.events.models import Event

pytestmark = pytest.mark.django_db

OWNERS = star_owners()


def _case(world: World, org: Any, name: str) -> Any:
    return world.case.objects.create(tenant=world.tenant, organization=org, name=name)


def _events(world: World, label: str) -> list[str]:
    return list(
        Event.objects.for_tenant(world.tenant)
        .filter(name__startswith=f"{label}.")
        .order_by("created_at")
        .values_list("name", flat=True)
    )


def _count(repointer: Repointer, world: World, row: Any) -> int:
    return int(repointer.count(tenant=world.tenant, loser=row))


def _repoint(repointer: Repointer, world: World, actor: Any, loser: Any, survivor: Any) -> int:
    with transaction.atomic():
        return int(
            repointer.repoint(tenant=world.tenant, actor=actor, loser=loser, survivor=survivor)
        )


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_count_is_what_leaves_and_repoint_is_what_left(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(1) `count` answers the rows that will leave the loser; `repoint` the rows that left;
    equal on a world that did not move between them — the collapsed pair included."""
    world, attach = attach_world, specimen_of(label)
    loser = _case(world, world.branch_a, "dup")
    survivor = _case(world, world.branch_a, "keep")
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    # The survivor already carries one: an owner with a unique pair collapses onto it.
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=survivor)
    promised = _count(repointer, world, loser)
    assert promised >= 1, label

    left = _repoint(repointer, world, world.owner_at_root, loser, survivor)

    assert left == promised, (label, promised, left)
    assert _count(repointer, world, loser) == 0, label


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_an_unreachable_row_is_not_found_with_nothing_changed(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(2) `repoint` re-resolves BOTH rows for the actor; one it cannot reach is
    `not_found`, with zero rows changed and no event."""
    world, attach = attach_world, specimen_of(label)
    loser = _case(world, world.branch_a, "dup")
    survivor = _case(world, world.branch_b, "keep")
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    before_events = _events(world, label)
    before = _count(repointer, world, loser)

    with pytest.raises(NotFound):
        _repoint(repointer, world, world.owner_at_a, loser, survivor)

    assert _count(repointer, world, loser) == before, label
    assert _count(repointer, world, survivor) == 0, label
    assert _events(world, label) == before_events, label


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_an_unreachable_loser_is_not_found_with_nothing_changed(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(2), the other row: the LOSER out of the actor's reach is `not_found` too —
    `repoint` re-resolves both, not only the survivor."""
    world, attach = attach_world, specimen_of(label)
    loser = _case(world, world.branch_b, "dup")
    survivor = _case(world, world.branch_a, "keep")
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    before_events = _events(world, label)
    before = _count(repointer, world, loser)

    with pytest.raises(NotFound):
        _repoint(repointer, world, world.owner_at_a, loser, survivor)

    assert _count(repointer, world, loser) == before, label
    assert _count(repointer, world, survivor) == 0, label
    assert _events(world, label) == before_events, label


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_one_moved_event_per_moved_row_and_a_leaving_event_per_collapse(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(3) one `<app>.<kind>.moved` per MOVED row; a collapsed row emits its owner's own
    leaving event, never `.moved`."""
    world, attach = attach_world, specimen_of(label)
    loser = _case(world, world.branch_a, "dup")
    survivor = _case(world, world.branch_a, "keep")
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=survivor)
    on_survivor_before = _count(repointer, world, survivor)
    seen = len(_events(world, label))

    left = _repoint(repointer, world, world.owner_at_root, loser, survivor)

    emitted = _events(world, label)[seen:]
    moved_events = [name for name in emitted if name.endswith(".moved")]
    leaving_events = [name for name in emitted if not name.endswith(".moved")]
    arrived = _count(repointer, world, survivor) - on_survivor_before
    assert len(moved_events) == arrived, (label, emitted)
    assert len(moved_events) + len(leaving_events) == left, (label, emitted)
    assert all(name.endswith(".deleted") for name in leaving_events), (label, emitted)


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_the_population_is_tenant_wide_wherever_the_subject_lived(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(4) an attachment does not follow its subject's move, so the loser's rows sit
    where it lived when they were filed; `count` and `repoint` both find them."""
    world, attach = attach_world, specimen_of(label)
    loser = _case(world, world.branch_a, "dup")
    survivor = _case(world, world.branch_a, "keep")
    attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    # The subject moves on without its attachment (a raw re-home, not the verb).
    world.case.objects.filter(pk=loser.pk).update(organization=world.branch_b)
    loser.refresh_from_db()

    assert _count(repointer, world, loser) == 1, label
    assert _repoint(repointer, world, world.owner_at_root, loser, survivor) == 1, label
    assert _count(repointer, world, loser) == 0, label


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_every_moving_write_stamps_updated_at(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(5) a re-pointed row never reads as untouched: its `updated_at` moves."""
    world, attach = attach_world, specimen_of(label)
    loser = _case(world, world.branch_a, "dup")
    survivor = _case(world, world.branch_a, "keep")
    row = attach(tenant=world.tenant, actor=world.owner_at_root, subject=loser)
    stamp = type(row).objects.filter(pk=row.pk).values_list("updated_at", flat=True).get()

    _repoint(repointer, world, world.owner_at_root, loser, survivor)

    after = type(row).objects.filter(pk=row.pk).values_list("updated_at", flat=True).get()
    assert after > stamp, label


@pytest.mark.parametrize(("label", "repointer"), OWNERS, ids=owners_ids())
def test_a_noun_that_does_not_take_the_kind_is_a_no_op_counted_zero(
    attach_world: World, label: str, repointer: Repointer
) -> None:
    """(7) a noun whose `attachments` does not name this owner's word: `count` and
    `repoint` both answer 0 — never a refusal — and nothing is emitted. A mergeable
    noun need not take every kind the tree has an owner for."""
    world = attach_world
    loser = world.bare.objects.create(tenant=world.tenant, organization=world.branch_a, name="d")
    survivor = world.bare.objects.create(tenant=world.tenant, organization=world.branch_a, name="k")
    seen = _events(world, label)

    assert _count(repointer, world, loser) == 0, label
    assert _repoint(repointer, world, world.owner_at_root, loser, survivor) == 0, label
    assert _events(world, label) == seen, label


def test_the_population_is_not_empty() -> None:
    """The floor: a walk that found no `"*"` owner would make every test above vacuous."""
    assert OWNERS, "no app answers for every noun in a merge_repointers.py"
