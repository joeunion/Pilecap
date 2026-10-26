"""The launch's cases: `up` driven onto a cold launch, the shell and the port in one world."""

from __future__ import annotations

import difflib
import json
import os
import re
import stat
from pathlib import Path

import pytest

from quality.tests.fixtures.box_world import NS, OWNER, RG, World
from quality.tests.test_box_push import ROOT, Record, both

pytestmark = pytest.mark.drives("quality/djb/box/launch.py")

LIFECYCLE = "ec2_describe-instances__Reservations0Instances0InstanceLifecycle"
SUBNET = "ec2_describe-subnets__Subnets0SubnetId"
PRICE = '{"terms":{"OnDemand":{"a":{"priceDimensions":{"b":{"unit":"Hrs","pricePerUnit":{"USD":"0.5804000000"}}}}}}}'  # noqa: E501
_PUB = re.compile(r"AAAAC3NzaC1lZDI1NTE5[A-Za-z0-9+/=]+")


def _blind(record: Record) -> Record:
    """The record with the fresh key pair hidden: the one thing two launches never share."""

    def hide(text: str) -> str:
        return _PUB.sub("<PUBKEY>", text)

    files = {
        name: "<PRIVATE KEY>\n"
        if name.endswith("/id_ed25519") and "PRIVATE KEY" in text
        else hide(text)
        for name, text in record.files.items()
    }
    return Record(record.rc, hide(record.out), hide(record.err), files)


def _diff(name: str, shell: str, port: str) -> str:
    lines = difflib.unified_diff(
        shell.splitlines(), port.splitlines(), f"shell {name}", f"port {name}", lineterm=""
    )
    return "\n".join(lines)


def twin(world: World, *args: str, **extra: str) -> Record:
    """Run the shell, then the port, from one world; assert every record equal; the port's."""
    shell, port = (_blind(r) for r in both(world, *args, env=world.env(**extra) if extra else None))
    assert port.rc == shell.rc, (shell, port)
    for name in sorted({*shell.files, *port.files}):
        assert port.files.get(name) == shell.files.get(name), _diff(
            name, shell.files.get(name, ""), port.files.get(name, "")
        )
    assert port.err == shell.err, _diff("stderr", shell.err, port.err)
    assert port.out == shell.out, _diff("stdout", shell.out, port.out)
    return port


def zones_ready(world: World) -> None:
    """The drive's `world_zones_ready`: the group's VPC and its three zones."""
    world.ans("ec2_describe-security-groups__SecurityGroups0VpcId", "vpc-v")
    world.ans("ec2_describe-subnets__SubnetsAvailabilityZone", f"{RG}a\t{RG}b\t{RG}c")


def refuse_launch(
    world: World, code: str, n: str = ".1", status: int = 1, *, answered: bool = False
) -> None:
    """The Nth `run-instances` refused with `code`; its answer emptied unless `answered`."""
    error = f"An error occurred ({code}) when calling the RunInstances operation\n"
    (world.rec / "err" / f"ec2_run-instances{n}").write_text(error)
    (world.rec / "rc" / f"ec2_run-instances{n}").write_text(f"{status}\n")
    if not answered:
        (world.rec / "ans" / f"ec2_run-instances{n}").write_text("")


def run_instances_args(world: World) -> list[list[str]]:
    """Every recorded `run-instances` argv, one argument per line, in order."""
    found = sorted((world.rec / "calls").glob("*.args"), key=lambda p: int(p.stem))
    lines = (path.read_text().splitlines() for path in found)
    return [args for args in lines if "run-instances" in args]


# --- 1.2 the launch the design describes ---------------------------------------------


def test_up_launches_exactly_the_box_the_design_describes(world: World) -> None:
    world.up_ready()
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    call = world.nth_call_of("run-instances", 1)
    assert call
    for want in (
        f"--region {RG}",
        "--image-id ami-v1",
        "--instance-type c7g.4xlarge",
        "MarketType=spot",
        "SpotInstanceType=one-time",
        "InstanceInterruptionBehavior=terminate",
        "--instance-initiated-shutdown-behavior terminate",
        "HttpTokens=required",
        f"--iam-instance-profile Name={NS}-verifier-box",
        "--security-group-ids sg-v",
        "VolumeSize=60",
        "VolumeType=gp3",
        "Encrypted=true",
        "Key=djb:role,Value=verifier",
        f"Key=djb:owner,Value={OWNER}",
        f"Key=djb:namespace,Value={NS}",
        f"Key=Name,Value={NS}-verifier-{OWNER}-X",
        f"Key=Project,Value={NS}",
        "Key=djb:expires,Value=2",
    ):
        assert want in call, want
    assert "--key-name" not in call
    assert "--subnet-id" not in call
    assert "us-west-2" not in call
    priv = world.vhome / "i-up1" / "id_ed25519"
    assert stat.S_IMODE(os.stat(priv).st_mode) == 0o600
    assert Path(f"{priv}.pub").read_text().rstrip("\n") in call
    assert OWNER in call
    line = next((x for x in world.out.splitlines() if x.startswith("instance   ")), "")
    assert line.startswith("instance   i-up1") and "market: spot" in line, line
    assert sum(1 for x in world.out.splitlines() if x) >= 5


def test_up_takes_an_explicit_image_id_over_the_tag_lookup(world: World) -> None:
    world.up_ready()
    world.ans("ec2_describe-images__sortby", "ami-from-the-tag")
    world.ans(
        "ec2_describe-images__Images0NameState",
        "al2023-ami-2026.0.20260917.0-kernel-6.1-arm64\tavailable",
    )
    twin(world, "up", "--for", "X", "--image-id", "ami-explicit")
    assert world.rc == 0, world.report()
    call = world.nth_call_of("run-instances", 1)
    assert "--image-id ami-explicit" in call
    assert "ami-from-the-tag" not in call
    assert world.said("ami-explicit")


@pytest.mark.parametrize("arm", ["sir", "on_demand"])
def test_up_records_the_spot_request_id(world: World, arm: str) -> None:
    world.up_ready()
    if arm == "sir":
        world.ans("ec2_run-instances", f"i-up1\tsir-0abc\t{RG}c\tspot")
        twin(world, "up", "--for", "X")
        assert world.rc == 0, world.report()
        assert "Instances[0].[InstanceId,SpotInstanceRequestId," in world.nth_call_of(
            "run-instances", 1
        )
        assert (world.vhome / "i-up1" / "spot-request").read_text() == "sir-0abc\n"
        return
    world.ans("ec2_run-instances", f"i-up1\tNone\t{RG}c\tNone")
    twin(world, "up", "--for", "X", "--on-demand")
    assert world.rc == 0, world.report()
    assert not (world.vhome / "i-up1" / "spot-request").exists()


@pytest.mark.parametrize("arm", ["spot", "on_demand"])
def test_up_prints_the_market_ec2_reports_not_the_one_it_asked_for(world: World, arm: str) -> None:
    world.up_ready()
    if arm == "spot":
        twin(world, "up", "--for", "X")
        assert world.rc == 0, world.report()
        assert "market     spot" in world.out
        assert "Placement.AvailabilityZone,InstanceLifecycle" in world.nth_call_of(
            "run-instances", 1
        )
        return
    world.ans("ec2_run-instances", f"i-up1\tNone\t{RG}c\tNone")
    twin(world, "up", "--for", "X", "--on-demand")
    assert world.rc == 0, world.report()
    assert "market     on-demand" in world.out


# --- the zone axis --------------------------------------------------------------------


@pytest.mark.parametrize("arm", ["az", "no_az"])
def test_up_with_az_launches_into_that_zones_subnet(world: World, arm: str) -> None:
    world.up_ready()
    zones_ready(world)
    world.ans(SUBNET, "subnet-b")
    if arm == "az":
        twin(world, "up", "--for", "X", "--az", f"{RG}b")
        assert world.rc == 0, world.report()
        assert "--subnet-id subnet-b" in world.nth_call_of("run-instances", 1)
        sub = world.nth_call_of("describe-subnets", 1)
        assert "Name=vpc-id,Values=vpc-v" in sub
        assert f"Name=availability-zone,Values={RG}b" in sub
        return
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    assert "--subnet-id" not in world.nth_call_of("run-instances", 1)
    assert world.op_count("ec2 describe-subnets") == 0


def test_a_zone_refusal_tries_the_next_zone_once_then_the_market_rule(world: World) -> None:
    world.up_ready()
    zones_ready(world)
    (world.rec / "ans" / f"{SUBNET}.1").write_text("subnet-b\n")
    (world.rec / "ans" / f"{SUBNET}.2").write_text("subnet-c\n")
    refuse_launch(world, "InsufficientInstanceCapacity", ".1", 255, answered=True)
    refuse_launch(world, "InsufficientInstanceCapacity", ".2", 255, answered=True)
    twin(world, "up", "--for", "X", "--az", f"{RG}b", DJB_VERIFIER_BANK_SHARD="1")
    assert world.rc == 2, world.report()
    assert world.said(f"az {RG}b refused (InsufficientInstanceCapacity); trying {RG}c")
    assert world.op_count("ec2 run-instances") == 2
    second = world.nth_call_of("run-instances", 2)
    assert "--subnet-id subnet-c" in second
    assert "MarketType=spot" in second
    assert world.said("THIS IS A BANK SHARD")
    calls = [world.nth_call_of("run-instances", i) for i in range(1, 11)]
    assert not [c for c in calls if c and "MarketType=spot" not in c]


def test_a_describe_that_has_not_caught_up_cannot_lie_about_the_market(world: World) -> None:
    world.up_ready()
    zones_ready(world)
    world.ans(SUBNET, "subnet-c")
    (world.rec / "ans" / LIFECYCLE).write_text(
        "\naws: [ERROR]: An error occurred (InvalidInstanceID.NotFound) when calling the"
        " DescribeInstances operation: The instance ID 'i-up1' does not exist\n"
    )
    world.rcf(LIFECYCLE, 255)
    twin(world, "up", "--for", "X", "--az", f"{RG}c")
    assert world.rc == 0, world.report()
    line = next((x for x in world.out.splitlines() if x.startswith("launched   ")), "")
    assert line == f"launched   i-up1   az {RG}c"
    assert "market     spot" in world.out
    calls = [world.nth_call_of("describe-instances", i) for i in range(1, 50)]
    assert not [c for c in calls if "Reservations[0].Instances[0].[InstanceLifecycle" in c]


# --- 1.3 the market: Spot, the fallback, the walls ------------------------------------


@pytest.mark.parametrize(
    "code", ["InsufficientInstanceCapacity", "SpotMaxPriceTooLow", "MaxSpotInstanceCountExceeded"]
)
def test_a_spot_refusal_falls_back_to_on_demand_and_says_which(world: World, code: str) -> None:
    world.up_ready()
    refuse_launch(world, code)
    world.ans("ec2_run-instances.2", "i-up1")
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 2
    assert "--instance-market-options" not in world.nth_call_of("run-instances", 2)
    assert f"market: on-demand (spot refused: {code})" in world.out
    first, second = run_instances_args(world)[:2]

    def unmarketed(args: list[str]) -> list[str]:
        return [
            a for a in args if "--instance-market-options" not in a and "MarketType=spot" not in a
        ]

    assert unmarketed(first) == unmarketed(second)


def test_on_demand_asked_for_is_one_call_with_no_market_options(world: World) -> None:
    world.up_ready()
    twin(world, "up", "--for", "X", "--on-demand")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 1
    assert "--instance-market-options" not in world.nth_call_of("run-instances", 1)
    assert "market: on-demand (asked for)" in world.out


def test_an_unasked_price_is_printed_as_unknown_and_says_why(world: World) -> None:
    world.up_ready()
    refuse_launch(world, "InsufficientInstanceCapacity")
    world.ans("ec2_run-instances.2", "i-up1")
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    assert world.op_count("pricing get-products") == 0
    assert world.said("DJB_VERIFIER_PRICING_REGION")


def test_the_spot_service_linked_role_refusal_is_named_as_the_prerequisite_it_is(
    world: World,
) -> None:
    world.up_ready()
    (world.rec / "err" / "ec2_run-instances").write_text(
        "An error occurred (AuthFailure.ServiceLinkedRoleCreationNotPermitted) when calling the"
        " RunInstances operation: The provided credentials do not have permission to create the"
        " service-linked role for EC2 Spot Instances.\n"
    )
    world.rcf("ec2_run-instances", 1)
    (world.rec / "ans" / "ec2_run-instances").write_text("")
    twin(world, "up", "--for", "X")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 1
    for want in (
        "ACCOUNT PREREQUISITE",
        "create-service-linked-role --aws-service-name spot.amazonaws.com",
        "verifier_bootstrap.sh",
        "--on-demand",
    ):
        assert world.said(want), want
    assert not world.said("no error code")


def test_the_ops_policy_grants_the_spot_request_read() -> None:
    policy = json.loads((ROOT / "deploy" / "iam" / "verifier-ops-policy.json").read_text())
    granted = [
        s["Sid"]
        for s in policy["Statement"]
        if "ec2:DescribeSpotInstanceRequests"
        in ([s["Action"]] if isinstance(s.get("Action"), str) else s.get("Action", []))
    ]
    assert granted
    sentence = "ec2:DescribeSpotInstanceRequests not in the ops policy"
    port = ROOT / "quality" / "djb" / "box" / "transport.py"
    assert sentence in port.read_text()
