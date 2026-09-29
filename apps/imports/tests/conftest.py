"""The world every import test is measured against.

Two things are doubled here and both are the OBJECT STORE, never the app under
test:

* **`memory_store`** stands in for the three `files.storage` calls an import
  reaches — `put_bytes` and `sha256_of` (which `files.services.store_bytes`
  makes to file the CSV) and `iter_object`, the server-side stream the import's
  activities read the file through. A dict keyed by the real key the real
  `version_key` built, belted by the real `refuse_foreign_key`. It keeps these
  tests off MinIO, so they run in the rung's own `--loop` rather than being
  derived into the slow tier.
* **`iter_object` is doubled to the seam's own contract** — the belt first,
  the bytes in `chunk`-sized pieces — so the dict above stands in for the
  bucket end to end. Tests only; the kill drive reads through the real one.

Everything else is real: the files services that file the CSV, the imports
services, the planted importer calling the example's own services, and the
audit rows all of them write.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from apps.core.actor import Actor
from apps.files import storage as files_storage
from apps.files.models import FileVersion
from apps.files.services import store_bytes
from apps.imports import activities as import_activities
from apps.imports.models import Import
from apps.imports.tests import planted
from apps.imports.types import CheckImport

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


@pytest.fixture
def planted_importer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget importer, where `core.verbs.hook("importers")` looks for it."""
    planted.plant(monkeypatch)


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


#: Five rows, the third one refused by the row schema (an empty name).
FIVE_ROWS_ONE_BAD = (
    "name,notes\r\n"
    "Alpha,first\r\n"
    "Bravo,second\r\n"
    ",third has no name\r\n"
    "Delta,fourth\r\n"
    "Echo,fifth\r\n"
)


@pytest.fixture
def run_check(monkeypatch: pytest.MonkeyPatch) -> Callable[[Import], Import]:
    """Run the REAL check activity over one staged run, in this test's transaction.

    The activity reads the tenant, the person and the hat off the workflow's
    headers; here there is no workflow, so `workflow_context` answers what the
    headers of the run `create_import` started would have carried. Everything
    below it — the read through the seam, the parse, the preview service — is
    the shipped code. `close_old_connections` is stilled because inside this
    test's transaction it would close the connection the test is holding; on a
    worker thread it is exactly right, and `test_workflows.py` drives the same
    activity, connections and all, on a real worker.
    """
    monkeypatch.setattr(import_activities, "close_old_connections", lambda: None)

    def check(run: Import) -> Import:
        monkeypatch.setattr(
            import_activities,
            "workflow_context",
            lambda: (run.tenant, str(run.requested_by_id), run.organization),
        )
        import_activities.check_import(CheckImport(import_id=str(run.pk)))
        return Import.objects.get(pk=run.pk)

    return check
