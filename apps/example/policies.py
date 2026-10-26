"""Who may do what to a widget. **Policies are code; roles are DATA.**"""

from __future__ import annotations

# golden: noun begin
from typing import Any

# golden: archive version move bulk history duplicate attach merge import begin
from pilecap import Policy, may_archive

# golden: noun end

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from pilecap import may_move

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: merge import begin
from pilecap import may_merge

# golden: merge import end
# golden: noun begin
# isort: split
from pilecap import Actor, holds, is_member

# golden: noun end
# golden: policy begin
#: The key that means "administers widgets in this branch".
ADMINISTERS_WIDGETS = "widget_policy.create"
# golden: policy end


# golden: noun begin
def can_create(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may create a widget; they own what they create."""
    return is_member(actor)


def owns(actor: Actor, obj: Any = None) -> bool:
    """The row's creator, or an actor holding `organization.update` where the row lives."""
    if obj is None:
        return holds(actor, "organization.update")
    if actor.user is not None and getattr(obj, "owner_id", None) == actor.user.pk:
        return True
    return may_archive(actor, obj)


# golden: noun end


def can_approve(actor: Actor, obj: Any = None) -> bool:
    """Somebody who administers widgets **over the widget's own branch**."""
    if obj is None:
        return holds(actor, ADMINISTERS_WIDGETS)
    return holds(actor, ADMINISTERS_WIDGETS, at=getattr(obj, "organization", None))


# golden: child entry begin
def can_record_entry(actor: Actor, obj: Any = None) -> bool:
    """Anyone who can see the widget may add a line to its ledger."""
    return is_member(actor)


# golden: child entry end
# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
POLICIES: dict[str, Policy] = {
    # golden: archive version move bulk history duplicate attach merge import end
    "widget.create": can_create,
    "widget.update": owns,
    "widget.delete": owns,
    # golden: noun end
    # golden: workflow onboard begin
    # Onboarding is the product acting for itself, as the system actor.
    "widget.onboard": owns,
    # golden: workflow onboard end
    # golden: workflow remind begin
    # The reminder acts as the system actor too; the entry names the rule a person would obey.
    "widget.remind": owns,
    # golden: workflow remind end
    # golden: workflow onboard begin
    # The one verb that is not "your own": see `can_approve`.
    "widget.approve": can_approve,
    # golden: workflow onboard end
    # golden: child entry begin
    # The ledger. Append-only and landing-gated, so the bar is membership.
    "widget_entry.record": can_record_entry,
    # golden: child entry end
    # golden: policy begin
    # A policy leaves the book the way a widget does: an administrator's press.
    "widget_policy.archive": may_archive,
    "widget_policy.restore": may_archive,
    # golden: policy end
    # Archive and restore are an ADMINISTRATOR's press at the row's own node.
    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
    "widget.archive": may_archive,
    "widget.restore": may_archive,
    # golden: noun end
    # golden: archive version end
    # A move is an administrator's press at BOTH ends, never the system's.
    "widget.move": may_move,
    # golden: move bulk history duplicate attach end
    # A merge is an administrator's press on BOTH records, never the system's.
    "widget.merge": may_merge,
    # golden: archive version move bulk history duplicate attach begin
    # golden: noun begin
}
# golden: noun end
# golden: archive version move bulk history duplicate attach merge import end
# **`widget_policy.create` is deliberately NOT here**: the roles hold it.

#: The keys `member` holds by declaration; each predicate above still narrows its key.
# golden: noun begin
DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "widget.create": frozenset({"member"}),
    "widget.update": frozenset({"member"}),
    "widget.delete": frozenset({"member"}),
    # golden: noun end
    # golden: workflow onboard begin
    "widget.onboard": frozenset({"member"}),
    # golden: workflow onboard end
    # golden: workflow remind begin
    "widget.remind": frozenset({"member"}),
    # golden: workflow remind end
    # golden: workflow onboard begin
    "widget.approve": frozenset({"member"}),
    # golden: workflow onboard end
    # golden: child entry begin
    "widget_entry.record": frozenset({"member"}),
    # golden: child entry end
    # golden: policy begin
    "widget_policy.archive": frozenset({"member"}),
    "widget_policy.restore": frozenset({"member"}),
    # golden: policy end
    # golden: noun begin
    "widget.archive": frozenset({"member"}),
    "widget.restore": frozenset({"member"}),
    # golden: noun end
    "widget.move": frozenset({"member"}),
    "widget.merge": frozenset({"member"}),
    # golden: noun begin
}
# golden: noun end


# The sentence a refused caller reads, per action.
# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
ACTION_PROSE: dict[str, str] = {
    # golden: archive version move bulk history duplicate attach merge import end
    "widget.create": "You may not create widgets in this organization.",
    "widget.update": "You may not change that widget.",
    "widget.delete": "You may not delete that widget.",
    # golden: noun end
    # golden: workflow onboard begin
    "widget.onboard": "You may not start onboarding that widget.",
    # golden: workflow onboard end
    # golden: workflow remind begin
    "widget.remind": "You may not send that widget's reminder.",
    # golden: workflow remind end
    # golden: workflow onboard begin
    "widget.approve": "You may not approve that widget.",
    # golden: workflow onboard end
    # golden: policy begin
    "widget_policy.create": "You may not set a widget policy for this organization.",
    # golden: policy end
    # golden: child entry begin
    "widget_entry.record": "You may not add entries to that widget's ledger.",
    # golden: child entry end
    # golden: policy begin
    "widget_policy.archive": "You may not archive this widget policy.",
    "widget_policy.restore": "You may not restore this widget policy.",
    # golden: policy end
    # A family key needs no line here: its derived sentence is the declared one.
    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
}
# golden: noun end
# golden: archive version move bulk history duplicate attach merge import end
