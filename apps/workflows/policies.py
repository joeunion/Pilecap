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

    Not privileged-only: signalling is a write, `member` is declared
    `("*.read",)`, and a plain member approving their own widget is the ordinary
    case the domain policy above already ruled on. What admits them is the
    compat residue — a key with a predicate and no `DEFAULT_ROLES` declaration
    is held by every declared role and the predicate narrows it
    (`core.authz._attach_default_roles`, clause 5) — so this line is what keeps
    the answer where it was through the transition, in a layer that cannot see
    the row and therefore should not be deciding about it.
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
    """Membership in the acting tenant. **The ownership half is not here.**

    `start_replay` refuses a run this actor did not start, with `not_found`,
    and it does that in the service rather than in this predicate on purpose. A
    policy answers "may this person do this kind of thing here"; it is handed
    the row, so it *could* compare `started_by` — but `require` raises
    `Forbidden`, and a `Forbidden` on somebody else's run confirms that the run
    exists, which is the one thing the tenant wall was hiding. Refusals are
    decided where the right *answer* can be given, not wherever the data
    happens to be in reach.

    A replay re-executes work, so this is a write and `member` — declared
    `("*.read",)` — reaches it only through the compat residue this line is what
    narrows (`belongs_to_the_tenant` above says the mechanism). That is
    deliberate: the person who started the run is the person who watches it
    fail, and telling them to find an admin to press the button again is how a
    ledger with a replay door still leaves the work undone. **The day this app's
    residue is converted to a `DEFAULT_ROLES` declaration, that sentence is what
    the declaration has to preserve**, and it is written here rather than left
    to be re-derived.
    """
    return membership_for(actor) is not None


def may_cancel_their_own(actor: Actor, obj: Any = None) -> bool:
    """Membership in the acting tenant. **The ownership half is not here either.**

    `may_replay_their_own`'s reasoning verbatim, and it is repeated as a named
    function rather than aliased because these are two decisions that happen to
    agree today: a product that lets a person stop their own job but not re-run
    it — or the other way round — changes one of these and not both, and an
    alias would make that a rename instead of an edit.

    `cancel_run` refuses a run this actor did not start, with `not_found`, in
    the service. The predicate is handed the row and could compare `started_by`
    itself; it does not, because `require` raises `Forbidden` and a `Forbidden`
    on somebody else's run confirms that the run exists — the one fact the
    tenant wall was keeping.

    Stopping work is a write, so a plain member reaches it through the same
    compat residue replay's docstring names, narrowed by this line. Deliberate,
    and the same argument replay makes: the person who started the job is the
    person watching it run away with itself, and telling them to find an admin
    is how a ledger with a cancel door still leaves the job running.
    """
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    "workflow_run.signal": belongs_to_the_tenant,
    "workflow_run.replay": may_replay_their_own,
    "workflow_run.cancel": may_cancel_their_own,
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
