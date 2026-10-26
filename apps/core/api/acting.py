"""The REST door's one resolver: who is acting, in which tenant, wearing which hat.

Every route that hands a service an actor and a tenant asks `acting(request)`,
and nothing else. It is the HTTP twin of `apps.core.mcp.acting_tenant` /
`acting_org`: the two doors resolve the same three facts and refuse the same
absence with the same registered code, `no_acting_scope`, composed by the one
`wire_refusal` — so a person with no membership reads one refusal at REST and at
MCP, never a coded one at one door and a bare `{"detail": …}` at the other.

**What it does not decide.** Whether the actor MAY do the thing is the
service's (`authz.require`); a permission check here would be a second copy of
the rule, one per door. Whether a SENT `X-Tenant`/`X-Org` is honourable is the
addressing law's (`apps.core.middleware.addressing_refusal`, asked by the mount
before any route runs) — this answers only the case where nothing resolved.

**Why a named tuple.** The hat rides on the actor, because that is
where a service reads it from; `Acting` names the three facts so a route says
`acting(request).hat` rather than re-deriving it, and it still unpacks as
`actor, tenant = acting(request)` — the shape every app's door already had.
"""

from __future__ import annotations

from typing import NamedTuple

from django.http import HttpRequest

from apps.core.actor import Actor, actor_from_request
from apps.core.exceptions import NoActingScope
from apps.core.models import Organization, Tenant
from apps.core.roads import road


class Acting(NamedTuple):
    """The actor, the tenant and the hat one request acts as — refused when absent."""

    actor: Actor
    tenant: Tenant

    @property
    def org(self) -> Organization | None:
        """The acting organization, or `None` when the request resolved no hat."""
        return self.actor.org

    @property
    def hat(self) -> Organization:
        """The acting organization, refused rather than defaulted when there is none."""
        return require_hat(self.actor)


@road("acting", example="apps/core/api/routes.py::list_organizations_route")
def acting(request: HttpRequest) -> Acting:
    """The actor and tenant this request acts as, or `no_acting_scope` when none resolved."""
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        raise NoActingScope()
    return Acting(actor=actor_from_request(request), tenant=tenant)


def require_hat(actor: Actor) -> Organization:
    """The actor's acting organization, or `no_acting_scope` when it has none.

    Every subtree read needs a root to start from. `visible_to(None)` already
    fails closed by returning nothing, but an empty list is a confusing way to
    say "you are wearing no hat" — so the door says it, in the registry's words.
    """
    if actor.org is None:
        # The tenant first — a hat is a place inside one — so a request with
        # neither hears about the first absence, as the MCP door's twin says it.
        raise NoActingScope(None if actor.tenant is None else NoActingScope.no_hat_detail)
    return actor.org
