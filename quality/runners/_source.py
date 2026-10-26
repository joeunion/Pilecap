"""The source-text reading the act, dialog, route and word runners share.

    from quality.runners import _source
    for src in _source.scripts(roots): ...

Rules 68-73 ask closed questions of the SCRIPT half of `frontend/src/` — JSX
attributes, element names, identifiers, object keys and string literals — and
this module reads that text once, so six runners cannot disagree about what a
comment, a string or a tag is. `_css.py` is the stylesheet half and is reused
for the two rules that also read stylesheets (68 and 69). No Node, no browser:
a static read, comments blanked and line numbers kept.

UNLIKE `_css.strip_comments`, THIS SCANNER KNOWS STRINGS: a `//` inside
`"https://…"` is not a comment here, and a quote inside a comment is not a
string. It walks code, line comments, block comments, the two quoted strings
and template literals (a `${…}` part is skipped by brace depth and marks the
literal as computed).

WHAT A STATIC READ CANNOT SEE, declared once for the six rules and repeated in
each rule's `does_not_cover`: a regular-expression literal holding a quote is
read as a string; JSX TEXT holding an apostrophe (`<p>Don't</p>`) opens a
string that runs to the end of its line, which can only HIDE what that line
holds, never invent it; a value computed at run time is not read; and a name
or a word assembled by a helper in another file is invisible.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import (
    _css,  # noqa: E402
    _kindscope,  # noqa: E402
)

SCRIPT_SUFFIXES = _css.SCRIPT_SUFFIXES
#: Test, story and spec modules exercise a face; they are not the face.
EXEMPT_INFIXES = (".test.", ".stories.", ".spec.")


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


def exempt(path: Path) -> bool:
    return any(infix in path.name for infix in EXEMPT_INFIXES)


def scripts(roots: list[str], *, under: tuple[str, ...] = _css.SRC_ROOT) -> list[Source]:
    """Every script under `under` (default `frontend/src/`), tests and stories aside."""
    out: list[Source] = []
    seen: set[Path] = set()
    for root in roots:
        for path in _kindscope.files_under(Path(root), _css.SUFFIXES, under=_css.SRC_ROOT):
            if path in seen or path.suffix not in SCRIPT_SUFFIXES or exempt(path):
                continue
            if path.parts[: len(under)] != under:
                continue
            seen.add(path)
            src = read(path)
            if src is not None:
                out.append(src)
    return out


def sheets(roots: list[str]) -> list[_css.Sheet]:
    """Every stylesheet under `frontend/src/`, read through `_css`."""
    return [s for s in _css.population(roots, frozenset()) if s.is_css]


# -- JSX ------------------------------------------------------------------------

_TAG_OPEN = re.compile(r"<([A-Za-z][\w.:-]*)")


@dataclass
class Tag:
    """One JSX opening tag: its name, where it starts, and its attribute text
    at brace depth 0 (brace contents blanked), offsets kept."""

    name: str
    start: int
    end: int
    attrs: str


def tags(src: Source) -> list[Tag]:
    """Every JSX-shaped opening tag in the string-blanked text."""
    text = src.blank
    out: list[Tag] = []
    for m in _TAG_OPEN.finditer(text):
        i = m.end()
        depth = 0
        attrs: list[str] = []
        while i < len(text):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}" and depth:
                depth -= 1
                attrs.append(" ")
                i += 1
                continue
            elif c == ">" and depth == 0:
                break
            elif c == "<" and depth == 0:
                break
            attrs.append(c if depth == 0 else ("\n" if c == "\n" else " "))
            i += 1
        out.append(Tag(m.group(1), m.start(), i, "".join(attrs)))
    return out


def balanced(text: str, open_at: int) -> int:
    """The offset just past the brace that closes the `{` at `open_at`."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


# -- words ----------------------------------------------------------------------

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def words(name: str) -> list[str]:
    """`LoadingSpinner` -> ['loading', 'spinner']; `is-toast_bar` -> ['is', 'toast', 'bar']."""
    out: list[str] = []
    for part in re.split(r"[-_./@:\s]+", name):
        out.extend(w.lower() for w in _CAMEL.findall(part))
    return out


def key_before(src: Source, lit: Literal) -> str | None:
    """The object key a literal is the value of (`key: "…"`), or None."""
    head = src.code[max(0, lit.start - 120) : lit.start]
    m = re.search(r"(?:(?<![\w$])([A-Za-z_$][\w$]*)|[\"']([^\"'\n]+)[\"'])\s*\??\s*:\s*$", head)
    if not m:
        return None
    return m.group(1) or m.group(2)


def is_key(src: Source, lit: Literal) -> bool:
    """A quoted object KEY (`"x": …`) or an index (`o["x"]`) — a machine word by position."""
    tail = src.code[lit.end : lit.end + 40]
    if re.match(r"\s*\??\s*:(?!:)", tail):
        return True
    head = src.code[max(0, lit.start - 40) : lit.start]
    return bool(re.search(r"\[\s*$", head) and re.match(r"\s*\]", tail))


def is_specifier(src: Source, lit: Literal) -> bool:
    """A module specifier: `from "…"`, `import "…"`, `import("…")`, `require("…")`."""
    head = src.code[max(0, lit.start - 40) : lit.start]
    return bool(re.search(r"(?:\bfrom|\bimport|\bimport\s*\(|\brequire\s*\()\s*$", head))
