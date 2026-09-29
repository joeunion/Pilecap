"""The seam's one server-side stream: an object's bytes, a chunk at a time.

`storage.iter_object` exists for a Temporal activity's own parser — an import
validating a file row by row — and never for a door. What it owes that caller is
four properties, each driven against the real object store (the `bucket` fixture):
the chunks re-join to exactly the bytes that were stored and hash to what
`sha256_of` measures; another tenant's key is refused by the same belt every other
function here wears; a missing object raises instead of reading as an empty file;
and a caller that stops early releases the body rather than leaking a connection.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest
from botocore.exceptions import ClientError

from apps.files import storage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant
    from apps.files.models import StoredFile

pytestmark = pytest.mark.django_db

BODY = b"id,name\n1,first\n2,second\n3,third\n"


def _put(tenant: Tenant, stored_file: StoredFile, bucket: str) -> str:
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=1)
    storage.client().put_object(Bucket=bucket, Key=key, Body=BODY)
    return key


def test_the_chunks_rejoin_to_the_stored_bytes_and_their_digest(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """Several chunks, not one: the chunk size is smaller than the object."""
    key = _put(tenant, stored_file, bucket)

    chunks = list(storage.iter_object(tenant=tenant, key=key, chunk=8))

    assert len(chunks) > 1
    assert all(len(piece) <= 8 for piece in chunks)
    assert b"".join(chunks) == BODY
    measured = storage.sha256_of(tenant=tenant, key=key)
    assert hashlib.sha256(b"".join(chunks)).hexdigest() == measured.sha256


def test_another_tenants_key_is_refused_by_the_seams_own_belt(
    tenant: Tenant, other_tenant: Tenant
) -> None:
    """The same refusal `refuse_foreign_key` raises — at the call, before any read."""
    foreign = storage.version_key(tenant=other_tenant, file_pk="f", version=1)

    with pytest.raises(ValueError, match="not under"):
        storage.iter_object(tenant=tenant, key=foreign)


def test_a_missing_object_raises_rather_than_reading_as_empty(
    tenant: Tenant, stored_file: StoredFile, bucket: str
) -> None:
    """No object at the key is an error at the call site, never an empty iterator."""
    key = storage.version_key(tenant=tenant, file_pk=stored_file.pk, version=9)

    with pytest.raises(ClientError):
        storage.iter_object(tenant=tenant, key=key)


def test_a_caller_that_stops_early_releases_the_body(
    tenant: Tenant, stored_file: StoredFile, bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `break` after one chunk closes the body — the connection goes back."""
    key = _put(tenant, stored_file, bucket)
    real = storage.client()
    closed: list[bool] = []

    class Spy:
        """The real client, with the body's `close` recorded."""

        def get_object(self, **kwargs: Any) -> Any:
            answered = real.get_object(**kwargs)
            body = answered["Body"]
            original = body.close

            def close() -> None:
                closed.append(True)
                original()

            body.close = close
            return answered

        def __getattr__(self, name: str) -> Any:
            return getattr(real, name)

    monkeypatch.setattr(storage, "client", Spy)

    chunks = storage.iter_object(tenant=tenant, key=key, chunk=4)
    assert closed == [], "an iterator nobody has read holds no body"
    for piece in chunks:
        assert piece == BODY[:4]
        break
    chunks.close()

    assert closed == [True]
