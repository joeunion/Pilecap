"""Rule 35: hot-path plan shapes (ADR gate-2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from quality.checks._hub import CheckResult, Finding, _dotted_to_file, _read
from quality.worlds import BUDGETS_FILE, Bound, budget_ceiling

# --- the diff-aware layer ------------------------------------------------------


# --- rule 35: hot-path plan shapes (ADR gate-2) --------------------------------

#: What a developer runs when the probe cannot: drop the `_hp` world, let the next run rebuild it.
HOT_PATH_CURE = "./scripts/db_sweep.sh --sweep --hot-path, then re-run"


def hot_path_sargability(root: Path, rule: dict) -> CheckResult:
    """EXPLAIN every probed registry entry's real read, via the probe subprocess.

    The subprocess (`quality/hotpath_probe.py`) owns the per-checkout `_hp`
    probe database, migrates it, ANALYZEs it (the declared statistics
    assumption — the seeder's precedent, F1d), sets `enable_seqscan = off` and
    applies each entry's clauses to the statements the read actually issued.
    A probe that cannot run reports zero targets, which the floors turn into
    UNBOUND — enforcement broken, never a pass.
    """
    out = CheckResult()
    registry = rule.get("registry") or []
    out.count("hot_paths", len(registry))
    proc = subprocess.run(
        [sys.executable, str(root / "quality" / "hotpath_probe.py")],
        cwd=root,
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=False,
    )
    if proc.returncode != 0:
        # No probed/explained counts land, so the floors report UNBOUND (exit
        # 2); this finding says why, so the reader is not left with a bare
        # "may be watching nothing".
        tail = (proc.stderr or proc.stdout).strip()[-1500:]
        out.hit(
            "quality/hotpath_probe.py",
            0,
            f"the hot-path probe could not run (exit {proc.returncode}) — "
            f"{HOT_PATH_CURE}; rule 35 is enforcing nothing until it can:\n{tail}",
        )
        return out
    try:
        report = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out.hit(
            "quality/hotpath_probe.py",
            0,
            "the hot-path probe produced no report — rule 35 is enforcing nothing "
            f"until it does. stdout tail:\n{proc.stdout.strip()[-800:]}",
        )
        return out
    if report.get("rebuilt"):
        sys.stderr.write(f"   rule 35: {report['rebuilt']}\n")
    out.count("probed_paths", int(report.get("probed", 0)))
    out.count("explained_statements", int(report.get("explained_statements", 0)))
    declared = int(report.get("lookup_columns_declared", 0))
    untyped = int(report.get("index_served_untyped", 0))
    proven = int(report.get("lookup_columns_proven", 0))
    unproven = int(report.get("lookup_columns_unproven", 0))
    out.count("lookup_columns_declared", declared)
    out.count("lookup_columns_proven", proven)
    out.count("lookup_columns_unproven", unproven)
    out.count("index_served_untyped", untyped)
    out.findings.extend(_untyped_ratchet(root, untyped))
    out.findings.extend(_unproven_ratchet(root, unproven))
    out.findings.extend(_vacuous_negatives(root, rule, report.get("plan_shapes") or {}))
    for note in report.get("notes", []):
        if "UNPROVEN" in str(note) or "is proven at gate scale" in str(note):
            # The world every declaration rests on, printed on every run. A
            # number a reviewer never sees is a blind spot, not a measurement.
            out.count("lookup_world_reported", 1)
    for finding in report.get("findings", []):
        dotted = str(finding).split(":", 1)[0]
        out.hit(_dotted_to_file(root, dotted), 0, str(finding))
    return out


def _unproven_ratchet(root: Path, unproven: int) -> list[Finding]:
    """`lookup_columns_unproven` may fall and never rise (b)).

    The declaration says a named column's predicate IS the lookup. That is only
    an assertion in a world where the planner could have chosen otherwise; on a
    nought-row table under `enable_seqscan = off` it is a restatement of the
    setting. Four of the five declarations were in that state when this was
    built — the header's own sizing argument, applied to one table out of five —
    and nothing said so. It is not a violation (the harness holds the evidence
    for those columns), it is a POPULATION, so it lives under the same
    rising-floor grammar as `index_served_untyped`: it may shrink, never grow.

    The finding points at `quality/hotpaths.py` and not at the budgets file,
    because the thing that has to change to shrink it is the WORLD.
    """
    ceiling = budget_ceiling(root, "hot_path_lookup_columns", "lookup_columns_unproven")
    if ceiling is None:
        return [
            Finding(
                "quality/hotpaths.py",
                0,
                "hot_path_lookup_columns.lookup_columns_unproven is not recorded — the "
                f"{unproven} declared lookup column(s) sitting on a probe table too small "
                "to falsify them are an undeclared population; record the measured number "
                "in quality/budgets.yaml",
            )
        ]
    bound = Bound(
        direction="ceiling",
        recorded=ceiling,
        measured=unproven,
        home=f"{BUDGETS_FILE} `hot_path_lookup_columns:`",
        klass="lookup_columns_unproven",
        word="ratchet",
    )
    if bound.breached:
        return [
            Finding(
                "quality/hotpaths.py",
                0,
                f"{bound.breach_clause()} — a declared lookup column has lost the world that "
                "made it an "
                "assertion. Either the probe world shrank (quality/hotpaths.py sizes it, "
                "and says what the sizes buy) or a new declaration landed on a table that "
                "has no rows. Grow the world, or raise the number in a diff a reviewer "
                "reads",
            )
        ]
    return []


def _vacuous_negatives(root: Path, rule: dict, shapes: dict) -> list[Finding]:
    """A planted negative must actually CONTAIN the shape it claims to exempt.

    A negative is silent for one of two reasons: the rule shows restraint, or
    the shape was never there. Those look identical from outside, and rule 35
    shipped one of each for a cycle — `filtered_audit_read.py` claimed to exempt
    "a Filter beside an Index Cond" while the planner folded its predicate into
    the Index Cond, so no `Filter:` was ever produced and the negative proved
    nothing at all ().

    So a rule-35 negative may declare `plan_shape: {marker, path, table,
    contains}`. `marker` is a string the fixture carries; when it is present in
    the plant target the fixture IS planted, and the shape it names must be in
    the plans the probe just read. When it is absent this costs nothing — which
    is every ordinary run.
    """
    out: list[Finding] = []
    for entry in rule.get("negatives") or []:
        shape = entry.get("plan_shape")
        if not shape:
            continue
        target = root / str(entry.get("plant_at", ""))
        if not target.is_file() or str(shape.get("marker", "")) not in _read(target):
            continue
        seen = (shapes.get(str(shape.get("path"))) or {}).get(str(shape.get("table"))) or []
        wanted = str(shape.get("contains"))
        if not any(wanted in str(item) for item in seen):
            out.append(
                Finding(
                    str(entry.get("plant_at", "quality/rules.yaml")),
                    0,
                    f"VACUOUS NEGATIVE — {entry.get('fixture')} is planted and claims to "
                    f"exempt {wanted!r} on {shape.get('table')}, but the plans for "
                    f"{shape.get('path')} carry {seen or 'nothing for that table'}. A "
                    "negative that is silent because the shape was never there proves the "
                    "rule ignores something nobody wrote; rewrite the fixture until its "
                    "plan carries the shape, then the silence means restraint",
                )
            )
    return out


def _untyped_ratchet(root: Path, untyped: int) -> list[Finding]:
    """`index_served_untyped` may fall and never rise (F2-4).

    The declared blind spot of the subject-column form is the population that
    has NOT declared one: those entries keep the weak any-Index-Cond semantics
    P-1 walked through. A blind spot that can grow while nobody looks is not a
    declared blind spot, so the size of it is a number in `budgets.yaml` and
    growth is a violation — the same rising-floor grammar every other budget
    uses, checked on every run rather than only against a diff, because a fresh
    checkout has no diff and the population is a property of the tree.
    """
    ceiling = budget_ceiling(root, "hot_path_lookup_columns", "index_served_untyped")
    if ceiling is None:
        return [
            Finding(
                "quality/budgets.yaml",
                0,
                "hot_path_lookup_columns.index_served_untyped is not recorded — the "
                f"{untyped} index_served table(s) keeping the weak any-Index-Cond "
                "semantics are an undeclared population, which is how P-1 stayed "
                "invisible; record the measured number",
            )
        ]
    bound = Bound(
        direction="ceiling",
        recorded=ceiling,
        measured=untyped,
        home=f"{BUDGETS_FILE} `hot_path_lookup_columns:`",
        klass="index_served_untyped",
        word="ratchet",
    )
    if bound.breached:
        return [
            Finding(
                BUDGETS_FILE,
                0,
                f"{bound.breach_clause()} — a new index_served table arrived with no "
                "`lookup_columns`, "
                "so its scan is index-served by whatever Index Cond happens to be there "
                "(the tenant leg, typically). Declare the column, or raise the number in "
                "a diff a reviewer reads",
            )
        ]
    return []
