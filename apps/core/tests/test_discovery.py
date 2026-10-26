"""The one discovery walk: `core.discovery`, and the installed set it honours.

`apps.core.discovery.declared` (`manage.py roads discover`) is the walk every
core reader of a conventionally named module calls — `TAGS`, the policies and
roles, the family hooks, the lifecycle and integrations censuses, the events,
the services. These tests hold three things:

* **It sees a product app the day it lands**: a throwaway app `zzz_probe` with
  an `events.py` declaring `EVENTS`, installed the way settings install an app
  (`config.settings.discovery.discover_local_apps`, the `installed_apps` road),
  is in `declared("events", "EVENTS")` with nothing edited anywhere.
* **It honours `DJB_DISABLED_APPS`**: the same plant, switched off through the
  same derivation, is not walked — the app is not installed, so nothing reads it.
* **It is the only walk in core**: every `find_spec(` under `apps/core` (tests
  excluded) is in `discovery.py`, except `newapp.py`, which asks whether a NEW
  app's name is free — a question about a module that must NOT exist yet, not
  a walk over the ones that do. Until the quality engine's discovery-loop class
  reads this shape for core, this census IS the enforcement.

**The plant never touches the checkout.** The probe is built under `tmp_path`
and joined to the `apps` package's search path for the test's length, so a
parallel worker scanning `apps/` never sees a half-written or vanishing app —
the demonstration creates its own victim and removes it.

DOES NOT COVER — declared: a module created after its package was imported in
a long-lived process (the probe is `find_spec`, which reads the import
system's caches — the plant invalidates them itself).
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

import apps as apps_package
from apps.core.discovery import declared, declared_services
from apps.core.tests.tree_census import source_lines
from config.settings.discovery import discover_local_apps

PROBE = "zzz_probe"
PROBE_MODULE = f"apps.{PROBE}"
PROBE_EVENT = f"{PROBE}.thing.happened"
PROBE_APPS_PY = f"""from typing import ClassVar

from django.apps import AppConfig


class ZzzProbeConfig(AppConfig):
    name = "{PROBE_MODULE}"
    optional: ClassVar[bool] = True
    depends_on: tuple[str, ...] = ("core",)
"""

#: The walk's shape in a source line: a submodule probed by name.
WALK_SHAPE = re.compile(r"find_spec\(")

#: The one module allowed the shape besides the walk itself, and why.
NOT_A_WALK = {"apps/core/management/commands/newapp.py": "asks whether a NEW app's name is free"}


@pytest.fixture
def probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """`apps.zzz_probe`, importable for this test only, on disk under `tmp_path`."""
    root = tmp_path / "apps"
    app = root / PROBE
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "apps.py").write_text(PROBE_APPS_PY)
    (app / "events.py").write_text(f'EVENTS = {{"{PROBE_EVENT}": "A thing happened."}}\n')
    # A probe of this name another test imported and left behind would shadow
    # this one (its `__path__` names a directory that is gone), so drop it first.
    for name in [m for m in sys.modules if m == PROBE_MODULE or m.startswith(f"{PROBE_MODULE}.")]:
        del sys.modules[name]
    monkeypatch.setattr(apps_package, "__path__", [*apps_package.__path__, str(root)])
    importlib.invalidate_caches()
    try:
        yield root
    finally:
        for name in [
            m for m in sys.modules if m == PROBE_MODULE or m.startswith(f"{PROBE_MODULE}.")
        ]:
            del sys.modules[name]
        importlib.invalidate_caches()


#: A `services/` package: the member defines the service, the `__init__` re-exports it.
PROBE_SERVICES = {
    "services/__init__.py": f"from {PROBE_MODULE}.services.people import enrol\n",
    "services/people.py": '''"""The probe's one service."""

from apps.core.service import service


@service
def enrol(*, name: str) -> str:
    """Enrol a person."""
    return name
''',
}


def _installed(root: Path, disabled: str) -> list[str]:
    """`INSTALLED_APPS` with the plant's directory derived the way settings derive `apps/`."""
    switched_off = [label for label in disabled.split(",") if label.strip()]
    return [*settings.INSTALLED_APPS, *discover_local_apps(root, switched_off)]


def _probe_events() -> list[object]:
    return [value for config, value in declared("events", "EVENTS") if config.label == PROBE]


def test_a_planted_app_is_walked_the_day_it_lands(probe: Path) -> None:
    with override_settings(INSTALLED_APPS=_installed(probe, disabled="")):
        assert _probe_events() == [{PROBE_EVENT: "A thing happened."}]
    assert _probe_events() == []


def test_a_switched_off_app_is_not_walked(probe: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJB_DISABLED_APPS", PROBE)
    with override_settings(INSTALLED_APPS=_installed(probe, os.environ["DJB_DISABLED_APPS"])):
        assert PROBE_MODULE not in settings.INSTALLED_APPS
        assert _probe_events() == []


def test_a_services_package_declares_what_its_init_re_exports(probe: Path) -> None:
    (probe / PROBE / "services").mkdir()
    for name, text in PROBE_SERVICES.items():
        (probe / PROBE / name).write_text(text)
    with override_settings(INSTALLED_APPS=_installed(probe, disabled="")):
        found = [
            (config.label, name, function.__module__)
            for config, name, function in declared_services()
            if config.label == PROBE
        ]
    assert found == [(PROBE, "enrol", f"{PROBE_MODULE}.services.people")]


def _walks(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root.parent.parent).as_posix()
        if "/tests/" in relative or "/migrations/" in relative:
            continue
        if any(WALK_SHAPE.search(line) for line in source_lines(path)):
            found.append(relative)
    return found


def test_core_has_one_discovery_walk() -> None:
    walks = _walks(Path(settings.BASE_DIR) / "apps" / "core")
    assert [w for w in walks if w not in NOT_A_WALK] == ["apps/core/discovery.py"], walks


def test_the_walk_census_sees_a_planted_copy(tmp_path: Path) -> None:
    """The negative: a second walk written beside the census is found by it."""
    stray = tmp_path / "apps" / "zzz_walker" / "selectors.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("spec = importlib.util.find_spec(name)\n")
    assert _walks(tmp_path / "apps" / "zzz_walker") == ["apps/zzz_walker/selectors.py"]
