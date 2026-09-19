"""The HTTP door onto exports: ask for one, watch it, fetch it.

Nothing here is implicit: the router restates `auth=`, the list paginates, every
read goes through `selectors.py` (which narrows to `request.tenant` **and**
`request.org`) and the one write goes through `services.py`. `request.org` is
the acting hat `TenantMiddleware` resolved from `X-Org`, and every read passes
it — a route that passed only the tenant would hand a sub-seller the whole
tenant.

The routes never say 404 either. `selectors.get_export` raises `NotFound` and
`config/api.py` is the only module that turns that into a number, so the MCP
tool over the same selector refuses identically without repeating the rule.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a
# `FilterSchema` parameter comes out as an unresolvable forward reference.

from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpResponseBase, HttpResponseRedirect
from ninja import Query, Router, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.docs import Tag
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.exports.models import Export
from apps.exports.schemas import ExportFilter, ExportIn, ExportOut
from apps.exports.selectors import get_export, list_exports
from apps.exports.services import create_export

# The path says what the resource is, not which app holds it. `config.api` reads
# this; an app that says nothing is mounted under its label. Here the two happen
# to agree, and it is written down anyway so that renaming the app never
# silently moves a published URL.
PREFIX = "exports"

# What `?ordering=` may name, and nothing else. Straight into `.order_by()` it
# would let a client sort by any column and traverse any relation — a full-table
# sort on an unindexed column at best, a read across a join at worst.
ORDERING = ("created_at", "completed_at", "status")

# The scope family this app's routes belong to, and a NEW one — the first since
# the three-way split of 2026-08-24. It follows the DEFAULT half of the choosing
# pattern (django-conventions §6): the plural noun of the section's primary
# resource, `exports`, because the noun does not mislead a reader who meets the
# string with no API around it. `exports:read` and `exports:write` say exactly
# what a token holding them is trusted with — see the archive, and ask for one.
# The exception half of the pattern (name the MEANING when the noun would
# mislead, as `messaging` does for comms) does not apply: there is no gap here
# between "may write an export row" and "may take a copy of the data", because
# they are the same act.
#
# The key FREEZES the day a token could name it, which is today: renaming it
# later kills every ceiling that holds it, silently, and the token goes on
# authenticating while being refused at every door. `FROZEN_FAMILIES` in
# `apps/core/api/scopes.py` is the census a later reader checks this against.
TAGS = {
    "exports": Tag(
        "Exports",
        "Taking a copy of your data out of the product. Ask for an archive of "
        "everything your organization can see — or, with administrator rights, of "
        "the whole account — follow it while it is built, and download it. Archives "
        "are deleted automatically after a month.",
        plane="everyday",
        plane_note=(
            "taking a copy of your data out: ask for an archive of everything your organization "
            "can see, follow it while it is built, and download it. Everyday rather than "
            "administrative, because an export of your own organization contains exactly what "
            "you can already read one page at a time. Asking for the **whole account** is the "
            "one act here that takes an owner or an administrator of it, and it is refused with "
            "`403 forbidden` otherwise."
        ),
    ),
}

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call these routes.
router = Router(tags=["exports"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as.

    Authentication has already guaranteed the user. The tenant has not been
    guaranteed by anything: a signed-in user with no membership resolves to
    `None`, and a write with no tenant is refused rather than guessed at.

    The hat rides on the actor rather than being returned beside the tenant,
    because that is where the service reads it from — `create_export` takes no
    `organization=` argument, so there is nothing for a route to pass and
    nothing for a caller to forge.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


@router.get("/", response=list[ExportOut], url_name="export-list")
@paginate(CursorPagination)
def list_exports_route(
    request: TenantRequest,
    filters: Query[ExportFilter],
    ordering: str = "-created_at",
) -> QuerySet[Export]:
    """List exports

    List the archives your organization has asked for, newest first.

    **Narrow** with `status`, which is one of `pending`, `running`, `completed`
    or `failed`. It is an exact match, so `?status=fail` finds nothing and
    `?status=failed` finds the failures.

    **Sort** with `ordering`. It accepts `created_at`, `completed_at` or
    `status`, each optionally prefixed with `-` for descending, and the default
    is `-created_at`. Any other value is refused with `400 invalid` rather than
    quietly ignored.

    **Pages** are `?cursor=` and `?limit=` (50 by default, 200 at most). The
    body is `{"items": [...], "has_more": ..., "next_cursor": ...}`: send the
    `next_cursor` you were given back as `?cursor=` for the following page, and
    stop when `has_more` is false. A cursor is opaque — never build or edit one.

    **`count` is `null` unless you send `?include_count=true`**, because a total
    costs a second pass over the matches.

    **What you can see** depends on the organization you are acting as — the
    `X-Org` header, or your default organization if you send none. You get that
    organization's exports and those of every organization beneath it. Exports
    belonging to an organization alongside yours, or above it, are not in the
    list.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization (send `X-Tenant` and `X-Org` naming ones you belong to), or
      your role does not include reading exports here.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Scoped first and only narrowed after, which is why the type widens from
    `ScopedQuerySet` to `QuerySet` here: filtering returns the plain one, and
    narrowing a queryset cannot widen its tenant.
    """
    exports: QuerySet[Export] = list_exports(
        tenant=request.tenant, org=request.org, actor=actor_from_request(request)
    )
    exports = filters.filter(exports)
    return ordered_by(exports, ordering, allowed=ORDERING, default="-created_at")


@router.post("/", response={201: ExportOut}, url_name="export-create")
def create_export_route(request: TenantRequest, payload: ExportIn) -> Status[Export]:
    """Request an export

    Ask for an archive of your data. Answers `201` straight away with an export
    in `pending`; the archive itself is built in the background.

    `scope` decides how much goes in it:

    * `organization` (the default) — everything the organization you are acting
      as can see, and everything beneath it. This needs no special permission,
      because it is the same data you can already page through one request at a
      time.
    * `tenant` — the whole account, including the tables that belong to the
      account as a whole rather than to any one organization. This needs
      administrator rights at the top of the account, and answers `403
      forbidden` otherwise.

    Send `idempotency_key` with your own name for the request — `nightly-2026-08-24`,
    a ticket number, anything stable. Asking again with the same one returns the
    export you already have instead of building a second copy of your data.

    Poll `GET /api/v1/exports/{id}/` until `status` is `completed`, then use
    `download_url` if it is set and `download_path` otherwise. The `manifest` on
    the export says exactly which tables are in the archive, how many rows each
    has, and which columns and tables were left out and why — read it before you
    download, not after.

    Refusals you can get here:

    * `400 invalid` — `scope` is not one of `organization` or `tenant`, or the
      body carried a field this endpoint does not accept. `errors` names the
      fields and nothing is created.
    * `403 forbidden` — you asked for the whole account and you are not an
      owner or an administrator of it, or the request resolved no acting
      organization.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` header for a different request, or the first request
      under it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Two different keys with two different jobs, and the docstring above says both
    without naming the seam: the `Idempotency-Key` HEADER is the transport-level
    replay guard `core.idempotency` owns, and `idempotency_key` in the body is
    this app's own — it survives the 24-hour record window and is what stops a
    nightly job from making thirty archives in a month.
    """
    actor, tenant = _acting(request)
    export = create_export(
        tenant=tenant,
        actor=actor,
        scope=payload.scope,
        idempotency_key=payload.idempotency_key,
    )
    return Status(201, export)


@router.get("/{export_id}/", response=ExportOut, url_name="export-detail")
def retrieve_export(request: TenantRequest, export_id: UUID) -> Export:
    """Retrieve an export

    One export, with where it has got to and how to fetch it.

    While `status` is `pending` or `running` there is nothing to download yet
    and both download fields are `null`. When it is `completed`, use
    `download_url` if it is set — that is a temporary link straight to storage —
    and `download_path` otherwise, which is a path on this API that you fetch
    with your usual credential. Reading `download_url or download_path` is
    correct on either kind of deployment.

    When it is `failed`, `error` says what went wrong and nothing was written:
    there is no partial archive to fetch. Ask for a new export.

    `expires_at` is when the archive and this record are deleted. It is about a
    month after you asked, and it is not extendable — download what you need
    before then.

    An export belonging to an organization you cannot see answers
    `404 not_found`, the same answer an id that names nothing gets.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting
      organization (send `X-Tenant` and `X-Org` naming ones you belong to), or
      your role does not include reading exports here.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_export(
        tenant=request.tenant,
        export_id=export_id,
        org=request.org,
        actor=actor_from_request(request),
    )


def downloadable_export(*, tenant: Tenant, actor: Actor, export_id: UUID) -> Export:
    """The export whose archive may be fetched right now — **one gate, both doors**.

    Three refusals in one place: the row this hat cannot see is `not_found`, the
    actor who may not read it is `forbidden`, and an export with no archive
    behind it — pending, failed, or already swept — is `not_found` again,
    because "there is no file here" and "there is no such export" are the same
    answer to somebody holding a URL.

    **The middle one is the SELECTOR's now** (§C6). `get_export` asks
    `export.read` at the row's own node after the scoped fetch, so this function
    no longer repeats the question: two `require`s for one key would be two
    places for the answer to be decided, and the one that would eventually
    disagree is the one a reviewer forgets is there. The refusal a caller sees
    is byte-identical, because it is the same key and the same sentence.

    It lives here rather than in `selectors.py` because it refuses rather than
    narrowing, and here rather than being written twice because `mcp.py` imports
    it: the two doors then cannot come to disagree about when an archive is
    fetchable, which is the kind of disagreement no value-by-value test would
    catch.
    """
    export = get_export(tenant=tenant, export_id=export_id, org=actor.org, actor=actor)
    if not export.is_downloadable:
        raise NotFound()
    return export


@router.get("/{export_id}/download/", url_name="export-download")
def download_export_route(request: TenantRequest, export_id: UUID) -> HttpResponseBase:
    """Download an export

    Fetch the archive itself: a zip file, streamed.

    Inside it there is one `models/<app>.<Model>.jsonl` file per table — one JSON
    object per line, in the table's own column names — and a `manifest.json`
    listing every table in the archive with its row count, the columns that were
    left out and why, the tables a single-organization export could not carry,
    and the tables left out because whoever asked for the archive may not read
    them (`omitted_models`, each with the reason `unreadable`). The manifest is
    the same document the export record shows you, so you can check what you are
    about to download before you download it.

    **This route redirects.** It answers `302` with a short-lived signed link to
    the archive in object storage, and your client follows it to the bytes — the
    same link the export record publishes as `download_url`. Any client that
    follows redirects needs no change (`curl -L`, a browser, `requests`); a
    client that does not should read `download_url` off the record instead.

    Send your usual credential to THIS route: the redirect is issued only to a
    caller who may read the export. The link it hands back carries its own
    signature, is good for a few minutes, and needs no credential of yours — so
    treat it as the secret it is and do not paste it anywhere durable.

    An export that has not finished, one that failed, and one whose archive has
    already expired all answer `404 not_found`. So does an export belonging to
    an organization you cannot see.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting
      organization (send `X-Tenant` and `X-Org` naming ones you belong to), or
      your role does not include reading exports here.
    * `404 not_found` — nothing has that id where you can see, or there is no
      archive on it to fetch.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    It used to stream a `FileResponse` over `default_storage`. XPr moved the
    archive onto the files seam, where ADR files-2 rules that bytes never travel
    through Django, and applied XP-1's OWN ratified either/or — *"a presigned
    `download_url` where the backend signs, and an authenticated `/download`
    stream otherwise"* — to its first branch: `files.storage.bucket_name()`
    refuses a deployment that has named no bucket, so an export artifact only
    ever exists somewhere that signs and the *otherwise* has no world left. What
    is gained is that a multi-gigabyte archive no longer occupies a worker for
    the length of a customer's download; what is spent is the redirect, which is
    why the paragraph above is written for a client to act on rather than left
    as a mechanism note.
    """
    actor, tenant = _acting(request)
    export = downloadable_export(tenant=tenant, actor=actor, export_id=export_id)
    # `download_url` and not a second presign call: one property mints the link,
    # so the record and this door cannot come to disagree about its lifetime or
    # its shape. `downloadable_export` has already refused everything for which
    # it would be `None`, which is what makes the cast honest rather than hopeful.
    return HttpResponseRedirect(str(export.download_url))
