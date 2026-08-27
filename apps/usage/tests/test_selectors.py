"""The read: what a period total is, whose it is, and what it leaves out.

Three properties, and each of them can be wrong in a way that looks right:

* the **basis re-adds** — `value` equals the sum of `basis.inputs` (ADR core-7).
  A total whose basis does not add up is a number two doors will
  eventually disagree about;
* the **correction is excluded** — record 100, supersede with 80, the period says
  80 (the ratified supersede semantics);
* the **hat narrows** — a branch's report never tallies a sibling's consumption,
  and the anti-oracle is the sibling that exists to make the zero a measurement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import Forbidden
from apps.core.models import Tenant
from apps.core.schemas import MeasuredOut
from apps.core.services import update_tenant_settings
from apps.usage.selectors import ZERO, get_usage, list_thresholds
from apps.usage.services import record_correction, record_usage
from apps.usage.tests.conftest import METER, OTHER_METER, World
from apps.usage.types import THRESHOLDS_SETTING, Period, PeriodKind

pytestmark = pytest.mark.django_db

#: A fixed instant, so a test that runs at 23:59:59 UTC does not bucket its rows
#: into two different days and fail once a day for reasons nobody can reproduce.
NOON = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

MONTH = Period.containing(NOON, PeriodKind.MONTH)

#: What one period read costs, measured on this tree: the
#: membership read `require` performs, and the one grouped aggregate. It does not
#: grow with the number of days or meters — that is the property the pin exists
#: to hold — so it may fall and never rise without a diff a reviewer reads.
READ_QUERY_BUDGET = 2


def _record(world: World, **overrides: Any) -> Any:
    call: dict[str, Any] = {
        "tenant": world.tenant,
        "actor": world.north_actor,
        "meter": METER,
        "quantity": Decimal("100"),
        "ref": world.widget,
        "idempotency_key": "run-1",
        "occurred_at": NOON,
    }
    call.update(overrides)
    return record_usage(**call)


def _readds(measured: MeasuredOut) -> bool:
    """Whether the value equals what the basis says it was summed from."""
    return measured.value == sum(measured.basis.inputs.values(), ZERO)


def test_the_value_is_the_sum_of_the_days_it_says_it_summed(
    world: World, a_declared_meter: str
) -> None:
    """A reader can check the arithmetic without a second request.

    Two entries on two different days, so the basis has something to be wrong
    about: a formula of `sum(day_totals)` over a basis with one key would be a
    total that only looks re-addable.
    """
    _record(world, quantity=Decimal("30"), idempotency_key="d1")
    _record(
        world, quantity=Decimal("12.5"), occurred_at=NOON + timedelta(days=1), idempotency_key="d2"
    )
    measured = get_usage(tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert measured.value == Decimal("42.5")
    assert measured.basis.formula == "sum(day_totals)"
    assert measured.basis.inputs["2026-08-12"] == Decimal("30")
    assert measured.basis.inputs["2026-08-13"] == Decimal("12.5")
    assert _readds(measured)


def test_the_basis_carries_every_day_in_the_window_including_the_empty_ones(
    world: World, a_declared_meter: str
) -> None:
    """A basis with the zeroes missing cannot be told from a basis with days lost."""
    _record(world, quantity=Decimal("30"), idempotency_key="d1")
    measured = get_usage(tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert len(measured.basis.inputs) == 31
    assert measured.basis.inputs["2026-08-01"] == ZERO
    assert _readds(measured)


def test_a_correction_moves_the_total_and_leaves_both_rows_readable(
    world: World, a_declared_meter: str
) -> None:
    """**The ratified criterion, end to end: record 100, supersede with 80 → 80.**"""
    original = _record(world, quantity=Decimal("100"))
    correction = record_correction(
        tenant=world.tenant,
        actor=world.north_actor,
        entry=original,
        quantity=Decimal("80"),
        because="the provider re-reported the run at a lower count",
        idempotency_key="run-1-corrected",
    )
    measured = get_usage(tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert measured.value == Decimal("80")
    assert _readds(measured)
    # Both rows readable: the mistake, and what it was corrected to.
    original.refresh_from_db()
    assert original.quantity == Decimal("100.0000")
    assert correction.quantity == Decimal("80.0000")


def test_a_meter_that_was_asked_for_and_never_fired_reports_zero(
    world: World, a_declared_meter: str
) -> None:
    """Zero is an answer; a missing key is a question the caller cannot tell apart."""
    _record(world, quantity=Decimal("30"))
    report = get_usage(
        tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER, OTHER_METER]
    )
    assert set(report) == {METER, OTHER_METER}
    assert report[OTHER_METER].value == ZERO
    assert _readds(report[OTHER_METER])


def test_a_branch_report_never_tallies_a_siblings_consumption(
    world: World, a_declared_meter: str
) -> None:
    """**The anti-oracle, one level down.** The sibling is what makes the zero a measurement."""
    _record(world, quantity=Decimal("100"), actor=world.north_actor, idempotency_key="n-1")
    _record(world, quantity=Decimal("40"), actor=world.south_actor, idempotency_key="s-1")

    north = get_usage(tenant=world.tenant, actor=world.north_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert north.value == Decimal("100")

    root = get_usage(tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert root.value == Decimal("140")

    south = get_usage(tenant=world.tenant, actor=world.south_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert south.value == Decimal("40")


def test_another_tenants_usage_is_absent(
    world: World, other_tenant: Tenant, other_root_org: Any, stranger: Any, a_declared_meter: str
) -> None:
    """The test that cannot pass vacuously: the neighbour has rows, and they are not here."""
    _record(world, quantity=Decimal("100"))
    neighbour = actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
    record_usage(
        tenant=other_tenant,
        actor=neighbour,
        meter=METER,
        quantity=Decimal("999"),
        ref=world.widget,
        idempotency_key="theirs-1",
        occurred_at=NOON,
    )
    mine = get_usage(tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER])[
        METER
    ]
    assert mine.value == Decimal("100")
    theirs = get_usage(tenant=other_tenant, actor=neighbour, period=MONTH, meters=[METER])[METER]
    assert theirs.value == Decimal("999")


def test_an_actor_with_no_hat_reads_an_empty_ledger(world: World, a_declared_meter: str) -> None:
    """`visible_to(None)` fails closed, so an unresolved hat reads nothing at all."""
    _record(world, quantity=Decimal("100"))
    hatless = actor_for(user=world.owner, tenant=world.tenant, org=None)
    measured = get_usage(tenant=world.tenant, actor=hatless, period=MONTH, meters=[METER])[METER]
    assert measured.value == ZERO


def test_a_stranger_to_the_tenant_is_refused(
    world: World, nomad: Any, a_declared_meter: str
) -> None:
    """The policy bar is membership, and somebody with none is refused rather than emptied."""
    outsider = actor_for(user=nomad, tenant=world.tenant, org=world.root)
    with pytest.raises(Forbidden):
        get_usage(tenant=world.tenant, actor=outsider, period=MONTH)


def test_a_period_read_costs_one_query(
    world: World, a_declared_meter: str, django_assert_num_queries: Any
) -> None:
    """The day bucketing is a GROUP BY, not a walk: one statement at any number of days.

    Two queries and not one: the policy read (`require` resolves the actor's
    membership) and then the aggregate. The number that matters is that the
    second one does not grow with the days — ten days, one statement.
    """
    for day in range(10):
        _record(
            world,
            quantity=Decimal("1"),
            occurred_at=NOON + timedelta(days=day),
            idempotency_key=f"day-{day}",
        )
    with django_assert_num_queries(READ_QUERY_BUDGET):
        measured = get_usage(
            tenant=world.tenant, actor=world.root_actor, period=MONTH, meters=[METER]
        )[METER]
    assert measured.value == Decimal("10")


# --- the configured lines ----------------------------------------------------


def test_thresholds_are_read_off_the_tenant_and_cost_no_query(
    world: World, django_assert_num_queries: Any
) -> None:
    """The whole reason the fast path is possible: the lines are already in hand."""
    update_tenant_settings(
        tenant=world.tenant,
        values={THRESHOLDS_SETTING: [{"meter": METER, "period": "month", "quantity": "1000"}]},
        actor=system_actor(tenant=world.tenant),
    )
    world.tenant.refresh_from_db()
    with django_assert_num_queries(0):
        lines = list_thresholds(tenant=world.tenant)
    assert [(line.meter, line.kind, line.quantity) for line in lines] == [
        (METER, PeriodKind.MONTH, Decimal("1000"))
    ]


def test_a_tenant_with_no_lines_has_no_lines(world: World) -> None:
    assert list_thresholds(tenant=world.tenant) == []


@pytest.mark.parametrize(
    "line",
    [
        "not an object",
        {"meter": METER, "period": "month"},
        {"meter": METER, "period": "fortnight", "quantity": "1"},
        {"meter": METER, "period": "month", "quantity": "nope"},
        {"meter": METER, "period": "month", "quantity": "-5"},
        {"meter": "", "period": "month", "quantity": "1"},
    ],
)
def test_a_malformed_line_is_dropped_and_the_good_ones_survive(world: World, line: Any) -> None:
    """Dropped, not raised — metering observes and never refuses — but never silently."""
    update_tenant_settings(
        tenant=world.tenant,
        values={THRESHOLDS_SETTING: [line, {"meter": METER, "period": "day", "quantity": "7"}]},
        actor=system_actor(tenant=world.tenant),
    )
    world.tenant.refresh_from_db()
    lines = list_thresholds(tenant=world.tenant)
    assert [(x.meter, x.kind, x.quantity) for x in lines] == [(METER, PeriodKind.DAY, Decimal("7"))]


def test_a_thresholds_setting_that_is_not_a_list_is_dropped_whole(world: World) -> None:
    update_tenant_settings(
        tenant=world.tenant,
        values={THRESHOLDS_SETTING: {"meter": METER}},
        actor=system_actor(tenant=world.tenant),
    )
    world.tenant.refresh_from_db()
    assert list_thresholds(tenant=world.tenant) == []
