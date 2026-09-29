"""The per-viewer contract's instruments: `event_payload`, `emit`'s refusal, `assert_four_doors`.

`allowed_acts` is a fact about (row, viewer). It rides the two viewer doors and
never a broadcast: `core.schemas.PER_VIEWER_FIELDS` is derived from `ActsOut`,
`event_payload()` is the one way a service builds a payload from an `Out`, and
`assert_four_doors` is the check every adopter's parity module calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.schemas import PER_VIEWER_FIELDS, ActsOut, ArchivedOut, event_payload
from apps.core.tests.doors import assert_four_doors


class _RowOut(ArchivedOut, ActsOut):
    """A row an adopter would answer."""

    name: str


def _body(acts: list[str]) -> dict[str, Any]:
    out = _RowOut(name="spares", allowed_acts=acts)
    return out.model_dump(mode="json")


def test_the_per_viewer_fields_are_derived_from_acts_out() -> None:
    assert frozenset(ActsOut.model_fields) == PER_VIEWER_FIELDS
    assert "allowed_acts" in PER_VIEWER_FIELDS


def test_event_payload_is_the_out_minus_every_per_viewer_field() -> None:
    out = _RowOut(name="spares", allowed_acts=["archive"])
    payload = event_payload(out)
    assert not PER_VIEWER_FIELDS & set(payload)
    assert payload == {k: v for k, v in out.model_dump(mode="json").items() if k != "allowed_acts"}


def test_a_viewer_s_acts_on_the_doors_and_none_in_the_payload_passes() -> None:
    """THE CONTRACT: the REST body carries this viewer's acts, the payload does not."""
    admin = _body(["update", "archive"])
    member = _body([])
    payload = {"v": 1, **event_payload(_RowOut(name="spares"))}
    assert_four_doors(rest=admin, mcp=dict(admin), event_payload=payload)
    # A second viewer: other acts, the same payload.
    assert_four_doors(rest=member, mcp=dict(member), event_payload=payload)
    assert admin["allowed_acts"] != member["allowed_acts"]


def test_a_per_viewer_key_in_the_payload_fails() -> None:
    admin = _body(["archive"])
    with pytest.raises(AssertionError, match="a per-viewer key in a payload"):
        assert_four_doors(rest=admin, mcp=dict(admin), event_payload={"v": 1, **admin})


def test_two_doors_disagreeing_for_one_viewer_fails_naming_the_key() -> None:
    admin = _body(["archive"])
    other = {**admin, "name": "other"}
    with pytest.raises(AssertionError, match="'name'"):
        assert_four_doors(rest=admin, mcp=other, event_payload=event_payload(_RowOut(name="x")))


def test_a_payload_that_is_not_the_row_fails_naming_the_key() -> None:
    admin = _body(["archive"])
    with pytest.raises(AssertionError, match="'name'"):
        assert_four_doors(
            rest=admin, mcp=dict(admin), event_payload=event_payload(_RowOut(name="else"))
        )


class _ChildOut(ActsOut):
    """A nested row with acts of its own."""

    label: str


class _ParentOut(ArchivedOut, ActsOut):
    """A row whose `Out` nests others."""

    name: str
    entries: list[_ChildOut]


def test_event_payload_strips_per_viewer_fields_at_any_depth() -> None:
    out = _ParentOut(
        name="spares",
        allowed_acts=["archive"],
        entries=[_ChildOut(label="a", allowed_acts=["delete"])],
    )
    payload = event_payload(out)
    assert "allowed_acts" not in payload
    assert payload["entries"] == [{"label": "a"}]
