"""The landing law, once, across every attach owner (ADR core-20's placement rule).

An attachment lands at its SUBJECT's organization; a TENANT-WIDE subject has
none, so the attachment lands at the ACTING HAT — never the root. Down-only
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
