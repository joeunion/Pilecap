"""What holds a widget policy in the book: the live widgets that name it.

`core.blockers` walks every installed app's `archive_blockers.py` and asks the
function registered under the noun being archived. A policy is config that the
widgets beneath it are governed by (`WidgetPolicy` is `InheritedDownward`), and
an archived policy stops governing — so archiving one that a live widget still
names would leave that widget governed by nothing it can read. The archive
refuses instead, and this is the half that says why.

Keyed by the PARENT noun (`widget_policy`); the answer names the CHILD
(`widget`) and the door that lands on exactly the rows that hold it. Nothing
cascades: the reader archives or re-points those widgets and archives again.
"""

from __future__ import annotations

from collections.abc import Callable

from apps.core.exceptions import Blocker
from apps.core.models import Tenant
from apps.example.models import Widget, WidgetPolicy


def policy_named_by_live_widgets(*, tenant: Tenant, obj: WidgetPolicy) -> tuple[Blocker, ...]:
    """One blocker when any LIVE widget names this policy, else nothing.

    `for_tenant()` leaves archived widgets out, so an archived widget naming the
    policy holds nothing — it is out of the book already. There is no
    `visible_to` narrowing, on purpose: a widget in a branch the archiver cannot
    see is governed by this policy all the same, and a policy archived out from
    under it is the same fault whoever pressed. The refusal names the kind and
    the door, never those rows, so it confirms nothing the archiver's own list
    would not.
    """
    # rule-24: a blocker counts every live child in the tenant, hat or no hat —
    # a widget the archiver cannot see is still governed by this policy, and the
    # refusal names a door, never a row, so nothing hidden is disclosed.
    held = Widget.objects.for_tenant(tenant).filter(policy=obj).exists()
    if not held:
        return ()
    return (
        Blocker(
            noun="widget",
            door=f"route:widget-list?policy={obj.pk}",
            label="Archive the widgets that name this policy, or give them another, first",
        ),
    )


BLOCKERS: dict[str, Callable[..., tuple[Blocker, ...]]] = {
    "widget_policy": policy_named_by_live_widgets,
}
