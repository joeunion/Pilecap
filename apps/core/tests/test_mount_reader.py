"""The mount has one reader, so one cut reds every reader of it.

`apps.core.api.mount.bound_operations` (`manage.py roads mount_read`) is the
one walk over what the API mounted. The family's acts
(`verbs.mounted_operations`), the system checks (`checks._mounted_paths`, and
through it rules 3, 17, 32 and 83), `introspect`'s routes, the MCP scope
derivation and the welcome page read it. ADR core-24's sentence — three private
re-derivations of one fact drift apart silently — is the reason: when each
reader walked the mount its own way they agreed, and a SEVERED reader was a red
only one caller noticed.

So the demonstration severs the reader: it drops one operation from
`bound_operations` and asserts every reader loses that operation. Restored, all
of them agree on the whole mount again.

DOES NOT COVER — declared: a reader that walks the mount without calling the
seam (none in core today; `test_discovery.py`'s census is the walk's own) — the
cut proves the readers that call it, not the absence of a reader that does not.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from dataclasses import astuple
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from apps.core import checks, route_table, script_source, verbs
from apps.core.api import mount
from apps.core.management.commands.introspect import _routes_payload
from apps.core.tests.tree_census import source_text


def _the_cut() -> tuple[str, str, Any]:
    """One named operation to sever: the first the mount binds."""
    return next(entry for entry in mount.bound_operations() if entry[1])


def _readers() -> dict[str, set[str]]:
    """What each reader of the mount says it holds, as `url_name`s."""
    return {
        "verbs.mounted_operations": set(verbs.mounted_operations()),
        "checks._mounted_paths": {
            str(operation.url_name) for _path, operation in checks._mounted_paths()
        },
        "introspect.routes": {
            str(route["name"]).removeprefix("api:") for route in _routes_payload() if route["name"]
        },
    }


def test_every_reader_reads_the_whole_mount() -> None:
    held = {name for _path, name, _operation in mount.bound_operations() if name}
    assert held, "the mount binds no named operation — this test would pass vacuously"
    readers = _readers()
    assert all(found == held for found in readers.values()), {
        reader: sorted(held ^ found) for reader, found in readers.items()
    }


def test_one_cut_reds_every_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    whole = mount.bound_operations()
    _path, severed, _operation = _the_cut()

    def cut() -> list[tuple[str, str, Any]]:
        return [entry for entry in whole if entry[1] != severed]

    monkeypatch.setattr(mount, "bound_operations", cut)
    lost = {reader: severed not in found for reader, found in _readers().items()}
    assert lost == dict.fromkeys(lost, True), lost


#: The deployed image's shape: `.dockerignore` keeps `quality/` out, so no check may import it.
IMAGE_SHAPE = """
import importlib.abc, sys
class Absent(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "quality" or name.startswith("quality."):
            raise ModuleNotFoundError(f"No module named {name!r}")
sys.meta_path.insert(0, Absent())
import django
django.setup()
from django.core import checks
checks.run_checks()
"""


def test_the_system_checks_import_nothing_the_image_does_not_carry() -> None:
    """Every system check runs with `quality` unimportable, as `manage.py` does in the image."""
    child = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, "-c", IMAGE_SHAPE],
        cwd=settings.BASE_DIR,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 0, child.stderr[-2000:]


def test_the_image_reader_is_rule_71s_reader() -> None:
    """The image's route-table reader is rule 71's: one table, one row shape, one scan."""
    # By name: the engine sits outside the strict type check, so what crosses is `Any`.
    _source: Any = importlib.import_module("quality.runners._source")
    js_route_table: Any = importlib.import_module("quality.runners.js_route_table")

    ours = (route_table.TABLE, route_table.ROW.pattern, route_table.PATH.pattern)
    theirs = (js_route_table.TABLE, js_route_table.ROW.pattern, js_route_table.PATH.pattern)
    assert ours == theirs
    scripts = sorted(Path(settings.BASE_DIR, "frontend", "src").rglob("*.ts*"))
    assert scripts
    for script in scripts:
        raw = source_text(script)
        code, blank, literals = script_source.scan(raw)
        want_code, want_blank, want_literals = _source.scan(raw)
        assert (code, blank) == (want_code, want_blank), script
        assert [astuple(lit) for lit in literals] == [astuple(lit) for lit in want_literals], script
