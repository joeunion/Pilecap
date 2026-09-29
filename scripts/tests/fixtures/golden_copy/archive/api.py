# collides: list_widgets_route — the self-case replays the example's fenced names on purpose
# collides: retrieve_widget — the self-case replays the example's fenced names on purpose
# collides: archive_widget_route — the self-case replays the example's fenced names on purpose
# collides: restore_widget_route — the self-case replays the example's fenced names on purpose
# collides: widget-list — the self-case replays the example's fenced names on purpose
# collides: widget-detail — the self-case replays the example's fenced names on purpose
# collides: widget-archive — the self-case replays the example's fenced names on purpose
# collides: widget-restore — the self-case replays the example's fenced names on purpose
"""The self-case's REST block: the list with `?show=`, the detail, the pair."""

# golden: archive begin
from typing import Any
from uuid import UUID

from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination
from apps.core.api.docs import Tag, refuses
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.example.selectors import Show, get_widget, list_widgets
from apps.example.services import archive_widget, restore_widget

PREFIX = "widgets"

TAGS = {
    "widgets": Tag(
        "Widgets",
        "Widgets, which leave the book by being archived and come back by a restore.",
    ),
}

router = Router(tags=["widgets"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


@router.get("/", response=list[WidgetOut], url_name="widget-list")
@paginate(CursorPagination)
def list_widgets_route(request: TenantRequest, show: Show = "live") -> Any:
    """List widgets

    The widgets your acting organization covers, newest first — the live ones,
    unless `?show=archived` asks for the archived ones or `?show=all` for both.
    """
    actor, tenant = _acting(request)
    return list_widgets(tenant=tenant, org=request.org, actor=actor, show=show)


@router.get("/{widget_id}/", response=WidgetOut, url_name="widget-detail")
def retrieve_widget(request: TenantRequest, widget_id: UUID) -> Widget:
    """Retrieve a widget

    One widget by id, archived or not. An archived widget answers read-only:
    `archived_at` and `archived_by` say when and by whom.
    """
    actor, tenant = _acting(request)
    return get_widget(tenant=tenant, widget_id=widget_id, org=request.org, actor=actor)


@router.post("/{widget_id}/archive/", response=WidgetOut, url_name="widget-archive")
@refuses("archive_blocked", "forbidden", "invalid_body", "not_found")
def archive_widget_route(request: TenantRequest, widget_id: UUID) -> Widget:
    """Archive a widget

    Take one widget out of the book. It stays readable here and in the list's
    archived cut; pressing it again answers the widget unchanged.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=request.org, actor=actor)
    return archive_widget(tenant=tenant, actor=actor, widget=widget)


@router.post("/{widget_id}/restore/", response=WidgetOut, url_name="widget-restore")
@refuses("restore_blocked", "forbidden", "invalid_body", "not_found")
def restore_widget_route(request: TenantRequest, widget_id: UUID) -> Widget:
    """Restore a widget

    Put one archived widget back in the book. Pressing it again answers the
    widget unchanged.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=request.org, actor=actor)
    return restore_widget(tenant=tenant, actor=actor, widget=widget)


# golden: archive end
