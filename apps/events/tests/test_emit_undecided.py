"""An undecided noun costs the event's fan-out, never the product's write.

**The rule-59 amendment, SIGNED by the owner 2026-09-21.** `emit` asks
`core.authz.kind_of_event` which authorization kind an event is about, and that
function refuses a noun no app's `EVENT_KINDS` decides. Until the amendment the
refusal was left to escape — out of `_refuse_a_branch_that_disagrees_with_the_name`,
out of `emit`, and into the *emitting service's transaction*. So a product that
added an event name and forgot one `EVENT_KINDS` line did not lose the event: it
lost the WRITE the event was about, and its doors answered 500. The consumer
measured exactly that on `apps/usage` — six `test_services.py` cases red, every
one of them a rolled-back recording rather than a dropped frame.

What this module pins is the amended behaviour, and the shape of the amendment
is *where* the refusal moved rather than that it went away:

* the write COMMITS and the `Event` row is written, with the noun undecided;
* the branch is stamped from the payload's top-level `organization_id` exactly
  as any other event's is — the resolution is untouched, so an absent key is
  still NULL and an id that does not resolve is still `Invalid`;
* the dispatch is still enqueued;
* `events.emit.kind_undecided` is logged at ERROR, carrying the name and the
  remedy (`--explain 59`);
* and the two PROVEN disagreements — an org-scoped noun whose payload names no
  branch, and an org-less noun whose payload names one — are untouched, because
  those are the two things `kind_of_event` can prove.

The noun is still refused, in the two places that can refuse it without costing
a write: the GATE (rule 59's `undecided_noun` class prints one finding per noun
with the `EVENT_KINDS` line to paste) and the SOCKET
(`realtime.consumers._may_read` catches the same `ImproperlyConfigured` per
frame and drops it, so an undecided noun reaches nobody). Both halves are cited
here and proved in their own files — `quality/rules.yaml` rule 59's canary
`an_undecided_noun.py`, and
`apps/realtime/tests/test_read_fanout.py::test_a_frame_whose_noun_is_undecided_is_dropped`.

**ABSENT before the amendment:** `services.emit` raised `ImproperlyConfigured` here,
so every case below was an exception rather than a row.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from apps.core import authz
from apps.core.actor import Actor
from apps.core.exceptions import Invalid
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.events import services
from apps.events.models import Event, Outbox
from apps.usage.events import THRESHOLD_CROSSED

pytestmark = pytest.mark.django_db


def structured(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """The JSON log lines stdlib logging received, parsed.

    The same idiom `accounts/tests/test_rp_login.py` uses, and for its reason:
    `structlog`'s capture fixture cuts the processor chain out, and what a
    person queries is the rendering. The `{` test keeps a library's stray
    plain-text line out of the list.
    """
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]


@pytest.fixture
def nobody_decides_the_noun(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every app declares no `EVENT_KINDS` — so `threshold` is undecided.

    Patched at `core.authz`, which is where `kind_of_event` looks the function
    up, rather than at `apps/usage/events.py`: deleting the real declaration
    would also be a change to the *tree* the gate measures, and the point of
    this module is the runtime behaviour on an undecided noun whatever produced
    it. `usage.threshold.crossed` is used because it is a DECLARED name — so
    `check_name` passes and the refusal under test is the only one in play — and
    because `threshold` is not itself an authorization kind, so the registry's
    first answer does not rescue it.
    """
    monkeypatch.setattr(authz, "event_kinds_of", lambda app_label: {})
    yield


def test_an_undecided_noun_still_writes_the_event_and_stamps_the_branch(
    tenant: Tenant,
    owner_actor: Actor,
    caplog: pytest.LogCaptureFixture,
    nobody_decides_the_noun: None,
) -> None:
    """The key is on the payload: one row, stamped with that branch, no raise."""
    root = root_organization(tenant=tenant)

    caplog.clear()
    with caplog.at_level(logging.ERROR):
        event = services.emit(
            name=THRESHOLD_CROSSED,
            tenant=tenant,
            payload={"organization_id": str(root.pk), "meter": "tokens"},
            actor=owner_actor,
        )

    assert Event.objects.for_tenant(tenant).filter(pk=event.pk).count() == 1
    assert event.organization_id == root.pk
    # The dispatch is enqueued exactly as it is for a decided noun: what the
    # undecided noun costs is delivery at the socket, not the outbox row.
    assert Outbox.objects.get(event=event).status == Outbox.Status.PENDING

    lines = [
        line for line in structured(caplog) if line.get("event") == "events.emit.kind_undecided"
    ]
    assert len(lines) == 1, structured(caplog)
    assert lines[0]["event_name"] == THRESHOLD_CROSSED
    assert lines[0]["remedy"] == "--explain 59"
    # The detail is `kind_of_event`'s own refusal, which names the noun and the
    # file that must decide about it — so the log line is actionable alone.
    assert "threshold" in lines[0]["detail"]
    assert "EVENT_KINDS" in lines[0]["detail"]


def test_an_undecided_noun_with_no_branch_on_the_payload_stamps_null(
    tenant: Tenant,
    owner_actor: Actor,
    caplog: pytest.LogCaptureFixture,
    nobody_decides_the_noun: None,
) -> None:
    """No key, no branch: NULL, which is what an org-less subject has always been.

    This is the case the amendment must NOT quietly convert into a refusal. The
    org-scoped refusal above it in `_refuse_a_branch_that_disagrees_with_the_name`
    is reached only when the kind is KNOWN to be org-scoped, and an undecided
    noun is not known to be anything — so the honest answer is the one the
    payload gives.
    """
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        event = services.emit(
            name=THRESHOLD_CROSSED,
            tenant=tenant,
            payload={"meter": "tokens"},
            actor=owner_actor,
        )

    assert event.organization_id is None
    assert Event.objects.for_tenant(tenant).filter(pk=event.pk).count() == 1
    assert [line["event"] for line in structured(caplog)].count("events.emit.kind_undecided") == 1


def test_an_undecided_noun_naming_a_branch_that_does_not_resolve_is_still_refused(
    tenant: Tenant, owner_actor: Actor, nobody_decides_the_noun: None
) -> None:
    """The narrowing still fails closed. The amendment moved ONE refusal.

    `_subject_organization`'s own refusal — a key that names no organization in
    this tenant — is untouched, because it is a fact about the payload rather
    than about the declaration: NULL means tenant-wide, so a narrowing that
    cannot be resolved must not be stamped NULL whatever the noun is.
    """
    with pytest.raises(Invalid) as refused:
        services.emit(
            name=THRESHOLD_CROSSED,
            tenant=tenant,
            payload={"organization_id": str(uuid4())},
            actor=owner_actor,
        )

    assert "organization_id" in refused.value.errors
    assert Event.objects.for_tenant(tenant).filter(name=THRESHOLD_CROSSED).count() == 0


# --- the static class and the runtime census are one population --------------


def test_rule_59s_undecided_class_walks_the_same_names_the_census_does() -> None:
    """Class 3's population IS `introspect.events`, and a drift is a blind rule.

    The amendment moved the refusal from `emit()` to the GATE, which makes the
    gate's population the thing that has to be right: a static walk that missed
    an app's `events.py` would go green over a noun the socket silently drops
    forever, and the runtime census would be the only witness left — after the
    frames stopped. So the two lists are compared, here, where both are
    reachable.

    `quality.checks` is reached through `importlib` and not with a plain
    `from quality.checks import …`: the codified idiom in
    `apps/usage/tests/test_authz_sweep.py` and `apps/core/tests/test_audit_rule_seam.py`,
    for the reason both give — a direct import under `apps/` drags the whole
    `quality/` tree into mypy `--strict` for the first time.

    The gate's own `declared_names` FLOOR is the other half and the stronger
    one: it refuses an unbound walk (exit 2) rather than reporting a clean
    nothing. This pins that the two walks see the same names; the floor pins
    that the static one sees any at all.
    """
    import importlib
    from pathlib import Path

    from apps.core.management.commands.introspect import _events_payload

    checks = importlib.import_module("quality.checks")
    root = Path(__file__).resolve().parents[3]

    static = {name for _app, _const, name, _line in checks._event_name_constants(root)}  # noqa: SLF001
    census = {str(entry["name"]) for entry in _events_payload()}

    assert static == census, {
        "declared in an events.py the census does not publish": sorted(static - census),
        "published by the census the static walk does not see": sorted(census - static),
    }
