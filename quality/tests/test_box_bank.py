"""`quality.djb.box.bank`: the 26 `bank_boxes_*` bodies, and the bank driven over them."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb.box import bank
from quality.djb.rituals import push_boxes

pytestmark = pytest.mark.drives("quality/djb/box/bank.py", "scripts/pm_push.sh")

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = "000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens"

# The swept push drive's `world_write_verifier_box` heredoc, comment lines dropped.
STUB_VB = r"""#!/usr/bin/env bash
set -uo pipefail
REC="__REC__"
REPO="__REPO__"
SUITELEG="__SUITELEG__"
printf '%s\n' "$*" >>"$REC/vb.calls"

label_of_rung() {
    local r="${1#bank-}"
    printf '%s\n' "${r#*-}"
}
unit_of_label() {
    local l="$1"
    if [[ $l =~ ^(.*)-[0-9]+of[0-9]+$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        printf '%s\n' "$l"
    fi
}

cmd="${1:-}"
shift || true
case "$cmd" in
up)
    rung=""
    az=""
    ttl=""
    idle=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --for)
            rung="${2:-}"
            shift 2
            ;;
        --az)
            az="${2:-}"
            shift 2
            ;;
        --ttl)
            ttl="${2:-}"
            shift 2
            ;;
        --idle)
            idle="${2:-}"
            shift 2
            ;;
        *) shift ;;
        esac
    done
    [ -n "$rung" ] || {
        echo "stub up: no --for" >&2
        exit 2
    }
    label="$(label_of_rung "$rung")"
    printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$rung" "${az:--}" "${ttl:--}" "${idle:--}" >>"$REC/up.calls"
    if [ -f "$REC/up.allow" ] && ! grep -qx "$label" "$REC/up.allow"; then
        i=0
        while [ ! -f "$REC/release" ] && [ "$i" -lt 300 ]; do
            sleep 0.2
            i=$((i + 1))
        done
        echo "stub up: ${label} released without launching" >&2
        exit 2
    fi
    upn="$(cat "$REC/up.n.${label}" 2>/dev/null || echo 0)"
    upn=$((upn + 1))
    printf '%s\n' "$upn" >"$REC/up.n.${label}"
    if [ -f "$REC/up.rc.${label}.${upn}" ]; then
        echo "stub up: ${label} attempt ${upn} refused by fixture" >&2
        exit "$(cat "$REC/up.rc.${label}.${upn}")"
    fi
    if [ -f "$REC/up.rc.${label}" ]; then
        echo "stub up: ${label} refused by fixture" >&2
        exit "$(cat "$REC/up.rc.${label}")"
    fi
    id="i-$(printf '%s' "$label" | cksum | awk '{printf "%010d", $1}')"
    [ "$upn" = "1" ] || id="${id}-r${upn}"
    printf '%s\n' "$label" >"$REC/label-of.${id}"
    echo "launched   ${id}   az ${az:-xx-drive-9a}"
    if [ -f "$REC/up.launched_then_rc.${label}" ]; then
        echo "stub up: ${label} launched and then failed by fixture" >&2
        exit "$(cat "$REC/up.launched_then_rc.${label}")"
    fi
    echo "instance   ${id}   c7g.4xlarge   market: spot   az ${az:-xx-drive-9a}"
    echo "market     $(cat "$REC/up.market.${label}" 2>/dev/null || echo spot)"
    echo "owner      drive        for: ${rung}   idle: 45m"
    echo "tree       the box agrees with this checkout"
    printf '%s\n' "$label" >>"$REC/up.done"
    exit 0
    ;;
leg)
    id="${1:-}"
    shift || true
    printf '%s\t%s\n' "$id" "$*" >>"$REC/leg.calls"
    plbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    case " $* " in
    *" --passes 1 "*) printf '1\n' >"$REC/leg.passes.${plbl}" ;;
    esac
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    n="$(cat "$REC/leg.n.${lbl}" 2>/dev/null || echo 0)"
    n=$((n + 1))
    printf '%s\n' "$n" >"$REC/leg.n.${lbl}"
    if [ -f "$REC/leg.rc.${lbl}.${n}" ]; then exit "$(cat "$REC/leg.rc.${lbl}.${n}")"; fi
    if [ -f "$REC/leg.rc.${lbl}" ]; then exit "$(cat "$REC/leg.rc.${lbl}")"; fi
    exit "$(cat "$REC/leg.rc" 2>/dev/null || echo 0)"
    ;;
run)
    id="${1:-}"
    shift || true
    printf '%s\t%s\n' "$id" "$*" >>"$REC/run.calls"
    case "$*" in
    *"fe_leg_frozen_lockfile"*)
        flbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
        printf '%s\t%s\n' "$id" "$flbl" >>"$REC/fe.calls"
        fn="$(cat "$REC/fe.n.${flbl}" 2>/dev/null || echo 0)"
        fn=$((fn + 1))
        printf '%s\n' "$fn" >"$REC/fe.n.${flbl}"
        if [ -f "$REC/fe.rc.${flbl}.${fn}" ]; then exit "$(cat "$REC/fe.rc.${flbl}.${fn}")"; fi
        exit 0
        ;;
    esac
    case "$*" in
    *"provision.sh image-tag"*)
        printf '%s\t%s\n' "$id" "$*" >>"$REC/image.calls"
        cat "${DJB_GATE_LEDGER:-/dev/null}" >"$REC/ledger.at.image" 2>/dev/null || true
        if [ -f "$REC/image.out" ]; then
            cat "$REC/image.out"
        elif [ -s "$REC/box.dirty" ]; then
            echo "!! image: refusing to build under 'tree-00000000000a-dirty' — this bank keys on a tree tag"
            echo "   the tree moved under it: $(cat "$REC/box.dirty")"
            exit 3
        else
            echo "Login Succeeded"
            echo "image: seconds web 39 worker 41"
            echo "image: digest web sha256:0aa1"
            echo "image: digest worker sha256:0bb2"
            echo "image: platform linux/arm64"
        fi
        exit "$(cat "$REC/image.rc" 2>/dev/null || echo 0)"
        ;;
    esac
    accept_out="$(printf '%s\n' "$*" | sed -n 's/.*--out \([^ ;]*\).*/\1/p')"
    case "$accept_out" in
    '') ;;
    /* | '$HOME'/* | '${HOME}'/*) ;;
    *) printf '%s\n' "$accept_out" >"$REC/box.dirty" ;;
    esac
    exit "$(cat "$REC/accept.rc" 2>/dev/null || echo 0)"
    ;;
zones)
    if [ -f "$REC/zones.rc" ]; then
        echo "stub zones: could not look by fixture" >&2
        exit "$(cat "$REC/zones.rc")"
    fi
    [ ! -f "$REC/zones.noise" ] || echo "verifier_box: warning — DJB_VERIFIER_PRICING_REGION is unset" >&2
    if [ -f "$REC/zones" ]; then
        cat "$REC/zones"
    else
        printf '%s\n' xx-drive-9a xx-drive-9b xx-drive-9c
    fi
    exit 0
    ;;
wait)
    id="${1:-}"
    name="${2:-}"
    printf '%s\t%s\n' "$id" "$name" >>"$REC/wait.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    wn="$(cat "$REC/wait.n.${lbl}" 2>/dev/null || echo 0)"
    wn=$((wn + 1))
    printf '%s\n' "$wn" >"$REC/wait.n.${lbl}"
    if [ -f "$REC/wait.block.${lbl}" ]; then
        i=0
        while [ ! -f "$REC/release-wait" ] && [ "$i" -lt 300 ]; do
            sleep 0.2
            i=$((i + 1))
        done
    fi
    if [ -f "$REC/wait.out.${lbl}.${wn}" ]; then
        cat "$REC/wait.out.${lbl}.${wn}"
    elif [ -f "$REC/wait.out.${lbl}" ]; then
        cat "$REC/wait.out.${lbl}"
    fi
    if [ -f "$REC/box.rc.${lbl}.${wn}" ]; then exit "$(cat "$REC/box.rc.${lbl}.${wn}")"; fi
    exit "$(cat "$REC/box.rc.${lbl}" 2>/dev/null || echo 0)"
    ;;
fetch)
    id="${1:-}"
    remote="${2:-}"
    dest="${3:-}"
    printf '%s\t%s\t%s\n' "$id" "$remote" "$dest" >>"$REC/fetch.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    case "$remote" in
    *proof.txt)
        pn="$(cat "$REC/accept.proof.n" 2>/dev/null || echo 0)"
        pn=$((pn + 1))
        printf '%s\n' "$pn" >"$REC/accept.proof.n"
        if [ -f "$REC/accept.proof.reclaimed" ] && [ "$pn" = "1" ]; then
            echo "box reclaimed (spot) ${id} status instance-terminated-no-capacity: not enough capacity" >&2
            echo "!! verifier_box: the box was reclaimed by AWS mid-flight." >&2
            exit 2
        fi
        if [ -f "$REC/accept.proof.absent" ]; then
            echo "stub fetch: nothing at ${remote} on ${id}" >&2
            exit 1
        fi
        if [ -f "$REC/accept.proof" ]; then
            cat "$REC/accept.proof" >"$dest"
        else
            printf 'seed=%s workers=16 pass1=0 pass2=0 map=0\n' 1073741827 >"$dest"
        fi
        exit 0
        ;;
    *pass1.log | *pass2.log)
        pl="${remote##*/}"
        pl="${pl%.log}"
        if [ -f "$REC/accept.${pl}.absent" ]; then
            echo "stub fetch: nothing at ${remote} on ${id}" >&2
            exit 1
        fi
        if [ -f "$REC/accept.${pl}" ]; then
            cat "$REC/accept.${pl}" >"$dest"
        else
            printf '%s\n' "Using --randomly-seed=1073741827" \
                "== 2481 passed in 512.01s ==" >"$dest"
        fi
        exit 0
        ;;
    *test_impact.json)
        if [ -f "$REC/accept.map.absent" ]; then
            echo "stub fetch: nothing at ${remote} on ${id}" >&2
            exit 1
        fi
        if [ -f "$REC/accept.map" ]; then
            cat "$REC/accept.map" >"$dest"
        else
            printf '%s\n' '{"generated": {"at": "2026-09-18T00:00:00+00:00", "pytest": 4, "tree": "tree:beefcafe1234"}, "tests": {"apps/x/tests/test_a.py::test_one": ["apps/x/services.py"]}, "unmapped": {}}' >"$dest"
        fi
        exit 0
        ;;
    esac
    if [ -f "$REC/absent.${lbl}" ]; then
        echo "stub fetch: nothing at ${remote} on ${id}" >&2
        exit 1
    fi
    case "$remote" in
    *.rc)
        if [ -f "$REC/norc.${lbl}" ]; then
            echo "stub fetch: no exit status on ${id}" >&2
            exit 1
        fi
        wn="$(cat "$REC/wait.n.${lbl}" 2>/dev/null || echo 1)"
        if [ -f "$REC/box.rc.${lbl}.${wn}" ]; then
            cat "$REC/box.rc.${lbl}.${wn}" >"$dest"
        elif [ -f "$REC/box.rc.${lbl}" ]; then
            cat "$REC/box.rc.${lbl}" >"$dest"
        else
            printf '0\n' >"$dest"
        fi
        exit 0
        ;;
    *.log)
        unit="$(unit_of_label "$lbl")"
        if [ -f "$REC/box.tree.${lbl}" ]; then
            tree="$(cat "$REC/box.tree.${lbl}")"
        else
            tree="$(cd "$REPO" && . scripts/gate_ledger.sh && gate_measured_tree)"
        fi
        onepass=""
        [ ! -f "$REC/leg.passes.${lbl}" ] || onepass=1
        if [ -f "$REC/box.legs.${lbl}" ]; then
            legs="$(cat "$REC/box.legs.${lbl}")"
        else
            legs="$(awk -F'\t' -v u="$unit" '$1 == u { print $4 }' "$REC/listlegs.out")"
            if [ -n "$onepass" ]; then
                legs=",${legs},"
                legs="${legs/,${SUITELEG},/,${SUITELEG}/1,}"
                legs="${legs#,}"
                legs="${legs%,}"
            fi
        fi
        wall="$(cat "$REC/box.wall.${lbl}" 2>/dev/null || echo 42)"
        {
            echo "- --leg ${unit}${onepass:+ --passes 1}"
            echo "  needs:       db (a DECLARATION — the gate refuses at the leg, never here)"
            echo "  shards:      N-capable"
            echo "  composed-of: ${legs}"
            echo "  This run takes NO machine lease, NO checkout lock and records NO verdict:"
            echo "  one unit of the gate vouches for no tree."
            echo "ok: all checks passed (${wall}s)"
            echo "  ...of ONE UNIT: ${unit}."
            echo "  no verdict recorded — --leg ${unit}: one unit of the gate"
            echo "  is a targeted drive and vouches for no tree. The tree it ran on was ${tree}."
        } >"$dest"
        [ ! -f "$REC/box.faillog.${lbl}" ] || cat "$REC/box.faillog.${lbl}" >>"$dest"
        exit 0
        ;;
    esac
    echo "stub fetch: no fixture for ${remote}" >&2
    exit 2
    ;;
harvest-drives)
    id="${1:-}"
    htree="${2:-}"
    printf '%s\t%s\n' "$id" "$htree" >>"$REC/harvest.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    if [ -f "$REC/harvest.rc.${lbl}" ]; then
        echo "box reclaimed (spot) ${id} status instance-terminated-no-capacity: not enough capacity" >&2
        echo "!! verifier_box: the box was reclaimed by AWS mid-flight." >&2
        exit "$(cat "$REC/harvest.rc.${lbl}")"
    fi
    hn=0
    halready=0
    if [ -f "$REC/boxledger.${lbl}" ]; then
        while IFS= read -r hline; do
            case "$hline" in
            *" drive "*"tree=${htree}"*) ;;
            *) continue ;;
            esac
            if grep -qxF -- "$hline" "${DJB_GATE_LEDGER}" 2>/dev/null; then
                halready=$((halready + 1))
                continue
            fi
            printf '%s\n' "$hline" >>"${DJB_GATE_LEDGER}"
            hn=$((hn + 1))
        done <"$REC/boxledger.${lbl}"
    fi
    echo "verifier_box: drive rows: ${hn} brought home at tree=${htree} (${halready} already here) from ${id}"
    exit 0
    ;;
down)
    id="${1:-}"
    printf '%s\n' "$id" >>"$REC/down.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    if [ -f "$REC/down.fail" ] || [ -f "$REC/down.fail.${lbl}" ]; then
        echo "stub down: terminate-instances refused for ${id}" >&2
        exit 1
    fi
    echo "terminated ${id}"
    exit 0
    ;;
esac
echo "stub verifier_box: unknown command '${cmd}'" >&2
exit 2
"""  # noqa: E501

STUB_PROVISION = r"""#!/usr/bin/env bash
REC="__REC__"
printf '%s\n' "$*" >>"$REC/provision.calls"
case "${1:-}" in
image-ref)
    reg="$(cat "$REC/registry" 2>/dev/null || true)"
    if [ -z "$reg" ]; then
        echo "!! provision: DJB_IMAGE_REGISTRY is empty." >&2
        exit 2
    fi
    printf '%s/djb-%s:%s\n' "$reg" "${2:-}" "${3:-}"
    exit 0
    ;;
esac
echo "stub provision: no fixture for '$*'" >&2
exit 2
"""

BAKE = (
    "#!/usr/bin/env bash\n"
    'BAKE_USER="${DJB_VERIFIER_BAKE_USER:-verifier}"\n'
    'BAKE_CHECKOUT="${DJB_VERIFIER_CHECKOUT:-/home/${BAKE_USER}/src}"\n'
)


def sh(*argv: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    """Run `argv` with its output to files (the gate refuses a pipe), refusing a non-zero exit."""
    done = run_to_files(list(argv), cwd=cwd, env=env)
    assert done.returncode == 0, f"{argv}: {done.stderr}"
    return done.stdout


def run_to_files(
    argv: list[str], *, cwd: Path, env: dict[str, str] | None
) -> subprocess.CompletedProcess[str]:
    """Run `argv` with stdin from /dev/null and stdout and stderr to files: its status and both."""
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        done = subprocess.run(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, check=False
        )
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(argv, done.returncode, out.read(), err.read())


def count_lines(path: Path) -> int:
    """`grep -c .`: the non-blank lines of `path`, 0 when absent."""
    try:
        return sum(1 for line in path.read_text().split("\n") if line)
    except OSError:
        return 0


# --- the listing and the plan this tree declares ------------------------------------------


@dataclass(frozen=True)
class Plan:
    """The drive's S.0: this tree's listing, its leg set, and the plan's boxes and victim."""

    listing: str
    full_legs: str
    suite_leg: str
    boxes: int
    victim: str


@pytest.fixture(scope="module")
def plan(tmp_path_factory: pytest.TempPathFactory) -> Plan:
    """The real `./scripts/check.sh --list-legs`, and a probe bank's labels for the victim."""
    listing = sh("./scripts/check.sh", "--list-legs")
    full_legs = sh(
        "bash", "-c", ". scripts/gate_refuse.sh; . scripts/gate_ledger.sh; gate_full_legs"
    )
    suite = push_boxes.SUITE_LEG
    rows = [line.split("\t") for line in listing.split("\n") if line.split("\t")[0]]
    capable = [r[0] for r in rows if len(r) > 2 and r[2] == "N-capable"]
    assert capable, "this tree's listing has no N-capable unit"
    boxes = len(rows) + 3
    probe = World.make(tmp_path_factory.mktemp("probe"), listing, full_legs.strip(), suite)
    assert probe.bank(boxes).returncode == 0, probe.out
    labels = [line.split("\t")[0] for line in probe.rec_lines("up.calls")]
    last = capable[-1]
    k = sum(1 for label in labels if re.fullmatch(rf"{re.escape(last)}-[0-9]+of[0-9]+", label))
    return Plan(listing, full_legs.strip(), suite, boxes, f"{last}-{k}of{k}")


# --- the drive's world, in Python -----------------------------------------------------------


@dataclass
class World:
    """`fresh_world`: a scratch repository with the wrapped `pm_push.sh` and the stubs around it."""

    root: Path
    out: str = ""

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def rec(self) -> Path:
        return self.root / "rec"

    @property
    def ledger(self) -> Path:
        return self.root / "verdicts"

    @classmethod
    def make(cls, root: Path, listing: str, full_legs: str, suite_leg: str) -> World:
        """The world `fresh_world` builds, from the same files."""
        world = cls(root)
        repo, rec = world.repo, world.rec
        for d in (repo / "scripts" / "githooks", rec, root / "tmp", root / "lease"):
            d.mkdir(parents=True)
        world.ledger.write_text("")
        git = ("git", "-C", str(repo))
        sh("git", "init", "-q", str(repo))
        sh(*git, "symbolic-ref", "HEAD", "refs/heads/main")
        sh(*git, "config", "user.email", "drive@example.invalid")
        sh(*git, "config", "user.name", "pm_push drive")
        for name in (
            "pm_push.sh",
            "bash_only.sh",
            "gate_ledger.sh",
            "gate_refuse.sh",
            "fe_gate.sh",
        ):
            (repo / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        hook = repo / "scripts" / "githooks" / "pre-push"
        hook.write_bytes((ROOT / "scripts" / "githooks" / "pre-push").read_bytes())
        for path in (repo / "scripts" / "pm_push.sh", hook):
            path.chmod(0o755)
        (rec / "listlegs.out").write_text(listing)
        (repo / "deploy" / "verifier").mkdir(parents=True)
        world.executable(repo / "deploy" / "verifier" / "bake.sh", BAKE)
        (rec / "registry").write_text(f"{REGISTRY}\n")
        world.executable(
            repo / "deploy" / "provision.sh", STUB_PROVISION.replace("__REC__", str(rec))
        )
        (repo / "scripts" / "test_impact.json").write_text(
            '{"generated": {"at": "-", "pytest": 0, "tree": "-"}, "tests": {}, "unmapped": {}}\n'
        )
        world.executable(
            repo / "scripts" / "check.sh",
            "#!/usr/bin/env bash\n"
            f"FULL_LEGS={full_legs}\n"
            f'printf \'%s\\n\' "$*" >>"{rec}/gate.calls"\n'
            'if [ "${1:-}" = "--list-legs" ]; then\n'
            f'    if [ -f "{rec}/listlegs.err" ]; then cat "{rec}/listlegs.err" >&2; fi\n'
            f'    if [ -f "{rec}/listlegs.rc" ]; then exit "$(cat "{rec}/listlegs.rc")"; fi\n'
            f'    cat "{rec}/listlegs.out"\n'
            "    exit 0\n"
            "fi\n"
            'echo "STUB GATE ran with: $*"\n'
            'exit "${DJB_DRIVE_GATE_RC:-0}"\n',
        )
        world.executable(
            repo / "scripts" / "pm_fold.sh",
            "#!/usr/bin/env bash\n"
            f"printf 'ran\\n' >>\"{rec}/fold.calls\"\n"
            'echo "STUB FOLD ran"\n'
            'echo "pm_fold: NOTHING TO FOLD. No commit was made."\n'
            "exit 0\n",
        )
        stub = STUB_VB.replace("__REC__", str(rec)).replace("__REPO__", str(repo))
        world.executable(
            repo / "scripts" / "verifier_box.sh", stub.replace("__SUITELEG__", suite_leg)
        )
        # THE PACKAGE AND THE INTERPRETER the `pm_push.sh` shim execs.
        for package in ("quality", "apps", ".venv"):
            (repo / package).symlink_to(ROOT / package)
        (repo / ".git" / "info" / "exclude").write_text("/quality\n/apps\n/.venv\n__pycache__/\n")
        (repo / "shared.txt").write_text("one\n")
        sh(*git, "add", "-A")
        sh(*git, "commit", "-q", "-m", "base")
        sh(*git, "worktree", "add", "-q", "--detach", str(root / "pm-push"))
        sh("git", "init", "-q", "--bare", str(root / "origin"))
        sh(*git, "remote", "add", "origin", str(root / "origin"))
        return world

    @staticmethod
    def executable(path: Path, text: str) -> None:
        """Write `text` to `path`, mode 0755."""
        path.write_text(text)
        path.chmod(0o755)

    def tree(self) -> str:
        """The scratch repository's committed tree."""
        return sh("git", "-C", str(self.repo), "rev-parse", "HEAD^{tree}").strip()

    def bank(self, boxes: int) -> subprocess.CompletedProcess[str]:
        """`run_bank --bank --no-fold --on-boxes <boxes>` through the drive's runner."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DJB_GATE_", "GIT_"))}
        env.update(
            DJB_GATE_LEDGER=str(self.ledger),
            TMPDIR=str(self.root / "tmp"),
            DJB_GATE_LEASE_DIR=str(self.root / "lease"),
            DJB_BANK_CHECKOUT=str(ROOT),
        )
        argv = ["./scripts/pm_push.sh", "--bank", "--no-fold", "--on-boxes", str(boxes)]
        done = run_to_files(argv, cwd=self.repo, env=env)
        self.out = done.stdout + done.stderr
        return done

    def rec_lines(self, name: str) -> list[str]:
        """The recorded lines of `rec/<name>`, or none."""
        path = self.rec / name
        return [line for line in path.read_text().split("\n") if line] if path.exists() else []

    def boxledger_rows(self, label: str, tree: str) -> None:
        """Two drive rows the box `label` banked at `tree`."""
        (self.rec / f"boxledger.{label}").write_text(
            f"v1 drive-v1:aaaa{label} drive 2026-09-18T00:00:00Z selftest exit=0 took=3 tree={tree}"
            " parts=scripts/tests/test_a.sh\n"
            f"v1 drive-v1:bbbb{label} drive 2026-09-18T00:00:01Z sweep exit=0 took=4 tree={tree}"
            " parts=scripts/tests/test_b.sh\n"
        )

    def ledger_drive_rows(self) -> int:
        """`grep -c ' drive '` over the ledger."""
        return sum(1 for line in self.ledger.read_text().split("\n") if " drive " in line)

    def assert_mac_measured_nothing(self) -> None:
        """No bare gate on this Mac, no lease, no slot."""
        other = [c for c in self.rec_lines("gate.calls") if "--list-legs" not in c]
        assert other == [], f"the Mac's own gate was invoked: {other}"
        assert not (self.root / "lease" / "djb-gate-lease").exists()
        assert not (self.root / "lease" / "djb-gate-slots").exists()


@pytest.fixture
def world(tmp_path: Path, plan: Plan) -> Iterator[World]:
    """A fresh world over this tree's listing."""
    yield World.make(tmp_path, plan.listing, plan.full_legs, plan.suite_leg)


# --- the 26 names, importable ------------------------------------------------------------------


def test_the_bank_bodies_import_under_their_shell_names() -> None:
    names = sorted(bank.BODIES)
    assert len(names) == 26, names
    assert all(name.startswith("bank_boxes_") for name in names), names
    for name in names:
        assert callable(getattr(bank, name)), name


# deleted: test_every_bank_body_in_pm_push_is_one_line_calling_its_own_name — no wrapper lines
# pin: test_the_bank_bodies_import_under_their_shell_names


def test_an_unknown_body_is_refused_by_name() -> None:
    done = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-c",
            "from quality.djb.box.bank import main; raise SystemExit(main())",
            "nope",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
    assert "'nope' is not one of the bank's bodies" in done.stderr


# --- the lines the box executes, byte for byte --------------------------------------------------


def test_the_acceptance_line_is_the_shells_byte_for_byte() -> None:
    assert bank.acceptance_remote_line("/home/verifier/src", "bank-1234abcd-acceptance", "16") == (
        "mkdir -p $HOME/verify/bank-1234abcd-acceptance; cd /home/verifier/src; "
        "./scripts/pm_push.sh --proof --where acceptance --workers 16 --out "
        '$HOME/verify/bank-1234abcd-acceptance; r=$?; [ "${r}" != 1 ] || r=0; exit ${r}'
    )


def test_the_frontend_line_is_the_shells_byte_for_byte() -> None:
    assert bank.frontend_remote_line("/home/verifier/src", "frontend") == (
        "cd /home/verifier/src && bash -c "
        "'. ./scripts/fe_gate.sh && fe_leg_frozen_lockfile frontend'"
    )


def test_the_image_line_is_the_shells_byte_for_byte() -> None:
    host = "000000000000.dkr.ecr.us-east-1.amazonaws.com"
    got = bank.image_remote_line(
        "/home/verifier/src",
        "tree-abc",
        REGISTRY,
        "us-east-1",
        "R/djb-web:tree-abc",
        "R/djb-worker:tree-abc",
    )
    assert got == (
        f"set -e; cd /home/verifier/src; export DJB_IMAGE_REGISTRY={REGISTRY}; "
        't=$(./deploy/provision.sh image-tag); if [ "$t" != "tree-abc" ]; then echo "!! image: '
        "refusing to build under '$t' — this bank keys on tree-abc\"; echo '   what moved under it "
        "(git status --short, first 10):'; git status --short | sed -n '1,10p'; exit 3; fi; "
        "p=$(aws ecr get-login-password --region us-east-1); printf '%s' \"$p\" | docker login "
        f"--username AWS --password-stdin {host}; T0=$(date +%s); docker build --target web "
        "--tag R/djb-web:tree-abc .; docker push R/djb-web:tree-abc; T1=$(date +%s); docker build "
        "--target worker --tag R/djb-worker:tree-abc .; docker push R/djb-worker:tree-abc; "
        'T2=$(date +%s); echo "image: seconds web $((T1-T0)) worker $((T2-T1))"; echo "image: '
        'digest web $(./deploy/provision.sh image-digest web tree-abc)"; echo "image: digest '
        'worker $(./deploy/provision.sh image-digest worker tree-abc)"; echo "image: platform '
        "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' R/djb-web:tree-abc)\"; "
        f"docker logout {host} || true"
    )


# --- the plan, against the shell's own arithmetic -----------------------------------------------

LISTING = (
    "static\tdb\t0\truff,mypy\n"
    "supply-chain\tnetwork\t0\tsupply-chain\n"
    "pytest-x2\tdb\tN-capable\tpytest-x2\n"
    "selftest\tdb\tN-capable\tselftest\n"
    "full-house-rules\tnone\t0\tfull-house-rules\n"
)
INDIV = (
    "static\tstatic\ta\t\t\nsupply-chain\tsupply-chain\tb\t\t\n"
    "full-house-rules\tfull-house-rules\tc\t\t\n"
)


@pytest.mark.parametrize(
    ("boxes", "rows"),
    [
        (5, "pytest-x2-1of1\tpytest-x2\ta\t1/1\t1\nselftest-1of1\tselftest\tb\t1/1\t\n"),
        (
            6,
            "pytest-x2-1of1\tpytest-x2\ta\t1/1\t1\nselftest-1of2\tselftest\tb\t1/2\t\n"
            "selftest-2of2\tselftest\tc\t2/2\t\n",
        ),
        (
            8,
            "pytest-x2-1of2\tpytest-x2\ta\t1/2\t1\npytest-x2-2of2\tpytest-x2\tb\t2/2\t1\n"
            "selftest-1of3\tselftest\tc\t1/3\t\nselftest-2of3\tselftest\ta\t2/3\t\n"
            "selftest-3of3\tselftest\tb\t3/3\t\n",
        ),
    ],
)
def test_the_plan_is_the_shells_at_every_n(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], boxes: int, rows: str
) -> None:
    listing = tmp_path / "listing.tsv"
    listing.write_text(LISTING)
    assert bank.bank_boxes_plan(str(listing), boxes, "1", "a b c", suite_leg="pytest-x2") == 0
    assert capsys.readouterr().out == INDIV + rows


def test_a_plan_below_the_floor_is_exit_2_naming_the_units(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = tmp_path / "listing.tsv"
    listing.write_text(LISTING)
    assert bank.bank_boxes_plan(str(listing), 4, "1", "a b c", suite_leg="pytest-x2") == 2
    err = capsys.readouterr().err
    assert "!! pm_push --bank --on-boxes 4: this gate declares 5 units (3 indivisible," in err
    assert "   Nothing was launched." in err


def test_the_first_failing_line_names_the_node_and_the_replay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "log"
    log.write_text(
        "collecting\nUsing --randomly-seed=12345abc\n"
        "FAILED apps/x/tests/test_a.py::test_one - boom\nFAILED apps/y/test_b.py::t2\n"
    )
    bank.bank_boxes_first_failing(str(log), "shard-1of2", "4242", workers="16")
    bank.bank_boxes_log_seed(str(log))
    bank.bank_boxes_first_failing(str(tmp_path / "nope"), "what", "", workers="16")
    assert capsys.readouterr().out == (
        "first failing: apps/x/tests/test_a.py::test_one (shard-1of2; 2 FAILED) - replay: "
        "./scripts/test.sh -n 16 --randomly-seed=4242 apps/x/tests/test_a.py::test_one\n"
        "12345\n"
        f"first failing: none named - no FAILED line in {tmp_path / 'nope'}\n"
    )


# --- the drive's bank cases, through the wrapped file ---------------------------------------


def test_bank_boxes_carry_a_one_hour_lifetime_and_a_thirty_minute_idle(
    world: World, plan: Plan
) -> None:
    assert world.bank(plan.boxes).returncode == 0, world.out
    assert "box lifetime: 1h hard, 30m idle - the box reaps itself if the Mac dies" in world.out
    ups = [line.split("\t") for line in world.rec_lines("up.calls")]
    assert sum(1 for u in ups if u[3] == "1") == plan.boxes + 1
    assert sum(1 for u in ups if u[4] == "30") == plan.boxes + 1
    world.assert_mac_measured_nothing()


def test_a_green_bank_brings_the_shards_drive_rows_home(world: World, plan: Plan) -> None:
    tree = world.tree()
    world.boxledger_rows(plan.victim, tree)
    assert world.bank(plan.boxes).returncode == 0, world.out
    harvests = world.rec_lines("harvest.calls")
    assert len(harvests) == plan.boxes
    assert world.ledger_drive_rows() == 2
    assert "drive rows: 2 brought home" in world.out
    assert {h.split("\t")[1] for h in harvests} == {tree}
    world.assert_mac_measured_nothing()


def test_a_red_bank_harvests_nothing(world: World, plan: Plan) -> None:
    world.boxledger_rows(plan.victim, world.tree())
    (world.rec / f"box.rc.{plan.victim}").write_text("1\n")
    assert world.bank(plan.boxes).returncode == 1, world.out
    assert world.rec_lines("harvest.calls") == []
    assert world.ledger_drive_rows() == 0
    assert count_lines(world.ledger) == 0
    world.assert_mac_measured_nothing()


def test_the_bank_reads_the_real_checkout_path_out_of_bake_sh(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert bank.bank_boxes_box_checkout(str(ROOT)) == 0
    got = capsys.readouterr().out.rstrip("\n")
    assert got.startswith("/"), got
    assert "${BAKE_USER}" not in got and "$BAKE_USER" not in got


def test_a_red_bank_builds_no_image(world: World, plan: Plan) -> None:
    (world.rec / f"box.rc.{plan.victim}").write_text("1\n")
    assert world.bank(plan.boxes).returncode == 1, world.out
    assert "the gate is RED. NO ROW WAS WRITTEN" in world.out
    assert plan.victim in world.out
    assert count_lines(world.rec / "image.calls") == 0
    assert count_lines(world.ledger) == 0
    assert "pushed (web" not in world.out
    world.assert_mac_measured_nothing()


def test_a_lying_tag_builds_nothing_and_the_bank_stands(world: World, plan: Plan) -> None:
    (world.rec / "image.out").write_text(
        "!! image: refusing to build under 'tree-00000000000a-dirty'"
        " — this bank keys on a tree tag\n"
    )
    (world.rec / "image.rc").write_text("3\n")
    assert world.bank(plan.boxes).returncode == 0, world.out
    assert count_lines(world.ledger) == 1
    assert "refusing to build under 'tree-00000000000a-dirty'" in world.out
    assert "image: NOT built (exit 3)" in world.out
    assert "the verdict row above STANDS" in world.out
    assert "pushed (web" not in world.out
    world.assert_mac_measured_nothing()
