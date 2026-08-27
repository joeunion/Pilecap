"""The platform pieces a product starts with: money, time, flags, lifecycle.

Each of these exists because getting it wrong is silent. A float total is out
by a hundredth of a cent; a naive datetime is fine until a daylight-saving
boundary; a flag that defaults on does nothing until somebody notices; a
"closed" tenant that deleted its rows takes the invoice history with it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.core import flags
from apps.core import time as core_time
from apps.core.actor import system_actor
from apps.core.exceptions import Conflict, Invalid
from apps.core.models import Tenant
from apps.core.money import CurrencyMismatch, Money, money_fields
from apps.core.services import (
    close_tenant,
    resume_tenant,
    set_flag,
    suspend_tenant,
    update_tenant_settings,
)

pytestmark = pytest.mark.django_db


# --- Money -------------------------------------------------------------------


def test_a_float_never_becomes_a_float() -> None:
    """`0.1 + 0.2 != 0.3` is the bug; going through `str` is the fix."""
    assert Money(0.1).amount == Decimal("0.1")
    assert (Money(0.1) + Money(0.2)).amount == Decimal("0.3")


def test_amounts_in_different_currencies_refuse_to_combine() -> None:
    """Summing a column whose rows are in three currencies is invisible until
    somebody's report is wrong."""
    with pytest.raises(CurrencyMismatch):
        Money("10", "USD") + Money("10", "EUR")
    with pytest.raises(CurrencyMismatch):
        assert Money("10", "USD") < Money("20", "EUR")


def test_arithmetic_keeps_the_currency() -> None:
    total = Money("10.50", "gbp") * 3
    assert total == Money(Decimal("31.50"), "GBP")
    assert str(total) == "31.50 GBP"
    assert (total - total).is_zero


def test_a_currency_is_three_letters() -> None:
    with pytest.raises(ValueError):
        Money("1", "DOLLARS")


def test_money_is_immutable() -> None:
    """A value, not a variable: a total that could be reassigned in place is a
    total two call sites can disagree about."""
    amount = Money("1")
    with pytest.raises(AttributeError):
        # noqa: B010 — `setattr` on purpose: writing `amount.amount = ...`
        # would be a type error the checker refuses before the test can run it,
        # and the property under test is the runtime refusal.
        setattr(amount, "amount", Decimal("2"))  # noqa: B010


def test_the_columns_are_decimal_and_a_currency_code() -> None:
    amount, currency = money_fields()
    assert amount.max_digits == 19
    assert amount.decimal_places == 4
    assert currency.max_length == 3


# --- Time --------------------------------------------------------------------


def test_now_is_aware_and_utc() -> None:
    moment = core_time.now()
    assert moment.tzinfo is not None
    assert moment.utcoffset() == timedelta(0)


def test_a_day_is_half_open_so_the_last_microsecond_is_not_lost() -> None:
    on = date(2026, 3, 15)
    start = core_time.start_of_day(on, tz="Europe/Lisbon")
    end = core_time.end_of_day(on, tz="Europe/Lisbon")
    assert end - start == timedelta(days=1)
    assert start.tzinfo == ZoneInfo("UTC")


def test_today_depends_on_where_you_ask() -> None:
    """ "Today" is a different day either side of most boundaries."""
    assert core_time.today(tz="Pacific/Kiritimati") >= core_time.today(tz="Pacific/Midway")


def test_a_deadline_of_none_is_not_expired() -> None:
    assert core_time.is_past(None) is False
    assert core_time.is_past(core_time.now() - timedelta(seconds=1)) is True
    assert core_time.is_past(core_time.in_days(1)) is False


def test_tenant_time_is_display_only(tenant: Tenant) -> None:
    stored = datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    shown = core_time.as_tenant_time(stored, tz="Asia/Tokyo")
    assert shown.hour == 21
    assert shown == stored  # the same instant, said differently


# --- Flags -------------------------------------------------------------------


def test_a_flag_nobody_set_is_off(tenant: Tenant) -> None:
    assert flags.is_enabled(tenant, "new_billing") is False


def test_a_deployment_default_reaches_a_tenant_that_says_nothing(
    tenant: Tenant, settings: object
) -> None:
    settings.FEATURE_FLAGS = {"new_billing": True}  # type: ignore[attr-defined]
    assert flags.is_enabled(tenant, "new_billing") is True


def test_a_tenant_overrides_the_deployment_default(tenant: Tenant, settings: object) -> None:
    settings.FEATURE_FLAGS = {"new_billing": True}  # type: ignore[attr-defined]
    set_flag(tenant=tenant, name="new_billing", enabled=False, actor=system_actor(tenant=tenant))
    tenant.refresh_from_db()
    assert flags.is_enabled(tenant, "new_billing") is False


def test_clearing_a_flag_is_different_from_turning_it_off(tenant: Tenant, settings: object) -> None:
    """Finishing a rollout means inheriting the default again, not opting out."""
    settings.FEATURE_FLAGS = {"new_billing": True}  # type: ignore[attr-defined]
    set_flag(tenant=tenant, name="new_billing", enabled=False, actor=system_actor(tenant=tenant))
    tenant.refresh_from_db()
    assert flags.is_enabled(tenant, "new_billing") is False

    set_flag(tenant=tenant, name="new_billing", enabled=None, actor=system_actor(tenant=tenant))
    tenant.refresh_from_db()
    assert flags.is_enabled(tenant, "new_billing") is True


def test_no_tenant_gets_the_deployment_default(settings: object) -> None:
    settings.FEATURE_FLAGS = {"new_billing": True}  # type: ignore[attr-defined]
    assert flags.is_enabled(None, "new_billing") is True


# --- Tenant settings ---------------------------------------------------------


def test_settings_are_merged_not_replaced(tenant: Tenant) -> None:
    """A caller that meant to set one key would otherwise delete every other."""
    update_tenant_settings(
        tenant=tenant,
        values={"brand": "Acme", "support_email": "a@b.c"},
        actor=system_actor(tenant=tenant),
    )
    update_tenant_settings(
        tenant=tenant, values={"brand": "Acme Ltd"}, actor=system_actor(tenant=tenant)
    )
    tenant.refresh_from_db()
    assert tenant.settings == {"brand": "Acme Ltd", "support_email": "a@b.c"}


def test_a_key_is_removed_by_sending_none(tenant: Tenant) -> None:
    update_tenant_settings(
        tenant=tenant, values={"brand": "Acme"}, actor=system_actor(tenant=tenant)
    )
    update_tenant_settings(tenant=tenant, values={"brand": None}, actor=system_actor(tenant=tenant))
    tenant.refresh_from_db()
    assert tenant.settings == {}


def test_a_typo_in_a_timezone_is_refused_now_rather_than_at_render_time(
    tenant: Tenant,
) -> None:
    with pytest.raises(Invalid) as raised:
        update_tenant_settings(
            tenant=tenant, timezone="Europe/Lisbn", actor=system_actor(tenant=tenant)
        )
    assert "timezone" in raised.value.errors

    update_tenant_settings(
        tenant=tenant, timezone="Europe/Lisbon", locale="pt-pt", actor=system_actor(tenant=tenant)
    )
    tenant.refresh_from_db()
    assert tenant.timezone == "Europe/Lisbon"
    assert tenant.locale == "pt-pt"


# --- Lifecycle ---------------------------------------------------------------


def test_suspending_is_reversible_and_deletes_nothing(tenant: Tenant) -> None:
    suspend_tenant(tenant=tenant, reason="unpaid invoice", actor=system_actor(tenant=tenant))
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.SUSPENDED
    assert tenant.suspended_at is not None
    assert tenant.settings["suspension_reason"] == "unpaid invoice"
    assert not tenant.is_active

    resume_tenant(tenant=tenant, actor=system_actor(tenant=tenant))
    resumed = Tenant.objects.get(pk=tenant.pk)
    assert resumed.is_active
    assert resumed.suspended_at is None
    assert "suspension_reason" not in resumed.settings


def test_closing_is_terminal_and_still_not_a_delete(tenant: Tenant) -> None:
    close_tenant(tenant=tenant, actor=system_actor(tenant=tenant))
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.CLOSED
    assert tenant.closed_at is not None
    # The row is still there, which is the point: an audit trail and an invoice
    # history outlive the customer relationship.
    assert Tenant.objects.filter(pk=tenant.pk).exists()

    with pytest.raises(Conflict):
        resume_tenant(tenant=tenant, actor=system_actor(tenant=tenant))
