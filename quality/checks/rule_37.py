"""Rule 37: no scoped model orders the whole deployment by time."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, scoped_model_names

# --- rule 37: no scoped model orders the whole deployment by time --------------
#
# ADR core-11 / . `BaseModel` shipped `created_at` with `db_index=True`
# behind `ordering = ["-created_at"]`, so every concrete model in the tree
# inherited an index over the WHOLE DEPLOYMENT's timeline while every supported
# read is tenant-scoped. A paginated page walked backwards down that index and
# threw away other tenants' entries one at a time (F1a measured 102,300 foreign
# rows examined per page; F1b measured 255,000 on `AuditEntry`). The fix is the
# `(tenant, -created_at)` composite declared once in `TenantScopedModel.Meta`.
#
# WHY A RULE AND NOT JUST THE FIX. Django does NOT merge `Meta.indexes` down an
# inheritance chain: a concrete model that declares its own `indexes` list
# SHADOWS the abstract one and silently loses the composite. That hole is
# invisible in review — the model looks like it has indexes — and it is one
# line wide. The same census refuses the next hand-written tenant-blind index
# and the next `DateTimeField(db_index=True)`, which is the disease's original
# spelling and the shape a product's builder reaches for first.
#
# THE POPULATION IS DERIVED, NEVER TYPED — every concrete class that reaches
# `TenantScopedModel`, off the same AST walk rules 8, 24 and 38 use. A hand
# list here would be the misses ledger's hand-list-goes-stale class (cycle-0
# #8): `exports.Export` landed between this rule's design and its build and was
# in scope the moment it existed, with no edit to this file.
#
# THE RULE READS DECLARATIONS AND NEVER PLANS. Whether the planner actually
# picks the composite is rule 35's job and the perf harness's.

_DATE_FIELDS = {"DateTimeField", "DateField"}
_RECENCY_COLUMN = "created_at"


def _nested_class(node: ast.ClassDef, name: str) -> ast.ClassDef | None:
    for stmt in node.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == name:
            return stmt
    return None


def _meta_parent(meta: ast.ClassDef) -> str | None:
    """`class Meta(TenantScopedModel.Meta)` -> `TenantScopedModel`.

    Django's Meta inheritance is plain Python class inheritance of the inner
    class, so this is the whole of the resolution rule.
    """
    for base in meta.bases:
        if isinstance(base, ast.Attribute) and base.attr == "Meta":
            if isinstance(base.value, ast.Name):
                return base.value.id
    return None


def _model_index_of(root: Path) -> dict[str, tuple[Path, ast.ClassDef]]:
    return {node.name: (path, node) for path, node in _model_classes(root)}


def _meta_attribute(
    index: dict[str, tuple[Path, ast.ClassDef]], model: str, attr: str
) -> ast.expr | None:
    """The value of `Meta.<attr>` as Python attribute lookup would find it.

    The FIRST `Meta` in the chain that declares the name wins — which is
    exactly why a concrete model's own `indexes` shadows the abstract base's,
    and why this rule exists.
    """
    seen: set[str] = set()
    name: str | None = model
    while name is not None and name not in seen:
        seen.add(name)
        entry = index.get(name)
        if entry is None:
            return None
        meta = _nested_class(entry[1], "Meta")
        if meta is None:
            return None
        for _line, declared, value in _field_assignments(meta):
            if declared == attr:
                return value
        name = _meta_parent(meta)
    return None


def _is_abstract(index: dict[str, tuple[Path, ast.ClassDef]], model: str) -> bool:
    entry = index.get(model)
    if entry is None:
        return False
    meta = _nested_class(entry[1], "Meta")
    if meta is None:
        return False
    for _line, declared, value in _field_assignments(meta):
        if declared == "abstract" and isinstance(value, ast.Constant) and value.value is True:
            return True
    return False


def _date_fields_of(
    index: dict[str, tuple[Path, ast.ClassDef]], model: str
) -> dict[str, tuple[int, bool]]:
    """`{field name: (line, db_index)}` for every date field the model has, its
    INHERITED ones included — `BaseModel.created_at` is the whole point, since
    that one line is what put a blind index on every table in the tree."""
    found: dict[str, tuple[int, bool]] = {}
    stack = [model]
    seen: set[str] = set()
    while stack:
        name = stack.pop(0)
        if name in seen:
            continue
        seen.add(name)
        entry = index.get(name)
        if entry is None:
            continue
        for line, field_name, value in _field_assignments(entry[1]):
            if _call_name(value) not in _DATE_FIELDS or not isinstance(value, ast.Call):
                continue
            indexed = any(
                kw.arg == "db_index" and isinstance(kw.value, ast.Constant) and kw.value.value
                for kw in value.keywords
            )
            # A subclass redeclaring the field wins over its base's: the walk is
            # breadth-first from the model itself, so the first write stands.
            found.setdefault(field_name, (line, indexed))
        stack.extend(_base_names(entry[1]))
    return found


def _string_list(value: ast.expr | None) -> list[str] | None:
    if not isinstance(value, ast.List):
        return None
    out: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        out.append(element.value)
    return out


def _declared_indexes(value: ast.expr | None) -> list[tuple[int, list[str] | None, bool]]:
    """`(line, fields — None for an expression index, whether it has a condition)`."""
    if not isinstance(value, ast.List):
        return []
    out: list[tuple[int, list[str] | None, bool]] = []
    for element in value.elts:
        if not isinstance(element, ast.Call) or _call_name(element) != "Index":
            continue
        fields: list[str] | None = None
        conditional = False
        for kw in element.keywords:
            if kw.arg == "fields":
                fields = _string_list(kw.value)
            elif kw.arg == "condition":
                conditional = True
        out.append((element.lineno, fields, conditional))
    return out


def _leads_on(columns: list[str], column: str) -> bool:
    return bool(columns) and columns[0].lstrip("-") == column


def _is_the_composite(columns: list[str]) -> bool:
    """First two columns `(tenant, created_at)`, in either direction.

    The census asserts LEADING COLUMNS and never a spelling: coverage is the
    guarantee, and a product that names its own composite something else is
    still covered.
    """
    return (
        len(columns) >= 2
        and columns[0].lstrip("-") == "tenant"
        and columns[1].lstrip("-") == _RECENCY_COLUMN
    )


def tenant_blind_index_census(root: Path, rule: dict) -> CheckResult:
    """Rule 37: three edges over one discovered population."""
    out = CheckResult()
    index = _model_index_of(root)
    scoped = {name for name in scoped_model_names(root) if not _is_abstract(index, name)}

    for model in sorted(scoped):
        entry = index.get(model)
        if entry is None:
            continue
        path, node = entry
        rel = path.relative_to(root).as_posix()
        out.count("scoped_models_censused")

        ordering = _string_list(_meta_attribute(index, model, "ordering")) or []
        declared = _declared_indexes(_meta_attribute(index, model, "indexes"))
        dates = _date_fields_of(index, model)

        # --- edge 1: COVERAGE -------------------------------------------------
        if _leads_on(ordering, _RECENCY_COLUMN):
            out.count("recency_ordered_models")
            if any(fields is not None and _is_the_composite(fields) for _l, fields, _c in declared):
                out.count("composites_found")
            elif _exempt(rule, rel, model):
                out.count("coverage_valves")
            else:
                out.hit(
                    rel,
                    node.lineno,
                    f"{model} orders by `{ordering[0]}` and carries no index leading on "
                    "(tenant, created_at). Every page of its default list walks the whole "
                    "DEPLOYMENT's timeline and discards other tenants' rows one at a time "
                    "(F1a: 102,300 foreign rows examined per page). "
                    "`TenantScopedModel.Meta` declares that composite for you — but Django "
                    "does not merge `Meta.indexes` down an inheritance chain, so this "
                    "model's own `indexes` list SHADOWS it. Re-add "
                    '`models.Index(fields=["tenant", "-created_at"], name="'
                    f'{model.lower()}_recency")` to that list (rule 37, ADR core-11)',
                    klass="coverage",
                )

        # --- edge 2: NO BLIND INDEX -------------------------------------------
        for line, fields, conditional in declared:
            if fields is None:
                # `models.Index(expressions=...)` has no leading fields list.
                out.count("expression_indexes_unseen")
                continue
            if not fields or fields[0].lstrip("-") not in dates:
                continue
            if conditional:
                # The `AuditEntry` platform-partial shape (ADR core-8): index
                # the population the read is over, never the whole table.
                out.count("platform_partial_indexes")
                continue
            if _exempt(rule, rel, f"{model}.index@{fields[0].lstrip('-')}"):
                out.count("blind_index_valves")
                continue
            out.hit(
                rel,
                line,
                f"{model} declares an index leading on the time column "
                f"`{fields[0].lstrip('-')}` with no `condition` — a tenant-blind index over "
                "the whole deployment, the exact shape ADR core-11 removed. Lead with "
                "`tenant`, or carry a `condition` that excludes tenant rows (the "
                "`AuditEntry` platform-partial shape). If this one index is the "
                "exception, `# rule-37: <reason>` on its line is counted and printed; the "
                "rules.yaml exemption is the heavier road and says the SHAPE is blessed "
                "rather than this line",
                klass="no_blind_time_index",
            )

        # --- edge 3: NO BLIND FIELD INDEX -------------------------------------
        for field_name, (line, indexed) in sorted(dates.items()):
            if not indexed:
                continue
            if _exempt(rule, rel, f"{model}.{field_name}"):
                out.count("blind_field_valves")
                continue
            out.hit(
                rel,
                line,
                f"{model}.{field_name} is a date field with `db_index=True` — the original "
                "disease's exact spelling (ADR core-11). A bare index on a time column of a "
                "SCOPED model orders the whole deployment, and every read of this table is "
                "tenant-scoped. Drop the flag and lead a composite with `tenant`. If this "
                "one field is the exception, `# rule-37: <reason>` on its line is counted "
                "and printed; the rules.yaml exemption is the heavier road and wants the "
                "cross-tenant reader that needs it named",
                klass="no_blind_field_index",
            )

    return out


from quality.checks.rule_16_the_rest_of_the_grammar import (  # noqa: E402
    _base_names,
    _call_name,
    _field_assignments,
    _model_classes,
)
