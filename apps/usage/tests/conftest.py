"""The world every usage test is measured against, and the meter it spends.

**A declared meter is the interesting fixture here**, because this app's whole
vocabulary belongs to apps that do not exist yet: ADR usage-1 names
`files.storage.bytes` and `completions.tokens.input`, and both arrive in later
rungs. So the tests declare a meter the way a real app would — a constant in a
real `meters.py`, discovered off the live app registry — rather than teaching
`record_usage` to trust a string nobody declared.

Two ways, deliberately, because they prove different things:

* `declared_meter` **plants a real file** on disk in an installed app and
  invalidates the import caches, so the discovery walk is the real one. That is
  the only way to prove the walk finds a module it has never seen;
* `a_declared_meter` **replaces the registry function** for the tests whose
  subject is the ledger rather than the vocabulary. Faster, and it keeps a
  hundred assertions from depending on a file this directory writes.

Every row is written by the service that really writes it rather than by
`objects.create`, so the shapes are the shapes production makes.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.usage import meters as meters_module

#: A literal a fixture hands to `create_user`, long enough to clear Django's
#: validators and nothing else.
PASSWORD = "a-long-enough-password-for-validators"  # pragma: allowlist secret

#: The meter these tests spend. It belongs to `example`, which is the app the
#: plant below lives in — the first segment of a meter name is the declaring
#: app's label, and a fixture that broke that rule would be testing a name the
#: boot check refuses.
METER = "example.widgets.count"

#: A second one, so "this meter's total" can be wrong by including another's.
OTHER_METER = "example.widgets.seconds"

#: Where the planted `meters.py` goes. `apps/example` rather than `apps/usage`:
#: a meter is declared by the app that SPENDS it, and planting into this app
#: would make the registry's most important property — that it finds somebody
#: else's file — untested.
_PLANT = Path(__file__).resolve().parents[2] / "example" / "meters.py"

_PLANT_SOURCE = '''"""Planted by apps/usage/tests/conftest.py. Removed by the same fixture."""

WIDGETS_COUNT = "example.widgets.count"
WIDGETS_SECONDS = "example.widgets.seconds"
'''


def plant_meters(source: str, *, at: Path = _PLANT) -> None:
    """Write a `meters.py` where discovery will find it, caches invalidated.

    `importlib.invalidate_caches()` is not optional: `find_spec` caches a
    package's directory listing, so a module created after the first import in
    this process is invisible without it — and the test would pass for the wrong
    reason, having proved that discovery finds nothing.

    **Written under another name and `os.replace`d into position**, because
    every tree-walking census in the suite is running on another xdist worker
    while this file exists (`apps/core/tests/tree_census.py` has the argument).
    A plain `write_text` truncates and then fills, so a census could read a
    half-written module and report a `SyntaxError` that describes nothing in
    the tree; `os.replace` within one directory is atomic, so the file is
    complete or absent and never in between. The *absent* half is what the
    tolerant read on the census side is for — nothing here can close that,
    because `unlink` is already a single syscall.
    """
    building = at.with_name(f".{at.name}.building")
    building.write_text(source)
    os.replace(building, at)
    sys.modules.pop(f"apps.{at.parent.name}.meters", None)
    importlib.invalidate_caches()


def unplant_meters(*, at: Path = _PLANT) -> None:
    """Take it away again, whatever happened. A leaked plant is a novel module
    name in somebody else's app, which is a house-rule-11 violation the next
    person to run the gate would inherit."""
    at.unlink(missing_ok=True)
    sys.modules.pop(f"apps.{at.parent.name}.meters", None)
    importlib.invalidate_caches()


@pytest.fixture
def declared_meter() -> Iterator[str]:
    """A meter declared in a REAL `meters.py`, discovered by the real walk."""
    plant_meters(_PLANT_SOURCE)
    try:
        yield METER
    finally:
        unplant_meters()


@pytest.fixture
def a_declared_meter(monkeypatch: pytest.MonkeyPatch) -> str:
    """The registry, answered without touching the filesystem.

    `check_meter` reads `declared_meters` out of its own module namespace at call
    time, so replacing the function here exercises every line of the checking
    itself — the grammar, the app-label lookup and the membership test — against
    a registry the test controls.
    """
    monkeypatch.setattr(
        meters_module,
        "declared_meters",
        lambda: {"example": frozenset({METER, OTHER_METER})},
    )
    return METER


@dataclass(frozen=True)
class World:
    """One tenant with a two-branch tree, plus the row usage points at.

    `north` and `south` are siblings under the root, which is the smallest tree
    in which the anti-oracle can fail: a report taken at `north` must not tally
    `south`'s consumption, and the root's must tally both.
    """

    tenant: Tenant
    root: Organization
    north: Organization
    south: Organization
    owner: User
    north_admin: User
    root_actor: Actor
    north_actor: Actor
    south_actor: Actor
    widget: Widget


@pytest.fixture
def world(tenant: Tenant, owner: User, root_org: Organization) -> World:
    """A tenant, two branches and somebody who can only see one of them."""
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    north = create_organization(
        tenant=tenant, parent=root_org, name="North", slug="north", actor=acting
    )
    south = create_organization(
        tenant=tenant, parent=root_org, name="South", slug="south", actor=acting
    )
    north_admin = create_user(email="north-admin@acme.com", password=PASSWORD)
    add_membership(
        user=north_admin,
        tenant=tenant,
        organization=north,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=acting,
    )
    widget = create_widget(tenant=tenant, actor=acting, name="The thing being metered")
    return World(
        tenant=tenant,
        root=root_org,
        north=north,
        south=south,
        owner=owner,
        north_admin=north_admin,
        root_actor=acting,
        north_actor=actor_for(user=north_admin, tenant=tenant, org=north),
        south_actor=actor_for(user=owner, tenant=tenant, org=south),
        widget=widget,
    )
