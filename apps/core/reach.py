"""The one reader of a template rule's scope joined by the drawer's `scope_extensions:`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from apps.core.reason_floor import MIN_REASON

#: The product's drawer, the key its extensions live under, and the rule-level mark that opens one.
RULES_DRAWER = "quality/local/rules.yaml"
EXTENSIONS_KEY = "scope_extensions"
REACH_KEY = "reach"
PRODUCT = "product"
#: A list whose drawer home predates this road keeps it: rule 16's verbs (`quality/engine/lexicon`).
OWN_KEYS: dict[tuple[str, str], str] = {("16", "service_verbs"): "service_verbs"}


def road(rule_id: str) -> str:
    """The one sentence a refusal of a reachable list prints, naming the road."""
    return f"a product adds its own under `{EXTENSIONS_KEY}: {{{rule_id}: …}}` in {RULES_DRAWER}"


def product_reachable(rule: Mapping[str, Any]) -> frozenset[str]:
    """The scope keys this rule declares `reach: product` on; every other list is the template's."""
    marks = rule.get(REACH_KEY)
    if not isinstance(marks, Mapping):
        return frozenset()
    return frozenset(str(k) for k, v in marks.items() if v == PRODUCT)


def _identity(entry: object) -> set[tuple[str, str]]:
    """What an entry names: every field but its reason, so one shared field is one shared entry."""
    if isinstance(entry, Mapping):
        return {(str(k), str(v)) for k, v in entry.items() if k != "reason"}
    return {("", str(entry))}


def _list_problems(rule_id: str, key: str, template: object, product: object) -> list[str]:
    """One line per refused entry the drawer adds to one reachable list, naming it."""
    where = f"{RULES_DRAWER}: `{EXTENSIONS_KEY}: {{{rule_id}: {{{key}: …}}}}`"
    shape = f"the shape rule {rule_id}'s own `{key}` carries"
    again = f"which rule {rule_id}'s own `{key}` already carries — delete it from the drawer"
    if isinstance(template, Mapping):
        if not isinstance(product, Mapping) or not all(
            isinstance(v, list) and all(isinstance(m, str) for m in v) for v in product.values()
        ):
            return [f"{where} is not a mapping of names to lists of names — {shape}"]
        taken = {(str(a), str(m)) for a, mods in template.items() for m in mods or []}
        return [
            f"{where} adds `{a}: {m}`, {again}"
            for a, mods in product.items()
            for m in mods
            if (str(a), str(m)) in taken
        ]
    if not isinstance(product, list):
        return [f"{where} is a {type(product).__name__}, not a list — {shape}"]
    entries = list(template) if isinstance(template, list) else []
    bare = not any(isinstance(e, Mapping) for e in entries)
    taken_ids = [_identity(e) for e in entries]
    problems: list[str] = []
    for entry in product:
        if bare and not isinstance(entry, str):
            problems.append(f"{where} carries `{entry}`, which is no bare name — {shape}")
            continue
        reason = entry.get("reason") if isinstance(entry, Mapping) else None
        if not bare and (not isinstance(reason, str) or len(reason.strip()) < MIN_REASON):
            problems.append(
                f"{where} carries `{entry}` with no `reason:` of {MIN_REASON} characters or "
                f"more — every entry of rule {rule_id}'s `{key}` says why"
            )
            continue
        if any(_identity(entry) & ids for ids in taken_ids):
            problems.append(f"{where} adds `{entry}`, {again}")
    return problems


def extension_problems(
    extensions: object, template_rules: Iterable[Mapping[str, Any]]
) -> list[str]:
    """One line per refusal of a drawer's `scope_extensions:`, naming rule and entry."""
    if extensions is None:
        return []
    if not isinstance(extensions, Mapping):
        return [
            f"{RULES_DRAWER}: `{EXTENSIONS_KEY}:` is a {type(extensions).__name__}, not a mapping "
            "of template rule ids to scope lists"
        ]
    rules = {str(r.get("id")): r for r in template_rules}
    problems: list[str] = []
    for raw_id, lists in extensions.items():
        rule_id = str(raw_id)
        rule = rules.get(rule_id)
        if rule is None:
            problems.append(
                f"{RULES_DRAWER}: `{EXTENSIONS_KEY}:` names rule {rule_id}, which is no template "
                "rule — a drawer rule's own scope lives in its own declaration"
            )
            continue
        if not isinstance(lists, Mapping):
            problems.append(
                f"{RULES_DRAWER}: `{EXTENSIONS_KEY}: {{{rule_id}: …}}` is not a mapping of scope "
                "keys to entries"
            )
            continue
        reachable = product_reachable(rule)
        scope = rule.get("scope") or {}
        for raw_key, product in lists.items():
            key = str(raw_key)
            own = OWN_KEYS.get((rule_id, key))
            if own is not None:
                problems.append(
                    f"{RULES_DRAWER}: rule {rule_id}'s `{key}` has its own drawer key — declare "
                    f"the entries under `{own}:`, not under `{EXTENSIONS_KEY}:`"
                )
            elif key not in reachable:
                problems.append(
                    f"{RULES_DRAWER}: `{EXTENSIONS_KEY}:` adds {product!r} to rule {rule_id}'s "
                    f"`{key}`, which rule {rule_id} does not declare `{REACH_KEY}: {PRODUCT}` "
                    "on — that list is the template's alone"
                )
            else:
                problems.extend(_list_problems(rule_id, key, scope.get(key), product))
    return problems


def read_drawer(root: Path) -> dict[str, Any]:
    """The drawer's top level; absent is empty, unreadable is `ValueError`."""
    path = root / RULES_DRAWER
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{RULES_DRAWER} could not be read as YAML — {exc}") from exc
    return loaded if isinstance(loaded, dict) else {}


def extended_scope(root: Path, rule: Mapping[str, Any]) -> dict[str, Any]:
    """The rule's `scope:` with the drawer's entries joined on; `ValueError` names a refusal."""
    scope = dict(rule.get("scope") or {})
    extensions = read_drawer(root).get(EXTENSIONS_KEY)
    if extensions is None:
        return scope
    if not isinstance(extensions, Mapping):
        raise ValueError("; ".join(extension_problems(extensions, [rule])))
    rule_id = str(rule.get("id"))
    lists = next((v for k, v in extensions.items() if str(k) == rule_id), None)
    if lists is None:
        return scope
    problems = extension_problems({rule_id: lists}, [rule])
    if problems:
        raise ValueError("; ".join(problems))
    for key, product in lists.items():
        template = scope.get(str(key))
        if isinstance(template, Mapping):
            merged = {str(a): list(m or []) for a, m in template.items()}
            for app, mods in product.items():
                merged.setdefault(str(app), []).extend(mods)
            scope[str(key)] = merged
        else:
            scope[str(key)] = [*(template or []), *product]
    return scope
