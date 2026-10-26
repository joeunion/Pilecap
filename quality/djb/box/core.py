"""The box client's core: configuration, walls, clock, registry, and run, wait, down, ceiling."""

from __future__ import annotations

import importlib
import os
import pkgutil
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from quality.djb.box.transport import (
    ROOT,
    Refused,
    Transport,
    api_line,
    die,
    last_line,
    none_empty,
    say,
    spawn,
    warn,
    which,
)

SUBCOMMANDS = (
    "up down pool census ceiling zones run loop leg wait fetch harvest harvest-drives push bake"
)


# --- the clock ---------------------------------------------------------------------


def clock_s() -> int:
    """Epoch seconds from the PATH's `date +%s`."""
    done = subprocess.run(["date", "+%s"], capture_output=True, text=True)
    text = done.stdout.strip()
    if done.returncode != 0 or not text.isdigit():
        die(f"verifier_box: the clock (`date +%s`) answered {text!r}")
    return int(text)


def pause(seconds: int) -> None:
    """The PATH's `sleep`."""
    subprocess.run(["sleep", str(seconds)])


def iso_at(epoch: int) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` of an epoch, in UTC."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_of_iso(iso: str) -> int | None:
    """The epoch of a `YYYY-MM-DDTHH:MM:SSZ` stamp, or None for any other shape."""
    try:
        return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())
    except ValueError:
        return None


def stamp_of(epoch: int) -> str:
    """`HH:MM:SS` of an epoch, in UTC."""
    return iso_at(epoch)[11:19]


def vb_log(text: str, *, err: bool = False) -> None:
    """`verifier_box: [HH:MM:SS] <text>` on stdout, or stderr when `err`."""
    line = f"verifier_box: [{stamp_of(clock_s())}] {text}"
    (warn if err else say)(line)


# --- the configuration -------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Every knob the environment sets, read once, with the shell's defaults."""

    namespace: str
    region: str
    profile: str
    home: Path
    owner: str
    instance_type: str
    ttl_hours: str
    idle_minutes: str
    wait_poll_seconds: int
    max_boxes: int
    max_boxes_source: str
    ceiling_file: Path
    ceiling_file_value: str
    env: dict[str, str]

    @property
    def group_name(self) -> str:
        """The security group every box joins."""
        return f"{self.namespace}-verifier"


TTL_CAP = 12
CEILING_DEFAULT = 2
ONLINE_POLL_SECONDS = 10
SPOT_QUOTA_CODE = "L-34B43A08"


def load_config(env: dict[str, str]) -> Config:
    """The configuration from `env`; refuses a missing namespace or region and a bad ceiling."""
    namespace = env.get("DJB_DEPLOY_NAMESPACE", "")
    if not namespace:
        die(
            "verifier_box: DJB_DEPLOY_NAMESPACE is required — this deployment's namespace,\n"
            "   the slug every identity, security group, image and tag here is composed from.\n"
            "   There is no default: more than one product shares this AWS account, and a\n"
            "   guessed namespace is a write into somebody else's resources. It is a slot in\n"
            "   this environment's env file (deploy/env.staging.example)."
        )
    region = env.get("DJB_VERIFIER_REGION", "")
    if not region:
        die(
            "verifier_box: DJB_VERIFIER_REGION is required — the region the verifier boxes\n"
            "   live in. There is no default and this script never inherits the profile's:\n"
            "   your own configured default region is very often a different one, and a box\n"
            "   launched there is a box this census will never see and the reaper's bill\n"
            "   nobody reads. Set it in the shell you run this from."
        )
    home = Path(env.get("DJB_VERIFIER_HOME") or f"{env.get('HOME', '')}/.{namespace}/verifier")
    ceiling_file = home / "ceiling"
    file_value = ""
    if ceiling_file.is_file():
        try:
            first = ceiling_file.read_text().splitlines()
        except OSError:
            die(
                f"verifier_box: the ceiling file {ceiling_file} exists and cannot be read.\n"
                "   Nothing was launched. Fix its permissions, or remove it and the default\n"
                f"   {CEILING_DEFAULT} applies again."
            )
        file_value = re.sub(r"\s", "", first[0] if first else "")
        if not file_value.isdigit() or file_value == "0":
            die(
                f"verifier_box: the ceiling file {ceiling_file} does not hold a positive whole"
                " number of boxes:\n"
                f"   '{file_value}'\n"
                "   Nothing was launched. A ceiling that cannot be read is not a ceiling of 2 —\n"
                "   it is a number nobody typed. Write one with\n"
                "   `./scripts/verifier_box.sh ceiling <n>`, or remove the file."
            )
    raw_max = env.get("DJB_VERIFIER_MAX_BOXES", "")
    if raw_max:
        if not raw_max.isdigit() or raw_max == "0":
            die(
                "verifier_box: DJB_VERIFIER_MAX_BOXES is not a positive whole number of boxes:\n"
                f"   '{raw_max}'\n"
                f"   Nothing was launched. Unset it to fall through to {ceiling_file} or the\n"
                f"   default {CEILING_DEFAULT}."
            )
        max_boxes, source = int(raw_max), "env"
    elif file_value:
        max_boxes, source = int(file_value), "file"
    else:
        max_boxes, source = CEILING_DEFAULT, "default"
    return Config(
        namespace=namespace,
        region=region,
        profile=env.get("DJB_VERIFIER_PROFILE") or f"{namespace}-verifier",
        home=home,
        owner=verifier_owner(env),
        instance_type=env.get("DJB_VERIFIER_INSTANCE_TYPE") or "c7g.4xlarge",
        ttl_hours=env.get("DJB_VERIFIER_TTL_HOURS") or "4",
        idle_minutes=env.get("DJB_VERIFIER_IDLE_MINUTES") or "30",
        wait_poll_seconds=int(env.get("DJB_VERIFIER_WAIT_POLL_SECONDS") or "120"),
        max_boxes=max_boxes,
        max_boxes_source=source,
        ceiling_file=ceiling_file,
        ceiling_file_value=file_value,
        env=env,
    )


def verifier_owner(env: dict[str, str]) -> str:
    """`DJB_VERIFIER_OWNER`, else `git config user.name`, else `unknown`, said on stderr."""
    if env.get("DJB_VERIFIER_OWNER"):
        return env["DJB_VERIFIER_OWNER"]
    if which("git", env):
        done = spawn(
            ["git", "config", "user.name"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=ROOT,
        )
        name = done.stdout.strip()
        if done.returncode == 0 and name:
            return name
    warn("verifier_box: no DJB_VERIFIER_OWNER and no git user.name — the owner tag is 'unknown'")
    return "unknown"


# --- the registry: every module's `COMMANDS`, found by discovery --------------------

Command = Callable[["Box", Sequence[str]], int]


def commands() -> dict[str, Command]:
    """Every subcommand the package's modules declare in their `COMMANDS`; a name twice refuses."""
    package = __name__.rpartition(".")[0]
    found: dict[str, Command] = {}
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if module.name.startswith("_"):
            continue
        declared = getattr(importlib.import_module(f"{package}.{module.name}"), "COMMANDS", {})
        for name, command in declared.items():
            if name in found:
                die(f"verifier_box: the subcommand '{name}' is declared twice in {package}")
            found[name] = command
    return found


def run_command(box: Box, name: str, args: Sequence[str]) -> int:
    """Run the subcommand `name` through the registry; one not ported yet refuses by name."""
    found = commands()
    if name in found:
        return found[name](box, args)
    if name in SUBCOMMANDS.split():
        not_ported(name)
    die(f"verifier_box: unknown subcommand '{name}': {SUBCOMMANDS}")


# --- the walls ---------------------------------------------------------------------


@dataclass
class Box(Transport):
    """One invocation's world: its configuration, the transport around it, and the walls."""

    def print_owner_commands(self) -> None:
        """The two commands that mint the identity these boxes need, verbatim."""
        cfg = self.cfg
        say("   The identity these boxes need is the owner's to mint, once:")
        say("")
        say(
            f"     DJB_DEPLOY_NAMESPACE={cfg.namespace} DJB_VERIFIER_ACCOUNT=<12-digit account>"
            f" DJB_VERIFIER_REGION={cfg.region} \\"
        )
        say("       ./deploy/iam/verifier_bootstrap.sh --confirm")
        say(f"     aws configure --profile {cfg.profile}")
        say("")
        say("   docs/runbooks/deploy.md's verifier-box section is the same two commands.")

    def require_profile(self) -> None:
        """Refuse, printing the owner's commands, when `aws configure list` cannot see it."""
        if self.aws_ok("configure", "list"):
            return
        warn(f"!! verifier_box: no AWS profile '{self.cfg.profile}' on this machine.")
        self.print_owner_commands()
        raise Refused(printed=True)

    def require_plugin(self) -> None:
        """Refuse when `session-manager-plugin` is not on PATH."""
        if which("session-manager-plugin", self.cfg.env):
            return
        die(
            "verifier_box: session-manager-plugin is not on PATH, and every command here tunnels\n"
            "   through it. It is a TOOL, not a credential, so it is yours to install:\n"
            "     brew install --cask session-manager-plugin"
        )

    def newest_image(self) -> str:
        """The newest image tagged as this namespace's verifier image."""
        return self.aws_text(
            "ec2",
            "describe-images",
            "--owners",
            "self",
            "--filters",
            "Name=tag:djb:role,Values=verifier-image",
            f"Name=tag:djb:namespace,Values={self.cfg.namespace}",
            "--query",
            "sort_by(Images,&CreationDate)[-1].ImageId",
            "--output",
            "text",
        )

    def require_image(self) -> str:
        """The newest image, or a refusal naming `bake` and the untagged-capture road."""
        image = self.newest_image()
        if image in ("", "None", "null"):
            cfg = self.cfg
            die(
                f"verifier_box: no verifier image in {cfg.region} for namespace '{cfg.namespace}'."
                " Bake one first:\n"
                "     scripts/verifier_box.sh bake\n"
                "   It takes about twenty minutes and costs about a dime; every launch after it\n"
                "   is a boot and a push.\n"
                "   AN IMAGE THAT EXISTS AND IS NOT TAGGED LOOKS EXACTLY LIKE THIS, and it has\n"
                "   happened: the lookup above filters on djb:role and djb:namespace, and a\n"
                "   capture whose tags the policy refused produces a working image that matches\n"
                "   neither. If a bake printed an image id and said its tags were refused, launch\n"
                "   from it by hand — 'up --for <rung> --image-id <ami>' — and fix the policy\n"
                "   (deploy/iam/verifier_bootstrap.sh) before the next bake."
            )
        return image

    def require_named_image(self, image: str) -> str:
        """`image` when it is `available`; a refusal naming its state otherwise."""
        row = self.aws_text(
            "ec2",
            "describe-images",
            "--image-ids",
            image,
            "--query",
            "Images[0].[Name,State]",
            "--output",
            "text",
        )
        name, _, state = row.partition("\t") if "\t" in row else (row, "", row)
        if state == "available":
            pass
        elif state in ("", "None", "null"):
            die(
                f"verifier_box: {image} is not an image this credential can see in"
                f" {self.cfg.region}. Nothing was\n"
                "   launched. Check the id, the region and the namespace's profile."
            )
        else:
            die(
                f"verifier_box: {image} is '{state}', not 'available'. Nothing was launched:"
                " an image that is\n"
                "   still being captured has no root volume to boot from, and the API's refusal\n"
                "   arrives seconds AFTER the launch call rather than before it. A capture\n"
                "   normally reaches 'available' in a few minutes — 'aws ec2 describe-images\n"
                f"   --image-ids {image}' is the thing to watch."
            )
        vb_log(
            f"image      {image}  {name or '<unnamed>'}  (named on the command line;"
            " the tag lookup was not used)",
            err=True,
        )
        return image


# --- run and wait ------------------------------------------------------------------


def cmd_run(box: Box, args: Sequence[str]) -> int:
    """`run <id> -- <command...>`: the remote command's own status."""
    instance = args[0] if args else ""
    if not instance:
        die("verifier_box: run needs an instance id")
    rest = list(args[1:])
    if not rest or rest[0] != "--":
        die("verifier_box: run takes: run <id> -- <command...>")
    rest = rest[1:]
    if not rest:
        die("verifier_box: run needs a command after --")
    idle = box.cfg.idle_minutes
    if not idle.isdigit() or int(idle) == 0:
        die(f"verifier_box: DJB_VERIFIER_IDLE_MINUTES takes whole minutes, got '{idle}'")
    box.refuse_if_reclaimed(instance)
    done = threading.Event()
    keeper = threading.Thread(
        target=keep_alive, args=(box, instance, int(idle) * 60 // 3, done), daemon=True
    )
    keeper.start()
    try:
        return box.ssh_to(instance, *rest)
    finally:
        done.set()


def keep_alive(box: Box, instance: str, interval: int, done: threading.Event) -> None:
    """Touch the box's activity marker every `interval` seconds until `done`, each touch bounded."""
    step = max(1, interval // 10)
    try:
        while True:
            waited = 0
            while waited < interval:
                pause(step)
                waited += step
                if done.is_set():
                    return
            box.ssh_within(interval, instance, "true")
    except Refused:
        return


def cmd_wait(box: Box, args: Sequence[str]) -> int:
    """`wait <id> <name>`: poll the detached gate, print its tail and reds, exit as it did."""
    instance = args[0] if args else ""
    name = args[1] if len(args) > 1 else ""
    if not instance or not name:
        die("verifier_box: wait takes: wait <id> <name>")
    pidfile = box.box_dir(instance) / f"{name}.pid"
    if not os.access(pidfile, os.R_OK):
        die(f"verifier_box: no detached gate named '{name}' for {instance} on this machine")
    pid = pidfile.read_text().rstrip("\n")
    rung = box.box_rung(instance)
    poll = box.cfg.wait_poll_seconds
    misses = 0
    while True:
        box.refuse_if_reclaimed(instance)
        prc, alive = box.ssh_within(
            poll, instance, f"kill -0 {pid} 2>/dev/null && echo alive || echo gone"
        )
        if prc == 124:
            box.refuse_if_reclaimed(instance)
            misses += 1
            if misses >= 3:
                die(
                    f"verifier_box: {instance} did not answer {misses} polls of {poll}s and"
                    " still reads as running. The verdict is unread, never red: fetch the log"
                    " by hand or take the box down."
                )
            continue
        misses = 0
        if last_line(alive) != "alive":
            break
        pause(ONLINE_POLL_SECONDS)
    prc, rc = box.ssh_within(poll, instance, f"cat ~/verify/{rung}/{name}.rc 2>/dev/null || echo 2")
    if prc == 124:
        box.refuse_if_reclaimed(instance)
        die(
            f"verifier_box: {instance} did not answer the read of '{name}'s exit status in"
            f" {poll}s. The verdict is unread, never red."
        )
    rc = last_line(rc)
    log = f"~/verify/{rung}/{name}.log"
    say(f"--- last 40 lines of {log} ---")
    box.ssh_to(instance, red_blocks_command(log))
    say(f"--- gate exit {rc} ---")
    if not rc.isdigit():
        die(f"verifier_box: the box did not record an exit status for '{name}'")
    if rc == "0":
        harvest_after_wait(box, instance, name)
    elif rc in ("1", "2"):
        from quality.djb.box.harvest import fetch_whole_log  # harvest imports this module

        fetch_whole_log(box, instance, name, log)
    return int(rc)


def harvest_after_wait(box: Box, instance: str, name: str) -> None:
    """A green wait's harvest: its lines, or one line saying why none came home."""
    try:
        run_command(box, "harvest", [instance, name])
    except Refused as refused:
        first = str(refused).split("\n")[0].removeprefix("verifier_box: ")
        say(f"wait: no loop row came home — {first}")


def red_blocks_command(log: str) -> str:
    """The remote line that prints the log's last 40 lines, then every RED block above them."""
    return (
        f"tail -n 40 {log} 2>/dev/null || true; awk 'NR == FNR {{ n = NR; next }} FNR > n - 40"
        ' { exit } /^!! (and )?RED:/ { if (!said) { print "--- every RED block above those'
        ' forty lines ---"; said = 1 } on = 1; print; next } on && /^ / { print; next }'
        f" {{ on = 0 }}' {log} {log} 2>/dev/null || true"
    )


# --- down --------------------------------------------------------------------------


def cmd_down(box: Box, args: Sequence[str]) -> int:
    """`down <id>` or `down --all-mine`: terminate, each box through `terminate_one`."""
    target = args[0] if args else ""
    if not target:
        die("verifier_box: down takes an instance id or --all-mine")
    box.require_profile()
    if target != "--all-mine":
        return terminate_one(box, target)
    ids = box.aws_text(
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:djb:namespace,Values={box.cfg.namespace}",
        "Name=instance-state-name,Values=pending,running",
        "--query",
        "Reservations[].Instances[].InstanceId",
        "--output",
        "text",
    )
    if not ids:
        vb_log(f"no running boxes in namespace {box.cfg.namespace}")
        return 0
    left = ""
    for instance in ids.split():
        owner = box.tag_of(instance, "djb:owner")
        if owner == box.cfg.owner:
            rc = terminate_one(box, instance)
            if rc:
                return rc
        else:
            left += f"\n   left {instance} — owner {owner}, not {box.cfg.owner}"
    if left:
        vb_log(f"boxes this session does not own were left alone:{left}")
    return 0


def terminate_one(box: Box, instance: str) -> int:
    """Terminate one of this namespace's boxes after ONE describe of its state and tags."""
    rc, look = box.aws_both(
        "ec2",
        "describe-instances",
        "--instance-ids",
        instance,
        "--query",
        "Reservations[0].Instances[0].[State.Name,StateReason.Code,"
        "Tags[?Key==`djb:role`].Value|[0],Tags[?Key==`djb:namespace`].Value|[0]]",
        "--output",
        "text",
    )
    if rc != 0:
        if "InvalidInstanceID.NotFound" in look:
            drop_tree(box.box_dir(instance))
            say(f"already gone {instance} (not-found — EC2 no longer holds this instance)")
            return 0
        warn(f"!! verifier_box: could not look at {instance}: {api_line(look)}")
        warn("   NOTHING was terminated, and this is not a claim that the box is not ours —")
        warn("   it is the API refusing the question. Fix the credential or the throttle and")
        warn("   run it again; 'census' reads the same fleet.")
        raise Refused(printed=True)
    fields = [none_empty(f) for f in look.split("\n")[0].split("\t")]
    state, reason, role, ns = (fields + ["", "", "", ""])[:4]
    if state in ("terminated", "shutting-down"):
        drop_tree(box.box_dir(instance))
        say(f"already gone {instance} ({reason or 'no reason given'})")
        return 0
    if role not in ("verifier", "verifier-bake"):
        die(
            f"verifier_box: {instance} is not a verifier box (djb:role={role or 'none'});"
            " nothing terminated."
        )
    if ns != box.cfg.namespace:
        die(
            f"verifier_box: {instance} belongs to namespace '{ns or 'none'}', not"
            f" '{box.cfg.namespace}'; nothing terminated.\n"
            "   One product's census never terminates another's boxes."
        )
    status = box.aws_status("ec2", "terminate-instances", "--instance-ids", instance)
    if status != 0:
        return status
    drop_tree(box.box_dir(instance))
    say(f"terminated {instance}")
    return 0


def terminate_or_by_hand(box: Box, instance: str) -> int:
    """`terminate_one`, a refusal kept as a status, and a failure naming the hand road."""
    try:
        trc = terminate_one(box, instance)
    except Refused as refused:
        if not refused.printed:
            warn(f"!! {refused}")
        trc = 2
    if trc == 0:
        return 0
    warn(
        f"!! verifier_box: could not terminate {instance} (aws exit {trc}) — IT IS STILL UP"
        " AND IT IS\n"
        "   STILL BILLING, and nothing else is going to notice except its expiry tag.\n"
        "   TAKE IT DOWN BY HAND:\n"
        f"     scripts/verifier_box.sh down {instance}\n"
        "   then read the fleet back, because a call that failed may also have half\n"
        "   worked and this box is not necessarily the only one on the clock:\n"
        "     scripts/verifier_box.sh census"
    )
    return trc


# --- ceiling -----------------------------------------------------------------------


def ceiling_sources(box: Box) -> str:
    """The three places a ceiling can come from, `->` against the one that bound."""
    cfg = box.cfg
    mark = {src: "->" if cfg.max_boxes_source == src else "  " for src in ("env", "file")}
    mark["default"] = "->" if cfg.max_boxes_source == "default" else "  "
    return (
        f"   {mark['env']} env      DJB_VERIFIER_MAX_BOXES"
        f"  {cfg.env.get('DJB_VERIFIER_MAX_BOXES') or 'unset'}\n"
        f"   {mark['file']} file     {cfg.ceiling_file}  {cfg.ceiling_file_value or 'absent'}\n"
        f"   {mark['default']} default  {CEILING_DEFAULT}"
    )


def cmd_ceiling(box: Box, args: Sequence[str]) -> int:
    """`ceiling [n]`: the ceiling, its three sources and the Spot quota; `n` writes the file."""
    want = ""
    for word in args:
        if word in ("-h", "--help"):
            return usage()
        if word.startswith("-"):
            die(
                f"verifier_box: unknown argument '{word}' to ceiling: it takes a whole number"
                " of boxes, or nothing"
            )
        if want:
            die(f"verifier_box: ceiling takes at most one number, got '{want}' and '{word}'")
        want = word
    cfg = box.cfg
    if want:
        if not want.isdigit() or want == "0":
            die(
                f"verifier_box: ceiling takes a positive whole number of boxes, got '{want}'.\n"
                f"   {cfg.ceiling_file} was not written."
            )
        try:
            cfg.home.mkdir(parents=True, exist_ok=True)
            cfg.ceiling_file.write_text(f"{want}\n")
        except OSError:
            die(f"verifier_box: could not write {cfg.ceiling_file}")
        say(f"wrote {cfg.ceiling_file} = {want}")
        source = cfg.max_boxes_source
        ceiling = cfg.max_boxes
        if source != "env":
            ceiling, source = int(want), "file"
        cfg = box.cfg = replace(
            cfg, ceiling_file_value=want, max_boxes=ceiling, max_boxes_source=source
        )
    say(f"ceiling {cfg.max_boxes} ({cfg.max_boxes_source})")
    say(ceiling_sources(box))
    quota = "unknown"
    rc, q = box.aws_quiet(
        "service-quotas",
        "get-service-quota",
        "--service-code",
        "ec2",
        "--quota-code",
        SPOT_QUOTA_CODE,
        "--query",
        "Quota.Value",
        "--output",
        "text",
    )
    if rc == 0 and q not in ("", "None", "null") and re.search(r"[0-9]", q):
        quota = q
    say(
        f"      quota    {SPOT_QUOTA_CODE}  {quota}  (Spot vCPU in {cfg.region};"
        f" this type is {cfg.instance_type})"
    )
    if quota == "unknown":
        say("               could not look — the local ceiling above still stands")
    return 0


COMMANDS: dict[str, Command] = {
    "run": cmd_run,
    "wait": cmd_wait,
    "down": cmd_down,
    "ceiling": cmd_ceiling,
}


# --- the entry -------------------------------------------------------------------


SYNOPSIS = (
    "verifier_box.sh up --for <rung> [--az <az>] [--ttl <h>] [--idle <min>] [--type <t>]"
    " [--on-demand] [--no-push] [--image-id <ami>]",
    "verifier_box.sh down <id> | --all-mine",
    "verifier_box.sh pool --want <N> [--idle <min>]",
    "verifier_box.sh census",
    "verifier_box.sh ceiling [<n>]",
    "verifier_box.sh zones",
    "verifier_box.sh run <id> -- <cmd...>",
    "verifier_box.sh loop <id> --log <name>",
    "verifier_box.sh leg <id> --unit <unit> [--shard k/N] [--passes 1|2] --log <name>",
    "verifier_box.sh wait <id> <name>",
    "verifier_box.sh fetch <id> <remote> <local>",
    "verifier_box.sh harvest <id> <name>",
    "verifier_box.sh harvest-drives <id> <tree>",
    "verifier_box.sh push <id> [<branch>...]",
    "verifier_box.sh bake [--prune] [--keep]",
)


def usage() -> int:
    """The two-line purpose and the synopsis, one line per subcommand; exit 2."""
    say("verifier_box.sh — one throwaway EC2 machine per verification, brought up,")
    say("  pushed to, run on, and taken down, from this laptop.")
    for line in SYNOPSIS:
        say(f" {line}")
    return 2


def drop_tree(path: Path) -> None:
    """`rm -rf path`."""
    shutil.rmtree(path, ignore_errors=True)


def not_ported(sub: str) -> NoReturn:
    """Refuse a subcommand `scripts/verifier_box.sh` still serves alone."""
    die(f"verifier_box: '{sub}' is not ported to quality/djb/box yet — scripts/verifier_box.sh")
