"""Reads: `for_tenant(...).visible_to(...)`, then one `require` (ADR core-27)."""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
from typing import Any
from uuid import UUID

from apps.example.models import Widget
from pilecap import Actor, NotFound, ScopedQuerySet, Show, require, shown
from pilecap.tenancy import Tenant

# golden: noun end

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: merge import begin
from pilecap import Invalid, Repointed, merge_counts

# golden: merge import end
# isort: split
# golden: attach merge import begin
from pilecap.attach import Tag, list_tag_links

# golden: attach merge import end
# isort: split
# golden: child entry begin
from apps.example.models import WidgetEntry

# golden: child entry end
# isort: split
# golden: policy begin
from apps.example.models import WidgetPolicy

# golden: policy end


# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
def _widgets_in(*, tenant: Tenant | None, org: Any, show: Show = "live") -> ScopedQuerySet[Widget]:
    """The scoped read without the capability; a list and a get ask it at different nodes."""
    rows: ScopedQuerySet[Widget] = shown(Widget.objects.for_tenant(tenant).visible_to(org), show)
    return rows.select_related("owner", "organization", "archived_by")


def list_widgets(
    *, tenant: Tenant | None, org: Any = None, actor: Actor, show: Show = "live"
) -> ScopedQuerySet[Widget]:
    """The widgets this hat may see, their related rows joined; no hat reads nothing."""
    # At the hat, before the queryset: a list has no row to hide.
    require(actor, "widget.read")
    return _widgets_in(tenant=tenant, org=org, show=show)


def get_widget(*, tenant: Tenant | None, widget_id: UUID, org: Any = None, actor: Actor) -> Widget:
    """One widget this hat may see, archived or not, or `NotFound`."""
    widget = _widgets_in(tenant=tenant, org=org, show="all").filter(pk=widget_id).first()
    if widget is None:
        raise NotFound()
    require(actor, "widget.read", widget)
    return widget


# golden: noun end


# golden: archive version move bulk history duplicate attach end
def get_widget_merge_preview(
    *, tenant: Tenant | None, actor: Actor, widget: Widget, into: Widget
) -> tuple[Repointed, ...]:
    """What merging `widget` into `into` would move, per owning app. Writes nothing."""
    if widget.pk == into.pk:
        raise Invalid({"into": ["A record cannot be merged into itself."]})
    require(actor, "widget.merge", widget)
    require(actor, "widget.merge", into)
    return merge_counts(tenant=tenant, loser=widget, noun="widget")


# golden: attach begin
def list_widget_tags(*, tenant: Tenant | None, actor: Actor, widget: Widget) -> list[Tag]:
    """The words on this widget as this hat sees them, through the tags app's selector."""
    # hat-scoped: a word is tenant-wide and read where the reader stands.
    require(actor, "djb_tag.read")
    links = list_tag_links(tenant=tenant, actor=actor, subject=f"widget:{widget.pk}")
    return [link.tag for link in links]


# golden: attach merge import end


# golden: policy begin
def list_widget_policies(
    *, tenant: Tenant | None, org: Any = None, actor: Actor, show: Show = "live"
) -> ScopedQuerySet[WidgetPolicy]:
    """The policies this hat may see: downward only, never the one governing it (ADR core-3)."""
    require(actor, "widget_policy.read")
    rows: ScopedQuerySet[WidgetPolicy] = shown(
        WidgetPolicy.objects.for_tenant(tenant).visible_to(org), show
    )
    return rows.select_related("organization", "archived_by")


def get_widget_policy(
    *, tenant: Tenant | None, policy_id: UUID, org: Any = None, actor: Actor
) -> WidgetPolicy:
    """One policy this hat may see — its node's or one beneath — archived or not, or `NotFound`."""
    policy = (
        WidgetPolicy.objects.for_tenant(tenant)
        .including_archived()
        .visible_to(org)
        .select_related("organization", "archived_by")
        .filter(pk=policy_id)
        .first()
    )
    if policy is None:
        raise NotFound()
    require(actor, "widget_policy.read", policy)
    return policy


def get_governing_widget_policy(
    *, tenant: Tenant | None, org: Any = None, policy_id: UUID | None = None, actor: Actor
) -> WidgetPolicy:
    """The policy governing this hat, optionally one named id."""
    require(actor, "widget_policy.read")
    policies = WidgetPolicy.objects.for_tenant(tenant).governing(org).select_related("organization")
    if policy_id is not None:
        policies = policies.filter(pk=policy_id)
    policy = policies.first()
    if policy is None:
        raise NotFound()
    return policy


# golden: policy end
# golden: child entry begin
def list_widget_entries(
    *, tenant: Tenant | None, org: Any = None, widget_id: UUID | None = None, actor: Actor
) -> ScopedQuerySet[WidgetEntry]:
    """The ledger lines this hat may see, newest first, optionally one widget's."""
    require(actor, "widget_entry.read")
    entries = WidgetEntry.objects.for_tenant(tenant).visible_to(org).select_related("organization")
    if widget_id is not None:
        widgets: list[Any] = [widget_id]
        # golden: child entry end
        # A merge keeps each line where it was written; `Widget.lineage` reads them together.
        subject = (
            Widget.objects.for_tenant(tenant)
            .including_archived()
            .visible_to(org)
            .filter(pk=widget_id)
            .first()
        )
        if subject is not None:
            widgets = Widget.lineage(subject)
        # golden: child entry begin
        entries = entries.filter(widget_id__in=widgets)
    return entries


# golden: child entry end
