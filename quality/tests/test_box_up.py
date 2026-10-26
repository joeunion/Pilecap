"""`up`'s cases: the walls, the warm claim, the market rule's walls and the push through `up`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quality.tests.fixtures.box_world import MAIN_SHA, NS, RG, SUBJECT, World
from quality.tests.test_box_census import pool_listing, pool_row
from quality.tests.test_box_launch import PRICE, SUBNET, refuse_launch, twin, zones_ready
from quality.tests.test_box_push import ROOT

pytestmark = pytest.mark.drives("quality/djb/box/up.py")

BASE = "4" * 40
IDLE_TAG = "ec2_describe-instances__Reservations0Instances0TagsKeydjbidleVal"


def warm_key(world: World, instance: str, home: Path | None = None) -> None:
    """A warm box this machine holds the key to."""
    directory = (home or world.vhome) / instance
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "id_ed25519").write_text("key\n")


def forked(world: World, revlist: str) -> None:
    """The rung `revlist` commits past its fork point `BASE`."""
    (world.rec / "git.mergebase").write_text(f"{BASE}\n")
    (world.rec / "git.revlist").write_text(f"{revlist}\n")


def git_flat(world: World) -> str:
    path = world.rec / "git.flat"
    return path.read_text() if path.is_file() else ""


def ssh_pushes(world: World) -> list[str]:
    return [line for line in git_flat(world).splitlines() if "push --force ssh://" in line]


# --- 1.1/1.2 the walls and the lifetime ----------------------------------------------


def test_up_refuses_a_lifetime_above_the_cap(world: World) -> None:
    world.up_ready()
    twin(world, "up", "--for", "X", "--ttl", "13")
    assert world.rc == 2, world.report()
    assert not (world.rec / "aws.ops").exists()
    assert world.said("cap")


def test_up_carries_a_shorter_lifetime_and_idle_through(world: World) -> None:
    world.up_ready()
    twin(world, "up", "--for", "X", "--ttl", "2", "--idle", "10")
    assert world.rc == 0, world.report()
    call = world.nth_call_of("run-instances", 1)
    assert "/etc/verifier/idle-minutes" in call
    assert 'content: "10"' in call
    tag = call.split("Key=djb:expires,Value=", 1)[1].split("}", 1)[0]
    assert tag and f'content: "{tag}"' in call, tag
    assert world.said("ttl 2h")


def test_up_names_the_box_before_anything_can_fail_after_the_launch(world: World) -> None:
    world.up_ready()
    twin(world, "up", "--for", "X", DJB_VERIFIER_MIN_KBPS="999999999")
    assert world.rc == 2, world.report()
    line = next((x for x in world.out.splitlines() if x.startswith("launched   ")), "")
    assert line == f"launched   i-up1   az {RG}c", line
    fields = line.split()
    assert fields[1] == "i-up1" and fields[2] == "az" and fields[3] == f"{RG}c"
    assert world.said("KB/s")


# --- 1.3 the market rule's walls -----------------------------------------------------


def test_a_bank_shard_never_falls_back_to_on_demand_silently(world: World) -> None:
    world.up_ready()
    refuse_launch(world, "InsufficientInstanceCapacity")
    world.ans("ec2_run-instances.2", "i-up1")
    twin(world, "up", "--for", "X", DJB_VERIFIER_BANK_SHARD="1")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 1
    for want in ("InsufficientInstanceCapacity", "DJB_VERIFIER_ON_DEMAND_OK", "could not launch"):
        assert world.said(want), want
    assert world.said("on-demand")


def test_a_bank_shard_with_the_valve_buys_on_demand_and_prints_the_reason(world: World) -> None:
    world.up_ready()
    world.ans("pricing_get-products", PRICE)
    refuse_launch(world, "InsufficientInstanceCapacity")
    world.ans("ec2_run-instances.2", "i-up1")
    reason = "the Spot pool is empty in this AZ and the wave has to finish today"
    twin(
        world,
        "up",
        "--for",
        "X",
        DJB_VERIFIER_BANK_SHARD="1",
        DJB_VERIFIER_ON_DEMAND_OK=reason,
        DJB_VERIFIER_PRICING_REGION=RG,
    )
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 2
    assert world.said(reason)
    assert world.said("0.5804")


def test_a_single_up_keeps_the_fallback_and_prints_the_price(world: World) -> None:
    world.up_ready()
    world.ans("pricing_get-products", PRICE)
    refuse_launch(world, "InsufficientInstanceCapacity")
    world.ans("ec2_run-instances.2", "i-up1")
    twin(world, "up", "--for", "X", DJB_VERIFIER_PRICING_REGION=RG)
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 2
    assert world.said("0.5804")


# --- the warm pool: claimed, skipped, raced -------------------------------------------


def test_up_claims_a_warm_box_and_launches_nothing(world: World) -> None:
    world.up_ready()
    pool_listing(world, pool_row(world, "i-w1", 12, "ami-v1", "0.2085"))
    warm_key(world, "i-w1")
    twin(world, "up", "--for", "V-boxpool")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 0
    assert "claimed i-w1 (warm, 12m)" in world.out
    assert (world.vhome / "i-w1" / "claim").is_dir()
    tagged = "".join(c for c in world.calls() if "create-tags" in c)
    assert "i-w1" in tagged and "djb:for" in tagged and "V-boxpool" in tagged
    assert (world.vhome / "i-w1" / "rung").read_text().rstrip("\n") == "V-boxpool"
    assert "tree       HEAD" in world.out


def test_a_claimed_box_summarises_its_own_idle_tag(world: World) -> None:
    world.up_ready()
    pool_listing(world, pool_row(world, "i-w1", 12, "ami-v1", "0.2085"))
    world.ans(IDLE_TAG, "45")
    warm_key(world, "i-w1")
    twin(world, "up", "--for", "V-boxpool")
    assert world.rc == 0, world.report()
    assert "idle: 45m" in world.out


@pytest.mark.parametrize("arm", ["old_image", "no_key"])
def test_a_warm_box_on_another_image_or_without_a_key_is_skipped_by_name(
    world: World, arm: str
) -> None:
    world.up_ready()
    if arm == "old_image":
        pool_listing(world, pool_row(world, "i-w1", 20, "ami-old", "0.2085"))
        warm_key(world, "i-w1")
        twin(world, "up", "--for", "X")
        assert world.rc == 0, world.report()
        assert world.said("skipped i-w1: image ami-old ≠ ami-v1")
        assert world.op_count("ec2 run-instances") == 1
        return
    pool_listing(world, pool_row(world, "i-w2", 20, "ami-v1", "0.2085"))
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    assert world.said("skipped i-w2: no key on this machine")
    assert world.op_count("ec2 run-instances") == 1
    assert not (world.vhome / "i-w2" / "claim").is_dir()


def test_a_warm_claim_says_the_zone_you_typed_applied_to_nothing(world: World) -> None:
    world.up_ready()
    zones_ready(world)
    world.ans(SUBNET, "subnet-c")
    pool_listing(world, pool_row(world, "i-warm1", 12, "ami-v1", "0.19"))
    warm_key(world, "i-warm1")
    twin(world, "up", "--for", "X", "--az", f"{RG}c")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 0
    assert world.said(f"--az {RG}c you typed applied to nothing")
    assert world.said("CLAIMED warm")
    assert world.op_count("ec2 describe-subnets") == 0


def _side(world: World, name: str) -> World:
    """A second world beside `world`: its own records, the same stubs and clock."""
    side = World(world.root / name, world.stubs, world.clock)
    for sub in ("ans", "err", "rc", "seq", "calls", "ssh"):
        (side.rec / sub).mkdir(parents=True)
    (side.home / ".aws").mkdir(parents=True)
    side.vhome.mkdir()
    (side.home / ".aws" / "config").write_text(
        f"[default]\nregion = us-west-2\n\n[profile {NS}-verifier]\nregion = {RG}\n"
    )
    side.ssh("default", "out", f"{MAIN_SHA}\n")
    (side.rec / "git.revparse").write_text(f"{MAIN_SHA}\n")
    return side


def test_two_claims_of_one_warm_box_yield_one_winner(world: World) -> None:
    shared = world.root / "claim_race_home"
    warm_key(world, "i-w1", shared)
    sides = [_side(world, "race-a"), _side(world, "race-b")]
    children = []
    for name, side in zip("ab", sides, strict=True):
        side.up_ready()
        side.ans("ssm_describe-instance-information", "Online")
        for stale in side.rec.glob("ans/ssm_describe-instance-information.*"):
            stale.unlink()
        pool_listing(side, pool_row(side, "i-w1", 5, "ami-v1", "0.2085"))
        env = side.env(DJB_VERIFIER_HOME=str(shared))
        env["DJB_FAKE_CLOCK"] = str(side.root / "ssh-clock")
        (side.root / "ssh-clock").write_text(f"{world.clock.now()}\n")
        with (side.root / "out").open("wb") as out, (side.root / "err").open("wb") as err:
            children.append(
                subprocess.Popen(
                    [*SUBJECT, "up", "--for", f"race-{name}"],
                    cwd=ROOT,
                    env=env,
                    stdout=out,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                )
            )
    for child in children:
        child.wait(timeout=120)
    claims = sum(1 for side in sides if "claimed i-w1" in side.out)
    launches = sum(side.op_count("ec2 run-instances") for side in sides)
    assert claims == 1, [side.report() for side in sides]
    assert launches == 1, [side.report() for side in sides]


# --- the push, as `up` runs it --------------------------------------------------------


def test_the_push_carries_the_rungs_fork_point_as_a_ref(world: World) -> None:
    world.up_ready()
    forked(world, "3")
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    flat = git_flat(world)
    assert "fetch -q --depth 4 " in flat
    assert f"update-ref refs/djb/base {BASE}" in flat
    assert f"-C {ROOT} update-ref" not in flat
    assert "refs/djb/base:refs/djb/base" in ssh_pushes(world)[0]


def test_a_rung_too_far_from_its_fork_point_carries_nothing_and_says_so(world: World) -> None:
    world.up_ready()
    forked(world, "5000")
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    flat = git_flat(world)
    assert "fetch -q --depth 1 " in flat
    assert "update-ref refs/djb/base" not in flat
    assert "refs/djb/base:refs/djb/base" not in flat
    assert world.said("5000 commits from its fork point")


def test_the_wrapper_sends_one_ref_per_push_base_first(world: World) -> None:
    world.up_ready()
    forked(world, "2")
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    sent = ssh_pushes(world)
    assert len(sent) == 2, sent
    assert "refs/djb/base:refs/djb/base" in sent[0]
    assert "refs/heads/main:refs/heads/main" in sent[1]
    assert not [s for s in sent if "refs/djb/base" in s and "refs/heads/main" in s]


def test_a_refused_base_never_sends_the_tree(world: World) -> None:
    world.up_ready()
    forked(world, "2")
    (world.rec / "git.push.base.rc").write_text("1\n")
    (world.rec / "git.push.base.err").write_text("error: failed to push some refs\n")
    twin(world, "up", "--for", "X")
    assert world.rc != 0, world.report()
    assert len(ssh_pushes(world)) == 1
    assert world.said("THE REF THAT FAILED: refs/djb/base:refs/djb/base")
    assert world.said("Nothing landed on the box")


def test_a_box_whose_tree_differs_is_exit_2(world: World) -> None:
    world.up_ready()
    world.ssh("default", "out", "2" * 40 + "\n")
    twin(world, "up", "--for", "X")
    assert world.rc == 2, world.report()
    assert world.said("WORKING TREE")
    assert world.said(MAIN_SHA) and world.said("2" * 40)


# --- the ceiling and the credential, through `up` whole --------------------------------

TWO_UP = "ec2_describe-instances__ReservationsInstancesInstanceId"


def ceiling_file(world: World, value: str) -> None:
    """The drive's `plant_ceiling_file`: this machine's ceiling file holds `value`."""
    (world.vhome / "ceiling").write_text(f"{value}\n")


@pytest.mark.parametrize("code", ["UnauthorizedOperation", "ExpiredToken"])
def test_a_credential_error_is_exit_2_and_one_call(world: World, code: str) -> None:
    world.up_ready()
    refuse_launch(world, code, n="")
    twin(world, "up", "--for", "X")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 1
    assert world.said(f"aws configure --profile {NS}-verifier")


def test_the_box_ceiling_refuses_before_the_call(world: World) -> None:
    world.up_ready()
    world.ans(TWO_UP, "i-a\ti-b")
    twin(world, "up", "--for", "X")
    assert world.rc == 2, world.report()
    assert world.op_count("ec2 run-instances") == 0
    for want in ("i-a", "i-b", "L-34B43A08"):
        assert world.said(want), want


def test_a_raised_ceiling_launches(world: World) -> None:
    world.up_ready()
    world.ans(TWO_UP, "i-a\ti-b")
    twin(world, "up", "--for", "X", DJB_VERIFIER_MAX_BOXES="3")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 1


@pytest.mark.parametrize("arm", ["raises", "binds"])
def test_the_ceiling_is_read_from_the_file_when_the_env_is_unset(world: World, arm: str) -> None:
    world.up_ready()
    world.ans(TWO_UP, "i-a\ti-b")
    ceiling_file(world, "3" if arm == "raises" else "2")
    twin(world, "up", "--for", "X")
    if arm == "raises":
        assert world.rc == 0, world.report()
        assert world.op_count("ec2 run-instances") == 1
        return
    assert world.rc == 2, world.report()
    assert world.said("ceiling is 2 (file)")
    assert world.op_count("ec2 run-instances") == 0


@pytest.mark.parametrize("arm", ["down", "up"])
def test_the_env_ceiling_wins_over_the_file(world: World, arm: str) -> None:
    world.up_ready()
    world.ans(TWO_UP, "i-a\ti-b")
    ceiling_file(world, "9" if arm == "down" else "2")
    twin(world, "up", "--for", "X", DJB_VERIFIER_MAX_BOXES="2" if arm == "down" else "9")
    if arm == "up":
        assert world.rc == 0, world.report()
        assert world.op_count("ec2 run-instances") == 1
        return
    assert world.rc == 2, world.report()
    assert world.said("ceiling is 2 (env)")
    assert world.said("9")
    assert world.op_count("ec2 run-instances") == 0


def test_the_ceiling_refusal_names_all_three_and_the_one_that_bound(world: World) -> None:
    world.up_ready()
    world.ans(TWO_UP, "i-a\ti-b")
    twin(world, "up", "--for", "X")
    assert world.rc == 2, world.report()
    for want in (
        "ceiling is 2 (default)",
        "DJB_VERIFIER_MAX_BOXES  unset",
        "/ceiling  absent",
        "default  2",
        "-> default",
        "L-34B43A08",
    ):
        assert world.said(want), want
    assert world.op_count("ec2 run-instances") == 0


# --- the tree agreement and a refused push, through `up` whole --------------------------


def test_up_prints_the_tree_agreement_when_they_agree(world: World) -> None:
    world.up_ready()
    twin(world, "up", "--for", "X")
    assert world.rc == 0, world.report()
    short = MAIN_SHA[:8]
    assert f"tree       HEAD measured {short} = box WORKTREE measured {short}" in world.out


def test_a_refused_push_inside_up_names_the_box_it_left_running(world: World) -> None:
    world.up_ready()
    (world.rec / "git.vouch.rc").write_text("1\n")
    (world.rec / "git.vouch.err").write_text(
        "!! pre-push: REFUSED — the ref being pushed is not the tree in this checkout.\n"
    )
    twin(world, "up", "--for", "X")
    assert world.rc == 2, world.report()
    for want in (
        "box i-up1 is UP",
        "verifier_box.sh push i-up1",
        "verifier_box.sh down i-up1",
        "pre-push: wall ",
        "pre-push: REFUSED",
    ):
        assert world.said(want), want
    assert world.op_count("ec2 terminate-instances") == 0
