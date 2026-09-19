"""Planted: a service asking for a key nothing declares (clause iv).

`gadget.polish` is a perfectly ordinary-looking string. No model derives it —
the four verbs a kind gets are create/read/update/delete — and no app's
`ACTION_PROSE` declares it, so nobody can ever hold it and this service
refuses every caller for a reason no instrument can print. `require` itself
cannot say so: it resolves the key, finds no policy and falls through to the
role, which is exactly the silence this clause ends.
"""

from apps.core.authz import require
from apps.core.service import service

from .models import Gadget


@service
def canary_polish_gadget(*, tenant, actor, gadget: Gadget) -> Gadget:
    """Planted wrongness: a verb nobody declared."""
    require(actor, "gadget.polish", gadget)
    gadget.label = "polished"
    gadget.save()
    return gadget
