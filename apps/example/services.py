"""Writes for the example app — every rule a service has to satisfy, visible.

Services own writes. A route calls a service; it never calls `.save()` or
`.delete()` itself, and no logic lives in a signal — this app ships no
`signals.py` on purpose.

Each one is `@service`, which is what makes it keyword-only (checked at import),
atomic, traced, logged and audited. Each takes `tenant` and `actor` explicitly:
`tenant` because a write must never read the tenant from global state, and
`actor` because **the service authorizes, not the door** — `require(actor,
"widget.update", widget)` is here so that the REST route, the MCP tool, the
admin and an activity all get the same answer instead of three copies of it.

**The acting organization comes from the actor, never from an argument.**
`create_widget` writes the row into `actor.org` — the hat the door resolved and
revalidated — so no caller can name a branch it holds no membership over, in
the same way no caller can name a tenant. A write with no hat is refused rather
than guessed at.

Refusals are `apps.core.exceptions` and nothing else: no `HttpError`, no
`Http404`, no status code (house rule 14).

Two things a service also owns are visible here: **it says what happened**
(`_publish`, inside the same transaction as the write it describes) and **it
starts the work that has to wait** (`start_workflow_on_commit`, registered on
the same transaction's commit). Neither is a signal, and neither is a door's.
"""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
import importlib
import importlib.util
from collections.abc import Callable
from typing import Any, cast

from apps.core.actor import Actor
from apps.core.authz import may_be_named, require
from apps.core.exceptions import NotFound
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.schemas import event_payload
from apps.core.service import service
from apps.core.verbs import archive_row, restore_row
from apps.example.events import WIDGET_ARCHIVED, WIDGET_RESTORED
from apps.example.models import Widget
from apps.example.schemas import WidgetOut

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from apps.core.concurrency import require_version
from apps.core.exceptions import as_invalid
from apps.core.verbs import require_live
from apps.example.events import WIDGET_UPDATED

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from uuid import UUID

from apps.accounts.models import User
from apps.core.models import Membership, Organization, ancestor_paths, is_descendant_path
from apps.core.verbs import rehome
from apps.example.events import WIDGET_MOVED

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
from apps.core.exceptions import NON_FIELD_KEY, Invalid
from apps.core.verbs import duplicate_row
from apps.example.events import WIDGET_DUPLICATED

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.core.verbs import merge_rows
from apps.example.events import WIDGET_MERGED

# golden: merge import end
# isort: split
# golden: attach merge import begin
from apps.tags.selectors import list_tag_links
from apps.tags.services import create_tag_link

# golden: attach merge import end
# isort: split
# golden: import begin
from apps.example.events import WIDGET_CREATED

# golden: import end
# isort: split
from django.utils import timezone

from apps.core.verbs import require_no_merged_losers
from apps.example.events import (
    WIDGET_DELETED,
    WIDGET_ONBOARDED,
    WIDGET_POLICY_ARCHIVED,
    WIDGET_POLICY_RESTORED,
)
from apps.example.models import WidgetEntry, WidgetPolicy
from apps.example.schemas import WidgetPolicyOut
from apps.example.types import WidgetOnboarding
from apps.workflows.services import signal_workflow, start_workflow_on_commit, workflow_id

# golden: archive version move bulk history duplicate attach merge import begin
log = get_logger("apps.example.services")

# golden: archive version move bulk history duplicate attach merge import end

# What may appear un-redacted in this app's log lines and audit `input`
# (`core.service`). An allow-list, not a blocklist: a widget's `notes` are the
# customer's prose and could be anything, so they are not on it. `approved` is a
# yes-or-no about a process rather than a fact about a person.
LOG_KEYS: frozenset[str] = frozenset({"name", "approved"})

# golden: archive version move bulk history duplicate attach merge import begin
# Where the runtime registry lives, and the name `apps.events` fills in from its
# `AppConfig.ready()`. Both are strings rather than an import on purpose — see
# `_event_bus`.
BRIDGE_MODULE = "apps.core.bridge"
EMIT = "events.emit"

# golden: archive version move bulk history duplicate attach merge import end

# The signal `WidgetOnboardingWorkflow` waits on. Named here rather than
# imported from `workflows.py`, because a `workflows.py` is a module that has to
# replay identically years from now and nothing outside the worker should be
# importing it to read a string. That leaves one name in two files, so
# `tests/test_workflows.py` reads the workflow's own signal definition and
# refuses the day they stop matching — the drift is caught, not hoped against.
WIDGET_APPROVAL_SIGNAL = "approve"


# golden: archive version move bulk history duplicate attach merge import begin
def _event_bus() -> Callable[..., Any] | None:
    """`events.emit`, resolved at call time through `core.bridge`, or `None`.

    **A registry lookup, never an import.** The layer contract would allow a
    domain app to import `apps.events` outright; what it cannot promise is that
    the app is *there*. The spine apps are removable — a template stripped back
    to `core` and one domain app still has to run. `architecture.md` gives that
    inversion one shape, `core.bridge`: a runtime registry the higher apps fill
    from `AppConfig.ready()`. This is a caller taking that door.

    **`find()` first, then `get()` once, and the order is the whole point.**
    `get()` never returns `None` — with nothing registered it hands back a
    logging no-op — so a caller that wanted to know whether anybody was
    listening could not find out from it, and this function used to answer
    "yes" in a tree that had published nothing. `find()` is the
    accessor that can say no.

    Asking `get()` afterwards is not a second attempt at the same question; it
    is a different one, and only production answers it. There, an absent
    registration is `BridgeNotRegistered` and the caller's transaction rolls
    back, because a deployment quietly dropping every event on the floor is the
    failure `core.bridge` was built to refuse. Everywhere else `get()` returns
    the no-op, nothing calls it, and the `None` here is what makes the caller
    log `example.event.unpublished` and carry on — a template must not fail a
    customer's write because a webhook had nowhere to go.
    """
    if importlib.util.find_spec(BRIDGE_MODULE) is None:
        return None
    bridge = importlib.import_module(BRIDGE_MODULE)
    found: Any = bridge.find(EMIT)
    if found is not None:
        return cast(Callable[..., Any], found)
    # Production refuses here; every other environment falls through to `None`.
    bridge.get(EMIT)
    return None


def _publish(
    name: str,
    *,
    tenant: Tenant,
    widget: Widget,
    actor: Actor,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Say that something happened, in the transaction it happened in.

    The payload is the **schema**, not the model: `WidgetOut` is what a REST
    client gets, so a webhook subscriber and a socket client see the same shape
    for the same fact rather than a third one invented here. `extra` carries what
    is true of the *event* and not of the row — an onboarding that nobody
    approved is a fact about the run, and there is no column for it.

    **The schema goes last, and the precedence is the point.** This used to
    merge `extra` *after* the schema, so a caller could
    overwrite any field of the row's own read shape — including
    `organization_id`, which is the key `events.emit` narrows the socket fan-out
    on. One call site passes `extra` today and it is benign, but this file is
    the worked example a product copies, and what it taught was an overridable
    narrowing key. Reordering rather than fencing the one key: the row's read
    shape is the authority for *every* field on it, not just that one, and a
    rule that listed the protected fields would be a list that goes stale.
    `extra` is additive by construction now — a key it shares with the schema is
    a caller bug, and the row wins.

    Returns whether anything was listening, which is a fact worth having in a
    test — and a log line worth having in a tree where the bus is not mounted.
    """
    emit = _event_bus()
    # NEVER a per-viewer field on an event: `allowed_acts` is what one caller may
    # press, and a subscriber is somebody else. The payload is the row, built by
    # the one helper that strips every per-viewer field at any depth.
    row = event_payload(WidgetOut.from_orm(widget))
    payload = {**(extra or {}), **row}
    if emit is None:
        # `event_name`, not `event`: structlog's own first argument is called
        # `event`, and a log line that shadows it is a `TypeError` at 2am.
        log.info("example.event.unpublished", event_name=name, widget_id=str(widget.pk))
        return False
    # `name=`, not positional: `events.emit` is `@service` and house rule 13
    # makes every service keyword-only, checked at import. The `actor` that
    # crosses is the `Actor` itself, not `actor.user` — the spine records which
    # *kind* of principal acted (human, agent, system) and a bare user cannot
    # say.
    emit(name=name, tenant=tenant, payload=payload, actor=actor)
    return True


@service
def archive_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Take a widget out of the book. **A repeat press changes nothing.**

    Reachability first (not-there and not-yours are one answer), then the
    capability at the row's own node (`widget.archive` is `may_archive`: an
    administrator of the widget's branch, never the system), then the row half
    `core.verbs.archive_row` owns: the row lock, the idempotent early return,
    the blocker walk and the two columns. The event is said ONLY when this
    press changed the row — a retried request answers the archived widget and
    tells no subscriber a second time.
    """
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.archive", widget)
    widget, changed = archive_row(tenant=tenant, actor=actor, row=widget, noun="widget")
    if changed:
        _publish(WIDGET_ARCHIVED, tenant=tenant, widget=widget, actor=actor)
    return widget


@service
def restore_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Put an archived widget back in the book. **A repeat press changes nothing.**

    The mirror of `archive_widget`, over `core.verbs.restore_row`: a live
    widget comes back unchanged and says nothing; an archived one loses both
    archive columns and `example.widget.restored` is said once.
    """
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.restore", widget)
    widget, changed = restore_row(tenant=tenant, actor=actor, row=widget, noun="widget")
    if changed:
        _publish(WIDGET_RESTORED, tenant=tenant, widget=widget, actor=actor)
    return widget


# golden: archive version move bulk history duplicate attach merge end
@service
def create_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    notes: str = "",
    external_ref: str = "",
    # golden: import end
    policy: WidgetPolicy | None = None,
    # golden: import begin
) -> Widget:
    # golden: import end
    """Create a widget in the part of the tenant the actor is acting as.

    The actor owns what they create, and the **hat** decides where it lands: a
    seller creating a widget creates it at that seller, and nobody above the
    seller's parent will ever see it. There is deliberately no `organization=`
    parameter — a caller that could name one could write a row into a branch it
    holds no membership over, which is the tenancy hole one level down.

    **`policy` is a row and not an id**, which is what lets the reachability
    question be asked about it at all. The door answers `may_be_named` where a
    reviewer can see the line (house rule 26); this service asks it again, and
    the two answers are not redundant — the door's is the *visible* fence and
    this one is the *audited* one, because a refusal raised inside a `@service`
    carries `outcome=error` on the audit trail and a 404 raised at a door does
    not.

    `external_ref` is the id the widget has in the system it came from — what
    an import finds it by (`importers.py`); blank for a widget made here.
    """
    # golden: import begin
    require(actor, "widget.create")
    # golden: import end
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: import begin
    if actor.user is None:
        # `widget.create` already refuses an actor with no membership, and the
        # system actor has no user to own a row. Stated rather than assumed,
        # because `owner` is not nullable and the alternative is a 500.
        raise Invalid({"owner": ["A widget needs somebody to own it."]})
    if actor.org is None:
        # Fails closed, like every other unresolved scope here: a row written
        # with no organization would be invisible to every read in the product,
        # including the root's.
        raise Invalid(
            {"organization": ["This request resolved no acting organization to create in."]}
        )
    widget = Widget(
        tenant=tenant,
        organization=actor.org,
        owner_id=actor.user.pk,
        name=name.strip(),
        notes=notes,
        external_ref=external_ref,
        # golden: import end
        policy=policy,
        # golden: import begin
    )
    with as_invalid():
        widget.full_clean()
    widget.save()
    _publish(WIDGET_CREATED, tenant=tenant, widget=widget, actor=actor)
    # golden: import end
    # Onboarding waits for a person, so it is a workflow and not the rest of this
    # function. The start is registered on this transaction's commit: a create
    # that rolls back onboards nothing. The id is deterministic and derived from
    # the row (house rule 18), so a retried create starts one run, not two.
    start_workflow_on_commit(
        workflow="WidgetOnboardingWorkflow",
        arg=WidgetOnboarding(widget_id=str(widget.pk)),
        tenant=tenant,
        user=actor.user,
        # The hat rides along, so the activities that run days later read and
        # write as the branch this widget belongs to rather than as the tenant.
        org=actor.org,
        id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
    )
    # golden: import begin
    return widget


# golden: import end
@service
def approve_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Approve a widget that is waiting to finish onboarding. **Ends the wait.**

    The counterpart to `create_widget`: that one starts a run which waits up to
    a week for a person, and this one is the person. It writes nothing — the
    approval *is* the signal, and what it changes is the workflow's state, not
    the row's. The row changes when the workflow's own activity says so, which
    is why `onboarded_at` and the `example.widget.onboarded` event are set and
    emitted out there and not here: a service that wrote both would be claiming
    an outcome the run has not reached yet.

    The workflow id is **derived** from the row (house rule 18), never
    remembered and never passed in, so this is exactly the id `create_widget`
    used. Everything after that is `workflows.signal_workflow`'s: an unknown or
    finished run is `NotFound` or `Conflict` from there, and both come back out
    of this service unchanged because a refusal about the run *is* the answer to
    "did this approval land".

    Approving twice while the run is still going is deliberately an `ok`: a
    client that retried a request it never saw the answer to must not be told it
    conflicted, and a workflow that sets the same flag twice is in the state it
    was in after the first.
    """
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.approve", widget)
    signal_workflow(
        tenant=tenant,
        actor=actor,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
        signal=WIDGET_APPROVAL_SIGNAL,
    )
    # ONE `approved` line per widget, however many times it is pressed: the
    # contract says a repeat changes nothing, and a second line would be a
    # second approval on the ledger. The widget's row lock serializes two
    # presses racing each other, so the second sees the first's line.
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
    # The ledger line the done-line drives, written **after** the signal landed
    # and inside the same transaction, so an approval that was refused by the
    # run leaves no line claiming it happened. It is not a second
    # authorization: `widget.approve` is strictly the stronger question (it is
    # held by `admin` over the row's own branch and by nobody else — the sweep
    # moved that sentence from a rank table into the role layer), and asking
    # `widget_entry.record` again here would be a check that can only ever say
    # yes.
    _entry(
        tenant=tenant,
        widget=widget,
        kind=WidgetEntry.Kind.APPROVED,
        note="Approved through the door that ends the onboarding wait.",
        organization=widget.organization,
    )
    return widget


# golden: version move bulk history duplicate attach merge import begin
def _locked(*, tenant: Tenant, widget: Widget) -> Widget:
    """The widget re-read under a row lock, archived or not — what every edit writes.

    The comparison a versioned edit makes is against the row as it stands
    while nobody else may write it, so two saves carrying the same version
    serialize and the second is refused rather than both passing a check made
    before either wrote. Archived rows are read too, so the refusal an archived
    widget earns is `archived` and never a missing row. `of=("self",)` locks
    the widget alone, not the owner and the node the read selects beside it.
    """
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
    # golden: version move bulk history duplicate attach merge import end
    policy: WidgetPolicy | None = None,
    # golden: version move bulk history duplicate attach merge import begin
) -> Widget:
    # golden: version move bulk history duplicate attach merge import end
    """Change a widget's editable fields. Nothing else writes to the table.

    Neither the tenant nor the organization is a field a caller may change:
    moving a row between tenants is a different operation with different rules,
    and moving one between branches is `move_widget`'s job. It is not this one.

    **`version` is the version the caller read** (`Widget.version`), and both
    doors require it: the widget is locked, and a version it no longer has is
    `stale_version` naming the current one, with nothing written. `None` is for
    a caller that never read the row through a door — the admin's form, an
    importer applying a file — and keeps last-write-wins under the same lock.

    `policy` is `None` for "leave it alone", like every other field here — which
    means this service can attach a policy and swap one, and cannot clear one.
    That asymmetry is deliberate rather than an oversight: `None` is already
    spoken for by the patch grammar, and "remove the config this row is governed
    by" is a different sentence that deserves its own verb the day a product
    needs it. The row it is given has been through `may_be_named` at the door,
    exactly as `create_widget`'s has.
    """
    # golden: version move bulk history duplicate attach merge import begin
    locked = _locked(tenant=tenant, widget=widget)
    # Every other write on the noun refuses `archived` first.
    require_live(locked, noun="widget")
    require(actor, "widget.update", locked)
    if version is not None:
        require_version(locked, version)
    # golden: version move bulk history duplicate attach merge import end
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: version move bulk history duplicate attach merge import begin
    updated: list[str] = []
    if name is not None:
        locked.name = name.strip()
        updated.append("name")
    if notes is not None:
        locked.notes = notes
        updated.append("notes")
    # golden: version move bulk history duplicate attach merge import end
    if policy is not None:
        locked.policy = policy
        updated.append("policy")
    # golden: version move bulk history duplicate attach merge import begin
    if not updated:
        return locked
    with as_invalid():
        locked.full_clean()
    # `updated_at` is named, always: it IS the version (house rule 76).
    locked.save(update_fields=[*updated, "updated_at"])
    _publish(WIDGET_UPDATED, tenant=tenant, widget=locked, actor=actor)
    return locked


# golden: version end
def _new_owner(*, tenant: Tenant, owner_id: UUID, organization: Organization) -> User:
    """The person a move hands the widget to — one who belongs where it is going.

    A widget's owner reads it through their own membership, and visibility
    inherits downwards only, so the new owner must hold a membership at the
    destination or on its ancestor chain; anybody else could never see the
    widget they were handed. Anyone who does not is `not_found`, the answer an
    id naming nobody gets.
    """
    held = (
        Membership.objects.filter(
            tenant=tenant,
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
    # reach: a destination is a NODE, and a node is its own reach — asked below
    # as the hat's subtree, as `core.selectors.get_organization` reads it.
    organization: Organization,
    owner_id: UUID | None = None,
    version: int | None = None,
) -> Widget:
    """Re-home a widget at another node, and hand it to another owner if one is named.

    **Reach at both ends, then the capability at both ends**: the widget
    must be one this hat could have named and the destination inside the hat's
    subtree — either miss is `not_found`, never `forbidden` — and then
    `widget.move` is asked of the widget where it lives and of the node it is
    going to (`core.policies.may_move`: an administrator at each end, never the
    system). A new owner must belong at the destination or above it.

    `core.verbs.rehome` does the row half: the lock, the idempotent early
    return (already there and already theirs → unchanged, no event), every
    mutable row that derives its organization from the widget carried along,
    and `move_blocked` over a ledger line (`WidgetEntry` is append-only, so a
    widget with an entry stays where its ledger was written). The event names
    both nodes: the row where it now is, and `from_organization_id`.
    """
    if not may_be_named(actor, widget):
        raise NotFound()
    hat = actor.org
    if hat is None or organization.tenant_id != tenant.pk:
        raise NotFound()
    if not is_descendant_path(organization.path, hat.path):
        raise NotFound()
    locked = _locked(tenant=tenant, widget=widget)
    # Every other write on the noun refuses `archived` first.
    require_live(locked, noun="widget")
    require(actor, "widget.move", locked)
    require(actor, "widget.move", organization)
    if version is not None:
        require_version(locked, version)
    owner = (
        None
        if owner_id is None
        else _new_owner(tenant=tenant, owner_id=owner_id, organization=organization)
    )
    left = locked.organization_id
    moved, changed = rehome(locked, organization, owner=owner, noun="widget")
    if changed:
        _publish(
            WIDGET_MOVED,
            tenant=tenant,
            widget=moved,
            actor=actor,
            extra={"from_organization_id": str(left)},
        )
    return cast(Widget, moved)


# golden: move bulk history end
@service
def duplicate_widget(
    *, tenant: Tenant, actor: Actor, widget: Widget, idempotency_key: str = ""
) -> Widget:
    """Make a new widget from this one, at the hat, owned by the person who pressed.

    A duplicate IS a create: the capability asked is `widget.create` at the
    acting hat, where the copy lands (ADR core-20), after reach on the source.
    `Widget.duplicate` says what carries across (the notes, the policy) and
    what starts again; the service FILLS what starts again that it decides —
    the owner is the presser, the name `Copy of <name>` — and
    `core.verbs.duplicate_row` sets both before the copy's one save. The ledger
    never copies: it is the source's history, not the copy's.

    **A repeated press with the same key answers the first copy** and says
    nothing; a second copy under the same name for the same person is
    `invalid` naming `name` (the name is unique per owner) with nothing written.
    """
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first: a copy is made
    # from a widget in the book.
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
        # The one constraint over several fields a copy can meet is the name per
        # owner, which the copy's validation reports object-wide: said here as
        # the field it is, so a screen can point at it.
        if NON_FIELD_KEY not in refused.errors:
            raise
        raise Invalid(
            {"name": [f"You already have a widget called {name!r}. Rename it, then copy again."]}
        ) from refused
    if created:
        # golden: duplicate end
        # The words on the source come with it — a tag is how the widget is
        # FOUND, so a copy that lost them would be lost itself. Notes and files
        # are the source's own and stay with it. Archived words are left behind.
        subject = f"widget:{copy.pk}"
        for link in list_tag_links(tenant=tenant, actor=actor, subject=f"widget:{widget.pk}"):
            if link.tag.archived_at is None:
                create_tag_link(tenant=tenant, actor=actor, tag=link.tag, subject=subject)
        # golden: duplicate begin
        _publish(WIDGET_DUPLICATED, tenant=tenant, widget=copy, actor=actor)
        # golden: duplicate attach merge import end
        # A copy is onboarded like any widget made here: the same run a create
        # starts, on this transaction's commit, under the id the copy implies.
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
# rule-82: `merge_rows` refuses an archived or merged row itself, AFTER it has
# answered a repeat of the same pair unchanged — a guard here would refuse the retry.
def merge_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    widget: Widget,
    into: Widget,
    version: int | None = None,
    into_version: int | None = None,
) -> Widget:
    """Fold this widget into `into`, which survives. **Not undone.**

    Reach on both rows, then `widget.merge` on both (an administrator of each
    record's branch, never the system), then — unless this pair is already
    merged, which answers the survivor unchanged — the versions both were read
    at. `core.verbs.merge_rows` does the row half under a lock on both, in pk
    order: every owning app's repointer moves ITS rows (notes, tags, files)
    from the loser to the survivor, the ledger stays where it was written
    (`Widget.merge_keeps`), and the loser is archived with `merged_into` naming
    the survivor — it still reads, and every change to it is `merged`.

    The event is the SURVIVOR's row, `loser_id`, and `repoints` — what each
    owning app moved, as the apply counted it.
    """
    if not may_be_named(actor, widget) or not may_be_named(actor, into):
        raise NotFound()
    require(actor, "widget.merge", widget)
    require(actor, "widget.merge", into)
    first, second = sorted((widget, into), key=lambda row: str(row.pk))
    locked = {row.pk: _locked(tenant=tenant, widget=row) for row in (first, second)}
    loser, survivor = locked[widget.pk], locked[into.pk]
    if loser.merged_into_id != survivor.pk:
        if version is not None:
            require_version(loser, version)
        if into_version is not None:
            require_version(survivor, into_version)
    outcome = merge_rows(tenant=tenant, actor=actor, loser=loser, into=survivor, noun="widget")
    if outcome.changed:
        _publish(
            WIDGET_MERGED,
            tenant=tenant,
            widget=outcome.survivor,
            actor=actor,
            extra={
                "loser_id": str(loser.pk),
                "repoints": [
                    {"title": repointed.title, "left": repointed.left}
                    for repointed in outcome.repoints
                ],
            },
        )
    return cast(Widget, outcome.survivor)


# golden: merge import end
@service
def delete_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Remove a widget.

    It returns the row it deleted rather than `None`, so the audit entry can
    name what went — a deletion whose audit row says only "delete_widget" is
    one you will want to read in six months and cannot.

    Django clears `pk` on the instance after a delete, so it is put back: the
    object is detached and will not be saved again, and the id is the only part
    of it that still means anything.

    A widget other widgets were merged into refuses `merge_survivor`, naming
    the archive: their tombstones name it, and nothing is removed.
    """
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.delete", widget)
    # A survivor other widgets were merged into is held by their tombstones.
    require_no_merged_losers(widget, noun="widget")
    deleted_id = widget.pk
    widget.delete()
    widget.id = deleted_id
    _publish(WIDGET_DELETED, tenant=tenant, widget=widget, actor=actor)
    return widget


@service
def mark_widget_onboarded(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Record that onboarding has begun for this widget. **The activity's write.**

    Called by `mark_widget_onboarded` in `activities.py` and by nothing else —
    which is the shape every workflow write takes here: the activity restores the
    tenant and the actor, the service does the writing and the authorizing.

    **Idempotent**, because Temporal guarantees an activity runs *at least* once:
    a second call on an already-onboarded widget keeps the first timestamp rather
    than moving it. The retry that lands after a worker crash must not rewrite
    history, and the honest timestamp is the earlier one.

    **An archived widget refuses `archived`**, like every other write on it: a
    run that waited while somebody took the widget out of the book does not
    mark it behind their back.
    """
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.onboard", widget)
    if widget.onboarded_at is not None:
        return widget
    widget.onboarded_at = timezone.now()
    widget.save(update_fields=["onboarded_at", "updated_at"])
    return widget


@service
def announce_widget_onboarded(
    *, tenant: Tenant, actor: Actor, widget: Widget, approved: bool
) -> Widget:
    """Say that a widget finished onboarding, and how. **The activity's event.**

    A separate service from `mark_widget_onboarded` because they are separated by
    a wait that can last a week: the mark happens immediately, the announcement
    only once somebody has approved — or once nobody has, which the payload says
    rather than hides.

    **An archived widget refuses `archived`**: finishing its onboarding is a
    change to a widget that is out of the book, and a subscriber told
    "onboarded" about an archived widget is told something nobody reviewing
    the book will see. The activity does not retry it (`activities.py`).
    """
    # Every other write on the noun refuses `archived` first.
    require_live(widget, noun="widget")
    require(actor, "widget.onboard", widget)
    _publish(
        WIDGET_ONBOARDED,
        tenant=tenant,
        widget=widget,
        actor=actor,
        extra={"approved": approved},
    )
    return widget


@service
def create_widget_policy(
    *, tenant: Tenant, actor: Actor, name: str, body: str = ""
) -> WidgetPolicy:
    """Set a policy at the part of the tenant the actor is acting as.

    Identical in shape to `create_widget` and deliberately so: the hat decides
    where it lands, there is no `organization=` parameter, and a request that
    resolved no hat is refused rather than guessed at. The difference is what
    the row then *does* — a widget is seen by this branch and the ones above it;
    a policy is obeyed by this branch and the ones **below** it, which is the
    whole of `InheritedDownward` and the reason it is a declaration on the model
    rather than a flag on the write.
    """
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


def _publish_policy(name: str, *, tenant: Tenant, policy: WidgetPolicy, actor: Actor) -> None:
    """Say a policy left the book or came back — `_publish`'s shape, for the policy's `Out`."""
    emit = _event_bus()
    if emit is None:
        log.info("example.event.unpublished", event_name=name, policy_id=str(policy.pk))
        return
    payload = event_payload(WidgetPolicyOut.from_orm(policy))
    emit(name=name, tenant=tenant, payload=payload, actor=actor)


@service
def archive_widget_policy(*, tenant: Tenant, actor: Actor, policy: WidgetPolicy) -> WidgetPolicy:
    """Take a policy out of the book — refused while a live widget still names it.

    `archive_row` asks every app's `archive_blockers.py`; this app's says a
    policy named by a live widget is held, and the refusal is `archive_blocked`
    naming the widgets' door. Nothing is written and nothing cascades. A repeat
    press answers the archived policy and says nothing.
    """
    if not may_be_named(actor, policy):
        raise NotFound()
    require(actor, "widget_policy.archive", policy)
    policy, changed = archive_row(tenant=tenant, actor=actor, row=policy, noun="widget_policy")
    if changed:
        _publish_policy(WIDGET_POLICY_ARCHIVED, tenant=tenant, policy=policy, actor=actor)
    return policy


@service
def restore_widget_policy(*, tenant: Tenant, actor: Actor, policy: WidgetPolicy) -> WidgetPolicy:
    """Put an archived policy back in the book, where it governs again."""
    if not may_be_named(actor, policy):
        raise NotFound()
    require(actor, "widget_policy.restore", policy)
    policy, changed = restore_row(tenant=tenant, actor=actor, row=policy, noun="widget_policy")
    if changed:
        _publish_policy(WIDGET_POLICY_RESTORED, tenant=tenant, policy=policy, actor=actor)
    return policy


def _entry(
    *,
    tenant: Tenant,
    widget: Widget,
    kind: str,
    note: str,
    organization: Organization,
) -> WidgetEntry:
    """Append one ledger line. **The only write path onto `WidgetEntry`.**

    Private and shared, because two public services append a line — a person
    recording one, and `approve_widget` recording its own outcome — and a ledger
    written two ways is a ledger with two shapes. There is no `_update_entry`
    beside it and there is no code path anywhere that updates or deletes one:
    `WidgetEntry.append_only` says so as a declaration the gate can read (house
    rule 20, over the discovered population), and this module's silence is the
    other half of it.

    `full_clean()` before `save()` is what makes the **landing gate** live: an
    `organization` that disagrees with the widget's is a field-level refusal on
    `organization`, not a row in the wrong branch. The gate is a model
    invariant, and this is the line that runs it.
    """
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
    """Append a line to a widget's ledger. **The entry lands where the widget is.**

    The organization is *derived*, not chosen: it comes from the widget this
    line is about, which is what `WidgetEntry.derive_org_from = "widget"`
    declares and what the model's `clean()` enforces. A caller may say which
    branch they believe it is — `organization_slug` — and the only value that
    will be accepted is the one the derivation would have produced anyway.
    Naming any other branch is a refusal on the `organization` field.

    That parameter therefore adds no reach and is not the hole the "no
    `organization=` on a write" convention warns about: it cannot place a row
    anywhere, because the gate refuses every value except the derived one. What
    it does is make the gate a **live refusal on the wire** rather than an
    invariant only a unit test can reach — which matters, because the failure
    the gate exists for (a row stamped with the actor's hat while its parent
    lives elsewhere) is silent, and a fence nobody can walk into is a fence
    nobody maintains.

    `widget` is a row rather than an id for the same reason `create_widget`'s
    `policy` is: it is a foreign-key target the caller named, so the door that
    named it answered `may_be_named(actor, widget)` where a reviewer can see it.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked at the node
    # the ROW names, so asking it first turned a widget outside this hat's
    # subtree into `forbidden` — which tells the caller the row exists.
    # Not-there before not-yours, as `core.revoke_membership` orders it.
    if not may_be_named(actor, widget):
        raise NotFound()
    # Every other write on the noun refuses `archived` first. An archived
    # widget's ledger is read-only with the rest of it: a line appended out of
    # the book is a change nobody reviewing the book sees.
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
