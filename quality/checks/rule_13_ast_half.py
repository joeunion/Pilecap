"""Rule 13 (AST half): services are @service, keyword-only, authorized."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _read
from quality.reason_floor import MIN_REASON
from quality.worlds import decorator_names, service_modules

# --- rule 13 (AST half): services are @service, keyword-only, authorized ------


def service_shape(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    # Read ONCE for the whole run, not once per function: the registry and the
    # key set are facts about the tree, and rebuilding them 500 times is the
    # difference between a check and a leg.
    kinds = model_kinds(root)
    vocabulary = ast_vocabulary(root)
    # Seeded at zero rather than counted up from nothing, so the rule's own
    # status line always PRINTS the four clause-(i)–(iv) numbers — the two
    # populations and the two valve counts. A number that only appears when it
    # is non-zero is a number nobody sees fall to zero either.
    for key in (
        "services_censused",
        "written_kinds_resolved",
        "literal_keys_seen",
        "authz_kind_valves",
        "authz_key_valves",
    ):
        out.targets_matched[key] = 0
    for path in service_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        src = _read(path)
        out.count("service_files")
        rel = str(path.relative_to(root))
        lines = src.splitlines()
        app = path.relative_to(root).parts[1]
        constants = string_constants(root, path, tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            out.count("functions_scanned")
            decorated = "service" in decorator_names(node)
            segment = ast.get_source_segment(src, node) or ""
            writes = _write_calls(ast.parse(segment)) if segment else []
            public = not node.name.startswith("_")
            if public and writes and not decorated and not _exempt(rule, rel, node.name):
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} writes ({writes[0][1]}) but is not @service — undecorated writes "
                    "skip the transaction, the span, the log lines and the audit row",
                )
            if decorated:
                out.count("services_censused")
                positional = [a.arg for a in node.args.args + node.args.posonlyargs]
                if positional or node.args.vararg:
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} is @service with positional parameters "
                        f"({', '.join(positional) or '*args'}) — a service is "
                        "keyword-only: put a bare * before the first parameter",
                    )
                takes_actor = any(a.arg == "actor" for a in node.args.kwonlyargs)
                # `require(` is a CALL, so it stays a source test; the valve is a
                # SENTENCE, read by the one in-function valve reader — a comment
                # line, never a docstring that spells one.
                valve = _function_valve(node, src, lines, _AUTHZ_RE)
                guarded = "require(" in segment or valve is not None
                if takes_actor and valve is not None and not valve.holds:
                    # A VALVE THAT DOES NOT HOLD is its own finding, as every
                    # other valve's is: a bare `# authz:` (or one under the
                    # reason floor) is an off switch nobody had to justify.
                    out.hit(
                        rel,
                        node.lineno,
                        f"`# authz:` on {node.name} carries no reason (under {MIN_REASON} "
                        "characters) — an escape hatch nobody has to justify is an off switch; "
                        "write the sentence a reviewer can disagree with",
                    )
                if takes_actor and not guarded and not _exempt(rule, rel, node.name):
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} takes an actor but never calls authz.require and carries no "
                        "# authz: <reason> — resolving who is asking without asking whether "
                        "they may",
                    )
            if decorated:
                out.findings.extend(
                    _kind_findings(node, rel, app, lines, constants, kinds, vocabulary, out)
                )
    return out


from quality.checks.rule_13_clauses_i_iv import (  # noqa: E402
    _AUTHZ_RE,
    _kind_findings,
    ast_vocabulary,
    model_kinds,
    string_constants,
)
from quality.checks.rule_54 import _function_valve  # noqa: E402
from quality.checks.rules_10_12 import _write_calls  # noqa: E402
