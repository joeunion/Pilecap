"""How a merge moves notes from its loser to its survivor — for every noun.

`core.verbs.hook("merge_repointers")` finds this file; nothing registers it.
The key is `"*"` because a note can be about any noun that declared notes, so
this app re-points notes for every merge, whichever noun is merged. The
merge service calls `count` for its dry run and `repoint` inside its
transaction, and `repoint` calls this app's own service (C3).
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.verbs import Repointer
from apps.djb_notes.selectors import list_notes_pointing_at
from apps.djb_notes.services import move_notes


def _count(*, tenant: Tenant, loser: Any) -> int:
    return int(list_notes_pointing_at(tenant=tenant, loser=loser).count())


def _repoint(*, tenant: Tenant, actor: Actor, loser: Any, survivor: Any) -> int:
    return move_notes(tenant=tenant, actor=actor, loser=loser, survivor=survivor)


REPOINTERS: dict[str, Repointer] = {
    "*": Repointer(title="Notes", count=_count, repoint=_repoint),
}
