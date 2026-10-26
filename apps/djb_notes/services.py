"""Writes for notes: every door calls these, and each resolves the subject again.

A note lands where its subject lives (`core.verbs.landing_for`, ADR core-20).
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import kind_of, may_be_named, require
from apps.core.exceptions import Invalid, NotFound, as_invalid
from apps.core.models import Tenant
from apps.core.schemas import event_payload
from apps.core.service import service
from apps.core.verbs import archive_row, landing_for, require_live, resolve_subject, restore_row
from apps.djb_notes.events import (
    NOTE_ARCHIVED,
    NOTE_CREATED,
    NOTE_MOVED,
    NOTE_RESTORED,
    NOTE_UPDATED,
)
from apps.djb_notes.models import Note
from apps.djb_notes.schemas import DjbNoteOut
from apps.djb_notes.selectors import get_subject, list_notes_pointing_at
from apps.events.services import emit

#: What may appear un-redacted in log lines and audit `input`; the body is prose, never logged.
LOG_KEYS: frozenset[str] = frozenset({"subject"})

NOUN = "djb_note"


def _said(note: Note) -> dict[str, Any]:
    return event_payload(DjbNoteOut.model_validate(note))


@service
def create_note(*, tenant: Tenant, actor: Actor, subject: str, body: str) -> Note:
    """Write a note about the row `subject` names (`<kind>:<id>`); reach before capability (C8)."""
    kind, row = get_subject(actor=actor, subject=subject)
    require(actor, "djb_note.create")
    if actor.user is None:
        # A note is one person's words; the product acting for itself has none.
        raise Invalid({"author": ["A note needs somebody to have written it."]})
    note = Note(
        tenant=tenant,
        organization=landing_for(row, actor),
        subject_kind=kind,
        subject_id=row.pk,
        author_id=actor.user.pk,
        body=body,
    )
    with as_invalid():
        note.full_clean()
    note.save()
    emit(name=NOTE_CREATED, tenant=tenant, payload=_said(note), actor=actor)
    return note


@service
def update_note(*, tenant: Tenant, actor: Actor, note: Note, body: str | None = None) -> Note:
    """Change a note's words. Its author alone; an archived note is read-only."""
    if not may_be_named(actor, note):
        raise NotFound()
    require(actor, "djb_note.update", note)
    require_live(note, noun=NOUN)
    if body is None or body == note.body:
        return note
    note.body = body
    with as_invalid():
        note.full_clean()
    note.save(update_fields=["body", "updated_at"])
    emit(name=NOTE_UPDATED, tenant=tenant, payload=_said(note), actor=actor)
    return note


@service
def archive_note(*, tenant: Tenant, actor: Actor, note: Note) -> Note:
    """Take a note out of the book. Idempotent: a second press changes nothing."""
    if not may_be_named(actor, note):
        raise NotFound()
    require(actor, "djb_note.archive", note)
    note, changed = archive_row(tenant=tenant, actor=actor, row=note, noun=NOUN)
    if changed:
        emit(name=NOTE_ARCHIVED, tenant=tenant, payload=_said(note), actor=actor)
    return note


@service
def restore_note(*, tenant: Tenant, actor: Actor, note: Note) -> Note:
    """Put an archived note back. Idempotent: restoring a live note changes nothing."""
    if not may_be_named(actor, note):
        raise NotFound()
    require(actor, "djb_note.restore", note)
    note, changed = restore_row(tenant=tenant, actor=actor, row=note, noun=NOUN)
    if changed:
        emit(name=NOTE_RESTORED, tenant=tenant, payload=_said(note), actor=actor)
    return note


# door: reached only through this app's `merge_repointers.py`, which a noun's
# merge service calls inside its own transaction; no route or tool moves notes
# by itself, because re-pointing is a consequence of a merge, never an act.
@service
def move_notes(*, tenant: Tenant, actor: Actor, loser: Any, survivor: Any) -> int:
    """Re-point every note of a merged `loser` at its `survivor`. Answers how many moved.

    Both subjects are re-resolved for this actor and asked `djb_note.archive` at their nodes.
    A moved note takes the survivor's organization; a repeat answers 0 and emits nothing.
    """
    kind = kind_of(type(loser))
    if kind is None or kind != kind_of(type(survivor)):
        raise Invalid({"survivor": ["A note can only move to a subject of the same kind."]})
    loser = resolve_subject(actor, kind, loser.pk)
    survivor = resolve_subject(actor, kind, survivor.pk)
    require(actor, "djb_note.archive", loser)
    require(actor, "djb_note.archive", survivor)
    landing = landing_for(survivor, actor)
    moved = 0
    for note in list_notes_pointing_at(tenant=tenant, loser=loser).select_for_update():
        note.subject_id = survivor.pk
        note.organization = landing
        note.save(update_fields=["subject_id", "organization", "updated_at"])
        emit(name=NOTE_MOVED, tenant=tenant, payload=_said(note), actor=actor)
        moved += 1
    return moved
