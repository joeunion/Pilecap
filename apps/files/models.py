"""A document and its versions. Two tables, because they age differently.

ADR files-2. The identity of a document — what it is called, what it is for,
who filed it, whether it has been archived — is a thing people edit. The bytes
are a thing nothing may edit: a digest recorded in an export manifest, an audit
row that says which version was handed out, and a presigned URL already issued
all have to still mean what they meant when they were written.

So `StoredFile` carries the mutable identity and `FileVersion` carries the
immutable object, one row per version, each with **its own key**. "Replace this
document" allocates version n+1 and finalizes it; version n stays readable,
stays presignable, and stays true for whatever cited it.

**What was rejected, and why it matters at this file's level:** a `version`
column mutated in place would rewrite `sha256` and `size_bytes` under every row
that already quoted them — "who uploaded v2, and what did v1 hold" becomes
unanswerable. A latest-pointer key (one stable key per document, overwritten)
would make a presigned GET issued before a replace serve the new bytes after it,
so an audited URL's meaning would change after issuance. Both are in the ADR's
rejection list; the shape below is what makes them impossible rather than
discouraged.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import OrgScopedModel

#: The longest key this app builds, with room to spare. A key is
#: `t/<uuid>/f/<uuid>/v/<n>` — 85 characters at a four-digit version — and S3's
#: own limit is 1024 bytes, so this column is generous rather than tight on
#: purpose: the shape is fixed by `storage.version_key` and a column that had to
#: be widened to hold a key would be a migration on a table full of them.
MAX_KEY_LENGTH = 255

#: Long enough for the longest name a browser will send and short enough that
#: the column is not a text field nobody indexes.
MAX_FILENAME_LENGTH = 255

#: A hex SHA-256, exactly.
SHA256_LENGTH = 64

#: How long a `PENDING` version may sit unfinished before `SweepPendingUploads`
#: takes it. **Twenty-four hours, and the number is chosen against a different
#: number**: an upload URL is good for `FILES_UPLOAD_URL_TTL` (fifteen minutes,
#: `storage.py`), so by the time this window closes the credential that could
#: have written to the key has been dead for the better part of a day. Anything
#: still `PENDING` is an upload nobody is making, and the sweep can take it
#: without ever racing a PUT in flight.
#:
#: **A constant rather than a setting**, and the same reasoning
#: `MAX_DECLARED_UPLOAD_BYTES` above records for itself and
#: `apps.exports.models.EXPORT_RETENTION_DAYS` records for the export window: a
#: retention window is a data-policy decision a customer contract can move, and
#: this app's territory did not include `config/settings/`. The trigger for
#: promoting it to an environment variable is the first deployment that needs a
#: different window from the template's.
PENDING_UPLOAD_TTL_HOURS = 24


class StoredFile(OrgScopedModel):
    """One document: what it is called, what it is for, and which version is current.

    **Org-scoped**: a file belongs to the part of the tenant that
    filed it, so a branch reading its own documents never sees a sibling's, and
    a tenant-wide read is what wearing the root hat already means. Every read is
    `for_tenant(t).visible_to(actor_or_org)` — house rule 24, both halves.

    **`filename` is a label and `key` is the identity** (ADR files-2).
    Renaming a document is an edit to this row and touches no object: the thing
    that survives a rename is the version's key, which carries primary keys and
    a version ordinal and nothing else. That is also why a key never carries the
    tenant's slug or the filename — a slug can be re-issued and a filename is
    user input, and neither is allowed to be part of where bytes live.

    **`archived_at` and not `is_deleted`** (house rule 15): archiving is a
    status a row carries, the object stays until purge, and the honest statement
    about that residual is in the lifecycle declaration below.
    """

    #: **The authorization kind, declared rather than derived** (rule 54 (a)).
    #:
    #: `snake_case(StoredFile)` is `stored_file`, and every key this app has ever
    #: had is `file.*` — `file.create`, `file.read`, `file.replace`,
    #: `file.archive`, written into policies, into published route contracts and
    #: into whatever a deployment's `Grant` rows already say. The key vocabulary
    #: predates the class name, and between renaming four published words and
    #: writing one line here, this is the line.
    #:
    #: It is also the honest reading: the thing somebody is given authority over
    #: is the DOCUMENT. `StoredFile` is what this codebase calls the row because
    #: `File` is a builtin; `file` is what the product calls the thing.
    authz_kind: ClassVar[str] = "file"

    #: ADR core-13, and the honest kind rather than the comfortable one.
    #:
    #: `bounded` would be wrong: `tenant` and `organization` are both PROTECT
    #: (`core.models`), so nothing cascades onto this table from anywhere and
    #: there is no parent whose death takes these rows with it — the same
    #: argument `comms.Recipient` makes about itself. `purged` would be worse:
    #: it would name a sweeper, and ADR files-2 rules object purge OUT of v1
    #: with a dated trigger. A `purged_by` pointing at a callable that does not
    #: exist is exactly the poller-that-was-never-built this vocabulary exists
    #: to catch, so this says `unbounded` and carries the residual out loud.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "archive is soft and purge is not built. `archive_file` sets `archived_at`; "
            "the row stays, its versions stay, and THE OBJECTS STAY IN THE BUCKET — "
            "which is the liability this sentence exists to keep visible, because an "
            "archived document reads like a deleted one to everybody except the bucket. "
            "ADR files-2 excludes purge from v1 deliberately (retention policy, tenant "
            "close and erasure all want to decide it together, and a delete written "
            "before they have is a delete written twice). SECOND POPULATION, and it is "
            "declared here rather than left for whoever finds it (a known frontier): an "
            "EXPORT ARCHIVE is filed through this app, and "
            "`apps.exports.services.purge_exports` deletes the object and the `Export` "
            "row at thirty days and deliberately leaves this row and its version — a "
            "few hundred bytes of metadata holding a key whose bytes are gone. That is "
            "not an oversight and it is not a promise either: the liability the export "
            "declaration exists to end is the COPY, and reaching these rows needs a "
            "document-retirement service this app does not have (`archived_at` hides a "
            "document; nothing deletes one), which the other app must not write for it "
            "(house rule 10). Until then such a row reads as a document whose download "
            "will refuse, and `is_downloadable` is what says so at the export end."
        ),
        trigger=(
            "2026-08-24 — the first of: the purge rung that lands "
            "`delete_tenant_objects` (ADR files-2 § exclusions, 'object purge'), a "
            "stated retention obligation, or the first tenant close that has to answer "
            "for the bytes. On that day this declaration becomes `purged` with the "
            "callable named, and this row's residual stops being a residual. The "
            "export-archive population above joins the same rung: a document-retirement "
            "service is what both halves are waiting for, and building one of them "
            "without the other would leave the tree with two answers to the same "
            "question."
        ),
    )

    class Purpose(models.TextChoices):
        """The platform's own labels for why a document exists.

        **The field is not constrained by these and that is deliberate.** What a
        product files is the product's vocabulary — a `contract`, a `lab-result`,
        a `paper` — and a closed enum here would make every product's own label a
        migration on a platform table. What these three buy is that platform code
        never spells a literal: `store_bytes(purpose=StoredFile.Purpose.EXPORT)`
        rather than `purpose="export"`, which is house rule 16's reasoning applied
        where the rule itself does not reach.
        """

        UPLOAD = "upload", "Uploaded by a person"
        GENERATED_DOCUMENT = "generated-document", "Rendered by the platform"
        EXPORT = "export", "A tenant's own data archive"

    #: The display name, renamable. See the class docstring: this is a label for
    #: a human reading a list, and nothing about where the bytes live depends on
    #: it.
    filename = models.CharField(max_length=MAX_FILENAME_LENGTH)

    #: The short label the audit trail reads. Open vocabulary — see `Purpose`.
    purpose = models.CharField(max_length=64)

    #: Which version a reader gets when they do not name one. **Zero until the
    #: first finalize**, which is a real state and not a placeholder: a document
    #: whose only version is still `PENDING` has no current bytes, and a reader
    #: asking for them should be refused rather than handed version 1's empty
    #: key. Advanced only by `record_stored`, under `select_for_update`, and only
    #: ever upward — two versions finalizing out of order converge
    #: on the highest STORED one rather than fighting.
    current_version = models.PositiveIntegerField(default=0)

    #: Who filed it. `PROTECT` because "who uploaded this" is a question the
    #: audit trail has to be able to answer for as long as the document exists.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_files",
    )

    #: Soft delete. Null means live; a timestamp means archived, and the
    #: objects are still in the bucket until purge lands — see `lifecycle`.
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "stored file"
        verbose_name_plural = "stored files"
        # NO `indexes` HERE, deliberately. `TenantScopedModel.Meta` declares the
        # tenant-leading recency composite (ADR core-11) and Django does NOT
        # merge `Meta.indexes` down an inheritance chain — a concrete model that
        # declares its own SHADOWS the inherited one. House rule 37 is the
        # tripwire over exactly that hole; the way to stay on the right side of
        # it is to not declare `indexes` at all unless this table needs one, and
        # then to re-add the recency index by hand in the same breath.

    def __str__(self) -> str:
        return f"{self.filename} (v{self.current_version})"


class FileVersion(OrgScopedModel):
    """One immutable object: its key, its measured digest, its measured size.

    **`derive_org_from = "file"`**: a version lands where its
    document lives, never where the uploader's hat happens to point. Without it
    a user acting under branch B could add a version to a document owned by
    branch A and the row would land in B — invisible to A, which owns the
    document it belongs to. `OrgScopedModel.clean()` refuses that mismatch on
    insert and on update alike.

    **The digest and the size are OURS.** They are blank until `verify_object`
    has streamed the object and measured it; what a client declared at upload
    time is used to enforce the size policy and is never written here. A digest
    a client supplied is a digest that says whatever the client wanted it to.

    **Why this is not `append_only`.** A version row transitions status exactly
    once, `PENDING → STORED`, so declaring house rule 20's `append_only` would
    be a lie — that rule is for populations nothing ever updates. The immutable
    half is the OBJECT, and it is held by three things that are not this
    declaration: the unique key constraint below, the presign fence in
    `storage.py` (an upload URL is minted only for a `PENDING` version), and the
    conditional-write belt on the presigned PUT.
    """

    #: **A version is authorized as its DOCUMENT** (rule 54 (e)). It names the
    #: foreign key, not the kind: `core.authz` reads the field, walks to
    #: `StoredFile` and takes that model's kind — and REFUSES the declaration if
    #: the key is not `CASCADE`, because the claim being made is that a version
    #: dies with its document and that writing a version IS writing the
    #: document. Both are true here: the FK below cascades, and "add a version"
    #: is the `file.replace` verb on the parent, which is the same argument
    #: `quality/rules.yaml`'s `policy_exemptions` entry for this model already
    #: makes. A `file_version.*` key would be a second, weaker vocabulary about
    #: a question `file.*` has already answered.
    authz_kind_of: ClassVar[str] = "file"

    #: `purged`, and it used to say `bounded`. **Both halves are true and only
    #: one of them can be the kind**, so this names the one with a sweeper behind
    #: it: `_refuse_malformed` puts it plainly — a sweeper named on a bounded
    #: table is either a wrong kind or a delete nobody meant to declare — and
    #: after this there IS a delete, so `bounded` would be the declaration that
    #: hides it.
    #:
    #: The chain rule 31 walks from here is:
    #:
    #:     purged_by -> `apps.files.activities.sweep_pending_uploads`
    #:               -> `SweepPendingUploadsWorkflow`
    #:               -> `apps.files.activities.SCHEDULES`
    #:
    #: and `tests/test_lifecycle.py` walks it link by link from inside the app,
    #: plus the one thing a static walk cannot see: what the sweep deletes, and
    #: what it leaves.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.files.services.purge_pending_versions",
        reason=(
            "TWO POPULATIONS, one table. A version that reached `STORED` dies with its "
            "document and never on its own — `file` below is CASCADE, which is what "
            f"`bounded` would have said. A version still `PENDING` after "
            f"{PENDING_UPLOAD_TTL_HOURS} hours is an upload that never happened, and it "
            "is swept: the row goes, because there is deliberately no `FAILED` status "
            "for it to move to and a third state on a two-state model would have to be "
            "undone by hand the moment a bucket came back. The OBJECT at that key, if a "
            "hijacked or very slow PUT ever put one there, is not this sweep's to take "
            "— object purge is `StoredFile`'s declared residual and lands with "
            "`delete_tenant_objects`."
        ),
    )

    class Status(models.TextChoices):
        """Two states, one transition, in services only.

        `PENDING` means a key has been allocated and an upload URL may be minted
        for it. `STORED` means `verify_object` has seen the object, measured it,
        and `record_stored` has written what it measured. There is no `FAILED`:
        an upload that never lands stays `PENDING` until `SweepPendingUploads`
        expires it, because "nothing arrived" is the absence of a transition
        rather than a state of its own.
        """

        PENDING = "pending", "Awaiting upload"
        STORED = "stored", "Stored and verified"

    #: The document this is a version of. **CASCADE** — an owned child of the
    #: aggregate: a version has no meaning without its file, and
    #: nothing outside this app ever points at a version row.
    file = models.ForeignKey(
        StoredFile,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    #: The ordinal, allocated under `select_for_update` on the parent so
    #: two concurrent replaces get n+1 and n+2 rather than one number twice.
    version = models.PositiveIntegerField()

    #: **Where the bytes are, forever.** Built by `storage.version_key` and never
    #: anywhere else; unique across the deployment by the constraint below. It
    #: carries the tenant's primary key, the file's, and the ordinal — no slug,
    #: no filename, no digest (a content-addressed key would make an instant
    #: upload a cross-tenant existence oracle) — and the tenant is in it while
    #: the organization deliberately is not, because re-parenting a branch must
    #: never orphan an object.
    key = models.CharField(max_length=MAX_KEY_LENGTH)

    #: What the uploader said the bytes are. Advisory: it is what a download
    #: response will carry, and it is not evidence of anything.
    content_type = models.CharField(max_length=255)

    #: **What we measured**, null until `verify_object` has. Null rather than
    #: zero because a zero-byte object is a real thing somebody can upload, and
    #: a column where "not measured yet" and "measured, empty" are the same
    #: value cannot answer the question it exists for.
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)

    #: The hex SHA-256 of the bytes **we hold**, computed by us by streaming the
    #: object. Blank until verified; a digest is never legitimately empty, so
    #: blank is unambiguous here in a way a null size is not.
    sha256 = models.CharField(max_length=SHA256_LENGTH, blank=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    #: Who uploaded this particular version — not the same question as who filed
    #: the document, which is the whole reason replace is a new row.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_file_versions",
    )

    #: A version lands where its document lives, never where the uploader's hat
    #: points. See the class docstring.
    derive_org_from = "file"

    class Meta(OrgScopedModel.Meta):
        verbose_name = "file version"
        verbose_name_plural = "file versions"
        # NO `indexes` HERE either — same reason as `StoredFile`'s, house rule 37.
        constraints = [
            # Invariants the database holds, not a service that remembers.
            models.UniqueConstraint(
                fields=["file", "version"],
                name="fileversion_one_row_per_version",
            ),
            # Unique across the whole deployment and not merely per tenant: the
            # key already carries the tenant's primary key, so a collision here
            # would mean two rows claiming one object, which is the single thing
            # this design must make impossible.
            models.UniqueConstraint(
                fields=["key"],
                name="fileversion_one_row_per_object",
            ),
            # A STORED version has been measured. The implication runs one way
            # on purpose: this refuses the row that says "stored" while carrying
            # no evidence of what was stored, and stays out of the way of a
            # PENDING row that a future rung might want to annotate.
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="stored")
                    | (models.Q(size_bytes__isnull=False) & ~models.Q(sha256=""))
                ),
                name="fileversion_stored_is_measured",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.file_id} v{self.version} ({self.status})"
