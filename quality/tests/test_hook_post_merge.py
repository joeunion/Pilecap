"""`scripts/githooks/post-merge`: a fast-forward pull and a merge the developer made, told apart."""

# does-not-cover: `check.sh` itself — the hook runs a stub whose one leg is the real `db_pin_leg`.
# does-not-cover: `git pull --rebase`, which does not leave ORIG_HEAD the way a merge does.
# does-not-cover: a squash merge (`$1` is 1) — the hook reads the commit graph, never `$1`.

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from quality.tests.fixtures.scratch_repo import make_repo

pytestmark = pytest.mark.drives(
    "scripts/githooks/post-merge", "scripts/db.sh", "scripts/gate_refuse.sh"
)

ROOT = Path(__file__).resolve().parents[2]
#: A gate whose one leg is the real db-pin leg, banner as `quality/djb/legs/db_pin.py` prints it.
STUB_GATE = (
    "#!/usr/bin/env bash\n"
    'echo "- DATABASE_NAME: this checkout\'s .env pin vs the derivation"\n'
    ". scripts/db.sh 2>/dev/null\n"
    "db_pin_leg fast\n"
)
WALL = "Fix forward, or reset"
UNSET = ("DATABASE_NAME", "DATABASE_NAME_SOURCE", "DJANGO_SETTINGS_MODULE", "GIT_DIR")


def git(repo: Path, *argv: str) -> str:
    """One git command in `repo`, its stdout; a failure raises."""
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(repo: Path, name: str) -> None:
    """One file, one commit."""
    (repo / name).write_text(f"{name}\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def upstream(scratch: Path) -> Path:
    """A repository carrying the hook, db.sh, the refusal seam and the stub gate."""
    repo = make_repo(scratch / "upstream")
    (repo / "scripts" / "githooks").mkdir(parents=True)
    for name in ("db.sh", "gate_refuse.sh", "githooks/post-merge"):
        shutil.copyfile(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "scripts" / "check.sh").write_text(STUB_GATE)
    (repo / "scripts" / "check.sh").chmod(0o755)
    (repo / ".gitignore").write_text(".env\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the hook and its gate")
    return repo


def developer(upstream: Path, scratch: Path, name: str) -> Path:
    """A clone of `upstream` with the hook installed and a `.env` pin that disagrees."""
    clone = scratch / name
    git(scratch, "clone", "-q", str(upstream), str(clone))
    for key, value in (("user.email", "dev@example.invalid"), ("user.name", "dev")):
        git(clone, "config", key, value)
    hook = clone / ".git" / "hooks" / "post-merge"
    shutil.copyfile(clone / "scripts" / "githooks" / "post-merge", hook)
    hook.chmod(0o755)
    (clone / ".env").write_text("DATABASE_NAME=djb_left_behind_by_another_branch\n")
    return clone


def hooked(clone: Path, *argv: str) -> str:
    """`git <argv>` in `clone`, the hook's output and git's interleaved."""
    env = {k: v for k, v in os.environ.items() if k not in UNSET}
    done = subprocess.run(["git", "-C", str(clone), *argv], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout + done.stderr


def test_a_fast_forward_pull_prints_the_one_pin_line(upstream: Path, scratch: Path) -> None:
    clone = developer(upstream, scratch, "pulled")
    git(upstream, "checkout", "-q", "-b", "side")
    commit(upstream, "side")
    git(upstream, "checkout", "-q", "main")
    commit(upstream, "main")
    git(upstream, "merge", "-q", "--no-ff", "side", "-m", "a pull request's merge")
    out = hooked(clone, "pull", "-q", "--ff-only")
    assert WALL not in out, out
    said = [line for line in out.splitlines() if line.startswith("post-merge: a fast-forward")]
    assert len(said) == 1, out
    assert "this checkout's .env and its derivation DISAGREE" in said[0], out
    assert "./scripts/setup.sh" in said[0], out
    assert "full output:" not in out, out


def test_a_lone_developers_fast_forward_pull_prints_the_one_pin_line(
    upstream: Path, scratch: Path
) -> None:
    clone = developer(upstream, scratch, "alone")
    git(upstream, "checkout", "-q", "-b", "side")
    commit(upstream, "side")
    git(upstream, "checkout", "-q", "main")
    git(upstream, "merge", "-q", "--no-ff", "side", "-m", "a pull request's merge")
    assert git(upstream, "rev-parse", "HEAD^1") == git(clone, "rev-parse", "HEAD")
    out = hooked(clone, "pull", "-q", "--ff-only")
    assert WALL not in out, out
    said = [line for line in out.splitlines() if line.startswith("post-merge: a fast-forward")]
    assert len(said) == 1, out
    assert "./scripts/setup.sh" in said[0], out


def test_a_merge_the_developer_made_keeps_the_wall(upstream: Path, scratch: Path) -> None:
    clone = developer(upstream, scratch, "merged")
    git(clone, "checkout", "-q", "-b", "feature")
    commit(clone, "feature")
    git(clone, "checkout", "-q", "main")
    commit(clone, "local")
    out = hooked(clone, "merge", "-q", "--no-ff", "feature", "-m", "my merge")
    assert WALL in out, out
    assert "post-merge: a fast-forward" not in out, out
    assert "DISAGREE" in out, out
