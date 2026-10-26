"""The push program's cases: `push` driven through the box world, beside the shell's own run."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.tests.conftest import REAL_TIME_CEILING_S
from quality.tests.fixtures.box_world import MAIN_SHA, World

pytestmark = pytest.mark.drives("quality/djb/box/push.py")

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "scripts" / "verifier_box.sh"
STATE = "ec2_describe-instances__Reservations0Instances0StateName"
_LEDGER_PATH = re.compile(r"rev-parse (--path-format=absolute )?--git-common-dir *$")
_PID = re.compile(r"\.(shallow|vouch|probe|ledger-out)-[0-9]+")


@dataclass(frozen=True)
class Record:
    """One run's observable world: exit, both streams, and every recorded argv."""

    rc: int
    out: str
    err: str
    files: dict[str, str]


def _snapshot(world: World, rc: int, out: str, err: str) -> Record:
    files = {}
    for path in sorted(world.rec.rglob("*")):
        if path.is_file() and not path.name.startswith("_") and "seq" not in path.parts:
            files[str(path.relative_to(world.rec))] = _PID.sub(r".\1-PID", path.read_text())
    _drop_the_ledger_path_read(files)
    for path in sorted(world.vhome.rglob("*")):
        if path.is_file():
            files[f"vhome/{path.relative_to(world.vhome)}"] = path.read_text()
    return Record(rc, _PID.sub(r".\1-PID", out), _PID.sub(r".\1-PID", err), files)


def _drop_the_ledger_path_read(files: dict[str, str]) -> None:
    """Drop the git calls that locate the ledger: the shell's library and `ledger.py` differ."""
    dest = files.get("git.dest", "").splitlines()
    drop = {n for n, line in enumerate(dest) if _LEDGER_PATH.search(line)}
    drop |= {n + 1 for n in drop if n + 1 < len(dest) and dest[n + 1].endswith("--show-toplevel")}
    for name in ("git.dest", "git.env", "git.flat"):
        if name in files:
            kept = [line for n, line in enumerate(files[name].splitlines()) if n not in drop]
            files[name] = "".join(f"{line}\n" for line in kept)


def both(world: World, *args: str, env: dict[str, str] | None = None) -> tuple[Record, Record]:
    """Run the shell, then the port, each from the same world and clock; both records."""
    pre = world.root / "pre"
    shutil.copytree(world.rec, pre / "rec")
    shutil.copytree(world.vhome, pre / "vhome")
    start = world.clock.now()
    with (world.root / "out").open("wb") as out, (world.root / "err").open("wb") as err:
        shell = subprocess.run(
            ["bash", str(SHELL), *args],
            cwd=ROOT,
            env=env if env is not None else world.env(),
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
        )
    before = _snapshot(world, shell.returncode, world.out, world.err)
    for name in ("rec", "vhome"):
        shutil.rmtree(world.root / name)
        shutil.copytree(pre / name, world.root / name)
    shutil.rmtree(pre)
    world.clock.file.write_text(f"{start}\n")
    world.vb(*args, env=env)
    return before, _snapshot(world, world.rc, world.out, world.err)


def same(world: World, *args: str, env: dict[str, str] | None = None) -> Record:
    """Run both and assert the port's record equals the shell's; the port's record."""
    shell, port = both(world, *args, env=env)
    assert port.rc == shell.rc, (shell, port)
    for name in sorted({*shell.files, *port.files}):
        assert port.files.get(name) == shell.files.get(name), _diff(
            name, shell.files.get(name, ""), port.files.get(name, "")
        )
    assert port.err == shell.err, _diff("stderr", shell.err, port.err)
    assert port.out == shell.out, _diff("stdout", shell.out, port.out)
    return port


def _diff(name: str, shell: str, port: str) -> str:
    lines = difflib.unified_diff(
        shell.splitlines(), port.splitlines(), f"shell {name}", f"port {name}", lineterm=""
    )
    return "\n".join(lines)


def keyed(world: World, instance: str = "i-up1", rung: str | None = None) -> None:
    """A running box this machine holds the key to, optionally with its rung."""
    world.ans(STATE, "running")
    box = world.vhome / instance
    box.mkdir(parents=True, exist_ok=True)
    (box / "id_ed25519").write_text("key\n")
    if rung is not None:
        (box / "rung").write_text(f"{rung}\n")


def git_flat(world: World) -> str:
    path = world.rec / "git.flat"
    return path.read_text() if path.is_file() else ""


def ssh_flats(world: World) -> list[str]:
    found = sorted((world.rec / "ssh").glob("*.flat"), key=lambda p: int(p.stem))
    return [path.read_text() for path in found]


def fresh(world: World) -> World:
    """The drive's second `world_new` in one case: the records and the boxes emptied."""
    for name in ("rec", "vhome"):
        shutil.rmtree(world.root / name)
    for sub in ("ans", "err", "rc", "seq", "calls", "ssh"):
        (world.rec / sub).mkdir(parents=True)
    world.vhome.mkdir()
    world.ssh("default", "out", f"{MAIN_SHA}\n")
    (world.rec / "git.revparse").write_text(f"{MAIN_SHA}\n")
    return world


def real_env(home: Path) -> dict[str, str]:
    """This process's environment for a real-git world: no ledger, no destination, no git dir."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "DJB_"))}
    env["HOME"] = str(home)
    # Invariant: no background gc or maintenance — its lock races the scratch repo's rmtree.
    env.update(QUIET_GIT_CONFIG)
    return env


#: The env-level git config every real-git world carries: no auto-gc, no auto-maintenance.
QUIET_GIT_CONFIG = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "gc.auto",
    "GIT_CONFIG_VALUE_0": "0",
    "GIT_CONFIG_KEY_1": "maintenance.auto",
    "GIT_CONFIG_VALUE_1": "false",
}


def real_git(env: dict[str, str], *args: str, check: bool = True) -> str:
    """Real `git <args>`; its stdout, stripped."""
    done = subprocess.run(["git", *args], env=env, capture_output=True, text=True, check=check)
    return done.stdout.strip()


@dataclass(frozen=True)
class HookWorld:
    """The drive's `hook_world`: a checkout with the real pre-push hook and a banked `main`."""

    work: Path
    probe: Path
    ledger: Path
    main_sha: str
    env: dict[str, str]


def hook_world(base: Path) -> HookWorld:
    """A throwaway checkout carrying the real hook, its own ledger, a stub gate and a probe."""
    work = base / "work"
    probe = base / "vhome" / ".vouch-4321" / "probe.git"
    (work / "scripts" / "githooks").mkdir(parents=True)
    probe.parent.mkdir(parents=True)
    env = real_env(base)
    real_git(env, "init", "-q", str(work))
    real_git(env, "-C", str(work), "symbolic-ref", "HEAD", "refs/heads/main")
    real_git(env, "-C", str(work), "config", "user.email", "drive@example.invalid")
    real_git(env, "-C", str(work), "config", "user.name", "boxvouch drive")
    real_git(env, "-C", str(work), "config", "core.hooksPath", "scripts/githooks")
    for name in ("gate_ledger.sh", "gate_refuse.sh"):
        shutil.copy(ROOT / "scripts" / name, work / "scripts" / name)
    hook = work / "scripts" / "githooks" / "pre-push"
    shutil.copy(ROOT / "scripts" / "githooks" / "pre-push", hook)
    hook.chmod(0o755)
    gate = work / "scripts" / "check.sh"
    gate.write_text('#!/usr/bin/env bash\nFULL_LEGS=drive-legs\necho "STUB GATE RAN"\nexit 0\n')
    gate.chmod(0o755)
    (work / "README.md").write_text("the measured content\n")
    for package in ("quality", "apps"):
        (work / package).symlink_to(ROOT / package)
    with (work / ".git" / "info" / "exclude").open("a") as exclude:
        exclude.write("/quality\n/apps\n")
    real_git(env, "-C", str(work), "add", "-A")
    real_git(env, "-C", str(work), "commit", "-q", "-m", "main, the tree a full gate measured")
    main_sha = real_git(env, "-C", str(work), "rev-parse", "HEAD")
    tree = real_git(env, "-C", str(work), "rev-parse", f"{main_sha}^{{tree}}")
    subprocess.run(
        [
            "bash",
            "-c",
            '. scripts/gate_ledger.sh && gate_ledger_record "$1" drive-legs',
            "bash",
            tree,
        ],
        cwd=work,
        env=env,
        check=True,
        capture_output=True,
    )
    ledger = work / ".git" / "djb-gate-verdicts"
    assert ledger.stat().st_size > 0, "the scratch ledger is empty — the plant did not take"
    real_git(env, "init", "-q", "--bare", str(probe))
    return HookWorld(work, probe, ledger, main_sha, env)


def hook_union_commit(hw: HookWorld) -> None:
    """One commit past the banked one: a verifier's union clone, a tree no bank measured."""
    (hw.work / "UNION.md").write_text("a union nothing measured\n")
    real_git(hw.env, "-C", str(hw.work), "add", "UNION.md")
    real_git(hw.env, "-C", str(hw.work), "commit", "-q", "-m", "the union tree, unmeasured")


def hook_push(hw: HookWorld, *refs: str) -> tuple[int, str]:
    """The vouch's own command, by hand: a declared box destination, a dry run at the probe."""
    done = subprocess.run(
        ["git", "-C", str(hw.work), "push", "--dry-run", "--force", str(hw.probe), *refs],
        env={**hw.env, "DJB_PUSH_DESTINATION": "verifier-box"},
        capture_output=True,
        text=True,
    )
    return done.returncode, done.stdout + done.stderr


# --- 1.8 push, and the tree agreement ----------------------------------------------------


def test_push_reads_the_checkout_path_out_of_the_recipe(world: World) -> None:
    keyed(world)
    same(world, "push", "i-up1", "rung/x")
    assert world.rc == 0, world.report()
    bake = (ROOT / "deploy" / "verifier" / "bake.sh").read_text()
    user = re.search(r'^BAKE_USER="\$\{DJB_VERIFIER_BAKE_USER:-(.*)\}"$', bake, re.M)
    path = re.search(r'^BAKE_CHECKOUT="\$\{DJB_VERIFIER_CHECKOUT:-(.*)\}"$', bake, re.M)
    assert user and path
    checkout = path.group(1).replace("${BAKE_USER}", user.group(1))
    expect = f"ssh://{user.group(1)}@i-up1{checkout}"
    call = git_flat(world)
    assert f"push --force {expect} refs/heads/main:refs/heads/main " in call
    assert f"push --force {expect} refs/heads/rung/x:refs/heads/rung/x " in call
    assert not re.search(r"(^| )main:main( |$)", call)
    assert "ProxyCommand=aws ssm start-session" in (world.rec / "git.env").read_text()
    spelled = [
        line
        for file in (*ROOT.glob("scripts/**/*.sh"), *ROOT.glob("deploy/**/*.sh"))
        if file.name not in ("bake.sh", "test_verifier_box.sh")
        for line in file.read_text(errors="replace").splitlines()
        if checkout in line
    ]
    assert spelled == []


def test_the_push_moves_the_boxs_working_tree_onto_what_it_pushed(world: World) -> None:
    keyed(world, rung="a-rung")
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    resets = [flat for flat in ssh_flats(world) if "reset --hard refs/heads/main" in flat]
    assert resets and "git -C /" in resets[-1]
    assert not [flat for flat in ssh_flats(world) if re.search(r"git -C .*clean", flat)]
    assert "= box WORKTREE" in world.out
    assert (
        f"tree       HEAD measured {MAIN_SHA[:8]} = box WORKTREE measured {MAIN_SHA[:8]}"
        in world.out
    )


def test_a_push_whose_box_worktree_will_not_move_is_refused(world: World) -> None:
    keyed(world, rung="a-rung")
    world.ssh(4, "out", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n")
    same(world, "push", "i-up1")
    assert world.rc != 0
    assert "WORKING TREE" in world.err


@pytest.mark.parametrize("arm", ["rows-then-delta", "empty-ledger"])
def test_push_sends_only_the_drive_rows(world: World, arm: str) -> None:
    keyed(world, rung="a-rung")
    if arm == "empty-ledger":
        _an_empty_ledger_sends_nothing(world)
        return
    ledger = world.root / "gate-verdicts"
    ledger.write_text(
        "v1 drive-v1:aaa drive 2026-09-18T10:00:00Z sweep exit=0 took=9 tree=t1 parts=p:1\n"
        "v1 fullkey1 full 2026-09-18T10:01:00Z ruff,mypy exit=0 took=900 tree=t1\n"
        "v1 drive-v1:bbb drive 2026-09-18T10:02:00Z db_pin exit=0 took=4 tree=t1 parts=p:2\n"
        "loop-v1 loop-v1:ccc loop 2026-09-18T10:03:00Z caller=unstated tree=t1\n"
        "v1 drive-v1:ddd drive 2026-09-18T10:04:00Z loop_scope exit=0 took=180 tree=t1"
        " parts=p:3\n"
        "v1 fullkey2 full 2026-09-18T10:05:00Z ruff,mypy exit=0 took=880 tree=t0\n"
    )
    env = world.env(DJB_GATE_LEDGER=str(ledger))
    same(world, "push", "i-up1", env=env)
    assert world.rc == 0, world.report()
    calls = (world.rec / "scp.flat").read_text().splitlines()
    assert len([c for c in calls if c.strip()]) == 1
    assert "ProxyCommand=aws ssm start-session" in calls[0]
    assert "@i-up1:verify/a-rung/ledger.in" in calls[0]
    want = [line for line in ledger.read_text().splitlines() if " drive " in line]
    assert _payload(world) == want
    assert not [f for f in ssh_flats(world) if re.search(r"ledger\.in.*djb-gate-verdicts", f)]

    with ledger.open("a") as handle:
        handle.write(
            "v1 drive-v1:eee drive 2026-09-18T10:06:00Z serve_port exit=0 took=3 tree=t1"
            " parts=p:4\n"
        )
    (world.rec / "scp.flat").write_text("")
    (world.rec / "scp.payload").write_text("")
    same(world, "push", "i-up1", env=env)
    assert world.rc == 0, world.report()
    assert _payload(world) == [
        "v1 drive-v1:eee drive 2026-09-18T10:06:00Z serve_port exit=0 took=3 tree=t1 parts=p:4"
    ]
    assert "@i-up1:verify/a-rung/ledger.in.part" in (world.rec / "scp.flat").read_text()
    assert "drive rows: 1 sent to i-up1:~/verify/a-rung/ledger.in (the delta; 4 in the ledger)" in (
        world.out
    )


def _an_empty_ledger_sends_nothing(world: World) -> None:
    empty = world.root / "gate-verdicts-empty"
    empty.write_text("")
    same(world, "push", "i-up1", env=world.env(DJB_GATE_LEDGER=str(empty)))
    assert world.rc == 0, world.report()
    scp = world.rec / "scp.flat"
    assert not scp.is_file() or not scp.read_text().strip()
    assert "drive rows: none to send" in world.out


def _payload(world: World) -> list[str]:
    path = world.rec / "scp.payload"
    current, lines = "", []
    for line in path.read_text().splitlines() if path.is_file() else []:
        if line.startswith("--- "):
            current = line[4:]
            continue
        if ".ledger-out-" in current:
            lines.append(line)
    return lines


# --- 1.8 the transport, across a shell and across a hook that measures --------------------

WANT_PROXY = (
    "aws ssm start-session --target %h --document-name AWS-StartSSHSession"
    " --parameters portNumber=%p --profile drivens-verifier --region xx-drive-9"
)


def _resolve(world: World, *argv: str, string: str = "") -> str:
    """The `proxycommand` real `ssh -G` resolves: from a shell string (git's) or an argv."""
    gbin = world.root / "gbin"
    env = {"PATH": f"{gbin}:/usr/bin:/bin", "HOME": str(world.home)}
    env["PROXY_RAN"] = str(world.root / "proxy.ran")
    if string:
        cmd = ["sh", "-c", f"{string} -G djb-resolve-only"]
    else:
        cmd = [str(gbin / "ssh"), *argv, "-G", "djb-resolve-only"]
    done = subprocess.run(cmd, env=env, capture_output=True, text=True)
    found = re.findall(r"^[Pp]roxy[Cc]ommand (.*)$", done.stdout + done.stderr, re.M)
    return found[-1] if found else ""


def _options(args_file: Path) -> list[str]:
    """The leading options of a recorded argv, one per line, up to the destination."""
    opts: list[str] = []
    lines = iter(args_file.read_text().splitlines())
    for arg in lines:
        if arg in ("-i", "-o", "-F", "-l", "-p", "-b", "-c", "-E"):
            opts += [arg, next(lines, "")]
        elif arg.startswith("-"):
            opts.append(arg)
        else:
            break
    return opts


def _transport_strings(world: World) -> list[str]:
    lines = (world.rec / "git.env").read_text().splitlines()
    return [line.removeprefix("GIT_SSH_COMMAND=") for line in lines if not line.endswith("<unset>")]


def test_the_push_transport_survives_the_shell_git_runs_it_in(world: World) -> None:
    keyed(world)
    real_ssh = world.stubs.require_real("ssh")
    gbin = world.root / "gbin"
    gbin.mkdir()
    (gbin / "ssh").symlink_to(real_ssh)
    (gbin / "aws").write_text('#!/usr/bin/env bash\nprintf "aws %s\\n" "$*" >>"$PROXY_RAN"\n')
    (gbin / "aws").chmod(0o755)
    same(world, "push", "i-up1", "rung/x")
    assert world.rc == 0, world.report()
    world.vb("run", "i-up1", "--", "true")
    world.vb("fetch", "i-up1", "~/verify/x/v1.log", str(world.root / "v1.log"))
    assert _resolve(world, string=_transport_strings(world)[-1]) == WANT_PROXY
    assert _resolve(world, *_options(world.rec / "ssh" / "1.args")) == WANT_PROXY
    assert _resolve(world, *_options(world.rec / "scp.args")) == WANT_PROXY


def test_the_push_transport_outlives_a_hook_that_measures(world: World) -> None:
    keyed(world)
    same(world, "push", "i-up1")
    assert world.rc == 0, world.report()
    gitssh = _transport_strings(world)[-1]
    assert "ServerAliveInterval=" in gitssh
    assert "ServerAliveCountMax=" in gitssh
    for flat in (world.rec / "ssh").glob("*.flat"):
        flat.unlink()
    (world.rec / "seq" / "_ssh").unlink()
    world.vb("run", "i-up1", "--", "true")
    ssh1 = world.ssh_flat(1)
    assert "ServerAliveInterval=" in ssh1
    assert "ServerAliveCountMax=" not in ssh1
    world.vb("fetch", "i-up1", "/tmp/gate.log", str(world.root / "fetched.log"))  # noqa: S108 — the remote box's log path the fake fetch is asked for
    scp1 = (world.rec / "scp.flat").read_text()
    assert scp1.strip()
    assert "ServerAlive" not in scp1


@pytest.mark.parametrize("arm", ["141", "1"])
def test_a_push_that_died_of_sigpipe_is_named_for_what_it_is(world: World, arm: str) -> None:
    keyed(world)
    (world.rec / "git.push.rc").write_text(f"{arm}\n")
    if arm == "1":
        (world.rec / "git.push.err").write_text("error: failed to push some refs\n")
    same(world, "push", "i-up1")
    assert world.rc == int(arm)
    if arm == "141":
        assert "SIGPIPE" in world.err
        assert "transport" in world.err
        return
    for needle in (
        "git exit 1",
        "THE TRANSPORT DIED",
        "shallow update not allowed",
        "already passed",
        "failed to push some refs",
    ):
        assert needle in world.err, needle


def test_a_transport_that_dies_while_the_hook_measures_is_git_141(world: World) -> None:
    """Real git's own order: the transport opens first, the hook runs, the pack is written last."""
    witness = world.root / "witness"
    (witness / "home").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(witness / "home")}
    env |= {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    repo = witness / "repo"
    real_git(env, "init", "-q", "--bare", str(witness / "remote.git"))
    real_git(env, "init", "-q", "-b", "main", str(repo))
    real_git(env, "-C", str(repo), "config", "user.email", "drive@example.invalid")
    real_git(env, "-C", str(repo), "config", "user.name", "transport drive")
    (repo / "README.md").write_text("the content this push carries\n")
    real_git(env, "-C", str(repo), "add", "README.md")
    real_git(env, "-C", str(repo), "commit", "-q", "-m", "one")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        '#!/usr/bin/env bash\ncat >/dev/null\nsleep "${DRIVE_HOOK_SECONDS:-0}"\n'
        'echo "the hook measured and passed"\nexit "${DRIVE_HOOK_RC:-0}"\n'
    )
    hook.chmod(0o755)
    transport = witness / "transport"
    transport.write_text(
        '#!/usr/bin/env bash\nshift\nexec 3<&0\n/bin/sh -c "$*" <&3 &\nchild=$!\n'
        'if [ -n "${DRIVE_TRANSPORT_DIES_AFTER:-}" ]; then\n'
        '    ( sleep "$DRIVE_TRANSPORT_DIES_AFTER"; kill -9 "$child" 2>/dev/null ) &\nfi\n'
        'wait "$child"\n'
    )
    transport.chmod(0o755)

    def push(**extra: str) -> tuple[int, str]:
        done = subprocess.run(
            ["git", "push", "--force", f"ssh://localhost{witness}/remote.git", "main:main"],
            cwd=repo,
            env={**env, "GIT_SSH_COMMAND": str(transport), **extra},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return done.returncode, done.stderr

    marker = re.compile(r"hung up|Broken pipe|write error|remote end|Killed")
    rc, said = push(DRIVE_HOOK_SECONDS="3", DRIVE_TRANSPORT_DIES_AFTER="1")
    assert rc != 0
    assert rc == 141 or marker.search(said), (rc, said)
    rc, said = push(DRIVE_HOOK_SECONDS="3")
    assert rc == 0, said
    assert real_git(env, "-C", str(witness / "remote.git"), "rev-parse", "-q", "--verify", "main")
    rc, said = push(DRIVE_HOOK_RC="141")
    assert rc == 1
    assert not marker.search(said), said
    assert world.ops() == []


@pytest.mark.parametrize("arm", ["slow", "fast"])
def test_a_tunnel_under_the_floor_refuses_before_the_pack(world: World, arm: str) -> None:
    keyed(world)
    seconds = "120" if arm == "slow" else "1"
    same(world, "push", "i-up1", env=world.env(DRIVE_SSH_SECONDS=seconds))
    if arm == "fast":
        assert world.rc == 0, world.report()
        return
    assert world.rc == 2
    assert "KB/s" in world.err
    assert "push --force ssh://" not in git_flat(world)
    assert "DJB_VERIFIER_MIN_KBPS" in world.err


@pytest.mark.parametrize("arm", ["early", "never", "dead"])
def test_a_probe_that_is_not_yet_connected_is_retried_within_the_ceiling(
    world: World, arm: str
) -> None:
    keyed(world)
    not_yet = "An error occurred (TargetNotConnected) when calling the StartSession operation\n"
    env = world.env(DRIVE_SSH_SECONDS="1")
    if arm == "early":
        world.ssh(1, "rc", "255\n")
        world.ssh(1, "err", not_yet)
    elif arm == "never":
        world.ssh("default", "rc", "255\n")
        world.ssh("default", "err", not_yet)
        env = world.env(DRIVE_SSH_SECONDS="1", DJB_VERIFIER_TUNNEL_WAIT_SECONDS="10")
    else:
        world.ssh("default", "rc", "255\n")
        world.ssh("default", "err", "ssh: connect to host i-up1 port 22: Connection refused\n")
    same(world, "push", "i-up1", env=env)
    attempts = int((world.rec / "seq" / "_ssh").read_text())
    if arm == "early":
        assert world.rc == 0, world.report()
        assert world.said("not yet connected; waited 5s")
        assert world.said("DJB_VERIFIER_TUNNEL_WAIT_SECONDS")
    elif arm == "never":
        assert world.rc == 2
        assert world.said("waited on for 10s and never connected")
        assert attempts == 3
    else:
        assert world.rc == 2
        assert attempts == 1


def test_a_probe_session_is_bounded_by_real_time(world: World) -> None:
    """The probe's ssh is ended by real time: a hung session refuses under the floor, promptly."""
    keyed(world)
    world.ssh(1, "hang", ":\n")
    env = world.env(DJB_VERIFIER_MIN_KBPS="512")
    started = time.monotonic()
    assert world.vb("push", "i-up1", env=env) == 2, world.report()
    assert time.monotonic() - started < REAL_TIME_CEILING_S
    assert world.said("the probe was ended at 3s of real time")
    assert world.said("under the 512 KB/s floor")
    assert "push --force ssh://" not in git_flat(world)


# --- the box is a measuring destination, not a forge: the hook's half -------------------


def test_a_box_destination_never_carries_a_foreign_tree(scratch: Path) -> None:
    hw = hook_world(scratch / "hook-bv2")
    real_git(hw.env, "-C", str(hw.work), "checkout", "-q", "-b", "foreign")
    (hw.work / "FOREIGN.md").write_text("not this checkout\n")
    real_git(hw.env, "-C", str(hw.work), "add", "FOREIGN.md")
    real_git(hw.env, "-C", str(hw.work), "commit", "-q", "-m", "a tree that is not the checkout's")
    foreign = real_git(hw.env, "-C", str(hw.work), "rev-parse", "HEAD")
    real_git(hw.env, "-C", str(hw.work), "checkout", "-q", "main")
    rc, said = hook_push(hw, f"{foreign}:refs/heads/foreign")
    assert rc == 1, said
    assert "REFUSED — the ref being pushed is not the tree in this checkout" in said
    assert "leaves for a VERIFIER BOX" not in said


def test_the_destination_variable_alone_opens_nothing(scratch: Path) -> None:
    hw = hook_world(scratch / "hook-bv3")
    hook_union_commit(hw)
    elsewhere = scratch / "hook-bv3" / "vhome" / "elsewhere.git"
    real_git(hw.env, "init", "-q", "--bare", str(elsewhere))
    union = real_git(hw.env, "-C", str(hw.work), "rev-parse", "HEAD")
    done = subprocess.run(
        ["./scripts/githooks/pre-push", "origin", str(elsewhere)],
        cwd=hw.work,
        env={**hw.env, "DJB_PUSH_DESTINATION": "verifier-box"},
        input=f"refs/heads/main {union} refs/heads/scratch {'0' * 40}\n",
        capture_output=True,
        text=True,
    )
    said = done.stdout + done.stderr
    assert done.returncode == 0, said
    assert (
        "DJB_PUSH_DESTINATION=verifier-box ignored — the remote is not a verifier-box probe" in said
    )
    assert "STUB GATE RAN" in said
    assert "leaves for a VERIFIER BOX" not in said
