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

from collections.abc import Callable

import pytest

from apps.djb_imports import activities as import_activities
from apps.djb_imports.models import Import
from apps.djb_imports.tests.store import memory_store as memory_store
from apps.djb_imports.types import CheckImport
from apps.workflows import context as workflow_context


@pytest.fixture
def planted_importer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget importer, where `core.verbs.hook("importers")` looks for it."""
    from apps.djb_imports.tests import planted  # it reaches the worked example, absent on a product

    planted.plant(monkeypatch)


@pytest.fixture
def run_check(monkeypatch: pytest.MonkeyPatch) -> Callable[[Import], Import]:
    """Run the REAL check activity over one staged run, under the headers its start would carry.

    `close_old_connections` is stilled: in this test's transaction it would close the test's own.
    """
    monkeypatch.setattr(import_activities, "close_old_connections", lambda: None)

    def check(run: Import) -> Import:
        tokens = workflow_context.set_principal(
            tenant_id=str(run.tenant_id),
            user_id=str(run.requested_by_id),
            org_id=str(run.organization_id),
        )
        try:
            import_activities.check_import(CheckImport(import_id=str(run.pk)))
        finally:
            workflow_context.reset_principal(tokens)
        return Import.objects.get(pk=run.pk)

    return check


#: Five rows, the third one refused by the row schema (an empty name).
FIVE_ROWS_ONE_BAD = (
    "name,notes\r\n"
    "Alpha,first\r\n"
    "Bravo,second\r\n"
    ",third has no name\r\n"
    "Delta,fourth\r\n"
    "Echo,fifth\r\n"
)
