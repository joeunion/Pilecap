"""Who may signal, replay or stop a run. Policies are code; roles are data.

**The four keys are `workflow_run.*` since P7.8**, which is the kind
`WorkflowRun` derives; `workflow.signal` and the three `workflowrun.*` spellings
still answer, as aliases, through `RENAMED_PERMISSIONS` below. **And READING is
no longer here at all** — `workflow_run.read` is a permission the vocabulary
resolves and a tenant's own rows narrow (ADR core-27); the retirement note where
`may_read_the_ledger` stood says why that is the same decision this file used to
make, made somewhere a customer can reach.

Every predicate that remains answers the same way, and it is deliberately the
weakest rule in the tree: **anybody who belongs to the acting tenant may do it.**
That is not laxness, it is a division of labour, and it is worth saying plainly
because the shape is easy to get wrong in the other direction. Two of the three
are then narrowed by whose run it is — replay and cancel — and that narrowing
is in the SERVICE and not here, for the reason each of those docstrings gives:
`require` raises `Forbidden`, and a `Forbidden` on somebody else's run confirms
the run exists.

`WorkflowRun` is a *visibility* row. It has a tenant and it has an id; it has
no organization column and no idea what business object the run is about — a
run for a widget, an invoice and a re-parent are the same three columns here.
So this layer can enforce exactly what it can see: the tenant wall (the scoped
read), the id wall (`check_workflow_id`), and "you are somebody in this
tenant".

**Object-level authorization belongs to the domain caller.** `example.
approve_widget` requires `widget.approve` over the *widget's* organization
before it ever reaches `signal_workflow`, and that is where the question "may
*this* person approve *that* row" can actually be answered, because that is the
only layer that holds the row. A product that lets a door call
`signal_workflow` directly, with no domain service in front of it, has skipped
that check — which is a house rule 13 review finding about the door, not
something this file can put back.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for


def belongs_to_the_tenant(actor: Actor, obj: Any = None) -> bool:
    """Any membership in the acting tenant, of any role, at any node.

    `member` holds the key by `DEFAULT_ROLES` below; object-level authorization is the caller's.
    """
    return membership_for(actor) is not None


# `may_read_the_ledger` was here, and PR4.i retired it rather than re-keying it.
#
# It answered `membership_for(actor) is not None`, and its docstring's argument
# was that the role fallback is *a default, and a default is a decision nobody
# wrote down* — so the run ledger should name its own bar, and a product that
# wanted it narrower should change one function.
#
# ADR core-27 grants that argument in full and gives it a better home. A read is
# a permission like any other now: `workflow_run.read` is held by `owner` (the
# vocabulary), by `admin` (`("*",)`), by `member` (`("*.read",)`), by whatever a
# custom role includes and by an `allow` grant — and a `withhold` subtracts it.
# So the bar is written down, in `apps/core/roles.py` where a product edits it,
# and it is narrowable **per tenant, in a running deployment, by an
# administrator writing a row** rather than per deployment by an engineer
# editing this file. A predicate that asked for a membership on top of that
# would be a second copy of the question `effective_permissions` has already
# answered: a person with no membership in the tenant holds nothing, so the
# predicate could only ever agree with it or be wrong.
#
# What has NOT moved is the shape ADR workflows-6 rules on: the ledger is
# tenant-wide, not narrowed to the reader's own runs, because "who in my company
# started that sync" is the question a ledger exists to answer. The door's
# `mine=True` default is where "my own work" lives, and `started_by` in the
# service is where replay and cancel are narrowed.


def may_replay_their_own(actor: Actor, obj: Any = None) -> bool:
    """Membership in the acting tenant; the ownership half is `start_replay`'s, as `not_found`.

    Why-not here: `require` raises `Forbidden`, which would confirm another person's run exists.
    `member` holds the key by `DEFAULT_ROLES`: whoever started the run may press it again.
    """
    return membership_for(actor) is not None


def may_cancel_their_own(actor: Actor, obj: Any = None) -> bool:
    """Membership in the acting tenant; the ownership half is `cancel_run`'s, as `not_found`.

    Kept apart from `may_replay_their_own` so a product can narrow one without the other.
    `member` holds the key by `DEFAULT_ROLES`: whoever started the run may stop it.
    """
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    "workflow_run.signal": belongs_to_the_tenant,
    "workflow_run.replay": may_replay_their_own,
    "workflow_run.cancel": may_cancel_their_own,
}

# The member half of the three run writes, as data; the predicates above and the services narrow it.

DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "workflow_run.signal": frozenset({"member"}),
    "workflow_run.replay": frozenset({"member"}),
    "workflow_run.cancel": frozenset({"member"}),
}


#: The four keys this app renamed when the vocabulary became one shape, and the
#: WHOLE cost of renaming one: a line here (ADR core-25). `core.authz.allows`
#: resolves an alias one line BEFORE the policy lookup, so a product still
#: calling `require(actor, "workflowrun.cancel", run)` — or holding a `Grant`
#: row that names it — gets exactly the answer it got before, with one
#: deprecation printed per process. `manage.py rename_permission` is what
#: rewrites rows once a deployment has grants.
#:
#: **Every one of the four named a kind that does not exist.** `WorkflowRun`
#: derives `workflow_run`; `workflowrun` is the same word with the boundary
#: filed off and `workflow` is not a noun this platform has a row for. That was
#: not cosmetic while it lasted: a key whose kind names no row skips the data
#: half of `allows` entirely, so a role's collection could not carry one of
#: these and a `Grant` withhold on one was a row that was written, was read back
#: by the role editor, and changed no answer anywhere.
#:
#: The sentences below did not move by one byte.
RENAMED_PERMISSIONS: dict[str, str] = {
    "workflow.signal": "workflow_run.signal",
    "workflowrun.read": "workflow_run.read",
    "workflowrun.replay": "workflow_run.replay",
    "workflowrun.cancel": "workflow_run.cancel",
}


# The sentence a refused caller reads, per action. See `core/policies.py`.
# "Background job" and not "workflow run": the caller sees a thing that is
# running somewhere without them, which is what the word means to them, and the
# API document's runs section uses the same words.
#
# `workflow_run.read` is the one of the four the model registry DERIVES, so its
# line here is a sentence override rather than a declaration (`decided_by` stays
# `derived`) — and it is worth having, because the derived sentence assembled
# from `verbose_name` would say "workflow run" to a reader the whole rest of
# this door speaks to about background jobs.
ACTION_PROSE: dict[str, str] = {
    "workflow_run.signal": "You may not send that to a background job in this tenant.",
    "workflow_run.read": "You may not read this tenant's background jobs.",
    "workflow_run.replay": "You may not run that background job again.",
    "workflow_run.cancel": "You may not stop that background job.",
}
