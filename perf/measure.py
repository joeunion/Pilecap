"""The four instruments, and the refusal of vibes (ADR perf-1).

A measurement criterion in this repository is satisfied by exactly one of:

* a **query count** equal at S and at the doubled axis (`count_queries` +
  `flat_under_doubling`) — a count that is flat under doubling is scale-free,
  which is what lets the gate later pin it cheaply at gate scale;
* an **EXPLAIN plan-shape assertion** (`explain` + `assert_index_scan`, or the
  narrower `assert_no_seq_scan_on` when the query joins a lookup table) — the
  named index used, no Seq Scan on the doubled axis. Assertions pin index
  *names and node types*, never full plan text: EXPLAIN output is
  Postgres-version-shaped, and the measurement docs record the server version
  (`postgres_server_version`) beside every excerpt;
* a **cache-hit count** (`call_counter` on the fetch seam — the JWKS shape).

Wall-clock, buffer counts and row estimates are RECORDED in the measurement
docs as observations (ClickStack's business) and may never appear in a
criterion or a budget — `refuse_wall_clock_assertions` below is run by
`perf/conftest.py` over every collected measurement module, so a module that
asserts in seconds fails at import, loudly, naming the refusal.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from django.db import connections
from django.test.utils import CaptureQueriesContext


class QueryCount(CaptureQueriesContext):
    """`CaptureQueriesContext` plus the one number a criterion reads."""

    @property
    def count(self) -> int:
        return len(self.captured_queries)


@contextmanager
def count_queries(using: str = "default") -> Iterator[QueryCount]:
    """Count every query the block runs. The N+1 detector's raw instrument.

    with count_queries() as counted:
        list(Widget.objects.for_tenant(t).visible_to(hat)[:50])
    assert counted.count == 2
    """
    capture = QueryCount(connections[using])
    with capture:
        yield capture


def explain(queryset: Any, **options: Any) -> str:
    """The planner's shape for this queryset — `QuerySet.explain()`, verbatim.

    Record excerpts in the measurement doc beside the server version; assert
    with `assert_index_scan`, never against full plan text.
    """
    return str(queryset.explain(**options))


def assert_index_scan(queryset: Any, index_name: str, *, forbid_seq_scan: bool = True) -> str:
    """The named index appears in the plan; optionally no Seq Scan does.

    Returns the plan so the caller can paste it into the measurement doc.
    """
    plan = explain(queryset)
    if index_name not in plan:
        raise AssertionError(f"index {index_name!r} is not in the plan for this query.\n{plan}")
    if forbid_seq_scan and "Seq Scan" in plan:
        raise AssertionError(f"a Seq Scan appears in the plan alongside {index_name!r}.\n{plan}")
    return plan


def explain_as_executed(run: Any, *, using: str = "default") -> list[str]:
    """EXPLAIN **the statements a call actually issued**, not a queryset's idea of them.

    `QuerySet.explain()` compiles the queryset it is called on. That is the
    wrong query whenever the thing under measurement is not the queryset but a
    *read a door performs*: every list door is `@paginate`d, so what runs is a
    `LIMIT`-ed page and a separate `COUNT(*)`, and both plan differently from
    the unsliced queryset — a `LIMIT` lets the planner stop early on an
    ordering index, which is exactly the plan an unsliced EXPLAIN never shows.
    F1a proved this on M1's own verdicts; F1d turned it into an instrument.

    So: run the call, capture the SQL the ORM emitted (params already inlined
    by Django's own `last_executed_query`), and `EXPLAIN` each `SELECT`
    verbatim. What comes back is the plan for the statement that ran.

    Returns one plan per SELECT, in execution order.
    """
    with count_queries(using=using) as counted:
        run()
    plans: list[str] = []
    with connections[using].cursor() as cursor:
        for query in counted.captured_queries:
            sql = query["sql"]
            if not sql.lstrip().upper().startswith("SELECT"):
                continue
            cursor.execute(f"EXPLAIN {sql}")
            plans.append("\n".join(str(row[0]) for row in cursor.fetchall()))
    return plans


def assert_index_in(plan: str, index_name: str, *, forbid_seq_scan: bool = True) -> None:
    """`assert_index_scan`'s claim, made against a plan already in hand.

    The queryset form re-compiles and re-EXPLAINs, which silently substitutes
    a *different* query whenever the plan under discussion came from
    `explain_as_executed` (a page, a count). Asserting on the string keeps the
    verdict and the assertion about the same statement.
    """
    if index_name not in plan:
        raise AssertionError(f"index {index_name!r} is not in this plan.\n{plan}")
    if forbid_seq_scan and "Seq Scan" in plan:
        raise AssertionError(f"a Seq Scan appears in the plan alongside {index_name!r}.\n{plan}")


def assert_no_seq_scan_on(plan: str, table: str) -> None:
    """No sequential scan **of this table**. The narrow form of the refusal.

    `assert_index_scan(..., forbid_seq_scan=True)` forbids a `Seq Scan`
    anywhere in the plan, which is too blunt for any query that joins to a
    lookup table: a plan that hashes the whole 26-row `core_tenant` is a
    planner doing its job, not a finding. The table under measurement is the
    one that may not be scanned end to end, so that is the table named.

    Promoted here from `perf/measure_ledgers.py` by F1d — M2 wrote it against
    the relay's `select_related("event", "event__tenant")` plan and noted that
    it belonged in the instrument box rather than in one measurement module.
    """
    offender = f"Seq Scan on {table}"
    if offender in plan:
        raise AssertionError(f"{offender} — the table is being scanned end to end.\n{plan}")


def flat_under_doubling(*, base: int, doubled: int, axis: str, what: str) -> None:
    """The doubling comparator: the count at x2 equals the count at S.

    A count that grows under doubling is a FINDING, written with its EXPLAIN
    pair into the measurement doc — the rung's job is the truth, F1's is the
    fix — so the raising message carries both numbers verbatim.
    """
    if doubled != base:
        raise AssertionError(
            f"{what}: query count is not flat under doubling of {axis!r} — "
            f"{base} at S, {doubled} at x2. This is a finding: record it with "
            "its EXPLAIN pair in the measurement doc."
        )


class CallCount:
    """A counter handed out by `call_counter`."""

    def __init__(self) -> None:
        self.count = 0


@contextmanager
def call_counter(target: Any, attribute: str) -> Iterator[CallCount]:
    """Count invocations of `target.attribute` — the cache-hit instrument.

    The JWKS shape: wrap the fetch seam, run the storm, and the criterion is
    the fetch count (<= 1 per cache window), never the storm's wall-clock.
    """
    counted = CallCount()
    original = getattr(target, attribute)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        counted.count += 1
        return original(*args, **kwargs)

    setattr(target, attribute, wrapper)
    try:
        yield counted
    finally:
        setattr(target, attribute, original)


def postgres_server_version(using: str = "default") -> str:
    """For the measurement docs: plan shapes are server-version-shaped."""
    with connections[using].cursor() as cursor:
        cursor.execute("SHOW server_version")
        return str(cursor.fetchone()[0])


# --- The refusal -------------------------------------------------------------


class WallClockAssertionRefused(ImportError):
    """A measurement module asserted in seconds. This is refused."""


# An `assert` (or a pytest.approx comparison) whose line speaks in time units
# is the vibes this refusal killed: wall-clock measured on a dev machine was noisier
# than the raw numbers, and normalizing made it worse. Recording an elapsed
# time as an observation is legal; ASSERTING one is not.
_WALL_CLOCK_TOKENS = re.compile(
    r"\b(seconds?|elapsed|wall_?clock|duration|latency|perf_counter|monotonic|time\.time|timeit)\b"
)


def refuse_wall_clock_assertions(path: Path | str) -> None:
    """Refuse, at import of a measurement module, any assertion in seconds.

    Run by `perf/conftest.py` over every module it collects, so the guard is
    structural rather than customary — a hurried builder cannot skip it.
    """
    source = Path(path).read_text(encoding="utf-8")
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        is_assertion = stripped.startswith("assert ") or "pytest.approx" in stripped
        if is_assertion and _WALL_CLOCK_TOKENS.search(stripped):
            raise WallClockAssertionRefused(
                f"{path}:{lineno} asserts a wall-clock value:\n    {stripped}\n"
                "Wall-clock is recorded in the measurement doc as an "
                "observation for ClickStack, never asserted and never budgeted. "
                "Use count_queries / assert_index_scan / flat_under_doubling / "
                "call_counter (perf/measure.py) instead."
            )
