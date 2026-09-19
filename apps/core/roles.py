"""The roles this deployment declares. **The one product-editable file in `core`.**

Every other file under `apps/core/` is the platform's; this one is yours, the
way `docs/product/north-star.md` is. Edit it, add roles to it, delete `admin` if
your product has no such person — a template merge brings it back as an
ordinary per-file conflict you adjudicate, exactly like the north star.

Roles are declared like policies: `core.authz.role_declarations()` walks every
`apps/<x>/roles.py` for a `ROLES` dict, so an app may declare its own without
editing this file, and this file never learns that the app exists. Two apps
declaring one key is an `ImproperlyConfigured` at discovery.

**A role is a set of PATTERNS, not a list of keys.** `("*.read",)` is still
"may read everything" in a deployment with three more apps in it, and no
migration ran to keep it true. The patterns are matched against
`core.authz.vocabulary()` with `fnmatch`, and **a reserved key matches
nothing** — so `("*",)` is "everything except ownership", which is exactly what
an administrator has always been here.

**`owner` is not in this file and cannot be put in it.** It is the one platform
role and its collection IS the vocabulary — every key, present and future,
reads and the reserved verb included. A declaration named `owner` is refused,
because a narrowed `owner` is a ceiling quietly disappearing.

The two below are the template's, with today's meaning:

* `admin` — `("*",)`: everything but ownership. Today's `admin`.
* `member` — `("*.read",)`, and the role a new membership gets. Today's
  `member` reads everything it can see; the writes today's member is admitted
  to by a policy predicate keep working through the transition, because a key
  with a predicate and no declaration is offered to every role and the
  predicate is what narrows it.

A product that wants a data-entry role writes
`("*.read", "widget_entry.create")`; a read-only auditor is `("*.read",)` with
`is_default_for_new_members=False`. A capability a role should have without
this file naming it goes the other way round: the owning app writes
`DEFAULT_ROLES = {"widget.create": frozenset({"member"})}` in its `policies.py`
and the role's author never hears about it.
"""

from __future__ import annotations

from apps.core.authz import DeclaredRole

ROLES: dict[str, DeclaredRole] = {
    "admin": DeclaredRole(
        key="admin",
        name="Admin",
        permissions=("*",),
        is_default_for_new_members=False,
        description="Everything in this tenant except making somebody an owner of it.",
    ),
    "member": DeclaredRole(
        key="member",
        name="Member",
        permissions=("*.read",),
        is_default_for_new_members=True,
        description="Reads what they can see, and whatever else a policy admits them to.",
    ),
}
