"""The road census — every marker on a tree, read statically, for every reader.

A JOB is a thing this platform must do exactly one way; a ROAD is the one
mechanism that does it; a MARKER is how a road says which job it does. This
module is the ONE reader of the marker grammar, and every consumer asks it:
`manage.py roads` (the door, an instrument), house rule 84's check in
`quality/checks/rule_84.py` (the judge), and the pytest census that pins the live
registry equal to this one. It reads FILES and never the app registry: the
fold reads a release it has not imported, and `--fast` boots no Django.

THE TWO CARRIERS, one field grammar (a job key and a worked example; the
contract is read off the road itself, never typed twice):

  importable Python (`apps/`, `config/`, `quality/`) — a decorator call named
  `road` with a string-literal job and a string-literal `example=` on a
  function or a class, or a module-level assignment to `ROAD` whose value is
  that call (or that call applied to the module object). Read by `ast`, so a
  docstring or a comment that SPELLS the call is not a marker. The contract is
  the first line of the marked object's docstring (the module's, for a module
  road). EVERY statement block is read — `if`, `try`, `with`, `for`, `while`,
  `match`, a function body — so a marker cannot hide from the census by where
  it sits; a marker that is not at module level (or on a definition directly
  inside a module-level class) is read and carries its `enclosure`, and house
  rule 84 refuses it: a road is unconditional and module-level.

  shell, and Python outside an importable package (`scripts/`, `deploy/`) — a
  comment line at column zero, `road:` after the comment token, then the job,
  an em dash, the contract, a middle dot and `example:` with the example. It is
  a marker only DIRECTLY ABOVE a function or class definition, or inside the
  header window; the same line anywhere else is prose, never a marker.

A marker that sits where a marker is read and cannot be read — an illegal job
key, a missing example, a docstring-less target, an argument that is not a
literal — raises `CensusError` naming it: could-not-look, never a skip.

THE VALVE. House rule 84 allows a declared second road for one job: the
comment line `rule-84: <reason>` (after the file's comment token) in the
contiguous comment block directly above the marker. The census records the
reason on the marker (`valve`) and names the standing road it is kept beside
(`kept_beside`); rule 84 judges it, the door prints it.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import cast

from quality.checks import _DRAWER_CONFTEST_PATH, SKIP_PARTS, _py_files

#: The roots a road may live under. A road anywhere else is a declared blind
#: spot of rule 84 (a root the walk does not name), never a silent reach.
PY_ROOTS: tuple[str, ...] = ("apps", "config", "quality")
#: Each app's test package is a root too, so `tests` is no skip there: a test-homed road is a road.
APP_TEST_ROOTS = "apps/*/tests"
TEXT_ROOTS: tuple[str, ...] = ("scripts", "scripts/tests", "deploy")

#: How many leading lines of a shell file are its header — the window a whole
#: script's marker is read in. The SAME number as `DRIVE_MARKER_LINES` in
#: `scripts/gate_ledger.sh`, which reads the drive markers in that window; the
#: shell constant is not importable from here, so the two are pinned equal by
#: the drive that owns the shell side.
HEADER_WINDOW = 40

#: One lowercase word or `noun_verb`; never a medium, a file name or a number.
JOB_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

#: THE WORDS THE READERS MATCH, once. The Python reader matches a call named
#: `ROAD_CALL`, a module-level target named `MODULE_TARGET` and a keyword named
#: `EXAMPLE_KEYWORD`; the shell reader matches `TEXT_KEY` after the comment token
#: and `EXAMPLE_KEY` before the example. The printed forms below are built from
#: the same words, so `--explain 84` and a could-not-look refusal spell the
#: grammar the readers read, never a second copy of it.
ROAD_CALL = "road"
MODULE_TARGET = "ROAD"
EXAMPLE_KEYWORD = "example"
TEXT_KEY = "road:"
EXAMPLE_KEY = "example:"

#: The shell carrier: the comment token, `TEXT_KEY`, the job, an em dash, the
#: contract, a middle dot, `EXAMPLE_KEY` and the example.
TEXT_MARKER_HEAD = re.compile(rf"^#\s*{re.escape(TEXT_KEY)}")
TEXT_MARKER_RE = re.compile(
    rf"^#\s*{re.escape(TEXT_KEY)}\s+(?P<job>\S+)\s+—\s+(?P<contract>.+?)\s+·\s+"
    rf"{re.escape(EXAMPLE_KEY)}\s+(?P<example>\S+)\s*$"
)

#: The three marker forms as a reader of `--explain 84` types them — built from
#: the words above, and pinned by a test that feeds each one back to the census.
PY_DECORATOR_FORM = f'@{ROAD_CALL}("<job>", {EXAMPLE_KEYWORD}="<path>::<symbol>")'
PY_MODULE_FORM = (
    f'{MODULE_TARGET} = {ROAD_CALL}("<job>", {EXAMPLE_KEYWORD}="<path>::<symbol>")'
    "(sys.modules[__name__])"
)
TEXT_MARKER_FORM = f"# {TEXT_KEY} <job> — <contract> · {EXAMPLE_KEY} <path>::<symbol>"

#: A definition a text marker may sit directly above: `name() {`, `def name`,
#: `class Name` — at column zero.
TEXT_DEF_RE = re.compile(
    r"^(?:(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{?|(?:async\s+)?def\s+(?P<pydef>\w+)|class\s+(?P<cls>\w+))"
)

#: The valve: rule 84's id, on a comment line, with its reason.
VALVE_RE = re.compile(r"^\s*#\s*rule-84:\s*(.*)$")

#: THE THIRD CARRIER: TypeScript under the browser tree. The same marker line as
#: the shell carrier, in the browser's comment token, directly above an
#: exported definition — `export function`, `export async function`,
#: `export const`, `export class`. No header window: a TypeScript module is
#: never a whole-file road the way a script is.
TS_ROOTS: tuple[str, ...] = ("frontend/src",)
TS_SUFFIXES: tuple[str, ...] = (".ts", ".tsx")
TS_COMMENT = "//"
TS_MARKER_HEAD = re.compile(rf"^{re.escape(TS_COMMENT)}\s*{re.escape(TEXT_KEY)}")
TS_MARKER_RE = re.compile(
    rf"^{re.escape(TS_COMMENT)}\s*{re.escape(TEXT_KEY)}\s+(?P<job>\S+)\s+—\s+(?P<contract>.+?)"
    rf"\s+·\s+{re.escape(EXAMPLE_KEY)}\s+(?P<example>\S+)\s*$"
)
TS_MARKER_FORM = f"{TS_COMMENT} {TEXT_KEY} <job> — <contract> · {EXAMPLE_KEY} <path>::<symbol>"
TS_DEF_RE = re.compile(
    r"^export\s+(?:(?:async\s+)?function\s+(?P<fn>[A-Za-z_$][\w$]*)"
    r"|const\s+(?P<const>[A-Za-z_$][\w$]*)|class\s+(?P<cls>[A-Za-z_$][\w$]*))"
)
TS_VALVE_RE = re.compile(rf"^\s*{re.escape(TS_COMMENT)}\s*rule-84:\s*(.*)$")

#: The drawer convention: anything under a `local/` segment is the product's.
LOCAL_SEGMENT = "local"


class CensusError(ValueError):
    """A marker where one is read that cannot be read. Exit 2 to every reader."""


@dataclass(frozen=True)
class Marker:
    """One road, as the census read it. `as_json()` is the door's `roads[]` row."""

    job: str
    partition: str  # platform | product
    carrier: str  # py (the decorator, by ast) | sh / ts (the comment line, read as text)
    kind: str  # function | class | module | script
    path: str  # relative to the root the census walked
    line: int  # the marker's own line
    import_path: str | None  # the dotted name a Python road imports as; None for text
    symbol: str | None  # the marked name; None for a module or whole-script road
    contract: str  # the road's first docstring line, or the marker line's text
    example: str  # `path::symbol`, existence-checked by the door
    kept_beside: str | None = None  # the standing road a valved second one is kept beside
    valve: str | None = None  # the rule-84 reason above the marker, if any
    enclosure: str | None = None  # the statement a conditional or nested marker sits inside

    @property
    def where(self) -> str:
        """How a finding names this road: its import, or `path::symbol`."""
        if self.import_path:
            return self.import_path
        return f"{self.path}::{self.symbol}" if self.symbol else self.path

    def as_json(self) -> dict[str, object]:
        row = asdict(self)
        row["import"] = row.pop("import_path")
        row.pop("valve")
        row.pop("enclosure")
        return row


def _platform_labels() -> frozenset[str]:
    from quality.partition import platform_apps

    return frozenset(platform_apps())


def partition_of(rel: str, platform: frozenset[str]) -> str:
    """`platform` or `product`, derived: the lockfile's apps, the template roots, the drawers.

    Under `apps/<label>/` the lockfile decides, by label. A file AT the apps
    root (`apps/conftest.py`, `apps/test_*.py`) is no app's: it is the
    template's, except the one declared drawer there — the product's fixtures
    file — which is the product's. A `local/` segment anywhere is the product's.
    """
    parts = Path(rel).parts
    if LOCAL_SEGMENT in parts[:-1]:
        return "product"
    if rel == _DRAWER_CONFTEST_PATH:
        return "product"
    if parts and parts[0] == "apps" and len(parts) > 2:
        return "platform" if parts[1] in platform else "product"
    return "platform"


def _valve_above(
    lines: list[str], line: int, *, comment: str = "#", pattern: re.Pattern[str] = VALVE_RE
) -> str | None:
    """The rule-84 reason in the contiguous comment block directly above `line`."""
    index = line - 2
    while index >= 0 and lines[index].strip().startswith(comment):
        match = pattern.match(lines[index])
        if match:
            return match.group(1).strip()
        index -= 1
    return None


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().splitlines()[0].strip() if (doc or "").strip() else ""


def _road_call(node: ast.expr) -> ast.Call | None:
    """The `road(...)` call this expression is, or applies; None if it is neither."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == ROAD_CALL:
        return node
    if isinstance(func, ast.Attribute) and func.attr == ROAD_CALL:
        return node
    # `road("job", example=...)(sys.modules[__name__])` — the module form.
    return _road_call(func)


def _literal_args(call: ast.Call, where: str) -> tuple[str, str]:
    """(job, example) off a road call, or CensusError: a marker is literals."""
    job_node = call.args[0] if call.args else None
    example_node = next((k.value for k in call.keywords if k.arg == EXAMPLE_KEYWORD), None)
    if not (isinstance(job_node, ast.Constant) and isinstance(job_node.value, str)):
        raise CensusError(f"{where}: a road marker's job is not a string literal")
    if not (isinstance(example_node, ast.Constant) and isinstance(example_node.value, str)):
        raise CensusError(f"{where}: a road marker's example= is not a string literal")
    return job_node.value, example_node.value


def _check_fields(job: str, example: str, contract: str, where: str) -> None:
    if not JOB_RE.match(job):
        raise CensusError(
            f"{where}: job key {job!r} is not one lowercase word or noun_verb "
            f"({JOB_RE.pattern}) — a job is never spelled by its medium, a file or a number"
        )
    if not example.strip():
        raise CensusError(f"{where}: the road for {job!r} names no example")
    if not contract:
        raise CensusError(f"{where}: the road for {job!r} has no contract — its docstring is empty")


def _describe(node: ast.stmt) -> str:
    """How a finding names the statement a marker sits inside: its own first line."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return f"`def {node.name}` (line {node.lineno})"
    if isinstance(node, ast.ClassDef):
        return f"`class {node.name}` (line {node.lineno})"
    head = ast.unparse(node).splitlines()[0].rstrip(":")
    return f"`{head}` (line {node.lineno})"


def _enclosure(chain: list[ast.stmt], *, class_ok: bool) -> str | None:
    """None where a road may stand; else the outermost statement that makes it conditional.

    A road stands at module level, or — `class_ok` — on a definition directly
    inside a module-level class. Anything else (a nested function, a class
    inside a class or a function, an `if`/`try`/`with`/`for`/`while`/`match`
    block) is named by the first statement on the way in that breaks that.
    """
    for depth, node in enumerate(chain):
        if class_ok and depth == 0 and isinstance(node, ast.ClassDef):
            continue
        return _describe(node)
    return None


def _blocks(node: ast.stmt) -> list[ast.stmt]:
    """Every statement directly inside `node`'s blocks, whatever the statement kind.

    `ast.iter_child_nodes` rather than a list of field names (`body`, `orelse`,
    `finalbody`, `handlers`, `cases`): a statement is the only node that holds
    statements, reached directly or through an `except` handler or a `match`
    case, so the walk is a closed question over the AST's own shape and a
    statement kind a later Python adds is read without an edit here.
    """
    out: list[ast.stmt] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            out.append(child)
        elif isinstance(child, (ast.excepthandler, ast.match_case)):
            out.extend(c for c in ast.iter_child_nodes(child) if isinstance(c, ast.stmt))
    return out


def _module_name(rel: str) -> str:
    parts = list(Path(rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _py_markers(path: Path, rel: str, platform: frozenset[str]) -> list[Marker]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if ROAD_CALL not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise CensusError(
            f"{rel}: does not parse, so its markers cannot be read ({error})"
        ) from error
    lines = source.splitlines()
    module = _module_name(rel)
    part = partition_of(rel, platform)
    out: list[Marker] = []

    def add(
        job: str,
        example: str,
        line: int,
        kind: str,
        symbol: str | None,
        contract: str,
        enclosure: str | None,
    ) -> None:
        where = f"{rel}:{line}"
        _check_fields(job, example, contract, where)
        out.append(
            Marker(
                job=job,
                partition=part,
                carrier="py",
                kind=kind,
                path=rel,
                line=line,
                import_path=f"{module}.{symbol}" if symbol else module,
                symbol=symbol,
                contract=contract,
                example=example,
                valve=_valve_above(lines, line),
                enclosure=enclosure,
            )
        )

    def walk(body: list[ast.stmt], prefix: str, chain: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == MODULE_TARGET for t in node.targets
            ):
                call = _road_call(node.value)
                if call is not None:
                    job, example = _literal_args(call, f"{rel}:{node.lineno}")
                    add(
                        job,
                        example,
                        node.lineno,
                        "module",
                        None,
                        _first_line(ast.get_docstring(tree)),
                        # A module road is the module's own statement: never in a class.
                        _enclosure(chain, class_ok=False),
                    )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{node.name}"
                for decorator in node.decorator_list:
                    call = _road_call(decorator)
                    if call is None or call is not decorator:
                        continue
                    job, example = _literal_args(call, f"{rel}:{decorator.lineno}")
                    add(
                        job,
                        example,
                        decorator.lineno,
                        "class" if isinstance(node, ast.ClassDef) else "function",
                        qual,
                        _first_line(ast.get_docstring(node)),
                        _enclosure(chain, class_ok=True),
                    )
                # The qualified name Python gives what is defined inside: a
                # class's members by dot, a function's by `<locals>` — so the
                # census's import path for a nested marker is the one import
                # would produce, and the two can be compared.
                inner = f"{qual}." if isinstance(node, ast.ClassDef) else f"{qual}.<locals>."
                walk(node.body, inner, [*chain, node])
                continue
            # A block statement does not change a qualified name; it does make
            # whatever is inside it conditional.
            walk(_blocks(node), prefix, [*chain, node])

    walk(tree.body, "", [])
    return out


def _text_markers(path: Path, rel: str, platform: frozenset[str]) -> list[Marker]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    part = partition_of(rel, platform)
    out: list[Marker] = []
    for index, text in enumerate(lines):
        if not TEXT_MARKER_HEAD.match(text):
            continue
        below = lines[index + 1] if index + 1 < len(lines) else ""
        definition = TEXT_DEF_RE.match(below)
        in_header = index < HEADER_WINDOW
        if not definition and not in_header:
            continue  # prose that spells the grammar, never a marker
        where = f"{rel}:{index + 1}"
        match = TEXT_MARKER_RE.match(text)
        if not match:
            raise CensusError(
                f"{where}: a road marker line that does not read as `{TEXT_MARKER_FORM}`"
            )
        job, contract, example = (
            match.group("job"),
            match.group("contract").strip(),
            match.group("example"),
        )
        _check_fields(job, example, contract, where)
        symbol = None
        if definition:
            symbol = definition.group("fn") or definition.group("pydef") or definition.group("cls")
        out.append(
            Marker(
                job=job,
                partition=part,
                carrier="sh",
                kind=("class" if definition.group("cls") else "function")
                if definition
                else "script",
                path=rel,
                line=index + 1,
                import_path=None,
                symbol=symbol,
                contract=contract,
                example=example,
                valve=_valve_above(lines, index + 1),
            )
        )
    return out


def _ts_markers(path: Path, rel: str, platform: frozenset[str]) -> list[Marker]:
    """The TypeScript carrier: `// road: …` directly above an exported definition."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    part = partition_of(rel, platform)
    out: list[Marker] = []
    for index, text in enumerate(lines):
        if not TS_MARKER_HEAD.match(text):
            continue
        below = lines[index + 1] if index + 1 < len(lines) else ""
        definition = TS_DEF_RE.match(below)
        if not definition:
            continue  # prose that spells the grammar, never a marker
        where = f"{rel}:{index + 1}"
        match = TS_MARKER_RE.match(text)
        if not match:
            raise CensusError(
                f"{where}: a road marker line that does not read as `{TS_MARKER_FORM}`"
            )
        job, contract, example = (
            match.group("job"),
            match.group("contract").strip(),
            match.group("example"),
        )
        _check_fields(job, example, contract, where)
        out.append(
            Marker(
                job=job,
                partition=part,
                carrier="ts",
                kind="class" if definition.group("cls") else "function",
                path=rel,
                line=index + 1,
                import_path=None,
                symbol=definition.group("fn")
                or definition.group("const")
                or definition.group("cls"),
                contract=contract,
                example=example,
                valve=_valve_above(lines, index + 1, comment=TS_COMMENT, pattern=TS_VALVE_RE),
            )
        )
    return out


def _standing_order(marker: Marker) -> tuple[int, int, str, int]:
    """An unconditional road stands over a conditional one; the platform's over a
    product's; then the lexically first path."""
    return (
        0 if marker.enclosure is None else 1,
        0 if marker.partition == "platform" else 1,
        marker.path,
        marker.line,
    )


def _py_roots(root: Path) -> tuple[str, ...]:
    """`PY_ROOTS`, then every directory `APP_TEST_ROOTS` matches under `root`."""
    tests = sorted(str(p.relative_to(root)) for p in root.glob(APP_TEST_ROOTS) if p.is_dir())
    return (*PY_ROOTS, *tests)


def census(root: Path) -> list[Marker]:
    """Every marker under `root`, each valved second road naming the one it is kept beside.

    Sorted by job, then by standing order — the first marker of each job is
    the road that stands. Reads files only: no import, no app registry.
    """
    root = Path(root)
    platform = _platform_labels()
    found: list[Marker] = []
    seen: set[str] = set()
    for path in _py_files(root, *_py_roots(root)):
        rel = str(path.relative_to(root))
        if rel in seen:
            continue
        seen.add(rel)
        found.extend(_py_markers(path, rel, platform))
    for path in _py_files(root, *TEXT_ROOTS, suffixes=(".sh", ".py")):
        rel = str(path.relative_to(root))
        if rel in seen:
            continue
        seen.add(rel)
        found.extend(_text_markers(path, rel, platform))
    for path in _py_files(root, *TS_ROOTS, suffixes=TS_SUFFIXES):
        rel = str(path.relative_to(root))
        found.extend(_ts_markers(path, rel, platform))
    by_job: dict[str, list[Marker]] = {}
    for marker in found:
        by_job.setdefault(marker.job, []).append(marker)
    out: list[Marker] = []
    for job in sorted(by_job):
        ordered = sorted(by_job[job], key=_standing_order)
        standing = next((m for m in ordered if m.valve is None and m.enclosure is None), ordered[0])
        for marker in ordered:
            if marker is not standing and marker.valve is not None:
                marker = replace(marker, kept_beside=standing.where)
            out.append(marker)
    return out


def standing(markers: list[Marker]) -> dict[str, Marker]:
    """The one road that stands per job: the first unconditional unvalved marker, else the first."""

    def rank(marker: Marker) -> tuple[bool, bool]:
        return (marker.enclosure is not None, marker.valve is not None)

    out: dict[str, Marker] = {}
    for marker in markers:
        current = out.get(marker.job)
        if current is None or rank(marker) < rank(current):
            out[marker.job] = marker
    return out


def population(root: Path, rule: dict[str, object]) -> list[str]:
    """What the census reads, derived from the constants it reads by — never typed twice.

    House rule 84's `census:`, so `--explain 84` prints which files and which
    lines will be counted before a product writes one; the counts below it are
    this tree's.
    """
    skips = ", ".join(sorted(SKIP_PARTS))
    lines = [
        f"python roots: {', '.join(f'{r}/' for r in (*PY_ROOTS, APP_TEST_ROOTS))} — every .py "
        "file, read by ast, never imported",
        f"text roots:   {', '.join(f'{r}/' for r in TEXT_ROOTS)} — every .sh file, and every "
        ".py file no python root already read",
        f"skipped:      any path segment named {skips}, judged under each root; a path "
        "outside every root is a declared blind spot, never read",
        f"python form 1: a decorator `{PY_DECORATOR_FORM}`, both string literals, on a def, "
        "an async def or a class — its docstring's first line is the contract",
        f"python form 2: `{PY_MODULE_FORM}` at module level — the module is the road and its "
        "docstring's first line is the contract",
        "where:        every statement block is read; a road stands only at module level or "
        "on a definition directly inside a module-level class — one under an if, try, with, "
        "for, while or match, or inside a function, is read and refused (a road is "
        "unconditional)",
        f"shell line:   `{TEXT_MARKER_FORM}` at column zero, "
        "directly above `name() {`, `def name` or `class Name`, or anywhere in the "
        f"first {HEADER_WINDOW} lines (the header window: the whole script is the road); the "
        "same line anywhere else is prose",
        f"typescript:   `{TS_MARKER_FORM}` at column zero in "
        f"{', '.join(f'{r}/' for r in TS_ROOTS)} "
        f"({', '.join(TS_SUFFIXES)}), directly above `export function`, `export const` or "
        "`export class`; the same line anywhere else is prose",
        f"job key:      {JOB_RE.pattern}; a marker that cannot be read is could-not-look "
        "(exit 2), never skipped",
        "partition:    apps/<label>/... by the lockfile's platform apps; a local/ segment and "
        f"{_DRAWER_CONFTEST_PATH} are the product's; every other path is the template's",
    ]
    markers = census(root)
    lines.append(
        f"read here:    {len(markers)} markers — "
        f"{sum(1 for m in markers if m.carrier == 'py')} python, "
        f"{sum(1 for m in markers if m.carrier == 'sh')} shell, "
        f"{sum(1 for m in markers if m.carrier == 'ts')} typescript, "
        f"{len({m.job for m in markers})} jobs"
    )
    # EACH FINDING CLASS'S POPULATION, read from the check's own docstring — the
    # one place it is written — so a class the rule records with no grammar
    # there says so here instead of printing nothing.
    grammar = _class_grammar()
    recorded = [str(k) for k in cast("Iterable[object]", rule.get("ratchets") or {})]
    frozen = cast("Iterable[object]", rule.get("frozen") or ())
    for klass in dict.fromkeys([*recorded, *(str(k) for k in frozen)]):
        text = grammar.get(str(klass))
        lines.append(
            f"class {klass}: {text}"
            if text
            else f"class {klass}: NO GRAMMAR — road_uniqueness's docstring does not define it"
        )
    return lines


def _class_grammar() -> dict[str, str]:
    """`class -> its population, one line` from rule 84's check docstring."""
    from quality.checks import road_uniqueness

    out: dict[str, str] = {}
    current: str | None = None
    for raw in (road_uniqueness.__doc__ or "").splitlines():
        head = re.match(r"^    ([a-z][a-z0-9_]*) — (.*)$", raw)
        if head:
            current = head.group(1)
            out[current] = head.group(2).strip()
        elif current and raw.startswith("      ") and raw.strip():
            out[current] += " " + raw.strip()
        else:
            current = None
    return out
