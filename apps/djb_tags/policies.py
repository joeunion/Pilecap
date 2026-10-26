"""Who may do what with a tag and a link. **Policies are code; roles are DATA.**

Found by discovery (`core.authz`); never registered anywhere.

**The words are the root's.** `djb_tag.create` and `djb_tag.update` carry no predicate,
so they are held by `owner` (the vocabulary) and `admin` (`*`) — and the
services ask them at the tenant's ROOT (house rule 55), so the people who coin,
respell and retire the tenant's words are the people who administer the whole
tenant. A branch administrator reads every tag and changes none of them.
`djb_tag.archive` / `djb_tag.restore` are `core.policies.may_archive`, which asks a
tenant-scoped row at the root too and refuses the system actor
(`@refuses_system`): a workflow does not retire a word on its own say-so.

**Links are anybody's who can see the subject.** Tagging a row is ordinary
work, so `djb_tag_link.create` and `djb_tag_link.delete` ask only that the actor belongs
to the tenant — the subject has already been resolved through the acting hat's
`visible_to` and `may_be_named` (`core.verbs.resolve_subject`) before this runs,
so a row the actor cannot reach is `not_found` long before this question.

`djb_tag_link.update` (moving links when two subjects merge) has no predicate, so it
is an administrator's, which is who may merge at all.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for
from apps.core.policies import may_archive


def may_tag(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may put a word on, or take it off, a row they can reach."""
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    "djb_tag.archive": may_archive,
    "djb_tag.restore": may_archive,
    "djb_tag_link.create": may_tag,
    "djb_tag_link.delete": may_tag,
}

#: The keys `member` holds by declaration; each predicate above still narrows its key.
DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "djb_tag.archive": frozenset({"member"}),
    "djb_tag.restore": frozenset({"member"}),
    "djb_tag_link.create": frozenset({"member"}),
    "djb_tag_link.delete": frozenset({"member"}),
}

ACTION_PROSE: dict[str, str] = {
    "djb_tag.create": "You may not coin tags for this tenant.",
    "djb_tag.update": "You may not rename that tag.",
    "djb_tag.archive": "You may not archive that tag.",
    "djb_tag.restore": "You may not restore that tag.",
    "djb_tag_link.create": "You may not tag that.",
    "djb_tag_link.delete": "You may not remove that tag.",
    "djb_tag_link.update": "You may not move those tags.",
}
