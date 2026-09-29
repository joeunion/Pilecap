"""How a merge carries tags from the loser to the survivor — for EVERY noun.

`"*"` because a link's subject is polymorphic: whatever noun two rows are
merged in, the links pointing at the loser are this app's rows, and this app
moves them. The merge (`core.verbs`) asks `count` for the dry run and calls
`repoint` inside its own transaction, after its own reach and policy checks on
both rows; `repoint` still re-resolves both through this app's service, which
calls its own authorization — a merge never writes a link except through
`services.py`.

**`count` equals what `repoint` answers.** The dry run cannot see the survivor,
so it counts the loser's links; `repoint` answers the same number because every
one of them leaves the loser — moved, or, when the survivor already carries
that word, deleted rather than duplicated (the unique `(tag, subject)` pair).

**A noun that does not take tags answers 0 on both**, never a refusal — the
merge of a noun without `tags` in its `attachments` is not this app's to stop.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.verbs import Repointer
from apps.djb_tags.selectors import _subject_tag_links, _takes_tags
from apps.djb_tags.services import move_tag_links


def _count(*, tenant: Tenant, loser: Any) -> int:
    if not _takes_tags(type(loser)):
        return 0
    return _subject_tag_links(tenant=tenant, subject=loser).count()


def _repoint(*, tenant: Tenant, actor: Actor, loser: Any, survivor: Any) -> int:
    # No link can name a subject that does not take tags (attaching one is
    # refused), so nothing is left behind and no row is looked up to say so.
    if not _takes_tags(type(loser)):
        return 0
    return move_tag_links(tenant=tenant, actor=actor, loser=loser, survivor=survivor)


REPOINTERS: dict[str, Repointer] = {
    "*": Repointer(title="Tags", count=_count, repoint=_repoint),
}
