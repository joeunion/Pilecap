# census: cross-app population=apps/*/mcp.py,apps/*/tests/*.py each mcp.py app drives the driver
"""Every app with an MCP door drives `apps.core.tests.doors.assert_four_doors` from its own tests.

The population is every `apps/*/mcp.py`; an app outside it is named, or listed in `KNOWN_GAPS`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings

from apps.core.tests.tree_census import source_tree
from quality.checks._hub import facade_reexports

ROOT = Path(str(settings.BASE_DIR))

#: The recorded backlog: an `mcp.py` app whose tests do not yet drive the driver, with its trigger.
KNOWN_GAPS: dict[str, str] = {
    "accounts": (
        "deactivate_user and erase_user, the writes both doors reach, emit no event — "
        "until an accounts write both doors reach emits one"
    ),
    "search": (
        "both tools are reads, and its two events carry an engine's state, no row's Out — "
        "until a search write reaches both doors"
    ),
    "usage": (
        "both tools are reads; usage.threshold.crossed is emitted by recording, which no "
        "door reaches — until a usage write both doors reach emits one"
    ),
    "workflows": (
        "cancel_run and replay_run, the writes both doors reach, emit no event — "
        "until a workflow-run write both doors reach emits one"
    ),
}

DRIVER = "assert_four_doors"
DRIVER_MODULE = "apps.core.tests.doors"


def mcp_apps(root: Path) -> list[str]:
    """Every app label under `root/apps` that has an `mcp.py`."""
    return sorted(path.parent.name for path in root.glob("apps/*/mcp.py"))


def driver_spellings(root: Path) -> set[tuple[str, str]]:
    """Every `(module, name)` the driver is imported by: its module and each facade re-export."""
    reexports = facade_reexports(root)
    return {(DRIVER_MODULE, DRIVER)} | {
        exported for exported, source in reexports.items() if source == (DRIVER_MODULE, DRIVER)
    }


def calls_the_driver(tree: ast.Module, spellings: set[tuple[str, str]]) -> bool:
    """Whether `tree` imports the driver under one of `spellings` and calls it by that name."""
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
        if alias.asname is None and (node.module, alias.name) in spellings
    }
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
        for node in ast.walk(tree)
    )


def drivers(root: Path) -> set[str]:
    """Every app label whose `tests/` holds a module that calls the shared parity driver."""
    spellings = driver_spellings(root)
    return {
        path.parts[-3]
        for path in root.glob("apps/*/tests/*.py")
        if calls_the_driver(source_tree(path), spellings)
    }


def undriven(root: Path) -> list[str]:
    """The `mcp.py` apps whose tests never call the driver."""
    found = drivers(root)
    return [label for label in mcp_apps(root) if label not in found]


def test_every_mcp_app_drives_the_shared_parity_driver() -> None:
    """The undriven set IS the recorded backlog: an adopter leaves it, a new app never joins."""
    population = mcp_apps(ROOT)
    missing = undriven(ROOT)
    print(f"four-doors census: {len(population) - len(missing)} of {len(population)} drive it")
    assert len(population) >= 10, "the mcp.py population came back nearly empty"
    assert missing == sorted(KNOWN_GAPS), (
        f"undriven {missing}; recorded {sorted(KNOWN_GAPS)} — a new mcp.py app drives "
        f"`{DRIVER}`, and an app that adopted it leaves KNOWN_GAPS"
    )


def test_an_app_with_an_mcp_door_and_no_driver_is_named(tmp_path: Path) -> None:
    """The negative: a planted app with `mcp.py` and a test that never names the driver."""
    planted = tmp_path / "apps" / "zzz_census_probe"
    (planted / "tests").mkdir(parents=True)
    (planted / "mcp.py").write_text("def register(server):\n    pass\n", encoding="utf-8")
    (planted / "tests" / "test_doors.py").write_text("def test_nothing():\n    pass\n")
    driven = tmp_path / "apps" / "zzz_census_driven"
    (driven / "tests").mkdir(parents=True)
    (driven / "mcp.py").write_text("", encoding="utf-8")
    (driven / "tests" / "test_doors.py").write_text(
        f"from {DRIVER_MODULE} import {DRIVER}\n"
        f"def test_one_press():\n    {DRIVER}(rest={{}}, mcp={{}}, event_payload={{}})\n",
        encoding="utf-8",
    )

    assert undriven(tmp_path) == ["zzz_census_probe"]


def test_a_module_that_only_names_the_driver_is_not_an_adopter(tmp_path: Path) -> None:
    """The phantom: the driver's name in a comment, a string and an unused import drives nothing."""
    planted = tmp_path / "apps" / "zzz_census_phantom"
    (planted / "tests").mkdir(parents=True)
    (planted / "mcp.py").write_text("", encoding="utf-8")
    (planted / "tests" / "test_doors.py").write_text(
        f"from apps.core.tests.doors import {DRIVER}  # noqa: F401\n"
        f"# this module will call {DRIVER} one day\n"
        f'WHY = "{DRIVER} is the driver"\n'
        "def test_nothing():\n    pass\n",
        encoding="utf-8",
    )

    assert undriven(tmp_path) == ["zzz_census_phantom"]


def test_the_driver_through_the_facade_drives_and_an_unexported_name_does_not(
    tmp_path: Path,
) -> None:
    """The driver through a facade that re-exports it drives; through one that does not, nothing."""
    facade = tmp_path / "pilecap"
    facade.mkdir()
    (facade / "testing.py").write_text(f"from {DRIVER_MODULE} import {DRIVER}\n", encoding="utf-8")
    (facade / "other.py").write_text("from apps.core.tests.wire import wire\n", encoding="utf-8")
    for label, module in (
        ("zzz_via_facade", "pilecap.testing"),
        ("zzz_via_other", "pilecap.other"),
    ):
        app = tmp_path / "apps" / label
        (app / "tests").mkdir(parents=True)
        (app / "mcp.py").write_text("", encoding="utf-8")
        (app / "tests" / "test_doors.py").write_text(
            f"from {module} import {DRIVER}\n"
            f"def test_one_press():\n    {DRIVER}(rest={{}}, mcp={{}}, event_payload={{}})\n",
            encoding="utf-8",
        )

    assert undriven(tmp_path) == ["zzz_via_other"]
