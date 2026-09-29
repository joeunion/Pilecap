"""The family's refusals: `Blocked`, its two archive codes, `archived`, and `wire_extra`.

`wire_refusal` is still the only composer; what is proved here is that a
refusal with something STRUCTURED to say says it beside the four common keys —
once, for both doors — and that a raise site can never rewrite one of the four.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.core.exceptions import (
    REFUSALS,
    ArchiveBlocked,
    Archived,
    Blocker,
    Conflict,
    RestoreBlocked,
    refusal_message,
    wire_refusal,
)

HELD = Blocker(
    noun="widget",
    door="route:widget-list?policy=019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d40",
    label="Move or archive the widgets that name this policy first",
)


def test_a_blocked_archive_carries_noun_and_blocking_beside_the_four() -> None:
    body = wire_refusal(
        ArchiveBlocked("Still named by live widgets.", noun="widget_policy", blocking=(HELD,))
    )

    assert body == {
        "detail": "Still named by live widgets.",
        "code": "archive_blocked",
        "remedies": [{"label": HELD.label, "destination": HELD.door}],
        "noun": "widget_policy",
        "blocking": [{"noun": "widget", "door": HELD.door}],
    }
    # The machine door's one line renders from the same body.
    assert refusal_message(body).startswith("archive_blocked: Still named by live widgets.")


def test_a_blocked_restore_is_its_own_code() -> None:
    body = wire_refusal(RestoreBlocked(noun="widget", blocking=(HELD,)))
    assert body["code"] == "restore_blocked"
    assert body["noun"] == "widget"
    assert body["blocking"] == [{"noun": "widget", "door": HELD.door}]


def test_an_archived_row_names_its_restore_door() -> None:
    body = wire_refusal(Archived(noun="widget"))
    assert body["code"] == "archived"
    assert body["noun"] == "widget"
    assert body["remedies"] == [
        {"label": "Restore it first", "destination": "route:widget-restore"}
    ]


@pytest.mark.parametrize("key", ["detail", "code", "errors", "remedies"])
def test_a_wire_extra_key_colliding_with_the_four_is_refused_at_raise(key: str) -> None:
    refusal = Conflict("x")
    with pytest.raises(ValueError, match=f"may not redefine {key}"):
        refusal.wire_extra = {key: "rewritten", "fine": 1}
    # Nothing half-landed: the refusal still composes the four untouched.
    assert wire_refusal(refusal) == {
        "detail": "x",
        "code": "conflict",
        "remedies": wire_refusal(Conflict("x"))["remedies"],
    }


def test_a_block_with_nothing_named_is_refused() -> None:
    with pytest.raises(ValueError, match="names its blocking children"):
        ArchiveBlocked(noun="widget", blocking=())
    with pytest.raises(ValueError, match="kind the verb was asked of"):
        ArchiveBlocked(noun="Widget Policy", blocking=(HELD,))


@pytest.mark.parametrize("code", ["archive_blocked", "restore_blocked", "archived"])
def test_the_three_codes_are_registered_409_with_a_fact_and_remedies(code: str) -> None:
    refusal = REFUSALS[code]
    assert refusal.status == 409
    assert refusal.fact.strip()
    assert refusal.remedies
    assert refusal.boundary == "service"


def test_introspect_lists_the_three_codes() -> None:
    out = StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())
    rows = {row["code"]: row for row in payload["refusals"]}
    for code in ("archive_blocked", "restore_blocked", "archived"):
        assert rows[code]["status"] == 409
        assert rows[code]["fact"]
        assert rows[code]["remedies"]
