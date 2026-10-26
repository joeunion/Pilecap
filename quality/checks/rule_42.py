"""Rule 42: every service is reachable through a door."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import (
    CheckResult,
    _app_dirs,
    _parse,
    _py_files,
    _read,
    api_modules,
    count_model_classes,
    count_routes,
    facade_reexports,
)
from quality.worlds import (
    SERVICE_MODULE,
    SKIP_PARTS,
    comment_reason,
    decorator_names,
    service_modules,
)

# --- rule 42: every service is reachable through a door -----------------------
#
# The owner's ruling: "mechanisms without doors is a miss in
# the development standard". The template grew a foundation — organizations,
# memberships, invitations, tenant settings, erasure, webhook endpoints, the run
# ledger — and none of it was reachable by anybody who was not holding a shell.
# A mechanism nobody can call is indistinguishable from a mechanism that was
# never built, except that it costs the same to maintain.
#
# THE QUESTION IS CLOSED, which is what makes it a rule and not a review: the
# population is every `@service` in the tree (rule 13 already guarantees that
# every write is one), and the answer is whether a DOOR module calls it by name.
# Door modules are the conventional ones the mounts already discover — api.py,
# mcp.py, consumers.py, activities.py, receivers.py and the shell's
# management/commands/** — so "what is a door" is not this rule's opinion.
#
# REACHABILITY IS DIRECT, DELIBERATELY. A service called only by another service
# is counted doorless, because that is exactly the finding: `create_organization`
# reached through `bootstrap_tenant` still has no door of its own, and the wave
# that gives the foundation doors is measured by this number falling. The valve
# for a service that genuinely should not have one — `emit()`, an operator act —
# is `# door: <reason>`, counted and printed like every other valve in this
# engine.
#
# ONE MARKER, TWO CLAIMS. The valve was born for the unreached service ("this
# deliberately has no door") and is read for the internal-only one too ("this
# is deliberately a workflow's step, or the shell's"). A second marker spelling
# would have been a second grammar to learn for a claim that is the same claim
# one degree weaker; the CLASS of the finding, and the count it lands in, are
# what tell the two apart. Read by `quality.worlds.comment_reason`, the one
# valve reader, with its one floor.

_DOOR_RE = re.compile(r"#\s*door:\s*(.*)$")

# : The conventional door modules — the same names the mounts discover. A door
# : mounted some other way is invisible here, and that is in `does_not_cover`.
DOOR_GLOBS = (
    "apps/*/api.py",
    "apps/*/api/*.py",
    "apps/*/mcp.py",
    "apps/*/consumers.py",
    "apps/*/activities.py",
    "apps/*/receivers.py",
    "apps/*/management/commands/*.py",
)

# The census used to answer one bit — reached or not — and a bit cannot
# tell `list_widgets`, which a person with a session can call, from
# `close_outbox`, which only this tree's own worker ever calls. Both read
# "reachable", and the peer's report is right that the two blur: a management
# command is a shell, and an activity is a workflow step. Neither is a door
# somebody outside this tree can knock on.
#
# So the kind is DERIVED from the same glob list above — never a second opinion
# about what a door is — and printed per class on the rule's status line.
_DOOR_KIND_BY_NAME = {
    "mcp.py": "tool",
    "consumers.py": "socket",
    "activities.py": "activity",
    "receivers.py": "receiver",
}
# A caller OUTSIDE this tree, holding a credential, can reach these.
EXTERNAL_DOOR_KINDS = frozenset({"route", "tool", "socket", "receiver"})
# These are this tree's own hands: a workflow's activity, and the shell.
INTERNAL_DOOR_KINDS = frozenset({"activity", "command"})
DOOR_KINDS = tuple(sorted(EXTERNAL_DOOR_KINDS | INTERNAL_DOOR_KINDS))


def _door_kind(root: Path, path: Path) -> str:
    """Which kind of door this module is, off the glob that matched it."""
    if "commands" in path.parts and "management" in path.parts:
        return "command"
    return _DOOR_KIND_BY_NAME.get(path.name, "route")


def _door_modules(root: Path) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in DOOR_GLOBS:
        for path in sorted(root.glob(pattern)):
            parts = set(path.parts)
            if parts & SKIP_PARTS or not path.is_file():
                continue
            seen[path.as_posix()] = path
    return [seen[key] for key in sorted(seen)]


# : The module a call could not be resolved to. `("*", name)` is the declared
# : valve: a call through a registry, a `getattr`, `self`, a parameter or a
# : local variable has no import to resolve, and rule 42 counts it by bare name
# : exactly as the whole check used to. `does_not_cover` names that valve.
UNRESOLVED = "*"


def _dotted(root: Path, path: Path) -> str:
    """The import path a module in this tree would be imported by."""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_first_party_module(root: Path, dotted: str) -> bool:
    """Whether this dotted name is a module IN THIS TREE (a file or a package)."""
    if not dotted:
        return False
    base = root.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _import_maps(root: Path, tree: ast.Module, here: str) -> tuple[dict[str, str], dict[str, str]]:
    """(module_alias -> dotted module, symbol_alias -> dotted owning module).

    ONE LEVEL of resolution, which is all the shape needs and all an AST
    can honestly claim: what a name in THIS module was bound to by an import
    statement in THIS module. `from apps.accounts import zitadel` binds a
    module; `from apps.accounts.services import deactivate_user` binds a
    symbol and records which module owns it. A relative import is resolved
    against `here`, the door module's own dotted path.
    """
    modules: dict[str, str] = {}
    symbols: dict[str, str] = {}
    facade = facade_reexports(root)
    package = here.rsplit(".", 1)[0] if "." in here else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                origin = ".".join([*base, node.module]) if node.module else ".".join(base)
            else:
                origin = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                candidate = f"{origin}.{alias.name}" if origin else alias.name
                if (origin, alias.name) in facade:
                    # A facade name is owned by the module `pilecap` re-exports it from.
                    symbols[bound] = facade[(origin, alias.name)][0]
                elif _is_first_party_module(root, candidate):
                    modules[bound] = candidate
                else:
                    # Either a symbol from a first-party module, or anything at
                    # all from a third-party one. Both resolve to a module that
                    # is not a first-party `services.py`, which is the only
                    # question this census asks.
                    symbols[bound] = origin
    return modules, symbols


def _flatten(node: ast.expr) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; anything not a pure name chain -> None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return list(reversed(parts))


def _called_qualnames(root: Path, tree: ast.Module, here: str) -> set[tuple[str, str]]:
    """Every call this module makes, as (owning module, name).

    , 2026-08-24 — the recorded live false pass. `apps/accounts/activities.py`
    calls `zitadel.deactivate_user(...)`, a DIFFERENT function that happens to
    share a name with the doorless service `accounts.services.deactivate_user`,
    and the bare-name census read the service as reached. The census now
    resolves the called name to the module it was imported from, so
    `("apps.accounts.zitadel", "deactivate_user")` no longer answers for
    `("apps.accounts.services", "deactivate_user")`.

    Where an import cannot answer — `self.x()`, `handler()` bound at runtime, a
    registry lookup — the pair is `(UNRESOLVED, name)` and matches by bare name
    as before. That is the declared valve, not an oversight: a census that
    called every unresolvable name doorless would invent findings out of its
    own blind spot.
    """
    modules, symbols = _import_maps(root, tree, here)
    local = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    return _resolved_calls(tree, here=here, modules=modules, symbols=symbols, local=local)


def _resolved_calls(
    node: ast.AST,
    *,
    here: str,
    modules: dict[str, str],
    symbols: dict[str, str],
    local: set[str],
) -> set[tuple[str, str]]:
    """The resolution itself, over any subtree.

    Split out of `_called_qualnames` so a rule that asks "what does THIS
    FUNCTION call" (rule 41's clause) and a rule that asks "what does this
    MODULE call" (rule 42) share one resolver. Two copies of a resolution is the
    shape this engine refuses everywhere else; it would be odd here.
    """
    out: set[tuple[str, str]] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            if func.id in symbols:
                out.add((symbols[func.id], func.id))
            elif func.id in local:
                out.add((here, func.id))  # defined right here; no service is
            else:
                out.add((UNRESOLVED, func.id))
            continue
        if not isinstance(func, ast.Attribute):
            continue
        chain = _flatten(func)
        if chain is None:
            out.add((UNRESOLVED, func.attr))
            continue
        head, middle, name = chain[0], chain[1:-1], chain[-1]
        if head in modules:
            out.add((".".join([modules[head], *middle]), name))
        elif head in symbols:
            out.add((".".join([symbols[head], head, *middle]), name))
        else:
            out.add((UNRESOLVED, name))
    return out


def door_reachability(root: Path, rule: dict) -> CheckResult:
    """Rule 42. Findings are classed by APP, so one app's backlog cannot pay for
    another app's growth — the per-app numbers in the census report and the
    per-app ratchets in `rules.yaml` are the same numbers.

    TWO CLASSES PER APP, not one. `<app>` is the doorless service —
    nothing reaches it at all. `<app>:internal-only` is the service reached
    ONLY by this tree's own hands, an activity or a management command: a real
    fact about who can call it, which the old reached/not-reached bit could not
    say. Separate classes because they have separate repairs and separate
    backlogs, and because a doorless service paid for by a workflow-only one
    would be the exact accounting this rule refuses everywhere else.
    """
    out = CheckResult()
    out.targets_matched["door_valves"] = 0
    out.targets_matched["reachable_services"] = 0
    # Seeded so every class PRINTS on every run, at zero or otherwise: a number
    # that only appears when it is non-zero is a number nobody watches fall.
    for kind in DOOR_KINDS:
        out.targets_matched[f"reached_by_{kind}"] = 0
    out.targets_matched["reached_internal_only"] = 0
    out.targets_matched["internal_only_declared"] = 0
    reached: dict[tuple[str, str], set[str]] = {}
    for path in _door_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("door_modules")
        kind = _door_kind(root, path)
        for pair in _called_qualnames(root, tree, _dotted(root, path)):
            reached.setdefault(pair, set()).add(kind)
    unresolved: dict[str, set[str]] = {}
    for (module, name), kinds in reached.items():
        if module == UNRESOLVED:
            unresolved.setdefault(name, set()).update(kinds)
    # The residual false-pass surface, printed on the rule's status line beside
    # `door_valves` because it is the same kind of thing: a service counted
    # reachable ONLY because a call somewhere could not be resolved to a
    # module. It measured 0 on the tree that landed the resolution, so
    # every reachable service today is reachable by a qualified name.
    out.targets_matched["reached_by_bare_name"] = 0
    for path in service_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("service_files")
        rel = path.relative_to(root).as_posix()
        app = path.relative_to(root).parts[1]
        here = _dotted(root, path)
        # A `services/` package re-exports its modules whole, so a call through it reaches them.
        package = path.name not in (SERVICE_MODULE, "__init__.py")
        owners = {here, here.rsplit(".", 1)[0]} if package else {here}
        lines = _read(path).splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in decorator_names(node):
                continue
            out.count("services_censused")
            top = min([d.lineno for d in node.decorator_list] or [node.lineno])
            kinds = {kind for owner in owners for kind in reached.get((owner, node.name), ())}
            by_bare_name = False
            if not kinds and node.name in unresolved:
                kinds = set(unresolved[node.name])
                by_bare_name = True
            if kinds:
                out.count("reachable_services")
                if by_bare_name:
                    out.count("reached_by_bare_name")
                for kind in sorted(kinds):
                    out.count(f"reached_by_{kind}")
                if kinds & EXTERNAL_DOOR_KINDS:
                    continue
                # REACHED, AND ONLY BY THIS TREE'S OWN HANDS. An
                # activity is a workflow's step and a management command is a
                # shell: both are legitimate, and neither is a door somebody
                # outside this tree can knock on. That is a different fact from
                # "doorless", so it is a different CLASS with its own recorded
                # backlog — one app's workflow-only work cannot pay for
                # another's, and neither can pay for a doorless service.
                out.count("reached_internal_only")
                said = " and ".join(sorted(kinds))
                internal_klass = f"{app}:internal-only"
                reason = comment_reason(lines, node.lineno, _DOOR_RE) or comment_reason(
                    lines, top, _DOOR_RE
                )
                if reason is not None:
                    if reason.holds:
                        out.count("internal_only_declared")
                        continue
                    out.hit(
                        rel,
                        node.lineno,
                        f"`# door:` with no reason on {node.name} — an escape hatch nobody "
                        "has to justify is an off switch; write the sentence a reviewer can "
                        "disagree with",
                        klass=internal_klass,
                    )
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} is reached only from {said} — no route, tool, consumer or "
                    "receiver calls it, so no credential-holding caller outside this tree "
                    "can. That may be exactly right (a workflow's own step, an operator "
                    "act) and it is not the same claim as a capability with a door: record "
                    "`# door: <reason>` saying which, counted and printed like every valve "
                    "here, or give it the door the persona who needs it would use "
                    "(house rule 42)",
                    klass=internal_klass,
                )
                continue
            reason = comment_reason(lines, node.lineno, _DOOR_RE) or comment_reason(
                lines, top, _DOOR_RE
            )
            if reason is not None:
                if reason.holds:
                    out.count("door_valves")
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"`# door:` with no reason on {node.name} — an escape hatch nobody has "
                    "to justify is an off switch; write the sentence a reviewer can "
                    "disagree with",
                    klass=app,
                )
                continue
            out.hit(
                rel,
                node.lineno,
                f"{node.name} is not called from any door — no route, tool, consumer, "
                "activity, receiver or management command reaches it, so nobody outside "
                "this tree can. Give it a door, or record `# door: <reason>` saying why it "
                "is deliberately unreachable (house rule 42)",
                klass=app,
            )
    return out


def count_contract_surface(root: Path, rule: dict) -> CheckResult:
    """Rule 41's floors: how much contract surface there is to be documented.

    Four populations rather than one, because rule 41 has four subjects and a
    single count would let three of them collapse to nothing while the fourth
    kept the floor satisfied — routes, the docstrings that document them, the
    tag declarations that name their groups, and the machine-door twins that
    have to render the same words.

    (a), 2026-08-24: the walk is `api_modules()` — the SAME population
    `config/api.py` mounts and the same one rule 5 was widened to in —
    rather than `api.py` by basename. An app whose routes have outgrown one
    file was outside all four counts, so `apps/core/api/routes.py` contributed
    nothing: TAG-1 moved core's `TAGS` from one entry to two and the floor
    counter read 8 either way, which is a floor that would not notice core's
    tags vanishing altogether. The counts are the tree's, measured in
    the retired contract-standard-measurement.md, and the floors below them are
    pinned AT the measurement (rules.yaml, rule 41) so a contraction is a
    number a human re-commits rather than a silence.
    """
    out = CheckResult()
    for path in [module for app in _app_dirs(root) for module in api_modules(app)]:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if "TAGS" in names:
                    out.count("tag_declarations", len(node.value.keys))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _route_decorators(node)[0]:
                out.count("documented_routes")
                if ast.get_docstring(node):
                    out.count("contract_docstrings")
    for path in _py_files(root, "apps", named={"mcp.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                out.count("twin_tools")
    return out


def count_mount_surface(root: Path, rule: dict) -> CheckResult:
    """Rule 32's floors: how much URL surface there is for a label to leak onto.

    Two populations, because rule 32 joins two and a single count would let
    either collapse while the other kept the floor satisfied — the api modules
    that expose a `router` (each one a `PREFIX` decision) and the app labels
    those prefixes could collide with. If discovery ever finds no api module,
    or the app registry no app, the census would pass by having nothing to
    census, and this is what says so instead.
    """
    out = CheckResult()
    out.targets_matched["app_labels"] = len(_app_dirs(root))
    for path in [*_py_files(root, "apps", named={"api.py"}), *root.glob("apps/*/api/*.py")]:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "router" for t in node.targets
            ):
                out.count("mounted_routers")
                break
    return out


def count_apps(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    out.targets_matched["apps"] = len(_app_dirs(root))
    return out


def count_admin_classes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named={"admin.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.bases:
                out.count("admin_classes")
    return out


def count_noun_roads(root: Path, rule: dict) -> CheckResult:
    """Rule 74's floor: the roads it reads and the marker population it judges.

    Two populations, each named, because they fail independently (rung-execution
    §2: a floor names populations, not reach kinds). `roads` is the keys of
    `apps/core/verbs.py`'s `ROADS` literal, read by AST — a table that emptied
    would leave the check judging nothing. `marker_classes` is the archivable
    population through rule 75's resolver, and it includes the `Archivable`
    mixin itself (the population's root), so the floor holds from the day the
    mixin lands, before any noun adopts it.
    """
    out = CheckResult()
    tree = _parse(root / "apps/core/verbs.py")
    for node in tree.body if tree is not None else []:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = getattr(node, "value", None)
        if isinstance(target, ast.Name) and target.id == "ROADS" and isinstance(value, ast.Dict):
            out.count("roads", len(value.keys))
    _sites, _append_only, archivable = declared_class_populations(root)
    out.count("marker_classes", len(archivable))
    return out


def count_surface_questions(root: Path, rule: dict) -> CheckResult:
    """Rule 85's floors: the populations a surface declaration is judged against.

    One count per population, because each can empty on its own, and then
    every declared word reads as undeclared — a red for the wrong reason: the
    family keys the `TAGS` literals name
    (rule 41's reader), the family roads `ROADS` names (rule 74's reader), and
    the apps whose `roles.py` exists. The route table's rows are the fourth
    population and are not floored here: a product with no face has none, and
    a screen declared against no table is the check's own finding.
    """
    out = CheckResult()
    out.count(
        "tag_declarations",
        count_contract_surface(root, rule).targets_matched.get("tag_declarations", 0),
    )
    out.count("roads", count_noun_roads(root, rule).targets_matched.get("roads", 0))
    out.count("role_modules", sum(1 for app in _app_dirs(root) if (app / "roles.py").is_file()))
    return out


FLOOR_PROXIES = {
    "count_surface_questions": count_surface_questions,
    "count_noun_roads": count_noun_roads,
    "count_model_classes": count_model_classes,
    "count_routes": count_routes,
    "count_contract_surface": count_contract_surface,
    "count_mount_surface": count_mount_surface,
    "count_apps": count_apps,
    "count_admin_classes": count_admin_classes,
}


from quality.checks.rule_41_clause import _route_decorators  # noqa: E402
from quality.checks.rule_75_resolver import declared_class_populations  # noqa: E402
