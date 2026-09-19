"""Writes for the files app. **The bytes are not here, and that is the design.**

Between them these services own the whole life of a document, from the moment
somebody files one to the moment somebody takes it out of the working set. They
are listed by what they do rather than counted, because a count in a docstring is
a number that goes stale invisibly — this list said "five" while there were
six, and the missing one was `store_stream`, the only one with a live production
caller):

* `create_file` — a new document at version 1, and a presigned PUT for it;
* `add_version` — **the replace verb**: version n+1 beside version n, which is
  untouched, still readable, still presignable, and still true for whatever
  already quoted its digest;
* `confirm_upload` — the client says it has finished; this starts the run that
  goes and looks;
* `record_stored` — what the platform MEASURED, written down: the status flip,
  the digest, the size, the meter and the event, all in one transaction;
* `issue_download_url` — the audited read: a short-lived link to ONE version's
  bytes, and an `AuditEntry` naming which version was signed for;
* `archive_file` — out of the working set, softly: `archived_at` is set, the
  versions stay readable and the objects stay in the bucket;
* `store_bytes` — the document-generation seam: one call an activity makes with
  bytes the platform rendered itself;
* `store_stream` — the same seam for a body too large to hold: an archive goes to
  the store a chunk at a time;
* `purge_pending_versions` — **the deployment's own sweep**, and the only one
  here nobody asks for: it expires the uploads that never happened and archives
  the documents they leave with nothing behind them. It names no tenant and
  resolves no actor, because it is scoped by the clock rather than by anybody.

**Nothing here takes a client's word for anything about the object.** A caller
declares a size so the size policy has something to refuse; the size that is
recorded and metered is the one `storage.sha256_of` counted while streaming the
object back out of the store. A digest a client supplied is a digest that says
whatever the client wanted it to.

**Where the bytes actually move.** `create_file` and `add_version` mint a
presigned PUT and return it; the client uploads to the object store directly.
`store_bytes` is the one path where the platform holds the bytes, and even there
they go to the store through `storage.py` and come back through it to be
measured — the row never learns a number that did not come off the wire.

**Placement is the acting hat, never the root** (ADR core-20). There is no
`organization=` parameter anywhere below, so no caller can file a document in a
branch it holds no membership over; an actor with no resolved hat is refused
rather than defaulted, because a document at the root is one branch's paperwork
silently attributed to the whole tenant. A version lands where its document
lives (`FileVersion.derive_org_from`), which the model's landing gate enforces on
insert and update alike.

**A person is required, and it is required HERE rather than at the door.**
Everything below that files a document or adds a version calls `_uploader_id`,
which refuses an actor carrying no user: `uploaded_by` is non-null and `PROTECT`
on both models, because "who filed this" has to stay answerable for as long as the
document exists. The consequence for a machine caller is stated on
`store_bytes`/`store_stream`, because that is where it bites — an activity's
house-shaped `system_actor(tenant, org)` carries no person and is refused.

Refusals are `apps.core.exceptions` and nothing else: no `HttpError`, no status
code (house rule 14). `api.py` and `mcp.py` map them, and neither maps anything
of its own — `config/api.py` and `core.mcp.tool_call` are the two composers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import models, transaction
from django.utils import timezone

from apps.core.actor import Actor, system_actor
from apps.core.authz import may_be_named, require
from apps.core.exceptions import Conflict, Invalid, NotFound, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.service import service
from apps.events.services import emit
from apps.files import storage
from apps.files.events import FILE_ARCHIVED, FILE_STORED
from apps.files.meters import STORAGE_BYTES
from apps.files.models import FileVersion, StoredFile
from apps.files.schemas import FileStoredOut, FileVersionOut, StoredFileOut
from apps.files.types import (
    FINALIZE_WORKFLOW,
    FinalizeUpload,
    SweepOutcome,
)
from apps.usage.services import record_usage
from apps.workflows.services import start_workflow_on_commit, workflow_id

log = get_logger("apps.files.services")

#: What may appear un-redacted in this app's log lines and audit `input`
#: (`core.service`). An allow-list, not a blocklist.
#:
#: **`filename` is deliberately absent.** It is the one field here that is free
#: user input about a document's subject, and a filename is routinely a fact
#: about a person — `mri-results-jane.pdf`, `termination-letter-okonkwo.docx`.
#: The audit row still names the ROW, which is how "who filed what" is answered
#: without the log line spelling it.
#:
#: What is here is the shape of the work rather than its content: a `purpose`
#: from an open but small vocabulary, a `content_type` from IANA's, a declared
#: `size_bytes`, a machine's own `idempotency_key`, and — on `record_stored` —
#: the `sha256` and `size_bytes` this platform measured, which are the numbers
#: the row is ABOUT. An audit of a storage event that could not say what was
#: measured would be an audit of nothing.
#:
#: **`file` and `version` are here because of the issuance audit.** An
#: `AuditEntry` names its object by reading the service's RETURN value, and
#: `core.service._object_of` recognises a model — so a service returning a ticket
#: names no object, which `UploadTicket` records as this app's declared blind
#: spot. The design decides it for the app the only way that does not put a URL in a
#: column: the rows the act was ABOUT travel in `input`, where `redact` renders a
#: model instance as `<label>:<pk>` and never as a copy of the row. So
#: `issue_download_url`'s audit row says which document and **which version was
#: signed for** (ADR files-2 § "Audit semantics"), and it says it whether or not
#: the caller named the version, because the version reaching the service is
#: already the resolved one.
#: **`before` is here because it is the whole content of the sweep's audit row.**
#: `purge_pending_versions` names no tenant, resolves no actor and returns two
#: integers, so the one thing its row can say that is worth reading later is
#: WHICH WINDOW it swept. A timestamp is a fact about the deployment's clock and
#: about nobody, which is the test this allow-list applies.
LOG_KEYS: frozenset[str] = frozenset(
    {
        "purpose",
        "content_type",
        "size_bytes",
        "idempotency_key",
        "sha256",
        "file",
        "version",
        "before",
    }
)

#: The largest object a caller may DECLARE at upload time. Five gigabytes,
#: which is S3's own single-PUT ceiling — above it an upload has to be multipart,
#: which is a different presign contract and a different rung.
#:
#: **What this does and does not buy, stated because the gap is real.** It
#: refuses a declared size the platform will not serve. It CANNOT refuse the
#: actual bytes: a presigned PUT signs a method, a key and an expiry, and there
#: is no size in that signature (a browser POST policy can carry one; this design
#: does not use one). So the honest enforcement is downstream and it is the
#: meter: `record_stored` records and meters what the object store handed back
#: when we streamed the object, so an uploader who declares a kilobyte and sends
#: a gigabyte is billed for a gigabyte. Metering counts and never refuses (the
#: quota-counting ruling), which is exactly why the counting has to be honest.
#:
#: A constant rather than a setting, and it is now the only one of the three
#: numbers this app publishes that is: the two presign TTLs moved to
#: `FILES_DOWNLOAD_URL_TTL`/`FILES_UPLOAD_URL_TTL` and deliberately left
#: this one alone. The TTLs are an OPERATOR's dial — how long a credential lives
#: in somebody's clipboard, per environment. This is S3's own single-PUT ceiling,
#: and a deployment that raised it would be promising an upload path that does not
#: exist here (multipart is a different presign contract and a different rung),
#: so the honest form is a constant with the ceiling's reason beside it.
MAX_DECLARED_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class UploadTicket:
    """Everything a caller needs to put one version's bytes somewhere.

    A small typed result rather than a model, because what `create_file` and
    `add_version` produce genuinely is three things: the document, the version
    allocated inside it, and a URL that exists only in this answer. The URL is
    not a column and must never become one — it is a signature with an expiry,
    and a signature at rest is a credential at rest.

    **The declared blind spot this shape carries, and what was decided about it.**
    `core.service._object_of` reads the object an audit row names off the
    service's return value, and it recognises a model — so the `AuditEntry` for
    `create_file` and `add_version` records the action, the actor, the input and
    the outcome, and names no object in `object_type`/`object_id`. The app's answer
    where the question actually bites, on the issuance audit, is settled: **the
    rows an act was about travel in `input`**, because `redact` renders a model
    argument as `<label>:<pk>` and never as a copy of the row (see `LOG_KEYS`).
    That works for `issue_download_url` and `archive_file`, whose subjects are
    arguments. It cannot work here, where the subject is created by the call — so
    these two rows still answer "who filed something, and when" and not "which
    document", and that is the residual. Closing it means teaching
    `core.service._object_of` to read a declared attribute off a non-model result,
    which is `apps/core`'s decision and not this app's to take.

    **The upload URL is a wire contract with two required headers.** The PUT must
    send the `Content-Type` this ticket was minted for and `If-None-Match: *` —
    both are signed (`storage.presign_put`), so omitting either is a signature
    mismatch rather than a lenient upload. The door that hands this to a human or
    an agent is where that sentence has to arrive.
    """

    file: StoredFile
    version: FileVersion
    upload_url: str
    #: How long the URL above is good for, in seconds. Carried on the ticket
    #: rather than left for a door to look up, so that the number a caller is
    #: told is read from the same call that signed the URL — a door that asked
    #: the setting a second time would be free to disagree with the signature.
    expires_in: int


@dataclass(frozen=True)
class DownloadTicket:
    """A link to one version's bytes, and the version it is a link TO.

    The same reasoning `UploadTicket` gives, in the read direction: the URL exists
    only in this answer and must never become a column, because a signature at rest
    is a credential at rest.

    **The version travels with the link.** A door could work it out — it resolved
    the version a moment earlier — but then the door would be free to report one
    version while the signature covered another, and the two doors would be free to
    disagree about which. What is on the wire is what was signed.
    """

    file: StoredFile
    version: FileVersion
    download_url: str
    expires_in: int


def _the_hat(actor: Actor) -> Organization:
    """The acting organization, or a refusal. **ADR core-20's placement law.**

    A row written with no organization is invisible to every read in the product
    — `visible_to(None)` returns nothing and there is no superuser exemption —
    so defaulting to the root would be worse than refusing: the document would
    exist, belong to the whole tenant, and read as one branch's.

    It RETURNS the hat rather than asserting about it, because a checker cannot
    narrow `actor.org` across a function boundary (django-conventions' own
    gotcha) and a caller holding the value it was refused for is a caller that
    cannot forget to use it.
    """
    if actor.org is None:
        raise Invalid(
            {
                "organization": [
                    "This request resolved no acting organization, so there is no part of "
                    "the tenant to file this document in. Documents belong to the branch "
                    "that filed them; one at the root would be everybody's."
                ]
            }
        )
    return actor.org


def _check_declared_size(size_bytes: int) -> None:
    """The size policy, over the number a client declared. See `MAX_DECLARED_UPLOAD_BYTES`."""
    if size_bytes < 0:
        raise Invalid({"size_bytes": ["An object cannot be a negative number of bytes."]})
    if size_bytes > MAX_DECLARED_UPLOAD_BYTES:
        raise Invalid(
            {
                "size_bytes": [
                    f"{size_bytes} bytes is above the {MAX_DECLARED_UPLOAD_BYTES}-byte ceiling "
                    f"a single upload may declare. Anything larger has to arrive multipart, "
                    f"which is a different upload contract than the one this door offers."
                ]
            }
        )


def _refuse_an_archived_document(file: StoredFile) -> None:
    """Nothing new goes into a document somebody has taken out of the working set.

    Archive is soft — the row stays, the versions stay and the objects stay
    in the bucket until purge lands — but it means the document is out of
    everybody's list, so a version added to one would be bytes filed into a place
    no reader looks. `Conflict` rather than `NotFound`: the caller resolved this
    document through a door that could see it, so telling them the truth about
    its state costs nothing and hiding it would produce a 404 for a row they were
    just handed.
    """
    if file.archived_at is not None:
        raise Conflict(
            "This document was archived, so it takes no new versions. Bytes added to an "
            "archived document would be filed where nobody lists them."
        )


def _next_version(
    *, file: StoredFile, org: Organization, content_type: str, uploaded_by_id: Any
) -> FileVersion:
    """Allocate the next ordinal for this document, under a lock.

    `select_for_update` on the DOCUMENT and not on the versions: the thing being
    serialised is "what is the next number", and the row that answers it is the
    parent every concurrent caller has in common. Two concurrent replaces
    therefore get n+1 and n+2 rather than one number twice — and the unique
    constraint on `(file, version)` is the database's own second opinion, which
    is what makes this a lock for throughput rather than a lock for correctness.

    **The ordinal comes off the versions and never off `current_version`.**
    `current_version` is what a reader gets when they name nothing, it is 0 until
    the first finalize, and it never moves for a version that is still `PENDING`.
    Allocating from it would hand version 1's number out again to every upload
    that arrived before the first one landed.

    **Both reads are scoped, and the second one's visibility root is the
    DOCUMENT'S organization rather than the actor's** (house rules 8 and 24).
    That is not a formality here: every version of a document lands at the
    document's own node (`derive_org_from`), so reading them under that node is
    exact — while reading them under a NARROWER acting hat could hide a version
    from the maximum and hand the same ordinal out twice, which the unique
    constraint would then turn into a failed upload for somebody. The lock read
    above it uses the caller's hat, which is the boundary that belongs to the
    caller: `org` is the hat the door resolved, and the caller has already
    established it may name this document.
    """
    locked = (
        StoredFile.objects.for_tenant(file.tenant)
        .visible_to(org)
        .select_for_update()
        .get(pk=file.pk)
    )
    highest = (
        FileVersion.objects.for_tenant(locked.tenant)
        .visible_to(locked.organization)
        .filter(file=locked)
        .aggregate(top=models.Max("version"))["top"]
    )
    ordinal = (highest or 0) + 1
    version = FileVersion(
        tenant=locked.tenant,
        # The version lands where its DOCUMENT lives, never where the uploader's
        # hat points; `derive_org_from = "file"` makes the landing gate refuse a
        # disagreement, and passing the file's own organization is what agreeing
        # with it looks like.
        organization=locked.organization,
        file=locked,
        version=ordinal,
        key=storage.version_key(tenant=locked.tenant, file_pk=locked.pk, version=ordinal),
        content_type=content_type,
        # `uploaded_by_id` and not `uploaded_by=`: `Actor.user` is typed
        # `AbstractBaseUser | None` because `core` may not name the concrete
        # `accounts.User` (house rule 1 and the layer contract), and the id is
        # the field the column actually holds.
        uploaded_by_id=uploaded_by_id,
    )
    with as_invalid():
        version.full_clean()
    version.save()
    return version


def _promote_if_higher(*, file: StoredFile, version: FileVersion) -> None:
    """Move `current_version` up to this version, or leave it alone.

    **The other half of the allocation lock.**

    Which version a reader gets when they name none, and it moves **only
    upward**. Two versions finalizing out of order converge on the highest
    STORED one rather than fighting over the column, and a v2 that lands after
    v3 does not silently demote a document — the reader who asks for "the
    current one" would otherwise get older bytes than they got a minute ago,
    with nothing anywhere saying why.

    Its own function rather than three lines inside `record_stored` because it
    is its own decision with its own argument: `record_stored` is about what was
    measured, and this is about what a reader is shown. The caller holds the
    document under `select_for_update`, which is what makes the comparison and
    the write one atom.
    """
    if version.version > file.current_version:
        file.current_version = version.version
        file.save(update_fields=["current_version", "updated_at"])


def _uploader_id(actor: Actor) -> Any:
    """The user a document is filed under, or a refusal. **A file has an uploader.**

    `uploaded_by` is `PROTECT` on both models because "who filed this" has to
    stay answerable for as long as the document exists — so a caller with no
    person behind it (a machine token with no user) cannot file one. That is a
    real gap and it is named rather than papered over: the day a product wants
    an agent to file documents in its own right, the column becomes nullable and
    the audit row is what says who acted, which is a schema decision and an ADR.
    """
    if actor.user is None:
        raise Invalid(
            {
                "uploaded_by": [
                    "This call resolved no person, and a document records who filed it. A "
                    "credential with no user behind it cannot file one."
                ]
            }
        )
    return actor.user.pk


def _upload_url_for(*, tenant: Tenant, version: FileVersion) -> str:
    """**The one place an upload URL is minted.** A `STORED` version gets none.

    ADR files-2: an upload presign is issued only for a `PENDING` version. This
    is the fence and it is service-side, so it stands on a backend that honours
    no conditional write at all; the `If-None-Match: *` belt that
    `storage.presign_put` carries is the other half, and it closes the window
    between the object landing and the row learning about it that this check
    cannot see.

    **Why one function rather than the check written twice.** Both minting sites
    today — `create_file` and `add_version` — allocate a fresh `PENDING` version
    a line earlier, so the refusal below can never fire from either of them, and
    a check that cannot fire is a check that rots. It exists as a seam for the
    caller that WILL be able to reach a stored version: a re-issue door, which was
    deliberately not opened (ADR files-2's door list has no re-issue route — an
    upload URL is minted once, with the version, and a caller who lost it adds a
    version rather than being handed a second write credential for the same key).
    Every presign path routes through here rather than calling
    `storage.presign_put`, which is what the census-shaped test (criterion 3e)
    holds every path to.

    `Conflict` rather than `NotFound`: the caller reached this version through a
    door that could see it, so the honest answer is what state it is in. A
    version whose bytes are already stored is not a thing to upload to; it is a
    thing to add a version beside.
    """
    if version.status != FileVersion.Status.PENDING:
        raise Conflict(
            "This version's bytes are already stored, so there is nothing to upload to it. "
            "An object is written once and read for as long as anything quotes its digest; "
            "replacing a document means adding a version beside this one."
        )
    return storage.presign_put(tenant=tenant, key=version.key, content_type=version.content_type)


@service
def create_file(
    *,
    tenant: Tenant,
    actor: Actor,
    filename: str,
    content_type: str,
    size_bytes: int,
    purpose: str,
) -> UploadTicket:
    """File a new document, at version 1, and mint the URL its bytes go to.

    Two rows and a signature: the `StoredFile` that carries the identity, the
    `FileVersion(1, PENDING)` that carries the key, and a short-TTL presigned PUT
    for that key. Nothing is stored yet and the document has no current version —
    `current_version` is 0 until `record_stored` says otherwise, which is a real
    state rather than a placeholder.

    `purpose` is an open vocabulary on purpose (see `StoredFile.Purpose`): what a
    product files is the product's word, and a closed enum on a platform table
    would make every product's own label a migration.

    `size_bytes` is what the caller SAYS it is about to upload. It is checked
    against the size policy and it is never written — see
    `MAX_DECLARED_UPLOAD_BYTES` for what that does and does not buy.
    """
    require(actor, "file.create")
    hat = _the_hat(actor)
    _check_declared_size(size_bytes)
    person = _uploader_id(actor)
    file = StoredFile(
        tenant=tenant,
        # ADR core-20: the acting hat, never the root, and never a parameter.
        organization=hat,
        filename=filename,
        purpose=purpose,
        uploaded_by_id=person,
    )
    with as_invalid():
        file.full_clean()
    file.save()
    version = _next_version(file=file, org=hat, content_type=content_type, uploaded_by_id=person)
    return UploadTicket(
        file=file,
        version=version,
        upload_url=_upload_url_for(tenant=tenant, version=version),
        expires_in=storage.upload_url_ttl(),
    )


@service
def add_version(
    *,
    tenant: Tenant,
    actor: Actor,
    file: StoredFile,
    content_type: str,
    size_bytes: int,
) -> UploadTicket:
    """**Replace this document** — which is to say, add a version beside the old one.

    Version n is untouched: still readable, still presignable, still true for
    every audit row and export manifest that already quoted its digest. What
    changes is which version a reader gets when they name none, and that changes
    only when the new one finalizes.

    The document is reached through `may_be_named` before anything else happens:
    a caller who handed over an id for a document in a branch their hat does not
    cover is refused with `not_found`, because a refusal that told not-there from
    not-yours apart would confirm the document exists.
    """
    # REACH BEFORE CAPABILITY (rule 26's order, `core.services.revoke_membership`'s
    # shape). A row in a branch this hat does not cover is `not_found`, and it has
    # to answer BEFORE the wall does: a `Forbidden` about a row they cannot see
    # confirms the row exists, which is the fact the scoping was hiding. Every one
    # of these services takes a MODEL INSTANCE, so a caller who resolved one
    # elsewhere hands it straight in. The two lines were the other way round until
    # the Phase R sweep.
    if not may_be_named(actor, file):
        raise NotFound()
    require(actor, "file.replace", file)
    hat = _the_hat(actor)
    _check_declared_size(size_bytes)
    _refuse_an_archived_document(file)
    version = _next_version(
        file=file, org=hat, content_type=content_type, uploaded_by_id=_uploader_id(actor)
    )
    return UploadTicket(
        file=file,
        version=version,
        upload_url=_upload_url_for(tenant=tenant, version=version),
        expires_in=storage.upload_url_ttl(),
    )


@service
def confirm_upload(
    *,
    tenant: Tenant,
    actor: Actor,
    version: FileVersion,
    idempotency_key: str,
) -> FileVersion:
    """The client says the bytes are up. **Start the run that goes and looks.**

    This service believes nothing and writes nothing about the object: it starts
    `FinalizeUpload`, which heads the object, streams it, measures it, and only
    then does `record_stored` call anything stored. A confirm for an upload that
    never happened produces a run that fails to find an object, not a row that
    says it is there.

    **What makes a double confirm one run is structural, not the key.** The
    workflow id is `workflow_id(tenant, "files", "version", key=<version pk>)` —
    deterministic and per VERSION (house rule 18) — so a second start with the
    same id is refused by Temporal itself. That holds even when the two confirms
    come from different callers with different keys, which a stored key could not
    do; and per-version rather than per-file is what lets two versions of one
    document finalize concurrently as two runs rather than colliding as one.

    `idempotency_key` is therefore the CALLER's own label for the unit of work,
    not this service's de-duplicator. It is required (a blank one is a caller who
    has not thought about their own retries), it rides onto the audit row and the
    log line, and this door is where it becomes the `Idempotency-Key` header's
    value.

    An already-`STORED` version returns quietly and starts nothing: the question
    it was asked has already been answered, by evidence.
    """
    # REACH BEFORE CAPABILITY (rule 26's order, `core.services.revoke_membership`'s
    # shape). A row in a branch this hat does not cover is `not_found`, and it has
    # to answer BEFORE the wall does: a `Forbidden` about a row they cannot see
    # confirms the row exists, which is the fact the scoping was hiding. Every one
    # of these services takes a MODEL INSTANCE, so a caller who resolved one
    # elsewhere hands it straight in. The two lines were the other way round until
    # the Phase R sweep.
    if not may_be_named(actor, version):
        raise NotFound()
    require(actor, "file.replace", version.file)
    # Refused here rather than an hour later, inside the run: the hat this
    # resolves is what rides on the workflow's headers, and it is what the meter
    # attributes the bytes to. A run started with no hat is a run whose finalize
    # is going to fail at `record_usage` with nobody watching.
    hat = _the_hat(actor)
    if not idempotency_key.strip():
        raise Invalid(
            {
                "idempotency_key": [
                    "Confirming an upload needs a key naming the unit of work it is for. A "
                    "confirm with no key cannot be retried safely by whoever sent it."
                ]
            }
        )
    if version.status == FileVersion.Status.STORED:
        log.info(
            "files.version.already_stored",
            version_id=str(version.pk),
            idempotency_key=idempotency_key,
        )
        return version
    # Registered on this transaction's commit: a confirm that rolls back starts
    # nothing. The hat rides along, so the activity that runs a minute later
    # reads — and meters — as the branch that asked rather than as the whole
    # tenant.
    start_workflow_on_commit(
        workflow=FINALIZE_WORKFLOW,
        arg=FinalizeUpload(version_id=str(version.pk)),
        tenant=tenant,
        user=actor.user,
        org=hat,
        id=workflow_id(tenant=tenant, app="files", noun="version", key=str(version.pk)),
    )
    return version


@service
def record_stored(
    *,
    tenant: Tenant,
    actor: Actor,
    # reach: the row is resolved by this platform's own workflow, from the id it
    # was started with, and no client ever names it — there is no door to this
    # service at all (the absence of a `# door:` line here is because the
    # activity IS its door). `may_be_named` answers "could this actor have
    # reached this row through a door", and asking it here would let a hat that
    # moved between `confirm_upload` and the finalize refuse a legitimate
    # finalize — leaving an object in the bucket that no row admits to holding,
    # which is the exact failure the measure-then-record order exists to prevent.
    version: FileVersion,
    sha256: str,
    size_bytes: int,
) -> FileVersion:
    """Write down what we MEASURED. **The status, the digest, the meter, the event.**

    One transaction, and everything in it or nothing: the version flips
    `PENDING → STORED` carrying the digest and size the store handed back, the
    document's `current_version` advances **only upward**, the tenant is metered
    `files.storage.bytes` for the verified byte count, and `files.file.stored`
    goes out. A finalize that rolls back leaves no status, no meter entry, no
    outbox row and no run of anything.

    **Idempotent through the ledger, deliberately, rather than through a guard
    here.** Temporal will retry this activity — that is what an activity is —
    and the retry hands the same version and the same measurement. The meter's
    `idempotency_key` is derived from the version's primary key and the meter
    name, so `usage.record_usage` recognises the replay and returns the first
    row **quietly, inside this transaction** (ADR usage-1's ratified semantics);
    one entry, however many times the activity runs. A retry that arrives with a
    DIFFERENT quantity — an object overwritten between attempts — is refused by
    the ledger as a `Conflict`, and this transaction rolls back rather than
    writing a digest the ledger disagrees with.

    There is deliberately **no second opinion here** about that disagreement: a
    predicate saying the same thing differently would be a place for the two to
    disagree, which is `apps/files/policies.py`'s argument about `can_read`.

    **The event fires once even though the write is idempotent.** `transitioned`
    is read before anything is written, so a replay re-asserts the row, re-asks
    the ledger, and says nothing — a subscriber that received two `stored`
    notifications for one object would have to de-duplicate a fact that only
    happened once. Promotion is `_promote_if_higher`'s, which holds the other
    half.

    # authz: the object is already in the store, put there through a URL a door
    # authorized when it minted it (`file.create`/`file.replace`). This service
    # records what the platform measured about bytes that already exist; a
    # permission that could refuse the RECORDING would leave a bucket holding
    # somebody's document that no row admits to, which is worse than any write it
    # could have prevented. The same shape, and the same reasoning,
    # `usage.record_usage` carries about metering an act already authorized.
    """
    hat = _the_hat(actor)
    if not sha256.strip():
        raise Invalid(
            {"sha256": ["A stored version records the digest of the bytes we hold; this is empty."]}
        )
    if size_bytes < 0:
        raise Invalid({"size_bytes": ["An object cannot be a negative number of bytes."]})

    with transaction.atomic():
        # Both rows locked, parent first, so the ordinal comparison below and the
        # promotion it decides cannot interleave with another version finalizing.
        #
        # **Both halves of the read** (house rules 8 and 24), under the RUN'S OWN
        # hat: the activity restored it from the workflow's headers, and it is
        # the same hat `_the_version` already read this row under a moment ago —
        # so this adds no failure mode the activity has not already met, and it
        # keeps the finalize inside the same boundary every other read in the
        # product sits in.
        file = (
            StoredFile.objects.for_tenant(tenant)
            .visible_to(hat)
            .select_for_update()
            .get(pk=version.file_id)
        )
        fresh = (
            FileVersion.objects.for_tenant(tenant)
            .visible_to(hat)
            .select_for_update()
            .get(pk=version.pk)
        )
        transitioned = fresh.status != FileVersion.Status.STORED

        fresh.status = FileVersion.Status.STORED
        fresh.sha256 = sha256
        fresh.size_bytes = size_bytes
        with as_invalid():
            fresh.full_clean()
        fresh.save(update_fields=["status", "sha256", "size_bytes", "updated_at"])

        _promote_if_higher(file=file, version=fresh)

        record_usage(
            tenant=tenant,
            actor=actor,
            meter=STORAGE_BYTES,
            # A `Decimal` in the meter's own unit, and the unit is bytes: the
            # ledger rounds nothing, so a dashboard that wants megabytes divides
            # and the record stays exact.
            quantity=Decimal(size_bytes),
            ref=fresh,
            # ADR files-2's shape, verbatim: the source row's primary key and the
            # meter name. The pk is what makes it one unit of work; the meter
            # name is what keeps a second meter over the same row from colliding
            # with this one the day storage is counted two ways.
            idempotency_key=f"{fresh.pk}:{STORAGE_BYTES}",
        )

        if transitioned:
            emit(
                name=FILE_STORED,
                tenant=tenant,
                payload=FileStoredOut(
                    **StoredFileOut.model_validate(file).model_dump(),
                    version=FileVersionOut.model_validate(fresh),
                ).model_dump(mode="json"),
                actor=actor,
            )
    return fresh


@service
def issue_download_url(
    *,
    tenant: Tenant,
    actor: Actor,
    file: StoredFile,
    version: FileVersion,
) -> DownloadTicket:
    """Sign a short-lived link to ONE version's bytes. **The read that is a write.**

    It writes no business row and it is a `@service` anyway, because **the write
    is the `AuditEntry`** (ADR files-2 § "Audit semantics", files-1's audit-on-
    access line kept): handing somebody a credential for a document is an act, and
    an act nobody recorded is an act nobody can answer for. `@service` is what
    makes a read auditable here, and it is the only mechanism in this repository
    that does.

    **Issuance is what we witness; use is not first-party observable.** The GET
    goes to the object store, not to us, so no row here can say the bytes were
    fetched. The honest claim is "a link to this version was issued, to this
    actor, under this hat, at this time" — and because the default TTL is five
    minutes and a UI that needs the bytes again re-issues, the trail approximates
    use at five-minute resolution. That is the best a design with no byte in
    transit can do, and it is stated rather than quietly upgraded.

    **The version is resolved before this is called, and that is deliberate.**
    `selectors.downloadable_version` turns "the current one" or "version 2" into a
    row, refusing `not_found` for a version that is missing, still `PENDING`, or in
    a branch this hat cannot see. Taking the row rather than the ordinal is what
    makes the audit unambiguous: `input` names the exact `FileVersion` that was
    signed for, whether or not the caller said which one they meant.

    `file.read` and not a `file.download` action of its own: issuing the link IS
    the read (`policies.py` says why at length — a reader who may see the metadata
    and not the bytes is a reader who has been told the document exists).

    **An archived document still signs.** Archiving takes a document out of
    everybody's working set; it does not retract the versions somebody already
    cited, and the objects are in the bucket regardless. Refusing here would make
    "archived" read like "deleted" to a caller while the liability was unchanged,
    which is the one thing `StoredFile.lifecycle` exists to keep visible.
    """
    # REACH BEFORE CAPABILITY (rule 26's order, `core.services.revoke_membership`'s
    # shape). A row in a branch this hat does not cover is `not_found`, and it has
    # to answer BEFORE the wall does: a `Forbidden` about a row they cannot see
    # confirms the row exists, which is the fact the scoping was hiding. Every one
    # of these services takes a MODEL INSTANCE, so a caller who resolved one
    # elsewhere hands it straight in. The two lines were the other way round until
    # the Phase R sweep.
    if not may_be_named(actor, file):
        raise NotFound()
    require(actor, "file.read", file)
    if version.file_id != file.pk:
        # A version and a document that do not belong together can only arrive
        # from a caller that resolved them separately. `not_found` rather than a
        # complaint about the pairing: telling the two apart would confirm that
        # the version exists somewhere else.
        raise NotFound()
    ttl = storage.download_url_ttl()
    return DownloadTicket(
        file=file,
        version=version,
        download_url=storage.presign_get(tenant=tenant, key=version.key, expires_in=ttl),
        expires_in=ttl,
    )


@service
def archive_file(*, tenant: Tenant, actor: Actor, file: StoredFile) -> StoredFile:
    """Take a document out of the working set. **Soft, and the objects stay.**

    `archived_at` is set and nothing else happens: every version stays readable by
    id, stays presignable through `issue_download_url`, and **the objects stay in
    the bucket** until purge lands (ADR files-2 § exclusions; `StoredFile.lifecycle`
    carries that residual with its dated trigger). What changes is that the
    document leaves every list, and that nothing new can be filed into it —
    `_refuse_an_archived_document` is the fence, and it is why `add_version` on an
    archived document is a `conflict` rather than a silent new version.

    **Archiving takes a role**, which filing and replacing do not. It is the
    nearest thing to a delete this app has and it is not one: it makes a tenant's
    own record less complete without making the liability smaller, which is an
    administrative decision rather than an ordinary one (`policies.py`).

    **Archiving twice is not an error and not a second event.** The row is already
    where the caller wants it, so this returns quietly and emits nothing —
    a retried call must not put a second `files.file.archived` on the spine, and a
    caller cannot tell whether their first attempt or their second was the one
    that landed anyway.

    The `emit` is inside the transaction, so an archive that rolled
    back said nothing.
    """
    # REACH BEFORE CAPABILITY (rule 26's order, `core.services.revoke_membership`'s
    # shape). A row in a branch this hat does not cover is `not_found`, and it has
    # to answer BEFORE the wall does: a `Forbidden` about a row they cannot see
    # confirms the row exists, which is the fact the scoping was hiding. Every one
    # of these services takes a MODEL INSTANCE, so a caller who resolved one
    # elsewhere hands it straight in. The two lines were the other way round until
    # the Phase R sweep.
    if not may_be_named(actor, file):
        raise NotFound()
    require(actor, "file.archive", file)
    if file.archived_at is not None:
        log.info("files.file.already_archived", file_id=str(file.pk))
        return file
    with transaction.atomic():
        fresh = (
            StoredFile.objects.for_tenant(tenant)
            .visible_to(actor)
            .select_for_update()
            .get(pk=file.pk)
        )
        if fresh.archived_at is not None:
            # Somebody else archived it between the read above and this lock. The
            # same quiet answer, for the same reason.
            return fresh
        fresh.archived_at = timezone.now()
        with as_invalid():
            fresh.full_clean()
        fresh.save(update_fields=["archived_at", "updated_at"])
        emit(
            name=FILE_ARCHIVED,
            tenant=tenant,
            payload=StoredFileOut.model_validate(fresh).model_dump(mode="json"),
            actor=actor,
        )
    return fresh


# door: the document-GENERATION seam, and it is deliberately not a door at all.
# A client that could hand this platform bytes to store on its behalf would be
# uploading through Django, which is the one thing this whole app is shaped to
# prevent — the upload door is `create_file` plus a presigned PUT, and it is the
# only one there should ever be. The caller population is activities that rendered
# the bytes themselves, and an activity IS a door for house rule 42's purposes.
# `apps/exports`' archive builder was the expected first caller and was pointed
# at `store_stream` instead (`apps/exports/activities.py:76` imports it, `:242`
# calls it), because an archive is built into a spooled file — so this half of the
# seam has no production caller yet and the valve stands on its own reasoning
# rather than on a promise about who will arrive.
@service
def store_bytes(
    *,
    tenant: Tenant,
    actor: Actor,
    filename: str,
    content_type: str,
    content: bytes,
    purpose: str,
    file: StoredFile | None = None,
) -> FileVersion:
    """Store bytes the PLATFORM rendered. **One call, and it comes back measured.**

    `file=None` files a new document at version 1; `file=` adds a version to an
    existing one. Either way the key, the digest, the size, the meter and the
    event are handled inside, and what comes back is the `FileVersion` — with
    `key`, `sha256` and `size_bytes` on it, which is what a caller recording an
    artifact reference needs.

    **`actor` MUST CARRY A PERSON — `actor.user` set — and the house-shaped
    activity actor does not.** A document records who filed it (`uploaded_by`,
    non-null and `PROTECT` on both models), so `_uploader_id` refuses an actor with
    no user behind it, and `system_actor(tenant, org)` — which
    `django-conventions` §7 shows as an activity's own actor, and which six of the
    seven `activities.py` in this tree pass — has none. The refusal is an `invalid`
    naming `uploaded_by`, at runtime, and it is the first thing a builder writing
    against this seam meets.

    An activity storing bytes on somebody's behalf therefore restores that person
    off the workflow headers and passes them HERE, while keeping `system_actor` for
    its own rows: the `_actor_for` / `_person_for` split in
    `apps/exports/activities.py` is the worked shape, with the argument for why the
    pair is honest in its own docstrings.

    **It measures rather than counts what it sent.** The bytes go up through
    `storage.put_bytes` and are then streamed back down through
    `storage.sha256_of` before anything is recorded. That is one extra read of an
    object we just wrote, deliberately: it makes the generation path and the
    upload path record their digests through the SAME instrument, so
    "the recorded digest is what the store holds" is one property with one proof
    rather than two paths a reviewer has to compare. A store that silently
    truncated or transcoded would be caught here rather than by whoever verifies
    the archive months later.

    **The renderer stays product work.** What a PDF engine or a paper template
    produces is the product's; the platform's half is that rendered bytes land
    scoped, digested, audited, versioned and metered.

    **Two declared prices.** (1) The PUT and the read-back happen inside this
    service's transaction — `@service` opens one — so a slow object store holds a
    database transaction for the length of an upload. That is acceptable here and
    nowhere else: every caller is an activity on a worker thread, never a
    request, and the row is meaningless without the object, so failing together
    is the behaviour we want. (2) If the PUT succeeds and the transaction then
    rolls back, an object is left at a key no row names. It is not lost:
    `storage.delete_prefix` reaches it with the rest of the tenant's objects, and
    it is at a version ordinal the allocator will never re-issue, so nothing will
    ever collide with it. It is dead space, and it is named here rather than
    discovered.
    """
    person = _uploader_id(actor)
    if file is None:
        require(actor, "file.create")
        hat = _the_hat(actor)
        document = StoredFile(
            tenant=tenant,
            organization=hat,
            filename=filename,
            purpose=purpose,
            uploaded_by_id=person,
        )
        with as_invalid():
            document.full_clean()
        document.save()
    else:
        # REACH BEFORE CAPABILITY (rule 26's order, `core.services.revoke_membership`'s
        # shape). A row in a branch this hat does not cover is `not_found`, and it has
        # to answer BEFORE the wall does: a `Forbidden` about a row they cannot see
        # confirms the row exists, which is the fact the scoping was hiding. Every one
        # of these services takes a MODEL INSTANCE, so a caller who resolved one
        # elsewhere hands it straight in. The two lines were the other way round until
        # the Phase R sweep.
        if not may_be_named(actor, file):
            raise NotFound()
        require(actor, "file.replace", file)
        hat = _the_hat(actor)
        _refuse_an_archived_document(file)
        document = file

    version = _next_version(
        file=document, org=hat, content_type=content_type, uploaded_by_id=person
    )
    storage.put_bytes(tenant=tenant, key=version.key, content=content, content_type=content_type)
    measured = storage.sha256_of(tenant=tenant, key=version.key)
    return record_stored(
        tenant=tenant,
        actor=actor,
        version=version,
        sha256=measured.sha256,
        size_bytes=measured.size_bytes,
    )


# door: the streaming half of the same generation seam, and no more a door than
# the one above — see `store_bytes`'s valve for the whole argument. It is here
# because an archive is built into a spooled file and `store_bytes` would make a
# worker hold a whole tenant's export in memory to call it; the caller is the
# same population (activities that rendered the bytes themselves) and the
# refusals are the same refusals.
@service
def store_stream(
    *,
    tenant: Tenant,
    actor: Actor,
    filename: str,
    content_type: str,
    body: storage.Rewindable,
    purpose: str,
    file: StoredFile | None = None,
) -> FileVersion:
    """Store a body the PLATFORM built into a file. **`store_bytes`, without the RAM.**

    Same contract as `store_bytes` in every respect a caller can observe — same
    two shapes (`file=None` files a new document at version 1, `file=` adds one),
    same placement law, same authorization, same meter, same event, same
    `FileVersion` back with `key`, `sha256` and `size_bytes` on it — and **the same
    requirement that `actor` carries a person**. `actor.user` must be set, so an
    activity's house-shaped `system_actor(tenant, org)` is refused here exactly as
    it is by `store_bytes`, for the same reason (`uploaded_by` is non-null and
    `PROTECT` on both models). See `store_bytes` for the whole argument, and
    `apps/exports/activities.py` — this seam's one production caller — for the
    `_actor_for`/`_person_for` split that satisfies it.

    What differs is where the bytes are while it runs: `store_bytes` is handed a
    `bytes` and this is handed something to READ, so an export archive as large as
    the tenant goes to the store a chunk at a time and never sits in a worker's
    memory.

    **Where the numbers come from, because the two seams differ here and the
    difference is the whole rung.** `store_bytes` puts the object and then
    streams it back down to measure it (`storage.sha256_of`) — one instrument for
    the generation path and the upload path, and worth the extra read for a
    rendered document. This one measures the pass it SENT
    (`storage.store_stream`), because a read-back doubles the network for the one
    body that could not afford the first trip. The honesty is kept by
    `storage.store_stream`'s belt: the store's own `HEAD` has to agree about the
    size, or nothing is recorded at all.

    **The body must be rewindable** — a `SpooledTemporaryFile`, which is what an
    archive builder has — and the seam refuses one that is not rather than
    spooling it behind the caller's back (`storage.store_stream`).

    **The same two declared prices as `store_bytes`**, unchanged: the upload
    happens inside this service's transaction, which is acceptable because every
    caller is an activity on a worker thread and the row is meaningless without
    the object; and a rollback after a successful PUT leaves an object at a key
    no row names, reachable by `storage.delete_prefix` and at an ordinal the
    allocator will never re-issue.
    """
    person = _uploader_id(actor)
    if file is None:
        require(actor, "file.create")
        hat = _the_hat(actor)
        document = StoredFile(
            tenant=tenant,
            organization=hat,
            filename=filename,
            purpose=purpose,
            uploaded_by_id=person,
        )
        with as_invalid():
            document.full_clean()
        document.save()
    else:
        # REACH BEFORE CAPABILITY (rule 26's order, `core.services.revoke_membership`'s
        # shape). A row in a branch this hat does not cover is `not_found`, and it has
        # to answer BEFORE the wall does: a `Forbidden` about a row they cannot see
        # confirms the row exists, which is the fact the scoping was hiding. Every one
        # of these services takes a MODEL INSTANCE, so a caller who resolved one
        # elsewhere hands it straight in. The two lines were the other way round until
        # the Phase R sweep.
        if not may_be_named(actor, file):
            raise NotFound()
        require(actor, "file.replace", file)
        hat = _the_hat(actor)
        _refuse_an_archived_document(file)
        document = file

    version = _next_version(
        file=document, org=hat, content_type=content_type, uploaded_by_id=person
    )
    measured = storage.store_stream(
        tenant=tenant, key=version.key, body=body, content_type=content_type
    )
    return record_stored(
        tenant=tenant,
        actor=actor,
        version=version,
        sha256=measured.sha256,
        size_bytes=measured.size_bytes,
    )


@service
def purge_pending_versions(*, before: datetime, tenant: Tenant | None) -> SweepOutcome:
    """Take the uploads that never happened, and archive what they leave empty.

    **The disposal half of a status that only ever had a state.** A version is
    born `PENDING` and there is deliberately no `FAILED` for it to move to —
    "nothing arrived" is the absence of a transition rather than a state of its
    own — which was honest and, until this service existed, permanent. A
    field test drove a confirm for an upload that never happened and recorded the
    gap in as many words: the row it left "has no expirer until this sweep,
    confirmed as state not disposal". This is the expirer, and it deletes the row
    rather than annotating it, because a third state on a two-state model would
    have to be undone by hand the moment a bucket came back.

    **Then the document**, which is a decision of its own with its own argument
    and therefore a function of its own: `_archive_the_emptied` below, the same
    split `_promote_if_higher` makes for the same reason. This one is about which
    rows the clock takes; that one is about what a reader is left looking at.

    **`tenant` is declared, is always `None`, and a non-`None` one REFUSES.** It
    is declared because that is what makes the call audited — `@service` writes an
    `AuditEntry` for every service that declares a `tenant` (ADR core-8), and
    `None` is that ADR's named population: the deployment's own actions, the ones
    a compliance trail exists for. A sweep that deleted rows across every customer
    and left no record of having run cannot be told from one that never fired. It
    refuses rather than ignoring, because a declared parameter that is silently
    dropped is a signature a reader can mistake for a scoped purge (a risk at the
    sibling seam in `apps/exports`).

    **Nobody is acting.** This service resolves no actor of its own: it is scoped
    by the clock, it names no tenant, it deletes rows rather than returning any,
    and the only values that leave are two counts — so there is nobody whose reach
    could be exceeded. Where an actor IS needed, one document at a time, is the
    helper below, and it says where it gets one.

    **Idempotent**, because Temporal runs an activity at least once: it selects by
    age and status, so a second run inside the same window finds nothing.

    DECLARED RESIDUE, because deleting a row frees the ordinal it held. The
    allocator takes the next number off the versions that exist
    (`_next_version`), so a swept `v2` can be issued again — and if a hijacked or
    very slow PUT did land an object at that key before the sweep, the re-issued
    upload is refused by the conditional-write belt (`If-None-Match: *`, always
    inside the signature) rather than overwriting it. A refused upload, never a
    silent overwrite: the fence this app is built on holds, and the cost is one
    document that will not take a new version at that ordinal until the object
    goes. It goes when object purge does (`StoredFile.lifecycle`).
    """
    if tenant is not None:
        raise Invalid(
            {
                "tenant": [
                    "This sweep is deployment-wide: it selects every tenant's expired "
                    "uploads at once, because a retention window is not something one "
                    "customer has and another does not. Naming a tenant here would read "
                    "as a scoped purge and would not be one."
                ]
            }
        )
    # rule-8: the population is every tenant's abandoned uploads at once, which
    # is what a retention sweep is — there is no tenant to scope by because the
    # sweep is not acting for one, and no hat either. Nothing crosses a tenant
    # boundary: the rows are deleted rather than returned, the documents are
    # archived one at a time under their own tenant and their own hat, and only
    # two integers leave this function.
    everything_abandoned = FileVersion.objects.filter(
        status=FileVersion.Status.PENDING, created_at__lt=before
    )
    # `select_related` down to the tenant and the organization: the archive half
    # below needs both ROWS to build the document's own hat, and fetching them
    # once per query rather than once per expired version is the difference
    # between one statement and three per abandoned upload.
    expired = list(
        everything_abandoned.select_related("file", "file__tenant", "file__organization")
    )
    if not expired:
        return SweepOutcome(versions=0, documents=0)

    # The documents the sweep touched, deduplicated: two abandoned versions of
    # one document are one document to consider, and asking the same question
    # twice would archive it twice in the count.
    touched = {version.file_id: version.file for version in expired}

    with transaction.atomic():
        # rule-8: the second half of the same deployment-wide sweep. It deletes
        # exactly the primary keys the read above returned, so narrowing it to a
        # tenant would be narrower than the population it selected from and would
        # leave every other customer's residue behind.
        _total, by_model = FileVersion.objects.filter(
            pk__in=[version.pk for version in expired]
        ).delete()
    # The per-model count and not the total: `delete()` returns everything it
    # removed including cascades, and a number that quietly counted a child table
    # would be a report about the wrong population the day this model grows one.
    versions = int(by_model.get(FileVersion._meta.label, 0))
    documents = _archive_the_emptied(touched.values())

    log.info("files.pending.swept", versions=versions, documents=documents)
    return SweepOutcome(versions=versions, documents=documents)


def _archive_the_emptied(documents: Iterable[StoredFile]) -> int:
    """Take out of the working set every document the sweep left with nothing.

    **The half a version-only sweep would miss.** Expiring the only version of a
    document leaves a `StoredFile` with `current_version` 0, no bytes and no way
    to ever get any, sitting in somebody's list looking like a document. This is
    its own function rather than four lines inside the sweep because it is its own
    decision with its own argument — the same split `_promote_if_higher` makes:
    the sweep is about which rows the clock takes, and this is about what a reader
    is left looking at.

    **The condition is "nothing left", not "no stored version."** A document whose
    upload from yesterday expired while another one is in flight this morning
    keeps its place: archiving it would make `_refuse_an_archived_document` refuse
    the finalize that is about to arrive, and that would be a conflict about bytes
    already on the wire.

    **Through `archive_file`, never by writing the column** (house rule 10 read at
    its own level): the same soft archive a person performs at the door, with the
    same fence against new versions, the same `files.file.archived` on the spine
    and the same audit row.

    **Each document under its own hat.** `system_actor(document.tenant,
    document.organization)` — the document's OWN branch and never the root — which
    is what puts the audit row in the right tenant, the event on the right spine,
    and `may_be_named`'s answer at True for the row being written, rather than at
    a blanket exemption. Nobody clicked this, so the actor is the system; the hat
    still rides, exactly as it does for the finalize activity's own writes.

    Returns how many it archived, and a document somebody archived by hand in the
    meantime is not counted: `archive_file` already answers quietly for one, and a
    count that grew on replay is a report that lies about how much work there was.
    """
    archived = 0
    for document in documents:
        if document.archived_at is not None:
            continue
        remaining = (
            FileVersion.objects.for_tenant(document.tenant)
            .visible_to(document.organization)
            .filter(file=document)
            .exists()
        )
        if remaining:
            continue
        archive_file(
            tenant=document.tenant,
            actor=system_actor(document.tenant, document.organization),
            file=document,
        )
        archived += 1
    return archived
