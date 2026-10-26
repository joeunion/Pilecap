"""Rule 38: an org-scoped `Out` schema carries its branch."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse


def _org_models_by_app(root: Path) -> dict[str, set[str]]:
    """{app label: the org-scoped model names its modules define}, derived, never typed.

    A member is in `org_scoped_model_names` AND `_model_classes`: a non-model namesake never is.
    """
    org_names = org_scoped_model_names(root)
    by_app: dict[str, set[str]] = {}
    for path, node in _model_classes(root):
        if node.name in org_names:
            by_app.setdefault(path.relative_to(root).parts[1], set()).add(node.name)
    return by_app


def org_scoped_out_schemas(root: Path, rule: dict) -> CheckResult:
    """Every `Out` schema of an `OrgScopedModel` declares `organization_id`.

    The invariant **one seam earlier** than rule 36 (P3 SEC-1's argument, built
    by SEC-R2). Rule 36 is an AST rule over push call sites, there is exactly one
    such site and it is generic — `group_for` can only ever read
    `event.organization_id` — so rule 36 structurally cannot see a payload that
    never carried the key. `events.services._subject_organization` derives the
    fan-out's narrowing from the subject's own `Out` schema, so a schema that
    omits `organization_id` produces an event that no branch owns, and the socket
    door reads that as *tenant-wide*: the row goes to every socket in the tenant.

    The population is derived, never listed: `OrgScopedModel` subclasses off the
    same transitive walk rule 8 uses, located to their app, paired with the
    `*Out` schemas in that app's `schemas.py` by the house naming convention
    (`_camel_suffix_pairs`). A hand-list would go stale the first time somebody
    adds a model, which is the failure class this house has a ledger for.
    """
    out = CheckResult()
    org_by_app = _org_models_by_app(root)
    for models in org_by_app.values():
        out.count("org_scoped_models", len(models))
    for path in _schema_modules(root):
        app = path.parent.name
        models = org_by_app.get(app)
        if not models:
            continue
        rel = str(path.relative_to(root))
        fields = _out_fields_with_inheritance(path)
        tree = _parse(path)
        lines = {}
        if tree is not None:
            lines = {
                node.name: node.lineno for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            }
        for schema, declared in sorted(fields.items()):
            stem = schema[: -len("Out")]
            paired = sorted(m for m in models if _camel_suffix_pairs(m, stem))
            if not paired:
                continue
            out.count("out_schemas_paired")
            if "organization_id" in declared:
                continue
            out.hit(
                rel,
                lines.get(schema, 1),
                f"{schema} is the read shape of {', '.join(paired)} — an OrgScopedModel — "
                "and does not declare `organization_id`. The socket fan-out narrows on that "
                "key and nothing else (`events.services._subject_organization`); a payload "
                "built from this shape carries no branch, and `bridge.group_for` reads "
                "no-branch as TENANT-WIDE. Declare `organization_id: UUID`, or rename the "
                "schema so it does not claim to be this model's read shape.",
            )
    return out


from quality.checks.rule_16_the_rest_of_the_grammar import _model_classes  # noqa: E402
from quality.checks.rule_24 import org_scoped_model_names  # noqa: E402
from quality.checks.rule_36 import (  # noqa: E402
    _camel_suffix_pairs,
    _out_fields_with_inheritance,
    _schema_modules,
)
