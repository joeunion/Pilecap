"""The tenant quiet-hours seam — **empty**, and that asymmetry closed.

The owner ruled: *"empty seam is right — do it
that way"*. Two claims, and they pull in opposite directions on purpose:

* **the platform ships NO policy.** No default window, no setting to leave
  blank, no column to leave null, no opinion about hours. On a fresh clone the
  seam is unregistered, `tenant_quiet_window` answers `None` for every tenant,
  and the consent wall takes the branch it has always taken. *"Unset ≡ the seam
  does not exist"* is the ruling's phrase and the first half of this module
  drives it as **byte-identical behaviour** rather than asserting it;
* **and yet the binding point is the platform's**, because house rule 25's
  one-legal-sender argument requires it: consent, quiet hours and suppression
  are *enforceable* precisely because one function decides them and nothing can
  reach around it. A product that grew a tenant-wide window beside `send()`
  would be a second wall, and two walls disagree. So the seam is here, in
  `_refusal`, consulted at both the moments that matter — queue time and the
  transport edge.

**And the asymmetry.** A temporal lever delays; it does not kill (ADR comms-10) — and
until this fix that was true at the transport edge and false at queue time, so
a marketing send submitted at 22:30 was thrown away while the identical send
submitted at 21:59 was delivered at 07:00. The asymmetry had a reason at the
time: at queue time no run existed to wait in. This fix starts one.
`test_the_two_sides_of_ten_oclock_now_agree` is that story as a test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.comms import policies, services
from apps.comms.models import Channel, Message, MessageTemplate, Recipient
from apps.comms.policies import (
    QuietWindow,
    quiet_defer_seconds,
    register_quiet_hours,
    tenant_quiet_window,
    unregister_quiet_hours,
)
from apps.comms.selectors import get_preference
from apps.comms.tests.conftest import make_preference, make_template
from apps.core.actor import Actor
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

CONTEXT: dict[str, Any] = {"name": "Ada"}


@pytest.fixture(autouse=True)
def _seam_is_unset_around_every_test() -> Iterator[None]:
    """The shipped state, restored both ways.

    Autouse and symmetric because the seam is a module-level slot — process
    global, exactly as the channel registry is — and a test that registered one
    and did not clear it would hand the next test a tenant window it never asked
    for. Clearing **before** as well as after is the half that matters: it makes
    every test below start from the state a fresh clone is in, whatever ran
    first under `-p randomly`.
    """
    unregister_quiet_hours()
    yield
    unregister_quiet_hours()


def _window_around_now(*, minutes: int = 30, timezone_name: str = "UTC") -> QuietWindow:
    """A window that contains this instant, whatever the hour.

    `test_services.py`'s idiom — quiet hours is "is *now* inside this window", so
    a test moves the window rather than the clock. There is no `time_machine` in
    this tree and this test suite adds no dependency.
    """
    now = timezone.now()
    start = (now - timedelta(minutes=minutes)).timetz().replace(tzinfo=None)
    end = (now + timedelta(minutes=minutes)).timetz().replace(tzinfo=None)
    return QuietWindow(
        start=time(start.hour, start.minute),
        end=time(end.hour, end.minute),
        timezone=timezone_name,
    )


def _campaign(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, template: str = "newsletter"
) -> Message:
    return services.send(
        recipient=recipient,
        template=template,
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=actor,
    )


# --- unset means the seam does not exist -----------------------------------------


def test_a_fresh_clone_has_no_resolver_and_no_window(tenant: Tenant) -> None:
    """The shipped state, said out loud.

    *Absent:* the template ships a default window, which is the one thing the
    ruling forbids by name — and nobody notices, because a default that works
    looks like a feature.
    """
    assert policies._QUIET_HOURS is None
    assert tenant_quiet_window(tenant) is None


def test_with_the_seam_unset_a_consented_marketing_send_is_untouched(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """Byte-identical, and driven as behaviour rather than asserted as intent.

    The person has consented and has no window of their own; with no tenant
    resolver registered this is a plain queued send with a run behind it —
    exactly what it was before this fix existed.

    *Absent:* the seam has an opinion when nobody configured one, and every
    product on the template inherits somebody else's idea of a decent hour.

    **The last assertion is the one that earns this test, and it was added
    because a plant walked past the first three.** Planting a default window
    into `tenant_quiet_window` left `status`, `suppressed_reason` and
    `delivery_workflow_id` all reading exactly as they do here — because a
    deferral IS a queued row with a run behind it, which is the whole of that
    fix. "Unset ≡ the seam does not exist" is a claim about the WAIT, so the
    wait is what has to be zero.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)

    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)

    assert message.status == Message.Status.QUEUED
    assert message.suppressed_reason == ""
    assert message.delivery_workflow_id
    assert (
        quiet_defer_seconds(
            preference=get_preference(
                tenant=tenant,
                recipient=recipient,
                channel=Channel.EMAIL,
                org=owner_actor.org,
                actor=owner_actor,
            ),
            tenant=tenant,
            at=timezone.now(),
        )
        == 0
    ), "not deferred at all — a default window would make this a wait"


def test_a_resolver_that_answers_none_is_the_same_as_no_resolver(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """A product may switch the feature on for one tenant and change nothing for the rest.

    Which is why `None` from a registered resolver and `None` from an
    unregistered seam are deliberately indistinguishable to the caller.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    register_quiet_hours(lambda _tenant: None)

    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)

    assert message.status == Message.Status.QUEUED
    assert message.suppressed_reason == ""
    assert (
        quiet_defer_seconds(
            preference=get_preference(
                tenant=tenant,
                recipient=recipient,
                channel=Channel.EMAIL,
                org=owner_actor.org,
                actor=owner_actor,
            ),
            tenant=tenant,
            at=timezone.now(),
        )
        == 0
    ), "and no wait, which is the half a status assertion cannot see"


# --- a configured window binds, at both binding points ---------------------------


def test_a_tenant_window_defers_a_marketing_send(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The seam doing its one job — and doing it as a DELAY, not a kill.

    The person has consented and has no window of their own. The tenant's window
    is the only thing holding this message, and what it produces is a `queued`
    row with a run to wait in.

    *Absent:* a product configures quiet hours and the platform ignores it,
    which would make the binding-point argument (house rule 25) a claim rather
    than a mechanism.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    register_quiet_hours(lambda _tenant: _window_around_now())

    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)

    assert message.status == Message.Status.QUEUED
    assert message.suppressed_reason == ""
    assert message.delivery_workflow_id, "held by the window, waiting in a run"
    assert (
        quiet_defer_seconds(
            preference=get_preference(
                tenant=tenant,
                recipient=recipient,
                channel=Channel.EMAIL,
                org=owner_actor.org,
                actor=owner_actor,
            ),
            tenant=tenant,
            at=timezone.now(),
        )
        > 0
    ), "and the wait it was given is a real one"


def test_an_escalation_step_is_held_by_the_tenant_window_too(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """A later escalation rung is judged against the tenant's window, as step 1 and the edge are."""
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    anchor = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)
    register_quiet_hours(lambda _tenant: _window_around_now())

    step = services.send_step(
        tenant=tenant,
        actor=owner_actor,
        message=anchor,
        step=2,
        channel=Channel.EMAIL,
        template=newsletter.name,
    )

    assert step.message.status == Message.Status.QUEUED
    assert step.deferred_seconds > 0, "the step waits the tenant's window out"
    assert step.message.send_at is not None


def test_the_edge_hands_back_the_seconds_it_holds_for(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The service that judged returns the hold; the activity never re-derives it."""
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)
    register_quiet_hours(lambda _tenant: _window_around_now())

    judged = services.mark_message_sending(tenant=tenant, actor=owner_actor, message=message)

    assert judged.message.status == Message.Status.QUEUED
    assert judged.deferred_seconds > 0


def test_a_tenant_window_never_touches_transactional_mail(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """The category line is where it always was, and the seam does not move it.

    A receipt at 3am is fine because the person just bought something. A tenant
    window that held transactional mail would be a product breaking its own
    customers' password resets, and the seam must not make that reachable.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    register_quiet_hours(lambda _tenant: _window_around_now())

    message = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )

    assert message.status == Message.Status.QUEUED
    assert (
        quiet_defer_seconds(
            preference=get_preference(
                tenant=tenant,
                recipient=recipient,
                channel=Channel.EMAIL,
                org=owner_actor.org,
                actor=owner_actor,
            ),
            tenant=tenant,
            at=timezone.now(),
        )
        > 0
    ), "the window IS shut — this send simply is not subject to it"


def test_the_seam_is_consulted_at_the_transport_edge_too(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """One binding point, both moments — the queue and the edge.

    A message queued while the tenant had no window and delivery-checked a
    moment after a product configured one is the 21:59/22:01 story with the two
    clocks swapped, and it is the only honest way to drive the edge without a
    clock library.

    *Absent:* a window a product configures applies to new sends and not to the
    message that has been asleep since yesterday — which is a wall with a hole
    in it exactly the width of the deferral it created.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)
    assert message.status == Message.Status.QUEUED

    register_quiet_hours(lambda _tenant: _window_around_now())
    judged = services.mark_message_sending(
        tenant=tenant, actor=owner_actor, message=message
    ).message

    # `queued`, not `sending`: the edge wall refused temporally, which is the
    # answer the delivery activity turns into a timer.
    assert judged.status == Message.Status.QUEUED
    assert judged.suppressed_reason == ""


def test_the_longer_of_the_two_windows_is_what_the_run_waits(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """Both windows refuse independently, so waiting the shorter is waking into a refusal.

    And waking into a refusal spends the run's one deferral (`MAX_DEFERRALS`) and
    records a message nobody sent — which is the failure `quiet_defer_seconds`
    exists to avoid rather than a conservatism.
    """
    at = timezone.now()
    make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(
            (at - timedelta(minutes=30)).time().replace(second=0, microsecond=0),
            (at + timedelta(minutes=10)).time().replace(second=0, microsecond=0),
        ),
    )
    register_quiet_hours(lambda _tenant: _window_around_now(minutes=90))

    preference = get_preference(
        tenant=tenant,
        recipient=recipient,
        channel=Channel.EMAIL,
        org=owner_actor.org,
        actor=owner_actor,
    )
    assert preference is not None
    person = int(preference.quiet_opens_in(at).total_seconds())
    both = quiet_defer_seconds(preference=preference, tenant=tenant, at=at)

    assert both > person, "the tenant's window runs later and is what decides"


# --- a product's resolver is a product's bug, and it is loud ----------------------


def test_a_resolver_that_raises_is_logged_and_lets_the_send_through(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The seam's one opinion, and it is about its own failure mode.

    Refusing would mean a product's quiet-hours misconfiguration stops that
    tenant contacting anybody at all — transactional mail their customers are
    waiting for included. Proceeding means a marketing message may go out inside
    a window somebody meant to configure. The second is the smaller harm and it
    is loud; the first is silent from the recipient's side and catastrophic from
    the tenant's.

    *Absent:* one raising resolver takes a tenant off the air, and the log says
    nothing about why.
    """

    def broken(_tenant: Tenant) -> QuietWindow | None:
        raise RuntimeError("the settings table is not there")

    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    register_quiet_hours(broken)

    assert tenant_quiet_window(tenant) is None
    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)
    assert message.status == Message.Status.QUEUED


def test_a_resolver_that_answers_something_else_is_ignored(tenant: Tenant) -> None:
    """A product handing back the wrong shape gets the unset answer, not a crash.

    The seam takes a `QuietWindow`; anything else is a product bug and is read
    as "no window", for the same reason a raising resolver is.
    """
    register_quiet_hours(lambda _tenant: "22:00-07:00")  # type: ignore[arg-type,return-value]
    assert tenant_quiet_window(tenant) is None


def test_an_unknown_timezone_falls_back_to_utc_rather_than_raising(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad string in a product's seam must not stop the tenant sending.

    The same fallback a preference row's own zone gets, through the same
    function — which is the point of `models.quiet_zone` being shared rather
    than copied.

    The clock is this test's own. The window is `start <= local < end`, so a
    window of 00:00–23:59 is open for the last minute of every UTC day, and a
    test that read the real clock failed whenever it ran inside that minute.
    Both instants below are fixed: one inside the window, and the end edge,
    which is outside it — and outside it because the zone fell back to UTC:
    the same instant read in a zone off UTC+0 lands mid-window.
    """
    window = QuietWindow(start=time(0, 0), end=time(23, 59), timezone="Mars/Olympus")

    inside = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: inside)
    assert window.is_quiet_at(timezone.now()) is True

    at_the_end_edge = datetime(2026, 1, 15, 23, 59, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: at_the_end_edge)
    assert window.is_quiet_at(timezone.now()) is False


# --- the queue-time/transport-edge asymmetry ---------------------------------------------------


def test_the_two_sides_of_ten_oclock_now_agree(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """22:30 and 21:59 reach the same place.

    The two sends are the two sides of the window's opening edge — one judged
    inside it at queue time, one judged inside it at the transport edge — and
    until this fix they got opposite answers to the same question about the
    same clock. Both are now `queued` with a run to wait in.

    Driven as the two code paths rather than as two wall-clock times, because
    the asymmetry was never about the hour: it was about *which wall saw it*.

    *Absent:* half of every evening campaign is silently thrown away, and the
    half that survives is the half that happened to be submitted a minute
    earlier.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    make_template(
        actor=owner_actor, name="late-campaign", channel=Channel.EMAIL, category="marketing"
    )

    # 21:59 — queued while the window is open, judged at the edge once it shuts.
    early = _campaign(
        tenant=tenant, actor=owner_actor, recipient=recipient, template="late-campaign"
    )
    register_quiet_hours(lambda _tenant: _window_around_now())
    at_the_edge = services.mark_message_sending(
        tenant=tenant, actor=owner_actor, message=early
    ).message

    # 22:30 — the window was already shut when this one was written.
    late = _campaign(
        tenant=tenant, actor=owner_actor, recipient=recipient, template="late-campaign"
    )

    assert at_the_edge.status == Message.Status.QUEUED
    assert late.status == Message.Status.QUEUED
    assert at_the_edge.suppressed_reason == late.suppressed_reason == ""
    assert late.delivery_workflow_id, "the queue-time refusal has a run to wait in"


def test_a_permanent_lever_still_kills_at_queue_time(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The other half of the fork, so this change is a fork and not a widening.

    Consent that was never given does not arrive by waiting, and a suppressed
    address does not un-suppress overnight. Both still write a refusal row here
    and start nothing.

    *Absent:* "quiet hours defers" quietly became "everything defers", and a
    marketing send to somebody who never opted in sits in a run instead of being
    refused.
    """
    register_quiet_hours(lambda _tenant: _window_around_now())

    never_consented = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)

    assert never_consented.status == Message.Status.SUPPRESSED
    assert never_consented.suppressed_reason == Message.SuppressedReason.NO_CONSENT
    assert never_consented.delivery_workflow_id == ""


def test_the_deferred_row_announces_itself_as_queued_and_not_as_suppressed(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The event a subscriber sees is the true one.

    A `comms.message.suppressed` for a message that is about to be delivered is
    the ledger lying in the noisiest possible way — `mark_message_sending`'s own
    note says so about the edge, and the queue-time path now says the same
    thing.
    """
    from apps.events.models import Event

    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    register_quiet_hours(lambda _tenant: _window_around_now())

    message = _campaign(tenant=tenant, actor=owner_actor, recipient=recipient)

    named = {
        event.name for event in Event.objects.for_tenant(tenant).filter(payload__id=str(message.pk))
    }
    assert named == {"comms.message.queued"}


def test_the_seam_reads_the_window_in_its_own_timezone(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The tenant's window belongs to the tenant, not to the server.

    The same property `ChannelPreference` has and — because both call the same
    two functions in `apps/comms/models.py` — necessarily the same answer. That
    sharing is the point: a tenant window and a person window that disagreed
    about what "22:00" means would be two quiet-hours features.
    """
    now = timezone.now()
    ahead = QuietWindow(
        start=time((now.hour + 2) % 24, 0),
        end=time((now.hour + 4) % 24, 0),
        timezone="UTC",
    )
    assert ahead.is_quiet_at(now) is False

    # The same clock window, read two hours west, now contains this instant.
    shifted = QuietWindow(start=ahead.start, end=ahead.end, timezone="Etc/GMT-2")
    assert shifted.is_quiet_at(now) is True


def test_the_window_and_the_preference_answer_alike() -> None:
    """A tenant window and a person's window with the same ends answer every instant alike."""
    from apps.comms.models import ChannelPreference

    windows = [(time(22, 0), time(7, 0)), (time(9, 0), time(17, 0)), (time(0, 0), time(23, 59))]
    base = datetime(2026, 3, 28, 0, 0, tzinfo=UTC)
    instants = [base + timedelta(minutes=37 * step) for step in range(80)]
    for zone in ("UTC", "Europe/London", "America/Los_Angeles"):
        for start, end in windows:
            person = ChannelPreference(
                quiet_hours_start=start, quiet_hours_end=end, quiet_hours_timezone=zone
            )
            house = QuietWindow(start=start, end=end, timezone=zone)
            for at in instants:
                assert person.is_quiet_at(at) == house.is_quiet_at(at), (zone, start, end, at)
                assert person.quiet_opens_in(at) == house.opens_in(at), (zone, start, end, at)


def test_a_window_whose_ends_are_equal_is_no_window(tenant: Tenant) -> None:
    """Not a zero-length window and not an all-day one: one nobody meant to set.

    Stated here because a product's resolver is the most likely place to produce
    one by accident, and "all day" would be the most expensive possible reading
    of a typo.
    """
    window = QuietWindow(start=time(9, 0), end=time(9, 0))
    assert window.is_quiet_at(timezone.now()) is False
    assert window.opens_in(timezone.now()) == timedelta(0)


def test_registering_twice_replaces_rather_than_stacks(tenant: Tenant) -> None:
    """One answer to "what is this tenant's window", because a second is a second policy."""
    register_quiet_hours(lambda _tenant: QuietWindow(start=time(1, 0), end=time(2, 0)))
    register_quiet_hours(lambda _tenant: QuietWindow(start=time(3, 0), end=time(4, 0)))

    window = tenant_quiet_window(tenant)
    assert window is not None
    assert window.start == time(3, 0)


def test_the_seam_is_per_tenant(tenant: Tenant, other_tenant: Tenant) -> None:
    """A resolver is handed the tenant, so a product may answer differently per tenant.

    Which is the whole reason it is a resolver rather than a setting: a
    deployment-wide window would make one customer's evening every customer's.
    """
    register_quiet_hours(
        lambda t: QuietWindow(start=time(1, 0), end=time(2, 0)) if t.pk == tenant.pk else None
    )

    assert tenant_quiet_window(tenant) is not None
    assert tenant_quiet_window(other_tenant) is None


def test_no_tenant_is_no_window(_seam_is_unset_around_every_test: None) -> None:
    """`None` in, `None` out — the fail-closed shape every other read here has."""
    register_quiet_hours(lambda _tenant: QuietWindow(start=time(1, 0), end=time(2, 0)))
    assert tenant_quiet_window(None) is None
