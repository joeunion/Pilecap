"""The names of the things this app says happened.

Names only. `services.py` emits each one inside the write's transaction, with
the note as the REST door renders it (`NoteOut`), so a webhook subscriber and a
client reading the same note see one shape.

`notes.note.moved` is said once per note a merge re-points from its loser to
its survivor: the note's subject and its organization both changed, and a
subscriber following that note hears where it went.
"""

from __future__ import annotations

NOTE_CREATED = "notes.note.created"
NOTE_UPDATED = "notes.note.updated"
NOTE_ARCHIVED = "notes.note.archived"
NOTE_RESTORED = "notes.note.restored"
NOTE_MOVED = "notes.note.moved"
