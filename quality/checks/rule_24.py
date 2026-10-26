"""Rule 24: org-scoped reads chain visible_to; the tree is written by services."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

from quality.checks._hub import (
    _RULE8_FILES,
    _WRITE_MANAGER_CALLS,
    CheckResult,
    _enclosing_functions,
    _function_at,
    _parse,
    _py_files,
    _read,
    scoped_model_names,
)
from quality.worlds import class_graph, reaching

# --- rule 24: org-scoped reads chain visible_to; the tree is written by services --

# The same door/service/selector set rule 8 watches. Rule 24 is rule 8 one level
# down: rule 8 asks "whose tenant", this asks "whose part of it".
_RULE24_FILES = dict.fromkeys(_RULE8_FILES)

_ORG_BASE = "OrgScopedModel"

# The two model names whose shape-bearing columns only their own services may
# write. Named here rather than derived, because they ARE the hierarchy: a
# product that renames them has rewritten the primitive.
_MEMBERSHIP = "Membership"
_ORGANIZATION = "Organization"
# The columns that decide who can see what. `role` on a membership, `path` and
# `parent` on an organization; everything else about either row is ordinary.
_ORG_SHAPE_FIELDS = ("path", "parent")

#: The two tables that ARE the permission exceptions. A `Grant` row widens or
#: narrows one person in one branch and a `RolePermission` row is a tenant's own
#: collection — both are the same act `Membership.role` is, reached through a
#: different column, and the escalation wall (`_refuse_escalation`) is the one
#: thing standing in front of all three. A row written anywhere else is a
#: capability handed out beside the wall rather than through it.
_PERMISSION_ROW_MODELS = ("Grant", "RolePermission")

# ADR core-3 (G1). `governing(org)` resolves configuration UPWARDS — the nearest
# row on the actor's ancestor chain wins — and it is legal on exactly one
# population: models that declared `InheritedDownward`. The widening and its
# fence are born together, which is why the marker's name and its attribute are
# both read here: `core.models.is_inherited_downward` is an attribute lookup, so
# a model that writes `inherited_downward = True` by hand has declared it just as
# loudly as one that inherits the marker class.
_INHERITED_BASE = "InheritedDownward"
_INHERITED_ATTR = "inherited_downward"


def _class_bases_by_name(root: Path) -> Mapping[str, frozenset[str]]:
    """{class name: base names} across the whole app tree — `quality.worlds.class_graph`."""
    return class_graph(root)


def _transitive(class_bases: Mapping[str, Iterable[str]], seed: str) -> set[str]:
    """Every class reaching `seed` through `class_bases`, the seed excluded."""
    return reaching(class_bases, {seed}) - {seed}


def inherited_downward_model_names(root: Path) -> set[str]:
    """Every class that declared itself inherited-downwards, by base or by attribute."""
    names = _transitive(_class_bases_by_name(root), _INHERITED_BASE)
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _class_attribute_is_true(node, _INHERITED_ATTR):
                names.add(node.name)
    # The marker class carries the attribute itself — it is the declaration, not
    # a model that made one.
    names.discard(_INHERITED_BASE)
    return names


def org_scoped_model_names(root: Path) -> set[str]:
    """Every class inheriting OrgScopedModel, transitively, by AST.

    Derived from the tree on every run, exactly as rule 8 derives its own set:
    a new org-scoped model is in scope the moment it exists, without anybody
    editing a list.

    The abstract base is NOT a member: `_transitive` discards its seed, and it
    is right to, because every reader of this set asks a question about a real
    table — which reads must chain `visible_to` (rule 24), which `Out` schemas
    owe `organization_id` (rule 38). Nobody has a row of `OrgScopedModel`. The
    one question that is about the ANNOTATION rather than the table has its own
    population below.
    """
    return _transitive(_class_bases_by_name(root), _ORG_BASE)


def org_fk_model_names(root: Path) -> set[str]:
    """Every model that names its organization through a FOREIGN KEY.

    The half `OrgScopedModel` does not cover, and it is not an edge case: it is
    `Membership` — person x tenant x org x role, the row the whole hierarchy is
    made of, which carries an `organization` column and inherits `BaseModel`
    rather than the scoped base. A service handed one and writing on the
    strength of it is exactly rule 26's subject, and it sat outside the
    population until a builder's `Membership.objects.get(pk=...)` followed by
    `set_role(...)` turned out to be gate-legal.

    Derived from the class body the same way rule 55 derives "does this row
    name a node", so the two cannot come to disagree about what a node-bearing
    model is.
    """
    facts = _model_facts(root)
    return {
        name
        for name, fact in facts.items()
        if not fact["abstract"] and "organization" in fact["foreign_keys"]
    }


def reach_population_names(root: Path) -> set[str]:
    """Rule 26's model population: org-scoped, plus the FK-bearing models."""
    return org_scoped_model_names(root) | org_fk_model_names(root)


def _fk_holders_of(root: Path, population: set[str]) -> set[str]:
    """Every model holding a foreign key to a member of `population`.

    `Grant.membership -> Membership`, so `create_grant(membership=...)` writing
    a `Grant` is writing a row that names the population member it was handed.
    Without this the widening would stop one hop short of the service the
    widening exists for.
    """
    facts = _model_facts(root)
    return {
        name
        for name, fact in facts.items()
        if not fact["abstract"] and set(fact["foreign_keys"].values()) & population
    }


def org_scoped_annotation_names(root: Path) -> set[str]:
    """The names an annotation may use to say "a row one part of a tenant owns".

    Every concrete org-scoped model, AND the abstract base itself.

    The distinction from `org_scoped_model_names` is the whole point. A model
    population must not hold the abstract class; an ANNOTATION population must,
    because `row: OrgScopedModel` is the most honest declaration a service can
    make — "any row one part of a tenant owns" — and the seed being discarded
    made exactly that declaration structurally invisible to rule 26. The
    parameter whose type said loudest that reachability needed asking was the
    one parameter nobody asked about. Measured on the tree that closed it: zero
    parameters in `apps/*/services.py` are annotated with the base, so counting
    it costs no false positive and the first one to arrive is seen.
    """
    return reach_population_names(root) | {_ORG_BASE}


def _parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _chained_after(parents: dict[int, ast.AST], node: ast.AST) -> set[str]:
    """Every attribute called on the result of `node`, walking the chain out.

    `X.objects.for_tenant(t).visible_to(o).filter(...)` -> {"visible_to",
    "filter"}. It stops the moment the expression stops being a method chain,
    so a queryset handed to another function and widened there is invisible
    here — declared in `does_not_cover`.
    """
    attrs: set[str] = set()
    current: ast.AST = node
    while True:
        parent = parents.get(id(current))
        if isinstance(parent, ast.Attribute) and parent.value is current:
            attrs.add(parent.attr)
            current = parent
        elif isinstance(parent, ast.Call) and parent.func is current:
            current = parent
        else:
            return attrs


def _rule24_paths(rule: dict, key: str) -> dict[str, set[str]]:
    """{path: {function, ...}} from a scope allow-list. An empty set means
    "anywhere in that file"."""
    allowed: dict[str, set[str]] = {}
    for entry in (rule.get("scope") or {}).get(key) or []:
        path = str(entry.get("path", ""))
        if not path:
            continue
        allowed.setdefault(path, set()).update(str(name) for name in entry.get("functions") or [])
    return allowed


def _allowed_here(allowed: dict[str, set[str]], rel: str, function: str | None) -> bool:
    if rel not in allowed:
        return False
    functions = allowed[rel]
    return not functions or (function in functions)


def org_scoped_reads(root: Path, rule: dict) -> CheckResult:
    """Rule 24, in four parts, because they are one rule from four sides.

    1. **Reads**: an `OrgScopedModel` read as `for_tenant(...)` with neither
       `.visible_to(...)` nor `.governing(...)` after it hands the whole tenant
       to whoever asked.
    2. **The fence on the widening** (ADR core-3): `.governing(...)` is upward
       *config resolution*, never upward *visibility*, and it is legal on
       exactly one population — models that declared `InheritedDownward`. A
       `governing()` on an unmarked model is a violation here for the same
       reason it is a `TypeError` there: the widening and its fence are born
       together, or the widening is a hole with no edges.
    3. **Grants**: a `Membership.role` written outside the membership services
       walks around the escalation wall rather than through it.
    4. **Shape**: an `Organization.path` or `.parent` written outside the move
       services silently detaches a subtree from every read in the product.
    """
    out = CheckResult()
    org_models = org_scoped_model_names(root)
    inherited = inherited_downward_model_names(root)
    known_models = org_models | scoped_model_names(root)
    out.targets_matched["org_scoped_models"] = len(org_models)
    out.targets_matched["inherited_downward_models"] = len(inherited)
    role_writers = _rule24_paths(rule, "membership_role_writers")
    shape_writers = _rule24_paths(rule, "organization_shape_writers")
    permission_writers = _rule24_paths(rule, "permission_row_writers")

    files = _py_files(root, "apps", named=set(_RULE24_FILES)) + _py_files(root, "config")
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        src = _read(path)
        spans = _enclosing_functions(tree)
        parents = _parent_map(tree)

        # (1) the read.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "for_tenant":
                continue
            base = _chain_root(node)
            if not (isinstance(base, ast.Name) and base.id in org_models):
                continue
            chained = _chained_after(parents, node)
            if "visible_to" in chained:
                continue
            if "governing" in chained:
                # Legal, and its own fence is part (2) below — which judges the
                # call whether or not it followed a for_tenant().
                continue
            out.hit(
                rel,
                node.lineno,
                f"{base.id}.objects.for_tenant(...) on an org-scoped model without "
                ".visible_to(...) — a tenant-wide read of a row one part of the tenant "
                "owns; chain .visible_to(actor_or_org) after it, or .governing(org) when "
                "the model declared InheritedDownward",
            )

        # (2) governing() is legal only on a model that declared InheritedDownward.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "governing":
                continue
            base = _chain_root(node)
            if not (isinstance(base, ast.Name) and base.id in known_models):
                continue
            if base.id in inherited:
                continue
            out.hit(
                rel,
                node.lineno,
                f"{base.id}.objects...governing(...) — {base.id} has not declared "
                "InheritedDownward, so the nearest-ancestor read is not legal on it. "
                "governing() is upward CONFIG resolution and never upward visibility: it "
                "returns rows a branch could never list, which is only safe where the "
                "model's rows are configuration inherited downwards. Declare "
                "`InheritedDownward` on the model (apps.core.models) if that is what it "
                "is, or read it with .visible_to(actor_or_org) (ADR core-3)",
            )

        # (3) who may write a membership's role.
        if _MEMBERSHIP in src:
            for lineno, what in _role_writes(tree):
                if _allowed_here(role_writers, rel, _function_at(spans, lineno)):
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"{what} outside the membership services — a role granted here skips "
                    "the escalation wall (no grant above your own effective role, none "
                    "outside your subtree)",
                )

        # (5) who may write a permission exception — the same question as (3),
        # one column over. `Membership.role` is not the only way to change what
        # somebody may do since the role tables landed.
        for model in _PERMISSION_ROW_MODELS:
            if model not in src:
                continue
            for lineno, what in _permission_row_writes(tree, model):
                if _allowed_here(permission_writers, rel, _function_at(spans, lineno)):
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"{what} outside the permission services — a grant or a role's own "
                    "collection written here skips the escalation wall exactly as a role "
                    "assignment would: `allow` is bounded by what the granter holds and "
                    "`withhold` by what the target holds, and neither bound exists on a "
                    "row written by hand",
                )

        # (4) who may write the tree's shape.
        if _ORGANIZATION in src:
            for lineno, what in _shape_writes(tree):
                if _allowed_here(shape_writers, rel, _function_at(spans, lineno)):
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"{what} outside the organization services — a path or parent written "
                    "by hand detaches a subtree from every visible_to in the product; "
                    "re-parenting is move_organization",
                )
    return out


def _role_writes(tree: ast.Module) -> list[tuple[int, str]]:
    """Every way this module changes what somebody may do."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "role":
                    hits.append((node.lineno, "an assignment to .role"))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == _MEMBERSHIP:
                hits.append((node.lineno, "a Membership(...) constructed"))
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                "update",
                "create",
                "get_or_create",
                "update_or_create",
                "bulk_create",
            ):
                if any(keyword.arg == "role" for keyword in node.keywords):
                    hits.append((node.lineno, f".{node.func.attr}(role=...)"))
    return hits


def _permission_row_writes(tree: ast.Module, model: str) -> list[tuple[int, str]]:
    """Every way this module writes a `Grant` or a `RolePermission` row.

    The constructor and the manager writes, which is the same population rule
    13's `_write_calls` reads — restated against one named model rather than
    against the registry, because the question here is not "does this write"
    but "does this write THESE two tables".
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == model:
            hits.append((node.lineno, f"a {model}(...) constructed"))
            continue
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _WRITE_MANAGER_CALLS | {"update", "delete", "bulk_update"}:
            continue
        root_name = _chain_root(func.value)
        if isinstance(root_name, ast.Name) and root_name.id == model:
            hits.append((node.lineno, f"a {model} row written (.{func.attr}())"))
    return hits


def _shape_writes(tree: ast.Module) -> list[tuple[int, str]]:
    """Every way this module moves a node in the tree."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in _ORG_SHAPE_FIELDS:
                    hits.append((node.lineno, f"an assignment to .{target.attr}"))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("update", "bulk_update")
        ):
            for keyword in node.keywords:
                if keyword.arg in _ORG_SHAPE_FIELDS:
                    hits.append((node.lineno, f".{node.func.attr}({keyword.arg}=...)"))
    return hits


from quality.checks.rule_13_clauses_i_iv import _model_facts  # noqa: E402
from quality.checks.rule_20_enforceable_half import _class_attribute_is_true  # noqa: E402
from quality.checks.rules_10_12 import _chain_root  # noqa: E402
