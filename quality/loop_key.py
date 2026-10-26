"""The loop key's census: the paths a leg quotes, and the docs-only candidates no leg reads.

The grammar is the docs-only decider's, pinned equal by `apps/core/tests/test_loop_key.py`.
Invariant: a doubt widens the reads; a read the grammar cannot see can still hit (rule 90).
"""

# does-not-cover: a path assembled from parts, reached by a glob or walked as a directory (rule 90).

from __future__ import annotations

import argparse
import ast
import bisect
import functools
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from apps.core.roads import road
from quality.could_not_look import CouldNotLook, exit_could_not_look
from quality.tree import measured_tree

#: The decider whose declarations this census reads rather than retypes.
DECIDER = "scripts/gate_ledger.sh"
#: The checkout this census runs from: the decider's declarations are its, never the tree's.
HOME = Path(__file__).resolve().parents[1]
#: The decider's name for the commit-measured mark.
MEASURED_NAME = "GATE_DOCS_ONLY_MEASURED_AT_COMMIT"
#: The gate whose `static` legs a commit-measured module must be run by.
GATE = "scripts/check.sh"
#: The leg package rule 90 reads as files; a `_`-prefixed module is a helper.
LEGS = "quality/djb/legs"
#: `Leg`'s positional fields, in its declaration's order.
_LEG_FIELDS = ("name", "unit", "banner", "body", "after", "modes", "argv")
#: The roots a leg runs or reads; wider than the decider's because `scripts/*.py` legs open docs.
READER_ROOTS = ("apps", "config", "deploy", "quality", "scripts", "frontend/scripts")
#: Build output and caches, never a reader.
SKIP_DIRS: frozenset[str] = frozenset({"__pycache__", "node_modules", ".next", ".turbo"})
#: Planted wrongness: read for quotes (the decider greps them too), never judged by rule 90.
FIXTURE_DIRS: frozenset[str] = frozenset({"canary", "negative"})
#: The roots rule 90's typed-list clause reads.
ASSIGNMENT_ROOTS: tuple[str, ...] = ("scripts", "quality")

_TOKEN = re.compile(r"[A-Za-z0-9_./-]+")
_FILE_LEAD = re.compile(r"file:[ \t]*$")
_LIST_LEAD = re.compile(r"^[ \t]*-[ \t]+$")
_REASON_DASHES = ("—", "--")
#: A name that feeds the key's exclusion.
KEY_NAME = re.compile(r"(?i)prose|loop_?key|key_?exclu")
_DOCS_PATH = re.compile(r"(?<![\w.-])docs/[\w./*-]*")
_STATIC_LEG = re.compile(r"^gate_run_body[ \t]+(\S+)[ \t]+(\S+)[ \t]+static\b", re.MULTILINE)
_SHELL_FUNCTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)[ \t]*\{[ \t]*$")
_CHECK_RUN = re.compile(r"(?<![\w./-])(scripts/[\w.-]+) --check\b")
_SHELL_ASSIGN = re.compile(
    r"^[ \t]*(?:(?:export|readonly|local|declare|typeset)(?:[ \t]+-\w+)*[ \t]+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)$"
)


def decider_value(name: str, home: Path = HOME) -> str:
    """The single-quoted value `home`'s decider assigns to `name`, or could-not-look."""
    path = home / DECIDER
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{DECIDER} could not be read ({exc}) — the candidates are its") from exc
    found = re.search(rf"^{re.escape(name)}='([^']*)'$", text, re.MULTILINE)
    if found is None:
        raise CouldNotLook(f"{DECIDER} assigns no `{name}='…'` — the census reads it there")
    return found.group(1)


def candidate_patterns(home: Path = HOME) -> tuple[str, ...]:
    """`GATE_DOCS_ONLY_PATHS`, the decider's declared candidates, word by word."""
    patterns = tuple(decider_value("GATE_DOCS_ONLY_PATHS", home).split())
    for pattern in patterns:
        stem = pattern[:-3] if pattern.endswith("/**") else pattern
        if any(ch in stem for ch in "*?["):
            raise CouldNotLook(f"candidate pattern {pattern!r} is neither a path nor `<dir>/**`")
    return patterns


def excluded_patterns(home: Path = HOME) -> tuple[str, ...]:
    """`GATE_DOCS_ONLY_EXCLUDED`, the paths carved out of the declared list, word by word."""
    return tuple(decider_value("GATE_DOCS_ONLY_EXCLUDED", home).split())


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return path == pattern


def admitted(path: str, patterns: tuple[str, ...], excluded: tuple[str, ...]) -> bool:
    """On the declared list and on no exclusion — the decider's own answer for a path."""
    if any(_matches(path, pat) for pat in excluded):
        return False
    return any(_matches(path, pat) for pat in patterns)


def tree_paths(root: Path) -> frozenset[str]:
    """Every path of the measured tree, or could-not-look."""
    read = measured_tree(root, fresh=True)
    if not read.blobs:
        raise CouldNotLook(f"the measured tree could not be read: {read.why}")
    return frozenset(read.blobs)


def candidates(root: Path, paths: frozenset[str] | None = None) -> tuple[str, ...]:
    """The measured tree's paths on the decider's declared list."""
    patterns, excluded = candidate_patterns(), excluded_patterns()
    population = tree_paths(root) if paths is None else paths
    return tuple(sorted(p for p in population if admitted(p, patterns, excluded)))


def reader_files(root: Path, roots: tuple[str, ...] = READER_ROOTS) -> Iterator[Path]:
    """Every file under the roots, minus build output, in path order."""
    for sub in roots:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not SKIP_DIRS & set(path.relative_to(base).parts):
                yield path


def _text(path: Path) -> str | None:
    """A file's text, or None for a binary file (`grep -I`'s judgement: a NUL byte)."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="surrogateescape")


def _judge(line: str, start: int, end: int) -> bool:
    """Whether the token at `line[start:end]` is a quote in the decider's judge."""
    hash_at = line.find("#")
    if hash_at >= 0 and start > hash_at:
        return False
    before = line[start - 1] if start > 0 else ""
    after = line[end] if end < len(line) else ""
    if before == "`":
        return False
    lead = line[:start]
    return bool(
        (before == '"' and after == '"')
        or (before == "'" and after == "'")
        or _FILE_LEAD.search(lead)
        or _LIST_LEAD.match(lead)
    )


def quoted_tokens(line: str) -> Iterator[str]:
    """Every token the decider's judge reads as a quote on this line."""
    for match in _TOKEN.finditer(line):
        if _judge(line, match.start(), match.end()):
            yield match.group(0)


def quoted_needles(text: str, needles: frozenset[str]) -> Iterator[tuple[int, str]]:
    """`(line, needle)` per quote of a needle in the text; the judge runs only on a token hit."""
    starts: list[int] | None = None
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if token not in needles:
            continue
        if starts is None:
            starts = [0, *(i + 1 for i, ch in enumerate(text) if ch == "\n")]
        number = bisect.bisect_right(starts, match.start())
        head = starts[number - 1]
        tail = text.find("\n", match.end())
        line = text[head : tail if tail >= 0 else len(text)]
        if _judge(line, match.start() - head, match.end() - head):
            yield number, token


def declarations(text: str, mark: str) -> list[tuple[int, str]]:
    """`(line, path)` for every path a comment line of its own declares a non-read."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        body = line.lstrip(" \t")
        if not body.startswith("#"):
            continue
        body = body[1:].lstrip(" \t")
        if not body.startswith(mark):
            continue
        for word in re.split(r"[ \t]+", body[len(mark) :]):
            if not word:
                continue
            if word in _REASON_DASHES or word.startswith("#"):
                break
            out.append((number, word))
    return out


def _covers(declared: list[tuple[int, str]], needle: str) -> bool:
    return any(d == needle or d.rsplit("/", 1)[-1] == needle for _, d in declared)


def _leg_fields(path: Path) -> tuple[str, str, tuple[tuple[str, ...], ...]]:
    """`(name, unit, argv)` of a leg module's `LEG = Leg(...)`, read by `ast`, never imported."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise CouldNotLook(f"{path.name} could not be read ({exc}) — its leg is") from exc
    assigned: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                assigned[target.id] = node.value
    call = assigned.get("LEG")
    if not (
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Leg"
    ):
        raise CouldNotLook(f"{path.name} declares no `LEG = Leg(...)` — a module there is a leg")
    fields: dict[str, ast.expr] = dict(zip(_LEG_FIELDS, call.args, strict=False))
    fields.update((k.arg, k.value) for k in call.keywords if k.arg is not None)

    def literal(field: str, default: object) -> object:
        node = fields.get(field)
        if node is None:
            return default
        if isinstance(node, ast.Name) and node.id in assigned:
            node = assigned[node.id]
        try:
            return ast.literal_eval(node)
        except ValueError as exc:
            raise CouldNotLook(f"{path.name}: the leg's `{field}` is not a literal") from exc

    name, unit = literal("name", None), literal("unit", None)
    if not (isinstance(name, str) and isinstance(unit, str)):
        raise CouldNotLook(f"{path.name}: the leg's name and unit are not literal strings")
    argv = literal("argv", ()) if unit == "static" else ()
    if not (
        isinstance(argv, tuple)
        and all(isinstance(w, tuple) and all(isinstance(x, str) for x in w) for w in argv)
    ):
        raise CouldNotLook(f"{path.name}: the leg's `argv` is not a tuple of string tuples")
    return name, unit, argv


def _registry_static() -> tuple[frozenset[str], frozenset[str]]:
    """The leg package's static leg names and `--check` modules, read as files; none if absent."""
    home = HOME / LEGS
    if not home.is_dir():
        return frozenset(), frozenset()
    names: set[str] = set()
    modules: set[str] = set()
    for path in sorted(home.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name, unit, argv = _leg_fields(path)
        if unit != "static":
            continue
        names.add(name)
        for words in argv:
            for i, word in enumerate(words[:-1]):
                if word.startswith("scripts/") and words[i + 1] == "--check":
                    modules.add(word)
    return frozenset(names), frozenset(modules)


def static_check_modules(root: Path) -> frozenset[str]:
    """The `scripts/<module>` files a `static` leg runs as `<module> --check`, registry first."""
    try:
        text = (root / GATE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{GATE} could not be read ({exc}) — its `static` legs are") from exc
    claimed, ported = _registry_static()
    legs = {fn for name, fn in _STATIC_LEG.findall(text) if name not in claimed}
    found: set[str] = set(ported)
    body: str | None = None
    # A leg's body runs from its `name() {` line to the next `gate_run_body` line.
    for line in text.splitlines():
        start = _SHELL_FUNCTION.match(line)
        if start is not None:
            body = start.group(1)
        elif line.startswith("gate_run_body"):
            body = None
        elif body in legs:
            found.update(_CHECK_RUN.findall(line.split("#", 1)[0]))
    return frozenset(found)


def honoured(rel: str, modules: Callable[[], frozenset[str]]) -> bool:
    """Whether a module's commit-measured line counts: directly under `scripts/`, run by a leg."""
    return rel.count("/") == 1 and rel.startswith("scripts/") and rel in modules()


@dataclass(frozen=True)
class Measured:
    """One commit-measured declaration: the module, its line, the path, honoured or not."""

    module: str
    line: int
    path: str
    honoured: bool


def measured_declarations(root: Path, *, scripts_only: bool = False) -> list[Measured]:
    """Every `measured at the commit:` declaration under the reader roots, fixtures out."""
    mark = decider_value(MEASURED_NAME)
    modules = functools.cache(functools.partial(static_check_modules, root))
    out: list[Measured] = []
    for path in reader_files(root, ("scripts",) if scripts_only else READER_ROOTS):
        rel = path.relative_to(root).as_posix()
        if FIXTURE_DIRS & set(path.relative_to(root).parts) or (
            scripts_only and rel.count("/") != 1
        ):
            continue
        text = _text(path)
        found = declarations(text, mark) if text is not None and mark in text else []
        if found:
            ok = honoured(rel, modules)
            out.extend(Measured(rel, number, d, ok) for number, d in found)
    return out


def measured_at_commit(root: Path) -> list[tuple[str, str]]:
    """`(path, module)` per honoured commit-measured declaration: what the hook runs."""
    return sorted(
        (m.path, m.module) for m in measured_declarations(root, scripts_only=True) if m.honoured
    )


@dataclass(frozen=True)
class Quote:
    """One quote of a needle: where, and whether its module declares it a non-read."""

    needle: str
    site: str
    excused: bool


def quotes(root: Path, needles: frozenset[str], mark: str | None = None) -> list[Quote]:
    """Every quote of a needle under the reader roots, judged against its module's declarations."""
    mark = decider_value("GATE_DOCS_ONLY_NONREAD") if mark is None else mark
    measured_mark = decider_value(MEASURED_NAME)
    modules = functools.cache(functools.partial(static_check_modules, root))
    out: list[Quote] = []
    for path in reader_files(root):
        text = _text(path)
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        declared: list[tuple[int, str]] | None = None
        for number, token in quoted_needles(text, needles):
            if declared is None:
                declared = declarations(text, mark)
                measured = declarations(text, measured_mark) if measured_mark in text else []
                if measured and honoured(rel, modules):
                    declared += measured
            out.append(Quote(token, f"{rel}:{number}", _covers(declared, token)))
    return out


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def reads(root: Path) -> dict[str, list[str]]:
    """Every tree path a leg quotes — whole, or a candidate by its basename — with the sites."""
    paths = tree_paths(root)
    cands = candidates(root, paths)
    by_base: dict[str, list[str]] = {}
    for cand in cands:
        by_base.setdefault(_basename(cand), []).append(cand)
    found: dict[str, list[str]] = {}
    for quote in quotes(root, frozenset(paths) | frozenset(by_base)):
        if quote.excused:
            continue
        named = [quote.needle] if quote.needle in paths else []
        for path in dict.fromkeys(named + by_base.get(quote.needle, [])):
            found.setdefault(path, []).append(quote.site)
    return dict(sorted(found.items()))


@road("prose_paths", example="apps/core/tests/test_loop_key.py::test_a_quote_moves_it_out")
def prose_paths(root: Path) -> tuple[str, ...]:
    """The docs-only candidates no leg quotes: the paths the loop key may leave out."""
    read = reads(root)
    return tuple(p for p in candidates(root) if p not in read)


@dataclass(frozen=True)
class Site:
    """A rule-90 finding's coordinates and its subject."""

    path: str
    line: int
    subject: str


def stale_declarations(root: Path) -> tuple[list[Site], int]:
    """Every declared non-read its module never quotes, and how many declared paths were read."""
    mark = decider_value("GATE_DOCS_ONLY_NONREAD")
    stale: list[Site] = []
    read = 0
    for path in reader_files(root):
        if FIXTURE_DIRS & set(path.relative_to(root).parts):
            continue
        text = _text(path)
        if text is None or mark not in text:
            continue
        declared = declarations(text, mark)
        if not declared:
            continue
        quoted = {token for line in text.splitlines() for token in quoted_tokens(line)}
        rel = path.relative_to(root).as_posix()
        for number, d in declared:
            read += 1
            if d not in quoted and _basename(d) not in quoted:
                stale.append(Site(rel, number, d))
    return stale, read


def measured_findings(root: Path) -> tuple[list[Site], list[Site], int]:
    """`(stale, unrun, declared)` over the commit-measured declarations."""
    stale: list[Site] = []
    unrun: list[Site] = []
    found = measured_declarations(root)
    texts: dict[str, set[str]] = {}
    for m in found:
        if m.module not in texts:
            text = _text(root / m.module) or ""
            texts[m.module] = {t for line in text.splitlines() for t in quoted_tokens(line)}
        if m.path not in texts[m.module] and _basename(m.path) not in texts[m.module]:
            stale.append(Site(m.module, m.line, m.path))
        if not m.honoured:
            unrun.append(Site(m.module, m.line, m.path))
    return stale, unrun, len(found)


def _python_typed_lists(tree: ast.Module) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name) and KEY_NAME.search(t.id)]
        if not names:
            continue
        if any(
            isinstance(c, ast.Constant) and isinstance(c.value, str) and _DOCS_PATH.search(c.value)
            for c in ast.walk(value)
        ):
            yield node.lineno, names[0]


def _shell_typed_lists(text: str) -> Iterator[tuple[int, str]]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        found = _SHELL_ASSIGN.match(line)
        if found is None or not KEY_NAME.search(found.group(1)):
            continue
        value = found.group(2)
        if value.startswith("(") and ")" not in value:
            for more in lines[index + 1 :]:
                value += "\n" + more
                if ")" in more:
                    break
        if _DOCS_PATH.search(value):
            yield index + 1, found.group(1)


def typed_exclusions(root: Path) -> tuple[list[Site], int]:
    """Every assignment under the key's name whose value names a `docs/` path; the files read."""
    found: list[Site] = []
    scanned = 0
    for path in reader_files(root, ASSIGNMENT_ROOTS):
        if FIXTURE_DIRS & set(path.relative_to(root).parts):
            continue
        if path.suffix not in {".py", ".sh", ""}:
            continue
        text = _text(path)
        if text is None:
            continue
        scanned += 1
        rel = path.relative_to(root).as_posix()
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            sites = _python_typed_lists(tree)
        else:
            sites = _shell_typed_lists(text)
        found.extend(Site(rel, line, name) for line, name in sites)
    return found, scanned


def main(argv: list[str] | None = None) -> int:
    """`--reads` quoted paths and sites; `--prose` unquoted candidates; `--measured` declared."""
    parser = argparse.ArgumentParser(prog="python -m quality.loop_key", description=main.__doc__)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--reads", action="store_true")
    which.add_argument("--prose", action="store_true")
    which.add_argument("--measured", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.reads:
            for path, sites in reads(root).items():
                print(f"{path}  {sites[0]}" + (f" (+{len(sites) - 1})" if len(sites) > 1 else ""))
        elif args.measured:
            for path, module in measured_at_commit(root):
                print(f"{path}  {module}")
        else:
            for path in prose_paths(root):
                print(path)
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
