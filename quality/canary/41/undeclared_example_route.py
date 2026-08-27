

# Planted: a NEW schema whose fields declare no examples, which is what pushes
# the census past its recorded ratchet. In the published document these arrive
# as `"channel": "channel"` and `"status": "status"` — always shaped right,
# never saying anything, which is the whole reason declaring one was made a seam
# (the owner's ruling of 2026-08-24). The ratchet is over the WHOLE population,
# so one new undeclared field is enough: that is the property worth having.

from ninja import Schema


class CanaryTrinketOut(Schema):
    """A trinket, as the probe app would return one."""

    channel: str
    status: str
    attempts: int


@router.get("/trinket/{trinket_id}/", response=CanaryTrinketOut, url_name="trinket-detail")
def canary_trinket_detail(request, trinket_id: str):
    """Retrieve a trinket

    One trinket by id, from the caller's tenant.
    """
    return CanaryTrinketOut(channel="email", status="sent", attempts=1)
