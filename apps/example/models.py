"""The worked example: one model that shows every convention.

Delete this app when the product has its own. Until then it is the reference —
an **org-scoped** model here, writes in `services.py`, Pydantic schemas in
`schemas.py`, a ninja router in `api.py` that declares its auth and paginates
its list, migrations with a `max_migration.txt` leaf, and tests that prove all
of it including the query count, that a second tenant's rows are absent, and
that a sibling branch of the *same* tenant's rows are absent too.

**Rule 31 is worked here too — and the fourth kind is worked by its absence.**
Each of the three models below declares how its data dies (ADR core-13), and
between them they show three of the four kinds: `bounded` on `Widget` (the
cascade IS the lifecycle), `unbounded` on `WidgetPolicy` (a decision, so a
reason and a dated trigger), `append_only` on `WidgetEntry` (declared beside its
`append_only = True`, because the two are different questions). Each carries the
comment saying WHY that kind is the right one, which is the part a fifteenth
builder is actually copying.

The fourth kind, `purged`, is deliberately **not** declared anywhere in this
app, and that is the teaching rather than a gap. None of these three rows
expires: a widget is deleted by an act (`delete_widget`), a policy is config,
and a ledger line is evidence. A `purged` declaration here would name a sweeper
nobody wrote — the poller-that-was-never-built, which is the exact defect ADR
core-13 exists to catch, and which the primitive refuses at import if you leave
`purged_by` off. **Do not add a kind to complete a set: a declaration that lies
is worse than a table that never spoke.** The worked `purged` in this tree is
`core.IdempotencyRecord` (`apps/core/idempotency.py`), which cites the existing
callable `apps.core.idempotency.purge_expired` and has the whole chain behind
it — the callable, the activity that references it, the workflow that executes
that activity, and a `ScheduleDeclaration` in some app's `SCHEDULES`. Copy that
declaration when your row genuinely expires, and land it in the **same commit**
as its schedule: rule 31 checks the callable is REACHED, not merely named.
"""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import Archivable, OrgScopedModel

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from apps.core.models import Versioned

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.core.models import Movable

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
from apps.core.models import Duplicable, Duplicate, duplicate_key_constraint

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.core.models import Mergeable

# golden: merge import end
# isort: split
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField

from apps.core.models import InheritedDownward

#: The Postgres text-search configuration the generated column below is built
#: under. It is spelled here rather than imported from
#: `apps.search.selectors.TEXT_SEARCH_CONFIG` for two reasons and neither is
#: laziness: a `GeneratedField` holding a tsvector must name an **immutable**
#: configuration inside its own expression, so the value has to be a literal
#: this module owns at migration time; and importing the search app's read
#: module here would drag `engine.py` — and the Meilisearch client with it —
#: into every `import apps.example.models`, at app-load time, in a checkout
#: that may not even have the engine running.
#:
#: **The two must agree**, because a vector built under `english` and a query
#: parsed under `simple` disagree about stemming and stop words and the failure
#: is a search that quietly finds less rather than an error anybody sees. That
#: agreement is not left to whoever reads this comment:
#: `apps/example/tests/test_search_adoption.py` pins the two constants equal,
#: so a product that indexes another language is told where the other half is.
SEARCH_CONFIG = "english"


# golden: archive version move bulk history duplicate attach merge import begin
class Widget(
    OrgScopedModel,
    Archivable,
    # golden: archive end
    Versioned,
    # golden: version end
    Movable,
    # golden: move bulk history end
    Duplicable,
    # golden: duplicate attach end
    Mergeable,
    # golden: archive version move bulk history duplicate attach begin
):
    # golden: archive version move bulk history duplicate attach merge import end
    """A thing somebody owns, inside exactly one **part** of one tenant.

    Org-scoped rather than merely tenant-scoped, and that is the reference
    point: this is what a row a seller, a branch or a practice owns looks like.
    `OrgScopedModel` adds the `organization` foreign key on top of `tenant`, and
    the read that goes with it is
    `Widget.objects.for_tenant(t).visible_to(actor_or_org)` — house rule 24,
    refused by the gate if the second half is missing.

    It declares no manager of its own: `TenantScopedModel` supplies
    `ScopedManager`, and both halves of the read live on it.

    A product whose rows every member of the tenant may see inherits
    `TenantScopedModel` instead. That choice is the architect's
    (`django-architect`, § A), and it is cheaper to get wrong in this direction
    than the other: an org-scoped row everybody may see costs a
    `visible_to(root)`, and a tenant-scoped row that should have been
    org-scoped is a leak between the tenant's own customers.

    **It leaves the book by being archived, never by a flag.** `Archivable`
    brings `archived_at` and `archived_by`, and `for_tenant()` then leaves an
    archived widget out of every read that does not widen on purpose —
    `including_archived()` for the detail and the restore, `archived_only()`
    for the list's `?show=archived`.

    **And it carries the rest of the family, one declaration each.**
    `Versioned` makes every edit name the version it was made against (a late
    save is `stale_version`, never a silent overwrite); `Movable` lets an
    administrator re-home it at another node — and hand it to another owner —
    with its ledger refusing to follow (`move_blocked`); `bulk_verbs` runs
    archive, restore and move over a selection; and any of those brings the
    history card, read off the audit trail. None of the three adds a column.
    `Duplicable` makes a new widget from this one (the `duplicate` declaration
    says what carries across); `attachments` takes notes, tags and files, which
    live in their own apps; `Mergeable` folds a duplicate into the widget it
    duplicates — its attachments re-pointed, its ledger kept where it was
    written (`merge_keeps`); and `external_ref` is the natural key a file of widgets is imported by
    (`importers.py`). Those three verbs add columns, and the migration that adds
    them is expand-only.

    **The fences, and why they list verbs.** The lines fenced `golden: <verbs>`
    in this app are the adoption a product copies onto its own noun; the
    unfenced lines around them are this widget's own business. The verbs are
    adopted in ONE ORDER — archive, version, move, bulk, history, duplicate,
    attach, merge, import — and each verb's copy is the noun as it stands after
    that adoption, so a block belongs to its own verb and to every verb after
    it, and its fence names them all in one line (`# golden: move bulk history
    duplicate attach merge import begin`). Attach comes before merge because a
    merge re-points the attachments: the owners' repointers answer only for a
    noun that takes them. History is owed by every verb but
    archive, so its blocks carry version's too.
    """

    #: ADR core-13, kind one of three. **The cascade IS the lifecycle.**
    #: `core.Membership` is the pattern and this is the same shape: a widget
    #: dies two ways and both of them are somebody's act — `delete_widget`
    #: removes it, deleting its `owner` CASCADEs it. There is no sweeper and
    #: none is wanted, because a widget nobody deleted is a widget somebody
    #: still has.
    #:
    #: HOW TO CHOOSE IT, since this is the kind you will reach for most: ask
    #: whether the row can **outlive the thing it hangs off**. Here it cannot.
    #: `owner` is `on_delete=CASCADE`, so the owner going takes the widget with
    #: it; and where a `WidgetEntry` PROTECTs the widget, the delete refuses and
    #: NEITHER row goes. Both branches keep the invariant `bounded` actually
    #: asserts, which is why the PROTECT below does not make this declaration
    #: false.
    #:
    #: NOTE WHAT IS NOT THE PARENT. `tenant` and `organization` are `PROTECT` on
    #: every scoped model in this tree (`core.TenantScopedModel`,
    #: `core.OrgScopedModel`), so "it dies with its tenant" is a sentence that
    #: reads well and is not true here. Read the `on_delete` you are about to
    #: claim off the field; do not assume it from the shape of the app.
    #:
    #: `bounded` carries no `reason` and no `trigger`, on purpose: a cascade is
    #: a mechanism the schema already states, not a decision to defend. The two
    #: reasoned kinds below are the ones that owe a sentence.
    # golden: archive version move bulk history duplicate attach merge import begin
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="widgets",
    )
    notes = models.TextField(blank=True)
    # golden: archive version end
    # The owner axis: a move may hand the widget to another person as well as
    # re-home it (`core.verbs.rehome` reassigns this field when it is named).
    move_owner_field: ClassVar[str | None] = "owner"
    # golden: move end
    # The verbs a selection runs, each through its own single road.
    bulk_verbs: ClassVar[tuple[str, ...]] = ("archive", "restore", "move")
    # golden: bulk history end
    # What a duplicate carries across, and what it starts again: every concrete
    # editable field is on one side (house rule 74's duplicate clause). The copy
    # belongs to the person who pressed and is named `Copy of <name>` — both are
    # the service's `fill`, set before the copy's one save.
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
            # golden: duplicate attach merge import begin
        ),
    )
    # golden: duplicate attach end
    # A merged loser keeps its ledger: every other foreign key into the noun is
    # re-pointed by the app that owns it (house rule 74's FK census).
    merge_keeps: ClassVar[dict[str, str]] = {
        "entries": "an append-only ledger stays where it was written",
    }
    # golden: attach begin
    # Notes, tags and files attach to a widget; the rows live in their own apps.
    attachments: ClassVar[tuple[str, ...]] = ("notes", "tags", "files")
    # golden: attach merge end
    # The natural key an import finds a widget by: the id the row has in the
    # system it came from. Blank for a widget made here; unique per organization
    # when set (the partial constraint in `Meta`, which the import copy takes).
    external_ref = models.CharField(max_length=200, blank=True, default="")
    # golden: import end
    onboarded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the onboarding workflow marked this widget ready.",
    )
    # Nullable because a widget without a policy is the ordinary case — most
    # trees have no policy at all, and a required FK here would make the
    # hierarchy's most optional feature its most compulsory one. `PROTECT`
    # because a policy several branches are governed by is not a row anybody
    # gets to delete out from under them: the refusal is the point.
    #
    # **A branch may name a policy it can never list.** That is `may_be_named`'s
    # link gate (ADR core-4) and it is checked at the door, not here — reachable
    # or ancestor-owned passes, sibling-owned is `not_found`, because not-there
    # and not-yours are one answer.
    policy = models.ForeignKey(
        "WidgetPolicy",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="widgets",
        help_text="The policy this widget was created under, if any.",
    )

    #: THE ADOPTING APP OWNS ITS OWN COLUMN (R-e, ADR search-2).
    #:
    #: `apps/search` never adds a column to anybody's table: it declares what a
    #: kind is and it reads. The degradation engine
    #: (`apps.search.selectors.PostgresEngine`) looks for a field spelled
    #: exactly `search_vector` — `selectors.VECTOR_FIELD` — and when it is there
    #: the GIN index below does the work; when it is not, the identical vector
    #: is computed inline with a sequential scan under it. **Correct either way,
    #: fast only the first way**, which is why an adopting app lands this
    #: column and why the migration that adds it is expand-only.
    #:
    #: `GeneratedField` and not a trigger, a signal or a service line: the
    #: column is Postgres's own STORED expression over this row, so it cannot be
    #: stale, cannot be forgotten by a write path nobody updated, and needs no
    #: backfill — which is exactly the property you want in the thing you are
    #: standing on when the synced engine is down. It is also why there is no
    #: `search_vector` anywhere in `services.py`: nothing writes it, ever.
    #:
    #: **The weights come from the declaration and may not drift from it.**
    #: `apps/example/search.py` declares `[("name", "A"), ("notes", "B")]`, the
    #: same list that ranks the Meilisearch document, and `setweight`'s labels
    #: are Postgres's four — which is why the registry closed that vocabulary to
    #: A–D. The test module pins this expression against the declaration rather
    #: than trusting the two to be edited together.
    #: `null=True` on a column that is in practice never null, and the reason is
    #: worth reading before copying: **a generated column can take no default**
    #: (Postgres refuses one — the expression IS the value), so the only way to
    #: declare an added column that needs no `DEFAULT` clause is to declare it
    #: nullable. Rule 22's hazard — "this fails on any table with rows" — cannot
    #: arise here: `ADD COLUMN … GENERATED ALWAYS AS (…) STORED` computes every
    #: existing row's value inside the same statement, which is why the
    #: migration needed no backfill. The expression coalesces, so what actually
    #: lands is an empty tsvector rather than a null.
    search_vector = models.GeneratedField(
        expression=(
            SearchVector("name", weight="A", config=SEARCH_CONFIG)
            + SearchVector("notes", weight="B", config=SEARCH_CONFIG)
        ),
        output_field=SearchVectorField(),
        db_persist=True,
        null=True,
    )

    # golden: duplicate attach merge import begin
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
            # golden: import begin
            # An import finds a widget by the id it has elsewhere, within one
            # branch: two branches may each hold the same outside system's `42`.
            models.UniqueConstraint(
                fields=["tenant", "organization", "external_ref"],
                condition=~models.Q(external_ref=""),
                name="widget_unique_external_ref_per_organization",
            ),
            # golden: import end
            # golden: duplicate attach merge import begin
            # A repeated duplicate press with one key answers the first copy:
            # the constraint is the model's, declared here (`core.E001` when it
            # is missing) — never added by the key field behind the migration's
            # back, which a fresh database could not migrate.
            duplicate_key_constraint(),
        ]
        # golden: duplicate attach merge import end
        # DECLARING `indexes` HERE SHADOWS THE ABSTRACT BASE'S (house rule 37).
        # Django does not merge `Meta.indexes` down an inheritance chain, so the
        # tenant-leading recency composite every `TenantScopedModel` gets is
        # re-added by hand here — it is the same index `0010` created and it
        # keeps its name, so the migration is a no-op for it rather than a drop
        # and a re-create. `core.TenantScopedModel.Meta` holds the reasoning.
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="widget_recency"),
            # The full-text index the degradation engine's real-column path
            # reads. GIN over the stored tsvector: the whole point of persisting
            # the column.
            GinIndex(fields=["search_vector"], name="widget_search_vector_gin"),
            # THE TRIGRAM INDEX, and what it is and is not for. `pg_trgm` gives
            # Postgres similarity and fast `ILIKE '%…%'` over `name`, which is
            # the half of Meilisearch's typo tolerance a relational fallback can
            # buy back. **The index is here; no query in this tree reads it
            # yet** — `PostgresEngine._ranked` still matches on the tsvector
            # alone, so a misspelled word still finds nothing while the circuit
            # is open. That gap is reported rather than papered over: an index
            # with no reader is the shape rule 30 exists to catch, and the
            # reader belongs in the search app's read path, not in this one.
            #
            # On the COLUMN rather than on `Upper(name)`: `pg_trgm` folds case
            # itself when it builds trigrams, so an upper-cased expression index
            # would cost a second copy of the same information and serve no
            # query the plain one does not.
            GinIndex(
                fields=["name"],
                opclasses=["gin_trgm_ops"],
                name="widget_name_trigram",
            ),
        ]

    # golden: archive version move bulk history duplicate attach merge import begin
    def __str__(self) -> str:
        return self.name

    # golden: archive version move bulk history duplicate attach merge import end
    # The two relation reads `WidgetOut` publishes, as properties rather than as
    # Pydantic field aliases — and that difference is load-bearing rather than
    # stylistic. An alias (`Field(alias="owner.email")`) is a *name*, and the
    # MCP transport serialises a tool result **by alias**, so the machine door
    # answered `owner.email` where the human door answered `owner_email`: one
    # row, two key sets, every value equal, which is a door-parity disagreement
    # no value-by-value test could catch (ADR example-3;
    # `apps/comms/models.py` is the precedent this follows).
    #
    # Neither costs a query: every read of this model goes through
    # `selectors.list_widgets` / `get_widget`, which select both relations. The
    # query pins on the list route and the list tool are what keep that true.

    # golden: archive version move bulk history duplicate attach merge import begin
    @property
    def owner_email(self) -> str:
        """Who owns this, without the caller having to fetch the owner."""
        return str(self.owner.email)

    @property
    def organization_slug(self) -> str:
        """Which part of the tenant owns it — the slug an `X-Org` header names."""
        return str(self.organization.slug)

    # golden: archive version end
    @property
    def owner_name(self) -> str | None:
        """Who owns it, in words — the move sheet's owner axis says it back.

        The user's `full_name` when the product's user model carries one, and
        `None` otherwise (`core.schemas.ArchivedByOut.name` reads the same way),
        which tells a screen to show the address instead. Costs no query: every
        read selects `owner`.
        """
        return getattr(self.owner, "full_name", None) or None


# golden: move bulk history duplicate attach merge import end
class WidgetPolicy(InheritedDownward, OrgScopedModel, Archivable):
    """Configuration one part of a tenant sets, **inherited by everything below**.

    This is the second shape a hierarchy needs and the one a flat product never
    notices it is missing: a row that is *config*, set at a node, and obeyed by
    every node underneath it. A quiet-hours window, a document template, a
    funnel definition and a pricing rule are all this shape.

    `InheritedDownward` is the declaration and it is the whole difference (ADR
    core-3). It makes `WidgetPolicy.objects.for_tenant(t).governing(org)` legal
    — the rows on this org's ancestor chain, nearest first — and it widens
    `core.authz.may_be_named` so a branch may *name* the policy its parent set
    for it. It does **not** widen `visible_to` by one row.

    **That asymmetry is the point, and it is what this app exists to show.**

    * A sub-seller **resolves** the policy its parent set: upward *config
      resolution*, because it was being governed by that policy whether it could
      see it or not.
    * A sub-seller **lists** only its own: downward *visibility*, unchanged. It
      never learns that its parent has a policy, or what the policy is called,
      unless somebody hands it the reference.

    Read the two together and the edge on the hole is visible: the caller has to
    already be holding the reference. `test_network.py` asserts both halves over
    the wire, because "the list does not show what the resolution used" is the
    kind of claim that is true until somebody adds a convenience `select_related`
    and nobody notices.

    `body` is deliberately meaningless — this is the template's worked example
    and a policy's *content* is the product's. What is worked here is where the
    row lives and who may resolve it.

    **Archivable, and held in the book by the widgets that name it.** An
    archived policy stops governing — `governing()` reads through
    `for_tenant()`, which leaves it out — so archiving one that a live widget
    still names would leave that widget governed by nothing it can see. The
    archive refuses instead, naming the widgets (`archive_blockers.py`), and
    nothing cascades.
    """

    #: ADR core-13, kind two of three. Config, not traffic — and a policy has no
    #: cascade parent at all: `tenant` and `organization` are PROTECT, and
    #: `Widget.policy` is PROTECT too, so a policy something was created under
    #: cannot leave while that widget still names it. Nothing sweeps it and no
    #: service deletes one. `bounded` would therefore be a lie here, which is
    #: the whole difference between this declaration and `Widget`'s.
    #:
    #: HOW TO CHOOSE IT: `unbounded` is the honest answer when a table grows
    #: with the BUSINESS rather than with time, and when that growth is a
    #: decision somebody took rather than a question nobody asked. That is why
    #: `reason` and `trigger` are mandatory here and absent on `bounded`:
    #: unbounded-by-decision and unbounded-by-nobody-thinking look identical in
    #: a schema, and the ISO date is what lets a reviewer age the decision
    #: instead of re-litigating it. `core.Organization` carries the same
    #: declaration for the same reason — a tenant's shape does not expire.
    #:
    #: Write a sentence a reviewer can DISAGREE with. "because we want it"
    #: clears every mechanical bar the primitive has and teaches nobody
    #: anything; the grammar is checked at import, the judgement is review's.
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
            # Per **organization**, not per tenant: two branches naming their
            # own policy "default" is not a collision, it is the ordinary case
            # — and it is exactly the case `governing()` resolves, nearest
            # first.
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


# golden: move bulk history duplicate attach merge import begin
class WidgetEntry(OrgScopedModel):
    """One line of a widget's ledger. **Append-only, and it lands where the widget is.**

    Two markers carry the whole meaning of this model and neither is enforced by
    anything this app wrote:

    * **`append_only = True`** — a service may create one and nothing anywhere
      may update or delete one. It is a class attribute rather than a base class
      (ADR core-6) and the population is *discovered*
      (`core.models.append_only_models`), so house rule 20 covers this model in
      the same commit that declares it, with no edit to `rules.yaml`. There is
      no update service, no PATCH route and no update tool — not as an omission,
      as the contract: a ledger with a write-back door is a ledger nobody can
      cite.
    * **`derive_org_from = "widget"`** — the landing gate. An entry does not
      *choose* its branch, it inherits the branch of the widget it describes,
      and `clean()` refuses a final `organization` that disagrees. That catches
      a whole class rather than a bug: a write that stamped the *actor's hat*
      onto a row hanging off something that lives somewhere else lands in a
      branch its own parent cannot see, silently, in whichever direction the
      mismatch went.

    `kind` is a closed vocabulary rather than free text, because the two lines
    this template writes come from two different places — a person recording
    one, and `approve_widget` recording the approval as it happens — and a
    ledger whose rows cannot be told apart by machine is a log.
    """

    #: House rule 20, declared rather than named: see `core.models.is_append_only`.
    append_only = True

    #: The landing gate: this row's organization is the widget's, or it is refused.
    derive_org_from = "widget"

    #: ADR core-13, kind three of three — and the reason this model is the one
    #: to read twice. It is declared BESIDE `append_only = True` above, and
    #: **the two are different questions with different answers**:
    #: `append_only = True` says a row is never REWRITTEN (rule 20, plus the
    #: runtime belt in `core.models.BaseModel.save`); this says what happens to
    #: the rows over TIME (rule 31) — nothing, on purpose, until a dated trigger
    #: fires. A table can be either without being the other, so declare both or
    #: neither deliberately. That coherence is what rule 31 makes checkable, and
    #: `core.AuditEntry` is the live member carrying both markers.
    #:
    #: HOW TO CHOOSE IT: `append_only` is `unbounded` that has also given up its
    #: delete, which is why it takes the same mandatory `reason` and dated
    #: `trigger`. Reach for it only when the row is EVIDENCE — a ledger line, a
    #: trail entry, a receipt — because giving up the delete is a promise made
    #: to whoever cites the row later, and it is not a promise a sweeper can be
    #: quietly added back to.
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


# golden: move bulk history duplicate attach merge import end
