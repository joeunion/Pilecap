"""Rule 40: a header is read by its declared name."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import (
    CheckResult,
    _enclosing_functions,
    _exempt,
    _function_at,
    _parse,
    _py_files,
)

# --- rule 40: a header is read by its declared name ----------------------------
#
# Three populations, one rule, because they are three views of one contract —
# "the spelling of a header lives in exactly one place":
#
# A. INBOUND READS. `request.headers.get(<arg>)` / `request.headers[<arg>]`,
# `request.META[<HTTP_*>]`, and the ASGI `scope["headers"]` loop (the
# socket and MCP doors, which have no `request`). The read is legal when
# `<arg>` is — or is derived from — a module-level header DECLARATION.
# B. THE DECLARATION POPULATION. Module-level assignments named `HEADER` or
# `*_HEADER` whose value is a string literal. Derived by the same walk,
# never listed: a new constant is in scope with no edit here.
# C. `Remedy(label, "header:<name>")`. A refusal that politely points at a
# header nobody reads is a dead end, so the name after `header:` must be
# some declaration's VALUE; and every destination's KIND must be one the
# `Remedy` docstring in `apps/core/exceptions.py` enumerates — read from
# that docstring, never re-typed here, so a sixth kind added there is
# seen with no edit to this file.
#
# Plus the CORS census (N100b-3): every declaration read by an HTTP request
# reader must appear, lowercased, in `CORS_ALLOW_HEADERS`. A header the API
# reads and a browser may not send is a door that is open on the server and
# shut in the client, which is exactly how `X-Org` was unreachable from a
# cross-origin front end for a cycle with no error anywhere.

# : The receivers whose `.headers` is an INBOUND request's. A `response.headers`
# : read is somebody else's contract (`Retry-After`, `Content-Type` off a
# : third-party reply) and is declared in `does_not_cover`, not scanned.
_REQUEST_RECEIVERS = {"request", "req"}

_CORS_SETTINGS_FILE = "config/settings/base.py"
_CORS_SETTING = "CORS_ALLOW_HEADERS"
_REMEDY_KIND_SOURCE = "apps/core/exceptions.py"
_REMEDY_DESTINATION_RE = re.compile(r"`([a-z]+):([A-Za-z0-9_.-]+)`")


def _is_header_constant_name(name: str) -> bool:
    """The declaration grammar: `HEADER`, or anything ending `_HEADER`.

    `apps/core/idempotency.py` names its own `HEADER` because the module IS the
    subject; every other declaration qualifies the noun. Both are declarations.
    """
    return name == "HEADER" or name.endswith("_HEADER")


def header_declarations(root: Path) -> dict[str, list[tuple[str, int, str]]]:
    """name -> [(file, line, value)] for every module-level header declaration.

    DERIVED by the same walk that finds the reads, so a constant added anywhere
    under `apps/` or `config/` is in the population with no edit to this file
    and no hand-list to go stale.
    """
    found: dict[str, list[tuple[str, int, str]]] = {}
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        for node in tree.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not isinstance(value, ast.Constant):
                continue
            if not isinstance(value.value, str):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and _is_header_constant_name(target.id):
                    found.setdefault(target.id, []).append((rel, node.lineno, value.value))
    return found


def _literal_root(node: ast.expr) -> str | None:
    """The str/bytes literal this expression is built from, if it is built from one.

    `"X-Tenant"`, `b"x-org"` and `"authorization".encode()` all answer; a name
    does not. This is what tells a spelled-out header name from a named one.
    """
    current = node
    while isinstance(current, ast.Call):
        current = current.func
    while isinstance(current, ast.Attribute):
        current = current.value
        while isinstance(current, ast.Call):
            current = current.func
    if isinstance(current, ast.Constant) and isinstance(current.value, (str, bytes)):
        return (
            current.value
            if isinstance(current.value, str)
            else current.value.decode("latin-1", "replace")
        )
    return None


def _name_root(node: ast.expr) -> str | None:
    """The bare name this expression is rooted at — `TENANT_HEADER.lower().encode()`
    is rooted at `TENANT_HEADER`, which is the whole point of allowing a chain."""
    current = node
    while True:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            current = current.value
        else:
            break
    return _callee_name(current)


def _scope_header_loops(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.For]:
    """The `for key, value in scope["headers"]` loops in this function.

    The structural test for "this is an ASGI header lookup": a loop over a
    `headers` collection taken off a `scope`. It is deliberately the LOOP and
    not the function's text — `scheme.lower() != "bearer"` beside a
    `request.headers.get(...)` is not a header name, and a text test read it as
    one while this was being built.
    """
    out: list[ast.For] = []
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            source = ast.dump(node.iter)
            if "'headers'" in source and "scope" in source:
                out.append(node)  # type: ignore[arg-type]
    return out


def _scope_header_helpers(tree: ast.Module) -> dict[str, int]:
    """`name -> parameter index` for every function that IS an ASGI header lookup.

    Derived, not named: a function qualifies when it walks `scope[...]`/
    `scope.get("headers"...)` and compares the key against something rooted in
    one of its own PARAMETERS. That parameter is the header name, so every call
    to the function is a read and its argument at that index is `<arg>`.

    A function whose loop compares against a LITERAL is not a helper — it is a
    read, spelled inline, and `_header_reads` reports it where it stands.
    """
    helpers: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _scope_header_loops(node):
            continue
        params = [a.arg for a in _all_args(node)]
        # One hop of local rebinding, because that is how all three of these
        # helpers are written: `wanted = name.lower().encode()`, and then the
        # loop compares against `wanted`. Chasing exactly one hop keeps the
        # walk honest about what it can see (declared in does_not_cover).
        local_root: dict[str, str] = {}
        for assign in ast.walk(node):
            if not isinstance(assign, ast.Assign) or len(assign.targets) != 1:
                continue
            target = assign.targets[0]
            root = _name_root(assign.value)
            if isinstance(target, ast.Name) and root is not None:
                local_root[target.id] = root
        for compare in ast.walk(node):
            if not isinstance(compare, ast.Compare):
                continue
            for side in [compare.left, *compare.comparators]:
                root = _name_root(side)
                root = local_root.get(root or "", root)
                if root is not None and root in params and root != "scope":
                    helpers[node.name] = params.index(root)
                    break
    return helpers


def _header_reads(tree: ast.Module) -> list[tuple[int, ast.expr, str]]:
    """(line, the header-name expression, what kind of read it is) for one module."""
    reads: list[tuple[int, ast.expr, str]] = []
    helpers = _scope_header_helpers(tree)
    for node in ast.walk(tree):
        # `request.headers.get(name)` / `request.META.get("HTTP_X")`
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if func.attr in {"get", "__getitem__"} and isinstance(func.value, ast.Attribute):
                owner = func.value
                if owner.attr in {"headers", "META"} and node.args:
                    root = _name_root(owner.value)
                    if root in _REQUEST_RECEIVERS:
                        reads.append((node.lineno, node.args[0], "request"))
            if func.attr in helpers:
                index = helpers[func.attr]
                if len(node.args) > index:
                    reads.append((node.lineno, node.args[index], "scope"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in helpers:
                index = helpers[node.func.id]
                if len(node.args) > index:
                    reads.append((node.lineno, node.args[index], "scope"))
        # `request.headers[name]` / `request.META["HTTP_X"]`
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            owner = node.value
            if owner.attr in {"headers", "META"}:
                root = _name_root(owner.value)
                if root in _REQUEST_RECEIVERS and isinstance(node.ctx, ast.Load):
                    reads.append((node.lineno, node.slice, "request"))
    # The loop itself: inside a function that walks an ASGI `scope`'s headers,
    # a comparison against a spelled-out name IS the read — there is no
    # `request` there to hang it off, which is precisely why the socket and MCP
    # doors are where a second spelling hides.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for loop in _scope_header_loops(node):
            for compare in ast.walk(loop):
                if not isinstance(compare, ast.Compare):
                    continue
                for side in [compare.left, *compare.comparators]:
                    if _literal_root(side) is not None:
                        reads.append((compare.lineno, side, "scope-loop"))
    return reads


def _imported_modules(tree: ast.Module) -> dict[str, str]:
    """`local name -> the module file it was imported from`, for `from X import Y`.

    Two apps legitimately declare a `TENANT_HEADER`: the HTTP one (`X-Tenant`)
    and Temporal's (`djb-tenant-id`). Which VALUE a read names is therefore the
    import's business, not the name's, and the census below would otherwise
    demand a Temporal header in the browser's CORS list.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            where = node.module.replace(".", "/") + ".py"
            for alias in node.names:
                out[alias.asname or alias.name] = where
    return out


def _declared_values(
    declarations: dict[str, list[tuple[str, int, str]]],
    name: str,
    *,
    here: str,
    imports: dict[str, str],
) -> list[str]:
    """The value(s) this name means AT THIS READ — same module, then the import."""
    entries = declarations.get(name) or []
    if len(entries) <= 1:
        return [value for _, _, value in entries]
    same = [value for file, _, value in entries if file == here]
    if same:
        return same
    source = imports.get(name)
    if source:
        via = [value for file, _, value in entries if file == source]
        if via:
            return via
    return [value for _, _, value in entries]


def _remedy_kinds(root: Path) -> set[str]:
    """The destination kinds, read off `Remedy`'s own docstring in core.exceptions.

    The kinds are the template's published contract and they are enumerated in
    exactly one place — the class docstring that explains what a destination is.
    Reading them from there rather than re-typing them here is what makes a
    sixth kind a one-file change: add it to the docstring beside the others and
    this rule accepts it, with no edit to `quality/`.
    """
    tree = _parse(root / _REMEDY_KIND_SOURCE)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Remedy":
            doc = ast.get_docstring(node) or ""
            return {m.group(1) for m in _REMEDY_DESTINATION_RE.finditer(doc)}
    return set()


def _remedy_destinations(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, destination) for every `Remedy(...)` whose destination is a literal."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node.func)
        if name != "Remedy":
            continue
        candidate: ast.expr | None = None
        if len(node.args) >= 2:
            candidate = node.args[1]
        for keyword in node.keywords:
            if keyword.arg == "destination":
                candidate = keyword.value
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            out.append((node.lineno, candidate.value))
    return out


def _cors_allowed(root: Path) -> list[str] | None:
    """`CORS_ALLOW_HEADERS` as the settings file declares it, read by AST.

    By AST and not by importing settings, for the reason the settings file
    itself gives: settings are read before the app registry is ready, so the
    census cannot travel as an import in either direction. The LAST module-level
    assignment wins, so a canary appended to the file is what the check sees.
    """
    tree = _parse(root / _CORS_SETTINGS_FILE)
    if tree is None:
        return None
    found: list[str] | None = None
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == _CORS_SETTING:
                try:
                    value = ast.literal_eval(node.value)  # type: ignore[arg-type]
                except (ValueError, TypeError, SyntaxError):
                    return None
                if isinstance(value, (list, tuple)):
                    found = [str(v) for v in value]
    return found


def header_contracts(root: Path, rule: dict) -> CheckResult:
    """Rule 40. A header is read by its declared name, and a remedy names one.

    Three clauses over three derived populations (the reads, the declarations,
    the remedies) plus the CORS census. Every one of them is a walk, so the
    populations grow with the tree and nothing here is a list somebody has to
    remember to extend.
    """
    out = CheckResult()
    declarations = header_declarations(root)
    values = {value for entries in declarations.values() for _, _, value in entries}
    out.count("header_declarations", len(declarations))

    allowed_literals = {
        str(entry) for entry in (rule.get("scope") or {}).get("standard_http_headers") or []
    }
    kinds = _remedy_kinds(root)
    if not kinds:
        out.hit(
            _REMEDY_KIND_SOURCE,
            0,
            "the Remedy docstring no longer enumerates its destination kinds, so this rule "
            "has nothing to validate a destination's kind against — the kind set is the "
            "contract and it is declared there, once (ADR core-5)",
        )
    out.count("remedy_kinds", len(kinds))

    read_values: set[str] = set()
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        spans = _enclosing_functions(tree)
        imports = _imported_modules(tree)
        for line, arg, kind in _header_reads(tree):
            out.count("header_reads", 1)
            if _exempt(rule, rel, _function_at(spans, line)):
                continue
            named = _name_root(arg)
            if named is not None and named in declarations:
                if kind == "request":
                    # The CORS census population: what an HTTP door reads. The
                    # socket and MCP doors are not preflighted and are not in it.
                    read_values.update(
                        _declared_values(declarations, named, here=rel, imports=imports)
                    )
                continue
            literal = _literal_root(arg)
            if literal is None:
                # A name that is not a declaration and not a literal: threaded
                # through a parameter, or built at runtime. Declared blind spot.
                out.count("header_reads_unresolved", 1)
                continue
            if literal in allowed_literals:
                continue
            match = sorted(
                name
                for name, entries in declarations.items()
                if any(value.lower() == literal.lower() for _, _, value in entries)
            )
            suggestion = (
                " — " + " / ".join(f"`{m}`" for m in match) + " already declares this "
                "exact spelling; name it"
                if match
                else " — declare it once as a module-level `*_HEADER` constant and read that"
            )
            out.hit(
                rel,
                line,
                f"the {kind} header read names {literal!r} as a literal rather than a "
                f"declared constant{suggestion}. A second spelling of a header is a "
                "fail-open the compiler cannot see: the read simply finds nothing, and "
                "the request is answered as though the caller had asked for nothing",
                root=root,
                klass=kind,
            )

        for line, destination in _remedy_destinations(tree):
            out.count("remedy_destinations", 1)
            kind, _, name = destination.partition(":")
            if kinds and kind not in kinds:
                out.hit(
                    rel,
                    line,
                    f"Remedy destination {destination!r} uses kind {kind!r}, which the "
                    f"Remedy docstring does not enumerate ({', '.join(sorted(kinds))}) — a "
                    "destination a renderer cannot classify is a button with nowhere to go. "
                    f"Add the kind beside the others in {_REMEDY_KIND_SOURCE}, or use one",
                    root=root,
                )
                continue
            if kind != "header":
                continue
            out.count("header_remedies", 1)
            if name in values or name in allowed_literals:
                continue
            out.hit(
                rel,
                line,
                f"Remedy destination {destination!r} names a header no declaration in this "
                "tree spells — the refusal politely points the caller at a header the "
                "server does not read. Name a declared constant's value",
                root=root,
            )

    # --- the CORS census (N100b-3): a list, derived, not a copy ----------------
    allowed = _cors_allowed(root)
    if allowed is None:
        out.hit(
            _CORS_SETTINGS_FILE,
            0,
            f"{_CORS_SETTING} could not be read as a literal tuple, so the census that "
            "keeps the browser's allow-list in step with the headers this API reads is "
            "enforcing nothing",
        )
    else:
        lowered = {entry.lower() for entry in allowed}
        out.count("cors_census_headers", len(read_values))
        for value in sorted(read_values):
            if value.lower() in lowered:
                continue
            out.hit(
                _CORS_SETTINGS_FILE,
                0,
                f"{_CORS_SETTING} does not list {value.lower()!r}, and an HTTP door reads "
                f"the header {value!r} — a cross-origin browser client cannot send it at "
                "all, so every one of its requests is answered as though it had not, with "
                "no error anywhere (the hat nobody could put on)",
            )
    return out


from quality.checks.rule_26 import _all_args  # noqa: E402
from quality.checks.rule_36 import _callee_name  # noqa: E402
