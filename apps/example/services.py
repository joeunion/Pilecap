"""Writes: `@service`, keyword-only, authorized here, never at a door (rule 13)."""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
from typing import cast

from apps.example.events import WIDGET_ARCHIVED, WIDGET_RESTORED
from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from pilecap import (
    Actor,
    NotFound,
    archive_row,
    event_payload,
    get_logger,
    may_be_named,
    require,
    restore_row,
    service,
)
from pilecap.events import EMIT, listener
from pilecap.tenancy import Tenant

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from apps.example.events import WIDGET_UPDATED
from pilecap import as_invalid, require_live, require_version

# golden: noun end

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from uuid import UUID

from apps.example.events import WIDGET_MOVED
from apps.example.schemas import WidgetMovedOut
from pilecap import ancestor_paths, is_descendant_path, rehome
from pilecap.accounts import User
from pilecap.tenancy import Membership

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
# golden: noun begin
from pilecap import NON_FIELD_KEY, Invalid

# golden: noun end
# isort: split
from apps.example.events import WIDGET_DUPLICATED
from pilecap import duplicate_row

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.example.events import WIDGET_MERGED
from apps.example.schemas import WidgetMergedOut
from pilecap import RepointOut, merge_rows

# golden: merge import end
# isort: split
# golden: attach merge import begin
from pilecap.attach import create_tag_link, list_tag_links

# golden: attach merge import end
# isort: split
# golden: import begin
# golden: noun begin
from apps.example.events import WIDGET_CREATED

# golden: import end
# isort: split
from datetime import UTC, datetime

from apps.example.events import (
    WIDGET_DELETED,
    # golden: noun end
    # golden: policy begin
    WIDGET_POLICY_ARCHIVED,
    WIDGET_POLICY_RESTORED,
    # golden: policy end
    # golden: noun begin
)

# golden: noun end
from pilecap import require_no_merged_losers

# isort: split
# golden: child entry begin
from apps.example.models import WidgetEntry

# golden: move bulk history duplicate attach merge import begin
from pilecap.tenancy import Organization

# golden: move bulk history duplicate attach merge import end
# golden: child entry end
# isort: split
# golden: policy begin
from apps.example.models import WidgetPolicy
from apps.example.schemas import WidgetPolicyOut

# golden: policy end

# isort: split
# golden: workflow onboard begin
# golden: workflow remind begin
from django.utils import timezone

# golden: workflow remind end
from apps.example.events import WIDGET_ONBOARDED
from apps.example.schemas import WidgetOnboardedOut
from apps.example.types import WidgetOnboarding

# golden: workflow remind begin
from pilecap.workflows import start_workflow_on_commit, workflow_id

# golden: workflow onboard end
# golden: workflow remind end
# isort: split
# golden: workflow onboard begin
from pilecap.workflows import signal_workflow

# golden: workflow onboard end
# isort: split
# golden: workflow remind begin
from apps.example.events import WIDGET_REMINDED
from apps.example.types import WidgetReminder

# golden: workflow remind end
# isort: split
# golden: webhook-in onboarding begin
from apps.example.events import WIDGET_ONBOARDING_CONFIRMED
from pilecap import now

# golden: webhook-in onboarding end
# isort: split
# golden: verb touch begin
from apps.example.events import WIDGET_TOUCHED

# golden: verb touch end
# isort: split
# golden: enum status begin
from apps.example.events import WIDGET_TRANSITIONED

# golden: workflow remind begin
from pilecap import Conflict

# golden: workflow remind end

# golden: enum status end

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
log = get_logger("apps.example.services")
# golden: noun end

# golden: archive version move bulk history duplicate attach merge import end

# What may appear un-redacted in this app's log lines and audit `input`
LOG_KEYS: frozenset[str] = frozenset({"name", "approved"})

# golden: workflow onboard begin
# The signal `WidgetOnboardingWorkflow` waits on; `test_workflows.py` pins the match.
WIDGET_APPROVAL_SIGNAL = "approve"
# golden: workflow onboard end


# golden: noun begin
# golden: archive version move bulk history duplicate attach merge import begin
def _publish_widget(
    name: str, *, tenant: Tenant, widget: Widget, actor: Actor, out: WidgetOut | None = None
) -> bool:
    """Say what happened inside the write's transaction: the `Out` as every viewer sees it."""
    emit = listener(EMIT)
    if emit is None:
        log.info("example.event.unpublished", event_name=name, widget_id=str(widget.pk))
        return False
    payload = event_payload(out or WidgetOut.from_orm(widget))
    emit(name=name, tenant=tenant, payload=payload, actor=actor)
    return True


@service
def archive_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Take a widget out of the book. **A repeat press changes nothing.**"""
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.archive", widget)
    widget, changed = archive_row(tenant=tenant, actor=actor, row=widget, noun="widget")
    if changed:
        _publish_widget(WIDGET_ARCHIVED, tenant=tenant, widget=widget, actor=actor)
    return widget


@service
def restore_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Put an archived widget back in the book. **A repeat press changes nothing.**"""
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.restore", widget)
    widget, changed = restore_row(tenant=tenant, actor=actor, row=widget, noun="widget")
    if changed:
        _publish_widget(WIDGET_RESTORED, tenant=tenant, widget=widget, actor=actor)
    return widget


# golden: archive version move bulk history duplicate attach merge end
@service
def create_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    notes: str = "",
    # golden: noun end
    external_ref: str = "",
    # golden: import end
    # golden: policy begin
    policy: WidgetPolicy | None = None,
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    due_at: datetime | None = None,
    # golden: field due_at end
    # golden: import begin
) -> Widget:
    # golden: noun end
    # golden: import end
    """Create a widget in the part of the tenant the actor is acting as."""
    # golden: import begin
    # golden: noun begin
    require(actor, "widget.create")
    # golden: noun end
    # golden: import end
    # golden: policy begin
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: policy end
    # golden: import begin
    # golden: noun begin
    if actor.user is None:
        # `owner` is not nullable, and the system actor has no user to own a row.
        raise Invalid({"owner": ["A widget needs somebody to own it."]})
    if actor.org is None:
        # Fails closed, like every other unresolved scope here.
        raise Invalid(
            {"organization": ["This request resolved no acting organization to create in."]}
        )
    widget = Widget(
        tenant=tenant,
        organization=actor.org,
        owner_id=actor.user.pk,
        name=name.strip(),
        notes=notes,
        # golden: noun end
        external_ref=external_ref,
        # golden: import end
        # golden: policy begin
        policy=policy,
        # golden: policy end
        # golden: noun begin
        # golden: field due_at begin
        due_at=due_at.astimezone(UTC) if due_at is not None else None,
        # golden: field due_at end
        # golden: import begin
    )
    with as_invalid():
        widget.full_clean()
    widget.save()
    _publish_widget(WIDGET_CREATED, tenant=tenant, widget=widget, actor=actor)
    # golden: noun end
    # golden: import end
    # golden: workflow onboard begin
    # Onboarding waits for a person: a run started on commit, its id from the row (rule 18).
    start_workflow_on_commit(
        workflow="WidgetOnboardingWorkflow",
        arg=WidgetOnboarding(widget_id=str(widget.pk)),
        tenant=tenant,
        user=actor.user,
        # The hat rides along, so the activities act as the widget's branch.
        org=actor.org,
        id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
    )
    # golden: workflow onboard end
    # golden: import begin
    # golden: noun begin
    return widget
    # golden: noun end


# golden: import end


# golden: verb touch begin
@service
def touch_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Mark a widget as seen now: only `updated_at` moves, and every press is said."""
    if not may_be_named(actor, widget):
        raise NotFound()
    locked = _locked_widget(tenant=tenant, widget=widget)
    require_live(locked, noun="widget")
    require(actor, "widget.update", locked)
    locked.save(update_fields=["updated_at"])
    _publish_widget(WIDGET_TOUCHED, tenant=tenant, widget=locked, actor=actor)
    return locked


# golden: verb touch end
# golden: enum status begin
@service
def transition_widget(*, tenant: Tenant, actor: Actor, widget: Widget, status: str) -> Widget:
    """Step a widget's status along its chain; any other move is `Conflict`."""
    if not may_be_named(actor, widget):
        raise NotFound()
    locked = _locked_widget(tenant=tenant, widget=widget)
    require_live(locked, noun="widget")
    require(actor, "widget.update", locked)
    if status not in Widget.Status.values:
        raise Invalid({"status": [f"Send one of: {', '.join(Widget.Status.values)}."]})
    if Widget.STATUS_NEXT.get(locked.status) != status:
        raise Conflict("A status moves one step forward at a time, never back or past a step.")
    locked.status = status
    locked.save(update_fields=["status", "updated_at"])
    _publish_widget(WIDGET_TRANSITIONED, tenant=tenant, widget=locked, actor=actor)
    return locked


# golden: enum status end
# golden: version move bulk history duplicate attach merge import begin
# golden: noun begin
def _locked_widget(*, tenant: Tenant, widget: Widget) -> Widget:
    """The widget re-read under a row lock, archived or not — what every edit writes."""
    return (
        Widget.objects.for_tenant(tenant)
        .including_archived()
        .visible_to(widget.organization)
        .select_related("owner", "organization", "archived_by")
        .select_for_update(of=("self",))
        .get(pk=widget.pk)
    )


@service
def update_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    widget: Widget,
    version: int | None = None,
    name: str | None = None,
    notes: str | None = None,
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: policy begin
    policy: WidgetPolicy | None = None,
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    due_at: datetime | None = None,
    clear_due_at: bool = False,
    # golden: field due_at end
    # golden: version move bulk history duplicate attach merge import begin
) -> Widget:
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    """Change a widget's editable fields. Nothing else writes to the table."""
    # golden: version move bulk history duplicate attach merge import begin
    # golden: noun begin
    if not may_be_named(actor, widget):
        raise NotFound()
    locked = _locked_widget(tenant=tenant, widget=widget)
    # Every other write on the noun refuses `archived` first.
    require_live(locked, noun="widget")
    require(actor, "widget.update", locked)
    if version is not None:
        require_version(locked, version)
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: policy begin
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    if clear_due_at and due_at is not None:
        raise Invalid({"due_at": ["Send a new value or ask to clear it, not both."]})
    # golden: field due_at end
    # golden: version move bulk history duplicate attach merge import begin
    updated: list[str] = []
    if name is not None:
        locked.name = name.strip()
        updated.append("name")
    if notes is not None:
        locked.notes = notes
        updated.append("notes")
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: policy begin
    if policy is not None:
        locked.policy = policy
        updated.append("policy")
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    if due_at is not None or clear_due_at:
        locked.due_at = due_at.astimezone(UTC) if due_at is not None else None
        updated.append("due_at")
    # golden: field due_at end
    # golden: version move bulk history duplicate attach merge import begin
    if not updated:
        return locked
    with as_invalid():
        locked.full_clean()
    # `updated_at` is named, always: it IS the version (house rule 76).
    locked.save(update_fields=[*updated, "updated_at"])
    _publish_widget(WIDGET_UPDATED, tenant=tenant, widget=locked, actor=actor)
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: workflow remind begin
    _remind_widget_on_commit(tenant=tenant, actor=actor, widget=locked)
    # golden: workflow remind end
    # golden: version move bulk history duplicate attach merge import begin
    # golden: noun begin
    return locked
    # golden: noun end


# golden: version end
def _new_widget_owner(*, tenant: Tenant, owner_id: UUID, organization: Organization) -> User:
    """The person a move hands the widget to — one who belongs where it is going."""
    held = (
        Membership.objects.for_tenant(tenant)
        .filter(
            user_id=owner_id,
            organization__path__in=ancestor_paths(organization.path),
        )
        .select_related("user")
        .first()
    )
    if held is None:
        raise NotFound()
    return held.user


@service
def move_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    widget: Widget,
    # reach: a destination is a NODE, asked below as the hat's subtree.
    organization: Organization,
    owner_id: UUID | None = None,
    version: int | None = None,
) -> Widget:
    """Re-home a widget at another node, and hand it to another owner if one is named."""
    if not may_be_named(actor, widget):
        raise NotFound()
    hat = actor.org
    if hat is None or organization.tenant_id != tenant.pk:
        raise NotFound()
    if not is_descendant_path(organization.path, hat.path):
        raise NotFound()
    locked = _locked_widget(tenant=tenant, widget=widget)
    # Every other write on the noun refuses `archived` first.
    require_live(locked, noun="widget")
    require(actor, "widget.move", locked)
    require(actor, "widget.move", organization)
    if version is not None:
        require_version(locked, version)
    owner = (
        None
        if owner_id is None
        else _new_widget_owner(tenant=tenant, owner_id=owner_id, organization=organization)
    )
    left = locked.organization_id
    moved, changed = rehome(locked, organization, owner=owner, noun="widget")
    if changed:
        _publish_widget(
            WIDGET_MOVED,
            tenant=tenant,
            widget=moved,
            actor=actor,
            out=WidgetMovedOut(**WidgetOut.from_orm(moved).model_dump(), from_organization_id=left),
        )
    return cast(Widget, moved)


# golden: move bulk history end
@service
def duplicate_widget(
    *, tenant: Tenant, actor: Actor, widget: Widget, idempotency_key: str = ""
) -> Widget:
    """Make a new widget from this one, at the hat, owned by the person who pressed."""
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.create")
    if actor.user is None:
        raise Invalid({"owner": ["A widget needs somebody to own it."]})
    name = f"Copy of {widget.name}"
    try:
        copy, created = duplicate_row(
            tenant=tenant,
            row=widget,
            organization=actor.org,
            idempotency_key=idempotency_key,
            fill={"owner": actor.user, "name": name},
        )
    except Invalid as refused:
        # The one constraint over several fields a copy can meet is the name per owner.
        if NON_FIELD_KEY not in refused.errors:
            raise
        raise Invalid(
            {"name": [f"Another widget is called {name!r}. Rename it, then copy again."]}
        ) from refused
    if created:
        # golden: duplicate end
        # The words on the source come with it; notes and files stay with the source.
        subject = f"widget:{copy.pk}"
        for link in list_tag_links(tenant=tenant, actor=actor, subject=f"widget:{widget.pk}"):
            if link.tag.archived_at is None:
                create_tag_link(tenant=tenant, actor=actor, tag=link.tag, subject=subject)
        # golden: duplicate begin
        _publish_widget(WIDGET_DUPLICATED, tenant=tenant, widget=copy, actor=actor)
        # golden: duplicate attach merge import end
        # A copy is onboarded like any widget made here.
        start_workflow_on_commit(
            workflow="WidgetOnboardingWorkflow",
            arg=WidgetOnboarding(widget_id=str(copy.pk)),
            tenant=tenant,
            user=actor.user,
            org=actor.org,
            id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(copy.pk)),
        )
        # golden: duplicate attach merge import begin
    return cast(Widget, copy)


# golden: duplicate attach end
@service
# rule-82: `merge_rows` refuses an archived or merged row itself, after a repeat.
def merge_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    widget: Widget,
    into: Widget,
    version: int | None = None,
    into_version: int | None = None,
) -> Widget:
    """Fold this widget into `into`, which survives. **Not undone.**"""
    if not may_be_named(actor, widget) or not may_be_named(actor, into):
        raise NotFound()
    require(actor, "widget.merge", widget)
    require(actor, "widget.merge", into)
    first, second = sorted((widget, into), key=lambda row: str(row.pk))
    locked = {row.pk: _locked_widget(tenant=tenant, widget=row) for row in (first, second)}
    loser, survivor = locked[widget.pk], locked[into.pk]
    if loser.merged_into_id != survivor.pk:
        if version is not None:
            require_version(loser, version)
        if into_version is not None:
            require_version(survivor, into_version)
    outcome = merge_rows(tenant=tenant, actor=actor, loser=loser, into=survivor, noun="widget")
    if outcome.changed:
        _publish_widget(
            WIDGET_MERGED,
            tenant=tenant,
            widget=outcome.survivor,
            actor=actor,
            out=WidgetMergedOut(
                **WidgetOut.from_orm(outcome.survivor).model_dump(),
                loser_id=loser.pk,
                repoints=[
                    RepointOut(title=repointed.title, left=repointed.left)
                    for repointed in outcome.repoints
                ],
            ),
        )
    return cast(Widget, outcome.survivor)


# golden: merge import end
# golden: noun begin
@service
def delete_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Remove a widget; answers the deleted row with its id, so the audit names it."""
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.delete", widget)
    # golden: noun end
    # A survivor other widgets were merged into is held by their tombstones.
    require_no_merged_losers(widget, noun="widget")
    # golden: noun begin
    deleted_id = widget.pk
    widget.delete()
    widget.id = deleted_id
    _publish_widget(WIDGET_DELETED, tenant=tenant, widget=widget, actor=actor)
    return widget
    # golden: noun end


# golden: workflow onboard begin
# door: the onboarding workflow's own step, reached only from its activity under the run's hat.
@service
def mark_widget_onboarded(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Record that onboarding has begun for this widget — the activity's write."""
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.onboard", widget)
    if widget.onboarded_at is not None:
        return widget
    widget.onboarded_at = timezone.now()
    widget.save(update_fields=["onboarded_at", "updated_at"])
    return widget


# door: the onboarding workflow's closing event, said only by its activity after the wait.
@service
def announce_widget_onboarded(
    *, tenant: Tenant, actor: Actor, widget: Widget, approved: bool
) -> Widget:
    """Say that a widget finished onboarding, and how. **The activity's event.**"""
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.onboard", widget)
    _publish_widget(
        WIDGET_ONBOARDED,
        tenant=tenant,
        widget=widget,
        actor=actor,
        out=WidgetOnboardedOut(**WidgetOut.from_orm(widget).model_dump(), approved=approved),
    )
    return widget


@service
def approve_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Approve a widget that is waiting to finish onboarding. **Ends the wait.**"""
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.approve", widget)
    signal_workflow(
        tenant=tenant,
        actor=actor,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
        signal=WIDGET_APPROVAL_SIGNAL,
    )
    # golden: workflow onboard end
    # ONE `approved` line per widget; the row lock serializes two racing presses.
    Widget.objects.for_tenant(tenant).visible_to(widget.organization).select_for_update().filter(
        pk=widget.pk
    ).first()
    already = (
        WidgetEntry.objects.for_tenant(tenant)
        .visible_to(widget.organization)
        .filter(widget=widget, kind=WidgetEntry.Kind.APPROVED)
        .exists()
    )
    if already:
        return widget
    # The ledger line, written **after** the signal landed, in the same transaction.
    _entry(
        tenant=tenant,
        widget=widget,
        kind=WidgetEntry.Kind.APPROVED,
        note="Approved through the door that ends the onboarding wait.",
        organization=widget.organization,
    )
    # golden: workflow onboard begin
    return widget


# golden: workflow onboard end
# golden: workflow remind begin
def _remind_widget_on_commit(*, tenant: Tenant, actor: Actor, widget: Widget) -> None:
    """Start the reminder on this commit when the widget names an unreminded moment."""
    # does-not-cover: a moment set again after its row's run closed without acting is not reminded.
    if widget.due_at is None or widget.reminded_at is not None:
        return
    try:
        start_workflow_on_commit(
            workflow="WidgetReminderWorkflow",
            arg=WidgetReminder(widget_id=str(widget.pk)),
            tenant=tenant,
            user=actor.user,
            org=actor.org,
            id=workflow_id(tenant=tenant, app="example", noun="widget", key=f"remind-{widget.pk}"),
            reask_after_failure=True,
        )
    except Conflict:
        # The row's run already finished: one reminder per row, never a second run under its id.
        return


# door: the reminder workflow's one act, reached only from its activity under the run's hat.
@service
def mark_widget_reminded(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Record that the widget's moment arrived and say so once; a repeat keeps the first."""
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.remind", widget)
    if widget.reminded_at is not None:
        return widget
    widget.reminded_at = timezone.now()
    widget.save(update_fields=["reminded_at", "updated_at"])
    _publish_widget(WIDGET_REMINDED, tenant=tenant, widget=widget, actor=actor)
    return widget


# golden: workflow remind end
# golden: webhook-in onboarding begin
# door: the onboarding handler in `integrations.py`, behind the signed receiver.
@service
def confirm_widget_onboarding(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Record the onboarding provider's confirmation; the first kept and said once."""
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.update", widget)
    if widget.onboarding_confirmed_at is not None:
        return widget
    widget.onboarding_confirmed_at = now()
    widget.save(update_fields=["onboarding_confirmed_at", "updated_at"])
    _publish_widget(WIDGET_ONBOARDING_CONFIRMED, tenant=tenant, widget=widget, actor=actor)
    return widget


# golden: webhook-in onboarding end
# golden: policy begin
@service
def create_widget_policy(
    *, tenant: Tenant, actor: Actor, name: str, body: str = ""
) -> WidgetPolicy:
    """Set a policy at the part of the tenant the actor is acting as."""
    require(actor, "widget_policy.create")
    if actor.org is None:
        raise Invalid(
            {"organization": ["This request resolved no acting organization to set a policy in."]}
        )
    policy = WidgetPolicy(tenant=tenant, organization=actor.org, name=name.strip(), body=body)
    with as_invalid():
        policy.full_clean()
    policy.save()
    return policy


def _publish_widget_policy(
    name: str, *, tenant: Tenant, policy: WidgetPolicy, actor: Actor
) -> None:
    """Say a policy left the book or came back — `_publish_widget`'s shape, for its `Out`."""
    emit = listener(EMIT)
    if emit is None:
        log.info("example.event.unpublished", event_name=name, policy_id=str(policy.pk))
        return
    payload = event_payload(WidgetPolicyOut.from_orm(policy))
    emit(name=name, tenant=tenant, payload=payload, actor=actor)


@service
def archive_widget_policy(*, tenant: Tenant, actor: Actor, policy: WidgetPolicy) -> WidgetPolicy:
    """Take a policy out of the book — refused while a live widget still names it."""
    if not may_be_named(actor, policy):
        raise NotFound()
    require(actor, "widget_policy.archive", policy)
    policy, changed = archive_row(tenant=tenant, actor=actor, row=policy, noun="widget_policy")
    if changed:
        _publish_widget_policy(WIDGET_POLICY_ARCHIVED, tenant=tenant, policy=policy, actor=actor)
    return policy


@service
def restore_widget_policy(*, tenant: Tenant, actor: Actor, policy: WidgetPolicy) -> WidgetPolicy:
    """Put an archived policy back in the book, where it governs again."""
    if not may_be_named(actor, policy):
        raise NotFound()
    require(actor, "widget_policy.restore", policy)
    policy, changed = restore_row(tenant=tenant, actor=actor, row=policy, noun="widget_policy")
    if changed:
        _publish_widget_policy(WIDGET_POLICY_RESTORED, tenant=tenant, policy=policy, actor=actor)
    return policy


# golden: policy end
# golden: child entry begin
def _entry(
    *,
    tenant: Tenant,
    widget: Widget,
    kind: str,
    note: str,
    organization: Organization,
) -> WidgetEntry:
    """Append one ledger line. **The only write path onto `WidgetEntry`.**"""
    entry = WidgetEntry(
        tenant=tenant,
        organization=organization,
        widget=widget,
        kind=kind,
        note=note,
    )
    with as_invalid():
        entry.full_clean()
    entry.save()
    return entry


@service
def record_widget_entry(
    *,
    tenant: Tenant,
    actor: Actor,
    widget: Widget,
    kind: str = WidgetEntry.Kind.NOTE,
    note: str = "",
    organization_slug: str | None = None,
) -> WidgetEntry:
    """Append a ledger line. **The entry lands where the widget is.**"""
    # REACHABILITY FIRST, then the capability: not-there before not-yours.
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget_entry.record", widget)
    organization = widget.organization
    if organization_slug is not None:
        named = Organization.objects.for_tenant(tenant).filter(slug=organization_slug).first()
        if named is None:
            raise Invalid(
                {"organization": [f"No organization here is called {organization_slug!r}."]}
            )
        organization = named
    return _entry(tenant=tenant, widget=widget, kind=kind, note=note, organization=organization)


# golden: child entry end
