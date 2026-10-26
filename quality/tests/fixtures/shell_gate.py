"""The shell gate as it last stood — `scripts/check.sh` at `SHELL_AT` — for the parity tests."""

# Invariant: a parity test reads the shell from git, never the shim the checkout now carries.

from __future__ import annotations

import atexit
import functools
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from quality.djb.registry import _DRIVE_LINE

ROOT = Path(__file__).resolve().parents[3]
#: The last commit whose `scripts/check.sh` is the shell gate the port is measured against.
SHELL_AT = "478358bf"
#: The last main commit carrying the shell libraries the tail deleted (`library`).
LIBRARY_AT = "5c8fa707"


@functools.cache
def text() -> str:
    """`raw()` less each drive registration whose file is gone (the sweep, GF5.6)."""
    lines = raw().splitlines(keepends=True)
    gone = {
        n
        for n, line in enumerate(lines)
        if (found := _DRIVE_LINE.match(line.rstrip("\n")))
        and not (ROOT / line.strip()).is_file()
        and lines[n - 1].startswith(f"selftest_drive {found.group(1)} ")
    }
    return "".join(line for n, line in enumerate(lines) if n not in gone and n + 1 not in gone)


@functools.cache
def raw() -> str:
    """The shell gate's bytes at `SHELL_AT`; a skip naming the commit where it is absent."""
    done = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{SHELL_AT}:scripts/check.sh"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(
            f"the shell gate's commit {SHELL_AT} is not in this repository",
            allow_module_level=True,
        )
    return done.stdout


@functools.cache
def path() -> Path:
    """`text()` on disk, once per session, for a reader that takes a path."""
    home = Path(tempfile.mkdtemp(prefix="djb-shell-gate-"))
    atexit.register(shutil.rmtree, home, True)
    (home / "check.sh").write_text(text(), encoding="utf-8")
    return home / "check.sh"


@functools.cache
def library(name: str) -> Path:
    """`scripts/<name>` at `LIBRARY_AT` on disk; a skip naming the commit where it is absent."""
    done = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{LIBRARY_AT}:scripts/{name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"scripts/{name} is not at {LIBRARY_AT} in this repository")
    home = Path(tempfile.mkdtemp(prefix="djb-shell-library-"))
    atexit.register(shutil.rmtree, home, True)
    (home / name).write_text(done.stdout, encoding="utf-8")
    return home / name
