"""The tree git holds, read ONCE — the measured tree every reader of "the tree" views.

`git read-tree HEAD` into a throwaway index, `_stage_all`, `write-tree`,
`ls-tree -r`: `scripts/gate_ledger.sh::gate_measured_tree`'s own read, in
process. "Tracked", "untracked" and "every path the gate can read" are views of
this one read, so they cannot come to disagree. Standard library only: the
partition (`quality/partition.py`) and a typed test import it without the
engine's world.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

Stage = subprocess.CompletedProcess[str]


class TreeRead(NamedTuple):
    """The MEASURED tree: path -> blob over HEAD and the working tree; HEAD's paths; why not."""

    blobs: dict[str, str]
    head: frozenset[str]
    why: str


def read_tree(root: Path) -> TreeRead:
    """The ONE read of "the tree": read-tree, `_stage_all`'s staging, write-tree, ls-tree.

    Invariant: an untracked path that vanishes mid-read is absent, never a refusal (`_stage_all`).
    """
    fd, index = tempfile.mkstemp(prefix="djb-measured-index.")
    os.close(fd)
    os.unlink(index)  # git wants to create it, not inherit an empty one
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = index

    def git(*argv: str, stdin: str | None = None) -> Stage:
        return subprocess.run(
            ["git", "-C", str(root), *argv],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    try:
        step = git("read-tree", "HEAD")
        if step.returncode != 0:
            return TreeRead({}, frozenset(), _git_failed("read-tree HEAD", step))
        listed = git("ls-files", "-z")
        if listed.returncode != 0:
            return TreeRead({}, frozenset(), _git_failed("ls-files", listed))
        head = frozenset(p for p in listed.stdout.split("\0") if p)
        what, step = _stage_all(git)
        if step.returncode != 0:
            return TreeRead({}, head, _git_failed(what, step))
        step = git("write-tree")
        if step.returncode != 0:
            return TreeRead({}, head, _git_failed("write-tree", step))
        tree = step.stdout.strip()
        if not tree:
            return TreeRead({}, head, "`git write-tree` printed no tree")
        listing = git("ls-tree", "-r", "-z", tree)
        if listing.returncode != 0:
            return TreeRead({}, head, _git_failed(f"ls-tree -r {tree}", listing))
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index)
    blobs: dict[str, str] = {}
    for record in listing.stdout.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        fields = meta.split()
        if len(fields) < 3 or not path:
            continue
        blobs[path] = fields[2]
    if not blobs:
        return TreeRead({}, head, "the measured tree named no path at all")
    return TreeRead(blobs, head, "")


def _stage_all(git: Callable[..., Stage]) -> tuple[str, Stage]:
    """`git add -A`'s index, staged so an untracked path unlinked after its listing is skipped.

    Why not `add -A`: it lists, then dies on the lstat of a path a sibling unlinked between.
    Invariant: the tree `add -A` writes; an untracked repo listed `sub/` is staged `sub`, a gitlink.
    """
    step = git("add", "-u")
    if step.returncode != 0:
        return "add -u", step
    listed = git("ls-files", "-o", "--exclude-standard", "-z")
    if listed.returncode != 0:
        return "ls-files -o --exclude-standard", listed
    others = "".join(f"{p.rstrip('/')}\0" for p in listed.stdout.split("\0") if p)
    return "update-index --add --remove", git(
        "update-index", "--add", "--remove", "-z", "--stdin", stdin=others
    )


def _git_failed(what: str, proc: object) -> str:
    code = getattr(proc, "returncode", "?")
    err = str(getattr(proc, "stderr", "") or "").strip() or "no stderr"
    return f"`git {what}` exited {code} — {err}"


_TREE_CACHE: dict[str, TreeRead] = {}


def measured_tree(root: Path, *, fresh: bool = False) -> TreeRead:
    """`read_tree`, once per process per root — or `fresh` for a reader whose world moves.

    A gate run does not re-derive its world half way through (the memo keys on
    one read); the self-test's diff layer plants and restores between passes,
    so it asks `fresh`.
    """
    key = str(root)
    if fresh or key not in _TREE_CACHE:
        _TREE_CACHE[key] = read_tree(root)
    return _TREE_CACHE[key]


def untracked_paths(root: Path, *, fresh: bool = False) -> list[str]:
    """The measured tree's paths HEAD does not carry — a view, never a second listing."""
    read = measured_tree(root, fresh=fresh)
    return sorted(set(read.blobs) - read.head)
