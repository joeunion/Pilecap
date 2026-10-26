"""`scripts/setup.sh`'s arguments: `--help` prints usage, anything else is refused, before any step.

does-not-cover: a whole setup run; the no-argument case proves only that the first step starts.
does-not-cover: a tool called by absolute path; only `docker`, `uv`, `pnpm` and `git` are stubbed.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives("scripts/setup.sh")

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "scripts" / "setup.sh"
STUBBED = ("docker", "uv", "pnpm", "git")
FIRST_STEP = "== local main"


def step_names() -> list[str]:
    """Every `step "<name>"` setup.sh runs, read from the script."""
    names = re.findall(r'^step "([^"]+)"', SETUP.read_text(), re.M)
    if not names:
        raise CouldNotLook('scripts/setup.sh declares no `step "…"` line')
    return names


@pytest.fixture
def copy(scratch: Path) -> Path:
    """A copy of this tree's `scripts/` and `.env.example` in scratch, with recording tool stubs."""
    checkout = scratch / "checkout"
    shutil.copytree(ROOT / "scripts", checkout / "scripts")
    shutil.copy2(ROOT / ".env.example", checkout / ".env.example")
    stubs = scratch / "bin"
    stubs.mkdir()
    for tool in STUBBED:
        stub = stubs / tool
        stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{scratch}/calls"\nexit 1\n')
        stub.chmod(0o755)
    return checkout


@pytest.fixture
def setup(
    copy: Path, scratch: Path, capture: Callable[..., Captured]
) -> Callable[..., tuple[Captured, list[str]]]:
    """`setup(*args)` runs the copy's setup.sh with the stubs first on PATH: (run, tool calls)."""

    def run(*args: str) -> tuple[Captured, list[str]]:
        calls = scratch / "calls"
        calls.unlink(missing_ok=True)
        path = f"{scratch / 'bin'}:/usr/bin:/bin"
        out = capture(
            ["bash", str(copy / "scripts" / "setup.sh"), *args], cwd=copy, env={"PATH": path}
        )
        made = calls.read_text().splitlines() if calls.is_file() else []
        return out, made

    return run


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_does_nothing(
    flag: str, copy: Path, setup: Callable[..., tuple[Captured, list[str]]]
) -> None:
    out, calls = setup(flag)
    text = out.text()
    assert out.rc == 0, text
    assert text.startswith("usage: setup.sh"), text
    assert [name for name in step_names() if name not in text] == [], text
    assert "re-run" in text and "--help" in text, text
    assert FIRST_STEP not in text, text
    assert calls == [], calls
    assert not (copy / ".venv").exists() and not (copy / ".env").exists()


@pytest.mark.parametrize("args", [("--nope",), ("--help", "--nope")])
def test_an_unknown_argument_is_refused_and_nothing_runs(
    args: tuple[str, ...], copy: Path, setup: Callable[..., tuple[Captured, list[str]]]
) -> None:
    out, calls = setup(*args)
    text = out.text()
    assert out.rc == 2, text
    refusal = [line for line in text.splitlines() if line.startswith("!!")]
    assert len(refusal) == 1 and "'--nope'" in refusal[0] and "--help" in refusal[0], text
    assert FIRST_STEP not in text and "usage:" not in text, text
    assert calls == [], calls
    assert not (copy / ".venv").exists() and not (copy / ".env").exists()


def test_no_argument_still_starts_the_real_run(
    setup: Callable[..., tuple[Captured, list[str]]],
) -> None:
    out, calls = setup()
    text = out.text()
    assert FIRST_STEP in text, text
    assert any(call.startswith("git ") for call in calls), calls
