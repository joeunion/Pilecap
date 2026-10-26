"""Rule 26: a service names nothing the actor could not have reached."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import _WRITE_MANAGER_CALLS, CheckResult, _parse, _read
from quality.worlds import comment_reason, decorator_names, service_modules

# --- rule 26: a service names nothing the actor could not have reached --------
#
# ADR core-4 (G3). `core.authz.may_be_named(actor, obj)` is the check; this rule
# is what makes calling it non-optional in the one population where forgetting
# it is a leak rather than a bug: a `@service` that WRITES an org-scoped row and
# takes a reference to an org-scoped row it was handed.
#
# The closed question, stated exactly: a `@service` in an app's `services.py`
# that writes an org-scoped row, and takes a parameter ANNOTATED with an
# org-scoped model, must either pass that parameter through `may_be_named`
# somewhere in its body, or carry `# reach: <reason>` on the parameter (or on
# the function). Which keyword arguments are foreign-key targets is unknowable
# in general — ADR core-4 says so, and rejects generic enforcement inside
# `@service` for exactly that reason — so **the annotation is the declaration**
# this rule reads. A target laundered through a local variable, a helper, or an
# unannotated parameter is outside the question, and `does_not_cover` says so
# rather than pretending otherwise.

# The valve. `# reach: <reason>` — a sentence somebody wrote and a reviewer can
# disagree with, on the line it excuses. It is not a disable: every one is
# counted (`reach_valves` on the rule's own status line) and every one is
# visible to `grep -rn "# reach:" apps/`.
_REACH_RE = re.compile(r"#\s*reach:\s*(.*)$")
_ORG_WRITE_CALLS = _WRITE_MANAGER_CALLS | {"update", "delete", "bulk_update"}


def _annotation_names(node: ast.expr | None) -> set[str]:
    """Every class name an annotation mentions. `Widget | None` -> {"Widget"}.

    String annotations are parsed rather than skipped, because a product may
    quote one even with `from __future__ import annotations` on.
    """
    if node is None:
        return set()
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return set()
        try:
            return _annotation_names(ast.parse(node.value, mode="eval").body)
        except (SyntaxError, ValueError):
            return set()
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub is not node:
            out |= _annotation_names(sub)
    return out


def _all_args(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    return list(fn.args.posonlyargs) + list(fn.args.args) + list(fn.args.kwonlyargs)


def _org_bound_names(fn: ast.FunctionDef | ast.AsyncFunctionDef, org_models: set[str]) -> set[str]:
    """Local names this function holds an org-scoped row in, as far as AST sees.

    Three ways to be one: a parameter annotated with an org-scoped model, a name
    annotated with one, and a name assigned from an expression whose chain root
    IS one (`row = Widget(...)`, `row = Message.objects.create(...)`).
    """
    bound = {a.arg for a in _all_args(fn) if _annotation_names(a.annotation) & org_models}
    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_names(node.annotation) & org_models:
                bound.add(node.target.id)
        elif isinstance(node, ast.Assign) and node.value is not None:
            root = _chain_root(node.value)
            if isinstance(root, ast.Name) and root.id in org_models:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.add(target.id)
    return bound


def _named_at_line(fn: ast.AST, param: str) -> int | None:
    """The line of the first `may_be_named(..., <param>)` in this body, or None."""
    lines = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and (
            node.func.id
            if isinstance(node.func, ast.Name)
            else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        )
        == "may_be_named"
        and any(isinstance(a, ast.Name) and a.id == param for a in node.args)
    ]
    return min(lines) if lines else None


def _asked_about_at_line(fn: ast.AST, param: str) -> int | None:
    """The line of the first `require`/`allows` whose OBJECT is `<param>`, or None.

    The subject: reach before capability. The third positional argument is
    the row the question is about, so a `require(actor, key, membership)` is a
    question about THAT row — and asking it before `may_be_named` has cleared
    the row is answering a capability about a row the actor may never have been
    able to name. The answer is then `forbidden` where it should have been
    `not_found`, which tells a caller that a row they cannot reach exists.
    """
    lines = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and (
            node.func.id
            if isinstance(node.func, ast.Name)
            else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        )
        in ("require", "allows")
        and len(node.args) > 2
        and isinstance(node.args[2], ast.Name)
        and node.args[2].id == param
    ]
    return min(lines) if lines else None


def _writes_org_scoped(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    org_models: set[str],
    bound: set[str],
    writable: set[str] | None = None,
) -> bool:
    """Whether this function writes a row one part of a tenant owns.

    Three witnesses, each of them closed:

    1. a manager or queryset write whose chain root names an org-scoped model
       (`Widget.objects.create(...)`, `Message.objects.filter(...).update(...)`);
    2. a `.save()` / `.delete()` on a name bound to an org-scoped row above;
    3. ANY ORM write at all inside a service whose return annotation names an
       org-scoped model — which is how a row assembled by a private helper and
       saved here is still recognised as the row this service writes.
    """
    writes = False
    # THE WRITE POPULATION IS WIDER THAN THE ANNOTATION POPULATION, and the gap
    # is the service this widening exists for: `create_grant(membership=...)`
    # writes a `Grant`, which is not org-scoped and not FK-to-organization —
    # it names its node through the very membership the caller handed in. A
    # write of a row that holds a foreign key to a population member is a write
    # on the strength of that member.
    writable = (writable or set()) | org_models
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr in _ORG_WRITE_CALLS:
            root = _chain_root(node.func.value)
            if isinstance(root, ast.Name) and root.id in writable:
                return True
        if isinstance(node.func, ast.Name) and node.func.id in writable:
            continue
        if attr in ("save", "delete", "update"):
            receiver = node.func.value
            if isinstance(receiver, ast.Name):
                if receiver.id in bound:
                    return True
                if receiver.id not in _NON_MODEL_RECEIVERS:
                    writes = True
    return writes and bool(_annotation_names(fn.returns) & org_models)


def _named_through_may_be_named(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every name handed DIRECTLY to a `may_be_named(...)` call in this function.

    Direct is the whole point . This used to walk each argument and count
    every `Name` inside it, so `may_be_named(actor, widget.parent)` marked
    `widget` checked — while the thing checked was its parent and `widget`
    itself was never asked about. That is the rule's own subject laundered
    through an attribute access, and it read as compliance.

    A bare `Name` argument is the only form that means "this parameter was
    checked". Anything else — an attribute, a subscript, a call, an f-string —
    checks something *derived from* the parameter, which is a different row,
    and the parameter it came from stays unchecked. An author who really did
    mean to clear the parameter writes it, and an author who meant the parent
    writes `# reach:` and says why.
    """
    checked: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name != "may_be_named":
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(arg, ast.Name):
                checked.add(arg.id)
    return checked


def service_reach(root: Path, rule: dict) -> CheckResult:
    """Rule 26. Findings are classed by APP, so one app's backlog cannot pay for
    another app's growth — the per-app numbers in the measurement report and the
    per-app ratchets in `rules.yaml` are the same numbers."""
    out = CheckResult()
    # Two numbers because they answer two questions, and reporting one for both
    # is how the abstract base hid: `org_scoped_models` is the table population (what rule
    # 24 and rule 38 read), `org_scoped_annotations` is what a parameter may be
    # typed with — the same set plus the abstract base a service may honestly
    # name. Both print on this rule's status line, so the day they stop
    # differing by exactly one, somebody can see it.
    concrete = reach_population_names(root)
    org_models = org_scoped_annotation_names(root)
    writable = concrete | _fk_holders_of(root, concrete)
    out.targets_matched["org_scoped_models"] = len(org_scoped_model_names(root))
    out.targets_matched["org_fk_models"] = len(org_fk_model_names(root))
    out.targets_matched["org_scoped_annotations"] = len(org_models)
    # Seeded and printed, like every other census number on this line.
    out.targets_matched["reach_order_checked"] = 0
    # Seeded at zero rather than counted up from nothing, so the rule's own
    # status line always PRINTS the standing valve count — "counted and printed"
    # is the whole discipline, and a key that only appears when it is non-zero
    # is a number nobody sees fall to zero either.
    out.targets_matched["reach_valves"] = 0
    out.targets_matched["reachability_checks"] = 0
    for path in service_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        app = path.relative_to(root).parts[1]
        lines = _read(path).splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in decorator_names(node):
                continue
            bound = _org_bound_names(node, org_models)
            if not _writes_org_scoped(node, org_models, bound, writable):
                continue
            out.count("writing_services")
            checked = _named_through_may_be_named(node)
            top = min([d.lineno for d in node.decorator_list] or [node.lineno])
            whole_function = comment_reason(lines, node.lineno, _REACH_RE) or comment_reason(
                lines, top, _REACH_RE
            )
            for arg in _all_args(node):
                targets = sorted(_annotation_names(arg.annotation) & org_models)
                if not targets:
                    continue
                out.count("fk_target_kwargs")
                if arg.arg in checked:
                    out.count("reachability_checks")
                    # REACH BEFORE CAPABILITY. The check is here rather
                    # than anywhere else because this is the one branch that
                    # knows the parameter WAS cleared — the order only becomes
                    # a question once both halves are present.
                    named_at = _named_at_line(node, arg.arg)
                    asked_at = _asked_about_at_line(node, arg.arg)
                    if named_at is not None and asked_at is not None:
                        out.count("reach_order_checked")
                        if asked_at < named_at:
                            out.hit(
                                rel,
                                asked_at,
                                f"{node.name} asks a capability about `{arg.arg}` at line "
                                f"{asked_at}, BEFORE core.authz.may_be_named clears it at "
                                f"line {named_at} — reach before capability. A "
                                "capability answered about a row the actor could never have "
                                "named answers `forbidden` where the honest answer is "
                                "`not_found`, and the difference tells a caller that a row "
                                "they cannot reach exists. Move the may_be_named above the "
                                "require",
                                klass=app,
                            )
                    continue
                reason = comment_reason(lines, arg.lineno, _REACH_RE)
                if reason is None:
                    reason = whole_function
                if reason is not None:
                    if reason.holds:
                        out.count("reach_valves")
                        continue
                    out.hit(
                        rel,
                        arg.lineno,
                        f"`# reach:` with no reason on {node.name}({arg.arg}=) — an escape "
                        "hatch nobody has to justify is an off switch; write the sentence a "
                        "reviewer can disagree with",
                        klass=app,
                    )
                    continue
                out.hit(
                    rel,
                    arg.lineno,
                    f"{node.name} writes an org-scoped row and takes {arg.arg}: "
                    f"{'/'.join(targets)} without passing it through "
                    "core.authz.may_be_named(actor, ...) — a reference the actor may never "
                    "have been able to reach, in a branch it holds no membership over. Check "
                    "it and refuse when it is False, or record `# reach: <reason>` on the "
                    "parameter (ADR core-4)",
                    klass=app,
                )
    return out


from quality.checks.rule_24 import (  # noqa: E402
    _fk_holders_of,
    org_fk_model_names,
    org_scoped_annotation_names,
    org_scoped_model_names,
    reach_population_names,
)
from quality.checks.rules_10_12 import _NON_MODEL_RECEIVERS, _chain_root  # noqa: E402
