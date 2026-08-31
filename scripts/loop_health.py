#!/usr/bin/env python3
"""Is the loop still working, or just moving?

Reads docs/product/readouts.md and evaluates the stop conditions from the PM
skill over the last two COMPLETED cycle rows. They were prose; prose is level 5
on the integration ladder and does not change behaviour. This makes them
arithmetic.

Exit 0 = healthy.
Exit 1 = two or more signals hold; stop and surface it to the owner.
Exit 2 = the scoreboard CANNOT BE READ — file missing, table header not found,
         fewer than two completed rows, a closed cycle with a section but no
         ROW, or a persona cell speaking a vocabulary this reader does
         not have. An empty scoreboard is exit 2, never a clean 0: a loop that
         cannot measure itself is not in a position to claim it is fine, and
         "not enough data" passing silently is the one state this check exists
         to make impossible.

Columns read (must stay identical to the header in docs/product/readouts.md):

  | Cycle | Closed | Criteria met / total | Persona verdict
  | Misses promoted to L1/L2 | Debt drawn (band top 1–2) | Overran session?
  | Debt added (with trigger) |

A row is COMPLETED when its `Closed` cell carries a date (YYYY-MM-DD). A row
whose first cell starts with `EXAMPLE` is ignored — the ledger skeleton carries
one marked worked example, and an example is not a cycle.

THE TWO FAILURE MODES THIS GUARDS AGAINST. A cycle can close and have its
section written below the table as PROSE rather than as a row — a reader that
only judges the last two ROWS then scores the two cycles before it, says "1
signal — watch it", and exits 0: a perfect, confident, wrong answer about a
board whose newest closed cycle it could not see. And a persona column can
carry ordinary English ("verifier: **DONE** — 'the green is load-bearing'")
instead of the vocabulary word it is testing for, so a naive reader fires
signal 2 on every row ever written and the signal means nothing. Both are now
exit 2:

  * A `## <id> — …` heading below the table whose `<id>` has no row, or whose
    `CLOSED <date>` is LATER than the last row's `Closed`, is CANNOT JUDGE. The
    heading is quoted so the fix is obvious.
  * A persona cell carrying no token from the closed vocabulary
    {better, same, worse, untested} is CANNOT JUDGE, and every offending cell is
    named. Two different tokens in one cell is also CANNOT JUDGE — one row, one
    comparison.

THE PERSONA CELL IS TWO THINGS. A comparison TOKEN, and the verifier's verdict
VERBATIM. Both shapes on the board are read:

    | worse — verifier: "the export still lies about counts" |
    | verifier verbatim: "PASS on every criterion" · token: **untested** |

The explicit `token: <word>` form wins when present; otherwise exactly one
standalone vocabulary word must appear. The vocabulary is asserted for
MEMBERSHIP, never for positivity: `worse` is a legal row that fires signal 2,
and `better` is a legal row that does not. This reader has no opinion about
which word is true — that is the PM's judgment at CLOSE, and the whole point
is that a reader scoring a vocabulary nobody speaks is worse than no reader.

The five signals, each over both of the last two completed rows:

  1. promotions   Misses promoted to L1/L2 is 0 (or blank) in both
                  -> the retro has become ceremony
  2. persona      the comparison token is not `better` in both
                  (same/worse/untested) -> done-per-criteria and
                  done-per-persona have separated
  3. draw         Debt drawn names nothing in both
                  -> the standing draw stopped; empty means stale, not clean
  4. overran      Overran session? is yes (or blank) in both
                  -> cycles are outgrowing a session
  5. criteria     Criteria met < total (or blank) in both
                  -> cycles are closing on lists, not on jobs

A BLANK column counts as a miss, never a zero: it is treated as the failing
value for the signal it belongs to. The output names every blank it found.

THE CRITERIA CELL IS SCORED BY ITS **FIRST** `n/m`, so the cell must LEAD with
the final fraction. A cell that opens with a mid-cycle count and closes with the
CLOSE count is scored on the mid-cycle one; the header line in `readouts.md`
says so, and this sentence is why.

WHAT THIS READER DOES NOT SEE (declared, not discovered):

  * A CYCLE WITH NEITHER A ROW NOR A SECTION. Nothing in this file can miss what
    was never written anywhere. The heading check closes the P2 shape (a section
    without a row); a cycle that closed in silence is invisible, and the PM
    skill's CLOSE checklist is the only thing that can catch it.
  * A HEADING WHOSE ID IS NOT CYCLE-SHAPED. `## <id>` is treated as a cycle
    section when the id matches `[A-Za-z]{0,2}\\d+[a-z]?` (`0`, `P2`, `P10a`) or
    the heading says `CLOSED`. A cycle called `## the big one` is invisible.
  * WHETHER A CELL IS TRUE. Every cell is a claim the PM wrote; this reader
    checks shape and vocabulary, never truth.
  * WHETHER THE VERBATIM VERDICT MATCHES ITS TOKEN. A row may say `better` beside
    a verdict that reads like a disaster. One writer, one judgment, no arithmetic
    over it.

THE SIZE TRIPWIRE — A FINDING, NOT A SIGNAL. Every run also stats
`docs/product/in-flight.md` and says its size out loud. Over 16,384 bytes it
prints a FINDING naming the size and the diet rule the black box carries in its
own Writing rules ("over 16KB, the next session's first act is a prune"). It is
deliberately NOT a sixth signal and deliberately does NOT move the exit code:
the five signals are arithmetic over closed cycles and the threshold is
`NEEDED`, so folding a file size into that population would change what "two
signals hold" means. A fat black box is not a reason to stop the loop; it is a
reason the next session prunes before it does anything else. The tooth is the
selftest, which plants an oversize scratch file and fails if the finding does
not fire — a printed line nobody asserts about is decoration.

If the file is missing or cannot be stat'd, the line says COULD NOT LOOK and
names the error. A tripwire that silently skipped an unreadable file would read
exactly like a thin ledger.

`--selftest` runs the canaries: two deliberately bad rows must fire all five
signals and exit 1; a legal pair must exit 0; an empty board must exit 2; a
board holding only EXAMPLE rows must exit 2; a heading with no row must exit 2;
an out-of-vocabulary persona cell must exit 2; `worse` must be legal and fire
signal 2; `better` must be legal and be silent; a planted oversize in-flight
file must produce the FINDING, a planted small one must not, and a path that is
not there must say COULD NOT LOOK. A check that cannot demonstrably fail is
decoration.

Stdlib only. Python 3.12. Run as `python3 scripts/loop_health.py`.
"""

from __future__ import annotations

import pathlib
import re
import sys
import tempfile

BOARD = pathlib.Path(__file__).resolve().parent.parent / "docs/product/readouts.md"
NEEDED = 2  # signals that must hold before we stop

# The black box, and the ceiling its own Writing rules declare. Both live in
# docs/product/in-flight.md; the number is repeated here because a stat needs an
# integer, and the finding text points back at the file that owns the rule.
IN_FLIGHT = pathlib.Path(__file__).resolve().parent.parent / "docs/product/in-flight.md"
IN_FLIGHT_CEILING = 16_384

COLUMNS = (
    "cycle",
    "closed",
    "criteria",
    "persona",
    "promotions",
    "drawn",
    "overran",
    "added",
)

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
NOTHING = {"", "-", "—", "–", "none", "n/a", "0", "nothing", "no"}

# The persona column's comparison vocabulary. CLOSED, and asserted for
# membership only — see the docstring. `readouts.md`'s header line is the other
# writer of these four words and points here.
PERSONA_TOKENS = ("better", "same", "worse", "untested")
PERSONA_EXPLICIT = re.compile(
    r"\btoken\s*:\s*\**\s*(" + "|".join(PERSONA_TOKENS) + r")\b", re.IGNORECASE
)
PERSONA_ANY = re.compile(r"\b(" + "|".join(PERSONA_TOKENS) + r")\b", re.IGNORECASE)

# A `## <id> — …` heading below the table. `<id>` is cycle-shaped, or the
# heading says CLOSED — the two ways a cycle section announces itself here.
HEADING = re.compile(r"^##\s+(?P<id>[^\n]+?)\s*(?:[—–-]\s|$)")
CYCLE_ID = re.compile(r"^[A-Za-z]{0,2}\d+[a-z]?$")


class CannotJudge(Exception):
    """The scoreboard is unreadable or too short to judge. Exit 2."""


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(text: str) -> list[dict[str, str]]:
    """Return the completed, non-example rows of the scoreboard, in order.

    Raises CannotJudge if no header row beginning with `Cycle` is found.
    """
    lines = text.splitlines()
    header_at = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            first = _cells(line)[0].lower()
            if first == "cycle":
                header_at = i
                break
    if header_at is None:
        raise CannotJudge("table header not found (no row whose first cell is `Cycle`)")

    rows: list[dict[str, str]] = []
    for line in lines[header_at + 1 :]:
        if not line.lstrip().startswith("|"):
            break  # a markdown table has no gaps: the first non-`|` line ends it
        cells = _cells(line)
        if not cells or set(cells[0]) <= {"-", ":", " "}:
            continue  # the separator row
        if cells[0].upper().startswith("EXAMPLE"):
            continue  # a marked worked example is not a cycle
        cells = (cells + [""] * len(COLUMNS))[: len(COLUMNS)]
        rows.append(dict(zip(COLUMNS, cells, strict=True)))
    return rows


def cycle_id(cell: str) -> str:
    """The id at the head of a cycle name: `P2 — comms earns its keep` -> `P2`."""
    return re.split(r"\s[—–-]\s", cell.strip(), maxsplit=1)[0].strip().strip("*` ")


def headings(text: str) -> list[tuple[str, str]]:
    """(id, the heading line) for every `##` heading BELOW the table.

    A heading counts as a cycle section when its id is cycle-shaped or the line
    says CLOSED. See the docstring's declared blind spot: a cycle called
    `## the big one` is invisible to this, and always was.
    """
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and _cells(line)[0].lower() == "cycle":
            start = i
            break
    out = []
    for line in lines[start:]:
        m = HEADING.match(line)
        if m is None:
            continue
        ident = cycle_id(m.group("id"))
        if CYCLE_ID.match(ident) or "CLOSED" in line.upper():
            out.append((ident, line.strip()))
    return out


def refuse_stale_board(text: str, rows: list[dict[str, str]]) -> None:
    """A closed cycle with a SECTION and no ROW is exit 2, not a silence.

    The reader judges the last two ROWS. A cycle that closed and was written up
    as prose below the table is therefore judged by nobody, and a naive reader
    says the board is fine — exactly the shape a section-without-a-row hides.
    """
    have = {cycle_id(r["cycle"]) for r in rows}
    newest = ""
    for r in rows:
        found = DATE.search(r["closed"])
        if found and found.group() > newest:
            newest = found.group()
    for ident, line in headings(text):
        if ident not in have:
            raise CannotJudge(
                f"a closed cycle has a section and no row:\n    {line}\n"
                f"  `{ident}` is written up below the table and is not on it, so this reader "
                f"would otherwise judge the two rows BEFORE it and call the board fine"
            )
        closed = re.search(r"CLOSED\s+(" + DATE.pattern + ")", line, re.IGNORECASE)
        if closed and newest and closed.group(1) > newest:
            raise CannotJudge(
                f"a cycle section is newer than every row on the board:\n    {line}\n"
                f"  it says CLOSED {closed.group(1)}; the newest row says Closed {newest}"
            )


def persona_token(cell: str) -> str | None:
    """The comparison token in a persona cell, or None when there is not exactly one.

    MEMBERSHIP ONLY. This function has no opinion about which word is good; it
    reports which word is there. See the docstring.
    """
    explicit = PERSONA_EXPLICIT.search(cell)
    if explicit:
        return explicit.group(1).lower()
    found = {m.group(1).lower() for m in PERSONA_ANY.finditer(cell)}
    return found.pop() if len(found) == 1 else None


def refuse_unreadable_personas(rows: list[dict[str, str]]) -> None:
    """Persona vocabulary: a vocabulary this reader does not have is exit 2.

    Checked over EVERY completed row, not only the two judged: the board is a
    ledger, and a cell nobody can read is a cell the next cycle inherits.
    """
    bad = []
    for r in rows:
        cell = r["persona"].strip()
        if persona_token(cell) is None:
            bad.append(f"    {cycle_id(r['cycle'])}: {cell or '<blank>'}")
    if bad:
        raise CannotJudge(
            "the persona column speaks a vocabulary this reader does not have.\n"
            + "\n".join(bad)
            + "\n  Each cell needs exactly one token from "
            + f"{{{', '.join(PERSONA_TOKENS)}}} beside the verifier's verdict verbatim "
            '— `worse — verifier: "…"`, or `verifier: "…" · token: **untested**`. '
            "Membership, not positivity: `worse` is a legal row"
        )


def completed(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for r in rows:
        closed = r["closed"].lower()
        if DATE.search(closed) and "in flight" not in closed:
            out.append(r)
    return out


def _int(cell: str) -> int | None:
    m = re.search(r"-?\d+", cell)
    return int(m.group()) if m else None


def _criteria(cell: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\s*/\s*(\d+)", cell)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _is_nothing(cell: str) -> bool:
    return cell.strip().lower() in NOTHING


def evaluate(text: str) -> tuple[int, list[str]]:
    """Evaluate the board text. Returns (exit_code, lines_to_print)."""
    out: list[str] = []
    rows = parse(text)
    done = completed(rows)
    # Both refusals run BEFORE the signals: a board this reader cannot read
    # is never scored, and a stale board is never called fine.
    refuse_stale_board(text, done)
    refuse_unreadable_personas(done)
    if len(done) < NEEDED:
        in_flight = len(rows) - len(done)
        raise CannotJudge(
            f"{len(done)} completed cycle(s) of the {NEEDED} needed "
            f"({len(rows)} row(s) on the board, {in_flight} not yet closed)"
        )

    last = done[-NEEDED:]
    out.append(f"loop_health: judging {last[0]['cycle']} and {last[1]['cycle']}")

    blanks: list[str] = []
    for r in last:
        for key, label in (
            ("criteria", "Criteria met / total"),
            ("persona", "Persona verdict"),
            ("promotions", "Misses promoted to L1/L2"),
            ("drawn", "Debt drawn"),
            ("overran", "Overran session?"),
            ("added", "Debt added"),
        ):
            if r[key].strip() == "":
                blanks.append(f"{r['cycle']}: {label}")

    signals: list[str] = []

    # 1 · promotions — blank counts as 0, which is the miss
    if all((_int(r["promotions"]) or 0) == 0 for r in last):
        signals.append(
            "promotions  no learning reached level 1 or 2 in two cycles — the retro is ceremony"
        )
    # 2 · persona — the TOKEN, not the prose. Anything but `better` is the miss.
    # The token is guaranteed present: a cell without one never reaches here.
    if all(persona_token(r["persona"]) != "better" for r in last):
        signals.append(
            "persona     the user team's verdict did not improve in two cycles — "
            "done-per-criteria and done-per-persona have separated"
        )
    # 3 · draw — nothing drawn from the band in two cycles
    if all(_is_nothing(r["drawn"]) for r in last):
        signals.append(
            "draw        nothing drawn from the non-functional band in two cycles — "
            "the standing draw stopped; empty means stale, not clean"
        )
    # 4 · overran — yes or blank in both
    if all(r["overran"].strip().lower() in {"", "yes", "y", "true"} for r in last):
        signals.append(
            "overran     two consecutive cycles outgrew a session — a cycle that spans "
            "sessions loses the thread that makes proving meaningful"
        )

    # 5 · criteria — met < total, or unreadable, in both
    def _unmet(r: dict[str, str]) -> bool:
        c = _criteria(r["criteria"])
        return c is None or c[0] < c[1]

    if all(_unmet(r) for r in last):
        signals.append(
            "criteria    criteria unmet at CLOSE two cycles running — cycles are closing "
            "on lists, not on jobs ('mostly works' is a fail with a list)"
        )

    for b in blanks:
        out.append(f"  BLANK   {b} — a blank is a miss, not a zero")

    if not signals:
        out.append("  healthy — no signal holds")
        return 0, out
    for s in signals:
        out.append(f"  SIGNAL  {s}")
    if len(signals) >= NEEDED:
        out.append(
            f"\n{len(signals)} signals hold. STOP and surface it to the owner. Running "
            "another cycle to find out is exactly what the failure mode looks like "
            "from inside."
        )
        return 1, out
    out.append(f"\n{len(signals)} signal — watch it. {NEEDED} is the threshold to stop.")
    return 0, out


def in_flight_line(path: pathlib.Path = IN_FLIGHT) -> str:
    """One line about the black box's size. Never silent; never exit-bearing.

    A FINDING over the ceiling, a COULD NOT LOOK when the file cannot be
    stat'd, and the measured size otherwise — so a run that says nothing about
    in-flight.md is a run of a build that has no tripwire, not a thin ledger.
    """
    try:
        size = path.stat().st_size
    except OSError as error:
        return (
            f"  COULD NOT LOOK  {path}: {error.strerror or error}. The size tripwire "
            "did not run — that is not a pass, it is an unmeasured ledger."
        )
    if size > IN_FLIGHT_CEILING:
        return (
            f"  FINDING  in-flight.md is {size:,} bytes, over the "
            f"{IN_FLIGHT_CEILING:,}-byte tripwire — the diet rule in its own Writing "
            "rules says the NEXT SESSION'S FIRST ACT is a prune. Not a signal: this "
            "does not move the exit code."
        )
    return f"  in-flight.md {size:,} bytes — under the {IN_FLIGHT_CEILING:,}-byte tripwire"


def run(path: pathlib.Path, in_flight: pathlib.Path = IN_FLIGHT) -> int:
    # Said before anything else, and on every path out of here: whether the
    # board can be read has nothing to do with whether the black box is fat.
    print(in_flight_line(in_flight))
    if not path.exists():
        print(f"loop_health: CANNOT JUDGE — no scoreboard at {path}", file=sys.stderr)
        return 2
    try:
        code, lines = evaluate(path.read_text())
    except CannotJudge as e:
        print(f"loop_health: CANNOT JUDGE — {e}.", file=sys.stderr)
        print(
            "  Every cycle owes a ROW at CLOSE, on the table, with a persona token.\n"
            "  Until the board can be read this check is not passing, it is SILENT — the\n"
            "  state it exists to make impossible. Exit 2 outranks a pass.",
            file=sys.stderr,
        )
        return 2
    print("\n".join(lines))
    return code


# --- canaries ----------------------------------------------------------------

HEADER = (
    "| Cycle | Closed | Criteria met / total | Persona verdict | Misses promoted to L1/L2 "
    "| Debt drawn (band top 1–2) | Overran session? | Debt added (with trigger) |\n"
    "|---|---|---|---|---|---|---|---|\n"
)

CANARY_BAD = HEADER + (
    '| c1 | 2026-01-01 | 6 / 8 | same — verifier: "the export still lies" | 0 | — | yes |  |\n'
    "| c2 | 2026-01-08 | 7 / 8 | untested — nobody drove it | 0 |  | yes |  |\n"
)

# THE LEGAL PAIR USES `same`, DELIBERATELY. A legal board is one whose tokens
# are in the vocabulary, not one whose tokens are flattering: `same` is legal,
# fires signal 2, and one signal is below the threshold, so this board is exit 0
# with a signal named. If this canary needed `better` to pass, the selftest
# would be asserting POSITIVITY — a reader that demands good news is the exact
# failure this check refuses to become, wearing a different hat. Membership is
# the whole assertion.
CANARY_LEGAL = HEADER + (
    '| c1 | 2026-01-01 | 8 / 8 | same — verifier: "no step failed as written" | 1 '
    "| N4 query floor on orders list | no | none |\n"
    '| c2 | 2026-01-08 | 5 / 5 | same — verifier: "no step failed as written" | 2 '
    "| N7 restore drill | no | "
    "orders export unbounded — due when a customer has > 10k orders |\n"
)

# `better` in both: legal, and SILENT — no signal at all.
CANARY_BETTER = HEADER + (
    "| c1 | 2026-01-01 | 8 / 8 | better — verifier: DONE | 1 | N4 | no | none |\n"
    "| c2 | 2026-01-08 | 5 / 5 | better — verifier: DONE | 2 | N7 | no | none |\n"
)

# `worse` in both: legal, and FIRES signal 2. A bad verdict is not a broken
# board.
CANARY_WORSE = HEADER + (
    "| c1 | 2026-01-01 | 8 / 8 | worse — verifier: DONE | 1 | N4 | no | none |\n"
    "| c2 | 2026-01-08 | 5 / 5 | worse — verifier: DONE | 2 | N7 | no | none |\n"
)

# `fine` is not in the vocabulary: exit 2, not a miss.
CANARY_OUT_OF_VOCABULARY = HEADER + (
    "| c1 | 2026-01-01 | 8 / 8 | fine — verifier: DONE | 1 | N4 | no | none |\n"
    "| c2 | 2026-01-08 | 5 / 5 | fine — verifier: DONE | 2 | N7 | no | none |\n"
)

# The stale-board shape: c3 closed, was written up below the table, and has no row.
CANARY_HEADING_NO_ROW = (
    CANARY_BETTER + "\n\n## c3 — the one that closed as prose "
    "(opened 2026-01-09, CLOSED 2026-01-15)\n\n**Built:** everything.\n"
)

CANARY_EMPTY = HEADER

CANARY_EXAMPLE_ONLY = HEADER + (
    "| EXAMPLE — cycle 3 | 2026-01-01 | 8 / 8 | better | 1 | N4 | no | none |\n"
    "| EXAMPLE — cycle 4 | 2026-01-08 | 5 / 5 | better | 2 | N7 | no | none |\n"
)


def selftest() -> int:
    """Run the canaries and print which fired. Exit 0 if every canary behaved."""

    def outcome(text: str) -> tuple[int, list[str]]:
        try:
            return evaluate(text)
        except CannotJudge as e:
            return 2, [f"CANNOT JUDGE — {e}"]

    # (name, board, wanted exit, signals that must have fired — None = do not check)
    cases: tuple[tuple[str, str, int, set[str] | None], ...] = (
        ("two deliberately bad rows", CANARY_BAD, 1, None),
        ("a legal pair (tokens `same` — membership, not positivity)", CANARY_LEGAL, 0, {"persona"}),
        ("an empty board (header only)", CANARY_EMPTY, 2, None),
        ("a board holding only EXAMPLE rows", CANARY_EXAMPLE_ONLY, 2, None),
        ("a `## c3 — … CLOSED` section with no row", CANARY_HEADING_NO_ROW, 2, None),
        (
            "a persona cell out of vocabulary (`fine — verifier: DONE`)",
            CANARY_OUT_OF_VOCABULARY,
            2,
            None,
        ),
        ("`worse — verifier: DONE` — legal, and fires signal 2", CANARY_WORSE, 0, {"persona"}),
        ("`better — verifier: DONE` — legal, and silent", CANARY_BETTER, 0, set()),
    )
    ok = True
    for name, text, want, want_fired in cases:
        code, lines = outcome(text)
        fired = {
            ln.strip()[len("SIGNAL") :].strip().split()[0]
            for ln in lines
            if ln.strip().startswith("SIGNAL")
        }
        bad = []
        if code != want:
            bad.append(f"exit {code}, want {want}")
        if want_fired is not None and fired != want_fired:
            bad.append(
                f"fired {sorted(fired) or 'nothing'}, want {sorted(want_fired) or 'nothing'}"
            )
        if bad:
            ok = False
        print(
            f"{'ok  ' if not bad else 'FAIL'}  {name}: "
            + (
                "; ".join(bad)
                if bad
                else f"exit {code}" + (f"; fired: {', '.join(sorted(fired))}" if fired else "")
            )
        )
        if bad:
            for ln in lines:
                print(f"          | {ln}")
        if name.startswith("two deliberately") and len(fired) != 5:
            ok = False
            print(f"FAIL  expected all five signals to fire on the bad pair, got {len(fired)}")

    # The size tripwire's canaries. The oversize file is PLANTED in a scratch
    # directory — never the live in-flight.md, which is on its diet and would
    # make this canary pass or fail for a reason it never stated.
    with tempfile.TemporaryDirectory() as scratch:
        fat = pathlib.Path(scratch) / "in-flight-fat.md"
        fat.write_bytes(b"x" * (IN_FLIGHT_CEILING + 1))
        thin = pathlib.Path(scratch) / "in-flight-thin.md"
        thin.write_bytes(b"x" * IN_FLIGHT_CEILING)
        absent = pathlib.Path(scratch) / "in-flight-not-here.md"

        for name, probe, want_start, want_in in (
            (
                f"a PLANTED in-flight of {IN_FLIGHT_CEILING + 1:,} bytes fires the FINDING",
                fat,
                "  FINDING",
                f"{IN_FLIGHT_CEILING + 1:,} bytes",
            ),
            (
                f"a PLANTED in-flight of exactly {IN_FLIGHT_CEILING:,} bytes is silent",
                thin,
                "  in-flight.md",
                "under the",
            ),
            (
                "an in-flight that is not there says COULD NOT LOOK",
                absent,
                "  COULD NOT LOOK",
                str(absent),
            ),
        ):
            line = in_flight_line(probe)
            bad = []
            if not line.startswith(want_start):
                bad.append(f"line does not start {want_start!r}")
            if want_in not in line:
                bad.append(f"{want_in!r} not named")
            if bad:
                ok = False
            print(
                f"{'ok  ' if not bad else 'FAIL'}  {name}: "
                + ("; ".join(bad) if bad else line.strip())
            )

    verdict = "every canary behaved" if ok else "A CANARY DID NOT BEHAVE — the check is decoration"
    print("selftest: " + verdict)
    return 0 if ok else 2


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        raise SystemExit(selftest())
    if len(sys.argv) == 2 and not sys.argv[1].startswith("--"):
        raise SystemExit(run(pathlib.Path(sys.argv[1])))
    if len(sys.argv) > 1:
        print(
            f"loop_health: unknown argument {sys.argv[1:]} — "
            "usage: loop_health.py [--selftest | PATH]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(run(BOARD))
