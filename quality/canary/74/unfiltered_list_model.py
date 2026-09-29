

# Planted: a second archivable noun whose road is drawn in full EXCEPT the one
# parameter that lets anybody see what was archived.

from django.db import models as _models74b

from apps.core.models import Archivable as _Archivable74b
from apps.core.models import OrgScopedModel as _OrgScoped74b


class CanaryCrate(_OrgScoped74b, _Archivable74b):
    label = _models74b.CharField(max_length=32)
