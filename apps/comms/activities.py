"""Where delivery is allowed to touch the world.

Everything the workflow may not do lives here: the ORM, the transport, the
clock. Both activities take the same three steps a product's will —
**restore the principal, read the row through the tenant's manager and the
acting hat, call a service.** Neither writes to a model itself (house rule 10),
and neither takes the tenant or the organization as an argument: both arrive on
the workflow's Temporal headers and are unpacked by the interceptor, which is
what makes it impossible for a caller to reach into somebody else's tenant — or
somebody else's branch — by putting the wrong id in a payload.

**Plain `def`**, like every activity in this repository: the ORM is synchronous
and the worker runs these in its thread pool, where a synchronous query
belongs. The one thing a sync activity owes that pool is `close_old_connections`
at both ends — there is no request cycle out here to do it.

**Idempotence**, because Temporal guarantees an activity runs at least once:
`deliver_message` returns the recorded attempt for a message already `sent`
rather than sending a second copy, and `SENDABLE` is the closed set of statuses
in which anything may reach a transport at all.

The honest limit, and it got wider with ADR comms-9 rather than narrower: a
crash between handing the message to an SMTP server and recording that we did is
at-least-once, and this app no longer helps the provider notice. It used to mint
the `Message-ID` header from the row's primary key, so a duplicate arrived
carrying the same id as the first; that header was also the key a bounce webhook
suppressed an address against, so printing it into every mail handed the
recipient a weapon against themselves. The key stopped being printed and
provider-side dedup went with it. What remains is the row: a message whose story
is over is never handed over twice, and the exposure is the one crash window,
not the retry policy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import close_old_connections
from django.utils import timezone
from temporalio import activity

from apps.comms import policies, providers, services
from apps.comms.models import Message
from apps.comms.selectors import get_message, get_preference
from apps.comms.types import DeliverMessage, DeliveryAttempt, MessageOutcome, SendStep, StepStarted
from apps.core.actor import system_actor
from apps.workflows.context import workflow_context

# The two states a message may be handed to a transport in: waiting to go, and
# already in flight (a retried activity re-sends; see the module docstring for
# what that costs since ADR comms-9). Everything else — sent, delivered, bounced,
# failed, suppressed — is a row whose story is over or was never allowed to
# start, and handing one of those to a transport is the bug this set exists to
# make impossible.
#
# **Read from `services`, not defined here** (SEC-R1b). This set and the edge
# wall's own guard are the same question asked twice — "may this row still reach
# a transport" — and while they were two hand-kept definitions they drifted:
# `sending` joined this one and the guard in `mark_message_sending` kept reading
# `queued` alone, so every retried attempt reached the transport with the
# consent wall skipped (SEC-1's H1). One definition cannot drift from itself.
SENDABLE: frozenset[str] = services.SENDABLE


@activity.defn(name="deliver_message")
def deliver_message(payload: DeliverMessage) -> DeliveryAttempt:
    """Render the message and hand it to its transport — **if the wall still says so.**

    Raising is how this says "not yet": the workflow's retry policy decides how
    many times that is worth hearing, and its deadline decides when it stops.

    A message deleted or moved out of this hat's reach while the run was
    waiting raises `NotFound` from the selector, the retries run out, and the
    run records `failed` saying so — which is the honest outcome rather than
    quietly succeeding at nothing.

    **The consent wall runs again before anything is handed over** (ADR
    comms-8). It runs inside `mark_message_sending`, not here, because this is
    an activity and an activity does not write (house rule 10) — what this does
    is read the status back and refuse to reach a transport with anything the
    service did not return as sendable. `send()` checked the wall when the row
    was written; that was minutes or hours ago, and a suppression or a consent
    revocation landing since is exactly the case this seam exists for.

    **And it runs on every attempt, not only the first** (SEC-R1b). A retry
    after a failed transport re-enters here with the row already `sending` —
    which `SENDABLE` allows on purpose — and the whole backoff is time for a
    bounce or a revocation to land. The recheck reads the same `SENDABLE` this
    guard does, so the two cannot answer differently.

    **And a refusal now comes back, with its kind** (ADR comms-10). Three
    statuses come out of the wall and they are disjoint: `sending` cleared and
    the transport is entered; `suppressed` is a permanent lever and the run must
    close promptly rather than sit out seventy-two hours waiting for a status
    nobody will send; `queued` is a temporal lever — quiet hours — and the
    result carries how many seconds are left on it so the run can wait the
    window out instead of throwing the message away. The seconds are
    computed here, not in the workflow: the arithmetic is I/O-free but reading
    the person's window is not, and rule 9 keeps both out of a module that has
    to replay.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        message = get_message(
            tenant=tenant,
            message_id=UUID(payload.message_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        if message.status not in SENDABLE:
            # Either a replay of an attempt that already succeeded, or — since
            # C2-comms-b — a row the consent wall refused. Report what is
            # recorded rather than sending the person a second copy, or a first
            # one they said they did not want. The interpreter never asks for a
            # suppressed step to be delivered; this is the second wall, in the
            # one place that actually touches the transport.
            #
            # A row that is *already* refused says so in the same words the wall
            # below uses (ADR comms-10): one refusal vocabulary, whether this
            # attempt drew the refusal or merely found it. The timestamp is the
            # row's own, because the honest answer to "when was this refused" is
            # when it was refused and not when somebody looked.
            refused = message.status == Message.Status.SUPPRESSED
            return DeliveryAttempt(
                provider=message.provider,
                provider_message_id=message.provider_message_id,
                edge_refused_at=(
                    (message.suppressed_at or message.updated_at).isoformat() if refused else None
                ),
                refusal_lever=services.LEVER_PERMANENT if refused else "",
            )
        # The system actor: nobody clicked this. Attributing an overnight retry
        # to whoever pressed "send" last week would make the audit trail read
        # plausibly and be false. The hat still rides on it.
        actor = system_actor(message.tenant, org)
        current = services.mark_message_sending(tenant=message.tenant, actor=actor, message=message)
        if current.status == Message.Status.SUPPRESSED:
            # A **permanent** lever refused since this row was last judged — at
            # queue time on a first attempt, at the previous attempt on a retry.
            # The row already says `suppressed` and the event is
            # already out; there is nothing to hand over. What is new since ADR
            # comms-10 is that the refusal is *reported*: the interpreter may
            # not read a row, so without this it could not tell a refusal from a
            # hand-over and sat out the seventy-two hour status wait before
            # closing the run.
            return DeliveryAttempt(
                provider=current.provider,
                provider_message_id=current.provider_message_id,
                edge_refused_at=timezone.now().isoformat(),
                refusal_lever=services.LEVER_PERMANENT,
            )
        if current.status not in SENDABLE:
            # Not a refusal at all: a replay of an attempt whose story is
            # already over — `sent`, `delivered`, `bounced`, `failed`. Report
            # what is recorded rather than sending a second copy.
            return DeliveryAttempt(
                provider=current.provider,
                provider_message_id=current.provider_message_id,
            )
        if current.status == Message.Status.QUEUED:
            # A **temporal** lever refused: the wall said "not yet" and wrote
            # the row back to `queued` rather than killing it (ADR comms-10).
            # Only quiet hours can leave a judged row queued, and the duration
            # is computed here because the timezone arithmetic is I/O-free but
            # the preference read is not — the workflow gets a number of seconds
            # and never touches either.
            at = timezone.now()
            preference = get_preference(
                tenant=message.tenant,
                recipient=current.recipient,
                channel=current.channel,
                org=current.organization,
                actor=system_actor(message.tenant, current.organization),
            )
            # `None` cannot happen behind a quiet-hours refusal — the wall read
            # the row to make it — and it is handled rather than asserted
            # because a zero-length deferral is already a legal answer here: the
            # run wakes at once and re-judges, which is the honest behaviour if
            # the preference vanished between the two reads.
            #
            # **The longer of the two windows** (`quiet_defer_seconds`):
            # a tenant's window, if a product's seam resolved one, refuses
            # independently of the person's, and waking on the shorter would
            # spend the run's one deferral on a second refusal.
            return DeliveryAttempt(
                edge_refused_at=at.isoformat(),
                refusal_lever=services.LEVER_TEMPORAL,
                defer_seconds=policies.quiet_defer_seconds(
                    preference=preference, tenant=message.tenant, at=at
                ),
            )
        body = services.render(template=message.template.body, context=message.context)
        subject = message.subject or services.render(
            template=message.template.subject, context=message.context
        )
        # **The nonce, handed to the transport.** It came in on the
        # workflow's payload and is the same string on every attempt of this
        # delivery, so a provider that honours a message identifier can tell a
        # retry from a second send. It is NOT `provider_message_id` and is
        # accepted by nothing here — which is what makes it safe to put on the
        # wire at all, and what `tests/test_nonce.py` drives.
        sent = providers.get_channel(message.channel).send(
            message=message, subject=subject, body=body, nonce=payload.nonce
        )
        return DeliveryAttempt(
            provider=sent.provider,
            provider_message_id=sent.provider_message_id,
        )
    finally:
        close_old_connections()


@activity.defn(name="finish_message")
def finish_message(payload: MessageOutcome) -> str:
    """Record how the delivery ended, through the service that owns the event.

    The activity does not emit anything itself: an event is a statement a
    service makes inside the transaction of the write it describes, and an
    activity reaching for the bus directly would be a door doing a service's
    job.

    Returns the status it recorded, so the run's history says how this message
    ended without decoding the payload.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        message = get_message(
            tenant=tenant,
            message_id=UUID(payload.message_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        actor = system_actor(message.tenant, org)
        if payload.status == Message.Status.SENT:
            recorded = services.record_message_sent(
                tenant=message.tenant,
                actor=actor,
                message=message,
                provider=payload.provider,
                provider_message_id=payload.provider_message_id,
            )
        else:
            recorded = services.record_message_failed(
                tenant=message.tenant,
                actor=actor,
                message=message,
                error=payload.error,
            )
        return str(recorded.status)
    finally:
        close_old_connections()


@activity.defn(name="send_step")
def send_step(payload: SendStep) -> StepStarted:
    """Start one later rung of an escalation, and say whether it may go out.

    The workflow carries an anchor id and a step number; **everything about who
    this is for is read here**, from step 1's row — the recipient, the acting
    organization, the context, the policy's name and version, the correlation
    chain. A workflow payload is history and history is forever, so the
    customer's own data does not travel through it.

    The service behind this runs the full consent wall at *this* moment (ADR
    comms-7), which is why the answer this returns is a status and not just an
    id: a suppressed step has nothing in flight, so the interpreter escalates
    past it without waiting rather than holding the run open for a delivery that
    was never attempted.

    Idempotence is the honest limit here and it is worth stating plainly: a
    retry after the row was written but before this returned writes a **second**
    step row. Temporal retries this activity only when it fails or the worker
    dies mid-call, both rare; the cost is a duplicate message rather than a lost
    one, and the alternative — a natural key on (run, step) — is a constraint
    C2-comms-b did not buy. Named, not hidden.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        anchor = get_message(
            tenant=tenant,
            message_id=UUID(payload.message_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        started = services.send_step(
            tenant=anchor.tenant,
            actor=system_actor(anchor.tenant, org),
            message=anchor,
            step=payload.step,
            channel=payload.channel,
            template=payload.template,
        )
        return StepStarted(
            message_id=str(started.message.pk),
            status=str(started.message.status),
            # How long the quiet-hours wall held this step, from the
            # service that judged it. Zero unless it was deferred.
            deferred_seconds=started.deferred_seconds,
            # Its own row, its own nonce — the interpreter carries it into that
            # step's delivery exactly as `send()` handed it step one's.
            nonce=services.issue_delivery_nonce(started.message.pk),
        )
    finally:
        close_old_connections()


ACTIVITIES: list[Callable[..., Any]] = [deliver_message, finish_message, send_step]
