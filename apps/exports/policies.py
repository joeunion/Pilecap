"""Who may ask for an archive, and who may read one. Policies are code.

`core.authz.require(actor, "export.create", ...)` finds these by discovery —
this file is never registered anywhere. The keys are `<kind>.<verb>` over the
kind `Export` derives, the predicates take the acting `Actor` and the object,
and they return a bool.

**After the sweep there is exactly ONE predicate here, and it asks no role.**
That is the shape §C7 asks for: a predicate answers *may this person do this to
THAT row*, never *how much authority does this person have*. Both role reads
this file used to make are gone; what `admin` and `member` are is
`apps/core/roles.py`'s, and a tenant's own `Role`, `RolePermission` and `Grant`
rows compose with it. One owner (principle 9).

**DEFERRED, by the PM's ruling of 2026-09-16, and named here so it is not
mistaken for an oversight: `can_request` still admits any membership.** The
sweep's shape puts that half in `DEFAULT_ROLES` — "a `member` holds
`export.create`" as data rather than as a predicate — and a `DEFAULT_ROLES`
entry moves what `defaults_for("member")` answers, which is a pin of the flat
product (`apps/core/tests/test_vocabulary.py`) that no per-app sweep may move
alone. Eight sweeps each moving it eight times is eight collisions on one file;
one later rung moving it once is one. So the membership half stays as
transitional residue here, `member` goes on holding `export.create` through the
vocabulary's own compat column, and every cell of this app's authorization
matrix is unmoved — which `tests/authz_baseline.json` measures rather than
claims.

**The interesting rule here is that there are two bars, not one, and the wide
one is somebody else's predicate.**

A **subtree** export is free. Not "cheap" — free: the walk reads
`for_tenant(t).visible_to(org)`, which is the same predicate that already
decides every list this actor can see at every door, so an export of their own
subtree hands them nothing they could not have paged through one request at a
time. Putting a role bar on that would be a permission that protects nothing
and that somebody would eventually be asked to widen — so there is no role bar,
and the predicate asks only whether the actor belongs to the tenant at all.

A **tenant-wide** export is a different act. It is one file containing every
row every part of the customer owns, and no branch of a tenant owns that reach —
so the bar is `accounts.policies.administers_the_whole_tenant`: `admin` or
better **at the tenant's root**, which fails closed on an actor with no resolved
hat because there is no subtree for "no hat" to be inside. That is a property of
the ROW being asked about (its `scope`), which is why it is a predicate at all.

**Reusing erasure's predicate rather than writing a second one is the point.**
Erasure and export are the two acts in this product that reach a whole tenant at
once, and two predicates that mean the same thing are two predicates that will
one day disagree — one of them widened by somebody who did not know the other
existed. If the ceiling on "reach the whole tenant" ever moves, it moves in one
place. (It is still a rank read today; it lives in `apps/accounts/policies.py`
and P8 is the rung that sweeps it.)

**What became of the two predicates this file used to carry.**

**Both retired predicates had NO row half, which is why they could go now
while `can_request`'s membership half waits.**

* `can_read` asked "does this actor carry a membership in the tenant", and never
  looked at the export. The role layer answers that already: `member` holds
  `*.read` by its declared pattern — no `DEFAULT_ROLES` entry needed, so no pin
  moves — and WHICH rows they see is still rule 24's
  `for_tenant(t).visible_to(org)` at the selector. A predicate that re-asked it
  would be a second, weaker opinion in a place where the two could disagree.
* `can_build` asked for `admin` or better **at the export's own organization**.
  The node half of that was never the predicate's: `core.authz.where_of` asks
  the question at the row's own node, so "admin at the export's branch" is
  exactly `admin` holding `export.build` there — held by `*`, and by no pattern
  a `member` has. The reason the action still has a SENTENCE and no predicate is
  unchanged from when it had one: the day somebody is given a button that
  rebuilds a stuck export by hand, the rule it has to obey is already written
  down, and an action nobody declared is invisible in `introspect`.
"""

from __future__ import annotations

from typing import Any

from apps.accounts.policies import administers_the_whole_tenant
from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for
from apps.exports.models import Export


def can_request(actor: Actor, obj: Any = None) -> bool:
    """A tenant-wide archive takes an administrator at the top. **Row-only.**

    `obj` is the `Export` being asked for — the row the service has built and
    not yet saved — so the predicate reads the **scope** off the thing being
    authorized rather than off a second argument. That is what lets one action
    key carry two bars honestly: the question really is one question ("may this
    actor make this export"), and the answer depends on a property of the object
    exactly as `widget.approve`'s depends on the widget's branch.

    `obj is None` is the abstract question — "could I export at all?" — and it is
    answered by membership, because every member can export their own subtree.

    **That membership half is DEFERRED, not kept on purpose** — see the module
    docstring's last paragraph and the PM's ruling of 2026-09-16.
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
