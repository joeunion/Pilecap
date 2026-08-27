
from typing import ClassVar as _NegAppendClassVar

from apps.core.lifecycle import Lifecycle as _NegAppendLifecycle
from apps.core.lifecycle import LifecycleKind as _NegAppendKind
from apps.core.models import BaseModel as _NegAppendBase


# `append_only`, declared BOTH ways and coherently: `append_only = True` is rule
# 20's population (the rows are unrewritable) and the `APPEND_ONLY` lifecycle is
# rule 31's (the rows never leave). The two are deliberately separate attributes
# — a table can be one without being the other — and `core.AuditEntry` is the
# live member carrying both, silent under both rules for exactly this reason.
class NegativeWitnessedFact(_NegAppendBase):
    """Declared append-only under both rules, coherently."""

    append_only: _NegAppendClassVar[bool] = True

    lifecycle: _NegAppendClassVar[_NegAppendLifecycle] = _NegAppendLifecycle(
        kind=_NegAppendKind.APPEND_ONLY,
        reason=(
            "a witnessed fact: what it records was true at the moment it was written, "
            "and a trail whose oldest rows can be rewritten is not a trail. Growth is "
            "real and is accepted rather than unnoticed."
        ),
        trigger=(
            "2026-08-24 — archival, when it comes, is a dated residual and never a "
            "delete nobody remembers; the first stated retention obligation turns this "
            "into a `purged` declaration whose callable moves rows to cold storage."
        ),
    )

    happened_at = models.DateTimeField()
