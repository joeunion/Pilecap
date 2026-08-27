"""Who may read, signal, replay or stop a run. Policies are code; roles are data.

Every predicate here answers the same way, and it is deliberately the weakest
rule in the tree: **anybody who belongs to the acting tenant may do it.** That
is not laxness, it is a division of labour, and it is worth saying plainly
because the shape is easy to get wrong in the other direction. Two of the four
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

    Not `is_read`-by-default and not privileged-only: signalling is a write, so
    the role fallback in `core.authz` would refuse a plain member — and a plain
    member approving their own widget is the ordinary case the domain policy
    above already ruled on. Naming the action here is what stops the fallback
    from making that decision twice, in a layer that cannot see the row.
    """
    return membership_for(actor) is not None


def may_read_the_ledger(actor: Actor, obj: Any = None) -> bool:
    """Anybody who belongs to the acting tenant may read that tenant's runs.

    Named rather than left to the role fallback, even though `read` is one of
    `core.authz`'s READ_VERBS and a plain member would have passed anyway. The
    fallback is a *default*, and a default is a decision nobody wrote down; the
    run ledger is the product's record of what it did on somebody's behalf, and
    a product that wants that narrower — owners and admins only, say — changes
    this function and nothing else.

    It is not narrowed to the reader's own runs, and that is the shape (ADR
    workflows-6): the door defaults to the caller's own work because that is
    what a person is looking for, and the ledger stays *tenant*-wide because
    "who in my company started that sync" is exactly the question a ledger
    exists to answer. What is narrowed to the actor's own is **replay**, and it
    is narrowed by `started_by` in the service rather than here — see below.
    """
    return membership_for(actor) is not None


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

    A replay re-executes work, so this is a write and a plain member reaches it
    only because this line says so — the role fallback would have refused. That
    is deliberate: the person who started the run is the person who watches it
    fail, and telling them to find an admin to press the button again is how a
    ledger with a replay door still leaves the work undone.
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

    Stopping work is a write, so a plain member reaches it only because this
    line says so; the role fallback would have refused. Deliberate, and the same
    argument replay makes: the person who started the job is the person watching
    it run away with itself, and telling them to find an admin is how a ledger
    with a cancel door still leaves the job running.
    """
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    "workflow.signal": belongs_to_the_tenant,
    "workflowrun.read": may_read_the_ledger,
    "workflowrun.replay": may_replay_their_own,
    "workflowrun.cancel": may_cancel_their_own,
}


# The sentence a refused caller reads, per action. See `core/policies.py`.
# "Background job" and not "workflow run": the caller sees a thing that is
# running somewhere without them, which is what the word means to them, and the
# API document's runs section uses the same words.
ACTION_PROSE: dict[str, str] = {
    "workflow.signal": "You may not send that to a background job in this tenant.",
    "workflowrun.read": "You may not read this tenant's background jobs.",
    "workflowrun.replay": "You may not run that background job again.",
    "workflowrun.cancel": "You may not stop that background job.",
}
