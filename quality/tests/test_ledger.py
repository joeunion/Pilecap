"""`quality.djb.ledger`, and `test_loop_ledger.sh`'s cases carried over by name."""

# names, never reads: docs/product/in-flight.md README.md scripts/test_impact.json — scratch paths
# does-not-cover: the environment fingerprint (`loop_env_fingerprint`); `env=` is taken as given.
# does-not-cover: a drive key's machine half and final digest; `drive_parts` re-derives the rest.
# does-not-cover: a read of the local drawer whose path is computed — the census reads spellings.
# deleted: loop_ledger twins that read check.sh's loop body — dies with the shim (8 below)
# pin: test_loop_run.py::test_the_leg_consults_before_it_measures_and_records_only_after_green
# pin: test_loop_run.py::test_the_bank_remembers_what_it_refused_and_its_rm_spares_the_memory
# pin: test_loop_run.py::test_mine_and_pr_never_reuse_on_a_docs_only_delta
# pin: test_loop_run.py::test_the_sync_is_wired_into_the_loop_leg_ahead_of_the_key
# pin: test_loop_run.py::test_a_commit_that_skipped_the_hook_meets_the_leg
# deleted: test_the_banner_takes_line_one_as_the_token_and_indents_the_rest — dies with the shim
# deleted: test_a_miss_prints_the_docs_only_line_by_default — dies with the shim
# pin: test_a_tree_miss_prints_three_lines_every_other_miss_two_and_the_detail_on_request
# deleted: test_the_local_loop_really_is_one_pass — dies with the shim
# pin: test_legs_loop_pytest.py::test_one_pass_in_one_slot_answers_as_the_shell_leg
# deleted: test_the_declaration_is_read_from_check_sh_and_not_kept_here — dies with the shim
# pin: test_a_shim_gate_s_full_legs_are_the_registry_s_members
# deleted: test_a_deletion_carries_no_tree_and_falls_back_to_the_working_tree — shell hook's
# pin: test_hook_pre_push.py::test_a_branch_deletion_measures_nothing
# narrowed: unfinished_run, bank_asks, key_that_could_not_look — pins: test_loop_run.py
# narrowed: docs_only_commit — test_legs_loop_pytest.py::test_a_docs_only_reuse_runs_no_pass…
# narrowed: equal_tree_row, fingerprint_globals, attributor — their check.sh asserts, vacuous

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from quality import loop_key
from quality.djb import ledger
from quality.tests.conftest import REAL_TIME_CEILING_S
from quality.tests.fixtures.scratch_ledger import real_ledger

pytestmark = pytest.mark.drives(
    "quality/djb/ledger.py",
    "quality/partition.py",
    "scripts/check.sh",
    "scripts/gate_refuse.sh",
    "scripts/githooks/",
    "scripts/loop_health.py",
    "scripts/test.sh",
)

STAMP = "2026-10-04T12:00:00Z"
ROWS = (
    f"v1 0123456789abcdef0123456789abcdef01234567 full {STAMP} ruff,mypy caller=pm-bank "
    "sanction=typed:gate-rung:quality%20rung%20the%20canary waited=0 took=3 leak-proof=ci:1 rc=0",
    f"v1 drive-v1:{'a' * 64} drive {STAMP} pm_merge exit=0 took=38 tree=abc parts=x:1,machine:2",
    f"v1 {'b' * 64}:{'c' * 64} partition {STAMP} caller=push-wall",
    f"v1 loop-v1:{'d' * 64} loop {STAMP} scope=mode=fast_own=- passes=1 tree=t env=e",
    f"v1 {'e' * 40} intent {STAMP} run=pending commit={'f' * 40} branch=pm/x",
    f"v1 {'e' * 40} run {STAMP} state=exit-2:selftest caller=pm-bank",
)


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str = "c") -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "--", *files)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD^{tree}")


# --- the grammar ----------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ROWS, ids=[r.split(" ")[2] for r in ROWS])
def test_one_row_per_kind_round_trips(line: str) -> None:
    row = ledger.parse(line)
    assert ledger.format(row) == line
    assert ledger.in_grammar(line)


def test_every_live_row_round_trips(request: pytest.FixtureRequest) -> None:
    path = real_ledger(request.config.rootpath)
    if path is None or not path.exists():
        return  # a checkout with no ledger has no row to hold to the grammar
    bad = [
        f"{path}:{n}" for n, line in ledger.rows(path) if ledger.format(ledger.parse(line)) != line
    ]
    assert bad == []


def test_the_live_ledger_has_one_row_grammar(request: pytest.FixtureRequest) -> None:
    path = real_ledger(request.config.rootpath)
    if path is None or not path.exists():
        return
    outside = [
        f"{path}:{n}"
        for n, line in ledger.rows(path)
        if not ledger.in_grammar(line) and not ledger.pre_grammar(line)
    ]
    assert outside == []


@pytest.mark.parametrize(
    "line",
    ["v1 key full", f"v2 key full {STAMP}", f"v1 key verdict {STAMP}", "loop-v1 x loop y"],
)
def test_a_line_outside_the_grammar_does_not_parse(line: str) -> None:
    with pytest.raises(ledger.MalformedRow):
        ledger.parse(line)


def test_a_planted_malformed_line_is_named_by_the_replay(scratch: Path) -> None:
    path = scratch / "verdicts"
    path.write_text(ROWS[2] + "\n" + "v1 nokind\n")
    said: list[str] = []
    assert ledger.replay(path, scratch, said.append) == 2
    assert said == [f"ledger replay: {path}:2 does not parse — fewer than four fields: 'v1 nokind'"]


# --- the writer -----------------------------------------------------------------------------------


def test_a_recorded_row_round_trips(scratch_ledger: Path) -> None:
    scope = "mode=fast scope=usage always=abc"
    key = ledger.loop_key("deadbeef", "envdigest", scope)
    fields = ["caller=unstated", f"scope={scope.replace(' ', '_')}", "passes=1", "tree=deadbeef"]
    ledger.append("loop", key, fields, path=scratch_ledger, stamp=STAMP)
    row = ledger.last(scratch_ledger, "loop", key)
    assert row is not None and row.key == key
    assert row.get("scope") == "mode=fast_scope=usage_always=abc"
    assert row.get("passes") == "1"
    assert ledger.format(row) == scratch_ledger.read_text().rstrip("\n")


@pytest.mark.parametrize(
    ("kind", "key", "fields", "stamp", "says"),
    [
        ("verdict", "k", [], STAMP, "is not a ledger kind"),
        ("loop", "two words", [], STAMP, "empty or holds whitespace"),
        ("loop", "", [], STAMP, "empty or holds whitespace"),
        ("loop", "k", ["a=b c"], STAMP, "field is empty or holds whitespace"),
        ("loop", "k", [""], STAMP, "field is empty or holds whitespace"),
        ("loop", "k", [], "2026-10-04 12:00", "is not UTC"),
        ("full", "k", ["sanction=the:drive:the%20push%20wall"], STAMP, "is not one of"),
        ("full", "k", ["sanction=typed:x:y"], STAMP, "at least 12 characters"),
    ],
)
def test_the_writer_refuses_and_records_nothing(
    scratch_ledger: Path, kind: str, key: str, fields: list[str], stamp: str, says: str
) -> None:
    with pytest.raises(ledger.Refused, match=says):
        ledger.append(kind, key, fields, path=scratch_ledger, stamp=stamp)
    assert not scratch_ledger.exists()


def test_an_idempotent_append_writes_a_line_once(scratch_ledger: Path) -> None:
    for _ in range(2):
        ledger.append(
            "run", "t" * 40, ["state=green"], path=scratch_ledger, stamp=STAMP, idempotent=True
        )
    assert len(scratch_ledger.read_text().splitlines()) == 1


def test_a_relative_ledger_path_is_refused(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJB_GATE_LEDGER", "verdicts")
    with pytest.raises(ledger.Refused, match="is relative"):
        ledger.ledger_path(scratch)


def test_the_sanction_is_one_field_of_an_enum_with_a_floor(request: pytest.FixtureRequest) -> None:
    for kind in ledger.SANCTION_KINDS:
        ledger.Sanction(kind, "drive", "a reason long enough to clear the floor").check()
    with pytest.raises(ledger.Refused, match="is not one of"):
        ledger.Sanction("the", "drive", "the push wall (DJB_GATE_CALLER=push-wall)").check()
    floor = (request.config.rootpath / "quality/reason_floor.py").read_text()
    assert "MIN_REASON = 12" in floor
    with pytest.raises(ledger.Refused, match="at least 12 characters"):
        ledger.Sanction.typed("x: y")
    ledger.Sanction.typed("gate-rung: quality rung, the canary self-test is the point")
    field = ledger.Sanction(
        "typed", "gate-rung", "quality/** rung — 100% the canary self-test"
    ).field()
    assert " " not in field and field.startswith("sanction=typed:gate-rung:")
    assert ledger.Sanction.parse(field.removeprefix("sanction=")) == ledger.Sanction(
        "typed", "gate-rung", "quality/** rung — 100% the canary self-test"
    )
    with pytest.raises(ledger.Refused, match="no who and reason"):
        ledger.Sanction.parse("gate-rung: quality rung — set by hand")


# --- the loop key ---------------------------------------------------------------------------------


def test_the_tree_and_the_environment_are_both_in_the_key() -> None:
    a = ledger.loop_key("treeone", "env-a", "mode=fast scope=- always=abc")
    assert a != ledger.loop_key("treetwo", "env-a", "mode=fast scope=- always=abc")
    assert a != ledger.loop_key("treeone", "env-b", "mode=fast scope=- always=abc")


def test_the_same_tree_at_two_scopes_is_two_keys() -> None:
    narrow = ledger.loop_key("deadbeef", "e", "mode=fast own=usage scope=usage always=abc")
    wide = ledger.loop_key("deadbeef", "e", "mode=fast own=usage scope=usage files always=abc")
    assert narrow != wide


def test_a_recorded_scope_is_read_back_whatever_its_underscores_were() -> None:
    scope = (
        "mode=fast own=djb_notes example_portal scope=core djb_notes always=x "
        "tests=- seeded=apps/core/tests/test_a_b.py apps/x/tests/test_c.py alwayson=y map=z"
    )
    recorded = scope.replace(" ", "_")
    vocabulary = frozenset({"core", "djb_notes", "example", "example_portal", "notes", "djb"})
    assert scope in set(ledger.scope_candidates(recorded, vocabulary))


def test_a_loop_row_whose_key_its_inputs_do_not_derive_is_a_mismatch(scratch: Path) -> None:
    scope = "mode=fast own=core scope=core always=x"
    good = ledger.loop_key("t1", "e1", scope)
    rows = [
        f"v1 {good} loop {STAMP} scope={scope.replace(' ', '_')} passes=1 tree=t1 env=e1",
        f"v1 {good} loop {STAMP} scope={scope.replace(' ', '_')} passes=1 tree=t2 env=e1",
    ]
    path = scratch / "verdicts"
    path.write_text("\n".join(rows) + "\n")
    said: list[str] = []
    assert ledger.replay(path, scratch, said.append) == 2
    assert said[-1].startswith(f"ledger replay: MISMATCH at {path}:2 (loop {good}): ")
    path.write_text(rows[0] + "\n")
    said.clear()
    assert ledger.replay(path, scratch, said.append) == 0
    assert "       1  loop: key re-derived" in said


def test_a_key_tree_outranks_the_tree_in_the_key() -> None:
    row = ledger.parse(
        f"v1 {ledger.loop_key('kt', 'e', 'mode=fast')} loop {STAMP} "
        "scope=mode=fast tree=t env=e key-tree=kt"
    )
    ledger.replay_row(row, ledger.Replay(Path(".")))


# --- the docs-only decider ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "admitted"),
    [
        ("docs/product/in-flight.md", True),
        ("README.md", True),
        (".claude/skills/x/SKILL.md", True),
        ("scripts/test_impact.json", True),
        ("apps/manual.md", False),
        ("docsx/a.md", False),
        ("scripts/gate_member_durations.json", False),
    ],
)
def test_the_declared_list_decides_a_path_alone(path: str, admitted: bool, scratch: Path) -> None:
    assert ledger.docs_only_admits(path, root=scratch) is admitted


def test_the_fold_outputs_are_admitted_by_derivation(scratch_repo: Callable[..., Path]) -> None:
    repo = scratch_repo()
    base = _commit(
        repo,
        {
            "quality/budgets.yaml": "a: 9\nb: 4\n",
            "scripts/gate_member_durations.json": '{"x": 12}\n',
        },
    )
    lowered = _commit(
        repo,
        {
            "quality/budgets.yaml": "a: 8\nb: 4\n",
            "scripts/gate_member_durations.json": '{"x": 31}\n',
        },
    )
    raised = _commit(repo, {"quality/budgets.yaml": "a: 10\nb: 4\n"})
    reworded = _commit(repo, {"scripts/gate_member_durations.json": '{"y": 31}\n'})
    assert ledger.docs_only_admits("quality/budgets.yaml", base, lowered, root=repo)
    assert ledger.docs_only_admits("scripts/gate_member_durations.json", base, lowered, root=repo)
    assert not ledger.docs_only_admits("quality/budgets.yaml", lowered, raised, root=repo)
    assert not ledger.docs_only_admits(
        "scripts/gate_member_durations.json", raised, reworded, root=repo
    )
    assert not ledger.docs_only_admits("quality/budgets.yaml", root=repo)


WALLS = "scripts/gate_member_durations.json"


def walls_table(members: dict[str, int], tree: str = "a" * 40) -> str:
    """A walls table in the fold's own layout: one member row per line, a measured stamp."""
    rows = ",\n".join(f'    "{name}": {{"ubuntu-latest": {n}}}' for name, n in members.items())
    return (
        f'{{\n  "schema": "member-walls/2",\n  "measured_at": {{\n'
        f'    "ubuntu-latest": "run:1 tree:{tree}"\n  }},\n  "members": {{\n{rows}\n  }}\n}}\n'
    )


def test_a_walls_table_that_gains_a_member_row_is_admitted(
    scratch_repo: Callable[..., Path],
) -> None:
    """A fold harvesting a NEW member row, a removed one and a new stamp: prices, by shape."""
    repo = scratch_repo()
    base = _commit(repo, {WALLS: walls_table({"ruff": 3, "mypy": 9})})
    grown = _commit(
        repo, {WALLS: walls_table({"ruff": 4, "mypy": 9, "gate-tests": 7275}, "b" * 40)}
    )
    shrunk = _commit(repo, {WALLS: walls_table({"ruff": 4, "gate-tests": 7275}, "b" * 40)})
    assert ledger.docs_only_admits(WALLS, base, grown, root=repo)
    assert ledger.docs_only_admits(WALLS, grown, shrunk, root=repo)


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(
            lambda t: t.replace('  "members": {', '  # planted\n  "members": {'), id="comment"
        ),
        pytest.param(lambda t: t.replace('"members"', '"memberz"'), id="key-rename"),
        pytest.param(
            lambda t: t.replace('"schema": "member-walls/2"', '"schema": "x"'), id="schema"
        ),
    ],
)
def test_a_walls_table_with_a_non_row_line_is_refused(
    scratch_repo: Callable[..., Path], edit: Callable[[str], str]
) -> None:
    repo = scratch_repo()
    text = walls_table({"ruff": 3, "mypy": 9})
    base = _commit(repo, {WALLS: text})
    planted = _commit(repo, {WALLS: edit(walls_table({"ruff": 4, "mypy": 9, "fe": 1}))})
    assert not ledger.docs_only_admits(WALLS, base, planted, root=repo)


BASELINE = ".secrets.baseline"


def secrets_baseline(results: dict[str, list[tuple[str, int]]], stamp: str = "") -> str:
    import json

    data: dict[str, object] = {"version": "1.5.0", "plugins_used": [{"name": "KeywordDetector"}]}
    data["results"] = {
        path: [
            {
                "type": "Secret Keyword",
                "filename": path,
                "hashed_secret": digest,
                "is_verified": False,
                **({"line_number": line} if line else {}),
            }
            for digest, line in found
        ]
        for path, found in results.items()
    }
    if stamp:
        data["generated_at"] = stamp
    return json.dumps(data, indent=2) + "\n"


def test_a_baseline_whose_only_change_is_the_stamp_is_admitted(
    scratch_repo: Callable[..., Path],
) -> None:
    repo = scratch_repo()
    found = {"a.py": [("1" * 40, 0)]}
    base = _commit(repo, {BASELINE: secrets_baseline(found)})
    stamped = _commit(repo, {BASELINE: secrets_baseline(found, "2026-10-24T00:00:00Z")})
    renumbered = _commit(
        repo, {BASELINE: secrets_baseline({"a.py": [("1" * 40, 9)]}, "2026-10-24T01:00:00Z")}
    )
    moved = _commit(repo, {BASELINE: secrets_baseline({"b.py": [("1" * 40, 4)]})})
    assert BASELINE in ledger.docs_only_derived()
    assert ledger.docs_only_admits(BASELINE, base, stamped, root=repo)
    assert ledger.docs_only_admits(BASELINE, stamped, renumbered, root=repo)
    assert ledger.docs_only_admits(BASELINE, renumbered, moved, root=repo)
    assert not ledger.docs_only_admits(BASELINE, root=repo), "no two ends: never admitted"


@pytest.mark.parametrize(
    "after",
    [
        pytest.param({"a.py": [("1" * 40, 0)], "b.py": [("2" * 40, 0)]}, id="new-finding"),
        pytest.param({"a.py": [("2" * 40, 0)]}, id="replaced-finding"),
        pytest.param({}, id="finding-dropped"),
    ],
)
def test_a_baseline_with_a_new_hashed_secret_is_not_admitted(
    scratch_repo: Callable[..., Path], after: dict[str, list[tuple[str, int]]]
) -> None:
    repo = scratch_repo()
    base = _commit(repo, {BASELINE: secrets_baseline({"a.py": [("1" * 40, 0)]})})
    changed = _commit(repo, {BASELINE: secrets_baseline(after)})
    assert not ledger.docs_only_admits(BASELINE, base, changed, root=repo)
    plugin = secrets_baseline({"a.py": [("1" * 40, 0)]}).replace("KeywordDetector", "Other")
    swapped = _commit(repo, {BASELINE: plugin})
    assert not ledger.docs_only_admits(BASELINE, base, swapped, root=repo), "a plugin moved"
    broken = _commit(repo, {BASELINE: "{ not json\n"})
    assert not ledger.docs_only_admits(BASELINE, swapped, broken, root=repo)


def test_the_three_docs_only_roads_answer_from_one_decider(
    scratch_repo: Callable[..., Path],
) -> None:
    repo = scratch_repo()
    a = _commit(repo, {"docs/product/in-flight.md": "1\n", "apps/x.py": "x = 1\n"})
    b = _commit(repo, {"docs/product/in-flight.md": "2\n", "README.md": "r\n"})
    c = _commit(repo, {"apps/x.py": "x = 2\n"})
    assert ledger.docs_only_delta(repo, a, b, None) == [
        ("docs", "README.md"),
        ("docs", "docs/product/in-flight.md"),
    ]
    assert ledger.docs_only_delta(repo, a, b, frozenset({"docs/product/in-flight.md"})) == [
        ("code", "README.md"),
        ("docs", "docs/product/in-flight.md"),
    ]
    assert ledger.docs_only_delta(repo, b, c, None) == [("code", "apps/x.py")]


def test_a_docs_only_admission_the_decider_refuses_is_a_mismatch(
    scratch_repo: Callable[..., Path], scratch: Path
) -> None:
    repo = scratch_repo()
    a = _commit(repo, {"docs/product/in-flight.md": "1\n", "apps/x.py": "x = 1\n"})
    b = _commit(repo, {"docs/product/in-flight.md": "2\n"})
    c = _commit(repo, {"apps/x.py": "x = 2\n"})
    reason = "docs-only%20from={}%20paths=1%20readers=static"
    path = scratch / "verdicts"
    path.write_text(f"v1 {b} full {STAMP} ruff sanction=docs-only:legacy:{reason.format(a)}\n")
    said: list[str] = []
    assert ledger.replay(path, repo, said.append) == 0
    assert "       1  docs-only: admission re-derived" in said
    path.write_text(f"v1 {c} full {STAMP} ruff sanction=docs-only:legacy:{reason.format(b)}\n")
    said.clear()
    assert ledger.replay(path, repo, said.append) == 2
    assert "the decider does not admit ['apps/x.py']" in said[-1]


# --- the drive key's parts ------------------------------------------------------------------------


JUDGE = {
    "quality/__init__.py": "",
    "quality/tests/__init__.py": "",
    "quality/tests/test_drives.py": "from quality.tests.drives import verdict\n",
    "quality/tests/drives.py": "VERDICT = 0\n",
    "quality/tests/test_harness.py": "def test_x():\n    pass\n",
    "quality/could_not_look.py": "class CouldNotLook(Exception):\n    pass\n",
    "scripts/tests/drive_preamble.sh": "# preamble\n",
    "scripts/tests/test_undeclaring.sh": "#!/usr/bin/env bash\n# drives: scripts/undeclared.sh\n",
    "scripts/undeclared.sh": "echo hi\n",
}


def test_the_judge_is_in_every_drive_key_and_a_harness_test_is_not(
    scratch_repo: Callable[..., Path],
) -> None:
    repo = scratch_repo()
    drive = "scripts/tests/test_undeclaring.sh"
    before = ledger.drive_parts(repo, _commit(repo, JUDGE), drive)
    assert set(before) == {
        drive,
        "scripts/tests/drive_preamble.sh",
        "quality/tests/",
        "scripts/undeclared.sh",
    }
    judged = ledger.drive_parts(
        repo, _commit(repo, {"quality/tests/drives.py": "VERDICT = 1\n"}), drive
    )
    assert judged["quality/tests/"] != before["quality/tests/"]
    assert {k: v for k, v in judged.items() if k != "quality/tests/"} == {
        k: v for k, v in before.items() if k != "quality/tests/"
    }
    harness = ledger.drive_parts(
        repo, _commit(repo, {"quality/tests/test_harness.py": "def test_y():\n    pass\n"}), drive
    )
    assert harness == judged
    imported = ledger.drive_parts(
        repo,
        _commit(
            repo,
            {
                "quality/tests/drives.py": "from quality.could_not_look import CouldNotLook\n",
                "quality/could_not_look.py": "class CouldNotLook(ValueError):\n    pass\n",
            },
        ),
        drive,
    )
    unrelated = ledger.drive_parts(repo, _commit(repo, {"quality/other.py": "x = 1\n"}), drive)
    assert imported["quality/tests/"] != judged["quality/tests/"]
    assert unrelated == imported


SHIM_GATE = {
    "scripts/check.sh": '#!/usr/bin/env bash\nexec python3 -m quality.djb gate "$@"\n',
    "quality/djb/legs/_run.py": (
        'LIBRARIES = (\n    "scripts/lib_b.sh",\n    "scripts/lib_a.sh",\n)\n'
    ),
    "quality/djb/modes.py": "MODES = 1\n",
    "scripts/lib_a.sh": "a=1\n",
    "scripts/lib_b.sh": "b=1\n",
    "scripts/tests/test_gate.sh": "#!/usr/bin/env bash\n# drives: scripts/check.sh\n",
}


def test_a_drive_declaring_a_shim_gate_is_keyed_on_its_package_and_libraries(
    scratch_repo: Callable[..., Path],
) -> None:
    repo = scratch_repo()
    drive = "scripts/tests/test_gate.sh"
    parts = ledger.drive_parts(repo, _commit(repo, {**JUDGE, **SHIM_GATE}), drive)
    assert {"quality/djb/", "scripts/lib_a.sh", "scripts/lib_b.sh"} <= set(parts)
    moved = ledger.drive_parts(repo, _commit(repo, {"quality/djb/modes.py": "MODES = 2\n"}), drive)
    assert moved["quality/djb/"] != parts["quality/djb/"]


def test_a_shim_gate_s_full_legs_are_the_registry_s_members(scratch: Path) -> None:
    (scratch / "scripts").mkdir()
    (scratch / "scripts/check.sh").write_text(SHIM_GATE["scripts/check.sh"])
    (scratch / "quality/djb/legs").mkdir(parents=True)
    members = ledger.full_legs(scratch)
    assert members[0] == "db-pin" and "pytest-x2" in members and "selftest" in members
    assert members == ledger.registry_members(scratch)


def test_a_drive_rows_recorded_parts_are_re_derived_from_its_tree(
    scratch_repo: Callable[..., Path], scratch: Path
) -> None:
    repo = scratch_repo()
    tree = _commit(repo, JUDGE)
    parts = ledger.drive_parts(repo, tree, "scripts/tests/test_undeclaring.sh")
    recorded = ",".join(f"{k}:{v[:12]}" for k, v in parts.items()) + ",machine:0123456789ab"
    path = scratch / "verdicts"
    path.write_text(
        f"v1 drive-v1:{'a' * 64} drive {STAMP} undeclaring exit=0 tree={tree} parts={recorded}\n"
    )
    said: list[str] = []
    assert ledger.replay(path, repo, said.append) == 0
    assert "       1  drive: parts re-derived" in said
    path.write_text(
        path.read_text().replace(
            f"scripts/undeclared.sh:{parts['scripts/undeclared.sh'][:12]}",
            "scripts/undeclared.sh:000000000000",
        )
    )
    said.clear()
    assert ledger.replay(path, repo, said.append) == 2
    assert "part scripts/undeclared.sh recorded 000000000000" in said[-1]


# --- the shell subject: `test_loop_ledger.sh`'s checkout, and `gate_ledger.sh` sourced into it ----

ROOT = Path(__file__).resolve().parents[2]
SHELL_LIB = ROOT / "scripts" / "gate_ledger.sh"
ENV_FILE = (
    "DATABASE_NAME=djb_checkout_one\n"
    "AWS_STORAGE_BUCKET_NAME=djb-checkout-one\n"  # pragma: allowlist secret
    "SECRET_KEY=not-a-real-key\n"  # pragma: allowlist secret
    "DEBUG=1\n"
)
CARRIED = ("db.sh", "rung_start.sh", "bash_only.sh", "gate_refuse.sh")


def _checkout(scratch_repo: Callable[..., Path], name: str = "repo") -> Path:
    """A repository holding what the drive's checkouts hold, in its one base commit."""
    repo = scratch_repo(name)
    (repo / ".venv/lib/python3.12/site-packages/thing-1.0.dist-info").mkdir(parents=True)
    (repo / ".env").write_text(ENV_FILE)
    (repo / "scripts").mkdir()
    for script in CARRIED:
        shutil.copy2(ROOT / "scripts" / script, repo / "scripts" / script)
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "-m", "base")
    return repo


def _sh(
    capture: Callable[..., object],
    cwd: Path,
    script: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    """`script` under `set -euo pipefail` with `gate_ledger.sh` sourced: (exit, output)."""
    done = capture(
        ["bash", "-c", f'set -euo pipefail\n. "{SHELL_LIB}" || exit 2\n{script}'],
        cwd=cwd,
        env=env,
    )
    rc, path = done.rc, done.path  # type: ignore[attr-defined]
    return rc, path.read_text(errors="replace")


def _hex64(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _sha40(text: str) -> str:
    return _hex64(text)[:40]


def _crafted_components(
    env_file: str = "",
    excluded: str = "AWS_STORAGE_BUCKET_NAME,DATABASE_NAME",
    dists: str = "",
    head: str = "",
    merge_base: str = "",
    reads: str = "",
) -> str:
    return (
        f"env-file={env_file or _hex64('envfile')} excluded={excluded} "
        f"dists={dists or _hex64('dists')} env-reads={reads or _hex64('reads')} "
        f"head={head or _sha40('head')} merge-base={merge_base or _sha40('base')}"
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _tree_in(capture: Callable[..., object], repo: Path) -> str:
    """The full gate's own key, `gate_measured_tree`, of `repo`'s working state."""
    rc, out = _sh(capture, repo, "gate_measured_tree 2>/dev/null")
    assert rc == 0, out
    return out.strip()


# --- group A: the drive's cases from its head to the consult path ---------------------------------

A_SCOPE = "mode=fast scope=- always=abc"
A_CANON = "mode=fast_scope=-_always=abc"
# names, never reads: docs/product/queue.md — a scratch checkout's path
A_QUEUE = "docs/product/queue.md"
A_HEX = frozenset("0123456789abcdef")


def _a_since_docs_only(out: str) -> bool:
    """A line `since banked head <8 hex>: 1 path(s) changed; docs-only: yes`, whole."""
    head, tail = "since banked head ", ": 1 path(s) changed; docs-only: yes"
    return any(
        line.startswith(head)
        and line.endswith(tail)
        and len(short := line[len(head) : -len(tail)]) == 8
        and set(short) <= A_HEX
        for line in out.splitlines()
    )


def _a_in_order(text: str, *needles: str) -> bool:
    at = 0
    for needle in needles:
        at = text.find(needle, at)
        if at < 0:
            return False
        at += len(needle)
    return True


def _a_said(capture: Callable[..., object], repo: Path, script: str) -> dict[str, str]:
    """Run `script` and answer every `@name=value` line it printed; any other exit is red."""
    rc, out = _sh(capture, repo, script)
    assert rc == 0, out
    said: dict[str, str] = {}
    for line in out.splitlines():
        if line.startswith("@") and "=" in line:
            name, value = line[1:].split("=", 1)
            said[name] = value
    return said


def _a_rc(capture: Callable[..., object], repo: Path, call: str, before: str = "") -> int:
    rc, out = _sh(capture, repo, f'{before}\nrc=0; {call} >/dev/null 2>&1 || rc=$?\necho "@rc=$rc"')
    assert rc == 0, out
    return int(out.rsplit("@rc=", 1)[1].strip())


def _a_comp(
    env_file: str = "",
    excluded: str = "",
    dists: str = "",
    head: str = "",
    merge_base: str = "",
    reads: str = "",
) -> str:
    return _crafted_components(
        env_file,
        excluded or "AWS_STORAGE_BUCKET_NAME,DATABASE_NAME",
        dists,
        head,
        merge_base,
        reads,
    )


def _a_plant_row(ledger_path: Path, canon: str, tree: str, env: str, comp: str = "") -> None:
    with ledger_path.open("a") as rows:
        rows.write(
            f"v1 loop-v1:{1:064d} loop 2026-09-07T00:00:00Z caller=drive scope={canon} "
            f"passes=1 tree={tree} env={env}{' ' + comp if comp else ''}\n"
        )


def _a_attr(
    capture: Callable[..., object], repo: Path, tree: str, env: str, scope: str, comp: str = ""
) -> tuple[int, str]:
    """`loop_ledger_attribute`'s exit and both streams, under `LOOP_ENV_COMPONENTS=comp`."""
    rc, out = _sh(
        capture,
        repo,
        f"LOOP_ENV_COMPONENTS='{comp}'\n"
        f'rc=0; loop_ledger_attribute {tree} {env} "{scope}" 2>&1 || rc=$?; exit "$rc"',
    )
    return rc, out


def _a_token(
    capture: Callable[..., object], repo: Path, tree: str, env: str, scope: str, comp: str = ""
) -> str:
    """The drive's `attr_token`: line 1 of the attributor's stdout."""
    _, out = _sh(
        capture,
        repo,
        f"LOOP_ENV_COMPONENTS='{comp}'\n"
        f'loop_ledger_attribute {tree} {env} "{scope}" 2>/dev/null || true',
    )
    return out.split("\n", 1)[0]


def _a_stdout(capture: Callable[..., object], repo: Path, call: str, before: str = "") -> str:
    """`$(call)`'s stdout as the drive's command substitution sees it."""
    rc, out = _sh(capture, repo, f'{before}\nv=$({call} 2>/dev/null)\nprintf "\\n@v=%s" "$v"')
    assert rc == 0, out
    return out.rsplit("\n@v=", 1)[1]


def _a_key(capture: Callable[..., object], repo: Path, tree: str, scope: str = A_SCOPE) -> str:
    return _a_stdout(capture, repo, f'loop_ledger_key {tree} "{scope}"')


def _a_fingerprint(capture: Callable[..., object], repo: Path) -> str:
    return _a_stdout(capture, repo, "loop_env_fingerprint")


def test_the_row_carries_tree_and_env_appended_after_passes(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    comp = _a_comp()
    said = _a_said(
        capture,
        repo,
        f'key=$(loop_ledger_key treeone "{A_SCOPE}")\n'
        f"LOOP_ENV_COMPONENTS='{comp}'\n"
        f'loop_ledger_record "$key" "{A_SCOPE}" 1 aaaabbbb ccccdddd\n'
        'printf "@row=%s\\n" "$(loop_ledger_lookup "$key")"\n'
        'LOOP_ENV_COMPONENTS=""\n'
        f'bare=$(loop_ledger_key treetwo "{A_SCOPE}")\n'
        f'loop_ledger_record "$bare" "{A_SCOPE}" 1 eeeeffff 11112222\n'
        'printf "@bare=%s\\n" "$(loop_ledger_lookup "$bare")"',
    )
    row = said["row"]
    assert " passes=1 tree=aaaabbbb env=ccccdddd " in row, row
    want = f" passes=1 tree=aaaabbbb env=ccccdddd {comp}"
    assert want in row, row
    assert _a_in_order(row, want + " waited=", " took="), row
    assert " passes=1 tree=eeeeffff env=11112222 waited=" in said["bare"], said["bare"]


def test_both_verdict_rows_record_what_the_run_COST(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    said = _a_said(
        capture,
        repo,
        f'key=$(loop_ledger_key costtree "{A_SCOPE}")\n'
        "GATE_LEASE_WAITED=0; GATE_SLOT_WAITED=94; GATE_PYTEST_TOOK=212\n"
        f'loop_ledger_record "$key" "{A_SCOPE}" 1 costtree envdigest\n'
        'printf "@row=%s\\n" "$(loop_ledger_lookup "$key")"\n'
        "GATE_LEASE_WAITED=0; GATE_SLOT_WAITED=0; GATE_PYTEST_TOOK=0\n"
        f'zkey=$(loop_ledger_key zerotree "{A_SCOPE}")\n'
        f'loop_ledger_record "$zkey" "{A_SCOPE}"\n'
        'printf "@zrow=%s\\n" "$(loop_ledger_lookup "$zkey")"',
    )
    assert " waited=94 took=212" in said["row"], said["row"]
    assert " waited=0 took=0" in said["zrow"], said["zrow"]


def test_a_row_without_the_cost_fields_is_still_a_hit(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    key = _a_key(capture, repo, "pretree")
    said = _a_said(
        capture,
        repo,
        "printf 'v1 %s loop 2026-09-01T00:00:00Z caller=unstated "
        "scope=mode=fast_scope=-_always=abc passes=1 tree=pretree env=envdigest\\n' "
        f'"{key}" >>"$(gate_ledger_path)"\n'
        f'rc=0; row=$(loop_ledger_lookup "{key}") || rc=$?\n'
        'printf "@rc=%s\\n@row=%s\\n" "$rc" "$row"',
    )
    assert said["rc"] == "0"
    assert said["row"].endswith(" tree=pretree env=envdigest"), said["row"]
    assert "waited=" not in said["row"]


def test_a_row_written_before_those_fields_existed_still_hits(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    key = _a_key(capture, repo, "treeone")
    with scratch_ledger.open("a") as rows:
        rows.write(
            f"v1 {key} loop 2026-09-07T00:00:00Z caller=drive "
            "scope=mode=fast_scope=-_always=abc passes=1\n"
        )
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{key}"') == 0


def test_the_attributor_names_which_of_the_three_lines_moved(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    assert _a_token(capture, repo, "T", "E", A_SCOPE) == "no-ledger"
    _a_plant_row(scratch_ledger, A_CANON, "TREEA", "ENVA")
    assert _a_token(capture, repo, "TREEB", "ENVA", A_SCOPE) == "tree"
    assert _a_token(capture, repo, "TREEA", "ENVB", A_SCOPE) == "env"
    assert _a_token(capture, repo, "TREEA", "ENVA", "mode=fast scope=core always=abc") == "scope"
    assert _a_token(capture, repo, "TREEZ", "ENVZ", "mode=fast scope=zzz always=abc") == "unmatched"
    _, out = _sh(capture, repo, f'loop_ledger_attribute TREEB ENVA "{A_SCOPE}" 2>/dev/null')
    assert "banked row carries no components (recorded before they were)" in out, out
    library = SHELL_LIB.read_text()
    assert "IT NAMES THE COMPONENT NOW, BECAUSE THE ROW CARRIES ONE" in library
    assert library.count("NAMES THE LINE, NOT THE COMPONENT") == 0


def test_the_attributor_reads_the_rows_components_most_specific_first(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    e, d = _hex64("envfile"), _hex64("dists")
    h0, b0 = _sha40("head-banked"), _sha40("base-banked")
    h1, b1 = _sha40("head-now"), _sha40("base-now")
    scratch_ledger.write_text("")
    _a_plant_row(scratch_ledger, A_CANON, "TREEA", "ENVA", _a_comp(e, "", d, h0, b0))

    def token(tree: str, comp: str) -> str:
        return _a_token(capture, repo, tree, "ENVB", A_SCOPE, comp)

    other_env, other_dists = _hex64("other-envfile"), _hex64("other-dists")
    assert token("TREEB", _a_comp(e, "", d, h1, b1)) == "tree"
    assert token("TREEA", _a_comp(e, "", d, h1, b0)) == "env:head"
    assert token("TREEA", _a_comp(e, "", d, h0, b1)) == "env:merge-base"
    assert token("TREEA", _a_comp(other_env, "", d, h0, b0)) == "env:env-file"
    assert token("TREEA", _a_comp(e, "", other_dists, h0, b0)) == "env:dists"
    assert token("TREEA", _a_comp(e, "DATABASE_NAME", d, h0, b0)) == "env:excluded"
    assert token("TREEA", _a_comp(other_env, "", other_dists, h0, b0)) == "env:env-file,dists"
    assert token("TREEB", _a_comp(e, "", other_dists, h1, b1)) == "unmatched"
    _, out = _sh(
        capture,
        repo,
        f"LOOP_ENV_COMPONENTS='{_a_comp(e, '', d, h1, b1)}'\n"
        f'loop_ledger_attribute TREEB ENVB "{A_SCOPE}" 2>/dev/null',
    )
    assert "banked row: tree=TREEA" in out, out


def test_the_tree_token_says_what_moved_and_whether_it_was_only_docs(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    e, d = _hex64("envfile"), _hex64("dists")
    _commit(repo, {A_QUEUE: "the queue\n"}, "a docs file to move")
    banked = _git(repo, "rev-parse", "HEAD")
    scratch_ledger.write_text("")
    _a_plant_row(scratch_ledger, A_CANON, "TREEA", "ENVA", _a_comp(e, "", d, banked, banked))
    _commit(repo, {A_QUEUE: "the queue\none more row\n"}, "queue row rowed [docs-only]")
    head = _git(repo, "rev-parse", "HEAD")
    _, out = _a_attr(capture, repo, "TREEB", "ENVB", A_SCOPE, _a_comp(e, "", d, head, head))
    assert out.split("\n", 1)[0] == "tree", out
    assert _a_since_docs_only(out), out
    with (repo / "scripts/db.sh").open("a") as script:
        script.write("a source change\n")
    _git(repo, "add", "scripts/db.sh")
    _git(repo, "commit", "-q", "-m", "a source change")
    head = _git(repo, "rev-parse", "HEAD")
    _, out = _a_attr(capture, repo, "TREEB", "ENVB", A_SCOPE, _a_comp(e, "", d, head, head))
    assert "docs-only: no" in out, out


def test_an_equal_tree_row_outranks_a_differing_tree_row_whatever_the_file_order(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    e, d = _hex64("envfile"), _hex64("dists")
    hf, bf = _sha40("head-foreign"), _sha40("base-foreign")
    h0, b0 = _sha40("head-mine"), _sha40("base-mine")
    foreign = ("TREEFOREIGN", "ENVF", _a_comp(e, "", d, hf, bf))
    own = ("TREEMINE", "ENVM", _a_comp(_hex64("other-envfile"), "", d, h0, b0))
    mine = _a_comp(e, "", d, h0, b0)
    for first, second in ((foreign, own), (own, foreign)):
        scratch_ledger.write_text("")
        _a_plant_row(scratch_ledger, A_CANON, *first)
        _a_plant_row(scratch_ledger, A_CANON, *second)
        assert _a_token(capture, repo, "TREEMINE", "ENVX", A_SCOPE, mine) == "env:env-file"

    readme = (repo / "README.md").read_text()
    _commit(repo, {"README.md": readme + "far\n"}, "the far banked head")
    far = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"README.md": readme + "far\nnear\n"}, "a commit between the two")
    _commit(repo, {"README.md": readme + "far\nnear\nnearer\n"}, "the near banked head")
    near = _git(repo, "rev-parse", "HEAD")
    scratch_ledger.write_text("")
    _a_plant_row(scratch_ledger, A_CANON, "TREEFAR", "ENVF", _a_comp(e, "", d, far, far))
    _a_plant_row(scratch_ledger, A_CANON, "TREENEAR", "ENVN", _a_comp(e, "", d, near, near))
    head = _git(repo, "rev-parse", "HEAD")
    _, out = _a_attr(capture, repo, "TREEB", "ENVB", A_SCOPE, _a_comp(e, "", d, head, head))
    assert out.split("\n", 1)[0] == "tree", out
    assert "banked row: tree=TREENEAR" in out, out
    assert f"since banked head {near[:8]}: 0 path(s) changed" in out, out

    _commit(repo, {A_QUEUE: "the queue\n"}, "a docs file to move")
    banked = _git(repo, "rev-parse", "HEAD")
    scratch_ledger.write_text(
        "".join(
            f"v1 loop-v1:{i:064d} loop 2026-09-07T00:00:00Z caller=drive scope={A_CANON} "
            f"passes=1 tree=FOREIGN{i} env=ENVF{i} {_a_comp(e, '', d, far, far)}\n"
            for i in range(1, 21)
        )
    )
    _a_plant_row(
        scratch_ledger, A_CANON, "TREEBANKED", "ENVBANKED", _a_comp(e, "", d, banked, banked)
    )
    _commit(repo, {A_QUEUE: "the queue\none more row\n"}, "queue row rowed [docs-only]")
    head = _git(repo, "rev-parse", "HEAD")
    drifted = _a_comp(e, "", d, head, head)
    rc, out = _a_attr(capture, repo, "TREEDRIFTED", "ENVDRIFTED", A_SCOPE, drifted)
    assert out.split("\n", 1)[0] == "tree", out
    assert _a_since_docs_only(out), out
    library = SHELL_LIB.read_text()
    assert "AN EQUAL-`tree` ROW ALWAYS" in library
    assert "THE NEAREST BANKED HEAD WINS" in library
    assert rc == 0


def test_the_fingerprint_globals_survive_the_call_that_sets_them(
    capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    said = _a_said(
        capture,
        ROOT,
        'LOOP_ENV_FINGERPRINT=""; LOOP_ENV_COMPONENTS=""\n'
        "loop_env_fingerprint >/dev/null 2>&1 || true\n"
        'printf "@fp=%s\\n@comp=%s\\n" "$LOOP_ENV_FINGERPRINT" "$LOOP_ENV_COMPONENTS"\n'
        'LOOP_ENV_FINGERPRINT=""\n'
        f'_discard=$(loop_ledger_key sometree "{A_SCOPE}" || true)\n'
        'printf "@after=%s\\n" "$LOOP_ENV_FINGERPRINT"',
    )
    assert said["fp"][:1] in A_HEX, said
    assert _a_in_order(said["comp"], "env-file=", "dists=", "merge-base="), said
    assert said["after"] == ""


def test_the_census_counts_rows_and_reports_a_seed(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    assert _a_stdout(capture, repo, "loop_ledger_census").startswith("0 rows (0 seeded")
    scratch_ledger.write_text(
        "".join(
            f"v1 loop-v1:{n:064d} loop 2026-09-07T00:00:0{n - 1}Z caller=drive "
            "scope=s passes=1 tree=T env=E\n"
            for n in (1, 2)
        )
    )
    seed = Path(f"{scratch_ledger}-seed")
    seed.write_text("seeded=2 from=/somewhere/else/.git/djb-loop-verdicts\n")
    assert (
        _a_stdout(capture, repo, "loop_ledger_census")
        == "2 rows (2 seeded from /somewhere/else/.git/djb-loop-verdicts)"
    )
    seed.unlink()


def test_a_seeded_row_is_no_hit_once_the_tree_has_moved(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    said = _a_said(
        capture,
        repo,
        'LOOP_ENV_COMPONENTS=""\n'
        f'seeded=$(loop_ledger_key thebuilderstree "{A_SCOPE}")\n'
        f'loop_ledger_record "$seeded" "{A_SCOPE}" 1 thebuilderstree ENVA\n'
        f'printf "@seeded=%s\\n@moved=%s\\n" "$seeded" '
        f'"$(loop_ledger_key thebuilderstreX "{A_SCOPE}")"',
    )
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{said["seeded"]}"') == 0
    assert said["seeded"] != said["moved"]
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{said["moved"]}"') == 1
    assert _a_token(capture, repo, "thebuilderstreX", "ENVA", A_SCOPE) == "tree"


def test_the_declarations_are_read_from_the_derivers_not_a_list(
    capture: Callable[..., object], env_strip: object
) -> None:
    keys = " ".join(_a_stdout(capture, ROOT, "loop_env_derived_keys").split("\n"))
    assert keys == "AWS_STORAGE_BUCKET_NAME DATABASE_NAME"
    in_code = [
        line
        for line in SHELL_LIB.read_text().splitlines()
        if any(key in line.split("#", 1)[0] for key in ("DATABASE_NAME", "AWS_STORAGE_BUCKET_NAME"))
        and "derived-env-keys" not in line
    ]
    assert in_code == []
    assert " WHERE " not in f" {keys} "


def test_a_declared_key_changing_does_not_move_the_key(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    before = _a_fingerprint(capture, repo)
    (repo / ".env").write_text(
        ENV_FILE.replace("djb_checkout_one", "djb_checkout_two").replace(
            "djb-checkout-one", "djb-checkout-two"
        )
    )
    assert _a_fingerprint(capture, repo) == before


def test_an_undeclared_key_changing_does_move_the_key(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    before = _a_fingerprint(capture, repo)
    (repo / ".env").write_text(ENV_FILE.replace("DEBUG=1", "DEBUG=0"))
    assert _a_fingerprint(capture, repo) != before


def test_zero_declarations_is_a_broken_read_and_hashes_the_whole_file(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    (repo / "scripts/db.sh").unlink()
    (repo / "scripts/rung_start.sh").unlink()
    assert (_a_stdout(capture, repo, "loop_env_derived_keys") or "none") == "none"
    before = _a_fingerprint(capture, repo)
    (repo / ".env").write_text(
        ENV_FILE.replace("djb_checkout_one", "djb_checkout_two").replace(
            "djb-checkout-one", "djb-checkout-two"
        )
    )
    assert _a_fingerprint(capture, repo) != before


def test_an_empty_distribution_census_is_could_not_look(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    shutil.rmtree(repo / ".venv")
    rc, out = _sh(capture, repo, "rc=0; loop_env_fingerprint || rc=$?; exit $rc")
    assert rc == 1, out
    assert "not answer" in out, out


def test_the_merge_base_is_used_and_not_mains_tip(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    _git(repo, "checkout", "-q", "-b", "rung/thing")
    _commit(repo, {"README.md": "base\nthe rung's own work\n"}, "the rung")
    before = _a_fingerprint(capture, repo)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"README.md": "base\nsomebody else's merge\n"}, "an unrelated commit on main")
    _git(repo, "checkout", "-q", "rung/thing")
    assert _a_fingerprint(capture, repo) == before


def test_a_commit_that_keeps_the_tree_keeps_the_fingerprint(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    _git(repo, "checkout", "-q", "-b", "rung/thing")
    before = _a_fingerprint(capture, repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a commit that moves HEAD and not the tree")
    assert _a_fingerprint(capture, repo) == before
    said = _a_said(
        capture,
        repo,
        'loop_env_fingerprint >/dev/null && printf "@comp=%s \\n" "$LOOP_ENV_COMPONENTS"',
    )
    assert f" head={_git(repo, 'rev-parse', 'HEAD')} " in said["comp"], said


def _a_reads(scratch: Path, *names: str) -> Path:
    """The drive's `plant_env_reads`: a names file for `DJB_LOOP_ENV_READS`."""
    path = scratch / f"env-reads-{len(list(scratch.glob('env-reads-*')))}"
    path.write_text("".join(f"{name}\n" for name in names))
    return path


def _a_key_with_env(
    capture: Callable[..., object], repo: Path, reads: Path, *assignments: str
) -> str:
    exports = "".join(f"export '{assignment}'\n" for assignment in assignments)
    said = _a_said(
        capture,
        repo,
        f'export DJB_LOOP_ENV_READS="{reads}"\n'
        f'k=$(\n{exports}loop_ledger_key treeone "{A_SCOPE}"\n)\nprintf "@k=%s\\n" "$k"',
    )
    return said["k"]


def test_an_exported_suite_variable_moves_the_key(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    reads = _a_reads(scratch, "DRIVE_SUITE_KNOB", "DRIVE_ABSENT_KNOB")
    plain = _a_key_with_env(capture, repo, reads)
    assert _a_key_with_env(capture, repo, reads, "DRIVE_SUITE_KNOB=narrower") != plain
    assert _a_key_with_env(capture, repo, reads, "DRIVE_SUITE_KNOB=") != plain
    assert _a_key_with_env(capture, repo, reads, "DRIVE_OFF_CENSUS_KNOB=whatever") == plain


def test_the_process_environment_wins_over_the_env_file(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    reads = _a_reads(scratch, "DRIVE_SUITE_KNOB")
    env = repo / ".env"

    def shadowed() -> str:
        return _a_stdout(
            capture,
            repo,
            "loop_env_reads",
            f'export DJB_LOOP_ENV_READS="{reads}"\nexport DRIVE_SUITE_KNOB=exported',
        )

    env.write_text(env.read_text() + "DRIVE_SUITE_KNOB=one\n")
    from_file = _a_key_with_env(capture, repo, reads)
    env.write_text(env.read_text() + "DRIVE_SUITE_KNOB=two\n")
    assert _a_key_with_env(capture, repo, reads) != from_file
    before = shadowed()
    env.write_text(env.read_text() + "DRIVE_SUITE_KNOB=three\n")
    assert shadowed() == before


def test_the_read_set_census_has_one_owner_and_this_file_names_nothing(
    capture: Callable[..., object], env_strip: object
) -> None:
    assert (ROOT / "quality/partition.py").is_file()
    assert os.access(ROOT / ".venv/bin/python", os.X_OK)
    done = capture(["./.venv/bin/python", "-m", "quality.partition", "env-reads"], cwd=ROOT)
    assert done.rc == 0  # type: ignore[attr-defined]
    names = done.path.read_text().rstrip("\n")  # type: ignore[attr-defined]
    assert len(names.split("\n")) > 10, names
    digest = _a_stdout(capture, ROOT, "loop_env_reads")
    assert digest not in ("no-census", "")
    assert len(digest) == 64 and set(digest) <= A_HEX, digest
    library = SHELL_LIB.read_text()
    assert [name for name in names.split("\n") if name and name in library] == []


def test_a_moved_read_set_is_attributed_by_name(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    e, d, h = _hex64("envfile"), _hex64("dists"), _sha40("head")
    banked = _hex64("reads-as-banked")
    scratch_ledger.write_text("")
    _a_plant_row(scratch_ledger, A_CANON, "SAMETREE", "ENVA", _a_comp(e, "", d, h, h, banked))

    def token(comp: str) -> str:
        return _a_token(capture, repo, "SAMETREE", "ENVB", A_SCOPE, comp)

    other, elsewhere = _hex64("other"), _sha40("elsewhere")
    assert token(_a_comp(e, "", d, h, h, _hex64("reads-as-now"))) == "env:env-reads"
    assert token(_a_comp(other, "", d, h, h, banked)) == "env:env-file"
    assert token(_a_comp(e, "", other, h, h, banked)) == "env:dists"
    assert token(_a_comp(e, "", d, elsewhere, h, banked)) == "env:head"
    assert token(_a_comp(e, "", d, h, elsewhere, banked)) == "env:merge-base"


def test_a_checkout_with_no_census_says_so_and_a_broken_read_refuses(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    assert _a_stdout(capture, repo, "loop_env_reads") == "no-census"
    malformed = 'loop_components_malformed "{}"'
    assert _a_stdout(capture, repo, malformed.format(_a_comp(reads="no-census"))) == ""
    assert _a_stdout(capture, repo, malformed.format(_a_comp(reads="not-a-digest"))) != ""
    empty = scratch / "env-reads-empty"
    empty.write_text("")
    seam = f'export DJB_LOOP_ENV_READS="{empty}"'
    assert _a_rc(capture, repo, "loop_env_reads", seam) == 1
    assert _a_rc(capture, repo, f'loop_ledger_key treeone "{A_SCOPE}"', seam) == 1


def test_a_wider_scope_never_reads_a_narrower_verdict(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    narrow_scope = "mode=fast own=usage scope=usage always=abc"
    narrow = _a_key(capture, repo, "deadbeef", narrow_scope)
    wide = _a_key(capture, repo, "deadbeef", "mode=fast own=usage scope=core usage always=abc")
    _a_said(capture, repo, f'loop_ledger_record "{narrow}" "{narrow_scope}"')
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{narrow}"') == 0
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{wide}"') == 1


def test_an_unreadable_always_on_declaration_is_refused_on_write(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    scope = "mode=fast scope=- always=UNDECLARED"
    key = _a_key(capture, repo, "deadbeef", scope)
    rc, out = _sh(capture, repo, f'rc=0; loop_ledger_record "{key}" "{scope}" || rc=$?; exit $rc')
    assert rc == 2, out
    assert "could not be read" in out, out
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{key}"') == 1


def test_every_doubt_is_a_miss_and_never_an_exit_2_on_the_consult_path(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    scratch_ledger.write_text("")
    key = _a_key(capture, repo, "deadbeef")
    scratch_ledger.unlink()
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{key}"') == 1
    scratch_ledger.write_text("")
    assert _a_rc(capture, repo, 'loop_ledger_lookup "not-a-key"') == 1
    assert _a_rc(capture, repo, f'loop_ledger_record "not-a-key" "{A_SCOPE}"') == 2
    scratch_ledger.write_text(f"v2 {key} loop 2026-01-01T00:00:00Z caller=unstated scope=x\n")
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{key}"') == 1
    scratch_ledger.write_text("this is not a row at all\n")
    assert _a_rc(capture, repo, f'loop_ledger_lookup "{key}"') == 1

    e, d = _hex64("envfile"), _hex64("dists")
    scratch_ledger.write_text("")
    _a_plant_row(
        scratch_ledger,
        A_CANON,
        "TREEA",
        "ENVA",
        f"env-file=not-a-digest excluded=X dists={d} head={_sha40('h')} merge-base={_sha40('b')}",
    )
    now = _a_comp(e, "", d, _sha40("h"), _sha40("b"))
    rc, out = _a_attr(capture, repo, "TREEB", "ENVB", A_SCOPE, now)
    assert (rc, out.split("\n", 1)[0]) == (0, "unmatched"), out
    assert "env-file (not a digest)" in out, out

    scratch_ledger.write_text("")
    _a_plant_row(
        scratch_ledger,
        A_CANON,
        "TREEA",
        "ENVA",
        f"env-file={e} excluded=X dists={d} env-reads={_hex64('reads')} head={_sha40('h')}",
    )
    rc, out = _a_attr(capture, repo, "TREEB", "ENVB", A_SCOPE, now)
    assert (rc, out.split("\n", 1)[0]) == (0, "unmatched"), out
    assert "merge-base (missing)" in out, out

    scratch_ledger.write_text("")
    unknown_head = "0123456789abcdef" * 2 + "01234567"
    _a_plant_row(
        scratch_ledger, A_CANON, "TREEA", "ENVA", _a_comp(e, "", d, unknown_head, _sha40("b"))
    )
    rc, out = _a_attr(
        capture, repo, "TREEB", "ENVB", A_SCOPE, _a_comp(e, "", d, _sha40("hnow"), _sha40("b"))
    )
    assert (rc, out.split("\n", 1)[0]) == (0, "tree"), out
    assert (
        "since banked head: not derivable (01234567 is not a commit in this repository)" in out
    ), out


# end of group A

# --- group B: the banner to the loop-health reader ------------------------------------------------


B_QUEUE = "docs/product/queue.md"
B_CANON = "mode=fast_scope=-_always=abc"
B_STRAY_NOTE = "is not in a source the reader scans"
B_REWRITE = "zzz_rewritten/evidence.png"


def _b_in_order(text: str, *needles: str) -> bool:
    at = 0
    for needle in needles:
        found = text.find(needle, at)
        if found < 0:
            return False
        at = found + len(needle)
    return True


def _b_differ(before: str, after: str) -> str:
    return f"same: {before}" if before == after else "differ"


def _b_plant_derived_leg(repo: Path, *entries: str) -> None:
    (repo / "scripts/planted_leg.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# A planted leg. It republishes derived/ on every green run, and the\n"
        "# bytes differ per box. Nothing measured reads them back.\n"
        "# >>> derived-tree-paths >>>\n"
        + "".join(f"# {entry}\n" for entry in entries)
        + "# <<< derived-tree-paths <<<\n"
    )


def _b_plant_derived_member(repo: Path) -> None:
    (repo / "derived").mkdir(exist_ok=True)
    (repo / "derived/planted.png").write_text("the accepted look, as this box draws it\n")
    (repo / "derived.txt").write_text("measured: yes\n")
    _commit_all(repo, "the derived artefact, committed as the real one is")


def _b_plant_stray_derived_leg(repo: Path, where: str, entry: str) -> None:
    (repo / where).parent.mkdir(parents=True, exist_ok=True)
    (repo / where).write_text(
        "#!/usr/bin/env bash\n"
        "# A planted leg that declares in the wrong place.\n"
        "# >>> derived-tree-paths >>>\n"
        f"# {entry}\n"
        "# <<< derived-tree-paths <<<\n"
    )
    _commit_all(repo, f"a declaration at {where}")


def _b_read_split(capture: Callable[..., object], repo: Path, sink: Path) -> tuple[int, str, str]:
    """`gate__derived_tree_paths` in `repo`: (exit, stdout, stderr), the two streams apart."""
    out, err = sink.with_suffix(".out"), sink.with_suffix(".err")
    rc, said = _sh(
        capture,
        repo,
        f'rc=0; gate__derived_tree_paths >"{out}" 2>"{err}" || rc=$?; printf "rc=%s" "$rc"',
    )
    assert said.startswith("rc="), said
    return int(said[3:]), out.read_text(), err.read_text()


def _b_declared(capture: Callable[..., object], repo: Path) -> str:
    rc, out = _sh(capture, repo, "gate__derived_tree_paths 2>/dev/null")
    return out.replace("\n", " ").rstrip(" ") if rc == 0 else ""


def _b_unreadable(capture: Callable[..., object], repo: Path, sink: Path) -> None:
    rc, out, err = _b_read_split(capture, repo, sink)
    assert rc == 1, (sink.name, rc, err)
    assert len(out.splitlines()) == 0, (sink.name, out)
    assert "WHOLE tree" in err, (sink.name, err)


def _b_tree_without_exclusion(repo: Path, index: Path) -> str:
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    for argv in (["read-tree", "HEAD"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(repo), *argv], env=env, capture_output=True, check=True)
    tree = subprocess.run(
        ["git", "-C", str(repo), "write-tree"], env=env, capture_output=True, text=True, check=True
    ).stdout.strip()
    index.unlink()
    return tree


def _b_reuse_checkout(scratch_repo: Callable[..., Path], name: str) -> tuple[Path, str]:
    """A checkout with an `apps/` naming no docs path and a `docs/`: (repo, banked head)."""
    repo = _checkout(scratch_repo, name)
    (repo / "apps/zzz_probe/tests").mkdir(parents=True)
    (repo / "docs/product").mkdir(parents=True)
    (repo / "apps/zzz_probe/tests/test_nothing.py").write_text(
        '"""A module that names no docs path at all."""\n'
    )
    (repo / B_QUEUE).write_text("the queue\n")
    _git(repo, "add", "apps", "docs")
    _git(repo, "commit", "-q", "-m", "a tree with apps/ and docs/")
    return repo, _git(repo, "rev-parse", "HEAD")


def _b_docs_commit(repo: Path, text: str = "one more row\n") -> None:
    with (repo / B_QUEUE).open("a") as queue:
        queue.write(text)
    _git(repo, "add", B_QUEUE)
    _git(repo, "commit", "-q", "-m", "queue row rowed [docs-only]")


def _b_attribute(
    capture: Callable[..., object],
    repo: Path,
    ledger_file: Path,
    banked_head: str,
    banked: str = "",
) -> tuple[str, str, str]:
    """The drive's `attribute_for_reuse`: (token, detail, the banked head's committed tree)."""
    banked_tree = _git(repo, "rev-parse", f"{banked_head}^{{tree}}")
    envfile, dists = _hex64("envfile"), _hex64("dists")
    row = _crafted_components(envfile, dists=dists, head=banked_head, merge_base=banked_head)
    ledger_file.write_text(
        f"v1 loop-v1:{1:064d} loop 2026-09-07T00:00:00Z caller=drive scope={B_CANON} "
        f"passes=1 tree={banked or banked_tree} env=ENVA {row}\n"
    )
    head = _git(repo, "rev-parse", "HEAD")
    now = _crafted_components(envfile, dists=dists, head=head, merge_base=head)
    rc, answer = _sh(
        capture,
        repo,
        f'LOOP_ENV_COMPONENTS="{now}"; loop_ledger_attribute NEWTREE ENVA "{SCOPE}" 2>/dev/null',
    )
    assert rc == 0, answer
    answer = answer.rstrip("\n")
    token, _, rest = answer.partition("\n")
    return token, (rest if "\n" in answer else answer), banked_tree


def _b_reuse(
    capture: Callable[..., object], repo: Path, token: str, detail: str
) -> tuple[int, str, str, str]:
    """`loop_docs_only_reuse` in this shell: (exit, LOOP_REUSE_TREE, _N, _WHY)."""
    _, out = _sh(
        capture,
        repo,
        'rc=0; loop_docs_only_reuse "$B_TOKEN" "$B_DETAIL" >/dev/null 2>&1 || rc=$?\n'
        'printf "rc=%s\\ntree=%s\\nn=%s\\nwhy=%s" "$rc" "${LOOP_REUSE_TREE-}" '
        '"${LOOP_REUSE_N-}" "${LOOP_REUSE_WHY-}"',
        env={"B_TOKEN": token, "B_DETAIL": detail},
    )
    rc, tree, n, why = out.split("\n", 3)
    return int(rc[3:]), tree[5:], n[2:], why[4:]


def _b_rewrites(capture: Callable[..., object], repo: Path, snap: Path) -> tuple[int, str]:
    rc, out = _sh(capture, repo, f'loop_tree_rewrites "{snap}" 2>/dev/null')
    return rc, out.rstrip("\n")


def _b_snapshot(capture: Callable[..., object], repo: Path, snap: Path) -> str:
    rc, out = _sh(capture, repo, f'loop_tree_snapshot "{snap}"')
    assert rc == 0, out
    return out.rstrip("\n")


def _b_rewrite_checkout(scratch_repo: Callable[..., Path], name: str) -> Path:
    repo = _checkout(scratch_repo, name)
    (repo / B_REWRITE).parent.mkdir()
    (repo / B_REWRITE).write_text("the committed evidence\n")
    _commit_all(repo, "a tracked evidence file")
    return repo


def _b_rewrite_after_the_stamp(repo: Path, rel: str, text: str) -> None:
    time.sleep(1)
    (repo / rel).write_text(f"{text}\n")


def test_the_superseded_sentence_was_superseded_in_the_same_commit() -> None:
    library = SHELL_LIB.read_text()
    assert "--fast and --loop write nothing anywhere" not in library
    assert "superseded" in library
    assert (
        "\\`--fast\\` writes nothing anywhere" in library
        or "fast` writes nothing anywhere" in library
    )


def test_no_pipeline_tail_in_this_territory_still_uses_grep_q() -> None:
    tail = re.compile(r"\|\s*grep\s+(-[A-Za-z]*q[A-Za-z]*\s)")
    territory = ("gate_ledger.sh", "secrets_scan.sh")
    hits = [
        name
        for name in territory
        if (ROOT / "scripts" / name).is_file()
        and any(tail.search(line) for line in (ROOT / "scripts" / name).read_text().splitlines())
    ]
    assert hits == []
    assert 'grep -E "$PARTITION_KEY_RE" >/dev/null' in SHELL_LIB.read_text()


def test_the_pipe_race_is_real_above_the_buffer_and_the_new_form_survives_it(
    capture: Callable[..., object], env_strip: object
) -> None:
    padded = f'{{ echo MATCH; "{ROOT}/.venv/bin/python" -c "print(\'x\' * 200000)"; }}'
    capture(["bash", "-c", f"set -o pipefail; {padded} | grep -q MATCH"], cwd=ROOT)
    green = capture(["bash", "-c", f"set -o pipefail; {padded} | grep MATCH >/dev/null"], cwd=ROOT)
    assert green.rc == 0  # type: ignore[attr-defined]


def test_a_declaration_outside_the_reader_sources_is_named(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    _b_plant_derived_member(repo)
    _b_plant_stray_derived_leg(
        repo,
        "scripts/tests/planted_leg.sh",
        "derived — republished on every green run; nothing measured reads it back",
    )
    rc, out, err = _b_read_split(capture, repo, scratch / "stray")
    assert rc == 0, err
    assert len(out.splitlines()) == 0, out
    assert B_STRAY_NOTE in err
    assert "scripts/tests/planted_leg.sh" in err
    before = _tree_in(capture, repo)
    (repo / "derived/planted.png").write_text("antialiasing moved on this box\n")
    assert _tree_in(capture, repo) != before


def test_a_declaration_inside_the_reader_sources_prints_no_stray_note(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    _b_plant_derived_member(repo)
    _b_plant_stray_derived_leg(
        repo,
        "scripts/planted_leg.sh",
        "derived — republished on every green run; nothing measured reads it back",
    )
    rc, _, err = _b_read_split(capture, repo, scratch / "inside")
    assert rc == 0, err
    assert _b_declared(capture, repo) == "derived"
    assert B_STRAY_NOTE not in err


def test_a_planted_churn_in_a_declared_derived_path_does_not_move_the_key(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _checkout(scratch_repo)
    _b_plant_derived_leg(
        repo,
        "derived — republished by the planted leg on every green run; the bytes are "
        "machine-dependent and nothing measured reads them back",
    )
    _b_plant_derived_member(repo)
    assert _b_declared(capture, repo) == "derived"
    before = _tree_in(capture, repo)
    (repo / "derived/planted.png").write_text("antialiasing moved on this box\n")
    after = _tree_in(capture, repo)
    assert after == before
    (repo / "derived/planted-390.png").write_text(
        "a fixture this box publishes and another does not\n"
    )
    before, after = after, _tree_in(capture, repo)
    assert after == before
    assert re.fullmatch(r"[0-9a-f]{40,64}", after)
    assert len(_git(repo, "ls-files", "derived").splitlines()) == 1
    (repo / "derived.txt").write_text("measured: no\n")
    before, after = after, _tree_in(capture, repo)
    assert _b_differ(before, after) == "differ"
    (repo / "README.md").write_text("moved\n")
    before, after = after, _tree_in(capture, repo)
    assert _b_differ(before, after) == "differ"
    (repo / "scripts/planted_leg.sh").unlink()
    assert _b_declared(capture, repo) == ""
    before = _tree_in(capture, repo)
    (repo / "derived/planted.png").write_text("churn, visible again\n")
    assert _b_differ(before, _tree_in(capture, repo)) == "differ"


def test_a_churn_in_an_undeclared_path_still_moves_the_key(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _checkout(scratch_repo)
    _b_plant_derived_leg(
        repo,
        "derived — republished by the planted leg on every green run; nothing measured "
        "reads it back",
    )
    _b_plant_derived_member(repo)
    before = _tree_in(capture, repo)
    (repo / "README.md").write_text("a tracked file the declaration never named\n")
    before, after = before, _tree_in(capture, repo)
    assert _b_differ(before, after) == "differ"
    (repo / "stray-artefact.png").write_text("a scratch file nobody declared\n")
    before, after = after, _tree_in(capture, repo)
    assert _b_differ(before, after) == "differ"
    (repo / "elsewhere/derived").mkdir(parents=True)
    (repo / "elsewhere/derived/planted.png").write_text(
        "the same basename, somewhere nobody declared\n"
    )
    before, after = after, _tree_in(capture, repo)
    assert _b_differ(before, after) == "differ"


def test_an_unreadable_derived_declaration_excludes_nothing_and_says_so(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    readable = "derived — republished on every green run; nothing measured reads it back"
    _b_plant_derived_leg(repo, readable)
    _b_plant_derived_member(repo)
    (repo / "scripts/planted_leg.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# >>> derived-tree-paths >>>\n"
        "# derived — republished on every green run\n"
        "# and then the block was never closed\n"
    )
    _b_unreadable(capture, repo, scratch / "unclosed")
    before = _tree_in(capture, repo)
    (repo / "derived/planted.png").write_text("churn under an unreadable declaration\n")
    assert _b_differ(before, _tree_in(capture, repo)) == "differ"
    for number, entry in enumerate(
        (
            ". — the whole tree, by typo",
            "/ — the filesystem, by typo",
            "../outside — an escape out of the checkout",
            "/var/tmp/elsewhere — an absolute path",  # noqa: S108 — an example path the refusal must name, never opened
            "A property of WHERE this tree is, never of what is in it",
            "never-committed — a path no commit holds",
        )
    ):
        _b_plant_derived_leg(repo, entry)
        _b_unreadable(capture, repo, scratch / f"entry-{number}")
    _b_plant_derived_leg(repo, readable)
    assert _b_declared(capture, repo) == "derived"
    before = _tree_in(capture, repo)
    (repo / "derived/planted.png").write_text("and the churn is invisible once more\n")
    assert _tree_in(capture, repo) == before


def test_an_empty_derived_declaration_leaves_the_key_unchanged(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    assert _b_declared(capture, ROOT) == LOCAL_DRAWER
    rc, out = _sh(capture, ROOT, "gate__derived_tree_paths")
    assert rc == 0, out
    assert _b_tree_without_exclusion(ROOT, scratch / "root-index") == _tree_in(capture, ROOT)
    repo = _checkout(scratch_repo, "dirty")
    (repo / "untracked.txt").write_text("an untracked file\n")
    (repo / "README.md").write_text("a modified one\n")
    assert _b_tree_without_exclusion(repo, scratch / "dirty-index") == _tree_in(capture, repo)
    repo = _checkout(scratch_repo, "clean")
    assert _tree_in(capture, repo) == _git(repo, "rev-parse", "HEAD^{tree}")
    repo = _checkout(scratch_repo, "code-sentinel")
    (repo / "scripts/planted_leg.sh").write_text(
        "#!/usr/bin/env bash\n"
        "DECL_BEGIN='>>> derived-tree-paths >>>'\n"
        "planted=derived\n"
        "DECL_END='<<< derived-tree-paths <<<'\n"
    )
    _b_plant_derived_member(repo)
    assert _b_declared(capture, repo) == ""
    rc, out = _sh(capture, repo, "gate__derived_tree_paths")
    assert rc == 0, out
    before = _tree_in(capture, repo)
    (repo / "derived/planted.png").write_text("churn nobody declared\n")
    assert _b_differ(before, _tree_in(capture, repo)) == "differ"


def test_a_docs_only_commit_reuses_the_pytest_verdict_and_banks_a_reuse_row(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, banked_head = _b_reuse_checkout(scratch_repo, "repo")
    _b_docs_commit(repo)
    token, detail, banked_tree = _b_attribute(capture, repo, scratch_ledger, banked_head)
    assert token == "tree"  # noqa: S105 — a parsed word compared to a keyword, not a credential
    assert f"reuse-basis: head={banked_head} tree={banked_tree}" in detail, detail
    rc, _ = _sh(capture, repo, "command -v loop_docs_only_reuse >/dev/null")
    assert rc == 0
    assert _b_reuse(capture, repo, token, detail) == (0, banked_tree, "1", "")
    assert _git(repo, "rev-parse", f"{banked_head}^{{tree}}") == banked_tree
    scratch_ledger.write_text("")
    rc, out = _sh(
        capture,
        repo,
        f'key=$(loop_ledger_key NEWTREE "{SCOPE}")\n'
        f'loop_ledger_record "$key" "{SCOPE}" 1 NEWTREE ENVA BANKEDTREE >/dev/null 2>&1\n'
        'row=$(loop_ledger_lookup "$key" 2>/dev/null) || row=""\n'
        'printf "%s\\n%s" "$key" "$row"',
    )
    assert rc == 0, out
    key, _, row = out.partition("\n")
    assert row != ""
    assert " reuse=BANKEDTREE" in row
    assert row.startswith(f"v1 {key} loop ")


def test_a_mixed_delta_measures_in_full(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, banked_head = _b_reuse_checkout(scratch_repo, "repo")
    with (repo / B_QUEUE).open("a") as queue:
        queue.write("one more row\n")
    with (repo / "apps/zzz_probe/tests/test_nothing.py").open("a") as module:
        module.write("\n# a source change\n")
    _git(repo, "add", "docs", "apps")
    _git(repo, "commit", "-q", "-m", "one docs path and one apps path")
    token, detail, _ = _b_attribute(capture, repo, scratch_ledger, banked_head)
    rc, tree, _, why = _b_reuse(capture, repo, token, detail)
    assert (rc, tree, why) == (1, "", "")


def test_a_dirty_tree_is_never_docs_only(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, banked_head = _b_reuse_checkout(scratch_repo, "repo")
    _b_docs_commit(repo)
    token, detail, _ = _b_attribute(capture, repo, scratch_ledger, banked_head)
    assert _b_reuse(capture, repo, token, detail)[0] == 0
    with (repo / "apps/zzz_probe/tests/test_nothing.py").open("a") as module:
        module.write("a half-finished change nobody can name\n")
    rc, tree, _, why = _b_reuse(capture, repo, token, detail)
    assert (rc, tree) == (1, "")
    assert "WORKING TREE is not clean" in why, why


def test_a_run_that_rewrites_a_path_the_key_reads_names_it(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    rc, out = _sh(
        capture, scratch, "command -v loop_tree_snapshot && command -v loop_tree_rewrites"
    )
    assert rc == 0, out
    repo = _b_rewrite_checkout(scratch_repo, "repo")
    snap = scratch / "rewrite-snapshot"
    _b_snapshot(capture, repo, snap)
    _b_rewrite_after_the_stamp(repo, B_REWRITE, "re-taken by the leg")
    assert _b_rewrites(capture, repo, snap) == (0, B_REWRITE)
    _b_snapshot(capture, repo, snap)
    _b_rewrite_after_the_stamp(repo, B_REWRITE, "re-taken by the leg")
    rc, rewrites = _b_rewrites(capture, repo, snap)
    assert (rc, rewrites) == (0, B_REWRITE)
    rc, out = _sh(capture, repo, f'loop_tree_remember "{snap}" "{rewrites}"')
    assert rc == 0, out
    _b_snapshot(capture, repo, snap)
    assert _b_rewrites(capture, repo, snap) == (0, B_REWRITE)
    for leftover in (snap, Path(f"{snap}.stamp"), Path(f"{snap}.end")):
        leftover.unlink(missing_ok=True)
    (repo / B_REWRITE).write_text("an author edit\n")
    _b_snapshot(capture, repo, snap)
    assert _b_rewrites(capture, repo, snap)[1] == ""
    rc, out = _sh(capture, repo, f'loop_tree_remember "{snap}" ""')
    assert rc == 0, out
    assert not Path(f"{snap}.rewrites").exists()
    _b_snapshot(capture, repo, snap)
    assert _b_rewrites(capture, repo, snap) == (0, "")
    _b_snapshot(capture, repo, snap)
    _b_rewrite_after_the_stamp(repo, "made-by-a-leg.txt", "a new file")
    assert _b_rewrites(capture, repo, snap)[1] == "made-by-a-leg.txt"
    (repo / "made-by-a-leg.txt").unlink()
    snap.unlink()
    Path(f"{snap}.stamp").unlink()
    assert _b_rewrites(capture, repo, snap)[0] == 2


def test_an_unfinished_run_is_remembered_at_the_next_snapshot(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _b_rewrite_checkout(scratch_repo, "interrupted")
    snap = scratch / "snap-interrupted"
    _b_snapshot(capture, repo, snap)
    _b_rewrite_after_the_stamp(repo, B_REWRITE, "re-taken by run 1")
    time.sleep(1)
    _sh(capture, repo, f'loop_tree_mark_end "{snap}" 2>/dev/null || true')
    said = _b_snapshot(capture, repo, snap)
    assert _b_rewrites(capture, repo, snap) == (0, B_REWRITE)
    assert _b_in_order(said, "never reached its bank's question", B_REWRITE), said
    repo = _b_rewrite_checkout(scratch_repo, "fixed-after")
    snap = scratch / "snap-fixed-after"
    _b_snapshot(capture, repo, snap)
    time.sleep(1)
    _sh(capture, repo, f'loop_tree_mark_end "{snap}" 2>/dev/null || true')
    _b_rewrite_after_the_stamp(repo, B_REWRITE, "the author's fix, after the red run")
    _b_snapshot(capture, repo, snap)
    assert _b_rewrites(capture, repo, snap)[1] == ""
    repo = _b_rewrite_checkout(scratch_repo, "killed")
    snap = scratch / "snap-killed"
    _b_snapshot(capture, repo, snap)
    _b_rewrite_after_the_stamp(repo, B_REWRITE, "re-taken by a run that was SIGKILLed")
    said = _b_snapshot(capture, repo, snap)
    assert _b_rewrites(capture, repo, snap)[1] == B_REWRITE
    assert "NO END MARK" in said, said


def test_a_drive_is_green_at_a_tree_only_by_its_exit_and_its_tree(
    capture: Callable[..., object], scratch: Path, env_strip: object
) -> None:
    led, tree, other = scratch / "green-at-ledger", "1" * 40, "2" * 40
    red = f"v1 k2 drive 2026-09-27T11:00:00Z zzz_d exit=1 took=1 tree={tree} parts=-\n"
    elsewhere = f"v1 k3 drive 2026-09-27T12:00:00Z zzz_d exit=0 took=1 tree={other} parts=-\n"
    led.write_text(
        f"v1 k1 drive 2026-09-27T09:00:00Z zzz_d exit=0 took=1 tree={tree} parts=-\n"
        + red
        + elsewhere
    )
    env = {"DJB_GATE_LEDGER": str(led)}
    rc, got = _sh(capture, scratch, f"drive_ledger_green_at zzz_d {tree}", env=env)
    got = got.rstrip("\n") if rc == 0 else ""
    fields = [(line.split() + ["", ""])[1] for line in got.split("\n")]
    assert "\n".join(fields).rstrip("\n") == "k1", got
    led.write_text(red + elsewhere)
    rc, _ = _sh(capture, scratch, f"drive_ledger_green_at zzz_d {tree} >/dev/null", env=env)
    assert rc == 1


def test_every_ledger_rewrite_is_write_then_mv() -> None:
    lines = SHELL_LIB.read_text().splitlines()
    found, ledger_fn, writes_ledger = [], "", False
    for number, line in enumerate(lines, start=1):
        if re.match(r"[a-z_]+\(\) \{", line):
            ledger_fn, writes_ledger = line.split()[0].replace("()", "", 1), False
        if "path=$(gate_ledger_path)" in line:
            writes_ledger = True
        if writes_ledger and re.search(r'[^>]>[ ]*"\$path"', line):
            found.append(f"{number} {ledger_fn}")
    assert found == []

    def body(name: str) -> list[str]:
        out: list[str] = []
        for line in lines:
            if out or re.match(rf"{name}\(\) \{{", line):
                out.append(line)
                if line.startswith("}"):
                    break
        return out

    truncating = re.compile(r'[^>]>[ ]*"\$(out|\{snap\}\.rewrites|\{out\})"')
    for name in ("loop_tree_snapshot", "loop_tree_remember", "loop_tree__unfinished"):
        text = body(name)
        assert text, f"{name} is not defined in scripts/gate_ledger.sh"
        assert not any(truncating.search(line) for line in text), name
        assert any("loop_tree__write" in line for line in text), name
    assert any('mv -f "$tmp" "$out"' in line for line in body("loop_tree__write"))


def test_a_rewrite_the_leg_declares_is_subtracted_and_the_key_is_heads(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
) -> None:
    repo = _b_rewrite_checkout(scratch_repo, "repo")
    rc, out = _sh(capture, repo, 'printf "%s\\n%s" "$GATE_TREE_DECL_BEGIN" "$GATE_TREE_DECL_END"')
    begin, end_sentinel = out.split("\n")
    (repo / "scripts/rewrite_leg.sh").write_text(
        f"#!/usr/bin/env bash\n# {begin}\n"
        f"# {B_REWRITE} — re-taken by this leg on every run\n# {end_sentinel}\n"
    )
    _commit_all(repo, "the leg declares what it re-takes")
    snap = scratch / "rewrite-snapshot"
    _b_snapshot(capture, repo, snap)
    _b_rewrite_after_the_stamp(repo, B_REWRITE, "re-taken by the leg")
    assert _b_rewrites(capture, repo, snap) == (0, "")
    rc, committed = _sh(capture, repo, 'gate_measured_tree_of "HEAD^{tree}" 2>/dev/null')
    assert rc == 0 and committed.strip(), committed
    assert _tree_in(capture, repo) == committed.strip()


def test_the_bank_asks_before_the_key_re_derives(
    capture: Callable[..., object], env_strip: object
) -> None:
    _, said = _sh(
        capture,
        ROOT,
        'printf "%s\\n" "$GATE_TREE_DECL_BEGIN"; '
        "loop_tree_refusal \"$(printf 'a.py\\tchanged\\nb.png\\tcarried\\n')\" 2>&1 >/dev/null "
        "|| true",
    )
    begin, _, said = said.partition("\n")
    assert _b_in_order(
        said, "a.py — changed during this run", "b.png — carried from a refused run"
    ), said
    assert _b_in_order(said, "git checkout -- <path>", "change its bytes", begin), said
    assert "still tree" not in said


def test_a_bank_measured_on_a_dirty_tree_is_no_basis_for_a_docs_only_reuse(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, banked_head = _b_reuse_checkout(scratch_repo, "repo")
    red = repo / "apps/zzz_probe/tests/test_nothing.py"
    saved = red.read_bytes()
    with red.open("a") as module:
        module.write("\n# the uncommitted edit that greens the committed red\n")
    dirty = _tree_in(capture, repo)
    red.write_bytes(saved)
    assert _b_differ(dirty, _git(repo, "rev-parse", f"{banked_head}^{{tree}}")) == "differ"
    assert _git(repo, "status", "--porcelain") == ""
    _b_docs_commit(repo)
    token, detail, _ = _b_attribute(capture, repo, scratch_ledger, banked_head, dirty)
    rc, tree, _, why = _b_reuse(capture, repo, token, detail)
    assert (rc, tree) == (1, "")
    assert (
        "the banked verdict was measured on a tree that is not its head's measured tree" in why
    ), why
    token, detail, banked_tree = _b_attribute(capture, repo, scratch_ledger, banked_head)
    rc, tree, _, why = _b_reuse(capture, repo, token, detail)
    assert (rc, tree, why) == (0, banked_tree, "")


def test_a_declaring_product_still_reuses_a_docs_only_loop_verdict(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, _ = _b_reuse_checkout(scratch_repo, "repo")
    _b_plant_derived_leg(repo, "derived — a per-box artefact; nothing measured reads it back")
    _b_plant_derived_member(repo)
    banked_head = _git(repo, "rev-parse", "HEAD")
    raw = _git(repo, "rev-parse", f"{banked_head}^{{tree}}")
    measured = _tree_in(capture, repo)
    assert _b_differ(raw, measured) == "differ"
    assert _git(repo, "status", "--porcelain") == ""
    _b_docs_commit(repo)
    token, detail, _ = _b_attribute(capture, repo, scratch_ledger, banked_head, measured)
    assert _b_reuse(capture, repo, token, detail) == (0, measured, "1", "")
    with (repo / "apps/zzz_probe/tests/test_nothing.py").open("a") as module:
        module.write("a half-finished change nobody can name\n")
    rc, tree, _, why = _b_reuse(capture, repo, token, detail)
    assert (rc, tree) == (1, "")
    assert "WORKING TREE is not clean" in why, why


def test_a_docs_path_spelled_under_apps_forces_a_measure(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, _ = _b_reuse_checkout(scratch_repo, "repo")
    (repo / "apps/zzz_probe/tests/test_reads_docs.py").write_text(
        f'"""Reads {B_QUEUE} for a census."""\n'
    )
    with (repo / B_QUEUE).open("a") as queue:
        queue.write("one more row\n")
    _git(repo, "add", "apps", "docs")
    _git(repo, "commit", "-q", "-m", "a docs commit under a path a test reads")
    banked_head = _git(repo, "rev-parse", "HEAD")
    _b_docs_commit(repo, "and one more\n")
    token, detail, _ = _b_attribute(capture, repo, scratch_ledger, banked_head)
    rc, tree, _, why = _b_reuse(capture, repo, token, detail)
    assert (rc, tree) == (1, "")
    assert why == (
        f"docs-only delta touches a path spelled in a module under apps/: {B_QUEUE} "
        "(named in apps/zzz_probe/tests/test_reads_docs.py) — measuring"
    )


def test_loop_health_reads_a_reuse_row(
    capture: Callable[..., object], scratch_repo: Callable[..., Path], env_strip: object
) -> None:
    python = ROOT / ".venv/bin/python"
    if not os.access(python, os.X_OK):
        pytest.skip("this checkout has no .venv/bin/python")
    spec = importlib.util.spec_from_file_location("loop_health", ROOT / "scripts/loop_health.py")
    assert spec is not None and spec.loader is not None
    health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health)
    repo = scratch_repo()
    # names, never reads: docs/product/readouts.md — the scratch checkout's copy
    plain = repo / "docs/product/readouts.md"
    plain.parent.mkdir(parents=True)
    plain.write_text(health.CANARY_LEGAL)
    marked = plain.with_name("readouts-reuse.md")
    marked.write_text(
        plain.read_text()
        + "\nV-ZZZ: loop: docs-only reuse of "
        + "0123456789abcdef" * 2
        + "01234567\n"
    )
    was = capture([str(python), "scripts/loop_health.py", str(plain)], cwd=ROOT)
    now = capture([str(python), "scripts/loop_health.py", str(marked)], cwd=ROOT)
    assert now.rc == was.rc  # type: ignore[attr-defined]
    said = now.path.read_text(errors="replace")  # type: ignore[attr-defined]
    assert not re.search(r"Traceback|CANNOT JUDGE", said), said


def test_the_two_ledger_files_that_bought_a_2302s_remeasure_are_a_reuse(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo, banked_head = _b_reuse_checkout(scratch_repo, "repo")
    in_flight = "docs/product/in-flight.md"
    # names, never reads: docs/product/cycles/README.md — planted in scratch
    plan = "docs/product/cycles/README.md"
    (repo / plan).parent.mkdir(parents=True)
    (repo / in_flight).write_text("in flight\n")
    (repo / plan).write_text("the plan\n")
    _git(repo, "add", "docs")
    _git(repo, "commit", "-q", "-m", "the two ledger files [docs-only]")
    token, detail, banked_tree = _b_attribute(capture, repo, scratch_ledger, banked_head)
    assert _b_reuse(capture, repo, token, detail) == (0, banked_tree, "2", "")
    assert _git(repo, "rev-parse", f"{banked_head}^{{tree}}") == banked_tree
    modules = sorted((ROOT / "apps").rglob("*.py"))
    for needle in (in_flight, plan):
        hits = [m for m in modules if m.is_file() and needle.encode() in m.read_bytes()]
        assert hits == [], (needle, hits)


# end of group B

# --- group C: the docs-only source to a deletion's push ------------------------------------------

# In halves: a planted scratch directory, never a pointer the dangling-paths census judges.
DOCSONLY_DIR = "docs/" + "fixtures"
DOCSONLY_DOC = f"{DOCSONLY_DIR}/rows.md"
DOCSONLY_LEGS = "ruff,mypy,pytest-x2,selftest"
NONREAD_MARK = "names, never" + " reads:"
CI_RUN_FIXTURE = "36282702383"
# names, never reads: docs/product/build-contract.md docs/product/design/patterns.md — census pairs
DOCS_QUOTE_LEGITIMATE_READS = (
    ("apps/core/tests/test_drawer_fixture_home.py", "docs/product/build-contract.md"),
    ("apps/core/tests/test_verb_table.py", "docs/product/design/patterns.md"),
)


def _c_full_rows(ledger_file: Path) -> list[str]:
    if not ledger_file.is_file():
        return []
    return [line for line in ledger_file.read_text().splitlines() if " full " in line]


def _c_plant_full_row(ledger_file: Path, tree: str, legs: str, extra: str = "") -> None:
    with ledger_file.open("a") as sink:
        sink.write(f"v1 {tree} full 2026-09-16T00:00:00Z {legs} caller=drive{extra}\n")


def _c_plant_drive_row(ledger_file: Path, key: str, name: str) -> None:
    with ledger_file.open("a") as sink:
        sink.write(f"v1 {key} drive 2026-09-18T00:00:00Z {name} exit=0 took=7 tree={key}\n")


def _c_legs_checkout(scratch_repo: Callable[..., Path], ledger_file: Path, legs: str) -> Path:
    """The drive's `legs_checkout`: a checkout whose `scripts/check.sh` declares `legs`."""
    ledger_file.write_text("")
    repo = _checkout(scratch_repo, "legs")
    (repo / "scripts/check.sh").write_text(f"#!/usr/bin/env bash\nFULL_LEGS={legs}\n")
    (repo / "scripts/check.sh").chmod(0o755)
    return repo


def _c_has_green(capture: Callable[..., object], repo: Path, tree: str) -> int:
    return _sh(capture, repo, f'gate_has_green "{tree}" 2>/dev/null')[0]


def _c_lookup(capture: Callable[..., object], repo: Path, tree: str) -> tuple[int, str]:
    return _sh(capture, repo, f'gate_ledger_lookup "{tree}" 2>&1')


def _c_world(scratch_repo: Callable[..., Path], ledger_file: Path, name: str) -> Path:
    """The drive's `docs_only_world`: apps/, config/, quality/, a docs dir, two drives; M rowed."""
    ledger_file.write_text("")
    repo = _checkout(scratch_repo, name)
    for rel in ("apps", "config", "quality", DOCSONLY_DIR, "scripts/tests"):
        (repo / rel).mkdir(parents=True, exist_ok=True)
    (repo / "scripts/check.sh").write_text(f"#!/usr/bin/env bash\nFULL_LEGS={DOCSONLY_LEGS}\n")
    (repo / "apps/quiet.py").write_text('"""A module that opens nothing at all."""\n')
    (repo / "config/quiet.py").write_text('"""Settings that open nothing at all."""\n')
    (repo / "quality/quiet.yaml").write_text("rules: []\n")
    (repo / DOCSONLY_DOC).write_text("the rows\n")
    drives = "drives" + ":"
    (repo / "scripts/tests/test_reads_docs.sh").write_text(
        f"#!/usr/bin/env bash\n# {drives} {DOCSONLY_DIR} scripts/check.sh\nexit 0\n"
    )
    (repo / "scripts/tests/test_cites_docs.sh").write_text(
        f"#!/usr/bin/env bash\n# {drives} scripts/check.sh\n# cites: {DOCSONLY_DOC}\nexit 0\n"
    )
    for rel in ("scripts/check.sh", "scripts/tests/test_reads_docs.sh"):
        (repo / rel).chmod(0o755)
    (repo / "scripts/tests/test_cites_docs.sh").chmod(0o755)
    _commit_all(repo, "a tree with apps/, config/, quality/, docs/ and two drives")
    _c_plant_full_row(ledger_file, _git(repo, "rev-parse", "HEAD^{tree}"), DOCSONLY_LEGS)
    return repo


def _c_rebase_m(repo: Path, ledger_file: Path, message: str) -> str:
    _commit_all(repo, message)
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    _c_plant_full_row(ledger_file, tree, DOCSONLY_LEGS)
    return tree


def _c_docs_commit(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    with (repo / path).open("a") as sink:
        sink.write(f"{text}\n")
    _commit_all(repo, f"a docs-only commit touching {path}")


def _c_plan(capture: Callable[..., object], repo: Path) -> dict[str, str]:
    """`gate_docs_only_plan HEAD` and the globals it answers in."""
    rc, out = _sh(
        capture,
        repo,
        "rc=0; gate_docs_only_plan HEAD || rc=$?\n"
        "printf '\\n@@plan\\n%s\\n%s\\n%s\\n%s\\n%s\\n%s\\n' \"$rc\" "
        '"${GATE_DOCS_ONLY_SOURCE-@unset}" "${GATE_DOCS_ONLY_N-@unset}" '
        '"${GATE_DOCS_ONLY_LEGS-@unset}" "${GATE_DOCS_ONLY_WHY-@unset}" '
        '"${GATE_DOCS_ONLY_READERS-@unset}"',
    )
    notes, mark, tail = out.rpartition("\n@@plan\n")
    assert mark and rc == 0, out
    names = ("rc", "source", "n", "legs", "why", "readers")
    shell = dict(zip(names, tail.split("\n"), strict=False))
    judged = ("rc", "why") if shell["rc"] != "0" else names
    assert _c_plan_py(repo) == {k: shell[k] for k in judged}, shell
    return {**shell, "notes": notes}


def _c_plan_py(repo: Path) -> dict[str, str]:
    """`ledger.docs_only_plan(repo, "HEAD")` in the globals' spelling: the Python body's answer."""
    try:
        plan = ledger.docs_only_plan(repo, "HEAD", say=lambda _: None)
    except ledger.DocsOnlyRefused as no:
        return {"rc": "1", "why": str(no)}
    return {
        "rc": "0",
        "source": plan.source,
        "n": str(plan.n),
        "legs": plan.legs,
        "why": "",
        "readers": ",".join(plan.readers),
    }


def test_the_docs_only_source_is_the_nearest_MEASURED_ancestor(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:

    rc, out = _sh(
        capture,
        ROOT,
        "for f in gate_docs_only_plan gate_docs_only_source gate_docs_only_admits; do "
        'command -v "$f" >/dev/null; done',
    )
    assert rc == 0, out
    repo = _c_world(scratch_repo, scratch_ledger, "r1")
    mtree = _git(repo, "rev-parse", "HEAD^{tree}")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["source"], plan["n"], plan["legs"], plan["why"]) == (
        "0",
        mtree,
        "1",
        DOCSONLY_LEGS,
        "",
    ), plan
    r1tree = _git(repo, "rev-parse", "HEAD^{tree}")
    sanction = f" sanction=docs-only from={mtree} paths=1 readers=static waited=0 took=0"
    _c_plant_full_row(scratch_ledger, r1tree, DOCSONLY_LEGS, sanction)
    _c_docs_commit(repo, DOCSONLY_DOC, "a second row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["source"], plan["n"]) == ("0", mtree, "1"), plan

    repo = _c_world(scratch_repo, scratch_ledger, "forged")
    mtree = _git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "apps/loud.py").write_text('print("a source change nobody measured")\n')
    with (repo / DOCSONLY_DOC).open("a") as sink:
        sink.write("one more row\n")
    _commit_all(repo, "a commit that is NOT docs-only, rowed as though it were")
    sanction = f" sanction=docs-only from={mtree} paths=1 readers=static waited=0 took=0"
    _c_plant_full_row(
        scratch_ledger, _git(repo, "rev-parse", "HEAD^{tree}"), DOCSONLY_LEGS, sanction
    )
    _c_docs_commit(repo, DOCSONLY_DOC, "and a docs row on top of it")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "1" and "apps/loud.py is not a docs-only path" in plan["why"], plan

    repo = _c_world(scratch_repo, scratch_ledger, "drive-row")
    mtree = _git(repo, "rev-parse", "HEAD^{tree}")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    r1tree = _git(repo, "rev-parse", "HEAD^{tree}")
    rc, out = _sh(
        capture, repo, f'drive_ledger_record "{r1tree}" test_reads_docs.sh 1 "{r1tree}" "x:1"'
    )
    if rc != 0:
        pytest.skip(f"drive_ledger_record would not write into the scratch ledger: {out}")
    _c_docs_commit(repo, DOCSONLY_DOC, "a second row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["source"], plan["n"]) == ("0", mtree, "1"), plan

    repo = _c_world(scratch_repo, scratch_ledger, "not-honoured")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    _c_plant_full_row(scratch_ledger, _git(repo, "rev-parse", "HEAD^{tree}"), "ruff,mypy")
    _c_docs_commit(repo, DOCSONLY_DOC, "a second row")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "1" and "nearest banked ancestor's row is not honoured" in plan["why"], (
        plan
    )
    assert "missing 'pytest-x2'" in plan["notes"], plan
    said: list[str] = []
    with pytest.raises(ledger.DocsOnlyRefused, match="row is not honoured"):
        ledger.docs_only_plan(repo, "HEAD", say=said.append)
    assert "missing 'pytest-x2'" in "\n".join(said), said

    repo = _c_world(scratch_repo, scratch_ledger, "empty")
    scratch_ledger.write_text("")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "1" and re.search("no honoured full row.*full bank", plan["why"]), plan


def test_the_docs_only_road_admits_a_declaring_product(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    rc, out = _sh(capture, ROOT, "command -v gate_docs_only_plan >/dev/null")
    assert rc == 0, out
    repo = _c_world(scratch_repo, scratch_ledger, "declaring")
    (repo / "scripts/planted_leg.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# A planted leg. It republishes derived/ on every green run, and the\n"
        "# bytes differ per box. Nothing measured reads them back.\n"
        "# >>> derived-tree-paths >>>\n"
        "# derived — a per-box artefact; nothing measured reads it back\n"
        "# <<< derived-tree-paths <<<\n"
    )
    (repo / "derived").mkdir()
    (repo / "derived/planted.png").write_text("the accepted look, as this box draws it\n")
    (repo / "derived.txt").write_text("measured: yes\n")
    _commit_all(repo, "the derived artefact, committed as the real one is")
    raw = _git(repo, "rev-parse", "HEAD^{tree}")
    rc, out = _sh(capture, repo, "gate_measured_tree 2>/dev/null")
    measured = out.strip() if rc == 0 else ""
    if not measured or measured == raw:
        pytest.skip(f"the planted declaration did not move the key: {raw} / {out}")
    _c_plant_full_row(scratch_ledger, measured, DOCSONLY_LEGS)
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"], plan["source"], plan["n"], plan["legs"]) == (
        "0",
        "",
        measured,
        "1",
        DOCSONLY_LEGS,
    ), plan
    (repo / "apps/loud.py").write_text('print("a change nothing measured")\n')
    _commit_all(repo, "an apps/ change on the declaring product")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "1" and "apps/loud.py is not a docs-only path" in plan["why"], plan


def test_a_quote_the_module_declares_a_non_read_takes_the_road(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _c_world(scratch_repo, scratch_ledger, "declared-quote")
    (repo / "apps/a.py").write_text(
        f"# {NONREAD_MARK} {DOCSONLY_DOC} — a string handed to an engine, never opened\n"
        f'PATH = "{DOCSONLY_DOC}"\n'
    )
    _c_rebase_m(repo, scratch_ledger, "a module that QUOTES a docs path and declares it no read")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == ("0", ""), plan
    assert plan["readers"] == "static" or plan["readers"].startswith("static,"), plan
    (repo / "apps/b.py").write_text(f'OTHER = "{DOCSONLY_DOC}"\n')
    _c_rebase_m(repo, scratch_ledger, "a second module quoting the same path, declaring nothing")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == (
        "1",
        f"docs-only? no — {DOCSONLY_DOC} is quoted at apps/b.py:1 and nothing declares the "
        "quote a non-read — full bank",
    ), plan


def test_an_undeclared_quote_refuses_and_names_a_quote_not_a_read(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _c_world(scratch_repo, scratch_ledger, "undeclared-quote")
    (repo / "apps/a.py").write_text(
        f'"""A docstring quoting \'{DOCSONLY_DOC}\' and opening nothing."""\n'
    )
    _c_rebase_m(repo, scratch_ledger, "a module that quotes a docs path and declares nothing")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == (
        "1",
        f"docs-only? no — {DOCSONLY_DOC} is quoted at apps/a.py:1 and nothing declares the "
        "quote a non-read — full bank",
    ), plan
    assert "read literally" not in plan["why"]
    elsewhere = f"{DOCSONLY_DIR}/elsewhere.md"
    (repo / "apps/a.py").write_text(
        f"# {NONREAD_MARK} {elsewhere} — a different path\n"
        f'ELSEWHERE = "{elsewhere}"\n'
        f'PATH = "{DOCSONLY_DOC}"\n'
    )
    _c_rebase_m(repo, scratch_ledger, "a module declaring one path and quoting two")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == (
        "1",
        f"docs-only? no — {DOCSONLY_DOC} is quoted at apps/a.py:3 and nothing declares the "
        "quote a non-read — full bank",
    ), plan


def test_every_docs_quote_in_a_template_test_module_is_declared(
    capture: Callable[..., object], env_strip: object
) -> None:

    docs = [p for p in _git(ROOT, "ls-files", "docs/*.md", "docs/**/*.md").splitlines() if p]
    if not docs:
        pytest.skip("git ls-files named no docs/**/*.md — a census over zero needles")
    needles = " ".join(f"{p} {p.rsplit('/', 1)[-1]}" for p in docs)
    rc, out = _sh(capture, ROOT, f"gate_docs_only_literal_reads {needles} 2>/dev/null")
    assert rc == 0, out
    seen: set[tuple[str, str]] = set()
    undeclared: list[str] = []
    for line in sorted(set(out.splitlines())):
        hit, _, needle = line.partition(" ")
        if not hit:
            continue
        file = hit.split(":", 1)[0]
        if not re.fullmatch(r"apps/.*/tests/.*\.py|apps/test_.*\.py", file):
            continue
        legit = [
            (f, d)
            for f, d in DOCS_QUOTE_LEGITIMATE_READS
            if f == file and (d == needle or d.rsplit("/", 1)[-1] == needle)
        ]
        if legit:
            seen.update(legit)
            continue
        covers, _ = _sh(capture, ROOT, f'gate_docs_only_nonread_covers "{file}" "{needle}"')
        assert ledger.docs_only_nonread_covers(ROOT / file, needle) is (covers == 0), hit
        if covers != 0:
            undeclared.append(f"{hit} {needle}")
    assert undeclared == [], f"declare each with `# {NONREAD_MARK} <path> — <why>`"
    for module, doc in DOCS_QUOTE_LEGITIMATE_READS:
        assert (module, doc) in seen, f"{module} is named as reading {doc}: a stale entry"
        assert re.search(r"read_text\(|open\(", (ROOT / module).read_text()), module


def test_a_stale_non_read_declaration_is_refused_naming_its_line(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:

    gone = f"{DOCSONLY_DIR}/gone.md"
    repo = _c_world(scratch_repo, scratch_ledger, "stale")
    (repo / "config/stale.py").write_text(
        '"""A module that quotes nothing at all."""\n'
        f"# {NONREAD_MARK} {gone} — the quote this excused was deleted\n"
    )
    _c_rebase_m(repo, scratch_ledger, "a module whose declaration outlived its quote")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == (
        "1",
        f"docs-only? no — config/stale.py:2 declares {gone} a non-read and the module never "
        "quotes it — a stale declaration — full bank",
    ), plan
    (repo / "config/stale.py").write_text(
        f'"""Mentions `{gone}` in backticks, which is prose."""\n'
        f"# {NONREAD_MARK} {gone} — the quote this excused was deleted\n"
    )
    _c_rebase_m(repo, scratch_ledger, "the stale declaration beside a prose mention")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "1", plan
    assert re.search(
        re.escape(f"config/stale.py:2 declares {gone}") + ".*stale declaration", plan["why"]
    ), plan


def test_a_path_outside_the_declared_list_is_a_full_bank(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _c_world(scratch_repo, scratch_ledger, "outside")
    with (repo / DOCSONLY_DOC).open("a") as sink:
        sink.write("one more row\n")
    (repo / "uv.lock").write_text("a lock line\n")
    _commit_all(repo, "a docs row and a lock file")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"], plan["readers"]) == (
        "1",
        "docs-only? no — uv.lock is not a docs-only path — full bank",
        "",
    ), plan
    inside: tuple[str, ...] = ("docs/product/queue.md", "README.md", "CLAUDE.md")
    inside += (".claude/skills/fixture/SKILL.md", "scripts/test_impact.json")
    outside = ("CHANGELOG.md", "TEMPLATE_VERSION", "uv.lock", "scripts/check.sh")
    for path, admitted in [(p, True) for p in inside] + [(p, False) for p in outside]:
        rc, out = _sh(capture, repo, f'gate_docs_only_admits "{path}"')
        assert (path, rc == 0) == (path, admitted), out
        assert ledger.docs_only_admits(path, root=repo) is admitted, path


WALLS_FOLD = Path(__file__).parent / "fixtures" / "walls_fold.json"


@pytest.mark.parametrize("planted", [False, True], ids=["real-fold", "planted-comment"])
def test_the_shell_and_the_python_admit_a_real_fold_alike(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], planted: bool
) -> None:
    """A real fold's walls diff (a stamp moved, rows renumbered, a row gained): one answer."""
    fold = json.loads(WALLS_FOLD.read_text())
    after = "\n".join(fold["after"]) + "\n"
    if planted:
        after = after.replace('  "members": {', '  # planted\n  "members": {')
    repo = scratch_repo()
    base = _commit(repo, {WALLS: "\n".join(fold["before"]) + "\n"})
    tip = _commit(repo, {WALLS: after})
    python = ledger.docs_only_admits(WALLS, base, tip, root=repo)
    rc, out = _sh(capture, repo, f'gate_docs_only_admits "{WALLS}" {base} {tip}')
    assert rc in (0, 1), out
    assert (python, rc == 0) == (not planted, not planted), out


def test_a_derived_sdk_page_is_a_full_bank_by_all_three_matchers(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _c_world(scratch_repo, scratch_ledger, "sdk")
    (repo / "docs/sdk").mkdir(parents=True)
    (repo / "docs/sdk/reference.md").write_text("a hand edit\n")
    _commit_all(repo, "a hand edit to a derived page")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == (
        "1",
        "docs-only? no — docs/sdk/reference.md is not a docs-only path — full bank",
    ), plan
    for path, admitted in (("docs/sdk/reference.md", False), ("docs/product/queue.md", True)):
        rc, out = _sh(capture, repo, f'gate_docs_only_admits "{path}"')
        assert (path, rc == 0) == (path, admitted), out
        assert ledger.docs_only_admits(path, root=repo) is admitted, path
        assert (path in loop_key.candidates(repo, frozenset({path}))) is admitted, path


def test_the_readers_are_derived_per_path_and_a_literal_read_refuses(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:

    repo = _c_world(scratch_repo, scratch_ledger, "opens")
    (repo / "apps/a.py").write_text(f'PATH = "{DOCSONLY_DOC}"\n')
    _c_rebase_m(repo, scratch_ledger, "a module that opens a docs path")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "1" and re.search(r"apps/a\.py:1.*full bank", plan["why"]), plan

    repo = _c_world(scratch_repo, scratch_ledger, "mentions")
    (repo / "apps/a.py").write_text(
        f"# the rows live in {DOCSONLY_DOC} and nothing here opens them\n"
        f'"""A docstring naming `{DOCSONLY_DOC}` and opening nothing."""\n'
    )
    _c_rebase_m(repo, scratch_ledger, "a module that MENTIONS a docs path")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert (plan["rc"], plan["why"]) == ("0", ""), plan

    repo = _c_world(scratch_repo, scratch_ledger, "yaml")
    (repo / "quality/quiet.yaml").write_text(
        f'rules:\n  - id: x\n    doc: {{ file: {DOCSONLY_DOC}, contains: "a row" }}\n'
    )
    _c_rebase_m(repo, scratch_ledger, "a rule whose doc: names a docs path")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    assert plan["rc"] == "0" and "full-house-rules" in plan["readers"].split(","), plan

    repo = _c_world(scratch_repo, scratch_ledger, "static")
    _c_docs_commit(repo, DOCSONLY_DOC, "one more row")
    plan = _c_plan(capture, repo)
    readers = plan["readers"].split(",")
    assert plan["rc"] == "0" and readers[0] == "static", plan
    assert "scripts/tests/test_reads_docs.sh" in readers, plan
    assert "scripts/tests/test_cites_docs.sh" not in readers, plan


def test_a_banked_row_whose_legs_do_not_cover_this_gate_is_not_honoured(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    tree = _sha40("legs-row")
    repo = _c_legs_checkout(scratch_repo, scratch_ledger, DOCSONLY_LEGS)
    _c_plant_full_row(scratch_ledger, tree, "ruff,mypy")
    assert _c_has_green(capture, repo, tree) == 1
    assert "missing 'pytest-x2'" in _c_lookup(capture, repo, tree)[1]
    _c_plant_full_row(scratch_ledger, tree, DOCSONLY_LEGS)
    assert _c_has_green(capture, repo, tree) == 0
    _c_plant_full_row(scratch_ledger, tree, f"{DOCSONLY_LEGS},something-new")
    assert _c_has_green(capture, repo, tree) == 0


def test_a_checkout_with_no_gate_declares_no_leg_set_and_compares_nothing(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    tree = _sha40("no-gate-row")
    scratch_ledger.write_text("")
    repo = _checkout(scratch_repo, "no-gate")
    (repo / "scripts/check.sh").unlink(missing_ok=True)
    _, declared = _sh(capture, repo, "gate_full_legs 2>/dev/null || true")
    assert declared == ""
    _c_plant_full_row(scratch_ledger, tree, "ruff,mypy")
    assert _c_has_green(capture, repo, tree) == 0


def _c_record(
    capture: Callable[..., object], repo: Path, tree: str, legs: str, proof: str, took: bool
) -> tuple[int, str]:
    """`gate_ledger_record` with `GATE_RUN_LEAK_PROOF` set to `proof` (a bash `$'…'` body)."""
    took_env = "GATE_PYTEST_TOOK=7 " if took else ""
    return _sh(
        capture,
        repo,
        f'{took_env}GATE_RUN_LEAK_PROOF=$\'{proof}\' gate_ledger_record "{tree}" "{legs}" 2>&1',
    )


def test_the_leak_proof_field_is_appended_last_or_the_row_is_refused(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    tree = _sha40("leak-proof-writer")
    scratch_ledger.write_text("")
    repo = _checkout(scratch_repo, "writer")
    proof = "acceptance:i-0123abc rc=0"
    rc, out = _c_record(capture, repo, tree, "ruff,pytest-x2/1", proof, True)
    assert rc == 0, out
    rows = _c_full_rows(scratch_ledger)
    assert rows[-1].endswith(f" waited=0 took=7 leak-proof={proof}"), rows
    assert len(rows) == 1
    assert _sh(capture, repo, f'gate_ledger_lookup "{tree}" >/dev/null 2>&1')[0] == 0
    before = len(_c_full_rows(scratch_ledger))
    rc, out = _c_record(capture, repo, tree, "ruff,pytest-x2/1", proof + "\\n", True)
    assert rc == 0, out
    rows = _c_full_rows(scratch_ledger)
    assert len(rows) - before == 1
    assert rows[-1].endswith(f"leak-proof={proof}"), rows
    before = len(rows)
    forged = proof + "\\nv1 forged full 2026-09-18T00:00:00Z everything caller=nobody"
    rc, out = _c_record(capture, repo, tree, "ruff,pytest-x2/1", forged, False)
    assert (rc, len(_c_full_rows(scratch_ledger))) == (1, before), out
    malformed = (
        "i-0123abc rc=0",
        "acceptance:i-0123abc",
        "acceptance:i-0123abc rc=",
        "acceptance:i-0123abc rc=x",
        "acceptance: rc=0",
        "acceptance:i 0123abc rc=0",
        "acceptance:i-0123abc rc=0 and more",
        "acceptance:i-0123abc rc=00",
        "acceptance:i-0123abc rc=01",
    )
    for value in malformed:
        before = len(_c_full_rows(scratch_ledger))
        rc, out = _c_record(capture, repo, tree, "ruff,pytest-x2/1", value, False)
        assert (value, rc, len(_c_full_rows(scratch_ledger))) == (value, 1, before), out
        assert "leak-proof" in out, (value, out)
    scratch_ledger.write_text("")
    repo = _checkout(scratch_repo, "writer-empty")
    tree = _sha40("leak-proof-empty")
    rc, out = _c_record(capture, repo, tree, "ruff,pytest-x2", "", True)
    assert rc == 0, out
    row = _c_full_rows(scratch_ledger)[-1]
    assert "leak-proof" not in row and row.endswith(" waited=0 took=7"), row


def test_a_one_pass_row_is_honoured_only_with_a_green_leak_proof(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _c_legs_checkout(scratch_repo, scratch_ledger, DOCSONLY_LEGS)
    one_pass = "ruff,mypy,pytest-x2/1,selftest"  # noqa: S105 — a list of gate leg names, not a credential
    green = " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
    red = " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=1"

    def plant(seed: str, legs: str, extra: str = "") -> str:
        tree = _sha40(seed)
        _c_plant_full_row(scratch_ledger, tree, legs, extra)
        return tree

    assert _c_has_green(capture, repo, plant("onepass-green", one_pass, green)) == 0
    rc, out = _c_lookup(capture, repo, plant("onepass-red", one_pass, red))
    assert rc == 1
    assert (
        "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof "
        "(leak-proof=acceptance:i-0f1e2d3c rc=1)"
    ) in out, out
    rc, out = _c_lookup(capture, repo, plant("onepass-none", one_pass))
    assert rc == 1
    assert (
        "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof "
        "(leak-proof=none)"
    ) in out, out
    malformed = " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c"
    assert _c_has_green(capture, repo, plant("onepass-malformed", one_pass, malformed)) == 1
    rc, out = _c_lookup(capture, repo, plant("twopass-today", DOCSONLY_LEGS))
    assert rc == 0 and "leak-proof" not in out, out
    rc, out = _c_lookup(capture, repo, plant("twopass-extra-proof", DOCSONLY_LEGS, red))
    assert rc == 0 and "leak-proof ignored: the row ran two passes" in out, out
    spelled = "ruff,mypy,pytest-x2/2,selftest"
    assert _c_has_green(capture, repo, plant("twopass-spelled", spelled)) == 0
    spelled = "ruff,mypy,pytest-x2/10,selftest"
    assert _c_has_green(capture, repo, plant("tenpass-spelled", spelled)) == 0
    for shape in ("pytest-x2/0", "pytest-x2/", "pytest-x2/x", "pytest-x2/1/1"):
        tree = plant(f"suffix-{shape}", f"ruff,mypy,{shape},selftest", green)
        rc, out = _c_lookup(capture, repo, tree)
        assert (shape, rc) == (shape, 1) and "missing 'pytest-x2'" in out, out
    tree = plant("onepass-wrong-unit", "ruff,mypy,pytest-x2,selftest/1", green)
    rc, out = _c_lookup(capture, repo, tree)
    assert rc == 1
    assert (
        "missing 'selftest' — the row ran ONE pass of a leg that is not 'pytest-x2', and one "
        "pass is sanctioned for that unit alone"
    ) in out, out
    superset = f"{one_pass},something-new"
    assert _c_has_green(capture, repo, plant("onepass-superset", superset, green)) == 0
    rc, out = _c_lookup(capture, repo, plant("onepass-short", "ruff,mypy", green))
    assert rc == 1 and "missing 'pytest-x2'" in out, out


def test_a_ci_proof_is_a_green_form_and_the_writer_refuses_a_malformed_one(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _c_legs_checkout(scratch_repo, scratch_ledger, DOCSONLY_LEGS)
    one_pass = "ruff,mypy,pytest-x2/1,selftest"  # noqa: S105 — a list of gate leg names, not a credential
    tree = _sha40("ci-proof-green")
    _c_plant_full_row(
        scratch_ledger, tree, one_pass, f" waited=0 took=0 leak-proof=ci:{CI_RUN_FIXTURE} rc=0"
    )
    assert _c_has_green(capture, repo, tree) == 0
    tree = _sha40("ci-proof-red")
    _c_plant_full_row(
        scratch_ledger, tree, one_pass, f" waited=0 took=0 leak-proof=ci:{CI_RUN_FIXTURE} rc=1"
    )
    rc, out = _c_lookup(capture, repo, tree)
    assert rc == 1
    assert f"carries no green leak proof (leak-proof=ci:{CI_RUN_FIXTURE} rc=1)" in out, out
    tree = _sha40("ci-proof-abc")
    _c_plant_full_row(scratch_ledger, tree, one_pass, " waited=0 took=0 leak-proof=ci:abc rc=0")
    assert _c_has_green(capture, repo, tree) == 1
    tree = _sha40("ci-proof-writer")
    rc, out = _sh(
        capture,
        repo,
        f'GATE_PYTEST_TOOK=0 GATE_RUN_LEAK_PROOF="ci:{CI_RUN_FIXTURE} rc=0" '
        f'gate_ledger_record "{tree}" "{one_pass}" 2>&1',
    )
    assert rc == 0, out
    assert _c_full_rows(scratch_ledger)[-1].endswith(f" leak-proof=ci:{CI_RUN_FIXTURE} rc=0")
    assert _c_has_green(capture, repo, tree) == 0
    for value in (
        "ci:abc rc=0",
        "ci:0123 rc=0",
        "ci: rc=0",
        f"ci:{CI_RUN_FIXTURE}",
        f"ci:{CI_RUN_FIXTURE} rc=00",
    ):
        before = len(_c_full_rows(scratch_ledger))
        rc, out = _c_record(capture, repo, tree, "ruff,pytest-x2/1", value, False)
        assert (value, rc, len(_c_full_rows(scratch_ledger))) == (value, 1, before), out
        assert "'ci:<run id> rc=<n>'" in out, (value, out)


def test_the_ci_record_has_one_grammar_both_ends(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:

    commit, tree, at = _sha40("ci-record-commit"), _sha40("ci-record-tree"), "20260927T120000Z"
    rc, line = _sh(
        capture,
        ROOT,
        f'gate_ci_record_line "{commit}" "{tree}" "static,supply-chain,pytest-x2/1,selftest" '
        f'6 whole 0 "{CI_RUN_FIXTURE}" 2 "{at}" 2>/dev/null',
    )
    assert (rc, line.rstrip("\n")) == (
        0,
        f"schema=gate-verdict/1 at={at} commit={commit} tree={tree} "
        "legs=static,supply-chain,pytest-x2/1,selftest shards=6 scope=whole rc=0 "
        f"run={CI_RUN_FIXTURE} attempt=2 where=ci",
    )
    _, line = _sh(
        capture,
        ROOT,
        f'gate_ci_record_line "{commit}" "{tree}" static 0 pr 1 "{CI_RUN_FIXTURE}" 1 2>/dev/null',
    )
    assert re.match(r"schema=gate-verdict/1 at=[0-9]{8}T[0-9]{6}Z commit=", line), line
    rc, out = _sh(
        capture,
        ROOT,
        f'line=$(gate_ci_record_line "{commit}" "{tree}" "static,pytest-x2/1" 3 whole 0 '
        f'"{CI_RUN_FIXTURE}" 4 "{at}" 2>/dev/null) || line=""\n'
        'rc=0; gate_ci_record_parse "$line" 2>/dev/null || rc=$?\n'
        'parsed=$(gate_ci_record_line "${GATE_CI_REC_COMMIT:-}" "${GATE_CI_REC_TREE:-}" '
        '"${GATE_CI_REC_LEGS:-}" "${GATE_CI_REC_SHARDS:-}" "${GATE_CI_REC_SCOPE:-}" '
        '"${GATE_CI_REC_RC:-}" "${GATE_CI_REC_RUN:-}" "${GATE_CI_REC_ATTEMPT:-}" '
        '"${GATE_CI_REC_AT:-}" 2>/dev/null) || parsed=""\n'
        'printf \'%s\\n%s\\n%s\\n\' "$rc" "$line" "$parsed"',
    )
    parse_rc, line, parsed = out.split("\n")[:3]
    assert (rc, parse_rc) == (0, "0"), out
    assert line and parsed == line, out
    mutations = (
        ("schema=gate-verdict/1", "schema=gate-verdict/2"),
        (f"at={at}", "at=2026-09-27T12:00:00Z"),
        (f"at={at}", "at=20261327T120000Z"),
        (f"commit={commit}", f"commit={commit[:39]}"),
        (f"tree={tree}", f"tree={tree}0"),
        ("legs=static,pytest-x2/1", "legs=static,,pytest-x2"),
        ("legs=static,pytest-x2/1", "legs=static,pytest-x2/2"),
        ("shards=3", "shards=03"),
        ("scope=whole", "scope=all"),
        ("rc=0", "rc=00"),
        (f"run={CI_RUN_FIXTURE}", f"run=0{CI_RUN_FIXTURE}"),
        ("attempt=4", "attempt=0"),
        ("where=ci", "where=box"),
        (" where=ci", " where=ci rc=0"),
        (" attempt=4", " attempt=4 "),
        ("rc=0 ", "rc=0  "),
    )
    bad_lines = [line.replace(old, new, 1) for old, new in mutations]
    assert all(bad != line for bad in bad_lines)
    lines_file = scratch / "ci-bad-lines"
    lines_file.write_text("".join(f"{bad}\n" for bad in bad_lines))
    rc, out = _sh(
        capture,
        ROOT,
        f'while IFS= read -r l; do rc=0; gate_ci_record_parse "$l" 2>/dev/null || rc=$?; '
        f'echo "$rc"; done <"{lines_file}"\n'
        'rc=0; gate_ci_record_parse "" 2>/dev/null || rc=$?; echo "$rc"',
    )
    assert out.split() == ["2"] * (len(mutations) + 1), (out, mutations)
    rc, out = _sh(
        capture,
        ROOT,
        f'gate_ci_record_line "{commit}" "{tree}" static 3 whole 00 "{CI_RUN_FIXTURE}" 1 '
        "2>/dev/null",
    )
    assert (rc, out) == (2, "")
    rc, out = _sh(
        capture, ROOT, f'gate_ci_record_line "{commit}" "{tree}" static 3 whole 0 2>/dev/null'
    )
    assert rc == 2


def _c_nightly_fixture(directory: Path, at: str, rc: str, extra: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "leak_proof.txt").write_text(
        f"schema=leak-proof/1 at={at} commit={_sha40('nightly-commit')} "
        f"tree={_sha40('nightly-tree')} seed=4242 pass1=ok pass2=ok map=written rc={rc} "
        f"run={CI_RUN_FIXTURE} attempt=1 where=nightly{extra}\n"
    )


def test_the_nightly_reader_returns_three_forms_and_refuses_the_unreadable(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:

    rc, out = _sh(
        capture,
        ROOT,
        "now=$(date -u +%s)\n"
        'gate_ci_stamp_of "$((now - 3600))"; gate_ci_stamp_of "$((now - 2 * 86400))"\n'
        'gate_ci_stamp_of "$((now + 3600))"',
    )
    assert rc == 0, out
    fresh, stale, future = out.split()
    tree12 = _sha40("nightly-tree")[:12]

    def read(directory: Path | str) -> tuple[int, str]:
        rc, out = _sh(capture, ROOT, f'gate_nightly_read "{directory}" 2>/dev/null')
        assert (rc, ledger.nightly_read(str(directory))) == (0, out.strip())
        return rc, out

    rc, out = _sh(capture, ROOT, 'gate_nightly_read "" 2>/dev/null')
    assert (rc, out.strip()) == (0, "nightly:none") == (0, ledger.nightly_read(""))
    _c_nightly_fixture(scratch / "nightly-fresh", fresh, "0")
    assert read(scratch / "nightly-fresh")[1].strip() == f"nightly:{fresh} tree={tree12} rc=0"
    _c_nightly_fixture(scratch / "nightly-fresh-red", fresh, "1")
    assert read(scratch / "nightly-fresh-red")[1].strip() == f"nightly:{fresh} tree={tree12} rc=1"
    _c_nightly_fixture(scratch / "nightly-stale", stale, "0")
    assert read(scratch / "nightly-stale")[1].strip() == f"nightly:stale:{stale}"
    for name in ("no-dir", "empty-dir", "garbage", "future", "twice", "unknown-field", "bad-hex"):
        d = scratch / f"nightly-{name}"
        if name == "empty-dir":
            d.mkdir()
        elif name == "garbage":
            d.mkdir()
            (d / "leak_proof.txt").write_text("this is not a record\n")
        elif name == "future":
            _c_nightly_fixture(d, future, "0")
        elif name == "twice":
            _c_nightly_fixture(d, fresh, "0", " rc=0")
        elif name == "unknown-field":
            _c_nightly_fixture(d, fresh, "0", " colour=blue")
        elif name == "bad-hex":
            _c_nightly_fixture(d, fresh, "0")
            record = (d / "leak_proof.txt").read_text()
            (d / "leak_proof.txt").write_text(
                re.sub(" tree=[0-9a-f]* ", " tree=xyz ", record, count=1)
            )
        out_file, err_file = scratch / f"{name}.out", scratch / f"{name}.err"
        rc, _ = _sh(
            capture,
            ROOT,
            f'rc=0; gate_nightly_read "{d}" >"{out_file}" 2>"{err_file}" || rc=$?; exit "$rc"',
        )
        assert (name, rc, out_file.read_text()) == (name, 2, ""), err_file.read_text()
        assert "nightly: unreadable — " in err_file.read_text(), name
        with pytest.raises(ledger.NightlyUnreadable) as said:
            ledger.nightly_read(str(d))
        assert re.sub("[0-9]+ s in", "N s in", str(said.value)) == re.sub(
            "[0-9]+ s in", "N s in", err_file.read_text().strip()
        ), name


def test_the_nightly_writer_spells_the_readers_grammar_and_refuses_out_of_it(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:
    at = ledger.ci_stamp(int(time.time()) - 60)
    commit, tree = _sha40("nightly-commit"), _sha40("nightly-tree")
    good = [at, commit, tree, "4242", "0", "1", "-", "1", CI_RUN_FIXTURE, "2", "nightly"]

    def shell(fields: list[str]) -> tuple[int, str]:
        return _sh(
            capture, ROOT, "gate_nightly_line " + " ".join(f"'{f}'" for f in fields) + " 2>&1"
        )

    rc, out = shell(good)
    assert rc == 0, out
    line = ledger.nightly_line(good)
    assert (
        line
        == out.strip()
        == (
            f"schema=leak-proof/1 at={at} commit={commit} tree={tree} seed=4242 pass1=0 pass2=1"
            f" map=- rc=1 run={CI_RUN_FIXTURE} attempt=2 where=nightly"
        )
    )
    (scratch / "record").mkdir()
    (scratch / "record" / "leak_proof.txt").write_text(line + "\n")
    assert ledger.nightly_read(str(scratch / "record")) == f"nightly:{at} tree={tree[:12]} rc=1"
    acceptance = [*good[:8], "0", "0", "acceptance"]
    assert ledger.nightly_line(acceptance) == shell(acceptance)[1].strip()
    bad = {
        "ten-fields": good[:10],
        "nightly-names-no-run": [*good[:8], "0", "0", "nightly"],
        "rc-3": [*good[:7], "3", *good[8:]],
        "pass1-word": [*good[:4], "ok", *good[5:]],
        "short-tree": [*good[:2], tree[:12], *good[3:]],
        "where-box": [*good[:10], "box"],
    }
    for name, fields in bad.items():
        rc, out = shell(fields)
        assert rc == 2, name
        with pytest.raises(ledger.Refused) as said:
            ledger.nightly_line(fields)
        assert str(said.value) == out.strip(), name
    rc, out = _sh(capture, ROOT, "gate_ci_artifact_name 3")
    assert ledger.ci_artifact_name("3") == out.strip() == f"{ledger.CI_ARTIFACT}-3"


#: A fake `gh` serving the nightly's three calls from fixtures under `__GH__`.
NIGHTLY_GH = """#!/usr/bin/env bash
GH="__GH__"
case "${1:-} ${2:-}" in
"run list")
    [ ! -f "$GH/list.rc" ] || { echo "HTTP 502" >&2; exit "$(cat "$GH/list.rc")"; }
    cat "$GH/list.out" 2>/dev/null; exit 0 ;;
"run view") cat "$GH/view-$3"; exit 0 ;;
"run download")
    id=$3; shift 3; name="" dir=""
    while [ "$#" -gt 0 ]; do
        case "$1" in --name) name=$2; shift ;; --dir) dir=$2; shift ;; esac; shift
    done
    [ ! -f "$GH/download.rc" ] || { echo "HTTP 500" >&2; exit "$(cat "$GH/download.rc")"; }
    [ -d "$GH/art-$id/$name" ] || { echo "no valid artifacts found to download" >&2; exit 1; }
    mkdir -p "$dir"; cp "$GH/art-$id/$name/"* "$dir/"; exit 0 ;;
esac
exit 1
"""


def test_the_nightly_fetch_and_source_read_the_latest_run_and_always_name_a_form(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:
    gh_dir, sink = scratch / "gh", scratch / "sink"
    gh = scratch / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(NIGHTLY_GH.replace("__GH__", str(gh_dir)))
    gh.chmod(0o755)
    now = int(time.time())
    commit, tree, other = _sha40("n-commit"), _sha40("n-tree"), _sha40("n-other")
    teeth = (
        "report-only: this bank is honoured; the deploy to prod refuses without a green nightly"
        " ≤ 24 h"
    )

    def plant(form: str) -> str:
        shutil.rmtree(gh_dir, ignore_errors=True)
        gh_dir.mkdir()
        if form == "none":
            (gh_dir / "list.out").write_text("")
            return ""
        if form == "fail":
            (gh_dir / "list.rc").write_text("1\n")
            return ""
        (gh_dir / "list.out").write_text("555\n")
        (gh_dir / "view-555").write_text("completed 2\n")
        if form == "dlfail":
            (gh_dir / "download.rc").write_text("1\n")
        if form in ("noart", "dlfail"):
            return ""
        at = ledger.ci_stamp(now - (172800 if form == "stale" else 3600))
        fields = [at, commit, other if form == "foreign" else tree, "99", "0", "0", "0"]
        fields += ["1" if form == "red" else "0", "555", "1" if form == "early" else "2"]
        art = gh_dir / "art-555" / "nightly-leak-proof"
        art.mkdir(parents=True)
        (art / "leak_proof.txt").write_text(ledger.nightly_line([*fields, "nightly"]) + "\n")
        return at

    def shell(verb: str, *args: str, gh_: Path = gh) -> tuple[int, str]:
        said = " ".join(f'"{a}"' for a in args)
        return _sh(capture, ROOT, f'GATE_NIGHTLY_GH="{gh_}"\ngate_nightly_{verb} {said}')

    dl = f"{sink}/nightly-555"
    fetched = {
        "green": (0, f"555 2 {dl}"),
        "none": (1, "no completed nightly-proof.yml run on main"),
        "fail": (2, f"`gh run list --workflow nightly-proof.yml` did not answer ({sink}/gh-nightly-list.err)"),  # noqa: E501
        "noart": (1, "nightly run 555 (attempt 2) carries no nightly-leak-proof artifact"),
        "dlfail": (2, "`gh run download 555 --name nightly-leak-proof` failed for a reason that is not a missing artifact"  # noqa: E501
                   f" ({sink}/gh-nightly-download.log)"),
        "early": (1, "nightly run 555's record says attempt=1 and the latest attempt is 2 — an earlier attempt's record is not the run's"),  # noqa: E501
    }  # fmt: skip
    for form, want in fetched.items():
        plant(form)
        rc, out = shell("fetch", str(sink))
        assert (rc, out.strip()) == want, form
        assert ledger.nightly_fetch(sink, gh=str(gh)) == want, form
    missing = scratch / "bin" / "no-gh"
    want = (
        2,
        f"no `{missing}` on PATH — the nightly's record is a workflow artifact and `gh` is its"
        " one reader",
    )
    assert ledger.nightly_fetch(sink, gh=str(missing)) == want
    rc, out = shell("fetch", str(sink), gh_=missing)
    assert (rc, out.strip()) == want

    for form in ("green", "foreign", "red", "stale", "none", "noart", "fail"):
        at = plant(form)
        night = other if form == "foreign" else tree
        source = {
            "green": (f"nightly:{at} tree={tree[:12]} rc=0",
                      f"leak-proof: nightly run 555 attempt 2 green — nightly:{at} tree={tree[:12]} rc=0"),  # noqa: E501
            "foreign": (f"nightly:{at} tree={night[:12]} rc=0",
                        f"leak-proof: nightly run 555 attempt 2 green — nightly:{at} tree={night[:12]} rc=0"  # noqa: E501
                        f" (measured {night[:12]}, not this bank's {tree[:12]}: report-only)"),
            "red": (f"nightly:{at} tree={tree[:12]} rc=1",
                    f"WARNING: leak-proof: the latest nightly (run 555, attempt 2) is RED (rc=1) — nightly:{at} tree={tree[:12]} rc=1; {teeth}"),  # noqa: E501
            "stale": (f"nightly:stale:{at}",
                      f"WARNING: leak-proof: the latest nightly (run 555, attempt 2) is older than 24 h — nightly:stale:{at}; {teeth}"),  # noqa: E501
            "none": ("nightly:none",
                     f"WARNING: leak-proof: no nightly leak proof (no completed nightly-proof.yml run on main) — nightly:none; {teeth}"),  # noqa: E501
            "noart": ("nightly:none",
                      f"WARNING: leak-proof: no nightly leak proof (nightly run 555 (attempt 2) carries no nightly-leak-proof artifact) — nightly:none; {teeth}"),  # noqa: E501
            "fail": ("nightly:none",
                     f"WARNING: leak-proof: no nightly leak proof (could not look: `gh run list --workflow nightly-proof.yml` did not answer ({sink}/gh-nightly-list.err)) — nightly:none; {teeth}"),  # noqa: E501
        }[form]  # fmt: skip
        rc, out = shell("source", str(sink), tree)
        assert (rc, tuple(out.splitlines())) == (0, source), form
        assert ledger.nightly_source(sink, tree, gh=str(gh)) == source, form


def test_a_drive_row_is_never_a_full_verdict(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    tree = _sha40("drive-row-not-a-full-verdict")
    repo = _c_legs_checkout(scratch_repo, scratch_ledger, DOCSONLY_LEGS)
    _c_plant_drive_row(scratch_ledger, tree, "sweep")
    assert _c_has_green(capture, repo, tree) == 1
    _c_plant_full_row(scratch_ledger, tree, DOCSONLY_LEGS)
    assert _c_has_green(capture, repo, tree) == 0


def _c_key_field(out: str) -> str:
    return "\n".join((line.split() + ["", ""])[1] for line in out.splitlines())


def test_the_machine_half_is_the_image_on_a_box_and_the_host_elsewhere(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:

    home = scratch / "machine-half"
    (home / "set").mkdir(parents=True)
    (home / "shim").mkdir()
    (home / "set/drive_preamble.sh").write_text(
        "# a scratch drive set preamble — never sourced, always keyed\n"
    )
    (home / "set/test_machinehalf.sh").write_text(
        "#!/bin/sh\n# drives" + ": scripts/gate_ledger.sh\nexit 0\n"
    )
    (home / "listing").write_text(
        f"100644 blob {_sha40('machine-half-blob')}\tscripts/gate_ledger.sh\n"
    )
    (home / "shim/bash").write_text('#!/bin/sh\necho "GNU bash, version 9.9.9(1)-release"\n')
    (home / "shim/bash").chmod(0o755)
    (home / "image-a").write_text("ami-0aaaa1111aaaa1111\n")
    (home / "image-b").write_text("ami-0bbbb2222bbbb2222\n")
    absent = home / "absent-marker"

    def keyof(machine: Path | str = absent, shim: bool = False) -> tuple[int, str]:
        path = f'export PATH="{home}/shim:$PATH"\n' if shim else ""
        return _sh(
            capture,
            ROOT,
            "unset DRIVE_MACHINE_DIGEST DRIVE_MACHINE_LABEL\n"
            f'export DJB_DRIVE_MACHINE_FILE="{machine}"\n{path}'
            f'drive_key "{home}/set/test_machinehalf.sh" fake-tree "{home}/listing" 2>&1',
        )

    host_out = keyof()[1].rstrip("\n")
    imga_out = keyof(home / "image-a")[1].rstrip("\n")
    imga_shim_out = keyof(home / "image-a", shim=True)[1]
    imgb_out = keyof(home / "image-b")[1]
    host_key, imga_key = _c_key_field(host_out), _c_key_field(imga_out)
    imga_shim_key, imgb_key = _c_key_field(imga_shim_out), _c_key_field(imgb_out)
    assert re.fullmatch(r"ok drive-v1:.* machine=image:ami-0aaaa1111aaaa1111", imga_out), imga_out
    assert re.fullmatch(r"ok drive-v1:.* machine=host:.*", host_out, re.DOTALL), host_out
    assert imga_key == imga_shim_key
    assert imga_key != imgb_key
    assert imga_key != host_key and imgb_key != host_key
    assert host_key != _c_key_field(keyof(shim=True)[1])
    (home / "image-locked").write_text("ami-0cccc3333cccc3333\n")
    (home / "image-locked").chmod(0o000)
    try:
        locked_rc, locked_out = keyof(home / "image-locked")
    finally:
        (home / "image-locked").chmod(0o644)
    assert locked_rc == 1
    assert locked_out.startswith("err this machine could not be digested"), locked_out
    rel_rc, rel_out = keyof("not/absolute/image-id")
    assert rel_rc == 1 and "is relative — refusing it" in rel_out, rel_out


def test_a_reserved_drawer_path_is_judged_even_where_the_tree_has_none(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:
    home = scratch / "drawer-floor"
    (home / "set").mkdir(parents=True)
    (home / "set/drive_preamble.sh").write_text(
        "# a scratch drive set preamble — never sourced, always keyed\n"
    )
    listing = (
        ("drawer-floor-a", "scripts/gate_ledger.sh"),
        ("drawer-floor-b", "apps/example/models.py"),
        ("drawer-floor-c", "docs/product/queue.md"),
        ("drawer-floor-d", "quality/rules.yaml"),
    )
    (home / "listing").write_text(
        "".join(f"100644 blob {_sha40(seed)}\t{path}\n" for seed, path in listing)
    )
    drive = home / "set/test_drawerfloor.sh"

    def keyof(spelled: str, cites: str = "") -> tuple[int, str]:
        drive.write_text(
            f"#!/bin/sh\n# drives: scripts/gate_ledger.sh\n{cites}# a body that spells "
            f"{spelled}\nexit 0\n"
        )
        return _sh(capture, ROOT, f'drive_key "{drive}" fake-tree "{home}/listing" 2>&1')

    rc, out = keyof("scripts/local/legs")
    assert rc == 1 and out.startswith("err its body spells scripts/local/legs and"), out
    rc, out = keyof("scripts/local/legs", "# cites: scripts/local/legs\n")
    assert rc == 0 and out.startswith("ok drive-v1:"), out
    assert keyof("apps/zzz_a_plant_no_tree_has/models.py")[0] == 0
    for spelled in ("docs" + "/product/instruments.local.md", "apps/conftest_local.py"):
        assert (spelled, keyof(spelled)[0]) == (spelled, 1)
    rc, out = _sh(capture, ROOT, "drive_drawer_globs")
    assert (rc, out.rstrip("\n")) == (0, "**/local/** *.local.md apps/conftest_local.py"), out
    assert _sh(capture, home, "drive_drawer_globs >/dev/null 2>&1")[0] == 1


def test_an_absorbed_derived_output_keys_as_absent_and_nothing_else_does(
    scratch: Path, capture: Callable[..., object], env_strip: object
) -> None:
    home = scratch / "absorbed"
    (home / "set").mkdir(parents=True)
    (home / "set/drive_preamble.sh").write_text(
        "# a scratch drive set preamble — never sourced, always keyed\n"
    )
    drives = "drives" + ":"
    (home / "set/test_absorbed.sh").write_text(
        f"#!/bin/sh\n# {drives} scripts/gate_ledger.sh scripts/test_impact.json\nexit 0\n"
    )
    (home / "set/test_notabsorbed.sh").write_text(
        f"#!/bin/sh\n# {drives} scripts/gate_ledger.sh scripts/loop_tier.sh\nexit 0\n"
    )
    without = f"100644 blob {_sha40('absorbed-a')}\tscripts/gate_ledger.sh\n"
    (home / "without").write_text(without)
    (home / "with").write_text(
        without + f"100644 blob {_sha40('absorbed-b')}\tscripts/test_impact.json\n"
    )

    def key(drive: str, listing: str) -> tuple[int, str]:
        return _sh(
            capture, ROOT, f'drive_key "{home}/set/{drive}" fake-tree "{home}/{listing}" 2>&1'
        )

    rc, out_without = key("test_absorbed.sh", "without")
    assert rc == 0 and "scripts/test_impact.json:absent" in out_without, out_without
    rc, out_with = key("test_absorbed.sh", "with")
    assert rc == 0, out_with
    assert _c_key_field(out_without) != _c_key_field(out_with)
    rc, out = key("test_notabsorbed.sh", "without")
    assert rc == 1, out
    assert out.startswith("err the declared path scripts/loop_tier.sh expands to nothing"), out
    rc, out = _sh(capture, ROOT, "drive_absorbed_paths")
    assert (rc, out.rstrip("\n")) == (0, "scripts/test_impact.json")
    assert _sh(capture, home, "drive_absorbed_paths >/dev/null 2>&1")[0] == 1


PUSH_STUB_GATE = '#!/usr/bin/env bash\nFULL_LEGS=drive-legs\necho "STUB GATE RAN"\nexit 0\n'


def _hook_packages(work: Path) -> None:
    """The belt imports the package from the checkout: `quality/` and `apps/` linked, excluded."""
    for package in ("quality", "apps"):
        (work / package).symlink_to(ROOT / package)
    if (work / ".git").is_dir():
        with (work / ".git/info/exclude").open("a") as exclude:
            exclude.write("/quality\n/apps\n")


def _c_push_world(
    scratch: Path, capture: Callable[..., object], name: str
) -> tuple[Path, Path, str]:
    """The drive's `push_world`: a checkout with the real hook, a stub gate and a scratch remote."""
    work, remote = scratch / name / "work", scratch / name / "origin.git"
    (work / "scripts/githooks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    for argv in (
        ("symbolic-ref", "HEAD", "refs/heads/main"),
        ("config", "user.email", "drive@example.invalid"),
        ("config", "user.name", "pre-push drive"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.hooksPath", "scripts/githooks"),
        ("remote", "add", "origin", str(remote)),
    ):
        _git(work, *argv)
    for script in ("gate_ledger.sh", "gate_refuse.sh"):
        shutil.copy2(ROOT / "scripts" / script, work / "scripts" / script)
    shutil.copy2(ROOT / "scripts/githooks/pre-push", work / "scripts/githooks/pre-push")
    (work / "scripts/githooks/pre-push").chmod(0o755)
    (work / "scripts/check.sh").write_text(PUSH_STUB_GATE)
    (work / "scripts/check.sh").chmod(0o755)
    (work / "README.md").write_text("the measured content\n")
    _hook_packages(work)
    _commit_all(work, "main, and this is the tree the gate measured")
    main = _git(work, "rev-parse", "HEAD")
    rc, out = _sh(
        capture, work, f'gate_ledger_record "$(git rev-parse "{main}^{{tree}}")" drive-legs'
    )
    if rc != 0:
        pytest.skip(f"gate_ledger_record would not write into the scratch ledger: {out}")
    return work, remote, main


def _c_push_unmeasured(work: Path, name: str = "red") -> str:
    _git(work, "checkout", "-q", "-b", name)
    (work / "RED.md").write_text("a test that has never been run\n")
    _git(work, "add", "RED.md")
    _git(work, "commit", "-q", "-m", "bytes no gate has measured")
    sha = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "main")
    return sha


def _c_push(capture: Callable[..., object], work: Path, *refspecs: str) -> tuple[int, str]:
    done = capture(["git", "-C", str(work), "push", "origin", *refspecs])
    return done.rc, done.path.read_text(errors="replace")  # type: ignore[attr-defined]


def _c_has_ref(remote: Path, ref: str) -> int:
    argv = ["git", "-C", str(remote), "rev-parse", "-q", "--verify", ref]
    return subprocess.run(argv, capture_output=True).returncode


def test_a_push_of_a_ref_that_is_not_the_measured_tree_is_not_honoured(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    work, remote, _ = _c_push_world(scratch, capture, "push-red")
    red = _c_push_unmeasured(work)
    rc, out = _c_push(capture, work, f"{red}:refs/heads/red")
    assert "verdict honoured" not in out, out
    assert "REFUSED — the ref being pushed is not the tree in this checkout" in out, out
    assert rc == 1
    assert _c_has_ref(remote, "refs/heads/red") == 1


def test_pm_pushs_detached_sha_push_is_honoured_in_seconds(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    work, remote, main = _c_push_world(scratch, capture, "push-pm")
    wt = scratch / "pmpush"
    _git(work, "worktree", "add", "-q", "--detach", str(wt), main)
    _hook_packages(wt)
    rc, out = _c_push(capture, wt, f"{main}:refs/heads/shipped")
    assert rc == 0, out
    assert "verdict honoured" in out, out
    assert "STUB GATE RAN" not in out, out
    assert _git(remote, "rev-parse", "refs/heads/shipped") == main


def test_an_ordinary_push_of_the_measured_branch_is_honoured(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    work, _, _ = _c_push_world(scratch, capture, "push-plain")
    rc, out = _c_push(capture, work, "main")
    assert rc == 0 and "verdict honoured" in out, out


def test_a_multi_ref_push_is_vouched_for_only_when_every_tree_is_measured(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    work, remote, main = _c_push_world(scratch, capture, "push-multi")
    red = _c_push_unmeasured(work)
    rc, out = _c_push(capture, work, f"{main}:refs/heads/one", f"{red}:refs/heads/two")
    assert rc == 1, out
    assert "verdict honoured" not in out, out
    assert _c_has_ref(remote, "refs/heads/one") == 1


# end of group C

# --- group D: the loop key's prose subtraction ----------------------------------------------------

CENSUS_FILES = (
    "quality/__init__.py",
    "quality/loop_key.py",
    "quality/could_not_look.py",
    "quality/tree.py",
    "apps/__init__.py",
    "apps/core/__init__.py",
    "apps/core/roads.py",
    "scripts/gate_ledger.sh",
)
SCOPE = "mode=fast scope=- always=abc"
RUNBOOKS = "docs" + "/runbooks"
CYCLES = "docs" + "/product/cycles"


def _census_checkout(scratch_repo: Callable[..., Path], name: str = "repo") -> Path:
    """The drive's `census_checkout`: the census's own files and this venv's interpreter."""
    repo = _checkout(scratch_repo, name)
    for rel in CENSUS_FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, repo / rel)
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(ROOT / ".venv/bin/python")
    with (repo / ".git/info/exclude").open("a") as exclude:
        exclude.write(".venv/\n__pycache__/\n")
    _commit_all(repo, "census")
    return repo


def _keytree(capture: Callable[..., object], repo: Path) -> str:
    """`loop_key_tree` of the measured tree, from the shell and from `ledger.py`, which agree."""
    rc, out = _sh(capture, repo, 'loop_key_tree "$(gate_measured_tree)" 2>/dev/null')
    shell = out.strip() if rc == 0 else ""
    assert ledger.loop_key_tree(repo, _tree_in(capture, repo)) == shell
    return shell


def _consult(capture: Callable[..., object], repo: Path) -> str:
    rc, _ = _sh(capture, repo, 'loop_ledger_tree_row "$(gate_measured_tree)" >/dev/null 2>&1')
    return "hit" if rc == 0 else "miss"


def _bank(capture: Callable[..., object], repo: Path) -> None:
    rc, out = _sh(
        capture,
        repo,
        f't=$(gate_measured_tree); k=$(loop_ledger_key "$t" "{SCOPE}"); '
        f'loop_ledger_record "$k" "{SCOPE}" 1 "$t" "{_hex64("env")}" >/dev/null',
    )
    assert rc == 0, out


def test_a_prose_path_a_member_reads_by_glob_stays_in_the_key(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _census_checkout(scratch_repo)
    (repo / RUNBOOKS).mkdir(parents=True)
    (repo / RUNBOOKS / "deploy-x.md").write_text("a runbook\n")
    _commit_all(repo, "runbook")
    k0 = _keytree(capture, repo)
    (repo / RUNBOOKS / "deploy-x.md").write_text("a runbook, amended\n")
    _commit_all(repo, "amend")
    assert _keytree(capture, repo) == k0 != ""
    (repo / "scripts/tests").mkdir()
    (repo / "scripts/tests/test_runbooks.sh").write_text(
        f"#!/usr/bin/env bash\n# drives: {RUNBOOKS}/\nexit 0\n"
    )
    _commit_all(repo, "a drive reading the runbooks by directory")
    kk0 = _keytree(capture, repo)
    (repo / RUNBOOKS / "deploy-x.md").write_text("a runbook, amended again\n")
    _commit_all(repo, "amend-again")
    assert _keytree(capture, repo) != kk0
    tree = _tree_in(capture, repo)
    prose = f"{RUNBOOKS}/deploy-x.md\n{RUNBOOKS}-other.md"
    rc, keep = _sh(capture, repo, f'loop_key_keep "{tree}" "{prose}"')
    assert (rc, keep.strip()) == (0, f"{RUNBOOKS}/deploy-x.md")
    assert ledger.loop_key_keep(repo, tree, prose.splitlines()) == [f"{RUNBOOKS}/deploy-x.md"]


def test_a_docs_only_commit_keeps_the_loop_key(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _census_checkout(scratch_repo)
    (repo / CYCLES).mkdir(parents=True)
    (repo / CYCLES / "a-plan.md").write_text("a plan\n")
    _commit_all(repo, "prose")
    t0, k0 = _tree_in(capture, repo), _keytree(capture, repo)
    _bank(capture, repo)
    (repo / CYCLES / "a-plan.md").write_text("a plan, amended\n")
    _commit_all(repo, "amend")
    assert k0 != "" and _keytree(capture, repo) == k0
    assert _tree_in(capture, repo) != t0
    assert _consult(capture, repo) == "hit"
    (repo / "quality/x.py").write_text("X = 1\n")
    _commit_all(repo, "code")
    assert _keytree(capture, repo) != k0
    assert _consult(capture, repo) == "miss"
    (repo / "quality/x.py").write_text(f'PLAN = "{CYCLES}/a-plan.md"\n')
    _commit_all(repo, "quote")
    _bank(capture, repo)
    (repo / CYCLES / "a-plan.md").write_text("a plan, quoted and amended\n")
    _commit_all(repo, "quoted-amend")
    assert _consult(capture, repo) == "miss"


def test_the_docs_only_decider_and_the_key_share_one_census(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _census_checkout(scratch_repo)
    (repo / CYCLES).mkdir(parents=True)
    (repo / CYCLES / "a-plan.md").write_text("a plan\n")
    (repo / "scripts/plan_reader.sh").write_text(f'PLAN="{CYCLES}/a-plan.md"\n')
    _commit_all(repo, "a script quotes the plan")
    rc, hits = _sh(capture, repo, f'gate_docs_only_literal_reads "{CYCLES}/a-plan.md" a-plan.md')
    assert f"scripts/plan_reader.sh:1 {CYCLES}/a-plan.md" in hits, (rc, hits)
    prose = ledger.loop_key_prose(repo, _tree_in(capture, repo))
    assert prose is not None and f"{CYCLES}/a-plan.md" not in prose
    library = SHELL_LIB.read_text()
    assert library.count("quality.loop_key import quotes") == 1
    assert library.count("grep -rnI -F") == 0


def test_a_census_that_cannot_look_refuses_the_key(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _census_checkout(scratch_repo, "no-candidates")
    lib = repo / "scripts/gate_ledger.sh"
    lib.write_text(
        "".join(
            line
            for line in lib.read_text().splitlines(keepends=True)
            if not line.startswith("GATE_DOCS_ONLY_PATHS=")
        )
    )
    tree = _tree_in(capture, repo)
    rc, out = _sh(capture, repo, f'loop_ledger_key "{tree}" "{SCOPE}" 2>/dev/null')
    assert (rc, out) == (2, "")
    rc, out = _sh(capture, repo, f'loop_ledger_key "{tree}" "{SCOPE}" 2>&1 >/dev/null')
    assert "COULD NOT LOOK" in out
    with pytest.raises(ledger.KeyCannot, match="exited 2"):
        ledger.loop_key_tree(repo, tree)
    repo = _census_checkout(scratch_repo, "no-interpreter")
    (repo / ".venv/bin/python").unlink()
    tree = _tree_in(capture, repo)
    rc, out = _sh(capture, repo, f'loop_ledger_key "{tree}" "{SCOPE}" 2>/dev/null')
    assert (rc, out) == (2, "")
    with pytest.raises(ledger.KeyCannot, match="has no interpreter at"):
        ledger.loop_key_tree(repo, tree)


def test_a_key_that_could_not_look_names_its_cause(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _census_checkout(scratch_repo)
    (repo / ".venv/bin/python").unlink()
    rc, out = _sh(
        capture,
        repo,
        f'rc=0; loop_key_derive "$(gate_measured_tree)" "{SCOPE}" 2>/dev/null || rc=$?\n'
        'printf "rc=%s cannot=%s\\n" "$rc" "$LOOP_KEY_CANNOT"',
    )
    assert "rc=2 cannot=quality/loop_key.py has no interpreter at" in out, out
    rc, out = _sh(capture, repo, 'LOOP_KEY_CANNOT="the census exploded"; loop_key_cannot_banner')
    assert "!! COULD NOT LOOK: no loop key — the census exploded" in out
    assert "something moved while the gate ran" not in out


def test_the_prose_cache_evicts_what_outlived_its_bound(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    library = SHELL_LIB.read_text()
    assert f"\nLOOP_KEY_PROSE_MAX_AGE_DAYS={ledger.PROSE_MAX_AGE_DAYS}\n" in library
    assert f"\nLOOP_KEY_PROSE_OWNER='{ledger.PROSE_OWNER}'\n" in library
    assert f"\nDRIVE_MARKER_LINES={ledger.DRIVE_MARKER_LINES}\n" in library
    for side in ("shell", "python"):
        repo = _census_checkout(scratch_repo, side)
        tree = _tree_in(capture, repo)

        def read(side: str = side, repo: Path = repo, tree: str = tree) -> None:
            if side == "shell":
                rc, out = _sh(capture, repo, "loop_key_prose >/dev/null")
                assert rc == 0, out
            else:
                assert ledger.loop_key_prose(repo, tree) is not None

        read()
        cache = Path(_git(repo, "rev-parse", "--absolute-git-dir")) / "djb-loop-key-prose"
        assert (cache / tree).is_file()
        old, fresh = cache / ("0" * 37 + "old"), cache / ("0" * 35 + "fresh")
        old.write_text("stale\n")
        fresh.write_text("fresh\n")
        month = time.time() - 30 * 86400
        os.utime(old, (month, month))
        (cache / tree).unlink()
        read()
        assert (side, old.exists(), fresh.exists()) == (side, False, True)


def test_every_deploy_drive_keys_on_the_one_preamble(
    scratch: Path,
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    env_strip: object,
) -> None:
    """A planted deploy drive keys on scripts/tests/ preamble — the sweep left the tree none."""
    repo = scratch_repo()
    shipped = ("scripts/tests/drive_preamble.sh", "quality/djb/rituals/divergence.py")
    drive = "deploy/tests/test_planted.sh"
    files = {rel: (ROOT / rel).read_text() for rel in shipped}
    files[drive] = "#!/usr/bin/env bash\n# drives: deploy/\nexit 0\n"
    _commit(repo, files)
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    listing = scratch / "deploy-listing"
    listing.write_text(_git(repo, "ls-tree", "-r", tree) + "\n")
    rc, out = _sh(capture, repo, f'drive_key "{drive}" "{tree}" "{listing}" 2>&1 || true')
    assert out.startswith("ok drive-v1:"), out
    assert "scripts/tests/drive_preamble.sh" in ledger.drive_parts(repo, tree, drive)


# end of group D

# --- group E: the commit hook to the sanction -----------------------------------------------------


E_DOCS = "docs"
E_IN_FLIGHT = "docs" + "/product/in-flight.md"
E_ARCHIVE = "docs" + "/product/archive/in-flight-p26.md"
E_NO_POINTER = "carries no `" + "docs" + "/product/reports/<cycle>/<id>.md` pointer"
E_LEDGER_FILES = (
    "scripts/ledger_check.py",
    "scripts/loop_metrics.py",
    "quality/__init__.py",
    "quality/could_not_look.py",
    "quality/loop_key.py",
    "quality/tree.py",
    "apps/core/roads.py",
)
E_LEDGER_LEG = (
    'exit 0\ngate_leg_ledger_check() {\n"$PY" scripts/ledger_check.py --check\n}\n'
    'gate_run_body ledger-check gate_leg_ledger_check static "x"\n'
)
E_ROW_HEAD = (
    "| # | Who | What | State | Sent | Returned | Verdict |\n|---|---|---|---|---|---|---|\n"
)
E_STAMPS = "stamps: sent=2026-10-04 10:00 done=2026-10-04 11:00"
E_SITE = "site-packages"
E_DIST = ".venv/lib/python3.12/" + E_SITE


def _e_append(path: Path, text: str) -> None:
    with path.open("a") as handle:
        handle.write(text)


def _e_hook_checkout(scratch_repo: Callable[..., Path], name: str = "repo") -> Path:
    """The drive's `hook_checkout`: the real pre-commit hook over a stub `--fast`."""
    repo = _checkout(scratch_repo, name)
    for rel in ("scripts/githooks", "apps", E_DOCS):
        (repo / rel).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts/githooks/pre-commit", repo / "scripts/githooks/pre-commit")
    shutil.copy2(SHELL_LIB, repo / "scripts/gate_ledger.sh")
    (repo / "scripts/check.sh").write_text('#!/usr/bin/env bash\necho "FAST RAN $*"\n')
    (repo / "scripts/check.sh").chmod(0o755)
    (repo / "scripts/githooks/pre-commit").chmod(0o755)
    (repo / E_DOCS / "notes.md").write_text("one\n")
    (repo / "apps/thing.py").write_text("x = 1\n")
    _commit_all(repo, "the hook's world")
    return repo


def _e_hook_ledger_checkout(scratch_repo: Callable[..., Path], name: str = "repo") -> Path:
    """The drive's `hook_ledger_checkout`: the hook's world plus the census and the ledger check."""
    repo = _e_hook_checkout(scratch_repo, name)
    for rel in (".venv/bin", "quality", "apps/core", "docs" + "/product/archive"):
        (repo / rel).mkdir(parents=True, exist_ok=True)
    (repo / ".venv/bin/python").symlink_to(ROOT / ".venv/bin/python")
    for rel in E_LEDGER_FILES:
        shutil.copy2(ROOT / rel, repo / rel)
    _e_append(repo / "scripts/check.sh", E_LEDGER_LEG)
    # The layer step stubbed as `--fast` is: this world is not a product's (rule 95's own drive).
    (repo / "quality/djb").mkdir(parents=True, exist_ok=True)
    (repo / "quality/djb/__init__.py").write_text("")
    (repo / "quality/djb/cli.py").write_text('import sys\n\nprint("LAYER RAN", *sys.argv[1:])\n')
    (repo / "apps/__init__.py").write_text("")
    (repo / "apps/core/__init__.py").write_text("")
    (repo / E_ARCHIVE).write_text(f"# a\n\n### s — pruned 2026-10-03 18:55\n\n{E_ROW_HEAD}")
    (repo / E_IN_FLIGHT).write_text(
        f"# x\n\n## Dispatch ledger\n\n{E_ROW_HEAD}"
        "| FX-01 | builder | a thing | sent | 2026-10-04 10:00 | — | — |\n"
    )
    _commit_all(repo, "the ledger's world")
    return repo


def _e_hook(
    capture: Callable[..., object], repo: Path, env: Mapping[str, str] | None = None
) -> tuple[int, str]:
    done = capture(["./scripts/githooks/pre-commit"], cwd=repo, env=env)
    return done.rc, done.path.read_text(errors="replace")  # type: ignore[attr-defined]


def _e_fields(text: str, *columns: int) -> str:
    """awk's `print $a, $b` over `text`, one output line per input line."""
    out = []
    for line in text.splitlines():
        words = line.split()
        out.append(" ".join(words[c - 1] if c <= len(words) else "" for c in columns))
    return "\n".join(out)


def test_the_hook_admits_a_docs_only_commit_and_nothing_else(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _e_hook_ledger_checkout(scratch_repo)
    notes = f"{E_DOCS}/notes.md"
    _e_append(repo / notes, "two\n")
    _git(repo, "add", notes)
    rc, out = _e_hook(capture, repo)
    assert rc == 0, out
    assert "pre-commit: docs-only — 1 staged path(s) on the declared list" in out
    assert out.index("LAYER RAN hook pre-commit") < out.index("pre-commit: docs-only")
    assert "FAST RAN" not in out
    (repo / "apps/thing.py").write_text("x = 2\n")
    _git(repo, "add", "apps/thing.py")
    rc, out = _e_hook(capture, repo)
    assert rc == 0, out
    assert "FAST RAN --fast" in out
    assert "docs-only — " not in out
    _git(repo, "reset", "-q")
    (repo / "apps/README.md").write_text("# readme\n")
    _git(repo, "add", "apps/README.md")
    assert "FAST RAN --fast" in _e_hook(capture, repo)[1]
    _git(repo, "reset", "-q")
    assert "FAST RAN --fast" in _e_hook(capture, repo)[1]
    alt = scratch / "hook-alt-index"
    _e_append(repo / notes, "three\n")
    alt_env = {**os.environ, "GIT_INDEX_FILE": str(alt)}
    for argv in (["read-tree", "HEAD"], ["add", notes, "apps/thing.py"]):
        subprocess.run(["git", *argv], cwd=repo, env=alt_env, check=True, capture_output=True)
    _git(repo, "add", notes)
    rc, out = _e_hook(capture, repo, env={"GIT_INDEX_FILE": str(alt)})
    assert "FAST RAN --fast" in out
    assert "docs-only — " not in out


def test_the_hook_admits_a_clean_ledger_commit_and_says_how_long_it_took(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _e_hook_ledger_checkout(scratch_repo)
    _e_append(
        repo / E_IN_FLIGHT,
        "| FX-02 | builder | b thing | returned | 2026-10-04 10:00 | — | met; "
        "reports/p26/fx-02.md stamps: sent=2026-10-04 10:00 done=2026-10-04 11:00 "
        "met=2026-10-04 12:00 merged=abcdef12 2026-10-04 13:00 |\n",
    )
    _git(repo, "add", E_IN_FLIGHT)
    t0 = time.monotonic()
    rc, out = _e_hook(capture, repo)
    took = time.monotonic() - t0
    assert rc == 0, out
    assert "pre-commit: docs-only — 1 staged path(s)" in out
    assert "== ledger-check: clean" in out
    assert (
        "pre-commit: docs-only admission — 1 commit-measured module(s) run on the staged bytes · "
        in out
    )
    assert "FAST RAN" not in out
    assert took < REAL_TIME_CEILING_S, took  # the bound only catches a hang


def test_the_hook_refuses_a_ledger_commit_the_check_refuses(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _e_hook_ledger_checkout(scratch_repo)
    _e_append(
        repo / E_IN_FLIGHT,
        f"| FX-03 | builder | c thing | returned | 2026-10-04 10:00 | — | met {E_STAMPS} |\n",
    )
    _git(repo, "add", E_IN_FLIGHT)
    rc, out = _e_hook(capture, repo)
    assert rc == 1, out
    assert E_NO_POINTER in out
    assert "scripts/ledger_check.py --check refused the staged bytes (exit 1)" in out
    _git(repo, "reset", "-q")
    _e_append(repo / E_DOCS / "notes.md", "two\n")
    _git(repo, "add", f"{E_DOCS}/notes.md")
    rc, out = _e_hook(capture, repo)
    assert rc == 0, out
    assert "ledger-check" not in out
    assert "pre-commit: docs-only admission — 0 commit-measured module(s) run" in out


def test_the_hook_judges_the_bytes_the_commit_carries(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _e_hook_ledger_checkout(scratch_repo)
    in_flight = repo / E_IN_FLIGHT
    good = in_flight.read_text()
    _e_append(
        in_flight,
        f"| FX-04 | builder | d thing | returned | 2026-10-04 10:00 | — | met {E_STAMPS} |\n",
    )
    _git(repo, "add", E_IN_FLIGHT)
    in_flight.write_text(good)
    rc, out = _e_hook(capture, repo)
    assert rc == 1, out
    assert f"FX-04 ({E_IN_FLIGHT}:8): returned row (state `returned`) {E_NO_POINTER}" in out
    _git(repo, "reset", "-q")
    in_flight.write_text(good)
    _e_append(in_flight, "| FX-07 | builder | g thing | sent | 2026-10-04 10:00 | — | — |\n")
    _git(repo, "add", E_IN_FLIGHT)
    _e_append(in_flight, "| FX-08 | builder | h thing | returned | 2026-10-04 10:00 | — | met |\n")
    rc, out = _e_hook(capture, repo)
    assert rc == 0, out
    assert "== ledger-check: clean" in out
    assert "FX-08" not in out


def test_the_hook_runs_what_the_census_names_and_types_no_path(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _e_hook_ledger_checkout(scratch_repo)
    shape = f"{E_DOCS}/zz-shape.md"
    (repo / "scripts/zz_shape.py").write_text(
        f'"""A planted commit-measured module."""\n\n# measured at the commit: {shape} — planted\n'
        f'import sys\n\nBOOK = "{shape}"\nprint("ZZ SHAPE RAN", sys.argv[1:])\n'
    )
    _e_append(
        repo / "scripts/check.sh",
        'gate_leg_zz_shape() {\n"$PY" scripts/zz_shape.py --check\n}\n'
        'gate_run_body zz-shape gate_leg_zz_shape static "x"\n',
    )
    (repo / shape).write_text("shape\n")
    _git(repo, "add", "scripts/zz_shape.py", "scripts/check.sh")
    _commit_all(repo, "the planted module")
    _e_append(repo / shape, "shape two\n")
    _git(repo, "add", shape)
    rc, out = _e_hook(capture, repo)
    assert rc == 0, out
    assert "ZZ SHAPE RAN ['--check']" in out
    assert "ledger-check" not in out
    assert "1 commit-measured module(s) run on the staged bytes" in out
    _git(repo, "reset", "-q")
    misses = "docs" + "/product/misses.md"
    (repo / misses).write_text("a miss\n")
    _git(repo, "add", misses)
    rc, out = _e_hook(capture, repo)
    assert rc == 0, out
    assert "ZZ SHAPE RAN" not in out
    assert "ledger-check" not in out
    assert "0 commit-measured module(s) run" in out
    (repo / ".venv/bin/python").unlink()
    rc, out = _e_hook(capture, repo)
    assert rc == 2, out
    assert "COULD NOT LOOK — this checkout has no .venv/bin/python for the layer step" in out
    (repo / ".venv/bin/python").symlink_to(ROOT / ".venv/bin/python")
    census = repo / "quality/loop_key.py"
    census.rename(census.with_suffix(".py.away"))
    rc, out = _e_hook(capture, repo)
    assert rc == 2, out
    assert "COULD NOT LOOK — python -m quality.loop_key --measured did not answer" in out
    census.with_suffix(".py.away").rename(census)
    _git(repo, "reset", "-q")
    _e_append(repo / "scripts/zz_shape.py", "raise SystemExit(2)\n")
    _git(repo, "add", "scripts/zz_shape.py")
    _commit_all(repo, "the module cannot look")
    _e_append(repo / shape, "shape three\n")
    _git(repo, "add", shape)
    rc, out = _e_hook(capture, repo)
    assert rc == 2, out
    assert "COULD NOT LOOK — scripts/zz_shape.py --check exited 2 on the staged bytes" in out


def test_the_ledger_pair_leaves_the_key_on_the_real_tree(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    measured = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-m", "quality.loop_key", "--measured"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    live = [w[0] for w in map(str.split, measured.splitlines()) if w[1:2] == [E_LEDGER_FILES[0]]]
    assert live, "the census lists no commit-measured path for scripts/ledger_check.py"
    clone = scratch / "ledger-key-clone"
    subprocess.run(["git", "clone", "-q", "--shared", str(ROOT), str(clone)], check=True)
    (clone / ".venv/bin").mkdir(parents=True)
    (clone / ".venv/bin/python").symlink_to(ROOT / ".venv/bin/python")
    tree = _git(clone, "rev-parse", "HEAD^{tree}")
    rc, keep = _sh(capture, clone, f'loop_key_keep "{tree}" "{chr(10).join(live)}" 2>/dev/null')
    assert (rc, keep) == (0, "")
    assert ledger.loop_key_keep(clone, tree, live) == []
    index_env = {**os.environ, "GIT_INDEX_FILE": str(scratch / "ledger-key-index")}

    def in_index(*argv: str, stdin: str | None = None) -> str:
        return subprocess.run(
            ["git", *argv],
            cwd=clone,
            env=index_env,
            input=stdin,
            text=True,
            check=True,
            capture_output=True,
        ).stdout.strip()

    in_index("read-tree", tree)
    for path in live:
        text = _git(clone, "show", f"HEAD:{path}") + "\n| ZZ-01 | a row only this tree carries |\n"
        blob = in_index("hash-object", "-w", "--stdin", stdin=text)
        in_index("update-index", "--cacheinfo", f"100644,{blob},{path}")
    other = in_index("write-tree")
    assert tree != other
    keys = []
    for subject in (tree, other):
        rc, key = _sh(capture, clone, f'loop_key_tree "{subject}" 2>/dev/null')
        assert rc == 0, key
        keys.append(key.strip())
    assert keys[0] == keys[1]
    assert ledger.loop_key_tree(clone, other) == keys[0]


def test_no_module_quotes_the_ledger_pair_into_the_key() -> None:
    """No undeclared quote of the commit-measured pair: `prose_paths` keeps it out of the key."""
    pair = [p for p, module in loop_key.measured_at_commit(ROOT) if module == E_LEDGER_FILES[0]]
    assert pair, "the census lists no commit-measured path for scripts/ledger_check.py"
    read = loop_key.reads(ROOT)
    assert {p: read[p] for p in pair if p in read} == {}
    assert set(pair) <= set(loop_key.prose_paths(ROOT))


def test_the_measured_tree_skips_a_plant_unlinked_at_its_listing(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    want = _tree_in(capture, repo)
    plant = "zz-vanishing-plant.txt"
    err = scratch / "vanish.err"
    (repo / plant).write_text("a plant\n")
    rc, out = _sh(
        capture,
        repo,
        f"plant={plant}\n"
        "got=$( {\n"
        "    git() {\n"
        '        case " $* " in\n'
        '        (*" add -A "*)\n'
        '            rm -f "$plant"\n'
        "            echo \"fatal: unable to stat '${plant}': No such file or directory\" >&2\n"
        "            return 128\n"
        "            ;;\n"
        "        (*ls-files*-o*)\n"
        '            command git "$@"\n'
        '            rm -f "$plant"\n'
        "            return 0\n"
        "            ;;\n"
        "        esac\n"
        '        command git "$@"\n'
        "    }\n"
        "    gate_measured_tree\n"
        f'}} 2>"{err}") || got=""\n'
        'printf "got=%s\\n" "$got"',
    )
    assert f"got={want}\n" in out, out
    (repo / plant).write_text("a plant\n")
    rc, out = _sh(
        capture,
        repo,
        "rc=0\n"
        "got=$( {\n"
        "    git() {\n"
        '        case " $* " in\n'
        '        (*" add -A "* | *" update-index "*)\n'
        '            echo "fatal: index.lock exists" >&2\n'
        "            return 128\n"
        "            ;;\n"
        "        esac\n"
        '        command git "$@"\n'
        "    }\n"
        "    gate_measured_tree\n"
        f'}} 2>"{err}") || rc=$?\n'
        'printf "rc=%s got=%s\\n" "$rc" "$got"',
    )
    assert "rc=1 got=\n" in out, out
    assert "update-index" in err.read_text(), err.read_text()


def _e_push_world(
    scratch: Path, capture: Callable[..., object], name: str
) -> dict[str, Path | str]:
    """The drive's `push_world`: a checkout, a bare remote, the real pre-push and a stub gate."""
    work, remote = scratch / name / "work", scratch / name / "origin.git"
    (work / "scripts/githooks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(work, "init", "-q")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(work, "config", "user.email", "drive@example.invalid")
    _git(work, "config", "user.name", "pre-push drive")
    _git(work, "config", "commit.gpgsign", "false")
    _git(work, "config", "core.hooksPath", "scripts/githooks")
    _git(work, "remote", "add", "origin", str(remote))
    shutil.copy2(SHELL_LIB, work / "scripts/gate_ledger.sh")
    shutil.copy2(ROOT / "scripts/gate_refuse.sh", work / "scripts/gate_refuse.sh")
    shutil.copy2(ROOT / "scripts/githooks/pre-push", work / "scripts/githooks/pre-push")
    (work / "scripts/githooks/pre-push").chmod(0o755)
    (work / "scripts/check.sh").write_text(PUSH_STUB_GATE)
    (work / "scripts/check.sh").chmod(0o755)
    (work / "README.md").write_text("the measured content\n")
    _hook_packages(work)
    _commit_all(work, "main, and this is the tree the gate measured")
    sha = _git(work, "rev-parse", "HEAD")
    rc, out = _sh(
        capture, work, f'gate_ledger_record "$(git rev-parse "{sha}^{{tree}}")" drive-legs'
    )
    assert rc == 0, out
    return {"work": work, "remote": remote, "sha": sha}


def _e_declaring_world(
    scratch: Path, capture: Callable[..., object], name: str
) -> dict[str, Path | str]:
    """The drive's `push_world_that_declares_a_derived_path`: raw and measured trees differ."""
    world = _e_push_world(scratch, capture, name)
    work = Path(world["work"])
    (work / "scripts/planted_leg.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# A planted leg. It republishes derived/ on every green run, and the\n"
        "# bytes differ per box. Nothing measured reads them back.\n"
        "# >>> derived-tree-paths >>>\n"
        "# derived — the box redraws these bytes on every green run; nothing measured reads them"
        " back\n"
        "# <<< derived-tree-paths <<<\n"
    )
    (work / "derived").mkdir()
    (work / "derived/planted.png").write_text("the accepted look, as this box draws it\n")
    (work / "derived.txt").write_text("measured: yes\n")
    _commit_all(work, "the derived artefact, committed as the real one is")
    world["sha"] = _git(work, "rev-parse", "HEAD")
    world["raw"] = _git(work, "rev-parse", f"{world['sha']}^{{tree}}")
    world["measured"] = _tree_in(capture, work)
    assert world["raw"] != world["measured"], "the planted declaration did not move the key"
    return world


def _e_push(
    capture: Callable[..., object], work: Path, *argv: str, env: Mapping[str, str] | None = None
) -> tuple[int, str]:
    done = capture(["git", "-C", str(work), "push", *argv], cwd=work, env=env)
    return done.rc, done.path.read_text(errors="replace")  # type: ignore[attr-defined]


def test_one_subtraction_site_serves_both_measured_tree_readers(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    rc, out = _sh(capture, ROOT, "command -v gate_measured_tree_of")
    assert rc == 0, "there is no gate_measured_tree_of — a ref can only be read RAW"
    library = SHELL_LIB.read_text().splitlines()
    assert sum("rm -r -f --cached" in line for line in library) == 1
    world = _e_declaring_world(scratch, capture, "push1")
    work = Path(world["work"])
    rc, out = _sh(capture, work, "gate_measured_tree_of HEAD 2>/dev/null")
    assert out.strip() == world["measured"], out
    assert ledger.measured_tree_of(work, "HEAD") == world["measured"]
    assert world["raw"] != world["measured"]
    rc, _ = _sh(
        capture, work, 'gate_measured_tree_of "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef^{tree}"'
    )
    assert rc == 1


def test_a_box_push_of_a_tree_that_declares_a_derived_path_is_exempt(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    world = _e_declaring_world(scratch, capture, "push1")
    probe = scratch / f".vouch-{os.getpid()}" / "probe.git"
    probe.parent.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(probe)], check=True)
    rc, out = _e_push(
        capture,
        Path(world["work"]),
        "--dry-run",
        "--force",
        str(probe),
        "HEAD:refs/heads/main",
        env={"DJB_PUSH_DESTINATION": "verifier-box"},
    )
    assert rc == 0, out
    assert f"pre-push: wall box-exempt {world['measured']}" in out
    assert "REFUSED — the ref being pushed is not the tree in this checkout" not in out
    assert "STUB GATE RAN" not in out


def test_a_banked_measured_verdict_honours_a_push_from_a_declaring_checkout(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    world = _e_declaring_world(scratch, capture, "push1")
    work = Path(world["work"])
    rc, out = _sh(capture, work, f'gate_ledger_record "{world["measured"]}" drive-legs')
    assert rc == 0, out
    rc, out = _e_push(capture, work, "origin", "main")
    assert rc == 0, out
    assert "pre-push: wall honoured" in out
    assert "this checkout measures:" not in out
    assert "STUB GATE RAN" not in out
    assert _git(Path(world["remote"]), "rev-parse", "refs/heads/main") == world["sha"]


def _e_wall_world(scratch: Path, capture: Callable[..., object], name: str) -> tuple[Path, str]:
    """The drive's `wall_world_with_a_declared_leg_set`: a stub gate declaring its legs."""
    work = Path(_e_push_world(scratch, capture, name)["work"])
    (work / "scripts/check.sh").write_text(
        '#!/usr/bin/env bash\nFULL_LEGS=ruff,pytest-x2\necho "STUB GATE RAN"\nexit 0\n'
    )
    _git(work, "add", "scripts/check.sh")
    _git(work, "commit", "-q", "-m", "a stub gate that declares the leg set it would run")
    return work, _git(work, "rev-parse", "HEAD^{tree}")


def _e_full_row(
    capture: Callable[..., object], repo: Path, tree: str, legs: str, extra: str = ""
) -> None:
    rc, path = _sh(capture, repo, "gate_ledger_path 2>/dev/null")
    assert rc == 0, path
    _e_append(
        Path(path.strip()), f"v1 {tree} full 2026-09-16T00:00:00Z {legs} caller=drive{extra}\n"
    )


def test_the_wall_refuses_a_one_pass_row_without_its_proof(
    scratch: Path, capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    proof = " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c"
    missing = "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof"
    work, tree = _e_wall_world(scratch, capture, "push1")
    _e_full_row(capture, work, tree, "ruff,pytest-x2/1", f"{proof} rc=0")
    rc, out = _e_push(capture, work, "origin", "main:refs/heads/wall1")
    assert rc == 0, out
    assert "pre-push: wall honoured" in out
    assert "STUB GATE RAN" not in out
    work, tree = _e_wall_world(scratch, capture, "push2")
    _e_full_row(capture, work, tree, "ruff,pytest-x2/1", f"{proof} rc=1")
    rc, out = _e_push(capture, work, "origin", "main:refs/heads/wall2")
    assert "pre-push: wall measuring" in out
    assert f"{missing} (leak-proof=acceptance:i-0f1e2d3c rc=1)" in out
    assert "STUB GATE RAN" in out
    work, tree = _e_wall_world(scratch, capture, "push3")
    _e_full_row(capture, work, tree, "ruff,pytest-x2/1")
    rc, out = _e_push(capture, work, "origin", "main:refs/heads/wall3")
    assert "pre-push: wall measuring" in out
    assert f"{missing} (leak-proof=none)" in out
    assert "STUB GATE RAN" in out
    work, tree = _e_wall_world(scratch, capture, "push4")
    _e_full_row(capture, work, tree, "ruff,pytest-x2")
    rc, out = _e_push(capture, work, "origin", "main:refs/heads/wall4")
    assert rc == 0, out
    assert "pre-push: wall honoured" in out
    hook = (ROOT / "scripts/githooks/pre-push").read_text()
    assert not any(word in hook for word in ("leak-proof", "--passes", "pytest-x2"))


E_SHIM_TOOLS = (
    "awk sed sort find tr cat cut head git env mktemp rm stat comm grep basename dirname date "
    "uname xargs wc printf ls sh bash perl sha256sum"
).split()
E_SHIM_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin", "/usr/local/bin")


def _e_digest_shim(where: Path) -> Path:
    """The drive's `digest_shim_path`: a whole PATH of symlinks with `sha256sum` and no `shasum`."""
    from quality.could_not_look import CouldNotLook

    where.mkdir(parents=True)
    for name in E_SHIM_TOOLS:
        found = next(
            (Path(d) / name for d in E_SHIM_DIRS if os.access(Path(d) / name, os.X_OK)), None
        )
        if found is not None:
            (where / name).symlink_to(found)
    for name in ("sha256sum", "awk", "sed", "sort", "find", "git", "grep"):
        if not os.access(where / name, os.X_OK):
            raise CouldNotLook(f"the digest shim could not link {name!r}")
    if (where / "shasum").exists():
        raise CouldNotLook("the digest shim linked 'shasum', the one name it exists to withhold")
    return where


def test_the_ledgers_digest_is_the_same_where_only_sha256sum_exists(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    shim = _e_digest_shim(scratch / "shim1")
    rc, _ = _sh(capture, repo, f"env PATH=\"{shim}\" bash -c 'command -v shasum >/dev/null 2>&1'")
    assert rc != 0, "the shim PATH still resolves shasum"
    rc, normal = _sh(capture, repo, "loop_env_fingerprint 2>/dev/null || true")
    rc, shadowed = _sh(
        capture,
        repo,
        f'env PATH="{shim}" bash -c \'. "{SHELL_LIB}" && loop_env_fingerprint\' 2>/dev/null'
        " || true",
    )
    assert re.match(r"[0-9a-f]", normal), normal
    assert shadowed == normal
    subject = scratch / "digest-subject1"
    subject.write_text("one line of it\n")
    rc, plain = _sh(capture, repo, f'sha256_of "{subject}" 2>/dev/null || true')
    refuse = ROOT / "scripts/gate_refuse.sh"
    rc, shimmed = _sh(
        capture,
        repo,
        f'env PATH="{shim}" bash -c \'. "{refuse}" && sha256_of "$1"\' _ "{subject}" 2>/dev/null'
        " || true",
    )
    assert plain.strip() == _hex64("one line of it\n")
    assert shimmed == plain
    empty = scratch / "no-digest-tool1"
    empty.mkdir()
    (empty / "bash").symlink_to(shim / "bash")
    rc, out = _sh(
        capture,
        repo,
        f'rc=0; out="$(env PATH="{empty}" bash -c \'. "{refuse}" && sha256_of "$1"\' _ '
        f'"{subject}" 2>/dev/null)" || rc=$?\nprintf "rc=%s out=[%s]\\n" "$rc" "$out"',
    )
    assert out.strip() == "rc=1 out=[]", out


E_DIGEST_FAMILY = (
    "scripts/gate_ledger.sh",
    "scripts/publish.sh",
    "scripts/docs_legs.sh",
    "scripts/archaeology_lib.sh",
    "scripts/secrets_scan.sh",
)


def test_no_site_in_this_family_spells_a_digest_tool_by_hand() -> None:
    # does-not-cover: a call inside a quoted string is stripped with the remedy text, as the drive's
    offenders = []
    for rel in E_DIGEST_FAMILY:
        if not (ROOT / rel).is_file():
            continue
        for line in (ROOT / rel).read_text().splitlines():
            bare = re.sub(r'"[^"]*"', "", re.sub(r"'[^']*'", "", re.sub(r"#.*", "", line)))
            if re.search(r"shasum|sha256sum", bare):
                offenders.append(rel)
                break
    assert offenders == []
    refuse = (ROOT / "scripts/gate_refuse.sh").read_text().splitlines()
    assert any(re.match(r"sha256_of\(\)", line) for line in refuse)


def _e_moved_script(plant: Path) -> str:
    """The drive's two fingerprints either side of `plant`, then `loop_key_moved` over them."""
    return (
        'LOOP_ENV_FINGERPRINT=""\nLOOP_ENV_COMPONENTS=""\n'
        "loop_env_fingerprint >/dev/null 2>&1 || true\n"
        'start="$LOOP_ENV_FINGERPRINT"; parts0="$LOOP_ENV_COMPONENTS"\n'
        f'mkdir -p "{plant}"\n'
        "loop_env_fingerprint >/dev/null 2>&1 || true\n"
        'end="$LOOP_ENV_FINGERPRINT"; parts1="$LOOP_ENV_COMPONENTS"\n'
        '[ "$start" = "$end" ] && echo "VERDICT same: $start" || echo "VERDICT differ"\n'
        "command -v loop_key_moved >/dev/null\n"
        "echo MOVED-BEGIN\n"
        'loop_key_moved atree "$start" "$parts0" atree "$end" "$parts1" mode=fast 2>&1\n'
    )


def test_a_package_installed_while_the_gate_runs_moves_the_env_half_of_the_key(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    plant = repo / E_DIST / "planted_plugin-1.2.3.dist-info"
    rc, out = _sh(capture, repo, _e_moved_script(plant))
    assert rc == 0, out
    assert "VERDICT differ" in out
    moved = out.split("MOVED-BEGIN\n", 1)[1]
    assert "THE ENVIRONMENT" in moved
    assert re.search(r"^ +dists: ", moved, re.M), moved
    assert "THE TREE" not in moved


def _e_fake_uv(bin_dir: Path, *lines: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "uv").write_text("#!/bin/sh\n" + "".join(f"{line}\n" for line in lines))
    (bin_dir / "uv").chmod(0o755)


def test_the_sync_installs_ahead_of_the_key_so_the_two_ends_agree(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    rc, out = _sh(capture, repo, "command -v loop_env_sync")
    assert rc == 0, "gate_ledger.sh defines no loop_env_sync"
    bin_dir = scratch / "bin1"
    on_path = f'PATH="{bin_dir}:$PATH"\n'
    _e_fake_uv(
        bin_dir,
        '[ "$1" = sync ] || { echo "the sync must be \\`uv sync\\`, got: $*" >&2; exit 64; }',
        'case " $* " in *" --frozen "*) ;; *) echo \'the sync must be --frozen: a bare uv sync '
        "may rewrite uv.lock, a TRACKED file' >&2; exit 65 ;; esac",
        f"mkdir -p '{repo / E_DIST / 'planted_plugin-1.2.3.dist-info'}'",
        "echo 'Installed 1 package in 30ms'",
    )
    rc, synced = _sh(capture, repo, on_path + "loop_env_sync")
    _, ends = _sh(
        capture,
        repo,
        on_path + "start=$(loop_env_fingerprint)\nuv sync --frozen >/dev/null 2>&1 || true\n"
        'end=$(loop_env_fingerprint)\nprintf "START=%s\\nEND=%s\\n" "$start" "$end"',
    )
    assert rc == 0, synced
    start = re.search(r"^START=(.*)$", ends, re.M)
    end = re.search(r"^END=(.*)$", ends, re.M)
    assert start and end and start.group(1) == end.group(1), ends
    assert "Installed 1 package" in synced
    assert re.search(r"uv sync --frozen, [0-9]+s", synced), synced
    _e_fake_uv(bin_dir, "echo 'Contemplated 156 packages in 1ms'")
    _, contemplated = _sh(capture, repo, on_path + "loop_env_sync || true")
    assert "Contemplated 156 packages" in contemplated
    _e_fake_uv(
        bin_dir, "echo 'Uninstalled 1 package in 12ms'", "echo 'Installed 1 package in 30ms'"
    )
    _, uninstalled = _sh(capture, repo, on_path + "loop_env_sync || true")
    assert "UNINSTALLED" in uninstalled
    assert "DJB_LOOP_NO_SYNC=1" in uninstalled
    assert "UNINSTALLED" not in contemplated


def test_a_sync_that_cannot_run_is_printed_and_never_a_refusal(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    rc, out = _sh(capture, repo, "command -v loop_env_sync")
    assert rc == 0, "gate_ledger.sh defines no loop_env_sync"
    rc, out = _sh(capture, repo, "loop_env_sync", env={"DJB_LOOP_NO_SYNC": "1"})
    assert rc == 0, out
    assert "NOT synced" in out
    empty = scratch / "empty-bin"
    empty.mkdir()
    rc, out = _sh(capture, repo, f'PATH="{empty}"\nloop_env_sync')
    assert rc == 0, out
    assert "no `uv` on PATH" in out


def test_a_sync_that_exits_non_zero_is_the_legs_business_and_the_refusal_still_names_dists(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    rc, out = _sh(capture, repo, "command -v loop_env_sync")
    assert rc == 0, "gate_ledger.sh defines no loop_env_sync"
    bin_dir = scratch / "binfail1"
    _e_fake_uv(
        bin_dir,
        f"mkdir -p '{repo / E_DIST / 'half_landed-0.1.dist-info'}'",
        "echo 'Prepared 2 packages in 500ms'",
        "echo 'error: failed to install the second package' >&2",
        "exit 2",
    )
    rc, out = _sh(capture, repo, f'PATH="{bin_dir}:$PATH"\nloop_env_sync')
    assert rc == 0, out
    assert "exited 2" in out
    assert "failed to install the second package" in out
    rc, out = _sh(capture, repo, _e_moved_script(repo / E_DIST / "the_other_half-0.1.dist-info"))
    assert rc == 0, out
    assert "VERDICT differ" in out
    assert re.search(r"^ +dists: ", out.split("MOVED-BEGIN\n", 1)[1], re.M), out


E_RECORDERS = (
    "gate_ledger_record",
    "gate_ledger_intent_record",
    "drive_ledger_record",
    "partition_ledger_record",
    "loop_ledger_record",
    "gate_run_note",
)


def test_every_record_and_lookup_is_a_caller_of_the_one_writer_and_reader(
    env_strip: object,
) -> None:
    library = SHELL_LIB.read_text().splitlines()
    appends, opens, fn = [], [], ""
    readers = ("ledger_rows", "ledger_census", "ledger_migrate")
    for number, line in enumerate(library, 1):
        if re.match(r"[a-z_]+\(\) \{", line):
            fn = line.split()[0].replace("()", "", 1)
        if re.search(r'>>[ ]*"\$path"', line) and fn != "ledger_append":
            appends.append(f"{fn}:{number}")
        if re.search(r'(cat|grep[^|]*|awk[^|]*) "\$path"', line) and fn not in readers:
            opens.append(f"{fn}:{number}")
    assert appends == []
    assert opens == []
    named = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            "djb-(loop|partition)-verdicts|djb-gate-(runs|last-full)|DJB_LOOP_LEDGER",
            "--",
            ":(glob)scripts/*.sh",
            ":(glob)scripts/githooks/*",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert named.returncode in (0, 1), named.stderr
    found = [
        line
        for line in named.stdout.splitlines()
        if not line.startswith("scripts/gate_ledger.sh:")
        and not re.match(r"scripts/verifier_box\.sh:.*cat .git/djb-loop-verdicts", line)
    ]
    assert found == []
    for recorder in E_RECORDERS:
        body: list[str] = []
        for line in library:
            if body or re.match(rf"{recorder}\(\) \{{", line):
                body.append(line)
                if line.startswith("}"):
                    break
        assert any("ledger_append" in line for line in body), recorder


def test_the_retired_stores_are_read_until_the_date_and_migrated_once(
    capture: Callable[..., object], scratch_ledger: Path, env_strip: object
) -> None:
    scratch_ledger.write_text("")
    where = scratch_ledger.parent
    tree = _sha40("retired-stores")
    key = f"loop-v1:{_hex64('retired-loop-key')}"
    (where / "djb-loop-verdicts").write_text(
        f"loop-v1 {key} loop 2026-09-30T00:00:00Z caller=drive scope=s passes=1 tree={tree} env=E\n"
    )
    (where / "djb-gate-runs").write_text(
        f"v1 {tree} 2026-09-30T00:00:01Z killed:pytest-x2 caller=drive\n"
    )
    (where / "djb-gate-last-full").write_text("2026-09-30T00:00:02Z 600 green\n")
    _e_append(
        scratch_ledger,
        f"intent=ci run=pending tree={tree} commit={tree} branch=pm/zzz at=20260930T000003Z "
        "epoch=1790000000 sanction=zzz: an old train cut\n"
        f"v1 {tree} full 2026-09-30T00:00:04Z ruff caller=push-wall sanction=the push wall "
        "(DJB_GATE_CALLER=push-wall) waited=0 took=1\n",
    )

    def read(script: str) -> str:
        return _sh(capture, ROOT, f"{script} 2>/dev/null || true")[1]

    assert _e_fields(read(f'ledger_last loop "{key}"'), 1, 3) == "v1 loop"
    assert _e_fields(read(f'ledger_last run "{tree}"'), 1, 3, 5) == "v1 run state=killed:pytest-x2"
    intent = _e_fields(read(f'ledger_last intent "{tree}"'), 1, 3, 4)
    assert intent == "v1 intent 2026-09-30T00:00:03Z"
    assert read(f'gate_run_lookup "{tree}"').strip() == "killed:pytest-x2"
    until = "DJB_GATE_LEDGER_LEGACY_UNTIL=2000-01-01 bash -c '. scripts/gate_ledger.sh && "
    rc, _ = _sh(capture, ROOT, f'{until}ledger_last loop "$1"\' _ "{key}" >/dev/null 2>&1')
    assert rc == 1
    rc, migrated = _sh(capture, ROOT, "ledger_migrate")
    assert rc == 0, migrated
    for store in ("djb-loop-verdicts", "djb-gate-runs", "djb-gate-last-full"):
        assert not (where / store).exists(), store
    assert "0 tolerated" in migrated
    assert "0 malformed" in migrated
    before = scratch_ledger.read_text()
    rc, _ = _sh(capture, ROOT, f"{until}ledger_census' >/dev/null 2>&1")
    assert rc == 0
    assert _e_fields(read(f'ledger_last loop "{key}"'), 3) == "loop"
    assert (
        read(f'ledger_last full "{tree}"')
        .rstrip("\n")
        .endswith(
            " sanction=push-wall:legacy:the%20push%20wall%20(DJB_GATE_CALLER=push-wall) waited=0"
            " took=1"
        )
    )
    rc, again = _sh(capture, ROOT, "ledger_migrate")
    assert rc == 0, again
    assert scratch_ledger.read_text() == before


def test_a_docs_only_subject_that_lies_is_named_by_the_claims_reader(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = _checkout(scratch_repo)
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"docs" + "/a-planted-page.txt": "a page\n"}, "ledger: a page [docs-only]")
    honest = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"apps/x/models.py": "x = 1\n"}, "a model, quietly [docs-only]")
    lie = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"apps/x/models.py": "x = 1\ny = 1\n"}, "a model, said plainly")
    rc, out = _sh(capture, repo, f'gate_docs_only_claims HEAD "{base}"')
    assert (rc, out.strip()) == (0, f"{lie} apps/x/models.py")
    assert honest not in out
    assert ledger.docs_only_claims(repo, "HEAD", base) == [(lie, "apps/x/models.py")]
    assert ledger.docs_only_claims(repo, "HEAD") == [(lie, "apps/x/models.py")]


# end of group E


# --- group F: the writer's surface — the full row, the readers, the durations ---------------------

F_TREE = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret
F_SANCTION = ledger.Sanction("typed", "gate-rung", "quality/** rung — the canary self-test")
F_GATE = "FULL_LEGS=ruff,mypy,pytest-x2\n"


def _f_lines(path: Path) -> int:
    return len(path.read_text().splitlines()) if path.exists() else 0


@pytest.mark.parametrize("caller", ("pr", "leg", "shard", "store-durations"))
def test_no_row_is_written_by_pr_leg_shard_or_store_durations(
    scratch_ledger: Path, caller: str
) -> None:
    scratch_ledger.write_text(ROWS[0] + "\n")
    fields = ["ruff", f"caller={caller}", F_SANCTION.field()]
    with pytest.raises(ledger.Refused, match=f"caller '{caller}'.*nothing recorded"):
        ledger.append("full", F_TREE, fields, path=scratch_ledger)
    assert _f_lines(scratch_ledger) == 1
    with pytest.raises(ledger.Refused, match=f"caller '{caller}'"):
        ledger.append("full", F_TREE, fields[::2], path=scratch_ledger, caller=caller)
    with pytest.raises(ledger.Refused, match=f"caller '{caller}'"):
        ledger.record_full(
            scratch_ledger.parent,
            tree=F_TREE,
            legs="ruff",
            caller=caller,
            sanction=F_SANCTION,
            path=scratch_ledger,
        )
    assert _f_lines(scratch_ledger) == 1


def test_a_full_row_with_no_sanction_is_refused(scratch_ledger: Path) -> None:
    scratch_ledger.write_text(ROWS[0] + "\n")
    with pytest.raises(ledger.Refused, match="no sanction= — a full row carries one, always"):
        ledger.append("full", F_TREE, ["ruff", "caller=push-wall"], path=scratch_ledger)
    assert _f_lines(scratch_ledger) == 1


def test_a_full_row_with_a_sanction_is_written(scratch_ledger: Path) -> None:
    row = ledger.append(
        "full", F_TREE, ["ruff", "caller=pm-bank", F_SANCTION.field()], path=scratch_ledger
    )
    assert ledger.last(scratch_ledger, "full", F_TREE) == row


def test_record_full_writes_the_row_the_shell_writes(
    capture: Callable[..., object],
    scratch_repo: Callable[..., Path],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = scratch_repo()
    ledger.record_full(
        repo,
        tree=F_TREE,
        legs="ruff,mypy",
        caller="quality-rung",
        sanction=F_SANCTION,
        waited=12,
        took=613,
        stamp=STAMP,
    )
    ledger.record_full(
        repo,
        tree=F_TREE,
        legs="ruff",
        caller="whoever",
        sanction=F_SANCTION,
        wall=99,
        proof="ci:7 rc=0",
        stamp=STAMP,
    )
    rc, out = _sh(
        capture,
        repo,
        f'gate_sanction_set typed gate-rung "{F_SANCTION.reason}"\n'
        "GATE_LEASE_WAITED=7 GATE_SLOT_WAITED=5 GATE_PYTEST_TOOK=613\n"
        f"LEDGER_STAMP={STAMP} DJB_GATE_CALLER=quality-rung gate_ledger_record {F_TREE} ruff,mypy\n"
        "GATE_LEASE_WAITED=0 GATE_SLOT_WAITED=0 GATE_PYTEST_TOOK=0 GATE_RUN_ARMED=1\n"
        "GATE_RUN_T0=$(( $(date +%s) - 99 )) GATE_RUN_LEAK_PROOF='ci:7 rc=0'\n"
        f"LEDGER_STAMP={STAMP} DJB_GATE_CALLER=whoever gate_ledger_record {F_TREE} ruff"
        " 2>/dev/null\n",
    )
    assert rc == 0, out
    lines = [
        re.sub(r" wall=(99|100) ", " wall=W ", x) for x in scratch_ledger.read_text().splitlines()
    ]
    assert len(lines) == 4
    assert lines[0] == lines[2] and lines[1] == lines[3], lines
    assert " wall=99 " in scratch_ledger.read_text().splitlines()[1]


def _f_repo(scratch_repo: Callable[..., Path], gate: str = F_GATE) -> Path:
    repo = scratch_repo()
    (repo / "scripts").mkdir()
    (repo / "scripts/check.sh").write_text(gate)
    return repo


F_CONSULT_ROWS = (
    ("covered", "ruff,mypy,pytest-x2", ""),
    ("one-pass-proved", "ruff,mypy,pytest-x2/1", " leak-proof=ci:9 rc=0"),
    ("one-pass-bare", "ruff,mypy,pytest-x2/1", ""),
    ("one-pass-elsewhere", "ruff/1,mypy,pytest-x2", ""),
    ("short", "ruff,mypy", ""),
    ("sharded", "ruff,mypy,pytest-x2/2", ""),
    (
        "nightly-red",
        "ruff,mypy,pytest-x2/1",
        " leak-proof=nightly:20261005T000000Z tree=abcdefabcdef rc=1",
    ),
    ("proof-unused", "ruff,mypy,pytest-x2", " leak-proof=ci:9 rc=0"),
)


@pytest.mark.parametrize(("name", "legs", "proof"), F_CONSULT_ROWS)
def test_consult_answers_what_gate_has_green_answers(
    capture: Callable[..., object],
    scratch_repo: Callable[..., Path],
    scratch_ledger: Path,
    env_strip: object,
    name: str,
    legs: str,
    proof: str,
) -> None:
    repo = _f_repo(scratch_repo)
    tree = _sha40(name)
    scratch_ledger.write_text(
        f"v1 {tree} full {STAMP} {legs} caller=pm-bank {F_SANCTION.field()} waited=0"
        f" took=0{proof}\n"
    )
    said: list[str] = []
    row = ledger.consult(repo, tree, say=said.append)
    rc, out = _sh(capture, repo, f'gate_ledger_lookup {tree} 2>"{scratch_ledger}.err" || exit 7')
    shell_said = Path(f"{scratch_ledger}.err").read_text().splitlines()
    assert (row is not None, said) == (rc == 0, shell_said), out
    if row is not None:
        assert ledger.format(row) == out.strip()


def test_consult_takes_the_last_row_and_none_without_a_ledger(
    scratch_repo: Callable[..., Path], scratch_ledger: Path
) -> None:
    repo = scratch_repo()
    assert ledger.consult(repo, F_TREE) is None
    scratch_ledger.write_text(
        f"v1 {F_TREE} full {STAMP} ruff caller=pm-bank {F_SANCTION.field()} took=1\n"
        f"v1 {F_TREE} full {STAMP} ruff caller=pm-bank {F_SANCTION.field()} took=2\n"
    )
    row = ledger.consult(repo, F_TREE)
    assert row is not None and row.get("took") == "2"


def test_consult_cannot_look_at_an_unreadable_ledger(
    scratch_repo: Callable[..., Path], scratch_ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = scratch_repo()
    scratch_ledger.mkdir()
    with pytest.raises(ledger.Unreadable):
        ledger.consult(repo, F_TREE)
    monkeypatch.setenv("DJB_GATE_LEDGER", "relative/verdicts")
    with pytest.raises(ledger.Unreadable, match="is relative"):
        ledger.consult(repo, F_TREE)


def test_measured_tree_equals_gate_measured_tree_on_a_dirty_tree(
    capture: Callable[..., object], scratch_repo: Callable[..., Path], env_strip: object
) -> None:
    repo = scratch_repo()
    (repo / "kept.txt").write_text("one\n")
    _commit_all(repo, "kept")
    assert ledger.measured_tree(repo) == _git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "kept.txt").write_text("two\n")
    (repo / "untracked.txt").write_text("new\n")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "ignored.txt").write_text("never\n")
    assert ledger.measured_tree(repo) == _tree_in(capture, repo)
    assert _git(repo, "status", "--porcelain")  # the real index is untouched
    assert "untracked.txt" not in _git(repo, "diff", "--cached", "--name-only")


def test_a_derived_tree_paths_declaration_moves_the_key(
    capture: Callable[..., object], scratch_repo: Callable[..., Path], env_strip: object
) -> None:
    repo = scratch_repo()
    (repo / "scripts").mkdir()
    (repo / "scripts/leg.sh").write_text(
        f"# {ledger.TREE_DECL_BEGIN}\n# out/made.json — the leg writes it\n"
        f"# {ledger.TREE_DECL_END}\n"
    )
    (repo / "out").mkdir()
    (repo / "out/made.json").write_text("{}\n")
    _commit_all(repo, "a declaring leg")
    head = _git(repo, "rev-parse", "HEAD^{tree}")
    working = ledger.measured_tree(repo)
    assert working != head
    assert working == ledger.measured_tree_of(repo, "HEAD") == _tree_in(capture, repo)


def test_the_memo_and_the_ledger_key_on_one_population() -> None:
    text = (ROOT / "quality/djb/ledger.py").read_text()
    assert text.count("def _subtract_and_write") == 1
    assert text.count("return _subtract_and_write(root, env, ") == 2


def test_an_intent_row_round_trips_with_the_shell(
    capture: Callable[..., object],
    scratch_repo: Callable[..., Path],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = scratch_repo()
    tree, commit = _sha40("intent-tree"), _sha40("intent-commit")
    who = "TRAIN-X: the PR's CI run is the one measurement"
    row = ledger.intent_record(repo, tree=tree, commit=commit, branch="pm/x", sanction=who)
    rc, out = _sh(capture, repo, f"gate_ledger_intent_lookup {tree}")
    assert (rc, out.strip()) == (0, ledger.format(row))
    assert ledger.intent_lookup(repo, tree) == row
    for branch in ("main", "pm/", "pm/a b"):
        with pytest.raises(ledger.Refused):
            ledger.intent_record(repo, tree=tree, commit=commit, branch=branch, sanction=who)
    old = int(row.get("epoch") or 0) - 901
    said: list[str] = []
    assert ledger.intent_lookup(repo, tree, now=old + 901 + 901, say=said.append) is None
    assert said and "not honoured" in said[0]
    assert ledger.intent_lookup(repo, _sha40("nothing")) is None


def test_the_run_log_round_trips_with_the_shell(
    capture: Callable[..., object],
    scratch_repo: Callable[..., Path],
    scratch_ledger: Path,
    env_strip: object,
) -> None:
    repo = scratch_repo()
    ledger.run_note(repo, F_TREE, "red:pytest-x2", caller="pm-bank", wall=42)
    rc, out = _sh(capture, repo, f"gate_run_lookup {F_TREE}; ledger_last run {F_TREE}")
    assert rc == 0, out
    state, line = out.strip().splitlines()
    assert state == ledger.run_lookup(repo, F_TREE) == "red:pytest-x2"
    assert line.endswith(" state=red:pytest-x2 caller=pm-bank wall=42")
    retired = scratch_ledger.parent / "djb-gate-runs"
    other = _sha40("legacy")
    retired.write_text(f"v1 {other} 2026-08-20T10:00:00Z killed:pytest-x2 caller=push-wall\n")
    rc, out = _sh(capture, repo, f"gate_run_lookup {other}")
    assert out.strip() == ledger.run_lookup(repo, other) == "killed:pytest-x2"
    ledger.append(
        "full",
        F_TREE,
        ["ruff", "caller=pm-bank", F_SANCTION.field(), "wall=77"],
        path=scratch_ledger,
    )
    assert ledger.last_wall(repo) == 77


F_CI_COMMIT = "a" * 40
F_CI_TREE = "b" * 40


def test_ci_record_is_the_shells_line(capture: Callable[..., object]) -> None:
    at = "20261005T120000Z"
    args = (F_CI_COMMIT, F_CI_TREE, "static,pytest-x2/1", "3", "whole", "0", CI_RUN_FIXTURE, "1")
    rc, out = _sh(
        capture, ROOT, "gate_ci_record_line " + " ".join(f'"{a}"' for a in args) + f" {at}"
    )
    assert (rc, out.strip()) == (0, ledger.ci_record(*args, at=at))
    rec = ledger.ci_parse(out.strip())
    assert (rec.commit, rec.tree, rec.run, rec.legs) == (
        F_CI_COMMIT,
        F_CI_TREE,
        CI_RUN_FIXTURE,
        args[2],
    )


F_CI_GOOD = (
    "schema=gate-verdict/1 at=20261005T120000Z commit={c} tree={t} legs=a shards=1 scope=whole"
    " rc=0 run=1 attempt=1 where=ci"
)


@pytest.mark.parametrize(
    ("good", "bad"),
    [
        ("", ""),
        ("", "schema=gate-verdict/1  at=x"),
        ("schema=gate-verdict/1", "schema=gate-verdict/2"),
        ("at=20261005T120000Z", "at=20261305T120000Z"),
        ("commit={c}", "commit=abc"),
        ("legs=a ", "legs=a,,b "),
        ("shards=1", "shards=01"),
        ("scope=whole", "scope=some"),
        ("rc=0", "rc=00"),
        ("run=1", "run=0"),
        ("attempt=1", "attempt=x"),
        ("where=ci", "where=box"),
        ("schema=gate-verdict/1 at=20261005T120000Z", "at=20261005T120000Z schema=gate-verdict/1"),
    ],
)
def test_ci_parse_refuses_what_the_shell_refuses_with_its_reason(
    capture: Callable[..., object], good: str, bad: str
) -> None:
    line = F_CI_GOOD.replace(good, bad, 1) if good else bad
    line = line.format(c=F_CI_COMMIT, t=F_CI_TREE)
    rc, out = _sh(
        capture, ROOT, f"gate_ci_record_parse '{line}' || {{ echo \"$GATE_CI_REC_WHY\"; exit 2; }}"
    )
    with pytest.raises(ledger.Refused) as refused:
        ledger.ci_parse(line)
    assert (rc, out.strip()) == (2, str(refused.value))


def test_a_record_carries_its_lane_last_and_a_laneless_record_is_unchanged() -> None:
    """MQ1.4: `lane=<word>` rides as the twelfth field; the eleven-field line is untouched."""
    args = (F_CI_COMMIT, F_CI_TREE, "static,pytest-x2/1", "3", "pr", "0", CI_RUN_FIXTURE, "1")
    at = "20261010T120000Z"
    bare = ledger.ci_record(*args, at=at)
    assert len(bare.split(" ")) == 11 and ledger.ci_parse(bare).lane == ""
    for word in ("docs", "loop", "full"):
        line = ledger.ci_record(*args, at=at, lane=word)
        assert line == f"{bare} lane={word}"
        assert ledger.ci_parse(line).lane == word
    for bad in ("fast", "", "whole", "loop,full"):
        with pytest.raises(ledger.Refused, match="lane="):
            ledger.ci_parse(f"{bare} lane={bad}")
    with pytest.raises(ledger.Refused, match="field 12"):
        ledger.ci_parse(f"{bare} rc=0")


def test_a_record_carries_its_selftest_word_after_the_lane_and_a_pre_field_record_parses() -> None:
    """`selftest=ran|withheld` rides thirteenth, only after a lane; a record without it is ran."""
    args = (F_CI_COMMIT, F_CI_TREE, "static,pytest-x2/1", "3", "whole", "0", CI_RUN_FIXTURE, "1")
    at = "20261021T120000Z"
    laned = ledger.ci_record(*args, at=at, lane="full")
    assert ledger.ci_parse(laned).selftest == ""
    for word in ("ran", "withheld"):
        line = ledger.ci_record(*args, at=at, lane="full", selftest=word)
        assert line == f"{laned} selftest={word}"
        assert ledger.ci_parse(line).selftest == word
        assert ledger.ci_parse(line).lane == "full"
    for bad in ("skipped", "", "ran,withheld"):
        with pytest.raises(ledger.Refused, match="selftest="):
            ledger.ci_parse(f"{laned} selftest={bad}")
    with pytest.raises(ledger.Refused, match="field 13"):
        ledger.ci_parse(f"{laned} rc=0")
    with pytest.raises(ledger.Refused):
        ledger.ci_record(*args, at=at, selftest="withheld")


def test_a_narrowed_pytest_record_round_trips_and_a_pre_field_record_parses() -> None:
    """CI-THIRD-3 3.4: `pytest=` rides fourteenth, after the selftest word; absent is whole."""
    at = ledger.ci_stamp(int(time.time()))
    args = (F_CI_COMMIT, F_CI_TREE, "static", "3", "whole", "0", CI_RUN_FIXTURE, "1")
    line = ledger.ci_record(*args, at=at, lane="full", selftest="ran", pytest="narrowed")
    assert line.endswith(" lane=full selftest=ran pytest=narrowed"), line
    rec = ledger.ci_parse(line)
    assert (rec.selftest, rec.pytest) == ("ran", "narrowed")
    before = ledger.ci_record(*args, at=at, lane="full", selftest="ran")
    assert ledger.ci_parse(before).pytest == ""
    for bad in ("skipped", ""):
        with pytest.raises(ledger.Refused):
            ledger.ci_record(*args, at=at, lane="full", selftest="ran", pytest=bad)
    with pytest.raises(ledger.Refused, match="field 13"):
        ledger.ci_record(*args, at=at, lane="full", pytest="narrowed")


@pytest.mark.parametrize("word", ["loop", "docs"])
def test_the_judge_refuses_a_loop_or_docs_record_offered_as_full(word: str) -> None:
    """MQ1.4: only the full lane vouches for a tree, whatever its scope field says."""
    at = ledger.ci_stamp(int(time.time()))
    fields = (F_CI_COMMIT, F_CI_TREE, "static", "3", "whole", "0", CI_RUN_FIXTURE, "1")
    line = ledger.ci_record(*fields, at=at, lane=word)
    with pytest.raises(ledger.Refused) as refused:
        ledger.ci_judge(ROOT, line, CI_RUN_FIXTURE, "1", "")
    assert f"ran the {word} lane" in str(refused.value)
    for honest in (ledger.ci_record(*fields, at=at, lane="full"), ledger.ci_record(*fields, at=at)):
        with pytest.raises(ledger.Refused) as later:
            ledger.ci_judge(ROOT, honest, CI_RUN_FIXTURE, "1", "")
        assert "lane" not in str(later.value), "a full or lane-less record passes the lane"


PROOF_GH = """#!/usr/bin/env bash
case "$1 ${2:-}" in
"api "*) printf '%s\\n' 3 2 1; exit 0 ;;
"run download")
    run=$3 dir=""
    while [ "$#" -gt 0 ]; do case "$1" in --dir) dir=$2; shift 2 ;; *) shift ;; esac; done
    [ -f "__RECORDS__/$run" ] || { echo "no artifact matches" >&2; exit 1; }
    mkdir -p "$dir"; cp "__RECORDS__/$run" "$dir/proof_from_zero.txt"; exit 0 ;;
esac
exit 1
"""


def _proof_record(source: str, tree: str, rc: str = "0") -> str:
    fields = ["20261021T070000Z", source, tree, "3", "loop,loop,loop", "0,0,0", "1,1,1"]
    fields += ["201,233,250", "3", "1", "2.5.0", "green", "0", "3", "agree,agree,agree", "-"]
    return ledger.proof_line([*fields, rc, "777", "ci"]) + "\n"


def test_proof_consult_honours_the_tree_it_already_proved(
    scratch_repo: Callable[..., Path], tmp_path: Path
) -> None:
    """The nightly proves only a source tree no run proved green; a red or other source proves."""
    repo = scratch_repo()
    tree = _commit(repo, {"a.txt": "a\n"})
    sha = _git(repo, "rev-parse", "HEAD")
    records, bin_ = tmp_path / "records", tmp_path / "bin"
    records.mkdir()
    bin_.mkdir()
    (bin_ / "gh").write_text(PROOF_GH.replace("__RECORDS__", str(records)))
    (bin_ / "gh").chmod(0o755)
    gh = str(bin_ / "gh")
    export = "e" * 40
    (records / "3").write_text(_proof_record(sha, export, rc="1"))
    (records / "2").write_text(_proof_record("b" * 40, export))
    line, run = ledger.proof_consult_source(repo, sha, gh=gh)
    assert (run, line.startswith("proof-consult: prove — no completed run")) == ("", True), line
    (records / "1").write_text(_proof_record(sha, export))
    line, run = ledger.proof_consult_source(repo, sha, gh=gh)
    assert (line, run, tree != export) == (
        f"proof-consult: honoured run=1 tree={export}",
        "1",
        True,
    )
    assert ledger.proof_consult_source(repo, "not-a-sha", gh=gh)[0].endswith("got 'not-a-sha')")


#: The system directories a world's PATH is built from.
SYSTEM_DIRS = ("/usr/bin", "/bin")


def _path_without(home: Path, tool: str, dirs: tuple[str, ...] = SYSTEM_DIRS) -> str:
    """A PATH of one directory linking every system tool but `tool`: the world has no `tool`."""
    home.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        for entry in sorted(Path(d).iterdir()) if Path(d).is_dir() else []:
            link = home / entry.name
            if entry.name != tool and not link.exists() and not link.is_symlink():
                link.symlink_to(entry)
    return str(home)


def test_ci_consult_cannot_look_without_gh_or_a_sha(
    capture: Callable[..., object], scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = scratch / "runner-bin"
    runner.mkdir()
    (runner / "gh").write_text("#!/bin/sh\nexit 0\n")
    (runner / "gh").chmod(0o755)
    bare = _path_without(scratch / "no-gh", "gh", (str(runner), *SYSTEM_DIRS))
    assert shutil.which("gh", path=bare) is None
    rc, out = _sh(capture, ROOT, f'gate_ci_consult "{F_CI_COMMIT}"', env={"PATH": bare})
    monkeypatch.setenv("PATH", bare)
    assert ledger.ci_consult(ROOT, F_CI_COMMIT) == (out.strip(), "")
    monkeypatch.undo()
    rc, out = _sh(capture, ROOT, "gate_ci_consult nope")
    assert ledger.ci_consult(ROOT, "nope") == (out.strip(), "")


@pytest.mark.parametrize("machine", ["box", "darwin", "ubuntu-latest"])
@pytest.mark.parametrize("only", [False, True])
def test_durations_equal_the_shells_walls_view(
    capture: Callable[..., object], machine: str, only: bool
) -> None:
    rc, out = _sh(capture, ROOT, f"gate_member_walls_view {machine} {'only' if only else '-'}")
    import json

    view = json.loads(out) if rc == 0 else {"members": {}}
    assert ledger.durations(ROOT, machine, only=only) == view["members"]


def test_the_shard_count_is_unchanged_when_the_ledger_reader_feeds_it() -> None:
    from quality.djb import registry

    listed = registry.list_legs(registry.load(ROOT), ci=True, root=ROOT)
    selftest = next(r.split("\t") for r in listed.splitlines() if r.startswith("selftest\t"))
    members = selftest[3].split(",")
    walls = ledger.durations(ROOT, registry.CI_MACHINE, only=True)
    population = [registry.ENGINE_MEMBER, *(m for m in members if m != "selftest")]
    table = registry.load(ROOT)
    homes = [ROOT / h for h in registry.WALLS_HOMES]
    parts = registry.member_parts(homes, registry.CI_MACHINE, table.units(ROOT))
    assert str(registry.shard_count(walls, population, table.pieces(), parts)) == selftest[2]
    golden = ROOT / "quality/tests/golden/list_legs_ci.tsv"
    if golden.is_file():
        assert listed == golden.read_text()


def test_store_durations_writes_the_shells_bytes(
    capture: Callable[..., object], scratch: Path
) -> None:
    py, sh = scratch / "py.json", scratch / "sh.json"
    walls, ats = ledger._walls_read([ROOT / ledger.WALLS_TEMPLATE], print)
    for home in (py, sh):
        ledger._walls_write(home, walls, ats, rules=({}, {}), modules=({}, {}))
    ledger.store_durations(py, "darwin", "tree:abc", {"ruff": 3, "a-new-member": 9})
    rc, out = _sh(
        capture,
        ROOT,
        f"printf 'ruff\\t3\\na-new-member\\t9\\n' | gate_member_walls_write '{sh}' darwin tree:abc",
    )
    assert rc == 0, out
    assert py.read_bytes() == sh.read_bytes()
    ledger.store_duration(py, "ruff", 5, "box")
    assert ledger.durations(scratch, "box", only=True, homes=[py]) == {"ruff": 5}
    assert ledger.durations(scratch, "darwin", homes=[py])["a-new-member"] == 9
    kept = scratch / "kept.json"
    shutil.copy2(ROOT / ledger.WALLS_TEMPLATE, kept)
    before = ledger.module_durations([kept], "darwin")
    ledger.store_durations(kept, "darwin", "tree:abc", {"ruff": 3})
    assert ledger.module_durations([kept], "darwin") == before, "a member write keeps the modules"


def test_ledger_path_reads_through_env_read(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJB_GATE_LEDGER", str(scratch / "named"))
    assert ledger.ledger_path(scratch) == scratch / "named"
    text = (ROOT / "quality/djb/ledger.py").read_text()
    assert "os.environ.get" not in text and "environ.get(" not in text
    assert 'djb_env.read("DJB_GATE_LEDGER")' in text


# --- group G: the bank arm — the one fold every bank door runs before it measures ----------------

NO_FOLD_NOTICE = (
    "pm_push --bank: ** --no-fold — THE DERIVED FILES WERE NOT REGENERATED. **\n"
    "  The contract, the secret baseline and the budget floors are whatever is committed.\n"
    "  If the gate reddens on a stale client or a budget, that is THIS FLAG and not the tree.\n"
)


def _fold(repo: Path, body: str | None) -> None:
    """`scripts/pm_fold.sh` in `repo`: an executable `body`, or absent when None."""
    fold = repo / "scripts/pm_fold.sh"
    fold.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        fold.unlink(missing_ok=True)
        return
    fold.write_text(f"#!/bin/sh\n{body}\n")
    fold.chmod(0o755)


def test_the_push_door_s_bank_arm_prints_the_no_fold_notice_or_folds(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    nothing = "Nothing was banked, nothing was pinned and nothing was pushed."
    _fold(scratch, "echo folded; exit 0")
    assert ledger.bank_arm(scratch, who="pm_push --bank", no_fold=True, nothing=nothing) == 0
    out, err = capfd.readouterr()
    assert (out, err) == (NO_FOLD_NOTICE, "")
    assert ledger.bank_arm(scratch, who="pm_push --bank", no_fold=False, nothing=nothing) == 0
    out, err = capfd.readouterr()
    fold = scratch / "scripts/pm_fold.sh"
    assert out == (
        f"pm_push --bank: folding {scratch} before the gate — {fold}\n"
        "  It regenerates the derived files and commits AT MOST the paths on its own typed list;\n"
        "  anything it modifies outside that list is its own exit 2, with nothing committed.\n"
        "folded\n"
    )
    assert err == ""


def test_the_merge_door_s_bank_arm_refuses_a_missing_or_failing_fold_naming_what_it_did_not_do(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    nothing = "THE MERGE ABOVE IS ALREADY MADE and the gate did not run."
    fold = scratch / "scripts/pm_fold.sh"
    _fold(scratch, None)
    assert ledger.bank_arm(scratch, who="pm_merge", no_fold=False, nothing=nothing) == 2
    out, err = capfd.readouterr()
    assert out == ""
    assert err == (
        f"!! pm_merge: no executable fold at {fold} — pass --no-fold to go without one.\n"
        f"   {nothing}\n"
    )
    _fold(scratch, "echo 'pm_fold: the tree is dirty' >&2; exit 2")
    assert ledger.bank_arm(scratch, who="pm_merge", no_fold=False, nothing=nothing) == 2
    out, err = capfd.readouterr()
    assert out.startswith(f"pm_merge: folding {scratch} before the gate — {fold}\n")
    assert err == (
        "pm_fold: the tree is dirty\n"
        "pm_merge: THE FOLD EXITED 2 — 2 is could-not-fold (a dirty tree, a generator that failed,"
        " a file\n"
        "   modified outside the derived list); its output above names which.\n"
        f"   {nothing}\n"
    )
    _fold(scratch, "exit 1")
    assert ledger.bank_arm(scratch, who="pm_merge", no_fold=False, nothing=nothing) == 1
    assert "THE FOLD EXITED 1 — " in capfd.readouterr().err


#: Where the gate's own code lives: the engine, its legs and rituals, and the shell libraries.
GATE_CODE = ("quality/djb/**/*.py", "scripts/*.sh")
#: The product's unmeasured drawer (`docs/product/build-contract.md`, product-owned, never shipped).
LOCAL_DRAWER = "docs/product/local"


#: The two readers' acceptance lines: each names the drawer to EXCLUDE it, and reads nothing.
NAMING_SITES = ("R0_DRAWER = ", "docs/product/local/*) tracked=1")


def drawer_readers(root: Path) -> list[str]:
    """`<file>:<line>` for each code line under `GATE_CODE` spelling the local drawer's path."""
    found = []
    for pattern in GATE_CODE:
        for path in sorted(root.glob(pattern)):
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                code = line.lstrip()
                if LOCAL_DRAWER in line and not code.startswith(("#", "*", *NAMING_SITES)):
                    found.append(f"{path.relative_to(root).as_posix()}:{n}")
    return found


def test_no_leg_reads_the_local_drawer(tmp_path: Path) -> None:
    assert drawer_readers(ROOT) == []
    named = [
        n
        for n in NAMING_SITES
        if not any(
            n in p.read_text()
            for p in (ROOT / "quality/djb/ledger.py", ROOT / "scripts/gate_ledger.sh")
        )
    ]
    assert named == [], "a naming site this census excuses is gone; drop it from NAMING_SITES"
    leg = tmp_path / "quality/djb/legs/planted.py"
    leg.parent.mkdir(parents=True)
    leg.write_text(f'# {LOCAL_DRAWER} — a comment reads nothing\nopen("{LOCAL_DRAWER}/x.md")\n')
    shell = tmp_path / "scripts/planted.sh"
    shell.parent.mkdir()
    shell.write_text(f"cat {LOCAL_DRAWER}/clock.md\n")
    assert drawer_readers(tmp_path) == ["quality/djb/legs/planted.py:2", "scripts/planted.sh:1"]


def _drawer_checkout(scratch_repo: Callable[..., Path]) -> Path:
    """A checkout carrying this tree's `gate_ledger.sh`, and with it every declaration it makes."""
    repo = _checkout(scratch_repo, "drawer")
    shutil.copy2(ROOT / "scripts/gate_ledger.sh", repo / "scripts/gate_ledger.sh")
    (repo / "docs/product").mkdir(parents=True)
    (repo / "docs/product/queue.md").write_text("the queue\n")
    _commit_all(repo, "the ledger library and a tracked page")
    return repo


def test_the_local_drawer_is_outside_the_key(
    scratch_repo: Callable[..., Path], capture: Callable[..., object], env_strip: object
) -> None:
    repo = _drawer_checkout(scratch_repo)
    declared = ledger.declared_paths(repo)
    assert (declared.paths, declared.notes, declared.refused) == ([LOCAL_DRAWER], [], False)
    assert _b_declared(capture, repo) == LOCAL_DRAWER
    started, shell_started = ledger.measured_tree(repo), _tree_in(capture, repo)
    drawer = repo / LOCAL_DRAWER
    drawer.mkdir(parents=True)
    (drawer / "clock.md").write_text("19:17 the gate began\n")
    assert ledger.measured_tree(repo) == started
    assert _tree_in(capture, repo) == shell_started
    _commit_all(repo, "the drawer, tracked as a product commits it")
    with (drawer / "clock.md").open("a") as clock:
        clock.write("19:20 a row written while the gate ran\n")
    (drawer / "journal.md").write_text("a second page, new mid-run\n")
    assert ledger.measured_tree(repo) == started
    assert _tree_in(capture, repo) == shell_started


@pytest.mark.parametrize(
    "write", ["apps/planted.py", "docs/product/queue.md", f"{LOCAL_DRAWER}host.md"]
)
def test_any_other_write_still_voids(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    env_strip: object,
    write: str,
) -> None:
    repo = _drawer_checkout(scratch_repo)
    started, shell_started = ledger.measured_tree(repo), _tree_in(capture, repo)
    (repo / write).parent.mkdir(parents=True, exist_ok=True)
    (repo / write).write_text("a write while the gate ran\n")
    assert ledger.measured_tree(repo) != started
    assert _tree_in(capture, repo) != shell_started


@pytest.mark.parametrize("drawer", ["quality/local", "scripts/local/legs", "docs/local"])
def test_a_drawer_the_gate_reads_is_never_excluded_untracked(
    scratch_repo: Callable[..., Path],
    capture: Callable[..., object],
    scratch: Path,
    env_strip: object,
    drawer: str,
) -> None:
    repo = _drawer_checkout(scratch_repo)
    _b_plant_derived_leg(repo, f"{drawer} — a typo'd declaration of a drawer the gate reads")
    declared = ledger.declared_paths(repo)
    assert declared.refused and declared.paths == [], declared
    assert f"names '{drawer}', which nothing tracks" in "\n".join(declared.notes)
    _b_unreadable(capture, repo, scratch / drawer.replace("/", "-"))


def test_the_prose_probe_carries_the_tools_own_lines(tmp_path: Path) -> None:
    said = "django.core.exceptions.ImproperlyConfigured: SECRET_KEY is unset"
    (tmp_path / ledger.PROSE_OWNER).parent.mkdir(parents=True)
    (tmp_path / ledger.PROSE_OWNER).write_text("")
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!/bin/sh\nprintf '%s\\n' {said!r} >&2\nexit 1\n")
    python.chmod(0o755)
    with pytest.raises(ledger.KeyCannot) as refused:
        ledger.loop_key_prose(tmp_path, "")
    assert f"no loop key\n   the tool said: {said}" in str(refused.value)
