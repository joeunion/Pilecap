"""Rule 35's runner: EXPLAIN every probed hot path under `enable_seqscan = off`.

Started as a subprocess by `quality/checks.py::hot_path_sargability` — never by
the default suite, never by `perf/`. It owns a per-checkout **probe database**
(`<derived-name>_hp`, `quality/hotpaths.py::probe_database_name`): created on
first use, migrated on every run (a no-op when current), seeded with the fixed
world (small, but no longer *minimal* — `quality/hotpaths.py` says what the
sizes buy and why a world too small to make the pinned plan the planner's own
choice cannot assert a plan at all), and `ANALYZE`d before any plan is read —
the statistics
assumption rule 35 declares, following the harness's own precedent
(`perf/seed.py::seed_scale` → `analyze_world`, F1d closing M2's FINDING F: an
EXPLAIN against stale statistics measures the loader, not the tree).

The instrument (ADR gate-2): with sequential scans cost-penalised, a plan that
STILL sequentially scans the entry's subject table means no index could serve
the query — the filter is unsargable or the index is gone. That is
scale-independent and machine-invariant, which is what lets the gate hold it on
a tiny world forever, where actual planner *choice at volume* stays the
harness's half (`does_not_cover`, with M1-C and M4 FINDING 1 as the measured
instances).

Output: one JSON object on stdout —
    {"findings": [...], "notes": [...], "hot_paths": N, "probed": P,
     "explained_statements": M, "lookup_columns_declared": D,
     "lookup_columns_proven": Pv, "lookup_columns_unproven": Un,
     "index_served_untyped": U, "plan_shapes": {path: {table: [shape, ...]}}}
Exit 0 whether or not there are findings (the check turns findings into
violations); a non-zero exit means the probe itself could not run, which the
check surfaces as UNBOUND — enforcement broken, never a pass.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRANSACTION_CONTROL = ("SAVEPOINT", "RELEASE", "BEGIN", "COMMIT", "ROLLBACK", "SET ")

_SCAN_NODE = re.compile(
    r"(?P<kind>Seq Scan|Index Scan|Index Only Scan|Bitmap Heap Scan)"
    r"(?: Backward)?(?: using \S+)? on (?P<table>\S+)"
)


# : A declared lookup column is only PROVEN in a world where the planner had a
# : choice to get wrong. `enable_seqscan = off` is a thumb on the scale, and on a
# : two-row table it is the whole scale: there is exactly one plan, so "the index
# : served it" is a fact about the setting rather than about the predicate. Rule
# : 35's own header makes this argument for `core_organization` and sizes the
# : world to it (`quality/hotpaths.py::FILLER_ORGS`); until the argument was
# : applied to one table out of five and nothing measured the other four.
# :
# : 100 is the smallest number at which the flip has ever been observed to be a
# : CHOICE rather than a foregone conclusion in this repository: the measured
# : per-filler sweep behind FILLER_ORGS goes red at 3 and green from 20 on, and
# : 100 sits an order of magnitude above the red edge with the whole measured
# : green band above it. It is a floor on the WORLD, not a claim about scale —
# : the harness still owns planner choice at volume.
LOOKUP_PROOF_MIN_ROWS = 100

_PLAN_ROWS = re.compile(r"\brows=(\d+)")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def scan_blocks(plan: str, table: str) -> list[tuple[str, list[str]]]:
    """(node kind, the lines on and under it) for every scan of `table`.

    Structure is read off the indentation EXPLAIN itself prints: a node's block
    runs until the next line at or above its own indent. A bitmap plan's
    `BitmapOr` and its `Bitmap Index Scan` children sit *under* the heap scan
    and are therefore part of its block, which is what lets the column checks
    below read a bitmap's conditions without knowing it is a bitmap.
    """
    lines = plan.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    for i, line in enumerate(lines):
        match = _SCAN_NODE.search(line)
        if match is None or match.group("table") != table:
            continue
        base = _indent(line)
        block = []
        for follower in lines[i + 1 :]:
            if follower.strip().startswith("->") and _indent(follower) <= base:
                break
            if _indent(follower) <= base and follower.strip():
                break
            block.append(follower)
        blocks.append((match.group("kind"), block))
    return blocks


def scan_nodes(plan: str, table: str) -> list[tuple[str, bool]]:
    """(node kind, has-a-lookup) for every scan of `table` in this plan.

    "Has a lookup" means an `Index Cond:` (or a bitmap `Recheck Cond:`) appears
    on the node or anywhere under it — the position M3-F3 proved is the finding
    (`Index Cond` is a lookup; `Filter` alone is a walk).

    **This is the weak form, and P-1 is why it needs a strong one beside it.**
    On a tenant-scoped read the `for_tenant` leg always supplies an Index Cond,
    so "some Index Cond exists" is satisfied by the tenancy predicate no matter
    what happened to the predicate the entry actually cares about. An entry that
    declares `lookup_columns` gets `column_findings()` as well; an entry that
    does not keeps exactly these semantics and is counted as
    `index_served_untyped`.
    """
    return [
        (kind, any("Index Cond:" in ln or "Recheck Cond:" in ln for ln in block))
        for kind, block in scan_blocks(plan, table)
    ]


def scan_estimate(plan: str, table: str) -> int | None:
    """The planner's own row estimate for the narrowest scan of `table`.

    EXPLAIN prints `(cost=… rows=N width=…)` on every node; on a scan node that
    N is how many rows the planner expects the predicate to REACH. Divided by
    the table's real row count it is the predicate's share — the number the
    sizing argument in `quality/hotpaths.py` is actually about, and the one
    nothing measured until .
    """
    estimates: list[int] = []
    for line in plan.splitlines():
        match = _SCAN_NODE.search(line)
        if match is None or match.group("table") != table:
            continue
        rows = _PLAN_ROWS.search(line)
        if rows:
            estimates.append(int(rows.group(1)))
    return min(estimates) if estimates else None


def plan_shapes(plan: str) -> dict[str, set[str]]:
    """`table -> the node kinds and condition kinds its scans carry, in this plan.

    The negative corpus's own instrument (c)). A negative claims to exempt
    a SHAPE — "a Filter beside an Index Cond", "a join to a lookup table" — and
    a negative whose planted fixture does not actually produce that shape is
    silent for the wrong reason: it proves the rule ignores something that was
    never there. `filtered_audit_read.py` was exactly that for a cycle (the
    planner folded its `created_at IS NOT NULL` into the Index Cond, so no
    `Filter:` was ever produced), and nothing could tell it from restraint.
    """
    shapes: dict[str, set[str]] = {}
    for line in plan.splitlines():
        match = _SCAN_NODE.search(line)
        if match is None:
            continue
        table = match.group("table")
        seen = shapes.setdefault(table, set())
        seen.add(match.group("kind"))
        for kind, block in scan_blocks(plan, table):
            seen.add(kind)
            for entry in block:
                for marker in ("Index Cond:", "Recheck Cond:", "Filter:"):
                    if marker in entry:
                        seen.add(marker)
    return shapes


def _names(line: str, column: str) -> bool:
    """Does this plan line name that column? Whole word, so `path` is not `pathological`."""
    return re.search(rf"\b{re.escape(column)}\b", line) is not None


def _condition_lines(block: list[str]) -> list[str]:
    return [ln for ln in block if "Index Cond:" in ln or "Recheck Cond:" in ln]


def _recheck_lines(block: list[str]) -> list[str]:
    return [ln for ln in block if "Recheck Cond:" in ln]


def _filter_lines(block: list[str]) -> list[str]:
    return [ln for ln in block if "Filter:" in ln]


def column_findings(*, path: str, table: str, column: str, plan: str) -> list[str]:
    """The two edges of the subject-column form, for one declared column.

    **(a) the lookup edge** — the column's predicate must BE an index condition
    on (or under) this table's scan node, not merely accompany one. This is the
    edge P-1 opened: re-spelling `path = p OR path LIKE 'p.%'` as its `iexact`
    twin leaves the `for_tenant` leg's `Index Cond` in place and demotes the
    path predicate to a `Filter`, and the weak form calls that index-served.

    **(b) the filter belt** — the same degradation seen from the other side: a
    `Filter:` that names the declared column. It is not (a) spelled twice: a
    plan whose `Index Cond` names the column as a coarse range while the
    selective predicate rides a `Filter` passes (a) and fails (b), which is
    M4 FINDING 1's substitution one notch subtler. The belt does NOT fire when
    a `Recheck Cond:` on the node names the column: a bitmap heap scan restates
    its `BitmapOr` qual as a `Filter` by construction, and reading that
    repetition as a demotion would refuse the very plan (a) is asking for.
    Declared in `does_not_cover`.

    Both findings print the plan, because a plan-shape finding a reader cannot
    see the plan for is a number without its measurement.
    """
    findings: list[str] = []
    for kind, block in scan_blocks(plan, table):
        if kind == "Seq Scan":
            continue  # the existing, louder finding already owns this plan
        if not any(_names(line, column) for line in _condition_lines(block)):
            findings.append(
                f"{path}: {table} is not index-served on `{column}` — the declared lookup "
                f"column appears in no Index Cond or Recheck Cond on this scan, so the "
                f"predicate on `{column}` is not what reaches the rows (an Index Cond on "
                f"another column — the tenant leg, typically — is not this column's "
                f"lookup). The plan:\n{plan}"
            )
        elif not any(_names(line, column) for line in _recheck_lines(block)):
            demoted = [line for line in _filter_lines(block) if _names(line, column)]
            if demoted:
                findings.append(
                    f"{path}: the predicate on `{column}` has fallen out of the index "
                    f"condition into a filter — {table}'s scan carries "
                    f"`{demoted[0].strip()}`, so those rows are read and discarded rather "
                    f"than never read. The plan:\n{plan}"
                )
    return findings


def load_registry() -> list[dict[str, Any]]:
    import yaml

    rules = yaml.safe_load((ROOT / "quality" / "rules.yaml").read_text())["rules"]
    for rule in rules:
        if str(rule["id"]) == "35":
            return list(rule.get("registry") or [])
    raise SystemExit("rule 35 (and its registry) is missing from quality/rules.yaml")


def load_counts() -> dict[str, int]:
    import yaml

    budgets = yaml.safe_load((ROOT / "quality" / "budgets.yaml").read_text()) or {}
    return {k: int(v) for k, v in (budgets.get("hot_path_query_counts") or {}).items()}


def ensure_database() -> None:
    """Point Django at the `_hp` probe database, creating it when missing.

    Both halves of its guard are here. `probe_database_name` refuses a name
    that is not `[A-Za-z0-9_]` within Postgres's budget — before any SQL is
    built — and the `CREATE` below composes its identifier with
    `psycopg.sql.Identifier` rather than an f-string. Either alone is
    sufficient; both, because this is the DDL the second strike was found in
    (`CREATE DATABASE "{name}"` off an env-derived `DATABASE_NAME`), and it was
    protected only by psycopg's implicit transaction refusing to run a second
    `CREATE DATABASE` — an accident, not a refusal.
    """
    from django.conf import settings

    from quality.hotpaths import probe_database_name

    default = settings.DATABASES["default"]
    base_name = default["NAME"]
    default["NAME"] = probe_database_name(base_name)

    import psycopg
    from psycopg import sql as psql

    with psycopg.connect(
        dbname="postgres",
        user=default.get("USER") or None,
        password=default.get("PASSWORD") or None,
        host=default.get("HOST") or None,
        port=default.get("PORT") or None,
        autocommit=True,
    ) as admin:
        row = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (default["NAME"],)
        ).fetchone()
        if row is None:
            admin.execute(
                psql.SQL("CREATE DATABASE {}").format(psql.Identifier(str(default["NAME"])))
            )


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

    import django

    django.setup()
    ensure_database()

    from django.core.management import call_command
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext
    from psycopg import sql as psql

    call_command("migrate", verbosity=0, interactive=False)

    from quality import worlds as W
    from quality.hotpaths import PROBE_NEEDS_APP, PROBES, World, app_installed, ensure_world

    optional = W.optional_app_labels(ROOT)

    world = World()
    ensure_world(world)

    registry = load_registry()
    counts = load_counts()
    findings: list[str] = []
    notes: list[str] = []
    skipped: list[str] = []
    explained = 0
    probed = 0
    declared_columns = 0
    untyped_tables = 0
    proven_columns = 0
    unproven_columns = 0
    row_counts: dict[str, int | None] = {}
    shapes_by_path: dict[str, dict[str, list[str]]] = {}

    def rows_in(table: str) -> int | None:
        """`SELECT count(*)` for a probe table, once per run.

        A count and not an estimate: the probe world is tiny and freshly
        ANALYZEd, and the whole question here is whether it is tiny.
        """
        if table not in row_counts:
            try:
                with connection.cursor() as counter:
                    # The identifier goes through psycopg's own composer, never
                    # an f-string — the guarded-identifier class closes.
                    counter.execute(
                        psql.SQL("SELECT count(*) FROM {}").format(psql.Identifier(table))
                    )
                    fetched = counter.fetchone()
                row_counts[table] = int(fetched[0]) if fetched else None
            except Exception:  # noqa: BLE001 # an unknown table is "no world"
                row_counts[table] = None
        return row_counts[table]

    with connection.cursor() as cursor:
        # Statistics are part of "the world exists" (the seeder's precedent,
        # F1d): a plan read against an unanalyzed table describes the loader.
        cursor.execute("ANALYZE")
        # The instrument itself: with sequential scans cost-penalised, only a
        # query no index can serve still sequentially scans its subject table.
        cursor.execute("SET enable_seqscan = off")

    try:
        for entry in registry:
            path = str(entry["path"])
            if entry.get("pin") != "probe":
                continue
            # NOT IN THIS DEPLOYMENT'S WORLD. An entry whose probe reads
            # an app this deployment left out cannot be executed, and executing
            # it anyway is how one optional import took three rules' canaries
            # down with it. Skipped, reported, and paid for on the other side:
            # rule 35's floors declare what they count (`registry_floors`) and
            # `quality/worlds.py` lowers each expectation by exactly the members
            # the absent app contributed.
            needs = PROBE_NEEDS_APP.get(path)
            if needs and not app_installed(str(needs)):
                skipped.append(f"{path} (needs apps/{needs}, which this deployment omits)")
                continue
            # THE TWO DECLARATIONS OF ONE FACT, held against each other. This
            # module's `PROBE_NEEDS_APP` decides what RUNS; the registry's app —
            # derived from the dotted path, or declared with `needs_app:` where
            # the path lies — is what the FLOORS are lowered by. They must name
            # the same optional app or a floor will be derived for a world the
            # probe did not measure, and the direction that hurts is silent:
            # the expectation falls and nothing is missing from the count.
            # Compared over OPTIONAL apps only, because a mandatory app is never
            # absent and never needs saying twice.
            registry_needs = W.registry_entry_app(entry)
            registry_needs = registry_needs if registry_needs in optional else None
            if needs != registry_needs:
                findings.append(
                    f"{path}: quality/hotpaths.py::PROBE_NEEDS_APP says {needs!r} and rule "
                    f"35's registry entry resolves to {registry_needs!r} — the probe's world "
                    "and the floor's derivation would disagree about which optional app this "
                    "entry needs"
                )
            probe = PROBES.get(path)
            if probe is None:
                findings.append(
                    f"registry entry {path} is marked `pin: probe` but "
                    "quality/hotpaths.py has no probe for it — the entry is unenforced"
                )
                continue
            probed += 1
            clauses = entry.get("clauses") or {}
            with transaction.atomic():
                with CaptureQueriesContext(connection) as captured:
                    result = probe(world)
                statements = [
                    q["sql"]
                    for q in captured.captured_queries
                    if not q["sql"].lstrip().upper().startswith(TRANSACTION_CONTROL)
                ]
                plans: list[str] = []
                with connection.cursor() as cursor:
                    for sql in statements:
                        if not sql.lstrip().upper().startswith("SELECT"):
                            continue
                        cursor.execute(f"EXPLAIN {sql}")
                        plans.append("\n".join(str(row[0]) for row in cursor.fetchall()))
                transaction.set_rollback(True)
            explained += len(plans)
            findings.extend(f"{path}: {extra}" for extra in result.findings)
            # What every table's scans looked like, for the negative corpus's
            # own self-test (c)). Recorded on every run and free.
            per_table: dict[str, set[str]] = {}
            for plan in plans:
                for table, seen in plan_shapes(plan).items():
                    per_table.setdefault(table, set()).update(seen)
            shapes_by_path[path] = {t: sorted(s) for t, s in per_table.items()}

            recorded = counts.get(path)
            if recorded is None:
                findings.append(
                    f"{path}: no recorded count in quality/budgets.yaml "
                    f"hot_path_query_counts (measured {len(statements)}) — a new hot path "
                    "fails until a human measures it and commits the number"
                )
            elif len(statements) > recorded:
                findings.append(
                    f"{path}: {len(statements)} statements at gate scale, past the recorded "
                    f"{recorded} — the flat count the harness certified has grown; find the "
                    "new statement or re-measure through perf/ and commit the higher number "
                    "in a diff a reviewer sees"
                )
            elif len(statements) < recorded:
                notes.append(
                    f"{path}: measured {len(statements)} statements, below the recorded "
                    f"{recorded} — a human may commit the lower number"
                )

            for table in clauses.get("no_seq_scan_on") or []:
                offender = f"Seq Scan on {table}"
                for plan in plans:
                    if offender in plan:
                        findings.append(
                            f"{path}: `{offender}` with enable_seqscan = off — no index can "
                            f"serve this read any more (an unsargable filter, or the index is "
                            f"gone). The plan:\n{plan}"
                        )
            lookup_columns = entry.get("lookup_columns") or {}
            for table in clauses.get("index_served") or []:
                # The population print (F2-4): a table under `index_served` with
                # no declared column keeps the weak any-Index-Cond semantics and
                # is COUNTED, so the blind spot is a number a reviewer sees
                # rather than a silence. The count is ratcheted in
                # quality/budgets.yaml: it may fall and never rise.
                columns = [str(c) for c in (lookup_columns.get(table) or [])]
                if columns:
                    declared_columns += len(columns)
                    # THE WORLD THE ASSERTION RESTS ON (b)). A declared
                    # column asserts that a PREDICATE is the lookup. On a table
                    # of two rows under `enable_seqscan = off` the planner has
                    # no alternative to be wrong about, so the assertion is
                    # true and empty — it measures the setting. Emitted per
                    # column, always: the size and the share are the evidence a
                    # reviewer needs to read the declaration at all.
                    total = rows_in(table)
                    estimate = min(
                        (e for e in (scan_estimate(p, table) for p in plans) if e is not None),
                        default=None,
                    )
                    share = (
                        f"{estimate / total:.1%}"
                        if estimate is not None and total not in (None, 0)
                        else "n/a"
                    )
                    for column in columns:
                        if total is None or total < LOOKUP_PROOF_MIN_ROWS:
                            unproven_columns += 1
                            notes.append(
                                f"{path}: lookup column {table}.{column} is UNPROVEN — the "
                                f"probe world has {total} row(s) in {table}, below the "
                                f"{LOOKUP_PROOF_MIN_ROWS} at which the planner has a choice "
                                "to get wrong. `enable_seqscan = off` FORCES the index here, "
                                "so the assertion holds by construction and says nothing "
                                "about the predicate. Size the world (the argument and the "
                                "measured sweep are in quality/hotpaths.py), or read the "
                                "declaration as a pin on the harness's evidence rather than "
                                "on this one"
                            )
                        else:
                            proven_columns += 1
                            notes.append(
                                f"{path}: lookup column {table}.{column} is proven at gate "
                                f"scale — {total} rows in {table}, the predicate reaches "
                                f"~{estimate} of them ({share}), so the narrowing this "
                                "declaration pins is the plan the planner would pick anyway"
                            )
                else:
                    untyped_tables += 1
                for plan in plans:
                    for column in columns:
                        findings.extend(
                            column_findings(path=path, table=table, column=column, plan=plan)
                        )
                    for kind, has_lookup in scan_nodes(plan, table):
                        if kind == "Seq Scan":
                            findings.append(
                                f"{path}: {table} is not index-served — a Seq Scan survives "
                                f"enable_seqscan = off, so no index can serve this read at "
                                f"all. The plan:\n{plan}"
                            )
                        elif not has_lookup:
                            findings.append(
                                f"{path}: {table} is not index-served — its scan carries no "
                                f"Index Cond, so the predicate has stopped being a lookup and "
                                f"become a walk (an unsargable filter defeats the index; "
                                f"M3-F3's shape: the column's position is the finding). The "
                                f"plan:\n{plan}"
                            )
            for table in lookup_columns:
                if table not in (clauses.get("index_served") or []):
                    findings.append(
                        f"{path}: lookup_columns declares {table}, which this entry's "
                        "index_served clause does not name — a declaration nothing reads "
                        "is a pin nobody is holding"
                    )
            for index_name in clauses.get("index_in_plan") or []:
                if plans and not any(index_name in plan for plan in plans):
                    findings.append(
                        f"{path}: index {index_name!r} is in none of the {len(plans)} executed "
                        "plans — the read has left the index the registry pinned. First plan:\n"
                        + plans[0]
                    )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET enable_seqscan = on")

    print(
        json.dumps(
            {
                "findings": findings,
                # The skipped entries ride in `notes` as well as in their own
                # key: `quality/checks.py` forwards notes and would drop an
                # unknown key, and a world that shrank silently is the whole
                # defect. Both, so neither reader has to know about the other.
                "notes": notes + [f"NOT IN THIS WORLD: {one}" for one in skipped],
                "skipped": skipped,
                "hot_paths": len(registry),
                "probed": probed,
                "explained_statements": explained,
                "lookup_columns_declared": declared_columns,
                "lookup_columns_proven": proven_columns,
                "lookup_columns_unproven": unproven_columns,
                "index_served_untyped": untyped_tables,
                "plan_shapes": shapes_by_path,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
