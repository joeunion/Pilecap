"""The box client's harvest cases: `harvest`, `harvest-drives`, `fetch`, and `wait` calling them."""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb.box.core import red_blocks_command
from quality.djb.box.harvest import box_rows_command
from quality.djb.box.transport import verifier_box_user, verifier_checkout_path
from quality.tests.fixtures.box_world import MAIN_SHA, NS, RG, World

pytestmark = pytest.mark.drives("quality/djb/box/harvest.py")

ROOT = Path(__file__).resolve().parents[2]
HARVEST = ROOT / "quality" / "djb" / "box" / "harvest.py"
STATE = "ec2_describe-instances__Reservations0Instances0StateName"
REASON = "ec2_describe-instances__Reservations0Instances0StateReason"
LOCAL_LEDGER_ROW = (
    "v1 loop-v1:" + "9" * 64 + " loop 2026-09-17T09:00:00Z caller=unstated scope=apps.core"
    " passes=1 tree=dddd444 env=envddd waited=0 took=90"
)


def hex64(char: str) -> str:
    return char * 64


def box_loop_ledger() -> str:
    """The box's three loop rows in the retired `loop-v1 …` shape; the log names the middle one."""
    rows = [
        ("a", "10:00:00", "aaaa111", "envaaa", "h1", "m1", 101),
        ("b", "10:05:00", "bbbb222", "envbbb", "h2", "m2", 136),
        ("c", "10:10:00", "cccc333", "envccc", "h3", "m3", 140),
    ]
    return "".join(
        f"loop-v1 loop-v1:{hex64(c)} loop 2026-09-18T{t}Z caller=unstated scope=apps.example"
        f" passes=1 tree={tree} env={env} head={head} merge-base={mb} waited=0 took={took}\n"
        for c, t, tree, env, head, mb, took in rows
    )


def box_loop_rows_now() -> str:
    """The same three rows in the one grammar."""
    return "".join(f"v1 {line[len('loop-v1 ') :]}\n" for line in box_loop_ledger().splitlines())


def box_loop_log() -> str:
    """A `--loop` log banking the middle row's key, as `check.sh` prints it."""
    return (
        "ok: loop checks passed (136s)\n"
        "  banked: this --loop verdict, keyed on tree + environment + scope.\n"
        f"          loop-v1:{hex64('b')}\n"
        "          tree=bbbb222\n"
        "          env=envbbb\n"
        "          scope=apps.example\n"
    )


def harvest_ready(world: World) -> Path:
    """A running box keyed for `a-rung`, and a local ledger holding one row; its path."""
    world.ans(STATE, "running")
    world.keyed_box()
    ledger = world.root / "gate-verdicts"
    ledger.write_text(f"{LOCAL_LEDGER_ROW}\n")
    return ledger


def lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line]


def nth_row(text: str, n: int) -> str:
    return text.splitlines()[n - 1]


# --- 1.7b harvest: the builder's box-banked --loop row comes home ----------------------


@pytest.mark.parametrize("rows", [box_loop_ledger, box_loop_rows_now], ids=["retired", "one"])
def test_harvest_brings_exactly_the_banked_row_home(world: World, rows: Callable[[], str]) -> None:
    gl = harvest_ready(world)
    world.ssh(1, "out", box_loop_log())
    world.ssh(2, "out", rows())
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=world.env(DJB_GATE_LEDGER=str(gl))) == 0
    assert len(lines(gl)) == 2, world.report()
    assert lines(gl)[0] == LOCAL_LEDGER_ROW
    assert lines(gl)[1] == f"{nth_row(box_loop_rows_now(), 2)} box=i-up1"
    assert f"harvested: loop-v1:{hex64('b')} tree=bbbb222 box=i-up1" in world.out
    assert f"banked: tree bbbb222 key loop-v1:{hex64('b')} box=i-up1" in world.out
    tree = ast.parse(HARVEST.read_text())
    called = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert "ledger.append" in called, "the row is not appended through the one writer"
    assert not {c for c in called if c.endswith(("open", "write_text", "write"))}, "a second writer"


@pytest.mark.parametrize("arm", ["nothing_banked", "no_row"])
def test_harvest_refuses_a_log_that_banked_nothing(world: World, arm: str) -> None:
    gl = harvest_ready(world)
    if arm == "nothing_banked":
        world.ssh(
            1,
            "out",
            "ok: loop checks passed (136s)\n"
            "  not banked: --mine — the closure was not walked, so this green is a\n"
            "  claim about one app.\n",
        )
        world.ssh(2, "out", box_loop_ledger())
    else:
        world.ssh(1, "out", box_loop_log())
        world.ssh(2, "out", "".join(nth_row(box_loop_ledger(), n) + "\n" for n in (1, 3)))
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=world.env(DJB_GATE_LEDGER=str(gl))) == 2
    assert len(lines(gl)) == 1
    needle = "banks no verdict" if arm == "nothing_banked" else hex64("b")
    assert world.said(needle), world.report()


@pytest.mark.parametrize("arm", ["banked", "nothing"])
def test_a_green_wait_brings_the_loop_row_home(world: World, arm: str) -> None:
    gl = harvest_ready(world)
    name = "loop-a-rung" if arm == "banked" else "leg"
    (world.vhome / "i-up1" / f"{name}.pid").write_text("4242\n")
    tail = (
        [box_loop_log(), box_loop_ledger()] if arm == "banked" else ["ok: static checks passed\n"]
    )
    for ordinal, text in enumerate(["gone\n", "0\n", "the last forty lines\n", *tail], start=1):
        world.ssh(ordinal, "out", text)
    assert world.vb("wait", "i-up1", name, env=world.env(DJB_GATE_LEDGER=str(gl))) == 0
    if arm == "banked":
        assert lines(gl)[1:] == [f"{nth_row(box_loop_rows_now(), 2)} box=i-up1"], world.report()
        assert f"banked: tree bbbb222 key loop-v1:{hex64('b')} box=i-up1" in world.out
    else:
        assert len(lines(gl)) == 1
        assert "wait: no loop row came home" in world.out, world.report()


def test_harvest_twice_is_one_row(world: World) -> None:
    gl = harvest_ready(world)
    world.ssh(1, "out", box_loop_log())
    world.ssh(2, "out", box_loop_ledger())
    world.ssh(4, "out", box_loop_log())
    world.ssh(5, "out", box_loop_ledger())
    env = world.env(DJB_GATE_LEDGER=str(gl))
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=env) == 0, world.report()
    before = gl.read_text()
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=env) == 0, world.report()
    assert gl.read_text() == before
    assert world.said("already harvested")


def test_harvest_brings_the_drive_rows_of_the_banked_tree(world: World) -> None:
    harvest_ready(world)
    world.ssh(1, "out", box_loop_log())
    world.ssh(2, "out", box_loop_ledger())
    box1 = "v1 drive-v1:box1 drive 2026-09-18T10:05:01Z sweep exit=0 took=9 tree=bbbb222 parts=p:1"
    box2 = "v1 drive-v1:box2 drive 2026-09-18T10:05:02Z db_pin exit=0 took=4 tree=bbbb222 parts=p:2"
    other = (
        "v1 drive-v1:other drive 2026-09-18T09:00:00Z sweep exit=0 took=9 tree=zzzz999 parts=p:9"
    )
    world.ssh(3, "out", f"{box1}\n{other}\n{box2}\n")
    gl = world.root / "gate-verdicts"
    kept = "v1 drive-v1:mine drive 2026-09-17T08:00:00Z sweep exit=0 took=9 tree=dddd444 parts=p:0"
    gl.write_text(f"{kept}\n")
    env = world.env(DJB_GATE_LEDGER=str(gl))
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=env) == 0, world.report()
    assert sum(" drive " in line for line in lines(gl)) == 3
    assert lines(gl)[0] == kept
    assert box1 in lines(gl) and box2 in lines(gl)
    assert "drive-v1:other" not in gl.read_text()
    assert "drive rows: 2 brought home at tree=bbbb222" in world.out

    world.ssh(4, "out", box_loop_log())
    world.ssh(5, "out", box_loop_ledger())
    world.ssh(6, "out", f"{box1}\n{other}\n{box2}\n")
    before = gl.read_text()
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=env) == 0, world.report()
    assert gl.read_text() == before
    assert "drive rows: 0 brought home at tree=bbbb222 (2 already here)" in world.out


def test_the_harvests_remote_lines_are_the_shells_bytes(world: World) -> None:
    """The three lines the box executes for a harvest, byte for byte as the shell sends them."""
    gl = harvest_ready(world)
    world.ssh(1, "out", box_loop_log())
    world.ssh(2, "out", box_loop_ledger())
    assert world.vb("harvest", "i-up1", "loop-a-rung", env=world.env(DJB_GATE_LEDGER=str(gl))) == 0
    checkout = verifier_checkout_path()
    reader = ". scripts/gate_ledger.sh >/dev/null 2>&1 && declare -F ledger_rows >/dev/null &&"
    marker = "touch /run/verifier/last-activity 2>/dev/null || true; "
    want = [
        "cat ~/verify/a-rung/loop-a-rung.log",
        f"cd {checkout} && {{ bash -c '{reader} ledger_rows loop'"
        " || cat .git/djb-loop-verdicts; }",
        f"cd {checkout} && {{ bash -c '{reader} ledger_rows drive'"
        " || cat .git/djb-gate-verdicts; }",
    ]
    for n, command in enumerate(want, start=1):
        assert world.ssh_flat(n).endswith(f" -- {marker}{command} "), world.ssh_flat(n)
    assert box_rows_command(checkout, "loop", "djb-loop-verdicts") == want[1]


# --- 1.3c harvest-drives: the rows a shard banked, with no loop row ---------------------


def test_harvest_drives_brings_the_boxs_rows_home_once(world: World) -> None:
    world.ans(STATE, "running")
    world.keyed_box()
    tree = MAIN_SHA
    gl = world.root / "verdicts"
    gl.write_text("")
    world.ssh(
        1,
        "out",
        f"v1 drive-v1:aaa drive 2026-09-18T00:00:00Z selftest exit=0 took=3 tree={tree}"
        " parts=scripts/tests/test_a.sh\n"
        f"v1 drive-v1:bbb drive 2026-09-18T00:00:01Z sweep exit=0 took=4 tree={tree}"
        " parts=scripts/tests/test_b.sh\n"
        f"v1 drive-v1:ccc drive 2026-09-18T00:00:02Z sweep exit=0 took=4 tree={'0' * 40}"
        " parts=scripts/tests/test_b.sh\n"
        f"v1 {tree} full 2026-09-18T00:00:03Z static,pytest caller=pm-bank\n",
    )
    env = world.env(DJB_GATE_LEDGER=str(gl))
    assert world.vb("harvest-drives", "i-up1", tree, env=env) == 0, world.report()
    assert len(lines(gl)) == 2
    assert " full " not in gl.read_text()
    assert world.said("drive rows: 2 brought home")

    world.ssh(2, "out", (world.rec / "ssh" / "1.out").read_text())
    assert world.vb("harvest-drives", "i-up1", tree, env=env) == 0, world.report()
    assert len(lines(gl)) == 2
    assert world.said("(2 already here)")


def test_harvest_drives_without_a_tree_is_refused(world: World) -> None:
    assert world.vb("harvest-drives", "i-up1") == 2
    assert world.said("harvest-drives takes"), world.report()


# --- fetch: the same transport --------------------------------------------------------


def test_fetch_uses_the_same_transport(world: World) -> None:
    world.ans(STATE, "running")
    world.keyed_box()
    local = world.root / "v1.log"
    assert world.vb("fetch", "i-up1", "~/verify/x/v1.log", str(local)) == 0, world.report()
    calls = (world.rec / "scp.flat").read_text().splitlines()
    assert len(calls) == 1
    assert "ProxyCommand=aws ssm start-session" in calls[0]
    assert "verifier@i-up1:~/verify/x/v1.log" in calls[0]


def test_fetchs_argv_is_the_shells_bytes(world: World) -> None:
    """The scp line, byte for byte as `cmd_fetch` builds it in the shell."""
    world.ans(STATE, "running")
    key = world.keyed_box() / "id_ed25519"
    local = world.root / "v1.log"
    assert world.vb("fetch", "i-up1", "~/verify/x/v1.log", str(local)) == 0, world.report()
    proxy = (
        "aws ssm start-session --target %h --document-name AWS-StartSSHSession"
        f" --parameters portNumber=%p --profile {NS}-verifier --region {RG}"
    )
    want = (
        f"-i {key} -o ProxyCommand={proxy} -o StrictHostKeyChecking=no"
        " -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
        f" {verifier_box_user()}@i-up1:~/verify/x/v1.log {local} \n"
    )
    assert (world.rec / "scp.flat").read_text() == want


# --- a reclaimed box: the Spot status beside the reclaim -------------------------------


def reclaimed_box(world: World) -> Path:
    world.ans(STATE, "terminated")
    world.ans(REASON, "Server.SpotInstanceTermination")
    directory = world.keyed_box(instance="i-gone")
    (directory / "loop-x.pid").write_text("4242\n")
    return directory


@pytest.mark.parametrize("arm", ["recorded", "unrecorded"])
def test_wait_on_a_reclaimed_box_prints_the_spot_status_code(world: World, arm: str) -> None:
    directory = reclaimed_box(world)
    if arm == "unrecorded":
        assert world.vb("wait", "i-gone", "loop-x") == 2, world.report()
        assert "status unrecorded" in world.out
        assert world.op_count("ec2 describe-spot-instance-requests") == 0
        return
    (directory / "spot-request").write_text("sir-0abc\n")
    world.ans(
        "ec2_describe-spot-instance-requests",
        "instance-terminated-no-capacity\tThere is no Spot capacity available",
    )
    assert world.vb("wait", "i-gone", "loop-x") == 2, world.report()
    assert "box reclaimed (spot) i-gone status instance-terminated-no-capacity" in world.out
    assert "There is no Spot capacity available" in world.out
    assert "sir-0abc" in world.nth_call_of("describe-spot-instance-requests", 1)


def test_a_status_the_policy_cannot_read_is_named_not_hidden(world: World) -> None:
    (reclaimed_box(world) / "spot-request").write_text("sir-0abc\n")
    world.errf(
        "ec2_describe-spot-instance-requests",
        "\naws: [ERROR]: An error occurred (UnauthorizedOperation) when calling the"
        " DescribeSpotInstanceRequests operation",
    )
    world.rcf("ec2_describe-spot-instance-requests", 255)
    assert world.vb("wait", "i-gone", "loop-x") == 2, world.report()
    assert "status unreadable" in world.out
    assert "ec2:DescribeSpotInstanceRequests not in the ops policy" in world.out
    assert "box reclaimed (spot) i-gone" in world.out


# --- the whole log comes home on a red or a could-not-look -----------------------------

COPYING_SCP = r"""#!/usr/bin/env bash
printf '%s ' "$@" >>"$REC/scp.flat"
printf '\n' >>"$REC/scp.flat"
_src="${@: -2:1}"
_remote="${_src#*:}"
_remote="${_remote/#\~\//$REC/box/}"
[ -f "$_remote" ] || { echo "scp: ${_src#*:}: No such file or directory" >&2; exit 1; }
cp "$_remote" "${@: -1}"
"""


def planted_red_log() -> str:
    """A leg's red above the forty-line window, in no `!! RED:` block the tail's reader prints."""
    return (
        "   pytest: 1 FAILED line(s)\n"
        "E   AssertionError: the planted red leg above the window\n"
        + "".join(f"the fixed block, line {i}\n" for i in range(1, 51))
    )


@pytest.mark.parametrize("status", [1, 2, 0])
def test_a_red_wait_brings_the_whole_log_home(world: World, status: int) -> None:
    """The caller holds the planted red only through the fetched file; a green fetches nothing."""
    world.stubs.remove("scp")
    world.stubs.plant("scp", COPYING_SCP)
    world.ans(STATE, "running")
    (world.keyed_box() / "v1.pid").write_text("4242\n")
    box_log = world.rec / "box" / "verify" / "a-rung" / "v1.log"
    box_log.parent.mkdir(parents=True)
    box_log.write_text(planted_red_log())
    tail = subprocess.run(
        ["bash", "-c", red_blocks_command(str(box_log))],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    ).stdout
    for ordinal, text in enumerate(["gone\n", f"{status}\n", tail], start=1):
        world.ssh(ordinal, "out", text)
    logs = world.root / "caller-scratch"
    env = world.env(DJB_VERIFIER_LOG_DIR=str(logs), DJB_GATE_LEDGER=str(world.root / "gl"))
    assert world.vb("wait", "i-up1", "v1", env=env) == status, world.report()
    assert "the planted red leg" not in world.out + world.err
    fetched = logs / "i-up1-v1.log"
    if status == 0:
        assert not (world.rec / "scp.flat").exists(), "a green fetched the log"
        assert not fetched.exists()
        return
    assert f"--- the whole log: {fetched} ---" in world.out, world.report()
    assert "AssertionError: the planted red leg above the window" in fetched.read_text()
    assert len((world.rec / "scp.flat").read_text().splitlines()) == 1
