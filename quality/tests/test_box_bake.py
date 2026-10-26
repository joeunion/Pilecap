"""`bake`'s cases: the launch, the waits, the push, the recipe, the phases, `--keep`, the walls."""

from __future__ import annotations

import re

import pytest

from quality.tests.fixtures.box_world import MAIN_SHA, NS, World
from quality.tests.test_box_launch import twin
from quality.tests.test_box_push import ROOT, STATE, fresh

pytestmark = pytest.mark.drives("quality/djb/box/bake.py")

#: The sessions a bake opens: 1 the readiness probe, 2–5 the push's, 6 the recipe.
SSH_READBACK = 5
SSH_RECIPE = 6
BAKE = ROOT / "deploy" / "verifier" / "bake.sh"
BAKE_SEAM = ROOT / "deploy" / "verifier" / "bake-user-data.yaml"


def bake_ready(world: World) -> None:
    """The drive's `world_bake_ready`: a bake that would succeed, so a case removes one thing."""
    world.ans("ssm_get-parameters", "ami-al2023")
    world.ans("ec2_describe-security-groups", "sg-v")
    world.ans("ec2_run-instances", "i-bake")
    world.ans("ssm_describe-instance-information", "Online")
    world.ans(STATE, "running")
    world.ans("ec2_create-image", "ami-new")
    world.ans("ec2_describe-images__Images0State", "available")
    world.tagged("verifier-bake", NS)
    world.ssh("default", "out", "bake: ready for create-image\n")
    world.ssh(SSH_READBACK, "out", f"{MAIN_SHA}\n")


def phases_line(world: World) -> str:
    return "\n".join(line for line in world.out.splitlines() if "phases" in line)


def recipe_ran(world: World) -> bool:
    return any("bake.sh" in p.read_text() for p in (world.rec / "ssh").glob("*.flat"))


def pushed(world: World) -> bool:
    path = world.rec / "git.flat"
    return path.is_file() and "push --force" in path.read_text()


def stamp_of(epoch: int) -> str:
    return f"{epoch // 3600 % 24:02d}:{epoch // 60 % 60:02d}:{epoch % 60:02d}"


# --- the success path ---------------------------------------------------------------------


def test_bake_launches_on_demand_and_captures_a_private_image(world: World) -> None:
    bake_ready(world)
    twin(world, "bake")
    assert world.rc == 0, world.report()
    call = world.nth_call_of("run-instances", 1)
    assert "--instance-market-options" not in call
    assert re.search(r"--image-id ami-al2023 .*--instance-type c7g\.2xlarge", call, re.S), call
    assert "Key=djb:role,Value=verifier-bake" in call
    assert world.said("on-demand")
    img = world.nth_call_of("create-image", 1)
    assert re.search(rf"--instance-id i-bake .*--name {NS}-verifier-{MAIN_SHA[:8]}-", img, re.S)
    for tag in (
        "Key=djb:role,Value=verifier-image",
        f"Key=djb:namespace,Value={NS}",
        f"Key=djb:main,Value={MAIN_SHA}",
        "Key=djb:baked,Value=2",
        "ResourceType=snapshot",
    ):
        assert tag in img, tag
    assert not any("launch-permission" in c or "modify-image-attribute" in c for c in world.calls())
    assert world.op_count("ec2 terminate-instances") == 1
    assert f"image ami-new (main {MAIN_SHA[:8]})" in world.out.splitlines()[-1]


def test_bake_waits_for_the_boxs_bootstrap_before_it_pushes(world: World) -> None:
    bake_ready(world)
    twin(world, "bake")
    assert world.rc == 0, world.report()
    found = re.search(r"test -f (\S+)", world.ssh_flat(1))
    assert found, world.ssh_flat(1)
    assert found.group(1) in BAKE_SEAM.read_text()
    assert "bake.sh" in world.ssh_flat(SSH_RECIPE)
    flats = sorted((world.rec / "ssh").glob("*.flat"), key=lambda p: int(p.stem))
    before = next(n for n, p in enumerate(flats) if "bake.sh" in p.read_text())
    assert before == SSH_RECIPE - 1
    text = BAKE.read_text()
    user = re.search(r'^BAKE_USER="\$\{DJB_VERIFIER_BAKE_USER:-(.*)\}"$', text, re.M)
    path = re.search(r'^BAKE_CHECKOUT="\$\{DJB_VERIFIER_CHECKOUT:-(.*)\}"$', text, re.M)
    assert user and path
    checkout = path.group(1).replace("${BAKE_USER}", user.group(1))
    launch = world.nth_call_of("run-instances", 1)
    assert re.search(rf"init.*{re.escape(checkout)}", launch, re.S)
    assert "${VERIFIER_" not in launch
    target = f"ssh://{user.group(1)}@i-bake{checkout}"
    assert (
        f"push --force {target} refs/heads/main:refs/heads/main"
        in (world.rec / "git.flat").read_text()
    )


def test_bake_stamps_its_phases_and_prints_their_durations(world: World) -> None:
    bake_ready(world)
    (world.rec / "ans" / "ssm_describe-instance-information.1").write_text("Pending\n")
    (world.rec / "ans" / "ssm_describe-instance-information.2").write_text("Online\n")
    started = world.clock.now()
    twin(world, "bake", DRIVE_SSH_SECONDS="37", DJB_VERIFIER_MIN_KBPS="1")
    assert world.rc == 0, world.report()
    stamped = re.compile(r"^verifier_box: \[[0-9]{2}:[0-9]{2}:[0-9]{2}\] ")
    unstamped = [
        line
        for line in world.out.splitlines()
        if line.startswith("verifier_box: ") and not stamped.match(line)
    ]
    assert not unstamped, unstamped
    phases = phases_line(world)
    for want in ("online 10s", "bootstrap 37s", "push 148s", "recipe 37s", "image 0s"):
        assert want in phases, (want, phases)
    elapsed = world.clock.now() - started
    assert f"total {elapsed}s" in phases, phases
    assert phases.startswith(f"verifier_box: [{stamp_of(world.clock.now())}]"), phases


# --- the walls before the launch ----------------------------------------------------------


def test_a_namespace_that_is_not_ascii_refuses_before_a_box_is_launched(world: World) -> None:
    bake_ready(world)
    twin(world, "bake", DJB_DEPLOY_NAMESPACE="drivéns")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 0
    assert world.op_count("ec2 create-image") == 0
    assert world.said("ASCII")


def test_bake_refuses_before_the_launch_when_there_is_no_local_main(world: World) -> None:
    bake_ready(world)
    (world.rec / "git.no-main").write_text(f"{ROOT}\n")
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 0
    assert world.op_count("ec2 create-image") == 0
    for want in ("NO local refs/heads/main", "git branch main HEAD", "setup.sh", "--loop scope"):
        assert world.said(want), want


# --- every way out takes the builder down -------------------------------------------------


def test_bake_terminates_its_builder_when_the_bootstrap_never_finishes(world: World) -> None:
    bake_ready(world)
    world.ssh("default", "rc", "1\n")
    started = world.clock.now()
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert not pushed(world)
    assert world.op_count("ec2 create-image") == 0
    assert world.op_count("ec2 terminate-instances") == 1
    elapsed = world.clock.now() - started
    named = re.findall(r"[0-9]+s", world.err)
    assert named, world.err
    assert abs(int(named[-1][:-1]) - elapsed) <= 10, (named, elapsed)
    assert elapsed >= 600


def test_bake_terminates_its_builder_when_the_recipe_fails(world: World) -> None:
    bake_ready(world)
    world.ssh("default", "out", "bake: step 7 failed\n")
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 create-image") == 0
    assert world.op_count("ec2 terminate-instances") == 1
    assert world.said("terminated")


def test_bake_terminates_its_builder_when_the_recipe_session_fails(world: World) -> None:
    bake_ready(world)
    world.ssh(SSH_RECIPE, "rc", "3\n")
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 create-image") == 0
    assert world.op_count("ec2 terminate-instances") == 1
    assert "exit 3" in world.err


def test_bake_terminates_its_builder_when_the_push_is_refused(world: World) -> None:
    bake_ready(world)
    (world.rec / "git.push.rc").write_text("128\n")
    (world.rec / "git.push.err").write_text("pre-push: refused\nerror: failed to push some refs\n")
    twin(world, "bake")
    assert world.rc == 1, world.report()
    assert "terminate-instances --instance-ids i-bake" in world.nth_call_of(
        "terminate-instances", 1
    )
    assert world.op_count("ec2 terminate-instances") == 1
    assert world.op_count("ec2 create-image") == 0
    assert not recipe_ran(world)
    assert world.said("terminated i-bake")
    assert re.search(r"push.*incomplete", phases_line(world)), phases_line(world)


def test_bake_terminates_its_builder_when_the_agent_never_registers(world: World) -> None:
    bake_ready(world)
    world.ans("ssm_describe-instance-information", "Pending")
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 terminate-instances") == 1
    assert not (world.rec / "ssh" / "1.flat").exists()
    assert "down i-bake" not in world.err
    assert "online 300s (incomplete)" in phases_line(world)


def test_bake_terminates_its_builder_when_the_wrapper_is_killed(world: World) -> None:
    bake_ready(world)
    world.ssh(1, "signal", "TERM\n")
    world.ssh("default", "rc", "1\n")
    twin(world, "bake")
    assert world.rc == 143, world.report()
    assert world.op_count("ec2 terminate-instances") == 1
    assert world.said("terminated i-bake")
    assert world.op_count("ec2 create-image") == 0


def test_bake_terminates_its_builder_when_the_image_never_lands(world: World) -> None:
    bake_ready(world)
    world.ans("ec2_create-image", "None")
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 terminate-instances") == 1
    assert world.said("terminated i-bake")


# --- --keep ---------------------------------------------------------------------------


def test_bake_keep_leaves_the_box_up_when_the_recipe_fails(world: World) -> None:
    bake_ready(world)
    world.ssh(SSH_RECIPE, "rc", "3\n")
    twin(world, "bake", "--keep")
    assert world.rc == 3, world.report()
    assert world.op_count("ec2 terminate-instances") == 0
    assert world.op_count("ec2 create-image") == 0
    for want in ("i-bake IS STILL UP", "down i-bake", "census", "no reaper", "bake.sh --plan"):
        assert want in world.err, want
    key_line = next((x for x in world.err.splitlines() if "ssh -i" in x), "")
    assert re.search(
        rf"{re.escape(str(world.vhome))}/i-bake/id_ed25519.*ProxyCommand=.*verifier@i-bake",
        key_line,
    ), key_line
    assert re.search(r"recipe.*incomplete", phases_line(world)), phases_line(world)


def test_bake_keep_still_tears_down_every_box_it_does_not_cover(world: World) -> None:
    bake_ready(world)
    (world.rec / "git.push.rc").write_text("128\n")
    (world.rec / "git.push.err").write_text("pre-push: refused\n")
    twin(world, "bake", "--keep")
    assert world.rc == 1, world.report()
    assert world.op_count("ec2 terminate-instances") == 1

    bake_ready(fresh(world))
    world.ssh("default", "rc", "1\n")
    twin(world, "bake", "--keep")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 terminate-instances") == 1

    bake_ready(fresh(world))
    world.ssh(1, "signal", "TERM\n")
    world.ssh("default", "rc", "1\n")
    twin(world, "bake", "--keep")
    assert world.rc == 143, world.report()
    assert world.op_count("ec2 terminate-instances") == 1

    bake_ready(fresh(world))
    twin(world, "bake", "--keep")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 terminate-instances") == 1

    bake_ready(fresh(world))
    twin(world, "bake", "--kepe")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 0


def test_bake_keep_leaves_the_box_up_when_the_capture_produces_nothing(world: World) -> None:
    bake_ready(world)
    world.ans("ec2_create-image", "None")
    twin(world, "bake", "--keep")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 terminate-instances") == 0
    assert "create-image returned no image id" in world.err
    assert "i-bake IS STILL UP" in world.err


# --- the clock is the seam ------------------------------------------------------------


def test_a_bake_session_that_charges_the_clock_past_its_bound_still_answers(world: World) -> None:
    bake_ready(world)
    twin(world, "bake", DRIVE_SSH_SECONDS="1000", DJB_VERIFIER_MIN_KBPS="1")
    assert world.rc == 0, world.report()
    phases = phases_line(world)
    assert "bootstrap 1000s" in phases and "recipe 1000s" in phases, phases
