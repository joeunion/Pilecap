"""Reads for notes — and the one place a subject pointer is turned into a row.

**A note is read only through its subject.** `list_notes` resolves the subject
first, through `core.verbs.resolve_subject` — the kind registry, the tenant
(archived rows included), the acting hat, `may_be_named` — and only then reads
the notes that point at it. `get_note` does the same in the other direction:
the note is fetched in scope, and then its subject must still resolve for this
actor. So a note whose subject is gone, or out of this hat's reach, is
`not_found` — unreachable, never wrong.

**Two questions, two owners** (rule 24): `for_tenant`/`visible_to` decide which
notes; `require(actor, "note.read", ...)` decides whether this kind, here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.actor import Actor
from apps.core.authz import kind_of, kind_registry, require
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.core.verbs import resolve_subject
from apps.notes.models import SUBJECT_SEPARATOR, Note

#: The word a noun puts in its `attachments` declaration to accept notes.
ATTACHMENT = "notes"

#: The class attribute a noun declares its attachment kinds in:
#: `attachments = ("notes", "files", "tags")`. Read off the model, the way every
#: other family marker is — the declaration is the whole population.
ATTACHMENTS_ATTR = "attachments"

#: The archive cuts a list may ask for (house rule 74).
SHOWS: tuple[str, ...] = ("live", "archived", "all")


def _refuse(reason: str) -> Invalid:
    return Invalid({"subject": [reason]})


def _parse(subject: str) -> tuple[str, UUID]:
    """`<kind>:<id>` into its two halves, or `invalid` naming `subject`."""
    kind, separator, raw_id = (subject or "").strip().partition(SUBJECT_SEPARATOR)
    if not separator or not kind or not raw_id:
        raise _refuse("Name the subject as `<kind>:<id>` — for example `widget:<id>`.")
    try:
        return kind, UUID(raw_id)
    except ValueError:
        raise _refuse(f"{raw_id!r} is not an id.") from None


def _accepts_notes(kind: str) -> bool:
    model = kind_registry().get(kind)
    if model is None:
        return False
    declared = getattr(model, ATTACHMENTS_ATTR, ()) or ()
    return ATTACHMENT in tuple(declared)


def get_subject(*, actor: Actor, subject: str) -> tuple[str, Any]:
    """The row a `<kind>:<id>` pointer names, for this actor, with its kind.

    Three answers, in this order, and the order is the contract:

    1. a pointer that is not `<kind>:<id>` → `invalid` naming `subject`;
    2. a kind that has not declared `attachments = ("notes", ...)` — or no kind
       at all — → `invalid` naming `subject`. Which kinds take notes is a fact
       about the product's schema, not about any row, so saying so leaks
       nothing;
    3. a row this actor could not have reached — another tenant, a sibling
       branch, or nothing at all — → `not_found`, never `forbidden`
       (`core.verbs.resolve_subject`, C8).
    """
    kind, subject_id = _parse(subject)
    if not _accepts_notes(kind):
        raise _refuse(f"A {kind!r} does not take notes.")
    return kind, resolve_subject(actor, kind, subject_id)


def _notes_in(*, tenant: Tenant | None, actor: Actor, show: str = "all") -> ScopedQuerySet[Note]:
    """The scoped read, without the capability, in one of the three archive cuts."""
    if show not in SHOWS:
        raise Invalid({"show": [f"Show one of {', '.join(SHOWS)}."]})
    notes = Note.objects.for_tenant(tenant).visible_to(actor)
    if show == "archived":
        notes = notes.archived_only()
    elif show == "all":
        notes = notes.including_archived()
    return notes.select_related("author", "archived_by")


def list_notes(
    *, tenant: Tenant | None, actor: Actor, subject: str, show: str = "live"
) -> ScopedQuerySet[Note]:
    """The notes about one subject this hat may see, newest first.

    The subject is resolved before anything is read (see `get_subject`), so a
    list about a row the actor cannot reach is `not_found` rather than an empty
    page that would confirm nothing — and would also confirm nothing wrong.
    `show` is the archive cut: `live` (the default), `archived`, or `all`.
    """
    kind, row = get_subject(actor=actor, subject=subject)
    require(actor, "note.read")
    return _notes_in(tenant=tenant, actor=actor, show=show).filter(
        subject_kind=kind, subject_id=row.pk
    )


def get_note(*, tenant: Tenant | None, actor: Actor, note_id: UUID) -> Note:
    """One note this hat may see, whose subject it can still reach, or `NotFound`.

    Archived notes answer (read-only): the detail is where a restore is
    pressed from.
    """
    note = _notes_in(tenant=tenant, actor=actor).filter(pk=note_id).first()
    if note is None:
        raise NotFound()
    resolve_subject(actor, note.subject_kind, note.subject_id)
    require(actor, "note.read", note)
    return note


def list_notes_pointing_at(*, tenant: Tenant, loser: Any) -> ScopedQuerySet[Note]:
    """Every note of this tenant pointing at `loser`, archived ones included.

    # read-open: the merge road's machine read — the merge service asks
    # `<noun>.merge` on both rows before any repointer runs, and a note is not
    # read out of here, only counted and re-pointed.

    The merge road's read, shared by the dry run's count and the move so the
    two cannot disagree about which notes a merge touches. Scoped to the tenant
    and NOT to a hat: a merge moves ALL of the loser's notes — one left pointing
    at an archived loser is a note nobody will find again — and the merge has
    authorized administering both rows before any repointer runs.
    """
    kind = kind_of(type(loser))
    return (
        # rule-24: a merge re-points every note of the loser, whoever wrote it and
        # wherever it landed; the merge service authorized both rows first, and the
        # dry run's count and the move read this one query so they cannot disagree.
        Note.objects.for_tenant(tenant)
        .including_archived()
        .filter(subject_kind=kind, subject_id=loser.pk)
    )
