"""Periods: the windows a total is bucketed into, and the boundary that matters.

A period is three lines of arithmetic and it decides which invoice a row lands
on, so the boundary gets its own test rather than being inferred from a total
that happened to be right.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.usage.types import Period, PeriodKind, Threshold


def test_a_day_is_half_open_in_utc() -> None:
    """`[start, end)`. A closed window double-counts the instant between two days.

    On a billing ledger that is a row that appears in two invoices, which is the
    one arithmetic error a customer always notices.
    """
    day = Period.containing(datetime(2026, 8, 12, 23, 59, 59, tzinfo=UTC), PeriodKind.DAY)
    assert day.starts_at == datetime(2026, 8, 12, tzinfo=UTC)
    assert day.ends_at == datetime(2026, 8, 13, tzinfo=UTC)
    assert day.days() == [day.starts_at.date()]


def test_a_month_runs_to_the_first_of_the_next_one() -> None:
    month = Period.containing(datetime(2026, 2, 17, 8, tzinfo=UTC), PeriodKind.MONTH)
    assert month.starts_at == datetime(2026, 2, 1, tzinfo=UTC)
    assert month.ends_at == datetime(2026, 3, 1, tzinfo=UTC)
    assert len(month.days()) == 28


def test_a_leap_february_is_twenty_nine_days() -> None:
    month = Period.containing(datetime(2028, 2, 3, tzinfo=UTC), PeriodKind.MONTH)
    assert len(month.days()) == 29


def test_a_december_month_rolls_into_january() -> None:
    """The obvious off-by-one, and it is worth a line: `month + 1` is not a month."""
    month = Period.containing(datetime(2026, 12, 20, tzinfo=UTC), PeriodKind.MONTH)
    assert month.ends_at == datetime(2027, 1, 1, tzinfo=UTC)


def test_an_instant_in_another_zone_is_bucketed_in_utc() -> None:
    """**The declared cost of bucketing in UTC**, asserted rather than assumed.

    Ten in the morning in Auckland on the 13th is 22:00 UTC on the 12th, and this
    ledger says the 12th. The alternative — bucketing in `Tenant.timezone` —
    makes last month's total move when a customer relocates, and a period that
    can move is not evidence.
    """
    auckland = datetime(2026, 8, 13, 10, tzinfo=ZoneInfo("Pacific/Auckland"))
    day = Period.containing(auckland, PeriodKind.DAY)
    assert day.starts_at.date().isoformat() == "2026-08-12"


def test_a_window_that_ends_before_it_starts_is_refused() -> None:
    start = datetime(2026, 8, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="ends after it starts"):
        Period(starts_at=start, ends_at=start - timedelta(days=1))


def test_a_threshold_line_parses_out_of_settings_json() -> None:
    line = Threshold.from_setting(
        {"meter": "example.widgets.count", "period": "month", "quantity": 1000}
    )
    assert line.kind is PeriodKind.MONTH
    assert line.quantity == Decimal("1000")


def test_a_threshold_quantity_that_arrived_as_a_float_keeps_its_decimal_value() -> None:
    """Through `str`, so a JSON float does not carry its binary approximation
    into a comparison against a `Decimal` total (house rule 15, at the config
    boundary)."""
    line = Threshold.from_setting(
        {"meter": "example.widgets.count", "period": "day", "quantity": 0.1}
    )
    assert line.quantity == Decimal("0.1")
