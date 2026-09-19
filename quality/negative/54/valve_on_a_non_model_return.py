"""The valve on a read the ANNOTATION puts outside clauses (d)/(e).

An aggregate read — a total, a per-meter measure, a display the rule cannot
resolve to a kind — is outside the findings by annotation, and its author still
writes the sentence, because the sentence is what a reviewer reads. Clause (d)
must stay silent here: the return annotation names no model, so there is no
kind to ask about and nothing to flag.

What this file is the control for is the COUNT, not the silence. The valve
above is counted into `read_open_valves` on the rule's status line even though
no finding could ever have been raised against this function — the population a
valve may be written in is every public `get_`/`list_` a `selectors.py`
declares, and the population a finding may be raised over is the subset an
annotation resolves. Two valves in `apps/usage` sat in the difference between
those two sets, uncounted, for a whole cycle: a valve nobody counts is an off
switch with a comment on it.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class GadgetTotal:
    """Not a model: an aggregate the rule cannot resolve to a kind."""

    gadget: str
    total: Decimal


def list_gadget_totals(*, tenant, actor) -> list[GadgetTotal]:
    """Totals per gadget, for the part of the tenant this hat wears.

    # read-open: an aggregate over rows the caller's own read already
    # authorized — there is no row of a kind handed back here, only a sum, and
    # the door's read is the selector that lists the rows this totals.
    """
    return []
