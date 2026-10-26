from django.db import transaction

from apps.core.roads import road


# Legal: `close_sockets_on_commit`'s shape with the registration inside a marked road.
@road("zzz_close_on_commit", example="apps/zzz_canary/services.py::zzz_close_on_commit")
def zzz_close_on_commit(*, user_id: str, reason: str) -> None:
    """Ask for the kick once the write that withdrew the access has landed."""

    def kick_on_commit() -> None:
        return None

    transaction.on_commit(kick_on_commit, robust=True)
