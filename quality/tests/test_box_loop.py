"""`loop` and `leg`: `quality.djb.box.loop` driven through `fixtures/box_world.py`."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from quality.djb.box.loop import box_ledger_ingest
from quality.tests.fixtures.box_world import MAIN_SHA, World
from quality.tests.fixtures.fake_clock import ADVANCE_SH

pytestmark = pytest.mark.drives("quality/djb/box/loop.py")

ROOT = Path(__file__).resolve().parents[2]
STATE = "ec2_describe-instances__Reservations0Instances0StateName"
CHECKOUT = "/home/verifier/src"
# The shell's `box_ledger_ingest /home/verifier/src a-rung`, byte for byte (GP G4.2).
INGEST = (
    "{ L=$(bash -c '. scripts/gate_ledger.sh >/dev/null 2>&1 && gate_ledger_path');"
    ' if [ -n "$L" ] && [ -f ~/verify/a-rung/ledger.in ]; then while IFS= read -r l; do'
    ' [ -z "$l" ] || grep -qxF -- "$l" "$L" 2>/dev/null || printf \'%s\\n\' "$l" >> "$L";'
    " done < ~/verify/a-rung/ledger.in; fi || true; }"
)
# The shell's `loop i-up1 --log v1` remote command as the ssh stub recorded it, byte for byte.
LOOP_LINE = (
    "touch /run/verifier/last-activity 2>/dev/null || true; { mkdir -p ~/verify/a-rung &&"
    f" cd {CHECKOUT} && {INGEST} && setsid nohup sh -c 'DJB_GATE_SLOTS=1"
    " DJB_LOOP_SCOPE_BASE=refs/djb/base ./scripts/check.sh --loop > ~/verify/a-rung/v1.log 2>&1;"
    " echo $? > ~/verify/a-rung/v1.rc; touch /run/verifier/last-activity 2>/dev/null || true'; }"
    " </dev/null >/dev/null 2>&1 & echo $! "
)


def _ready(world: World, rung: str = "a-rung") -> None:
    """`world_box_ready_to_detach`: up, keyed, on HEAD's tree, answering `4242` to everything."""
    world.ans(STATE, "running")
    world.keyed_box(rung=rung)
    world.ssh(1, "out", f"{MAIN_SHA}\n")
    world.ssh(2, "out", f"{MAIN_SHA}\n")
    world.ssh("default", "out", "4242\n")


def _launched(world: World) -> list[str]:
    """Every recorded ssh session that started a detached gate."""
    return [
        path.read_text()
        for path in sorted((world.rec / "ssh").glob("*.flat"))
        if "setsid nohup" in path.read_text()
    ]


def _remote(flat: str) -> str:
    """The remote command of a recorded ssh argv: everything after the `--`."""
    return flat.split(" -- ", 1)[1]


# --- loop: the detach, the caller, the pins ---------------------------------------------


def test_loop_detaches_the_gate_on_the_box_and_never_pipes_it(world: World) -> None:
    _ready(world)
    assert world.vb("loop", "i-up1", "--log", "v1") == 0, world.report()
    call = world.ssh_flat(3)
    for want in (
        "setsid nohup",
        "DJB_LOOP_SCOPE_BASE=refs/djb/base ./scripts/check.sh --loop >",
        "~/verify/a-rung/v1.log 2>&1",
        "~/verify/a-rung/v1.rc",
    ):
        assert want in call, call
    assert "check.sh --loop |" not in call and "check.sh --loop 2>&1 |" not in call
    assert (world.vhome / "i-up1" / "v1.pid").read_text() == "4242\n"


def test_the_loop_launch_and_the_ledger_ingest_are_the_shells_lines_byte_for_byte(
    world: World,
) -> None:
    assert box_ledger_ingest(CHECKOUT, "a-rung") == INGEST
    _ready(world)
    assert world.vb("loop", "i-up1", "--log", "v1") == 0, world.report()
    assert _remote(world.ssh_flat(3)) == LOOP_LINE


@pytest.mark.parametrize("arm", ["forwarded", "refused"])
def test_loop_forwards_the_gate_caller_to_the_box(world: World, arm: str) -> None:
    _ready(world)
    if arm == "forwarded":
        assert (
            world.vb("loop", "i-up1", "--log", "v1", env=world.env(DJB_GATE_CALLER="main-loop"))
            == 0
        )
        assert "sh -c 'DJB_GATE_CALLER=main-loop DJB_GATE_SLOTS=1 " in world.ssh_flat(3)
    else:
        env = world.env(DJB_GATE_CALLER="main;rm")
        assert world.vb("loop", "i-up1", "--log", "v1", env=env) == 2, world.report()
        assert world.said("DJB_GATE_CALLER='main;rm' is not a caller word"), world.report()
        assert not (world.rec / "ssh" / "3.flat").exists()


def _swapped(flat: str, scratch: Path, seconds: int) -> str:
    """`detach_payload_swapped`: the recorded command, its gate a sleep, its paths in scratch."""
    command = _remote(flat).replace(
        "touch /run/verifier/last-activity 2>/dev/null || true; ", "", 1
    )
    start = command.index("sh -c '")
    end = command.index("'", start + 7)
    command = f"{command[:start]}sh -c 'sleep {seconds}'{command[end + 1 :]}"
    command = re.sub(r"&& cd \S+ &&", f"&& cd {scratch} &&", command)
    return re.sub(r"~/verify/[^/\s;]+", str(scratch), command)


@pytest.mark.parametrize("sub", ["loop", "leg"])
def test_the_detach_returns_while_the_gate_is_still_running(
    world: World, scratch: Path, sub: str
) -> None:
    _ready(world)
    argv = ("--log", "v1") if sub == "loop" else ("--unit", "ruff", "--log", "v1")
    assert world.vb(sub, "i-up1", *argv) == 0, world.report()
    last = (world.rec / "seq" / "_ssh").read_text().strip()
    here = scratch / f"detach-{sub}"
    (here / "bin").mkdir(parents=True)
    setsid = here / "bin" / "setsid"
    setsid.write_text('#!/bin/sh\nexec "$@"\n')
    setsid.chmod(0o755)
    finished = here / "payload-finished"
    command = _swapped(world.ssh_flat(int(last)), here, 8)
    assert "sh -c 'sleep 8'" in command
    command = command.replace("sh -c 'sleep 8'", f"sh -c 'sleep 8; touch {finished}'", 1)
    done = subprocess.run(
        ["bash", "-c", command],
        env={**os.environ, "PATH": f"{here / 'bin'}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert not finished.exists(), "the detach held its caller until the 8s payload had finished"
    assert re.fullmatch(r"[0-9]+", done.stdout.strip()), done.stdout


def test_the_detached_gate_restarts_the_idle_clock_when_it_exits(world: World) -> None:
    _ready(world)
    assert world.vb("loop", "i-up1", "--log", "v1") == 0, world.report()
    call = world.ssh_flat(3)
    inner = call.split("nohup sh -c '", 1)[1].split("'; }", 1)[0]
    root, verify, fake, rbin = (world.root / d for d in ("reaproot", "verify", "fake", "rbin"))
    for directory in (root / "etc" / "verifier", root / "run" / "verifier", verify / "a-rung"):
        directory.mkdir(parents=True)
    fake.mkdir()
    rbin.mkdir()
    (root / "etc" / "verifier" / "expires").write_text("2099-01-01T00:00:00Z\n")
    (root / "etc" / "verifier" / "idle-minutes").write_text("1\n")
    marker = root / "run" / "verifier" / "last-activity"
    marker.write_text("")
    old = time.time() - 120
    os.utime(marker, (old, old))
    (fake / "check.sh").write_text("#!/bin/sh\nexit 0\n")
    (fake / "check.sh").chmod(0o755)
    inner = inner.replace("./scripts/check.sh", str(fake / "check.sh"))
    inner = inner.replace("~/verify", str(verify)).replace(
        "/run/verifier/last-activity", str(marker)
    )
    subprocess.run(["sh", "-c", inner], cwd=world.root, check=False)
    assert (verify / "a-rung" / "v1.rc").is_file(), inner
    halted = world.root / "halted"
    for name, body in (
        ("who", "exit 0"),
        ("pgrep", "exit 1"),
        ("logger", "exit 0"),
        ("shutdown", f'echo halted >>"{halted}"'),
    ):
        (rbin / name).write_text(f"#!/bin/sh\n{body}\n")
        (rbin / name).chmod(0o755)
    reaper = subprocess.run(
        ["bash", str(ROOT / "deploy" / "verifier" / "idle_reaper.sh")],
        env={
            "PATH": f"{rbin}:/usr/bin:/bin",
            "VERIFIER_ROOT": str(root),
            "VERIFIER_USER": "driveuser",
        },
        capture_output=True,
        text=True,
    )
    assert not halted.exists(), reaper.stdout + reaper.stderr


# --- leg: one unit, its modifiers, its refusals -------------------------------------


@pytest.mark.parametrize("arm", ["sharded", "unsharded"])
def test_leg_detaches_one_unit_shard_and_never_pipes_it(world: World, arm: str) -> None:
    if arm == "unsharded":
        _ready(world, "bank-abc12345-static")
        assert world.vb("leg", "i-up1", "--unit", "static", "--log", "leg") == 0, world.report()
        assert (
            "./scripts/check.sh --leg static > ~/verify/bank-abc12345-static/leg.log"
            in world.ssh_flat(3)
        )
        return
    _ready(world, "bank-abc12345-selftest-2of3")
    argv = ("--unit", "selftest", "--shard", "2/3", "--log", "leg")
    assert world.vb("leg", "i-up1", *argv) == 0, world.report()
    call = world.ssh_flat(3)
    for want in (
        "setsid nohup",
        "./scripts/check.sh --leg selftest --shard 2/3 >",
        "~/verify/bank-abc12345-selftest-2of3/leg.log 2>&1",
        "~/verify/bank-abc12345-selftest-2of3/leg.rc",
        "touch /run/verifier/last-activity",
    ):
        assert want in call, call
    assert "--shard 2/3 |" not in call and "--shard 2/3 2>&1 |" not in call
    assert "DJB_LOOP_SCOPE_BASE" not in call
    assert (world.vhome / "i-up1" / "leg.pid").read_text() == "4242\n"


@pytest.mark.parametrize(
    ("arm", "argv", "want"),
    [
        ("one", "--unit pytest-x2 --shard 1/1 --passes 1 --log leg", "--shard 1/1 --passes 1 >"),
        ("two", "--unit pytest-x2 --shard 1/1 --passes 2 --log leg", "--shard 1/1 --passes 2 >"),
        ("absent", "--unit pytest-x2 --shard 1/2 --log leg", "--shard 1/2 > ~/verify/"),
        ("no-value", "--unit pytest-x2 --shard 1/1 --log leg --passes", "--passes takes 1 or 2"),
        (
            "three",
            "--unit pytest-x2 --shard 1/1 --passes 3 --log leg",
            "--passes takes 1 or 2, got '3'",
        ),
        (
            "word",
            "--unit pytest-x2 --shard 1/1 --passes all --log leg",
            "--passes takes 1 or 2, got 'all'",
        ),
        (
            "quote",
            "--unit pytest-x2 --shard 1/1 --passes 1;id --log leg",
            "--passes takes 1 or 2, got '1;id'",
        ),
    ],
)
def test_leg_forwards_the_pass_count_verbatim(world: World, arm: str, argv: str, want: str) -> None:
    _ready(world, "bank-abc12345-pytest-x2-1of1")
    rc = world.vb("leg", "i-up1", *argv.split())
    if arm in ("one", "two", "absent"):
        assert rc == 0, world.report()
        call = world.ssh_flat(3)
        assert f"./scripts/check.sh --leg pytest-x2 {want}" in call, call
        assert arm != "absent" or "--passes" not in call
        return
    assert rc == 2, world.report()
    assert world.said(want), world.report()
    assert not (world.rec / "seq" / "_ssh").exists()


@pytest.mark.parametrize("status", [0, 1, 2])
def test_leg_passes_the_shards_own_status_through(world: World, status: int) -> None:
    _ready(world)
    world.ssh(4, "out", "gone\n")
    world.ssh(5, "out", f"{status}\n")
    world.ssh(6, "out", "the last forty lines\n")
    assert world.vb("leg", "i-up1", "--unit", "pytest-x2", "--shard", "1/2", "--log", "leg") == 0
    assert world.vb("wait", "i-up1", "leg") == status, world.report()


@pytest.mark.parametrize(
    ("arm", "argv", "want"),
    [
        ("no-unit", "i-up1 --log leg", "leg needs --unit"),
        ("no-log", "i-up1 --unit static", "leg needs --log"),
        ("no-id", "", "leg needs an instance id"),
        (
            "unknown-flag",
            "i-up1 --unit static --log leg --nonsense",
            "unknown argument '--nonsense' to leg",
        ),
        ("reclaimed", "i-up1 --unit static --log leg", "box reclaimed"),
    ],
)
def test_leg_without_a_unit_or_log_is_refused(world: World, arm: str, argv: str, want: str) -> None:
    _ready(world)
    if arm == "reclaimed":
        world.ans(STATE, "terminated")
        world.ans(
            "ec2_describe-instances__Reservations0Instances0StateReason",
            "Server.SpotInstanceTermination",
        )
    assert world.vb("leg", *argv.split()) == 2, world.report()
    assert world.said(want), world.report()
    assert not (world.rec / "seq" / "_ssh").exists()


# --- the tree pre-flight: the box against itself, then against HEAD ----------------------


def test_a_loop_over_a_box_that_is_not_on_the_pushed_tree_is_refused(world: World) -> None:
    _ready(world)
    world.ssh(1, "out", f"{'3' * 40}\n")
    world.ssh(2, "out", f"{'4' * 40}\n")
    assert world.vb("loop", "i-up1", "--log", "v1") == 2, world.report()
    assert world.said("the box's checkout is not the pushed tree")
    assert world.said("run push i-up1")
    assert _launched(world) == []
    assert not (world.vhome / "i-up1" / "v1.pid").exists()


def test_a_loop_over_a_box_holding_an_earlier_push_is_refused_by_name(world: World) -> None:
    _ready(world)
    stale = "5" * 40
    world.ssh(1, "out", f"{stale}\n")
    world.ssh(2, "out", f"{stale}\n")
    assert world.vb("loop", "i-up1", "--log", "v1") == 2, world.report()
    assert world.said(f"the box holds {stale[:12]}, HEAD measures {MAIN_SHA[:12]} — push first")
    assert world.said("scripts/verifier_box.sh push i-up1")
    assert _launched(world) == []
    assert not (world.vhome / "i-up1" / "v1.pid").exists()
    git = world.rec / "git.flat"
    assert " push " not in (git.read_text() if git.is_file() else "")


# --- a long `run` is not idle: the keepalive (GF6.3) ------------------------------------

RUN_MINUTES = 31
IDLE_MINUTES = 30
# The keepalive's sessions record the fake time they touched; the long run waits on that clock.
_RUN_HANG = """case "$*" in
*the-long-run*)
    while [ "$(cat "$DJB_FAKE_CLOCK")" -lt {end} ] && [ "$SECONDS" -lt 12 ]; do
        /bin/sleep 0.05
    done
    exit 0
    ;;
*)
    printf '%s\\n' "$(cat "$DJB_FAKE_CLOCK")" >>"$REC/touches"
    exit 0
    ;;
esac
"""
# The clock's `sleep`, through the clock's one locked writer, holding real time at the run's end.
_RUN_SLEEP = """#!/usr/bin/env bash
{advance}_n="$(_clock_advance "{clock}" "${{1:-0}}")" || exit 2
[ "$_n" -lt {end} ] || /bin/sleep 3
exit 0
"""


def test_a_long_run_keeps_the_activity_marker_fresh_for_the_childs_life(world: World) -> None:
    world.ans(STATE, "running")
    world.keyed_box()
    start = world.clock.now()
    end = start + RUN_MINUTES * 60
    world.stubs.remove("sleep")
    world.stubs.plant(
        "sleep", _RUN_SLEEP.format(advance=ADVANCE_SH, clock=world.clock.file, end=end)
    )
    for ordinal in range(1, 41):
        world.ssh(ordinal, "hang", _RUN_HANG.format(end=end))
    env = world.env(DJB_VERIFIER_IDLE_MINUTES=str(IDLE_MINUTES))
    assert world.vb("run", "i-up1", "--", "the-long-run", env=env) == 0, world.report()
    finished = world.clock.now()
    touches_file = world.rec / "touches"
    touches = [int(t) for t in touches_file.read_text().split()] if touches_file.exists() else []
    interval = IDLE_MINUTES * 60 // 3
    assert len(touches) >= RUN_MINUTES * 60 // interval, f"{len(touches)} touches over the run"
    gaps = [b - a for a, b in zip([start, *touches], touches, strict=False)]
    assert all(gap <= interval + 30 for gap in gaps), gaps
    assert finished - touches[-1] < IDLE_MINUTES * 60, (finished, touches)
    sessions = len(list((world.rec / "ssh").glob("*.flat")))
    time.sleep(1)
    assert len(list((world.rec / "ssh").glob("*.flat"))) == sessions, "a touch after the child"
