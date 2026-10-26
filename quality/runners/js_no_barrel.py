"""Barrel files are banned — the runner half. (fe-conventions §2)

    python3 quality/runners/js_no_barrel.py <root> [<root> …]

THE COLLISION FILE, and why an index re-export is the one this rule targets.
An `index.ts` that re-exports a directory is the `INSTALLED_APPS` of
JavaScript: one shared file every parallel rung adding a component or a
selector must edit, so every parallel rung collides in it — the exact reason
this template registers Django apps by discovery instead of a hand-edited
list. Banning the shape rather than reviewing for it is what lets frontend
rungs fan out at all (fe-conventions §2).

WHAT COUNTS: a file whose STEM is `index` (`index.ts`, `index.tsx`, …) that
carries a line-level re-export — `export * from '...'` or
`export { X, Y } from '...'` (which also matches `export { default } from
'...'`). A file that merely happens to be NAMED index but exports its own
local declarations (`export const X = ...`) is not a barrel and is the
rule's own negative.

WHY THIS RUNNER CANNOT REPEAT RULE 50'S MISTAKE (found when the
scaffold merged — a name-based scan matched a framework's own vocabulary).
This rule keys on a FILENAME (`index.*`) plus a fixed RE-EXPORT SYNTAX marker
— never an English word in an identifier — so nothing a library or a
framework names collides with it.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _kindscope  # noqa: E402

SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

INDEX_STEM = "index"

#: `export * from '...'` or `export { A, B as C } from '...'` — the re-export
#: shape, whatever it names. Deliberately not distinguishing `default` from a
#: named re-export: both create the same collision file.
REEXPORT = re.compile(r"""^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+(['"])[^'"]+\1""")


def findings_in(path: Path) -> list[dict]:
    if path.stem != INDEX_STEM:
        return []
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    found: list[dict] = []
    for lineno, text in enumerate(lines, start=1):
        if REEXPORT.match(text):
            found.append(
                {
                    "path": str(path),
                    "line": lineno,
                    "msg": (
                        f"`{path.name}` re-exports a directory — a barrel is the "
                        "`INSTALLED_APPS` of JavaScript: one shared file every parallel rung "
                        "must edit. Import from the module that defines the thing instead"
                    ),
                    "klass": "barrel",
                }
            )
    return found


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv]
    findings: list[dict] = []
    scanned = 0
    for root in roots:
        for path in _kindscope.files_under(root, SUFFIXES):
            scanned += 1
            findings.extend(findings_in(path))
    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {"files_scanned": scanned, "barrels_flagged": len(findings)},
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
