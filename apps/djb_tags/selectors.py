"""Reads for tags. Every one narrows to the tenant, and every link read to a subject.

**Tags are read at the acting hat** — a tag is tenant-wide vocabulary and names
no node below the tenant, so the hat is the only node the question has. Each
such line carries the dated `hat-scoped` valve house rule 55 counts.

**Links are read only THROUGH their subject.** `list_tag_links` resolves the
subject first (`core.verbs.resolve_subject`: the kind registry, the acting
hat's `visible_to`, `may_be_named`) and only then reads the links that point
at it — so a subject in a sibling branch is `not_found`, exactly as if it did
not exist, and a pointer whose subject is gone is unreachable rather than wrong.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.actor import Actor
from apps.core.authz import kind_of, kind_registry, require
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import Organization, ScopedQuerySet, Tenant, is_org_scoped
from apps.core.verbs import resolve_subject
from apps.djb_tags.models import ATTACHMENT, Tag, TagLink

#: The field every subject refusal names, on every door.
SUBJECT_FIELD = "subject"


def _split_subject(subject: str) -> tuple[str, str]:
    """`"widget:<id>"` → `("widget", "<id>")`, or `invalid` naming `subject`."""
    kind, sep, subject_id = subject.partition(":")
    if not sep or not kind or not subject_id:
        raise Invalid(
            {SUBJECT_FIELD: ["Name the subject as <kind>:<id>, for example widget:<id>."]}
        )
    return kind, subject_id


def _takes_tags(model: Any) -> bool:
    """Whether a noun declares `tags` in its `attachments` — the one reading of it here."""
    return ATTACHMENT in tuple(getattr(model, "attachments", ()) or ())


def _subject_model(kind: str) -> Any:
    """The model a kind names, if it declares tags — or `invalid` naming `subject`.

    A kind is published vocabulary, so saying "that kind does not take tags" leaks
    nothing: no row was looked up to say it.
    """
    model = kind_registry().get(kind)
    if model is None or not _takes_tags(model):
        raise Invalid({SUBJECT_FIELD: [f"A {kind!s} does not take tags."]})
    return model


def get_subject(*, actor: Actor, subject: str) -> Any:
    """The row a `<kind>:<id>` pointer names, if it takes tags and this actor can reach it."""
    kind, subject_id = _split_subject(subject)
    _subject_model(kind)
    return resolve_subject(actor, kind, subject_id)


def _landing(*, subject: Any, actor: Actor) -> Organization:
    """Where a link on this subject lives — the landing law (ADR core-20).

    The subject's own branch; a TENANT-WIDE subject has none, so the link lands
    at the ACTING HAT, the placement every created org-scoped row takes. Never
    the root: visibility is down-only, so a root-landed link is one its own
    branch author could not read back. (House rule 55's root-only writes govern
    the tenant-wide `Tag` row, never the org-scoped link.)
    """
    if is_org_scoped(type(subject)):
        organization: Organization = subject.organization
        return organization
    if actor.org is None:
        raise Invalid(
            {"organization": ["This request resolved no acting organization to write in."]}
        )
    return actor.org


def _tags_in(*, tenant: Tenant | None, show: str) -> ScopedQuerySet[Tag]:
    tags = Tag.objects.for_tenant(tenant)
    if show == "archived":
        tags = tags.archived_only()
    elif show == "all":
        tags = tags.including_archived()
    return tags.select_related("archived_by")


def list_tags(*, tenant: Tenant | None, actor: Actor, show: str = "live") -> ScopedQuerySet[Tag]:
    """The tenant's vocabulary — the live words, unless `show` asks for another cut."""
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
