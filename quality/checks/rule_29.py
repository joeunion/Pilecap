"""Rule 29: a role is never granted above the granter."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _read
from quality.worlds import comment_reason, decorator_names, service_modules

# --- rule 29: a role is never granted above the granter -----------------------
#
# The class-closure. A fix closed the two concrete paths
# (`create_sso_connection`, `update_sso_connection`); this rule is what stops
# the next one being written. The defect it holds closed is the worst kind of quiet:
# a service takes `role=` from a door, writes it onto a `Membership`, and an
# admin who could pass `"owner"` becomes an owner — with a clean audit row
# saying they did it on purpose.
#
# THE CLOSED QUESTION: a `@service` whose signature carries a ROLE-SHAPED
# parameter, and whose body puts that parameter into a ROLE POSITION, must show
# a bound against the actor in the same body.
#
# role-shaped name is `role`, `default_role`, or ends `_role`
# role position a `role=`/`*_role=` keyword on any call, or an assignment to
# a `.role`/`.*_role` attribute
# a bound a call to the escalation wall — `_refuse_escalation`, or
# `_refuse_role_above_the_configurer`, which wraps it
#
# The bound is looked for as a CALL to the wall, not as `authz.require`, and
# that is the whole shape of the decision: `require` asks "may this actor act on
# this object"; a grant also has a *role being granted*, and the refusal is
# about the relationship between that role and the granter's own effective role.
# There is no object a policy predicate could inspect that carries it.
#
# The valve is `# role-bound: <reason>`, read with the same grammar as
# `# reach:` and counted the same way, because the honest exceptions are real: a
# path where nobody is granting (an IdP asserted an identity) has no granter to
# measure, and the ceiling lives where a person actually acted.
_ROLE_PARAM = re.compile(r"^(role|default_role|.*_role)$")
_ROLE_WALL = {"_refuse_escalation", "_refuse_role_above_the_configurer"}
# A ROLE POSITION IS A MODEL WRITE. Three things can be one: a model
# constructor keyword (`Membership(role=...)`), a queryset write keyword
# (`.create(role=...)`, `.update(role=...)`), or an attribute assignment
# (`.role = role`). A `role=` handed to another FUNCTION is none of them — the
# row is written there, and there is where the bound belongs.
#
# That distinction is the whole reason `accounts.services.ensure_membership`
# needs no exemption. It forwards `role` to `add_membership`, which is itself a
# @service in this population and is bounded on every path — including this one,
# where the wall correctly short-circuits because no actor is granting (an IdP
# asserted an identity). Judging the forwarder would have demanded an exemption
# with the reason parked in rules.yaml, away from the code; judging the writer
# puts the bound where the row is.
#
# The residual — a role forwarded to a non-@service helper that writes the row —
# is covered one layer down rather than here: rule 13 requires every write in a
# services.py to be a @service, and rule 10 keeps writes out of the doors. It is
# declared on the rule regardless.
_ROLE_WRITE_CALLS = {
    "create",
    "get_or_create",
    "update_or_create",
    "update",
    "bulk_create",
    "bulk_update",
}
# `role=` on a READ narrows a query; it grants nothing, and counting it would
# make every service that so much as filters by role a finding — a rule
# ratcheted into noise is a rule nobody reads. Found by writing the negative
# (`role_never_written.py`), which is what negatives are for.
_ROLE_READ_CALLS = {
    "filter",
    "exclude",
    "get",
    "count",
    "exists",
    "values",
    "values_list",
    "annotate",
    "aggregate",
    "order_by",
    "only",
    "defer",
    "first",
    "last",
    "all",
}
_ROLE_BOUND_RE = re.compile(r"#\s*role-bound:\s*(.*)$")


def _role_positions(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, params: set[str]
) -> list[tuple[int, str]]:
    """(line, description) everywhere a role-shaped PARAMETER lands in a role position."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            callee = _call_name(node)
            # A model CONSTRUCTOR is capitalised (`Membership(...)`); a queryset
            # write is one of the write verbs. Everything else — the wall
            # itself, a read verb, a call to another service — is not a place a
            # row is written, so it is not a role position.
            constructor = bool(callee[:1].isupper())
            if not constructor and callee not in _ROLE_WRITE_CALLS:
                continue
            for kw in node.keywords:
                if (
                    kw.arg
                    and _ROLE_PARAM.match(kw.arg)
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id in params
                ):
                    found.append((node.lineno, f"{callee or 'a call'}({kw.arg}=)"))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and _ROLE_PARAM.match(target.attr)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in params
                ):
                    found.append((node.lineno, f".{target.attr} ="))
    return found


def _plain_string(arg: ast.arg) -> bool:
    """Whether a parameter is unannotated or `str` — a name that may be a job title, not a role."""
    note = arg.annotation
    return (
        note is None
        or (isinstance(note, ast.Name) and note.id == "str")
        or (isinstance(note, ast.Constant) and note.value == "str")
    )


def role_bound_assignment(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    # Two counters, not one: these were ONE counter, so a scope exemption (a
    # judgement parked in rules.yaml, away from the code) and a `# role-bound:`
    # comment (a judgement written where the grant is) added up to a single
    # number nobody could read back. Both start at 0 so both always print —
    # which is what makes the rule's "NO EXEMPTIONS" claim visible rather than
    # merely written down.
    out.targets_matched["role_bound_exemption_valves"] = 0
    out.targets_matched["role_bound_valves"] = 0
    for path in service_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        app = rel.split("/")[1]
        lines = _read(path).splitlines()
        out.count("services_files")
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in decorator_names(node):
                continue
            args = [a for a in _all_args(node) if _ROLE_PARAM.match(a.arg)]
            if not args:
                continue
            out.count("role_param_services")
            params = {a.arg for a in args}
            positions = _role_positions(node, params)
            if not positions:
                # A role-named parameter that never reaches a role position is
                # not this rule's subject, and reading it as one would make
                # every read-only lookup taking `role=` a finding.
                continue
            out.count("role_writing_services")
            if _ROLE_WALL & {_call_name(c) for c in ast.walk(node) if isinstance(c, ast.Call)}:
                out.count("role_bounds")
                continue
            if _exempt(rule, rel, node.name):
                out.count("role_bound_exemption_valves")
                continue
            whole = comment_reason(lines, node.lineno, _ROLE_BOUND_RE)
            reason = next(
                (
                    r
                    for r in (comment_reason(lines, a.lineno, _ROLE_BOUND_RE) for a in args)
                    if r is not None
                ),
                whole,
            )
            line, where = positions[0]
            named = "/".join(sorted(params))
            if reason is not None:
                if reason.holds:
                    out.count("role_bound_valves")
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"`# role-bound:` with no reason on {node.name}("
                    f"{'/'.join(sorted(params))}=) — an escape hatch nobody has to justify is "
                    "an off switch; write the sentence a reviewer can disagree with",
                    klass=app,
                )
                continue
            valve = (
                f"carry # role-bound: <reason> on the parameter when {named} is a plain "
                "field (a job title)"
            )
            wall = (
                "call the escalation wall (_refuse_escalation / _refuse_role_above_the_configurer)"
            )
            remedy = (
                f"{valve}, or {wall} when it is an authorization role"
                if all(_plain_string(a) for a in args)
                else f"{wall}, or {valve}"
            )
            out.hit(
                rel,
                line,
                f"{node.name} puts {named} into a role position ({where}) with no bound "
                f"against the actor: {remedy}. Recording a ratchet is the second road, for a "
                "real grant left open on purpose — an admin who may pass 'owner' becomes an "
                "owner, and the audit row says they meant to",
                klass=app,
            )
    return out


from quality.checks.rule_16_the_rest_of_the_grammar import _call_name  # noqa: E402
from quality.checks.rule_26 import _all_args  # noqa: E402
