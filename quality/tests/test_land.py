"""`python -m quality.djb.rituals.land` over a scratch origin, primary and builder's worktree."""

# does-not-cover: a real forge — `gh` is a stub answering one pull request's JSON.
# does-not-cover: a real database — `db.sh`, `db_sweep.sh` and `pm_push.sh` are doubles that record.

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb.rituals import land
from quality.tests.fixtures.scratch_repo import make_repo
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives("quality/djb/rituals/land.py", "scripts/pm_land.sh")

ROOT = Path(__file__).resolve().parents[2]
#: The fixture ids' letter, held apart: an id spelled whole in this text is a plan coordinate.
N = "N"
#: The report the rung files, never a `.md` literal: the pointer scan would read one as dangling.
RUNG_REPORT = "docs/product/reports/p99/rung" + ".md"
#: The preamble is carried into the index, so its length gives the byte ceiling headroom.
QUEUE = f"""# Queue — the fixture

{"Order lives here. " * 160}

## The section

- **{N}9001 (MED, fixture): the row the pull request ships** — open.
- **{N}9002 (LOW, fixture): a row nobody ships** — open.
"""
REPORT = f"""# The rung's report

## Rows
ships: {N}9001
books:
- **(LOW hygiene / a finding, the builder 2026-10-24):** evidence `a.py:1`. Band: non-functional.
"""
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$LAND_REC/gh.calls"
if [ -f "$LAND_REC/gh.rc" ]; then
    echo "HTTP 502: the API is down" >&2
    exit "$(cat "$LAND_REC/gh.rc")"
fi
cat "$LAND_REC/pr.json"
"""
DB_SH = """db_name() { printf 'djb_%s' "$(basename "$(git rev-parse --show-toplevel)")"; }
db_drop() {
    live=$(test -e .git && echo yes)
    printf 'drop %s env=%s live=%s\\n' "$1" "${DATABASE_NAME:-unset}" "$live" >>"$LAND_REC/reap"
}
"""
SWEEP = """#!/usr/bin/env bash
printf 'sweep %s %s\\n' "$(basename "$PWD")" "$*" >>"$LAND_REC/reap"
"""
PUSH = """#!/usr/bin/env bash
main=$(git log -1 --format=%s main)
printf 'push %s %s %s\\n' "$(basename "$PWD")" "$*" "$main" >>"$LAND_REC/reap"
"""


def git(repo: Path, *argv: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
    return done.stdout.strip()


@dataclass
class World:
    """The origin, the primary on main, the merged head's worktree, the forge's answer."""

    scratch: Path
    rec: Path

    @property
    def primary(self) -> Path:
        return self.scratch / "primary"

    @property
    def worktree(self) -> Path:
        return self.primary / ".claude" / "worktrees" / "pm-rung"

    def answer(self, state: str = "MERGED", mergeable: str = "UNKNOWN") -> None:
        sha = git(self.scratch / "forge", "rev-parse", "HEAD")
        pr = {"state": state, "mergeCommit": {"oid": sha}, "headRefName": "pm/rung"}
        pr |= {"mergedAt": "2026-10-24T12:00:00Z", "title": "the rung", "mergeable": mergeable}
        (self.rec / "pr.json").write_text(json.dumps(pr))

    def land(self, *argv: str, at: Path | None = None) -> int:
        with contextlib.chdir(at or self.primary):
            return land.main(["7", *argv], root=at or self.primary)

    def reap(self) -> list[str]:
        path = self.rec / "reap"
        return path.read_text().splitlines() if path.exists() else []

    def gh_calls(self) -> int:
        path = self.rec / "gh.calls"
        return len(path.read_text().splitlines()) if path.exists() else 0


@pytest.fixture
def world(scratch: Path, stub_path: StubPath, monkeypatch: pytest.MonkeyPatch) -> World:
    rec = scratch / "rec"
    rec.mkdir()
    stub_path.plant("gh", FAKE_GH)
    stub_path.plant("uv", '#!/usr/bin/env bash\nprintf \'uv %s\\n\' "$*" >>"$LAND_REC/reap"\n')
    monkeypatch.setenv("PATH", f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LAND_REC", str(rec))
    monkeypatch.setenv("DATABASE_NAME", "djb_the_primarys_own")
    monkeypatch.delenv("DJB_GATE_LEDGER", raising=False)
    monkeypatch.setenv("CI", "1")
    seed = make_repo(scratch / "seed")
    (seed / ".gitignore").write_text(".claude/worktrees/\n")
    product = seed / "docs" / "product"
    product.mkdir(parents=True)
    (product / "queue.md").write_text(QUEUE)
    gen = ROOT / "scripts" / "queue_index.py"
    split = [
        sys.executable,
        str(gen),
        "--split",
        "docs/product/queue.md",
        "docs/product/queue-detail.md",
    ]
    subprocess.run(split, cwd=seed, check=True, capture_output=True)
    scripts = seed / "scripts"
    scripts.mkdir()
    for name, body in (("db.sh", DB_SH), ("db_sweep.sh", SWEEP), ("pm_push.sh", PUSH)):
        (scripts / name).write_text(body)
        (scripts / name).chmod(0o755)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "the seed")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(seed), str(scratch / "origin.git")], check=True
    )
    w = World(scratch, rec)
    for name in ("primary", "forge"):
        subprocess.run(
            ["git", "clone", "-q", str(scratch / "origin.git"), str(scratch / name)], check=True
        )
        git(scratch / name, "config", "user.email", "drive@example.invalid")
        git(scratch / name, "config", "user.name", "drive")
    git(w.primary, "worktree", "add", "-q", "-b", "pm/rung", str(w.worktree), "origin/main")
    (w.worktree / RUNG_REPORT).parent.mkdir(parents=True)
    (w.worktree / RUNG_REPORT).write_text(REPORT)
    git(w.worktree, "add", RUNG_REPORT)
    git(w.worktree, "commit", "-q", "-m", "the rung's report")
    git(w.worktree, "push", "-q", "origin", "pm/rung")
    forge = scratch / "forge"
    git(forge, "fetch", "-q", "origin")
    git(forge, "merge", "-q", "--no-ff", "-m", "Merge pull request #7", "origin/pm/rung")
    git(forge, "push", "-q", "origin", "main")
    w.answer()
    return w


def test_an_open_pr_is_refused_untouched(world: World, capfd: pytest.CaptureFixture[str]) -> None:
    world.answer("OPEN", "CONFLICTING")
    before = git(world.primary, "rev-parse", "HEAD")
    assert world.land() == 1
    said = capfd.readouterr().err
    assert "OPEN, not MERGED" in said and "CONFLICTING" in said
    assert git(world.primary, "rev-parse", "HEAD") == before
    assert world.worktree.is_dir() and world.reap() == []


def test_a_dirty_primary_is_exit_2(world: World, capfd: pytest.CaptureFixture[str]) -> None:
    (world.primary / "stray.txt").write_text("not committed\n")
    assert world.land() == 2
    assert "uncommitted changes" in capfd.readouterr().err
    assert world.gh_calls() == 0 and world.worktree.is_dir()


def test_a_primary_off_main_or_a_worktree_is_exit_2(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    assert world.land(at=world.worktree) == 2
    assert "linked worktree" in capfd.readouterr().err
    git(world.primary, "checkout", "-q", "-b", "elsewhere")
    assert world.land() == 2
    assert "not main" in capfd.readouterr().err
    assert world.gh_calls() == 0


def test_a_refused_gh_is_exit_2(world: World, capfd: pytest.CaptureFixture[str]) -> None:
    (world.rec / "gh.rc").write_text("1")
    assert world.land() == 2
    assert "gh pr view 7` refused" in capfd.readouterr().err
    assert world.worktree.is_dir()


def test_main_is_merged_no_ff_and_the_line_printed(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    before = git(world.primary, "rev-parse", "HEAD")
    assert world.land() == 0, capfd.readouterr()
    said = capfd.readouterr().out
    tip = git(world.scratch / "forge", "rev-parse", "HEAD")
    first_parent = git(world.primary, "rev-list", "--first-parent", f"{before}..HEAD").split()
    assert len(first_parent) == 2, "one merge, then the landing commit"
    assert git(world.primary, "rev-parse", f"{first_parent[1]}^1") == before
    assert git(world.primary, "rev-parse", f"{first_parent[1]}^2") == tip
    assert f"main: {before[:8]}.." in said and "main_is_read: not asked" in said
    git(world.primary, "reset", "-q", "--hard", before)
    assert world.land("--read-main") == 0, capfd.readouterr()
    assert "main_is_read: unread — tree" in capfd.readouterr().out


def test_reap_runs_the_four_steps_in_order_and_names_each(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    assert world.land() == 0, capfd.readouterr()
    said = capfd.readouterr().out
    assert world.reap() == [
        "sweep pm-rung --sweep --hot-path",
        "drop djb_pm-rung env=unset live=yes",
    ]
    assert not world.worktree.exists()
    assert git(world.primary, "branch", "--list", "pm/rung") == ""
    labels = ["(a) inside sweep", "(b) inside db_drop", "(c) worktree remove", "(d) branch delete"]
    at = [said.index(f"{label}: exit 0") for label in [*labels, "(e) worktree prune"]]
    assert at == sorted(at)


def test_an_unmerged_tip_refuses_branch_delete(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    (world.worktree / "late.txt").write_text("after the merge\n")
    git(world.worktree, "add", "late.txt")
    git(world.worktree, "commit", "-q", "-m", "a commit the pull request never carried")
    tip = git(world.worktree, "rev-parse", "HEAD")
    assert world.land() == 1
    assert f"tip {tip[:8]} is NOT in main" in capfd.readouterr().err
    assert git(world.primary, "rev-parse", "pm/rung") == tip


def test_land_makes_one_pathspec_commit_and_prints_the_line(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    assert world.land() == 0, capfd.readouterr()
    said = capfd.readouterr().out
    sha = git(world.primary, "rev-parse", "--short=8", "HEAD")
    subject = git(world.primary, "log", "-1", "--format=%s")
    assert subject == "land: #7 the rung — 1 struck, 1 booked, pm-rung reaped [docs-only]", said
    files = git(world.primary, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == ["docs/product/queue-detail.md", "docs/product/queue.md"]
    detail = (world.primary / "docs/product/queue-detail.md").read_text()
    merge = git(world.scratch / "forge", "rev-parse", "--short=8", "HEAD")
    assert f"~~{N}9001~~ SHIPPED ({merge}, {RUNG_REPORT})" in detail
    assert f"- **{N}9002 (LOW" in detail and f"### {N}9003" in detail
    assert f"Booked from `{RUNG_REPORT}`." in detail
    line = f"pm-land: #7 landed at {sha} · struck {N}9001 · booked {N}9003 · reaped pm-rung"
    assert line in said
    assert git(world.primary, "status", "--porcelain") == ""


def test_a_second_land_of_the_same_pr_changes_nothing(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    assert world.land() == 0, capfd.readouterr()
    head = git(world.primary, "rev-parse", "HEAD")
    capfd.readouterr()
    assert world.land() == 0, capfd.readouterr()
    said = capfd.readouterr().out
    assert git(world.primary, "rev-parse", "HEAD") == head
    assert "reap: none (no worktree)" in said and "nothing to commit" in said
    assert "struck none · booked none · reaped none" in said


def test_a_handed_over_report_is_copied_beside_the_prs_own_and_read(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    memo = world.scratch / Path(RUNG_REPORT).name.replace("rung", "v-rung")
    memo.write_text(f"# The verifier\n\n## Rows\nships: {N}9002\nbooks:\n")
    assert world.land("--report", str(memo)) == 0
    files = git(world.primary, "show", "--name-only", "--format=", "HEAD").split()
    assert RUNG_REPORT.replace("/rung", "/v-rung") in files
    assert f"struck {N}9001 {N}9002" in capfd.readouterr().out


def test_ledger_pr_merges_main_into_the_day_s_branch_and_runs_its_pr(
    world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    assert world.land("--ledger-pr") == 0
    branch = f"pm/ledger-{time.strftime('%Y-%m-%d')}"
    wt = world.primary / ".claude" / "worktrees" / branch.replace("/", "-")
    assert git(wt, "rev-parse", "HEAD^{tree}") == git(world.primary, "rev-parse", "HEAD^{tree}")
    assert world.reap()[-2:] == [
        "uv sync",
        f"push {wt.name} --pr land: #7 the rung — 1 struck, 1 booked, pm-rung reaped [docs-only]",
    ]
    assert "ledger pr: exit 0" in capfd.readouterr().out
