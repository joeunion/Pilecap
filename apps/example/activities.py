# golden: workflow onboard begin
# golden: workflow remind begin
"""Where the example's workflows touch the world: restore the actor, read, call a service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

from django.db import close_old_connections
from temporalio import activity
from temporalio.exceptions import ApplicationError

from apps.example import services
from apps.example.selectors import get_widget
from apps.example.types import WidgetAnnouncement, WidgetMoment, WidgetOnboarding, WidgetReminder
from pilecap import Archived, current_actor

# golden: workflow remind end


@activity.defn(name="mark_widget_onboarded", no_thread_cancel_exception=True)
def mark_widget_onboarded(payload: WidgetOnboarding) -> str:
    """Mark the widget onboarded and answer when, as an ISO string; the first mark is kept."""
    close_old_connections()
    try:
        # Nobody clicked this: the system actor, under the hat the run was started with.
        actor = current_actor(kind="system")
        widget = get_widget(
            tenant=actor.tenant, widget_id=UUID(payload.widget_id), org=actor.org, actor=actor
        )
        try:
            marked = services.mark_widget_onboarded(
                tenant=widget.tenant, actor=actor, widget=widget
            )
        except Archived as refused:
            raise ApplicationError(
                refused.detail, type=refused.code, non_retryable=True
            ) from refused
        return marked.onboarded_at.isoformat() if marked.onboarded_at is not None else ""
    finally:
        close_old_connections()


@activity.defn(name="announce_widget_onboarded", no_thread_cancel_exception=True)
def announce_widget_onboarded(payload: WidgetAnnouncement) -> str:
    """Emit `example.widget.onboarded` through the service that owns it; answers the widget id."""
    close_old_connections()
    try:
        actor = current_actor(kind="system")
        widget = get_widget(
            tenant=actor.tenant, widget_id=UUID(payload.widget_id), org=actor.org, actor=actor
        )
        try:
            announced = services.announce_widget_onboarded(
                tenant=widget.tenant,
                actor=actor,
                widget=widget,
                approved=payload.approved,
            )
        except Archived as refused:
            raise ApplicationError(
                refused.detail, type=refused.code, non_retryable=True
            ) from refused
        return str(announced.pk)
    finally:
        close_old_connections()


# golden: workflow onboard end
# golden: workflow remind begin
def _epoch(moment: date | datetime) -> float:
    """A `date` or an aware `datetime` as epoch seconds; a bare date is its midnight in UTC."""
    if not isinstance(moment, datetime):
        moment = datetime.combine(moment, time.min, tzinfo=UTC)
    return moment.timestamp()


@activity.defn(name="read_widget_due_at", no_thread_cancel_exception=True)
def read_widget_due_at(payload: WidgetReminder) -> WidgetMoment:
    """The row's `due_at` as epoch seconds; `None` when it has none."""
    close_old_connections()
    try:
        actor = current_actor(kind="system")
        widget = get_widget(
            tenant=actor.tenant, widget_id=UUID(payload.widget_id), org=actor.org, actor=actor
        )
        until = _epoch(widget.due_at) if widget.due_at is not None else None
        return WidgetMoment(widget_id=payload.widget_id, until=until)
    finally:
        close_old_connections()


@activity.defn(name="mark_widget_reminded", no_thread_cancel_exception=True)
def mark_widget_reminded(payload: WidgetMoment) -> str:
    """Remind once, if `due_at` is still the moment slept to; answers when."""
    close_old_connections()
    try:
        actor = current_actor(kind="system")
        widget = get_widget(
            tenant=actor.tenant, widget_id=UUID(payload.widget_id), org=actor.org, actor=actor
        )
        if widget.due_at is None or _epoch(widget.due_at) != payload.until:
            return ""
        try:
            marked = services.mark_widget_reminded(tenant=widget.tenant, actor=actor, widget=widget)
        except Archived as refused:
            raise ApplicationError(
                refused.detail, type=refused.code, non_retryable=True
            ) from refused
        return marked.reminded_at.isoformat() if marked.reminded_at is not None else ""
    finally:
        close_old_connections()


# golden: workflow remind end
# golden: workflow onboard begin
# golden: workflow remind begin
ACTIVITIES: list[Callable[..., Any]] = [
    # golden: workflow remind end
    mark_widget_onboarded,
    announce_widget_onboarded,
    # golden: workflow onboard end
    # golden: workflow remind begin
    read_widget_due_at,
    mark_widget_reminded,
    # golden: workflow onboard begin
]
# golden: workflow remind end
# golden: workflow onboard end
