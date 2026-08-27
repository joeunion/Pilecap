"""Reads. Every one of them excludes a row that has been corrected.

**The exclusion is the invariant of this module**, so it is stated once here
rather than argued at each call site: an entry a supersede points at is not part
of any total, anywhere. Record 100, correct it to 80, and the period says 80 —
while both rows stay readable, which is what makes the ledger evidence rather
than a table somebody tidied. `_ledger()` below is the one place that filter is
written, and the `usageentry_one_correction_per_entry` constraint on the model is
what makes the join it uses safe inside a `SUM`: a reverse relation that could
match twice would double the row it excluded.

Reads never write (house rule 12), and no function here returns a queryset for
display: they return a `MeasuredOut`, because a total is what a caller asked for
and handing back rows would push the adding-up out to whichever door asked — the
exact failure ADR core-7 exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.db.models.functions import TruncDate

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.log import get_logger
from apps.core.models import Organization, ScopedQuerySet, Tenant
from apps.core.schemas import MeasuredBasisOut, MeasuredOut
from apps.usage.models import UsageEntry
from apps.usage.policies import USAGE_READ_REPORT
from apps.usage.types import THRESHOLDS_SETTING, Period, Threshold

log = get_logger("apps.usage.selectors")

#: What `MeasuredOut.basis.formula` says about every total this module returns.
#: A formula a reader can evaluate over `basis.inputs` themselves — which is the
#: whole contract of ADR core-7 and the criterion this app is checked
#: against: the value equals the recomputation from the inputs.
DAY_SUM_FORMULA = "sum(day_totals)"

#: The one place `Decimal("0")` is spelled for this module. A total of nothing is
#: a total, not an absence: a meter that was asked for and did not fire returns
#: zero with a basis full of zeroed days, so a reader can tell "nothing was
#: consumed" from "I asked the wrong question".
ZERO = Decimal("0")


def list_thresholds(*, tenant: Tenant) -> list[Threshold]:
    """The lines this tenant configured, dropping — loudly — any that do not parse.

    **No query.** The lines live in `Tenant.settings`, which the caller already
    holds, and that is what makes the ratified fast path possible: a deployment
    with no thresholds configured pays nothing on the hot write path, because
    there is nothing to read and therefore nothing to aggregate.

    **Malformed lines are logged and dropped rather than raised**, and the
    asymmetry is deliberate. Metering observes and never refuses (ADR usage-1):
    a typo in one tenant's settings must not stop that tenant's usage being
    recorded, because the row is money and the threshold is a notification.
    Dropping silently would be the other failure — the poller that was never
    built — so each bad line leaves a structured record naming the tenant, the
    line and the complaint.

    **Declared blind spot, handed up rather than closed here**: ADR usage-1 says
    these keys are "schema-validated per the platform table", and there is no
    such table — `core.services.update_tenant_settings` merges arbitrary JSON and
    validates nothing beyond the timezone. So the earliest a bad line can be
    caught today is here, on read, in the tenant's own logs rather than at the
    door that accepted it.
    """
    raw = (tenant.settings or {}).get(THRESHOLDS_SETTING)
    if not raw:
        return []
    if not isinstance(raw, list):
        log.warning(
            "usage.thresholds.malformed",
            tenant_id=str(tenant.pk),
            complaint=f"{THRESHOLDS_SETTING} is a list of lines; got {type(raw).__name__}",
        )
        return []
    lines: list[Threshold] = []
    for index, entry in enumerate(raw):
        try:
            lines.append(Threshold.from_setting(entry))
        except ValueError as complaint:
            log.warning(
                "usage.thresholds.malformed",
                tenant_id=str(tenant.pk),
                line=index,
                complaint=str(complaint),
            )
    return lines


def _ledger(*, tenant: Tenant, viewer: Actor | Organization, period: Period) -> Any:
    """The rows one viewer may count, in one window. **The only queryset here.**

    Both halves of the read (house rule 24): `for_tenant` answers whose data and
    `visible_to` answers which part of their network. Both fail closed, so an
    unresolved tenant or an unresolved hat reads an empty ledger rather than the
    ledger. `viewer` is an `Actor` for a door's read and an `Organization` — the
    tenant's root — for the tenant-wide total a threshold is measured against;
    `visible_to` takes either.

    And the correction exclusion, written once: every total in this app skips a
    row that a later row supersedes.
    """
    rows: ScopedQuerySet[UsageEntry] = (
        UsageEntry.objects.for_tenant(tenant)
        .visible_to(viewer)
        .filter(
            superseded_by__isnull=True,
            occurred_at__gte=period.starts_at,
            occurred_at__lt=period.ends_at,
        )
    )
    return rows


def _measured(rows: Any, *, period: Period, meters: list[str] | None) -> dict[str, MeasuredOut]:
    """Group by meter and UTC day, and wrap each total in its own basis. One query.

    The day bucketing is a `GROUP BY` in the database rather than a walk in
    Python, and `basis.inputs` carries **every** day in the window including the
    empty ones — a basis with the zeroes missing cannot be told from a basis with
    days lost, and re-addability is the whole contract (ADR core-7).
    """
    buckets: list[dict[str, Any]] = list(
        rows.annotate(day=TruncDate("occurred_at", tzinfo=UTC))
        # `.order_by(...)` explicitly, and it is not cosmetic: `BaseModel.Meta`
        # orders by `-created_at`, and a default ordering left in place here
        # would join `created_at` to the GROUP BY and shatter every day bucket
        # into one group per row.
        .values("meter", "day")
        .annotate(subtotal=Sum("quantity"))
        .order_by("meter", "day")
    )
    days = [day.isoformat() for day in period.days()]
    subtotals: dict[str, dict[str, Decimal]] = {}
    for bucket in buckets:
        meter = str(bucket["meter"])
        per_day = subtotals.setdefault(meter, dict.fromkeys(days, ZERO))
        per_day[bucket["day"].isoformat()] = Decimal(bucket["subtotal"])
    for meter in meters or []:
        subtotals.setdefault(meter, dict.fromkeys(days, ZERO))
    return {
        meter: MeasuredOut(
            value=sum(per_day.values(), ZERO),
            basis=MeasuredBasisOut(formula=DAY_SUM_FORMULA, inputs=per_day),
        )
        for meter, per_day in sorted(subtotals.items())
    }


def get_meter_measure(
    *, tenant: Tenant, org: Organization, meter: str, period: Period
) -> MeasuredOut:
    """One meter's total over one window, for everything `org` can see. One query.

    This is the aggregate the crossing check rides, and it takes an
    `Organization` rather than an `Actor` because its caller is a service
    measuring the **tenant-wide** total against a tenant-wide line: it passes the
    tenant's root, which is what ADR usage-1 means by "the tenant total is the
    root's `visible_to(root)` for free". No `require` here for the same reason —
    the caller is the platform recording its own witnessed side-effect, not a
    person asking to see somebody's consumption. The door's read is `get_usage`,
    and that one authorizes.

    It returns the whole `MeasuredOut` rather than a bare `Decimal` because the
    crossing event publishes the basis, and computing the total twice — once to
    compare and once to publish — is how two numbers in one message come to
    disagree.
    """
    rows = _ledger(tenant=tenant, viewer=org, period=period).filter(meter=meter)
    return _measured(rows, period=period, meters=[meter])[meter]


def get_usage(
    *,
    tenant: Tenant,
    actor: Actor,
    period: Period,
    meters: Iterable[str] | None = None,
) -> dict[str, MeasuredOut]:
    """Per-meter totals for the part of the tenant this actor wears, **with the basis**.

    The read ADR usage-1 specifies: `value` is the period total and
    `basis.inputs` are the ISO-date day subtotals it was summed from, so a reader
    can add them up and get the same number. That re-addability is a criterion,
    not a nicety — it is what stops a dashboard, an export and an assistant each
    computing a customer's consumption differently from the same rows.

    `visible_to(actor)` narrows to the actor's own subtree, so a branch admin's
    report never tallies a sibling's tokens; the tenant-wide total is what
    wearing the root hat already means.

    `meters=None` reports whatever the window actually holds. Naming meters
    reports **all of them**, including the ones at zero: an agent asking "how much
    have I used of X" must be able to tell "none" from "I asked the wrong
    question", and a key missing from a mapping cannot say which.

    One query, whatever the number of meters or days.
    """
    # The DECLARATION rather than a literal: the action name is spelled
    # once, in `policies.py`, beside the roles a product narrows. A string
    # re-typed here is an authorization that stops running the day the
    # declaration is renamed, and nothing would say so.
    require(actor, USAGE_READ_REPORT.action)
    wanted = None if meters is None else sorted(set(meters))
    rows = _ledger(tenant=tenant, viewer=actor, period=period)
    if wanted is not None:
        rows = rows.filter(meter__in=wanted)
    return _measured(rows, period=period, meters=wanted)
