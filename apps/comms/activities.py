"""Where delivery touches the world: principal restored, hat read, service called (ADR comms-8)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import close_old_connections
from django.utils import timezone
from temporalio import activity

from apps.comms import providers, services
from apps.comms.models import Message
from apps.comms.selectors import get_message
from apps.comms.types import DeliverMessage, DeliveryAttempt, MessageOutcome, SendStep, StepStarted
from apps.core.context import current_actor
from apps.workflows.context import workflow_context

#: The statuses a row may reach a transport in — one definition, shared with the edge wall.
SENDABLE: frozenset[str] = services.SENDABLE


def _message(message_id: str) -> Message:
    """The run's row, read through the run's tenant and hat as the system actor."""
    tenant, _user_id, org = workflow_context()
    return get_message(
        tenant=tenant, message_id=UUID(message_id), org=org, actor=current_actor(kind="system")
    )


@activity.defn(name="deliver_message", no_thread_cancel_exception=True)
def deliver_message(payload: DeliverMessage) -> DeliveryAttempt:
    """Hand the message to its transport if the wall, re-judged now, still lets it go.

    A refusal carries its lever: `permanent` ends the step, `temporal` the seconds it is held.
    """
    close_old_connections()
    try:
        message = _message(payload.message_id)
        if message.status not in SENDABLE:
            # A replay of a finished attempt, or a row already refused: report what is recorded.
            refused = message.status == Message.Status.SUPPRESSED
            return DeliveryAttempt(
                provider=message.provider,
                provider_message_id=message.provider_message_id,
                edge_refused_at=(
                    (message.suppressed_at or message.updated_at).isoformat() if refused else None
                ),
                refusal_lever=services.LEVER_PERMANENT if refused else "",
            )
        judged = services.mark_message_sending(
            tenant=message.tenant, actor=current_actor(kind="system"), message=message
        )
        current = judged.message
        if current.status == Message.Status.SUPPRESSED:
            return DeliveryAttempt(
                provider=current.provider,
                provider_message_id=current.provider_message_id,
                edge_refused_at=timezone.now().isoformat(),
                refusal_lever=services.LEVER_PERMANENT,
            )
        if current.status not in SENDABLE:
            return DeliveryAttempt(
                provider=current.provider,
                provider_message_id=current.provider_message_id,
            )
        if current.status == Message.Status.QUEUED:
            return DeliveryAttempt(
                edge_refused_at=timezone.now().isoformat(),
                refusal_lever=services.LEVER_TEMPORAL,
                defer_seconds=judged.deferred_seconds,
            )
        body = services.render(template=message.template.body, context=message.context)
        subject = message.subject or services.render(
            template=message.template.subject, context=message.context
        )
        # The nonce is the same on every attempt of this delivery and accepted by nothing here.
        sent = providers.get_channel(message.channel).send(
            message=message, subject=subject, body=body, nonce=payload.nonce
        )
        return DeliveryAttempt(
            provider=sent.provider,
            provider_message_id=sent.provider_message_id,
        )
    finally:
        close_old_connections()


@activity.defn(name="finish_message", no_thread_cancel_exception=True)
def finish_message(payload: MessageOutcome) -> str:
    """Record how the delivery ended through the service that owns the event; returns the status."""
    close_old_connections()
    try:
        message = _message(payload.message_id)
        actor = current_actor(kind="system")
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


@activity.defn(name="send_step", no_thread_cancel_exception=True)
def send_step(payload: SendStep) -> StepStarted:
    """Start one later rung of an escalation off step 1's row, and say whether it may go out.

    At-least-once: a retry between the write and the return writes a second step row.
    """
    close_old_connections()
    try:
        anchor = _message(payload.message_id)
        started = services.send_step(
            tenant=anchor.tenant,
            actor=current_actor(kind="system"),
            message=anchor,
            step=payload.step,
            channel=payload.channel,
            template=payload.template,
        )
        return StepStarted(
            message_id=str(started.message.pk),
            status=str(started.message.status),
            deferred_seconds=started.deferred_seconds,
            nonce=services.issue_delivery_nonce(started.message.pk),
        )
    finally:
        close_old_connections()


ACTIVITIES: list[Callable[..., Any]] = [deliver_message, finish_message, send_step]
