"""Who may ask for an archive, and who may read one. Policies are code.

`core.authz.require(actor, "export.request", ...)` finds these by discovery —
this file is never registered anywhere. The keys are `<noun>.<verb>`, the
predicates take the acting `Actor` and the object, and they return a bool.

**The interesting rule here is that there are two bars, not one, and the wide
one is somebody else's predicate.**

A **subtree** export is free. Not "cheap" — free: the walk reads
`for_tenant(t).visible_to(org)`, which is the same predicate that already
decides every list this actor can see at every door, so an export of their own
subtree hands them nothing they could not have paged through one request at a
time. Putting a role bar on that would be a permission that protects nothing
and that somebody would eventually be asked to widen.

A **tenant-wide** export is a different act. It is one file containing every
row every part of the customer owns, and no branch of a tenant owns that reach —
so the bar is `accounts.policies.administers_the_whole_tenant`: `admin` or
better **at the tenant's root**, which fails closed on an actor with no resolved
hat because there is no subtree for "no hat" to be inside.

**Reusing erasure's predicate rather than writing a second one is the point.**
Erasure and export are the two acts in this product that reach a whole tenant at
once, and two predicates that mean the same thing are two predicates that will
one day disagree — one of them widened by somebody who did not know the other
existed. If the ceiling on "reach the whole tenant" ever moves, it moves in one
place.
"""

from __future__ import annotations

from typing import Any

from apps.accounts.policies import administers_the_whole_tenant
from apps.core.actor import Actor
from apps.core.authz import ADMIN_RANK, Policy, actor_role, membership_for, rank
from apps.exports.models import Export


def can_request(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may export their own subtree; the root's takes admin.

    `obj` is the `Export` being asked for — the row the service has built and
    not yet saved — so the predicate reads the **scope** off the thing being
    authorized rather than off a second argument. That is what lets one action
    key carry two bars honestly: the question really is one question ("may this
    actor make this export"), and the answer depends on a property of the object
    exactly as `widget.approve`'s depends on the widget's branch.

    `obj is None` is the abstract question — "could I export at all?" — and it is
    answered by membership, because every member can export their own subtree.
    """
    if isinstance(obj, Export) and obj.scope == Export.Scope.TENANT:
        return administers_the_whole_tenant(actor, obj)
    return membership_for(actor) is not None


def can_read(actor: Actor, obj: Any = None) -> bool:
    """Anybody in the tenant who can see the row may read it and fetch it.

    Deliberately plain, and the reason is that the row has already been through
    the acting hat's `visible_to` at the door: an export made at a branch this
    actor holds no membership over is `not_found` long before this predicate
    runs, because not-there and not-yours are one answer. What is left to ask is
    only whether they belong to the tenant at all.

    **What this does NOT re-ask is whether they could have made it.** A member
    who is handed a tenant-wide archive their owner made can download it, and
    that is the correct reading: the archive exists, it is in their branch's
    list because their owner put it there, and a second bar here would be a
    permission check on a file whose contents have already been decided.
    """
    return membership_for(actor) is not None


def can_build(actor: Actor, obj: Any = None) -> bool:
    """An owner or admin **over the export's own branch**.

    The run does this as the system, and `core.authz.allows` answers a system
    actor before it reads a policy at all — so in the tree as it stands this
    predicate is never consulted. It is written anyway, for the reason
    `example.policies`' `widget.onboard` entry gives about itself: the day
    somebody is given a button that rebuilds a stuck export by hand, the rule it
    has to obey is already written down, and an action with no policy is
    invisible in `introspect`.

    The role is read over the ROW's organization rather than over the actor's
    hat, like `widget.approve` and for the same reason: the row already exists,
    and what is being asked is how much authority the actor holds where it
    lives.
    """
    if obj is None:
        return _is_privileged(actor)
    return rank(actor_role(actor, getattr(obj, "organization", None))) >= ADMIN_RANK


def _is_privileged(actor: Actor) -> bool:
    membership = membership_for(actor)
    return membership is not None and membership.is_privileged


POLICIES: dict[str, Policy] = {
    # One key, two bars — see `can_request`. Splitting it into
    # `export.request_tenant` and `export.request_organization` was the
    # alternative and it is worse: the two would be one act with two names, and
    # `introspect`'s action list would suggest a caller picks between them.
    "export.request": can_request,
    "export.read": can_read,
    # The run's own writes — starting the walk, recording the archive, recording
    # a failure. See `can_build`: the system reaches these and a person does
    # not, today.
    "export.build": can_build,
}


# The sentence a refused caller reads, per action. A product declares these
# beside its policies and never edits `core`; see `core/policies.py` for the
# register.
ACTION_PROSE: dict[str, str] = {
    "export.request": (
        "You may not export the whole tenant. Exporting everything your own "
        "organization can see needs no special permission; exporting the whole "
        "tenant needs administrator rights at the top of it."
    ),
    "export.read": "You may not read that export.",
    "export.build": "You may not build or close out that export.",
}
