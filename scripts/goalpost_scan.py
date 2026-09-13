#!/usr/bin/env python3
"""The goal-post scan, and the instrument census — two readers, one file.

    python3 scripts/goalpost_scan.py             the scan: one line per pillar
    python3 scripts/goalpost_scan.py --kinds     the verdict + re-trigger vocabularies
    python3 scripts/goalpost_scan.py --census    re-derive the instrument population
    python3 scripts/goalpost_scan.py --selftest  the canaries

WHY IT EXISTS (ADR gate-3). T0's entry condition is "all twelve pillars green",
and until this script that condition was PROSE: a paragraph in `readouts.md`
typed by hand at CLOSE, with no notion of staleness. A verdict earned in P1 and
never re-proven read exactly like one earned this morning, so "all twelve green"
was satisfiable by a stale green. This script makes the register a table with a
DATE and a RE-TRIGGER per row, and refuses a green whose re-trigger has fired
since its proof date.

THE TWO DUTIES, and why they share a file. The scan reads a verdict register;
`--census` re-derives the population of instruments that report a verdict at
all — including this one. They are one script because the census's only reason
to exist is that reporters like this one go blind silently, and a census kept in
a second script is the second copy that agrees today and drifts tomorrow. They
have SEPARATE exit meanings and neither reads the other's input.

EXIT (both duties, the gate's semantics):
    0  read, judged, nothing stale
    1  a verdict is STALE — a computable re-trigger fired after its proof date
    2  COULD NOT LOOK — an unreadable file, a pillar with no row, a row with no
       proof date, a re-trigger kind outside the closed set, a MECHANISM row
       missing its operating owner, an instrument with no census row. 2 outranks
       a pass: an instrument that cannot read its input is not reporting "fine".

THE VERDICT VOCABULARY IS DATA, NOT CODE. `VERDICT_KINDS` below is one line per
kind; adding a kind is that line and nothing else. `docs/product/goal-posts.md`
deliberately does NOT list the kinds — it points at `--kinds`, so there is one
writer for the vocabulary (CLAUDE.md: point at the thing that knows).

THE RE-TRIGGER VOCABULARY IS BORROWED, AND CLOSED. Every token is
`<kind>:<spec>`, tokens separated by ` · `. The kinds come from
`docs/product/scale-envelope.md` § Re-triggers — there is no second re-trigger
vocabulary in this repository, and inventing one is the drift this refuses:

    paths:<glob,…>      the "any change to X" shape. Computable: the newest
                        commit touching the globs vs the proof date.
    pin:<name>@<major>  the "Postgres major / pyjwt major" shape. Computable
                        off `uv.lock` (packages) and `compose.yaml` (images).
                        The `@<major>` is the major the verdict was proven
                        against; without it the token is not computable and is
                        exit 2, not a silent pass.
    asserted:<who>      a fact no tree can see — "a deployment doubling past an
                        axis", "10k joins", "before pilot users go live". NEVER
                        computed and never printed as a bare green: the scan
                        prints UNVERIFIED — asserted by <who> on <date>.
    envelope:           the pillar's evidence IS `docs/product/scale-envelope.md`.
                        The scan reads the FENCED ```re-trigger-paths block in
                        that file's § Re-triggers and re-uses the paths named
                        there rather than copying its dates. A block, not the
                        prose around it, so rewording a sentence cannot change
                        what the coupling computes; no block is exit 2.

WHAT THIS SCAN DOES NOT SEE (declared, not discovered):

  * A WRONG ANSWER THAT CITES A REAL LINE. Every cell in the register and in the
    census is a claim with a citation; the scan checks that the citation has the
    shape of a `file:line`, never that the line says what the cell says. The
    surveyor's rotation reads them.
  * SAME-DAY CHANGES. The register carries dates, not timestamps, so staleness
    is judged at DAY resolution against the commit's own committer date (`%cs`,
    in the commit's timezone — the way a human writes a date in a doc). A
    re-trigger touched later on the proof date itself is invisible.
  * UNMERGED WORK. `paths:` staleness is read from THIS checkout's commit
    history. A re-trigger touched in a worktree nobody has merged is invisible
    until merge — correct, because main is the only tree a verdict vouches for.
  * WHETHER AN `asserted:` CLAIM IS STILL TRUE. `asserted:` is honest and
    toothless: a stale assertion stays UNVERIFIED forever and nobody is
    mechanically obliged to refresh it. The PM's CLOSE scan is that obligation,
    and it is prose.
  * WHETHER A PROOF ARTIFACT EXISTS. The proof-artifact cell must be non-empty;
    the scan does not open it. A dead link passes.
  * `--census`: WHETHER AN INSTRUMENT IS AN INSTRUMENT. The population is every
    executable git knows about outside `apps/`, `config/`, `.venv/` and `.git/`,
    plus the two carve-ins below — a script that reports no verdict still owes a
    row saying so. The census cannot tell a reporter from a plumber; it can only
    tell a listed file from an unlisted one.
  * `--census`: A SCRIPT WITH NO `+x`. The population is derived from `git
    ls-files` and the working tree's MODE BIT, so a file run as `bash thing.sh`
    or `python thing.py` — never marked executable, possibly never given a
    shebang — is invisible to this reader however loudly it reports. That is
    the cost of deriving rather than listing, and it is stated rather than
    discovered.
  * `--census`: AN INSTRUMENT OUTSIDE THIS REPOSITORY. A dashboard query, a
    console alert, a CI step defined in somebody's web UI — none of them is a
    file in this tree, so none of them is derivable here.

Stdlib only. Python 3.12.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

NORTH_STAR = ROOT / "docs/product/north-star.md"
REGISTER = ROOT / "docs/product/goal-posts.md"
ENVELOPE = ROOT / "docs/product/scale-envelope.md"
CENSUS = ROOT / "docs/product/instruments.md"


class CannotLook(Exception):
    """The input cannot be read or cannot be trusted. Exit 2, never a pass."""


# --- the verdict vocabulary: DATA. ONE LINE PER KIND. ------------------------
#
# A kind is `K(<gloss>, <flags>)` and nothing else, so ADDING A KIND IS ONE LINE
# and no code moves. The flags are a space-separated set, and each is one clause
# in `flag()` below:
#
#   stale   a computable re-trigger firing after the proof date makes this row
#           STALE (exit 1). A verdict that claims nothing proven cannot go stale.
#   green   the word GREEN may be printed for this row.
#   t0      this kind satisfies T0's "all twelve" entry condition.
#   owned   the proof is only half here: the cell must carry
#           `operation_by: <product>` AND the row must carry an `asserted:`
#           re-trigger naming the gate that closes it, or exit 2.
#
# An unknown flag is exit 2 at import — a typo in this table must never become a
# silently weaker kind.


@dataclasses.dataclass(frozen=True)
class VerdictKind:
    gloss: str
    flags: str = ""

    def flag(self, name: str) -> bool:
        return name in self.flags.split()


K = VerdictKind
FLAGS = {"stale", "green", "t0", "owned"}

VERDICT_KINDS: dict[str, VerdictKind] = {
    "GREEN": K("proven, and dated; a re-trigger that fired since makes it STALE", "stale green t0"),
    "MECHANISM": K("mechanism proven here; operation proven on the product", "stale t0 owned"),
    "YELLOW": K("partly proven; the cell names what is still pending", ""),
    "RED": K("not proven; the cell names the pass that fills it", ""),
}

for _name, _kind in VERDICT_KINDS.items():
    _unknown = set(_kind.flags.split()) - FLAGS
    if _unknown:
        raise SystemExit(f"goalpost_scan: verdict kind {_name} declares unknown flag(s) {_unknown}")

# The re-trigger kinds, closed and borrowed from scale-envelope.md § Re-triggers.
# Adding one here without adding it there would be the second vocabulary this
# refuses to grow, so the docstring above is the contract and this is its index.
RETRIGGER_KINDS = ("paths", "pin", "asserted", "envelope")

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A citation: a path with at least one `/`, or a filename with an extension,
# followed by `:<line>`. Extensionless is deliberate — `scripts/githooks/pre-push`
# is a file and owes a line number like everything else.
FILE_LINE = re.compile(r"(?:[\w\-.]+/)+[\w\-.]+:\d+|[\w\-.]+\.\w{1,6}:\d+")


# --- markdown table reading ---------------------------------------------------


def _cells(line: str) -> list[str]:
    """Cells of a markdown table row, blockquote markers stripped."""
    return [c.strip() for c in line.strip().lstrip("> ").strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= {"-", ":", " "} for c in cells if c != "")


def read_table(text: str, first_header: str, where: str) -> list[list[str]]:
    """Rows of the first table whose first header cell is `first_header`.

    Raises CannotLook when no such table exists — a missing table is never an
    empty table.
    """
    lines = text.splitlines()
    at = None
    for i, line in enumerate(lines):
        stripped = line.strip().lstrip("> ").strip()
        if not stripped.startswith("|"):
            continue
        if not (_cells(line) and _cells(line)[0].lower() == first_header.lower()):
            continue
        # A header is a header only when a separator row follows it. Without
        # this, a BODY row whose first cell happens to read `Pillar` — the
        # column glossary in goal-posts.md is exactly that — is mistaken for
        # the table this reader wants, and the reader judges the wrong table.
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not (nxt.strip().lstrip("> ").strip().startswith("|") and _is_separator(_cells(nxt))):
            continue
        at = i
        break
    if at is None:
        raise CannotLook(f"{where}: no table whose first column is `{first_header}`")
    rows: list[list[str]] = []
    for line in lines[at + 1 :]:
        stripped = line.strip().lstrip("> ").strip()
        if not stripped.startswith("|"):
            break
        cells = _cells(line)
        if _is_separator(cells):
            continue
        rows.append(cells)
    return rows


def _plain(cell: str) -> str:
    """A table cell with markdown emphasis removed."""
    return cell.replace("**", "").replace("`", "").strip()


# --- the pillars, read from north-star.md ------------------------------------


def pillars(text: str) -> list[str]:
    rows = read_table(text, "Pillar", "north-star.md")
    names = [_plain(r[0]) for r in rows if r and _plain(r[0])]
    if not names:
        raise CannotLook("north-star.md: the pillar table has no rows")
    return names


# --- the re-triggers ----------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Retrigger:
    kind: str
    spec: str


def parse_retriggers(cell: str, pillar: str) -> list[Retrigger]:
    raw = [t.strip() for t in _plain(cell).split("·")]
    raw = [t for t in raw if t]
    if not raw:
        raise CannotLook(
            f"{pillar}: no re-trigger — a verdict with no re-trigger is permanent, which is the "
            f"thing this register refuses"
        )
    out = []
    for token in raw:
        if ":" not in token:
            raise CannotLook(
                f"{pillar}: re-trigger `{token}` is not `<kind>:<spec>` "
                f"(kinds: {', '.join(RETRIGGER_KINDS)})"
            )
        kind, _, spec = token.partition(":")
        kind = kind.strip()
        if kind not in RETRIGGER_KINDS:
            raise CannotLook(
                f"{pillar}: re-trigger kind `{kind}` is outside the closed set {RETRIGGER_KINDS} "
                f"— the vocabulary is scale-envelope.md § Re-triggers, and there is no second "
                f"one"
            )
        out.append(Retrigger(kind, spec.strip()))
    return out


# --- computing a re-trigger's last firing ------------------------------------


def _git(args: list[str]) -> str:
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise CannotLook(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def _pathspec(glob: str) -> str:
    return f":(glob){glob}" if "*" in glob or "?" in glob else glob


def newest_commit(globs: list[str], pillar: str) -> tuple[str, str, str] | None:
    """(sha, YYYY-MM-DD, the glob) of the newest commit touching any glob.

    Raises CannotLook when a glob matches nothing in the tree: a re-trigger
    pointed at a path that does not exist is a re-trigger nobody can fire, and
    that is broken enforcement rather than a clean pass.
    """
    newest: tuple[str, str, str] | None = None
    for glob in globs:
        spec = _pathspec(glob)
        if not _git(["ls-files", "--", spec]).strip():
            raise CannotLook(
                f"{pillar}: re-trigger glob `{glob}` matches no file in this tree — nothing can "
                f"ever fire it"
            )
        out = _git(["log", "-1", "--format=%H %cs", "--", spec]).strip()
        if not out:
            continue
        sha, _, day = out.partition(" ")
        if newest is None or day > newest[1]:
            newest = (sha[:8], day.strip(), glob)
    return newest


#: The fence that carries the envelope's computable re-triggers. An info string
#: nobody types by accident, so a stray ```` ```text ```` block in the section
#: cannot become the coupling.
ENVELOPE_FENCE = "re-trigger-paths"


def envelope_globs() -> list[str]:
    """The paths in scale-envelope.md § Re-triggers' fenced block, re-read not copied.

    A FENCED BLOCK AND NOT THE PROSE. This used to scrape every
    backticked token out of the section and keep the ones that resolved — which
    made the coupling a property of the ENGLISH: reword a sentence, drop a
    backtick, move an example into a different paragraph, and what the
    `envelope:` re-trigger computes changes without anybody having edited a
    path. A staleness check that silently narrows is the same failure as a
    verdict that silently goes stale, and this scan exists to refuse that one.

    So the block is the input, and only the block. `#` starts a comment; a line
    is a path or a glob; every line must resolve to something this tree has.
    Three ways to be exit 2, and none of them is a quiet pass: no section, no
    block, or a line naming nothing.
    """
    if not ENVELOPE.exists():
        raise CannotLook(f"envelope: {ENVELOPE} does not exist")
    text = ENVELOPE.read_text()
    m = re.search(r"^##\s+Re-triggers.*?$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if m is None:
        raise CannotLook("envelope: scale-envelope.md has no `## Re-triggers` section")
    fence = re.search(
        rf"^```{re.escape(ENVELOPE_FENCE)}\s*$(.*?)^```\s*$",
        m.group(1),
        re.MULTILINE | re.DOTALL,
    )
    if fence is None:
        raise CannotLook(
            f"envelope: scale-envelope.md § Re-triggers has no ```{ENVELOPE_FENCE} block. "
            "The `envelope:` re-trigger reads its paths from that block and from nothing "
            "else, so without it this scan would check an empty coupling and call it green"
        )
    globs: list[str] = []
    for raw in fence.group(1).splitlines():
        token = raw.split("#", 1)[0].strip().lstrip("./")
        if not token or token in globs:
            continue
        found = bool(list(ROOT.glob(token))) if "*" in token else (ROOT / token).exists()
        if not found:
            raise CannotLook(
                f"envelope: scale-envelope.md § Re-triggers' {ENVELOPE_FENCE} block names "
                f"`{token}`, which this tree does not have — a re-trigger that matches nothing "
                "never fires, and never firing reads exactly like never being stale"
            )
        globs.append(token)
    if not globs:
        raise CannotLook(
            f"envelope: scale-envelope.md § Re-triggers' {ENVELOPE_FENCE} block is empty — "
            "an empty coupling is not a satisfied one"
        )
    return globs


def pin_major(name: str, pillar: str) -> str:
    """The major version this tree pins for a package (uv.lock) or image (compose)."""
    lock = ROOT / "uv.lock"
    if lock.exists():
        m = re.search(
            rf'^name = "{re.escape(name)}"\s*\nversion = "(\d+)',
            lock.read_text(),
            re.MULTILINE | re.IGNORECASE,
        )
        if m:
            return m.group(1)
    for compose in (ROOT / "compose.yaml", ROOT / "deploy/compose.yaml"):
        if not compose.exists():
            continue
        m = re.search(
            rf"^\s*image:\s*\S*{re.escape(name)}:v?(\d+)",
            compose.read_text(),
            re.MULTILINE | re.IGNORECASE,
        )
        if m:
            return m.group(1)
    raise CannotLook(
        f"{pillar}: pin `{name}` is in neither uv.lock nor a compose file — this tree cannot "
        f"say what it pins"
    )


# --- a register row -----------------------------------------------------------


@dataclasses.dataclass
class Row:
    pillar: str
    verdict_cell: str
    kind_name: str
    kind: VerdictKind
    proof_date: str
    artifact: str
    retriggers: list[Retrigger]


def parse_register(text: str, want: list[str]) -> list[Row]:
    rows = read_table(text, "Pillar", "goal-posts.md")
    seen: dict[str, Row] = {}
    for cells in rows:
        if len(cells) < 5:
            raise CannotLook(
                f"goal-posts.md: row `{cells[0] if cells else ''}` has {len(cells)} columns, "
                f"want 5 (Pillar | Verdict | Proof date | Proof artifact | Re-trigger)"
            )
        pillar = _plain(cells[0])
        if not pillar:
            continue
        if pillar in seen:
            raise CannotLook(f"goal-posts.md: `{pillar}` has two rows — one pillar, one verdict")
        verdict_cell = _plain(cells[1])
        kind = None
        kind_name = ""
        for name in sorted(VERDICT_KINDS, key=len, reverse=True):
            if verdict_cell.startswith(name):
                kind, kind_name = VERDICT_KINDS[name], name
                break
        if kind is None:
            raise CannotLook(
                f"{pillar}: verdict `{verdict_cell or '<empty>'}` does not start with a declared "
                f"kind ({', '.join(VERDICT_KINDS)}) — see --kinds"
            )
        proof = DATE.search(_plain(cells[2]))
        if proof is None:
            raise CannotLook(
                f"{pillar}: no proof date (YYYY-MM-DD) — a verdict with no date is permanent, "
                f"and a permanent verdict is the thing this register exists to refuse"
            )
        artifact = _plain(cells[3])
        if not artifact:
            raise CannotLook(
                f"{pillar}: no proof artifact — a status with no artifact is a hypothesis wearing "
                f"a status"
            )
        triggers = parse_retriggers(cells[4], pillar)
        if kind.flag("owned"):
            # The `owned` flag, in full: half the proof lives with somebody else,
            # so the row must name WHO owes it and WHICH gate closes it.
            if not re.search(r"\boperation_by\s*:\s*\S", verdict_cell):
                raise CannotLook(
                    f"{pillar}: a {kind_name} verdict must carry `operation_by: <product>` in "
                    f"its verdict cell — {kind.gloss}"
                )
            if "asserted" not in {t.kind for t in triggers}:
                raise CannotLook(
                    f"{pillar}: a {kind_name} verdict must carry a `asserted:` re-trigger naming "
                    f"the gate that closes it"
                )
        seen[pillar] = Row(pillar, verdict_cell, kind_name, kind, proof.group(), artifact, triggers)

    missing = [p for p in want if p not in seen]
    extra = [p for p in seen if p not in want]
    if missing:
        raise CannotLook(
            f"goal-posts.md: no row for pillar(s) {missing} — north-star.md promises them and "
            f"the register does not judge them"
        )
    if extra:
        raise CannotLook(
            f"goal-posts.md: row(s) {extra} name no pillar in north-star.md's table — the register "
            f"invented a promise"
        )
    return [seen[p] for p in want]


def field_of(cell: str, field: str) -> str:
    m = re.search(rf"\b{re.escape(field)}\s*:\s*([^·|]+)", cell)
    return m.group(1).strip() if m else ""


# --- the scan -----------------------------------------------------------------


def scan(north_star_text: str, register_text: str) -> tuple[int, list[str]]:
    want = pillars(north_star_text)
    rows = parse_register(register_text, want)
    out = [f"goalpost_scan: {len(rows)} pillars, read from north-star.md's table"]
    stale = 0
    for row in rows:
        asserted = [t for t in row.retriggers if t.kind == "asserted"]
        fired: tuple[str, str, str] | None = None
        if row.kind.flag("stale"):
            for trigger in row.retriggers:
                if trigger.kind == "paths":
                    hit = newest_commit(
                        [g.strip() for g in trigger.spec.split(",") if g.strip()], row.pillar
                    )
                elif trigger.kind == "envelope":
                    hit = newest_commit(envelope_globs(), row.pillar)
                elif trigger.kind == "pin":
                    name, _, proven = trigger.spec.partition("@")
                    if not proven.strip():
                        raise CannotLook(
                            f"{row.pillar}: pin re-trigger `{trigger.spec}` names no proven major "
                            f"— write `pin:{name.strip()}@<major>`; a pin with no proven value "
                            f"cannot be computed and is not a pass"
                        )
                    now = pin_major(name.strip(), row.pillar)
                    hit = (
                        (
                            f"pin {name.strip()}",
                            f"{now} (proven against {proven.strip()})",
                            trigger.spec,
                        )
                        if now != proven.strip()
                        else None
                    )
                else:
                    hit = None
                if hit and (trigger.kind == "pin" or hit[1] > row.proof_date):
                    if fired is None or hit[1] > fired[1]:
                        fired = hit

        # `dated`, never `proven`: only the kind says whether anything was
        # proven, and a RED that reported itself as "proven RED" would be this
        # instrument telling its own small lie.
        if fired is not None:
            stale += 1
            out.append(
                f"  {'STALE':<26} {row.pillar} — dated {row.proof_date}, but `{fired[2]}` fired "
                f"at {fired[1]} ({fired[0]})"
            )
            out.append(
                f"      the verdict cell reads `{row.verdict_cell}` and this scan will not print it"
            )
        elif asserted and row.kind.flag("green"):
            who = asserted[0].spec.split("—")[0].strip() or "?"
            out.append(
                f"  {row.kind_name + '-UNVERIFIED(asserted)':<26} {row.pillar} — UNVERIFIED — "
                f"asserted by {who} on {row.proof_date}"
            )
        elif row.kind.flag("owned"):
            owed = field_of(row.verdict_cell, "operation_by") or "?"
            out.append(
                f"  {row.kind_name:<26} {row.pillar} — {row.kind.gloss}; "
                f"operation owed by {owed}; "
                f"satisfies T0's entry, and is not a proof of operation"
            )
            for t in asserted:
                out.append(
                    f"      UNVERIFIED — asserted by {t.spec.split('—')[0].strip() or '?'} on "
                    f"{row.proof_date}"
                )
        else:
            out.append(
                f"  {row.kind_name:<26} {row.pillar} — dated {row.proof_date} · {row.artifact}"
            )

    t0 = [r.pillar for r in rows if not r.kind.flag("t0")]
    out.append("")
    if stale:
        out.append(
            f"{stale} verdict(s) STALE — a re-trigger fired after the proof date. Re-prove or "
            f"re-date; a green nobody has re-proven is not a green."
        )
    if t0:
        out.append(
            f"T0's entry condition is NOT met: {len(t0)} pillar(s) do not satisfy it — "
            + ", ".join(t0)
        )
    else:
        out.append(
            "Every pillar satisfies T0's entry condition (MECHANISM rows satisfy entry, never "
            "operation)."
        )
    return (1 if stale else 0), out


# --- the census ---------------------------------------------------------------

# Reporting surfaces that are NOT executables and so are not derived. Two, and
# both are pinned rather than typed into the doc: the verdict ledger's line
# shapes live in a sourced file with no shebang, and this script's own duties
# are derived (it is executable) so it needs no pin.
CENSUS_PINS = ("scripts/gate_ledger.sh",)
# `integrations` joins by name rather than by suffix: the owner's charge
# names the command `manage.py integrations`, so it cannot be spelled
# `integrations_audit` to fit the pattern, and an instrument that ships
# uncensused is precisely the class this census refuses.
CENSUS_COMMANDS = re.compile(r"^(introspect|integrations|.*_audit|.*_sweep)$")

# WHERE THE CENSUS DOES NOT LOOK, and why each one. The population used
# to be two DIRECTORY LISTINGS — `scripts/` and `scripts/githooks/` — which is
# to say the census could only see instruments in the place somebody had
# already thought to name. `deploy/` grew a readiness prober, an alert census
# and four alert tools; `deploy/teardown.sh` grew a broom; none of them owed a
# row, because none of them lived in the two directories the list knew about.
# An instrument the census cannot see is exactly the class this file exists to
# refuse, so the derivation is now the whole tree minus a stated four:
#
#   apps/     PRODUCT CODE, not instruments — with the one carve-out below:
#             the management commands that DO report a verdict (`introspect`,
#             `*_audit`, `*_sweep`) are named back in by `CENSUS_COMMANDS`.
#   config/   the mounts. Settings and URL conf report nothing.
#   .venv/    somebody else's software; every console script in it is
#             executable and none of them is ours to vouch for.
#   .git/     hooks git installed, and the object store.
#
# A prefix, not a glob, and it is checked against the POSIX path, so `deploy/`
# staying disjoint from `deployment_notes/` is arithmetic rather than luck.
CENSUS_NOT_LOOKED_AT = ("apps/", "config/", ".venv/", ".git/")


def tracked_and_new() -> list[str]:
    """Every path git knows about: tracked, plus untracked-and-not-ignored.

    `git ls-files` and NOT a directory walk, because the walk has no notion of
    what is ignored: `clients/`, `htmlcov/`, `node_modules/` and every build
    artifact are executables somebody would then owe a row for. Git already
    knows which files are this repository's, and `--others --exclude-standard`
    is what makes an instrument owe its row the moment it lands in the tree
    rather than the moment somebody commits it — which is the whole point, an
    uncensused instrument being at its most invisible before its first commit.
    """
    paths: set[str] = set()
    for extra in ((), ("--others", "--exclude-standard")):
        try:
            out = subprocess.run(
                ["git", "ls-files", "-z", *extra],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CannotLook(
                f"census: `git ls-files {' '.join(extra)}` could not be run in {ROOT} "
                f"({exc}) — the population is derived from it and from nothing else"
            ) from exc
        paths.update(p for p in out.split("\0") if p)
    return sorted(paths)


def population() -> list[str]:
    found: set[str] = set()
    # THE MODE BIT IS THE TEST, and it is read off the working tree rather than
    # off the index: a file made executable and not yet committed is an
    # instrument now. Declared blind spot (the docstring): a script with no
    # `+x`, run as `bash file`, is invisible to this.
    #
    # `stat().st_mode & 0o111` AND NOT `os.access(p, os.X_OK)`. The two
    # agree on a normal filesystem and disagree on one class of filesystem:
    # **virtiofs answers `access()` true for every file**, so inside a
    # devcontainer running on it the census derived every tracked text file —
    # every `.md`, every `.py`, every `.json` — as an instrument owing a row,
    # and exited 2 on a tree that was perfectly fine. `access()` asks "may
    # THIS PROCESS execute it", a question the mount is entitled to answer
    # loosely and the kernel may answer differently for root; `st_mode` reports
    # what the FILE says about itself, which is the property the census actually
    # means and is the same answer on every filesystem.
    #
    # Any of the three execute bits counts, deliberately: a file marked
    # executable for its group and not its owner is still a file somebody
    # intends to be run, and the census's question is about intent, not about
    # who is asking today.
    for rel in tracked_and_new():
        if rel.startswith(CENSUS_NOT_LOOKED_AT):
            continue
        p = ROOT / rel
        if p.is_file() and (p.stat().st_mode & 0o111):
            found.add(rel)
    engine = ROOT / "quality/gate.py"
    if not engine.exists():
        raise CannotLook(
            "census: quality/gate.py does not exist — the house-rules engine is the census's anchor"
        )
    found.add("quality/gate.py")
    for p in sorted(ROOT.glob("apps/*/management/commands/*.py")):
        if CENSUS_COMMANDS.match(p.stem):
            found.add(str(p.relative_to(ROOT)))
    for pin in CENSUS_PINS:
        if not (ROOT / pin).exists():
            raise CannotLook(f"census: pinned surface `{pin}` does not exist — the pin is stale")
        found.add(pin)
    if not found:
        raise CannotLook(
            "census: the derivation named no instrument at all — a tree with no executable "
            "outside apps/ and config/ is this reader looking at the wrong tree, not an "
            "all-clear"
        )
    return sorted(found)


def census(text: str) -> tuple[int, list[str]]:
    rows = read_table(text, "Instrument", "instruments.md")
    listed: dict[str, list[str]] = {}
    for cells in rows:
        if len(cells) < 5:
            raise CannotLook(
                f"instruments.md: row `{cells[0] if cells else ''}` has {len(cells)} columns, "
                f"want 5"
            )
        m = re.search(r"`([^`]+)`", cells[0])
        if m is None:
            raise CannotLook(f"instruments.md: row `{cells[0]}` names no `path` in its first cell")
        listed[m.group(1)] = cells

    derived = population()
    uncensused = [p for p in derived if p not in listed]
    ghost = [p for p in listed if p not in derived]
    out = [f"census: {len(derived)} instruments derived, {len(listed)} rows in {CENSUS.name}"]
    for p in uncensused:
        out.append(f"  uncensused: {p}")
    for p in ghost:
        out.append(f"  censused but not an instrument (gone, or no longer executable): {p}")

    thin: list[str] = []
    for path, cells in listed.items():
        for i in (1, 2, 3):
            if not FILE_LINE.search(cells[i]):
                thin.append(
                    f"  {path}: column {i + 1} answers without a file:line — a claim with no "
                    f"citation is a hypothesis wearing a status"
                )
        if not cells[4].strip():
            thin.append(f"  {path}: column 5 (finding) is blank — write `none` if there was none")
    out.extend(thin)

    # THE 755-MODE GAP, PRINTED RATHER THAN LEFT IN THE MODULE DOCSTRING ONLY.
    # `population()` derives an instrument from the working tree's execute
    # bit; a reporting surface invoked as `python3 thing.py` or `bash thing.sh`
    # without `+x` — a future package-manager script wrapper is the shape
    # named when this gap was raised — is invisible to it however loudly it
    # reports. That was already declared in this module's own docstring
    # (`scripts/goalpost_scan.py:84-89`); it did not used to be said in the
    # OUTPUT of a `--census` run, so a reader of a green census log had to
    # already know to go read the source to learn the derivation has this
    # hole. Printed every run, clean or not, exactly like every other
    # declared blind spot in this gate: a skip that prints nothing is
    # indistinguishable from a pass.
    out.append(
        "  blind spot: a script with no +x, invoked as `bash x.sh` or `python x.py` "
        "(mode 644), is NOT derived — population() reads the working tree's mode bit "
        "and nothing else (scripts/goalpost_scan.py:84-89)"
    )

    if uncensused or ghost or thin:
        out.append("")
        out.append(
            "CANNOT VOUCH — the census and the tree disagree. A new instrument ships uncensused "
            "and the doc goes stale invisibly; that is the class this re-deriver exists to refuse."
        )
        return 2, out
    out.append("  every derived instrument has a row, and every row cites a file:line")
    return 0, out


# --- the canaries -------------------------------------------------------------

FIXTURE_NORTH_STAR = """# north-star

> | Pillar | The promise, plainly | A stranger checks it by | Verdict read from | Re-trigger |
> |---|---|---|---|---|
> | **Correctness** | a green gate means it | planting one | the self-test | quality/ changed |
> | **Performance** | stated scale | re-running the harness | the envelope | hot paths |
> | **Velocity** | the loop stays fast | reading the readouts | readouts.md | two overruns |
"""

FIXTURE_HEADER = (
    "| Pillar | Verdict | Proof date | Proof artifact | Re-trigger |\n|---|---|---|---|---|\n"
)


def _fixture(correctness: str, performance: str = "", velocity: str = "") -> str:
    return FIXTURE_HEADER + "".join(
        [
            correctness,
            performance
            or "| Performance | YELLOW — pending | 2026-08-22 | scale-envelope.md | envelope: |\n",
            velocity
            or "| Velocity | RED — not proven | 2026-08-22 | readouts.md | asserted:pm |\n",
        ]
    )


def selftest() -> int:
    ok = True

    def case(
        name: str, want: int, north: str, register: str, absent: str = "", present: str = ""
    ) -> None:
        nonlocal ok
        try:
            code, lines = scan(north, register)
        except CannotLook as e:
            code, lines = 2, [f"CANNOT LOOK — {e}"]
        text = "\n".join(lines)
        bad = []
        if code != want:
            bad.append(f"exit {code}, want {want}")
        if absent and absent in text:
            bad.append(f"`{absent}` appears and must not")
        if present and present not in text:
            bad.append(f"`{present}` does not appear and must")
        if bad:
            ok = False
        print(
            f"{'ok  ' if not bad else 'FAIL'}  {name}: "
            + ("; ".join(bad) if bad else f"exit {code}")
        )
        if bad:
            for ln in lines:
                print(f"          | {ln}")

    # (a) a GREEN whose `paths:` glob was touched after the proof date -> STALE, exit 1
    case(
        "(a) GREEN whose paths: glob was touched after the proof date",
        1,
        FIXTURE_NORTH_STAR,
        _fixture(
            "| Correctness | GREEN | 2020-01-01 | the self-test "
            "| paths:quality/**,scripts/check.sh |\n"
        ),
        present="STALE",
    )
    # (b) an `asserted:` re-trigger -> UNVERIFIED, exit 0, never a bare GREEN
    case(
        "(b) GREEN + asserted: -> UNVERIFIED, and the row never reads a bare GREEN",
        0,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | asserted:the owner |\n"),
        present="UNVERIFIED — asserted by the owner on 2026-08-22",
    )
    # (c) an unknown kind -> exit 2
    case(
        "(c) an unknown re-trigger kind `vibes:` -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | vibes:it feels fine |\n"),
        present="outside the closed set",
    )
    # (d) a pillar with no proof date -> exit 2
    case(
        "(d) a pillar with no proof date -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | soon | the self-test | paths:quality/** |\n"),
        present="no proof date",
    )
    # the register must cover exactly the pillar table
    case(
        "a 13th row naming no pillar -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | asserted:pm |\n")
        + "| Vibes | GREEN | 2026-08-22 | a feeling | asserted:pm |\n",
        present="invented a promise",
    )
    case(
        "a pillar with no row -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        FIXTURE_HEADER + "| Correctness | GREEN | 2026-08-22 | the self-test | asserted:pm |\n",
        present="no row for pillar",
    )
    # (f) a MECHANISM row lacking operation_by -> exit 2   [Amendment A2]
    case(
        "(f) MECHANISM without `operation_by:` -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture(
            "| Correctness | MECHANISM — proven once | 2026-08-22 | V1's staging | asserted:owner "
            "— before pilot users go live |\n"
        ),
        present="must carry `operation_by",
    )
    # a MECHANISM row with no `asserted:` re-trigger -> exit 2  [Amendment A2]
    case(
        "MECHANISM with no `asserted:` re-trigger -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture(
            "| Correctness | MECHANISM — operation_by: example-product | 2026-08-22 | V1's staging "
            "| paths:quality/** |\n"
        ),
        present="must carry a `asserted:` re-trigger",
    )
    # (g) a complete MECHANISM row -> exit 0, and GREEN never appears on its line
    case(
        "(g) a complete MECHANISM row -> exit 0, and its line never says GREEN",
        0,
        FIXTURE_NORTH_STAR,
        _fixture(
            "| Correctness | MECHANISM — operation_by: example-product | 2026-08-22 | V1's staging "
            "| asserted:owner — before pilot users go live |\n"
        ),
        absent="GREEN",
        present="satisfies T0's entry, and is not a proof of operation",
    )
    # a MECHANISM row is still stale-checked
    case(
        "a MECHANISM row whose paths: glob fired -> STALE, exit 1",
        1,
        FIXTURE_NORTH_STAR,
        _fixture(
            "| Correctness | MECHANISM — operation_by: example-product | 2020-01-01 | V1's staging "
            "| asserted:owner — before pilot users go live · paths:quality/** |\n"
        ),
        present="STALE",
    )
    # a pin re-trigger with no proven major cannot be computed
    case(
        "a `pin:` with no proven major -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | pin:django |\n"),
        present="names no proven major",
    )
    case(
        "a `pin:` whose major moved -> STALE, exit 1",
        1,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | pin:django@4 |\n"),
        present="STALE",
    )
    case(
        "a `pin:` this tree does not pin -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | pin:nosuchthing@1 |\n"),
        present="is in neither uv.lock nor a compose file",
    )
    case(
        "a `paths:` glob matching nothing -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | paths:no/such/place/** |\n"),
        present="matches no file in this tree",
    )
    # a register that is not there at all
    case(
        "a register with no table -> exit 2",
        2,
        FIXTURE_NORTH_STAR,
        "there is no table here\n",
        present="no table whose first column is `Pillar`",
    )
    case(
        "a north-star with no pillar table -> exit 2",
        2,
        "# north-star\n\nnothing here\n",
        _fixture("| Correctness | GREEN | 2026-08-22 | the self-test | asserted:pm |\n"),
        present="no table whose first column is `Pillar`",
    )

    # (e)/(h) THE REAL REGISTER on this tree: the real verdicts, and the three
    # mechanism pillars are not GREEN and not MECHANISM before their rungs land.
    print("")
    print("--- (e)/(h) the real register on this tree ---")
    try:
        code, lines = scan(NORTH_STAR.read_text(), REGISTER.read_text())
    except CannotLook as e:
        code, lines = 2, [f"CANNOT LOOK — {e}"]
    for ln in lines:
        print(f"      {ln}")
    if code not in (0, 1):
        ok = False
        print(f"FAIL  the real register does not read: exit {code}")
    else:
        print(f"ok    the real register reads: exit {code}")
    for pillar in ("Deployability", "Durability", "Observability"):
        line = next((ln for ln in lines if f" {pillar} —" in ln), "")
        verdict = line.strip().split()[0] if line.strip() else "<no line>"
        if verdict in ("GREEN", "MECHANISM"):
            ok = False
            print(
                f"FAIL  {pillar} reads {verdict} before its mechanism rung's verification "
                f"verdict exists (A2 canary (h))"
            )
        else:
            print(f"ok    {pillar} reads {verdict} — not GREEN, not MECHANISM (A2 canary (h))")

    # the census, on this tree
    print("")
    print("--- the census re-deriver on this tree ---")
    try:
        ccode, clines = census(_read(CENSUS))
    except CannotLook as e:
        ccode, clines = 2, [f"CANNOT LOOK — {e}"]
    for ln in clines:
        print(f"      {ln}")
    if ccode != 0:
        ok = False
        print(f"FAIL  the census does not agree with the tree: exit {ccode}")
    else:
        print("ok    the census agrees with the tree")

    print("")
    print(
        "selftest: "
        + ("every canary behaved" if ok else "A CANARY DID NOT BEHAVE — the scan is decoration")
    )
    return 0 if ok else 2


# --- entry --------------------------------------------------------------------


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text()
    except OSError as e:
        raise CannotLook(f"{path} cannot be read: {e}") from e


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if len(argv) > 2 or mode not in ("", "--kinds", "--census", "--selftest", "--help"):
        print(
            f"goalpost_scan: unknown argument {argv[1:]} — usage: goalpost_scan.py [--kinds | "
            f"--census | --selftest]",
            file=sys.stderr,
        )
        return 2
    if mode == "--help":
        print(__doc__)
        return 0
    if mode == "--kinds":
        print("verdict kinds (the register's `Verdict` column starts with one of these):")
        for name, k in VERDICT_KINDS.items():
            print(f"  {name:<10} {k.gloss}")
            print(f"             flags: {k.flags or 'none'}")
        print("\nflags: stale = a fired re-trigger makes it STALE · green = may print GREEN")
        print(
            "       t0 = satisfies T0's entry · owned = needs `operation_by:` + an `asserted:` "
            "re-trigger"
        )
        print("\nre-trigger kinds (closed; borrowed from scale-envelope.md § Re-triggers):")
        for name in RETRIGGER_KINDS:
            print(f"  {name}")
        return 0
    try:
        if mode == "--selftest":
            return selftest()
        if mode == "--census":
            code, lines = census(_read(CENSUS))
        else:
            code, lines = scan(_read(NORTH_STAR), _read(REGISTER))
    except CannotLook as e:
        print(f"goalpost_scan: CANNOT LOOK — {e}", file=sys.stderr)
        print(
            "  Exit 2 outranks a pass: an instrument that cannot read its input is not\n"
            "  reporting "
            "that nothing is wrong.",
            file=sys.stderr,
        )
        return 2
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
