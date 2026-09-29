

# Planted: a noun that declares `Archivable` — the probe app's own — and whose
# road below stops half way: it can be archived and never restored.

from django.db import models as _models74

from apps.core.models import Archivable as _Archivable74
from apps.core.models import OrgScopedModel as _OrgScoped74


class CanaryBin(_OrgScoped74, _Archivable74):
    label = _models74.CharField(max_length=32)
