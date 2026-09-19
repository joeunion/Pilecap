"""The names of the things this app says happened.

Names only, and that is the whole file (house rule 16). One name per terminal
state a message can reach, because a subscriber's question is always "what
happened to the thing I asked you to send" and the four answers are: it is on
its way, it went, it did not go, and we refused to send it.

**Two names below are about the person rather than about the message**, and
they are the second exception to the sentence above: `comms.message.opened` and
`comms.message.clicked` (ADR comms-9's engagement half) announce a
`MessageEngagement` row and change nothing about the `Message` at all. They are
named `comms.message.*` because the aggregate is still `Message` — house rule
16's grammar is `<app>.<noun>.<past-verb>` and the noun is the thing the news
is about.

**And two names are about a DEVICE** — `comms.device.registered` and
`comms.device.retired` (T3). Those really are a third noun rather than a
third exception: the push address book is its own table, a registration is not
a fact about any message, and house rule 16's grammar puts the noun the news is
about in the middle.

**`comms.message.complained` is the one exception and it is a deliberate one**
(ADR comms-9, amended): a spam complaint is not a state the message reached at
all — it is news about *consent*, arriving after a message that very much
arrived. It has its own name here rather than a status on the row, because the
alternative is a `delivered` message logged as having bounced.

**`comms.message.suppressed` is the one that matters most**, and it is an event
rather than an exception on purpose. A marketing send to somebody who never
consented is not a *failure* — the product behaved correctly — but it is
absolutely something a campaign dashboard, an audit and a support agent need to
be able to see. So the refusal writes a `Message` row with
`status=suppressed`, says so here, and starts no delivery.

`comms.message.delivered` and `comms.message.bounced` are the two this app
cannot say on its own. They are facts the *transport* tells us afterwards,
through the signed status webhook that rides `apps/connections`' receiver (ADR
comms-3), and `services.record_delivery_status` is the only function that
emits them. An event name is a published contract, so each is declared here in
the same change as the code that publishes it and not before.
"""

from __future__ import annotations

#: The payload version this app stamps on the events whose payload it builds by
#: hand — today the two suppression-surge announcements. The `comms.message.*`
#: events publish a SCHEMA — `MessageOut` for the message's own lifecycle,
#: `MessageEngagementOut` for the two engagement names — and are versioned with
#: that schema rather than with a number here; a `v` bolted onto them now would
#: be a second version story for one contract.
V = 1

#: Accepted, consent checked, delivery workflow started.
MESSAGE_QUEUED = "comms.message.queued"

#: The provider accepted it. The furthest this app can see on its own.
MESSAGE_SENT = "comms.message.sent"

#: The provider refused it, or the delivery workflow ran out of attempts.
MESSAGE_FAILED = "comms.message.failed"

#: The transport says it arrived. From a status webhook, never from us.
MESSAGE_DELIVERED = "comms.message.delivered"

#: The transport says it will not arrive: a hard bounce or a rejection. The one
#: a product most needs on its own message log — a bounce nobody can see is an
#: address that stays wrong for ever. **A spam complaint is no longer one of
#: these** (ADR comms-9, amended): it says nothing about whether the message
#: arrived, and it has `MESSAGE_COMPLAINED` below.
MESSAGE_BOUNCED = "comms.message.bounced"

#: We refused to send it: no consent, quiet hours, or a suppressed address.
MESSAGE_SUPPRESSED = "comms.message.suppressed"

#: Somebody pressed "report spam". **The one `comms.message.*` name that is not
#: a terminal state**, and that is the whole of ADR comms-9 as amended: a
#: complaint is a fact about *consent*, where a bounce is a fact about the
#: *address* and a delivery a fact about the *message*. A complaint by
#: definition follows a delivery, so a name that had to transition the row
#: could only say the message failed — which it did not, and E1′'s live drive
#: found the row's own truth being refused with a `Conflict` while the person
#: who reported us stayed mailable.
#:
#: So this one transitions nothing: it suppresses the recipient through the
#: same `suppress_recipient` a hard bounce and a support agent both use, and
#: says so under its own name. The payload is the message `MessageOut` — the
#: row exactly as it stands, `delivered` still reading `delivered` — and the
#: provider's own handle for the message rides on it as
#: `provider_message_id`, which is the join back to the report.
MESSAGE_COMPLAINED = "comms.message.complained"

#: A provider says somebody OPENED a message. **News about a person, never
#: about the message row** (ADR comms-9): an open is an inference from a request
#: for a tracking image, and on Apple Mail Privacy Protection that request is
#: made for every message a user receives whether they look at it or not. So
#: this name announces an engagement row and nothing else — no status moved, no
#: consent changed, nothing was suppressed. The payload is
#: `MessageEngagementOut`, the read shape of the row itself, which carries
#: `organization_id` because the socket fan-out narrows on that key and a
#: payload without one is delivered to every socket in the tenant.
MESSAGE_OPENED = "comms.message.opened"

#: And the same for a click, which is the stronger signal of the two: a click
#: is a request a person's own action caused, where an open may be a proxy's.
#: Its own name rather than a field on the one above, because a subscriber
#: filtering for "somebody actually engaged" should not have to read a payload
#: to find out which kind of event it just received.
MESSAGE_CLICKED = "comms.message.clicked"

#: The suppression wall started firing like a weapon: more than
#: `services.SURGE_THRESHOLD` addresses silenced on one connection inside a
#: trailing hour (ADR comms-9). Emitted **once**, on the crossing, and never
#: again while the surge is open — the announce-on-transition ruling of
#: 2026-08-22, whose whole point is that a degradation is a *state* the system
#: announces rather than a stream of per-request noise a human learns to
#: ignore. The `SuppressionSurge` row is the memory that makes "once" true even
#: when an attacker re-probes.
SUPPRESSION_SURGED = "comms.suppression.surged"

#: The trailing hour is back under the threshold and the surge row is closed.
#: The other half of the transition pair, emitted exactly once for each
#: `comms.suppression.surged` — an alert that can be raised and never lowered is
#: an alert somebody silences.
SUPPRESSION_RECOVERED = "comms.suppression.recovered"

#: A contact's device joined the push address book — a new install, or a token
#: this deployment had already seen coming back after a rotation. **News about
#: reachability, never about consent**: a registration says the product now
#: *can* push to this handset, and whether it *may* is the `push` channel's
#: `ChannelPreference`, decided inside `send()`. A subscriber that treated this
#: as an opt-in would be reading the wrong table.
#:
#: The payload is `DeviceOut` — which carries no token material at all, for the
#: reason `Device.push_token` is encrypted: an event is delivered to every
#: subscribed endpoint a tenant has configured, and a push token on that wire is
#: the capability to reach somebody's lock screen sitting in somebody else's
#: log.
DEVICE_REGISTERED = "comms.device.registered"

#: A device stopped being reachable: the platform retired the token, the person
#: signed out, the handset was sold. Its own name rather than a field on the one
#: above, for `comms.message.clicked`'s reason — a subscriber keeping a mirror
#: of who is reachable filters on the name and never on a payload.
DEVICE_RETIRED = "comms.device.retired"


#: The sender changed their mind before it went out. **Not a suppression
#: and deliberately its own name**: `comms.message.suppressed` is the product
#: refusing on the RECIPIENT's behalf, and a subscriber keeping a consent mirror
#: off that stream would record an opt-out nobody made. Only a message no
#: transport has seen can reach this. The payload is `MessageOut`, the row as it
#: now stands.
MESSAGE_CANCELLED = "comms.message.cancelled"


#: Which authorization kind each noun above is about, for the socket door's read
#: check (`apps.realtime.bridge.kind_of_event`, ADR core-27). Only the nouns that
#: are not themselves kinds need a line: `message` and `device` are kinds and
#: answer for themselves.
EVENT_KINDS: dict[str, str | None] = {
    # The surge announcements are about the `SuppressionSurge` row they are
    # raised and cleared from, so `suppression_surge.read` is the key that
    # governs hearing them.
    "suppression": "suppression_surge",
}
