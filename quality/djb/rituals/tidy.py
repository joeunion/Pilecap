"""The rung tidy: a refusal's prescribed bookkeeping, applied through the instrument owning it."""

# does-not-cover: whether a raise is legitimate — the number the engine printed lands in the diff.
# does-not-cover: the generator's first-run network — `pin_client.sh`'s exit and words carry.
# does-not-cover: whether the tidied tree passes — `./scripts/check.sh --loop` is the caller's.
# does-not-cover: a fourth budget sentence shape — the count cross-check makes it a could-not-look.

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import budgets as sentences

#: The checkout this ritual tidies: the one it lives in, as the shell's `dirname $0/..`.
ROOT = Path(__file__).resolve().parents[3]
SUBJECTS = ("budgets", "client", "secrets")
PIN = "frontend/scripts/pin_client.sh"
DOCUMENT = "frontend/openapi.json"
CLIENT = "frontend/src/api/generated/schema.d.ts"
#: The tree's one legal baseline writer, and the arguments that keep it out of the index.
FOLD = "scripts/pm_fold.sh"
FOLD_ARGV = ("--only", "secrets", "--no-commit")
SECTION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:[ \t]*$")
USAGE = """\
usage: rung_tidy.sh [--budgets] [--client] [--secrets] [-h]

  Applies the bookkeeping the gate's own refusals prescribe. With no flag it
  does every subject this checkout has; a subject that is not here is
  `skipped`, printed, at exit 0.

  --budgets  Write the ceilings the engine's `budget:` lines named into
             quality/budgets.yaml — the RAISE and the NEW SUBJECT, which are
             the two shapes that end in a pasteable line. A LOWERING note is
             left alone: it is the fold's, under its clause 3.
  --client   Regenerate the committed client and document through
             frontend/scripts/pin_client.sh --write. Never the generator
             directly.
  --secrets  Re-scan .secrets.baseline through scripts/pm_fold.sh --only
             secrets --no-commit, so the tree's ONE legal baseline writer stays
             the one legal baseline writer.

  It never commits, never stages and never runs the gate.

exit: 0 applied, or nothing to apply · 1 a subject it could not apply cleanly
      · 2 refused, or could not look (2 outranks a pass).
"""
DONE = {
    0: "rung_tidy: DONE. Nothing was staged and nothing was committed — the changes above are "
    "in the working tree, for the caller's own diff.",
    1: "rung_tidy: A SUBJECT COULD NOT BE APPLIED CLEANLY (above). Nothing was staged and "
    "nothing was committed.",
    2: "rung_tidy: COULD NOT LOOK (above). Nothing was staged and nothing was committed.",
}

Collect = Callable[[Path], str]
#: `(section, key, value)` — one record line the engine printed under a sentence.


class Refused(CouldNotLook):
    """Exit 2 before any subject ran; its sentences are already on stderr."""


def out(text: str = "") -> None:
    """One line on stdout, flushed before any child writes beside it."""
    print(text, flush=True)


def err(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def refuse_if_piped() -> None:
    """Exit 2 when stdout is a pipe outside CI (`refuse_if_piped`): the exit is the verdict."""
    if os.environ.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        err("!! rung_tidy refuses pipes — run it bare or redirect to a file.")
        err("   The exit status is the verdict, and a filter replaces it.")
        raise Refused


def parse(argv: Sequence[str]) -> tuple[str, ...] | None:
    """The subjects asked for, every one when none is named; None for `-h`."""
    wanted: list[str] = []
    for word in argv:
        if word in ("-h", "--help"):
            return None
        if word.startswith("--") and word[2:] in SUBJECTS:
            wanted.append(word[2:])
            continue
        err(f"!! rung_tidy takes --budgets, --client and --secrets; got '{word}'.")
        sys.stderr.write(USAGE)
        raise Refused
    return tuple(s for s in SUBJECTS if s in wanted) if wanted else SUBJECTS


@dataclass
class Tidy:
    """One run over one checkout: the subjects in order, the verdict composed 2 > 1 > 0."""

    root: Path
    collect: Collect
    status: int = 0
    said: list[str] = field(default_factory=list)

    def raise_to(self, code: int) -> None:
        """The verdict never lowered by a later subject."""
        self.status = max(self.status, code)

    def skipped(self, subject: str, reason: str) -> None:
        """A subject this checkout does not have: printed, never silent."""
        out(f"tidy {subject}: skipped — {reason}")

    def budgets(self) -> None:
        """Write the ceilings the engine's pasteable lines named, and only those."""
        budgets = self.root / "quality/budgets.yaml"
        if not budgets.is_file():
            self.skipped(
                "budgets",
                "no quality/budgets.yaml in this checkout — there are no ceilings to write",
            )
            return
        try:
            text = self.collect(self.root)
        except Exception as error:  # noqa: BLE001 — any engine failure is a could-not-look here
            err(f"!! tidy budgets: the budgets check raised {type(error).__name__}: {error}")
            err("   A tidy cannot write a ceiling it could not measure.")
            self.raise_to(2)
            return
        if sentences.summary_lines(text) != 1:
            err("!! tidy budgets: the budgets check did not print exactly one summary line.")
            err("   This reader reads the engine's own sentences; a run whose shape it does")
            err("   not recognise is a could-not-look, never an empty set.")
            self.raise_to(2)
            return
        stated = sentences.claimed(text, "problems")
        if not stated:
            err("!! tidy budgets: the summary line did not name a problem count.")
            self.raise_to(2)
            return
        named = sentences.pastables(text)
        if str(len(named)) != stated:
            sys.stderr.write(text)
            err(f"!! tidy budgets: the budgets check wrote {stated} problem(s) and this reader")
            err(f"   recognised {len(named)} pasteable line(s). The engine's sentence has moved")
            err("   and this reader has not — could-not-look, never a tidy that applied some")
            err("   of them.")
            self.raise_to(2)
            return
        from quality.engine.run import EXAMPLE_BUDGET_APPS

        follows = sentences.follows(text, EXAMPLE_BUDGET_APPS)
        followed = {(sect, key) for sect, key, _old, _new in follows}
        for sect, key, value in sentences.lowerings(text):
            if (sect, key) not in followed:
                out(f"  budget lowering {sect}.{key} -> {value}: left for the fold (clause 3)")
        if not named and not follows:
            out("tidy budgets: nothing to do")
            return
        moves = [*named, *((sect, key, new) for sect, key, _old, new in follows)]
        try:
            written, applied = apply_pastables(budgets.read_text(), moves)
        except Unapplied as unapplied:
            for line in unapplied.said:
                err(line)
            err("!! tidy budgets: a line the engine named could not be applied (above).")
            err("   UNREADABLE is a ceiling standing in quality/budgets.yaml that is not a")
            err("   number; NOSECTION is a section the engine names and the file does not")
            err("   have. Either way this run cannot say what it would have written, so")
            err("   quality/budgets.yaml was NOT modified.")
            self.raise_to(2)
            return
        budgets.write_text(written)
        if named:
            out(f"tidy budgets: {len(named)} ceiling(s) written from the lines the engine printed")
        for sect, key, old, new in applied:
            if (sect, key) in followed:
                out(
                    f"  re-recorded {key} {old} → {new} (the worked example's ceiling follows"
                    " its measurement — advisory)"
                )
            else:
                out(f"  budget applied: {sect}.{key} {old} → {new}")

    def client(self) -> None:
        """Regenerate the committed client and document through the pin, and say what moved."""
        pin, paths = self.root / PIN, (self.root / DOCUMENT, self.root / CLIENT)
        if not any(path.is_file() for path in paths):
            self.skipped(
                "client", f"neither {DOCUMENT} nor the generated client is in this checkout"
            )
            return
        if not os.access(pin, os.X_OK) or not pin.is_file():
            err(f"!! tidy client: the committed contract is here but {pin} is not executable.")
            err("   A committed client this run cannot regenerate is a client nobody can say")
            err("   is current — could-not-look, never a clean tidy.")
            self.raise_to(2)
            return
        before = [read_or_none(path) for path in paths]
        rc = relay([str(pin), "--write"], self.root)
        if rc == 2:
            err("!! tidy client: the client generator could not look (exit 2, its output above).")
            err("   That is the generator's own code for an absent toolchain — no npx or Node")
            err("   on PATH. The OpenAPI document it exports is complete; what is missing is")
            err("   the thing that reads it.")
            self.raise_to(2)
            return
        if rc != 0:
            err(f"!! tidy client: the client generator exited {rc} (its output above).")
            err("   1 is a checkout that cannot export a schema — a finding in this tree, not")
            err("   in the generator.")
            self.raise_to(1)
            return
        moved = sum(1 for path, was in zip(paths, before, strict=True) if read_or_none(path) != was)
        out(f"tidy client: regenerated {moved} file(s)" if moved else "tidy client: nothing to do")

    def secrets(self) -> None:
        """Re-scan the baseline through the fold, which is its one writer, and say if it moved."""
        baseline = self.root / ".secrets.baseline"
        if not baseline.is_file():
            self.skipped(
                "secrets",
                "no .secrets.baseline in this checkout — there is no baseline to bring level",
            )
            return
        fold = Path(os.environ.get("DJB_TIDY_FOLD") or self.root / FOLD)
        if not os.access(fold, os.X_OK) or not fold.is_file():
            err(f"!! tidy secrets: {fold} is not executable.")
            err("   It is the tree's ONE legal baseline writer and this ritual deliberately")
            err("   owns no second one. Could-not-look.")
            self.raise_to(2)
            return
        before = baseline.read_bytes()
        rc = relay([str(fold), *FOLD_ARGV], self.root)
        if rc != 0:
            err(f"!! tidy secrets: the fold exited {rc} (its output above).")
            err("   The fold never answers 1, so this is a refusal or a could-not-look — a")
            err("   dirty tree is the usual cause, and the fold folds a COMMITTED tree")
            err("   whichever flags it was handed. Commit the boundary and re-run.")
            self.raise_to(2)
            return
        if read_or_none(baseline) == before:
            out("tidy secrets: nothing to do")
        else:
            out("tidy secrets: the baseline was re-scanned and rewritten, stampless and numberless")

    def run(self, subjects: Sequence[str]) -> int:
        """Every subject asked for, then the closing line on the stream its verdict owns."""
        out(f"== rung_tidy · {self.root}")
        out()
        for subject in subjects:
            getattr(self, subject)()
        out()
        (out if self.status == 0 else err)(DONE[min(self.status, 2)])
        return self.status


class Unapplied(CouldNotLook):
    """A named line could not be applied: `UNREADABLE`/`NOSECTION` lines, in the file's order."""

    def __init__(self, said: list[str]) -> None:
        super().__init__(len(said))
        self.said = said


def read_or_none(path: Path) -> bytes | None:
    """The file's bytes, or None when it is not there."""
    return path.read_bytes() if path.is_file() else None


def relay(argv: Sequence[str], cwd: Path) -> int:
    """`argv` in `cwd` into a file, never a pipe, relayed as `  | <line>`; its exit returned."""
    with tempfile.TemporaryFile() as sink:
        try:
            rc = subprocess.run(
                list(argv), cwd=cwd, stdout=sink, stderr=subprocess.STDOUT, check=False
            ).returncode
        except OSError as error:
            out(f"  | {argv[0]}: {error}")
            return 127
        sink.seek(0)
        said = sink.read().decode(errors="replace")
    for line in said.splitlines():
        out(f"  | {line}")
    return rc


def engine_sentences(root: Path) -> str:
    """The engine's budget problems and notes, the example's follows, and the summary line."""
    from quality import engine
    from quality.engine.run import EXAMPLE_BUDGET_APPS
    from quality.worlds import read_budgets

    measures = Path(engine.ROOT).resolve()
    if measures != root.resolve():
        raise ValueError(f"the engine in this process measures {measures}, not {root}")
    before = len(engine.notes)
    problems = engine.check_budgets()
    notes = engine.notes[before:]
    recorded = read_budgets(root) or {}
    moved = [
        f"{sentences.FOLLOW} {section} {key} {ceiling} {value}"
        for section, subjects in engine._measure_budgets_detailed().items()
        for key, (value, _label) in subjects.items()
        if key.startswith(EXAMPLE_BUDGET_APPS)
        and (ceiling := (recorded.get(section) or {}).get(key)) is not None
        and str(ceiling) != str(value)
    ]
    summary = f"{sentences.SUMMARY}notes={len(notes)} problems={len(problems)}"
    return "\n".join([*problems, *notes, *moved, summary]) + "\n"


def apply_pastables(
    text: str, named: Sequence[sentences.Record]
) -> tuple[str, list[tuple[str, str, str, str]]]:
    """`budgets.yaml`, raises in place, new subjects after the section's last non-blank line."""
    lines = text.splitlines()
    sections: list[str] = []
    header: dict[str, int] = {}
    last: dict[str, int] = {}
    section = ""
    for at, line in enumerate(lines):
        if SECTION.match(line):
            section = re.sub(r":[ \t]*$", "", line)
            header[section] = at
        sections.append(section)
        if section and line.strip(" \t"):
            last[section] = at
    said: list[str] = []
    applied: list[tuple[str, str, str, str]] = []
    hit = [False] * len(named)
    for at, line in enumerate(lines):
        for i, (sect, key, value) in enumerate(named):
            prefix = f"  {key}: "
            if hit[i] or sections[at] != sect or not line.startswith(prefix):
                continue
            tail = line[len(prefix) :]
            comment = ""
            if "#" in tail:
                old, mark = tail.split("#", 1)
                comment = re.sub(r"^[^ \t]*", "", old) + "#" + mark
            else:
                old = tail
            old = old.rstrip(" \t")
            if not re.fullmatch(r"[0-9]+", old):
                said.append(f"UNREADABLE {sect} {key} {old} {value}")
            lines[at] = prefix + value + comment
            applied.append((sect, key, old, value))
            hit[i] = True
    inserts: dict[int, list[str]] = {}
    for i, (sect, key, value) in enumerate(named):
        if hit[i]:
            continue
        at = last.get(sect, header.get(sect, -1))
        if at < 0:
            said.append(f"NOSECTION {sect} {key}")
            continue
        inserts.setdefault(at, []).append(f"  {key}: {value}")
        applied.append((sect, key, "none", value))
        hit[i] = True
    if said:
        raise Unapplied(said)
    written: list[str] = []
    for at, line in enumerate(lines):
        written += [line, *inserts.get(at, [])]
    return "".join(f"{line}\n" for line in written), applied


def main(
    argv: Sequence[str] | None = None, root: Path = ROOT, collect: Collect | None = None
) -> int:
    """`rung_tidy [--budgets] [--client] [--secrets]`: 0 applied · 1 unclean · 2 could not look."""
    try:
        refuse_if_piped()
        subjects = parse(list(sys.argv[1:] if argv is None else argv))
    except Refused:
        return 2
    if subjects is None:
        sys.stdout.write(USAGE)
        return 0
    return Tidy(root, collect or engine_sentences).run(subjects)


if __name__ == "__main__":
    raise SystemExit(main())
