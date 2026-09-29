"""`assert_four_doors` — one press, told four ways, held to the per-viewer contract.

Every adopter's door-parity module (house rule 46) asks the same three questions
of one press, and three hand copies of them existed before this helper (the
worked example's, comms', imports'); this is the one they call:

1. **One viewer, two doors, one byte string.** The REST body and the MCP
   `structuredContent` for the SAME viewer are equal, key for key and byte for
   byte (sorted keys, the door's own separators) — `allowed_acts` included,
   because it is that viewer's.
2. **No per-viewer field in a payload.** `Event.payload` carries none of
   `core.schemas.PER_VIEWER_FIELDS`: an event is broadcast, and a broadcast has
   no viewer.
3. **The payload is the row as ANY viewer sees it.** `event_payload(REST)` —
   the body minus its per-viewer fields — equals `Event.payload` byte for byte.

A SECOND viewer's body satisfies (3) against the same payload with a different
`allowed_acts`, which is the property that makes the field per-viewer; a caller
proves it by calling this twice — once per viewer, each with its own MCP answer.

Each failure names the first differing key, so a red run says where the doors
parted rather than printing two dicts to diff by eye. The socket frame and the
webhook body carry the event's envelope around the same payload
(`apps/events/activities.py`), so (2) and (3) are their answer too.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.core.schemas import PER_VIEWER_FIELDS

#: The spine's own key on every recorded payload (`events.emit` adds it): a
#: version for a subscriber to branch on, not a field of the row.
SPINE_KEYS = frozenset({"v"})


def canonical(body: Mapping[str, Any]) -> str:
    """One byte string per body: sorted keys, compact separators."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def first_difference(left: Mapping[str, Any], right: Mapping[str, Any]) -> str | None:
    """The first key (sorted) where two bodies part, or `None` when they are equal."""
    for key in sorted(set(left) | set(right)):
        if key not in left:
            return f"{key!r} is missing from the first"
        if key not in right:
            return f"{key!r} is missing from the second"
        if canonical({key: left[key]}) != canonical({key: right[key]}):
            return f"{key!r}: {left[key]!r} != {right[key]!r}"
    return None


def without_viewer(body: Mapping[str, Any]) -> dict[str, Any]:
    """The body as every viewer sees it: its per-viewer fields left out."""
    return {key: value for key, value in body.items() if key not in PER_VIEWER_FIELDS}


def assert_four_doors(
    *, rest: Mapping[str, Any], mcp: Mapping[str, Any], event_payload: Mapping[str, Any]
) -> None:
    """Hold one viewer's REST and MCP answers and the recorded event to one row.

    `event_payload` is `Event.payload` as recorded; its spine key `v` is set
    aside. Raises `AssertionError` naming the first key where two tellings part.
    """
    same_viewer = first_difference(rest, mcp)
    if same_viewer is not None:
        raise AssertionError(f"REST and MCP disagree for one viewer — {same_viewer}")
    payload = {key: value for key, value in event_payload.items() if key not in SPINE_KEYS}
    carried = sorted(PER_VIEWER_FIELDS & set(payload))
    if carried:
        raise AssertionError(
            f"a per-viewer key in a payload — {', '.join(carried)}: an event has no viewer"
        )
    row = first_difference(without_viewer(rest), payload)
    if row is not None:
        raise AssertionError(f"the payload is not the row the doors answered — {row}")
