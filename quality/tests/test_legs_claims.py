"""A leg claiming a shell line keeps that line's place; an unclaimed one follows the shell."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives("quality/djb/registry.py", "quality/djb/legs/")

ROOT = Path(__file__).resolve().parents[2]
GATE = textwrap.dedent(
    """\
    gate_unit pytest-x2 db N-capable
    gate_unit selftest db N-capable
    gate_run_body census gate_leg_census_pre pytest-x2 "pre"
    gate_run_body partition gate_leg_partition pytest-x2 "partition"
    gate_run_body pytest-x2 gate_leg_pytest_x2 pytest-x2 "passes"
    gate_run_body own-tree gate_leg_own_tree pytest-x2 "own"
    gate_run_body selftest gate_leg_selftest selftest "selftest"
    ./scripts/tests/test_one.sh
    ./scripts/tests/test_two.sh
    """
)
UNITS = (R.Unit("pytest-x2", ("db",), "N-capable"), R.Unit("selftest", ("db",), "N-capable"))
DRIVES = ("one", "two")


def _leg(name: str, unit: str, after: str | None = None) -> R.Leg:
    return R.Leg(name, unit, name, lambda ctx: 0, after)


def test_a_claimed_member_in_the_middle_of_its_unit_keeps_its_place() -> None:
    table = R.build(
        [_leg("pytest-x2", "pytest-x2"), _leg("selftest", "selftest")], GATE, UNITS, DRIVES
    )
    assert table.unit("pytest-x2")[1] == ("census", "partition", "pytest-x2", "own-tree")


def test_the_claimed_head_keeps_its_place_and_an_unclaimed_leg_follows_the_drives() -> None:
    legs = [
        _leg("pytest-x2", "pytest-x2"),
        _leg("selftest", "selftest"),
        _leg("tail", "selftest", "selftest"),
    ]
    table = R.build(legs, GATE, UNITS, DRIVES)
    assert table.unit("selftest")[1] == ("selftest", "one", "two", "tail")


def test_claimed_legs_take_their_own_chain_at_the_first_claimed_place() -> None:
    legs = [
        _leg("partition", "pytest-x2", "own-tree"),
        _leg("own-tree", "pytest-x2"),
        _leg("selftest", "selftest"),
    ]
    table = R.build(legs, GATE, UNITS, DRIVES)
    assert table.unit("pytest-x2")[1] == ("census", "own-tree", "partition", "pytest-x2")


def test_this_trees_three_units_keep_their_claimed_places() -> None:
    table = R.load(ROOT)
    shell = R.shell_legs(shell_gate.text())
    claimed = {c for g in table.legs for c in g.claims}
    for unit in ("supply-chain", "pytest-x2", "selftest"):
        members = table.unit(unit)[1]
        row = [n for n, u in shell if u == unit and n not in claimed]
        for leg in (g for g in table.legs if g.unit == unit and g.name in row):
            assert members.index(leg.name) == row.index(leg.name), (unit, leg.name)
