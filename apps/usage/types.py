"""The shapes that cross a boundary here: a period, and a configured threshold.

Standard library only, like every other `types.py` in this tree. Nothing in this
module touches the ORM, so a workflow could import it the day this app grows one
(the rollup ADR usage-1 defers with a named trigger).
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

#: Where a caller who named a meter this deployment does not have should go next.
#: `<kind>:<name>`, the template's opaque destination grammar (ADR core-5) — the
#: `url_name` of the vocabulary route, so a product with a navigation manifest
#: can resolve it and one without still reads where to look.
#:
#: **It lives HERE and not in `meters.py`, and that is not tidiness.**
#: `declared_meters()` reads every uppercase, non-underscored STRING constant of
#: an app's `meters.py` as a declared meter name — that is how the registry has
#: no hand-list — so a destination token declared in that module is a meter
#: called `route:meter-list`, and the boot check refuses the whole vocabulary
#: over it (it did, once, before this constant moved). A `meters.py` is
#: a module of meter names and nothing else; anything else a meter-shaped module
#: needs to say belongs where the rest of this app's constants live.
METERS_DESTINATION = "route:meter-list"


class PeriodKind(StrEnum):
    """The windows a total is asked for over. Two, and adding a third is a diff.

    A `StrEnum` because these values are written by hand into a tenant's settings
    JSON and read back out of it: `"month"` in the config file and
    `PeriodKind.MONTH` in the code have to be the same object without anybody
    mapping between them.

    **No `year`, no `week`, no arbitrary range** — not because they are hard, but
    because every one of them is a bucketing decision a rollup will one day have
    to materialise, and the set that gets materialised should be the set somebody
    chose. A caller wanting an arbitrary window builds a `Period` directly.
    """

    DAY = "day"
    MONTH = "month"


@dataclass(frozen=True)
class Period:
    """A half-open window `[starts_at, ends_at)` in UTC.

    Half-open, and that is the only interesting thing about it: a closed window
    double-counts the boundary instant between two adjacent periods, which on a
    billing ledger is a row that appears in two invoices.
    """

    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValueError(
                f"A period ends after it starts; got {self.starts_at!r} to {self.ends_at!r}."
            )

    def days(self) -> list[date]:
        """Every UTC calendar day this window touches, in order.

        The keys of `MeasuredOut.basis.inputs` — so a reader who wants to check
        the arithmetic can see the days that contributed nothing as well as the
        days that did. A basis with the empty days missing is a basis that cannot
        be told from a basis with days lost.
        """
        first = self.starts_at.date()
        last = (self.ends_at - timedelta(microseconds=1)).date()
        span = (last - first).days
        return [first + timedelta(days=offset) for offset in range(span + 1)]

    @classmethod
    def containing(cls, at: datetime, kind: PeriodKind) -> Period:
        """The `kind`-shaped window that contains this instant, in UTC.

        **UTC and not the tenant's timezone**, deliberately and with a cost
        stated: a tenant in Auckland whose month total is measured in UTC sees a
        few hours of the first and last day fall the other side of the boundary.
        The alternative — bucketing in `Tenant.timezone` — makes a total depend
        on a column somebody can change, so last month's number would move when
        a customer relocates. A ledger's periods have to be stable to be
        evidence. The product-layer app that renders an invoice is where a local
        calendar belongs, on top of a total that never moved.
        """
        moment = at.astimezone(UTC)
        if kind is PeriodKind.DAY:
            start = datetime.combine(moment.date(), time.min, tzinfo=UTC)
            return cls(starts_at=start, ends_at=start + timedelta(days=1))
        start = datetime.combine(moment.date().replace(day=1), time.min, tzinfo=UTC)
        _, length = monthrange(start.year, start.month)
        return cls(starts_at=start, ends_at=start + timedelta(days=length))


#: The key in `Tenant.settings` that holds the lines. Named once, here, so the
#: service that reads it, the test that writes it and the docstring that
#: describes it cannot come to spell it differently.
THRESHOLDS_SETTING = "usage_thresholds"


@dataclass(frozen=True)
class Threshold:
    """One configured line: this meter, over this window, at this quantity.

    **Tenant configuration, not platform policy** (ADR usage-1). The platform
    owns the mechanism — notice a total passing a line — and never an opinion
    about where the line is. A deployment with no lines configured is the normal
    case and costs nothing: `services.record_usage` issues no aggregate query at
    all when this list is empty, which is the ratified fast-path criterion.
    """

    meter: str
    kind: PeriodKind
    quantity: Decimal

    @classmethod
    def from_setting(cls, raw: Any) -> Threshold:
        """Parse one line out of `Tenant.settings`, or say precisely what is wrong.

        `ValueError` with a sentence, never a silent skip: this is somebody's
        configuration, and a threshold that quietly does not exist is the same
        defect as a poller that was never built. What the CALLER does with the
        complaint is its decision — `selectors.list_thresholds` logs and drops,
        because metering must not stop because a config line is malformed.
        """
        if not isinstance(raw, dict):
            raise ValueError(f"a threshold is an object with meter/period/quantity; got {raw!r}")
        missing = sorted({"meter", "period", "quantity"} - set(raw))
        if missing:
            raise ValueError(f"a threshold is missing {', '.join(missing)}")
        meter = raw["meter"]
        if not isinstance(meter, str) or not meter:
            raise ValueError(f"`meter` is a declared meter name; got {meter!r}")
        try:
            kind = PeriodKind(raw["period"])
        except ValueError:
            allowed = ", ".join(sorted(member.value for member in PeriodKind))
            raise ValueError(f"`period` is one of {allowed}; got {raw['period']!r}") from None
        try:
            # Through `str` so that a JSON number that arrived as a float does
            # not carry its binary approximation into a comparison against a
            # Decimal total. House rule 15's reasoning, at the config boundary.
            quantity = Decimal(str(raw["quantity"]))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"`quantity` is a number; got {raw['quantity']!r}") from None
        if quantity <= 0:
            raise ValueError(f"`quantity` is above zero; got {quantity}")
        return cls(meter=meter, kind=kind, quantity=quantity)
