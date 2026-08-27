"""One row per archive somebody asked for.

The row is the request, the receipt and the address of the artifact, in that
order over time. Nothing here holds the archive itself: a zip of a tenant's
whole database does not belong in a column, and `artifact_key` is a key in the
**files seam's** bucket, built by `files.storage.version_key` — primary keys and
a version ordinal, never a slug and never a filename (ADR files-2).

**This app used to build its own key** (`core.storage.tenant_prefixed_key`,
`"tenants/<slug>/<uuid>-<name>"`) and write through `default_storage`. XPr
retired both: that grammar quoted two renamable, re-issuable, user-supplied
things, which ADR files-2 rules against, and F1 recorded the contradiction as a
SUPERSESSION rather than a promotion. The archive is now an ordinary document in
`apps.files` — filed by `files.services.store_stream`, addressed by
`files.storage`, signed for by `files.storage.presign_get` — and what is left
here is the two halves a row owes: where the bytes are (`artifact_key`) and what
they were when we wrote them (`artifact_version`, which carries the digest).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import OrgScopedModel
from apps.files import storage as files_storage

#: How long an archive lives before the sweep takes it — the artifact from
#: storage and the row with it. Thirty days: long enough that a customer who
#: asked on a Friday and read their mail the following month still has it, short
#: enough that a copy of a tenant's whole database is not sitting in a bucket
#: for a year because nobody chose a number.
#:
#: A module constant rather than a setting, and the same honest gap
#: `apps.connections.activities.INBOUND_WEBHOOK_RETENTION_DAYS` records: a
#: retention window is a data-policy decision a customer contract can move, and
#: `config/settings/` is out of this app's territory. The trigger for
#: promoting it is the first deployment that needs a different window from the
#: template's.
EXPORT_RETENTION_DAYS = 30


class Export(OrgScopedModel):
    """An archive of one tenant's rows — or of one branch's — as a row.

    **Org-scoped, and that is the whole authorization design.** An export lands
    at the organization the request was made under, and what it may contain is
    read with the same `for_tenant(t).visible_to(org)` every other read in this
    product uses. So a branch manager exporting their own subtree needs no new
    permission at all: rule 24 already answers "which part of the network", and
    the walk simply asks it once per model. What needs a permission is the
    other one — a **tenant-wide** export, which is the whole deployment's copy
    of one customer, and which `policies.can_request` puts behind
    `accounts.policies.administers_the_whole_tenant`, the same ceiling erasure
    stands behind.

    The row is also **census-included**: `Export` is org-scoped, so an export
    contains the tenant's own export rows. That does not recurse, because what
    the row carries is the artifact's *key* and never the artifact — a fact
    worth stating because it is the first thing a reader worries about.
    """

    #: ADR core-13, and the kind this app is the newest member of. A copy of
    #: somebody's database sitting in a bucket forever is the failure this
    #: declaration exists to prevent, so `purged` is the only honest kind and
    #: the sweeper lands in the same commit as the declaration — which is rule
    #: 31's own discipline, honoured by the rung that ships the rule's newest
    #: member. The chain rule 31 walks from here is:
    #:
    #:     purged_by -> `apps.exports.activities.purge_expired_exports`
    #:               -> `PurgeExportsWorkflow`
    #:               -> `apps.exports.activities.SCHEDULES`
    #:
    #: and `tests/test_lifecycle.py` walks it link by link from inside the app,
    #: plus the one thing a static walk cannot see: what the sweep deletes, and
    #: what it leaves.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.exports.services.purge_exports",
        reason=(
            "an export is a COPY of everything a tenant has, in one file, and a copy "
            "that outlives the reason it was made is the largest single liability this "
            "product can create. It is deleted from storage and from the table "
            f"{EXPORT_RETENTION_DAYS} days after it was asked for — the artifact first, "
            "then the row, so a failure between the two leaves a row pointing at "
            "nothing rather than an orphan nobody can find."
        ),
    )

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Scope(models.TextChoices):
        """How wide the walk goes, and it is a field rather than an inference.

        `ORGANIZATION` is the acting hat's subtree — free by rule 24, because
        that is exactly what the caller can already read at every other door.
        `TENANT` is the whole customer, which is a different act with a
        different ceiling, so it is something a caller asks for out loud rather
        than something they get by being an administrator.
        """

        TENANT = "tenant", "The whole tenant"
        ORGANIZATION = "organization", "This organization and everything under it"

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.ORGANIZATION)

    #: Who asked. `SET_NULL` for the reason `core.AuditEntry`'s pointers are:
    #: a person erased under a data-protection request must not take the record
    #: that an export happened with them.
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exports_requested",
    )

    #: What the archive says about itself: the models walked, the row counts,
    #: the fields left out and why, and the models skipped and why. The SAME
    #: object is written into the zip as `manifest.json`, so the row and the
    #: artifact cannot come to disagree — and `tests/test_archive.py` compares
    #: the two against the database, three ways.
    manifest = models.JSONField(default=dict, blank=True)

    #: **Where the bytes are** — a key in the files seam's bucket, built by
    #: `files.storage.version_key` and copied off the `FileVersion` by
    #: `finish_export`. Blank until the run finishes. Blank rather than null:
    #: this is a string that is sometimes empty, not a value that is sometimes
    #: absent, and `""` is what every other CharField in this tree says for
    #: "not yet".
    #:
    #: **Denormalized on purpose, and the duplication is load-bearing.** It
    #: repeats `artifact_version.key`, and it outlives it: `artifact_version` is
    #: `SET_NULL`, so the day the files app grows a document sweep the pointer
    #: can go while the purge still has to reach exactly these bytes. An address
    #: the sweep cannot lose is what makes the `PURGED` declaration above a
    #: promise rather than a hope. The two never disagree because only
    #: `finish_export` writes either, from one `FileVersion`, in one statement.
    artifact_key = models.CharField(max_length=1024, blank=True)

    #: **What the bytes were when we wrote them** — the files-app row that owns
    #: the object, carrying the digest and the size this deployment MEASURED
    #: rather than counted (`files.services.store_stream`). The re-point's
    #: fourth item (the dependency-boundary decision: *the artifact
    #: reference onto the files app's blob model*), and the reason it is a
    #: relation and not three more columns here: a departing customer verifying
    #: an archive months later needs a digest whose provenance is the same
    #: instrument every other document in the product was measured with.
    #:
    #: **`SET_NULL`, not `PROTECT`.** `PROTECT` would make `apps.files` unable
    #: to sweep its own rows for as long as any export named one, which is one
    #: app holding another's lifecycle hostage. `CASCADE` would be worse: it
    #: would delete the export RECORD — the receipt a customer's own archive
    #: carries — because a file row went. Null here means "the artifact row is
    #: gone"; `artifact_key` still says where the bytes were, and
    #: `is_downloadable` reads that.
    artifact_version = models.ForeignKey(
        "files.FileVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="export_artifacts",
    )

    #: How big the archive is, so a client can decide whether to fetch it now.
    artifact_bytes = models.BigIntegerField(default=0)

    completed_at = models.DateTimeField(null=True, blank=True)

    #: What a failed run says. The activity's own complaint, walked out of the
    #: cause chain by the workflow, not the wrapper's "Activity task failed".
    error = models.TextField(blank=True)

    #: The caller's own name for this request, so a retry does not make a second
    #: archive. Blank means "no key was sent", and blank rows never collide:
    #: the uniqueness constraint below is partial.
    idempotency_key = models.CharField(max_length=255, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "export"
        verbose_name_plural = "exports"
        constraints = [
            # Per **organization**, not per tenant, and that is the same
            # reasoning `WidgetPolicy`'s name constraint carries: a key is a
            # caller's own name for their own request, two branches picking
            # "nightly" is not a collision, and a tenant-wide constraint would
            # answer the second branch with an integrity error about a row it
            # cannot see. Partial, so the blank default is not a collision at
            # all — a `condition` rather than a nullable column, because a
            # nullable CharField is two spellings of empty.
            models.UniqueConstraint(
                fields=["tenant", "organization", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="export_unique_idempotency_key_per_organization",
            ),
        ]
        # No index declared here. The sweep reads `created_at < before` across
        # every tenant at once — the only query in this app that is not
        # tenant-leading, which is what a retention sweep is — and `BaseModel`
        # already indexes `created_at` for every model in the product. A second
        # index over the same column would be a write cost buying a plan
        # Postgres already has.

    def __str__(self) -> str:
        return f"{self.scope} export of {self.tenant_id} ({self.status})"

    @property
    def organization_slug(self) -> str:
        """Which part of the tenant asked — a property, not a schema alias.

        ADR example-3: an alias is a NAME, and the REST door renders by field
        name while the MCP transport renders `structuredContent` by alias. One
        row, two key sets. A model property is found by both doors under one
        name, which is what `tests/test_doors_over_the_wire.py` holds.
        """
        return str(self.organization.slug)

    @property
    def expires_at(self) -> datetime:
        """When the sweep takes the artifact and this row.

        Derived rather than stored, and the window lives in ONE place — the
        `ScheduleDeclaration`'s action in `activities.py`, where an operator can
        read it off the schedule in the Temporal UI instead of out of the
        source. A stored copy would be a second answer that a changed window
        silently disagrees with, for every row already in the table.

        Measured from `created_at` and not from `completed_at`, which is what
        makes the sweep total: a run that never finished has no completion to
        count from, and a pending export that has been pending for a month is
        exactly as much of a copy-of-everything as a finished one.
        """
        return self.created_at + timedelta(days=EXPORT_RETENTION_DAYS)

    @property
    def is_downloadable(self) -> bool:
        """Whether there is an artifact to fetch right now.

        Both halves, because either alone is a lie: a `completed` row whose key
        the purge has already blanked has nothing behind it, and a key on a row
        that is still running names an object that is half-written.
        """
        return self.status == self.Status.COMPLETED and bool(self.artifact_key)

    @property
    def download_path(self) -> str | None:
        """Where to fetch the archive with your own credential. `None` until there is one.

        `reverse()`d rather than spelled, for `core.views`' reason: `config/urls.py`
        owns the version segment and an app never writes it, so a `v2` mount moves
        this string without anybody editing this app.
        """
        if not self.is_downloadable:
            return None
        return str(reverse("api:export-download", kwargs={"export_id": self.pk}))

    @property
    def artifact_sha256(self) -> str:
        """The digest of the archive we hold, or `""` once the artifact row is gone.

        Read through the relation rather than copied into a column here: the
        digest is `apps.files`' measurement, taken by the same instrument every
        other document in this product was measured with, and a second copy in
        this table would be a number that could come to disagree with the one
        the file's own audit row quotes.
        """
        version = self.artifact_version
        if version is None:
            return ""
        return str(version.sha256)

    @property
    def download_url(self) -> str | None:
        """A **presigned** URL straight to the object store. `None` until there is one.

        **Always signed now, and that is XP-1's own ratified either/or resolving
        to its first branch** — *"a presigned `download_url` where the backend
        signs, and an authenticated `/download` stream otherwise"*. There is no
        otherwise left: the archive lives in the files seam's bucket, and
        `files.storage.bucket_name()` refuses a deployment that has named none,
        so an export artifact only ever exists somewhere that signs (MinIO on a
        laptop, in CI and in every worktree; S3 in a deployment). The old
        `storage_signs_urls()` capability probe asked `default_storage` a
        question that now has one answer, and it is gone with the backend it
        asked.

        `None` here is still not "not ready": it means there is no artifact at
        all, and `download_path` is `None` in exactly the same case, so a client
        reading `download_url or download_path` is right as it always was. That
        pair, and not a flag, is what the read shape publishes.

        **The TTL is the files seam's** (`DOWNLOAD_URL_TTL_SECONDS`, five
        minutes — ADR files-2 § "Presigned URLs"), inherited rather than restated:
        that is the first of the four re-point items, and a number copied here
        would be a second posture that drifts. Five minutes is short because a
        presigned URL is a stateless signature nobody can revoke; a client that
        needs the bytes again re-reads this row and gets a fresh one.
        """
        if not self.is_downloadable:
            return None
        return files_storage.presign_get(tenant=self.tenant, key=self.artifact_key)
