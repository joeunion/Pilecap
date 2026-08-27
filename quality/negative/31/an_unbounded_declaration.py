
from typing import ClassVar as _NegUnboundedClassVar

from apps.core.lifecycle import Lifecycle as _NegUnboundedLifecycle
from apps.core.lifecycle import LifecycleKind as _NegUnboundedKind
from apps.core.models import BaseModel as _NegUnboundedBase


# `unbounded`, with the two things the kind demands: a reason a reviewer can
# disagree with, and a DATED trigger that would make somebody revisit it.
# Unbounded-by-decision and unbounded-by-nobody-thinking look identical in a
# schema, and this pair is the whole difference. `core.Tenant`,
# `core.Organization` and `core.Invitation` are the live members and are silent
# for the same reason.
class NegativeUnboundedRow(_NegUnboundedBase):
    """Declared unbounded, on purpose, with the decision written down."""

    lifecycle: _NegUnboundedClassVar[_NegUnboundedLifecycle] = _NegUnboundedLifecycle(
        kind=_NegUnboundedKind.UNBOUNDED,
        reason=(
            "the probe app's standing register: it is the shape a product's own "
            "reference table has, it grows with the catalogue and not with traffic, "
            "and a row removed would take the meaning of every row that cites it."
        ),
        trigger=(
            "2026-08-24 — the first deployment whose register is large enough that a "
            "full scan of it shows up in the hot-path budgets."
        ),
    )

    label = models.CharField(max_length=64)
