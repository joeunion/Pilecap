"""The committed flat baseline IS what its own writer writes on this tree.

`apps/core/tests/flat_product_baseline.json` is DERIVED — its header carries
the command that made it (`_command`) and the tree it was made on
(`_baseline`). A document that its writer would no longer produce is a
document nobody re-derived: the census beside it (`test_resolution.py`) then
compares this tree against an older one and has to excuse the difference.

So this runs the writer's own function — `flat_product_census()` — in-process,
inside the test transaction, and diffs it against the committed document: the
population first (keys added, keys removed), then every cell. Any difference
prints the keys, and the remedy is the header's own command.

DOES NOT COVER: whether a moved cell is RIGHT — that is the census test's and
each app's sweep's question; this one says only that the document is current.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.core.tests.permissions_world import (
    BASELINE_COMMAND,
    BASELINE_SHA,
    flat_product_census,
)

DOCUMENT = Path(str(settings.BASE_DIR)) / "apps/core/tests/flat_product_baseline.json"


def _drift(committed: dict[str, Any], derived: dict[str, Any]) -> list[str]:
    before: dict[str, dict[str, bool]] = committed["answers"]
    after: dict[str, dict[str, bool]] = derived["answers"]
    lines = [f"added    {key}" for key in sorted(set(after) - set(before))]
    lines += [f"removed  {key}" for key in sorted(set(before) - set(after))]
    lines += [
        f"moved    {key} · {role}: {before[key].get(role)} -> {after[key].get(role)}"
        for key in sorted(set(before) & set(after))
        for role in sorted(set(before[key]) | set(after[key]))
        if before[key].get(role) != after[key].get(role)
    ]
    if committed.get("roles") != derived["roles"]:
        lines.append(f"roles    {committed.get('roles')} -> {derived['roles']}")
    return lines


def test_the_document_is_what_its_writer_writes_on_this_tree(db: None) -> None:
    committed = json.loads(DOCUMENT.read_text())
    drift = _drift(committed, flat_product_census())
    assert drift == [], (
        f"flat_product_baseline.json is not what its writer derives on this tree "
        f"({len(drift)} lines):\n    "
        + "\n    ".join(drift)
        + f"\n  Re-derive it with the header's own command: {BASELINE_COMMAND}"
    )


def test_the_header_names_its_writer_and_its_tree() -> None:
    """The provenance travels in the document, and it is the writer's own."""
    committed = json.loads(DOCUMENT.read_text())
    assert committed["_baseline"] == BASELINE_SHA
    assert committed["_command"] == BASELINE_COMMAND
    assert "write_flat_product_baseline" in committed["_command"]


def test_the_diff_names_an_added_a_removed_and_a_moved_key() -> None:
    """The canary: each shape of drift is printed, by key."""
    committed = {
        "roles": ["owner"],
        "answers": {"a.keep": {"owner": True}, "a.gone": {"owner": True}},
    }
    derived = {
        "roles": ["owner"],
        "answers": {"a.keep": {"owner": False}, "a.new": {"owner": True}},
    }
    assert _drift(committed, derived) == [
        "added    a.new",
        "removed  a.gone",
        "moved    a.keep · owner: True -> False",
    ]
    assert _drift(committed, committed) == []
