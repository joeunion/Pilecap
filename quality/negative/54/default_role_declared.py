"""The right form, kept forever: a capability offered to a role that exists.

`member` is declared in `apps/core/roles.py` — the one product-editable file in
core — so the offer lands. This is the whole intended use of `DEFAULT_ROLES`:
the app that owns the capability decides which roles get it by default, and the
role's author never has to learn that the app exists.
"""

DEFAULT_ROLES = {"gadget.create": frozenset({"member"})}
