"""Rule 93: a field that names a person is declared `personal` on its `Out` (ADR core-30)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _read
from quality.reason_floor import MIN_REASON
from quality.worlds import comment_reason

# --- rule 93: a person's field declares itself --------------------------------

_MARK = "personal"
_VALVE_RE = re.compile(r"#\s*not-personal:\s*(.*)$")
_CAMEL_WORD = re.compile(r"[A-Z][a-z0-9]*")


def _calls_the_mark(value: ast.expr | None) -> bool:
    """Whether a field's default carries a `personal(...)` call anywhere inside it."""
    if value is None:
        return False
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == _MARK:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _MARK:
            return True
    return False


def _lexicon_hit(schema: str, field: str, lexicon: dict) -> str | None:
    """Why the detector reads this field as a person's, or None."""
    exempt = lexicon.get("exempt") or {}
    last = field.rsplit("_", 1)[-1]
    if last in (lexicon.get("last_word") or []):
        return f"its last word is `{last}`"
    for suffix in lexicon.get("suffix") or []:
        if field.endswith(str(suffix)) and field != str(suffix):
            if field in exempt:
                return None
            return f"it ends `{suffix}`"
    if field in (lexicon.get("bare") or []):
        nouns = set(lexicon.get("person_nouns") or [])
        words = _CAMEL_WORD.findall(schema[: -len("Out")])
        person = next((w for w in words if w in nouns), None)
        if person is not None:
            return f"a bare `{field}` on a shape whose noun is a person (`{person}`)"
    return None


def personal_fields_declared(root: Path, rule: dict) -> CheckResult:
    """Rule 93. Every lexicon hit an `Out` in `apps/*/schemas.py` declares is marked or valved."""
    out = CheckResult()
    lexicon = rule.get("lexicon") or {}
    for path in _schema_modules(root):
        rel = path.relative_to(root).as_posix()
        tree = _parse(path)
        if tree is None:
            continue
        out.count("schema_modules")
        lines = _read(path).splitlines()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name.endswith("Out")):
                continue
            out.count("out_schemas")
            for stmt in node.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                out.count("fields_read")
                field = stmt.target.id
                why = _lexicon_hit(node.name, field, lexicon)
                if why is None:
                    continue
                out.count("lexicon_hits")
                if _calls_the_mark(stmt.value):
                    out.count("marked")
                    continue
                valve = comment_reason(lines, stmt.lineno, _VALVE_RE)
                if valve is not None and valve.holds:
                    out.count("declared")
                    continue
                if valve is not None:
                    out.hit(
                        rel,
                        stmt.lineno,
                        f"`# not-personal:` on {node.name}.{field} carries no reason (under "
                        f"{MIN_REASON} characters) — write the sentence a reviewer can "
                        "disagree with",
                    )
                    continue
                out.hit(
                    rel,
                    stmt.lineno,
                    f"{node.name}.{field} reads as a person's ({why}) and is neither marked nor "
                    "declared — mark it `Field(json_schema_extra=personal(...))` so an event never "
                    "carries it, or write `# not-personal: <reason>` above it",
                )
    return out


from quality.checks.rule_36 import _schema_modules  # noqa: E402
