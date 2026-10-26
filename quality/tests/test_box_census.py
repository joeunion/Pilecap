"""The box client's census, zones and pool cases, driven through `fixtures/box_world.py`."""

from __future__ import annotations

import re

import pytest

from quality.djb.box.core import iso_at as iso
from quality.djb.box.core import verifier_owner
from quality.tests.fixtures.box_world import NS, OWNER, RG, World
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives("quality/djb/box/census.py")

CENSUS = "ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
POOL = "ec2_describe-instances__sortbyReservations"
SGVPC = "ec2_describe-security-groups__SecurityGroups0VpcId"
SUBNET_ZONES = "ec2_describe-subnets__SubnetsAvailabilityZone"
LAUNCHED = "2026-09-15T10:00:00.000Z"


def census_rows(world: World, *rows: tuple[str, ...]) -> None:
    """The census listing: one tab-joined line per row."""
    world.ans(CENSUS, *("\t".join(row) for row in rows))


def pool_row(world: World, instance: str, age_min: int, ami: str, price: str) -> str:
    """One warm-pool row: `<id> <launched age_min ago> <ami> c7g.4xlarge <price>`."""
    launched = iso(world.clock.now() - age_min * 60)
    return f"{instance}\t{launched}\t{ami}\tc7g.4xlarge\t{price}"


def pool_listing(world: World, *rows: str) -> None:
    """The one fixture key `warm_pool_rows` reads."""
    world.ans(POOL, *rows)


def pool_ready(world: World) -> None:
    """A world in which a pool launch would succeed and `terminate_one` reads a verifier box."""
    world.ans("ec2_describe-images__sortby", "ami-v1")
    world.ans("ec2_describe-security-groups", "sg-v")
    world.ans("ec2_describe-instances__ReservationsInstancesInstanceId", "")
    world.ans("service-quotas_get-service-quota", "32.0")
    world.ans("ec2_describe-spot-price-history", "0.2085", "None")
    world.tagged("verifier", NS)


def out_line(world: World, pattern: str) -> bool:
    """Whether a stdout line matches `pattern` from its start (`grep -E '^…'`)."""
    return re.search(rf"^{pattern}", world.out, re.MULTILINE) is not None


def terminated(world: World) -> list[str]:
    """The `i-w<n>` ids every `terminate-instances` call named, sorted."""
    found = (re.findall(r"i-w[0-9]", c) for c in world.calls() if "terminate-instances" in c)
    return sorted(i for ids in found for i in ids)


# --- 1.4 census: the market, the image, the zone, the findings ----------------------


def test_census_prints_the_market_each_box_is_on(world: World) -> None:
    future = iso(world.clock.now() + 3 * 3600)
    census_rows(
        world,
        ("i-spot", "c7g.4xlarge", "verifier", OWNER, future, LAUNCHED, "ami-baked-7", "spot"),
        ("i-cash", "c7g.4xlarge", "verifier", OWNER, future, LAUNCHED, "ami-baked-7", "None"),
    )
    assert world.vb("census") == 0, world.report()
    assert out_line(world, "i-spot .*market spot"), world.report()
    assert out_line(world, "i-cash .*market on-demand"), world.report()
    assert "InstanceLifecycle" in world.nth_call_of("describe-instances", 1)


def test_census_prints_the_ceiling_beside_the_pool(world: World) -> None:
    now = world.clock.now()
    census_rows(
        world,
        ("i-c1", "c7g.4xlarge", "verifier", OWNER, iso(now + 3600), iso(now - 300), "ami-v1"),
    )
    (world.vhome / "ceiling").write_text("8\n")
    assert world.vb("census") == 0, world.report()
    assert "ceiling 8 (file) · pool: empty" in world.out, world.report()
    pool_listing(world, pool_row(world, "i-w1", 30, "ami-v1", "0.2085"))
    world.vb("census", env=world.env(DJB_VERIFIER_MAX_BOXES="5"))
    assert "ceiling 5 (env) · pool: 1 warm · $0.2085/h" in world.out, world.report()


def test_census_says_nothing_when_there_is_nothing(world: World) -> None:
    world.ans(CENSUS, "")
    assert world.vb("census") == 0, world.report()
    for want in ("no verifier boxes", RG, f"{NS}-verifier"):
        assert want in world.out, world.report()


def test_census_finds_an_overdue_box_and_that_is_a_finding(world: World) -> None:
    now = world.clock.now()
    past, future = iso(now - 17 * 60), iso(now + 3 * 3600)
    census_rows(
        world,
        ("i-ok", "c7g.4xlarge", "verifier", OWNER, future, LAUNCHED),
        ("i-late", "c7g.4xlarge", "verifier", OWNER, past, LAUNCHED),
    )
    assert world.vb("census") == 1, world.report()
    assert "OVERDUE" in world.out
    assert "the reaper did not fire; down it" in world.out
    assert len(re.findall(r"^i-", world.out, re.MULTILINE)) == 2, world.report()


def test_census_flags_a_bake_box_that_outlived_its_bake(world: World) -> None:
    now = world.clock.now()
    old = iso(now - 120 * 60).replace("Z", ".000Z")
    census_rows(world, ("i-bake", "c7g.2xlarge", "verifier-bake", OWNER, iso(now + 3600), old))
    assert world.vb("census") == 1, world.report()
    assert "STALE BAKE" in world.out, world.report()


def test_census_that_cannot_look_is_exit_2(world: World) -> None:
    world.ans(
        CENSUS, "An error occurred (AccessDenied) when calling the DescribeInstances operation"
    )
    world.rcf(CENSUS, 255)
    assert world.vb("census") == 2, world.report()
    assert world.said("could not look")
    assert world.said(f"aws configure --profile {NS}-verifier")


@pytest.mark.parametrize("arm", ["priced", "unpriced"])
def test_census_prints_the_pool_and_its_hourly_cost(world: World, arm: str) -> None:
    now = world.clock.now()
    exp = iso(now + 3600)
    if arm == "unpriced":
        census_rows(
            world, ("i-w1", "c7g.4xlarge", "verifier", OWNER, exp, iso(now - 1800), "ami-v1")
        )
        pool_listing(world, pool_row(world, "i-w1", 30, "ami-v1", "None"))
        world.vb("census")
        assert "i-w1 warm 30m $?/h" in world.out, world.report()
        assert world.op_count("ec2 describe-spot-price-history") == 0
        return
    census_rows(
        world,
        ("i-w1", "c7g.4xlarge", "verifier", OWNER, exp, iso(now - 1800), "ami-v1"),
        ("i-w2", "c7g.4xlarge", "verifier", OWNER, exp, iso(now - 600), "ami-v1"),
        ("i-c1", "c7g.4xlarge", "verifier", OWNER, exp, iso(now - 300), "ami-v1"),
    )
    pool_listing(
        world,
        pool_row(world, "i-w1", 30, "ami-v1", "0.2085"),
        pool_row(world, "i-w2", 10, "ami-v1", "0.2085"),
    )
    assert world.vb("census") == 0, world.report()
    assert "i-w1 warm 30m $0.2085/h" in world.out, world.report()
    assert "i-w2 warm 10m $0.2085/h" in world.out
    assert "i-c1 warm" not in world.out
    assert "pool: 2 warm · $0.4170/h" in world.out, world.report()


@pytest.mark.parametrize("arm", ["empty", "overdue"])
def test_census_with_no_pool_says_empty(world: World, arm: str) -> None:
    now = world.clock.now()
    if arm == "empty":
        census_rows(
            world,
            ("i-c1", "c7g.4xlarge", "verifier", OWNER, iso(now + 3600), iso(now - 300), "ami-v1"),
        )
        assert world.vb("census") == 0, world.report()
        assert "pool: empty" in world.out, world.report()
        return
    census_rows(
        world,
        ("i-c1", "c7g.4xlarge", "verifier", OWNER, iso(now - 7200), iso(now - 10800), "ami-v1"),
    )
    pool_listing(world, pool_row(world, "i-w1", 30, "ami-v1", "0.2085"))
    assert world.vb("census") == 1, world.report()
    assert "pool: 1 warm" in world.out, world.report()


def test_census_prints_the_image_each_box_is_running(world: World) -> None:
    future = iso(world.clock.now() + 3 * 3600)
    census_rows(world, ("i-one", "c7g.4xlarge", "verifier", OWNER, future, LAUNCHED, "ami-baked-7"))
    assert world.vb("census") == 0, world.report()
    assert "ami-baked-7" in world.out, world.report()
    assert "ImageId" in world.nth_call_of("describe-instances", 1)


@pytest.mark.parametrize("arm", ["two_zones", "short_row"])
def test_census_prints_each_boxs_zone(world: World, arm: str) -> None:
    future = iso(world.clock.now() + 3 * 3600)
    row = ("c7g.4xlarge", "verifier", OWNER, future, LAUNCHED, "ami-baked-7", "spot")
    if arm == "short_row":
        census_rows(world, ("i-old", *row))
        assert world.vb("census") == 0, world.report()
        assert "az unknown" in world.out, world.report()
        return
    census_rows(world, ("i-one", *row, f"{RG}a"), ("i-two", *row, f"{RG}c"))
    assert world.vb("census") == 0, world.report()
    assert out_line(world, f"i-one .* az {RG}a "), world.report()
    assert out_line(world, f"i-two .* az {RG}c "), world.report()
    assert "Placement.AvailabilityZone" in world.nth_call_of("describe-instances", 1)


# --- zones: the list a bank spreads across -------------------------------------------


@pytest.mark.parametrize("arm", ["ok", "empty", "no_group"])
def test_zones_lists_the_vpcs_zones_and_refuses_when_it_cannot_look(world: World, arm: str) -> None:
    world.ans(SGVPC, "None" if arm == "no_group" else "vpc-v")
    if arm == "ok":
        world.ans(SUBNET_ZONES, f"{RG}c\t{RG}a\t{RG}c\t{RG}b")
        assert world.vb("zones") == 0, world.report()
        assert world.out.replace("\n", " ") == f"{RG}a {RG}b {RG}c ", world.report()
        assert world.op_count("ec2 run-instances") == 0
        assert world.op_count("ec2 terminate-instances") == 0
        assert "Name=vpc-id,Values=vpc-v" in world.nth_call_of("describe-subnets", 1)
        return
    if arm == "empty":
        world.ans(SUBNET_ZONES, "")
        assert world.vb("zones") == 2, world.report()
        assert world.said("could not look")
        return
    assert world.vb("zones") == 2, world.report()
    assert world.said(f"{NS}-verifier")


# --- pool: the ceiling first, the trim only of what nobody claimed -------------------


def test_pool_above_the_ceiling_is_exit_2_before_any_call(world: World) -> None:
    pool_ready(world)
    assert world.vb("pool", "--want", "5") == 2, world.report()
    assert not (world.rec / "aws.ops").exists(), world.report()
    assert world.said("DJB_VERIFIER_MAX_BOXES")
    assert world.said("L-34B43A08")
    assert world.op_count("ec2 run-instances") == 0


@pytest.mark.parametrize(("want", "gone"), [("2", ["i-w1"]), ("1", ["i-w1", "i-w3"])])
def test_pool_trims_only_unclaimed_boxes(world: World, want: str, gone: list[str]) -> None:
    pool_ready(world)
    pool_listing(
        world,
        pool_row(world, "i-w1", 90, "ami-v1", "0.2085"),
        pool_row(world, "i-w2", 60, "ami-v1", "0.2085"),
        pool_row(world, "i-w3", 30, "ami-v1", "0.2085"),
    )
    for name in ("i-w1", "i-w2/claim", "i-w3"):
        (world.vhome / name).mkdir(parents=True)
    assert world.vb("pool", "--want", want) == 0, world.report()
    assert "i-w2" not in terminated(world)
    assert terminated(world) == gone, world.report()
    if want == "2":
        assert "pool: 3 warm · 0 launched · 1 trimmed" in world.out, world.report()


# --- the owner default: the environment, then git, never the ledger -----------------


def test_the_owner_default_reads_the_environment_then_git_and_never_the_ledger(
    stub_path: StubPath,
) -> None:
    stub_path.plant("git", "#!/bin/sh\nexit 1\n")
    bare = {"PATH": stub_path.path}
    assert verifier_owner({**bare, "DJB_VERIFIER_OWNER": "named-owner"}) == "named-owner"
    assert verifier_owner(bare) == "unknown"
    stub_path.remove("git")
    stub_path.plant("git", "#!/bin/sh\n[ \"$*\" = 'config user.name' ] && echo 'Git Person'\n")
    assert verifier_owner(bare) == "Git Person"
