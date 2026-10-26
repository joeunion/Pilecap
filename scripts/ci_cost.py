"""Runner-minutes per merged PR since a sha, against the goal; exit 0 met, 1 above, 2 blind."""

# does-not-cover: the GitHub billing endpoint — the PM's token cannot read it; the bill rules.
# does-not-cover: the macOS/Windows minute multipliers — every job is billed at ubuntu's 1x.
# does-not-cover: minutes of runs on branches never merged — their own line, never in the mean.
# does-not-cover: self-hosted minutes — unbilled, printed labelled self-hosted, not in the mean.
# does-not-cover: the nightlies — printed as the window's share per merged PR, never in the mean.
# does-not-cover: main pushes no merged PR produced (ledger commits) — their own line, not the mean.

from __future__ import annotations

import argparse
import json
import math
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from quality.could_not_look import CouldNotLook, exit_could_not_look  # noqa: E402

ROOT = pathlib.Path(_ROOT)
GOAL = 155
WINDOW = 30
UNITS = ("selftest", "pytest-x2", "images", "static", "supply-chain", "house-rules", "other")
NIGHTLY_WORKFLOWS = frozenset({"nightly-proof", "nightly-security", "mirror images"})
PROOF_WORKFLOW = "proof-from-zero"
#: A zero-job run with one of these conclusions never reached a runner, so it billed nothing.
NEVER_STARTED = frozenset({"cancelled", "skipped"})
DOES_NOT_COVER = tuple(
    line.split(":", 1)[1].strip()
    for line in pathlib.Path(__file__).read_text().splitlines()
    if line.startswith("# does-not-cover:")
)


@dataclass(frozen=True)
class Pr:
    """One merged pull request, as `gh pr list` names it."""

    number: int
    head: str
    merge_sha: str
    merged_at: str
    created_at: str
    fork: bool = False


@dataclass(frozen=True)
class Run:
    """One workflow run, as the runs endpoint names it."""

    id: str
    created_at: str
    event: str
    conclusion: str
    branch: str
    workflow: str
    head_sha: str


@dataclass(frozen=True)
class Job:
    """One job of a run, with the two stamps GitHub bills between."""

    name: str
    labels: tuple[str, ...]
    started_at: str
    completed_at: str
    conclusion: str = ""


class Source(Protocol):
    """Where the PRs, runs and jobs come from: `gh` live, or a recorded fixture."""

    def merged_prs(self) -> list[Pr]: ...

    def runs(self, created_from: str) -> list[Run]: ...

    def jobs(self, run: Run) -> list[Job]: ...


class Git(Protocol):
    """The two questions asked of the checkout."""

    def resolve(self, ref: str) -> str: ...

    def has(self, sha: str) -> bool: ...

    def descends(self, since: str, sha: str) -> bool: ...


def _t(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def billed(job: Job) -> int:
    """The job's minutes as GitHub bills them: rounded UP, a started job at least one."""
    if job.conclusion == "skipped" or not job.started_at or not job.completed_at:
        return 0
    seconds = max(0.0, (_t(job.completed_at) - _t(job.started_at)).total_seconds())
    return max(1, math.ceil(seconds / 60))


def unit(name: str) -> str:
    """The cost unit a job's name belongs to."""
    if name.startswith("legs (selftest") or name.startswith("selftest belt"):
        return "selftest"
    if name.startswith("legs (pytest-x"):
        return "pytest-x2"
    if name == "images":
        return "images"
    if name == "legs (static)":
        return "static"
    if name == "legs (supply-chain)" or name.startswith("supply chain"):
        return "supply-chain"
    if name == "legs (full-house-rules)":
        return "house-rules"
    return "other"


def self_hosted(job: Job) -> bool:
    """Whether the job ran on a runner GitHub does not bill."""
    return "self-hosted" in job.labels


def is_full(jobs: Sequence[Job]) -> bool:
    """Whether a gate run measured the legs, rather than honouring a verdict."""
    return any(j.name.startswith("legs (") and billed(j) for j in jobs)


@dataclass
class Row:
    """One merged PR's cost, unit by unit."""

    number: int
    merge_sha: str
    fork: bool
    pr_runs: int = 0
    full: int = 0
    cancelled: int = 0
    failed: int = 0
    pushes: int = 0
    main: str = "none"
    proof: float = 0.0
    units: dict[str, float] = field(default_factory=lambda: dict.fromkeys(UNITS, 0.0))

    @property
    def total(self) -> float:
        """Every billed minute this PR bought, its share of a shared merge included."""
        return sum(self.units.values()) + self.proof


@dataclass
class Report:
    """The window's rows and the lines printed beside them."""

    since: str
    window: int
    rows: list[Row]
    span: tuple[str, str]
    nightly: int
    unmerged: int
    unmerged_runs: int
    direct_main: int
    self_hosted: int
    zero_job_runs: list[str]
    runs_attributed: int
    all_in: int = 0


class Once:
    """A source whose jobs are read once per run: the all-in sum reads runs the rows read."""

    def __init__(self, source: Source) -> None:
        self.source = source
        self.read: dict[str, list[Job]] = {}

    def merged_prs(self) -> list[Pr]:
        return self.source.merged_prs()

    def runs(self, created_from: str) -> list[Run]:
        return self.source.runs(created_from)

    def jobs(self, run: Run) -> list[Job]:
        if run.id not in self.read:
            self.read[run.id] = self.source.jobs(run)
        return self.read[run.id]


def _minutes(jobs: Sequence[Job]) -> tuple[int, int]:
    billable = sum(billed(j) for j in jobs if not self_hosted(j))
    return billable, sum(billed(j) for j in jobs if self_hosted(j))


def _jobs(source: Source, run: Run, zero: list[str]) -> list[Job]:
    jobs = source.jobs(run)
    if jobs:
        return jobs
    if run.conclusion in NEVER_STARTED:
        zero.append(run.id)
        return []
    raise CouldNotLook(
        f"run {run.id} ({run.workflow}, {run.event}, conclusion {run.conclusion or 'none'}) "
        f"answered no jobs — its minutes cannot be read, and a zero would lower the mean"
    )


def select(prs: Sequence[Pr], since: str, git: Git) -> list[Pr]:
    """Every merged PR whose merge commit descends from `since`, oldest merge first."""
    since = git.resolve(since)
    out = []
    for pr in sorted(prs, key=lambda p: (p.merged_at, p.number)):
        if not git.has(pr.merge_sha):
            raise CouldNotLook(
                f"PR #{pr.number}'s merge commit {pr.merge_sha[:9]} is not in this checkout — fetch"
            )
        if pr.merge_sha != since and git.descends(since, pr.merge_sha):
            out.append(pr)
    return out


def measure(
    since: str, window: Sequence[Pr], everyone: Sequence[Pr], runs: Sequence[Run], source: Source
) -> Report:
    """The window's rows, read from its runs and their jobs."""
    ordered = sorted(everyone, key=lambda p: (p.merged_at, p.number))
    first = min(window, key=lambda p: (p.merged_at, p.number))
    before = [p for p in ordered if p.merged_at < first.merged_at]
    span = (before[-1].merged_at if before else first.created_at, max(p.merged_at for p in window))
    sharing: dict[str, int] = {}
    for p in everyone:
        sharing[p.merge_sha] = sharing.get(p.merge_sha, 0) + 1
    heads = {p.head for p in everyone}
    merges = {p.merge_sha for p in everyone}
    zero: list[str] = []
    hosted = 0
    attributed: set[str] = set()
    source = Once(source)
    rows = []
    for pr in sorted(window, key=lambda p: (p.merged_at, p.number)):
        row = Row(number=pr.number, merge_sha=pr.merge_sha, fork=pr.fork)
        earlier = [
            p.merged_at for p in everyone if p.head == pr.head and p.merged_at < pr.merged_at
        ]
        floor = max(earlier) if earlier else ""
        mine = [
            r
            for r in runs
            if r.event == "pull_request"
            and r.branch == pr.head
            and floor < r.created_at <= pr.merged_at
        ]
        row.pr_runs = len(mine)
        row.pushes = len({r.head_sha for r in mine})
        for r in mine:
            jobs = _jobs(source, r, zero)
            row.full += is_full(jobs)
            row.cancelled += r.conclusion == "cancelled"
            row.failed += r.conclusion == "failure"
            for j in jobs:
                if self_hosted(j):
                    hosted += billed(j)
                else:
                    row.units[unit(j.name)] += billed(j)
            attributed.add(r.id)
        share = 1 / sharing[pr.merge_sha]
        for r in runs:
            if r.head_sha != pr.merge_sha or r.workflow in NIGHTLY_WORKFLOWS:
                continue
            if r.event == "push":
                jobs = _jobs(source, r, zero)
                row.main = "measured" if is_full(jobs) else "honoured"
                for j in jobs:
                    if self_hosted(j):
                        hosted += billed(j)
                    else:
                        row.units[unit(j.name)] += billed(j) * share
                attributed.add(r.id)
            elif r.workflow == PROOF_WORKFLOW and r.event == "workflow_run":
                billable, unbilled = _minutes(_jobs(source, r, zero))
                row.proof += billable * share
                hosted += unbilled
                attributed.add(r.id)
        rows.append(row)
    nightly = unmerged = unmerged_runs = direct = all_in = 0
    for r in runs:
        if span[0] < r.created_at <= span[1]:
            all_in += _minutes(_jobs(source, r, zero))[0]
    for r in runs:
        if r.id in attributed or not (span[0] < r.created_at <= span[1]):
            continue
        nightly_run = r.workflow in NIGHTLY_WORKFLOWS or r.event in (
            "schedule",
            "workflow_dispatch",
        )
        orphan_pr = r.event == "pull_request" and r.branch not in heads
        direct_main = r.event in ("push", "workflow_run") and r.head_sha not in merges
        if not (nightly_run or orphan_pr or direct_main):
            continue
        billable, unbilled = _minutes(_jobs(source, r, zero))
        hosted += unbilled
        if nightly_run:
            nightly += billable
        elif orphan_pr:
            unmerged += billable
            unmerged_runs += 1
        else:
            direct += billable
    return Report(
        since=since,
        window=len(window),
        rows=rows,
        span=span,
        nightly=nightly,
        unmerged=unmerged,
        unmerged_runs=unmerged_runs,
        direct_main=direct,
        self_hosted=hosted,
        zero_job_runs=zero,
        runs_attributed=len(attributed),
        all_in=all_in,
    )


def summary(report: Report) -> dict[str, Any]:
    """The window's mean, median and the lines beside them, as numbers."""
    totals = [r.total for r in report.rows]
    n = len(totals)
    mean = sum(totals) / n
    all_in = report.all_in / n
    return {
        "schema": "ci_cost/1",
        "since": report.since,
        "window": n,
        "span": list(report.span),
        "mean": round(mean, 1),
        "median": round(statistics.median(totals), 1),
        "goal": GOAL,
        "all_in": round(all_in, 1),
        "all_in_minutes": report.all_in,
        "verdict": "MET" if all_in <= GOAL else "ABOVE",
        "mean_verdict": "MET" if mean <= GOAL else "ABOVE",
        "nightly_minutes": report.nightly,
        "nightly_share_per_pr": round(report.nightly / n, 1),
        "runs_per_merged_pr": round(report.runs_attributed / n, 2),
        "pushes_per_pr": round(sum(r.pushes for r in report.rows) / n, 2),
        "full_pr_runs_per_pr": round(sum(r.full for r in report.rows) / n, 2),
        "unmerged_branch_minutes": report.unmerged,
        "unmerged_branch_runs": report.unmerged_runs,
        "direct_main_minutes": report.direct_main,
        "self_hosted_minutes": report.self_hosted,
        "zero_job_runs_never_started": report.zero_job_runs,
        "does_not_cover": list(DOES_NOT_COVER),
        "rows": [{**asdict(r), "total": round(r.total, 1)} for r in report.rows],
    }


def verdict_line(s: dict[str, Any]) -> str:
    """The per-PR mean, the diagnostic beside the all-in verdict."""
    return (
        f"ci-cost: {s['mean']:.0f} min/merged PR over {s['window']} PRs since {s['since'][:9]}"
        f" (diagnostic) — goal {GOAL}: {s['mean_verdict']}"
    )


def all_in_line(s: dict[str, Any]) -> str:
    """The one line the PM pastes at CLOSE: every billed minute of the window over its PRs."""
    return (
        f"all-in: {s['all_in']:.0f} min/merged PR over {s['window']} PRs since {s['since'][:9]}"
        f" — goal {GOAL}: {s['verdict']}"
    )


def table(report: Report, s: dict[str, Any]) -> list[str]:
    """The per-PR table and the lines under it."""
    head = ["pr", "merge", "runs", "full", "canc", "fail", "push", "main", "proof", *UNITS, "total"]
    out = ["  ".join(f"{h:>12}" if i > 1 else f"{h:<9}" for i, h in enumerate(head))]
    for r in report.rows:
        cells = [
            f"#{r.number}" + (" fork" if r.fork else ""),
            r.merge_sha[:9],
            str(r.pr_runs),
            str(r.full),
            str(r.cancelled),
            str(r.failed),
            str(r.pushes),
            r.main,
            f"{r.proof:.0f}",
            *(f"{r.units[u]:.0f}" for u in UNITS),
            f"{r.total:.0f}",
        ]
        out.append("  ".join(f"{c:>12}" if i > 1 else f"{c:<9}" for i, c in enumerate(cells)))
    out += [
        f"mean {s['mean']:.0f} · median {s['median']:.0f} min/merged PR over {s['window']} PRs "
        f"({s['span'][0]} → {s['span'][1]})",
        f"runs per merged PR {s['runs_per_merged_pr']} · pushes per PR {s['pushes_per_pr']} · "
        f"full PR runs per PR {s['full_pr_runs_per_pr']}",
        f"nightlies: {s['nightly_minutes']} min over the window = {s['nightly_share_per_pr']} "
        f"min/merged PR (not in the mean)",
        f"unmerged branches: {s['unmerged_branch_minutes']} min over "
        f"{s['unmerged_branch_runs']} runs (not in the mean)",
        f"main pushes no merged PR produced: {s['direct_main_minutes']} min (not in the mean)",
        f"self-hosted: {s['self_hosted_minutes']} min (unbilled, not in the mean)",
    ]
    if s["zero_job_runs_never_started"]:
        out.append(
            "counted 0, cancelled before any job: " + " ".join(s["zero_job_runs_never_started"])
        )
    return out


class GhSource:
    """The live source: every answer through `quality.djb.ledger._gh`, evidence in `sink`."""

    def __init__(self, root: pathlib.Path, sink: pathlib.Path) -> None:
        if shutil.which("gh") is None:
            raise CouldNotLook("no `gh` on PATH — the runs and their jobs are read through it")
        self.root, self.sink = root, sink
        self.calls = 0

    def _lines(self, *argv: str) -> list[dict[str, Any]]:
        from quality.djb.ledger import _gh

        self.calls += 1
        name = f"{self.calls:05d}"
        rc, out = _gh(self.root, self.sink, name, *argv)
        if rc != 0:
            raise CouldNotLook(
                f"`gh {' '.join(argv[:2])}` exited {rc} — the API refused or could not be reached "
                f"(its error: {self.sink / (name + '.err')})"
            )
        try:
            return [json.loads(line) for line in out.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise CouldNotLook(
                f"`gh {' '.join(argv[:2])}` answered something not JSON: {exc}"
            ) from exc

    def merged_prs(self) -> list[Pr]:
        """Every PR merged into main."""
        fields = "number,headRefName,mergeCommit,mergedAt,createdAt,isCrossRepository"
        found = self._lines(
            "pr", "list", "--state", "merged", "--base", "main", "--limit", "1000",
            "--json", fields, "--jq", ".[] | tojson",
        )  # fmt: skip
        return [
            Pr(
                number=p["number"],
                head=p["headRefName"],
                merge_sha=(p.get("mergeCommit") or {}).get("oid", ""),
                merged_at=p["mergedAt"],
                created_at=p["createdAt"],
                fork=bool(p.get("isCrossRepository")),
            )
            for p in found
        ]

    def runs(self, created_from: str) -> list[Run]:
        """Every run created at or after `created_from`."""
        found = self._lines(
            "api", "--paginate",
            f"repos/{{owner}}/{{repo}}/actions/runs?per_page=100&created=%3E%3D{created_from}",
            "--jq", ".workflow_runs[] | tojson",
        )  # fmt: skip
        return [
            Run(
                id=str(r["id"]),
                created_at=r["created_at"],
                event=r["event"],
                conclusion=r.get("conclusion") or "",
                branch=r.get("head_branch") or "",
                workflow=r["name"],
                head_sha=r["head_sha"],
            )
            for r in found
        ]

    def jobs(self, run: Run) -> list[Job]:
        """Every job of every attempt of `run`; a job still running is could-not-look."""
        found = self._lines(
            "api", "--paginate",
            f"repos/{{owner}}/{{repo}}/actions/runs/{run.id}/jobs?per_page=100&filter=all",
            "--jq", ".jobs[] | tojson",
        )  # fmt: skip
        if not run.conclusion:
            raise CouldNotLook(
                f"run {run.id} is still queued or in progress — measure after it ends"
            )
        out = []
        for j in found:
            if j.get("status") not in (None, "completed") and not j.get("started_at"):
                raise CouldNotLook(
                    f"run {run.id}'s job `{j['name']}` is still queued or in progress — measure"
                    " after it ends"
                )
            if j.get("started_at") and not j.get("completed_at"):
                raise CouldNotLook(
                    f"run {run.id}'s job `{j['name']}` is still running — measure after it ends"
                )
            out.append(
                Job(
                    name=j["name"],
                    labels=tuple(j.get("labels") or ()),
                    started_at=j.get("started_at") or "",
                    completed_at=j.get("completed_at") or "",
                    conclusion=j.get("conclusion") or "",
                )
            )
        return out


class CheckoutGit:
    """The checkout's own git."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def _ok(self, *argv: str) -> bool:
        return (
            subprocess.run(["git", "-C", str(self.root), *argv], capture_output=True).returncode
            == 0
        )

    def resolve(self, ref: str) -> str:
        """The full sha `ref` names; a ref the checkout lacks is could-not-look."""
        done = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise CouldNotLook(f"--since {ref} is not a commit this checkout has")
        return done.stdout.strip()

    def has(self, sha: str) -> bool:
        """Whether the checkout holds `sha` as a commit."""
        return bool(sha) and self._ok("cat-file", "-e", f"{sha}^{{commit}}")

    def descends(self, since: str, sha: str) -> bool:
        """Whether `sha` has `since` as an ancestor."""
        return self._ok("merge-base", "--is-ancestor", since, sha)


def run(
    argv: Sequence[str],
    source: Source | None = None,
    git: Git | None = None,
    write: Callable[[str], None] = print,
) -> int:
    """Read, measure and print; the exit status is the verdict."""
    ap = argparse.ArgumentParser(prog="scripts/ci_cost.py")
    ap.add_argument("--since", required=True, help="the sha whose descendants' merges are measured")
    ap.add_argument("--window", type=int, default=WINDOW, help="the trailing merged PRs judged")
    ap.add_argument("--json", action="store_true", help="print the numbers as one JSON document")
    args = ap.parse_args(argv)
    if args.window < 1:
        raise CouldNotLook(f"--window {args.window} judges nothing")
    if source is None:
        source = GhSource(ROOT, pathlib.Path(tempfile.mkdtemp(prefix="ci_cost-")))
    git = git or CheckoutGit(ROOT)
    everyone = source.merged_prs()
    since = git.resolve(args.since)
    since_prs = select(everyone, since, git)
    if len(since_prs) < args.window:
        raise CouldNotLook(
            f"not enough data — {len(since_prs)} merged PRs since {since[:9]}, the window is "
            f"{args.window}"
        )
    window = since_prs[-args.window :]
    created_from = (min(_t(p.created_at) for p in window) - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    report = measure(since, window, everyone, source.runs(created_from), source)
    s = summary(report)
    if args.json:
        write(json.dumps(s, indent=2))
    else:
        for line in table(report, s):
            write(line)
        write(verdict_line(s))
        write(all_in_line(s))
    return 0 if s["verdict"] == "MET" else 1


def main(argv: Sequence[str] | None = None) -> int:
    """The command line's door."""
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))


if __name__ == "__main__":
    sys.exit(main())
