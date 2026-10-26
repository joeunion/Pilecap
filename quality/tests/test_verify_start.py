"""`python -m quality.djb.rituals.verify_start` driven over scratch repositories this module builds.

does-not-cover: the database and a real `uv sync` — a `uv` shim writes the `.dist-info` counted.
does-not-cover: the real ZITADEL — the carry is a file operation over a value this module invents.
does-not-cover: a hostile `.env` — `ZITADEL_*` lines are carried verbatim.
does-not-cover: the loop's banner wording — the seam it prints from is driven in the clone.
"""

from __future__ import annotations

import ast
import io
import os
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from quality.djb.rituals import merge, verify_start
from quality.tests.fixtures.capture import Captured, run_to

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/verify_start.py",
    "TEMPLATE_VERSION",
    "quality/djb/ledger.py",
    "scripts/verify_start.sh",
    "scripts/db.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "scripts/steps.sh",
    "scripts/bash_only.sh",
    "scripts/divergence_census.sh",
    "scripts/archaeology_lib.sh",
    "quality/djb/rituals/merge.py",
    "quality/loop_key.py",
    "quality/tree.py",
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(verify_start.__file__)
MERGE = Path(merge.__file__)
WRAPPER = ROOT / "scripts" / "verify_start.sh"
TOTAL = verify_start.STEP_TOTAL
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.verify_start import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
COPIED = ("db.sh", "gate_ledger.sh", "gate_refuse.sh", "steps.sh", "bash_only.sh")
CENSUS_FILES = (
    "quality/__init__.py",
    "quality/loop_key.py",
    "quality/could_not_look.py",
    "quality/tree.py",
    "apps/__init__.py",
    "apps/core/__init__.py",
    "apps/core/roads.py",
)
CARRY_VALUE = "drive-invented-not-a-credential-0000"
#: A two-line fixture `.env.example` whose identity key is deliberately empty.
ENV_EXAMPLE = "DATABASE_NAME=djb_placeholder\nZITADEL_PAT=\n"  # pragma: allowlist secret
SCOPE = "mode=loop_own=x_scope=x_always=d"
#: The scratch docs directory, assembled so no pointer census reads a fixture as a tree path.
D = "docs"
STRIPPED = ("DJB_GATE_LEDGER", "DJB_TEMPLATE_BASE", "DATABASE_NAME", "GIT_DIR", "GIT_WORK_TREE")
UV_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$DJB_DRIVE_UV_LOG"
echo "uv-shim invoked: $*"
case "$*" in
*sync*)
    if [ "${DJB_DRIVE_UV_RC:-0}" -ne 0 ]; then
        echo "uv-shim: this sync was asked to fail by the drive" >&2
        exit "${DJB_DRIVE_UV_RC}"
    fi
    site=".venv/lib/python3.12/site-packages"
    mkdir -p "${site}/django-5.2.0.dist-info" "${site}/pytest-8.4.2.dist-info"
    if [ -n "${DJB_DRIVE_UV_PYTHON:-}" ]; then
        mkdir -p .venv/bin && ln -sf "$DJB_DRIVE_UV_PYTHON" .venv/bin/python
    fi
    printf 'Name: django\\nVersion: 5.2.0\\n' >"${site}/django-5.2.0.dist-info/METADATA"
    printf 'Name: pytest\\nVersion: 8.4.2\\n' >"${site}/pytest-8.4.2.dist-info/METADATA"
    if [ -n "${DJB_DRIVE_RACE_ROW:-}" ]; then
        printf '%s\\n' "$DJB_DRIVE_RACE_ROW" >>"$DJB_DRIVE_RACE_LEDGER"
    fi
    ;;
esac
exit 0
"""
#: A `post-merge` that is could-not-look with no venv, as the real one is through `check.sh`.
POST_MERGE = """#!/usr/bin/env bash
cd "$(git rev-parse --show-toplevel)"
if [ ! -d .venv ]; then
    echo "!! post-merge: ENFORCEMENT BROKEN (exit 2) on the tree this merge produced." >&2
    exit 2
fi
echo "post-merge stub: measured with a venv"
exit "${DJB_DRIVE_HOOK_RC:-0}"
"""
SLEEP_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$1" >>"$DJB_DRIVE_CLOCK"
if [ -n "${DJB_DRIVE_RESTLESS:-}" ]; then
    printf 'v1 loop-v1:%064d loop 2026-10-07T00:00:00Z caller=restless scope=x passes=1\\n' 4 \\
        >>"$DJB_DRIVE_RACE_LEDGER"
fi
exit 0
"""


@dataclass
class Run:
    """One run of the subject: its exit and both streams, merged in order."""

    rc: int
    text: str
    dest: Path
    uv_log: Path

    def says(self, needle: str) -> bool:
        return needle in self.text

    def line_of(self, needle: str) -> int:
        """The first line number holding `needle`, or -1."""
        for n, line in enumerate(self.text.splitlines(), 1):
            if needle in line:
                return n
        return -1


@dataclass
class World:
    """The scratch: shims on PATH, the source repositories, every run's capture."""

    root: Path
    n: int = 0
    src: Path = field(default_factory=Path)
    uv_rc: int = 0
    uv_python: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    def next(self) -> int:
        self.n += 1
        return self.n

    def env(self, n: int) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in STRIPPED}
        base.update(
            PATH=f"{self.bin}:{os.environ['PATH']}",
            PYTHONPATH=str(ROOT),
            DJB_DRIVE_UV_LOG=str(self.root / f"uv{n}.log"),
            DJB_DRIVE_UV_RC=str(self.uv_rc),
            DJB_DRIVE_UV_PYTHON=self.uv_python,
            DJB_DRIVE_CLOCK=str(self.root / "clock"),
        )
        base.update(self.extra)
        return base

    def git(self, *argv: str, repo: Path | None = None) -> str:
        done = subprocess.run(
            ["git", "-C", str(repo or self.src), *argv], capture_output=True, text=True
        )
        assert done.returncode == 0, (argv, done.stderr)
        return done.stdout.strip()

    def fresh(self, shape: str = "ignores-dotenv", union: str = "moved-on") -> Path:
        """`fresh_source`: main, a rung branch, main moved on (or the branch folded)."""
        self.uv_rc = 0
        self.src = src = self.root / f"src{self.next()}"
        (src / "scripts").mkdir(parents=True)
        self.git("init", "-q", repo=src)
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.email", "drive@example.invalid")
        self.git("config", "user.name", "verify start drive")
        for name in COPIED:
            (src / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        if shape == "ignores-dotenv":
            (src / ".gitignore").write_text(".env\n.env.*\n!.env.example\n*.log\n.venv/\n")
        elif shape == "bare-gitignore":
            (src / ".gitignore").write_text("*.log\n")
        (src / ".env.example").write_text(ENV_EXAMPLE)
        (src / "tracked.txt").write_text("one\n")
        listed = [f"scripts/{n}" for n in COPIED] + [".env.example", "tracked.txt"]
        if shape != "no-gitignore":
            listed.append(".gitignore")
        self.git("add", *listed)
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "rung-x")
        (src / "rung.txt").write_text("what the rung built\n")
        self.git("add", "rung.txt")
        self.git("commit", "-q", "-m", "the rung")
        self.git("checkout", "-q", "main")
        self.append("tracked.txt", "two")
        self.git("commit", "-q", "-am", "main moved on afterwards")
        if union == "already-up-to-date":
            self.fold()
        return src

    def plant_post_merge(self) -> None:
        """The clone's `post-merge` hook, committed on main so the union carries it."""
        hook = self.src / "scripts" / "githooks" / "post-merge"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(POST_MERGE)
        hook.chmod(0o755)
        self.git("add", "scripts/githooks/post-merge")
        self.git("commit", "-q", "-m", "the post-merge hook")

    def fold(self) -> None:
        """The builder's last fold: main merged into the rung branch."""
        self.git("checkout", "-q", "rung-x")
        self.git("merge", "-q", "--no-edit", "main")
        self.git("checkout", "-q", "main")

    def append(self, path: str, line: str) -> None:
        with (self.src / path).open("a") as sink:
            sink.write(f"{line}\n")

    def commit_on_main(self, path: str, line: str, message: str) -> None:
        self.append(path, line)
        self.git("add", path)
        self.git("commit", "-q", "-m", message)

    def source_env(self, *lines: str) -> None:
        (self.src / ".env").write_text("".join(f"{line}\n" for line in lines))

    def common(self) -> Path:
        common = Path(self.git("rev-parse", "--git-common-dir"))
        return common if common.is_absolute() else self.src / common

    def seed_ledger(self, good: int = 2, bad: int = 1) -> Path:
        """`seed_source_ledger`: good loop rows and malformed ones in the source's ledger."""
        path = self.common() / "djb-gate-verdicts"
        rows = [
            f"v1 loop-v1:{i:064d} loop 2026-09-07T00:00:0{i}Z caller=drive "
            f"scope=mode=fast_own=x_scope=x_always=d passes=1 tree={i:064d} env={i:064d}"
            for i in range(good)
        ]
        rows += [
            "v1 loop-v1:not-a-key loop 2026-09-07T00:00:00Z caller=drive scope=x passes=1"
        ] * bad
        path.write_text("".join(f"{r}\n" for r in rows))
        return path

    def copy_census(self) -> None:
        """The loop key's prose census and its imports, copied in so the clone has its own."""
        for name in CENSUS_FILES:
            (self.src / name).parent.mkdir(parents=True, exist_ok=True)
            (self.src / name).write_bytes((ROOT / name).read_bytes())
        self.append(".gitignore", "__pycache__/")

    def run(self, *args: str, dest: bool = True, cwd: Path | None = None) -> Run:
        """The subject from the source checkout; the destination appended unless `dest` is False."""
        n = self.next()
        target = self.root / f"clone{n}"
        argv = [sys.executable, "-P", "-c", ENTRY, *args] + ([str(target)] if dest else [])
        (self.root / f"uv{n}.log").write_text("")
        done = run_to(self.root / f"out{n}.log", argv, cwd or self.src, self.env(n))
        return Run(done.rc, read(done), target, self.root / f"uv{n}.log")

    def check(self, clone: Path) -> Run:
        return self.run("--check", str(clone), dest=False)

    def shell(self, where: Path, script: str, *args: str) -> str:
        """`script` after the checkout's own `gate_ledger.sh` in `where`; stdout, '' on failure."""
        done = subprocess.run(
            ["bash", "-c", f". ./scripts/gate_ledger.sh >/dev/null 2>&1 && {script}", "_", *args],
            cwd=where,
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k not in STRIPPED},
        )
        return done.stdout.strip() if done.returncode == 0 else ""

    def measured(self, clone: Path) -> str:
        """`clone_measured_tree`: the loop's own reading of the clone's tree."""
        return self.shell(clone, "gate_measured_tree")

    def plant_builder_row(self, clone: Path, ledger: Path) -> str:
        """A builder's banked row at the key `clone` derives, its components carried."""
        tree = self.measured(clone)
        derived = self.shell(
            clone,
            'loop_env_fingerprint >/dev/null 2>&1 && printf "%s\\n%s\\n" "$LOOP_ENV_FINGERPRINT"'
            ' "$LOOP_ENV_COMPONENTS"',
        )
        fp, _, components = derived.partition("\n")
        key = self.shell(clone, 'loop_ledger_key "$1" "$2"', tree, SCOPE)
        assert tree and fp and components and key, (tree, derived, key)
        with ledger.open("a") as sink:
            sink.write(
                f"v1 {key} loop 2026-09-18T00:00:00Z caller=builder scope={SCOPE} passes=1 "
                f"tree={tree} env={fp} {components.strip()}\n"
            )
        return key

    def seam(self, clone: Path) -> tuple[str, str]:
        """`loop_seam_verdict`: the loop's consult in the clone, `hit <key>` or `miss <token>`."""
        said = self.shell(
            clone,
            'seam_tree=$(gate_measured_tree) || { echo "miss no-tree"; exit 0; }; '
            "loop_env_fingerprint >/dev/null 2>&1 || true; "
            'seam_key=$(loop_ledger_key "$seam_tree" "$1") || { echo "miss no-key"; exit 0; }; '
            'if loop_ledger_lookup "$seam_key" >/dev/null; then printf "hit %s\\n" "$seam_key"; '
            'else printf "miss %s\\n" "$(loop_ledger_attribute "$seam_tree" '
            '"${LOOP_ENV_FINGERPRINT:-unstated}" "$1" | sed -n 1p)"; fi',
            SCOPE,
        )
        verdict, _, rest = said.partition(" ")
        return verdict, rest

    def plant_tree_row(self, tree: str) -> str:
        """A harvested box row at `tree` in the source's ledger; the key."""
        key = "loop-v1:" + "c" * 64
        path = self.seed_ledger(0, 0)
        with path.open("a") as sink:
            sink.write(
                f"v1 {key} loop 2026-10-02T10:00:00Z caller=builder scope=mode=loop passes=1 "
                f"tree={tree} env={0:064d} box=i-0drivebox\n"
            )
        return key


def read(done: Captured) -> str:
    return done.path.read_text(errors="replace") if done.path.is_file() else ""


@pytest.fixture
def world(scratch: Path) -> Iterator[World]:
    """The drive's world: the `uv` and `sleep` shims first on PATH, one scratch per test."""
    here = World(scratch.resolve())
    here.bin.mkdir()
    for name, body in (("uv", UV_SHIM), ("sleep", SLEEP_SHIM)):
        (here.bin / name).write_text(body)
        (here.bin / name).chmod(0o755)
    yield here


def says(run: Run, *needles: str) -> None:
    for needle in needles:
        assert run.says(needle), f"does not say {needle!r}\n{run.text}"


def says_not(run: Run, *needles: str) -> None:
    for needle in needles:
        assert not run.says(needle), f"says {needle!r} and must not\n{run.text}"


def code_text(path: Path) -> str:
    """`path`'s executable text: comments and docstrings dropped."""
    source = path.read_text()
    docstrings = {
        node.body[0].value.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    kept = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start[0] in docstrings:
            continue
        kept.append(tok.string)
    return " ".join(kept)


# --- the refusals before anything is created -----------------------------------------------------


def test_a_piped_stdout_is_refused(scratch: Path) -> None:
    piped = subprocess.run(
        [str(WRAPPER)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=scratch
    )
    assert piped.returncode == 2, piped.stdout
    assert "refuses pipes" in piped.stdout
    assert "The exit status is the verdict" in piped.stdout


def test_an_unknown_option_is_refused(scratch: Path) -> None:
    done = run_to(scratch / "out.log", [str(WRAPPER), "--force"], scratch)
    text = read(done)
    assert done.rc == 2, text
    assert "unknown option" in text
    assert f"step 1/{TOTAL}" not in text


def test_no_branch_at_all_is_refused(world: World) -> None:
    world.fresh()
    run = world.run(dest=False)
    assert run.rc == 2, run.text
    says(run, "needs the rung branch")
    says_not(run, f"step 1/{TOTAL}")


def test_a_branch_this_checkout_does_not_have_is_refused(world: World) -> None:
    world.fresh()
    run = world.run("rung-that-never-existed")
    assert run.rc == 2, run.text
    says(run, "no local branch 'rung-that-never-existed'")
    assert not run.dest.exists()


def test_an_occupied_destination_is_refused(world: World) -> None:
    world.fresh()
    occupied = world.root / "occupied"
    occupied.mkdir()
    (occupied / "in-progress.txt").write_text("somebody else's half-finished verification\n")
    run = world.run("rung-x", str(occupied), dest=False)
    assert run.rc == 2, run.text
    says(run, "the destination is not empty")
    assert (occupied / "in-progress.txt").is_file()


def test_check_and_no_loop_refuse_alike_in_either_order(world: World) -> None:
    world.fresh()
    for order in (("--check", "--no-loop"), ("--no-loop", "--check")):
        run = world.run(*order, dest=False)
        assert run.rc == 2, run.text
        says(run, "--no-loop consults a clone this run makes; --check makes none.")
        says_not(run, "no such directory")


def test_it_never_reads_the_environment_file_into_its_own_shell() -> None:
    code = code_text(MODULE)
    assert not re.search(r"(^|[^a-zA-Z_])(source|\.)\s+\S*\.env([^a-zA-Z]|$)", code)
    assert "dotenv" not in code and "environ.update" not in code
    assert "scripts/db.sh" in code, "the derivation seam is no longer named"
    assert not re.search(r"shasum|sha256sum|sha256_of|openssl dgst|cksum|hashlib|sha256", code)
    assert "three gate runs" in MODULE.read_text()


# --- step 1 · clone ------------------------------------------------------------------------------


def test_the_happy_path_clones_merges_derives_and_ends_clean(world: World) -> None:
    world.fresh()
    world.source_env(f"ZITADEL_PAT={CARRY_VALUE}", "ZITADEL_ISSUER=http://localhost:8081")
    tip, main = world.git("rev-parse", "rung-x"), world.git("rev-parse", "main")
    reflog = world.git("reflog", "--all")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    assert world.git("reflog", "--all") == reflog, "the SOURCE's reflog moved"
    says(run, "== READY", f"step 4/{TOTAL}")
    assert (run.dest / ".git").is_dir()
    for parent in (tip, main):
        world.git("merge-base", "--is-ancestor", parent, "HEAD", repo=run.dest)
    assert world.git("rev-parse", "HEAD", repo=run.dest) != tip
    assert world.git("status", "--porcelain", repo=run.dest) == ""
    assert (run.dest / ".env").is_file()


def test_the_clone_carries_the_hooks_path(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    assert world.git("config", "--get", "core.hooksPath", repo=run.dest) == "scripts/githooks"
    says(run, "hooks        core.hooksPath=scripts/githooks")


def test_a_fresh_clone_meets_its_post_merge_hook_only_once_the_venv_exists(world: World) -> None:
    world.fresh()
    world.plant_post_merge()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says_not(run, "ENFORCEMENT BROKEN")
    says(run, "== READY")
    sync, hook = run.line_of("uv-shim invoked: sync"), run.line_of("measured with a venv")
    assert 0 < sync < hook, (sync, hook)


def test_a_red_post_merge_hook_is_never_read_as_ready(world: World) -> None:
    world.fresh()
    world.plant_post_merge()
    world.extra["DJB_DRIVE_HOOK_RC"] = "2"
    run = world.run("rung-x")
    assert run.rc == 2, run.text
    says_not(run, "== READY")


def test_a_dirty_source_checkout_is_refused_and_nothing_is_cloned(world: World) -> None:
    world.fresh()
    world.append("tracked.txt", "work in progress nobody committed")
    (world.src / "untracked-work.txt").write_text("a new file nobody has added yet\n")
    run = world.run("rung-x")
    assert run.rc == 2, run.text
    says(run, "uncommitted work", "untracked-work.txt", "tracked.txt")
    says(run, "Nothing was cloned, merged or written.")
    assert not run.dest.exists()
    assert "work in progress nobody committed" in (world.src / "tracked.txt").read_text()
    assert (world.src / "untracked-work.txt").is_file()


def test_an_untracked_log_in_the_source_is_not_dirt(world: World) -> None:
    world.fresh("no-gitignore")
    (world.src / "gate-somebody.log").write_text("a gate log\n")
    clone = world.root / "clone-logcase"
    run = world.run("rung-x", str(clone), dest=False)
    says_not(run, "uncommitted work")
    says(run, f"step 1/{TOTAL}")
    assert (clone / ".git").is_dir()


def test_docs_only_dirt_in_the_source_is_announced_and_the_clone_proceeds(world: World) -> None:
    world.fresh()
    (world.src / "docs/product").mkdir(parents=True)
    world.commit_on_main("docs/product/queue.md", "a committed plan", "the plan")
    world.append("docs/product/queue.md", "an uncommitted ledger row")
    (world.src / "docs/product/in-flight.md").write_text("an unsaved cycle file\n")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "path(s) under docs/product/ are dirty here and are NOT in")
    says(run, "a criterion read from an uncommitted plan is not in")
    # names, never reads: docs/product/in-flight.md — a path the announcement prints
    says(run, "docs/product/queue.md", "docs/product/in-flight.md", "READY")
    assert "an uncommitted ledger row" not in (run.dest / "docs/product/queue.md").read_text()
    assert not (run.dest / "docs/product/in-flight.md").exists()
    assert "an uncommitted ledger row" in (world.src / "docs/product/queue.md").read_text()


def test_docs_dirt_mixed_with_code_dirt_is_still_refused_naming_both(world: World) -> None:
    world.fresh()
    (world.src / "docs/product").mkdir(parents=True)
    world.commit_on_main("docs/product/queue.md", "a committed plan", "the plan")
    world.append("docs/product/queue.md", "an uncommitted ledger row")
    world.append("tracked.txt", "and a real code change")
    run = world.run("rung-x")
    assert run.rc == 2, run.text
    says(run, "uncommitted work", "docs/product/queue.md", "tracked.txt")
    says(run, "Nothing was cloned, merged or written.")
    assert not run.dest.exists()


# --- step 2 · union merge ------------------------------------------------------------------------


def test_a_conflicting_rung_branch_is_an_exit_1_naming_the_paths(world: World) -> None:
    world.fresh()
    world.git("checkout", "-q", "rung-x")
    world.append("tracked.txt", "the rung's own second line")
    world.git("commit", "-q", "-am", "the rung touches tracked.txt too")
    world.git("checkout", "-q", "main")
    run = world.run("rung-x")
    assert run.rc == 1, run.text
    says(run, "CONFLICT", "tracked.txt", "left AT THE CONFLICT")


def test_the_clone_is_given_a_local_main_ref_at_the_verified_sha(world: World) -> None:
    world.fresh()
    plain = world.root / "plainclone"
    subprocess.run(
        ["git", "clone", "-q", "--branch", "rung-x", str(world.src), str(plain)], check=True
    )
    absent = subprocess.run(
        ["git", "-C", str(plain), "rev-parse", "-q", "--verify", "refs/heads/main"]
    )
    assert absent.returncode != 0, "a plain --branch clone already carries refs/heads/main"
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "main ref")
    assert world.git("rev-parse", "refs/heads/main", repo=run.dest) == world.git(
        "rev-parse", "main"
    )


def test_the_clone_records_its_fold_point_as_refs_djb_base(world: World) -> None:
    for arm in ("moved-on", "already-up-to-date"):
        world.fresh("ignores-dotenv", arm)
        want = world.git("merge-base", "main", "rung-x")
        run = world.run("rung-x")
        assert run.rc == 0, run.text
        assert world.git("rev-parse", "refs/djb/base", repo=run.dest) == want, arm
        says(run, f"fork point   refs/djb/base = {world.git('rev-parse', '--short', want)}")
        says(run, f"fold point   {want}")
        absent = subprocess.run(
            ["git", "-C", str(world.src), "rev-parse", "-q", "--verify", "refs/djb/base"]
        )
        assert absent.returncode != 0, "refs/djb/base was written into the SOURCE"


#: `divergence_census.sh`'s shim in a scratch product: this checkout's module over the cwd.
DIVERGENCE_SHIM = f"""\
#!/usr/bin/env bash
export PYTHONPATH="{ROOT}"
exec "{sys.executable}" -P -c "import sys; from pathlib import Path; \\
from quality.djb.rituals.divergence import main; sys.exit(main(sys.argv[1:], root=Path.cwd()))" "$@"
"""


def grow_into_a_product(world: World, version: str) -> None:
    """The scratch primary grown into a product whose census can run, tagged `v<version>`."""
    (world.src / "config").mkdir()
    (world.src / "scripts/archaeology_lib.sh").write_bytes(
        (ROOT / "scripts/archaeology_lib.sh").read_bytes()
    )
    (world.src / "scripts/divergence_census.sh").write_text(DIVERGENCE_SHIM)
    (world.src / "scripts/divergence_census.sh").chmod(0o755)
    (world.src / "config/settings.py").write_text(
        "# a template-owned path for the census to classify\n"
    )
    (world.src / "TEMPLATE_VERSION").write_text(f"{version}\n")
    world.git("add", "scripts/divergence_census.sh", "scripts/archaeology_lib.sh")
    world.git("add", "config/settings.py", "TEMPLATE_VERSION")
    world.git("commit", "-q", "-m", "the census, a template-owned path, the version")
    world.git("tag", f"v{version}")


def census_in(clone: Path, exported: str = "") -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "DJB_TEMPLATE_BASE"}
    if exported:
        env["DJB_TEMPLATE_BASE"] = exported
    done = run_to(
        clone.parent / f"census-{clone.name}-{bool(exported)}.log",
        ["./scripts/divergence_census.sh"],
        clone,
        env,
    )
    return done.rc, read(done)


def test_the_clone_carries_the_template_remote(world: World) -> None:
    version = (ROOT / "TEMPLATE_VERSION").read_text().strip()
    shell_base = "v9.9.9"
    still = (
        "— a census run in this shell still reads the exported value first; "
        "unset it or run the census without it"
    )
    for arm in ("drawer", "remote", "shell", "carried"):
        world.fresh()
        grow_into_a_product(world, version)
        url = world.root / f"template{world.n}.git"
        tag_commit = world.git("rev-parse", f"v{version}^{{commit}}")
        if arm == "remote":
            subprocess.run(["git", "init", "-q", "--bare", str(url)], check=True)
            world.git("remote", "add", "template", str(url))
        if arm in ("drawer", "carried"):
            (world.src / "scripts/local").mkdir()
            (world.src / "scripts/local/template-base").write_text(f"{tag_commit}\n")
            world.git("add", "scripts/local/template-base")
            world.git("commit", "-q", "-m", "the product's base, declared in the drawer")
        remotes = world.git("remote", "-v")
        world.extra = {"DJB_TEMPLATE_BASE": shell_base} if arm in ("shell", "carried") else {}
        run = world.run("rung-x")
        world.extra = {}
        assert run.rc == 0, run.text
        if arm == "remote":
            says(run, f"template     remote copied ({url}) — the census's base derives from it")
            assert world.git("remote", "get-url", "template", repo=run.dest) == str(url)
        else:
            says(run, "template     none — this checkout declares no template remote")
            assert world.git("remote", repo=run.dest) == "origin"
        if arm == "shell":
            says(
                run,
                f"base         DJB_TEMPLATE_BASE={shell_base} is set in this shell and does NOT"
                " reach the clone"
                " — a typed override is the person standing there (divergence_census.sh's"
                " precedence 1);"
                " to carry a base, commit the tag's commit sha in scripts/local/template-base or"
                " add the"
                f" template remote {still}",
            )
        elif arm == "carried":
            says(
                run,
                f"base         DJB_TEMPLATE_BASE={shell_base} is set in this shell and does NOT"
                " reach the clone —",
            )
            says(
                run,
                f"the clone's census reads the declaration this checkout carries instead {still}",
            )
        else:
            says_not(run, "DJB_TEMPLATE_BASE=")
        if arm in ("shell", "carried"):
            assert world.git("status", "--porcelain", repo=run.dest) == ""
            assert "DJB_TEMPLATE_BASE" not in (run.dest / ".env").read_text()
        assert world.git("remote", "-v") == remotes, "the SOURCE's remotes moved"
        rc, text = census_in(run.dest)
        if arm == "remote":
            assert (
                rc == 0
                and f"base       v{version}  (from the 'template' remote, derived from"
                " TEMPLATE_VERSION)"
                in text
            ), text
        elif arm in ("drawer", "carried"):
            assert (
                rc == 0 and f"base       {tag_commit}  (from scripts/local/template-base)" in text
            ), text
        else:
            assert rc == 2 and "NO BASE IS DECLARED" in text, text
        if arm in ("shell", "carried"):
            rc, text = census_in(run.dest, shell_base)
            assert rc == 2 and f"base       {shell_base}  (from DJB_TEMPLATE_BASE)" in text, text


# --- step 3 · environment ------------------------------------------------------------------------


def test_the_database_name_is_asked_for_and_matches_db_sh(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    found = re.search(r"^   database     (djb_.*)$", run.text, re.MULTILINE)
    assert found, run.text
    printed = found.group(1)
    assert re.fullmatch(r"djb_rung_x_[0-9a-f]{8}", printed), printed
    ask = ["bash", "-c", '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"']
    env = {**os.environ, "DATABASE_NAME": ""}
    independent = subprocess.run(ask, cwd=run.dest, env=env, capture_output=True, text=True).stdout
    assert printed == independent
    source_name = subprocess.run(ask, cwd=world.src, env=env, capture_output=True, text=True).stdout
    assert printed != source_name, "the clone was given the SOURCE checkout's database name"
    assert f"DATABASE_NAME={printed}" in (run.dest / ".env").read_text().splitlines()


def test_an_exported_database_name_does_not_reach_the_clone(world: World) -> None:
    world.fresh()
    world.extra = {"DATABASE_NAME": "djb_the_callers_own"}
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "is set in this shell and is IGNORED here")
    assert "DATABASE_NAME=djb_the_callers_own" not in (run.dest / ".env").read_text()


def test_the_zitadel_carry_announces_names_and_never_values(world: World) -> None:
    world.fresh()
    world.source_env(
        f"ZITADEL_PAT={CARRY_VALUE}",
        "ZITADEL_ISSUER=http://localhost:8081",
        "ZITADEL_ORG_NAME=",
        "DATABASE_URL=postgres://not-a-zitadel-key/",
    )
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "carried 2 key(s)", "ZITADEL_PAT", "ZITADEL_ISSUER", "ZITADEL_ORG_NAME")
    says_not(run, CARRY_VALUE)
    lines = (run.dest / ".env").read_text().splitlines()
    assert f"ZITADEL_PAT={CARRY_VALUE}" in lines
    assert not any(line.startswith("DATABASE_URL=postgres://not-a-zitadel-key/") for line in lines)


def test_an_empty_primary_carries_nothing_and_says_so(world: World) -> None:
    world.fresh()
    world.source_env("ZITADEL_PAT=", "ZITADEL_ISSUER=")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "nothing carried", "is empty")
    says_not(run, "carried 1 key(s)")


def test_a_primary_with_no_env_at_all_says_so(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "no .env to carry from")


# --- step 4 · python dependencies ----------------------------------------------------------------


def test_the_venv_is_provisioned_before_the_seed_and_the_order_is_asserted(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "python dependencies", "uv sync --frozen", "fingerprint  ")
    assert "sync --frozen" in run.uv_log.read_text()
    merge, sync, seed = (
        run.line_of("· union merge"),
        run.line_of("uv-shim invoked: sync --frozen"),
        run.line_of("· loop-verdict seed"),
    )
    assert 0 < merge < sync < seed, (merge, sync, seed)
    assert list((run.dest / ".venv").glob("lib/*/site-packages/*.dist-info"))


def test_no_sync_skips_the_step_and_says_the_seed_cannot_hit(world: World) -> None:
    world.fresh()
    world.seed_ledger(2, 0)
    run = world.run("rung-x", "--no-sync")
    assert run.rc == 0, run.text
    says(run, "SKIPPED", "THE SEED BELOW CANNOT HIT", "re-measure the suite in full")
    says(run, "ledger seeded: 2 loop rows")
    assert run.uv_log.read_text() == ""
    assert not (run.dest / ".venv").exists()
    assert world.shell(run.dest, "loop_env_fingerprint") == ""
    says(run, "consult: WILL RUN (--no-sync")
    says_not(run, "EXPECTED HIT")


def test_a_failing_sync_is_could_not_look_and_seeds_nothing(world: World) -> None:
    world.fresh()
    world.seed_ledger(3, 0)
    world.uv_rc = 1
    run = world.run("rung-x")
    assert run.rc == 2, run.text
    says(run, "could not be VERIFIED", "uv sync --frozen", "Nothing was seeded.")
    assert not (run.dest / ".git/djb-gate-verdicts").exists()
    assert (run.dest / ".git").is_dir()


def test_the_verdict_key_ignores_the_provisioned_venv(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "clean", "READY")
    assert (run.dest / ".venv").is_dir()
    assert world.git("status", "--porcelain", repo=run.dest) == ""
    world.git("check-ignore", "-q", ".venv", repo=run.dest)


# --- step 5 · the loop-verdict seed --------------------------------------------------------------


def test_the_loop_ledger_is_seeded_and_the_counts_are_exact(world: World) -> None:
    world.fresh()
    ledger = world.seed_ledger(3, 2)
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "ledger seeded: 3 loop rows", "(2 skipped: not a loop row of the one grammar)")
    seeded = (run.dest / ".git/djb-gate-verdicts").read_text()
    assert seeded.count(" loop ") == 3
    assert "loop-v1:not-a-key" not in seeded
    note = (run.dest / ".git/djb-gate-verdicts-seed").read_text()
    says(run, "/.git/djb-gate-verdicts")
    named = re.search(r"from=(.*)$", note, re.MULTILINE)
    assert named and Path(named.group(1)).read_bytes() == ledger.read_bytes()
    assert "seeded=3" in note


def test_a_source_still_carrying_the_retired_loop_store_is_seeded_from_it(world: World) -> None:
    world.fresh()
    (world.common() / "djb-loop-verdicts").write_text(
        f"loop-v1 loop-v1:{7:064d} loop 2026-09-07T00:00:00Z caller=drive scope=x passes=1"
        " tree=x env=x\n"
        f"loop-v1 loop-v1:{8:064d} loop 2026-09-07T00:00:01Z caller=drive scope=x passes=1"
        " tree=y env=y\n"
    )
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "ledger seeded: 2 loop rows")
    rows = (run.dest / ".git/djb-gate-verdicts").read_text().splitlines()
    assert len([r for r in rows if re.match(r"^v1 loop-v1:[0-9]* loop ", r)]) == 2
    assert not (run.dest / ".git/djb-loop-verdicts").exists()


def test_a_source_with_no_loop_ledger_is_a_named_absence(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "ledger not seeded:", "holds no loop rows")
    assert not (run.dest / ".git/djb-gate-verdicts").exists()


def test_the_seed_never_writes_to_the_source(world: World) -> None:
    world.fresh()
    ledger = world.seed_ledger(2, 1)
    before = ledger.read_bytes()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    assert ledger.read_bytes() == before
    with (run.dest / ".git/djb-gate-verdicts").open("a") as sink:
        sink.write(
            f"v1 loop-v1:{9:064d} loop 2026-09-07T00:00:09Z caller=planted scope=x passes=1\n"
        )
    assert ledger.read_bytes() == before


def test_step_four_is_still_green_over_the_seeded_file(world: World) -> None:
    world.fresh()
    world.seed_ledger(2, 0)
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "clean", "READY")
    assert world.git("status", "--porcelain", repo=run.dest) == ""


def test_a_seeded_row_is_a_hit_once_the_venv_exists(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    says(first, "already up to date")
    fp = world.shell(first.dest, "loop_env_fingerprint")
    assert fp, "env= unstated — the clone's gate_ledger.sh could not census .venv"
    tree = world.git("rev-parse", "HEAD^{tree}", repo=first.dest)
    key = world.shell(first.dest, 'loop_ledger_key "$1" "$2"', tree, SCOPE)
    assert key
    ledger = world.seed_ledger(1, 0)
    with ledger.open("a") as sink:
        sink.write(
            f"v1 {key} loop 2026-09-14T00:00:00Z caller=builder scope={SCOPE} passes=1"
            f" tree={tree} env={fp}\n"
        )
    second = world.run("rung-x")
    assert second.rc == 0, second.text
    says(second, "ledger seeded: 2 loop rows")
    tree_b = world.git("rev-parse", "HEAD^{tree}", repo=second.dest)
    key_b = world.shell(second.dest, 'loop_ledger_key "$1" "$2"', tree_b, SCOPE)
    assert key_b == key
    assert world.shell(second.dest, 'loop_ledger_lookup "$1"', key_b), (
        "the seeded row is dead on arrival"
    )
    assert not world.shell(second.dest, 'loop_ledger_lookup "$1"', f"loop-v1:{7:064d}")


def test_a_racing_writer_is_re_copied_and_the_consult_hits(world: World) -> None:
    """GF6.2: a row banked in the source mid-run is a HIT after one bounded re-copy, not exit 2."""
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    tree = world.measured(first.dest)
    ledger = world.seed_ledger(1, 0)
    key = "loop-v1:" + "d" * 64
    world.extra = {
        "DJB_DRIVE_RACE_LEDGER": str(ledger),
        "DJB_DRIVE_RACE_ROW": (
            f"v1 {key} loop 2026-10-07T10:00:00Z caller=racer scope=mode=loop passes=1 "
            f"tree={tree} env={0:064d} box=i-0racer"
        ),
    }
    run = world.run("rung-x", "--no-loop")
    world.extra = {}
    assert run.rc == 0, run.text
    says(
        run,
        "re-copy      the source's ledger moved while it was copied (a writer beside this run);"
        f" copy 2 of {verify_start.RECOPY_BOUND}",
    )
    says(
        run,
        "ledger seeded: 2 loop rows",
        "read-only    the source's ledger is byte-identical across copy 2",
    )
    says(run, f"consult: HIT key {key} banked 2026-10-07T10:00:00Z box=i-0racer", "loop: hit")
    assert (world.root / "clock").read_text().split() == ["1"], "one pause, charged to the clock"


def test_a_source_that_never_holds_still_is_could_not_look(world: World) -> None:
    """GF6.2's floor: a source moving under every copy is exit 2, the bound charged to the clock."""
    world.fresh()
    ledger = world.seed_ledger(1, 0)
    world.extra = {
        "DJB_DRIVE_RACE_LEDGER": str(ledger),
        "DJB_DRIVE_RACE_ROW": (
            f"v1 loop-v1:{3:064d} loop 2026-10-07T00:00:00Z caller=racer scope=x passes=1"
        ),
        "DJB_DRIVE_RESTLESS": "1",
    }
    run = world.run("rung-x")
    world.extra = {}
    assert run.rc == 2, run.text
    says(
        run,
        "!! step 5 could not be VERIFIED: the SOURCE's ledger changed while it was being copied.",
    )
    says(
        run,
        f"It moved under each of {verify_start.RECOPY_BOUND} copies, so no stable copy was taken.",
    )
    says(run, "a step it cannot prove is never reported as done.")
    pauses = (world.root / "clock").read_text().split()
    assert pauses == ["1"] * (verify_start.RECOPY_BOUND - 1), pauses


# --- step 6 · the verdict key, and `--check` -----------------------------------------------------


def test_a_planted_stray_in_the_clone_is_refused_by_name(world: World) -> None:
    world.fresh()
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    (run.dest / "verifier-notes.md").write_text("verification notes\n")
    refused = world.check(run.dest)
    assert refused.rc == 2, refused.text
    says(refused, "STRAY FILES", "verifier-notes.md", "SHIFTS THE KEY")
    (run.dest / "verifier-notes.md").unlink()
    cleared = world.check(run.dest)
    assert cleared.rc == 0, cleared.text
    says(cleared, "CLEAN")
    (run.dest / "gate-verification.log").write_text("a gate log\n")
    assert world.check(run.dest).rc == 0


def test_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4(world: World) -> None:
    world.fresh("bare-gitignore")
    run = world.run("rung-x")
    assert run.rc == 2, run.text
    says(run, f"step {TOTAL}/{TOTAL}", "STRAY FILES", ".env")
    assert (run.dest / ".git").is_dir()


def test_the_narrowing_does_not_reach_the_verdict_key_guard(world: World) -> None:
    world.fresh()
    (world.src / "docs/product").mkdir(parents=True)
    world.commit_on_main("docs/product/queue.md", "a committed plan", "the plan")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    planted = "product/stray.md"
    (run.dest / "docs" / planted).write_text("written into the clone by something\n")
    refused = world.check(run.dest)
    assert refused.rc == 2, refused.text
    says(refused, "STRAY FILES", f"docs/{planted}")


# --- the consult prediction ----------------------------------------------------------------------


def test_a_folded_branch_predicts_a_hit(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    says(first, "already up to date")
    tree = world.measured(first.dest)
    assert tree
    key = world.plant_builder_row(first.dest, world.seed_ledger(1, 0))
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, f"consult: EXPECTED HIT {key}", f"(union = branch tip; seeded row tree={tree})")
    says_not(run, "WILL RUN")
    says(run, f"fold point   {world.git('rev-parse', 'main')}")


def test_main_moved_after_the_fold_predicts_a_run_and_counts(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    world.plant_builder_row(first.dest, world.seed_ledger(1, 0))
    fold = world.git("rev-parse", "main")
    world.commit_on_main("tracked.txt", "after the fold", "main moved after the fold")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, f"consult: WILL RUN (union differs: 1 commit(s) on main since the fold {fold})")
    says_not(run, "EXPECTED HIT")
    world.fresh()
    world.commit_on_main("tracked.txt", "and again", "main moved a second time")
    fold = world.git("merge-base", "main", "rung-x")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, f"consult: WILL RUN (union differs: 2 commit(s) on main since the fold {fold})")


def test_no_seeded_row_is_a_named_absence(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    world.seed_ledger(2, 1)
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    tree = world.measured(run.dest)
    assert tree
    says(run, f"consult: WILL RUN (no seeded row for tree {tree})")
    says_not(run, "EXPECTED HIT")
    world.fresh("ignores-dotenv", "already-up-to-date")
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, "ledger not seeded:", "consult: WILL RUN (no seeded row for tree ")


def test_the_prediction_matches_the_loops_own_verdict(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    key = world.plant_builder_row(first.dest, world.seed_ledger(1, 0))
    hit = world.run("rung-x")
    assert hit.rc == 0, hit.text
    says(hit, f"consult: EXPECTED HIT {key}")
    assert world.seam(hit.dest) == ("hit", key)
    world.commit_on_main(
        "tracked.txt", "main moved under the prediction", "main moved under the prediction"
    )
    miss = world.run("rung-x")
    assert miss.rc == 0, miss.text
    says(miss, "consult: WILL RUN (union differs: 1 commit(s) on main since the fold ")
    verdict, token = world.seam(miss.dest)
    assert verdict == "miss" and token.startswith("tree"), (verdict, token)


def test_an_env_change_is_never_a_hit_whatever_the_prediction(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    key = world.plant_builder_row(first.dest, world.seed_ledger(1, 0))
    run = world.run("rung-x")
    assert run.rc == 0, run.text
    says(run, f"consult: EXPECTED HIT {key}")
    says(run, "the environment and the scope halves are measured when the loop runs")
    env_file = run.dest / ".env"
    env_file.write_text(
        re.sub(
            r"^ZITADEL_PAT=.*$",
            "ZITADEL_PAT=changed-by-the-drive",
            env_file.read_text(),
            flags=re.MULTILINE,
        )
    )
    assert "changed-by-the-drive" in env_file.read_text()
    verdict, token = world.seam(run.dest)
    assert verdict == "miss" and token.startswith("env"), (verdict, token)


# --- step 7 · `--no-loop` ------------------------------------------------------------------------


def test_no_loop_consults_and_prints_the_row(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    tree = world.measured(first.dest)
    assert tree
    key = world.plant_tree_row(tree)
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(run, f"consult: HIT key {key} banked 2026-10-02T10:00:00Z box=i-0drivebox", "loop: hit")
    says_not(run, "WILL RUN", "./scripts/check.sh --loop")
    fold = world.git("rev-parse", "main")
    world.commit_on_main("tracked.txt", "code after the fold", "main moved by code after the fold")
    main = world.git("rev-parse", "main")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    span = f"{fold[:8]}..{main[:8]}"
    says(run, f"consult: MISS(code: {span}) — main moved by code after the fold point: tracked.txt")
    says(run, f"loop: miss(code: {span})")


def test_no_loop_admits_a_docs_only_delta_and_names_no_row(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    first = world.run("rung-x")
    key = world.plant_tree_row(world.measured(first.dest))
    (world.src / "docs").mkdir()
    world.commit_on_main(
        f"{D}/ledger-row.md", "a ledger row", "a docs-only commit on main after the fold"
    )
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(
        run, f"consult: HIT (docs-only delta) key {key} banked 2026-10-02T10:00:00Z box=i-0drivebox"
    )
    says(run, "loop: docs-only reuse")
    world.fresh("ignores-dotenv", "already-up-to-date")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(run, "consult: MISS(no-ledger) — no loop row names tree ", "loop: miss(no-ledger)")


def census_world(world: World, *extra: tuple[str, str]) -> None:
    """A source carrying the prose census, `extra` files committed on main, the branch folded."""
    world.fresh("ignores-dotenv", "already-up-to-date")
    world.copy_census()
    for path, text in extra:
        (world.src / path).parent.mkdir(parents=True, exist_ok=True)
        (world.src / path).write_text(text)
    world.git("add", "quality", "apps", ".gitignore", *(p for p, _ in extra))
    world.git("commit", "-q", "-m", "a census and its readers")
    world.fold()
    world.uv_python = str(ROOT / ".venv/bin/python")


def test_no_loop_refuses_a_quoted_docs_delta(world: World) -> None:
    census_world(
        world,
        (f"{D}/quoted.md", "a ledger the reader parses\n"),
        (f"{D}/prose.md", "plain prose\n"),
        ("scripts/reader.py", f'LEDGER = open("{D}/quoted.md")\n'),
    )
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    key = world.plant_tree_row(world.measured(first.dest))
    fold = world.git("rev-parse", "main")
    world.commit_on_main(f"{D}/prose.md", "more prose", "main moves an unquoted doc after the fold")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(run, f"consult: HIT (docs-only delta) key {key}")
    world.commit_on_main(
        f"{D}/quoted.md", "a row the reader would parse", "main moves a QUOTED doc"
    )
    main = world.git("rev-parse", "main")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(
        run,
        f"consult: MISS(code: {fold[:8]}..{main[:8]}) — main moved by code after the fold point:"
        f" {D}/quoted.md",
    )
    says_not(run, "HIT (docs-only delta)")


def test_both_consults_ask_the_one_docs_only_decider(world: World) -> None:
    census_world(
        world,
        (f"{D}/ledger.md", "the ledger\n"),
        (
            "scripts/readout.py",
            f"# names, never reads: {D}/ledger.md — a readout size line\n"
            f'LEDGER = "{D}/ledger.md"\n',
        ),
    )
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    key = world.plant_tree_row(world.measured(first.dest))
    fold = world.git("rev-parse", "main")
    world.commit_on_main(f"{D}/ledger.md", "a ledger row", "a ledger-only commit")
    main = world.git("rev-parse", "main")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(run, f"consult: HIT (docs-only delta) key {key}")
    assert (
        world.shell(run.dest, 'gate_docs_only_delta "$1" "$2"', fold, main) == f"docs {D}/ledger.md"
    )
    assert len(re.findall(r"ledger\s*\.\s*docs_only_delta\s*\(", code_text(MERGE))) == 1
    assert len(re.findall(r"ledger\s*\.\s*docs_only_delta\s*\(", code_text(MODULE))) == 1


def test_both_consults_hit_across_a_commit_measured_ledger_commit(world: World) -> None:
    d = "docs/product"
    census_world(
        world,
        (f"{d}/zz-ledger.md", "the ledger\n"),
        (
            "scripts/zz_shape.py",
            f"# measured at the commit: {d}/zz-ledger.md — the hook runs it\nLEDGER ="
            f' "{d}/zz-ledger.md"\n',
        ),
        (
            "scripts/check.sh",
            "#!/usr/bin/env bash\nexit 0\ngate_leg_zz_shape()"
            ' {\n"$PY" scripts/zz_shape.py --check\n}\n'
            'gate_run_body zz-shape gate_leg_zz_shape static "x"\n',
        ),
    )
    (world.src / ".venv/bin").mkdir(parents=True)
    (world.src / ".venv/bin/python").symlink_to(ROOT / ".venv/bin/python")
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    key = world.plant_tree_row(world.measured(first.dest))
    t_main = world.shell(world.src, 'gate_measured_tree_of "main^{tree}"')
    with (world.common() / "djb-gate-verdicts").open("a") as sink:
        sink.write(
            f"v1 {key} loop 2026-10-02T10:00:00Z caller=builder scope=mode=loop passes=1 "
            f"tree={t_main} env={0:064d} box=i-0drivebox\n"
        )
    fold = world.git("rev-parse", "main")
    world.commit_on_main(f"{d}/zz-ledger.md", "a ledger row", "a ledger-only commit")
    main = world.git("rev-parse", "main")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(run, f"consult: HIT (docs-only delta) key {key}")
    asked = merge.main_is_read(world.src, "main")
    assert (asked.word, asked.origin, asked.count, asked.key) == ("docs-only", t_main, 1, key), (
        asked
    )
    assert world.git("diff", "--name-only", fold, main) == f"{d}/zz-ledger.md"


def test_a_bank_plus_report_tip_hits_by_key_tree(world: World) -> None:
    rb = "docs/runbooks"
    world.fresh("ignores-dotenv", "already-up-to-date")
    world.copy_census()
    (world.src / rb).mkdir(parents=True)
    (world.src / rb / "x.md").write_text("a runbook\n")
    (world.src / "scripts/tests").mkdir()
    (world.src / "scripts/tests/test_globber.sh").write_text(
        f"#!/usr/bin/env bash\n# drives: {rb}/\nexit 0\n"
    )
    world.git("add", "quality", "apps", "docs", "scripts/tests/test_globber.sh", ".gitignore")
    world.git("commit", "-q", "-m", "a census and a drive that reads the runbooks by directory")
    world.git("checkout", "-q", "rung-x")
    world.git("merge", "-q", "--no-edit", "main")
    world.uv_python = str(ROOT / ".venv/bin/python")
    first = world.run("rung-x")
    assert first.rc == 0, first.text
    banked = world.measured(first.dest)
    key_tree = world.shell(first.dest, 'loop_key_tree "$1"', banked)
    key = "loop-v1:" + "b" * 64
    with world.seed_ledger(0, 0).open("a") as sink:
        sink.write(
            f"v1 {key} loop 2026-10-03T10:00:00Z caller=builder scope=mode=loop passes=1 "
            f"tree={banked} env={0:064d} box=i-0drivebox key-tree={key_tree}\n"
        )
    (world.src / f"{D}/reports").mkdir()
    (world.src / f"{D}/reports/r.md").write_text("the builder's report\n")
    world.git("add", f"{D}/reports/r.md")
    world.git("commit", "-q", "-m", "the report, after the bank")
    world.git("checkout", "-q", "main")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says(run, f"consult: HIT key {key}")
    world.git("checkout", "-q", "rung-x")
    world.append(f"{rb}/x.md", "a runbook line")
    world.git("commit", "-q", "-am", "a runbook edit the drive reads")
    world.git("checkout", "-q", "main")
    run = world.run("rung-x", "--no-loop")
    assert run.rc == 0, run.text
    says_not(run, "consult: HIT")


def test_no_loop_with_no_sync_promises_no_loop(world: World) -> None:
    world.fresh("ignores-dotenv", "already-up-to-date")
    run = world.run("rung-x", "--no-loop", "--no-sync")
    assert run.rc == 0, run.text
    says_not(run, "the first --loop re-measures")
    says(run, "--no-loop runs no --loop; the consult above is the loop cell")
