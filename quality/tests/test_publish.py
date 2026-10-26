"""`python -m quality.djb.rituals.publish` driven over a one-file-per-rule scratch repository."""

# moved: case_r0_a_reserved_path_is_refused_and_named's quiet half
# pin: test_r0_stays_silent_and_says_it_looked
# does-not-cover: a real published repository — release mode runs against a scratch clone it cuts.
# does-not-cover: the real tree's buckets — every census case reads the fixture's tree.
# does-not-cover: a secret in a shape detect-secrets does not know.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import ledger
from quality.djb.rituals import publish
from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.fixtures.scratch_repo import make_repo

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/publish.py",
    ".secrets.baseline",
    "README.md",
    "TEMPLATE_VERSION",
    "apps/example/models.py",
    "docs/runbooks/deploy.md",
    "scripts/archaeology_lib.sh",
    "scripts/dangling_paths.py",
    "scripts/docs_legs.sh",
    "scripts/gate_refuse.sh",
    "scripts/publish.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.publish import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
#: The shell libraries the module sources from the root it publishes.
LIBRARIES = ("archaeology_lib.sh", "gate_refuse.sh", "docs_legs.sh")
LEDGERS = publish.LEDGERS
MARKER = publish.MARKER
# Assembled, never spelled: this shipped file's own pointers and ids would be read by the censuses.
PROD = "docs/product"
CY = f"{PROD}/cycles"
SK = f"{PROD}/skeletons"
PLAN = "plan.md"
ADR_REAL = "core-1"
ADR_SECOND = "search-1"
ADR_GHOST = "ghost-9"
HANDOFF = "pm-handoff-2026-03-01.md"
ARCH_N = "".join(("N", "347"))
ARCH_RUNG = "".join(("P", "9-2"))
ARCH_NARRATIVE = "".join(("PROVE", "-1"))
ARCH_THIS = "".join(("this ", "rung"))
ARCH_PRIVATE = "".join(("Att", "icus"))
ARCH_NOQA = "".join(("N", "802"))
ARCH_DOMAIN = "".join(("pilecap", ".dev"))
ARCH_BRAND = "".join(("Django", "Bootstrap"))
ARCH_COORD = "".join(("pilecap", "-staging"))
LOCAL_MD = "." + "local.md"
MEASURED = (
    "scripts/test_impact.json",
    "scripts/pytest_durations.json",
    "scripts/gate_member_durations.json",
)
#: The fixture's gate: `--leg supply-chain` answers clean, or the audit a test names, red.
FIXTURE_GATE = """#!/bin/sh
# the gate: --loop and --leg are this fixture gate's declared flags
[ "$1" = "--leg" ] && [ "$2" = "supply-chain" ] || exit 2
if [ -n "${PUBLISH_FIXTURE_AUDIT:-}" ]; then
    cat "$PUBLISH_FIXTURE_AUDIT"
    exit 1
fi
echo "supply chain: clean"
"""
#: A pip-audit report naming one unpatched pin, as the supply-chain leg prints it.
UNPATCHED = """Found 1 known vulnerability in 1 package
Name    Version    ID                  Fix Versions
------- ---------- ------------------- ------------
certifi 2025.10.5  GHSA-6q48-6c7w-9gw2 2026.10.20
"""
STUB_FILE = re.compile(r"^dangling-paths: (.*) does not exist in fixture — ")
STUB_SYMBOL = re.compile(r"^dangling-paths: (.*)::([A-Za-z0-9_]*) is defined nowhere in ")
STUB_LINE = re.compile(r"^dangling-paths: (\S+?):(\d+)(?:-(\d+))? cites past ")


def git(repo: Path, *args: str) -> str:
    """`git` in `repo` with a fixture identity and no signing; its stdout."""
    done = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"git {' '.join(args)} in {repo}: {done.stderr.strip()}")
    return done.stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    """Stage everything and commit, empty or not."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)


def write(repo: Path, rel: str, text: str, append: bool = False) -> None:
    """One file under `repo`, its directory made."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w") as handle:
        handle.write(text)


def stub_dangling(fixture: Path) -> None:
    """Stub each path the copied libraries' prose names: dangling-paths judges the plants only."""
    for _ in ("files", "symbols", "lines"):
        listing = fixture.parent / "untracked.nul"
        untracked = subprocess.run(
            ["git", "-C", str(fixture), "ls-files", "-z", "--others", "--exclude-standard"],
            capture_output=True,
            check=True,
        ).stdout
        listing.write_bytes(untracked)
        done = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/dangling_paths.py"),
                str(fixture),
                str(listing),
                "--noun",
                "fixture",
            ],
            capture_output=True,
            text=True,
        )
        wanted: set[tuple[str, str]] = set()
        long: dict[str, int] = {}
        for line in done.stdout.splitlines():
            if cited := STUB_LINE.match(line):
                end = int(cited.group(3) or cited.group(2))
                long[cited.group(1)] = max(long.get(cited.group(1), 0), end)
            elif m := STUB_FILE.match(line):
                wanted.add((m.group(1), ""))
            elif m := STUB_SYMBOL.match(line):
                wanted.add((m.group(1), m.group(2)))
        for rel, sym in sorted(wanted):
            if rel.endswith("/"):
                (fixture / rel).mkdir(parents=True, exist_ok=True)
                continue
            (fixture / rel).parent.mkdir(parents=True, exist_ok=True)
            (fixture / rel).touch()
            if sym:
                line = f"{sym} = None\n" if rel.endswith(".py") else f"{sym}() {{ :; }}\n"
                write(fixture, rel, line, append=True)
        for rel, end in sorted(long.items()):
            have = len((fixture / rel).read_text().splitlines())
            write(fixture, rel, "# stub\n" * (end - have), append=True)


def build_fixture(fixture: Path) -> Path:
    """One tracked file per bucket rule, the libraries the module sources, and a baseline."""
    make_repo(fixture, "fixture")
    (fixture / "scripts").mkdir()
    for lib in LIBRARIES:
        shutil.copyfile(ROOT / "scripts" / lib, fixture / "scripts" / lib)
    files = {
        "apps/example/models.py": "# a model\n",
        "frontend/package.json": '{"name":"scaffold"}\n',
        "config/settings.py": "# settings\n",
        "manage.py": "# manage\n",
        "quality/rules.yaml": "rules: []\n",
        f"{PROD}/instruments.md": "| Instrument | a | b | c | d |\n",
        "scripts/check.sh": FIXTURE_GATE,
        "scripts/test_impact.json": '{"generated":{"tree":"tree:'
        + "0" * 40
        + '","pytest":3},"tests":{}}\n',
        "scripts/pytest_durations.json": '{"a::b": 0.5}\n',
        "scripts/gate_member_durations.json": (
            '{"measured_at":"tree:0000000","machine":"fixture","members":{}}\n'
        ),
        "pyproject.toml": "[project]\n",
        publish.PROOF_FLOW: "name: proof-from-zero\non: workflow_dispatch\n",
        ".gitignore": "*.log\n.venv\nscripts/dangling_paths.py\n",
        "CLAUDE.md": "# the guide\n",
        "README.md": "# readme\n",
        "docs/runbooks/deploy.md": "# deploy\n",
        "docs/standards.md": "# standards\n",
        "docs/sdk/reference.md": "# the reference\n",
        ".claude/agents/builder.md": "---\nname: builder\nmodel: a-model\n---\n\nThe builder.\n",
        "TEMPLATE_VERSION": "0.1.0\n",
        "CHANGELOG.md": "# changelog\n",
        f"{PROD}/architecture.md": "# architecture — the current state\n",
        f"{PROD}/adrs/{ADR_REAL}.md": f"# ADR {ADR_REAL}\n\nADR {ADR_REAL} says so.\n",
        f"{PROD}/adrs/{ADR_SECOND}.md": f"# ADR {ADR_SECOND}\n",
        f"{PROD}/adrs-ingredients.md": "# ingredients — the design record\n",
        f"{PROD}/design/patterns.md": "# the pattern book\n",
        f"{CY}/{PLAN}": "# a cycle plan, trimmed\n",
        f"{PROD}/{HANDOFF}": "# a dated handoff, trimmed\n",
        f"{SK}/queue.md": f"# queue — the skeleton\n\n{MARKER}\n\n> example row\n",
    }
    for name in (
        "api-editorial-standard",
        "build-contract",
        "operating-protocol",
        "partition-closure",
        "scale-envelope",
        "publication-manifest",
    ):
        files[f"{PROD}/{name}.md"] = f"# {name}\n"
    for name in LEDGERS:
        files[f"{PROD}/{name}.md"] = f"# {name}\n\n{MARKER}\n\n> example row\n"
    for rel, text in files.items():
        write(fixture, rel, text)
    (fixture / "scripts/check.sh").chmod(0o755)
    (fixture / ".venv").symlink_to(ROOT / ".venv")
    (fixture / "scripts/dangling_paths.py").symlink_to(ROOT / "scripts/dangling_paths.py")
    stub_dangling(fixture)
    baseline = subprocess.run(
        [str(ROOT / ".venv/bin/detect-secrets"), "scan", "--all-files"],
        cwd=fixture,
        capture_output=True,
        text=True,
    )
    if baseline.returncode != 0:
        raise CouldNotLook(
            f"detect-secrets would not build the fixture's baseline: {baseline.stderr}"
        )
    (fixture / ".secrets.baseline").write_text(baseline.stdout)
    commit_all(fixture, "fixture")
    return fixture


#: The release's `gh`: origin holds HEAD, a green record names the export's tree; GH_STUB_* say no.
PROOF_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "__LOG__"
case "$1 ${2:-}" in
"api repos/{owner}/{repo}/commits/"*)
    [ "${GH_STUB_ORIGIN:-on}" = on ] && { printf '%s\\n' "${2##*/}"; exit 0; }
    echo "gh: No commit found for SHA (HTTP 422)" >&2; exit 1 ;;
"api "*) [ "${GH_STUB_PROOF:-green}" = green ] && echo 1; exit 0 ;;
"run download")
    dir=""
    while [ "$#" -gt 0 ]; do case "$1" in --dir) dir=$2; shift 2 ;; *) shift ;; esac; done
    tree=$(git -C "$GH_STUB_ART" rev-parse 'HEAD^{tree}') line='__LINE__'
    mkdir -p "$dir"; printf '%s\\n' "${line//__TREE__/$tree}" > "$dir/proof_from_zero.txt"
    exit 0 ;;
esac
exit 1
"""


def proof_gh(home: Path) -> tuple[Path, Path]:
    """`(bin directory, call log)` of the stubbed `gh` the release's proof step meets."""
    fields = ["20261021T070000Z", "a" * 40, "f" * 40, "1", "loop", "0", "1", "201", "0", "0"]
    fields += ["-", "green", "0", "1", "agree", "-", "0", "1", "ci"]
    line = ledger.proof_line(fields).replace("f" * 40, "__TREE__")
    bin_, log = home / "gh-bin", home / "gh-calls.txt"
    bin_.mkdir(parents=True, exist_ok=True)
    (bin_ / "gh").write_text(PROOF_GH.replace("__LOG__", str(log)).replace("__LINE__", line))
    (bin_ / "gh").chmod(0o755)
    return bin_, log


@dataclass
class Run:
    """One publish run: its exit and its combined transcript."""

    rc: int
    text: str


class World:
    """A fixture copy, its scratch directory, and the scratch published repository's stage."""

    def __init__(self, fixture: Path, scratch: Path) -> None:
        self.fix = fixture
        self.scratch = scratch
        self.art = scratch / "artifact"
        self.pub = scratch / "published"
        self.cons = scratch / "consumer"
        self.count = 0
        self.stage = ""
        self.pub_root_sha = ""
        self.new_tip = ""
        self.gh_bin, self.gh_log = proof_gh(scratch)

    def run(self, *args: str, **extra: str) -> Run:
        """The module over the fixture, both streams to a numbered file; never a pipe."""
        self.count += 1
        path = f"{self.gh_bin}{os.pathsep}{os.environ.get('PATH', '')}"
        art = args[args.index("--to") + 1] if "--to" in args else str(self.art)
        env = {**os.environ, "PYTHONPATH": str(ROOT), "PATH": path, "GH_STUB_ART": art, **extra}
        cap: Captured = run_to(
            self.scratch / f"run-{self.count}.out",
            [sys.executable, "-c", ENTRY, *args],
            cwd=self.fix,
            env=env,
        )
        return Run(cap.rc, cap.path.read_text(errors="replace"))

    def release_fixture(self, version: str, section: str = "") -> None:
        """TEMPLATE_VERSION bumped; the CHANGELOG with a section, a lying one, or none."""
        write(self.fix, "TEMPLATE_VERSION", f"{version}\n")
        if section == "with-section":
            text = f"# changelog\n\n## [{version}]\n\n- the fixture drop\n"
        elif section == "with-bad-flag":
            text = (
                f"# changelog\n\n## [{version}]\n\n"
                "- the fixture drop: `./scripts/check.sh --nosuchflag`\n"
            )
        else:
            text = "# changelog\n"
        write(self.fix, "CHANGELOG.md", text)
        commit_all(self.fix, f"v{version}")

    def reread(self, named: str = "") -> str:
        """A `--to` of the source, then a committed re-read naming its version-masked identity."""
        self.count += 1
        run = self.run("--to", str(self.scratch / f"reread-{self.count}"))
        printed = re.search(r"^   identity +([0-9a-f]{40}) ", run.text, re.M)
        if run.rc != 0 or printed is None:
            raise CouldNotLook(f"the re-read's export did not print its identity: {run.text}")
        identity = named or printed.group(1)
        write(
            self.fix,
            "/".join(("docs/product/reports/p26", "critique-all-reread.md")),
            f"# The five-lens re-read of the candidate (identity {identity[:12]})\n\n## Findings\n",
        )
        commit_all(self.fix, f"re-read {identity[:12]}")
        return identity

    def commits(self) -> str:
        """The published repository's commit count."""
        try:
            return git(self.pub, "rev-list", "--count", "HEAD")
        except CouldNotLook:
            return "none"

    def pub_at(self, stage: str) -> None:
        """The published repository cut once and released forward to `stage`; never backwards."""
        order = ("", "root", "0.2.0", "0.3.0")
        if order.index(self.stage) > order.index(stage):
            raise CouldNotLook(f"pub_at {stage}: the scratch published repository is past it")
        if not self.stage:
            run = self.run("--to", str(self.pub))
            if run.rc != 0:
                raise CouldNotLook(f"the scratch published repository would not cut: {run.text}")
            git(self.pub, "tag", "-a", "v0.1.0", "-m", "v0.1.0", "HEAD")
            self.pub_root_sha = git(self.pub, "rev-parse", "HEAD")
            self.stage = "root"
        for version in ("0.2.0", "0.3.0"):
            if order.index(self.stage) >= order.index(stage):
                return
            self.release_fixture(version, "with-section")
            self.reread()
            run = self.run("--release", str(self.pub), "--to", str(self.art))
            if run.rc != 0:
                raise CouldNotLook(f"pub_at {version}: the release would not publish: {run.text}")
            if version == "0.2.0":
                self.new_tip = git(self.pub, "rev-parse", "HEAD")
            self.stage = version


def _git_locks(directory: str, names: list[str]) -> set[str]:
    return {n for n in names if n.endswith(".lock")} if ".git" in Path(directory).parts else set()


def copy_fixture(pristine: Path, to: Path) -> None:
    """A copy of the fixture that skips any `.lock` git holds under `.git`."""
    shutil.copytree(pristine, to, symlinks=True, ignore=_git_locks)


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest) -> Path:
    """The fixture built once per module; every test publishes a copy of it."""
    base = require_scratch(tmp_path_factory.mktemp("publish"), request.config.rootpath)
    return build_fixture(base / "fixture")


@pytest.fixture
def world(pristine: Path, scratch: Path) -> World:
    """A private copy of the fixture: a test plants freely and nothing restores."""
    fixture = scratch / "fixture"
    copy_fixture(pristine, fixture)
    return World(fixture, scratch)


@dataclass
class Clean:
    """The clean fixture's census and artifact, each run once per module."""

    census: Run
    artifact: Run
    art: Path
    tree: str


@pytest.fixture(scope="module")
def clean(
    pristine: Path, tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[Clean]:
    """`clean_census` and `clean_artifact`: the shared state the read-only cases inspect."""
    base = require_scratch(tmp_path_factory.mktemp("clean"), request.config.rootpath)
    fixture = base / "fixture"
    copy_fixture(pristine, fixture)
    w = World(fixture, base)
    census = w.run("--census")
    artifact = w.run("--to", str(w.art))
    tree = subprocess.run(
        ["git", "-C", str(w.art), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True
    ).stdout.strip()
    yield Clean(census, artifact, w.art, tree or "none")


def rows(run: Run) -> str:
    """The census's rule rows, for a failing assertion's message."""
    return "\n".join(line for line in run.text.splitlines() if re.match(r"^ +R[0-9]+", line))


def tracked(repo: Path, rel: str) -> bool:
    """Whether `rel` is in `repo`'s index."""
    return (
        subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", rel], capture_output=True
        ).returncode
        == 0
    )


def test_the_fixture_repository_runs_no_background_maintenance(pristine: Path) -> None:
    """No git maintenance may hold a lock in the fixture while `copytree` reads it."""
    said = {
        key: subprocess.run(
            ["git", "-C", str(pristine), "config", "--get", key], capture_output=True, text=True
        ).stdout.strip()
        for key in ("gc.auto", "maintenance.auto")
    }
    assert said == {"gc.auto": "0", "maintenance.auto": "false"}, said


# --- the arguments ----------------------------------------------------------------------------


def test_a_piped_stdout_is_refused(world: World) -> None:
    done = subprocess.run(
        [sys.executable, "-c", ENTRY, "--census"],
        cwd=world.fix,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert "refuses pipes" in done.stderr


def test_an_unknown_flag_is_exit_2(world: World) -> None:
    run = world.run("--nonsense")
    assert run.rc == 2, run.text
    assert "unknown argument '--nonsense'" in run.text


# --- every bucket rule fires on something ----------------------------------------------------


def test_r11_places_the_client_layer_in_ship(clean: Clean) -> None:
    assert clean.census.rc == 0, clean.census.text
    assert re.search(r"^ +R11 +SHIP +[1-9]", clean.census.text, re.M), rows(clean.census)


def test_r12_places_the_measured_files_in_trim(clean: Clean) -> None:
    assert clean.census.rc == 0, clean.census.text
    assert re.search(r"^ +R12 +TRIM +3$", clean.census.text, re.M), rows(clean.census)


def test_r13_places_the_sdk_reference_in_ship(clean: Clean) -> None:
    assert clean.census.rc == 0, clean.census.text
    assert re.search(r"^ +R13 +SHIP +1$", clean.census.text, re.M), rows(clean.census)
    assert (clean.art / "docs" / "sdk" / "reference.md").is_file()


@pytest.mark.parametrize("artifact_rc", [0, 1])
def test_the_sdk_leg_checks_the_reference_inside_the_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact_rc: int
) -> None:
    src, art = tmp_path / "src", tmp_path / "art"
    (src / "quality").mkdir(parents=True)
    (src / "quality" / "sdk_surface.json").write_text("{}\n")
    art.mkdir()
    calls: list[tuple[str, Path]] = []

    def run(argv: list[str], cwd: Path, **_kw: object) -> subprocess.CompletedProcess[str]:
        calls.append((" ".join(argv), Path(cwd)))
        return subprocess.CompletedProcess(argv, artifact_rc if Path(cwd) == art else 0)

    monkeypatch.setattr(subprocess, "run", run)
    ritual = publish.Publish(src, publish.Args())
    ritual.target = art
    ritual.sdk()
    inside = [argv for argv, cwd in calls if cwd == art]
    assert any("--reference --check" in argv for argv in inside), calls
    assert ritual.violations == artifact_rc, calls


def test_an_agent_definition_is_r5(clean: Clean) -> None:
    assert clean.census.rc == 0, clean.census.text
    assert re.search(r"^ +R5 +SHIP +5$", clean.census.text, re.M), rows(clean.census)


def test_the_pattern_book_is_r9(clean: Clean) -> None:
    assert clean.census.rc == 0, clean.census.text
    assert re.search(r"^ +R9 +SHIP +11$", clean.census.text, re.M), rows(clean.census)


def test_the_census_with_a_target_is_refused(world: World) -> None:
    run = world.run("--census", "--to", str(world.scratch / "x"))
    assert run.rc == 2, run.text


def test_a_dirty_source_is_refused(world: World) -> None:
    write(world.fix, "untracked-thing", "dirt\n")
    run = world.run("--census")
    assert run.rc == 2, run.text
    assert "working tree is dirty" in run.text
    assert "untracked-thing" in run.text


# --- the census's own refusals ---------------------------------------------------------------


def test_a_tracked_path_matching_no_rule_is_refused(world: World) -> None:
    write(world.fix, "UNPLACEABLE.txt", "who am i\n")
    commit_all(world.fix, "unplaced")
    run = world.run("--census")
    assert run.rc == 2, run.text
    assert "unplaced      UNPLACEABLE.txt" in run.text


@pytest.mark.parametrize(
    "rel",
    ["scripts/local/legs/x.sh", f"{PROD}/instruments" + LOCAL_MD, "apps/conftest" + "_local.py"],
    ids=["drawer", "doc", "fixtures"],
)
def test_r0_a_reserved_path_is_refused_and_named(world: World, rel: str) -> None:
    write(world.fix, rel, "# a product-owned extension\n")
    commit_all(world.fix, "reserved")
    run = world.run("--census")
    assert run.rc == 2, run.text
    assert rel in run.text and "RESERVED PATH IS TRACKED" in run.text


def test_r0_stays_silent_and_says_it_looked(clean: Clean) -> None:
    assert clean.census.rc == 0, clean.census.text
    assert "R0   reserved        none tracked" in clean.census.text


def test_an_orphan_skeleton_is_refused(world: World) -> None:
    write(world.fix, f"{SK}/not-a-ledger.md", "# nothing\n")
    commit_all(world.fix, "orphan")
    run = world.run("--census")
    assert run.rc == 2, run.text
    assert "ORPHAN SKELETON" in run.text


def test_a_ledger_neither_substituted_nor_marked_is_refused(world: World) -> None:
    write(world.fix, f"{PROD}/misses.md", "# misses — no marker anywhere\n")
    commit_all(world.fix, "unmarked")
    run = world.run("--census")
    assert run.rc == 2, run.text
    assert "NEITHER" in run.text


# --- the clean run, and what it must be true of ----------------------------------------------


def test_the_clean_fixture_publishes(clean: Clean) -> None:
    assert clean.artifact.rc == 0, clean.artifact.text
    assert "== CLEAN" in clean.artifact.text


def test_the_trim_trims_the_cycle_plans(clean: Clean) -> None:
    assert clean.artifact.rc == 0, clean.artifact.text
    assert not (clean.art / CY / PLAN).exists()


def test_the_measured_files_are_trimmed(clean: Clean) -> None:
    left = [m for m in MEASURED if (clean.art / m).exists() or tracked(clean.art, m)]
    assert not left, f"the measured files reached the artifact: {left}"


def test_an_agent_definition_reaches_the_artifact(clean: Clean) -> None:
    assert tracked(clean.art, ".claude/agents/builder.md")


def test_the_skeletons_are_consumed_not_shipped(clean: Clean) -> None:
    assert not (clean.art / SK).exists(), "the skeleton SOURCES shipped at their own path"
    assert "the skeleton" in (clean.art / PROD / "queue.md").read_text()


def test_the_artifact_starts_at_commit_one_with_its_stamp_outside_the_index(clean: Clean) -> None:
    assert git(clean.art, "rev-list", "--count", "HEAD") == "1"
    assert (clean.art / publish.STAMP).exists()
    assert not tracked(clean.art, publish.STAMP)


# --- idempotence, the claim that makes this a repeatable instrument --------------------------


def test_the_export_is_idempotent(clean: Clean, world: World) -> None:
    run = world.run("--to", str(world.art))
    tree2 = git(world.art, "rev-parse", "HEAD^{tree}")
    assert run.rc == 0, run.text
    assert clean.tree != "none" and tree2 == clean.tree
    assert f"   tree       {tree2}" in run.text


# --- the destruction guard -------------------------------------------------------------------


def test_a_target_it_cannot_prove_it_wrote_is_refused(world: World) -> None:
    foreign = world.scratch / "foreign"
    write(foreign, "precious.txt", "somebody's work\n")
    run = world.run("--to", str(foreign))
    assert run.rc == 2, run.text
    assert (foreign / "precious.txt").is_file()


# --- the verification legs each fire ---------------------------------------------------------


def test_adr_census_fires_on_an_id_resolving_nowhere(world: World) -> None:
    write(world.fix, "apps/example/models.py", f"# see ADR {ADR_GHOST} for why\n", append=True)
    commit_all(world.fix, "ghost-adr")
    run = world.run("--to", str(world.art))
    assert run.rc == 1, run.text
    assert f"adr-census: ADR {ADR_GHOST}" in run.text


def test_dangling_docs_fires_on_a_pointer_into_trimmed_history(world: World) -> None:
    write(world.fix, "README.md", f"See {CY}/{PLAN} for the rationale.\n", append=True)
    commit_all(world.fix, "dangler")
    run = world.run("--to", str(world.art))
    assert run.rc == 1, run.text
    assert f"dangling-docs: {CY}/{PLAN}" in run.text


def test_dangling_paths_excuses_a_measured_file_and_a_trimmed_directory_not_a_trimmed_file(
    world: World,
) -> None:
    write(
        world.fix,
        "README.md",
        f"The reader regenerates scripts/test_impact.json; closed plans move to {CY}/.\n",
        append=True,
    )
    commit_all(world.fix, "measured")
    run = world.run("--to", str(world.art))
    assert run.rc == 0 and "VIOLATION  dangling-paths" not in run.text, run.text

    write(world.fix, "README.md", f"The plan is {CY}/{PLAN}.\n", append=True)
    commit_all(world.fix, "trimmed-file")
    run = world.run("--to", str(world.art))
    assert run.rc == 1, run.text
    assert f"VIOLATION  dangling-paths: {CY}/{PLAN} does not exist" in run.text


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("finding-id", ARCH_N),
        ("rung-token", ARCH_RUNG),
        ("narrative", ARCH_NARRATIVE),
        ("narrative", ARCH_THIS),
        ("private-name", ARCH_PRIVATE),
        ("private-name", ARCH_DOMAIN),
        ("former-brand", ARCH_BRAND),
        ("deploy-coordinate", ARCH_COORD),
    ],
)
def test_archaeology_census_fires_on_every_class(world: World, label: str, token: str) -> None:
    write(
        world.fix,
        "apps/example/models.py",
        f"# the reason it is shaped this way, as it was found in {token}\n",
        append=True,
    )
    commit_all(world.fix, "arch-plant")
    run = world.run("--to", str(world.art))
    assert run.rc == 1, run.text
    assert re.search(rf"archaeology-census: apps/example/models\.py:[0-9]+  {label}", run.text)
    assert f'"{token}"' in run.text


def test_archaeology_census_stays_silent_on_the_allowed_forms(world: World) -> None:
    write(
        world.fix,
        "docs/runbooks/deploy.md",
        "\n## PROVE verdict\n\n"
        f"Stage 6 PROVE. Pilecap ships its own name. See house rule 7 and ADR {ADR_REAL}.\n"
        f"The stack is `name: {'django' + 'bootstrap'}` and the example env sets"
        " ZITADEL_ORG_NAME=Pilecap.\n"
        f"{MARKER}\n",
        append=True,
    )
    write(
        world.fix,
        "apps/example/models.py",
        f"def do_POST(self) -> None:  # noqa: {ARCH_NOQA} - the linter code, not a finding id\n",
        append=True,
    )
    commit_all(world.fix, "arch-allowed")
    run = world.run("--to", str(world.art))
    assert run.rc == 0 and "VIOLATION  archaeology-census" not in run.text, run.text


def test_the_secret_scan_reads_the_artifact(world: World) -> None:
    head = "-----BEGIN RSA PRIVATE"
    write(world.fix, "config/settings.py", f"{head} KEY-----\nMIIEowIBAAKCAQEAx\n", append=True)
    commit_all(world.fix, "plant")
    run = world.run("--to", str(world.art))
    assert run.rc == 1, run.text
    assert "VIOLATION  secrets" in run.text


def test_the_fixture_publishes_clean_after_every_plant(world: World) -> None:
    write(world.fix, "README.md", f"See {CY}/{PLAN}.\n", append=True)
    commit_all(world.fix, "plant")
    assert world.run("--to", str(world.art)).rc == 1
    git(world.fix, "checkout", "-q", "HEAD~1", "--", "README.md")
    commit_all(world.fix, "undo")
    run = world.run("--to", str(world.art))
    assert run.rc == 0, run.text


# --- release mode ----------------------------------------------------------------------------


def test_the_scratch_published_repository_is_cut_once(world: World) -> None:
    world.pub_at("root")
    assert world.commits() == "1"
    assert git(world.pub, "rev-list", "-n", "1", "v0.1.0") == world.pub_root_sha


def test_the_root_recut_door_is_shut(world: World) -> None:
    world.pub_at("root")
    run = world.run("--to", str(world.pub))
    assert run.rc == 2, run.text
    assert "ROOT RE-CUT DOOR IS CLOSED" in run.text
    assert world.commits() == "1"
    assert git(world.pub, "rev-parse", "-q", "--verify", "refs/tags/v0.1.0")


def test_a_release_whose_changelog_has_no_section_commits_nothing(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 1, run.text
    assert "VIOLATION  changelog" in run.text
    assert world.commits() == "1"
    assert "v0.2.0" not in git(world.pub, "tag", "--list")


def test_a_release_whose_source_carries_no_proof_workflow_is_refused(world: World) -> None:
    """CI-THIRD-5 rider: no proof workflow is no proof — refused with the remedy, never advised."""
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    world.reread()
    git(world.fix, "rm", "-q", publish.PROOF_FLOW)
    commit_all(world.fix, "the proof workflow dropped")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 2, run.text
    assert f"!! this source carries no {publish.PROOF_FLOW}" in run.text
    assert "   remedy: " in run.text and "advisory — this source" not in run.text
    assert world.commits() == "1" and "v0.2.0" not in git(world.pub, "tag", "--list")


def test_a_product_tree_is_refused_once_at_the_top_of_a_release(world: World) -> None:
    """A tree that declares a namespace never meets the proof or the re-read refusal."""
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    git(world.fix, "rm", "-q", publish.PROOF_FLOW)
    write(world.fix, "quality/local/rules.yaml", "rule_id_namespace: acme\n")
    commit_all(world.fix, "the product declares itself; R14 took the proof")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 2, run.text
    assert "!! --release is the template's own release ritual; this tree is the product acme." in (
        run.text
    )
    assert "deploy/release.sh" in run.text and "R14" in run.text
    assert "carries no" not in run.text and "critique:" not in run.text
    assert not world.art.exists() and world.commits() == "1"


def test_a_release_whose_source_is_not_on_origin_refuses_before_dispatching(world: World) -> None:
    """CI-THIRD-5 rider: no green proof and a source origin lacks — refused before any dispatch."""
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    world.reread()
    world.gh_log.write_text("")
    run = world.run(
        "--release", str(world.pub), "--to", str(world.art), GH_STUB_PROOF="none",
        GH_STUB_ORIGIN="off",
    )  # fmt: skip
    assert run.rc == 2, run.text
    sha = git(world.fix, "rev-parse", "HEAD")
    assert f"!! the source {sha[:12]} is not on origin" in run.text
    calls = world.gh_log.read_text()
    assert f"commits/{sha}" in calls and "workflow run" not in calls, calls
    assert world.commits() == "1" and "v0.2.0" not in git(world.pub, "tag", "--list")


def test_changelog_flags_is_wired_into_release_mode(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-bad-flag")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 1, run.text
    assert (
        "VIOLATION  changelog-flags: --nosuchflag is not a literal in scripts/check.sh" in run.text
    )
    assert "ok — ## [0.2.0] is in the published CHANGELOG.md" in run.text
    assert world.commits() == "1"
    assert "v0.2.0" not in git(world.pub, "tag", "--list")


def test_the_release_is_a_child_commit_carrying_the_verified_tree(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    world.reread()
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 0 and world.commits() == "2", run.text
    tip = git(world.pub, "rev-parse", "HEAD")
    assert git(world.pub, "rev-parse", "HEAD^") == world.pub_root_sha
    assert git(world.pub, "rev-list", "-n", "1", "v0.2.0") == tip
    printed = re.search(r"^   tree +([0-9a-f]{40})$", run.text, re.M)
    assert printed and git(world.pub, "rev-parse", "HEAD^{tree}") == printed.group(1)
    assert git(world.pub, "status", "--porcelain") == ""
    assert (world.pub / "TEMPLATE_VERSION").read_text().strip() == "0.2.0"


def test_release_refuses_an_unpatched_pin(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    audit = world.scratch / "audit.txt"
    audit.write_text(UNPATCHED)
    run = world.run(
        "--release", str(world.pub), "--to", str(world.art), PUBLISH_FIXTURE_AUDIT=str(audit)
    )
    assert run.rc == 1, run.text
    assert "== step 5/7 · the supply chain — ./scripts/check.sh --leg supply-chain" in run.text
    assert (
        "VIOLATION  supply-chain: certifi 2025.10.5 GHSA-6q48-6c7w-9gw2 — fixed in 2026.10.20"
        in run.text
    )
    assert run.text.index("step 5/7 · the supply chain") < run.text.index("step 6/7")
    assert world.commits() == "1"
    assert "v0.2.0" not in git(world.pub, "tag", "--list")
    world.reread()
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 0 and world.commits() == "2", run.text
    assert "   ok — the supply-chain leg is green on the source" in run.text


def test_the_artifacts_baseline_keeps_only_the_excuses_its_own_files_need(world: World) -> None:
    write(world.fix, "README.md", "# readme\nthe live excuse: ZZLIVE_EXCUSE_1\n")
    unshipped = "/".join(("docs/product/reports/p26", "a-memo.md"))
    write(world.fix, unshipped, "the dead excuse: ZZDEAD_EXCUSE_2\n")
    data = json.loads((world.fix / ".secrets.baseline").read_text())
    lines = "detect_secrets.filters.regex.should_exclude_line"
    data["filters_used"] = [f for f in data["filters_used"] if f["path"] != lines]
    data["filters_used"].append({"path": lines, "pattern": ["ZZLIVE_EXCUSE_1", "ZZDEAD_EXCUSE_2"]})
    write(world.fix, ".secrets.baseline", json.dumps(data, indent=2) + "\n")
    commit_all(world.fix, "two line excuses, one for an unshipped memo")
    run = world.run("--to", str(world.art))
    assert run.rc == 0, run.text
    assert "1 line/secret excuse(s) that excuse nothing shipped dropped" in run.text
    shipped = json.loads((world.art / ".secrets.baseline").read_text())["filters_used"]
    assert [f["pattern"] for f in shipped if f["path"] == lines] == [["ZZLIVE_EXCUSE_1"]]
    source = json.loads((world.fix / ".secrets.baseline").read_text())["filters_used"]
    assert [f["pattern"] for f in source if f["path"] == lines] == [
        ["ZZLIVE_EXCUSE_1", "ZZDEAD_EXCUSE_2"]
    ]


DEBT_RULES = """rules:
  - id: "91"
    member_classes: [docstring-tail]
    debt: { since: abc1234 }
"""


def released_with_debt(world: World, version: str, floor: int, sections: dict[str, str]) -> None:
    """TEMPLATE_VERSION at `version`, rule 91's one floor at `floor`, the CHANGELOG's sections."""
    write(world.fix, "quality/rules.yaml", DEBT_RULES)
    write(world.fix, "quality/ratchet_floors.yaml", f'"91":\n  quality.docstring-tail: {floor}\n')
    write(world.fix, "TEMPLATE_VERSION", f"{version}\n")
    body = "".join(f"## [{v}]\n\n- a drop\n\n{line}\n\n" for v, line in sections.items())
    write(world.fix, "CHANGELOG.md", f"# changelog\n\n{body}")
    commit_all(world.fix, f"v{version}")
    world.reread()


def test_the_first_debt_line_is_the_baseline_and_a_flat_floor_is_refused(world: World) -> None:
    world.pub_at("root")
    released_with_debt(world, "0.2.0", 5000, {"0.2.0": "ratchet-debt: 91=5000"})
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 0, run.text
    assert "v0.1.0 recorded no ratchet-debt line: this one is the first baseline" in run.text
    flat = {"0.3.0": "ratchet-debt: 91=5000", "0.2.0": "ratchet-debt: 91=5000"}
    released_with_debt(world, "0.3.0", 5000, flat)
    run = world.run("--release", str(world.pub), "--to", str(world.scratch / "art-flat"))
    assert run.rc == 2, run.text
    assert "!! the ratchets did not fall since v0.2.0: 91 5000→5000" in run.text
    assert world.commits() == "2"


def test_a_minor_owes_the_step_and_a_fall_by_it_releases(world: World) -> None:
    world.pub_at("root")
    released_with_debt(world, "0.2.0", 5000, {"0.2.0": "ratchet-debt: 91=5000"})
    assert world.run("--release", str(world.pub), "--to", str(world.art)).rc == 0
    short = {"0.3.0": "ratchet-debt: 91=3001", "0.2.0": "ratchet-debt: 91=5000"}
    released_with_debt(world, "0.3.0", 3001, short)
    run = world.run("--release", str(world.pub), "--to", str(world.scratch / "art-short"))
    assert run.rc == 2 and "owes the summed floors (5000) a fall of at least 2000" in run.text
    fell = {"0.3.0": "ratchet-debt: 91=3000", "0.2.0": "ratchet-debt: 91=5000"}
    released_with_debt(world, "0.3.0", 3000, fell)
    run = world.run("--release", str(world.pub), "--to", str(world.scratch / "art-fell"))
    assert run.rc == 0 and "ok — 91 5000→3000: fell 2000, the minor step is 2000" in run.text


def test_a_section_without_the_measured_debt_line_is_refused(world: World) -> None:
    world.pub_at("root")
    released_with_debt(world, "0.2.0", 5000, {"0.2.0": "ratchet-debt: 91=4999"})
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 2, run.text
    assert "does not carry the candidate's debt line" in run.text
    assert "measured  ratchet-debt: 91=5000" in run.text


def test_a_minor_with_no_reread_naming_its_tree_releases_nothing(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 1, run.text
    assert "VIOLATION  critique: no docs/product/reports/*/critique-*-reread.md names" in run.text
    assert world.commits() == "1"


def test_a_reread_of_a_cut_differing_only_in_its_version_homes_names_the_release(
    world: World,
) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0a1", "with-section")
    cut = world.reread()
    world.release_fixture("0.2.0", "with-section")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 0 and world.commits() == "2", run.text
    assert f"names the candidate's identity {cut[:12]}" in run.text


def test_a_reread_naming_another_identity_releases_nothing(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.2.0", "with-section")
    world.reread(named="f" * 40)
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 1, run.text
    assert "VIOLATION  critique: no docs/product/reports/*/critique-*-reread.md names" in run.text
    assert world.commits() == "1"


def test_the_identity_masks_only_the_version_homes(tmp_path: Path) -> None:
    def tree(version: str, other: str) -> Path:
        root = tmp_path / f"{version}-{other}"
        make_repo(root, "identity")
        write(root, "TEMPLATE_VERSION", f"{version}\n")
        write(root, "pyproject.toml", f'[project]\nname = "kit"\nversion = "{version}"\n')
        write(root, "uv.lock", f'[[package]]\nname = "kit"\nversion = "{version}"\n')
        write(
            root,
            "CHANGELOG.md",
            f"# c\n\n## [{version}] — the drop\n\n- {other}\n\n[{version}]: ../x...v{version}\n",
        )
        commit_all(root, version)
        return root

    same = publish.export_identity(tree("1.2.0a3", "a"), "1.2.0a3")
    assert same == publish.export_identity(tree("1.2.0", "a"), "1.2.0")
    assert same != publish.export_identity(tree("1.2.0", "b"), "1.2.0")


def test_a_patch_with_no_reread_is_advised_and_releases(world: World) -> None:
    world.pub_at("root")
    world.release_fixture("0.1.1", "with-section")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 0 and world.commits() == "2", run.text
    assert "advisory — no re-read names the candidate's identity" in run.text


def test_release_kind_and_the_step() -> None:
    assert publish.release_kind("2.5.0", "2.5.1") == "patch"
    assert publish.release_kind("2.5.0", "2.6.0") == "minor"
    assert publish.release_kind("2.5.0", "3.0.0") == "minor"
    assert publish.release_kind("2.5.0a20", "2.5.0a21") == "pre-release"
    assert publish.debt_step(74_000, "minor") == 3700
    assert publish.debt_step(30_000, "minor") == 2000
    assert publish.debt_step(1500, "minor") == 1500
    assert publish.debt_step(10, "patch") == 1 and publish.debt_step(0, "patch") == 0


def test_a_version_already_released_is_refused(world: World) -> None:
    world.pub_at("0.2.0")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 2, run.text
    assert "v0.2.0 already exists" in run.text
    assert world.commits() == "2"


def test_a_published_tip_that_is_not_the_last_release_is_refused(world: World) -> None:
    world.pub_at("0.2.0")
    write(world.pub, "README.md", "a hand commit somebody made on the published branch\n")
    git(world.pub, "add", "README.md")
    git(world.pub, "commit", "-q", "-m", "by hand")
    hand_tip = git(world.pub, "rev-parse", "HEAD")
    world.release_fixture("0.3.0", "with-section")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 2, run.text
    assert "tip is NOT its last release" in run.text
    assert hand_tip in run.text and world.new_tip in run.text


def test_a_dirty_published_clone_is_refused(world: World) -> None:
    world.pub_at("0.2.0")
    world.release_fixture("0.3.0", "with-section")
    write(world.pub, "SOMEBODYS-WORK.txt", "uncommitted work in the published clone\n")
    run = world.run("--release", str(world.pub), "--to", str(world.art))
    assert run.rc == 2, run.text
    assert "release target's working tree is dirty" in run.text
    assert (world.pub / "SOMEBODYS-WORK.txt").is_file()


def test_a_release_target_that_is_not_a_repository_is_refused(world: World) -> None:
    world.pub_at("root")
    run = world.run("--release", str(world.scratch / "no-such-published-dir"))
    assert run.rc == 2, run.text
    run = world.run("--census", "--release", str(world.pub))
    assert run.rc == 2, run.text


def test_a_second_release_chains_onto_the_first(world: World) -> None:
    world.pub_at("0.3.0")
    assert world.commits() == "3"
    assert git(world.pub, "rev-list", "-n", "1", "v0.3.0") == git(world.pub, "rev-parse", "HEAD")


def test_a_consumer_skips_an_intermediate_release(world: World) -> None:
    world.pub_at("0.3.0")
    subprocess.run(["git", "clone", "-q", str(world.pub), str(world.cons)], check=True)
    git(world.cons, "reset", "-q", "--hard", "v0.1.0")
    write(world.cons, "PATCHED.md", "# a local patch this product carries\n")
    git(world.cons, "add", "PATCHED.md")
    git(world.cons, "commit", "-q", "-m", "our own change")
    git(world.cons, "merge", "-q", "--no-edit", "v0.3.0")
    assert git(world.cons, "diff", "--name-only", "v0.3.0", "HEAD") == "PATCHED.md"
    assert git(world.cons, "rev-list", "--count", "--merges", "HEAD") == "1"
    assert (world.cons / "TEMPLATE_VERSION").read_text().strip() == "0.3.0"


# --- leg changelog-flags: the release section's flag claims, at the body ---------------------


def clroot(base: Path, body: str) -> Path:
    """A changelog world: a gate with two flags, a command with one, a section and its history."""
    root = base / "clroot"
    shutil.rmtree(root, ignore_errors=True)
    write(root, "scripts/gate.sh", "# a gate\n# the flags it really has: --loop --fast\n")
    write(root, "apps/thing/management/commands/dothing.py", '"""a command"""\n# --email\n')
    write(
        root,
        "CHANGELOG.md",
        f"# Changelog\n\n## [9.9.9]\n\n{body}\n\n## [9.9.8]\n\n"
        "- and this section is HISTORY: `./scripts/gate.sh --gone`\n",
    )
    return root


def refusal(root: Path, version: str) -> str:
    """The could-not-look's sentences; fails the test when the body judged instead."""
    with pytest.raises(publish.Refused) as refused:
        publish.changelog_flags(root, version)
    return "\n".join(refused.value.lines)


def test_a_flag_no_script_declares_reds(scratch: Path) -> None:
    root = clroot(scratch, "- run `./scripts/gate.sh --nosuchflag` at every boundary.")
    flags = publish.changelog_flags(root, "9.9.9")
    assert flags.findings == [
        "changelog-flags: --nosuchflag is not a literal in scripts/gate.sh"
        " — claimed in `./scripts/gate.sh --nosuchflag`"
    ]


def test_an_unscripted_span_is_counted_not_judged(scratch: Path) -> None:
    body = "- `./scripts/gate.sh` is the gate; the recipe is printed by `gate --nosuchflag` first."
    flags = publish.changelog_flags(clroot(scratch, body), "9.9.9")
    assert (flags.findings, flags.claims, flags.unresolved) == ([], 0, 1)


def test_a_declared_flag_is_green(scratch: Path) -> None:
    body = "- `./scripts/gate.sh --loop` at every boundary, and `manage.py dothing --email <a>`."
    flags = publish.changelog_flags(clroot(scratch, body), "9.9.9")
    assert (flags.findings, flags.claims) == ([], 2)


def test_a_shim_gate_flag_is_judged_against_the_package(scratch: Path) -> None:
    root = clroot(scratch, "- `./scripts/check.sh --loop` at every boundary.")
    write(root, "scripts/check.sh", '#!/usr/bin/env bash\nexec "$py" -m quality.djb gate "$@"\n')
    flags = publish.changelog_flags(root, "9.9.9")
    assert flags.findings == [
        "changelog-flags: --loop is not a literal in scripts/check.sh"
        " — claimed in `./scripts/check.sh --loop`"
    ]
    write(root, "quality/djb/gate_args.py", 'MODES = ("--fast", "--loop")\n')
    flags = publish.changelog_flags(root, "9.9.9")
    assert (flags.findings, flags.claims) == ([], 1)


THIN = '#!/usr/bin/env bash\nexec "$py" -P -m quality.djb.rituals.census "$@"\n'


def test_a_thin_wrapper_flag_is_judged_against_the_module_it_execs(scratch: Path) -> None:
    root = clroot(scratch, "- `./scripts/census.sh --against <tag>` before the merge.")
    write(root, "scripts/census.sh", THIN)
    write(root, "quality/djb/rituals/census.py", 'p.add_argument("--against")\n')
    flags = publish.changelog_flags(root, "9.9.9")
    assert (flags.findings, flags.claims) == ([], 1)


def test_a_flag_in_neither_wrapper_nor_module_names_both(scratch: Path) -> None:
    root = clroot(scratch, "- `./scripts/census.sh --nosuchflag` before the merge.")
    write(root, "scripts/census.sh", THIN)
    write(root, "quality/djb/rituals/census.py", 'p.add_argument("--against")\n')
    flags = publish.changelog_flags(root, "9.9.9")
    assert flags.findings == [
        "changelog-flags: --nosuchflag is not a literal in scripts/census.sh"
        " nor in quality/djb/rituals/census.py — claimed in `./scripts/census.sh --nosuchflag`"
    ]


def test_a_wrapper_execing_an_absent_module_cannot_look(scratch: Path) -> None:
    root = clroot(scratch, "- `./scripts/census.sh --against <tag>` before the merge.")
    write(root, "scripts/census.sh", THIN)
    said = refusal(root, "9.9.9")
    assert "scripts/census.sh" in said and "quality/djb/rituals/census.py" in said


def test_an_older_section_is_history_and_is_not_read(scratch: Path) -> None:
    flags = publish.changelog_flags(clroot(scratch, "- nothing to say."), "9.9.9")
    assert flags.findings == [] and flags.claims == 0


def test_a_version_with_no_section_cannot_look(scratch: Path) -> None:
    assert "has no `## [4.4.4]` section" in refusal(clroot(scratch, "- x."), "4.4.4")


def test_a_claim_naming_a_script_not_in_the_tree_cannot_look(scratch: Path) -> None:
    root = clroot(scratch, "- run `./scripts/absent.sh --whatever` once.")
    assert "names scripts/absent.sh, which is not in" in refusal(root, "9.9.9")


def test_unbalanced_backticks_cannot_look(scratch: Path) -> None:
    root = clroot(scratch, "- an unbalanced ` span that never closes.")
    assert "ODD number of" in refusal(root, "9.9.9")


# --- the archive class and the artifact's own baseline ---------------------------------------

ARCHIVE_DOC = f"{PROD}/archive/" + "old-ledger.md"
REPORT_DOC = f"{PROD}/reports/" + "old-report.md"


def test_an_archive_pointer_is_excused_by_class_and_counted(world: World) -> None:
    write(world.fix, ARCHIVE_DOC, "# a closed ledger, trimmed\n")
    write(world.fix, "scripts/reader.sh", f"# the default reader input: {ARCHIVE_DOC}\n")
    commit_all(world.fix, "archive pointer")
    run = world.run("--to", str(world.art))
    assert run.rc == 0, run.text
    assert "VIOLATION" not in run.text
    assert "1 pointer(s) excused: docs/product/archive/ is the platform's record" in run.text
    assert not (world.art / ARCHIVE_DOC).exists()


def test_a_pointer_to_a_trimmed_report_is_still_a_finding(world: World) -> None:
    write(world.fix, REPORT_DOC, "# a report, trimmed\n")
    write(world.fix, "scripts/reader.sh", f"# see {REPORT_DOC}\n")
    commit_all(world.fix, "report pointer")
    run = world.run("--to", str(world.art))
    assert run.rc == 1, run.text
    assert f"VIOLATION  dangling-docs: {REPORT_DOC} does not exist" in run.text


def test_the_baseline_is_rederived_over_the_artifacts_own_files(world: World) -> None:
    key = "pass" + "word"
    write(world.fix, REPORT_DOC, f'# a report, trimmed\n\n{key} = "{"hunter" + "2" * 9}"\n')
    baseline = subprocess.run(
        [str(ROOT / ".venv/bin/detect-secrets"), "scan", "--all-files"],
        cwd=world.fix,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert REPORT_DOC in baseline, "the plant did not reach the source baseline"
    write(world.fix, ".secrets.baseline", baseline)
    commit_all(world.fix, "a baselined secret in a trimmed report")
    run = world.run("--to", str(world.art))
    assert run.rc == 0, run.text
    assert "(1 entries for unshipped files dropped; 0 line/secret excuse(s)" in run.text
    shipped = (world.art / ".secrets.baseline").read_text()
    assert REPORT_DOC not in shipped
    source = json.loads(baseline)
    source["results"].pop(REPORT_DOC)
    assert json.loads(shipped) == source


def test_an_advisory_row_of_either_reader_names_its_fix() -> None:
    text = (
        "certifi 2025.10.5  GHSA-6q48-6c7w-9gw2 2026.10.20\n"
        "idna    3.1        PYSEC-2024-60\n"
        "    moderate  vite@6.0.1  (vulnerable <6.3.5)  a title  "
        "https://github.com/advisories/GHSA-698v-4r3x-3vcv\n"
    )
    assert publish.advisories(text) == [
        "certifi 2025.10.5 GHSA-6q48-6c7w-9gw2 — fixed in 2026.10.20",
        "idna 3.1 PYSEC-2024-60 — no fixed version is published",
        "vite@6.0.1 GHSA-698v-4r3x-3vcv — fixed outside <6.3.5",
    ]
