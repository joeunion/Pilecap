"""Who may read what this tenant has consumed. Policies are code.

`core.authz.require(actor, "usage.read_report")` finds this by discovery — this
file is never registered anywhere. The key is `<noun>.<verb>`, the predicate
takes the acting `Actor` and the object, and it returns a bool.

**There is one key and not two, and the missing one is the design.** There is no
`usage.record`: recording is not something anybody asks for. It is the
platform's witnessed side-effect of an action that was already authorized — the
completion ran, the file was stored — and `record_usage` carries rule 13's
`# authz:` valve saying exactly that, with the actor kept for the audit row
rather than asked for permission. A `usage.record` predicate would be a
permission nobody could ever be refused, which is a permission that teaches a
reader the wrong thing about what this app does.

**The bar on reading is membership at ALL_ROLES, and it is now DECLARED rather
than argued** (owner-ruled; `design-agreements.md` § Usage
visibility). Rule 24 has already decided what a given hat can *see*:
`for_tenant(t).visible_to(actor)` narrows a usage report to the actor's own
subtree, so a branch manager reading their own consumption learns nothing they
could not have derived by paging their own completions one at a time. What that
argument leaves is a **root-hat member reading the tenant-wide bill**, which is
a product decision and not a platform one — an earlier finding, and the
owner's ruling was that the default stays as it is and stops being an argument
buried in a docstring.

So the bar is a **named permission**: one module-level declaration, all roles by
default, and `can()` consults it. A product that wants a narrower bill narrows
`USAGE_READ_REPORT`'s `default_roles` — one line, in a diff a reviewer sees —
and never forks this file, never edits `core`, and never grows a second opinion
about the same question somewhere else. A fresh clone behaves exactly as it did
before the declaration existed, which is pinned by
`tests/test_policies.py::test_a_fresh_clone_lets_every_role_read_the_report`.

**Why the declaration lives here and not in `core`.** The declaration is the
DATA half of "roles are data, policies are code" and its home is
the app that owns the action — the same reason `POLICIES` and `ACTION_PROSE`
live here. A central registry would be one file every app in a parallel wave has
to edit, which is the collision this template is shaped around avoiding; if one
is ever wanted it is a lead's decision, and this app deliberately did not take
it. What IS handed up is the one thing this
file cannot do from here: `manage.py introspect` prints the action and the
predicate's name, and has no column for the declared roles — so a narrowing is
visible in the diff and in this file, and not yet in the instrument. Recorded,
not worked around.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from apps.core.actor import Actor
from apps.core.authz import ROLE_RANK, Policy, membership_for

#: Every role this deployment has, **derived and never listed**. `ROLE_RANK` is
#: the one place in the tree that says one role outranks another, and a product
#: that adds a fourth role adds it there — so "all roles" keeps meaning all of
#: them without this line changing. A hand-listed tuple here would be the second
#: spelling of the role vocabulary, and the day they disagreed the quieter one
#: would win silently.
ALL_ROLES: frozenset[str] = frozenset(ROLE_RANK)


@dataclass(frozen=True)
class DeclaredPermission:
    """One action, and the roles a product has decided may perform it.

    Frozen because a permission that could be mutated at runtime is a permission
    whose value in a log line and value at the check can differ. Narrowing is an
    edit to the declaration below, in a commit, not a `setattr` at boot.
    """

    #: The `<noun>.<verb>` key `core.authz.require` is called with. Spelled ONCE
    #: here so that a caller names the declaration rather than re-typing the
    #: string — a typo'd action name is an authorization that never runs.
    action: str

    #: The roles that may perform it. A membership whose role is outside this
    #: set is refused exactly as no membership at all is.
    roles: frozenset[str]

    def can(self, actor: Actor, obj: Any = None) -> bool:
        """The predicate `core.authz` calls. **It consults the declaration.**

        Never an inline role set: the whole point of the declaration is that the
        answer to "who may read a bill here" is readable in one place and
        changeable in one place. `obj` is unused and stays in the signature
        because that is the shape a `Policy` is called with — a usage report is
        not a row, it is a total over whatever `visible_to` already narrowed to,
        so there is no per-row question to ask.

        Membership first, and it is not redundant: `membership_for` narrows to
        the acting hat's own ancestors, so somebody acting under a hat they hold
        no role over is refused here rather than reading an empty report and
        being told they consumed nothing.
        """
        membership = membership_for(actor)
        if membership is None:
            return False
        return str(membership.role) in self.roles


def declared_permission(*, action: str, default_roles: Iterable[str]) -> DeclaredPermission:
    """Declare a permission, refusing a role name this deployment does not have.

    The refusal is at import — so a typo in a product's narrowing stops the
    process rather than surfacing as a permission that silently refuses
    everybody. It is the same tier `apps/usage/meters.py::validate_declared_meters`
    puts the meter grammar on, and for the same reason: a narrowing nobody can
    see is worse than a narrowing that fails loudly.
    """
    roles = frozenset(str(role) for role in default_roles)
    unknown = sorted(roles - ALL_ROLES)
    if unknown:
        raise ImproperlyConfigured(
            f"apps/usage/policies.py declares {action!r} for role(s) {unknown} that this "
            f"deployment does not have. The roles are {sorted(ALL_ROLES)}, derived from "
            f"`core.authz.ROLE_RANK`. A permission declared for a role nobody holds is a "
            f"permission that refuses everybody, quietly."
        )
    if not roles:
        raise ImproperlyConfigured(
            f"apps/usage/policies.py declares {action!r} for no roles at all. Deleting the "
            f"capability is an edit to the door; a declaration nobody satisfies is a route "
            f"that answers 403 to everyone with nothing saying why."
        )
    return DeclaredPermission(action=action, roles=roles)


#: **The one place the usage read's bar is set.** All roles by default: a fresh
#: clone behaves exactly as it did before this declaration existed (pinned red
#: in `tests/test_policies.py`), and a product that wants only owners and admins
#: to see the bill edits THIS LINE — never a fork of this file.
USAGE_READ_REPORT = declared_permission(action="usage.read_report", default_roles=ALL_ROLES)


POLICIES: dict[str, Policy] = {
    USAGE_READ_REPORT.action: USAGE_READ_REPORT.can,
}


# The sentence a refused caller reads. Plain language, never the action name;
# a product declares these beside its policies and never edits `core`.
ACTION_PROSE: dict[str, str] = {
    USAGE_READ_REPORT.action: (
        "You may not read this tenant's usage. A usage report covers the part of "
        "the organization you are acting as, so signing in under a hat you hold "
        "in this tenant is what opens it."
    ),
}
