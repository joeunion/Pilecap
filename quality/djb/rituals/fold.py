"""The fold: regenerate this checkout's derived files and commit exactly those, or refuse."""

# does-not-cover: whether the derived files are right — they are made to agree with this checkout.
# does-not-cover: whether a declared path is honest — a step that stopped writing it is unseen.
# does-not-cover: anything a local step does outside this tree; the census is `git status`.
# does-not-cover: a number that is lower but wrong — clause 3's comparison is arithmetic.
# does-not-cover: a second always-moving field in the baseline; the one-stamp check refuses it.
# does-not-cover: a writer racing the fold between clause 1's read and clause 2's.
# does-not-cover: `.rung/introspect.json` — git-ignored, regenerated, never in the census.

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from apps.core.roads import road
from apps.core.scaffold import copier
from apps.core.scaffold.copier import GOLDENS
from apps.core.scaffold.shapes import adopt_verbs
from quality.could_not_look import CouldNotLook
from quality.djb import budgets as sentences
from quality.djb import ledger
from quality.djb import registry as R

#: The checkout this ritual folds: the one it lives in, as the shell's `dirname $0/..`.
ROOT = Path(__file__).resolve().parents[3]
#: The template's steps, in the order they run — a CLOSED list; `--only` refuses any other name.
STEP_NAMES = ("contract", "schema", "secrets", "budgets", "walls", "map", "goldens")
#: The template's derived files, TYPED: a computed list grows whenever a generator misbehaves.
DERIVED_PATHS = (
    "frontend/openapi.json",
    "frontend/src/api/generated/schema.d.ts",
    ".secrets.baseline",
    "quality/budgets.yaml",
    "scripts/test_impact.json",
    "scripts/gate_member_durations.json",
    "scripts/local/gate_member_durations.ci.json",
    "apps/core/scaffold/goldens/**",
)
#: Derived paths written from outside this checkout: clause 1's one exception, a subset.
ABSORBED_PATHS = ("scripts/test_impact.json",)
#: The fold's own sentinel pair, assembled so this file declares nothing.
WRITES_BEGIN = ">>> fold-writes >>>"
WRITES_END = "<<< fold-writes <<<"
#: The gate's sentinel word a local step must not spell, assembled for the same reason.
GATE_SENTINEL = ledger.GATE_SENTINEL
LOCAL_DIR = "scripts/local/fold.d"
WALLS_TEMPLATE = "scripts/gate_member_durations.json"
WALLS_DRAWER = "scripts/local/gate_member_durations.ci.json"
MAP_PATH = "scripts/test_impact.json"
NIGHTLY_RECORD = ledger.NIGHTLY_RECORD
SUBJECT_PREFIX = "fold: "
NOTHING = "Nothing was regenerated and nothing was committed."
COMMITTED_NOTHING = "Nothing was committed."
#: The reader `uv run python` executes in the folded checkout: the engine's own budget sentences.
BUDGET_READER = """\
import sys

sys.path.insert(0, ".")
import quality.gate as gate  # noqa: E402

problems = gate.check_budgets()
for problem in problems:
    print(problem)
for note in gate.notes:
    print(note)
print("### budget-check: notes=%d problems=%d" % (len(gate.notes), len(problems)))
"""
WALLS_HOME_READER = """\
import sys
sys.argv = ["gate"]
from quality import gate
print("namespace=" + str(gate.LOCAL_DOC.get("rule_id_namespace") or "").strip())
"""
USAGE = """\
THE FOLD. Regenerate this checkout's derived files and commit exactly those.

  ./scripts/pm_fold.sh                        fold this checkout
  ./scripts/pm_fold.sh --only <steps>         run only those steps
  ./scripts/pm_fold.sh --only <steps> --no-commit
                                              …and leave the result in the
                                              working tree, staging nothing
  ./scripts/pm_fold.sh --help

<steps> is a comma-joined subset of a CLOSED list: the seven template steps, in
order — contract, schema, secrets, budgets, walls, map, goldens — plus every step this checkout's
scripts/local/fold.d/ declares, which run after them in name order. An unknown
name is exit 2, and the refusal prints both halves.

`--no-commit` is legal only WITH `--only`: a whole fold that commits nothing is
a bank that vouches for a tree nobody wrote down. `scripts/rung_tidy.sh
--secrets` is the caller these two exist for — step (c)'s scan, the tree's one
legal baseline writer, stays in this module rather than being copied into a
second writer.

`--bank` and `--no-fold` are the CALLERS' flags (scripts/pm_push.sh,
scripts/pm_merge.sh), never this script's.

Exit: 0 folded, or nothing to fold · 1 never · 2 refused, or could not look.

The four clauses: a dirty tree is refused (except a typed ABSORBED path, which
is a derived file written from outside this checkout); only the typed derived list may be
touched; a ceiling is never raised; a pipe and an unknown flag are refused.
None of them is lifted by the flags above. `quality/djb/rituals/fold.py` says
what each one is made of.
"""
DIED = (
    "!! pm_fold: DIED part-way ({cause}).",
    "   The run ended before its last line and before any refusal this module",
    "   authors. NOTHING THIS RUN PRINTED IS A VERDICT — the diagnostic above",
    "   this line names the cause. The working tree may hold a half-regenerated",
    "   derived file: read `git status` before doing anything else.",
)


class Died(CouldNotLook):
    """Exit 2 in `gate_die`'s shape: `!! <headline>`, then its lines indented three."""

    def __init__(self, headline: str, *lines: str) -> None:
        super().__init__(headline)
        self.headline = headline
        self.lines = lines


class Printed(CouldNotLook):
    """Exit 2 whose sentences are already on stderr."""


def out(text: str = "") -> None:
    """One line on stdout, flushed before any child writes beside it."""
    print(text, flush=True)


def err(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def refuse(*lines: str) -> Printed:
    """The lines on stderr as written; the exit-2 they end in."""
    for line in lines:
        err(line)
    return Printed(lines[0] if lines else "")


def git(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """`git <argv>`, both streams captured."""
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)


def git_out(*argv: str, cwd: Path | None = None) -> str:
    """`git <argv>`'s stdout stripped, or '' when it exits non-zero."""
    done = git(*argv, cwd=cwd)
    return done.stdout.strip() if done.returncode == 0 else ""


def passthrough(argv: Sequence[str], cwd: Path, **kwargs: object) -> int:
    """`argv` with this process's streams, its exit returned; 127 when it cannot start."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        done = subprocess.run(list(argv), cwd=cwd, check=False, **kwargs)  # type: ignore[call-overload]
        return int(done.returncode)
    except OSError:
        return 127


def refuse_if_piped() -> None:
    """Exit 2 when stdout is a pipe outside CI (`refuse_if_piped`): the exit is the verdict."""
    if os.environ.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        raise Died(
            "pm_fold refuses pipes — run it bare or redirect to a file.",
            "The exit status is the verdict, and a filter replaces it.",
        )


def count_lines(text: str, needle: str) -> int:
    """`grep -c <needle>`: the lines carrying it."""
    return sum(1 for line in text.splitlines() if needle in line)


class Unapplied(CouldNotLook):
    """The apply refused: `UNREADABLE`/`RAISE` lines (4) or `MISS` lines (3), in the awk's order."""

    def __init__(self, code: int, said: list[str]) -> None:
        super().__init__(code)
        self.code = code
        self.said = said


def apply_lowerings(text: str, lowerings: Sequence[tuple[str, str, str]]) -> str:
    """`budgets.yaml` with each lowering applied: the number replaced, its comment kept."""
    said: list[str] = []
    hit = [False] * len(lowerings)
    bad = False
    section = ""
    lines: list[str] = []
    for line in text.splitlines():
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:[ \t]*$", line):
            section = re.sub(r":[ \t]*$", "", line)
            lines.append(line)
            continue
        for i, (sect, key, value) in enumerate(lowerings):
            prefix = f"  {key}: "
            if sect != section or not line.startswith(prefix):
                continue
            tail = line[len(prefix) :]
            comment = ""
            at = tail.find("#")
            if at >= 0:
                old = tail[:at]
                comment = re.sub(r"^[^ \t]*", "", old) + tail[at:]
            else:
                old = tail
            old = old.rstrip(" \t")
            if not re.fullmatch(r"[0-9]+", old):
                said.append(
                    f'UNREADABLE {sect} {key}: the ceiling standing in the file is "{old}", '
                    f"which is not a number -> {value}"
                )
                bad = True
            elif int(value) >= int(old):
                said.append(f"RAISE {sect} {key}: {old} -> {value}")
                bad = True
            lines.append(prefix + value + comment)
            hit[i] = True
            break
        else:
            lines.append(line)
    missed = [f"MISS {s} {k}" for (s, k, _), seen in zip(lowerings, hit, strict=True) if not seen]
    if bad:
        raise Unapplied(4, said + missed)
    if missed:
        raise Unapplied(3, said + missed)
    return "\n".join(lines) + "\n"


# --- the nightly's record: `leak-proof/1` through `gh` ------------------------------------------


class NoNight(Exception):
    """The fetch found nothing to read (`gate_nightly_fetch`'s 1), its sentence the message."""


def _field_of(record: Path, name: str) -> str:
    """`name=`'s value on the record's first non-blank line, or ''."""
    try:
        text = record.read_text(errors="replace")
    except OSError:
        return ""
    line = next((x for x in text.splitlines() if x.split()), "")
    for token in line.split():
        if token.startswith(f"{name}="):
            return token[len(name) + 1 :]
    return ""


# --- the walls: a green CI run's own shard lines, harvested whole or not at all -----------------

_SHARD_JOB = re.compile(r"^legs \(selftest(, [0-9]+/[0-9]+)?\)$")
_EXIT_LINE = re.compile(r"^  drive [A-Za-z0-9_:-]+: exit [0-9]+ \([0-9]+s\)$")
_REUSED_LINE = re.compile(r"^  drive [A-Za-z0-9_:-]+: REUSED ")
_HONOURED = re.compile(r"honoured: tree [0-9a-f]* was measured green by run ([0-9]+)")


class Harvest(Exception):
    """A harvest that stops: `code` 1 could-not-look, 3 not a green run."""

    def __init__(self, code: int, why: str) -> None:
        super().__init__(why)
        self.code = code
        self.why = why


def walls_from_log(log: str) -> list[str]:
    """`member-walls/1` rows from a run's log, one per selftest shard's drive line."""
    rows: list[str] = []
    for raw in log.splitlines():
        cells = raw.split("\t")
        if len(cells) < 3 or not _SHARD_JOB.match(cells[0]):
            continue
        shard = re.search(r"[0-9]+/[0-9]+", cells[0])
        part = shard.group() if shard else "1/1"
        line = re.sub(r"^[0-9][0-9TZ:.+-]* ", "", cells[2], count=1)
        if _EXIT_LINE.match(line):
            words = line.split(" ")
            name = words[3].rstrip(":")
            rows.append(f"member-walls/1\t{name}\t{words[5]}\t{words[6].strip('()s')}\t{part}")
        elif _REUSED_LINE.match(line):
            name = line.split(" ")[3].rstrip(":")
            rows.append(f"member-walls/1\t{name}\treused\t-\t{part}")
    return rows


@dataclass
class Walls:
    """One walls step: the checkout, its `gh`, its scratch and what it printed."""

    root: Path
    gh: str
    work: Path

    def home(self, uv: str) -> str:
        """The table this tree's walls belong in, or '' when the engine's reading did not answer."""
        given = os.environ.get("DJB_FOLD_WALLS_HOME", "")
        if given:
            return given
        try:
            done = subprocess.run(
                [uv, "run", "python", "-c", WALLS_HOME_READER],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return ""
        if done.returncode != 0 or "namespace=" not in done.stdout:
            return ""
        namespace = done.stdout.rsplit("namespace=", 1)[1]
        return WALLS_DRAWER if namespace.strip() else WALLS_TEMPLATE

    def rule_ids(self, uv: str) -> list[str] | None:
        """The engine's rule ids in plan order, or None when the engine did not answer."""
        given = os.environ.get("DJB_FOLD_RULE_IDS", "")
        if given:
            try:
                return [x for x in Path(given).read_text().splitlines() if x]
            except OSError:
                return None
        try:
            done = subprocess.run(
                [uv, "run", "python", "-c", R.RULE_IDS_READER],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        ids = [x for x in done.stdout.splitlines() if x.strip()]
        return ids if done.returncode == 0 and ids else None

    def population(self) -> list[str] | None:
        """The selftest unit's members as `--list-legs` derives them, or None."""
        given = os.environ.get("DJB_FOLD_WALLS_POPULATION", "")
        if given:
            try:
                return [x for x in Path(given).read_text().splitlines() if x]
            except OSError:
                return None
        try:
            done = subprocess.run(
                [str(self.root / "scripts/check.sh"), "--list-legs"],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if done.returncode != 0:
            return None
        for row in done.stdout.splitlines():
            cells = row.split("\t")
            if cells[0] == "selftest" and len(cells) > 3:
                return ["house-rules-engine" if m == "selftest" else m for m in cells[3].split(",")]
        return None

    def gh_run(self, *argv: str) -> str:
        """`gh <argv>`'s stdout; `Harvest(1)` with its first stderr line when it fails."""
        done = subprocess.run(
            [self.gh, *argv], cwd=self.root, capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            first = (done.stderr.splitlines() or [""])[0]
            raise Harvest(1, first)
        return done.stdout.strip()

    def fetch(self, directory: Path, run: str = "", followed: bool = False) -> list[str]:
        """The run's meta written and its rows answered, artifacts first, its log second."""
        if shutil.which(self.gh) is None:
            raise Harvest(1, f"no {self.gh} on PATH")
        run = run or os.environ.get("DJB_FOLD_WALLS_RUN", "")
        if not run:
            try:
                run = self.gh_run(
                    "run",
                    "list",
                    "--workflow",
                    "ci.yml",
                    "--branch=main",
                    "--event",
                    "push",
                    "--status",
                    "success",
                    "--limit",
                    "1",
                    "--json",
                    "databaseId",
                    "--jq",
                    ".[0].databaseId // empty",
                )
            except Harvest as failed:
                raise Harvest(1, f"gh run list failed: {failed.why}") from failed
            if not run:
                raise Harvest(1, "no green CI run on main")
        if not re.fullmatch(r"[0-9]+", run):
            raise Harvest(1, f"the run id '{run}' is not a number")
        try:
            view = self.gh_run(
                "run",
                "view",
                run,
                "--json",
                "status,conclusion,headSha",
                "--jq",
                '"\\(.status) \\(.conclusion) \\(.headSha)"',
            )
        except Harvest as failed:
            raise Harvest(1, f"gh run view {run} failed: {failed.why}") from failed
        words = (view.split() + ["", "", ""])[:3]
        status, conclusion, sha = words
        if status != "completed" or conclusion != "success":
            raise Harvest(3, f"run {run} is {status}/{conclusion}, not a green completed run")
        tree = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{tree}}", cwd=self.root)
        if not tree:
            try:
                tree = self.gh_run(
                    "api", f"repos/{{owner}}/{{repo}}/git/commits/{sha}", "--jq", ".tree.sha"
                )
            except Harvest as failed:
                raise Harvest(1, f"the tree of {sha} could not be read: {failed.why}") from failed
        try:
            labels = self.gh_run(
                "api",
                f"repos/{{owner}}/{{repo}}/actions/runs/{run}/jobs?per_page=100",
                "--jq",
                '.jobs[] | select(.name | startswith("legs (selftest")) | .labels | join(",")',
            )
        except Harvest as failed:
            raise Harvest(1, f"gh api could not list run {run}'s jobs: {failed.why}") from failed
        machine = "+".join(sorted({x for x in labels.splitlines() if x}))
        (directory / "run.meta").write_text(f"run={run}\nmachine={machine}\ntree={tree}\n")
        artifacts = directory / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        got = subprocess.run(
            [
                self.gh,
                "run",
                "download",
                run,
                "--pattern",
                "member-walls*",
                "--dir",
                str(artifacts),
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        files = sorted(p for p in artifacts.rglob("*") if p.is_file())
        if got.returncode == 0 and files:
            lines = [line for p in files for line in p.read_text(errors="replace").splitlines()]
            rows = [line for line in lines if line.startswith("member-walls/1\t")]
            (directory / "artifacts.walls").write_text("".join(f"{r}\n" for r in rows))
            rules = [line for line in lines if line.startswith(f"{R.RULE_ROW}\t")]
            (directory / "artifacts.rules").write_text("".join(f"{r}\n" for r in rules))
            units = [line for line in lines if line.startswith(f"{R.MODULE_ROW}\t")]
            (directory / "artifacts.modules").write_text("".join(f"{r}\n" for r in units))
            return rows
        log = subprocess.run(
            [self.gh, "run", "view", run, "--log"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        if log.returncode != 0:
            first = (log.stderr.splitlines() or [""])[0]
            raise Harvest(1, f"gh run view {run} --log failed: {first}")
        rows = walls_from_log(log.stdout)
        (directory / "log.walls").write_text("".join(f"{r}\n" for r in rows))
        if not rows and not followed:
            honoured = _HONOURED.search(log.stdout)
            if honoured:
                (directory / "follow.note").write_text(
                    f"the push run {run} ran no selftest shard — derive honoured its tree by run "
                    f"{honoured.group(1)}, which measured it; followed\n"
                )
                shutil.rmtree(artifacts, ignore_errors=True)
                for name in ("artifacts.walls", "log.walls"):
                    (directory / name).unlink(missing_ok=True)
                return self.fetch(directory, honoured.group(1), followed=True)
        return rows


def walls_rows(directory: Path) -> list[str]:
    """Every `*.walls` file's lines in name order (`fold_walls_rows`)."""
    return [
        line
        for path in sorted(directory.glob("*.walls"))
        if path.is_file()
        for line in path.read_text(errors="replace").splitlines()
    ]


def rules_judgement(rows: Sequence[str], ids: Sequence[str], walls: Sequence[str]) -> str:
    """'' for one green run's seconds for exactly the engine's rules, else every reason not."""
    engine = [
        cells
        for cells in (row.split("\t") for row in walls)
        if len(cells) == 5 and cells[1].partition(R.PIECE)[0] == R.ENGINE_MEMBER
    ]
    red = sorted({f"{c[1]}(exit {c[2]})" for c in engine if c[2] != "0"})
    seen: dict[str, str] = {}
    twice: list[str] = []
    bad: list[str] = []
    for number, row in enumerate(rows, start=1):
        cells = row.split("\t")
        if not row.split():
            continue
        shaped = len(cells) == 4 and re.fullmatch(r"[0-9]+\.?[0-9]*", cells[2])
        if cells[0] != R.RULE_ROW or not shaped:
            bad.append(f"unparsable:{number}")
            continue
        if cells[1] == R.RULE_FIXED:
            continue
        if cells[1] in seen:
            twice.append(f"{cells[1]}({seen[cells[1]]},{cells[3]})")
        seen[cells[1]] = cells[3]
    parts = []
    for label, items in (
        ("no engine row green in this run:", [] if engine else ["(none)"]),
        ("engine not green:", red),
        ("timed twice:", twice),
        ("missing against the engine's rules:", [r for r in ids if r not in seen]),
        ("not a rule of this engine:", [r for r in seen if r not in set(ids) | {R.RULE_WHOLE}]),
        ("malformed:", bad),
    ):
        if items:
            parts.append(label + "".join(f" {x}" for x in items))
    return "; ".join(parts)


def modules_judgement(
    rows: Sequence[str], units: dict[str, list[str]], walls: Sequence[str]
) -> str:
    """'' for one green run's seconds for exactly the split legs' modules, else every reason."""
    members = [
        cells
        for cells in (row.split("\t") for row in walls)
        if len(cells) == 5 and cells[1].partition(R.PIECE)[0] in units
    ]
    red = sorted({f"{c[1]}(exit {c[2]})" for c in members if c[2] != "0"})
    want = [m for found in units.values() for m in found]
    seen: dict[str, str] = {}
    twice: list[str] = []
    bad: list[str] = []
    for number, row in enumerate(rows, start=1):
        cells = row.split("\t")
        if not row.split():
            continue
        shaped = len(cells) == 4 and re.fullmatch(r"[0-9]+\.?[0-9]*", cells[2])
        if cells[0] != R.MODULE_ROW or not shaped:
            bad.append(f"unparsable:{number}")
            continue
        if cells[1] in seen:
            twice.append(f"{cells[1]}({seen[cells[1]]},{cells[3]})")
        seen[cells[1]] = cells[3]
    parts = []
    for label, items in (
        ("no split member's row in this run:", [] if members else ["(none)"]),
        ("split member not green:", red),
        ("timed twice:", twice),
        ("missing against the tree's modules:", [m for m in want if m not in seen]),
        ("not a module of this tree:", [m for m in seen if m not in set(want)]),
        ("malformed:", bad),
    ):
        if items:
            parts.append(label + "".join(f" {x}" for x in items))
    return "; ".join(parts)


_SPLIT = re.compile(r"^(?P<name>.+)#(?P<ks>[0-9]+(?:,[0-9]+)*)/(?P<n>[0-9]+)$")


def whole_rows(rows: Sequence[str]) -> tuple[list[str], str]:
    """A split member's `<name>#<ks>/<n>` rows as one row of its summed seconds, and any gap."""
    out: list[str] = []
    split: dict[str, list[list[str]]] = {}
    for row in rows:
        cells = row.split("\t")
        hit = _SPLIT.match(cells[1]) if len(cells) == 5 else None
        if hit is None:
            out.append(row)
        else:
            split.setdefault(hit["name"], []).append([*cells, hit["ks"], hit["n"]])
    gaps: list[str] = []
    for name, parts in split.items():
        ks = [int(k) for p in parts for k in p[5].split(",")]
        n = {p[6] for p in parts}
        want = list(range(1, int(next(iter(n))) + 1)) if len(n) == 1 else []
        if sorted(ks) != want:
            held = ",".join(map(str, sorted(ks)))
            gaps.append(f"{name}(members {held} of {'/'.join(sorted(n))})")
            continue
        rcs = [p[2] for p in parts]
        rc = next((r for r in rcs if r != "0"), "0")
        secs = [p[3] for p in parts]
        took = str(sum(int(x) for x in secs)) if all(x.isdigit() for x in secs) else "-"
        out.append("\t".join([parts[0][0], name, rc, took, "+".join(p[4] for p in parts)]))
    return out, ("split member incomplete:" + "".join(f" {g}" for g in gaps)) if gaps else ""


def walls_judgement(rows: Sequence[str], population: Sequence[str]) -> str:
    """'' for a whole green harvest of exactly the population, else every reason it is not."""
    want = set(population)
    seen: dict[str, str] = {}
    twice: list[str] = []
    extra: list[str] = []
    red: list[str] = []
    reused: list[str] = []
    bad: list[str] = []
    for number, row in enumerate(rows, start=1):
        cells = row.split("\t")
        if row == "" or not row.split():
            continue
        if cells[0] != "member-walls/1" or len(cells) != 5:
            bad.append(f"unparsable:{number}")
            continue
        _, name, rc, secs, part = cells
        if rc == "reused":
            reused.append(name)
        elif rc != "0":
            red.append(f"{name}(exit {rc})")
        elif not re.fullmatch(r"[0-9]+", secs):
            bad.append(f"{name}(wall {secs})")
        if name in seen:
            twice.append(f"{name}({seen[name]},{part})")
        seen[name] = part
        if name not in want:
            extra.append(name)
    missing = sorted(want - set(seen))
    parts = []
    for label, items in (
        ("in two shards:", twice),
        ("missing against the population:", missing),
        ("not a member of the population:", extra),
        ("not green:", red),
        ("reused (never this run's wall):", reused),
        ("malformed:", bad),
    ):
        if items:
            parts.append(label + "".join(f" {x}" for x in items))
    return "; ".join(parts)


# --- the fold itself ------------------------------------------------------------------------------


@dataclass
class Args:
    """The command line: the selected steps and whether to commit."""

    only: str = ""
    no_commit: bool = False


def parse(argv: Sequence[str], root: Path) -> Args | None:
    """The arguments, or None for `--help`; an unknown one is exit 2, never a different run."""
    args = Args()
    rest = list(argv)
    names = " ".join(STEP_NAMES)
    while rest:
        word = rest.pop(0)
        if word in ("-h", "--help"):
            return None
        if word == "--only" or word.startswith("--only="):
            args.only = word[len("--only=") :] if "=" in word else (rest.pop(0) if rest else "")
            if not args.only:
                raise Died(
                    f"pm_fold: --only takes a comma-joined subset of: {names}",
                    f"It was given nothing. {NOTHING}",
                )
        elif word == "--no-commit":
            args.no_commit = True
        else:
            raise Died(
                f"pm_fold: unknown argument '{word}'.",
                "pm_fold takes --only <steps>, --no-commit and --help, and nothing else. It",
                f"folds the checkout it lives in, which is {root}. `--bank` and",
                "`--no-fold` belong to pm_push.sh and pm_merge.sh; a flag that looks like",
                "the wiring's own flag is still not this script's.",
                NOTHING,
            )
    return args


def fold_step_selected(only: str, name: str) -> bool:
    """With no `--only`, every step; with one, the named subset (the fold.d drawer's reader)."""
    return not only or name in only.split(",")


@dataclass
class LocalStep:
    """One drawer step: its name, its path and the paths it declares it writes."""

    name: str
    path: Path
    declared: list[str]


def porcelain(root: Path, *paths: str) -> list[str]:
    """`git status --porcelain -uall` entries (`tree_dirt . -uall`)."""
    argv = ["status", "--porcelain", "-uall"]
    if paths:
        argv += ["--", *paths]
    done = git(*argv, cwd=root)
    return [line for line in done.stdout.splitlines() if line]


@dataclass
class Fold:
    """One fold of `root`: the steps run, what each changed, and the commit that carries it."""

    root: Path
    args: Args
    work: Path
    uv: str = field(default_factory=lambda: os.environ.get("DJB_FOLD_UV") or "uv")
    gh: str = field(default_factory=lambda: os.environ.get("DJB_FOLD_GH") or "gh")
    pin: Path = Path()
    tree_paths: list[str] = field(default_factory=list)
    local: list[LocalStep] = field(default_factory=list)
    steps_run: int = 0
    lowered: int = 0
    map_harvested: bool = False
    map_absorbed: bool = False
    map_pruned: int = 0
    pre_head: str = ""
    pre_tree: str = ""

    def __post_init__(self) -> None:
        given = os.environ.get("DJB_FOLD_PIN_CLIENT")
        self.pin = Path(given) if given else self.root / "frontend/scripts/pin_client.sh"

    # --- the shared predicates ---------------------------------------------------------------

    def selected(self, name: str) -> bool:
        """Whether this run's `--only` selects the step `name`."""
        return fold_step_selected(self.args.only, name)

    def skipped(self, why: str) -> None:
        """The step's one `skipped —` line."""
        out(f"  skipped — {why}")

    def declared(self, path: str) -> bool:
        """Whether a fold-writes block (the tree's or a local step's) names `path`."""
        return path in self.tree_paths or any(path in step.declared for step in self.local)

    def derived(self, path: str) -> bool:
        """The typed list (a `/**` entry by its prefix) or a declaration (`fold_is_derived`)."""
        under = any(path.startswith(p[:-2]) for p in DERIVED_PATHS if p.endswith("/**"))
        return path in DERIVED_PATHS or under or self.declared(path)

    def dirty_paths(self) -> list[str]:
        """The working tree's changed paths, the status letters dropped."""
        return [entry[3:] for entry in porcelain(self.root)]

    # --- before any step ---------------------------------------------------------------------

    def read_drawer(self) -> None:
        """Every drawer step, refused unless named, tracked, executable and declared."""
        drawer = self.root / LOCAL_DIR
        if not drawer.is_dir():
            return
        owners: dict[str, str] = {}
        for path in sorted(drawer.glob("*.sh")):
            name = path.name[: -len(".sh")]
            rel = f"{LOCAL_DIR}/{name}.sh"
            if name in STEP_NAMES:
                raise Died(
                    f"pm_fold: {rel} takes the name of one of this fold's own steps.",
                    f"The template's own are {' '.join(STEP_NAMES)}, and a local step that "
                    "shadowed",
                    "one would make --only ambiguous and could silently replace a step this",
                    "module calls the tree's only legal writer. Rename the local step.",
                    NOTHING,
                )
            if git("ls-files", "--error-unmatch", "--", rel, cwd=self.root).returncode != 0:
                raise Died(
                    f"pm_fold: {rel} is not tracked by git.",
                    "A step in this drawer is EXECUTED by the one script here that commits",
                    "unattended, so it is code a reviewer and a release can both see, or it does",
                    "not run. An untracked or ignored step is neither — and it would look",
                    "identical in the transcript to one somebody wrote on purpose.",
                    "git add it, or take it out of the drawer.",
                    NOTHING,
                )
            if not os.access(path, os.X_OK):
                raise Died(
                    f"pm_fold: {rel} is not executable.",
                    "A step in this drawer is EXECUTED. A missing +x bit is a step that never",
                    "runs and says nothing about it — the one failure a drawer makes easy.",
                    NOTHING,
                )
            text = path.read_text(errors="replace").splitlines()
            wrong = next(((n, x) for n, x in enumerate(text, 1) if GATE_SENTINEL in x), None)
            if wrong is not None:
                raise Died(
                    f"pm_fold: {rel}:{wrong[0]} spells the GATE's declaration sentinel.",
                    f"    {wrong[1]}",
                    "That grammar subtracts a path from the verdict key, and a path this fold",
                    "COMMITS is read back by the gate by construction — the consumer's generated",
                    "client is compiled inside it. A step declares in the fold's own grammar:",
                    f"    # {WRITES_BEGIN}",
                    "    # path/to/the/file — why this step regenerates it",
                    f"    # {WRITES_END}",
                    NOTHING,
                )
            read = ledger.declared_paths(self.root, WRITES_BEGIN, WRITES_END, sources=[rel])
            if read.refused:
                for note in read.notes:
                    err(note)
                raise Died(
                    f"pm_fold: the declaration in {rel} could not be read (notes above).",
                    "It is read by this module's one reader, in the gate's entry grammar, and a",
                    "block it refuses is a block whose paths this fold cannot partition against.",
                    NOTHING,
                )
            if not read.paths:
                raise Died(
                    f"pm_fold: {rel} declares no written paths.",
                    "A step owes a sentinel block naming every path it writes — the em dash and",
                    "the reason are part of the entry form, because without them a paragraph",
                    "inside the block declares whatever its first word is:",
                    f"    # {WRITES_BEGIN}",
                    "    # path/to/the/file — why this step regenerates it",
                    f"    # {WRITES_END}",
                    "A block that is empty, one the reader could not read, and a path nothing",
                    "tracks are all this same refusal: the declaration is what clause 2",
                    "partitions against, and a step whose output nobody can partition is a step",
                    "that may commit anything.",
                    NOTHING,
                )
            for claimed in read.paths:
                if claimed in owners:
                    raise Died(
                        f"pm_fold: two local fold steps declare '{claimed}'.",
                        f"    {LOCAL_DIR}/{owners[claimed]}.sh",
                        f"    {rel}",
                        "Two steps with a claim on one path have no order anybody wrote down:",
                        "whichever ran last would win, silently, and this run could attribute the",
                        "write to neither of them.",
                        NOTHING,
                    )
                owners[claimed] = name
            self.local.append(LocalStep(name, path, read.paths))

    def check_flags(self) -> None:
        """`--only` names known steps; `--no-commit` comes only with `--only`."""
        if self.args.only:
            known = set(STEP_NAMES) | {step.name for step in self.local}
            for wanted in self.args.only.split(","):
                if wanted not in known:
                    local = " ".join(step.name for step in self.local) or "(nothing)"
                    raise Died(
                        f"pm_fold: --only names '{wanted}', which is not a step of this fold.",
                        "The steps are a closed list, in the order they run: "
                        f"{' '.join(STEP_NAMES)}.",
                        f"This checkout's scripts/local/fold.d/ adds: {local}.",
                        NOTHING,
                    )
        if self.args.no_commit and not self.args.only:
            raise Died(
                "pm_fold: --no-commit is legal only with --only.",
                "A WHOLE fold that commits nothing leaves every derived file regenerated in a",
                "working tree nobody wrote down, and the next bank keys its verdict on that",
                "tree. --only names the one subject a caller is tidying; --no-commit says the",
                "rung's own commit will carry it.",
                NOTHING,
            )

    def read_tree_declarations(self) -> None:
        """The tree's own fold-writes blocks, read once; a refused read is exit 2."""
        read = ledger.declared_paths(self.root, WRITES_BEGIN, WRITES_END)
        if read.refused:
            for note in read.notes:
                err(note)
            raise Died(
                "pm_fold: this checkout's fold-writes declarations could not be read "
                "(notes above).",
                "A block the reader refuses is a block whose paths this fold can neither",
                "commit nor call a stray.",
                NOTHING,
            )
        self.tree_paths = read.paths
        for absorbed in ABSORBED_PATHS:
            if absorbed not in DERIVED_PATHS:
                raise Died(
                    f"pm_fold: the absorbed path {absorbed} is not on DERIVED_PATHS.",
                    "An absorbed path is a DERIVED path this fold may find already dirty. Off the",
                    "derived list it would be tolerated by clause 1 and convicted as a stray by",
                    "clause 2, so every fold in this checkout would refuse for a reason two lists",
                    "apart. Put it on both lists or neither.",
                    NOTHING,
                )

    def clause_one(self) -> list[str]:
        """The absorbed paths already dirty; any other dirt is exit 2 (clause 1)."""
        absorbed: list[str] = []
        unsaved: list[str] = []
        for entry in porcelain(self.root):
            path = entry[3:]
            if path in ABSORBED_PATHS and not set(entry[:2]) & {"D", "d"}:
                absorbed.append(path)
                continue
            unsaved.append(entry)
        if unsaved:
            raise refuse(
                f"!! pm_fold: {self.root} has uncommitted changes.",
                *unsaved,
                "   A fold folds a COMMITTED tree. With work already in the checkout there is",
                "   no way to say which of the changes below the fold made, and the commit this",
                "   script would write would carry whatever it swept up. Commit or stash first;",
                "   this script will not decide that for you.",
                f"   {NOTHING}",
            )
        return absorbed

    # --- (a) the contract --------------------------------------------------------------------

    def contract(self) -> None:
        """(a) The committed document and the generated client, regenerated by the byte-pin."""
        out(f"== (a) contract · {self.pin} --write")
        if not self.selected("contract"):
            self.skipped(f"--only {self.args.only} does not name this step")
        elif (
            not (self.root / "frontend/openapi.json").is_file()
            and not (self.root / "frontend/src/api/generated/schema.d.ts").is_file()
        ):
            self.skipped(
                "neither frontend/openapi.json nor the generated client is in this checkout"
            )
        elif not os.access(self.pin, os.X_OK) or not self.pin.is_file():
            raise Died(
                f"pm_fold: the committed contract is here but {self.pin} is not executable.",
                "A committed client this run cannot regenerate is a client nobody can say is",
                "current — could-not-look, never a clean fold.",
                COMMITTED_NOTHING,
            )
        else:
            self.steps_run += 1
            rc = passthrough([str(self.pin), "--write"], self.root)
            if rc != 0:
                raise Died(
                    f"pm_fold: the client generator exited {rc} (its output is above).",
                    "2 is its own could-not-look (no npx, no Node); 1 is a checkout that cannot",
                    "export a schema. Either way the contract was not regenerated and may now be",
                    "half-written.",
                    COMMITTED_NOTHING,
                )
        out()

    # --- (b) the schema dump -----------------------------------------------------------------

    def schema(self) -> None:
        """(b) `manage.py introspect` to `.rung/introspect.json`: regenerated, never committed."""
        out(
            "== (b) schema · manage.py introspect -> .rung/introspect.json "
            "(git-ignored, never committed)"
        )
        ignored = git("check-ignore", "-q", ".rung/introspect.json", cwd=self.root).returncode == 0
        if not self.selected("schema"):
            self.skipped(f"--only {self.args.only} does not name this step")
        elif not (self.root / "manage.py").is_file():
            self.skipped("no manage.py in this checkout — there is no schema to dump")
        elif not ignored:
            self.skipped(
                ".rung/introspect.json is NOT git-ignored in this checkout, so writing it\n"
                "            would manufacture a stray for the footprint census to refuse on. "
                "The dump is\n"
                "            a builder's convenience, never something a fold commits; add "
                "`/.rung/` to\n"
                "            .gitignore and it comes back."
            )
        elif shutil.which(self.uv) is None:
            raise Died(
                f"pm_fold: manage.py is here but there is no {self.uv} on PATH.",
                COMMITTED_NOTHING,
            )
        else:
            self.steps_run += 1
            (self.root / ".rung").mkdir(exist_ok=True)
            dump = self.work / "introspect.json"
            with dump.open("w") as sink, (self.work / "introspect.err").open("w") as errors:
                done = subprocess.run(
                    [self.uv, "run", "python", "manage.py", "introspect"],
                    cwd=self.root,
                    stdout=sink,
                    stderr=errors,
                    check=False,
                )
            if done.returncode != 0:
                sys.stderr.write((self.work / "introspect.err").read_text(errors="replace"))
                raise Died(
                    f"pm_fold: introspect exited {done.returncode} (output above).",
                    "A fold that cannot read this checkout's schema cannot say the derived files",
                    "it is about to commit came from it.",
                    COMMITTED_NOTHING,
                )
            target = self.root / ".rung/introspect.json"
            shutil.copyfile(dump, target)
            out(f"  -> .rung/introspect.json ({target.stat().st_size} bytes)")
        out()

    # --- (c) the secret baseline -------------------------------------------------------------

    def secrets(self) -> None:
        """(c) The full-tree re-scan, the tree's one baseline writer, its moving fields stripped."""
        out(f"== (c) secrets · {self.uv} run detect-secrets scan --baseline .secrets.baseline")
        baseline = self.root / ".secrets.baseline"
        if not self.selected("secrets"):
            self.skipped(f"--only {self.args.only} does not name this step")
            out()
            return
        if not baseline.is_file():
            self.skipped("no .secrets.baseline in this checkout — there is no baseline to shift")
            out()
            return
        if shutil.which(self.uv) is None:
            raise Died(
                f"pm_fold: .secrets.baseline is here but there is no {self.uv} on PATH.",
                COMMITTED_NOTHING,
            )
        self.steps_run += 1
        before = baseline.read_bytes()
        rc = passthrough(
            [self.uv, "run", "detect-secrets", "scan", "--baseline", ".secrets.baseline"],
            self.root,
        )
        if rc != 0:
            raise Died(
                f"pm_fold: detect-secrets exited {rc}.",
                "The baseline was not re-scanned and may now be half-written.",
                COMMITTED_NOTHING,
            )
        after = baseline.read_bytes()
        before_text = before.decode(errors="replace")
        stamps_before = count_lines(before_text, '"generated_at"')
        stamps_after = count_lines(after.decode(errors="replace"), '"generated_at"')
        if stamps_after != 1:
            raise Died(
                f"pm_fold: the scan wrote {stamps_after} generated_at line(s); "
                "this strip is built on exactly one.",
                "detect-secrets' format has moved under this strip. Stripping on a shape this",
                "script no longer recognises would either commit churn on every fold, hide a",
                "real shift, or write a file that is no longer JSON.",
                COMMITTED_NOTHING,
            )
        try:
            after_stripped = strip_baseline(after)
        except ValueError as exc:
            raise Died(
                "pm_fold: could not strip the generated_at stamp from the re-scanned baseline.",
                str(exc) or "the JSON reader said nothing readable.",
                "Without the strip every fold would commit a line that differs on every branch.",
                COMMITTED_NOTHING,
            ) from exc
        try:
            before_stripped = strip_baseline(before)
        except ValueError as exc:
            raise Died(
                "pm_fold: could not strip the committed baseline for comparison.",
                str(exc) or "the JSON reader said nothing readable.",
                "The committed .secrets.baseline is not readable as JSON — a half-resolved",
                "merge is the usual cause, and it is a human's to fix.",
                COMMITTED_NOTHING,
            ) from exc
        left = count_lines(after_stripped, '"generated_at"')
        if left:
            raise Died(
                f"pm_fold: the strip left {left} generated_at line(s) behind.",
                "A strip that does not strip would commit the stamp and bring the merge",
                "conflict class straight back.",
                COMMITTED_NOTHING,
            )
        numbers_left = count_lines(after_stripped, '"line_number"')
        if numbers_left:
            raise Died(
                f"pm_fold: the strip left {numbers_left} line_number key(s) behind.",
                "The same sentence as the stamp one field over: a strip that does not strip",
                "commits a number that moves whenever anything is inserted above a recorded",
                "secret, and two lanes then conflict on it.",
                COMMITTED_NOTHING,
            )
        numbers_before = count_lines(before_text, '"line_number"')
        if before_stripped == after_stripped:
            if stamps_before == 0 and numbers_before == 0:
                baseline.write_bytes(before)
                out(
                    "  no shift — only the generated_at stamp the scan writes on every run "
                    "differed, so the baseline was restored"
                )
            else:
                baseline.write_text(after_stripped)
                out(
                    f"  the always-moving fields were removed ({stamps_before} generated_at, "
                    f"{numbers_before} line_number) — the results did not shift, but the "
                    "committed baseline carried fields that conflict between lanes"
                )
        else:
            grown = grown_results(before, after)
            if grown:
                baseline.write_bytes(before)
                raise Died(
                    f"pm_fold: the scan found {len(grown)} secret(s) the committed baseline "
                    "does not record:",
                    *(f"  {line}" for line in grown),
                    "A baseline only shrinks by itself; a new result is refused, never adopted.",
                    "The road, per line: `# pragma: allowlist secret — <what the literal is and",
                    "why it is no secret>` on the line, or remove the literal. A detect-secrets",
                    "plugin added later grows this list legitimately; regenerating the baseline",
                    "then is the owner's act, not a builder's.",
                    ".secrets.baseline was restored byte-identical. " + COMMITTED_NOTHING,
                )
            baseline.write_text(after_stripped)
            out("  BASELINE SHIFTED — the scan found a different tree than the baseline recorded")
            out(
                "  the next rung brings its own checkout level with: "
                "./scripts/rung_tidy.sh --secrets"
            )
        out()

    # --- (d) the budgets ---------------------------------------------------------------------

    def budgets(self) -> None:
        """(d) Every ceiling the engine printed a lowering for, lowered — never one raised."""
        out("== (d) budgets · quality.gate.check_budgets(), lowerings only")
        budgets = self.root / "quality/budgets.yaml"
        if not self.selected("budgets"):
            self.skipped(f"--only {self.args.only} does not name this step")
            out()
            return
        if not budgets.is_file():
            self.skipped("no quality/budgets.yaml in this checkout — there are no floors to lower")
            out()
            return
        if shutil.which(self.uv) is None:
            raise Died(
                f"pm_fold: quality/budgets.yaml is here but there is no {self.uv} on PATH.",
                COMMITTED_NOTHING,
            )
        self.steps_run += 1
        reader = self.work / "budget_notes.py"
        reader.write_text(BUDGET_READER)
        said_path = self.work / "budget.out"
        with said_path.open("w") as sink:
            done = subprocess.run(
                [self.uv, "run", "python", str(reader)],
                cwd=self.root,
                stdout=sink,
                stderr=subprocess.STDOUT,
                check=False,
            )
        said = said_path.read_text(errors="replace")
        if done.returncode != 0:
            sys.stderr.write(said)
            raise Died(
                f"pm_fold: the budgets check exited {done.returncode} (output above).",
                "A fold cannot lower a floor it could not measure.",
                COMMITTED_NOTHING,
            )
        sys.stdout.write(said)
        summaries = sentences.summary_lines(said)
        if summaries != 1:
            raise Died(
                f"pm_fold: the budgets check printed {summaries} summary line(s), not exactly one.",
                "This parser reads the engine's own sentences; a run whose shape it does not",
                "recognise is a could-not-look, never an empty set of lowerings.",
                COMMITTED_NOTHING,
            )
        claimed = sentences.claimed(said, "notes")
        if not claimed:
            raise Died(
                "pm_fold: the budgets check's summary line did not name a note count.",
                COMMITTED_NOTHING,
            )
        lowerings = sentences.lowerings(said)
        self.lowered = len(lowerings)
        if str(self.lowered) != claimed:
            raise Died(
                f"pm_fold: the budgets check wrote {claimed} note(s) and this parser "
                f"recognised {self.lowered}.",
                "The engine's sentence has moved and this file has not. A parser that reads a",
                "sentence that is no longer printed reports 'nothing to lower', which looks",
                "exactly like a clean tree.",
                COMMITTED_NOTHING,
            )
        if not lowerings:
            if any(line.startswith("budget: ") for line in said.splitlines()):
                out("  nothing to lower — the check reported only RAISES or new subjects, and a")
                out("  raise is a decision that stays a human diff. The fold changes nothing here.")
            else:
                out("  nothing to lower — every recorded ceiling already equals what was measured")
            out()
            return
        try:
            rewritten = apply_lowerings(budgets.read_text(), lowerings)
        except Unapplied as refused:
            for line in refused.said:
                err(line)
            if refused.code == 4 and refused.said[0].startswith("UNREADABLE"):
                raise Died(
                    "pm_fold: a ceiling standing in quality/budgets.yaml is not a number (above: "
                    "section, key, the text found, and the number the note carried), so the fold "
                    "cannot tell lowering from raising and refuses to guess.",
                    "Clause 3 says the fold never raises a ceiling, and it owns that property "
                    "HERE,",
                    "against the file it is rewriting. Owning it means READING the current "
                    "ceiling;",
                    "a line it cannot read is a line it cannot say is being lowered, and "
                    "cannot-say",
                    "is exit 2 here as everywhere. Fix the ceiling by hand, then fold.",
                    "quality/budgets.yaml was not modified and nothing was committed.",
                ) from refused
            if refused.code == 4:
                raise Died(
                    "pm_fold: a lowering note carried a number that is not BELOW the ceiling "
                    "quality/budgets.yaml already records (above: section, key, old, new).",
                    "The fold never raises a ceiling — clause 3 — and it owns that property HERE,",
                    "against the file it is rewriting, rather than inheriting it from whichever",
                    "engine printed the note. A note is an input, and inputs are not trusted.",
                    "quality/budgets.yaml was not modified and nothing was committed.",
                ) from refused
            raise Died(
                "pm_fold: the budgets check named a line quality/budgets.yaml does not contain "
                "(above).",
                "The two files disagree about what a subject is called. Applying the rest and",
                "staying quiet about this one is how a floor stops being a floor.",
                "quality/budgets.yaml was not modified and nothing was committed.",
            ) from refused
        budgets.write_text(rewritten)
        out(f"  {self.lowered} ceiling(s) lowered to the number the gate printed:")
        for section, key, value in lowerings:
            out(f"    {section}  {key}: {value}")
        out()

    # --- (e) the CI walls --------------------------------------------------------------------

    def walls(self) -> None:
        """(e) The latest green CI run's selftest shard walls, into the table this tree owns."""
        walls = Walls(self.root, self.gh, self.work)
        home = walls.home(self.uv)
        out(
            f"== (e) walls · the latest green CI run on main -> "
            f"{home or '<the home could not be read>'}"
        )
        given_population = os.environ.get("DJB_FOLD_WALLS_POPULATION", "")
        if not self.selected("walls"):
            self.skipped(f"--only {self.args.only} does not name this step")
        elif not os.access(self.root / "scripts/check.sh", os.X_OK) and not given_population:
            self.skipped(
                "no scripts/check.sh in this checkout — there is no selftest population to "
                "harvest walls for"
            )
        elif not home:
            self.steps_run += 1
            out(
                "  walls: could not look (the engine's reading of rule_id_namespace did not "
                "answer, so whether this tree's walls belong in the template's table or the "
                "drawer cannot be guessed) — the committed table stands"
            )
        else:
            self.steps_run += 1
            self.harvest_walls(walls, home)
        out()

    def harvest_walls(self, walls: Walls, home: str) -> None:
        """The harvest, judged against the population and written whole, or the table stands."""
        directory = self.work / "walls"
        directory.mkdir(parents=True, exist_ok=True)
        given = os.environ.get("DJB_FOLD_WALLS_DIR", "")
        try:
            if given:
                if not Path(given).is_dir():
                    raise Harvest(1, f"DJB_FOLD_WALLS_DIR={given} is not a directory")
                for path in Path(given).iterdir():
                    if path.is_file():
                        shutil.copyfile(path, directory / path.name)
            else:
                walls.fetch(directory)
        except Harvest as stopped:
            note = directory / "follow.note"
            if note.is_file() and note.stat().st_size:
                out(f"  walls: {note.read_text().rstrip()}")
            if stopped.code == 1:
                out(f"  walls: could not look ({stopped.why}) — the committed table stands")
            else:
                out(f"  walls: NOT harvested — {stopped.why}")
                out(f"         {home} unchanged (a hint, never a partial table).")
            return
        note = directory / "follow.note"
        if note.is_file() and note.stat().st_size:
            out(f"  walls: {note.read_text().rstrip()}")
        self.write_rules(walls, directory, home)
        self.write_modules(directory, home)
        population = walls.population()
        if not population:
            out(
                "  walls: could not look (the selftest population would not derive from "
                "./scripts/check.sh --list-legs) — the committed table stands"
            )
            return
        self.write_walls(directory, population, home)

    def write_walls(self, directory: Path, population: Sequence[str], home: str) -> None:
        """The table rewritten through the ledger's one writer, or `NOT harvested` and why."""
        meta: dict[str, str] = {}
        try:
            for line in (directory / "run.meta").read_text().splitlines():
                key, _, value = line.partition("=")
                meta.setdefault(key, value)
        except OSError:
            pass
        run, machine, tree = meta.get("run", ""), meta.get("machine", ""), meta.get("tree", "")
        rows, split_why = whole_rows(walls_rows(directory))
        why = ""
        if not (run and machine and tree):
            why = (
                "the harvest does not say whose walls they are (run.meta needs run=, machine= "
                "and tree=)"
            )
        else:
            why = "; ".join(x for x in (split_why, walls_judgement(rows, population)) if x)
        if why:
            out(f"  walls: NOT harvested — {why}")
            out(f"         {home} unchanged (a hint, never a partial table).")
            return
        target = self.root / home
        table = directory / "table.json"
        if target.is_file():
            shutil.copyfile(target, table)
        seconds = {
            cells[1]: int(cells[3])
            for cells in (row.split("\t") for row in rows)
            if len(cells) == 5 and cells[3].isdigit()
        }
        try:
            ledger.store_durations(table, machine, f"run:{run} tree:{tree}", seconds)
        except (ledger.Refused, OSError, ValueError):
            out(
                "  walls: NOT harvested — the one writer (gate_member_walls_write) could not "
                "write the table"
            )
            out(f"         {home} unchanged (a hint, never a partial table).")
            return
        members = sum(1 for row in rows if len(row.split("\t")) == 5)
        if target.is_file() and target.read_bytes() == table.read_bytes():
            out(
                f"  walls: harvested run {run} ({members} members, {machine}, tree {tree}) — "
                "the committed table already says exactly this"
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(table, target)
        out(f"  walls: harvested run {run} ({members} members, {machine}, tree {tree}) -> {home}")

    def write_rules(self, walls: Walls, directory: Path, home: str) -> None:
        """The per-rule column from the same run, judged on its own, or `NOT harvested` and why."""
        rows = [
            line
            for path in sorted(directory.glob("*.rules"))
            if path.is_file()
            for line in path.read_text(errors="replace").splitlines()
        ]
        if not rows:
            out(
                "  rules: none in this run — the engine printed no rule-wall line; the column "
                "stands"
            )
            return
        meta = (
            dict(
                line.partition("=")[::2]
                for line in (directory / "run.meta").read_text().splitlines()
                if "=" in line
            )
            if (directory / "run.meta").is_file()
            else {}
        )
        run, machine, tree = meta.get("run", ""), meta.get("machine", ""), meta.get("tree", "")
        ids = walls.rule_ids(self.uv)
        if ids is None:
            out(
                "  rules: could not look (the engine's rule ids did not answer) — the column stands"
            )
            return
        why = (
            rules_judgement(rows, ids, walls_rows(directory))
            if run and machine and tree
            else (
                "the harvest does not say whose walls they are (run.meta needs run=, machine= "
                "and tree=)"
            )
        )
        if why:
            out(f"  rules: NOT harvested — {why}")
            return
        seconds: dict[str, float] = {}
        for cells in (row.split("\t") for row in rows):
            if cells[1] == R.RULE_FIXED:
                seconds[cells[1]] = max(seconds.get(cells[1], 0.0), float(cells[2]))
            else:
                seconds[cells[1]] = float(cells[2])
        target = self.root / home
        try:
            ledger.store_rule_walls(target, machine, f"run:{run} tree:{tree}", seconds)
        except (ledger.Refused, OSError, ValueError):
            out("  rules: NOT harvested — the one writer could not write the table")
            return
        out(f"  rules: harvested run {run} ({len(seconds)} rule rows, {machine}) -> {home}")

    def write_modules(self, directory: Path, home: str) -> None:
        """The per-module column from the same run, judged on its own, or `NOT harvested`."""
        rows = [
            line
            for path in sorted(directory.glob("*.modules"))
            if path.is_file()
            for line in path.read_text(errors="replace").splitlines()
        ]
        if not rows:
            out("  modules: none in this run — no piece wrote a module row; the column stands")
            return
        meta = (
            dict(
                line.partition("=")[::2]
                for line in (directory / "run.meta").read_text().splitlines()
                if "=" in line
            )
            if (directory / "run.meta").is_file()
            else {}
        )
        run, machine, tree = meta.get("run", ""), meta.get("machine", ""), meta.get("tree", "")
        try:
            units = R.load(self.root).units(self.root)
        except (R.RegistryError, CouldNotLook, OSError) as exc:
            out(f"  modules: could not look (the split legs' modules would not list: {exc})")
            return
        why = (
            modules_judgement(rows, units, walls_rows(directory))
            if run and machine and tree
            else (
                "the harvest does not say whose walls they are (run.meta needs run=, machine= "
                "and tree=)"
            )
        )
        if why:
            out(f"  modules: NOT harvested — {why}")
            return
        seconds = {cells[1]: float(cells[2]) for cells in (row.split("\t") for row in rows)}
        try:
            ledger.store_module_walls(self.root / home, machine, f"run:{run} tree:{tree}", seconds)
        except (ledger.Refused, OSError, ValueError):
            out("  modules: NOT harvested — the one writer could not write the table")
            return
        out(f"  modules: harvested run {run} ({len(seconds)} module rows, {machine}) -> {home}")

    # --- (f) the test-impact map -------------------------------------------------------------

    def map(self) -> None:
        """(f) The latest green nightly's test-impact map, or an absorbed one; stale ids pruned."""
        out(f"== (f) map · the latest nightly's test-impact map -> {MAP_PATH}")
        if not self.selected("map"):
            self.skipped(f"--only {self.args.only} does not name this step")
            out()
            return
        if not (self.root / MAP_PATH).is_file():
            self.skipped(f"no {MAP_PATH} in this checkout — there is no map to keep current")
            out()
            return
        self.steps_run += 1
        self.harvest_map()
        self.prune_map()
        out()

    def harvest_map(self) -> None:
        """The night's map copied in when green, fresh and readable; every other answer said."""
        if porcelain(self.root, MAP_PATH):
            self.map_absorbed = True
            out(f"  map: {MAP_PATH} is already modified in this working tree — a bank's")
            out("       acceptance box wrote it, and this tree's own measurement outranks last")
            out("       night's. Absorbed as it stands; nothing was fetched.")
            return
        run = "(given)"
        given = os.environ.get("DJB_FOLD_MAP_DIR", "")
        try:
            if given:
                if not Path(given).is_dir():
                    raise CouldNotLook(f"DJB_FOLD_MAP_DIR={given} is not a directory")
                directory = Path(given)
            else:
                rc, got = ledger.nightly_fetch(self.work / "map", gh=self.gh)
                if rc == 1:
                    raise NoNight(got)
                if rc != 0:
                    raise CouldNotLook(got)
                run, _, fetched = got.split(" ", 2)
                directory = Path(fetched)
            try:
                form = ledger.nightly_read(str(directory))
            except ledger.NightlyUnreadable as exc:
                raise CouldNotLook(f"the record is unreadable: {exc} ") from exc
        except NoNight as none:
            out(f"  map: none — {none} — {MAP_PATH} unchanged")
            return
        except CouldNotLook as cannot:
            out(f"  map: could not look ({cannot}) — {MAP_PATH} unchanged")
            return
        night_map = directory / "test_impact.json"
        map_rc = _field_of(directory / NIGHTLY_RECORD, "map")
        if form.startswith("nightly:stale:"):
            out(
                f"  map: NOT harvested — the latest nightly (run {run}) is older than 24 h ({form})"
            )
            out(f"       — {MAP_PATH} unchanged.")
        elif not form.endswith(" rc=0"):
            out(f"  map: NOT harvested — the latest nightly (run {run}) is red ({form})")
            out(f"       — {MAP_PATH} unchanged; a red night's map is half a measurement.")
        elif map_rc != "0" or not night_map.is_file() or not night_map.stat().st_size:
            out(
                f"  map: NOT harvested — nightly run {run} is green and published no map "
                f"(map={map_rc or '?'})"
            )
            out(f"       — {MAP_PATH} unchanged.")
        elif not _is_map(night_map):
            out(
                f"  map: could not look (nightly run {run}'s test_impact.json is not a map "
                f"python3 can read) — {MAP_PATH} unchanged"
            )
        elif night_map.read_bytes() == (self.root / MAP_PATH).read_bytes():
            out(
                f"  map: harvested nightly run {run} ({form}) — the committed map already says "
                "exactly this"
            )
        else:
            shutil.copyfile(night_map, self.root / MAP_PATH)
            self.map_harvested = True
            out(f"  map: harvested nightly run {run} ({form}) -> {MAP_PATH}")

    def prune_map(self) -> None:
        """Every map entry the collection no longer holds, removed through `test_impact.render`."""
        if not (self.root / MAP_PATH).is_file():
            return
        if not (self.root / "scripts/test_impact.py").is_file():
            out(
                f"  map: could not prune (no scripts/test_impact.py to read a collection with) — "
                f"{MAP_PATH} as it stands"
            )
            return
        collected = os.environ.get("DJB_FOLD_MAP_COLLECTED", "")
        if not collected:
            collected = str(self.work / "map-collected.txt")
            if shutil.which(self.uv) is None:
                out(
                    f"  map: could not prune (no {self.uv} on PATH to collect with) — "
                    f"{MAP_PATH} as it stands"
                )
                return
            with open(collected, "w") as sink:
                done = subprocess.run(
                    [self.uv, "run", "pytest", "--collect-only", "-q", "-p", "no:randomly"],
                    cwd=self.root,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if done.returncode != 0:
                first = next(
                    (
                        x
                        for x in Path(collected).read_text(errors="replace").splitlines()
                        if re.search(r"Error|error", x)
                    ),
                    "no error line",
                )
                out(
                    f"  map: could not prune (the collection exited {done.returncode}: "
                    f"{first}) — "
                    f"{MAP_PATH} as it stands"
                )
                return
        said = prune(self.root, MAP_PATH, Path(collected))
        if said.startswith("could not prune"):
            out(f"  map: {said} — {MAP_PATH} as it stands")
            return
        if said.startswith("pruned"):
            self.map_pruned = int(said.split()[1])
        out(f"  map: {said}")

    # --- (g) the scaffold's goldens ----------------------------------------------------------

    def goldens(self) -> None:
        """(g) Every `golden:` fence, formatted, to the scaffold's template-owned extracts."""
        out(f"== (g) goldens · every fence -> {GOLDENS}/")
        if not self.selected("goldens"):
            self.skipped(f"--only {self.args.only} does not name this step")
        elif not (self.root / "apps/core/scaffold").is_dir():
            self.skipped("no apps/core/scaffold in this checkout — there is no scaffold to feed")
        elif not copier.fenced_apps(self.root, adopt_verbs(self.root)):
            self.skipped("no `golden:` fence in this checkout — the extracts it carries stand")
        else:
            self.steps_run += 1
            try:
                changed = copier.regenerate(self.root)
            except (copier.FenceError, copier.NoFormatter) as error:
                raise Died(
                    f"pm_fold: the goldens could not be extracted: {error}",
                    "A fence the grammar cannot read is a golden nobody can copy, and the extracts",
                    "may now be half-written.",
                    COMMITTED_NOTHING,
                ) from error
            out(f"  goldens: {len(changed)} extract path(s) regenerated")
        out()

    # --- (local) the product's own steps -----------------------------------------------------

    def local_steps(self) -> None:
        """Each drawer step, run and partitioned against its own declaration as it finishes."""
        if not self.local:
            return
        before = set(self.dirty_paths())
        for step in self.local:
            out(f"== (local) {step.name} · {LOCAL_DIR}/{step.name}.sh")
            if not self.selected(step.name):
                self.skipped(f"--only {self.args.only} does not name this step")
                out()
                continue
            self.steps_run += 1
            rc = passthrough([str(step.path)], self.root, stdin=subprocess.DEVNULL)
            if rc != 0:
                raise Died(
                    f"pm_fold: the local step '{step.name}' exited {rc} (its output is above).",
                    "A step that failed did not regenerate what it declares, and this run cannot",
                    "say the declared paths came from this checkout — could-not-look, never a",
                    "clean fold.",
                    COMMITTED_NOTHING,
                )
            gone = [
                entry[3:]
                for entry in porcelain(self.root)
                if set(entry[:2]) & {"D", "d"} and self.declared(entry[3:])
            ]
            if gone:
                raise refuse(
                    f"!! pm_fold: the local step '{step.name}' DELETED a path it declares.",
                    *(f"     {p}" for p in gone),
                    "   A declaration says the step REGENERATES that path. Committing the",
                    '   deletion under "declared path(s) regenerated" would put a removal into',
                    "   the one history nobody reads by hand, and the next fold would red on a",
                    "   generator whose input had vanished a commit earlier.",
                    "   NOTHING WAS COMMITTED. Removing a derived file is a human diff: take the",
                    "   path out of the step's declaration in the same change.",
                )
            after = self.dirty_paths()
            stray = [p for p in after if p not in before and not self.derived(p)]
            if stray:
                raise refuse(
                    f"!! pm_fold: the local step '{step.name}' wrote a path it did not declare.",
                    *(f"     {p}" for p in stray),
                    f"   {LOCAL_DIR}/{step.name}.sh declares:",
                    *(f"     {p}" for p in step.declared),
                    "   A step's declaration is what this fold partitions its output against, and",
                    "   the declaration is the product's own — so a write outside it is not a",
                    "   smaller commit, it is a step that did something nobody wrote down.",
                    "   NOTHING WAS COMMITTED. The tree is left exactly as the run left it, so the",
                    "   evidence is still there: read `git status`.",
                )
            before = set(after)
            out()

    # --- clause 2 and the commit -------------------------------------------------------------

    def subject(self, changed: Sequence[str]) -> str:
        """`fold: <part> · <part>`, one part per kind of derived file that moved."""
        parts: list[str] = []
        if any(
            p == "frontend/openapi.json" or p.startswith("frontend/src/api/generated/")
            for p in changed
        ):
            parts.append("contract regenerated")
        if ".secrets.baseline" in changed:
            parts.append("baseline shifted")
        if "quality/budgets.yaml" in changed:
            parts.append(f"{self.lowered} budgets lowered")
        if MAP_PATH in changed:
            if self.map_harvested:
                parts.append("nightly map harvested")
            elif not self.map_absorbed and self.map_pruned:
                parts.append(f"map pruned ({self.map_pruned} ids no longer collected)")
            else:
                parts.append("acceptance map absorbed")
        if WALLS_TEMPLATE in changed or WALLS_DRAWER in changed:
            parts.append("CI walls harvested")
        if any(p.startswith(f"{GOLDENS}/") for p in changed):
            parts.append("goldens regenerated")
        typed = {
            "frontend/openapi.json",
            ".secrets.baseline",
            "quality/budgets.yaml",
            MAP_PATH,
            WALLS_TEMPLATE,
            WALLS_DRAWER,
        }
        declared = sum(
            1
            for p in changed
            if p not in typed and not p.startswith(("frontend/src/api/generated/", f"{GOLDENS}/"))
        )
        if declared:
            parts.append(f"{declared} declared path(s) regenerated")
        return SUBJECT_PREFIX + " · ".join(parts)

    def finish(self) -> int:
        """Clause 2's census, then nothing, the working tree, or one commit of derived paths."""
        if self.steps_run == 0:
            if self.args.only:
                raise Died(
                    f"pm_fold: --only {self.args.only} selected no step this checkout can run.",
                    "The named step's artifact is not here, so this run regenerated nothing and",
                    "cannot say the file a caller asked about is current. A caller reading a 0",
                    "would read 'already current' off a run that never looked.",
                    COMMITTED_NOTHING,
                )
            raise Died(
                "pm_fold: this checkout has none of the four things a fold folds — no committed "
                "contract, no manage.py, no .secrets.baseline, no quality/budgets.yaml.",
                "That is a reader looking at the wrong tree, not a tree with nothing to fold.",
                COMMITTED_NOTHING,
            )
        out("== the fold's own footprint")
        changed: list[str] = []
        stray: list[str] = []
        for path in self.dirty_paths():
            (changed if self.derived(path) else stray).append(path)
        if stray:
            raise refuse(
                "!! pm_fold: the fold modified a file OUTSIDE the derived list.",
                *(f"     {p}" for p in stray),
                "   A fold regenerates derived files and nothing else. A generator that wrote",
                "   somewhere else did something nobody asked for, and this run cannot say what",
                "   else it did — so it is a could-not-look and not a smaller commit.",
                "   NOTHING WAS COMMITTED. The tree is left exactly as the run left it, so the",
                "   evidence is still there: read `git status`, then `git checkout --` what you",
                "   did not want.",
            )
        short = git_out("rev-parse", "--short", self.pre_head, cwd=self.root)
        if not changed:
            out("  nothing moved — every derived file already agrees with this checkout.")
            out(f"pm_fold: NOTHING TO FOLD. No commit was made; HEAD is still {short}.")
            return 0
        if self.args.no_commit:
            out()
            for path in changed:
                out(f"  changed  {path}")
            out()
            out("pm_fold: --no-commit. The regenerated file(s) above are in the WORKING TREE,")
            out(f"  unstaged and uncommitted; HEAD is still {short}. They")
            out("  belong in the rung's own diff, where a reviewer reads them.")
            return 0
        for path in changed:
            out(f"  changed  {path}")
            if git("add", "--", path, cwd=self.root).returncode != 0:
                raise Died(f"pm_fold: could not stage {path}.", COMMITTED_NOTHING)
        subject = self.subject(changed)
        message = self.work / "message"
        message.write_text(
            f"{subject}\n\nPre-fold tree: {self.pre_tree}\nPre-fold HEAD: {self.pre_head}\n\n"
            "Derived files only, regenerated by scripts/pm_fold.sh. Nothing in this\n"
            "commit was written by hand: the contract is the byte-pin's regeneration,\n"
            "the baseline is detect-secrets', and every budget number is a line the\n"
            'gate itself printed under "a human may commit the lower number". A\n'
            "ceiling is never raised here. The CI walls table is a green CI run's own\n"
            "shard lines, harvested whole or not at all.\n"
        )
        out()
        out(f"pm_fold: committing — {subject}")
        rc = passthrough(["git", "commit", "-F", str(message)], self.root)
        if rc != 0:
            raise refuse(
                f"!! pm_fold: the commit failed (git exit {rc}).",
                "   The derived files above are STAGED and the tree is dirty. A caller that",
                "   banks or merges from here would measure a tree nobody committed — which is",
                "   why this is a 2 and not a warning. Read git's output above (a pre-commit",
                "   hook that went red is the usual cause), then commit or reset by hand.",
            )
        post = git_out("rev-parse", "--verify", "HEAD", cwd=self.root)
        if post == self.pre_head:
            raise Died(
                f"pm_fold: git exited 0 but HEAD did not move ({short}).",
                "A zero status for a commit that produced nothing is the shape a caller reads as",
                "a fold. Nothing here is vouched for.",
            )
        out()
        passthrough(["git", "show", "--stat", "--oneline", post], self.root)
        if porcelain(self.root):
            err("!! pm_fold: the tree is still dirty after the fold commit.")
            passthrough(["git", "status", "--short"], self.root, stdout=sys.stderr)
            raise refuse(
                "   Everything the fold changed was supposed to be in it. A caller banking from",
                "   here would key its verdict on a tree that is in nobody's history.",
            )
        out()
        out(f"pm_fold: FOLDED. {short} -> {git_out('rev-parse', '--short', post, cwd=self.root)}")
        return 0

    def run(self) -> int:
        """Every clause and step in order; the exit code."""
        self.read_drawer()
        self.check_flags()
        if shutil.which("git") is None:
            raise Died("pm_fold: no git on PATH.", NOTHING)
        if git("rev-parse", "--show-toplevel", cwd=self.root).returncode != 0:
            raise Died(f"pm_fold: {self.root} is not inside a git checkout.", NOTHING)
        self.read_tree_declarations()
        absorbed = self.clause_one()
        self.pre_head = git_out("rev-parse", "--verify", "HEAD", cwd=self.root)
        if not self.pre_head:
            raise Died("pm_fold: this checkout has no HEAD to fold.", COMMITTED_NOTHING)
        self.pre_tree = git_out("rev-parse", "--verify", "HEAD^{tree}", cwd=self.root)
        if not self.pre_tree:
            raise Died("pm_fold: could not read HEAD's tree.", COMMITTED_NOTHING)
        subject = git_out("log", "-1", "--format=%s", self.pre_head, cwd=self.root)
        short = git_out("rev-parse", "--short", self.pre_head, cwd=self.root)
        out(f"pm_fold: folding {self.root}")
        out(f"  Pre-fold HEAD  {short}  {subject}")
        out(f"  Pre-fold tree  {self.pre_tree}")
        for path in absorbed:
            out(
                f"  absorbed       {path} — already in the working tree; written from outside "
                "this checkout"
            )
        out()
        self.contract()
        self.schema()
        self.secrets()
        self.budgets()
        self.walls()
        self.map()
        self.goldens()
        self.local_steps()
        return self.finish()


def grown_results(before: bytes, after: bytes) -> list[str]:
    """`path:line <type>` for every scan result whose `(file, hash, type)` `before` lacks."""

    def keyed(raw: bytes) -> dict[tuple[str, str, str], int]:
        data = json.loads(raw)
        return {
            (str(path), str(e.get("hashed_secret")), str(e.get("type"))): int(
                e.get("line_number") or 0
            )
            for path, entries in (data.get("results") or {}).items()
            for e in entries
        }

    known = keyed(before)
    return [
        f"{path}:{line} {kind}"
        for (path, digest, kind), line in sorted(keyed(after).items())
        if (path, digest, kind) not in known
    ]


def strip_baseline(raw: bytes) -> str:
    """The baseline less `generated_at` and every `line_number`, as the scanner writes JSON."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("the baseline is not a JSON object")
    data.pop("generated_at", None)
    for entries in (data.get("results") or {}).values():
        for entry in entries:
            entry.pop("line_number", None)
    return json.dumps(data, indent=2) + "\n"


def _is_map(path: Path) -> bool:
    """Whether `path` reads as a test-impact map: an object with `tests` and `generated`."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get("tests"), dict) and "generated" in data


def prune(root: Path, map_path: str, collected: Path) -> str:
    """One sentence: what the prune did to `map_path` against the collection in `collected`."""
    spec = importlib.util.spec_from_file_location("test_impact", root / "scripts/test_impact.py")
    if spec is None or spec.loader is None:
        return "could not prune (scripts/test_impact.py would not load)"
    module = importlib.util.module_from_spec(spec)
    writes = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — a product's module may raise anything on load
        return f"could not prune (scripts/test_impact.py would not load: {exc})"
    finally:
        sys.dont_write_bytecode = writes
    try:
        held = set(module.read_collected(str(collected)))
    except module.CannotLook as exc:
        return f"could not prune ({str(exc).splitlines()[0]})"
    target = root / map_path
    doc = json.loads(target.read_text(encoding="utf-8"))
    stale = sorted(n for n in doc["tests"] if n not in held)
    if not stale:
        return f"every entry is collected ({len(doc['tests'])}) — nothing pruned"
    for nodeid in stale:
        del doc["tests"][nodeid]
    target.write_text(module.render(doc), encoding="utf-8")
    shown = ", ".join(stale[:5]) + (f" (+{len(stale) - 5} more)" if len(stale) > 5 else "")
    return f"pruned {len(stale)} ids no longer collected — {shown} -> {map_path}"


def died_part_way(cause: str) -> int:
    """The exit guard's sentence for a run that ended outside every refusal this module authors."""
    err("")
    for line in DIED:
        err(line.format(cause=cause))
    return 2


@road(
    "fold",
    example="quality/tests/test_fold.py::test_contract_drift_is_one_commit_of_derived_paths",
)
def main(
    argv: Sequence[str] | None = None,
    root: Path = ROOT,
    hook: Callable[[Fold], None] | None = None,
) -> int:
    """The fold: regenerate this checkout's derived files and commit exactly those, or refuse."""
    try:
        refuse_if_piped()
        root = root.resolve()
        args = parse(list(sys.argv[1:] if argv is None else argv), root)
        if args is None:
            sys.stdout.write(USAGE)
            return 0
        os.chdir(root)
        with tempfile.TemporaryDirectory(prefix="djb-pm-fold.") as work:
            fold = Fold(root, args, Path(work))
            if hook is not None:
                hook(fold)
            return fold.run()
    except Died as died:
        err(f"!! {died.headline}")
        for line in died.lines:
            for part in line.split("\n"):
                err(f"   {part}")
        return 2
    except Printed:
        return 2
    except CouldNotLook as cannot:
        err(f"!! pm_fold: COULD NOT LOOK: {cannot}")
        return 2
    except Exception as exc:  # noqa: BLE001 — the exit guard: a death outside a refusal is exit 2
        return died_part_way(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
