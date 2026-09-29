"""The HTTP door onto tags: the tenant's words at `/tags/`, and the words a row
carries at `/tag-links/?subject=<kind>:<id>`.

Generic, and deliberately so: there is no route per noun. A product's noun
takes tags by declaring `attachments = ("tags", ...)` on its model, and these
routes serve it through the `<kind>:<id>` pointer. Every read goes through
`selectors.py`, every write through `services.py`; the routes never say 404 —
`NotFound` from below is turned into a number by `config/api.py` alone, so the
MCP tools over the same functions refuse identically.
"""

# NOTE: no `from __future__ import annotations` — ninja builds a Pydantic model
# out of each route's signature at import time and needs real annotations.

from typing import Literal
from uuid import UUID

from django.db.models import QuerySet
from ninja import Router, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination
from apps.core.api.docs import Tag as DocTag
from apps.core.api.docs import also_refuses, refuses
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.tags.models import Tag, TagLink
from apps.tags.schemas import TagIn, TagLinkIn, TagLinkOut, TagOut, TagPatch
from apps.tags.selectors import get_tag, get_tag_link, list_tag_links, list_tags
from apps.tags.services import (
    TagLinking,
    archive_tag,
    create_tag,
    create_tag_link,
    delete_tag_link,
    rename_tag,
    restore_tag,
)

PREFIX = ""

TAGS = {
    "tags": DocTag(
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

router = Router(tags=["tags"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as. No tenant is refused, never guessed."""
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


def linking_body(linking: TagLinking) -> Status[TagLink]:
    """201 for the link this call made; 200 for the link that was already there."""
    return Status(201 if linking.created else 200, linking.link)


@router.get("/tags/", response=list[TagOut], url_name="tag-list")
@paginate(CursorPagination)
def list_tags_route(
    request: TenantRequest, show: Literal["live", "archived", "all"] = "live"
) -> QuerySet[Tag]:
    """List tags

    The tenant's words, newest first. Every member of the tenant may read them.

    **`show`** picks the cut: `live` (the default) is the words in use,
    `archived` the retired ones, `all` both. A retired word stays on every row
    that already carries it; it only leaves this list and the pickers.
    """
    actor, tenant = _acting(request)
    return list_tags(tenant=tenant, actor=actor, show=show)


@router.post("/tags/", response={201: TagOut}, url_name="tag-create")
def create_tag_route(request: TenantRequest, payload: TagIn) -> Status[Tag]:
    """Create a tag

    Coin a word for the whole tenant. Its `slug` is derived from `name` and is
    the word's identity: coining a word the tenant already has — live or
    archived — is refused with `409 conflict` (restore an archived one instead).
    Takes an administrator of the whole tenant.
    """
    actor, tenant = _acting(request)
    return Status(201, create_tag(tenant=tenant, actor=actor, name=payload.name))


@router.get("/tags/{tag_id}/", response=TagOut, url_name="tag-detail")
def retrieve_tag(request: TenantRequest, tag_id: UUID) -> Tag:
    """Get a tag

    One word, live or archived. An archived word answers read-only: its
    `archived_at` and `archived_by` say when and by whom it was retired.
    """
    actor, tenant = _acting(request)
    return get_tag(tenant=tenant, actor=actor, tag_id=tag_id)


@router.patch("/tags/{tag_id}/", response=TagOut, url_name="tag-rename")
@also_refuses("archived")
def rename_tag_route(request: TenantRequest, tag_id: UUID, payload: TagPatch) -> Tag:
    """Rename a tag

    Respell a word; its `slug` follows. Every row that carries it reads the new
    spelling at once — the link names the word, not the spelling. An archived
    word is refused with `409 archived`; restore it first. Takes an
    administrator of the whole tenant.
    """
    actor, tenant = _acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
    return rename_tag(tenant=tenant, actor=actor, tag=tag, name=payload.name)


@router.post("/tags/{tag_id}/archive/", response=TagOut, url_name="tag-archive")
@refuses("archive_blocked", "forbidden", "not_found")
def archive_tag_route(request: TenantRequest, tag_id: UUID) -> Tag:
    """Archive a tag

    Retire a word: it leaves `/tags/` and every picker, and every row that
    already carries it keeps it, readable. Pressing it again answers the same
    row with its first date. Takes an administrator of the whole tenant.
    """
    actor, tenant = _acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
    return archive_tag(tenant=tenant, actor=actor, tag=tag)


@router.post("/tags/{tag_id}/restore/", response=TagOut, url_name="tag-restore")
@refuses("forbidden", "not_found", "restore_blocked")
def restore_tag_route(request: TenantRequest, tag_id: UUID) -> Tag:
    """Restore a tag

    Bring a retired word back to `/tags/` and the pickers. Pressing it on a live
    word answers the row unchanged. Takes an administrator of the whole tenant.
    """
    actor, tenant = _acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
    return restore_tag(tenant=tenant, actor=actor, tag=tag)


@router.get("/tag-links/", response=list[TagLinkOut], url_name="tag_links-list")
@paginate(CursorPagination)
def list_tag_links_route(request: TenantRequest, subject: str) -> QuerySet[TagLink]:
    """List a row's tags

    The words one row carries, newest first. Name the row as `subject=<kind>:<id>`
    — for example `subject=widget:<id>`. A kind that does not take tags is
    refused with `400 invalid` naming `subject`; a row you cannot see is `404`,
    the same answer as a row that does not exist. Archived words stay listed:
    the row still carries them.
    """
    actor, tenant = _acting(request)
    return list_tag_links(tenant=tenant, actor=actor, subject=subject)


@router.post("/tag-links/", response={200: TagLinkOut, 201: TagLinkOut}, url_name="tag_link-create")
@also_refuses("archived")
def create_tag_link_route(request: TenantRequest, payload: TagLinkIn) -> Status[TagLink]:
    """Tag a row

    Put a word on a row, naming the row as `subject=<kind>:<id>`. The link lives
    in the branch the row lives in. Sending a pair that is already linked
    answers `200` with the same link rather than a second one; a new link
    answers `201`. A kind that does not take tags is `400 invalid` naming
    `subject`; a row you cannot see is `404`; an archived word is
    `409 archived`.
    """
    actor, tenant = _acting(request)
    tag = get_tag(tenant=tenant, actor=actor, tag_id=payload.tag_id)
    return linking_body(
        create_tag_link(tenant=tenant, actor=actor, tag=tag, subject=payload.subject)
    )


@router.delete("/tag-links/{link_id}/", response={204: None}, url_name="tag_link-delete")
def delete_tag_link_route(request: TenantRequest, link_id: UUID) -> Status[None]:
    """Remove a tag from a row

    Take one word off one row. A link has no archive: removing it is how it
    goes, and tagging the row again brings it back.
    """
    actor, tenant = _acting(request)
    link = get_tag_link(tenant=tenant, actor=actor, link_id=link_id)
    delete_tag_link(tenant=tenant, actor=actor, link=link)
    return Status(204, None)
