"""Split one module into a package along its `# --- ` section markers, and prove the move."""

# does-not-cover: a write via vars(mod)[…], mod.__dict__[…], sys.modules[…], or mod.X: T = ….
# does-not-cover: --prove misses a re-aliased import, __init__'s docstring, family import order.
# does-not-cover: a submodule's __all__; no canary for --door, --prefix or --families.
# does-not-cover: --django cannot cold-import a module that needs a database at import time.
# does-not-cover: a module reaching Django only through first-party imports needs --django named.

from __future__ import annotations

import argparse
import ast
import builtins
import copy
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

LINE_LENGTH = 100
MARKER = "# --- "
FAMILY = "# --- rule"
HUB = "_hub"
INIT = "__init__"
NOQA = "# noqa: E402"
CONTRACT = "# import order: the hub first — families import it at their head, it imports them last"
HAZARD_NAMES = frozenset(
    {"__file__", "__name__", "__spec__", "__package__", "__loader__", "__path__", "__cached__"}
)
HAZARD_CALLS = frozenset({"globals", "locals", "vars", "__import__"})
MODULE_NAMES = HAZARD_NAMES | {"__doc__", "__builtins__", "__annotations__", "__dict__"}
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
CARRIED = (*DEFS, ast.Assign, ast.AnnAssign)
IMPORTS = (ast.Import, ast.ImportFrom)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


class Refused(Exception):
    """A case the tool will not carry; the message names the statement."""


@dataclass
class Unit:
    """One top-level statement and the source lines that travel with it."""

    node: ast.stmt
    first: int
    last: int
    lead: list[str] = field(default_factory=list)
    trail: list[str] = field(default_factory=list)
    marker: str = ""
    module: str = ""
    binds: set[str] = field(default_factory=set)
    eager: set[str] = field(default_factory=set)
    lazy: set[str] = field(default_factory=set)
    rebinds: set[str] = field(default_factory=set)

    @property
    def is_def(self) -> bool:
        return isinstance(self.node, DEFS)

    @property
    def label(self) -> str:
        return f"{','.join(sorted(self.binds))} (line {self.first})"


def _stored(target: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def binds(node: ast.stmt) -> set[str]:
    """The module-level names one top-level statement binds."""
    if isinstance(node, DEFS):
        return {node.name}
    if isinstance(node, ast.Assign):
        return set().union(*(_stored(t) for t in node.targets))
    if isinstance(node, ast.AnnAssign):
        return _stored(node.target)
    if isinstance(node, ast.Import):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    if isinstance(node, ast.ImportFrom):
        return {a.asname or a.name for a in node.names}
    return set()


def _scope_names(node: ast.AST) -> set[str]:
    """Every name a function, lambda, class body or comprehension binds in its own scope."""
    names: set[str] = set()
    if isinstance(node, COMPREHENSIONS):
        for gen in node.generators:
            names |= _stored(gen.target)
        return names
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = node.args
        names |= {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x}
    body = node.body if isinstance(node.body, list) else [node.body]  # type: ignore[attr-defined]
    stack: list[ast.AST] = list(body)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, DEFS):
            names.add(n.name)
            continue
        elif isinstance(n, IMPORTS):
            names |= binds(n)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            names.add(n.rest)
        elif isinstance(n, (ast.Lambda, *COMPREHENSIONS)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return names


class Reads(ast.NodeVisitor):
    """The module-global names a statement reads: at import time (eager) or later (lazy)."""

    def __init__(self, lazy_annotations: bool) -> None:
        self.eager: set[str] = set()
        self.lazy: set[str] = set()
        self.hazards: list[str] = []
        self.rebinds: set[str] = set()
        self._scopes: list[tuple[str, set[str]]] = []
        self._depth = 0
        self._lazy_annotations = lazy_annotations

    def _local(self, name: str) -> bool:
        for i, (kind, names) in enumerate(reversed(self._scopes)):
            if kind == "class" and i:
                continue
            if name in names:
                return True
        return False

    def _scoped(self, kind: str, node: ast.AST, body: list[ast.AST], lazy: bool) -> None:
        self._scopes.append((kind, _scope_names(node)))
        self._depth += lazy
        for part in body:
            self.visit(part)
        self._depth -= lazy
        self._scopes.pop()

    def _annotation(self, node: ast.AST | None) -> None:
        if node is None:
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval")
            except SyntaxError:
                return
        self._depth += self._lazy_annotations
        self.visit(node)
        self._depth -= self._lazy_annotations

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in HAZARD_NAMES:
            self.hazards.append(f"{node.id} at line {node.lineno}")
        if isinstance(node.ctx, ast.Load) and not self._local(node.id):
            (self.lazy if self._depth else self.eager).add(node.id)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in HAZARD_CALLS:
            self.hazards.append(f"{node.func.id}() at line {node.lineno}")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.rebinds |= set(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.hazards.append(f"nonlocal at line {node.lineno}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.hazards.append(f"relative import at line {node.lineno}")

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        a = node.args
        for default in [*a.defaults, *[d for d in a.kw_defaults if d]]:
            self.visit(default)
        if not isinstance(node, ast.Lambda):
            for deco in node.decorator_list:
                self.visit(deco)
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
                if arg is not None:
                    self._annotation(arg.annotation)
            self._annotation(node.returns)
        body = node.body if isinstance(node.body, list) else [node.body]
        self._scoped("function", node, list(body), lazy=True)

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expr in [*node.decorator_list, *node.bases, *[k.value for k in node.keywords]]:
            self.visit(expr)
        self._scoped("class", node, list(node.body), lazy=False)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._annotation(node.annotation)
        self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    def _comprehension(self, node: ast.ListComp) -> None:
        gens = node.generators
        self.visit(gens[0].iter)
        rest: list[ast.AST] = [g.iter for g in gens[1:]] + [c for g in gens for c in g.ifs]
        rest += [getattr(node, p) for p in ("elt", "key", "value") if hasattr(node, p)]
        self._scoped("comprehension", node, rest, lazy=False)

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension


def _slug(marker: str) -> str:
    title = marker[len(MARKER) :].rstrip("- ").strip()
    head = title.split(":")[0].replace("'s ", " ")
    return re.sub(r"[^a-z0-9]+", "_", head.lower()).strip("_")


def _title(marker: str) -> str:
    title = marker[len(MARKER) :].rstrip("- ").strip()
    return title[:1].upper() + title[1:] + ("" if title.endswith(".") else ".")


def _is_main_block(node: ast.stmt) -> bool:
    test = node.test if isinstance(node, ast.If) else None
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def read_families(path: Path) -> list[tuple[str, str]]:
    """Rows of `<module>: <marker text>`; a marker that starts with the text lands in the module."""
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or (line.startswith("#") and not line.startswith(MARKER)):
            continue
        module, sep, marker = line.partition(": ")
        if not sep or not marker.startswith(MARKER) or not module.isidentifier():
            raise Refused(f"a families row is not `<module>: {MARKER}<title>`: {line!r}")
        rows.append((module, marker.rstrip("- ").rstrip()))
    return rows


@dataclass
class Plan:
    """The whole move: what lands where, and why anything left its family."""

    source: list[str]
    docstring: list[str]
    imports: list[ast.stmt]
    units: list[Unit]
    titles: dict[str, str]
    sections: int
    families: int
    hoisted: list[tuple[Unit, str]] = field(default_factory=list)
    tail: list[Unit] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    main: list[str] = field(default_factory=list)

    @property
    def external(self) -> set[str]:
        return set().union(*(binds(n) for n in self.imports))

    @property
    def owner(self) -> dict[str, str]:
        """For every name the module defines, the module its last binding lands in."""
        found: dict[str, str] = {}
        for unit in self.units:
            for name in unit.binds:
                found[name] = unit.module
        return found

    def modules(self) -> dict[str, list[Unit]]:
        out: dict[str, list[Unit]] = {}
        for unit in self.units:
            if unit.module != INIT:
                out.setdefault(unit.module, []).append(unit)
        return out


def _lead_split(gap: list[str]) -> tuple[list[str], list[str]]:
    for i, line in enumerate(gap):
        if line.startswith(MARKER):
            return gap[:i], gap[i:]
    return [], gap


def _family(marker: str, prefix: str, families: list[tuple[str, str]]) -> str:
    for module, text in families:
        if marker.startswith(text):
            return module
    return _slug(marker) if marker and marker.startswith(prefix) else HUB


def plan(
    text: str,
    *,
    prefix: str = FAMILY,
    families: list[tuple[str, str]] | None = None,
    door: bool = False,
    rebound: frozenset[str] = frozenset(),
) -> Plan:
    """Read a module and decide, statement by statement, where each one lands."""
    rows = families or []
    source = text.splitlines()
    tree = ast.parse(text)
    body = list(tree.body)
    refusals: list[str] = []
    docstring: list[str] = []
    end = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        node = body.pop(0)
        docstring, end = source[node.lineno - 1 : node.end_lineno], node.end_lineno or 0
    imports: list[ast.stmt] = []
    while body and isinstance(body[0], IMPORTS):
        node = body.pop(0)
        imports.append(node)
        end = node.end_lineno or 0
    lazy_annotations = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "__future__"
        and any(a.name == "annotations" for a in n.names)
        for n in imports
    )
    main_node = body.pop() if door and body and _is_main_block(body[-1]) else None
    markers = [(i + 1, line) for i, line in enumerate(source) if line.startswith(MARKER)]
    titles = {HUB: "What two or more sections share, and what they need at import time."}
    units: list[Unit] = []
    for node in body:
        if isinstance(node, IMPORTS):
            refusals.append(f"an import after the first definition, line {node.lineno}")
            imports.append(node)
            continue
        if not isinstance(node, CARRIED):
            refusals.append(f"a top-level {type(node).__name__} at line {node.lineno}")
            continue
        first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        if first <= end:
            raise Refused(f"two statements share line {first}")
        trail, lead = (
            _lead_split(source[end : first - 1]) if units else ([], source[end : first - 1])
        )
        if units:
            units[-1].trail = trail
        unit = Unit(node=node, first=first, last=node.end_lineno or node.lineno, lead=lead)
        reads = Reads(lazy_annotations)
        reads.visit(node)
        unit.binds = binds(node)
        if reads.hazards:
            refusals.append(f"{unit.binds} reads its own location: {', '.join(reads.hazards)}")
        unit.eager, unit.lazy = reads.eager, reads.lazy - reads.eager
        unit.rebinds = reads.rebinds
        unit.marker = next((m for n, m in reversed(markers) if n <= first), "")
        unit.module = _family(unit.marker, prefix, rows)
        if unit.module != HUB:
            titles.setdefault(unit.module, _title(unit.marker))
        units.append(unit)
        end = unit.last
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in imports):
        raise Refused("a star import: the names it binds cannot be read from the source")
    if not units:
        raise Refused("nothing to move after the imports")
    main: list[str] = []
    if main_node is not None:
        units[-1].trail = []
        main = source[end:]
    else:
        units[-1].trail = source[end:]
    unused = [t for _, t in rows if not any(m.startswith(t) for _, m in markers)]
    refusals += [f"a families row names no marker: {t}" for t in unused]
    family_markers = [m for _, m in markers if _family(m, prefix, rows) != HUB]
    slugs = Counter(_slug(m) for m in family_markers if not any(m.startswith(t) for _, t in rows))
    if clash := sorted(s for s, n in slugs.items() if n > 1):
        raise Refused(f"two family markers name one module: {', '.join(clash)}")
    p = Plan(source, docstring, imports, units, titles, len(markers), len(family_markers))
    p.refusals, p.main = refusals, main
    names = p.external | set().union(*(u.binds for u in units))
    for unit in units:
        unit.eager &= names
        unit.lazy &= names
    if both := sorted(p.external & set().union(*(u.binds for u in units))):
        raise Refused(f"imported and also defined at top level: {', '.join(both)}")
    _place(p)
    _check_rebindings(p)
    _check_rebound(p, rebound)
    return p


def _live_binder(units: list[Unit], name: str, before: int) -> Unit:
    found = [u for u in units[:before] if name in u.binds]
    if not found:
        raise Refused(f"{units[before].label} reads {name} before anything binds it")
    return found[-1]


def _place(p: Plan) -> None:
    """An unread aggregator goes to the package; what a module needs at import goes to the hub."""
    readers = Counter(n for u in p.units for n in u.eager | u.lazy)
    for i, unit in enumerate(p.units):
        binders = {_live_binder(p.units, name, i).module for name in unit.eager - p.external}
        foreign = binders - {unit.module, HUB}
        if foreign and unit.module != HUB and not any(readers[n] for n in unit.binds):
            unit.module = INIT
            p.tail.append(unit)
    moved = True
    while moved:
        moved = False
        for i, unit in enumerate(p.units):
            for name in sorted(unit.eager - p.external):
                binder = _live_binder(p.units, name, i)
                if binder.module in (unit.module, HUB) or unit.module == INIT:
                    continue
                if binder.module == INIT:
                    raise Refused(f"{unit.label} reads {name}, which only the package binds")
                if any(name in u.binds and u.module == unit.module for u in p.units[i:]):
                    raise Refused(f"{unit.label} reads {name} at import time, then rebinds it")
                p.hoisted.append((binder, f"{unit.label} reads {name} at import time"))
                binder.module = HUB
                moved = True


def shape(node: ast.AST) -> str:
    """The statement's AST, docstrings included, without positions."""
    return ast.dump(copy.deepcopy(node), include_attributes=False)


def _check_rebindings(p: Plan) -> None:
    """A name bound in two modules is safe only where every reader sees the value it saw before."""
    last = p.owner
    for unit in p.units:
        for name in unit.lazy - p.external:
            if last[name] == unit.module:
                continue
            mine = [u for u in p.units if name in u.binds and u.module == unit.module]
            final = [u for u in p.units if name in u.binds][-1]
            if mine and shape(mine[-1].node) != shape(final.node):
                raise Refused(f"{unit.label} reads {name}, bound differently in two modules")


def _check_rebound(p: Plan, outside: frozenset[str]) -> None:
    """A rebound name lives in one module, and no other module binds it by `from … import`."""
    owner = p.owner
    by_global = {n: u for u in p.units for n in u.rebinds}
    for name in sorted(set(by_global) | (outside & set(owner))):
        home = owner.get(name, by_global[name].module if name in by_global else HUB)
        why = f"global in {by_global[name].label}" if name in by_global else "assigned from outside"
        for unit in p.units:
            if name in unit.rebinds and unit.module != home:
                p.refusals.append(
                    f"{name} is rebound ({why}) in {unit.module}, but lives in {home}"
                )
            elif name in unit.eager | unit.lazy and unit.module not in (home, INIT):
                p.refusals.append(
                    f"{name} is rebound ({why}); {unit.label} in {unit.module} would bind a copy"
                )


# --- rendering, in the form the import sorter and the formatter already accept -------


def _natural(text: str) -> list[object]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def _member_key(member: tuple[str, str]) -> tuple[int, list[object]]:
    name = member[0]
    cased = [c for c in name if c.isalpha()]
    if len(name) > 1 and cased and all(c.isupper() for c in cased):
        return (0, _natural(name))
    return (1 if name[:1].isupper() else 2, _natural(name))


def _section(module: str, first_party: set[str]) -> int:
    top = module.split(".")[0]
    if top == "__future__":
        return 0
    if top in sys.stdlib_module_names:
        return 1
    return 3 if top in first_party else 2


@dataclass(frozen=True)
class Imp:
    """One import statement, reduced to what the sorter orders it by."""

    module: str
    names: tuple[tuple[str, str], ...]
    plain: bool = False
    foot: bool = False

    def render(self) -> str:
        tag = f"  {NOQA}" if self.foot else ""
        if self.plain:
            name, alias = self.names[0]
            return f"import {name}{f' as {alias}' if alias else ''}{tag}"
        parts = [f"{n} as {a}" if a else n for n, a in sorted(set(self.names), key=_member_key)]
        line = f"from {self.module} import {', '.join(parts)}{tag}"
        if len(line) <= LINE_LENGTH:
            return line
        inner = "".join(f"    {part},\n" for part in parts)
        return f"from {self.module} import ({tag}\n{inner})"


def _block(imps: list[Imp], first_party: set[str]) -> str:
    groups: dict[int, list[Imp]] = {}
    for imp in imps:
        groups.setdefault(_section(imp.module, first_party), []).append(imp)
    out: list[str] = []
    for key in sorted(groups):
        plain = sorted((i for i in groups[key] if i.plain), key=lambda i: _natural(i.names[0][0]))
        bare: dict[str, Imp] = {}
        aliased: list[Imp] = []
        for imp in (i for i in groups[key] if not i.plain):
            for name, alias in imp.names:
                if alias:
                    aliased.append(Imp(imp.module, ((name, alias),), foot=imp.foot))
                else:
                    had = bare.get(imp.module)
                    names = (had.names if had else ()) + ((name, ""),)
                    bare[imp.module] = Imp(imp.module, names, foot=imp.foot)
        ordered = sorted(
            [*bare.values(), *aliased],
            key=lambda i: (_natural(i.module), _member_key(min(i.names, key=_member_key))),
        )
        out.append("\n".join(i.render() for i in [*plain, *ordered]))
    return "\n\n".join(out)


def _external(imports: list[ast.stmt], wanted: set[str] | None) -> list[Imp]:
    imps: list[Imp] = []
    for node in imports:
        if isinstance(node, ast.Import):
            for a in node.names:
                if wanted is None or (a.asname or a.name).split(".")[0] in wanted:
                    imps.append(Imp(a.name, ((a.name, a.asname or ""),), plain=True))
        elif isinstance(node, ast.ImportFrom):
            keep = tuple(
                (a.name, a.asname or "")
                for a in node.names
                if wanted is None or node.module == "__future__" or (a.asname or a.name) in wanted
            )
            if keep:
                imps.append(Imp(node.module or "", keep))
    return imps


def _chunk(source: list[str], unit: Unit, previous: Unit | None) -> str:
    lead = list(unit.lead)
    blanks = 0
    while lead and not lead[0].strip():
        lead.pop(0)
        blanks += 1
    if previous is None:
        blanks = 2 if unit.is_def and not lead[:1] else 1
    elif previous.is_def or unit.is_def:
        blanks = 2
    trail = list(unit.trail)
    while trail and not trail[-1].strip():
        trail.pop()
    lines = lead + source[unit.first - 1 : unit.last] + trail
    return "\n" * min(blanks, 2) + "\n".join(lines) + "\n"


def _chunks(source: list[str], units: list[Unit]) -> str:
    out, previous = "", None
    for unit in units:
        out += _chunk(source, unit, previous)
        previous = unit
    return out


def _declare_hub_first(block: str, dotted: str) -> str:
    """The contract line above the hub import, set off by the blank line the import sorter wants."""
    head = f"from {dotted}.{HUB} import"
    lines = block.split("\n")
    at = next(i for i, line in enumerate(lines) if line.startswith(head))
    gap = [""] if at and lines[at - 1].strip() else []
    return "\n".join([*lines[:at], *gap, CONTRACT, *lines[at:]])


def render(p: Plan, dotted: str, first_party: set[str], door: bool = False) -> dict[str, str]:
    """Every file of the package, by file name; with a door, `<door>` is the module's new text."""
    files: dict[str, str] = {}
    owner = p.owner
    hub_foot, hub_read = False, False
    for module, units in p.modules().items():
        defined = set().union(*(u.binds for u in units))
        reads = set().union(*(u.eager | u.lazy for u in units))
        top = _external(p.imports, reads & p.external)
        foot: list[Imp] = []
        for name in sorted(reads - defined - p.external):
            src = owner[name]
            if src == HUB:
                top.append(Imp(f"{dotted}.{HUB}", ((name, ""),)))
                hub_read = True
            else:
                foot.append(Imp(f"{dotted}.{src}", ((name, ""),), foot=True))
        hub_foot = hub_foot or (module == HUB and bool(foot))
        text = f'"""{p.titles[module]}"""\n\n{_block(top, first_party)}\n'
        text += _chunks(p.source, units)
        if foot:
            text += f"\n\n{_block(foot, first_party)}\n"
        files[f"{module}.py"] = text
    imps = _external(p.imports, None)
    for name, module in sorted(owner.items()):
        if module != INIT:
            imps.append(Imp(f"{dotted}.{module}", ((name, name if name[:1] == "_" else ""),)))
    block = _block(imps, first_party)
    if hub_foot and hub_read:
        block = _declare_hub_first(block, dotted)
    public = sorted(n for n in set(owner) | p.external if not n.startswith("_"))
    exported = "__all__ = [\n" + "".join(f'    "{n}",\n' for n in public) + "]\n"
    text = "\n".join(p.docstring) + f"\n\n{block}\n"
    text += _chunks(p.source, p.tail)
    text += ("\n\n" if p.tail else "\n") + exported
    files[f"{INIT}.py"] = text
    if door:
        imps = _external(p.imports, None)
        imps += [Imp(dotted, ((n, n if n[:1] == "_" else ""),)) for n in sorted(owner)]
        text = "\n".join(p.docstring) + f"\n\n{_block(imps, first_party)}\n\n{exported}"
        main = list(p.main)
        while main and not main[0].strip():
            main.pop(0)
        files["<door>"] = text + ("\n\n" + "\n".join(main).rstrip() + "\n" if main else "")
    return files


# --- the proof ------------------------------------------------------------------------


@dataclass
class Stmt:
    """One top-level statement of one file, keyed so a move cannot change it unseen."""

    key: tuple[str, str, str]
    file: str
    line: int
    label: str


@dataclass
class Census:
    """Every top-level statement of a module or a package, its imports and its comments."""

    stmts: list[Stmt] = field(default_factory=list)
    order: dict[str, list[Stmt]] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)
    exported: list[str] = field(default_factory=list)
    comments: Counter[tuple[str, str]] = field(default_factory=Counter)
    imports: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)
    binds: dict[str, set[str]] = field(default_factory=dict)
    reads: dict[str, set[str]] = field(default_factory=dict)
    trees: dict[str, list[ast.stmt]] = field(default_factory=dict)


def _label(node: ast.stmt) -> str:
    if isinstance(node, DEFS):
        return node.name
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return ",".join(sorted(binds(node)))
    return f"{type(node).__name__}: {ast.unparse(node).splitlines()[0][:60]}"


def _key(node: ast.stmt) -> tuple[str, str, str]:
    kind = "def" if isinstance(node, DEFS) else "bind" if isinstance(node, CARRIED) else "stmt"
    return (kind, _label(node) if kind != "stmt" else type(node).__name__, shape(node))


def _comment_anchors(text: str, body: list[ast.stmt]) -> Counter[tuple[str, str]]:
    """Each comment keyed by the statement it precedes, or the one above when a marker follows."""
    spans = [
        (min([n.lineno, *(d.lineno for d in getattr(n, "decorator_list", []))]), n.end_lineno, n)
        for n in body
    ]
    lines = text.splitlines()
    out: Counter[tuple[str, str]] = Counter()
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT or tok.string in (NOQA, CONTRACT):
            continue
        row = tok.start[0]
        inside = [n for a, b, n in spans if a <= row <= (b or a)]
        after = [(a, n) for a, _, n in spans if a > row]
        before = [n for a, _, n in spans if a < row]
        if inside:
            anchor: ast.stmt | None = inside[0]
        elif after and before and not tok.string.startswith(MARKER.strip()):
            gap = lines[row : after[0][0] - 1]
            anchor = before[-1] if any(g.startswith(MARKER) for g in gap) else after[0][1]
        else:
            anchor = after[0][1] if after else None
        out[(tok.string, _label(anchor) if anchor else "the foot")] += 1
    return out


def _import_map(node: ast.stmt) -> dict[str, tuple[str, str]]:
    if isinstance(node, ast.Import):
        return {(a.asname or a.name).split(".")[0]: (a.name, "") for a in node.names}
    assert isinstance(node, ast.ImportFrom)  # noqa: S101 — narrows the ast type for mypy; a False is a bug, not input
    return {a.asname or a.name: (node.module or "", a.name) for a in node.names}


def census(files: dict[str, str], entry: str) -> Census:
    """Every top-level statement in order, every import, and every comment with its anchor."""
    c = Census()
    for name, text in sorted(files.items()):
        body = list(ast.parse(text).body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        lazy = any(
            isinstance(n, ast.ImportFrom)
            and n.module == "__future__"
            and n.names[0].name == "annotations"
            for n in body
        )
        c.trees[name], c.order[name], c.imports[name] = body, [], {}
        c.binds[name], c.reads[name] = set(), set()
        anchored = [n for n in body if not isinstance(n, IMPORTS)]
        c.comments += _comment_anchors(text, anchored)
        for node in body:
            bound = binds(node)
            c.binds[name] |= bound
            if name == entry:
                c.names |= bound
            if isinstance(node, IMPORTS):
                c.imports[name].update(_import_map(node))
                continue
            reads = Reads(lazy)
            reads.visit(node)
            c.reads[name] |= reads.eager | reads.lazy
            if bound == {"__all__"} and isinstance(node, ast.Assign):
                if name == entry:
                    c.exported = list(ast.literal_eval(node.value))
                    c.names.discard("__all__")
                continue
            stmt = Stmt(_key(node), name, node.lineno, _label(node))
            c.stmts.append(stmt)
            c.order[name].append(stmt)
    return c


def _dotted(files: dict[str, str]) -> str:
    """The package's import name, read off the imports its `__init__` makes of its own files."""
    stems = {Path(n).stem for n in files}
    for node in ast.parse(files[f"{INIT}.py"]).body:
        if isinstance(node, ast.ImportFrom) and node.module and "." in node.module:
            head, _, stem = node.module.rpartition(".")
            if stem in stems:
                return head
    return ""


_PROBE = """
import importlib, importlib.util, os, sys, types
where, dotted, module, alone, settings = sys.argv[1:6]
if settings:
    os.environ["DJANGO_SETTINGS_MODULE"] = settings
    import django
    django.setup()
if alone == "1":
    pkg = types.ModuleType(dotted)
    pkg.__path__ = [where]
    sys.modules[dotted] = pkg
else:
    spec = importlib.util.spec_from_file_location(
        dotted, where + "/__init__.py", submodule_search_locations=[where]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = pkg
    spec.loader.exec_module(pkg)
importlib.import_module(dotted + "." + module)
"""


def _cold(package: Path, dotted: str, module: str, alone: bool, django: str = "") -> str:
    """Import one module in a fresh interpreter; the empty string is a clean import."""
    root = package.resolve().parents[len(dotted.split(".")) - 1]
    inherited = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path.cwd()), str(root), *inherited]))
    argv = [sys.executable, "-B", "-c", _PROBE, str(package.resolve()), dotted, module]
    done = subprocess.run(
        [*argv, "1" if alone else "0", django], capture_output=True, text=True, env=env, check=False
    )
    tail = (done.stderr.strip().splitlines() or ["exit " + str(done.returncode)])[-1]
    return "" if done.returncode == 0 else tail


def _cold_imports(
    package: Path, files: dict[str, str], django: str = ""
) -> tuple[list[str], list[str], int]:
    dotted = _dotted(files)
    mods = sorted(Path(n).stem for n in files if "/" not in n and n[0] != "<" and n != f"{INIT}.py")
    if not dotted:
        return [f"{package}: the package's import name cannot be read off its __init__"], [], 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        through = list(pool.map(lambda m: _cold(package, dotted, m, False, django), mods))
        alone = list(pool.map(lambda m: _cold(package, dotted, m, True, django), mods))
    failed = [f"{m}: {why}" for m, why in zip(mods, through, strict=True) if why]
    hub_first = [m for m, why in zip(mods, alone, strict=True) if why]
    return failed, hub_first, len(mods)


def _ordered(before: Census, after: Census) -> list[str]:
    """Statements that share a file keep the order they had in the old module."""
    queue: dict[tuple[str, str, str], list[int]] = {}
    for i, s in enumerate(before.stmts):
        queue.setdefault(s.key, []).append(i)
    found: list[str] = []
    for name, stmts in sorted(after.order.items()):
        last: Stmt | None = None
        at = -1
        for s in stmts:
            if not queue.get(s.key):
                continue
            here = queue[s.key].pop(0)
            if here < at and last is not None:
                found.append(f"order: {last.label} now precedes {s.label} in {name}")
            if here > at:
                at, last = here, s
    return found


def _resolution(before: Census, after: Census, dotted: str, door: str) -> list[str]:
    """Every name a file reads is bound in it, and every import names a binder that exists."""
    loose = {"annotations"} | MODULE_NAMES | set(dir(builtins))
    old_unbound = set().union(*(r - before.binds[n] for n, r in before.reads.items())) - loose
    old_imports = {v for m in before.imports.values() for v in m.values()}
    found: list[str] = []
    for name in sorted(after.trees):
        for read in sorted(after.reads[name] - after.binds[name] - loose - old_unbound):
            found.append(f"unbound: {read} is read in {name} and nothing there binds it")
        for local, (module, orig) in sorted(after.imports[name].items()):
            if module == dotted or module.startswith(f"{dotted}."):
                stem = module[len(dotted) + 1 :] or INIT
                if orig not in after.binds.get(f"{stem}.py", set()):
                    found.append(f"import: {orig} from {module} in {name}, which does not bind it")
            elif (module, orig) not in old_imports and module != "__future__":
                found.append(f"import added: {orig} from {module or '(plain)'} in {name}")
            if name not in (f"{INIT}.py", door) and local not in after.reads[name]:
                if module != "__future__":
                    found.append(f"import unread: {local} in {name}")
    return found


def _hub_first(files: dict[str, str], dotted: str) -> list[str]:
    """Where the hub and a family import each other, `__init__` imports the hub first, declared."""
    hub = files.get(f"{HUB}.py")
    if hub is None:
        return []
    foot = [
        n
        for n in ast.parse(hub).body
        if isinstance(n, ast.ImportFrom) and NOQA in hub.splitlines()[n.lineno - 1]
    ]
    readers = [
        f
        for f, t in files.items()
        if f != f"{HUB}.py" and f"from {dotted}.{HUB} import" in t and f != f"{INIT}.py"
    ]
    if not (foot and readers):
        return []
    init = files[f"{INIT}.py"]
    own = [
        n.module
        for n in ast.parse(init).body
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith(f"{dotted}.")
    ]
    found = []
    if own[:1] != [f"{dotted}.{HUB}"]:
        found.append(
            f"hub-first: {INIT}.py imports {own[:1]} before the hub, which the families need first"
        )
    if CONTRACT not in init.splitlines():
        found.append(
            f"hub-first: {INIT}.py depends on importing the hub first and does not declare it"
        )
    return found


def prove(
    old_text: str, package: Path, door: Path | None = None, cold: bool = True, django: str = ""
) -> int:
    """Every statement moved in identical shape and order; nothing added, nothing lost."""
    files = {
        str(p.relative_to(package)): p.read_text(encoding="utf-8")
        for p in sorted(package.rglob("*.py"))
        if "__pycache__" not in p.parts
    }
    if f"{INIT}.py" not in files:
        print(f"!! {package}: no {INIT}.py", file=sys.stderr)
        return 2
    door_name = ""
    if door is not None:
        door_name = f"<door {door.name}>"
        files[door_name] = door.read_text(encoding="utf-8")
    entry = door_name or f"{INIT}.py"
    before = census({"<old>": old_text}, "<old>")
    after = census(files, entry)
    olds = Counter(s.key for s in before.stmts)
    news = Counter(s.key for s in after.stmts)
    where = {s.key: f"{s.file}:{s.line}" for s in after.stmts}
    lost, added = olds - news, news - olds
    lost_labels = {(k[0], k[1]) for k in lost}
    changed = sorted({(k[0], k[1]) for k in added} & lost_labels)
    findings = [
        f"changed: {k} {n} at {where[a]}" for k, n in changed for a in added if a[:2] == (k, n)
    ]
    findings += [f"missing: {k[0]} {k[1]}" for k in sorted(lost.elements()) if k[:2] not in changed]
    findings += [
        f"added: {k[0]} {k[1]} at {where[k]}"
        for k in sorted(added.elements())
        if k[:2] not in changed
    ]
    findings += _ordered(before, after)
    dotted = _dotted(files)
    findings += _resolution(before, after, dotted, door_name)
    findings += _hub_first(files, dotted)
    c_lost, c_new = before.comments - after.comments, after.comments - before.comments
    for text, anchor in sorted(c_lost.elements()):
        moved = [a for t, a in c_new if t == text]
        findings.append(
            f"comment moved: {text} (was before {anchor}, now before {moved[0]})"
            if moved
            else f"comment lost: {text} (before {anchor})"
        )
    lost_texts = {t for t, _ in c_lost}
    findings += [
        f"comment added: {t} (before {a})"
        for t, a in sorted(c_new.elements())
        if t not in lost_texts
    ]
    public = sorted(n for n in before.names if not n.startswith("_"))
    if before.names != after.names:
        gone, new = sorted(before.names - after.names), sorted(after.names - before.names)
        findings.append(f"names differ: lost {gone} · added {new}")
    if after.exported != public:
        findings.append(f"__all__ differs from the {len(public)} public names")
    defs = [s for s in before.stmts if s.key[0] == "def"]
    same = sum((olds & news).values())
    print(f"statements: {len(before.stmts)} before · {len(after.stmts)} after · identical: {same}")
    kept = not any(f.startswith("order") for f in findings)
    print(f"defs: {len(defs)} · changed: {len(changed)} · order kept: {kept}")
    print(
        f"names: {len(before.names)} before · {len(after.names)} after · __all__ "
        f"{'equals' if after.exported == public else 'differs from'} the {len(public)} public"
    )
    print(
        f"comments: {sum(before.comments.values())} before · {sum(c_lost.values())} lost or "
        f"moved · {sum(c_new.values())} added · files: {len(files)}"
    )
    if cold:
        django = django or (django_settings("") if imports_django(old_text) else "")
        failed, hub_first, total = _cold_imports(package, files, django)
        print(
            f"cold imports: {total - len(failed)} of {total} · "
            f"alone: {total - len(hub_first)} of {total}"
        )
        findings += [f"cold import: {f}" for f in failed]
        if hub_first and CONTRACT not in files[f"{INIT}.py"].splitlines():
            findings.append(
                f"alone: {len(hub_first)} import only after the hub, undeclared: "
                + ", ".join(hub_first)
            )
    for line in findings:
        print(f"!! {line}", file=sys.stderr)
    return 2 if findings else 0


# --- the readers of the module, in other files ------------------------------------------


@dataclass(frozen=True)
class Reader:
    """One line in a tracked file that would read the module differently after the move."""

    file: str
    line: int
    kind: str
    mechanism: bool
    text: str

    def render(self) -> str:
        cls = "mechanism" if self.mechanism else "prose"
        return f"{cls:<9} {self.kind:<22} {self.file}:{self.line}  {self.text.strip()[:90]}"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def _prose_lines(path: str, text: str) -> dict[int, int]:
    """For each line, the column where prose starts (a comment, a docstring); absent is code."""
    out: dict[int, int] = {}
    if path.endswith(".py"):
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    out[tok.start[0]] = min(out.get(tok.start[0], tok.start[1]), tok.start[1])
            for node in ast.walk(ast.parse(text)):
                body = getattr(node, "body", None)
                if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
                    doc = body[0].value
                    if isinstance(doc, ast.Constant) and isinstance(doc.value, str):
                        for row in range(doc.lineno, (doc.end_lineno or doc.lineno) + 1):
                            out[row] = 0
        except (SyntaxError, tokenize.TokenError):
            pass
        return out
    if path.endswith(".md"):
        return {i: 0 for i in range(1, text.count("\n") + 2)}
    for i, line in enumerate(text.splitlines(), 1):
        hit = re.search(r"(^|\s)#", line)
        if hit:
            out[i] = hit.start()
    return out


def _aliases(text: str, dotted: str) -> set[str]:
    parent, _, leaf = dotted.rpartition(".")
    found: set[str] = set()
    if parent:
        for names in re.findall(rf"from\s+{re.escape(parent)}\s+import\s+\(?([^)\n]*)", text):
            for part in names.split(","):
                bits = part.split()
                if bits and bits[0] == leaf:
                    found.add(bits[2] if len(bits) == 3 and bits[1] == "as" else leaf)
    for alias in re.findall(rf"import\s+{re.escape(dotted)}(?:\s+as\s+(\w+))?", text):
        found.add(alias or dotted)
    named = rf"[\"'](?:{re.escape(dotted)}|{re.escape(leaf)})[\"']"
    found |= set(re.findall(rf"^\s*(\w+)\s*=\s*[\w.]+\([^\n]*{named}", text, re.M))
    return found


def _named_writes(text: str, aliases: set[str]) -> dict[int, list[tuple[str, int]]]:
    """By line, every call over the text taking an alias then a name string, read as a write."""
    out: dict[int, list[tuple[str, int]]] = {}
    for alias in aliases:
        call = rf"(?<![\w.])([\w.]+)\(\s*{re.escape(alias)}\s*,\s*[\"'](\w+)[\"']"
        for m in re.finditer(call, text):
            if m.group(1).rpartition(".")[2] in ("getattr", "hasattr"):
                continue
            row = text.count("\n", 0, m.start()) + 1
            col = m.start() - text.rfind("\n", 0, m.start()) - 1
            out.setdefault(row, []).append((f"assigns {m.group(2)}", col))
    return out


def readers(module: Path) -> list[Reader]:
    """Every tracked line naming the module's path, reading its location, or assigning onto it."""
    root = Path(_git(module.resolve().parent, "rev-parse", "--show-toplevel").strip())
    rel = module.resolve().relative_to(root).as_posix()
    dotted = rel.removesuffix(".py").replace("/", ".")
    texts: dict[str, str] = {}
    for path in _git(root, "ls-files", "-z").split("\0"):
        try:
            texts[path] = (root / path).read_text(encoding="utf-8") if path else ""
        except (OSError, UnicodeDecodeError):
            continue
    code = "\n".join(t for p, t in texts.items() if p.endswith((".py", ".sh", ".json", ".yaml")))
    found: set[Reader] = set()
    for path, text in sorted(texts.items()):
        aliases = _aliases(text, dotted) if path != rel else set()
        if rel not in text and not aliases:
            continue
        prose = _prose_lines(path, text)
        calls = _named_writes(text, aliases)
        for i, line in enumerate(text.splitlines(), 1):
            hits = list(calls.get(i, []))
            for m in re.finditer(re.escape(rel), line):
                cite = re.match(r"::\w", line[m.end() : m.end() + 3])
                read = path.endswith(".md") and bool(cite) and path in code
                hits.append(("path", -1 if read else m.start()))
            for alias in aliases:
                a = re.escape(alias)
                for m in re.finditer(rf"(?<![\w.]){a}\.(__file__|__spec__)", line):
                    hits.append(("location", m.start()))
                for m in re.finditer(rf"(?:getsourcefile|getfile)\(\s*{a}\s*\)", line):
                    hits.append(("location", m.start()))
                for m in re.finditer(rf"(?<![\w.]){a}\.([A-Za-z_]\w*)\s*[-+*/|&]?=(?!=)", line):
                    hits.append((f"assigns {m.group(1)}", m.start()))
            for m in re.finditer(rf"(?:setattr|patch)\(\s*[\"']{re.escape(dotted)}\.(\w+)", line):
                hits.append((f"assigns {m.group(1)}", m.start()))
            for kind, col in hits:
                mech = col < 0 or i not in prose or prose[i] > col
                found.add(Reader(path, i, kind, mech, line))
    return sorted(found, key=lambda r: (r.file, r.line, r.kind))


def _print_readers(found: list[Reader]) -> None:
    for r in found:
        print(r.render())
    mech = [r for r in found if r.mechanism]
    assigned = sorted({r.kind.split()[1] for r in mech if r.kind.startswith("assigns")})
    print(
        f"readers: {len(mech)} mechanism · {len(found) - len(mech)} prose · "
        f"in {len({r.file for r in found})} files · assigned: {', '.join(assigned) or 'none'}"
    )


def _print_map(p: Plan, dotted: str, files: dict[str, str]) -> None:
    print(f"sections: {p.sections} · families: {p.families} · files: {len(files)}")
    for module, units in p.modules().items():
        defs = sum(1 for u in units if u.is_def)
        lines = files[f"{module}.py"].count("\n")
        print(f"  {dotted}.{module:<34} {lines:>5} lines · {defs:>3} defs · {p.titles[module]}")
    print(f"  {dotted}.{INIT:<34} {files[f'{INIT}.py'].count(chr(10)):>5} lines")
    if "<door>" in files:
        print(f"  the door{'':<34} {files['<door>'].count(chr(10)):>5} lines")
    for unit, why in p.hoisted:
        print(f"hub: {unit.label} — {why}")
    for unit in p.tail:
        print(f"package: {unit.label} — reads other families at import time; nothing reads it")


# --- the proof's own canaries ---------------------------------------------------------

FIXTURE = '''"""A module the self-test splits."""

from __future__ import annotations

import os

SHARED = 1
OTHER = 2


def twice() -> int:
    """Answer the second family's value twice."""
    return beta() * 2


# --- rule a: the first family ------------------------------------------------------


def alpha() -> int:
    """Answer the shared value through the second family."""
    # alpha reads beta at call time
    return SHARED + beta()


A_FIRST = 1
A_SECOND = 2


# --- rule b: the second family -----------------------------------------------------


def beta() -> int:
    """Answer the other value."""
    return OTHER + len(os.sep)


def gamma() -> int:
    """Answer the first family's value."""
    return alpha()
'''

REBOUND = (
    FIXTURE
    + '''

def bump() -> None:
    """Count one more."""
    global SHARED
    SHARED += 1
'''
)


DOOR_FOOT = """

def main() -> int:
    \"\"\"Answer through the first family.\"\"\"
    return alpha()


# the door keeps the entry point
if __name__ == "__main__":
    raise SystemExit(main())
"""


def _foot_import_deleted(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if NOQA not in line) + "\n"


def _comment_moved(text: str) -> str:
    comment = "    # alpha reads beta at call time"
    return text.replace(comment + "\n", "") + comment.strip() + "\n"


def _swapped(text: str) -> str:
    return text.replace("A_FIRST = 1\nA_SECOND = 2", "A_SECOND = 2\nA_FIRST = 1")


CANARIES: list[tuple[str, str, str, object, str]] = [
    (
        "(a) a docstring changed",
        "rule_b.py",
        "edit",
        lambda t: t.replace("the other value", "another value"),
        "changed: def beta",
    ),
    (
        "(b) a top-level expression added",
        "rule_a.py",
        "edit",
        lambda t: t + '\nprint("planted")\n',
        "added: stmt Expr",
    ),
    (
        "(c) a top-level block added",
        "rule_a.py",
        "edit",
        lambda t: t + "\nif True:\n    PLANTED = 1\n",
        "added: stmt If",
    ),
    ("(d) a foot import deleted", "rule_a.py", "edit", _foot_import_deleted, "unbound: beta"),
    (
        "(e) a comment moved off its statement",
        "rule_a.py",
        "edit",
        _comment_moved,
        "comment moved: # alpha reads beta",
    ),
    (
        "(f) two assignments swapped",
        "rule_a.py",
        "edit",
        _swapped,
        "order: A_SECOND now precedes A_FIRST",
    ),
    (
        "(g) a file in a sub-directory",
        "sub/extra.py",
        "new",
        lambda t: "def extra() -> int:\n    return 1\n",
        "added: def extra",
    ),
    (
        "(h) an assignment added, by name",
        "rule_b.py",
        "edit",
        lambda t: t + "\nPLANTED_NAME = 3\n",
        "added: bind PLANTED_NAME",
    ),
    (
        "(i) the hub-first contract removed",
        "__init__.py",
        "edit",
        lambda t: t.replace(CONTRACT + "\n", ""),
        "does not declare it",
    ),
]


def _split(text: str, where: Path) -> Path:
    package = where / "fx"
    package.mkdir(parents=True)
    for name, body in render(plan(text), "fx", {"fx"}).items():
        (package / name).write_text(body, encoding="utf-8")
    return package


def _door_split(text: str, where: Path) -> tuple[Path, Path]:
    package = where / "fx"
    package.mkdir(parents=True)
    files = render(plan(text, door=True), "fx", {"fx"}, door=True)
    door = where / "door.py"
    door.write_text(files.pop("<door>"), encoding="utf-8")
    for name, body in files.items():
        (package / name).write_text(body, encoding="utf-8")
    return package, door


def _quiet_prove(
    old: str, package: Path, door: Path | None = None, django: str = ""
) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = prove(old, package, door, django=django)
    return code, out.getvalue() + err.getvalue()


DJANGO_FIXTURE = '''"""A module that reads a Django model at import time."""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

# --- the model


def the_model() -> type:
    """The model this module imported."""
    return ContentType


# --- the label


def the_label() -> str:
    """The model's app label."""
    return str(ContentType._meta.app_label)
'''

DJANGO_SETTINGS = """SECRET_KEY = "split-module-selftest"  # pragma: allowlist secret
INSTALLED_APPS = ["django.contrib.contenttypes"]
USE_TZ = True
"""


def _django_selftest(where: Path) -> int:
    """Split a module that imports a model and expect --django to cold-import every file."""
    package = _split(DJANGO_FIXTURE, where)
    (where / "fx_settings.py").write_text(DJANGO_SETTINGS, encoding="utf-8")
    code, said = _quiet_prove(DJANGO_FIXTURE, package, django="fx_settings")
    line = next((x for x in said.splitlines() if x.startswith("cold imports:")), "")
    total = len(list(package.glob("*.py"))) - 1
    ok = code == 0 and line.startswith(f"cold imports: {total} of {total}") and total > 0
    print(f"{'fired' if ok else 'DID NOT FIRE'}: a Django module splits and proves — exit {code}")
    if not ok:
        print(said)
    was = os.environ.get("DJANGO_SETTINGS_MODULE")
    os.environ["DJANGO_SETTINGS_MODULE"] = "fx_settings"
    try:
        code, said = _quiet_prove(DJANGO_FIXTURE, package)
    finally:
        if was is None:
            os.environ.pop("DJANGO_SETTINGS_MODULE")
        else:
            os.environ["DJANGO_SETTINGS_MODULE"] = was
    line = next((x for x in said.splitlines() if x.startswith("cold imports:")), "")
    unasked = code == 0 and line.startswith(f"cold imports: {total} of {total}")
    print(
        f"{'fired' if unasked else 'DID NOT FIRE'}: a module importing Django boots it unasked "
        f"— exit {code}"
    )
    if not unasked:
        print(said)
    return int(not ok) + int(not unasked)


WRITERS = '''"""Writes onto the module through a helper and over several lines."""

import pk.mod as M


def _swap(module, name, value):
    """Set a module global and hand back what was there."""
    was = getattr(module, name)
    setattr(module, name, value)
    return was


def test_writes(monkeypatch):
    """Write two globals and read one."""
    _swap(M, "HELPED", 1)
    monkeypatch.setattr(
        M,
        "SPREAD",
        2,
    )
    assert getattr(M, "READ")
'''

READER_CANARIES = [
    ("(k) a write through a helper", "assigns HELPED", True),
    ("(l) a write over several lines", "assigns SPREAD", True),
    ("a read through getattr", "assigns READ", False),
]


def _readers_selftest(where: Path) -> int:
    """Sweep a planted checkout and expect each write listed and the read not."""
    (where / "pk").mkdir(parents=True)
    (where / "pk" / "mod.py").write_text("HELPED = SPREAD = READ = 0\n", encoding="utf-8")
    (where / "test_writers.py").write_text(WRITERS, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(where)], check=True)
    _git(where, "add", "pk/mod.py", "test_writers.py")
    found = [r for r in readers(where / "pk" / "mod.py") if r.mechanism]
    broken = 0
    for what, kind, listed in READER_CANARIES:
        hit = next((r for r in found if r.kind == kind), None)
        ok = (hit is not None) == listed
        broken += not ok
        word = ("fired" if ok else "DID NOT FIRE") if listed else ("silent" if ok else "NOT SILENT")
        print(f"{word}: {what} — " + (hit.render() if hit else f"no `{kind}` listed"))
    return broken


def selftest() -> int:
    """Plant each hole into a split of the fixture and expect the proof to name it."""
    broken = 0
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        code, said = _quiet_prove(FIXTURE, _split(FIXTURE, base / "untouched"))
        quiet = code == 0
        print(f"{'silent' if quiet else 'NOT SILENT'}: the untouched split — exit {code}")
        broken += not quiet
        if not quiet:
            print(said)
        with_main = FIXTURE + DOOR_FOOT
        code, said = _quiet_prove(with_main, *_door_split(with_main, base / "door"))
        quiet = code == 0
        print(f"{'silent' if quiet else 'NOT SILENT'}: the split behind a door — exit {code}")
        broken += not quiet
        if not quiet:
            print(said)
        for i, (what, target, how, change, expect) in enumerate(CANARIES):
            package = _split(FIXTURE, base / f"c{i}")
            path = package / target
            path.parent.mkdir(parents=True, exist_ok=True)
            old = path.read_text(encoding="utf-8") if how == "edit" else ""
            path.write_text(change(old), encoding="utf-8")  # type: ignore[operator]
            code, said = _quiet_prove(FIXTURE, package)
            line = next((x for x in said.splitlines() if x.startswith("!!") and expect in x), "")
            ok = code == 2 and bool(line)
            broken += not ok
            print(
                f"{'fired' if ok else 'DID NOT FIRE'}: {what} — exit {code} · "
                + (line or said.strip())
            )
        broken += _readers_selftest(base / "readers")
        broken += _django_selftest(base / "django")
    try:
        p = plan(REBOUND)
        why = [r for r in p.refusals if "SHARED is rebound" in r and "would bind a copy" in r]
    except Refused:
        why = []
    print(
        f"{'fired' if why else 'DID NOT FIRE'}: (j) a rebound name read by another module — "
        + "; ".join(why[:1])
    )
    broken += not why
    print(
        "selftest: "
        + ("every canary fired, every negative stayed silent" if not broken else f"{broken} BROKEN")
    )
    return 2 if broken else 0


def imports_django(text: str) -> bool:
    """Whether the module imports Django itself, so its cold imports need `django.setup()`."""
    for node in ast.walk(ast.parse(text)):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom) and not node.level:
            names = [node.module or ""]
        if any(n == "django" or n.startswith("django.") for n in names):
            return True
    return False


def django_settings(named: str, root: Path | None = None) -> str:
    """The settings module `--django` sets up: the one named, the environment's, or manage.py's."""
    if named or os.environ.get("DJANGO_SETTINGS_MODULE"):
        return named or os.environ["DJANGO_SETTINGS_MODULE"]
    manage = (root or Path.cwd()) / "manage.py"
    text = manage.read_text(encoding="utf-8") if manage.is_file() else ""
    found = re.search(r"setdefault\(\s*[\"']DJANGO_SETTINGS_MODULE[\"']\s*,\s*[\"']([\w.]+)", text)
    return found.group(1) if found else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="exit 0 moved, proved or listed · 2 refused: a case it cannot carry, a failed proof",
    )
    parser.add_argument("module", type=Path, nargs="?")
    parser.add_argument("package", type=Path, nargs="?")
    parser.add_argument("--prove", action="store_true", help="prove an existing package")
    parser.add_argument(
        "--old",
        type=Path,
        help="with --prove: the old module's text, when the module is a door now",
    )
    parser.add_argument("--replace", action="store_true", help="regenerate an existing package")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the map and every refusal, write nothing"
    )
    parser.add_argument(
        "--door", action="store_true", help="keep the module as a door that re-exports the package"
    )
    parser.add_argument(
        "--prefix",
        default=FAMILY,
        help=f"a marker starting with this is a family (default {FAMILY!r})",
    )
    parser.add_argument(
        "--families", type=Path, help="rows of `<module>: <marker text>`, read before --prefix"
    )
    parser.add_argument(
        "--readers", action="store_true", help="list every tracked reader of the module"
    )
    parser.add_argument(
        "--rekeyed", action="append", default=[], help="a file whose mechanism readers are re-keyed"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="plant each hole and expect the proof to fire"
    )
    parser.add_argument(
        "--django",
        nargs="?",
        const="",
        metavar="SETTINGS",
        help="run django.setup() before each cold import (default: the environment's, then "
        "manage.py's settings module)",
    )
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    django = ""
    if args.django is not None:
        django = django_settings(args.django)
        if not django:
            print(
                "!! --django: no settings module named, in the environment or in manage.py",
                file=sys.stderr,
            )
            return 2
    if args.module is None:
        parser.error("the module is required")
    if args.readers:
        _print_readers(readers(args.module))
        return 0
    if args.package is None:
        parser.error("the package is required")
    if args.prove:
        old = args.old or args.module
        if args.door and not args.old:
            parser.error("--prove --door reads the old module from --old")
        return prove(
            old.read_text(encoding="utf-8"),
            args.package,
            args.module if args.door else None,
            django=django,
        )
    old_text = args.module.read_text(encoding="utf-8")
    root = Path.cwd()
    try:
        dotted = ".".join(args.package.resolve().relative_to(root).parts)
    except ValueError:
        print(f"!! {args.package} is not under {root}", file=sys.stderr)
        return 2
    first_party = {d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")}
    try:
        swept = readers(args.module)
    except subprocess.CalledProcessError:
        swept = []
        print(f"readers: {args.module} is not in a git checkout; nothing swept")
    rekeyed = {Path(f).resolve() for f in args.rekeyed}
    root_dir = Path(_git(root, "rev-parse", "--show-toplevel").strip()) if swept else root
    outside = frozenset(
        r.kind.split()[1] for r in swept if r.mechanism and r.kind.startswith("assigns")
    )
    try:
        families = read_families(args.families) if args.families else None
        p = plan(old_text, prefix=args.prefix, families=families, door=args.door, rebound=outside)
        files = render(p, dotted, first_party, door=args.door)
    except Refused as why:
        print(f"!! refused: {why}", file=sys.stderr)
        return 2
    _print_map(p, dotted, files)
    pending: dict[str, list[Reader]] = {}
    for r in swept:
        if r.mechanism and (root_dir / r.file).resolve() not in rekeyed:
            pending.setdefault(r.file, []).append(r)
    p.refusals += [
        f"mechanism readers not named --rekeyed: {f} ({len(rs)}: "
        f"{', '.join(f'{r.line} {r.kind}' for r in rs[:4])}{' …' if len(rs) > 4 else ''})"
        for f, rs in pending.items()
    ]
    for refusal in p.refusals:
        print(f"!! refused: {refusal}", file=sys.stderr)
    if p.refusals or args.dry_run:
        return 2 if p.refusals else 0
    package: Path = args.package
    if package.exists():
        strays = [x for x in package.iterdir() if x.suffix != ".py" and x.name != "__pycache__"]
        if not args.replace or strays:
            print(
                f"!! {package} exists: --replace regenerates a package of .py files",
                file=sys.stderr,
            )
            return 2
        for stale in package.glob("*.py"):
            stale.unlink()
    package.mkdir(parents=True, exist_ok=True)
    door_text = files.pop("<door>", None)
    for name, text in files.items():
        (package / name).write_text(text, encoding="utf-8")
    if door_text is None:
        args.module.unlink()
        return prove(old_text, package, django=django)
    args.module.write_text(door_text, encoding="utf-8")
    return prove(old_text, package, args.module, django=django)


if __name__ == "__main__":
    sys.exit(main())
