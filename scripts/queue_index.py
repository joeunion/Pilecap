#!/usr/bin/env python3
"""The queue's index/detail generator, migration and consistency check.

WHY THIS EXISTS. One file was carrying both the order of the work and the
whole record of every finding, and it crossed a third of a megabyte — half of
everything a cold agent is told to read before it does anything. The split is
the compression: the record stays whole, VERBATIM, in the detail file; the
ordered file becomes a GENERATED index, one line per row, that nobody edits.

THE CONTRACT, in one paragraph. `<detail>` is the record: every row of the
old single file, byte for byte, in its own order, with a stable `### N<id>`
anchor line inserted immediately before each row-defining line. `<index>` is
DERIVED from it and is never edited by hand: the file's preamble (everything
before the first row-defining line, which is where the ROW STATUS block that
`scripts/queue_cited.sh` reads as the triage authority lives) is carried over
verbatim, then every `##`/`###` heading verbatim, then one line per anchor.
Every number this file prints is read off the detail file; none is typed.

THE FOUR MODES.

    --split  <index> <detail>   the migration: write <detail> from today's
                                single <index>, then write the index over it.
                                Refuses if <detail> exists or <index> is
                                already a generated index (exit 2).
    --index  [<index> <detail>] regenerate <index> from <detail>.
    --check  [<index> <detail>] the gate leg: regenerate in memory, compare,
                                and run the consistency checks below.
    --unsplit <detail> [<out>]  strip the anchor lines — reproduces the
                                pre-split single file BYTE FOR BYTE.

EXIT STATUS, the house semantics: 0 clean · 1 violations (a disagreement it
looked at and judged) · 2 could-not-look, or a refusal (an absent or
unreadable detail file, an index whose header it cannot parse, an unknown
flag). 2 outranks a pass and is never a judgment on the readable half.

THE THREE STATES `--check` TELLS APART, and why it is three rather than two.
The migration is run ONCE, by hand, at merge — so this check is registered in
the gate on trees where the split has not happened yet, and a two-state
instrument would either red every one of them or go blind on a deleted record.
The discriminator is DERIVED — whether `<index>` carries the generated header
— never a bare "does the file exist", because that test cannot tell the two
apart and answering both with one verdict is the silent narrowing this whole
instrument exists to refuse:

    no header, no record   PRE-SPLIT. Exit 0, and it SAYS SO — a named
                           absence, with the command that ends it. Nothing was
                           checked and the line does not pretend otherwise.
    no header, a record    HALF-MIGRATED: the record stands, the index was
                           replaced by hand. Exit 2.
    a header, no record    THE RECORD IS GONE and a generated index still
                           claims to summarise it. Exit 2, and the readable
                           index is deliberately NOT judged.

WHAT `--check` JUDGES, each one exit 1 and each one naming the id:

    1. every anchor is unique, and immediately precedes a row-defining line;
    2. every row-defining line in the detail is immediately preceded by its
       own anchor;
    3. every anchor has exactly one index row and every index row has exactly
       one anchor (the id population is READ OFF THE ANCHORS, never typed);
    4. every index head is the row's own text, verbatim, truncated and
       nothing else;
    5. every index status agrees with the row's own strike;
    6. the queue-citation parser reads the generated index exactly as it read
       the pre-split rows (the parity check below);
    7. the whole index equals its own regeneration (a hand edit is caught
       here even where 1-6 pass), naming the first differing line;
    8. the index is at or under its recorded byte ceiling;
    9. the over-long-row census count is at or under its recorded floor.

THE PARITY CHECK, and why the index line looks the way it does.
`scripts/queue_cited.sh` classifies a queue row by two shapes and reads the id
out of the line's leading 40 characters. That classifier is replicated here
(`classify`) rather than approximated, and `--check` runs it over the
GENERATED index and asserts the (id, status) sequence it yields equals the
one the detail's rows yield. That is the whole of "the consumers are
unchanged", made executable instead of asserted. It is also why the emitted
line closes its bold AFTER the status rather than after the id: measured on
that classifier, `- **N9001** . open .` reads as NO ROW AT ALL (the id is
followed by an asterisk, and the open shape wants a space, `(` or `:`), while
`- **N9001 . open** .` reads as open. The struck shape reads correctly either
way. A generated line that would be misread is a violation here, not a
surprise in somebody else's census two weeks later.

THE TWO RATCHETS. Both numbers live in the generated header, on their own
line, and both move DOWN by machine and UP only by a human:

    CEILING:  the index's byte ceiling. Set at migration to the generated
              size + 20% rounded up to the KB, lowered by the generator
              whenever the regenerated index falls under 80% of it, and
              raised only by editing the line -- which is a conspicuous diff
              by design, and the place to write the reason.
    LONGROWS: the number of rows over 1,500 characters. There is deliberately
              NO per-row ceiling: a refusal that produces `--no-verify` is
              worse than a census that produces pruning. This closes the
              class (no further report-shaped row) without refusing any row
              that already exists.

Everything after the number on either line is carried through regeneration
verbatim, so a hand-raised number keeps its reason beside it.

WHAT THIS DOES NOT COVER, declared rather than discovered:

    a. WHETHER A ROW IS TRUE, or in the right order, or held by the right
       person. This is a shape check over two files and nothing else.
    b. TWO ROWS WHOSE FIRST 92 CHARACTERS ARE THE SAME read identically in
       the index. The anchor still disambiguates them; the human eye does
       not.
    c. AN ID THAT CARRIES TWO ROW LINES is a declared population in the queue
       itself (a row and its own later addendum). The second and further
       lines take a `(2)`, `(3)` suffixed anchor so the anchor set stays a
       key; the index still prints the bare id, so two lines in the index can
       show the same id.
    d. A LANE-PREFIXED BULLET whose leading 40 characters happen to name a
       DIFFERENT row's id is attributed to that id -- inherited from the
       classifier this file replicates on purpose, because divergence there
       would be a silent disagreement with the census that consumes the file.
    e. RENDERING. An anchor line inserted before a table row splits that
       table where it renders. The detail file is a record, and the anchor is
       what makes it addressable; this is the cost, taken knowingly.
    f. A PRODUCT THAT RENAMES OR DROPS THE QUEUE inherits a check about a
       file it no longer has. The skeleton says so.
    g. A FULL REVERSAL OF THE MIGRATION READS AS PRE-SPLIT, and therefore as
       exit 0. Unsplit the record back over the index and delete the record,
       and the tree is byte-for-byte the tree that existed before the
       migration — there is nothing left for the third state above to see, so
       it answers with the first one. Measured, on a copy: `--unsplit` over
       the index, `rm` the record, `--check` prints the PRE-SPLIT banner and
       exits 0. THIS IS VISIBLE RATHER THAN SILENT — the banner says in as
       many words that nothing was checked and names the command that ends
       it, and the drive's own case asserts that banner, which is the belt
       while this holds. A HALF reversal is still caught: the record surviving
       beside a hand-restored index is state two, exit 2.
       ITS CLOSING TRIGGER, named rather than left open: the day the SKELETON
       ships already split — the skeleton index generated from the skeleton
       record, so a clone is born with the header — the generated header
       becomes REQUIRED rather than merely expected, PRE-SPLIT becomes exit 2
       like the other two absences, and this blind spot closes with it.
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import NamedTuple

DEFAULT_INDEX = "docs/product/queue.md"
DEFAULT_DETAIL = "docs/product/queue-detail.md"

# The head width `scripts/queue_cited.sh` reads an id out of, and its two row
# shapes. Replicated, not approximated -- see THE PARITY CHECK above.
HEAD_WIDTH = 40
RE_TABLE_STRUCK = re.compile(r"^\| *~~N[0-9]+[a-z]?~~")
RE_TABLE_OPEN = re.compile(r"^\| *N[0-9]+[a-z]?[ )]")
RE_STRUCK_IN_HEAD = re.compile(r"~~N[0-9]+[a-z]?~~")
RE_OPEN_IN_HEAD = re.compile(r"N[0-9]+[a-z]?[ (:]")
RE_ID = re.compile(r"N[0-9]+[a-z]?")

# The anchor line, and the index line it is read back out of.
RE_ANCHOR = re.compile(r"^### (N[0-9]+[a-z]?)(?: \(([0-9]+)\))?$")
RE_HEADING = re.compile(r"^#{2,6} ")


def index_row_re(detail_name: str) -> re.Pattern[str]:
    """The index line, read back. The bold closes AFTER the status, so the
    non-greedy meta cannot run into a head that carries its own `**`."""
    return re.compile(
        r"^- \*\*(?P<meta>[^*]*)\*\* · (?P<head>.*) → "
        + re.escape(detail_name)
        + r"#(?P<slug>\S+)$"
    )


# The row's own tokens, where they parse. Nothing here invents a field: a row
# with neither token gets neither.
RE_SEVERITY = re.compile(r"^\(([A-Z][A-Z0-9-]{0,15})[ ,)]")
RE_HOLDER = re.compile(r"Holder:\s*([^.|]{1,44})")

HEAD_CHARS = 92
LONG_ROW_CHARS = 1500
CEILING_HEADROOM = 1.20
CEILING_SLACK = 0.80

CEILING_PREFIX = "CEILING: "
LONGROWS_PREFIX = "LONGROWS: "

GENERATOR = "scripts/queue_index.py"
# THE INTERPRETER EVERY REMEDY BELOW NAMES, and it is this checkout's rather
# than `python3`. This file is written at the version the venv holds and it uses
# it (`zip(..., strict=True)`); a verifier box's system `python3` is 3.9, where
# that is `TypeError: zip() takes no keyword arguments`. A remedy that printed
# `python3` told the reader on such a box to reproduce the interpreter mismatch
# by hand. `scripts/check.sh`'s own queue-index leg resolves the same path
# through `checkout_python` (scripts/gate_refuse.sh).
INTERPRETER = ".venv/bin/python"


class Refusal(Exception):
    """Could not look, or will not act. Exit 2."""


class Row(NamedTuple):
    lineno: int  # 1-based, in the detail file
    text: str  # the row-defining line, verbatim
    ident: str  # the id the queue-citation parser reads off it
    status: str  # "open" or "struck"
    rest: str  # the row's own text after its id token, left-stripped
    slug: str  # the anchor slug it is addressed by
    anchor: str  # the anchor line, verbatim


# --------------------------------------------------------------------------
# the classifier, replicated from scripts/queue_cited.sh
# --------------------------------------------------------------------------


def classify(line: str) -> tuple[str, str, str] | None:
    """Return (status, id, rest-after-the-id) for a row-defining line.

    The two shapes and the 40-character head are the queue-citation census's,
    byte for byte. `rest` is what the index quotes from: everything after the
    id token, left-stripped of whitespace and nothing else.
    """
    head = line[:HEAD_WIDTH]
    if RE_TABLE_STRUCK.match(line) or (line.startswith("- **") and RE_STRUCK_IN_HEAD.search(head)):
        token = RE_STRUCK_IN_HEAD.search(head)
        ident = RE_ID.search(head)
        if token is None or ident is None:  # pragma: no cover - both matched above
            return None
        return ("struck", ident.group(0), line[token.end() :].lstrip())
    if RE_TABLE_OPEN.match(line) or (line.startswith("- **") and RE_OPEN_IN_HEAD.search(head)):
        ident = RE_ID.search(head)
        if ident is None:
            return None
        return ("open", ident.group(0), line[ident.end() :].lstrip())
    return None


def slug_for(ident: str, occurrence: int) -> str:
    """The anchor's fragment. `### N9001` -> `n9001`; `### N9001 (2)` -> `n9001-2`."""
    base = ident.lower()
    return base if occurrence == 1 else f"{base}-{occurrence}"


def anchor_for(ident: str, occurrence: int) -> str:
    return f"### {ident}" if occurrence == 1 else f"### {ident} ({occurrence})"


# --------------------------------------------------------------------------
# reading files
# --------------------------------------------------------------------------


def read_lines(path: str, what: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
    except OSError as exc:
        raise Refusal(f"{what} ({path}) could not be read: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise Refusal(f"{what} ({path}) is not UTF-8: {exc}") from exc
    return body.split("\n")


def write_lines(path: str, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


# --------------------------------------------------------------------------
# the detail file
# --------------------------------------------------------------------------


def add_anchors(source: list[str], source_path: str) -> list[str]:
    """The migration: today's single file, plus one anchor per row line."""
    for lineno, line in enumerate(source, start=1):
        if RE_ANCHOR.match(line):
            raise Refusal(
                f"{source_path}:{lineno} already carries an anchor-shaped line "
                f"({line!r}). The split would not be reversible byte for byte, "
                "so it is refused rather than attempted."
            )
    seen: dict[str, int] = {}
    out: list[str] = []
    for line in source:
        verdict = classify(line)
        if verdict is not None:
            _status, ident, _rest = verdict
            seen[ident] = seen.get(ident, 0) + 1
            out.append(anchor_for(ident, seen[ident]))
        out.append(line)
    return out


def strip_anchors(detail: list[str]) -> list[str]:
    return [line for line in detail if not RE_ANCHOR.match(line)]


def parse_detail(detail: list[str], path: str) -> tuple[list[Row], list[str]]:
    """Rows read off the anchors, and the structural findings, in file order."""
    findings: list[str] = []
    rows: list[Row] = []
    anchors_seen: dict[str, int] = {}
    for i, line in enumerate(detail):
        match = RE_ANCHOR.match(line)
        if match is None:
            continue
        ident = match.group(1)
        occurrence = int(match.group(2)) if match.group(2) else 1
        slug = slug_for(ident, occurrence)
        anchors_seen[slug] = anchors_seen.get(slug, 0) + 1
        if anchors_seen[slug] > 1:
            findings.append(
                f"{path}:{i + 1}: DUPLICATE ANCHOR {line!r} — an anchor is a key, and this "
                f"is its {anchors_seen[slug]}th use"
            )
            continue
        following = detail[i + 1] if i + 1 < len(detail) else ""
        verdict = classify(following)
        if verdict is None:
            findings.append(
                f"{path}:{i + 1}: anchor {ident} is not immediately followed by a "
                f"row-defining line (the next line is {following[:60]!r}) — an anchor "
                "with no row has no index row either"
            )
            continue
        status, row_ident, rest = verdict
        if row_ident != ident:
            findings.append(
                f"{path}:{i + 2}: anchor {ident} sits before a row the citation parser "
                f"reads as {row_ident}"
            )
            continue
        rows.append(
            Row(
                lineno=i + 2,
                text=following,
                ident=ident,
                status=status,
                rest=rest,
                slug=slug,
                anchor=line,
            )
        )
    # every row-defining line is preceded by its own anchor
    for i, line in enumerate(detail):
        if classify(line) is None:
            continue
        previous = detail[i - 1] if i >= 1 else ""
        if RE_ANCHOR.match(previous) is None:
            ident = classify(line)[1]  # type: ignore[index]
            findings.append(
                f"{path}:{i + 1}: row {ident} carries NO anchor — it is unaddressable and it "
                "will not appear in the index"
            )
    return rows, findings


# --------------------------------------------------------------------------
# the index
# --------------------------------------------------------------------------


def head_of(rest: str) -> str:
    if len(rest) > HEAD_CHARS:
        return rest[:HEAD_CHARS] + " …"
    return rest


def meta_of(row: Row) -> str:
    id_token = f"~~{row.ident}~~" if row.status == "struck" else row.ident
    parts = [id_token, row.status]
    severity = RE_SEVERITY.match(row.rest)
    if severity:
        parts.append(severity.group(1))
    holder = RE_HOLDER.search(row.text)
    if holder:
        cleaned = holder.group(1).replace("·", " ").replace("~", "").replace("*", "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned:
            parts.append(f"Holder: {cleaned}")
    return " · ".join(parts)


def index_line(row: Row, detail_name: str) -> str:
    return f"- **{meta_of(row)}** · {head_of(row.rest)} → {detail_name}#{row.slug}"


def kb_ceiling(size: int) -> int:
    target = int(size * CEILING_HEADROOM)
    return -(-target // 1024) * 1024


def long_rows(rows: list[Row]) -> tuple[list[str], int]:
    ids = [r.ident for r in rows if len(r.text) > LONG_ROW_CHARS]
    total = sum(len(r.text.encode("utf-8")) for r in rows if len(r.text) > LONG_ROW_CHARS)
    return ids, total


def read_recorded(index: list[str], prefix: str) -> tuple[int, str] | None:
    """The recorded number and the whole line it lives on, carried verbatim."""
    for line in index:
        if line.startswith(prefix):
            tail = line[len(prefix) :]
            digits = re.match(r"([0-9]+)", tail)
            if digits is None:
                raise Refusal(
                    f"the generated header's {prefix.strip()} line does not start with a "
                    f"number: {line!r}. Nothing was judged."
                )
            return int(digits.group(1)), line
    return None


def build_index(
    detail: list[str],
    rows: list[Row],
    detail_path: str,
    ceiling_line: str,
    longrows_line: str,
) -> list[str]:
    detail_name = os.path.basename(detail_path)
    body = strip_anchors(detail)
    first_row = next((i for i, line in enumerate(body) if classify(line) is not None), len(body))
    ids, total_bytes = long_rows(rows)

    out: list[str] = [
        f"<!-- GENERATED INDEX — DO NOT EDIT THIS FILE. Edit {detail_path}, then run:",
        f"         {INTERPRETER} {GENERATOR} --index",
        f"     Generator: {GENERATOR} · Record: {detail_path}",
        f"     Rows: {len(rows)} · read off the record's anchors, never typed.",
        "     Both numbers below ratchet DOWN by machine and UP only by a human:",
        "     edit the line, and write the reason on it. The diff is the point.",
        ceiling_line,
        longrows_line,
        f"     Long rows now: {len(ids)} over {LONG_ROW_CHARS} chars, {total_bytes} bytes.",
        f"     Long-row ids: {' '.join(ids) if ids else '(none)'}",
        "-->",
    ]
    out.extend(body[:first_row])

    # body index -> line number in the detail file, so a row found by the
    # anchor walk can be placed back in the stripped body's order.
    detail_line_of_body: list[int] = [
        detail_i + 1 for detail_i, line in enumerate(detail) if RE_ANCHOR.match(line) is None
    ]
    row_by_detail_line = {r.lineno: r for r in rows}
    for i in range(first_row, len(body)):
        line = body[i]
        if RE_HEADING.match(line):
            out.append(line)
            continue
        row = row_by_detail_line.get(detail_line_of_body[i])
        if row is not None:
            out.append(index_line(row, detail_name))
    out.append("")
    return out


def generate(
    detail: list[str], rows: list[Row], detail_path: str, existing: list[str] | None
) -> list[str]:
    """The index, with both ratchets applied. Bounded fixpoint on the ceiling."""
    ids, _total = long_rows(rows)
    recorded_ceiling = read_recorded(existing, CEILING_PREFIX) if existing else None
    recorded_longrows = read_recorded(existing, LONGROWS_PREFIX) if existing else None

    # LONGROWS: down by machine, and the recorded line — reason and all — is
    # carried through verbatim wherever the census has not fallen below it.
    if recorded_longrows is None or len(ids) < recorded_longrows[0]:
        longrows_line = f"{LONGROWS_PREFIX}{len(ids)}"
    else:
        longrows_line = recorded_longrows[1]

    keep_recorded = recorded_ceiling is not None
    ceiling_line = recorded_ceiling[1] if recorded_ceiling else f"{CEILING_PREFIX}0"
    for _ in range(8):
        candidate = build_index(detail, rows, detail_path, ceiling_line, longrows_line)
        size = len("\n".join(candidate).encode("utf-8"))
        slack = recorded_ceiling[0] * CEILING_SLACK if recorded_ceiling else 0.0
        if keep_recorded and recorded_ceiling is not None and size >= slack:
            return candidate  # the recorded ceiling stands, verbatim
        wanted = kb_ceiling(size)
        if ceiling_line == f"{CEILING_PREFIX}{wanted}":
            return candidate  # settled
        ceiling_line = f"{CEILING_PREFIX}{wanted}"
        keep_recorded = False
    raise Refusal(
        "the byte ceiling did not settle in eight passes — the index size and the "
        "ceiling it records are chasing each other. Nothing was written."
    )


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------


def check_consistency(
    rows: list[Row], index: list[str], detail_name: str, index_path: str
) -> list[str]:
    findings: list[str] = []
    row_re = index_row_re(detail_name)
    by_slug = {r.slug: r for r in rows}
    seen: set[str] = set()
    for i, line in enumerate(index):
        match = row_re.match(line)
        if match is None:
            continue
        slug = match.group("slug")
        meta = match.group("meta").split(" · ")
        head = match.group("head")
        ident = meta[0].replace("~", "") if meta else ""
        status = meta[1] if len(meta) > 1 else ""
        if slug in seen:
            findings.append(
                f"{index_path}:{i + 1}: index row {ident} points at {slug}, which another "
                "index row already claimed"
            )
            continue
        seen.add(slug)
        row = by_slug.get(slug)
        if row is None:
            findings.append(
                f"{index_path}:{i + 1}: index row {ident} points at {detail_name}#{slug}, "
                "and the detail file carries NO such anchor"
            )
            continue
        if status != row.status:
            findings.append(
                f"{index_path}:{i + 1}: index row {ident} says {status!r}; the row itself "
                f"is {row.status!r} ({detail_name}:{row.lineno})"
            )
        expected = head_of(row.rest)
        if head != expected:
            findings.append(
                f"{index_path}:{i + 1}: index head for {ident} is not the row's own text "
                f"({detail_name}:{row.lineno}). Indexed {head[:60]!r}; the row reads "
                f"{expected[:60]!r}"
            )
    for row in rows:
        if row.slug not in seen:
            findings.append(
                f"{detail_name}:{row.lineno}: anchor {row.anchor!r} has NO index row — "
                "the index cannot be missing a row the record carries"
            )
    return findings


def check_parity(rows: list[Row], index: list[str], index_path: str) -> list[str]:
    """The generated index is read by the citation census exactly as the rows were."""
    findings: list[str] = []
    expected = [(r.ident, r.status) for r in rows]
    got: list[tuple[str, str, int]] = []
    for i, line in enumerate(index):
        verdict = classify(line)
        if verdict is not None:
            got.append((verdict[1], verdict[0], i + 1))
    if len(got) != len(expected):
        findings.append(
            f"{index_path}: the queue-citation parser reads {len(got)} rows out of the generated "
            f"index; the record carries {len(expected)}"
        )
        return findings
    for (want_id, want_status), (got_id, got_status, lineno) in zip(expected, got, strict=True):
        if (want_id, want_status) != (got_id, got_status):
            findings.append(
                f"{index_path}:{lineno}: the queue-citation parser reads this line as "
                f"({got_id}, {got_status}); the row it indexes is ({want_id}, {want_status}). "
                "The index line must be re-shaped — see THE PARITY CHECK in "
                f"{GENERATOR}"
            )
    return findings


def first_difference(got: list[str], want: list[str]) -> str:
    for i, (a, b) in enumerate(zip(got, want, strict=False)):
        if a != b:
            return f"line {i + 1}:\n     committed: {a[:120]!r}\n     generated: {b[:120]!r}"
    if len(got) != len(want):
        longer, which = (got, "committed") if len(got) > len(want) else (want, "generated")
        at = min(len(got), len(want))
        return f"line {at + 1}: only the {which} file has it: {longer[at][:120]!r}"
    return "(no differing line — the two are equal)"


# --------------------------------------------------------------------------
# the modes
# --------------------------------------------------------------------------


def mode_split(index_path: str, detail_path: str) -> int:
    if os.path.exists(detail_path):
        raise Refusal(
            f"{detail_path} already exists — the migration runs once. Nothing was written."
        )
    source = read_lines(index_path, "the queue")
    if read_recorded(source, CEILING_PREFIX) is not None:
        raise Refusal(f"{index_path} is already a generated index. Use --index to regenerate it.")
    detail = add_anchors(source, index_path)
    rows, findings = parse_detail(detail, detail_path)
    if findings:
        for f in findings:
            print(f"!! {f}")
        raise Refusal("the anchored detail file does not hold together — nothing was written.")
    write_lines(detail_path, detail)
    index = generate(detail, rows, detail_path, None)
    write_lines(index_path, index)
    ids, total = long_rows(rows)
    size = os.path.getsize(index_path)
    print(f"== split · {len(source)} lines in, {len(rows)} rows anchored")
    print(f"   record  {detail_path}  {os.path.getsize(detail_path)} bytes")
    recorded = read_recorded(index, CEILING_PREFIX)
    print(f"   index   {index_path}  {size} bytes  (ceiling {recorded[0] if recorded else '?'})")
    print(f"   long rows  {len(ids)} over {LONG_ROW_CHARS} chars, {total} bytes")
    print(f"   reverse it with: python3 {GENERATOR} --unsplit {detail_path}")
    return 0


def mode_index(index_path: str, detail_path: str) -> int:
    # The index's own state is read FIRST: a tree that was never split must be
    # told to run the migration, not told its record is missing.
    existing = read_lines(index_path, "the queue index") if os.path.exists(index_path) else None
    if existing is not None and read_recorded(existing, CEILING_PREFIX) is None:
        raise Refusal(
            f"{index_path} is not a generated index (no {CEILING_PREFIX.strip()} line). "
            "If this tree has not been split yet, run --split. Nothing was written."
        )
    detail = read_lines(detail_path, "the queue's record")
    rows, findings = parse_detail(detail, detail_path)
    if findings:
        for f in findings:
            print(f"!! {f}")
        raise Refusal("the record does not hold together — the index was NOT regenerated.")
    index = generate(detail, rows, detail_path, existing)
    write_lines(index_path, index)
    size = os.path.getsize(index_path)
    ceiling = read_recorded(index, CEILING_PREFIX)
    print(
        f"== index regenerated · {len(rows)} rows · {size} bytes · "
        f"ceiling {ceiling[0] if ceiling else '?'}"
    )
    return 0


def mode_check(index_path: str, detail_path: str) -> int:
    started = time.time()
    # THREE STATES, AND THEY ARE DERIVED — see THE THREE STATES in the header.
    # The discriminator is the generated header, not the presence of a file: a
    # bare `-f` test cannot tell a tree that was never split from one whose
    # record was deleted, and answering both with one verdict is the silent
    # narrowing this whole instrument exists to refuse.
    if not os.path.exists(index_path):
        raise Refusal(f"{index_path} is absent — there is no index to check. Nothing was judged.")
    index = read_lines(index_path, "the queue index")
    is_generated = read_recorded(index, CEILING_PREFIX) is not None
    detail_present = os.path.exists(detail_path)
    if not is_generated and not detail_present:
        # PRE-SPLIT. A named absence, never silence: this tree has not been
        # migrated, so there is no index and no record to disagree, and saying
        # so is the whole verdict. The day `--split` runs, this line stops
        # printing and the checks below start.
        print(
            f"== queue-index: PRE-SPLIT — {index_path} is not a generated index and "
            f"{detail_path} does not exist, so nothing was checked."
        )
        print(
            f"   This is a named absence, not a pass on the ledger: run "
            f"`python3 {GENERATOR} --split` to migrate, and every check in this "
            "instrument starts binding on the next commit."
        )
        return 0
    if not is_generated and detail_present:
        raise Refusal(
            f"{detail_path} exists but {index_path} is not a generated index (no "
            f"{CEILING_PREFIX.strip()} line). This tree is half-migrated: the record "
            f"stands and the index was replaced by hand. Regenerate it with "
            f"`{INTERPRETER} {GENERATOR} --index`. Nothing was judged."
        )
    if not detail_present:
        raise Refusal(
            f"{detail_path} is absent while {index_path} IS a generated index over it. "
            "The index is not judged without its record — a summary whose source is gone "
            "is not a clean summary. Restore the record. Nothing was judged."
        )
    detail = read_lines(detail_path, "the queue's record")
    rows, findings = parse_detail(detail, detail_path)
    detail_name = os.path.basename(detail_path)
    findings += check_consistency(rows, index, detail_name, index_path)
    findings += check_parity(rows, index, index_path)

    recorded_ceiling = read_recorded(index, CEILING_PREFIX)
    recorded_longrows = read_recorded(index, LONGROWS_PREFIX)
    if recorded_ceiling is None or recorded_longrows is None:
        raise Refusal(
            f"{index_path} carries no generated header ({CEILING_PREFIX.strip()} / "
            f"{LONGROWS_PREFIX.strip()}). Nothing was judged."
        )

    regenerated = generate(detail, rows, detail_path, index)
    if regenerated != index:
        findings.append(
            f"{index_path} is NOT what {GENERATOR} generates from {detail_path}. "
            f"First difference at {first_difference(index, regenerated)}\n"
            f"   Remedy: edit {detail_path}, then run `{INTERPRETER} {GENERATOR} --index`. "
            "The index is derived; it is never edited by hand."
        )

    size = len("\n".join(index).encode("utf-8"))
    if size > recorded_ceiling[0]:
        findings.append(
            f"{index_path} is {size} bytes, over its recorded ceiling of {recorded_ceiling[0]}.\n"
            f"   Remedy 1: prune closed rows out of {detail_path} into the "
            "closed-rows archive under docs/product/archive/, then regenerate.\n"
            f"   Remedy 2: raise the {CEILING_PREFIX.strip()} number by hand and write the reason "
            "on that line — a conspicuous diff, by design."
        )
    ids, total = long_rows(rows)
    if len(ids) > recorded_longrows[0]:
        findings.append(
            f"{detail_path} carries {len(ids)} rows over {LONG_ROW_CHARS} characters "
            f"({total} bytes); the recorded floor is {recorded_longrows[0]}.\n"
            f"   The over-long ids: {' '.join(ids)}\n"
            f"   Remedy 1: move the evidence out of the row into the cycle plan or the retro "
            "that already holds it, and shorten the row.\n"
            f"   Remedy 2: raise the {LONGROWS_PREFIX.strip()} number by hand with the reason on "
            "that line. There is no per-row ceiling here, on purpose."
        )

    elapsed = time.time() - started
    if findings:
        for f in findings:
            print(f"!! {f}")
        print(f"== queue-index: {len(findings)} finding(s) · {len(rows)} rows · {elapsed:.3f}s")
        return 1
    print(
        f"== queue-index: {len(rows)} rows · index {size}B of {recorded_ceiling[0]}B ceiling · "
        f"{len(ids)} long rows of {recorded_longrows[0]} floor · {elapsed:.3f}s"
    )
    return 0


def mode_unsplit(detail_path: str, out_path: str | None) -> int:
    detail = read_lines(detail_path, "the queue's record")
    body = strip_anchors(detail)
    if out_path is None:
        sys.stdout.write("\n".join(body))
    else:
        write_lines(out_path, body)
        print(f"== unsplit · {out_path} · {os.path.getsize(out_path)} bytes")
    return 0


USAGE = f"""usage: {GENERATOR} <mode> [paths]

  --split   [<index> <detail>]   the one-time migration (writes both files)
  --index   [<index> <detail>]   regenerate the index from the record
  --check   [<index> <detail>]   the gate leg: 0 clean, 1 findings, 2 cannot look
  --unsplit <detail> [<out>]     strip anchors — the pre-split file, byte for byte

  defaults: index {DEFAULT_INDEX} · detail {DEFAULT_DETAIL}
"""


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE, file=sys.stderr)
        return 2
    mode = argv[0]
    rest = argv[1:]
    if mode in ("--help", "-h"):
        print(USAGE)
        return 0
    if mode == "--unsplit":
        if not rest:
            raise Refusal("--unsplit needs the record's path")
        return mode_unsplit(rest[0], rest[1] if len(rest) > 1 else None)
    if mode in ("--split", "--index", "--check"):
        if len(rest) not in (0, 2):
            raise Refusal(
                f"{mode} takes either no path or both paths (<index> <detail>), not {len(rest)}"
            )
        index_path = rest[0] if rest else DEFAULT_INDEX
        detail_path = rest[1] if rest else DEFAULT_DETAIL
        if mode == "--split":
            return mode_split(index_path, detail_path)
        if mode == "--index":
            return mode_index(index_path, detail_path)
        return mode_check(index_path, detail_path)
    raise Refusal(f"unknown argument {mode!r} — see --help. Nothing was read.")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Refusal as refusal:
        print(f"!! {refusal}", file=sys.stderr)
        print("   Nothing was judged: this is could-not-look, never a pass.", file=sys.stderr)
        sys.exit(2)
