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

import importlib
import importlib.util
from collections.abc import Callable
from typing import Any, cast

from django.utils import timezone

from apps.core.actor import Actor
from apps.core.authz import may_be_named, require
from apps.core.exceptions import Invalid, NotFound, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.service import service
from apps.example.events import (
    WIDGET_CREATED,
    WIDGET_DELETED,
    WIDGET_ONBOARDED,
    WIDGET_UPDATED,
)
from apps.example.models import Widget, WidgetEntry, WidgetPolicy
from apps.example.schemas import WidgetOut
from apps.example.types import WidgetOnboarding
from apps.workflows.services import signal_workflow, start_workflow_on_commit, workflow_id

log = get_logger("apps.example.services")

# What may appear un-redacted in this app's log lines and audit `input`
# (`core.service`). An allow-list, not a blocklist: a widget's `notes` are the
# customer's prose and could be anything, so they are not on it. `approved` is a
# yes-or-no about a process rather than a fact about a person.
LOG_KEYS: frozenset[str] = frozenset({"name", "approved"})

# Where the runtime registry lives, and the name `apps.events` fills in from its
# `AppConfig.ready()`. Both are strings rather than an import on purpose — see
# `_event_bus`.
BRIDGE_MODULE = "apps.core.bridge"
EMIT = "events.emit"

# The signal `WidgetOnboardingWorkflow` waits on. Named here rather than
# imported from `workflows.py`, because a `workflows.py` is a module that has to
# replay identically years from now and nothing outside the worker should be
# importing it to read a string. That leaves one name in two files, so
# `tests/test_workflows.py` reads the workflow's own signal definition and
# refuses the day they stop matching — the drift is caught, not hoped against.
WIDGET_APPROVAL_SIGNAL = "approve"


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
    payload = {**(extra or {}), **WidgetOut.from_orm(widget).model_dump(mode="json")}
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
def create_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    notes: str = "",
    policy: WidgetPolicy | None = None,
) -> Widget:
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
    """
    require(actor, "widget.create")
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
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
        policy=policy,
    )
    with as_invalid():
        widget.full_clean()
    widget.save()
    _publish(WIDGET_CREATED, tenant=tenant, widget=widget, actor=actor)
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
    return widget


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
    require(actor, "widget.approve", widget)
    signal_workflow(
        tenant=tenant,
        actor=actor,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
        signal=WIDGET_APPROVAL_SIGNAL,
    )
    # The ledger line the done-line drives, written **after** the signal landed
    # and inside the same transaction, so an approval that was refused by the
    # run leaves no line claiming it happened. It is not a second
    # authorization: `widget.approve` is strictly the stronger question
    # (`policies.can_approve` wants admin over the row's own branch), and asking
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


@service
def update_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    widget: Widget,
    name: str | None = None,
    notes: str | None = None,
    policy: WidgetPolicy | None = None,
) -> Widget:
    """Change a widget's editable fields. Nothing else writes to the table.

    Neither the tenant nor the organization is a field a caller may change:
    moving a row between tenants is a different operation with different rules,
    and moving one between branches is `move_organization`'s job or a service a
    product writes on purpose. It is not this one.

    `policy` is `None` for "leave it alone", like every other field here — which
    means this service can attach a policy and swap one, and cannot clear one.
    That asymmetry is deliberate rather than an oversight: `None` is already
    spoken for by the patch grammar, and "remove the config this row is governed
    by" is a different sentence that deserves its own verb the day a product
    needs it. The row it is given has been through `may_be_named` at the door,
    exactly as `create_widget`'s has.
    """
    require(actor, "widget.update", widget)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    updated: list[str] = []
    if name is not None:
        widget.name = name.strip()
        updated.append("name")
    if notes is not None:
        widget.notes = notes
        updated.append("notes")
    if policy is not None:
        widget.policy = policy
        updated.append("policy")
    if not updated:
        return widget
    with as_invalid():
        widget.full_clean()
    widget.save(update_fields=[*updated, "updated_at"])
    _publish(WIDGET_UPDATED, tenant=tenant, widget=widget, actor=actor)
    return widget


@service
def delete_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Remove a widget.

    It returns the row it deleted rather than `None`, so the audit entry can
    name what went — a deletion whose audit row says only "delete_widget" is
    one you will want to read in six months and cannot.

    Django clears `pk` on the instance after a delete, so it is put back: the
    object is detached and will not be saved again, and the id is the only part
    of it that still means anything.
    """
    require(actor, "widget.delete", widget)
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
    """
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
    """
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
    require(actor, "widget_entry.record", widget)
    if not may_be_named(actor, widget):
        raise NotFound()
    organization = widget.organization
    if organization_slug is not None:
        named = Organization.objects.for_tenant(tenant).filter(slug=organization_slug).first()
        if named is None:
            raise Invalid(
                {"organization": [f"No organization here is called {organization_slug!r}."]}
            )
        organization = named
    return _entry(tenant=tenant, widget=widget, kind=kind, note=note, organization=organization)
