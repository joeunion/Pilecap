"""Every list a rule reads declares its reach: a product's by a drawer road, or the platform's."""

# does-not-cover: a rule that reads a list from somewhere other than `scope:` or `ALLOW_LIST_KEYS`.
# does-not-cover: whether the drawer road named for a `product` list actually reads its union.

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quality.engine.rules import ALLOW_LIST_KEYS
from quality.engine.world import LOCAL_KEYS
from quality.reason_floor import MIN_REASON

pytestmark = pytest.mark.drives("quality/rules.yaml", "quality/engine/rules.py")

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "quality/rules.yaml"
#: The drawer key through which a product extends a template rule's list.
EXTENSIONS = "scope_extensions"
REACHES = ("product", "platform")

#: The day the dated rows below were written; the rung that marks a list deletes its row.
KNOWN_SINCE = "2026-10-19"
#: Lists the drawer-reach rung opens; a row whose list is marked reds until it is deleted.
KNOWN_UNMARKED: dict[tuple[str, str], str] = {}


def lists() -> dict[tuple[str, str], dict[str, object]]:
    """(rule id, list key) → the rule, for every list (or dict of lists) a rule's scope reads."""
    doc = yaml.safe_load(RULES.read_text())
    out: dict[tuple[str, str], dict[str, object]] = {}
    for rule in doc["rules"]:
        for key, value in (rule.get("scope") or {}).items():
            listed = (
                isinstance(value, dict)
                and value
                and all(isinstance(v, list) for v in value.values())
            )
            if isinstance(value, list) or listed:
                out[(str(rule["id"]), str(key))] = rule
        for key in ALLOW_LIST_KEYS:
            if key in rule:
                out[(str(rule["id"]), key)] = rule
    return out


def judged(rule: dict[str, object], key: str) -> str | None:
    """Why the list's reach fails; None when it holds; `"unmarked"`: no mark, no drawer key."""
    reach = rule.get("reach")
    if not isinstance(reach, dict) or key not in reach:
        return None if key in LOCAL_KEYS else "unmarked"
    mark = reach[key]
    to = mark if isinstance(mark, str) else mark.get("to") if isinstance(mark, dict) else None
    if to not in REACHES:
        return f"reach is {to!r}, not one of {REACHES}"
    if to == "product":
        if key in LOCAL_KEYS or EXTENSIONS in LOCAL_KEYS:
            return None
        return f"`product`, and the drawer has no road for it (no `{key}` or `{EXTENSIONS}` key)"
    reason = " ".join(str(mark.get("reason") or "").split()) if isinstance(mark, dict) else ""
    if len(reason) < MIN_REASON:
        return f"`platform` needs `reason:` of {MIN_REASON}+ characters, has {reason!r}"
    return None


def test_every_list_a_rule_reads_declares_its_reach() -> None:
    bad = sorted(
        f"rule {rid} `{key}`: {why}"
        for (rid, key), rule in lists().items()
        if (why := judged(rule, key)) and (rid, key) not in KNOWN_UNMARKED
    )
    assert not bad, (
        "a rule's list says neither `reach: product` (a drawer road) nor `reach: platform`"
        f" with why — add `reach: {{<key>: {{to: platform, reason: …}}}}` to the rule: {bad}"
    )


def test_a_reach_mark_names_a_list_the_rule_reads() -> None:
    found = lists()
    doc = yaml.safe_load(RULES.read_text())
    dangling = sorted(
        f"rule {rule['id']} `{key}`"
        for rule in doc["rules"]
        for key in rule.get("reach") or {}
        if (str(rule["id"]), key) not in found
    )
    assert not dangling, f"a reach mark names no list its rule reads: {dangling}"


def test_a_known_unmarked_list_is_still_unmarked() -> None:
    found = lists()
    stale = sorted(
        f"rule {rid} `{key}`"
        for rid, key in KNOWN_UNMARKED
        if (rid, key) not in found or judged(found[(rid, key)], key) != "unmarked"
    )
    assert not stale, f"a row dated {KNOWN_SINCE} is marked now, or gone — delete its row: {stale}"
