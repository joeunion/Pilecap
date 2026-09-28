"""One dialog primitive, and no dismiss word in its foot — the runner half. (patterns.md §1)

    python3 quality/runners/js_one_dialog.py <root> [<root> …]

TWO CLOSED QUESTIONS about the one floating surface.

1. **Is every dialog the primitive?** A `<dialog>` element, a
   `role="dialog"` / `role="alertdialog"` (as a JSX attribute or an object
   key), or a `createElement("dialog")` anywhere under `frontend/src/` except
   `frontend/src/primitives/dialog.tsx` is a second sheet — a second head, a
   second dismiss, a second way to trap focus, and the day the two disagree the
   reader learns two floating surfaces. Every sheet in a product renders
   through the primitive.

2. **Is the foot acts only?** The book's sheet has its ONE dismiss in the head;
   a foot carries the sheet's acts and nothing else, so *Close*, *Cancel*,
   *Done* and *Dismiss* never appear in one. A foot is read in two spellings:
   the primitive's `foot={…}` prop wherever a sheet is opened, and a
   `<footer>…</footer>` in a module that draws a dialog. Inside it, the words
   are read from JSX text, string literals, and a copy key named for one of
   them (`COPY.cancel`) — a `.close()` CALL is a method, not a word.

THE PRIMITIVE IS A POPULATION OF ONE, and it is floored: the file must exist and
draw a `<dialog>`, or the first question has nothing to compare against and the
rule could pass by scanning a tree with no primitive in it.

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

PRIMITIVE = "frontend/src/primitives/dialog.tsx"

DIALOG_TAG = re.compile(r"<dialog(?![\w-])")
ROLE = re.compile(r"\brole\s*(?:=\s*\{?|:)\s*([\"'`])(alertdialog|dialog)\1")
CREATE = re.compile(r"createElement\(\s*([\"'`])dialog\1")
DRAWS_DIALOG = re.compile(r"<(?:dialog|Dialog)(?![\w-])")
FOOT_PROP = re.compile(r"(?<![\w$.-])foot\s*=\s*\{")
FOOTER_OPEN = re.compile(r"<footer(?![\w-])[^>]*>")
FOOTER_CLOSE = re.compile(r"</footer\s*>")
JSX_TEXT = re.compile(r">([^<>{}]*)<")
WORD = re.compile(r"\b(close|cancel|done|dismiss)\b", re.IGNORECASE)
MEMBER = re.compile(r"\.(close|cancel|done|dismiss)\b(?!\s*\()", re.IGNORECASE)

SECOND = (
    "is a second dialog — every sheet renders through `frontend/src/primitives/dialog.tsx` "
    "(patterns.md §1): one head, one dismiss, one focus trap, so the reader learns one "
    "floating surface"
)
FOOT = (
    "sits in a dialog foot — the sheet's one dismiss is in its head, and a foot carries acts "
    "only (patterns.md §1: never Close · Cancel · Done in a foot)"
)


def foot_regions(src: _source.Source) -> list[tuple[int, int]]:
    """(start, end) offsets in `src.code` of every dialog foot the file writes."""
    regions: list[tuple[int, int]] = []
    for m in FOOT_PROP.finditer(src.blank):
        brace = m.end() - 1
        regions.append((brace, _source.balanced(src.blank, brace)))
    if DRAWS_DIALOG.search(src.blank):
        for m in FOOTER_OPEN.finditer(src.blank):
            close = FOOTER_CLOSE.search(src.blank, m.end())
            regions.append((m.end(), close.start() if close else len(src.blank)))
    return regions


def main(argv: list[str]) -> int:
    findings: list[dict] = []
    scripts = _source.scripts(argv)
    primitives = 0

    for src in scripts:
        is_primitive = Path(src.path).as_posix() == PRIMITIVE
        if is_primitive and DIALOG_TAG.search(src.blank):
            primitives += 1
        if not is_primitive:
            for pattern, text, what in (
                (DIALOG_TAG, src.blank, "a `<dialog>` element"),
                (ROLE, src.code, "a `role` of dialog"),
                (CREATE, src.code, 'a `createElement("dialog")`'),
            ):
                for m in pattern.finditer(text):
                    findings.append(
                        {
                            "path": src.path,
                            "line": src.line_of(m.start()),
                            "msg": f"{what} outside the primitive {SECOND}",
                            "klass": "second-dialog",
                        }
                    )
        seen: set[tuple[int, str]] = set()
        for start, end in foot_regions(src):
            hits: list[tuple[int, str]] = []
            region = src.code[start:end]
            for m in JSX_TEXT.finditer(region):
                for w in WORD.finditer(m.group(1)):
                    hits.append((start + m.start(1) + w.start(), w.group(1)))
            for lit in src.literals:
                if start <= lit.start < end:
                    for w in WORD.finditer(lit.value):
                        hits.append((lit.start, w.group(1)))
            for m in MEMBER.finditer(src.blank[start:end]):
                hits.append((start + m.start(), f"{m.group(1)} (a copy key)"))
            for at, word in hits:
                line = src.line_of(at)
                if (line, word.lower()) in seen:
                    continue
                seen.add((line, word.lower()))
                findings.append(
                    {
                        "path": src.path,
                        "line": line,
                        "msg": f"`{word}` {FOOT}",
                        "klass": "foot-word",
                    }
                )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {"files_scanned": len(scripts), "dialog_primitives": primitives},
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
