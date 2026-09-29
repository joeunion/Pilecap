

# Planted: a `Versioned` noun whose update body does not require `version` —
# a save that forgot it is silently last-write-wins.

from apps.core.models import OrgScopedModel as _OrgScoped74e
from apps.core.models import Versioned as _Versioned74e


class CanaryCard(_OrgScoped74e, _Versioned74e):
    pass
