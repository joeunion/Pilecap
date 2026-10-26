"""The admin for the example app — a door like any other."""

# golden: noun begin
from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.example.models import Widget
from apps.example.services import create_widget, delete_widget, update_widget
from pilecap.admin import Action, ServiceModelAdmin


@admin.register(Widget)
class WidgetAdmin(ServiceModelAdmin[Widget]):
    list_display = ("name", "tenant", "organization", "owner", "created_at")
    list_select_related = ("tenant", "organization", "owner")
    search_fields = ("name", "owner__email", "organization__slug")
    # `tenant`, `organization` and `owner` are set by the service, from the acting hat.
    readonly_fields = ("id", "tenant", "organization", "owner", "created_at", "updated_at")
    fields = (
        "name",
        "notes",
        "id",
        "tenant",
        "organization",
        "owner",
        "created_at",
        "updated_at",
    )

    # What `delete_widget` and `update_widget` take the row as.
    object_kwarg = "widget"

    def service_for(self, action: Action) -> Any | None:
        return {
            "create": create_widget,
            "update": update_widget,
            "delete": delete_widget,
        }[action]

    def call_service(self, service: Any, **kwargs: Any) -> None:
        """Map the form onto the service's signature."""
        form, actor, tenant = kwargs["form"], kwargs["actor"], kwargs["tenant"]
        fields = {
            name: form.cleaned_data[name] for name in form.changed_data if name in {"name", "notes"}
        }
        if kwargs["change"]:
            service(tenant=tenant, actor=actor, widget=kwargs["obj"], **fields)
        else:
            service(tenant=tenant, actor=actor, **fields)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Widget]:
        return super().get_queryset(request).select_related("tenant", "organization", "owner")


# golden: noun end
