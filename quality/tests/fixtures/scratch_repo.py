"""The `scratch_repo` fixture: a throwaway repository on `main` with one base commit."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


def make_repo(path: Path, author: str = "drive") -> Path:
    """A fresh repository at `path`, no auto gc or maintenance; `CouldNotLook` if git refuses."""
    if path.exists():
        raise CouldNotLook(f"scratch_repo: {path} already exists — a repository is built fresh")
    path.mkdir(parents=True)
    steps = (
        ["init", "-q"],
        ["symbolic-ref", "HEAD", "refs/heads/main"],
        ["config", "user.email", f"{author}@example.invalid"],
        ["config", "user.name", author],
        ["config", "commit.gpgsign", "false"],
        ["config", "gc.auto", "0"],
        ["config", "maintenance.auto", "false"],
        ["commit", "-q", "--allow-empty", "-m", "base"],
    )
    for step in steps:
        done = subprocess.run(["git", "-C", str(path), *step], capture_output=True, text=True)
        if done.returncode != 0:
            raise CouldNotLook(
                f"scratch_repo: `git {' '.join(step)}` failed at {path}: {done.stderr.strip()}"
            )
    return path


@pytest.fixture
def scratch_repo(scratch: Path) -> Callable[..., Path]:
    """`scratch_repo(name="repo", author="drive")` builds one repository under `scratch`."""

    def build(name: str = "repo", author: str = "drive") -> Path:
        if not name or "/" in name or name in (".", ".."):
            raise CouldNotLook(f"scratch_repo: {name!r} is not one directory name")
        return make_repo(scratch / name, author)

    return build
