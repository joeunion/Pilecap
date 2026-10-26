"""`python -m quality.djb gate`: the modes' refusals, what each takes, and what each banks."""

# Invariant: every run here points the lease and the ledger at a scratch directory of its own.
# does-not-cover: a real full gate or a real `--loop` — a box runs those (G3b.5).

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import gate_args, hold, modes
from quality.djb import registry as R

pytestmark = pytest.mark.drives(
    "quality/djb/modes.py", "quality/djb/loop.py", "quality/djb/__main__.py"
)

ROOT = Path(__file__).resolve().parents[2]
#: Names a caller's environment may carry that would change which mode runs, cleared per run.
CLEARED = (
    "CI",
    "DJB_GATE_SANCTION",
    "DJB_GATE_CALLER",
    "DJB_LOOP_HERE",
    "DJB_GATE_BOX_MARKERS",
    "DJB_LOOP_NO_CACHE",
    "DJB_GATE_LEGS_DRY",
)


def gate(tmp_path: Path, *argv: str, cwd: Path = ROOT, **extra: str) -> tuple[int, str]:
    """One door run, stdout to a file (the door refuses a pipe), lease and ledger in `tmp_path`."""
    env = {k: v for k, v in os.environ.items() if k not in CLEARED}
    lease = tmp_path / "lease"
    lease.mkdir(exist_ok=True)
    env.update(
        DJB_GATE_LEASE_DIR=str(lease),
        DJB_GATE_LEDGER=str(tmp_path / "ledger"),
        DJB_GATE_BOX_MARKER=str(tmp_path / "no-box-marker"),
        **extra,
    )
    out = tmp_path / "out.txt"
    with out.open("w") as sink:
        rc = subprocess.run(
            [sys.executable, "-m", "quality.djb", "gate", *argv],
            cwd=cwd,
            env=env,
            stdout=sink,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode
    return rc, out.read_text()


def taken(tmp_path: Path) -> list[str]:
    """Whatever the run left in the scratch lease directory."""
    return sorted(p.name for p in (tmp_path / "lease").iterdir())


def test_an_unsanctioned_full_gate_is_exit_2_and_takes_no_lease(tmp_path: Path) -> None:
    rc, said = gate(tmp_path)
    assert rc == 2, said
    assert gate_args.UNSANCTIONED[0] in said
    assert taken(tmp_path) == []
    assert not (tmp_path / "ledger").exists()


def test_a_loop_off_a_box_is_refused_in_the_shells_words_above_every_hold(tmp_path: Path) -> None:
    rc, said = gate(tmp_path, "--loop", DJB_LOOP_NO_CACHE="1")
    assert rc == 2, said
    assert said.splitlines() == list(gate_args.OFF_BOX_SAID)
    assert taken(tmp_path) == []


def test_a_shapeless_loop_valve_is_exit_2_before_the_box_question(tmp_path: Path) -> None:
    rc, said = gate(tmp_path, "--loop", DJB_LOOP_HERE="no reason")
    assert rc == 2, said
    assert said.splitlines()[0] == gate_args.LOOP_HERE_SHAPE[0]


def test_a_leg_takes_no_lease_no_lock_and_writes_no_verdict(tmp_path: Path) -> None:
    rc, said = gate(tmp_path, "--leg", "static", DJB_GATE_LEGS_DRY="1")
    assert rc == 0, said
    assert "This run takes NO machine lease, NO checkout lock and records NO verdict:" in said
    assert "no verdict recorded — --leg static: one unit of the gate" in said
    assert taken(tmp_path) == []
    assert not (tmp_path / "ledger").exists()


def test_a_leg_needs_no_sanction_and_an_unknown_unit_names_the_listing(tmp_path: Path) -> None:
    rc, said = gate(tmp_path, "--leg", "nope")
    assert rc == 2, said
    for unit, _ in R.load(ROOT).rows:
        assert f"     {unit.name}" in said.splitlines()


def test_a_dry_full_gate_prints_its_typed_sanction_and_banks_nothing(tmp_path: Path) -> None:
    # Invariant: the checkout lock is cwd's git dir's; a scratch repo's run nests in a full gate.
    world = tmp_path / "world"
    world.mkdir()
    subprocess.run(["git", "init", "-q", str(world)], check=True)
    for top in ROOT.iterdir():
        if top.name != ".git":
            (world / top.name).symlink_to(top)
    why = "GF-5-B3: the header line carries the typed sanction"
    rc, said = gate(tmp_path, cwd=world, DJB_GATE_SANCTION=why, DJB_GATE_LEGS_DRY="1")
    assert rc == 0, said
    assert "- sanction: typed:GF-5-B3:the header line carries the typed sanction" in said
    assert "no verdict recorded — DJB_GATE_LEGS_DRY" in said
    ledger = tmp_path / "ledger"
    assert not ledger.exists() or " full " not in ledger.read_text()
    assert taken(tmp_path) == []


def test_any_other_first_word_is_the_cli_door(tmp_path: Path) -> None:
    out = tmp_path / "listing.txt"
    with out.open("w") as sink:
        rc = subprocess.run(
            [sys.executable, "-m", "quality.djb", "--list-legs"], cwd=ROOT, stdout=sink
        ).returncode
    assert rc == 0
    rc, said = gate(tmp_path, "--list-legs")
    assert rc == 0
    assert said == out.read_text()


def test_the_listing_reads_through_a_pipe_and_every_other_mode_refuses_one() -> None:
    env = {k: v for k, v in os.environ.items() if k not in CLEARED}
    listing = subprocess.run(
        [sys.executable, "-m", "quality.djb", "gate", "--list-legs"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert listing.returncode == 0 and listing.stdout
    piped = subprocess.run(
        [sys.executable, "-m", "quality.djb", "gate", "--leg", "static"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert piped.returncode == 2
    assert "refuses pipes" in piped.stderr


def test_the_census_reads_through_a_pipe_with_its_rows() -> None:
    env = {k: v for k, v in os.environ.items() if k not in CLEARED}
    census = subprocess.run(
        [sys.executable, "-m", "quality.djb", "gate", "--census"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert census.returncode == 0, census.stderr
    assert "refuses pipes" not in census.stderr and census.stdout.strip(), census.stdout


class _Taken:
    def __init__(self, scope: str, said: list[str]) -> None:
        self.scope, self.said, self.paths = scope, said, [Path(scope)]

    def release(self) -> None:
        self.said.append(f"release {self.scope}")


def _full(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refuse: str = ""
) -> tuple[int, list[str]]:
    """`modes.run_full` with the holds recorded, its legs red and nothing written."""
    said: list[str] = []

    def hold_(scope: str, on_contention: str, **_: object) -> _Taken:
        said.append(f"ask {scope} {on_contention}")
        if scope == refuse:
            raise hold.Refused(f"planted: {scope} refused")
        return _Taken(scope, said)

    for name in CLEARED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DJB_GATE_SANCTION", "gf-5-b3: the hold order is the property")
    monkeypatch.setenv("DJB_GATE_LEDGER", str(tmp_path / "ledger"))
    monkeypatch.setattr(hold, "hold", hold_)
    monkeypatch.setattr(modes, "_measured", lambda root: "planted-tree")
    monkeypatch.setattr(modes, "announce", lambda *a: said.append("announce"))

    def legs(*_: object) -> int:
        said.append("legs")
        return 1

    monkeypatch.setattr(modes, "run_members", legs)
    monkeypatch.setattr(modes, "_note", lambda *a: said.append("note"))
    return modes.run_full(ROOT, gate_args.Request()), said


def test_the_full_gate_asks_the_lease_before_the_lock_and_releases_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rc, said = _full(monkeypatch, tmp_path)
    assert rc == 1
    assert said == [
        "ask lease wait",
        "ask host wait",
        "ask checkout refuse",
        "announce",
        "legs",
        "note",
        "release checkout",
        "release host",
        "release lease",
    ]


def test_a_refused_host_slot_is_exit_2_and_gives_the_lease_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rc, said = _full(monkeypatch, tmp_path, refuse="host")
    assert rc == 2
    assert said == ["ask lease wait", "ask host wait", "release lease"]


def test_a_refused_lease_is_exit_2_and_the_lock_is_never_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rc, said = _full(monkeypatch, tmp_path, refuse="lease")
    assert rc == 2
    assert said == ["ask lease wait"]


def _exits(code: int) -> Callable[[R.Ctx], int]:
    def body(ctx: R.Ctx) -> int:
        return code

    return body


def _legs(*codes: int) -> R.Table:
    """A table of planted legs, one per exit code."""
    legs = tuple(
        R.Leg(f"leg-{n}", "unit", f"leg {n}", body=_exits(code)) for n, code in enumerate(codes)
    )
    return R.Table(rows=(), legs=legs)


@pytest.mark.parametrize(("mode", "ran", "rc"), [("loop", 3, 2), ("full", 1, 1)])
def test_the_loop_runs_every_leg_and_names_every_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str, ran: int, rc: int
) -> None:
    table = _legs(1, 0, 2)
    clock = modes.Clock()
    names = [leg.name for leg in table.legs]
    assert modes.run_members(table, names, R.Ctx(tmp_path, mode, {}), clock) == rc
    assert len(clock.seconds) == ran
    said = capsys.readouterr().out
    if mode == "loop":
        assert "- every red leg: leg-0 exit 1 · leg-2 exit 2" in said, said
    else:
        assert "every red leg" not in said


def test_a_bare_id_through_the_loop_flag_is_exit_2_before_the_box_question(
    tmp_path: Path,
) -> None:
    rc, said = gate(tmp_path, "--loop", "--here", "loop-here")
    assert rc == 2, said
    assert said.splitlines()[0] == gate_args.LOOP_HERE_FLAG_SHAPE[0]
    assert taken(tmp_path) == []
