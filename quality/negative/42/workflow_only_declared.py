"""The same shape with the sentence written: reached only from an activity, and
said so.

The marker is the same `# door:` the doorless case uses — one grammar to learn
for a claim that is the same claim one degree weaker — and the count it lands in
(`internal_only_declared`) is what tells the two apart on the status line.
"""

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.service import service


# door: a retention sweep the schedule drives; there is no persona who runs it,
# and a route onto it would be a route onto the worker's own clock
@service
def sweep_probe_rows(*, tenant: Tenant, actor: Actor) -> int:
    """A retention sweep, deliberately the worker's alone."""
    return 0
