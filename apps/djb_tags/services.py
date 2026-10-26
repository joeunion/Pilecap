"""Writes for tags; every door — REST, MCP, the merge's repointer — calls these.

A word is asked at `root_organization(tenant)` (rule 55); a link at its subject's node, landing by
`core.verbs.landing_for` (ADR core-20). A request that changed nothing emits nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils.text import slugify

from apps.core.actor import Actor
from apps.core.authz import kind_of, may_be_named, require
from apps.core.exceptions import Conflict, Invalid, NotFound, as_invalid
from apps.core.models import Tenant
from apps.core.schemas import event_payload
from apps.core.service import service
from apps.core.services import root_organization
from apps.core.verbs import archive_row, landing_for, require_live, restore_row
from apps.djb_tags.events import (
    TAG_ARCHIVED,
    TAG_CREATED,
    TAG_LINK_CREATED,
    TAG_LINK_DELETED,
    TAG_LINK_MOVED,
    TAG_RENAMED,
    TAG_RESTORED,
)
from apps.djb_tags.models import Tag, TagLink
from apps.djb_tags.schemas import DjbTagLinkOut, DjbTagOut
from apps.djb_tags.selectors import _subject_tag_links, get_subject
from apps.events.services import emit

#: What may appear un-redacted in log lines and audit `input`: vocabulary and an id.
LOG_KEYS: frozenset[str] = frozenset({"name", "subject"})


def _tag_payload(tag: Tag) -> dict[str, Any]:
    return event_payload(DjbTagOut.from_orm(tag))


def _link_payload(link: TagLink) -> dict[str, Any]:
    return event_payload(DjbTagLinkOut.from_orm(link))


def _slug_for(name: str) -> str:
    slug = slugify(name.strip(), allow_unicode=True)
    if not slug:
        raise Invalid({"name": ["A tag needs at least one letter or digit."]})
    return slug


def _refuse_a_taken_slug(*, tenant: Tenant, slug: str, other_than: UUID | None = None) -> None:
    taken = Tag.objects.for_tenant(tenant).including_archived().filter(slug=slug)
    if other_than is not None:
        taken = taken.exclude(pk=other_than)
    holder = taken.first()
    if holder is None:
        return
    state = "an archived tag — restore it instead" if holder.is_archived else "a tag"
    raise Conflict(f"{holder.name!r} is already {state}; a word is coined once per tenant.")


@service
def create_tag(*, tenant: Tenant, actor: Actor, name: str) -> Tag:
    """Coin a word for the whole tenant. Asked at the root; the slug is the identity."""
    require(actor, "djb_tag.create", root_organization(tenant=tenant))
    slug = _slug_for(name)
    _refuse_a_taken_slug(tenant=tenant, slug=slug)
    tag = Tag(tenant=tenant, name=name.strip(), slug=slug)
    with as_invalid():
        tag.full_clean()
    tag.save()
    emit(name=TAG_CREATED, tenant=tenant, payload=_tag_payload(tag), actor=actor)
    return tag


@service
def rename_tag(*, tenant: Tenant, actor: Actor, tag: Tag, name: str) -> Tag:
    """Respell a word. Every link that carries it reads the new spelling at once."""
    require(actor, "djb_tag.update", root_organization(tenant=tenant))
    require_live(tag, noun="djb_tag")
    slug = _slug_for(name)
    if tag.name == name.strip() and tag.slug == slug:
        return tag
    _refuse_a_taken_slug(tenant=tenant, slug=slug, other_than=tag.pk)
    tag.name = name.strip()
    tag.slug = slug
    with as_invalid():
        tag.full_clean()
    tag.save(update_fields=["name", "slug", "updated_at"])
    emit(name=TAG_RENAMED, tenant=tenant, payload=_tag_payload(tag), actor=actor)
    return tag


@service
def archive_tag(*, tenant: Tenant, actor: Actor, tag: Tag) -> Tag:
    """Retire a word from `/djb_tags/` and the pickers, its links kept. A repeat says nothing."""
    require(actor, "djb_tag.archive", root_organization(tenant=tenant))
    tag, changed = archive_row(tenant=tenant, actor=actor, row=tag, noun="djb_tag")
    if changed:
        emit(name=TAG_ARCHIVED, tenant=tenant, payload=_tag_payload(tag), actor=actor)
    return tag


@service
def restore_tag(*, tenant: Tenant, actor: Actor, tag: Tag) -> Tag:
    """Bring a retired word back. Idempotent, the mirror of `archive_tag`."""
    require(actor, "djb_tag.restore", root_organization(tenant=tenant))
    tag, changed = restore_row(tenant=tenant, actor=actor, row=tag, noun="djb_tag")
    if changed:
        emit(name=TAG_RESTORED, tenant=tenant, payload=_tag_payload(tag), actor=actor)
    return tag


@dataclass(frozen=True)
class TagLinking:
    """The link, and whether THIS call made it — the door's 201 or 200.

    The row first, so the audit names it (`core.service._object_of`).
    """

    link: TagLink
    created: bool


@service
def create_tag_link(*, tenant: Tenant, actor: Actor, tag: Tag, subject: str) -> TagLinking:
    """Put a word on a subject. **Idempotent on `(tag, subject)`**: a repeat answers the same row.

    Two racing requests meet the unique constraint and the loser reads the winner's row.
    A pair already carried from a branch this hat does not cover is `conflict`.
    """
    row = get_subject(actor=actor, subject=subject)
    require(actor, "djb_tag_link.create", row)
    require_live(tag, noun="djb_tag")
    organization = landing_for(row, actor)
    kind = kind_of(type(row))
    if kind is None:
        raise NotFound()
    existing = _subject_tag_links(tenant=tenant, subject=row).filter(tag=tag).first()
    if existing is not None:
        return TagLinking(link=_already_linked(actor=actor, link=existing), created=False)
    link = TagLink(
        tenant=tenant, organization=organization, tag=tag, subject_kind=kind, subject_id=row.pk
    )
    with as_invalid():
        link.full_clean(validate_constraints=False)
    try:
        with transaction.atomic():
            link.save()
    except IntegrityError:
        winner = _subject_tag_links(tenant=tenant, subject=row).get(tag=tag)
        return TagLinking(link=_already_linked(actor=actor, link=winner), created=False)
    emit(name=TAG_LINK_CREATED, tenant=tenant, payload=_link_payload(link), actor=actor)
    return TagLinking(link=link, created=True)


def _already_linked(*, actor: Actor, link: TagLink) -> TagLink:
    """The link a repeat press answers, if this hat may read it; else an unnamed `conflict`."""
    if may_be_named(actor, link):
        return link
    raise Conflict("That row already carries this tag, put there from another part of the tenant.")


@service
def delete_tag_link(*, tenant: Tenant, actor: Actor, link: TagLink) -> TagLink:
    """Take a word off a subject; answers the removed row, id restored, so the audit names it."""
    if not may_be_named(actor, link):
        raise NotFound()
    require(actor, "djb_tag_link.delete", link)
    removed_id = link.pk
    payload = _link_payload(link)
    link.delete()
    link.id = removed_id
    emit(name=TAG_LINK_DELETED, tenant=tenant, payload=payload, actor=actor)
    return link


# door: reached only through this app's merge_repointers.py, which the family's
# merge calls inside its own audited transaction — the merge's route is the door.
@service
def move_tag_links(*, tenant: Tenant, actor: Actor, loser: Any, survivor: Any) -> int:
    """Carry every link on a merged-away subject to its survivor. Answers how many left the loser.

    Both subjects are re-resolved and asked `djb_tag_link.update` at their nodes.
    A word the survivor already carries is deleted from the loser, not duplicated, and still counts.
    """
    kind = kind_of(type(loser))
    if kind is None or kind != kind_of(type(survivor)):
        raise Invalid({"survivor": ["Links move only between two rows of the same kind."]})
    loser = get_subject(actor=actor, subject=f"{kind}:{loser.pk}")
    survivor = get_subject(actor=actor, subject=f"{kind}:{survivor.pk}")
    require(actor, "djb_tag_link.update", loser)
    require(actor, "djb_tag_link.update", survivor)
    landing = landing_for(survivor, actor)
    carried = set(
        _subject_tag_links(tenant=tenant, subject=survivor).values_list("tag_id", flat=True)
    )
    moved = 0
    for link in _subject_tag_links(tenant=tenant, subject=loser).select_for_update():
        if link.tag_id in carried:
            payload = _link_payload(link)
            link.delete()
            emit(name=TAG_LINK_DELETED, tenant=tenant, payload=payload, actor=actor)
        else:
            link.subject_id = survivor.pk
            link.organization = landing
            link.save(update_fields=["subject_id", "organization", "updated_at"])
            carried.add(link.tag_id)
            emit(name=TAG_LINK_MOVED, tenant=tenant, payload=_link_payload(link), actor=actor)
        moved += 1
    return moved
