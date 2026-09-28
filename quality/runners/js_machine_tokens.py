"""No machine token in a copy string — the runner half. (patterns.md §21)

    python3 quality/runners/js_machine_tokens.py <root> [<root> …]

THE CLOSED QUESTION: does any string a copy module hands a reader carry a word
the MACHINE speaks? A field name (`invoice_id`), an operation or a slug key
(`sign-in-form`, `widget-list`) or a raw id (thirty-two hex digits, a UUID) on a
face is the product's internal vocabulary reaching a person — the thing
`design-agreements.md` § 1 · 7 rules never happens — and a person cannot say it
back to anybody.

WHAT IS READ: every string literal VALUE in a module under `frontend/src/copy/`
(tests and stories aside) — the lexicon included, since its rows are what every
label spends. A literal in a KEY position (`"socket_closed": …`, `COPY["x"]`)
and a module specifier are machine words by position and are skipped; the
static parts of a template literal are read and its `${…}` parts are not.

THE TOKENS, closed:

* **snake** — a run of letters and digits joined by `_` (`invoice_id`,
  `READY_STATE`);
* **hex id** — thirty-two hex digits, or a UUID's 8-4-4-4-12;
* **kebab key** — a lower-case run joined by `-` that reads as a key and not as
  an English compound: three or more parts none of which is a small joining
  word (`sign-in-form`; `up-to-date` passes), or any length ending in a machine
  suffix (`-id`, `-uuid`, `-key`, `-slug`, `-url`, `-uri`, `-code`, `-ref`,
  `-pk`) or a url-name action (`-list`, `-detail`, `-create`, `-update`,
  `-delete`).

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

COPY = ("frontend", "src", "copy")

SNAKE = re.compile(r"(?<![\w-])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w-])")
UUID = re.compile(
    r"(?<![0-9A-Za-z-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Za-z-])"
)
HEX32 = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32}(?![0-9A-Za-z])")
KEBAB = re.compile(r"(?<![\w-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![\w-])")

JOINING = frozenset({"a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to"})
MACHINE_SUFFIX = frozenset(
    {
        "id",
        "uuid",
        "key",
        "slug",
        "url",
        "uri",
        "code",
        "ref",
        "pk",
        "list",
        "detail",
        "create",
        "update",
        "delete",
    }
)

WHY = (
    "a copy string hands a reader a word the machine speaks (patterns.md §21; "
    "design-agreements.md § 1 · 7) — say the thing in the reader's words, and keep the "
    "key where the code needs it"
)


def kebab_is_key(token: str) -> bool:
    parts = token.split("-")
    if parts[-1] in MACHINE_SUFFIX:
        return True
    return len(parts) >= 3 and not (JOINING & set(parts))


def tokens_in(value: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    spans: list[tuple[int, int]] = []
    for pattern, klass in ((UUID, "hex-id"), (HEX32, "hex-id")):
        for m in pattern.finditer(value):
            found.append((m.group(0), klass))
            spans.append(m.span())
    for m in SNAKE.finditer(value):
        found.append((m.group(0), "snake-token"))
    for m in KEBAB.finditer(value):
        if any(a <= m.start() < b for a, b in spans):
            continue
        if kebab_is_key(m.group(0)):
            found.append((m.group(0), "kebab-token"))
    return found


def main(argv: list[str]) -> int:
    findings: list[dict] = []
    modules = _source.scripts(argv, under=COPY)
    strings = 0
    for src in modules:
        for lit in src.literals:
            if _source.is_key(src, lit) or _source.is_specifier(src, lit):
                continue
            strings += 1
            for token, klass in tokens_in(lit.value):
                findings.append(
                    {
                        "path": src.path,
                        "line": lit.line,
                        "msg": f"`{token}` is a machine token in a copy string — {WHY}",
                        "klass": klass,
                    }
                )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(modules),
                    "copy_modules": len(modules),
                    "copy_strings": strings,
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
