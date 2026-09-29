"""The other half: a service whose write calls the family seam that refuses `archived`."""

from typing import Any

from apps.core.models import Tenant
from apps.core.service import service
from apps.core.verbs import require_live


@service
def polish_sprocket(*, tenant: Tenant, sprocket_id: str) -> dict[str, Any]:
    """Polish one sprocket — refused when it is archived."""
    row: Any = None
    require_live(row, noun="sprocket")
    return {"id": sprocket_id}
