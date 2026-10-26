# census: cross-app population=apps/*/activities.py to read every daily_purge registrant's sweep
"""The platform schedule factory: one id shape, checked by the gate that judges run ids.

`apps.core.schedules.daily_purge` and `platform_schedule` mint
`platform:<app>:<noun>:<queue>` for a periodic machine's schedule and for the run
it starts. `core` may not import `apps.workflows`, so the grammar is restated
there; this module holds the two equal the only way that cannot drift — by
handing every minted id to `apps.workflows.services.check_workflow_id` itself.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from datetime import timedelta
from pathlib import Path

import pytest

from apps.core.lifecycle import declared_lifecycles
from apps.core.schedules import (
    DAILY,
    ID_SEPARATOR,
    PLATFORM_SEGMENT,
    ScheduleDeclaration,
    daily_purge,
    platform_id,
)
from apps.core.tests.tree_census import source_tree
from apps.workflows import services as workflow_services

APPS = Path(__file__).resolve().parents[2]

#: Daily-purge sweeps off the one signature, each by a ruling.
OFF_THE_SIGNATURE = {
    "apps.exports.services.purge_exports": "its `PurgeOutcome.artifacts` is read; the owner ruled",
}


def _minted(declaration: ScheduleDeclaration, queue: str = "djb_main_0123abcd") -> list[str]:
    schedule = declaration.schedule(queue)
    return [declaration.schedule_id(queue), str(schedule.action.id)]  # type: ignore[attr-defined]


def test_the_factory_mints_one_platform_id() -> None:
    declaration = daily_purge(app="exports", noun="purge", workflow="PurgeExports", arg=None)
    schedule_id, run_id = _minted(declaration)
    assert schedule_id == run_id == "platform:exports:purge:djb_main_0123abcd"
    for minted in (schedule_id, run_id):
        assert workflow_services.check_workflow_id(id=minted, tenant=None) == minted
    spec = declaration.schedule("q").spec
    assert spec.intervals[0].every == DAILY == timedelta(days=1)
    assert declaration.name == "exports.purge"


def test_the_system_spelling_is_refused_by_the_check_the_factory_matches() -> None:
    """The negative: the prefix eight declarations still carry is one a run may not wear."""
    with pytest.raises(ValueError, match="platform"):
        workflow_services.check_workflow_id(id="system:exports:purge:q", tenant=None)


def test_the_restated_grammar_is_the_workflows_grammar() -> None:
    assert PLATFORM_SEGMENT == workflow_services.PLATFORM_SEGMENT
    assert ID_SEPARATOR == workflow_services.ID_SEPARATOR


@pytest.mark.parametrize(
    ("app", "noun", "key"), [("", "purge", "q"), ("a:b", "purge", "q"), ("app", "purge", " ")]
)
def test_a_segment_the_grammar_refuses_cannot_be_minted(app: str, noun: str, key: str) -> None:
    with pytest.raises(ValueError, match="segment"):
        platform_id(app=app, noun=noun, key=key)


def test_core_s_own_prober_is_declared_through_the_factory() -> None:
    from apps.core.activities import PROBE_INTEGRATIONS

    for minted in _minted(PROBE_INTEGRATIONS):
        assert minted.startswith(f"{PLATFORM_SEGMENT}{ID_SEPARATOR}core{ID_SEPARATOR}integrations")
        workflow_services.check_workflow_id(id=minted, tenant=None)


def _registrant_apps() -> list[str]:
    """Every app whose `activities.py` declares a schedule through `daily_purge`, by its `app=`."""
    found = []
    for module in sorted(APPS.glob("*/activities.py")):
        for node in source_tree(module).body:
            call = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "daily_purge":
                app = next(k.value for k in call.keywords if k.arg == "app")
                found.append(str(app.value))  # type: ignore[attr-defined]
    return sorted(set(found))


def _service_sweeps(app: str) -> list[str]:
    """The `purged_by` services a registrant's tables name; an activity sweep owns no row."""
    prefix = f"apps.{app}.services."
    named = {str(one.purged_by) for one in declared_lifecycles().values() if one.purged_by}
    return sorted(path for path in named if path.startswith(prefix))


def _spelled(annotation: object) -> str:
    """An annotation as its source spells it, whether the module postponed it or not."""
    if isinstance(annotation, str):
        return annotation
    return "None" if annotation is None else getattr(annotation, "__name__", repr(annotation))


def _resolve(path: str) -> object:
    module, _, name = path.rpartition(".")
    return getattr(importlib.import_module(module), name)


SWEEPS = [path for app in _registrant_apps() for path in _service_sweeps(app)]

#: Sweeps found off the signature with no ruling yet: each fails strictly until it conforms.
UNRULED: dict[str, str] = {}


def _case(path: str) -> object:
    if path in UNRULED:
        return pytest.param(path, marks=pytest.mark.xfail(strict=True, reason=UNRULED[path]))
    return path


def test_every_daily_purge_registrant_names_a_service_sweep() -> None:
    """The population is derived, and a registrant whose tables name no service sweep reds here."""
    apps = _registrant_apps()
    assert apps, "no `daily_purge` registrant was found — the derivation went blind"
    assert all(_service_sweeps(app) for app in apps), {a: _service_sweeps(a) for a in apps}


@pytest.mark.parametrize("path", [_case(p) for p in SWEEPS if p not in OFF_THE_SIGNATURE])
def test_every_daily_purge_sweep_has_the_one_signature(path: str) -> None:
    """ADR core-22: `(*, before: datetime, tenant: None) -> Swept`, the factory's one shape."""
    signature = inspect.signature(_resolve(path))  # type: ignore[arg-type]
    shape = {name: _spelled(p.annotation) for name, p in signature.parameters.items()}

    assert shape == {"before": "datetime", "tenant": "None"}, path
    assert {p.kind for p in signature.parameters.values()} == {inspect.Parameter.KEYWORD_ONLY}
    assert _spelled(signature.return_annotation) == "Swept", path


def test_every_sweep_off_the_signature_is_still_a_registrants() -> None:
    """A declared exception that left the population is a stale ruling, not a pass."""
    assert set(OFF_THE_SIGNATURE) <= set(SWEEPS), sorted(set(OFF_THE_SIGNATURE) - set(SWEEPS))
