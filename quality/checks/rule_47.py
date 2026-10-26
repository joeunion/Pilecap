"""Rule 47: a declared refusal reaches the document."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from quality.checks._hub import CheckResult, _parse

# --- rule 47: a declared refusal reaches the document --------------------------
#
# its find, and the reason it is a rule rather than a fix: the drop is
# SILENT. `config/api.py::_document_operation` turns a route's refusal codes into
# responses through `CODE_STATUS.get(code)` guarded by `if status is not None`,
# so a code with no status leaves the document without a word — the route still
# refuses that way on the wire, and the published `x-refusal-codes` a generated
# client switches on has no branch for it.
#
# WHERE THE STATUS COMES FROM MOVED (ADR core-23, 2026-08-29) and this
# rule's messages moved with it. `CODE_STATUS` was a hand-appended block in
# `config/api.py`; it is now DERIVED — `CODE_STATUSES` in
# `apps/core/exceptions.py`, fed by `status=` on each `register_refusal(...)`
# call at its declaring site. The finding below therefore names the declaring
# site, not a table to append to: a message that sends a builder to a table that
# no longer exists teaches an edit the tree refuses.
#
# PRODUCTION STAYS TOLERANT. The mount does not raise for this and must not: the
# document is built at import, and a refusal to build it takes the whole API down
# on the machine that ran the server — rule 44's docstring records that exact
# malady. The gate is the right time, on the machine that ran `uv sync`.


def _code_status_drop_site(root: Path) -> tuple[str, int]:
    """Where the silent drop is written, DERIVED rather than typed.

    A finding that names `config/api.py:953` is right until somebody adds a line
    above it, so the line is found by reading for the guard itself.
    """
    rel = "config/api.py"
    path = root / rel
    tree = _parse(path)
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "status"
                and any(isinstance(op, ast.IsNot) for op in test.ops)
            ):
                return rel, node.lineno
    return rel, 0


def declared_refusals_documented(root: Path, rule: dict) -> CheckResult:
    """Rule 47. Every refusal a bound operation can answer with is in the document.

    The probe (`quality/refusal_probe.py`) is a subprocess for rule 44's reason:
    `document_api()` runs at import of `config/api.py`, so a gate that imported
    it would take every other rule's canary down with it the day that import
    broke.

    Two branches, and the difference between them is the whole of . A missing
    code that ALSO carries no registered status is the one drop this rule has
    proven, and the finding names the declaring `register_refusal` site to give
    a `status=` to. A missing code that DOES carry one went somewhere else, and
    the finding says exactly that — a violation that admits what it has not
    established, rather than one that names a cause it guessed.
    """
    out = CheckResult()
    proc = subprocess.run(
        [sys.executable, str(root / "quality" / "refusal_probe.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout)
    except (ValueError, TypeError):
        report = None
    if proc.returncode != 0 or not isinstance(report, dict):
        out.hit(
            _CENSUS_DECLARATION,
            0,
            "rule 47's probe could not read the document at all (exit "
            f"{proc.returncode}) — the mount did not import, or did not answer. That is "
            "enforcement broken and not a clean document; the floors below say so as exit "
            f"2. Output:\n{(proc.stdout + proc.stderr).strip()[-1500:]}",
            klass="probe",
        )
        return out

    out.count("operations_checked", int(report.get("operations", 0)))
    out.count("registry_codes", int(report.get("registry_codes", 0)))
    # ONE REGISTRY, TWO WITNESSES, HELD EQUAL. Rule 41 reads the codes off the
    # tree (`code = "..."` on every refusal class, `_refusal_codes_by_class`);
    # this probe reads the live registry both doors populate at import. They
    # are one population, and a code one reader holds and the other does not is
    # a registry that answers differently depending on who asks.
    live = {str(code) for code in report.get("registry") or ()}
    sites = {code: (rel, line) for code, rel, line in _refusal_code_sites(root).values()}
    for code in sorted(live ^ set(sites)):
        where, at = sites.get(code, (_CENSUS_DECLARATION, 0))
        out.hit(
            where,
            at,
            f"the refusal code `{code}` is "
            + (
                "registered at import and declared by no refusal class on the tree"
                if code in live
                else "declared by a refusal class on the tree and never registered at import"
            )
            + " — the two readers of the one registry disagree; register the code beside "
            "the class that raises it (`register_refusal`), or retire the class",
            klass="registry-readers",
        )
    out.count("documented_codes", int(report.get("documented_codes", 0)))
    out.count("narrowed_routes", int(report.get("narrowed_routes", 0)))

    table_rel, table_line = _code_status_drop_site(root)
    for drop in report.get("drops") or []:
        code = str(drop.get("code"))
        route = str(drop.get("route"))
        said = "declares with `@refuses(...)`" if drop.get("declared") else "derives"
        if not drop.get("in_code_status"):
            out.hit(
                str(drop.get("path")),
                int(drop.get("line") or 1),
                f"`{route}` {said} the refusal `{code}`, and the published document does "
                f"not carry it. `{code}` has no status in the refusal registry, so "
                f"`_document_operation`'s `if status is not None` ({table_rel}:{table_line}) "
                "drops it without a word: the route refuses that way on the wire and a "
                "client that branches on `x-refusal-codes` has no branch for it. Give the "
                f"code its number where it is DECLARED — `status=<4xx or 5xx>` on the "
                f'`register_refusal(code="{code}", ...)` call beside the class that raises '
                "it — in the same commit that registers the code. `CODE_STATUS` in "
                "config/api.py is DERIVED off the registry (ADR core-23) and is not a "
                "table anybody appends to any more",
                root=root,
                klass="unmapped",
            )
        else:
            out.hit(
                str(drop.get("path")),
                int(drop.get("line") or 1),
                f"`{route}` {said} the refusal `{code}`, and the published document does "
                f"not carry it — AND `{code}` DOES carry a registered status "
                f"({drop.get('status')}), so it is in the derived `CODE_STATUS`, "
                f"so this is NOT the `if status is not None` drop at {table_rel}:{table_line} "
                "that this rule has proven. Where it went is UNDIAGNOSED: this message says "
                "so rather than naming a cause nobody established, and the fix starts by "
                "finding out",
                root=root,
                klass="undiagnosed",
            )
    for bullet in report.get("unpublished_bullets") or []:
        code = str(bullet.get("code"))
        out.hit(
            str(bullet.get("path")),
            int(bullet.get("line") or 1),
            f"`{bullet.get('route')}`'s docstring bullets `{code}` and the published document "
            f"does not carry it — a client told to handle `{code}` has no branch for it in "
            "`x-refusal-codes`. Publish it (`@also_refuses(...)` naming it), or drop the bullet",
            root=root,
            klass="unpublished_bullet",
        )
    return out


from quality.checks.rule_41_clause import _refusal_code_sites  # noqa: E402
from quality.checks.rule_44 import _CENSUS_DECLARATION  # noqa: E402
