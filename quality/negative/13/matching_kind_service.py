"""The right form, kept forever: the ask and the write name the same kind.

Two silences in one fixture, and both are load-bearing. `canary_make_gadget`
asks `gadget.create` and writes a `Gadget`, so clause (iii) has nothing to say.
`canary_burnish_gadget` asks `gadget.burnish` — a verb NO kind derives, in the
vocabulary only because the planted `policies.py` declares it — so clause (iv)
has nothing to say either. If the declared half of the key set ever stopped
being read, this file would start firing, which is the only way anybody would
find out.
"""

from apps.core.authz import require
from apps.core.service import service

from .models import Gadget


@service
def canary_make_gadget(*, tenant, actor, label: str) -> Gadget:
    """The ordinary shape: authorize the noun you are about to write."""
    require(actor, "gadget.create")
    gadget = Gadget(tenant=tenant, label=label)
    gadget.save()
    return gadget


@service
def canary_burnish_gadget(*, tenant, actor, gadget: Gadget) -> Gadget:
    """A declared verb outside the four — legal, and the census says so."""
    require(actor, "gadget.burnish", gadget)
    gadget.label = "burnished"
    gadget.save()
    return gadget
