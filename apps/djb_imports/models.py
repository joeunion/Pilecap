"""One row per file somebody asked to import, and one row per line of that file.

`Import` is the run: which file, which kind of row it makes, where it has got to
(`checking → previewed → importing → imported`, or `failed`), and what the dry
run and the apply counted. `ImportRow` is one line of the CSV — the values it
carried, what the preview said it WOULD do, and what the apply DID.

**The file is not copied here.** `file_version` points at the `files.FileVersion`
whose bytes were measured when they were stored, and `digest` repeats that
version's `sha256` because it is what makes staging idempotent: the same bytes
staged twice for the same kind, at the same organization, are the same run
(`import_one_live_run_per_digest` below).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import OrgScopedModel

#: How long a settled run and its rows live. The rows hold the imported data
#: itself — names, notes, whatever columns a product's importer declares — and a
#: second copy of a customer's data sitting in a staging table after the import
#: is done is a liability with no reader (principle 18). Thirty days: long
#: enough to answer "what did that import do", short enough that the copy dies.
#: A module constant for `apps.exports.models.EXPORT_RETENTION_DAYS`' reason.
IMPORT_RETENTION_DAYS = 30

#: The largest file an import takes, in data rows. Bigger is refused whole
#: (`import_invalid`) rather than applied in part.
MAX_IMPORT_ROWS = 10_000


class Import(OrgScopedModel):
    """One import run. **Org-scoped**: it lands at the acting hat, and so do its rows.

    The run is two workflows, never one waiting on a person: staging starts the
    check (the dry run: validate every row, write nothing to the noun), and the
    apply is a second start the person presses after reading the preview.
    """

    #: The authorization kind, prefixed like the app's label: a platform name a
    #: product never spells, so a product's own `Import` keeps the kind its class
    #: name derives. The policy keys and the road's url_names follow from it.
    authz_kind: ClassVar[str] = "djb_import"

    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.djb_imports.services.purge_imports",
        reason=(
            "a run's rows are a COPY of the file's data, and a copy that outlives the "
            "import it served is a liability with no reader. A run that has settled — "
            "imported, failed, or previewed and never applied — is deleted "
            f"{IMPORT_RETENTION_DAYS} days after its last change, and its rows go with "
            "it (CASCADE). A run still checking or importing is never swept."
        ),
    )

    class Status(models.TextChoices):
        CHECKING = "checking", "Checking"
        PREVIEWED = "previewed", "Previewed"
        IMPORTING = "importing", "Importing"
        IMPORTED = "imported", "Imported"
        FAILED = "failed", "Failed"

    #: The importer this file is read with — a key of some app's `IMPORTERS`.
    kind = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CHECKING)

    #: The version whose bytes are imported. `SET_NULL`, for the reason
    #: `Export.artifact_version` gives: `PROTECT` would let this app hold the
    #: files app's lifecycle hostage, and `CASCADE` would delete the record of an
    #: import because a document went. `digest` and `file_name` survive it.
    file_version = models.ForeignKey(
        "files.FileVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="djb_imports",
    )
    #: The document's name when it was staged, for a person reading the run.
    file_name = models.CharField(max_length=255)
    #: The version's measured SHA-256 — what "the same file" means.
    digest = models.CharField(max_length=64)

    #: The reverse accessors here and on `file_version` carry the label's
    #: prefix: they are names on another app's model, and a product's own
    #: `Import` keyed to the same model would otherwise clash with them
    #: (`fields.E304`).
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="djb_imports_requested",
    )
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="djb_imports_applied",
    )

    #: The caller's own name for this request; blank never collides.
    idempotency_key = models.CharField(max_length=255, blank=True)

    #: The counts. Written by the dry run (create/update/refused) and rewritten
    #: by the apply (create/update/unchanged/refused as they HAPPENED).
    count_create = models.PositiveIntegerField(default=0)
    count_update = models.PositiveIntegerField(default=0)
    count_unchanged = models.PositiveIntegerField(default=0)
    count_refused = models.PositiveIntegerField(default=0)

    applied_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    #: Why the run failed, as the refusal a client would have been sent
    #: (`{detail, code, errors?, remedies?}`), or `{}`.
    failure = models.JSONField(default=dict, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "import"
        verbose_name_plural = "imports"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "organization", "kind", "digest"],
                condition=~models.Q(status="failed"),
                name="djb_imports_import_one_live_run_per_digest",
            ),
            models.UniqueConstraint(
                fields=["tenant", "organization", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="djb_imports_import_unique_idempotency_key_per_organization",
            ),
        ]
        # The inherited recency composite, re-added under this table's name
        # (house rule 37): the base's `%(class)s_recency` would be
        # `import_recency`, and index names are global to the Postgres schema —
        # a product's own `Import` already owns that one.
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["tenant", "-created_at"], name="djb_imports_import_recency"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} import of {self.file_name} ({self.status})"

    @property
    def counts(self) -> dict[str, int]:
        """The four counts as one object — the read shape's `counts`."""
        return {
            "create": self.count_create,
            "update": self.count_update,
            "unchanged": self.count_unchanged,
            "refused": self.count_refused,
        }

    @property
    def apply_writes(self) -> int:
        """Rows that write to the noun: what the apply WILL write, then what it DID."""
        return self.count_create + self.count_update

    @property
    def expires_at(self) -> datetime:
        """When the sweep may take this run, counted from its last change."""
        return self.updated_at + timedelta(days=IMPORT_RETENTION_DAYS)


class ImportRow(OrgScopedModel):
    """One data line of an import's file. **Dies with its run.**

    `authz_kind_of = "run"`: reading a row is reading the run, so a row has no
    kind of its own. `derive_org_from = "run"`: a row lands where its run is.
    (The key is `run` and not `import_`: Django refuses a field name ending in an
    underscore, `fields.E001`, and `import` is a keyword.)
    """

    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    authz_kind_of: ClassVar[str] = "run"
    derive_org_from = "run"

    class Preview(models.TextChoices):
        CREATE = "create", "Would create"
        UPDATE = "update", "Would update"
        REFUSED = "refused", "Refused"

    class Outcome(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        UNCHANGED = "unchanged", "Unchanged"
        REFUSED = "refused", "Refused"

    run = models.ForeignKey(Import, on_delete=models.CASCADE, related_name="rows")
    #: The line's position among the data rows, from 1 (the header is not a row).
    row_no = models.PositiveIntegerField()
    #: The values the line carried, by column.
    data = models.JSONField(default=dict, blank=True)
    outcome_preview = models.CharField(max_length=16, choices=Preview.choices)
    #: Blank until the apply has settled this row; set exactly once.
    outcome = models.CharField(max_length=16, choices=Outcome.choices, blank=True)
    #: The refusal this row got, as the wire body (`{detail, code, errors?}`), or `{}`.
    refusal = models.JSONField(default=dict, blank=True)
    #: The noun row this line created or updated, when it did.
    object_id = models.UUIDField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "import row"
        verbose_name_plural = "import rows"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "row_no"], name="djb_imports_importrow_one_row_per_line"
            ),
        ]
        # The inherited recency composite, re-added under this table's name
        # (house rule 37), for the reason `Import.Meta` gives.
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["tenant", "-created_at"], name="djb_imports_importrow_recency"),
        ]

    def __str__(self) -> str:
        return f"row {self.row_no} of {self.run_id}"
