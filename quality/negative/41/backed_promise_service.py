"""The other half of the kept promise: the service that actually asks.

One level down and called by a name this tree resolves, which is all the depth
this clause claims. A `require` two calls below the route is invisible to it,
and that residual is declared in rule 41's `does_not_cover` beside its —
they are the same blind spot, read from two directions.
"""

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.models import Tenant
from apps.core.service import service


@service
def create_doohickey(*, tenant: Tenant, actor: Actor, name: str) -> str:
    """Register a doohickey. Owner or admin, and the door says so."""
    require(actor, "doohickey.create", tenant)
    return name
