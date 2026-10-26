"""A ratchet recorded above its count, in an app the change touches, is the change's to lower."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.engine.run import touched_apps, touched_headroom

pytestmark = pytest.mark.drives("quality/engine/run.py", "quality/engine/cli.py")

RULE = {"id": "91", "ratchets": {"example.block-tail": 5, "core.block-tail": 4}}


def test_a_touched_apps_floor_above_its_count_prints_the_lower_line() -> None:
    held = {"example.block-tail": (3, 3), "core.block-tail": (1, 1)}
    assert touched_headroom(RULE, held, {"example"}) == [
        "rule 91 ratchet: class 'example.block-tail' is recorded at 5 and this tree holds 3 —"
        " headroom in an app this change touches. Lower it to 3 in apps/example/apps.py"
    ]
    assert touched_headroom(RULE, {"example.block-tail": (5, 5)}, {"example"}) == []
    assert touched_headroom(RULE, held, set()) == []


def test_the_touched_apps_are_the_diffs_and_the_untracked(
    scratch_repo: Callable[..., Path],
) -> None:
    root = scratch_repo("headroom", "touched apps")
    (root / "apps/mid").mkdir(parents=True)
    (root / "apps/mid/services.py").write_text("base\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "base"], check=True)
    (root / "apps/mid/services.py").write_text("changed\n")
    (root / "apps/new").mkdir()
    (root / "apps/new/models.py").write_text("new\n")
    assert touched_apps(root, "HEAD") == {"mid", "new"}
