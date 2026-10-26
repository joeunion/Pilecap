"""How a merge re-points the documents filed against a merged-away record.

Found by `core.verbs.hook("merge_repointers")` — this file is registered nowhere.
The key is `"*"`: a document may be filed against ANY noun that lists `files` in
its `attachments`, so this app answers for every noun a merge can join rather
than naming them (it cannot know a product's nouns, which is why the subject is
polymorphic at all).

`count` is the dry run a merge shows before it is pressed; `repoint` moves the
rows through this app's own service (`services.move_attached_files`), never by
writing them from outside. Both count archived documents too: an archived
document is still filed against its record.
"""

from __future__ import annotations

from typing import Any

from apps.core.authz import kind_of
from apps.core.verbs import Repointer
from apps.files.models import StoredFile
from apps.files.services import move_attached_files


def _count_files(*, tenant: Any, loser: Any) -> int:
    """How many documents are filed against `loser` — the merge's dry run."""
    kind = kind_of(type(loser))
    if kind is None:
        return 0
    # rule-24: a dry-run COUNT over the whole tenant, never a listing — the merge
    # that asks is authorized on both records before anything moves, and a
    # document filed against the loser may sit wherever the record lived when it
    # was filed, so narrowing to one node would under-count what the merge moves.
    return (
        StoredFile.objects.for_tenant(tenant)
        .including_archived()
        .filter(subject_kind=kind, subject_id=loser.pk)
        .count()
    )


def _repoint_files(*, tenant: Any, actor: Any, loser: Any, survivor: Any) -> int:
    """Move them, through this app's own service, and say how many moved."""
    return move_attached_files(tenant=tenant, actor=actor, loser=loser, survivor=survivor)


REPOINTERS: dict[str, Repointer] = {
    "*": Repointer(title="Files", count=_count_files, repoint=_repoint_files),
}
