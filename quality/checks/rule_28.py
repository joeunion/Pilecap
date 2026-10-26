"""Rule 28: every workflow closes its run row (or declares it owns none)."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse
from quality.worlds import reaching

# --- rule 28: every workflow closes its run row (or declares it owns none) -----
#
# ADR workflows-5. The defect this holds closed was not a subtle one: the
# platform app's own SendEmailWorkflow and MoveOrganizationWorkflow never
# marked their `WorkflowRun` finished, so every row they wrote said RUNNING
# for ever, and EchoWorkflow marked itself *completed before doing anything*.
# Each now reaches the finish seam. A rule is what stops the 15th builder's first workflow
# from reopening it, because the wrong shape costs nothing at write time and
# only lies later, to a reader who has no way to know.
#
# THE CLOSED QUESTION, and it has to cover two seams that are both correct:
#
# apps/workflows/workflows.py result, slug = await _finish(work)
# the four domain apps await self._finish(status=..., error=...)
#
# One is a module-level wrapper taking the work as a callable; the other is a
# method on the class. Asking "does it call `mark_run_finished`" would miss
# both (they invoke the activity BY NAME, one level down, which house rule 9
# requires). Asking for one exact call shape would force four apps to rewrite
# a seam that is already right. So the question is: **does the `@workflow.run`
# method reference a SEAM NAME, or name the finish activity, or does the class
# declare `owns_no_run = True`.** A seam name is DERIVED, never a suffix: a
# function that reaches the finish activity — its name as a string, or the
# seam module's constant for it — directly or through another seam name, in
# the workflow seam module (`apps/core/determinism.py`: `finish_run`,
# `run_to_finish`), on the class itself (an app's `_finish` method), or at
# module level in the same `workflows.py`. A suffix read missed `finish_run`
# and would have honoured any `*_finish` that closes nothing.
#
# The declaration half is not a loophole, it is the other real population: a
# workflow started by a Temporal SCHEDULE has no `WorkflowRun` row, because no
# service asked for it and nobody is waiting on a visibility row for the
# deployment's own housekeeping. `owns_no_run = True` says that out loud, on
# the class, where a reviewer meets it.
_FINISH_ACTIVITY = "mark_run_finished"
#: The seam module's own name for the activity, and the module itself.
_FINISH_CONSTANT = "FINISH_ACTIVITY"
_WORKFLOW_SEAM_MODULE = "apps/core/determinism.py"
_OWNS_NO_RUN_ATTR = "owns_no_run"
_WORKFLOWS_LIST = "WORKFLOWS"
_RUN_DECORATOR = "run"


def _declared_workflow_names(tree: ast.Module) -> set[str]:
    """The class names in this module's `WORKFLOWS` list(s) — the population.

    Read off the list the worker's discovery (`apps.core.discovery.declared`)
    actually hands it, not off "every class with @workflow.defn": the list is
    what gets registered on the worker, so it is what can run, so it is what
    must close its rows.
    """
    names: set[str] = set()
    for value in _assigned_values(tree, _WORKFLOWS_LIST):
        if isinstance(value, (ast.List, ast.Tuple)):
            names |= {e.id for e in value.elts if isinstance(e, ast.Name)}
    return names


def _run_method(node: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for stmt in node.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in stmt.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr == _RUN_DECORATOR:
                return stmt
    return None


def _names_used(fn: ast.AST) -> set[str]:
    """Every name a body references: bare names, attribute names, and string constants."""
    used: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            used.add(node.value)
    return used


def _seam_names(
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef], known: frozenset[str] = frozenset()
) -> set[str]:
    """The names among `functions` reaching the finish activity or a `known` seam, transitively."""
    seeds = {_FINISH_ACTIVITY, _FINISH_CONSTANT} | known
    edges = {fn.name: _names_used(fn) for fn in functions}
    return reaching(edges, seeds) - {_FINISH_ACTIVITY, _FINISH_CONSTANT}


def _module_seam_names(root: Path) -> frozenset[str]:
    """The workflow seam module's functions that close a run (`finish_run`, `run_to_finish`)."""
    tree = _parse(root / _WORKFLOW_SEAM_MODULE)
    if tree is None:
        return frozenset()
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return frozenset(_seam_names(functions))


def _references_finish_seam(fn: ast.FunctionDef | ast.AsyncFunctionDef, seam: set[str]) -> bool:
    used = _names_used(fn)
    return bool(used & seam) or _FINISH_ACTIVITY in used or _FINISH_CONSTANT in used


def workflows_close_runs(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    module_seam = _module_seam_names(root)
    out.count("seam_names", len(module_seam))
    for app in _app_dirs(root):
        wf = app / "workflows.py"
        tree = _parse(wf) if wf.exists() else None
        if tree is None:
            continue
        rel = wf.relative_to(root).as_posix()
        population = _declared_workflow_names(tree)
        if not population:
            continue
        out.count("workflow_modules")
        module_functions = [
            n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name not in population:
                continue
            out.count("workflow_classes")
            if _class_attribute_is_true(node, _OWNS_NO_RUN_ATTR):
                out.count("declared_no_run")
                continue
            run = _run_method(node)
            if run is None:
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} is registered in WORKFLOWS with no @workflow.run method — "
                    "a class the worker will register and can never execute",
                    klass="workflows",
                )
                continue
            methods = [
                n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            others = [fn for fn in module_functions + methods if fn is not run]
            seam = _seam_names(others, frozenset(module_seam))
            if _references_finish_seam(run, seam):
                continue
            out.hit(
                rel,
                node.lineno,
                f"{node.name}.run() never reaches the finish seam — a WorkflowRun row was "
                "written when this was started and nothing here closes it, so it says RUNNING "
                "for ever. Call the finish seam LAST (`run_to_finish` or `finish_run` from "
                "`apps.workflows.determinism`, or a method reaching the finish activity), or "
                "declare "
                f"`{_OWNS_NO_RUN_ATTR} = True` on the class if it is schedule-started and owns "
                "no row (ADR workflows-5).",
                klass="workflows",
            )
    return out


from quality.checks.rule_18 import _assigned_values  # noqa: E402
from quality.checks.rule_20_enforceable_half import _class_attribute_is_true  # noqa: E402
