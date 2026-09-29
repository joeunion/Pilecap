"""Fixtures every app's tests share.

Tenancy is on, so a user without a membership sees nothing. Every fixture user
here therefore comes with the tenant it belongs to — except `nomad` and
`root`, which exist precisely to prove that a user without a membership reads
an empty table, superuser or not.

**The hierarchy is on too**, and these fixtures are the flat case of it:
`create_tenant` makes each tenant's root node, every membership here lands on
it, and every actor wears it as its hat. A depth-one tree behaves exactly as a
flat tenant did, which is the property that lets a product ignore the
hierarchy entirely — and the network-shaped fixtures live beside the tests
that need them (`apps/example/tests/test_network.py`), not here, because a tree
in the shared conftest would make every unrelated test pay for one.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import warnings
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple, TypeVar

import pytest
from asgiref.sync import AsyncToSync, SyncToAsync
from django.db import DEFAULT_DB_ALIAS, connections
from django.test import Client
from pytest_django import DjangoDbBlocker

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import context
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_tenant, root_organization
from apps.core.tests.isolation import registry_difference, registry_field_names
from apps.core.tests.tree_census import source_tree

PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


# --- the product's fixture drawer -------------------------------------------
#
# WHAT THIS IS FOR. This file is template-owned (`quality/partition.yaml`
# class C2): a product that edits it invalidates the platform partition, and
# the first consumer of this template added 609 lines of its own fixtures here
# because there was nowhere else to put a fixture every one of its apps needs.
# `apps/<x>/tests/conftest.py` is scoped by directory ancestry, so it cannot
# serve a product-wide fixture; the root conftest can, and it is mine.
#
# So: `apps/conftest_local.py` is the drawer. It is product-owned and it is
# DISCOVERED — the template never writes it and a product never edits this
# line. The template must never SHIP one either: the publication manifest's
# reserved-path rule is where that is enforced, and this exact path belongs
# on it.
#
# ABSENT IS BYTE-IDENTICAL: no module, no `pytest_plugins`, the collected set
# unchanged.
#
# PRESENT, IT MOVES THE PARTITION KEY, and that is honest rather than
# unfortunate. `pytest_plugins` loads the drawer for the WHOLE session, so an
# `autouse=True` fixture in it runs inside every PLATFORM test as well as the
# product's own — measured: a drawer autouse fixture errors
# `apps/core/tests/test_refusals.py`. A product's drawer can therefore change
# what the platform suite answers, so class C2 names this path as a member and
# a drawer invalidates a banked verdict exactly as an edit to THIS file does.
# The design's "never invalidates a banked verdict" could not be honoured
# honestly and is withdrawn.
#
# ON A NAME CLASH, THIS FILE WINS AND SAYS NOTHING. A conftest's own fixtures
# take precedence over a plugin's, so a drawer fixture sharing a name with one
# below is silently ignored — no warning, no error, the template's version
# used. Give a drawer fixture a name this file does not use.
#
# ONE KNOWN EDGE, since it is pytest's and not ours. `pytest_plugins` in a
# conftest that is not the ROOTDIR's is refused by pytest — but only when that
# conftest is loaded after configure, which happens when the rootdir itself is
# the argument (`pytest .`). Every way this tree is actually run makes
# `apps/conftest.py` an INITIAL conftest and is unaffected: a bare `pytest`
# (`testpaths = ["apps"]`), any `pytest apps/...`, `scripts/test.sh`, and both
# gate legs. A product that runs `pytest .` and has a drawer will see that
# refusal; it runs `pytest apps` instead.
#
# WHY `find_spec` AND NOT A BARE `try: import ... except ImportError: pass`.
# The two disagree exactly when the drawer is BROKEN. A try/except around the
# import cannot tell "there is no drawer" from "the drawer raised ImportError
# on line 40", so a product whose fixtures stopped loading would see every one
# of its tests fail with `fixture not found` and nothing naming the cause.
# `find_spec` answers only the question we are actually asking — does the
# module exist — and then pytest imports it, so a broken drawer is a LOUD
# ImportError (or SyntaxError) naming `apps/conftest_local.py`, never a silent
# absence. `find_spec` locates; it does not execute, and it does not compile.
if importlib.util.find_spec("apps.conftest_local") is not None:
    pytest_plugins = ["apps.conftest_local"]


# --- the absent-app world: the one subtraction a deployment may make ---------
#
# WHAT THIS IS FOR. `DJB_DISABLED_APPS=<label>` is the single subtraction
# `config/settings/discovery.py` invites a product to make, and until this the
# suite could not be COLLECTED once it was made: `DJB_DISABLED_APPS=example
# uv run pytest --collect-only` exited 2 with **23 collection errors** on the
# tree that shipped this, 15 of them outside `apps/example`, every one of them
# `RuntimeError: Model class apps.example.models.Widget doesn't declare an
# explicit app_label and isn't in an application in INSTALLED_APPS`. A
# configuration a product is invited to ship, in which nobody can run a single
# test, is a configuration nobody has checked.
#
# THE ABSENT-APP SUITE — one invocation, named, run before the flag is flipped:
#
#     DJB_DISABLED_APPS=example uv run pytest
#
# It is not a second suite and there is no second list: it is this suite, in a
# smaller world, with the modules that are ABOUT the absent app withheld.
#
# THE POPULATION IS DERIVED, NEVER TYPED — the same law as `INSTALLED_APPS` and
# as the tier below. A collected file is out of this run's world IFF it REACHES
# an absent app through its imports, read with `ast` off the files themselves:
#
#   * at module level -> the FILE is out of the world (that import runs at
#     collection time and is exactly what was exiting 2);
#   * inside a top-level `test_*` function -> that ONE TEST is out of the world,
#     and the rest of the module runs. `apps/core/tests/test_tenancy.py` is why
#     this half exists: one test imports the worked example inside its own body
#     and the other twenty-odd are about tenancy;
#   * anywhere else — a helper, a fixture, a method, a `TYPE_CHECKING` block —
#     the FILE is out of the world. A reference the derivation cannot attribute
#     to one test is not evidence that no test needs it, and guessing narrower
#     is how a world quietly runs a test that cannot hold.
#
# REACH IS TRANSITIVE, and this half was born red rather than reasoned: a
# derivation that read each file's own imports and stopped there left exactly
# ONE collection error standing, `apps/core/tests/test_database_unavailable.py`,
# which imports `apps.core.tests.test_refusal_wire`, which imports
# `apps.example.mcp`. So the module-level edges between every `.py` under
# `apps/` are read into a graph and closed over: a file needs an absent app if
# it names one, or if anything it imports at import time does. The declared
# blind spot that predicted this case was wrong by one module, on this tree, on
# the day it was written — which is why it is a fixpoint now and not a note.
#
# A `conftest.py` that names an absent app takes its whole DIRECTORY with it,
# because a directory whose fixtures cannot be imported has no collectable
# tests — three of them do today (`exports`, `search`, `usage`), and that is the
# largest loss this mechanism causes, which is why it is printed by name.
#
# IT IS PRINTED, ALWAYS. A world that silently withheld a third of the suite is
# a green nobody can read, so `pytest_report_header` names the absent apps, the
# withheld directories, the withheld modules per app and the withheld test
# count, on every run that removed anything. In the ordinary world — no flag,
# every dev run, both gate passes — this section reads no file and returns an
# empty list: it costs nothing to have.
#
# DECLARED BLIND SPOTS, one of them MEASURED rather than imagined. It reads
# imports, not use: a module that reaches an absent app through a hardcoded URL
# (`apps/core/tests/test_addressing_headers.py:75`, `LIST_URL =
# "/api/v1/widgets/"`), an `apps.get_model("example", ...)`, a fixture name or a
# settings key names nothing importable and is not seen. That class is real and
# large on this tree — the absent-app suite collects clean and still fails, in
# modules the derivation withheld nothing from — and it is deliberately left
# LOUD: each such failure is the absent app's real reach, and hiding it behind a
# string scan would turn a suite that names its couplings into a green that
# hides them. A function-level import inside a HELPER is attributed to the whole
# file rather than to the tests that call it, deliberately (above), so a module
# can be withheld more widely than it strictly needs. And the graph is static:
# an `importlib.import_module` or an `__import__` of an absent app is invisible
# to it. A RELATIVE import is not a blind spot: it is resolved against the
# importing file's package, as the import system resolves it.

#: The invocation, spelled once. Pinned by `apps/core/tests/test_optional_apps.py`
#: and repeated in `.env.example` beside the flag, which is the file an operator
#: reads before flipping it.
DJB_ABSENT_APP_SUITE = "DJB_DISABLED_APPS=example uv run pytest"

#: This file's directory — `apps/`, the root of every collected path.
_APPS_ROOT = pathlib.Path(__file__).resolve().parent


class AbsentWorld(NamedTuple):
    """What one run's absent apps take out of the collection, and the census.

    A value rather than three globals so the plan can be driven — and disagreed
    with — by a test: `apps/core/tests/test_optional_apps.py` calls the planner
    under both worlds, which is the only way the ordinary world's "this costs
    nothing" claim is falsifiable.
    """

    #: Paths pytest must not collect. Absolute, because pytest treats a
    #: `PathLike` entry in `collect_ignore` as already-absolute and only joins
    #: strings against the conftest's directory.
    ignore: list[pathlib.Path]
    #: (module path, top-level test name) -> the absent apps that test reaches.
    tests: dict[tuple[str, str], str]
    #: The header lines. Empty in the ordinary world.
    report: list[str]


def _disabled_app_labels() -> frozenset[str]:
    """The labels `DJB_DISABLED_APPS` names for THIS run.

    Parsed the way `config/settings/base.py` and `quality/worlds.py` parse it — a
    comma list, forgivingly — so the suite's idea of the world and the process's
    idea are the same world. Nothing is validated here: whether a label names an
    app, and whether that app allowed it, is `discover_apps`'s refusal to make
    while settings are read, and a second opinion about it here would be a second
    place to disagree.
    """
    raw = os.environ.get("DJB_DISABLED_APPS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _dotted(path: pathlib.Path) -> str:
    """`apps/core/tests/test_x.py` -> `apps.core.tests.test_x`; a package -> its dir."""
    relative = path.relative_to(_APPS_ROOT.parent)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(node: ast.AST, package: str = "") -> frozenset[str]:
    """Every module name one `import` statement could be naming.

    `from apps.core import context` names `apps.core` and may be reaching
    `apps.core.context` — a module or an attribute of a package, and which one
    it is cannot be told from the syntax. Both are returned; the caller resolves
    each against the tree and keeps what exists.

    **A relative import is resolved against `package`** — the dotted package
    the importing file lives in (`_dotted` of its directory, or of itself for an
    `__init__.py`) — exactly as the import system resolves it: `level` 1 is that
    package, each further level one parent up. Treating `from .helper import x`
    as naming nothing was the planner's silent narrowing: a test reaching an
    absent app through a sibling helper was collected and errored at import.
    A level that climbs above `apps` names nothing this tree can reach.
    """
    if isinstance(node, ast.Import):
        return frozenset(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return frozenset()
    if node.level:
        parts = package.split(".") if package else []
        if node.level > len(parts):
            return frozenset()
        base = ".".join(parts[: len(parts) - node.level + 1])
        module = f"{base}.{node.module}" if node.module else base
    elif node.module:
        module = node.module
    else:
        return frozenset()
    return frozenset([module, *(f"{module}.{alias.name}" for alias in node.names)])


def _absent_app_reach(
    path: pathlib.Path, absent: frozenset[str]
) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """(modules this FILE imports at import time, {test name: modules it imports}).

    Only `apps.*` names are kept — nothing outside this tree can reach an app —
    and the attribution rule for where an import sits is in the section header
    above. The failure mode this guards is a file that cannot be read or parsed,
    which must be loud: an underived population is not an empty one, and a file
    silently treated as naming nothing is a collection error waiting at the
    other end.
    """
    try:
        # `source_tree` is the tree's ONE tolerant read (see its module
        # docstring): a file another xdist worker plants and unlinks between
        # this walk's listing and its open is not a file this survey could not
        # look at — it is a file that is not there, and it holds no imports.
        # Measured here rather than reasoned: the R4 gate run refused on
        # `apps/zzz_vanisher_*.py`, the plant whose whole job is to cause this.
        # Anything else — a permission error, a decoding error, a file that
        # exists and does not parse — is still loud, below.
        tree = source_tree(path)
    except (OSError, SyntaxError) as exc:
        raise pytest.UsageError(
            f"the absent-app world could not read {path} to derive whether it "
            f"reaches one of the absent apps ({', '.join(sorted(absent))}): {exc}. "
            "Nothing was withheld and nothing was cleared — this refuses rather "
            "than collecting a world it did not survey."
        ) from exc

    def apps_only(names: frozenset[str]) -> frozenset[str]:
        return frozenset(name for name in names if name.split(".")[0] == "apps")

    # The package a relative import in this file resolves against.
    package = _dotted(path) if path.name == "__init__.py" else _dotted(path.parent / "__init__.py")

    at_import: set[str] = set()
    per_test: dict[str, frozenset[str]] = {}
    for statement in tree.body:
        own = apps_only(_imported_modules(statement, package))
        if own:
            at_import |= own
            continue
        nested = apps_only(
            frozenset().union(*(_imported_modules(node, package) for node in ast.walk(statement)))
        )
        if not nested:
            continue
        if isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and statement.name.startswith("test_"):
            per_test[statement.name] = nested
        else:
            at_import |= nested
    return frozenset(at_import), per_test


def _reaching_the_absent(
    absent: frozenset[str],
) -> tuple[dict[pathlib.Path, frozenset[str]], dict[pathlib.Path, dict[str, frozenset[str]]]]:
    """Close the module-level import graph under `apps/` over the absent apps.

    Returns, per file, the absent apps it CANNOT be imported without, and — for
    the files that can be imported — the absent apps each of its own `test_*`
    functions reaches. The fixpoint is why `test_database_unavailable.py` is
    seen: nothing in it names the worked example, and it cannot be imported
    without one.
    """
    files = sorted(_APPS_ROOT.rglob("*.py"))
    by_module = {_dotted(path): path for path in files}
    read = {
        path: _absent_app_reach(path, absent)
        for path in files
        if path.relative_to(_APPS_ROOT).parts[0] not in absent
    }

    def landing(module: str) -> frozenset[str]:
        """The absent app a module name lands in directly, if any."""
        parts = module.split(".")
        return frozenset({parts[1]}) if len(parts) >= 2 and parts[1] in absent else frozenset()

    needs: dict[pathlib.Path, frozenset[str]] = {
        path: frozenset().union(*(landing(module) for module in imports))
        for path, (imports, _tests) in read.items()
    }
    edges: dict[pathlib.Path, frozenset[pathlib.Path]] = {
        path: frozenset(
            by_module[module]
            for module in imports
            if module in by_module and by_module[module] in read
        )
        for path, (imports, _tests) in read.items()
    }
    moved = True
    while moved:
        moved = False
        for path, targets in edges.items():
            grown = needs[path].union(*(needs[target] for target in targets))
            if grown != needs[path]:
                needs[path] = grown
                moved = True

    per_file_tests: dict[pathlib.Path, dict[str, frozenset[str]]] = {}
    for path, (_imports, tests) in read.items():
        resolved: dict[str, frozenset[str]] = {}
        for name, imports in tests.items():
            reached = frozenset().union(
                *(
                    landing(module) | (needs.get(by_module.get(module, path), frozenset()))
                    for module in imports
                )
            )
            if reached:
                resolved[name] = reached
        if resolved:
            per_file_tests[path] = resolved
    return needs, per_file_tests


def _plan_the_absent_world() -> AbsentWorld:
    """What this run must not collect, and the census that says so out loud."""
    absent = _disabled_app_labels()
    if not absent:
        # The ordinary world, which is every dev run and both gate passes: no
        # file read, no census, no behaviour change at all.
        return AbsentWorld(ignore=[], tests={}, report=[])

    withheld: dict[tuple[str, str], str] = {}
    census: list[str] = []
    needs, per_file_tests = _reaching_the_absent(absent)
    ignore: list[pathlib.Path] = [_APPS_ROOT / label for label in sorted(absent)]
    gone_dirs: list[str] = [
        f"apps/{label} — the absent app's own tests" for label in sorted(absent)
    ]

    collected = sorted(
        path
        for path in needs
        if (path.name == "conftest.py" or path.name.startswith("test_"))
        and path != _APPS_ROOT / "conftest.py"
    )
    dead_dirs = {path.parent for path in collected if path.name == "conftest.py" and needs[path]}
    for directory in sorted(dead_dirs):
        ignore.append(directory)
        labels = ", ".join(sorted(needs[directory / "conftest.py"]))
        where = directory.relative_to(_APPS_ROOT.parent)
        gone_dirs.append(f"{where} — its conftest reaches {labels}")

    gone_modules: dict[str, list[str]] = {}
    withheld_tests = 0
    for path in collected:
        if path.parent in dead_dirs or any(one in path.parents for one in dead_dirs):
            continue
        if needs[path]:
            ignore.append(path)
            app = path.relative_to(_APPS_ROOT).parts[0]
            gone_modules.setdefault(f"apps/{app}", []).append(path.stem)
            continue
        for name, labels_reached in per_file_tests.get(path, {}).items():
            withheld[(str(path), name)] = ", ".join(sorted(labels_reached))
            withheld_tests += 1

    census.append(
        "djb world: ABSENT-APP — "
        + ", ".join(sorted(absent))
        + " not installed (DJB_DISABLED_APPS). Everything that reaches an absent "
        f"app is withheld from collection; everything else runs — {DJB_ABSENT_APP_SUITE}"
    )
    for line in gone_dirs:
        census.append(f"  directory withheld: {line}")
    for app in sorted(gone_modules):
        census.append(f"  modules withheld in {app}: " + ", ".join(sorted(gone_modules[app])))
    census.append(
        f"  individual tests withheld: {withheld_tests} (they reach an absent app "
        "from inside their own body; their modules run)."
    )
    return AbsentWorld(ignore=ignore, tests=withheld, report=census)


_DJB_ABSENT_WORLD = _plan_the_absent_world()

#: Consulted by pytest's own `pytest_ignore_collect` for every path under
#: `apps/`, resolved against THIS file's directory.
collect_ignore: list[pathlib.Path] = _DJB_ABSENT_WORLD.ignore

#: Applied as a skip in `pytest_collection_modifyitems`; printed by
#: `pytest_report_header`. Both empty in the ordinary world.
_DJB_ABSENT_TESTS: dict[tuple[str, str], str] = _DJB_ABSENT_WORLD.tests
_DJB_ABSENT_REPORT: list[str] = _DJB_ABSENT_WORLD.report


def _withhold_the_absent_world(items: list[pytest.Item]) -> None:
    """Skip the individual tests that reach an app this world does not hold.

    A skip with the app named, not a silent deselection: a reader of the absent
    world's green has to be able to see which tests it does not cover.
    """
    if not _DJB_ABSENT_TESTS:
        return
    for item in items:
        name = getattr(item, "originalname", None) or item.name.split("[")[0]
        labels = _DJB_ABSENT_TESTS.get((str(getattr(item, "path", "")), str(name)))
        if labels is not None:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"this test reaches {labels}, which DJB_DISABLED_APPS left "
                        "out of this deployment; the rest of its module runs"
                    )
                )
            )


# --- the `--loop` tier: a slow tier DERIVED, never a hand-marked list --------
#
# WHAT THIS IS FOR. The per-rung gate runs one pytest pass over the whole suite;
# the full gate at push runs two. A builder pays the whole suite on every
# iteration, and the measurement behind this tier says where that time
# actually goes: the tests that talk to a REAL ORGAN — the compose MinIO, a real
# time-skipping Temporal server, the compose Meilisearch — are a minority of the
# suite and a plurality of its wall clock. `--loop` skips them; **the full gate
# runs everything, unchanged**, so nothing is dropped, only deferred from
# loop-time to push-time. That trade is a declared blind spot, and is the
# point of the tier, not a side effect of it.
#
# THE POPULATION IS DERIVED, NEVER TYPED. A hand-marked list of slow tests is
# the drift class the whole rules engine exists against: it is right on the day
# it is written and wrong on the day somebody adds a test. So a test is in the
# slow tier IFF it REACHES an organ, and reach is computed two ways because this
# tree opts into its organs two ways:
#
#   1. BY FIXTURE CLOSURE. A fixture that hands a test a real organ declares
#      itself with `@organ("<kind>")` (`apps/files/tests/conftest.py::bucket`,
#      `apps/exports/tests/conftest.py::archive_bucket`,
#      `apps/search/tests/conftest.py::live_label`). A test reaches the organ if
#      that fixture is anywhere in its closure — `name2fixturedefs` is the
#      CLOSURE, so a fixture that requests `bucket` three levels down is caught
#      without anybody saying so.
#
#   2. BY MODULE SOURCE, for Temporal ONLY, and this is a finding rather than a
#      preference. There is NO Temporal organ fixture in this tree to reach:
#      `_no_dialling_temporal` below refuses the client factory for every test,
#      and a test that genuinely needs a server starts its own
#      `WorkflowEnvironment.start_time_skipping()` INSIDE ITS OWN BODY and
#      monkeypatches the factory at it (see that fixture's docstring). The opt-in
#      is a call site, not a fixture, in 21 modules across nine apps — two of
#      them importing it inside the test function rather than at module scope. So
#      the derivation reads the module's own source for the entry point's name.
#      It is still derived from the tree and still needs no list; it is coarser
#      (a whole module joins, not one test) and it over-includes a module that
#      merely NAMES the symbol, which errs toward running more in `--loop`.
#
# THE FLOORS ARE THE CANARY. Every failure mode of a derivation like this one is
# silent: a private pytest attribute renamed, a decorator dropped in a merge, a
# module read that started failing — each leaves a tier that deselects nothing
# or, worse, everything, and a green `--loop` that vouches for less than it says.
# So the derivation asserts a floor per organ kind before it deselects a single
# test, and an unmet floor is a hard refusal, never a quiet pass. An underived
# population is not an empty one — the same doctrine `secrets_scan.sh` states for
# the same reason.

#: The attribute `@organ(...)` leaves on a fixture function. Read off
#: `FixtureDef.func`, so it survives `@pytest.fixture` in either decorator order.
DJB_ORGAN_ATTRIBUTE = "__djb_organ__"

#: The organ with no fixture to reach — see (2) above.
DJB_TEMPORAL_ORGAN = "temporal"

#: The one call that starts a real time-skipping Temporal server. A test module
#: that names it is treated as reaching Temporal.
DJB_TEMPORAL_ENTRY_POINT = "WorkflowEnvironment"

#: The declared floor per organ kind: how many collected tests must be derived
#: as reaching it before this tier is allowed to deselect anything. One each,
#: deliberately — a floor tuned to today's count would redden on the next
#: legitimate deletion, and what has to be caught is a derivation that stopped
#: seeing the KIND at all.
DJB_ORGAN_FLOORS: dict[str, int] = {"minio": 1, "meili": 1, DJB_TEMPORAL_ORGAN: 1}

# --- the ALWAYS-ON set: cross-app tripwires, derived ------------------------
#
# WHAT THIS IS FOR. `scripts/loop_tier.sh` derives a SCOPE — the apps the active rung
# changed, plus the reverse-transitive `depends_on` closure over them — and
# `--loop` deselects everything outside it. That narrowing is sound for a test
# that lives inside one app and reads one app. It is NOT sound for a test that
# quantifies over the whole tree: a census that walks `get_app_configs()` and
# asserts something of every app is broken by a change in ANY app, including one
# no scope will ever contain. Deselecting those is how a scope stops being a
# narrowing and starts being a hole.
#
# So a module that READS A WHOLE POPULATION runs unconditionally, whatever the
# scope is. The population is DERIVED by the same source-reach technique the
# organ tier above already uses (`_module_organs`), for the same reason: a
# hand-marked list of cross-app tests is right on the day it is written and
# wrong on the day somebody adds a census.
#
# TWO PREDICATES WERE REJECTED and are recorded here so nobody re-tries them:
#
#   * "a module that imports two or more apps" — that is IMPORT TOPOLOGY, not
#     population reach. Half the suite imports `apps.core` beside its own app
#     and reaches no population at all; the predicate would make the always-on
#     set most of the tree and the scope worth nothing.
#   * "a module that imports `config.api`" — the same class, one hop narrower.
#     Reaching the router registry is not reaching the app registry, and the
#     modules it catches are mostly ordinary door tests that a scope already
#     covers through their own app.
#
# THE FLOORS COME IN TWO LAYERS, and the second layer is the point.
#
#   LAYER 1, per REACH KIND: at least one module must derive as reaching each
#   kind. This catches the whole derivation going blind — a renamed token, a
#   source read that started failing.
#
#   LAYER 2, per NAMED POPULATION: each named population must still hold the
#   number of members this tree has. Layer 1 alone is satisfied by EITHER of two
#   populations that share a reach kind, so either one can empty completely
#   while the floor stays green — a masking gap inside the floors themselves,
#   which is the one place nobody re-reads. Measured on this tree: five modules
#   derive `app_registry` reach and nine derive `model_registry`, and the
#   `lifecycle_registry_walkers` population is a subset of both — so
#   `app_registry >= 1` would survive the total disappearance of every lifecycle
#   walker. Naming the population and its count is what makes emptying one
#   member a floor failure rather than an arithmetic coincidence.
#
# WHAT A LAYER-2 FLOOR IS NOT: an identity check. It counts members; it cannot
# see a census gutted in place. The full gate's canary self-test and review are
# the cover for that, and no instrument here pretends otherwise.
#
# THE FLOORS ASSERT BEFORE ANYTHING IS DESELECTED. An unmet floor is a
# `pytest.UsageError`, which pytest reports as exit 4 and `scripts/check.sh`
# maps to exit 2; raised inside an xdist worker during collection it surfaces as
# INTERNALERROR and exit 3, which that same mapping treats identically. An
# underived population is not an empty one.
#
# THE SENTINEL BLOCK BELOW IS READ BY `scripts/loop_tier.sh`. It digests exactly
# these bytes into the loop ledger's key, so changing which tests are
# unconditional invalidates every banked `--loop` verdict rather than silently
# letting one vouch for a selection it never saw. Moving a declaration out of
# the block is therefore not a refactor — it is a verdict that stops being keyed
# on its own rules.

# >>> always-on-derivation >>>
#: Reach kind -> the source tokens that mean "this module reads that whole
#: population". Tokens, not imports: some readers reach the registry inside a
#: test body rather than at module scope, exactly as the Temporal organ
#: derivation above found.
DJB_REACH_TOKENS: dict[str, tuple[str, ...]] = {
    "app_registry": ("get_app_configs",),
    "model_registry": ("get_models(",),
    "introspect_registry": ("management.commands.introspect",),
    "absent_world": ("DJB_DISABLED_APPS",),
    "door_parity": ("DOOR_PAIR",),
    # THE DOOR REGISTRY: the two documents every door publishes, rendered
    # whole. `get_openapi_schema(` is the REST door's document over EVERY
    # mounted router — the call, not a receiver name, because the walkers spell
    # the receiver five ways (`api`, `the_api`, `ninja_api`, `mounted`,
    # `contract`) and no narrower token catches every one of them. `_list_tools(`
    # is the MCP door's whole catalogue as a test reads it: the helper that
    # returns every tool's published `outputSchema`. The bare wire method
    # `tools/list` was measured and rejected — the modules that spell it are
    # auth and throttle probes that ask for the list and read none of it. A
    # module that reads either document reads a route or a tool that ANY app
    # can add, rename or reshape, so a change in an app no scope pairs with it
    # can move its answer. Derived from what
    # `apps/core/tests/test_door_schema_parity.py` actually reads (both
    # documents, compared), never from a list of modules. The import of
    # `config.api` stays rejected (above): importing the router is not reading
    # the document it renders.
    "door_registry": ("get_openapi_schema(", "_list_tools("),
}

#: LAYER 1. One each, deliberately: what has to be caught here is a derivation
#: that stopped seeing the KIND at all. A kind a product declares in its drawer
#: (`DJB_REACH_KINDS`, below) is floored at one the same way, by
#: `_reach_floors`: a declared kind nothing reads is a token with a typo in it.
DJB_REACH_FLOORS: dict[str, int] = {kind: 1 for kind in DJB_REACH_TOKENS}

#: The populations INSIDE a reach kind whose tokens name two different
#: documents. Layer 1 over `door_registry` is satisfied by either half, so
#: either half could empty while it stayed green — the masking gap the LAYER 2
#: comment below names. Each token set here is one named population.
DJB_REACH_POPULATIONS: dict[str, tuple[str, ...]] = {
    "openapi_document_readers": ("get_openapi_schema(",),
    "mcp_catalogue_readers": ("_list_tools(",),
}

#: LAYER 2. Named populations and the number of MODULES this tree holds for
#: each — every one of these integers was DERIVED by collecting this suite,
#: never chosen — and the floor is an EQUALITY: a population BELOW its number
#: lost a member (a deletion, or a derivation going blind), and a population
#: ABOVE it gained one no declaration names. Both refuse, naming the members.
#: A legitimate deletion or addition reddens them and that is the trade: the
#: alternative is a floor that cannot tell a deletion from a derivation going
#: blind, and — the one-sided `<` this replaced — a floor that stays green while
#: its population grows past it, so the NEXT member moved aside is invisible.
#: Measured: four populations sat above their floors with no red, and
#: `apps_root_modules` went 3 → 4 → 5 → 6 with every join found later by a
#: drive's moved-aside case, never at the commit that joined.
#:
#: THE DERIVATION IS A COMMAND, NOT A WORD — pasted here because "derived" was
#: once true of four of these and false of the fifth for long enough that a
#: reader had no way to tell which. It counts MODULES over the WHOLE collection:
#: the populations are built in `pytest_collection_modifyitems` below BEFORE
#: anything is deselected, so the scope a run was asked for does not move these
#: numbers. Two of the seven are a path shape and five are tokens declared above
#: (`DJB_REACH_TOKENS`, `DJB_REACH_POPULATIONS`), matched as FIXED strings — in
#: prose as well as code: a docstring that spells a token makes its module a
#: member, which is declared here rather than decided (an unescaped `.` in the
#: introspect token also matches `management/commands/introspect.py` and reads
#: one more):
#:
#:   uv run pytest --collect-only -q | sed -n 's/::.*//p' | sort -u > /tmp/m
#:   grep -c '^apps/test_[^/]*\.py$'      /tmp/m                      # apps_root_modules
#:   xargs grep -lF 'DOOR_PAIR'         < /tmp/m | wc -l              # door_parity_census
#:   xargs grep -lF 'DJB_DISABLED_APPS' < /tmp/m | wc -l              # absent_world_consumers
#:   xargs grep -lF 'management.commands.introspect' < /tmp/m | wc -l # introspect_registry_readers
#:   grep -c 'tests/test_lifecycle\.py$'  /tmp/m                      # lifecycle_registry_walkers
#:   xargs grep -lF 'get_openapi_schema(' < /tmp/m | wc -l            # openapi_document_readers
#:   xargs grep -lF '_list_tools('     < /tmp/m | wc -l              # mcp_catalogue_readers
#:
#: RUN 2026-09-28 on a verifier box (aarch64 Linux), tree
#: b81706ae09bb0bc33e07650bb0cc62aeeaa57348, N = 4824 items collected over 328
#: modules → 6 · 17 · 4 · 7 · 9 · 20 · 2.
#: ALL SEVEN NUMBERS BELOW ARE THAT RUN. The joiners since the 2026-09-27 run
#: (tree 88f17ef8: 5 · 14 · 3 · 7 · 8 · 18 · 2), each named with the change
#: that added it, because a number re-derived without its member is the shape
#: this paragraph exists to end:
#:
#:   door_parity_census 14 → 17: apps/djb_imports/tests/test_doors_over_the_wire.py
#:     (the imports app), apps/djb_notes/tests/test_doors_over_the_wire.py (the
#:     notes app), apps/djb_tags/tests/test_doors_over_the_wire.py (the tags app).
#:   absent_world_consumers 3 → 4: apps/core/tests/test_resource_first_urls.py —
#:     joined by a DOCSTRING sentence carrying the fixed-string token, not by a
#:     reader of the absent world; counted, as the property above says.
#:   lifecycle_registry_walkers 8 → 9: apps/djb_imports/tests/test_lifecycle.py.
#:   openapi_document_readers 18 → 20: apps/files/tests/test_archive_road.py,
#:     apps/djb_imports/tests/test_api.py.
#:   apps_root_modules 5 → 6: apps/test_absent_relative_imports.py — the fourth
#:     re-derivation of this one population (3 → 4 test_census_markers.py,
#:     4 → 5 test_retry_floor.py), and the reason it is now declared BY MEMBER.
#:   introspect_registry_readers (7) and mcp_catalogue_readers (2): unchanged.
#:   openapi_document_readers 20 → 21 (after that run, by the change that made
#:     a family refusal's published remedy the one the wire sends):
#:     apps/core/tests/test_remedies_published_equal_wire.py.
#:
#: **A rung that adds or removes a member of any population here changes its
#: declaration in the same commit, and names the member in this paragraph** (a
#: product: its drawer, below); the equality refuses the commit that forgot.
#:
#: WHERE IT IS ASSERTED, and where it is not. Over a collection of the WHOLE
#: tree — every run whose pytest arguments are the `apps` test path or none —
#: whichever branch below that run takes. A collection narrowed BY PATH (a
#: drive collecting a fixture world, a hand run over one directory) is not the
#: tree's population, so layer 2 asserts nothing there; layer 1 still does.
DJB_POPULATION_FLOOR_MEMBERS: dict[str, tuple[str, ...]] = {
    # CLOSED BY A PATH SHAPE (`apps/test_*.py`), so its members can be named and
    # a refusal can say WHICH one joined or left. The six token populations are
    # open — a fixed-string match over the collection — and keep integers: a
    # hand list of a population that is found rather than declared is the list
    # that goes stale first.
    "apps_root_modules": (
        "apps/test_absent_relative_imports.py",
        "apps/test_absent_world.py",
        "apps/test_census_markers.py",
        "apps/test_gate_liveness.py",
        "apps/test_retry_floor.py",
        "apps/test_temporal_guard.py",
    ),
}
DJB_POPULATION_FLOORS: dict[str, int] = {
    "apps_root_modules": len(DJB_POPULATION_FLOOR_MEMBERS["apps_root_modules"]),
    "door_parity_census": 17,
    "absent_world_consumers": 4,
    "introspect_registry_readers": 7,
    "lifecycle_registry_walkers": 9,
    "openapi_document_readers": 21,
    "mcp_catalogue_readers": 2,
}

# THE DRAWER DECLARES A PRODUCT'S MEMBERS; IT NEVER EDITS THE TEMPLATE'S. The
# declarations above are the TEMPLATE's populations and a product cannot change
# them: this file is template-owned and a fold overwrites it. A product with a
# seventh apps-root module declares it in its fixtures drawer, by NAME for a
# population the template declares by member and by COUNT for the others:
#
#     # apps/conftest_local.py
#     DJB_POPULATION_FLOOR_MEMBERS = {"apps_root_modules": ("apps/test_acme.py",)}
#     DJB_POPULATION_FLOOR_ADDENDS = {"door_parity_census": 2}
#
# The members asserted are the template's UNION the drawer's; the number
# asserted is that union's size plus any addend. It is the
# `DRAWER_RATCHET_PARTS` shape in `quality/gate.py`: the two halves are kept
# apart so the refusal can say which number lives in which file, because a
# reader told "floor 7" looks for a 7 written in neither. An addend on a
# member-declared population is still legal — it is how a drawer written
# before members existed keeps working — and it counts members the refusal
# then cannot name, which is why a member list is the better declaration.
#
# ONE READER, `_population_floors`, and nothing else reads either declaration.
# `test_loop_scope.sh` plants drawer rows and proves the refusal names the
# drawer's half — a declaration no reader reads would otherwise be a comment.
#
# RAISES ONLY. An addend is a non-negative integer and a member is a path, for
# a population the template declares; a negative addend would let a drawer
# silence the canary the floor is, and a name the template does not declare is
# a typo that would otherwise raise nothing. Each is a refusal naming the
# drawer, never a silent skip. A declared member path the tree lacks is refused
# at the floor, naming the file.
DJB_POPULATION_FLOOR_DRAWER = "apps/conftest_local.py"

#: The remedy every layer-2 refusal prints, in one place.
DJB_POPULATION_FLOOR_REMEDY = (
    "Raise the declaration and its paragraph in the same commit (lower them for a "
    "member that left), naming the member, in apps/conftest.py; a product: "
    f"DJB_POPULATION_FLOOR_MEMBERS / DJB_POPULATION_FLOOR_ADDENDS in {DJB_POPULATION_FLOOR_DRAWER}."
)


class PopulationFloor(NamedTuple):
    """One named population's declaration, as `_population_floors` read it."""

    template: int
    addend: int
    members: frozenset[str] | None


def _population_floors() -> dict[str, PopulationFloor]:
    """Each named population's declaration: the template's half and the drawer's.

    The ONE reader of `DJB_POPULATION_FLOOR_ADDENDS` and
    `DJB_POPULATION_FLOOR_MEMBERS` in the fixtures drawer. `addend` is the
    drawer's whole half — its extra members plus its addend — so the number
    asserted is always `template + addend`; `members` is the declared member
    set (template's union drawer's) for a population declared by member, and
    `None` for one declared by count. No drawer is the template's floors,
    unchanged.
    """
    template_members = {
        name: frozenset(paths) for name, paths in DJB_POPULATION_FLOOR_MEMBERS.items()
    }
    extra: dict[str, frozenset[str]] = {}
    addends: dict[str, int] = {}
    drawer = _fixtures_drawer()
    declared = getattr(drawer, "DJB_POPULATION_FLOOR_ADDENDS", None) if drawer else None
    if declared is not None:
        where = f"{DJB_POPULATION_FLOOR_DRAWER}'s DJB_POPULATION_FLOOR_ADDENDS"
        if not isinstance(declared, dict):
            raise pytest.UsageError(
                f"{where} is a {type(declared).__name__}, not a dict of population name to addend."
            )
        for name, addend in declared.items():
            if name not in DJB_POPULATION_FLOORS:
                raise pytest.UsageError(
                    f"{where} names {name!r}, which is not a population apps/conftest.py "
                    f"declares ({', '.join(sorted(DJB_POPULATION_FLOORS))}) — an addend for "
                    "no population raises nothing, so it is refused rather than ignored."
                )
            if isinstance(addend, bool) or not isinstance(addend, int) or addend < 0:
                raise pytest.UsageError(
                    f"{where}[{name!r}] is {addend!r} — an addend is a non-negative integer: "
                    "a drawer raises a floor by its own members and never lowers the template's."
                )
            addends[name] = addend
    named = getattr(drawer, "DJB_POPULATION_FLOOR_MEMBERS", None) if drawer else None
    if named is not None:
        where = f"{DJB_POPULATION_FLOOR_DRAWER}'s DJB_POPULATION_FLOOR_MEMBERS"
        if not isinstance(named, dict):
            raise pytest.UsageError(
                f"{where} is a {type(named).__name__}, not a dict of population name to paths."
            )
        for name, paths in named.items():
            if name not in template_members:
                raise pytest.UsageError(
                    f"{where} names {name!r}, which apps/conftest.py does not declare by "
                    f"member ({', '.join(sorted(template_members))}); a population "
                    "declared by count takes DJB_POPULATION_FLOOR_ADDENDS."
                )
            if not isinstance(paths, (tuple, list)) or not all(
                isinstance(path, str) and path.startswith("apps/") for path in paths
            ):
                raise pytest.UsageError(
                    f"{where}[{name!r}] is {paths!r} — members are a tuple of repo-relative "
                    "paths under apps/."
                )
            extra[name] = frozenset(paths) - template_members[name]
    floors: dict[str, PopulationFloor] = {}
    for name, number in DJB_POPULATION_FLOORS.items():
        mine = extra.get(name, frozenset())
        members = template_members[name] | mine if name in template_members else None
        floors[name] = PopulationFloor(number, len(mine) + addends.get(name, 0), members)
    return floors


def _population_floor_text(name: str, floor: PopulationFloor, derived: set[str]) -> str | None:
    """One population's refusal, or `None` when it holds its declaration exactly.

    Says the declared number, which half of it lives in which file, the
    derived count, and — the part an integer could never say — WHICH members:
    every derived member by path when the population is above its number, and
    for a population declared by member, the undeclared ones that joined and
    the declared ones that left (naming a file the tree lacks as such).
    """
    template, addend, members = floor
    total = template + addend
    missing = sorted(members - derived) if members is not None else []
    if len(derived) == total and not missing:
        return None
    if not addend:
        head = f"{name} (floor {total} in apps/conftest.py, derived {len(derived)} module(s))"
    else:
        head = (
            f"{name} (floor {total} = {template} in apps/conftest.py + {addend} in "
            f"{DJB_POPULATION_FLOOR_DRAWER}, derived {len(derived)} module(s))"
        )
    notes: list[str] = []
    if len(derived) > total:
        notes.append(
            f"ABOVE its declaration — the derived members are {', '.join(sorted(derived))}"
        )
    if members is not None:
        joined = sorted(derived - members)
        if joined and len(derived) != total:
            notes.append(f"not declared: {', '.join(joined)}")
    for path in missing:
        present = (DJB_REPO_ROOT / path).exists()
        notes.append(
            f"declared but not collected: {path}"
            + ("" if present else " (the tree has no such file)")
        )
    return head + ("" if not notes else " — " + "; ".join(notes))


# THE DRAWER DECLARES A REACH KIND; IT NEVER EDITS ONE. `DJB_REACH_TOKENS`
# above is the TEMPLATE's registries, and a product's own registry reader —
# a census over something the product registers, spelled with a call the
# template has never heard of — was always-on only if somebody edited this
# template-owned file, which the next fold overwrites. So the product declares
# the kind in its fixtures drawer, in the template's own shape:
#
#     # apps/conftest_local.py
#     DJB_REACH_KINDS = {"acme_registry": ("list_widgets(",)}
#
# and a module whose source carries `list_widgets(` is always-on, printed in
# the banner as `derived: acme_registry`, and floored at one like every kind:
# a declared kind nothing reads is a token with a typo in it.
#
# ONE READER, `_reach_tokens`. ADDS ONLY: a drawer kind that reuses a template
# kind's name is refused naming both files, because it would silently replace
# the template's tokens rather than add to them.
#
# AND THE DRAWER'S KEYS ARE A CLOSED SET. Every module-level name in the drawer
# spelled `DJB_*` is a declaration to one of the readers in this file, and a
# name no reader reads is a typo that would otherwise declare nothing, which
# reads exactly like a product with nothing to declare. So `_fixtures_drawer`
# refuses one, naming it, before any reader looks. Fixtures and helpers in the
# drawer are not `DJB_*` and are untouched by this.
DJB_REACH_KINDS_KEY = "DJB_REACH_KINDS"

#: Every `DJB_*` name the drawer may declare, and the one reader of each.
DJB_DRAWER_KEYS: dict[str, str] = {
    "DJB_POPULATION_FLOOR_ADDENDS": "_population_floors",
    "DJB_POPULATION_FLOOR_MEMBERS": "_population_floors",
    DJB_REACH_KINDS_KEY: "_reach_tokens",
}


def _drawer_unknown_keys(drawer: Any) -> list[str]:
    """The `DJB_*` names a drawer declares that no reader in this file reads."""
    return sorted(
        name for name in vars(drawer) if name.startswith("DJB_") and name not in DJB_DRAWER_KEYS
    )


def _fixtures_drawer() -> Any | None:
    """The fixtures drawer module, or `None` when the product has none.

    The ONE place the drawer is opened for a declaration, so the closed-key
    refusal cannot be skipped by whichever reader happens to run first.
    """
    if importlib.util.find_spec("apps.conftest_local") is None:
        return None
    drawer = importlib.import_module("apps.conftest_local")
    unknown = _drawer_unknown_keys(drawer)
    if unknown:
        raise pytest.UsageError(
            f"{DJB_POPULATION_FLOOR_DRAWER} declares {', '.join(unknown)}, which no "
            f"reader in apps/conftest.py reads (the drawer's keys: "
            f"{', '.join(sorted(DJB_DRAWER_KEYS))}). A declaration nobody reads "
            "declares nothing and reads exactly like a drawer with nothing to "
            "declare, so it is refused rather than ignored."
        )
    return drawer


def _drawer_reach_kinds(drawer: Any | None) -> dict[str, tuple[str, ...]]:
    """The reach kinds a drawer declares, validated; `{}` when it declares none."""
    if drawer is None:
        return {}
    declared = getattr(drawer, DJB_REACH_KINDS_KEY, None)
    if declared is None:
        return {}
    where = f"{DJB_POPULATION_FLOOR_DRAWER}'s {DJB_REACH_KINDS_KEY}"
    if not isinstance(declared, dict):
        raise pytest.UsageError(
            f"{where} is a {type(declared).__name__}, not a dict of reach kind to source tokens."
        )
    kinds: dict[str, tuple[str, ...]] = {}
    for kind, tokens in declared.items():
        if not isinstance(kind, str) or not kind:
            raise pytest.UsageError(f"{where} names {kind!r} — a reach kind is a non-empty name.")
        if kind in DJB_REACH_TOKENS:
            raise pytest.UsageError(
                f"{where} declares {kind!r}, which apps/conftest.py already declares in "
                "DJB_REACH_TOKENS — a drawer adds a reach kind and never replaces the "
                "template's, so name the product's kind something the template does not."
            )
        if (
            not isinstance(tokens, (tuple, list))
            or not tokens
            or not all(isinstance(token, str) and token for token in tokens)
        ):
            raise pytest.UsageError(
                f"{where}[{kind!r}] is {tokens!r} — a reach kind is a non-empty tuple of "
                "non-empty source tokens; an empty one would derive no reader and floor "
                "nothing."
            )
        kinds[kind] = tuple(tokens)
    return kinds


#: The merged kinds, read once per session: a 4000-item collection asks per module.
_DJB_REACH_TOKENS_MERGED: list[dict[str, tuple[str, ...]]] = []


def _reach_tokens() -> dict[str, tuple[str, ...]]:
    """The template's reach kinds plus the drawer's — the ONE reader of `DJB_REACH_KINDS`."""
    if not _DJB_REACH_TOKENS_MERGED:
        _DJB_REACH_TOKENS_MERGED.append(
            {**DJB_REACH_TOKENS, **_drawer_reach_kinds(_fixtures_drawer())}
        )
    return _DJB_REACH_TOKENS_MERGED[0]


def _reach_floors() -> dict[str, int]:
    """LAYER 1 over every kind in force: the template's floors, and one per drawer kind."""
    return {**{kind: 1 for kind in _reach_tokens()}, **DJB_REACH_FLOORS}


# THE THIRD WAY IN, AND IT IS A DECLARATION RATHER THAN A DERIVATION.
#
# Everything above derives always-on from what a module READS through a Django
# registry. A census that walks the SOURCE TREE BY PATH reads no registry at
# all: `apps/core/tests/test_settings.py` parses `config/settings/base.py`,
# `apps/files/tests/test_storage_fence.py` rglobs every `*.py` under `apps/`,
# `apps/workflows/tests/test_services.py` does the same three times. No token
# above can see any of them, so a scope that does not contain their app
# deselects them — and a change in the app the census exists to police is
# exactly the change no scope will ever pair with the census. That is not a
# narrowing, it is a hole.
#
# So the module SAYS SO ITSELF, at column zero inside its first
# `DJB_CENSUS_MARKER_LINES` lines, in the marker grammar this tree already uses
# for `# drives:` in `scripts/tests/`:
#
#     <marker> <one line saying what population it walks>
#
# THE REASON IS MANDATORY AND ITS ABSENCE IS COULD-NOT-LOOK, never a silently
# unmarked module. The whole value of a declaration over a derivation is that a
# reader can DISAGREE with it, and a bare marker is a claim nobody can dispute.
#
# WHY A DECLARATION AT ALL, when everything else here is derived: the walk is
# spelled in an open set of ways, so the derivation below can only ever be a
# hand list of tokens — and a hand list is right on the day it is written. The
# marker is the half a human writes; `apps/test_census_markers.py` is the half
# that re-derives it, in BOTH directions, so neither half can go quiet alone.
DJB_CENSUS_MARKER = "# census: cross-app"

#: How far into a module the marker is looked for. A header, not a haystack: a
#: declaration buried at line 400 is not a declaration anybody reads.
DJB_CENSUS_MARKER_LINES = 40

# THE POPULATION: THE HALF OF THE DECLARATION A LOOP CAN ACT ON.
#
# A marker alone says "run me at every scope", and that is the right answer for
# a census and the wrong PRICE for every loop that could not possibly have moved
# what the census walks: fifteen marked modules ride on every scope today, and a
# rung that edited one template pays for the module that parses
# `config/settings/base.py` exactly as a rung that edited the settings does.
#
# So the declaration may also say WHICH FILES IT IS ABOUT, in the same line and
# immediately after the marker:
#
#     <marker> population=<glob>[,<glob>] <one line saying what it walks>
#
# The globs are checkout-relative, comma-joined, and shaped like `# drives:`
# (`scripts/gate_ledger.sh`) — `apps/**/*.py`, `config/settings/base.py`,
# `templates/**/*.html`. A census WITH a population runs whenever any changed
# file the caller named (`--djb-changed`) is inside any of its globs, and at
# every scope when the caller named none. A census with NO population runs
# always, exactly as it did before this grammar existed, and the banner SAYS SO
# — the silent default is the one a reader cannot audit.
#
# TWO REFUSALS, BOTH COULD-NOT-LOOK, for the reason the missing reason already
# is one: a `population=` with no globs after it, and a population whose globs
# match NOTHING on this tree (`_census_population_or_refuse`). A glob with a typo
# in it would otherwise deselect its census from every loop forever, and the
# only symptom of that is a green one.
#
# WHAT IT IS NOT: a claim anybody checked. Whether a declared population is the
# RIGHT population is a reviewer's finding, exactly as the reason is — which is
# why both live in the module's first lines, where a reviewer has one place to
# look. `apps/test_census_markers.py` re-derives that the globs resolve, never
# that they are the ones the walk needed.
DJB_CENSUS_POPULATION = "population="

#: The source tokens that mean "this module walks the source tree" — the
#: population the marker exists for, and the population the REVERSE census in
#: `apps/test_census_markers.py` re-derives the marked set from.
#:
#: A HAND LIST OF AN OPEN SET, legal only because of that reverse half: a
#: walker spelled with a fifth token escapes both halves identically, which is
#: this rule's declared blind spot. The day a miss names a fifth token is the
#: day it joins this tuple — and joining it changes these bytes, which moves the
#: loop ledger's key, which is the property the sentinels exist for.
DJB_WALK_TOKENS: tuple[str, ...] = (
    "source_tree(",
    ".rglob(",
    'glob("apps/',
    "glob('apps/",
)
# <<< always-on-derivation <<<

#: Per-module reach verdicts, cached beside the organ verdicts and for the same
#: reason: a 2600-test collection reads each module once.
_DJB_MODULE_REACH: dict[str, frozenset[str]] = {}

#: Per-module membership of the populations INSIDE a reach kind, filled by the
#: same read as `_DJB_MODULE_REACH` so a module's source is read once.
_DJB_MODULE_REACH_POPULATIONS: dict[str, frozenset[str]] = {}

_FixtureFunction = TypeVar("_FixtureFunction", bound=Callable[..., Any])

#: Set by `pytest_collection_modifyitems`, printed by
#: `pytest_report_collectionfinish`. The tier choice is PRINTED ON EVERY RUN: a
#: silent tier choice is an unfalsifiable one, and a reader who cannot see which
#: tier ran cannot tell a fast green from a whole-suite green.
_DJB_TIER_REPORT: list[str] = []

#: Per-module source verdicts, so a 2600-test collection reads each module once.
_DJB_MODULE_ORGANS: dict[str, frozenset[str]] = {}


def organ(name: str) -> Callable[[_FixtureFunction], _FixtureFunction]:
    """Declare that this fixture hands its test a REAL organ.

    The declaration lives on the fixture — the one place that knows — and the
    population of tests it reaches is derived from it. Adding an organ fixture
    anywhere under `apps/` puts every test that reaches it into the slow tier
    with no list to edit and no other file to touch.
    """

    def declare(func: _FixtureFunction) -> _FixtureFunction:
        setattr(func, DJB_ORGAN_ATTRIBUTE, name)
        return func

    return declare


def _module_organs(path: str) -> frozenset[str]:
    """The organs a test MODULE reaches by its own source (see (2) above)."""
    cached = _DJB_MODULE_ORGANS.get(path)
    if cached is not None:
        return cached
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop tier could not read {path} to derive its organ reach ({exc}). "
            "An underived population is not an empty one: nothing was classified, "
            "so this is neither a fast tier nor a full one."
        ) from exc
    organs: frozenset[str] = frozenset()
    if DJB_TEMPORAL_ENTRY_POINT in source:
        organs = frozenset({DJB_TEMPORAL_ORGAN})
    _DJB_MODULE_ORGANS[path] = organs
    return organs


def _item_organs(item: pytest.Item) -> frozenset[str]:
    """Every organ this item reaches, by fixture closure and by module source."""
    organs: set[str] = set()
    # `_fixtureinfo` is pytest's own per-item fixture CLOSURE. It is private, and
    # that is why the floors below exist: if a future pytest renames it, this
    # returns nothing for everything, the floors go unmet and the tier refuses
    # rather than silently running the fast half of nothing.
    info: Any = getattr(item, "_fixtureinfo", None)
    name2fixturedefs: Any = getattr(info, "name2fixturedefs", None)
    if isinstance(name2fixturedefs, dict):
        for defs in name2fixturedefs.values():
            if not defs:
                continue
            # The LAST definition is the one this item resolves — a fixture name
            # overridden closer to the test wins, exactly as pytest resolves it.
            declared = getattr(getattr(defs[-1], "func", None), DJB_ORGAN_ATTRIBUTE, None)
            if isinstance(declared, str):
                organs.add(declared)
    path = getattr(item, "path", None)
    if path is not None:
        organs |= _module_organs(str(path))
    return frozenset(organs)


def _app_label(nodeid: str) -> str | None:
    """`apps/<label>/…` -> `<label>`; anything else -> no app.

    `apps/test_temporal_guard.py` and `apps/test_gate_liveness.py` sit at the
    root and belong to no app, so they are never anybody's own app.
    """
    parts = nodeid.split("/")
    if len(parts) >= 3 and parts[0] == "apps":
        return parts[1]
    return None


def _module_of(nodeid: str) -> str:
    """`apps/x/tests/test_y.py::test_z[p]` -> `apps/x/tests/test_y.py`.

    The populations below are counts of MODULES, so the split has to happen in
    one place: counting `::`-qualified nodeids instead multiplies a population
    by its parametrisation and turns a floor into a number nobody can predict.
    """
    return nodeid.split("::")[0]


def _module_reach(path: str) -> frozenset[str]:
    """The whole-population reach kinds this test MODULE has, by its own source.

    The same tolerant-read failure mode as `_module_organs`, and the same
    answer: a module pytest has just imported and this cannot read is a refusal,
    never an empty answer.
    """
    cached = _DJB_MODULE_REACH.get(path)
    if cached is not None:
        return cached
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to derive its cross-app reach "
            f"({exc}). An underived population is not an empty one: nothing was "
            "classified, so this is neither a scoped run nor a whole one."
        ) from exc
    reach = frozenset(
        kind for kind, tokens in _reach_tokens().items() if any(token in source for token in tokens)
    )
    _DJB_MODULE_REACH[path] = reach
    _DJB_MODULE_REACH_POPULATIONS[path] = frozenset(
        name
        for name, tokens in DJB_REACH_POPULATIONS.items()
        if any(token in source for token in tokens)
    )
    return reach


def _module_reach_populations(path: str) -> frozenset[str]:
    """The `DJB_REACH_POPULATIONS` this module belongs to — read with its reach."""
    _module_reach(path)
    return _DJB_MODULE_REACH_POPULATIONS.get(path, frozenset())


#: Per-module census DECLARATIONS, cached beside the reach ones and for the same
#: reason. `("", ())` is a real answer here (this module declares nothing), which
#: is why the cache is checked with `is not None` rather than for truthiness.
_DJB_MODULE_CENSUS: dict[str, tuple[str, tuple[str, ...]]] = {}


def _module_census_reason(path: str) -> str:
    """The reason a module DECLARES for being a cross-app census; `""` unmarked."""
    return _module_census_declaration(path)[0]


def _module_census_population(path: str) -> tuple[str, ...]:
    """The globs a marked module DECLARES it is about; `()` when it names none.

    `()` is "no population — always", not "an empty population": the second is a
    refusal and it is made in `_module_census_declaration` below.
    """
    return _module_census_declaration(path)[1]


def _module_census_declaration(path: str) -> tuple[str, tuple[str, ...]]:
    """The reason and the population a module DECLARES; `("", ())` unmarked.

    The grammar is the sentinel block's: the marker at column zero, inside the
    first `DJB_CENSUS_MARKER_LINES` lines, followed by whitespace, an optional
    `population=<glob>[,<glob>]`, and a reason.

    THREE REFUSALS, AND ALL THREE ARE COULD-NOT-LOOK RATHER THAN AN EMPTY
    ANSWER — the same rule its two neighbours state, for the same reason. A
    module pytest has just imported and this cannot read is a refusal; a marker
    with NO reason is a refusal too, because the alternative is treating an
    unreadable declaration as an absent one, which is how a census silently
    stops being always-on at the moment somebody half-wrote its marker; and a
    `population=` with no globs after it is the same failure one clause along.
    The fourth refusal — a population that names nothing on the tree — needs a
    tree and is therefore `_census_population_or_refuse`'s, not this one's.
    """
    cached = _DJB_MODULE_CENSUS.get(path)
    if cached is not None:
        return cached
    try:
        head = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to derive its census declaration "
            f"({exc}). An underived population is not an empty one: a module this "
            "could not read would be deselected as if it had declared nothing."
        ) from exc
    reason = ""
    globs: tuple[str, ...] = ()
    for line in head[:DJB_CENSUS_MARKER_LINES]:
        if not line.startswith(DJB_CENSUS_MARKER):
            continue
        rest = line[len(DJB_CENSUS_MARKER) :]
        if rest and not rest[0].isspace():
            # `<marker>lication` is a different word, not this marker.
            continue
        reason = rest.strip()
        if reason.startswith(DJB_CENSUS_POPULATION):
            # THE POPULATION COMES FIRST AND IT IS ONE WORD. Anything after the
            # first whitespace is the reason, whole — a population is a machine's
            # half of the line and a sentence is a reader's, and putting the
            # machine's half first is what keeps the sentence from having to be
            # parsed at all.
            spec, _, reason = reason[len(DJB_CENSUS_POPULATION) :].partition(" ")
            globs = tuple(part for part in spec.split(",") if part)
            reason = reason.strip()
            if not globs:
                raise pytest.UsageError(
                    f"{path} declares an EMPTY POPULATION. The grammar is "
                    f"`{DJB_CENSUS_MARKER} {DJB_CENSUS_POPULATION}<glob>[,<glob>] "
                    "<reason>` — see the sentinel block in apps/conftest.py. A "
                    "population nobody can match against is not a narrowing, it is "
                    "a census that would be deselected by every scope, so this "
                    "refuses rather than reading it as an absent population."
                )
        if not reason:
            raise pytest.UsageError(
                f"{path} declares itself a cross-app census and gives NO REASON. "
                "The grammar is the marker at column zero followed by one line "
                "saying what population the module walks — see the sentinel block "
                "in apps/conftest.py. A declaration nobody can disagree with is "
                "not a declaration, so this refuses rather than reading the line "
                "as an absent marker."
            )
        break
    _DJB_MODULE_CENSUS[path] = (reason, globs)
    return reason, globs


# --- the population: matching it, resolving it, and saying what it did -------

#: The checkout, for resolving a declared population against a real tree.
#: `apps/conftest.py` -> the directory above `apps`, the same arithmetic
#: `apps/test_census_markers.py::REPO_ROOT` does.
DJB_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _census_glob_regex(glob: str) -> str:
    """One checkout-relative glob as an anchored regex over a POSIX path.

    `fnmatch` is not this, and the difference is the whole reason for the eight
    lines: its `*` crosses `/`, so `apps/*/services.py` would match
    `apps/core/api/services.py` and a population would silently be wider than
    the one its author wrote. Here `*` is one segment's worth, `**` is any
    number of whole segments, and a trailing `**` is everything below.
    """
    segments = glob.split("/")
    out = ["^"]
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
            continue
        out.append(
            "".join(
                "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
                for char in segment
            )
        )
        if not last:
            out.append("/")
    out.append("$")
    return "".join(out)


def _census_glob_matches(glob: str, path: str) -> bool:
    """Whether one checkout-relative path is inside one declared glob."""
    return re.match(_census_glob_regex(glob), path.lstrip("./")) is not None


def _census_verdict(module: str, globs: tuple[str, ...], changed: frozenset[str]) -> str | None:
    """`None` when this census still runs; the SENTENCE saying why not when it does not.

    Two ways to be kept and they are not the same claim: a census with no
    population is unconditional (the grammar's default, printed by
    `_census_banner`), and a caller that named no changed files narrows nothing
    at all — the `--djb-scope-narrow` rule, which is that nothing narrows unless
    somebody asked.
    """
    if not globs or not changed:
        return None
    if any(_census_glob_matches(glob, path) for glob in globs for path in changed):
        return None
    return f"{module}: population {','.join(globs)} does not contain the change — deselected"


#: Resolved populations, keyed on the module and the root they were resolved
#: against: the check walks the tree, and a per-item walk over fifteen modules
#: is the difference between a banner and a cost.
_DJB_CENSUS_RESOLVED: dict[tuple[str, str], tuple[str, ...]] = {}


def _census_population_or_refuse(path: str, root: pathlib.Path) -> tuple[str, ...]:
    """The module's population, REFUSING one whose globs name nothing on this tree.

    An underived population is not an empty one — the rule the reach and the
    reason derivations above both make. Read as "no files", a glob with a typo in
    it deselects its census from every loop forever and the only symptom is a
    green one.
    """
    key = (path, str(root))
    cached = _DJB_CENSUS_RESOLVED.get(key)
    if cached is not None:
        return cached
    globs = _module_census_population(path)
    # `next(..., None)` rather than a list: the question is whether the glob
    # reaches ANYTHING, and `apps/**/*.py` over this tree is four thousand paths.
    missing = [glob for glob in globs if next(iter(root.glob(glob)), None) is None]
    if missing:
        raise pytest.UsageError(
            f"{path} declares population {','.join(missing)}, which names NOTHING "
            f"under {root}. An underived population is not an empty one: read as "
            "an empty set, this census would be deselected by every scope forever "
            "and the only symptom would be a green loop. Fix the glob, or drop the "
            "`population=` clause and let the census run always."
        )
    _DJB_CENSUS_RESOLVED[key] = globs
    return globs


#: The counts-file field that carries one always-on module and its way in.
DJB_ALWAYS_ON_FIELD = "always_on_module"
#: The counts-file field carrying `_impact_selection`'s line.
DJB_IMPACT_FIELD = "impact"

#: The seeded census's own declaration, at column zero — the line
#: `scripts/loop_tier.sh`'s `loop_scope__census_modules` greps for.
DJB_CENSUS_SEEDED_BY = "CENSUS_SEEDED_BY"

_DJB_MODULE_SEEDS: dict[str, bool] = {}


def _module_seeds_a_census(path: str) -> bool:
    """Whether the module declares `CENSUS_SEEDED_BY` at column zero."""
    cached = _DJB_MODULE_SEEDS.get(path)
    if cached is not None:
        return cached
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to tell a seeded census from an "
            f"edited module ({exc}). An underived population is not an empty one."
        ) from exc
    seeds = any(line.startswith(DJB_CENSUS_SEEDED_BY) for line in lines)
    _DJB_MODULE_SEEDS[path] = seeds
    return seeds


def _way_in(nodeid: str, reach: frozenset[str]) -> str:
    """How an always-on module got in, in `_is_always_on`'s own order.

    `structural` (it belongs to no app, so no scope can hold it), `derived:
    <kind>[,<kind>]` (it reads a whole registry), or `declared` (it carries the
    census marker). The fourth way, `seeded`, is not unconditional and is named
    where the kept set is known.
    """
    if _app_label(nodeid) is None:
        return "structural"
    if reach:
        return "derived: " + ",".join(sorted(reach))
    return "declared"


def _always_on_headline(ways: dict[str, str], derived: int, dropped: int) -> str:
    """The one line that heads the list, and says how it differs from `derived`.

    TWO NUMBERS WOULD OTHERWISE SIT UNDER ONE LABEL: the derivation's module
    count is taken BEFORE the fast tier, and the list is what RAN after it —
    an organ-reaching census outside the rung's own apps is dropped whole there,
    and a seeded census joins after the derivation. The line names both moves.
    """
    seeded = sum(1 for way in ways.values() if way == "seeded")
    parts = [f"{derived} derived before the tier"]
    if dropped:
        parts.append(
            f"{dropped} dropped whole by the fast tier (organ-reaching, outside the own apps)"
        )
    if seeded:
        parts.append(f"{seeded} seeded by the change")
    return f"always-on: {len(ways)} modules ran — " + ", ".join(parts)


def _always_on_banner(ways: dict[str, str], derived: int, dropped: int) -> list[str]:
    """`always-on: <n> modules …`, then every module with its way in, one line each.

    An always-on set nobody can enumerate is one nobody audits — and a count
    alone cannot say WHICH module a scope kept, or why, which is the question a
    reader has when a cross-app census did or did not run.
    """
    return [f"  {_always_on_headline(ways, derived, dropped)}"] + [
        f"    {module} {way}" for module, way in sorted(ways.items())
    ]


def _census_banner(declared: dict[str, tuple[str, ...]], changed: frozenset[str]) -> list[str]:
    """What the run SAYS about the declared censuses it narrowed.

    An always-on set nobody can enumerate is one nobody audits — the argument
    `scripts/check.sh`'s own declared-census listing is printed for. This is the
    narrowing half of that: how many declarations there are, how many of them
    are bounded by a population, how many survived this run's changed files, and
    the module-by-module sentence for every one that did not.
    """
    deselected = sorted(
        sentence
        for module, globs in declared.items()
        if (sentence := _census_verdict(module, globs, changed)) is not None
    )
    unbounded = sorted(module for module, globs in declared.items() if not globs)
    lines = [
        f"  declared censuses: {len(declared)} declared, "
        f"{len(declared) - len(unbounded)} with a population, "
        f"{len(declared) - len(deselected)} selected"
    ]
    if unbounded:
        lines.append("  (no population — always): " + ", ".join(unbounded))
    lines += [f"  {sentence}" for sentence in deselected]
    return lines


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
    reason `scripts/loop_tier.sh` gives: it is a fixture every module of `<x>`
    stands on.
    """
    parts = module.split("/")
    return len(parts) >= 4 and parts[0] == "apps" and parts[2] == "tests"


def _module_test_imports(path: str, labels: frozenset[str]) -> frozenset[str]:
    """The tests-only labels whose TEST PACKAGE this module's source names.

    THE COUPLING A TESTS-ONLY CHANGE CAN ACTUALLY BREAK. A change under
    `apps/x/tests/` cannot break another app's code, but it can break another
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


def _assert_the_floors(
    reached_kinds: dict[str, set[str]], populations: dict[str, set[str]], whole: bool
) -> None:
    """Both layers of floors, or a `pytest.UsageError` naming what is wrong.

    LAYER 1 always (a reach kind nothing reads is a derivation gone blind,
    whatever was collected); LAYER 2 only over the whole tree
    (`_collects_the_whole_tree`) and as an EQUALITY with its members named
    (`_population_floor_text`). Raised before anything is deselected.
    """
    unmet_reach = sorted(
        f"{kind} (floor {floor}, derived {len(reached_kinds.get(kind, ()))} module(s))"
        for kind, floor in _reach_floors().items()
        if len(reached_kinds.get(kind, ())) < floor
    )
    unmet_population: list[str] = []
    if whole:
        for name, floor in sorted(_population_floors().items()):
            text = _population_floor_text(name, floor, populations.get(name, set()))
            if text is not None:
                unmet_population.append(text)
    if not unmet_reach and not unmet_population:
        return
    raise pytest.UsageError(
        "the --loop scope's always-on derivation is not answering, so "
        "NOTHING was deselected. "
        + ("LAYER 1 (reach kind): " + "; ".join(unmet_reach) + ". " if unmet_reach else "")
        + (
            "LAYER 2 (named population): "
            + "; ".join(unmet_population)
            + ". "
            + DJB_POPULATION_FLOOR_REMEDY
            + " "
            if unmet_population
            else ""
        )
        + "A scope narrows the suite to the active rung's apps and leans on the "
        "always-on set for everything that quantifies over the whole tree. "
        "A derivation that stopped seeing a kind reads exactly like a tree "
        "that no longer has one, an EMPTIED population reads exactly like a "
        "smaller suite, and a GROWN one is a member no declaration names — so "
        "this refuses instead of running a tier nobody can trust. The "
        "declaration and the floors are the sentinel block in apps/conftest.py; "
        "the scope that asked for this is scripts/loop_tier.sh."
    )


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
            "`--loop` derives the scope in scripts/loop_tier.sh; no flag names an "
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
            "scripts/loop_tier.sh; no flag names an app INTO the closure."
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
            "is written by scripts/test_impact.py and read by scripts/loop_tier.sh; "
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


# --- the worker ceiling: a typed `-n` cannot exceed this box's slot share -----
#
# THE DEFECT THIS CLOSES. The gate splits this machine's cores into pytest
# SLOTS and every slot holder runs its share (`scripts/gate_lease.sh`,
# `gate_slot_workers`; `scripts/check.sh` runs `-n $GATE_SLOT_WORKERS`). A
# direct `uv run pytest … -n 10` holds no slot and read no ceiling, so it ran
# ten workers beside two gates running five each and minted ten
# `test_<db>_gwN` databases on the way — the shared-box contention that put a
# sibling platform's Postgres into recovery. `scripts/test.sh` now refuses
# `-n auto`; this is the belt for every other way a number gets typed,
# including a bare `uv run pytest`, because the runner is not the only door.
#
# ONE NUMBER, AND WHERE IT COMES FROM. An inherited `DJB_GATE_SLOT_WORKERS` or
# `DJB_PYTEST_MAX_WORKERS` wins outright — that is the caller handing down the
# share it already took, and this must never second-guess it. Only when nothing
# was handed down is the share DERIVED, and then it is derived exactly as
# `scripts/gate_lease.sh` derives it (cores ÷ slots, slots = cores ÷ 5 or
# `DJB_GATE_SLOTS`). That derivation is a SECOND copy of a shell constant and it
# is named as one: `scripts/tests/test_loop_scope.sh`'s
# `case_the_python_clamp_and_the_shell_share_are_the_same_number` runs both and
# asserts they agree, so the copy cannot drift in silence.
#
# AND EVERY GATE LEG NOW HANDS IT DOWN, which is what closes the one case the
# derivation above cannot get right. A `--bank` run holds EVERY pytest slot, so
# its share is the whole box's cores rather than one slot's — a number this file
# has no way to reach, because "how many slots is this holder holding" is the
# semaphore's state and not the box's. It derived one slot's share anyway,
# clamped the bank's `-n 10` to 5, and left the collector census expecting ten
# collectors from a five-worker run: `5 of 10 collectors reported`, exit 2,
# nothing banked (bank-2349.log, 2026-09-16). `gate_slot_worker_count`
# (scripts/gate_lease.sh) exports the resolved share under the first name above
# and `gate_slot_release` unsets it, so under any gate leg the branch below takes
# the hand-down and the derivation is what a BARE `uv run pytest` gets — which is
# the door the ceiling was built for.
#
# THE ESCAPE IS TYPED: `DJB_PYTEST_UNCAPPED=1`. A ceiling with no way past it
# gets worked around by leaving the runner, which is the one place nobody can
# see the number at all.
_DJB_GATE_SLOT_CORES_PER_SLOT = 5  # scripts/gate_lease.sh: GATE_SLOT_CORES_PER_SLOT


def _djb_positive_int(raw: str) -> int | None:
    text = raw.strip()
    return int(text) if text.isdigit() and int(text) >= 1 else None


def _djb_slot_share() -> int | None:
    """This run's worker ceiling, or None when nobody can say what it is."""
    for name in ("DJB_GATE_SLOT_WORKERS", "DJB_PYTEST_MAX_WORKERS"):
        handed_down = _djb_positive_int(os.environ.get(name, ""))
        if handed_down is not None:
            return handed_down
    cores = os.cpu_count() or 0
    if cores < 1:
        # A ceiling nobody can derive is no ceiling: refusing here would turn an
        # unreadable core count into a failed test run, and the gate's own
        # derivation falls back the same way rather than guessing small.
        return None
    declared = os.environ.get("DJB_GATE_SLOTS", "").strip()
    if declared:
        slots = _djb_positive_int(declared)
        if slots is None:
            return None
    else:
        slots = max(cores // _DJB_GATE_SLOT_CORES_PER_SLOT, 1)
    return max(cores // slots, 1)


def pytest_configure(config: pytest.Config) -> None:
    """Lower a typed `-n` to the slot share, and say so on one line."""
    typed = getattr(config.option, "numprocesses", None)
    if os.environ.get("DJB_PYTEST_UNCAPPED", "").strip():
        # THE ESCAPE PRINTS, AND THAT IS THE HALF THAT MAKES IT AN ESCAPE RATHER
        # THAN A HOLE. A ceiling with a silent override is a ceiling nobody can
        # tell they are outside: the transcript of an uncapped run and the
        # transcript of a capped one differed nowhere, so `-n 10` on a five-share
        # box read exactly like `-n 5` to every later reader of the log.
        #
        # It says the number that was TYPED and the share it is running past, so
        # the line answers both questions a reader has — how many workers this
        # box is about to carry, and how many it would have carried. An
        # underivable share says so rather than printing a guess.
        if isinstance(typed, int) and typed >= 1:
            share = _djb_slot_share()
            basis = (
                f"the slot share on this box is {share}"
                if share is not None
                else "the slot share on this box could not be derived"
            )
            sys.stderr.write(f"uncapped: -n {typed} (DJB_PYTEST_UNCAPPED=1 — {basis})\n")
        return
    # `auto`/`logical` are still strings here on the bare-pytest path (xdist
    # resolves them in its own `pytest_cmdline_main`, which has already run);
    # scripts/test.sh refuses those outright, and a run that reaches here with
    # one has no number to compare.
    if not isinstance(typed, int) or typed < 1:
        return
    share = _djb_slot_share()
    if share is None or typed <= share:
        return
    config.option.numprocesses = share
    # xdist builds one `tx` entry per worker in `pytest_cmdline_main`, BEFORE
    # this hook, and `NodeManager` reads that list rather than the number — so
    # lowering the number alone would print a clamp and still start every
    # worker. Measured, not assumed: the drive asserts the worker count.
    spec = getattr(config.option, "tx", None)
    if isinstance(spec, list) and len(spec) > share:
        config.option.tx = spec[:share]
    sys.stderr.write(
        f"clamped -n {typed} → {share} (DJB_PYTEST_UNCAPPED=1 to override)\n"
        f"  this box's cores are shared between the gate's pytest slots; "
        f"{share} is one slot's share (scripts/gate_lease.sh, gate_slot_workers).\n"
    )


def pytest_report_header(config: pytest.Config) -> list[str]:
    """The tier CHOICE, printed before collection — which is the only place it
    survives `-n auto`.

    MEASURED, not assumed: under xdist the WORKERS collect and the controller
    only compares their lists, so `pytest_collection_modifyitems` (and the
    counts it knows) runs in the workers and its report line never reaches the
    terminal. The session header does — the controller prints it — so the
    declaration lives here and the counts live below, where a serial run and
    the census drive can both see them. `--loop` prints its own basis, own apps
    and rule beside this, at the leg (`scripts/check.sh`).
    """
    if str(config.getoption("--djb-tier")) != "fast":
        return list(_DJB_ABSENT_REPORT)
    own = [str(label) for label in config.getoption("--djb-own-app")]
    if own:
        where = "everywhere except " + ", ".join(f"apps/{label}" for label in sorted(own))
        where += ", which are in scope and run IN FULL"
    else:
        where = "everywhere — no app is in scope under apps/<x>/, so there is no own app"
    scope_line: list[str] = []
    if bool(config.getoption("--djb-scope-narrow")):
        scoped = sorted(set(str(label) for label in config.getoption("--djb-scope")) | set(own))
        scope_line = [
            "djb scope: NARROWED — every app outside "
            + (", ".join(f"apps/{label}" for label in scoped) or "(an empty scope)")
            + " is DESELECTED except the derived always-on cross-app set. The scope "
            "is the active rung's touched apps plus the reverse-transitive depends_on "
            "closure (scripts/loop_tier.sh); a regression in a deselected app "
            "surfaces at the wave bank, not at the active rung."
        ]
    return [
        *_DJB_ABSENT_REPORT,
        "djb tier: FAST — organ-reaching tests (real MinIO, a real Temporal server, "
        f"real Meili) are DESELECTED {where}. The full gate at push runs every one "
        "of them, twice.",
        *scope_line,
    ]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # The absent-app world first, and unconditionally: what a smaller deployment
    # cannot run is not a tier choice, and the tier's early return below is
    # allowed to skip work only because it changes nothing.
    _withhold_the_absent_world(items)
    tier = str(config.getoption("--djb-tier"))
    manifest = str(config.getoption("--djb-tier-manifest"))
    narrow = bool(config.getoption("--djb-scope-narrow"))
    counts_dir = str(config.getoption("--djb-scope-counts"))
    # THE IMPACT SEAM. `--djb-impact-select` is a selection and narrows on its
    # own; `--djb-changed` is a MODIFIER and narrows nothing by itself — it can
    # only subtract from the declared censuses of a run that was already
    # narrowing, which is why it is absent from the early return below.
    impact_select = str(config.getoption("--djb-impact-select"))
    changed = frozenset(str(path).lstrip("./") for path in config.getoption("--djb-changed"))
    _DJB_TIER_REPORT.clear()
    if tier == "all" and not manifest and not narrow and not impact_select:
        # THE WHOLE-SUITE BRANCH, AND IT STILL PAYS NOTHING. No source read, no
        # closure walk, no deselection, no behaviour change — the one thing it
        # does now is SAY HOW MANY TESTS THIS COLLECTOR HELD, and only when a
        # caller asked for counts at all.
        #
        # WHY IT HAS TO. The counts file is the only evidence that a collector
        # reached the end of collecting, and the reconciliation in
        # `scripts/check.sh` is what turns a missing one into a refusal. It was
        # written under `--loop` alone, so the full gate's two passes wrote none
        # — and a worker that dies during collection with xdist's restart budget
        # exhausted leaves pytest able to exit **0** with `no tests ran`, which
        # the full gate reads as a clean tree and banks. Nothing is
        # deselected on this branch, so the file says `selected=<everything>`
        # and `deselected=0`: a population, not a scope.
        #
        # AND IT ASSERTS THE FLOORS WHEN IT HOLDS THE WHOLE TREE. A `--loop` whose
        # rung changed shared test infrastructure runs the WHOLE suite on this
        # branch — and adding an apps-root module IS that change — so a floor
        # read only under narrowing was never read by the one loop that grew its
        # population (measured: a seventh apps-root module, a whole-suite loop,
        # green). One cached source read per collected module per collector.
        if _collects_the_whole_tree(config):
            _assert_the_floors(*_reach_and_populations(items), whole=True)
        if counts_dir:
            _write_scope_counts(
                config,
                counts_dir,
                frozenset(),
                frozenset(),
                frozenset(),
                0,
                0,
                0,
                0,
                0,
                len(items),
                0,
            )
        return

    own_apps = frozenset(str(label) for label in config.getoption("--djb-own-app"))
    # The rung's OWN apps are always inside its scope — it edited them. Stated
    # as a union rather than assumed, so a caller that named an own app and
    # forgot the scope flag narrows nothing it should have kept.
    scope_apps = frozenset(str(label) for label in config.getoption("--djb-scope")) | own_apps
    # THE TESTS-ONLY SET, which is neither of the two above and must not be
    # folded into either: an app here is NOT own (its organ tests stay
    # push-side) and NOT in scope (nothing widened to it through the
    # declarations). It brings its own test tree, the modules the rung edited,
    # and the modules that import its test package — and nothing else.
    tests_only = frozenset(str(label) for label in config.getoption("--djb-tests-only"))
    changed_tests = frozenset(str(path) for path in config.getoption("--djb-changed-test"))
    classified = [(item, _item_organs(item)) for item in items]

    reached: dict[str, int] = {}
    for _item, organs in classified:
        for name in organs:
            reached[name] = reached.get(name, 0) + 1
    unmet = sorted(
        f"{kind} (floor {floor}, derived {reached.get(kind, 0)})"
        for kind, floor in DJB_ORGAN_FLOORS.items()
        if reached.get(kind, 0) < floor
    )
    if unmet:
        raise pytest.UsageError(
            "the --loop tier's organ derivation is not answering: "
            + "; ".join(unmet)
            + ". Nothing was deselected. A derivation that stopped seeing an organ "
            "kind reads exactly like a suite that no longer has one, so this refuses "
            "instead of running a fast tier nobody can trust. If you asked for "
            "--djb-tier=fast over a NARROW path, this is that refusal working: the "
            "floors are asserted over the whole collection, and `--loop` always "
            "collects the whole suite. Narrow a run with a path and leave the tier "
            "alone — it defaults to `all`."
        )

    # THE ALWAYS-ON DERIVATION AND ITS TWO LAYERS OF FLOORS, asserted BEFORE a
    # single item is deselected. Derived whenever narrowing is asked for, so the
    # refusal cannot be dodged by a scope that happens to be empty.
    always_on: set[str] = set()
    always_on_ways: dict[str, str] = {}
    declared_censuses: dict[str, tuple[str, ...]] = {}
    if narrow or impact_select:
        reached_kinds: dict[str, set[str]] = {}
        populations: dict[str, set[str]] = {}
        for item in items:
            path = str(getattr(item, "path", "") or "")
            reach = _module_reach(path) if path else frozenset()
            module = _module_of(item.nodeid)
            for kind in reach:
                reached_kinds.setdefault(kind, set()).add(module)
            for name in _population_members(path, item.nodeid):
                populations.setdefault(name, set()).add(module)
            if path and _app_label(item.nodeid) is not None and _module_census_reason(path):
                declared_censuses[module] = _census_population_or_refuse(path, DJB_REPO_ROOT)
            if _is_always_on(item, reach, changed):
                always_on.add(item.nodeid)
                always_on_ways.setdefault(module, _way_in(item.nodeid, reach))

        _assert_the_floors(reached_kinds, populations, _collects_the_whole_tree(config))
    elif _collects_the_whole_tree(config):
        _assert_the_floors(*_reach_and_populations(items), whole=True)

    if manifest and not hasattr(config, "workerinput"):
        lines = []
        for item, organs in classified:
            where = "slow" if organs else "fast"
            lines.append(f"{where}\t{','.join(sorted(organs)) or '-'}\t{item.nodeid}")
        pathlib.Path(manifest).write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")

    if tier != "fast" and not narrow and not impact_select:
        return

    # THE SELECTION, READ BEFORE ANYTHING IS DESELECTED, for the reason the
    # floors above are asserted there: a selection file this could not read must
    # never reach the loop below as an empty set.
    selected: frozenset[str] = frozenset()
    impact_line = ""
    if impact_select:
        selected, impact_line = _impact_selection(
            [item.nodeid for item in items],
            _read_impact_select(impact_select),
            frozenset(always_on),
        )

    keep: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    n_in_scope = 0
    n_always_on = 0
    n_tests_only = 0
    importer_modules: set[str] = set()
    always_on_modules = {_module_of(nodeid) for nodeid in always_on}
    for item, organs in classified:
        label = _app_label(item.nodeid)
        module = _module_of(item.nodeid)
        in_scope = label in scope_apps
        is_own = label in own_apps
        # THE THREE WAYS A TESTS-ONLY APP REACHES AN ITEM, each its own claim.
        in_tests_tree = label in tests_only and _is_app_tests_module(module)
        is_changed_test = module in changed_tests
        imports_tests = (
            _module_test_imports(str(getattr(item, "path", "") or ""), tests_only)
            if tests_only
            else frozenset()
        )
        if imports_tests and not in_tests_tree:
            importer_modules.add(module)
        tests_only_keeps_it = in_tests_tree or is_changed_test or bool(imports_tests)
        if impact_select and item.nodeid not in selected:
            # THE MAP ANSWERED. A selection is the whole question — the scope
            # rules below would only ever widen it back, which is the one thing
            # a caller that handed over a list did not ask for.
            dropped.append(item)
            continue
        if narrow and not in_scope and item.nodeid not in always_on and not tests_only_keeps_it:
            # Outside the scope and not a cross-app tripwire: the active rung's change
            # cannot reach it, by the declarations the closure walked.
            dropped.append(item)
            continue
        if tier == "fast" and organs and not is_own and not is_changed_test:
            # Organ-reaching outside the rung's OWN apps — the organ tier's rule,
            # unchanged, and still push-time. It applies to an in-scope app the
            # closure pulled in and to an always-on member alike: neither being
            # reachable nor being unconditional earns a test a real MinIO in a
            # per-rung gate. THE ONE EXEMPTION is a module the rung EDITED: a
            # test somebody just changed is the one organ test this gate has a
            # reason to run, and it is named by path, not by app.
            dropped.append(item)
            continue
        keep.append(item)
        if in_scope:
            n_in_scope += 1
        elif tests_only_keeps_it and item.nodeid not in always_on:
            n_tests_only += 1
        else:
            n_always_on += 1
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep

    # THE FOURTH WAY IN, AND IT IS NOT UNCONDITIONAL: a census the scope SEEDED
    # because the change touched a declaration module it quantifies over
    # (`CENSUS_SEEDED_BY`, derived by `scripts/loop_tier.sh`). It arrives as a
    # changed-test path, so it is named here only when it is kept and carries
    # the declaration — an edited module is not a census.
    #
    # AND THE LIST IS WHAT RAN: a member the organ tier took out whole (an
    # organ-reaching census outside the rung's own apps, under `--djb-tier=fast`)
    # is not printed as if it had run.
    kept_modules = {_module_of(item.nodeid) for item in keep}
    dropped_whole = sum(1 for module in always_on_ways if module not in kept_modules)
    always_on_ways = {m: way for m, way in always_on_ways.items() if m in kept_modules}
    for item in keep:
        module = _module_of(item.nodeid)
        if module in always_on_ways or module not in changed_tests:
            continue
        path = str(getattr(item, "path", "") or "")
        if path and _module_seeds_a_census(path):
            always_on_ways[module] = "seeded"

    if counts_dir:
        _write_scope_counts(
            config,
            counts_dir,
            own_apps,
            scope_apps,
            tests_only,
            n_in_scope,
            n_always_on,
            n_tests_only,
            len(always_on_modules),
            len(importer_modules),
            len(keep),
            len(dropped),
            always_on_ways,
            dropped_whole,
            impact_line,
        )

    census = ", ".join(f"{kind}={reached[kind]}" for kind in sorted(reached)) or "none"
    if narrow or impact_select:
        # THE ALWAYS-ON SET, ENUMERATED. A set nobody can enumerate is one
        # nobody audits — the argument `scripts/check.sh`'s declared-census
        # listing is printed for, and this is its narrowing half.
        _DJB_TIER_REPORT.extend(
            _always_on_banner(always_on_ways, len(always_on_modules), dropped_whole)
        )
        _DJB_TIER_REPORT.extend(_census_banner(declared_censuses, changed))
        _DJB_TIER_REPORT.append(
            f"  {impact_line}" if impact_line else "  impact: not consulted (seam only)"
        )
    if narrow:
        _DJB_TIER_REPORT.append(
            f"djb scope: {len(dropped)} test(s) deselected, {len(keep)} running "
            f"({n_in_scope} in scope, {n_always_on} always-on) — derived organ "
            f"reach: {census}."
        )
    elif impact_select:
        # NOT "FAST" AND NOT "SCOPE": a selection is a third basis, and printing
        # one of the other two here would tell a reader the run narrowed by a
        # rule it did not use.
        _DJB_TIER_REPORT.append(
            f"djb impact: {len(dropped)} test(s) deselected, {len(keep)} running — "
            f"the selection came from {impact_select}, plus the always-on set. "
            f"Derived organ reach: {census}."
        )
    else:
        _DJB_TIER_REPORT.append(
            f"djb tier: FAST — {len(dropped)} organ-reaching test(s) deselected, "
            f"{len(keep)} running (derived reach: {census})."
        )
    if own_apps:
        _DJB_TIER_REPORT.append(
            "  own app(s), run IN FULL including organ tests: " + ", ".join(sorted(own_apps))
        )
    else:
        _DJB_TIER_REPORT.append(
            "  no app is in scope under apps/, so there is NO own app: the rule for "
            "that case is the always-on set alone, and it is declared here rather "
            "than chosen silently."
        )
    _DJB_TIER_REPORT.append(
        "  the deselected tests are NOT skipped forever — the FULL gate at push runs "
        "every one of them, twice."
    )


def _write_scope_counts(
    config: pytest.Config,
    counts_dir: str,
    own_apps: frozenset[str],
    scope_apps: frozenset[str],
    tests_only: frozenset[str],
    in_scope: int,
    always_on: int,
    tests_only_tests: int,
    always_on_modules: int,
    importer_modules: int,
    selected: int,
    deselected: int,
    always_on_ways: dict[str, str] | None = None,
    always_on_dropped_whole: int = 0,
    impact_line: str = "",
) -> None:
    """One counts file per COLLECTOR, named for the collector.

    RECONCILE, NEVER SUM. Under xdist every worker performs its own full
    collection and then runs its share, so all N workers derive the SAME three
    counts and a sum multiplies them by N. The caller compares the files and
    refuses on disagreement — a disagreement means two collectors saw different
    suites, and a verdict banked under a scope one of them disowned is a verdict
    about nothing.

    AND EVERY FILE CARRIES THE POPULATION IT BELONGS TO. `workers=` is the
    worker count pytest actually CREATED for this run — the number xdist prints
    as `created: N/N workers` — and it is here because the census in
    `scripts/check.sh` (`loop_counts_refuse_if_short`) has to answer "how many
    collectors should have reported" and the only honest source for that is the
    run itself. It used to answer with the `-n` the leg ASKED for, so a leg whose
    `-n` was lowered inside pytest read its own survivors as casualties:
    `5 of 10 collectors reported — a collector died`, exit 2, on a suite that had
    just passed 3653 tests. Identical in every worker, so the file-vs-file
    comparison above is unchanged by it.

    AND IT IS `workerinput["workercount"]`, NOT `numprocesses`. Measured, not
    assumed: a WORKER's own config carries no `-n` at all — `numprocesses` there
    is 0, so a file written from the number the controller was given records
    `workers=0` and the census silently learns nothing (it did, on the first
    green run of this drive). `workercount` is what the controller hands each
    worker when it creates it, so it is the created population by construction.
    The controller/serial path has no `workerinput` and falls back to its own
    `numprocesses`, which is that path's true population.
    """
    workerinput = getattr(config, "workerinput", {})
    worker = workerinput.get("workerid", "controller")
    created = int(workerinput.get("workercount", 0) or 0) or int(
        getattr(config.option, "numprocesses", 0) or 0
    )
    target = pathlib.Path(counts_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / str(worker)).write_text(
            f"workers={created}\n"
            f"in_scope={in_scope}\n"
            f"always_on={always_on}\n"
            f"tests_only_tests={tests_only_tests}\n"
            f"always_on_modules={always_on_modules}\n"
            f"importers={importer_modules}\n"
            f"selected={selected}\n"
            f"deselected={deselected}\n"
            f"own={','.join(sorted(own_apps)) or '-'}\n"
            f"scope={','.join(sorted(scope_apps)) or '-'}\n"
            f"tests_only={','.join(sorted(tests_only)) or '-'}\n"
            f"always_on_dropped_whole={always_on_dropped_whole}\n"
            # THE MAP'S OWN LINE, so a stale entry reaches the log under `-n`
            # too: the controller collects nothing and prints this file.
            + (f"{DJB_IMPACT_FIELD}={impact_line}\n" if impact_line else "")
            # THE ALWAYS-ON SET BY MODULE, one line each, so the leg that runs
            # under `-n` — whose controller collects nothing — prints the same
            # enumeration the serial report does. Sorted, so every collector's
            # file stays byte-identical to its siblings'.
            + "".join(
                f"{DJB_ALWAYS_ON_FIELD}={module} {way}\n"
                for module, way in sorted((always_on_ways or {}).items())
            ),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - the caller turns absence into 2
        raise pytest.UsageError(
            f"the --loop scope could not write its counts file into {counts_dir} "
            f"({exc}). The banner reconciles those files; a missing one is a "
            "collector whose scope nobody can read."
        ) from exc


def pytest_report_collectionfinish(config: pytest.Config) -> list[str]:
    return list(_DJB_TIER_REPORT)


# --- the PRE-RUN banner, and why it can exist at all --------------------------
#
# The counts are known only once something has COLLECTED, and under xdist the
# WORKERS collect — which is why this banner used to print after the run, beside
# the verdict, where a reader asking "did it even run my test?" had already
# waited for the whole leg to find out.
#
# THE ORDERING IS A FACT, NOT A BET. A worker writes its counts file in
# `pytest_collection_modifyitems` (above); pytest runs that BEFORE
# `pytest_collection_finish`, which is what sends the worker's `collectionfinish`
# event (xdist/remote.py:236,257). The controller answers that event in
# `worker_collectionfinish`, whose FIRST act is to call
# `pytest_xdist_node_collection_finished` (xdist/dsession.py:287) — so the file
# this reads is complete — and which schedules no test at all until EVERY node
# has reported (`sched.collection_is_completed`, :297-305). Waiting for the last
# node therefore still lands before the first test runs, and it is what lets the
# banner say `reconciled across N collectors` and mean it.
#
# RECONCILE, NEVER SUM, here as in the after-run banner: every collector
# performs its own full collection, so the files must be identical. A
# disagreement is `scripts/check.sh`'s refusal (exit 2) and NOT a second one
# here — a banner that refused would refuse before the leg it is describing.
_DJB_PRERUN_NODES: set[str] = set()
_DJB_PRERUN_PRINTED: list[bool] = [False]


def _djb_prerun_banner(config: pytest.Config, counts_dir: str, collectors: int) -> None:
    """Print one line per selection decision, before the first test runs."""
    _DJB_PRERUN_PRINTED[0] = True
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:  # pragma: no cover - -p no:terminal
        return
    try:
        files = sorted(path for path in pathlib.Path(counts_dir).iterdir() if path.is_file())
        texts = {path.read_text(encoding="utf-8") for path in files}
    except OSError:  # pragma: no cover - the after-run reconciliation is the refusal
        return
    if not texts:
        return
    if len(texts) > 1:
        reporter.write_line(
            "scope   THE COLLECTORS DISAGREE — the counts are not printed here; "
            "the after-run reconciliation in scripts/check.sh is the refusal."
        )
        return
    fields = dict(line.split("=", 1) for line in next(iter(texts)).splitlines() if "=" in line)
    if fields.get(DJB_IMPACT_FIELD):
        # THE MAP'S LINE FIRST, and on every shape of run below: a stale map
        # entry is a fact about the selection whatever the tier said.
        reporter.write_line(f"scope   {fields[DJB_IMPACT_FIELD]}")
    if str(config.getoption("--djb-tier")) == "all" and not bool(
        config.getoption("--djb-scope-narrow")
    ):
        # THE WHOLE-SUITE LINE. Under the full gate — and under a `--pr` whose
        # scope narrowed nothing — there is no scope to describe: every
        # collector collected the tree. The one thing in question is the one
        # this says, before the first test runs: how many collectors reported.
        # The after-run reconciliation in `scripts/check.sh` is the refusal;
        # this is its pre-run half, and the counts-dir plumbing is shared.
        reporter.write_line(f"collectors: {collectors} of {collectors} reported (the whole suite)")
        return
    lines: list[str] = []
    labels = fields.get("tests_only", "-")
    if labels and labels != "-":
        lines.append(
            f"scope   tests-only: {labels.replace(',', ', ')} — their test trees at the "
            "FAST tier, the edited module(s) whatever tier they are in, and every "
            "collected module naming one of those test packages; NO closure walked"
        )
        lines.append(
            f"scope   importers: {fields.get('importers', '?')} module(s) outside those "
            "test trees name one of those test packages (derived from the modules' own "
            "source, never a list)"
        )
    lines.append(
        f"scope   always-on: {fields.get('always_on', '?')} test(s) in "
        f"{fields.get('always_on_modules', '?')} module(s) — the cross-app tripwires, "
        "floors met"
    )
    listed = [
        line.split("=", 1)[1]
        for line in next(iter(texts)).splitlines()
        if line.startswith(f"{DJB_ALWAYS_ON_FIELD}=")
    ]
    ways = dict(entry.split(" ", 1) for entry in listed)
    lines.append(
        "scope   "
        + _always_on_headline(
            ways,
            int(fields.get("always_on_modules", "0") or 0),
            int(fields.get("always_on_dropped_whole", "0") or 0),
        )
    )
    lines += [f"scope     {entry}" for entry in listed]
    lines.append(
        f"scope   selected {fields.get('selected', '?')} · deselected "
        f"{fields.get('deselected', '?')}    (reconciled across {collectors} collectors)"
    )
    for line in lines:
        reporter.write_line(line)


def pytest_xdist_node_collection_finished(node: Any, ids: Any) -> None:
    """The controller's seam — the only place the counts exist before the run."""
    config = getattr(node, "config", None)
    if config is None or _DJB_PRERUN_PRINTED[0]:
        return
    counts_dir = str(config.getoption("--djb-scope-counts", "") or "")
    if not counts_dir:
        return
    gateway = getattr(node, "gateway", None)
    _DJB_PRERUN_NODES.add(str(getattr(gateway, "id", None) or len(_DJB_PRERUN_NODES)))
    expected = int(getattr(config.option, "numprocesses", 0) or 0)
    if expected and len(_DJB_PRERUN_NODES) < expected:
        return
    _djb_prerun_banner(config, counts_dir, max(len(_DJB_PRERUN_NODES), 1))


def pytest_collection_finish(session: pytest.Session) -> None:
    """The serial seam. Under xdist the controller collects nothing and the hook
    above is the one that fires; this is the `-p no:xdist` / `-n 0` path, and the
    one the drives' `--collect-only` invocations take."""
    config = session.config
    if hasattr(config, "workerinput") or _DJB_PRERUN_PRINTED[0]:
        return
    if int(getattr(config.option, "numprocesses", 0) or 0) > 0:
        return
    counts_dir = str(config.getoption("--djb-scope-counts", "") or "")
    if not counts_dir:
        return
    _djb_prerun_banner(config, counts_dir, 1)


# --- the test databases come down clean ---------------------------------------
#
# The defect, named. `sync_to_async(fn)` with asgiref's default
# `thread_sensitive=True`, called with no surrounding `ThreadSensitiveContext`,
# runs `fn` on `asgiref.sync.SyncToAsync.single_thread_executor` — ONE
# `ThreadPoolExecutor(max_workers=1)` built as a class attribute at import and
# never shut down (asgiref 3.12.1, `asgiref/sync.py:409`; its thread is the one
# called `ThreadPoolExecutor-0_0`). A database call made there opens a
# connection in that thread and nothing ever closes it: there is no request
# cycle to fire `close_old_connections`, `CONN_MAX_AGE = 0` only decides what
# happens when something DOES check, and the thread outlives every test in the
# process. At the end of the session pytest-django asks Postgres to drop the
# worker's test database, Postgres answers `database "test_<name>_gwN" is being
# accessed by other users`, and pytest-django turns that into a WARNING and
# carries on — so the run stays green and the database stays on disk, per
# checkout, silently, forever.
#
# Reproduced deterministically at rung time by the one test
# `test_an_emitted_event_arrives_on_a_connected_socket`
# (`apps/realtime/tests/test_spine_end_to_end.py`) run alone: its last act is a
# bare `sync_to_async(...objects.get)`, so the pool thread's connection is still
# open when the drop is attempted.
#
# Why the fix is here and not at the call sites. Closing the call sites would
# close today's holder and nothing else; the class comes back with the next
# pool, the next `sync_to_async`, the next library that keeps a thread. This
# closes it where the drop happens, once, for every holder.


def _close_connections_in_persistent_pools() -> None:
    """Close what asgiref's long-lived worker threads still hold.

    Asked of each pool *from inside the pool*, so Django's own bookkeeping does
    the closing (`connections.close_all()` is thread-local, which is exactly
    why the connection could not be reached from here in the first place).
    Reached by attribute rather than by import path because these are asgiref's
    internals: if a future asgiref renames them the net below still holds.
    """
    pools: list[ThreadPoolExecutor] = []
    single = getattr(SyncToAsync, "single_thread_executor", None)
    if isinstance(single, ThreadPoolExecutor):
        pools.append(single)
    for holder in (SyncToAsync, AsyncToSync):
        # Per-`ThreadSensitiveContext` pools. Weak-keyed, so listed before use.
        by_context = getattr(holder, "context_to_thread_executor", {})
        pools.extend(
            pool for pool in list(by_context.values()) if isinstance(pool, ThreadPoolExecutor)
        )
    for pool in pools:
        try:
            pool.submit(connections.close_all).result(timeout=30)
        except RuntimeError:
            # Already shut down: its threads are gone and so are their sockets.
            continue


def _terminate_strays_on_this_workers_database() -> int:
    """The net: hang up on anything still connected to OUR test database.

    Scoped to `current_database()`, which under `-n auto` is this worker's own
    `test_<DATABASE_NAME>_gwN` and under a serial run this checkout's own
    `test_<DATABASE_NAME>` — a name no other checkout and no other worker can
    reach (`scripts/db.sh`). So this cannot touch a neighbour's live database,
    which is the hazard a broad sweep would be.

    It returns the count rather than swallowing it: a stray that survives the
    close above is a holder nobody has diagnosed yet, and the caller says so out
    loud instead of leaving the next reader a mystery.
    """
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.vendor != "postgresql":
        return 0
    others = "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) {others}")
        row = cursor.fetchone()
        strays = int(row[0]) if row else 0
        if strays:
            cursor.execute(f"SELECT pg_terminate_backend(pid) {others}")
    return strays


# --- what this fixture costs, and where the lever for it is (V1-c) -----------
#
# MEASURED, not estimated (V1-c, ten-core laptop, 2026-08-24). Under `-n auto`
# every xdist worker creates and migrates its OWN `test_<DATABASE_NAME>_gwN`,
# and pytest's own `--durations` report shows the bill as exactly ten setup
# entries of ~5.5–6.2s, one per worker, charged to whichever test happened to
# ask for a database first. That is ~57 CPU-seconds per pass, and ~5.7s of it
# is on EVERY worker's critical path — a floor the per-rung leg cannot get
# under by running fewer tests, and a floor the FULL gate pays twice.
#
# THE LEVER IS NOT HERE, and this note exists so the next reader does not go
# looking for it here. `--reuse-db` would remove the cost and is refused: a
# reused database is not re-migrated, so a rung that adds a migration would test
# against a stale schema in silence, which is a correctness hole bought with
# seconds. **THE SEAM IS A TEMPLATE**: Django's Postgres backend issues
# `CREATE DATABASE … WITH TEMPLATE …` when the connection's
# `TEST["TEMPLATE"]` is set, so a migrated template — which is V1-b's subject in
# `scripts/db.sh` — turns each worker's migrate into a file copy. One line, in
# `config/settings/test.py`, pointed at whatever name V1-b derives. Nothing here
# needs to change for it.


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup: None, django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    """pytest-django's database setup, with the connections released after it.

    An override that REQUESTS the fixture it overrides, which is what puts this
    teardown in the right place: a fixture set up after `django_db_setup` is
    finalised before it, so this runs while the test databases still exist and
    before the drop is attempted.
    """
    yield
    _close_connections_in_persistent_pools()
    with django_db_blocker.unblock():
        strays = _terminate_strays_on_this_workers_database()
    if strays:
        warnings.warn(
            f"{strays} connection(s) to this worker's test database outlived the suite and were "
            "terminated so it could be dropped. A thread pool is holding a Django connection "
            "past teardown and apps/conftest.py does not know about it — find the holder's "
            "class, do not widen this net.",
            stacklevel=2,
        )


# --- the ephemeral Temporal test servers come down clean too ------------------
#
# THE DEFECT, NAMED. `WorkflowEnvironment.start_time_skipping()` spawns a real
# `temporal-test-server` binary as a CHILD OF THIS PROCESS, and every call site
# in this repository already uses it as an async context manager, so the happy
# path shuts it down — a full green `-n auto` pass leaks nothing, measured. What
# breaks is what happens when two of them are handed one port, and all three
# steps below were MEASURED on this machine rather than reasoned about:
#
#   1. THE LOSER OF A COLLISION NEVER EXITS. Two servers on one port: the second
#      dies in `main` with `java.io.IOException: Failed to bind to address
#      0.0.0.0/0.0.0.0:<port>` / `java.net.BindException: Address already in
#      use` out of grpc-netty — the trace that failed a push at
#      `apps/workflows/tests/test_context.py` — but its netty event-loop thread
#      is not a daemon, so the PROCESS WEDGES: alive, listening on nothing,
#      ~24 MB resident, immortal. Launched against an occupied port it was
#      still running at t+30s with `rc=None`.
#   2. THE CALLER IS NOT TOLD. The loser's `start_time_skipping()` RETURNS
#      SUCCESSFULLY in 0.1s, because the health check reaches the port and the
#      WINNER answers it. The test then runs against another xdist worker's
#      Temporal server without either of them knowing — which is what a burst
#      of unreproducible workflow failures in one pass looks like from outside.
#   3. IT NEVER TIMES OUT. When the thing answering the port is not a Temporal
#      server at all, the start waits FOREVER — no timeout of any kind (killed
#      at 120s). A run aborted in that state leaves the child behind, and a
#      child whose pytest parent is gone is reparented to pid 1 and survives
#      for days: the specimen found on this machine had been up 21 minutes with
#      no listener and the netty boss thread parked, which is step 1's state
#      exactly, and is E1's eleven strays.
#
# A HYPOTHESIS THAT DID NOT SURVIVE, recorded so nobody spends the afternoon on
# it again: the SDK probes the LOOPBACK for a free port and the server binds the
# WILDCARD, and `bind(("127.0.0.1", P))` with SO_REUSEADDR — which is what
# Rust's `std::net::TcpListener::bind` sets — DOES succeed while a server holds
# P on the wildcard. It looked like the whole story. It is not: the kernel's
# ephemeral allocator does not hand out a wildcard-held port even to that
# socket. Measured against 400 held ports: 0/400 collisions from an SDK-shaped
# probe, 0/400 from a wildcard one. Reserving the port here would therefore buy
# nothing, so this does not do it — the residual window is between the probe
# closing and the server binding, and no probe can close that.
#
# WHY THE FIX IS HERE. There are ~60 `async with await
# WorkflowEnvironment.start_time_skipping()` call sites across seven apps and
# every one of them is already correct. What is wrong is what the SDK does when
# a start goes sideways, so this wraps the ONE function they all resolve
# through: the start is bounded instead of infinite, the environment it returns
# is checked to be OURS before a test is allowed to trust it, and anything left
# running is this process's own child and is reaped as one.
#
# WHAT THIS DELIBERATELY DOES NOT DO: share one environment per worker. Time
# skipping is global to an environment (the SDK's own docstring says so),
# workflow ids here are deterministic by house rule 18 — `test_context.py`
# starts `acme:workflows:parent:seen` by name — and pytest-randomly reorders
# every run, so a shared server would make each test's clock and id space
# depend on whichever test happened to run before it. That is precisely the
# coupling the one-seed two-pass gate leg exists to catch, bought for a few
# seconds of wall time.

_TEST_SERVER = "temporal-test-server"

# The predicate the collision check actually applies, in words, in ONE place so
# that both refusals below say the same true thing. It is per-START-
# CHILD and not per-process: `_the_server_answering_is_ours` asks whether the
# listener is a process THIS start spawned, and the honest answer against an
# environment this same pytest process started a minute ago is "no". The text
# used to say "another process", which is correct for the xdist collision it was
# written against and flatly false for the same-process one — and sent whoever
# read it hunting for a sibling that was never there.
_NOT_THIS_STARTS_CHILD = "something that is not this start's child"

# The census's own budget, and the sentence it says when it runs out.
# Ten seconds is not a guess about how long `ps -A` takes — it takes
# milliseconds — it is the line past which the only remaining explanations are
# a wedged kernel table or a machine so loaded that the suite's answer is
# worthless either way. Both are worth a red.
_PS_SECONDS = 10.0
_PS_HUNG = (
    f"the `ps -Ao pid=,ppid=,args=` census in `_test_server_children` did not answer within "
    f"{_PS_SECONDS:.0f}s. Without this timeout, the call is unbounded work inside an "
    "autouse fixture: it once froze the whole gate at 96% with every "
    "xdist worker at 0% CPU and nothing said why. The suite cannot tell whether a Temporal test "
    "server leaked, so it refuses rather than reporting a census it could not take — "
    "`scripts/temporal_sweep.sh` is the census to run by hand, and a machine this loaded should "
    "not be running a gate."
)

# A cold checkout downloads a 64 MB binary INSIDE the first start, so the first
# attempt in a process gets a download-sized budget and later ones do not. Any
# finite number beats what is there now, which is no timeout at all (step 3
# above): the hang is what orphans the child when the run is eventually killed.
_FIRST_START_SECONDS = 300.0
_LATER_START_SECONDS = 60.0
_START_ATTEMPTS = 3

_a_start_has_finished_here = False
"""Whether a start has already FINISHED in this process.

Which is what decides which of the two budgets above a named-port start gets:
the download happens inside the first start and nowhere else. The unnamed
branch reads the same fact off its own attempt counter; the named branch gets
ONE attempt (a caller that named a port meant that port), so it reads it here.

**FINISHED, not SUCCEEDED — and the gap is deliberate.** This is set in
`_bounded_start` the moment `original(**kwargs)` RETURNS, which includes a start
whose environment is thrown away a few lines later as a collision: that start
still went out to the network and still unpacked the 64 MB binary if this
checkout was cold, so the next start will not pay for that again and must not be
given a download-sized budget as though it might. The question the name asks is
"has a start run to completion in this process", not "did one work", and 60 s
rather than 300 s is the right answer to it either way.

A start that was CANCELLED, or that ran out its budget, does NOT set it —
neither of those finished, and neither of them is known to have completed the
download. So the flag only ever moves in the direction that is safe to be wrong
about: it is never True before a start has done the expensive part.
"""

# Servers THIS process started and has not yet seen exit, and whether the test
# now running asked for one at all. Per process, so each xdist worker keeps its
# own and never reasons about a sibling's.
_servers_started_here: set[int] = set()
_a_server_was_started_this_test = False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _test_server_children() -> set[int]:
    """The `temporal-test-server` processes whose parent is THIS process.

    The parentage is the whole safety argument, and it is the same shape as
    `scripts/db_sweep.sh`'s refusals: a peer agent's live worker in another
    checkout is a child of ITS pytest process, never of ours, so nothing here
    can reach it however loaded the machine is.

    Matched on the EXECUTABLE — the first argv token's basename — never on a
    command line that merely mentions the name, which is the difference between
    a census and a `grep` that counts itself.

    **The reaper cannot be allowed to hang the reaper.** This `ps` is
    called from an autouse fixture, so every test in the suite passes through
    it; without a timeout it is an unbounded wait inside test teardown, and on
    2026-08-24 that is exactly what it became — the merge gate sat 22+
    minutes at 96% with every xdist worker at 0% CPU because this call never
    returned (macOS, machine under two concurrent full suites). A `ps -A` that
    has not answered in ten seconds is not slow, it is stuck, so the wait is
    bounded and the refusal is LOUD: `RuntimeError` naming the call and the
    budget, which surfaces as an errored fixture with a sentence a reader can
    act on. Never a silent `set()` — a census that answers "no children" when
    it could not look is how a leaked server becomes invisible, which is the
    same failure shape this helper exists to prevent.
    """
    try:
        listing = subprocess.run(
            ["ps", "-Ao", "pid=,ppid=,args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=_PS_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        raise RuntimeError(_PS_HUNG) from expired
    ours = str(os.getpid())
    found: set[int] = set()
    for line in listing.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) < 3 or fields[1] != ours:
            continue
        if os.path.basename(fields[2].split()[0]).startswith(_TEST_SERVER):
            found.add(int(fields[0]))
    return found


def _the_server_answering_is_ours(children: set[int], port: int) -> bool:
    """Is the process serving `port` the child this start just spawned?

    This is the collision detector, and it is the whole of step 2 in the header:
    a losing start returns a client pointed at a server IT DID NOT SPAWN and
    says nothing. Asking who actually holds the listening socket separates the
    two cases exactly — measured on a forced collision, the winner's child came
    back as the holder and the loser's child came back holding nothing.

    The question is per START, not per process, and the difference is not
    academic: the winner may be another xdist worker's server, or it may be an
    environment THIS process started earlier and has not shut down. Both are
    equally fatal to a caller that wanted its own clock, both answer False
    here, and `_NOT_THIS_STARTS_CHILD` is the sentence both refusals say.

    Answers TRUE whenever it cannot tell: no child could be attributed to this
    start (the `ps` scan and the spawn raced), or there is no `lsof` on the
    machine. A start that worked must never be thrown away because the check
    was blind.
    """
    if not children:
        return True
    for pid in children:
        try:
            held = subprocess.run(
                ["lsof", "-nP", "-a", "-p", str(pid), f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return True  # no lsof: unknowable, and unknowable is not guilty
        if held.stdout.strip():
            return True
    return False


def _port_of(environment: Any) -> int | None:
    """The port the returned environment is actually talking to, or None."""
    try:
        target = str(environment.client.service_client.config.target_host)
        return int(target.rsplit(":", 1)[1])
    except (AttributeError, ValueError, IndexError):
        return None


def _reap(pids: set[int]) -> None:
    """Stop test servers this process started. TERM, then KILL what ignores it.

    A wedged loser has already lost its `main` thread, so TERM is the courtesy
    and KILL is the guarantee.
    """
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        alive = {pid for pid in pids if _alive(pid)}
        if not alive:
            return
        for pid in alive:
            try:
                os.kill(pid, signal_number)
            except (ProcessLookupError, PermissionError):
                continue
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and any(_alive(pid) for pid in alive):
            time.sleep(0.05)


async def _bounded_start(original: Any, kwargs: dict[str, Any], *, budget: float) -> Any:
    """Await ONE start under a finite budget, reaping the child a cancel strands.

    This is the only place `original` is awaited, and that is the whole of it.
    Both branches below want the same three things — a bound, a reap on cancel,
    and the note that a start has now finished in this process — and when each
    branch kept its own copy, only one of them ended up with the bound: on the
    same plain TCP occupant, the unnamed branch ended each attempt at its
    declared budget while the named branch was still waiting past 75 s, when the
    verifier's own timeout ended it — with the header above
    claiming both were bounded. One copy cannot drift from itself.

    `TimeoutError` comes back out as itself, because the two callers mean
    different things by a budget that ran out — a named port that nothing
    answers on is refused, an unnamed one is retried onto another port — and the
    caller is the one that knows which. `CancelledError` is re-raised after the
    reap: a cancel is not ours to swallow, but the child is ours to bury, and it
    is orphaned the moment this process goes.
    """
    global _a_start_has_finished_here

    before = _test_server_children()
    try:
        async with asyncio.timeout(budget):
            environment = await original(**kwargs)
    except asyncio.CancelledError:
        # `asyncio.timeout` turns its OWN expiry into `TimeoutError` on the way
        # out, so a `CancelledError` reaching here came from outside: somebody
        # cancelled the task that is starting a server. Reap and re-raise.
        _reap(_test_server_children() - before)
        raise
    # FINISHED, not succeeded: the caller above may still refuse this
    # environment as a collision, and the download happened all the same. The
    # flag's own docstring is where that is argued (N106b).
    _a_start_has_finished_here = True
    return environment


@pytest.fixture(scope="session", autouse=True)
def _temporal_test_servers_are_ours_to_clean_up() -> Iterator[None]:
    """Wrap the one call every workflow test makes, for the whole session.

    Session-scoped and not per-test: the wrapper has to be in place for the
    first workflow test whatever order pytest-randomly picks, and the class
    attribute is the single thing all ~60 call sites resolve through.
    """
    from temporalio.testing import WorkflowEnvironment

    original = WorkflowEnvironment.start_time_skipping

    async def start_time_skipping(**kwargs: Any) -> Any:
        global _a_server_was_started_this_test
        _a_server_was_started_this_test = True
        named_port = kwargs.get("port")
        if named_port is not None:
            # A caller that named a port meant THAT port, so a collision here
            # is not retried onto another one — it is refused. Silently handing
            # back a server this start did not spawn is the one answer that is
            # never right, whoever fathered it.
            before = _test_server_children()
            budget = (
                _FIRST_START_SECONDS if not _a_start_has_finished_here else _LATER_START_SECONDS
            )
            try:
                environment = await _bounded_start(original, kwargs, budget=budget)
            except TimeoutError:
                # NOTHING ANSWERED — a different fact from the collision below,
                # and it gets its own sentence because the reader's next move is
                # different. Something holds this port without speaking Temporal
                # (a plain listener, a wedged loser, a foreign service), so the
                # SDK's health probe waits for an answer that is never coming.
                # Unbounded, that is a hang that ends only when somebody kills
                # the run — and a killed run is exactly what reparents the child
                # to pid 1 and leaves it there for days (step 3 in the header).
                _reap(_test_server_children() - before)
                raise RuntimeError(
                    f"nothing answered as a Temporal server on port {named_port} within "
                    f"{budget:g}s, so this start could never have finished. Something "
                    "holds that port without speaking Temporal; anything this start spawned "
                    "has been reaped. Ask for a port nothing holds, or ask for none and let "
                    "one be chosen."
                ) from None
            ours = _test_server_children() - before
            port = _port_of(environment)
            if port is not None and not _the_server_answering_is_ours(ours, port):
                try:
                    await environment.shutdown()
                except Exception:  # noqa: BLE001 — the reap below is the guarantee
                    pass
                _reap(ours)
                raise RuntimeError(
                    f"port {port} is already served by {_NOT_THIS_STARTS_CHILD}, so this "
                    "environment would have driven a Temporal server this start did not "
                    "spawn — a sibling worker's, or one this same process started "
                    "earlier; either way the clock and the workflow-id space would be "
                    "shared. Our own server lost the bind and has been reaped; ask for a "
                    "port nothing holds, or ask for none and let one be chosen."
                )
            _servers_started_here.update(ours)
            return environment

        failures: list[str] = []
        for attempt in range(1, _START_ATTEMPTS + 1):
            before = _test_server_children()
            budget = _FIRST_START_SECONDS if attempt == 1 else _LATER_START_SECONDS
            try:
                environment = await _bounded_start(original, kwargs, budget=budget)
            except Exception as exc:
                _reap(_test_server_children() - before)
                failures.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                continue

            ours = _test_server_children() - before
            port = _port_of(environment)
            if port is not None and not _the_server_answering_is_ours(ours, port):
                # The collision, caught where the SDK stays silent: this start
                # was handed another worker's server, and OUR child is the
                # wedged loser. Both go, and the next attempt takes a new port.
                try:
                    await environment.shutdown()
                except Exception:  # noqa: BLE001 — the reap below is the guarantee
                    pass
                _reap(ours)
                failures.append(
                    f"attempt {attempt}: port {port} was already served by "
                    f"{_NOT_THIS_STARTS_CHILD} — our own server lost the bind and was reaped"
                )
                continue

            _servers_started_here.update(ours)
            return environment

        raise RuntimeError(
            f"no time-skipping Temporal test server of our own would start in {_START_ATTEMPTS} "
            "attempts. Every attempt was bounded, checked to be serving OUR child, and reaped "
            "before the next, so nothing was left behind by this call: " + " | ".join(failures)
        )

    patch = pytest.MonkeyPatch()
    patch.setattr(WorkflowEnvironment, "start_time_skipping", staticmethod(start_time_skipping))
    try:
        yield
    finally:
        patch.undo()
        # The last word for this worker: whatever it started and did not stop
        # dies with it, rather than reparenting to launchd and living for days.
        _reap(_test_server_children())


@pytest.fixture(autouse=True)
def _no_test_server_outlives_the_test_that_started_it() -> Iterator[None]:
    """The invariant, checked where it is cheap to check.

    Every call site owns its environment for the length of one test, so at the
    end of a test this process should own ZERO test-server children. Anything
    still running is a leak; it is reaped and SAID OUT LOUD, because a silent
    broom would hide the next holder exactly as a silent warning does.

    The check is by PARENTAGE and not by the pids the wrapper recorded, so it
    also catches a server this process fathered without going through the
    wrapper at all — which is the one the wrapper can never know about. Only a
    test that asked for a server pays for it: the ~1300 tests that never touch
    Temporal read one boolean and stop.
    """
    global _a_server_was_started_this_test
    yield
    if not _a_server_was_started_this_test:
        return
    _a_server_was_started_this_test = False
    # A `shutdown()` that has just returned may still be reaping its child, so
    # the ordinary case gets a moment before it is called a leak. `_alive` on
    # the recorded pids first, because it costs no process at all.
    deadline = time.monotonic() + 2.0
    known = {pid for pid in _servers_started_here if _alive(pid)}
    while known and time.monotonic() < deadline:
        time.sleep(0.05)
        known = {pid for pid in known if _alive(pid)}
    _servers_started_here.clear()
    strays = _test_server_children()
    if strays:
        _reap(strays)
        warnings.warn(
            f"{len(strays)} ephemeral Temporal test server(s) outlived the test that started "
            "them and were reaped. The `async with` around "
            "WorkflowEnvironment.start_time_skipping() did not run its exit — find out why "
            "before widening this net; scripts/temporal_sweep.sh is the census.",
            stacklevel=2,
        )


# --- registry integrity: no module leaves the real models' relations rewritten --
#
# A model built in a throwaway registry writes its reverse-relation graph onto
# the REAL classes that registry holds (`apps/core/tests/isolation.py` has the
# mechanism), and nothing expires it on the way out. The damage surfaces in
# whichever unrelated test next recomputes a real model's field map, on
# whichever worker, under whichever seed — `FieldError: Cannot resolve keyword
# 'memberships'` a thousand tests away from the module that caused it. Or it
# surfaces nowhere: a fixture that happens to define a related model expires the
# poisoned tree first, and the suite is green over a registry that was wrong.
#
# So the PROPERTY is tested, not a spelling: every real model's field names are
# snapshotted once per session and recomputed at every test MODULE's teardown,
# and a difference fails THAT module, naming the model and the field. Every road
# that rewrites the registry is caught — `isolate_apps` under any import alias,
# a hand-built `Apps`, a model defined mid-run with a relation to a real one —
# because the guard reads the result, never the road. The source census
# (`apps/core/tests/test_isolation_discipline.py`) closes the common spelling
# cheaply; this is the net behind it.
#
# What the recompute does and does not disturb: it resets each model's
# `get_fields()` memo ONLY (`_expire_cache(forward=False, reverse=False)`), so
# the answer is rebuilt from `_relation_tree` AS FOUND — expiring the tree too,
# or letting another model's rebuild overwrite it first, would rebuild it from
# the real registry and heal the very poison it is looking for (measured: the
# first version of this guard read `core.Tenant` before `accounts.User`, and
# Tenant's expired tree rebuilt User's). After a failure the guard heals
# (`apps.clear_cache()`), so one poisoner is one red, not a cascade through
# every module the worker runs next.
#
# DOES NOT COVER: a rewrite that a later statement in the SAME module repairs
# before the module ends (nothing is left to find, and nothing is left to harm);
# a rewrite confined to a model's forward fields that leaves `get_fields()` names
# unchanged (a field swapped for a same-named one); a model that is not in the
# global registry at all (an isolated registry's own planted models, which die
# with it). A model defined into the GLOBAL registry mid-run that changes no
# real model's field names — a proxy defined bare in a test body, measured: it
# added a `<kind>.read` key to every registry census that ran after it on that
# worker — IS covered: a label the session did not start with is a red naming
# it (`joined the registry`), and the heal takes it back out. The granularity
# is the MODULE, like every other finding here: the red names the module whose
# teardown found the class, never the test function inside it that defined it.
#
# The two readers (`registry_field_names`, `registry_difference`) live in
# `apps/core/tests/isolation.py`, beside the drop-in they back, so the guard's
# canary in core's own tests can import them without importing this file.


@pytest.fixture(scope="session")
def _djb_registry_at_session_start() -> dict[str, tuple[str, ...]]:
    """The real registry's field names, before any test module ran."""
    return registry_field_names()


@pytest.fixture(scope="module", autouse=True)
def _no_module_rewrites_the_real_registry(
    request: pytest.FixtureRequest, _djb_registry_at_session_start: dict[str, tuple[str, ...]]
) -> Iterator[None]:
    """Fail the MODULE that left a real model's relations rewritten, by name."""
    yield
    after = registry_field_names()
    moved = registry_difference(_djb_registry_at_session_start, after)
    if not moved:
        return
    from django.apps import apps as global_apps

    from apps.core import authz

    for label in set(after) - set(_djb_registry_at_session_start):
        app_label, _, name = label.partition(".")
        global_apps.all_models[app_label].pop(name.lower(), None)
    global_apps.clear_cache()
    authz.reset_policies()  # the kind registry is cached; a joiner may be in it
    # Re-read after the heal, so a damage the heal cannot undo (a model that
    # left) is reported once, by the module that did it, and not again by
    # every module this worker runs next.
    healed = registry_field_names()
    for label in list(_djb_registry_at_session_start):
        if label in healed:
            _djb_registry_at_session_start[label] = healed[label]
        else:
            del _djb_registry_at_session_start[label]
    pytest.fail(
        f"REGISTRY REWRITTEN by {request.node.nodeid}: the real models' field names "
        "differ from the session's start after this module ran —\n    "
        + "\n    ".join(moved)
        + "\n  A model built in a throwaway registry wrote its relation graph onto a "
        "real class and nothing expired it, or a model class defined in a test body "
        "joined the real registry and nothing took it out. Build it under "
        "`apps.core.tests.isolation.isolated_apps`, which keeps the class out of the "
        "real registry and rebuilds every real model's relation caches on the way out. "
        "(The registry was healed after this report, so no other module reds for it.)",
        pytrace=False,
    )


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    """No test inherits the last one's ambient context.

    `contextvars` are per-task and pytest runs every test on the same one, so a
    test that drives a middleware directly (rather than through the client)
    would otherwise leave `tenant_id` and `door` bound for whatever runs next —
    and a test that passes because of the previous test is worse than one that
    fails.
    """
    context.clear()
    yield
    context.clear()


@pytest.fixture(autouse=True)
def _no_dialling_temporal(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches a Temporal server it did not start itself.

    `start_workflow_on_commit` registers an `on_commit` hook that builds a
    client from settings and starts a durable run. In a `transaction=True` test
    that commit is real, so the hook fired against the **development server**:
    the cycle-0 verifier measured twenty executions leaked per gate run and 275
    stuck RUNNING, each one a worker somewhere retrying an activity against a
    row that only ever existed inside a test (queue V3).

    Making it impossible rather than discouraged is the point. The factory is
    replaced with one that refuses and says what to do instead; a test that
    genuinely needs a server starts its own time-skipping
    `WorkflowEnvironment` and points the factory at *that*, which is the
    existing per-module pattern (`apps/example/tests/test_workflows.py`,
    `apps/workflows/tests/test_services.py`) and is now also the opt-in: their
    `monkeypatch.setattr` runs inside the test body, after this fixture, and
    replaces the refusal.

    `config/settings/test.py` points `TEMPORAL_ADDRESS` at a dead port as the
    second layer, for anything that builds a client without going through here.
    """
    from apps.workflows import client as workflow_client

    async def refuse(*args: object, **kwargs: object) -> object:
        raise RuntimeError(
            "tests must not dial Temporal — use the time-skipping env or monkeypatch start"
        )

    monkeypatch.setattr(workflow_client, "get_client", refuse)


@pytest.fixture
def recorded_workflow_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit work that starts a workflow, without a Temporal server.

    The opt-in for a `transaction=True` test whose subject is **not** the
    workflow — a service that happens to call `start_workflow_on_commit`, an
    `emit()` whose dispatch is proved elsewhere. The `WorkflowRun` row is still
    written in the caller's transaction and the `on_commit` hook still fires;
    what does not happen is the client call at the end of it.

    A test whose subject *is* the workflow does the other thing instead: it
    starts a time-skipping `WorkflowEnvironment` and points the factory at it
    (`apps/example/tests/test_workflows.py`, `apps/workflows/tests/test_services.py`),
    which proves the start rather than skipping it. Pick by what the test is
    about; neither of them reaches the development server.

    The seam is `run_async`, which is the one thing the on-commit hook does
    that a test cannot want: give the client call its own event loop. Everything
    above it — the id check, the `WorkflowRun` row, the hook being registered on
    the right transaction — still runs, so what this skips is exactly the dial.
    """
    from apps.workflows import services as workflow_services

    def do_not_dispatch(_coroutine_factory: Callable[[], Any]) -> None:
        return None

    monkeypatch.setattr(workflow_services, "run_async", do_not_dispatch)


@pytest.fixture
def api() -> Client:
    return Client()


@pytest.fixture
def tenant(db: None) -> Tenant:
    return create_tenant(name="Acme", slug="acme", actor=system_actor())


@pytest.fixture
def other_tenant(db: None) -> Tenant:
    return create_tenant(name="Globex", slug="globex", actor=system_actor())


@pytest.fixture
def root_org(tenant: Tenant) -> Organization:
    """The tenant's root node — made by `create_tenant`, never by a test."""
    return root_organization(tenant=tenant)


@pytest.fixture
def other_root_org(other_tenant: Tenant) -> Organization:
    return root_organization(tenant=other_tenant)


@pytest.fixture
def owner(tenant: Tenant) -> User:
    """The tenant's owner, said out loud.

    `add_membership` defaults the *first* membership of a tenant to `owner` and
    everybody after it to `member` (`core.services`), which is the right
    default for a product and the wrong one for a fixture: whether this user
    came out an owner would depend on whether a test happened to ask for
    `member` or `admin_member` first, and pytest builds fixtures in the order a
    signature names them. A test that passes because of its argument order is a
    test nobody can move. So every fixture here names its role, and the default
    keeps its own test (`core/tests/test_authz.py`) instead of being proved by
    accident here.
    """
    user = create_user(email="owner@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def stranger(other_tenant: Tenant) -> User:
    """The owner of the *other* tenant — same reasoning, same explicit role."""
    user = create_user(email="stranger@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=other_tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=other_tenant),
    )
    return user


@pytest.fixture
def nomad(db: None) -> User:
    """A real, active user who belongs to no tenant at all."""
    return create_user(email="nomad@example.com", password=PASSWORD)


@pytest.fixture
def root(db: None) -> User:
    """A superuser with no membership. Tenancy has no exemption for it."""
    return create_user(email="root@example.com", password=PASSWORD, is_superuser=True)


@pytest.fixture
def member(tenant: Tenant) -> User:
    """A second person in the same tenant, with the least privileged role.

    The pair is what every authorization test needs: the same tenant, the same
    rows, two different answers — and which is which does not depend on the
    order the test's signature happens to name them in.
    """
    user = create_user(email="member@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def admin_member(tenant: Tenant) -> User:
    """Someone in the tenant with the `admin` role."""
    user = create_user(email="admin@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def owner_actor(owner: User, tenant: Tenant, root_org: Organization) -> Actor:
    """The owner, wearing the tenant's root as their hat.

    Every actor fixture names its hat for the same reason each names its role:
    an actor with `org=None` reads nothing from an org-scoped table, so a test
    that forgot would pass or fail for a reason it never stated.
    """
    return actor_for(user=owner, tenant=tenant, org=root_org)


@pytest.fixture
def member_actor(member: User, tenant: Tenant, root_org: Organization) -> Actor:
    return actor_for(user=member, tenant=tenant, org=root_org)


@pytest.fixture
def admin_actor(admin_member: User, tenant: Tenant, root_org: Organization) -> Actor:
    return actor_for(user=admin_member, tenant=tenant, org=root_org)


@pytest.fixture
def stranger_actor(stranger: User, other_tenant: Tenant, other_root_org: Organization) -> Actor:
    return actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
