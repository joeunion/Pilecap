# collides: archive_widget — the self-case replays the example's fenced names on purpose
# collides: restore_widget — the self-case replays the example's fenced names on purpose
"""The self-case's service block, and the placement CANARY.

The archive pair over `core.verbs`, plus one private helper whose fenced
`require_live(...)` sits after its `return` inside the same fence: dead code
the copy would carry and the copied test would never reach. The placement
step must red on it naming the copied file and line; the copy the self-case
builds takes `negative/archive/services.py` in this file's place.
"""

# golden: archive begin
import importlib

from apps.core.actor import Actor
from apps.core.authz import may_be_named, require
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.core.service import service
from apps.core.verbs import archive_row, require_live, restore_row
from apps.example.events import WIDGET_ARCHIVED, WIDGET_RESTORED
from apps.example.models import Widget
from apps.example.schemas import WidgetOut


def _say(name: str, *, tenant: Tenant, widget: Widget, actor: Actor) -> None:
    """Emit through `core.bridge` — a registry lookup, never an import of the spine."""
    emit = importlib.import_module("apps.core.bridge").find("events.emit")
    if emit is not None:
        payload = WidgetOut.from_orm(widget).model_dump(mode="json")
        emit(name=name, tenant=tenant, payload=payload, actor=actor)


@service
def archive_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Take a widget out of the book. A repeat is unchanged; a live child refuses."""
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.archive", widget)
    widget, changed = archive_row(tenant=tenant, actor=actor, row=widget, noun="widget")
    if changed:
        _say(WIDGET_ARCHIVED, tenant=tenant, widget=widget, actor=actor)
    return widget


@service
def restore_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Put an archived widget back in the book. A repeat is unchanged."""
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.restore", widget)
    widget, changed = restore_row(tenant=tenant, actor=actor, row=widget, noun="widget")
    if changed:
        _say(WIDGET_RESTORED, tenant=tenant, widget=widget, actor=actor)
    return widget


def _live(widget: Widget) -> Widget:
    """Hand a widget back — and then, unreachably, ask whether it is live."""
    return widget
    require_live(widget, noun="widget")


# golden: archive end
