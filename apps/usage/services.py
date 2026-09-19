"""Writes for the usage app. **Two of them, and neither has a door.**

This module is the seam every other ingredient imports: `apps/files` calls
`record_usage` when an upload finalises with the verified byte size,
`apps/completions` calls it from the activity that ran a model. That is why this
app lands first and alone — a seam is code, not prose.

**Why there is no write door, stated where somebody would add one.** A REST or
MCP route that recorded usage would let a client mint its own bill; one that
edited an entry would let a client dispute it into nothing. So both services
below carry rule 42's `# door:` valve, and the reason on each is the ADR's own.
The read door reads `selectors.get_usage`.

**Why recording does not ask permission.** `record_usage` takes an `actor` and
never calls `require`. That is rule 13's `# authz:` escape hatch used with its
reason: metering is the platform's witnessed side-effect of an action that was
already authorized at the door that started it — the completion ran, the file was
stored — and the actor is carried so the audit row `@service` writes says who
caused it, not so anybody can be refused. A `usage.record` predicate would be a
permission nobody could ever fail.

Refusals are `apps.core.exceptions` and nothing else: no `HttpError`, no status
code (house rule 14).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import models

from apps.core.actor import Actor
from apps.core.exceptions import Conflict, Invalid, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.service import service
from apps.core.services import root_organization
from apps.core.time import now
from apps.events.services import emit
from apps.usage.events import THRESHOLD_CROSSED
from apps.usage.meters import check_meter
from apps.usage.models import UsageEntry
from apps.usage.schemas import ThresholdCrossingOut, UsageEntryOut
from apps.usage.selectors import get_meter_measure, list_thresholds
from apps.usage.types import Period

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime

log = get_logger("apps.usage.services")

#: What may appear un-redacted in this app's log lines and audit `input`
#: (`core.service`). An allow-list, not a blocklist. `meter` is a name from a
#: declared vocabulary, `idempotency_key` is a machine's label for a unit of work
#: it just did, and `quantity` is the number the row is ABOUT — a usage audit row
#: that could not say how much was recorded would be an audit of nothing. None of
#: the three is a fact about a person.
LOG_KEYS: frozenset[str] = frozenset({"meter", "idempotency_key", "quantity"})


def _replay_of(
    *, tenant: Tenant, root: Organization, idempotency_key: str, meter: str, quantity: Decimal
) -> UsageEntry | None:
    """The row this key already wrote, or `None`. **A retry may not change its mind.**

    The ratified idempotent-replay semantics, both halves. Same key and same
    payload returns the first row **quietly, inside the caller's transaction** —
    an `IntegrityError` escaping from here would roll back the legitimate
    finalize that wrapped this call, so a retried activity would destroy the work
    it was retrying. Same key and a *different* quantity is a domain refusal,
    because the two calls disagree about what happened and this table's whole
    value is that it does not guess.

    The read is tenant-wide (`visible_to(root)`) because the key is unique per
    TENANT: a retry that resolved a different acting hat still has to find the
    first row, and a read narrowed to the retrying hat would miss it and then
    collide with the constraint.
    """
    existing = (
        UsageEntry.objects.for_tenant(tenant)
        .visible_to(root)
        .filter(idempotency_key=idempotency_key)
        .first()
    )
    if existing is None:
        return None
    if existing.meter != meter or existing.quantity != quantity:
        raise Conflict(
            f"Usage was already recorded under this idempotency key as "
            f"{existing.quantity} of {existing.meter!r}, and this call says "
            f"{quantity} of {meter!r}. A key names one unit of work: a retry repeats "
            f"itself, and a correction is a superseding entry that says why."
        )
    log.info(
        "usage.entry.replayed",
        entry_id=str(existing.pk),
        meter=meter,
        idempotency_key=idempotency_key,
    )
    return existing


def _announce_a_crossing(
    *,
    tenant: Tenant,
    actor: Actor,
    root: Organization,
    entry: UsageEntry,
    delta: Decimal,
) -> None:
    """Emit `usage.threshold.crossed` for each configured line this entry moved past.

    **The fast path is the first line and it is a ratified criterion**: a tenant
    with no thresholds configured issues **zero** aggregate queries here.
    `list_thresholds` reads `Tenant.settings`, which the caller already holds, so
    a deployment that never configures a threshold — the normal case — pays
    nothing on the hottest write path in the product.

    **The dedupe is the straddle, not a table.** A line fires only for the write
    whose own contribution moved the total across it (`before < line <= after`),
    and `delta` is that contribution — the entry's quantity, less whatever the
    entry it supersedes was contributing to the same window. So the two cases ADR
    usage-1 names never double-fire: a **retried activity** gets its first row
    back before ever reaching here, and a **superseding correction** moves the
    total by the difference, which straddles upward only if the correction was
    upward.

    DOES NOT COVER, declared: two concurrent recordings that each straddle the
    same line can each read the same `before` under READ COMMITTED and both fire.
    The window is one statement wide and the consequence is a duplicate
    notification rather than a wrong number — no total moves — so it is recorded
    here rather than paid for with a serialised read on every metered call.
    Trigger: the first observed duplicate crossing, which turns this into the
    uniqueness row ADR usage-1 sketches.
    """
    lines = [line for line in list_thresholds(tenant=tenant) if line.meter == entry.meter]
    for line in lines:
        period = Period.containing(entry.occurred_at, line.kind)
        total = get_meter_measure(tenant=tenant, org=root, meter=entry.meter, period=period)
        before = total.value - delta
        if not (before < line.quantity <= total.value):
            continue
        crossing = ThresholdCrossingOut(
            # The ENTRY's branch, not `root` and not the actor's hat: the two
            # differ exactly when somebody writes downward, and a hat-stamped
            # event is a WRONG branch rather than a wide one (ADR realtime-2a).
            organization_id=entry.organization_id,
            meter=entry.meter,
            period=line.kind.value,
            period_starts_on=period.starts_at.date(),
            period_ends_on=period.days()[-1],
            threshold=line.quantity,
            total=total,
            crossed_by=UsageEntryOut.from_orm(entry),
        )
        emit(
            name=THRESHOLD_CROSSED,
            tenant=tenant,
            payload=crossing.model_dump(mode="json"),
            actor=actor,
        )


# door: recording is not a capability anybody asks for — it is the platform's
# witnessed side-effect of an action a door already authorized, and a route or a
# tool that reached this would let a client MINT ITS OWN BILL (ADR usage-1, §
# Doors: "deliberately door-less: writes"). Its callers are the activities and
# services that spend the money — `apps/files` at finalize, `apps/completions`
# after a run — and the read door reads the ledger it writes.
@service
def record_usage(
    *,
    tenant: Tenant,
    actor: Actor,
    meter: str,
    quantity: Decimal,
    ref: models.Model,
    idempotency_key: str,
    occurred_at: datetime | None = None,
) -> UsageEntry:
    """Witness one consumption. **The seam every other ingredient imports.**

    The signature is ADR usage-1's, keyword for keyword, because two other apps
    are being built against it in the same cycle.

    `meter` is a declared name (`apps/usage/meters.py`) and an undeclared one is
    refused before a row exists — a typo would otherwise accrue money under a
    name no aggregate sums and no threshold matches.

    `quantity` is a `Decimal` in the meter's own unit and **may be negative**:
    that is how a storage meter answers a purge (ADR usage-1 — a negative entry,
    never a decrement of something).

    `ref` is the row that caused it; its model label and primary key are stored,
    the way `core.AuditEntry` stores an object, so "everything this completion
    accrued" is an indexed equality rather than a `LIKE`.

    `idempotency_key` is required and it is the whole of the idempotency contract: an activity
    Temporal retries hands the same key and gets the same row back, inside the caller's own
    transaction. A key that comes back with a **different** quantity is a `Conflict` — see
    `_replay_of`.

    `occurred_at` defaults to now and is the time the consumption HAPPENED, which
    is what the period totals bucket by: an activity that retried for an hour, or
    a provider reporting yesterday's bytes, must not move a customer's usage
    across a month boundary because a worker was slow.

    **Where the row lands** (ADR core-20): at the acting hat, never at the root.
    There is no `organization=` parameter, so no caller can put another branch's
    consumption on somebody else's ledger. An actor with no resolved hat is
    refused rather than defaulted, because usage landed at the root is a branch's
    spending silently attributed to the whole tenant — and the org is what makes a
    branch admin's report honest.

    **Declared blind spot on `ref`**: it is annotated `models.Model` rather than
    an org-scoped model, so house rule 26's reachability check does not read it,
    and nothing here asks whether the actor could have named that row. Today's
    callers hand over a row they wrote microseconds earlier in the same
    transaction, and there is no door through which a stranger could name one.
    That holds only while this service stays doorless, which the valve above says
    it will.
    """
    # authz: recording is the platform's witnessed side-effect of an
    # already-authorized action; the actor is carried for audit, not asked for
    # permission. ADR usage-1's own wording, and it is the whole reason there is
    # no `usage.record` predicate: the completion already ran and the file was
    # already stored, at a door that authorized them, and a permission that
    # could refuse the RECORDING of what happened would produce a deployment
    # that spent money it has no row for.
    check_meter(meter)
    if not idempotency_key.strip():
        raise Invalid(
            {
                "idempotency_key": [
                    "Recording usage needs a key naming the unit of work it is for. A "
                    "metering call with no key double-bills on the retry Temporal is "
                    "guaranteed to make."
                ]
            }
        )
    if actor.org is None:
        raise Invalid(
            {
                "organization": [
                    "This call resolved no acting organization, so there is nobody to "
                    "attribute the consumption to. Usage recorded at the root would be "
                    "one branch's spending charged to the whole tenant."
                ]
            }
        )
    # The tenant's root: the ONE query this service pays before the write, and it
    # buys two things — the tenant-wide replay read (the key is unique per TENANT)
    # and the tenant-wide total a threshold is measured against.
    root = root_organization(tenant=tenant)
    existing = _replay_of(
        tenant=tenant,
        root=root,
        idempotency_key=idempotency_key,
        meter=meter,
        quantity=quantity,
    )
    if existing is not None:
        return existing
    entry = UsageEntry(
        tenant=tenant,
        organization=actor.org,
        meter=meter,
        quantity=quantity,
        occurred_at=occurred_at or now(),
        ref_type=ref._meta.label,
        ref_id=ref.pk,
        idempotency_key=idempotency_key,
    )
    with as_invalid():
        entry.full_clean()
    entry.save()
    _announce_a_crossing(tenant=tenant, actor=actor, root=root, entry=entry, delta=quantity)
    return entry


# door: the correction half of the same seam, door-less for the same reason with
# one more on top — a client that could supersede an entry could dispute its own
# bill down to nothing. A correction is made by whoever can see that the recorded
# number was wrong, which is the platform, and it leaves BOTH rows readable so a
# customer can see what changed.
@service
def record_correction(
    *,
    tenant: Tenant,
    actor: Actor,
    # reach: the platform corrects its own ledger and holds no hat — a
    # reconciliation activity, or an operator answering a provider that
    # re-reported a run. `may_be_named` would refuse every one of them, because
    # it answers "could this actor have reached this row through a door" and
    # there is no door to this table at all (the two `# door:` valves here say
    # so). What bounds the reference instead is the tenant check below, which is
    # the boundary the caller could actually get wrong.
    entry: UsageEntry,
    quantity: Decimal,
    because: str,
    idempotency_key: str,
) -> UsageEntry:
    """Answer a wrong entry with a new one. **Never edit; the belt refuses it anyway.**

    The ratified supersede semantics, and every half of them matters:

    * the superseding row carries the **corrected FULL quantity**, not a delta.
      Record 100, correct to 80, and the new row says 80 — so a reader holding one
      row knows what the answer is without finding and adding its siblings;
    * it **inherits the original's `occurred_at`**, because a correction does not
      move when the thing happened. That is what keeps a corrected entry in the
      period it was always in, rather than moving a customer's usage into the
      month somebody noticed the mistake;
    * it lands in the **original's organization**, not the corrector's acting hat.
      ADR core-20's placement law is about a create choosing a branch; this row
      does not choose one — it answers a row that already has one, and landing it
      anywhere else would take the mistake off one branch's ledger and put the
      correction on another's.

    Every aggregate then skips the row this one points at (`selectors._ledger`),
    so the period total is 80 while both rows stay readable — which is the whole
    difference between a ledger and a table somebody tidied.

    A row is corrected at most once (`usageentry_one_correction_per_entry`), and
    correcting a correction is legal: the chain grows forward, each link
    superseding the previous one.
    """
    # authz: the same valve `record_usage` carries, for the same reason — this
    # writes the platform's own witnessed correction of its own ledger, and the
    # actor is carried so the audit row says who caused it rather than so
    # anybody can be refused. What a PERSON may do with this table is read it
    # (`usage_entry.read`, the derived key `policies.py` gives the sentence and
    # the alias for), and that key is asked in `selectors.get_usage`.
    check_meter(entry.meter)
    if not because.strip():
        raise Invalid(
            {
                "because": [
                    "A correction says why. A superseding row with no reason is an edit "
                    "wearing a new row's clothes, and the reason is what a customer "
                    "disputing the number gets to read."
                ]
            }
        )
    if entry.tenant_id != tenant.pk:
        # A service never trusts that the caller resolved its object correctly
        # (django-conventions §2). Everywhere a client can reach, not-there and
        # not-yours are one answer; here the caller is the platform and the
        # honest complaint is that its two arguments disagree.
        raise Invalid({"entry": ["That entry belongs to another tenant."]})
    root = root_organization(tenant=tenant)
    existing = _replay_of(
        tenant=tenant,
        root=root,
        idempotency_key=idempotency_key,
        meter=entry.meter,
        quantity=quantity,
    )
    if existing is not None:
        return existing
    if entry.superseded_by.exists():
        raise Conflict(
            "That entry has already been corrected. Correct the correction — the "
            "chain grows forward, so the newest row is the one that counts."
        )
    correction = UsageEntry(
        tenant=tenant,
        organization=entry.organization,
        meter=entry.meter,
        quantity=quantity,
        occurred_at=entry.occurred_at,
        ref_type=entry._meta.label,
        ref_id=entry.pk,
        idempotency_key=idempotency_key,
        supersedes=entry,
        superseded_because=because,
    )
    with as_invalid():
        correction.full_clean()
    correction.save()
    # The delta is the DIFFERENCE, because this write both adds a row and removes
    # the one it supersedes from every total.
    _announce_a_crossing(
        tenant=tenant,
        actor=actor,
        root=root,
        entry=correction,
        delta=quantity - entry.quantity,
    )
    return correction
