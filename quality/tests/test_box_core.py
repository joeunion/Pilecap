"""The box client's core cases: `quality.djb.box` driven through `fixtures/box_world.py`."""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.conftest import REAL_TIME_CEILING_S
from quality.tests.fixtures.box_world import DOWN_LOOK, LISTING, NS, OWNER, RG, World
from quality.tests.fixtures.fake_clock import FakeClock
from quality.tests.fixtures.stub_path import StubPath
from quality.tests.harness import fixtures_in

pytestmark = pytest.mark.drives("quality/djb/box/core.py")

ROOT = Path(__file__).resolve().parents[2]


# --- the seam fixtures: found by discovery, each refusing -------------------------


def test_the_seam_fixtures_are_found_by_discovery() -> None:
    found = fixtures_in(ROOT / "quality" / "tests" / "fixtures", "quality.tests.fixtures")
    assert {"stub_path", "fake_clock", "world"} <= set(found)


@pytest.mark.parametrize("name", ["", "a/b", ".", ".."])
def test_stub_path_refuses_a_name_that_is_not_a_command(stub_path: StubPath, name: str) -> None:
    with pytest.raises(CouldNotLook, match="bare command name"):
        stub_path.plant(name, "#!/bin/sh\n")


def test_stub_path_refuses_a_second_plant(stub_path: StubPath) -> None:
    stub_path.plant("aws", "#!/bin/sh\nexit 0\n")
    with pytest.raises(CouldNotLook, match="planted twice"):
        stub_path.plant("aws", "#!/bin/sh\nexit 1\n")


def test_stub_path_refuses_a_stub_exec_cannot_run(stub_path: StubPath) -> None:
    with pytest.raises(CouldNotLook, match="no `#!`"):
        stub_path.plant("aws", "exit 0\n")


def test_stub_path_refuses_a_real_tool_that_is_absent(stub_path: StubPath) -> None:
    with pytest.raises(CouldNotLook, match="no real"):
        stub_path.require_real("djb-no-such-tool")


def test_stub_path_answers_first_on_its_path(stub_path: StubPath) -> None:
    stub_path.plant("aws", "#!/bin/sh\necho stubbed\n")
    done = subprocess.run(
        ["sh", "-c", "aws"], env={"PATH": stub_path.path}, capture_output=True, text=True
    )
    assert done.stdout == "stubbed\n"


def test_fake_clock_refuses_to_run_backwards(fake_clock: FakeClock) -> None:
    with pytest.raises(CouldNotLook, match="backwards"):
        fake_clock.advance(-1)


def test_fake_clock_refuses_a_file_that_is_not_a_clock(fake_clock: FakeClock) -> None:
    fake_clock.file.write_text("soon\n")
    with pytest.raises(CouldNotLook, match="not epoch seconds"):
        fake_clock.now()


def test_fake_clock_sleep_advances_and_date_reads_it(
    fake_clock: FakeClock, stub_path: StubPath
) -> None:
    start = fake_clock.now()
    done = subprocess.run(
        ["sh", "-c", "sleep 90; date +%s"],
        env={"PATH": stub_path.path},
        capture_output=True,
        text=True,
    )
    assert done.stdout.strip() == str(start + 90)


# --- 1.1 the walls, before anything is launched -----------------------------------


@pytest.mark.parametrize("unset", ["DJB_DEPLOY_NAMESPACE", "DJB_VERIFIER_REGION"])
def test_the_wrapper_refuses_without_a_namespace_or_a_region(world: World, unset: str) -> None:
    world.up_ready()
    env = world.env()
    del env[unset]
    assert world.vb("up", "--for", "X", env=env) == 2, world.report()
    assert world.said(unset)
    assert not (world.rec / "aws.ops").exists()


def test_up_refuses_when_there_is_no_profile(world: World) -> None:
    world.up_ready()
    world.profile_absent()
    assert world.vb("up", "--for", "X") == 2, world.report()
    assert world.said("./deploy/iam/verifier_bootstrap.sh --confirm")
    assert world.said(f"aws configure --profile {NS}-verifier")
    assert world.op_count("ec2 run-instances") == 0


def test_up_refuses_when_the_session_plugin_is_absent(world: World) -> None:
    world.up_ready()
    world.stubs.remove("session-manager-plugin")
    assert world.vb("up", "--for", "X") == 2, world.report()
    assert world.said("brew install --cask session-manager-plugin")
    assert world.op_count("ec2 run-instances") == 0


def test_up_refuses_when_no_image_has_been_baked(world: World) -> None:
    world.up_ready()
    world.ans("ec2_describe-images__sortby", "None")
    assert world.vb("up", "--for", "X") == 2, world.report()
    assert world.said("verifier_box.sh bake")
    assert world.op_count("ec2 run-instances") == 0


def test_up_refuses_an_explicit_image_that_is_not_available_yet(world: World) -> None:
    world.up_ready()
    world.ans("ec2_describe-images__Images0NameState", "some-name\tpending")
    assert world.vb("up", "--for", "X", "--image-id", "ami-half-baked") == 2, world.report()
    assert world.said("pending")
    assert world.op_count("ec2 run-instances") == 0


# --- 1.6 run: the transport, the status, the reclaimed box -------------------------


def test_run_carries_the_transport_and_touches_the_activity_marker(world: World) -> None:
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
    world.keyed_box()
    assert world.vb("run", "i-up1", "--", "true") == 0, world.report()
    call = world.ssh_flat(1)
    for want in (
        "ProxyCommand=aws ssm start-session --target %h --document-name AWS-StartSSHSession",
        f"--profile {NS}-verifier",
        f"--region {RG}",
        "-o ServerAliveInterval=30",
        "verifier@i-up1",
        "touch /run/verifier/last-activity",
    ):
        assert want in call


@pytest.mark.parametrize("status", [7, 1, 2])
def test_run_passes_the_remote_status_through_unchanged(world: World, status: int) -> None:
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
    world.keyed_box()
    world.ssh("default", "rc", f"{status}\n")
    assert world.vb("run", "i-up1", "--", "false") == status, world.report()


def test_run_refuses_a_reclaimed_box_without_attempting_ssh(world: World) -> None:
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "terminated")
    world.ans(
        "ec2_describe-instances__Reservations0Instances0StateReason",
        "Server.SpotInstanceTermination",
    )
    world.keyed_box(instance="i-gone")
    assert world.vb("run", "i-gone", "--", "true") == 2, world.report()
    assert "box reclaimed (spot) i-gone" in world.out
    assert not (world.rec / "ssh" / "1.flat").exists()
    assert world.said("never red")


# --- 1.7 wait: the gate's own status, its red blocks, a box that vanished ----------


def test_wait_passes_the_gates_own_status_through(world: World) -> None:
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
    (world.keyed_box() / "v1.pid").write_text("4242\n")
    for ordinal, text in enumerate(
        ("alive", "alive", "gone", "1", "the last forty lines"), start=1
    ):
        world.ssh(ordinal, "out", f"{text}\n")
    assert world.vb("wait", "i-up1", "v1") == 1, world.report()
    assert "the last forty lines" in world.out
    assert "gate exit 1" in world.out


def _two_red_log() -> str:
    lines = [f"a member line {i}" for i in range(1, 21)]
    lines += [
        "!! COULD NOT LOOK: engine",
        "!! and RED: always_on",
        "   always_on: 1 FAILED line(s)",
        "     FAILED   case_always_one — a red above the window",
        "an unindented line that ends the first block",
        "!! RED: pm_fold sweep",
        "   pm_fold: 2 FAILED line(s)",
        "     FAILED   case_fold_one — the first red member",
        "     FAILED   case_fold_two — its second case",
        "   sweep: 1 FAILED line(s)",
        "     FAILED   case_sweep_one — the second red member",
        "   Every drive ran and every red is named above.",
        "",
    ]
    lines += [f"the fixed block, line {i}" for i in range(1, 31)]
    lines += ["!! RED: inside_the_tail", "     FAILED   case_inside — a red the tail already shows"]
    lines += [f"the fixed block, line {i}" for i in range(31, 39)]
    return "\n".join(lines) + "\n"


def test_wait_prints_every_red_block_the_tail_cannot_reach(world: World) -> None:
    """The status read is bounded by real time on the child, so a slow host cannot race it."""
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
    (world.keyed_box() / "v1.pid").write_text("4242\n")
    world.ssh(1, "out", "gone\n")
    world.ssh(2, "out", "1\n")
    assert world.vb("wait", "i-up1", "v1") == 1, world.report()
    record = world.ssh_flat(3)
    assert "~/verify/a-rung/v1.log" in record
    command = record.split(" -- ", 1)[1]
    command = command.removeprefix("touch /run/verifier/last-activity 2>/dev/null || true; ")
    log = world.root / "box-v1.log"
    log.write_text(_two_red_log())
    command = command.replace("~/verify/a-rung/v1.log", str(log))
    got = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}
    )
    text = got.stdout + got.stderr
    assert "the fixed block, line 38" in text
    for want in (
        "--- every RED block above those forty lines ---",
        "!! and RED: always_on",
        "FAILED   case_always_one — a red above the window",
        "!! RED: pm_fold sweep",
        "FAILED   case_fold_one — the first red member",
        "FAILED   case_fold_two — its second case",
        "FAILED   case_sweep_one — the second red member",
    ):
        assert want in text
    for stray in (
        "a member line 20",
        "an unindented line that ends the first block",
        "!! COULD NOT LOOK: engine",
    ):
        assert stray not in text
    assert text.count("!! RED: inside_the_tail") == 1


def test_wait_on_a_box_that_stops_answering_names_its_end(world: World) -> None:
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
    (world.keyed_box() / "v1.pid").write_text("4242\n")
    world.ssh(
        1,
        "hang",
        'printf "terminated\\n" >"$REC/ans/ec2_describe-instances__Reservations0Instances0'
        'StateName"\nprintf "Client.InstanceInitiatedShutdown\\n" >"$REC/ans/ec2_describe-'
        'instances__Reservations0Instances0StateReasonCode"\n',
    )
    started = time.monotonic()
    assert world.vb("wait", "i-up1", "v1", env=world.env(DJB_VERIFIER_WAIT_POLL_SECONDS="3")) == 2
    assert world.said("Client.InstanceInitiatedShutdown"), world.report()
    assert time.monotonic() - started < REAL_TIME_CEILING_S


def test_a_session_that_charges_the_clock_past_the_bound_still_answers(world: World) -> None:
    """The race's pin: fake time spent inside a session never ends it; only real time does."""
    world.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
    (world.keyed_box() / "v1.pid").write_text("4242\n")
    world.ssh(1, "out", "gone\n")
    world.ssh(2, "out", "1\n")
    env = world.env(DRIVE_SSH_SECONDS="1000", DJB_VERIFIER_WAIT_POLL_SECONDS="120")
    assert world.vb("wait", "i-up1", "v1", env=env) == 1, world.report()
    assert "gate exit 1" in world.out


# --- 1.5 down: the two walls, the key, the owner, a gone box, a blind call ----------


def test_down_refuses_an_instance_that_is_not_ours(world: World) -> None:
    world.tagged("None", "None")
    assert world.vb("down", "i-environment") == 2, world.report()
    assert world.said("not a verifier box")
    assert world.op_count("ec2 terminate-instances") == 0


def test_down_refuses_another_namespaces_box(world: World) -> None:
    world.tagged("verifier", "someone-else")
    assert world.vb("down", "i-theirs") == 2, world.report()
    assert world.said("someone-else")
    assert world.op_count("ec2 terminate-instances") == 0


def test_down_terminates_and_takes_the_private_key_with_it(world: World) -> None:
    world.tagged("verifier", NS)
    world.keyed_box()
    assert world.vb("down", "i-up1") == 0, world.report()
    assert world.op_count("ec2 terminate-instances") == 1
    call = world.nth_call_of("terminate-instances", 1)
    assert "--instance-ids i-up1" in call and f"--region {RG}" in call, call
    assert not (world.vhome / "i-up1").exists()
    assert "terminated i-up1" in world.out


def test_down_all_mine_leaves_other_owners_alone(world: World) -> None:
    world.ans(LISTING, "i-mine1\ti-mine2\ti-theirs")
    owner_key = "ec2_describe-instances__Reservations0Instances0TagsKeydjbowner"
    world.ans(owner_key, OWNER)
    world.ans(f"{owner_key}.1", OWNER)
    world.ans(f"{owner_key}.2", OWNER)
    world.ans(f"{owner_key}.3", "another-session")
    world.tagged("verifier", NS)
    assert world.vb("down", "--all-mine") == 0, world.report()
    assert world.op_count("ec2 terminate-instances") == 2
    assert world.said("i-theirs") and world.said("another-session")


def test_down_on_a_reclaimed_box_says_already_gone_and_is_not_a_refusal(world: World) -> None:
    world.keyed_box(instance="i-gone")
    world.ans(DOWN_LOOK, f"terminated\tServer.SpotInstanceTermination\tverifier\t{NS}")
    assert world.vb("down", "i-gone") == 0, world.report()
    assert "already gone i-gone" in world.out
    assert "Server.SpotInstanceTermination" in world.out
    assert not world.said("is not a verifier box")
    assert world.op_count("ec2 terminate-instances") == 0
    assert world.op_count("ec2 describe-instances") == 1
    assert not (world.vhome / "i-gone").exists()


def test_down_that_cannot_look_says_so_and_never_calls_it_foreign(world: World) -> None:
    world.keyed_box()
    (world.rec / "ans" / DOWN_LOOK).write_text(
        "\naws: [ERROR]: An error occurred (RequestLimitExceeded) when calling the"
        " DescribeInstances operation\n"
    )
    world.rcf(DOWN_LOOK, 255)
    assert world.vb("down", "i-up1") == 2, world.report()
    assert world.said("could not look at i-up1")
    assert (
        "could not look at i-up1: aws: [ERROR]: An error occurred (RequestLimitExceeded)"
        in world.err
    )
    assert not world.said("is not a verifier box")
    assert world.op_count("ec2 terminate-instances") == 0
    assert (world.vhome / "i-up1").is_dir()


# --- 1.4 ceiling: the three sources, the write, the quota it stands for -------------


def test_ceiling_prints_the_file_the_env_and_the_quota(world: World) -> None:
    world.ans("service-quotas_get-service-quota", "32.0")
    assert world.vb("ceiling") == 0, world.report()
    for want in (
        "ceiling 2 (default)",
        "DJB_VERIFIER_MAX_BOXES  unset",
        "/ceiling  absent",
        "default  2",
        "L-34B43A08  32.0",
    ):
        assert want in world.out, world.report()
    assert world.vb("ceiling", "6") == 0, world.report()
    assert (world.vhome / "ceiling").read_text() == "6\n"
    assert "wrote " in world.out and "ceiling 6 (file)" in world.out
    world.vb("ceiling", env=world.env(DJB_VERIFIER_MAX_BOXES="4"))
    assert "ceiling 4 (env)" in world.out and "/ceiling  6" in world.out, world.report()
    (world.vhome / "ceiling").unlink()
    world.rcf("service-quotas_get-service-quota", 255)
    world.errf("service-quotas_get-service-quota", "An error occurred (AccessDeniedException)")
    assert world.vb("ceiling") == 0, world.report()
    assert "L-34B43A08  unknown" in world.out and "could not look" in world.out


@pytest.mark.parametrize(("planted", "env"), [("1O", {}), ("", {"DJB_VERIFIER_MAX_BOXES": "lots"})])
def test_a_ceiling_file_that_is_not_a_number_is_exit_2_before_any_call(
    world: World, planted: str, env: dict[str, str]
) -> None:
    world.up_ready()
    if planted:
        (world.vhome / "ceiling").write_text(f"{planted}\n")
    assert world.vb("up", "--for", "X", env=world.env(**env)) == 2, world.report()
    assert not (world.rec / "aws.ops").exists()
    if planted:
        assert world.said("1O") and world.said("/ceiling")


# --- the dispatcher: the usage, an unknown subcommand ---------------------------------


def test_no_subcommand_prints_the_usage_and_is_exit_2(world: World) -> None:
    assert world.vb() == 2, world.report()
    assert "verifier_box.sh up --for <rung>" in world.out
    assert not (world.rec / "aws.ops").exists()


def test_an_unknown_subcommand_is_exit_2_and_names_the_known_ones(world: World) -> None:
    assert world.vb("nonsense") == 2, world.report()
    assert "unknown subcommand 'nonsense': up down pool census" in world.err
    assert not (world.rec / "aws.ops").exists()


# --- the seam's censuses: one world, one transport, one exit ---------------------------

PACKAGE = ROOT / "quality" / "djb" / "box"
SPAWNERS = ("subprocess", "os.system", "os.popen", "os.exec", "os.spawn", "pty")


def _modules() -> dict[str, ast.Module]:
    return {path.name: ast.parse(path.read_text()) for path in sorted(PACKAGE.glob("*.py"))}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


def test_the_world_is_a_fixture_file_and_this_module_defines_none() -> None:
    here = ast.parse(Path(__file__).read_text())
    defined = {node.name for node in ast.walk(here) if isinstance(node, ast.ClassDef)}
    assert "World" not in defined
    assert "world" in fixtures_in(ROOT / "quality" / "tests" / "fixtures", "quality.tests.fixtures")


def test_only_the_transport_spawns_and_the_core_only_for_its_clock() -> None:
    found: list[str] = []
    for name, tree in _modules().items():
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Call) and _dotted(node.func).startswith(SPAWNERS):
                    found.append(f"{name}::{func.name}")
    allowed = {"core.py::clock_s", "core.py::pause"}
    assert {f for f in found if not f.startswith("transport.py::")} == allowed, found
    for name, tree in _modules().items():
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        if name not in ("transport.py", "core.py"):
            assert "subprocess" not in imported, name


def test_no_module_but_the_entry_exits() -> None:
    found = []
    for name, tree in _modules().items():
        for node in ast.walk(tree):
            exits = isinstance(node, ast.Raise) and "SystemExit" in ast.unparse(node)
            calls = isinstance(node, ast.Call) and _dotted(node.func) in ("sys.exit", "exit")
            if (exits or calls) and name != "__main__.py":
                found.append(f"{name}:{getattr(node, 'lineno', 0)}")
    assert found == []


# --- the shared leaves the seam carries for its partitions ------------------------------


def test_the_checkout_path_is_the_recipes_own() -> None:
    from quality.djb.box.transport import verifier_checkout_path

    bake = ROOT / "deploy" / "verifier" / "bake.sh"
    shell = subprocess.run(
        [
            "bash",
            "-c",
            'u="$(sed -n \'s|^BAKE_USER="\\${DJB_VERIFIER_BAKE_USER:-\\(.*\\)}"$|\\1|p\' "$1")";'
            ' p="$(sed -n \'s|^BAKE_CHECKOUT="\\${DJB_VERIFIER_CHECKOUT:-\\(.*\\)}"$|\\1|p\''
            ' "$1")"; printf \'%s\\n\' "${p//\\$\\{BAKE_USER\\}/$u}"',
            "bash",
            str(bake),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert verifier_checkout_path() == shell.stdout.rstrip("\n") != ""


def test_the_boxs_measured_tree_is_its_last_line_over_the_one_transport(world: World) -> None:
    from quality.djb.box.core import load_config
    from quality.djb.box.transport import Transport

    world.keyed_box()
    world.ssh(1, "out", "\r\nnoise\r\nabc123\r\n\r\n")
    world.ssh(1, "err", "a warning the reader never sees\n")
    transport = Transport(load_config(world.env()))
    tree = transport.measured_tree_on_box("i-up1", "/home/verifier/src", "HEAD")
    assert tree == "abc123"
    assert world.ssh_flat(1).endswith(
        "cd /home/verifier/src && bash -c '. scripts/gate_ledger.sh >/dev/null 2>&1 &&"
        " gate_measured_tree_of HEAD' "
    )
