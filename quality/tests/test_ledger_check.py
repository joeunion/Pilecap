"""`scripts/ledger_check.py`: a planted canary per refusal class fires; the snapshot passes."""

# does-not-cover: whether the gate registers the leg — the registry's announced sequence holds that.
# does-not-cover: whether a stamp or a verdict is true.

# names, never reads: docs/product/in-flight.md docs/product/archive/in-flight-p26.md — rule 90

# moved: test_the_real_ledger_passes_in_under_a_second — this module, renamed

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives("quality/tests/fixtures/ledger_pair/", "scripts/ledger_check.py")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts/ledger_check.py"
SNAPSHOT_LIVE = ROOT / "quality/tests/fixtures/ledger_pair/live.md"
SNAPSHOT_ARCHIVE = ROOT / "quality/tests/fixtures/ledger_pair/archive.md"
SKELETON = ROOT / "docs/product/skeletons" / "in-flight.md"
HEADER = "| # | Who | What | State | Sent | Returned | Verdict |\n|---|---|---|---|---|---|---|"
GOOD = (
    "| FX-01 | builder | a thing | returned | 2026-10-04 10:00 | 2026-10-04 11:00 | met; "
    "reports/p26/fx-01.md stamps: sent=2026-10-04 10:00 done=2026-10-04 11:00 "
    "met=2026-10-04 12:00 merged=abcdef12 2026-10-04 13:00 |"
)
STAMPS = "stamps: sent=2026-10-04 10:00 done=2026-10-04 11:00"
CLEAN = "== ledger-check: clean"
POINTER = (
    "The dispatch ledger is derived: `.venv/bin/python scripts/ledger_derive.py` "
    "(briefs → reports → pull requests)."
)


@dataclass(frozen=True)
class World:
    """A live table holding GOOD plus the planted rows, beside a one-stage archive."""

    dir: Path
    run: Callable[..., Captured]

    @property
    def live(self) -> Path:
        return self.dir / "live.md"

    @property
    def archive(self) -> Path:
        return self.dir / "archive.md"

    def plant(self, *rows: str) -> World:
        body = "".join(f"{row}\n" for row in rows)
        self.live.write_text(
            f"# In flight\n\n## Dispatch ledger\n\n{HEADER}\n{GOOD}\n{body}\n## After the table\n"
        )
        self.archive.write_text(
            f"# Archive\n\n### Train 1 rows — pruned 2026-10-03 18:55\n\n{HEADER}\n"
        )
        return self

    def archived(self, *rows: str) -> None:
        with self.archive.open("a") as archive:
            archive.writelines(f"{row}\n" for row in rows)

    def check(self, *args: str, pair: bool = True) -> tuple[int, str]:
        argv = [sys.executable, str(CHECK), "--check", *args]
        if pair:
            argv += ["--in-flight", "live.md", "--archive", "archive.md"]
        env = {k: v for k, v in os.environ.items() if k != "DJB_STAGED_ROOT"}
        done = self.run(argv, cwd=self.dir, env=env)
        return done.rc, done.text()


@pytest.fixture
def world(scratch: Path, capture: Callable[..., Captured]) -> World:
    """`world.plant(rows…)` then `world.check()` — `(exit, output)` of `--check` over the pair."""
    (scratch / "world").mkdir()
    return World(scratch / "world", capture)


def _row(row_id: str, who: str, state: str, verdict: str, what: str = "a thing") -> str:
    return f"| {row_id} | {who} | {what} | {state} | 2026-10-04 10:00 | — | {verdict} |"


def test_a_clean_ledger_is_exit_0(world: World) -> None:
    rc, out = world.plant().check()
    assert rc == 0 and CLEAN in out, out


def test_a_long_row_and_a_big_live_table_are_not_refused(world: World) -> None:
    rows = [
        GOOD.replace("FX-01 | builder | a thing", f"FX-{i} | builder | " + "v" * 1300)
        for i in range(9010, 9041)
    ]
    rc, out = world.plant(*rows).check()
    assert rc == 0 and CLEAN in out, out


def test_a_live_file_with_the_pointer_line_and_no_table_passes(world: World) -> None:
    world.plant().live.write_text(f"# In flight\n\n{POINTER}\n")
    rc, out = world.check()
    assert rc == 0 and CLEAN in out, out


def test_a_live_row_sent_since_the_table_was_derived_is_refused(world: World) -> None:
    late = "| FX-30 | builder | a thing | sent | 2026-10-25 09:00 | — | — |"
    rc, out = world.plant(late).check()
    assert rc == 1, out
    want = "live.md:3 `## Dispatch ledger`: 1 row(s) sent on or after 2026-10-25 (FX-30) — the"
    assert want + " table is derived (`scripts/ledger_derive.py`); delete it" in out, out


def _commit_after_arming(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    env = {**os.environ, "GIT_COMMITTER_DATE": "2026-10-26T09:00:00-07:00"}
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "after arming"], check=True, env=env)


def test_the_briefs_beside_the_live_file_are_judged(
    world: World, scratch_repo: Callable[..., Path]
) -> None:
    repo = scratch_repo("product")
    product = repo / "docs/product"
    (product / "briefs").mkdir(parents=True)
    (product / "reports/p26").mkdir(parents=True)
    (product / "in-flight.md").write_text(f"# In flight\n\n{POINTER}\n")
    (product / "briefs/fx-40.md").write_text("# FX-40 — a thing\n\n```\nrole: verifier\n```\n")
    (product / "reports/p26/fx-40.md").write_text("returned\n")
    _commit_after_arming(repo)
    rc, out = world.check("--in-flight", str(product / "in-flight.md"), pair=False)
    assert rc == 0 and "1 brief(s) read, 1 report(s) armed on 2026-10-25" in out, out
    stray = "docs" + "/product/reports/p26/fx-41.md"
    (repo / stray).write_text("nobody asked\n")
    _commit_after_arming(repo)
    rc, out = world.check("--in-flight", str(product / "in-flight.md"), pair=False)
    assert rc == 1 and f"!! ledger-check: {stray}: an orphan report — no brief names it" in out, out
    (product / "briefs/fx-42.md").write_text("# FX-42 — no block\n")
    _commit_after_arming(repo)
    rc, out = world.check("--in-flight", str(product / "in-flight.md"), pair=False)
    assert rc == 2 and "docs" + "/product/briefs/fx-42.md: no header block" in out, out


def test_a_returned_row_with_no_stamps_cell_is_refused(world: World) -> None:
    rc, out = world.plant(_row("FX-03", "builder", "merged", "met; reports/p26/fx-03.md")).check()
    assert rc == 1, out
    assert "FX-03 (live.md:8): returned row (state `merged`) carries no `stamps:` cell" in out


def test_an_agent_row_with_no_report_pointer_is_refused(world: World) -> None:
    rc, out = world.plant(_row("FX-04", "verifier", "returned", f"met {STAMPS}")).check()
    assert rc == 1, out
    want = "FX-04 (live.md:8): returned row (state `returned`) carries no "
    assert want + "`docs/product/reports/<cycle>/<id>.md` pointer" in out, out


def test_a_landed_pm_row_points_at_its_merge_sha_not_a_report(world: World) -> None:
    pm = f"green {STAMPS} met=2026-10-04 11:30 merged="
    rc, out = world.plant(
        _row("TRAIN-FX05", "the PM", "landed", pm + "—", "a train"),
        _row("TRAIN-FX06", "the PM", "landed", pm + "abcdef12 2026-10-04 12:00", "a train"),
    ).check()
    assert rc == 1, out
    want = "TRAIN-FX05 (live.md:8): PM row (state `landed`) carries no merge sha in its `merged=`"
    assert want in out and "TRAIN-FX06" not in out, out


def test_a_lead_row_points_at_its_plan_not_a_report(world: World) -> None:
    lead = "engineering lead"
    rc, out = world.plant(
        _row(
            "LEAD-FX07",
            lead,
            "merged",
            "ruled; cycles/2026-10-04-cycle-fx.md stamps: commits=- fold=-",
            "a plan",
        ),  # noqa: E501
        _row("LEAD-FX08", lead, "merged", "ruled stamps: commits=- fold=-", "a plan"),
    ).check()
    assert rc == 1, out
    want = "LEAD-FX08 (live.md:9): lead row (state `merged`) carries no "
    assert want + "`docs/product/cycles/<plan>.md` pointer" in out and "LEAD-FX07" not in out, out


def test_a_bare_stage_stamp_is_refused_naming_the_field(world: World) -> None:
    verdict = "reports/p26/fx-07.md stamps: sent=2026-10-04 10:00 done=11:00 met=2026-10-04 10:30"
    rc, out = world.plant(_row("FX-07", "builder", "returned", verdict)).check()
    assert rc == 1, out
    assert "FX-07 (live.md:8): the `done` stamp reads `11:00` — a stage stamp is dated" in out


def test_a_clock_that_runs_backwards_is_refused_naming_the_field(world: World) -> None:
    verdict = f"reports/p26/fx-08.md {STAMPS} met=2026-10-04 12:00 merged=abcdef12 2026-10-04 09:00"
    rc, out = world.plant(_row("FX-08", "builder", "returned", verdict)).check()
    assert rc == 1, out
    assert "FX-08 (live.md:8): stamps refused" in out
    assert "the `merged` stamp (2026-10-04 09:00) is BEFORE" in out


def test_a_row_with_a_pipe_inside_backticks_is_refused_for_its_cell_count(world: World) -> None:
    rc, out = world.plant(
        "| FX-09 | builder | runs `a | b` | sent | 2026-10-04 10:00 | — | — |"
    ).check()
    assert rc == 1, out
    want = "FX-09 (live.md:8): row has 8 cells, not the header's 7 (a `|` inside backticks still"
    assert want + " splits a cell)" in out, out


def test_a_six_cell_row_is_refused_and_counted(world: World) -> None:
    rc, out = world.plant(
        "| FX-10 | builder | a thing | sent | 2026-10-04 10:00 | — |",
        "| FX-11 | builder | `a` thing | sent | 2026-10-04 10:00 | — |",
    ).check()
    assert rc == 1, out
    six = "row has 6 cells, not the header's 7"
    assert f"FX-10 (live.md:8): {six}" in out and f"FX-10 (live.md:8): {six} (" not in out
    assert f"FX-11 (live.md:9): {six}" in out and "inside backticks" not in out
    assert "== ledger-check: 2 refusal(s) · 3 of 3 rows armed" in out, out


def test_a_six_cell_archived_row_is_judged_only_when_armed(world: World) -> None:
    world.plant().archived(
        "| FX-12 | builder | old | sent | 2026-10-02 10:00 | — |",
        "| FX-13 | builder | new | sent | 2026-10-04 10:00 | — |",
    )
    rc, out = world.check()
    assert rc == 1, out
    assert "FX-13 (archive.md:8): row has 6 cells, not the header's 7" in out and "FX-12" not in out


def test_a_closed_spend_row_without_its_number_is_refused(world: World) -> None:
    what = "spend per rung measured"
    rc, out = world.plant(
        _row("CLOSE-FX11", "the PM", "closed", "—", what),
        _row("CLOSE-FX12", "the PM", "closed", "$124 per rung", what),
    ).check()
    assert rc == 1, out
    want = "CLOSE-FX11 (live.md:8): the CLOSE row measuring spend per rung is closed without its"
    assert want + " number" in out and "CLOSE-FX12" not in out, out


def test_an_archived_row_sent_before_arming_is_history(world: World) -> None:
    world.plant().archived(
        "| FX-13 | builder | `a | b` | merged | 2026-10-03 10:00 | — | no stamps, no pointer |"
    )
    rc, out = world.check()
    assert rc == 0 and CLEAN in out, out


def test_an_archived_row_sent_after_arming_is_judged(world: World) -> None:
    world.plant().archived(
        "| FX-14 | builder | a thing | merged | 2026-10-05 10:00 | — | no stamps, no pointer |"
    )
    rc, out = world.check()
    assert rc == 1, out
    assert "FX-14 (archive.md:7): returned row (state `merged`) carries no `stamps:` cell" in out


def test_an_absent_ledger_is_exit_2(world: World) -> None:
    world.plant().live.unlink()
    rc, out = world.check()
    assert rc == 2 and "COULD NOT LOOK" in out, out


def test_a_live_file_with_no_dispatch_table_is_exit_2(world: World) -> None:
    world.plant().live.write_text("# In flight\n\nnothing here\n")
    rc, out = world.check()
    assert rc == 2 and "carries no `## Dispatch ledger` section" in out, out


def test_the_ledger_pair_s_snapshot_passes_in_under_a_second(world: World) -> None:
    """A committed snapshot of the pair's shape; the hook's `--check` measures the real pair."""
    world.plant()
    shutil.copy(SNAPSHOT_LIVE, world.live)
    shutil.copy(SNAPSHOT_ARCHIVE, world.archive)
    rc, out = world.check()
    assert rc == 0 and CLEAN in out, out
    took = re.search(r"^== ledger-check: .* · ([0-9]+\.[0-9]+)s$", out, re.M)
    assert took is not None and float(took.group(1)) < 1.0, out


def test_the_archive_is_derived_beside_the_live_file(world: World) -> None:
    archive = world.dir / "docs/product/archive/in-flight-p26.md"
    archive.parent.mkdir(parents=True)
    world.plant().live.rename(world.dir / "docs/product/in-flight.md")
    archive.write_text(world.archive.read_text())
    world.archive.unlink()
    with archive.open("a") as stage:
        stage.write("| FX-15 | builder | a thing | merged | 2026-10-05 10:00 | — | no stamps |\n")
    rc, out = world.check("--in-flight", "docs/product/in-flight.md", pair=False)
    assert rc == 1 and "FX-15 (docs/product/archive/in-flight-p26.md:7)" in out, out
    rc, out = world.check(pair=False)
    assert rc == 1 and "FX-15 (docs/product/archive/in-flight-p26.md:7)" in out, out


@pytest.mark.template_only(reason="the skeleton sources exist only in the template")
def test_the_shipped_skeleton_passes_with_no_archive(world: World) -> None:
    live = world.dir / "docs/product/in-flight.md"
    live.parent.mkdir(parents=True)
    shutil.copy(SKELETON, live)
    rc, out = world.check(pair=False)
    assert rc == 0 and "== ledger-check: clean · 0 rows" in out, out
    assert len(out.strip().splitlines()) == 1, out


def test_an_absent_archive_is_nothing_archived_not_a_refusal(world: World) -> None:
    world.plant().archive.unlink()
    rc, out = world.check("--in-flight", "live.md", pair=False)
    assert rc == 0 and CLEAN in out and "no archive — nothing archived" in out, out


def test_a_derived_archive_with_no_pruned_stage_holds_nothing(world: World) -> None:
    closed = world.dir / "archive/in-flight-closed.md"
    closed.parent.mkdir()
    closed.write_text("# Closed\n\n## Cycle 1 — closed\n\n| a | b |\n")
    world.plant().archive.unlink()
    rc, out = world.check("--in-flight", "live.md", pair=False)
    assert rc == 0 and CLEAN in out, out


def test_the_alpha_skeleton_heading_is_refused_naming_the_one_heading(world: World) -> None:
    world.plant()
    world.live.write_text(
        world.live.read_text().replace("## Dispatch ledger\n", "## Live dispatch table\n")
    )
    rc, out = world.check()
    assert rc == 2 and "rename `## Live dispatch table` to `## Dispatch ledger`" in out, out
    world.live.write_text(f"# In flight\n\n## Dispatch ledger states\n\n{HEADER}\n{GOOD}\n")
    rc, out = world.check()
    assert rc == 2 and "carries no `## Dispatch ledger` section" in out, out


def test_a_tree_with_no_reports_directory_is_clean(
    world: World, scratch_repo: Callable[..., Path]
) -> None:
    """The published tree: manifest R8 trims `docs/product/reports/**`; R8S ships READMEs back."""
    repo = scratch_repo("published")
    product = repo / "docs/product"
    (product / "briefs").mkdir(parents=True)
    (product / "cycles").mkdir()
    (product / "briefs/README.md").write_text("# Briefs\n")
    (product / "cycles/README.md").write_text("# Cycles\n")
    (product / "in-flight.md").write_text(f"# In flight\n\n{POINTER}\n")
    _commit_after_arming(repo)
    rc, out = world.check("--in-flight", str(product / "in-flight.md"), pair=False)
    assert rc == 0 and CLEAN in out and "0 brief(s) read" in out, out
