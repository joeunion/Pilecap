"""The `quality -> apps` contract refuses a planted import and keeps a leaf's."""

# does-not-cover: the real tree's edges — the leg's own `lint-imports` run measures those.

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.drives("pyproject.toml", "quality/djb/legs/import_linter.py")

ROOT = Path(__file__).resolve().parents[2]
NAME = "the gate reads the product's leaves; nothing else of apps"
LINT = Path(sys.executable).with_name("lint-imports")


def _contract() -> dict[str, object]:
    """The contract as `pyproject.toml` declares it, found by its name."""
    doc = tomllib.loads((ROOT / "pyproject.toml").read_text())
    found = [c for c in doc["tool"]["importlinter"]["contracts"] if c["name"] == NAME]
    assert len(found) == 1, f"pyproject.toml declares {len(found)} contracts named {NAME!r}"
    return dict(found[0])


def _world(tmp_path: Path, planted: str) -> Path:
    """A scratch graph of the four root packages, with `quality.x` importing `planted`."""
    for package in ("apps", "apps/core", "config", "config/settings", "pilecap", "quality"):
        (tmp_path / package).mkdir(parents=True, exist_ok=True)
        (tmp_path / package / "__init__.py").write_text("")
    (tmp_path / "apps/core/roads.py").write_text("")
    (tmp_path / "apps/core/models.py").write_text("")
    (tmp_path / "quality/x.py").write_text(f"import {planted}\n")
    contract = {**_contract(), "unmatched_ignore_imports_alerting": "none"}
    toml = '[tool.importlinter]\nroot_packages = ["apps", "config", "quality", "pilecap"]\n\n'
    toml += "[[tool.importlinter.contracts]]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in contract.items()
    )
    (tmp_path / "pyproject.toml").write_text(toml)
    return tmp_path


def _lint(world: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(world)}
    return subprocess.run(
        [str(LINT), "--config", str(world / "pyproject.toml"), "--no-cache"],
        cwd=world,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_a_planted_import_of_the_product_is_refused(tmp_path: Path) -> None:
    """`quality.x -> apps.core.models` breaks the contract and the refusal names the edge."""
    done = _lint(_world(tmp_path, "apps.core.models"))
    assert done.returncode == 1, done.stdout + done.stderr
    assert "quality.x -> apps.core.models" in done.stdout, done.stdout


def test_an_import_of_a_leaf_is_kept(tmp_path: Path) -> None:
    """`quality.x -> apps.core.roads` is a declared leaf, so the same contract keeps it."""
    done = _lint(_world(tmp_path, "apps.core.roads"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"{NAME} KEPT" in done.stdout, done.stdout
