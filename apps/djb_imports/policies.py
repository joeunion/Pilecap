"""Who may stage, apply and cancel an import. Policies are code, found by discovery.

**An import is two permissions, and this file owns only the first.** Staging a
file needs `djb_import.create` — anybody in the tenant, like creating a widget — AND
`<kind>.create` for the noun the file makes, which is the noun's own key, asked
by `services.create_import` at stage and again, per row, at apply. So a member
who may not create widgets may not import them either, and no predicate here
has to know what a widget is.

**The member half is a predicate, not a `DEFAULT_ROLES` entry**, for the reason
`apps/exports/policies.py` records: a `DEFAULT_ROLES` entry moves what
`defaults_for("member")` answers, which is a pin of the flat product no per-app
change may move alone. A key with a predicate and no `DEFAULT_ROLES` entry is
held by every declared role and narrowed by the predicate — the compat column
`widget.create` rides today — so a tenant's own `RolePermission` exclude and a
person's `withhold` grant still take it away.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for


def _is_member(actor: Actor, obj: Any = None) -> bool:
    """Whether this actor belongs to the tenant at all. Not a role read."""
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    "djb_import.create": _is_member,
    "djb_import.apply": _is_member,
    "djb_import.cancel": _is_member,
}

ACTION_PROSE: dict[str, str] = {
    "djb_import.create": "You may not import files in this organization.",
    "djb_import.apply": "You may not apply that import.",
    "djb_import.cancel": "You may not cancel that import.",
}
