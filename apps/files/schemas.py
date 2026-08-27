"""The shapes this app publishes — the documents, the tickets, and the bodies a client sends.

The models and the storage seam, the services and the workflow, then
the routes and the tools — and the request schemas arrive with the routes that
read them, each inheriting `apps.core.schemas.StrictIn`, so an unknown field is a
refusal naming the field rather than a value silently dropped.

The `Out`s were written before anything sent them, because an **event** payload
is a published contract exactly as a route's response body is: `files.file.stored`
sends `FileStoredOut`, which IS a `StoredFileOut` plus the version that landed, so
a webhook subscriber and a REST client see one shape for one fact.

**No `key` on any of these schemas, deliberately.** A key is where bytes live, and
the only legitimate way to reach bytes is a presigned URL this platform minted and
audited. Publishing the key would hand every reader the one string a misconfigured
bucket policy turns into a URL, and it would tempt a client into constructing one.

**A URL, by contrast, is on two of them and is never a column.** `upload_url` and
`download_url` exist only in the answer that minted them — a signature at rest is
a credential at rest, so nothing here is `from_attributes` over a stored field.

**Nothing here carries a `Field(alias=...)`** (ADR example-3): REST renders by
field name and the MCP transport renders `structuredContent` by alias, so an alias
makes the two doors describe one row with two key sets and every value equal —
the class of finding a value-by-value test is blind to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, StrictIn, example

__all__ = [
    "ArchiveIn",
    "ConfirmUploadIn",
    "DownloadUrlIn",
    "FileDownloadOut",
    "FileFilter",
    "FileIn",
    "FilePage",
    "FileStoredOut",
    "FileVersionOut",
    "FileVersionPage",
    "StoredFileOut",
    "UploadTicketOut",
    "VersionIn",
]

#: A digest-shaped example that no secret scanner can mistake for a leak. Sixty-four
#: hex characters of two repeated symbols: `detect-secrets` measures Shannon entropy
#: over the characters, and this scores far under the limit where a realistic-looking
#: digest scores exactly what a random one does (see also `core.schemas.example`'s
#: own note about the full-gate run that taught it).
SAMPLE_DIGEST = "beadbead" * 8


class FileVersionOut(Schema):
    """One version: the ordinal, what we measured, and whether it landed.

    `size_bytes` and `sha256` are **what this platform measured** by streaming the
    object, never what an uploader declared — see `models.FileVersion`. They are
    `None` and empty respectively until the version is `stored`, which is the
    honest answer while an upload is still outstanding rather than a zero that
    reads like a measurement.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("4c1d1e2f-3a4b-4c5d-8e9f-0a1b2c3d4e5f"))
    organization_id: UUID = Field(
        json_schema_extra=example("9f8e7d6c-5b4a-4321-8fed-cba987654321"),
        description="The part of the organization the document this version belongs to lives in.",
    )
    version: int = Field(
        json_schema_extra=example(2),
        description="The ordinal, counting from 1. Version 1 is never re-issued.",
    )
    content_type: str = Field(
        json_schema_extra=example("application/pdf"),
        description="What the uploader said the bytes are. Advisory, and never evidence.",
    )
    size_bytes: int | None = Field(
        json_schema_extra=example(41238),
        description="What we measured, in bytes. Null until the bytes have landed.",
    )
    sha256: str = Field(
        json_schema_extra=example(SAMPLE_DIGEST),
        description="The hex SHA-256 we computed by streaming the object. Empty until stored.",
    )
    status: str = Field(
        json_schema_extra=example("stored"),
        description="`pending` while the bytes are outstanding, `stored` once we have seen them.",
    )
    uploaded_by_id: UUID = Field(
        json_schema_extra=example("11111111-2222-4333-8444-555555555555"),
        description="Who uploaded this version — not the same question as who filed the document.",
    )
    created_at: datetime = Field(json_schema_extra=example("2026-08-24T09:30:00Z"))


class StoredFileOut(Schema):
    """One document, as `files.file.stored` and every read door report it.

    `current_version` is `0` until the first version finalizes. That is a real
    state, not a placeholder: a document whose only version is still pending has
    no current bytes, and a subscriber that sees `0` should read it as "nothing is
    downloadable yet" rather than as version one.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"))
    organization_id: UUID = Field(
        json_schema_extra=example("9f8e7d6c-5b4a-4321-8fed-cba987654321"),
        description="The part of the organization this document belongs to.",
    )
    filename: str = Field(
        json_schema_extra=example("invoice-2026-08.pdf"),
        description="The display name. Renaming it moves no bytes.",
    )
    purpose: str = Field(
        json_schema_extra=example("upload"),
        description="Your own short label for why the document exists. An open vocabulary.",
    )
    current_version: int = Field(
        json_schema_extra=example(2),
        description="Which version a reader who names none gets. `0` until the first one lands.",
    )
    uploaded_by_id: UUID = Field(
        json_schema_extra=example("11111111-2222-4333-8444-555555555555"),
        description="Who filed the document.",
    )
    archived_at: datetime | None = Field(
        json_schema_extra=example(None),
        description="When it was taken out of the working set. Null while it is live.",
    )
    created_at: datetime = Field(json_schema_extra=example("2026-08-24T09:30:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-08-24T09:31:12Z"))


class FileStoredOut(StoredFileOut):
    """What `files.file.stored` carries. **The document, plus the version that landed.**

    ADR files-2 says the payload is `StoredFileOut` and that it carries "the
    finalized `version`, its digest, and the resulting `current_version`". A
    `StoredFileOut` alone cannot say the first two — a digest belongs to a version,
    not to a document — so this is that sentence made a shape: it **is** a
    `StoredFileOut` (by inheritance, so every field a read door reports is here, in
    the same place, under the same name) with the finalized version nested under
    `version`.

    **Why the document's fields stay at the top level and are not nested too.**
    `apps/events/services.py::_subject_organization` narrows the fan-out on a
    payload's `organization_id` and on nothing else (house rule 38): a payload that
    buried it one level down would emit an event no branch owns, and
    `realtime.bridge.group_for` reads no-branch as **tenant-wide**. So the top
    level is the subject's own read shape, exactly as every other event's is.

    **`current_version` and `version.version` are two different numbers and a
    subscriber has to read both.** A version finalizing out of order does not
    promote — `record_stored` advances `current_version` only upward — so
    `version.version` is what just landed and `current_version` is what a reader
    who names no version gets. They are equal in the ordinary case and the ordinary
    case is not the contract.
    """

    version: FileVersionOut


class UploadTicketOut(Schema):
    """A place to put one version's bytes, and the two headers the PUT must carry.

    What `POST /files/` and `POST /files/{id}/versions` answer with. **The URL is
    in this answer and nowhere else** — it is a signature with an expiry, and a
    signature written to a column is a credential at rest — so re-reading the
    document later will not give it back to you. Ask again and a fresh one is
    minted and audited.

    **The PUT is signed for exactly two headers and both are required.** Send
    `Content-Type` set to the value you declared here, and `If-None-Match: *`,
    which is the store's own way of saying *write only if nothing is there*. SigV4
    covers the header set, so omitting either is not a lenient upload — it is a
    signature over a request you did not make, and the store refuses it before a
    byte lands. That belt is also what stops a leaked upload URL from replacing
    bytes that have already been finalized and digested.

    Then call `POST /files/{id}/versions/{n}/confirm`. Nothing is stored until the
    platform has been round and measured the object itself.
    """

    file: StoredFileOut
    version: FileVersionOut
    upload_url: str = Field(
        json_schema_extra=example("https://objects.example.com/…?X-Amz-Signature=…"),
        description="Where to PUT the bytes. Short-lived, and issued once.",
    )
    expires_in: int = Field(
        json_schema_extra=example(900),
        description="How many seconds the upload URL is good for.",
    )


class FileDownloadOut(Schema):
    """Where one version's bytes are, for the few minutes after you asked.

    What `POST /files/{id}/download-url` answers with, at both doors. It names the
    version it signed for, which is the same version the audit row records: an
    issuance is a witnessed act, and what was witnessed is *which bytes*, not
    *which document*.

    **The link is a bearer credential with no name on it.** Anyone holding it can
    fetch those bytes until it expires, and nothing of ours sits in that request
    path — so do not paste it anywhere durable, and do not store it. When it
    expires the store answers `403` in its own words, un-re-dressed by us, and the
    remedy is to ask here again rather than to look for a longer-lived link. There
    is no longer-lived link, and re-issuing re-audits.

    **A URL issued for version 2 keeps serving version 2's bytes** after version 3
    lands and becomes current. Every version has its own object; promotion moves
    which one a reader who names none gets, and never what an already-issued link
    means.
    """

    file_id: UUID = Field(json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"))
    version: int = Field(
        json_schema_extra=example(2),
        description="The version these bytes are. Pinned at issuance and never re-pointed.",
    )
    version_id: UUID = Field(json_schema_extra=example("4c1d1e2f-3a4b-4c5d-8e9f-0a1b2c3d4e5f"))
    download_url: str = Field(
        json_schema_extra=example("https://objects.example.com/…?X-Amz-Signature=…"),
        description="A temporary link straight to storage. Needs no credential of yours.",
    )
    expires_in: int = Field(
        json_schema_extra=example(300),
        description="How many seconds the link is good for.",
    )
    content_type: str = Field(
        json_schema_extra=example("application/pdf"),
        description="What the uploader declared the bytes are. Advisory.",
    )
    size_bytes: int | None = Field(
        json_schema_extra=example(41238),
        description="What we measured when we streamed the object.",
    )
    sha256: str = Field(
        json_schema_extra=example(SAMPLE_DIGEST),
        description="The digest we measured. Check the bytes you fetched against it.",
    )


class FileIn(StrictIn):
    """What a client sends to file a new document.

    There is no `organization` on this list and its absence is the enforcement: a
    document lands at the organization the request was made under — the `X-Org`
    header, or your default one — so no body can put one somewhere the caller is
    not a member.
    """

    filename: str = Field(
        max_length=255,
        json_schema_extra=example("invoice-2026-08.pdf"),
        description="What to call it. A label for people; nothing about the bytes depends on it.",
    )
    content_type: str = Field(
        max_length=255,
        json_schema_extra=example("application/pdf"),
        description="What you are about to upload. The presigned PUT is signed for this value.",
    )
    size_bytes: int = Field(
        ge=0,
        json_schema_extra=example(41238),
        description="How big you expect it to be. Checked against the limit; never recorded.",
    )
    purpose: str = Field(
        default="upload",
        max_length=64,
        json_schema_extra=example("upload"),
        description="Your own short label for why it exists — `contract`, `lab-result`, anything.",
    )


class VersionIn(StrictIn):
    """What a client sends to replace a document — which is to add a version beside it.

    There is no `filename` here: replacing a document does not rename it, and a
    body that could would make "replace" two acts with one name.
    """

    content_type: str = Field(
        max_length=255,
        json_schema_extra=example("application/pdf"),
        description="What you are about to upload. The presigned PUT is signed for this value.",
    )
    size_bytes: int = Field(
        ge=0,
        json_schema_extra=example(41238),
        description="How big you expect it to be. Checked against the limit; never recorded.",
    )


class ConfirmUploadIn(StrictIn):
    """What a client sends to say the bytes are up.

    `idempotency_key` is **your own name for the unit of work**, and it is
    required: a confirm with no key is a caller who has not thought about their own
    retries. It is not what stops a double confirm — the verification run's id is
    derived from the version, so a second confirm joins the first run rather than
    starting one — it is what ties this call to whatever you were doing in your own
    system, on the audit row and in the log line.
    """

    idempotency_key: str = Field(
        max_length=255,
        json_schema_extra=example("upload-9f3c1"),
        description="Your own name for this upload. Rides onto the audit row.",
    )


class DownloadUrlIn(StrictIn):
    """What a client may send when asking for a link to the bytes.

    Send nothing and you get the current version. Name a `version` and the link is
    pinned to that one — useful when you recorded a digest and want the bytes it
    was taken from, whatever has landed since.
    """

    version: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=example(2),
        description="Which version to sign for. Leave it out for the current one.",
    )


class ArchiveIn(StrictIn):
    """What a client may send when archiving a document.

    Empty on purpose, and a schema rather than no body at all: archiving takes a
    reason the day somebody rules that it does, and a route that took no body would
    make that a breaking change instead of an added optional field. Sending an
    unknown field here is refused, which is what makes the emptiness a contract.
    """


class FileFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised.

    A `FilterSchema` is how ninja turns query parameters into a `Q` without any
    route reading `request.GET` — which is where filtering usually goes wrong,
    because a hand-rolled filter reaches into `.filter(**request.GET)` and lets a
    client query any column and traverse any relation.

    `purpose` is an exact match: it is a label a product chose, and a substring
    match would make `?purpose=export` quietly mean `export-archive` too.
    `filename` is a containment match, because a filename is what a person
    remembers half of.
    """

    purpose: Annotated[str | None, FilterLookup(q="purpose__iexact")] = Field(
        default=None, json_schema_extra=example("upload")
    )
    filename: Annotated[str | None, FilterLookup(q="filename__icontains")] = Field(
        default=None, json_schema_extra=example("invoice")
    )


class FilePage(ListPage):
    """One page of documents, in the envelope the HTTP list uses.

    The MCP tool returns a value rather than a response, so the same envelope has
    to be a schema it can declare — and it is deliberately the *same* envelope,
    inherited from `core.schemas.ListPage`, because a machine client that has
    learned to unwrap one list should not have to learn a second shape.
    """

    items: list[StoredFileOut]


class FileVersionPage(ListPage):
    """One page of versions of one document, in the same envelope."""

    items: list[FileVersionOut]
