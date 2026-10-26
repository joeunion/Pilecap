"""The `secrets` leg: the changed set, its basis sentence and the hook's verdict, as the shell's."""

# does-not-cover: detect-secrets' own judgement — every hook here is a planted `uv`.

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.djb.legs import secrets
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives("quality/djb/legs/secrets.py", "scripts/secrets_scan.sh")

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
BODY = GATE_TEXT.split("    gate_leg_secrets() {\n", 1)[1].split("\n    gate_run_body secrets ", 1)[
    0
]
#: A `uv` that records the paths it was handed, then exits as told.
FAKE_UV = """#!/bin/sh
shift 4
printf '%s\\n' "$@" >>"$FAKE_UV_LOG"
exit "${FAKE_UV_RC:-0}"
"""


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def world(scratch: Path, scratch_repo: Callable[..., Path]) -> tuple[Path, dict[str, str]]:
    """A repository on a branch two commits past main, one file dirty, and a planted `uv`."""
    repo = scratch_repo()
    for name in ("kept.txt", "gone.txt"):
        (repo / name).write_text(f"{name}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "main")
    _git(repo, "checkout", "-q", "-b", "rung")
    (repo / "new.txt").write_text("new\n")
    (repo / "gone.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the rung")
    (repo / "kept.txt").write_text("dirty\n")
    bin_ = scratch / "bin"
    bin_.mkdir()
    (bin_ / "uv").write_text(FAKE_UV)
    (bin_ / "uv").chmod(0o755)
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", str(scratch)),
        "FAKE_UV_LOG": str(scratch / "uv.log"),
        "TMPDIR": str(scratch),
    }
    return repo, env


def _shell(repo: Path, env: dict[str, str]) -> tuple[int, str]:
    script = "\n".join(
        (
            f". {ROOT}/scripts/gate_refuse.sh",
            f". {ROOT}/scripts/secrets_scan.sh",
            "set -e",
            "gate_leg_secrets() {",
            BODY,
            "gate_leg_secrets",
        )
    )
    done = subprocess.run(["bash", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    return done.returncode, done.stdout


def _python(repo: Path, env: dict[str, str], capfd: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capfd.readouterr()
    rc = secrets.run(R.Ctx(repo, "loop", env))
    return rc, capfd.readouterr().out


def _log(env: dict[str, str]) -> list[str]:
    path = Path(env["FAKE_UV_LOG"])
    lines = path.read_text().splitlines() if path.exists() else []
    path.unlink(missing_ok=True)
    return lines


def test_the_registry_claims_the_loop_only_leg_first_of_the_three() -> None:
    table = R.load(ROOT)
    leg = table.leg("secrets")
    assert (leg.unit, set(leg.modes), leg.body) == (R.LOOP_ONLY, {"loop"}, secrets.run)
    assert [g.name for g in table.mode_legs("loop")][-3] == "secrets"
    assert " ".join(secrets.ARGV[0]) == "uv run detect-secrets-hook --baseline .secrets.baseline"


@pytest.mark.parametrize("where", ["branch", "main", "fresh-branch", "no-main", "carried"])
def test_on_one_planted_world_the_port_scans_and_says_what_the_shell_did(
    world: tuple[Path, dict[str, str]], capfd: pytest.CaptureFixture[str], where: str
) -> None:
    repo, env = world
    if where == "main":
        _git(repo, "checkout", "-q", "main")
    elif where == "fresh-branch":
        _git(repo, "checkout", "-q", "-b", "fresh", "main")
    elif where == "no-main":
        _git(repo, "branch", "-q", "-m", "main", "trunk")
    elif where == "carried":
        _git(repo, "checkout", "-q", "-b", "mirror")
        _git(repo, "branch", "-q", "-f", "main", "HEAD")
        env = {**env, "DJB_LOOP_SCOPE_BASE": _git(repo, "rev-parse", "HEAD~1")}
    shell_rc, shell_out = _shell(repo, env)
    shell_log = _log(env)
    port_rc, port_out = _python(repo, env, capfd)
    assert (port_rc, port_out.splitlines(), _log(env)) == (
        shell_rc,
        shell_out.splitlines(),
        shell_log,
    )
    if where in ("branch", "carried"):
        assert shell_log == ["kept.txt", "new.txt"]


def test_a_finding_is_the_hooks_own_exit_where_the_shell_said_its_xargs(
    world: tuple[Path, dict[str, str]], capfd: pytest.CaptureFixture[str]
) -> None:
    repo, env = world
    env = {**env, "FAKE_UV_RC": "1"}
    shell_rc, _ = _shell(repo, env)
    port_rc, _ = _python(repo, env, capfd)
    # GNU xargs answers 123 for a callee's 1, BSD xargs 1; the port answers the hook's own 1.
    assert shell_rc in (1, 123)
    assert port_rc == 1


def test_an_underived_set_is_2_and_never_an_empty_scan(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    lone = scratch / "not-a-repo"
    lone.mkdir()
    env = {"PATH": "/usr/bin:/bin", "GIT_CEILING_DIRECTORIES": str(scratch)}
    assert secrets.run(R.Ctx(lone, "loop", env)) == 2
    said = capfd.readouterr().err
    assert "COULD NOT DERIVE the active rung's changed files" in said
    assert "could not read a git directory" in said


def test_nothing_changed_scans_nothing_and_says_so(
    world: tuple[Path, dict[str, str]], capfd: pytest.CaptureFixture[str]
) -> None:
    repo, env = world
    _git(repo, "checkout", "-q", "kept.txt")
    _git(repo, "checkout", "-q", "main")
    rc, out = _python(repo, env, capfd)
    assert rc == 0 and _log(env) == []
    assert "NOTHING WAS SCANNED" in out
