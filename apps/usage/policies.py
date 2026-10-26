"""Who may read what a tenant consumed: the derived `usage_entry.read`, no predicate (ADR core-27).

# why-not a `usage.record` key: recording is the witnessed side-effect of an authorized act.
# why-not a predicate: rows are `visible_to`'s and the capability is the vocabulary's.
"""

from __future__ import annotations

from apps.core.authz import Policy

#: The renamed key and its successor (ADR core-25): the old word answers as the new one.
RENAMED_PERMISSIONS: dict[str, str] = {
    "usage.read_report": "usage_entry.read",
}


#: Empty on purpose; the dict stays so a product's first predicate is an addition.
POLICIES: dict[str, Policy] = {}


#: The refused caller's sentence: they asked for a report, not a row.
ACTION_PROSE: dict[str, str] = {
    "usage_entry.read": (
        "You may not read this tenant's usage. A usage report covers the part of "
        "the organization you are acting as, and reading it is a capability your "
        "role or a grant has to carry."
    ),
}
