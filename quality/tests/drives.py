"""The drives as a population, and the one judgment of a drive's run: its exit and its summary."""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook

HOMES = ("scripts/tests/test_*.sh", "deploy/tests/test_*.sh")
# `<name>: N passed · M failed · K skipped`; the drive's file stem marks its own line.
SUMMARY = r"^{own}: (\d+) passed(?: ·|,) (\d+) failed(?: · (\d+) (skipped|could not look))?\b"


def population(root: Path) -> list[str]:
    """Every tracked drive under `root`, as `git ls-files` lists the two homes."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", *HOMES], capture_output=True, text=True
    )
    if listed.returncode != 0:
        raise CouldNotLook(f"git ls-files could not list the drives: {listed.stderr.strip()}")
    return listed.stdout.split()


def drive_name(path: str) -> str:
    """The gate's name for a drive: its file's stem without `test_`."""
    return Path(path).stem.removeprefix("test_")


def header_line(path: Path, key: str) -> str | None:
    """The value of the first `# <key>:` line in the drive's first 60 lines, or None."""
    prefix = f"# {key}:"
    with path.open(errors="replace") as lines:
        for _, line in zip(range(60), lines, strict=False):
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
    return None


def params(root: Path) -> Iterator[object]:
    """One param per drive, id its name, marked `drives(...)` from its header."""
    for path in population(root):
        declared = header_line(root / path, "drives")
        # does-not-cover: a hung drive (timeout(0)) — it holds its worker and the leg never returns.
        marks = [pytest.mark.timeout(0)]
        if declared:
            marks.append(pytest.mark.drives(*declared.split()))
        yield pytest.param(path, id=drive_name(path), marks=marks)


def require_declared(node: pytest.Item, drive: str) -> None:
    """`CouldNotLook` for a drive whose param carries no `drives` marker."""
    if node.get_closest_marker("drives") is None:
        raise CouldNotLook(f"{drive} has no `# drives:` line, so no selection and no reuse key")


def require_alone(path: Path) -> None:
    """`CouldNotLook` for a `# serial:` drive in an xdist worker, where others run beside it."""
    if header_line(path, "serial") is not None and os.environ.get("PYTEST_XDIST_WORKER"):
        raise CouldNotLook(
            f"{path.name} declares `# serial:` and this session runs drives beside it"
        )


def verdict(rc: int, output: str, own: str) -> tuple[int, str]:
    """0 green, 1 red, 2 could not look, from the exit and the drive's own last summary line."""
    if rc == 2:
        return 2, "exit 2"
    if rc != 0:
        return 1, f"exit {rc}"
    lines = re.findall(SUMMARY.format(own=re.escape(own)), output, re.MULTILINE)
    if not lines:
        return 2, f"exit 0 with no `{own}:` summary line, so nothing says what was cleared"
    passed, failed, third, word = lines[-1]
    if word == "could not look" and int(third) != 0:
        return 2, f"exit 0 but the summary counts {third} could not look"
    if int(failed) != 0:
        return 1, f"exit 0 but the summary counts {failed} failed"
    if int(passed) == 0:
        return 2, "exit 0 but the summary counts 0 passed and 0 failed: it asserted nothing"
    return 0, "exit 0 and a clean summary"


def run_drive(path: Path, cwd: Path, sink: Path) -> tuple[int, int]:
    """Run one drive with both streams to `sink`; answer its exit and whole seconds."""
    started = time.monotonic()
    with sink.open("wb") as out:
        done = subprocess.run(
            [str(path)], cwd=cwd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
        )
    return done.returncode, int(time.monotonic() - started)
