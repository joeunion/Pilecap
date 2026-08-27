
from typing import ClassVar as _CanaryClassVar

from apps.core.lifecycle import Lifecycle as _CanaryLifecycle
from apps.core.lifecycle import LifecycleKind as _CanaryLifecycleKind
from apps.core.models import BaseModel as _CanaryPurgedBase


# , PLANTED. The sweeper is written, the declaration names it, the TTL column
# is there — and no `ScheduleDeclaration` in any app's `activities.py::SCHEDULES`
# reaches it, so nothing ever calls it. This is the exact shape `purge_expired`
# had for a whole cycle, and the only difference between this canary and a real
# outage is that this one is planted on purpose.
#
# The callable is real and imports cleanly (see the fixture planted beside this
# one in `apps/example/services.py`): the finding must be about the missing
# SCHEDULE and not about a path that does not resolve, because those are two
# different repairs.
class CanaryStrandedPurge(_CanaryPurgedBase):
    """Declared purged, with a sweeper no schedule starts."""

    lifecycle: _CanaryClassVar[_CanaryLifecycle] = _CanaryLifecycle(
        kind=_CanaryLifecycleKind.PURGED,
        purged_by="apps.example.services.purge_canary_stranded_rows",
    )

    expires_at = models.DateTimeField()
