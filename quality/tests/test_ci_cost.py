"""The CI-cost reader: an October slice reproduces the memo; every could-not-look is exit 2."""

# does-not-cover: the live API's shapes — the fixture is normalized rows recorded from tsvs.
# does-not-cover: GitHub's own bill — the memo's arithmetic is reproduced, never the invoice.

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.drives("scripts/ci_cost.py", "quality/tests/fixtures/ci_cost/prs.tsv")

ROOT = Path(__file__).resolve().parents[2]
READER = ROOT / "scripts" / "ci_cost.py"
FIXTURE = ROOT / "quality/tests/fixtures/ci_cost"

#: Each PR's minutes, derived from the slice by the recorder's arithmetic, never the memo's.
OCTOBER_TOTALS = {
    68: 555, 67: 342, 69: 352, 70: 399, 66: 390, 72: 376, 73: 470, 74: 483, 75: 282, 76: 292,
    77: 295, 78: 339, 79: 367, 80: 574, 81: 389, 82: 460, 83: 378, 84: 315, 85: 304, 86: 460,
    87: 424, 88: 695,
}  # fmt: skip
OCTOBER_WINDOW = 22
#: The merged PR whose merge commit the slice is measured since.
SINCE_PR = 71


@pytest.fixture(scope="module")
def cc() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_cost", READER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_cost"] = module
    spec.loader.exec_module(module)
    return module


class World:
    """A recorded or built world the reader reads instead of `gh`."""

    def __init__(
        self, cc: ModuleType, prs: list[Any], runs: list[Any], jobs: dict[str, list[Any]]
    ) -> None:
        self.prs, self.run_list, self.by_run = prs, runs, jobs
        self.cc = cc
        self.order: dict[str, str] = {p.merge_sha: p.merged_at for p in prs}

    def merged_prs(self) -> list[Any]:
        return list(self.prs)

    def runs(self, created_from: str) -> list[Any]:
        return [r for r in self.run_list if r.created_at >= created_from]

    def jobs(self, run: Any) -> list[Any]:
        return list(self.by_run.get(run.id, []))

    def resolve(self, ref: str) -> str:
        found = [sha for sha in self.order if sha.startswith(ref)]
        if len(found) != 1:
            raise self.cc.CouldNotLook(f"--since {ref} is not a commit this checkout has")
        return found[0]

    def has(self, sha: str) -> bool:
        return sha in self.order

    def descends(self, since: str, sha: str) -> bool:
        return self.order[sha] > self.order[since]


def recorded(cc: ModuleType) -> tuple[World, str]:
    with (FIXTURE / "prs.tsv").open() as f:
        prs = [
            cc.Pr(int(n), head, sha, merged, created, fork == "1")
            for n, head, sha, merged, created, fork in csv.reader(f, delimiter="\t")
        ]
    with (FIXTURE / "runs.tsv").open() as f:
        runs = [cc.Run(*row) for row in csv.reader(f, delimiter="\t")]
    jobs: dict[str, list[Any]] = {}
    with (FIXTURE / "jobs.tsv").open() as f:
        for run_id, name, labels, started, completed, end in csv.reader(f, delimiter="\t"):
            jobs.setdefault(run_id, []).append(
                cc.Job(name, tuple(labels.split(",")), started, completed, end)
            )
    since = next(p.merge_sha for p in prs if p.number == SINCE_PR)
    return World(cc, prs, runs, jobs), since


def judge(cc: ModuleType, world: World, *argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    try:
        code = cc.run(list(argv), source=world, git=world, write=lines.append)
    except cc.CouldNotLook as exc:
        return 2, [str(exc)]
    return code, lines


def test_october_fixture_reproduces_the_memo(cc: ModuleType) -> None:
    world, since = recorded(cc)
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW), "--json")
    doc = json.loads("\n".join(lines))
    assert {r["number"]: r["total"] for r in doc["rows"]} == OCTOBER_TOTALS
    assert doc["mean"] == round(sum(OCTOBER_TOTALS.values()) / OCTOBER_WINDOW, 1)
    assert doc["window"] == OCTOBER_WINDOW and doc["verdict"] == "ABOVE" and code == 1
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW))
    assert lines[-2] == (
        f"ci-cost: 406 min/merged PR over {OCTOBER_WINDOW} PRs since {since[:9]} (diagnostic)"
        " — goal 155: ABOVE"
    )
    assert code == 1


def test_the_window_is_the_trailing_n(cc: ModuleType) -> None:
    world, since = recorded(cc)
    code, lines = judge(cc, world, "--since", since, "--window", "5", "--json")
    doc = json.loads("\n".join(lines))
    assert [r["number"] for r in doc["rows"]] == list(OCTOBER_TOTALS)[-5:], doc["rows"]


def test_an_abbreviated_since_leaves_its_own_merge_out_of_the_window(cc: ModuleType) -> None:
    world, since = recorded(cc)
    code, lines = judge(cc, world, "--since", since[:9], "--window", str(OCTOBER_WINDOW), "--json")
    doc = json.loads("\n".join(lines))
    assert [r["number"] for r in doc["rows"]] == list(OCTOBER_TOTALS) and doc["since"] == since


def test_a_legs_job_that_never_started_is_not_a_full_run(cc: ModuleType) -> None:
    skipped = cc.Job("legs (static)", ("ubuntu-latest",), "", "")
    started = replace(
        skipped, started_at="2026-10-20T00:00:00Z", completed_at="2026-10-20T00:01:00Z"
    )
    assert not cc.is_full([skipped]) and cc.is_full([skipped, started])


def test_a_run_with_no_jobs_is_exit_2_not_a_zero(cc: ModuleType) -> None:
    world, since = recorded(cc)
    victim = next(
        r for r in world.run_list if r.event == "pull_request" and r.conclusion == "success"
    )
    world.by_run.pop(victim.id)
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW))
    assert code == 2 and f"run {victim.id}" in lines[0] and "answered no jobs" in lines[0], lines


def test_a_cancelled_run_that_never_started_counts_zero_and_is_named(cc: ModuleType) -> None:
    world, since = recorded(cc)
    victim = next(
        r for r in world.run_list if r.event == "pull_request" and r.conclusion == "cancelled"
    )
    world.by_run.pop(victim.id)
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW))
    assert code == 1 and any(victim.id in ln and "counted 0" in ln for ln in lines), lines


def test_fewer_than_the_window_is_not_enough_data(cc: ModuleType) -> None:
    world, since = recorded(cc)
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW + 1))
    assert code == 2 and lines[0].startswith("not enough data — 22 merged PRs"), lines


def test_a_merge_commit_the_checkout_lacks_is_exit_2(cc: ModuleType) -> None:
    world, since = recorded(cc)
    lost = world.prs[-1].merge_sha
    world.has = lambda sha: sha != lost  # type: ignore[method-assign]
    code, lines = judge(cc, world, "--since", since, "--window", "3")
    assert code == 2 and lost[:9] in lines[0] and "not in this checkout" in lines[0], lines


def test_no_gh_is_exit_2(cc: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    with pytest.raises(cc.CouldNotLook, match="no `gh` on PATH"):
        cc.GhSource(ROOT, tmp_path)


def test_a_refused_token_is_exit_2(
    cc: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import quality.djb.ledger as ledger

    monkeypatch.setattr(cc.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(ledger, "_gh", lambda root, sink, name, *argv: (4, ""))
    monkeypatch.setattr(cc.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    with pytest.raises(SystemExit) as stopped:
        cc.main(["--since", "HEAD"])
    assert stopped.value.code == 2
    assert "exited 4 — the API refused" in capsys.readouterr().err


def _world(cc: ModuleType, minutes: int, *, shared: bool = False, hosted: bool = False) -> World:
    stamp = "2026-10-20T{:02d}:00:00Z".format
    prs = [cc.Pr(0, "pm/zero", "s0", stamp(0), stamp(0))]
    runs: list[Any] = []
    jobs: dict[str, list[Any]] = {}
    for n in (1, 2):
        sha = "m1" if shared else f"m{n}"
        prs.append(cc.Pr(n, f"pm/b{n}", sha, stamp(2 * n + 1), stamp(2 * n)))
        runs.append(
            cc.Run(f"pr{n}", stamp(2 * n), "pull_request", "success", f"pm/b{n}", "gate", f"h{n}")
        )
        labels = ("self-hosted", "linux") if hosted and n == 2 else ("ubuntu-latest",)
        jobs[f"pr{n}"] = [
            cc.Job(
                "legs (static)", labels, stamp(2 * n), f"2026-10-20T{2 * n:02d}:{minutes:02d}:00Z"
            )
        ]
    for sha in sorted({p.merge_sha for p in prs[1:]}):
        runs.append(cc.Run(f"push-{sha}", stamp(5), "push", "success", "main", "gate", sha))
        jobs[f"push-{sha}"] = [
            cc.Job("derive", ("ubuntu-latest",), stamp(5), "2026-10-20T05:10:00Z")
        ]
    return World(cc, prs, runs, jobs)


def test_below_the_goal_is_exit_0(cc: ModuleType) -> None:
    code, lines = judge(cc, _world(cc, 30), "--since", "s0", "--window", "2")
    assert code == 0 and lines[-1].endswith("goal 155: MET"), lines


def test_a_train_splits_its_one_merge_over_the_prs_it_landed(cc: ModuleType) -> None:
    code, lines = judge(cc, _world(cc, 30, shared=True), "--since", "s0", "--window", "2", "--json")
    rows = json.loads("\n".join(lines))["rows"]
    assert [r["units"]["other"] for r in rows] == [5.0, 5.0], rows


def test_self_hosted_minutes_are_labelled_and_never_billed(cc: ModuleType) -> None:
    code, lines = judge(cc, _world(cc, 30, hosted=True), "--since", "s0", "--window", "2", "--json")
    doc = json.loads("\n".join(lines))
    assert doc["self_hosted_minutes"] == 30 and doc["rows"][1]["units"]["static"] == 0, doc


def test_a_started_job_bills_whole_minutes_rounded_up(cc: ModuleType) -> None:
    job = cc.Job(
        "legs (static)", ("ubuntu-latest",), "2026-10-20T00:00:00Z", "2026-10-20T00:01:01Z"
    )
    assert cc.billed(job) == 2
    assert cc.billed(replace(job, completed_at=job.started_at)) == 1
    assert cc.billed(replace(job, started_at="")) == 0
    assert cc.billed(replace(job, completed_at=job.started_at, conclusion="skipped")) == 0


def test_does_not_cover_is_printed_under_json(cc: ModuleType) -> None:
    code, lines = judge(cc, _world(cc, 30), "--since", "s0", "--window", "2", "--json")
    named = json.loads("\n".join(lines))["does_not_cover"]
    for blind in ("billing endpoint", "multipliers", "never merged", "self-hosted"):
        assert any(blind in line for line in named), (blind, named)


def _all_in(span_from: str, span_to: str, n: int) -> float:
    """The all-in number, re-derived from the tsvs by this test's own arithmetic."""
    with (FIXTURE / "runs.tsv").open() as f:
        inside = {row[0] for row in csv.reader(f, delimiter="\t") if span_from < row[1] <= span_to}
    total = 0
    with (FIXTURE / "jobs.tsv").open() as f:
        for run_id, _name, labels, started, completed, end in csv.reader(f, delimiter="\t"):
            if run_id not in inside or "self-hosted" in labels.split(","):
                continue
            if end == "skipped" or not started or not completed:
                continue
            a, b = (datetime.fromisoformat(s.replace("Z", "+00:00")) for s in (started, completed))
            total += max(1, -(-int(max(0.0, (b - a).total_seconds())) // 60))
    return round(total / n, 1)


def test_the_all_in_line_is_every_billed_minute_of_the_window_over_its_merged_prs(
    cc: ModuleType,
) -> None:
    """R0: the 463's own arithmetic — every run created in the span — judged for the exit code."""
    world, since = recorded(cc)
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW), "--json")
    doc = json.loads("\n".join(lines))
    want = _all_in(doc["span"][0], doc["span"][1], OCTOBER_WINDOW)
    assert doc["all_in"] == want and want > doc["mean"], (doc["all_in"], want, doc["mean"])
    assert doc["verdict"] == "ABOVE" and code == 1
    code, lines = judge(cc, world, "--since", since, "--window", str(OCTOBER_WINDOW))
    assert lines[-1] == (
        f"all-in: {want:.0f} min/merged PR over {OCTOBER_WINDOW} PRs since {since[:9]}"
        " — goal 155: ABOVE"
    )
    assert lines[-2].startswith("ci-cost: 406 min/merged PR") and "(diagnostic)" in lines[-2]


def test_a_queued_job_or_a_run_in_progress_is_exit_2(
    cc: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """R0: a job with no stamps yet, or a run with no conclusion, bills nothing it will bill."""
    monkeypatch.setattr(cc.shutil, "which", lambda name: "/usr/bin/gh")
    source = cc.GhSource(ROOT, tmp_path)
    queued = {"name": "legs (static)", "status": "queued", "started_at": None}
    monkeypatch.setattr(source, "_lines", lambda *argv: [queued])
    done = cc.Run("7", "2026-10-20T00:00:00Z", "pull_request", "success", "pm/x", "gate", "h")
    with pytest.raises(cc.CouldNotLook, match="still queued or in progress"):
        source.jobs(done)
    finished = {**queued, "status": "completed", "conclusion": "skipped"}
    monkeypatch.setattr(source, "_lines", lambda *argv: [finished])
    assert source.jobs(done)[0].conclusion == "skipped"
    with pytest.raises(cc.CouldNotLook, match="run 7 is still queued or in progress"):
        source.jobs(replace(done, conclusion=""))
