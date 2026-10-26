"""The product modules the gate imports are leaves: each imports with Django blocked."""

# does-not-cover: a Django import inside a leaf's function — the probe imports, never calls.

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.drives(
    "apps/core/roads.py",
    "apps/core/reach.py",
    "apps/core/reason_floor.py",
    "apps/core/lexicon.py",
    "config/settings/discovery.py",
)

ROOT = Path(__file__).resolve().parents[2]

#: The product modules `quality/` imports at its own import time: stdlib + `yaml` only.
LEAVES = (
    "apps.core.roads",
    "apps.core.reach",
    "apps.core.reason_floor",
    "apps.core.lexicon",
    "config.settings.discovery",
)
#: Packages a leaf's import passes through on the way, which execute nothing of their own here.
PACKAGES = ("apps", "apps.core", "config", "config.settings")
#: `yaml`, its C extension and the Cython runtime that extension loads.
YAML = frozenset({"yaml", "_yaml", "cython_runtime"})

PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
sys.modules["django"] = None
before = set(sys.modules)
import importlib
error = None
try:
    importlib.import_module(sys.argv[2])
except ImportError as exc:
    error = f"{type(exc).__name__}: {exc}"
loaded = sorted(set(sys.modules) - before)
print(json.dumps({"error": error, "loaded": loaded}))
"""


def _probe(module: str) -> dict[str, object]:
    done = subprocess.run(
        [sys.executable, "-I", "-P", "-c", PROBE, str(ROOT), module],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, object] = json.loads(done.stdout)
    return result


def _foreign(loaded: list[str]) -> list[str]:
    """The loaded modules that are neither stdlib, `YAML`, a leaf nor a package on a leaf's path."""
    own = set(LEAVES) | set(PACKAGES)
    return [
        name
        for name in loaded
        if name not in own
        and name.split(".")[0] not in sys.stdlib_module_names
        and name.split(".")[0] not in YAML
        and not name.startswith("_cython_")
    ]


@pytest.mark.parametrize("module", LEAVES)
def test_a_leaf_imports_with_django_blocked(module: str) -> None:
    """Under `python -I -P` with `django` blocked it imports, loading only stdlib, YAML, leaves."""
    found = _probe(module)
    assert found["error"] is None, f"{module} is no leaf: {found['error']}"
    loaded = found["loaded"]
    assert isinstance(loaded, list)
    assert _foreign(loaded) == [], f"{module} loads {_foreign(loaded)}"


def test_the_probe_sees_a_module_that_drags_django() -> None:
    """A module that imports Django is refused by the same probe, so a green leaf is a real one."""
    found = _probe("apps.core.lifecycle")
    assert "django" in str(found["error"]), found
