"""Planted, in the probe scaffold: a write ON an archivable row that never asks.

The form that keeps rule 82 able to fail when a deployment leaves the worked
example out.
"""

from apps.core.service import service
from apps.zzz_canary.models import ZzzShelvedBin82


@service
def relabel_bin(*, tenant, actor, bin: ZzzShelvedBin82):  # noqa: ANN001, ANN201, A002
    """Relabel a bin."""
    bin.save(update_fields=["updated_at"])
    return bin
