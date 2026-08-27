"""Visibility over durable work.

Temporal is the source of truth for what a workflow is doing; this table is the
product's own answer to "did we start one, for whom, and how did it end".

**It is the platform-wide run ledger, and that is one population plus a
declared second one** (ADR workflows-3). Nearly every run belongs to a tenant
and is read through the same `for_tenant` door as its rows and no other. A few
belong to the *deployment* — revoking the identity of a person who belongs to
no tenant, syncing workforce identity — and until this model could hold them,
that work either skipped its ledger entirely (`accounts.identity.not_revoked`,
an erasure hole) or borrowed somebody's tenant to get a row.

So `tenant` is nullable, and **null is a declared population rather than a
loosening**:

* a platform run's workflow id carries `PLATFORM_SEGMENT` (`"platform"`) as its
  first segment, and `check_workflow_id` requires that segment **iff** the
  tenant is None — so neither population can wear the other's id;
* `for_tenant(...)` is untouched and still fails closed, which means it can
  never see a platform row: every tenant door — REST, MCP, the admin changelist
  through `ServiceModelAdmin.get_queryset` — excludes them **by construction**,
  not by remembering to;
* `for_platform()` is the one read path for the null population, and it is
  spelled differently from `for_tenant` on purpose: a reader of a query can see
  which population it is over.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import ScopedManager, ScopedQuerySet, Tenant, TenantScopedModel


class WorkflowRunQuerySet(ScopedQuerySet["WorkflowRun"]):
    """`ScopedQuerySet` plus the one read path onto the platform population."""

    def for_platform(self) -> WorkflowRunQuerySet:
        """The runs no tenant owns. **The declared null population, ADR workflows-3.**

        The mirror of `for_tenant`, and deliberately not a widening of it:
        `for_tenant(None)` still returns nothing, so a door that failed to
        resolve a tenant reads an empty table rather than the deployment's own
        work. Asking for the platform's runs is a different question and it is
        asked with a different word.
        """
        return self.filter(tenant__isnull=True)


class WorkflowRunManager(ScopedManager["WorkflowRun"]):
    """The only supported way to read a run: by tenant, or by platform."""

    def get_queryset(self) -> WorkflowRunQuerySet:
        return WorkflowRunQuerySet(self.model, using=self._db)

    def for_platform(self) -> WorkflowRunQuerySet:
        return self.get_queryset().for_platform()


class WorkflowRun(TenantScopedModel):
    """One started workflow, from this product's point of view."""

    #: ADR core-13, rule 31. The run ledger is a **log with a retention
    #: window**, and until this line it was the largest table in the tree with
    #: nothing at all said about how its rows end: every widget onboarded,
    #: every email sent and every organization moved has written one since the
    #: day the template was cloned, and nothing has ever removed one.
    #:
    #: **The population is narrower than "finished", and the narrowing is the
    #: honest part of this declaration.** `purge_finished_runs` deletes rows
    #: that are `completed` or `cancelled` and whose `finished_at` is past the
    #: window. It does not touch:
    #:
    #: * **`running` rows** — those are the reconciler's population and it is
    #:   sacred (`activities.reconcile_runs`). A row that says `running` is
    #:   either live work or a promise nobody kept, and a purge that ate one
    #:   while the sweep was about to close it would be rule 28's exact fear:
    #:   the ledger lying by omission, with the omission indistinguishable
    #:   from a run that never happened.
    #: * **`failed` rows** — the same reasoning `apps.events.services.
    #:   purge_dispatched_outbox` states one app over: a failure is the record
    #:   of something that did not work, and deleting it is deleting the
    #:   finding. A `failed` row is what somebody reads six weeks later to
    #:   answer "has this been breaking the whole time"; a retention window
    #:   that swept it away would answer "no" by having forgotten.
    #:
    #: **Rule 31 cannot see any of that** — its own `does_not_cover` says so in
    #: the first sentence: the chain proves a callable is REACHED, never that
    #: the rows it deletes are the rows that should go. So the filter's honesty
    #: is stated here, where the declaration is, and pinned by
    #: `tests/test_purges.py`, which seeds all four statuses and asserts
    #: exactly which two survive.
    #:
    #: `purged_by` names the CALLABLE, never the schedule: rule 31 walks
    #: outwards from this string — callable, to the activity that references
    #: it, to the `ScheduleDeclaration` whose workflow reaches that activity —
    #: and naming the schedule would assert the end of the chain instead of
    #: letting the check prove it.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.workflows.services.purge_finished_runs",
        reason=(
            "the run ledger is a log, and a log with no window is a table that "
            "grows for as long as the product runs. A closed run answers 'what "
            "did we do for this person' and stops being asked long before it "
            "stops costing an index."
        ),
    )

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        #: **A deliberate stop is not a failure** (ADR workflows-7). Until this
        #: value existed, a run somebody asked to stop closed as `failed` and
        #: read, months later, exactly like a run that broke — so "did this
        #: break or did we stop it" was unanswerable from the ledger, and the
        #: reconciler lumped Temporal's own `CANCELED` into `FAILED` for the
        #: same reason: there was nowhere else to put it.
        #:
        #: The word is spelled the way the rest of this tree spells English —
        #: two `l`s — while Temporal's enum member is `CANCELED`; the mapping
        #: between them lives in `activities.reconcile_runs` and in
        #: `workflows._finish`, and nowhere else.
        CANCELLED = "cancelled", "Cancelled"

    #: Overridden from `TenantScopedModel` to be nullable. See the module
    #: docstring: null is the platform population, fenced by the id segment,
    #: and `for_tenant` never sees it.
    tenant = models.ForeignKey(  # type: ignore[assignment]  # widened: see above
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_set",
    )

    workflow_id = models.CharField(max_length=255)
    run_id = models.CharField(max_length=255, blank=True)
    type = models.CharField(max_length=255)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    #: sha256 hex over the run's `arg`, serialised through Temporal's own
    #: default payload converter, computed by the starters and never by a
    #: caller (ADR workflows-4). It is what tells a *retry* — the same work
    #: under the same deterministic id — from a *second job* wearing that id.
    #: Empty means unknown: rows written before this column existed hold `""`
    #: and never conflict, because a backfill nobody can compute would be a
    #: guess rather than a fact.
    input_digest = models.CharField(max_length=64, blank=True, default="")

    #: **Who asked for this run** (ADR workflows-6). Written by `record_run`
    #: off the user `start_workflow_on_commit` already threads onto the
    #: workflow's headers — never handed in by a door, which is what makes
    #: "the actor's own runs" a fact about the start rather than a claim about
    #: the request that is reading.
    #:
    #: `SET_NULL`, because **the ledger outlives its people**: a person erased
    #: under `erase_user` must not take the record of what ran with them, and a
    #: `PROTECT` here would make erasure impossible for anybody who had ever
    #: started a workflow.
    #:
    #: **Null is unknown, not "nobody"** — the `input_digest` precedent
    #: verbatim. Rows written before this column existed hold `NULL` and are
    #: nobody's own runs; they are readable through the tenant door and are
    #: never replayable, because a backfill nobody can compute would be a guess
    #: wearing the authority of a fact. A platform run legitimately has no
    #: starter and holds `NULL` for the same reason.
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_started",
    )

    # The house name for the one supported read path, narrowed to the manager
    # that also knows `for_platform`. django-stubs declares `objects` a
    # ClassVar on the base, which is what the ignore is about — not the
    # narrowing, which is exactly what Django's manager inheritance is for.
    objects = WorkflowRunManager()  # type: ignore[misc]

    class Meta(TenantScopedModel.Meta):
        verbose_name = "workflow run"
        verbose_name_plural = "workflow runs"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "workflow_id"],
                name="workflowrun_unique_workflow_id_per_tenant",
            ),
            # Postgres treats NULLs as distinct, so the constraint above does
            # not bind the platform population at all — two platform rows could
            # share an id and the reopen race would have no arbiter. This is
            # that arbiter, over exactly the rows the first one cannot see.
            models.UniqueConstraint(
                fields=["workflow_id"],
                condition=models.Q(tenant__isnull=True),
                name="workflowrun_unique_platform_workflow_id",
            ),
        ]
        indexes = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            # NOTE, booked as an observation: this door's DEFAULT `?ordering=` is
            # `-started_at`, which has no index of its own. Rule 37 censuses
            # the model's default ordering, not a route's allow-listed
            # columns, and says so in its `does_not_cover`. That gap belongs to
            # rule 35's registry or a measurement rung, not to this index.
            models.Index(fields=["tenant", "-created_at"], name="workflowrun_recency"),
            models.Index(fields=["tenant", "status"], name="workflowrun_tenant_status"),
        ]

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None

    @property
    def started_by_email(self) -> str:
        """Who started it, as a door reports it. `""` when nobody is recorded.

        A property rather than a schema alias, for the reason `comms.MessageOut`
        states in full: the MCP transport serialises a tool result **by alias**,
        so an aliased field answers with a different key at the machine door
        than at the human one. One name, both doors.

        It reads `started_by`, so every selector that feeds a list door
        `select_related`s it — a property is not an excuse for an N+1, it is a
        place to hide one.
        """
        starter = self.started_by
        return str(starter.email) if starter is not None else ""

    def __str__(self) -> str:
        return f"{self.type} {self.workflow_id}"
