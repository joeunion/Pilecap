"""Planted: a service REACHED, and only by this tree's own hands.

The activity beside this file calls it by name, so the old census
counted it "reachable" and said nothing more — indistinguishable, on the status
line, from a capability a person with a session can call. No route, tool,
consumer or receiver reaches it, so nobody outside this tree can; that may be
exactly right, and until somebody writes the sentence saying so it is a claim
nobody has made.

Planted into the probe app, which carries no `:internal-only` ratchet, so the
first finding is a violation.
"""

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.service import service


@service
def sweep_probe_rows(*, tenant: Tenant, actor: Actor) -> int:
    """A retention sweep. Only the worker ever calls it, and nothing says so."""
    return 0
