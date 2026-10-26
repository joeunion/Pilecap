"""The additive shapes' extracts: fragments inside a noun, each carried with the line it sits by."""

# does-not-cover: a target whose earlier scaffolds repeat an anchor's text in scope — nth counts it.

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from apps.core.scaffold import copier

#: The shape words whose goldens are fragments of a noun, inserted rather than written whole.
ADDITIVE: frozenset[str] = frozenset(
    {
        "field",
        "filter",
        "ordering",
        "verb",
        "enum",
        "workflow",
        "policy",
        "stat",
        "search",
        "child",
        "webhook-in",
    }
)
#: The one module an additive golden fences inside a class: its `ready()`, extracted dedented.
APP_CONFIG = "apps.py"
#: The noun golden every additive fragment is anchored inside.
BASE = "noun"
ANCHOR = "# golden-anchor: "
SIDES = ("after", "before", "imports", "end")


class AnchorMissing(ValueError):
    """A fragment's anchor line is not in the target where its golden put it."""


def additive(key: str) -> bool:
    """Whether an extract key is an additive shape's golden."""
    return key.partition(".")[0] in ADDITIVE


@dataclass(frozen=True)
class Anchor:
    """Where a fragment goes: by the `nth` line reading `text` in `scope`, or at a seam."""

    scope: tuple[str, ...]
    side: str
    text: str = ""
    nth: int = 0

    def line(self) -> str:
        """The header line an extract carries above its fragment."""
        body = {"scope": list(self.scope), "side": self.side, "text": self.text, "nth": self.nth}
        return ANCHOR + json.dumps(body, sort_keys=True)

    def where(self) -> str:
        """The anchor as `--dry-run` prints it."""
        inside = ".".join(self.scope) or "<module>"
        if self.side in ("imports", "end"):
            return f"at the {self.side} of {inside}"
        return f"{self.side} `{self.text}` (#{self.nth + 1}) in {inside}"


@dataclass
class Piece:
    """One fragment and its anchor."""

    anchor: Anchor
    lines: list[str] = field(default_factory=list)


@dataclass
class View:
    """A module as the noun copy sees it, with one key's lines marked: `(text, is_key)` per line."""

    lines: list[tuple[str, bool]]

    def text(self, with_key: bool) -> str:
        """The module's text with or without the key's lines."""
        return "".join(t + "\n" for t, mine in self.lines if with_key or not mine)


def view(source: str, key: str, verbs: Sequence[str], where: str = "") -> View:
    """The lines inside the noun's fences or `key`'s, fences dropped, gaps two blank lines."""
    open_keys: list[str] = []
    lines: list[tuple[str, bool]] = []
    gap = False
    for number, line in enumerate(source.splitlines(), 1):
        fence = copier.parse_fence(line, verbs, f"{where}:{number}: ")
        if fence is not None:
            for k in fence.keys:
                if fence.edge == "begin":
                    open_keys.append(k)
                elif k in open_keys:
                    open_keys.remove(k)
            continue
        mine, base = key in open_keys, BASE in open_keys
        if not (mine or base):
            gap = gap or bool(lines)
            continue
        if gap:
            lines += [("", False), ("", False)]
            gap = False
        lines.append((line, mine))
    return View(lines)


def _scopes(tree: ast.Module) -> list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every class and function of a module, outermost first."""
    kinds = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return [node for node in ast.walk(tree) if isinstance(node, kinds)]


def _chain(tree: ast.Module, first: int, last: int) -> tuple[tuple[str, ...], int, int]:
    """The names of the scopes holding lines `first..last` that open before them, and its range."""
    names: list[str] = []
    span = (1, 10**9)

    def walk(body: Sequence[ast.stmt]) -> None:
        nonlocal span
        for node in body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = node.end_lineno or node.lineno
            if node.lineno < first and end >= last:
                names.append(node.name)
                span = (node.lineno, end)
                walk(node.body)
                return

    walk(tree.body)
    return tuple(names), span[0], span[1]


def _parsed(text: str, where: str) -> ast.Module:
    """`text` parsed, or a `FenceError` naming where."""
    try:
        return ast.parse(text)
    except SyntaxError as error:
        raise copier.FenceError(f"{where}: the noun's view does not parse ({error})") from error


def _importing(lines: Sequence[str]) -> bool:
    """Whether a fragment is only import statements."""
    code = [line for line in lines if line.strip()]
    try:
        body = ast.parse("\n".join(code)).body
    except SyntaxError:
        return False
    return bool(body) and all(isinstance(n, (ast.Import, ast.ImportFrom)) for n in body)


def pieces(source: str, key: str, verbs: Sequence[str], where: str = "") -> list[Piece]:
    """`key`'s fragments in a module, each anchored on a noun line that is not the key's."""
    seen = view(source, key, verbs, where)
    tree = _parsed(seen.text(with_key=True), where)
    rows = seen.lines
    found: list[Piece] = []
    index = 0
    while index < len(rows):
        if not rows[index][1]:
            index += 1
            continue
        start = index
        while index < len(rows) and rows[index][1]:
            index += 1
            gap = index
            while gap < len(rows) and not rows[gap][1] and not rows[gap][0].strip():
                gap += 1
            if gap < len(rows) and rows[gap][1]:
                index = gap  # only blank lines between two runs of the key: one fragment
        block = [text for text, _ in rows[start:index]]
        scope, low, high = _chain(tree, start + 1, index)
        found.append(Piece(_anchor(rows, start, index, scope, low, high, block, where), block))
    return found


def _anchor(
    rows: list[tuple[str, bool]],
    start: int,
    stop: int,
    scope: tuple[str, ...],
    low: int,
    high: int,
    block: list[str],
    where: str,
) -> Anchor:
    """The steadiest noun line beside rows `start..stop`: unique beats counted, next beats prior."""
    if not scope and _importing(block):
        return Anchor(scope, "imports")

    def usable(i: int) -> bool:
        text, mine = rows[i]
        code = bool(text.strip()) and not text.lstrip().startswith("#")
        return not mine and code and low <= i + 1 <= high

    def nth(i: int) -> tuple[int, int]:
        text = rows[i][0].strip()
        same = [j for j in range(low - 1, min(high, len(rows))) if usable(j)]
        same = [j for j in same if rows[j][0].strip() == text]
        return same.index(i), len(same)

    before = next((i for i in range(start - 1, low - 2, -1) if usable(i)), None)
    after = next((i for i in range(stop, min(high, len(rows))) if usable(i)), None)
    for i, side in ((after, "before"), (before, "after")):
        if i is not None and nth(i)[1] == 1:
            return Anchor(scope, side, rows[i][0].strip(), 0)
    if before is not None:
        return Anchor(scope, "after", rows[before][0].strip(), nth(before)[0])
    if after is not None:
        return Anchor(scope, "before", rows[after][0].strip(), nth(after)[0])
    if not scope:
        return Anchor(scope, "end")
    raise copier.FenceError(f"{where}: a fragment in {'.'.join(scope)} has no noun line beside it")


def serialize(found: Sequence[Piece]) -> str:
    """An additive extract's text: each fragment under its anchor's header line."""
    return "".join(p.anchor.line() + "\n" + "".join(f"{t}\n" for t in p.lines) for p in found)


def read(text: str) -> list[Piece]:
    """An additive extract read back into its fragments."""
    found: list[Piece] = []
    for line in text.splitlines():
        if line.startswith(ANCHOR):
            body = json.loads(line.removeprefix(ANCHOR))
            anchor = Anchor(tuple(body["scope"]), body["side"], body["text"], int(body["nth"]))
            found.append(Piece(anchor))
        elif found:
            found[-1].lines.append(line)
        else:
            raise copier.FenceError("an additive extract starts with a fragment and no anchor")
    return found


def _flat(text: str) -> str:
    """`text` as the formatter cannot change it: no whitespace, no comma before a closer."""
    return re.sub(r",(?=[)\]}])", "", re.sub(r"\s+", "", text))


def _spans(lines: Sequence[str], first: int, high: int, text: str) -> tuple[int, int] | None:
    """The lines `first..last` that read `text` however the formatter wrapped it, else None."""
    want, said = _flat(text), ""
    if not _flat(lines[first]) or copier.FENCE_LINE.match(lines[first]):
        return None
    for last in range(first, high):
        said = _flat(said + lines[last])
        if said == want:
            return first, last
        if not want.startswith(said.rstrip(",")):
            return None
    return None


def _locate(text: str, anchor: Anchor) -> int:
    """The 0-based line index a fragment is inserted at in `text`, or `AnchorMissing`."""
    lines = text.splitlines()
    tree = ast.parse(text)
    low, high = 1, len(lines)
    body: Sequence[ast.stmt] = tree.body
    for name in anchor.scope:
        node = next(
            (
                n
                for n in body
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name
            ),
            None,
        )
        if node is None:
            raise AnchorMissing(f"no `{name}` to hold the fragment ({anchor.where()})")
        low, high, body = node.lineno, node.end_lineno or node.lineno, node.body
    if anchor.side == "end":
        return len(lines)
    if anchor.side == "imports":
        ends = [
            n.end_lineno or n.lineno
            for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        return max(ends, default=0)
    hits = [span for i in range(low - 1, high) if (span := _spans(lines, i, high, anchor.text))]
    if len(hits) <= anchor.nth:
        raise AnchorMissing(f"the target has no line {anchor.where()}")
    hit, last = hits[anchor.nth]
    if anchor.side == "after":
        return last + 1
    while hit > low - 1 and lines[hit - 1].lstrip().startswith("#"):
        hit -= 1  # a comment above the anchor is the anchor's own: the fragment goes above it
    return hit


def carried(
    read: Mapping[str, Sequence[Piece]],
    found: Mapping[str, Sequence[Piece]],
    existing: Mapping[str, str],
    target: str,
) -> None:
    """Each fragment in `found` without the road marker of an example the copy does not carry."""
    held = {
        rel: "\n".join([existing.get(rel, ""), *(line for p in pieces for line in p.lines)])
        for rel, pieces in found.items()
    }
    held = {**existing, **held}
    for rel, pieces in found.items():
        for was, piece in zip(read[rel], pieces[: len(read[rel])], strict=True):
            if not piece.lines:
                continue
            text = copier.carried_examples(
                "\n".join(was.lines) + "\n", "\n".join(piece.lines) + "\n", held, target
            )
            piece.lines = text.removesuffix("\n").split("\n")


def insert(text: str, found: Sequence[Piece]) -> tuple[str, list[int]]:
    """`text` with every fragment put at its anchor; the 1-based line each landed on."""
    landed: list[int] = []
    for piece in found:
        at = _locate(text, piece.anchor)
        lines = text.splitlines()
        block = list(piece.lines)
        if piece.anchor.side == "end":
            block = ["", "", *block]
        lines[at:at] = block
        text = "\n".join(lines) + "\n"
        landed.append(at + 1)
        try:
            ast.parse(text)
        except SyntaxError as error:
            raise AnchorMissing(
                f"the fragment {piece.anchor.where()} does not parse there"
            ) from error
    return text, landed


def renamed(
    found: Sequence[Piece], block: Sequence[tuple[str, str]], anchor: Sequence[tuple[str, str]]
) -> list[Piece]:
    """The fragments with `block`'s renames on their lines and `anchor`'s on where they go."""

    def apply(text: str, renames: Sequence[tuple[str, str]]) -> str:
        for old, new in renames:
            text = text.replace(old, new)
        return text

    return [
        Piece(
            Anchor(
                tuple(apply(s, anchor) for s in p.anchor.scope),
                p.anchor.side,
                apply(p.anchor.text, anchor),
                p.anchor.nth,
            ),
            [apply(line, block) for line in p.lines],
        )
        for p in found
    ]
