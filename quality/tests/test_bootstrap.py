"""`scripts/rung_start.sh`'s refusals and reset, and `scripts/setup.sh`'s fenced steps, end to end.

does-not-cover: rung_start's steps 2-5 end to end; past step 1 a scratch repository has no venv.
does-not-cover: a copy of rung_start.sh runs in the scratch repositories, copied fresh per case.
does-not-cover: whether a carried credential works, or whether main's tip is the brief's tree.
does-not-cover: steps 3, 4 and 6's call sites, which are read as text.
does-not-cover: `setup.sh` end to end; its fences are sourced and its call sites read as text.
does-not-cover: the real loop digest; a model of gate_ledger.sh's drop-by-key, anchored by one case.
does-not-cover: a real registry or pull; a `docker` stub answers and the workflow is read as YAML.
does-not-cover: a dirty detached checkout, or a repository whose default branch is not `main`.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    ".env.example",
    ".github/workflows/ci.yml",
    ".github/workflows/proof-from-zero.yml",
    "README.md",
    "apps/conftest.py",
    "compose.yaml",
    "manage.py",
    "pyproject.toml",
    "scripts/check.sh",
    "scripts/db.sh",
    "scripts/fe_gate.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "scripts/kill_mine.sh",
    "scripts/pm_push.sh",
    "scripts/provision.sh",
    "scripts/queue_cited.sh",
    "scripts/rung_start.sh",
    "scripts/secrets_scan.sh",
    "scripts/setup.sh",
    "scripts/steps.sh",
    "scripts/sweep.sh",
    "scripts/verifier_box.sh",
    "scripts/verify_start.sh",
)

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "scripts" / "rung_start.sh"
PROVISION = ROOT / "scripts" / "provision.sh"
SETUP = ROOT / "scripts" / "setup.sh"
COPIED = ("rung_start.sh", "bash_only.sh", "gate_refuse.sh", "steps.sh", "provision.sh")
NOTHING_WRITTEN = "Nothing was reset, installed, created or written."


def git(repo: Path, *args: str) -> str:
    """`git -C <repo> <args>`; its stripped stdout, raising on failure."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def git_rc(repo: Path, *args: str) -> int:
    """`git -C <repo> <args>`; its exit status alone."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode


def missing(text: str, *needles: str) -> list[str]:
    """The needles `text` does not carry."""
    return [needle for needle in needles if needle not in text]


def present(text: str, *needles: str) -> list[str]:
    """The needles `text` carries and must not."""
    return [needle for needle in needles if needle in text]


def line_of(path: Path, pattern: str) -> int | None:
    """The 1-based number of the first line of `path` matching `pattern`, or None."""
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if re.search(pattern, line):
            return number
    return None


def fence(path: Path, name: str) -> str:
    """The text between `# >>> <name> >>>` and `# <<< <name> <<<`, both lines kept."""
    lines = path.read_text().splitlines(keepends=True)
    opened = f"# >>> {name} >>>\n"
    closed = f"# <<< {name} <<<\n"
    if opened not in lines:
        raise CouldNotLook(f"{path.name} has no line reading exactly `{opened.strip()}`")
    start = lines.index(opened)
    if closed not in lines[start:]:
        raise CouldNotLook(f"{path.name} opens the {name} fence and never closes it")
    return "".join(lines[start : lines.index(closed, start) + 1])


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every key this checkout's `.env` declares, as no shell drive inherited them."""
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        name = line.split("=", 1)[0].strip()
        if "=" in line and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            monkeypatch.delenv(name, raising=False)


# scripts/rung_start.sh


@pytest.fixture(scope="module")
def step_total() -> str:
    """The step count `rung_start.sh` declares, asked rather than typed."""
    if shutil.which("git") is None:
        raise CouldNotLook("no git on PATH")
    if not os.access(REAL, os.X_OK):
        raise CouldNotLook("scripts/rung_start.sh is not an executable file in this tree")
    found = re.search(r"^STEP_TOTAL=([0-9]+)", REAL.read_text(), re.M)
    if not found:
        raise CouldNotLook("scripts/rung_start.sh declares no STEP_TOTAL")
    return found.group(1)


@pytest.fixture
def fixture_repo(scratch_repo: Callable[..., Path], step_total: str) -> Callable[[], Path]:
    """`fixture_repo()` builds a repository whose `main` has two commits and the script's copy."""
    count = 0

    def build() -> Path:
        nonlocal count
        count += 1
        repo = scratch_repo(f"repo{count}", "rung-start-port")
        (repo / "scripts").mkdir()
        for name in COPIED:
            shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
        (repo / "scripts" / "rung_start.sh").chmod(0o755)
        (repo / "tracked.txt").write_text("one\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        with (repo / "tracked.txt").open("a") as tracked:
            tracked.write("two\n")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-q", "-m", "second commit on main")
        return repo

    return build


@pytest.fixture
def rung(capture: Callable[..., Captured]) -> Callable[..., tuple[int, str]]:
    """`rung(repo, *args)` runs the repository's copy from inside it: (exit, transcript)."""

    def run(repo: Path, *args: str) -> tuple[int, str]:
        out = capture(["./scripts/rung_start.sh", *args], cwd=repo)
        return out.rc, out.text()

    return run


@pytest.fixture
def sourced(capture: Callable[..., Captured]) -> Callable[..., Captured]:
    """`sourced(body, *args, **env)` sources this tree's rung_start.sh and runs `body` after it."""

    def run(body: str, *args: str, **env: str) -> Captured:
        script = (
            'set -uo pipefail\nargs=("$@")\nset --\n(\n'
            f'. "{REAL}"\n'
            '[ "${#args[@]}" -eq 0 ] || set -- "${args[@]}"\n'
            f"{body}\n) || exit $?\n"
        )
        return capture(["bash", "-c", script, "port", *args], env=env)

    return run


def test_a_piped_stdout_is_refused(step_total: str) -> None:
    piped = subprocess.run([str(REAL)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert piped.returncode == 2, piped.stdout
    assert not missing(piped.stdout, "refuses pipes", "The exit status is the verdict")


def test_an_unknown_argument_is_refused(step_total: str, capture: Callable[..., Captured]) -> None:
    out = capture([str(REAL), "--force"])
    text = out.text()
    assert out.rc == 2, text
    assert "takes no arguments" in text
    assert f"step 1/{step_total}" not in text


def test_a_dirty_tree_is_refused_and_nothing_is_lost(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main~1")
    with (repo / "tracked.txt").open("a") as tracked:
        tracked.write("work in progress a builder has not committed\n")
    (repo / "untracked.txt").write_text("a new file nobody has added yet\n")
    before_tracked, before_head = (repo / "tracked.txt").read_text(), git(repo, "rev-parse", "HEAD")
    rc, text = rung(repo)
    assert rc == 2, text
    assert not missing(
        text,
        "uncommitted work",
        "REFUSING to reset",
        NOTHING_WRITTEN,
        "tracked.txt",
        "untracked.txt",
    )
    assert (repo / "tracked.txt").read_text() == before_tracked
    assert (repo / "untracked.txt").is_file()
    assert git(repo, "rev-parse", "HEAD") == before_head


def commit_a_leg(repo: Path) -> str:
    """A branch `work` off `main~1` with one commit main does not have; its HEAD."""
    git(repo, "checkout", "-q", "-b", "work", "main~1")
    (repo / "leg.txt").write_text("a finished leg, committed the way rung-execution §5 says to\n")
    git(repo, "add", "leg.txt")
    git(repo, "commit", "-q", "-m", "rung work main does not have")
    return git(repo, "rev-parse", "HEAD")


def test_a_branch_ahead_of_main_is_refused_and_the_commits_survive(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    before_head = commit_a_leg(repo)
    rc, text = rung(repo)
    assert rc == 2, text
    assert not missing(
        text,
        "commit(s) main does not have",
        "REFUSING to reset",
        "rung work main does not have",
        NOTHING_WRITTEN,
        "./scripts/rung_start.sh --resume",
    )
    assert git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / "leg.txt").is_file()


def test_a_stale_baseline_is_reset_and_said(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main~1")
    before_head = git(repo, "rev-parse", "HEAD")
    _, text = rung(repo)
    assert not missing(text, "** STALE BASELINE **", "1 commits behind main", "RESET 1 commits")
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "main")
    assert git(repo, "rev-parse", "HEAD") != before_head


def test_a_current_baseline_says_the_reset_was_a_no_op(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    _, text = rung(repo)
    assert "already current" in text
    assert "** STALE BASELINE **" not in text


def test_the_pool_mechanism_is_diagnosed_by_name(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "main~1"))
    git(repo, "checkout", "-q", "-b", "work", "origin/main")
    _, text = rung(repo)
    assert not missing(
        text,
        "THE POOL (why this keeps happening)",
        "origin/main is 1 commits behind local main",
        "This branch was created from: origin/main",
        "scripts/pm_push.sh",
        "** STALE BASELINE **",
    )
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "main")


def test_a_current_origin_main_prints_no_pool_block(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "main"))
    git(repo, "checkout", "-q", "-b", "work", "main")
    _, text = rung(repo)
    assert "THE POOL (why this keeps happening)" not in text


def test_a_detached_head_is_refused(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "--detach", "main")
    rc, text = rung(repo)
    assert rc == 2, text
    assert not missing(text, "detached HEAD", NOTHING_WRITTEN)


def test_no_local_main_is_refused(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    git(repo, "branch", "-q", "-D", "main")
    rc, text = rung(repo)
    assert rc == 2, text
    assert not missing(text, "no local branch 'main'", NOTHING_WRITTEN)


def test_the_storage_step_is_wired_and_is_not_fatal(step_total: str) -> None:
    source = REAL.read_text()
    assert int(step_total) >= 5
    assert "manage.py ensure_bucket" in source
    code = re.sub(r"#.*", "", source)
    assert not re.search(r"shasum|sha256sum|sha256_of|derived_bucket_name", code)
    assert "AWS_STORAGE_BUCKET_NAME=" in source
    assert "object storage ABSENT" in source
    db = line_of(REAL, r"^# STEP 3 · DATABASE")
    bucket = line_of(REAL, r"^# STEP 4 · STORAGE")
    introspect = line_of(REAL, r"^# STEP 5 · INTROSPECT")
    assert db and bucket and introspect and db < bucket < introspect, (db, bucket, introspect)


def frontend_fixture(scratch: Path, name: str, with_frontend: bool) -> Path:
    """A scratch root, optionally carrying a `frontend/` with a manifest and a lockfile."""
    root = require_scratch(scratch / f"fe-{name}", ROOT)
    root.mkdir()
    if with_frontend:
        (root / "frontend").mkdir()
        (root / "frontend" / "package.json").write_text(
            '{\n  "name": "fixture",\n  "private": true\n}\n'
        )
        (root / "frontend" / "pnpm-lock.yaml").write_text('lockfileVersion: "9.0"\n')
    return root


@dataclass(frozen=True)
class Shim:
    """A `pnpm` that records its argument vector and working directory, then exits as asked."""

    path: Path
    log: Path


def pnpm_shim(scratch: Path, rc: int) -> Shim:
    """Plant a recording `pnpm` exiting `rc`."""
    path, log = scratch / f"pnpm-shim-{rc}", scratch / f"pnpm-shim-{rc}.log"
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >>'{log}'\n"
        f"printf 'pwd=%s\\n' \"$(pwd -P)\" >>'{log}'\n"
        "mkdir -p ./node_modules\n"
        "printf 'hoistPattern:\\n  - \"*\"\\n' >./node_modules/.modules.yaml\n"
        f"exit {rc}\n"
    )
    path.chmod(0o755)
    return Shim(path, log)


INSTALL = 'frontend_install "$1"\nprintf \'FRONTEND_NOTE=[%s]\\n\' "${FRONTEND_NOTE:-}"'


def test_step_six_installs_when_frontend_and_pnpm_exist(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    root = frontend_fixture(scratch, "install", True)
    shim = pnpm_shim(scratch, 0)
    out = sourced(INSTALL, str(root), FE_PNPM=str(shim.path))
    text = out.text()
    assert out.rc == 0, text
    log = shim.log.read_text() if shim.log.is_file() else "<never called>"
    assert "install --frozen-lockfile" in log
    assert f"pwd={(root / 'frontend').resolve()}" in log
    assert not missing(
        text,
        "FRONTEND_NOTE=[]",
        "frontend/node_modules: for the fe leg's FULL state and pnpm pin:client; "
        "gen_client.sh uses npx and is unaffected",
    )


def test_step_six_skips_and_says_why_without_pnpm(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    root = frontend_fixture(scratch, "nopnpm", True)
    out = sourced(INSTALL, str(root), FE_PNPM=str(scratch / "no-such-pnpm"))
    text = out.text()
    assert out.rc == 0, text
    assert not missing(
        text, "skipped — pnpm not on PATH", "the fe leg will be could-not-look", "FRONTEND_NOTE=[]"
    )
    assert not (root / "frontend" / "node_modules").exists()


def test_step_six_skips_without_a_frontend(scratch: Path, sourced: Callable[..., Captured]) -> None:
    root = frontend_fixture(scratch, "nofrontend", False)
    shim = pnpm_shim(scratch, 0)
    out = sourced(INSTALL, str(root), FE_PNPM=str(shim.path))
    text = out.text()
    assert out.rc == 0, text
    assert not missing(text, "skipped — no frontend/ on this tree", "FRONTEND_NOTE=[]")
    assert not shim.log.exists(), "pnpm was invoked on a tree with no frontend/"


def test_a_failing_install_joins_the_footer_and_does_not_change_the_verdict(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    root = frontend_fixture(scratch, "failing", True)
    shim = pnpm_shim(scratch, 1)
    out = sourced(INSTALL, str(root), FE_PNPM=str(shim.path))
    text = out.text()
    assert out.rc == 0, text
    assert not missing(
        text,
        "pnpm install --frozen-lockfile exited 1",
        "THIS IS NOT FATAL",
        "FRONTEND_NOTE=[frontend/node_modules was not installed (pnpm exited 1)]",
    )


def test_step_six_is_idempotent_so_resume_may_run_it(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    root = frontend_fixture(scratch, "idempotent", True)
    shim = pnpm_shim(scratch, 0)
    modules = root / "frontend" / "node_modules" / ".modules.yaml"
    first = sourced(INSTALL, str(root), FE_PNPM=str(shim.path))
    assert first.rc == 0, first.text()
    assert modules.is_file(), "the first run left no node_modules"
    before = modules.read_bytes()
    second = sourced(INSTALL, str(root), FE_PNPM=str(shim.path))
    assert second.rc == 0, second.text()
    assert modules.read_bytes() == before


def test_step_six_is_wired_and_is_not_fatal(step_total: str) -> None:
    assert step_total == "6"
    if line_of(PROVISION, r"^frontend_install\(\) \{") is None:
        raise CouldNotLook("scripts/provision.sh defines no frontend_install")
    definition = line_of(REAL, r'^\. .*/provision\.sh"')
    call = line_of(REAL, r'^frontend_install "\$ROOT"')
    introspect = line_of(REAL, r"^# STEP 5 · INTROSPECT")
    seam = line_of(REAL, r'^if \[ "\$\{BASH_SOURCE\[0\]\}" != "\$0" \]; then')
    assert definition, "no frontend_install function — the cases above are driving nothing"
    assert call and introspect and call > introspect, (call, introspect)
    assert seam and definition < seam, (definition, seam)
    assert "FRONTEND_NOTE" in REAL.read_text()
    assert "FRONTEND_NOTE=" in PROVISION.read_text()
    assert "FE_PNPM" in PROVISION.read_text()


def test_resume_keeps_a_branch_ahead_of_main_and_says_what_it_skipped(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]], step_total: str
) -> None:
    repo = fixture_repo()
    before_head = commit_a_leg(repo)
    _, text = rung(repo, "--resume")
    assert not missing(
        text,
        "** RESUME **",
        "the reset in step 1 was SKIPPED",
        "skipped    git reset --hard main",
        "kept       1 commit(s) main does not have",
        "rung work main does not have",
        f"step 2/{step_total}",
        "** STALE BASELINE NOT REPAIRED **",
    )
    assert not present(text, "REFUSING to reset", "** STALE BASELINE **")
    assert git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / "leg.txt").is_file()


def test_resume_on_a_current_baseline_says_there_was_nothing_to_skip(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    before_head = git(repo, "rev-parse", "HEAD")
    _, text = rung(repo, "--resume")
    assert not missing(
        text,
        "** RESUME **",
        "kept       0 commits main does not have",
        "baseline   already current — nothing to skip past",
    )
    assert not present(text, "STALE BASELINE", "REFUSING to reset")
    assert git(repo, "rev-parse", "HEAD") == before_head


def test_resume_on_a_dirty_tree_still_refuses(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]], step_total: str
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    with (repo / "tracked.txt").open("a") as tracked:
        tracked.write("work in progress a builder has not committed\n")
    (repo / "untracked.txt").write_text("a new file nobody has added yet\n")
    before_tracked, before_head = (repo / "tracked.txt").read_text(), git(repo, "rev-parse", "HEAD")
    rc, text = rung(repo, "--resume")
    assert rc == 2, text
    assert not missing(
        text,
        "uncommitted work",
        "REFUSING to reset",
        "--resume DOES NOT LIFT THIS",
        NOTHING_WRITTEN,
    )
    assert f"step 2/{step_total}" not in text
    assert (repo / "tracked.txt").read_text() == before_tracked
    assert (repo / "untracked.txt").is_file()
    assert git(repo, "rev-parse", "HEAD") == before_head


def test_resume_does_not_lift_the_reporting_refusals(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]]
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "--detach", "main")
    rc, text = rung(repo, "--resume")
    assert rc == 2, text
    assert not missing(text, "detached HEAD", NOTHING_WRITTEN)
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    git(repo, "branch", "-q", "-D", "main")
    rc, text = rung(repo, "--resume")
    assert rc == 2, text
    assert not missing(text, "no local branch 'main'", NOTHING_WRITTEN)


def test_the_help_documents_resume(step_total: str, capture: Callable[..., Captured]) -> None:
    out = capture([str(REAL), "--help"])
    text = out.text()
    assert out.rc == 0, text
    assert not missing(text, "--resume", "RESET REMOVED", "It lifts NO refusal")


def test_expect_accepts_a_commit_sha_and_says_it_resolved_the_tree(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]], step_total: str
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    commit = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", f"{commit}^{{tree}}")
    _, text = rung(repo, "--expect", commit)
    assert not missing(
        text,
        f"handed a COMMIT: {commit}",
        f"resolved to tree {tree}",
        "MATCH",
        f"step 2/{step_total}",
    )
    assert f"handed a TREE: {commit}" not in text
    _, text = rung(repo, "--expect", tree)
    assert not missing(text, f"handed a TREE: {tree}", "MATCH")
    assert "resolved to tree" not in text


def test_expect_still_refuses_a_tree_that_does_not_match(
    fixture_repo: Callable[[], Path], rung: Callable[..., tuple[int, str]], step_total: str
) -> None:
    repo = fixture_repo()
    git(repo, "checkout", "-q", "-b", "work", "main")
    wrong_tree = git(repo, "rev-parse", "main~1^{tree}")
    before_head = git(repo, "rev-parse", "HEAD")
    rc, text = rung(repo, "--expect", wrong_tree)
    assert rc == 2, text
    assert not missing(
        text,
        "THE BASELINE IS NOT THE ONE THE BRIEF NAMED",
        f"expected tree  {wrong_tree}",
        "Flag it and hold",
        NOTHING_WRITTEN,
    )
    assert f"step 2/{step_total}" not in text
    assert git(repo, "rev-parse", "HEAD") == before_head
    rc, text = rung(repo, "--expect", "0" * 40)
    assert rc == 2, text
    assert "cannot resolve to a commit or a tree" in text
    assert "THE BASELINE IS NOT THE ONE THE BRIEF NAMED" not in text
    rc, text = rung(repo, "--expect")
    assert rc == 2, text
    assert "--expect takes a sha" in text


CANARY_PAT = "CARRY-CANARY-A-VALUE-THAT-MUST-NEVER-BE-PRINTED"  # pragma: allowlist secret
CANARY_AUD = "CARRY-CANARY-A-SECOND-VALUE-THAT-MUST-NEVER-BE-PRINTED"  # pragma: allowlist secret
CANARY_OTHER = "CARRY-CANARY-NOT-ZITADEL-AND-MUST-NOT-TRAVEL"  # pragma: allowlist secret
PRIMARY_ENV = f"""# A comment line that happens to spell ZITADEL_PAT= and carries no value.
DATABASE_NAME=djb_primary_checkout
ZITADEL_ISSUER=http://localhost:8081
ZITADEL_PAT={CANARY_PAT}
ZITADEL_MCP_AUDIENCE={CANARY_AUD}
ZITADEL_ORG_NAME=
SECRET_KEY={CANARY_OTHER}
NOT_ZITADEL_PAT={CANARY_OTHER}
"""
FRESH_ENV = """DATABASE_NAME=djb_fresh_worktree
ZITADEL_ISSUER=http://localhost:8081
ZITADEL_PAT=
ZITADEL_MCP_AUDIENCE=
SECRET_KEY=
"""
CARRY = 'zitadel_carry "$1" "$2"'
EMPTY_PRIMARY_ENV = "DATABASE_NAME=djb_primary_checkout\nZITADEL_PAT=\n"  # pragma: allowlist secret
EMPTY_PRIMARY_ENV += "ZITADEL_MCP_AUDIENCE=\nZITADEL_ORG_NAME=\n"


def test_the_identity_carry_copies_zitadel_keys_and_prints_no_value(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    primary, fresh = scratch / "primary.env", scratch / "fresh.env"
    primary.write_text(PRIMARY_ENV)
    fresh.write_text(FRESH_ENV)
    out = sourced(CARRY, str(primary), str(fresh))
    text = out.text()
    assert out.rc == 0, text
    assert not missing(
        text,
        "ZITADEL_* carried from the primary checkout",
        "KEY NAMES only",
        "ZITADEL_PAT",
        "ZITADEL_MCP_AUDIENCE",
        "ZITADEL_ISSUER",
    )
    assert not present(text, CANARY_PAT, CANARY_AUD)
    carried = fresh.read_text()
    assert not missing(
        carried,
        f"ZITADEL_PAT={CANARY_PAT}",
        f"ZITADEL_MCP_AUDIENCE={CANARY_AUD}",
        "DATABASE_NAME=djb_fresh_worktree",
    )
    assert len(re.findall(r"^ZITADEL_PAT=", carried, re.M)) == 1


def test_the_identity_carry_population_is_the_zitadel_prefix_only(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    primary, fresh = scratch / "primary.env", scratch / "fresh.env"
    primary.write_text(PRIMARY_ENV)
    fresh.write_text(FRESH_ENV)
    out = sourced(CARRY, str(primary), str(fresh))
    text = out.text()
    assert out.rc == 0, text
    carried = fresh.read_text()
    assert not present(carried, CANARY_OTHER, "NOT_ZITADEL_PAT", "ZITADEL_ORG_NAME")
    assert not present(text, "SECRET_KEY", "NOT_ZITADEL_PAT", "ZITADEL_ORG_NAME")
    assert "SECRET_KEY=" in carried


def test_the_identity_carry_on_an_empty_primary_carries_nothing(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    primary, fresh = scratch / "primary.env", scratch / "fresh.env"
    primary.write_text(EMPTY_PRIMARY_ENV)
    fresh.write_text(FRESH_ENV)
    out = sourced(CARRY, str(primary), str(fresh))
    text = out.text()
    assert out.rc == 0, text
    assert not missing(text, "carries no populated ZITADEL_* value", "zitadel_seed")
    assert "ZITADEL_* carried from the primary checkout" not in text
    assert fresh.read_text() == FRESH_ENV


def test_the_identity_carry_says_so_when_there_is_no_primary_env(
    scratch: Path, sourced: Callable[..., Captured]
) -> None:
    fresh = scratch / "fresh.env"
    fresh.write_text(FRESH_ENV)
    out = sourced(CARRY, str(scratch / "no-such.env"), str(fresh))
    text = out.text()
    assert out.rc == 0, text
    assert "no readable .env" in text
    assert fresh.read_text() == FRESH_ENV


def test_the_identity_carry_is_wired_into_step_three() -> None:
    source = REAL.read_text()
    definition = line_of(REAL, r"^zitadel_carry\(\) \{")
    call = line_of(REAL, r'^ *zitadel_carry "')
    db = line_of(REAL, r"^# STEP 3 · DATABASE")
    assert definition, "no zitadel_carry function — the cases above are driving nothing"
    assert "BASH_SOURCE[0]" in source
    assert call and db and call > db, (call, db)
    assert "ZITADEL_* left alone" in "\n".join(source.splitlines()[db - 1 :])


def test_the_pin_marker_is_read_from_db_sh_and_not_recopied() -> None:
    assert line_of(REAL, r"pinned' *\"\$ROOT/\.env\"") is None
    decide = line_of(REAL, r"^db_pin_decide$")
    assert decide, "this script never calls db_pin_decide"
    db_source = line_of(REAL, r'^\. "\$ROOT/scripts/db\.sh"')
    assert db_source and decide > db_source, (decide, db_source)
    create = line_of(REAL, r"^db_create_out=\$\(db_create 2>&1\)$")
    assert create and create > decide, (create, decide)
    assert "marker — DATABASE_NAME left alone" in REAL.read_text()


def test_an_unmarked_exported_stale_pin_is_overridden_and_the_leg_is_silent(
    fixture_repo: Callable[[], Path], capture: Callable[..., Captured]
) -> None:
    pin = fence(REAL, "env-pin")
    assert "db_pin_decide" in pin
    repo = fixture_repo()
    (repo / ".env").write_text("DEBUG=1\nDATABASE_NAME=djb_stale\n")
    script = (
        "(\n"
        "export DATABASE_NAME=djb_stale\n"
        "unset DATABASE_NAME_SOURCE\n"
        f'. "{ROOT}/scripts/db.sh" 2>/dev/null\n'
        f'ROOT="{repo}"\n'
        "say() { printf '   %s\\n' \"$*\"; }\n"
        f"{pin}"
        'echo "block-left-DATABASE_NAME=${DATABASE_NAME}"\n'
        'echo "derived=$(db_name)"\n'
        'echo "== the leg, same checkout, same shell"\n'
        "db_pin_leg fast\n"
        'echo "leg-rc=$?"\n'
        ") || exit $?\n"
    )
    out = capture(["bash", "-c", script], cwd=repo)
    text = out.text()
    assert out.rc == 0, text
    derived = re.search(r"^derived=(.*)$", text, re.M)
    assert derived and derived.group(1), text
    name = derived.group(1)
    assert not missing(
        text,
        f"DATABASE_NAME: the unmarked .env pin djb_stale (also exported in this shell) was "
        f'overridden by the derivation {name}; add "# pinned" above it to keep it',
        f"block-left-DATABASE_NAME={name}",
        "leg-rc=0",
    )
    assert "DISAGREE" not in text
    pins = [
        line
        for line in (repo / ".env").read_text().splitlines()
        if line.startswith("DATABASE_NAME=")
    ]
    assert pins[-1] == f"DATABASE_NAME={name}"


# scripts/setup.sh's fences


@pytest.fixture(scope="module")
def prelude(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One file that sources what the drive sourced: db.sh, the four fences, the control's three."""
    for path in (SETUP, ROOT / "scripts" / "gate_ledger.sh", ROOT / "scripts" / "check.sh"):
        if not path.is_file():
            raise CouldNotLook(f"{path.relative_to(ROOT)} is not in this tree")
    if shutil.which("shasum") is None and shutil.which("sha256sum") is None:
        raise CouldNotLook("neither shasum nor sha256sum is on PATH")
    work = require_scratch(tmp_path_factory.mktemp("fences"), ROOT)
    defines = {
        "env-sync": "env_sync_from_example() {",
        "services": "services_up() {",
        "local-main": "ensure_local_main() {",
        "zitadel-pat": "adopt_zitadel_pat() {",
        "step-wall": "setup_total() {",
        "sign-in-door": "sign_in_door() {",
    }
    for name, definition in defines.items():
        text = fence(SETUP, name)
        if f"\n{definition}" not in text:
            raise CouldNotLook(f"the {name} fence in scripts/setup.sh defines no {definition[:-4]}")
        (work / f"{name}.sh").write_text(text)
    body = f"""ROOT="{ROOT}"
WORK="${{PORT_WORK:-{work}}}"
cd "$ROOT" || exit 3
make_tmp() {{
    local __t="$1"
    printf -v "$__t" '%s' "$(mktemp "${{WORK}}/tmp.XXXXXXXX")"
}}
. scripts/db.sh 2>/dev/null
. "{work}/env-sync.sh"
SERVICES=(db minio)
. scripts/ci_stack.sh
. "{work}/services.sh"
. "{work}/local-main.sh"
. "{work}/zitadel-pat.sh"
. "{work}/sign-in-door.sh"
. scripts/gate_refuse.sh
. scripts/secrets_scan.sh
"""
    prelude_path = work / "prelude.sh"
    prelude_path.write_text(body)
    probe = subprocess.run(
        [
            "bash",
            "-c",
            f'. "{prelude_path}" >/dev/null 2>&1; command -v env_sync_from_example '
            "services_up image_registry_host ensure_local_main adopt_zitadel_pat sign_in_door",
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise CouldNotLook(f"sourcing the fences left a function undefined: {probe.stdout!r}")
    return prelude_path


@pytest.fixture
def fenced(
    prelude: Path, scratch: Path, capture: Callable[..., Captured]
) -> Callable[..., Captured]:
    """`fenced(body, cwd=…, **env)` runs `body` after the prelude, in `cwd` (default this tree)."""

    def run(body: str, cwd: Path = ROOT, **env: str) -> Captured:
        script = (
            f'set -uo pipefail\n. "{prelude}" >/dev/null 2>&1\ncd "{cwd}" || exit 3\n'
            f"(\n{body}\n) || exit $?\n"
        )
        return capture(["bash", "-c", script], env={"PORT_WORK": str(scratch), **env})

    return run


CURL_REFUSED = "curl: (7) Failed to connect to localhost port 8081 after 0 ms: Couldn't connect"


def test_the_sign_in_door_quotes_curls_own_error_under_its_refusal(
    fenced: Callable[..., Captured], scratch: Path, stub_path: StubPath
) -> None:
    case = scratch / "sign-in-door"
    case.mkdir()
    (case / ".env").write_text("ZITADEL_PAT=planted\nZITADEL_ISSUER=http://localhost:8081\n")
    stub_path.plant("curl", f"#!/bin/sh\necho {CURL_REFUSED!r} >&2\nprintf '\\n000'\nexit 7\n")
    done = fenced("sign_in_door", cwd=case, PATH=stub_path.path)
    assert done.rc == 0, done.text()
    assert f"   the tool said: {CURL_REFUSED}" in done.text(), done.text()


def plant(directory: Path, name: str, *lines: str) -> Path:
    """Write `lines` (newline-terminated) to `directory/name`; an empty file when none."""
    path = directory / name
    path.write_text("".join(f"{line}\n" for line in lines))
    return path


@dataclass
class Synced:
    """One `env_sync_from_example` run in its own case directory."""

    case: Path
    rc: int
    block: str

    @property
    def env(self) -> str:
        """The `.env` the run left."""
        return (self.case / ".env").read_text()


@pytest.fixture
def sync(scratch: Path, fenced: Callable[..., Captured]) -> Callable[..., Synced]:
    """`sync(example_lines, env_lines)` plants a case directory and runs the env step in it."""
    count = 0

    def run(
        example: tuple[str, ...] | None, env: tuple[str, ...] | None, case: Path | None = None
    ) -> Synced:
        nonlocal count
        if case is None:
            count += 1
            case = require_scratch(scratch / f"case{count}", ROOT)
            case.mkdir()
            if example is not None:
                plant(case, ".env.example", *example)
            if env is not None:
                plant(case, ".env", *env)
        out = fenced("env_sync_from_example", cwd=case)
        block = out.path.read_text() if out.path.is_file() else ""
        return Synced(case, out.rc, block)

    return run


EXAMPLE = ("# the first key", "ALPHA=one", "BETA=two", "", "# the third key", "GAMMA=three")
DRIFTED = ("GAMMA=three", "DELTA=kept-value", "ALPHA=changed")
EXPECTED = (
    "# the first key\nALPHA=changed\nBETA=two\n\n# the third key\nGAMMA=three\n\n"
    "# --- kept from a previous .env: not in .env.example ---\nDELTA=kept-value\n"
)
KEPT_MARKER = "# --- kept from a previous .env: not in .env.example ---"


@pytest.fixture
def regenerated(sync: Callable[..., Synced]) -> Synced:
    """The criteria's fixture regenerated: six example lines, a drifted `.env` of three."""
    return sync(EXAMPLE, DRIFTED)


def test_the_result_is_the_example_with_the_values_carried_over(regenerated: Synced) -> None:
    assert regenerated.rc == 0, regenerated.block
    assert regenerated.env == EXPECTED


def test_the_changed_value_sits_at_the_examples_position(regenerated: Synced) -> None:
    assert regenerated.env.splitlines()[1] == "ALPHA=changed"


def test_the_extra_key_sits_after_the_marker(regenerated: Synced) -> None:
    lines = regenerated.env.splitlines()
    assert KEPT_MARKER in lines and "DELTA=kept-value" in lines
    assert lines.index("DELTA=kept-value") > lines.index(KEPT_MARKER)


def test_the_block_counts_one_added_one_preserved_one_kept(regenerated: Synced) -> None:
    assert not missing(
        regenerated.block,
        "1 key(s) added from .env.example: BETA",
        "1 value(s) preserved in place: ALPHA",
        "1 key(s) not in .env.example kept at the end: DELTA",
        ".env.previous written",
    )


def test_the_block_never_prints_a_value(regenerated: Synced) -> None:
    assert regenerated.block
    assert "=" not in regenerated.block, regenerated.block


def test_the_previous_file_is_the_original(regenerated: Synced) -> None:
    previous = regenerated.case / ".env.previous"
    assert previous.read_text() == "".join(f"{line}\n" for line in DRIFTED)
    mode = previous.stat().st_mode
    assert stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600, oct(mode)


def test_a_second_run_changes_nothing_and_says_so(
    regenerated: Synced, sync: Callable[..., Synced]
) -> None:
    after_first = regenerated.env
    again = sync(None, None, case=regenerated.case)
    assert again.rc == 0, again.block
    assert again.env == after_first
    assert (regenerated.case / ".env.previous").read_text() == again.env
    assert ".env already matches .env.example's shape — nothing to do" in again.block


def test_a_value_holding_an_equals_or_a_hash_survives(sync: Callable[..., Synced]) -> None:
    run = sync(
        ("# the doors", "URL=https://example.invalid/x", "NOTE=plain", "PLAIN=same"),
        (
            "URL=https://example.invalid/x?a=b&c=d",
            "NOTE=has # a hash and = an equals",
            "PLAIN=same",
        ),
    )
    assert run.rc == 0, run.block
    lines = run.env.splitlines()
    for line in (
        "URL=https://example.invalid/x?a=b&c=d",
        "NOTE=has # a hash and = an equals",
        "PLAIN=same",
    ):
        assert line in lines
    assert len(lines) == 4


def test_no_env_at_all_copies_the_example(sync: Callable[..., Synced]) -> None:
    run = sync(("# a comment", "ALPHA=one", "BETA=two"), None)
    assert run.rc == 0, run.block
    assert run.env == (run.case / ".env.example").read_text()
    assert not missing(run.block, "0 value(s) preserved in place", ".env.previous not written")
    assert not (run.case / ".env.previous").exists()


def test_no_example_is_a_refusal_that_touches_nothing(sync: Callable[..., Synced]) -> None:
    run = sync(None, ("ALPHA=mine", "BETA=also-mine"))
    assert run.rc == 1, run.block
    assert not missing(run.block, ".env.example", "was not written and was not touched")
    assert run.env == "ALPHA=mine\nBETA=also-mine\n"
    assert not (run.case / ".env.previous").exists()


def test_an_empty_env_is_a_truncated_file_and_not_an_empty_environment(
    sync: Callable[..., Synced],
) -> None:
    run = sync(("# the doors", "ALPHA=one", "BETA=two", "", "GAMMA=three"), ())
    assert run.rc == 0, run.block
    assert run.env == (run.case / ".env.example").read_text()
    assert not missing(
        run.block,
        "3 key(s) added from .env.example: ALPHA BETA GAMMA",
        "0 value(s) preserved in place",
        "0 key(s) not in .env.example kept at the end",
        ".env.previous written",
    )
    assert KEPT_MARKER not in run.env.splitlines()
    previous = run.case / ".env.previous"
    assert previous.is_file() and previous.stat().st_size == 0
    assert "=" not in run.block


def test_the_pinned_marker_survives_the_rebuild(sync: Callable[..., Synced]) -> None:
    run = sync(
        ("# the database", "DATABASE_URL=", "DATABASE_NAME=", "OTHER=1"),
        ("OTHER=1", "# pinned — the owner said so", "DATABASE_NAME=djb_x"),
    )
    assert run.rc == 0, run.block
    lines = run.env.splitlines()
    assert lines[lines.index("DATABASE_NAME=djb_x") - 1] == "# pinned — the owner said so"
    assert run.env.count("pinned") == 1
    run = sync(("OTHER=1",), ("# pinned", "DATABASE_NAME=djb_y", "OTHER=1"))
    assert run.rc == 0, run.block
    lines = run.env.splitlines()
    assert lines[lines.index("DATABASE_NAME=djb_y") - 1] == "# pinned"
    run = sync(("DATABASE_NAME=", "OTHER=1"), ("# pinned", "OTHER=2", "DATABASE_NAME=djb_z"))
    assert run.rc == 0, run.block
    assert "pinned" not in run.env


def test_a_key_present_twice_collapses_to_its_last_value(sync: Callable[..., Synced]) -> None:
    run = sync(("# the doors", "ALPHA=one", "BETA=two"), ("ALPHA=first", "BETA=two", "ALPHA=last"))
    assert run.rc == 0, run.block
    assert not missing(
        run.block,
        "1 value(s) preserved in place: ALPHA",
        "0 key(s) added from .env.example",
        "0 key(s) not in .env.example kept at the end",
    )
    lines = run.env.splitlines()
    assert lines[1] == "ALPHA=last"
    assert sum(line.startswith("ALPHA=") for line in lines) == 1
    assert "ALPHA=first" not in lines
    assert len(lines) == 3


def env_file_digest(path: Path, drop: tuple[str, ...]) -> str:
    """A model of `loop_env_fingerprint`'s env-file part: drop the keys named, SHA-256 the rest."""
    kept = []
    for line in path.read_text().splitlines():
        name = re.sub(r"[ \t]", "", line.split("=", 1)[0])
        if name not in drop:
            kept.append(f"{line}\n")
    return hashlib.sha256("".join(kept).encode()).hexdigest()


def test_the_digest_agrees_when_the_files_agree(sync: Callable[..., Synced], scratch: Path) -> None:
    run = sync(
        ("# the identity carry", "ZITADEL_PAT=", "DATABASE_NAME=djb_example", "", "ALPHA=one"),
        ("ALPHA=one", "ZITADEL_PAT=a-machine-credential", "DATABASE_NAME=djb_the_builders_own"),
    )
    assert run.rc == 0, run.block
    clone = plant(
        scratch,
        "clone.env",
        "# the identity carry",
        "ZITADEL_PAT=a-machine-credential",
        "DATABASE_NAME=djb_the_clones_own",
        "",
        "ALPHA=one",
    )
    ours = env_file_digest(run.case / ".env", ("DATABASE_NAME",))
    theirs = env_file_digest(clone, ("DATABASE_NAME",))
    assert ours == theirs
    plus = scratch / "clone-plus.env"
    plus.write_text(clone.read_text() + f"\n{KEPT_MARKER}\nMINE=set-by-hand\n")
    assert env_file_digest(plus, ("DATABASE_NAME",)) != theirs


def test_the_digest_model_still_matches_the_shipped_digest() -> None:
    ledger = (ROOT / "scripts" / "gate_ledger.sh").read_text()
    assert not missing(ledger, "if (name in drop) next", 'sub(/=.*$/, "", name)', "| sha256_of")
    assert re.search(r"^sha256_of\(\)", (ROOT / "scripts" / "gate_refuse.sh").read_text(), re.M)


DOCKER_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"
case "$*" in
*"compose ps -a"*)
    printf '%s' "${DJB_DRIVE_PS:-}"
    ;;
*"compose ps"*)
    printf '%s' "${DJB_DRIVE_PS:-}" |
        awk -F '\\t' -v s="${!#}" '$1 == s && $2 == "running" { print $3 }'
    ;;
*"compose config --images"*)
    awk -v want=" ${*:4} " '
        /^  [^ ]/ { service = $1; sub(/:$/, "", service) }
        /^    image:/ && (want == "  " || index(want, " " service " ")) { print $2 }
    ' "$DJB_DRIVE_COMPOSE"
    ;;
*"compose config"*)
    from="${DJB_DRIVE_CONFIG_REFUSE_FROM:-0}"
    seen=$(grep -c 'compose config$' "$DJB_DRIVE_DOCKER_LOG")
    if [ "$from" -gt 0 ] && [ "$seen" -ge "$from" ]; then
        echo 'service "zitadel" refers to undefined volume zitadel_bootstrap: invalid' >&2
        exit 15
    fi
    cat "$DJB_DRIVE_COMPOSE"
    ;;
*"compose cp"*)
    printf '%s\\n' "${DJB_DRIVE_CP_ERR:-}" >&2
    exit "${DJB_DRIVE_CP_RC:-0}"
    ;;
*"manifest inspect"*)
    printf '%s\\n' "${DJB_DRIVE_MANIFEST_ERR:-}" >&2
    exit "${DJB_DRIVE_MANIFEST_RC:-0}"
    ;;
*"compose pull"*)
    if [ "${DJB_DRIVE_PULL_RC:-0}" -ne 0 ] && [ -n "${DJB_DRIVE_PULL_LINE:-}" ]; then
        printf '%s\\n' "$DJB_DRIVE_PULL_LINE" >&2
        exit "${DJB_DRIVE_PULL_RC}"
    fi
    if [ "${DJB_DRIVE_PULL_RC:-0}" -ne 0 ]; then
        echo "${DJB_DRIVE_PLANTED_REF} Pulling"
        echo "Error response from daemon: manifest for ${DJB_DRIVE_PLANTED_REF} not found:" \\
            "manifest unknown" >&2
        exit "${DJB_DRIVE_PULL_RC}"
    fi
    echo "${DJB_DRIVE_PLANTED_REF} Pulled"
    ;;
esac
exit 0
"""
MINIO_PINNED_REF = (
    "public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z"
    "@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f"
)


@dataclass(frozen=True)
class Services:
    """One `services_up` run: its exit, its output and every docker invocation in order."""

    rc: int
    text: str
    docker_log: list[str]


HEALTHY_PS = "db\trunning\thealthy\t0\nminio\trunning\thealthy\t0\n"
ONE_SHOT_COMPOSE = (
    "name: djangobootstrap",
    "services:",
    "  db:",
    "    image: postgres:17",
    "  init:",
    "    image: postgres:17",
    "    depends_on:",
    "      db:",
    "        condition: service_healthy",
    "  minio:",
    "    depends_on:",
    "      init:",
    "        condition: service_completed_successfully",
)


@pytest.fixture
def services(scratch: Path, fenced: Callable[..., Captured]) -> Callable[..., Services]:
    """`services(ref, ps, pull_rc, …)` runs `services_up`; `ps` is the shim's `ps -a` answer."""

    def run(
        ref: str,
        ps: str,
        pull_rc: int,
        one_shot: bool = False,
        manifest_err: str = "",
        manifest_rc: int = 0,
        pull_line: str = "",
        compose: tuple[str, ...] = (),
        config_refuse_from: int = 0,
    ) -> Services:
        case = scratch / "services"
        (case / "bin").mkdir(parents=True)
        (case / "bin" / "docker").write_text(DOCKER_SHIM)
        (case / "bin" / "docker").chmod(0o755)
        if compose:
            plant(case, "compose.yaml", *compose)
        elif one_shot:
            plant(case, "compose.yaml", *ONE_SHOT_COMPOSE, f"    image: {ref}")
        else:
            plant(
                case,
                "compose.yaml",
                "name: djangobootstrap",
                "services:",
                "  db:",
                "    image: postgres:17",
                "  minio:",
                f"    image: {ref}",
            )
        log = case / "docker.log"
        log.write_text("")
        listed = "SERVICES=(db init minio)\n" if one_shot else ""
        out = fenced(
            f'export PATH="{case / "bin"}:$PATH"\n{listed}services_up',
            DJB_DRIVE_DOCKER_LOG=str(log),
            DJB_DRIVE_COMPOSE=str(case / "compose.yaml"),
            DJB_DRIVE_PS=ps,
            DJB_DRIVE_PULL_RC=str(pull_rc),
            DJB_DRIVE_PLANTED_REF=ref,
            DJB_DRIVE_MANIFEST_ERR=manifest_err,
            DJB_DRIVE_MANIFEST_RC=str(manifest_rc),
            DJB_DRIVE_PULL_LINE=pull_line,
            DJB_DRIVE_CONFIG_REFUSE_FROM=str(config_refuse_from),
        )
        return Services(out.rc, out.text(), log.read_text().splitlines())

    return run


def invoked(run: Services, words: str) -> bool:
    """Whether any docker invocation carries `words`."""
    return any(words in call for call in run.docker_log)


def test_a_pull_failure_is_could_not_look_naming_the_image(
    services: Callable[..., Services],
) -> None:
    ref = "example/files-store:RELEASE.9999-01-01T00-00-00Z"
    run = services(ref, "", 1)
    assert run.rc == 2, run.text
    assert not missing(
        run.text, "COULD NOT LOOK", ref, "(registry docker.io)", "NOTHING WAS STARTED"
    )
    assert invoked(run, "compose pull")
    assert not invoked(run, "compose up")
    assert "ci_stack: up --wait" not in run.text


@pytest.mark.parametrize(
    ("chosen", "named"),
    [
        ("", "the stack registry: docker.io (DJB_STACK_REGISTRY unset)"),
        (
            "registry.example.com/stack",
            "the stack registry: registry.example.com/stack (DJB_STACK_REGISTRY)",
        ),
    ],
)
def test_the_pull_refusal_names_the_registry_the_product_chose(
    services: Callable[..., Services], monkeypatch: pytest.MonkeyPatch, chosen: str, named: str
) -> None:
    monkeypatch.setenv("DJB_STACK_REGISTRY", chosen)
    run = services("example/files-store:RELEASE.9999-01-01T00-00-00Z", "", 1)
    assert run.rc == 2, run.text
    assert named in run.text, run.text


def test_a_healthy_stack_is_reused_without_a_pull(services: Callable[..., Services]) -> None:
    run = services(MINIO_PINNED_REF, HEALTHY_PS, 0)
    assert run.rc == 0, run.text
    assert "reusing running stack" in run.text
    assert not invoked(run, "compose pull")
    assert not invoked(run, "compose up")
    assert "ci_stack: up --wait" not in run.text


@pytest.mark.parametrize(
    "init_row",
    ["init\texited\t\t0\n", ""],
    ids=["exited-0", "removed-after-its-dependant-came-up-healthy"],
)
def test_a_stack_whose_one_shot_completed_is_reused_without_a_pull(
    services: Callable[..., Services], init_row: str
) -> None:
    run = services(MINIO_PINNED_REF, HEALTHY_PS + init_row, 0, one_shot=True)
    assert run.rc == 0, run.text
    assert "reusing running stack" in run.text
    assert not invoked(run, "compose pull")
    assert not invoked(run, "compose up")


@pytest.mark.parametrize(
    "ps",
    [
        HEALTHY_PS + "init\texited\t\t1\n",
        "db\trunning\thealthy\t0\nminio\trunning\tstarting\t0\n",
        "db\trunning\thealthy\t0\n",
    ],
    ids=["one-shot-exited-1", "dependant-not-healthy", "neither-ran"],
)
def test_a_one_shot_that_did_not_complete_falls_through_to_the_pull(
    services: Callable[..., Services], ps: str
) -> None:
    run = services(MINIO_PINNED_REF, ps, 0, one_shot=True)
    assert run.rc == 0, run.text
    assert "reusing running stack" not in run.text
    assert invoked(run, "compose pull")


@pytest.mark.parametrize(
    ("said", "remedy"),
    [
        (
            "Your authorization token has expired. Reauthenticate and try again.",
            "remedy: a stored login for public.ecr.aws is stale or expired",
        ),
        (
            "manifest unknown: manifest unknown",
            "remedy: public.ecr.aws no longer serves this pin",
        ),
    ],
    ids=["stale-login", "pin-no-longer-served"],
)
def test_a_refused_pull_prints_the_manifest_reads_own_cause_and_its_remedy(
    services: Callable[..., Services], said: str, remedy: str
) -> None:
    run = services(MINIO_PINNED_REF, "", 1, manifest_err=said, manifest_rc=1)
    assert run.rc == 2, run.text
    assert invoked(run, f"manifest inspect {MINIO_PINNED_REF}")
    assert not missing(run.text, f"docker manifest inspect {MINIO_PINNED_REF}", said, remedy)


def test_compose_measured_refusal_line_inspects_the_failing_services_own_pin(
    services: Callable[..., Services],
) -> None:
    stripped = MINIO_PINNED_REF.replace(":RELEASE.2025-09-07T16-13-09Z", "")
    said = "Your authorization token has expired. Reauthenticate and try again."
    run = services(
        MINIO_PINNED_REF,
        "",
        1,
        manifest_err=said,
        manifest_rc=1,
        pull_line=(
            f'minio Error failed to resolve reference "{stripped}": unexpected status from'
            f" HEAD request to https://public.ecr.aws/v2/w9i8o4b2/minio/manifests/"
            f"{stripped.rsplit('@', 1)[1]}: 403 Forbidden"
        ),
    )
    assert run.rc == 2, run.text
    assert invoked(run, "compose config --images minio")
    assert invoked(run, f"manifest inspect {MINIO_PINNED_REF}")
    assert not invoked(run, "manifest inspect postgres")
    assert not missing(
        run.text,
        said,
        "remedy: a stored login for public.ecr.aws is stale or expired",
        "docker logout public.ecr.aws",
    )


def test_the_reuse_line_names_the_project_and_ports_compose_publishes(
    services: Callable[..., Services],
) -> None:
    published: tuple[str, ...] = (
        "    ports:",
        "      - mode: ingress",
        '        published: "5432"',
    )
    published += ("      - mode: ingress", '        published: "8233"')
    rendered = ("name: djangobootstrap", "services:", "  db:", *published, "  minio:")
    run = services(
        MINIO_PINNED_REF,
        HEALTHY_PS,
        0,
        compose=(*rendered, "    ports:", '      - published: "1025"', "        target: 1025"),
    )
    assert run.rc == 0, run.text
    assert (
        "reusing running stack (compose project djangobootstrap, ports 5432/8233/1025)" in run.text
    )


def test_a_reuse_line_compose_cannot_render_is_could_not_look_never_unnamed(
    services: Callable[..., Services],
) -> None:
    run = services(MINIO_PINNED_REF, HEALTHY_PS, 0, config_refuse_from=2)
    assert run.rc == 2, run.text
    assert "COULD NOT LOOK — the stack answered healthy" in run.text, run.text
    assert 'the tool said: service "zitadel" refers to undefined volume' in run.text, run.text
    assert "<unnamed>" not in run.text and "reusing running stack" not in run.text
    assert not invoked(run, "compose up")


def test_a_reuse_line_whose_render_carries_no_name_is_could_not_look_never_unnamed(
    services: Callable[..., Services],
) -> None:
    rendered = ("services:", "  db:", "    image: postgres:17", "  minio:")
    run = services(
        MINIO_PINNED_REF, HEALTHY_PS, 0, compose=(*rendered, f"    image: {MINIO_PINNED_REF}")
    )
    assert run.rc == 2, run.text
    assert "COULD NOT LOOK — the stack answered healthy" in run.text, run.text
    assert "rendered no `name:` line; its first line: services:" in run.text, run.text
    assert "<unnamed>" not in run.text and "reusing running stack" not in run.text
    assert not invoked(run, "compose up")


def pat_copy(fenced: Callable[..., Captured], scratch: Path, said: str, rc: int) -> tuple[int, str]:
    """`adopt_zitadel_pat` over a `.env` with no PAT; the shim's `compose cp` answers `said`."""
    case = scratch / "pat"
    (case / "bin").mkdir(parents=True)
    (case / "bin" / "docker").write_text(DOCKER_SHIM)
    (case / "bin" / "docker").chmod(0o755)
    plant(case, ".env", "ZITADEL_PAT=")
    log = case / "docker.log"
    out = fenced(
        f'export PATH="{case / "bin"}:$PATH"\nadopt_zitadel_pat "{case / "machine.pat"}"',
        cwd=case,
        DJB_DRIVE_DOCKER_LOG=str(log),
        DJB_DRIVE_CP_ERR=said,
        DJB_DRIVE_CP_RC=str(rc),
    )
    return out.rc, out.text()


def test_a_pat_copy_refused_by_a_stopped_daemon_says_so_and_prescribes_no_drop(
    fenced: Callable[..., Captured], scratch: Path
) -> None:
    said = (
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock."
        " Is the docker daemon running?"
    )
    rc, text = pat_copy(fenced, scratch, said, 1)
    assert rc == 0, text
    assert not missing(text, "exited 1; its first line:", said, "Docker is not running")
    assert "drop the zitadel database" not in text
    assert "DESTRUCTIVE" not in text


def test_a_volume_with_no_pat_names_the_drop_as_destructive_and_last(
    fenced: Callable[..., Captured], scratch: Path
) -> None:
    said = "Error response from daemon: Could not find the file /zitadel/bootstrap/machine.pat"
    rc, text = pat_copy(fenced, scratch, said, 1)
    assert rc == 0, text
    assert not missing(text, said, "holds no PAT", "DESTRUCTIVE", "drop the zitadel database")
    assert "Docker is not running" not in text


def test_a_clean_pull_starts_the_stack_and_then_waits(services: Callable[..., Services]) -> None:
    run = services(MINIO_PINNED_REF, "", 0)
    assert run.rc == 0, run.text
    for words in ("compose pull", "compose up -d", "compose up -d --wait db minio"):
        assert invoked(run, words), words
    assert "ci_stack: up --wait db minio" in run.text
    assert "COULD NOT LOOK" not in run.text
    pull = next(i for i, call in enumerate(run.docker_log) if "compose pull" in call)
    up = next(i for i, call in enumerate(run.docker_log) if "compose up" in call)
    assert pull < up


def test_a_reference_names_its_registry_the_way_docker_reads_one(
    fenced: Callable[..., Captured],
) -> None:
    cases = {
        "example/files-store:1": "docker.io",
        "quay.io/example/thing:1": "quay.io",
        MINIO_PINNED_REF: "public.ecr.aws",
        "ghcr.io/zitadel/zitadel:v4.17.1": "ghcr.io",
        "localhost:5000/thing:1": "localhost:5000",
        "postgres:17": "docker.io",
    }
    body = "".join(f'printf "%s|%s\\n" "{ref}" "$(image_registry_host "{ref}")"\n' for ref in cases)
    out = fenced(body)
    assert out.rc == 0, out.text()
    got = dict(line.rsplit("|", 1) for line in out.text().splitlines() if "|" in line)
    assert got == cases


def test_the_minio_pin_names_the_registry_that_serves_it() -> None:
    compose = (ROOT / "compose.yaml").read_text()
    lines = [line for line in compose.splitlines() if re.search(r"image: .*minio", line)]
    assert len(lines) == 1, lines
    assert MINIO_PINNED_REF in lines[0]
    block = re.search(r"^  minio:\n(?:(?!  [a-z]).*\n)*", compose, re.M)
    assert block and "\n    platform: linux/arm64\n" in block.group(0)
    assert "newest release published to" not in compose


ROLE_GUARD = "vars.AWS_ECR_ROLE_ARN != ''"
#: A step that starts the stack: compose itself, CI's wrapper, or the proof's clone's `setup.sh`.
COMPOSE_UP = r"docker compose\b[^\n]*\bup\b|scripts/ci_stack\.sh up\b|scripts/proof_from_zero\.sh\b"


def runs_step(step: dict[str, Any], prefix: str, up_guard: str | None = None) -> bool:
    """Whether `step` uses `prefix` and runs whenever the up does: guard none, role, up, both."""
    allowed = {None, ROLE_GUARD}
    if up_guard is not None:
        allowed |= {up_guard, f"{up_guard} && {ROLE_GUARD}"}
    return step.get("if") in allowed and str(step.get("uses", "")).startswith(prefix)


def compose_up_jobs(workflow: dict[str, Any], host: str) -> dict[str, tuple[bool, bool]]:
    """Per job that starts the stack: (QEMU arm64 before the up, logged in before the up)."""
    found: dict[str, tuple[bool, bool]] = {}
    for name, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps") or []
        up = next(
            (i for i, s in enumerate(steps) if re.search(COMPOSE_UP, str(s.get("run", "")))), None
        )
        if up is None:
            continue
        before = steps[:up]
        guard = steps[up].get("if")
        qemu = any(
            runs_step(s, "docker/setup-qemu-action@", guard)
            and "arm64" in str((s.get("with") or {}).get("platforms", ""))
            for s in before
        )
        assume = next(
            (
                i
                for i, s in enumerate(before)
                if runs_step(s, "aws-actions/configure-aws-credentials@", guard)
                and (s.get("with") or {}).get("aws-region") == "us-east-1"
                and "vars.AWS_ECR_ROLE_ARN" in str((s.get("with") or {}).get("role-to-assume", ""))
            ),
            None,
        )
        login = next(
            (
                i
                for i, s in enumerate(before)
                if host == "public.ecr.aws"
                and runs_step(s, "aws-actions/amazon-ecr-login@", guard)
                and (s.get("with") or {}).get("registry-type") == "public"
            ),
            None,
        )
        perms = job.get("permissions", workflow.get("permissions")) or {}
        oidc = isinstance(perms, dict) and perms.get("id-token") == "write"
        found[name] = (qemu, login is not None and assume is not None and assume < login and oidc)
    return found


def test_every_compose_up_job_runs_arm64_and_logs_in_before_the_pull() -> None:
    assert_logs_in_before_the_pull("ci.yml", "legs")


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_proof_from_zero_runs_arm64_and_logs_in_before_the_pull() -> None:
    assert_logs_in_before_the_pull("proof-from-zero.yml", "proof")


def assert_logs_in_before_the_pull(flow: str, subject: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / flow).read_text())
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    host = compose["services"]["minio"]["image"].split("/", 1)[0]
    jobs = compose_up_jobs(workflow, host)
    assert subject in jobs, f"no `{subject}` job starts the stack — the census has no subject"
    assert all(qemu for qemu, _ in jobs.values()), jobs
    assert all(logged for _, logged in jobs.values()), jobs
    no_login = copy.deepcopy(workflow)
    for job in (no_login.get("jobs") or {}).values():
        job["steps"] = [
            s
            for s in job.get("steps") or []
            if not str(s.get("uses", "")).startswith("aws-actions/amazon-ecr-login@")
        ]
    planted = compose_up_jobs(no_login, host)
    assert subject in planted and not any(logged for _, logged in planted.values()), planted
    if_false = copy.deepcopy(workflow)
    for job in (if_false.get("jobs") or {}).values():
        for s in job.get("steps") or []:
            if str(s.get("uses", "")).startswith(
                (
                    "aws-actions/amazon-ecr-login@",
                    "aws-actions/configure-aws-credentials@",
                    "docker/setup-qemu-action@",
                )
            ):
                s["if"] = False
    assert compose_up_jobs(if_false, host).get(subject) == (False, False)
    no_oidc = copy.deepcopy(workflow)
    for job in (no_oidc.get("jobs") or {}).values():
        if isinstance(job.get("permissions"), dict):
            job["permissions"].pop("id-token", None)
    no_oidc.pop("permissions", None)
    assert compose_up_jobs(no_oidc, host).get(subject) == (True, False)


def gate_after_login(workflow: dict[str, Any]) -> list[tuple[str, bool]]:
    """Every gate step after an AWS login: (its job, whether it pins the three exports empty)."""
    seen: list[tuple[str, bool]] = []
    for name, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps") or []
        login = next(
            (
                i
                for i, s in enumerate(steps)
                if str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")
            ),
            None,
        )
        if login is None:
            continue
        for s in steps[login + 1 :]:
            if not re.search(r"check\.sh|proof_from_zero\.sh", str(s.get("run", ""))):
                continue
            env = s.get("env") or {}
            pinned = (
                env.get("AWS_ACCESS_KEY_ID") == ""
                and env.get("AWS_SECRET_ACCESS_KEY") == ""
                and env.get("AWS_SESSION_TOKEN", "<inherited>") == ""
            )
            seen.append((name, pinned))
    return seen


def test_the_gate_after_the_login_dials_the_compose_store() -> None:
    assert_gate_after_login_pinned("ci.yml", "legs")


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_proof_after_the_login_dials_the_compose_store() -> None:
    assert_gate_after_login_pinned("proof-from-zero.yml", "proof")


def assert_gate_after_login_pinned(flow: str, subject: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / flow).read_text())
    steps = gate_after_login(workflow)
    assert any(job == subject for job, _ in steps), (
        f"no gate step follows an AWS login in `{subject}`"
    )
    assert all(pinned for _, pinned in steps), steps
    unpinned, via_context = copy.deepcopy(workflow), copy.deepcopy(workflow)
    for job in (unpinned.get("jobs") or {}).values():
        for s in job.get("steps") or []:
            for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                (s.get("env") or {}).pop(key, None)
    for job in (via_context.get("jobs") or {}).values():
        for s in job.get("steps") or []:
            if "AWS_ACCESS_KEY_ID" in (s.get("env") or {}):
                s["env"]["AWS_ACCESS_KEY_ID"] = "${{ env.AWS_ACCESS_KEY_ID }}"
    for planted in (unpinned, via_context):
        found = gate_after_login(planted)
        assert (subject, False) in found and not any(pinned for _, pinned in found), found


@dataclass(frozen=True)
class Source:
    """A scratch repository with `main` and the tag `v0.0.1-drive` on its one commit."""

    repo: Path
    work: Path

    def clone(self, name: str, *how: str) -> Path:
        """`git clone <how> <repo> <work/name>`; `CouldNotLook` when git cannot build it."""
        dest = require_scratch(self.work / name, ROOT)
        done = subprocess.run(
            ["git", "clone", "--quiet", *how, str(self.repo), str(dest)], capture_output=True
        )
        if done.returncode != 0:
            raise CouldNotLook(f"could not clone the scratch repository ({' '.join(how)})")
        return dest

    def advance(self) -> None:
        """Move `main` one commit past the tag."""
        with (self.repo / "README.md").open("a") as readme:
            readme.write("past the tag\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-q", "-m", "one commit past the tag")


@pytest.fixture
def source(scratch: Path) -> Source:
    """A fresh source repository for the tag-clone cases."""
    if shutil.which("git") is None:
        raise CouldNotLook("no git on PATH — the tag-clone cases cannot build a victim")
    repo = require_scratch(scratch / "src", ROOT)
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.email", "drive@example.invalid")
    git(repo, "config", "user.name", "setup env port")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "tag", "v0.0.1-drive")
    return Source(repo, scratch)


TAG_CLONE = ("--branch", "v0.0.1-drive")
SHALLOW_TAG_CLONE = ("--branch", "v0.0.1-drive", "--depth", "1", "--single-branch")


def git_shim(scratch: Path, name: str, failing: str | None = None) -> tuple[Path, Path]:
    """A `git` in front of the real one that logs every call, or refuses one subcommand."""
    real = shutil.which("git")
    assert real
    bin_dir, log = scratch / name, scratch / f"{name}.log"
    bin_dir.mkdir()
    log.write_text("")
    if failing:
        head = (
            f'if [ "$1" = "{failing}" ]; then echo "fatal: planted failure in the drive" >&2; '
            "exit 128; fi\n"
        )
    else:
        head = f"printf '%s\\n' \"$*\" >> '{log}'\n"
    (bin_dir / "git").write_text(f'#!/usr/bin/env bash\n{head}exec "{real}" "$@"\n')
    (bin_dir / "git").chmod(0o755)
    return bin_dir, log


def main_step(fenced: Callable[..., Captured], where: Path, shim: Path | None = None) -> Captured:
    """`ensure_local_main` in `where`, with `shim` first on PATH when given."""
    prefix = f'export PATH="{shim}:$PATH"\n' if shim else ""
    return fenced(f"{prefix}ensure_local_main", cwd=where)


def on_branch(repo: Path) -> str:
    """`refs/heads/<x>` when HEAD is on a branch, else `detached`."""
    done = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"], capture_output=True, text=True
    )
    return done.stdout.strip() if done.returncode == 0 else "detached"


def test_a_tag_clone_gets_main_at_head_and_is_on_it(
    source: Source, fenced: Callable[..., Captured]
) -> None:
    want = git(source.repo, "rev-parse", "v0.0.1-drive^{commit}")
    clone = source.clone("clone", *TAG_CLONE)
    assert git_rc(clone, "rev-parse", "-q", "--verify", "refs/heads/main") != 0
    assert on_branch(clone) == "detached"
    out = main_step(fenced, clone)
    assert out.rc == 0, out.text()
    assert git(clone, "rev-parse", "refs/heads/main") == want
    assert on_branch(clone) == "refs/heads/main"
    short = git(clone, "rev-parse", "--short", "main")
    assert (
        f"main created at {short} (this checkout had no local main — a tag clone; the --loop "
        "scope and the database name derive from it; to move to the tip: git fetch origin main "
        "&& git reset --hard FETCH_HEAD)"
    ) in out.text()


def test_the_printed_remedy_runs_where_the_step_leaves_you(
    source: Source, fenced: Callable[..., Captured], capture: Callable[..., Captured]
) -> None:
    source.advance()
    tip = git(source.repo, "rev-parse", "main")
    tag = git(source.repo, "rev-parse", "v0.0.1-drive^{commit}")
    for shape, how in (("full", TAG_CLONE), ("shallow", SHALLOW_TAG_CLONE)):
        clone = source.clone(f"clone-{shape}", *how)
        out = main_step(fenced, clone)
        assert out.rc == 0, out.text()
        assert on_branch(clone) == "refs/heads/main"
        assert git(clone, "rev-parse", "HEAD") == tag
        remedy = re.search(r"^main created at .*to move to the tip: (.*)\)$", out.text(), re.M)
        assert remedy, f"the {shape} sentence names no follow-up"
        assert "branch -f main" not in remedy.group(1)
        superseded = capture(["git", "branch", "-f", "main", "origin/main"], cwd=clone)
        assert superseded.rc != 0, f"{shape}: the superseded remedy SUCCEEDED"
        assert "fatal:" in superseded.text()
        assert git(clone, "rev-parse", "main") == tag
        if shape == "shallow":
            assert git_rc(clone, "rev-parse", "--verify", "origin/main") != 0
        ran = capture(["bash", "-c", remedy.group(1)], cwd=clone)
        assert ran.rc == 0, f"{shape}: {remedy.group(1)}"
        assert git(clone, "rev-parse", "main") == tip
        assert on_branch(clone) == "refs/heads/main"


def test_a_clone_with_main_is_untouched(
    source: Source, scratch: Path, fenced: Callable[..., Captured]
) -> None:
    clone = source.clone("clone", "--branch", "main")
    shim, log = git_shim(scratch, "bin-log")
    out = main_step(fenced, clone, shim)
    assert out.rc == 0
    assert out.path.stat().st_size == 0, out.path.read_text()
    calls = log.read_text().splitlines()
    assert calls, "the shim logged NOTHING — it was not on PATH"
    assert not [call for call in calls if re.match(r"(branch|switch) ", call)], calls


def test_a_linked_worktree_of_a_repository_holding_main_is_untouched(
    source: Source, scratch: Path, fenced: Callable[..., Captured]
) -> None:
    worktree = require_scratch(scratch / "wt", ROOT)
    if git_rc(source.repo, "worktree", "add", "--detach", str(worktree), "HEAD") != 0:
        raise CouldNotLook("could not add a linked worktree to the scratch repository")
    shim, log = git_shim(scratch, "bin-log")
    out = main_step(fenced, worktree, shim)
    assert out.rc == 0
    assert out.path.stat().st_size == 0, out.path.read_text()
    calls = log.read_text().splitlines()
    assert calls, "the shim logged NOTHING — it was not on PATH"
    assert not [call for call in calls if re.match(r"(branch|switch) ", call)], calls
    assert on_branch(worktree) == "detached"


def test_an_unborn_head_prints_and_skips(scratch: Path, fenced: Callable[..., Captured]) -> None:
    empty = require_scratch(scratch / "empty", ROOT)
    empty.mkdir()
    git(empty, "init", "-q")
    git(empty, "symbolic-ref", "HEAD", "refs/heads/main")
    out = main_step(fenced, empty)
    assert out.rc == 0, out.text()
    assert "no commit to place main on — skipping" in out.text()
    assert git_rc(empty, "rev-parse", "-q", "--verify", "refs/heads/main") != 0


def test_a_failing_git_is_exit_2_naming_the_command(
    source: Source, scratch: Path, fenced: Callable[..., Captured]
) -> None:
    clone = source.clone("clone", *TAG_CLONE)
    shim, _ = git_shim(scratch, "bin-fail", failing="branch")
    out = main_step(fenced, clone, shim)
    assert out.rc == 2, out.text()
    assert "git branch main HEAD` failed" in out.text()
    assert git_rc(clone, "rev-parse", "-q", "--verify", "refs/heads/main") != 0


# deleted: test_the_loop_scope_refusal_is_what_a_tag_clone_hits_without_the_step — loop_tier.sh died
# pin: quality/tests/test_scope.py::test_an_absent_local_main_is_a_refusal_not_a_thin_basis


def test_every_step_prints_its_wall_and_the_run_its_total(
    fenced: Callable[..., Captured], prelude: Path
) -> None:
    wall = prelude.parent / "step-wall.sh"
    out = fenced(f'. "{wall}"\nstep "alpha"\nstep "beta"\nsetup_total')
    text = out.text()
    assert out.rc == 0, text
    walls = re.findall(r"^  \([a-z]+: [0-9]+\.[0-9]+s\)$", text, re.M)
    assert len(walls) == 2, walls
    assert re.search(r"^  \(alpha: ", text, re.M) and re.search(r"^  \(beta: ", text, re.M)
    assert re.search(r"^setup: total [0-9]+\.[0-9]+s$", text, re.M)
    assert len(re.findall(r"^  \(beta: ", text, re.M)) == 1


def test_the_clock_and_the_steps_have_one_home_each(prelude: Path) -> None:
    def homes(pattern: str) -> list[str]:
        return sorted(
            f"scripts/{path.name}"
            for path in (ROOT / "scripts").glob("*.sh")
            if re.search(pattern, path.read_text(errors="replace"), re.M)
        )

    assert homes(r"^(now_ms|clock_ms|fmt_ms|clock_fmt)\(\) \{") == ["scripts/gate_refuse.sh"]
    assert homes(r"^(step|step_begin|step_end|step_close)\(\) \{") == ["scripts/steps.sh"]
    assert "scripts/steps.sh" in (prelude.parent / "step-wall.sh").read_text()


def test_ensure_local_main_precedes_the_environment_step() -> None:
    banner = line_of(SETUP, re.escape('step "local main"'))
    call = line_of(SETUP, r"^ensure_local_main$")
    env_line = line_of(SETUP, re.escape('step "environment file"'))
    assert banner and call and env_line and banner < call < env_line, (banner, call, env_line)
    assert line_of(SETUP, r'^step "') == banner


def test_the_total_is_the_last_thing_the_script_prints() -> None:
    lines = SETUP.read_text().splitlines()
    start = lines.index("setup_total")
    tail = [re.sub(r"#.*$", "", line) for line in lines[start:]]
    tail = [line for line in tail if line.strip()]
    assert len(tail) == 2 and "setup_total" in tail and "exit 1" in "\n".join(tail), tail


def test_the_readme_quickstart_matches_what_setup_runs() -> None:
    readme = (ROOT / "README.md").read_text()
    section = re.search(
        r"^## Quickstart, from a fresh clone\n(.*?)(?=^## |\Z)", readme, re.M | re.S
    )
    assert section, "README.md has no '## Quickstart, from a fresh clone' section"
    block = re.search(r"^```bash\n(.*?)^```$", section.group(1), re.M | re.S)
    assert block, "the quickstart has no bash command block"
    commands = [line.split(" ", 1)[0] for line in block.group(1).splitlines()]
    absent = [
        c for c in commands if c.startswith("./scripts/") and not os.access(ROOT / c[2:], os.X_OK)
    ]
    assert not absent, absent
    steps = set(re.findall(r'^step "([^"]*)"$', SETUP.read_text(), re.M))
    named = re.findall(r"`([a-z][a-z ]+)` step", section.group(1))
    assert named, "the quickstart names no setup step by its printed name"
    assert not [name for name in named if name not in steps], named
    assert re.search(r"Node.*pnpm|pnpm.*Node", section.group(1), re.S)


def _order(text: str, needles: tuple[str, ...]) -> list[int]:
    """Where each needle first appears in `text`, by line; -1 for a needle it never names."""
    lines = text.splitlines()
    return [next((i for i, line in enumerate(lines) if n in line), -1) for n in needles]


def test_the_readme_quickstart_declares_where_day_zero_does() -> None:
    readme = (ROOT / "README.md").read_text()
    section = re.search(
        r"^## Quickstart, from a fresh clone\n(.*?)(?=^## |\Z)", readme, re.M | re.S
    )
    assert section
    block = re.search(r"^```bash\n(.*?)^```$", section.group(1), re.M | re.S)
    assert block
    quick = _order(block.group(1), ("./scripts/setup.sh", "manage.py declare", "./scripts/test.sh"))
    day = _order(
        (ROOT / "docs/sdk/day-zero.md").read_text(),
        ("`./scripts/setup.sh`", "manage.py declare", "./scripts/check.sh"),
    )
    assert -1 not in quick and quick == sorted(quick), ("README", quick)
    assert -1 not in day and day == sorted(day), ("day-zero", day)


def test_the_step_calls_services_up() -> None:
    step_line = line_of(SETUP, re.escape('step "services"'))
    call_line = line_of(SETUP, r"^services_up$")
    assert step_line and call_line and call_line > step_line, (step_line, call_line)
    fence_line = line_of(SETUP, r"^# >>> services >>>")
    organs = line_of(SETUP, r'^[ \t]+ci_stack_organs "\$\{SERVICES\[@\]\}"')
    assert fence_line and organs and organs > fence_line, (fence_line, organs)
    assert line_of(SETUP, r"^[ \t]*docker compose up") is None


def test_the_step_calls_the_function() -> None:
    step_line = line_of(SETUP, re.escape('step "environment file"'))
    call_line = line_of(SETUP, r"^env_sync_from_example$")
    chmod_line = line_of(SETUP, r"^chmod 600 \.env$")
    assert step_line and call_line and chmod_line, (step_line, call_line, chmod_line)
    assert step_line < call_line < chmod_line


def test_the_superseded_sentence_is_gone() -> None:
    assert "already present, leaving it alone" not in SETUP.read_text()


def test_the_previous_file_is_ignored_by_git() -> None:
    assert git_rc(ROOT, "check-ignore", "-q", ".env.previous") == 0
