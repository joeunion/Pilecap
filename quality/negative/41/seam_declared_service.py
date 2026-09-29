"""The services the declared routes call — the same two seam calls as the canaries."""

from typing import Any

from apps.core import verbs
from apps.core.models import Tenant
from apps.core.service import service
from apps.core.verbs import require_live


@service
def polish_sprocket(*, tenant: Tenant, sprocket_id: str) -> dict[str, Any]:
    """Polish one sprocket — refused when it is archived."""
    row: Any = None
    require_live(row, noun="sprocket")
    return {"id": sprocket_id}


@service
def shelve_cog(*, tenant: Tenant, cog_id: str) -> dict[str, Any]:
    """Archive one cog."""
    row: Any = None
    verbs.archive_row(tenant=tenant, actor=None, row=row, noun="cog")
    return {"id": cog_id}
