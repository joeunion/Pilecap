

# Planted: the trolley's move route, and nothing that reads its history.

from apps.core.schemas import HomedOut as _HomedOut74g
from apps.core.schemas import MoveIn as _MoveIn74g


@router.post("/trolleys/{trolley_id}/move/", response=_HomedOut74g, url_name="canary_trolley-move")
def canary_trolley_move(request, trolley_id: str, payload: _MoveIn74g):
    """Move a trolley

    Re-home one trolley at another organization.
    """
    return _HomedOut74g(organization_id=trolley_id, organization_name="Branch")
