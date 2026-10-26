"""The landing law, once, across every attach owner (ADR core-20's placement rule).

An attachment lands at its SUBJECT's organization; a TENANT-WIDE subject has
none, so the attachment lands at the HAT — never the root. Down-only
visibility decides it: a root-landed note on a tenant-wide subject is readable
by root hats only, so a branch author could not read back what they wrote. House
rule 55's root-only writes govern the tenant-wide ROW (a `Tag`), never the
org-scoped link. Every `"*"` repointer app is an attach owner and is driven
here through its own `tests/attach_specimen.py`.

**Two rulings the law carries, for the owners** (stated here and in the
conventions' attach recipe; not yet asserted, because asserting them reds two
owners' trees outside core — the owners' changes land them):

* **One per pair follows the landing.** A tenant-wide `(tag, subject)`
  uniqueness answers `conflict` to a second hat attaching the same word — a
  refusal revealing a link that hat cannot see, the existence leak a reach
  refusal exists to prevent. The pair is unique per hat: `(tag, subject,
  organization)`.
* **A merge does not re-land.** A repoint onto a TENANT-WIDE survivor keeps
  each attachment's organization (a repoint changes what the row is about,
  never who may read it; re-landing at the merging actor's hat widens a
  branch's private row as a side effect nobody pressed); onto an org-scoped
  survivor it moves to the survivor's organization, where its subject lives.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.accounts.models import User
from apps.core.tests.attach_world import (  # noqa: F401 — the fixture is used by name
    World,
    attach_world_fixture,
    owners_ids,
    specimen_of,
    star_owners,
)

pytestmark = pytest.mark.django_db

LABELS = [label for label, _ in star_owners()]


def _visible(row: Any, actor: Any) -> bool:
    model = type(row)
    return bool(model.objects.for_tenant(actor.tenant).visible_to(actor).filter(pk=row.pk).exists())


@pytest.mark.parametrize("label", LABELS, ids=owners_ids())
def test_an_org_scoped_subject_lands_its_attachment_at_the_subject_s_node(
    attach_world: World, label: str
) -> None:
    world, attach = attach_world, specimen_of(label)
    subject = world.case.objects.create(
        tenant=world.tenant, organization=world.branch_a, name="case"
    )
    row = attach(tenant=world.tenant, actor=world.owner_at_root, subject=subject)
    assert row.organization_id == world.branch_a.pk, label


@pytest.mark.parametrize("label", LABELS, ids=owners_ids())
def test_a_tenant_wide_subject_lands_its_attachment_at_the_acting_hat(
    attach_world: World, label: str
) -> None:
    world, attach = attach_world, specimen_of(label)
    subject = world.notebook.objects.create(tenant=world.tenant, name="shared")
    row = attach(tenant=world.tenant, actor=world.owner_at_a, subject=subject)
    assert row.organization_id == world.branch_a.pk, (label, row.organization_id)
    assert _visible(row, world.owner_at_a), label
    assert not _visible(row, world.owner_at_b), label


# --- one refusal order: the subject seam, and the owners that still fork -------
#
# A pointer `<kind>:<id>` naming a kind that takes no attachments AND a row the
# actor cannot reach could be refused two ways: by the kind first (`invalid`
# naming `subject` — the kind list is published vocabulary, so saying so leaks
# nothing) or by the row first (`not_found`). `apps.core.verbs.subject_for` is the
# one seam and it asks the kind first (ADR attach-1). Until every owner reads
# through it the owners fork, and this census prints how many — RECORDED below
# and only ever falling: the owners' adoption (each owner's own rung) brings it
# to 0, and that change lowers the number here.

#: Owners answering the undeclared-kind-and-unreachable-row case unlike the seam ("forking: 0").
FORKING_OWNERS_AT_MOST = 0


def _code_of(call: Any) -> str:
    from apps.core.exceptions import DomainError

    try:
        call()
    except DomainError as refused:
        return refused.code
    return "answered"


def test_every_owner_refuses_in_the_seam_s_order_or_is_counted(attach_world: World) -> None:
    import importlib

    from apps.core.verbs import subject_for

    world = attach_world
    hidden = world.bare.objects.create(
        tenant=world.tenant, organization=world.branch_b, name="out of reach"
    )
    pointer = f"{_kind(world.bare)}:{hidden.pk}"
    seam = _code_of(lambda: subject_for(world.owner_at_a, pointer, attachment="notes"))
    assert seam == "invalid", seam
    codes = {}
    for label in LABELS:
        reader = importlib.import_module(f"apps.{label}.selectors").get_subject
        codes[label] = _code_of(lambda r=reader: r(actor=world.owner_at_a, subject=pointer))
    forking = sorted(label for label, code in codes.items() if code != seam)
    print(f"attach owners forking: {len(forking)} {forking} (codes: {codes}; seam: {seam})")
    assert len(forking) <= FORKING_OWNERS_AT_MOST, codes


def test_the_seam_refuses_an_unreachable_row_of_a_kind_that_takes_it_as_not_found(
    attach_world: World,
) -> None:
    from apps.core.exceptions import NotFound
    from apps.core.verbs import subject_for

    world = attach_world
    hidden = world.case.objects.create(
        tenant=world.tenant, organization=world.branch_b, name="out of reach"
    )
    with pytest.raises(NotFound):
        subject_for(world.owner_at_a, f"{_kind(world.case)}:{hidden.pk}", attachment="notes")
    seen = world.case.objects.create(tenant=world.tenant, organization=world.branch_a, name="mine")
    assert (
        subject_for(world.owner_at_a, f"{_kind(world.case)}:{seen.pk}", attachment="notes") == seen
    )


@pytest.mark.parametrize("pointer", ["", "widget", "widget:", ":abc", "widget:not-a-uuid"])
def test_a_malformed_pointer_is_invalid_naming_subject(pointer: str) -> None:
    from apps.core.exceptions import Invalid
    from apps.core.verbs import parse_subject

    with pytest.raises(Invalid) as refused:
        parse_subject(pointer)
    assert set(refused.value.errors) == {"subject"}


def test_landing_for_follows_the_law(attach_world: World) -> None:
    """Org-scoped → its organization; tenant-wide → the acting hat; an organization → itself."""
    from apps.core.verbs import landing_for

    world = attach_world
    case = world.case.objects.create(tenant=world.tenant, organization=world.branch_b, name="c")
    notebook = world.notebook.objects.create(tenant=world.tenant, name="n")
    assert landing_for(case, world.owner_at_a) == world.branch_b
    assert landing_for(notebook, world.owner_at_a) == world.branch_a
    assert landing_for(world.branch_b, world.owner_at_a) == world.branch_b


def test_landing_for_with_no_hat_is_no_acting_scope(attach_world: World) -> None:
    """A tenant-wide subject and an actor wearing no hat: nowhere to land, the door's one word."""
    from apps.core.actor import actor_for
    from apps.core.exceptions import NoActingScope
    from apps.core.verbs import landing_for

    world = attach_world
    notebook = world.notebook.objects.create(tenant=world.tenant, name="n")
    hatless = actor_for(user=world.owner_at_a.user, tenant=world.tenant, org=None)
    with pytest.raises(NoActingScope) as refused:
        landing_for(notebook, hatless)
    assert refused.value.detail == NoActingScope.no_hat_detail


def test_the_fork_over_the_wire(attach_world: World) -> None:
    """The same pointer at two owners' list doors: the codes a client actually gets.

    Measured on the tree that introduced the seam: notes `400 invalid` (the
    seam's order), files `404 not_found` (resolve first) — the fork the census
    above counts. Printed rather than pinned per owner, so an owner's adoption
    of the seam changes a number, not this test.
    """
    from django.test import Client

    world = attach_world
    hidden = world.bare.objects.create(
        tenant=world.tenant, organization=world.branch_b, name="out of reach"
    )
    pointer = f"{_kind(world.bare)}:{hidden.pk}"
    client = Client()
    person = world.owner_at_a.user
    assert isinstance(person, User)
    client.force_login(person)
    answers = {
        path: client.get(path, {"subject": pointer}, headers={"x-org": world.branch_a.slug})
        for path in ("/api/v1/djb_notes/", "/api/v1/files/")
    }
    codes = {path: (r.status_code, r.json().get("code")) for path, r in answers.items()}
    print(f"over the wire: {codes}")
    assert codes["/api/v1/djb_notes/"] == (400, "invalid"), codes
    assert codes["/api/v1/files/"] in {(400, "invalid"), (404, "not_found")}, codes


def _kind(model: Any) -> str:
    from apps.core import authz

    kind = authz.kind_of(model)
    assert kind is not None
    return kind
