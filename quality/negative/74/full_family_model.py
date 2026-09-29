

# The family's other roads, whole, on one noun: `Movable` and `Versioned`, and
# `bulk_verbs` naming the one verb it runs in bulk. Its routes are
# `full_family_routes.py` beside it; its twins the probe's mirrored `mcp.py`.

from django.db import models as _models74h

from apps.core.models import Movable as _Movable74h
from apps.core.models import OrgScopedModel as _OrgScoped74h
from apps.core.models import Versioned as _Versioned74h


class GizmoCart(_OrgScoped74h, _Movable74h, _Versioned74h):
    bulk_verbs = ("move",)
    label = _models74h.CharField(max_length=32)
