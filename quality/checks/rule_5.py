"""Rule 5: list endpoints carry a query budget."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from quality.checks._hub import (
    CheckResult,
    _app_dirs,
    _app_is_pinned,
    _dotted_to_file,
    _parse,
    _read,
    api_modules,
)

# --- rule 5: list endpoints carry a query budget ------------------------------


def _has_paginate(tree: ast.Module) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Name) and target.id == "paginate":
                lines.append(node.lineno)
    return lines


def hot_path_registry(root: Path) -> list[dict]:
    rules = yaml.safe_load((root / "quality" / "rules.yaml").read_text())["rules"]
    for rule in rules:
        if str(rule["id"]) == "35":
            return list(rule.get("registry") or [])
    return []


def hot_path_counts(root: Path) -> dict[str, Any]:
    budgets_path = root / "quality" / "budgets.yaml"
    if not budgets_path.is_file():
        return {}
    budgets = yaml.safe_load(budgets_path.read_text()) or {}
    return dict(budgets.get("hot_path_query_counts") or {})


def _module_constant(root: Path, path_rel: str, name: str) -> Any:
    tree = _parse(root / path_rel)
    if tree is None:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return None
    return None


def _hierarchy_proposal_paths(root: Path) -> set[str]:
    """The keys of perf/measure_hierarchy.py::HOT_PATH_PROPOSALS — M1's
    machine-readable seam ("read them from the module, not retype them")."""
    tree = _parse(root / "perf" / "measure_hierarchy.py")
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "HOT_PATH_PROPOSALS":
                    if isinstance(node.value, ast.Dict):
                        return {
                            k.value
                            for k in node.value.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        }
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "HOT_PATH_PROPOSALS" and isinstance(node.value, ast.Dict):
                return {
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
    return set()


# : A spec hash is twelve hex characters (`perf/seed.py::spec_hash`). Used only
# : to say WHICH hash a doc is carrying when it carries the wrong one — the
# : verdict itself is membership of the computed hash, never this pattern.
SPEC_STAMP_RE = re.compile(r"\b[0-9a-f]{12}\b")


# : The envelope is not a measurement doc and cites nothing, so no registry entry
# : names it — and it is the file that states the spec for the whole product.
# : Named here rather than derived, with the reason.
SCALE_ENVELOPE = "docs/product/scale-envelope.md"


def _scale_spec_stamp(root: Path) -> str | None:
    """The hash `perf/seed.py::ScaleSpec` has right now, or None if unreadable.

    **`quality/` may import `perf/`; the reverse is the boundary.** The gate is
    allowed to read the harness's own contract — that is the whole mechanism
    here, a doc's claim compared against the artifact rather than against a
    number somebody retyped — and `perf/seed.py` is written to be importable
    before `django.setup()` precisely so that callers outside the harness can do
    it. Nothing in `perf/` imports `quality/`, and nothing should: the harness
    must not learn to satisfy the gate.

    `ScaleSpec()` is constructed here rather than reading `DEFAULT_SPEC`,
    because a spec whose FIELDS changed is the case this exists to catch and
    `DEFAULT_SPEC` is bound at the seeder's import.

    **Reloaded, not imported.** The gate runs every rule in one process and the
    self-test plants into the real tree between rules, so a cached `perf.seed`
    would make this check answer from the seeder as it was before the plant —
    a canary that cannot fire because the module it moves was already read.
    """
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        importlib.invalidate_caches()
        module = importlib.reload(importlib.import_module("perf.seed"))
    except Exception:  # noqa: BLE001 # any import failure is the same answer
        return None
    return str(module.spec_hash(module.ScaleSpec()))


def _stamp_findings(root: Path, registry: list[dict], out: CheckResult) -> None:
    """Every cited measurement doc, and the envelope, carries the current spec hash.

    A measurement doc's numbers describe ONE world. Until P3 F2 the docs said
    which — four of them carried `9959d8a1c073` — and nothing compared it to
    anything, so when `ScaleSpec` moved to `df07df482a95` every number in every
    doc went on citing a world that no longer existed, in silence, and the fifth
    doc carried no hash at all (done-line item 1). The stamp the
    seeder puts in the DATABASE is checked on every `perf.sh` run; the stamp in
    the PROSE was checked by nobody.

    Counts `stamp_candidates` (docs examined — the rule's floor, so a check
    that found nothing to stamp reads as UNBOUND rather than as a pass) and
    `stamped_docs` (docs that carry the current hash — the verdict, printed).
    """
    stamp = _scale_spec_stamp(root)
    if stamp is None:
        out.hit(
            "perf/seed.py",
            0,
            "perf/seed.py::ScaleSpec could not be imported, so no measurement doc's "
            "spec stamp can be compared with the spec — the seam is unenforced, not clean",
        )
        return
    docs = sorted(
        {
            str((entry.get("citation") or {}).get("doc", ""))
            for entry in registry
            if (entry.get("citation") or {}).get("doc")
        }
        | {SCALE_ENVELOPE}
    )
    for doc_rel in docs:
        doc_path = root / doc_rel
        if not doc_path.is_file():
            continue  # the citation half above already fires on a missing doc
        # The FLOOR rides on how many docs were examined, never on how many
        # passed: a stale stamp is a violation (exit 1) and an empty doc set is
        # broken enforcement (exit 2), and conflating the two would report a
        # `ScaleSpec` move as the gate being broken.
        out.count("stamp_candidates", 1)
        carried = sorted(set(SPEC_STAMP_RE.findall(doc_path.read_text())))
        if stamp in carried:
            out.count("stamped_docs", 1)
            continue
        out.hit(
            doc_rel,
            0,
            f"this doc's spec stamp is {', '.join(carried) if carried else 'MISSING'} and "
            f"perf/seed.py::ScaleSpec hashes to {stamp} — every number in it was measured "
            "against a world the fixture contract no longer declares, or against one it "
            "never named. Re-run the census and re-stamp, or say which spec the numbers "
            "are for",
        )


def query_budget_tests(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    # -- the app half: every paginated list route's app carries a pin ----------
    for app in _app_dirs(root):
        paginated: list[int] = []
        first_home: Path | None = None
        for api in api_modules(app):
            tree = _parse(api)
            if tree is None:
                continue
            found = _has_paginate(tree)
            if found and first_home is None:
                first_home = api
            paginated += found
        out.count("paginated_routes", len(paginated))
        if not paginated or first_home is None:
            continue
        if not _app_is_pinned(app):
            rel = str(first_home.relative_to(root))
            out.hit(
                rel,
                paginated[0],
                f"{app.name} has a paginated list route but no test pins its query count "
                "(assert_num_queries) — an N+1 here is a slow page, not a failure",
            )

    # -- the registry half (ADR gate-2): the declared hot paths ----------------
    registry = hot_path_registry(root)
    counts = hot_path_counts(root)
    out.count("hot_paths", len(registry))
    registered_paths = {str(entry.get("path", "")) for entry in registry}
    for entry in registry:
        dotted = str(entry.get("path", ""))
        where = _dotted_to_file(root, dotted)
        if dotted not in counts:
            out.hit(
                "quality/budgets.yaml",
                0,
                f"hot path {dotted} has no recorded count under hot_path_query_counts — "
                "a registered path with no measured number is vibes with teeth",
            )
        for spec, wanted in (entry.get("constants") or {}).items():
            const_file, _, const_name = str(spec).partition("::")
            measured = _module_constant(root, const_file, const_name)
            if measured != wanted:
                out.hit(
                    const_file,
                    0,
                    f"hot path {dotted}: {const_name} is {measured!r}, not the registered "
                    f"{wanted!r} — the ceiling the measurement doc pinned has moved without "
                    "the registry moving with it",
                )
        pin_test = entry.get("pin_test")
        if pin_test:
            pin_path = root / str(pin_test)
            if not pin_path.is_file() or "assert_num_queries" not in _read(pin_path):
                out.hit(
                    where,
                    0,
                    f"hot path {dotted} points at pin {pin_test}, which is missing or "
                    "carries no assert_num_queries — the gate-scale pin is gone",
                )
    # -- the stamp seam: a cited doc names the world it measured -----------------
    _stamp_findings(root, registry, out)

    for dotted in counts:
        if str(dotted) not in registered_paths:
            out.hit(
                "quality/budgets.yaml",
                0,
                f"hot_path_query_counts records {dotted}, which no registry entry declares — "
                "a count with no cited measurement behind it; register it "
                "with its citation in quality/rules.yaml, or remove the number",
            )
    for dotted in sorted(_hierarchy_proposal_paths(root)):
        if dotted not in registered_paths:
            out.hit(
                "perf/measure_hierarchy.py",
                0,
                f"HOT_PATH_PROPOSALS proposes {dotted} and the registry does not carry it — "
                "M1-2's seam: the module is the machine-readable proposal and the registry "
                "must consume it or record why not",
            )
    return out
