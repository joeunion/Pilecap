"""A token has a consumer — BOTH directions, the runner half. (fe-conventions §5)

    python3 quality/runners/js_token_consumer.py <root> [<root> …]

TWO POPULATIONS, and they fail differently. A CSS custom property declared in
`frontend/src/tokens/**` (`--accent-loud: #ff4400;`) and never read anywhere
is a reader-less declaration — rule 30's class, the same shape as a
`next_attempt_at` field with no poller. The other direction is WORSE and
fails OPEN: a `var(--accent-loud)` consumed somewhere in the tree that no
token ever declared silently resolves to nothing, and an unset custom
property renders as the browser's own default — the UA-blue class, invisible
to any static check that only asked "was this named?" A chain that reaches a
component, a screen or an `app` route that consumes an undeclared name is
covered here exactly as one that reaches `tokens/` itself is: the consumer
population is the whole of `frontend/src/`, not only the tokens layer.

DECLARATION is scoped to `frontend/src/tokens/**` on purpose — that is the
layer fe-conventions names as owning "names, values, and the ONE stylesheet a
route may import" (§2). A `--local-var` a component sets on itself
dynamically (`style={{ '--progress': pct }}`) is parameterization, not a
design-system token, and is outside this rule's declared population (see
does_not_cover).

WHY THIS RUNNER CANNOT REPEAT RULE 50'S MISTAKE (found when the
scaffold merged — a name-based scan matched a framework's own vocabulary).
Unlike rule 50, this rule's marker is CSS custom-property SYNTAX (`--name:`
and `var(--name)`), not an English word — but a THIRD PARTY'S own custom
properties (Tailwind's `--tw-*`, Radix's `--radix-*`, a UI library's own
runtime tokens) carry that identical syntax while being declared in THEIR
CSS, never ours. Consuming one is legal and is excluded from the
consumed-undeclared population by its vendor prefix, named below, rather than
by loosening the syntax this rule watches.

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

#: Wider than the `js` kind's own suffixes on purpose: a token is CSS, and a
#: stylesheet is where most declarations and much consumption actually lives.
#: `.css` is outside `kind: js`'s declared suffix list (see does_not_cover) —
#: this runner's OWN population is wider than the valve-discovery walk's.
SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css")

TOKENS_LAYER = ("frontend", "src", "tokens")
SRC_ROOT = ("frontend", "src")

#: `--name: value;` — a custom-property declaration.
DECLARE = re.compile(r"--([A-Za-z][\w-]*)\s*:")
#: `var(--name)` or `var(--name, fallback)` — a custom-property read.
CONSUME = re.compile(r"var\(\s*--([A-Za-z][\w-]*)")

#: A third party's own runtime tokens. Declared in THEIR CSS, never ours — a
#: consumption here is legal by construction, excluded by prefix rather than
#: by loosening the syntax marker itself. Extend this list, never CONSUME's
#: pattern, the day a new library's prefix shows up as a false positive (the
#: fetch-`credentials` lesson, applied to this rule's own vocabulary).
VENDOR_PREFIXES = ("tw-", "radix-", "next-", "chakra-", "mantine-")


def _is_vendor_token(name: str) -> bool:
    return name.startswith(VENDOR_PREFIXES)


#: Suffixes on which `//` opens a comment. NOT `.css`, where `//` is not a
#: comment at all and treating it as one would silently drop the rest of a real
#: declaration line.
LINE_COMMENT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def strip_comments(lines: list[str], *, line_comments: bool) -> list[str]:
    """The same lines with every comment span blanked, LINE NUMBERING PRESERVED.

    A STYLESHEET'S OWN DOCUMENTATION IS NOT A POPULATION (RDF-1). This runner's
    two markers are CSS syntax, and CSS syntax is exactly what a stylesheet's
    prose quotes when it explains itself: `tokens.css` opens by teaching the
    very rule this runner enforces — "a `var(--accent-loud)` nobody declared
    resolves to nothing at all" — and the unstripped scan read that sentence as
    a consumption, reporting the scaffold's own teaching text as a fail-open
    defect. A rule tripped by the documentation of itself is measuring the wrong
    thing, and it fails in the direction that trains people to ignore it.

    Comments are stripped rather than the markers narrowed, for rule 50's
    reason recorded in this module's header: the marker is right, the
    POPULATION was wrong. `/* … */` is a comment in CSS and in JS/TS alike and
    spans lines, so the block state carries across the list; `//` is a comment
    in JS/TS only and runs to end of line.

    DECLARED BLIND SPOT: string literals are not parsed, so a `"/*"` inside a
    JS string opens a comment span this stripper honours. Erring here drops
    text from BOTH populations at once, which cannot invent a finding — it can
    only hide one — and no file in this template's scaffold carries the shape.
    """
    out: list[str] = []
    in_block = False
    for text in lines:
        kept: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if in_block:
                close = text.find("*/", i)
                if close == -1:
                    break
                i = close + 2
                in_block = False
                continue
            if text.startswith("/*", i):
                in_block = True
                i += 2
                continue
            if line_comments and text.startswith("//", i):
                break
            kept.append(text[i])
            i += 1
        out.append("".join(kept))
    return out


def _under_tokens_layer(path: Path) -> bool:
    return path.parts[: len(TOKENS_LAYER)] == TOKENS_LAYER


def _under_src(path: Path) -> bool:
    return path.parts[: len(SRC_ROOT)] == SRC_ROOT


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv]
    files: list[Path] = []
    for root in roots:
        files.extend(_kindscope.files_under(root, SUFFIXES))

    #: name -> (path, line) of its FIRST declaration.
    declared: dict[str, tuple[str, int]] = {}
    #: name -> [(path, line), ...] every place it is consumed.
    consumed: dict[str, list[tuple[str, int]]] = {}
    scanned = 0

    for path in files:
        scanned += 1
        if not _under_src(path):
            continue
        try:
            raw = path.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        lines = strip_comments(raw, line_comments=path.suffix in LINE_COMMENT_SUFFIXES)
        for lineno, text in enumerate(lines, start=1):
            if _under_tokens_layer(path):
                for m in DECLARE.finditer(text):
                    name = m.group(1)
                    declared.setdefault(name, (str(path), lineno))
            for m in CONSUME.finditer(text):
                name = m.group(1)
                consumed.setdefault(name, []).append((str(path), lineno))

    findings: list[dict] = []

    # (1) DECLARED-UNREAD — rule 30's class.
    for name, (path, lineno) in sorted(declared.items()):
        if name not in consumed:
            findings.append(
                {
                    "path": path,
                    "line": lineno,
                    "msg": (
                        f"`--{name}` is declared in the tokens layer and consumed nowhere — a "
                        "reader-less token (rule 30's class)"
                    ),
                    "klass": "declared-unread",
                }
            )

    # (2) CONSUMED-UNDECLARED — the worse, fail-open class.
    for name, sites in sorted(consumed.items()):
        if name in declared or _is_vendor_token(name):
            continue
        for path, lineno in sites:
            findings.append(
                {
                    "path": path,
                    "line": lineno,
                    "msg": (
                        f"`var(--{name})` is read here but no token declares it — it resolves "
                        "to nothing at all, the browser-default class, and is WORSE than a "
                        "reader-less declaration because it fails open"
                    ),
                    "klass": "consumed-undeclared",
                }
            )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": scanned,
                    "declared_tokens": len(declared),
                    "consumed_tokens": len(consumed),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
