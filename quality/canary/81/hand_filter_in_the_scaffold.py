"""Planted, in the probe scaffold: an archivable noun's archived cut asked for by hand.

The form that keeps rule 81 able to fail when a deployment leaves the worked
example out — the noun and the trap live in an app no product removes.
"""

from apps.core.models import Archivable, OrgScopedModel


class ZzzShelvedCrate81(OrgScopedModel, Archivable):
    pass


def _canary81_scaffold_archived_cut(tenant):  # noqa: ANN001, ANN202
    return ZzzShelvedCrate81.objects.for_tenant(tenant).filter(archived_at__isnull=False)
