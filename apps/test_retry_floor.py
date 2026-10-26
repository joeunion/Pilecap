"""Every run is handed the deployment's retry floor in its argument; no workflow reads settings.

A tripwire above the apps it names: `apps.workflows` may not import them (the layer contract).
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import sys
from datetime import timedelta

import pytest
from django.conf import settings
from temporalio.client import ScheduleActionStartWorkflow

from apps.core.determinism import retry_policy
from apps.core.retry import retry_floor_seconds
from apps.events import workflows as events_workflows
from apps.search import workflows as search_workflows
from apps.workflows.client import discovered_schedules, discovered_workflows

#: This checkout's top level — `apps/` is one directory down.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The services that start a floor-taking run, and the argument class each builds.
STARTERS = (
    ("apps/djb_imports/services.py", "CheckImport"),
    ("apps/djb_imports/services.py", "ApplyImport"),
    ("apps/events/services.py", "DispatchEvent"),
    ("apps/exports/services.py", "BuildExport"),
    ("apps/files/services.py", "FinalizeUpload"),
)


def _workflow_modules() -> list[pathlib.Path]:
    """Every discovered workflow class's module file, once each."""
    files = {pathlib.Path(sys.modules[c.__module__].__file__ or "") for c in discovered_workflows()}
    return sorted(files)


def test_no_workflow_module_reads_settings() -> None:
    """No discovered `workflows.py` imports `django.conf`: the floor arrives in the argument."""
    readers = []
    for path in _workflow_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("django"):
                readers.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert len(_workflow_modules()) >= 5, "the workflow population came back nearly empty"
    assert readers == [], f"a workflow module imports Django (rule 9): {readers}"


@pytest.mark.parametrize(("path", "arg_class"), STARTERS, ids=[f"{p}:{c}" for p, c in STARTERS])
def test_every_start_hands_the_floor_in_its_argument(path: str, arg_class: str) -> None:
    """Each construction of the run's argument in its service passes `retry_floor_seconds()`."""
    tree = ast.parse((REPO_ROOT / path).read_text())
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == arg_class
    ]
    assert built, f"{path} builds no {arg_class}"
    for call in built:
        floors = [kw.value for kw in call.keywords if kw.arg == "retry_floor"]
        assert len(floors) == 1, f"{path}:{call.lineno}: {arg_class}(...) hands no retry_floor"
        value = floors[0]
        assert (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "retry_floor_seconds"
        ), f"{path}:{call.lineno}: retry_floor is not `retry_floor_seconds()`"


def test_every_schedule_whose_argument_takes_a_floor_is_handed_it() -> None:
    """A declared schedule's start arguments carry the deployment's floor, read from settings."""
    handed = []
    for declaration in discovered_schedules():
        action = declaration.schedule("q").action
        assert isinstance(action, ScheduleActionStartWorkflow), declaration.name
        for arg in action.args:
            if dataclasses.is_dataclass(arg) and hasattr(arg, "retry_floor"):
                handed.append((declaration.name, arg.retry_floor))
    assert handed, "no schedule's argument takes a retry floor — the search reconcile's does"
    assert handed == [(name, retry_floor_seconds()) for name, _ in handed]


def test_a_policy_built_from_the_floor_starts_at_the_floor() -> None:
    """`retry_policy(initial_seconds=floor)` and the reconcile's start where the argument says."""
    floor = retry_floor_seconds()
    expected = timedelta(seconds=floor)
    assert retry_policy(initial_seconds=floor, maximum_attempts=5).initial_interval == expected
    reconcile = search_workflows.reconcile_retry(floor)
    assert reconcile.initial_interval == expected
    assert reconcile.maximum_interval is not None
    assert reconcile.maximum_interval >= reconcile.initial_interval


def test_the_index_retry_is_twice_the_floor_and_its_ceiling_cannot_sink_below_it() -> None:
    """`apps/events`' `index_retry` is the one deliberate multiple, and it is 2x."""
    floor = retry_floor_seconds()
    policy = events_workflows.index_retry(floor)
    assert policy.initial_interval == 2 * timedelta(seconds=floor)
    assert policy.maximum_interval is not None
    assert policy.maximum_interval >= policy.initial_interval


def test_the_test_settings_floor_is_milliseconds_and_the_base_default_is_the_sdks() -> None:
    """The deployment default is the SDK's one second; the suite runs at a hundredth of it.

    `base.py` is read as text: `apps` may not import `config` (the layer contract).
    """
    declaration = "TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS: float = 1.0"
    base_py = REPO_ROOT / "config" / "settings" / "base.py"
    assert declaration in base_py.read_text()
    assert settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS <= 0.05
