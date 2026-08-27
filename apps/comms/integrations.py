"""What this deployment can actually reach a person on. **One row per channel.**

`apps.core.integrations`' discovered hook, for comms. The census asks
every app the same question — *is this integration real here, is it a fake, or
is it absent, and what does somebody type* — and this app's answer is the
channel registry, read at census time and never listed.

## Derived from `registered_channels()`, which is the whole point

There is no list of channels here. `providers.registered_channels()` is the
registry a product replaces slots in from its own `AppConfig.ready()`, so a
deployment that swaps `FakeSmsChannel` for `TwilioSmsChannel` changes what this
module reports **without editing this module** — and a product that registers a
fourth kind gets a fourth row for free. That is the owner's criterion on the
census (a new integration reaches all four surfaces with no edit to any list)
applied one level down, to the thing this app's integrations actually are.

## Why the fake is the row that matters

A fresh clone keeps `FakeSmsChannel` on the `sms`
slot by design. A real recipient texts STOP, Twilio signs the callback,
`apps/connections`' receiver verifies it, stores it and answers 202 — and then
nothing happens, because the transport that would have read it is a stand-in.
Every layer worked. The only thing in the tree that said so was a comment in
`providers.py`.

A filled slot is **more** dangerous than an empty one, because the empty one
refuses and the fake one succeeds. `providers.DeclaresFakeness` is how a
transport confesses and `IntegrationStatus.FAKE` is where the confession lands;
this module is the wire between them.

## What it does NOT say, and where that lives instead

* **Whether mail leaves this process.** That is `EMAIL_BACKEND`, deployment
  configuration rather than a channel, and `apps.core.integrations` already
  declares it as `outbound-email`. This module's `email` row reports the
  *adapter holding the slot* and points at that row for the rest. Two rows, two
  different questions, and neither re-decides the other — a second opinion in a
  second place is how two instruments come to disagree, which the census's own
  docstring says about itself.
* **Whether any tenant can send.** Twilio and FCM credentials are `Connection`
  rows, so "can this deployment send an SMS" is a query and not a setting. The
  census's own docstring declares that boundary; a deployment-level slot is
  what this app can honestly answer for.
* **Whether a transport is telling the truth.** Nothing here audits the claim —
  a fake that declared itself real would be reported as real. That is the
  census's declared blind spot, and the defence for the transports this
  template ships is `tests/test_integrations.py`, which holds every shipped
  `Fake…Channel` to declaring.

Every row is `probe="declared"`. Reaching a transport to find out whether it
works would mean sending somebody a message, and an instrument that mails a
person every time it is asked a question is an instrument that gets run twice —
the same argument `_outbound_email` makes one module over.
"""

from __future__ import annotations

from apps.comms.models import Channel
from apps.comms.providers import (
    ChannelProvider,
    channel_fakeness,
    registered_channels,
)
from apps.core.integrations import (
    PROBE_DECLARED,
    Integration,
    IntegrationRegistry,
    IntegrationStatus,
)

SOURCE = "apps/comms/integrations.py"

#: The key prefix every row here carries. One word, so a runbook, an alert and
#: the deploy wall can all name a comms channel without ambiguity, and so a
#: prefix search finds the set — the same reasoning `workflow_id`'s four-segment
#: grammar rests on.
KEY_PREFIX = "comms-channel"

#: The row `apps.core.integrations` owns and this module deliberately does not.
#: Named rather than described so the cross-reference in the `email` row's
#: detail cannot drift from the key it points at.
EMAIL_BACKEND_KEY = "outbound-email"


def _title(slug: str) -> str:
    """What a person calls this channel, from the enum that already names it.

    `Channel`'s own labels, so the census and the API document say the same
    word — and a slug a product invented for a kind this template has never
    heard of still gets a readable title rather than a `KeyError`.
    """
    labels = {choice.value: choice.label for choice in Channel}
    # `.capitalize()` over a de-hyphenated slug rather than `.title()`, which
    # would make `carrier-pigeon` into `Carrier-Pigeon` — a shape nobody writes.
    fallback = str(slug).replace("-", " ").replace("_", " ").capitalize()
    return f"{labels.get(slug, fallback)} channel"


def _row(slug: str, provider: ChannelProvider) -> Integration:
    """One channel's row: which transport holds the slot, and is it real.

    The status comes from the transport itself (`DeclaresFakeness`), never from
    this module inspecting a class name — see `providers.channel_fakeness` for
    why a name heuristic would be the worst of both.
    """
    holder = type(provider).__name__
    confession = channel_fakeness(provider)
    if confession is None:
        # **Silence is not a yes.** The transport does not implement
        # `DeclaresFakeness` at all, so nothing has said whether it reaches
        # anybody — and the census must not guess, least of all optimistically
        # on the one question it exists to answer.
        #
        # `NOT_CONFIGURED` rather than a fourth status word, and that is a
        # territory decision rather than a judgement that the
        # word is right: `IntegrationStatus` lives in `apps/core`, whose own
        # docstring says there is deliberately no fourth member, and this
        # app's territory is `apps/comms`. The behaviour asked for is here in
        # full — it never reads `configured`, the deploy wall refuses it, and
        # the remedy says what to implement. Whether the platform grows a
        # literal `unknown` is a core decision, flagged separately.
        return Integration(
            key=f"{KEY_PREFIX}-{slug}",
            title=_title(slug),
            status=IntegrationStatus.NOT_CONFIGURED,
            detail=(
                f"{holder} holds the {slug!r} slot and has told the census nothing: it "
                f"does not implement providers.DeclaresFakeness, so whether it reaches "
                f"a real gateway or quietly drops every message is unknown here."
            ),
            remedy=(
                f"implement `fakeness()` on {holder} — return None if it really sends, "
                f"or a providers.Fakeness(detail=..., remedy=...) if it is a stand-in "
                f"(apps/comms/providers.py, beside FakeSmsChannel)."
            ),
            probe=PROBE_DECLARED,
        )
    if confession.detail or confession.remedy:
        return Integration(
            key=f"{KEY_PREFIX}-{slug}",
            title=_title(slug),
            status=IntegrationStatus.FAKE,
            detail=confession.detail,
            remedy=confession.remedy,
            probe=PROBE_DECLARED,
        )
    # Past here the transport claimed to be real (`REALLY_SENDS`).
    if slug == Channel.EMAIL.value:
        return Integration(
            key=f"{KEY_PREFIX}-{slug}",
            title=_title(slug),
            status=IntegrationStatus.CONFIGURED,
            detail=(
                f"{holder} holds the 'email' slot and hands each message to Django's "
                f"mail path; whether mail then LEAVES this process is EMAIL_BACKEND's "
                f"answer and is the {EMAIL_BACKEND_KEY!r} row's."
            ),
            probe=PROBE_DECLARED,
        )
    return Integration(
        key=f"{KEY_PREFIX}-{slug}",
        title=_title(slug),
        status=IntegrationStatus.CONFIGURED,
        detail=(
            f"{holder} holds the {slug!r} slot and reaches a real gateway; each "
            f"tenant's credentials are a Connection row, so whether a given tenant "
            f"can send is a query rather than a setting."
        ),
        probe=PROBE_DECLARED,
    )


def register(registry: IntegrationRegistry) -> None:
    """The discovered hook. One row per registered channel, in slug order.

    Sorted so the four surfaces print the same order every time: a census whose
    rows move between runs is a census whose diff nobody can read.
    """
    for slug, provider in sorted(registered_channels().items()):
        registry.declare(_row(slug, provider), source=SOURCE)
