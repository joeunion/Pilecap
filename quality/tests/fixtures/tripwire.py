"""The `tripwire` fixture: the real repository fingerprinted at session start and end."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def fingerprint(root: Path) -> dict[str, str]:
    """HEAD, its ref, `core.bare` and every branch's sha, keyed by what they name."""
    head = _git(root, "rev-parse", "HEAD")
    ref = _git(root, "symbolic-ref", "-q", "HEAD")
    bare = _git(root, "config", "--get", "core.bare")
    seen = {
        "HEAD": head.stdout.strip() if head.returncode == 0 else "(none)",
        "HEAD-ref": ref.stdout.strip() if ref.returncode == 0 else "(detached)",
        "core.bare": bare.stdout.strip() if bare.returncode == 0 else "(unset)",
    }
    refs = _git(root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    for line in refs.stdout.splitlines():
        name, _, sha = line.partition(" ")
        seen[name] = sha
    return seen


def _peer_refs(root: Path) -> set[str]:
    here = root.resolve()
    peers: set[str] = set()
    tree: Path | None = None
    for line in _git(root, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            tree = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("branch ") and tree != here:
            peers.add(line.removeprefix("branch "))
    return peers


def unexcused(root: Path, before: dict[str, str], after: dict[str, str]) -> list[str]:
    """The deltas nobody else owns: HEAD's lines, or a ref no peer worktree or merge explains."""
    peers = _peer_refs(root)
    found: list[str] = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if name.startswith("refs/heads/"):
            if (
                new is None
                and old
                and _git(root, "merge-base", "--is-ancestor", old, "refs/heads/main").returncode
                == 0
            ):
                continue
            if new is not None and name in peers:
                continue
        found.append(f"{name}: {old or '(absent)'} -> {new or '(absent)'}")
    return found


@pytest.fixture(scope="session", autouse=True)
def tripwire(request: pytest.FixtureRequest) -> Iterator[dict[str, str]]:
    """A moved ref, HEAD or `core.bare` in the real repository is could-not-look."""
    root = request.config.rootpath
    before = fingerprint(root)
    yield before
    delta = unexcused(root, before, fingerprint(root))
    if delta:
        raise CouldNotLook(
            f"this session MUTATED THE REAL REPOSITORY at {root}: " + "; ".join(delta)
        )
