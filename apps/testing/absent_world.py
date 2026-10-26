"""The absent-app world: the one subtraction a deployment may make."""

from __future__ import annotations

import ast
import os
import pathlib
from typing import NamedTuple

import pytest

import apps
from apps.core.tests.tree_census import source_tree

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
_APPS_ROOT = pathlib.Path(apps.__file__).resolve().parent


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
    """`apps/core/tests/test_<x>.py` -> `apps.core.tests.test_<x>`; a package -> its dir."""
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
