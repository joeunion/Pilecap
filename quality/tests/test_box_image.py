"""The bake's image cases: the base, the capture, the naming, the teardown, the prune."""

from __future__ import annotations

import re

import pytest

from quality.tests.fixtures.box_world import MAIN_SHA, NS, RG, World
from quality.tests.test_box_bake import BAKE, SSH_RECIPE, bake_ready, phases_line
from quality.tests.test_box_launch import twin
from quality.tests.test_box_push import ROOT

pytestmark = pytest.mark.drives("quality/djb/box/image.py")

NAME_STATE = "ec2_describe-images__Images0NameState"
PRUNE = "ec2_describe-images__reverse"
THROTTLED = (
    "An error occurred (RequestLimitExceeded) when calling the TerminateInstances operation:"
    " Request limit exceeded."
)


def users_block(launch: str) -> str:
    """The `users:` block of the rendered cloud-config in a recorded `run-instances`."""
    found, inside = [], False
    for line in launch.split("\n"):
        if line == "users:":
            inside = True
            continue
        if re.match(r"^[a-z_]+:", line):
            inside = False
        if inside:
            found.append(line)
    return "\n".join(found)


# --- the base image and the capture -------------------------------------------------------


def test_the_base_image_is_pinned_printed_and_recorded_on_the_capture(world: World) -> None:
    bake_ready(world)
    world.ans(NAME_STATE, "al2023-ami-2026.0.20260917.0-kernel-6.1-arm64\tavailable")
    twin(world, "bake")
    assert world.rc == 0, world.report()
    for want in (
        "ami-al2023",
        "KB/s",
        "al2023-ami-2026.0.20260917.0-kernel-6.1-arm64",
        "DJB_VERIFIER_AL2023_AMI=ami-al2023",
    ):
        assert world.said(want), want
    img = world.nth_call_of("create-image", 1)
    assert "Key=djb:base-ami,Value=ami-al2023" in img
    assert "Key=djb:base-ami-name,Value=al2023-ami-2026.0.20260917.0-kernel-6.1-arm64" in img


def test_a_pinned_base_image_is_used_and_the_parameter_is_not_read(world: World) -> None:
    bake_ready(world)
    world.ans("ssm_get-parameters", "ami-whatever-is-latest-today")
    world.ans(NAME_STATE, "al2023-ami-pinned-build\tavailable")
    twin(world, "bake", DJB_VERIFIER_AL2023_AMI="ami-pinned")
    assert world.rc == 0, world.report()
    call = world.nth_call_of("run-instances", 1)
    assert "--image-id ami-pinned" in call
    assert world.op_count("ssm get-parameters") == 0
    assert "ami-whatever-is-latest-today" not in call


def test_the_image_is_named_for_the_tree_it_holds_not_local_main(world: World) -> None:
    other = "3" * 40
    bake_ready(world)
    (world.rec / "git.revparse.main").write_text(f"{ROOT}\t{other}\n")
    twin(world, "bake")
    assert world.rc == 0, world.report()
    img = world.nth_call_of("create-image", 1)
    assert f"--name {NS}-verifier-{MAIN_SHA[:8]}-" in img
    assert other[:8] not in img
    assert f"Key=djb:main,Value={MAIN_SHA}" in img
    assert f"main {MAIN_SHA[:8]}, base ami-al2023" in img
    assert f"image ami-new (main {MAIN_SHA[:8]})" in world.out
    assert world.said(f"this checkout's main is {other[:8]}")


def test_a_capture_whose_tags_are_refused_keeps_the_image_and_names_the_policy(
    world: World,
) -> None:
    bake_ready(world)
    world.rcf("ec2_create-image.1", 254)
    world.errf(
        "ec2_create-image.1",
        "An error occurred (UnauthorizedOperation) when calling the CreateImage operation: You"
        f" are not authorized to perform: ec2:CreateTags on resource: arn:aws:ec2:{RG}::snapshot/*",
    )
    world.ans("ec2_create-image.2", "ami-untagged")
    twin(world, "bake")
    assert world.rc == 1, world.report()
    assert world.op_count("ec2 create-image") == 2
    assert "--tag-specifications" in world.nth_call_of("create-image", 1)
    assert "--tag-specifications" not in world.nth_call_of("create-image", 2)
    for want in (
        "ami-untagged",
        "--image-id ami-untagged",
        "verifier_bootstrap.sh",
        "create-policy-version",
    ):
        assert world.said(want), want
    assert world.op_count("ec2 terminate-instances") == 1


# --- the recipe ---------------------------------------------------------------------------


def test_the_bake_seam_grants_the_recipe_the_root_it_needs(world: World) -> None:
    bake_ready(world)
    twin(world, "bake")
    assert world.rc == 0, world.report()
    users = users_block(world.nth_call_of("run-instances", 1))
    found = re.search(r'^BAKE_USER="\$\{DJB_VERIFIER_BAKE_USER:-(.*)\}"$', BAKE.read_text(), re.M)
    assert users and found, users
    assert f"- name: {found.group(1)}" in users
    rule = re.compile(r"^\s+sudo:\s*ALL=\(ALL\)\s+NOPASSWD:ALL(\s|$)", re.M)
    assert rule.search(users), users
    assert "sudo -n true" in BAKE.read_text()


def test_a_recipe_that_refuses_is_a_refusal_the_operator_can_read(world: World) -> None:
    bake_ready(world)
    world.ssh(SSH_RECIPE, "rc", "2\n")
    world.ssh(
        SSH_RECIPE,
        "out",
        "!! bake: the bake account cannot sudo without a password.\n"
        "   deploy/verifier/bake-user-data.yaml's users: entry is the fix.\n",
    )
    twin(world, "bake")
    assert world.rc == 2, world.report()
    assert world.said("bake-user-data.yaml")
    assert world.op_count("ec2 create-image") == 0
    assert world.op_count("ec2 terminate-instances") == 1


# --- the teardown -------------------------------------------------------------------------


def test_a_teardown_that_cannot_terminate_says_so_and_names_the_hand(world: World) -> None:
    bake_ready(world)
    (world.rec / "git.push.rc").write_text("128\n")
    (world.rec / "git.push.err").write_text("pre-push: refused\n")
    world.rcf("ec2_terminate-instances", 254)
    world.errf("ec2_terminate-instances", THROTTLED)
    twin(world, "bake")
    assert world.rc == 1, world.report()
    for want in ("could not terminate i-bake", "TAKE IT DOWN BY HAND", "down i-bake", "census"):
        assert want in world.err, want
    assert re.search(r"push.*incomplete", phases_line(world)), phases_line(world)
    assert (world.vhome / "i-bake" / "id_ed25519").is_file()


def test_a_teardown_whose_credential_expired_still_hands_over_the_id(world: World) -> None:
    bake_ready(world)
    world.ans("ec2_create-image", "None")
    world.rcf("ec2_terminate-instances", 255)
    world.errf(
        "ec2_terminate-instances",
        "An error occurred (ExpiredToken) when calling the TerminateInstances operation: The"
        " security token included in the request is expired",
    )
    twin(world, "bake")
    assert world.rc == 2, world.report()
    for want in ("could not terminate i-bake", "TAKE IT DOWN BY HAND", "ExpiredToken"):
        assert want in world.err, want
    assert "total" in phases_line(world)


def test_a_teardown_in_the_body_cannot_swallow_a_failed_terminate(world: World) -> None:
    bake_ready(world)
    world.ssh("default", "out", "bake: step 7 failed\n")
    world.rcf("ec2_terminate-instances", 254)
    world.errf("ec2_terminate-instances", THROTTLED)
    twin(world, "bake")
    assert world.rc == 2, world.report()
    for want in ("could not terminate i-bake", "TAKE IT DOWN BY HAND", "census"):
        assert want in world.err, want
    assert world.op_count("ec2 terminate-instances") == 1


# --- the prune ----------------------------------------------------------------------------


def test_bake_prune_keeps_the_newest_two(world: World) -> None:
    world.ans(
        PRUNE,
        "ami-4\tsnap-4\t2026-09-15T10:00:00Z",
        "ami-3\tsnap-3\t2026-09-14T10:00:00Z",
        "ami-2\tsnap-2\t2026-09-13T10:00:00Z",
        "ami-1\tsnap-1\t2026-09-12T10:00:00Z",
    )
    twin(world, "bake", "--prune")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 deregister-image") == 2
    assert world.op_count("ec2 delete-snapshot") == 2
    assert not any("ami-4" in call for call in world.calls())
    assert "pruned ami-1" in world.out and "pruned ami-2" in world.out


def test_bake_prune_finds_snapshots_through_the_block_mappings(world: World) -> None:
    world.ans(
        PRUNE,
        "ami-4\tsnap-4a\tsnap-4b\t2026-09-15T10:00:00Z",
        "ami-3\tsnap-3a\tsnap-3b\t2026-09-14T10:00:00Z",
        "ami-2\tsnap-2a\tsnap-2b\t2026-09-13T10:00:00Z",
        "ami-1\tsnap-1a\tsnap-1b\t2026-09-12T10:00:00Z",
    )
    twin(world, "bake", "--prune")
    assert world.rc == 0, world.report()
    query = world.nth_call_of("describe-images", 1)
    assert "BlockDeviceMappings" in query
    assert "Name=tag:" in query
    assert world.op_count("ec2 describe-snapshots") == 0
    assert world.op_count("ec2 delete-snapshot") == 4
    kept = ("snap-4a", "snap-4b", "snap-3a", "snap-3b")
    assert not any(snap in call for call in world.calls() for snap in kept)
