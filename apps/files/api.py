"""The HTTP door onto documents: file one, replace one, find one, fetch one, archive one.

**No route in this module carries a byte.** Uploading and downloading both happen
directly between the client and the object store, on short-lived signed URLs this
app mints and audits — so what these routes hand out is a *place* and never a
*stream*. That is ADR files-2's central design, and it is why there is no
`/download/` route here of the kind `apps/exports` has: exports redirects to a
link because an export is one artifact with one link, and a document is a document
with versions, so the link names the version and the client asks for it.

Nothing here is implicit: the router restates `auth=`, both lists paginate, every
read goes through `selectors.py` (which narrows to `request.tenant` **and**
`request.org`) and every write goes through `services.py`. `request.org` is the
acting hat `TenantMiddleware` resolved from `X-Org`, and every read passes it — a
route that passed only the tenant would hand a branch the whole tenant.

The routes never say 404 either. `selectors.get_file` raises `NotFound` and
`config/api.py` is the only module that turns that into a number, so the MCP tool
over the same selector refuses identically without repeating the rule.

`document_of` and `downloadable` below are shared with `mcp.py` rather than written
twice, for the same reason `apps/exports/api.py::downloadable_export` is: the two
doors would otherwise be free to come to different opinions about when a version
is signable, and a disagreement about that is a disagreement about who may reach
somebody's bytes.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a
# `FilterSchema` parameter comes out as an unresolvable forward reference.

from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.docs import Tag, refuses
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.files.models import FileVersion, StoredFile
from apps.files.schemas import (
    ArchiveIn,
    ConfirmUploadIn,
    DownloadUrlIn,
    FileDownloadOut,
    FileFilter,
    FileIn,
    FileVersionOut,
    StoredFileOut,
    UploadTicketOut,
    VersionIn,
)
from apps.files.selectors import get_downloadable_version, get_file, get_version, list_versions
from apps.files.selectors import list_files as list_files_selector
from apps.files.services import (
    DownloadTicket,
    UploadTicket,
    add_version,
    archive_file,
    confirm_upload,
    create_file,
    issue_download_url,
)

# The path says what the resource is, not which app holds it (house rule 32).
# Here the two coincide, and the coincidence is declared in `quality/rules.yaml`
# under rule 32's `allowed_label_paths` with its reason rather than relied on:
# `apps/files` is the plural-of-its-aggregate convention working, and `a file` is
# a noun every caller already has. It is written down here as well so that
# renaming the app never silently moves a published URL.
PREFIX = "files"

# What `?ordering=` may name on the document list, and nothing else. Straight into
# `.order_by()` it would let a client sort by any column and traverse any
# relation — a full-table sort on an unindexed column at best, a read across a
# join at worst.
ORDERING = ("created_at", "updated_at", "filename")

# The same, for the version history of one document. `version` is the ordinal and
# is what a person means by "in order"; `created_at` is what they mean by "when".
VERSION_ORDERING = ("version", "created_at")

# The scope family this app's routes belong to — `files`, the ratified key from
# RUL-1 (`design-agreements.md`: files/search/usage/devices). It follows the
# DEFAULT half of the choosing pattern (django-conventions §6): the plural noun of
# the section's primary resource, because the noun does not mislead a reader who
# meets the string with no API around it. `files:read` and `files:write` say
# exactly what a token holding them is trusted with — see the documents, and put
# one in. The exception half (name the MEANING when the noun would mislead, as
# `messaging` does for comms) does not apply: there is no gap here between "may
# write a file row" and "may store bytes", because they are the same act.
#
# `files:read` covers issuing a download link even though that route is a POST,
# and that is not a leak in the derivation — it is the derivation being honest.
# Issuance WRITES an audit row, which is what makes it a write at the scope layer;
# and a token that may read a document's metadata may already learn everything the
# link's existence would tell it. See `policies.py` on why there is no separate
# `file.download` action for the same reason one layer down.
#
# The key FREEZES the day a token could name it, which is today: renaming it later
# kills every ceiling that holds it, silently, and the token goes on
# authenticating while being refused at every door. `FROZEN_FAMILIES` in
# `apps/core/api/scopes.py` is the census this is written into in the same commit.
TAGS = {
    "files": Tag(
        "Files",
        "Documents you store with us and the versions they have had. Put a "
        "document in, replace it later without losing what it used to say, and "
        "fetch any version back on a short-lived private link. The bytes never "
        "travel through this API — you upload and download straight to storage — "
        "and every link we issue is recorded against the version it was issued "
        "for.",
        plane="everyday",
        plane_note=(
            "documents you store with us and the versions they have had: put one in, replace it "
            "later without losing what it used to say, and fetch any version back on a "
            "short-lived private link. **The bytes never travel through this API** — you upload "
            "and download straight to storage on links we sign and record. Everyday rather than "
            "administrative, because filing and replacing are ordinary product work and what you "
            "can see is already narrowed to the part of the tree you are acting in. **Archiving "
            "is the one act here that takes an owner or an administrator**, because it takes a "
            "document out of everybody's working set while the stored bytes remain, and it is "
            "refused with `403 forbidden` otherwise."
        ),
    ),
}

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call these routes.
router = Router(tags=["files"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a call happens as.

    Authentication has already guaranteed the user. The tenant has not been
    guaranteed by anything: a signed-in user with no membership resolves to
    `None`, and a call with no tenant is refused rather than guessed at.

    The hat rides on the actor rather than being returned beside the tenant,
    because that is where the services read it from — `create_file` takes no
    `organization=` argument, so there is nothing for a route to pass and nothing
    for a caller to forge (ADR core-20's placement law).
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


def document_of(*, tenant: Tenant | None, org: object, file_id: UUID) -> StoredFile:
    """One document this hat may see, or `not_found` — **one lookup, both doors**.

    A one-line wrapper on the selector, and it earns its place by being the thing
    `mcp.py` imports: the two doors then cannot come to fetch a document two
    different ways, which is how a scoping fix lands on one door and not the other.

    `tenant` is allowed to be `None` and is not refused here: `for_tenant(None)`
    reads an empty table, so an unresolved tenant gets the same `not_found` a
    stranger gets rather than a different refusal that would tell the two apart. A
    route that is about to WRITE refuses earlier and louder, in `_acting`.
    """
    return get_file(tenant=tenant, file_id=file_id, org=org)


def downloadable(
    *, tenant: Tenant, actor: Actor, file_id: UUID, version: int | None
) -> DownloadTicket:
    """The signed link for one version — **one gate, both doors**.

    Four refusals in one place, all of them `not_found`: no such document
    where this hat can see; no such version; a version whose bytes have not landed;
    and a document that has never had a version finalize. A caller holding an id
    cannot tell which, which is the same answer somebody outside the tenant gets —
    a presigned URL must never be the oracle that confirms a document exists.

    It lives here rather than in each door because `mcp.py` imports it, so the two
    doors cannot come to disagree about when a version is signable — the kind of
    disagreement no value-by-value parity test would catch.
    """
    document = document_of(tenant=tenant, org=actor.org, file_id=file_id)
    row = get_downloadable_version(tenant=tenant, file=document, version=version, org=actor.org)
    return issue_download_url(tenant=tenant, actor=actor, file=document, version=row)


def _ticket(ticket: UploadTicket) -> UploadTicketOut:
    """The wire shape of an upload ticket, built once for both doors."""
    return UploadTicketOut(
        file=StoredFileOut.model_validate(ticket.file),
        version=FileVersionOut.model_validate(ticket.version),
        upload_url=ticket.upload_url,
        expires_in=ticket.expires_in,
    )


def download_body(ticket: DownloadTicket) -> FileDownloadOut:
    """The wire shape of a download ticket, built once for both doors."""
    return FileDownloadOut(
        file_id=ticket.file.pk,
        version=ticket.version.version,
        version_id=ticket.version.pk,
        download_url=ticket.download_url,
        expires_in=ticket.expires_in,
        content_type=ticket.version.content_type,
        size_bytes=ticket.version.size_bytes,
        sha256=ticket.version.sha256,
    )


# --- the documents ------------------------------------------------------------


@router.get("/", response=list[StoredFileOut], url_name="file-list")
@paginate(CursorPagination)
def list_files_route(
    request: TenantRequest,
    filters: Query[FileFilter],
    ordering: str = "-created_at",
) -> QuerySet[StoredFile]:
    """List documents

    The documents your organization has stored, newest first.

    **Archived documents are not here.** Archiving takes a document out of
    everyone's working set, and this is the working set. A document you archived is
    still readable by its id, and its versions are still fetchable.

    **Narrow** with `purpose`, which matches exactly — whatever short label you
    filed the document under — and with `filename`, which matches anywhere in the
    name, so `?filename=invoice` finds `invoice-2026-08.pdf`.

    **Sort** with `ordering`. It accepts `created_at`, `updated_at` or `filename`,
    each optionally prefixed with `-` for descending, and the default is
    `-created_at`. Any other value is refused with `400 invalid` rather than
    quietly ignored.

    **Pages** are `?cursor=` and `?limit=` (50 by default, 200 at most). The body
    is `{"items": [...], "has_more": ..., "next_cursor": ...}`: send the
    `next_cursor` you were given back as `?cursor=` for the following page, and
    stop when `has_more` is false. A cursor is opaque — never build or edit one.

    **`count` is `null` unless you send `?include_count=true`**, because a total
    costs a second pass over the matches.

    **What you can see** depends on the organization you are acting as — the
    `X-Org` header, or your default organization if you send none. You get that
    organization's documents and those of every organization beneath it. Documents
    belonging to an organization alongside yours, or above it, are not in the list.

    Each document says which version is `current_version`; `0` means nothing has
    finished uploading yet, which is a real state and not a placeholder.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or a
      filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting organization.
      Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `403 insufficient_scope` — the token authenticated and its ceiling does not
      carry `files:read`. Mint one that does.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Scoped first and only narrowed after, which is why the type widens from
    `ScopedQuerySet` to `QuerySet` here: filtering returns the plain one, and
    narrowing a queryset cannot widen its tenant.
    """
    files: QuerySet[StoredFile] = list_files_selector(tenant=request.tenant, org=request.org)
    files = filters.filter(files)
    return ordered_by(files, ordering, allowed=ORDERING, default="-created_at")


@router.post("/", response={201: UploadTicketOut}, url_name="file-create")
def create_file_route(request: TenantRequest, payload: FileIn) -> Status[UploadTicketOut]:
    """File a document

    Start a new document. Answers `201` with the document, its first version, and
    **where to PUT the bytes** — the bytes never travel through this API.

    Three steps, and the second one does not touch us at all:

    1. `POST` here. You get back `upload_url`, good for `expires_in` seconds.
    2. `PUT` your bytes to that URL with **two headers**: `Content-Type` set to
       exactly the `content_type` you sent here, and `If-None-Match: *`. Both are
       part of the signature, so leaving either out is refused by storage rather
       than accepted leniently — and the second is what stops the same link being
       replayed later over bytes that have already been finalized.
    3. `POST /files/{id}/versions/{n}/confirm` to tell us you have finished. We
       then fetch the object ourselves, measure it, and record what we measured.

    Nothing is stored until step 3 completes: until then `current_version` is `0`
    and the version's `status` is `pending`.

    `size_bytes` is what you expect to upload. We check it against the limit and
    never record it — what gets recorded is what we measure when we read the
    object back, so a declared size that turns out to be wrong changes nothing
    except that the true size is what you are metered for.

    `purpose` is your own short label — `contract`, `lab-result`, `invoice`. It is
    an open vocabulary on purpose: what you file is your word for it.

    **Where it lands** is the organization you are acting as — the `X-Org` header,
    or your default organization — and there is no field here to send instead. A
    request that resolves no organization is refused rather than filed at the top
    of your account.

    **Your credential must belong to a person.** A document records who filed it,
    for as long as it exists, so a machine token with no user behind it is refused
    with `400 invalid` naming `uploaded_by`.

    Send `Idempotency-Key` with your own opaque value and a retry of the identical
    request replays the first answer — the same document, the same version, and the
    same upload URL — instead of filing a second document.

    Refusals you can get here:

    * `400 invalid` — the declared size is above the limit, your credential
      resolved no person, or the request resolved no acting organization. Nothing
      was created.
    * `422 invalid_body` — the body carried a field this endpoint does not accept,
      or one was missing or the wrong type. `errors` names the fields.
    * `403 forbidden` — the request resolved no tenant, or you may not file
      documents in this organization.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:write`.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` header for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    ticket = create_file(
        tenant=tenant,
        actor=actor,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        purpose=payload.purpose,
    )
    return Status(201, _ticket(ticket))


@router.get("/{file_id}/", response=StoredFileOut, url_name="file-detail")
def retrieve_file(request: TenantRequest, file_id: UUID) -> StoredFile:
    """Retrieve a document

    One document, with the version a reader who names none would get.

    `current_version` is `0` while nothing has finished uploading. `archived_at` is
    `null` while the document is in the working set and a timestamp once somebody
    has archived it — an archived document is still here, still readable, and its
    versions are still fetchable; it is simply out of the lists.

    A document belonging to an organization you cannot see answers `404 not_found`,
    the same answer an id that names nothing gets.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting organization.
      Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:read`.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return document_of(tenant=request.tenant, org=request.org, file_id=file_id)


@router.post("/{file_id}/archive/", response=StoredFileOut, url_name="file-archive")
@refuses("forbidden", "insufficient_scope", "invalid_body", "not_found", "rate_limited")
def archive_file_route(request: TenantRequest, file_id: UUID, payload: ArchiveIn) -> StoredFile:
    """Archive a document

    Take a document out of everyone's working set. It disappears from the list, and
    nothing new can be added to it.

    **This is not a delete, and the difference matters.** Every version stays
    readable, every version stays fetchable on a signed link, and the stored bytes
    remain exactly where they were. What changes is that the document stops
    appearing in the list and that `POST /files/{id}/versions` on it is refused.

    **It takes administrator rights**, unlike filing and replacing, which are open
    to anybody in the account. Archiving makes your own record less complete
    without making anything smaller, so it is kept to the people who administer
    that part of the organization.

    Archiving something already archived answers `200` with the document unchanged
    and does nothing — safe to retry.

    The body is empty; send `{}`.

    Refusals you can get here:

    * `422 invalid_body` — the body carried a field this endpoint does not accept.
    * `403 forbidden` — you are not an owner or an administrator of the part of the
      organization this document belongs to, or the request resolved no tenant or
      no acting organization.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:write`.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `@refuses` narrows the derived set by exactly one code: a POST derives
    `conflict`, and this route has no conflicting state to be in — archiving an
    archived document is the quiet no-op above rather than a refusal. Documenting a
    409 here would teach a client to handle one that never comes.
    """
    actor, tenant = _acting(request)
    document = document_of(tenant=tenant, org=actor.org, file_id=file_id)
    return archive_file(tenant=tenant, actor=actor, file=document)


@router.post("/{file_id}/download-url/", response=FileDownloadOut, url_name="download_url-issue")
@refuses("forbidden", "insufficient_scope", "invalid_body", "not_found", "rate_limited")
def issue_download_url_route(
    request: TenantRequest, file_id: UUID, payload: DownloadUrlIn
) -> FileDownloadOut:
    """Get a link to a document's bytes

    Ask for a short-lived private link to one version of a document, and fetch the
    bytes from it directly.

    Send an empty body — `{}` — for the current version, or `{"version": 2}` to pin
    the link to a particular one. **A link issued for version 2 keeps serving
    version 2's bytes** after version 3 lands and becomes current: every version
    has its own object, and what an already-issued link means never changes.

    The link needs no credential of yours and works for anyone holding it until it
    expires, in `expires_in` seconds. **Treat it as the secret it is**: do not
    email it, do not put it in a URL bar somebody screenshots, do not store it.
    When it expires, storage refuses it in its own words — a `403` that is not from
    this API and does not look like one — and the remedy is to ask here again.
    There is no longer-lived link.

    The answer also carries `sha256` and `size_bytes`, which are **what we measured
    by reading the object ourselves**, never what the uploader declared. Check the
    bytes you fetched against them.

    **Every issuance is recorded** against the version it was issued for, together
    with who asked and which organization they were acting as. What we cannot
    record is whether the link was used: the fetch goes to storage, not to us. So
    the trail says a link existed, and asking again for the bytes creates a new
    entry.

    A document belonging to an organization you cannot see answers `404 not_found`
    — and so does a version that does not exist, a version whose bytes have not
    finished uploading, and a document that has never had one finish. All four are
    the same answer on purpose: a link request must never be a way of finding out
    whether somebody's document is there.

    Refusals you can get here:

    * `422 invalid_body` — the body carried a field this endpoint does not accept,
      or `version` was not a positive whole number.
    * `403 forbidden` — the request resolved no tenant or no acting organization,
      or you may not read this organization's documents.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:write`.
      Issuing a link records an entry against the document, which is what puts this
      operation on the writing side of a token's ceiling.
    * `404 not_found` — nothing has that id where you can see, or there are no
      stored bytes at the version you asked for.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `@refuses` narrows the derived set by one code: a POST derives `conflict`, and
    there is no state this route conflicts with — every "the bytes are not there"
    answer is deliberately `not_found`, so a documented 409 would be a refusal
    no caller can ever receive.
    """
    actor, tenant = _acting(request)
    return download_body(
        downloadable(tenant=tenant, actor=actor, file_id=file_id, version=payload.version)
    )


# --- the versions -------------------------------------------------------------


@router.get("/{file_id}/versions/", response=list[FileVersionOut], url_name="version-list")
@paginate(CursorPagination)
def list_versions_route(
    request: TenantRequest, file_id: UUID, ordering: str = "-version"
) -> QuerySet[FileVersion]:
    """List a document's versions

    Every version this document has had, newest first — what each one was called
    when it arrived, how big it is, its digest, and whether its bytes have landed.

    `size_bytes` and `sha256` are **what we measured** by reading the object, not
    what the uploader told us. They are `null` and empty while a version is still
    `pending`, which is the honest answer rather than a zero that reads like a
    measurement.

    Versions are never rewritten. Replacing a document adds a version beside the
    old one, so a digest you recorded stays true about the bytes it was taken from
    forever.

    **Sort** with `ordering`: `version` or `created_at`, optionally prefixed with
    `-`, default `-version`.

    **Pages** are `?cursor=` and `?limit=`, and `count` is `null` unless you send
    `?include_count=true`, exactly as on the document list.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept.
    * `403 forbidden` — the request resolved no tenant or no acting organization.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:read`.
    * `404 not_found` — nothing has that id where you can see, or a `?cursor=` you
      sent belongs to a different walk.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    document = document_of(tenant=request.tenant, org=request.org, file_id=file_id)
    versions: QuerySet[FileVersion] = list_versions(
        tenant=request.tenant, file=document, org=request.org
    )
    return ordered_by(versions, ordering, allowed=VERSION_ORDERING, default="-version")


@router.post("/{file_id}/versions/", response={201: UploadTicketOut}, url_name="version-add")
def add_version_route(
    request: TenantRequest, file_id: UUID, payload: VersionIn
) -> Status[UploadTicketOut]:
    """Replace a document

    Add a new version beside the current one, and get somewhere to PUT its bytes.

    **The old version is untouched.** It stays readable, stays fetchable on a
    signed link, and stays true for anything that already quoted its digest. What
    changes is which version a reader who names none gets — and that only changes
    once the new one has finished uploading and we have measured it.

    The three steps are the same as filing a document: `POST` here for an
    `upload_url`, `PUT` the bytes to it with `Content-Type` and `If-None-Match: *`,
    then `POST .../confirm`. Until the confirm completes, `current_version` still
    points at the old version and the new one's `status` is `pending`.

    There is no `filename` here on purpose: replacing a document does not rename
    it. A document that needs a different name is a different document.

    An **archived** document cannot be replaced — that is what archiving is for —
    and answers `409 conflict`.

    Send `Idempotency-Key` and a retry of the identical request replays the first
    answer instead of allocating a second version.

    Refusals you can get here:

    * `400 invalid` — the declared size is above the limit, your credential
      resolved no person, or the request resolved no acting organization.
    * `422 invalid_body` — the body carried a field this endpoint does not accept.
    * `403 forbidden` — the request resolved no tenant, or you may not add versions
      in this organization.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:write`.
    * `404 not_found` — nothing has that id where you can see.
    * `409 conflict` — the document is archived, so nothing new goes into it.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` header for a different request, or the first request under
      it has not finished.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    document = document_of(tenant=tenant, org=actor.org, file_id=file_id)
    ticket = add_version(
        tenant=tenant,
        actor=actor,
        file=document,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )
    return Status(201, _ticket(ticket))


@router.post(
    "/{file_id}/versions/{version}/confirm/",
    response={202: FileVersionOut},
    url_name="upload-confirm",
)
def confirm_upload_route(
    request: TenantRequest, file_id: UUID, version: int, payload: ConfirmUploadIn
) -> Status[FileVersion]:
    """Confirm an upload

    Tell us the bytes are up. Answers `202` immediately and starts the check in the
    background.

    **We take nothing on trust here.** Confirming does not mark anything stored: it
    starts a job that fetches the object from storage, streams it, and measures its
    size and its SHA-256 itself. Only then does the version become `stored`, get
    its digest, and — if it is the highest one stored — become the document's
    `current_version`. A confirm for an upload that never happened produces a job
    that finds nothing, not a version that claims to be there.

    So the version in this response is still `pending`. Poll
    `GET /files/{id}/versions/` until it says `stored`.

    `idempotency_key` is **your own name for this upload** and is required. It is
    not what stops a double confirm — confirming twice joins the check already
    running, because the job's identity comes from the version itself — it is what
    ties this call to whatever you were doing in your own system, in the record we
    keep of it.

    Confirming a version whose bytes we have already measured answers `202` and
    starts nothing. The question has already been answered, by evidence.

    Refusals you can get here:

    * `400 invalid` — `idempotency_key` was blank, or the request resolved no
      acting organization.
    * `422 invalid_body` — the body carried a field this endpoint does not accept.
    * `403 forbidden` — the request resolved no tenant, or you may not add versions
      in this organization.
    * `403 insufficient_scope` — the token's ceiling does not carry `files:write`.
    * `404 not_found` — nothing has that id where you can see, or that document has
      no version with that number.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    document = document_of(tenant=tenant, org=actor.org, file_id=file_id)
    row = get_version(tenant=tenant, file=document, version=version, org=actor.org)
    return Status(
        202,
        confirm_upload(
            tenant=tenant, actor=actor, version=row, idempotency_key=payload.idempotency_key
        ),
    )
