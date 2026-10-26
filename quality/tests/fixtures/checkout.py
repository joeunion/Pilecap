"""The `checkout` fixture: a detached worktree of HEAD in scratch, removed at teardown."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


def add_checkout(root: Path, dest: Path) -> Path:
    """A detached worktree of `root`'s HEAD at `dest` with its `.env`; `CouldNotLook` if none."""
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    if head.returncode != 0:
        raise CouldNotLook(f"checkout: {root} has no HEAD to check out")
    added = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "worktree",
            "add",
            "-q",
            "--detach",
            str(dest),
            head.stdout.strip(),
        ],
        capture_output=True,
        text=True,
    )
    if added.returncode != 0:
        raise CouldNotLook(
            f"checkout: git could not add a worktree at {dest}: {added.stderr.strip()}"
        )
    # Invariant: the harness runs `-p no:django`, so `.env` is the only road to a database name.
    if (root / ".env").is_file() and not (dest / ".env").exists():
        shutil.copy(root / ".env", dest / ".env")
    return dest


def remove_checkout(root: Path, dest: Path) -> None:
    """Remove the worktree at `dest` and prune its record from `root`."""
    subprocess.run(
        ["git", "-C", str(root), "worktree", "remove", "--force", str(dest)], capture_output=True
    )
    subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)


@pytest.fixture
def checkout(scratch: Path, request: pytest.FixtureRequest) -> Iterator[Path]:
    """A whole checkout of HEAD for the end-to-end cases that need one."""
    root = request.config.rootpath
    dest = add_checkout(root, scratch / "checkout")
    yield dest
    remove_checkout(root, dest)
