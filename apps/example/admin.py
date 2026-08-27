"""The admin for the example app — a door like any other.

Nothing here writes to the model. `service_for` names the service for each
action and `core.admin.ServiceModelAdmin` calls it with the acting actor and
tenant, so a change a support agent makes here goes through exactly the same
validation, authorization and audit trail as the same change through the API.

**`WidgetEntry` is deliberately not registered here, and that is the point of
it.** The model declares `append_only`, and a `ModelAdmin` is a door with an
edit form and a delete action on it by default — the one door in the product
that would hand somebody a way to rewrite a ledger line. "No admin" is
therefore the same statement as "no PATCH route and no update tool": the
absence is the contract, not an omission somebody will helpfully fill in.
`WidgetPolicy` is unregistered for the quieter reason that config a branch sets
for its children belongs to that branch, and a staff form that wrote it would
be writing it as whatever hat the staff member happened to be wearing.
"""

from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.admin import Action, ServiceModelAdmin
from apps.example.models import Widget
from apps.example.services import create_widget, delete_widget, update_widget


@admin.register(Widget)
class WidgetAdmin(ServiceModelAdmin[Widget]):
    list_display = ("name", "tenant", "organization", "owner", "created_at")
    list_select_related = ("tenant", "organization", "owner")
    search_fields = ("name", "owner__email", "organization__slug")
    # `tenant`, `organization` and `owner` are not editable here, and their
    # absence is the enforcement: a form that offered them would be the one door
    # in the product that can place a row in a tenant — or a branch — it is not
    # acting in. They are shown on the page and set by the service, from the
    # acting hat.
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
        """Map the form onto the service's signature.

        `owner`, `tenant` and `organization` are not arguments a service takes
        here: the widget belongs to whoever created it, in the tenant and the
        branch the staff member is acting in. Letting an admin form set any of
        them would be the one door that can write a row into a tenant — or a
        branch — it is not acting in.
        """
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
