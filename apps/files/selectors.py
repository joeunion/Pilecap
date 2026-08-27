"""Reads for the files app. **Nothing here writes, and nothing here mints a URL.**

House rule 12: reads and writes are separate. `services.py` never returns a
queryset for display, and this module never calls `storage.presign_*` — a
presigned URL is a credential, minting one is an audited act, and an audited act
is a `@service`. What this module does is answer *which rows may this hat see*,
once, so that both doors and every service reach a `StoredFile` or a
`FileVersion` the same way.

**Every read is `for_tenant(...).visible_to(...)`** — both halves, always, because
both models are org-scoped (house rule 24). `for_tenant` answers *whose data*;
`visible_to` answers *which part of their network*; both fail closed, so an
unresolved tenant or an unresolved hat reads an empty table rather than the table.

**Every refusal here is `NotFound`, for a row in another tenant, a row in a
sibling branch, a row one level up the tree, and a row that never existed alike**
(ADR files-2 § "Presigned URLs"). The reason is sharper for this app than for
most: a caller asking for a download URL is asking us to sign something, and a
refusal that told not-there from not-yours apart would make the issuance door an
oracle confirming that somebody's document exists.

**Archived documents are excluded from the list and reachable by id** (ADR
files-2 § Doors: "current-version metadata, archived excluded"). Those are not in
tension: archiving takes a document out of everybody's working set, and it does
not un-say that the document exists to whoever holds a link to it, has an audit
row naming it, or wants to know why their id stopped appearing. `list_files` is
the working set; `get_file` is the record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet
from apps.files.models import FileVersion, StoredFile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from uuid import UUID

    from apps.core.models import Tenant


def list_files(*, tenant: Tenant | None, org: Any = None) -> ScopedQuerySet[StoredFile]:
    """The live documents this hat may see, newest first by the caller's ordering.

    `select_related("organization", "uploaded_by")` is the contract rather than an
    optimisation: the read shape publishes the organization the document belongs
    to and who filed it, so without it a page of fifty is a hundred and one
    queries. `tests/test_api.py::LIST_QUERY_BUDGET` is what turns removing it into
    a failure rather than a slow page.

    **Archived documents are absent.** See the module docstring: this is the
    working set, and `get_file` is the record.
    """
    return (
        StoredFile.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(archived_at__isnull=True)
        .select_related("organization", "uploaded_by")
    )


def get_file(*, tenant: Tenant | None, file_id: UUID, org: Any = None) -> StoredFile:
    """One document this hat may see, archived or not, or `NotFound`.

    Deliberately NOT built on `list_files`: an archived document is still a
    document, and a caller holding its id — from an audit row, from an event
    payload, from a link somebody sent them — gets the record rather than a
    refusal that would read as "this never existed".
    """
    file = (
        StoredFile.objects.for_tenant(tenant)
        .visible_to(org)
        .select_related("organization", "uploaded_by")
        .filter(pk=file_id)
        .first()
    )
    if file is None:
        raise NotFound()
    return file


def list_versions(
    *, tenant: Tenant | None, file: StoredFile, org: Any = None
) -> ScopedQuerySet[FileVersion]:
    """Every version of one document, in the same scoped read the document was.

    Scoped again rather than reached through `file.versions`: the caller handed a
    `StoredFile` somebody else fetched, and a reverse accessor would inherit that
    fetch's opinion of the boundary instead of re-asserting it. It costs the same
    index and it means this read is one a rule-24 scan can see.
    """
    return (
        FileVersion.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(file=file)
        .select_related("uploaded_by")
    )


def get_version(
    *, tenant: Tenant | None, file: StoredFile, version: int, org: Any = None
) -> FileVersion:
    """One version of one document, by its ordinal, or `NotFound`."""
    row = list_versions(tenant=tenant, file=file, org=org).filter(version=version).first()
    if row is None:
        raise NotFound()
    return row


def get_downloadable_version(
    *, tenant: Tenant | None, file: StoredFile, version: int | None, org: Any = None
) -> FileVersion:
    """The version an issuance would sign for — **one gate, both doors**.

    `version=None` means "whatever a reader who names none gets", which is
    `file.current_version` and is `0` while nothing has finalized. Naming an
    ordinal pins it: **a URL issued for v2 serves v2's bytes after v3 lands**,
    because a version's key is its own and promotion never rewrites one.

    Three refusals collapse into one, and that is the point: a version that
    does not exist, a version whose bytes have not landed yet (`PENDING` — there
    is nothing at that key to sign for), and a document with no current version at
    all are all `not_found`. A caller holding an id learns "there are no bytes
    here" and cannot tell which of the three it was, which is the same answer
    somebody outside the tenant gets.

    It lives here rather than in each door because `api.py` and `mcp.py` both
    import it: the two doors then cannot come to disagree about when a version is
    signable, which is the class of disagreement no value-by-value parity test
    would catch.
    """
    wanted = file.current_version if version is None else version
    if wanted <= 0:
        raise NotFound()
    row = get_version(tenant=tenant, file=file, version=wanted, org=org)
    if row.status != FileVersion.Status.STORED:
        raise NotFound()
    return row
