"""The partition's read census judges a built path against the closure's own population."""

# does-not-cover: the live tree's census — `python -m quality.partition selftest` is that pin.

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality import partition

pytestmark = pytest.mark.drives("quality/partition.py")

TEST_MODULE = (
    "from pathlib import Path\n"
    "\n"
    "ROOT = Path(__file__).resolve().parents[3]\n"
    "\n"
    "\n"
    "def test_reads() -> None:\n"
    '    assert (ROOT / "{target}").exists()\n'
)


def _world(scratch_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, target: str) -> Path:
    """A scratch repository whose one platform test builds `ROOT / target`; `.env` ignored."""
    repo = scratch_repo("census")
    module = repo / "apps" / "core" / "tests" / "test_reads.py"
    module.parent.mkdir(parents=True)
    module.write_text(TEST_MODULE.format(target=target))
    (repo / ".gitignore").write_text(".env\n")
    (repo / ".env").write_text("LOCAL=1\n")
    (repo / "notes").mkdir()
    (repo / "notes" / "uncovered.txt").write_text("tracked, in no class\n")
    (repo / "apps" / "core" / "models.py").write_text("")
    for argv in (
        ["add", ".gitignore", "apps/core/tests/test_reads.py", "apps/core/models.py"],
        ["add", "notes/uncovered.txt"],
        ["commit", "-q", "-m", "world"],
    ):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)
    monkeypatch.setattr(partition, "ROOT", repo)
    monkeypatch.setattr(partition, "closure_members", lambda: {"C1": ("apps/core/models.py",)})
    monkeypatch.setattr(partition, "_platform_test_modules", lambda: [module])
    return repo


def test_a_git_ignored_file_a_platform_test_builds_is_not_reported(
    scratch_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _world(scratch_repo, monkeypatch, ".env")
    assert (repo / ".env").exists()
    assert partition.read_census() == []


def test_a_tracked_file_no_class_covers_is_still_reported(
    scratch_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _world(scratch_repo, monkeypatch, "notes/uncovered.txt")
    assert partition.read_census() == [
        "apps/core/tests/test_reads.py reads notes/uncovered.txt, which no closure class covers"
    ]
