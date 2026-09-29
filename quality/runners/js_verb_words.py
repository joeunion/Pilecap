"""One word per verb, product-wide — the runner half. (patterns.md §20, §21)

    python3 quality/runners/js_verb_words.py <root> [<root> …]

THE CLOSED QUESTION: for every noun whose wire carries a family verb, does
that noun's copy module (`frontend/src/copy/**/<noun>.ts`, the noun in kebab
case) spell ANOTHER word for the verb? A noun that archives says *Archive*,
never *Delete* on one face and *Remove* on the next: the reader learns one
word per act, and a synonym is a second act the reader has to rule out.

THE RED WORDS are the design grammar's, per verb:

* archive — Delete · Remove · Trash · Retire · Deactivate · Discard · Hide ·
  Unarchive · Recover, anywhere in the noun's copy;
* move — Transfer · Reassign · Relocate, anywhere;
* duplicate — Copy · Clone, as labels; merge — Combine · Dedupe ·
  Consolidate, anywhere;
* update — Modify · Update, as labels; history — Activity · Log · Audit ·
  Timeline, as a title (a label or title key, house rule 72's grammar).

A WORD THE PRODUCT CHOSE IS NEVER RED: every word the code's verb table
spends (`frontend/src/screens/verbs.ts`, read through `js_verb_table.py`) —
a verb renamed once, product-wide, or a way back such as *Remove tag* — is
lifted out of a string before its words are read, and so is every phrase a
product declares in its drawer's fenced `verb-words` block, one per line
(read through `quality/pattern_book.py`).

THE WIRE is `js_verb_road.py`'s reading of `frontend/openapi.json` (a noun's
single verb doors and its bulk door's verbs), so the two runners cannot
disagree about which nouns carry which verbs.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality import pattern_book  # noqa: E402
from quality.runners import _source  # noqa: E402
from quality.runners import js_verb_road as _road  # noqa: E402
from quality.runners import js_verb_table as _table  # noqa: E402

COPY = ("frontend", "src", "copy")

#: verb -> (its red words, whether they are red only as a label or title).
RED: dict[str, tuple[tuple[str, ...], bool]] = {
    "archive": (
        (
            "Delete",
            "Remove",
            "Trash",
            "Retire",
            "Deactivate",
            "Discard",
            "Hide",
            "Unarchive",
            "Recover",
        ),
        False,
    ),
    "move": (("Transfer", "Reassign", "Relocate"), False),
    "duplicate": (("Copy", "Clone"), True),
    "merge": (("Combine", "Dedupe", "Consolidate"), False),
    "update": (("Modify", "Update"), True),
    "history": (("Activity", "Log", "Audit", "Timeline"), True),
}
#: A verb the wire carries lends its red list to the verb its road pairs it with.
ALIASES = {"restore": "archive"}
LABEL_KEYS = ("label", "act", "title", "heading", "dismiss")
LABEL_SUFFIXES = ("Label", "Act", "Title", "Heading")


def _is_label(src: _source.Source, lit: _source.Literal) -> bool:
    key = _source.key_before(src, lit)
    return key is not None and (key in LABEL_KEYS or key.endswith(LABEL_SUFFIXES))


def main(argv: list[str]) -> int:
    root = Path.cwd()
    findings: list[dict] = []
    doors, bulk, read = _road.wire(root)
    carried: dict[str, set[str]] = {}
    for noun, verbs in doors.items():
        carried.setdefault(noun, set()).update(ALIASES.get(verb, verb) for verb in verbs)
    for noun, verbs in bulk.items():
        carried.setdefault(noun, set()).update(ALIASES.get(verb, verb) for verb in verbs)
    chosen = sorted(
        _table.family_words(root)
        | {
            text
            for _rel, _line, text in pattern_book.fenced_lines(root, pattern_book.VERB_WORDS_FENCE)
        },
        key=len,
        reverse=True,
    )
    modules = [src for src in _source.scripts(argv, under=COPY) if Path(src.path).stem in carried]
    judged = 0

    for src in modules:
        noun = Path(src.path).stem
        lists = [(verb, *RED[verb]) for verb in sorted(carried[noun]) if verb in RED]
        for lit in src.literals:
            if lit.computed or _source.is_key(src, lit) or _source.is_specifier(src, lit):
                continue
            judged += 1
            text = lit.value
            for phrase in chosen:
                text = re.sub(rf"(?<![\w]){re.escape(phrase)}(?![\w])", " ", text)
            label = _is_label(src, lit)
            for verb, words, labels_only in lists:
                if labels_only and not label:
                    continue
                for word in words:
                    if re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", text, re.IGNORECASE):
                        findings.append(
                            {
                                "path": src.path,
                                "line": lit.line,
                                "msg": (
                                    f"*{word}* in the `{noun}` copy is another word for `{verb}` — "
                                    f"`{noun}`'s wire carries the {verb} door, and a noun says one "
                                    "word per act, product-wide (the verb table's); a phrase that "
                                    "only looks like a synonym goes in the drawer's `verb-words` "
                                    "block"
                                ),
                                "klass": "synonym",
                            }
                        )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(modules) + int(read),
                    "documents": int(read),
                    "copy_modules": len(modules),
                    "strings": judged,
                    "family_words": len(chosen),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
