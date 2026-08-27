
from typing import ClassVar as _NegBoundedClassVar

from apps.core.lifecycle import Lifecycle as _NegBoundedLifecycle
from apps.core.lifecycle import LifecycleKind as _NegBoundedKind
from apps.core.models import BaseModel as _NegBoundedBase


# `bounded`: the rows die with their parent, and the CASCADE is the lifecycle.
# No reason and no trigger, deliberately — a cascade is a mechanism the schema
# already states, not a decision somebody has to defend. `core.Membership` is
# the live member of this kind and it is silent for the same reason.
class NegativeBoundedRow(_NegBoundedBase):
    """Declared bounded; the parent's delete is what removes it."""

    lifecycle: _NegBoundedClassVar[_NegBoundedLifecycle] = _NegBoundedLifecycle(
        kind=_NegBoundedKind.BOUNDED,
    )

    widget = models.ForeignKey("example.Widget", on_delete=models.CASCADE)
