"""The `gate` fixture: `scripts/check.sh` run in a scratch checkout, never in the one under test."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


def require_gate_checkout(where: Path, root: Path) -> Path:
    """`where/scripts/check.sh`; `CouldNotLook` for the real checkout or one with no gate."""
    if where.resolve() == root.resolve():
        raise CouldNotLook(
            f"gate: {where} is the checkout under test — a nested gate meets its own lock"
        )
    script = where / "scripts" / "check.sh"
    if not script.is_file():
        raise CouldNotLook(f"gate: {where} carries no scripts/check.sh")
    return script


@pytest.fixture
def gate(capture: Callable[..., object], request: pytest.FixtureRequest) -> Callable[..., object]:
    """`gate(*args, cwd=<checkout>, env=…)` answers the gate's `Captured` run."""

    def run(*args: str, cwd: Path, env: Mapping[str, str] | None = None) -> object:
        script = require_gate_checkout(cwd, request.config.rootpath)
        # Invariant: the shim runs the checkout's interpreter; a venv-less one borrows this one's.
        venv = cwd / ".venv"
        if not venv.exists():
            venv.symlink_to(request.config.rootpath / ".venv")
        # Invariant: an outer box loop's carried base names a ref the scratch checkout lacks.
        return capture(
            [str(script), *args], cwd=cwd, env={"DJB_LOOP_SCOPE_BASE": "", **(env or {})}
        )

    return run
