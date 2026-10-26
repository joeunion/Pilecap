"""The dated-valve grammar: a past trigger is exit 2, a future one its own line, a plan id red."""

# does-not-cover: the live scan's wiring of these verdicts — a planted valve in a real engine run.

from __future__ import annotations

import re

import pytest

from quality.engine.cli import backlog_census, dated_valve_verdicts
from quality.worlds import valve_on_line

pytestmark = pytest.mark.drives("quality/engine/cli.py", "quality/worlds.py")

TODAY = "2026-10-10"
REASON = "the vendor's client holds this read until it ships the replacement"


def row(reason: str, token: str = "authz") -> tuple[str, str, int, str]:  # noqa: S107 — a valve-kind word default, not a credential
    """One standing row, its reason read by the one valve reader."""
    pattern = re.compile(rf"#\s*{token}:\s*(.*)$")
    valve = valve_on_line(f"    # {token}: {reason}", pattern)
    assert valve is not None and valve.holds, reason
    return (token, "apps/zzz_canary/services.py", 7, valve.reason)


def test_a_past_trigger_is_exit_two_with_its_date() -> None:
    lines, past, named = dated_valve_verdicts([row(f"{REASON} — until 2001-01-01")], TODAY)
    assert past == [
        "apps/zzz_canary/services.py:7: the `authz:` valve's trigger 2001-01-01 is past "
        "(MOVE-TRIGGER 2001-01-01 fired) — do what it waited for and delete it, or write the "
        "new trigger"
    ]
    assert lines == ["dated: 1 valve(s) carry a date"] and named == []


def test_a_future_trigger_prints_its_own_line() -> None:
    lines, past, named = dated_valve_verdicts([row(f"{REASON} — until 2999-01-01")], TODAY)
    assert lines == [
        "dated: 1 valve(s) carry a date",
        "  until 2999-01-01 · authz apps/zzz_canary/services.py:7",
    ]
    assert past == [] and named == []


# coordinate: each id is this case's subject, planted in a valve's reason
@pytest.mark.parametrize("coordinate", ["G-5", "G3b", "RI-2", "C-QUAL-1", "N1234", "P26"])
def test_a_valve_naming_a_plan_coordinate_is_red(coordinate: str) -> None:
    standing = [row(f"{REASON}, booked as {coordinate}")]
    lines, past, named = dated_valve_verdicts(standing, TODAY)
    assert named == [
        f"apps/zzz_canary/services.py:7: the `authz:` valve names the plan coordinate "
        f"`{coordinate}` — say the reason in words; a trigger is a date or a sentence"
    ]
    assert backlog_census(standing, rules=[], held={}, today=TODAY).coordinate == 1
    assert past == [] and lines == ["dated: 0 valve(s) carry a date"]


def test_a_dateless_valve_is_declared_and_unchanged() -> None:
    standing = [row(f"{REASON} — until the vendor ships v2"), row(REASON)]
    lines, past, named = dated_valve_verdicts(standing, TODAY)
    census = backlog_census(standing, rules=[], held={}, today=TODAY)
    assert (lines, past, named) == (["dated: 0 valve(s) carry a date"], [], [])
    assert (census.declared, census.backlog) == (2, 0)


def test_a_coordinate_valve_keeps_its_own_subject() -> None:
    # coordinate: a `coordinate:` valve's subject is the id it names
    standing = [row("the queue row this reader parses is N1234 by design", token="coordinate")]  # noqa: S106 — a valve-kind word, not a credential
    assert dated_valve_verdicts(standing, TODAY)[2] == []
