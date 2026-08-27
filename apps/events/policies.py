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
    "endpoint.create": is_privileged,
    "endpoint.update": is_privileged,
    "endpoint.deactivate": is_privileged,
    # Arrived with the doors. Each is the same owner-or-admin decision the three
    # above are, and each is written here rather than inherited so that
    # `introspect` prints the whole subscription surface in one place.
    #
    # `endpoint.issue_secret` is the sharpest of them: whoever calls it is handed
    # the tenant's new signing key and every subscriber holding the old one stops
    # verifying at the next delivery. `endpoint.resume` is its mirror image —
    # turning delivery back on is the same weight of act as turning it off, so it
    # is not a lighter permission than `endpoint.deactivate`.
    "endpoint.issue_secret": is_privileged,
    "endpoint.resume": is_privileged,
    # A replay re-sends an event to every active subscriber. That is an egress
    # decision about the tenant's data, exactly as registering an endpoint is,
    # so it is the same permission and not a read.
    "delivery.replay": is_privileged,
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
