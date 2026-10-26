"""`python -m quality.djb.rituals.fold` driven over scratch repositories with stub generators."""

# does-not-cover: whether the real generators are right — the stubs stand in for them.
# does-not-cover: that today's engine sentence is the one parsed — only that a moved one refuses.
# narrowed: the_docs_only_delta_no_longer_carries_the_map — its readers half: no drive reads the map

# names, never reads: docs/product/in-flight.md — a scratch world's docs-only commit

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb import ledger
from quality.djb.rituals import fold
from quality.djb.rituals import merge as merge_ritual
from quality.djb.rituals import push as push_ritual
from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/fold.py",
    "quality/djb/ledger.py",
    "scripts/pm_fold.sh",
    "scripts/pm_push.sh",
    "scripts/pm_merge.sh",
    "scripts/fe_gate.sh",
    "scripts/bash_only.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "scripts/test_impact.py",
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.fold import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
#: The steering files and stubs the census must not see, excluded in every world.
EXCLUDED = ("bin/", "pin.act", "secrets.act", "budget.out", "measured-tree.txt", ".wt/")
BUDGETS = """\
service_function_length:
  apps/alpha/services.py: 40 # provenance: the comment that must survive
  apps/beta/services.py: 55

out_schema_fields:
  apps/alpha/schemas.py::ThingOut: 9
"""
BASELINE = (
    '{\n  "version": "1.5.0",\n  "results": {"src/oops.txt": [{"type": "Secret Keyword"}]}\n}\n'
)
#: The byte-pin stand-in, steered by `pin.act` in the folded checkout.
PIN_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
act="$(cat pin.act 2>/dev/null || echo noop)"
case "$act" in
fail)
    echo "stub pin_client: the generator could not produce a client" >&2
    exit 1
    ;;
drift)
    printf '{\\n  "openapi": "3.1.0",\\n  "paths": {"/api/v1/things": {}}\\n}\\n' \\
        >frontend/openapi.json
    printf 'export type paths = { "/api/v1/things": unknown };\\n' \\
        >frontend/src/api/generated/schema.d.ts
    echo "stub pin_client: wrote a regenerated contract"
    ;;
stray)
    echo "a generator wrote here and nobody asked it to" >src/side-effect.txt
    echo "stub pin_client: wrote a side effect"
    ;;
straydir)
    mkdir -p brandnew/deeper
    echo "x" >brandnew/deeper/output.txt
    echo "stub pin_client: wrote into a directory that did not exist"
    ;;
noop) echo "stub pin_client: the committed contract is already current" ;;
esac
"""
#: `uv`, answering the three shapes the fold calls it with; steered by files in the checkout.
UV_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
*"manage.py introspect"*)
    echo '{"stub": "introspect"}'
    ;;
*"detect-secrets scan"*)
    act="$(cat secrets.act 2>/dev/null || echo stamp)"
    case "$act" in
    fail)
        echo "stub detect-secrets: refused" >&2
        exit 1
        ;;
    shift)
        printf '%s\\n' '{' '  "version": "1.5.0",' '  "results": {},' \\
            '  "generated_at": "2026-06-06T06:06:06Z"' '}' >.secrets.baseline
        ;;
    stamp)
        printf '%s\\n' '{' '  "version": "1.5.0",' \\
            '  "results": {"src/oops.txt": [{"type": "Secret Keyword"}]},' \\
            '  "generated_at": "2026-06-06T06:06:06Z"' '}' >.secrets.baseline
        ;;
    nostamp)
        printf '%s\\n' '{' '  "version": "1.6.0",' '  "results": {},' \\
            '  "produced_at": "2026-06-06T06:06:06Z"' '}' >.secrets.baseline
        ;;
    twostamps)
        printf '%s\\n' '{' '  "version": "1.6.0",' '  "results": {},' \\
            '  "generated_at": "2026-06-06T06:06:06Z",' \\
            '  "plugins": {"generated_at": "2026-06-06T06:06:06Z"}' '}' >.secrets.baseline
        ;;
    lanes)
        python3 - <<'PYSCAN'
import hashlib
import json
import os

results = {}
for name in sorted(os.listdir(".")):
    if not name.endswith(".md"):
        continue
    entries = []
    with open(name) as fh:
        for i, line in enumerate(fh, 1):
            if "PLANTED-KEY" in line:
                entries.append({
                    "type": "Secret Keyword",
                    "filename": name,
                    "hashed_secret": hashlib.sha1(line.strip().encode()).hexdigest(),
                    "is_verified": False,
                    "line_number": i,
                })
    if entries:
        results[name] = entries
with open(".secrets.baseline", "w") as fh:
    fh.write(json.dumps(
        {"version": "1.5.0", "results": results,
         "generated_at": "2026-06-06T06:06:06Z"}, indent=2) + "\\n")
PYSCAN
        ;;
    esac
    ;;
*python*)
    if [ -f budget.out ]; then
        cat budget.out
    else
        echo "### budget-check: notes=0 problems=0"
    fi
    ;;
esac
"""


@dataclass
class World:
    """One scratch checkout carrying the four derived files, a victim and the stub generators."""

    repo: Path
    stubs: StubPath
    scratch: Path
    before_head: str = ""
    before_tree: str = ""

    def git(self, *argv: str) -> str:
        """`git -C <repo> <argv>`'s stdout; a failure fails the test."""
        done = subprocess.run(
            ["git", "-C", str(self.repo), *argv], capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
        return done.stdout.strip()

    def commit(self, message: str, *paths: str) -> None:
        """Stage `paths` (every change when none) and commit; the before-coordinates move."""
        self.git("add", *(paths or ("-A",)))
        self.git("commit", "-q", "-m", message)
        self.mark()

    def mark(self) -> None:
        """Record HEAD and its tree as the coordinates a refusal must leave standing."""
        self.before_head = self.git("rev-parse", "HEAD")
        self.before_tree = self.git("rev-parse", "HEAD^{tree}")

    def steer(self, name: str, value: str) -> None:
        """Write one steering file the stubs read."""
        (self.repo / name).write_text(f"{value}\n")

    def env(self, **extra: str) -> dict[str, str]:
        """The fold's environment: the stubs first on PATH, this checkout's package importable."""
        return {
            **os.environ,
            "PATH": f"{self.stubs.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": str(ROOT),
            "DJB_FOLD_PIN_CLIENT": str(self.repo / "frontend/scripts/pin_client.sh"),
            "DJB_FOLD_UV": "uv",
            "DJB_FOLD_GH": str(self.scratch / "no-such-gh-anywhere"),
            "DJB_FOLD_WALLS_HOME": "scripts/gate_member_durations.json",
            **extra,
        }

    def fold(self, *args: str, **extra: str) -> Captured:
        """One fold of the checkout, both streams to a file outside it."""
        sink = self.scratch / f"fold-{self.repo.name}-{len(list(self.scratch.glob('fold-*')))}"
        return run_to(sink, [sys.executable, "-c", ENTRY, *args], self.repo, self.env(**extra))

    def head_unmoved(self) -> None:
        """HEAD is where the world left it."""
        assert self.git("rev-parse", "HEAD") == self.before_head

    def subject(self) -> str:
        """HEAD's subject line."""
        return self.git("log", "-1", "--format=%s")

    def committed(self) -> list[str]:
        """The paths HEAD's commit touched, sorted."""
        return sorted(self.git("show", "--name-only", "--format=", "HEAD").split())

    def status(self) -> str:
        """`git status --porcelain`, verbatim."""
        done = subprocess.run(
            ["git", "-C", str(self.repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.stdout.rstrip("\n")


def build_world(scratch: Path, stubs: StubPath, name: str) -> World:
    """`make_repo`: the derived files, a non-derived victim, the stubs, one base commit."""
    repo = scratch / f"repo-{name}"
    for directory in ("scripts", "frontend/scripts", "frontend/src/api/generated", "quality"):
        (repo / directory).mkdir(parents=True, exist_ok=True)
    (repo / "src").mkdir()
    (repo / "src/oops.txt").write_text("a file no fold has any business touching\n")
    (repo / "frontend/openapi.json").write_text('{\n  "openapi": "3.1.0",\n  "paths": {}\n}\n')
    (repo / "frontend/src/api/generated/schema.d.ts").write_text(
        "export type paths = Record<string, never>;\n"
    )
    (repo / ".secrets.baseline").write_text(BASELINE)
    (repo / "quality/budgets.yaml").write_text(BUDGETS)
    (repo / "manage.py").write_text("print('nothing')\n")
    pin = repo / "frontend/scripts/pin_client.sh"
    pin.write_text(PIN_STUB)
    pin.chmod(0o755)
    (repo / ".gitignore").write_text("/.rung/\n")
    world = World(repo, stubs, scratch)
    for step in (
        ["init", "-q"],
        ["symbolic-ref", "HEAD", "refs/heads/main"],
        ["config", "user.email", "drive@example.invalid"],
        ["config", "user.name", "fold drive"],
        ["config", "commit.gpgsign", "false"],
    ):
        world.git(*step)
    (repo / ".git/info/exclude").write_text("".join(f"{x}\n" for x in EXCLUDED))
    world.commit("base")
    return world


@pytest.fixture
def world(scratch: Path, stub_path: StubPath) -> Iterator[Callable[[str], World]]:
    """`world(name)` builds one scratch checkout; the `uv` stub is planted once for all of them."""
    stub_path.plant("uv", UV_STUB)
    yield lambda name: build_world(scratch, stub_path, name)


# --- the clauses ---------------------------------------------------------------------------------


def test_dirty_tree_is_refused(world: Callable[[str], World]) -> None:
    w = world("dirty")
    with (w.repo / "src/oops.txt").open("a") as sink:
        sink.write("somebody's unsaved work\n")
    said = w.fold()
    assert said.rc == 2
    text = said.text()
    assert "has uncommitted changes" in text
    assert "A fold folds a COMMITTED tree" in text
    assert "Nothing was regenerated and nothing was committed" in text
    w.head_unmoved()


def test_unknown_flag_is_refused(world: Callable[[str], World]) -> None:
    w = world("flag")
    said = w.fold("--fold-everything")
    assert said.rc == 2
    assert "unknown argument '--fold-everything'" in said.text()
    w.head_unmoved()
    said = w.fold("--no-fold")
    assert said.rc == 2
    assert "unknown argument '--no-fold'" in said.text()
    assert "belong to pm_push.sh and" in said.text()
    said = w.fold("--bank")
    assert said.rc == 2
    assert "unknown argument '--bank'" in said.text()
    said = w.fold("--help")
    assert said.rc == 0
    assert "The four clauses" in said.text()
    w.head_unmoved()


def test_piped_stdout_is_refused(world: Callable[[str], World]) -> None:
    w = world("pipe")
    done = subprocess.run(
        [sys.executable, "-c", ENTRY],
        cwd=w.repo,
        env=w.env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "pm_fold refuses pipes" in done.stderr
    w.head_unmoved()


def test_out_of_list_write_is_exit_2(world: Callable[[str], World]) -> None:
    w = world("stray")
    w.steer("pin.act", "stray")
    said = w.fold()
    assert said.rc == 2
    text = said.text()
    assert "modified a file OUTSIDE the derived list" in text
    assert "src/side-effect.txt" in text
    assert "NOTHING WAS COMMITTED" in text
    w.head_unmoved()
    assert (w.repo / "src/side-effect.txt").is_file(), "the evidence was cleaned up"


def test_stray_inside_an_untracked_directory_is_named(world: Callable[[str], World]) -> None:
    w = world("straydir")
    w.steer("pin.act", "straydir")
    said = w.fold()
    assert said.rc == 2
    assert "brandnew/deeper/output.txt" in said.text()
    w.head_unmoved()


def test_nothing_to_fold_makes_no_commit(world: Callable[[str], World]) -> None:
    w = world("nothing")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "NOTHING TO FOLD" in said.text()
    assert "already agrees with this checkout" in said.text()
    w.head_unmoved()
    assert w.status() == ""


def test_a_checkout_with_nothing_to_fold_at_all_is_could_not_look(
    world: Callable[[str], World],
) -> None:
    w = world("barren")
    w.git("rm", "-q", "-r", "frontend", "quality", ".secrets.baseline", "manage.py")
    w.commit("strip everything a fold folds")
    said = w.fold()
    assert said.rc == 2
    assert "a reader looking at the wrong tree" in said.text()
    w.head_unmoved()


def test_the_exit_guard_is_the_real_scripts_own(scratch: Path) -> None:
    def dies(_: fold.Fold) -> None:
        raise RuntimeError("a name nobody set")

    sink = scratch / "guard.err"
    with sink.open("w") as errors:
        saved = sys.stderr
        sys.stderr = errors
        try:
            rc = fold.main([], root=scratch, hook=dies)
        finally:
            sys.stderr = saved
    text = sink.read_text()
    assert rc == 2
    assert "DIED part-way" in text
    assert "NOTHING THIS RUN PRINTED IS A VERDICT" in text
    assert "a name nobody set" in text


# --- (c) the secret baseline ---------------------------------------------------------------------


def test_the_fold_restores_on_no_shift_from_a_stampless_file(
    world: Callable[[str], World],
) -> None:
    w = world("stamp")
    w.steer("secrets.act", "stamp")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "only the generated_at stamp the scan writes" in said.text()
    assert "NOTHING TO FOLD" in said.text()
    w.head_unmoved()
    assert (w.repo / ".secrets.baseline").read_text() == BASELINE


def test_the_fold_commits_a_stampless_baseline_on_a_real_shift(
    world: Callable[[str], World],
) -> None:
    w = world("shift")
    w.steer("secrets.act", "shift")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "BASELINE SHIFTED" in said.text()
    assert w.git("rev-parse", "HEAD") != w.before_head
    assert w.subject() == "fold: baseline shifted"
    assert w.committed() == [".secrets.baseline"]
    assert w.status() == ""
    committed = w.git("show", "HEAD:.secrets.baseline")
    assert '"generated_at"' not in committed
    assert "src/oops.txt" not in committed
    json.loads(committed)


def test_an_unrecognised_stamp_shape_is_refused(world: Callable[[str], World]) -> None:
    w = world("noshape")
    w.steer("secrets.act", "nostamp")
    said = w.fold()
    assert said.rc == 2
    assert "generated_at line(s)" in said.text()
    assert "format has moved under this strip" in said.text()
    w.head_unmoved()
    w = world("twoshapes")
    w.steer("secrets.act", "twostamps")
    said = w.fold()
    assert said.rc == 2
    assert "2 generated_at line(s)" in said.text()
    w.head_unmoved()


def test_a_committed_stamp_is_stripped_even_when_nothing_shifted(
    world: Callable[[str], World],
) -> None:
    w = world("stamped")
    (w.repo / ".secrets.baseline").write_text(
        '{\n  "version": "1.5.0",\n'
        '  "results": {"src/oops.txt": [{"type": "Secret Keyword"}]},\n'
        '  "generated_at": "2026-01-01T00:00:00Z"\n}\n'
    )
    w.commit("a baseline from before the strip", ".secrets.baseline")
    w.steer("secrets.act", "stamp")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "the always-moving fields were removed" in said.text()
    assert "(1 generated_at, 0 line_number)" in said.text()
    assert w.git("rev-parse", "HEAD") != w.before_head
    assert '"generated_at"' not in w.git("show", "HEAD:.secrets.baseline")
    assert w.status() == ""


def _two_lane_merge(scratch: Path, stamped: bool) -> tuple[int, Path, str]:
    """Two lanes each add a result to one baseline; the merge's exit, the file and its log."""
    repo = scratch / f"merge-{'stamped' if stamped else 'stampless'}"
    repo.mkdir()

    def git(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=False
        )

    git("init", "-q", "-b", "main", ".")
    git("config", "user.email", "drive@example.invalid")
    git("config", "user.name", "fold drive")
    git("config", "commit.gpgsign", "false")
    entry = {
        "type": "Secret Keyword",
        "hashed_secret": "1" * 40,
        "is_verified": False,
        "line_number": 1,
    }
    base: dict[str, object] = {"version": "1.5.0", "results": {"middle.md": [entry]}}
    if stamped:
        base["generated_at"] = "2026-01-01T00:00:00Z"
    path = repo / ".secrets.baseline"
    path.write_text(json.dumps(base, indent=2) + "\n")
    git("add", ".secrets.baseline")
    git("commit", "-q", "-m", "base")
    for lane in ("x", "y"):
        git("checkout", "-q", "-b", lane, "main")
        data = json.loads(path.read_text())
        mine = [{**entry, "hashed_secret": ("2" if lane == "x" else "3") * 40}]
        results = data["results"]
        data["results"] = (
            {"aaa_top.md": mine, **results} if lane == "x" else {**results, "zzz_bottom.md": mine}
        )
        if stamped:
            data["generated_at"] = f"2026-09-1{1 if lane == 'x' else 2}T00:00:00Z"
        path.write_text(json.dumps(data, indent=2) + "\n")
        git("commit", "-q", "-am", f"lane {lane}")
    git("checkout", "-q", "x")
    merged = git("merge", "--no-edit", "y")
    return merged.returncode, path, merged.stdout + merged.stderr


def test_two_lanes_baselines_merge_clean_without_the_stamp(scratch: Path) -> None:
    rc, path, _ = _two_lane_merge(scratch, stamped=False)
    assert rc == 0
    text = path.read_text()
    assert "<<<<<<<" not in text
    assert "aaa_top.md" in text and "zzz_bottom.md" in text


def test_the_stamp_is_what_conflicted(scratch: Path) -> None:
    rc, path, log = _two_lane_merge(scratch, stamped=True)
    assert rc == 1
    assert "CONFLICT (content): Merge conflict in .secrets.baseline" in log
    text = path.read_text()
    assert "generated_at" in text
    assert sum(1 for line in text.splitlines() if line.startswith("<<<<<<<")) == 1
    assert "aaa_top.md" in text and "zzz_bottom.md" in text


def test_two_lanes_baselines_merge_clean_without_line_numbers(
    scratch: Path, stub_path: StubPath
) -> None:
    stub_path.plant("uv", UV_STUB)
    repo = scratch / "fold-merge"
    repo.mkdir()
    lanes = World(repo, stub_path, scratch)
    for step in (
        ["init", "-q"],
        ["symbolic-ref", "HEAD", "refs/heads/main"],
        ["config", "user.email", "drive@example.invalid"],
        ["config", "user.name", "fold drive"],
        ["config", "commit.gpgsign", "false"],
    ):
        lanes.git(*step)
    (repo / "mmm_keys.md").write_text(
        "".join(f"body line {i}\n" for i in range(1, 41))
        + "alpha PLANTED-KEY one\nalpha PLANTED-KEY two\n"
    )
    (repo / "nnn_other.md").write_text("beta PLANTED-KEY three\n")
    (repo / ".git/info/exclude").write_text("bin/\nsecrets.act\n")
    (repo / "secrets.act").write_text("lanes\n")
    seeded = subprocess.run(
        [str(stub_path.bin / "uv"), "run", "detect-secrets", "scan"], cwd=repo, check=False
    )
    assert seeded.returncode == 0
    lanes.commit("base: the baseline records the three keys")
    assert lanes.fold().rc == 0
    lanes.git("checkout", "-q", "-b", "lane-a", "main")
    keys = repo / "mmm_keys.md"
    keys.write_text("filler-a\n" * 10 + keys.read_text())
    (repo / "nnn_other.md").write_text("nothing here any more\n")
    lanes.commit("lane A: ten lines at the top, and the other file's key gone")
    assert lanes.fold().rc == 0
    lanes.git("checkout", "-q", "-b", "lane-b", "main")
    rows = keys.read_text().splitlines(True)
    rows = [row for row in rows if "PLANTED-KEY one" not in row]
    keys.write_text("".join(rows[:30] + ["filler-b\n"] * 3 + rows[30:]))
    lanes.commit("lane B: three lines far from lane A's, and key one gone")
    assert lanes.fold().rc == 0
    lanes.git("checkout", "-q", "lane-a")
    merged = subprocess.run(
        ["git", "-C", str(repo), "merge", "--no-edit", "lane-b"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert merged.returncode == 0, merged.stdout + merged.stderr
    text = (repo / ".secrets.baseline").read_text()
    assert "<<<<<<<" not in text
    assert '"line_number"' not in text
    assert "mmm_keys.md" in text and "nnn_other.md" not in text
    assert len(json.loads(text)["results"]["mmm_keys.md"]) == 1


def test_only_secrets_no_commit_rescans_and_stages_nothing(world: Callable[[str], World]) -> None:
    w = world("only")
    w.steer("secrets.act", "shift")
    said = w.fold("--only", "secrets", "--no-commit")
    assert said.rc == 0, said.text()
    text = said.text()
    assert "--only secrets does not name this step" in text
    assert "BASELINE SHIFTED" in text
    assert "pm_fold: --no-commit" in text
    w.head_unmoved()
    assert w.git("diff", "--cached", "--name-only") == ""
    assert w.status() == " M .secrets.baseline"
    baseline = (w.repo / ".secrets.baseline").read_text()
    assert '"generated_at"' not in baseline and '"line_number"' not in baseline
    said = w.fold("--only", "secretz", "--no-commit")
    assert said.rc == 2
    assert "--only names 'secretz'" in said.text()
    said = w.fold("--no-commit")
    assert said.rc == 2
    assert "legal only with --only" in said.text()


# --- (a) the contract and (b) the schema dump ----------------------------------------------------


def test_contract_drift_is_one_commit_of_derived_paths(world: Callable[[str], World]) -> None:
    w = world("contract")
    w.steer("pin.act", "drift")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert w.subject() == "fold: contract regenerated"
    assert w.committed() == ["frontend/openapi.json", "frontend/src/api/generated/schema.d.ts"]
    body = w.git("log", "-1", "--format=%b")
    assert f"Pre-fold tree: {w.before_tree}" in body
    assert f"Pre-fold HEAD: {w.before_head}" in body
    assert "ceiling is never raised here" in body
    assert w.status() == ""
    assert (w.repo / ".rung/introspect.json").is_file(), "the schema dump was not regenerated"
    assert ".rung/introspect.json" not in w.committed()


def test_an_unignored_rung_dir_is_skipped(world: Callable[[str], World]) -> None:
    w = world("unignored")
    w.git("rm", "-q", ".gitignore")
    w.commit("a checkout that does not ignore .rung/")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "is NOT git-ignored in this checkout" in said.text()
    assert "modified a file OUTSIDE the derived list" not in said.text()
    assert not (w.repo / ".rung/introspect.json").exists(), "it wrote the dump anyway"
    w.head_unmoved()


def test_a_failed_generator_commits_nothing(world: Callable[[str], World]) -> None:
    w = world("genfail")
    w.steer("pin.act", "fail")
    said = w.fold()
    assert said.rc == 2
    assert "the client generator exited 1" in said.text()
    assert "Nothing was committed" in said.text()
    w.head_unmoved()


def test_the_folded_tree_is_the_tree_a_verdict_keys_on(world: Callable[[str], World]) -> None:
    w = world("keyed")
    w.steer("pin.act", "drift")
    assert w.fold().rc == 0
    measured = ledger.measured_tree(w.repo)
    assert measured == w.git("rev-parse", "HEAD^{tree}")
    assert measured != w.before_tree


# --- (d) the budgets: clause 3 -------------------------------------------------------------------

LOWER = "a human may commit the lower number:"
ALPHA_31 = (
    "budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) "
    f"measured 31, below its ceiling 40 — {LOWER}\n  apps/alpha/services.py: 31\n"
)


def summary(notes: int) -> str:
    """The engine reader's one summary line."""
    return f"### budget-check: notes={notes} problems=0\n"


def test_a_budget_raise_is_never_applied(world: Callable[[str], World]) -> None:
    w = world("raise")
    (w.repo / "budget.out").write_text(
        "budget: service_function_length apps/alpha/services.py — do_thing (lines 10-99) grew to "
        "91, past the recorded ceiling 40 — shrink it, or raise the ceiling in "
        "quality/budgets.yaml in a diff a reviewer sees. The line to paste, verbatim:\n"
        "  apps/alpha/services.py: 91\n"
        "budget: out_schema_fields has no recorded ceiling for apps/gamma/schemas.py::NewOut "
        "(measured 4) — a new subject fails until a human measures it and commits the number. "
        "The line to paste under `out_schema_fields:` in quality/budgets.yaml:\n"
        "  apps/gamma/schemas.py::NewOut: 4\n" + summary(0)
    )
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "raise is a decision that stays a human diff" in said.text()
    assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS
    assert "NOTHING TO FOLD" in said.text()
    w.head_unmoved()


def test_a_budget_lowering_is_applied_and_committed(world: Callable[[str], World]) -> None:
    w = world("lower")
    (w.repo / "budget.out").write_text(
        ALPHA_31
        + "budget note: out_schema_fields apps/alpha/schemas.py::ThingOut — ThingOut (lines "
        f"3-12) measured 6, below its ceiling 9 — {LOWER}\n"
        "  apps/alpha/schemas.py::ThingOut: 6\n" + summary(2)
    )
    said = w.fold()
    assert said.rc == 0, said.text()
    assert w.subject() == "fold: 2 budgets lowered"
    new = (w.repo / "quality/budgets.yaml").read_text()
    assert "  apps/alpha/services.py: 31" in new
    assert "31 # provenance: the comment that must survive" in new
    assert "  apps/alpha/schemas.py::ThingOut: 6" in new
    assert "  apps/beta/services.py: 55" in new
    assert w.committed() == ["quality/budgets.yaml"]


def test_a_lowering_for_an_absent_key_is_refused(world: Callable[[str], World]) -> None:
    w = world("miss")
    (w.repo / "budget.out").write_text(
        "budget note: service_function_length apps/ghost/services.py — vanish (lines 1-2) "
        f"measured 2, below its ceiling 9 — {LOWER}\n  apps/ghost/services.py: 2\n" + summary(1)
    )
    said = w.fold()
    assert said.rc == 2
    assert "MISS service_function_length apps/ghost/services.py" in said.text()
    assert "how a floor stops being a floor" in said.text()
    assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS
    w.head_unmoved()


def test_a_lowering_note_above_the_ceiling_is_refused(world: Callable[[str], World]) -> None:
    for name, number in (("above", "900"), ("equal", "40")):
        w = world(name)
        (w.repo / "budget.out").write_text(
            "budget note: service_function_length apps/alpha/services.py — do_thing (lines "
            f"10-40) measured {number}, below its ceiling 40 — {LOWER}\n"
            f"  apps/alpha/services.py: {number}\n" + summary(1)
        )
        said = w.fold()
        assert said.rc == 2
        text = said.text()
        assert f"service_function_length apps/alpha/services.py: 40 -> {number}" in text
        assert "never raises a ceiling" in text
        assert "not BELOW the ceiling" in text
        assert "ceiling(s) lowered" not in text
        assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS
        w.head_unmoved()


def test_an_unreadable_ceiling_says_it_cannot_compare(world: Callable[[str], World]) -> None:
    w = world("unreadable")
    unreadable = "service_function_length:\n  apps/alpha/services.py: forty\n"
    (w.repo / "quality/budgets.yaml").write_text(unreadable)
    w.commit("a ceiling nobody can compare against", "quality/budgets.yaml")
    (w.repo / "budget.out").write_text(ALPHA_31 + summary(1))
    said = w.fold()
    assert said.rc == 2
    text = said.text()
    assert 'the ceiling standing in the file is "forty", which is not a number -> 31' in text
    assert "so the fold cannot tell lowering from raising and refuses to guess" in text
    assert "not BELOW the ceiling" not in text
    assert "ceiling(s) lowered" not in text
    assert (w.repo / "quality/budgets.yaml").read_text() == unreadable
    w.head_unmoved()


def test_an_inline_comment_keeps_its_own_spacing(world: Callable[[str], World]) -> None:
    w = world("spacing")
    before = BUDGETS.replace(
        "40 # provenance: the comment that must survive",
        "40   # provenance: three spaces out, and it stays there",
    )
    (w.repo / "quality/budgets.yaml").write_text(before)
    w.commit("a ceiling line whose comment is aligned", "quality/budgets.yaml")
    (w.repo / "budget.out").write_text(ALPHA_31 + summary(1))
    said = w.fold()
    assert said.rc == 0, said.text()
    assert w.subject() == "fold: 1 budgets lowered"
    after = (w.repo / "quality/budgets.yaml").read_text()
    old, new = before.splitlines(), after.splitlines()
    differs = [(a, b) for a, b in zip(old, new, strict=True) if a != b]
    assert len(differs) == 1
    assert differs[0][1] == differs[0][0].replace(" 40 ", " 31 ")
    assert "31   # provenance: three spaces out" in after


def test_a_moved_sentence_is_refused_not_read_as_nothing(world: Callable[[str], World]) -> None:
    w = world("moved")
    (w.repo / "budget.out").write_text(
        ALPHA_31.replace(LOWER, "a person may record the smaller value:") + summary(1)
    )
    said = w.fold()
    assert said.rc == 2
    assert "wrote 1 note(s) and this parser recognised 0" in said.text()
    assert "sentence has moved and this file has not" in said.text()
    w.head_unmoved()


def test_a_missing_summary_line_is_refused(world: Callable[[str], World]) -> None:
    w = world("nosummary")
    (w.repo / "budget.out").write_text(
        "something the engine printed and this parser does not know\n"
    )
    said = w.fold()
    assert said.rc == 2
    assert "printed 0 summary line(s), not exactly one" in said.text()
    w.head_unmoved()


def test_the_combined_subject_joins_with_the_separator(world: Callable[[str], World]) -> None:
    w = world("combined")
    w.steer("pin.act", "drift")
    w.steer("secrets.act", "shift")
    (w.repo / "budget.out").write_text(ALPHA_31 + summary(1))
    said = w.fold()
    assert said.rc == 0, said.text()
    assert w.subject() == "fold: contract regenerated · baseline shifted · 1 budgets lowered"
    assert w.committed() == [
        ".secrets.baseline",
        "frontend/openapi.json",
        "frontend/src/api/generated/schema.d.ts",
        "quality/budgets.yaml",
    ]
    assert w.status() == ""


# --- (local) the product's drawer ----------------------------------------------------------------

DECL_OPEN = "# " + fold.WRITES_BEGIN
DECL_ENTRY = "# product/catalog.json — the product's own generated catalogue"
DECL_CLOSE = "# " + fold.WRITES_END
GATE_OPEN = "# >>> " + fold.GATE_SENTINEL + " >>>"
GATE_CLOSE = "# <<< " + fold.GATE_SENTINEL + " <<<"
REGENERATE = 'printf "the REGENERATED product artefact\\n" > product/catalog.json'


def step_body(*lines: str) -> str:
    """A drawer step: the shebang, `set -euo pipefail`, then `lines`."""
    return "".join(f"{x}\n" for x in ("#!/usr/bin/env bash", "set -euo pipefail", *lines))


def plant_local_step(w: World, name: str, *lines: str, commit: bool = True) -> Path:
    """`scripts/local/fold.d/<name>.sh` and the product file it owns; committed unless told not."""
    (w.repo / "scripts/local/fold.d").mkdir(parents=True, exist_ok=True)
    (w.repo / "product").mkdir(exist_ok=True)
    (w.repo / "product/catalog.json").write_text("the OLD product artefact\n")
    step = w.repo / f"scripts/local/fold.d/{name}.sh"
    step.write_text(step_body(*lines))
    step.chmod(0o755)
    if commit:
        w.commit("the product's drawer and its derived file")
    return step


def test_a_local_fold_step_runs_and_commits_only_what_it_declared(
    world: Callable[[str], World],
) -> None:
    w = world("localstep")
    plant_local_step(
        w,
        "50-catalog",
        DECL_OPEN,
        DECL_ENTRY,
        DECL_CLOSE,
        REGENERATE,
        'echo "local step: regenerated product/catalog.json"',
    )
    said = w.fold()
    assert said.rc == 0, said.text()
    text = said.text()
    assert "== (local) 50-catalog" in text
    assert "local step: regenerated product/catalog.json" in text
    assert "changed  product/catalog.json" in text
    assert "declared path(s) regenerated" in text
    assert w.committed() == ["product/catalog.json"]
    assert w.status() == ""
    assert w.git("show", "HEAD:product/catalog.json") == "the REGENERATED product artefact"


def test_a_local_steps_undeclared_write_is_refused_by_name(world: Callable[[str], World]) -> None:
    w = world("localstray")
    plant_local_step(
        w,
        "50-catalog",
        DECL_OPEN,
        DECL_ENTRY,
        DECL_CLOSE,
        'printf "new\\n" > product/catalog.json',
        'printf "nobody wrote this down\\n" > product/sneaky.json',
    )
    said = w.fold()
    assert said.rc == 2
    text = said.text()
    assert "the local step '50-catalog' wrote a path it did not declare" in text
    assert "product/sneaky.json" in text and "product/catalog.json" in text
    w.head_unmoved()
    assert "product/sneaky.json" in w.status()


def test_an_absent_fold_drawer_is_byte_identical(world: Callable[[str], World]) -> None:
    w = world("drawerabsent")
    absent = w.fold()
    assert absent.rc == 0, absent.text()
    assert "== (local)" not in absent.text()
    (w.repo / "scripts/local/fold.d").mkdir(parents=True)
    empty = w.fold()
    assert empty.text() == absent.text()


def test_only_addresses_a_local_step_by_name(world: Callable[[str], World]) -> None:
    w = world("onlylocal")
    plant_local_step(w, "50-catalog", DECL_OPEN, DECL_ENTRY, DECL_CLOSE, REGENERATE)
    said = w.fold("--only", "50-catalog")
    assert said.rc == 0, said.text()
    assert "skipped — --only 50-catalog does not name this step" in said.text()
    assert "changed  product/catalog.json" in said.text()
    said = w.fold("--only", "nosuchstep")
    assert said.rc == 2
    assert "--only names 'nosuchstep', which is not a step of this fold" in said.text()
    assert "contract schema secrets budgets" in said.text()
    assert "scripts/local/fold.d/ adds: 50-catalog" in said.text()


def test_a_malformed_local_step_is_exit_2_by_name(world: Callable[[str], World]) -> None:
    w = world("drawerchmod")
    step = plant_local_step(w, "50-catalog", DECL_OPEN, DECL_ENTRY, DECL_CLOSE, commit=False)
    step.chmod(0o644)
    w.commit("a step nobody made executable")
    said = w.fold()
    assert said.rc == 2
    assert "scripts/local/fold.d/50-catalog.sh is not executable" in said.text()

    w = world("drawernodecl")
    plant_local_step(w, "50-catalog", 'printf "new\\n" > product/catalog.json')
    said = w.fold()
    assert said.rc == 2
    assert "scripts/local/fold.d/50-catalog.sh declares no written paths" in said.text()

    w = world("drawerprose")
    plant_local_step(
        w, "50-catalog", DECL_OPEN, "# this block holds a sentence instead of an entry", DECL_CLOSE
    )
    said = w.fold()
    assert said.rc == 2
    assert "is not `<path> — <reason>`" in said.text()
    assert "the declaration in scripts/local/fold.d/50-catalog.sh could not be read" in said.text()

    w = world("drawercollide")
    plant_local_step(w, "secrets", DECL_OPEN, DECL_ENTRY, DECL_CLOSE)
    said = w.fold()
    assert said.rc == 2
    assert (
        "scripts/local/fold.d/secrets.sh takes the name of one of this fold's own steps"
        in said.text()
    )


def test_a_declared_path_in_a_product_file_needs_no_edit_to_the_fold(
    world: Callable[[str], World],
) -> None:
    w = world("productdecl")
    events = w.repo / "frontend/src/api/generated/events.ts"
    events.write_text("export const events = [];\n")
    (w.repo / "frontend/scripts/pin_client.sh").write_text(
        step_body(
            "# The product's client generator, declaring its own extra output.",
            DECL_OPEN,
            "# frontend/src/api/generated/events.ts — this product's generated event client",
            DECL_CLOSE,
            'printf "export const events = [\\"thing.created\\"];\\n" > '
            "frontend/src/api/generated/events.ts",
            'echo "stub pin_client: regenerated the product\'s client"',
        )
    )
    w.commit("the product's extra generated client, declared by its generator")
    said = w.fold()
    assert said.rc == 0, said.text()
    assert "changed  frontend/src/api/generated/events.ts" in said.text()
    assert "modified a file OUTSIDE the derived list" not in said.text()
    assert w.committed() == ["frontend/src/api/generated/events.ts"]
    assert ledger.derived_tree_paths(w.repo) == [], "a fold-written path left the verdict key"


def test_a_local_step_reaching_for_the_gates_grammar_is_refused(
    world: Callable[[str], World],
) -> None:
    w = world("wronggrammar")
    step = plant_local_step(
        w, "50-catalog", GATE_OPEN, DECL_ENTRY, GATE_CLOSE, 'printf "new\\n" > product/catalog.json'
    )
    line = next(
        n for n, x in enumerate(step.read_text().splitlines(), 1) if fold.GATE_SENTINEL in x
    )
    said = w.fold()
    assert said.rc == 2
    text = said.text()
    assert (
        f"scripts/local/fold.d/50-catalog.sh:{line} spells the GATE's declaration sentinel" in text
    )
    assert "subtracts a path from the verdict key" in text
    assert "fold-writes" in text


def test_an_untracked_local_step_does_not_run(world: Callable[[str], World]) -> None:
    w = world("nottracked")
    (w.repo / "product").mkdir()
    (w.repo / "product/catalog.json").write_text("the OLD product artefact\n")
    w.commit("the derived file, tracked; the step is not", "product/catalog.json")
    (w.repo / "scripts/local/fold.d").mkdir(parents=True)
    step = w.repo / "scripts/local/fold.d/50-catalog.sh"
    step.write_text(step_body(DECL_OPEN, DECL_ENTRY, DECL_CLOSE, REGENERATE))
    step.chmod(0o755)
    said = w.fold()
    assert said.rc == 2
    assert "scripts/local/fold.d/50-catalog.sh is not tracked by git" in said.text()
    assert (w.repo / "product/catalog.json").read_text() == "the OLD product artefact\n"


def test_a_local_step_that_deletes_its_declared_path_is_refused(
    world: Callable[[str], World],
) -> None:
    w = world("deletes")
    plant_local_step(
        w, "50-catalog", DECL_OPEN, DECL_ENTRY, DECL_CLOSE, "rm -f product/catalog.json"
    )
    said = w.fold()
    assert said.rc == 2
    assert "the local step '50-catalog' DELETED a path it declares" in said.text()
    assert "product/catalog.json" in said.text()
    assert "pm_fold: committing" not in said.text()
    w.head_unmoved()


def test_two_local_steps_declaring_one_path_are_refused_by_both_names(
    world: Callable[[str], World],
) -> None:
    w = world("duplicate")
    plant_local_step(
        w, "50-catalog", DECL_OPEN, DECL_ENTRY, DECL_CLOSE, 'printf "a\\n" > product/catalog.json'
    )
    second = w.repo / "scripts/local/fold.d/60-also-catalog.sh"
    second.write_text(
        step_body(DECL_OPEN, DECL_ENTRY, DECL_CLOSE, 'printf "b\\n" > product/catalog.json')
    )
    second.chmod(0o755)
    w.commit("a second step with a claim on the same path")
    said = w.fold()
    assert said.rc == 2
    text = said.text()
    assert "two local fold steps declare 'product/catalog.json'" in text
    assert "scripts/local/fold.d/50-catalog.sh" in text
    assert "scripts/local/fold.d/60-also-catalog.sh" in text


# --- (f) the map: absorbed, harvested, pruned ----------------------------------------------------

MAP = "scripts/test_impact.json"
OLD_TREE = "0" * 40
NEW_TREE = "1" * 40
NIGHT_MAP = (
    '{\n  "generated": {"tree": "tree:nightly00000"},\n  "tests": {},\n  "unmapped": {}\n}\n'
)


def map_world(world: Callable[[str], World], name: str) -> World:
    """`map_repo`: a world carrying a COMMITTED acceptance map."""
    w = world(name)
    (w.repo / MAP).write_text(f'{{\n  "tree": "{OLD_TREE}",\n  "tests": {{}}\n}}\n')
    w.commit("the acceptance map, as the last bank left it", MAP)
    return w


def map_rewrite(w: World) -> None:
    """What the acceptance box does at the end of a bank."""
    (w.repo / MAP).write_text(
        f'{{\n  "tree": "{NEW_TREE}",\n  "tests": {{"apps/widgets/models.py": '
        '["apps/widgets/tests/test_thing.py::test_it"]}\n}\n'
    )


def map_night(w: World, directory: Path, age: int, rc: int, map_rc: int = 0) -> Path:
    """A nightly's `leak-proof/1` record `age` seconds old, and its map when `map_rc` is 0."""
    directory.mkdir(parents=True, exist_ok=True)
    at = ledger.ci_stamp(int(time.time()) - age)
    head, tree = w.git("rev-parse", "HEAD"), w.git("rev-parse", "HEAD^{tree}")
    (directory / "leak_proof.txt").write_text(
        f"schema=leak-proof/1 at={at} commit={head} tree={tree} seed=99 pass1=0 pass2={rc} "
        f"map={map_rc} rc={rc} run=555 attempt=1 where=nightly\n"
    )
    if map_rc == 0:
        (directory / "test_impact.json").write_text(NIGHT_MAP)
    return directory


def test_a_rewritten_acceptance_map_is_absorbed_and_committed(
    world: Callable[[str], World],
) -> None:
    w = map_world(world, "map")
    map_rewrite(w)
    said = w.fold()
    assert said.rc == 0, said.text()
    text = said.text()
    assert "absorbed       scripts/test_impact.json" in text
    assert "written from outside this checkout" in text
    assert "acceptance map absorbed" in text
    assert "1 declared path(s) regenerated" not in text
    assert w.committed() == [MAP]
    assert w.git("rev-parse", "HEAD") != w.before_head
    assert NEW_TREE in w.git("show", f"HEAD:{MAP}")
    assert w.status() == ""


def test_a_dirty_tree_beside_the_map_is_still_refused(world: Callable[[str], World]) -> None:
    w = map_world(world, "mapdirty")
    map_rewrite(w)
    with (w.repo / "src/oops.txt").open("a") as sink:
        sink.write("somebody's unsaved work\n")
    said = w.fold()
    assert said.rc == 2
    assert "has uncommitted changes" in said.text()
    assert "src/oops.txt" in said.text()
    assert " M scripts/test_impact.json" not in said.text()
    w.head_unmoved()


def test_a_deleted_acceptance_map_is_still_a_dirty_tree(world: Callable[[str], World]) -> None:
    w = map_world(world, "mapgone")
    (w.repo / MAP).unlink()
    said = w.fold()
    assert said.rc == 2
    assert "has uncommitted changes" in said.text()
    assert MAP in said.text()
    w.head_unmoved()


def test_the_docs_only_delta_no_longer_carries_the_map(world: Callable[[str], World]) -> None:
    w = map_world(world, "mapdelta")
    map_rewrite(w)
    assert w.fold().rc == 0
    banked = w.git("rev-parse", "HEAD^{tree}")
    inflight = "docs/product/in-flight.md"
    (w.repo / "docs/product").mkdir(parents=True)
    (w.repo / inflight).write_text("the cycle ledger, as a docs-only push carries it\n")
    w.commit("ledger [docs-only]", inflight)
    delta = w.git("diff-tree", "-r", "--name-only", banked, "HEAD^{tree}")
    assert NEW_TREE in w.git("show", f"{banked}:{MAP}")
    assert delta == inflight


def map_fold(w: World, **extra: str) -> Captured:
    """`--only map`, the night given as a directory or fetched through a planted `gh`."""
    return w.fold("--only", "map", **extra)


def test_map_prunes_ids_the_collection_no_longer_holds(world: Callable[[str], World]) -> None:
    w = map_world(world, "prune")
    shutil.copyfile(ROOT / "scripts/test_impact.py", w.repo / "scripts/test_impact.py")
    (w.repo / MAP).write_text(
        '{\n  "generated": {\n    "tree": "tree:0"\n  },\n  "tests": {\n'
        '    "apps/zzz_mapped/tests/test_a.py::test_kept": ["apps/zzz_mapped/models.py"],\n'
        '    "apps/zzz_mapped/tests/test_a.py::test_renamed_away": '
        '["apps/zzz_mapped/models.py"]\n  },\n  "unmapped": {}\n}\n'
    )
    w.commit("a map with one entry the collection no longer holds")
    collected = w.scratch / "collected.txt"
    collected.write_text(
        "apps/zzz_mapped/tests/test_a.py::test_kept\n\n1 test collected in 0.01s\n"
    )
    night = map_night(w, w.scratch / "night-prune", 3600, 1)
    said = map_fold(w, DJB_FOLD_MAP_DIR=str(night), DJB_FOLD_MAP_COLLECTED=str(collected))
    assert said.rc == 0, said.text()
    assert (
        "map: pruned 1 ids no longer collected — apps/zzz_mapped/tests/test_a.py::test_renamed_away"
        in said.text()
    )
    assert "map pruned (1 ids no longer collected)" in said.text()
    committed = w.git("show", f"HEAD:{MAP}")
    assert "test_renamed_away" not in committed and "test_kept" in committed
    w.mark()
    said = map_fold(w, DJB_FOLD_MAP_DIR=str(night), DJB_FOLD_MAP_COLLECTED=str(collected))
    assert said.rc == 0, said.text()
    assert "map: every entry is collected (1) — nothing pruned" in said.text()
    w.head_unmoved()


def test_map_harvests_a_green_night_and_leaves_red_stale_and_none_said(
    world: Callable[[str], World],
) -> None:
    w = map_world(world, "green")
    night = map_night(w, w.scratch / "night-green", 3600, 0)
    said = map_fold(w, DJB_FOLD_MAP_DIR=str(night))
    assert said.rc == 0, said.text()
    assert "map: harvested nightly run (given) (nightly:" in said.text()
    assert "nightly map harvested" in said.text()
    assert w.committed() == [MAP]
    assert "tree:nightly00000" in w.git("show", f"HEAD:{MAP}")
    w.mark()
    said = map_fold(w, DJB_FOLD_MAP_DIR=str(night))
    assert said.rc == 0
    assert "the committed map already says exactly this" in said.text()
    w.head_unmoved()
    for name, age, rc, map_rc, needle in (
        (
            "red",
            3600,
            1,
            0,
            "map: NOT harvested — the latest nightly (run (given)) is red (nightly:",
        ),
        ("stale", 172800, 0, 0, "is older than 24 h (nightly:stale:"),
        ("nomap", 3600, 0, 1, "is green and published no map (map=1)"),
    ):
        w = map_world(world, name)
        before = (w.repo / MAP).read_text()
        night = map_night(w, w.scratch / f"night-{name}", age, rc, map_rc)
        said = map_fold(w, DJB_FOLD_MAP_DIR=str(night))
        assert said.rc == 0, said.text()
        assert needle in said.text()
        assert (w.repo / MAP).read_text() == before
        w.head_unmoved()


NIGHTLY_GH = """\
#!/usr/bin/env bash
D="{home}"
[ ! -f "$D/fail" ] || {{ echo "stub gh: HTTP 401: Bad credentials" >&2; exit 1; }}
case "${{1:-}} ${{2:-}}" in
"run list") cat "$D/list.out" 2>/dev/null; exit 0 ;;
"run view") cat "$D/view"; exit 0 ;;
"run download")
    dir=""
    while [ "$#" -gt 0 ]; do [ "$1" != "--dir" ] || dir="$2"; shift; done
    [ -d "$D/art" ] || {{ echo "no valid artifacts found to download" >&2; exit 1; }}
    mkdir -p "$dir"
    cp "$D/art/"* "$dir/"
    exit 0
    ;;
esac
echo "stub gh: unexpected $*" >&2
exit 1
"""


def nightly_gh(w: World) -> Path:
    """A `gh` answering the nightly's three questions out of a directory beside the world."""
    home = w.scratch / f"{w.repo.name}-ngh"
    home.mkdir()
    (home / "list.out").write_text("555\n")
    (home / "view").write_text("completed 1\n")
    gh = home / "gh"
    gh.write_text(NIGHTLY_GH.format(home=home))
    gh.chmod(0o755)
    return gh


def test_map_reads_the_night_through_gh_and_could_not_look_is_said(
    world: Callable[[str], World],
) -> None:
    w = map_world(world, "gh")
    gh = nightly_gh(w)
    map_night(w, gh.parent / "art", 3600, 0)
    said = map_fold(w, DJB_FOLD_GH=str(gh))
    assert said.rc == 0, said.text()
    assert "map: harvested nightly run 555 (nightly:" in said.text()
    assert "tree:nightly00000" in w.git("show", f"HEAD:{MAP}")

    for name, needle in (
        ("none", "map: none — no completed nightly-proof.yml run on main"),
        ("fail", "map: could not look ("),
    ):
        w = map_world(world, f"gh-{name}")
        gh = nightly_gh(w)
        (gh.parent / ("list.out" if name == "none" else "fail")).write_text("")
        before = (w.repo / MAP).read_text()
        said = map_fold(w, DJB_FOLD_GH=str(gh))
        assert said.rc == 0, said.text()
        assert needle in said.text()
        assert (w.repo / MAP).read_text() == before
        w.head_unmoved()

    w = map_world(world, "gh-absent")
    absent = w.scratch / "no-such-gh-anywhere"
    said = map_fold(w, DJB_FOLD_GH=str(absent))
    assert said.rc == 0, said.text()
    assert f"map: could not look (no `{absent}` on PATH" in said.text()
    w.head_unmoved()


def test_a_map_a_bank_already_wrote_outranks_the_night(world: Callable[[str], World]) -> None:
    w = map_world(world, "outranks")
    map_rewrite(w)
    night = map_night(w, w.scratch / "night-dirty", 3600, 0)
    said = w.fold(DJB_FOLD_MAP_DIR=str(night))
    assert said.rc == 0, said.text()
    assert "Absorbed as it stands; nothing was fetched." in said.text()
    assert "acceptance map absorbed" in said.text()
    assert NEW_TREE in w.git("show", f"HEAD:{MAP}")


# --- (e) the CI walls ----------------------------------------------------------------------------

WALLS = "scripts/gate_member_durations.json"
RUN = "36282702383"
WALLS_RUN_ROWS = (
    "1/3:backup_restore:17 1/3:sweep:52 1/3:secrets_scan:3 1/3:scripts_census:1 "
    "1/3:archaeology_loop:1 1/3:loop_tier:90 1/3:rung_start:2 1/3:db_template:33 "
    "1/3:verify_start:18 1/3:db_zsh:0 1/3:queue_index:2 1/3:test_impact:2 1/3:verifier_box:46 "
    "1/3:local_legs:13 2/3:pm_push:147 2/3:fe_leg:7 2/3:db_pin:20 2/3:loop_scope:433 "
    "2/3:loop_ledger:38 2/3:serve_port:1 2/3:gate_lease:47 2/3:publish:34 "
    "2/3:divergence_census:2 2/3:gate_explain:283 2/3:drive_preamble:31 2/3:shard_census:9 "
    "2/3:selftest_leg:85 2/3:stage:1 3/3:house-rules-engine:383 3/3:pm_merge:4 3/3:pm_fold:14 "
    "3/3:rung_tidy:2 3/3:secrets_baseline_guard:5 3/3:setup_env:3 3/3:fast_censuses:3 "
    "3/3:runbook_recipes:37 3/3:loop_metrics:1 3/3:pipefail_readers:7 3/3:list_legs:297 "
    "3/3:verifier_image:5 3/3:selftest_shapes:401"
).split()


def walls_fixture(w: World, directory: Path) -> Path:
    """A harvest of three shards' rows, its meta and the population it must equal."""
    shutil.rmtree(directory, ignore_errors=True)
    (directory / "harvest").mkdir(parents=True)
    names = []
    for spec in WALLS_RUN_ROWS:
        part, name, secs = spec.split(":")
        names.append(name)
        with (directory / f"harvest/shard-{part.split('/')[0]}.walls").open("a") as sink:
            sink.write(f"member-walls/1\t{name}\t0\t{secs}\t{part}\n")
    (directory / "population").write_text("".join(f"{n}\n" for n in names))
    (directory / "harvest/run.meta").write_text(
        f"run={RUN}\nmachine=ubuntu-latest\ntree={w.git('rev-parse', 'HEAD^{tree}')}\n"
    )
    return directory


def walls_fold(w: World, directory: Path, *args: str) -> Captured:
    """A fold with the harvest and the population given as directories."""
    return w.fold(
        *args,
        DJB_FOLD_WALLS_DIR=str(directory / "harvest"),
        DJB_FOLD_WALLS_POPULATION=str(directory / "population"),
    )


def ci_column(w: World) -> dict[str, int]:
    """The table's `ubuntu-latest` column, member by member."""
    doc = json.loads((w.repo / WALLS).read_text())
    return {n: r["ubuntu-latest"] for n, r in doc["members"].items() if "ubuntu-latest" in r}


def test_walls_harvests_the_runs_three_shards_into_one_table(
    world: Callable[[str], World],
) -> None:
    w = world("walls-ok")
    harvest = walls_fixture(w, w.scratch / "walls-ok")
    said = walls_fold(w, harvest)
    assert said.rc == 0, said.text()
    assert f"walls: harvested run {RUN} (41 members, ubuntu-latest" in said.text()
    column = ci_column(w)
    assert len(column) == 41
    doc = json.loads((w.repo / WALLS).read_text())
    assert doc["measured_at"]["ubuntu-latest"] == f"run:{RUN} tree:{w.before_tree}"
    assert column["loop_scope"] == 433
    assert column["house-rules-engine"] == 383
    assert w.committed() == [WALLS]
    assert "CI walls harvested" in said.text()
    w.mark()
    said = walls_fold(w, harvest)
    assert said.rc == 0
    assert "the committed table already says exactly this" in said.text()
    assert "NOTHING TO FOLD" in said.text()
    w.head_unmoved()


def walls_world(world: Callable[[str], World], name: str) -> World:
    """A world committing an older one-member table."""
    w = world(name)
    (w.repo / WALLS).write_text(
        '{\n  "schema": "member-walls/2",\n  "measured_at": {\n    "ubuntu-latest": '
        '"run:1 tree:older"\n  },\n  "members": {\n    "sweep": {"ubuntu-latest": 99}\n  }\n}\n'
    )
    w.commit("an older table", WALLS)
    return w


def test_walls_refuses_a_partial_or_borrowed_harvest(world: Callable[[str], World]) -> None:
    def twice(h: Path) -> None:
        with (h / "shard-2.walls").open("a") as sink:
            sink.write("member-walls/1\tsweep\t0\t52\t2/3\n")

    def edit(h: Path, old: str, new: str) -> None:
        shard = h / "shard-2.walls"
        lines = shard.read_text().splitlines(True)
        shard.write_text("".join(x.replace(old, new) for x in lines if new or old not in x))

    for name, plant, needle in (
        ("twice", twice, "in two shards: sweep(1/3,2/3)"),
        (
            "missing",
            lambda h: edit(h, "\tpm_push\t", ""),
            "missing against the population: pm_push",
        ),
        (
            "red",
            lambda h: edit(h, "\tgate_lease\t0\t", "\tgate_lease\t1\t"),
            "not green: gate_lease(exit 1)",
        ),
        (
            "reused",
            lambda h: edit(h, "\tstage\t0\t1\t", "\tstage\treused\t-\t"),
            "reused (never this run's wall): stage",
        ),
    ):
        w = walls_world(world, f"walls-{name}")
        harvest = walls_fixture(w, w.scratch / f"walls-{name}")
        plant(harvest / "harvest")
        before = (w.repo / WALLS).read_text()
        said = walls_fold(w, harvest)
        assert said.rc == 0, said.text()
        assert "walls: NOT harvested — " in said.text()
        assert needle in said.text()
        assert (w.repo / WALLS).read_text() == before
        w.head_unmoved()


def shard_log(rows: Sequence[str] = WALLS_RUN_ROWS) -> str:
    """A run log's selftest shard lines, one per row."""
    out = ""
    for spec in rows:
        part, name, secs = spec.split(":")
        out += (
            f"legs (selftest, {part})\tUNKNOWN STEP\t2026-09-27T00:32:04.1069319Z   "
            f"drive {name}: exit 0 ({secs}s)\n"
        )
    return out


LOG_GH = """\
#!/usr/bin/env bash
act="$(cat "{home}/gh.act" 2>/dev/null || echo fail)"
[ "$act" = "log" ] || {{ echo "stub gh: HTTP 401: Bad credentials" >&2; exit 1; }}
case "$*" in
"run list "*) echo {run} ;;
"run view {run} --json "*) echo "completed success $(git rev-parse HEAD)" ;;
"api repos/{{owner}}/{{repo}}/actions/runs/"*) printf 'ubuntu-latest\\nubuntu-latest\\n' ;;
"run download "*) echo "no artifact matches any of the names or patterns provided" >&2; exit 1 ;;
"run view {run} --log") cat "{home}/gh.log" ;;
*) echo "stub gh: unexpected $*" >&2; exit 1 ;;
esac
"""
HONOURED_GH = """\
#!/usr/bin/env bash
case "$*" in
"run list "*) echo 900 ;;
"run view 900 --json "*|"run view {run} --json "*)
    echo "completed success $(git rev-parse HEAD)" ;;
"api repos/{{owner}}/{{repo}}/actions/runs/900/jobs"*) : ;;
"api repos/{{owner}}/{{repo}}/actions/runs/{run}/jobs"*)
    printf 'ubuntu-latest\\nubuntu-latest\\n' ;;
"run download "*)
    echo "no artifact matches any of the names or patterns provided" >&2; exit 1 ;;
"run view 900 --log") printf 'derive\\tconsult\\t2026-09-27T01:00:00.0000000Z honoured: \
tree %s was measured green by run {run} (attempt 1) — no row runs:\\n' \
"$(git rev-parse 'HEAD^{{tree}}')" ;;
"run view {run} --log") cat "{home}/gh.log" ;;
*) echo "stub gh: unexpected $*" >&2; exit 1 ;;
esac
"""


def planted_gh(w: World, body: str, log: str = "", act: str = "") -> Path:
    """A `gh` beside the world, its log and its steering file in its own directory."""
    home = w.scratch / f"{w.repo.name}-gh"
    home.mkdir()
    (home / "gh.log").write_text(log)
    if act:
        (home / "gh.act").write_text(f"{act}\n")
    gh = home / "gh"
    gh.write_text(body.format(home=home, run=RUN))
    gh.chmod(0o755)
    return gh


def test_walls_reads_a_runs_log_when_it_has_no_artifacts(world: Callable[[str], World]) -> None:
    w = world("walls-log")
    harvest = walls_fixture(w, w.scratch / "walls-log")
    decoys = (
        "legs (selftest, 2/3)\tUNKNOWN STEP\t2026-09-27T00:40:00.0000000Z       "
        "drive 1_alpha: exit 0 (0s)\n"
        "legs (pytest-x2, 1/3)\tUNKNOWN STEP\t2026-09-27T00:40:00.0000000Z   "
        "drive sweep: exit 1 (9s)\n"
    )
    gh = planted_gh(w, LOG_GH, shard_log() + decoys, act="log")
    said = w.fold(
        "--only",
        "walls",
        "--no-commit",
        DJB_FOLD_GH=str(gh),
        DJB_FOLD_WALLS_POPULATION=str(harvest / "population"),
    )
    assert said.rc == 0, said.text()
    assert f"walls: harvested run {RUN} (41 members, ubuntu-latest" in said.text()
    assert len(ci_column(w)) == 41


def test_walls_follows_an_honoured_push_to_the_run_that_measured_it(
    world: Callable[[str], World],
) -> None:
    w = world("walls-honoured")
    harvest = walls_fixture(w, w.scratch / "walls-honoured")
    gh = planted_gh(w, HONOURED_GH, shard_log())
    said = w.fold(
        "--only",
        "walls",
        "--no-commit",
        DJB_FOLD_GH=str(gh),
        DJB_FOLD_WALLS_POPULATION=str(harvest / "population"),
    )
    assert said.rc == 0, said.text()
    assert (
        f"walls: the push run 900 ran no selftest shard — derive honoured its tree by run {RUN}"
        in said.text()
    )
    assert f"walls: harvested run {RUN} (41 members, ubuntu-latest" in said.text()
    assert len(ci_column(w)) == 41


def test_walls_could_not_look_leaves_the_table_standing(world: Callable[[str], World]) -> None:
    for name in ("absent", "fails"):
        w = walls_world(world, f"walls-cnl-{name}")
        harvest = walls_fixture(w, w.scratch / f"walls-cnl-{name}")
        gh = planted_gh(w, LOG_GH) if name == "fails" else w.scratch / "no-such-gh-anywhere"
        before = (w.repo / WALLS).read_text()
        said = w.fold(DJB_FOLD_GH=str(gh), DJB_FOLD_WALLS_POPULATION=str(harvest / "population"))
        assert said.rc == 0, said.text()
        assert "— the committed table stands" in said.text()
        assert "walls: could not look (" in said.text()
        assert (w.repo / WALLS).read_text() == before
        w.head_unmoved()


# --- the callers: the bank doors and the fe leg around the fold ----------------------------------

#: The modules the bank arm imports, linked into a world whose `pm_push.sh` banks.
BANK_ARM_MODULES = (
    "quality/could_not_look.py",
    "quality/djb/env.py",
    "quality/djb/ledger.py",
    "apps/core/roads.py",
)
FOLD_SHIM = f"""\
#!/usr/bin/env bash
export PYTHONPATH="{ROOT}"
exec "{sys.executable}" -c "{ENTRY}" "$@"
"""
#: `scripts/pm_push.sh`'s shim, its package this checkout's: the push module, cwd the world.
PUSH_SHIM = f"""\
#!/usr/bin/env bash
export PYTHONPATH="{ROOT}"
exec "{sys.executable}" -P -m quality.djb.rituals.push "$@"
"""


def test_a_stale_client_cannot_bank_green_through_pm_push(
    world: Callable[[str], World], scratch: Path
) -> None:
    w = world("bank")
    for name in ("gate_ledger.sh", "gate_refuse.sh", "bash_only.sh"):
        shutil.copy2(ROOT / "scripts" / name, w.repo / "scripts" / name)
    push = w.repo / "scripts/pm_push.sh"
    push.write_text(PUSH_SHIM)
    push.chmod(0o755)
    shim = w.repo / "scripts/pm_fold.sh"
    shim.write_text(FOLD_SHIM)
    shim.chmod(0o755)
    for module in BANK_ARM_MODULES:
        (w.repo / module).parent.mkdir(parents=True, exist_ok=True)
        (w.repo / module).symlink_to(ROOT / module)
    with (w.repo / ".git/info/exclude").open("a") as sink:
        sink.write("".join(f"/{m}\n" for m in BANK_ARM_MODULES) + "__pycache__/\n")
    gate = w.repo / "scripts/check.sh"
    gate.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'cd "{w.repo}"\n. "{w.repo}/scripts/gate_ledger.sh" >/dev/null 2>&1\n'
        f'gate_measured_tree >"{w.repo}/measured-tree.txt"\n'
        f'echo "stub check.sh: a verdict for $(cat "{w.repo}/measured-tree.txt")"\n'
    )
    gate.chmod(0o755)
    bare = scratch / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    w.commit("the wiring, the stub gate and the ledger library")
    w.git("remote", "add", "origin", str(bare))
    w.git("push", "-q", "origin", "HEAD:refs/heads/main")
    w.git("worktree", "add", "-q", "--detach", str(w.repo / ".wt/pm-push"), "HEAD")
    pre_head, pre_tree = w.before_head, w.before_tree
    pushing = {"DJB_PUSH_REMOTE": "origin", "DJB_PUSH_BRANCH": "main"}
    pushing["DJB_PUSH_WORKTREE"] = "pm-push"

    def bank(*args: str) -> Captured:
        sink = scratch / f"bank-{len(list(scratch.glob('bank-*')))}"
        argv = ["./scripts/pm_push.sh", *args]
        return run_to(sink, argv, w.repo, w.env(**pushing))

    try:
        w.steer("pin.act", "drift")
        said = bank("--bank")
        assert said.rc == 0, said.text()
        assert "folding" in said.text()
        assert w.subject() == "fold: contract regenerated"
        assert "banking the POST-FOLD HEAD" in said.text()
        post_head, post_tree = w.git("rev-parse", "HEAD"), w.git("rev-parse", "HEAD^{tree}")
        measured = (w.repo / "measured-tree.txt").read_text().strip()
        assert measured == post_tree and measured != pre_tree
        remote = subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "refs/heads/main"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert remote == post_head and remote != pre_head

        w.steer("pin.act", "drift")
        (w.repo / "frontend/openapi.json").write_text('{"stale": true}\n')
        w.commit("plant a stale contract by hand", "frontend/openapi.json")
        said = bank("--bank", "--no-fold")
        assert said.rc == 0, said.text()
        assert "THE DERIVED FILES WERE NOT REGENERATED" in said.text()
        assert "that is THIS FLAG and not the tree" in said.text()
        w.head_unmoved()
        assert (w.repo / "frontend/openapi.json").read_text() == '{"stale": true}\n'
    finally:
        w.git("worktree", "remove", "--force", str(w.repo / ".wt/pm-push"))


def test_no_fold_outside_bank_is_refused_by_both_scripts(scratch: Path) -> None:
    def run(*argv: str) -> Captured:
        sink = scratch / f"no-fold-{len(list(scratch.glob('no-fold-*')))}"
        return run_to(sink, list(argv), scratch, dict(os.environ))

    said = run(str(ROOT / "scripts/pm_push.sh"), "--no-fold")
    assert said.rc == 2
    assert "--no-fold is only meaningful with --bank" in said.text()
    assert "there is nothing here for --no-fold to skip" in said.text()
    assert "scripts/pm_merge.sh refuses the same combination" in said.text()
    said = run(str(ROOT / "scripts/pm_merge.sh"), "some-branch", "--no-fold")
    assert said.rc == 2
    assert "--no-fold is only meaningful with --bank" in said.text()
    assert "scripts/pm_push.sh refuses the same combination" in said.text()
    said = run(str(ROOT / "scripts/pm_merge.sh"), "some-branch", "--bank", "--no-fold")
    assert "--no-fold is only meaningful with --bank" not in said.path.read_text()


def test_the_fold_sits_where_the_ordering_requires() -> None:
    push = inspect.getsource(push_ritual.bank)
    fold_at = push.find('ledger.bank_arm(root, who="pm_push --bank"')
    resolve_at = push.find("could not re-read HEAD after the fold")
    clean_at = push.find("has uncommitted changes")
    gate_at = push.find("mac_or_boxes(root, gate, args)")
    assert '[str(gate), "--bank"]' in inspect.getsource(push_ritual.mac_or_boxes)
    assert min(fold_at, resolve_at, clean_at, gate_at) >= 0, (
        fold_at,
        resolve_at,
        clean_at,
        gate_at,
    )
    assert fold_at < clean_at, "pm_push: the fold is after the cleanliness check"
    assert fold_at < resolve_at < gate_at, "pm_push: the SHA is not re-resolved between them"
    merge = inspect.getsource(merge_ritual.Merge.run)
    proof_at = merge.find("self.prove()")
    merge_fold_at = merge.find("ledger.bank_arm(")
    merge_gate_at = merge.find("self.exec_gate()")
    assert min(proof_at, merge_fold_at, merge_gate_at) >= 0, (
        proof_at,
        merge_fold_at,
        merge_gate_at,
    )
    assert proof_at < merge_fold_at < merge_gate_at
    assert "THE MERGE ABOVE IS ALREADY MADE" in merge


def test_the_fe_leg_names_a_client_suspect(scratch: Path) -> None:
    frontend = scratch / "fe-suspect"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"name":"x"}\n')
    lists = {
        "suspect": "apps/example/api.py\0docs/product/queue.md\0",
        "plain": "apps/example/models.py\0docs/product/queue.md\0",
    }
    said = {}
    for name, changed in lists.items():
        listed = scratch / f"changed-{name}.lst"
        listed.write_text(changed)
        said[name] = run_to(
            scratch / f"fe-{name}.out",
            [
                "bash",
                "-c",
                '. "$1"; FE_FRONTEND_DIR="$2"; fe_leg_run "$3"; echo "STATE=$FE_LEG_STATE RC=$?"',
                "_",
                str(ROOT / "scripts/fe_gate.sh"),
                str(frontend),
                str(listed),
            ],
            ROOT,
        ).text()
    assert "CLIENT SUSPECT" in said["suspect"]
    assert "apps/example/api.py" in said["suspect"]
    assert "STATE=suspect RC=0" in said["suspect"]
    assert "UNTOUCHED (fast path)" not in said["suspect"]
    assert "UNTOUCHED (fast path)" in said["plain"]
    assert "STATE=untouched RC=0" in said["plain"]
