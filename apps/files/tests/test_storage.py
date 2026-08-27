"""The storage seam: what a key may say, what it may not, and a real round trip.

The unit half needs nothing running. The round-trip half runs against the compose
MinIO and is **not skipped when it is absent** on purpose: MinIO is in
`scripts/setup.sh`'s service list and in CI's wait list, so an unreachable object
store is a broken environment saying so, not a test quietly declining to prove
the thing it exists to prove.
"""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from io import StringIO, UnsupportedOperation
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from apps.core.models import Tenant
from apps.files import storage

#: What a client MUST send on a presigned PUT from this seam, and it is not a
#: convenience: both headers are inside the SigV4 signature
#: (`X-Amz-SignedHeaders=content-type;host;if-none-match`), so a PUT that omits
#: either is refused by the store with "headers present in the request which
#: were not signed" — a 400, not a lenient upload. `If-None-Match` was added as
#: the overwrite belt; this constant is where the wire contract lives for every
#: test that drives one.
UPLOAD_HEADERS = {"Content-Type": "application/pdf", "If-None-Match": storage.OVERWRITE_NOTHING}

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

    from apps.files.models import StoredFile


# --- Keys ---------------------------------------------------------------------


@pytest.mark.django_db
def test_a_key_carries_the_tenant_and_not_the_organization(
    tenant: Tenant, stored_file: StoredFile
) -> None:
    """The tenant is in the key forever; the organization deliberately is not.

    Re-parenting a branch is a row edit. If the organization were in the key, it
    would be a row edit that orphaned every object underneath it.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=3)
    assert key == f"t/{tenant.pk}/f/{stored_file.pk}/v/3"
    assert str(stored_file.organization_id) not in key
    assert tenant.slug not in key


@pytest.mark.django_db
def test_a_version_gets_its_own_key(tenant: Tenant, stored_file: StoredFile) -> None:
    """Replace is a new object, never an overwrite of an old one."""
    first = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    second = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=2)
    assert first != second


@pytest.mark.django_db
def test_every_tenants_objects_live_under_one_prefix(
    tenant: Tenant, other_tenant: Tenant, stored_file: StoredFile
) -> None:
    """The unit a prefix delete reaches, and the unit the belt below compares against."""
    assert storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1).startswith(
        storage.tenant_prefix(tenant)
    )
    assert storage.tenant_prefix(tenant) != storage.tenant_prefix(other_tenant)


# --- The belt -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_seam_refuses_another_tenants_key(tenant: Tenant, other_tenant: Tenant) -> None:
    """A signature over somebody else's key cannot be produced, even from inside the wall.

    Every signing and reaching function calls this first. It is not the wall —
    `for_tenant` and `visible_to` are — and it is the last thing standing between a
    resolved-the-wrong-row bug and a URL somebody else can fetch.
    """
    foreign = storage.version_key(tenant=other_tenant, file_pk="f", version=1)
    with pytest.raises(ValueError, match="not under"):
        storage.refuse_foreign_key(tenant=tenant, key=foreign)


@pytest.mark.django_db
@pytest.mark.parametrize("sign", ["presign_put", "presign_get"])
def test_neither_presign_will_sign_a_foreign_key(
    tenant: Tenant, other_tenant: Tenant, sign: str, settings: Any
) -> None:
    """Proven through the public functions, not only through the helper.

    A belt that is only asserted on its own helper is a belt that a later edit can
    stop calling with nothing noticing. No bucket is configured in this test and
    that is deliberate: the refusal has to land BEFORE anything talks to a store.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    foreign = storage.version_key(tenant=other_tenant, file_pk="f", version=1)
    kwargs: dict[str, Any] = {"tenant": tenant, "key": foreign}
    if sign == "presign_put":
        kwargs["content_type"] = "application/pdf"
    with pytest.raises(ValueError, match="not under"):
        getattr(storage, sign)(**kwargs)


# --- The bucket ---------------------------------------------------------------


def test_a_checkout_derives_its_own_bucket_name() -> None:
    """Shaped like a bucket name, and derived from this checkout's own path.

    The `DATABASE_NAME` derivation, for objects: two worktrees of one branch share
    a compose stack, and a bucket they both wrote `t/<tenant>/` into would make one
    gate's prefix delete take the other's objects away.
    """
    name = storage.derived_bucket_name()
    assert storage.BUCKET_NAME.match(name), name
    assert name.startswith(f"{storage.BUCKET_PREFIX}-")


def test_two_checkouts_derive_different_buckets(settings: Any, tmp_path: Any) -> None:
    """The property, planted: a different checkout path is a different bucket."""
    here = storage.derived_bucket_name()
    settings.BASE_DIR = tmp_path / "some-other-checkout"
    assert storage.derived_bucket_name() != here


def test_every_xdist_worker_gets_its_own_bucket(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bucket per parallel worker, so a prefix delete cannot reach a neighbour.

    Outside pytest-xdist `PYTEST_XDIST_WORKER` is unset and the suffix is the
    identity function — a deployment reads exactly the name it configured.
    """
    settings.AWS_STORAGE_BUCKET_NAME = "djb-fixed"
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert storage.bucket_name() == "djb-fixed"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    assert storage.bucket_name() == "djb-fixed-gw3"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw4")
    assert storage.bucket_name() == "djb-fixed-gw4"


def test_a_configured_name_wins_over_the_derivation(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 1 of the `DATABASE_NAME` precedent: a name in the environment wins.

    `PYTEST_XDIST_WORKER` is cleared rather than tolerated, because the two
    properties are separate and this test is about only one of them. Leaving it
    set made this the ONE test in the rung that passed serially and failed under
    the gate's parallel run — which is the shape of bug that gets a test marked
    flaky instead of read.
    """
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    settings.AWS_STORAGE_BUCKET_NAME = "a-named-bucket"
    assert storage.bucket_name() == "a-named-bucket"
    assert storage.derived_bucket_name() != "a-named-bucket"


def test_no_bucket_is_a_refusal_and_never_a_guess(settings: Any) -> None:
    """**No silent fallback.** An unconfigured deployment is told so, loudly.

    A seam that invented a name here would be the fourth opinion on "is object
    storage configured" — `STORAGES`, `/readyz` and this module — and the only one
    of the four that wrote anything.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    with pytest.raises(ImproperlyConfigured, match="AWS_STORAGE_BUCKET_NAME"):
        storage.bucket_name()


# --- The round trip, against the real object store ----------------------------


@pytest.mark.django_db
def test_bytes_go_up_and_come_back_on_presigned_urls_alone(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The whole contract, once, end to end: PUT on a signed URL, GET on another.

    Nothing in this test streams through Django, which is the design being proven
    rather than described. What it also proves is that `sha256_of` measures the
    bytes that really landed: the digest it returns is recomputed here from the
    same bytes, so a seam that echoed back whatever it was told would fail.
    """
    body = b"the bytes we actually hold\n" * 4096
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)

    upload = storage.presign_put(tenant=tenant, key=key, content_type="application/pdf")
    put = httpx.put(upload, content=body, headers=UPLOAD_HEADERS, timeout=30)
    assert put.status_code == 200, put.text

    described = storage.head(tenant=tenant, key=key)
    assert described.size_bytes == len(body)
    assert described.content_type == "application/pdf"

    measured = storage.sha256_of(tenant=tenant, key=key)
    assert measured.sha256 == hashlib.sha256(body).hexdigest()
    assert measured.size_bytes == len(body)

    download = storage.presign_get(tenant=tenant, key=key)
    got = httpx.get(download, timeout=30)
    assert got.status_code == 200
    assert got.content == body


@pytest.mark.django_db
def test_a_digest_is_measured_and_never_declared(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """Bytes that disagree with what a client would have declared, measured anyway.

    `verify_object` is what uses this; the property it needs from the seam is
    that the number comes from the object and from nothing else.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    storage.client().put_object(Bucket=bucket, Key=key, Body=b"tiny")
    measured = storage.sha256_of(tenant=tenant, key=key)
    assert measured.size_bytes == 4
    assert measured.sha256 == hashlib.sha256(b"tiny").hexdigest()


@pytest.mark.django_db
def test_a_prefix_delete_reaches_one_tenant_and_stops(
    tenant: Tenant, other_tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The off-ORM half of tenant close: this customer's objects, and nobody else's.

    The neighbour's object is the assertion that matters. A prefix delete that took
    one key too many would be the worst bug this app can have, and it would look
    exactly like a working one from the tenant that asked.
    """
    mine = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    theirs = storage.version_key(tenant=other_tenant, file_pk=stored_file.pk, version=1)
    client = storage.client()
    client.put_object(Bucket=bucket, Key=mine, Body=b"mine")
    client.put_object(Bucket=bucket, Key=theirs, Body=b"theirs")

    assert storage.delete_prefix(tenant=tenant) == 1

    with pytest.raises(client.exceptions.NoSuchKey):
        client.get_object(Bucket=bucket, Key=mine)
    assert client.get_object(Bucket=bucket, Key=theirs)["Body"].read() == b"theirs"


@pytest.mark.django_db
def test_an_expired_url_is_refused_by_the_store_itself(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The TTL is real, and the refusal is the store's own — no Django in that path.

    ADR files-2's posture, wire-true: an expired or tampered URL gets S3's own 403,
    un-re-dressed, because there is nothing of ours between the client and the
    bytes. The remedy is re-issuance through the audited door.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    storage.client().put_object(Bucket=bucket, Key=key, Body=b"gone in a moment")
    expired = storage.presign_get(tenant=tenant, key=key, expires_in=1)
    time.sleep(1.5)
    refused = httpx.get(expired, timeout=30)
    assert refused.status_code == 403, refused.text


@pytest.mark.django_db
def test_an_upload_url_is_unusable_without_the_headers_it_was_signed_for(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The belt is inside the signature, so it is not something a client may skip.

    `If-None-Match: *` was added to the presigned PUT (ADR files-2). SigV4 covers
    the header set, so a client that drops it is not making a lenient upload — it
    is presenting a signature over a request it did not make, and the store says
    so before any byte lands.

    Proven in BOTH directions in this module: with the headers the upload works
    (the round-trip test above), without them it is refused here, and the belt
    itself refuses an overwrite below.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    upload = storage.presign_put(tenant=tenant, key=key, content_type="application/pdf")

    bare = httpx.put(
        upload, content=b"no belt", headers={"Content-Type": "application/pdf"}, timeout=30
    )

    assert bare.status_code == 400, bare.text
    assert "not signed" in bare.text
    with pytest.raises(storage.client().exceptions.ClientError):
        storage.head(tenant=tenant, key=key)


@pytest.mark.django_db
def test_a_leaked_upload_url_cannot_overwrite_what_already_landed(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """**The belt, wire-asserted against MinIO** (ADR files-2, criterion 6).

    The threat is precise: an upload URL is a fifteen-minute write credential for
    one key, and a version's digest is quoted by audit rows, export manifests and
    every presigned GET already issued for it. If a leaked pre-finalize URL could
    be replayed after the bytes landed, an audited digest would stop being true
    about the object it names — silently, because nothing in this platform sits
    in that request path to notice.

    So the same URL is replayed here, with different bytes, after the first PUT
    succeeded. The store refuses it — 412, its own answer to a failed conditional
    write — and the object still holds the first bytes.

    **The belt is never the fence.** The service-side refusal (an upload URL is
    minted only for a `PENDING` version) stands on a backend that honours no
    conditional write at all; this closes the window between the object landing
    and the row learning about it, which is the one window that refusal cannot
    see.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    upload = storage.presign_put(tenant=tenant, key=key, content_type="application/pdf")

    first = httpx.put(upload, content=b"the real document", headers=UPLOAD_HEADERS, timeout=30)
    assert first.status_code == 200, first.text

    replayed = httpx.put(upload, content=b"somebody else's", headers=UPLOAD_HEADERS, timeout=30)

    assert replayed.status_code == 412, replayed.text
    assert (
        storage.sha256_of(tenant=tenant, key=key).sha256
        == hashlib.sha256(b"the real document").hexdigest()
    )


@pytest.mark.django_db
def test_put_bytes_will_not_overwrite_an_object_either(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The generation path carries the same condition as the upload path.

    `store_bytes` allocates a fresh ordinal and so writes a key nothing has ever
    written. A PUT that succeeded at an occupied key would mean the version
    allocator handed one ordinal out twice — better heard here, as a failed
    store, than discovered later as a rewritten digest.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=7)
    storage.put_bytes(tenant=tenant, key=key, content=b"rendered", content_type="application/pdf")

    with pytest.raises(storage.client().exceptions.ClientError) as refused:
        storage.put_bytes(
            tenant=tenant, key=key, content=b"rendered again", content_type="application/pdf"
        )

    assert refused.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
    assert storage.sha256_of(tenant=tenant, key=key).size_bytes == len(b"rendered")


# --- One object, deleted ------------------------------------------------------


@pytest.mark.django_db
def test_delete_object_takes_one_key_and_leaves_every_neighbour(
    tenant: Tenant, other_tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """Proved the way the prefix delete is: **the survivors are the assertion.**

    A single-object delete that took one key too many would look exactly like a
    working one from the caller that asked. So three objects go in — the target,
    this tenant's OTHER version, and a neighbouring tenant's — and only the
    target goes away.
    """
    target = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    sibling = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=2)
    neighbour = storage.version_key(tenant=other_tenant, file_pk=stored_file.pk, version=1)
    client = storage.client()
    for key, body in ((target, b"go"), (sibling, b"stay"), (neighbour, b"theirs")):
        client.put_object(Bucket=bucket, Key=key, Body=body)

    storage.delete_object(tenant=tenant, key=target)

    with pytest.raises(client.exceptions.ClientError) as absent:
        storage.head(tenant=tenant, key=target)
    assert absent.value.response["ResponseMetadata"]["HTTPStatusCode"] == 404
    assert storage.head(tenant=tenant, key=sibling).size_bytes == len(b"stay")
    assert client.get_object(Bucket=bucket, Key=neighbour)["Body"].read() == b"theirs"


@pytest.mark.django_db
def test_deleting_a_key_that_is_not_there_is_a_no_op(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """Idempotent, and it is the store's own answer rather than a swallowed error.

    The caller is a purge — `delete_object` is what a `PURGED` declaration will
    stand on — and a purge is retried. A second attempt that raised would make a
    replay indistinguishable from a failure, and the remedy for that is always
    the same wrong one: catch everything.
    """
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    storage.client().put_object(Bucket=bucket, Key=key, Body=b"once")

    storage.delete_object(tenant=tenant, key=key)
    storage.delete_object(tenant=tenant, key=key)
    storage.delete_object(
        tenant=tenant, key=storage.version_key(tenant=tenant, file_pk="never-existed", version=1)
    )


@pytest.mark.django_db
def test_delete_object_refuses_another_tenants_key(
    tenant: Tenant, other_tenant: Tenant, settings: Any
) -> None:
    """The belt, on the one function whose mistake is not recoverable.

    No bucket is configured here on purpose: the refusal has to land before
    anything reaches a store, because a delete that got as far as the wire has
    already happened.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    foreign = storage.version_key(tenant=other_tenant, file_pk="f", version=1)
    with pytest.raises(ValueError, match="not under"):
        storage.delete_object(tenant=tenant, key=foreign)


# --- A body that never fits in memory -----------------------------------------


class _OneShot:
    """A body that can be read once and never rewound. The shape being refused.

    Modelled on a pipe rather than on a missing method: `seekable()` answers
    `False` and `seek` raises the error a real unseekable stream raises, so the
    refusal being proved is the one a caller would actually meet. (It satisfies
    `storage.Rewindable` structurally, which is the point — the type says what
    the seam CALLS, and whether a body can really rewind is a runtime fact.)
    """

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        chunk, self._payload = self._payload, b""
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        raise UnsupportedOperation("underlying stream is not seekable")

    def tell(self) -> int:
        return 0

    def seekable(self) -> bool:
        return False


#: The largest single read this seam may ever ask a body for. The SDK chooses its
#: own chunk — one mebibyte, measured against botocore 1.43 — and what is being
#: asserted is that the body goes over in SOME bounded piece rather than whole.
#: Four times the observed chunk, so an SDK that later reads twice as much at a
#: time is not a false failure, while a seam that read the body WHOLE — which is
#: what `store_bytes(content=body.read())` does — still is, by an order of
#: magnitude.
STREAMED_READ_CEILING = 4 * 1024 * 1024


class _WatchedBody:
    """A spooled body that remembers the largest single `read` anybody asked of it.

    The memory posture, measured deterministically rather than sampled. A seam
    that materialised the body — `put_bytes(content=body.read())` — takes it in
    ONE read, and the largest read is then the whole body; a seam that streams
    takes it in the SDK's own chunks. `tracemalloc` was tried first and rejected:
    its peak is dominated by whatever the process had not yet allocated (a boto3
    client, Django's own machinery), so the same code measured differently
    depending on what ran before it — a flaky test about a property that is not.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.largest_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk: bytes = self._inner.read(size)
        self.largest_read = max(self.largest_read, len(chunk))
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        return int(self._inner.seek(offset, whence))

    def tell(self) -> int:
        return int(self._inner.tell())

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True


def _spooled(chunk: bytes, times: int) -> tuple[Any, str, int]:
    """A spooled body of `chunk * times`, with the digest and size the test expects.

    Built the way an archive builder builds one — written in pieces into a
    `SpooledTemporaryFile` that spills to disk — so nothing in this module ever
    holds the whole body either, and the expected digest is accumulated as it
    goes rather than computed over a `bytes` the test kept.
    """
    spool = SpooledTemporaryFile(max_size=64 * 1024)
    digest = hashlib.sha256()
    for _ in range(times):
        spool.write(chunk)
        digest.update(chunk)
    spool.seek(0)
    return spool, digest.hexdigest(), len(chunk) * times


@pytest.mark.django_db
def test_a_streamed_store_measures_the_bytes_it_actually_sent(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The digest comes off the stream, and the store agrees with it.

    The body is deliberately larger than one read — the SDK reads a seekable body
    more than once (a length probe, the payload signature over plain HTTP, then
    the transmission), so a hash that did not restart with the body would return
    the digest of three copies. It returns the digest of one, and `sha256_of`
    re-measuring the object from the store says the same thing.
    """
    body, expected, size = _spooled(b"archive-bytes" * 1024, 900)

    measured = storage.store_stream(
        tenant=tenant,
        key=storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1),
        body=body,
        content_type="application/zip",
    )

    assert measured.size_bytes == size
    assert measured.sha256 == expected
    from_the_store = storage.sha256_of(
        tenant=tenant, key=storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    )
    assert from_the_store.sha256 == expected
    assert from_the_store.size_bytes == size


@pytest.mark.django_db
def test_a_streamed_store_never_holds_the_whole_body(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """**The posture, measured rather than asserted about.**

    The whole point of streaming is that an archive built into a spooled file does not
    materialise in RAM on its way to the store. The body counts the largest read
    it was ever asked for: a seam that took it whole would show one read the size
    of the body, and this one shows the SDK's own chunks.
    """
    spool, expected, size = _spooled(b"archive-bytes" * 1024, 900)
    body = _WatchedBody(spool)
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)

    measured = storage.store_stream(
        tenant=tenant, key=key, body=body, content_type="application/zip"
    )

    assert measured.sha256 == expected
    assert size > STREAMED_READ_CEILING
    assert 0 < body.largest_read <= STREAMED_READ_CEILING, (
        f"read {body.largest_read} of {size} at once"
    )


@pytest.mark.django_db
def test_a_streamed_store_will_not_overwrite_what_is_already_there(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """The same `If-None-Match: *` belt the other two write paths carry."""
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    first, _, _ = _spooled(b"first", 10)
    storage.store_stream(tenant=tenant, key=key, body=first, content_type="application/zip")

    again, _, _ = _spooled(b"second", 10)
    with pytest.raises(storage.client().exceptions.ClientError) as refused:
        storage.store_stream(tenant=tenant, key=key, body=again, content_type="application/zip")

    assert refused.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412


@pytest.mark.django_db
def test_a_streamed_store_refuses_a_foreign_key(
    tenant: Tenant, other_tenant: Tenant, settings: Any
) -> None:
    """Before the bucket is read, like every other reaching function here."""
    settings.AWS_STORAGE_BUCKET_NAME = ""
    body, _, _ = _spooled(b"nope", 4)
    with pytest.raises(ValueError, match="not under"):
        storage.store_stream(
            tenant=tenant,
            key=storage.version_key(tenant=other_tenant, file_pk="f", version=1),
            body=body,
            content_type="application/zip",
        )


@pytest.mark.django_db
def test_a_body_that_cannot_be_rewound_is_refused_with_the_remedy(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """An iterator is refused HERE rather than spooled behind the caller's back.

    The SDK needs a length and — over plain HTTP — a payload signature, so it
    rewinds the body; a one-shot iterator cannot answer that. Spooling it inside
    this seam would silently decide how much memory the caller's body may use,
    which is precisely the decision the streaming seam exists to leave with the caller.
    """
    with pytest.raises(ValueError, match="seekable"):
        storage.store_stream(
            tenant=tenant,
            key=storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1),
            body=_OneShot(b"not rewindable"),
            content_type="application/zip",
        )


# --- The bucket, made ---------------------------------------------------------


@contextmanager
def _a_bucket_named(name: str) -> Iterator[None]:
    """A scratch bucket that is REMOVED whether the body raises or not.

    The `bucket` fixture cannot serve these tests: their subject is what happens
    when the bucket does NOT exist yet, which is precisely what that fixture
    provides.

    **Never the checkout's own name**, and that is not a detail — every caller
    below moves `settings.BASE_DIR` first so the derivation answers something
    else. `derived_bucket_name()` carries no xdist suffix (it is the name a
    CHECKOUT configures, not the one a worker tests against), so a test that
    created and then deleted the real derivation would take the bucket `.env`
    names out from under `/readyz` and under every other worker's `apps/exports`
    test at the same time — which is exactly what happened once: 30 `NoSuchBucket`
    failures across two other apps.
    """
    try:
        yield
    finally:
        client = storage.client()
        try:
            client.delete_bucket(Bucket=name)
        except client.exceptions.ClientError:
            pass


@pytest.mark.django_db
def test_setups_door_creates_the_bucket_and_saying_so_twice_is_free(
    settings: Any, tmp_path: Any
) -> None:
    """Half of the seam: a checkout asks for a bucket and gets one.

    Idempotent because setup is re-run — `scripts/setup.sh`'s whole promise —
    and a second run must be a no-op rather than a `BucketAlreadyOwnedByYou`
    from MinIO.

    `BASE_DIR` is moved so the derivation answers a name no other process holds
    (see `_a_bucket_named`): this test destroys the bucket it made.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    settings.BASE_DIR = tmp_path / "a-checkout-of-its-own"
    expected = storage.derived_bucket_name()
    with _a_bucket_named(expected):
        first = storage.create_bucket_if_absent()
        second = storage.create_bucket_if_absent()

        assert first == second == expected
        # It is really there: a head that raised would be an absent bucket.
        assert storage.client().head_bucket(Bucket=expected)


@pytest.mark.django_db
def test_setups_door_honours_a_configured_name_over_the_derivation(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DATABASE_NAME`'s rule 1, on the object store: a name in the environment wins.

    A deployment pointing at a real S3 bucket must have THAT bucket checked, not
    a derivation invented over the top of it — which would be setup silently
    re-homing a production deployment's objects.

    The xdist suffix is cleared for the same reason
    `test_a_configured_name_wins_over_the_derivation` clears it: this answers
    "what should the checkout configure", and a `-gw0` in `.env` would pin every
    process to one worker's bucket.
    """
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    settings.AWS_STORAGE_BUCKET_NAME = "djb-a-named-bucket-1f2e3d"
    with _a_bucket_named("djb-a-named-bucket-1f2e3d"):
        assert storage.create_bucket_if_absent() == "djb-a-named-bucket-1f2e3d"
        assert storage.derived_bucket_name() != "djb-a-named-bucket-1f2e3d"


@pytest.mark.django_db
def test_the_command_prints_the_name_alone_because_a_script_reads_it(
    settings: Any, tmp_path: Any
) -> None:
    """`scripts/setup.sh` captures stdout into `AWS_STORAGE_BUCKET_NAME`.

    So stdout is DATA — one line, the name, nothing else — and everything a human
    reads goes to stderr. A command that greeted its reader on stdout would put
    the greeting in `.env`.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    settings.BASE_DIR = tmp_path / "a-checkout-of-its-own"
    expected = storage.derived_bucket_name()
    out, err = StringIO(), StringIO()
    with _a_bucket_named(expected):
        call_command("ensure_bucket", stdout=out, stderr=err)

    assert out.getvalue().strip() == expected
    assert out.getvalue().count("\n") == 1
    assert expected in err.getvalue()
