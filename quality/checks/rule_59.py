"""Rule 59: an org-scoped event carries its branch (R4 F4/F5)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import (
    _EVENT_KINDS_NAME,
    _UNDECIDED_DRAFT_MARKER,
    CheckResult,
    _app_dirs,
    _parse,
    _py_files,
    _read,
    event_name_segments,
)

# --- rule 59: an org-scoped event carries its branch (R4 F4/F5) ---------------
#
# THE FINDING. `events.services._subject_organization` reads only the payload's
# TOP-LEVEL `organization_id`; absent means NULL, and `bridge.group_for` reads
# NULL as tenant-wide. Rule 38 certifies that an org-scoped model's `Out`
# DECLARES the key; nothing certified that an emit site PASSES one. The live
# instance R4 found is `usage.threshold.crossed`: `ThresholdCrossingOut` has no
# top-level `organization_id` and its nested `crossed_by` is an org-scoped
# `UsageEntryOut`, so a rival administrator at branch B received a ledger row
# that `GET /usage/` under hat B never lists. Generalised: ANY hand dict that
# omits the key.
#
# AND THE OTHER DIRECTION (F5). A noun an app maps to `None` in `EVENT_KINDS`
# while the app declares a model of that name is an event about a real row
# declared to be about nothing — `consumers._may_read` answers True for a
# `None` kind regardless of the branch, so such a frame bypasses the read set
# entirely. The `ImproperlyConfigured` text itself offers the `None` road and
# the noun census accepts any `None`, which is what makes this worth a rule.

_EMIT_CALL = "emit"
_ORG_KEY_NAME = "organization_id"
_OUT_SUFFIX = "Out"


def _event_kinds_declared(root: Path) -> dict[str, dict[str, str | None]]:
    """{app label: {noun: kind or None}} — every app's `EVENT_KINDS`, by AST.

    The same declaration `core.authz.event_kinds_of` reads at runtime, read here
    without importing anything, so the rule sees what the door sees.
    """
    declared: dict[str, dict[str, str | None]] = {}
    for app in _app_dirs(root):
        tree = _parse(app / "events.py")
        if tree is None:
            continue
        for node in tree.body:
            names, value = _assigned(node)
            if not names:
                continue
            if _EVENT_KINDS_NAME not in names or not isinstance(value, ast.Dict):
                continue
            mapping: dict[str, str | None] = {}
            for key, item in zip(value.keys, value.values, strict=False):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                if isinstance(item, ast.Constant) and (
                    item.value is None or isinstance(item.value, str)
                ):
                    mapping[str(key.value)] = item.value
            declared[app.name] = mapping
    return declared


def _org_scoped_kind_names(root: Path) -> set[str]:
    """Every authorization kind whose model is an `OrgScopedModel`.

    DERIVED from the two walks rules 24, 38 and 55 already share — the
    transitive `OrgScopedModel` closure and `model_kinds` — so a model that
    gains a branch joins this population on the run it joins theirs.
    """
    kinds = model_kinds(root)
    return {
        kind
        for name in org_scoped_model_names(root)
        for kind in [kinds.get(name)]
        if isinstance(kind, str)
    }


def _certified_out_schemas(root: Path) -> set[str]:
    """Every `Out` schema that DECLARES `organization_id` — rule 38's own half.

    Rule 38 keeps the key on an org-scoped model's `Out`; this reads which
    schemas actually carry it, so "a rule-38-certified `Out`" is a fact about
    the tree rather than a claim about the rule.
    """
    certified: set[str] = set()
    for path in _schema_modules(root):
        for name, fields in _out_fields_with_inheritance(path).items():
            if _ORG_KEY_NAME in fields:
                certified.add(name)
    return certified


def _names_a_certified_out(node: ast.AST, certified: set[str]) -> bool:
    """Whether this expression mentions an `Out` schema carrying the key."""
    return any(isinstance(sub, ast.Name) and sub.id in certified for sub in ast.walk(node)) or any(
        isinstance(sub, ast.Attribute) and sub.attr in certified for sub in ast.walk(node)
    )


def _dict_names_the_key(node: ast.AST) -> bool:
    """Whether this expression builds a display with an `organization_id` key."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == _ORG_KEY_NAME for key in sub.keys
        ):
            return True
        if isinstance(sub, ast.keyword) and sub.arg == _ORG_KEY_NAME:
            return True
    return False


def _payload_carries_the_branch(
    node: ast.expr,
    *,
    certified: set[str],
    locals_bound: dict[str, ast.expr],
    helpers: dict[str, ast.AST],
    depth: int = 0,
) -> bool:
    """Whether this payload expression provably carries the narrowing key.

    Four forms, and they are the four the tree actually writes:

    * a dict display naming `organization_id`;
    * anything mentioning an `Out` schema that declares it (rule 38's certificate);
    * a name the enclosing scope bound to either of those;
    * a call to a helper in the same module whose `return`s are one of the above
      — `comms`' `_payload(message)` is that shape, and a rule that could not
      follow one hop would call thirteen honest emit sites violations.

    Bounded at two hops, deliberately: a payload assembled across modules is a
    declared blind spot rather than a walk that guesses.
    """
    if depth > 2:
        return False
    if _dict_names_the_key(node) or _names_a_certified_out(node, certified):
        return True
    if isinstance(node, ast.Name) and node.id in locals_bound:
        return _payload_carries_the_branch(
            locals_bound[node.id],
            certified=certified,
            locals_bound={k: v for k, v in locals_bound.items() if k != node.id},
            helpers=helpers,
            depth=depth + 1,
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `crossing.model_dump(mode="json")` — the body is whatever `crossing`
        # holds, and the receiver is where the certificate lives. Without this
        # the walk stops at the method name and calls the tree's most ordinary
        # emit shape a violation.
        if _payload_carries_the_branch(
            node.func.value,
            certified=certified,
            locals_bound=locals_bound,
            helpers=helpers,
            depth=depth + 1,
        ):
            return True
    if isinstance(node, ast.Call):
        callee = _callee_name(node.func)
        helper = helpers.get(callee or "")
        if helper is not None:
            return any(
                isinstance(sub, ast.Return)
                and sub.value is not None
                and _payload_carries_the_branch(
                    sub.value,
                    certified=certified,
                    locals_bound=_bound_in(helper),
                    helpers={k: v for k, v in helpers.items() if k != callee},
                    depth=depth + 1,
                )
                for sub in ast.walk(helper)
            )
    return False


def _bound_in(scope: ast.AST) -> dict[str, ast.expr]:
    """`name -> expression` for every simple assignment inside this scope."""
    bound: dict[str, ast.expr] = {}
    for sub in ast.walk(scope):
        names, value = _assigned(sub)
        if value is not None:
            for name in names:
                bound[name] = value
    return bound


def _module_helpers(tree: ast.Module) -> dict[str, ast.AST]:
    """Every function this module defines, by name — the one hop the walk follows."""
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


from quality.checks.rule_13_clauses_i_iv import _assigned, model_kinds  # noqa: E402
from quality.checks.rule_24 import org_scoped_model_names  # noqa: E402
from quality.checks.rule_36 import (  # noqa: E402
    _callee_name,
    _out_fields_with_inheritance,
    _schema_modules,
)


def event_noun_segment() -> int:
    """Which segment is the noun: the one before the past verb."""
    return event_name_segments() - 2


def _event_name_constants(root: Path) -> list[tuple[str, str, str, int]]:
    """(app label, constant, event name, line) for every name an app declares.

    The population is the same one `apps.events.events.declared_names` builds at
    runtime and `manage.py introspect` publishes — read here by AST, from the
    file that declares it, so the static rule and the runtime census are looking
    at one list. Module level only and UPPERCASE only: house rule 16 makes an
    event name a constant with one definition, and a lowercase local holding a
    name is a caller's variable rather than a declaration.
    """
    found: list[tuple[str, str, str, int]] = []
    for app in _app_dirs(root):
        tree = _parse(app / "events.py")
        if tree is None:
            continue
        for node in tree.body:
            targets, value = _assigned(node)
            if not targets:
                continue
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            text = str(value.value)
            if len(text.split(".")) < event_name_segments():
                continue
            for target in targets:
                if target.isupper():
                    found.append((app.name, target, text, node.lineno))
    return found


def _all_out_fields(root: Path) -> dict[str, dict[str, str]]:
    """`{OutClassName: {field: annotation}}` across every app's `schemas.py`."""
    merged: dict[str, dict[str, str]] = {}
    for path in _schema_modules(root):
        merged.update(_out_fields_with_inheritance(path))
    return merged


def _out_named_in(
    node: ast.expr,
    out_names: set[str],
    *,
    locals_bound: dict[str, ast.expr],
    helpers: dict[str, ast.AST],
    depth: int = 0,
) -> str | None:
    """Which `Out` schema this payload expression mentions, or None.

    The SAME two-hop walk `_payload_carries_the_branch` makes — a name the scope
    bound, a receiver's method call, one hop into a module-local helper's
    returns — and it is written beside it rather than folded into it because the
    two answer different questions: that one asks whether the key is provably
    there (and must fail CLOSED), this one asks which schema the body is (and
    must not guess). Sharing the traversal by having the first return a name
    would make a walk that is allowed to be wrong here able to be wrong there.
    """
    if depth > 2:
        return None
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in out_names:
            return sub.id
        if isinstance(sub, ast.Attribute) and sub.attr in out_names:
            return sub.attr
    if isinstance(node, ast.Name) and node.id in locals_bound:
        return _out_named_in(
            locals_bound[node.id],
            out_names,
            locals_bound={k: v for k, v in locals_bound.items() if k != node.id},
            helpers=helpers,
            depth=depth + 1,
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `crossing.model_dump(mode="json")` — the tree's most ordinary emit
        # shape. The schema is on the RECEIVER, and a walk that stopped at the
        # method name would hand every such site the `?` draft.
        named = _out_named_in(
            node.func.value,
            out_names,
            locals_bound=locals_bound,
            helpers=helpers,
            depth=depth + 1,
        )
        if named is not None:
            return named
    if isinstance(node, ast.Call):
        callee = _callee_name(node.func)
        helper = helpers.get(callee or "")
        if helper is not None:
            for sub in ast.walk(helper):
                if not (isinstance(sub, ast.Return) and sub.value is not None):
                    continue
                named = _out_named_in(
                    sub.value,
                    out_names,
                    locals_bound=_bound_in(helper),
                    helpers={k: v for k, v in helpers.items() if k != callee},
                    depth=depth + 1,
                )
                if named is not None:
                    return named
    return None


def _emit_sites_by_name(root: Path, out_names: set[str]) -> dict[str, tuple[str, int, str | None]]:
    """`event name -> (file, line, the Out its payload mentions)`, first site wins.

    First and not every: the draft line names ONE site as the evidence for the
    kind it proposes, and a reader who disagrees with the proposal is better
    served by one file:line they can open than by a list they have to reconcile.
    """
    sites: dict[str, tuple[str, int, str | None]] = {}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None or _is_test_module(str(path.relative_to(root))):
            continue
        rel = str(path.relative_to(root))
        constants = string_constants(root, path, tree)
        helpers = _module_helpers(tree)
        bound = _bound_in(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _callee_name(node.func) != _EMIT_CALL:
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            name_node, payload = keywords.get("name"), keywords.get("payload")
            if name_node is None or payload is None:
                continue
            if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str):
                event_name: str | None = name_node.value
            elif isinstance(name_node, ast.Name):
                event_name = constants.get(name_node.id)
            else:
                event_name = None
            if event_name is None or event_name in sites:
                continue
            sites[event_name] = (
                rel,
                node.lineno,
                _out_named_in(payload, out_names, locals_bound=bound, helpers=helpers),
            )
    return sites


def _model_paired_with(out_name: str, models: set[str]) -> str | None:
    """The model an `Out` schema reports, by rule 16's own pairing.

    Exact match first, then `_camel_suffix_pairs`' one legal looseness (a schema
    that drops a qualifying prefix the model carries). Exact first and not
    merely sorted: `PreferenceOut` suffix-pairs with `ChannelPreference`, and a
    tree that also declared a `Preference` would otherwise get whichever name
    came first in the alphabet.
    """
    stem = out_name[: -len(_OUT_SUFFIX)]
    if stem in models:
        return stem
    paired = sorted(model for model in models if _camel_suffix_pairs(model, stem))
    return paired[0] if len(paired) == 1 else None


def _nested_certified_out(
    out_name: str, fields: dict[str, dict[str, str]], certified: set[str]
) -> str | None:
    """A certified `Out` mentioned in an UNCERTIFIED one's field annotations.

    The consumer's nine uncertified outer schemas, and `usage.threshold.crossed`'s
    own shape: the body is about an
    org-scoped row, the key is one level down, and `_subject_organization` reads
    only the top level. Naming the inner schema in the draft is what stops the
    reader proposing a kind whose events would then be broadcast tenant-wide.
    """
    if out_name in certified:
        return None
    for annotation in fields.get(out_name, {}).values():
        for inner in sorted(certified):
            if re.search(rf"\b{re.escape(inner)}\b", annotation):
                return inner
    return None


def org_scoped_events_carry_their_branch(root: Path, rule: dict) -> CheckResult:
    """Rule 59. An org-scoped event carries its branch; an org-less kind names none.

    Three classes:

    * **`emit`** — every `emit(name=..., payload=...)` whose noun resolves to an
      org-scoped kind passes a payload that provably carries `organization_id`.
    * **`none_mapping`** — a noun an app maps to `None` in `EVENT_KINDS` while
      that app declares a model of that name.
    * **`undecided_noun`** — a declared event name whose noun is neither an
      authorization kind nor a key of its app's `EVENT_KINDS`. The rule-59
      amendment the owner signed 2026-09-21 took this refusal out of
      `emit()`, where it cost the product's write; this class is where the tree
      refuses it instead, and **the finding IS the draft line to paste**.
    """
    out = CheckResult()
    org_kinds = _org_scoped_kind_names(root)
    certified = _certified_out_schemas(root)
    declared = _event_kinds_declared(root)
    kinds = model_kinds(root)
    out.count("org_scoped_kinds", len(org_kinds))
    # SEEDED AT ZERO SO IT PRINTS WHATEVER IT IS. The population this rule
    # cannot judge is the one the `does_not_cover` used to give a TYPED number
    # for, and a typed count rots: it said four while the tree carried eight.
    # A class nobody counts is an off switch, so the blind half is printed on
    # the status line beside the seeing half and the sentence names the class.
    out.count("unresolvable_emit_sites", 0)

    models_by_app: dict[str, set[str]] = {}
    for path in _model_files(root):
        parts = path.relative_to(root).parts
        if len(parts) < 2:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        models_by_app.setdefault(parts[1], set()).update(
            kind
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for kind in [kinds.get(node.name)]
            if isinstance(kind, str)
        )

    for app_label, mapping in declared.items():
        for noun, kind in mapping.items():
            if kind is not None:
                continue
            out.count("none_mappings")
            if noun not in models_by_app.get(app_label, set()):
                continue
            out.hit(
                f"apps/{app_label}/events.py",
                1,
                f"`{noun}` is mapped to None in {_EVENT_KINDS_NAME} while `apps/{app_label}` "
                f"declares a model whose authorization kind IS {noun!r}. A None kind means "
                "'no row is behind this', and the socket door answers True for one whatever "
                "branch the frame names (`consumers._may_read`) — so a real row's event "
                "declared org-less bypasses the read set for every connection in the tenant. "
                f"Map it to the kind whose `{noun}.read` governs it",
                klass="none_mapping",
            )

    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        constants = string_constants(root, path, tree)
        helpers = _module_helpers(tree)
        bound = _bound_in(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _callee_name(node.func) != _EMIT_CALL:
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            name_node, payload = keywords.get("name"), keywords.get("payload")
            if name_node is None or payload is None:
                continue
            if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str):
                event_name: str | None = name_node.value
            elif isinstance(name_node, ast.Name):
                event_name = constants.get(name_node.id)
            else:
                event_name = None
            if event_name is None:
                # The noun is what decides whether the question applies, and a
                # guessed noun is a guessed answer — so this site is out of the
                # population entirely and COUNTED on the way out. Each one is
                # somebody else's control flow (a parameter, a conditional, a
                # table lookup); the runtime belt in `emit()` is what covers
                # them, which is why the rule and the belt ship together.
                out.count("unresolvable_emit_sites")
                continue
            out.count("emit_sites")
            segments = event_name.split(".")
            noun_at = event_noun_segment()
            if len(segments) <= noun_at:
                continue
            app_label, noun = segments[0], segments[noun_at]
            kind = noun if noun in org_kinds or noun in kinds.values() else None
            if kind is None:
                kind = declared.get(app_label, {}).get(noun)
            if kind not in org_kinds:
                continue
            if _payload_carries_the_branch(
                payload, certified=certified, locals_bound=bound, helpers=helpers
            ):
                continue
            out.hit(
                rel,
                node.lineno,
                f"`{event_name}` is about {kind!r}, which is an org-scoped row, and this "
                f"payload does not carry `{_ORG_KEY_NAME}` at its top level. "
                "`events.services._subject_organization` reads only the top level and an "
                "absent key is NULL, which `bridge.group_for` reads as TENANT-WIDE — so "
                "every branch's socket hears this branch's row, while the REST list under "
                "the same hat never shows it. Pass the row's own rule-38-certified `Out` "
                f"dump, or a display carrying `{_ORG_KEY_NAME}`",
                klass="emit",
            )

    # --- class 4: the needless map entry ----------------------------------------
    # `core.authz.kind_of_event` asks the registry FIRST: a noun that IS a kind
    # answers itself, and the app's `EVENT_KINDS` line for it is never read — a
    # dead entry that reads like a decision (and may name a kind no model
    # carries any more). Counted as `needless-kind-map`, down-only.
    kind_names = {kind for kind in kinds.values() if isinstance(kind, str)}
    for app_label, mapping in sorted(declared.items()):
        lines = _read(root / "apps" / app_label / "events.py").splitlines()
        for noun, mapped in sorted(mapping.items()):
            out.count("event_kind_entries")
            # A kind mapped to None is class `none_mapping`'s (a real row
            # declared org-less) — named once, by the class that says why.
            if noun not in kind_names or mapped is None:
                continue
            at = next(
                (
                    i
                    for i, line in enumerate(lines, 1)
                    if re.match(rf'\s*["\']{noun}["\']\s*:', line)
                ),
                1,
            )
            out.hit(
                f"apps/{app_label}/events.py",
                at,
                f"{_EVENT_KINDS_NAME}[{noun!r}] = {mapped!r} is never read — `{noun}` is itself an "
                "authorization kind, and `kind_of_event` asks the kinds first; delete the line "
                "(an event noun that is a kind needs no map)",
                klass="needless-kind-map",
            )

    # --- class 3: the undecided noun (the signed amendment) ----------------
    out_fields = _all_out_fields(root)
    sites = _emit_sites_by_name(root, set(out_fields))
    seen_nouns: set[tuple[str, str]] = set()
    for app_label, constant, event_name, lineno in _event_name_constants(root):
        out.count("declared_names")
        noun = event_name.split(".")[event_noun_segment()]
        if noun in kind_names or noun in declared.get(app_label, {}):
            continue
        if (app_label, noun) in seen_nouns:
            # ONE finding per noun, not per name. Three constants sharing a noun
            # are one missing line, and printing it three times makes the reader
            # decide whether they are three problems.
            continue
        seen_nouns.add((app_label, noun))
        site = sites.get(event_name)
        draft = f'"{noun}": ?,  # no payload names an Out: a kind, or None with the reason'
        if site is not None and site[2] is not None:
            where, at, out_name = site[0], site[1], site[2]
            model = _model_paired_with(out_name, set(kinds))
            kind = kinds.get(model or "")
            if isinstance(kind, str):
                draft = (
                    f'"{noun}": "{kind}",  # draft: {where}:{at}\'s payload '
                    f"{out_name} names {model}"
                )
            nested = _nested_certified_out(out_name, out_fields, certified)
            if nested is not None:
                draft += f" # via nested {nested}: the outer Out must carry {_ORG_KEY_NAME}"
        out.hit(
            f"apps/{app_label}/events.py",
            lineno,
            f"`{constant}` is `{event_name}`, and `{noun}` is no authorization kind and no "
            f"key of {_EVENT_KINDS_NAME} in apps/{app_label}/events.py — so nothing in this "
            "product can say who may be told it happened. `emit()` no longer refuses this "
            "(the rule-59 amendment, SIGNED by the owner 2026-09-21): the write COMMITS and "
            "the event is recorded, and the cost lands on the socket instead — "
            "`realtime.consumers._may_read` catches the same refusal per frame and DROPS it, "
            f"so this event reaches NOBODY until the line below exists. "
            f"{_UNDECIDED_DRAFT_MARKER}    {draft}",
            klass="undecided_noun",
        )
    return out


from quality.checks.rule_13_clauses_i_iv import string_constants  # noqa: E402
from quality.checks.rule_16_the_rest_of_the_grammar import _model_files  # noqa: E402
from quality.checks.rule_36 import (  # noqa: E402
    _camel_suffix_pairs,
    _is_test_module,
)
