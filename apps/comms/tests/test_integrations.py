"""comms in the integrations census: **the fake says so, out loud.**

The census (`apps.core.integrations`) asks every app the same
question and an earlier pass landed the seam with only a planted fixture ever having
answered it. This is comms' answer, and every test here is one property of it:

* **derived, never listed.** The rows come out of `providers.registered_channels()`
  at census time, so a product that replaces a slot changes what the census
  reports with no edit to `apps/comms/integrations.py` — and a product that
  registers a fourth kind gets a fourth row. That is the owner's no-list-edit
  criterion, driven twice below rather than restated;
* **the fake is loud.** `FakeSmsChannel` and `FakePushChannel` hold the `sms`
  and `push` slots on a fresh clone and each reports `FAKE` with a remedy
  somebody can type. This is the fresh-clone STOP class — a STOP that was
  signed, verified, stored and dropped while the only thing in the tree saying
  the transport was a stand-in was a comment in `providers.py`;
* **every shipped fake declares.** The one defence the census's declared blind
  spot ("nothing here audits the claim") leaves available: this template's own
  fakes cannot quietly stop confessing, because the population is derived from
  the module and checked, not from a list;
* **it stays out of core's lane.** `outbound-email` is the backend's row and is
  `apps.core.integrations`'; comms' `email` row is about the adapter holding the
  slot. Two questions, two keys, and neither re-decides the other.
"""

# names, never reads: docs/runbooks/deploy.md — a substring a row's remedy must carry; never opened

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from apps.comms.integrations import EMAIL_BACKEND_KEY, KEY_PREFIX, SOURCE, register
from apps.comms.models import Channel
from apps.comms.providers import (
    ChannelProvider,
    DeclaresFakeness,
    Fakeness,
    ProviderStatus,
    Sent,
    channel_fakeness,
    register_channel,
    registered_channels,
    unregister_channel,
)
from apps.core.integrations import (
    Integration,
    IntegrationRegistry,
    IntegrationStatus,
    census,
    declaring_modules,
)


def _declared() -> dict[str, Integration]:
    """What this app's `register` puts in a registry of its own. No census walk."""
    registry = IntegrationRegistry()
    register(registry)
    return {row.key: row for row in registry.declarations()}


@pytest.fixture
def channel_slot() -> Iterator[Any]:
    """Register a transport for the length of a test, then put the slot back.

    The registry is process-global — `test_sms_transport.py` records what an
    unregister-on-teardown did to the tests relying on the shipped fake — so the
    teardown restores the previous occupant rather than emptying the slot, and
    removes a slug that was not there before.
    """
    taken: list[tuple[str, Any]] = []

    def use(provider: Any) -> Any:
        taken.append((provider.slug, registered_channels().get(provider.slug)))
        register_channel(provider)
        return provider

    yield use
    for slug, previous in reversed(taken):
        if previous is not None:
            register_channel(previous)
        else:
            unregister_channel(slug)


# --- the seam is reachable at all -------------------------------------------------


def test_the_census_walk_finds_this_app() -> None:
    """The discovered hook, from the platform's side.

    Until this fix the census had only ever met `apps/core/tests/integrations.py`
    — a fixture declared honestly as one. This is the first real app through the
    seam, which is the thing that was untested about it.
    """
    assert "apps.comms.integrations" in declaring_modules()


def test_the_census_reads_comms_without_an_unreadable_seam() -> None:
    """A raising `register` is exit 2, never a verdict. This one does not raise.

    Asserted on the whole census rather than on this app's rows, because
    "readable" is the property the four surfaces branch on and an app that broke
    it would break them for every other app too.
    """
    read = census()
    assert read.is_readable, read.unreadable
    assert any(row.declared_by == SOURCE for row in read.integrations)


# --- one row per registered channel, derived ---------------------------------------


def test_there_is_one_row_per_registered_channel() -> None:
    """The population IS the registry — equality, not containment.

    Equality both ways is what makes this able to fail: a row for a channel
    nobody registered is as wrong as a registered channel with no row, and only
    one of those two is what a list would have produced.
    """
    rows = _declared()
    assert set(rows) == {f"{KEY_PREFIX}-{slug}" for slug in registered_channels()}


def test_a_fresh_clone_reports_the_two_fakes_and_the_one_real_adapter() -> None:
    """The shipped state, said out loud.

    *Absent:* a deployment reads its own census, sees three channels and no
    warning, and finds out about the `sms` slot from a customer.
    """
    rows = _declared()
    assert rows[f"{KEY_PREFIX}-sms"].status is IntegrationStatus.FAKE
    assert rows[f"{KEY_PREFIX}-push"].status is IntegrationStatus.FAKE
    assert rows[f"{KEY_PREFIX}-email"].status is IntegrationStatus.CONFIGURED


def test_every_fake_row_carries_a_remedy_somebody_can_type() -> None:
    """The census refuses a remedy-less non-configured row at import; this is the
    half that says the remedy is *useful*.

    `register_channel` and the runbook section are both named, because "not
    configured" without "here is what to type" is the failure the instrument
    checklist exists for.
    """
    for row in _declared().values():
        if row.is_configured:
            continue
        assert "register_channel(" in row.remedy, row.key
        assert "docs/runbooks/deploy.md" in row.remedy, row.key
        # And the detail says what is TRUE rather than restating the status: it
        # names the class holding the slot and what becomes of a message handed
        # to it. `core.integrations`' own docstring asks for exactly this — "the
        # console backend prints mail to stdout" rather than "fake" — and the
        # assertion is about the SENTENCE having content, not about the word
        # `fake` being absent, because these details legitimately name
        # `FakeSmsChannel` and `fake_sms_outbox`.
        assert row.detail.strip() != row.status.value, row.key
        assert "slot" in row.detail, row.key
        assert row.detail.rstrip().endswith("."), row.key


def test_the_sms_row_names_the_silence_it_closes() -> None:
    """The STOP that a fresh clone drops.

    The one row whose *detail* has to carry a specific fact rather than a shape,
    because the defect was specific: everything upstream of the transport worked,
    so a reader who is told only "this is a stand-in" still does not know that
    their opt-outs are going nowhere.
    """
    detail = _declared()[f"{KEY_PREFIX}-sms"].detail
    assert "STOP" in detail
    assert "nothing leaves this process" in detail


def test_the_email_row_defers_to_cores_backend_row() -> None:
    """Two questions, two keys, and neither re-decides the other.

    comms says which adapter holds the slot; `apps.core.integrations` says
    whether mail leaves the process. A comms row that judged `EMAIL_BACKEND`
    would be a second opinion in a second place, which is how two instruments
    come to disagree — the census's own docstring says so about itself.
    """
    rows = _declared()
    email = rows[f"{KEY_PREFIX}-email"]
    assert EMAIL_BACKEND_KEY in email.detail
    assert EMAIL_BACKEND_KEY not in rows, "core owns that key; comms must not declare it"
    # And the two really are both in the live census, under their two keys.
    live = {row.key for row in census().integrations}
    assert {EMAIL_BACKEND_KEY, f"{KEY_PREFIX}-email"} <= live


def test_comms_keys_never_collide_with_another_apps() -> None:
    """The registry refuses a duplicate key by raising; this catches it earlier.

    A collision would be a census that fails to build at all, on every surface,
    for every app — so the prefix is worth an assertion of its own rather than
    being discovered when somebody's `setup.sh` stops printing.
    """
    mine = set(_declared())
    theirs = {row.key for row in census().integrations if row.declared_by != SOURCE}
    assert mine.isdisjoint(theirs)
    assert all(key.startswith(f"{KEY_PREFIX}-") for key in mine)


# --- the no-list-edit criterion, driven -------------------------------------------


class _RealSms:
    """A product's real SMS transport, **and it says so.**

    It used to say nothing and be read as real by default. That default was the
    finding: silence and a claim were the same answer, so a product's forgotten
    stand-in read `configured`. Declaring is now how a transport claims it.
    """

    slug = Channel.SMS.value

    def send(self, *, message: Any, subject: str, body: str, nonce: str = "") -> Sent:
        return Sent(provider="a-real-gateway", provider_message_id="SM1")

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        return None

    def fakeness(self) -> Fakeness | None:
        return None


class _Carrier:
    """A kind this template has never heard of, registered by a product."""

    slug = "carrier-pigeon"

    def send(self, *, message: Any, subject: str, body: str, nonce: str = "") -> Sent:
        return Sent(provider="pigeon", provider_message_id="P1")

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        return None

    def fakeness(self) -> Fakeness | None:
        return None


class _Bare:
    """A transport that declares NOTHING — the population `DeclaresFakeness` is about.

    Not a fake and not claiming to be real: it simply never implements the
    protocol, which is what a product's adapter looks like the day before
    somebody remembers. The census must not guess, and must not guess
    optimistically.
    """

    slug = "carrier-pigeon"

    def send(self, *, message: Any, subject: str, body: str, nonce: str = "") -> Sent:
        return Sent(provider="bare", provider_message_id="B1")

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        return None


def test_replacing_a_slot_changes_the_row_with_no_edit_here(channel_slot: Any) -> None:
    """The owner's criterion, one level down, and this is the direction that matters.

    A deployment that registers a real SMS transport stops being reported as a
    fake — everywhere, on all four surfaces — because the row was derived from
    the registry rather than written down. Nothing in
    `apps/comms/integrations.py` moved.

    *Absent:* the module lists its channels, a product swaps a slot, and the
    census goes on printing a remedy for a problem that was fixed months ago.
    """
    assert _declared()[f"{KEY_PREFIX}-sms"].status is IntegrationStatus.FAKE

    channel_slot(_RealSms())

    row = _declared()[f"{KEY_PREFIX}-sms"]
    assert row.status is IntegrationStatus.CONFIGURED
    assert "_RealSms" in row.detail
    assert row.remedy == "", "a configured row needs no remedy and must not invent one"


def test_a_kind_this_template_never_heard_of_gets_a_row_for_free(
    channel_slot: Any,
) -> None:
    """The other direction: growth with no edit to any list, including this one.

    A slug outside `Channel` still gets a readable title rather than a
    `KeyError`, which is the difference between a census that survives a product
    and one that is a list with extra steps.
    """
    channel_slot(_Carrier())

    row = _declared()[f"{KEY_PREFIX}-carrier-pigeon"]
    assert row.status is IntegrationStatus.CONFIGURED
    assert row.title == "Carrier pigeon channel"


def test_a_products_fake_is_reported_as_a_fake_too(channel_slot: Any) -> None:
    """The protocol is the product's to implement, not this template's to detect.

    A product with a sandbox transport declares `fakeness()` and the census
    reports it, with the product's own remedy — which is the whole reason this
    is a protocol rather than a list of class names in `apps/comms`.
    """

    class _Sandbox:
        slug = "carrier-pigeon"

        def send(self, *, message: Any, subject: str, body: str, nonce: str = "") -> Sent:
            return Sent(provider="sandbox", provider_message_id="S1")

        def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
            return None

        def fakeness(self) -> Fakeness:
            return Fakeness(
                detail="the sandbox pigeon never leaves the loft.",
                remedy="point PIGEON_LOFT at a real loft and restart the worker.",
            )

    channel_slot(_Sandbox())

    row = _declared()[f"{KEY_PREFIX}-carrier-pigeon"]
    assert row.status is IntegrationStatus.FAKE
    assert row.remedy.startswith("point PIGEON_LOFT")


# --- the belt on this template's own fakes ------------------------------------------


def test_every_shipped_fake_transport_declares_its_fakeness() -> None:
    """**The one defence available against the census's declared blind spot.**

    `core.integrations`' docstring says it plainly: nothing there audits the
    claim, and a fake that declared itself real would be reported as real. That
    is unavoidable for a product's own adapters. It is entirely avoidable for
    the transports THIS template ships, and this is how — the population is
    derived from the module rather than listed, so a fourth fake added in some
    future rung is caught the day it lands rather than the day somebody's
    customer notices.

    *Absent:* somebody adds `FakeChatChannel`, forgets the confession, and the
    census reports a chat integration that reaches nobody as configured.
    """
    from apps.comms import providers

    shipped_fakes = [
        candidate
        for name in dir(providers)
        if name.startswith("Fake")
        and name.endswith("Channel")
        and isinstance(candidate := getattr(providers, name), type)
    ]
    assert shipped_fakes, "no fake transports found — this test would pass vacuously"

    for fake in shipped_fakes:
        # Typed as the transport protocol, which is what these classes are and
        # what the census hands `channel_fakeness`. Asserting `DeclaresFakeness`
        # after narrowing to it would be asserting the narrowing.
        instance: ChannelProvider = fake()
        assert isinstance(instance, DeclaresFakeness), fake.__name__
        confession = channel_fakeness(instance)
        assert confession is not None, fake.__name__
        assert confession.detail.strip() and confession.remedy.strip(), fake.__name__


def test_the_real_email_adapter_claims_to_be_real(channel_slot: Any) -> None:
    """The control, **inverted by the new protocol** — and the inversion is the finding.

    The earlier shape shipped this as `…_declares_nothing`: `EmailChannel` implemented no
    protocol and `channel_fakeness` took silence as a claim of realness. The
    comms lane then planted a bare channel and read `configured` back, which is
    that default being the optimistic one on the single question the census
    exists to answer.

    So silence is silence now. A real transport SAYS it is real
    (`REALLY_SENDS`), a stand-in says what it does instead, and a transport that
    says nothing is neither — which is the third case below.
    """
    from apps.comms.providers import REALLY_SENDS, EmailChannel

    assert isinstance(EmailChannel(), DeclaresFakeness)
    assert channel_fakeness(EmailChannel()) == REALLY_SENDS
    assert not REALLY_SENDS.detail and not REALLY_SENDS.remedy


def test_a_transport_that_declares_nothing_is_never_configured(
    channel_slot: Any,
) -> None:
    """**Driven.** The optimistic default is dead.

    A product's adapter that has not implemented `DeclaresFakeness` reads as
    unknown-and-therefore-unmet: the deploy wall refuses it, and the remedy says
    what to write. Before this fix it read `configured` — so a product's silent
    fake was invisible to the one instrument built to catch silent fakes.

    *Absent:* a deployment ships a stand-in nobody declared, the census says
    everything is configured, and the first person to find out is a customer.
    """
    channel_slot(_Bare())

    row = _declared()[f"{KEY_PREFIX}-carrier-pigeon"]
    assert row.status is not IntegrationStatus.CONFIGURED
    assert not row.is_configured, "the deploy wall refuses on exactly this"
    assert "fakeness()" in row.remedy
    assert "unknown" in row.detail
