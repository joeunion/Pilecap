

# THE ARCHIVE ROAD'S POLICY PAIR: `may_archive` declares `@refuses_system`, so
# the system actor gets its answer (no) rather than the exemption.

from apps.core.policies import may_archive as _may_archive74
from apps.core.policies import may_move as _may_move74

POLICIES["gizmo_bin.archive"] = _may_archive74  # noqa: F821
POLICIES["gizmo_bin.restore"] = _may_archive74  # noqa: F821
POLICIES["gizmo_cart.move"] = _may_move74  # noqa: F821
