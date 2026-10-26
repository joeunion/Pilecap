"""Who may ask for an archive, and who may read one. Policies are code, found by discovery.

A subtree export is any member's; a tenant-wide one takes an administrator at the root.
The tenant-wide bar is erasure's predicate: two acts that reach a whole tenant share one ceiling.
`export.read` comes from `member`'s `*.read`; `export.build` from `admin`'s `*`, at the row's node.
"""

from __future__ import annotations

from typing import Any

from apps.accounts.policies import administers_the_whole_tenant
from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for
from apps.exports.models import Export


def can_request(actor: Actor, obj: Any = None) -> bool:
    """A tenant-wide archive takes an administrator at the top; any other, a membership.

    `obj is None` is the abstract question — may this actor export at all — answered by membership.
    """
    if isinstance(obj, Export) and obj.scope == Export.Scope.TENANT:
        return administers_the_whole_tenant(actor, obj)
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    # One key, two bars — see `can_request`. Splitting it into
    # `export.create_tenant` and `export.create_organization` was the
    # alternative and it is worse: the two would be one act with two names, and
    # `introspect`'s action list would suggest a caller picks between them.
    "export.create": can_request,
}


# The one key this app renamed when the vocabulary became one shape, and the
# WHOLE cost of renaming one (ADR core-25). `core.authz.allows` resolves an
# alias one line BEFORE the policy lookup, so a product still calling
# `require(actor, "export.request", export)` gets exactly the answer it got
# before — never the role default, which is what an alias resolved after the
# lookup would have handed it. `manage.py rename_permission` rewrites a
# deployment's `Grant` and `RolePermission` rows once it has any.
#
# `request` was the CRUD verb the act already was: asking for an archive creates
# an `Export` row. The sentence below did not move by one byte.
RENAMED_PERMISSIONS: dict[str, str] = {
    "export.request": "export.create",
}

DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "export.create": frozenset({"member"}),
}


# The sentence a refused caller reads, per action. A product declares these
# beside its policies and never edits `core`; see `core/policies.py` for the
# register. These three override the sentence the vocabulary would derive from
# the model's own `verbose_name`, which is what an app declaring prose for a
# derived key is for.
ACTION_PROSE: dict[str, str] = {
    "export.create": (
        "You may not export the whole tenant. Exporting everything your own "
        "organization can see needs no special permission; exporting the whole "
        "tenant needs administrator rights at the top of it."
    ),
    "export.read": "You may not read that export.",
    "export.build": "You may not build or close out that export.",
}
