"""The one module that speaks to the object store. Bytes never pass through Django.

ADR files-2's stack ruling: MinIO on a laptop, in CI and in every worktree; S3
in a deployment; **one boto3-backed seam** rather than django-storages, because
django-storages' whole abstraction is `FieldFile` semantics this design does not
use — the client and the object store exchange bytes directly, on presigned URLs
this module mints, and Django only ever holds the metadata.

**Everything about a bucket is decided here.** This is the only module under
`apps/` that imports boto3 or names a storage setting — the shape house rule 27
uses for the identity platform, for the same reason: "exactly one place" has to
be something a check can see, and the storage wall (ADR files-2 § "Rules &
canaries born with it") is the check that will see it.

**`version_key` below is now the ONLY key builder in this repository**, and this
paragraph is the record of how that became true rather than a comparison a
reader still has to make. It was written as a coexistence note: the core app's `storage.py`
held a `tenant_prefixed_key` producing `tenants/<slug>/<uuid>-<name>`, and this
module's `version_key` produced `t/<tenant pk>/f/<file pk>/v/<n>`, and the two
lived side by side because `apps/exports` still wrote its archive through
`default_storage` with the core one. **Both halves of that are gone.** Exports
was re-pointed onto `files.services.store_bytes`, which took the
last production caller; the module was then deleted. The
supersession's REASON is what survives and is worth keeping: a key carrying a
tenant SLUG and a FILENAME is built out of two renamable, re-issuable,
user-supplied things, and ADR files-2 rules that keys carry primary keys and a
version ordinal and nothing else.

House rule 48 is the enforceable form of the same sentence now — one door to the
object store, and this is the door — so a second key grammar cannot reappear
quietly the way the first one lingered.

**No silent fallback** (the ADR's posture, and search-2's in the other
direction): there is no degradation engine behind this seam. An unreachable
backend raises, a missing bucket name raises at the moment it is asked for, and
neither is quietly retried into something that looks like it worked.

**HOW BYTES COME BACK OUT: this seam signs, and it does not stream**, applying
the ratified either/or rather than inventing a second one. The
ratified shape is *"a presigned `download_url` where the backend signs, and an
authenticated `/download` stream otherwise"* (`architecture.md`, the exports
row). **This seam is always the first branch**: `bucket_name()` refuses a
deployment that has named no bucket, so a files object only ever exists where a
backend that signs is configured — MinIO on a laptop, in CI and in every
worktree, S3 in a deployment. There is no filesystem-fallback world here for a
`get_stream` to serve.

So there is deliberately **no read-the-bytes function on this module for a
door**: `presign_get` fills `download_url`, and a `/download` door over a files object
**may 302 to it** rather than proxying. `sha256_of` reads an object, and it is
not that function wearing a different hat — it measures and returns two numbers,
it never hands bytes to a caller, and a door that used it to serve a response
would be putting a whole document through a worker's memory. The one thing this
whole app is shaped to prevent is bytes travelling through Django, and a
`get_stream` with no world that needs it would be that shape with a permission
slip. **The door rung applies this; it is not implemented here** — an ADR-level
change (a backend that cannot sign) is what would reopen it. Bytes may reach a
Temporal ACTIVITY's own parser through `iter_object`, chunk by chunk, and never
a response: a door that proxied them (a `get_object` or `iter_object` call from
an `api.py`, `mcp.py` or `consumers.py`) is exactly what this paragraph refuses.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Generator, Iterator, Sequence
    from pathlib import Path

    from apps.core.models import Tenant

# --- The TTLs (ADR files-2 § "Presigned URLs") --------------------------------
#
# PER-ENVIRONMENT SETTINGS, opened by the rung that opened the doors that
# issue these URLs, which left them as constants with the reason written down — a
# settings variable lands with its `.env.example` line in the same commit, and
# `config/settings/` was outside that work's territory — and a later measurement showed
# the gap's cost: `.env.example` presents `AWS_QUERYSTRING_EXPIRE=3600` directly
# under "objects are private and read through a signed URL that expires", that
# variable feeds `STORAGES` and nothing else, and an operator tuning presign
# lifetime edited the line while this seam went on minting 900 and 300.
#
# The NUMBERS below are the ADR's and are the defaults, so a deployment that
# configures nothing behaves exactly as it did before this change.
#
# READ THROUGH A FUNCTION, never captured in a default argument. A module-level
# `expires_in: int = DOWNLOAD_URL_TTL_SECONDS` is evaluated once at import, which
# would make the setting readable only by whoever restarted the process — and
# unreachable from a test that wants to prove the knob is wired to the signature.

#: FIVE MINUTES for a download, because a longer one turns each issuance into a
#: durable bearer credential: a presigned URL is a stateless signature and there
#: is no such thing as revoking one. A UI that needs the bytes again re-issues,
#: and re-issuance re-audits.
DOWNLOAD_URL_TTL_SECONDS = 300

#: FIFTEEN MINUTES for an upload, because a large file on a slow link has to get
#: started, and short because whatever lands in that PENDING key is digested and
#: measured at finalize regardless of who put it there.
UPLOAD_URL_TTL_SECONDS = 900


def download_url_ttl() -> int:
    """How long a download link is good for, in seconds. `FILES_DOWNLOAD_URL_TTL`."""
    return int(getattr(settings, "FILES_DOWNLOAD_URL_TTL", DOWNLOAD_URL_TTL_SECONDS))


def upload_url_ttl() -> int:
    """How long an upload link is good for, in seconds. `FILES_UPLOAD_URL_TTL`."""
    return int(getattr(settings, "FILES_UPLOAD_URL_TTL", UPLOAD_URL_TTL_SECONDS))


# --- The bucket ---------------------------------------------------------------

#: A bucket name is `[a-z0-9-]`, 3–63 characters, starting and ending with a
#: letter or a digit. Everything this module derives is inside that by
#: construction; the pattern is here so the derivation can be asserted against
#: the rule rather than against itself.
BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")

#: The prefix every derived name carries, so a MinIO console listing says at a
#: glance which buckets belong to this template's checkouts.
BUCKET_PREFIX = "djb"

#: Everything a directory name might hold that a bucket name may not.
_UNSAFE_IN_BUCKET = re.compile(r"[^a-z0-9]+")

#: The same 38 `scripts/db.sh` caps a branch at, and for the same arithmetic:
#: prefix(3) + `-`(1) + label(38) + `-`(1) + hash(8) = 51, and a pytest-xdist
#: worker suffix (`-gw999`, up to 6) takes it to 57 — inside 63 with room.
MAX_BUCKET_LABEL = 38

#: **The name of the variable, held here because this is the module that may
#: hold it.** House rule 48 fences `AWS_STORAGE_BUCKET_NAME` to this seam and to
#: `config/settings/`, and an earlier attempt found out what that costs: a census row
#: saying "no object storage here" has to print the variable as its REMEDY, and
#: `apps/core/integrations.py` was refused BY NAME for trying. The fence is
#: right and the remedy is owed, so the string lives where the fence puts it and
#: `apps/files/integrations.py` asks this module for it — the same shape as
#: every other fact about a bucket being decided here.
BUCKET_SETTING = "AWS_STORAGE_BUCKET_NAME"

#: What somebody types to give this deployment object storage. Printed by the
#: integrations census and by `bucket_name`'s own refusal, so the two cannot
#: come to say different things.
CONFIGURE_BUCKET_REMEDY = (
    f"set {BUCKET_SETTING} in .env to a bucket that exists — on a laptop or in a "
    "worktree `scripts/setup.sh` does both (it runs `manage.py ensure_bucket` and "
    "writes the derived name back); a deployment names its own S3 bucket there and "
    "lets the instance role carry the credentials."
)

#: The other half of the pair: a bucket IS named and the store would not answer.
#: Here for the same reason `CONFIGURE_BUCKET_REMEDY` is — it names the endpoint
#: variable, which rule 48 fences to this module — and beside it so the two
#: remedies for the two halves of one question cannot drift apart.
UNREACHABLE_BUCKET_REMEDY = (
    "on a laptop or in a worktree the store is the compose MinIO — "
    "`docker compose up -d minio` — and the address the app dials is "
    "AWS_S3_ENDPOINT_URL in .env; a deployment checks that the bucket named in "
    f"{BUCKET_SETTING} still exists in the region configured and that this role may "
    "see it."
)


def derived_bucket_name() -> str:
    """This checkout's own bucket name — the `DATABASE_NAME` derivation, for objects.

    **Why a checkout derives one at all.** Agents build in parallel worktrees
    against one compose stack. Postgres was solved first (`scripts/db.sh`: a
    database per checkout, named for the checkout's own absolute path), and an
    object store has exactly the same collision — two gates listing
    `t/<tenant>/` in one bucket would see each other's objects, and a prefix
    delete in one would take the other's away. So the bucket follows the
    checkout, by the same rule: the SHA-256 of the checkout's absolute top-level
    path, first eight hex digits, with the directory's own name in front of it
    so a human reading a listing can tell which is which.

    **A name in the environment WINS** — `AWS_STORAGE_BUCKET_NAME` — exactly as
    `DATABASE_NAME` does, and that is the only escape. This function is what a
    checkout should put THERE (`scripts/setup.sh` writes the database's line
    today and the storage line is the flagged follow-on); it is not consulted by
    `bucket_name` below, because a seam that invents a bucket when none is
    configured would contradict the one thing `/readyz` says about storage: a
    report with no `storage` member IS the signal that no bucket is named
    (`apps/core/health.py::checks`). Two answers to "is object storage
    configured" is one answer too many.
    """
    return bucket_name_for(settings.BASE_DIR)


def bucket_name_for(root: Path) -> str:
    """The bucket name a checkout at `root` derives — `derived_bucket_name` for any path."""
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    label = _UNSAFE_IN_BUCKET.sub("-", str(root.name).lower()).strip("-")
    label = label[:MAX_BUCKET_LABEL].strip("-")
    return f"{BUCKET_PREFIX}-{label}-{digest}" if label else f"{BUCKET_PREFIX}-{digest}"


def bucket_name() -> str:
    """The bucket this process reads and writes, or a refusal saying so.

    Two jobs and no third: read what the deployment configured, and keep two
    pytest-xdist workers out of each other's objects.

    **The refusal is the design.** There is no derived fallback here — see
    `derived_bucket_name` for the whole argument. A deployment that has not
    named a bucket has not configured object storage, `config/settings/base.py`
    leaves `STORAGES` on the local filesystem to say so, `/readyz` omits its
    `storage` member to say so, and this raises to say so. An app that quietly
    picked a name would be the fourth opinion and the only one that wrote
    anything.
    """
    configured = settings.AWS_STORAGE_BUCKET_NAME
    if not configured:
        raise ImproperlyConfigured(
            "apps.files needs AWS_STORAGE_BUCKET_NAME. No bucket is named, so this "
            "deployment has no object storage: `STORAGES` is on the local filesystem "
            "and /readyz carries no `storage` member. On a laptop or in a worktree the "
            f"name to set is this checkout's own — {derived_bucket_name()} — and the "
            "bucket has to exist: `manage.py ensure_bucket` derives that name and "
            "creates it, and `scripts/setup.sh` runs it for you. Nothing on a read or "
            "a write path ever creates a bucket."
        )
    return _worker_suffixed(configured)


def _worker_suffixed(name: str) -> str:
    """The configured name, plus this pytest-xdist worker's own suffix.

    **Outside pytest this is the identity function**, because `PYTEST_XDIST_WORKER`
    is set by xdist and by nothing else — the same variable pytest-django reads
    to give each worker its own database (`test_<name>_gw0`). Inside a parallel
    run it is what stops worker 3's prefix delete from taking worker 4's objects
    away while worker 4 is still reading them: one bucket per worker, disjoint by
    construction rather than by every test remembering to namespace itself.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    if not worker:
        return name
    return f"{name}-{_UNSAFE_IN_BUCKET.sub('-', worker.lower()).strip('-')}"


# --- Keys ---------------------------------------------------------------------


def tenant_prefix(tenant: Tenant) -> str:
    """Everything one tenant's objects live under. The unit of a prefix delete.

    The tenant's PRIMARY KEY and not its slug: a slug is renamable and
    re-issuable, and a key that quoted one would point somewhere else after a
    rename — or, worse, at a different tenant after a re-issue.
    """
    return f"t/{tenant.pk}/"


def version_key(*, tenant: Tenant, file_pk: Any, version: int) -> str:
    """Where one version's bytes live, forever. **The only way a key is built.**

    `t/<tenant pk>/f/<file pk>/v/<n>`. Four facts and no fifth:

    * the TENANT is in it, because a prefix delete has to be able to reach
      exactly one customer's objects and nobody else's;
    * the ORGANIZATION is deliberately NOT, because re-parenting a branch is a
      row edit and must never orphan an object key (ADR files-2, kept from
      files-1);
    * the FILE's primary key, so a rename is free — the identity
      that survives a rename is the key, and the key lives on the version;
    * the VERSION ordinal, which is what makes replace a new object rather than
      an overwrite of an old one.

    No filename (user input, and a name is a label), no digest (a
    content-addressed key makes an instant upload a cross-tenant existence
    oracle), no slug.
    """
    return f"{tenant_prefix(tenant)}f/{file_pk}/v/{version}"


def refuse_foreign_key(*, tenant: Tenant, key: str) -> None:
    """**The seam's own belt**: this tenant's keys, or nothing.

    Every function below that signs or reaches an object calls this first, so a
    signature over another tenant's key cannot be produced even by a confused
    caller already inside the wall. It is not the wall — `for_tenant` and
    `visible_to` are, at every door — and it is not a substitute for one. It is
    the last thing standing between a resolved-the-wrong-row bug and a URL
    somebody else can fetch, and it costs a string comparison.

    `ValueError` and not a domain refusal: reaching here with a foreign key is a
    programming error inside the wall, not something a client did. The doors
    turn a client's unreachable reference into `not_found` long before this.
    """
    prefix = tenant_prefix(tenant)
    if not key.startswith(prefix):
        raise ValueError(
            f"refusing to touch {key!r}: it is not under {prefix!r}. A key outside the "
            "acting tenant's prefix reached the storage seam, which means something "
            "upstream resolved a row it should not have — signing this would hand out "
            "another tenant's bytes."
        )


# --- The client ---------------------------------------------------------------

#: boto3's defaults are a 60-second connect with retries on top, which turns a
#: slow bucket into a hung worker rather than a failed call. The same reasoning
#: (and the same posture) as `apps/core/health.py::check_object_storage`, with a
#: longer budget because this one does real work rather than a readiness probe.
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3

#: How much of an object is held in memory at once while it is digested. Big
#: enough that a large object is not a million round trips, small enough that a
#: worker thread streaming one is not a memory event.
DIGEST_CHUNK_BYTES = 1024 * 1024

#: S3's own limit on one `delete_objects` call.
DELETE_BATCH = 1000

#: The conditional-write condition every write this seam signs or performs
#: carries: **succeed only if nothing is there**. `*` is S3's and MinIO's own
#: spelling of "no entity tag matches, because there is no entity"; a store that
#: honours it answers 412 rather than overwriting. See `presign_put` for why it
#: is a belt and never the fence.
OVERWRITE_NOTHING = "*"


def client() -> Any:
    """The S3 client, built from settings. **Never cached.**

    Not cached because a `settings` override in a test has to be seen — the
    `settings` fixture is how a test points this at a bucket of its own, and a
    module-level client would have frozen the first environment it met. boto3's
    own session handling makes the construction cheap; the connection pool it
    opens is per-client and short-lived here by design.

    Credentials are read from settings only because a laptop pointing at MinIO
    has nothing else. A deployment leaves them empty and boto3 finds the
    instance role or the workload identity by itself, which is why the
    `or None` on each is load-bearing: an empty string would be taken literally
    as a credential and the role would never be consulted.
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME or None,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        config=Config(
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            retries={"max_attempts": MAX_ATTEMPTS},
            # Presigned URLs are signed with SigV4 explicitly rather than by
            # whatever the region negotiated: MinIO and S3 both honour it, and a
            # URL whose signature version depends on the endpoint is a URL that
            # works on a laptop and not in production.
            signature_version="s3v4",
        ),
    )


# --- What the seam offers -----------------------------------------------------


@dataclass(frozen=True)
class ObjectHead:
    """What the store says about an object without fetching it.

    `size_bytes` is the store's own count and `etag` is the store's own
    identifier — neither is the digest this app records. `sha256_of` below is
    what produces that, by reading the bytes, because an ETag is a
    multipart-dependent implementation detail and not a content hash.
    """

    size_bytes: int
    content_type: str
    etag: str


@dataclass(frozen=True)
class DigestedObject:
    """The bytes we actually hold, measured by us.

    Both fields come from the same single pass over the object, so they cannot
    disagree with each other the way a HEAD and a later GET could.
    """

    sha256: str
    size_bytes: int


def presign_put(
    *,
    tenant: Tenant,
    key: str,
    content_type: str,
    expires_in: int | None = None,
    store: Any = None,
) -> str:
    """A URL a client may PUT one object to, once this tenant's prefix allows it.

    **What a leak of this URL exposes, exactly**: write access into ONE key
    until it expires. Not a list, not another key, not a read of anything else.
    Whatever lands there is streamed and measured by `FinalizeUpload` before any
    row calls it stored, so a hijacked pending upload produces a
    wrong-but-witnessed object rather than a silent one.

    **The belt: `If-None-Match: *`** (ADR files-2). The signature covers the
    header (`X-Amz-SignedHeaders=...;if-none-match`), so the URL is unusable
    without it and the store itself then refuses the PUT — 412 — if anything is
    already at the key. A leaked pre-finalize URL replayed after the version has
    landed therefore cannot overwrite the object whose digest a manifest or an
    audit row already quotes.

    **The belt is never the fence.** The fence is the service side:
    `create_file`/`add_version` mint an upload URL only for a `PENDING` version
    and refuse a `STORED` one, which stands on backends that honour no
    conditional write at all. This costs one header and closes the window
    between the object landing and the row learning about it, which is the one
    window the service-side refusal cannot see.

    **What this asks of the client, stated because it is a wire contract**: the
    PUT must send **both** `Content-Type` (the value passed here) and
    `If-None-Match: *`. They are signed headers; omitting either is a signature
    mismatch, not a lenient upload. The door that hands the URL out is where that
    sentence has to reach a caller.

    `expires_in=None` means this deployment's `FILES_UPLOAD_URL_TTL`, read at the
    call rather than at import so the knob is the one thing a signature depends on
    that an operator can actually turn.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    return str(
        (client() if store is None else store).generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket_name(),
                "Key": key,
                "ContentType": content_type,
                "IfNoneMatch": OVERWRITE_NOTHING,
            },
            ExpiresIn=upload_url_ttl() if expires_in is None else expires_in,
        )
    )


def put_bytes(*, tenant: Tenant, key: str, content: bytes, content_type: str) -> None:
    """Put bytes we already hold at one key. **The generation path, not the upload one.**

    A client's bytes never come through here — they go straight to the store on a
    presigned URL, which is the whole design. What comes through here is what the
    PLATFORM rendered: an export archive, a generated document. `store_bytes` is
    the service that calls it, and it is the only caller there should ever be.

    The same `If-None-Match: *` condition the presigned PUT carries, for the same
    reason and one more: `store_bytes` allocates a fresh version and so writes a
    key nothing has ever written, and a PUT that succeeded at an occupied key
    would mean the version allocator had handed out an ordinal twice. Better to
    hear that as a failed store than to discover it as a rewritten digest.

    Not streamed, because the caller is holding the bytes already: a renderer
    returns a document, and spooling it through a file to hand boto3 a file-like
    object would buy nothing.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    client().put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=content,
        ContentType=content_type,
        IfNoneMatch=OVERWRITE_NOTHING,
    )


# --- A body that never fits in memory -----------------------------------------
#
# WHY A WRAPPER AND NOT A SECOND READ. The digest this platform records has to be
# the digest of the bytes the store received; the cheap way to get one is to read
# the object back afterwards (`sha256_of`, which is exactly what `store_bytes`
# does and pays for on purpose). That is fine for a rendered document held in
# memory and wrong for an archive: a read-back doubles the network for a body
# whose whole reason for streaming was that it does not fit anywhere.
#
# WHAT THE SDK ACTUALLY DOES WITH A FILE-LIKE BODY, measured against MinIO rather
# than assumed (measured: a 12 MiB spooled body produced 37.7 MiB of reads
# and six seeks). `put_object` with a seekable body reads it MORE THAN ONCE — a
# length probe (`seek(0, 2)`), the SigV4 payload signature over plain HTTP, and
# then the transmission — rewinding to the start before each pass. So a hash fed
# by a naive read-through wrapper is the hash of THREE copies, and the failure is
# silent: a plausible-looking digest that matches nothing.
#
# Hence `_MeasuredBody`: it hashes what it hands over and **starts again whenever
# the body is rewound to the beginning**, so what it holds at the end is the
# digest of the LAST pass — the one that went on the wire — and not of the
# rehearsals. `test_a_streamed_store_measures_the_bytes_it_actually_sent` uses a
# body large enough for the multi-pass behaviour to be real; without the restart
# it fails with a digest three passes wide.
#
# The payload-signature pass disappears over HTTPS (botocore sends
# `UNSIGNED-PAYLOAD` there), which makes this cheaper in a deployment than on a
# laptop. Nothing about the digest changes either way, because the restart is
# about the LAST pass rather than about how many there were.


class Rewindable(Protocol):
    """What this seam needs of a body: read it, and put it back to the start.

    A `Protocol` rather than `IO[bytes]` because those four methods are the whole
    requirement, and a type that demanded the rest of the file interface would be
    asking a caller for permissions it never uses. A `SpooledTemporaryFile` —
    what an archive builder holds — satisfies it, and so does a plain file, a
    `BytesIO` and a test double.

    `seekable()` is in the contract rather than assumed, because
    `store_stream` refuses a body that answers `False` (see it for why the SDK
    needs the rewind, and why spooling one here would be this seam deciding how
    much of the caller's memory to spend).
    """

    def read(self, size: int = -1, /) -> bytes: ...

    def seek(self, offset: int, whence: int = 0, /) -> int: ...

    def tell(self) -> int: ...

    def seekable(self) -> bool: ...


class _MeasuredBody(io.RawIOBase):
    """A read-through body that measures the pass the store actually receives.

    `io.RawIOBase` and not a bare object, because botocore inspects a body for
    `read`/`seek`/`tell` and urllib3 reads it in chunks — this is the shape both
    already know how to drive, proven against the real client rather than
    guessed.

    Nothing here buffers: a chunk is hashed, counted and handed straight on, so
    the most memory this holds at once is one of the SDK's own reads.
    """

    def __init__(self, inner: Rewindable) -> None:
        self._inner = inner
        self._digest = hashlib.sha256()
        self._size = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._inner.read(size)
        if chunk:
            self._digest.update(chunk)
            self._size += len(chunk)
        return chunk

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        position = self._inner.seek(offset, whence)
        if position == 0:
            # Back at the beginning: whatever was measured was a rehearsal.
            self._digest = hashlib.sha256()
            self._size = 0
        return position

    def tell(self) -> int:
        return self._inner.tell()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def measured(self) -> DigestedObject:
        return DigestedObject(sha256=self._digest.hexdigest(), size_bytes=self._size)


def store_stream(
    *, tenant: Tenant, key: str, body: Rewindable, content_type: str
) -> DigestedObject:
    """Put a body we are HOLDING OPEN at one key, and measure it on the way past.

    The streaming sibling of `put_bytes`, for the caller that built its bytes in
    a `SpooledTemporaryFile` — an export archive is the first — and would have to
    materialise the whole thing in RAM to call `put_bytes(content=body.read())`.
    A tenant's export is as large as the tenant, so that call is a worker one
    customer away from being killed.

    **What comes back is measured, not counted**: the digest and the size are the
    bytes this seam handed to the store, taken during the transmission (see
    `_MeasuredBody` above for why that is one pass and not three). No read-back
    over the network, which is the one thing `store_bytes` pays for and the one
    thing an archive cannot afford.

    **The belt: the store's own `HEAD` has to agree about the size.** The digest
    is ours and unverifiable from outside; the length is not, and a store that
    truncated, or a pass this wrapper mis-tracked, shows up as two different
    numbers. Disagreeing is a `RuntimeError` and never a recorded row: an
    activity retries, and the alternative is a `sha256` column that is a fact
    about nothing.

    **The body must be rewindable, and this refuses one that is not.** The SDK
    rewinds (above), so a one-shot iterator cannot be uploaded at all — and
    spooling one to disk inside this function would be this seam quietly deciding
    how much of the caller's memory its body may use, which is the decision the
    caller is holding a `SpooledTemporaryFile` in order to make for itself.

    **From the beginning, always.** The body is rewound before the first byte
    goes anywhere, so "store this file" never means "store the part of it nobody
    has read yet" because of where some earlier reader left the cursor.

    The same `If-None-Match: *` condition the other two write paths carry, for
    the same reason: this writes a freshly allocated version key, and a PUT that
    succeeded at an occupied one would mean the allocator handed out an ordinal
    twice.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    if not (callable(getattr(body, "seekable", None)) and body.seekable()):
        raise ValueError(
            "store_stream needs a seekable body and this one is not: the S3 client "
            "rewinds a body to measure its length and to sign it, so a one-shot "
            "iterator cannot be uploaded. Spool it first — a SpooledTemporaryFile is "
            "what the archive builders use — so the memory ceiling stays yours."
        )
    body.seek(0)
    measuring = _MeasuredBody(body)
    client().put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=measuring,
        ContentType=content_type,
        IfNoneMatch=OVERWRITE_NOTHING,
    )
    measured = measuring.measured()
    described = head(tenant=tenant, key=key)
    if described.size_bytes != measured.size_bytes:
        raise RuntimeError(
            f"the store holds {described.size_bytes} bytes at {key!r} and this stream "
            f"measured {measured.size_bytes}. Nothing is recorded: a digest that is "
            "not about the object it names is worse than a failed store."
        )
    return measured


def presign_get(
    *,
    tenant: Tenant,
    key: str,
    expires_in: int | None = None,
) -> str:
    """A URL a client may GET one object from until it expires.

    **A window, never single-use, and the ADR says so out loud**: a presigned URL
    is a stateless signature and single-use does not exist without a stateful
    door in front of the bytes — which would be this design's own rejection
    (proxying bytes through Django) wearing a feature name. The mitigation is the
    five-minute default and the fact that issuance is audited.

    **Use is not first-party observable.** The GET reaches the object store, not
    us. What this platform can claim is issuance; the store's own access logs are
    the record of use, and wiring them is the production pass's job.

    `expires_in=None` means this deployment's `FILES_DOWNLOAD_URL_TTL`, read at the
    call rather than at import — see the TTL block at the top of this module for
    why the pair stopped being constants.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    return str(
        client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name(), "Key": key},
            ExpiresIn=download_url_ttl() if expires_in is None else expires_in,
        )
    )


def head(*, tenant: Tenant, key: str) -> ObjectHead:
    """What is at this key, without reading it. Raises if there is nothing there.

    The cheap half of finalize: it answers "did anything land" before
    `sha256_of` pays to read the whole object.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    response = client().head_object(Bucket=bucket_name(), Key=key)
    return ObjectHead(
        size_bytes=int(response["ContentLength"]),
        content_type=str(response.get("ContentType", "")),
        etag=str(response.get("ETag", "")).strip('"'),
    )


def sha256_of(*, tenant: Tenant, key: str) -> DigestedObject:
    """Stream the object and measure it. **The digest of the bytes we hold.**

    Streamed in chunks rather than read whole, because the size of a document is
    the client's choice and a worker that loads one into memory is a worker one
    upload away from being killed.

    Never trusts anything the client said: what comes back is what was on the
    wire, counted and hashed in one pass, and it is what `record_stored` writes.
    A digest a client supplied is a digest that says whatever the client wanted.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    digest = hashlib.sha256()
    size = 0
    body = client().get_object(Bucket=bucket_name(), Key=key)["Body"]
    try:
        while chunk := body.read(DIGEST_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    return DigestedObject(sha256=digest.hexdigest(), size_bytes=size)


def iter_object(*, tenant: Tenant, key: str, chunk: int = DIGEST_CHUNK_BYTES) -> Generator[bytes]:
    """The object's bytes, a chunk at a time — **for an activity's parser, never a door.**

    The one server-side read of an object's CONTENT this seam offers, and the
    reason it exists is a worker that must look inside a file the platform was
    handed (an import validating a CSV row by row) without holding the whole
    document in memory. It is `sha256_of`'s own walk — the same belt first, the
    same `get_object`, the same chunk size by default — yielding the chunks
    instead of hashing them.

    **Eager where it can refuse, lazy where it reads.** `refuse_foreign_key` and
    a `head_object` run when this is CALLED, so another tenant's key and a missing
    object both raise at the call site rather than as an empty iterator a caller
    might mistake for an empty file. The body is opened on the first chunk asked
    for — an iterator nobody reads holds no connection — and closed in `finally`,
    so a caller that stops early (a `break` after the header row) releases it
    rather than leaking it. An object deleted between the two calls raises on the
    first chunk: late, but never silent.

    Never behind a door (the module docstring, § HOW BYTES COME BACK OUT): a route
    or a tool that handed these chunks to a client would be bytes travelling
    through Django, the one shape this app exists to prevent.
    """
    if chunk <= 0:
        raise ValueError("A chunk is a positive number of bytes.")
    refuse_foreign_key(tenant=tenant, key=key)
    bucket = bucket_name()
    client().head_object(Bucket=bucket, Key=key)
    return _chunks(bucket=bucket, key=key, chunk=chunk)


def _chunks(*, bucket: str, key: str, chunk: int) -> Generator[bytes]:
    """Yield the object in `chunk`-sized reads, and close it however the caller stops."""
    body = client().get_object(Bucket=bucket, Key=key)["Body"]
    try:
        while piece := body.read(chunk):
            yield piece
    finally:
        body.close()


def delete_prefix(*, tenant: Tenant) -> int:
    """Delete every object this tenant owns. Returns how many went.

    **The off-ORM half of tenant close and of erasure**, and the callable ADR
    files-2 names for the day object purge lands (`delete_tenant_objects`, which
    will be a service wrapping this). It is here now because the seam owes its
    consumers a complete surface — an app cannot be told "everything is
    reachable" if the thing that reaches a whole tenant's bytes is missing — and
    because a prefix delete written later, under pressure, next to a deadline, is
    the one that reaches one prefix too far.

    Paginated and batched because both limits are real: `list_objects_v2` returns
    a page at a time and `delete_objects` takes a thousand keys at a time.
    """
    bucket = bucket_name()
    prefix = tenant_prefix(tenant)
    s3 = client()
    deleted = 0
    batch: list[dict[str, str]] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for entry in page.get("Contents", []):
            # Belt inside the loop, not outside it: the prefix was sent to the
            # store, and what comes back is the store's answer. A key that is not
            # under this tenant's prefix has no business in this list, and
            # deleting one because a paginator surprised us is the failure this
            # function must not have.
            refuse_foreign_key(tenant=tenant, key=str(entry["Key"]))
            batch.append({"Key": str(entry["Key"])})
            if len(batch) == DELETE_BATCH:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
                deleted += len(batch)
                batch = []
    if batch:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        deleted += len(batch)
    return deleted


def delete_object(*, tenant: Tenant, key: str) -> None:
    """Delete ONE object. **Idempotent: a key that is not there is a no-op.**

    The single-object half of what `delete_prefix` does wholesale, and the thing
    a `PURGED` lifecycle declaration on a versioned document will stand on: a
    declaration saying "the bytes go when the row goes" is a declaration that
    lies until something can reach exactly those bytes.

    **Idempotent because the store is** — S3 and MinIO both answer `204` to a
    delete of a key that was never there (measured: `204`, no error), so
    there is nothing here catching an exception and calling it success. That
    matters because every caller is a retried purge: a second attempt that raised
    would make a replay indistinguishable from a failure, and the usual remedy
    for that is a bare `except` that also swallows the failures worth hearing.

    Belted like everything else here, and this is the function where the belt
    matters most: a signature over a foreign key hands out somebody else's bytes,
    and a delete of one destroys them.
    """
    refuse_foreign_key(tenant=tenant, key=key)
    client().delete_object(Bucket=bucket_name(), Key=key)


def create_bucket_if_absent() -> str:
    """Make sure this checkout has a bucket, and say which one. **Setup's door only.**

    Returns the name either way — the caller asked for a bucket to exist, and one
    does. It is what `scripts/setup.sh` writes into `.env`, which is what makes
    `/readyz` grow its `storage` member on a laptop (`core.health.checks`).

    **The name follows `DATABASE_NAME`'s rule 1: a configured name wins**, and a
    checkout with nothing configured gets its own derivation
    (`derived_bucket_name`). That precedence lives here rather than in the command
    or in the shell, because this is the file that owns what a bucket is called
    and two places deciding a name is how two checkouts end up sharing one.

    **This is not a fallback and cannot become one.** Nothing on a read or a write
    path calls it: `bucket_name()` still refuses a deployment that has named no
    bucket, and a seam that quietly created what it could not find would be
    exactly the fourth opinion that function's docstring refuses. The only callers
    are `manage.py ensure_bucket` and `scripts/setup.sh` through it — a human, or
    a script a human ran, asking for a bucket ON PURPOSE. That is also why the
    creating lives here rather than in the command: this module is the only one
    under `apps/` allowed to hold a boto3 client at all
    (`tests/test_storage_fence.py`), and a laptop bootstrap is not a reason to put
    a second one somewhere else.

    **No xdist suffix** (`_worker_suffixed` is deliberately not called): this
    answers "what should this CHECKOUT configure", and the per-worker split is a
    thing `bucket_name()` does to the configured value at test time. A setup
    script writing `…-gw0` into `.env` would pin every process to one worker's
    bucket.

    `head_bucket` first, because `create_bucket` on a bucket that already exists
    is a `BucketAlreadyOwnedByYou` on MinIO and a silent success in `us-east-1` on
    real S3 — two answers to one question, and the head asks the question that was
    actually meant.
    """
    name = settings.AWS_STORAGE_BUCKET_NAME or derived_bucket_name()
    s3 = client()
    try:
        s3.head_bucket(Bucket=name)
    except s3.exceptions.ClientError:
        # The region has to be RESTATED in the body outside `us-east-1`, and only
        # outside it: S3 answers `IllegalLocationConstraint` to a create with no
        # constraint anywhere else, and `InvalidLocationConstraint` to one that
        # names `us-east-1` — the one region whose name may not be said. MinIO
        # accepts either, so a laptop proves nothing about this line; it is here
        # for the operator running this command against a real bucket in
        # `eu-west-1`, and it is DECLARED UNPROVEN rather than assumed
        # (only MinIO was driven).
        region = settings.AWS_S3_REGION_NAME
        elsewhere = (
            {"CreateBucketConfiguration": {"LocationConstraint": region}}
            if region and region != "us-east-1"
            else {}
        )
        s3.create_bucket(Bucket=name, **elsewhere)
    return str(name)


# --- What an audit is allowed to look at -----------------------------------------
#
# `manage.py storage_audit` is the read-only drift tripwire for the one thing no
# check in `quality/` can see: the bucket itself. Rule 48's own `does_not_cover`
# says so in as many words — "THE BUCKET'S OWN STATE AND POLICY are the declared
# blind spot this rule is one half of … the partial answer is `manage.py
# ensure_bucket` and `storage_audit`, not a check."
#
# Everything that instrument needs to LOOK at lives here, for rule 48's reason
# and not as a convenience: the command may not hold a client, name a bucket
# setting or reach an object, so the alternative to these four functions is a
# second door to the store wearing an audit's clothes.
#
# THEY READ AND THEY NEVER WRITE. Not "should not": there is no write verb in
# this section, which is what makes "it changes nothing" a property of the code
# rather than a promise in a docstring (`zitadel_audit`'s standard, rule 27).


#: A pytest-xdist worker's copy of a derived name (`_worker_suffixed`).
_WORKER_SUFFIX = re.compile(r"-gw[0-9]+")


def list_derived_buckets() -> list[str]:
    """Every bucket in the store whose name carries the derived prefix, sorted. Reads only."""
    try:
        listed = client().list_buckets().get("Buckets", [])
    except (ClientError, BotoCoreError) as failure:
        raise StorageUnreadable(
            f"the object store would not list its buckets: {failure}"
        ) from failure
    return sorted(
        str(entry["Name"]) for entry in listed if str(entry["Name"]).startswith(f"{BUCKET_PREFIX}-")
    )


def derives(root: Path, name: str) -> bool:
    """Is `name` the bucket a checkout at `root` derives, or one of its xdist workers' copies?"""
    base = bucket_name_for(root)
    return name == base or (
        name.startswith(base) and _WORKER_SUFFIX.fullmatch(name[len(base) :]) is not None
    )


def remove_derived_buckets(*, root: Path) -> list[str]:
    """Empty and remove every bucket `root` derives — a path, never a name; answers what went."""
    s3 = client()
    removed: list[str] = []
    try:
        for name in list_derived_buckets():
            if not derives(root, name):
                continue
            _empty_and_remove(s3, name)
            removed.append(name)
    except (ClientError, BotoCoreError) as failure:
        raise StorageUnreadable(f"the object store refused a removal: {failure}") from failure
    return removed


def remove_foreign_buckets(names: Sequence[str], *, roots: Sequence[Path]) -> list[str]:
    """Empty and remove each named bucket still standing; `roots` licenses it, never derived."""
    if not roots:
        raise ValueError(
            "--force-foreign needs --roots <dir> — the census must have been given every place"
            " clones live"
        )
    s3 = client()
    removed: list[str] = []
    try:
        standing = set(list_derived_buckets())
        for name in names:
            if name not in standing:
                continue
            _empty_and_remove(s3, name)
            removed.append(name)
    except (ClientError, BotoCoreError) as failure:
        raise StorageUnreadable(f"the object store refused a removal: {failure}") from failure
    return removed


def _empty_and_remove(s3: Any, name: str) -> None:
    """Delete every object version and delete marker in `name`, then the bucket itself."""
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=name):
        doomed = [
            {"Key": entry["Key"], "VersionId": entry["VersionId"]}
            for entry in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
        ]
        if doomed:
            s3.delete_objects(Bucket=name, Delete={"Objects": doomed})
    s3.delete_bucket(Bucket=name)


class StorageUnreadable(RuntimeError):
    """The store would not answer the question. **Never a verdict.**

    The distinction this class exists for is the instrument checklist's, and
    `apps/core/integrations.py` makes the same one for the same reason: "I could
    not look" and "I looked and it is not there" are different answers, and an
    instrument that reports the second when the first is true is how a green
    report gets produced during an outage of the probe itself.

    Every raise site here is a call the store REFUSED or could not be asked —
    credentials, network, a permission the audit's role does not hold. An answer
    that says "there is no lifecycle configuration on this bucket" is a FACT and
    is returned as one; it does not come through here.

    `manage.py storage_audit` turns this into exit 2, which is the same code the
    gate and `manage.py integrations` use for the same meaning.
    """


def head_bucket() -> None:
    """Does this deployment's bucket answer, right now? **The live probe.**

    Raises `StorageUnreadable` when it does not, and returns `None` when it does
    — a bool would make "no bucket configured" and "the bucket refused us" the
    same answer, which is exactly the collapse this seam refuses everywhere else.
    An unconfigured deployment never reaches here: `bucket_name()` raises
    `ImproperlyConfigured` first, and the caller is expected to tell those two
    apart (`apps/files/integrations.py` does).

    `head_bucket` and not a list or a probe object, for `apps/core/health.py`'s
    reason restated: it is the cheapest call S3 has that proves reachability AND
    that this credential may see this bucket, and it writes nothing. A probe that
    uploaded a canary would fill the bucket with rubbish at the probe interval,
    forever.
    """
    name = bucket_name()
    try:
        client().head_bucket(Bucket=name)
    except (ClientError, BotoCoreError) as failure:
        raise StorageUnreadable(
            f"the object store did not answer for bucket {name!r}: {failure}"
        ) from failure


@dataclass(frozen=True)
class StoredObject:
    """One object as the bucket lists it. Metadata only — no bytes are read."""

    key: str
    size_bytes: int


def walk_objects(*, prefix: str = "") -> Iterator[StoredObject]:
    """Every object in this deployment's bucket, under `prefix`. **Unbelted, and why.**

    This is the ONE read in this module that does not call `refuse_foreign_key`,
    and the omission is the point rather than an oversight. Every other function
    here acts FOR a tenant, so a key outside that tenant's prefix means something
    upstream resolved the wrong row. This one acts for the DEPLOYMENT, on behalf
    of an operator with a shell, and the objects it most needs to find are the
    ones no tenant's prefix contains — an object under a key grammar nothing in
    this tree writes any more is precisely the orphan `storage_audit` exists to
    surface, and a belted walk could not see it.

    Nothing tenant-facing may call this: `bucket_name()` is deployment-wide, the
    result is deployment-wide, and there is no `tenant` in the signature to make
    a caller think otherwise. Its callers are the audit command and its tests.

    A generator rather than a list because a production bucket does not fit in a
    worker's memory, and the audit consumes it once.
    """
    bucket = bucket_name()
    s3 = client()
    try:
        pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for page in pages:
            for entry in page.get("Contents", []):
                yield StoredObject(key=str(entry["Key"]), size_bytes=int(entry["Size"]))
    except (ClientError, BotoCoreError) as failure:
        raise StorageUnreadable(
            f"the object store would not list bucket {bucket!r} under {prefix!r}: {failure}"
        ) from failure


#: What S3 answers when a bucket simply has no lifecycle configuration. It is an
#: error code and it is a FACT — "I looked and there is none" — which is why it
#: is named and handled rather than allowed to become a `StorageUnreadable`.
NO_LIFECYCLE_CONFIGURATION = "NoSuchLifecycleConfiguration"

#: The versioning state S3 reports while versioning is on. A bucket that has
#: never been versioned reports NOTHING at all and a suspended one reports
#: `Suspended`, which is why the posture below reads for this word rather than
#: against a list of the others.
VERSIONING_ENABLED = "Enabled"

#: A lifecycle rule S3 will actually act on. The same English word as the
#: versioning state above and a different question, so it is a different
#: constant: a rule with `Status: Disabled` is a rule somebody wrote and turned
#: off, and counting one would report a posture the bucket does not have.
RULE_ENABLED = "Enabled"


@dataclass(frozen=True)
class RetentionPosture:
    """What the bucket itself does with a deleted object. **The live half.**

    `deploy/provision.sh` SETS this posture and
    `apps/core/tests/test_archive_retention.py` reads that script as TEXT — which
    pins the two declarations to each other and says nothing whatsoever about any
    bucket. That is the whole gap this value closes: the numbers can agree
    perfectly in the repository while the deployment's bucket carries no rule
    at all, and every instrument on the tree would go on reporting an archive purged.

    **Why versioning decides whether the rule is owed.** On an UNVERSIONED bucket
    a delete is a delete, `purge_exports`' `delete_object` really removes the
    bytes, and house rule 31's `purged` is true with no lifecycle rule anywhere.
    Turn versioning on and the same call writes a delete marker and keeps the
    object as a noncurrent version forever — so the rule becomes load-bearing at
    the moment versioning is switched on, and nothing announces that moment. The
    audit is what announces it.
    """

    #: Whether the bucket keeps a version behind a delete.
    is_versioned: bool

    #: Days after which a noncurrent version is expired, or `None` when no rule
    #: says. `None` on a versioned bucket is a live hole in that posture.
    noncurrent_expiry_days: int | None

    #: Days after which an abandoned multipart upload is aborted, or `None`.
    #: Parts that are billed and invisible in every listing (`provision.sh`).
    abort_incomplete_after_days: int | None

    #: Every enabled rule's id, so a report can name what it did read.
    rule_ids: tuple[str, ...]

    @property
    def keeps_deleted_objects_forever(self) -> bool:
        """The one question this whole value exists to answer."""
        return self.is_versioned and self.noncurrent_expiry_days is None


def retention_posture() -> RetentionPosture:
    """Read the bucket's versioning and lifecycle rules. Raises when it cannot look.

    Two calls, both read-only, both `GET`s in S3's own vocabulary. An absent
    lifecycle configuration is an S3 *error code* rather than an empty document,
    so it is recognised by name and turned back into the fact it is — everything
    else the store refuses is a `StorageUnreadable`, because an audit that cannot
    read a policy must not report the policy as missing.
    """
    bucket = bucket_name()
    s3 = client()

    try:
        versioning = s3.get_bucket_versioning(Bucket=bucket)
    except (ClientError, BotoCoreError) as failure:
        raise StorageUnreadable(
            f"could not read the versioning state of bucket {bucket!r}: {failure}"
        ) from failure

    try:
        rules = list(s3.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", []))
    except ClientError as failure:
        if str(failure.response.get("Error", {}).get("Code", "")) != NO_LIFECYCLE_CONFIGURATION:
            raise StorageUnreadable(
                f"could not read the lifecycle configuration of bucket {bucket!r}: {failure}"
            ) from failure
        rules = []
    except BotoCoreError as failure:
        raise StorageUnreadable(
            f"could not read the lifecycle configuration of bucket {bucket!r}: {failure}"
        ) from failure

    enabled = [rule for rule in rules if str(rule.get("Status", "")) == RULE_ENABLED]
    return RetentionPosture(
        is_versioned=str(versioning.get("Status", "")) == VERSIONING_ENABLED,
        noncurrent_expiry_days=_first_day_count(
            enabled, "NoncurrentVersionExpiration", "NoncurrentDays"
        ),
        abort_incomplete_after_days=_first_day_count(
            enabled, "AbortIncompleteMultipartUpload", "DaysAfterInitiation"
        ),
        rule_ids=tuple(str(rule.get("ID", "")) for rule in enabled),
    )


def _first_day_count(rules: list[Any], clause: str, field: str) -> int | None:
    """The day count the first enabled rule carrying `clause` names, or `None`.

    **The first and not the smallest**, deliberately: S3 evaluates every matching
    rule and the effective window is whichever fires soonest, so a bucket with two
    disagreeing rules has a posture nobody can state in one number. Reporting the
    first one found keeps this function honest about being a reader — the audit
    prints every rule id it saw beside the number, which is what lets a person
    notice there were two.
    """
    for rule in rules:
        value = rule.get(clause, {}).get(field)
        if value is not None:
            return int(value)
    return None
