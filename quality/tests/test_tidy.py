"""`python -m quality.djb.rituals.tidy` driven over scratch checkouts this module builds."""

# does-not-cover: the real generator and the real scanner — `pin_client.sh` and `uv` are stubs.
# does-not-cover: whether a raise is legitimate — the tidy applies the number the engine printed.
# does-not-cover: the house-rules offer — `test_legs.py` pins it on the Python leg.

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb import budgets
from quality.djb.rituals import tidy
from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "quality/budgets.yaml",
    "frontend/openapi.json",
    "frontend/src/api/generated/schema.d.ts",
    ".secrets.baseline",
    ".gitignore",
    "scripts/pm_fold.sh",
    "scripts/budget_notes.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "scripts/bash_only.sh",
    "scripts/fe_gate.sh",
    "scripts/rung_tidy.sh",
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(tidy.__file__)
#: The fold's files every fixture carries: the one baseline writer and what it sources.
COPIED = ("budget_notes.sh", "bash_only.sh", "gate_ledger.sh", "gate_refuse.sh")
#: `scripts/pm_fold.sh`'s shim in a fixture: the fold module of this checkout, folding the fixture.
FOLD_SHIM = f"""\
#!/usr/bin/env bash
export PYTHONPATH="{ROOT}"
exec "{sys.executable}" -P -c "import sys; from pathlib import Path; \\
from quality.djb.rituals.fold import main; sys.exit(main(sys.argv[1:], root=Path.cwd()))" "$@"
"""
#: The tidy over the fixture, its engine replaced by the file `TIDY_ENGINE_OUT` names.
ENTRY = (
    "import os, sys; from pathlib import Path; from quality.djb.rituals import tidy; "
    "out = Path(os.environ['TIDY_ENGINE_OUT']); "
    "sys.exit(tidy.main(sys.argv[1:], root=Path.cwd(), collect=lambda root: "
    "out.read_text() if out.is_file() else '### budget-check: notes=0 problems=0\\n'))"
)
BUDGETS = """\
service_function_length:
  apps/alpha/services.py: 40 # provenance: the comment that must survive
  # and its second line, which a naive insertion lands in the middle of
  apps/beta/services.py: 55

out_schema_fields:
  apps/alpha/schemas.py::ThingOut: 9
"""
BASELINE = (
    '{\n  "version": "1.5.0",\n  "results": {"src/oops.txt": [{"type": "Secret Keyword"}]}\n}\n'
)
PIN_STUB = """#!/usr/bin/env bash
set -euo pipefail
act="$(cat "$TIDY_PIN_ACT" 2>/dev/null || echo noop)"
case "$act" in
nonpx)
    echo "npx was not found, so the TypeScript client was not generated." >&2
    exit 2
    ;;
fail)
    echo "stub pin_client: this checkout cannot export a schema" >&2
    exit 1
    ;;
write)
    doc=frontend/openapi.json client=frontend/src/api/generated/schema.d.ts
    printf '{\\n  "openapi": "3.1.0",\\n  "paths": {"/api/v1/things": {}}\\n}\\n' >"$doc"
    printf 'export type paths = { "/api/v1/things": unknown };\\n' >"$client"
    echo "wrote frontend/src/api/generated/schema.d.ts"
    echo "wrote frontend/openapi.json"
    echo "Commit both. They are one artefact of one commit of this checkout."
    ;;
noop)
    echo "the committed client and document are byte-identical to a fresh generation"
    ;;
esac
"""
UV_STUB = """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
*"detect-secrets scan"*)
    act="$(cat "$TIDY_SECRETS_ACT" 2>/dev/null || echo stamp)"
    if [ "$act" = shift ]; then
        printf '%s\\n' '{' '  "version": "1.5.0",' '  "results": {},' \\
            '  "generated_at": "2026-06-06T06:06:06Z"' '}' >.secrets.baseline
    else
        printf '%s\\n' '{' '  "version": "1.5.0",' \\
            '  "results": {"src/oops.txt": [{"type": "Secret Keyword", "line_number": 7}]},' \\
            '  "generated_at": "2026-06-06T06:06:06Z"' '}' >.secrets.baseline
    fi
    ;;
esac
"""
RAISE_AND_NEW = """\
budget: service_function_length apps/alpha/services.py — do_thing (lines 10-99) grew to 91, \
past the recorded ceiling 40 — shrink it, or raise the ceiling in quality/budgets.yaml in a diff \
a reviewer sees. The line to paste, verbatim:
  apps/alpha/services.py: 91
budget: out_schema_fields has no recorded ceiling for apps/gamma/schemas.py::NewOut (measured 4) \
— a new subject fails until a human measures it and commits the number. The line to paste under \
`out_schema_fields:` in quality/budgets.yaml:
  apps/gamma/schemas.py::NewOut: 4
### budget-check: notes=0 problems=2
"""
LOWERING = """\
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-30) measured 21, \
below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 21
### budget-check: notes=1 problems=0
"""
REWORDED = """\
budget: service_function_length apps/alpha/services.py — do_thing grew to 91, past the recorded \
ceiling 40. Here is the line you should paste:
  apps/alpha/services.py: 91
### budget-check: notes=0 problems=1
"""


@dataclass
class World:
    """One fixture checkout, its steering files outside it, and the stub PATH it runs under."""

    repo: Path
    steer: Path
    stubs: StubPath
    runs: int = 0

    def engine_says(self, text: str) -> None:
        """What the injected engine prints for the budgets subject."""
        (self.steer / "engine.out").write_text(text)

    def pin_does(self, act: str) -> None:
        """The stub pin's next act: noop · write · nonpx · fail."""
        (self.steer / "pin.act").write_text(act)

    def scan_does(self, act: str) -> None:
        """The stub scanner's next act: stamp · shift."""
        (self.steer / "secrets.act").write_text(act)

    def env(self) -> dict[str, str]:
        """The run's environment: the stubs first, the steering files named, no CI."""
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GIT_DIR", "GIT_WORK_TREE")}
        env.update(
            PATH=os.pathsep.join((str(self.stubs.bin), env.get("PATH", ""))),
            PYTHONPATH=str(ROOT),
            TIDY_ENGINE_OUT=str(self.steer / "engine.out"),
            TIDY_PIN_ACT=str(self.steer / "pin.act"),
            TIDY_SECRETS_ACT=str(self.steer / "secrets.act"),
        )
        return env

    def run(self, *args: str) -> Run:
        """The tidy over this checkout, both streams captured outside it."""
        self.runs += 1
        got = run_to(
            self.steer / f"run-{self.runs}.out",
            [sys.executable, "-c", ENTRY, *args],
            self.repo,
            self.env(),
        )
        return Run(got)

    def git(self, *argv: str) -> str:
        """`git -C <repo> <argv>`'s stdout."""
        return subprocess.run(
            ["git", "-C", str(self.repo), *argv], capture_output=True, text=True, check=True
        ).stdout

    def commit(self, message: str) -> None:
        """Stage everything in the fixture and commit it."""
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)


@dataclass
class Run:
    """One run: its exit and its transcript."""

    got: Captured

    @property
    def rc(self) -> int:
        """The exit status."""
        return self.got.rc

    @property
    def out(self) -> str:
        """Both streams, in order."""
        return self.got.text()


@pytest.fixture
def world(
    scratch_repo: Callable[..., Path], stub_path: StubPath, scratch: Path
) -> Callable[[str], World]:
    """`world(name)`: a committed checkout carrying all three subjects and the fold's files."""

    def build(name: str) -> World:
        repo = scratch_repo(name, author="tidy-drive")
        steer = scratch / f"{name}-steer"
        steer.mkdir()
        (repo / "scripts").mkdir()
        for each in COPIED:
            shutil.copy2(ROOT / "scripts" / each, repo / "scripts" / each)
        (repo / "scripts/pm_fold.sh").write_text(FOLD_SHIM)
        (repo / "scripts/pm_fold.sh").chmod(0o755)
        (repo / "quality").mkdir()
        (repo / "quality/budgets.yaml").write_text(BUDGETS)
        (repo / "frontend/scripts").mkdir(parents=True)
        (repo / "frontend/src/api/generated").mkdir(parents=True)
        (repo / "frontend/openapi.json").write_text('{\n  "openapi": "3.1.0",\n  "paths": {}\n}\n')
        (repo / "frontend/src/api/generated/schema.d.ts").write_text(
            "export type paths = Record<string, never>;\n"
        )
        pin = repo / "frontend/scripts/pin_client.sh"
        pin.write_text(PIN_STUB)
        pin.chmod(0o755)
        (repo / ".secrets.baseline").write_text(BASELINE)
        (repo / ".gitignore").write_text("/.rung/\n")
        if "uv" not in stub_path.planted:
            stub_path.plant("uv", UV_STUB)
        made = World(repo, steer, stub_path)
        made.commit("base")
        return made

    return build


def code_constants(path: Path) -> list[str]:
    """Every string constant in `path`'s code, docstrings left out."""
    tree = ast.parse(path.read_text())
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
    ]


def invokes_past_the_pin(path: Path) -> list[str]:
    """The constants that would call the generator or `npx` rather than the pin."""
    return [s for s in code_constants(path) if s == "npx" or "gen_client.sh" in s]


# --- the door -------------------------------------------------------------------------------


def test_a_piped_stdout_is_refused(scratch: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    env["PYTHONPATH"] = str(ROOT)
    done = subprocess.run(
        [sys.executable, "-m", "quality.djb.rituals.tidy", "--budgets"],
        cwd=scratch,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert done.returncode == 2, done.stdout
    assert "refuses pipes" in done.stdout
    assert "The exit status is the verdict" in done.stdout


def test_an_unknown_argument_is_refused(world: Callable[[str], World]) -> None:
    run = world("unknown").run("--force")
    assert run.rc == 2, run.out
    assert "got '--force'" in run.out
    assert "tidy budgets" not in run.out


# --- the budgets ----------------------------------------------------------------------------


def test_budgets_applies_the_printed_lines_and_only_those(world: Callable[[str], World]) -> None:
    w = world("budgets_apply")
    w.engine_says(RAISE_AND_NEW)
    run = w.run("--budgets")
    assert run.rc == 0, run.out
    assert "budget applied: service_function_length.apps/alpha/services.py 40 → 91" in run.out
    assert "budget applied: out_schema_fields.apps/gamma/schemas.py::NewOut none → 4" in run.out
    after = (w.repo / "quality/budgets.yaml").read_text().splitlines()
    assert "  apps/alpha/services.py: 91 # provenance: the comment that must survive" in after
    assert after.count("  apps/gamma/schemas.py::NewOut: 4") == 1
    assert after.index("  apps/gamma/schemas.py::NewOut: 4") > after.index("out_schema_fields:")
    assert "  apps/beta/services.py: 55" in after, "a ceiling no sentence named moved"
    assert (
        after.count("  # and its second line, which a naive insertion lands in the middle of") == 1
    )
    assert w.git("diff", "--cached", "--name-only") == ""
    assert w.git("status", "--porcelain") == " M quality/budgets.yaml\n"


def test_a_lowering_is_left_to_the_fold(world: Callable[[str], World]) -> None:
    w = world("budgets_lowering")
    w.engine_says(LOWERING)
    run = w.run("--budgets")
    assert run.rc == 0, run.out
    assert "left for the fold (clause 3)" in run.out
    assert "tidy budgets: nothing to do" in run.out
    assert "budget applied:" not in run.out
    assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS


EXAMPLE_BUDGETS = (
    BUDGETS
    + """\
  apps/example/schemas.py::WidgetOut: 18 # the example's provenance, kept
  apps/example_portal/schemas.py::PortalRequestOut: 10
"""
)
FOLLOWS = """\
budget follow: out_schema_fields apps/example/schemas.py::WidgetOut 18 19
budget follow: out_schema_fields apps/example_portal/schemas.py::PortalRequestOut 10 9
budget note: out_schema_fields apps/example_portal/schemas.py::PortalRequestOut measured 9, \
below its ceiling 10 — a human may commit the lower number:
  apps/example_portal/schemas.py::PortalRequestOut: 9
### budget-check: notes=1 problems=0
"""


def test_a_moved_example_row_follows_its_measurement(world: Callable[[str], World]) -> None:
    w = world("budgets_example_follows")
    (w.repo / "quality/budgets.yaml").write_text(EXAMPLE_BUDGETS)
    w.commit("example rows")
    w.engine_says(FOLLOWS)
    run = w.run("--budgets")
    assert run.rc == 0, run.out
    assert (
        "re-recorded apps/example/schemas.py::WidgetOut 18 → 19 (the worked example's ceiling"
        " follows its measurement — advisory)"
    ) in run.out
    assert "re-recorded apps/example_portal/schemas.py::PortalRequestOut 10 → 9" in run.out
    assert "left for the fold" not in run.out, "a followed row was also left for the fold"
    after = (w.repo / "quality/budgets.yaml").read_text().splitlines()
    assert "  apps/example/schemas.py::WidgetOut: 19 # the example's provenance, kept" in after
    assert "  apps/example_portal/schemas.py::PortalRequestOut: 9" in after
    assert "  apps/alpha/schemas.py::ThingOut: 9" in after, "a platform row moved"
    assert w.git("status", "--porcelain") == " M quality/budgets.yaml\n"


def test_a_platform_row_never_follows(world: Callable[[str], World]) -> None:
    w = world("budgets_platform_stays")
    w.engine_says(
        "budget follow: out_schema_fields apps/alpha/schemas.py::ThingOut 9 12\n"
        "### budget-check: notes=0 problems=0\n"
    )
    run = w.run("--budgets")
    assert run.rc == 0, run.out
    assert "tidy budgets: nothing to do" in run.out
    assert "re-recorded" not in run.out
    assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS


def test_budgets_with_nothing_to_do_is_byte_identical(world: Callable[[str], World]) -> None:
    w = world("budgets_clean")
    run = w.run("--budgets")
    assert run.rc == 0, run.out
    assert "tidy budgets: nothing to do" in run.out
    assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS
    assert w.git("status", "--porcelain") == ""


def test_a_reworded_engine_sentence_is_could_not_look(world: Callable[[str], World]) -> None:
    w = world("budgets_reworded")
    w.engine_says(REWORDED)
    run = w.run("--budgets")
    assert run.rc == 2, run.out
    assert "wrote 1 problem(s) and this reader" in run.out
    assert "recognised 0 pasteable line(s)" in run.out
    assert "COULD NOT LOOK" in run.out
    assert (w.repo / "quality/budgets.yaml").read_text() == BUDGETS


# --- the client -----------------------------------------------------------------------------


def test_client_regenerates_via_pin_client(world: Callable[[str], World], scratch: Path) -> None:
    w = world("client_write")
    w.pin_does("write")
    run = w.run("--client")
    assert run.rc == 0, run.out
    assert "Commit both. They are one artefact of one commit of this checkout." in run.out
    assert "tidy client: regenerated 2 file(s)" in run.out
    moved = sorted(line[3:] for line in w.git("status", "--porcelain").splitlines())
    assert moved == ["frontend/openapi.json", "frontend/src/api/generated/schema.d.ts"]
    assert w.git("diff", "--cached", "--name-only") == ""
    assert invokes_past_the_pin(MODULE) == [], "tidy.py reaches past the pin"
    planted = scratch / "planted_npx.py"
    planted.write_text(
        MODULE.read_text() + '\nsubprocess.run(["npx", "--yes", "openapi-typescript@7.9.1"])\n'
    )
    assert invokes_past_the_pin(planted) == ["npx"], "the census is blind to a planted call"


def test_an_unmoved_client_is_nothing_to_do(world: Callable[[str], World]) -> None:
    w = world("client_noop")
    w.pin_does("noop")
    run = w.run("--client")
    assert run.rc == 0, run.out
    assert "byte-identical to a fresh generation" in run.out
    assert "tidy client: nothing to do" in run.out
    assert w.git("status", "--porcelain") == ""


def test_no_npx_is_could_not_look(world: Callable[[str], World]) -> None:
    w = world("client_nonpx")
    w.pin_does("nonpx")
    run = w.run("--client")
    assert run.rc == 2, run.out
    assert "npx was not found" in run.out
    assert "could not look (exit 2" in run.out
    assert "COULD NOT LOOK" in run.out
    assert "tidy client: regenerated" not in run.out


# --- the secrets, through the one writer ----------------------------------------------------


def test_secrets_goes_through_the_fold_and_stages_nothing(world: Callable[[str], World]) -> None:
    w = world("secrets_shift")
    w.scan_does("shift")
    head = w.git("rev-parse", "HEAD")
    run = w.run("--secrets")
    assert run.rc == 0, run.out
    assert "tidy secrets: the baseline was re-scanned and rewritten" in run.out
    assert "pm_fold: --no-commit" in run.out
    assert "BASELINE SHIFTED" in run.out
    assert w.git("status", "--porcelain") == " M .secrets.baseline\n"
    assert w.git("diff", "--cached", "--name-only") == ""
    assert w.git("rev-parse", "HEAD") == head
    baseline = (w.repo / ".secrets.baseline").read_text()
    assert '"generated_at"' not in baseline
    assert '"line_number"' not in baseline


def test_the_tidy_names_no_baseline_writer_of_its_own() -> None:
    names = [s for s in code_constants(MODULE) if "detect-secrets" in s or "detect_secrets" in s]
    assert names == [], f"tidy.py names the scanner in code: {names}"
    assert tidy.FOLD == "scripts/pm_fold.sh" and tidy.FOLD in code_constants(MODULE)
    assert tidy.FOLD_ARGV == ("--only", "secrets", "--no-commit")


def test_an_absent_subject_is_skipped_and_says_why(world: Callable[[str], World]) -> None:
    w = world("absent")
    shutil.rmtree(w.repo / "frontend")
    (w.repo / "quality/budgets.yaml").unlink()
    w.commit("a checkout with neither budgets nor a frontend")
    run = w.run()
    assert run.rc == 0, run.out
    assert "tidy budgets: skipped — no quality/budgets.yaml" in run.out
    assert "tidy client: skipped — neither frontend/openapi.json" in run.out
    assert "tidy secrets:" in run.out


# --- the offers that name this ritual -------------------------------------------------------


# deleted: plant 1 of case_each_refusal_offers_its_own_flag — the house-rules offer is the leg's
# pin: test_legs.py::test_house_rules_returns_the_engine_exit_and_offers_only_on_a_budget
def test_each_refusal_offers_its_own_flag(world: Callable[[str], World], scratch: Path) -> None:
    face = scratch / "fe"
    face.mkdir()
    changed = scratch / "fe-changed"
    changed.write_bytes(b"apps/alpha/schemas.py\0docs/product/queue.md\0")
    fe = run_to(
        scratch / "fe.out",
        [
            "bash",
            "-c",
            'set +u; FE_FRONTEND_DIR="$1"; . "$2"; FE_FRONTEND_DIR="$1" fe_leg_run "$3"',
            "fe",
            str(face),
            str(ROOT / "scripts/fe_gate.sh"),
            str(changed),
        ],
        ROOT,
    )
    said = fe.text()
    assert fe.rc == 0, said
    assert "CLIENT SUSPECT" in said
    assert "offer: ./scripts/rung_tidy.sh --client" in said
    assert "assert it with ./frontend/scripts/pin_client.sh, regenerate" not in said

    w = world("offer_shift")
    w.scan_does("shift")
    fold = run_to(
        w.steer / "fold.out",
        ["./scripts/pm_fold.sh", "--only", "secrets", "--no-commit"],
        w.repo,
        w.env(),
    )
    said = fold.text()
    assert fold.rc == 0, said
    assert "BASELINE SHIFTED" in said
    assert "./scripts/rung_tidy.sh --secrets" in said


# --- the engine, read in this process -------------------------------------------------------


def test_todays_engine_sentence_is_the_one_the_reader_parses() -> None:
    from quality import engine

    measured = engine._measure_budgets_detailed()
    section, subjects = next((s, d) for s, d in sorted(measured.items()) if d)
    key, (value, _label) = sorted(subjects.items())[0]
    problems = engine.check_budgets({section: {key: value - 1}})
    raised = [p for p in problems if f"\n  {key}: {value}" in p]
    assert len(raised) == 1, problems
    assert budgets.pastables(raised[0]) == [(section, key, str(value))]
    text = tidy.engine_sentences(ROOT)
    assert budgets.summary_lines(text) == 1, text
    assert budgets.claimed(text, "problems") == str(len(budgets.pastables(text)))
    from quality.engine.run import EXAMPLE_BUDGET_APPS

    assert budgets.follows(text, EXAMPLE_BUDGET_APPS) == [], text
