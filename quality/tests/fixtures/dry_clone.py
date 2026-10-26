"""The `dry_clone` fixture: one clone of HEAD per module, its own `main`, this interpreter lent."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.scratch import require_scratch

#: Where the clone's `main` comes from, in `drive_base_ref`'s order; HEAD when neither resolves.
BASE_REFS = ("refs/heads/main", "refs/remotes/origin/main")


def base_of(root: Path) -> str:
    """The sha `root`'s `main` names: its local branch, else `origin/main`, else its HEAD."""
    for ref in (*BASE_REFS, "HEAD"):
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if done.returncode == 0:
            return done.stdout.strip()
    raise CouldNotLook(f"dry_clone: {root} names no main, no origin/main and no HEAD")


def head_of(root: Path) -> str:
    """`root`'s HEAD commit; `CouldNotLook` when it has none."""
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"dry_clone: {root} has no HEAD to clone")
    return done.stdout.strip()


def clone_into(root: Path, dest: Path) -> Path:
    """A detached shared clone of `root`'s HEAD at `dest` whose local `main` is `base_of(root)`."""
    head = head_of(root)
    steps = (
        ["git", "clone", "-q", "--shared", "--no-hardlinks", "--no-checkout", str(root), str(dest)],
        ["git", "-C", str(dest), "checkout", "-q", "--detach", head],
        ["git", "-C", str(dest), "branch", "-f", "main", base_of(root)],
    )
    for argv in steps:
        done = subprocess.run(argv, capture_output=True, text=True)
        if done.returncode != 0:
            raise CouldNotLook(f"dry_clone: `{' '.join(argv)}` failed: {done.stderr.strip()}")
    # Invariant: the harness runs `-p no:django`, so `.env` is the only road to a database name.
    if (root / ".env").is_file():
        shutil.copy(root / ".env", dest / ".env")
    return dest


@pytest.fixture(scope="module")
def dry_clone(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[Path]:
    """A detached clone with `main`, `.venv` linked and an empty `lease/` beside it."""
    root = request.config.rootpath
    venv = root / ".venv"
    if not (venv / "bin" / "python").exists():
        raise CouldNotLook(f"dry_clone: {venv} has no interpreter to lend — run ./scripts/setup.sh")
    base = require_scratch(tmp_path_factory.mktemp("dry"), root)
    dest = clone_into(root, base / "clone")
    (dest / ".venv").symlink_to(venv)
    (base / "lease").mkdir()
    yield dest
    shutil.rmtree(dest, ignore_errors=True)
