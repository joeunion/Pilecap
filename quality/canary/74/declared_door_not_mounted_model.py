

# Planted: a noun whose archive door is DECLARED under another name
# (`act_doors`) and never mounted. The road demands the door the declaration
# names — `zzz_shelving-door` — so the finding names it, never the derived
# `canary_shelf-archive` nobody asked for.

from django.db import models as _models74o

from apps.core.models import Archivable as _Archivable74o
from apps.core.models import OrgScopedModel as _OrgScoped74o


class CanaryShelf(_OrgScoped74o, _Archivable74o):
    act_doors = {"archive": "zzz_shelving-door"}
    label = _models74o.CharField(max_length=32)
