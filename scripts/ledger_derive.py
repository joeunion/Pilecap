"""The dispatch ledger, derived from briefs, reports, git and pull requests — never typed."""

# does-not-cover: a brief edited after dispatch — Sent is the dispatch, the text today's.
# does-not-cover: a dispatch message not naming the rung by `dispatch` — Sent is the brief's.
# does-not-cover: a builder's own commit touching a ledger path — `--turns` counts it as the PM's.
# does-not-cover: a pre-block brief's fields are inferred from title and text, a guess.
# does-not-cover: a resumed standing agent (a message, no brief) — its report still moves.
# does-not-cover: a rung re-cut onto a second branch — the brief's `branch:` names one.
# does-not-cover: a report committed by the PM after the agent returned — Returned is that commit.
# does-not-cover: `gh` at `--check` — the check is tree and local git only, no network.
# does-not-cover: a shallow clone's dates — `--check` says it could not date, and judges nothing.

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import zoneinfo
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _path in (str(_ROOT), str(_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from ledger_check import DERIVED_ON  # noqa: E402

from quality.could_not_look import CouldNotLook  # noqa: E402

#: The brief header block's one closed grammar; CER-3's preamble cites it by this name.
BRIEF_FIELDS = ("rung", "role", "branch", "report", "verifies")
ROLES = ("builder", "verifier", "lead", "reader", "surveyor")
#: Briefs first committed on or after this instant carry the block; earlier ones are inferred.
CLOCK = zoneinfo.ZoneInfo("America/Los_Angeles")
ARMED_ON = DERIVED_ON.replace(tzinfo=CLOCK)
PRODUCT = "docs/product"
LEDGER_PATHS = (f"{PRODUCT}/in-flight.md", f"{PRODUCT}/queue-detail.md", f"{PRODUCT}/queue.md")
HEADER = ("#", "Task", "Role", "State", "Sent", "Returned", "Result")
FIRST_CYCLE = (
    "the first rung's report goes at docs/product/reports/<cycle>/<rung>.md, "
    "the path its brief's `report:` names"
)
NO_CYCLE = f"no cycle yet: docs/product/reports/ holds no cycle directory — {FIRST_CYCLE}"
RESULT_CHARS = 200
TURNS_GOAL = 2.0

EPILOG = """\
A row is one brief under docs/product/briefs/: Sent is its dispatch commit (the
first ledger commit at or after the brief's first commit whose message names the
rung in a clause that says "dispatch"; else the brief's first commit), Returned its report's
first commit (main, or the pull request's branch), State the pull request gh
answers for the brief's `branch:`, Result the report's first line. A brief opens
with the fenced header block BRIEF_FIELDS names, straight after its title line; a
brief first committed before ARMED_ON with no block is read by inference from its
title and text; an uncommitted file is dated now.
There is no shebang: callers run it through the checkout's own interpreter, as
scripts/loop_metrics.py says. It writes nothing.

--turns: the ledger line is every non-merge commit HEAD has and --since does not
that touches in-flight.md, queue-detail.md or queue.md. A builder rung is live
from its dispatch commit THROUGH its landing commit — the first ledger commit at
or after its PR's merge whose message or added lines name the rung or `#<pr>` —
and live until now while it has none. Each ledger commit is split 1/k over the
k builder rungs live at it (verifier, lead and reader briefs are not rungs); the
mean is over the n landed builder rungs; goal ≤ 2 (V-CER1, 2026-10-24).

exit 0 every brief read, a tree with no cycle under reports/ yet included · 1 a
finding (--check, --stale) · 2 could not look (a brief with no block after
ARMED_ON, an unreadable file, a reports/ that is a file, a brief naming no
`report:` before the first cycle, gh absent or refusing, --offline's builder
rows). 2 outranks 1.
"""
_FENCE = "```"
_CLAUSE = re.compile(r"[;,()\n]|—")
_FIELD_LINE = re.compile(r"^([a-z]+):\s*(.*?)\s*(?:#.*)?$")
_TITLE = re.compile(r"^#\s+(\S+(?:\s+/\s+[A-Za-z0-9-]+)?)\s*(?:[—–:-]+\s*)?(.*)$")
_REPORT = re.compile(r"\b(?:docs/product/)?(reports/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.md)\b")
_BRANCH = re.compile(r"branch\s+`(pm/[A-Za-z0-9._/-]+)`")
_VERIFIES = re.compile(r"\bverify\s+([A-Za-z][A-Za-z0-9-]*[A-Za-z0-9])", re.IGNORECASE)
_PLAN = re.compile(r"\b(?:docs/product/)?(cycles/[A-Za-z0-9_.-]+\.md)\b")


@dataclasses.dataclass
class Brief:
    """One brief as the derivation reads it: its declared or inferred header fields."""

    path: str
    rung: str
    task: str
    role: str
    branch: str
    report: str
    verifies: str
    blocked: bool
    sent: int | None


@dataclasses.dataclass
class Pull:
    """One pull request as `gh pr list` answers it."""

    number: int
    state: str
    head: str
    merged_at: int | None
    merge_sha: str
    updated_at: int | None
    checks: str = ""


@dataclasses.dataclass
class Row:
    """One derived ledger row, before it is printed."""

    brief: Brief
    state: str
    sent: int | None
    returned: int | None
    result: str
    pull: Pull | None
    stamps: str = ""


def stamp(epoch: int | None) -> str:
    """`YYYY-MM-DD HH:MM` on the one clock, or the em dash for a stage not reached."""
    if epoch is None:
        return "—"
    return dt.datetime.fromtimestamp(epoch, CLOCK).strftime("%Y-%m-%d %H:%M")


def git(root: pathlib.Path, *argv: str) -> tuple[int, str]:
    """`(rc, stdout)` of one local git call; 127 when git cannot be started."""
    try:
        done = subprocess.run(
            ["git", *argv],
            cwd=root,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return 127, ""
    return done.returncode, done.stdout


def first_adds(root: pathlib.Path, ref: str = "HEAD") -> dict[str, tuple[int, str]]:
    """`path → (epoch, sha)` of each brief, report and plan's first adding commit on `ref`."""
    rc, out = git(
        root,
        "log",
        "--no-renames",
        "--diff-filter=A",
        "--name-only",
        "--format=%x00%ct %H",
        ref,
        "--",
        f"{PRODUCT}/briefs",
        f"{PRODUCT}/reports",
        f"{PRODUCT}/cycles",
    )
    if rc != 0:
        raise CouldNotLook(f"`git log` over {PRODUCT} answered {rc} at {root} — nothing dated.")
    found: dict[str, tuple[int, str]] = {}
    for chunk in out.split("\x00")[1:]:
        head, *names = chunk.strip().splitlines()
        epoch, sha = head.split()
        for name in filter(None, names):
            if name not in found or int(epoch) < found[name][0]:
                found[name] = (int(epoch), sha)
    return found


@dataclasses.dataclass
class LedgerCommit:
    """One non-merge commit touching a ledger path: its sha, time and message."""

    sha: str
    when: int
    message: str


def ledger_commits(root: pathlib.Path) -> list[LedgerCommit]:
    """Every non-merge commit HEAD reaches that touches a ledger path, oldest first."""
    rc, out = git(
        root, "log", "--no-merges", "--format=%x00%H %ct%n%B", "HEAD", "--", *LEDGER_PATHS
    )
    if rc != 0:
        raise CouldNotLook(f"`git log` over the ledger paths answered {rc} at {root}")
    found = []
    for chunk in out.split("\x00")[1:]:
        head, _, message = chunk.partition("\n")
        sha, when = head.split()
        found.append(LedgerCommit(sha, int(when), message))
    return sorted(found, key=lambda c: c.when)


def _names(text: str, *ids: str) -> bool:
    return any(
        re.search(rf"(?<![A-Za-z0-9-]){re.escape(i)}(?![A-Za-z0-9-])", text) for i in ids if i
    )


def dispatched(brief: Brief, line: list[LedgerCommit]) -> int | None:
    """The dispatch commit's time: the first ledger commit since the brief naming it, else Sent."""
    if brief.sent is None:
        return None
    for commit in line:
        if commit.when < brief.sent:
            continue
        for clause in _CLAUSE.split(commit.message):
            if "dispatch" in clause.lower() and _names(clause, brief.rung):
                return commit.when
    return brief.sent


def landing(root: pathlib.Path, row: Row, line: list[LedgerCommit]) -> int | None:
    """The landing commit's time: the first ledger commit since the merge naming the rung or PR."""
    pull = row.pull
    if row.brief.role != "builder" or pull is None or pull.merged_at is None:
        return None
    ids = (row.brief.rung, f"#{pull.number}")
    for commit in line:
        if commit.when < pull.merged_at:
            continue
        if _names(commit.message, *ids):
            return commit.when
        rc, diff = git(root, "show", "--format=", "-U0", commit.sha, "--", *LEDGER_PATHS)
        added = "\n".join(x for x in diff.splitlines() if x.startswith("+"))
        if rc == 0 and _names(added, *ids):
            return commit.when
    return None


def shallow(root: pathlib.Path) -> bool:
    """True when this clone's history is cut short, so a first commit is not a first commit."""
    return git(root, "rev-parse", "--is-shallow-repository")[1].strip() == "true"


def read_text(path: pathlib.Path) -> str:
    """The file's text, or could-not-look naming it."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{path}: could not be read — {exc}") from exc


def header_block(text: str) -> dict[str, str] | None:
    """The fenced block straight after the title line, as fields; None when the brief has none."""
    lines = text.splitlines()
    rest = [line for line in lines[1:]]
    while rest and not rest[0].strip():
        rest.pop(0)
    if not rest or rest[0].strip() != _FENCE:
        return None
    fields: dict[str, str] = {}
    for line in rest[1:]:
        if line.strip() == _FENCE:
            return fields
        hit = _FIELD_LINE.match(line.strip())
        if not hit or hit.group(1) not in BRIEF_FIELDS:
            raise CouldNotLook(
                f"the header block line `{line.strip()}` is not a BRIEF_FIELDS field"
            )
        fields[hit.group(1)] = hit.group(2).strip()
    raise CouldNotLook("the header block's fence never closes")


def infer_role(rung: str, h1: str) -> str:
    """The role a pre-block brief's id and title name; builder when they name none."""
    low = h1.lower()
    if rung.upper().startswith("V-") or "verifier" in low:
        return "verifier"
    if rung.upper().startswith("LEAD-"):
        return "lead"
    for role in ("reader", "surveyor"):
        if re.search(rf"\b{role}\b", low):
            return role
    if "(lead" in low or " lead," in low:
        return "lead"
    return "builder"


def read_brief(
    product: pathlib.Path,
    rel: str,
    cycle: str | None,
    sent: int | None,
    plans: dict[str, int],
    reports: dict[str, int],
) -> Brief:
    """One brief, by its block or (sent before ARMED_ON) by inference; could-not-look otherwise."""
    path = product / "briefs" / rel
    text = read_text(path)
    h1 = text.splitlines()[0] if text.strip() else ""
    title = _TITLE.match(h1)
    where = f"{PRODUCT}/briefs/{rel}"
    if not title:
        raise CouldNotLook(f"{where}: the first line is not a title (`# <ID> — <task>`)")
    stem = rel.removesuffix(".md")
    try:
        block = header_block(text)
    except CouldNotLook as exc:
        raise CouldNotLook(f"{where}: {exc}") from exc
    default_report = f"{PRODUCT}/reports/{cycle}/{stem}.md" if cycle else ""
    if block is None:
        if (time.time() if sent is None else sent) >= ARMED_ON.timestamp():
            raise CouldNotLook(
                f"{where}: no header block (`{_FENCE}` + {', '.join(BRIEF_FIELDS)}) after its title"
                f" — a brief sent on or after {ARMED_ON:%Y-%m-%d} carries one"
            )
        rung = re.sub(r"\s+", "", title.group(1))
        role = infer_role(rung, h1)
        branch = ""
        if role == "builder":
            hit = _BRANCH.search(text)
            branch = hit.group(1) if hit else ""
        report = default_report
        if (
            role in ("reader", "surveyor", "verifier")
            and not (product.parent.parent / report).is_file()
        ):
            named = [
                f"{PRODUCT}/{r}"
                for r in _REPORT.findall(text)
                if reports.get(r, 1 << 62) >= (sent or 0)
            ]
            report = named[0] if named else report
        if role == "lead":
            later = [
                f"{PRODUCT}/{p}" for p in _PLAN.findall(text) if plans.get(p, 0) >= (sent or 0)
            ]
            report = later[0] if later else ""
        verifies = ""
        if role == "verifier":
            hit = _VERIFIES.search(h1)
            verifies = hit.group(1).upper() if hit else ""
        return Brief(where, rung, title.group(2), role, branch, report, verifies, False, sent)
    role = block.get("role", "")
    if role not in ROLES:
        raise CouldNotLook(f"{where}: `role: {role}` is not one of {', '.join(ROLES)}")
    if role == "builder" and not block.get("branch"):
        raise CouldNotLook(f"{where}: a builder brief names no `branch:` — its PR cannot be found")
    if not (block.get("report") or default_report):
        raise CouldNotLook(f"{where}: names no `report:` and there is no cycle yet — {FIRST_CYCLE}")
    return Brief(
        where,
        block.get("rung") or stem.upper(),
        title.group(2),
        role,
        block.get("branch", ""),
        block.get("report") or default_report,
        block.get("verifies", "").upper(),
        True,
        sent,
    )


def default_cycle(product: pathlib.Path) -> str | None:
    """The newest reports directory's name; None when there is none; could-not-look on a file."""
    reports = product / "reports"
    if reports.exists() and not reports.is_dir():
        raise CouldNotLook(f"{reports} is not a directory — no cycle can be read from it")
    found = sorted(p.name for p in reports.glob("*") if p.is_dir())
    return found[-1] if found else None


def read_briefs(
    root: pathlib.Path, adds: dict[str, tuple[int, str]], cycle: str | None
) -> list[Brief]:
    """Every brief under the product's briefs/, in Sent order; uncommitted ones last."""
    product = root / PRODUCT
    plans = {k.removeprefix(f"{PRODUCT}/"): v[0] for k, v in adds.items() if "/cycles/" in k}
    reports = {k.removeprefix(f"{PRODUCT}/"): v[0] for k, v in adds.items() if "/reports/" in k}
    briefs = []
    for path in sorted((product / "briefs").glob("*.md")):
        if path.name == "README.md" or path.name.startswith("_"):
            continue
        sent = adds.get(f"{PRODUCT}/briefs/{path.name}", (None, ""))[0]
        briefs.append(read_brief(product, path.name, cycle, sent, plans, reports))
    return sorted(briefs, key=lambda b: (b.sent is None, b.sent or 0, b.path))


def first_line(text: str) -> str:
    """The text's first non-blank line, its heading marks and pipes taken out, truncated."""
    for line in text.splitlines():
        if line.strip():
            text = line.strip().lstrip("#").strip().replace("|", "/")
            return text if len(text) <= RESULT_CHARS else text[: RESULT_CHARS - 1] + "…"
    return ""


def branch_ref(root: pathlib.Path, branch: str) -> str | None:
    """The local name for the branch's tip — the remote's copy first; None when neither exists."""
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        if git(root, "rev-parse", "--verify", "--quiet", ref)[0] == 0:
            return ref
    return None


def report_added(
    root: pathlib.Path, brief: Brief, adds: dict[str, tuple[int, str]], ref: str | None
) -> int | None:
    """The report's first commit on main, else on the branch; None when it has none."""
    if brief.report in adds:
        return adds[brief.report][0]
    if ref is None:
        return None
    rc, out = git(
        root, "log", "--no-renames", "--diff-filter=A", "--format=%ct", ref, "--", brief.report
    )
    times = [int(t) for t in out.split()] if rc == 0 else []
    return min(times) if times else None


def report_text(root: pathlib.Path, brief: Brief, ref: str | None) -> str:
    """The report as the tree holds it, else as the branch does; empty when neither can show it."""
    path = root / brief.report
    if path.is_file():
        return read_text(path)
    if ref is None:
        return ""
    rc, out = git(root, "show", f"{ref}:{brief.report}")
    return out if rc == 0 else ""


def _epoch(value: str | None) -> int | None:
    if not value:
        return None
    return int(dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _checks(rollup: list[dict[str, Any]]) -> str:
    states = [
        str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup
    ]
    if not states:
        return "no checks"
    bad = sum(
        s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED") for s in states
    )
    done = sum(s in ("SUCCESS", "NEUTRAL", "SKIPPED") for s in states)
    if bad:
        return f"red {bad}/{len(states)}"
    if done < len(states):
        return f"pending {len(states) - done}/{len(states)}"
    return "green"


def pulls(root: pathlib.Path, gh: str, branches: set[str]) -> dict[str, Pull]:
    """`head ref → newest pull request` for the named branches; could-not-look when `gh` cannot."""
    if not branches:
        return {}
    from quality.djb.ledger import _gh

    with tempfile.TemporaryDirectory(prefix="ledger-derive-") as sink:
        fields = "number,state,headRefName,mergedAt,mergeCommit,updatedAt"
        rc, out = _gh(
            root,
            pathlib.Path(sink),
            "list",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "500",
            "--json",
            fields,
            gh=gh,
        )
        if rc != 0:
            raise CouldNotLook(f"`gh pr list` answered {rc} — no pull request state was read")
        try:
            listed = json.loads(out)
        except json.JSONDecodeError as exc:
            raise CouldNotLook(f"`gh pr list` answered no JSON — {exc}") from exc
        found: dict[str, Pull] = {}
        for item in listed:
            head = str(item.get("headRefName", ""))
            if head not in branches or (head in found and found[head].number > item["number"]):
                continue
            merge = item.get("mergeCommit") or {}
            found[head] = Pull(
                int(item["number"]),
                str(item.get("state", "")).upper(),
                head,
                _epoch(item.get("mergedAt")),
                str(merge.get("oid", "")),
                _epoch(item.get("updatedAt")),
            )
        for pull in found.values():
            if pull.state != "OPEN":
                continue
            rc, out = _gh(
                root,
                pathlib.Path(sink),
                f"view-{pull.number}",
                "pr",
                "view",
                str(pull.number),
                "--json",
                "statusCheckRollup",
                gh=gh,
            )
            if rc != 0:
                raise CouldNotLook(f"`gh pr view {pull.number}` answered {rc} — its checks unread")
            pull.checks = _checks(json.loads(out).get("statusCheckRollup") or [])
    return found


def state_of(brief: Brief, returned: int | None, pull: Pull | None, offline: bool) -> str:
    """The State cell: sent · returned · pr #n open · merged <sha8> <t> · closed #n · plan."""
    if brief.role == "lead":
        return "plan written" if returned is not None else "sent"
    if brief.role != "builder":
        return "returned" if returned is not None else "sent"
    if offline:
        return ("returned · " if returned is not None else "") + "pr: could not look"
    if pull is None:
        return "returned" if returned is not None else "sent"
    if pull.state == "MERGED":
        return f"merged {pull.merge_sha[:8]} {stamp(pull.merged_at)}"
    if pull.state == "CLOSED":
        return f"closed #{pull.number}"
    lead = "returned · " if returned is not None else ""
    return f"{lead}pr #{pull.number} open · {pull.checks}"


def coding(
    root: pathlib.Path, pull: Pull | None, ref: str | None, sent: int | None
) -> tuple[str, str]:
    """`(commits, fold)`: the branch's non-merge commits since Sent, first..last; its last fold."""
    if pull is not None and pull.state == "MERGED" and pull.merge_sha:
        span = f"{pull.merge_sha}^1..{pull.merge_sha}^2"
    elif ref is not None:
        span = f"origin/main..{ref}"
    else:
        return "—", "—"
    rc, out = git(root, "log", "--no-merges", "--format=%ct", span)
    times = sorted(int(t) for t in out.split() if int(t) >= (sent or 0)) if rc == 0 else []
    commits = f"{stamp(times[0])}..{stamp(times[-1])}" if times else "—"
    rc, out = git(root, "log", "--merges", "--format=%ct", span)
    folds = sorted(int(t) for t in out.split() if int(t) >= (sent or 0)) if rc == 0 else []
    return commits, stamp(folds[-1]) if folds and times else "—"


def derive(
    root: pathlib.Path,
    *,
    since: set[str] | None,
    cycle: str | None,
    gh: str,
    offline: bool,
    with_stamps: bool,
) -> list[Row]:
    """Every row whose brief was first committed inside `since` (or not yet), in Sent order."""
    adds = first_adds(root)
    line = ledger_commits(root)
    briefs = read_briefs(root, adds, cycle or default_cycle(root / PRODUCT))
    picked = [b for b in briefs if since is None or adds.get(b.path, (0, ""))[1] in since | {""}]
    refs = {b.branch: branch_ref(root, b.branch) for b in picked if b.branch}
    found = {} if offline else pulls(root, gh, {b.branch for b in picked if b.branch})
    returned = {b.path: report_added(root, b, adds, refs.get(b.branch)) for b in briefs}
    met = {
        b.verifies: returned[b.path]
        for b in briefs
        if b.role == "verifier" and b.verifies and returned[b.path] is not None
    }
    rows = []
    for brief in picked:
        pull = found.get(brief.branch)
        back = returned[brief.path]
        result = (
            "—" if back is None else first_line(report_text(root, brief, refs.get(brief.branch)))
        )
        sent = dispatched(brief, line)
        row = Row(brief, state_of(brief, back, pull, offline), sent, back, result, pull)
        if with_stamps:
            merged = (
                f"{pull.merge_sha[:8]} {stamp(pull.merged_at)}"
                if pull is not None and pull.state == "MERGED"
                else "—"
            )
            commits, fold = coding(root, pull, refs.get(brief.branch), sent)
            row.stamps = (
                f"stamps: sent={stamp(sent)} done={stamp(back)} "
                f"met={stamp(met.get(brief.rung.upper()))} merged={merged} "
                f"commits={commits} fold={fold} loop=— held=— train=—"
            )
        rows.append(row)
    return rows


def table(rows: list[Row]) -> list[str]:
    """The seven-cell table, header first; a `--stamps` row carries its stamps in Result."""
    out = ["| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
    for row in rows:
        result = f"{row.result} {row.stamps}".strip() if row.stamps else row.result
        cells = (
            row.brief.rung,
            row.brief.task.replace("|", "/"),
            row.brief.role,
            row.state,
            stamp(row.sent) if row.sent is not None else "uncommitted",
            stamp(row.returned),
            result,
        )
        out.append("| " + " | ".join(cells) + " |")
    return out


def check(root: pathlib.Path, cycle: str | None = None) -> tuple[list[str], str]:
    """`(findings, coverage line)` over briefs and reports: tree and local git, no network."""
    product = root / PRODUCT
    undated = shallow(root)
    adds: dict[str, tuple[int, str]] = {} if undated else first_adds(root)
    cycle = cycle or default_cycle(product)
    armed = ARMED_ON.timestamp()
    briefs = read_briefs(root, adds, cycle) if not undated else []
    findings: list[str] = []
    named: set[str] = set()
    for brief in briefs:
        named.add(brief.report)
        if not brief.blocked:
            continue
        if brief.report and not brief.report.startswith(
            (f"{PRODUCT}/reports/", f"{PRODUCT}/cycles/")
        ):
            findings.append(
                f"{brief.path}: `report: {brief.report}` is outside reports/ and cycles/"
            )
        if brief.role == "builder" and not brief.branch.startswith("pm/"):
            findings.append(f"{brief.path}: `branch: {brief.branch}` has no `pm/` prefix")
    reports = sorted(
        f"{PRODUCT}/reports/{p.relative_to(product / 'reports').as_posix()}"
        for p in (product / "reports").glob("*/*.md")
    )
    judged = 0
    for report in reports:
        when = adds.get(report, (int(time.time()), ""))[0]
        if undated or when < armed:
            continue
        judged += 1
        if report not in named:
            findings.append(f"{report}: an orphan report — no brief names it")
    if undated:
        line = "briefs and reports NOT judged: a shallow clone cannot date a first commit"
    else:
        line = f"{len(briefs)} brief(s) read, {judged} report(s) armed on {ARMED_ON:%Y-%m-%d}"
    return findings, line


def stale(rows: list[Row], hours: float, now: float, legacy: bool) -> list[Row]:
    """Every `sent` row past the window, no report, no PR activity; pre-block only if `legacy`."""
    edge = now - hours * 3600
    out = []
    for row in rows:
        if not (row.brief.blocked or legacy):
            continue
        if row.returned is not None or row.sent is None or row.sent > edge:
            continue
        if row.pull is not None and row.pull.updated_at is not None and row.pull.updated_at > edge:
            continue
        if row.pull is not None and row.pull.state != "OPEN":
            continue
        out.append(row)
    return out


def turns(
    root: pathlib.Path, rows: list[Row], since: set[str], now: int
) -> tuple[dict[str, float], dict[str, bool], int]:
    """`(path → 1/k share, path → landed, ledger commits no builder rung was live at)`."""
    line = ledger_commits(root)
    spans: dict[str, tuple[int, int]] = {}
    closed: dict[str, bool] = {}
    for row in rows:
        if row.brief.role != "builder" or row.sent is None:
            continue
        end = landing(root, row, line)
        spans[row.brief.path] = (row.sent, end if end is not None else now)
        closed[row.brief.path] = end is not None
    share = dict.fromkeys(spans, 0.0)
    orphans = 0
    for commit in line:
        if commit.sha not in since:
            continue
        live = [path for path, (start, end) in spans.items() if start <= commit.when <= end]
        if not live:
            orphans += 1
        for path in live:
            share[path] += 1 / len(live)
    return share, closed, orphans


def window(root: pathlib.Path, sha: str) -> set[str]:
    """The commit `sha` and every commit HEAD has that it does not; could-not-look on a stranger."""
    rc, out = git(root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if rc != 0 or not out.strip():
        raise CouldNotLook(f"`{sha}` is not a commit this checkout knows")
    rc, listed = git(root, "rev-list", f"{sha}..HEAD")
    if rc != 0:
        raise CouldNotLook(f"`git rev-list {sha}..HEAD` answered {rc}")
    return {out.strip(), *listed.split()}


def main(argv: list[str]) -> int:
    """Exit 0 every brief read · 1 a finding · 2 could not look; 2 outranks 1."""
    parser = argparse.ArgumentParser(
        prog="ledger_derive.py",
        description=(__doc__ or "").splitlines()[0],
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--stale", action="store_true")
    mode.add_argument("--turns", action="store_true")
    parser.add_argument("--since")
    parser.add_argument("--cycle")
    parser.add_argument("--hours", type=float)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--stamps", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--gh", default="gh")
    parser.add_argument("--root", default=".")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.stale and args.hours is None:
        parser.error("--stale needs --hours N")
    if args.turns and not args.since:
        parser.error("--turns needs --since <sha>")
    root = pathlib.Path(args.root).resolve()
    started = time.time()
    try:
        if args.check:
            findings, line = check(root, args.cycle)
            for finding in findings:
                print(f"!! ledger-derive: {finding}")
            verdict = f"{len(findings)} finding(s)" if findings else "clean"
            print(f"== ledger-derive --check: {verdict} · {line} · {time.time() - started:.3f}s")
            return 1 if findings else 0
        since = window(root, args.since) if args.since else None
        cycle = args.cycle or default_cycle(root / PRODUCT)
        rows = derive(
            root,
            since=since,
            cycle=cycle,
            gh=args.gh,
            offline=args.offline,
            with_stamps=args.stamps,
        )
    except CouldNotLook as exc:
        print(f"!! COULD NOT LOOK: {exc}", file=sys.stderr)
        return 2
    now = int(time.time())
    if args.turns:
        assert since is not None  # noqa: S101 — --turns requires --since, refused above
        try:
            share, landed, orphans = turns(root, rows, since, now)
        except CouldNotLook as exc:
            print(f"!! COULD NOT LOOK: {exc}", file=sys.stderr)
            return 2
        closed = [r for r in rows if landed.get(r.brief.path)]
        if args.verbose:
            for row in rows:
                if row.brief.path in share:
                    mark = "landed" if landed[row.brief.path] else "live"
                    print(f"{row.brief.rung}: {share[row.brief.path]:.2f} ({mark})")
            print(f"   {orphans} ledger commit(s) with no builder rung live")
        mean = sum(share[r.brief.path] for r in closed) / len(closed) if closed else 0.0
        verdict = "MET" if closed and mean <= TURNS_GOAL else "ABOVE"
        print(
            f"pm-turns: {mean:.2f} commits/landed rung over {len(closed)} rungs since "
            f"{args.since[:8]} — goal {TURNS_GOAL:g}: {verdict}"
        )
        return 0
    if args.stale:
        late = stale(rows, args.hours, now, legacy=since is not None)
        unjudged = 0 if since is not None else sum(not r.brief.blocked for r in rows)
        for row in late:
            print(
                f"stale: {row.brief.rung} sent {stamp(row.sent)}, no report, no PR activity in "
                f"{args.hours:g} h — a stall is the agent list's to confirm"
            )
        if unjudged:
            print(f"   {unjudged} pre-block brief(s) not judged — name a window with --since")
        print(f"== ledger-derive --stale: {len(late)} row(s) past {args.hours:g} h")
        return 1 if late else 0
    if args.json:
        print(json.dumps([_as_json(row) for row in rows], indent=2))
    else:
        print("\n".join(table(rows)))
        if cycle is None:
            print(NO_CYCLE)
    return 2 if args.offline and any(r.brief.role == "builder" for r in rows) else 0


def _as_json(row: Row) -> dict[str, Any]:
    return {
        "rung": row.brief.rung,
        "task": row.brief.task,
        "role": row.brief.role,
        "state": row.state,
        "sent": stamp(row.sent),
        "returned": stamp(row.returned),
        "result": row.result,
        "brief": row.brief.path,
        "report": row.brief.report,
        "pr": row.pull.number if row.pull else None,
        "stamps": row.stamps or None,
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
