"""The loop key's census, driven over scratch trees and pinned to the decider's grammar."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

#: Through `importlib`: a plain import of `quality` drags the engine into mypy's `--strict` graph.
LK = importlib.import_module("quality.loop_key")
CNL = importlib.import_module("quality.could_not_look")
CHECKS = importlib.import_module("quality.checks")

ROOT = Path(__file__).resolve().parents[3]
#: Docs paths no real tree carries, assembled so no census reads a pointer here.
PLANTED = "/".join(("docs", "product", "zz-planted.md"))
QUIET = "/".join(("docs", "product", "zz-quiet.md"))


#: A gate with one `static` leg running `scripts/<s>.py --check`, and one leg that is not static.
STATIC_GATE = (
    "gate_leg_shape() {\n"
    "set +e\n"
    '"$PY" scripts/shape.py --check\n'
    "}\n"
    'gate_run_body shape gate_leg_shape static "the shape"\n'
    "gate_leg_slow() {\n"
    '"$PY" scripts/slow.py --check\n'
    "}\n"
    'gate_run_body slow gate_leg_slow pytest "the slow one"\n'
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - a scratch repo this test just created
        ["git", *args],  # noqa: S607 — `git` resolved on PATH, as the gate's own legs run it
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _scratch(tmp_path: Path, *, gate: bool = True) -> Path:
    """A committed tree carrying two candidate docs and no decider: the census reads its own."""
    repo = tmp_path / "tree"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "rung@example.test")
    _git(repo, "config", "user.name", "loop key scratch")
    if gate:
        _write(repo, LK.GATE, STATIC_GATE)
    _write(repo, PLANTED, "planted\n")
    _write(repo, QUIET, "quiet\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_a_quote_moves_it_out(tmp_path: Path) -> None:
    repo = _scratch(tmp_path)
    assert set(LK.prose_paths(repo)) == {PLANTED, QUIET}
    _write(repo, "quality/x.py", f'BOOK = "{PLANTED}"\n')
    assert PLANTED in LK.reads(repo)
    assert LK.prose_paths(repo) == (QUIET,)


def test_its_own_declaration_puts_it_back(tmp_path: Path) -> None:
    repo = _scratch(tmp_path)
    mark = LK.decider_value("GATE_DOCS_ONLY_NONREAD")
    _write(
        repo, "quality/x.py", f'# {mark} {PLANTED} — a value, never opened\nBOOK = "{PLANTED}"\n'
    )
    assert PLANTED not in LK.reads(repo)
    assert set(LK.prose_paths(repo)) == {PLANTED, QUIET}
    assert LK.stale_declarations(repo) == ([], 1)


@pytest.mark.parametrize(
    "line",
    [
        f'x = "{PLANTED}"',
        f"x = '{PLANTED}'",
        f"  file: {PLANTED}",
        f"  - {PLANTED}",
        f"see `{PLANTED}`",
        f'x = 1  # "{PLANTED}"',
        f'x = "a/{PLANTED}"',
        f"x = {PLANTED}",
        f'doc: {{ file: {PLANTED}, contains: "y" }}',
        'x = "zz-planted.md"',
    ],
)
def test_the_judge_is_the_deciders(line: str) -> None:
    needles = f"{PLANTED} zz-planted.md"
    shell = subprocess.run(  # noqa: S603 - the decider's own judge, sourced read-only
        ["bash", "-c", f'. "{ROOT / LK.DECIDER}" && gate__docs_only_judge "$1"', "judge", needles],  # noqa: S607 — `bash` resolved on PATH, as the gate's own legs run it
        input=f"m.py:1:{line}\n",
        capture_output=True,
        text=True,
        check=True,
    )
    python = [t for t in LK.quoted_tokens(line) if t in needles.split()]
    assert bool(shell.stdout.strip()) == bool(python), (line, shell.stdout, python)


def test_the_declaration_grammar_is_the_deciders(tmp_path: Path) -> None:
    mark = LK.decider_value("GATE_DOCS_ONLY_NONREAD")
    text = (
        f"#   {mark} a.md b/c.md — why\n"
        f"x = 1\n"
        f"    # {mark} d.md -- why # e.md\n"
        f'echo "# {mark} f.md — planted"\n'
        f"#: {mark} g.md — prose\n"
    )
    module = tmp_path / "m.py"
    module.write_text(text)
    shell = subprocess.run(  # noqa: S603 - the decider's own reader, sourced read-only
        [  # noqa: S607 — `bash` from PATH, as the gate runs it
            "bash",
            "-c",
            f'. "{ROOT / LK.DECIDER}" && gate_docs_only_nonreads "$1"',
            "nonreads",
            str(module),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = [(int(n), p) for n, p in (row.split(" ", 1) for row in shell.stdout.splitlines())]
    assert LK.declarations(text, mark) == expected == [(1, "a.md"), (1, "b/c.md"), (3, "d.md")]


def test_a_typed_list_under_the_key_s_name_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, "quality/x.py", f'PROSE_PATHS = ("{PLANTED}",)\nBOOK = "{PLANTED}"\n')
    _write(
        tmp_path,
        "scripts/y.sh",
        f"GATE_DOCS_ONLY_PATHS='docs/** {PLANTED}'\nLOOP_KEY_SKIP=(\n  {PLANTED}\n)\n",
    )
    found, scanned = LK.typed_exclusions(tmp_path)
    assert scanned == 2
    assert sorted((s.path, s.line, s.subject) for s in found) == [
        ("quality/x.py", 1, "PROSE_PATHS"),
        ("scripts/y.sh", 2, "LOOP_KEY_SKIP"),
    ]


def test_a_stale_declaration_is_named_and_a_fixture_is_not(tmp_path: Path) -> None:
    mark = LK.decider_value("GATE_DOCS_ONLY_NONREAD")
    _write(tmp_path, LK.GATE, STATIC_GATE)
    _write(tmp_path, "apps/a/tests/test_x.py", f"# {mark} {PLANTED} — its quote was deleted\n")
    _write(tmp_path, "quality/canary/90/fixture.py", f"# {mark} {PLANTED} — planted\n")
    stale, read = LK.stale_declarations(tmp_path)
    assert read == 1
    assert [(s.path, s.line, s.subject) for s in stale] == [("apps/a/tests/test_x.py", 1, PLANTED)]
    result = CHECKS.loop_key_exclusions_are_derived(tmp_path, {"id": "90"})
    assert [f.klass for f in result.findings] == ["stale-declaration"]


def test_without_the_decider_the_census_could_not_look(tmp_path: Path) -> None:
    with pytest.raises(CNL.CouldNotLook):
        LK.candidate_patterns(tmp_path)
    with pytest.raises(CNL.CouldNotLook):
        LK.decider_value("GATE_DOCS_ONLY_NONREAD", tmp_path)


def test_a_tree_with_no_scripts_is_read_against_the_running_decider(tmp_path: Path) -> None:
    repo = _scratch(tmp_path, gate=False)
    _write(repo, "apps/a.py", f'BOOK = "{PLANTED}"\n')
    assert not (repo / "scripts").exists()
    assert LK.reads(repo) == {PLANTED: ["apps/a.py:1"]}
    assert LK.prose_paths(repo) == (QUIET,)


def test_a_mark_that_declares_nothing_never_asks_for_a_gate(tmp_path: Path) -> None:
    repo = _scratch(tmp_path, gate=False)
    mark = LK.decider_value(LK.MEASURED_NAME)
    _write(repo, LK.DECIDER, f"{LK.MEASURED_NAME}='{mark}'\nBOOK=\"{PLANTED}\"\n")
    assert LK.reads(repo) == {PLANTED: [f"{LK.DECIDER}:2"]}
    assert LK.measured_at_commit(repo) == []


def test_a_measured_declaration_in_a_tree_with_no_gate_could_not_look(tmp_path: Path) -> None:
    repo = _scratch(tmp_path, gate=False)
    _measured(repo, "scripts/shape.py", PLANTED)
    with pytest.raises(CNL.CouldNotLook):
        LK.reads(repo)


def _measured(repo: Path, rel: str, path: str) -> None:
    mark = LK.decider_value(LK.MEASURED_NAME)
    _write(repo, rel, f'# {mark} {path} — the hook runs it on the staged bytes\nBOOK = "{path}"\n')


def test_a_measured_declaration_moves_its_module_s_quote_out(tmp_path: Path) -> None:
    repo = _scratch(tmp_path)
    _measured(repo, "scripts/shape.py", PLANTED)
    assert PLANTED not in LK.reads(repo)
    assert set(LK.prose_paths(repo)) == {PLANTED, QUIET}
    assert LK.measured_at_commit(repo) == [(PLANTED, "scripts/shape.py")]
    assert LK.measured_findings(repo) == ([], [], 1)


def test_a_second_module_quoting_the_path_keeps_it_read(tmp_path: Path) -> None:
    repo = _scratch(tmp_path)
    _measured(repo, "scripts/shape.py", PLANTED)
    _write(repo, "scripts/other.py", f'BOOK = "{PLANTED}"\n')
    assert LK.reads(repo)[PLANTED] == ["scripts/other.py:1"]
    assert LK.prose_paths(repo) == (QUIET,)


@pytest.mark.parametrize(
    "rel", ["scripts/tests/shape.py", "quality/shape.py", "scripts/slow.py", "scripts/unrun.py"]
)
def test_a_measured_line_outside_a_static_check_module_is_not_honoured(
    tmp_path: Path, rel: str
) -> None:
    repo = _scratch(tmp_path)
    _measured(repo, rel, PLANTED)
    assert LK.reads(repo)[PLANTED] == [f"{rel}:2"]
    assert LK.measured_at_commit(repo) == []
    stale, unrun, declared = LK.measured_findings(repo)
    assert (stale, declared) == ([], 1)
    assert [(s.path, s.subject) for s in unrun] == [(rel, PLANTED)]


def test_a_stale_measured_declaration_is_named(tmp_path: Path) -> None:
    repo = _scratch(tmp_path)
    mark = LK.decider_value(LK.MEASURED_NAME)
    _write(repo, "scripts/shape.py", f"# {mark} {PLANTED} — its quote was deleted\n")
    stale, unrun, _ = LK.measured_findings(repo)
    assert ([(s.path, s.line, s.subject) for s in stale], unrun) == (
        [("scripts/shape.py", 1, PLANTED)],
        [],
    )


def test_the_real_gate_runs_the_ledger_check_as_a_static_check() -> None:
    assert "scripts/ledger_check.py" in LK.static_check_modules(ROOT)


def test_rule_90_names_a_stale_and_an_unrun_measured_declaration(tmp_path: Path) -> None:
    repo = _scratch(tmp_path)
    mark = LK.decider_value(LK.MEASURED_NAME)
    _write(repo, "scripts/shape.py", f"# {mark} {PLANTED} — its quote was deleted\n")
    _measured(repo, "scripts/unrun.py", QUIET)
    result = CHECKS.loop_key_exclusions_are_derived(repo, {"id": "90"})
    assert sorted((f.klass, f.path) for f in result.findings) == [
        ("stale-measured", "scripts/shape.py"),
        ("unrun-measured", "scripts/unrun.py"),
    ]
