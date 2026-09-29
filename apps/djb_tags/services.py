"""Writes for tags. Every door — REST, MCP, the merge's repointer — calls these.

Each is `@service` (keyword-only, atomic, traced, audited) and authorizes
itself. Two scopes, two placements:

* **The words** (`create_tag`, `rename_tag`, `archive_tag`, `restore_tag`) are
  tenant-wide, so every one is asked at `root_organization(tenant)` — never at
  the acting hat, where a branch administrator holds `*` (house rule 55).
* **The links** (`create_tag_link`, `delete_tag_link`, `move_tag_links`) are
  acts on a SUBJECT row, so the subject is resolved and reached first
  (`core.verbs.resolve_subject`), the capability is asked at the subject's own
  node, and the link lands in the subject's branch — or, for a tenant-wide
  subject that has no branch, at the acting hat (ADR core-20); never the root.

Every state change is said once, with `emit()`, inside the transaction that
made it; a request that changed nothing says nothing.
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
from apps.core.service import service
from apps.core.services import root_organization
from apps.core.verbs import archive_row, require_live, restore_row
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
from apps.djb_tags.schemas import TagLinkOut, TagOut
from apps.djb_tags.selectors import _landing, _subject_tag_links, get_subject
from apps.events.services import emit

#: What may appear un-redacted in this app's log lines and audit `input`. A tag's
#: name is vocabulary, not a person's data; a subject pointer is an id.
LOG_KEYS: frozenset[str] = frozenset({"name", "subject"})


def _tag_payload(tag: Tag) -> dict[str, Any]:
    return TagOut.from_orm(tag).model_dump(mode="json")


def _link_payload(link: TagLink) -> dict[str, Any]:
    return TagLinkOut.from_orm(link).model_dump(mode="json")


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
    """Retire a word: off `/djb_tags/` and every picker. Its links stay readable.

    Idempotent — a second press answers the row unchanged, keeping the first
    press's date, and says nothing.
    """
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
    """Put a word on a subject. **Idempotent on `(tag, subject)`.**

    The subject is resolved through the one resolver — a kind that does not take
    tags is `invalid` naming `subject`; a row this actor could not reach
    (another branch, another tenant, no row at all) is `not_found`, one answer
    for all three. The link lands in the SUBJECT's branch (a tenant-wide subject:
    the acting hat). A second request for a
    pair that is already linked answers the same row, `created=False`, and emits
    nothing; two racing requests meet the unique constraint and the loser reads
    the winner's row. A pair already carried from a branch this hat does not
    cover (only a tenant-wide subject's links can sit there) is `conflict`.
    """
    row = get_subject(actor=actor, subject=subject)
    require(actor, "djb_tag_link.create", row)
    require_live(tag, noun="djb_tag")
    organization = _landing(subject=row, actor=actor)
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
    """The link a repeat press answers with — if this hat may read it.

    One link per `(tag, subject)` holds tenant-wide, but a link on a tenant-wide
    subject lands at the hat that put it there (the landing law), so the pair may
    already be carried from a branch this hat does not cover. That is a
    `conflict` naming no branch — never the other branch's row, and never a 500
    off the lost race.
    """
    if may_be_named(actor, link):
        return link
    raise Conflict("That row already carries this tag, put there from another part of the tenant.")


@service
def delete_tag_link(*, tenant: Tenant, actor: Actor, link: TagLink) -> TagLink:
    """Take a word off a subject — the face's *Remove tag*. A link has no archive.

    Returns the row it removed, id restored, so the audit and the event can
    name what went.
    """
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
    """Carry every link on a merged-away subject to its survivor. Answers how many.

    Called by this app's `merge_repointers.py` inside the merge's own
    transaction. Both subjects are re-resolved through the one resolver (a merge
    that named a row this actor cannot reach moves nothing), and moving is asked
    as `djb_tag_link.update` at both subjects' nodes — an administrator's key, which
    is who may merge at all.

    **A link the survivor already carries is not duplicated**: the unique
    `(tag, subject)` pair means the survivor already says that word, so the
    loser's copy is deleted (`djb_tags.tag_link.deleted`) rather than moved. It
    counts toward the answer all the same — after this call the loser carries
    no link and the survivor carries every word either of them carried — which
    is what `count` (the dry run, which cannot see the survivor) promised.
    """
    kind = kind_of(type(loser))
    if kind is None or kind != kind_of(type(survivor)):
        raise Invalid({"survivor": ["Links move only between two rows of the same kind."]})
    loser = get_subject(actor=actor, subject=f"{kind}:{loser.pk}")
    survivor = get_subject(actor=actor, subject=f"{kind}:{survivor.pk}")
    require(actor, "djb_tag_link.update", loser)
    require(actor, "djb_tag_link.update", survivor)
    landing = _landing(subject=survivor, actor=actor)
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
