"""The pattern book's drawer is read — one planted entry reaches rule 63.

The book the template ships is template-owned, so a product's own entries land
in the drawer beside it, and `quality/pattern_book.py` is the one reader of
both. This is the case the drawers table names for that row: it plants ONE
entry into a drawer under `tmp_path`, beside a minimal copy of the book, and
proves the reader judged it — the finding names the DRAWER's path, not the
book's, so a reader that stopped opening the drawer cannot pass.

WHAT THIS FILE DOES NOT TOUCH: the tree. The book and the drawer are built in
`tmp_path` and the reader is handed that root, because a test that wrote the
real drawer would move the working tree a concurrent gate's verdict is keyed
on. Reached through `importlib` for the reason `test_drawer_seam.py` gives: a
plain import of a `quality` module from `apps/` drags that tree into mypy's
`--strict` graph.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

_BOOK: Any = importlib.import_module("quality.pattern_book")

_ENTRY = """
### §90 · A planted entry

**Shape.** One band.
**Words.** One sentence.
**Placement.** Under the head.
**States.** Empty: none. Loading: none. Refused: none. Phone: one column.
**Ruling.** Row 1.
**Instrument.** `frontend/src/zzz_canary/never-written.test.tsx` (a file nobody wrote).
"""


def _tree(root: Path, *, drawer: str | None) -> None:
    book = root / _BOOK.BOOK
    book.parent.mkdir(parents=True)
    book.write_text("# The pattern book\n\nNo entries of its own in this copy.\n")
    if drawer is not None:
        (root / _BOOK.LOCAL_BOOK).write_text(drawer)


def test_the_pattern_book_drawer(tmp_path: Path) -> None:
    """One entry in the drawer is read, counted and judged against the tree."""
    _tree(tmp_path, drawer=None)
    before, before_counts = _BOOK.findings(tmp_path)
    assert before == []
    assert before_counts["books"] == 1
    assert before_counts["entries"] == 0

    (tmp_path / _BOOK.LOCAL_BOOK).write_text(_ENTRY)
    after, after_counts = _BOOK.findings(tmp_path)

    assert after_counts["books"] == 2
    assert after_counts["entries"] == 1
    assert [(f.path, f.klass) for f in after] == [(_BOOK.LOCAL_BOOK, "instrument-missing")]
    assert "never-written.test.tsx" in after[0].msg


def test_an_entry_whose_instrument_exists_is_silent_in_the_drawer(tmp_path: Path) -> None:
    """The control: the same entry, its instrument written, is no finding."""
    _tree(tmp_path, drawer=_ENTRY)
    written = tmp_path / "frontend/src/zzz_canary/never-written.test.tsx"
    written.parent.mkdir(parents=True)
    written.write_text("// the instrument\n")

    found, counts = _BOOK.findings(tmp_path)

    assert counts["entries"] == 1
    assert found == []


def test_a_tree_with_no_book_is_could_not_look_not_clean(tmp_path: Path) -> None:
    """No book at all is a finding naming the book — never an empty, clean read."""
    found, counts = _BOOK.findings(tmp_path)

    assert counts["books"] == 0
    assert [(f.path, f.klass) for f in found] == [(_BOOK.BOOK, "book")]
