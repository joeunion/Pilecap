"""The source-text reading the four scale runners share — CSS rules and inline styles.

    from quality.runners import _css
    for sheet in _css.population(roots): ...

Rules 64-67 (the type scale, the spacing scale, the motion ledger, the focus
ring and the act floor) ask closed questions of the SAME two populations:
every declaration in a stylesheet under `frontend/src/`, and every literal an
inline `style={{ … }}` object hands a CSS property in a `.ts`/`.tsx` file
there. They are read once, here, so four runners cannot disagree about what a
declaration is. No Node, no browser: a static read of the text, in the shape
`js_token_consumer.py` already proved (comments stripped, line numbers kept).

WHAT A STATIC READ CANNOT SEE, declared once for all four rules and repeated in
each rule's `does_not_cover`: a value computed at run time (a variable, a
ternary, a template literal with `${…}` in it) is not judged; CSS nesting is
read flat (a nested rule's selector is not joined to its parent's); a `{`, `}`
or `;` inside a CSS string or `url(…)` confuses the block reader; a style
object split across files, or built by a helper, is invisible; and a string
literal containing `//` or `/*` in a `.ts`/`.tsx` file opens a comment span
the stripper honours (it can only HIDE a finding, never invent one — the trade
`js_token_consumer.py` already declares).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _kindscope  # noqa: E402

SRC_ROOT = ("frontend", "src")
TOKENS_LAYER = ("frontend", "src", "tokens")
SCRIPT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
SUFFIXES = (*SCRIPT_SUFFIXES, ".css")
KEYWORDS = frozenset({"inherit", "initial", "unset", "revert", "revert-layer"})


@dataclass
class Decl:
    prop: str
    value: str
    line: int


@dataclass
class Rule:
    selectors: list[str]
    line: int
    decls: list[Decl] = field(default_factory=list)


@dataclass
class Sheet:
    """One file: its path, and what it declares — as CSS rules or inline style literals."""

    path: str
    rules: list[Rule] = field(default_factory=list)
    inline: list[Decl] = field(default_factory=list)
    text: str = ""
    is_css: bool = False

    @property
    def in_tokens_layer(self) -> bool:
        return Path(self.path).parts[: len(TOKENS_LAYER)] == TOKENS_LAYER


def strip_comments(text: str, *, line_comments: bool) -> str:
    """The text with every comment blanked and every newline kept."""
    out: list[str] = []
    i, n = 0, len(text)
    in_block = False
    while i < n:
        if in_block:
            if text.startswith("*/", i):
                in_block = False
                i += 2
                continue
            out.append("\n" if text[i] == "\n" else " ")
            i += 1
            continue
        if text.startswith("/*", i):
            in_block = True
            i += 2
            out.append("  ")
            continue
        if line_comments and text.startswith("//", i):
            end = text.find("\n", i)
            if end == -1:
                break
            out.append(" " * (end - i))
            i = end
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def parse_css(text: str) -> list[Rule]:
    """Every style rule (at-rule blocks walked through, never judged as rules)."""
    rules: list[Rule] = []
    stack: list[tuple[str, int, Rule | None]] = []
    buf: list[str] = []
    buf_line = 0
    line = 1

    def flush_decl() -> None:
        raw = "".join(buf).strip()
        if not raw or not stack or stack[-1][2] is None or ":" not in raw:
            return
        prop, _, value = raw.partition(":")
        rule = stack[-1][2]
        rule.decls.append(Decl(prop.strip().lower(), value.strip(), buf_line or line))

    for ch in text:
        if ch == "{":
            prelude = "".join(buf).strip()
            node = None
            if not prelude.startswith("@"):
                node = Rule(split_top(prelude, ","), buf_line or line)
                rules.append(node)
            stack.append((prelude, buf_line or line, node))
            buf, buf_line = [], 0
        elif ch == "}":
            flush_decl()
            if stack:
                stack.pop()
            buf, buf_line = [], 0
        elif ch == ";":
            flush_decl()
            buf, buf_line = [], 0
        else:
            if not buf_line and not ch.isspace():
                buf_line = line
            buf.append(ch)
        if ch == "\n":
            line += 1
    return rules


def split_top(text: str, sep: str) -> list[str]:
    """`text` split on `sep` outside parentheses and brackets, each part stripped."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def value_tokens(value: str) -> list[str]:
    """A declaration value split on whitespace outside parentheses."""
    tokens: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                tokens.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


#: `key: <literal>` inside a `.ts`/`.tsx` object — a string, a template string, or a number.
_INLINE = re.compile(
    r"(?<![\w$.-])(?P<key>[A-Za-z]+)\s*:\s*"
    r"(?P<val>\"[^\"\n]*\"|'[^'\n]*'|`[^`]*`|-?\d+(?:\.\d+)?)(?=\s*[,}\n])"
)


def kebab(key: str) -> str:
    return re.sub(r"([A-Z])", r"-\1", key).lower()


def inline_decls(text: str, wanted: frozenset[str]) -> list[Decl]:
    """Every `key: literal` whose kebab-cased key is in `wanted`, as a declaration.

    A template literal carrying `${…}` is computed at run time and is not read.
    A bare number keeps its digits: React sends a unitless number as pixels for
    these properties, and the caller decides what that means.
    """
    out: list[Decl] = []
    for m in _INLINE.finditer(text):
        prop = kebab(m.group("key"))
        if prop not in wanted:
            continue
        raw = m.group("val")
        if raw.startswith("`") and "${" in raw:
            continue
        value = raw[1:-1] if raw[0] in "\"'`" else raw
        out.append(Decl(prop, value.strip(), text.count("\n", 0, m.start()) + 1))
    return out


def population(roots: list[str], inline_props: frozenset[str]) -> list[Sheet]:
    """Every stylesheet and script under `frontend/src/`, read."""
    sheets: list[Sheet] = []
    seen: set[Path] = set()
    for root in roots:
        for path in _kindscope.files_under(Path(root), SUFFIXES, under=SRC_ROOT):
            if path in seen:
                continue
            seen.add(path)
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if path.suffix == ".css":
                text = strip_comments(raw, line_comments=False)
                sheets.append(Sheet(str(path), rules=parse_css(text), text=text, is_css=True))
            else:
                text = strip_comments(raw, line_comments=True)
                sheets.append(Sheet(str(path), inline=inline_decls(text, inline_props), text=text))
    return sheets


def declarations(sheet: Sheet) -> list[Decl]:
    """Every declaration a sheet makes — its rules' and its inline styles'."""
    out = [d for rule in sheet.rules for d in rule.decls]
    out.extend(sheet.inline)
    return out
