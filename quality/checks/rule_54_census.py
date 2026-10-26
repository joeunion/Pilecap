"""Rule 54's `census:` — the reads THIS tree refuses, and what opens each."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import _parse, _py_files, _read

# --- rule 54's `census:` — the reads THIS tree refuses, and what opens each --
#
# A product folds the template and meets Phase R's hard read rule at its
# OWN doors: `GET /api/v1/memberships/mine/` answers "You may not read this
# membership." to a hat-less caller, because `list_memberships` asks
# `membership.read` and a caller with no hat is asked at the tenant-wide union.
# CHANGELOG item 5 says "one kwarg or one valve line each" and names no door,
# so the product reads `apps/core/authz.py`, then every `selectors.py`, then
# every door that reaches one — a session's work to recover a list this tree
# already knows. This is that list, printed by `--explain 54` (C0's seam).
#
# IT READS AND NEVER WRITES, and it asks no question a walker here does not
# already answer. The population is clause (d)'s own — the same file walk, the
# same public `get_`/`list_` filter, the same return-annotation filter, the
# same `_function_valve` reader — and the three facts each row adds come from
# the three walkers that own them: rule 54's `_asks` for the key, rule 55's
# `_node_verdict` for where that key resolves, rule 42's door walk for who
# knocks. A fourth derivation would be a second opinion about `allows()`, and
# the whole value of a row here is that a reader can hold it against
# `apps/core/authz.py` and find them saying one thing.


def _clipped(reason: str | None, width: int = 56) -> str:
    """A valve's reason, cut to one readable clause. The valve line is the truth.

    `_function_valve` hands back the rest of the comment LINE, which in this
    tree is a sentence that continues on the next one. A census row is one
    line and a reason that runs off the end of it stops being readable, so it
    is cut HERE and the row already names the file and the line to read it at.
    """
    text = " ".join((reason or "").split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _read_ask_calls(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[int, ast.expr | None]:
    """`lineno -> the third argument` for each `require`/`allows` in this body.

    The one join between rule 54's `_asks`, which names the KEY at a line and
    throws the call away, and rule 55's `_node_verdict`, which judges the THIRD
    ARGUMENT of a call. Keyed on the line `_asks` already reported, so the two
    can never disagree about which call they are describing.
    """
    out: dict[int, ast.expr | None] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name not in _ASK_FUNCTIONS:
            continue
        out[node.lineno] = node.args[2] if len(node.args) > 2 else None
    return out


def _read_at_phrase(arg: ast.expr | None, typed: set[str], rooted: set[str]) -> str:
    """Where `allows()` will resolve this ask, in the words a reader needs.

    `_node_verdict` stays the ONE classifier of a third argument — it is rule
    55's because rule 55 is the rule that turns the answer into a finding — and
    this names its verdict for the other half of the same fact. `where_of`
    takes the node the argument names, the acting hat when it names none, and
    `None` (the tenant-wide union) when there is no hat either; so "no third
    argument" is the row that 403s a hat-less caller, and that is the row a
    product is looking for.
    """
    if arg is None or (isinstance(arg, ast.Constant) and arg.value is None):
        return "the acting hat, or the tenant-wide union when the caller has none"
    resolved, how = _node_verdict(arg, typed, rooted)
    if resolved:
        if isinstance(arg, ast.Call) or (isinstance(arg, ast.Name) and arg.id in rooted):
            return f"the tenant root ({how})"
        if isinstance(arg, ast.Name):
            return f"the node the caller handed in ({how})"
        return f"the node the row names ({how})"
    return f"the node the row names (`{ast.unparse(arg)[:48]}`)"


def _reading_doors(root: Path) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]:
    """Rule 42's door walk, keeping the PATH: which door reaches which selector.

    Rule 42 asks this of `services.py` and throws the path away, because a
    service only ever needed the reached/not-reached bit. A reader holding a
    403 needs the door itself, so this reuses the walk that finds them —
    `_door_modules`, `_called_qualnames`, `_door_kind` — and keeps the module
    it matched at. Two maps rather than one, and for rule 42's reason: a call
    the imports resolve answers by QUALIFIED name, and a call they cannot
    (`self.x()`, a registry lookup) answers by bare name and says so, rather
    than being silently dropped or silently believed.
    """
    qualified: dict[tuple[str, str], list[str]] = {}
    bare: dict[str, list[str]] = {}
    for path in _door_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        site = f"{rel} ({_door_kind(root, path)})"
        for module, name in _called_qualnames(root, tree, _dotted(root, path)):
            if module == UNRESOLVED:
                if site not in bare.setdefault(name, []):
                    bare[name].append(site)
            elif module.endswith(".selectors"):
                if site not in qualified.setdefault((module, name), []):
                    qualified[(module, name)].append(site)
    return qualified, bare


#: What this census cannot see. Printed with the rows rather than folded into
#: rule 54's `does_not_cover:`, because it is the CENSUS's blind spot and not
#: the rule's — rule 54 is exactly as true on a tree where every one of these
#: bites, and a reader holding the LIST is the one who needs the caveat.
_READS_CENSUS_BLIND = (
    "a predicate (`POLICIES`) that refuses after the key is held; a grant, a "
    "withhold or a custom role written at RUNTIME, which is rows and not code; "
    "which hat a given request resolves (`X-Org`, per request); and a selector a "
    "door reaches THROUGH a helper or a service, which rule 42's walk reads as "
    "the helper's call and not the door's"
)


def reads_census(root: Path, rule: dict) -> list[str]:
    """Rule 54's `census:` — every read this tree asks for, and what opens it.

    One line per selector in clause (d)'s population, sorted by file. Each
    names the site, the model and kind it hands back, the key it asks and where
    that key resolves, who gets the 403, the opening, and the doors that reach
    it. A selector that asks NOTHING is printed too and says so: it is clause
    (d)'s own finding, it refuses nobody today, and the product that grants a
    role tomorrow discovers it then.

    Returns `[]` only on a tree with no such selector at all, which the rule's
    `selectors_censused` floor already refuses.
    """
    kinds = model_kinds(root)
    qualified_doors, bare_doors = _reading_doors(root)
    rows: list[str] = []
    asking = opened_count = rekinded_count = silent = 0
    for path in _py_files(root, "apps", named={"selectors.py"}):
        rel = path.relative_to(root).as_posix()
        tree = _parse(path)
        if tree is None:
            continue
        src = _read(path)
        lines = src.splitlines()
        here = _dotted(root, path)
        constants = string_constants(root, path, tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (node.name.startswith("get_") or node.name.startswith("list_")):
                continue
            returned = sorted(n for n in _annotation_names(node.returns) if kinds.get(n))
            if not returned:
                continue
            model = returned[0]
            kind = kinds[model]
            open_reason = _function_valve(node, src, lines, _READ_OPEN_RE)
            kind_reason = _function_valve(node, src, lines, _READ_KIND_RE)
            is_open = open_reason is not None and open_reason.holds
            is_rekinded = kind_reason is not None and kind_reason.holds
            typed, rooted = _organization_names(node)
            thirds = _read_ask_calls(node)
            reads = [
                (line, key)
                for line, key, _ in _asks(node, constants)
                if key and key.rsplit(".", 1)[-1] == "read"
            ]
            sites = qualified_doors.get((here, node.name))
            if sites:
                door = ", ".join(sites)
            elif node.name in bare_doors:
                door = ", ".join(bare_doors[node.name]) + " — by bare name, unresolved"
            else:
                door = "no door found"

            if reads:
                asked_line, asked_key = reads[0]
                at = _read_at_phrase(thirds.get(asked_line), typed, rooted)
                asks = f"asks {asked_key} at {at}"
                if asked_key == f"{kind}.read":
                    asking += 1
                    refuses = (
                        f"403s: no tenant; hat-less unless a membership holds {kind}.read; "
                        'a custom role without "*.read"'
                    )
                    opening = (
                        f"opening: `# read-open: <reason>` in {node.name}'s own source, or "
                        f"grant {kind}.read to the role"
                    )
                else:
                    rekinded_count += 1
                    valve = "declared" if is_rekinded else "UNDECLARED — rule 54 (e)"
                    asks += f" (a kind other than {kind}: `# read-kind:` {valve})"
                    refuses = f"403s: no tenant; anyone not holding {asked_key} where it resolves"
                    opening = (
                        f"opening: ask {kind}.read instead, or `# read-kind: {kind}` saying "
                        "which aggregate answers for it"
                    )
            elif is_open:
                opened_count += 1
                asks = f"asks nothing — `# read-open: {_clipped(open_reason.reason)}`"
                refuses = "403s: never here (the door's own `auth=` is the whole gate)"
                opening = "opening: already open"
            else:
                silent += 1
                asks = "asks NOTHING — rule 54 (d)'s read finding"
                refuses = (
                    "403s: nobody today — every door inherits this read for free, and the "
                    "first product to grant a narrow role discovers it then"
                )
                opening = (
                    f'opening: take `actor: Actor` and call require(actor, "{kind}.read", '
                    "<the row, or nothing to ask at the hat>), or `# read-open: <reason>`"
                )
            rows.append(
                f"{rel}:{node.lineno} {node.name} -> {model} ({kind}); {asks}; "
                f"{refuses}; {opening}; door: {door}"
            )
    if not rows:
        return []
    header = (
        f"{len(rows)} public get_/list_ selector(s) over a kind — rule 54 (d)'s population: "
        f"{asking} ask their own kind's read, {rekinded_count} ask another kind's, "
        f"{opened_count} are open by `# read-open:`, {silent} ask nothing "
        f"(= rule 54's read-class findings)"
    )
    return [header, *rows, f"does not cover: {_READS_CENSUS_BLIND}"]


from quality.checks.rule_13_clauses_i_iv import (  # noqa: E402
    _ASK_FUNCTIONS,
    _asks,
    model_kinds,
    string_constants,
)
from quality.checks.rule_26 import _annotation_names  # noqa: E402
from quality.checks.rule_42 import (  # noqa: E402
    UNRESOLVED,
    _called_qualnames,
    _door_kind,
    _door_modules,
    _dotted,
)
from quality.checks.rule_54 import _READ_KIND_RE, _READ_OPEN_RE, _function_valve  # noqa: E402
from quality.checks.rule_55 import _node_verdict, _organization_names  # noqa: E402
