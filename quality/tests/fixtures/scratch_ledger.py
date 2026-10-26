"""The `scratch_ledger` fixture: `DJB_GATE_LEDGER` in scratch, never the real ledger."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


def real_ledger(root: Path) -> Path | None:
    """The checkout's own verdict ledger, or None outside a checkout."""
    common = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"], capture_output=True, text=True
    )
    if common.returncode != 0:
        return None
    return (root / common.stdout.strip()).resolve() / "djb-gate-verdicts"


def require_scratch_ledger(path: Path, root: Path) -> Path:
    """`path` as a ledger a test may write; `CouldNotLook` when it is the real one."""
    real = real_ledger(root)
    if real is not None and path.resolve() == real:
        raise CouldNotLook(
            f"scratch_ledger: {path} is the real ledger — a test never writes a verdict there"
        )
    return path


@pytest.fixture
def scratch_ledger(
    scratch: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A ledger file in scratch, exported as `DJB_GATE_LEDGER` for this test only."""
    path = require_scratch_ledger(scratch / "djb-gate-verdicts", request.config.rootpath)
    monkeypatch.setenv("DJB_GATE_LEDGER", str(path))
    return path
