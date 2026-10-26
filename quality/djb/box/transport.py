"""The box client's one boundary above the vendor CLIs: every child process it spawns."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, NoReturn

from quality.could_not_look import CouldNotLook

if TYPE_CHECKING:
    from quality.djb.box.core import Config

ROOT = Path(__file__).resolve().parents[3]
BAKE_SH = ROOT / "deploy" / "verifier" / "bake.sh"
SSM_SSH_DOCUMENT = "AWS-StartSSHSession"
Sink = int | IO[bytes] | IO[str] | None
PIPE = subprocess.PIPE
DEVNULL = subprocess.DEVNULL
STDOUT = subprocess.STDOUT
_USER = re.compile(r'BAKE_USER="\$\{DJB_VERIFIER_BAKE_USER:-(.*)\}"')
_CHECKOUT = re.compile(r'BAKE_CHECKOUT="\$\{DJB_VERIFIER_CHECKOUT:-(.*)\}"')


class Refused(CouldNotLook):
    """A `gate_die`: the sentence `main` prints after `!! ` on stderr, exit 2."""

    def __init__(self, message: str = "", *, printed: bool = False) -> None:
        super().__init__(message)
        self.printed = printed


def die(message: str) -> NoReturn:
    """Refuse with `message`; `main` prints it and exits 2."""
    raise Refused(message)


def say(text: str = "") -> None:
    """One line on stdout, flushed before any child writes to the same descriptor."""
    print(text, flush=True)


def warn(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def spawn(
    argv: Sequence[str],
    *,
    env: dict[str, str],
    stdout: Sink = None,
    stderr: Sink = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `argv` to its end as text; every child this client waits on is spawned here."""
    sys.stdout.flush()
    return subprocess.run(
        list(argv), env=env, stdout=stdout, stderr=stderr, cwd=cwd, text=True, check=False
    )


def capture(
    argv: Sequence[str],
    *,
    env: dict[str, str],
    stderr: Sink = DEVNULL,
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Run `argv` to its end: its status and its stdout less trailing newlines."""
    done = spawn(argv, env=env, stdout=PIPE, stderr=stderr, cwd=cwd)
    return done.returncode, done.stdout.rstrip("\n")


def kill_group(child: subprocess.Popen[bytes]) -> None:
    """Kill `child`'s process group and reap it."""
    try:
        os.killpg(child.pid, 9)
    except ProcessLookupError:
        pass
    child.wait()


def which(name: str, env: dict[str, str]) -> str | None:
    """`command -v name` under `env`'s PATH."""
    for directory in env.get("PATH", "").split(os.pathsep):
        candidate = Path(directory or ".") / name
        if candidate.is_file() and os.stat(candidate).st_mode & stat.S_IXUSR:
            return str(candidate)
    return None


def last_line(text: str) -> str:
    """The last line of `text` with carriage returns dropped (`tr -d '\\r' | tail -n 1`)."""
    lines = text.replace("\r", "").rstrip("\n").split("\n")
    return lines[-1] if lines else ""


def api_line(text: str) -> str:
    """The first line of `text` that is not blank."""
    for line in text.split("\n"):
        if line.strip():
            return line
    return ""


def none_empty(value: str) -> str:
    """`''` for the text output's spelling of an absent field (`None`, `null`)."""
    return "" if value in ("None", "null") else value


def bake_knob(pattern: str, what: str) -> str:
    """One default read out of `deploy/verifier/bake.sh`, the one place it is written."""
    if not os.access(BAKE_SH, os.R_OK):
        die(f"verifier_box: cannot read {BAKE_SH}")
    for line in BAKE_SH.read_text().splitlines():
        found = re.fullmatch(pattern, line)
        if found:
            return found.group(1)
    die(f"verifier_box: could not read {what} out of {BAKE_SH}")


def verifier_box_user() -> str:
    """The box's login user, as `bake.sh`'s `BAKE_USER` default names it."""
    return bake_knob(_USER.pattern, "BAKE_USER")


def verifier_checkout_path() -> str:
    """The box's checkout path, `bake.sh`'s `BAKE_CHECKOUT` default with its user filled in."""
    if not os.access(BAKE_SH, os.R_OK):
        die(
            f"verifier_box: cannot read {BAKE_SH}, and it is the ONE place the box's\n"
            "   checkout path is written down. Guessing it here is how the push target and the\n"
            "   recipe's expectation drift apart."
        )
    text = BAKE_SH.read_text().splitlines()
    user = next((m.group(1) for m in map(_USER.fullmatch, text) if m), "")
    path = next((m.group(1) for m in map(_CHECKOUT.fullmatch, text) if m), "")
    if not user or not path:
        die(
            "verifier_box: could not read the checkout knobs out of\n"
            f"   {BAKE_SH}. Its BAKE_USER/BAKE_CHECKOUT defaults are the contract this script\n"
            "   reads; if their shape changed, this is the line that must change with them."
        )
    return path.replace("${BAKE_USER}", user)


def measured_tree_here(rev: str, env: dict[str, str]) -> str:
    """This checkout's measured tree of `rev` (`gate_measured_tree_of`); '' when it cannot say."""
    done = spawn(
        [
            "bash",
            "-c",
            '. scripts/gate_ledger.sh >/dev/null 2>&1 && gate_measured_tree_of "$1"',
            "bash",
            rev,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
    )
    return done.stdout.rstrip("\n")


@dataclass
class Transport:
    """One configuration's AWS and SSH calls: the region and profile on every one."""

    cfg: Config

    # --- the AWS side ----------------------------------------------------------------

    def aws(self, *args: str) -> list[str]:
        """`aws --region <r> --profile <p> <args>`, the one argv every call carries."""
        return ["aws", "--region", self.cfg.region, "--profile", self.cfg.profile, *args]

    def aws_text(self, *args: str) -> str:
        """The call's stdout with its trailing newline gone, stderr discarded (`|| true`)."""
        done = spawn(
            self.aws(*args), env=self.cfg.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return done.stdout.rstrip("\n")

    def aws_both(self, *args: str) -> tuple[int, str]:
        """The call's status and its stdout and stderr as one text (`2>&1`)."""
        done = spawn(
            self.aws(*args), env=self.cfg.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return done.returncode, done.stdout.rstrip("\n")

    def aws_quiet(self, *args: str) -> tuple[int, str]:
        """The call's status and its stdout, stderr discarded (`2>/dev/null`)."""
        done = spawn(
            self.aws(*args), env=self.cfg.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        return done.returncode, done.stdout.rstrip("\n")

    def aws_ok(self, *args: str) -> bool:
        """Whether the call exited 0, its output discarded."""
        done = spawn(
            self.aws(*args), env=self.cfg.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return done.returncode == 0

    def aws_status(self, *args: str) -> int:
        """The call's status, stdout discarded and stderr passed through (`>/dev/null`)."""
        return spawn(self.aws(*args), env=self.cfg.env, stdout=subprocess.DEVNULL).returncode

    def instance_field(self, instance: str, query: str) -> str:
        """One `describe-instances` field of `instance`, text, '' on failure."""
        return self.aws_text(
            "ec2",
            "describe-instances",
            "--instance-ids",
            instance,
            "--query",
            query,
            "--output",
            "text",
        )

    def tag_of(self, instance: str, key: str) -> str:
        """The value of tag `key` on `instance`."""
        return self.instance_field(
            instance, f"Reservations[0].Instances[0].Tags[?Key=='{key}'].Value | [0]"
        )

    def spot_status_of(self, instance: str) -> str:
        """The Spot request's own status code and message, or why it could not be read."""
        try:
            sir = (self.box_dir(instance) / "spot-request").read_text().split("\n")[0]
        except OSError:
            sir = ""
        if sir in ("", "None", "null"):
            return "unrecorded (no spot request id was written for this box at launch)"
        rc, out = self.aws_both(
            "ec2",
            "describe-spot-instance-requests",
            "--spot-instance-request-ids",
            sir,
            "--query",
            "SpotInstanceRequests[0].Status.[Code,Message]",
            "--output",
            "text",
        )
        if rc != 0:
            if "UnauthorizedOperation" in out or "AccessDenied" in out:
                return (
                    "unreadable (ec2:DescribeSpotInstanceRequests not in the ops policy's"
                    " LIVE version)"
                )
            return f"unreadable ({api_line(out)})"
        out = out.split("\n")[0]
        code, tab, msg = out.partition("\t")
        if code in ("", "None", "null"):
            return f"unreadable (the API named no status code for {sir})"
        if not tab or msg in ("", "None", "null"):
            return code
        return f"{code}: {msg}"

    def refuse_if_reclaimed(self, instance: str) -> None:
        """Refuse, naming the state and its reason, unless the box is running or pending."""
        state = self.instance_field(instance, "Reservations[0].Instances[0].State.Name")
        if state in ("running", "pending", ""):
            return
        reason = self.instance_field(instance, "Reservations[0].Instances[0].StateReason.Code")
        if "SpotInstanceTermination" in reason:
            say(f"box reclaimed (spot) {instance} status {self.spot_status_of(instance)}")
            die(
                "verifier_box: the box was reclaimed by AWS mid-flight. Nothing on it is"
                " retrievable.\n"
                "   The verdict is LOST, never red: report 'stuck on: box reclaimed' and let the\n"
                "   PM bring another one up."
            )
        say(f"box gone ({state}) {instance}")
        die(
            f"verifier_box: the box is {state} ({reason or 'no reason given'})."
            " Nothing was attempted."
        )

    # --- the SSH side ----------------------------------------------------------------

    def box_dir(self, instance: str) -> Path:
        """This machine's directory for `instance`: its key, its rung, its pid files."""
        return self.cfg.home / instance

    def box_key(self, instance: str) -> Path:
        """The private half of `instance`'s key."""
        return self.box_dir(instance) / "id_ed25519"

    def box_rung(self, instance: str) -> str:
        """The rung `instance` was brought up for, or `unknown`."""
        try:
            return (self.box_dir(instance) / "rung").read_text().rstrip("\n")
        except OSError:
            return "unknown"

    def proxy_command(self) -> str:
        """The `ssm start-session` ProxyCommand every ssh, scp and push carries."""
        return (
            f"aws ssm start-session --target %h --document-name {SSM_SSH_DOCUMENT}"
            f" --parameters portNumber=%p --profile {self.cfg.profile} --region {self.cfg.region}"
        )

    def ssh_argv(self, instance: str, *command: str) -> list[str]:
        """The one ssh argv: key, the tunnel, no host-key pinning, the activity marker first."""
        # why-not pinning: Session Manager authenticates the instance; its key is new every launch
        key = self.box_key(instance)
        if not os.access(key, os.R_OK):
            die(
                f"verifier_box: no private key for {instance} under {self.cfg.home}. Either this"
                " box was\n"
                "   brought up by another machine, or 'down' has already removed it. Either way\n"
                "   there is no way in from here."
            )
        return [
            "ssh",
            "-i",
            str(key),
            "-o",
            f"ProxyCommand={self.proxy_command()}",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            f"{verifier_box_user()}@{instance}",
            "--",
            "touch /run/verifier/last-activity 2>/dev/null || true; " + " ".join(command),
        ]

    def scp_argv(self, instance: str, *paths: str) -> list[str]:
        """The one scp argv: key, the tunnel, no host-key pinning, then `paths`."""
        return [
            "scp",
            "-i",
            str(self.box_key(instance)),
            "-o",
            f"ProxyCommand={self.proxy_command()}",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            *paths,
        ]

    def ssh_to(self, instance: str, *command: str) -> int:
        """Run `command` on the box, streams passed through; the remote status, untouched."""
        return spawn(self.ssh_argv(instance, *command), env=self.cfg.env).returncode

    def ssh_capture(self, instance: str, *command: str) -> tuple[int, str]:
        """`ssh_to` with stdout captured and stderr discarded."""
        done = spawn(
            self.ssh_argv(instance, *command),
            env=self.cfg.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return done.returncode, done.stdout

    def ssh_within(
        self,
        seconds: int,
        instance: str,
        *command: str,
        stdin: Sink = None,
        stderr: Sink = DEVNULL,
    ) -> tuple[int, str]:
        """`ssh_to`, bounded by `seconds` of real time: `(124, '')` and its group killed."""
        argv = self.ssh_argv(instance, *command)
        with tempfile.TemporaryFile() as sink:
            child = subprocess.Popen(
                argv,
                stdin=stdin,
                stdout=sink,
                stderr=stderr,
                env=self.cfg.env,
                start_new_session=True,
            )
            try:
                rc = child.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                kill_group(child)
                return 124, ""
            sink.seek(0)
            return rc, sink.read().decode(errors="replace")

    def measured_tree_on_box(self, instance: str, checkout: str, rev: str) -> str:
        """The box's measured tree of `rev`, by its own `gate_ledger.sh`; '' when it cannot say."""
        _, out = self.ssh_capture(
            instance,
            f"cd {checkout} && bash -c '. scripts/gate_ledger.sh >/dev/null 2>&1 &&"
            f" gate_measured_tree_of {rev}'",
        )
        lines = [line for line in out.replace("\r", "").split("\n") if line.strip()]
        return lines[-1] if lines else ""
