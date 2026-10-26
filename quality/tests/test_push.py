"""`python -m quality.djb.rituals.push` over scratch worlds: a repository, its origin, its stubs."""

# does-not-cover: a real forge — the origin is a scratch bare repository and `gh` is a stub.
# does-not-cover: `check.sh` and `pm_fold.sh` — each is a stub whose record is the proof.

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb import ledger
from quality.djb.box import bank as box_bank
from quality.djb.rituals import push
from quality.djb.rituals.verify_start import Died
from quality.tests.fixtures.capture import run_to
from quality.tests.fixtures.scratch_repo import make_repo
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/push.py",
    "quality/djb/rituals/push_boxes.py",
    "quality/djb/box/bank.py",
    "quality/djb/ledger.py",
    "quality/djb/cli.py",
    "scripts/githooks/pre-push",
    "scripts/pm_push.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ZERO = "0" * 40
#: The stub gate: every argv a line in `rec/gate.calls`; a bare call is an empty line.
STUB_GATE = """#!/usr/bin/env bash
FULL_LEGS=__LEGS__
printf '%s\\n' "$*" >>"__REC__/gate.calls"
if [ "${1:-}" = "--list-legs" ]; then cat "__REC__/listlegs.out"; exit 0; fi
echo "STUB GATE ran with: $*"
exit "${DJB_DRIVE_GATE_RC:-0}"
"""
#: The stub fold: `rec/fold.rc` is its exit, `rec/fold.dirt` a file it leaves untracked.
STUB_FOLD = """#!/usr/bin/env bash
printf 'ran\\n' >>"__REC__/fold.calls"
echo "STUB FOLD ran"
if [ -f "__REC__/fold.dirt" ]; then cp "__REC__/fold.dirt" ./fold-left-this.txt; fi
if [ -f "__REC__/fold.rc" ]; then exit "$(cat "__REC__/fold.rc")"; fi
echo "pm_fold: NOTHING TO FOLD. No commit was made."
exit 0
"""
#: The drive's FAKE `gh`: every argv recorded, every answer from a fixture under `__GH__`.
FAKE_GH = """#!/usr/bin/env bash
GH="__GH__"
printf '%s\\n' "$*" >>"$GH/calls"
case "${1:-} ${2:-}" in
"run list")
    if [ -f "$GH/list.rc" ]; then
        echo "HTTP 502: the API is down" >&2
        exit "$(cat "$GH/list.rc")"
    fi
    cat "$GH/list.out" 2>/dev/null
    exit 0
    ;;
"run view")
    [ -f "$GH/view-$3" ] || {
        echo "could not find any workflow run with ID $3" >&2
        exit 1
    }
    cat "$GH/view-$3"
    exit 0
    ;;
"run download")
    id=$3
    shift 3
    name="" dir=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --name) name=$2; shift ;;
        --dir) dir=$2; shift ;;
        esac
        shift
    done
    if [ -f "$GH/download-$id.rc" ]; then
        echo "HTTP 500: the artifact store failed" >&2
        exit "$(cat "$GH/download-$id.rc")"
    fi
    [ -d "$GH/art-$id/$name" ] || {
        echo "no valid artifacts found to download" >&2
        exit 1
    }
    mkdir -p "$dir"
    cp "$GH/art-$id/$name/"* "$dir/"
    exit 0
    ;;
"pr list")
    state=$(cat "$GH/pr.state" 2>/dev/null || echo OPEN)
    case " $* " in *" --state open "*) [ "$state" = OPEN ] || exit 0 ;; esac
    [ ! -f "$GH/pr.out" ] || cat "$GH/pr.out"
    exit 0
    ;;
"pr view")
    state=$(cat "$GH/pr.state" 2>/dev/null || echo OPEN)
    case " $* " in *" state,mergeCommit "*)
        echo "$state $(cat "$GH/merge.out" 2>/dev/null)"
        exit 0
        ;;
    *" statusCheckRollup "*)
        cat "$GH/rollup.out" 2>/dev/null
        exit 0
        ;;
    esac
    armed=true
    [ "$state" = OPEN ] && [ ! -f "$GH/pr.unarmed" ] || armed=false
    echo "$state $armed $(cat "$GH/pr.status" 2>/dev/null || echo CLEAN)"
    exit 0
    ;;
"pr create")
    [ ! -f "$GH/create.rc" ] || { echo "GraphQL: the forge refused" >&2; exit 1; }
    echo "7 https://github.com/o/r/pull/7" >"$GH/pr.out"
    rm -f "$GH/pr.state"
    echo "https://github.com/o/r/pull/7"
    exit 0
    ;;
"pr merge")
    [ ! -f "$GH/merge.rc" ] || { echo "GraphQL: auto-merge is not allowed" >&2; exit 1; }
    [ ! -f "$GH/merge.now" ] || echo MERGED >"$GH/pr.state"
    [ ! -f "$GH/merge.unarmed" ] || : >"$GH/pr.unarmed"
    exit 0
    ;;
"repo view")
    cat "$GH/repo.out" 2>/dev/null || echo o/r
    exit 0
    ;;
"api "*)
    [ ! -f "$GH/api.rc" ] || { echo "HTTP 403: API rate limit exceeded" >&2; exit 1; }
    case "$2" in
    */rules/branches/*) cat "$GH/rules.out" 2>/dev/null || echo '[]'; exit 0 ;;
    */pulls) cat "$GH/pulls.out" 2>/dev/null; exit 0 ;;
    */pulls/*/commits*) cat "$GH/pr-commits.out" 2>/dev/null; exit 0 ;;
    *head_sha=*)
        [ -f "$GH/runs-${2##*head_sha=}.out" ] || exit 0
        while read -r id; do
            st=$(cut -d' ' -f1 "$GH/view-$id" 2>/dev/null)
            case "$2" in
            *status=completed*) [ -z "$st" ] || [ "$st" = completed ] || continue ;;
            esac
            case " $* " in
            *pull_requests*) echo "$id $(cat "$GH/prs-$id" 2>/dev/null)" ;;
            *) echo "$id" ;;
            esac
        done <"$GH/runs-${2##*head_sha=}.out"
        exit 0
        ;;
    esac
    ;;
esac
echo "fake gh: no fixture for: $*" >&2
exit 1
"""
#: `gh api repos/<r>/rules/branches/main`: the platform ruleset's four rules, transcribed.
RULES_REQUIRED = """[{"type":"deletion","ruleset_source_type":"Repository","ruleset_id":1},\
{"type":"non_fast_forward","ruleset_source_type":"Repository","ruleset_id":1},\
{"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":true,\
"do_not_enforce_on_create":false,"required_status_checks":[{"context":"verdict"},\
{"context":"gate-verdict"}]},"ruleset_source_type":"Repository","ruleset_id":1},\
{"type":"pull_request","parameters":{"required_approving_review_count":0},\
"ruleset_source_type":"Repository","ruleset_id":1}]
"""
#: A `git` that refuses `write-tree` and is the real git for everything else.
STUB_GIT_NO_TREE = """#!/usr/bin/env bash
case " $* " in *" write-tree "*) echo "stub git: write-tree refused" >&2; exit 128 ;; esac
exec __GIT__ "$@"
"""


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True
    ).stdout.strip()


def count_lines(path: Path) -> int:
    """The non-blank lines of `path`, 0 when absent."""
    return sum(1 for line in path.read_text().splitlines() if line) if path.exists() else 0


@dataclass
class World:
    """`cv_world`: a repository on `pm/train` one commit past `main`, `main` on a bare origin."""

    root: Path
    stubs: StubPath
    out: str = ""
    rc: int = 0
    runs: int = 0

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def origin(self) -> Path:
        return self.root / "origin.git"

    @property
    def rec(self) -> Path:
        return self.root / "rec"

    @property
    def ledger(self) -> Path:
        return self.root / "verdicts"

    @property
    def pm_push(self) -> Path:
        return self.root / "pm-push"

    @property
    def gh(self) -> Path:
        return self.rec / "gh"

    @classmethod
    def make(cls, root: Path, stubs: StubPath, plan: Plan) -> World:
        world = cls(root, stubs)
        repo, rec = world.repo, world.rec
        make_repo(repo, "pm-push-drive")
        for d in (rec, root / "tmp", root / "lease", repo / "scripts" / "githooks"):
            d.mkdir(parents=True)
        for lib in ("gate_ledger.sh", "gate_refuse.sh"):
            shutil.copy2(ROOT / "scripts" / lib, repo / "scripts" / lib)
        hook = repo / "scripts" / "githooks" / "pre-push"
        shutil.copy2(ROOT / "scripts" / "githooks" / "pre-push", hook)
        world.executable(repo / "scripts" / "check.sh", STUB_GATE.replace("__LEGS__", plan.legs))
        (rec / "listlegs.out").write_text(plan.listing)
        world.gh.mkdir()
        (world.gh / "rules.out").write_text(RULES_REQUIRED)
        world.executable(repo / "scripts" / "pm_fold.sh", STUB_FOLD)
        for package in ("quality", "apps"):
            (repo / package).symlink_to(ROOT / package)
        (repo / ".git" / "info" / "exclude").write_text("/quality\n/apps\n__pycache__/\n")
        (repo / "shared.txt").write_text("one\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "main")
        _git(repo, "worktree", "add", "-q", "--detach", str(world.pm_push))
        for package in ("quality", "apps"):
            (world.pm_push / package).symlink_to(ROOT / package)
        _git(root, "init", "-q", "--bare", str(world.origin))
        _git(world.origin, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(repo, "remote", "add", "origin", str(world.origin))
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "switch", "-q", "-c", "pm/train")
        (repo / "train.txt").write_text("train\n")
        _git(repo, "add", "train.txt")
        _git(repo, "commit", "-q", "-m", "the train")
        stubs.plant("gh", FAKE_GH.replace("__GH__", str(world.gh)))
        return world

    def executable(self, path: Path, text: str) -> None:
        path.write_text(text.replace("__REC__", str(self.rec)))
        path.chmod(0o755)

    def wire_hook(self) -> None:
        """The world's pushes now run the real pre-push hook over the stub gate."""
        _git(self.repo, "config", "core.hooksPath", "scripts/githooks")

    def env(self, **extra: str) -> dict[str, str]:
        drop = ("GIT_", "DJB_GATE_", "DJB_PUSH", "DJB_LOOP_", "PYTHON")
        env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
        env.update(
            DJB_GATE_LEDGER=str(self.ledger),
            TMPDIR=str(self.root / "tmp"),
            DJB_GATE_LEASE_DIR=str(self.root / "lease"),
            PATH=self.stubs.path,
        )
        env.update(extra)
        return env

    def run(self, *argv: str, at: Path | None = None, **extra: str) -> int:
        """`pm_push <argv>` as the module, in the repository or `at`: its exit, its output kept."""
        self.runs += 1
        sink = self.root / f"push-{self.runs}.log"
        argv_ = [sys.executable, "-m", "quality.djb.rituals.push", *argv]
        done = run_to(sink, argv_, at or self.repo, self.env(**extra))
        self.rc, self.out = done.rc, sink.read_text(errors="replace")
        return self.rc

    def hook(self, refs: str, **extra: str) -> str:
        """The pre-push hook as git calls it: two arguments, the refs on stdin."""
        return self.hook_at(self.repo, refs, **extra)

    def hook_at(self, where: Path, refs: str, **extra: str) -> str:
        """The pre-push hook in the checkout `where`, as git calls it there."""
        done = subprocess.run(
            ["./scripts/githooks/pre-push", "origin", str(self.origin)],
            cwd=where,
            input=refs,
            capture_output=True,
            text=True,
            env=self.env(**extra),
            check=False,
        )
        return done.stdout + done.stderr

    def head(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD")

    def tree(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD^{tree}")

    def origin_ref(self, ref: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.origin), "rev-parse", "-q", "--verify", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.stdout.strip() or "none"

    def origin_pm_refs(self) -> int:
        return len(_git(self.origin, "for-each-ref", "refs/heads/pm").splitlines())

    def rows(self, kind: str) -> list[str]:
        if not self.ledger.exists():
            return []
        return [r for r in self.ledger.read_text().splitlines() if r.split()[2:3] == [kind]]

    def bare_gate_calls(self) -> int:
        path = self.rec / "gate.calls"
        lines = path.read_text().split("\n")[:-1] if path.exists() else []
        return sum(1 for line in lines if "--list-legs" not in line)


@dataclass(frozen=True)
class Plan:
    """This tree's `--list-legs`, its full legs, and the units a whole CI run names."""

    listing: str
    legs: str
    units: str


@pytest.fixture(scope="module")
def plan() -> Plan:
    """The real listing, read once; the units carry `/1` on the one that holds the suite."""
    done = subprocess.run(
        ["./scripts/check.sh", "--list-legs"], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0 and done.stdout.strip(), done.stderr
    units = []
    for row in done.stdout.splitlines():
        cols = row.split("\t")
        if len(cols) >= 4:
            one = ledger.ONEPASS_UNIT in cols[3].split(",")
            units.append(f"{cols[0]}/1" if one else cols[0])
    assert units, "the real listing names no units for a CI record"
    return Plan(done.stdout, ",".join(ledger.full_legs(ROOT)), ",".join(units))


@pytest.fixture
def world(scratch: Path, stub_path: StubPath, plan: Plan) -> World:
    """A fresh train-road world."""
    return World.make(scratch / "w", stub_path, plan)


# moved: case_bank_boxes_carry_a_one_hour_lifetime_and_a_thirty_minute_idle — test_box_bank.py

# moved: case_a_green_bank_brings_the_shards_drive_rows_home — test_box_bank.py

# moved: case_a_red_bank_harvests_nothing — test_box_bank.py

# moved: case_the_bank_reads_the_real_checkout_path_out_of_bake_sh — test_box_bank.py

# moved: case_a_red_bank_builds_no_image — test_box_bank.py

# moved: case_a_lying_tag_builds_nothing_and_the_bank_stands — test_box_bank.py


# --- the argument arm: every refusal before a fold, a box or a push -----------------------------


def test_on_boxes_without_bank_is_refused(world: World) -> None:
    assert world.run("--on-boxes", "8") == 2
    assert "--on-boxes is only meaningful with --bank" in world.out
    assert "STUB GATE ran" not in world.out
    assert count_lines(world.rec / "fold.calls") == 0
    assert not world.ledger.exists()
    assert world.bare_gate_calls() == 0
    assert world.run("--on-boxen", "8") == 2
    assert "unknown flag --on-boxen" in world.out
    assert world.run("--bank", "--on-boxes") == 2
    assert "--on-boxes takes a box count" in world.out
    assert count_lines(world.rec / "fold.calls") == 0


def test_on_boxes_below_the_syntactic_floor_is_refused(world: World) -> None:
    floor = push.ON_BOXES_FLOOR
    assert world.run("--bank", "--on-boxes", str(floor - 1)) == 2
    assert f"is below the floor of {floor}" in world.out
    assert "N = 3 + P + S" in world.out
    assert count_lines(world.rec / "fold.calls") == 0
    assert not world.ledger.exists()
    assert world.bare_gate_calls() == 0
    assert world.run("--bank", "--on-boxes", "eight") == 2
    assert "takes a whole number of boxes, got 'eight'" in world.out


# --- --pr: the train branch, pushed on an intent --------------------------------------------


def test_pr_pushes_a_train_branch_on_an_intent_and_the_wall_says_so(world: World) -> None:
    world.wire_hook()
    _git(world.repo, "switch", "-q", "main")
    assert world.run("--pr") == 2
    assert "--pr pushes a TRAIN branch, and this checkout is on 'main'" in world.out
    assert world.origin_pm_refs() == 0
    assert count_lines(world.ledger) == 0
    _git(world.repo, "switch", "-q", "pm/train")

    (world.repo / "dirty.txt").write_text("dirty\n")
    assert world.run("--pr") == 2
    assert "has uncommitted changes" in world.out
    assert count_lines(world.rec / "fold.calls") == 0
    assert world.origin_pm_refs() == 0
    (world.repo / "dirty.txt").unlink()

    assert world.run("--pr") == 0, world.out
    tree, sha = world.tree(), world.head()
    assert "DJB_GATE_SANCTION" not in world.out
    assert count_lines(world.rec / "fold.calls") == 1
    assert "pm_push --pr: pr=#7 https://github.com/o/r/pull/7 auto-merge=on (merge commit)" in (
        world.out
    )
    assert f"pre-push: wall ci-intent {tree}" in world.out
    assert "pre-push: wall measuring" not in world.out
    assert world.bare_gate_calls() == 0
    assert world.origin_ref("refs/heads/pm/train") == sha
    assert world.rows("full") == []
    (intent,) = world.rows("intent")
    words = intent.split()
    assert words[:3] == ["v1", tree, "intent"]
    assert words[4:7] == ["run=pending", f"commit={sha}", "branch=pm/train"]
    assert words[7].startswith("at=") and words[-1] == (
        "sanction=ci:pm_push:the%20pull%20request's%20run%20measures%20pm/train"
    )
    calls = (world.gh / "calls").read_text().splitlines()
    assert [c.split()[:2] for c in calls] == [
        ["pr", "list"],
        ["pr", "create"],
        ["pr", "list"],
        ["repo", "view"],
        ["api", "repos/o/r/rules/branches/main"],
        ["pr", "merge"],
        ["pr", "view"],
    ]
    assert calls[0].startswith("pr list --head pm/train --state open --json number,url ")
    assert calls[1].startswith("pr create --base main --head pm/train --title the train --body ")
    assert calls[5] == "pr merge 7 --auto --merge"
    assert calls[6].startswith("pr view 7 --json autoMergeRequest,state,mergeStateStatus ")

    (world.repo / "train.txt").write_text("two\n")
    _git(world.repo, "commit", "-q", "-am", "the train, again")
    assert world.run("--pr", "--no-fold") == 0, world.out
    assert "--no-fold — THE DERIVED FILES WERE NOT REGENERATED" in world.out
    assert count_lines(world.rec / "fold.calls") == 1
    assert f"pre-push: wall ci-intent {world.tree()}" in world.out
    assert "pm_push --pr: pr=#7" in world.out
    assert (world.gh / "calls").read_text().count("pr create") == 1

    sha, tree = world.head(), world.tree()
    said = world.hook(
        f"refs/heads/pm/train {sha} refs/heads/scratch {ZERO}\n", DJB_PUSH_INTENT="ci"
    )
    assert "DJB_PUSH_INTENT=ci ignored — the push names refs/heads/scratch" in said
    assert f"pre-push: wall measuring {tree}" in said
    assert "wall ci-intent" not in said

    now = int(time.time())
    world.ledger.write_text(
        f"v1 {tree} intent 2026-01-01T00:00:00Z run=pending commit={sha} branch=pm/train"
        f" at={ledger.ci_stamp(now - 5000)} epoch={now - 5000}"
        " sanction=typed:drive:an%20old%20train\n"
    )
    said = world.hook(
        f"refs/heads/pm/train {sha} refs/heads/pm/train {ZERO}\n", DJB_PUSH_INTENT="ci"
    )
    assert "(the window is 900 s) — not honoured." in said
    assert f"pre-push: wall measuring {tree}" in said
    assert "wall ci-intent" not in said


def test_pr_needs_no_typed_sanction_and_names_its_pull_request(world: World) -> None:
    """R10.1: the PR number is the audit; a typed sanction is neither asked for nor read."""
    world.wire_hook()
    assert world.run("--pr", DJB_GATE_SANCTION="") == 0, world.out
    assert "takes a typed sanction" not in world.out
    assert "pm_push --pr: pr=#7 https://github.com/o/r/pull/7 auto-merge=on" in world.out
    assert world.origin_ref("refs/heads/pm/train") == world.head()


def test_the_pr_recipe_says_push_once_and_that_a_fold_only_push_is_honoured(world: World) -> None:
    world.wire_hook()
    assert world.run("--pr") == 0, world.out
    assert push.PR_ONCE in world.out
    assert "push once at `--fast` green with main folded in" in push.PR_ONCE
    assert "a push whose only change is the fold is honoured" in push.PR_ONCE
    assert "a push that brings main's commits is measured" in push.PR_ONCE


def test_a_stacked_pull_request_behind_main_is_named_and_the_exit_is_unchanged(
    world: World,
) -> None:
    world.wire_hook()
    (world.gh / "pr.status").write_text("BEHIND\n")
    assert world.run("--pr") == 0, world.out
    assert "pm_push --pr: pr=#7 https://github.com/o/r/pull/7 auto-merge=on" in world.out
    behind = "pr #7 is BEHIND main (strict checks): merge origin/main into this branch"
    assert f"{behind} and run --pr again" in world.out
    assert (world.gh / "calls").read_text().count("pr view") == 1
    (world.gh / "pr.status").unlink()
    assert world.run("--pr") == 0, world.out
    assert "is BEHIND" not in world.out


#: The forge's two acts after the push: each refusal is exit 2 and says the branch is pushed.
FORGE = {
    "create": ("`gh pr create` refused", "GraphQL: the forge refused"),
    "merge": ("`gh pr merge 7 --auto --merge` refused", "auto-merge is not allowed"),
}


@pytest.mark.parametrize("act", sorted(FORGE))
def test_a_forge_refusal_after_the_push_is_exit_2_and_a_rerun_finishes_it(
    world: World, act: str
) -> None:
    world.wire_hook()
    (world.gh / f"{act}.rc").write_text("1\n")
    assert world.run("--pr") == 2, world.out
    for needle in FORGE[act]:
        assert needle in world.out
    assert "the branch IS pushed" in world.out
    assert world.origin_ref("refs/heads/pm/train") == world.head()
    (world.gh / f"{act}.rc").unlink()
    assert world.run("--pr") == 0, world.out
    assert "nothing to push" in world.out
    assert "pm_push --pr: pr=#7" in world.out


#: The merge call's two answers that arm nothing: each is exit 2 and never says auto-merge=on.
UNARMED = {
    "now": "pull request #7 MERGED at once, without a CI verdict",
    "unarmed": "auto-merge was NOT armed on pull request #7 (state OPEN)",
}


@pytest.mark.parametrize("shape", sorted(UNARMED))
def test_a_merge_call_that_armed_nothing_is_exit_2_naming_what_happened(
    world: World, shape: str
) -> None:
    world.wire_hook()
    (world.gh / f"merge.{shape}").write_text("")
    assert world.run("--pr") == 2, world.out
    assert UNARMED[shape] in world.out
    assert "the ruleset that requires the CI run on main must be active" in " ".join(
        world.out.split()
    )
    assert "auto-merge=on" not in world.out


#: A merged pull request's check rollup as the read-back's `--jq` prints it: name, conclusion, url.
ROLLUP_PASSED = """verdict SUCCESS https://github.com/o/r/actions/runs/11/job/1
gate-verdict SUCCESS https://github.com/o/r/actions/runs/11/job/2
lint SKIPPED https://github.com/o/r/actions/runs/11/job/3
"""
MERGED_SOUNDLY = (
    "pm_push --pr: pull request #7 merged at once — its required checks had already passed"
    " (verdict: https://github.com/o/r/actions/runs/11/job/1,"
    " gate-verdict: https://github.com/o/r/actions/runs/11/job/2)"
)


def test_a_merge_at_once_whose_required_checks_had_passed_is_exit_0_naming_them(
    world: World,
) -> None:
    world.wire_hook()
    (world.gh / "merge.now").write_text("")
    (world.gh / "rollup.out").write_text(ROLLUP_PASSED)
    assert world.run("--pr") == 0, world.out
    assert MERGED_SOUNDLY in world.out
    assert "MERGED at once, without a CI verdict" not in world.out
    calls = (world.gh / "calls").read_text().splitlines()
    assert calls[7].startswith("pr view 7 --json statusCheckRollup ")


#: A rollup that does not vouch for the merge: each is today's refusal, exit 2, unchanged.
UNSOUND = {
    "none": "",
    "one-failed": ROLLUP_PASSED.replace("gate-verdict SUCCESS", "gate-verdict FAILURE"),
    "one-missing": ROLLUP_PASSED.replace(
        "verdict SUCCESS https://github.com/o/r/actions/runs/11/job/1\n", ""
    ),
}


@pytest.mark.parametrize("shape", sorted(UNSOUND))
def test_a_merge_at_once_without_every_required_check_passed_is_today_s_refusal(
    world: World, shape: str
) -> None:
    world.wire_hook()
    (world.gh / "merge.now").write_text("")
    (world.gh / "rollup.out").write_text(UNSOUND[shape])
    assert world.run("--pr") == 2, world.out
    refusal = (
        "!! pm_push --pr: pull request #7 MERGED at once, without a CI verdict"
        " (mergeStateStatus CLEAN).\n"
        "   `gh pr merge --auto` merges immediately when nothing requires a check: the\n"
        "   ruleset that requires the CI run on main must be active before --pr is used.\n"
    )
    assert refusal in world.out
    assert "merged at once —" not in world.out


#: Main's required checks as the forge answers them, and the context each answer leaves out.
UNREQUIRED = {
    "no-ruleset": ("[]\n", "verdict, gate-verdict"),
    "one-context": (RULES_REQUIRED.replace('{"context":"verdict"},', ""), "verdict"),
}


@pytest.mark.parametrize("shape", sorted(UNREQUIRED))
def test_pr_refuses_to_arm_auto_merge_when_main_does_not_require_both_checks(
    world: World, shape: str
) -> None:
    world.wire_hook()
    answer, missing = UNREQUIRED[shape]
    (world.gh / "rules.out").write_text(answer)
    assert world.run("--pr") == 2, world.out
    calls = (world.gh / "calls").read_text().splitlines()
    assert not any(c.startswith("pr merge") for c in calls)
    assert "pull request #7 is OPEN and NOT merged" in world.out
    assert f"(missing: {missing})" in world.out
    edit = world.out.index("gh repo edit o/r --enable-auto-merge")
    assert edit < world.out.index("gh api -X POST repos/o/r/rulesets --input deploy/ruleset.json")
    assert "auto-merge=on" not in world.out
    (world.gh / "rules.out").write_text(RULES_REQUIRED)
    assert world.run("--pr") == 0, world.out
    assert "pm_push --pr: pr=#7 https://github.com/o/r/pull/7 auto-merge=on" in world.out


def test_a_forge_that_cannot_answer_for_main_s_checks_is_exit_2_and_never_a_merge(
    world: World,
) -> None:
    world.wire_hook()
    (world.gh / "api.rc").write_text("1\n")
    assert world.run("--pr") == 2, world.out
    assert "`gh api repos/o/r/rules/branches/main` refused (exit 1)" in world.out
    assert "HTTP 403: API rate limit exceeded" in world.out
    calls = (world.gh / "calls").read_text().splitlines()
    assert not any(c.startswith("pr merge") for c in calls)


def test_the_shipped_ruleset_requires_what_pr_reads_on_the_default_branch() -> None:
    shipped = json.loads((ROOT / push.RULESET_FILE).read_text())
    assert shipped["enforcement"] == "active"
    assert shipped["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert push.missing_checks(shipped["rules"]) == []
    assert push.missing_checks([]) == list(push.REQUIRED_CHECKS)


def test_a_merged_pull_request_of_the_same_branch_is_not_reused(world: World) -> None:
    world.wire_hook()
    (world.gh / "pr.out").write_text("5 https://github.com/o/r/pull/5\n")
    (world.gh / "pr.state").write_text("MERGED\n")
    assert world.run("--pr") == 0, world.out
    calls = (world.gh / "calls").read_text().splitlines()
    assert sum(c.startswith("pr create ") for c in calls) == 1
    assert "pr merge 7 --auto --merge" in calls
    assert not any(c.startswith("pr merge 5") for c in calls)
    assert "pm_push --pr: pr=#7 https://github.com/o/r/pull/7 auto-merge=on" in world.out


def test_pr_with_nothing_new_exits_0_before_the_hook(world: World) -> None:
    world.wire_hook()
    assert world.run("--pr") == 0, world.out
    sha = world.head()
    assert world.origin_ref("refs/heads/pm/train") == sha
    intents = len(world.rows("intent"))
    (world.rec / "gate.calls").write_text("")
    assert world.run("--pr") == 0, world.out
    assert f"pm/train is already at {sha} — nothing to push." in world.out
    assert "pm_push --pr: pr=#7" in world.out
    assert "pre-push:" not in world.out
    assert world.bare_gate_calls() == 0
    assert len(world.rows("intent")) == intents


#: `pr`'s six refusals: each is exit 2 (the fold's own exit for the fold), before any row.
SIX = {
    "off-train": ("--pr pushes a TRAIN branch, and this checkout is on 'a detached HEAD'",),
    "dirty": ("has uncommitted changes.", "Nothing was folded, nothing was written"),
    "fold-failed": ("THE FOLD EXITED 2", "Nothing was written and nothing was pushed."),
    "fold-left-dirt": ("the fold left", "fold-left-this.txt"),
    "no-measured-tree": ("the measured tree of", "the intent row would name nothing"),
    "no-intent-row": ("the intent row could not be written",),
}


@pytest.mark.parametrize("cause", sorted(SIX))
def test_pr_refuses_each_of_its_six_causes_with_exit_2_and_nothing_pushed(
    world: World, cause: str
) -> None:
    ledger_at = str(world.ledger)
    if cause == "off-train":
        _git(world.repo, "switch", "-q", "--detach")
    elif cause == "dirty":
        (world.repo / "dirty.txt").write_text("dirty\n")
    elif cause == "fold-failed":
        (world.rec / "fold.rc").write_text("2\n")
    elif cause == "fold-left-dirt":
        (world.rec / "fold.dirt").write_text("a file the fold forgot\n")
    elif cause == "no-measured-tree":
        real = world.stubs.require_real("git")
        world.stubs.plant("git", STUB_GIT_NO_TREE.replace("__GIT__", real))
    elif cause == "no-intent-row":
        ledger_at = str(world.root / "tmp")
    assert world.run("--pr", DJB_GATE_LEDGER=ledger_at) == 2, world.out
    for needle in SIX[cause]:
        assert needle in world.out
    assert world.origin_pm_refs() == 0
    assert world.rows("intent") == []
    assert count_lines(world.gh / "calls") == 0
    folded = count_lines(world.rec / "fold.calls")
    assert folded == (0 if cause in ("off-train", "dirty") else 1)


STALE_PAGE = (
    "docs/sdk/discovered-files.md is stale — run: python -m quality.sdk --reference,"
    " then stage docs/sdk/"
)


@pytest.mark.parametrize("mode", ["--pr", "--bank"])
def test_a_stale_reference_is_refused_before_the_gate(
    world: World,
    mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    from quality.djb.legs import sdk_reference
    from quality.tests.test_sdk_reference import _shifted_world

    shifted = _shifted_world(tmp_path)
    real, env = sdk_reference.check, dict(os.environ)
    monkeypatch.setattr(sdk_reference, "check", lambda root, env_=None: real(shifted, env))
    (world.repo / "docs/sdk").mkdir(parents=True)
    (world.repo / "docs/sdk/reference.md").write_text("# the reference\n")
    _git(world.repo, "add", "docs/sdk/reference.md")
    _git(world.repo, "commit", "-q", "-m", "the reference")
    for name in list(os.environ):
        monkeypatch.delenv(name)
    for name, value in world.env().items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(world.repo)
    assert push.main([mode]) == 2
    said = capfd.readouterr()
    assert f"!! {STALE_PAGE}" in said.err, said.out + said.err
    assert "Nothing was pinned and nothing was pushed." in said.err
    assert world.bare_gate_calls() == 0
    assert world.origin_pm_refs() == 0
    assert world.rows("intent") == [] and world.rows("full") == []
    assert count_lines(world.gh / "calls") == 0


def test_pr_takes_no_commit_and_refuses_one(world: World) -> None:
    assert world.run("--pr", "HEAD") == 2
    assert "--pr pushes THIS checkout's train branch, so it takes no commit argument." in world.out
    assert count_lines(world.rec / "fold.calls") == 0


# --- --ci-verdict: the PR run's record read, judged and banked ---------------------------------

RUN = "36282702383"


def gh_run(world: World, run: str, status: str, attempt: int) -> None:
    (world.gh / f"view-{run}").write_text(f"{status} {attempt}\n")


def gh_record(world: World, run: str, attempt: int, line: str) -> None:
    art = world.gh / f"art-{run}" / f"{ledger.CI_ARTIFACT}-{attempt}"
    art.mkdir(parents=True, exist_ok=True)
    (art / ledger.CI_RECORD).write_text(line + "\n")


def ci_rec(
    plan: Plan, commit: str, tree: str, rc: int, attempt: int, scope: str = "whole", **kw: str
) -> str:
    """A record for `RUN`, written by THE writer, so no fixture is a line the grammar refuses."""
    legs = kw.get("legs", plan.units)
    return ledger.ci_record(
        commit,
        tree,
        legs,
        "3",
        scope,
        str(rc),
        RUN,
        str(attempt),
        kw.get("at") or None,
        lane=kw.get("lane") or None,
    )


def stamp_from_now(seconds: int) -> str:
    return ledger.ci_stamp(int(time.time()) + seconds)


#: Each refusal: the sentence it says, and what the fake `gh` and the record are made to hold.
CI_CAUSES = (
    "no-gh",
    "gh-failing",
    "no-completed-run",
    "no-such-run",
    "not-completed",
    "no-artifact",
    "download-failed",
    "unparsable",
    "another-run",
    "another-attempt",
    "scope-pr",
    "red",
    "future",
    "older-than-24h",
    "unknown-commit",
    "wrong-tree",
    "not-an-ancestor",
    "legs-short",
    "unknown-unit",
    "lane-loop",
    "lane-docs",
)


@pytest.mark.parametrize("cause", CI_CAUSES)
def test_ci_verdict_refuses_each_cause_with_exit_2_and_no_row(
    world: World, plan: Plan, cause: str
) -> None:
    commit, tree = world.head(), world.tree()
    run: tuple[str, ...] = (RUN,)
    if cause == "no-gh":
        world.stubs.remove("gh")
        said = "no `gh` on PATH"
    elif cause == "gh-failing":
        (world.gh / "api.rc").write_text("1\n")
        run, said = (), f"could not look (`gh api` for the pull requests of {commit[:12]}"
    elif cause == "no-completed-run":
        run, said = (
            (),
            f"no candidate (no pull_request or push run of ci.yml for {commit[:12]}",
        )
    elif cause == "no-such-run":
        said = f"`gh run view {RUN}` did not answer"
    elif cause == "not-completed":
        gh_run(world, RUN, "in_progress", 1)
        said = f"has not completed its {ledger.CI_RECORD_JOB} job (run status 'in_progress'"
    else:
        attempt = 2 if cause == "another-attempt" else 1
        gh_run(world, RUN, "completed", attempt)
        side = _git(world.repo, "commit-tree", tree, "-m", "a root with the same bytes")
        empty = _git(world.repo, "hash-object", "-t", "tree", "/dev/null")
        records = {
            "no-artifact": ("", "attempt 1 (the latest) carries no gate-verdict-1 artifact"),
            "download-failed": (
                ci_rec(plan, commit, tree, 0, 1),
                "failed for a reason that is not a missing artifact",
            ),
            "unparsable": ("schema=gate-verdict/1 at=yesterday rc=0", "record will not parse"),
            "another-run": (
                ledger.ci_record(commit, tree, plan.units, "3", "whole", "0", "999", "1"),
                "record names run=999",
            ),
            "another-attempt": (
                ci_rec(plan, commit, tree, 0, 1),
                "latest attempt is 2 and its record says attempt=1",
            ),
            "scope-pr": (ci_rec(plan, commit, tree, 0, 1, "pr"), "ran NARROWED (scope=pr)"),
            "red": (ci_rec(plan, commit, tree, 1, 1), "is RED (rc=1)"),
            "future": (
                ci_rec(plan, commit, tree, 0, 1, at=stamp_from_now(3600)),
                "stamped IN THE FUTURE",
            ),
            "older-than-24h": (
                ci_rec(plan, commit, tree, 0, 1, at=stamp_from_now(-172800)),
                "OLDER THAN 24 h",
            ),
            "unknown-commit": (
                ci_rec(plan, "c" * 40, tree, 0, 1),
                "which this checkout does not have",
            ),
            "wrong-tree": (
                ci_rec(plan, commit, empty, 0, 1),
                "the run measured bytes the commit does not carry",
            ),
            "not-an-ancestor": (
                ci_rec(plan, side, tree, 0, 1),
                "neither HEAD nor an ancestor of it",
            ),
            "legs-short": (
                ci_rec(plan, commit, tree, 0, 1, legs=plan.units.rsplit(",", 1)[0]),
                "do not cover this gate's full leg set — missing",
            ),
            "unknown-unit": (
                ci_rec(plan, commit, tree, 0, 1, legs=f"{plan.units},no-such-unit"),
                "names unit 'no-such-unit', which this checkout's listing does not declare",
            ),
            "lane-loop": (
                ci_rec(plan, commit, tree, 0, 1, lane="loop"),
                f"run {RUN} ran the loop lane — only the full lane vouches for a tree",
            ),
            "lane-docs": (
                ci_rec(plan, commit, tree, 0, 1, lane="docs"),
                f"run {RUN} ran the docs lane — only the full lane vouches for a tree",
            ),
        }
        line, said = records[cause]
        if line:
            gh_record(world, RUN, attempt, line)
        if cause == "download-failed":
            (world.gh / f"download-{RUN}.rc").write_text("1\n")
    assert world.run("--ci-verdict", *run) == 2, world.out
    assert "THE CI RECORD CANNOT BE BANKED: " in world.out
    assert said in world.out
    assert "No row was written and nothing was pushed." in world.out
    assert world.rows("full") == []


def test_ci_verdict_reads_the_latest_attempt_and_banks_one_honoured_row(
    world: World, plan: Plan
) -> None:
    commit, tree = world.head(), world.tree()
    gh_run(world, RUN, "completed", 2)
    gh_record(world, RUN, 1, ci_rec(plan, commit, tree, 0, 1))
    gh_record(world, RUN, 2, ci_rec(plan, commit, tree, 1, 2))
    assert world.run("--ci-verdict", RUN) == 2
    assert "is RED (rc=1)" in world.out
    assert world.rows("full") == []
    shutil.rmtree(world.gh)
    world.gh.mkdir()

    gh_run(world, RUN, "completed", 2)
    gh_record(world, RUN, 1, ci_rec(plan, commit, tree, 1, 1))
    gh_record(world, RUN, 2, ci_rec(plan, commit, tree, 0, 2))
    assert world.run("--ci-verdict", RUN) == 0, world.out
    assert f"verdict banked for tree {tree}" in world.out
    (row,) = world.rows("full")
    assert f" {tree} full " in row
    assert f"caller=pm-bank sanction=ci-verdict:pm_push:run={RUN}%20attempt=2%20" in row
    assert row.endswith(f" leak-proof=ci:{RUN} rc=0")
    calls = (world.gh / "calls").read_text()
    assert f"--name {ledger.CI_ARTIFACT}-2" in calls
    assert f"--name {ledger.CI_ARTIFACT}-1" not in calls
    looked = ledger.consult(world.repo, tree, path=world.ledger)
    assert looked is not None and ledger.format(looked) == row
    shutil.rmtree(world.gh)
    world.gh.mkdir()

    world.ledger.write_text("")
    (world.gh / f"runs-{commit}.out").write_text(f"{RUN}\n")
    gh_run(world, RUN, "completed", 1)
    gh_record(world, RUN, 1, ci_rec(plan, commit, tree, 0, 1))
    assert world.run("--ci-verdict") == 0, world.out
    assert f"(the run that measured {commit[:12]}'s tree)" in world.out
    (row,) = world.rows("full")
    assert "%20merge=" not in row
    assert f"event=pull_request&head_sha={commit}" in (world.gh / "calls").read_text()

    assert world.run("--ci-verdict", "12ab") == 2
    assert "--ci-verdict takes a run id" in world.out


# narrowed: case_a_row_the_lookup_refuses_is_removed_and_the_footer_is_true
def test_a_row_the_lookup_refuses_is_removed_and_the_footer_is_true(
    world: World, plan: Plan, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The drive planted a refusing shell reader; the reader is `ledger.consult`, patched here."""
    commit, tree = world.head(), world.tree()
    good = f"v1 {tree} full 2026-09-27T00:00:00Z {plan.legs} caller=pm-bank"
    world.ledger.write_text(good + "\n")
    before = world.ledger.read_bytes()
    gh_run(world, RUN, "completed", 1)
    gh_record(world, RUN, 1, ci_rec(plan, commit, tree, 0, 1))
    intruder: list[str] = []

    def refusing(root: Path, tree: str, **_: object) -> None:
        print("note: PLANTED — this world's reader refuses every row", file=sys.stderr)
        with world.ledger.open("a") as rows:
            rows.writelines(f"{line}\n" for line in intruder)

    monkeypatch.chdir(world.repo)
    for name, value in world.env().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ledger, "consult", refusing)

    assert push.main(["--ci-verdict", RUN]) == 2
    said = capsys.readouterr().err
    assert "PLANTED — this world's reader refuses every row" in said
    assert "the row was written and gate_ledger_lookup refuses it" in said
    assert "the row was REMOVED, and the ledger holds exactly what it held before this run" in said
    assert "No row was written and nothing was pushed." in said
    assert world.ledger.read_bytes() == before

    intruder.append("v1 intruder full 2026-09-27T00:00:00Z ruff caller=unstated")
    assert push.main(["--ci-verdict", RUN]) == 2
    said = capsys.readouterr().err
    assert "nothing was removed; the refused row STANDS" in said
    assert "A REFUSED ROW STANDS in the ledger" in said
    assert "No row was written" not in said
    assert count_lines(world.ledger) == 3


# --- main: reached by a pull request's merge, never pinned and pushed ---------------------------


def test_the_pin_and_push_road_to_main_is_retired(world: World) -> None:
    """MQ2.1: main moves by a pull request's auto-merge; no argument pins and pushes it."""
    was = _git(world.pm_push, "rev-parse", "HEAD")
    for argv in ((), ("HEAD",), ("--dry-run",), (world.head(),)):
        assert world.run(*argv) == 2, (argv, world.out)
        assert "the pin-and-push road to main is retired" in world.out
        assert "./scripts/pm_push.sh --pr" in world.out
        assert "INTENDED TIP" not in world.out
    assert _git(world.pm_push, "rev-parse", "HEAD") == was
    assert world.origin_ref("refs/heads/main") != world.head()
    assert world.run("--no-fold") == 2
    assert "--no-fold is only meaningful with --bank or --pr" in world.out

    (world.pm_push / "unsaved.txt").write_text("somebody's work\n")
    assert world.run("--bank") == 2
    assert "has uncommitted changes." in world.out
    assert "Pinning it would throw them away." in world.out
    (world.pm_push / "unsaved.txt").unlink()
    assert world.run("--bank", DJB_PUSH_WORKTREE="no-such-worktree") == 2
    assert "no worktree named 'no-such-worktree' in git worktree list" in world.out
    assert count_lines(world.rec / "fold.calls") == 0


def merged_main(world: World, *, moved: bool = False) -> tuple[str, str, str]:
    """The forge's merge of `pm/train` into main (a merge commit), pushed with no hook wired."""
    head, tree = world.head(), world.tree()
    _git(world.repo, "switch", "-q", "main")
    if moved:
        (world.repo / "moved.txt").write_text("moved\n")
        _git(world.repo, "add", "moved.txt")
        _git(world.repo, "commit", "-q", "-m", "main moved under the pull request")
    _git(world.repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #7", "pm/train")
    _git(world.repo, "push", "-q", "origin", "main")
    return head, tree, world.head()


def fresh_clone(world: World) -> Path:
    """A fresh clone of the origin's main, its packages linked and its hook wired."""
    fresh = world.root / "fresh"
    _git(world.root, "clone", "-q", str(world.origin), str(fresh))
    for package in ("quality", "apps"):
        (fresh / package).symlink_to(ROOT / package)
    (fresh / ".git" / "info" / "exclude").write_text("/quality\n/apps\n__pycache__/\n")
    _git(fresh, "config", "core.hooksPath", "scripts/githooks")
    return fresh


def test_after_the_merge_a_fresh_clone_banks_the_pr_run_and_the_wall_honours_main(
    world: World, plan: Plan
) -> None:
    """MQ2.2: the PR run measured the head; the merge commit holds that tree; one row banks it."""
    head, tree, merge = merged_main(world)
    assert _git(world.repo, "rev-parse", "HEAD^{tree}") == tree
    gh_run(world, RUN, "completed", 1)
    gh_record(world, RUN, 1, ci_rec(plan, head, tree, 0, 1))
    (world.gh / "pulls.out").write_text(f"{head}\n")
    (world.gh / f"runs-{head}.out").write_text(f"{RUN}\n")
    gh_record(world, RUN, 1, ci_rec(plan, head, tree, 0, 1, lane="full"))
    fresh = fresh_clone(world)
    ledger_ = world.root / "fresh-verdicts"
    assert world.run("--ci-verdict", at=fresh, DJB_GATE_LEDGER=str(ledger_)) == 0, world.out
    assert f"consult: honoured run={RUN} attempt=1 tree={tree}" in world.out
    assert f"verdict banked for tree {tree}" in world.out
    (row,) = [r for r in ledger_.read_text().splitlines() if " full " in r]
    assert f" {tree} full " in row
    assert f"%20commit={head[:12]}%20merge={merge[:12]}%20" in row
    calls = (world.gh / "calls").read_text()
    assert f"commits/{merge}/pulls" in calls
    assert f"event=push&head_sha={merge}" in calls
    said = world.hook_at(
        fresh, f"refs/heads/main {merge} refs/heads/main {merge}\n", DJB_GATE_LEDGER=str(ledger_)
    )
    assert f"pre-push: wall honoured {tree}" in said
    assert "main-refused" not in said
    pushed = subprocess.run(
        ["git", "-C", str(fresh), "push", "origin", "main"],
        capture_output=True,
        text=True,
        env=world.env(DJB_GATE_LEDGER=str(ledger_)),
        check=False,
    )
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    assert f"pre-push: wall honoured {tree}" in pushed.stdout + pushed.stderr


def test_a_merged_pr_s_run_still_finishing_after_its_verdict_job_is_honoured(
    world: World, plan: Plan
) -> None:
    """The record is the verdict job's: a run still running later jobs after the merge holds it."""
    head, tree, merge = merged_main(world)
    (world.gh / f"view-{RUN}").write_text("in_progress 1 completed\n")
    gh_record(world, RUN, 1, ci_rec(plan, head, tree, 0, 1, lane="full"))
    (world.gh / "pulls.out").write_text(f"{head}\n")
    (world.gh / f"runs-{head}.out").write_text(f"{RUN}\n")
    fresh = fresh_clone(world)
    ledger_ = world.root / "fresh-verdicts"
    assert world.run("--ci-verdict", at=fresh, DJB_GATE_LEDGER=str(ledger_)) == 0, world.out
    assert f"consult: honoured run={RUN} attempt=1 tree={tree}" in world.out
    assert f"verdict banked for tree {tree}" in world.out

    ledger_.write_text("")
    (world.gh / f"view-{RUN}").write_text("in_progress 1 in_progress\n")
    assert world.run("--ci-verdict", at=fresh, DJB_GATE_LEDGER=str(ledger_)) == 2, world.out
    assert f"run {RUN} has not completed its {ledger.CI_RECORD_JOB} job" in world.out
    assert "no candidate" not in world.out
    assert [r for r in ledger_.read_text().splitlines() if " full " in r] == []


def test_ci_verdict_refuses_a_run_whose_tree_is_not_the_merged_tree(
    world: World, plan: Plan
) -> None:
    """MQ2.3: a merge over a moved main holds a tree the pull request's run never measured."""
    head, tree, merge = merged_main(world, moved=True)
    merged = _git(world.repo, "rev-parse", "HEAD^{tree}")
    assert merged != tree
    gh_run(world, RUN, "completed", 1)
    gh_record(world, RUN, 1, ci_rec(plan, head, tree, 0, 1, lane="full"))
    assert world.run("--ci-verdict", RUN) == 2, world.out
    assert f"run {RUN} measured tree {tree[:12]}" in world.out
    assert f"HEAD {merge[:12]} holds the merged tree {merged[:12]}" in world.out
    assert "No row was written and nothing was pushed." in world.out
    assert world.rows("full") == []


def test_ci_verdict_on_a_loop_lane_pr_names_main_push_run_and_merge_banks_it(
    world: World, plan: Plan
) -> None:
    """A loop-lane pull request's merge is vouched for by main's push run, from any checkout."""
    head, tree, merge = merged_main(world, moved=True)
    merged = _git(world.repo, "rev-parse", "HEAD^{tree}")
    _git(world.repo, "switch", "-q", "pm/train")
    gh_run(world, RUN, "completed", 1)
    gh_record(world, RUN, 1, ci_rec(plan, head, tree, 0, 1, lane="loop"))
    assert world.run("--ci-verdict", RUN) == 2, world.out
    assert "has not merged (state OPEN)" in world.out
    (world.gh / "pr.state").write_text("MERGED\n")
    (world.gh / "merge.out").write_text(f"{merge}\n")
    push_run = "36282702999"
    (world.gh / f"runs-{merge}.out").write_text(f"{push_run}\n")
    assert world.run("--ci-verdict", RUN) == 2, world.out
    road = f"bank from main's push run {push_run} at {merge} — the PR's last run was the loop lane"
    assert road in world.out
    assert f"./scripts/pm_push.sh --ci-verdict --merge {merge}" in world.out
    assert world.rows("full") == []

    (world.gh / f"runs-{merge}.out").write_text(f"{RUN}\n")
    gh_record(world, RUN, 1, ci_rec(plan, merge, merged, 0, 1, lane="full"))
    assert world.run("--ci-verdict", "--merge", merge[:12]) == 0, world.out
    assert f"verdict banked for tree {merged}" in world.out
    assert world.head() == head
    assert [r.split()[1] for r in world.rows("full")] == [merged]
    assert "ci-merge" not in _git(world.repo, "worktree", "list")


def test_the_pull_request_is_titled_by_the_branch_s_last_working_commit(world: World) -> None:
    for name, subject in (
        ("two.txt", "mq-3: the second commit"),
        ("fold.txt", "fold: CI walls harvested"),
        ("docs" + "/ledger.md", "ledger: a row [docs-only]"),
    ):
        (world.repo / name).parent.mkdir(exist_ok=True)
        (world.repo / name).write_text(f"{subject}\n")
        _git(world.repo, "add", name)
        _git(world.repo, "commit", "-q", "-m", subject)
    assert push.pr_title(world.repo, "main", world.head()) == "mq-3: the second commit"
    assert push.pr_title(world.repo, "main", "main") == "main"


def test_ci_verdict_on_a_docs_lane_pr_names_the_docs_lane(world: World, plan: Plan) -> None:
    """The road's sentence names the lane the pull request's last run had."""
    head, tree, merge = merged_main(world, moved=True)
    _git(world.repo, "switch", "-q", "pm/train")
    gh_run(world, RUN, "completed", 1)
    gh_record(world, RUN, 1, ci_rec(plan, head, tree, 0, 1, lane="docs"))
    assert world.run("--ci-verdict", RUN) == 2, world.out
    assert "The pull request's last run was the docs lane, and it has not merged" in world.out
    (world.gh / "pr.state").write_text("MERGED\n")
    (world.gh / "merge.out").write_text(f"{merge}\n")
    (world.gh / f"runs-{merge}.out").write_text("36282702999\n")
    assert world.run("--ci-verdict", RUN) == 2, world.out
    assert f"at {merge} — the PR's last run was the docs lane" in world.out
    assert "loop lane" not in world.out.replace("ran the docs lane", "")


def test_ci_verdict_merge_refuses_a_commit_this_checkout_lacks(world: World) -> None:
    assert world.run("--ci-verdict", "--merge", "1111111aaaaaaa") == 2, world.out
    assert "merge commit 1111111aaaaaaa is not in this checkout — fetch it first." in world.out
    assert world.run("--ci-verdict", "--merge") == 2
    assert "--ci-verdict --merge takes the merge commit's sha" in world.out


# --- --bank: the docs-only road, before either arm ----------------------------------------------

DOCS_DIR = "docs/" + "fixtures"
DOCS_DOC = f"{DOCS_DIR}/rows.md"
SOURCE_PROOF = " leak-proof=acceptance:i-0drivebox0000000 rc=0"
#: The stub drive: declares the fixture directory, records its argv, exits from `rec/drive.rc`.
STUB_DRIVE = """#!/usr/bin/env bash
# __DRIVES__ __DIR__
printf 'ran %s\\n' "$*" >>"__REC__/drive.calls"
echo "STUB DRIVE ran"
exit "$(cat "__REC__/drive.rc" 2>/dev/null || echo 0)"
"""
DOCS_ROW_STAMP = " full 2026-09-19T00:00:00Z "


@dataclass
class Docs:
    """`world_docs_only`: one docs-only commit on top of a measured tree with a planted row."""

    world: World
    mtree: str
    legs: str

    def row(self, tree: str, legs: str, proof: str = "") -> None:
        with self.world.ledger.open("a") as rows:
            rows.write(
                f"v1 {tree}{DOCS_ROW_STAMP}{legs} caller=pm-bank sanction=push-wall boxes=5"
                f" shards=static waited=0 took=100{proof}\n"
            )

    def new_rows(self) -> list[str]:
        return [r for r in self.world.ledger.read_text().splitlines() if DOCS_ROW_STAMP not in r]

    def measuring_calls(self) -> list[str]:
        path = self.world.rec / "gate.calls"
        lines = path.read_text().splitlines() if path.exists() else []
        return [line for line in lines if "--list-legs" not in line]


def docs_world(world: World, plan: Plan, also: str = "") -> Docs:
    repo = world.repo
    legs = ",".join(
        f"{leg}/1" if leg == ledger.ONEPASS_UNIT else leg for leg in plan.legs.split(",")
    )
    (repo / DOCS_DIR).mkdir(parents=True)
    (repo / DOCS_DOC).write_text("the rows\n")
    drive = repo / "scripts" / "tests" / "test_docs_probe.sh"
    drive.parent.mkdir(parents=True)
    stub = STUB_DRIVE.replace("__DRIVES__", "drives" + ":").replace("__DIR__", DOCS_DIR)
    world.executable(drive, stub)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a measured tree with a doc and a drive that reads it")
    docs = Docs(world, world.tree(), legs)
    docs.row(docs.mtree, legs, SOURCE_PROOF)
    with (repo / DOCS_DOC).open("a") as doc:
        doc.write("one more row\n")
    if also:
        (repo / also).write_text("a line nobody measured\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a documentation commit")
    return docs


def test_a_docs_only_delta_runs_the_readers_and_banks_without_a_box(
    world: World, plan: Plan
) -> None:
    docs = docs_world(world, plan)
    assert world.run("--bank", "--no-fold", "--on-boxes", "8") == 0, world.out
    assert "docs-only? yes" in world.out
    assert f"docs-only reuse of {docs.mtree}" in world.out
    assert not (world.root / "lease" / "djb-gate-lease").exists()
    assert not (world.root / "lease" / "djb-gate-slots").exists()
    assert docs.measuring_calls() == ["--leg static"]
    assert count_lines(world.rec / "drive.calls") == 1
    (row,) = docs.new_rows()
    tree = world.tree()
    grammar = (
        rf"^v1 {tree} full [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}Z"
        rf" {re.escape(docs.legs)} caller=pm-bank sanction=docs-only:pm_push:from={docs.mtree}"
        r"%20paths=1%20readers=static,scripts/tests/test_docs_probe.sh waited=0 took=0"
        r" leak-proof=acceptance:i-[0-9a-z]+ rc=0$"
    )
    assert re.match(grammar, row), row
    overhead = re.search(r"^  source \+ delta \+ row: ([0-9]+) s$", world.out, re.MULTILINE)
    assert overhead is not None, world.out
    print(f"docs-only overhead: {int(overhead.group(1))} s")
    assert world.origin_ref("refs/heads/main") == world.head()


def test_the_hook_honours_the_docs_only_row_and_measures_nothing(world: World, plan: Plan) -> None:
    docs = docs_world(world, plan)
    assert world.run("--bank", "--no-fold") == 0, world.out
    assert len(docs.new_rows()) == 1
    (world.rec / "gate.calls").write_text("")
    said = world.hook(f"refs/heads/main {world.head()} refs/heads/main {ZERO}\n")
    assert "is measured green by a full gate run — verdict honoured" in said, said
    assert count_lines(world.rec / "gate.calls") == 0


def test_a_docs_only_subject_that_lies_is_refused_at_the_bank(world: World, plan: Plan) -> None:
    docs = docs_world(world, plan)
    (world.repo / "apps.txt").write_text("x = 1\n")
    _git(world.repo, "add", "apps.txt")
    _git(world.repo, "commit", "-q", "-m", "a model, quietly [docs-only]")
    lie = world.head()
    assert world.run("--bank", "--no-fold", "--on-boxes", "8") == 2, world.out
    assert "a commit says [docs-only] and its own diff is not docs-only" in world.out
    assert f"     {lie[:12]}  apps.txt" in world.out
    assert docs.new_rows() == []
    assert docs.measuring_calls() == []


def test_one_path_off_the_declared_list_and_the_arm_runs_as_it_always_did(
    world: World, plan: Plan
) -> None:
    docs = docs_world(world, plan, also="uv.lock")
    assert world.run("--bank", "--no-fold") == 0, world.out
    assert "docs-only? no — uv.lock is not a docs-only path — full bank" in world.out
    assert docs.measuring_calls() == ["--bank"]
    assert count_lines(world.rec / "drive.calls") == 0
    assert docs.new_rows() == []
    assert "pm_push: verdict banked. The pre-push hook will honour it" in world.out


def test_a_red_reader_is_a_red_tree_and_a_reader_that_could_not_look_is_a_full_bank(
    world: World, plan: Plan, scratch: Path
) -> None:
    docs = docs_world(world, plan)
    (world.rec / "drive.rc").write_text("1\n")
    assert world.run("--bank", "--no-fold") == 1, world.out
    assert "RED: pm_push --bank: docs-only readers RED: scripts/tests/test_docs_probe.sh" in (
        world.out
    )
    assert docs.new_rows() == []
    assert "verdict banked" not in world.out
    assert docs.measuring_calls() == ["--leg static"]
    assert world.origin_ref("refs/heads/main") != world.head()

    (scratch / "bin-2").mkdir()
    other = World.make(scratch / "two", StubPath(scratch / "bin-2"), plan)
    docs = docs_world(other, plan)
    (other.rec / "drive.rc").write_text("2\n")
    assert other.run("--bank", "--no-fold") == 0, other.out
    assert "could not look" in other.out and "full bank" in other.out
    assert docs.measuring_calls() == ["--leg static", "--bank"]
    assert docs.new_rows() == []


def test_a_source_row_that_is_not_honoured_is_a_full_bank_with_the_lookups_note(
    world: World, plan: Plan, scratch: Path
) -> None:
    docs = docs_world(world, plan)
    world.ledger.write_text("")
    docs.row(docs.mtree, "ruff,mypy")
    assert world.run("--bank", "--no-fold") == 0, world.out
    assert "nearest banked ancestor's row is not honoured — full bank" in world.out
    assert "so it is not honoured — measuring" in world.out
    assert "--bank" in docs.measuring_calls()

    (scratch / "bin-2").mkdir()
    other = World.make(scratch / "two", StubPath(scratch / "bin-2"), plan)
    docs = docs_world(other, plan)
    other.ledger.write_text("")
    docs.row(docs.mtree, docs.legs)
    assert other.run("--bank", "--no-fold") == 0, other.out
    assert "nearest banked ancestor's row is not honoured — full bank" in other.out
    assert "carries no green leak proof" in other.out


def test_a_dirty_tree_refuses_before_the_road_and_the_measuring_valve_skips_it(
    world: World, plan: Plan
) -> None:
    docs = docs_world(world, plan)
    with (world.repo / DOCS_DOC).open("a") as doc:
        doc.write("an uncommitted byte nobody can name\n")
    assert world.run("--bank", "--no-fold") == 2, world.out
    assert "has uncommitted changes" in world.out
    assert "docs-only?" not in world.out
    assert docs.new_rows() == []
    _git(world.repo, "checkout", "--", DOCS_DOC)

    assert world.run("--bank", "--no-fold", DJB_BANK_MEASURE="1") == 0, world.out
    assert "docs-only reuse SKIPPED by DJB_BANK_MEASURE — measuring" in world.out
    assert "docs-only? yes" not in world.out
    assert docs.measuring_calls() == ["--bank"]


def test_the_mac_arm_folds_first_and_a_red_gate_pushes_nothing(world: World) -> None:
    """Beyond the drive: the fold before the Mac's gate, its exit passed through, no pin on red."""
    assert world.run("--bank", DJB_DRIVE_GATE_RC="1") == 1, world.out
    assert count_lines(world.rec / "fold.calls") == 1
    assert "banking the POST-FOLD HEAD" in world.out
    assert "!! pm_push --bank: the full gate exited 1." in world.out
    assert _git(world.pm_push, "rev-parse", "HEAD") != world.head()
    (world.rec / "fold.rc").write_text("2\n")
    assert world.run("--bank") == 2
    assert "THE FOLD EXITED 2" in world.out
    assert world.run("--bank", "HEAD") == 2
    assert "--bank measures THIS checkout's tree" in world.out


# --- --proof: the whole suite twice under one seed ----------------------------------------------

#: The stub suite: every argv recorded, each phase's exit from a fixture.
STUB_SUITE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"__REC__/test.calls"
case " $* " in
*" --collect-only "*)
    [ ! -f "__REC__/collect.rc" ] || exit "$(cat "__REC__/collect.rc")"
    echo "apps/x/tests/test_a.py::test_one"
    exit 0
    ;;
*" --cov-context=test "*)
    [ -z "${COVERAGE_FILE:-}" ] || echo "coverage" >"$COVERAGE_FILE"
    exit "$(cat "__REC__/pass1.rc" 2>/dev/null || echo 0)"
    ;;
esac
exit "$(cat "__REC__/pass2.rc" 2>/dev/null || echo 0)"
"""
#: The stub map writer: `scripts/test_impact.py write … --out <file>`.
STUB_MAP = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"__REC__/map.calls"
out=""
while [ "$#" -gt 0 ]; do
    [ "$1" != "--out" ] || out="$2"
    shift
done
printf '%s\\n' '{"generated": {"tree": "tree:proofproof12"}, "tests": {}, "unmapped": {}}' >"$out"
exit "$(cat "__REC__/map.rc" 2>/dev/null || echo 0)"
"""


def proof_world(world: World) -> World:
    world.executable(world.repo / "scripts" / "test.sh", STUB_SUITE)
    (world.repo / ".venv" / "bin").mkdir(parents=True)
    world.executable(world.repo / ".venv" / "bin" / "python", STUB_MAP)
    with (world.repo / ".git" / "info" / "exclude").open("a") as exclude:
        exclude.write("/.venv\n/scripts/test.sh\n")
    return world


def fields(record: Path) -> dict[str, str]:
    return dict(token.split("=", 1) for token in record.read_text().split())


def test_proof_is_one_function_the_box_and_the_runner_both_call(
    world: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    proof_world(world)
    out_dir = scratch / "proof-out"
    tree = ledger.measured_tree(world.repo)
    argv = ("--proof", "--where", "nightly", "--run", "77", "--attempt", "1", "--seed", "424242")
    assert world.run(*argv, "--workers", "3", "--out", str(out_dir)) == 0, world.out
    assert "leak proof: GREEN - pass 1 and pass 2 both passed under seed 424242" in world.out
    calls = (world.rec / "test.calls").read_text().splitlines()
    assert len(calls) == 3 and "--collect-only" in calls[0]
    assert sorted(set(re.findall(r"--randomly-seed=[0-9]+", "\n".join(calls)))) == [
        "--randomly-seed=424242"
    ]
    assert sum("--randomly-seed=424242" in c for c in calls) == 2
    assert sum("--cov-context=test" in c for c in calls) == 1
    assert sum("-n 3 " in c for c in calls) == 2
    assert count_lines(world.rec / "map.calls") == 1
    record = out_dir / ledger.NIGHTLY_RECORD
    assert list(fields(record)) == ["schema", *ledger.NIGHTLY_FIELDS]
    assert fields(record)["map"] == "0" and fields(record)["tree"] == tree
    assert re.fullmatch(rf"nightly:\S+ tree={tree[:12]} rc=0", ledger.nightly_read(str(out_dir)))
    assert (out_dir / "test_impact.json").stat().st_size > 0
    assert _git(world.repo, "status", "--porcelain", "--", "scripts/test_impact.json") == ""

    # THE BOX HALF: the command the bank hands the acceptance box, run in a proof world.
    sent = another(scratch, plan, "proof-box-cmd")
    sent.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes))
    cmd = next(c.split("\t", 1)[1] for c in rec_lines(sent, "run.calls") if "--proof" in c)
    cmd = cmd.removeprefix("-- ").replace(CHECKOUT, str(world.repo))
    world.executable(
        world.repo / "scripts" / "pm_push.sh",
        f'#!/usr/bin/env bash\nexec "{sys.executable}" -m quality.djb.rituals.push "$@"\n',
    )
    with (world.repo / ".git" / "info" / "exclude").open("a") as exclude:
        exclude.write("/scripts/pm_push.sh\n")
    home = scratch / "home"
    home.mkdir()
    box = subprocess.run(
        ["bash", "-c", cmd],
        env=world.env(HOME=str(home)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert box.returncode == 0, box.stdout + box.stderr
    (box_record,) = (home / "verify").rglob(ledger.NIGHTLY_RECORD)
    assert list(fields(box_record)) == list(fields(record)), "the box's record has another shape"
    assert fields(box_record)["where"] == "acceptance"
    assert "acceptance: pass1 (contexts)" in box.stdout + box.stderr

    shutil.rmtree(world.rec)
    world.rec.mkdir()
    (world.rec / "pass2.rc").write_text("1\n")
    assert (
        world.run("--proof", "--seed", "8675309", "--workers", "3", "--out", str(scratch / "p2"))
        == 1
    )
    assert (
        "pass 2 red after a green pass 1 — candidate causes: state pass 1 left behind, the wall"
        " clock, test order; replay: ./scripts/pm_push.sh --proof --seed 8675309 --workers 3"
    ) in world.out
    assert fields(scratch / "p2" / ledger.NIGHTLY_RECORD)["rc"] == "1"
    assert fields(scratch / "p2" / ledger.NIGHTLY_RECORD)["pass2"] == "1"
    assert fields(scratch / "p2" / ledger.NIGHTLY_RECORD)["where"] == "acceptance"

    shutil.rmtree(world.rec)
    world.rec.mkdir()
    (world.rec / "pass1.rc").write_text("1\n")
    assert world.run("--proof", "--seed", "5", "--out", str(scratch / "p1")) == 1
    assert fields(scratch / "p1" / ledger.NIGHTLY_RECORD)["map"] == "2"
    assert count_lines(world.rec / "map.calls") == 0
    assert count_lines(world.rec / "test.calls") == 3
    assert not (scratch / "p1" / "test_impact.json").exists()

    shutil.rmtree(world.rec)
    world.rec.mkdir()
    (world.rec / "collect.rc").write_text("4\n")
    assert world.run("--proof", "--seed", "5", "--out", str(scratch / "pc")) == 2
    assert fields(scratch / "pc" / ledger.NIGHTLY_RECORD)["rc"] == "2"
    assert fields(scratch / "pc" / ledger.NIGHTLY_RECORD)["pass1"] == "-"

    shutil.rmtree(world.rec)
    world.rec.mkdir()
    assert world.run("--proof", "--out", str(world.repo / "inside")) == 2
    assert "is inside" in world.out
    assert world.run("--proof", "--where", "nightly") == 2
    assert "names the workflow run that is writing it" in world.out
    assert world.run("--proof", "--bogus") == 2
    assert "--proof takes --out, --seed, --workers, --where, --run and --attempt" in world.out
    assert count_lines(world.rec / "test.calls") == 0


# --- --bank --on-boxes: test_box_bank.py's stub wrapper around the module ----------------------

#: The box world's gate: `--list-legs` answers from a fixture, or fails with `listlegs.rc`.
BOX_GATE = """#!/usr/bin/env bash
FULL_LEGS=__LEGS__
printf '%s\\n' "$*" >>"__REC__/gate.calls"
if [ "${1:-}" = "--list-legs" ]; then
    if [ -f "__REC__/listlegs.err" ]; then cat "__REC__/listlegs.err" >&2; fi
    if [ -f "__REC__/listlegs.rc" ]; then exit "$(cat "__REC__/listlegs.rc")"; fi
    cat "__REC__/listlegs.out"
    exit 0
fi
echo "STUB GATE ran with: $*"
exit "${DJB_DRIVE_GATE_RC:-0}"
"""
#: `world_fold_commits`: a fold that commits a derived file, so the tree moves under the bank.
FOLD_COMMITS = """#!/usr/bin/env bash
printf 'ran\\n' >>"__REC__/fold.calls"
echo "STUB FOLD ran"
printf 'derived\\n' >"__REPO__/derived.txt"
git -C "__REPO__" add derived.txt
git -C "__REPO__" commit -q -m 'fold: the derived files'
echo "pm_fold: committed the derived files."
exit 0
"""


@dataclass(frozen=True)
class Boxes:
    """The drive's S.0: the box count this listing needs, its units, and the plan's labels at N."""

    boxes: int
    capable: tuple[str, ...]
    indiv: tuple[str, ...]
    labels: tuple[str, ...]
    suite_unit: str

    @property
    def floor(self) -> int:
        """The DERIVED floor: one box per unit the listing declares."""
        return len(self.indiv) + len(self.capable)

    @property
    def victim_unit(self) -> str:
        """The LAST shardable unit — what the failure cases perturb."""
        return self.capable[-1]

    @property
    def victim_k(self) -> int:
        return sum(lb.startswith(f"{self.victim_unit}-") for lb in self.labels)

    @property
    def victim(self) -> str:
        """The victim unit's last shard."""
        return f"{self.victim_unit}-{self.victim_k}of{self.victim_k}"

    @property
    def victim_first(self) -> str:
        return f"{self.victim_unit}-1of{self.victim_k}"

    def shards_of(self, unit: str) -> list[str]:
        return [lb for lb in self.labels if lb.startswith(f"{unit}-")]


def plan_labels(listing: str, n: int, sink: Path) -> list[str]:
    """`bank_boxes_plan`'s labels for `listing` at N, in plan order."""
    (sink / "listing.tsv").write_text(listing)
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        rc = box_bank.bank_boxes_plan(
            str(sink / "listing.tsv"), n, "1", "a b c", suite_leg="pytest-x2"
        )
    assert rc == 0, f"the plan refused this tree's listing at N={n}"
    return [row.split("\t")[0] for row in said.getvalue().splitlines() if row]


@pytest.fixture(scope="module")
def boxes(plan: Plan, tmp_path_factory: pytest.TempPathFactory) -> Boxes:
    rows = [r.split("\t") for r in plan.listing.splitlines() if r.split("\t")[0]]
    capable = tuple(r[0] for r in rows if len(r) > 2 and r[2] == "N-capable")
    indiv = tuple(r[0] for r in rows if len(r) > 2 and r[2] != "N-capable")
    suite = next((r[0] for r in rows if len(r) > 3 and "pytest-x2" in r[3].split(",")), "")
    assert capable, "this tree's listing has no N-capable unit"
    assert len(indiv) >= 2, "the cases that perturb a whole-box shard need two indivisible units"
    assert suite in capable, "no N-capable unit carries the suite leg"
    n = len(rows) + 3
    labels = plan_labels(plan.listing, n, tmp_path_factory.mktemp("plan"))
    return Boxes(n, capable, indiv, tuple(labels), suite)


def box_world(
    world: World, plan: Plan, *, legs: str | None = None, listing: str | None = None
) -> World:
    """`fresh_world`'s box half: the stub wrapper, bake.sh, provision.sh and a map, committed."""
    from quality.tests.test_box_bank import BAKE, REGISTRY, STUB_PROVISION, STUB_VB

    repo, rec = world.repo, world.rec
    gate = BOX_GATE.replace("__LEGS__", plan.legs if legs is None else legs)
    world.executable(repo / "scripts" / "check.sh", gate)
    if listing is not None:
        (rec / "listlegs.out").write_text(listing)
    vb = STUB_VB.replace("__REC__", str(rec)).replace("__REPO__", str(repo))
    world.executable(repo / "scripts" / "verifier_box.sh", vb.replace("__SUITELEG__", "pytest-x2"))
    (repo / "deploy" / "verifier").mkdir(parents=True)
    world.executable(repo / "deploy" / "verifier" / "bake.sh", BAKE)
    world.executable(repo / "deploy" / "provision.sh", STUB_PROVISION)
    (rec / "registry").write_text(f"{REGISTRY}\n")
    (repo / "scripts" / "test_impact.json").write_text(
        '{"generated": {"at": "-", "pytest": 0, "tree": "-"}, "tests": {}, "unmapped": {}}\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the box world")
    return world


def rec_lines(world: World, name: str) -> list[str]:
    path = world.rec / name
    return [line for line in path.read_text().split("\n") if line] if path.exists() else []


def assert_mac_measured_nothing(world: World) -> None:
    """No bare gate on this Mac, no lease, no slot."""
    other = [c for c in rec_lines(world, "gate.calls") if "--list-legs" not in c]
    assert other == [], f"the Mac's own gate was invoked: {other}"
    assert not (world.root / "lease" / "djb-gate-lease").exists()
    assert not (world.root / "lease" / "djb-gate-slots").exists()


def round_robin(boxes: int, zones: int) -> list[int]:
    """`plan_round_robin`: N shards dealt over Z zones, the per-zone counts largest first."""
    return sorted(
        (boxes // zones + (1 if z < boxes % zones else 0) for z in range(zones)), reverse=True
    )


def shards_per_zone(world: World) -> list[int]:
    ups = [line.split("\t") for line in rec_lines(world, "up.calls")]
    zones = [u[2] for u in ups if u[0] != "acceptance"]
    return sorted((zones.count(z) for z in set(zones)), reverse=True)


@pytest.fixture
def bw(world: World, plan: Plan) -> World:
    """A fresh box world."""
    return box_world(world, plan)


def test_the_composed_row_keys_on_the_post_fold_tree(bw: World, boxes: Boxes) -> None:
    bw.executable(
        bw.repo / "scripts" / "pm_fold.sh", FOLD_COMMITS.replace("__REPO__", str(bw.repo))
    )
    _git(bw.repo, "add", "scripts/pm_fold.sh")
    _git(bw.repo, "commit", "-q", "-m", "a fold that commits")
    before = bw.tree()
    assert bw.run("--bank", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    after = bw.tree()
    assert before != after, "the fold did not move the tree, so this case measures nothing"
    (row,) = bw.ledger.read_text().splitlines()
    assert row.split()[1] == after
    assert "banking the POST-FOLD HEAD" in bw.out
    assert_mac_measured_nothing(bw)


def test_the_mac_holds_no_lease_and_runs_no_gate(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert rec_lines(bw, "gate.calls") == ["--list-legs"]
    assert "This Mac MEASURES NOTHING" in bw.out
    assert_mac_measured_nothing(bw)

    (scratch / "bin-red").mkdir()
    red = box_world(World.make(scratch / "red", StubPath(scratch / "bin-red"), plan), plan)
    (red.rec / "box.rc.static").write_text("1\n")
    assert red.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, red.out
    assert_mac_measured_nothing(red)


def test_one_more_box_goes_to_the_last_shardable_unit(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    (scratch / "bin-probe").mkdir()
    probe = box_world(World.make(scratch / "probe", StubPath(scratch / "bin-probe"), plan), plan)
    assert probe.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, probe.out
    before = {
        u: sum(f"--unit {u} --shard" in c for c in rec_lines(probe, "leg.calls"))
        for u in boxes.capable
    }
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes + 1)) == 0, bw.out
    after = {
        u: sum(f"--unit {u} --shard" in c for c in rec_lines(bw, "leg.calls"))
        for u in boxes.capable
    }
    last = boxes.capable[-1]
    assert after[last] == before[last] + 1
    assert {u: after[u] for u in boxes.capable[:-1]} == {u: before[u] for u in boxes.capable[:-1]}
    assert_mac_measured_nothing(bw)


def test_a_broken_listing_is_exit_2_before_any_box(bw: World, boxes: Boxes) -> None:
    (bw.rec / "listlegs.rc").write_text("2\n")
    (bw.rec / "listlegs.err").write_text("!! --list-legs: a leg is in NO unit.\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "--list-legs exited 2" in bw.out
    assert "a leg is in NO unit" in bw.out
    assert rec_lines(bw, "up.calls") == []
    assert count_lines(bw.ledger) == 0
    assert_mac_measured_nothing(bw)


def test_the_plan_spreads_shards_across_the_zones_the_wrapper_lists(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    three = "xx-drive-9a\nxx-drive-9b\nxx-drive-9c\n"
    (bw.rec / "zones").write_text(three)
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert "zones xx-drive-9a xx-drive-9b xx-drive-9c" in bw.out
    assert sum(c.startswith("zones") for c in rec_lines(bw, "vb.calls")) == 1
    assert shards_per_zone(bw) == round_robin(boxes.boxes, 3)
    ups = [u.split("\t") for u in rec_lines(bw, "up.calls")]
    assert len({u[2] for u in ups}) == 3
    assert all(u[2] != "-" for u in ups), "a box was brought up with no --az at all"
    assert count_lines(bw.ledger) == 1
    assert_mac_measured_nothing(bw)

    (scratch / "bin-noisy").mkdir()
    noisy = box_world(World.make(scratch / "noisy", StubPath(scratch / "bin-noisy"), plan), plan)
    (noisy.rec / "zones").write_text(three)
    (noisy.rec / "zones.noise").write_text("")
    assert noisy.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, noisy.out
    assert "zones xx-drive-9a xx-drive-9b xx-drive-9c" in noisy.out
    assert "zones verifier_box: warning" not in noisy.out
    assert len({u.split("\t")[2] for u in rec_lines(noisy, "up.calls")}) == 3

    (scratch / "bin-two").mkdir()
    two = box_world(World.make(scratch / "two", StubPath(scratch / "bin-two"), plan), plan)
    (two.rec / "zones").write_text("xx-drive-9a\nxx-drive-9b\n")
    assert two.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, two.out
    assert shards_per_zone(two) == round_robin(boxes.boxes, 2)


def test_no_zones_is_exit_2_before_any_box(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    (bw.rec / "zones.rc").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "could not read the zones" in bw.out
    assert rec_lines(bw, "up.calls") == []
    assert count_lines(bw.ledger) == 0
    assert_mac_measured_nothing(bw)

    (scratch / "bin-empty").mkdir()
    empty = box_world(World.make(scratch / "empty", StubPath(scratch / "bin-empty"), plan), plan)
    (empty.rec / "zones").write_text("")
    assert empty.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, empty.out
    assert "could not read the zones" in empty.out
    assert rec_lines(empty, "up.calls") == []
    assert count_lines(empty.ledger) == 0


def another(scratch: Path, plan: Plan, name: str, **kw: str | None) -> World:
    """A second box world in the same case: its own scratch root and its own stub PATH."""
    (scratch / f"bin-{name}").mkdir()
    made = World.make(scratch / name, StubPath(scratch / f"bin-{name}"), plan)
    return box_world(made, plan, **kw)


def leg_calls(world: World) -> list[str]:
    return rec_lines(world, "leg.calls")


def test_the_plan_follows_the_listing(bw: World, plan: Plan, boxes: Boxes, scratch: Path) -> None:
    extra = plan.listing.rstrip("\n") + "\nextra-unit\tnone\t0\textra-leg\n"
    (bw.rec / "listlegs.out").write_text(extra)
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert any("--unit extra-unit --log leg" in c for c in leg_calls(bw)), "no box of its own"
    victim = sum(f"--unit {boxes.victim_unit} " in c for c in leg_calls(bw))
    assert victim == boxes.victim_k - 1
    assert len(rec_lines(bw, "up.calls")) == boxes.boxes + 1

    flat = "".join(
        "\t".join([c[0], c[1], "0", *c[3:]]) + "\n" if c[0] == boxes.victim_unit else row + "\n"
        for row in plan.listing.splitlines()
        for c in [row.split("\t")]
    )
    victim_flat = another(scratch, plan, "victim-flat", listing=flat)
    assert victim_flat.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0
    calls = leg_calls(victim_flat)
    assert any(f"--unit {boxes.victim_unit} --log leg" in c for c in calls), calls
    assert sum("--shard" in c for c in calls) == boxes.boxes - (boxes.floor - 1)
    assert_mac_measured_nothing(victim_flat)

    derived = another(scratch, plan, "derived-floor", listing=extra)
    assert derived.run("--bank", "--no-fold", "--on-boxes", str(boxes.floor)) == 2
    assert f"this gate declares {boxes.floor + 1} units" in derived.out
    assert "cannot give every one of them a box" in derived.out
    assert "never typed" in derived.out
    assert rec_lines(derived, "up.calls") == []
    assert count_lines(derived.ledger) == 0

    at_floor = another(scratch, plan, "at-floor")
    assert at_floor.run("--bank", "--no-fold", "--on-boxes", str(boxes.floor)) == 0, at_floor.out
    calls = leg_calls(at_floor)
    for unit in boxes.capable:
        passes = " --passes 1" if unit == boxes.suite_unit else ""
        want = f"--unit {unit} --shard 1/1{passes} --log leg"
        assert any(want in c for c in calls), want
    assert len(rec_lines(at_floor, "up.calls")) == boxes.floor + 1
    assert count_lines(at_floor.ledger) == 1


def drawer_plant(path: Path, unit: str, needs: str) -> None:
    """One product leg with X2's header, a real file in scratch (never the checkout)."""
    path.write_text(
        "#!/usr/bin/env bash\n# >>> leg v1 >>>\n"
        f"# unit: {unit}\n# needs: {needs}\n# tier: full\n# <<< leg <<<\n"
        f'echo "{path.name}: a product\'s own leg"\nexit 0\n'
    )
    path.chmod(0o755)


def drawer_listing(drawer: Path) -> str:
    done = subprocess.run(
        ["./scripts/check.sh", "--list-legs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "DJB_LOCAL_LEGS_DIR": str(drawer)},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def drawer_legs(drawer: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """`gate_full_legs` composed under that drawer, for a world whose listing was too."""
    with monkeypatch.context() as m:
        m.setenv("DJB_LOCAL_LEGS_DIR", str(drawer))
        return ",".join(ledger.full_legs(ROOT))


def test_a_product_leg_in_the_drawer_gets_its_own_unit_and_its_own_box(
    world: World, plan: Plan, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawer, empty = scratch / "drawer-legs", scratch / "drawer-empty"
    drawer.mkdir()
    empty.mkdir()
    drawer_plant(drawer / "x.sh", "local", "none")
    base, listing = drawer_listing(empty), drawer_listing(drawer)
    units = count_lines_of(listing)
    assert units == count_lines_of(base) + 1
    assert any(r.split("\t")[0] == "local" for r in listing.splitlines())

    n = units + 3
    one = box_world(world, plan, legs=drawer_legs(drawer, monkeypatch), listing=listing)
    assert one.run("--bank", "--no-fold", "--on-boxes", str(n)) == 0, one.out
    assert count_lines(one.ledger) == 1
    assert any("--unit local --log leg" in c for c in leg_calls(one))
    assert len(rec_lines(one, "up.calls")) == n + 1
    assert len(leg_calls(one)) == n
    assert len(rec_lines(one, "down.calls")) == n + 1
    assert_mac_measured_nothing(one)

    assert units - 1 >= push.ON_BOXES_FLOOR, "the derived floor has no room to be asserted here"
    legs = drawer_legs(drawer, monkeypatch)
    short = another(scratch, plan, "drawer-floor", legs=legs, listing=listing)
    assert short.run("--bank", "--no-fold", "--on-boxes", str(units - 1)) == 2
    assert f"this gate declares {units} units" in short.out
    assert "never typed" in short.out
    assert rec_lines(short, "up.calls") == []
    assert count_lines(short.ledger) == 0

    drawer_plant(drawer / "y.sh", "frontend", "node")
    listing = drawer_listing(drawer)
    units = count_lines_of(listing)
    assert units == count_lines_of(base) + 2
    two = another(
        scratch, plan, "drawer-two", legs=drawer_legs(drawer, monkeypatch), listing=listing
    )
    assert two.run("--bank", "--no-fold", "--on-boxes", str(units + 3)) == 0, two.out
    assert count_lines(two.ledger) == 1
    for want in ("--unit local --log leg", "--unit frontend --log leg"):
        assert any(want in c for c in leg_calls(two)), want
    assert len(rec_lines(two, "up.calls")) == units + 4
    assert "local:x" in two.ledger.read_text()
    assert "local:y" in two.ledger.read_text()
    assert_mac_measured_nothing(two)


def count_lines_of(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


# --- --on-boxes class 2: shards and boxes -------------------------------------------------------

CHECKOUT = "/home/verifier/src"


def test_every_shard_gets_its_own_box_and_the_seams_argv(bw: World, boxes: Boxes) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert len(rec_lines(bw, "up.calls")) == boxes.boxes + 1
    assert len(leg_calls(bw)) == boxes.boxes
    assert len(rec_lines(bw, "wait.calls")) == boxes.boxes
    assert len(rec_lines(bw, "run.calls")) == 2, "the acceptance measurement and one image build"
    assert len(rec_lines(bw, "image.calls")) == 1
    assert len(rec_lines(bw, "fetch.calls")) == boxes.boxes * 2 + 4
    tree8 = bw.tree()[:8]
    ups = "\n".join(rec_lines(bw, "up.calls"))
    calls = leg_calls(bw)
    for label in boxes.labels:
        assert f"bank-{tree8}-{label}" in ups, label
        sharded = re.fullmatch(r"(.*)-([0-9]+)of([0-9]+)", label)
        if sharded:
            unit, k, of = sharded.groups()
            passes = " --passes 1" if unit == boxes.suite_unit else ""
            want = f"--unit {unit} --shard {k}/{of}{passes} --log leg"
        else:
            want = f"--unit {label} --log leg"
        assert any(want in c for c in calls), want
    ids = sorted(c.split("\t")[0] for c in calls)
    assert ids == sorted(set(ids)), "a box was handed two legs"
    assert_mac_measured_nothing(bw)


def test_a_detach_that_ssh_refused_is_retried_once(bw: World, boxes: Boxes) -> None:
    (bw.rec / f"leg.rc.{boxes.victim}.1").write_text("255\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert len(leg_calls(bw)) == boxes.boxes + 1
    for said in ("exited 255", boxes.victim, "retrying the detach"):
        assert said in bw.out, said
    assert count_lines(bw.ledger) == 1
    assert_mac_measured_nothing(bw)


def test_a_detach_that_failed_for_anything_else_is_not_retried(bw: World, boxes: Boxes) -> None:
    (bw.rec / f"leg.rc.{boxes.victim}").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert len(leg_calls(bw)) == boxes.boxes
    assert f"a unit could not be detached: {boxes.victim}" in bw.out
    assert "retrying the detach" not in bw.out
    assert count_lines(bw.ledger) == 0
    assert_mac_measured_nothing(bw)


def with_frontend(world: World, *, lock: bool = True) -> None:
    (world.repo / "frontend").mkdir()
    (world.repo / "frontend" / "package.json").write_text(
        '{"name": "drive-frontend", "private": true}\n'
    )
    paths = ["frontend/package.json"]
    if lock:
        (world.repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
        paths.append("frontend/pnpm-lock.yaml")
    _git(world.repo, "add", *paths)
    _git(world.repo, "commit", "-q", "-m", "a tree with a frontend")


def test_every_shard_installs_the_frontend_before_its_unit(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert "no frontend/ on this tree — no shard installs a frontend toolchain." in bw.out
    assert rec_lines(bw, "fe.calls") == []

    fe = another(scratch, plan, "fe-present")
    with_frontend(fe)
    assert fe.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, fe.out
    lines = fe.out.splitlines()
    planned = next(i for i, ln in enumerate(lines) if "every shard, before its unit" in ln)
    assert "every shard, before its unit: frontend/ installed on its box" in lines[planned]
    up = next(i for i, ln in enumerate(lines) if re.search(r"bringing .* boxes up", ln))
    assert planned < up
    installs = rec_lines(fe, "fe.calls")
    assert len(installs) == boxes.boxes
    line = f"cd {CHECKOUT} && bash -c '. ./scripts/fe_gate.sh && fe_leg_frozen_lockfile frontend'"
    assert sum(line in c for c in rec_lines(fe, "run.calls")) == boxes.boxes
    vb = rec_lines(fe, "vb.calls")
    for label in boxes.labels:
        box = next((c.split("\t")[0] for c in installs if c.split("\t")[1] == label), "")
        assert box, f"{label}: its box installed nothing"
        fe_at = next(i for i, c in enumerate(vb) if c.startswith(f"run {box} ") and "fe_leg" in c)
        leg_at = next(i for i, c in enumerate(vb) if c.startswith(f"leg {box} "))
        assert fe_at < leg_at, f"{label}: not installed before its unit"
    rows = [r.split("\t") for r in plan.listing.splitlines()]
    fe_units = [r[0] for r in rows if len(r) > 3 and "gate-tests" in r[3].split(",")]
    assert fe_units, "no unit in this tree's listing composes gate-tests"
    for unit in fe_units:
        mine = [lb for lb in boxes.labels if lb == unit or lb.startswith(f"{unit}-")]
        assert mine, f"the plan gave {unit} no shard"
        for label in mine:
            assert any(c.split("\t")[1] == label for c in installs), label
    assert count_lines(fe.ledger) == 1
    assert_mac_measured_nothing(fe)

    retry = another(scratch, plan, "fe-255")
    with_frontend(retry, lock=False)
    (retry.rec / f"fe.rc.{boxes.victim}.1").write_text("255\n")
    (retry.rec / f"fe.rc.{boxes.victim}.2").write_text("1\n")
    assert retry.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, retry.out
    assert f"{boxes.victim}: the frontend install exited 255" in retry.out
    assert "retrying the frontend install, once." in retry.out
    assert f"{boxes.victim}: frontend install exited 1" in retry.out
    assert len(rec_lines(retry, "fe.calls")) == boxes.boxes + 1
    assert len(leg_calls(retry)) == boxes.boxes
    assert count_lines(retry.ledger) == 1
    assert_mac_measured_nothing(retry)


def boxledger_rows(world: World, label: str, tree: str) -> str:
    """Two drive rows this box banked at the bank's tree."""
    rows = (
        f"v1 drive-v1:aaaa{label} drive 2026-09-18T00:00:00Z selftest exit=0 took=3 tree={tree}"
        " parts=scripts/tests/test_a.sh\n"
        f"v1 drive-v1:bbbb{label} drive 2026-09-18T00:00:01Z sweep exit=0 took=4 tree={tree}"
        " parts=scripts/tests/test_b.sh\n"
    )
    (world.rec / f"boxledger.{label}").write_text(rows)
    return rows


def drive_rows(world: World) -> int:
    return len(world.rows("drive"))


def test_drive_rows_already_home_are_not_appended_twice(bw: World, boxes: Boxes) -> None:
    bw.ledger.write_text(boxledger_rows(bw, boxes.victim, bw.tree()))
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert drive_rows(bw) == 2
    assert "drive rows: 0 brought home" in bw.out
    assert "(2 already here)" in bw.out
    assert_mac_measured_nothing(bw)


def test_the_shard_table_names_the_market_each_box_is_on(bw: World, boxes: Boxes) -> None:
    flat1, flat2 = boxes.indiv[0], boxes.indiv[1]
    (bw.rec / f"up.market.{flat1}").write_text("on-demand\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert re.search(r"^  shard .*market", bw.out, re.M), "the table has no market column"
    assert re.search(rf"^  {re.escape(flat1)} .*on-demand", bw.out, re.M)
    assert re.search(rf"^  {re.escape(flat2)} .*spot", bw.out, re.M)
    assert_mac_measured_nothing(bw)


def test_a_homing_a_reclaim_ate_is_lost_per_box_and_counted(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    flat1, flat2 = boxes.indiv[0], boxes.indiv[1]
    (bw.rec / f"harvest.rc.{flat1}").write_text("255\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert count_lines(bw.ledger) == 1, "a lost homing decides nothing"
    assert (
        f"drive rows from {flat1}: LOST (instance-terminated-no-capacity: not enough capacity)"
        " — the next bank re-drives them" in bw.out
    )
    assert f"drive rows homed: {boxes.boxes - 1}/{boxes.boxes} boxes" in bw.out

    failed = another(scratch, plan, "homing-failed")
    (failed.rec / f"harvest.rc.{flat2}").write_text("1\n")
    assert failed.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, failed.out
    assert f"drive rows homed: {boxes.boxes - 1}/{boxes.boxes} boxes" in failed.out

    every = another(scratch, plan, "homing-all")
    assert every.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, every.out
    assert f"drive rows homed: {boxes.boxes}/{boxes.boxes} boxes" in every.out
    assert ": LOST (" not in every.out


# --- --on-boxes class 3: the composition ---------------------------------------------------------

RECLAIMED = (
    "box reclaimed (spot) i-000 status instance-terminated-no-capacity: not enough capacity\n"
)


def ups_of(world: World, label: str) -> list[list[str]]:
    return [u.split("\t") for u in rec_lines(world, "up.calls") if u.split("\t")[0] == label]


def start(world: World, *argv: str) -> tuple[subprocess.Popen[bytes], Path]:
    """`pm_push <argv>` as the module in the background: the process and its log."""
    world.runs += 1
    sink = world.root / f"push-{world.runs}.log"
    with sink.open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "quality.djb.rituals.push", *argv],
            cwd=world.repo,
            env=world.env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    return proc, sink


def until(check: object, seconds: float = 60.0) -> bool:
    """Poll `check()` every 0.2 s for at most `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():  # type: ignore[operator]
            return True
        time.sleep(0.2)
    return False


def test_one_red_shard_is_exit_1_and_no_row(bw: World, boxes: Boxes) -> None:
    (bw.rec / f"box.rc.{boxes.victim}").write_text("1\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, bw.out
    k = boxes.victim_k
    for said in ("the gate is RED", boxes.victim, f"--leg {boxes.victim_unit} --shard {k}/{k}"):
        assert said in bw.out, said
    assert count_lines(bw.ledger) == 0
    assert "shard" in bw.out
    assert boxes.shards_of(boxes.suite_unit)[0] in bw.out
    assert_mac_measured_nothing(bw)


def test_a_missing_or_exit_2_shard_is_exit_2(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    flat1, flat2 = boxes.indiv[0], boxes.indiv[1]
    (bw.rec / f"box.rc.{flat1}").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "the shard exited 2" in bw.out
    assert flat1 in bw.out
    assert count_lines(bw.ledger) == 0
    assert_mac_measured_nothing(bw)

    norc = another(scratch, plan, "no-rc")
    (norc.rec / f"norc.{flat2}").write_text("")
    assert norc.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, norc.out
    assert "no exit status came back from the box" in norc.out
    assert count_lines(norc.ledger) == 0

    absent = another(scratch, plan, "absent")
    (absent.rec / f"absent.{boxes.victim_first}").write_text("")
    assert absent.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, absent.out
    assert "no log came back from the box" in absent.out
    assert count_lines(absent.ledger) == 0
    assert_mac_measured_nothing(absent)


def test_a_reclaimed_shard_is_retried_once_on_a_fresh_box_in_the_next_zone(
    bw: World, boxes: Boxes
) -> None:
    last = boxes.shards_of(boxes.suite_unit)[-1]
    (bw.rec / f"wait.out.{last}.1").write_text(RECLAIMED)
    (bw.rec / f"box.rc.{last}.1").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert count_lines(bw.ledger) == 1
    assert "was RECLAIMED" in bw.out
    assert "retried-from i-" in bw.out
    assert "the verdict is LOST, never red" not in bw.out
    assert "the gate is RED" not in bw.out
    mine = ups_of(bw, last)
    assert len(mine) == 2
    assert mine[0][2] != mine[1][2], f"the retry went back into {mine[0][2]}"
    assert len(rec_lines(bw, "up.calls")) == boxes.boxes + 2
    assert len(leg_calls(bw)) == boxes.boxes + 1
    downs = rec_lines(bw, "down.calls")
    assert len(downs) == boxes.boxes + 2
    assert len(set(downs)) == len(downs), "a box was taken down twice"
    assert_mac_measured_nothing(bw)


def test_a_finished_shards_log_is_fetched_before_the_slowest_shard_returns(
    bw: World, boxes: Boxes
) -> None:
    flat1 = boxes.indiv[0]
    (bw.rec / f"wait.block.{boxes.victim}").write_text("")
    proc, sink = start(bw, "--bank", "--no-fold", "--on-boxes", str(boxes.boxes))
    early = until(lambda: any(f"{flat1}/leg.rc" in c for c in rec_lines(bw, "fetch.calls")))
    (bw.rec / "release-wait").write_text("")
    assert proc.wait(timeout=300) == 0, sink.read_text()
    assert early, "nothing was fetched until every wait had returned"
    assert count_lines(bw.ledger) == 1
    assert sum("proof.txt" in c for c in rec_lines(bw, "fetch.calls")) == 1
    assert_mac_measured_nothing(bw)


def test_a_shard_reclaimed_twice_is_lost_never_red(bw: World, boxes: Boxes) -> None:
    last = boxes.shards_of(boxes.suite_unit)[-1]
    (bw.rec / f"wait.out.{last}").write_text(RECLAIMED)
    (bw.rec / f"box.rc.{last}").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "RECLAIMED mid-flight" in bw.out
    assert "the verdict is LOST, never red" in bw.out
    assert "the gate is RED" not in bw.out
    assert count_lines(bw.ledger) == 0
    assert len(ups_of(bw, last)) == 2
    assert_mac_measured_nothing(bw)


def test_a_retry_box_that_will_not_come_up_is_lost(bw: World, boxes: Boxes) -> None:
    last = boxes.shards_of(boxes.suite_unit)[-1]
    (bw.rec / f"wait.out.{last}.1").write_text(RECLAIMED)
    (bw.rec / f"box.rc.{last}.1").write_text("2\n")
    (bw.rec / f"up.rc.{last}.2").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "the second box did not come up either" in bw.out
    assert "the verdict is LOST, never red" in bw.out
    assert "the gate is RED" not in bw.out
    assert count_lines(bw.ledger) == 0
    assert len(ups_of(bw, last)) == 2
    assert_mac_measured_nothing(bw)


def test_a_reclaimed_acceptance_box_is_retried_once(bw: World, boxes: Boxes) -> None:
    (bw.rec / "accept.proof.reclaimed").write_text("")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert count_lines(bw.ledger) == 1
    assert "was RECLAIMED" in bw.out
    assert "retried-from i-" in bw.out
    assert "the leak proof could not be read" not in bw.out
    assert len(ups_of(bw, "acceptance")) == 2
    assert len(rec_lines(bw, "up.calls")) == boxes.boxes + 2
    assert len(rec_lines(bw, "down.calls")) == boxes.boxes + 2
    assert_mac_measured_nothing(bw)


def test_a_foreign_tree_on_a_box_is_exit_2_naming_both(bw: World, boxes: Boxes) -> None:
    foreign = "dead0000" * 5
    (bw.rec / f"box.tree.{boxes.victim}").write_text(f"{foreign}\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    for said in ("a box measured a DIFFERENT tree", foreign, bw.tree()):
        assert said in bw.out, said
    assert count_lines(bw.ledger) == 0
    assert_mac_measured_nothing(bw)


def test_legs_that_do_not_add_up_are_exit_2_naming_the_leg(
    bw: World, plan: Plan, boxes: Boxes
) -> None:
    members = {r.split("\t")[0]: r.split("\t")[3] for r in plan.listing.splitlines() if r}
    unit = next((u for u in boxes.indiv if "," in members[u]), "")
    assert unit, "no unsharded unit in the listing has two members — nothing to drop one from"
    kept, dropped = members[unit].rsplit(",", 1)
    (bw.rec / f"box.legs.{unit}").write_text(f"{kept}\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "do not add up to a full gate" in bw.out
    assert dropped in bw.out
    assert count_lines(bw.ledger) == 0
    assert_mac_measured_nothing(bw)


def test_a_red_shard_names_its_first_failing_test(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    first = boxes.shards_of(boxes.suite_unit)[0]
    (bw.rec / f"box.rc.{first}").write_text("1\n")
    (bw.rec / f"box.faillog.{first}").write_text(
        "Using --randomly-seed=424242\n"
        "=========================== short test summary info ============================\n"
        "FAILED apps/connections/tests/test_relay.py::test_at_least_once - TimeoutError\n"
    )
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, bw.out
    assert count_lines(bw.ledger) == 0
    assert "the gate is RED" in bw.out
    node = "apps/connections/tests/test_relay.py::test_at_least_once"
    assert (
        f"first failing: {node} ({first}; 1 FAILED) - replay: ./scripts/test.sh -n 16"
        f" --randomly-seed=424242 {node}" in bw.out
    )
    assert_mac_measured_nothing(bw)

    flat = another(scratch, plan, "red-flat")
    (flat.rec / f"box.rc.{boxes.indiv[0]}").write_text("1\n")
    assert flat.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, flat.out
    assert "the gate is RED" in flat.out
    assert "first failing:" not in flat.out


def test_a_red_log_with_no_failed_line_says_none_named(bw: World, boxes: Boxes) -> None:
    (bw.rec / "accept.proof").write_text("seed=8675309 workers=16 pass1=0 pass2=1 map=0\n")
    (bw.rec / "accept.pass2").write_text(
        "Using --randomly-seed=8675309\nINTERNALERROR> RuntimeError: the worker crashed\n"
    )
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, bw.out
    assert count_lines(bw.ledger) == 0
    assert "the leak proof is RED" in bw.out
    assert "first failing: none named - no FAILED line in" in bw.out
    assert "/pass2.log" in bw.out
    assert "replay: ./scripts/test.sh" not in bw.out
    assert_mac_measured_nothing(bw)


# --- --on-boxes class 4: the row and the hook ----------------------------------------------------


def refs(world: World) -> str:
    return f"refs/heads/main {world.head()} refs/heads/main {ZERO}\n"


def test_the_composed_row_has_the_grammar_and_one_writer(
    bw: World, plan: Plan, boxes: Boxes
) -> None:
    suite = boxes.shards_of(boxes.suite_unit)
    (bw.rec / f"box.wall.{suite[0]}").write_text("90\n")
    (bw.rec / f"box.wall.{suite[-1]}").write_text("140\n")
    (bw.rec / f"box.wall.{boxes.victim_first}").write_text("900\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    (row,) = bw.ledger.read_text().splitlines()
    grammar = (
        r"v1 [0-9a-f]{40} full [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
        r" [a-z0-9,:/_-]+ caller=pm-bank"
        rf" sanction=push-wall:pm_push:boxes={boxes.boxes}%20shards=[A-Za-z0-9,.:_-]+"
        r" waited=0 took=[0-9]+ leak-proof=acceptance:i-[0-9a-f]+ rc=0"
    )
    assert re.fullmatch(grammar, row), row
    words = row.split()
    assert words[1] == bw.tree()
    onepass = [f"{leg}/1" if leg == "pytest-x2" else leg for leg in plan.legs.split(",")]
    assert words[4] == ",".join(onepass)
    assert "took=140" in words, "took= is the slowest pytest shard, not the slowest shard"
    last = re.escape(suite[-1])
    table = rf"^  {last} +i-[0-9]+ +(spot|on-demand|-) +[a-z0-9-]+ +1 +0 +140s +[0-9a-f]{{40}}$"
    assert re.search(table, bw.out, re.M), "the table does not carry the shard's own row"
    flat = re.escape(boxes.indiv[0])
    assert re.search(rf"^  {flat} +i-[0-9]+ +(spot|on-demand|-) +[a-z0-9-]+ +- +0 ", bw.out, re.M)
    assert f"shards={','.join(boxes.labels)}" in row
    looked = subprocess.run(
        ["bash", "-c", '. scripts/gate_ledger.sh && gate_ledger_lookup "$1"', "_", bw.tree()],
        cwd=bw.repo,
        env=bw.env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert looked.stdout.strip() == row
    assert_mac_measured_nothing(bw)


def test_the_hook_honours_a_composed_row(bw: World, boxes: Boxes) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    (bw.rec / "gate.calls").write_text("")
    said = bw.hook(refs(bw))
    assert "is measured green by a full gate run — verdict honoured" in said, said
    assert count_lines(bw.rec / "gate.calls") == 0


def test_a_short_legs_field_is_not_honoured(bw: World, boxes: Boxes) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    words = bw.ledger.read_text().split()
    words[4] = "ruff,mypy"
    bw.ledger.write_text(" ".join(words) + "\n")
    (bw.rec / "gate.calls").write_text("")
    said = bw.hook(refs(bw))
    assert "not honoured — measuring" in said, said
    assert "verdict honoured" not in said


def test_the_consult_honours_one_green_whole_record_of_this_tree_and_measures_everything_else(
    world: World, plan: Plan, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha, tree = world.head(), world.tree()
    monkeypatch.setenv("PATH", world.stubs.path)
    monkeypatch.setenv("TMPDIR", str(world.root / "tmp"))

    def consulted(at: str, want: str, *, setup: object = None) -> None:
        shutil.rmtree(world.gh)
        world.gh.mkdir()
        if setup is not None:
            setup()  # type: ignore[operator]
        line, run = ledger.ci_consult(world.repo, at)
        assert want in line, (want, line)
        assert (run == RUN) == want.startswith("consult: honoured"), line

    def record(
        head: str, rc: int, attempt: int, scope: str = "whole", at: str = "", lane: str = ""
    ) -> object:
        def plant() -> None:
            (world.gh / f"runs-{head}.out").write_text(f"{RUN}\n")
            gh_run(world, RUN, "completed", attempt)
            gh_record(world, RUN, attempt, ci_rec(plan, head, tree, rc, 1, scope, at=at, lane=lane))

        return plant

    honoured = f"consult: honoured run={RUN} attempt=1 tree={tree}"
    consulted(sha, honoured, setup=record(sha, 0, 1))
    consulted(sha, honoured, setup=record(sha, 0, 1, lane="full"))
    consulted(
        sha,
        f"consult: measure — run {RUN} ran the loop lane — only the full lane vouches for a tree",
        setup=record(sha, 0, 1, "pr", lane="loop"),
    )
    stale = stamp_from_now(-172800)
    consulted(
        sha,
        f"consult: measure — run {RUN}'s record is OLDER THAN 24 h",
        setup=record(sha, 0, 1, at=stale),
    )
    consulted(
        sha, f"consult: measure — run {RUN} ran NARROWED (scope=pr)", setup=record(sha, 0, 1, "pr")
    )
    consulted(sha, f"consult: measure — run {RUN} attempt 1 is RED (rc=1)", setup=record(sha, 1, 1))
    consulted(sha, f"consult: measure — run {RUN}'s latest attempt is 2", setup=record(sha, 0, 2))
    consulted(sha, "consult: measure — no candidate")
    consulted(
        sha,
        "consult: measure — could not look (",
        setup=lambda: (world.gh / "api.rc").write_text(""),
    )
    world.stubs.remove("gh")
    with monkeypatch.context() as m:
        m.setenv("PATH", world.stubs.path)
        consulted(sha, "consult: measure — could not look (no `gh` on PATH)")
    world.stubs.plant("gh", FAKE_GH.replace("__GH__", str(world.gh)))

    _git(world.repo, "switch", "-q", "main")
    _git(world.repo, "merge", "-q", "--no-ff", "-m", "the pull request, merged", "pm/train")
    merge = world.head()

    def via_pull() -> None:
        (world.gh / "pulls.out").write_text(f"{sha}\n")
        record(sha, 0, 1)()  # type: ignore[operator]

    consulted(merge, honoured, setup=via_pull)

    def via_pull_still_deploying() -> None:
        via_pull()
        (world.gh / f"view-{RUN}").write_text("in_progress 1 completed\n")

    consulted(merge, honoured, setup=via_pull_still_deploying)

    def docs_commit(name: str) -> str:
        (world.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (world.repo / name).write_text("a ledger line\n")
        _git(world.repo, "add", name)
        _git(world.repo, "commit", "-q", "-m", f"ledger: {name}")
        return world.head()

    def via_docs_road(at: str) -> tuple[str, str]:
        shutil.rmtree(world.gh)
        world.gh.mkdir()
        via_pull()
        return ledger.ci_consult(world.repo, at, docs_road=True)

    once = docs_commit("docs" + "/ledger-a.md")
    twice = docs_commit("docs" + "/ledger-b.md")
    mine = world.tree()
    line, run = via_docs_road(twice)
    assert (line, run) == (
        f"consult: honoured run={RUN} attempt=1 docs-only-since={tree} tree={mine}",
        RUN,
    ), (once, line)
    assert ledger.ci_consult(world.repo, twice)[1] == "", "the road is the push consult's alone"
    (world.repo / "code.py").write_text("x = 1\n")
    _git(world.repo, "add", "code.py")
    _git(world.repo, "commit", "-q", "-m", "code")
    line, run = via_docs_road(world.head())
    assert run == "" and line.startswith("consult: measure — "), line
    _git(world.repo, "reset", "-q", "--hard", merge)
    (world.repo / "moved.txt").write_text("moved\n")
    _git(world.repo, "add", "moved.txt")
    _git(world.repo, "commit", "-q", "-m", "main moved")
    consulted(
        world.head(),
        f"consult: measure — run {RUN} measured tree {tree[:12]} and this checkout measures",
        setup=via_pull,
    )


# --- CI-THIRD-1: the pull request's own consult, over a fold-only delta ---------------------------

PR = "7"


@dataclass
class PrConsult:
    world: World
    plan: Plan
    measured: str
    folded: str

    def tree_of(self, rev: str) -> str:
        return _git(self.world.repo, "rev-parse", f"{rev}^{{tree}}")

    def plant(
        self,
        *,
        prs: str = PR,
        commits: tuple[str, ...] = (),
        rc: int = 0,
        scope: str = "whole",
        lane: str = "",
        at: str = "",
    ) -> None:
        gh = self.world.gh
        shutil.rmtree(gh)
        gh.mkdir()
        (gh / f"runs-{self.measured}.out").write_text(f"{RUN}\n")
        (gh / f"prs-{RUN}").write_text(f"{prs}\n")
        (gh / "pr-commits.out").write_text(
            "\n".join(commits or (self.measured, self.folded)) + "\n"
        )
        gh_run(self.world, RUN, "completed", 1)
        tree = self.tree_of(self.measured)
        rec = ci_rec(self.plan, self.measured, tree, rc, 1, scope, lane=lane, at=at)
        gh_record(self.world, RUN, 1, rec)

    def consult(self, at: str = "") -> tuple[str, str]:
        return ledger.ci_consult(self.world.repo, at or self.folded, docs_road=True, pr=PR)


@pytest.fixture
def pr_consult(world: World, plan: Plan, monkeypatch: pytest.MonkeyPatch) -> PrConsult:
    monkeypatch.setenv("PATH", world.stubs.path)
    monkeypatch.setenv("TMPDIR", str(world.root / "tmp"))
    repo = world.repo
    (repo / ".secrets.baseline").write_text('{\n  "version": "1.5.0",\n  "results": {}\n}\n')
    _git(repo, "add", ".secrets.baseline")
    _git(repo, "commit", "-q", "-m", "the train, measured")
    measured = world.head()
    (repo / ".secrets.baseline").write_text(
        '{\n  "version": "1.5.0",\n  "generated_at": "2026-10-24T00:00:00Z",\n  "results": {}\n}\n'
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "ledger.md").write_text("a ledger line\n")
    _git(repo, "add", ".secrets.baseline", "docs" + "/ledger.md")
    _git(repo, "commit", "-q", "-m", "fold: baseline shifted")
    return PrConsult(world, plan, measured, world.head())


def test_a_pull_request_run_honours_its_own_earlier_measure_over_a_fold_only_delta(
    pr_consult: PrConsult,
) -> None:
    c = pr_consult
    c.plant()
    since, mine = c.tree_of(c.measured), c.tree_of(c.folded)
    honoured = f"consult: honoured run={RUN} attempt=1 docs-only-since={since} tree={mine}"
    assert c.consult() == (honoured, RUN)
    calls = (c.world.gh / "calls").read_text()
    assert f"pulls/{PR}/commits" in calls and "/commits/" not in calls.replace(
        f"pulls/{PR}/commits", ""
    ), "the PR consult asks this PR's commits, never which pull requests carry a commit"
    (c.world.repo / "code.py").write_text("x = 1\n")
    _git(c.world.repo, "add", "code.py")
    _git(c.world.repo, "commit", "-q", "-m", "code")
    c.plant(commits=(c.measured, c.folded, c.world.head()))
    line, run = c.consult(c.world.head())
    assert run == "" and line.startswith("consult: measure — "), line
    _git(c.world.repo, "reset", "-q", "--hard", c.folded)
    (c.world.repo / "untracked.py").write_text("y = 2\n")
    c.plant()
    line, run = c.consult()
    assert run == "" and "main moved under pull request #7" in line, line
    (c.world.repo / "untracked.py").unlink()
    assert ledger.ci_consult(c.world.repo, c.folded, docs_road=True, pr="x7")[0].endswith(
        "got 'x7')"
    )


def test_the_pr_consult_never_honours_another_pull_requests_run(pr_consult: PrConsult) -> None:
    c = pr_consult
    c.plant(prs="8")
    line, run = c.consult()
    assert run == "" and line.startswith("consult: measure — "), line
    c.plant(prs="8,9")
    assert c.consult()[1] == ""
    c.plant(commits=(c.folded,))
    line, run = c.consult()
    assert run == "" and line.startswith("consult: measure — "), line
    c.plant(commits=(c.measured,))
    line, run = c.consult()
    assert run == "" and f"{c.folded[:12]} is not a commit of pull request #7" in line, line
    c.plant(prs="17")
    assert c.consult()[1] == "", "#17 is not #7"
    c.plant(prs="8,7")
    assert c.consult()[1] == RUN


@pytest.mark.parametrize(
    "record",
    [
        pytest.param({"rc": 1}, id="red"),
        pytest.param({"scope": "pr"}, id="narrowed"),
        pytest.param({"scope": "pr", "lane": "loop"}, id="loop-lane"),
        pytest.param({"lane": "docs"}, id="docs-lane"),
        pytest.param({"at": "old"}, id="older-than-24h"),
    ],
)
def test_a_red_or_narrowed_earlier_pr_run_is_never_honoured(
    pr_consult: PrConsult, record: dict[str, object]
) -> None:
    c = pr_consult
    at = stamp_from_now(-172800) if record.get("at") == "old" else ""
    scope, lane = str(record.get("scope", "whole")), str(record.get("lane", ""))
    c.plant(rc=int(str(record.get("rc", 0))), scope=scope, lane=lane, at=at)
    line, run = c.consult()
    assert run == "" and line.startswith("consult: measure — "), line


def test_main_honours_a_pull_request_head_its_own_run_honoured(pr_consult: PrConsult) -> None:
    c = pr_consult
    c.plant()
    (c.world.gh / "pulls.out").write_text(f"{c.folded}\n")
    _git(c.world.repo, "switch", "-q", "main")
    _git(c.world.repo, "merge", "-q", "--no-ff", "-m", "the pull request, merged", "pm/train")
    merge, since = c.world.head(), c.tree_of(c.measured)
    line, run = ledger.ci_consult(c.world.repo, merge, docs_road=True)
    assert (line, run) == (
        f"consult: honoured run={RUN} attempt=1 docs-only-since={since} tree={c.tree_of(merge)}",
        RUN,
    )
    assert ledger.ci_consult(c.world.repo, merge)[1] == "", "the head road is the docs road's"


# --- --on-boxes class 5: the teardown ------------------------------------------------------------


def bank_sinks(world: World) -> list[Path]:
    return sorted((world.root / "tmp").glob("djb-bank-boxes.*"))


def boxes_in_flight(world: World) -> int:
    return sum(count_lines(s / "boxes.tsv") for s in bank_sinks(world))


def test_every_launched_box_is_taken_down_on_green_red_and_kill(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    downs = rec_lines(bw, "down.calls")
    assert len(downs) == boxes.boxes + 1
    assert len(set(downs)) == len(downs), "a box was taken down twice"

    red = another(scratch, plan, "down-red")
    (red.rec / f"box.rc.{boxes.indiv[0]}").write_text("1\n")
    assert red.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, red.out
    assert len(rec_lines(red, "down.calls")) == boxes.boxes + 1

    kill = another(scratch, plan, "down-kill")
    (kill.rec / "up.allow").write_text("\n".join(boxes.labels[:3]) + "\n")
    proc, sink = start(kill, "--bank", "--no-fold", "--on-boxes", str(boxes.boxes))
    if not until(lambda: boxes_in_flight(kill) >= 3, 30):
        (kill.rec / "release").write_text("")
        proc.wait(timeout=120)
        pytest.fail("three boxes never reached the bank's own census — nothing to interrupt")
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=120) == 143, sink.read_text()
    # THE CHILDREN WENT WITH IT: an `up` still blocked would answer the release below.
    (kill.rec / "release").write_text("")
    time.sleep(1.5)
    said = sink.read_text()
    assert len(rec_lines(kill, "down.calls")) == 3
    assert "the bank stopped (exit 143) with boxes still up" in said
    assert count_lines(kill.ledger) == 0
    survivors = [
        log.name
        for s in bank_sinks(kill)
        for log in s.glob("up-*.log")
        if "released without launching" in log.read_text(errors="replace")
    ]
    assert survivors == [], f"the signalled bank left its children running: {survivors}"

    bare = another(scratch, plan, "down-no-pgrep")
    bare.stubs.hide("pgrep")
    assert bare.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bare.out
    assert "teardown: children not read — no pgrep" in bare.out, bare.out
    assert len(rec_lines(bare, "down.calls")) == boxes.boxes + 1, "the teardown was skipped"


def test_a_box_whose_up_failed_after_the_launch_is_still_taken_down(
    bw: World, boxes: Boxes
) -> None:
    (bw.rec / f"up.launched_then_rc.{boxes.victim}").write_text("2\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert f"a box did not come up: {boxes.victim}" in bw.out
    assert count_lines(bw.ledger) == 0
    logs = [s / f"up-{boxes.victim}.log" for s in bank_sinks(bw)]
    launched = [
        ln.split()[1]
        for log in logs
        if log.is_file()
        for ln in log.read_text().splitlines()
        if ln.startswith("launched")
    ]
    assert launched, "the stub's up printed no launched line — nothing to assert"
    assert launched[0] in rec_lines(bw, "down.calls"), f"{launched[0]} was never taken down"
    assert_mac_measured_nothing(bw)


def test_a_failed_down_names_the_hand_and_keeps_the_status(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    (bw.rec / "down.fail").write_text("")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    for said in (
        "IT IS STILL UP",
        "scripts/verifier_box.sh down",
        "scripts/verifier_box.sh census",
    ):
        assert said in bw.out, said
    assert count_lines(bw.ledger) == 1, "the verdict was still banked"
    assert "pm_push: pushing" not in bw.out

    red = another(scratch, plan, "down-fail-red")
    (red.rec / "down.fail").write_text("")
    (red.rec / f"box.rc.{boxes.victim_first}").write_text("1\n")
    assert red.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, red.out
    assert "IT IS STILL UP" in red.out
    assert count_lines(red.ledger) == 0


# --- --on-boxes class 6: the acceptance box and the leak proof -----------------------------------

COULD_NOT_READ = (
    "the leak proof could not be read — one pass was measured and nothing proved it left"
    " nothing behind"
)


def map_tree(world: World) -> str:
    import json

    doc = json.loads((world.repo / "scripts" / "test_impact.json").read_text())
    return str(doc["generated"]["tree"])


def without_bake(world: World) -> None:
    _git(world.repo, "rm", "-q", "deploy/verifier/bake.sh")
    _git(world.repo, "commit", "-q", "-m", "a checkout with no bake.sh to read")


def test_the_acceptance_box_is_outside_the_verdict(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    n = str(boxes.boxes)
    (bw.rec / "accept.rc").write_text("1\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", n) == 0, bw.out
    assert count_lines(bw.ledger) == 1
    assert "acceptance: map NOT written (exit 1) — the loop keeps the closure scope" in bw.out
    legs_red = bw.ledger.read_text().split()[4]
    assert not any("test_impact.json" in c for c in rec_lines(bw, "fetch.calls"))
    assert_mac_measured_nothing(bw)

    green = another(scratch, plan, "acc-rc0")
    assert green.run("--bank", "--no-fold", "--on-boxes", n) == 0, green.out
    assert count_lines(green.ledger) == 1
    assert "acceptance: scripts/test_impact.json rewritten" in green.out
    assert "tree:beefcafe1234" in green.out
    assert map_tree(green) == "tree:beefcafe1234"
    assert green.ledger.read_text().split()[4] == legs_red
    assert_mac_measured_nothing(green)

    argv = another(scratch, plan, "acc-argv")
    assert argv.run("--bank", "--no-fold", "--on-boxes", n) == 0, argv.out
    assert f"bank-{argv.tree()[:8]}-acceptance" in "\n".join(rec_lines(argv, "up.calls"))
    runs = "\n".join(rec_lines(argv, "run.calls"))
    assert "./scripts/pm_push.sh --proof --where acceptance" in runs
    assert CHECKOUT in runs
    assert "acceptance" not in "\n".join(leg_calls(argv))
    assert "test_impact.json" in "\n".join(rec_lines(argv, "fetch.calls"))

    nobake = another(scratch, plan, "acc-no-checkout")
    without_bake(nobake)
    assert nobake.run("--bank", "--no-fold", "--on-boxes", n) == 0, nobake.out
    assert count_lines(nobake.ledger) == 1
    assert "acceptance: no box" in nobake.out
    assert "a box did not come up" not in nobake.out
    assert "--passes" not in nobake.out
    assert "--passes" not in "\n".join(leg_calls(nobake))
    row = nobake.ledger.read_text()
    assert "leak-proof=" not in row
    assert f" {plan.legs} " in row, "the two-pass row's legs field is not FULL_LEGS"
    assert_mac_measured_nothing(nobake)

    nobox = another(scratch, plan, "acc-planned-no-box")
    (nobox.rec / "up.rc.acceptance").write_text("2\n")
    assert nobox.run("--bank", "--no-fold", "--on-boxes", n) == 2, nobox.out
    assert count_lines(nobox.ledger) == 0
    for said in (COULD_NOT_READ, "NO ROW WAS", "this bank will be"):
        assert said in nobox.out, said
    assert (
        "REFUSED — one pass was measured and nothing can prove it left nothing behind" in nobox.out
    )
    assert "every shard is unaffected" not in nobox.out
    assert_mac_measured_nothing(nobox)


def test_the_plan_hands_passes_1_only_when_a_proof_box_exists(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    n = str(boxes.boxes)
    suite, k = boxes.suite_unit, len(boxes.shards_of(boxes.suite_unit))
    assert bw.run("--bank", "--no-fold", "--on-boxes", n) == 0, bw.out
    calls = leg_calls(bw)
    one = re.compile(rf"--unit {re.escape(suite)} --shard [0-9]+/[0-9]+ --passes 1 --log leg")
    assert sum(bool(one.search(c)) for c in calls) == k
    assert sum("--passes" in c for c in calls) == k
    assert f"--leg {suite} --shard 1/{k} --passes 1" in bw.out
    assert "ONE pass per suite shard" in bw.out
    if boxes.victim_unit != suite:
        assert f"--leg {boxes.victim_unit} --shard 1/{boxes.victim_k} --passes" not in bw.out
    assert_mac_measured_nothing(bw)

    moved_rows = []
    for row in plan.listing.splitlines():
        c = row.split("\t")
        if c[0] == "pytest-x2":
            c[3] = "temporal-census,partition,own-tree-census"
        elif c[0] == "selftest":
            c[3] = f"{c[3]},pytest-x2"
        moved_rows.append("\t".join(c))
    moved = another(scratch, plan, "passes-follow", listing="\n".join(moved_rows) + "\n")
    moved.run("--bank", "--no-fold", "--on-boxes", n)
    moved_calls = "\n".join(leg_calls(moved))
    victim = rf"--unit {re.escape(boxes.victim_unit)} --shard [0-9]+/[0-9]+ --passes 1 --log leg"
    assert re.search(victim, moved_calls), "the pass count did not follow the suite leg to its unit"
    assert f"--unit {suite} --shard 1/{k} --passes 1" not in moved_calls

    nobake = another(scratch, plan, "passes-no-proof-box")
    without_bake(nobake)
    assert nobake.run("--bank", "--no-fold", "--on-boxes", n) == 0, nobake.out
    assert not any("--passes" in c for c in leg_calls(nobake))
    assert count_lines(nobake.ledger) == 1

    disagree = another(scratch, plan, "passes-disagree")
    members = {r.split("\t")[0]: r.split("\t")[3] for r in plan.listing.splitlines() if r}
    last = boxes.shards_of(suite)[-1]
    (disagree.rec / f"box.legs.{last}").write_text(members[suite] + "\n")
    assert disagree.run("--bank", "--no-fold", "--on-boxes", n) == 2, disagree.out
    assert "the plan and the unit listing disagree" in disagree.out
    assert f"{suite}: planned --passes 1 and the shard reports pytest-x2" in disagree.out
    assert count_lines(disagree.ledger) == 0
    assert_mac_measured_nothing(disagree)


def test_the_acceptance_command_mints_one_seed_and_writes_a_proof(bw: World, boxes: Boxes) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    cmd = "\n".join(c for c in rec_lines(bw, "run.calls") if "--proof" in c)
    assert cmd, "no acceptance command was recorded at all"
    assert "./scripts/pm_push.sh --proof --where acceptance --workers 16 --out $HOME/verify/" in cmd
    assert "test_impact.py write" not in cmd
    assert "--randomly-seed=" not in cmd
    assert 'r=$?; [ "${r}" != 1 ] || r=0; exit ${r}' in cmd
    assert CHECKOUT in cmd


def test_the_leak_proof_is_composed_and_the_map_is_not(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    n = str(boxes.boxes)
    (bw.rec / "accept.proof").write_text("seed=8675309 workers=16 pass1=0 pass2=1 map=0\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", n) == 1, bw.out
    assert count_lines(bw.ledger) == 0
    for said in ("the gate is RED", "the leak proof is RED", "pass1=0 pass2=1", "acceptance.log"):
        assert said in bw.out, said
    assert_mac_measured_nothing(bw)

    def proof(name: str, line: str | None, rc: int, *, absent: str = "") -> World:
        w = another(scratch, plan, name)
        if line is not None:
            (w.rec / "accept.proof").write_text(line + "\n")
        if absent:
            (w.rec / absent).write_text("")
        assert w.run("--bank", "--no-fold", "--on-boxes", n) == rc, w.out
        return w

    p1 = proof("proof-pass1-red", "seed=8675309 workers=16 pass1=1 pass2=0 map=2", 1)
    assert count_lines(p1.ledger) == 0
    assert "the leak proof is RED" in p1.out
    gone = proof("proof-absent", None, 2, absent="accept.proof.absent")
    assert count_lines(gone.ledger) == 0
    assert COULD_NOT_READ in gone.out
    assert "fetch-proof.log" in gone.out
    assert_mac_measured_nothing(gone)
    for name, line in (
        ("proof-unparsable", "workers=16 pass1=0 pass2=0 map=0"),
        ("proof-rc-nan", "seed=8675309 workers=16 pass1=0 pass2=ok map=0"),
    ):
        bad = proof(name, line, 2)
        assert count_lines(bad.ledger) == 0
        assert COULD_NOT_READ in bad.out
    died = proof(
        "proof-map-died",
        "seed=8675309 workers=16 pass1=0 pass2=0 map=1",
        0,
        absent="accept.map.absent",
    )
    assert count_lines(died.ledger) == 1
    assert "acceptance: map NOT written (the box's map writer exited 1)" in died.out
    assert "the box said 0 and no file came back" not in died.out
    assert "the leak proof — seed=8675309" in died.out
    assert "map= is a measurement and decides nothing" in died.out
    assert "leak-proof=acceptance:" in died.ledger.read_text()
    assert_mac_measured_nothing(died)
    green = proof("proof-green", None, 0)
    assert count_lines(green.ledger) == 1
    assert "scripts/test_impact.json rewritten" in green.out
    assert "pass1=0 pass2=0" in green.out
    assert map_tree(green) == "tree:beefcafe1234"
    assert_mac_measured_nothing(green)
    fetched = [c.split("\t")[2] for c in rec_lines(green, "fetch.calls") if "proof.txt" in c]
    assert fetched and fetched[0].endswith("/acceptance.proof"), fetched


def test_a_red_leak_proof_names_the_first_failing_test_and_the_replay(
    bw: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    (bw.rec / "accept.proof").write_text("seed=8675309 workers=16 pass1=0 pass2=1 map=0\n")
    (bw.rec / "accept.pass2").write_text(
        "Using --randomly-seed=8675309\n"
        "=========================== short test summary info ============================\n"
        "FAILED apps/example/tests/test_doors.py::test_rest_and_mcp_agree - AssertionEr...\n"
        "FAILED apps/core/tests/test_audit.py::test_append_only - assert 1 == 2\n"
    )
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, bw.out
    assert count_lines(bw.ledger) == 0
    assert "the leak proof is RED" in bw.out
    node = "apps/example/tests/test_doors.py::test_rest_and_mcp_agree"
    assert (
        f"first failing: {node} (pass 2; 2 FAILED) - replay: ./scripts/test.sh -n 16"
        f" --randomly-seed=8675309 {node}" in bw.out
    )
    assert sum(bool(re.search(r"pass[12]\.log", c)) for c in rec_lines(bw, "fetch.calls")) == 2
    assert_mac_measured_nothing(bw)

    green = another(scratch, plan, "green-pass-logs")
    assert green.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, green.out
    assert sum(bool(re.search(r"pass[12]\.log", c)) for c in rec_lines(green, "fetch.calls")) == 2
    assert "first failing:" not in green.out


def test_the_composed_row_carries_the_proof_and_the_hook_reads_it(bw: World, boxes: Boxes) -> None:
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    (row,) = bw.ledger.read_text().splitlines()
    assert re.search(r" leak-proof=acceptance:i-[0-9a-f]+ rc=0$", row), row
    aid = next(
        (f.name.removeprefix("label-of.") for f in bw.rec.glob("label-of.*")
         if f.read_text().strip() == "acceptance"),
        "",
    )  # fmt: skip
    assert aid, "no acceptance box id was recorded at all"
    assert f" leak-proof=acceptance:{aid} rc=0" in row
    assert re.search(r" waited=0 took=[0-9]+ leak-proof=", row), row
    (bw.rec / "gate.calls").write_text("")
    said = bw.hook(refs(bw))
    assert "is measured green by a full gate run — verdict honoured" in said, said
    assert count_lines(bw.rec / "gate.calls") == 0
    bw.ledger.write_text(row.removesuffix(" rc=0") + " rc=1\n")
    said = bw.hook(refs(bw))
    assert "the row ran ONE pass and carries no green leak proof" in said, said
    assert "Not honoured — measuring" in said
    assert "verdict honoured" not in said


def test_the_map_lands_in_the_tree_uncommitted(bw: World, boxes: Boxes) -> None:
    before = bw.head()
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert bw.head() == before, "the bank committed something"
    assert _git(bw.repo, "status", "--porcelain", "--", "scripts/test_impact.json")
    assert "git add scripts/test_impact.json" in bw.out
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 2, bw.out
    assert "has uncommitted changes" in bw.out
    assert "scripts/test_impact.json" in bw.out
    assert count_lines(bw.ledger) == 1
    assert map_tree(bw) == "tree:beefcafe1234"


def test_the_acceptance_map_never_dirties_the_box(bw: World, boxes: Boxes) -> None:
    tag = f"tree-{bw.tree()[:12]}"
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    outs = re.findall(r"--out ([^ ;]*)", "\n".join(rec_lines(bw, "run.calls")))
    assert outs and outs[0].startswith(("/", "$HOME/", "${HOME}/")), outs
    assert count_lines(bw.rec / "box.dirty") == 0, "the acceptance run left the box's tree dirty"
    assert "refusing to build under" not in bw.out
    assert "image: NOT built" not in bw.out
    assert f"image: {tag} pushed (web 39s, worker 41s)" in bw.out
    assert "acceptance: scripts/test_impact.json rewritten from" in bw.out
    assert_mac_measured_nothing(bw)


# --- --on-boxes class 7: --leak-proof nightly ----------------------------------------------------

NIGHTLY_RUN = "555"
ONLY_ON_BOXES = "--leak-proof is only meaningful with --bank --on-boxes N"


def nightly_plant(world: World, form: str) -> None:
    """The latest nightly as the fake `gh` serves it."""
    shutil.rmtree(world.gh)
    world.gh.mkdir()
    if form == "none":
        (world.gh / "list.out").write_text("")
        return
    if form == "fail":
        (world.gh / "list.rc").write_text("1\n")
        return
    (world.gh / "list.out").write_text(f"{NIGHTLY_RUN}\n")
    gh_run(world, NIGHTLY_RUN, "completed", 1)
    if form == "noart":
        return
    at = stamp_from_now(-172800 if form == "stale" else -3600)
    rc = "1" if form == "red" else "0"
    tree = world.tree()
    if form == "foreign":
        tree = _git(world.repo, "hash-object", "-t", "tree", "/dev/null")
    art = world.gh / f"art-{NIGHTLY_RUN}" / "nightly-leak-proof"
    art.mkdir(parents=True)
    line = ledger.nightly_line(
        [at, world.head(), tree, "99", "0", rc, "0", rc, NIGHTLY_RUN, "1", "nightly"]
    )
    (art / ledger.NIGHTLY_RECORD).write_text(line + "\n")
    (art / "test_impact.json").write_text('{"generated": {}, "tests": {}, "unmapped": {}}\n')


def test_leak_proof_nightly_reads_the_night_and_launches_no_box(
    world: World, plan: Plan, boxes: Boxes, scratch: Path
) -> None:
    n = str(boxes.boxes)
    empty = ""
    for form in ("green", "foreign", "red", "stale", "none", "noart", "fail"):
        w = box_world(world, plan) if form == "green" else another(scratch, plan, f"night-{form}")
        nightly_plant(w, form)
        tree = w.tree()
        empty = _git(w.repo, "hash-object", "-t", "tree", "/dev/null")
        assert w.run("--bank", "--no-fold", "--on-boxes", n, "--leak-proof", "nightly") == 0, w.out
        sources = re.findall(r"^(leak-proof: nightly |WARNING: leak-proof: )", w.out, re.M)
        assert len(sources) == 1, (form, sources)
        run = f"run {NIGHTLY_RUN}"
        said, want = {
            "green": (
                f"leak-proof: nightly {run} attempt 1 green — nightly:",
                rf"nightly:[0-9]{{8}}T[0-9]{{6}}Z tree={tree[:12]} rc=0",
            ),
            "foreign": (
                f" tree={empty[:12]} rc=0 (measured {empty[:12]}, not this bank's {tree[:12]}:"
                " report-only)",
                rf"nightly:[0-9]{{8}}T[0-9]{{6}}Z tree={empty[:12]} rc=0",
            ),
            "red": (
                f"WARNING: leak-proof: the latest nightly ({run}, attempt 1) is RED (rc=1)",
                rf"nightly:[0-9]{{8}}T[0-9]{{6}}Z tree={tree[:12]} rc=1",
            ),
            "stale": (
                f"WARNING: leak-proof: the latest nightly ({run}, attempt 1) is older than 24 h",
                r"nightly:stale:[0-9]{8}T[0-9]{6}Z",
            ),
            "none": (
                "WARNING: leak-proof: no nightly leak proof (no completed nightly-proof.yml run"
                " on main)",
                "nightly:none",
            ),
            "noart": (
                f"WARNING: leak-proof: no nightly leak proof (nightly {run} (attempt 1) carries no"
                " nightly-leak-proof artifact)",
                "nightly:none",
            ),
            "fail": ("WARNING: leak-proof: no nightly leak proof (could not look:", "nightly:none"),
        }[form]
        assert said in w.out, (form, said)
        if form == "green":
            assert "not this bank's" not in w.out
        assert not ups_of(w, "acceptance"), form
        assert len(rec_lines(w, "up.calls")) == boxes.boxes
        assert not any("--proof" in c for c in rec_lines(w, "run.calls"))
        assert "acceptance: no box — --leak-proof nightly" in w.out
        (row,) = w.rows("full")
        assert re.search(rf" leak-proof={want}$", row), (form, row)
        assert "pytest-x2/1" in row.split()[4].split(",")
        looked = subprocess.run(
            ["bash", "-c", '. scripts/gate_ledger.sh && gate_ledger_lookup "$1"', "_", tree],
            cwd=w.repo,
            env=w.env(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert looked.stdout.strip() == row, form
        assert_mac_measured_nothing(w)

    refusals = another(scratch, plan, "night-refusals")
    for argv, said in (
        (("--bank", "--no-fold", "--leak-proof", "nightly"), ONLY_ON_BOXES),
        (("--leak-proof", "nightly"), ONLY_ON_BOXES),
        (("--bank", "--no-fold", "--on-boxes", n, "--leak-proof", "tuesday"),
         "--leak-proof takes nightly or acceptance, got 'tuesday'"),
        (("--bank", "--no-fold", "--on-boxes", n, "--leak-proof"), "--leak-proof takes a source"),
    ):  # fmt: skip
        assert refusals.run(*argv) == 2, refusals.out
        assert said in refusals.out, said
    assert rec_lines(refusals, "up.calls") == []
    assert refusals.rows("full") == []

    acc = another(scratch, plan, "night-acceptance")
    assert acc.run("--bank", "--no-fold", "--on-boxes", n, "--leak-proof", "acceptance") == 0
    assert len(ups_of(acc, "acceptance")) == 1
    assert not re.search(r"^(leak-proof: nightly |WARNING: leak-proof: )", acc.out, re.M)
    assert "leak-proof=acceptance:" in acc.ledger.read_text()


def test_a_pass_2_only_red_names_candidate_causes_never_one(bw: World, boxes: Boxes) -> None:
    fields_ = [stamp_from_now(-60), bw.head(), bw.tree(), "8675309", "0", "1", "0", "1", "0", "0"]
    (bw.rec / "accept.proof").write_text(ledger.nightly_line([*fields_, "acceptance"]) + "\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 1, bw.out
    assert count_lines(bw.ledger) == 0
    assert (
        "pass 2 red after a green pass 1 — candidate causes: state pass 1 left behind, the wall"
        " clock, test order; replay: ./scripts/pm_push.sh --proof --seed 8675309 --workers 16"
        in bw.out
    )
    assert "and nothing else" not in bw.out
    assert "a red pass 2 is state pass 1 left behind" not in bw.out
    assert_mac_measured_nothing(bw)


# --- --on-boxes class 8: the image ---------------------------------------------------------------

REG = "000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens"


def test_the_image_is_built_after_the_row_and_never_on_a_red(bw: World, boxes: Boxes) -> None:
    tag = f"tree-{bw.tree()[:12]}"
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    calls = rec_lines(bw, "image.calls")
    assert len(calls) == 1, "one image build, never one per shard"
    for asked in (
        f"docker build --target web --tag {REG}/djb-web:{tag}",
        f"docker build --target worker --tag {REG}/djb-worker:{tag}",
        f"docker push {REG}/djb-web:{tag}",
        f"docker push {REG}/djb-worker:{tag}",
        "aws ecr get-login-password --region us-east-1",
        "./deploy/provision.sh image-tag",
        "docker logout 000000000000.dkr.ecr.us-east-1.amazonaws.com",
    ):
        assert asked in calls[0], asked
    assert count_lines(bw.rec / "ledger.at.image") == 1, "the build started before the row"
    assert count_lines(bw.ledger) == 1
    assert f"image: {tag} pushed (web 39s, worker 41s)" in bw.out
    assert "image: web sha256:0aa1 worker sha256:0bb2" in bw.out
    assert_mac_measured_nothing(bw)


def test_a_failed_push_is_printed_and_the_row_still_stands(bw: World, boxes: Boxes) -> None:
    (bw.rec / "image.out").write_text(
        "Login Succeeded\ndenied: User is not authorized to perform ecr:InitiateLayerUpload\n"
    )
    (bw.rec / "image.rc").write_text("1\n")
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert count_lines(bw.ledger) == 1
    for said in (
        "image: NOT built (exit 1)",
        "ecr:InitiateLayerUpload",
        "CI's images job builds a tag",
    ):
        assert said in bw.out, said
    assert len(rec_lines(bw, "down.calls")) == boxes.boxes + 1
    assert_mac_measured_nothing(bw)


def test_no_registry_coordinate_is_printed_and_nothing_is_built(bw: World, boxes: Boxes) -> None:
    (bw.rec / "registry").unlink()
    assert bw.run("--bank", "--no-fold", "--on-boxes", str(boxes.boxes)) == 0, bw.out
    assert count_lines(bw.ledger) == 1
    assert rec_lines(bw, "image.calls") == []
    assert "image: not built — no registry coordinate" in bw.out
    assert_mac_measured_nothing(bw)


CI_SKIP_STEP = "is this tag already in the registry"


def ci_step_body(name: str) -> str:
    """The `run: |` block of ci.yml's step `name`, dedented."""
    lines = (ROOT / ".github" / "workflows" / "ci.yml").read_text().splitlines()
    body: list[str] = []
    instep = inrun = False
    for line in lines:
        if line == f"      - name: {name}":
            instep = True
            continue
        if instep and line.startswith("      - "):
            break
        if instep and line.startswith("        run: |"):
            inrun = True
            continue
        if inrun and re.match(r"^        [^ ]", line):
            break
        if inrun:
            body.append(line.removeprefix("          "))
    return "\n".join(body)


@pytest.mark.drives(".github/workflows/ci.yml")
def test_ci_skips_a_present_tag_and_builds_an_absent_one(scratch: Path) -> None:
    body = ci_step_body(CI_SKIP_STEP)
    assert body, f"there is no '{CI_SKIP_STEP}' step with a run: block in ci.yml"

    def ci(rcweb: int, rcworker: int) -> tuple[subprocess.CompletedProcess[str], str]:
        world = scratch / f"ci-{rcweb}-{rcworker}"
        (world / "deploy").mkdir(parents=True)
        stub = world / "deploy" / "provision.sh"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            '[ "${1:-}" = image-services ] && { echo "web worker frontend"; exit 0; }\n'
            f'case "${{2:-}}" in\nweb) rc={rcweb}; dg=sha256:0aa1 ;;\n'
            f"worker) rc={rcworker}; dg=sha256:0bb2 ;;\n"
            "frontend) rc=0; dg=sha256:0cc3 ;;\n"
            '*) echo "stub provision: no such service" >&2; exit 2 ;;\nesac\n'
            '[ "$rc" = "0" ] || exit "$rc"\nprintf "%s\\n" "$dg"\n'
        )
        stub.chmod(0o755)
        (world / "body.sh").write_text(body + "\n")
        (world / "github_output").write_text("")
        env = {
            **os.environ,
            "TAG": "tree-0123456789ab",
            "REGISTRY": REG,
            "PUSH": "true",
            "GITHUB_OUTPUT": str(world / "github_output"),
        }
        done = subprocess.run(
            ["bash", str(world / "body.sh")],
            cwd=world,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, (world / "github_output").read_text()

    done, said = ci(0, 0)
    assert done.returncode == 0, done.stderr
    assert (
        "::notice::tree-0123456789ab already in the registry — skipped" in done.stdout + done.stderr
    )
    assert "have=true" in said.splitlines()
    done, said = ci(0, 2)
    assert done.returncode == 0, done.stderr
    assert "already in the registry" not in done.stdout + done.stderr
    assert "worker is NOT in the registry" in done.stdout + done.stderr
    assert "have=false" in said.splitlines()
    cond = ""
    for line in (ROOT / ".github" / "workflows" / "ci.yml").read_text().splitlines():
        if line.startswith("      - "):
            cond = ""
        if line.startswith("        if: "):
            cond = line
        if re.match(r"^ +docker buildx build ", line):
            break
    assert "steps.have.outputs.have != 'true'" in cond, "buildx is not conditioned on the answer"


def _modes_the_parser_yields() -> set[str]:
    """Every literal `_mode` assigns to `args.mode`; the empty default is `parse`'s refusal."""
    tree = ast.parse((ROOT / "quality/djb/rituals/push.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            pairs: list[tuple[ast.expr, ast.expr]] = [(target, node.value)]
            if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                pairs = list(zip(target.elts, node.value.elts, strict=True))
            for left, right in pairs:
                if isinstance(left, ast.Attribute) and left.attr == "mode":
                    if isinstance(right, ast.Constant) and isinstance(right.value, str):
                        found.add(right.value)
    return found


def test_every_mode_the_parser_yields_reaches_its_own_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    def arm(name: str) -> Callable[..., int]:
        def record(*_: object, **kw: object) -> int:
            ran.append(f"{name}{'-dry' if kw.get('dry_run') else ''}")
            return 0

        return record

    for name in ("pr", "ci_verdict", "bank", "proof"):
        monkeypatch.setattr(push, name, arm(name))
    monkeypatch.setattr(push, "_root", lambda: ROOT)
    monkeypatch.setattr(push, "head", lambda root, rev="HEAD": ZERO)
    monkeypatch.setattr(push, "pm_push_worktree", lambda root: ROOT)
    reached: dict[str, str] = {}
    parse = push.parse
    for mode in sorted(_modes_the_parser_yields()):
        ran.clear()
        monkeypatch.setattr(push, "parse", lambda argv, mode=mode: push.Args(mode=mode))
        assert push.run([]) == 0
        reached[mode] = ran[0] if ran else "usage"
    assert reached == {
        "bank": "bank",
        "ci-verdict": "ci_verdict",
        "help": "usage",
        "pr": "pr",
        "proof": "proof",
    }, reached
    assert push.Args().mode == ""
    with pytest.raises(Died) as refused:
        parse([])
    assert "the pin-and-push road to main is retired" in refused.value.headline
