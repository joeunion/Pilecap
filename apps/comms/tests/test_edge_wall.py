"""The wall at the transport edge, and the census that keeps it the only path.

P2-R1's finding 2: the consent wall ran at `send()` time while the transport
ran later, so a suppression or a consent revocation landing **between queue and
delivery** was ignored at the one moment that decides whether a human is
mailed. `send_step` had honoured that seam since ADR comms-7 — the authors knew
the class — and the plain path did not.

ADR comms-8 (3) closes it in the service the delivery activity already calls
first: `mark_message_sending` re-runs the wall against *current* state, and a
row it refuses becomes `suppressed` with the declared event, before
`deliver_message` has anything to hand to a provider.

Two kinds of test live here, and the second is the one that has to keep being
true:

* **the seam**, driven through the real activity with a real transport, so the
  evidence is "nothing went out" and not "a function returned early";
* **the census** (R2-7), which enumerates every call path to a provider's
  `.send()` in this app and asserts the set is exactly the transport
  chokepoints, each carrying the wall recheck. Its declared limit, borrowed
  honestly from house rule 28's own: it sees **references, not execution
  paths**.

The activity is called directly rather than through a Temporal server: what is
being measured is a decision the activity makes before it touches a transport,
and `test_workflows.py` already proves the run assembly around it. The
principal the interceptor would have unpacked is set by hand, which is what
`acting_as` below is for.

`transaction=True` throughout, and it is forced rather than chosen: an activity
begins with `close_old_connections()`, which closes a connection whose
autocommit state disagrees with its settings — precisely the state pytest's
ordinary `django_db` wrapper leaves it in. A test that called the activity
inside that wrapper would fail on a closed connection before it reached an
assertion, which is measuring the harness rather than the product. The price is
a real commit, so the house's `recorded_workflow_starts` opt-in is declared
autouse below.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from django.core import mail

from apps.comms import providers, services
from apps.comms.activities import deliver_message
from apps.comms.models import Category, Channel, Message, MessageTemplate, Recipient
from apps.comms.providers import Sent
from apps.comms.tests.conftest import make_preference, make_template
from apps.comms.types import DeliverMessage
from apps.core.actor import Actor
from apps.core.models import Organization, Tenant
from apps.core.tests.tree_census import source_text
from apps.events.models import Event
from apps.workflows.context import reset_principal, set_principal

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _starts_are_recorded_not_dialled(recorded_workflow_starts: None) -> None:
    """The house opt-in, for a `transaction=True` module whose subject is not the run.

    `send()` writes its `WorkflowRun` row inside the caller's transaction and
    defers the client call to that transaction's commit; these tests commit for
    real, so the hook fires. `recorded_workflow_starts` (`apps/conftest.py`) is
    the sanctioned way to let everything above the dial happen and skip the dial
    — declared autouse here because every test in this module sends.

    The other choice is the one a test whose subject *is* the run makes: start a
    time-skipping environment and point the factory at it, which is what
    `test_workflows.py` and `test_escalation.py` do.
    """


# --- driving the activity the way the worker would --------------------------------


@contextmanager
def acting_as(tenant: Tenant, org: Organization) -> Iterator[None]:
    """The principal an inbound interceptor would have unpacked from the headers.

    Set by hand because there is no worker here. It is the same three values
    `workflow_context()` reads and nothing else: an activity that could take the
    tenant as an argument would be an activity a caller could point at somebody
    else's data.
    """
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=None, org_id=str(org.pk))
    try:
        yield
    finally:
        reset_principal(tokens)


@dataclass
class CountingChannel:
    """A transport that counts instead of sending. **The tripwire.**

    `mail.outbox` proves no *email* left; this proves the provider's `send` was
    never **entered**, which is the stronger half of R2-4 and the half a future
    refactor could quietly break while leaving the outbox empty.
    """

    slug: str = Channel.EMAIL.value
    calls: list[str] = field(default_factory=list)

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        self.calls.append(str(message.pk))
        return Sent(provider="counting", provider_message_id=f"<{message.pk}@counted>")

    def normalize_status(self, *, payload: dict[str, Any]) -> Any:
        return None


@pytest.fixture
def counting() -> Iterator[CountingChannel]:
    """The counting transport in the `email` slot, and the real one back after."""
    spy = CountingChannel()
    providers.register_channel(spy)
    try:
        yield spy
    finally:
        providers.register_channel(providers.EmailChannel())


@dataclass
class FlakyChannel(CountingChannel):
    """A transport that drops its first attempt, the way a real one does.

    This is the state SEC-1's H1 needs and no other fixture here can reach: a
    row left `sending` because the transport was **entered and failed**, which
    is what a Temporal retry re-enters minutes or hours later. Raising is the
    honest simulation — `deliver_message` lets it out, the workflow's retry
    policy counts it, and the row stays mid-flight with `sent_at` unset.

    `calls` still records every *entry* into `send`, before the failure, because
    the tripwire's question is "was a transport reached", not "did it succeed".
    """

    failures: int = 1

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        self.calls.append(str(message.pk))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("the transport hung up before it accepted this")
        return Sent(provider="counting", provider_message_id=f"<{message.pk}@counted>")


@pytest.fixture
def flaky() -> Iterator[FlakyChannel]:
    """The flaky transport in the `email` slot, and the real one back after."""
    spy = FlakyChannel()
    providers.register_channel(spy)
    try:
        yield spy
    finally:
        providers.register_channel(providers.EmailChannel())


def reread(tenant: Tenant, message: Message) -> Message:
    return Message.objects.for_tenant(tenant).get(pk=message.pk)


def suppressed_events(tenant: Tenant) -> list[Event]:
    return list(
        Event.objects.for_tenant(tenant)
        .filter(name="comms.message.suppressed")
        .order_by("created_at")
    )


def queue_one(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, template: str = "receipt"
) -> Message:
    """One message, accepted by the wall at send time. The state the seam needs."""
    message = services.send(
        recipient=recipient,
        template=template,
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=actor,
    )
    assert message.status == Message.Status.QUEUED, "the wall said yes when the send was made"
    return message


# --- R2-1(b), R2-4: the wall at the edge ------------------------------------------


def test_a_suppression_between_queue_and_delivery_stops_the_send(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """**The reviewer's probe, and the shape it was red in.**

    Queued while the address was mailable; suppressed while the run was on its
    way to the transport. Before this fix the activity read only the message's
    own status — still `queued` — and mailed them anyway, which is the one
    moment the whole consent wall exists for.

    Absent: the wall runs at queue time and the moment that
    decides whether a human gets mailed is unguarded.
    """
    mail.outbox.clear()
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)

    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        attempt = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert mail.outbox == [], "the person asked to be left alone before this went out"
    row = reread(tenant, message)
    assert row.status == Message.Status.SUPPRESSED
    assert row.suppressed_reason == Message.SuppressedReason.SUPPRESSED
    assert row.suppressed_at is not None
    assert row.sent_at is None
    assert (attempt.provider, attempt.provider_message_id) == ("", "")

    published = suppressed_events(tenant)
    assert [str(event.payload["id"]) for event in published] == [str(message.pk)]
    assert published[0].payload["status"] == "suppressed"


def test_a_revocation_between_queue_and_delivery_stops_a_marketing_send(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """R2-4's second case. The other lever, and it has to be the other lever.

    Suppression refuses everything; a marketing revocation refuses only what
    needs consent. Proving the edge recheck with suppression alone would leave
    "does it run the *whole* wall, or just the strongest clause" unanswered — so
    this one queues a marketing message with live consent and takes the consent
    back before delivery.
    """
    mail.outbox.clear()
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    message = queue_one(
        tenant=tenant, actor=owner_actor, recipient=recipient, template="newsletter"
    )

    services.revoke_consent(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert mail.outbox == [], "they took marketing consent back before this went out"
    row = reread(tenant, message)
    assert row.status == Message.Status.SUPPRESSED
    assert row.suppressed_reason == Message.SuppressedReason.NO_CONSENT


def test_the_provider_is_never_entered_when_the_wall_refuses(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    counting: CountingChannel,
) -> None:
    """R2-4's tripwire: **ZERO** send calls, counted at the transport itself.

    An empty outbox is evidence that nothing was delivered. This is evidence
    that nothing was *attempted* — the provider object's `send` was never
    entered — which is the property that survives a transport that fails
    silently or a refactor that moves the guard downstream.
    """
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert counting.calls == [], "the wall refused and the transport was still reached"
    assert reread(tenant, message).status == Message.Status.SUPPRESSED


def test_the_wall_that_says_yes_still_delivers(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    counting: CountingChannel,
) -> None:
    """The negative the three above would pass without: a recheck that refuses
    everything is not a wall, it is an outage.

    Nothing changes between queue and delivery, so the transport is reached
    exactly once and the row moves the way it always did.
    """
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)

    with acting_as(tenant, root_org):
        attempt = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert counting.calls == [str(message.pk)]
    assert attempt.provider == "counting"
    assert reread(tenant, message).status == Message.Status.SENDING
    assert suppressed_events(tenant) == []


def test_a_second_delivery_attempt_on_a_refused_row_stays_refused(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    counting: CountingChannel,
) -> None:
    """Temporal runs an activity at least once, so the refusal has to be idempotent.

    A replay must not emit `comms.message.suppressed` twice, and must not walk
    the refusal back into a delivery on the second pass.
    """
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        deliver_message(DeliverMessage(message_id=str(message.pk)))
        deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert counting.calls == []
    assert len(suppressed_events(tenant)) == 1, "one refusal, one announcement"
    assert reread(tenant, message).status == Message.Status.SUPPRESSED


def test_the_bookkeeping_cannot_walk_a_refused_row_back_into_a_send(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """The other half of the edge refusal, and it is not optional.

    `finish_message` records the outcome the workflow computed, and the workflow
    cannot see that the edge refused — it may not read a row (house rule 9), and
    `DeliveryAttempt` carries no status. So the terminal write is what has to
    know: `suppressed` is a status the delivery's own bookkeeping must not walk
    back over, exactly as `delivered` and `bounced` are.

    Absent: the row says `sent` a heartbeat after the wall refused it, and
    `comms.message.sent` announces a message nobody was sent.
    """
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )
    refused = services.mark_message_sending(tenant=tenant, actor=owner_actor, message=message)
    assert refused.status == Message.Status.SUPPRESSED

    services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=refused,
        provider="counting",
        provider_message_id="<x@counted>",
    )
    services.record_message_failed(
        tenant=tenant, actor=owner_actor, message=refused, error="too late"
    )

    row = reread(tenant, message)
    assert row.status == Message.Status.SUPPRESSED
    assert row.sent_at is None
    assert row.failed_at is None
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.sent").count() == 0, (
        "nothing was sent, so nothing may say it was"
    )


# --- SEC-R1b: the wall runs on every attempt, not only the first ------------------
#
# SEC-1's HIGH finding H1. `SENDABLE` deliberately holds two statuses — `queued`
# and `sending` — because a retry after a transport failure re-sends a row that
# is already `sending`. But
# the edge wall's own guard read one status, `queued`, so the recheck ADR
# comms-8 put at the transport ran on the **first** attempt and was skipped on
# every one after it. The attack window is the whole retry backoff: the address
# hard-bounces, or the person revokes consent, while attempt 1 is failing, and
# attempt 2 delivers anyway.
#
# The two sets are now one set, defined once in `services.py` and read by the
# activity, because two hand-kept copies of "which statuses may reach a
# transport" drifting apart is exactly how this happened.


def test_a_retried_attempt_consults_the_wall_before_it_re_sends(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    flaky: FlakyChannel,
) -> None:
    """SEC-1 H1, red first. **The retry is an attempt, and an attempt is walled.**

    Attempt 1 reaches the transport and the transport fails, so the row is left
    `sending`. The recipient is suppressed while the run backs off. Attempt 2
    must find the wall standing.

    Absent: `mark_message_sending` returns a `sending` row untouched before it
    reaches `_refusal`, the activity reads back a status still in `SENDABLE`,
    and the second attempt mails somebody who asked to be left alone — with the
    row and the event log both saying it was fine.
    """
    mail.outbox.clear()
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)

    with acting_as(tenant, root_org), pytest.raises(RuntimeError):
        deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert flaky.calls == [str(message.pk)], "attempt 1 never reached the transport"
    assert reread(tenant, message).status == Message.Status.SENDING, (
        "the row has to be mid-flight, or this test is not about a retry"
    )

    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        attempt = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert flaky.calls == [str(message.pk)], (
        "the retry entered the transport after the address was suppressed"
    )
    assert mail.outbox == []
    row = reread(tenant, message)
    assert row.status == Message.Status.SUPPRESSED
    assert row.suppressed_reason == Message.SuppressedReason.SUPPRESSED
    assert row.suppressed_at is not None
    assert row.sent_at is None
    assert (attempt.provider, attempt.provider_message_id) == ("", "")

    published = suppressed_events(tenant)
    assert [str(event.payload["id"]) for event in published] == [str(message.pk)]
    assert published[0].payload["status"] == "suppressed"


def test_a_retried_attempt_with_a_clean_recipient_still_re_sends(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    flaky: FlakyChannel,
) -> None:
    """The negative the one above would pass without. **Retry semantics intact.**

    A wall that refused every `sending` row would not be a widened wall, it
    would be a delivery system with one attempt — and Temporal's retry, the
    whole reason `sending` is in `SENDABLE`, would be dead code. Nothing changes
    between the failed attempt and the retry, so the transport is entered a
    second time and the row stays mid-flight.
    """
    message = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)

    with acting_as(tenant, root_org), pytest.raises(RuntimeError):
        deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert reread(tenant, message).status == Message.Status.SENDING

    with acting_as(tenant, root_org):
        attempt = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert flaky.calls == [str(message.pk), str(message.pk)], "the retry never re-sent"
    assert attempt.provider == "counting"
    assert attempt.provider_message_id == f"<{message.pk}@counted>", (
        "the retry minted a new id instead of the one derived from the row"
    )
    assert reread(tenant, message).status == Message.Status.SENDING
    assert suppressed_events(tenant) == []


def test_the_widened_wall_still_leaves_a_settled_row_alone(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """The wall widens; the idempotence narrows nothing.

    Two statuses joined `queued` at the recheck — and only one. A row that has
    been handed over, or has spent its attempts, is a row whose story is over:
    re-walling it would let a suppression arriving afterwards rewrite `sent`
    into `suppressed`, which is the log lying in the other direction.
    """
    handed_over = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.mark_message_sending(tenant=tenant, actor=owner_actor, message=handed_over)
    services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=handed_over,
        provider="counting",
        provider_message_id="<a@counted>",
    )

    spent = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.mark_message_sending(tenant=tenant, actor=owner_actor, message=spent)
    services.record_message_failed(
        tenant=tenant, actor=owner_actor, message=spent, error="the attempts are spent"
    )

    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    after_sent = services.mark_message_sending(
        tenant=tenant, actor=owner_actor, message=reread(tenant, handed_over)
    )
    after_failed = services.mark_message_sending(
        tenant=tenant, actor=owner_actor, message=reread(tenant, spent)
    )

    assert after_sent.status == Message.Status.SENT
    assert after_failed.status == Message.Status.FAILED
    assert reread(tenant, handed_over).sent_at is not None
    assert suppressed_events(tenant) == [], "a settled row was re-walked and announced"


# --- R2-5: the two walls agree ----------------------------------------------------


def test_the_edge_recheck_and_the_step_recheck_speak_one_vocabulary(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """R2-5, ADR comms-8 against ADR comms-7. **One refusal dialect, not two.**

    `send_step`'s recheck has refused a later escalation rung since comms-7; the
    edge recheck refuses a queued message at the transport. Given the same lever
    — the address suppressed — both must produce the same `(status, reason)`
    pair, from the same two closed sets. A second word for one refusal is the
    drift this asserts against, one layer below the door parity E9 measures.

    The comms-7 tests themselves are untouched here and stay green in
    `test_escalation.py`; this is the *agreement*, which no single-wall test can
    state.
    """
    anchor = queue_one(tenant=tenant, actor=owner_actor, recipient=recipient)
    make_template(actor=owner_actor, name="chaser", category=Category.TRANSACTIONAL)
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    at_the_edge = services.mark_message_sending(tenant=tenant, actor=owner_actor, message=anchor)
    at_the_step = services.send_step(
        tenant=tenant,
        actor=owner_actor,
        message=anchor,
        step=2,
        channel=Channel.EMAIL,
        template="chaser",
    )

    # `send_step` returns a `StepOutcome`: the row, plus how
    # long the quiet-hours wall held it. The property here is about the row.
    at_the_step_row = at_the_step.message
    assert (at_the_edge.status, at_the_edge.suppressed_reason) == (
        at_the_step_row.status,
        at_the_step_row.suppressed_reason,
    )
    assert at_the_edge.status == Message.Status.SUPPRESSED
    assert at_the_edge.suppressed_reason == Message.SuppressedReason.SUPPRESSED


# --- R2-7: the class is closed ----------------------------------------------------
#
# Every path from this app to a transport, enumerated from the source. The
# invariant is one sentence — **every path to a provider's `.send()` re-runs the
# wall on current state** — and it holds today by inspection, which is precisely
# the kind of truth the fifteenth builder's first shortcut reopens. Promotion to
# a house rule is a queue candidate; its trigger is a second app growing a
# transport of its own, at which point a per-app census stops being enough.


#: What makes an expression a *provider*, as opposed to any other object with a
#: `send` method. Two clauses, because there are two ways to get one: through
#: the registry (the legal way) and by building a channel class directly (the
#: bypass a future builder reaches for when the registry is inconvenient).
REGISTRY_MARKERS: tuple[str, ...] = ("get_channel", "registered_channels")
CHANNEL_CLASS_MARKER = "Channel"

#: The declared chokepoints: file, and the function the call sits in. Exactly
#: one today. Growing this set is a visible diff and the whole mechanism.
CHOKEPOINTS: set[tuple[str, str]] = {("activities.py", "deliver_message")}

#: What a chokepoint has to contain to count as walled. The service named here
#: is the one that re-runs `_refusal` against current state before anything is
#: handed over; a chokepoint that does not call it is a chokepoint with no wall.
WALL_REFERENCE = "mark_message_sending"


@dataclass(frozen=True)
class TransportCall:
    """One place in this app's source that hands something to a transport."""

    module: str
    function: str
    line: int
    receiver: str
    enclosing_source: str


def _enclosing(tree: ast.AST, source: str, line: int) -> tuple[str, str]:
    """The innermost function containing `line`, by name and by source.

    A module-level call answers `"<module>"` and the whole file, which is the
    honest answer and also the loudest possible census entry: a transport call
    at import time belongs to no function and therefore to no wall.
    """
    best: tuple[int, str, str] = (-1, "<module>", source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= line <= end and node.lineno > best[0]:
            best = (node.lineno, node.name, ast.get_source_segment(source, node) or "")
    return best[1], best[2]


def transport_calls(source: str, module: str) -> list[TransportCall]:
    """Every `<provider>.send(...)` in one module, with the function it sits in.

    Source-order over the AST rather than a grep, so a call spread over four
    lines is one finding and a `send` in a docstring is none.

    **Declared limit** (house rule 28's own, borrowed honestly): this sees
    *references*, not execution paths. A provider reached through an alias
    assigned in another function, handed in as an argument, or pulled out of a
    dictionary is invisible to it — which is why the assertion is `==` against a
    declared set rather than a search for known-bad shapes: a new path has to be
    written into `CHOKEPOINTS` by a human, and the diff is the review.
    """
    tree = ast.parse(source)
    found: list[TransportCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "send":
            continue
        receiver = ast.get_source_segment(source, func.value) or ""
        registry = any(marker in receiver for marker in REGISTRY_MARKERS)
        if not registry and CHANNEL_CLASS_MARKER not in receiver:
            continue
        name, body = _enclosing(tree, source, node.lineno)
        found.append(
            TransportCall(
                module=module,
                function=name,
                line=node.lineno,
                receiver=receiver,
                enclosing_source=body,
            )
        )
    return sorted(found, key=lambda call: call.line)


def census() -> list[TransportCall]:
    """The whole app's transport calls. Production modules only — tests drive
    providers on purpose and are not paths the product can take."""
    root = Path(services.__file__).parent
    found: list[TransportCall] = []
    for path in sorted(root.glob("*.py")):
        found.extend(transport_calls(source_text(path), path.name))
    return found


def test_every_path_to_a_provider_is_a_declared_chokepoint_that_runs_the_wall() -> None:
    """R2-7. The set is exactly the chokepoints, and every one of them is walled.

    Absent: the invariant holds today by inspection and is reopened silently by
    the next builder who needs to send something from somewhere new.
    """
    found = census()
    assert found, "the census found no transport at all — it has stopped measuring"
    assert {(call.module, call.function) for call in found} == CHOKEPOINTS

    for call in found:
        assert WALL_REFERENCE in call.enclosing_source, (
            f"{call.module}:{call.line} reaches a transport without the wall recheck"
        )


def test_the_census_catches_a_planted_bypass() -> None:
    """The canary. A census that cannot fail is a comment with a test's name.

    Two plants, because they are the two shapes a bypass actually takes: a new
    helper that reaches the registry, and a call at import time that belongs to
    no function at all. Neither carries the wall reference, and neither is in
    the declared set.
    """
    planted = """
from apps.comms import providers


def blast(message, subject, body):
    return providers.get_channel(message.channel).send(
        message=message, subject=subject, body=body
    )
"""
    found = transport_calls(planted, "planted.py")
    assert [(call.module, call.function) for call in found] == [("planted.py", "blast")]
    assert {(call.module, call.function) for call in found} != CHOKEPOINTS
    assert WALL_REFERENCE not in found[0].enclosing_source

    at_import = """
from apps.comms.providers import EmailChannel

EmailChannel().send(message=None, subject="", body="")
"""
    module_level = transport_calls(at_import, "planted.py")
    assert [call.function for call in module_level] == ["<module>"]


def test_the_census_does_not_flag_what_is_not_a_transport() -> None:
    """And it stays silent on the ordinary `send` that is not a provider's.

    Without this the census would pass by flagging everything, which is the
    other way an enumeration stops meaning anything.
    """
    ordinary = """
def notify(mail, channel_name):
    mail.send()
    return channel_name
"""
    assert transport_calls(ordinary, "ordinary.py") == []
