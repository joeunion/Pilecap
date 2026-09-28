"""Every size names a type role — the type scale, the runner half. (patterns.md §26)

    python3 quality/runners/js_type_scale.py <root> [<root> …]

THE CLOSED QUESTION: does every `font-size`, `letter-spacing` and `font`
shorthand under `frontend/src/` — in a stylesheet or in an inline style
literal — name a `--type-*` role? A literal that fits no role is a size a
builder chose on the day, and a book of such days is a face with fourteen
sizes and no scale. And NO HALF PIXEL: a fractional `px` anywhere in a size, a
tracking, or a `--type-*` token's own declaration renders differently on every
screen density, and is the tell of a value measured off a picture rather than
chosen from a scale.

Allowed without a role: the CSS-wide keywords (`inherit`, `initial`, `unset`,
`revert`, `revert-layer`) and `letter-spacing: normal` — none of them is a
size. A role is any `var(--type-…)`; which role a seat spends is the book's
entry, never this instrument's.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _css  # noqa: E402

JUDGED = frozenset({"font-size", "letter-spacing", "font"})
ROLE = re.compile(r"var\(\s*--type-[A-Za-z0-9-]+")
HALF_PIXEL = re.compile(r"(?<![\w.-])\d*\.\d+px\b")
ALLOWED = _css.KEYWORDS | {"normal"}


def main(argv: list[str]) -> int:
    sheets = _css.population(argv, JUDGED)
    findings: list[dict] = []
    judged = 0
    roles: set[str] = set()

    for sheet in sheets:
        for rule in sheet.rules:
            for decl in rule.decls:
                if not decl.prop.startswith("--type-"):
                    continue
                if sheet.in_tokens_layer:
                    roles.add(decl.prop)
                if HALF_PIXEL.search(decl.value):
                    findings.append(
                        {
                            "path": sheet.path,
                            "line": decl.line,
                            "msg": (
                                f"the type role `{decl.prop}` is declared as `{decl.value}` — a "
                                "half pixel. A fractional pixel renders differently at every "
                                "density; the role is a whole pixel or a rem."
                            ),
                            "klass": "half-pixel",
                        }
                    )
        for decl in _css.declarations(sheet):
            if decl.prop not in JUDGED:
                continue
            judged += 1
            value = decl.value.replace("!important", "").strip()
            if value.lower() in ALLOWED:
                continue
            if HALF_PIXEL.search(value) or (decl.value and ROLE.search(value) is None):
                half = HALF_PIXEL.search(value) is not None
                findings.append(
                    {
                        "path": sheet.path,
                        "line": decl.line,
                        "msg": (
                            f"`{decl.prop}: {decl.value}` "
                            + ("is a half pixel and " if half else "")
                            + "names no `--type-*` role — every size, tracking and font "
                            "shorthand spends a role from the type scale (patterns.md §26); a "
                            "literal that fits no role is a design finding, never a builder's "
                            "choice"
                        ),
                        "klass": "half-pixel" if half else "literal-size",
                    }
                )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(sheets),
                    "stylesheets": sum(1 for s in sheets if s.is_css),
                    "type_declarations": judged,
                    "type_roles": len(roles),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
