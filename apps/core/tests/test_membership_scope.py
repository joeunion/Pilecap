# census: cross-app population=apps/core/**/*.py for a bare Membership read
"""`Membership` is read through a manager house rule 8 can see, and fails closed.

`Membership` inherits `BaseModel`, not `TenantScopedModel`, so it carries its
own `MembershipQuerySet`: `.for_tenant(tenant)` for a tenant's rows and
`.of(user)` for one person's (`manage.py roads membership_read`). These tests
hold three things:

* **It fails closed exactly as the scoped manager does**: an unresolved tenant
  (or person) reads an empty queryset — no query, never the table.
* **The role chain runs down only** (`core.authz.chain_over`): a membership on
  an ancestor reaches a child node; a membership on the child never reaches
  its parent.
* **No bare read in core**: `Membership.objects.filter(` appears under
  `apps/core` (tests and migrations excluded) only inside the manager's own
  module. Until the quality engine widens house rule 8's population to the
  declared member, this census IS the enforcement.

DOES NOT COVER — declared: a read through a related manager
(`user.memberships.filter(...)`) is not `Membership.objects.filter(` and the
census does not see it; the manager's fail-closed half is proven here by a
unit test, not by a door driven with no tenant. Migrations are excluded by
name: a merged migration is never edited, and its historical model reads the
table as it stood.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.core.actor import actor_for, system_actor
from apps.core.authz import chain_over, memberships_in
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.core.tests.tree_census import source_lines

pytestmark = pytest.mark.django_db

#: The bare read the census refuses outside the manager's module.
BARE_READ = re.compile(r"\bMembership\.objects\.filter\(")

#: The module that holds the manager — the one place the shape may appear.
MANAGER_MODULE = "apps/core/models.py"


def test_an_unresolved_tenant_reads_nothing_as_the_scoped_manager_does(
    tenant: Tenant, owner: User
) -> None:
    assert Membership.objects.for_tenant(tenant).exists()
    scoped = Membership.objects.for_tenant(None)
    reference = Organization.objects.for_tenant(None)
    assert scoped.query.is_empty() and reference.query.is_empty()
    assert list(scoped) == [] and list(reference) == []


def test_an_unresolved_person_reads_nothing(tenant: Tenant, owner: User) -> None:
    assert Membership.objects.of(owner).exists()
    assert Membership.objects.of(None).query.is_empty()


def test_the_two_scopes_compose_to_one_person_in_one_tenant(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    add_membership(
        user=owner, tenant=other_tenant, role="member", actor=system_actor(tenant=other_tenant)
    )
    mine_here = Membership.objects.for_tenant(tenant).of(owner)
    assert {m.tenant_id for m in mine_here} == {tenant.pk}
    assert {m.tenant_id for m in Membership.objects.of(owner)} == {tenant.pk, other_tenant.pk}


def test_the_chain_runs_down_only(tenant: Tenant, owner: User) -> None:
    root = Organization.objects.for_tenant(tenant).get(depth=0)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    child = create_organization(tenant=tenant, parent=root, name="C", slug="c", actor=acting)
    rows = memberships_in(owner, tenant)
    on_root = [m for m in rows if m.organization_id == root.pk]
    assert on_root, "the owner's membership sits on the root"
    # The ancestor's row reaches the child node...
    assert list(chain_over(rows, child)) == on_root
    # ...and a row on the child never reaches its parent.
    on_child = add_membership(
        user=User.objects.create(email="leaf@example.com"),
        tenant=tenant,
        organization=child,
        role="member",
        actor=acting,
    )
    leaf_rows = memberships_in(on_child.user, tenant)
    assert list(chain_over(leaf_rows, child)) == leaf_rows
    assert list(chain_over(leaf_rows, root)) == []


def _bare_reads(root: Path) -> list[str]:
    """Every `Membership.objects.filter(` under `root`, tests and migrations excluded."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root.parent.parent)
        if "tests" in relative.parts or "migrations" in relative.parts:
            continue
        for number, line in enumerate(source_lines(path), start=1):
            if BARE_READ.search(line):
                found.append(f"{relative.as_posix()}:{number}")
    return found


def test_no_bare_membership_filter() -> None:
    core = Path(settings.BASE_DIR) / "apps" / "core"
    stray = [hit for hit in _bare_reads(core) if not hit.startswith(f"{MANAGER_MODULE}:")]
    assert stray == [], stray


def test_the_census_reds_on_a_planted_bare_read(tmp_path: Path) -> None:
    """The negative: a scratch app with one bare read is found by the same census."""
    services = tmp_path / "apps" / "zzz_probe" / "services.py"
    services.parent.mkdir(parents=True)
    services.write_text("rows = Membership.objects.filter(user_id=1)\n")
    assert _bare_reads(tmp_path / "apps" / "zzz_probe") == ["apps/zzz_probe/services.py:1"]
