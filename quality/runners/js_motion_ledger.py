"""Every motion names a ledger token — the motion ledger, the runner half. (patterns.md §26)

    python3 quality/runners/js_motion_ledger.py <root> [<root> …]

TWO CLOSED QUESTIONS, and they fail in two directions:

1. **Does every motion name a `--motion-*` token?** Every `transition`,
   `animation` and their duration, delay and timing-function longhands under
   `frontend/src/` — in a stylesheet or an inline style literal — names a
   `var(--motion-…)` and carries no raw time (`200ms`, `.3s`) and no raw
   easing (`ease-out`, `cubic-bezier(…)`, `steps(…)`) outside one. `none` and
   the CSS-wide keywords move nothing and are silent. A raw motion is a moment
   somebody decided should move without the ledger hearing of it.
2. **Is the token set the ledger?** The `--motion-*` tokens a product declares
   in its tokens layer equal, by name, the rows of the motion ledger — every
   fenced `motion-ledger` block in the pattern book and in the product's drawer
   beside it, read through `quality/pattern_book.py`, the one reader of both.
   A token off the ledger is a motion nobody ruled on; a ledger row with no
   token is a ruling nothing can spend. A token is a ruling.

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
from quality.runners import _css  # noqa: E402

JUDGED = frozenset(
    {
        "transition",
        "transition-duration",
        "transition-delay",
        "transition-timing-function",
        "animation",
        "animation-duration",
        "animation-delay",
        "animation-timing-function",
    }
)
TOKEN = re.compile(r"var\(\s*--motion-[A-Za-z0-9-]+\s*(?:,[^)]*)?\)")
RAW = re.compile(
    r"(?<![\w.-])\d*\.?\d+m?s\b"
    r"|\b(?:ease|ease-in|ease-out|ease-in-out|linear|step-start|step-end)\b"
    r"|\b(?:cubic-bezier|steps|linear)\("
)
SILENT = _css.KEYWORDS | {"none"}


def main(argv: list[str]) -> int:
    sheets = _css.population(argv, JUDGED)
    findings: list[dict] = []
    judged = 0
    declared: dict[str, tuple[str, int]] = {}
    token_files: list[str] = []

    for sheet in sheets:
        if sheet.in_tokens_layer and sheet.is_css:
            token_files.append(sheet.path)
            for rule in sheet.rules:
                for decl in rule.decls:
                    if decl.prop.startswith("--motion-"):
                        declared.setdefault(decl.prop, (sheet.path, decl.line))
        for decl in _css.declarations(sheet):
            if decl.prop not in JUDGED:
                continue
            judged += 1
            value = decl.value.replace("!important", "").strip()
            if value.lower() in SILENT:
                continue
            outside = TOKEN.sub(" ", value)
            if TOKEN.search(value) and not RAW.search(outside):
                continue
            findings.append(
                {
                    "path": sheet.path,
                    "line": decl.line,
                    "msg": (
                        f"`{decl.prop}: {decl.value}` is a raw motion — every transition and "
                        "animation names a `--motion-*` token from the motion ledger and "
                        "carries no time or easing of its own (patterns.md §26); a motion "
                        "not on the ledger is not built"
                    ),
                    "klass": "raw-motion",
                }
            )

    book_read, ledger = pattern_book.ledger_tokens(Path.cwd())
    for name, (path, line) in sorted(declared.items()):
        if name in ledger:
            continue
        findings.append(
            {
                "path": path,
                "line": line,
                "msg": (
                    f"`{name}` is declared in the tokens layer and is on no motion-ledger row "
                    "— the token set equals the ledger by name; a token is a ruling, so a "
                    "token nobody ruled on is a motion nobody ruled on"
                ),
                "klass": "off-ledger",
            }
        )
    anchor = token_files[0] if token_files else "/".join(_css.TOKENS_LAYER)
    for name, (book, line) in sorted(ledger.items()):
        if name in declared:
            continue
        findings.append(
            {
                "path": anchor,
                "line": 1,
                "msg": (
                    f"the motion ledger names `{name}` ({book}:{line}) and no token in the "
                    "tokens layer declares it — a ruling nothing can spend; declare the token "
                    "or strike the row"
                ),
                "klass": "ledger-undeclared",
            }
        )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(sheets),
                    "stylesheets": sum(1 for s in sheets if s.is_css),
                    "motion_declarations": judged,
                    "ledger_books": 1 if book_read else 0,
                    "ledger_rows": len(ledger),
                    "motion_tokens": len(declared),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
