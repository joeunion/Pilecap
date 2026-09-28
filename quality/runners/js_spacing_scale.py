"""Every gap is on the scale — the spacing scale, the runner half. (patterns.md §26)

    python3 quality/runners/js_spacing_scale.py <root> [<root> …]

THE CLOSED QUESTION: is every `gap`, `row-gap`, `column-gap`, `padding` and
`margin` (and every side and logical twin of the last two) under
`frontend/src/` — in a stylesheet or an inline style literal — made only of
steps on the scale? A step is `0`, `auto`, a CSS-wide keyword, or a
`var(--space-…)` token, alone or inside `calc()`/`min()`/`max()`/`clamp()`
beside unitless numbers (a negative step is `calc(-1 * var(--space-2))`). A
`10px` is a gap a builder chose on the day; ninety of them are a face nobody
can re-space. The scale itself is the `--space-*` tokens a product declares in
its tokens layer, and which step a seat spends is the book's entry.

Geometry that is not spacing — the act floor, a sheet's edge, a border — is
not judged here, and a custom property that is not a `--space-*` step does not
become one by being a variable: `padding: var(--gutter)` is off the scale.

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

_SIDES = (
    "",
    "-top",
    "-right",
    "-bottom",
    "-left",
    "-block",
    "-inline",
    "-block-start",
    "-block-end",
    "-inline-start",
    "-inline-end",
)
JUDGED = frozenset(
    {"gap", "row-gap", "column-gap"}
    | {f"padding{side}" for side in _SIDES}
    | {f"margin{side}" for side in _SIDES}
)
STEP = re.compile(r"^var\(\s*--space-[A-Za-z0-9-]+\s*\)$")
_STEP_ANYWHERE = re.compile(r"var\(\s*--space-[A-Za-z0-9-]+\s*\)")
_MATH = re.compile(r"^(calc|min|max|clamp)\((.*)\)$", re.S)
_UNITLESS = re.compile(r"^-?\d*\.?\d+$")


def _on_scale(token: str) -> bool:
    if token in ("0", "auto", "!important") or token.lower() in _css.KEYWORDS:
        return True
    if STEP.match(token):
        return True
    math = _MATH.match(token)
    if math:
        inner = _STEP_ANYWHERE.sub(" ", math.group(2))
        for part in re.split(r"[\s,*/+()-]+", inner):
            if part and not _UNITLESS.match(part) and part not in ("calc",):
                return False
        return _STEP_ANYWHERE.search(math.group(2)) is not None or inner.strip() in ("", "0")
    return False


def main(argv: list[str]) -> int:
    sheets = _css.population(argv, JUDGED)
    findings: list[dict] = []
    judged = 0
    steps: set[str] = set()

    for sheet in sheets:
        if sheet.in_tokens_layer:
            for rule in sheet.rules:
                steps.update(d.prop for d in rule.decls if d.prop.startswith("--space-"))
        for decl in _css.declarations(sheet):
            if decl.prop not in JUDGED:
                continue
            judged += 1
            off = [t for t in _css.value_tokens(decl.value) if not _on_scale(t)]
            if not off:
                continue
            findings.append(
                {
                    "path": sheet.path,
                    "line": decl.line,
                    "msg": (
                        f"`{decl.prop}: {decl.value}` is off the spacing scale — "
                        + ", ".join(f"`{t}`" for t in off)
                        + " is not `0`, `auto` or a `--space-*` step; every gap, padding "
                        "and margin spends a step from the scale (patterns.md §26)"
                    ),
                    "klass": "off-scale",
                }
            )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(sheets),
                    "stylesheets": sum(1 for s in sheets if s.is_css),
                    "spacing_declarations": judged,
                    "space_steps": len(steps),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
