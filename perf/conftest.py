"""pytest wiring for the perf package (ADR perf-1).

Three jobs, all structural:

1. **Point pytest at the seeded world.** The `django_db_setup` override below
   creates no `test_` database and tears nothing down: measurements run
   against the per-checkout `_perf` database `scripts/perf.sh` seeded, and
   refuse (session-wide, loudly) a database whose name lacks the `_perf`
   suffix or whose stamp does not match the active spec — a measurement of a
   stale or foreign world is the 955-error class wearing a lab coat.

2. **Everything here is `perf`.** Every collected item gains the `perf`
   marker, so `pytest -m perf` (what `perf.sh` runs) selects all of it and
   the default suite (whose `testpaths = ["apps"]` never reaches this
   directory) collects none of it.

3. **The instrument refuses vibes.** Every module collected out of this
   directory is scanned by `measure.refuse_wall_clock_assertions` before it
   imports; an assertion phrased in seconds dies naming the refusal.

Note for measurement modules: `perf.sh` passes them as explicit file
arguments (`perf/measure_*.py` does not match `python_files`, deliberately —
directory discovery can never pick a measurement up into another run).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from perf import measure
from perf.seed import LOADED_SLUGS, require_perf_database, seeded_spec

HERE = Path(__file__).resolve().parent


def pytest_pycollect_makemodule(module_path: Path, parent: Any) -> None:
    """Refuse wall-clock assertions before the module imports."""
    if Path(module_path).resolve().is_relative_to(HERE):
        measure.refuse_wall_clock_assertions(module_path)
    return None  # the default Module collector


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every item under perf/ carries the `perf` marker."""
    for item in items:
        if Path(str(item.fspath)).resolve().is_relative_to(HERE):
            item.add_marker(pytest.mark.perf)


@pytest.fixture(scope="session")
def django_db_setup() -> None:
    """Use the seeded `_perf` database as-is: create nothing, destroy nothing.

    Overriding pytest-django's fixture with a no-op is the documented way to
    run against an existing database; the name it runs against is whatever
    `DATABASE_NAME` the settings derived — `scripts/perf.sh` exports the
    `_perf` one, and the guard fixture below refuses anything else.
    """


@pytest.fixture(scope="session", autouse=True)
def _seeded_world(django_db_setup: None, django_db_blocker: Any) -> Any:
    """Refuse to measure a world no declared spec describes.

    The stamp tenant's slug embeds the spec hash and the recognizable
    population is closed (the default spec + every single-axis doubling), so
    the world is self-describing: a stale world (ScaleSpec edited, database
    not re-seeded) or a half-seeded one fails every measurement up front
    with the reason, instead of producing numbers about a fixture nobody
    declared. Returns the world's spec; the `spec` fixture republishes it.
    """
    with django_db_blocker.unblock():
        require_perf_database()
        try:
            return seeded_spec()
        except RuntimeError as refusal:
            pytest.fail(str(refusal), pytrace=False)


@pytest.fixture(scope="session")
def spec(_seeded_world: Any) -> Any:
    """The ScaleSpec of the seeded world this run measures — read off its stamp."""
    return _seeded_world


@pytest.fixture()
def loaded_tenants(db: None) -> list[Any]:
    """The two loaded twins, by slug order (perf-a, perf-b)."""
    from apps.core.models import Tenant

    return list(Tenant.objects.filter(slug__in=LOADED_SLUGS).order_by("slug"))
