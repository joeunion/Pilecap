"""The world every usage test is measured against, and the meter it spends.

**A declared meter is the interesting fixture here**, because this app's whole
vocabulary belongs to apps that do not exist yet: ADR usage-1 names
`files.storage.bytes` and `completions.tokens.input`, and both arrive in later
rungs. So the tests declare a meter the way a real app would — a constant in a
real `meters.py`, discovered off the live app registry — rather than teaching
`record_usage` to trust a string nobody declared.

Two ways, deliberately, because they prove different things:

* `declared_meter` **plants a real file** in an installed app's package, for
  this process only, and invalidates the import caches, so the discovery walk
  is the real one. That is the only way to prove the walk finds a module it has
  never seen;
* `a_declared_meter` **replaces the registry function** for the tests whose
  subject is the ledger rather than the vocabulary. Faster, and it keeps a
  hundred assertions from depending on a file this directory writes.

Every row is written by the service that really writes it rather than by
`objects.create`, so the shapes are the shapes production makes.
"""

from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.models import Organization
from apps.core.tests.permissions_world import World as World
from apps.core.tests.permissions_world import build_world
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.usage import meters as meters_module

#: A literal handed to `create_user`, long enough for Django's validators.
PASSWORD = "a-long-enough-password-for-validators"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret

#: The meter these tests spend. It belongs to `example`, which is the app the
#: plant below lives in — the first segment of a meter name is the declaring
#: app's label, and a fixture that broke that rule would be testing a name the
#: boot check refuses.
METER = "example.widgets.count"

#: A second one, so "this meter's total" can be wrong by including another's.
OTHER_METER = "example.widgets.seconds"

#: The package the plant is declared under. `apps/example` rather than
#: `apps/usage`: a meter is declared by the app that SPENDS it, and planting into
#: this app would make the registry's most important property — that it finds
#: somebody else's module — untested.
_PLANT_PACKAGE = "apps.example"

_PLANT_SOURCE = '''"""Planted by apps/usage/tests/conftest.py. Removed by the same fixture."""

WIDGETS_COUNT = "example.widgets.count"
WIDGETS_SECONDS = "example.widgets.seconds"
'''

#: The live plant, when there is one: the overlay directory and the package's
#: search path as it was before the overlay joined it.
_planted: list[tuple[Path, list[str]]] = []


def plant_meters(source: str) -> None:
    """Declare a `meters.py` in `apps.example` for THIS PROCESS ONLY.

    **Never written into the shared tree.** Every xdist worker runs out of one
    checkout, so a file under `apps/example/` is a file every worker's
    `declared_meters()` walks. The plant used to live there, and a worker
    recording usage for real (a `files` test metering stored bytes) found the
    module with `find_spec`, lost it to this fixture's `unlink` before
    `import_module` read it, and failed with `FileNotFoundError` on a test that
    had nothing to do with meters — one test in 2,707, under whichever schedule
    put the two on different workers at the same millisecond.

    So the module goes in a private directory appended to the package's own
    search path (`apps.example.__path__`). `declared_meters()` still does the
    real walk — the live app registry, `find_spec` by module name,
    `import_module` — and the import system still finds a module it has never
    seen in an app that is not this one; nothing else in any process can see it.
    What this does NOT exercise is the import system reading the package's
    first directory, which is Python's behaviour rather than this registry's.

    `importlib.invalidate_caches()` is not optional: `find_spec` caches
    directory listings, so a module created after the first lookup is invisible
    without it — and the test would pass for the wrong reason, having proved
    that discovery finds nothing.
    """
    unplant_meters()
    package = importlib.import_module(_PLANT_PACKAGE)
    overlay = Path(tempfile.mkdtemp(prefix="djb-meters-plant-"))
    (overlay / "meters.py").write_text(source)
    _planted.append((overlay, list(package.__path__)))
    package.__path__.append(str(overlay))
    sys.modules.pop(f"{_PLANT_PACKAGE}.meters", None)
    importlib.invalidate_caches()


def unplant_meters() -> None:
    """Take it away again, whatever happened — the search path restored, the
    overlay removed, the module forgotten, so the next walk in this process
    finds what the tree declares and nothing else."""
    package = importlib.import_module(_PLANT_PACKAGE)
    while _planted:
        overlay, original = _planted.pop()
        package.__path__[:] = original
        sys.path_importer_cache.pop(str(overlay), None)
        shutil.rmtree(overlay, ignore_errors=True)
    sys.modules.pop(f"{_PLANT_PACKAGE}.meters", None)
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


#: The name of the one row usage points at in a world.
METERED = "The thing being metered"


@pytest.fixture
def world() -> World:
    """Core's world (`root → A → A1 → A1X`, sibling `B`) and the widget usage points at."""
    built = build_world()
    create_widget(tenant=built.tenant, actor=built.owner, name=METERED)
    return built


def metered(world: World) -> Widget:
    """The row a world's usage points at."""
    return Widget.objects.filter(tenant=world.tenant).get(name=METERED)


def owner_at(world: World, org: Organization) -> Actor:
    """The world's owner wearing `org` as the hat."""
    return actor_for(user=user_of(world.owner), tenant=world.tenant, org=org)


def user_of(actor: Actor) -> User:
    """The person an actor of the world is."""
    assert isinstance(actor.user, User)
    return actor.user
