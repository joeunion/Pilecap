"""Rule 41's role-promise clause."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse, api_modules

# --- rule 41's role-promise clause ------------------------------------
#
# , and the OWNER'S QUESTION is what makes it a rule: "is there a
# correctness pattern we can enforce here?" had just found that the
# sentence "403 forbidden — you are not an owner or an administrator of the
# tenant" had been PASTED onto five reads in `apps/events` that check no role at
# all. It was not a typo and it was not five typos: `derived_refusals` gives
# every authenticated route a `forbidden`, and a builder writing the prose
# transcribed that superset as though it were a decision somebody had made per
# route. The same sentence was sitting in three more api modules.
#
# WHY NOTHING CAUGHT IT. Every existing mechanism was satisfied. The code is
# registered (rule 41's older clause). It IS reachable — `_acting` raises a bare
# 403 when no tenant resolves — so its overclaim direction is silent and
# correct to be. The route answers 200 for a member and the document says 403,
# and no test compares those two facts. The failure is entirely in the SENTENCE
# somebody wrote about the code: a reader is told there is a permission wall
# where there is none, and the direction of that error is the dangerous one —
# it reads as security and delivers none.
#
# THE PREDICATE. A contract half that promises the caller a ROLE — the
# authorization seam's own refusal named beside a word for a privileged role —
# must have a permission check under it: `core.authz.require(...)` in the route
# body or in a function it calls by a name this tree can resolve, or rule 13's
# `# authz: <reason>` valve on that callee, which is the same declaration rule
# 13 already accepts from a service that delegates its check.
#
# NOTHING HERE IS HAND-COPIED. The code is read off `core.authz.require`'s own
# raise site, so renaming `Forbidden` moves the tell rather than blinding it;
# the role words are read off the role declarations (`roles.py`'s `ROLES` and
# the platform's owner role), which is where this tree declares what
# "privileged" means. Typing `"forbidden"` and
# `{"owner", "admin"}` into this file would be a third copy of two decisions
# that already have homes.

# : Where the authorization seam lives, and its name. House rules 13, 24 and 26
# : all read the same one; it is not this clause's opinion about where a
# : permission check goes.
_AUTHZ_SOURCE = "apps/core/authz.py"
_AUTHZ_SEAM = "require"

# : Rule 13's declared valve, written on the line it excuses. A service that
# : delegates its check to the one it calls says so here, and this clause takes
# : that sentence at its word for the same reason rule 13 does.
_AUTHZ_VALVE = "# authz:"

# : Where the tree declares which roles are privileged (ADR core-25): every
# : `apps/<x>/roles.py` `ROLES` declaration whose patterns include the whole
# : vocabulary, beside the platform's one role, `core.authz.OWNER_ROLE`, whose
# : collection IS the vocabulary and which no `roles.py` may declare.
_ROLES_MODULE = "roles.py"
_ROLES_NAME = "ROLES"
_WHOLE_VOCABULARY = "*"
_PLATFORM_ROLE_NAME = "OWNER_ROLE"


def _policy_refusal_code(root: Path, codes_by_class: dict[str, str]) -> str | None:
    """The code the authorization seam itself answers with.

    Read off `core.authz.require`'s raise site rather than typed here. The tell
    this clause looks for in prose is "the refusal a permission check gives
    you"; deriving it means a rename of that exception class moves the tell
    instead of quietly emptying it.
    """
    tree = _parse(root / _AUTHZ_SOURCE)
    if tree is None:
        return None
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != _AUTHZ_SEAM:
            continue
        codes = _raised_codes(node, codes_by_class)
        # Exactly one, or nothing. A seam that grew a second refusal is a
        # change to what "the permission answer" means, and guessing which of
        # two codes the prose is about would be this clause inventing the
        # decision it exists to read.
        return next(iter(codes)) if len(codes) == 1 else None
    return None


def _privileged_role_words(root: Path) -> set[str]:
    """The role keys this tree declares privileged, as prose spells them.

    The platform role (`core.authz.OWNER_ROLE`, read off its module-level
    assignment) and every declared role whose `permissions` hold the whole
    vocabulary (`"*"`) — `{"owner", "admin"}` on the template. Read off the
    declarations ADR core-25 made the home of authority, so a product's own
    everything-but-ownership role is privileged the day it is declared, and a
    deprecated shim's removal changes nothing here.
    """
    words: set[str] = set()
    authz = _parse(root / _AUTHZ_SOURCE)
    for node in authz.body if authz is not None else []:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == _PLATFORM_ROLE_NAME for t in targets):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                words.add(value.value)
    for app in _app_dirs(root):
        path = app / _ROLES_MODULE
        tree = _parse(path) if path.exists() else None
        entries = _dict_entries(tree, _ROLES_NAME) if tree is not None else None
        if entries is None:
            continue
        for key, value in zip(entries.keys, entries.values, strict=False):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            permissions = next(
                (
                    kw.value
                    for kw in (value.keywords if isinstance(value, ast.Call) else [])
                    if kw.arg == "permissions"
                ),
                None,
            )
            if any(
                isinstance(leaf, ast.Constant) and leaf.value == _WHOLE_VOCABULARY
                for leaf in ast.walk(permissions or ast.Tuple(elts=[]))
            ):
                words.add(key.value)
    return words


def _promising_spans(doc: str | None, *, code: str, roles: set[str], divider: str) -> list[str]:
    """The chunks of a CONTRACT HALF that promise a role check.

    A chunk is a bullet or a paragraph, and the two halves of the tell have to
    meet inside ONE of them. That is what keeps the clause off its own
    corrected prose, which names the owner-or-administrator acts in the very
    sentence that says this read is not one of them — a different bullet, about
    a different code, and a reader would never confuse the two.
    """
    if not doc:
        return []
    lines = []
    for raw in doc.splitlines():
        # The divider and everything under it is the workshop half: notes for
        # whoever maintains this, never a promise to a caller.
        if raw.strip() == divider:
            break
        lines.append(raw)
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        starts_a_bullet = stripped.startswith("* ")
        if starts_a_bullet or not stripped:
            if current:
                chunks.append(" ".join(current))
            current = [stripped] if starts_a_bullet else []
            continue
        current.append(stripped)
    if current:
        chunks.append(" ".join(current))
    found = []
    for chunk in chunks:
        if not re.search(rf"\b{re.escape(code)}\b", chunk):
            continue
        # `admin` reaches `administrator` and `administer`, `owner` reaches
        # `owners`: a docstring writes English, not choice values, and a tell
        # that only matched the literal would miss every sentence it is for.
        if any(re.search(rf"\b{re.escape(word)}[a-z]*\b", chunk, re.I) for word in roles):
            found.append(chunk)
    return found


def _calls_the_seam(node: ast.AST) -> bool:
    """Whether this subtree calls `require(...)`, however it is imported."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id == _AUTHZ_SEAM:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _AUTHZ_SEAM:
            return True
    return False


def _module_file(root: Path, dotted: str) -> Path | None:
    """The file a resolved dotted module names, or None if it is not ours."""
    if not (dotted.startswith("apps.") or dotted.startswith("config.")):
        return None
    base = root.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _declares_the_valve(root: Path, dotted: str, node: ast.AST) -> bool:
    """Whether rule 13's `# authz:` valve is written inside this function.

    A comment, so it is read off the source lines rather than the tree. That is
    the point of the valve: it is a sentence somebody wrote, on the line it
    excuses, that a reviewer can disagree with — the same grammar rule 13 reads
    and rule 26's `# reach:` reads beside it.
    """
    path = _module_file(root, dotted)
    if path is None or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return _function_valve(node, src, src.splitlines(), _AUTHZ_RE) is not None


def _seam_calls(
    root: Path,
    module: str,
    callee: ast.AST,
    cache: dict[str, tuple[dict[str, str], dict[str, str], set[str]]],
) -> set[str]:
    """The seam-module functions a callee calls by a name its own module imported."""
    maps = cache.get(module)
    if maps is None:
        path = _module_file(root, module)
        tree = _parse(path) if path is not None else None
        if tree is None:
            maps = ({}, {}, set())
        else:
            modules, symbols = _import_maps(root, tree, module)
            local = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            maps = (modules, symbols, local)
        cache[module] = maps
    modules, symbols, local = maps
    return {
        name
        for owner, name in _resolved_calls(
            callee, here=module, modules=modules, symbols=symbols, local=local
        )
        if owner == _SECOND_HOP_MODULE
    }


def refusal_block_census(root: Path, rule: dict) -> CheckResult:
    """Rule 41's refusal clauses: the published refusals against the code.

    The first asks whether a code the document names can actually be raised
    here. The second asks the question one layer up — whether a refusal the
    prose describes as a ROLE check has a role check under it.
    """
    out = CheckResult()
    vocabulary = _door_shape_vocabulary(root)
    codes_by_class = _refusal_codes_by_class(root)
    seam_codes = _second_hop_codes(root, codes_by_class)
    callee_maps: dict[str, tuple[dict[str, str], dict[str, str], set[str]]] = {}
    policy_code = _policy_refusal_code(root, codes_by_class)
    role_words = _privileged_role_words(root)
    out.targets_matched["shape_codes"] = len(vocabulary)
    out.targets_matched["refusal_classes"] = len(codes_by_class)
    out.targets_matched["narrowed_routes"] = 0
    out.targets_matched["routes_with_an_unresolved_callee"] = 0
    out.targets_matched["privileged_role_words"] = len(role_words)
    out.targets_matched["role_promising_routes"] = 0
    out.targets_matched["seam_functions"] = len(seam_codes)
    out.targets_matched["seam_calls_followed"] = 0
    divider = _module_string_constants(_parse(root / _CONTRACT_DIVIDER_SOURCE)).get(
        "CONTRACT_DIVIDER", "---"
    )

    for app in _app_dirs(root):
        for path in api_modules(app):
            tree = _parse(path)
            if tree is None:
                continue
            rel = path.relative_to(root).as_posix()
            here = _dotted(root, path)
            modules, symbols = _import_maps(root, tree, here)
            local = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                is_route, declared = _route_decorators(node)
                if not is_route:
                    continue
                added = set(_added_refusals(node))
                out.count("censused_routes")
                if declared is not None:
                    out.count("narrowed_routes")
                calls = _resolved_calls(
                    node, here=here, modules=modules, symbols=symbols, local=local
                )
                opaque = _dispatches_opaquely(node, modules=modules, symbols=symbols, local=local)
                reachable = _raised_codes(node, codes_by_class)
                authorizes = _calls_the_seam(node)
                # What the family seam module raises, reached through a service
                # (or the route itself). Kept apart so a finding it alone makes
                # is its own class: the backlog the second hop found on the day
                # it landed is measured and ratcheted separately, and can never
                # pay for a one-hop underclaim.
                via_seam: set[str] = set()
                for module, name in sorted(calls):
                    if module == _SECOND_HOP_MODULE and name in seam_codes:
                        out.count("seam_calls_followed")
                        via_seam |= seam_codes[name]
                    module, name = _reexported(root, module, name)
                    callee = _function_in(root, module, name)
                    if callee is None:
                        continue
                    out.count("callees_read")
                    reachable |= _raised_codes(callee, codes_by_class)
                    # The second hop, into the family seam module only.
                    for seam in _seam_calls(root, module, callee, callee_maps):
                        if seam in seam_codes:
                            out.count("seam_calls_followed")
                            via_seam |= seam_codes[seam]
                    if _calls_the_seam(callee) or _declares_the_valve(root, module, callee):
                        authorizes = True
                seam_only = via_seam - reachable
                reachable |= via_seam
                if opaque:
                    out.count("routes_with_an_unresolved_callee")

                # . The prose promised a role; the code under it must ask.
                if policy_code and role_words:
                    promises = _promising_spans(
                        ast.get_docstring(node),
                        code=policy_code,
                        roles=role_words,
                        divider=divider,
                    )
                    if promises:
                        out.count("role_promising_routes")
                    if promises and not authorizes:
                        out.hit(
                            rel,
                            node.lineno,
                            f"{node.name} tells a caller that {policy_code!r} here means they are "
                            f"not {' or '.join(sorted(role_words))} — and nothing under it asks. "
                            f"Neither the route body nor a function it calls by name calls "
                            f"`{_AUTHZ_SEAM}(...)` or carries `{_AUTHZ_VALVE} <reason>`. The "
                            "sentence reads as a permission wall and there is none; a member who "
                            "believed it never tries, and a reviewer who believed it never looks "
                            f"(house rule 41). The promise: {promises[0][:120]!r}",
                            root=root,
                            klass="unbacked_promise",
                        )

                published = set(declared) | added if declared is not None else None
                for code in sorted(reachable):
                    if code in added:
                        continue
                    if published is not None:
                        if code in published:
                            continue
                        out.hit(
                            rel,
                            node.lineno,
                            f"{node.name} narrows its refusals with `@refuses(...)` and does not "
                            f"name {code!r}, which something it calls directly raises. A narrowed "
                            "block is a promise that the list is the whole list — a client that "
                            f"branches on the document has no branch for {code!r} and will meet "
                            "one (house rule 41)",
                            root=root,
                            klass="seam_underclaim" if code in seam_only else "underclaim",
                        )
                        continue
                    if code in vocabulary:
                        continue
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} can answer {code!r} — something it calls directly raises "
                        "it — and the door-shape derivation can never produce that code, so the "
                        "document does not mention it anywhere. Narrow the route with "
                        "`@refuses(...)` naming it — or, when the derivation is right and "
                        "this is one more, `@also_refuses(...)` (house rule 41)",
                        root=root,
                        klass="seam_undocumented" if code in seam_only else "undocumented",
                    )
                if published is None or opaque:
                    continue
                for code in sorted(published - reachable - vocabulary):
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} publishes {code!r} and nothing it reaches raises it — not "
                        "its own body and not the services it calls. A refusal a client is told "
                        "to handle and can never meet is a branch nobody will ever exercise "
                        "(house rule 41)",
                        root=root,
                        klass="overclaim",
                    )
    return out


from quality.checks.rule_13_clauses_i_iv import _AUTHZ_RE, _module_string_constants  # noqa: E402
from quality.checks.rule_41_clause import (  # noqa: E402
    _SECOND_HOP_MODULE,
    _added_refusals,
    _dispatches_opaquely,
    _door_shape_vocabulary,
    _function_in,
    _raised_codes,
    _reexported,
    _refusal_codes_by_class,
    _route_decorators,
    _second_hop_codes,
)
from quality.checks.rule_42 import _dotted, _import_maps, _resolved_calls  # noqa: E402
from quality.checks.rule_43 import _CONTRACT_DIVIDER_SOURCE  # noqa: E402
from quality.checks.rule_54 import _dict_entries, _function_valve  # noqa: E402
