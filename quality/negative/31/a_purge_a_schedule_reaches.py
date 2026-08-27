
from typing import ClassVar as _NegPurgedClassVar

from apps.core.lifecycle import Lifecycle as _NegPurgedLifecycle
from apps.core.lifecycle import LifecycleKind as _NegPurgedKind
from apps.core.models import BaseModel as _NegPurgedBase


# THE TOOTH'S POSITIVE DIRECTION, and the reason it is a negative rather than a
# passing thought: this declaration names `apps.core.idempotency.purge_expired`,
# whose whole chain is written down in this tree —
#
#   ScheduleDeclaration 'events.purge-expired'
#     -> workflow PurgeExpiredWorkflow
#       -> activity purge_expired_records
#         -> apps.core.idempotency.purge_expired
#
# — so the walk must find it and stay silent. A rule that fired here would be
# refusing the one shape it exists to demand, and `core.IdempotencyRecord` is
# the live member proving the same thing on every run of the gate.
#
# Sharing a sweeper with another model is not the subject: whether a purge
# filter deletes the RIGHT rows is `does_not_cover` and is review's.
class NegativeSweptRow(_NegPurgedBase):
    """Declared purged, naming a callable a real schedule reaches."""

    lifecycle: _NegPurgedClassVar[_NegPurgedLifecycle] = _NegPurgedLifecycle(
        kind=_NegPurgedKind.PURGED,
        purged_by="apps.core.idempotency.purge_expired",
        reason=(
            "a replay cache with a TTL: past `expires_at` the row can answer nothing, "
            "so keeping it buys nothing and costs a growing table."
        ),
    )

    expires_at = models.DateTimeField()
