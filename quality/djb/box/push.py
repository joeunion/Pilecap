"""`push`: the vouch, the throughput probe, the shallow transfer, the worktree, the drive rows."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.djb import ledger
from quality.djb.box.core import Box, Command, clock_s, drop_tree, pause, vb_log
from quality.djb.box.shallow import fork_point, git, push_the_tree_shallow
from quality.djb.box.transport import (
    ROOT,
    Refused,
    die,
    measured_tree_here,
    say,
    spawn,
    verifier_box_user,
    verifier_checkout_path,
    warn,
)

TUNNEL_POLL_SECONDS = 5
#: A probe with no floor is still bounded: the push transport's own hour (30 s × 120).
UNFLOORED_PROBE_SECONDS = 3600


def _whole(env: dict[str, str], name: str, default: str, what: str) -> int:
    raw = env.get(name) or default
    if not raw.isdigit():
        die(f"verifier_box: {name} must be whole {what}, got '{raw}'")
    return int(raw)


def cmd_push(box: Box, args: Sequence[str]) -> int:
    """`push <id> [branch…]`: vouch, probe, transfer, move the box's worktree, send drive rows."""
    instance = args[0] if args else ""
    if not instance:
        die("verifier_box: push needs an instance id")
    branches = list(args[1:])
    box.refuse_if_reclaimed(instance)
    if not os.access(box.box_key(instance), os.R_OK):
        die(f"verifier_box: no private key for {instance}")
    env = box.cfg.env
    checkout = verifier_checkout_path()
    _, head_sha = git(env, "-C", str(ROOT), "rev-parse", "HEAD", quiet=False)
    rc, head_ref = git(env, "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD")
    if rc:
        head_ref = f"{head_ref}\nHEAD" if head_ref else "HEAD"
    _, main_sha = git(env, "-C", str(ROOT), "rev-parse", "--verify", "--quiet", "refs/heads/main")
    base_sha, base_from = fork_point(env, head_sha, head_ref, main_sha)
    if base_sha:
        vb_log(f"carried    fork point {base_sha[:8]} ({base_from}) as refs/djb/base", err=True)
    vouch_refs = ["HEAD:refs/heads/main"] + [f"refs/heads/{b}:refs/heads/{b}" for b in branches]
    refs = ["refs/heads/main:refs/heads/main"] + [
        f"refs/heads/{b}:refs/heads/{b}" for b in branches
    ]
    also = f" , and: {' '.join(branches)}" if branches else ""
    vb_log(f"pushing    HEAD ({head_ref} {head_sha[:8]}) as the box's main{also}")
    if main_sha and main_sha != head_sha:
        vb_log(
            f"           NOTE: this checkout's main is {main_sha[:8]} — the box's main will be"
            " HEAD's",
            err=True,
        )
        vb_log(
            "           tree, which is the tree this checkout can vouch for and the tree a",
            err=True,
        )
        vb_log("           verification here is about.", err=True)
    prc = vouch(box, vouch_refs)
    if prc:
        return prc
    throughput_probe(box, instance)
    prc = push_the_tree_shallow(box, instance, head_sha, checkout, base_sha, refs)
    if prc:
        return prc
    sync_box_worktree(box, instance, checkout)
    push_drive_rows(box, instance)
    return 0


def vouch(box: Box, refs: Sequence[str]) -> int:
    """Run this checkout's pre-push hook over `refs` at a scratch repository; its status."""
    cfg = box.cfg
    scratch = cfg.home / f".vouch-{os.getpid()}"
    drop_tree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    probe = scratch / "probe.git"
    with open(os.devnull, "w") as null:
        made = spawn(["git", "init", "-q", "--bare", str(probe)], env=cfg.env, stderr=null)
    if made.returncode:
        drop_tree(scratch)
        die(
            f"verifier_box: could not make a scratch repository under {cfg.home} to run the"
            " pre-push\n"
            "   hook against. Nothing was pushed."
        )
    hook_log = scratch / "hook.out"
    with hook_log.open("w") as sink:
        prc = spawn(
            ["git", "-C", str(ROOT), "push", "--dry-run", "--force", str(probe), *refs],
            env={**cfg.env, "DJB_PUSH_DESTINATION": "verifier-box"},
            stdout=sink,
            stderr=sink,
        ).returncode
    said = hook_log.read_text(errors="replace")
    sys.stderr.write(said)
    sys.stderr.flush()
    drop_tree(scratch)
    if prc:
        for line in (
            f"!! verifier_box: the pre-push hook refused this tree (exit {prc}), and nothing left"
            " this",
            "   machine. The hook's own words are above; it consults the verdict ledger and, on a",
            "   miss, measures the full gate. This is THIS machine's wall and not the box's:",
            "   there is nothing on the box that explains it and nothing there that can fix it.",
            "   The push was not attempted.",
        ):
            warn(line)
        return prc
    if "pre-push: wall " not in said:
        warn(
            "!! verifier_box: no pre-push hook ran on this checkout — set"
            " core.hooksPath=scripts/githooks (verify_start.sh does) — nothing left this machine"
        )
        raise Refused(printed=True)
    return 0


@dataclass
class _Fed(Box):
    """A `Box` whose ssh reads `feed` on stdin and writes its stderr to `errors`."""

    feed: Path = field(default=Path(os.devnull))
    errors: Path = field(default=Path(os.devnull))

    def ssh_argv(self, instance: str, *command: str) -> list[str]:
        """The one ssh argv, exec'd by `sh` with stdin and stderr redirected."""
        redirect = 'f=$1; e=$2; shift 2; exec "$@" <"$f" 2>"$e"'
        argv = super().ssh_argv(instance, *command)
        return ["sh", "-c", redirect, "sh", str(self.feed), str(self.errors), *argv]


def throughput_probe(box: Box, instance: str) -> None:
    """Send `DJB_VERIFIER_PROBE_MB` through the tunnel; refuse a rate under the floor."""
    cfg = box.cfg
    env = cfg.env
    raw = env.get("DJB_VERIFIER_PROBE_MB", "1")
    if not raw.isdigit():
        die(f"verifier_box: DJB_VERIFIER_PROBE_MB must be whole megabytes, got '{raw}'")
    megabytes = int(raw)
    if megabytes == 0:
        vb_log("probe      skipped (DJB_VERIFIER_PROBE_MB=0)")
        return
    floor = _whole(env, "DJB_VERIFIER_MIN_KBPS", "50", "KB/s")
    ceiling = _whole(env, "DJB_VERIFIER_TUNNEL_WAIT_SECONDS", "60", "seconds")
    feed = cfg.home / f".probe-{os.getpid()}"
    errors = cfg.home / f".probe-{os.getpid()}.err"
    try:
        cfg.home.mkdir(parents=True, exist_ok=True)
        with feed.open("wb") as handle:
            for _ in range(megabytes):
                handle.write(bytes(1048576))
    except OSError:
        feed.unlink(missing_ok=True)
        die(f"verifier_box: could not write a {megabytes} MB probe file under {cfg.home}")
    kb = megabytes * 1024
    bound = kb // floor + 1 if floor else UNFLOORED_PROBE_SECONDS
    fed = _Fed(cfg, feed=feed, errors=errors)
    waited = 0
    while True:
        started = clock_s()
        arc, answered = fed.ssh_within(bound, instance, "cat >/dev/null")
        sys.stdout.write(answered)
        sys.stdout.flush()
        if arc == 0:
            break
        said = _read(errors)
        if arc == 255 and "TargetNotConnected" in said and waited < ceiling:
            pause(TUNNEL_POLL_SECONDS)
            waited += TUNNEL_POLL_SECONDS
            vb_log(
                f"tunnel     not yet connected; waited {waited}s (ceiling {ceiling}s,"
                " DJB_VERIFIER_TUNNEL_WAIT_SECONDS)",
                err=True,
            )
            continue
        if arc == 124:
            break
        _drain(said)
        feed.unlink(missing_ok=True)
        errors.unlink(missing_ok=True)
        waited_line = (
            f"\n   The session channel was waited on for {waited}s and never connected."
            if waited
            else ""
        )
        die(
            f"verifier_box: the throughput probe could not reach {instance} through the tunnel at"
            " all. Nothing was\n"
            f"   pushed. The box is up as far as this wrapper knows; the transport is"
            f" not.{waited_line}"
        )
    _drain(_read(errors))
    errors.unlink(missing_ok=True)
    feed.unlink(missing_ok=True)
    elapsed = bound if arc == 124 else max(clock_s() - started, 1)
    kbps = kb // elapsed
    vb_log(
        f"probe      {megabytes} MB through the tunnel in {elapsed}s = {kbps} KB/s (floor"
        f" {floor} KB/s)",
        err=True,
    )
    if arc == 124:
        vb_log(f"           the probe was ended at {bound}s of real time", err=True)
    if kbps < floor or arc == 124:
        die(
            f"verifier_box: the tunnel to {instance} is carrying {kbps} KB/s, under the {floor}"
            " KB/s floor.\n"
            "   NOTHING WAS PUSHED, deliberately: a tree that needs a few minutes on a\n"
            "   healthy tunnel needs hours on this one, and an hour of a push that looks\n"
            "   alive is worse than a refusal — it was measured at ~7 KB/s on a real box,\n"
            "   where a 213 MB push stalled twice at 16 MB and a 9 MB file took 18 minutes.\n"
            "   This is the TUNNEL, not the box and not this wrapper. What has changed\n"
            "   before: the base AMI (its SSM agent), the region's Session Manager data\n"
            "   plane, and this machine's own network. 'census' prints the image each box is\n"
            "   running; DJB_VERIFIER_AL2023_AMI pins a base that was measured to work.\n"
            "   Take the box down, or raise the floor deliberately with DJB_VERIFIER_MIN_KBPS\n"
            "   if a slow push is what you want."
        )


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _drain(text: str) -> None:
    sys.stderr.write(text)
    sys.stderr.flush()


def sync_box_worktree(box: Box, instance: str, checkout: str) -> None:
    """Move the box's working tree onto the pushed main; refuse unless the measured trees agree."""
    with open(os.devnull, "w") as null:
        moved = spawn(
            box.ssh_argv(instance, f"git -C {checkout} reset --hard refs/heads/main"),
            env=box.cfg.env,
            stdout=null,
        )
    if moved.returncode:
        die(
            "verifier_box: could not move the box's working tree onto the pushed main. The ref"
            " landed and\n"
            "   the files did not, which is the shape that measured the image for a whole\n"
            "   cycle: the gate over there would grade whatever the box is standing on."
        )
    here = measured_tree_here("HEAD", box.cfg.env)
    if not here:
        die(
            "verifier_box: could not read this checkout's MEASURED tree (gate_measured_tree_of"
            " HEAD), so there\n"
            "   is nothing to hold the box's worktree up against. The ref moved; nothing further"
            " was attempted."
        )
    there = box.measured_tree_on_box(instance, checkout, "HEAD")
    if here != there:
        die(
            f"verifier_box: the box's WORKING TREE is {there or '<unreadable>'} and this"
            f" checkout's is {here}.\n"
            "   The ref moved and the files did not agree with it. A gate on the box would\n"
            "   measure that tree and bank an honest verdict about the wrong thing —\n"
            "   which is exactly what every consult before this check did. Nothing further\n"
            "   was attempted."
        )
    rung = box.box_rung(instance)
    say(f"tree       HEAD measured {here[:8]} = box WORKTREE measured {there[:8]} · rung {rung}")


def drive_rows(env: dict[str, str]) -> list[str] | None:
    """This checkout's `drive` rows, verbatim, through the ledger's reader; None for no ledger."""
    try:
        path = ledger.ledger_path(ROOT)
    except (ledger.Refused, ledger.Mismatch):
        return None
    if not os.access(path, os.R_OK):
        return None
    found = []
    for _, line in ledger.rows(path):
        fields = line.split()
        if len(fields) > 2 and fields[0] == ledger.SCHEMA and fields[2] == "drive":
            found.append(line)
    return found


def push_drive_rows(box: Box, instance: str) -> None:
    """Carry the drive rows the box has not been sent to `~/verify/<rung>/ledger.in`, by scp."""
    cfg = box.cfg
    if not os.access(ROOT / "scripts" / "gate_ledger.sh", os.R_OK):
        vb_log(
            f"drive rows: not sent — no {ROOT}/scripts/gate_ledger.sh to read the ledger's path"
            " from",
            err=True,
        )
        return
    rows = drive_rows(cfg.env)
    if rows is None or not rows:
        vb_log("drive rows: none to send")
        return
    rung = box.box_rung(instance)
    sent_file = box.box_dir(instance) / "drive-rows.sent"
    dest, before = "ledger.in", ""
    if _read(sent_file):
        had = set(_read(sent_file).splitlines())
        before = str(len(rows))
        rows = [row for row in rows if row not in had]
        if not rows:
            vb_log(f"drive rows: none to send — {instance} was sent all {before} already")
            return
        dest = "ledger.in.part"
    cfg.home.mkdir(parents=True, exist_ok=True)
    scratch = cfg.home / f".ledger-out-{os.getpid()}"
    scratch.write_text("".join(f"{row}\n" for row in rows))
    try:
        if box.ssh_capture(instance, f"mkdir -p ~/verify/{rung}")[0]:
            vb_log(f"drive rows: not sent — could not make ~/verify/{rung} on {instance}", err=True)
            return
        remote = f"{verifier_box_user()}@{instance}:verify/{rung}/{dest}"
        if spawn(scp_argv(box, instance, str(scratch), remote), env=cfg.env).returncode:
            vb_log(
                f"drive rows: NOT sent — the scp to {instance} failed; the box will re-drive what"
                " it could have reused",
                err=True,
            )
            return
        appended = (
            dest == "ledger.in"
            or not box.ssh_capture(
                instance,
                f"cat ~/verify/{rung}/ledger.in.part >> ~/verify/{rung}/ledger.in && rm -f"
                f" ~/verify/{rung}/ledger.in.part",
            )[0]
        )
        if not appended:
            vb_log(
                f"drive rows: the delta reached {instance} and was NOT appended; the box will"
                " re-drive what it could have reused",
                err=True,
            )
            return
        with sent_file.open("a") as handle:
            handle.write(scratch.read_text())
        delta = f" (the delta; {before} in the ledger)" if before else ""
        vb_log(f"drive rows: {len(rows)} sent to {instance}:~/verify/{rung}/ledger.in{delta}")
    finally:
        scratch.unlink(missing_ok=True)


def scp_argv(box: Box, instance: str, *paths: str) -> list[str]:
    """The scp argv: key, the tunnel, no host-key pinning, then `paths`."""
    return [
        "scp",
        "-i",
        str(box.box_key(instance)),
        "-o",
        f"ProxyCommand={box.proxy_command()}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        *paths,
    ]


def cmd_fetch(box: Box, args: Sequence[str]) -> int:
    """`fetch <id> <remote path> <local path>`: one scp of one file home."""
    # stub: cmd_fetch — harvest.py's; registered below only until that module exists
    instance, remote, local = (list(args) + ["", "", ""])[:3]
    if not (instance and remote and local):
        die("verifier_box: fetch takes: fetch <id> <remote path> <local path>")
    box.refuse_if_reclaimed(instance)
    if not os.access(box.box_key(instance), os.R_OK):
        die(f"verifier_box: no private key for {instance}")
    argv = scp_argv(box, instance, f"{verifier_box_user()}@{instance}:{remote}", local)
    rc = spawn(argv, env=box.cfg.env).returncode
    if rc:
        return rc
    vb_log(f"fetched {instance}:{remote} -> {local}")
    return 0


COMMANDS: dict[str, Command] = {"push": cmd_push}
if importlib.util.find_spec("quality.djb.box.harvest") is None:
    COMMANDS["fetch"] = cmd_fetch
