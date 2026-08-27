"""The staff door onto the spine. Reading, mostly — and one write, through a service.

House rule 21: every `ModelAdmin` inherits `core.admin.ServiceModelAdmin`, and
scoped models are filtered to the acting tenant by it.

Three of these four tables are **read-only from here**, and that is the design
rather than a shortcut: an `Event` is a statement that something happened and
editing one would be editing history; an `Outbox` row's state is the dispatch
workflow's to move, and a human flipping it to "dispatched" would be telling the
product a lie it can never detect; a `Delivery` is the record of what was sent.
Re-sending is `manage.py replay_events`, which re-enqueues properly and leaves
an audit row.

`WebhookEndpoint` is the exception, because adding a subscriber is exactly the
kind of thing somebody does from the admin — and it goes through
`services.register_endpoint`, so it is authorised, audited, and emits its event
like every other write.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.admin import Action, ReadOnlyModelAdmin, ServiceModelAdmin
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint


@admin.register(Event)
class EventAdmin(ReadOnlyModelAdmin[Event]):
    """What happened, in this tenant, newest first."""

    list_display = ("occurred_at", "name", "v", "actor_kind", "correlation_id")
    list_filter = ("name", "actor_kind")
    search_fields = ("name", "correlation_id", "causation_id", "trace_id")
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Event]:
        return super().get_queryset(request).select_related("tenant", "actor_user")


@admin.register(Outbox)
class OutboxAdmin(ReadOnlyModelAdmin[Outbox]):
    """Which events have been told to everybody, and which have not."""

    list_display = ("created_at", "event", "status", "attempts", "dispatched_at")
    list_filter = ("status",)
    search_fields = ("event__name",)
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Outbox]:
        return super().get_queryset(request).select_related("event")


@admin.register(Delivery)
class DeliveryAdmin(ReadOnlyModelAdmin[Delivery]):
    """Every attempt at every subscriber, including the ones that gave up."""

    list_display = ("created_at", "event", "endpoint", "status", "attempts", "last_code")
    list_filter = ("status",)
    search_fields = ("event__name", "endpoint__url", "correlation_id")
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Delivery]:
        return super().get_queryset(request).select_related("event", "endpoint")


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(ServiceModelAdmin[WebhookEndpoint]):
    """A tenant's subscriptions. Created through the service, like every write."""

    # The secret is on the add form and deliberately in no list column: a
    # signing key does not belong in a screenshot or over somebody's shoulder.
    list_display = ("url", "is_active", "description", "created_at")
    list_filter = ("is_active",)
    search_fields = ("url", "description")

    def service_for(self, action: Action) -> Any | None:
        from apps.events.services import deactivate_endpoint, register_endpoint

        # There is no `update_endpoint`: changing an endpoint's URL is adding a
        # subscriber and removing one, and doing it as an edit would deliver a
        # tenant's events somewhere new with no record of the decision.
        #
        # "Delete" **deactivates**. `Delivery.endpoint` is PROTECT, so the row
        # cannot go without taking the record of what was sent to it, and
        # "stop delivering here" is what the person clicking it means.
        if action == "create":
            return register_endpoint
        if action == "delete":
            return deactivate_endpoint
        return None

    object_kwarg = "endpoint"
