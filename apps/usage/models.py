"""The ledger. One table, and everything about it is a consequence of one word.

**Append-only.** A usage row is a witnessed fact about money the platform spent
on somebody's behalf, and a fact that can be edited is not evidence. So the
correction convention is a superseding row (ADR usage-1): the
mistake and the correction both stay readable, which is what lets a customer
disputing an invoice see what was recorded, what it was changed to, and why.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import OrgScopedModel
from apps.usage.meters import MAX_METER_LENGTH


class UsageEntry(OrgScopedModel):
    """One witnessed consumption: who, what meter, how much, when, and caused by what.

    **Org-scoped, one level down from the tenant, and that is the anti-oracle.**
    Usage is attributable to the branch that caused it, so a branch admin's usage
    report never tallies a sibling's tokens — `for_tenant(t).visible_to(actor)`
    answers that with no code here at all (house rule 24). The tenant-wide total
    a threshold is measured against is the ROOT's `visible_to(root)`, which comes
    out of the same read for free.

    **No price column, ever.** ADR usage-1 is explicit and it is worth restating
    where somebody would be tempted to add one: this app meters, and a rate is a
    commercial decision that changes retroactively, differs per contract, and
    belongs to whatever product-layer app does invoicing. A `price` here would be
    a second truth that can disagree with the rate card, and the disagreement
    would be discovered on an invoice.

    **No write door, ever.** A client that could mint a usage row could bill
    itself; a client that could edit one could dispute it into nothing. The one
    write seam is `services.record_usage`, reached from activities and services
    under the run's own actor — see rule 42's `# door:` valve on it, which says
    exactly that.
    """

    #: `core.models.is_append_only` reads this; nothing anywhere may update or
    #: delete a row of a model that declares it, and `BaseModel.save`/`delete`
    #: refuse at the last possible moment for the whole declared population.
    #: This is the runtime belt; house rule 20 is the static half.
    append_only: ClassVar[bool] = True

    #: ADR core-13, and coherent with the declaration above rather than a second
    #: opinion about the same table: rule 20 reads `append_only` and asks "may a
    #: row be rewritten"; rule 31 reads this and asks "what happens to these rows
    #: over TIME". The honest answer for a billing ledger is `append_only`, and
    #: the trigger is dated because a decision nobody can age is a decision
    #: nobody will revisit.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.APPEND_ONLY,
        reason=(
            "this is what an invoice is derived from. A customer disputing a bill "
            "eighteen months later is asking a question only these rows can answer, "
            "and a retention window on them is a window inside which the platform "
            "cannot show its working. Growth is real and accepted: the composite "
            "index below is what keeps a big table's period reads cheap, and the "
            "rollup ADR named in the trigger is the answer if it stops being enough."
        ),
        trigger=(
            "2026-08-24 — the first of: a deployment past ~50 million rows in this "
            "table, a stated retention obligation, or the day the day-bucketed SUM "
            "stops being fast enough at seeded scale (ADR usage-1 already names that "
            "last one as the trigger for materialized rollups, measured by a targeted "
            "harness). Archival, when it comes, is a DATED RESIDUAL — rows move to "
            "cold storage — and never a DELETE nobody remembers, because a deleted "
            "accrual is a bill nobody can defend."
        ),
    )

    #: What was consumed, as `<app>.<noun>.<unit>` — declared vocabulary, not a
    #: literal (`apps/usage/meters.py`). `services.record_usage` refuses a name
    #: no installed app declares, which is why this column carries no `choices`:
    #: the vocabulary is discovered off the installed apps, so a product adding a
    #: meter adds a constant to its own file and never migrates this one.
    meter = models.CharField(max_length=MAX_METER_LENGTH)

    #: How much, in the meter's own unit. **Decimal, never Float** (house rule
    #: 15) — and for counts too, not only money: a token count that arrives as a
    #: float is a number that stops adding up exactly when the totals get large
    #: enough to matter. 19 digits with 4 decimal places is ADR usage-1's, and it
    #: holds both ends of the range this ledger has to carry: fractional units of
    #: a currency-like meter, and billions of tokens.
    quantity = models.DecimalField(max_digits=19, decimal_places=4)

    #: When the consumption HAPPENED, which is not when the row was written.
    #: `created_at` answers the second question already; an activity that retries
    #: for an hour, or a provider that reports yesterday's storage bytes, needs
    #: the first — and a period total that bucketed by write time would move a
    #: customer's usage across a month boundary because a worker was slow.
    #:
    #: A superseding row **inherits the original's** `occurred_at` (the ratified
    #: supersede semantics): a correction does not move when the thing happened.
    occurred_at = models.DateTimeField()

    #: What caused it, as the pair `core.AuditEntry` already uses for the same
    #: job: the source row's model label and its primary key. Two columns rather
    #: than one string because "every entry that came from this completion" is a
    #: question support will ask, and it should be an indexed equality rather
    #: than a `LIKE`.
    ref_type = models.CharField(max_length=128)
    ref_id = models.UUIDField()

    #: The caller's own name for this recording, and the whole of the
    #: idempotency contract: a retried
    #: activity that already wrote a row gets that row back instead of a second
    #: one. Required, not optional — a metering call with no key is a call that
    #: double-bills on the retry Temporal is guaranteed to make.
    idempotency_key = models.CharField(max_length=255)

    #: The row this one corrects, and why. **The pair moves together** — the
    #: constraint below refuses one without the other — because a correction with
    #: no reason is an edit wearing a new row's clothes.
    #:
    #: `PROTECT` is free here (nothing ever deletes a row of this table) and it
    #: is declared anyway, because house rule 15 asks for an explicit `on_delete`
    #: and because the day somebody writes a purge, the database should be the
    #: thing that says "this row is somebody's evidence".
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    superseded_because = models.TextField(blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "usage entry"
        verbose_name_plural = "usage entries"
        constraints = [
            # In the database rather than in a service that remembers. Per
            # TENANT and not per organization (ADR usage-1's word), and that is
            # the right level for this key where it was the wrong one for
            # `Export`: an export key is a person naming their own request, while
            # a metering key is a machine naming a unit of work — the completion
            # it just ran — and the same work must not be billed twice because
            # the retry resolved a different acting hat.
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="usageentry_unique_idempotency_key_per_tenant",
            ),
            # A row is corrected AT MOST ONCE, and this constraint is load-bearing
            # rather than tidy: every aggregate excludes rows a supersede points
            # at by joining the reverse relation, and a reverse relation that
            # could match twice would DOUBLE that row's contribution inside a
            # SUM. Correcting a correction is still legal — the chain grows
            # forward, each link superseding the previous one.
            models.UniqueConstraint(
                fields=["supersedes"],
                condition=models.Q(supersedes__isnull=False),
                name="usageentry_one_correction_per_entry",
            ),
            # The pair, or neither. A `supersedes` with no reason is an edit; a
            # reason with nothing superseded is a comment on a fresh accrual,
            # which is a field this table does not have and should not grow.
            models.CheckConstraint(
                condition=(
                    models.Q(supersedes__isnull=True, superseded_because="")
                    | (models.Q(supersedes__isnull=False) & ~models.Q(superseded_because=""))
                ),
                name="usageentry_correction_states_why",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            # THE PERIOD READ. `get_usage` is `tenant` equality, `meter` equality
            # and an `occurred_at` range, so the columns are in exactly that
            # order: two equalities then the scan. This is the "counter" ADR
            # usage-1 chose instead of a counter row — until measurement says
            # otherwise, and the lifecycle trigger above names that measurement.
            models.Index(fields=["tenant", "meter", "occurred_at"], name="usageentry_period"),
            # RE-ADDED BY HAND, and it must be (house rule 37, ADR core-11).
            # Django does not merge `Meta.indexes` down an inheritance chain, so
            # declaring the index above SHADOWS `TenantScopedModel`'s
            # `(tenant, -created_at)` composite — the one that keeps a paginated
            # default-ordered page from walking other tenants' index entries. The
            # name is what the abstract's `%(class)s_recency` interpolates to, so
            # this is the same index, not a second one.
            models.Index(fields=["tenant", "-created_at"], name="usageentry_recency"),
        ]

    def __str__(self) -> str:
        return f"{self.meter} {self.quantity} @ {self.occurred_at:%Y-%m-%d}"

    @property
    def is_superseded(self) -> bool:
        """Whether a later row corrects this one — and so whether totals skip it.

        A property rather than a column: the answer is the existence of the row
        that points here, and a boolean somebody has to remember to set is a
        boolean that will one day disagree with the FK. It costs a query per
        call, so aggregates use the join (`selectors.py`) rather than this — this
        is for a reader holding one row.
        """
        return self.superseded_by.exists()
