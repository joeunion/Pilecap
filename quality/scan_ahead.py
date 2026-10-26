"""Unmemoised rule scans run across processes and replay in order; a failed one rescans."""

from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from typing import Any

#: The valve: `1` scans in the gate's own process, in order; unset is the box's cores, capped.
WORKERS_ENV = "DJB_RULES_WORKERS"
#: The cap when unset — past it the spawn cost outruns the scans it splits.
DEFAULT_CAP = 8


def workers() -> tuple[int, str]:
    """(processes, why) — the typed valve when set, else the cores capped at `DEFAULT_CAP`."""
    typed = os.environ.get(WORKERS_ENV, "").strip()
    if typed:
        try:
            return max(1, int(typed)), f"{WORKERS_ENV}={typed}"
        except ValueError:
            return 1, f"{WORKERS_ENV}={typed!r} is not a number — scanned in order"
    cores = os.cpu_count() or 1
    return max(1, min(DEFAULT_CAP, cores)), f"{cores} cores, capped at {DEFAULT_CAP}"


def _scan_one(rid: str) -> tuple[str, Any, BaseException | None, str, list[str], list[str]]:
    """One rule's check in a worker: (id, result, raised, printed, new broken, new notes)."""
    from quality import gate as G

    rule = G.RULES_BY_ID[rid]
    printed = io.StringIO()
    broken_at, notes_at = len(G.broken), len(G.notes)
    result: Any = None
    raised: BaseException | None = None
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
        try:
            result = G.REGISTRY[str(rule["check"])](G.ROOT, rule)
        except Exception as exc:  # replayed in the gate's own process, in rule order
            raised = exc
    return rid, result, raised, printed.getvalue(), G.broken[broken_at:], G.notes[notes_at:]


def scan_ahead(rids: Iterable[str], processes: int) -> tuple[dict[str, tuple], list[str]]:
    """({id: (result, raised, printed, broken, notes)}, ids left to scan in order)."""
    wanted = list(rids)
    answers: dict[str, tuple] = {}
    dropped: list[str] = []
    if processes <= 1 or len(wanted) < 2:
        return answers, wanted
    try:
        with ProcessPoolExecutor(
            max_workers=min(processes, len(wanted)), mp_context=get_context("spawn")
        ) as pool:
            futures = {pool.submit(_scan_one, rid): rid for rid in wanted}
            for future in as_completed(futures):
                rid = futures[future]
                try:
                    _rid, result, raised, printed, broken, notes = future.result()
                except Exception:
                    dropped.append(rid)
                    continue
                answers[rid] = (result, raised, printed, broken, notes)
    except Exception:
        return {}, wanted
    return answers, sorted(dropped)
