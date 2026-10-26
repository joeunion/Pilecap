"""The two durations tables the shards balance by: each still about the population it weighs."""

# deleted: case_a_one_line_ci_walls_table_reads_as_the_same_table — dies with the shim
# pin: test_a_one_line_walls_table_reads_as_the_same_table_through_the_ledger (ledger.durations)
# narrowed: case_the_durations_file_is_derived_and_regenerable — check.sh's `--store-durations` text
# narrowed: case_the_ci_walls_table_is_about_this_selftest_population — check.sh's walls view text
# does-not-cover: whether the recorded times are any good — which tests are named, never how long.
# does-not-cover: the balance itself — a coverage floor, never a wall-clock question.
# does-not-cover: every partition property — test_list_legs.py's, over the fixture world.

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import ledger
from quality.djb import registry as R

pytestmark = pytest.mark.drives(
    "apps/*.py",
    "apps/*/tests/",
    "apps/testing/",
    "scripts/check.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_member_durations.json",
    "scripts/pm_fold.sh",
    "scripts/pytest_durations.json",
)

ROOT = Path(__file__).resolve().parents[2]
DURATIONS = ROOT / "scripts/pytest_durations.json"
#: Half: far below any honest tree, far above a file about another suite.
COVERAGE_FLOOR = 50
REGENERATE = "Regenerate: ./scripts/check.sh --leg pytest-x2 --store-durations"


@pytest.mark.template_only(
    reason="the durations file is the template's own measurement; a product never receives it"
)
def test_the_durations_file_is_derived_and_regenerable() -> None:
    assert DURATIONS.is_file(), "scripts/pytest_durations.json is not in this tree"
    recorded = json.loads(DURATIONS.read_text(encoding="utf-8"))
    assert recorded, "the durations file records nothing"
    assert "quality" not in DURATIONS.relative_to(ROOT).parts[:1]
    assert "store-durations" in ledger.NO_BANK_CALLERS


@pytest.mark.template_only(
    reason="the durations file is the template's own measurement; a product never receives it"
)
def test_the_durations_file_covers_the_collection_it_balances(
    capture: Callable[..., object],
) -> None:
    ran = capture(
        [str(ROOT / ".venv/bin/python"), "-m", "pytest", "--collect-only", "-q"]
        + ["-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=ROOT,
    )
    assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
    collected = {
        line.strip()
        for line in ran.text().splitlines()  # type: ignore[attr-defined]
        if "::" in line and not line.startswith(" ")
    }
    assert collected, "the collection transcript held no node ids"
    keys = set(json.loads(DURATIONS.read_text(encoding="utf-8")))
    covered, stale = collected & keys, keys - collected
    pct = 100 * len(covered) // len(collected)
    print(f"{len(covered)} of {len(collected)} collected carry a duration ({pct}%)")
    assert pct >= COVERAGE_FLOOR, f"{pct}% under the floor of {COVERAGE_FLOOR}% — {REGENERATE}"
    assert keys, "the durations file records nothing at all"
    assert len(stale) * 2 < len(keys), f"{len(stale)} of {len(keys)} are gone — {REGENERATE}"


def test_the_ci_walls_table_is_about_this_selftest_population() -> None:
    homes = [ROOT / ledger.WALLS_TEMPLATE, ROOT / ledger.WALLS_DRAWER]
    walls, ats = ledger._walls_read(homes, print)
    view = ledger.durations(ROOT, R.CI_MACHINE, only=True)
    assert view, "the one walls table carries no ubuntu-latest column"
    assert re.fullmatch(r"run:[0-9]+ tree:[0-9a-f]{40}", ats.get(R.CI_MACHINE, "")), ats
    assert all(isinstance(v, int) for v in view.values())
    members = R.load(ROOT).unit("selftest")[1]
    population = [R.ENGINE_MEMBER if m == "selftest" else m for m in members]
    named = sum(1 for m in population if m in view)
    pct = named * 100 // len(population)
    stale = sorted(m for m in view if m not in population)
    again = "re-harvest: ./scripts/pm_fold.sh --only walls"
    assert pct >= COVERAGE_FLOOR, f"{named} of {len(population)} ({pct}%) — {again}"
    assert not stale, f"members the population lacks: {' '.join(stale)} — {again}"
    assert ledger.WALLS_TEMPLATE == R.WALLS_HOMES[0]
    assert R.CI_MACHINE == "ubuntu-latest"


def test_a_one_line_walls_table_reads_as_the_same_table_through_the_ledger(
    scratch: Path,
) -> None:
    doc = json.loads((ROOT / ledger.WALLS_TEMPLATE).read_text(encoding="utf-8"))
    multi, compact = scratch / "multi.json", scratch / "compact.json"
    multi.write_text(json.dumps(doc, indent=2))
    compact.write_text(json.dumps(doc, separators=(",", ":")))
    assert len(compact.read_text().splitlines()) == 1
    for machine in ("ubuntu-latest", "darwin", "box"):
        one = ledger.durations(scratch, machine, only=True, homes=[compact])
        two = ledger.durations(scratch, machine, only=True, homes=[multi])
        assert one == two, machine
    assert ledger.durations(scratch, R.CI_MACHINE, only=True, homes=[compact])
    assert ledger._walls_read([compact], print) == ledger._walls_read([multi], print)
