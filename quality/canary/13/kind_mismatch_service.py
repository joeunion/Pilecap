"""Planted: a service that authorizes one noun and writes another (clause iii).

The shape this whole clause exists for, and the reason it is not caught
anywhere else: `canary_create_gadget` is decorated, keyword-only, takes an
actor and CALLS `require` — every older clause of rule 13 reads it as green —
while the capability it asks for is a `widget_policy` and the row it writes is
a `Gadget`. Somebody who may configure widget policy now creates gadgets.
"""

from apps.core.authz import require
from apps.core.service import service

from .models import Gadget


@service
def canary_create_gadget(*, tenant, actor, label: str) -> Gadget:
    """Planted wrongness: asks about the policy, writes the row."""
    require(actor, "widget_policy.create")
    gadget = Gadget(tenant=tenant, label=label)
    gadget.save()
    return gadget
