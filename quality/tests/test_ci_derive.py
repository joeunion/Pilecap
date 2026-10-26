"""The workflow's shell, read out of the YAML and run: what CI measures, records, honours."""

# narrowed: the_one_walls_table_prices_the_ci_only_members_where_a_box_reads — dies with the shim
# pin: test_the_one_walls_table_prices_the_ci_only_members_where_a_box_reads (registry.walls_view)
# typed: the walls view and writer through ledger.durations/store_durations, the shell's twins
# does-not-cover: whether GitHub agrees — `fromJSON`, a job `if:` on an empty matrix, outputs.
# does-not-cover: the GitHub API's real answers; the stub `gh` answers with `--jq` applied.
# does-not-cover: the consult's own refusals (the push family's); only both answers acted on.
# does-not-cover: wall clock, an authenticated runner `gh`, and the runner's road to a box.
# does-not-cover: whether a fallback price is a box's — a runner's wall is assumed, not measured.

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from quality.djb import ledger
from quality.djb import registry as R
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.deploy_scaffold import DeployScaffold

pytestmark = pytest.mark.drives(
    ".github/workflows/ci.yml",
    ".github/workflows/nightly-proof.yml",
    "deploy/provision.sh",
    "scripts/gate_ledger.sh",
    "quality/djb/ledger.py",
    "scripts/gate_refuse.sh",
    "scripts/fe_gate.sh",
    "scripts/gate_member_durations.json",
    "quality/rules.yaml",
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly-proof.yml"
GATE_STEP = "the gate, one unit (./scripts/check.sh --leg)"
FE_STEP = "the frontend toolchain — install (the fe leg's own function)"
R62 = ROOT / "quality" / "runners" / "workflow_credential_pins.py"
#: What a world's `python3 -m quality.djb.ledger` imports: this checkout's, linked.
LEDGER_PACKAGES = ("quality", "apps")

#: The stub gate: records its argv, answers a listing from the knobs or a replay.
CHECK_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
if [ -n "${DJB_MEMBER_WALLS_OUT:-}" ]; then
    d=${DJB_MEMBER_WALLS_OUT%/*}
    if [ -d "$d" ]; then w=dir-exists; else w=dir-missing; fi
    printf 'walls=%s %s\n' "$DJB_MEMBER_WALLS_OUT" "$w" >>"$DJB_DRIVE_ARGV_LOG.env"
fi
if [ "${1:-}" = "--list-legs" ]; then
    if [ -n "${DJB_DRIVE_REPLAY:-}" ]; then
        if [ "$#" = 1 ]; then which=full
        elif [ "$#" = 2 ] && [ "$2" = "--ci" ]; then which=ci
        else shift; echo "!! unexpected extra arguments: $*" >&2; exit 2
        fi
        cat "$DJB_DRIVE_REPLAY/$which.out"
        exit 0
    fi
    [ -z "${DJB_DRIVE_LIST_STDOUT:-}" ] || printf '%b' "$DJB_DRIVE_LIST_STDOUT"
    [ -z "${DJB_DRIVE_LIST_STDERR:-}" ] || printf '%b' "$DJB_DRIVE_LIST_STDERR" >&2
    exit "${DJB_DRIVE_LIST_RC:-0}"
fi
exit "${DJB_DRIVE_LEG_RC:-0}"
"""

#: The record world's stub gate: FULL_LEGS and a listing composing the one-pass unit.
RECORD_STUB = r"""#!/usr/bin/env bash
FULL_LEGS=ruff,mypy,partition,@ONEPASS@,selftest,drv_a
printf '%s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
if [ "${1:-}" = "--list-legs" ]; then
    if [ "${2:-}" = "--ci" ]; then
        printf 'fast\tnone\t0\truff,mypy\t\n'
        printf 'suite\tdb\tN-capable\tpartition,@ONEPASS@\t1\n'
        printf 'drives\tdb\t2\tselftest,drv_a\t\n'
    else
        printf 'fast\tnone\t0\truff,mypy\n'
        printf 'suite\tdb\tN-capable\tpartition,@ONEPASS@\n'
        printf 'drives\tdb\tN-capable\tselftest,drv_a\n'
    fi
fi
exit 0
""".replace("@ONEPASS@", ledger.ONEPASS_UNIT)

#: The consult's four `gh` calls, `--jq` already applied, from FAKE_RUN/ATTEMPT/RECORD.
GH_CONSULT = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG.gh"
case "$1 ${2:-}" in
"api "*"/pulls") exit 0 ;;
"api "*"/pulls/"*"/commits"*) printf '%s\n' "${FAKE_PR_COMMITS:-}"; exit 0 ;;
"api "*"/runs?"*)
    [ -n "${FAKE_RUN:-}" ] || exit 0
    case " $* " in
    *pull_requests*) printf '%s %s\n' "$FAKE_RUN" "${FAKE_RUN_PRS:-}" ;;
    *) printf '%s\n' "$FAKE_RUN" ;;
    esac
    exit 0 ;;
"run view") printf 'completed %s\n' "${FAKE_ATTEMPT:-1}"; exit 0 ;;
"run download")
    name="" dir=""
    shift 2
    while [ "$#" -gt 0 ]; do
        case "$1" in --name) name=$2; shift 2 ;; --dir) dir=$2; shift 2 ;; *) shift ;; esac
    done
    if [ "$name" != "gate-verdict-${FAKE_ATTEMPT:-1}" ]; then
        echo "no artifact matches any of the names or patterns provided" >&2; exit 1
    fi
    mkdir -p "$dir"; cp "$FAKE_RECORD" "$dir/gate_verdict.txt"; exit 0 ;;
esac
echo "stub gh: unexpected call: $*" >&2
exit 1
"""

#: The nightly step's `gh`: `run list` answers FAKE_NIGHTLY_RUN; `run download` a record.
GH_NIGHTLY = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG.gh"
[ -z "${FAKE_GH_DOWN:-}" ] || { echo "stub gh: the API is down" >&2; exit 1; }
case "$1 ${2:-}" in
"run list") [ -z "${FAKE_NIGHTLY_RUN:-}" ] || printf '%s\n' "$FAKE_NIGHTLY_RUN"; exit 0 ;;
"run download")
    if [ -n "${FAKE_NO_ARTIFACT:-}" ]; then
        echo "no artifact matches any of the names or patterns provided" >&2
        exit 1
    fi
    dir=""
    while [ "$#" -gt 0 ]; do case "$1" in --dir) dir=$2; shift 2 ;; *) shift ;; esac; done
    mkdir -p "$dir"; echo "schema=leak-proof/1 rc=0" >"$dir/leak_proof.txt"; exit 0 ;;
esac
echo "stub gh: unexpected call: $*" >&2
exit 1
"""

#: The deploy script's stand-in: argv one argument per line, a closing line, the case's exit.
STAGE_STUB = r"""#!/usr/bin/env bash
: >"$DJB_DRIVE_ARGV_LOG.stage"
for a in "$@"; do printf '%s\n' "$a" >>"$DJB_DRIVE_ARGV_LOG.stage"; done
printf 'ns=%s registry=%s\n' "${DJB_DEPLOY_NAMESPACE:-}" "${DJB_IMAGE_REGISTRY:-}" \
    >"$DJB_DRIVE_ARGV_LOG.stage.env"
echo "stage: destination  $1"
[ -z "${DJB_DRIVE_STAGE_CLOSING:-}" ] || echo "$DJB_DRIVE_STAGE_CLOSING"
[ -z "${DJB_DRIVE_STAGE_REFUSAL:-}" ] || echo "!! stage: $DJB_DRIVE_STAGE_REFUSAL" >&2
exit "${DJB_DRIVE_STAGE_RC:-0}"
"""

PNPM_SHIM = r"""#!/usr/bin/env bash
printf '%s|%s\n' "${PWD##*/}" "$*" >>"$DJB_DRIVE_ARGV_LOG"
exit "${DJB_DRIVE_PNPM_RC:-0}"
"""

#: Every kind of unit: indivisible, a derived count, the one-pass N-capable suite, a network unit.
LISTING_CI = (
    "fast\tdb\t0\truff,mypy\t\n"
    "drives\tdb,docker\t4\tselftest,drv_a,drv_b\t\n"
    "suite\tdb,redis\tN-capable\tpartition,suite-x2\t1\n"
    "net\tnetwork\t0\tsupply\t\n"
)

RECORD_MATRIX = json.dumps(
    [
        {"unit": "fast", "needs": "none", "shard": "", "passes": ""},
        {"unit": "suite", "needs": "db", "shard": "1/2", "passes": "1"},
        {"unit": "suite", "needs": "db", "shard": "2/2", "passes": "1"},
        {"unit": "drives", "needs": "db", "shard": "1/2", "passes": ""},
        {"unit": "drives", "needs": "db", "shard": "2/2", "passes": ""},
    ]
)

ALWAYS_BUT_DISPATCH = "always() && github.event_name != 'workflow_dispatch'"


@functools.cache
def _doc(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} is not a YAML mapping"
    return loaded


def jobs(path: Path = WORKFLOW) -> dict[str, Any]:
    """The workflow's jobs by name."""
    return _doc(path).get("jobs") or {}


def job(name: str) -> dict[str, Any]:
    """One job's keys; `{}` when the workflow has no such job."""
    return jobs().get(name) or {}


def step(job_name: str, want: str) -> dict[str, Any]:
    """A job's step by `id` or `name`; `{}` when absent."""
    for each in job(job_name).get("steps") or []:
        if want in (each.get("id"), each.get("name")):
            return dict(each)
    return {}


def run_of(job_name: str, want: str) -> str:
    """A step's `run:` text; the assertion names what is missing."""
    text = step(job_name, want).get("run") or ""
    assert text, f"the {job_name} job has no {want!r} step with a run block in {WORKFLOW.name}"
    return str(text)


def needs_of(name: str) -> list[str]:
    """A job's `needs`, always as a list."""
    n = job(name).get("needs") or []
    return [n] if isinstance(n, str) else list(n)


@dataclass
class Tree:
    """One scratch tree, its outputs beside it (`.out`) and its runner temp (`.tmp`)."""

    root: Path

    @property
    def out(self) -> Path:
        return self.root.with_name(self.root.name + ".out")

    @property
    def tmp(self) -> Path:
        return self.root.with_name(self.root.name + ".tmp")

    @property
    def github_output(self) -> Path:
        return self.out / "github_output"

    @property
    def argv_log(self) -> Path:
        return self.out / "argv.log"

    def output(self, key: str) -> str:
        """What a block wrote to `$GITHUB_OUTPUT` under `key`; absent is the empty string."""
        for line in self.github_output.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line[len(key) + 1 :]
        return ""

    def has_output(self, key: str) -> bool:
        return any(ln.startswith(f"{key}=") for ln in self.github_output.read_text().splitlines())

    def matrix(self) -> list[dict[str, str]]:
        raw = self.output("matrix")
        return json.loads(raw) if raw else []

    def rows_of(self, unit: str) -> int:
        return sum(1 for r in self.matrix() if r["unit"] == unit)

    def argv(self, suffix: str = "") -> list[str]:
        path = Path(f"{self.argv_log}{suffix}")
        return path.read_text().splitlines() if path.exists() else []

    def reset_logs(self) -> None:
        self.github_output.write_text("")
        self.argv_log.write_text("")

    def plant(self, rel: str, body: str) -> Path:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        target.chmod(0o755)
        return target


@dataclass
class Ran:
    """One block's run: its exit and everything it printed."""

    rc: int
    said: str


@pytest.fixture
def tree(scratch: Path) -> Callable[..., Tree]:
    """`tree(stub=CHECK_STUB)` makes a fresh scratch tree holding a stub gate."""
    count = 0

    def build(stub: str | None = CHECK_STUB) -> Tree:
        nonlocal count
        count += 1
        made = Tree(scratch / f"case{count}")
        for d in (made.root / "scripts", made.out, made.tmp):
            d.mkdir(parents=True)
        made.reset_logs()
        if stub is not None:
            made.plant("scripts/check.sh", stub)
        return made

    return build


@pytest.fixture
def block(capture: Callable[..., Captured]) -> Callable[..., Ran]:
    """`block(tree, text, **knobs)` runs a `run:` block as a runner does: clean env, `bash -e`."""
    count = 0

    def run(
        where: Tree,
        text: str,
        *,
        flags: tuple[str, ...] = ("-e",),
        clean: bool = True,
        **knobs: str,
    ) -> Ran:
        nonlocal count
        count += 1
        script = where.out / f"block{count}.sh"
        script.write_text(text)
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", "/tmp"),  # noqa: S108 — the HOME fallback a CI step expects; never written to here
            "LANG": "C.UTF-8",
            "TMPDIR": str(where.tmp),
            "RUNNER_TEMP": str(where.tmp),
            "GITHUB_OUTPUT": str(where.github_output),
            "DJB_DRIVE_ARGV_LOG": str(where.argv_log),
            "PYTEST_SHARDS": "3",
            "LANE": "full",
            **knobs,
        }
        if clean:
            argv = ["env", "-i", *(f"{k}={v}" for k, v in env.items()), "bash", *flags]
            done = capture([*argv, str(script)], cwd=where.root)
        else:
            done = capture(["bash", *flags, str(script)], cwd=where.root, env=env)
        said = done.path.read_text(errors="replace") if done.path.exists() else ""
        return Ran(done.rc, said)

    return run


@pytest.fixture(scope="module")
def replay(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """This checkout's listing in both forms, from the registry, as the stub gate replays it."""
    where = tmp_path_factory.mktemp("replay")
    table = R.load(ROOT)
    (where / "full.out").write_text(R.list_legs(table, ci=False))
    ci = R.list_legs(table, ci=True, root=ROOT)
    assert ci, "the registry's CI listing is empty — there is nothing to derive"
    (where / "ci.out").write_text(ci)
    return where


def ci_rows(replay: Path) -> list[list[str]]:
    return [ln.split("\t") for ln in (replay / "ci.out").read_text().splitlines() if ln]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tree: Callable[..., Tree]) -> Callable[[], Tree]:
    """A committed git repository holding the real ledger package and the record's stub gate."""

    def build() -> Tree:
        made = tree(RECORD_STUB)
        for name in ("gate_ledger.sh", "gate_refuse.sh"):
            shutil.copy(ROOT / "scripts" / name, made.root / "scripts" / name)
        for package in LEDGER_PACKAGES:
            (made.root / package).symlink_to(ROOT / package)
        git(made.root, "init", "-q")
        # Invariant: the links are excluded, so the measured tree is the world's own bytes.
        (made.root / ".git" / "info" / "exclude").write_text(
            "".join(f"/{p}\n" for p in LEDGER_PACKAGES) + "__pycache__/\n"
        )
        git(made.root, "config", "user.email", "drive@example.invalid")
        git(made.root, "config", "user.name", "ci derive drive")
        (made.root / "shared.txt").write_text("one\n")
        git(made.root, "add", "-A")
        git(made.root, "commit", "-q", "-m", "base")
        return made

    return build


def record_knobs(where: Tree, **over: str) -> dict[str, str]:
    """The record step's env as a green push to main, `over` on top."""
    return {
        "DERIVE_RESULT": "success",
        "LEGS_RESULT": "success",
        "IMAGES_RESULT": "success",
        "MATRIX": RECORD_MATRIX,
        "RUN_ID": "31415926535",
        "RUN_ATTEMPT": "2",
        "HEAD_SHA": git(where.root, "rev-parse", "HEAD"),
        "PR_BASE": "",
        "PR_HEAD_REF": "",
        "HONOURED": "",
        "LANE": "full",
        **over,
    }


def record_file(where: Tree) -> Path:
    return where.tmp / "gate-verdict" / "gate_verdict.txt"


def record_fields(where: Tree) -> dict[str, str]:
    line = record_file(where).read_text().splitlines()[0]
    return dict(tok.split("=", 1) for tok in line.split(" "))


# --- derive asks `--list-legs --ci` and expands it ------------------------------------------------


def test_derive_asks_the_gate_for_the_ci_listing(
    tree: Callable[..., Tree], block: Callable[..., Ran], replay: Path
) -> None:
    w = tree()
    ran = block(w, run_of("derive", "units"), DJB_DRIVE_REPLAY=str(replay))
    assert ran.rc == 0, ran.said
    assert w.argv() == ["--list-legs --ci"]


def test_the_real_listing_becomes_the_measured_matrix(
    tree: Callable[..., Tree], block: Callable[..., Ran], replay: Path
) -> None:
    w = tree()
    ran = block(w, run_of("derive", "units"), DJB_DRIVE_REPLAY=str(replay), PYTEST_SHARDS="3")
    assert ran.rc == 0, ran.said
    counted = []
    for unit, _needs, shards, _legs, _passes in ci_rows(replay):
        want = {"0": 1, "N-capable": 3}.get(shards) or int(shards)
        assert w.rows_of(unit) == want, f"{unit}: the listing says {shards}"
        if shards not in ("0", "N-capable"):
            counted.append(unit)
    print("units counted by the listing:", counted or "none (the N-capable arm carries it)")
    assert all("passes" in r for r in w.matrix())
    onepass = {row[0] for row in ci_rows(replay) if row[4] == "1"}
    assert onepass, "no unit of the registry's CI listing carries passes=1"
    for unit in onepass:
        assert w.rows_of(unit) == 3
        assert all(r["passes"] == "1" for r in w.matrix() if r["unit"] == unit)
    assert [r for r in w.matrix() if r["passes"] == "1" and r["unit"] not in onepass] == []


def test_a_listing_becomes_rows_by_its_own_columns(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    units = run_of("derive", "units")
    w = tree()
    ran = block(w, units, DJB_DRIVE_LIST_STDOUT=LISTING_CI, PYTEST_SHARDS="3")
    assert ran.rc == 0, ran.said

    def row(u: str, n: str, s: str, p: str) -> dict[str, str]:
        return {"needs": n, "passes": p, "shard": s, "unit": u}

    assert w.matrix() == [
        row("fast", "db", "", ""),
        *(row("drives", "db,docker", f"{k}/4", "") for k in range(1, 5)),
        *(row("suite", "db,redis", f"{k}/3", "1") for k in range(1, 4)),
        row("net", "network", "", ""),
    ]
    assert "row: drives 4/4" in ran.said
    assert "row: suite 3/3 passes=1" in ran.said

    w = tree()
    assert block(w, units, DJB_DRIVE_LIST_STDOUT=LISTING_CI, PYTEST_SHARDS="5").rc == 0
    assert (w.rows_of("drives"), w.rows_of("suite")) == (4, 5)

    w = tree()
    no_count = "fast\tdb\t0\truff\t\ndrives\tdb\tN-capable\tselftest,drv_a\t\n"
    assert block(w, units, DJB_DRIVE_LIST_STDOUT=no_count).rc == 0
    assert w.rows_of("drives") == 3
    assert [r for r in w.matrix() if r["passes"] == "1"] == []


def test_a_loop_lane_runs_the_units_its_line_names_and_no_other(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    w = tree()
    units = run_of("derive", "units")
    ran = block(
        w, units, DJB_DRIVE_LIST_STDOUT=LISTING_CI, LANE="loop", UNITS="fast suite drives:1"
    )
    assert ran.rc == 0, ran.said
    assert (w.rows_of("fast"), w.rows_of("suite"), w.rows_of("drives"), w.rows_of("net")) == (
        1,
        3,
        1,
        0,
    )
    assert [r["shard"] for r in w.matrix() if r["unit"] == "drives"] == [""]
    assert "skipped: net — not a unit the loop lane's diff reaches" in ran.said


def test_a_full_lane_with_a_units_line_runs_those_units_whole_and_no_other(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    """A withheld selftest unit: the picker's `units:` line on `full` is honoured as the loop's."""
    w = tree()
    ran = block(
        w, run_of("derive", "units"), DJB_DRIVE_LIST_STDOUT=LISTING_CI, UNITS="fast suite net"
    )
    assert ran.rc == 0, ran.said
    rows = (w.rows_of("fast"), w.rows_of("suite"), w.rows_of("drives"), w.rows_of("net"))
    assert rows == (1, 3, 0, 1)
    assert "skipped: drives — not a unit the full lane's diff reaches" in ran.said
    assert "row: drives" not in ran.said
    w = tree()
    assert block(w, run_of("derive", "units"), DJB_DRIVE_LIST_STDOUT=LISTING_CI).rc == 0
    assert w.rows_of("drives") == 4


def test_a_drawer_unit_is_a_matrix_row_and_the_workflow_names_the_drawer_in_its_local_job_only(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    units = run_of("derive", "units")
    drawer = "scripts/" + "local"
    assert drawer not in units, "the derive block names the drawer — the listing must carry it"
    listing = LISTING_CI + "local\tnone\t0\tlocal:canary\t\nfrontend\tnode\t0\tlocal:tc\t\n"
    w = tree()
    ran = block(w, units, DJB_DRIVE_LIST_STDOUT=listing, PYTEST_SHARDS="3")
    assert ran.rc == 0, ran.said
    drawn = [r for r in w.matrix() if r["unit"] in ("local", "frontend")]
    assert drawn == [
        {"needs": "none", "passes": "", "shard": "", "unit": "local"},
        {"needs": "node", "passes": "", "shard": "", "unit": "frontend"},
    ]
    inlocal, outside, inside = False, [], 0
    for n, line in enumerate(WORKFLOW.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r"^  [a-z]", line):
            inlocal = line == "  local:"
        if drawer in line:
            inside += inlocal
            outside += [] if inlocal else [n]
    assert outside == [], f"ci.yml names the drawer outside its one optional local job: {outside}"
    assert inside, "the local job no longer names its drawer — the census has no subject"


@pytest.mark.parametrize(
    ("listing", "shards"),
    [
        pytest.param("suite\tdb\t0\tsuite-x2\t1\n", "3", id="one-pass-on-an-indivisible-unit"),
        pytest.param("drives\tdb\tmany\tselftest\t\n", "3", id="shards-not-a-count"),
        pytest.param("suite\tdb\tN-capable\tsuite-x2\t2\n", "3", id="passes-not-1"),
        pytest.param(LISTING_CI, "zero", id="pytest-shards-not-a-count"),
    ],
)
def test_a_listing_the_matrix_cannot_honour_is_refused(
    tree: Callable[..., Tree], block: Callable[..., Ran], listing: str, shards: str
) -> None:
    w = tree()
    ran = block(w, run_of("derive", "units"), DJB_DRIVE_LIST_STDOUT=listing, PYTEST_SHARDS=shards)
    assert ran.rc == 2, ran.said
    assert w.output("matrix") == ""


@pytest.mark.parametrize("flags", [("-e",), ()], ids=["bash-e", "bare-bash"])
def test_a_refusing_listing_fails_the_job_with_no_fallback(
    tree: Callable[..., Tree], block: Callable[..., Ran], flags: tuple[str, ...]
) -> None:
    units = run_of("derive", "units")
    w = tree()
    broken = "!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass.\n"
    ran = block(w, units, flags=flags, DJB_DRIVE_LIST_RC="2", DJB_DRIVE_LIST_STDERR=broken)
    assert ran.rc == 2, ran.said
    assert w.output("matrix") == ""
    assert "ENFORCEMENT ITSELF IS BROKEN" in ran.said
    w = tree()
    ran = block(w, units, flags=flags, DJB_DRIVE_LIST_RC="1", DJB_DRIVE_LIST_STDOUT=LISTING_CI)
    assert ran.rc == 1, ran.said
    assert w.output("matrix") == ""
    w = tree()
    ran = block(w, units, flags=flags, DJB_DRIVE_LIST_STDOUT="")
    assert ran.rc == 2, ran.said
    assert w.output("matrix") == ""


def test_the_seed_is_minted_once(tree: Callable[..., Tree], block: Callable[..., Ran]) -> None:
    w = tree()
    block(w, run_of("derive", "units"), DJB_DRIVE_LIST_STDOUT=LISTING_CI)
    assert w.output("seed").isdigit(), f"no numeric seed was minted: {w.output('seed')!r}"
    assert sum(ln.startswith("seed=") for ln in w.github_output.read_text().splitlines()) == 1


@pytest.mark.parametrize(
    ("knobs", "argv"),
    [
        pytest.param(
            {"UNIT": "fast", "DJB_DRIVE_LEG_RC": "1"}, "--leg fast", id="a-unit-that-failed"
        ),
        pytest.param(
            {"UNIT": "fast", "DJB_DRIVE_LEG_RC": "2"}, "--leg fast", id="enforcement-broke"
        ),
        pytest.param({"UNIT": "fast"}, "--leg fast", id="indivisible-on-a-push"),
        pytest.param({"UNIT": "drives", "SHARD": "3/4"}, "--leg drives --shard 3/4", id="counted"),
        pytest.param(
            {"UNIT": "suite", "SHARD": "2/3", "PASSES": "1"},
            "--leg suite --shard 2/3 --passes 1",
            id="suite-one-pass",
        ),
        pytest.param(
            {"UNIT": "suite", "SHARD": "2/3", "PASSES": "1", "PR_BASE": "abc123"}
            | {"PR_HEAD_REF": "pm/mq-1", "LANE": "loop"},
            "--leg suite --shard 2/3 --passes 1 --pr --base abc123",
            id="a-pm-head-on-the-loop-lane-is-narrowed",
        ),
        pytest.param(
            {"UNIT": "drives", "SHARD": "1/4", "PR_BASE": "abc123", "PR_HEAD_REF": "feature/x"}
            | {"LANE": "loop"},
            "--leg drives --shard 1/4 --pr --base abc123",
            id="a-loop-lane-pr-is-narrowed",
        ),
        pytest.param(
            {"UNIT": "drives", "SHARD": "1/4", "PR_BASE": "abc123", "PR_HEAD_REF": "feature/x"},
            "--leg drives --shard 1/4",
            id="a-full-lane-pr-runs-whole",
        ),
    ],
)
def test_the_row_invokes_the_gate_and_nothing_else(
    tree: Callable[..., Tree],
    block: Callable[..., Ran],
    scratch: Path,
    knobs: dict[str, str],
    argv: str,
) -> None:
    walls = scratch / "walls" / "member-walls" / "walls.tsv"
    w = tree()
    base = {"SHARD": "", "PASSES": "", "PR_BASE": "", "PR_HEAD_REF": ""}
    seeded = {"DJB_GATE_PYTEST_SEED": "12345", "DJB_MEMBER_WALLS_OUT": str(walls)}
    ran = block(w, run_of("legs", GATE_STEP), **{**base, **seeded, **knobs})
    assert ran.rc == int(knobs.get("DJB_DRIVE_LEG_RC", "0")), ran.said
    assert w.argv() == [argv]
    assert w.argv(".env") == [f"walls={walls} dir-exists"]


def test_no_step_grades_a_pull_request_by_its_head_branchs_name() -> None:
    """The lane alone says how a pull request is graded; no step reads the head ref."""
    text = WORKFLOW.read_text()
    assert "github.head_ref" not in text and "PR_HEAD_REF" not in text
    runs = [str(s.get("run", "")) for j in jobs().values() for s in j.get("steps") or []]
    assert [r for r in runs if "pm/" in r] == [], "a branch-name case in a step"
    assert sum(1 for r in runs if r) >= 10, "a floor: the steps were read"


def test_every_row_writes_its_walls_and_uploads_them(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    gate_step = step("legs", GATE_STEP)
    walls_out = (gate_step.get("env") or {}).get("DJB_MEMBER_WALLS_OUT")
    assert walls_out == "${{ runner.temp }}/member-walls/walls.tsv"
    uploads = [
        s
        for s in job("legs").get("steps") or []
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
        and "member-walls" in json.dumps(s)
    ]
    assert uploads, "the legs job has no upload-artifact step for the member walls"
    assert uploads[0].get("if") == "always()"
    assert uploads[0]["with"]["name"] == "${{ steps.row.outputs.walls_artifact }}"
    assert uploads[0]["with"]["path"] == "${{ runner.temp }}/member-walls/"
    w = tree()
    assert block(w, run_of("legs", "row"), UNIT="drives", SHARD="2/6").rc == 0
    assert w.output("walls_artifact") == "member-walls-drives-2-of-6"
    w = tree()
    assert block(w, run_of("legs", "row"), UNIT="fast", SHARD="").rc == 0
    assert w.output("walls_artifact") == "member-walls-fast"


def test_every_row_installs_the_frontend_toolchain_by_the_fe_legs_own_function(
    tree: Callable[..., Tree], block: Callable[..., Ran], scratch: Path
) -> None:
    names = [s.get("name") or s.get("uses") or "" for s in job("legs").get("steps") or []]
    order = [
        "the frontend toolchain — pnpm",
        "the frontend toolchain — node",
        FE_STEP,
        GATE_STEP,
    ]
    at = [names.index(w) for w in order]
    assert at == sorted(at), "pnpm, then node, then the install, then the gate"
    node = step("legs", "the frontend toolchain — node").get("with") or {}
    assert node.get("cache") == "pnpm"
    assert node.get("cache-dependency-path") == "frontend/pnpm-lock.yaml"
    assert "if" not in step("legs", FE_STEP), "every row runs the install"
    text = run_of("legs", FE_STEP)
    lines = text.splitlines()
    assert [ln.strip() for ln in lines].count(". ./scripts/fe_gate.sh") == 1
    assert sum("fe_leg_frozen_lockfile " in ln for ln in lines) == 1
    typed = [ln for ln in lines if "pnpm " in ln and not ln.strip().startswith(("#", "echo "))]
    assert typed == [], "the install types no pnpm command of its own"
    shim = scratch / "pnpm-shim"
    shim.write_text(PNPM_SHIM)
    shim.chmod(0o755)
    no_aws = {"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "", "AWS_SESSION_TOKEN": ""}

    def fe_tree(frontend: bool) -> Tree:
        w = tree()
        shutil.copy(ROOT / "scripts" / "fe_gate.sh", w.root / "scripts" / "fe_gate.sh")
        if frontend:
            (w.root / "frontend").mkdir()
            (w.root / "frontend" / "package.json").write_text('{"name":"fixture","private":true}\n')
            (w.root / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: 9.0\n")
        return w

    w = fe_tree(True)
    assert block(w, text, FE_PNPM=str(shim), **no_aws).rc == 0
    assert w.argv() == ["frontend|install --frozen-lockfile"]
    w = fe_tree(True)
    ran = block(w, text, FE_PNPM=str(shim), DJB_DRIVE_PNPM_RC="1", **no_aws)
    assert ran.rc == 0, "a lockfile pnpm refuses never fails the row"
    assert "named no lockfile drift" in ran.said, "a silent pnpm failure is could-not-look"
    assert "::warning::pnpm install --frozen-lockfile exited 2" in ran.said
    w = fe_tree(False)
    ran = block(w, text, FE_PNPM=str(shim), **no_aws)
    assert ran.rc == 0
    assert "nothing to install" in ran.said
    assert w.argv() == []


def test_the_workflow_types_no_unit_name_of_its_own(replay: Path) -> None:
    prose = [ln for ln in WORKFLOW.read_text().splitlines() if not ln.lstrip().startswith("#")]
    typed = {
        unit: n
        for unit, *_ in ci_rows(replay)
        if (n := sum(len(re.findall(rf"(?<!\w){re.escape(unit)}(?!\w)", ln)) for ln in prose))
    }
    assert typed == {}, "the matrix is asked for, never typed"


# --- the record -----------------------------------------------------------------------------------


def test_the_record_is_the_measured_tree_and_every_field(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    w = repo()
    ran = block(w, run_of("gate-verdict", "record"), **record_knobs(w))
    assert ran.rc == 0, ran.said
    got = record_fields(w)
    assert got["tree"] == ledger.measured_tree(w.root)
    assert got["commit"] == git(w.root, "rev-parse", "HEAD")
    assert got["legs"] == "drives,fast,suite/1"
    assert (got["shards"], got["scope"], got["rc"]) == ("3", "whole", "0")
    assert (got["run"], got["attempt"]) == ("31415926535", "2")
    lines = record_file(w).read_text().splitlines()
    assert len(lines) == 1
    parsed = ledger.ci_parse(lines[0])
    assert (parsed.tree, parsed.rc, parsed.attempt) == (got["tree"], "0", "2")
    assert w.output("artifact") == "gate-verdict-2", "the name the consult downloads by attempt"


def test_a_red_or_cancelled_job_is_rc_1_and_a_narrowed_pr_says_so(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    record = run_of("gate-verdict", "record")
    for over in (
        {"LEGS_RESULT": "failure"},
        {"LEGS_RESULT": "cancelled"},
        {"LEGS_RESULT": "skipped"},
        {"DERIVE_RESULT": "failure"},
        {"IMAGES_RESULT": "failure"},
        {"IMAGES_RESULT": "skipped"},
        {"DERIVE_RESULT": "failure", "MATRIX": ""},
    ):
        w = repo()
        assert block(w, record, **record_knobs(w, **over)).rc == 0
        assert record_fields(w)["rc"] == "1", over
    for lane, scope in (("loop", "pr"), ("full", "whole")):
        w = repo()
        knobs = record_knobs(w, PR_BASE="abc123", PR_HEAD_REF="feature/x", LANE=lane)
        assert block(w, record, **knobs).rc == 0
        assert (record_fields(w)["scope"], record_fields(w)["lane"]) == (scope, lane)
    w = repo()
    ran = block(w, record, **record_knobs(w, DERIVE_RESULT="failure", MATRIX="", LANE=""))
    assert ran.rc == 0, ran.said
    assert (record_fields(w)["rc"], "lane" in record_fields(w)) == ("1", False)
    w = repo()
    empty = subprocess.run(
        ["git", "-C", str(w.root), "mktree"], input="", capture_output=True, text=True, check=True
    ).stdout.strip()
    other = git(w.root, "commit-tree", empty, "-m", "empty")
    ran = block(w, record, **record_knobs(w, HEAD_SHA=other))
    assert ran.rc == 0, ran.said
    assert "the reader will refuse this record" in ran.said


def test_an_honoured_push_writes_no_record(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    w = repo()
    knobs = record_knobs(
        w,
        LEGS_RESULT="skipped",
        MATRIX="[]",
        HONOURED="777",
        HONOURED_ATTEMPT="2",
        HONOURED_TREE="abcdef0123",
    )
    ran = block(w, run_of("gate-verdict", "record"), **knobs)
    assert ran.rc == 0, ran.said
    assert not record_file(w).exists()
    assert w.output("artifact") == ""
    assert "honoured" in ran.said


def test_a_record_the_workflow_writes_is_a_record_the_reader_honours(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    """G5.4: the record step's writer and `push.ci_verdict`'s reader, one module, round-tripped."""
    w = repo()
    ran = block(w, run_of("gate-verdict", "record"), **record_knobs(w))
    assert ran.rc == 0, ran.said
    line = record_file(w).read_text().splitlines()[0]
    got = record_fields(w)
    wrote = (got["commit"], got["tree"], got["legs"], got["shards"], got["scope"], got["rc"])
    assert got["lane"] == "full"
    assert line == ledger.ci_record(*wrote, got["run"], got["attempt"], at=got["at"], lane="full")
    listing = subprocess.run(
        ["./scripts/check.sh", "--list-legs"],
        cwd=w.root,
        env={**os.environ, "DJB_DRIVE_ARGV_LOG": str(w.argv_log)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    judged = ledger.ci_judge(w.root, line, "31415926535", "2", listing)
    assert judged.split(",") == ["selftest", "drv_a", "ruff", "mypy", "partition", "pytest-x2/1"]
    with pytest.raises(ledger.Refused, match="attempt=2"):
        ledger.ci_judge(w.root, line, "31415926535", "3", listing)
    assert w.output("artifact") == ledger.ci_artifact_name("2")
    for lane in ("loop", "docs"):
        knobs = record_knobs(w, LANE=lane, PR_BASE="abc123", PR_HEAD_REF="feature/x")
        if lane == "docs":
            knobs.update(LEGS_RESULT="skipped", IMAGES_RESULT="skipped", MATRIX="[]")
        assert block(w, run_of("gate-verdict", "record"), **knobs).rc == 0
        narrowed = record_file(w).read_text().splitlines()[0]
        assert record_fields(w)["rc"] == "0", lane
        with pytest.raises(ledger.Refused, match=f"ran the {lane} lane"):
            ledger.ci_judge(w.root, narrowed, "31415926535", "2", listing)


def test_a_withheld_selftest_record_round_trips_and_the_judge_vouches_by_induction(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    """A `full` record with `selftest=withheld` vouches for the tree; the unit's legs ride it."""
    w = repo()
    w.plant("scripts/check.sh", RECORD_STUB.replace("drives", "selftest"))
    git(w.root, "add", "scripts/check.sh")
    git(w.root, "commit", "-q", "-m", "the unit named as the template names it")
    matrix = json.dumps([r for r in json.loads(RECORD_MATRIX) if r["unit"] != "drives"])
    knobs = record_knobs(w, MATRIX=matrix, CLOSURE="withheld")
    ran = block(w, run_of("gate-verdict", "record"), **knobs)
    assert ran.rc == 0, ran.said
    line = record_file(w).read_text().splitlines()[0]
    assert line.endswith(" lane=full selftest=withheld"), line
    assert ledger.ci_parse(line).selftest == "withheld"
    listing = subprocess.run(
        ["./scripts/check.sh", "--list-legs"],
        cwd=w.root,
        env={**os.environ, "DJB_DRIVE_ARGV_LOG": str(w.argv_log)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    judged = ledger.ci_judge(w.root, line, "31415926535", "2", listing)
    assert set(judged.split(",")) >= {"selftest", "drv_a", "ruff", "mypy"}, judged
    bare = line.removesuffix(" selftest=withheld")
    with pytest.raises(ledger.Refused, match="missing 'selftest'"):
        ledger.ci_judge(w.root, bare, "31415926535", "2", listing)


# --- the consult on a push, and the verdict that honours it ---------------------------------------


@dataclass
class Consult:
    """A repository whose HEAD a pull request run measured, its record behind a stub `gh`."""

    where: Tree
    head: str
    tree: str

    def knobs(self, **over: str) -> dict[str, str]:
        return {
            "PATH": f"{self.where.out / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PUSH_SHA": self.head,
            "GH_TOKEN": "drive",
            "GH_REPO": "example/drive",
            "FAKE_RUN": "777",
            "FAKE_ATTEMPT": "2",
            "FAKE_RECORD": str(self.where.out / "record.txt"),
            **over,
        }


@pytest.fixture
def consult(repo: Callable[[], Tree]) -> Callable[[str], Consult]:
    """`consult(rc)` — the world, the record written by `ledger.ci_record` with that rc."""

    def build(rc: str) -> Consult:
        w = repo()
        (w.out / "bin").mkdir()
        gh = w.out / "bin" / "gh"
        gh.write_text(GH_CONSULT)
        gh.chmod(0o755)
        head = git(w.root, "rev-parse", "HEAD")
        measured = ledger.measured_tree(w.root)
        line = ledger.ci_record(head, measured, "fast,suite/1,drives", "3", "whole", rc, "777", "2")
        (w.out / "record.txt").write_text(line + "\n")
        return Consult(w, head, measured)

    return build


def test_an_honoured_push_measures_nothing(
    consult: Callable[[str], Consult], block: Callable[..., Ran]
) -> None:
    c = consult("0")
    ran = block(c.where, run_of("derive", "consult"), **c.knobs())
    assert ran.rc == 0, ran.said
    assert f"consult: honoured run=777 attempt=2 tree={c.tree}" in ran.said
    w = c.where
    assert (w.output("honoured"), w.output("attempt"), w.output("tree")) == ("777", "2", c.tree)
    w.reset_logs()
    honour = {"HONOURED": "777", "HONOURED_ATTEMPT": "2", "HONOURED_TREE": c.tree}
    assert block(w, run_of("derive", "units"), **honour).rc == 0
    assert w.output("matrix") == "[]"
    assert not any("--list-legs" in a for a in w.argv()), "the listing was never asked"
    ran = block(
        w,
        run_of("verdict", "the verdict"),
        DERIVE_RESULT="success",
        LEGS_RESULT="skipped",
        **honour,
    )
    assert ran.rc == 0, ran.said
    honoured = f"honoured: pull_request run 777 for tree {c.tree} — nothing re-measured"
    assert f"{honoured} (attempt 2)" in ran.said


def test_a_pull_request_run_honours_its_own_earlier_measure_over_a_fold_only_delta(
    consult: Callable[[str], Consult], block: Callable[..., Ran]
) -> None:
    """CI-THIRD-1 1.1, the YAML: a pull request consults its own head, by its number."""
    gate = str(step("derive", "consult").get("if") or "")
    assert "github.event_name == 'pull_request'" in gate, gate
    assert "github.event_name == 'push'" in gate, gate
    c = consult("0")
    knobs = c.knobs(PR_NUMBER="7", FAKE_PR_COMMITS=c.head, FAKE_RUN_PRS="7")
    ran = block(c.where, run_of("derive", "consult"), **knobs)
    assert ran.rc == 0, ran.said
    assert f"consult: honoured run=777 attempt=2 tree={c.tree}" in ran.said
    gh = c.where.argv(".gh")
    assert any("pulls/7/commits" in a for a in gh), gh
    assert not any(a.endswith("/pulls --jq .[].head.sha") for a in gh), gh
    w = c.where
    honour = {"HONOURED": w.output("honoured"), "HONOURED_ATTEMPT": "2", "HONOURED_TREE": c.tree}
    w.reset_logs()
    assert block(w, run_of("derive", "units"), LANE="full", **honour).rc == 0
    assert w.output("matrix") == "[]"
    ran = block(
        w,
        run_of("verdict", "the verdict"),
        DERIVE_RESULT="success",
        LEGS_RESULT="skipped",
        **honour,
    )
    assert ran.rc == 0, ran.said
    assert f"honoured: pull_request run 777 for tree {c.tree} — nothing re-measured" in ran.said
    w.reset_logs()
    ran = block(w, run_of("derive", "consult"), **c.knobs(PR_NUMBER="7", FAKE_RUN_PRS="8"))
    assert ran.rc == 0 and "consult: measure — " in ran.said, ran.said
    assert not w.has_output("honoured"), "another pull request's run is never this one's"


def test_the_honour_line_says_the_selftest_unit_was_withheld_and_the_belt_measures(
    consult: Callable[[str], Consult], block: Callable[..., Ran]
) -> None:
    """Main's summary names what was not measured; the belt's consult honours no such run."""
    c = consult("0")
    w = c.where
    w.plant("scripts/check.sh", RECORD_STUB.replace("drives", "selftest"))
    git(w.root, "add", "scripts/check.sh")
    git(w.root, "commit", "-q", "-m", "the unit named as the template names it")
    head, tree = git(w.root, "rev-parse", "HEAD"), ledger.measured_tree(w.root)
    for word, legs, honoured in (
        ("withheld", "fast,suite/1", False),
        ("ran", "fast,suite/1,selftest", True),
    ):
        line = ledger.ci_record(
            head, tree, legs, "3", "whole", "0", "777", "2", lane="full", selftest=word
        )
        (w.out / "record.txt").write_text(line + "\n")
        w.reset_logs()
        ran = block(w, run_of("derive", "consult"), **c.knobs(PUSH_SHA=head))
        assert ran.rc == 0, ran.said
        assert f"consult: honoured run=777 attempt=2 selftest={word} tree={tree}" in ran.said
        assert w.output("tree") == tree, ran.said
        belt = subprocess.run(
            [sys.executable, "-E", "-S", "-m", "quality.djb.ledger", "selftest-consult", head],
            cwd=w.root,
            env={**os.environ, **c.knobs(PUSH_SHA=head), "DJB_DRIVE_ARGV_LOG": str(w.argv_log)},
            capture_output=True,
            text=True,
        )
        assert belt.returncode == 0, belt.stderr
        assert belt.stdout.startswith("consult: honoured") is honoured, belt.stdout
        if not honoured:
            assert "run 777 withheld the selftest unit" in belt.stdout, belt.stdout


def test_a_full_lanes_row_narrows_only_the_unit_its_units_line_marks_pr(
    tree: Callable[..., Tree], block: Callable[..., Ran], scratch: Path
) -> None:
    """CI-THIRD-3 3.2: `<unit>:pr` carries `--pr --base` on a full lane; no other row does."""
    walls = scratch / "walls" / "member-walls" / "walls.tsv"
    knobs = {"SHARD": "", "PASSES": "", "PR_BASE": "abc123", "LANE": "full"}
    knobs |= {"DJB_MEMBER_WALLS_OUT": str(walls), "UNITS": "fast suite:pr drives"}
    for unit, want in (("suite", "--leg suite --pr --base abc123"), ("fast", "--leg fast")):
        w = tree()
        assert block(w, run_of("legs", GATE_STEP), UNIT=unit, **knobs).rc == 0
        assert w.argv() == [want], w.argv()
    w = tree()
    ran = block(
        w, run_of("derive", "units"), DJB_DRIVE_LIST_STDOUT=LISTING_CI, UNITS="fast suite:pr"
    )
    assert ran.rc == 0, ran.said
    assert (w.rows_of("fast"), w.rows_of("suite"), w.rows_of("drives")) == (1, 3, 0)
    env = step("gate-verdict", "record").get("env") or {}
    assert env.get("PYTEST") == "${{ needs.derive.outputs.pytest }}"
    assert '--pytest "$PYTEST"' in run_of("gate-verdict", "record")


#: The plan stub: the gate as a row runs it, printing the plan file its environment names.
PLAN_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
printf 'plan=%s\n' "$(cat "${DJB_SELFTEST_PLAN:-/dev/null}")" >>"$DJB_DRIVE_ARGV_LOG.env"
"""


def test_a_full_lane_runs_the_narrowed_selftest_unit_on_its_own_shard_count_and_plan(
    tree: Callable[..., Tree], block: Callable[..., Ran], scratch: Path
) -> None:
    """CI-THIRD-2 2.3: `selftest:<n>` is n rows, and every row reads the lane's plan line."""
    w = tree()
    ran = block(
        w,
        run_of("derive", "units"),
        DJB_DRIVE_LIST_STDOUT=LISTING_CI,
        UNITS="fast suite drives:2 net",
    )
    assert ran.rc == 0, ran.said
    assert [r["shard"] for r in w.matrix() if r["unit"] == "drives"] == ["1/2", "2/2"]
    assert (w.rows_of("fast"), w.rows_of("suite"), w.rows_of("net")) == (1, 3, 1)
    plan = "selftest-plan/1 gate-tests=quality/tests/test_a.py engine="
    walls = scratch / "walls" / "member-walls" / "walls.tsv"
    row = tree(PLAN_STUB)
    knobs = {"UNIT": "drives", "SHARD": "1/2", "PASSES": "", "PR_BASE": ""}
    knobs["DJB_MEMBER_WALLS_OUT"] = str(walls)
    ran = block(row, run_of("legs", GATE_STEP), SELFTEST_PLAN=plan, **knobs)
    assert ran.rc == 0, ran.said
    assert row.argv(".env") == [f"plan={plan}"]
    lane = run_of("derive", "lane")
    assert "lane --plan --base" in lane and "plan=$plan" in lane
    assert job("legs")["steps"]
    env = step("legs", GATE_STEP).get("env") or {}
    assert env.get("SELFTEST_PLAN") == "${{ needs.derive.outputs.plan }}"
    assert job("derive")["outputs"]["plan"] == "${{ steps.lane.outputs.plan }}"


def test_a_narrowed_selftest_record_round_trips_and_the_belt_does_not_honour_it(
    consult: Callable[[str], Consult], block: Callable[..., Ran]
) -> None:
    """2.4: `selftest=narrowed` parses and vouches on main; the nightly belt measures it whole."""
    c = consult("0")
    w = c.where
    w.plant("scripts/check.sh", RECORD_STUB.replace("drives", "selftest"))
    git(w.root, "add", "scripts/check.sh")
    git(w.root, "commit", "-q", "-m", "the unit named as the template names it")
    head, tree = git(w.root, "rev-parse", "HEAD"), ledger.measured_tree(w.root)
    line = ledger.ci_record(
        head, tree, "fast,suite/1,selftest", "3", "whole", "0", "777", "2", lane="full",
        selftest="narrowed",
    )  # fmt: skip
    assert ledger.ci_parse(line).selftest == "narrowed"
    (w.out / "record.txt").write_text(line + "\n")
    ran = block(w, run_of("derive", "consult"), **c.knobs(PUSH_SHA=head))
    assert f"consult: honoured run=777 attempt=2 selftest=narrowed tree={tree}" in ran.said
    belt = subprocess.run(
        [sys.executable, "-E", "-S", "-m", "quality.djb.ledger", "selftest-consult", head],
        cwd=w.root,
        env={**os.environ, **c.knobs(PUSH_SHA=head), "DJB_DRIVE_ARGV_LOG": str(w.argv_log)},
        capture_output=True,
        text=True,
    )
    assert belt.returncode == 0, belt.stderr
    assert "run 777 narrowed the selftest unit" in belt.stdout, belt.stdout
    closure = run_of("derive", "lane")
    assert "(ran|narrowed|withheld)" in closure


def _belt_step(want: str) -> dict[str, Any]:
    belt = jobs(NIGHTLY)["selftest-belt"]
    return next(s for s in belt["steps"] if want in (s.get("id"), s.get("name")))


@pytest.mark.template_only(
    reason="the nightly proof is the template's own workflow; a product never receives it"
)
def test_the_nightly_belt_runs_the_selftest_unit_whole_only_when_no_run_measured_the_tree(
    consult: Callable[[str], Consult], block: Callable[..., Ran]
) -> None:
    """The closure's belt is consult-gated: one line and no install when the tree was measured."""
    c = consult("0")
    w = c.where
    w.plant("scripts/check.sh", RECORD_STUB.replace("drives", "selftest"))
    git(w.root, "add", "scripts/check.sh")
    git(w.root, "commit", "-q", "-m", "the unit named as the template names it")
    head, tree = git(w.root, "rev-parse", "HEAD"), ledger.measured_tree(w.root)
    text = str(_belt_step("consult")["run"])
    for word, legs, measure in (
        ("ran", "fast,suite/1,selftest", ""),
        ("withheld", "fast,suite/1", "1"),
    ):
        line = ledger.ci_record(
            head, tree, legs, "3", "whole", "0", "777", "2", lane="full", selftest=word
        )
        (w.out / "record.txt").write_text(line + "\n")
        w.reset_logs()
        ran = block(w, text, **c.knobs(SHA=head))
        assert ran.rc == 0, ran.said
        assert w.output("measure") == measure, ran.said
        said = "skipped — tree of" if not measure else "measuring — run 777 withheld"
        assert f"selftest belt: {said}" in ran.said, ran.said
    gated = [s for s in jobs(NIGHTLY)["selftest-belt"]["steps"][2:]]
    assert all(
        str(s.get("if", "")).startswith("steps.consult.outputs.measure == '1'") for s in gated
    )
    assert gated[-1]["run"] == "./scripts/check.sh --leg selftest"


def test_a_push_nothing_honours_measures_in_full(
    consult: Callable[[str], Consult], block: Callable[..., Ran]
) -> None:
    c = consult("1")
    ran = block(c.where, run_of("derive", "consult"), **c.knobs())
    assert ran.rc == 0, ran.said
    assert "consult: measure" in ran.said
    assert c.where.output("honoured") == ""
    c.where.reset_logs()
    assert block(c.where, run_of("derive", "units"), HONOURED="").rc == 0
    assert len(c.where.matrix()) == 6, "one indivisible, three one-pass, two counted"

    c = consult("0")
    (c.where.out / "bin" / "gh").write_text(
        '#!/usr/bin/env bash\necho "stub gh: the API is down" >&2\nexit 1\n'
    )
    ran = block(c.where, run_of("derive", "consult"), **c.knobs())
    assert ran.rc == 0, "a consult that cannot look measures — it never refuses"
    assert "consult: measure — could not look" in ran.said
    assert c.where.output("honoured") == ""


@pytest.mark.parametrize(
    ("knobs", "rc"),
    [
        pytest.param({"LEGS_RESULT": "success", "HONOURED": ""}, 0, id="every-row-green"),
        pytest.param({"LEGS_RESULT": "skipped", "HONOURED": ""}, 1, id="skipped-unhonoured"),
        pytest.param({"LEGS_RESULT": "failure", "HONOURED": ""}, 1, id="a-red-row"),
        pytest.param(
            {"DERIVE_RESULT": "failure", "LEGS_RESULT": "skipped", "HONOURED": "777"}
            | {"HONOURED_ATTEMPT": "1", "HONOURED_TREE": "abc"},
            1,
            id="failed-derive-beside-an-honour",
        ),
    ],
)
def test_the_verdict_honours_only_an_honour(
    tree: Callable[..., Tree], block: Callable[..., Ran], knobs: dict[str, str], rc: int
) -> None:
    w = tree()
    ran = block(w, run_of("verdict", "the verdict"), **{"DERIVE_RESULT": "success", **knobs})
    assert ran.rc == rc, ran.said
    if rc == 0:
        assert "ok: every unit of the gate ran and passed" in ran.said


@pytest.mark.parametrize(
    ("knobs", "said"),
    [
        pytest.param(
            {"LEGS_RESULT": "cancelled"},
            "could not look: legs did not run (cancelled by the runner)",
            id="legs-cancelled",
        ),
        pytest.param(
            {"LEGS_RESULT": "skipped", "MATRIX": '[{"unit":"selftest"}]'},
            "could not look: legs did not run (skipped by the runner with rows planned)",
            id="legs-skipped-with-rows",
        ),
        pytest.param(
            {"DERIVE_RESULT": "cancelled", "LEGS_RESULT": "skipped"},
            "could not look: derive did not run (cancelled by the runner)",
            id="derive-cancelled",
        ),
    ],
)
def test_a_job_the_runner_never_ran_is_could_not_look(
    tree: Callable[..., Tree], block: Callable[..., Ran], knobs: dict[str, str], said: str
) -> None:
    w = tree()
    base = {"DERIVE_RESULT": "success", "HONOURED": "", "LANE": "full"}
    ran = block(w, run_of("verdict", "the verdict"), **{**base, **knobs})
    assert ran.rc == 2, ran.said
    assert said in ran.said


def plant_row_exit(where: Tree, row: str, rc: str) -> None:
    """One row's `member-walls` artifact as the verdict jobs download it, holding its exit."""
    home = where.tmp / "rows" / f"member-walls-{row}"
    home.mkdir(parents=True, exist_ok=True)
    (home / "rc").write_text(f"{rc}\n")


def test_a_row_writes_its_own_exit_beside_its_walls(
    tree: Callable[..., Tree], block: Callable[..., Ran], scratch: Path
) -> None:
    for rc in ("0", "1", "2"):
        walls = scratch / f"walls-{rc}" / "member-walls" / "walls.tsv"
        w = tree()
        knobs = {"UNIT": "selftest", "SHARD": "", "PASSES": "", "PR_BASE": ""}
        ran = block(
            w,
            run_of("legs", GATE_STEP),
            **knobs,
            DJB_MEMBER_WALLS_OUT=str(walls),
            DJB_DRIVE_LEG_RC=rc,
        )
        assert ran.rc == int(rc), ran.said
        assert (walls.parent / "rc").read_text().strip() == rc


@pytest.mark.parametrize(
    "name",
    [
        "the stack the gate assumes (docker compose up)",
        "the mail catcher, on a row whose unit needs it",
        "the identity platform, its machine credential and the second host",
    ],
)
def test_a_stack_step_that_could_not_look_writes_the_row_s_exit(
    tree: Callable[..., Tree], block: Callable[..., Ran], name: str
) -> None:
    """A pull that failed twice is the row's exit 2 before the gate step ever runs."""
    w = tree()
    w.plant("scripts/ci_stack.sh", "#!/usr/bin/env bash\necho 'could not look: x'\nexit 2\n")
    ran = block(w, run_of("legs", name))
    assert ran.rc == 2, ran.said
    assert (w.tmp / "member-walls" / "rc").read_text().strip() == "2"


def test_a_row_that_could_not_look_is_could_not_look_in_both_verdicts(
    tree: Callable[..., Tree],
    repo: Callable[[], Tree],
    block: Callable[..., Ran],
) -> None:
    """A row's own exit 2 reaches the verdict as `failure`; its artifact carries the 2."""
    base = {"DERIVE_RESULT": "success", "HONOURED": "", "LANE": "full", "ROWS_READ": "success"}
    w = tree()
    plant_row_exit(w, "pytest-x2-1-of-3", "0")
    plant_row_exit(w, "selftest-3-of-5", "2")
    ran = block(w, run_of("verdict", "the verdict"), **base, LEGS_RESULT="failure")
    assert ran.rc == 2, ran.said
    assert "could not look: selftest-3-of-5 could not look (rc=2)" in ran.said
    w = tree()
    plant_row_exit(w, "selftest-3-of-5", "1")
    ran = block(w, run_of("verdict", "the verdict"), **base, LEGS_RESULT="failure")
    assert ran.rc == 1, ran.said
    assert "could not look" not in ran.said
    w = tree()
    over = {**base, "ROWS_READ": "failure", "LEGS_RESULT": "success"}
    ran = block(w, run_of("verdict", "the verdict"), **over)
    assert ran.rc == 2, ran.said
    assert "could not look: the rows' exits would not download" in ran.said

    w = repo()
    plant_row_exit(w, "selftest-3-of-5", "2")
    record = run_of("gate-verdict", "record")
    ran = block(w, record, **record_knobs(w, LEGS_RESULT="failure"), ROWS_READ="success")
    assert ran.rc == 2, ran.said
    assert "record: none — selftest-3-of-5 could not look (rc=2)" in ran.said
    assert not record_file(w).exists()
    assert w.output("artifact") == ""


def test_both_verdicts_download_the_rows_exits_before_they_judge() -> None:
    for name, judge in (("verdict", "verdict"), ("gate-verdict", "record")):
        steps = [s.get("id") or s.get("name") for s in job(name).get("steps") or []]
        got = step(name, "rows")
        assert str(got.get("uses", "")).startswith("actions/download-artifact@"), name
        assert got["with"] == {"pattern": "member-walls-*", "path": "${{ runner.temp }}/rows"}
        assert got.get("continue-on-error") is True, name
        assert steps.index("rows") < steps.index(judge), name
        env = step(name, judge).get("env") or {}
        assert env.get("ROWS_READ") == "${{ steps.rows.outcome }}", name


def test_the_wiring_between_the_jobs() -> None:
    consulted = "github.event_name == 'push' || github.event_name == 'pull_request'"
    assert step("derive", "consult").get("if") == consulted, "CI-THIRD-1: a PR consults too"
    honour = "${{ steps.consult.outputs.honoured }}"
    assert step("derive", "units")["env"]["HONOURED"] == honour
    assert job("derive")["outputs"]["honoured"] == honour
    assert job("legs").get("if") == "needs.derive.outputs.matrix != '[]'"
    verdict_env = step("verdict", "the verdict").get("env") or {}
    assert verdict_env.get("HONOURED") == "${{ needs.derive.outputs.honoured }}"
    assert verdict_env.get("MATRIX") == "${{ needs.derive.outputs.matrix }}"
    assert job("verdict").get("if") == ALWAYS_BUT_DISPATCH
    checkouts = [
        s for s in job("derive")["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert (checkouts[0].get("with") or {}).get("fetch-depth") == 0, "the consult needs history"


# --- the lane: derive asks one word and the run follows it (MQ1.3) ------------------------------

#: The lane step's stand-in picker: logs its argv, prints what the case hands it.
PICKER_STUB = r"""#!/usr/bin/env bash
printf 'python %s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
printf '%b' "${DJB_DRIVE_LANE_OUT:-}"
exit "${DJB_DRIVE_LANE_RC:-0}"
"""

LANE_STEP = "the lane — what this change can reach"


def _picker(w: Tree) -> None:
    w.plant(".venv/bin/python", PICKER_STUB)


@pytest.mark.parametrize(
    ("knobs", "lane", "asked"),
    [
        pytest.param({"EVENT": "push"}, "full", False, id="a-push-is-full-unasked"),
        pytest.param(
            {"EVENT": "pull_request", "PR_BASE": "abc123", "DJB_DRIVE_LANE_OUT": "docs\\n  why\\n"},
            "docs",
            True,
            id="a-pull-request-asks",
        ),
        pytest.param(
            {"EVENT": "pull_request", "PR_BASE": "abc123", "PR_HEAD_REF": "pm/mq-1"}
            | {"DJB_DRIVE_LANE_OUT": "loop\\n  units:      static\\n"},
            "loop",
            True,
            id="a-pm-head-is-the-pickers-word",
        ),
    ],
)
def test_the_lane_step_asks_the_picker_and_hands_on_one_word(
    repo: Callable[[], Tree],
    block: Callable[..., Ran],
    scratch: Path,
    knobs: dict[str, str],
    lane: str,
    asked: bool,
) -> None:
    w = repo()
    _picker(w)
    summary = scratch / f"summary-{lane}-{asked}"
    ran = block(w, run_of("derive", "lane"), GITHUB_STEP_SUMMARY=str(summary), **knobs)
    assert ran.rc == 0, ran.said
    assert w.output("lane") == lane
    head = git(w.root, "rev-parse", "HEAD")
    want = [f"python -m quality.djb.scope lane --plan --base abc123 --head {head}"] if asked else []
    assert w.argv() == want
    assert summary.read_text().startswith(f"### lane: {lane}\n")


@pytest.mark.parametrize(
    ("out", "rc"),
    [pytest.param("", "2", id="the-picker-refuses"), pytest.param("fast\\n", "0", id="not-a-lane")],
)
def test_a_lane_the_step_cannot_honour_fails_derive(
    repo: Callable[[], Tree], block: Callable[..., Ran], out: str, rc: str
) -> None:
    w = repo()
    _picker(w)
    knobs = {"EVENT": "pull_request", "PR_BASE": "abc123", "DJB_DRIVE_LANE_OUT": out}
    ran = block(w, run_of("derive", "lane"), DJB_DRIVE_LANE_RC=rc, **knobs)
    assert ran.rc == 2, ran.said
    assert w.output("lane") == ""


WITHHELD = "  selftest:  withheld — none of the 3 changed path(s) is in the selftest closure\\n"


@pytest.mark.parametrize(
    ("out", "rc", "selftest", "units"),
    [
        pytest.param(f"full\\n{WITHHELD}  units:      static\\n", 0, "withheld", "static"),
        pytest.param(
            "full\\n  selftest:  ran — quality/x.py is in the closure (quality/)\\n", 0, "ran", ""
        ),
        pytest.param(f"full\\n{WITHHELD}", 2, "", ""),
    ],
    ids=["withheld-with-units", "ran-whole", "withheld-with-no-units-refused"],
)
def test_the_lane_step_hands_on_the_selftest_word_and_refuses_a_withheld_lane_with_no_units(
    repo: Callable[[], Tree],
    block: Callable[..., Ran],
    out: str,
    rc: int,
    selftest: str,
    units: str,
) -> None:
    w = repo()
    _picker(w)
    knobs = {"EVENT": "pull_request", "PR_BASE": "abc123", "DJB_DRIVE_LANE_OUT": out}
    ran = block(w, run_of("derive", "lane"), **knobs)
    assert ran.rc == rc, ran.said
    assert (w.output("closure"), w.output("units")) == (selftest, units)


def test_the_record_carries_the_selftest_word_derive_handed_on() -> None:
    text = run_of("gate-verdict", "record")
    assert '[ -z "${CLOSURE:-}" ] || lane+=(--closure "$CLOSURE")' in text
    assert job("derive")["outputs"]["closure"] == "${{ steps.lane.outputs.closure }}"


def test_the_lane_step_runs_the_real_picker_on_a_docs_change(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    """The step's own line, the real picker, a real one-commit documentation change."""
    w = repo()
    (w.root / ".venv").mkdir()
    (w.root / ".venv" / "bin").symlink_to(ROOT / ".venv" / "bin")
    exclude = w.root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "/.venv\n")
    base = git(w.root, "rev-parse", "HEAD")
    (w.root / "README.md").write_text("# a documentation change\n")
    git(w.root, "add", "README.md")
    git(w.root, "commit", "-q", "-m", "docs")
    ran = block(w, run_of("derive", "lane"), EVENT="pull_request", PR_BASE=base)
    assert ran.rc == 0, ran.said
    assert w.output("lane") == "docs", ran.said


def test_the_docs_lane_is_an_empty_matrix_never_asked_of_the_listing(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    w = tree()
    ran = block(w, run_of("derive", "units"), LANE="docs", DJB_DRIVE_LIST_STDOUT=LISTING_CI)
    assert ran.rc == 0, ran.said
    assert w.output("matrix") == "[]"
    assert w.argv() == [], "the listing was never asked"
    assert "lane: docs — no row runs" in ran.said
    w = tree()
    ran = block(w, run_of("derive", "units"), LANE="", DJB_DRIVE_LIST_STDOUT=LISTING_CI)
    assert ran.rc == 2, ran.said
    assert w.output("matrix") == ""
    w = tree()
    ran = block(w, run_of("derive", "units"), LANE="loop", DJB_DRIVE_LIST_STDOUT=LISTING_CI)
    assert ran.rc == 2 and "the listing produced no units" in ran.said, ran.said
    w = tree()
    every = "fast drives suite net"
    ran = block(
        w, run_of("derive", "units"), LANE="loop", UNITS=every, DJB_DRIVE_LIST_STDOUT=LISTING_CI
    )
    assert ran.rc == 0, ran.said
    assert len(w.matrix()) == 9 and "lane: loop" in ran.said


@pytest.mark.parametrize(
    ("lane", "rc"), [pytest.param("docs", 0, id="docs"), pytest.param("loop", 1, id="loop")]
)
def test_the_verdict_passes_a_docs_lane_and_nothing_else_that_ran_nothing(
    tree: Callable[..., Tree], block: Callable[..., Ran], lane: str, rc: int
) -> None:
    w = tree()
    knobs = {"DERIVE_RESULT": "success", "LEGS_RESULT": "skipped", "HONOURED": "", "LANE": lane}
    ran = block(w, run_of("verdict", "the verdict"), **knobs)
    assert ran.rc == rc, ran.said
    assert w.output("lane") == lane


def test_a_docs_record_is_green_with_no_row_and_no_image(
    repo: Callable[[], Tree], block: Callable[..., Ran]
) -> None:
    record = run_of("gate-verdict", "record")
    docs = {"LANE": "docs", "LEGS_RESULT": "skipped", "MATRIX": "[]", "PR_BASE": "abc123"}
    for images, rc in (("skipped", "0"), ("success", "1")):
        w = repo()
        assert block(w, record, **record_knobs(w, IMAGES_RESULT=images, **docs)).rc == 0
        got = record_fields(w)
        assert (got["rc"], got["legs"], got["scope"], got["lane"]) == (rc, "none", "pr", "docs")


#: The build stands down on the docs lane and on an honoured push, whose tree a PR measured.
IMAGES_IF = "needs.derive.outputs.lane != 'docs' && needs.derive.outputs.honoured == ''"


def test_an_honoured_push_builds_no_image() -> None:
    """Run 38142479801: an honoured push skips `legs` and so `images-push`; a build is waste."""
    assert job("images").get("if") == IMAGES_IF
    assert job("derive")["outputs"]["honoured"] == "${{ steps.consult.outputs.honoured }}"


def test_a_docs_pull_request_runs_derive_verdict_and_gate_verdict_alone() -> None:
    """MQ1.3: every other job stands down on the docs lane, by its own `if:`."""
    stands_down = {
        "legs": "needs.derive.outputs.matrix != '[]'",
        "images": IMAGES_IF,
        "images-push": "needs.verdict.outputs.lane != 'docs'",
        "local": "needs.verdict.outputs.lane != 'docs'",
        "deploy-staging": "github.event_name == 'push' && github.ref == 'refs/heads/main'",
        "deploy-prod": "github.event_name == 'workflow_dispatch'",
    }
    assert {n: job(n).get("if") for n in stands_down} == stands_down
    assert sorted(set(jobs()) - set(stands_down)) == ["derive", "gate-verdict", "verdict"]
    lane = "${{ needs.derive.outputs.lane }}"
    assert job("derive")["outputs"]["lane"] == "${{ steps.lane.outputs.lane }}"
    assert step("derive", "units")["env"]["LANE"] == "${{ steps.lane.outputs.lane }}"
    assert step("legs", GATE_STEP)["env"]["LANE"] == lane
    assert step("verdict", "the verdict")["env"]["LANE"] == lane
    assert step("gate-verdict", "record")["env"]["LANE"] == lane
    assert job("verdict")["outputs"]["lane"] == "${{ steps.verdict.outputs.lane }}"
    names = [s.get("name") or s.get("uses") for s in job("derive")["steps"]]
    assert names.index(LANE_STEP) < names.index("ask the gate what its units are")


# --- the shape ------------------------------------------------------------------------------------


def _perms(holder: dict[str, Any]) -> dict[str, Any]:
    p = holder.get("permissions")
    return p if isinstance(p, dict) else {}


def test_the_shape_of_the_workflow(capture: Callable[..., Captured], scratch: Path) -> None:
    assert needs_of("images") == ["derive"], "the build runs beside the legs"
    assert needs_of("gate-verdict") == ["derive", "legs", "images"]
    assert job("gate-verdict").get("if") == ALWAYS_BUT_DISPATCH
    uploads = [
        s
        for s in job("gate-verdict").get("steps") or []
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert uploads[0].get("if") == "always() && steps.record.outputs.artifact != ''"
    assert uploads[0]["with"]["name"] == "${{ steps.record.outputs.artifact }}"
    top = _perms(_doc(WORKFLOW))
    assert top.get("contents") != "write"
    assert [n for n, j in jobs().items() if _perms(j).get("contents") == "write"] == []
    for grant, holders in (("actions", ["deploy-prod", "derive"]), ("pull-requests", ["derive"])):
        assert not top.get(grant), f"{grant} is granted workflow-wide"
        held = sorted(n for n, j in jobs().items() if _perms(j).get(grant) in ("read", "write"))
        assert held == holders, f"{grant}: read is held where its readers run, and nowhere else"
    prose = [ln for ln in WORKFLOW.read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert [ln for ln in prose if re.search(r"git +push", ln)] == []
    ran = capture([sys.executable, str(R62), ".github/workflows"], cwd=ROOT)
    assert ran.rc == 0, ran.text()
    found = json.loads(ran.text())
    assert found["findings"] == [], "house rule 62 on the workflows"
    assert found["targets"]["run_steps_after_an_exporter"] >= 1, "a floor, not a vacuous zero"


def test_every_job_reads_only_the_jobs_it_needs() -> None:
    """A `needs.<job>` a job names outside its own `needs:` is null, so its `if:` never holds."""
    assert jobs(), "a floor: the workflow has jobs to judge"
    stray = {}
    for name, body in jobs().items():
        named = set(re.findall(r"needs\.([A-Za-z0-9_-]+)", str(body.get("if") or "")))
        read = set(re.findall(r"needs\.([A-Za-z0-9_-]+)", json.dumps(body)))
        if (named | read) - set(needs_of(name)):
            stray[name] = sorted((named | read) - set(needs_of(name)))
    assert stray == {}, "a job reads an output of a job it does not wait on"
    assert sum("needs." in str(j.get("if") or "") for j in jobs().values()) >= 3, "a floor"


def upstream(name: str) -> set[str]:
    """Every job `name` waits on, transitively."""
    seen: set[str] = set()
    todo = needs_of(name)
    while todo:
        each = todo.pop()
        if each not in seen:
            seen.add(each)
            todo.extend(needs_of(each))
    return seen


#: What writes to ECR; the build job's session may hold none of it.
ECR_WRITES = (
    "ecr:Put",
    "ecr:InitiateLayerUpload",
    "ecr:UploadLayerPart",
    "ecr:CompleteLayerUpload",
)


def test_the_image_builds_beside_the_legs_and_pushes_behind_the_verdict() -> None:
    assert "verdict" not in upstream("images"), "the build waits on nothing but derive"
    assert sorted(needs_of("images-push")) == ["images", "verdict"]
    gate = str(job("images-push").get("if") or "")
    assert not re.search(r"\b(always|failure|cancelled|success)\(", gate), (
        "no status function, so success() of both is implied: a red verdict skips the push"
    )
    assert "images-push" not in upstream("gate-verdict"), "the record never waits on a push"
    assert "verdict" not in upstream("gate-verdict"), "the record is the rows and the build"
    assert _perms(job("images")) == {"contents": "read", "id-token": "write"}
    assert _perms(job("images-push")) == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    assume = [
        s
        for s in job("images")["steps"]
        if str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")
    ]
    assert len(assume) == 1
    policy = json.loads(assume[0]["with"]["inline-session-policy"])
    actions = [a for st in policy["Statement"] for a in st["Action"]]
    assert actions and [a for a in actions if a.startswith(ECR_WRITES)] == []
    built = json.dumps(job("images"))
    assert "--push" not in built and "skopeo copy" not in built, "the build job writes no registry"
    pushed = json.dumps(job("images-push"))
    assert "skopeo copy --all --preserve-digests" in pushed, "the push is the built bytes"
    assert "docker buildx build" not in pushed, "the push job builds nothing"


def _uses(job_name: str, action: str) -> list[dict[str, Any]]:
    return [
        s for s in job(job_name).get("steps") or [] if str(s.get("uses", "")).startswith(action)
    ]


def test_the_push_downloads_the_one_name_the_build_uploads() -> None:
    up = [s for s in _uses("images", "actions/upload-artifact@") if s["with"]["name"] == "images"]
    down = _uses("images-push", "actions/download-artifact@")
    assert len(up) == len(down) == 1
    assert up[0]["with"]["name"] == down[0]["with"]["name"], "the push reads what the build wrote"
    assert "run_attempt" not in up[0]["with"]["name"], "a --failed rerun keeps attempt 1's build"
    assert up[0]["with"].get("overwrite") is True, "a rerun of the build replaces its archive"


#: A provision.sh for the image steps: a digest is `.present-<target>`'s content, else absent.
PROVISION_STUB = r"""#!/usr/bin/env bash
case "$1" in
image-services) echo "web worker frontend" ;;
image-ref) printf 'reg/djb-%s:%s\n' "$2" "$3" ;;
image-digest)
    if [ -f ".present-$2" ]; then cat ".present-$2"; exit 0; fi
    if [ -f ".refuse" ]; then
        echo "denied: not authorized to perform: ecr:BatchGetImage" >&2
    else
        echo "manifest unknown" >&2
    fi
    exit 1 ;;
*) exit 2 ;;
esac
"""

#: A skopeo: `copy` records and lands the archive's digest; `inspect` answers $STUB_USER.
SKOPEO_STUB = r"""#!/usr/bin/env bash
printf 'skopeo %s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
case "$1" in
copy)
    for a in "$@"; do case "$a" in oci-archive:*) archive="${a#oci-archive:}" ;; esac; done
    target="$(basename "$archive" .tar)"
    tar -xOf "$archive" index.json | jq -r '.manifests[0].digest' >".present-$target" ;;
inspect) printf '{"config":{"User":"%s"}}\n' "${STUB_USER:-}" ;;
esac
"""


def image_world(tree: Callable[..., Tree]) -> tuple[Tree, str]:
    """A scratch tree with the provision and skopeo stubs and one archive per target."""
    w = tree(stub=None)
    w.plant("deploy/provision.sh", PROVISION_STUB)
    w.plant("bin/skopeo", SKOPEO_STUB)
    for target in ("web", "worker", "frontend"):
        src = w.out / f"oci-{target}"
        src.mkdir()
        (src / "index.json").write_text(
            json.dumps({"manifests": [{"digest": f"sha256:built{target}"}]})
        )
        (w.tmp / "images").mkdir(exist_ok=True)
        subprocess.run(
            ["tar", "-cf", str(w.tmp / "images" / f"{target}.tar"), "-C", str(src), "index.json"],
            check=True,
        )
    return w, f"{w.root / 'bin'}:{os.environ['PATH']}"


PUSH_STEP = "push the built archive under the tree tag"


def test_the_push_copies_an_absent_tag_and_skips_an_equal_one(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    w, path = image_world(tree)
    (w.root / ".present-web").write_text("sha256:builtweb\n")
    ran = block(w, run_of("images-push", PUSH_STEP), PATH=path, TAG="tree-1", REGISTRY="reg")
    assert ran.rc == 0, ran.said
    assert "reg/djb-web:tree-1 already holds the built sha256:builtweb" in ran.said
    copies = [ln for ln in w.argv() if ln.startswith("skopeo copy")]
    assert [c.split("oci-archive:")[1].split()[0].rsplit("/")[-1] for c in copies] == [
        "worker.tar",
        "frontend.tar",
    ], copies


def test_a_rerun_s_rebuild_of_a_pushed_tree_is_not_re_pushed(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    w, path = image_world(tree)
    (w.root / ".present-web").write_text("sha256:other\n")
    ran = block(w, run_of("images-push", PUSH_STEP), PATH=path, TAG="tree-1", REGISTRY="reg")
    assert ran.rc == 0, ran.said
    assert "tree-1 already pushed (sha256:other) — this rerun's build is not re-pushed" in ran.said
    copies = [ln for ln in w.argv() if ln.startswith("skopeo copy")]
    assert [c.split("oci-archive:")[1].split()[0].rsplit("/")[-1] for c in copies] == [
        "worker.tar",
        "frontend.tar",
    ], copies


def test_the_have_check_says_a_refused_read_aloud(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    w, path = image_world(tree)
    have = run_of("images", "have")
    knobs = {"PATH": path, "TAG": "tree-1", "REGISTRY": "reg", "PUSH": "true"}
    ran = block(w, have, flags=(), **knobs)
    assert ran.rc == 0 and w.output("have") == "false"
    assert "manifest unknown" in ran.said and "::warning::" not in ran.said
    (w.root / ".refuse").write_text("")
    w.reset_logs()
    ran = block(w, have, flags=(), **knobs)
    assert ran.rc == 0 and w.output("have") == "false", "a refusal still builds"
    assert "not authorized" in ran.said
    assert "::warning::the registry REFUSED the read of web" in ran.said


NONROOT_STEP = "the images run as a non-root user"


@pytest.mark.parametrize(
    ("user", "rc"),
    [("djb:djb", 0), ("10001", 0), ("", 1), ("root", 1), ("0:0", 1)],
)
def test_the_non_root_check_reads_the_archive(
    tree: Callable[..., Tree], block: Callable[..., Ran], user: str, rc: int
) -> None:
    body = run_of("images", NONROOT_STEP)
    assert "--load" not in body, "the check reads the archive, never a rebuild"
    w, path = image_world(tree)
    ran = block(w, body, PATH=path, TAG="tree-1", STUB_USER=user)
    assert ran.rc == rc, ran.said
    inspected = [ln for ln in w.argv() if ln.startswith("skopeo inspect --config")]
    assert len(inspected) == (6 if rc == 0 else 1), inspected


def test_derive_prints_the_critical_path_the_graph_draws() -> None:
    record = upstream("gate-verdict")
    assert record == {"derive", "legs", "images"}
    assert needs_of("legs") == needs_of("images") == ["derive"], "legs and the build are siblings"
    said = run_of("derive", "units")
    assert (
        'echo "critical path: derive → the longest legs row ∥ images → gate-verdict;'
        " images-push waits on verdict, off the record's path\"" in said
    )


# --- the deploy jobs: staging on a push to main, prod by dispatch ---------------------------------


def step_line(s: dict[str, Any]) -> str:
    return f"{s.get('id', '')}|{str(s.get('uses', '')).split('@')[0]}|{s.get('if', '')}"


def role_of(name: str) -> str:
    for s in job(name).get("steps") or []:
        if str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials@"):
            return str((s.get("with") or {}).get("role-to-assume"))
    return ""


def env_of(job_name: str, want: str) -> dict[str, str]:
    return step(job_name, want).get("env") or {}


def stage_argv(w: Tree) -> list[str]:
    return w.argv(".stage")


def test_deploy_staging_stands_behind_the_verdict_and_the_image() -> None:
    ds = job("deploy-staging")
    assert ds, "the workflow has no deploy-staging job — a merge to main deploys nothing"
    assert needs_of("deploy-staging") == ["verdict", "images-push"]
    assert ds.get("if") == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert _perms(ds) == {"contents": "read", "id-token": "write"}
    assert ds.get("environment") is None, "the trust names the ref form"
    assert "secrets." not in json.dumps(ds), "its one credential is the OIDC role"
    asked = "steps.target.outputs.deploy == 'true'"
    assert [step_line(s) for s in ds["steps"]] == [
        "target||",
        f"|actions/checkout|{asked}",
        f"|aws-actions/configure-aws-credentials|{asked}",
        f"stage||{asked}",
    ]
    assert role_of("deploy-staging") == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    env = env_of("deploy-staging", "stage")
    assert env["TARGET"] == "${{ vars.DJB_STAGE_TARGET }}"
    assert env["DJB_DEPLOY_NAMESPACE"] == "${{ vars.DJB_DEPLOY_NAMESPACE }}"
    assert env["DJB_IMAGE_REGISTRY"] == "${{ vars.DJB_IMAGE_REGISTRY }}"


def test_deploy_staging_skips_with_a_notice_unless_the_product_names_a_stage(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    gate_block = run_of("deploy-staging", "target")
    role = "arn:aws:iam::1:role/x"
    for target, arn in (("", ""), ("ec2-user@stage", ""), ("", role)):
        w = tree()
        ran = block(w, gate_block, TARGET=target, ROLE=arn)
        assert ran.rc == 0, ran.said
        assert w.output("deploy") == "false"
        assert "::notice::deploy-staging skipped" in ran.said
        if not target and not arn:
            assert "DJB_STAGE_TARGET AWS_DEPLOY_ROLE_ARN" in ran.said
    w = tree()
    assert block(w, gate_block, TARGET="ec2-user@stage", ROLE=role).rc == 0
    assert w.output("deploy") == "true"


def test_deploy_staging_runs_stage_sh_and_carries_its_exit_and_closing_line(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    stage = run_of("deploy-staging", "stage")
    registry = "1.dkr.ecr.us-east-1.amazonaws.com/acme"
    closing = "stage: tree-0123456789ab live in 97s (migrate 4s)"
    w = tree()
    w.plant("deploy/stage.sh", STAGE_STUB)
    ran = block(
        w,
        stage,
        TARGET="ec2-user@stage",
        DJB_DEPLOY_NAMESPACE="acme",
        DJB_IMAGE_REGISTRY=registry,
        DJB_DRIVE_STAGE_CLOSING=closing,
    )
    assert ran.rc == 0, ran.said
    assert stage_argv(w) == ["ec2-user@stage", "--env", "staging"]
    assert w.argv(".stage.env") == [f"ns=acme registry={registry}"]
    assert f"stage-verdict: rc=0 {closing}" in ran.said
    refusal = "the registry does not have this tree's web image"
    for rc in ("1", "2"):
        w = tree()
        w.plant("deploy/stage.sh", STAGE_STUB)
        knobs = {"DJB_DEPLOY_NAMESPACE": "acme", "DJB_IMAGE_REGISTRY": "r"}
        ran = block(
            w,
            stage,
            TARGET="ec2-user@stage",
            DJB_DRIVE_STAGE_RC=rc,
            DJB_DRIVE_STAGE_REFUSAL=refusal,
            **knobs,
        )
        assert ran.rc == int(rc), ran.said
        assert f"stage-verdict: rc={rc} no closing line" in ran.said
        assert f"!! stage: {refusal}" in ran.said
    w = tree()
    w.plant("deploy/stage.sh", STAGE_STUB)
    ran = block(
        w, stage, TARGET="ec2-user@stage", DJB_DEPLOY_NAMESPACE="acme", DJB_IMAGE_REGISTRY="r"
    )
    assert ran.rc == 0, "a docs-only delta: exit 0, nothing went live"
    assert "stage-verdict: rc=0 no closing line" in ran.said


def test_deploy_prod_is_a_dispatch_with_a_tree_and_a_sanction() -> None:
    doc = _doc(WORKFLOW)
    on = doc.get("on") or doc.get(True) or {}  # type: ignore[call-overload]
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
    assert {k: (v.get("required"), v.get("type")) for k, v in inputs.items()} == {
        "sanction": (True, "string"),
        "tree": (True, "string"),
    }
    dp = job("deploy-prod")
    assert dp, "the workflow has no deploy-prod job — nothing promotes a staged tree"
    assert dp.get("if") == "github.event_name == 'workflow_dispatch'"
    assert needs_of("deploy-prod") == [], "the gate already measured the tree staging holds"
    assert _perms(dp) == {"actions": "read", "contents": "read", "id-token": "write"}
    assert dp.get("environment") is None
    assert "secrets." not in json.dumps(dp)
    runs = [str(s.get("run", "")) for s in dp["steps"]]
    assert [r for r in runs if "inputs." in r] == [], "dispatch inputs arrive as env, never shell"
    assert [step_line(s) for s in dp["steps"]] == [
        "target||",
        "|actions/checkout|",
        "tree||",
        "nightly||",
        "|aws-actions/configure-aws-credentials|",
        "promote||",
    ]
    assert role_of("deploy-prod") == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    assert env_of("deploy-prod", "tree")["TREE"] == "${{ inputs.tree }}"
    promote = env_of("deploy-prod", "promote")
    assert promote["SANCTION"] == "${{ inputs.sanction }}"
    assert promote["NIGHTLY_DIR"] == "${{ steps.nightly.outputs.dir }}"
    assert promote["PROD"] == "${{ vars.DJB_PROD_TARGET }}"
    assert promote["STAGE"] == "${{ vars.DJB_STAGE_TARGET }}"


def test_deploy_prod_refuses_when_the_product_names_no_prod(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    gate_block = run_of("deploy-prod", "target")
    every = {"PROD": "p", "STAGE": "s", "ROLE": "r", "REF": "refs/heads/main"}
    for missing in ("PROD", "STAGE", "ROLE", "REF"):
        knobs = {**every, missing: "refs/heads/feature" if missing == "REF" else ""}
        ran = block(tree(), gate_block, **knobs)
        assert ran.rc == 2, (missing, ran.said)
        assert "nothing was promoted" in ran.said
    assert block(tree(), gate_block, **every).rc == 0


@dataclass
class History:
    """A main holding a code commit then a docs-only one, and a tree only a side branch holds."""

    where: Tree
    code: str
    code_tree: str
    docs: str
    side_tree: str


@pytest.fixture
def history(repo: Callable[[], Tree], deploy_scaffold: DeployScaffold) -> Callable[[], History]:
    def build() -> History:
        w = repo()
        (w.root / "deploy").mkdir()
        shutil.copy(ROOT / "deploy" / "provision.sh", w.root / "deploy" / "provision.sh")
        deploy_scaffold.into(w.root)
        git(w.root, "add", "-A")
        git(w.root, "commit", "-q", "-m", "code")
        code, code_tree = git(w.root, "rev-parse", "HEAD"), git(w.root, "rev-parse", "HEAD^{tree}")
        (w.root / "README.md").write_text("docs\n")
        git(w.root, "add", "README.md")
        git(w.root, "commit", "-q", "-m", "docs")
        docs = git(w.root, "rev-parse", "HEAD")
        git(w.root, "update-ref", "refs/remotes/origin/main", docs)
        git(w.root, "checkout", "-q", "-b", "side")
        (w.root / "side.txt").write_text("side\n")
        git(w.root, "add", "side.txt")
        git(w.root, "commit", "-q", "-m", "side")
        side_tree = git(w.root, "rev-parse", "HEAD^{tree}")
        git(w.root, "checkout", "-q", docs)
        return History(w, code, code_tree, docs, side_tree)

    return build


def test_deploy_prod_checks_out_the_tree_staging_holds(
    history: Callable[[], History], block: Callable[..., Ran]
) -> None:
    tree_block = run_of("deploy-prod", "tree")
    first = history()
    short = first.code_tree[:12]
    for form in (f"tree-{short}", short, first.code_tree):
        h = history()
        ran = block(h.where, tree_block, TREE=form)
        assert ran.rc == 0, (form, ran.said)
        assert git(h.where.root, "rev-parse", "HEAD") == h.code, (
            "the commit carrying staging's tree"
        )
        assert h.where.output("tag") == f"tree-{short}"
    for form in ("", "tree-xyz", "tree-0123", "HEAD", f"tree-{short}; rm -rf /"):
        h = history()
        ran = block(h.where, tree_block, TREE=form)
        assert ran.rc == 2, (form, ran.said)
        assert git(h.where.root, "rev-parse", "HEAD") == h.docs, "the checkout did not move"
    h = history()
    ran = block(h.where, tree_block, TREE=f"tree-{h.side_tree[:12]}")
    assert ran.rc == 2, ran.said
    assert "no commit on origin/main" in ran.said
    assert git(h.where.root, "rev-parse", "HEAD") == h.docs


@pytest.mark.template_only(
    reason="the nightly proof is the template's own workflow; a product never receives it"
)
def test_deploy_prod_hands_stage_sh_the_latest_nightly(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    nightly = run_of("deploy-prod", "nightly")
    names = [
        (s.get("with") or {}).get("name", "")
        for j in jobs(NIGHTLY).values()
        for s in j.get("steps") or []
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(names) == 1, f"nightly-proof.yml publishes {names}"

    def with_gh(**knobs: str) -> tuple[Tree, Ran]:
        w = tree()
        (w.out / "bin").mkdir()
        gh = w.out / "bin" / "gh"
        gh.write_text(GH_NIGHTLY)
        gh.chmod(0o755)
        path = f"{w.out / 'bin'}{os.pathsep}{os.environ['PATH']}"
        ran = block(w, nightly, PATH=path, GH_TOKEN="drive", GH_REPO="example/drive", **knobs)  # noqa: S106 — a fake GitHub token the stub gh accepts
        return w, ran

    w, ran = with_gh(FAKE_NIGHTLY_RUN="4242")
    assert ran.rc == 0, ran.said
    assert (Path(w.output("dir")) / "leak_proof.txt").stat().st_size > 0
    asked = w.argv(".gh")
    listing = "run list --workflow nightly-proof.yml --branch main --status completed"
    assert sum(listing in a for a in asked) == 1
    assert sum(f"run download 4242 --name {names[0]} " in a for a in asked) == 1

    w, ran = with_gh(FAKE_NIGHTLY_RUN="")
    assert ran.rc == 0, ran.said
    assert w.has_output("dir") and w.output("dir") == "", "stage.sh reads nightly:none"

    w, ran = with_gh(FAKE_NIGHTLY_RUN="4242", FAKE_NO_ARTIFACT="1")
    assert ran.rc == 0, ran.said
    handed = Path(w.output("dir"))
    assert w.output("dir") and handed.is_dir(), "an empty directory, refused as unreadable"
    assert not (handed / "leak_proof.txt").exists()

    w, ran = with_gh(FAKE_GH_DOWN="1")
    assert ran.rc == 2, ran.said
    assert "could not ask GitHub" in ran.said


def test_deploy_prod_asks_no_nightly_in_a_product_tree(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    nightly = run_of("deploy-prod", "nightly")

    def in_drawer(text: str) -> tuple[Tree, Ran]:
        w = tree()
        w.plant("quality/local/rules.yaml", text)
        (w.out / "bin").mkdir()
        gh = w.out / "bin" / "gh"
        gh.write_text(GH_NIGHTLY)
        gh.chmod(0o755)
        path = f"{w.out / 'bin'}{os.pathsep}{os.environ['PATH']}"
        ran = block(
            w,
            nightly,
            PATH=path,
            GH_TOKEN="drive",  # noqa: S106 — a fake GitHub token the stub gh accepts
            GH_REPO="example/drive",
            FAKE_GH_DOWN="1",
        )
        return w, ran

    w, ran = in_drawer("rule_id_namespace: workbench\n")
    assert ran.rc == 0, ran.said
    assert (
        "nightly: a product tree — the platform's nightly leak proof is the template's;"
        " stage.sh reads the product's own gate"
    ) in ran.said
    assert w.has_output("dir") and w.output("dir") == "", "stage.sh is handed no nightly"
    assert w.argv(".gh") == [], "a product's repo has no nightly-proof.yml to list"

    w, ran = in_drawer('rule_id_namespace: ""\n')
    assert ran.rc == 2, ran.said
    assert "could not ask GitHub" in ran.said


def test_deploy_prod_runs_stage_sh_with_the_four_teeth_inputs(
    tree: Callable[..., Tree], block: Callable[..., Ran]
) -> None:
    promote = run_of("deploy-prod", "promote")
    sanction = 'Ana O\'Neil: "ship" $(touch pwned) `id` & more'
    base = {
        "PROD": "ec2-user@prod",
        "STAGE": "ec2-user@stage",
        "DJB_DEPLOY_NAMESPACE": "acme",
        "DJB_IMAGE_REGISTRY": "r",
    }
    closing = "stage: tree-0123456789ab live in 120s (migrate skipped)"
    w = tree()
    w.plant("deploy/stage.sh", STAGE_STUB)
    ran = block(
        w,
        promote,
        SANCTION=sanction,
        NIGHTLY_DIR="/tmp/nightly",  # noqa: S108 — the CI runner's path the derived step names, compared
        DJB_DRIVE_STAGE_CLOSING=closing,
        **base,
    )
    assert ran.rc == 0, ran.said
    assert stage_argv(w) == [
        "ec2-user@prod",
        "--env",
        "prod",
        "--sanction",
        sanction,
        "--staging",
        "ec2-user@stage",
        "--nightly",
        "/tmp/nightly",  # noqa: S108 — the CI runner's path the derived step names, compared
    ]
    assert not (w.root / "pwned").exists(), "the sanction's command substitution never ran"
    assert f"stage-verdict: rc=0 {closing}" in ran.said
    w = tree()
    w.plant("deploy/stage.sh", STAGE_STUB)
    ran = block(
        w,
        promote,
        SANCTION="a: b",
        NIGHTLY_DIR="",
        DJB_DRIVE_STAGE_RC="2",
        DJB_DRIVE_STAGE_REFUSAL="REFUSED — nightly: nightly:none",
        **base,
    )
    assert ran.rc == 2, ran.said
    assert stage_argv(w)[-1] == "" and stage_argv(w)[-2] == "--nightly", "passed empty, not dropped"
    assert "stage-verdict: rc=2 no closing line" in ran.said


def test_a_dispatch_runs_no_gate() -> None:
    assert job("derive").get("if") == "github.event_name != 'workflow_dispatch'"
    assert job("verdict").get("if") == ALWAYS_BUT_DISPATCH
    assert job("gate-verdict").get("if") == ALWAYS_BUT_DISPATCH
    concurrency = _doc(WORKFLOW).get("concurrency") or {}
    dispatch = "github.event_name == 'workflow_dispatch'"
    assert concurrency.get("group") == (
        f"gate-${{{{ github.workflow }}}}-${{{{ {dispatch} && 'dispatch' || github.ref }}}}"
    )
    assert concurrency.get("cancel-in-progress") == (
        "${{ github.event_name != 'workflow_dispatch' && github.ref != 'refs/heads/main' }}"
    )


@pytest.mark.template_only(
    reason="the nightly proof is the template's own workflow; a product never receives it"
)
def test_the_nightly_runs_the_supply_chain_unit() -> None:
    doc = _doc(NIGHTLY)
    on = doc.get("on") or doc.get(True) or {}  # type: ignore[call-overload]
    assert [c.get("cron") for c in on.get("schedule") or []] == ["17 7 * * *"]
    sc = jobs(NIGHTLY).get("supply-chain") or {}
    assert sc.get("name") == "supply chain (the gate's unit)"
    runs = [str(s.get("run", "")).strip() for s in sc.get("steps") or [] if s.get("run")]
    assert runs[-1] == "./scripts/check.sh --leg supply-chain"
    assert "supply-chain" in [u.name for u, _ in R.load(ROOT).rows], "a unit of the registry"


def test_rule_62_judges_the_deploy_steps(capture: Callable[..., Captured], scratch: Path) -> None:
    plant = scratch / "r62plant"
    (plant / "quality").mkdir(parents=True)
    (plant / "wf").mkdir()
    shutil.copy(ROOT / "quality" / "rules.yaml", plant / "quality" / "rules.yaml")
    kept, current = [], ""
    for line in WORKFLOW.read_text().splitlines(keepends=True):
        m = re.match(r"^  ([a-z][a-z-]*):\s*$", line)
        if m:
            current = m.group(1)
        stripped = current in ("deploy-staging", "deploy-prod") and re.search(r"#\s*creds:", line)
        if not stripped:
            kept.append(line)
    (plant / "wf" / "ci.yml").write_text("".join(kept))
    ran = capture([sys.executable, str(R62), "wf"], cwd=plant)
    assert ran.rc == 0, ran.text()
    msgs = [f["msg"] for f in json.loads(ran.text())["findings"]]
    for name in ("deploy-staging", "deploy-prod"):
        named = [m for m in msgs if f"job {name}, step" in m and "unset" in m]
        assert len(named) == 1, f"with the valves stripped, rule 62 names {name}: {msgs}"


# --- the one walls table: one grammar, one view, two homes ----------------------------------------

TEMPLATE_WALLS = {
    "schema": "member-walls/2",
    "measured_at": {"darwin": "tree:planted-mac", "ubuntu-latest": "run:1 tree:planted-ci"},
    "members": {"mac_only": {"darwin": 5}, "both": {"darwin": 40, "ubuntu-latest": 30}},
}
DRAWER_WALLS = {
    "schema": "member-walls/2",
    "measured_at": {"ubuntu-latest": "run:2 tree:the-products-own"},
    "members": {"ci_only": {"ubuntu-latest": 2}, "both": {"ubuntu-latest": 7}},
}


@pytest.fixture
def walls(scratch: Path) -> Callable[..., Path]:
    """`walls(drawer=False)` plants the template's table, and the product's drawer when asked."""

    def build(drawer: bool = False) -> Path:
        root = scratch / f"walls{len(list(scratch.glob('walls*')))}"
        (root / "scripts" / "local").mkdir(parents=True)
        (root / ledger.WALLS_TEMPLATE).write_text(json.dumps(TEMPLATE_WALLS))
        if drawer:
            (root / ledger.WALLS_DRAWER).write_text(json.dumps(DRAWER_WALLS))
        return root

    return build


def test_the_one_walls_table_prices_the_ci_only_members_where_a_box_reads(
    walls: Callable[..., Path], scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real table's CI-only floor left with GF-7's swept drives; the planted walls price it.
    assert not (ROOT / "scripts" / "gate_member_durations.ci.json").exists(), "the second file"
    marker = scratch / "box-marker"
    marker.write_text("ami-planted\n")
    monkeypatch.setenv("DJB_GATE_BOX_MARKER", str(marker))
    assert R._machine() == "box"
    root = walls()
    box = ledger.durations(root, "box")
    assert (box["mac_only"], box["both"]) == (5, 30), "CI's wall is the nearer machine's"
    assert "mac_only" not in ledger.durations(root, "ubuntu-latest", only=True)
    homes = [root / h for h in R.WALLS_HOMES]
    assert "mac_only" not in R.walls_view(homes, R.CI_MACHINE, only=True), "the selftest partition"


def test_a_products_ci_walls_in_the_drawer_join_the_one_view(walls: Callable[..., Path]) -> None:
    view = ledger.durations(walls(drawer=True), "ubuntu-latest", only=True)
    assert view["ci_only"] == 2, "the member only the product's CI measured"
    assert view["both"] == 7, "the drawer wins over the template's table for its own machine"
    assert "ci_only" not in ledger.durations(walls(), "ubuntu-latest", only=True)


def test_the_one_writer_rewrites_one_machine_column_and_keeps_the_rest(
    walls: Callable[..., Path],
) -> None:
    home = walls() / ledger.WALLS_TEMPLATE
    ledger.store_durations(home, "ubuntu-latest", "run:3 tree:next", {"both": 33, "new_member": 4})
    out = home.read_text()
    assert '"mac_only": {"darwin": 5}' in out
    assert '"both": {"darwin": 40, "ubuntu-latest": 33}' in out
    assert '"new_member": {"ubuntu-latest": 4}' in out
    old = home.with_name("old.json")
    old.write_text(
        json.dumps(
            {"measured_at": "tree:old", "machine": "Darwin 24.6.0", "members": {"legacy": 9}}
        )
    )
    ledger.store_durations(old, "ubuntu-latest", "run:4", {"fresh": 1})
    assert '"legacy": {"darwin": 9}' in old.read_text()
