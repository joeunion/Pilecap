"""The names of the things this app says happened.

Names only. `services.py` emits each one inside the write's transaction, with
the note as the REST door renders it (`NoteOut`), so a webhook subscriber and a
client reading the same note see one shape.

`djb_notes.note.moved` is said once per note a merge re-points from its loser to
its survivor: the note's subject and its organization both changed, and a
subscriber following that note hears where it went.
"""

from __future__ import annotations

NOTE_CREATED = "djb_notes.note.created"
NOTE_UPDATED = "djb_notes.note.updated"
NOTE_ARCHIVED = "djb_notes.note.archived"
NOTE_RESTORED = "djb_notes.note.restored"
NOTE_MOVED = "djb_notes.note.moved"

#: The event grammar's noun is the short word; the model's authorization kind
#: carries the template's `djb_` prefix (so a product's own `Note` keeps the
#: kind its class name derives). This maps the one to the other, so a socket
#: can still ask who may hear each event.
EVENT_KINDS: dict[str, str | None] = {
    "note": "djb_note",
}
