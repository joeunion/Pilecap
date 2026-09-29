"""Where the widget onboarding workflow is allowed to touch the world.

Everything the workflow may not do lives here: the ORM, the clock, the event
bus. Both activities take the same three steps, and a product's will too —
**restore the principal, read the row through the tenant's manager and the
acting hat, call a service.** Neither writes to a model itself (house rule 10),
and neither takes the tenant or the organization as an argument: both arrive on
the workflow's Temporal headers and are unpacked by the interceptor, which is
what makes it impossible for a caller to reach into somebody else's tenant — or
somebody else's branch — by putting the wrong id in a payload.

**The hat is restored, not widened.** An activity for a run started by a
sub-seller reads with that sub-seller's `visible_to` and writes an audit row
carrying it. A workflow that quietly acted for the whole tenant because nobody
threaded the org through would be the leak this whole layer exists to close,
and it would be invisible in a diff.

**Plain `def`**, like every activity in this repository: the ORM is synchronous
and the worker runs these in its thread pool, where a synchronous query belongs.
The one thing a sync activity owes that pool is `close_old_connections` at both
ends — there is no request cycle out here to do it, and a connection left open
per thread is a connection leaked forever.

Both are **idempotent**, because Temporal guarantees an activity runs at least
once: the mark keeps the first timestamp it wrote, and the announcement says the
same thing twice rather than something different.

**An archived widget is refused, once.** Both services refuse `archived` (every
write on an archived row does), and that refusal is already true at the first
attempt and is not made false by waiting — so it leaves here as a
NON-RETRYABLE failure whose type and message carry the code, the run fails at
once, and its row's `error` says `archived` instead of the run retrying an
answer it already has.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.db import close_old_connections
from temporalio import activity
from temporalio.exceptions import ApplicationError

from apps.core.actor import system_actor
from apps.core.exceptions import Archived
from apps.example import services
from apps.example.selectors import get_widget
from apps.example.types import WidgetAnnouncement, WidgetOnboarding
from apps.workflows.context import workflow_context


@contextmanager
def _refused_for_good() -> Iterator[None]:
    """An `archived` refusal leaves as a failure Temporal does not retry.

    The type is the refusal's CODE, so the workflow's history, the Temporal UI
    and the run row's `error` all name it; the message is the sentence a person
    reads. Only `archived` is here: a refusal that waiting
    can change (a conflict, a transport's error) keeps the retry policy's
    answer.
    """
    try:
        yield
    except Archived as refused:
        # The message is the sentence alone: an `ApplicationError` already says
        # its type first (`archived: …`), so the code is never written twice.
        raise ApplicationError(refused.detail, type=refused.code, non_retryable=True) from refused


@activity.defn(name="mark_widget_onboarded", no_thread_cancel_exception=True)
def mark_widget_onboarded(payload: WidgetOnboarding) -> str:
    """Mark the widget onboarded, and report when.

    The timestamp goes back to the workflow as an ISO string because that is what
    survives being written into Temporal's history and read out of it years
    later.

    A widget deleted while the workflow was waiting raises `NotFound` from the
    selector. Temporal retries, it keeps raising, and the run fails saying so —
    which is the honest outcome, rather than quietly succeeding at nothing.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        # The system actor reads too, since Phase R: `get_widget` asks
        # `widget.read` at the row's node, and nobody clicked this — a workflow
        # step has no person whose collection could answer. `allows` passes a
        # `system` actor at step 1, and the scoped manager still fences the read
        # to this tenant and this branch.
        widget = get_widget(
            tenant=tenant,
            widget_id=UUID(payload.widget_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        # The system actor: nobody clicked this. Attributing it to whoever
        # created the widget last week would make the audit trail read plausibly
        # and be false. The hat still rides on it, so the audit row says which
        # part of the network the work was done for.
        with _refused_for_good():
            marked = services.mark_widget_onboarded(
                tenant=widget.tenant,
                actor=system_actor(widget.tenant, org),
                widget=widget,
            )
        return marked.onboarded_at.isoformat() if marked.onboarded_at is not None else ""
    finally:
        close_old_connections()


@activity.defn(name="announce_widget_onboarded", no_thread_cancel_exception=True)
def announce_widget_onboarded(payload: WidgetAnnouncement) -> str:
    """Emit `example.widget.onboarded`, through the service that owns the event.

    The activity does not publish the event itself: an event is a statement a
    service makes inside the transaction of the write it describes, and an
    activity that reached for the bus directly would be a door doing a service's
    job.

    Returns the widget id it announced, so the workflow's history says which row
    this run was about without decoding the payload.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        # The system actor reads too, since Phase R: `get_widget` asks
        # `widget.read` at the row's node, and nobody clicked this — a workflow
        # step has no person whose collection could answer. `allows` passes a
        # `system` actor at step 1, and the scoped manager still fences the read
        # to this tenant and this branch.
        widget = get_widget(
            tenant=tenant,
            widget_id=UUID(payload.widget_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        with _refused_for_good():
            announced = services.announce_widget_onboarded(
                tenant=widget.tenant,
                actor=system_actor(widget.tenant, org),
                widget=widget,
                approved=payload.approved,
            )
        return str(announced.pk)
    finally:
        close_old_connections()


ACTIVITIES: list[Callable[..., Any]] = [mark_widget_onboarded, announce_widget_onboarded]
