

# Planted: the tote's record, answered without its `tags`.

from pydantic import BaseModel as _BaseModel74k


class CanaryToteOut(_BaseModel74k):
    """A tote, as the probe app would return one."""

    label: str = "spare parts"


@router.get("/totes/{tote_id}/", response=CanaryToteOut, url_name="canary_tote-detail")
def canary_tote_detail(request, tote_id: str):
    """Retrieve a tote

    One tote by id — and never the words on it.
    """
    return CanaryToteOut()
