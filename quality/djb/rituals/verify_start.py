"""The verify start: a rung branch cloned, unioned with main, provisioned, seeded, proven clean."""

# does-not-cover: whether the merge is the right merge — main as this checkout has it at clone time.
# does-not-cover: the database and the schema — named for `./scripts/setup.sh`, never created here.
# does-not-cover: a conflicted merge's meaning — the paths are named, whose fault it is is not.
# does-not-cover: a repository that does not ignore `.env` — the verdict-key step refuses it.
# does-not-cover: the identity carry's validity — `ZITADEL_*` lines move by name, unaudited.
# does-not-cover: whether a seeded `--loop` row will hit — the prediction reads the tree half only.
# does-not-cover: the box push and a CI checkout carry no remote; the drawer file does.
# does-not-cover: a consult row banked on another environment for the same bytes reads as a HIT.
# does-not-cover: the docs-only decider's declarations are this checkout's, not the clone's.

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import ledger

#: The checkout this ritual clones from: the one it lives in, as the shell's `dirname $0/..`.
ROOT = Path(__file__).resolve().parents[3]
#: Six steps; `--no-loop` adds the consult as the seventh.
STEP_TOTAL = 6
#: Copies of the source ledger taken before a moving source is could-not-look (GF6.2).
RECOPY_BOUND = 5
NOTHING_TOUCHED = "Nothing was cloned, merged or written."
UNPROVEN = (
    "The step may have done its work; this script could not prove it,\n"
    "and a step it cannot prove is never reported as done."
)
SEED_ROW = re.compile(r"^v1 loop-v1:[0-9a-f]{64} loop ")
ZITADEL_LINE = re.compile(r"^ZITADEL_[A-Z0-9_]+=")
DOCS_DIRT = "docs/product/"
EMAIL = "verify-start@localhost"
USAGE = """\
usage: verify_start.sh <rung-branch> [--no-sync] [--no-loop] [<destination>]
       verify_start.sh --check [<checkout>]
       verify_start.sh -h

  scripts/verify_start.sh runs `python -m quality.djb.rituals.verify_start`.

  <rung-branch>   the branch the rung was built on, as this checkout has it.
  <destination>   where the clone goes. Default: $TMPDIR/djb-verify/<branch>.
                  It must not already exist with anything in it.

  --no-sync       skip the python-dependencies step. The clone then has no
                  venv, and the seeded --loop rows CANNOT HIT — the ledger's
                  environment fingerprint censuses .venv and refuses an empty
                  one, so the first --loop re-measures in full.

  --no-loop       step 7: consult the ledger for the union and print the
                  `loop:` cell instead of leaving a --loop to run. A MISS is
                  information (exit 0); nothing is measured.

  --check         run THE LAST STEP alone — the verdict-key guard — against an
                  existing checkout (default: the one you are standing in).
                  Nothing is cloned, merged or written.

  In the clone, `source scripts/db.sh` before the engine (python -m quality.gate):
  it names the clone's own database and task queue, never the source's.

exit: 0 ready · 1 a step ran and failed · 2 refused, or a step could not be
      verified (2 outranks a pass).
"""


class Died(CouldNotLook):
    """Exit 2 in `gate_die`'s shape: `!! <headline>`, its lines indented, then the trailer."""

    def __init__(self, trailer: str, headline: str, *lines: str) -> None:
        super().__init__(headline)
        self.trailer = trailer
        self.headline = headline
        self.lines = lines


class Finding(Exception):
    """Exit 1 in `gate_finding`'s shape: a step ran and came back with a real answer."""

    def __init__(self, headline: str, *lines: str) -> None:
        super().__init__(headline)
        self.headline = headline
        self.lines = lines


class Printed(CouldNotLook):
    """Exit 2 whose sentences are already on stderr."""


def out(text: str = "") -> None:
    """One line on stdout, flushed before any child writes beside it."""
    print(text, flush=True)


def say(text: str) -> None:
    """`steps.sh::say`: the line, indented three."""
    out(f"   {text}")


def err(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def indented(*texts: str) -> None:
    """`gate__indented`: every line of every text on stderr, indented three."""
    for text in texts:
        for line in text.split("\n"):
            err(f"   {line}")


def clock_fmt(seconds: float) -> str:
    """`clock_fmt`'s `<n.nn>s`."""
    return f"{seconds:.2f}s"


def pause(seconds: int) -> None:
    """The PATH's `sleep`, bounded by real time in this process."""
    try:
        subprocess.run(["sleep", str(seconds)], timeout=seconds + 30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return


def git(*argv: str) -> subprocess.CompletedProcess[str]:
    """`git <argv>`, both streams captured."""
    return subprocess.run(["git", *argv], capture_output=True, text=True, check=False)


def git_out(*argv: str) -> str:
    """`git <argv>`'s stdout stripped, or '' when it exits non-zero."""
    done = git(*argv)
    return done.stdout.strip() if done.returncode == 0 else ""


def passthrough(argv: Sequence[str], cwd: Path | None = None) -> int:
    """`argv` with this process's streams, its exit returned."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        return subprocess.run(list(argv), cwd=cwd, check=False).returncode
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
            "",
            "verify_start refuses pipes — run it bare or redirect to a file.",
            "The exit status is the verdict, and a filter replaces it.",
        )


@dataclass
class Args:
    """The command line: the mode, the branch, the destination and the two skips."""

    mode: str = "clone"
    branch: str = ""
    dest: str = ""
    check_dir: str = ""
    no_sync: bool = False
    no_loop: bool = False


def usage_refusal(sentence: str) -> Printed:
    """The sentence and the usage on stderr; the exit-2 it ends in."""
    err(sentence)
    sys.stderr.write(USAGE)
    sys.stderr.flush()
    return Printed(sentence)


def parse(argv: Sequence[str]) -> Args | None:
    """The arguments, or None for `-h`; an unknown option is exit 2, never a different run."""
    args = Args()
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word in ("-h", "--help"):
            return None
        if word == "--no-sync":
            args.no_sync = True
        elif word == "--no-loop":
            args.no_loop = True
        elif word == "--check":
            args.mode = "check"
            if rest and not rest[0].startswith("-"):
                args.check_dir = rest.pop(0)
            if rest and not rest[0].startswith("-"):
                raise usage_refusal(f"!! --check takes at most one path; got '{rest[0]}' as well.")
        elif word.startswith("-"):
            raise usage_refusal(f"!! verify_start: unknown option '{word}'.")
        elif not args.branch:
            args.branch = word
        elif not args.dest:
            args.dest = word
        else:
            raise usage_refusal(
                f"!! verify_start takes a branch and at most one destination; got '{word}' as well."
            )
    return args


def strays_in(directory: Path) -> list[str]:
    """Every `git status --porcelain` line in `directory` but an untracked `*.log`."""
    done = git("-C", str(directory), "status", "--porcelain")
    if done.returncode != 0:
        raise CouldNotLook(f"`git status --porcelain` in {directory} exited {done.returncode}")
    strays = []
    for line in done.stdout.split("\n"):
        if not line:
            continue
        if line.startswith("?? ") and line[3:].endswith(".log"):
            continue
        strays.append(line)
    return strays


def verdict_key_guard(directory: Path, label: str, step: int) -> None:
    """The last step and `--check`'s whole body: nothing untracked but `*.log`, else exit 2."""
    if git("-C", str(directory), "rev-parse", "--git-dir").returncode != 0:
        raise Died(
            UNPROVEN,
            f"step {step} could not be VERIFIED: {label} is not a git checkout: {directory}",
            "There is no working tree to read a verdict key off.",
        )
    strays = strays_in(directory)
    if not strays:
        say(f"clean        `git status --porcelain` in {label} is empty but for ignored files")
        say("             (untracked `*.log` is the one allowance, and it is ignored here anyway)")
        return
    err(f"\n!! STRAY FILES in {directory} — REFUSING to call this checkout ready.")
    err("   The gate keys its verdict on the working tree measured through")
    err("   `git add -A`, so every one of these SHIFTS THE KEY. A green full")
    err("   gate over this tree banks a verdict against a tree nothing will")
    err("   present again, and the next run measures the whole thing over.")
    err("   Only an untracked `*.log` is allowed. These are not:\n")
    for line in strays:
        err(f"     {line}")
    err("\n   Remove them, ignore them, or commit them — deliberately.")
    raise Printed(f"stray files in {directory}")


def check(args: Args) -> int:
    """`--check [<checkout>]`: the verdict-key guard alone, against a checkout that exists."""
    if args.no_loop:
        raise Died(
            NOTHING_TOUCHED,
            "verify_start: --no-loop consults a clone this run makes; --check makes none.",
        )
    directory = args.check_dir
    if not directory:
        directory = git_out("rev-parse", "--show-toplevel")
        if not directory:
            raise Died(
                NOTHING_TOUCHED,
                "no checkout to look at.",
                "You are not standing in a git checkout, and --check was given no path.",
            )
    if not Path(directory).is_dir():
        raise Died(NOTHING_TOUCHED, f"no such directory: {directory}")
    where = Path(os.path.abspath(directory))
    out(f"== verify_start --check · {where}")
    verdict_key_guard(where, "this checkout", STEP_TOTAL)
    out("\n== CLEAN · no stray file shifts this tree's verdict key.")
    return 0


def safe_branch(branch: str) -> str:
    """The branch as a directory name, sanitised the way `db.sh` sanitises a database name."""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    return "".join(c if c in allowed else "-" for c in branch.lower())


def replace_lines(path: Path, matches: re.Pattern[str], line: str) -> None:
    """Every line of `path` that `matches` becomes `line` (the shell's awk rewrite)."""
    lines = path.read_text().splitlines()
    path.write_text("".join(f"{line if matches.match(old) else old}\n" for old in lines))


class VerifyStart:
    """One run: the source, the destination, the step clock, and what each step left."""

    def __init__(self, root: Path, args: Args) -> None:
        self.root = root
        self.args = args
        self.total = STEP_TOTAL + (1 if args.no_loop else 0)
        self.n = 0
        self.step_start = 0.0
        self.run_start = time.monotonic()
        self.dest = Path()
        self.main_sha = ""
        self.clone_head = ""
        self.origin_main = ""
        self.fold_point = ""
        self.union_is_tip = False
        self.template_url = ""
        self.src_ledger: Path | None = None
        self.snapshot: bytes | None = None

    def begin(self, label: str) -> None:
        """`step_begin`: `== step <n>/<total> · <label>`."""
        self.n += 1
        self.step_start = time.monotonic()
        out(f"\n== step {self.n}/{self.total} · {label}")

    def end(self) -> None:
        """`step_end`: `[<t>] step <n> done`."""
        say(f"[{clock_fmt(time.monotonic() - self.step_start)}] step {self.n} done")

    def unproven(self, headline: str, *lines: str) -> Died:
        """Exit 2 for a step that may have acted and could not be proven."""
        return Died(UNPROVEN, f"step {self.n} could not be VERIFIED: {headline}", *lines)

    def act_failed(self, what: str, rc: int) -> Finding:
        """Exit 1: the act ran and came back non-zero."""
        return Finding(
            f"step {self.n} FAILED: {what} exited {rc}", "Its output is above, unfiltered."
        )

    def log1(self, repo: Path, rev: str) -> str:
        """`git log -1 --format='%h  %s' <rev>` in `repo`."""
        return git_out("-C", str(repo), "log", "-1", "--format=%h  %s", rev)

    def run(self) -> int:
        """The six steps (seven under `--no-loop`), then the footer."""
        self.preconditions()
        self.step_clone()
        self.step_union()
        self.step_environment()
        self.step_dependencies()
        self.step_seed()
        self.predict()
        self.begin("verdict key — nothing untracked but *.log, or this clone is not ready")
        verdict_key_guard(self.dest, "the clone", self.n)
        self.end()
        if self.args.no_loop:
            self.step_consult()
        self.footer()
        return 0

    # --- before step 1 --------------------------------------------------------------------------

    def preconditions(self) -> None:
        """The branch, main and the destination, refused before anything is created."""
        root, branch = self.root, self.args.branch
        if not branch:
            raise usage_refusal("!! verify_start needs the rung branch to verify.")
        if git("-C", str(root), "rev-parse", "--git-dir").returncode != 0:
            raise Died(NOTHING_TOUCHED, f"this is not a git checkout: {root}")
        verified = git("-C", str(root), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if verified.returncode != 0:
            raise Died(
                NOTHING_TOUCHED,
                f"no local branch '{branch}' in this repository.",
                "A rung branch is verified from the checkout the PM merges in, and this",
                "one does not have it. Fetch it, or name the branch as this checkout has it.",
            )
        self.main_sha = git_out("-C", str(root), "rev-parse", "--verify", "--quiet", "main")
        if not self.main_sha:
            raise Died(
                NOTHING_TOUCHED,
                "no local branch 'main' in this repository.",
                "The union this script builds is the rung branch merged with local main,",
                "and main does not resolve.",
            )
        dest = self.args.dest
        if not dest:
            tmproot = (os.environ.get("TMPDIR") or "/tmp").rstrip("/")  # noqa: S108 — the TMPDIR fallback the shell rituals use too
            dest = f"{tmproot}/djb-verify/{safe_branch(branch)}"
        if not dest.startswith("/"):
            dest = f"{root}/{dest}"
        self.dest = Path(dest)
        if os.path.lexists(dest):
            if not self.dest.is_dir():
                raise Died(
                    NOTHING_TOUCHED, f"the destination exists and is not a directory: {dest}"
                )
            if any(self.dest.iterdir()):
                raise Died(
                    NOTHING_TOUCHED,
                    f"the destination is not empty: {dest}",
                    "Cloning over it would destroy whatever verification is already there.",
                    "Remove it deliberately, or name another destination.",
                )
        out(f"== verify_start · {root}")
        say(f"branch       {branch}  {self.log1(root, branch)}")
        say(f"main         {self.log1(root, self.main_sha)}")
        say(f"destination  {dest}")

    # --- step 1 ---------------------------------------------------------------------------------

    def step_clone(self) -> None:
        """Step 1: the source refused when dirty but for docs, then `git clone` at the branch."""
        root, dest, branch = self.root, self.dest, self.args.branch
        self.begin("clone — this checkout, at the rung branch, into its own directory")
        strays = strays_in(root)
        if strays and all(self.docs_path(line) for line in strays):
            say(
                f"docs dirt    {len(strays)} path(s) under docs/product/ are dirty here and are"
                " NOT in"
            )
            say("             the clone — a criterion read from an uncommitted plan is not in")
            say("             this clone either. Cloning from HEAD anyway:")
            for line in strays:
                say(f"               {line}")
            strays = []
        if strays:
            err("\n!! this checkout has uncommitted work — REFUSING to clone it.")
            err("   `git clone` copies COMMITTED state only, so the verifier would")
            err("   measure a tree that differs from the one you are looking at, and")
            err("   nothing inside the clone could tell them. Untracked `*.log` files")
            err("   are allowed and none of these are:\n")
            for line in strays:
                err(f"     {line}")
            err("\n   Commit them, stash them, or discard them by hand — deliberately.")
            err(f"   {NOTHING_TOUCHED}")
            raise Printed("the source checkout is dirty")
        common = git_out("-C", str(root), "rev-parse", "--git-common-dir")
        if common:
            self.src_ledger = (Path(common) if common.startswith("/") else root / common) / (
                "djb-gate-verdicts"
            )
            if self.src_ledger.is_file():
                self.snapshot = self.src_ledger.read_bytes()
        rc = passthrough(["git", "clone", "--quiet", "--branch", branch, str(root), str(dest)])
        if rc != 0:
            raise self.act_failed("git clone", rc)
        if not (dest / ".git").is_dir():
            raise self.unproven(
                f"git clone exited 0 and {dest}/.git is not there.",
                "There is no clone for the next three steps to work in.",
            )
        self.clone_head = git_out("-C", str(dest), "rev-parse", "HEAD")
        here = git_out("-C", str(root), "rev-parse", f"refs/heads/{branch}")
        if self.clone_head != here:
            raise self.unproven(
                f"the clone's HEAD is {self.clone_head}, and {branch} here is {here}.",
                "The clone did not land on the branch it was aimed at.",
            )
        say(f"cloned       {dest}")
        say(f"HEAD         {self.log1(dest, 'HEAD')}")
        self.end()

    @staticmethod
    def docs_path(line: str) -> bool:
        """Whether a porcelain line's path (a rename's destination) is under `docs/product/`."""
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        return path.startswith(DOCS_DIRT)

    # --- step 2 ---------------------------------------------------------------------------------

    def step_union(self) -> None:
        """Step 2: local main merged into the branch in the clone; the fold point recorded."""
        dest, branch = str(self.dest), self.args.branch
        self.begin("union merge — local main, merged into the rung branch")
        self.origin_main = git_out(
            "-C", dest, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"
        )
        if not self.origin_main:
            raise self.unproven(
                "the clone carries no origin/main.",
                "There is nothing to merge the rung branch with.",
            )
        if self.origin_main != self.main_sha:
            raise self.unproven(
                f"the clone's origin/main is {self.origin_main}; this checkout's main is"
                f" {self.main_sha}.",
                "The clone did not carry the main this run announced.",
            )
        say(f"origin/main  {self.log1(self.dest, self.origin_main)}")
        if git("-C", dest, "rev-parse", "-q", "--verify", "refs/heads/main").returncode == 0:
            say("main ref     the clone already carries refs/heads/main — left alone")
        else:
            if git("-C", dest, "branch", "main", self.origin_main).returncode != 0:
                raise self.unproven(
                    f"could not create refs/heads/main in the clone at {self.origin_main}.",
                    "Every changed-file derivation in this tree forks from that ref.",
                )
            short = git_out("-C", dest, "rev-parse", "--short", self.origin_main)
            say(f"main ref     refs/heads/main created at {short} (the verified MAIN_SHA)")
        self.fold_point = git_out("-C", dest, "merge-base", self.origin_main, self.clone_head)
        if git("-C", dest, "merge-base", "--is-ancestor", self.origin_main, "HEAD").returncode == 0:
            self.union_is_tip = True
            say("already up to date — the rung branch already contains main's tip")
            say(
                f"union        {git_out('-C', dest, 'rev-parse', 'HEAD')}  (= the branch tip; no"
                " merge commit)"
            )
        else:
            rc = passthrough(
                [
                    "git", "-C", dest,
                    "-c", f"user.name={os.environ.get('GIT_AUTHOR_NAME') or 'verify_start'}",
                    "-c", f"user.email={os.environ.get('GIT_AUTHOR_EMAIL') or EMAIL}",
                    "merge", "--no-edit", "--no-ff", self.origin_main,
                    "-m", f"verify_start: {branch} union main for verification",
                ]
            )  # fmt: skip
            if rc != 0:
                unmerged = git("-C", dest, "diff", "--name-only", "--diff-filter=U").stdout
                raise Finding(
                    "the rung branch and main CONFLICT.",
                    "The union this verification is about cannot be built without a",
                    "human deciding what it means. The unmerged paths:",
                    "\n".join(f"  {p}" for p in unmerged.splitlines()),
                    "The clone is left AT THE CONFLICT, on purpose, so it can be read:",
                    f"  {dest}",
                    "Whether this is the rung's doing, main's, or a PM ordering",
                    "failure is a judgement this script does not make.",
                )
            say(f"union        {git_out('-C', dest, 'rev-parse', 'HEAD')}  (merge commit)")
        for parent, what in (
            (
                self.origin_main,
                "main is still not an ancestor of the clone's HEAD after the merge.",
            ),
            (
                self.clone_head,
                f"the rung branch tip {self.clone_head} is not an ancestor of the clone's HEAD.",
            ),
        ):
            if git("-C", dest, "merge-base", "--is-ancestor", parent, "HEAD").returncode != 0:
                raise self.unproven(
                    what, "The merge reported success over a tree that is not the union."
                )
        say("verified     both parents are ancestors of the union")
        if self.fold_point:
            if git("-C", dest, "update-ref", "refs/djb/base", self.fold_point).returncode != 0:
                raise self.unproven(
                    f"could not record the fold point {self.fold_point} as refs/djb/base in the"
                    " clone.",
                    "A box pushed from this clone would carry no fork point.",
                )
            short = git_out("-C", dest, "rev-parse", "--short", self.fold_point)
            say(f"fork point   refs/djb/base = {short} (the fold point, recorded for the box push)")
        else:
            say(
                "fork point   NOT recorded — the branch and main share no merge-base, so there"
                " is no fold point to carry"
            )
        self.carry_template_remote()
        self.end()

    def carry_template_remote(self) -> None:
        """The source's `template` remote, name and URL, copied into the clone; no fetch."""
        listed = git("-C", str(self.root), "remote")
        if listed.returncode != 0:
            raise self.unproven(
                "could not list this checkout's remotes.",
                "Whether the clone owes a template remote is unknown, and a guess is a base the"
                " census would trust.",
            )
        if "template" in listed.stdout.split("\n"):
            got = git("-C", str(self.root), "remote", "get-url", "template")
            if got.returncode != 0:
                raise self.unproven(
                    "this checkout names a 'template' remote and git would not give its URL.",
                    "A clone given the remote's name without its URL carries a declaration"
                    " nobody can read.",
                )
            self.template_url = got.stdout.strip()
        if self.template_url:
            if (
                git("-C", str(self.dest), "remote", "add", "template", self.template_url).returncode
                != 0
            ):
                raise self.unproven(
                    f"could not add the 'template' remote ({self.template_url}) to the clone.",
                    "The clone's census would say no base is declared while the primary declares"
                    " one.",
                )
            say(
                f"template     remote copied ({self.template_url}) — the census's base derives"
                " from it"
            )
        else:
            say(
                "template     none — this checkout declares no template remote (the template's"
                " own shape, or a drawer declaration)"
            )

    # --- step 3 ---------------------------------------------------------------------------------

    def step_environment(self) -> None:
        """Step 3: `.env` from `.env.example`, the clone's own database name, the identity carry."""
        dest = self.dest
        env_file = dest / ".env"
        self.begin("environment — .env, this clone's own derived database name, the identity carry")
        if not (dest / ".env.example").is_file():
            raise self.unproven(
                "the clone has no .env.example.",
                "There is nothing to derive this clone's environment from.",
            )
        shutil.copyfile(dest / ".env.example", env_file)
        say(".env         created from .env.example")
        if not os.access(dest / "scripts/db.sh", os.R_OK):
            raise self.unproven(
                "the clone has no readable scripts/db.sh.",
                "It is the one seam this script derives a database name through.",
            )
        named = os.environ.get("DATABASE_NAME", "")
        if named:
            say(f"note: DATABASE_NAME={named} is set in this shell and is IGNORED here —")
            say("      the clone derives its own, or two checkouts share one database.")
        self.name_the_shell_base()
        derived = subprocess.run(
            ["bash", "-c", '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"'],
            cwd=dest,
            env={**os.environ, "DATABASE_NAME": ""},
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        if not derived:
            raise self.unproven(
                "the clone's scripts/db.sh derived no DATABASE_NAME.",
                "The one seam this script consumes did not answer.",
            )
        database_line = re.compile(r"^DATABASE_NAME=")
        if any(database_line.match(line) for line in env_file.read_text().splitlines()):
            replace_lines(env_file, database_line, f"DATABASE_NAME={derived}")
        else:
            with env_file.open("a") as sink:
                sink.write(f"DATABASE_NAME={derived}\n")
        say(f"database     {derived}")
        say("             derived by the clone's own scripts/db.sh, not by this script")
        self.carry_identity(env_file)
        out()
        say("NOT SOURCED  every value above was PRINTED. This script never reads that")
        say("             file into its own shell — the header records what that cost a")
        say("             sibling product, and it was three gate runs.")
        self.end()

    def name_the_shell_base(self) -> None:
        """A `DJB_TEMPLATE_BASE` in this shell is named as not carried; nothing is written."""
        typed = os.environ.get("DJB_TEMPLATE_BASE", "")
        if not typed:
            return
        still = (
            "— a census run in this shell still reads the exported value first; "
            "unset it or run the census without it"
        )
        if self.template_url or (self.dest / "scripts/local/template-base").is_file():
            say(
                f"base         DJB_TEMPLATE_BASE={typed} is set in this shell and does NOT reach"
                " the clone —"
            )
            say(
                "             the clone's census reads the declaration this checkout carries"
                f" instead {still}"
            )
        else:
            say(
                f"base         DJB_TEMPLATE_BASE={typed} is set in this shell and does NOT reach"
                " the clone"
                " — a typed override is the person standing there (divergence_census.sh's"
                " precedence 1);"
                " to carry a base, commit the tag's commit sha in scripts/local/template-base or"
                " add the"
                f" template remote {still}"
            )

    def carry_identity(self, env_file: Path) -> None:
        """`ZITADEL_*` lines from the source's `.env` into the clone's, announced by name only."""
        source = self.root / ".env"
        carried: list[str] = []
        empty: list[str] = []
        if source.is_file():
            for line in source.read_text().splitlines():
                if not line or not ZITADEL_LINE.match(line):
                    continue
                key, _, value = line.partition("=")
                if not value:
                    empty.append(key)
                    continue
                mine = re.compile(rf"^{re.escape(key)}=")
                if any(mine.match(old) for old in env_file.read_text().splitlines()):
                    replace_lines(env_file, mine, line)
                else:
                    with env_file.open("a") as sink:
                        sink.write(f"{line}\n")
                carried.append(key)
        if carried:
            say(f"zitadel      carried {len(carried)} key(s) from {source}, BY NAME ONLY:")
            for key in carried:
                say(f"               {key}")
            say("             (values are never printed and never enter this shell; house rule 27)")
        elif empty:
            say(f"zitadel      nothing carried — every ZITADEL_* line in {source} is empty.")
            say("             the clone keeps .env.example's defaults.")
        elif source.is_file():
            say(f"zitadel      nothing carried — no ZITADEL_* line in {source}.")
        else:
            say("zitadel      nothing carried — this checkout has no .env to carry from.")
        if empty and carried:
            say(f"             not carried, empty in {source}:")
            for key in empty:
                say(f"               {key}")

    # --- step 4 ---------------------------------------------------------------------------------

    def step_dependencies(self) -> None:
        """Step 4: `uv sync --frozen` in the clone, proven by the ledger's own fingerprint."""
        dest = self.dest
        self.begin("python dependencies — uv sync --frozen in the clone")
        if self.args.no_sync:
            say("SKIPPED      --no-sync was given: this clone gets no venv.")
            say("             THE SEED BELOW CANNOT HIT. The --loop ledger's environment")
            say("             fingerprint censuses the installed distributions under")
            say("             .venv and refuses an empty census, so no key is derived and")
            say("             every seeded row is dead on arrival — the first --loop in")
            say("             this clone will re-measure the suite in full.")
            say("             Run `uv sync --frozen` in the clone to undo the skip.")
            self.arm_hooks()
            self.end()
            return
        if shutil.which("uv") is None:
            raise self.unproven(
                "no `uv` on PATH.",
                "This repository's interpreter and dependencies are uv's (CLAUDE.md, the",
                "stack), and without them the clone has no environment for the seed",
                "below to be about.",
            )
        rc = passthrough(["uv", "sync", "--frozen"], cwd=dest)
        if rc != 0:
            raise self.unproven(
                f"`uv sync --frozen` in the clone exited {rc}.",
                "Its output is above, unfiltered. The clone has no environment the",
                "loop ledger can fingerprint, so the seed below would write rows",
                "nothing could ever match. Nothing was seeded.",
            )
        if not os.access(dest / "scripts/gate_ledger.sh", os.R_OK):
            raise self.unproven(
                "the clone has no readable scripts/gate_ledger.sh.",
                "It owns the --loop ledger's environment fingerprint, and it is the",
                "one seam this step proves the venv through.",
            )
        fingerprint, why = env_fingerprint(dest)
        if not fingerprint:
            err(
                f"\n!! step {self.n} could not be VERIFIED: the clone's own gate_ledger.sh still"
                " cannot"
            )
            err("   fingerprint this environment after uv sync exited 0.")
            for line in why.splitlines():
                err(f"   {line}")
            err("   A seed written over an environment the ledger cannot read is a set")
            err("   of rows nothing will ever match. Nothing was seeded.")
            raise Printed("no fingerprint after uv sync")
        say("installed    uv sync --frozen (the recipe is rung_start.sh's STEP 2 · VENV;")
        say("             --frozen because uv.lock is tracked and the verdict-key step")
        say("             below refuses a clone this script dirtied)")
        say(f"fingerprint  {fingerprint}")
        say("             derived by the clone's own scripts/gate_ledger.sh — the same")
        say("             function the first --loop will call. The seed below is about")
        say("             THIS environment, and that is the whole point of the step.")
        self.arm_hooks()
        self.end()

    def arm_hooks(self) -> None:
        """The clone's hooks armed after its venv, and the union's `post-merge` run there."""
        dest = self.dest
        if git("-C", str(dest), "config", "core.hooksPath", "scripts/githooks").returncode != 0:
            raise self.unproven(
                f"could not set core.hooksPath in {dest}.",
                "A clone with no hooks vouches for nothing it pushes.",
            )
        say(
            "hooks        core.hooksPath=scripts/githooks (a clone inherits neither the config"
            " nor the hook)"
        )
        hook = dest / "scripts" / "githooks" / "post-merge"
        if self.union_is_tip or not os.access(hook, os.X_OK):
            return
        if self.args.no_sync:
            say("post-merge   NOT RUN — --no-sync: the union merge is measured by the first")
            say("             commit's hook in this clone, once it has a venv")
            return
        rc = passthrough([str(hook), "0"], cwd=dest)
        if rc == 2:
            raise self.unproven(
                "the union's post-merge hook was ENFORCEMENT BROKEN (exit 2) over the venv.",
                "Its output is above, unfiltered. A clone its own hook cannot measure is",
                "never reported ready.",
            )
        if rc != 0:
            raise Finding(
                f"the union's post-merge hook is RED (exit {rc}): --fast fails on the union.",
                "Its output is above, unfiltered.",
            )
        say("post-merge   the union merge measured by its own hook, over this venv")

    # --- step 5 ---------------------------------------------------------------------------------

    def step_seed(self) -> None:
        """Step 5: the source's loop rows into the clone's ledger, re-copied while it moves."""
        dest_ledger = self.dest / ".git" / "djb-gate-verdicts"
        self.begin("loop-verdict seed — the source's banked --loop rows, copied into the clone")
        named = str(self.src_ledger) if self.src_ledger else ""
        counts: tuple[int, int] | None = None
        stable = 0
        snapshot = self.snapshot
        for copy in range(1, RECOPY_BOUND + 1):
            counts = seed(source_loop_rows(self.root), dest_ledger)
            if self.src_ledger is None or snapshot is None or not self.src_ledger.is_file():
                break
            now = self.src_ledger.read_bytes()
            if now == snapshot:
                stable = copy
                break
            if copy == RECOPY_BOUND:
                raise self.unproven(
                    "the SOURCE's ledger changed while it was being copied.",
                    "This step reads the source and writes only into the clone.",
                    f"It moved under each of {RECOPY_BOUND} copies, so no stable copy was taken.",
                )
            say(
                "re-copy      the source's ledger moved while it was copied (a writer beside"
                " this run);"
                f" copy {copy + 1} of {RECOPY_BOUND}"
            )
            snapshot = now
            pause(1)
        if counts is None:
            say(f"ledger not seeded: {named or '<no common git dir>'} holds no loop rows")
            say("             A NAMED ABSENCE, never silence — the clone's first --loop will")
            say("             re-measure, which is correct and is not an error.")
        else:
            seeded, skipped = counts
            Path(f"{dest_ledger}-seed").write_text(f"seeded={seeded} from={named}\n")
            say(
                f"ledger seeded: {seeded} loop rows from {named} "
                f"({skipped} skipped: not a loop row of the one grammar)"
            )
        if stable == 1:
            say("read-only    the source's ledger is byte-identical to before the clone")
        elif stable:
            say(f"read-only    the source's ledger is byte-identical across copy {stable}")
        if not dest_ledger.is_relative_to(self.dest / ".git"):
            raise self.unproven(
                f"the seeded ledger path {dest_ledger} is not inside {self.dest}/.git.",
                "It would be a stray file, and the verdict-key step would refuse the clone this"
                " script just made.",
            )
        say(f"inside .git  {dest_ledger} — invisible to the verdict-key guard below")
        self.end()

    # --- the prediction -------------------------------------------------------------------------

    def predict(self) -> None:
        """Not a step: which side of the seed's rule this clone landed on, the tree half only."""
        dest = self.dest
        dest_ledger = dest / ".git" / "djb-gate-verdicts"
        if not self.args.no_loop:
            out("\n== consult · what the verifier's first `--loop` will do")
        try:
            tree = ledger.measured_tree(dest)
        except (CouldNotLook, ledger.Mismatch, OSError):
            tree = ""
        key = ""
        if tree and dest_ledger.is_file():
            for _, line in ledger.rows(dest_ledger):
                if f" tree={tree} " in f"{line} ":
                    key = line.split()[1]
                    break
        ahead = ""
        if self.fold_point:
            ahead = git_out(
                "-C", str(dest), "rev-list", "--count", f"{self.fold_point}..{self.origin_main}"
            )
        if self.args.no_loop:
            pass
        elif self.args.no_sync:
            say(
                "consult: WILL RUN (--no-sync: this clone has no venv, so the ledger derives no"
                " key)"
            )
        elif not tree:
            say("consult: NOT PREDICTED (this clone's own scripts/gate_ledger.sh could not")
            say("         measure its tree). A named absence: the loop will say, and the")
            say("         clone is no less ready for it.")
        elif self.union_is_tip and key:
            say(f"consult: EXPECTED HIT {key} (union = branch tip; seeded row tree={tree})")
        elif self.union_is_tip:
            say(f"consult: WILL RUN (no seeded row for tree {tree})")
        elif ahead:
            say(
                f"consult: WILL RUN (union differs: {ahead} commit(s) on main since the fold"
                f" {self.fold_point})"
            )
        else:
            say(
                "consult: WILL RUN (union differs; the commits since the fold could not be counted)"
            )
        if not self.args.no_loop:
            say("         a PREDICTION about the TREE half of the key, and only that half:")
            say("         the environment and the scope halves are measured when the loop runs,")
            say("         so a clone whose .env or whose changed-file set differs misses")
            say("         whatever the line above says.")
        say(
            f"fold point   {self.fold_point or 'unknown'} — compare it against the builder's"
            " report's"
        )
        say("             `fold: main@<sha>` line; unequal is a finding, not a re-measure.")

    # --- step 7 ---------------------------------------------------------------------------------

    def step_consult(self) -> None:
        """Step 7 (`--no-loop`): the union looked up by tree; a docs-only delta, one decider."""
        self.begin("consult — the clone's ledger answers for the union; no loop is run")
        try:
            lines = consult(
                self.dest, self.union_is_tip, self.fold_point, self.origin_main, self.clone_head
            )
        except (CouldNotLook, ledger.Mismatch, OSError) as error:
            raise self.unproven(
                f"the clone's tree, its delta or its ledger could not be read ({error}).",
                "A consult that could not look is never a MISS.",
            ) from error
        for line in lines:
            say(line)
        self.end()

    def footer(self) -> None:
        """`== READY`, the total, and the commands from here."""
        total = clock_fmt(time.monotonic() - self.run_start)
        out(f"\n== READY · total {total} · {self.log1(self.dest, 'HEAD')}")
        out(f"   The clone is the union of {self.args.branch} and main, and nothing in it shifts a")
        if self.args.no_sync and self.args.no_loop:
            out(
                "   verdict key. It has NO VENV (--no-sync) and no database yet; --no-loop runs"
                " no --loop; the consult above is the loop cell."
            )
        elif self.args.no_sync:
            out("   verdict key. It has NO VENV (--no-sync) and no database yet, and with no")
            out("   venv the seeded --loop rows cannot hit — the first --loop re-measures.")
        else:
            out("   verdict key. Its python dependencies are installed; it has no database")
            out("   yet — deliberately (header, WHAT IT CANNOT SEE 2).")
        out("   From here:")
        out()
        out(f"     cd {self.dest}")
        if self.args.no_loop:
            out(
                "     # --no-loop: the consult above is the loop cell; read the committed delta,"
                " run no --loop"
            )
        else:
            out("     ./scripts/setup.sh                       # the database and the migrations")
            out('     ./scripts/check.sh --loop > "$PWD/gate-<your-verification>.log" 2>&1')
        out()
        out("   Re-run the guard alone whenever you have written into the tree:")
        out(f"     {self.root}/scripts/verify_start.sh --check {self.dest}")


# invariant: through the shell wrapper until `scope.py` lands with GF-5's cutover (GP G4.3).
def env_fingerprint(dest: Path) -> tuple[str, str]:
    """The clone's loop-ledger environment fingerprint and why not, by its `gate_ledger.sh`."""
    done = subprocess.run(
        ["bash", "-c", ". ./scripts/gate_ledger.sh >/dev/null 2>&1 && loop_env_fingerprint"],
        cwd=dest,
        capture_output=True,
        text=True,
        check=False,
    )
    fingerprint = done.stdout.strip() if done.returncode == 0 else ""
    return fingerprint, done.stderr


def source_loop_rows(root: Path) -> list[str]:
    """The source's loop rows in the one grammar, the retired store's first while legacy lives."""
    try:
        path = ledger.ledger_path(root)
    except (ledger.Refused, ledger.Mismatch):
        return []
    return ledger.loop_rows(path)


# invariant: idempotent — the clone's ledger is rewritten from `rows` whole on every call.
def seed(rows: list[str], dest_ledger: Path) -> tuple[int, int] | None:
    """`rows` into the clone's ledger through `ledger.append`: (seeded, skipped), None for none."""
    if not rows:
        dest_ledger.unlink(missing_ok=True)
        return None
    dest_ledger.write_text("")
    seeded = skipped = 0
    for row in rows:
        parts = row.split()
        if not SEED_ROW.match(row) or len(parts) < 4:
            skipped += 1
            continue
        try:
            ledger.append(parts[2], parts[1], parts[4:], path=dest_ledger, stamp=parts[3])
        except (ledger.Refused, ledger.MalformedRow):
            skipped += 1
            continue
        seeded += 1
    return seeded, skipped


def row_words(row: str) -> str:
    """`key <key> banked <stamp>[ box=<id>]` for a consult's answer."""
    words = row.split()
    boxes = [w[4:] for w in words if w.startswith("box=")]
    return f"key {words[1]} banked {words[3]}" + (f" box={boxes[-1]}" if boxes else "")


def consult(dest: Path, union_is_tip: bool, fold: str, origin_main: str, tip: str) -> list[str]:
    """The `--no-loop` answer: a HIT, a docs-only HIT or a MISS naming why, and the `loop:` cell."""
    dest_ledger = dest / ".git" / "djb-gate-verdicts"
    union = ledger.measured_tree_of(dest, "HEAD")
    row = ledger.loop_tree_row(dest, union, [line for _, line in ledger.rows(dest_ledger)])
    if row:
        return [f"consult: HIT {row_words(row)}", "loop: hit"]
    if not union_is_tip and fold:
        prose = ledger.loop_key_prose(dest, union)
        delta = ledger.docs_only_delta(
            dest, fold, origin_main, None if prose is None else frozenset(prose)
        )
        code = "".join(f" {path}" for kind, path in delta if kind == "code")
        span = f"{fold[:8]}..{origin_main[:8]}"
        if code:
            return [
                f"consult: MISS(code: {span}) — main moved by code after the fold point:{code}",
                f"loop: miss(code: {span})",
            ]
        tip_tree = ledger.measured_tree_of(dest, tip)
        row = ledger.loop_tree_row(dest, tip_tree, [line for _, line in ledger.rows(dest_ledger)])
        if row:
            return [f"consult: HIT (docs-only delta) {row_words(row)}", "loop: docs-only reuse"]
        return [
            f"consult: MISS(no-ledger) — no loop row names tree {union} nor the branch tip's"
            f" {tip_tree}"
            " (main's delta since the fold is docs-only)",
            "loop: miss(no-ledger)",
        ]
    return [f"consult: MISS(no-ledger) — no loop row names tree {union}", "loop: miss(no-ledger)"]


def drop_own_path() -> None:
    """The wrapper's `PYTHONPATH` entry withheld from every child this run starts."""
    entries = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    kept = [e for e in entries if e and os.path.realpath(e) != str(ROOT)]
    if kept:
        os.environ["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        os.environ.pop("PYTHONPATH", None)


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`verify_start <branch> [--no-sync] [--no-loop] [<dest>]` · `--check [<dir>]`: 0 · 1 · 2."""
    drop_own_path()
    try:
        refuse_if_piped()
        args = parse(list(sys.argv[1:] if argv is None else argv))
        if args is None:
            sys.stdout.write(USAGE)
            return 0
        if args.mode == "check":
            return check(args)
        return VerifyStart(root, args).run()
    except Died as died:
        err(f"!! {died.headline}")
        indented(*died.lines)
        if died.trailer:
            indented(died.trailer)
        return 2
    except Finding as finding:
        err(f"RED: {finding.headline}")
        indented(*finding.lines)
        return 1
    except Printed:
        return 2
    except CouldNotLook as cannot:
        err(f"!! COULD NOT LOOK: {cannot}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
