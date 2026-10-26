"""Who may stage, apply and cancel an import. Policies are code, found by discovery.

An import asks two keys: `djb_import.*` here, and the noun's own `<kind>.create`, per row at apply.
"""

from __future__ import annotations

from apps.core.authz import Policy, is_member

POLICIES: dict[str, Policy] = {
    "djb_import.create": is_member,
    "djb_import.apply": is_member,
    "djb_import.cancel": is_member,
}

DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "djb_import.create": frozenset({"member"}),
    "djb_import.apply": frozenset({"member"}),
    "djb_import.cancel": frozenset({"member"}),
}

ACTION_PROSE: dict[str, str] = {
    "djb_import.create": "You may not import files in this organization.",
    "djb_import.apply": "You may not apply that import.",
    "djb_import.cancel": "You may not cancel that import.",
}
