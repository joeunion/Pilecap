"""The `pytest-x2` leg: each member judged from its tool's answer, in the unit's order."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.djb.legs import pytest_x2 as S

pytestmark = pytest.mark.drives("quality/djb/legs/pytest_x2.py")

ROOT = Path(__file__).resolve().parents[2]
Answer = tuple[int, str]


class Tools:
    """The leg's three subprocess roads replaced: each call recorded, each answer scripted."""

    def __init__(self, answer: Callable[[list[str], Mapping[str, str]], Answer]) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[Mapping[str, str]] = []
        self.answer = answer

    def captured(
        self, ctx: R.Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None
    ) -> Answer:
        self.calls.append(list(argv))
        self.envs.append(dict(env or {}))
        return self.answer(list(argv), env or {})

    def streamed(
        self, ctx: R.Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None
    ) -> int:
        rc, text = self.captured(ctx, argv, env)
        sys.stdout.write(text)
        return rc

    def bash(self, ctx: R.Ctx, script: str, env: Mapping[str, str] | None = None) -> Answer:
        return self.captured(ctx, ["bash", script], env)


def _tools(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[list[str], Mapping[str, str]], Answer]
) -> Tools:
    tools = Tools(answer)
    monkeypatch.setattr(S, "_captured", tools.captured)
    monkeypatch.setattr(S, "_streamed", tools.streamed)
    monkeypatch.setattr(S, "_bash", tools.bash)
    return tools


def _ctx(root: Path = ROOT, /, **env: str) -> R.Ctx:
    return R.Ctx(root, "full", {"PATH": "/usr/bin:/bin", **env})


def test_the_leg_claims_the_pytest_x2_line_at_its_place_in_the_unit() -> None:
    table = R.load(ROOT)
    assert table.unit("pytest-x2")[1] == ("pytest-x2",)
    assert table.leg("pytest-x2").body is S.run
    assert table.leg("pytest-x2").modes == frozenset({"full"})


def test_the_leg_imports_under_the_system_python_with_no_site() -> None:
    done = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-c",
            "import sys; sys.path.insert(0, '.'); import quality.djb.legs.pytest_x2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


CENSUS = "LIVE  x 101 port=7233\nORPHAN x 202 -\nORPHAN x 202 -\nREFUSED x 303 -\nnoise\n"


def test_the_census_reads_every_pid_once_and_the_orphans_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tools(monkeypatch, lambda argv, env: (0, CENSUS))
    assert S.temporal_census(_ctx(), "pre-suite") == (0, ["101", "202", "303"], ["202"])


def test_a_census_whose_instrument_fails_could_not_look(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch, lambda argv, env: (3, "boom\n"))
    assert S.temporal_census(_ctx(), "post-suite")[0] == 2


def test_a_missing_sweep_script_is_could_not_look(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert S.temporal_census(_ctx(tmp_path), "pre-suite")[0] == 2
    assert "CANNOT BE TAKEN" in capsys.readouterr().err


def test_an_orphan_seen_before_the_suite_is_not_the_suites(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert S.new_orphans(["202"], ["202"]) == 0
    assert S.new_orphans(["101"], ["202"]) == 1
    assert "pid 202" in capsys.readouterr().err


def _decide(doc: object, rc: int = 0) -> Callable[[list[str], Mapping[str, str]], Answer]:
    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        if "decide" in argv and doc is not None:
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps(doc))
        return rc, ""

    return answer


DOC = {"mode": "skip", "key": "k1", "paths": ["apps/a", "apps/b"], "bankable": True}


@pytest.mark.parametrize(("rc", "want"), [(1, 1), (3, 2)])
def test_the_partition_finding_is_1_and_its_broken_enforcement_2(
    monkeypatch: pytest.MonkeyPatch, rc: int, want: int
) -> None:
    _tools(monkeypatch, _decide(DOC, rc))
    assert S.partition(_ctx(), S.Run.of({})) == (want, None)


def test_a_decision_that_cannot_be_read_back_is_2(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch, _decide(None))
    assert S.partition(_ctx(), S.Run.of({}))[0] == 2


def test_the_decision_stands_on_a_whole_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch, _decide(DOC))
    assert S.partition(_ctx(), S.Run.of({})) == (
        0,
        S.Decision("skip", "k1", ("apps/a", "apps/b"), True),
    )


def test_pr_measures_the_whole_collection_with_its_own_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tools(monkeypatch, _decide(DOC))
    env = {"GATE_PR": "1", "GATE_PR_PYTEST_ARGS": "-m x --djb-scope-counts=/c"}
    rc, decision = S.partition(_ctx(**env), S.Run.of(env))
    assert (rc, decision) == (
        0,
        S.Decision("measure", "k1", ("-m", "x", "--djb-scope-counts=/c"), True),
    )


def test_a_shard_measures_the_whole_collection_unnarrowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch, _decide(DOC))
    env = {"GATE_SHARD_K": "2", "GATE_SHARD_N": "3"}
    assert S.partition(_ctx(**env), S.Run.of(env))[1] == S.Decision("measure", "k1", (), True)


def test_a_typed_seed_is_used_and_an_unparsable_one_refused() -> None:
    assert S.seed({"DJB_GATE_PYTEST_SEED": "42"}) == 42
    assert S.seed({"DJB_GATE_PYTEST_SEED": "4x"}) is None
    minted = S.seed({})
    assert minted is not None and 0 <= minted < 2**30


def test_a_durations_path_outside_the_rootdir_or_through_dotdot_is_refused(tmp_path: Path) -> None:
    assert S.durations_path(tmp_path, {}) == S.DURATIONS
    assert S.durations_path(tmp_path, {"DJB_GATE_DURATIONS_PATH": "a/../b.json"}) is None
    assert S.durations_path(tmp_path, {"DJB_GATE_DURATIONS_PATH": "/elsewhere/d.json"}) is None


def test_shard_k_of_n_splits_and_groups_and_one_of_one_is_whole(tmp_path: Path) -> None:
    env = {"GATE_SHARD_K": "2", "GATE_SHARD_N": "3"}
    assert S.split_args(_ctx(tmp_path, **env), S.Run.of(env)) == [
        "--splits",
        "3",
        "--group",
        "2",
        "--durations-path",
        S.DURATIONS,
    ]
    one = {"GATE_SHARD_K": "1", "GATE_SHARD_N": "1"}
    assert S.split_args(_ctx(tmp_path, **one), S.Run.of(one)) == []
    store = {"GATE_STORE_DURATIONS": "1"}
    assert S.split_args(_ctx(tmp_path, **store), S.Run.of(store)) == [
        "--store-durations",
        "--durations-path",
        S.DURATIONS,
    ]
    assert S.split_args(_ctx(tmp_path), S.Run.of({})) == []


def test_fewer_collectors_than_workers_is_2_and_the_file_states_the_count(tmp_path: Path) -> None:
    assert S.counts_short("", 4) == 0
    (tmp_path / "gw0").write_text("workers=2\n")
    assert S.counts_short(str(tmp_path), 4) == 2
    (tmp_path / "gw1").write_text("workers=2\n")
    assert S.counts_short(str(tmp_path), 4) == 0


def _passes(rcs: list[int], text: str = "") -> Callable[[list[str], Mapping[str, str]], Answer]:
    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        return rcs.pop(0), text

    return answer


def test_shard_k_of_n_passes_split_and_group_to_both_passes_under_one_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _tools(monkeypatch, _passes([0, 0]))
    args = ["--splits", "3", "--group", "2", "--durations-path", S.DURATIONS]
    assert S.passes(_ctx(), S.Run.of({}), 4, 77, args, "") == 0
    want = [S.TEST_SH, "-n", "4", "--randomly-seed=77", *args]
    assert tools.calls == [want, want]


@pytest.mark.parametrize(
    ("env", "calls"), [({"GATE_PASSES": "1"}, 1), ({"GATE_STORE_DURATIONS": "1"}, 1), ({}, 2)]
)
def test_passes_one_and_store_durations_run_pass_one_only(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], calls: int
) -> None:
    tools = _tools(monkeypatch, _passes([0, 0]))
    assert S.passes(_ctx(), S.Run.of(env), 2, 1, [], "") == 0
    assert len(tools.calls) == calls


@pytest.mark.parametrize(("rc", "want"), [(5, 2), (4, 2), (1, 1)])
def test_a_pass_one_that_collected_nothing_is_2_and_a_red_one_1(
    monkeypatch: pytest.MonkeyPatch, rc: int, want: int
) -> None:
    tools = _tools(monkeypatch, _passes([rc]))
    assert S.passes(_ctx(), S.Run.of({}), 2, 1, [], "") == want
    assert len(tools.calls) == 1


def test_a_red_pass_two_names_the_inherited_state_and_its_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "== short test summary info ==\nFAILED apps/x/tests/test_y.py::test_z\n== 1 failed ==\n"
    _tools(monkeypatch, _passes([0, 1], text))
    assert S.passes(_ctx(), S.Run.of({}), 2, 9, [], "") == 1
    err = capsys.readouterr().err
    assert "FAILED IN PASS 2 UNDER THE SAME SEED" in err
    assert "     FAILED apps/x/tests/test_y.py::test_z" in err


def test_pass_two_that_never_came_up_is_the_harness_not_an_inference() -> None:
    lines = "\n".join(S.pass2_verdict("INTERNALERROR boom\n1 error\n", 3, 2))
    assert "PASS 2 DID NOT COME UP" in lines and "zero tests ran" in lines
    assert "--randomly-seed=3" in lines and "does NOT read them" in lines
    assert "CANNOT TELL WHY" in "\n".join(S.pass2_verdict("exit\n", 3, 2))


GRANTS = """\
____ test_prod ____
apps/ledger/tests/test_a.py:10: in test_prod
apps/billing/services.py:20: in charge
apps/ledger/services.py:30: in write
E   psycopg.errors.InsufficientPrivilege: permission denied for table ledger_entry
____ test_own ____
apps/ledger/tests/test_b.py:5: in test_own
E   permission denied for table ledger_entry
____ test_other ____
apps/x/services.py:1: in f
E   permission denied for table not_a_ledger
"""


def test_the_grants_judge_names_product_writes_apart_from_test_owned_ones() -> None:
    assert S.grants_judge(GRANTS, ["ledger_entry"]) == [
        (
            "PROD",
            "test_prod",
            "ledger_entry via apps/ledger/services.py:30 (called from apps/billing/services.py:20)",
        ),
        ("TEST", "test_own", "ledger_entry (from apps/ledger/tests/test_b.py:5)"),
    ]


@pytest.mark.parametrize(
    "env",
    [
        {"DJB_GATE_GRANTS_PASS": "0"},
        {"GATE_STORE_DURATIONS": "1"},
        {"GATE_PR": "1"},
        {"CI": "true"},
    ],
)
def test_the_grants_pass_steps_aside_for_a_measurement_a_pr_ci_or_a_typed_no(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    tools = _tools(monkeypatch, _passes([]))
    assert S.grants_pass(_ctx(**env), S.Run.of(env), 2, 1, []) == 0
    assert tools.calls == []


def test_a_product_write_to_a_ledger_reds_the_grants_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        return (1, GRANTS) if argv[0] == S.TEST_SH else (0, "")

    monkeypatch.setattr(
        S,
        "grants_db",
        lambda ctx, action, t="": (0, "template=t ledgers=1:ledger_entry from=migrate\n"),
    )
    tools = _tools(monkeypatch, answer)
    assert S.grants_pass(_ctx(), S.Run.of({}), 2, 5, ["a", "--djb-scope-counts=/c"]) == 1
    assert tools.calls == [[S.TEST_SH, "-n", "2", "--randomly-seed=5", "a"]]
    assert tools.envs[0]["DATABASE_USER"] == S.GRANTS_ROLE


def test_a_test_owned_privilege_failure_is_named_not_a_verdict_before_its_transcript(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    own = (
        "____ test_own ____\n"
        "apps/ledger/tests/test_b.py:5: in test_own\n"
        "E   permission denied for table ledger_entry\n"
        "=========================== short test summary info ============================\n"
        "FAILED apps/ledger/tests/test_b.py::test_own\n"
        "========================= 1 failed, 5 passed in 1.00s =========================\n"
    )

    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        return (1, own) if argv[0] == S.TEST_SH else (0, "")

    monkeypatch.setattr(
        S,
        "grants_db",
        lambda ctx, action, t="": (0, "template=t ledgers=1:ledger_entry from=migrate\n"),
    )
    _tools(monkeypatch, answer)
    assert S.grants_pass(_ctx(), S.Run.of({}), 2, 5, []) == 0
    out = capsys.readouterr().out
    assert out.index("NOT a verdict about the tree") < out.index("1 failed, 5 passed"), out


def test_own_tree_census_names_an_undeclared_shape_2(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch, lambda argv, env: (1, "UNRECOGNIZED thing\n"))
    assert S.own_tree_census(_ctx(DATABASE_NAME="djb_x")) == 2


def test_a_deployment_lifetime_asserts_no_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(monkeypatch, lambda argv, env: (0, "deployment\n" if argv[0] == "uv" else ""))
    assert S.own_tree_census(_ctx(DATABASE_NAME="djb_x")) == 0
    assert not any("--assert-none" in c for c in tools.calls)


def test_a_leaked_schedule_in_process_lifetime_is_a_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        if argv[0] == "uv":
            return 0, "process\n"
        return (1, "") if "schedule" in argv else (0, "")

    _tools(monkeypatch, answer)
    assert S.own_tree_census(_ctx(DATABASE_NAME="djb_x")) == 1


@pytest.mark.parametrize(
    ("env", "banks"),
    [({}, True), ({"GATE_PR": "1"}, False), ({"GATE_SHARD_K": "1", "GATE_SHARD_N": "2"}, False)],
)
def test_only_a_whole_measured_run_banks_the_partition(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], banks: bool
) -> None:
    tools = _tools(monkeypatch, lambda argv, env_: (0, ""))
    assert S.bank_partition(_ctx(**env), S.Run.of(env), S.Decision("measure", "k", (), True)) == 0
    assert (tools.calls == [[*S.BANK, "--key", "k"]]) is banks


def test_a_partition_bank_that_fails_is_2(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch, lambda argv, env: (1, ""))
    assert S.bank_partition(_ctx(), S.Run.of({}), S.Decision("measure", "k", (), True)) == 2


def _unit(monkeypatch: pytest.MonkeyPatch, verdicts: dict[str, int]) -> list[str]:
    seen: list[str] = []

    def census(ctx: R.Ctx, phase: str) -> tuple[int, list[str], list[str]]:
        seen.append(phase)
        return verdicts.get(phase, 0), [], []

    def member(name: str, value: object) -> Callable[..., object]:
        def body(*args: object) -> object:
            seen.append(name)
            return value

        return body

    decision = S.Decision("measure", "k", (), True)
    monkeypatch.setattr(S, "temporal_census", census)
    monkeypatch.setattr(
        S, "partition", member("partition", (verdicts.get("partition", 0), decision))
    )
    monkeypatch.setattr(S, "suite", member("suite", verdicts.get("suite", 0)))
    monkeypatch.setattr(S, "new_orphans", member("orphans", verdicts.get("orphans", 0)))
    monkeypatch.setattr(S, "own_tree_census", member("own-tree", verdicts.get("own-tree", 0)))
    return seen


ORDER = ["pre-suite", "partition", "suite", "post-suite", "orphans", "own-tree"]


def test_the_unit_runs_its_members_in_the_listing_order(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _unit(monkeypatch, {})
    assert S.run(_ctx()) == 0
    assert seen == ORDER


@pytest.mark.parametrize("member", ORDER)
@pytest.mark.parametrize("verdict", [1, 2])
def test_the_unit_stops_at_its_first_member_that_is_not_green(
    monkeypatch: pytest.MonkeyPatch, member: str, verdict: int
) -> None:
    seen = _unit(monkeypatch, {member: verdict})
    assert S.run(_ctx()) == verdict
    assert seen == ORDER[: ORDER.index(member) + 1]


def test_the_suite_takes_one_slot_and_a_bank_takes_every_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quality.djb import hold

    asked: list[tuple[str, bool, str]] = []

    def acquire(mode: str, *, lease_first: bool, lease: hold.Hold) -> hold.Hold:
        asked.append((mode, lease_first, str(lease.paths[0]) if lease.paths else ""))
        return hold.Hold("slot")

    monkeypatch.setattr(hold, "acquire_slot", acquire)
    assert S.slot(_ctx(), S.Run.of({})) is not None
    lease = {"GATE_SLOT_LEASE_FIRST": "1", "GATE_LEASE": "/tmp/djb-lease"}  # noqa: S108 — a planted lease path compared, never opened
    assert S.slot(_ctx(**lease), S.Run.of({"GATE_BANK": "1"})) is not None
    assert asked == [("full", False, ""), ("bank", True, "/tmp/djb-lease")]  # noqa: S108 — a planted lease path compared, never opened


def test_the_workers_line_carries_the_slots_own_phrase(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb import hold

    taken = hold.Hold("slot", workers=3, phrase="planted: one share per pytest slot")
    monkeypatch.setattr(S, "slot", lambda ctx, run: taken)
    monkeypatch.setattr(S, "passes", lambda *a: 1)
    decision = S.Decision("measure", "k", (), True)
    assert S.suite(_ctx(DJB_GATE_PYTEST_SEED="7"), S.Run.of({}), decision) == 1
    said = capsys.readouterr().out
    assert "  workers:    -n 3 (planted: one share per pytest slot)\n" in said
    assert "cores split" not in said


def _product(tmp_path: Path, *apps: str) -> Path:
    """A tree whose drawer declares a product namespace, with `apps/<label>/apps.py` each."""
    (tmp_path / "quality/local").mkdir(parents=True)
    (tmp_path / "quality/local/rules.yaml").write_text(
        "rule_id_namespace: zzzg3\ntemplate_rule_ids_through: 98\n"
    )
    for label in apps:
        (tmp_path / "apps" / label).mkdir(parents=True)
        (tmp_path / "apps" / label / "apps.py").write_text("")
    return tmp_path


def _paths(listed: str) -> Callable[[list[str], Mapping[str, str]], Answer]:
    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        if "decide" in argv:
            Path(argv[argv.index("--out") + 1]).write_text(
                json.dumps({"mode": "full", "key": "k1", "paths": [], "bankable": True})
            )
            return 0, "  PLATFORM PARTITION: RUNNING — no banked verdict for this key\n"
        return (0, listed) if argv == list(S.PATHS) else (0, "")

    return answer


NETS = "apps/accounts/tests/test_a9_matrix.py\n"


def test_a_product_tree_decides_no_platform_partition_and_names_its_own_apps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = _tools(monkeypatch, _paths(f"apps/widgets\n{NETS}"))
    root = _product(tmp_path, "widgets")
    assert S.partition(_ctx(root), S.Run.of({})) == (
        0,
        S.Decision("product", "", ("apps/widgets",), False),
    )
    assert tools.calls == [list(S.PATHS)]
    assert capsys.readouterr().out.splitlines() == [f"  {S.ON_A_PRODUCT}"]


def test_the_template_tree_still_decides_the_platform_partition(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = _tools(monkeypatch, _paths(""))
    assert S.partition(_ctx(), S.Run.of({})) == (0, S.Decision("full", "k1", (), True))
    assert tools.calls[0][: len(S.DECIDE)] == list(S.DECIDE)
    assert "PLATFORM PARTITION: RUNNING" in capsys.readouterr().out


def test_a_product_pass_runs_its_apps_once_then_the_grants_pass_on_them_and_no_bank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb import hold

    tools = _tools(monkeypatch, _paths(f"apps/widgets\n{NETS}"))
    monkeypatch.setattr(S, "slot", lambda ctx, run: hold.Hold("slot", workers=2))
    monkeypatch.setattr(S, "counts_short", lambda *a: False)
    monkeypatch.setattr(
        S,
        "grants_db",
        lambda ctx, action, t="": (0, "template=t ledgers=1:ledger_entry from=migrate\n"),
    )
    ctx = _ctx(_product(tmp_path, "widgets"), DJB_GATE_PYTEST_SEED="7")
    rc, decision = S.partition(ctx, S.Run.of({}))
    assert rc == 0 and decision is not None
    assert S.suite(ctx, S.Run.of({}), decision) == 0
    ran = [c for c in tools.calls if c[0] == S.TEST_SH]
    assert [c[:5] for c in ran] == [[S.TEST_SH, "-n", "2", "--randomly-seed=7", "apps/widgets"]] * 2
    assert tools.envs[tools.calls.index(ran[1])]["DATABASE_USER"] == S.GRANTS_ROLE
    assert not [c for c in tools.calls if S.BANK[-1] in c or "decide" in c]
    said = capsys.readouterr().out
    assert "PRODUCT PASS — the one pass runs: apps/widgets" in said
    assert "  pytest pass 2 NOT run — a product pass is one pass\n" in said
    assert "  grants pass: the product's own targets\n" in said
    assert "PLATFORM PARTITION" not in said


def test_a_product_pr_runs_its_own_apps_once_with_the_grants_pass_and_no_partition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb import hold

    tools = _tools(monkeypatch, _paths(f"apps/widgets\n{NETS}"))
    monkeypatch.setattr(S, "slot", lambda ctx, run: hold.Hold("slot", workers=2))
    monkeypatch.setattr(S, "counts_short", lambda *a: False)
    monkeypatch.setattr(
        S,
        "grants_db",
        lambda ctx, action, t="": (0, "template=t ledgers=1:ledger_entry from=migrate\n"),
    )
    env = {"GATE_PR": "1", "GATE_PR_PYTEST_ARGS": "apps/widgets", "DJB_GATE_PYTEST_SEED": "7"}
    ctx = _ctx(_product(tmp_path, "widgets"), **env)
    run = S.Run.of(env)
    rc, decision = S.partition(ctx, run)
    assert (rc, decision) == (0, S.Decision("product", "", ("apps/widgets",), False))
    assert decision is not None
    assert S.suite(ctx, run, decision) == 0
    ran = [c for c in tools.calls if c[0] == S.TEST_SH]
    assert [c[:5] for c in ran] == [[S.TEST_SH, "-n", "2", "--randomly-seed=7", "apps/widgets"]] * 2
    assert not [c for c in tools.calls if "decide" in c]
    said = capsys.readouterr().out
    assert "  grants pass: the product's own targets\n" in said
    assert "NOT run — --pr" not in said


def test_a_product_app_with_no_tests_yet_passes_the_product_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb import hold

    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        return (
            (5, "no tests ran\n") if argv[0] == S.TEST_SH else _paths("apps/widgets\n")(argv, env)
        )

    _tools(monkeypatch, answer)
    monkeypatch.setattr(S, "slot", lambda ctx, run: hold.Hold("slot", workers=2))
    monkeypatch.setattr(S, "counts_short", lambda *a: False)
    monkeypatch.setattr(
        S,
        "grants_db",
        lambda ctx, action, t="": (0, "template=t ledgers=1:ledger_entry from=migrate\n"),
    )
    ctx = _ctx(_product(tmp_path, "widgets"), DJB_GATE_PYTEST_SEED="7")
    rc, decision = S.partition(ctx, S.Run.of({}))
    assert rc == 0 and decision is not None
    assert S.suite(ctx, S.Run.of({}), decision) == 0
    assert (
        "  pytest-x2: apps/widgets has no tests yet — nothing to run\n" in capsys.readouterr().out
    )


def test_a_product_with_no_app_yet_runs_no_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _product(tmp_path)
    tools = _tools(monkeypatch, _paths(NETS))
    rc, decision = S.partition(_ctx(root), S.Run.of({}))
    assert rc == 0 and decision == S.Decision("product", "", (), False)
    assert decision is not None
    assert S.suite(_ctx(root), S.Run.of({}), decision) == 0
    assert tools.calls == [list(S.PATHS)]
    said = capsys.readouterr().out
    assert "  PRODUCT PASS — no product app yet: nothing to run, and no grants pass\n" in said


#: The headline a refusing sweep prints last, as `sweep.sh`'s `gate_die` shapes it.
SWEEP_HEADLINE = "!! NOTHING WAS JUDGED — the temporal CLI answered (exit 1: deadline exceeded)"


@pytest.mark.parametrize("census", ["schedule", "open-execution"])
def test_the_cause_is_sweeps_headline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], census: str
) -> None:
    said = f"  reading the namespace\n!! an earlier line\n{SWEEP_HEADLINE}\n   the remedy\n"

    def answer(argv: list[str], env: Mapping[str, str]) -> Answer:
        if argv[0] == "bash":
            return 0, "0\n"
        return (2, said) if census in argv else (0, "")

    _tools(monkeypatch, answer)
    assert S.process_lifetime(_ctx(), "djb_x") == 2
    err = capsys.readouterr().err
    assert f"   cause: {SWEEP_HEADLINE[3:]}" in err.splitlines(), err


def test_a_lifetime_settings_cannot_answer_is_quoted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    said = "ModuleNotFoundError: No module named 'config.settings.local'"
    _tools(
        monkeypatch, lambda argv, env: (1, f"Traceback\n{said}\n") if argv[0] == "uv" else (0, "")
    )
    assert S.own_tree_census(_ctx(DATABASE_NAME="djb_x")) == 2
    err = capsys.readouterr().err
    assert f"   the tool said: {said}" in err and "(exit 2).\n   the tool said:" in err, err


#: The grants program's world, faked: no Postgres and no Django, only what it imports.
FAKES = {
    "django/__init__.py": "def setup():\n    pass\n",
    "django/conf.py": (
        "class settings:\n    DATABASES = {'default': "
        "{'USER': 'u', 'PASSWORD': 'p', 'HOST': '', 'PORT': '', 'NAME': 'djb_x'}}\n"
    ),
    "psycopg/__init__.py": (
        "class _Row:\n    def fetchone(self):\n        return None\n\n\n"
        "class _Conn:\n    def __enter__(self):\n        return self\n\n"
        "    def __exit__(self, *a):\n        return False\n\n"
        "    def execute(self, *a):\n        return _Row()\n\n\n"
        "class Error(Exception):\n    pass\n\n\n"
        "def connect(**k):\n    return _Conn()\n"
    ),
    "psycopg/sql.py": (
        "class SQL(str):\n    def format(self, *a):\n        return self\n\n\n"
        "def Identifier(x):\n    return x\n\n\ndef Literal(x):\n    return x\n"
    ),
}


def test_a_grants_template_that_will_not_migrate_quotes_migrate(tmp_path: Path) -> None:
    said = "django.db.utils.OperationalError: connection refused"
    for rel, body in FAKES.items():
        (tmp_path / "fakes" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "fakes" / rel).write_text(body)
    (tmp_path / "manage.py").write_text(
        f"import sys\nprint({said!r}, file=sys.stderr)\nsys.exit(1)\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": f"{tmp_path / 'fakes'}{os.pathsep}{ROOT}",
        "DJB_GRANTS_ACTION": "prepare",
        "DJB_GRANTS_ROLE": "r",
        "DJB_GRANTS_SECRET": "s",
    }
    done = subprocess.run(
        [sys.executable, "-"],
        input=S.GRANTS_DB,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2, done
    assert f"would not migrate (exit 1)\n   the tool said: {said}" in done.stdout, done
