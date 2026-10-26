

# A noun whose archive door is mounted under ANOTHER name and says so:
# `act_doors = {"archive": "zzz_shelving-door"}`. There is no
# `gizmo_shelf-archive` route and none is owed — the road demands the door the
# declaration names, the one `allowed_acts` offers the act at.

from django.db import models as _models74p

from apps.core.models import Archivable as _Archivable74p
from apps.core.models import OrgScopedModel as _OrgScoped74p


class GizmoShelf(_OrgScoped74p, _Archivable74p):
    act_doors = {"archive": "zzz_shelving-door"}
    label = _models74p.CharField(max_length=32)
