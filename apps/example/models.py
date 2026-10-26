"""The worked example: one model that shows every convention."""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
from typing import ClassVar

from django.conf import settings
from django.db import models

from pilecap import Archivable, Lifecycle, LifecycleKind, OrgScopedModel

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from pilecap import Versioned

# golden: noun end

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from pilecap import Movable

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
from pilecap import Duplicable, Duplicate, duplicate_key_constraint

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from pilecap import Mergeable

# golden: merge import end
# isort: split
# golden: search begin
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField

# golden: search end
# isort: split
# golden: policy begin
from pilecap import InheritedDownward

# golden: policy end

# golden: search begin
#: The text-search configuration; pinned equal to the search app's by a test.
SEARCH_CONFIG = "english"
# golden: search end


# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
class Widget(
    OrgScopedModel,
    Archivable,
    # golden: archive end
    Versioned,
    # golden: noun end
    # golden: version end
    Movable,
    # golden: move bulk history end
    Duplicable,
    # golden: duplicate attach end
    Mergeable,
    # golden: archive version move bulk history duplicate attach begin
    # golden: noun begin
):
    # golden: noun end
    # golden: archive version move bulk history duplicate attach merge import end
    """A thing somebody owns, inside exactly one **part** of one tenant."""

    #: ADR core-13, kind one of three. **The cascade IS the lifecycle.**
    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="widgets",
    )
    notes = models.TextField(blank=True)
    # golden: noun end
    # golden: archive version end
    # The owner axis: `core.verbs.rehome` reassigns this field when a move names it.
    move_owner_field: ClassVar[str | None] = "owner"
    # golden: move end
    # The verbs a selection runs, each through its own single road.
    bulk_verbs: ClassVar[tuple[str, ...]] = ("archive", "restore", "move")
    # golden: bulk history end
    # What a duplicate carries across, and what it starts again (house rule 74).
    duplicate = Duplicate(
        copies=(
            "notes",
            # golden: duplicate attach merge import end
            "policy",
            # golden: duplicate attach merge import begin
        ),
        resets=(
            "name",
            "owner",
            # golden: duplicate attach merge end
            "external_ref",
            # golden: import end
            "onboarded_at",
            "reminded_at",
            "onboarding_confirmed_at",
            "due_at",
            "status",
            # golden: duplicate attach merge import begin
        ),
    )
    # golden: duplicate attach end
    # A merged loser keeps its ledger; every other foreign key into the noun is re-pointed.
    merge_keeps: ClassVar[dict[str, str]] = {
        "entries": "an append-only ledger stays where it was written",
    }
    # golden: attach begin
    # Notes, tags and files attach to a widget; the rows live in their own apps.
    attachments: ClassVar[tuple[str, ...]] = ("notes", "tags", "files")
    # golden: attach merge end
    # The natural key an import finds a widget by; unique per organization when set.
    external_ref = models.CharField(max_length=200, blank=True, default="")
    # golden: import end
    # golden: workflow onboard begin
    onboarded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the onboarding workflow marked this widget ready.",
    )
    # golden: workflow onboard end
    # golden: workflow remind begin
    reminded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the reminder workflow reminded about this widget's due date.",
    )
    # golden: workflow remind end
    # golden: webhook-in onboarding begin
    onboarding_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When a signed onboarding delivery confirmed this widget.",
    )
    # golden: webhook-in onboarding end
    # golden: noun begin
    # golden: field due_at begin
    due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this widget is due, if it carries a due date.",
    )
    # golden: field due_at end
    # golden: noun end
    # golden: enum status begin

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    #: The one move each status may make: a step forward, never back (`transition_widget`).
    STATUS_NEXT: ClassVar[dict[str, str]] = {
        Status.DRAFT: Status.ACTIVE,
        Status.ACTIVE: Status.RETIRED,
    }
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # golden: enum status end
    # golden: policy begin
    # Nullable: a widget without a policy is the ordinary case (ADR core-4).
    policy = models.ForeignKey(
        "WidgetPolicy",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="widgets",
        help_text="The policy this widget was created under, if any.",
    )
    # golden: policy end

    # golden: search begin
    #: THE ADOPTING APP OWNS ITS OWN COLUMN (R-e, ADR search-2).
    search_vector = models.GeneratedField(
        expression=(
            SearchVector("name", weight="A", config=SEARCH_CONFIG)
            + SearchVector("notes", weight="B", config=SEARCH_CONFIG)
        ),
        output_field=SearchVectorField(),
        db_persist=True,
        null=True,
    )
    # golden: search end

    # golden: duplicate attach merge import begin
    # golden: noun begin
    class Meta(OrgScopedModel.Meta):
        # golden: duplicate attach merge import end
        verbose_name = "widget"
        verbose_name_plural = "widgets"
        # golden: duplicate attach merge import begin
        constraints = [
            # golden: duplicate attach merge import end
            models.UniqueConstraint(
                fields=["tenant", "owner", "name"],
                name="widget_unique_name_per_owner_per_tenant",
            ),
            # golden: noun end
            # golden: import begin
            # An import finds a widget by the id it has elsewhere, within one branch.
            models.UniqueConstraint(
                fields=["tenant", "organization", "external_ref"],
                condition=~models.Q(external_ref=""),
                name="widget_unique_external_ref_per_organization",
            ),
            # golden: import end
            # golden: duplicate attach merge import begin
            # A repeated duplicate press with one key answers the first copy:
            duplicate_key_constraint(),
            # golden: noun begin
        ]
        # golden: noun end
        # golden: duplicate attach merge import end
        # golden: search begin
        # DECLARING `indexes` HERE SHADOWS THE ABSTRACT BASE'S (house rule 37).
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="widget_recency"),
            # The full-text index the degradation engine's real-column path reads.
            GinIndex(fields=["search_vector"], name="widget_search_vector_gin"),
            # golden: search end
            # The trigram index over `name`; no query in this tree reads it yet (rule 30).
            GinIndex(
                fields=["name"],
                opclasses=["gin_trgm_ops"],
                name="widget_name_trigram",
            ),
            # golden: search begin
        ]
        # golden: search end

    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
    def __str__(self) -> str:
        return self.name

    # golden: noun end

    # golden: archive version move bulk history duplicate attach merge import end
    # Relation reads on `WidgetOut` are properties, never aliases (ADR example-3).

    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
    @property
    def owner_email(self) -> str:
        """Who owns this, without the caller having to fetch the owner."""
        return str(self.owner.email)

    @property
    def organization_slug(self) -> str:
        """Which part of the tenant owns it — the slug an `X-Org` header names."""
        return str(self.organization.slug)

    # golden: noun end

    # golden: archive version end
    @property
    def owner_name(self) -> str | None:
        """Who owns it, in words — the move sheet's owner axis says it back."""
        return getattr(self.owner, "full_name", None) or None


# golden: move bulk history duplicate attach merge import end
# golden: policy begin
class WidgetPolicy(InheritedDownward, OrgScopedModel, Archivable):
    """Configuration one part of a tenant sets, **inherited by everything below**."""

    #: ADR core-13, kind two of three: config, not traffic, with no cascade parent.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a policy is a tenant's configuration, not its traffic: the population "
            "is bounded by how many rules the business writes and never by time. A "
            "retired policy still has to be readable, because every widget created "
            "under it names it through a PROTECT, and 'what were the terms when "
            "this was made' is a question a dispute turns on."
        ),
        trigger=(
            "2026-08-24 — the first product whose policies genuinely churn (a "
            "pricing rule rewritten weekly per branch), which is the product that "
            "needs `superseded_at` on this row and a rule about what a superseded "
            "policy's widgets are still allowed to resolve."
        ),
    )

    name = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "widget policy"
        verbose_name_plural = "widget policies"
        constraints = [
            # Per **organization**, not per tenant: `governing()` resolves nearest first.
            models.UniqueConstraint(
                fields=["tenant", "organization", "name"],
                name="widget_policy_unique_name_per_organization",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def organization_slug(self) -> str:
        """Which node set it — a property, not a schema alias (ADR example-3)."""
        return str(self.organization.slug)


# golden: policy end
# golden: move bulk history duplicate attach merge import begin
# golden: child entry begin
class WidgetEntry(OrgScopedModel):
    """A widget's ledger line. **Append-only; it lands where the widget is.**"""

    #: House rule 20, declared rather than named: see `core.models.is_append_only`.
    append_only = True

    #: The landing gate: this row's organization is the widget's, or it is refused.
    derive_org_from = "widget"

    #: ADR core-13, kind three of three: append-only like `core.AuditEntry` (rules 20 and 31).
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.APPEND_ONLY,
        reason=(
            "the widget's ledger, and a ledger with a retention window is a ledger "
            "whose oldest lines cannot be cited. 'When was this approved, and by "
            "whom' has to stay answerable for as long as anybody can ask — and the "
            "line outlives every attempt to remove its subject, because `widget` "
            "is PROTECT rather than CASCADE."
        ),
        trigger=(
            "2026-08-24 — archival, when it comes, is a DATED RESIDUAL and never a "
            "DELETE nobody remembers (`core.audit`'s grammar). The first "
            "of: a product whose entry table outgrows its widget table by orders "
            "of magnitude, or a stated retention obligation. Either one turns this "
            "into a `purged` declaration whose callable moves lines to cold "
            "storage, and that declaration lands in the SAME COMMIT as its "
            "`ScheduleDeclaration` — a purge with no schedule is the defect, not "
            "the fix."
        ),
    )

    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        APPROVED = "approved", "Approved"

    widget = models.ForeignKey(
        Widget,
        on_delete=models.PROTECT,
        related_name="entries",
        help_text="The widget this line is about. Its organization is this row's.",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.NOTE)
    note = models.TextField(blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "widget entry"
        verbose_name_plural = "widget entries"

    def __str__(self) -> str:
        return f"{self.kind} on {self.widget_id}"

    @property
    def organization_slug(self) -> str:
        return str(self.organization.slug)


# golden: child entry end
# golden: move bulk history duplicate attach merge import end
