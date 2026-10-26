"""Rule 63: every pattern-book entry names an instrument that exists."""

from __future__ import annotations

from pathlib import Path

from quality.checks._hub import CheckResult


def pattern_book_names_its_instruments(root: Path, rule: dict) -> CheckResult:
    """Rule 63. Every pattern-book entry names an instrument file that exists.

    THE READING IS `quality/pattern_book.py`'s, not this function's. That module
    is the one reader of the book and of the product's drawer beside it — the
    motion-ledger runner (rule 66) reads the same two files through it, as a
    subprocess, so the grammar lives once and this wrapper only turns its
    findings into the engine's. Imported here rather than at the top so a
    runner never has to drag this module's Django-shaped world in with it.
    """
    from quality import pattern_book

    out = CheckResult()
    found, counts = pattern_book.findings(root)
    for key, n in counts.items():
        out.count(key, n)
    # THE RATCHET KEYS ARE THE READER'S CLASSES, one each. Counted only when the
    # rule's `ratchets:` names exactly `pattern_book.CLASSES`, so a class the
    # reader grows without a key (a backlog nobody could record) and a key with
    # no class (a ceiling on nothing) both leave the floor unbound.
    keyed = {str(key) for key in (rule.get("ratchets") or {})}
    out.count("ratchet_classes_keyed", 1 if keyed == set(pattern_book.CLASSES) else 0)
    for finding in found:
        out.hit(finding.path, finding.line, finding.msg, klass=finding.klass)
    return out
