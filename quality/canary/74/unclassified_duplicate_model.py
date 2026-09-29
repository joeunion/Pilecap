

# Planted: a duplicable noun whose `Duplicate` declaration says nothing about one
# of its fields — `shade` is neither copied nor reset, so what a copy carries
# would be an accident of whoever wrote the service.

from django.db import models as _models74i

from apps.core.models import Duplicable as _Duplicable74i
from apps.core.models import Duplicate as _Duplicate74i
from apps.core.models import OrgScopedModel as _OrgScoped74i


class CanaryStencil(_OrgScoped74i, _Duplicable74i):
    duplicate = _Duplicate74i(copies=("label",))
    label = _models74i.CharField(max_length=32)
    shade = _models74i.CharField(max_length=32)
