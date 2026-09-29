

# Planted: an archivable noun whose app declared no `POLICIES` pair for its
# archive and restore keys — the system actor would be waved through, and a
# workflow could archive a person's row on its own say-so.

from apps.core.models import Archivable as _Archivable74c
from apps.core.models import OrgScopedModel as _OrgScoped74c


class CanaryVault(_OrgScoped74c, _Archivable74c):
    pass
