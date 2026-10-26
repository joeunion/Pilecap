# census: cross-app population=apps/**/*.py for the org-subtree predicate's spellings
"""The org-subtree predicate has one spelling, and `visible_to` is that spelling.

`apps.core.models.subtree_q` is the one road for "everything at or below this
node" (`manage.py roads subtree`). These tests hold three things about it:

* **It is `visible_to`'s own predicate**, row for row: an org-scoped read
  narrowed by `visible_to(child)` reaches exactly the rows whose organization
  `Organization.objects.filter(subtree_q(child))` names.
* **Down only** (A5a): the parent and the sibling never match.
* **It is the only spelling in core**: the census below reads `apps/core` for
  the predicate's shape — a `__startswith` lookup over a path joined to
  `PATH_SEPARATOR` — and finds it once, inside `subtree_q`. Until the quality
  engine carries a rule for the shape, this census IS the enforcement.

DOES NOT COVER — declared: a subtree read spelled without `PATH_SEPARATOR`
(a raw string `"."`, or a hand `LIKE` in SQL) is not the census's shape; the
two copies outside core (`apps/realtime`, `apps/search`) are their own apps'
to adopt, and the census prints them as a note rather than failing on them.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.core.actor import actor_for
from apps.core.models import Invitation, Organization, Tenant, subtree_q
from apps.core.services import create_organization, root_organization
from apps.core.tests.tree_census import source_lines
from apps.core.time import now

pytestmark = pytest.mark.django_db

#: The predicate's shape: a `__startswith` lookup whose prefix is joined to the
#: path separator. A line under `apps/core` (tests excluded) matching it is a
#: spelling of the subtree predicate.
SUBTREE_SHAPE = re.compile(r"__startswith.*PATH_SEPARATOR")


class Tree:
    """root → child → grandchild, and the child's sibling."""

    def __init__(self, tenant: Tenant, owner: User) -> None:
        self.root = root_organization(tenant=tenant)
        acting = actor_for(user=owner, tenant=tenant, org=self.root)
        self.child = create_organization(
            tenant=tenant, parent=self.root, name="Child", slug="child", actor=acting
        )
        self.sibling = create_organization(
            tenant=tenant, parent=self.root, name="Sibling", slug="sibling", actor=acting
        )
        self.grandchild = create_organization(
            tenant=tenant, parent=self.child, name="Grandchild", slug="grandchild", actor=acting
        )
        self.nodes = (self.root, self.child, self.sibling, self.grandchild)


@pytest.fixture
def tree(tenant: Tenant, owner: User) -> Tree:
    return Tree(tenant, owner)


def _invite_at_every_node(tenant: Tenant, owner: User, tree: Tree) -> None:
    """One org-scoped row per node — set-up through the bare manager, as tests may."""
    for index, node in enumerate(tree.nodes):
        Invitation.objects.create(
            tenant=tenant,
            organization=node,
            email=f"person{index}@example.com",
            token_hash=f"{index:064d}",
            expires_at=now() + timedelta(days=1),
            invited_by=owner,
        )


def test_visible_to_is_the_subtree_predicate_row_for_row(
    tenant: Tenant, owner: User, tree: Tree
) -> None:
    _invite_at_every_node(tenant, owner, tree)
    seen = set(
        Invitation.objects.for_tenant(tenant)
        .visible_to(tree.child)
        .values_list("organization_id", flat=True)
    )
    nodes = set(
        Organization.objects.for_tenant(tenant)
        .filter(subtree_q(tree.child))
        .values_list("pk", flat=True)
    )
    assert seen == nodes == {tree.child.pk, tree.grandchild.pk}


def test_the_subtree_runs_down_only(tenant: Tenant, tree: Tree) -> None:
    below_child = set(Organization.objects.for_tenant(tenant).filter(subtree_q(tree.child)))
    assert tree.root not in below_child
    assert tree.sibling not in below_child
    below_root = set(Organization.objects.for_tenant(tenant).filter(subtree_q(tree.root)))
    assert below_root == set(tree.nodes)


def test_an_unresolved_node_reaches_nothing(tenant: Tenant, tree: Tree) -> None:
    assert not Organization.objects.for_tenant(tenant).filter(subtree_q(None)).exists()


def _spellings(root: Path) -> list[str]:
    """Every non-test line under `root` that spells the subtree predicate."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(settings.BASE_DIR)
        if "tests" in relative.parts or "migrations" in relative.parts:
            continue
        for number, line in enumerate(source_lines(path), start=1):
            if SUBTREE_SHAPE.search(line):
                found.append(f"{relative}:{number}")
    return found


def test_one_subtree_predicate_in_core() -> None:
    """`apps/core` spells the predicate once, inside `subtree_q`; elsewhere is a note."""
    base = Path(settings.BASE_DIR)
    in_core = _spellings(base / "apps" / "core")
    assert len(in_core) == 1, in_core
    assert in_core[0].startswith("apps/core/models.py:"), in_core
    tree_wide = _spellings(base / "apps")
    print(f"note: the subtree predicate is spelled {len(tree_wide)} times under apps/: {tree_wide}")


def test_the_census_sees_a_planted_copy() -> None:
    """The negative: the shape the census reads fires on a copy written beside it."""
    planted = "Q(path__startswith=org.path + PATH_SEPARATOR)"
    assert SUBTREE_SHAPE.search(planted)
    assert not SUBTREE_SHAPE.search("Q(path=org.path)")
