"""The housekeeping sweep and its schedule: the far end of `InboundWebhook.lifecycle`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import close_old_connections
from temporalio import activity
from temporalio.exceptions import ApplicationError

from apps.connections import services
from apps.connections.models import InboundWebhook
from apps.connections.types import (
    PURGE_WORKFLOW,
    HandleInboundWebhook,
    PurgeInboundWebhooks,
    PurgeOutcome,
)
from apps.core.context import current_actor
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration, daily_purge
from apps.core.time import now

log = get_logger(__name__)

#: Ninety days after the hand-off closed: the retry window, then the support window, then nobody's.
INBOUND_WEBHOOK_RETENTION_DAYS = 90


@activity.defn(name="purge_inbound_webhooks", no_thread_cancel_exception=True)
def purge_inbound_webhooks(window: PurgeInboundWebhooks) -> PurgeOutcome:
    """Take the handed-off deliveries past their retention, through the service; idempotent."""
    close_old_connections()
    try:
        rows = services.purge_inbound_webhooks(
            before=now() - timedelta(days=window.retention_days), tenant=None
        )
        log.info("connections.purge.done", inbound_webhooks=rows.count)
        return PurgeOutcome(inbound_webhooks=rows.count)
    finally:
        close_old_connections()


@activity.defn(name="apply_inbound_webhook", no_thread_cancel_exception=True)
def apply_inbound_webhook(receipt: HandleInboundWebhook) -> str:
    """Hand the stored receipt to its handler through the service; a failure fails the attempt."""
    close_old_connections()
    try:
        actor = current_actor()
        if actor.tenant is None:
            raise ApplicationError("a receipt's run carries its tenant", non_retryable=True)
        received = services.apply_inbound_webhook(
            tenant=actor.tenant,
            actor=actor,
            inbound_webhook_id=UUID(receipt.inbound_webhook_id),
        )
        if received.status == InboundWebhook.Status.HANDLER_FAILED:
            raise ApplicationError(f"the {received.connection.provider} handler raised")
        return str(received.status)
    finally:
        close_old_connections()


#: `platform:connections:purge:<queue>`, daily, the retention on the argument.
PURGE_INBOUND_WEBHOOKS = daily_purge(
    app="connections",
    noun="purge",
    workflow=PURGE_WORKFLOW,
    arg=PurgeInboundWebhooks(retention_days=INBOUND_WEBHOOK_RETENTION_DAYS),
    name="connections.purge-inbound-webhooks",
    log_prefix="connections",
)


ACTIVITIES: list[Callable[..., Any]] = [purge_inbound_webhooks, apply_inbound_webhook]

SCHEDULES: list[ScheduleDeclaration] = [PURGE_INBOUND_WEBHOOKS]
