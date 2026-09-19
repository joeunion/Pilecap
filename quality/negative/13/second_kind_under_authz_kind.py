"""The valve, with a reason: one ask, two kinds, the second one declared.

A service legitimately writes more than one kind — a create that also stamps a
counter, an archive that also closes a child. Clause (iii) does not forbid
that; it forbids doing it SILENTLY. The `# authz-kind:` comment on the second
write is the sentence a reviewer can disagree with, and the gate counts every
one of them on rule 13's own status line (`authz_kind_valves`), so the
population is readable rather than inferred.
"""

from apps.core.authz import require
from apps.core.service import service

from .models import Gadget, Gizmo


@service
def canary_make_gadget_and_gizmo(*, tenant, actor, label: str) -> Gadget:
    """One capability, two rows — and the second row says why."""
    require(actor, "gadget.create")
    gadget = Gadget(tenant=tenant, label=label)
    gadget.save()
    companion = Gizmo(tenant=tenant, label=label)
    # authz-kind: a gadget is never made without its gizmo — the pair is the
    # unit of the act, and `gadget.create` is the capability over the pair. A
    # separate `gizmo.create` would be a second permission nobody could fail
    # independently of the first.
    companion.save()
    return gadget
