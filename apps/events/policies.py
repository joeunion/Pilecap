"""Who may manage a tenant's webhook subscriptions.

An endpoint is a **credential-bearing egress route**: whoever adds one decides
where a copy of everything that happens in the tenant is sent, and holds the
secret it is signed with. That is an owner-or-admin decision, not a member's,
and it is written here rather than left to the role default so that the rule is
greppable, testable, and reported by `manage.py introspect` — a permission that
exists only as the absence of a policy is a permission nobody reviews.

Events themselves carry no policy, and neither does *recording* a delivery:
nothing outside this app writes them, and the services that do are reached only
by the dispatch workflow as the system actor (`core.authz` lets the system
through, and the scoped manager still holds the tenancy).

**Replaying** a delivery is the exception, and it is the exception for the same
reason registering an endpoint is a policy: it puts a copy of the tenant's data
back on the wire to every active subscriber. So `delivery.replay` is here, at
the same owner-or-admin weight — a read of a dead letter is a read, and sending
it again is not.

**What the Phase-W sweep changed here: this file has no predicates left.** The
one it had read `Membership.role` by value to answer "is this person an owner or
an admin", which is a rank table nobody's tenant can edit — a second opinion
about the rows the role editor writes (house rule 54 (c), principle 9). The
sentence it enforced has not moved by one byte; it is now enforced by the layer
that owns it. `admin` holds `("*",)` and `owner` is the vocabulary, so the six
keys below resolve to exactly the people the predicate admitted — and a tenant
that wants a fourth kind of person able to rotate a signing secret can now say
so with a `Role` row, which the predicate gave them no way to do.

**And `WebhookEndpoint` now DECLARES its kind** (`authz_kind = "endpoint"`,
`models.py`). Every door, refusal and `require` in this app has said `endpoint.*`
since the app landed, and the derived name would have been `webhook_endpoint.*`
— two words for one noun, which is the defect rule 54 (a) exists to refuse. The
five `endpoint.*` keys become conforming; the four derived `webhook_endpoint.*`
keys nobody typed are renamed below, so a `Grant` or `RolePermission` row
carrying one goes on answering.

**What this sweep deliberately did NOT do** (PM ruling, 2026-09-16): the other
half — moving "which declared role holds this by default" out of the compat
residue and into a `DEFAULT_ROLES` mapping — is DEFERRED to one later rung,
because any `DEFAULT_ROLES` entry moves `defaults_for("member")` and two pins of
the flat product in `apps/core/tests/test_vocabulary.py` read that value
directly. This app would have had nothing to put in one — it admits no member to
any write — but the deferral is recorded here so the next reader knows the file
is waiting on a rung rather than finished by omission.

The proof is a census rather than these paragraphs: `tests/authz_baseline.json`
is derived on the tree before the sweep and `tests/test_authz_sweep.py`
re-derives it here and asserts equality, cell for cell.
"""

from __future__ import annotations

from apps.core.authz import Policy

# **Empty on purpose, and the emptiness is the rung.** Every key this app
# declares asks "how much authority does this person hold in this tenant", and
# that is what `effective_permissions` is. There is no row-shaped half here: an
# endpoint is a tenant's configuration, not somebody's record, so "of their own"
# has nothing to be about.
#
# The keys and what each one is, kept from the predicates that used to carry
# them: `endpoint.create`/`.update`/`.deactivate`/`.resume` are the subscription
# surface — whoever holds them decides where a copy of everything that happens
# in the tenant is sent. `endpoint.issue_secret` is the sharpest: whoever calls
# it is handed the tenant's new signing key and every subscriber holding the old
# one stops verifying at the next delivery. `delivery.replay` puts a copy of the
# tenant's data back on the wire to every active subscriber, which is an egress
# decision and not a read.
#
# The file stays because the next question about an endpoint may well be a row
# question, and because `ACTION_PROSE` below is what a refused caller reads.
POLICIES: dict[str, Policy] = {}


# The four keys this app renamed when `WebhookEndpoint` declared its kind, and
# the WHOLE cost of renaming one: a line here (ADR core-25, rule 54 (a)).
# `core.authz.allows` resolves an alias one line BEFORE the policy lookup, so a
# stored `Grant` or `RolePermission` row carrying `webhook_endpoint.read` goes on
# answering — with one deprecation printed per process — and never falls through
# to the role default, which is the silent widening a rename must not cause.
#
# Nobody TYPED any of these: they are the four derived verbs the registry
# produced from the class name, and the declared `endpoint.*` keys have always
# sat beside them. What the rename does is collapse the two spellings into the
# one the doors use. **A row stored under an old key still needs
# `manage.py rename_permission` to be moved**; until then the alias is what keeps
# it answering, which is the point of having one.
RENAMED_PERMISSIONS: dict[str, str] = {
    "webhook_endpoint.create": "endpoint.create",
    "webhook_endpoint.read": "endpoint.read",
    "webhook_endpoint.update": "endpoint.update",
    "webhook_endpoint.delete": "endpoint.delete",
}


# The sentence a refused caller reads, per action. See `core/policies.py`.
ACTION_PROSE: dict[str, str] = {
    "endpoint.create": "You may not register a webhook endpoint for this tenant.",
    "endpoint.update": "You may not change this tenant's webhook endpoints.",
    "endpoint.deactivate": "You may not pause this tenant's webhook endpoints.",
    "endpoint.resume": "You may not resume this tenant's webhook endpoints.",
    "endpoint.issue_secret": "You may not replace an endpoint's signing secret.",
    "delivery.replay": "You may not send a given-up webhook delivery again.",
}
