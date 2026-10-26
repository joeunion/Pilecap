"""The merge ritual: a returned branch merged into this checkout, refused loudly, then gated."""

# does-not-cover: whether the branch should be merged — criteria and verification are the PM's.
# does-not-cover: a conflict's resolution — refused and the tree's state named, never resolved.
# does-not-cover: the full gate — `--fast` is the default tier; `--bank` hands on to `check.sh`.
# does-not-cover: any remote — pushing is the push ritual's.
# does-not-cover: a hand edit committed after a fold as its own commit — only merges are read.
# does-not-cover: a delta path a leg reaches by glob or walk — the docs-only decider judges it.

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from apps.core.roads import road
from quality.could_not_look import CouldNotLook
from quality.djb import ledger

#: The checkout this ritual merges into: the one it lives in, as the shell's `dirname $0/..`.
ROOT = Path(__file__).resolve().parents[3]
NOTHING_MERGED = "Nothing was merged and the working tree was not touched."
FLAG_USAGE = (
    "<branch> [-m <msg-file|->] [--bank [--no-fold]] [--resolution <file>]"
    " [--main-unmeasured <who>:<why>]"
)
USAGE = """\
Merge a returned builder's branch into this checkout, and own the exit status.
The PM's one merge path.

  pm_merge.sh <branch>                  merge --no-ff, git's default message
  pm_merge.sh <branch> -m FILE          ...with the message in FILE
  pm_merge.sh <branch> -m -             ...with the message on stdin
  pm_merge.sh <branch> --bank           ...and gate the merged tree FULLY, banking a verdict
  pm_merge.sh <branch> --resolution F   ...admitting folds that differ from merge-tree,
                                        each path `<path> — <why>`
  pm_merge.sh <branch> --main-unmeasured <who>:<why>
                                        ...onto a main no loop has read, the sanction printed

Main is read when a loop row names main's tree, or a docs-only delta from the nearest
row-named tree on the first-parent line or a merge's second parent.
"""
NO_FOLD_WITHOUT_BANK = """\
pm_merge: --no-fold is only meaningful with --bank, and this is not a --bank run.
   The fold runs at the BANK: it regenerates the derived files and commits them
   BEFORE the gate measures the tree, so that the verdict vouches for the tree
   that is committed. A --fast merge banks no verdict, so no fold runs here and
   there is nothing for --no-fold to skip. Accepting it silently would be a flag
   that did nothing with no line printed.
   scripts/pm_push.sh refuses the same combination in the same words."""
DOCS_ONLY_DEPTH = 60
TIER_TEXT = {
    "--bank": (
        "  THE FULL GATE, asked for with --bank: two whole-suite passes, the supply",
        "                chain, the canary self-test, every shell refusal drive, and a",
        "                verdict recorded against this tree with caller=pm-bank.",
        "  It takes the machine-wide full-gate lease and one of this box's pytest",
        "  slots, so every other full gate here waits behind it. That is the price of",
        "  a verdict, and it is the same price the pre-push hook pays unwatched.",
    ),
    "--fast": (
        "  NOT run here: pytest, the supply chain, the canary self-test, the shell",
        "                refusal drives, the verdict. Those bind at push. See this",
        "                script's header for why the self-test is not here (ADR gate-3).",
        "  To BANK a verdict for the merged tree before pushing it — the ritual full",
        "  gate, which is legal from this checkout and refused from a rung worktree —",
        "  pass --bank to THIS script, or run it yourself:",
        '      {gate} --bank > "$PWD/bank.log" 2>&1',
        "  It records caller=pm-bank and a sanction on the verdict row. Skipping it is",
        "  legal too: the pre-push hook runs the same gate if the tree has no verdict.",
    ),
}


class Died(CouldNotLook):
    """Exit 2 in `gate_die`'s shape: `!! <headline>`, its lines indented, then the trailer."""

    def __init__(self, trailer: str, headline: str, *lines: str) -> None:
        super().__init__(headline)
        self.trailer = trailer
        self.headline = headline
        self.lines = lines


class Printed(CouldNotLook):
    """Exit 2 whose sentences are already on stderr."""


class Exited(Exception):
    """A status the ritual already explained: git's own, the fold's, or the gate's."""

    def __init__(self, rc: int) -> None:
        super().__init__(rc)
        self.rc = rc


def out(text: str = "") -> None:
    """One line on stdout, flushed before any child writes beside it."""
    print(text, flush=True)


def err(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def indented(*texts: str) -> None:
    """`gate__indented`: every line of every text on stderr, indented three."""
    for text in texts:
        for line in text.split("\n"):
            err(f"   {line}")


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git -C <root> <argv>`, both streams captured."""
    return subprocess.run(
        ["git", "-C", str(root), *argv], capture_output=True, text=True, check=False
    )


def git_out(root: Path, *argv: str) -> str:
    """`git -C <root> <argv>`'s stdout stripped, or '' when it exits non-zero."""
    done = git(root, *argv)
    return done.stdout.strip() if done.returncode == 0 else ""


def passthrough(root: Path, *argv: str) -> int:
    """`git -C <root> <argv>` on this process's streams, its exit returned."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(["git", "-C", str(root), *argv], check=False).returncode


def short(root: Path, rev: str) -> str:
    """`git rev-parse --short <rev>`."""
    return git_out(root, "rev-parse", "--short", rev)


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
            "",
            "pm_merge refuses pipes — run it bare or redirect to a file.",
            "The exit status is the verdict, and a filter replaces it.",
            "this script exists BECAUSE a merge was piped through a grep that could not match"
            " git's refusal.",
        )


@dataclass
class Args:
    """The command line: one branch, the message, the tier and the three typed admissions."""

    branch: str = ""
    message: str = ""
    tier: str = "--fast"
    no_fold: bool = False
    resolution: str = ""
    main_unmeasured: str = ""


def parse(argv: Sequence[str]) -> Args | None:
    """The arguments, or None for `-h`; an unknown flag is exit 2, never a different merge."""
    args = Args()
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word in ("-h", "--help"):
            return None
        if word == "--bank":
            args.tier = "--bank"
        elif word == "--no-fold":
            args.no_fold = True
        elif word in ("--resolution", "--main-unmeasured", "-m"):
            args = typed_value(args, word, rest)
        elif word.startswith("-"):
            raise Died(
                NOTHING_MERGED,
                f"pm_merge: unknown flag '{word}'. Usage: scripts/pm_merge.sh {FLAG_USAGE}",
            )
        elif args.branch:
            raise Died(
                NOTHING_MERGED, f"pm_merge: one branch at most; got '{args.branch}' and '{word}'."
            )
        else:
            args.branch = word
    if not args.branch:
        raise Died(
            NOTHING_MERGED,
            "pm_merge: no branch named. Usage: scripts/pm_merge.sh <branch> [-m <msg-file|->]",
        )
    if args.no_fold and args.tier != "--bank":
        raise Died(NOTHING_MERGED, NO_FOLD_WITHOUT_BANK)
    return args


def typed_value(args: Args, word: str, rest: list[str]) -> Args:
    """`-m`, `--resolution` or `--main-unmeasured` and its one value; twice or bare is exit 2."""
    field, missing = {
        "-m": ("message", "pm_merge: -m needs a message file, or - for stdin."),
        "--resolution": (
            "resolution",
            "pm_merge: --resolution needs a file of <path> — <why> lines.",
        ),
        "--main-unmeasured": (
            "main_unmeasured",
            "pm_merge: --main-unmeasured takes <who>:<why>.",
        ),
    }[word]
    if not rest:
        raise Died(NOTHING_MERGED, missing)
    if getattr(args, field):
        raise Died(NOTHING_MERGED, f"pm_merge: {word} given twice.")
    setattr(args, field, rest.pop(0))
    return args


# invariant: a fold whose merge-tree reports a conflict lists its conflicted paths — never a pass.
@road("fold_check", example="quality/tests/test_merge.py::test_a_clean_fold_prints_equals")
def fold_rows(root: Path, onto: str, tip: str) -> Iterator[tuple[str, list[str]]]:
    """`(sha, differing paths)` per merge on `tip` whose second parent is on `onto`."""
    merges = git(root, "rev-list", "--reverse", "--merges", f"{onto}..{tip}")
    if merges.returncode != 0:
        raise CouldNotLook(f"git rev-list {onto}..{tip} exited {merges.returncode}")
    for m in merges.stdout.split():
        p2 = git_out(root, "rev-parse", "--verify", "--quiet", f"{m}^2")
        if not p2 or git(root, "merge-base", "--is-ancestor", p2, onto).returncode != 0:
            continue
        p1 = git_out(root, "rev-parse", "--verify", "--quiet", f"{m}^1")
        if not p1:
            raise CouldNotLook(f"{m} has no first parent")
        done = git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", p1, p2)
        if done.returncode > 1:
            raise CouldNotLook(f"git merge-tree exited {done.returncode} for {m}")
        lines = done.stdout.split("\n")
        if not git_out(root, "rev-parse", "--verify", "--quiet", f"{lines[0]}^{{tree}}"):
            raise CouldNotLook(f"git merge-tree wrote no tree for {m}")
        diff = git(root, "diff", "--name-only", "--no-renames", lines[0], f"{m}^{{tree}}")
        if diff.returncode != 0:
            raise CouldNotLook(f"git diff exited {diff.returncode} for {m}")
        paths = set(diff.stdout.split("\n"))
        if done.returncode != 0:
            paths.update(lines[1:])
        yield m, sorted(p for p in paths if p)


def drive_rows(root: Path) -> list[list[str]]:
    """Every drive row's words."""
    return [
        line.split()
        for _, line in ledger.rows(ledger.ledger_path(root))
        if line.split()[:3][::2] == [ledger.SCHEMA, "drive"]
    ]


@dataclass
class MainRead:
    """`main_is_read`'s answer: the word, main's tree, and what the word carries."""

    word: str
    tree: str
    origin: str = ""
    paths: str = ""
    count: int = 0
    key: str = ""
    at: str = ""
    depth: int = 0


@road(
    "main_read",
    example="quality/tests/test_merge.py::test_merge_reads_main_through_a_trains_second_parent",
)
def main_is_read(root: Path, head: str) -> MainRead:
    """Whether a loop read main: its tree's row, or a docs-only delta from the nearest row's."""
    depth = int(os.environ.get("GATE_DOCS_ONLY_DEPTH") or DOCS_ONLY_DEPTH)
    try:
        tree = ledger.measured_tree_of(root, f"{head}^{{tree}}")
    except ledger.Mismatch as error:
        raise CouldNotLook(f"the measured tree of {head} would not read: {error}") from error
    row = ledger.loop_tree_row(root, tree, ledger.loop_rows(ledger.ledger_path(root)))
    if row:
        words = row.split()
        return MainRead("read", tree, key=words[1], at=words[3])
    for c in ledger.ancestors(root, head, depth):
        try:
            t = ledger.measured_tree_of(root, f"{c}^{{tree}}")
        except ledger.Mismatch:
            continue
        row = ledger.loop_tree_row(root, t, ledger.loop_rows(ledger.ledger_path(root)))
        if not row:
            continue
        try:
            prose = ledger.loop_key_prose(root, ledger.measured_tree(root))
            delta = ledger.docs_only_delta(
                root, t, tree, None if prose is None else frozenset(prose)
            )
        except (CouldNotLook, ledger.Mismatch) as error:
            raise CouldNotLook(f"the docs-only delta from {t} would not read: {error}") from error
        bad = [p for kind, p in delta if kind != "docs"]
        if bad:
            return MainRead("unread", tree, origin=t, paths=" ".join(bad))
        words = row.split()
        return MainRead("docs-only", tree, t, count=len(delta), key=words[1], at=words[3])
    return MainRead("unread", tree, origin="-", depth=depth)


def red_main_loop_log(root: Path, tree: str) -> str:
    """`main's last loop on this tree: <verdict> — <log>` from the newest main-loop log, or ''."""
    home = os.environ.get("DJB_MAIN_LOOP_HOME") or str(
        Path(git_out(root, "rev-parse", "--git-common-dir") or ".git") / "djb-main-loop"
    )
    where = Path(home) if home.startswith("/") else root / home
    best: tuple[float, Path, str] | None = None
    for log in sorted(where.glob("main-loop-*.log")):
        if not log.is_file():
            continue
        lines = log.read_text(errors="replace").splitlines()
        words = lines[-1].split() if lines else []
        if len(words) < 3 or words[0] != "main-loop:" or words[2] != tree:
            continue
        mtime = log.stat().st_mtime
        if best is None or mtime > best[0]:
            best = (mtime, log, words[1])
    return "" if best is None else f"main's last loop on this tree: {best[2]} — {best[1]}"


def resolution_lines(path: str) -> list[tuple[int, str]]:
    """`(line number, line)` for every line of the resolution file, a last unterminated one too."""
    text = Path(path).read_text()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return list(enumerate(lines, 1))


def judge_resolution(path: str, differing: list[str]) -> tuple[list[str], list[str]]:
    """`(refusals, admitted lines)`: exactly the differing paths, each `<path> — <why>`."""
    bad: list[str] = []
    admitted: list[str] = []
    named: set[str] = set()
    for number, line in resolution_lines(path):
        if not line:
            continue
        where, sep, why = line.partition(" — ")
        if not sep or not where or re.search(r"\s", where) or not why.strip():
            bad.append(
                f"could not merge: --resolution {path} line {number} is not <path> — <why>: {line}"
            )
            continue
        named.add(where)
        admitted.append(line)
    bad += [
        f"could not merge: --resolution {path} does not name {p}"
        for p in differing
        if p not in named
    ]
    bad += [
        f"could not merge: --resolution {path} names {p}, which no fold differs in"
        for p in sorted(named)
        if p not in differing
    ]
    return bad, admitted


class Merge:
    """One run: the checkout, the branch's tip, main before, and what each step decided."""

    def __init__(self, root: Path, args: Args) -> None:
        self.root = root
        self.args = args
        self.gate = root / "scripts" / "check.sh"
        self.tip = ""
        self.before = ""
        self.onto = ""
        self.sanction = ""
        self.admitted: list[str] = []

    def run(self) -> int:
        """Refuse, read main and the folds, merge, prove it, consult, fold at the bank, gate."""
        self.refuse_before_merging()
        self.read_main()
        self.read_folds()
        self.merge()
        after = self.prove()
        consult(self.root, self.args.branch, self.tip, self.before, after)
        template_advisory(self.root)
        if self.args.tier == "--bank":
            rc = ledger.bank_arm(
                self.root,
                who="pm_merge",
                no_fold=self.args.no_fold,
                nothing=(
                    "THE MERGE ABOVE IS ALREADY MADE and the gate did not run; the next move is"
                    f" a fix commit, or 'git -C {self.root} reset --hard"
                    f" {short(self.root, self.before)}'."
                ),
            )
            if rc != 0:
                raise Exited(rc)
        return self.exec_gate()

    def refuse_before_merging(self) -> None:
        """The checkout, gate, branch, tree and ancestry: each refusal exit 2, nothing merged."""
        top = git_out(Path.cwd(), "rev-parse", "--show-toplevel")
        if not top:
            raise Died(NOTHING_MERGED, "pm_merge: not inside a git checkout")
        if not Path(top).samefile(self.root):
            raise Died(
                NOTHING_MERGED,
                f"pm_merge: you are standing in {top}, which is not the checkout this script"
                f" lives in ({self.root}). Run the pm_merge.sh that belongs to the tree you mean"
                " to merge into.",
            )
        if not (self.gate.is_file() and os.access(self.gate, os.X_OK)):
            raise Died(
                NOTHING_MERGED,
                f"pm_merge: no executable gate at {self.gate} — a merge this script cannot gate"
                " is a merge it will not make",
            )
        branch = self.args.branch
        self.tip = git_out(self.root, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}")
        if not self.tip:
            self.refuse_unknown_branch()
        dirt = git(self.root, "status", "--porcelain")
        if dirt.stdout.strip():
            err(f"!! pm_merge: {self.root} has uncommitted changes.")
            sys.stderr.flush()
            passthrough(self.root, "status", "--short")
            err("   Merging on top of them would produce a tree whose contents nobody can")
            err("   attribute, and the gate below would measure the mixture. Commit or")
            err("   stash them first; this script will not decide that for you.")
            raise Printed("a dirty tree")
        self.before = git_out(self.root, "rev-parse", "--verify", "HEAD")
        if not self.before:
            raise Died(NOTHING_MERGED, "pm_merge: this checkout has no HEAD commit")
        self.onto = git_out(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        if git(self.root, "merge-base", "--is-ancestor", self.tip, self.before).returncode == 0:
            err(
                f"!! pm_merge: {branch} ({short(self.root, self.tip)}) is ALREADY an ancestor"
                f" of {self.onto}."
            )
            err("   git would exit 0 saying 'Already up to date' — a success status for a")
            err("   merge that did not happen. If you meant a different branch, name it;")
            err("   if this work is already in, the ledger row is what needs the edit.")
            err(f"   {NOTHING_MERGED}")
            raise Printed("already an ancestor")
        subject = git_out(self.root, "log", "-1", "--format=%s", self.before)
        tip_subject = git_out(self.root, "log", "-1", "--format=%s", self.tip)
        count = git_out(self.root, "rev-list", "--count", f"{self.before}..{self.tip}")
        out(f"pm_merge: merging into {self.onto} in {self.root}")
        out(f"  onto          {short(self.root, self.before)}  {subject}")
        out(f"  MERGING       {short(self.root, self.tip)}  {tip_subject}")
        out(f"  branch        {branch}")
        out(
            f"  RANGE         {short(self.root, self.before)}..{short(self.root, self.tip)}"
            f"  ({count} commit(s) not yet in {self.onto})"
        )

    def refuse_unknown_branch(self) -> None:
        """A name that resolves to nothing: exit 2, naming the near misses."""
        branch = self.args.branch
        err(f"!! pm_merge: '{branch}' names no commit in {self.root}.")
        err("   git would have said 'not something we can")
        err("   merge' on one line, and a filtered merge would have swallowed it.")
        names = git_out(self.root, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        tail = branch[-8:] if len(branch) >= 8 else ""
        near = [n for n in names.splitlines() if tail in n][:5]
        if near:
            err("   Local branches whose names end similarly:")
            for name in near:
                err(f"     {name}")
        else:
            err(f"   Local branches: {''.join(f'{n} ' for n in names.splitlines()[:8])}")
        err(f"   {NOTHING_MERGED}")
        raise Printed("no such branch")

    def read_main(self) -> None:
        """Condition 1: a loop has read main, or a typed sanction stands in for the read."""
        typed = self.args.main_unmeasured
        if typed:
            if not re.match(r"^[^:]+:", typed):
                raise Died(
                    NOTHING_MERGED, f"pm_merge: --main-unmeasured takes <who>:<why>; got '{typed}'."
                )
            who, _, why = typed.partition(":")
            try:
                self.sanction = ledger.Sanction("typed", who, why.removeprefix(" ")).check().field()
            except ledger.Refused as refused:
                err(f"!! {refused}. Nothing was judged.")
                raise Died(
                    NOTHING_MERGED,
                    f"could not merge: --main-unmeasured '{typed}' is not a sanction — see above.",
                ) from refused
        try:
            read = main_is_read(self.root, self.before)
        except (CouldNotLook, ledger.Refused) as error:
            raise Died(
                NOTHING_MERGED,
                f"could not merge: main's loop row could not be read (main_is_read: {error})",
            ) from error
        if read.word != "unread":
            if self.sanction:
                raise Died(
                    NOTHING_MERGED,
                    f"could not merge: --main-unmeasured was given and main is read"
                    f" ({read.tree[:8]}); drop it — a sanction is written only where a loop did"
                    " not read",
                )
            if read.word == "read":
                out(f"  main: read — loop row {read.key} banked {read.at}")
            else:
                out(
                    f"  main: read — docs-only delta from {read.origin[:8]} ({read.count} paths),"
                    f" loop row {read.key} banked {read.at}"
                )
            return
        if self.sanction:
            out(f"  main: UNMEASURED — {self.sanction}")
            return
        tail = (
            "run ./scripts/pm_main_loop.sh and read its line, or pass --main-unmeasured <who>:<why>"
        )
        if read.origin == "-":
            headline = (
                f"could not merge: main {read.tree[:8]} has no green loop row and no first-parent"
                f" ancestor within {read.depth} commits, nor a merge's second parent among them,"
                f" has one; {tail}"
            )
        else:
            headline = (
                f"could not merge: main {read.tree[:8]} has no green loop row and its delta from"
                f" {read.origin[:8]} is not docs-only ({read.paths}); {tail}"
            )
        last = red_main_loop_log(self.root, read.tree)
        raise Died(NOTHING_MERGED, headline, *([last] if last else []))

    def read_folds(self) -> None:
        """The fold rule: every fold on the branch read against merge-tree, before the merge."""
        try:
            rows = list(fold_rows(self.root, self.before, self.tip))
        except CouldNotLook as error:
            version = git_out(self.root, "--version")
            raise Died(
                NOTHING_MERGED,
                "could not merge: git merge-tree --write-tree could not answer for a fold on"
                f" {self.args.branch} (it needs git 2.38 or later; this is {version})",
            ) from error
        differs: list[str] = []
        differing: set[str] = set()
        if not rows:
            base = git_out(self.root, "merge-base", self.before, self.tip)
            out(
                f"  fold: none — no merge of {self.onto} on {self.args.branch} since"
                f" {short(self.root, base)}"
            )
        for sha, paths in rows:
            if not paths:
                out(f"  fold {sha[:8]}: equals merge-tree")
                continue
            out(
                f"  fold {sha[:8]}: differs from merge-tree — {len(paths)} paths: {' '.join(paths)}"
            )
            differs.append(f"fold {sha[:8]} differs from merge-tree in {' '.join(paths)}")
            differing.update(paths)
        resolution = self.args.resolution
        if resolution:
            if not (os.path.isfile(resolution) and os.access(resolution, os.R_OK)):
                raise Died(
                    NOTHING_MERGED,
                    f"could not merge: --resolution {resolution} is not a readable file",
                )
            bad, self.admitted = judge_resolution(resolution, sorted(differing))
            if not bad and not differing:
                bad = [
                    f"could not merge: --resolution {resolution} was given and no fold on"
                    f" {self.args.branch} differs from merge-tree"
                ]
            if bad:
                rest = ["\n".join(bad[1:])] if len(bad) > 1 else []
                raise Died(
                    NOTHING_MERGED, bad[0], *rest, *(["\n".join(differs)] if differs else [])
                )
        elif differs:
            raise Died(
                NOTHING_MERGED,
                f"could not merge: {differs[0]}; pass --resolution <file> naming each path and why",
                *(["\n".join(differs[1:])] if len(differs) > 1 else []),
            )

    def merge(self) -> None:
        """`git merge --no-ff`, its status read at once; a failure names the tree's state."""
        argv = ["merge", "--no-ff", "--no-edit"]
        message = self.args.message
        scratch = ""
        if message == "-":
            text = sys.stdin.read()
            if not text:
                raise Died(
                    NOTHING_MERGED,
                    "pm_merge: -m - was given but stdin was empty; a merge message nobody wrote is"
                    " worse than git's default",
                )
            handle, scratch = tempfile.mkstemp(prefix="djb-pm-merge-msg.")
            with os.fdopen(handle, "w") as sink:
                sink.write(text)
            argv += ["-F", scratch]
        elif message:
            if not (os.path.isfile(message) and os.access(message, os.R_OK)):
                raise Died(
                    NOTHING_MERGED,
                    f"pm_merge: -m {message}: no such readable file (use - to read the message"
                    " from stdin)",
                )
            argv += ["-F", message]
        argv.append(self.args.branch)
        out(f"pm_merge: git {' '.join(argv)}")
        try:
            rc = passthrough(self.root, *argv)
        finally:
            if scratch:
                os.unlink(scratch)
        if rc == 0:
            return
        err("")
        err(f"!! pm_merge: THE MERGE FAILED (git exit {rc}). Nothing below ran.")
        if git(self.root, "rev-parse", "--verify", "--quiet", "MERGE_HEAD").returncode == 0:
            err(f"   WORKING TREE: MID-MERGE. {self.root} now holds a merge in progress.")
            err("   Unmerged paths:")
            passthrough(self.root, "diff", "--name-only", "--diff-filter=U")
            err(f"   Resolve them and commit, or 'git -C {self.root} merge --abort' to put the")
            err("   tree back. This script does neither for you: an automatic abort")
            err("   would destroy a resolution somebody may already have started.")
        else:
            err("   WORKING TREE: unchanged — the merge was refused before it began.")
            passthrough(self.root, "status", "--short")
        raise Exited(rc)

    def prove(self) -> str:
        """`git log -1 --oneline` as the proof, after HEAD moved and the tip has two parents."""
        after = git_out(self.root, "rev-parse", "--verify", "HEAD")
        if after == self.before:
            err(
                "!! pm_merge: git exited 0 but HEAD did not move"
                f" ({short(self.root, self.before)})."
            )
            err("   A zero status for a merge that produced no commit is exactly the shape")
            err("   a filtered pipe would hide. Nothing is vouched for here; the gate did not run.")
            raise Printed("HEAD did not move")
        if not git_out(self.root, "rev-parse", "--verify", "--quiet", f"{after}^2"):
            err(
                f"!! pm_merge: the new tip {short(self.root, after)} has ONE parent — it is not"
                " a merge commit,"
            )
            err("   though --no-ff was given. Something is not what this script assumes.")
            raise Printed("one parent")
        out("")
        out("pm_merge: MERGED. Proof of merge — git log -1 --oneline:")
        out(git_out(self.root, "log", "-1", "--oneline"))
        out(f"  parents       {git_out(self.root, 'log', '-1', '--format=%p', after)}")
        for line in self.admitted:
            out(f"  resolution    {line}")
        if self.sanction:
            out(f"  main-unmeasured {self.sanction}")
        return after

    def exec_gate(self) -> int:
        """The tier named, then `exec` the gate: nothing runs between a red gate and the caller."""
        tier = self.args.tier
        out("")
        out(f"pm_merge: gating the merged tree — {self.gate} {tier}")
        for line in TIER_TEXT[tier]:
            out(line.format(gate=self.gate))
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(str(self.gate), [str(self.gate), tier])  # noqa: S606 — execs this checkout's own gate script with a fixed tier word


def declaring_drives(root: Path, changed: list[str]) -> list[str]:
    """Every `scripts/tests/test_*.sh` whose `# drives:` line covers a changed path."""
    found = []
    for drive in sorted((root / "scripts" / "tests").glob("test_*.sh")):
        if not drive.is_file():
            continue
        head = drive.read_text(errors="replace").splitlines()[: ledger.DRIVE_MARKER_LINES]
        line = next(
            (m.group(1) for m in map(re.compile(r"^#\s*drives:(.*)$").match, head) if m), None
        )
        if line is None:
            continue
        declared = [t.rstrip("/") for t in line.split()]
        if any(p == d or p.startswith(f"{d}/") for d in declared for p in changed):
            found.append(drive.relative_to(root).as_posix())
    return found


def drive_seen(
    drives: list[list[str]], looped: set[str], name: str, tree: str
) -> tuple[bool, bool]:
    """`(green here, a loop records it)` for one drive by its rows (`merge_drive_loop_seen`)."""
    green_here = recorded = False
    for words in drives:
        if len(words) < 5 or words[4] != name:
            continue
        green = "exit=0" in words[5:]
        at = next((w for w in reversed(words[5:]) if w.startswith("tree=")), "")
        if at == f"tree={tree}":
            recorded = True
            green_here = green_here or green
        elif green and at in looped:
            recorded = True
    return green_here, recorded


def consult(root: Path, branch: str, tip: str, before: str, after: str) -> None:
    """The loop consult and the drives line: advisory, after the merge, and never a verdict."""
    try:
        tip_tree = ledger.measured_tree_of(root, f"{tip}^{{tree}}")
    except (ledger.Mismatch, CouldNotLook):
        out(f"  loop consult: could not look — the measured tree of {branch}'s head would not read")
        return
    try:
        loops = ledger.loop_rows(ledger.ledger_path(root))
        row = ledger.loop_tree_row(root, tip_tree, loops)
        drives = drive_rows(root)
    except (ledger.Refused, ledger.Mismatch, OSError) as error:
        out(f"  loop consult: could not look — the ledger would not read: {error}")
        return
    if row:
        words = row.split()
        box = next((w[4:] for w in reversed(words) if w.startswith("box=")), "")
        out(
            f"  loop consult: HIT — tree {tip_tree} ({branch}'s head) key {words[1]}"
            f" {f'box={box} ' if box else ''}banked {words[3]}"
        )
    else:
        out(
            f"  loop consult: MISS — no loop row names tree {tip_tree} ({branch}'s head); the"
            " verifier's consult re-measures"
        )
    changed = ledger.changed_between(root, before, after)
    declaring = declaring_drives(root, changed)
    if not declaring:
        out("  drives: no shell drive declares a file this merge changed")
        return
    looped = {w for line in loops for w in line.split()[4:] if w.startswith("tree=")}
    ran: list[str] = []
    red: list[str] = []
    unrecorded: list[str] = []
    for path in declaring:
        name = path.rsplit("/", 1)[-1].removeprefix("test_").removesuffix(".sh")
        green_here, recorded = drive_seen(drives, looped, name, tip_tree)
        (ran if green_here else red if recorded else unrecorded).append(name)
    out(
        f"  drives: {len(declaring)} declare this merge's files — ran green on the branch head's"
        f" tree ({tip_tree}): {', '.join(ran) or 'none'}; red or absent on it:"
        f" {', '.join(red) or 'none'}; not recorded by any loop: {', '.join(unrecorded) or 'none'}"
    )
    if red:
        out(
            f"  !! drives red or absent on these bytes that a loop records: {', '.join(red)} — a"
            " finding; run them on a box before the bank"
        )
    if unrecorded:
        out(
            f"          not recorded by any loop ({len(unrecorded)}): no --loop runs them, so they"
            " meet these files first at the bank — information, not a finding"
        )


def template_advisory(root: Path) -> None:
    """The template database republished for the next wave; advisory, it cannot fail the merge."""
    if not (root / "scripts" / "db.sh").is_file():
        return
    sys.stdout.flush()
    sys.stderr.flush()
    subprocess.run(
        [
            "bash",
            "-c",
            "set +u; . scripts/db.sh >/dev/null 2>&1 || exit 0; db_template_refresh_advisory",
        ],
        cwd=root,
        check=False,
    )


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`merge <branch> [-m <file|->] [--bank [--no-fold]] [--resolution <f>] …`: 0 · 1 · 2."""
    try:
        refuse_if_piped()
        args = parse(list(sys.argv[1:] if argv is None else argv))
        if args is None:
            sys.stdout.write(USAGE)
            return 0
        return Merge(root, args).run()
    except Died as died:
        err(f"!! {died.headline}")
        indented(*died.lines)
        if died.trailer:
            indented(died.trailer)
        return 2
    except Exited as exited:
        return exited.rc
    except Printed:
        return 2
    except CouldNotLook as cannot:
        err(f"!! COULD NOT LOOK: {cannot}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
