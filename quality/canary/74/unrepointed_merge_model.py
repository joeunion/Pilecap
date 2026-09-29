

# Planted: a mergeable noun with a child that points at it and that nobody
# re-points or keeps — after a merge the child would still name the tombstone.

from django.db import models as _models74j

from apps.core.models import Archivable as _Archivable74j
from apps.core.models import Mergeable as _Mergeable74j
from apps.core.models import OrgScopedModel as _OrgScoped74j


class CanaryLedgerBook(_OrgScoped74j, _Archivable74j, _Mergeable74j):
    label = _models74j.CharField(max_length=32)


class CanaryLedgerLine(_OrgScoped74j):
    book = _models74j.ForeignKey(
        CanaryLedgerBook, on_delete=_models74j.PROTECT, related_name="lines"
    )
