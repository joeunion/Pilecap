"""The dispatch ledger's inputs checked: briefs and reports as `ledger_derive` reads them, the archive's armed rows."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import sys
import time

_SCRIPTS = str(pathlib.Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# One reader for one grammar (principle 11): rows and stamps are loop_metrics'.
import loop_metrics as lm  # noqa: E402

from quality.could_not_look import CouldNotLook as CannotLook  # noqa: E402

# The day this leg was armed: archived rows sent earlier are history kept verbatim and are not judged.
ARMED_ON = dt.datetime(2026, 10, 4)
# The day the table became derived (`ledger_derive.ARMED_ON`): a live row sent since is a hand table.
DERIVED_ON = dt.datetime(2026, 10, 25)
#: The line that stands where the live table was.
POINTER_LINE = "The dispatch ledger is derived: `.venv/bin/python scripts/ledger_derive.py`"
CELLS = 7

# measured at the commit: docs/product/in-flight.md — the hook runs --check on the staged bytes (rule 90)
LIVE = "docs/product/in-flight.md"
# The archive is derived beside the live file; none (a product's day zero) is nothing archived.
ARCHIVE_GLOB = "archive/in-flight-*.md"
#: Where the pre-commit hook exports the index's copies of the declared paths; unset, the working tree.
STAGED_ROOT = "DJB_STAGED_ROOT"
# Both table headers name the same seven columns; cell 1 is who, cell 2 is what.
# does-not-cover: whether a stamp or a verdict is TRUE — a shape check over the PM's own claims.
# does-not-cover: tables outside in-flight.md § "Dispatch ledger" and the archive's `### … — pruned` stages.
# does-not-cover: the archive at the commit — the hook exports the live file alone; the archive is judged at `--fast`.
# does-not-cover: a row whose State lacks a RETURNED word — a `done` or `banked` State with Returned filled is not held to stamps or a pointer.
# does-not-cover: an archived row in a stage pruned before ARMED_ON whose Sent cell and `sent=` stamp are both unreadable.
# does-not-cover: rows pruned before ARMED_ON — history kept verbatim.
# does-not-cover: what the CLOSE row's number means — any `$<digit>` or `… per rung` in the row satisfies it.
# does-not-cover: an open (unstruck) spend row — only a closed one owes its number.
# does-not-cover: a commit that skipped the hook (a merge, a rebase, `--no-verify`) — measured at the next `--fast`.
# does-not-cover: briefs and reports at the commit — the hook exports the live file alone; they are judged at `--fast`.
# does-not-cover: a pull request's state — `gh` is `ledger_derive`'s, never this check's (no network at the commit).
_LIVE_HEADING = "## Dispatch ledger"
# The v2.5.0a1 skeleton's heading for the same table.
_ALPHA_HEADING = "## Live dispatch table"
_STAGE_HEADING = re.compile(r"^### .* — pruned (\d{4}-\d{2}-\d{2}) \d{1,2}:\d{2}\s*$")
RETURNED = re.compile(r"\b(returned|merged|landed|verified|met)\b", re.IGNORECASE)
_LANDED = re.compile(r"\b(merged|landed)\b", re.IGNORECASE)
_PM_ROW = re.compile(r"^(TRAIN|PM)-")
# A lead's artifact is its plan, not a report.
_LEAD_ROW = re.compile(r"^LEAD-")
POINTER = re.compile(r"\b(?:docs/product/)?reports/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.md\b")
PLAN_POINTER = re.compile(r"\b(?:docs/product/)?cycles/[A-Za-z0-9_.-]+\.md\b")
_CLOSE_ROW = re.compile(r"spend per rung|cost baseline", re.IGNORECASE)
_CLOSED = re.compile(r"\b(struck|closed)\b|~~", re.IGNORECASE)
_SPEND = re.compile(r"\$\s?\d|\d[\d.,]*\s*(?:\$|USD)?\s*per rung", re.IGNORECASE)
_PIPE_IN_TICKS = re.compile(r"`[^`]*\|[^`]*`")
_DATED_STAMP = re.compile(r"^(?:[0-9a-f]{7,40}\s+)?\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}(?:\s*PDT)?$")


def read_lines(path: str) -> list[str]:
    """The file's lines, or could-not-look naming it."""
    if not os.path.isfile(path):
        raise lm.refuse(f"the ledger file is absent: {path} — nothing was judged.")
    with open(path, encoding="utf-8") as handle:
        return handle.read().splitlines()


def archives(live: str) -> list[str]:
    """The archive files beside the live file, sorted; empty when it has none."""
    return sorted(str(p) for p in pathlib.Path(live).parent.glob(ARCHIVE_GLOB) if p.is_file())


def stages(
    path: str, lines: list[str], live: bool, *, required: bool = True
) -> list[tuple[str, int, int]]:
    """`(heading, first line, last line)` of each stage the file holds, 1-based and inclusive."""
    found: list[tuple[str, int, int]] = []
    open_stage = False
    for lineno, line in enumerate(lines, start=1):
        if open_stage and line.startswith("## " if live else "#"):
            found[-1] = (found[-1][0], found[-1][1], lineno - 1)
            open_stage = False
        if (line.strip() == _LIVE_HEADING) if live else _STAGE_HEADING.match(line):
            found.append((line.strip(), lineno, len(lines)))
            open_stage = True
    if not found and live and any(line.startswith(POINTER_LINE) for line in lines):
        return found
    if not found and required:
        want = (
            f"`{_LIVE_HEADING}` section or derived-ledger pointer line"
            if live
            else "`### … — pruned <date time>` stage"
        )
        hint = (
            f" — rename `{_ALPHA_HEADING}` to `{_LIVE_HEADING}`"
            if live and any(line.strip() == _ALPHA_HEADING for line in lines)
            else ""
        )
        raise lm.refuse(f"{path} carries no {want}{hint} — nothing was judged.")
    return found


def sent_at(row: lm.Row, cells: list[str]) -> dt.datetime | None:
    """The row's dispatch time from its Sent column or its `sent=` stamp; None when neither reads."""
    for raw in (
        cells[4] if len(cells) > 4 else "",
        *(v for k, v in stamp_fields(row) if k == "sent"),
    ):
        dated = lm._DATED.match(raw.replace("PDT", "").strip())
        if dated:
            return dt.datetime.strptime(
                f"{dated.group(1)} {dated.group(2)}:{dated.group(3)}", "%Y-%m-%d %H:%M"
            )
    return None


def stamp_fields(row: lm.Row) -> list[tuple[str, str]]:
    """The stamps cell's fields as written, through loop_metrics' own splitter."""
    found = lm._STAMPS_CELL.search(row.notes)
    return lm.split_stamps(found.group(1)) if found else []


def armed(row: lm.Row | None, cells: list[str], stage_day: str | None) -> bool:
    """Every live row is judged; an archived row only when it was sent, or its stage pruned, on or after ARMED_ON."""
    if stage_day is None:
        return True
    if dt.datetime.strptime(stage_day, "%Y-%m-%d") >= ARMED_ON:
        return True
    if row is None:
        dated = lm._DATED.match(cells[4].replace("PDT", "").strip()) if len(cells) > 4 else None
        when = (
            dt.datetime.strptime(
                f"{dated.group(1)} {dated.group(2)}:{dated.group(3)}", "%Y-%m-%d %H:%M"
            )
            if dated
            else None
        )
    else:
        when = sent_at(row, cells)
    return when is not None and when >= ARMED_ON


def _cell_count(where: str, raw: str, count: int) -> str:
    """The cell-count refusal; the backtick clause only when the line carries a `|` inside backticks."""
    why = " (a `|` inside backticks still splits a cell)" if _PIPE_IN_TICKS.search(raw) else ""
    return f"{where}: row has {count} cells, not the header's {CELLS}{why}"


def skipped_lines(lines: list[str], first: int, last: int, read: set[int]) -> list[int]:
    """The stage's table lines the one reader returned no row for: data-shaped, not the header or separator."""
    out: list[int] = []
    for lineno in range(first, last + 1):
        line = lines[lineno - 1]
        if not line.startswith("|") or lineno in read:
            continue
        body = line.strip().strip("|")
        if set(body.replace("|", "").replace(" ", "")) <= {"-", ":"}:
            continue
        head = body.split("|", 1)[0].strip()
        if head == "#" or head.startswith("EXAMPLE"):
            continue
        out.append(lineno)
    return out


def check_row(row: lm.Row, raw: str) -> list[str]:
    """Every refusal one armed row earns, one line each."""
    out: list[str] = []
    cells = raw.strip().strip("|").split("|")
    if len(cells) != CELLS:
        out.append(_cell_count(row.where(), raw, len(cells)))
    for field, value in stamp_fields(row):
        if (
            field in lm.RUNG_STAGES
            and value.strip() not in lm._NOT_REACHED
            and not _DATED_STAMP.match(value.strip())
        ):
            out.append(
                f"{row.where()}: the `{field}` stamp reads `{value.strip()}` — a stage stamp is dated (`YYYY-MM-DD HH:MM`), never a bare time"
            )
    try:
        lm.parse_stamps(row)
    except CannotLook as exc:
        out.append(f"{row.where()}: stamps refused — {str(exc).splitlines()[0]}")
        return out
    if RETURNED.search(row.state):
        if not row.stamped:
            out.append(
                f"{row.where()}: returned row (state `{row.state[:40]}`) carries no `stamps:` cell"
            )
        if _PM_ROW.match(row.ident):
            if _LANDED.search(row.state) and not row.merged_sha:
                out.append(
                    f"{row.where()}: PM row (state `{row.state[:40]}`) carries no merge sha in its `merged=` stamp"
                )
        elif _LEAD_ROW.match(row.ident):
            if not PLAN_POINTER.search(raw):
                out.append(
                    f"{row.where()}: lead row (state `{row.state[:40]}`) carries no `docs/product/cycles/<plan>.md` pointer"
                )
        elif not POINTER.search(raw):
            out.append(
                f"{row.where()}: returned row (state `{row.state[:40]}`) carries no `docs/product/reports/<cycle>/<id>.md` pointer"
            )
    if (
        _CLOSE_ROW.search(f"{row.task} {row.role}")
        and _CLOSED.search(f"{row.state} {raw}")
        and not _SPEND.search(raw)
    ):
        out.append(
            f"{row.where()}: the CLOSE row measuring spend per rung is closed without its number (`$…` or `… per rung`)"
        )
    return out


def check(live: str, archive: list[str] | None) -> tuple[list[str], int, int]:
    """`(findings, rows judged, rows read)` over the live table and the archives' armed rows; `None` derives them."""
    findings: list[str] = []
    judged = read = 0
    named = archive is not None
    held = archive if archive is not None else archives(live)
    files = [(live, True)] + [(path, False) for path in held]
    # A short line is judged here, never by `loop_metrics.read_rows`, which skips it.
    for path, is_live in files:
        lines = read_lines(path)
        all_rows = lm.read_rows(path)
        for heading, first, last in stages(path, lines, is_live, required=is_live or named):
            rows = [row for row in all_rows if first <= row.lineno <= last]
            read += len(rows)
            if is_live:
                late = [row.ident for row in rows if derived_since(row, lines[row.lineno - 1])]
                if late:
                    findings.append(
                        f"{path}:{first} `{heading}`: {len(late)} row(s) sent on or after {DERIVED_ON:%Y-%m-%d} ({', '.join(late[:5])}) — the table is derived (`scripts/ledger_derive.py`); delete it"
                    )
            day = None if is_live else _STAGE_HEADING.match(heading).group(1)  # type: ignore[union-attr]
            for lineno in skipped_lines(lines, first, last, {row.lineno for row in rows}):
                raw = lines[lineno - 1]
                cells = [c.strip() for c in raw.strip().strip("|").split("|")]
                read += 1
                if armed(None, cells, day):
                    judged += 1
                    findings.append(
                        _cell_count(f"{cells[0] or '?'} ({path}:{lineno})", raw, len(cells))
                    )
            for row in rows:
                raw = lines[row.lineno - 1]
                if is_live and derived_since(row, raw):
                    continue
                if armed(row, [c.strip() for c in raw.strip().strip("|").split("|")], day):
                    judged += 1
                    findings += check_row(row, raw)
    return findings, judged, read


def derived_since(row: lm.Row, raw: str) -> bool:
    """True when a live row was sent on or after DERIVED_ON — a row the derivation owns."""
    when = sent_at(row, [c.strip() for c in raw.strip().strip("|").split("|")])
    return when is not None and when >= DERIVED_ON


def inputs(live: str) -> tuple[list[str], str]:
    """`(findings, coverage)` over the briefs and reports beside the live file, through ledger_derive."""
    product = pathlib.Path(live).resolve().parent
    if not (product / "briefs").is_dir() or product.parts[-2:] != ("docs", "product"):
        return [], "no briefs beside the live file — none judged"
    import ledger_derive

    return ledger_derive.check(product.parent.parent)


def main(argv: list[str]) -> int:
    """Exit 0 clean · 1 a row, the live table, a brief or a report refused, each named · 2 could not look."""
    parser = argparse.ArgumentParser(prog="ledger_check.py", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--in-flight", default=LIVE)
    parser.add_argument(
        "--archive",
        action="append",
        help=f"repeatable; default every {ARCHIVE_GLOB} beside --in-flight",
    )
    args = parser.parse_args(argv)
    if os.environ.get(STAGED_ROOT):
        os.chdir(os.environ[STAGED_ROOT])
    started = time.time()
    try:
        findings, judged, read = check(args.in_flight, args.archive)
    except CannotLook as exc:
        print(f"!! COULD NOT LOOK: {exc}", file=sys.stderr)
        return 2
    try:
        derived, coverage = inputs(args.in_flight)
    except CannotLook as exc:
        print(f"!! COULD NOT LOOK: {exc}", file=sys.stderr)
        return 2
    findings += derived
    elapsed = time.time() - started
    for finding in findings:
        print(f"!! ledger-check: {finding}")
    verdict = f"{len(findings)} refusal(s)" if findings else "clean"
    rows = f"{judged} of {read} rows armed" if read else "0 rows"
    held = args.archive if args.archive is not None else archives(args.in_flight)
    where = f"archive armed on {ARMED_ON:%Y-%m-%d}" if held else "no archive — nothing archived"
    print(f"== ledger-check: {verdict} · {rows} ({where}) · {coverage} · {elapsed:.3f}s")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
