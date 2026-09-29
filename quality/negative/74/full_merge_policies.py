

# THE MERGE ROAD'S POLICIES: the archive pair and `may_merge`, each declaring
# `@refuses_system`.

from apps.core.policies import may_archive as _may_archive74n
from apps.core.policies import may_merge as _may_merge74n

POLICIES["gizmo_stencil.archive"] = _may_archive74n  # noqa: F821
POLICIES["gizmo_stencil.restore"] = _may_archive74n  # noqa: F821
POLICIES["gizmo_stencil.merge"] = _may_merge74n  # noqa: F821
