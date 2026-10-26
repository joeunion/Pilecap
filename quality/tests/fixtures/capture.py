"""The `capture` fixture: a command run to a file, never a pipe, read back only when non-empty."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


@dataclass(frozen=True)
class Captured:
    """One run: its exit and the file its stdout and stderr went to."""

    rc: int
    path: Path

    def text(self) -> str:
        """The capture; `CouldNotLook` when absent or empty, since then nothing was captured."""
        if not self.path.is_file() or self.path.stat().st_size == 0:
            raise CouldNotLook(
                f"capture: {self.path} is empty or absent (exit {self.rc}) — nothing was captured"
            )
        return self.path.read_text(errors="replace")


def run_to(
    path: Path, argv: Sequence[str], cwd: Path, env: Mapping[str, str] | None = None
) -> Captured:
    """Run `argv` in `cwd` with both streams to `path`; `CouldNotLook` when it cannot be started."""
    try:
        with path.open("wb") as sink:
            done = subprocess.run(
                list(argv),
                cwd=cwd,
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
            )
    except OSError as error:
        raise CouldNotLook(f"capture: {argv[0]!r} could not be started: {error}") from error
    return Captured(done.returncode, path)


@pytest.fixture
def capture(scratch: Path, request: pytest.FixtureRequest) -> Callable[..., Captured]:
    """`capture(argv, cwd=…, env=…)` runs once into the next numbered file under `scratch`."""
    count = 0

    def run(
        argv: Sequence[str], cwd: Path | None = None, env: Mapping[str, str] | None = None
    ) -> Captured:
        nonlocal count
        count += 1
        merged = None if env is None else {**os.environ, **env}
        return run_to(
            scratch / f"capture-{count}.out", argv, cwd or request.config.rootpath, merged
        )

    return run
