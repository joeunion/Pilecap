"""The velocity reader: the cost-baseline row DERIVED, never typed.

    .venv/bin/python scripts/loop_metrics.py [--in-flight F] [--readouts F]
                                             [--bank-logs DIR] [--loop-logs DIR]
                                             [--git REPO] [--cycle NAME] [--json]

It reads four things and writes nothing:

  * the dispatch ledger's stamps  — the two velocity clocks
  * the readouts file             — the cost-baseline table's own header
  * the bank logs                 — banks launched, pushed, green, and their legs
  * the loop logs                 — the inner loop, by change class

and prints the cost-baseline row for a person to paste. THERE IS NO SHEBANG,
DELIBERATELY: `python3` off PATH is some other environment's interpreter — on a
Linux verifier box it is the system 3.9, where this file's syntax is a
`SyntaxError` reported as a finding about the ledger. Every caller invokes it
through the checkout's own interpreter (`checkout_python`, scripts/gate_refuse.sh),
and a file with no shebang cannot be invoked any other way by accident.

WHY IT EXISTS. The numbers under `readouts.md` § COST BASELINE were typed by
hand, from a usage screen and from memory. A typed number cannot be disagreed
with: it has no input anybody can re-read, so a number that drifted and a number
that was always wrong look identical a week later, and the levers they are meant
to measure are argued about instead of measured. Deriving them moves the failure
mode somewhere a check can stand: a derivation can be WRONG, and wrong in two
ways that both look like an answer — it can read an impossible stamp and print a
plausible minute count from it, and it can silently skip the rows that carry no
stamps and report a median over the convenient half of the ledger. Both are
refused here: a malformed stamp is exit 2 naming the row and the field, and an
unstamped row is COUNTED and NAMED and never dropped.

THE STAMP GRAMMAR, which is the contract this reader holds the ledger to. Every
dispatch row's last cell carries

    stamps: sent=<t> done=<t> met=<t> merged=<sha8> <t> pushed=<t> staged=<t>

where <t> is `YYYY-MM-DD HH:MM`, or a bare `HH:MM` inheriting the date of the
nearest dated field before it in the same cell, or an em dash for a stage that
was not reached. ONE CLOCK, PDT — an unlabelled time is PDT and a time labelled
with any other zone is exit 2, because two clocks in one ledger (CEST rows
beside unlabelled ones) is a measured defect of the rows this grammar replaces
and normalising them after the fact is guesswork wearing arithmetic.

`pushed` and `staged` are WAVE stamps: they are written once, on the wave's own
row (`| WAVE-<n> | … |`), and inherited by the rungs of that wave. WHICH RUNGS
IS DERIVED FROM THE CLOCKS THEMSELVES rather than from a second list that would
have to be kept in step: a rung belongs to the first wave whose `pushed` stamp
is at or after the rung's `merged` stamp. A rung merged after every wave that
was pushed is not yet pushed, and says so.

THE TWO CLOCKS, and why they are measured where they are. Stage 3 (builder done
→ verified met) is PER RUNG. Stages 4 and 5 (the wave's last met → pushed →
staged) are PER WAVE, because the push is per wave: a rung verified first in a
wave of six waits for five more builds before anything can be pushed, and
measuring that wait per rung reports a batching decision as a regression in the
rung that happened to be ready first.

EXIT 0 with a row · EXIT 2 could not look. There is no exit 1: this reader
judges nothing, it measures. Anything it cannot measure — a broken stamp, a
missing section, a ledger that is not there — is exit 2 naming what it could not
read, and nothing is printed as a number.

WHAT IT DOES NOT COVER, declared rather than discovered:

 1. WHETHER A STAMP IS TRUE. The ledger is written by hand; a stamp entered an
    hour late is a correct calculation over a wrong input and nothing here can
    tell the two apart. The stamp is a claim by the person who wrote it.
 2. SPEND. Tokens and dollars per rung come from the usage screen and from the
    agent-cost reader over the transcripts; neither is in the ledger, in git or
    in the gate's logs, so those measures print as not derivable HERE and name
    where they come from instead of being estimated.
 3. A BUILD THAT WAS KILLED AND RESUMED. Its minutes are counted from the
    ORIGINAL `sent`, which is the honest wall clock of the work and not the
    agent's occupancy. Stated in the output.
 4. THE ARCHIVE. Closed cycles' rows move out of the dispatch ledger; `--archive`
    reads such a file with the identical grammar, and a cycle whose rows are
    split across both files must be given both.
 5. THE LOG GRAMMAR. The bank and loop readers match the lines this gate prints
    today. A gate that renamed one of them would leave this reader blind, so
    every log it could not classify is counted and NAMED rather than skipped —
    a count of unclassified logs is the tell.
 6. WHICH WAVE A HELD RUNG BELONGS TO. The wave derivation above attributes a
    rung to the first wave pushed after it merged; a rung deliberately held out
    of that push is attributed to it anyway, and the only tell is a merge→push
    figure that disagrees with the wave's other rungs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

# --- the refusal -------------------------------------------------------------


class CannotLook(Exception):
    """Something could not be read. Exit 2, nothing printed as a number."""


def refuse(what: str, *more: str) -> CannotLook:
    return CannotLook("\n".join([what, *more]))


# --- the ledger --------------------------------------------------------------

STAMP_FIELDS = ("sent", "done", "met", "merged", "pushed", "staged")
RUNG_STAGES = ("sent", "done", "met", "merged")

# The one clock. An unlabelled time IS this one; any other label is two clocks.
THE_CLOCK = "PDT"
_OTHER_CLOCKS = re.compile(r"\b(CES?T|UTC|GMT|BST|E[SD]T|P[SD]T|Z)\b")

_NOT_REACHED = {"—", "-", "–", ""}
_STAMPS_CELL = re.compile(r"\bstamps:\s*(.*)$")
_FIELD = re.compile(r"\b(" + "|".join(STAMP_FIELDS) + r")=")
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})$")
_BARE = re.compile(r"^(\d{1,2}):(\d{2})$")
_SHA8 = re.compile(r"^([0-9a-f]{7,40})\s+(.*)$")
_WAVE_ID = re.compile(r"^WAVE-[A-Za-z0-9]+$")


class Row:
    """One line of the dispatch table, parsed but not yet judged."""

    def __init__(self, path: str, lineno: int, cells: list[str]):
        self.path = path
        self.lineno = lineno
        self.ident = cells[0]
        self.task = cells[1]
        self.role = cells[2]
        self.state = cells[3]
        self.notes = cells[6]
        self.stamps: dict[str, dt.datetime | None] = {}
        self.merged_sha: str | None = None
        self.stamped = False

    @property
    def is_wave(self) -> bool:
        return bool(_WAVE_ID.match(self.ident))

    @property
    def is_verification(self) -> bool:
        return "verification" in self.role.lower() or self.ident.startswith("V-")

    @property
    def was_killed(self) -> bool:
        return "killed" in (self.state + " " + self.notes).lower()

    def where(self) -> str:
        return f"{self.ident} ({self.path}:{self.lineno})"


def read_rows(path: str) -> list[Row]:
    """Every data row of the dispatch table, in file order."""
    if not os.path.isfile(path):
        raise refuse(
            f"the dispatch ledger is not a file: {path}",
            "   There is nothing to measure. Name the file with --in-flight.",
        )
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        raise refuse(f"the dispatch ledger could not be read: {path} — {exc}") from exc

    rows: list[Row] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.startswith("|"):
            continue
        body = line.strip().strip("|")
        if set(body.replace("|", "").replace(" ", "")) <= {"-", ":"}:
            continue  # the separator
        cells = [cell.strip() for cell in body.split("|")]
        if len(cells) < 7:
            continue
        cells = cells[:6] + ["|".join(cells[6:]).strip()]
        if cells[0] in ("#", "") or cells[0].startswith("EXAMPLE"):
            continue
        rows.append(Row(path, lineno, cells))
    return rows


def split_stamps(cell: str) -> list[tuple[str, str]]:
    """`sent=… done=… …` → the fields in the order they were written."""
    hits = list(_FIELD.finditer(cell))
    out: list[tuple[str, str]] = []
    for index, hit in enumerate(hits):
        end = hits[index + 1].start() if index + 1 < len(hits) else len(cell)
        out.append((hit.group(1), cell[hit.end() : end].strip()))
    return out


def parse_stamps(row: Row) -> None:
    """Fill `row.stamps`, or refuse naming the row and the field."""
    found = _STAMPS_CELL.search(row.notes)
    if not found:
        row.stamped = False
        return
    row.stamped = True
    fields = dict(split_stamps(found.group(1)))
    unknown = set(fields) - set(STAMP_FIELDS)
    if unknown:
        raise refuse(
            f"{row.where()}: the stamps cell carries a field this grammar has no clock for: "
            + ", ".join(sorted(unknown)),
        )
    previous: dt.datetime | None = None
    for field in STAMP_FIELDS:
        raw = fields.get(field, "—").strip()
        value, sha = _one_stamp(row, field, raw, previous)
        if field == "merged":
            row.merged_sha = sha
        row.stamps[field] = value
        if value is not None:
            previous = value


def _one_stamp(
    row: Row, field: str, raw: str, previous: dt.datetime | None
) -> tuple[dt.datetime | None, str | None]:
    if raw in _NOT_REACHED:
        return None, None
    sha: str | None = None
    if field == "merged":
        carried = _SHA8.match(raw)
        if not carried:
            raise refuse(
                f"{row.where()}: the `merged` stamp must carry its sha and then its time "
                f"(`merged=<sha8> HH:MM`), and this one reads `{raw}`.",
            )
        sha, raw = carried.group(1), carried.group(2).strip()
    label = _OTHER_CLOCKS.search(raw)
    if label and label.group(1) != THE_CLOCK:
        raise refuse(
            f"{row.where()}: the `{field}` stamp is labelled `{label.group(1)}`, and this ledger "
            f"keeps one clock ({THE_CLOCK}).",
            "   Two clocks in one ledger cannot be normalised after the fact without guessing",
            "   which rows were written under which. Rewrite the stamp on the one clock.",
        )
    raw = _OTHER_CLOCKS.sub("", raw).strip()
    dated = _DATED.match(raw)
    bare = _BARE.match(raw)
    try:
        if dated:
            when = dt.datetime(
                int(dated.group(1)[0:4]),
                int(dated.group(1)[5:7]),
                int(dated.group(1)[8:10]),
                int(dated.group(2)),
                int(dated.group(3)),
            )
        elif bare:
            if previous is None:
                raise refuse(
                    f"{row.where()}: the `{field}` stamp is a bare time (`{raw}`) and no dated "
                    "stamp comes before it in the cell, so there is no date to inherit.",
                )
            when = previous.replace(hour=int(bare.group(1)), minute=int(bare.group(2)))
            while when < previous:
                when += dt.timedelta(days=1)
        else:
            raise refuse(
                f"{row.where()}: the `{field}` stamp reads `{raw}`, which is neither "
                "`YYYY-MM-DD HH:MM`, a bare `HH:MM`, nor an em dash for a stage not reached.",
            )
    except ValueError as exc:
        raise refuse(
            f"{row.where()}: the `{field}` stamp reads `{raw}`, which is not a time on any "
            f"clock — {exc}.",
        ) from exc
    if previous is not None and when < previous:
        raise refuse(
            f"{row.where()}: the `{field}` stamp ({when:%Y-%m-%d %H:%M}) is BEFORE the stamp "
            "written before it in the same cell. A stage cannot finish before the one it",
            "   waited on.",
        )
    return when, sha


def check_completeness(rows: list[Row]) -> None:
    """A stage reached with an earlier stage missing is a stamp nobody can measure."""
    for row in rows:
        if not row.stamped:
            continue
        if row.is_wave:
            if row.stamps.get("pushed") is None:
                raise refuse(
                    f"{row.where()}: a wave row carries the `pushed` and `staged` stamps for its "
                    "rungs, and this one has no `pushed` time.",
                    "   A wave is written once it is pushed; until then there is no wave row",
                    "   to read.",
                )
            continue
        reached = [stage for stage in RUNG_STAGES if row.stamps.get(stage) is not None]
        if not reached:
            continue
        # A ROW THAT WAS MERGED AND NEVER DISPATCHED IS NOT A RUNG, and saying
        # so is worth its own sentence. The generic refusal below names the
        # missing field — `the merged stamp is set and the sent stamp is not` —
        # which reads as "backfill `sent`", and for a note, a ruling or a merge
        # record there is no `sent` to backfill: nothing was ever dispatched.
        # The remedy is the opposite one, so the reader says it.
        if row.stamps.get("merged") is not None and row.stamps.get("sent") is None:
            raise refuse(
                f"{row.where()}: this row carries a `merged` stamp and no `sent` stamp, so it "
                "is NOT A RUNG ROW — a rung is dispatched before it is merged, and the stages "
                "between the two are what this reader measures.",
                "   A note, a ruling or a merge record has no build to time: WITHHOLD THE",
                "   STAMPS CELL entirely rather than stamping the one field it happens to",
                "   have. An unstamped row is counted and named, never dropped.",
            )
        last = RUNG_STAGES.index(reached[-1])
        for stage in RUNG_STAGES[:last]:
            if row.stamps.get(stage) is None:
                raise refuse(
                    f"{row.where()}: the `{RUNG_STAGES[last]}` stamp is set and the `{stage}` "
                    "stamp is not, so the stages between them cannot be measured.",
                    "   Backfill the missing stamp, or clear the later one.",
                )


# --- the waves ---------------------------------------------------------------


def assign_waves(rows: list[Row]) -> tuple[list[Row], dict[str, list[Row]], list[Row]]:
    """Each merged rung joins the first wave pushed at or after its merge."""
    waves = sorted(
        (row for row in rows if row.is_wave and row.stamped),
        key=lambda row: (row.stamps["pushed"], row.ident),
    )
    members: dict[str, list[Row]] = {wave.ident: [] for wave in waves}
    orphans: list[Row] = []
    for row in rows:
        if row.is_wave or not row.stamped or row.stamps.get("merged") is None:
            continue
        when_merged = row.stamps["merged"]
        home = None
        for wave in waves:
            when_pushed = wave.stamps["pushed"]
            if when_pushed is not None and when_merged is not None and when_pushed >= when_merged:
                home = wave
                break
        if home is None:
            orphans.append(row)
        else:
            members[home.ident].append(row)
    return waves, members, orphans


# --- the logs ----------------------------------------------------------------

_SCOPE_RULE = re.compile(r"^\s*scope\s+rule:\s*(.*)$")
_LOOP_WALL = re.compile(r"^ok: loop checks passed \((\d+)s\)")
_FULL_WALL = re.compile(r"^ok: all checks passed \((\d+)s\)")
_LEG_WALL = re.compile(r"^\s*\(([a-z0-9-]+):\s*(\d+)s\)")
_TOOK = re.compile(r"\btook=(\d+)\b")
_PUSH_HONOURED = re.compile(r"^pre-push: .*verdict honoured")
# THE DOCS-ONLY ROAD PRINTS NO LEG BANNER AND NO "all checks passed", BECAUSE
# IT RAN NO FULL GATE — it ran the readers the changed documentation has and
# wrote the same row a bank writes. A reader that only knew the full banner
# counted such a push as a bank that LAUNCHED and never went green, which is
# the opposite of what happened: the cheapest green in the population would
# have dragged the green percentage down every time it worked. So the road's
# own line is a green bank here, and the wall it carries is the road's total.
_DOCS_ONLY_WALL = re.compile(r"^pm_push --bank: docs-only reuse of \S+ .* total (\d+) s")
_ROOT_APPS = ("core", "accounts")

CLASSES = ("leaf", "core", "shared", "empty")


def classify_scope(reason: str) -> str:
    """The three change classes the gate's own scope rule already distinguishes."""
    if "shared test infrastructure" in reason and "FULL suite" in reason:
        return "shared"
    apps: list[str] = []
    for group in re.findall(r"\[([^\]]*)\]", reason):
        for part in re.split(r"[,\s]+", group):
            if part.strip() not in ("", "-"):
                apps.append(part.strip())
    if not apps:
        return "empty"
    if any(app in _ROOT_APPS for app in apps):
        return "core"
    return "leaf"


def read_loop_logs(directory: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "by_class": {name: [] for name in CLASSES},
        "unclassified": [],
        "no_wall": [],
    }
    if directory is None:
        return out
    for path in _logs_in(directory):
        reason = None
        wall = None
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                hit = _SCOPE_RULE.match(line)
                if hit and reason is None:
                    reason = hit.group(1).strip()
                wall_hit = _LOOP_WALL.match(line)
                if wall_hit:
                    wall = int(wall_hit.group(1))
                elif wall is None:
                    took = _TOOK.search(line)
                    if took and "nominal" not in line:
                        wall = int(took.group(1))
        name = os.path.basename(path)
        if reason is None:
            out["unclassified"].append(name)
            continue
        if wall is None:
            out["no_wall"].append(name)
            continue
        out["by_class"][classify_scope(reason)].append(wall)
    return out


def read_bank_logs(directory: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "launched": 0,
        "green": 0,
        "pushed": 0,
        "docs_only": 0,
        "walls": [],
        "legs": {},
        "names": [],
    }
    if directory is None:
        return out
    for path in _logs_in(directory):
        out["launched"] += 1
        out["names"].append(os.path.basename(path))
        legs: dict[str, int] = {}
        wall = None
        docs_wall = None
        pushed = False
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                leg = _LEG_WALL.match(line)
                if leg:
                    legs[leg.group(1)] = int(leg.group(2))
                full = _FULL_WALL.match(line)
                if full:
                    wall = int(full.group(1))
                docs = _DOCS_ONLY_WALL.match(line)
                if docs:
                    docs_wall = int(docs.group(1))
                if _PUSH_HONOURED.match(line):
                    pushed = True
        # THE FULL BANNER WINS WHERE BOTH ARE PRESENT. A reader that could not
        # look prints the road's refusal AND then pays the whole bank, and the
        # wall that push cost is the bank's.
        if wall is None and docs_wall is not None:
            wall = docs_wall
            out["docs_only"] += 1
        if wall is not None:
            out["green"] += 1
            out["walls"].append(wall)
        if pushed:
            out["pushed"] += 1
        for name, seconds in legs.items():
            out["legs"].setdefault(name, []).append(seconds)
    return out


def _logs_in(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        raise refuse(f"the log directory is not a directory: {directory}")
    return sorted(
        os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".log")
    )


# --- git ----------------------------------------------------------------------


def resolve_merges(repo: str | None, rows: list[Row]) -> dict[str, Any]:
    """Cross-check each merge stamp's sha against the repository it names."""
    out: dict[str, Any] = {"asked": 0, "resolved": 0, "unresolved": [], "disagreed": []}
    if repo is None:
        return out
    for row in rows:
        if not row.merged_sha:
            continue
        out["asked"] += 1
        try:
            result = subprocess.run(
                ["git", "-C", repo, "show", "-s", "--format=%cI", row.merged_sha + "^{commit}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise refuse(f"git could not be run over {repo}: {exc}") from exc
        if result.returncode != 0:
            out["unresolved"].append(row.ident)
            continue
        out["resolved"] += 1
        try:
            committed = dt.datetime.fromisoformat(result.stdout.strip()).replace(tzinfo=None)
        except ValueError:
            out["unresolved"].append(row.ident)
            continue
        stamped = row.stamps["merged"]
        if stamped is not None and abs((committed - stamped).total_seconds()) > 3600:
            out["disagreed"].append(row.ident)
    return out


# --- the readouts header -------------------------------------------------------


def read_baseline_header(path: str) -> tuple[str, str, int]:
    """The cost-baseline table's header line, verbatim, and where it was read."""
    if not os.path.isfile(path):
        raise refuse(f"the readouts file is not a file: {path}")
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("## ") and "COST BASELINE" in line),
        None,
    )
    if start is None:
        raise refuse(
            f"{path} has no `## … COST BASELINE …` section.",
            "   The row's columns are READ from that table's header and never carried here:",
            "   a second copy of a header is a second truth about what a cycle measures.",
        )
    for index in range(start, len(lines)):
        line = lines[index]
        if line.startswith("|") and line.rstrip().endswith("|"):
            columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(columns) != 3:
                raise refuse(
                    f"{path}:{index + 1}: the cost-baseline table has {len(columns)} columns and "
                    "this reader writes three-column rows.",
                )
            return line.rstrip(), "|".join(["---"] * 3).join(["|", "|"]), index + 1
    raise refuse(f"{path}: the COST BASELINE section has no table header under it.")


# --- arithmetic ----------------------------------------------------------------


def minutes(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 60.0


def number(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def p75(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = -(-75 * len(ordered) // 100)  # nearest-rank, ceiling
    return ordered[max(rank, 1) - 1]


def hours(value: float | None) -> str:
    return number(value / 60.0) if value is not None else "—"


def _last_met(rows: list[Row]) -> dt.datetime | None:
    mets = [row.stamps["met"] for row in rows if row.stamps.get("met") is not None]
    return max(m for m in mets if m is not None) if mets else None


def spread(values: Sequence[float], unit: str) -> str:
    if not values:
        return "—"
    return (
        f"{number(median(values))} / {number(p75(values))} / {number(max(values))} {unit} "
        f"(n={len(values)})"
    )


# --- the report -----------------------------------------------------------------

NOT_HERE = "— not derivable from the ledger, git or the gate's logs"


def build_report(args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    rows: list[Row] = []
    for path in [args.in_flight] + list(args.archive or []):
        rows += read_rows(path)
    for row in rows:
        parse_stamps(row)
    check_completeness(rows)

    header, rule, header_line = read_baseline_header(args.readouts)
    loops = read_loop_logs(args.loop_logs)
    banks = read_bank_logs(args.bank_logs)
    git = resolve_merges(args.git, rows)

    stamped = [row for row in rows if row.stamped]
    unstamped = [row for row in rows if not row.stamped]
    rungs = [row for row in stamped if not row.is_wave and not row.is_verification]
    verifications = [row for row in stamped if row.is_verification]
    waves, members, orphans = assign_waves(rows)

    out: list[str] = []
    say = out.append

    say("== loop_metrics · the cost-baseline row, derived")
    say(f"   ledger    {args.in_flight}")
    for extra in args.archive or []:
        say(f"   archive   {extra}")
    say(f"   readouts  {args.readouts}:{header_line} (the header below is read from there)")
    say(f"   clock     {THE_CLOCK}, one clock; a build killed and resumed is counted from `sent`")
    say("")

    # --- stage 3, per rung
    say("-- STAGE 3, per rung · done→met")
    stage3: list[float] = []
    for row in rungs:
        gap = minutes(row.stamps.get("done"), row.stamps.get("met"))
        build = minutes(row.stamps.get("sent"), row.stamps.get("done"))
        if gap is None:
            say(f"   {row.ident:<14} done→met  — (not reached)")
            continue
        stage3.append(gap)
        say(f"   {row.ident:<14} done→met  {number(gap)} min   [sent→done {number(build)} min]")
    if not stamped:
        say("   no stamped row in this ledger — nothing to measure, and nothing guessed")
    say(f"   median done→met: {number(median(stage3))} min over {len(stage3)} rung(s)")
    say("")

    # --- stages 4 and 5, per wave
    say("-- STAGES 4-5, per wave · last met→pushed→staged")
    stage4: list[float] = []
    stage5: list[float] = []
    for wave in waves:
        mine = members[wave.ident]
        mets = [row.stamps["met"] for row in mine if row.stamps.get("met") is not None]
        last_met = max(m for m in mets if m is not None) if mets else None
        to_push = minutes(last_met, wave.stamps.get("pushed"))
        to_stage = minutes(wave.stamps.get("pushed"), wave.stamps.get("staged"))
        if to_push is not None:
            stage4.append(to_push)
        if to_stage is not None:
            stage5.append(to_stage)
        say(
            f"   {wave.ident:<14} last met→pushed  "
            f"{number(to_push) + ' min' if to_push is not None else 'not reached'}"
            f"   ·   pushed→staged  "
            f"{number(to_stage) + ' min' if to_stage is not None else 'not reached'}"
        )
        roll = ", ".join(row.ident for row in mine) or "no rung merged into it"
        say(f"   {wave.ident}: {roll}")
    for row in orphans:
        say(f"   {row.ident:<14} merged, not yet pushed by any wave in this ledger")
    say(
        f"   median last met→pushed: {number(median(stage4))} min"
        f"   ·   median pushed→staged: {number(median(stage5))} min"
    )
    say("")

    # --- the inner loop, by change class
    say("-- THE INNER LOOP, by change class (the gate's own `scope rule:`)")
    for name in CLASSES:
        walls = loops["by_class"][name]
        if walls:
            say(
                f"   {name:<14} median {number(median(walls))} s"
                f"   (n={len(walls)}; {', '.join(str(w) for w in sorted(walls))})"
            )
        else:
            say(f"   {name:<14} no log of this class")
    if loops["unclassified"]:
        say(
            f"   unclassified   {len(loops['unclassified'])} log(s) with no `scope rule:` line, "
            "counted and named: " + ", ".join(loops["unclassified"])
        )
    if loops["no_wall"]:
        say(
            f"   no wall        {len(loops['no_wall'])} log(s) that named their scope and not "
            "their seconds: " + ", ".join(loops["no_wall"])
        )
    say("")

    # --- what could not be measured
    say("-- UNSTAMPED ROWS, counted and named, never dropped")
    say(
        f"   {len(unstamped)} of {len(rows)} ledger row(s) are unstamped — no stamps cell at all. "
        "They are excluded from every median above and counted here:"
    )
    for row in unstamped:
        say(f"     {row.ident:<14} {row.state[:40]}")
    if git["asked"]:
        say(
            f"   merge shas: {git['resolved']} of {git['asked']} resolved in {args.git}"
            + (f"; unresolved: {', '.join(git['unresolved'])}" if git["unresolved"] else "")
            + (
                f"; stamped time disagrees with the commit by over an hour: "
                f"{', '.join(git['disagreed'])}"
                if git["disagreed"]
                else ""
            )
        )
    say("")

    # --- the row itself
    build_minutes = [
        m for m in (minutes(r.stamps.get("sent"), r.stamps.get("done")) for r in rungs) if m
    ]
    verify_minutes = [
        m
        for m in (minutes(r.stamps.get("sent"), r.stamps.get("done")) for r in verifications)
        if m is not None
    ]
    to_merge = [
        m for m in (minutes(r.stamps.get("sent"), r.stamps.get("merged")) for r in rungs) if m
    ]
    merge_to_push: list[float] = []
    for wave in waves:
        for row in members[wave.ident]:
            gap = minutes(row.stamps.get("merged"), wave.stamps.get("pushed"))
            if gap is not None:
                merge_to_push.append(gap)
    fix_laps = [row for row in rungs if re.search(r"F[0-9]*$", row.ident)]
    fix_minutes = sum(
        m for m in (minutes(r.stamps.get("sent"), r.stamps.get("done")) for r in fix_laps) if m
    )
    merged_rungs = [row for row in rungs if row.stamps.get("merged")]
    killed = [row for row in rows if row.was_killed]
    green_pct = f"{round(100 * banks['green'] / banks['launched'])}%" if banks["launched"] else "—"
    legs = banks["legs"]

    say("-- THE COST BASELINE ROW (paste under § COST BASELINE; relabel the middle column")
    say("   with this cycle's name and date — the header below is the one read from the file)")
    say(header)
    say(rule)
    measures: list[tuple[str, str, str]] = [
        ("cycle", args.cycle or "—", "the window these rows were measured over"),
        ("rungs merged", str(len(merged_rungs)), "throughput: rungs with a merge stamp"),
        (
            "fix laps (n, % of build min)",
            f"{len(fix_laps)}"
            + (
                f" · {round(100 * fix_minutes / sum(build_minutes))}%"
                if build_minutes and fix_minutes
                else " · 0%"
            ),
            "rework: criteria before code, and a loop that sees what the bank sees",
        ),
        (
            "build min (med/p75/max)",
            spread(build_minutes, "min"),
            "one rung per build; brief shape",
        ),
        (
            "verify min (med/p75)",
            f"{number(median(verify_minutes))} / {number(p75(verify_minutes))} min "
            f"(n={len(verify_minutes)})"
            if verify_minutes
            else "—",
            "batched per territory; the builder's consult reused",
        ),
        (
            "dispatch→merge h (med/p75)",
            f"{hours(median(to_merge))} / {hours(p75(to_merge))} h (n={len(to_merge)})"
            if to_merge
            else "—",
            "lead time for changes, end to end",
        ),
        (
            "merge→push h (med)",
            f"{hours(median(merge_to_push))} h (n={len(merge_to_push)})" if merge_to_push else "—",
            "one push per bank, one bank per wave",
        ),
        (
            "banks launched / pushed / green %",
            (
                f"{banks['launched']} / {banks['pushed']} / {green_pct}"
                + (f" ({banks['docs_only']} docs-only)" if banks.get("docs_only") else "")
            )
            if banks["launched"]
            else "— no bank log given",
            "the constraint: small batches, bounded retries on transients",
        ),
        (
            "bank wall s (med) by leg",
            _bank_walls(banks, legs),
            "stage split; input-keyed reuse",
        ),
        (
            "--loop consult s (leaf / core / shared)",
            " / ".join(
                number(median(loops["by_class"][name])) for name in ("leaf", "core", "shared")
            )
            + (f" · {len(loops['unclassified'])} unclassified" if loops["unclassified"] else ""),
            "the commit stage: one median per change class, never one median",
        ),
        (
            "builders' waits >= 5 min (n)",
            NOT_HERE + "; the transcript profiler is its source",
            "bounded polls; staggered dispatch",
        ),
        (
            "agents killed",
            str(len(killed)) + (f" ({', '.join(r.ident for r in killed)})" if killed else ""),
            "the platform and the stall guard, from the ledger's own state cells",
        ),
        (
            "turns and tool calls per build (med)",
            NOT_HERE + "; the transcript profiler is its source",
            "brief shape; fewer bookkeeping turns",
        ),
        (
            "cache-read tokens per build (med)",
            NOT_HERE + "; the transcript profiler is its source",
            "context size, which is what the stall guard re-reads",
        ),
        (
            "$ per verified rung",
            NOT_HERE + "; the owner's usage screen and the agent-cost reader are its source",
            "all of the above, in one number",
        ),
        (
            "box: consult s, $ per verification",
            NOT_HERE + "; a box's logs are given with --loop-logs and labelled by hand",
            "verification off the operator's machine",
        ),
        (
            "one clock",
            f"{THE_CLOCK}; {len(stamped)} of {len(rows)} rows stamped",
            "a ledger with two clocks cannot be read straight",
        ),
    ]
    for measure, value, lever in measures:
        say(f"| {measure} | {value} | {lever} |")

    payload = {
        "clock": THE_CLOCK,
        "ledger": args.in_flight,
        "header": header,
        "stage3": {
            "per_rung": {
                row.ident: minutes(row.stamps.get("done"), row.stamps.get("met")) for row in rungs
            },
            "median_min": median(stage3),
        },
        "stage4_5": {
            wave.ident: {
                "rungs": [row.ident for row in members[wave.ident]],
                "last_met_to_pushed_min": minutes(
                    _last_met(members[wave.ident]),
                    wave.stamps.get("pushed"),
                ),
                "pushed_to_staged_min": minutes(
                    wave.stamps.get("pushed"), wave.stamps.get("staged")
                ),
            }
            for wave in waves
        },
        "inner_loop": {
            "by_class": {name: loops["by_class"][name] for name in CLASSES},
            "unclassified": loops["unclassified"],
            "no_wall": loops["no_wall"],
        },
        "banks": {
            "launched": banks["launched"],
            "pushed": banks["pushed"],
            "green": banks["green"],
            "walls": banks["walls"],
        },
        "unstamped": [row.ident for row in unstamped],
        "row_count": len(rows),
        "git": git,
        "row": [{"measure": m, "value": v} for m, v, _ in measures],
    }
    return out, payload


def _bank_walls(banks: dict[str, Any], legs: dict[str, list[int]]) -> str:
    if not banks["walls"]:
        return "— no green bank log given"
    parts = [f"{number(median(banks['walls']))} s"]
    for name in ("selftest", "pytest-x2", "house-rules", "supply-chain"):
        if name in legs:
            parts.append(f"{name} {number(median(legs[name]))}")
    return " = ".join([parts[0], " + ".join(parts[1:])]) if len(parts) > 1 else parts[0]


# --- the door -------------------------------------------------------------------


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(
        prog="loop_metrics.py",
        description="Derive the cost-baseline row from the dispatch ledger, git and the logs.",
        allow_abbrev=False,
    )
    parser.add_argument("--in-flight", default=os.path.join(here, "docs/product/in-flight.md"))
    parser.add_argument("--archive", action="append", default=[])
    parser.add_argument("--readouts", default=os.path.join(here, "docs/product/readouts.md"))
    parser.add_argument("--bank-logs", default=None)
    parser.add_argument("--loop-logs", default=None)
    parser.add_argument("--git", default=None)
    parser.add_argument("--cycle", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        lines, payload = build_report(args)
    except CannotLook as exc:
        print(f"!! loop_metrics: {exc}", file=sys.stderr)
        print(
            "   Nothing was measured. A reader that could not read its inputs has",
            file=sys.stderr,
        )
        print("   measured nothing, and prints no number.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
