"""The REST door onto notes; each route resolves its row and calls the service its MCP twin calls.

# why-not `from __future__ import annotations`: ninja reads the route signatures at import.
"""

from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.api import CursorPagination
from apps.core.api.acting import acting
from apps.core.api.docs import Tag, refuses
from apps.core.requests import TenantRequest
from apps.djb_notes.models import Note
from apps.djb_notes.schemas import DjbNoteFilter, DjbNoteIn, DjbNoteOut, DjbNotePatch
from apps.djb_notes.selectors import get_note, list_notes
from apps.djb_notes.services import archive_note, create_note, restore_note, update_note

PREFIX = "djb_notes"

TAGS = {
    "djb_notes": Tag(
        "Notes",
        "Notes about any record that takes them. A note names the record it is about "
        "as `<kind>:<id>` and lives where that record lives, so it is visible to "
        "exactly the people who can see the record. Notes are listed through the "
        "record they are about, edited only by the person who wrote them, and "
        "archived rather than deleted.",
        plane="everyday",
        plane_note=(
            "write a note about a record, read a record's notes, correct your own, "
            "archive one that no longer belongs."
        ),
    ),
}

router = Router(tags=["djb_notes"], auth=API_AUTH)


@router.get("/", response=list[DjbNoteOut], url_name="djb_note-list")
@paginate(CursorPagination)
def list_notes_route(request: TenantRequest, filters: Query[DjbNoteFilter]) -> QuerySet[Note]:
    """List a record's notes

    List the notes about one record, newest first.

    **`subject` is required**: name the record as `<kind>:<id>` — for example
    `?subject=widget:<id>`. Notes are only ever read through the record they
    are about, so there is no list of every note.

    **`show`** picks the cut: `live` (the default) lists the notes nobody has
    archived, `archived` lists only the archived ones, and `all` lists both.

    **Pages** are `?cursor=` and `?limit=` (50 by default, 200 at most). Send the
    `next_cursor` you were given back as `?cursor=` and stop when `has_more` is
    false. `count` is `null` unless you send `?include_count=true`.

    Refusals you can get here:

    * `400 invalid` — `subject` is not `<kind>:<id>`, or names a kind of record
      that does not take notes. `errors` names `subject`.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization, or your role here does not let you read notes.
    * `404 not_found` — the record is not one you can see from the organization
      you are acting as. A record in a branch alongside yours answers this too,
      exactly as one that does not exist.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return list_notes(tenant=tenant, actor=actor, subject=filters.subject, show=filters.show)


@router.post("/", response={201: DjbNoteOut}, url_name="djb_note-create")
def create_note_route(request: TenantRequest, payload: DjbNoteIn) -> Status[DjbNoteOut]:
    """Write a note

    Write a note about a record.

    Send the `subject` — the record, as `<kind>:<id>` — and the `body`. The note
    lives where the record lives: its organization is the record's, so everyone
    who can see the record can read it, and nobody else can.

    Answers `201` with the note.

    Refusals you can get here:

    * `400 invalid` — `subject` is not `<kind>:<id>`, names a kind of record that
      does not take notes, or `body` is empty. `errors` names the field.
    * `403 forbidden` — you may not write notes here, or the request resolved no
      tenant or no acting organization.
    * `404 not_found` — the record is not one you can see from the organization
      you are acting as; nothing is written. A record in a branch alongside
      yours answers this, not `403`.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    note = create_note(tenant=tenant, actor=actor, subject=payload.subject, body=payload.body)
    return Status(201, DjbNoteOut.model_validate(note))


@router.get("/{note_id}/", response=DjbNoteOut, url_name="djb_note-detail")
def retrieve_note(request: TenantRequest, note_id: UUID) -> DjbNoteOut:
    """Retrieve a note

    Fetch one note by id — archived notes included, read-only.

    You get it only if you can see both the note and the record it is about
    from the organization you are acting as. Anything else answers
    `404 not_found`, the same answer an id that names nothing gets.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting
      organization, or your role here does not let you read notes.
    * `404 not_found` — nothing with that id, about a record you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return DjbNoteOut.model_validate(get_note(tenant=tenant, actor=actor, note_id=note_id))


@router.patch("/{note_id}/", response=DjbNoteOut, url_name="djb_note-update")
@refuses("archived", "forbidden", "invalid", "invalid_body", "no_acting_scope", "not_found")
def update_note_route(request: TenantRequest, note_id: UUID, payload: DjbNotePatch) -> DjbNoteOut:
    """Update a note

    Change the words of a note you wrote.

    Only the person who wrote a note may change it — not an administrator, not
    the owner. The record it is about never changes by an edit. Sending the
    words it already has changes nothing.

    Answers `200` with the note as it now stands.

    Refusals you can get here:

    * `400 invalid` — `body` is empty. `errors` names it.
    * `422 invalid_body` — the body carried a field this endpoint does not accept.
    * `403 forbidden` — you did not write this note.
    * `404 not_found` — nothing with that id, about a record you can see.
    * `409 archived` — the note is archived; restore it first.
    """
    actor, tenant = acting(request)
    note = get_note(tenant=tenant, actor=actor, note_id=note_id)
    return DjbNoteOut.model_validate(
        update_note(tenant=tenant, actor=actor, note=note, body=payload.body)
    )


@router.post("/{note_id}/archive/", response=DjbNoteOut, url_name="djb_note-archive")
@refuses("archive_blocked", "forbidden", "no_acting_scope", "not_found")
def archive_note_route(request: TenantRequest, note_id: UUID) -> DjbNoteOut:
    """Archive a note

    Take a note out of its record's list. It is not deleted: it stays readable by
    id and under `?show=archived`, and it can be restored.

    It takes administrator rights over the part of the organization the note
    lives in. Archiving a note that is already archived answers `200` with the
    note unchanged — safe to retry. It takes no body.

    Refusals you can get here:

    * `403 forbidden` — you do not administer the part of the organization this
      note lives in.
    * `404 not_found` — nothing with that id, about a record you can see.
    * `409 archive_blocked` — something an app declared still holds the note;
      the remedies name each blocker and where to clear it.
    """
    actor, tenant = acting(request)
    note = get_note(tenant=tenant, actor=actor, note_id=note_id)
    return DjbNoteOut.model_validate(archive_note(tenant=tenant, actor=actor, note=note))


@router.post("/{note_id}/restore/", response=DjbNoteOut, url_name="djb_note-restore")
@refuses("forbidden", "no_acting_scope", "not_found", "restore_blocked")
def restore_note_route(request: TenantRequest, note_id: UUID) -> DjbNoteOut:
    """Restore a note

    Put an archived note back in its record's list.

    It takes the same administrator rights as archiving. Restoring a note that
    is not archived answers `200` with the note unchanged — safe to retry. It
    takes no body.

    Refusals you can get here:

    * `403 forbidden` — you do not administer the part of the organization this
      note lives in.
    * `404 not_found` — nothing with that id, about a record you can see.
    * `409 restore_blocked` — something the note depends on is not there for
      it; the remedies name it.
    """
    actor, tenant = acting(request)
    note = get_note(tenant=tenant, actor=actor, note_id=note_id)
    return DjbNoteOut.model_validate(restore_note(tenant=tenant, actor=actor, note=note))
