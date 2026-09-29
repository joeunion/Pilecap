# collides: deactivate_user — the live false pass replayed: a doorless service sharing its name with a vendor function, which the qualified census must tell apart
"""Planted: its live false pass, verbatim, in the gate's own probe app.

`apps/accounts/activities.py` called `zitadel.deactivate_user(...)` — a
different function in a different module that happened to share a name with the
doorless service `accounts.services.deactivate_user` — and the bare-name census
read the service as reached. B-ACCT caught it by hand; nothing in the engine
could. The door beside this file (`vendor.py`, called from `activities.py`) is
that shape, and this service still has no door of its own.

Planted into the probe app rather than a product one because a plant whose
liveness depends on a real app never growing a door dies the day the tree gets
healthier (rule 5's recorded lesson).
"""

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.service import service


@service
def deactivate_user(*, tenant: Tenant, actor: Actor, email: str) -> str:
    """Take a person out of service. Nothing outside this tree can call it."""
    return email
