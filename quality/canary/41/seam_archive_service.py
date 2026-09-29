"""The other half: a service over the family's archive seam."""

from typing import Any

from apps.core import verbs
from apps.core.models import Tenant
from apps.core.service import service


@service
def shelve_cog(*, tenant: Tenant, cog_id: str) -> dict[str, Any]:
    """Archive one cog."""
    row: Any = None
    verbs.archive_row(tenant=tenant, actor=None, row=row, noun="cog")
    return {"id": cog_id}
