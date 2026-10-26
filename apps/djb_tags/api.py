"""The HTTP door onto tags; each route resolves its row and calls the service its MCP twin calls.

# why-not `from __future__ import annotations`: ninja reads the route signatures at import.
"""

from uuid import UUID

from django.db.models import QuerySet
from ninja import Router, Status
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.api import CursorPagination
from apps.core.api.acting import acting
from apps.core.api.docs import Tag as DocTag
from apps.core.api.docs import also_refuses, refuses
from apps.core.requests import TenantRequest
from apps.core.schemas import Show
from apps.djb_tags.models import Tag, TagLink
from apps.djb_tags.schemas import DjbTagIn, DjbTagLinkIn, DjbTagLinkOut, DjbTagOut, DjbTagPatch
from apps.djb_tags.selectors import get_tag, get_tag_link, list_tag_links, list_tags
from apps.djb_tags.services import (
    archive_tag,
    create_tag,
    create_tag_link,
    delete_tag_link,
    rename_tag,
    restore_tag,
)

PREFIX = ""

TAGS = {
    "djb_tags": DocTag(
        "Tags",
        "The tenant's shared words, and the rows that carry them. Coin a tag once "
        "for the whole tenant, put it on any row that takes tags by naming the row "
        "as `<kind>:<id>`, read a row's tags the same way, and take a tag off "
        "again. Retiring a word hides it from the list and keeps it on every row "
        "that already carries it.",
        plane="everyday",
        plane_note=(
            "the tenant's shared words and the rows that carry them: tag a row you can see, "
            "read a row's tags, take a tag off. Everyday, because tagging is ordinary work and "
            "every link lives in the branch its row lives in. **Coining, renaming, archiving "
            "and restoring a word take an administrator of the whole tenant**, because a word "
            "means the same thing in every branch, and they are refused with `403 forbidden` "
            "otherwise."
        ),
    ),
}

router = Router(tags=["djb_tags"], auth=API_AUTH)


@router.get("/djb_tags/", response=list[DjbTagOut], url_name="djb_tag-list")
@paginate(CursorPagination)
def list_tags_route(request: TenantRequest, show: Show = "live") -> QuerySet[Tag]:
    """List tags

    The tenant's words, newest first. Every member of the tenant may read them.

    **`show`** picks the cut: `live` (the default) is the words in use,
    `archived` the retired ones, `all` both. A retired word stays on every row
    that already carries it; it only leaves this list and the pickers.
    """
    actor, tenant = acting(request)
    return list_tags(tenant=tenant, actor=actor, show=show)


@router.post("/djb_tags/", response={201: DjbTagOut}, url_name="djb_tag-create")
def create_tag_route(request: TenantRequest, payload: DjbTagIn) -> Status[DjbTagOut]:
    """Create a tag

    Coin a word for the whole tenant. Its `slug` is derived from `name` and is
    the word's identity: coining a word the tenant already has — live or
    archived — is refused with `409 conflict` (restore an archived one instead).
    Takes an administrator of the whole tenant.
    """
    actor, tenant = acting(request)
    return Status(
        201, DjbTagOut.from_orm(create_tag(tenant=tenant, actor=actor, name=payload.name))
    )


@router.get("/djb_tags/{tag_id}/", response=DjbTagOut, url_name="djb_tag-detail")
def retrieve_tag(request: TenantRequest, tag_id: UUID) -> DjbTagOut:
    """Get a tag

    One word, live or archived. An archived word answers read-only: its
    `archived_at` and `archived_by` say when and by whom it was retired.
    """
    actor, tenant = acting(request)
    return DjbTagOut.from_orm(get_tag(tenant=tenant, actor=actor, tag_id=tag_id))


@router.patch("/djb_tags/{tag_id}/", response=DjbTagOut, url_name="djb_tag-rename")
@also_refuses("archived")
def rename_tag_route(request: TenantRequest, tag_id: UUID, payload: DjbTagPatch) -> DjbTagOut:
    """Rename a tag

    Respell a word; its `slug` follows. Every row that carries it reads the new
    spelling at once — the link names the word, not the spelling. An archived
    word is refused with `409 archived`; restore it first. Takes an
    administrator of the whole tenant.
    """
    actor, tenant = acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
    return DjbTagOut.from_orm(rename_tag(tenant=tenant, actor=actor, tag=tag, name=payload.name))


@router.post("/djb_tags/{tag_id}/archive/", response=DjbTagOut, url_name="djb_tag-archive")
@refuses("archive_blocked", "forbidden", "no_acting_scope", "not_found")
def archive_tag_route(request: TenantRequest, tag_id: UUID) -> DjbTagOut:
    """Archive a tag

    Retire a word: it leaves `/djb_tags/` and every picker, and every row that
    already carries it keeps it, readable. Pressing it again answers the same
    row with its first date. Takes an administrator of the whole tenant.
    """
    actor, tenant = acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
    return DjbTagOut.from_orm(archive_tag(tenant=tenant, actor=actor, tag=tag))


@router.post("/djb_tags/{tag_id}/restore/", response=DjbTagOut, url_name="djb_tag-restore")
@refuses("forbidden", "no_acting_scope", "not_found", "restore_blocked")
def restore_tag_route(request: TenantRequest, tag_id: UUID) -> DjbTagOut:
    """Restore a tag

    Bring a retired word back to `/djb_tags/` and the pickers. Pressing it on a live
    word answers the row unchanged. Takes an administrator of the whole tenant.
    """
    actor, tenant = acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
    return DjbTagOut.from_orm(restore_tag(tenant=tenant, actor=actor, tag=tag))


@router.get("/djb_tag_links/", response=list[DjbTagLinkOut], url_name="djb_tag_links-list")
@paginate(CursorPagination)
def list_tag_links_route(request: TenantRequest, subject: str) -> QuerySet[TagLink]:
    """List a row's tags

    The words one row carries, newest first. Name the row as `subject=<kind>:<id>`
    — for example `subject=widget:<id>`. A kind that does not take tags is
    refused with `400 invalid` naming `subject`; a row you cannot see is `404`,
    the same answer as a row that does not exist. Archived words stay listed:
    the row still carries them.
    """
    actor, tenant = acting(request)
    return list_tag_links(tenant=tenant, actor=actor, subject=subject)


@router.post(
    "/djb_tag_links/",
    response={200: DjbTagLinkOut, 201: DjbTagLinkOut},
    url_name="djb_tag_link-create",
)
@also_refuses("archived")
def create_tag_link_route(request: TenantRequest, payload: DjbTagLinkIn) -> Status[DjbTagLinkOut]:
    """Tag a row

    Put a word on a row, naming the row as `subject=<kind>:<id>`. The link lives
    in the branch the row lives in. Sending a pair that is already linked
    answers `200` with the same link rather than a second one; a new link
    answers `201`. A kind that does not take tags is `400 invalid` naming
    `subject`; a row you cannot see is `404`; an archived word is
    `409 archived`.
    """
    actor, tenant = acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=payload.tag_id)
    linking = create_tag_link(tenant=tenant, actor=actor, tag=tag, subject=payload.subject)
    return Status(201 if linking.created else 200, DjbTagLinkOut.from_orm(linking.link))


@router.delete("/djb_tag_links/{link_id}/", response={204: None}, url_name="djb_tag_link-delete")
def delete_tag_link_route(request: TenantRequest, link_id: UUID) -> Status[None]:
    """Remove a tag from a row

    Take one word off one row. A link has no archive: removing it is how it
    goes, and tagging the row again brings it back.
    """
    actor, tenant = acting(request)
    link = get_tag_link(tenant=tenant, actor=actor, link_id=link_id)
    delete_tag_link(tenant=tenant, actor=actor, link=link)
    return Status(204, None)
