"""The book's verb table and the family's roads, censused against each other.

Two tables name the noun-verb family: the design book's fenced `verb-table`
(`docs/product/design/patterns.md`, DESIGN's — the words a face presses) and
`apps.core.verbs.ROADS` (what house rule 74 reads — the doors a marker demands).
They differ, and until now nothing said so: the book has rows the roads have no
entry for and the roads have entries the book has no row for. Neither side is
made to equal the other here; each difference is RECORDED below with its reason,
and the census pins that the two sets differ by exactly the records — a verb
joining either side, or a record going stale, fails by name.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.core.verbs import ROADS

BOOK = Path(__file__).resolve().parents[3] / "docs" / "product" / "design" / "patterns.md"

#: Book verbs with no road, and why each has none.
BOOK_ONLY: dict[str, str] = {
    "update": (
        "a CRUD door every editable noun has; the road that governs it is `version` "
        "(its body's `version`), which the book words as this press"
    ),
    "restore": "archive's second half — the archive road's routes are (archive, restore)",
    "attach": (
        "an `attachments` declaration read by the three owner apps (notes, files, tags); "
        "it demands no door on the noun itself, so there is no road for rule 74 to read"
    ),
    "import": (
        "an `importers.py` module the imports app discovers; its demand — the noun's "
        "create road — is not a marker on a model, so there is no road for rule 74 to read"
    ),
}

#: Roads with no book row, and why each has none.
ROADS_ONLY: dict[str, str] = {
    "version": "the update press's guard, not a press of its own — the book words it as `update`",
    "bulk": "a selection's one door; whether the book gains its row is DESIGN's question, asked",
}


def book_verbs() -> set[str]:
    """The verb column of the book's fenced `verb-table` — its FIRST field, `# verb | …`."""
    text = BOOK.read_text(encoding="utf-8")
    block = re.search(r"^```verb-table\n(.*?)^```", text, flags=re.MULTILINE | re.DOTALL)
    assert block is not None, f"{BOOK}: no fenced verb-table block"
    rows = [line for line in block.group(1).splitlines() if line.strip()]
    header = [cell.strip() for cell in rows[0].lstrip("#").split("|")]
    assert header[0] == "verb", header
    return {row.split("|")[0].strip() for row in rows[1:] if not row.startswith("#")}


def test_the_book_and_the_roads_differ_by_exactly_the_records() -> None:
    book = book_verbs()
    roads = set(ROADS)
    print(f"book-only (recorded): {sorted(BOOK_ONLY)}")
    print(f"roads-only (recorded): {sorted(ROADS_ONLY)}")
    assert book - set(BOOK_ONLY) == roads - set(ROADS_ONLY)
    assert set(BOOK_ONLY) <= book, "a book-only record names a verb the book no longer has"
    assert set(ROADS_ONLY) <= roads, "a roads-only record names a road that no longer exists"
    assert not set(BOOK_ONLY) & roads, "a recorded book-only verb has since become a road"
    assert not set(ROADS_ONLY) & book, "a recorded roads-only verb has since gained a book row"
