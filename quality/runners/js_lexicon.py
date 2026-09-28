"""The lexicon, and the label census over the copy modules — the runner half. (patterns.md §21)

    python3 quality/runners/js_lexicon.py <root> [<root> …]

THE CLOSED QUESTION: is every LABEL a copy module writes a row of the lexicon?
One word per thing, everywhere: two screens labelling one act are two chances
to spell it differently, and a word a builder composed on the day is a word
nobody chose. The lexicon — `frontend/src/copy/lexicon.ts`, one `LEXICON`
array of strings — is the product's closed set of labels; a rename is one line
there and every copy module that spells the old word goes red.

WHAT A LABEL IS, closed: a string literal that is the value of a key named
`label`, `act`, `title`, `heading` or `dismiss`, or of a camel-cased key ending
in `Label`, `Act`, `Title` or `Heading` (`emptyLabel`, `saveAct`), in a module
under `frontend/src/copy/` (the lexicon itself, tests and stories aside). It
must equal a row VERBATIM — the case and the punctuation are the word. A
sentence (`detail`, a remedy, a band's line) sits under any other key and is
not a label; a label reached through a reference or computed at run time is not
read.

And the lexicon's own form: it exists, it declares a `LEXICON` array, and no
row appears twice.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _source  # noqa: E402

LEXICON = "frontend/src/copy/lexicon.ts"
COPY = ("frontend", "src", "copy")
LABEL_KEYS = frozenset({"label", "act", "title", "heading", "dismiss"})
LABEL_SUFFIX = re.compile(r"[a-z0-9](Label|Act|Title|Heading)$")
DECLARATION = re.compile(r"\bLEXICON\b[^=\n]*=\s*\[")


def is_label_key(key: str | None) -> bool:
    return key is not None and (key in LABEL_KEYS or LABEL_SUFFIX.search(key) is not None)


def lexicon_rows(src: _source.Source) -> list[tuple[str, int]] | None:
    m = DECLARATION.search(src.blank)
    if m is None:
        return None
    start = m.end() - 1
    depth = 0
    end = len(src.blank)
    for i in range(start, len(src.blank)):
        if src.blank[i] == "[":
            depth += 1
        elif src.blank[i] == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    return [
        (lit.value, lit.line)
        for lit in src.literals
        if start < lit.start < end and not lit.computed
    ]


def main(argv: list[str]) -> int:
    findings: list[dict] = []
    table = Path(LEXICON)
    lexicon = _source.read(table) if table.is_file() else None
    rows: dict[str, int] = {}
    declared = False
    if lexicon is None:
        findings.append(
            {
                "path": LEXICON,
                "line": 1,
                "msg": (
                    f"the lexicon `{LEXICON}` is not in this tree — every label a copy module "
                    "writes is a row of it (patterns.md §21: one word per thing, everywhere)"
                ),
                "klass": "lexicon-missing",
            }
        )
    else:
        read = lexicon_rows(lexicon)
        if read is None:
            findings.append(
                {
                    "path": LEXICON,
                    "line": 1,
                    "msg": (
                        "the lexicon declares no `LEXICON` array of strings — nothing can "
                        "be a row of it"
                    ),
                    "klass": "lexicon-missing",
                }
            )
        else:
            declared = True
            for word, line in read:
                if word in rows:
                    findings.append(
                        {
                            "path": LEXICON,
                            "line": line,
                            "msg": (
                                f"`{word}` is a row twice (the first is line {rows[word]}) "
                                "— one word, one row"
                            ),
                            "klass": "lexicon-duplicate",
                        }
                    )
                    continue
                rows[word] = line

    modules = [s for s in _source.scripts(argv, under=COPY) if Path(s.path).as_posix() != LEXICON]
    labels = 0
    for src in modules:
        for lit in src.literals:
            if lit.computed or _source.is_key(src, lit):
                continue
            key = _source.key_before(src, lit)
            if not is_label_key(key):
                continue
            labels += 1
            if lit.value in rows:
                continue
            findings.append(
                {
                    "path": src.path,
                    "line": lit.line,
                    "msg": (
                        f'the label `{key}: "{lit.value}"` is not a row of the lexicon '
                        f"(`{LEXICON}`) — a label is spent from the lexicon verbatim, never "
                        "composed on the day; add the row there if the word is the product's"
                    ),
                    "klass": "off-lexicon",
                }
            )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(modules) + (1 if lexicon is not None else 0),
                    "copy_modules": len(modules),
                    "lexicons": 1 if declared else 0,
                    "lexicon_rows": len(rows),
                    "labels": labels,
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
