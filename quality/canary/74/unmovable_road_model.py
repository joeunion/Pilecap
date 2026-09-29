

# Planted: a noun that declares `Movable` and draws no move route — it says it
# can change node, and no door can move it.

from apps.core.models import Movable as _Movable74d
from apps.core.models import OrgScopedModel as _OrgScoped74d


class CanaryDolly(_OrgScoped74d, _Movable74d):
    pass
