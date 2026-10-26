"""Each fixture's refusal, and each fixture doing its one job."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import env as djb_env
from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.checkout import add_checkout
from quality.tests.fixtures.env_strip import read_env_keys
from quality.tests.fixtures.gate import require_gate_checkout
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.fixtures.scratch_ledger import real_ledger, require_scratch_ledger
from quality.tests.fixtures.scratch_repo import make_repo
from quality.tests.fixtures.tripwire import fingerprint, unexcused

pytestmark = pytest.mark.drives("quality/tests/fixtures/")

ROOT = Path(__file__).resolve().parents[2]
Nested = Callable[..., tuple[int, str]]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.parametrize("value", ["", "relative/path", "/", str(Path.home()), str(ROOT / "apps")])
def test_scratch_refuses(value: str) -> None:
    with pytest.raises(CouldNotLook):
        require_scratch(value, ROOT)


def test_scratch_refuses_a_file(scratch: Path) -> None:
    (scratch / "f").write_text("x")
    with pytest.raises(CouldNotLook, match="not a directory"):
        require_scratch(scratch / "f", ROOT)


def test_scratch_is_a_directory_outside_the_checkout(scratch: Path) -> None:
    assert scratch.is_dir()
    assert ROOT.resolve() not in scratch.resolve().parents


def test_scratch_repo_refuses_an_existing_path(scratch: Path) -> None:
    (scratch / "taken").mkdir()
    with pytest.raises(CouldNotLook, match="already exists"):
        make_repo(scratch / "taken")


def test_scratch_repo_is_on_main_with_one_commit(scratch_repo: Callable[..., Path]) -> None:
    repo = scratch_repo(author="someone")
    assert _git(repo, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"
    assert _git(repo, "config", "user.name") == "someone"


def test_checkout_refuses_a_directory_with_no_repository(scratch: Path) -> None:
    (scratch / "plain").mkdir()
    with pytest.raises(CouldNotLook, match="no HEAD"):
        add_checkout(scratch / "plain", scratch / "dest")


def test_checkout_is_head_detached(checkout: Path) -> None:
    assert _git(checkout, "rev-parse", "HEAD") == _git(ROOT, "rev-parse", "HEAD")
    assert subprocess.run(["git", "-C", str(checkout), "symbolic-ref", "-q", "HEAD"]).returncode


def test_scratch_ledger_refuses_the_real_ledger() -> None:
    real = real_ledger(ROOT)
    assert real is not None
    with pytest.raises(CouldNotLook, match="real ledger"):
        require_scratch_ledger(real, ROOT)


def test_scratch_ledger_is_exported_into_scratch(scratch_ledger: Path, scratch: Path) -> None:
    assert os.environ["DJB_GATE_LEDGER"] == str(scratch_ledger)
    assert scratch_ledger.parent == scratch


@pytest.mark.parametrize("line", ["DJB_GATE_SANCTION", "CI", "DJB_LOOP_ANYTHING", "NOT A NAME"])
def test_env_strip_refuses_a_drawer_line(scratch: Path, line: str) -> None:
    (scratch / "env_keys").write_text(f"# product keys\nPRODUCT_KEY\n{line}\n")
    with pytest.raises(CouldNotLook):
        read_env_keys(scratch / "env_keys")


def test_env_strip_unsets_what_the_preamble_unsets(nested_pytest: Nested) -> None:
    test = (
        "import os\n\n\ndef test_stripped():\n"
        "    assert not {'GIT_DIR', 'CI', 'DJB_LOOP_HERE', 'DJB_SELFTEST_PLAN'} & set(os.environ)\n"
        "    assert os.environ['KEPT_KEY'] == 'kept'\n"
    )
    env = {"GIT_DIR": "/nowhere", "CI": "1", "DJB_LOOP_HERE": "x", "KEPT_KEY": "kept"}
    env["DJB_SELFTEST_PLAN"] = "/a/narrowed/plan.txt"
    rc, out = nested_pytest({"test_e.py": test}, env=env)
    assert rc == 0, out


def test_the_engines_environment_in_a_test_carries_no_steering_name(nested_pytest: Nested) -> None:
    """`R.Ctx(ROOT, mode, dict(os.environ))` in a test is pristine: the autouse strip ran first."""
    test = (
        "import os\n\nfrom quality.djb import env as djb_env\n\n\ndef test_pristine():\n"
        "    handed = dict(os.environ)\n"
        "    assert not (set(djb_env.STEERS) | {'DJB_LAYER_HOOK_JUDGED'}) & set(handed)\n"
    )
    from quality.djb import env as djb_env

    env = {name: "1" for name in (*djb_env.STEERS, "DJB_LAYER_HOOK_JUDGED")}
    rc, out = nested_pytest({"test_p.py": test}, env=env)
    assert rc == 0, out


def test_the_preambles_hand_list_is_env_steers() -> None:
    """The preamble's DRIVE_GATE_VARS is `env.STEERS` in shell, name for name; STEERS the source."""
    text = (ROOT / "scripts/tests/drive_preamble.sh").read_text()
    (line,) = re.findall(r'^DRIVE_GATE_VARS="([^"]*)"$', text, re.MULTILINE)
    shell = line.split()
    assert len(shell) == len(set(shell)), shell
    assert set(shell) == set(djb_env.STEERS), (
        sorted(set(shell) - set(djb_env.STEERS)),
        sorted(set(djb_env.STEERS) - set(shell)),
    )


def test_tripwire_names_a_moved_head_and_an_unowned_ref(scratch_repo: Callable[..., Path]) -> None:
    repo = scratch_repo()
    before = fingerprint(repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "moved")
    _git(repo, "branch", "stray")
    found = unexcused(repo, before, fingerprint(repo))
    assert any(d.startswith("HEAD:") for d in found)
    assert any(d.startswith("refs/heads/stray:") for d in found)


def test_tripwire_excuses_a_reaped_merged_branch(scratch_repo: Callable[..., Path]) -> None:
    repo = scratch_repo()
    _git(repo, "branch", "merged")
    before = fingerprint(repo)
    _git(repo, "branch", "-d", "merged")
    assert unexcused(repo, before, fingerprint(repo)) == []


def test_tripwire_fails_the_session_that_moved_its_root(
    nested_pytest: Nested, scratch_repo: Callable[..., Path]
) -> None:
    repo = scratch_repo()
    test = (
        "import subprocess\n\n\ndef test_moves(request):\n"
        "    root = str(request.config.rootpath)\n"
        "    subprocess.run(['git', '-C', root, 'branch', 'stray'], check=True)\n"
    )
    rc, out = nested_pytest({"test_t.py": test}, root=repo)
    assert rc == 2, out
    assert "MUTATED THE REAL REPOSITORY" in out


def test_capture_refuses_an_empty_capture(scratch: Path) -> None:
    captured = run_to(scratch / "c.out", ["true"], scratch)
    assert captured.rc == 0
    with pytest.raises(CouldNotLook, match="empty or absent"):
        captured.text()


def test_capture_refuses_a_command_that_cannot_start(scratch: Path) -> None:
    with pytest.raises(CouldNotLook, match="could not be started"):
        run_to(scratch / "c.out", [str(scratch / "absent")], scratch)


def test_capture_runs_to_a_file(capture: Callable[..., Captured], scratch: Path) -> None:
    captured = capture(["sh", "-c", "echo out; echo err >&2; exit 3"], cwd=scratch)
    assert captured.rc == 3
    assert captured.text().split() == ["out", "err"]


def test_gate_refuses_the_checkout_under_test() -> None:
    with pytest.raises(CouldNotLook, match="checkout under test"):
        require_gate_checkout(ROOT, ROOT)


def test_gate_refuses_a_directory_with_no_gate(scratch: Path) -> None:
    with pytest.raises(CouldNotLook, match="no scripts/check.sh"):
        require_gate_checkout(scratch, ROOT)


def test_gate_runs_the_checkouts_own_script(gate: Callable[..., Captured], scratch: Path) -> None:
    (scratch / "scripts").mkdir()
    (scratch / "scripts/check.sh").write_text('#!/bin/sh\necho gate "$@"\nexit 1\n')
    (scratch / "scripts/check.sh").chmod(0o755)
    captured = gate("--fast", cwd=scratch)
    assert (captured.rc, captured.text().strip()) == (1, "gate --fast")


def test_an_engine_under_xdist_scans_on_its_workers_share_of_the_cores() -> None:
    from quality.tests.fixtures.engine_share import share

    assert (share(4, 4), share(10, 4), share(1, 8), share(8, 0)) == (1, 2, 1, 8)
    workers = os.environ.get("PYTEST_XDIST_WORKER_COUNT")
    if workers is None:
        return  # a serial session: the engine keeps its own default
    want = str(share(os.cpu_count() or 1, int(workers)))
    assert os.environ.get("DJB_RULES_WORKERS") == want, "the engine would scan on every core"
