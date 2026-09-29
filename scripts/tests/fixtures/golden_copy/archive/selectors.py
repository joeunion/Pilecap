# collides: list_widgets — the self-case replays the example's fenced names on purpose
# collides: get_widget — the self-case replays the example's fenced names on purpose
"""The self-case's read block: the live book, the archived cut, and the detail."""

# golden: archive begin
from typing import Any, Literal
from uuid import UUID

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.example.models import Widget

Show = Literal["live", "archived", "all"]


def list_widgets(
    *, tenant: Tenant | None, org: Any, actor: Actor, show: Show = "live"
) -> ScopedQuerySet[Widget]:
    """The widgets this hat may see — the live book unless `show` asks otherwise."""
    require(actor, "widget.read")
    read = Widget.objects.for_tenant(tenant)
    if show == "archived":
        read = read.archived_only()
    elif show == "all":
        read = read.including_archived()
    return read.visible_to(org)


def get_widget(*, tenant: Tenant | None, widget_id: UUID, org: Any, actor: Actor) -> Widget:
    """One widget this hat may see, archived or not — an archived one reads read-only."""
    widget = (
        Widget.objects.for_tenant(tenant)
        .including_archived()
        .visible_to(org)
        .filter(pk=widget_id)
        .first()
    )
    if widget is None:
        raise NotFound()
    require(actor, "widget.read", widget)
    return widget


# golden: archive end
