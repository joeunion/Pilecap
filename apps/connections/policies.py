"""Who may do what to a connection. Policies are code; roles are data.

`core.authz.require(actor, "connection.create")` finds these by discovery — this
file is never registered anywhere.

The rule is one sentence and it is stricter than the example app's: **only an
owner or an admin CHANGES a connection.** A connection holds a credential that
acts as the whole tenant against somebody else's system, so "a member may act on
their own records" — right for a widget — would here mean any member of the
tenant can point the product's Stripe key at a new webhook URL. There is no
per-row half-measure to make, which is exactly why this is three lines.

The verb is `changes`, not `touches`, and the difference is a ruling: **starting
an OAuth handshake stores nothing and is not gated — the callback is the wall**
(ruled in `docs/product/design-agreements.md`). A member may call
`POST /connections/{id}/oauth/start/`; it writes a single-use 600-second cache
entry, no service and no row. The one path that persists an exchange result is
`services.update_credentials`, and it opens with
`require(actor, "connection.update", ...)` — so the member is refused on the way
back, with nothing stored. `apps/connections/tests/test_api.py`'s
`test_a_member_starts_the_handshake_and_the_callback_is_the_wall` is that
sentence made executable; if it goes green with the require deleted, the
invariant has been lost.

Reading a connection is not on this list, and that is deliberate: reads go
through `selectors.py`, which narrows to the acting tenant, and `authz` already
lets a `member` perform a `view`-shaped action. What a member may *not* see is
the credential itself, and that is enforced where it belongs — `ConnectionOut`
has no field for it.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for


def is_privileged(actor: Actor, obj: Any = None) -> bool:
    """An owner or an admin of the acting tenant, and nobody else."""
    membership = membership_for(actor)
    return membership is not None and membership.is_privileged


POLICIES: dict[str, Policy] = {
    "connection.create": is_privileged,
    "connection.update": is_privileged,
    "connection.revoke": is_privileged,
}


# The sentence a refused caller reads, per action. See `core/policies.py`.
# `connection.receive_webhook` is here although no policy above names it:
# `require` is called with it on the inbound receiver and the role fallback
# answers it.
ACTION_PROSE: dict[str, str] = {
    "connection.create": "You may not connect this tenant to an outside system.",
    "connection.update": "You may not change this tenant's connections.",
    "connection.revoke": "You may not stop this tenant's connections from being used.",
    "connection.receive_webhook": "You may not deliver webhooks to this connection.",
}
