"""How a merge carries tags from the loser to the survivor, for every noun (`"*"`).

`count` equals what `repoint` answers: a word the survivor carries is deleted, not duplicated.
A noun that takes no tags answers 0 on both, never a refusal.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.verbs import Repointer, takes
from apps.djb_tags.models import ATTACHMENT
from apps.djb_tags.selectors import _subject_tag_links
from apps.djb_tags.services import move_tag_links


def _count_tag_links(*, tenant: Tenant, loser: Any) -> int:
    if not takes(type(loser), ATTACHMENT):
        return 0
    return _subject_tag_links(tenant=tenant, subject=loser).count()


def _repoint_tag_links(*, tenant: Tenant, actor: Actor, loser: Any, survivor: Any) -> int:
    # No link can name a subject that does not take tags (attaching one is
    # refused), so nothing is left behind and no row is looked up to say so.
    if not takes(type(loser), ATTACHMENT):
        return 0
    return move_tag_links(tenant=tenant, actor=actor, loser=loser, survivor=survivor)


REPOINTERS: dict[str, Repointer] = {
    "*": Repointer(title="Tags", count=_count_tag_links, repoint=_repoint_tag_links),
}
