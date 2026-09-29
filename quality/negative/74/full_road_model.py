

# The archive road's noun, whole: `Archivable` after the scoped base. Its road
# is `full_road_routes.py` beside it, and its twins come from the probe app's
# one `mcp.py`, which mirrors every route the router ends up with.

from django.db import models as _models74

from apps.core.models import Archivable as _Archivable74
from apps.core.models import OrgScopedModel as _OrgScoped74


class GizmoBin(_OrgScoped74, _Archivable74):
    label = _models74.CharField(max_length=32)
