"""The shared interpreter's fingerprint, and a guard that a fixture never wrote through to it."""

# Invariant: a world linking this checkout's `.venv` reaches uv's one interpreter for the machine.

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def interpreters() -> list[Path]:
    """The real files behind `sys.executable` and this checkout's `.venv/bin/python*`."""
    found = {Path(sys.executable).resolve()}
    bin_ = ROOT / ".venv/bin"
    if bin_.is_dir():
        found.update(p.resolve() for p in bin_.iterdir() if p.name.startswith("python"))
    return sorted(found)


def fingerprint(paths: Sequence[Path] | None = None) -> dict[str, tuple[int, int, int]]:
    """Each path's inode, mtime and size; a path that is gone is left out."""
    out: dict[str, tuple[int, int, int]] = {}
    for path in interpreters() if paths is None else paths:
        try:
            st = path.stat()
        except OSError:
            continue
        out[str(path)] = (st.st_ino, st.st_mtime_ns, st.st_size)
    return out


@contextmanager
def untouched(paths: Sequence[Path] | None = None) -> Iterator[None]:
    """`AssertionError` when the body changed an interpreter: a write that followed a link out."""
    before = fingerprint(paths)
    yield
    after = fingerprint(paths)
    assert after == before, f"the shared interpreter changed under a fixture: {before} -> {after}"
