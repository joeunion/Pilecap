"""The ONE reader of everything Temporal says, for the machinery census.

`scripts/lifecycle.sh` declares the machinery classes and `scripts/sweep.sh`
walks them; this is the parser those two share for the three Temporal documents
they read — `schedule list`, `workflow list` and `task-queue describe`. It takes
one of those documents on stdin and prints tab- or pipe-separated columns.

WHY A FILE AND NOT THREE INLINE `python3 -c` PROGRAMS, which is what the census
had before this. The finding is not "there are dead schedules" — the
census already said FOREIGN about every one of them. It is that the census could
not say WHAT THE HARM WAS: how long ago a schedule last fired, how soon it fires
again, how old the stranded runs are, how deep the backlog is behind a queue
nothing polls. All four are CLOCK arithmetic, and Temporal stamps its clocks in
two formats that neither the shell nor `datetime.fromisoformat` reads as it
finds them — RFC-3339 with up to nine fractional digits, and Go durations
(`7h52m3s`). One parser for both, in one place, because two parsers is two
answers to "how old is this" and the second one is the one nobody read.

AGES ARE EMITTED AS INTEGER SECONDS, never as a formatted string. The formatting
belongs to `lifecycle.sh::lc_duration`, in the shell, so that printing one of a
hundred and thirty-six census rows does not cost a fork — and so this program
stays a thing the drive can hold a fixture up to without a server anywhere near
it. `-1` is the one sentinel: it means THIS RUN COULD NOT TELL, and it is never
confused with zero, which is a real answer.

The population is whatever the server said. Nothing here filters, judges or
attributes: the four verdicts are `lifecycle.sh`'s and the identity derivation
is `db.sh`'s, and a parser that started deciding whose a thing is would be a
second place the rules live.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime

# `-` and never an empty column: a tab is IFS whitespace to the shell reader, so
# an empty first field would collapse and every later field would be read one
# place to the left — a shifted read that judges the wrong string.
MISSING = "-"

# THIS RUN COULD NOT TELL, which is not zero. A schedule that has never fired and
# a schedule that fired this second are different facts, and a census that
# printed `0s` for both would be inventing one of them.
UNKNOWN = -1

_FRACTION = re.compile(r"\.(\d+)")
_GO_TERM = re.compile(r"(\d+(?:\.\d+)?)([a-zµ]+)")
_GO_UNITS = {
    "ns": 1e-9,
    "us": 1e-6,
    "µs": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}


def parse_stamp(stamp: object) -> datetime | None:
    """An RFC-3339 instant as Temporal writes it, or None if it is unreadable.

    Two shapes have to be normalised and both are Temporal's normal output:
    a trailing `Z` for UTC, and up to NINE fractional digits, which
    `datetime.fromisoformat` rejects on this interpreter.
    """
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    text = stamp.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        # A stamp with no zone is UTC here, because every Temporal stamp is.
        when = when.replace(tzinfo=UTC)
    return when


def seconds_since(stamp: object, now: datetime) -> int:
    """Whole seconds since `stamp`. Negative means it is still ahead of now."""
    when = parse_stamp(stamp)
    if when is None:
        return UNKNOWN
    return int((now - when).total_seconds())


def seconds_until(stamp: object, now: datetime) -> int:
    """Whole seconds until `stamp`. Negative means it has already passed."""
    when = parse_stamp(stamp)
    if when is None:
        return UNKNOWN
    return int((when - now).total_seconds())


def go_duration_seconds(text: object) -> int:
    """A Go duration (`7h52m3s`, `0s`, `1.5m`) as whole seconds, or UNKNOWN.

    `DescribeTaskQueue` reports `approximateBacklogAge` this way and nothing
    else in the census speaks that dialect.
    """
    if not isinstance(text, str) or not text.strip():
        return UNKNOWN
    total = 0.0
    seen = False
    for amount, unit in _GO_TERM.findall(text.strip()):
        if unit not in _GO_UNITS:
            return UNKNOWN
        total += float(amount) * _GO_UNITS[unit]
        seen = True
    if not seen:
        return UNKNOWN
    return int(total)


def load(raw: str) -> object:
    """The document, or None when the CLI printed nothing readable at all.

    A server that answered with silence is not a server that answered with an
    empty population, so the caller is told the difference by an exit status and
    never by an empty list that reads like `(none)`.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def short_status(status: object) -> str:
    """`WORKFLOW_EXECUTION_STATUS_RUNNING` as `RUNNING`, and unknown as `-`."""
    if not isinstance(status, str) or not status.strip():
        return MISSING
    return status.strip().rsplit("_", 1)[-1] if "_" in status else status.strip()


def emit_schedules(doc: object) -> None:
    """One tab-separated row per schedule:

    `<schedule id>` · seconds since its last fire · seconds until its next ·
    the workflow type it starts · what became of that last action.

    THE LAST COLUMN IS WHY THE GRAVEYARD IS QUIET. A schedule whose previous
    action is still RUNNING does not fire again while it waits, so a census that
    only read the clock would report a schedule that "last fired five hours ago"
    and sound harmless — when what it is actually doing is blocked behind its
    own run, stranded on a queue nothing polls, and it will resume the moment
    anything drains it.
    """
    now = datetime.now(UTC)
    if not isinstance(doc, list):
        return
    for item in doc:
        if not isinstance(item, dict):
            continue
        schedule_id = item.get("scheduleId")
        if not schedule_id:
            continue
        info = item.get("info") or {}
        actions = info.get("recentActions") or []
        # The LAST entry is the most recent action the server still keeps.
        last = UNKNOWN
        status = MISSING
        if isinstance(actions, list) and actions:
            newest = actions[-1]
            if isinstance(newest, dict):
                last = seconds_since(newest.get("actualTime"), now)
                status = short_status(newest.get("startWorkflowStatus"))
        future = info.get("futureActionTimes") or []
        nxt = UNKNOWN
        if isinstance(future, list) and future:
            nxt = seconds_until(future[0], now)
        workflow_type = (info.get("workflowType") or {}).get("name") or MISSING
        print(f"{schedule_id}\t{last}\t{nxt}\t{workflow_type}\t{status}")


def emit_executions(doc: object) -> None:
    """One tab-separated row per open run: queue · id · age · workflow type.

    The QUEUE is the identity — a workflow id names a tenant and a noun, never a
    checkout — and the AGE is what makes a run stranded on a dead queue legible
    as a leak instead of as a row.
    """
    now = datetime.now(UTC)
    if not isinstance(doc, list):
        return
    for item in doc:
        if not isinstance(item, dict):
            continue
        workflow_id = (item.get("execution") or {}).get("workflowId")
        if not workflow_id:
            continue
        queue = item.get("taskQueue") or MISSING
        age = seconds_since(item.get("startTime"), now)
        workflow_type = (item.get("type") or {}).get("name") or MISSING
        print(f"{queue}\t{workflow_id}\t{age}\t{workflow_type}")


def emit_queue(doc: object) -> None:
    """`<pollers>|<backlog>|<backlog age>` for one task queue.

    POLLERS ARE THE LIVENESS EVIDENCE and the other two are NOT. A backlog is
    proof that work is piling up, which is the opposite of proof that something
    is working it off — see `lifecycle.sh`, where that distinction is exactly
    the difference between IN USE and FOREIGN.
    """
    pollers = 0
    backlog = 0
    age = UNKNOWN
    if isinstance(doc, dict):
        pollers = len(doc.get("pollers") or [])
        stats = doc.get("stats") or []
        if isinstance(stats, list):
            for stat in stats:
                if not isinstance(stat, dict):
                    continue
                count = stat.get("approximateBacklogCount") or 0
                if isinstance(count, int):
                    backlog += count
                # The OLDEST age across the task-queue types: one number for the
                # queue, and the honest one is the worst one.
                one = go_duration_seconds(stat.get("approximateBacklogAge"))
                if one > age:
                    age = one
    print(f"{pollers}|{backlog}|{age}")


MODES = {
    "schedules": emit_schedules,
    "executions": emit_executions,
    "queue": emit_queue,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        modes = ", ".join(sorted(MODES))
        sys.stderr.write(f"lifecycle_temporal.py takes exactly one of: {modes}\n")
        return 2
    doc = load(sys.stdin.read())
    if doc is None:
        # 2 and not 0: the caller must be able to tell "the server said nothing"
        # from "the server said there is nothing", because the census prints
        # `(none)` for the second and has to exit 2 on the first.
        sys.stderr.write("lifecycle_temporal.py: stdin held no readable JSON document\n")
        return 2
    MODES[argv[1]](doc)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
