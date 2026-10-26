"""The harness plugin: could-not-look as a third outcome, one summary line, one exit (0 · 1 · 2)."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _pytest.fixtures import FixtureFunctionDefinition

from quality.could_not_look import CouldNotLook

OUTCOME = "could not look"
_MARK = ("djb_outcome", OUTCOME)
_SEEN: set[str] = set()
_RESULTS: list[Path] = []
OUTSIDE = "outside.lines"
#: The apps tree's template-only honour, by file: `apps/testing/__init__` needs Django.
TEMPLATE_ONLY_SOURCE = Path(__file__).resolve().parents[2] / "apps" / "testing" / "template_only.py"
_WITHHELD: list[str] = []
WITHHELD_KEY = "djb_template_only_withheld"


def fixtures_in(directory: Path, package: str | None = None) -> dict[str, Any]:
    """Every fixture the modules in `directory` define, by name; a file is the registration."""
    found: dict[str, Any] = {}
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        for name, value in vars(_load(path, package)).items():
            if isinstance(value, FixtureFunctionDefinition):
                if name in found:
                    raise CouldNotLook(f"the fixture {name!r} is defined twice in {directory}")
                found[name] = value
    return found


def _load(path: Path, package: str | None) -> ModuleType:
    if package is not None:
        return importlib.import_module(f"{package}.{path.stem}")
    spec = importlib.util.spec_from_file_location(f"djb_fixtures_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise CouldNotLook(f"the fixture module {path} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pytest_addoption(parser: pytest.Parser) -> None:
    """`--drives-results <dir>` keeps each drive's output and verdict for the leg to settle."""
    parser.addoption(
        "--drives-results", default="", help="a directory for <name>.out and <name>.done per drive"
    )


def _template_only() -> ModuleType:
    spec = importlib.util.spec_from_file_location("djb_template_only", TEMPLATE_ONLY_SOURCE)
    if spec is None or spec.loader is None:
        raise CouldNotLook(f"the template-only honour {TEMPLATE_ONLY_SOURCE} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """On a tree declaring a namespace, each `template_only` test outside `apps/` is deselected."""
    apps_root = config.rootpath / "apps"
    marked = [
        item
        for item in items
        if item.get_closest_marker("template_only") is not None
        and apps_root not in item.path.parents
    ]
    if not marked:
        return
    withheld = {
        id(item): sentence for item, sentence in _template_only()._withhold_template_only(marked)
    }
    if not withheld:
        return
    gone = [item for item in items if id(item) in withheld]
    items[:] = [item for item in items if id(item) not in withheld]
    config.hook.pytest_deselected(items=gone)
    _WITHHELD.extend(f"deselected {item.nodeid} — {withheld[id(item)]}" for item in gone)
    if hasattr(config, "workerinput"):
        getattr(config, "workeroutput", {})[WITHHELD_KEY] = list(_WITHHELD)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: Any) -> None:
    """The controller keeps each worker's withheld lines for the summary."""
    for line in getattr(node, "workeroutput", {}).get(WITHHELD_KEY, ()):
        if line not in _WITHHELD:
            _WITHHELD.append(line)


def is_could_not_look(report: pytest.TestReport | pytest.CollectReport) -> bool:
    """Whether this report is the third outcome; a `CollectReport` (no properties) never is."""
    return any(tuple(p) == _MARK for p in getattr(report, "user_properties", ()))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    """A raised `CouldNotLook`, or any skip, becomes could-not-look."""
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if call.excinfo is not None and call.excinfo.errisinstance(CouldNotLook):
        reason = f"{call.when}: {call.excinfo.value}"
    elif report.skipped:
        reason = f"{call.when}: a skip clears nothing — {_skip_reason(report)}"
    else:
        return
    report.outcome = "failed"
    report.longrepr = f"COULD NOT LOOK — {reason}"
    report.user_properties = [*report.user_properties, _MARK]


def _skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


def pytest_report_teststatus(
    report: pytest.TestReport | pytest.CollectReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    """Could-not-look is counted under its own word, never as a failure."""
    if report.failed and is_could_not_look(report):
        return OUTCOME, "C", "COULD NOT LOOK"
    return None


def pytest_configure(config: pytest.Config) -> None:
    """An undeclared release's clone is refused; the outcomes start empty; results are read once."""
    refusal = _template_only().undeclared_artifact_refusal()
    if refusal is not None:
        pytest.exit(refusal, returncode=2)
    _SEEN.clear()
    _RESULTS.clear()
    _WITHHELD.clear()
    if config.getoption("drives_results", default=""):
        _RESULTS.append(Path(config.getoption("drives_results")))


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Remember every node id that could not look; write each failed teardown down."""
    if is_could_not_look(report):
        _SEEN.add(report.nodeid)
    # A teardown carries the session's fixtures too, so it names no one drive.
    if report.failed and report.when == "teardown" and _RESULTS:
        word = "could-not-look" if is_could_not_look(report) else "failed"
        with (_RESULTS[0] / OUTSIDE).open("a") as lines:
            lines.write(f"{report.when} {word} {report.nodeid}\n")


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    """The one summary line: `N passed · M failed · K could not look`."""
    for line in _WITHHELD:
        terminalreporter.write_line(line)
    stats = terminalreporter.stats
    for report in stats.get(OUTCOME, []):
        terminalreporter.write_line(f"COULD NOT LOOK {report.nodeid}: {report.longrepr}")
    looked_not = {r.nodeid for r in stats.get(OUTCOME, [])}
    failed = {r.nodeid for key in ("failed", "error") for r in stats.get(key, [])} - looked_not
    passed = {r.nodeid for r in stats.get("passed", [])} - failed - looked_not
    terminalreporter.write_line(
        f"harness: {len(passed)} passed · {len(failed)} failed · {len(looked_not)} could not look"
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Could-not-look is exit 2, and so is every pytest exit that is not 0 or 1."""
    if _SEEN or int(exitstatus) not in (0, 1):
        session.exitstatus = 2
