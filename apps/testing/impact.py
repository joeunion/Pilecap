"""The impact map's seam: an explicit selection, plus the always-on set."""

from __future__ import annotations

import pathlib

import pytest

# --- the impact map's seam: an explicit selection, plus the always-on set -----


def _read_impact_select(path: str) -> frozenset[str]:
    """The nodeids a caller named, one per line. Unreadable is COULD-NOT-LOOK."""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise pytest.UsageError(
            f"--djb-impact-select named {path}, which could not be read ({exc}). "
            "Nothing was selected and nothing was deselected: a selection file "
            "this cannot read would otherwise narrow the suite to the always-on "
            "set and report a green tree over it."
        ) from exc
    return frozenset(line.strip() for line in text.splitlines() if line.strip())


#: How many orphaned ids the line spells before it counts the rest.
DJB_IMPACT_ORPHANS_SHOWN = 10


def _impact_selection(
    nodeids: list[str], named: frozenset[str], always_on: frozenset[str]
) -> tuple[frozenset[str], str]:
    """(the nodeids to keep, the banner line). An orphan is NAMED, and its module runs whole.

    THE ORPHAN IS A STALE MAP, AND IT IS SAID — NEVER A CRASH. A map entry
    naming a test this collection does not hold is a test that was renamed,
    parametrized or deleted since the map was measured. This used to raise
    `UsageError` in every xdist worker: the loop exited 2 blaming whichever test
    a worker was on, and the sentence never reached the log. Now the line names
    the ids (`impact map: <n> ids no longer collected — <ids>`), and every
    collected test in an orphan's MODULE joins the selection — a renamed or
    newly parametrized test lives in the file its old id named, so the module is
    where it went. An orphan whose module is gone entirely selects nothing and
    is named all the same. The map itself is pruned by the fold's map step.
    """
    collected = frozenset(nodeids)
    orphans = sorted(named - collected)
    keep = (named | always_on) & collected
    line = f"impact-select: {len(named)} named, {len(keep - named)} always-on"
    if not orphans:
        return keep, line
    orphan_modules = {_module_of(nodeid) for nodeid in orphans}
    whole = frozenset(nodeid for nodeid in collected if _module_of(nodeid) in orphan_modules)
    live_modules = sorted({_module_of(nodeid) for nodeid in whole})
    shown = ", ".join(orphans[:DJB_IMPACT_ORPHANS_SHOWN])
    more = len(orphans) - DJB_IMPACT_ORPHANS_SHOWN
    if more > 0:
        shown += f" (+{more} more)"
    line = (
        f"impact map: {len(orphans)} ids no longer collected — {shown} · "
        + (
            f"{len(live_modules)} module(s) run whole in their place: {', '.join(live_modules)}"
            if live_modules
            else "no module of theirs is collected, so nothing runs in their place"
        )
        + f" · {line}"
    )
    return keep | whole, line


#: Per-module cross-TEST import verdicts, beside the reach ones. Keyed on the
#: module path alone: the labels asked about are fixed for the whole run, so a
#: second question with a different set cannot reach this cache.
_DJB_MODULE_TEST_IMPORTS: dict[str, frozenset[str]] = {}


def _is_app_tests_module(module: str) -> bool:
    """`apps/<x>/tests/…` -> True — the shell's tests-only row, asked of a module.

    The app-root `apps/<x>/conftest.py` is deliberately not this shape, for the
    reason `quality/djb/scope.py` gives: it is a fixture every module of `<x>`
    stands on.
    """
    parts = module.split("/")
    return len(parts) >= 4 and parts[0] == "apps" and parts[2] == "tests"


def _module_test_imports(path: str, labels: frozenset[str]) -> frozenset[str]:
    """The tests-only labels whose TEST PACKAGE this module's source names.

    THE COUPLING A TESTS-ONLY CHANGE CAN ACTUALLY BREAK. A change under
    `apps/<x>/tests/` cannot break another app's code, but it can break another
    app's TEST that imports `apps.x.tests.<something>` — a census helper, a
    shared fixture module. Derived by the same source-token technique as
    `_module_reach`, over the collected modules, so it is a closed question with
    no list to keep in step.

    The same tolerant-read failure mode as its neighbours, and the same answer:
    a module pytest has just imported and this cannot read is a refusal.
    """
    if not labels:
        return frozenset()
    cached = _DJB_MODULE_TEST_IMPORTS.get(path)
    if cached is not None:
        return cached
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to derive its cross-test imports "
            f"({exc}). An underived population is not an empty one: a tests-only "
            "narrowing that could not read a module would deselect it silently."
        ) from exc
    found = frozenset(label for label in labels if f"apps.{label}.tests" in source)
    _DJB_MODULE_TEST_IMPORTS[path] = found
    return found


def _population_members(path: str, nodeid: str) -> frozenset[str]:
    """The LAYER-2 populations this test module belongs to."""
    reach = _module_reach(path)
    module = _module_of(nodeid)
    members: set[str] = set()
    # `apps/test_*.py` — a test module at the apps root, owned by no app. No
    # scope can ever contain it, so it is always-on by construction; the floor
    # is what notices one of them being moved aside.
    parts = module.split("/")
    if len(parts) == 2 and parts[0] == "apps" and parts[1].startswith("test_"):
        members.add("apps_root_modules")
    if "door_parity" in reach:
        members.add("door_parity_census")
    if "absent_world" in reach:
        members.add("absent_world_consumers")
    if "introspect_registry" in reach:
        members.add("introspect_registry_readers")
    if module.endswith("tests/test_lifecycle.py"):
        members.add("lifecycle_registry_walkers")
    members |= _module_reach_populations(path)
    return frozenset(members)


def _collects_the_whole_tree(config: pytest.Config) -> bool:
    """Whether this collection is the TREE's population, so layer 2 can assert.

    True when every pytest argument is the `apps` test path, the repository
    root, or nothing (pytest then collects `testpaths`), AND the run is the
    ordinary world. A collection narrowed BY PATH — a drive collecting a
    fixture world, a hand run over one directory — holds some other
    population, and an absent-app world (`DJB_DISABLED_APPS`) withholds real
    members on purpose; asserting the tree's declarations over either would be
    measuring the wrong thing.
    """
    if _DJB_ABSENT_WORLD.report:
        return False
    root = DJB_REPO_ROOT
    whole = {root, root / "apps"}
    bases = {pathlib.Path(config.invocation_params.dir), pathlib.Path(config.rootpath)}
    for arg in config.args:
        spelled = pathlib.Path(str(arg).split("::", 1)[0])
        candidates = [spelled] if spelled.is_absolute() else [base / spelled for base in bases]
        if not any(candidate.resolve() in whole for candidate in candidates):
            return False
    return True


def _reach_and_populations(
    items: list[pytest.Item],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Every reach kind's modules and every named population's modules."""
    reached_kinds: dict[str, set[str]] = {}
    populations: dict[str, set[str]] = {}
    for item in items:
        path = str(getattr(item, "path", "") or "")
        module = _module_of(item.nodeid)
        for kind in _module_reach(path) if path else frozenset():
            reached_kinds.setdefault(kind, set()).add(module)
        for name in _population_members(path, item.nodeid):
            populations.setdefault(name, set()).add(module)
    return reached_kinds, populations


def _is_always_on(item: pytest.Item, reach: frozenset[str], changed: frozenset[str]) -> bool:
    """Whether this item runs whatever the scope is.

    THREE ways in, in the order they cost:

    1. STRUCTURAL. An item that belongs to NO app can never be inside any scope,
       so deselecting it would need a positive decision nobody has made.
    2. DERIVED. The registry-reach derivation above — a module that reads a
       whole Django population.
    3. DECLARED. The module carries the census marker (`_module_census_reason`),
       which is how a census that walks the SOURCE TREE by path says so: no
       registry token can see one, and the reverse half of
       `apps/test_census_markers.py` is what keeps the declaration honest.

    The order is not decoration: (1) and (2) are free by the time this is
    called, and (3) reads the module's first lines off disk (cached per module).

    `changed` is the caller's changed-file list (`--djb-changed`), and it can
    only ever subtract from (3): a DECLARED census that named a `population=`
    none of those files is inside has said, in its own line, that this change
    cannot have moved what it walks. An empty `changed` narrows nothing.
    """
    if _app_label(item.nodeid) is None or reach:
        return True
    path = str(getattr(item, "path", "") or "")
    if not path or not _module_census_reason(path):
        return False
    # (3) IS THE ONLY WAY IN A POPULATION MAY NARROW, and that is a decision
    # rather than an omission: (1) and (2) are about what a module READS through
    # a registry, and a registry is not a subtree anybody can name. Narrowing
    # them by path would be the hole the always-on set exists to close.
    return (
        _census_verdict(
            _module_of(item.nodeid),
            _census_population_or_refuse(path, DJB_REPO_ROOT),
            changed,
        )
        is None
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("djb", "Pilecap gate tiers")
    group.addoption(
        "--djb-tier",
        action="store",
        default="all",
        choices=("all", "fast"),
        help=(
            "all (default): every collected test, which is what the FULL gate runs. "
            "fast: deselect the derived organ-reaching tier, except in the apps named "
            "by --djb-own-app. Nothing is marked by hand; see apps/conftest.py."
        ),
    )
    group.addoption(
        "--djb-own-app",
        action="append",
        default=[],
        metavar="LABEL",
        help=(
            "an app label whose tests run IN FULL even under --djb-tier=fast. "
            "Repeatable. `--loop` derives these from the rung's changed files."
        ),
    )
    group.addoption(
        "--djb-scope-narrow",
        action="store_true",
        default=False,
        help=(
            "narrow the run to the apps named by --djb-scope, plus the DERIVED "
            "always-on cross-app set. Without this flag nothing is narrowed. "
            "`--loop` derives the scope in quality/djb/scope.py; no flag names an "
            "app INTO it."
        ),
    )
    group.addoption(
        "--djb-scope",
        action="append",
        default=[],
        metavar="LABEL",
        help=(
            "an app label inside the active rung's scope: it is NOT deselected under "
            "--djb-scope-narrow. Distinct from --djb-own-app, which is the stronger "
            "claim that an app runs IN FULL including its organ tests. The rung's "
            "TOUCHED apps are own-apps; the apps its depends_on closure pulled in are "
            "merely in scope, and promoting those too would make an apps/core touch "
            "run every organ test in the tree."
        ),
    )
    group.addoption(
        "--djb-tests-only",
        action="append",
        default=[],
        metavar="LABEL",
        help=(
            "an app whose ONLY changed files are under apps/<label>/tests/. Its test "
            "tree runs at the fast tier and it seeds NO closure — a test edit cannot "
            "break another app's code. Repeatable. `--loop` derives these in "
            "quality/djb/scope.py; no flag names an app INTO the closure."
        ),
    )
    group.addoption(
        "--djb-changed-test",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "a test module the rung actually edited, repo-relative. It runs whatever "
            "tier it is in — an organ-reaching module the rung CHANGED is the one "
            "organ test a per-rung gate has a reason to run. Repeatable."
        ),
    )
    group.addoption(
        "--djb-impact-select",
        action="store",
        default="",
        metavar="PATH",
        help=(
            "keep exactly the nodeids PATH names (one per line) plus the always-on "
            "cross-app set, and deselect everything else. A missing or unreadable "
            "file is a usage error. A nodeid this collection does not hold is a "
            "stale map entry: it is NAMED on the banner line and every collected "
            "test in its module runs in its place. The map "
            "is written by scripts/test_impact.py and read by quality/djb/scope.py; "
            "no flag names a test INTO the run."
        ),
    )
    group.addoption(
        "--djb-changed",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "a file the active rung changed, checkout-relative and repeatable. A "
            "DECLARED cross-app census that names a `population=` runs only when one "
            "of these is inside it; a census with no population, and every DERIVED "
            "always-on member, runs whatever this says. Without the flag nothing "
            "narrows — the --djb-scope-narrow rule, unchanged."
        ),
    )
    group.addoption(
        "--djb-scope-counts",
        action="store",
        default="",
        metavar="DIR",
        help=(
            "every collector writes its OWN counts file into DIR, named for its "
            "xdist worker. The caller RECONCILES them and never sums them: each "
            "worker performs its own full collection, so a sum multiplies by the "
            "worker count. What scripts/check.sh's scope banner reads."
        ),
    )
    group.addoption(
        "--djb-tier-manifest",
        action="store",
        default="",
        metavar="PATH",
        help=(
            "write the derived classification (one `<tier>\\t<organs>\\t<nodeid>` line "
            "per collected test) to PATH. What the census drive reads."
        ),
    )


from apps.testing.absent_world import _DJB_ABSENT_WORLD  # noqa: E402
from apps.testing.tier import (  # noqa: E402
    DJB_REPO_ROOT,
    _app_label,
    _census_population_or_refuse,
    _census_verdict,
    _module_census_reason,
    _module_of,
    _module_reach,
    _module_reach_populations,
)
