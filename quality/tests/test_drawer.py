"""The drawer's legs run: the full gate's place, each exit, the provisioner, the loop, the key."""

# does-not-cover: a drawer leg reused across runs by its key — the loop runs each leg every time.

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import drawer
from quality.djb import registry as R
from quality.djb.modes import Clock, run_members
from quality.tests.fixtures import shell_gate
from quality.tests.test_registry import ROOT, plant_leg
from quality.tests.test_selftest_compose import UNIT_INPUTS

pytestmark = pytest.mark.drives(
    "quality/djb/drawer.py",
    "quality/djb/registry.py",
    "quality/djb/modes.py",
    ".github/workflows/ci.yml",
    "quality/djb/rituals/push_boxes.py",
)


def _table(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[R.Table, Path]:
    tree = scratch / "tree"
    (tree / "scripts").mkdir(parents=True, exist_ok=True)
    (tree / R.GATE).write_text(shell_gate.text())
    legs = scratch / "legs"
    monkeypatch.setenv("DJB_LOCAL_LEGS_DIR", str(legs))
    return R.load(tree), legs


def _provisioner(legs: Path, unit: str, log: Path, code: int = 0) -> Path:
    script = legs / f"_provision-{unit}.sh"
    script.write_text(f'#!/usr/bin/env bash\necho provisioned >>"{log}"\nexit {code}\n')
    script.chmod(0o755)
    return script


def _marking(legs: Path, name: str, log: Path, unit: str, tier: str = "full") -> None:
    plant_leg(legs, name, unit=unit, tier=tier)
    leg = legs / f"{name}.sh"
    text = leg.read_text().replace("exit 0", f'echo "ran {name}" >>"{log}"\nexit 0')
    leg.write_text(text)


def test_the_full_gate_announces_the_drawer_after_the_house_rules(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legs = scratch / "legs"
    plant_leg(legs, "canary", 1)
    table, _ = _table(scratch, monkeypatch)
    members = [m for _, ms in table.rows for m in ms]
    assert members[-1] == "local:canary"
    no_drives = scratch / "no-drives"
    no_drives.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in UNIT_INPUTS}
    env.update(DJB_GATE_LEGS_DRY="1", DJB_SELFTEST_DRIVES_DIR=str(no_drives))
    ctx = R.Ctx(scratch / "tree", "full", env)
    assert run_members(table, members, ctx, Clock()) == 0
    seq = re.findall(r"^  leg: ([a-z0-9-]+) \(DJB_GATE_LEGS_DRY", capsys.readouterr().out, re.M)
    assert seq[-2:] == ["full-house-rules", "local-legs"], seq


def test_a_red_local_leg_reds_the_gate_naming_it(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legs = scratch / "legs"
    plant_leg(legs, "canary", 1)
    plant_leg(legs, "quiet")
    table, _ = _table(scratch, monkeypatch)
    ctx = R.Ctx(scratch / "tree", "full", dict(os.environ))
    assert run_members(table, ["local:canary", "local:quiet"], ctx, Clock()) == 1
    said = capsys.readouterr()
    assert "local:canary: exit 1" in said.out and "local:quiet: exit 0" in said.out
    assert "canary: this is a planted product leg" in said.out
    assert "!! LOCAL LEGS RED: local:canary" in said.err


def test_an_exit_2_from_a_product_leg_is_could_not_look_and_two_means_is_refused(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legs = scratch / "legs"
    plant_leg(legs, "blind", 2)
    plant_leg(legs, "canary", 1)
    table, _ = _table(scratch, monkeypatch)
    assert drawer.run(table, "full", dict(os.environ), narrowed=False) == 2
    said = capsys.readouterr()
    assert "COULD NOT LOOK: local:blind" in said.err and "and RED: local:canary" in said.err
    plant_leg(legs, "old", two_means="finding")
    with pytest.raises(R.RegistryError, match="retired 'two-means'"):
        R.local_legs(legs)


def test_inputs_and_env_are_folded_into_the_reuse_key(scratch: Path) -> None:
    legs = scratch / "legs"
    plant_leg(legs, "scan", inputs="frontend/package.json", env="DJB_FE_BASE_URL")
    (leg,) = R.local_legs(legs)
    files = {"frontend/package.json": "100644 aaa 0\tfrontend/package.json"}

    def listing(prefix: str) -> str:
        return files.get(prefix, "")

    base, parts = drawer.key(leg, listing, {"DJB_FE_BASE_URL": "a"}, "m1")
    assert re.fullmatch(r"drive-v1:[0-9a-f]{64}", base)
    assert [p.split(":")[0] for p in parts.split(",")] == [
        "self",
        "frontend/package.json",
        "env",
        "machine",
    ]
    assert drawer.key(leg, listing, {"DJB_FE_BASE_URL": "b"}, "m1")[0] != base
    assert drawer.key(leg, listing, {}, "m1")[0] != base
    assert drawer.key(leg, listing, {"DJB_FE_BASE_URL": "a"}, "m2")[0] != base
    files["frontend/package.json"] = "100644 bbb 0\tfrontend/package.json"
    assert drawer.key(leg, listing, {"DJB_FE_BASE_URL": "a"}, "m1")[0] != base
    files.clear()
    with pytest.raises(CouldNotLook, match="expands to nothing"):
        drawer.key(leg, listing, {}, "m1")


def test_a_new_local_unit_provisions_once_before_its_legs(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legs, log = scratch / "legs", scratch / "order.log"
    _marking(legs, "one", log, "frontend")
    _marking(legs, "two", log, "frontend")
    _provisioner(legs, "frontend", log)
    table, _ = _table(scratch, monkeypatch)
    assert drawer.run(table, "full", dict(os.environ), narrowed=False) == 0
    assert log.read_text().splitlines() == ["provisioned", "ran one", "ran two"]
    assert "_provision-frontend" not in R.list_legs(table, ci=False)


def test_a_failed_provisioner_stops_every_leg_of_its_unit(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legs, log = scratch / "legs", scratch / "order.log"
    _marking(legs, "one", log, "frontend")
    _marking(legs, "two", log, "frontend")
    _marking(legs, "other", log, "local")
    _provisioner(legs, "frontend", log, code=1)
    table, _ = _table(scratch, monkeypatch)
    assert drawer.run(table, "full", dict(os.environ), narrowed=False) == 2
    assert log.read_text().splitlines() == ["provisioned", "ran other", "provisioned"]
    said = capsys.readouterr()
    assert "unit 'frontend' is NOT provisioned" in said.err
    assert "COULD NOT LOOK: local:one local:two" in said.err


def test_the_loop_half_provisions_its_unit_too(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legs, log = scratch / "legs", scratch / "order.log"
    _marking(legs, "lint", log, "frontend", tier="loop")
    _marking(legs, "dear", log, "frontend", tier="full")
    plant_leg(legs, "fescan", tier="loop", touches="frontend")
    _provisioner(legs, "frontend", log)
    table, _ = _table(scratch, monkeypatch)
    env = dict(os.environ)
    assert drawer.run(table, "loop", env, narrowed=True, changed=["apps/x.py"]) == 0
    assert log.read_text().splitlines() == ["provisioned", "ran lint"]
    assert "local:fescan: SKIPPED — its touches (frontend)" in capsys.readouterr().out
    assert drawer.run(table, "full", env, narrowed=False) == 0
    assert "local:fescan: exit 0" in capsys.readouterr().out


def test_cis_matrix_takes_the_unit_with_no_yaml_edit(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plant_leg(scratch / "legs", "typecheck", unit="frontend", needs="node")
    table, _ = _table(scratch, monkeypatch)
    rows = [line.split("\t") for line in R.list_legs(table, ci=True).splitlines()]
    assert rows[-1] == ["frontend", "node", "0", "local:typecheck", ""]
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "./scripts/check.sh --list-legs --ci" in workflow
    assert "frontend" not in re.findall(r"--leg ([a-z0-9-]+)", workflow)


def test_the_bank_plan_takes_a_local_unit_from_the_listing(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plant_leg(scratch / "legs", "census", unit="product-census")
    table, _ = _table(scratch, monkeypatch)
    units = [line.split("\t")[0] for line in R.list_legs(table, ci=False).splitlines()]
    assert units[-1] == "product-census"
    plan = (ROOT / "quality/djb/rituals/push_boxes.py").read_text(encoding="utf-8")
    assert '[str(self.gate), "--list-legs"],' in plan
    assert "product-census" not in plan
