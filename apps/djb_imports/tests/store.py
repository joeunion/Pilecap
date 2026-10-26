"""The object store as a dict for the import tests, and one CSV filed through the files seam."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

import pytest

from apps.core.actor import Actor
from apps.files import storage as files_storage
from apps.files.models import FileVersion
from apps.files.services import store_bytes

CSV = "text/csv"


@pytest.fixture
def memory_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """The object store as a dict, behind the seam's own names and belt."""
    objects: dict[str, bytes] = {}

    def put_bytes(*, tenant: Any, key: str, content: bytes, content_type: str) -> None:
        files_storage.refuse_foreign_key(tenant=tenant, key=key)
        objects[key] = content

    def sha256_of(*, tenant: Any, key: str) -> files_storage.DigestedObject:
        files_storage.refuse_foreign_key(tenant=tenant, key=key)
        body = objects[key]
        return files_storage.DigestedObject(
            sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body)
        )

    def iter_object(
        *, tenant: Any, key: str, chunk: int = files_storage.DIGEST_CHUNK_BYTES
    ) -> Iterator[bytes]:
        files_storage.refuse_foreign_key(tenant=tenant, key=key)
        body = objects[key]
        for start in range(0, len(body), chunk):
            yield body[start : start + chunk]

    monkeypatch.setattr(files_storage, "put_bytes", put_bytes)
    monkeypatch.setattr(files_storage, "sha256_of", sha256_of)
    monkeypatch.setattr(files_storage, "iter_object", iter_object)
    return objects


def stored_csv(
    actor: Actor, text: str | bytes, *, filename: str = "widgets.csv", content_type: str = CSV
) -> FileVersion:
    """File one CSV as a document the actor owns, through the files seam's service."""
    assert actor.tenant is not None
    content = text.encode() if isinstance(text, str) else text
    return store_bytes(
        tenant=actor.tenant,
        actor=actor,
        filename=filename,
        content_type=content_type,
        content=content,
        purpose="import",
    )
