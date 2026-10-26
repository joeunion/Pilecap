"""The `env_strip` fixture: what `env.STEERS` names, and the unit and CI inputs, unset per test."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import env as djb_env

GIT_LOCATION = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_QUARANTINE_PATH",
)
GATE_INPUTS = djb_env.STEERS
CI_EXEMPTIONS = ("CI", "GITHUB_ACTIONS")
#: The unit a gate run hands its legs: a test's world names its own unit and shard, or none.
UNIT_INPUTS = (
    "GATE_LEG_UNIT",
    "GATE_SHARD_K",
    "GATE_SHARD_N",
    "GATE_PASSES",
    "GATE_BANK",
    "GATE_PR",
    "GATE_PR_PYTEST_ARGS",
    "GATE_PR_COUNTS_DIR",
    "GATE_STORE_DURATIONS",
    "MEASURED_START",
)
STRIPPED = GIT_LOCATION + GATE_INPUTS + CI_EXEMPTIONS + UNIT_INPUTS
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def read_env_keys(path: Path) -> tuple[str, ...]:
    """The product's declared env keys; `CouldNotLook` on a malformed or a stripped name."""
    if not path.is_file():
        return ()
    keys: list[str] = []
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _NAME.fullmatch(line):
            raise CouldNotLook(f"{path}:{number}: {line!r} is not a variable NAME")
        if line in STRIPPED or line.startswith(("DJB_GATE_", "DJB_LOOP_", "DJB_LOCAL_")):
            raise CouldNotLook(
                f"{path}:{number}: {line!r} is a name this template strips from every drive"
            )
        keys.append(line)
    return tuple(keys)


@pytest.fixture(autouse=True)
def env_strip(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    """Unset the git location, gate input, CI and unit variables; answer the product keys kept."""
    kept = read_env_keys(request.config.rootpath / "scripts" / "local" / "env_keys")
    for name in STRIPPED:
        monkeypatch.delenv(name, raising=False)
    return kept
