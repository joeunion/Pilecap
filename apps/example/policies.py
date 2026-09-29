"""Who may do what to a widget. **Policies are code; roles are DATA.**

`core.authz.require(actor, "widget.update", widget)` finds these by discovery —
this file is never registered anywhere. The keys are `<kind>.<verb>`, and the
predicates take the acting `Actor` and the object, and return a bool.

**What the Phase-W sweep changed here, and why no caller can see it.** This file
used to answer two different questions with one mechanism. *"Is this person the
record's owner?"* is a question about a ROW, and it belongs in code beside the
model, because a role cannot say "of their own" — a role does not know which row
you meant. *"How much authority does this person hold here?"* is a question
about DATA, and it did not belong here at all: it was read off `Membership.role`
through a rank table nobody's tenant can edit, which is a second opinion about
the rows the role editor writes (house rule 54 (c), principle 9).

So every place that read a role by value now asks
`holds(actor, "widget_policy.create", at=...)` instead — the same question said
in the vocabulary, resolved through the same three layers (`owner` is the
vocabulary, `admin` is `("*",)`, a tenant's own `Role`/`RolePermission`/`Grant`
rows compose on top). A widget *policy* is this branch's widget configuration,
so "may set it here" IS "administers widgets here", and unlike the rank table it
is something a tenant can hand out, narrow or withhold.

**The matrix is the proof, not this paragraph.** `tests/authz_baseline.json` is
the 105-cell census of this app's keys × {owner, admin, member} × five object
states, derived on the tree before the sweep by `tests/authz_matrix.py`;
`tests/test_authz_sweep.py` re-derives it here and asserts equality. A sentence
about "no behaviour change" that no instrument re-runs is a hypothesis wearing a
status.

**What this sweep deliberately did NOT do** (PM ruling, 2026-09-16): the other
half of the sweep — moving "a member may create a widget" and "a member may add
a ledger line" out of `can_create`/`can_record_entry` and into a `DEFAULT_ROLES`
mapping — is DEFERRED to one later rung, because any `DEFAULT_ROLES` entry moves
`defaults_for("member")` and two pins of the flat product in
`apps/core/tests/test_vocabulary.py` read that value directly. Until then the
compat residue admits `member` exactly as it always has, and the two predicates
below stay as they are: they read a MEMBERSHIP's existence, which is not a role,
so rule 54 (c) has nothing to say about them either way.

**Approval is still the interesting one.** `widget.approve` is not "a member may
act on their own" — approving your own work is precisely what an approval step
exists to prevent — so it asks the authority question instead, and asks it *over
the widget's own branch*: an administrator of Seller A may approve a widget at
Sub A1 because authority inherits downwards, and an administrator of Sub A1 may
not approve one at Seller A because nothing inherits up. That sentence used to
be a rank comparison; it is now one `holds(...)` at the node the row names.
"""

from __future__ import annotations

from typing import Any

# golden: archive version move bulk history duplicate attach merge import begin
from apps.core.authz import Policy
from apps.core.policies import may_archive

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.core.policies import may_move

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.core.policies import may_merge

# golden: merge import end
# isort: split
from apps.core.actor import Actor
from apps.core.authz import holds, membership_for

#: The key that means "administers widgets in this branch", asked wherever this
#: file used to compare a role. It is this app's own key on purpose: a product
#: app reaching into `core`'s vocabulary for an administrative bar would make
#: every such predicate depend on a key `core` is free to rename, and the whole
#: point of the sweep is that the authority question has ONE owner per app.
#:
#: It resolves to `admin` (by its `("*",)` pattern) and `owner` (by the
#: vocabulary) on the template, which is exactly who the rank comparison
#: admitted — and to whoever else a tenant's own role rows name, which is what
#: the rank comparison could never express.
ADMINISTERS_WIDGETS = "widget_policy.create"


def _is_member(actor: Actor) -> bool:
    """Whether this actor belongs to the tenant at all.

    Membership is not a role and this is not the authority question: it asks
    whether there is anybody there, which is the bar two of this app's verbs
    have always had. `core.authz` reads the role; this reads the row's
    existence, and rule 54 (c) is about the first.
    """
    return membership_for(actor) is not None


def can_create(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may create a widget; they own what they create."""
    return _is_member(actor)


def owns(actor: Actor, obj: Any = None) -> bool:
    """The record's owner — or somebody who administers widgets in this branch.

    The first half is the app's own sentence and the reason this file exists at
    all: *a member may act on their own records*. `owner_id` is a column, the
    question is about one row, and no role can express it.

    The second half is the authority question, and it is now asked rather than
    computed: `holds(actor, ADMINISTERS_WIDGETS)` at the **acting hat**, which
    is where the predicate it replaced looked too — the actor's own standing,
    not the row's branch. `can_approve` below is the one that asks at the row's
    node, and the difference between the two is deliberate.

    **`obj is None` is the capability in the abstract** — "could I edit widgets
    at all?" — and it falls to the second half alone, exactly as it did before.
    """
    if (
        obj is not None
        and actor.user is not None
        and getattr(obj, "owner_id", None) == actor.user.pk
    ):
        return True
    return holds(actor, ADMINISTERS_WIDGETS)


def can_approve(actor: Actor, obj: Any = None) -> bool:
    """Somebody who administers widgets **over the widget's own branch**.

    Not the widget's owner: see the module docstring. The node is the row's
    rather than the actor's hat, because the row already exists and authority
    inherits downwards — which is one `at=` argument, where it used to be a rank
    read against a role resolved at that node.

    It costs nothing extra: the actor cannot see the row at all unless
    `visible_to` already let it through, so the only question left is how much
    authority they hold where the row lives.
    """
    if obj is None:
        return holds(actor, ADMINISTERS_WIDGETS)
    return holds(actor, ADMINISTERS_WIDGETS, at=getattr(obj, "organization", None))


def can_record_entry(actor: Actor, obj: Any = None) -> bool:
    """Anyone who can see the widget may add a line to its ledger.

    Deliberately the plainest rule in this file, and the reason is the model:
    `WidgetEntry` is `append_only`, so a line cannot be edited or removed, and
    the row it lands on is `derive_org_from`'d to the widget's own branch. There
    is nothing here to escalate — the worst a member can do is append a line
    that names them.

    `obj` is the **widget**, and it has already been through the acting hat's
    `visible_to` at the door: a widget this actor could not see is `not_found`
    long before this predicate runs. What is left to ask is only whether they
    belong to the tenant at all.
    """
    return _is_member(actor)


# golden: archive version move bulk history duplicate attach merge import begin
POLICIES: dict[str, Policy] = {
    # golden: archive version move bulk history duplicate attach merge import end
    "widget.create": can_create,
    "widget.update": owns,
    "widget.delete": owns,
    # Onboarding is the product acting for itself: the workflow's activities run
    # as the system actor, which `core.authz` allows before it reads a policy at
    # all. The entry is here anyway, because the day a person is given a button
    # that onboards a widget by hand, the rule it has to obey is already written
    # — and because an action with no policy is invisible in `introspect`.
    "widget.onboard": owns,
    # The one verb that is not "your own": see `can_approve`.
    "widget.approve": can_approve,
    # The ledger. Append-only and landing-gated, so the bar is membership.
    "widget_entry.record": can_record_entry,
    # A policy leaves the book the way a widget does: an administrator's press
    # at the node that set it, never the system's.
    "widget_policy.archive": may_archive,
    "widget_policy.restore": may_archive,
    # Archive and restore are an ADMINISTRATOR's press at the row's own node, and
    # the system is nobody's: `may_archive` refuses the system actor rather than
    # exempting it, so a workflow never takes a person's row out of the book on
    # its own say-so. Declaring the pair is what keeps that refusal: a key with
    # no policy is one the system actor passes before any policy is read.
    # golden: archive version move bulk history duplicate attach merge import begin
    "widget.archive": may_archive,
    "widget.restore": may_archive,
    # golden: archive version end
    # A move is an administrator's press at BOTH ends — asked of the widget where
    # it lives and of the node it is going to — and never the system's.
    "widget.move": may_move,
    # golden: move bulk history duplicate attach end
    # A merge is an administrator's press on BOTH records — the one folded away
    # and the one it becomes — and never the system's: nothing un-merges.
    "widget.merge": may_merge,
    # golden: archive version move bulk history duplicate attach begin
}
# golden: archive version move bulk history duplicate attach merge import end
# **`widget_policy.create` is deliberately NOT here.** Config travels DOWN, so
# its bar is authority and not ownership — and "does this person administer this
# branch" is the data half's whole question since the sweep. A predicate that
# re-asked it would be the second copy of it this file exists to have deleted.
# `admin` holds the key by its `("*",)` pattern, `owner` by the vocabulary, and
# a tenant may now hand it to a role of its own, which is the capability the
# rank comparison took away. The key keeps its sentence in `ACTION_PROSE` below,
# so it is still a declared word `introspect` prints.


# The sentence a refused caller reads, per action, and the worked example of the
# seam: a product declares these beside its policies and never edits `core`.
# See `core/policies.py` for the register.
# golden: archive version move bulk history duplicate attach merge import begin
ACTION_PROSE: dict[str, str] = {
    # golden: archive version move bulk history duplicate attach merge import end
    "widget.create": "You may not create widgets in this organization.",
    "widget.update": "You may not change that widget.",
    "widget.delete": "You may not delete that widget.",
    "widget.onboard": "You may not start onboarding that widget.",
    "widget.approve": "You may not approve that widget.",
    "widget_policy.create": "You may not set a widget policy for this organization.",
    "widget_entry.record": "You may not add entries to that widget's ledger.",
    "widget_policy.archive": "You may not archive this widget policy.",
    "widget_policy.restore": "You may not restore this widget policy.",
    # A family key — `widget.archive`, `widget.restore`, `widget.move` — needs no
    # line here: its derived sentence ("You may not archive this widget.") is the
    # one a refused caller reads, and the prose census accepts it as declared.
    # golden: archive version move bulk history duplicate attach merge import begin
}
# golden: archive version move bulk history duplicate attach merge import end
