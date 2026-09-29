"""The HTTP door onto imports: stage a file, read the preview, apply it.

Every read goes through `selectors.py` (both halves of the scope, every time),
every write through `services.py`, and no route says a status code of its own
choosing except the two a stage can answer with — `201` for a new run and `200`
for the run these bytes already had.
"""

# NOTE: no `from __future__ import annotations` — ninja builds a Pydantic model
# out of each route's signature at import time (`apps/exports/api.py` says why).

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
from apps.imports.models import Import, ImportRow
from apps.imports.schemas import (
    ImportFilter,
    ImportIn,
    ImportOut,
    ImportRowOut,
    ImportStagedOut,
)
from apps.imports.selectors import get_import, get_import_source, list_import_rows, list_imports
from apps.imports.services import apply_import, cancel_import, create_import

PREFIX = "imports"

#: What `?ordering=` may name on the list, and nothing else.
ORDERING = ("created_at", "updated_at", "status")

TAGS = {
    "imports": Tag(
        "Imports",
        "Bringing rows in from a CSV file. Stage a file you have uploaded, read the "
        "preview of what it would do — every row checked, nothing written — and apply "
        "it. Rows the preview refused are listed with the reason and skipped; the rest "
        "apply. Staging the same file twice gives you the same import.",
        plane="everyday",
        plane_note=(
            "bringing rows in from a CSV file: stage it, read the preview, apply it. "
            "Everyday rather than administrative, because an import makes exactly the rows "
            "you could make one at a time — and it asks, for every row, the same permission "
            "making that row by hand would."
        ),
    ),
}

router = Router(tags=["imports"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as; no tenant is refused, never guessed."""
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


def staged_out(run: Import, created: bool) -> ImportStagedOut:
    """The staging answer — the run, and whether this call made it. Both doors."""
    return ImportStagedOut.model_validate(
        {**ImportOut.from_orm(run).model_dump(), "created": created}
    )


@router.get("/", response=list[ImportOut], url_name="import-list")
@paginate(CursorPagination)
def list_imports_route(
    request: TenantRequest,
    filters: Query[ImportFilter],
    ordering: str = "-created_at",
) -> QuerySet[Import]:
    """List imports

    List the imports your organization has staged, newest first.

    **Narrow** with `status` (one of `checking`, `previewed`, `importing`,
    `imported` or `failed`) and `kind`, each an exact match. **Sort** with
    `ordering`: `created_at`, `updated_at` or `status`, optionally prefixed with
    `-`; the default is `-created_at`.

    **Pages** are `?cursor=` and `?limit=`; the body is `{"items": [...],
    "has_more": ..., "next_cursor": ...}`, and `count` is `null` unless you send
    `?include_count=true`.

    You see the imports of the organization you are acting as — the `X-Org`
    header, or your default one — and of every organization beneath it.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization, or your role does not include reading imports here.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    runs: QuerySet[Import] = list_imports(
        tenant=request.tenant, org=request.org, actor=actor_from_request(request)
    )
    runs = filters.filter(runs)
    return ordered_by(runs, ordering, allowed=ORDERING, default="-created_at")


@router.post("/", response={200: ImportStagedOut, 201: ImportStagedOut}, url_name="import-create")
def create_import_route(request: TenantRequest, payload: ImportIn) -> Status[ImportStagedOut]:
    """Stage an import

    Stage a CSV file you have already uploaded, as rows of one `kind`.

    Answers `201` with a new import in `checking`, and `created: true`. The file
    is then checked in the background: every row is validated and matched
    against what you already have, and nothing is written. When `status` is
    `previewed`, `counts` says how many rows would be created, updated or
    refused, and `GET /api/v1/imports/{id}/rows/` lists them — with the reason
    for every refused row. Nothing happens to your data until you apply it.

    **Staging the same file again returns the same import** — `200` and
    `created: false` — for as long as that import has not failed. The file is
    recognized by its contents, not its name. An `idempotency_key` you send is
    honoured the same way.

    The first row of the file is its header and must name the columns this kind
    of import reads; the file must be UTF-8 CSV with at most 10,000 rows. A file
    that is not is not refused here: the import is staged and then ends
    `failed`, with `failure.code` `import_invalid` saying what was wrong.

    Refusals you can get here:

    * `400 invalid` — no importer is declared for `kind`, or the document has no
      stored version yet.
    * `422 invalid_body` — the body carried a field this endpoint does not accept.
    * `403 forbidden` — you may not import here, or you may not create rows of
      this `kind` — importing them needs the same permission as creating one.
    * `404 not_found` — `file_id` names no document you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    version = get_import_source(
        tenant=tenant, file_id=payload.file_id, org=request.org, actor=actor
    )
    run, created = create_import(
        tenant=tenant,
        actor=actor,
        kind=payload.kind,
        file_version=version,
        idempotency_key=payload.idempotency_key,
    )
    return Status(201 if created else 200, staged_out(run, created))


@router.get("/{import_id}/", response=ImportOut, url_name="import-detail")
def retrieve_import(request: TenantRequest, import_id: UUID) -> Import:
    """Retrieve an import

    One import, with where it has got to and what it found.

    `status` moves `checking` → `previewed` → `importing` → `imported`, or ends
    `failed`. `counts` is the preview's (`create`, `update`, `refused`) until
    the import is applied, and what actually happened (`create`, `update`,
    `unchanged`, `refused`) after. `apply_writes` is how many rows write: will,
    then did. `failure` is the reason a failed import ended, as a refusal body.

    An import belonging to an organization you cannot see answers `404
    not_found`, the same answer an id that names nothing gets.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting
      organization, or your role does not include reading imports here.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_import(
        tenant=request.tenant,
        import_id=import_id,
        org=request.org,
        actor=actor_from_request(request),
    )


@router.get("/{import_id}/rows/", response=list[ImportRowOut], url_name="import_rows-list")
@paginate(CursorPagination)
def list_import_rows_route(
    request: TenantRequest, import_id: UUID, outcome: str | None = None
) -> QuerySet[ImportRow]:
    """List an import's rows

    The rows of one import's file, in file order, with what happened to each.

    `outcome_preview` is what the preview said (`create`, `update` or
    `refused`); `outcome` is what the apply did (`created`, `updated`,
    `unchanged` or `refused`) and is empty until then. `refusal` says why a
    refused row was refused — `errors` names the columns.

    Narrow with `?outcome=`: `?outcome=refused` lists the refused rows before
    and after the apply. Paged like every list here.

    Refusals you can get here:

    * `403 forbidden` — your role does not include reading imports here.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor = actor_from_request(request)
    run = get_import(tenant=request.tenant, import_id=import_id, org=request.org, actor=actor)
    rows: QuerySet[ImportRow] = list_import_rows(
        tenant=request.tenant, import_=run, org=request.org, actor=actor, outcome=outcome
    )
    return rows


@router.post("/{import_id}/apply/", response=ImportOut, url_name="import-apply")
@refuses("conflict", "forbidden", "import_invalid", "not_found")
def apply_import_route(request: TenantRequest, import_id: UUID) -> Import:
    """Apply an import

    Apply a previewed import: every row the preview accepted is written, and
    every row it refused is skipped and stays listed with its reason.

    Answers the import in `importing`; poll it until `imported`. Each row is
    checked again as it is written — your permission to create this kind of
    row, and the row's values — so a row can still end `refused` if something
    changed since the preview. Pressing apply again answers the same import and
    writes nothing twice.

    Refusals you can get here:

    * `409 conflict` — the import is still being checked, or it ended without a
      preview (it failed or was cancelled); stage the file again.
    * `400 import_invalid` — the import failed because the file was refused
      whole; `errors` says what was wrong with it.
    * `403 forbidden` — you may not apply imports here, or may not create rows
      of this kind.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    run = get_import(tenant=tenant, import_id=import_id, org=request.org, actor=actor)
    return apply_import(tenant=tenant, actor=actor, import_=run)


@router.post("/{import_id}/cancel/", response=ImportOut, url_name="import-cancel")
@refuses("conflict", "forbidden", "not_found")
def cancel_import_route(request: TenantRequest, import_id: UUID) -> Import:
    """Cancel an import

    Stop an import before it is applied. It ends `failed`, with `cancelled_at`
    set, and nothing it previewed is written. Cancelling again answers the same
    import.

    Refusals you can get here:

    * `409 conflict` — the import is already being applied, or was; rows may
      already be written, so it can no longer be cancelled.
    * `403 forbidden` — you may not cancel imports here.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    run = get_import(tenant=tenant, import_id=import_id, org=request.org, actor=actor)
    return cancel_import(tenant=tenant, actor=actor, import_=run)
