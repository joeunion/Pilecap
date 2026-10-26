"""The box client's test world: the drive's stubbed AWS, SSH, SCP and git, one per test."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.tests.fixtures.fake_clock import ADVANCE_SH, FakeClock
from quality.tests.fixtures.stub_path import StubPath

ROOT = Path(__file__).resolve().parents[3]


# --- the world: one fake account, one fake machine, per test ----------------------------

AWS_SHIM = r"""#!/usr/bin/env bash
_n="$(cat "$REC/seq/_call" 2>/dev/null || echo 0)"
_n=$((_n + 1))
printf '%s\n' "$_n" >"$REC/seq/_call"
printf '%s ' "$@" >"$REC/calls/${_n}.flat"
for _a in "$@"; do printf '%s\n' "${_a//$'\n'/\\n}" >>"$REC/calls/${_n}.args"; done

_saw_region=""
_saw_profile=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --region)
        _saw_region="$2"
        shift 2
        ;;
    --profile)
        _saw_profile="$2"
        shift 2
        ;;
    *) break ;;
    esac
done
printf '%s %s\tregion=%s\tprofile=%s\n' "${1:-}" "${2:-}" "$_saw_region" "$_saw_profile" >>"$REC/aws.ops"

_key="${1:-}_${2:-}"
_q=""
for _a in "$@"; do
    if [ -n "${_take_next:-}" ]; then
        _q="$_a"
        _take_next=""
    fi
    [ "$_a" = "--query" ] && _take_next=1
done
_qslug="$(printf '%s' "$_q" | tr -cd 'A-Za-z0-9' | cut -c1-40)"
_qkey="${_key}__${_qslug}"

_seqfile="$REC/seq/$_qkey"
_i="$(cat "$_seqfile" 2>/dev/null || echo 0)"
_i=$((_i + 1))
printf '%s\n' "$_i" >"$_seqfile"

_pick() {
    local dir="$1" want base best f
    for want in "${_qkey}.${_i}" "${_qkey}" "${_key}.${_i}" "${_key}"; do
        if [ -f "$dir/$want" ]; then
            printf '%s\n' "$dir/$want"
            return 0
        fi
    done
    for want in "$_qkey" "$_key"; do
        best=""
        for f in "$dir"/*; do
            [ -f "$f" ] || continue
            base="${f##*/}"
            case "$base" in *.[0-9]) continue ;; esac
            case "$want" in
            "$base"*)
                if [ "${#base}" -gt "${#best}" ]; then best="$base"; fi
                ;;
            esac
        done
        if [ -n "$best" ]; then
            if [ -f "$dir/${best}.${_i}" ]; then
                printf '%s\n' "$dir/${best}.${_i}"
            else
                printf '%s\n' "$dir/$best"
            fi
            return 0
        fi
    done
    return 1
}

_out="$(_pick "$REC/ans" || true)"
_errf="$(_pick "$REC/err" || true)"
_rcf="$(_pick "$REC/rc" || true)"
[ -z "$_out" ] || cat "$_out"
[ -z "$_errf" ] || cat "$_errf" >&2
if [ -n "$_rcf" ]; then exit "$(cat "$_rcf")"; fi
exit 0
"""  # noqa: E501

SSH_SHIM = (
    "#!/usr/bin/env bash\n"
    + ADVANCE_SH
    + r"""[ -z "$DJB_FAKE_CLOCK" ] || _clock_advance "$DJB_FAKE_CLOCK" "${DRIVE_SSH_SECONDS:-5}" >/dev/null
_n="$(cat "$REC/seq/_ssh" 2>/dev/null || echo 0)"
_n=$((_n + 1))
printf '%s\n' "$_n" >"$REC/seq/_ssh"
printf '%s ' "$@" >"$REC/ssh/${_n}.flat"
if [ -f "$REC/ssh/${_n}.signal" ]; then
    kill -"$(cat "$REC/ssh/${_n}.signal")" "$PPID" 2>/dev/null || true
fi
for _a in "$@"; do printf '%s\n' "${_a//$'\n'/\\n}" >>"$REC/ssh/${_n}.args"; done
if [ -f "$REC/ssh/${_n}.hang" ]; then
    . "$REC/ssh/${_n}.hang"
    exec /bin/sleep 30
fi
if [ -f "$REC/ssh/${_n}.out" ]; then
    cat "$REC/ssh/${_n}.out"
elif [ -f "$REC/ssh/default.out" ]; then
    cat "$REC/ssh/default.out"
fi
if [ -f "$REC/ssh/${_n}.err" ]; then
    cat "$REC/ssh/${_n}.err" >&2
elif [ -f "$REC/ssh/default.err" ]; then
    cat "$REC/ssh/default.err" >&2
fi
if [ -f "$REC/ssh/${_n}.rc" ]; then exit "$(cat "$REC/ssh/${_n}.rc")"; fi
if [ -f "$REC/ssh/default.rc" ]; then exit "$(cat "$REC/ssh/default.rc")"; fi
exit 0
"""  # noqa: E501
)

SCP_SHIM = r"""#!/usr/bin/env bash
printf '%s ' "$@" >>"$REC/scp.flat"
printf '\n' >>"$REC/scp.flat"
for _a in "$@"; do printf '%s\n' "${_a//$'\n'/\\n}" >>"$REC/scp.args"; done
_prev=""
for _a in "$@"; do
    case "$_prev" in -i | -o) _prev="$_a"; continue ;; esac
    _prev="$_a"
    [ -f "$_a" ] || continue
    printf -- '--- %s\n' "$_a" >>"$REC/scp.payload"
    cat "$_a" >>"$REC/scp.payload"
done
exit 0
"""  # noqa: E501

GIT_SHIM = r"""#!/usr/bin/env bash
printf '%s ' "$@" >>"$REC/git.flat"
printf '\n' >>"$REC/git.flat"
printf 'GIT_SSH_COMMAND=%s\n' "${GIT_SSH_COMMAND:-<unset>}" >>"$REC/git.env"
printf '%s\t%s\n' "${DJB_PUSH_DESTINATION:-<unset>}" "$*" >>"$REC/git.dest"
for _a in "$@"; do
    if [ "$_a" = "push" ]; then
        case "$*" in
        *ssh://*)
            if [ -f "$REC/git.push.base.rc" ]; then
                case "$*" in
                *refs/djb/base*)
                    [ -f "$REC/git.push.base.err" ] && cat "$REC/git.push.base.err" >&2
                    exit "$(cat "$REC/git.push.base.rc")"
                    ;;
                esac
            fi
            if [ -f "$REC/git.push.rc" ]; then
                [ -f "$REC/git.push.err" ] && cat "$REC/git.push.err" >&2
                exit "$(cat "$REC/git.push.rc")"
            fi
            ;;
        *)
            if [ -f "$REC/git.vouch.out" ]; then
                cat "$REC/git.vouch.out"
            else
                echo "pre-push: wall box-exempt 2222222222222222222222222222222222222222"
            fi
            if [ -f "$REC/git.vouch.rc" ]; then
                [ -f "$REC/git.vouch.err" ] && cat "$REC/git.vouch.err" >&2
                exit "$(cat "$REC/git.vouch.rc")"
            fi
            ;;
        esac
    fi
    if [ "$_a" = "merge-base" ]; then
        case " $* " in
        *" --is-ancestor "*) exit "$(cat "$REC/git.ancestor.rc" 2>/dev/null || echo 0)" ;;
        esac
        cat "$REC/git.mergebase" 2>/dev/null || true
        exit 0
    fi
    if [ "$_a" = "rev-list" ]; then
        cat "$REC/git.revlist" 2>/dev/null || true
        exit 0
    fi
    if [ "$_a" = "write-tree" ]; then
        cat "$REC/git.writetree" 2>/dev/null || cat "$REC/git.revparse" 2>/dev/null || echo "0000000000000000000000000000000000000000"
        exit 0
    fi
    if [ "$_a" = "rev-parse" ]; then
        case " $* " in
        *refs/djb/base*)
            [ -f "$REC/git.djbbase" ] || exit 1
            cat "$REC/git.djbbase"
            exit 0
            ;;
        esac
        _nomain="$(cat "$REC/git.no-main" 2>/dev/null || true)"
        if [ -n "$_nomain" ]; then
            _repo=""
            _prev=""
            for _c in "$@"; do
                [ "$_prev" = "-C" ] && {
                    _repo="$_c"
                    break
                }
                _prev="$_c"
            done
            [ "$_repo" = "$_nomain" ] || _nomain=""
        fi
        if [ -n "$_nomain" ]; then
            case " $* " in
            *" refs/heads/main "* | *" main "*)
                case "$*" in
                *--quiet*) exit 1 ;;
                *)
                    echo "fatal: ambiguous argument 'main': unknown revision or path not in the working tree." >&2
                    exit 128
                    ;;
                esac
                ;;
            esac
        fi
        if [ -f "$REC/git.revparse.main" ]; then
            _mainfix="$(cat "$REC/git.revparse.main")"
            _mainrepo=""
            _prev=""
            for _c in "$@"; do
                [ "$_prev" = "-C" ] && {
                    _mainrepo="$_c"
                    break
                }
                _prev="$_c"
            done
            if [ "$_mainrepo" = "${_mainfix%%	*}" ]; then
                case " $* " in
                *" refs/heads/main "* | *" main "*)
                    printf '%s\n' "${_mainfix##*	}"
                    exit 0
                    ;;
                esac
            fi
        fi
        cat "$REC/git.revparse" 2>/dev/null || echo "0000000000000000000000000000000000000000"
        exit 0
    fi
done
exit 0
"""  # noqa: E501

PLUGIN_SHIM = "#!/usr/bin/env bash\nexit 0\n"
NS = "drivens"
RG = "xx-drive-9"
OWNER = "drive-session-1"
MAIN_SHA = "1" * 40
SUBJECT = (sys.executable, "-m", "quality.djb.box")
LISTING = "ec2_describe-instances__ReservationsInstancesInstanceId"
DOWN_LOOK = "ec2_describe-instances__Reservations0Instances0StateNameStateRea"


@dataclass
class World:
    """The drive's world: `rec/` the stubs answer from and record into, `home/`, `vhome/`."""

    root: Path
    stubs: StubPath
    clock: FakeClock
    rc: int = 0

    @property
    def rec(self) -> Path:
        return self.root / "rec"

    @property
    def vhome(self) -> Path:
        return self.root / "vhome"

    @property
    def home(self) -> Path:
        return self.root / "home"

    def ans(self, key: str, *lines: str) -> None:
        """The answer the `aws` stub prints for `key`, one line per argument."""
        (self.rec / "ans" / key).write_text("".join(f"{line}\n" for line in lines))

    def rcf(self, key: str, status: int) -> None:
        """The status the `aws` stub exits with for `key`."""
        (self.rec / "rc" / key).write_text(f"{status}\n")

    def errf(self, key: str, text: str) -> None:
        """What the `aws` stub prints on stderr for `key`."""
        (self.rec / "err" / key).write_text(f"{text}\n")

    def ssh(self, ordinal: int | str, suffix: str, text: str) -> None:
        """The `ssh` stub's answer for its Nth session (`out`, `err`, `rc`, `hang`, `signal`)."""
        (self.rec / "ssh" / f"{ordinal}.{suffix}").write_text(text)

    def env(self, **extra: str) -> dict[str, str]:
        """`env -i` with the drive's variables: the stub PATH first."""
        base = {
            "PATH": self.stubs.path,
            "HOME": str(self.home),
            "REC": str(self.rec),
            "USER": "driveuser",
            "DJB_DEPLOY_NAMESPACE": NS,
            "DJB_VERIFIER_REGION": RG,
            "DJB_VERIFIER_HOME": str(self.vhome),
            "DJB_VERIFIER_OWNER": OWNER,
            "DJB_FAKE_CLOCK": str(self.clock.file),
        }
        base.update(extra)
        return {key: value for key, value in base.items() if value is not None}

    def vb(self, *args: str, env: dict[str, str] | None = None) -> int:
        """Run the subject with `args`; stdout to `out`, stderr to `err`; the exit kept."""
        with (self.root / "out").open("wb") as out, (self.root / "err").open("wb") as err:
            done = subprocess.run(
                [*SUBJECT, *args],
                cwd=ROOT,
                env=env if env is not None else self.env(),
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
            )
        self.rc = done.returncode
        return self.rc

    @property
    def out(self) -> str:
        return (self.root / "out").read_text(errors="replace")

    @property
    def err(self) -> str:
        return (self.root / "err").read_text(errors="replace")

    def said(self, text: str) -> bool:
        """Whether `text` is on stdout or stderr."""
        return text in self.out or text in self.err

    def ops(self) -> list[str]:
        """`<service> <operation>` per `aws` call, in order."""
        path = self.rec / "aws.ops"
        return path.read_text().splitlines() if path.is_file() else []

    def op_count(self, prefix: str) -> int:
        """How many `aws` calls began with `prefix`."""
        return sum(1 for line in self.ops() if line.startswith(prefix))

    def calls(self) -> list[str]:
        """Every `aws` call's flat argv, in order."""
        found = sorted((self.rec / "calls").glob("*.flat"), key=lambda p: int(p.stem))
        return [path.read_text() for path in found]

    def nth_call_of(self, operation: str, n: int) -> str:
        """The flat argv of the Nth `aws` call naming `operation`, or ''."""
        word = re.compile(rf"(^| ){re.escape(operation)}( |$)")
        matching = [call for call in self.calls() if word.search(call)]
        return matching[n - 1] if len(matching) >= n else ""

    def ssh_flat(self, n: int) -> str:
        """The flat argv of the Nth ssh session, or ''."""
        path = self.rec / "ssh" / f"{n}.flat"
        return path.read_text() if path.is_file() else ""

    def report(self) -> str:
        """stdout, stderr and the aws ops, for an assertion's message."""
        return f"--- stdout ---\n{self.out}--- stderr ---\n{self.err}--- aws ops ---\n{self.ops()}"

    def profile_absent(self) -> None:
        """No `[profile <ns>-verifier]`, and `aws configure list` refusing."""
        (self.home / ".aws" / "config").write_text("[default]\nregion = us-west-2\n")
        self.rcf("configure_list", 1)
        self.errf("configure_list", "The config profile could not be found")

    def up_ready(self) -> None:
        """A world in which `up` would succeed, so a refusal case removes exactly one thing."""
        self.ans("ec2_describe-images__sortby", "ami-v1")
        self.ans("ec2_describe-security-groups", "sg-v")
        self.ans("ec2_describe-instances__ReservationsInstancesInstanceId", "")
        self.ans("service-quotas_get-service-quota", "32.0")
        self.ans("ec2_run-instances", f"i-up1\tsir-w1\t{RG}c\tspot")
        (self.rec / "ans" / "ssm_describe-instance-information.1").write_text("Pending\n")
        (self.rec / "ans" / "ssm_describe-instance-information.2").write_text("Online\n")
        self.ans("ec2_describe-instances__Reservations0Instances0Placement", f"{RG}c")
        self.ans("ec2_describe-instances__Reservations0Instances0InstanceLifecycle", f"spot\t{RG}c")
        self.ans("ec2_describe-spot-price-history", "0.2085", "None")
        self.ans("ec2_describe-instances__Reservations0Instances0StateName", "running")
        self.ssh("default", "out", f"{MAIN_SHA}\n")

    def tagged(self, role: str, namespace: str, state: str = "running") -> None:
        """The one four-column describe `terminate_one` reads: state, reason, role, namespace."""
        self.ans(DOWN_LOOK, f"{state}\tNone\t{role}\t{namespace}")

    def keyed_box(self, rung: str = "a-rung", instance: str = "i-up1") -> Path:
        """`instance` known to this machine: a key and the rung it was brought up for."""
        directory = self.vhome / instance
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "id_ed25519").write_text("key\n")
        (directory / "rung").write_text(f"{rung}\n")
        return directory


@pytest.fixture
def world(scratch: Path, stub_path: StubPath, fake_clock: FakeClock) -> World:
    """The drive's `world_new`: the stubs planted, the operator's config in the WRONG region."""
    here = World(scratch, stub_path, fake_clock)
    for sub in ("ans", "err", "rc", "seq", "calls", "ssh"):
        (here.rec / sub).mkdir(parents=True)
    (here.home / ".aws").mkdir(parents=True)
    here.vhome.mkdir()
    (here.home / ".aws" / "config").write_text(
        f"[default]\nregion = us-west-2\n\n[profile {NS}-verifier]\nregion = {RG}\n"
    )
    for name, body in (("aws", AWS_SHIM), ("ssh", SSH_SHIM), ("scp", SCP_SHIM), ("git", GIT_SHIM)):
        stub_path.plant(name, body)
    stub_path.plant("session-manager-plugin", PLUGIN_SHIM)
    here.ssh("default", "out", f"{MAIN_SHA}\n")
    (here.rec / "git.revparse").write_text(f"{MAIN_SHA}\n")
    return here
