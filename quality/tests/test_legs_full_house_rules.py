"""The `full-house-rules` leg: the engine's argv, its diff base and its exits, as the shell's."""

# does-not-cover: the engine's own verdict on a real tree — every engine here is a planted `uv`.

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.djb.legs import full_house_rules as fhr
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives("quality/djb/legs/full_house_rules.py")

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
SHELL = GATE_TEXT.split("\ngate_leg_full_house_rules() {\n", 1)[1].split(
    "\ngate_run_body full-house-rules ", 1
)[0]
#: A `uv` that records its argv and the one environment name the leg sets, then exits as told.
FAKE_UV = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_UV_LOG"
printf 'skip=%s\\n' "${GATE_SKIP_DJANGO_LEG:-}" >>"$FAKE_UV_LOG"
exit "${FAKE_UV_RC:-0}"
"""


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def world(scratch: Path, scratch_repo: Callable[..., Path]) -> tuple[Path, dict[str, str]]:
    """A repository with a commit on main and a branch one commit ahead, and a planted `uv`."""
    repo = scratch_repo()
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "on main")
    _git(repo, "checkout", "-q", "-b", "rung")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "on the rung")
    bin_ = scratch / "bin"
    bin_.mkdir()
    (bin_ / "uv").write_text(FAKE_UV)
    (bin_ / "uv").chmod(0o755)
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", str(scratch)),
        "FAKE_UV_LOG": str(scratch / "uv.log"),
    }
    return repo, env


def _shell(repo: Path, env: dict[str, str]) -> int:
    script = f"set -euo pipefail\ngate_leg_full_house_rules() {{\n{SHELL}\n"
    script += "gate_leg_full_house_rules"
    return subprocess.run(["bash", "-c", script], cwd=repo, env=env).returncode


def _python(repo: Path, env: dict[str, str]) -> int:
    return fhr.run(R.Ctx(repo, "full", env))


def _log(env: dict[str, str]) -> list[str]:
    path = Path(env["FAKE_UV_LOG"])
    lines = path.read_text().splitlines() if path.exists() else []
    path.unlink(missing_ok=True)
    return lines


def test_the_registry_claims_the_shell_leg_of_its_name_in_its_own_unit() -> None:
    table = R.load(ROOT)
    assert table.unit("full-house-rules")[1] == ("full-house-rules",)
    assert table.leg("full-house-rules").body is fhr.run
    assert table.mode_legs("full")[-1].name == "full-house-rules"
    assert "full-house-rules" not in {g.name for g in table.mode_legs("loop")}


def test_the_declared_command_and_environment_are_the_shell_bodys() -> None:
    assert "uv run python -m quality.gate" in SHELL
    assert " ".join(fhr.ARGV[0]) == "uv run python -m quality.gate"
    for key, value in fhr.ENV.items():
        assert f"{key}={value} " in SHELL


@pytest.mark.parametrize("where", ["branch", "main", "detached", "no-main"])
@pytest.mark.parametrize("rc", [0, 1, 2, 3])
def test_on_one_planted_world_the_port_runs_what_the_shell_ran_and_exits_as_it_did(
    world: tuple[Path, dict[str, str]], where: str, rc: int
) -> None:
    repo, env = world
    if where == "main":
        _git(repo, "checkout", "-q", "main")
    elif where == "detached":
        _git(repo, "checkout", "-q", "--detach")
    elif where == "no-main":
        _git(repo, "branch", "-q", "-m", "main", "trunk")
    env = {**env, "FAKE_UV_RC": str(rc)}
    shell_rc, shell_log = _shell(repo, env), _log(env)
    port_rc, port_log = _python(repo, env), _log(env)
    assert (port_rc, port_log) == (shell_rc, shell_log)
    base = _git(repo, "rev-parse", "HEAD~1")
    diffed = f"run python -m quality.gate --diff {base}"
    assert shell_log[0] == (diffed if where == "branch" else "run python -m quality.gate")
    assert shell_log[1] == "skip=1"


def test_an_engine_exit_2_says_enforcement_is_broken(
    world: tuple[Path, dict[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, env = world
    assert _python(repo, {**env, "FAKE_UV_RC": "2"}) == 2
    assert "ENFORCEMENT ITSELF IS BROKEN" in capsys.readouterr().err
    assert _python(repo, {**env, "FAKE_UV_RC": "1"}) == 1
    assert "ENFORCEMENT" not in capsys.readouterr().err
