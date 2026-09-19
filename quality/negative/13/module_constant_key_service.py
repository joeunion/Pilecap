"""The right form, kept forever: the key asked for through a module constant.

PM Overrule 4 (2026-09-15). A literals-only reading of clause (ii) would call
this service unguarded and the whole of `apps/workflows/services.py` with it —
four of its asks go through module-level constants, which is the idiom the
conventions actually teach for a key used more than once. A `Name` bound at
module level to a string constant IS the literal, resolved where it was
written, and this fixture is what keeps that true.
"""

from apps.core.authz import require
from apps.core.service import service

from .models import Gadget

CANARY_CREATE = "gadget.create"


@service
def canary_create_through_a_constant(*, tenant, actor, label: str) -> Gadget:
    """The ask is a name; the name is a literal one line up."""
    require(actor, CANARY_CREATE)
    gadget = Gadget(tenant=tenant, label=label)
    gadget.save()
    return gadget
