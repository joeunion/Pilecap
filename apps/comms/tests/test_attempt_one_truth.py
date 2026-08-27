"""Three small honesties found by driving comms.

Each is the same shape at a different layer: **the product knew, and did not
say.** None of them was a correctness bug — every one produced the right final
answer — and every one made the log or the row lie for a while, which is what a
person reads.

* a refusal that is already true at attempt 1 was retried five times,
  so a no-device push read `sending` for about a minute before failing with the
  reason it had at the start;
* a click posted with `url` instead of `click_url` recorded a legal
  `clicked` row with an empty link, no refusal and **no log line at all**;
* an escalation step landing in a quiet window was written
  `suppressed`, so the interpreter escalated straight past it and the person's
  own quiet hours cost them a step and moved the chain to a channel they had not
  asked for.
"""

from __future__ import annotations

import logging
from datetime import time, timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.comms import providers, services
from apps.comms.models import Channel, Message, MessageTemplate, Recipient
from apps.comms.tests.conftest import make_preference, make_template
from apps.core.actor import Actor
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

CONTEXT: dict[str, Any] = {"name": "Ada"}


# --- the attempt-1 truth ------------------------------------------------------


def test_the_delivery_retry_declares_what_cannot_become_true_by_waiting() -> None:
    """The tuple, and what is deliberately not in it.

    *Absent:* `Invalid` burns five attempts and a minute of backoff for an
    answer the first attempt already had.
    """
    from apps.comms.workflows import DELIVERY_RETRY, NON_RETRYABLE

    assert set(NON_RETRYABLE) == {"Invalid", "NotFound"}
    assert DELIVERY_RETRY.non_retryable_error_types == list(NON_RETRYABLE)
    # Still bounded for everything else — a transport that raises is exactly
    # what the backoff is for, and this must not have quietly disabled it.
    assert DELIVERY_RETRY.maximum_attempts == 5


def test_a_push_with_no_device_is_bad_input_and_says_so_at_attempt_one(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    recorded_workflow_starts: None,
) -> None:
    """The finding's own case, at the seam the retry policy reads.

    The activity raises `Invalid` — a caller-fault the wall knew before any
    gateway was reached — and `Invalid` is now non-retryable, so the run records
    the reason it had at the start instead of showing `sending` for a minute.

    Driven at the transport rather than through a worker: what the retry policy
    keys on is the exception TYPE, and this is the test that pins which type
    this path actually raises. A drive through Temporal would prove the policy
    and not the seam.
    """
    from apps.core.exceptions import Invalid

    make_template(actor=owner_actor, name="nudge", channel=Channel.PUSH)
    message = services.send(
        recipient=recipient,
        template="nudge",
        context=CONTEXT,
        channel=Channel.PUSH,
        tenant=tenant,
        actor=owner_actor,
    )

    with pytest.raises(Invalid) as raised:
        providers.get_channel(Channel.PUSH.value).send(
            message=message, subject="Your invoice", body="Due."
        )

    assert type(raised.value).__name__ in {"Invalid"}
    assert "devices" in raised.value.errors, "and the reason names what is missing"


# --- the near-miss key gets a tell -------------------------------------------


def test_a_click_posted_with_the_wrong_key_is_logged_naming_both(
    caplog: Any,
) -> None:
    """**The zero-diagnostic path dies; the permissive read survives.**

    The lead's ruling, and both halves are asserted here. The body is still
    ACCEPTED — refusing unknown keys in somebody else's webhook would break on
    the vendor's next release — and it now leaves a structured tell naming the
    key that was sent and the one this product reads.

    *Absent:* a product's integration posts `url` for a year, every click is
    recorded linkless, and nothing anywhere says why.
    """
    with caplog.at_level(logging.WARNING):
        read = providers.engagement_of(
            providers.get_channel(Channel.EMAIL.value),
            payload={
                "event_type": "clicked",
                "message_id": "a-handle",
                "url": "https://example.com/offer",
            },
        )

    # Still read, still permissive — the click is not thrown away.
    assert read is not None
    assert read.kind == "clicked"

    said = " ".join(record.getMessage() for record in caplog.records)
    assert "near_miss_key" in said
    assert "url" in said and "click_url" in said


def test_the_right_key_says_nothing(caplog: Any) -> None:
    """The control. Without it the tell above could be firing on every click."""
    with caplog.at_level(logging.WARNING):
        read = providers.engagement_of(
            providers.get_channel(Channel.EMAIL.value),
            payload={
                "event_type": "clicked",
                "message_id": "a-handle",
                "click_url": "https://example.com/offer",
            },
        )

    assert read is not None
    assert read.url == "https://example.com/offer"
    assert "near_miss_key" not in " ".join(r.getMessage() for r in caplog.records)


def test_a_body_carrying_both_keys_is_not_a_mistake(caplog: Any) -> None:
    """A sender who found the right key and kept the old one is not confused.

    Telling them anyway would be the tell crying wolf on a body that is
    completely correct, which is how a diagnostic gets filtered out of a log
    sink and stops being read at all.
    """
    with caplog.at_level(logging.WARNING):
        providers.engagement_of(
            providers.get_channel(Channel.EMAIL.value),
            payload={
                "event_type": "clicked",
                "message_id": "a-handle",
                "click_url": "https://example.com/offer",
                "url": "https://example.com/offer",
            },
        )

    assert "near_miss_key" not in " ".join(r.getMessage() for r in caplog.records)


# --- an escalation step defers ------------------------------------------------


def test_an_escalation_step_in_a_quiet_window_defers_instead_of_dying(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """**The last piece of kill-vs-delay.**

    A temporal lever delays; it does not kill — true at the transport edge since
    ADR comms-10, true at queue time since the deferred-window mechanism, and
    until this fix false
    for an escalation step. So a person's own quiet hours cost them the step AND
    moved the chain on to a channel they had not asked to be reached on, which
    is the wall being a weapon with extra steps.

    *Absent:* `status='suppressed'`, `reason='quiet_hours'`, and the interpreter
    escalating past a step that was only ever "not yet".
    """
    now = timezone.now()
    make_template(actor=owner_actor, name="chase", channel=Channel.EMAIL, category="marketing")
    make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(
            (now - timedelta(minutes=30)).time().replace(second=0, microsecond=0),
            (now + timedelta(hours=3)).time().replace(second=0, microsecond=0),
        ),
    )
    anchor = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )

    outcome = services.send_step(
        tenant=tenant,
        actor=owner_actor,
        message=anchor,
        step=2,
        channel=Channel.EMAIL,
        template="chase",
    )

    step = outcome.message
    assert step.status == Message.Status.QUEUED, "deferred, not killed"
    assert step.suppressed_reason == ""
    assert outcome.deferred_seconds > 0, "and the interpreter is told how long to wait"
    assert step.send_at is not None, "visible on the row, like every other wait"
    assert isinstance(time(0, 0), time)


def test_a_permanent_lever_still_kills_an_escalation_step(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """The fork stays a fork. Consent never given does not arrive by waiting.

    *Absent:* "quiet hours defers" quietly became "everything defers", and a
    step to somebody who opted out sits in a run instead of being refused.
    """
    make_template(actor=owner_actor, name="chase", channel=Channel.EMAIL, category="marketing")

    outcome = services.send_step(
        tenant=tenant,
        actor=owner_actor,
        message=services.send(
            recipient=recipient,
            template="receipt",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        ),
        step=2,
        channel=Channel.EMAIL,
        template="chase",
    )

    assert outcome.message.status == Message.Status.SUPPRESSED
    assert outcome.message.suppressed_reason == Message.SuppressedReason.NO_CONSENT
    assert outcome.deferred_seconds == 0


@pytest.mark.django_db(transaction=True)
def test_the_interpreter_is_handed_the_seconds(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """The activity's half: the number reaches the payload the workflow reads.

    Without this the service could defer perfectly and the interpreter would
    still escalate immediately — the two halves are a service and a
    branch, and this is the wire between them.
    """
    from apps.comms.activities import send_step as send_step_activity
    from apps.comms.types import SendStep

    now = timezone.now()
    make_template(actor=owner_actor, name="chase", channel=Channel.EMAIL, category="marketing")
    make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(
            (now - timedelta(minutes=30)).time().replace(second=0, microsecond=0),
            (now + timedelta(hours=3)).time().replace(second=0, microsecond=0),
        ),
    )
    anchor = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )

    from apps.workflows.context import reset_principal, set_principal

    tokens = set_principal(
        tenant_id=str(tenant.pk), user_id=None, org_id=str(anchor.organization_id)
    )
    try:
        started = send_step_activity(
            SendStep(
                message_id=str(anchor.pk),
                step=2,
                channel=Channel.EMAIL.value,
                template="chase",
            )
        )
    finally:
        reset_principal(tokens)

    assert started.status == Message.Status.QUEUED
    assert started.deferred_seconds > 0
