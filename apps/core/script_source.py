"""The script scanner: one face source read once, comments blanked, strings and line numbers kept.

The image carries no `quality/`, so this twin of `quality/runners/_source.py` is pinned by test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Literal:
    """One string literal: its span in the text, its quote, its value, its line."""

    start: int
    end: int
    quote: str
    value: str
    line: int
    computed: bool = False


@dataclass
class Source:
    """One script: raw, comments blanked, comments and strings blanked, and its literals."""

    path: str
    raw: str
    code: str
    blank: str
    literals: list[Literal] = field(default_factory=list)

    def line_of(self, offset: int) -> int:
        return self.raw.count("\n", 0, offset) + 1


def scan(raw: str) -> tuple[str, str, list[Literal]]:
    """(code, blank, literals) — see `Source`. Newlines are kept everywhere."""
    code: list[str] = []
    blank: list[str] = []
    lits: list[Literal] = []
    i, n = 0, len(raw)
    line = 1

    def keep(ch: str) -> None:
        code.append(ch)
        blank.append(ch)

    def hide(ch: str, *, in_code: bool) -> None:
        filler = "\n" if ch == "\n" else " "
        code.append(ch if in_code else filler)
        blank.append(filler)

    while i < n:
        ch = raw[i]
        if raw.startswith("//", i):
            while i < n and raw[i] != "\n":
                hide(raw[i], in_code=False)
                i += 1
            continue
        if raw.startswith("/*", i):
            end = raw.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for c in raw[i:end]:
                hide(c, in_code=False)
                if c == "\n":
                    line += 1
            i = end
            continue
        if ch in "\"'":
            start, start_line = i, line
            keep(ch)
            i += 1
            value: list[str] = []
            while i < n and raw[i] != ch and raw[i] != "\n":
                if raw[i] == "\\" and i + 1 < n and raw[i + 1] != "\n":
                    value.append(raw[i + 1])
                    hide(raw[i], in_code=True)
                    hide(raw[i + 1], in_code=True)
                    i += 2
                    continue
                value.append(raw[i])
                hide(raw[i], in_code=True)
                i += 1
            if i < n and raw[i] == ch:
                keep(ch)
                i += 1
            lits.append(Literal(start, i, ch, "".join(value), start_line))
            continue
        if ch == "`":
            start, start_line = i, line
            keep(ch)
            i += 1
            value = []
            computed = False
            while i < n and raw[i] != "`":
                if raw[i] == "\\" and i + 1 < n:
                    value.append(raw[i + 1])
                    for c in raw[i : i + 2]:
                        hide(c, in_code=True)
                        if c == "\n":
                            line += 1
                    i += 2
                    continue
                if raw.startswith("${", i):
                    computed = True
                    depth = 0
                    while i < n:
                        c = raw[i]
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                        keep(c)
                        if c == "\n":
                            line += 1
                        i += 1
                        if depth == 0:
                            break
                    value.append(" ")
                    continue
                value.append(raw[i])
                if raw[i] == "\n":
                    line += 1
                hide(raw[i], in_code=True)
                i += 1
            if i < n:
                keep("`")
                i += 1
            lits.append(Literal(start, i, "`", "".join(value), start_line, computed))
            continue
        keep(ch)
        if ch == "\n":
            line += 1
        i += 1
    return "".join(code), "".join(blank), lits


def read(path: Path) -> Source | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    code, blank, lits = scan(raw)
    return Source(str(path), raw, code, blank, lits)
