"""`scripts/ledger_derive.py`: a scratch repository's briefs, reports and a `gh` stub, derived."""

# does-not-cover: the real `gh` — the stub answers the two calls the reader makes, as recorded.
# does-not-cover: the live repository's table — the builder's report pastes that run.

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives("quality/tests/fixtures/ledger_derive/", "scripts/ledger_derive.py")

ROOT = Path(__file__).resolve().parents[2]
DERIVE = ROOT / "scripts/ledger_derive.py"
RECORDED = ROOT / "quality/tests/fixtures/ledger_derive/table.md"
BRIEFS = "docs/product/briefs"
REPORTS = "docs/product/reports/p26"
PLAN = "docs" + "/product/cycles/2026-10-20-fx.md"
LIVE = "docs" + "/product/in-flight.md"
DAY = "2026-10-20"
AFTER_ARMING = "2026-10-26"
GH_STUB = """#!/bin/sh
case "$1 $2" in
"pr list") cat "$(dirname "$0")/list.json" ;;
"pr view") cat "$(dirname "$0")/view-$3.json" ;;
*) exit 1 ;;
esac
"""


def _brief(rung: str, task: str, block: str) -> str:
    return f"# {rung} — {task}\n\n```\n{block}```\n\nThe brief's body.\n"


@dataclass
class Repo:
    """A scratch repository on `main` that commits on a fixed PDT clock."""

    dir: Path
    run: Callable[..., Captured]
    bin: Path
    merge: str = ""

    def git(self, *argv: str, when: str = f"{DAY} 08:00") -> str:
        stamp = f"{when.replace(' ', 'T')}:00-07:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        done = subprocess.run(
            ["git", *argv], cwd=self.dir, env=env, capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    def commit(self, when: str, files: dict[str, str], message: str = "a commit") -> str:
        for rel, text in files.items():
            path = self.dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            self.git("add", rel)
        self.git("commit", "-q", "-m", message, when=when)
        return self.git("rev-parse", "HEAD")

    def derive(self, *args: str) -> tuple[int, str]:
        argv = [sys.executable, str(DERIVE), "--gh", str(self.bin / "gh"), *args]
        done = self.run(argv, cwd=self.dir)
        return done.rc, done.text()

    def answer_gh(self, merge: str) -> None:
        self.bin.mkdir(exist_ok=True)
        (self.bin / "gh").write_text(GH_STUB)
        (self.bin / "gh").chmod(0o755)
        pulls = [
            {
                "number": 7,
                "state": "MERGED",
                "headRefName": "pm/fx-build",
                "mergedAt": f"{DAY}T19:00:00Z",
                "mergeCommit": {"oid": merge},
                "updatedAt": f"{DAY}T19:00:00Z",
            }
        ]
        (self.bin / "list.json").write_text(json.dumps(pulls))


@pytest.fixture
def repo(
    scratch_repo: Callable[..., Path], capture: Callable[..., Captured], scratch: Path
) -> Repo:
    """A builder dispatched, returned, merged and landed; its verifier; a sent lead; a reap."""
    world = Repo(scratch_repo(), capture, scratch / "bin")
    world.commit(
        f"{DAY} 09:00",
        {
            f"{BRIEFS}/fx-build.md": _brief(
                "FX-BUILD", "the built thing", "role: builder\nbranch: pm/fx-build\n"
            ),
            LIVE: "FX-BUILD sent\n",
        },
        "ledger: FX-BUILD dispatched",
    )
    world.git("checkout", "-q", "-b", "pm/fx-build")
    world.commit(f"{DAY} 09:30", {"thing.py": "x = 1\n"})
    world.commit(
        f"{DAY} 10:00", {f"{REPORTS}/fx-build.md": "done, stopping — the thing is built\n\nmore\n"}
    )
    world.git("checkout", "-q", "main")
    world.commit(
        f"{DAY} 10:30",
        {
            f"{BRIEFS}/v-fx-build.md": _brief(
                "V-FX-BUILD", "verify FX-BUILD", "role: verifier\nverifies: FX-BUILD\n"
            )
        },
    )
    world.commit(f"{DAY} 10:45", {LIVE: "FX-BUILD returned\n"}, "ledger: FX-BUILD returned")
    world.commit(f"{DAY} 11:00", {f"{REPORTS}/v-fx-build.md": "# VERIFIED — every criterion met\n"})
    world.git(
        "merge", "-q", "--no-ff", "-m", "Merge pull request #7", "pm/fx-build", when=f"{DAY} 12:00"
    )
    world.git("branch", "-q", "-D", "pm/fx-build")
    world.merge = world.git("rev-parse", "HEAD")
    world.commit(f"{DAY} 12:30", {LIVE: "struck\n"}, "ledger: the train landed (#7)")
    world.commit(f"{DAY} 12:45", {LIVE: "reaped\n"}, "ledger: the worktrees reaped")
    plan = PLAN
    world.commit(
        f"{DAY} 13:00",
        {
            f"{BRIEFS}/lead-fx.md": _brief(
                "LEAD-FX", "decompose the fx goal", f"role: lead\nreport: {plan}\n"
            )
        },
    )
    world.answer_gh(world.merge)
    return world


def _recorded(repo: Repo) -> str:
    return RECORDED.read_text().replace("<MERGE8>", repo.merge[:8])


def test_fixture_repo_derives_the_recorded_table(repo: Repo) -> None:
    rc, out = repo.derive()
    assert rc == 0, out
    assert out == _recorded(repo), out
    sent = repo.git(
        "log",
        "--diff-filter=A",
        "--format=%cd",
        "--date=format:%H:%M",
        "--",
        f"{BRIEFS}/fx-build.md",
    )
    assert f"| {DAY} {sent} |" in out


@pytest.fixture
def lm() -> ModuleType:
    """`scripts/loop_metrics.py`, imported — the stamps grammar's one reader, never a copy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module("loop_metrics")
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_stamps_round_trip_through_loop_metrics(repo: Repo, scratch: Path, lm: ModuleType) -> None:
    rc, out = repo.derive("--stamps")
    assert rc == 0, out
    table = scratch / "derived.md"
    table.write_text(out)
    rows = lm.read_rows(str(table))
    assert [r.ident for r in rows] == ["FX-BUILD", "V-FX-BUILD", "LEAD-FX"], out
    for row in rows:
        lm.parse_stamps(row)
        assert row.stamped, row.text
    built = rows[0]
    assert str(built.stamps["met"]) == f"{DAY} 11:00:00", built.text
    assert built.merged_sha == repo.merge[:8]
    assert built.commits is not None and str(built.commits[0]) == f"{DAY} 09:30:00", built.text


def test_a_brief_with_no_block_is_exit_2(repo: Repo) -> None:
    repo.commit(f"{AFTER_ARMING} 09:00", {f"{BRIEFS}/fx-bare.md": "# FX-BARE — no block\n\nbody\n"})
    rc, out = repo.derive()
    assert rc == 2, out
    assert f"{BRIEFS}/fx-bare.md: no header block" in out and "| FX-BUILD" not in out, out
    rc, out = repo.derive("--check")
    assert rc == 2 and f"{BRIEFS}/fx-bare.md: no header block" in out, out


def test_a_brief_sent_before_arming_is_read_by_inference(repo: Repo) -> None:
    repo.commit(
        f"{DAY} 14:00",
        {f"{BRIEFS}/fx-old.md": "# FX-OLD — an old one (builder; branch `pm/fx-old`)\n\nbody\n"},
    )
    rc, out = repo.derive("--json")
    assert rc == 0, out
    old = [row for row in json.loads(out) if row["rung"] == "FX-OLD"]
    assert old and old[0]["role"] == "builder" and old[0]["state"] == "sent", out


def test_an_orphan_report_is_exit_1(repo: Repo) -> None:
    rc, out = repo.derive("--check")
    assert rc == 0 and "== ledger-derive --check: clean · 3 brief(s) read" in out, out
    repo.commit(f"{AFTER_ARMING} 09:00", {f"{REPORTS}/fx-stray.md": "a report nobody asked for\n"})
    rc, out = repo.derive("--check")
    assert rc == 1, out
    assert f"!! ledger-derive: {REPORTS}/fx-stray.md: an orphan report — no brief names it" in out


def test_check_names_a_report_outside_and_a_branch_with_no_pm_prefix(repo: Repo) -> None:
    repo.commit(
        f"{AFTER_ARMING} 09:00",
        {
            f"{BRIEFS}/fx-odd.md": _brief(
                "FX-ODD", "odd", "role: builder\nbranch: fx-odd\nreport: notes/fx-odd.md\n"
            )
        },
    )
    rc, out = repo.derive("--check")
    assert rc == 1, out
    assert f"{BRIEFS}/fx-odd.md: `report: notes/fx-odd.md` is outside reports/ and cycles/" in out
    assert f"{BRIEFS}/fx-odd.md: `branch: fx-odd` has no `pm/` prefix" in out


def test_offline_prints_could_not_look_per_row_and_exits_2(repo: Repo) -> None:
    rc, out = repo.derive("--offline")
    assert rc == 2, out
    assert "| FX-BUILD | the built thing | builder | returned · pr: could not look |" in out, out
    assert "| V-FX-BUILD | verify FX-BUILD | verifier | returned |" in out, out


def test_a_refusing_gh_is_exit_2_and_no_partial_table(repo: Repo) -> None:
    (repo.bin / "list.json").unlink()
    rc, out = repo.derive()
    assert rc == 2 and "COULD NOT LOOK" in out and "| FX-BUILD" not in out, out


def test_a_sent_brief_older_than_the_window_prints_stale(repo: Repo) -> None:
    rc, out = repo.derive("--stale", "--hours", "3")
    assert rc == 1, out
    assert "stale: LEAD-FX sent 2026-10-20 13:00, no report, no PR activity in 3 h" in out
    assert "a stall is the agent list's to confirm" in out and "FX-BUILD" not in out, out
    repo.commit(f"{DAY} 15:00", {PLAN: "# the fx plan\n"})
    rc, out = repo.derive("--stale", "--hours", "3")
    assert rc == 0 and "== ledger-derive --stale: 0 row(s) past 3 h" in out, out


def test_turns_reads_the_hand_count_through_the_landing(repo: Repo) -> None:
    base = repo.git("rev-list", "--max-parents=0", "HEAD")
    rc, out = repo.derive("--turns", "--since", base)
    assert rc == 0, out
    want = f"pm-turns: 3.00 commits/landed rung over 1 rungs since {base[:8]} — goal 2: ABOVE"
    assert out.strip() == want, out
    rc, out = repo.derive("--turns", "-v", "--since", base)
    assert "FX-BUILD: 3.00 (landed)" in out and "V-FX-BUILD" not in out, out
    assert "1 ledger commit(s) with no builder rung live" in out, out


def test_turns_attributes_one_over_k_from_the_dispatch_not_the_brief(repo: Repo) -> None:
    base = repo.git("rev-list", "--max-parents=0", "HEAD")
    held = _brief("FX-HELD", "a held one", "role: builder\nbranch: pm/fx-held\n")
    repo.commit(f"{DAY} 09:15", {f"{BRIEFS}/fx-held.md": held}, "a brief written, held")
    repo.commit(f"{DAY} 11:30", {LIVE: "FX-HELD sent\n"}, "ledger: FX-HELD dispatched")
    rc, out = repo.derive("--turns", "-v", "--since", base)
    assert rc == 0, out
    assert "FX-BUILD: 3.00 (landed)" in out and "FX-HELD: 2.00 (live)" in out, out
    rc, out = repo.derive("--json")
    held_row = [row for row in json.loads(out) if row["rung"] == "FX-HELD"]
    assert held_row and held_row[0]["sent"] == f"{DAY} 11:30", out


def test_a_pre_block_reader_brief_finds_its_report_by_the_path_it_names(repo: Repo) -> None:
    lens = f"{REPORTS}/critique-lens-reread.md"
    text = f"# READ-9 / lens — a re-read (Fable reader; read-only)\n\nWrite `{lens}`.\n"
    repo.commit(f"{DAY} 14:00", {f"{BRIEFS}/reread-lens.md": text})
    repo.commit(f"{DAY} 14:30", {lens: "cut the tag\n"})
    rc, out = repo.derive("--json")
    row = [r for r in json.loads(out) if r["rung"] == "READ-9/lens"]
    assert row and (row[0]["role"], row[0]["state"]) == ("reader", "returned"), out
    assert row[0]["result"] == "cut the tag", out


@pytest.fixture
def published(
    scratch_repo: Callable[..., Path], capture: Callable[..., Captured], scratch: Path
) -> Repo:
    """The published tree: manifest R8 trims `docs/product/reports/**`; R8S ships 3 files back."""
    world = Repo(scratch_repo("published"), capture, scratch / "bin")
    world.commit(
        f"{AFTER_ARMING} 09:00",
        {
            f"{BRIEFS}/README.md": "# Briefs\n\nOne per dispatch.\n",
            "docs/product/cycles/README.md": "# Cycles\n",
            "docs/product/cycles/EXAMPLE-cycle-plan.md": "# EXAMPLE\n",
            LIVE: "# In flight\n",
        },
    )
    return world


NO_CYCLE = "no cycle yet: docs/product/reports/ holds no cycle directory"


def test_a_tree_with_no_reports_derives_the_header_and_says_no_cycle_yet(published: Repo) -> None:
    rc, out = published.derive()
    assert rc == 0, out
    lines = out.strip().splitlines()
    assert lines[0] == "| # | Task | Role | State | Sent | Returned | Result |", out
    assert lines[2].startswith(NO_CYCLE) and "docs/product/reports/<cycle>/" in lines[2], out
    rc, out = published.derive("--check")
    assert rc == 0 and "== ledger-derive --check: clean · 0 brief(s) read" in out, out


def test_a_reports_directory_holding_no_cycle_is_no_cycle_yet(published: Repo) -> None:
    (published.dir / "docs/product/reports").mkdir()
    rc, out = published.derive()
    assert rc == 0 and NO_CYCLE in out, out


def test_a_reports_path_that_is_a_file_is_could_not_look(published: Repo) -> None:
    published.commit(f"{AFTER_ARMING} 10:00", {"docs/product/reports": "not a directory\n"})
    rc, out = published.derive("--check")
    assert rc == 2 and "COULD NOT LOOK" in out and "is not a directory" in out, out


def test_a_brief_naming_no_report_on_a_tree_with_no_cycle_is_could_not_look(
    published: Repo,
) -> None:
    brief = _brief("FX-ONE", "the first", "role: builder\nbranch: pm/fx-one\n")
    published.commit(f"{AFTER_ARMING} 10:00", {f"{BRIEFS}/fx-one.md": brief})
    rc, out = published.derive("--check")
    assert rc == 2 and f"{BRIEFS}/fx-one.md: names no `report:`" in out, out
    named = _brief(
        "FX-ONE",
        "the first",
        "role: builder\nbranch: pm/fx-one\nreport: " + "docs" + "/product/reports/c1/fx-one.md\n",
    )
    published.commit(f"{AFTER_ARMING} 10:30", {f"{BRIEFS}/fx-one.md": named})
    rc, out = published.derive("--check")
    assert rc == 0 and "clean · 1 brief(s) read" in out, out
