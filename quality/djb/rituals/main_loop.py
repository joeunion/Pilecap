"""Main's `--loop` on a verifier box from a clone pinned to main, its row brought home."""

# does-not-cover: a real box — the box package runs in the clone; its own drive proves its verbs.
# does-not-cover: the box's gate carrying `caller=` into the row — the box package forwards it.

from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import NoReturn

from quality.could_not_look import CouldNotLook
from quality.djb import ledger
from quality.djb.rituals.verify_start import Died, Printed, err, indented, out

#: The checkout this ritual lives in, as the shell's `dirname $0/..`.
ROOT = Path(__file__).resolve().parents[3]
NOTHING = "Nothing was launched."
#: The name the refusals tell the operator to run, as the shell's `$0`.
SELF = "./scripts/pm_main_loop.sh"
#: The first-parent depth the base search reads, as the docs-only road's.
DOCS_ONLY_DEPTH = 60
#: The box client, run as a module inside the clone so its checkout is main's.
BOX = ("-m", "quality.djb.box")
REMOTE_HEAD = "--- last 40 lines of ~/"
WORDS = {0: "green", 1: "red"}
USAGE = f"""\
Run main's `--loop` on a verifier box from a clone pinned to main, and bring its row
home to this checkout's ledger.

  {SELF}                 claim a box (`up --for main-loop`), loop, wait, fetch the log, down
  {SELF} --box <id>      the same on a box already up, which is left up
  {SELF} --base <rev>    scope the loop from <rev> instead of the derived base

Exit: the loop's own — 0 green · 1 red · 2 could not look. The last line is
`main-loop: <green|red|could-not-look> <tree> <s>s <log>`.
"""


def die(headline: str) -> NoReturn:
    """Exit 2 before anything is launched: the headline, then the trailer."""
    raise Died(NOTHING, f"pm_main_loop: {headline}")


def refuse_if_piped() -> None:
    """Exit 2 when stdout is a pipe outside CI: the exit is the loop's verdict on main."""
    if os.environ.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        raise Died(
            "",
            "pm_main_loop refuses pipes — run it bare or redirect to a file.",
            "The exit status is the verdict, and a filter replaces it.",
            "its exit is the loop's verdict on main, and a pipe replaces it with the filter's.",
        )


def git(cwd: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git <argv>` in `cwd`, both streams captured."""
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)


def git_out(cwd: Path, *argv: str) -> str:
    """`git <argv>`'s stdout stripped, or '' when it exits non-zero."""
    done = git(cwd, *argv)
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass
class Args:
    """The command line: a box already up, and a base to scope from."""

    box: str = ""
    base: str = ""


def parse(argv: Sequence[str]) -> Args | None:
    """The arguments, or None for `-h`; an unknown one is exit 2, never a different run."""
    args = Args()
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word in ("-h", "--help"):
            return None
        if word in ("--box", "--base"):
            value = rest.pop(0) if rest else ""
            if not value:
                die(f"{word} takes {'an instance id' if word == '--box' else 'a revision'}.")
            setattr(args, word[2:], value)
            continue
        die(f"unknown argument '{word}'. Usage: {SELF} [--box <id>] [--base <rev>]")
    return args


def local_path(root: Path, name: str) -> str:
    """`gate_local_path <name>`: `<the absolute git common dir>/<name>`, or ''."""
    common = git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return f"{common}/{name}" if common else ""


def drop_own_path() -> None:
    """The wrapper's `PYTHONPATH` entry withheld from every child this run starts."""
    entries = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    kept = [e for e in entries if e and os.path.realpath(e) != str(ROOT)]
    if kept:
        os.environ["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        os.environ.pop("PYTHONPATH", None)


class MainLoop:
    """One run: refused before anything is launched, or a box claimed, looped, read and downed."""

    def __init__(self, root: Path, args: Args) -> None:
        self.root = root
        self.args = args
        self.started = time.monotonic()
        self.main = ""
        self.tree = ""
        self.ledger = Path()
        self.home = Path()
        self.name = ""
        self.log = Path()
        self.base = ""
        self.why = ""
        self.clone = Path()
        self.env: dict[str, str] = {}
        self.instance = ""
        self.owned = False
        self.waiting: subprocess.Popen[bytes] | None = None
        self.interrupted = False

    def run(self) -> int:
        """Refuse, derive, clone, then the box; the loop's own exit."""
        self.refuse_the_checkout()
        self.read_main()
        self.derive_base()
        out(f"pm_main_loop: main {self.main[:8]} tree {self.tree}")
        out(f"base       {self.base[:8]} ({self.why})")
        out(f"ledger     {self.ledger}")
        self.make_clone()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, self.on_signal)
        return self.loop()

    def refuse_the_checkout(self) -> None:
        """The primary, clean, standing where this ritual lives — else exit 2, nothing launched."""
        top = git_out(Path.cwd(), "rev-parse", "--show-toplevel")
        if not top:
            die("not inside a git checkout")
        if Path(top).resolve() != self.root.resolve():
            die(
                f"you are standing in {top}, which is not the checkout this script lives in"
                f" ({self.root})."
            )
        here = git_out(self.root, "rev-parse", "--path-format=absolute", "--git-dir")
        common = git_out(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if not here or Path(here).resolve() != Path(common).resolve():
            die(
                f"{self.root} is a linked worktree; run it from the primary checkout, whose"
                " ledger the row comes home to."
            )
        dirt = git(self.root, "status", "--short")
        if dirt.returncode != 0 or dirt.stdout.strip():
            sys.stderr.write(dirt.stdout)
            die(
                f"{self.root} has uncommitted changes — a merge in progress or an edit nobody"
                " committed; main's loop waits for a clean primary."
            )

    def read_main(self) -> None:
        """Main's commit, its measured tree, the ledger, and the home the logs land in."""
        self.main = git_out(
            self.root, "rev-parse", "--verify", "--quiet", "refs/heads/main^{commit}"
        )
        if not self.main:
            die(f"{self.root} has no local main")
        try:
            self.tree = ledger.measured_tree_of(self.root, f"{self.main}^{{tree}}")
        except (CouldNotLook, ledger.Mismatch):
            die(f"the measured tree of main {self.main[:8]} would not read")
        try:
            self.ledger = ledger.ledger_path(self.root)
        except (CouldNotLook, ledger.Refused, ledger.Mismatch):
            die("this checkout's ledger path would not read")
        self.env = {
            **os.environ,
            "DJB_GATE_LEDGER": str(self.ledger),
            "DJB_GATE_CALLER": "main-loop",
        }
        home = os.environ.get("DJB_MAIN_LOOP_HOME") or local_path(self.root, "djb-main-loop")
        if not home.startswith("/"):
            die(f"DJB_MAIN_LOOP_HOME='{home}' is not absolute")
        self.home = Path(home)
        try:
            self.home.mkdir(parents=True, exist_ok=True)
        except OSError:
            die(f"could not make {self.home}")
        self.name = f"main-loop-{self.main[:8]}"
        self.log = self.home / f"{self.name}.log"

    def derive_base(self) -> None:
        """`--base`, else the newest row-named tree, the newest merge's parent, main's parent."""
        if self.args.base:
            self.base = git_out(
                self.root, "rev-parse", "--verify", "--quiet", f"{self.args.base}^{{commit}}"
            )
            if not self.base:
                die(f"--base {self.args.base} names no commit")
            ancestor = git(self.root, "merge-base", "--is-ancestor", self.base, self.main)
            if self.base == self.main or ancestor.returncode != 0:
                die(f"--base {self.args.base} is not a proper ancestor of main {self.main[:8]}")
            self.why = f"--base {self.args.base}"
            return
        depth = int(os.environ.get("GATE_DOCS_ONLY_DEPTH") or DOCS_ONLY_DEPTH)
        for commit in ledger.ancestors(self.root, self.main, depth):
            try:
                tree = ledger.measured_tree_of(self.root, f"{commit}^{{tree}}")
            except (CouldNotLook, ledger.Mismatch):
                continue
            if ledger.loop_tree_row(self.root, tree, ledger.loop_rows(self.ledger)):
                self.base = commit
                self.why = (
                    "the newest row-named tree on the first-parent line or a merge's second parent"
                )
                return
        merge = git_out(
            self.root, "rev-list", "--first-parent", "--merges", "--max-count=1", self.main
        )
        if merge:
            self.base = git_out(self.root, "rev-parse", f"{merge}^1")
            self.why = "the newest merge's first parent"
            return
        self.base = git_out(self.root, "rev-parse", "--verify", "--quiet", f"{self.main}^1")
        if not self.base:
            die(f"main {self.main[:8]} is a root commit; there is no base to scope a loop from")
        self.why = "main's parent"

    def make_clone(self) -> None:
        """A fresh clone at main carrying the base as `refs/djb/base` and the repository's hooks."""
        self.clone = self.home / "checkout"
        shutil.rmtree(self.clone, ignore_errors=True)
        cloned = git(
            self.root,
            "clone",
            "--quiet",
            "--single-branch",
            "--branch",
            "main",
            str(self.root),
            str(self.clone),
        )
        if cloned.returncode != 0:
            sys.stderr.write(cloned.stderr)
            die(f"could not clone {self.root} into {self.clone}")
        if git_out(self.clone, "rev-parse", "HEAD") != self.main:
            die(f"the clone at {self.clone} is not at main {self.main[:8]}")
        git(self.clone, "update-ref", "refs/djb/base", self.base)
        git(self.clone, "config", "core.hooksPath", "scripts/githooks")
        if not (self.clone / "quality" / "djb" / "box" / "__main__.py").is_file():
            die("main carries no quality/djb/box package to claim a box with")
        path = [
            str(self.clone),
            *(p for p in self.env.get("PYTHONPATH", "").split(os.pathsep) if p),
        ]
        self.env["PYTHONPATH"] = os.pathsep.join(path)
        out(f"clone      {self.clone} at {self.main[:8]}, refs/djb/base {self.base[:8]}")

    def box(self, *argv: str, sink: Path | None = None) -> int:
        """One box verb in the clone, its streams this run's or `sink`'s: its exit."""
        sys.stdout.flush()
        sys.stderr.flush()
        command = [sys.executable, *BOX, *argv]
        try:
            if sink is None:
                return subprocess.run(command, cwd=self.clone, env=self.env, check=False).returncode
            with sink.open("wb") as fh:
                done = subprocess.run(
                    command,
                    cwd=self.clone,
                    env=self.env,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
            return done.returncode
        except OSError as error:
            err(f"!! pm_main_loop: the box client would not start: {error}")
            return 2

    def on_signal(self, signum: int, frame: FrameType | None) -> None:
        """A signal ends the run: the wait is stopped now, every other verb finishes first."""
        self.interrupted = True
        if self.waiting is not None and self.waiting.poll() is None:
            self.waiting.terminate()

    def check_signal(self) -> None:
        """Down the box this run owns and stop, when a signal arrived."""
        if self.interrupted:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_DFL)
            err("pm_main_loop: interrupted — downing the box it owns")
            self.finish(2)

    def loop(self) -> int:
        """Claim or push, loop, wait, fetch, read the row: `finish`'s exit."""
        if self.args.box:
            self.instance = self.args.box
            pushed = self.box("push", self.instance)
            self.check_signal()
            if pushed != 0:
                self.finish(2)
        else:
            up_log = self.home / f"up-{self.name}.log"
            up_rc = self.box("up", "--for", "main-loop", sink=up_log)
            text = up_log.read_text(errors="replace") if up_log.is_file() else ""
            sys.stdout.write(text)
            self.instance = next(
                (
                    w[1]
                    for w in (line.split() for line in text.splitlines())
                    if w[:1] == ["instance"] and len(w) > 1
                ),
                "",
            )
            self.owned = bool(self.instance)
            self.check_signal()
            if up_rc != 0 or not self.instance:
                self.finish(2)
        looped = self.box("loop", self.instance, "--log", self.name)
        self.check_signal()
        if looped != 0:
            self.finish(2)
        rc = self.wait()
        self.check_signal()
        self.fetch()
        if rc == 0:
            row = ledger.loop_tree_row(self.root, self.tree, ledger.loop_rows(self.ledger))
            if row:
                out(f"main-loop: row {row}")
            else:
                err(
                    f"!! pm_main_loop: the loop was green and no loop row names tree {self.tree}"
                    f" in {self.ledger}"
                )
        self.finish(rc)

    def wait(self) -> int:
        """The box's wait into its log, stoppable by a signal: its exit."""
        wait_log = self.home / f"wait-{self.name}.log"
        sys.stdout.flush()
        try:
            with wait_log.open("wb") as fh:
                self.waiting = subprocess.Popen(
                    [sys.executable, *BOX, "wait", self.instance, self.name],
                    cwd=self.clone,
                    env=self.env,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                )
                rc = self.waiting.wait()
        except OSError as error:
            err(f"!! pm_main_loop: the box client would not start: {error}")
            rc = 2
        self.waiting = None
        sys.stdout.write(wait_log.read_text(errors="replace") if wait_log.is_file() else "")
        return rc

    def fetch(self) -> None:
        """The box's log home as this run's log, else the wait's output in its place."""
        wait_log = self.home / f"wait-{self.name}.log"
        text = wait_log.read_text(errors="replace") if wait_log.is_file() else ""
        remote = next(
            (
                line[len(REMOTE_HEAD) : -len(" ---")]
                for line in text.splitlines()
                if line.startswith(REMOTE_HEAD) and line.endswith(" ---")
            ),
            "",
        )
        if not remote or self.box("fetch", self.instance, remote, str(self.log)) != 0:
            err(
                f"!! pm_main_loop: the box's log did not come home; {self.log} holds the wait's"
                " output instead"
            )
            if wait_log.is_file():
                shutil.copyfile(wait_log, self.log)

    def finish(self, rc: int) -> NoReturn:
        """Down an owned box, append and print the verdict line, exit `rc`."""
        if self.owned and self.instance and self.box("down", self.instance) != 0:
            err(
                f"!! pm_main_loop: could not take {self.instance} down — run:"
                f" scripts/verifier_box.sh down {self.instance}"
            )
        word = WORDS.get(rc, "could-not-look")
        code = rc if rc in WORDS else 2
        line = f"main-loop: {word} {self.tree} {int(time.monotonic() - self.started)}s {self.log}"
        with self.log.open("a") as fh:
            fh.write(f"{line}\n")
        out(line)
        raise Exit(code)


class Exit(Exception):
    """The run's exit, raised by `finish` once the verdict line is written."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`pm_main_loop [--box <id>] [--base <rev>]`: 0 green · 1 red · 2 could not look."""
    drop_own_path()
    try:
        refuse_if_piped()
        args = parse(list(sys.argv[1:] if argv is None else argv))
        if args is None:
            sys.stdout.write(USAGE)
            return 0
        return MainLoop(root, args).run()
    except Exit as done:
        return done.code
    except Died as died:
        err(f"!! {died.headline}")
        indented(*died.lines)
        if died.trailer:
            indented(died.trailer)
        return 2
    except Printed:
        return 2
    except CouldNotLook as cannot:
        err(f"!! COULD NOT LOOK: {cannot}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
