"""The alert census's spike half, over planted trees and the real one; run by name, off the gate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ALERTS = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("alert_census", ALERTS / "census.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["alert_census"] = module
    spec.loader.exec_module(module)
    return module


census = _load()

_SPIKE = (
    'SPIKES = (\n    {{"key": "{key}", "threshold": {threshold}, "window": "{window}", '
    '"reason": "a planted spike for the census test"}},\n)\n'
)


def _plant(
    root: Path,
    *,
    key: str = "widgets.door.refused",
    threshold: int = 20,
    window: str = "5m",
    logged: str | None = "widgets.door.refused",
) -> Path:
    """A tree with one app declaring one spike, and a module logging `logged` unless it is None."""
    (root / "manage.py").write_text("", encoding="utf-8")
    app = root / "apps" / "widgets"
    app.mkdir(parents=True)
    (app / "events.py").write_text(
        'WIDGET_CREATED = "widgets.widget.created"\n'
        + _SPIKE.format(key=key, threshold=threshold, window=window),
        encoding="utf-8",
    )
    if logged is not None:
        (app / "door.py").write_text(
            f'def refuse(log):\n    log.info("{logged}", reason="x")\n', encoding="utf-8"
        )
    return root


def _spikes(result: dict) -> list[dict]:
    return [alert for alert in result["alerts"] if alert["kind"] == "spike"]


def test_a_declared_spike_is_in_the_census(tmp_path: Path) -> None:
    result = census.census(_plant(tmp_path))
    assert result["warnings"] == []
    (spike,) = _spikes(result)
    assert spike["log_key"] == "widgets.door.refused"
    assert (spike["threshold"], spike["window"], spike["where"]) == (20, "5m", "log")
    assert spike["delivered_by"] == "clickstack"
    assert spike["emitted_at"] == ["apps/widgets/door.py:2"]
    assert "widgets.door.refused" in census.render(result)


def test_a_spike_over_a_never_logged_key_warns(tmp_path: Path) -> None:
    result = census.census(_plant(tmp_path, logged=None))
    assert _spikes(result) == []
    (warning,) = result["warnings"]
    assert "widgets.door.refused" in warning
    assert "no log." in warning


def test_a_test_module_logging_the_key_is_not_an_emitter(tmp_path: Path) -> None:
    root = _plant(tmp_path, logged=None)
    tests = root / "apps" / "widgets" / "tests"
    tests.mkdir()
    (tests / "test_door.py").write_text('log.info("widgets.door.refused")\n', encoding="utf-8")
    result = census.census(root)
    assert _spikes(result) == []
    assert len(result["warnings"]) == 1


def test_a_window_the_sink_cannot_check_warns(tmp_path: Path) -> None:
    result = census.census(_plant(tmp_path, window="7m"))
    assert _spikes(result) == []
    (warning,) = result["warnings"]
    assert "7m" in warning


def test_a_zero_threshold_warns(tmp_path: Path) -> None:
    result = census.census(_plant(tmp_path, threshold=0))
    assert _spikes(result) == []
    (warning,) = result["warnings"]
    assert "threshold" in warning


def test_a_key_outside_its_own_app_warns(tmp_path: Path) -> None:
    result = census.census(
        _plant(tmp_path, key="accounts.door.refused", logged="accounts.door.refused")
    )
    assert _spikes(result) == []
    (warning,) = result["warnings"]
    assert "accounts.door.refused" in warning


def test_the_worked_spike_is_the_auth_failure_one() -> None:
    result = census.census(REPO)
    spikes = {spike["log_key"]: spike for spike in _spikes(result)}
    spike = spikes["accounts.signin.refused"]
    assert (spike["app"], spike["threshold"], spike["window"]) == ("accounts", 20, "5m")
    assert any(site.startswith("apps/accounts/signin.py:") for site in spike["emitted_at"])
    assert result["warnings"] == []


def test_every_spike_instantiates_the_definitions_shape() -> None:
    definitions = json.loads((ALERTS / "definitions.json").read_text(encoding="utf-8"))
    shape = definitions["spike"]
    for spike in _spikes(census.census(REPO)):
        assert shape["saved_search"]["where"].format(**spike) == (
            f"JSONExtractString(Body, 'event') = '{spike['log_key']}'"
        )
        assert shape["alert"]["thresholdType"] == "above"
        assert shape["alert"]["interval"].format(**spike) == spike["window"]
        assert int(shape["alert"]["threshold"].format(**spike)) == spike["threshold"]
        message = shape["alert"]["message"].format(**spike)
        for part in (
            spike["log_key"],
            str(spike["threshold"]),
            spike["window"],
            "docs/runbooks/alerts.md",
        ):
            assert part in message


def _traces(result: dict) -> dict[str, dict]:
    return {alert["key"]: alert for alert in result["alerts"] if alert["kind"] == "traces"}


def _definitions() -> dict:
    return json.loads((ALERTS / "definitions.json").read_text(encoding="utf-8"))


def test_a_traces_definition_is_in_the_census(capsys) -> None:  # noqa: ANN001
    assert "traces" in census.KINDS
    result = census.census(REPO)
    members = _traces(result)
    assert sorted(members) == ["traces:error_rate", "traces:latency"]
    for member in members.values():
        assert (member["where"], member["delivered_by"]) == ("traces", "clickstack")
        assert member["window"] in census.SPIKE_WINDOWS
    assert "quantile(0.95)(Duration" in members["traces:latency"]["select"]
    assert members["traces:error_rate"]["select"].startswith("count()")
    assert census.main(["--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert {m["kind"] for m in listed["alerts"]} >= {"spike", "traces"}
    assert "[traces] latency" in census.render(result)


def test_every_kind_has_one_shape_and_every_shape_a_kind() -> None:
    assert census.shape_problems(_definitions()) == []


def test_a_shape_of_an_unknown_kind_is_a_refusal() -> None:
    definitions = _definitions()
    definitions["histogram"] = definitions["traces"]
    del definitions["spike"]
    problems = census.shape_problems(definitions)
    assert any("histogram" in problem for problem in problems)
    assert any("spike" in problem for problem in problems)


def test_every_traces_member_instantiates_the_definitions_shape() -> None:
    shape = _definitions()["traces"]
    for member in _traces(census.census(REPO)).values():
        tile = census.fill(shape["tile"], member)
        alert = census.fill(shape["alert"], member)
        assert tile["select"] == member["select"]
        assert tile["where"] == member["where_sql"]
        assert alert["source"] == "tile"
        assert alert["interval"] == member["window"]
        assert float(alert["threshold"]) == member["threshold"]
        for part in (member["name"], member["window"], "docs/runbooks/alerts.md"):
            assert part in alert["message"]
