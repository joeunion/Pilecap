

# The merge and duplicate roads, whole, on one noun: archivable (a merged loser
# is archived), mergeable with its one child KEPT on the loser by `merge_keeps`,
# and duplicable with every field classified. Its routes are
# `full_merge_routes.py` beside it; its twins the probe's mirrored `mcp.py`.

from django.db import models as _models74n

from apps.core.models import Archivable as _Archivable74n
from apps.core.models import Duplicable as _Duplicable74n
from apps.core.models import Duplicate as _Duplicate74n
from apps.core.models import Mergeable as _Mergeable74n
from apps.core.models import OrgScopedModel as _OrgScoped74n


class GizmoStencil(_OrgScoped74n, _Archivable74n, _Mergeable74n, _Duplicable74n):
    merge_keeps = {"strokes": "an append-only record stays where it was written"}
    duplicate = _Duplicate74n(copies=("label",), resets=("inked_at",))
    label = _models74n.CharField(max_length=32)
    inked_at = _models74n.DateTimeField(null=True, blank=True)


class GizmoStencilStroke(_OrgScoped74n):
    append_only = True
    stencil = _models74n.ForeignKey(
        GizmoStencil, on_delete=_models74n.PROTECT, related_name="strokes"
    )
