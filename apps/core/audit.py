"""The audit trail. On by default, written by `@service`, append-only.

Every write in the product leaves a row here, and it is not the developer's job
to remember: `core.service.service` writes it. What a row answers is fixed
(`architecture.md`, "Traceability"):

* **who** — `actor_user`, `actor_token`, `actor_kind` (human | agent | system);
* **as what** — `acting_org`: which node of the tenant's tree the actor was
  wearing as a hat, because in a networked tenant "who" alone is ambiguous;
* **what** — `action`, the service's name, plus the object it returned;
* **from where** — `door`: rest, mcp, socket, workflow, webhook, admin, shell;
* **how it went** — `outcome` and, when it failed, the domain `error_code`;
* **with what** — `input`, redacted to the app's `LOG_KEYS` allow-list;
* **as part of what** — `request_id`, `session_id`, `correlation_id`,
  `causation_id`, `trace_id`.

**Append-only, and enforced rather than promised.** `save()` refuses a second
write to the same row and `delete()` refuses at all; the admin is read-only.
An audit trail that any code path can rewrite is a log with better marketing —
the whole value is that a row, once written, is what happened.

**It is the product-wide trail, and that is one population plus a declared
second one** (ADR core-8, mirroring ADR workflows-3 shape for shape). Nearly
every row belongs to a tenant and is read through the same `for_tenant` door as
the rows it describes. A few belong to the *deployment* — erasing a person who
belongs to no tenant, syncing workforce identity, revoking a Zitadel credential
that is nobody's workspace's — and until this model could hold them, `@service`
simply skipped the row: the one compliance-shaped trail had a hole exactly where
the compliance actions were.

So `tenant` is nullable, and **null is a declared population rather than a
loosening**:

* `for_tenant(...)` is untouched and still fails closed, which means it can
  never see a platform row: every tenant door — REST, MCP, the admin changelist
  through `ServiceModelAdmin.get_queryset` — excludes them **by construction**,
  not by remembering to. `for_tenant(None)` is still empty, because "unresolved"
  and "the deployment's own" are different facts;
* `for_platform()` is the one read path for the null population, and it is
  spelled differently from `for_tenant` on purpose: a reader of a query can see
  which population it is over;
* the `@service` decorator is the population's **one writer** — a service that
  declares a `tenant` parameter writes its row whether that parameter resolved
  to a tenant or to None (`apps/core/service.py`, and the enumeration of the
  population lives beside the branch);
* **rule 20 is unchanged over the widened population.** `save()` and `delete()`
  below do not read `tenant`, so a null-tenant row is exactly as unrewritable as
  any other. Widening which rows exist never widened what may be done to one.

Retention is a residual, not a silent policy: archival is dated in the
product's queue rather than implemented as a `DELETE` nobody remembers.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from apps.core.lifecycle import AppendOnlyViolation, Lifecycle, LifecycleKind
from apps.core.models import ScopedManager, ScopedQuerySet, Tenant, TenantScopedModel


class AuditImmutable(AppendOnlyViolation):
    """Raised by any attempt to change or remove a written audit row.

    A subclass of `AppendOnlyViolation` since ADR core-14 gave `BaseModel` the
    runtime belt: this trail's refusal is the first and most specific member of
    that family rather than a lookalike beside it, so `except
    AppendOnlyViolation` catches every append-only tamper in the product and
    the sentence this class has always said is unchanged. `AppendOnlyViolation`
    is itself a `RuntimeError`, so nothing that caught one before catches less
    now.

    The model keeps its own `save()`/`delete()` below rather than leaning on
    the belt: they predate it, they are the more specific message, and a table
    whose whole value is that nothing rewrites it is the last place to remove a
    guard because a more general one arrived.
    """


class AuditEntryQuerySet(ScopedQuerySet["AuditEntry"]):
    """`ScopedQuerySet` plus the one read path onto the platform population."""

    def for_platform(self) -> AuditEntryQuerySet:
        """The rows no tenant owns. **The declared null population, ADR core-8.**

        The mirror of `for_tenant`, and deliberately not a widening of it:
        `for_tenant(None)` still returns nothing, so a door that failed to
        resolve a tenant reads an empty table rather than the deployment's own
        actions. Asking for the platform's trail is a different question and it
        is asked with a different word — the same shape, the same spelling and
        the same reasoning as `WorkflowRun.objects.for_platform()`.
        """
        return self.filter(tenant__isnull=True)


class AuditEntryManager(ScopedManager["AuditEntry"]):
    """The only supported way to read the trail: by tenant, or by platform."""

    def get_queryset(self) -> AuditEntryQuerySet:
        return AuditEntryQuerySet(self.model, using=self._db)

    def for_platform(self) -> AuditEntryQuerySet:
        return self.get_queryset().for_platform()


class AuditEntry(TenantScopedModel):
    """One thing that happened, and everything needed to place it.

    **The first member of the append-only population**, and no longer the
    definition of it. House rule 20 used to name this class; it reads the
    declaration below instead, so a product's witnessed facts, accruals and
    stage-transition logs are covered by declaring one attribute rather than by
    editing `rules.yaml` (ADR core-6). `save()` and `delete()` below are this
    model's own enforcement; the declaration is what makes the rule find it.

    **What a conforming row is: ADR core-22** — NIST SP 800-53 AU-3's content
    elements read onto the columns below, column by column, with the actor
    semantics per door and the five legitimate absences enumerated so that a
    reviewer meeting a gap can tell the contract from a defect. No column was
    added for it: a contract that can be met by reading discipline must not be
    met by schema.

    **The pre-contract population is declared, dated, and NOT backfilled**
    (core-22's absence v). Every row written before **2026-08-26** predates the
    contract — including the revocation rows that carry no actor, and every
    credential death that predates it, which was never recorded at all. The
    ground for leaving them is structural rather than preferential, and it is
    the attribute directly above: **a backfill is an UPDATE on a ledger,
    forbidden by the very rule that makes this table evidence.** `save()` below
    refuses the second write, so the only way to "complete" the trail would be
    to disable the guard that makes it worth completing. A trail whose gaps are
    dated and declared is evidence; a trail somebody helpfully finished is not.
    """

    #: `core.models.is_append_only` reads this; nothing anywhere may update or
    #: delete a row of a model that declares it. It is a property of the model,
    #: not of a row's tenant, so the platform population below is covered by it
    #: exactly as every tenant's rows are.
    append_only: ClassVar[bool] = True

    #: ADR core-13. The append-only declaration above says rows are never
    #: rewritten; this says what happens to them over TIME, which is a
    #: different question with a different answer — nothing, on purpose, until
    #: a dated trigger fires. The two are deliberately separate attributes:
    #: rule 20 reads the first and rule 31 the second, and a table can be one
    #: without being the other.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.APPEND_ONLY,
        reason=(
            "the compliance trail. 'Who approved this refund' has to be answerable "
            "for as long as anybody can ask, and a trail with a retention window is "
            "a trail whose oldest disputes are unanswerable. Growth is real and is "
            "accepted: the two indexes in `Meta` are what keep a big table's reads "
            "cheap (`quality/perf-ledgers-measurement.md`, FINDINGs A and B)."
        ),
        trigger=(
            "2026-08-24 — archival, when it comes, is a DATED RESIDUAL and never a "
            "DELETE nobody remembers (this module's own docstring, and the same "
            "grammar for `comms.Message`). The first of: a deployment past ~10 "
            "million rows in this table, a stated retention obligation, or a "
            "compliance ask — whichever arrives first turns this into a `purged` "
            "declaration whose callable moves rows to cold storage rather than "
            "dropping them."
        ),
    )

    #: Overridden from `TenantScopedModel` to be nullable. See the module
    #: docstring: null is the platform population (ADR core-8), the `@service`
    #: decorator is its one writer, and `for_tenant` never sees it.
    tenant = models.ForeignKey(  # type: ignore[assignment]  # widened: see above
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_set",
    )

    #: Overridden from `BaseModel` to drop the **single-column** `created_at`
    #: index, and that is a performance fix with a measurement behind it
    #: (`quality/perf-ledgers-measurement.md`, FINDINGs A and B; cycle P3, rung
    #: F1b).
    #:
    #: `BaseModel` indexes `created_at` for every model in the product, which is
    #: the right default for a table read newest-first across the whole of it.
    #: This table is never read that way. `AuditEntryManager` offers exactly two
    #: read paths — `for_tenant(...)` and `for_platform()` — and both lead with
    #: the tenant column, so between them the two indexes in `Meta` below serve
    #: every supported question: the composite for a tenant's page, the partial
    #: one for the platform population's.
    #:
    #: What the redundant single-column index bought was a wrong plan. At 500k
    #: rows the planner estimated a loaded tenant at ~49% of the table, decided
    #: a backward walk of `core_auditentry_created_at` would fill a 50-row page
    #: at once, and discarded **255,000 other tenants' rows** to return 50 —
    #: doubling to 510,000 when the ledger doubled, with the query count sitting
    #: at 1 the whole time. The platform read paid the mirror of it: newest-first
    #: looked free only because the seed writes that slice last, and oldest-first
    #: through the same index discarded 490,000. The choice flipped on an
    #: estimate, so no reader could rely on it: a tenant that had been quiet
    #: while its neighbours were busy paid for their write volume to read page
    #: one of its own trail. With the alternative gone the composite is the only
    #: ordered path and every supported read is tenant-leading by construction
    #: rather than by the planner's luck.
    #:
    #: The write side gets the same fix for free: an append-only ledger was
    #: paying to maintain two indexes where one was ever read.
    created_at = models.DateTimeField(auto_now_add=True, db_index=False)

    class Outcome(models.TextChoices):
        OK = "ok", "OK"
        ERROR = "error", "Error"

    class Kind(models.TextChoices):
        HUMAN = "human", "Human"
        AGENT = "agent", "Agent"
        SYSTEM = "system", "System"

    # --- Who ---------------------------------------------------------------
    # Both nullable and both SET_NULL: a user erased under a data-protection
    # request must not take the trail of what they did with them, and a revoked
    # token that is eventually purged must not either. The row survives; the
    # pointer does not.
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    actor_token = models.ForeignKey(
        "accounts.ApiToken",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    actor_kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SYSTEM)
    # **Which hat.** In a networked tenant "who" is not enough: the same person
    # holds memberships at two levels, and "did they do this as the group or as
    # the branch" is the question a dispute turns on. It is the acting
    # organization the door resolved (`X-Org`, the MCP principal, the workflow
    # headers), not the row's own — those are different facts and the row's own
    # is already reachable through `object_id`.
    #
    # Nullable and `SET_NULL`, like the other two pointers: an organization that
    # is eventually removed must not take the trail of what was done under it,
    # and a tenant-scoped write has no acting org at all.
    acting_org = models.ForeignKey(
        "core.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )

    # --- What --------------------------------------------------------------
    action = models.CharField(max_length=255, db_index=True)
    object_type = models.CharField(max_length=255, blank=True)
    object_id = models.UUIDField(null=True, blank=True)

    # --- From where, and how it went ---------------------------------------
    door = models.CharField(max_length=16, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.OK)
    error_code = models.CharField(max_length=64, blank=True)
    input = models.JSONField(default=dict, blank=True)

    # --- As part of what ---------------------------------------------------
    request_id = models.CharField(max_length=64, blank=True)
    session_id = models.CharField(max_length=64, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    causation_id = models.CharField(max_length=64, blank=True)
    trace_id = models.CharField(max_length=64, blank=True)

    # The house name for the one supported read path, narrowed to the manager
    # that also knows `for_platform`. django-stubs declares `objects` a
    # ClassVar on the base, which is what the ignore is about — not the
    # narrowing, which is exactly what Django's manager inheritance is for.
    objects = AuditEntryManager()  # type: ignore[misc]

    class Meta(TenantScopedModel.Meta):
        verbose_name = "audit entry"
        verbose_name_plural = "audit entries"
        indexes: ClassVar[Any] = [
            # The one query this table exists to serve: "what happened in this
            # tenant, most recent first". With `created_at`'s single-column
            # index gone (see the field above) this is the only ordered path
            # into the table, so the read is tenant-leading by construction
            # rather than by whichever way the planner's estimate fell.
            models.Index(fields=["tenant", "-created_at"], name="auditentry_tenant_created"),
            # The **platform** population's own index (ADR core-8, and FINDING
            # B of `quality/perf-ledgers-measurement.md`), partial because the
            # population is: it indexes the deployment's own rows and no
            # tenant's, so a table that is 98% tenant rows pays for 2% of an
            # index.
            #
            # It is here because dropping the competing `created_at` index was
            # not by itself enough for this read, and the difference is worth
            # stating. Without it the planner answers `tenant_id IS NULL` off
            # the tenant FK index and then top-N sorts the **whole** platform
            # slice — correct, and free of the 490,000 discarded rows FINDING B
            # measured, but O(platform population) for a 50-row page in both
            # directions. `IS NULL` reads as an index condition on the
            # composite's leading column and yet does not carry that column's
            # ordering the way an equality does, so the composite cannot serve
            # this page ordered. The partial index can, and does: one `Index
            # Scan` forward for newest-first and `Backward` for oldest-first,
            # no sort node in either.
            #
            # Oldest-first is named on purpose. It is the direction a retention
            # sweep and a "what did this deployment do first" audit both ask in,
            # and it is the direction FINDING B caught: newest-first looked free
            # only because the fixture writes the platform slice last.
            models.Index(
                fields=["-created_at"],
                name="auditentry_platform_created",
                condition=models.Q(tenant__isnull=True),
            ),
            # The HISTORY card's read (`core.selectors.list_history`): "what
            # happened to THIS row, newest first", one tenant at a time. Tenant-
            # leading like every read here; `object_id` next, so a row's history
            # is one contiguous range; ordered, so a page is an index walk with
            # no sort. Partial because the population is: a sweep's row, a
            # refused call's row and a platform row carry no `object_id`, and
            # the history never reads them. Built CONCURRENTLY (migration 0019,
            # non-atomic): the trail is the product's largest table.
            models.Index(
                fields=["tenant", "object_id", "-created_at"],
                name="auditentry_object_history",
                condition=models.Q(object_id__isnull=False),
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Write once. A second save on the same row is refused, loudly.

        `_state.adding` is the honest test: a row loaded from the database and
        saved again has it False, whatever the caller intended. Checking `pk`
        alone would not work here — `BaseModel` assigns the UUID in Python, so
        an unsaved row already has one.
        """
        if not self._state.adding:
            raise AuditImmutable(
                "An audit entry is append-only; it cannot be changed once written."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AuditImmutable("An audit entry cannot be deleted. Archival is a dated residual.")

    def __str__(self) -> str:
        return f"{self.action} ({self.outcome}) via {self.door or 'unknown'}"
