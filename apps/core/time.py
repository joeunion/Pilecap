"""Time, said the same way everywhere.

Thin on purpose — every function here is one line — because the value is not the
code, it is that there is one spelling of each of these in the tree. Four rules
this makes hard to break:

* **Everything stored is UTC** (`USE_TZ = True`). A naive datetime in a column
  is an incident waiting for a daylight-saving boundary.
* **A tenant's clock is a display concern.** `Tenant.timezone` decides what a
  human sees; it never decides what is stored, and it never appears in a query.
* **`now()` goes through `django.utils.timezone`**, so `time_machine` and the
  `freeze_time`-style tests can move it. `datetime.now()` cannot be moved and
  is naive besides.
* **`DateTimeField`s end `_at`, `DateField`s end `_on`** (house rule 15) —
  because "expires" alone does not say whether tomorrow at 00:01 counts.

Nothing here reads the clock inside a workflow: `workflows.py` uses
`workflow.now()`, which replays identically. That is house rule 9, and it is
why this module is not imported there.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

UTC = ZoneInfo("UTC")


def now() -> datetime:
    """The current instant, aware and in UTC. The only clock in `apps/`."""
    return timezone.now()


def today(*, tz: str | None = None) -> date:
    """Today's date *somewhere*.

    The timezone is required to be a choice rather than a default, because
    "today" is a different day either side of most boundaries and a report that
    silently uses the server's idea of it is wrong for half the customers.
    """
    return now().astimezone(ZoneInfo(tz) if tz else UTC).date()


def start_of_day(on: date, *, tz: str | None = None) -> datetime:
    """The first instant of a date in a timezone, as an aware UTC datetime.

    The pair with `end_of_day` is how a date range becomes a query: a
    `__range` on `created_at` needs instants, and building them by hand is
    where the off-by-one-day bugs live.
    """
    zone = ZoneInfo(tz) if tz else UTC
    return datetime.combine(on, time.min, tzinfo=zone).astimezone(UTC)


def end_of_day(on: date, *, tz: str | None = None) -> datetime:
    """The first instant of the *next* day — a half-open upper bound.

    Half-open (`>= start, < end`) rather than 23:59:59.999999, because the
    closed form drops whatever happened in the last microsecond and the bug it
    causes is invisible until it is not.
    """
    return start_of_day(on + timedelta(days=1), tz=tz)


def as_tenant_time(moment: datetime, *, tz: str) -> datetime:
    """One stored instant, rendered in a tenant's timezone. Display only."""
    return moment.astimezone(ZoneInfo(tz))


def is_past(moment: datetime | None) -> bool:
    """True when a deadline has gone. `None` means "no deadline", not "expired"."""
    return moment is not None and moment <= now()


def in_days(days: int) -> datetime:
    """An instant `days` from now. For expiries, in UTC, like everything stored."""
    return now() + timedelta(days=days)
