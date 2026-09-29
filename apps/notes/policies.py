"""Who may write, edit and archive a note. Policies are code; roles are data.

`core.authz.require(actor, "note.update", note)` finds this by discovery. The
rule for this app is three sentences:

* **anybody in the tenant may write a note** about a row they can see — which
  rows they can see is already answered by `core.verbs.resolve_subject` before
  this is asked;
* **only the author edits a note** — not an administrator, not the owner. A
  note is one person's words, and an edit by somebody else would put words in
  their mouth under their name;
* **archive and restore are an administrator's press** (`core.policies.
  may_archive`), asked at the note's own organization, and never the system's.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for
from apps.core.policies import may_archive


def can_write(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may write a note about a row they can reach."""
    return membership_for(actor) is not None


def is_author(actor: Actor, obj: Any = None) -> bool:
    """The note's author, and nobody else.

    **`obj is None` is no**: there is no "may edit notes in general" — the
    question is always about one note and whose words it holds.
    """
    if obj is None or actor.user is None:
        return False
    return bool(getattr(obj, "author_id", None) == actor.user.pk)


POLICIES: dict[str, Policy] = {
    "note.create": can_write,
    "note.update": is_author,
    "note.archive": may_archive,
    "note.restore": may_archive,
}


ACTION_PROSE: dict[str, str] = {
    "note.create": "You may not write notes in this organization.",
    "note.update": "Only the person who wrote that note may change it.",
    "note.archive": "You may not archive that note.",
    "note.restore": "You may not restore that note.",
}
