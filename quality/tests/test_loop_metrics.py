"""The velocity reader: the two clocks, the inner loop and the speed cells, read off the ledger."""

# does-not-cover: whether a stamp is TRUE — the reader measures what the ledger says happened.
# does-not-cover: a bank or loop log under a name the reader's globs do not match.
# does-not-cover: the cost-baseline table's meaning — its header is read, never judged.

# names, never reads: docs/product/in-flight.md — the fixture world's file name (rule 90)

# moved: test_the_real_ledger_reads_and_names_what_it_could_not_measure — this module, renamed

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives(
    "scripts/loop_metrics.py",
    "quality/djb/rituals/push.py",
    "docs/product/readouts.md",
    "quality/tests/fixtures/ledger_pair/live.md",
)

ROOT = Path(__file__).resolve().parents[2]
READER = ROOT / "scripts" / "loop_metrics.py"
SNAPSHOT = ROOT / "quality/tests/fixtures/ledger_pair/live.md"
LEDGER = """# The dispatch ledger — fixture

Some prose above the table, which is not a row.

| # | Task | Role · model | State | Sent | Returned | Result |
|---|---|---|---|---|---|---|
| RUNG-A | alpha | development · opus | merged | 2026-09-17 08:00 | 2026-09-17 09:40 | DONE. stamps: sent=2026-09-17 08:00 done=09:40 met=10:05 merged=1a2b3c4d 10:20 pushed=— staged=— |
| RUNG-B | beta | development · opus | merged | 2026-09-17 08:05 | 2026-09-17 10:10 | DONE. stamps: sent=2026-09-17 08:05 done=10:10 met=10:50 merged=2b3c4d5e 11:00 pushed=— staged=— |
| WAVE-1 | the first wave | wave | pushed | — | — | stamps: sent=— done=— met=— merged=— pushed=2026-09-17 11:30 staged=2026-09-17 11:52 |
| RUNG-C | gamma | development · opus | merged | 2026-09-17 12:00 | 2026-09-17 13:00 | DONE. stamps: sent=2026-09-17 12:00 done=13:00 met=13:20 merged=3c4d5e6f 13:35 pushed=— staged=— |
| WAVE-2 | the second wave | wave | pushed | — | — | stamps: sent=— done=— met=— merged=— pushed=2026-09-17 14:00 staged=— |
| VERIFY-A | prove alpha | verification · opus | returned | 2026-09-17 09:45 | 2026-09-17 10:05 | PASS. stamps: sent=2026-09-17 09:45 done=10:05 met=10:05 merged=— pushed=— staged=— |
| RUNG-D | delta | development · opus | returned | 2026-09-17 15:00 | 2026-09-17 16:00 | DONE — this row predates the stamp grammar and carries no stamps cell |
| RUNG-E | epsilon | development · opus | killed | 2026-09-17 15:00 | — | killed by the platform; no report |
"""  # noqa: E501
READOUTS = """# Readouts — fixture

## COST BASELINE — fixture

| Measure | Fixture column two | Fixture column three |
|---|---|---|
| opus | some spend | some lever |
"""
LEAF = (
    "the fast tier NARROWED to the active rung's scope — its own app(s) [example], which run IN"
    " FULL, plus the reverse-transitive depends_on closure [-], which runs its fast tier — plus"
    " the always-on cross-app set"
)
CORE = LEAF.replace("[example]", "[core]").replace("closure [-]", "closure [example]")
SHARED = (
    "the active rung changed shared test infrastructure or a file no app owns that every test"
    " stands on — so --loop runs the FULL suite, not a scope"
)
SPEED_EDITS = (
    (
        "DONE. stamps: sent=2026-09-17 08:00",
        "DONE. `loop: miss(no-ledger) 900s` fold 1a2b3c4d: equals merge-tree."
        " stamps: sent=2026-09-17 08:00",
    ),
    (
        "merged=1a2b3c4d 10:20 pushed=— staged=— |",
        "merged=1a2b3c4d 10:20 pushed=— staged=— commits=08:10..09:30 fold=09:35 loop=774"
        " held=owner:12 |",
    ),
    (
        "DONE. stamps: sent=2026-09-17 08:05",
        "DONE. fold 2b3c4d5e: differs from merge-tree — 1 paths: x. stamps: sent=2026-09-17 08:05",
    ),
    (
        "merged=2b3c4d5e 11:00 pushed=— staged=— |",
        "merged=2b3c4d5e 11:00 pushed=— staged=— commits=2026-09-17 08:20..10:00 loop=800s |",
    ),
    (
        "| PASS. stamps:",
        "| PASS. `loop: hit 412s` fold 1a2b3c4d: equals merge-tree `loop: miss(code: 9f8e7d6c)"
        " 700s` stamps:",
    ),
    (
        "carries no stamps cell |",
        "carries no stamps cell `loop: docs-only reuse of 1111111` `loop: miss(tree) 600s` |",
    ),
)


@dataclass
class World:
    """One fixture world: its ledger, readouts, bank and loop log directories, and a runner."""

    dir: Path
    capture: Callable[..., Captured]

    @property
    def ledger(self) -> Path:
        return self.dir / "in-flight.md"

    def edit(self, old: str, new: str, path: Path | None = None) -> None:
        """Replace `old` once; the anchor must be found, never an edit that did nothing."""
        target = path or self.ledger
        text = target.read_text()
        assert old in text, f"the edit's anchor is not in {target.name}: {old!r}"
        target.write_text(text.replace(old, new, 1))

    def speed(self) -> None:
        for old, new in SPEED_EDITS:
            self.edit(old, new)

    def loop_log(self, name: str, reason: str, wall: int) -> None:
        lines = ["== check.sh --loop"]
        if reason:
            lines.append(f"  scope   rule: {reason}")
        lines += ["  (house-rules: 22s)", f"  (pytest: {wall - 40}s)"]
        lines.append(f"ok: loop checks passed ({wall}s)")
        (self.dir / "loops" / f"{name}.log").write_text("\n".join(lines) + "\n")

    def bank_log(self, name: str, *lines: str) -> None:
        (self.dir / "banks" / f"{name}.log").write_text("\n".join(lines) + "\n")

    def run(self, *argv: str) -> tuple[int, str]:
        ran = self.capture([sys.executable, str(READER), *argv])
        return ran.rc, ran.text()

    def report(self, *argv: str) -> tuple[int, str]:
        return self.run(
            "--in-flight",
            str(self.ledger),
            "--readouts",
            str(self.dir / "readouts.md"),
            "--bank-logs",
            str(self.dir / "banks"),
            "--loop-logs",
            str(self.dir / "loops"),
            *argv,
        )


PUSHED = (
    "pre-push: every pushed tree (6d03b4f9864dd3a087d4eb984cada3e6774b4b6d) is measured green by"
    " a full gate run — verdict honoured"
)
GREEN = (
    "== check.sh (full)",
    "  (house-rules: 25s)",
    "  (supply-chain: 76s)",
    "  (pytest-x2: 480s)",
    "  (selftest: 900s)",
    "ok: all checks passed (1879s)",
    PUSHED,
)
RED = (
    "== check.sh (full)",
    "  (house-rules: 25s)",
    "!! pm_push --bank: the full gate exited 1.",
    "   Nothing was pinned and nothing was pushed.",
)
M = "1111111111111111111111111111111111111111"
DOCS_ONLY = (
    "pm_push --bank: docs-only? yes — 3 path(s) changed since the",
    f"  measured tree {M}, every one of them on the declared list.",
    "  readers, DERIVED from what those paths are read by:",
    "    static",
    "  reader static: 41s (exit 0)",
    f"pm_push --bank: docs-only reuse of {M} — readers 41 s, total 43 s",
    "  source + delta + row: 2 s",
    PUSHED,
)


@pytest.fixture
def world(scratch: Path, capture: Callable[..., Captured]) -> World:
    """The fixture ledger and readouts, and empty bank and loop log directories."""
    home = scratch / "world"
    (home / "banks").mkdir(parents=True)
    (home / "loops").mkdir()
    (home / "in-flight.md").write_text(LEDGER)
    (home / "readouts.md").write_text(READOUTS)
    return World(home, capture)


# --- the two clocks ----------------------------------------------------------------


def test_the_two_clocks_are_derived_from_the_stamps(world: World) -> None:
    rc, out = world.report()
    assert rc == 0, out
    for said in ("RUNG-A", "done→met", "25 min", "40 min", "20 min", "WAVE-1", "WAVE-2"):
        assert said in out
    for said in ("last met→pushed", "pushed→staged", "22 min", "not reached"):
        assert said in out


def test_the_wave_of_a_rung_is_derived_from_the_clocks(world: World) -> None:
    rc, out = world.report()
    assert rc == 0
    assert "WAVE-1: RUNG-A, RUNG-B" in out
    assert "WAVE-2: RUNG-C" in out


def test_the_inner_loop_is_reported_by_change_class(world: World) -> None:
    world.loop_log("leaf-1", LEAF, 100)
    world.loop_log("leaf-2", LEAF, 140)
    world.loop_log("core-1", CORE, 300)
    world.loop_log("shared-1", SHARED, 900)
    world.loop_log("nothing-said", "", 61)
    rc, out = world.report()
    assert rc == 0
    for said in ("leaf", "core", "shared", "120 s", "300 s", "900 s", "unclassified"):
        assert said in out
    assert "nothing-said.log" in out
    assert "61 s" not in out


# --- the refusals ------------------------------------------------------------------


def test_a_malformed_stamp_cannot_be_measured(world: World) -> None:
    world.edit("met=10:05 merged=1a2b3c4d", "met=25:99 merged=1a2b3c4d")
    rc, out = world.report()
    assert rc == 2
    assert "RUNG-A" in out and "met" in out
    assert "done→met" not in out
    assert "Nothing was measured" in out


def test_a_merged_rung_with_no_met_stamp_cannot_be_measured(world: World) -> None:
    world.edit("met=10:05 merged=1a2b3c4d", "met=— merged=1a2b3c4d")
    rc, out = world.report()
    assert rc == 2
    assert "RUNG-A" in out and "met" in out
    assert "done→met" not in out


def test_a_note_row_that_was_merged_and_never_dispatched_is_named_as_one(world: World) -> None:
    world.edit(
        "| RUNG-C | gamma | development · opus | merged | 2026-09-17 12:00 | 2026-09-17 13:00"
        " | DONE. stamps: sent=2026-09-17 12:00 done=13:00 met=13:20 merged=3c4d5e6f 13:35"
        " pushed=— staged=— |",
        "| NOTE-1 | a ruling nobody built | note | — | — | — | stamps: sent=— done=— met=—"
        " merged=3c4d5e6f 2026-09-17 13:35 pushed=— staged=— |",
    )
    rc, out = world.report()
    assert rc == 2
    for said in ("NOTE-1", "NOT A RUNG ROW", "WITHHOLD THE"):
        assert said in out
    assert "done→met" not in out


def test_a_wave_with_no_pushed_stamp_cannot_be_measured(world: World) -> None:
    world.edit("pushed=2026-09-17 11:30", "pushed=—")
    rc, out = world.report()
    assert rc == 2
    assert "WAVE-1" in out and "pushed" in out


def test_a_second_clock_in_a_stamp_is_refused(world: World) -> None:
    world.edit("done=13:00 met=13:20", "done=13:00 CEST met=13:20")
    rc, out = world.report()
    assert rc == 2
    assert "RUNG-C" in out and "one clock" in out


# --- the unstamped ------------------------------------------------------------------


def test_a_row_with_no_stamps_is_counted_never_dropped(world: World) -> None:
    rc, out = world.report()
    assert rc == 0
    for said in ("unstamped", "RUNG-D", "RUNG-E", "2 of 8"):
        assert said in out


def test_a_ledger_with_no_stamped_row_measures_nothing_and_says_so(world: World) -> None:
    text = world.ledger.read_text()
    stripped = "".join(
        line.split("stamps: ")[0] + ("|" + line.split("stamps: ", 1)[1].split("|", 1)[1])
        if "stamps: " in line
        else line
        for line in text.splitlines(keepends=True)
    )
    assert stripped != text
    world.ledger.write_text(stripped)
    rc, out = world.report()
    assert rc == 0
    assert "8 of 8" in out and "no stamped row" in out


# --- read-only, deterministic ------------------------------------------------------


def test_metrics_are_read_only_and_deterministic(world: World) -> None:
    world.loop_log("leaf-1", LEAF, 100)
    world.bank_log("bank-1", *GREEN)
    world.bank_log("bank-2", *RED)
    rc, first = world.report()
    assert rc == 0
    paths = [world.dir, *world.dir.rglob("*")]
    modes = {p: p.stat().st_mode for p in paths}
    for p in paths:
        p.chmod(modes[p] & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        rc, second = world.report()
    finally:
        for p in paths:
            p.chmod(modes[p])
    assert rc == 0
    assert second == first, "two runs over one world differ"
    assert "banks launched" in first
    assert "2 / 1 / 50%" in first


# --- the readouts ------------------------------------------------------------------


def test_the_cost_baseline_header_is_read_not_retyped(world: World) -> None:
    rc, out = world.report()
    assert rc == 0
    assert "| Measure | Fixture column two | Fixture column three |" in out
    assert "The lever it measures" not in READER.read_text(), "the reader retypes the header"


def test_a_readouts_file_with_no_cost_baseline_section_is_exit_2(world: World) -> None:
    (world.dir / "readouts.md").write_text("# Readouts — fixture\n\nNo section here at all.\n")
    rc, out = world.report()
    assert rc == 2
    assert "COST BASELINE" in out


# --- the inputs ----------------------------------------------------------------------


def test_an_unknown_flag_is_exit_2(world: World) -> None:
    rc, out = world.run(
        "--in-flight", str(world.ledger), "--readouts", str(world.dir / "readouts.md"), "--wat"
    )
    assert rc == 2
    assert "done→met" not in out


def test_an_absent_ledger_is_exit_2(world: World) -> None:
    rc, out = world.run(
        "--in-flight", str(world.dir / "nowhere.md"), "--readouts", str(world.dir / "readouts.md")
    )
    assert rc == 2
    assert "nowhere.md" in out


def test_the_ledger_snapshot_reads_and_names_what_it_could_not_measure(world: World) -> None:
    """The ledger's committed snapshot and the real readouts; the hook reads the real ledger."""
    (world.dir / "real-in-flight.md").write_text(SNAPSHOT.read_text())
    (world.dir / "real-readouts.md").write_text((ROOT / "docs/product/readouts.md").read_text())
    rc, out = world.run(
        "--in-flight",
        str(world.dir / "real-in-flight.md"),
        "--readouts",
        str(world.dir / "real-readouts.md"),
        "--bank-logs",
        str(world.dir / "banks"),
        "--loop-logs",
        str(world.dir / "loops"),
    )
    assert rc == 0, out
    assert "unstamped" in out and "COST BASELINE" in out


def test_the_json_carries_the_same_numbers(world: World) -> None:
    rc, out = world.report("--json")
    assert rc == 0
    assert '"stage3"' in out and '"unstamped"' in out
    json.loads(out)


def test_a_docs_only_bank_is_a_green_bank_with_its_own_wall(world: World) -> None:
    world.bank_log("bank-1", *GREEN)
    world.bank_log("bank-2", *DOCS_ONLY)
    world.bank_log("bank-3", *RED)
    rc, out = world.report()
    assert rc == 0
    assert "3 / 2 / 67%" in out
    assert "(1 docs-only)" in out
    assert "961" in out
    pusher = (ROOT / "quality/djb/rituals/push.py").read_text()
    assert "docs-only reuse of {plan.source} — readers " in pusher, (
        "the push script no longer prints the line this reader matches"
    )


# --- the speed cells ---------------------------------------------------------------


def test_a_row_with_coding_cells_yields_a_ratio(world: World) -> None:
    world.speed()
    rc, out = world.report("--speed")
    assert rc == 0, out
    assert (
        "RUNG-A         dispatch → merge 140 min · coding 85 min (61 %) · bank → MET 25 min"
        " · loop 774 s · held owner:12"
    ) in out
    assert "else 55 min" in out
    assert (
        "RUNG-B         dispatch → merge 175 min · coding 100 min (57 %) · bank → MET 40 min"
        " · loop 800 s · held —"
    ) in out
    assert "no fold= cell" in out


def test_the_tax_lines_are_summed_and_a_row_without_one_is_named(world: World) -> None:
    world.speed()
    world.edit("equals merge-tree.", "equals merge-tree. tax: 1.5 min in 1 member(s).")
    world.edit("differs from merge-tree", "tax: 2+? min in 2 member(s); differs from merge-tree")
    rc, out = world.report("--speed")
    assert rc == 0, out
    assert "   tax: 3.5 min over 2 rung(s) (+? on RUNG-B) — reported, never asserted" in out
    assert "   tax: no `tax:` line on RUNG-C" in out


def test_an_unmeasured_row_is_named(world: World) -> None:
    world.speed()
    rc, out = world.report("--speed")
    assert rc == 0
    assert "RUNG-C         unmeasured — no commits= cell" in out
    assert "2 of 3 rung(s) measured" in out


def test_the_wave_ratio_is_the_union_of_its_rungs_spans(world: World) -> None:
    world.speed()
    rc, out = world.report("--speed")
    assert rc == 0
    assert (
        "WAVE-1         first dispatch → pushed 210 min · coding 110 min (52 %) · pushed →"
        " staged 22 min"
    ) in out
    assert (
        "WAVE-2         first dispatch → pushed 120 min · coding — (no member carries commits=)"
    ) in out


def test_the_loop_and_fold_cells_are_tallied(world: World) -> None:
    world.speed()
    rc, out = world.report("--speed")
    assert rc == 0
    assert (
        "loop: hit 1 · miss(code: …) 1 · miss(no-ledger) 1 · docs-only reuse 1 · other 1"
        " (miss(tree))"
    ) in out
    assert "fold: equals 1 · differs 1 · regenerated 0 over 2 merge(s)" in out
    assert "tripwire" in out


def test_a_regenerated_fold_is_tallied_apart_from_differs(world: World) -> None:
    world.speed()
    world.edit(
        "carries no stamps cell ",
        "carries no stamps cell fold 3c4d5e6f: regenerated —"
        " apps/core/tests/flat_product_baseline.json ",
    )
    rc, out = world.report("--speed")
    assert rc == 0
    assert "fold: equals 1 · differs 1 · regenerated 1 over 3 merge(s)" in out


def test_a_train_merge_row_carries_its_branch_count(world: World) -> None:
    world.speed()
    world.edit("held=owner:12 |", "held=owner:12 train=3 |")
    rc, out = world.report("--speed")
    assert rc == 0
    assert "train: RUNG-A carried 3 branch(es) in one merge" in out
    assert "trains: 1 merge(s) carried 3 branch(es)" in out
    world.edit("train=3 |", "train=many |")
    rc, out = world.report("--speed")
    assert rc == 2
    assert "train" in out


def test_a_fold_read_both_ways_is_exit_2(world: World) -> None:
    world.speed()
    world.edit("fold 2b3c4d5e: differs", "fold 1a2b3c4d: differs")
    rc, out = world.report("--speed")
    assert rc == 2
    assert "1a2b3c4d" in out
    assert "dispatch → merge" not in out


@pytest.fixture
def speed_text(world: World) -> str:
    world.speed()
    return world.ledger.read_text()


def test_a_malformed_coding_cell_is_exit_2(world: World, speed_text: str) -> None:
    for old, new, said in (
        ("commits=08:10..09:30", "commits=09:30..08:10", ("RUNG-A", "commits")),
        ("commits=08:10..09:30", "commits=08:10..10:45", ("after the `merged` stamp",)),
        ("held=owner:12", "held=owner", ("held",)),
        ("loop=774", "loop=fast", ("loop",)),
    ):
        world.ledger.write_text(speed_text)
        world.edit(old, new)
        rc, out = world.report("--speed")
        assert rc == 2, f"{new} was not refused"
        assert all(one in out for one in said), (new, said)


def test_a_row_without_the_new_cells_reads_as_today(world: World) -> None:
    rc, plain = world.report()
    assert rc == 0
    world.speed()
    rc, speedy = world.report()
    assert rc == 0
    strip = [line for line in plain.splitlines() if str(world.dir) not in line]
    assert strip == [line for line in speedy.splitlines() if str(world.dir) not in line]
    world.ledger.write_text(LEDGER)
    rc, out = world.report("--speed")
    assert rc == 0
    assert "0 of 3 rung(s) measured" in out


def test_the_speed_json_carries_the_rows(world: World) -> None:
    world.speed()
    rc, out = world.report("--speed", "--json")
    assert rc == 0
    assert '"speed"' in out
    assert '"coding_min": 85.0' in out
    json.loads(out)
