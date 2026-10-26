"""`quality.djb.cli hook pre-push`, the wall, against the shell hook it ports byte for byte."""

# names, never reads: README.md — a scratch checkout's file
# does-not-cover: a push to a real forge; the remote is a scratch bare repository.
# does-not-cover: `check.sh` itself — the wall execs a stub, and the stub's record is the proof.

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import ledger

pytestmark = pytest.mark.drives(
    "quality/djb/cli.py", "quality/djb/ledger.py", "scripts/githooks/pre-push"
)

ROOT = Path(__file__).resolve().parents[2]
#: `scripts/githooks/pre-push` at the cutover, byte for byte: the belt over this door.
BELT_TEXT = """#!/usr/bin/env bash
# Pre-push: the wall — `quality.djb.cli hook pre-push` consults the ledger for every pushed ref.
# Why the system interpreter with no site: a clone with no venv must still be refused honestly.
# Why -E: an inherited PYTHONSAFEPATH or PYTHONPATH would move what `-m` imports.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# An exported GIT_DIR (a push from a linked worktree) outranks `-C` in every child.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR \\
    GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE GIT_PREFIX
exec /usr/bin/python3 -E -S -m quality.djb.cli hook pre-push "$@"
"""
#: The last commit whose `pre-push` is the shell hook the port is measured against.
SHELL_HOOK_AT = "fbf05826aeca357e8426d05b15c7b63ca47ba7a0"  # pragma: allowlist secret
SANCTION = ledger.Sanction("typed", "gate-rung", "quality/** rung — the canary self-test")
STUB = (
    "#!/usr/bin/env bash\nFULL_LEGS=drive-legs\n"
    'echo "STUB GATE RAN caller=${DJB_GATE_CALLER:-}" >>"$0.ran"\n'
)
ZERO = "0" * 40
#: The remote sha of a ref the remote already holds; `ZERO` there means the remote lacks it.
HELD = "1" * 40
#: A ref the R10.2 refusal does not cover, where the shell wall and the port still agree.
OFF_MAIN = "refs/heads/scratch"


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def belt(scratch: Path) -> Path:
    """The belt written to scratch, executable, as the cutover will ship it."""
    path = scratch / "pre-push.belt"
    path.write_text(BELT_TEXT)
    path.chmod(0o755)
    return path


def _shell_hook(scratch: Path) -> Path:
    done = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{SHELL_HOOK_AT}:scripts/githooks/pre-push"],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"the shell hook's commit {SHELL_HOOK_AT[:12]} is not in this repository")
    path = scratch / "pre-push.shell"
    path.write_bytes(done.stdout)
    return path


def _world(scratch_repo: Callable[..., Path], scratch: Path, name: str = "work") -> Path:
    """A checkout: the ledger library, the package (excluded), a stub gate, a bare `origin`."""
    work = scratch_repo(name)
    (work / "scripts").mkdir()
    for lib in ("gate_ledger.sh", "gate_refuse.sh"):
        shutil.copy2(ROOT / "scripts" / lib, work / "scripts" / lib)
    gate = work / "scripts" / "check.sh"
    gate.write_text(STUB)
    gate.chmod(0o755)
    (work / "README.md").write_text("the measured content\n")
    for package in ("quality", "apps"):
        (work / package).symlink_to(ROOT / package)
    (work / ".git/info/exclude").write_text("/quality\n/apps\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "main, the tree the gate measured")
    remote = scratch / f"{name}-origin.git"
    _git(scratch, "init", "-q", "--bare", str(remote))
    _git(work, "remote", "add", "origin", str(remote))
    return work


def _bank(work: Path, rev: str = "HEAD") -> str:
    tree = _git(work, "rev-parse", f"{rev}^{{tree}}")
    ledger.record_full(work, tree=tree, legs="drive-legs", caller="pm-bank", sanction=SANCTION)
    return tree


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "DJB_PUSH"))}
    env.update(extra)
    return env


def _hook(
    hook: Path, work: Path, refs: str, *, url: str = "", **extra: str
) -> tuple[int, str, str]:
    done = subprocess.run(
        ["bash", str(hook), "origin", url or str(work.parent / "work-origin.git")],
        cwd=work,
        input=refs,
        capture_output=True,
        text=True,
        env=_env(**extra),
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


def _ran(work: Path) -> str:
    ran = work / "scripts" / "check.sh.ran"
    return ran.read_text() if ran.exists() else ""


def _ref(work: Path, rev: str, to: str = "refs/heads/main", remote: str = HELD) -> str:
    return f"refs/heads/x {_git(work, 'rev-parse', rev)} {to} {remote}\n"


def test_the_belt_is_twelve_code_lines_under_the_system_interpreter() -> None:
    code = [
        line
        for line in BELT_TEXT.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(code) <= 12, code
    assert code[-1] == 'exec /usr/bin/python3 -E -S -m quality.djb.cli hook pre-push "$@"'
    assert "gate_ledger.sh" not in BELT_TEXT


def test_the_committed_hook_is_the_belt_byte_for_byte() -> None:
    assert (ROOT / "scripts/githooks/pre-push").read_text() == BELT_TEXT


def test_a_banked_tree_is_honoured_and_no_gate_is_spawned(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    work = _world(scratch_repo, scratch)
    tree = _bank(work)
    hooks = scratch / "hooks"
    hooks.mkdir()
    shutil.copy2(belt, hooks / "pre-push")
    (hooks / "pre-push").chmod(0o755)
    _git(work, "config", "core.hooksPath", str(hooks))
    done = subprocess.run(
        ["git", "-C", str(work), "push", "origin", "main"],
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    )
    said = done.stdout + done.stderr
    assert done.returncode == 0, said
    assert f"pre-push: wall honoured {tree}\n" in said
    assert f"pre-push: every pushed tree ({tree}) is measured green" in said
    assert _ran(work) == "", "the hook spawned the gate for a tree the ledger holds green"


@pytest.mark.parametrize(
    "case",
    ["honoured", "foreign", "measuring", "no-refs", "box-ignored", "box-exempt", "intent-off-pm"],
)
def test_the_python_wall_says_what_the_shell_wall_says(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, case: str, belt: Path
) -> None:
    """Off main the walls agree; divergences: a push to main (R10.2), a dirty refusal's rows."""
    shell = _shell_hook(scratch)
    work = _world(scratch_repo, scratch)
    _bank(work)
    refs, url, extra = _ref(work, "HEAD", OFF_MAIN), "", {}
    if case == "foreign":
        _git(work, "checkout", "-q", "-b", "red")
        (work / "RED.md").write_text("bytes no gate measured\n")
        _git(work, "add", "RED.md")
        _git(work, "commit", "-q", "-m", "red")
        refs = _ref(work, "red", OFF_MAIN)
        _git(work, "checkout", "-q", "main")
    elif case in ("measuring", "box-exempt", "box-ignored", "intent-off-pm"):
        (work / "README.md").write_text("an unmeasured change\n")
        _git(work, "commit", "-q", "-am", "unmeasured")
        refs = _ref(work, "HEAD", OFF_MAIN)
        if case.startswith("box"):
            extra["DJB_PUSH_DESTINATION"] = "verifier-box"
            url = str(scratch / ".vouch-123" / "probe.git") if case == "box-exempt" else ""
        if case == "intent-off-pm":
            extra["DJB_PUSH_INTENT"] = "ci"
    elif case == "no-refs":
        refs = ""
    was = _hook(shell, work, refs, url=url, **extra)
    shell_ran = _ran(work)
    (work / "scripts" / "check.sh.ran").unlink(missing_ok=True)
    now = _hook(belt, work, refs, url=url, **extra)
    assert now == was
    assert _ran(work) == shell_ran
    assert "pre-push: wall " in now[1]


def test_an_intent_row_vouches_for_pm_refs_only(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    work = _world(scratch_repo, scratch)
    (work / "README.md").write_text("a train's tree\n")
    _git(work, "commit", "-q", "-am", "the train")
    tree = _git(work, "rev-parse", "HEAD^{tree}")
    ledger.intent_record(
        work,
        tree=tree,
        commit=_git(work, "rev-parse", "HEAD"),
        branch="pm/train",
        sanction="TRAIN-X: the PR's CI run is the one measurement",
    )
    rc, out, _ = _hook(belt, work, _ref(work, "HEAD", "refs/heads/pm/train"), DJB_PUSH_INTENT="ci")
    assert rc == 0 and f"pre-push: wall ci-intent {tree}\n" in out
    assert _ran(work) == ""
    rc, out, _ = _hook(belt, work, _ref(work, "HEAD", OFF_MAIN), DJB_PUSH_INTENT="ci")
    assert "an intent vouches for refs/heads/pm/* only" in out
    assert f"pre-push: wall measuring {tree}\n" in out
    assert "caller=push-wall" in _ran(work)
    (work / "scripts" / "check.sh.ran").unlink()
    rc, out, err = _hook(belt, work, _ref(work, "HEAD"), DJB_PUSH_INTENT="ci")
    assert rc == 2 and f"pre-push: wall main-refused {tree}\n" in out, out + err
    assert _ran(work) == ""


def test_a_push_to_main_is_refused_naming_the_road_and_never_measured(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    """R10.2: an unmeasured tree for main is exit 2 and no gate; a banked one is honoured."""
    work = _world(scratch_repo, scratch)
    banked = _bank(work)
    rc, out, err = _hook(belt, work, _ref(work, "HEAD"))
    assert rc == 0 and f"pre-push: wall honoured {banked}\n" in out, out + err
    (work / "README.md").write_text("an unmeasured change\n")
    _git(work, "commit", "-q", "-am", "unmeasured")
    tree = _git(work, "rev-parse", "HEAD^{tree}")
    for refs in (_ref(work, "HEAD"), _ref(work, "HEAD") + _ref(work, "HEAD", OFF_MAIN)):
        rc, out, err = _hook(belt, work, refs)
        assert rc == 2, out + err
        assert f"pre-push: wall main-refused {tree}\n" in out
        assert "!! pre-push: REFUSED — refs/heads/main moves by a pull request's merge" in err
        assert "./scripts/pm_push.sh --pr" in err
        assert "running the full gate" not in out
    assert _ran(work) == ""
    rc, out, _ = _hook(
        belt,
        work,
        _ref(work, "HEAD"),
        url=str(scratch / ".vouch-123" / "probe.git"),
        DJB_PUSH_DESTINATION="verifier-box",
    )
    assert rc == 0 and f"pre-push: wall box-exempt {tree}\n" in out


def test_a_remote_with_no_main_is_seeded_and_every_later_move_is_refused(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    """The null remote sha seeds main under the ordinary rules; a held main stays refused."""
    work = _world(scratch_repo, scratch)
    seeded = (
        "pre-push: main seeded — the remote had no main; every later move is a pull request's merge"
    )
    banked = _bank(work)
    rc, out, err = _hook(belt, work, _ref(work, "HEAD", remote=ZERO))
    assert rc == 0 and seeded in out and f"pre-push: wall honoured {banked}\n" in out, out + err
    (work / "README.md").write_text("an unmeasured first tree\n")
    _git(work, "commit", "-q", "-am", "unmeasured")
    tree = _git(work, "rev-parse", "HEAD^{tree}")
    rc, out, err = _hook(belt, work, _ref(work, "HEAD", remote=ZERO))
    assert rc == 0 and seeded in out, out + err
    assert f"pre-push: wall measuring {tree}\n" in out
    assert "caller=push-wall" in _ran(work)
    (work / "scripts" / "check.sh.ran").unlink()
    rc, out, err = _hook(belt, work, _ref(work, "HEAD"))
    assert rc == 2 and seeded not in out, out + err
    assert f"pre-push: wall main-refused {tree}\n" in out
    assert "!! pre-push: REFUSED — refs/heads/main moves by a pull request's merge" in err
    assert _ran(work) == ""


def test_a_branch_deletion_measures_nothing(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    work = _world(scratch_repo, scratch)
    (work / "README.md").write_text("an unmeasured working tree\n")
    rc, out, _ = _hook(belt, work, f"(delete) {ZERO} refs/heads/scratch {'1' * 40}\n")
    assert rc == 0, out
    assert "pre-push: wall deletion " in out
    assert "a deletion pushes no tree" in out
    assert "consulting the verdict" not in out
    assert _ran(work) == ""


def test_an_unreadable_ledger_refuses_the_push_with_exit_2(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    work = _world(scratch_repo, scratch)
    scratch_ledger.mkdir()
    rc, out, err = _hook(belt, work, _ref(work, "HEAD"))
    assert rc == 2, out + err
    assert "pre-push: wall could-not-look " in out
    assert "the verdict ledger could not be read" in err
    assert _ran(work) == ""
    rc, out, err = _hook(belt, work, _ref(work, "HEAD"), DJB_GATE_LEDGER="relative/ledger")
    assert rc == 2 and "is relative" in err


def test_an_unknown_hook_is_exit_2() -> None:
    done = subprocess.run(
        ["/usr/bin/python3", "-E", "-S", "-m", "quality.djb.cli", "hook", "post-merge"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    )
    assert done.returncode == 2 and "the hooks are pre-push, pre-commit, commit-msg" in done.stderr


def test_a_refused_push_names_the_untracked_paths_and_never_says_seeded(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    """The gate banked the checkout with a journal in it; the journal grew; HEAD has no verdict."""
    work = _world(scratch_repo, scratch)
    seeded = "pre-push: main seeded"
    journal = work / "NOTES.md"
    journal.write_text("the developer's own journal\n")
    ledger.record_full(
        work,
        tree=ledger.measured_tree(work),
        legs="drive-legs",
        caller="pm-bank",
        sanction=SANCTION,
    )
    journal.write_text("the developer's own journal\na row written after the gate\n")
    rc, out, err = _hook(belt, work, _ref(work, "HEAD", remote=ZERO))
    assert rc == 1, out + err
    assert "!! pre-push: REFUSED — the ref being pushed is not the tree in this checkout." in err
    assert "     ?? NOTES.md\n" in err
    assert (
        "   untracked, not ignored files are part of the measured tree: commit them, or ignore"
        " them (.gitignore or .git/info/exclude), then push again\n"
    ) in err
    assert err.index("this checkout measures:") < err.index("?? NOTES.md")
    assert seeded not in out + err
    for n in range(12):
        (work / f"extra-{n:02}.md").write_text(f"{n}\n")
    rc, out, err = _hook(belt, work, _ref(work, "HEAD", remote=ZERO))
    assert rc == 1 and "     … and 3 more\n" in err, out + err
    assert "?? extra-08.md" in err and "?? extra-09.md" not in err
    for path in work.glob("*.md"):
        if path.name != "README.md":
            path.unlink()
    _bank(work)
    rc, out, err = _hook(belt, work, _ref(work, "HEAD", remote=ZERO))
    assert rc == 0 and seeded in out, out + err


def test_a_push_of_another_commit_says_the_paths_are_heads(
    scratch_repo: Callable[..., Path], scratch: Path, scratch_ledger: Path, belt: Path
) -> None:
    """The porcelain rows are HEAD's: a pushed ref that is not HEAD is named before them."""
    work = _world(scratch_repo, scratch)
    _git(work, "checkout", "-q", "-b", "red")
    (work / "RED.md").write_text("bytes no gate measured\n")
    _git(work, "add", "RED.md")
    _git(work, "commit", "-q", "-m", "red")
    red = _git(work, "rev-parse", "red")
    _git(work, "checkout", "-q", "main")
    head = _git(work, "rev-parse", "HEAD")
    (work / "NOTES.md").write_text("the developer's own journal\n")
    rc, out, err = _hook(belt, work, _ref(work, "red", OFF_MAIN))
    line = (
        f"   HEAD is {head[:12]}; the pushed ref is {red[:12]} — the paths below are HEAD's,"
        " not the pushed commit's\n"
    )
    assert rc == 1 and line in err, out + err
    assert err.index(line) < err.index("?? NOTES.md")
    _git(work, "commit", "-q", "--allow-empty", "-m", "HEAD itself")
    rc, out, err = _hook(belt, work, _ref(work, "HEAD", OFF_MAIN))
    assert rc == 1 and "?? NOTES.md" in err and "the pushed ref is" not in err, out + err
