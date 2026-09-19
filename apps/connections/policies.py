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

Reading a connection **is** a permission since Phase R (ADR core-27), and it is
still not on this list: `connection.read` and `inbound_webhook.read` are derived
keys the vocabulary produces from the models, asked once inside `selectors.py`,
and held by `member` through its `("*.read",)` pattern. What a member may *not*
see is the credential itself, and that is enforced where it belongs —
`ConnectionOut` has no field for it.

**What the Phase-W sweep changed here: this file has no predicates left.** The
one it had read `Membership.role` by value to answer "is this person an owner or
an admin", which is a rank table nobody's tenant can edit — a second opinion
about the rows the role editor writes (house rule 54 (c), principle 9). The
sentence it enforced has not moved by one byte; it is now enforced by the layer
that owns it. `admin` holds `("*",)` and `owner` is the vocabulary, so the three
keys below resolve to exactly the people the predicate admitted — and a tenant
that wants a fourth kind of person able to rotate a credential can now say so
with a `Role` row, which the predicate gave them no way to do.

The proof is a census rather than this paragraph: `tests/authz_baseline.json` is
derived on the tree before the sweep and `tests/test_authz_sweep.py` re-derives
it here and asserts equality, cell for cell.

**What this sweep deliberately did NOT do** (PM ruling, 2026-09-16): the other
half of the sweep — moving "which declared role holds this by default" out of
the compat residue and into a `DEFAULT_ROLES` mapping — is DEFERRED to one later
rung, because any `DEFAULT_ROLES` entry moves `defaults_for("member")` and two
pins of the flat product in `apps/core/tests/test_vocabulary.py` read that value
directly. This app would have had nothing to put in one — it admits no member to
any write — but the deferral is recorded here so the next reader knows the file
is waiting on a rung rather than finished by omission.
"""

from __future__ import annotations

from apps.core.authz import Policy

# **Empty on purpose, and the emptiness is the rung.** Every key this app
# declares is answered by the data half alone: `connection.create`,
# `connection.update`, `connection.revoke` and `connection.receive_webhook` ask
# "how much authority does this person hold in this tenant", and that is what
# `effective_permissions` is. There is no row-shaped half here — a connection
# holds one credential that acts as the WHOLE tenant, so "a member may act on
# their own" has nothing to be about (the paragraph above says why).
#
# The file stays because the next question about a connection may well be a row
# question, and because `ACTION_PROSE` below is what a refused caller reads.
POLICIES: dict[str, Policy] = {}


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
