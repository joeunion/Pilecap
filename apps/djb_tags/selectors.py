"""Reads for tags: the words at the acting hat; a link only through its subject, resolved first."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.actor import Actor
from apps.core.authz import kind_of, require
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.core.verbs import shown, subject_for
from apps.djb_tags.models import ATTACHMENT, Tag, TagLink


def get_subject(*, actor: Actor, subject: str) -> Any:
    """The row a `<kind>:<id>` pointer names, if it takes tags and this actor can reach it."""
    return subject_for(actor, subject, attachment=ATTACHMENT)


def _tags_in(*, tenant: Tenant | None, show: str) -> ScopedQuerySet[Tag]:
    tags: ScopedQuerySet[Tag] = shown(Tag.objects.for_tenant(tenant), show)
    return tags.select_related("archived_by")


def list_tags(*, tenant: Tenant | None, actor: Actor, show: str = "live") -> ScopedQuerySet[Tag]:
    """The tenant's vocabulary in the cut `show` names; an unknown word is `invalid`."""
    # hat-scoped: sight is the acting hat's — a tag is TENANT-WIDE vocabulary and
    # every branch's people may SEE the words they are meant to use; they cannot
    # coin, respell or retire one, because those writes are asked at the root.
    # DATED, 2026-09-27, the stopgap every tenant-wide kind carries: reads of a
    # tenant-wide kind are the hat's on every door until the hierarchy gives these
    # kinds a home (the universal-homing proposal, 2026-09-17).
    require(actor, "djb_tag.read")
    return _tags_in(tenant=tenant, show=show)


def get_tag(*, tenant: Tenant | None, actor: Actor, tag_id: UUID) -> Tag:
    """One tag, live or archived — an archived word still answers, read-only."""
    tag = _tags_in(tenant=tenant, show="all").filter(pk=tag_id).first()
    if tag is None:
        raise NotFound()
    # hat-scoped: sight is the acting hat's — the row is handed over for the
    # policy to read and never as a node to resolve at, so this asks exactly what
    # the list asks and answers at the same node.
    # DATED, 2026-09-27, the tenant-wide stopgap (the universal-homing proposal,
    # 2026-09-17 — every record homed at a node).
    require(actor, "djb_tag.read", tag)
    return tag


def list_tag_links(*, tenant: Tenant | None, actor: Actor, subject: str) -> ScopedQuerySet[TagLink]:
    """The tags one subject carries — archived words included, since the link stands."""
    row = get_subject(actor=actor, subject=subject)
    if tenant is None:
        raise NotFound()
    require(actor, "djb_tag_link.read", row)
    return _tag_links_seen(tenant=tenant, actor=actor, subject=row)


def _tag_links_seen(*, tenant: Tenant, actor: Actor, subject: Any) -> ScopedQuerySet[TagLink]:
    """The links on a subject the CALLER already resolved, as this actor sees them.

    No authorization here — the caller resolved and authorized the subject. The
    narrowing is the acting hat: every link on a branch-owned subject sits at the
    subject's node, which a hat that reached the subject covers; a link on a
    tenant-wide subject sits at the hat that put it there, and is this hat's to
    read only when that node is inside its branch.
    """
    return (
        TagLink.objects.for_tenant(tenant)
        .visible_to(actor)
        .filter(subject_kind=kind_of(type(subject)), subject_id=subject.pk)
        .select_related("tag")
    )


def _subject_tag_links(*, tenant: Tenant, subject: Any) -> ScopedQuerySet[TagLink]:
    """EVERY link on a subject, wherever it landed. No authorization here.

    The merge's population: shared by the repointer's dry-run `count` and the
    move (and the pair lookup a new link is judged against), so they read one
    query and cannot disagree about which links a subject carries. The caller
    resolved and authorized the subject first.
    """
    return (
        # rule-24: a merge carries every link of the loser, whoever put it there
        # and wherever it landed — a tenant-wide subject's links sit at many hats —
        # and the merge authorized administering both records before any
        # repointer runs; narrowing to one node would strand the rest.
        TagLink.objects.for_tenant(tenant)
        .filter(subject_kind=kind_of(type(subject)), subject_id=subject.pk)
        .select_related("tag")
    )


def get_tag_link(*, tenant: Tenant | None, actor: Actor, link_id: UUID) -> TagLink:
    """One link, if it sits in a branch this actor's hat covers."""
    link = (
        TagLink.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_related("tag")
        .filter(pk=link_id)
        .first()
    )
    if link is None:
        raise NotFound()
    require(actor, "djb_tag_link.read", link)
    return link
