"""The probe scaffold's archivable noun, for rule 82's example-free canary."""

from apps.core.models import Archivable, OrgScopedModel


class ZzzShelvedBin82(OrgScopedModel, Archivable):
    pass
