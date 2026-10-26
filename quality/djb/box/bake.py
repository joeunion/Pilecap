"""`bake`: one on-demand box, its bootstrap, the push, the recipe, the capture, the box down."""

from __future__ import annotations

import os
import shutil
import signal
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType

from quality.djb.box.core import (
    ONLINE_POLL_SECONDS,
    Box,
    Command,
    clock_s,
    drop_tree,
    iso_at,
    pause,
    terminate_one,
    terminate_or_by_hand,
    vb_log,
)
from quality.djb.box.image import (
    bake_prune,
    bake_teardown,
    image_name_and_state,
    print_untagged_capture,
)
from quality.djb.box.launch import run_instances_common, security_group, wait_for_ssm
from quality.djb.box.push import cmd_push
from quality.djb.box.shallow import git
from quality.djb.box.transport import (
    PIPE,
    ROOT,
    STDOUT,
    Refused,
    die,
    say,
    spawn,
    verifier_box_user,
    verifier_checkout_path,
    warn,
)

BAKE_SEAM = ROOT / "deploy" / "verifier" / "bake-user-data.yaml"
AL2023_PARAM = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
BAKE_READY_MARKER = "/run/verifier/bake-ready"
BOOTSTRAP_WAIT_SECONDS = 600
CAPTURE_WAIT_SECONDS = 1800
#: The recipe's session is bounded by the push transport's own hour (30 s × 120).
RECIPE_SECONDS = 3600
READY_LINE = "ready for create-image"
SIGNAL_STATUS = {signal.SIGINT: 130, signal.SIGTERM: 143}


class Stopped(Exception):
    """The bake's own exit with `status`: every way out after the launch runs the teardown."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


@dataclass
class Phases:
    """The bake's phase clock: each phase's duration, summarised once."""

    log: str = ""
    name: str = ""
    start: int = 0
    origin: int = 0
    summarised: bool = False

    def begin(self, name: str) -> None:
        """Close the phase in flight and open `name`."""
        self.end()
        self.name = name
        self.start = clock_s()
        if not self.origin:
            self.origin = self.start

    def end(self) -> None:
        """Close the phase in flight, if any."""
        if not self.name:
            return
        self.log += f"{self.name} {clock_s() - self.start}s · "
        self.name = ""

    def summary(self) -> None:
        """`phases  <name> <n>s · … total <n>s`, once, the phase in flight marked incomplete."""
        if self.summarised:
            return
        line = self.log
        if self.name:
            line += f"{self.name} {clock_s() - self.start}s (incomplete) · "
        if not line:
            return
        self.summarised = True
        vb_log(f"phases  {line}total {clock_s() - self.origin}s")


@dataclass
class Signals:
    """INT and TERM held until the step in flight ends, then the shell's `exit 130`/`exit 143`."""

    caught: list[int] = field(default_factory=list)

    def _hold(self, signum: int, frame: FrameType | None) -> None:
        self.caught.append(signum)

    @contextmanager
    def armed(self) -> Iterator[Signals]:
        """The two handlers installed for the block, the previous ones restored after."""
        before = {sig: signal.signal(sig, self._hold) for sig in SIGNAL_STATUS}
        try:
            yield self
        finally:
            for sig, handler in before.items():
                signal.signal(sig, handler)

    def check(self) -> None:
        """Stop with the first held signal's status."""
        if self.caught:
            raise Stopped(SIGNAL_STATUS[signal.Signals(self.caught[0])])


def ascii_only(what: str, value: str) -> None:
    """Refuse `value` unless every character is printable 7-bit ASCII (`create-image`'s rule)."""
    if all(0x20 <= ord(char) <= 0x7E for char in value):
        return
    die(
        f"verifier_box: the {what} is not ASCII, and EC2's create-image refuses a name or a"
        " description\n"
        f"   that is not: '{value}'\n"
        "   Nothing was launched and nothing was captured. Every character in an image's\n"
        "   name and description comes from this deployment's namespace\n"
        "   (DJB_DEPLOY_NAMESPACE) and a git sha; the sha is hex, so the namespace is\n"
        "   where this came from. A namespace is a slug — letters, digits and hyphens —\n"
        "   in every other place it is used too (the profile, the security group, the\n"
        "   instance profile and the tags)."
    )


def wait_for_bake_bootstrap(box: Box, instance: str, signals: Signals) -> tuple[bool, int]:
    """Probe for the seam's ready marker until the ceiling; whether it came and the time waited."""
    started = clock_s()
    waited = 0
    while waited < BOOTSTRAP_WAIT_SECONDS:
        bound = max(ONLINE_POLL_SECONDS, BOOTSTRAP_WAIT_SECONDS - waited)
        rc, _ = box.ssh_within(bound, instance, f"test -f {BAKE_READY_MARKER}")
        signals.check()
        if rc == 0:
            return True, waited
        pause(ONLINE_POLL_SECONDS)
        signals.check()
        waited = clock_s() - started
    return False, waited


def bake_keep_hands_over(box: Box, instance: str, why: str) -> None:
    """The `--keep` hand-over: the box is up, unwatched, and these commands reach it and end it."""
    warn(f"!! verifier_box: {why}")
    warn(
        f"   --keep: {instance} IS STILL UP, deliberately, and it is still billing. Nothing on"
        " this\n"
        "   box is watched by anything: a bake box runs no reaper (the recipe installs the\n"
        "   unit disabled and only the launch seam enables it), so its djb:expires tag is a\n"
        "   label the census reads and NOT a timer the machine enforces. It goes down when\n"
        "   you take it down.\n"
        "   A SHELL ON IT — the same transport ssh_to opens, printed so it can be copied:\n"
        f'     ssh -i {box.box_key(instance)} -o "ProxyCommand={box.proxy_command()}" -o'
        " StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
        f" {verifier_box_user()}@{instance}\n"
        "   then, on the box:\n"
        f"     cd {verifier_checkout_path()} && ./deploy/verifier/bake.sh --plan\n"
        "   which prints the whole recipe in order so you can walk the steps that are left.\n"
        "   One command at a time from here instead:\n"
        f"     scripts/verifier_box.sh run {instance} -- '<command>'\n"
        "   WHEN YOU ARE DONE:\n"
        f"     scripts/verifier_box.sh down {instance}\n"
        "     scripts/verifier_box.sh census"
    )


@contextmanager
def stdout_discarded() -> Iterator[None]:
    """This process's stdout, and every child's, sent to /dev/null for the block (`>/dev/null`)."""
    sys.stdout.flush()
    saved = os.dup(1)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
        os.close(null)


def indented(text: str, pad: str) -> None:
    """`sed 's/^/<pad>/' >&2` over `text`."""
    for line in text.splitlines():
        warn(f"{pad}{line}")


@dataclass
class Bake:
    """One bake's state: the box on the clock, the flag, the phases, the signals."""

    box: Box
    keep: bool
    phases: Phases = field(default_factory=Phases)
    signals: Signals = field(default_factory=Signals)
    instance: str = ""
    base: str = ""
    base_name: str = ""

    def resolve_base(self) -> None:
        """The base image, pinned or read once; its id, its dated name and the knob that pins it."""
        box = self.box
        pinned = box.cfg.env.get("DJB_VERIFIER_AL2023_AMI", "")
        if pinned:
            base = pinned
            vb_log(
                f"base       {base} (pinned by DJB_VERIFIER_AL2023_AMI; the SSM parameter was"
                " not read)"
            )
        else:
            done = spawn(
                box.aws(
                    "ssm",
                    "get-parameters",
                    "--names",
                    AL2023_PARAM,
                    "--query",
                    "Parameters[0].Value",
                    "--output",
                    "text",
                ),
                env=box.cfg.env,
                stdout=PIPE,
            )
            if done.returncode:
                raise Stopped(done.returncode)
            base = done.stdout.rstrip("\n")
            if base in ("", "None"):
                die(f"verifier_box: could not resolve the Amazon Linux image from {AL2023_PARAM}")
        row = image_name_and_state(box, base)
        name = row.split("\t", 1)[0]
        state = row.rsplit("\t", 1)[-1]
        if name in ("", "None", "null"):
            name = "<name unreadable>"
        vb_log(f"base       {base}  {name}  (state {state or 'unknown'})")
        vb_log(
            f"           pin this bake's base with DJB_VERIFIER_AL2023_AMI={base}"
            " to repeat it exactly"
        )
        self.base, self.base_name = base, name

    def launch(self, group: str) -> int:
        """The on-demand bake box, its key moved under its id; 0, or the launch's own status."""
        box = self.box
        cfg = box.cfg
        pending = cfg.home / f".pending-bake-{os.getpid()}"
        drop_tree(pending)
        pending.mkdir(parents=True)
        pending.chmod(0o700)
        keyfile = pending / "id_ed25519"
        keygen = ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"verifier-bake@{cfg.owner}"]
        rc = spawn([*keygen, "-f", str(keyfile)], env=cfg.env).returncode
        if rc:
            return rc
        keyfile.chmod(0o600)
        pubkey = Path(f"{keyfile}.pub").read_text().rstrip("\n")
        expires = iso_at(clock_s() + 2 * 3600)
        user_data = (
            BAKE_SEAM.read_text()
            .replace("${VERIFIER_PUBKEY}", pubkey)
            .replace("${VERIFIER_CHECKOUT}", verifier_checkout_path())
            .rstrip("\n")
        )
        vb_log("baking on-demand (a bake interrupted is an image half-written)")
        bake_type = cfg.env.get("DJB_VERIFIER_BAKE_TYPE") or "c7g.2xlarge"
        name = f"{cfg.namespace}-verifier-bake-{cfg.owner}"
        rc, out = run_instances_common(
            box, self.base, bake_type, group, user_data, "verifier-bake", expires, name, ""
        )
        if rc:
            return rc
        instance = out.split("\n")[0].split("\t")[0]
        if not instance or instance == "None":
            drop_tree(pending)
            die("verifier_box: run-instances returned no instance id for the bake box")
        home = box.box_dir(instance)
        home.mkdir(parents=True, exist_ok=True)
        home.chmod(0o700)
        shutil.move(keyfile, box.box_key(instance))
        shutil.move(f"{keyfile}.pub", f"{box.box_key(instance)}.pub")
        box.box_key(instance).chmod(0o600)
        (home / "rung").write_text("bake\n")
        drop_tree(pending)
        self.instance = instance
        return 0

    def keep_or_die(self, why: str, status: int) -> None:
        """Under `--keep`, hand the box over and stop with `status`; else refuse with `why`."""
        if self.keep:
            instance, self.instance = self.instance, ""
            bake_keep_hands_over(self.box, instance, why)
            raise Stopped(status)
        die(f"verifier_box: {why}")

    def terminate_and_die(self, why: str) -> None:
        """Take the box down here, naming the hand if that fails, then refuse with `why`."""
        terminate_or_by_hand(self.box, self.instance)
        self.instance = ""
        die(why)

    def on_the_clock(self) -> int:
        """Everything after the launch: online, bootstrap, push, recipe, image; the answer line."""
        box, instance, phases, signals = self.box, self.instance, self.phases, self.signals
        phases.begin("online")
        wait_for_ssm(box, instance, baking=True)
        signals.check()
        phases.begin("bootstrap")
        vb_log(f"waiting for the box's own bootstrap ({BAKE_READY_MARKER})")
        ready, waited = wait_for_bake_bootstrap(box, instance, signals)
        if not ready:
            self.terminate_and_die(
                f"verifier_box: {instance} never wrote {BAKE_READY_MARKER} in {waited}s (ceiling"
                f" {BOOTSTRAP_WAIT_SECONDS}s), so its\n"
                "   cloud-init did not finish: there is no git and no repository to push into.\n"
                "   The box was terminated so it cannot become a stale bill. Nothing was pushed\n"
                "   and nothing was captured."
            )
        phases.begin("push")
        vb_log("pushing this checkout's HEAD into the box's checkout (depth 1)")
        with stdout_discarded():
            prc = cmd_push(box, [instance])
        signals.check()
        if prc:
            warn(
                f"RED: verifier_box: the push to {instance} failed (git exit {prc}). Whichever of"
                " the two\n"
                "   readings above it is — this machine's pre-push hook refusing before a byte\n"
                "   left the laptop, or the tunnel dying while that hook measured — it happened\n"
                "   on THIS side: there is nothing on the box that explains it and nothing there\n"
                "   that can fix it. The box is going down; fix it here and bake again."
            )
            raise Stopped(1)
        phases.begin("recipe")
        _, image_sha = git(box.cfg.env, "-C", str(ROOT), "rev-parse", "HEAD", quiet=False)
        rc, out = box.ssh_within(
            RECIPE_SECONDS,
            instance,
            f"cd {verifier_checkout_path()} && ./deploy/verifier/bake.sh",
            stderr=STDOUT,
        )
        signals.check()
        say(out.rstrip("\n"))
        if rc != 0 or READY_LINE not in out:
            if self.keep:
                self.keep_or_die(f"the recipe did not finish (exit {rc}).", rc or 1)
            self.terminate_and_die(
                f"verifier_box: the recipe did not finish (exit {rc}); the bake box was"
                " terminated so it\n"
                "   cannot become a stale bill. Nothing was captured."
            )
        phases.begin("image")
        return self.capture(image_sha)

    def capture(self, image_sha: str) -> int:
        """`create-image` with its tags, untagged when the tags are refused; the box down after."""
        box, instance = self.box, self.instance
        cfg = box.cfg
        vb_log("capturing the image")
        baked = iso_at(clock_s())
        compact = baked.replace(":", "").replace("-", "")
        image_name = f"{cfg.namespace}-verifier-{image_sha[:8]}-{compact}"
        image_desc = (
            f"Verifier box image for {cfg.namespace}, main {image_sha[:8]}, base {self.base}"
            f" {self.base_name}"
        )
        ascii_only("image name", image_name)
        ascii_only("image description", image_desc)
        tags = (
            f"Tags=[{{Key=djb:role,Value=verifier-image}},{{Key=djb:namespace,Value={cfg.namespace}}},"
            f"{{Key=djb:main,Value={image_sha}}},{{Key=djb:baked,Value={baked}}},"
            f"{{Key=djb:base-ami,Value={self.base}}},{{Key=djb:base-ami-name,Value={self.base_name}}}]"
        )
        cap_err = cfg.home / f".capture-{os.getpid()}.err"
        cfg.home.mkdir(parents=True, exist_ok=True)
        create = ["ec2", "create-image", "--instance-id", instance, "--name", image_name]
        create += ["--description", image_desc]
        query = ["--query", "ImageId", "--output", "text"]
        specs = [
            "--tag-specifications",
            f"ResourceType=image,{tags}",
            f"ResourceType=snapshot,{tags}",
        ]
        cap_rc, new_image = self.create(cap_err, [*create, *specs, *query])
        untagged = ""
        failed = cap_rc != 0 or new_image in ("", "None")
        if failed and "CreateTags" in _read(cap_err):
            warn(
                "!! verifier_box: the capture's TAGS were refused — 'ec2:CreateTags' is not granted"
                " on the"
            )
            warn("   image and/or the snapshot this call creates. EC2's own words:")
            indented(_read(cap_err), "     ")
            warn(
                "   Retrying the capture UNTAGGED: the recipe finished and the image is worth more"
            )
            warn("   than its labels.")
            cap_rc, new_image = self.create(cap_err, [*create, *query])
            if cap_rc == 0 and new_image not in ("", "None"):
                untagged = new_image
        if cap_rc != 0 and new_image in ("", "None"):
            indented(_read(cap_err), "   ")
        cap_err.unlink(missing_ok=True)
        if new_image in ("", "None"):
            self.keep_or_die(f"create-image returned no image id for {instance}.", 2)
        self.signals.check()
        waited, state = 0, ""
        while waited < CAPTURE_WAIT_SECONDS:
            _, state = box.aws_quiet(
                "ec2",
                "describe-images",
                "--image-ids",
                new_image,
                "--query",
                "Images[0].State",
                "--output",
                "text",
            )
            if state == "available":
                break
            waited += ONLINE_POLL_SECONDS
            pause(ONLINE_POLL_SECONDS)
            self.signals.check()
        if state != "available":
            self.keep_or_die(f"{new_image} did not become available inside {waited}s.", 2)
        self.phases.end()
        self.phases.summary()
        rc = terminate_one(box, instance)
        if rc:
            raise Stopped(rc)
        self.instance = ""
        if untagged:
            print_untagged_capture(box, new_image)
            say(f"image {new_image} (main {image_sha[:8]}) — UNTAGGED: up --image-id {new_image}")
            return 1
        say(f"image {new_image} (main {image_sha[:8]}) — verifier_box.sh up will use it")
        return 0

    def create(self, errors: Path, args: list[str]) -> tuple[int, str]:
        """One `create-image`: its status and stdout, its stderr written to `errors`."""
        with errors.open("w") as sink:
            done = spawn(self.box.aws(*args), env=self.box.cfg.env, stdout=PIPE, stderr=sink)
        return done.returncode, done.stdout.rstrip("\n")


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


NO_LOCAL_MAIN = (
    "verifier_box: this checkout has NO local refs/heads/main. The image itself is named after\n"
    "   HEAD — the tree the push sends — but the ref is what the gate on the box\n"
    "   derives its --loop scope from, and that derivation REFUSES without it: a\n"
    "   box baked here is twenty minutes and a bill spent on an image whose gate\n"
    "   cannot run.\n"
    "   Nothing was launched and nothing was captured: the refusal is here rather\n"
    "   than there because there it costs a launch, a bootstrap and a push first.\n"
    "   The two legal moves:\n"
    "     1. create the ref at this clone's fork point:\n"
    "          git branch main HEAD\n"
    "        (./scripts/setup.sh does exactly this as its first step)\n"
    "     2. bake from a checkout of the family that HAS one — the primary, or any\n"
    "        linked worktree of it, whose refs live in the common git dir."
)


def cmd_bake(box: Box, args: Sequence[str]) -> int:
    """`bake [--keep] | bake --prune`: a private image of this checkout's HEAD, the box down."""
    words = list(args)
    if words[:1] == ["--prune"]:
        return bake_prune(box)
    keep = words[:1] == ["--keep"]
    if keep:
        words = words[1:]
    if words:
        die(f"verifier_box: unknown argument '{words[0]}' to bake")
    ascii_only("deployment namespace", box.cfg.namespace)
    if git(box.cfg.env, "-C", str(ROOT), "rev-parse", "--verify", "--quiet", "refs/heads/main")[0]:
        die(NO_LOCAL_MAIN)
    box.require_profile()
    box.require_plugin()
    bake = Bake(box, keep)
    try:
        bake.resolve_base()
    except Stopped as stopped:
        return stopped.status
    group = security_group(box)
    rc = bake.launch(group)
    if rc:
        return rc
    with bake.signals.armed():
        try:
            rc = bake.on_the_clock()
        except Stopped as stopped:
            rc = stopped.status
        except Refused as refused:
            if not refused.printed:
                warn(f"!! {refused}")
            rc = 2
        return bake_teardown(box, rc, bake.instance, bake.phases.summary)


COMMANDS: dict[str, Command] = {"bake": cmd_bake}
