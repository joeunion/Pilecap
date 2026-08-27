"""The mirror of the canary, and the reason the resolution is not a tax.

The same two modules, the same colliding name — and this time the door calls
BOTH: the vendor client AND the service. A census that fired here would be
saying that a door may not talk to an upstream whose function shares a name
with the service it calls, which is a rule about vocabulary, not about doors.
"""

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.service import service


@service
def deactivate_user(*, tenant: Tenant, actor: Actor, email: str) -> str:
    """Take a person out of service. The activity beside this file calls it."""
    return email
