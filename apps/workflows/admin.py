"""Visibility over durable work, and nothing else.

Read-only by construction: a run is written by `apps.workflows.services` as the
workflow progresses, and a person editing a status here would be editing the
product's record of what Temporal did — which Temporal would then disagree
with. When the two disagree, Temporal is right.

`ReadOnlyModelAdmin` rather than a raw `ModelAdmin` (house rule 21): `WorkflowRun`
is tenant-scoped, so the list is narrowed through `for_tenant` to the tenant the
staff member is acting in, like every other read in the product.
"""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.admin import ReadOnlyModelAdmin
from apps.workflows.models import WorkflowRun


@admin.register(WorkflowRun)
class WorkflowRunAdmin(ReadOnlyModelAdmin[WorkflowRun]):
    list_display = ("type", "workflow_id", "tenant", "status", "started_at", "finished_at")
    list_filter = ("status", "type")
    list_select_related = ("tenant",)
    search_fields = ("workflow_id", "run_id", "type", "tenant__slug")
    date_hierarchy = "started_at"
    readonly_fields = (
        "id",
        "tenant",
        "workflow_id",
        "run_id",
        "type",
        "status",
        "started_at",
        "finished_at",
        "error",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[WorkflowRun]:
        return super().get_queryset(request).select_related("tenant")
