"""The other half of the underclaim: the service that raises what the door omits.

One level down and called by name, which is the whole of the depth this clause
claims. A code raised two calls below this one still passes, and that residual
is declared in rule 41's `does_not_cover` rather than hidden by a deeper walk
nobody could trust.
"""

from apps.core.exceptions import Conflict
from apps.core.models import Tenant
from apps.core.service import service


@service
def create_doodad(*, tenant: Tenant, name: str) -> str:
    """Register a doodad. Refuses when one already carries that name."""
    if name == "taken":
        raise Conflict("A doodad already carries that name.")
    return name


def list_doodads(*, tenant: Tenant) -> list[str]:
    """A read, and it refuses nothing at all."""
    return []
