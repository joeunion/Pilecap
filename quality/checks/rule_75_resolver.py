"""Rule 75's resolver: the two declared populations, by class name."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _py_files
from quality.worlds import reaching

# --- rule 75's resolver: the two declared populations, by class name -------------
#
# `core.models.Archivable` sets `archivable = True`; `append_only = True` is
# rule 20's declaration. Both are INHERITED, so the population is resolved by
# class name to a fixed point over every `.py` under `apps/` — the same reading
# the registry's attribute lookup makes, without running anything. Rule 54's
# vocabulary census reads the archivable half too (an archivable kind derives
# `archive` and `restore`), and rule 76 will read the same resolver for its own
# marker; one resolver, so the three cannot come to disagree about who declared.


def declared_class_populations(
    root: Path,
) -> tuple[dict[str, list[tuple[str, int]]], set[str], set[str]]:
    """(definition sites by class name, append-only names, archivable names).

    Sites are `(relative path, line)` per definition — two modules defining one
    class name are read as the union of both, which can accuse a bystander (the
    loud direction, and the rule's valve is the answer) and never hides one.
    `Archivable` itself seeds the archivable population: it declares the marker
    and is its root.
    """
    sites: dict[str, list[tuple[str, int]]] = {}
    bases_of: dict[str, set[str]] = {}
    append_only: set[str] = set()
    archivable: set[str] = {_ARCHIVABLE_MIXIN}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name == "Meta":
                continue
            sites.setdefault(node.name, []).append((rel, node.lineno))
            bases_of.setdefault(node.name, set()).update(_base_names(node))
            if _class_attribute_is_true(node, _APPEND_ONLY_ATTR):
                append_only.add(node.name)
            if _class_attribute_is_true(node, _ARCHIVABLE_ATTR):
                archivable.add(node.name)
    append_only = reaching(bases_of, append_only)
    archivable = reaching(bases_of, archivable)
    return sites, append_only & sites.keys(), archivable & sites.keys()


def archivable_is_not_append_only(root: Path, rule: dict) -> CheckResult:
    """Rule 75. No model is both append-only and `Archivable` (D8).

    The static half of `core.models.Archivable.__init_subclass__`'s refusal:
    it reads the source and fires without running it. Both populations are
    derived from the tree by class name to a fixed point; nothing is listed.
    """
    out = CheckResult()
    sites, append_only, archivable = declared_class_populations(root)
    out.count("append_only_classes", len(append_only))
    out.count("archivable_classes", len(archivable))
    for name in sorted(append_only & archivable):
        for rel, line in sites.get(name, []):
            if _exempt(rule, rel):
                continue
            out.hit(
                rel,
                line,
                f"{name} is both append-only (`append_only = True`, itself or through a "
                "base) and `Archivable`. The two are disjoint (D8): an append-only row is "
                "a witnessed fact and archiving one hides it from every read — a rewrite "
                "by another name. Supersede a ledger row with a new one; archive a noun "
                "that owns no ledger promise. `core.models.Archivable` refuses the same "
                "shape at class definition; this is its static half.",
            )
    return out


from quality.checks.rule_16_the_rest_of_the_grammar import _base_names  # noqa: E402
from quality.checks.rule_20_enforceable_half import (  # noqa: E402
    _APPEND_ONLY_ATTR,
    _class_attribute_is_true,
)
from quality.checks.rules_81_and_82 import _ARCHIVABLE_ATTR, _ARCHIVABLE_MIXIN  # noqa: E402
