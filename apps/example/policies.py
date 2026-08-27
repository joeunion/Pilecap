"""Who may do what to a widget. Policies are code; roles are data.

`core.authz.require(actor, "widget.update", widget)` finds these by discovery —
this file is never registered anywhere. The keys are `<noun>.<verb>`, and the
predicates take the acting `Actor` and the object, and return a bool.

The rule here is the ordinary one and it is worth stating plainly: **a member
may act on their own records; an owner or an admin may act on anyone's.** That
is a sentence about the domain, which is exactly why it belongs in code beside
the model rather than in a fourth role called "widget_editor" — a role cannot
say "of their own", because a role does not know which row you meant.

**Approval is the exception, and it is the interesting one.** `widget.approve`
is not "a member may act on their own" — approving your own work is precisely
what an approval step exists to prevent — so it asks a role question instead,
and asks it *over the widget's own branch*. That is a sentence about the domain
too, and it is the second reason policies are code: the first rule and this one
are both "who may", and no set of roles can express the difference.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import ADMIN_RANK, Policy, actor_role, membership_for, rank


def _is_privileged(actor: Actor) -> bool:
    membership = membership_for(actor)
    return membership is not None and membership.is_privileged


def _is_member(actor: Actor) -> bool:
    return membership_for(actor) is not None


def can_create(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may create a widget; they own what they create."""
    return _is_member(actor)


def owns_or_is_privileged(actor: Actor, obj: Any = None) -> bool:
    """The owner of the record, or an owner/admin of the tenant.

    `obj is None` means the caller asked about the capability in the abstract
    ("could I edit widgets at all?"), and only a privileged role can be
    answered yes without a row to look at.
    """
    if obj is None:
        return _is_privileged(actor)
    if actor.user is not None and getattr(obj, "owner_id", None) == actor.user.pk:
        return True
    return _is_privileged(actor)


def can_approve(actor: Actor, obj: Any = None) -> bool:
    """An owner or admin **over the widget's own branch**. Not the widget's owner.

    Approval is the one verb here that is deliberately *not* "a member may act
    on their own": approving your own work is the thing an approval step exists
    to prevent. So the question is a role question, and the role is read over
    the row's organization rather than over the actor's hat — an admin of
    Seller A may approve a widget at Sub A1 because roles inherit downwards,
    and an admin of Sub A1 may not approve one at Seller A because nothing
    inherits up.

    Reading the role over the *widget's* node rather than the actor's is what
    makes that true in one line. It costs nothing extra: the actor cannot see
    the row at all unless `visible_to` already let it through, so the only
    question left is how much authority they hold where the row lives.
    """
    if obj is None:
        return _is_privileged(actor)
    return rank(actor_role(actor, getattr(obj, "organization", None))) >= ADMIN_RANK


def can_set_policy(actor: Actor, obj: Any = None) -> bool:
    """An owner or admin of the branch they are acting in. **Not every member.**

    A policy is not a record, it is *configuration*, and the difference is the
    direction it travels: a widget one member creates is seen by that branch and
    the ones above it, while a policy that member sets is obeyed by that branch
    and every branch **below** it. Letting a member write config for their own
    sub-sellers would be a quiet escalation — nothing about their role changed,
    but what they can make other people's branches do did.

    So the question is a role question, asked over the **acting hat** (unlike
    `can_approve`, which asks it over the row's node, because there the row
    already exists). `create_widget_policy` writes into `actor.org`, so the hat
    is exactly the node the config will govern.
    """
    return rank(actor_role(actor, actor.org)) >= ADMIN_RANK


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


POLICIES: dict[str, Policy] = {
    "widget.create": can_create,
    "widget.update": owns_or_is_privileged,
    "widget.delete": owns_or_is_privileged,
    # Onboarding is the product acting for itself: the workflow's activities run
    # as the system actor, which `core.authz` allows before it reads a policy at
    # all. The entry is here anyway, because the day a person is given a button
    # that onboards a widget by hand, the rule it has to obey is already written
    # — and because an action with no policy is invisible in `introspect`.
    "widget.onboard": owns_or_is_privileged,
    # The one verb that is not "your own": see `can_approve`.
    "widget.approve": can_approve,
    # Config, not a record — and config travels DOWN, so the bar is a role and
    # not ownership. See `can_set_policy`.
    "widget_policy.create": can_set_policy,
    # The ledger. Append-only and landing-gated, so the bar is membership.
    "widget_entry.record": can_record_entry,
}


# The sentence a refused caller reads, per action, and the worked example of the
# seam: a product declares these beside its policies and never edits `core`.
# See `core/policies.py` for the register.
ACTION_PROSE: dict[str, str] = {
    "widget.create": "You may not create widgets in this organization.",
    "widget.update": "You may not change that widget.",
    "widget.delete": "You may not delete that widget.",
    "widget.onboard": "You may not start onboarding that widget.",
    "widget.approve": "You may not approve that widget.",
    "widget_policy.create": "You may not set a widget policy for this organization.",
    "widget_entry.record": "You may not add entries to that widget's ledger.",
}
