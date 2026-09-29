"""What holds an archived widget out of the book: the archived policy it names.

`core.blockers` walks every installed app's `restore_blockers.py` and asks the
function registered under the noun being restored. A widget is governed by the
policy it was created under, and an archived policy governs nobody — so a
widget restored while its policy is archived would come back into the book
governed by nothing it can read. The restore refuses instead, and this is the
half that says why, and where to put it right: restore the policy first.

The mirror of `archive_blockers.py`, which holds a POLICY in the book while a
live widget names it. Between the two, a live widget never names an archived
policy, whichever order the presses come in. Nothing cascades either way.

Keyed by the noun being restored (`widget`); the answer names the blocking
noun (`widget_policy`) and the one door that clears it — that policy's restore.
"""

from __future__ import annotations

from collections.abc import Callable

from apps.core.exceptions import Blocker
from apps.core.models import Tenant
from apps.example.models import Widget, WidgetPolicy


def widget_named_policy_is_archived(*, tenant: Tenant, obj: Widget) -> tuple[Blocker, ...]:
    """One blocker when the policy this widget names is archived, else nothing.

    `for_tenant()` leaves archived policies out, so the widening is on purpose:
    `archived_only()` finds exactly the case that holds the restore. A widget
    with no policy is held by nothing. The refusal names the policy's restore
    door and never the policy's name, so it tells the restorer nothing their
    own reads would not.
    """
    if obj.policy_id is None:
        return ()
    # rule-24: a blocker asks about the ONE policy this widget already names,
    # hat or no hat — the widget is governed by it wherever the restorer acts,
    # and the refusal names a door, never the row.
    archived = (
        WidgetPolicy.objects.for_tenant(tenant).archived_only().filter(pk=obj.policy_id).exists()
    )
    if not archived:
        return ()
    return (
        Blocker(
            noun="widget_policy",
            door=f"route:widget_policy-restore?policy_id={obj.policy_id}",
            label="Restore the policy this widget names first",
        ),
    )


BLOCKERS: dict[str, Callable[..., tuple[Blocker, ...]]] = {
    "widget": widget_named_policy_is_archived,
}
