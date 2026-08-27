"""The seam: what `record_usage` promises, and what it refuses.

Every test here is one of the ratified criteria for this app, and the ones that
are the *reason* this app lands first are named as such: the signature two other
apps are being built against, the idempotent replay, the supersede semantics and
the no-thresholds fast path.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import Conflict, Invalid
from apps.core.lifecycle import AppendOnlyViolation
from apps.core.models import Tenant
from apps.core.services import update_tenant_settings
from apps.events.models import Event
from apps.usage.events import THRESHOLD_CROSSED
from apps.usage.models import UsageEntry
from apps.usage.services import record_correction, record_usage
from apps.usage.tests.conftest import METER, OTHER_METER, World
from apps.usage.types import THRESHOLDS_SETTING

pytestmark = pytest.mark.django_db

#: What the ADR fixes, keyword for keyword, because `apps/files` and
#: `apps/completions` are being written against it in the same cycle.
SEAM_SIGNATURE = (
    "tenant",
    "actor",
    "meter",
    "quantity",
    "ref",
    "idempotency_key",
    "occurred_at",
)


def _record(world: World, **overrides: Any) -> UsageEntry:
    """One recording, with the world's own defaults. Keeps the tests about the point."""
    call: dict[str, Any] = {
        "tenant": world.tenant,
        "actor": world.north_actor,
        "meter": METER,
        "quantity": Decimal("100"),
        "ref": world.widget,
        "idempotency_key": "run-1",
    }
    call.update(overrides)
    return record_usage(**call)


def _crossings(tenant: Tenant) -> list[Event]:
    return list(
        Event.objects.for_tenant(tenant).filter(name=THRESHOLD_CROSSED).order_by("created_at")
    )


# --- the seam itself ---------------------------------------------------------


def test_the_seam_signature_is_the_adrs_keyword_for_keyword() -> None:
    """**The cycle's first criterion.** Two apps are being built against this.

    Asserted on the signature rather than on a call, because a call that happens
    to work says nothing about a keyword nobody used yet — and the two consumers
    (`apps/files` at finalize, `apps/completions` after a run) write their calls
    from this list before they can run them.
    """
    signature = inspect.signature(record_usage)
    assert tuple(signature.parameters) == SEAM_SIGNATURE
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    assert signature.parameters["occurred_at"].default is None


def test_recording_writes_the_row_the_ledger_promises(world: World, a_declared_meter: str) -> None:
    entry = _record(world)
    assert entry.meter == METER
    assert entry.quantity == Decimal("100.0000")
    assert entry.ref_type == "example.Widget"
    assert entry.ref_id == world.widget.pk
    # ADR core-20: at the acting hat, never the root.
    assert entry.organization_id == world.north.pk
    assert entry.supersedes_id is None
    assert entry.superseded_because == ""


def test_an_undeclared_meter_never_reaches_the_ledger(world: World) -> None:
    """No registry entry, no row — the typo is refused before anything is written."""
    with pytest.raises(Invalid) as refusal:
        _record(world, meter="example.widgets.conut")
    assert "meter" in refusal.value.errors
    assert UsageEntry.objects.count() == 0


def test_a_call_with_no_acting_hat_is_refused(world: World, a_declared_meter: str) -> None:
    """Fails closed rather than landing at the root (ADR core-20).

    Usage recorded at the root is one branch's spending charged to the whole
    tenant, and no read afterwards can tell you it happened.
    """
    hatless = actor_for(user=world.owner, tenant=world.tenant, org=None)
    with pytest.raises(Invalid) as refusal:
        _record(world, actor=hatless)
    assert "organization" in refusal.value.errors
    assert UsageEntry.objects.count() == 0


def test_a_recording_with_no_key_is_refused(world: World, a_declared_meter: str) -> None:
    with pytest.raises(Invalid) as refusal:
        _record(world, idempotency_key="   ")
    assert "idempotency_key" in refusal.value.errors


def test_a_negative_quantity_is_legal(world: World, a_declared_meter: str) -> None:
    """A purge answers a storage meter with a negative entry, never a decrement.

    ADR usage-1 says so out loud, and it matters here: a service that refused
    negatives would force the files app to invent a second meter for "released",
    and the total would then be a subtraction somebody has to remember to do.
    """
    entry = _record(world, quantity=Decimal("-42.5"), idempotency_key="purge-1")
    assert entry.quantity == Decimal("-42.5000")


# --- The ratified idempotent replay ---------------------------------------------


def test_the_same_key_and_the_same_payload_returns_the_first_row(
    world: World, a_declared_meter: str
) -> None:
    """**Ratified criterion.** A retry gets its row back, quietly, in-transaction.

    Quietly is the load-bearing word: an `IntegrityError` escaping this call
    would roll back the legitimate finalize that wrapped it, so a retried
    activity would destroy the work it was retrying.
    """
    first = _record(world)
    again = _record(world)
    assert again.pk == first.pk
    assert UsageEntry.objects.count() == 1


def test_the_same_key_with_a_different_quantity_is_a_domain_refusal(
    world: World, a_declared_meter: str
) -> None:
    """**Ratified criterion.** Two calls that disagree are not a retry.

    The table's whole value is that it does not guess which of them was right.
    """
    _record(world)
    with pytest.raises(Conflict) as refusal:
        _record(world, quantity=Decimal("250"))
    assert "already recorded under this idempotency key" in str(refusal.value)
    assert UsageEntry.objects.count() == 1


def test_a_retry_that_resolved_a_different_hat_still_finds_the_first_row(
    world: World, a_declared_meter: str
) -> None:
    """The key is unique per TENANT, so the replay read has to be tenant-wide.

    A read narrowed to the retrying hat would miss the row and then collide with
    the constraint — an `IntegrityError` out of the seam, which is exactly what
    the ratified semantics forbid.
    """
    first = _record(world)
    again = _record(world, actor=world.south_actor)
    assert again.pk == first.pk
    assert again.organization_id == world.north.pk


# --- rule 20 / the runtime belt ----------------------------------------------


def test_an_update_to_a_recorded_entry_is_refused_by_the_belt(
    world: World, a_declared_meter: str
) -> None:
    """**The rung's rule-20 criterion**, and it is one assert because the belt is live.

    `UsageEntry` declares `append_only = True`, so `BaseModel.save` refuses the
    second write to a row of a declaring model. The ledger cannot be edited even
    by somebody holding the instance.
    """
    entry = _record(world)
    entry.quantity = Decimal("1")
    with pytest.raises(AppendOnlyViolation):
        entry.save()
    with pytest.raises(AppendOnlyViolation):
        entry.delete()
    entry.refresh_from_db()
    assert entry.quantity == Decimal("100.0000")


# --- the ratified supersede semantics ----------------------------------------


def test_a_correction_carries_the_full_quantity_and_inherits_when_it_happened(
    world: World, a_declared_meter: str
) -> None:
    """**Ratified criterion.** Record 100, correct to 80: the new row says 80.

    Not a delta of -20, and not a new `occurred_at`. The full quantity is what
    lets a reader holding one row know the answer; the inherited timestamp is
    what keeps the corrected entry in the period it was always in, rather than
    moving a customer's usage into the month somebody noticed the mistake.
    """
    yesterday = datetime.now(UTC) - timedelta(days=1)
    original = _record(world, occurred_at=yesterday)
    correction = record_correction(
        tenant=world.tenant,
        actor=world.north_actor,
        entry=original,
        quantity=Decimal("80"),
        because="the provider re-reported the run at a lower count",
        idempotency_key="run-1-corrected",
    )
    assert correction.quantity == Decimal("80.0000")
    assert correction.occurred_at == original.occurred_at
    assert correction.supersedes_id == original.pk
    assert correction.organization_id == original.organization_id
    # BOTH rows readable — the mistake and the correction. That is the whole
    # difference between a ledger and a table somebody tidied.
    assert UsageEntry.objects.count() == 2
    original.refresh_from_db()
    assert original.quantity == Decimal("100.0000")
    assert original.is_superseded is True


def test_a_correction_with_no_reason_is_refused(world: World, a_declared_meter: str) -> None:
    """A superseding row with no reason is an edit wearing a new row's clothes."""
    original = _record(world)
    with pytest.raises(Invalid) as refusal:
        record_correction(
            tenant=world.tenant,
            actor=world.north_actor,
            entry=original,
            quantity=Decimal("80"),
            because="  ",
            idempotency_key="run-1-corrected",
        )
    assert "because" in refusal.value.errors
    assert UsageEntry.objects.count() == 1


def test_an_entry_is_corrected_at_most_once(world: World, a_declared_meter: str) -> None:
    """And the refusal says where the correction goes instead.

    The uniqueness is load-bearing rather than tidy: every total excludes
    superseded rows by joining the reverse relation, and a relation that could
    match twice would double the excluded row inside a `SUM`.
    """
    original = _record(world)
    record_correction(
        tenant=world.tenant,
        actor=world.north_actor,
        entry=original,
        quantity=Decimal("80"),
        because="first correction",
        idempotency_key="fix-1",
    )
    with pytest.raises(Conflict) as refusal:
        record_correction(
            tenant=world.tenant,
            actor=world.north_actor,
            entry=original,
            quantity=Decimal("70"),
            because="second correction of the same row",
            idempotency_key="fix-2",
        )
    assert "already been corrected" in str(refusal.value)


def test_correcting_a_correction_is_legal(world: World, a_declared_meter: str) -> None:
    """The chain grows forward; the newest row is the one that counts."""
    original = _record(world)
    first = record_correction(
        tenant=world.tenant,
        actor=world.north_actor,
        entry=original,
        quantity=Decimal("80"),
        because="first correction",
        idempotency_key="fix-1",
    )
    second = record_correction(
        tenant=world.tenant,
        actor=world.north_actor,
        entry=first,
        quantity=Decimal("75"),
        because="and again, on a later reconciliation",
        idempotency_key="fix-2",
    )
    assert second.supersedes_id == first.pk
    assert UsageEntry.objects.count() == 3


def test_a_correction_across_tenants_is_refused(
    world: World, other_tenant: Tenant, a_declared_meter: str
) -> None:
    original = _record(world)
    with pytest.raises(Invalid) as refusal:
        record_correction(
            tenant=other_tenant,
            actor=world.north_actor,
            entry=original,
            quantity=Decimal("80"),
            because="a neighbour reaching across the fence",
            idempotency_key="fix-1",
        )
    assert "entry" in refusal.value.errors


# --- the ratified fast path --------------------------------------------------


def test_with_no_thresholds_configured_recording_issues_no_aggregate_query(
    world: World, a_declared_meter: str, django_assert_num_queries: Any
) -> None:
    """**Ratified criterion**, pinned by rule 5's instrument: ZERO aggregate queries.

    The normal case — no tenant has configured a threshold — must cost nothing on
    the hottest write path in the product. The count is a ceiling on the whole
    call, and the assertion under it is the one that names the property: no
    statement in this call aggregates.
    """
    with django_assert_num_queries(RECORD_QUERY_BUDGET) as captured:
        _record(world)
    statements = [query["sql"] for query in captured.captured_queries]
    assert not [sql for sql in statements if "SUM(" in sql.upper()], statements


#: What one recording costs with no thresholds configured, **measured** on this
#: tree rather than guessed. The thirteen statements, in the
#: order they run:
#:
#:   1  SAVEPOINT — `@service`'s transaction
#:   2  the tenant's root organization
#:   3  the replay read on the idempotency key
#:   4-5 `full_clean`: the tenant FK exists, the organization FK exists
#:   6-7 `full_clean`: the pk is free, the (tenant, idempotency_key) pair is free
#:   8-10 SAVEPOINT / the check constraint / RELEASE — `validate_constraints`
#:   11 the INSERT
#:   12 the audit row `@service` writes
#:   13 RELEASE SAVEPOINT
#:
#: **Nine of the thirteen are `full_clean` and the transaction machinery**, which
#: is the house write shape and is left alone here on purpose: the
#: criterion is that no statement AGGREGATES, and trading the validation for
#: speed is a decision about the whole template rather than about this app. The
#: number is the evidence behind the ADR trigger written down here — the first
#: per-REQUEST meter turns this path from a per-activity cost into a per-request
#: one, and that is when buffered ingestion gets designed.
#:
#: It may fall and never rise without a diff a reviewer reads.
RECORD_QUERY_BUDGET = 13


# --- the crossing ------------------------------------------------------------


def _configure_threshold(world: World, *, quantity: str, period: str = "month") -> None:
    update_tenant_settings(
        tenant=world.tenant,
        values={
            THRESHOLDS_SETTING: [
                {"meter": METER, "period": period, "quantity": quantity},
            ]
        },
        actor=system_actor(tenant=world.tenant),
    )
    world.tenant.refresh_from_db()


def test_crossing_a_configured_line_says_so_once(world: World, a_declared_meter: str) -> None:
    """The event fires on the write that moved the total past the line, and once.

    A second entry that leaves the total ABOVE the line does not fire again: the
    line was already crossed, and a subscriber told twice cannot tell a new fact
    from a repeat.
    """
    _configure_threshold(world, quantity="150")
    _record(world, quantity=Decimal("100"), idempotency_key="run-1")
    assert _crossings(world.tenant) == []
    _record(world, quantity=Decimal("100"), idempotency_key="run-2")
    crossed = _crossings(world.tenant)
    assert len(crossed) == 1
    payload = crossed[0].payload
    assert payload["meter"] == METER
    assert payload["threshold"] == "150"
    assert payload["total"]["value"] == "200.0000"
    assert payload["total"]["basis"]["formula"] == "sum(day_totals)"
    _record(world, quantity=Decimal("100"), idempotency_key="run-3")
    assert len(_crossings(world.tenant)) == 1


def test_a_retried_recording_never_double_fires_a_crossing(
    world: World, a_declared_meter: str
) -> None:
    """One of the two cases ADR usage-1 names by name.

    The replay returns the first row before the crossing check is ever reached,
    so the dedupe costs no table and no second uniqueness.
    """
    _configure_threshold(world, quantity="50")
    _record(world, quantity=Decimal("100"))
    _record(world, quantity=Decimal("100"))
    assert len(_crossings(world.tenant)) == 1


def test_a_correction_downward_does_not_fire_a_crossing(
    world: World, a_declared_meter: str
) -> None:
    """The other case ADR usage-1 names. A correction lowers the total; nothing crossed."""
    _configure_threshold(world, quantity="150")
    _record(world, quantity=Decimal("200"))
    assert len(_crossings(world.tenant)) == 1
    original = UsageEntry.objects.get(idempotency_key="run-1")
    record_correction(
        tenant=world.tenant,
        actor=world.north_actor,
        entry=original,
        quantity=Decimal("80"),
        because="the provider re-reported the run at a lower count",
        idempotency_key="run-1-corrected",
    )
    assert len(_crossings(world.tenant)) == 1


def test_a_line_on_another_meter_is_not_this_meters_business(
    world: World, a_declared_meter: str
) -> None:
    update_tenant_settings(
        tenant=world.tenant,
        values={THRESHOLDS_SETTING: [{"meter": OTHER_METER, "period": "month", "quantity": "1"}]},
        actor=system_actor(tenant=world.tenant),
    )
    world.tenant.refresh_from_db()
    _record(world, quantity=Decimal("1000"))
    assert _crossings(world.tenant) == []


def test_a_malformed_threshold_line_never_stops_a_recording(
    world: World, a_declared_meter: str
) -> None:
    """**Metering observes and never refuses** (ADR usage-1, the owner's word).

    A typo in one tenant's settings must not stop that tenant's usage being
    recorded: the row is money and the threshold is a notification. The bad line
    is logged and dropped; the good line beside it still fires.
    """
    update_tenant_settings(
        tenant=world.tenant,
        values={
            THRESHOLDS_SETTING: [
                {"meter": METER, "period": "fortnight", "quantity": "1"},
                "not even an object",
                {"meter": METER, "period": "month", "quantity": "50"},
            ]
        },
        actor=system_actor(tenant=world.tenant),
    )
    world.tenant.refresh_from_db()
    entry = _record(world, quantity=Decimal("100"))
    assert entry.pk is not None
    assert len(_crossings(world.tenant)) == 1


def test_the_crossing_is_measured_tenant_wide_across_branches(
    world: World, a_declared_meter: str
) -> None:
    """A threshold is tenant configuration, so the total it watches is the tenant's.

    Two branches each under the line, together over it: the line is crossed. A
    check that measured only the recording branch's own subtree would let a
    tenant quietly exceed a limit it had set for itself.
    """
    _configure_threshold(world, quantity="150")
    _record(world, quantity=Decimal("100"), actor=world.north_actor, idempotency_key="n-1")
    assert _crossings(world.tenant) == []
    _record(world, quantity=Decimal("100"), actor=world.south_actor, idempotency_key="s-1")
    assert len(_crossings(world.tenant)) == 1
