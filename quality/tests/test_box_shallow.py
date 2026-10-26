"""The shallow push's cases: the fork point, the mirror, the vouch, and git's own measured rules."""

from __future__ import annotations

import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quality.tests.fixtures.box_world import MAIN_SHA, World
from quality.tests.test_box_push import (
    ROOT,
    git_flat,
    hook_push,
    hook_union_commit,
    hook_world,
    keyed,
    real_env,
    real_git,
    same,
    ssh_flats,
)

pytestmark = pytest.mark.drives("quality/djb/box/shallow.py")


def _quiet_git(env: dict[str, str], *args: str) -> int:
    return subprocess.run(["git", *args], env=env, capture_output=True).returncode


def _receiver(env: dict[str, str], box: Path, *, seed: bool = True) -> None:
    """A working checkout in the box's shape: parked off `main`, accepting a shallow push."""
    real_git(env, "init", "-q", str(box))
    real_git(env, "-C", str(box), "config", "user.email", "drive@example.invalid")
    real_git(env, "-C", str(box), "config", "user.name", "verifier box drive")
    real_git(env, "-C", str(box), "config", "receive.denyCurrentBranch", "updateInstead")
    real_git(env, "-C", str(box), "config", "receive.shallowUpdate", "true")
    if seed:
        (box / "seed.txt").write_text("seed\n")
        real_git(env, "-C", str(box), "add", "-A")
        real_git(env, "-C", str(box), "commit", "-q", "-m", "seed")
        real_git(env, "-C", str(box), "checkout", "-q", "-b", "verifier-parking")


def _verify(env: dict[str, str], repo: Path, ref: str) -> str:
    return real_git(env, "-C", str(repo), "rev-parse", "-q", "--verify", ref, check=False)


# --- 1.8 the fork point travels with the tree -------------------------------------------


def test_a_union_pushed_as_main_carries_the_fork_point_it_declares(world: World) -> None:
    env = real_env(world.root)
    src = world.root / "union-as-main" / "src"
    real_git(env, "init", "-q", str(src))
    real_git(env, "-C", str(src), "symbolic-ref", "HEAD", "refs/heads/main")
    real_git(env, "-C", str(src), "config", "user.email", "drive@example.invalid")
    real_git(env, "-C", str(src), "config", "user.name", "verifier box drive")
    (src / "shared.txt").write_text("shared\n")
    real_git(env, "-C", str(src), "add", "shared.txt")
    real_git(env, "-C", str(src), "commit", "-q", "-m", "the fold point")
    fold = real_git(env, "-C", str(src), "rev-parse", "HEAD")
    (src / "rung.txt").write_text("the rung's own work\n")
    real_git(env, "-C", str(src), "add", "rung.txt")
    real_git(env, "-C", str(src), "commit", "-q", "-m", "the rung")
    union = real_git(env, "-C", str(src), "rev-parse", "HEAD")
    real_git(env, "-C", str(src), "update-ref", "refs/djb/base", fold)

    keyed(world, "i-ua1")
    (world.rec / "git.revparse").write_text(f"{union}\n")
    world.ssh("default", "out", f"{union}\n")
    (world.rec / "git.mergebase").write_text(f"{union}\n")
    span = real_git(env, "-C", str(src), "rev-list", "--count", f"{fold}..{union}")
    (world.rec / "git.revlist").write_text(f"{span}\n")
    (world.rec / "git.djbbase").write_text(f"{fold}\n")
    same(world, "push", "i-ua1")
    assert world.rc == 0, world.report()
    flat = git_flat(world)
    carried = re.search(r" update-ref refs/djb/base ([0-9a-f]{40})", flat)
    assert carried and carried.group(1) == fold
    first_push = next(line for line in flat.splitlines() if "push --force ssh://" in line)
    assert "refs/djb/base:refs/djb/base" in first_push
    assert world.said(
        f"carried    fork point {fold[:8]} (refs/djb/base, declared in this checkout)"
    )
    depth = re.search(r"fetch -q --depth ([0-9]+) ", flat)
    assert depth

    mirror, box, listing = (world.root / "union-as-main" / n for n in ("mirror", "box", "list"))
    real_git(env, "init", "-q", "--bare", str(mirror))
    real_git(
        env,
        "-C",
        str(mirror),
        "fetch",
        "-q",
        "--depth",
        depth.group(1),
        f"file://{src}",
        "+HEAD:refs/heads/main",
    )
    real_git(env, "-C", str(mirror), "update-ref", "refs/djb/base", carried.group(1))
    _receiver(env, box)
    real_git(env, "-C", str(box), "update-ref", "-d", "refs/heads/main")
    real_git(
        env, "-C", str(mirror), "push", "-q", "--force", str(box), "refs/djb/base:refs/djb/base"
    )
    real_git(
        env, "-C", str(mirror), "push", "-q", "--force", str(box), "refs/heads/main:refs/heads/main"
    )
    real_git(env, "-C", str(box), "reset", "-q", "--hard", "refs/heads/main")
    derived = subprocess.run(
        [
            "bash",
            "-c",
            '. "$1/scripts/secrets_scan.sh" && DJB_LOOP_SCOPE_BASE=refs/djb/base'
            ' secrets_scan_changed_files "$2" >/dev/null 2>&1'
            ' && printf "%s\\n" "$SECRETS_SCAN_BASIS"',
            "bash",
            str(ROOT),
            str(listing),
        ],
        cwd=box,
        env=env,
        capture_output=True,
        text=True,
    )
    assert derived.returncode == 0, derived.stderr
    listed = listing.read_bytes().decode().split("\0")
    assert "rung.txt" in listed
    assert "shared.txt" not in listed
    assert "CARRIED fork point" in derived.stdout


@pytest.mark.parametrize("arm", ["no-fork-point", "derivable"])
def test_commits_past_main_with_no_fork_point_are_refused_before_anything_leaves(
    world: World, arm: str
) -> None:
    keyed(world, "i-nf1")
    (world.rec / "git.revparse.main").write_text(f"{ROOT}\t{'3' * 40}\n")
    if arm == "no-fork-point":
        (world.rec / "git.ancestor.rc").write_text("1\n")
    else:
        (world.rec / "git.mergebase").write_text(f"{'3' * 40}\n")
        (world.rec / "git.revlist").write_text("1\n")
    same(world, "push", "i-nf1")
    if arm == "derivable":
        assert world.rc == 0, world.report()
        return
    assert world.rc == 2
    assert world.said("git update-ref refs/djb/base <sha>")
    assert world.said("Nothing was pushed")
    assert " push " not in git_flat(world)


def test_a_declared_base_that_is_not_behind_head_is_not_carried(world: World) -> None:
    keyed(world, "i-fb1")
    (world.rec / "git.djbbase").write_text(f"{'5' * 40}\n")
    (world.rec / "git.ancestor.rc").write_text("1\n")
    same(world, "push", "i-fb1")
    assert world.rc == 0, world.report()
    assert f"refs/djb/base {'5' * 40}" not in git_flat(world)


# --- the mirror: depth one, one ref per push, the box's refs cleared once ----------------


def test_the_push_sends_a_depth_one_mirror_and_not_the_history(world: World) -> None:
    keyed(world)
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    flat = git_flat(world)
    assert f"fetch -q --depth 1 file://{ROOT} +HEAD:refs/heads/main" in flat
    transfer = [line for line in flat.splitlines() if "push --force ssh://" in line][-1]
    assert f"-C {world.vhome}/" in transfer
    assert f"-C {ROOT} " not in transfer
    assert f"init -q --bare {ROOT}" not in flat
    assert any("receive.shallowUpdate true" in f for f in ssh_flats(world))


def test_the_first_push_to_a_box_clears_its_refs(world: World) -> None:
    bake = (ROOT / "deploy" / "verifier" / "bake.sh").read_text()
    park = re.search(r'^BAKE_PARK_BRANCH="(.*)"$', bake, re.M)
    assert park, "BAKE_PARK_BRANCH is not in the real deploy/verifier/bake.sh"
    keyed(world)
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    flats = ssh_flats(world)
    joined = "".join(flats)
    assert "update-ref -d refs/heads/main" in joined
    assert f"update-ref -d refs/heads/{park.group(1)}" in joined
    assert "update-ref -d refs/djb/base" in joined
    clear = next(n for n, f in enumerate(flats) if "update-ref -d refs/heads/main" in f)
    reset = next(n for n, f in enumerate(flats) if "reset --hard refs/heads/main" in f)
    assert clear < reset
    for flat in (world.rec / "ssh").glob("*.flat"):
        flat.unlink()
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    assert not [f for f in ssh_flats(world) if "update-ref -d refs/heads/main" in f]


def test_a_shallow_mirror_cannot_send_two_refs_in_one_push(scratch: Path) -> None:
    """git's own rule, measured: a shallow source lands only the first of two refs."""
    env = real_env(scratch)
    w = scratch / "realgit"
    src, mirror = w / "src", w / "mirror"
    real_git(env, "init", "-q", str(src))
    real_git(env, "-C", str(src), "symbolic-ref", "HEAD", "refs/heads/main")
    real_git(env, "-C", str(src), "config", "user.email", "drive@example.invalid")
    real_git(env, "-C", str(src), "config", "user.name", "verifier box drive")
    for name, text, msg in (("a.txt", "base", "base"), ("b.txt", "more", "on main")):
        (src / name).write_text(f"{text}\n")
        real_git(env, "-C", str(src), "add", "-A")
        real_git(env, "-C", str(src), "commit", "-q", "-m", msg)
    real_git(env, "-C", str(src), "checkout", "-q", "-b", "rung")
    (src / "rung.txt").write_text("work\n")
    real_git(env, "-C", str(src), "add", "-A")
    real_git(env, "-C", str(src), "commit", "-q", "-m", "rung work")
    box = w / "box"
    _receiver(env, box)
    base = real_git(env, "-C", str(src), "merge-base", "rung", "main")
    real_git(env, "init", "-q", "--bare", str(mirror))
    real_git(
        env,
        "-C",
        str(mirror),
        "fetch",
        "-q",
        "--depth",
        "2",
        f"file://{src}",
        "+HEAD:refs/heads/main",
    )
    real_git(env, "-C", str(mirror), "update-ref", "refs/djb/base", base)
    assert (mirror / "shallow").is_file(), "the mirror is not shallow — this measures nothing"

    both = subprocess.run(
        [
            "git",
            "-C",
            str(mirror),
            "push",
            "--force",
            str(box),
            "refs/heads/main:refs/heads/main",
            "refs/djb/base:refs/djb/base",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert both.returncode != 0
    assert "remote failed to report status" in both.stdout + both.stderr
    assert _verify(env, box, "refs/heads/main") and not _verify(env, box, "refs/djb/base")

    box2 = w / "box2"
    _receiver(env, box2)
    rc1 = _quiet_git(
        env, "-C", str(mirror), "push", "--force", str(box2), "refs/djb/base:refs/djb/base"
    )
    rc2 = _quiet_git(
        env, "-C", str(mirror), "push", "--force", str(box2), "refs/heads/main:refs/heads/main"
    )
    assert (rc1, rc2) == (0, 0)
    assert _verify(env, box2, "refs/heads/main")
    assert _verify(env, box2, "refs/djb/base") == base

    box3 = w / "box3"
    _receiver(env, box3)
    _quiet_git(
        env,
        "-C",
        str(mirror),
        "fetch",
        "-q",
        "--depth",
        "2",
        f"file://{src}",
        "+refs/heads/rung:refs/heads/rung",
    )
    rc3 = _quiet_git(
        env,
        "-C",
        str(mirror),
        "push",
        "--force",
        str(box3),
        "refs/heads/main:refs/heads/main",
        "refs/heads/rung:refs/heads/rung",
    )
    assert rc3 != 0


def _blob(n: int) -> str:
    """Two thousand lines that share their shape with every other n: content git deltifies."""
    rand = random.Random(n)  # noqa: S311 — a seeded fixture generator; not crypto
    return "".join(f"{j} payloadpayloadpayload {rand.randrange(99999)}\n" for j in range(2000))


def _shallow_refs_source(env: dict[str, str], src: Path) -> None:
    """Six lanes crossing the depth frontier, merged into main: more than one shallow boundary."""
    git = ["git", "-C", str(src)]
    real_git(env, "init", "-q", str(src))
    real_git(env, *git[1:], "symbolic-ref", "HEAD", "refs/heads/main")
    real_git(env, *git[1:], "config", "user.email", "drive@example.invalid")
    real_git(env, *git[1:], "config", "user.name", "verifier box drive")
    (src / "big.txt").write_text(_blob(0))
    real_git(env, *git[1:], "add", "-A")
    real_git(env, *git[1:], "commit", "-q", "-m", "c0")
    n = 0
    for lane in range(1, 7):
        real_git(
            env, *git[1:], "checkout", "-q", "-b", f"lane{lane}", "main" if lane == 1 else "main~3"
        )
        for k in range(1, 9):
            n += 1
            (src / f"lane{lane}.txt").write_text(_blob(n))
            real_git(env, *git[1:], "add", "-A")
            real_git(env, *git[1:], "commit", "-q", "-m", f"lane{lane} c{k}")
        real_git(env, *git[1:], "checkout", "-q", "main")
        for _ in range(3):
            n += 1
            (src / "big.txt").write_text(_blob(n))
            real_git(env, *git[1:], "add", "-A")
            real_git(env, *git[1:], "commit", "-q", "-m", f"main {n}")
        real_git(env, *git[1:], "merge", "-q", "--no-ff", f"lane{lane}", "-m", f"merge lane{lane}")


def test_a_shallow_push_into_a_box_that_already_has_refs_is_refused(scratch: Path) -> None:
    """A box shallow at its bake commit fails the push, so does `--no-thin`; a clear lands it."""
    env = real_env(scratch)
    w = scratch / "shallow-refs"
    src, box, keep, mirror, bakemirror = (w / n for n in ("src", "box", "keep", "mirror", "bm"))
    _shallow_refs_source(env, src)
    bake = real_git(env, "-C", str(src), "rev-parse", "-q", "--verify", "main~2")
    _receiver(env, box, seed=False)
    real_git(env, "init", "-q", "--bare", str(bakemirror))
    real_git(
        env,
        "-C",
        str(bakemirror),
        "fetch",
        "-q",
        "--depth",
        "1",
        f"file://{src}",
        f"+{bake}:refs/heads/main",
    )
    real_git(
        env,
        "-C",
        str(bakemirror),
        "push",
        "-q",
        "--force",
        f"file://{box}",
        "refs/heads/main:refs/heads/main",
    )
    real_git(env, "-C", str(box), "checkout", "-q", "-B", "verifier-parking", "refs/heads/main")
    assert (box / ".git" / "shallow").is_file(), "the seeded box is not shallow"
    real_git(env, "init", "-q", "--bare", str(mirror))
    real_git(
        env,
        "-C",
        str(mirror),
        "fetch",
        "-q",
        "--depth",
        "24",
        f"file://{src}",
        "+refs/heads/main:refs/heads/main",
    )
    assert (mirror / "shallow").is_file(), "the mirror is not shallow"
    shutil.copytree(box, keep, symlinks=True)

    def pushed(*flags: str) -> int:
        return _quiet_git(
            env,
            "-C",
            str(mirror),
            "push",
            *flags,
            "--force",
            f"file://{box}",
            "refs/heads/main:refs/heads/main",
        )

    def restore() -> None:
        shutil.rmtree(box)
        shutil.copytree(keep, box, symlinks=True)

    assert pushed() != 0, "this graph no longer reproduces the failure"
    restore()
    assert pushed("--no-thin") != 0, "--no-thin cured it — then the shipped remedy is wrong"
    restore()
    real_git(env, "-C", str(box), "update-ref", "-d", "refs/heads/main")
    real_git(env, "-C", str(box), "update-ref", "-d", "refs/heads/verifier-parking")
    assert pushed() == 0
    real_git(env, "-C", str(box), "reset", "--hard", "refs/heads/main")
    assert real_git(env, "-C", str(box), "symbolic-ref", "--short", "HEAD") == "verifier-parking"
    there = real_git(env, "-C", str(box), "rev-parse", "HEAD^{tree}")
    assert there == real_git(env, "-C", str(mirror), "rev-parse", "refs/heads/main^{tree}")


# --- the vouch: the wall runs here, over HEAD, before the tunnel --------------------------


def test_the_pre_push_hook_still_vouches_for_the_tree_that_goes(world: World) -> None:
    keyed(world)
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    pushes = [line for line in git_flat(world).splitlines() if " push " in f" {line}"]
    dry = next(line for line in pushes if "push --dry-run" in line)
    assert f"-C {ROOT} " in dry
    assert "HEAD:refs/heads/main" in dry
    assert " refs/heads/main:refs/heads/main" not in dry
    assert "ssh://" not in dry
    assert "--dry-run" in pushes[0]


def test_a_vouch_with_no_hook_is_refused(world: World) -> None:
    keyed(world)
    (world.rec / "git.vouch.out").write_text("")
    same(world, "push", "i-up1")
    assert world.rc != 0
    assert world.said("no pre-push hook ran on this checkout")
    assert world.said("core.hooksPath=scripts/githooks")
    assert "push --force ssh://" not in git_flat(world)
    assert "fetch -q --depth 1" not in git_flat(world)


def test_a_hook_that_refuses_stops_the_push_before_the_tunnel(world: World) -> None:
    keyed(world)
    (world.rec / "git.vouch.rc").write_text("1\n")
    (world.rec / "git.vouch.err").write_text(
        "!! pre-push: REFUSED — the ref being pushed is not the tree in this checkout.\n"
    )
    same(world, "push", "i-up1")
    assert world.rc != 0
    assert "fetch -q --depth 1" not in git_flat(world)
    assert "push --force ssh://" not in git_flat(world)
    assert world.said("pre-push hook refused")


def test_an_unmeasured_union_tree_reaches_the_box_without_a_mac_gate(
    world: World, scratch: Path
) -> None:
    keyed(world)
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    dest = (world.rec / "git.dest").read_text().splitlines()
    vouch = next(line for line in dest if "push --dry-run" in line)
    transfer = next(line for line in dest if "push --force ssh://" in line)
    assert vouch.startswith("verifier-box")
    assert transfer.startswith("<unset>")

    hw = hook_world(scratch / "hook-bv1")
    hook_union_commit(hw)
    before = hw.ledger.stat().st_size
    rc, said = hook_push(hw, "HEAD:refs/heads/main")
    assert rc == 0, said
    assert "STUB GATE RAN" not in said
    assert "leaves for a VERIFIER BOX" in said
    assert "pre-push: wall box-exempt" in said
    assert hw.ledger.stat().st_size == before


def test_the_narration_prints_the_measured_tree_a_declaration_moves(world: World) -> None:
    measured = "2" * 40
    keyed(world, rung="a-rung")
    (world.rec / "git.writetree").write_text(f"{measured}\n")
    world.ssh("default", "out", f"{measured}\n")
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    assert (
        f"tree       HEAD measured {measured[:8]} = box WORKTREE measured {measured[:8]}"
        in world.out
    )
    assert f"HEAD {MAIN_SHA[:8]}" not in world.out
    package = ROOT / "quality" / "djb" / "box"
    raw = [
        f"{path.name}:{n}"
        for path in package.glob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"rev-parse.*HEAD\^\{tree\}", line)
    ]
    assert raw == []


def test_the_real_git_env_carries_no_background_gc_or_maintenance(tmp_path: Path) -> None:
    env = real_env(tmp_path)
    real_git(env, "init", "-q", str(tmp_path / "r"))
    said = real_git(env, "-C", str(tmp_path / "r"), "config", "--get", "gc.auto")
    assert said == "0"
    said = real_git(env, "-C", str(tmp_path / "r"), "config", "--get", "maintenance.auto")
    assert said == "false"
