"""The staff view of a connection: everything except the credential, read-only.

House rule 21 says every `ModelAdmin` inherits `core.admin.ServiceModelAdmin` so
that a write from here goes through the same service as a write from anywhere
else. Both admins in this file take that one step further and inherit
`ReadOnlyModelAdmin`, which is a decision worth stating rather than a shortcut:

* a **connection** is created, re-credentialled and revoked by three services
  that each take a credential or a reason and write an audit row. An admin form
  for them would mean a text box containing a live API key, rendered into a
  staff member's browser and posted back through a Django form — which is the
  one place this app has spent all its effort keeping a credential out of;
* an **inbound webhook** is a record of what somebody else sent. Editing it
  would be editing the evidence.

What staff need from here is the question "is this connection working, and what
has arrived through it" — and that is entirely readable.
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.connections.models import Connection, InboundWebhook
from apps.core.admin import ReadOnlyModelAdmin


@admin.register(Connection)
class ConnectionAdmin(ReadOnlyModelAdmin[Connection]):
    list_display = ("name", "provider", "tenant", "status", "has_credentials", "connected_at")
    list_filter = ("status", "provider")
    list_select_related = ("tenant",)
    search_fields = ("name", "provider", "tenant__slug")
    ordering = ("-created_at",)
    # `credentials` is not on this list and must never be. It is not a matter of
    # `readonly_fields` either — a read-only field is still rendered, and a
    # rendered credential is a credential in a browser, a proxy log and a
    # screenshot.
    fields = (
        "id",
        "tenant",
        "provider",
        "name",
        "status",
        "has_credentials",
        "last_error",
        "connected_at",
        "revoked_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    @admin.display(boolean=True, description="credentials stored")
    def has_credentials(self, obj: Connection) -> bool:
        return obj.has_credentials

    def get_queryset(self, request: HttpRequest) -> QuerySet[Connection]:
        return super().get_queryset(request).select_related("tenant")


@admin.register(InboundWebhook)
class InboundWebhookAdmin(ReadOnlyModelAdmin[InboundWebhook]):
    list_display = ("created_at", "connection", "event_type", "status", "handed_off_at")
    list_filter = ("status", "connection__provider")
    list_select_related = ("connection", "tenant")
    search_fields = ("event_type", "connection__name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[InboundWebhook]:
        return super().get_queryset(request).select_related("connection", "tenant")
