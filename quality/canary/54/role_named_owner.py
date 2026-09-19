"""Planted: a `roles.py` declaring the platform's own role (clause b).

`owner` IS the vocabulary — every key, present and future, reads and the
reserved verb included — so a product declaration named `owner` is a ceiling
quietly disappearing: whatever patterns it lists become the whole of what an
owner may do, and every key outside them stops being held by anybody.
"""

from apps.core.authz import DeclaredRole

ROLES = {
    "owner": DeclaredRole(
        key="owner",
        name="Owner",
        permissions=("*.read",),
        description="Planted wrongness: a narrowed owner.",
    ),
}
