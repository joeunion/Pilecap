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
import os
import pathlib
import signal
import subprocess
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
from apps.core.tests.tree_census import source_tree

PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


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
# an `importlib.import_module` of an absent app is invisible to it.

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


def _imported_modules(node: ast.AST) -> frozenset[str]:
    """Every module name one `import` statement could be naming.

    `from apps.core import context` names `apps.core` and may be reaching
    `apps.core.context` — a module or an attribute of a package, and which one
    it is cannot be told from the syntax. Both are returned; the caller resolves
    each against the tree and keeps what exists.
    """
    if isinstance(node, ast.Import):
        return frozenset(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return frozenset([node.module, *(f"{node.module}.{alias.name}" for alias in node.names)])
    return frozenset()


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

    at_import: set[str] = set()
    per_test: dict[str, frozenset[str]] = {}
    for statement in tree.body:
        own = apps_only(_imported_modules(statement))
        if own:
            at_import |= own
            continue
        nested = apps_only(
            frozenset().union(*(_imported_modules(node) for node in ast.walk(statement)))
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
        "--djb-tier-manifest",
        action="store",
        default="",
        metavar="PATH",
        help=(
            "write the derived classification (one `<tier>\\t<organs>\\t<nodeid>` line "
            "per collected test) to PATH. What the census drive reads."
        ),
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
    return [
        *_DJB_ABSENT_REPORT,
        "djb tier: FAST — organ-reaching tests (real MinIO, a real Temporal server, "
        f"real Meili) are DESELECTED {where}. The full gate at push runs every one "
        "of them, twice.",
    ]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # The absent-app world first, and unconditionally: what a smaller deployment
    # cannot run is not a tier choice, and the tier's early return below is
    # allowed to skip work only because it changes nothing.
    _withhold_the_absent_world(items)
    tier = str(config.getoption("--djb-tier"))
    manifest = str(config.getoption("--djb-tier-manifest"))
    _DJB_TIER_REPORT.clear()
    if tier == "all" and not manifest:
        # The full gate's two passes take this branch and pay nothing: no source
        # read, no closure walk, no deselection, no behaviour change at all.
        return

    own_apps = frozenset(str(label) for label in config.getoption("--djb-own-app"))
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

    if manifest and not hasattr(config, "workerinput"):
        lines = []
        for item, organs in classified:
            where = "slow" if organs else "fast"
            lines.append(f"{where}\t{','.join(sorted(organs)) or '-'}\t{item.nodeid}")
        pathlib.Path(manifest).write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")

    if tier != "fast":
        return

    keep: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    for item, organs in classified:
        if organs and _app_label(item.nodeid) not in own_apps:
            dropped.append(item)
        else:
            keep.append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep

    census = ", ".join(f"{kind}={reached[kind]}" for kind in sorted(reached)) or "none"
    _DJB_TIER_REPORT.append(
        f"djb tier: FAST — {len(dropped)} organ-reaching test(s) deselected, "
        f"{len(keep)} running (derived reach: {census})."
    )
    if own_apps:
        _DJB_TIER_REPORT.append(
            "  own app(s) in scope, run IN FULL: " + ", ".join(sorted(own_apps))
        )
    else:
        _DJB_TIER_REPORT.append(
            "  no app is in scope under apps/, so there is NO own app: the rule for "
            "that case is the fast tier alone, and it is declared here rather than "
            "chosen silently."
        )
    _DJB_TIER_REPORT.append(
        "  the deselected tests are NOT skipped forever — the FULL gate at push runs "
        "every one of them, twice."
    )


def pytest_report_collectionfinish(config: pytest.Config) -> list[str]:
    return list(_DJB_TIER_REPORT)


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
