"""Reads for notes — a note is read only through its subject, resolved first.

Rule 24's two halves: `for_tenant`/`visible_to` decide which notes;
`require(actor, "djb_note.read", ...)` decides whether this kind, here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.actor import Actor
from apps.core.authz import kind_of, require
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.core.verbs import resolve_subject, shown, subject_for
from apps.djb_notes.models import Note

#: The word a noun puts in its `attachments` declaration to accept notes.
ATTACHMENT = "notes"


def get_subject(*, actor: Actor, subject: str) -> tuple[str, Any]:
    """The `(kind, row)` a `<kind>:<id>` pointer names for this actor, in `subject_for`'s order."""
    row = subject_for(actor, subject, attachment=ATTACHMENT)
    return str(kind_of(type(row))), row


def _notes_in(*, tenant: Tenant | None, actor: Actor, show: str = "all") -> ScopedQuerySet[Note]:
    """The scoped read, without the capability, in one archive cut."""
    notes: ScopedQuerySet[Note] = shown(Note.objects.for_tenant(tenant).visible_to(actor), show)
    return notes.select_related("author", "archived_by")


def list_notes(
    *, tenant: Tenant | None, actor: Actor, subject: str, show: str = "live"
) -> ScopedQuerySet[Note]:
    """The notes about one subject this hat may see, newest first; the subject resolved first."""
    kind, row = get_subject(actor=actor, subject=subject)
    require(actor, "djb_note.read")
    return _notes_in(tenant=tenant, actor=actor, show=show).filter(
        subject_kind=kind, subject_id=row.pk
    )


def get_note(*, tenant: Tenant | None, actor: Actor, note_id: UUID) -> Note:
    """One note this hat sees whose subject it still reaches, archived included; else `NotFound`."""
    note = _notes_in(tenant=tenant, actor=actor).filter(pk=note_id).first()
    if note is None:
        raise NotFound()
    resolve_subject(actor, note.subject_kind, note.subject_id)
    require(actor, "djb_note.read", note)
    return note


def list_notes_pointing_at(*, tenant: Tenant, loser: Any) -> ScopedQuerySet[Note]:
    """Every note of this tenant pointing at `loser`, archived included — the merge's one read.

    # read-open: the merge road's machine read — the merge asks `<noun>.merge` on
    # both rows before any repointer runs, and a note is only counted and re-pointed.
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
