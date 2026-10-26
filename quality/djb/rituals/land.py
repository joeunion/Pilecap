"""The landing ritual: a merged pull request landed on the primary's main in one command."""

# does-not-cover: whether the pull request should have merged — CI and the verifier decide that.
# does-not-cover: whether `ships:` names rows the pull request really closed — the verifier's read.
# does-not-cover: old orphans of other checkouts — the `--force-foreign` drop stays the owner's.

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from quality.could_not_look import CouldNotLook
from quality.djb import ledger
from quality.djb.rituals import merge

ROOT = Path(__file__).resolve().parents[3]
NOTHING_LANDED = "Nothing was merged, reaped, struck or committed."
QUEUE = "docs/product/queue.md"
DETAIL = "docs/product/queue-detail.md"
REPORTS = "docs/product/reports"
DB_ENV = ("DATABASE_NAME", "DATABASE_NAME_SOURCE")
USAGE = """\
Land a merged pull request on the primary's main: merge origin/main, reap the head's
worktree and database, strike and book the report's rows, commit once.

  pm_land.sh <pr>                    the whole landing
  pm_land.sh <pr> --report <path>    ...and a verifier's report copied in beside the PR's own
  pm_land.sh <pr> --ledger-pr        ...then main's docs pushed through pm/ledger-<date>'s PR
  pm_land.sh <pr> --read-main        ...and main_is_read asked (minutes when no loop row is near)

Exit 0 landed (or already landed) · 1 the PR is not merged, a row is refused, or the
branch is not in main · 2 refused before touching, or a step could not act.
"""


@dataclass
class Args:
    """The command line: the pull request, the reports handed over, the ledger PR."""

    pr: int = 0
    reports: list[str] = field(default_factory=list)
    ledger_pr: bool = False
    read_main: bool = False


def parse(argv: Sequence[str]) -> Args | None:
    """`<pr> [--report <path>]... [--ledger-pr]`; None for help; `CouldNotLook` on anything else."""
    args = Args()
    words = list(argv)
    if not words or words[0] in ("-h", "--help"):
        return None
    while words:
        word = words.pop(0)
        if word == "--report" and words:
            args.reports.append(words.pop(0))
        elif word == "--ledger-pr":
            args.ledger_pr = True
        elif word == "--read-main":
            args.read_main = True
        elif word.isdigit() and not args.pr:
            args.pr = int(word)
        else:
            raise CouldNotLook(f"pm_land: unknown or misplaced argument {word!r} — see --help")
    if not args.pr:
        raise CouldNotLook("pm_land: name the pull request's number")
    return args


def step(label: str, argv: Sequence[str], cwd: Path) -> int:
    """One step, its command and exit printed; a sourced `db.sh`'s database name not carried in."""
    merge.out(f"  {label}: {' '.join(argv)}")
    sys.stdout.flush()
    env = {k: v for k, v in os.environ.items() if k not in DB_ENV}
    rc = subprocess.run(list(argv), cwd=cwd, env=env, check=False).returncode
    merge.out(f"  {label}: exit {rc}")
    return rc


def worktree_of(root: Path, branch: str) -> Path | None:
    """The linked worktree `git worktree list --porcelain` names for `branch`, if any."""
    path: Path | None = None
    for line in merge.git_out(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return None if path.resolve() == root.resolve() else path
    return None


class Land:
    """One landing: the pull request read, main merged, the head reaped, the rows written."""

    def __init__(self, root: Path, args: Args) -> None:
        self.root = root
        self.args = args
        self.pr: dict[str, object] = {}
        self.head = ""
        self.merge_sha = ""
        self.worktree: Path | None = None
        self.reports: list[str] = []
        self.copies: list[tuple[Path, Path]] = []
        self.struck: list[str] = []
        self.booked: list[str] = []

    def run(self) -> int:
        """Refuse, merge, reap, strike and book, commit once, print the line; then the ledger PR."""
        self.refuse_before_touching()
        self.merge_main()
        reaped = self.reap()
        self.write_rows()
        landed = self.commit(reaped)
        struck, booked = " ".join(self.struck) or "none", " ".join(self.booked) or "none"
        merge.out(
            f"pm-land: #{self.args.pr} landed at {landed} · struck {struck}"
            f" · booked {booked} · reaped {reaped}"
        )
        return self.ledger_pr() if self.args.ledger_pr else 0

    def refuse_before_touching(self) -> None:
        """The checkout, the branch, the tree, the pull request and the reports: nothing touched."""
        top = merge.git_out(Path.cwd(), "rev-parse", "--show-toplevel")
        if not top or not Path(top).samefile(self.root):
            raise CouldNotLook(
                f"pm_land: run it from the checkout it lives in ({self.root}), not {top}"
            )
        common = merge.git_out(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        own = merge.git_out(self.root, "rev-parse", "--path-format=absolute", "--git-dir")
        if not common or Path(common).resolve() != Path(own).resolve():
            raise CouldNotLook(f"pm_land: {self.root} is a linked worktree; land from the primary")
        branch = merge.git_out(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != "main":
            raise CouldNotLook(
                f"pm_land: the primary is on {branch or 'a detached HEAD'}, not main"
            )
        if merge.git_out(self.root, "status", "--porcelain"):
            raise CouldNotLook(
                f"pm_land: {self.root} has uncommitted changes; commit or stash first"
            )
        self.read_pr()
        if merge.git(self.root, "fetch", "--quiet", "origin").returncode != 0:
            raise CouldNotLook(
                f"pm_land: `git fetch origin` failed in {self.root}. {NOTHING_LANDED}"
            )
        ok = merge.git(self.root, "merge-base", "--is-ancestor", self.merge_sha, "origin/main")
        if ok.returncode != 0:
            raise CouldNotLook(
                f"pm_land: #{self.args.pr}'s merge {self.merge_sha[:8]} is not on origin/main after"
                f" the fetch. {NOTHING_LANDED}"
            )
        self.worktree = worktree_of(self.root, self.head)
        if self.worktree is not None and merge.git_out(self.worktree, "status", "--porcelain"):
            raise CouldNotLook(
                f"pm_land: the head's worktree {self.worktree} has uncommitted changes; its"
                " builder's work is not all in the pull request"
            )
        self.read_reports()

    def read_pr(self) -> None:
        """`gh pr view`: exit 2 when the forge will not answer, 1 when the PR is not merged."""
        fields = "state,mergeCommit,headRefName,mergedAt,title,mergeable"
        with tempfile.TemporaryDirectory(prefix="pm-land.") as sink:
            rc, said = ledger._gh(
                self.root, Path(sink), "pr-view", "pr", "view", str(self.args.pr), "--json", fields
            )
            why = (Path(sink) / "pr-view.err").read_text().strip() if rc else ""
        if rc != 0:
            raise CouldNotLook(f"pm_land: `gh pr view {self.args.pr}` refused (exit {rc}): {why}")
        try:
            self.pr = json.loads(said)
        except json.JSONDecodeError as error:
            raise CouldNotLook(f"pm_land: `gh pr view` answered no JSON: {error}") from error
        state = str(self.pr.get("state", ""))
        if state != "MERGED":
            merge.err(
                f"!! pm_land: #{self.args.pr} is {state or 'in no state'}, not MERGED"
                f" (mergeable: {self.pr.get('mergeable', '?')})."
            )
            merge.err(f"   {NOTHING_LANDED}")
            raise merge.Exited(1)
        commit = self.pr.get("mergeCommit")
        self.merge_sha = str(commit.get("oid", "")) if isinstance(commit, dict) else ""
        self.head = str(self.pr.get("headRefName", ""))
        if not self.merge_sha or not self.head:
            raise CouldNotLook(f"pm_land: #{self.args.pr} answered no merge commit or head branch")

    def read_reports(self) -> None:
        """The reports to read rows from: the merge's own, then each one handed over."""
        own: list[str] = []
        listed = merge.git_out(
            self.root, "diff", "--name-only", "--diff-filter=AM",
            f"{self.merge_sha}^1", self.merge_sha, "--", REPORTS,
        )  # fmt: skip
        own = [p for p in listed.splitlines() if p.endswith(".md")]
        self.reports = list(own)
        for given in self.args.reports:
            source = Path(given).resolve()
            if not source.is_file():
                raise CouldNotLook(f"pm_land: --report {given} is not a file")
            if source.is_relative_to(self.root.resolve()):
                self.reports.append(str(source.relative_to(self.root.resolve())))
                continue
            if not own:
                raise CouldNotLook(
                    f"pm_land: --report {given} is outside the tree and #{self.args.pr} carries no"
                    " report of its own to file it beside"
                )
            target = Path(own[0]).parent / source.name
            self.copies.append((source, target))
            self.reports.append(str(target))

    def merge_main(self) -> None:
        """`git merge --no-ff origin/main` onto the fetch; the range and main's read printed."""
        before = merge.git_out(self.root, "rev-parse", "HEAD")
        if merge.git(self.root, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode:
            done = merge.git(self.root, "merge", "--no-ff", "--no-edit", "origin/main")
            if done.returncode != 0:
                merge.git(self.root, "merge", "--abort")
                raise CouldNotLook(
                    f"pm_land: `git merge --no-ff origin/main` refused and was aborted:"
                    f" {(done.stdout + done.stderr).strip().splitlines()[-1:]}"
                )
        after = merge.git_out(self.root, "rev-parse", "HEAD")
        merge.out(f"main: {before[:8]}..{after[:8]}" + ("" if before != after else " (unchanged)"))
        if not self.args.read_main:
            merge.out(
                "main_is_read: not asked — CI measured the merge; --read-main walks the ledger"
            )
            return
        try:
            read = merge.main_is_read(self.root, after)
        except (CouldNotLook, ledger.Refused) as error:
            merge.out(f"main_is_read: could not look — {error}")
            return
        detail = {
            "read": f"loop row {read.key} at {read.at}",
            "docs-only": f"docs-only delta from {read.origin[:8]}, {read.count} paths",
        }.get(
            read.word,
            f"from {read.origin[:8] or '-'}: {read.paths or f'no row within {read.depth}'}",
        )
        merge.out(f"main_is_read: {read.word} — tree {read.tree[:8]} ({detail})")

    def reap(self) -> str:
        """The head's worktree and database in the no-orphan order; its name, or `none`."""
        if self.worktree is None:
            merge.out("reap: none (no worktree)")
        else:
            wt = self.worktree
            merge.out(f"reap: {wt}")
            sweep = ["./scripts/db_sweep.sh", "--sweep", "--hot-path"]
            drop = 'source scripts/db.sh && db_drop "$(db_name)"'
            for label, argv, cwd in (
                ("(a) inside sweep", sweep, wt),
                ("(b) inside db_drop", ["bash", "-c", drop], wt),
                ("(c) worktree remove", ["git", "worktree", "remove", str(wt)], self.root),
            ):  # fmt: skip
                if step(label, argv, cwd) != 0:
                    raise CouldNotLook(
                        f"pm_land: reap step {label} failed — run it by hand: {' '.join(argv)}"
                    )
        self.delete_branch()
        if step(
            "(e) worktree prune", ["git", "-C", str(self.root), "worktree", "prune"], self.root
        ):
            raise CouldNotLook("pm_land: `git worktree prune` failed")
        return self.worktree.name if self.worktree is not None else "none"

    def delete_branch(self) -> None:
        """`git branch -d` once the tip is in main; exit 1 naming an unmerged tip, never `-D`."""
        tip = merge.git_out(
            self.root, "rev-parse", "--verify", "--quiet", f"refs/heads/{self.head}"
        )
        if not tip:
            merge.out(f"  (d) branch: none ({self.head} is not a local branch)")
            return
        if merge.git(self.root, "merge-base", "--is-ancestor", tip, "HEAD").returncode != 0:
            merge.err(
                f"!! pm_land: {self.head}'s tip {tip[:8]} is NOT in main — the branch is kept."
            )
            raise merge.Exited(1)
        argv = ["git", "-C", str(self.root), "branch", "-d", self.head]
        if step("(d) branch delete", argv, self.root) != 0:
            raise CouldNotLook(f"pm_land: run it by hand: {' '.join(argv)}")

    def write_rows(self) -> None:
        """Each report's `## Rows`: ships struck with the merge and the report, books booked."""
        spec = importlib.util.spec_from_file_location(
            "queue_index", ROOT / "scripts/queue_index.py"
        )
        if spec is None or spec.loader is None:
            raise CouldNotLook("pm_land: scripts/queue_index.py would not load")
        qi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qi)
        for source, target in self.copies:
            (self.root / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, self.root / target)
        files = ["--files", str(self.root / QUEUE), str(self.root / DETAIL)]
        for report in self.reports:
            try:
                rows = qi.report_rows(str(self.root / report))
            except CouldNotLook as refusal:
                raise CouldNotLook(f"pm_land: {refusal}") from refusal
            if rows is None:
                merge.out(f"rows: {report} carries no `{qi.REPORT_ROWS}` block — nothing from it")
                continue
            before = self.ids(qi, open_only=True)
            if rows.ships:
                argv = ["--strike", *rows.ships, "--sha", self.merge_sha, "--artifact", report]
                self.queue(qi, [*argv, *files])
                self.struck += [i for i in rows.ships if i in before]
            known = set(self.ids(qi))
            self.queue(qi, ["--book", report, *files])
            self.booked += [i for i in self.ids(qi) if i not in known]

    def ids(self, qi: ModuleType, *, open_only: bool = False) -> list[str]:
        """The ids the record's anchors carry, or only those whose rows are open."""
        _detail, rows = qi.read_record(str(self.root / DETAIL))
        return [str(r.ident) for r in rows if not open_only or r.status == "open"]

    def queue(self, qi: ModuleType, argv: list[str]) -> None:
        """One `queue_index.py` write: exit 1 and 2 are this ritual's too."""
        try:
            rc = int(qi.main(argv))
        except CouldNotLook as refusal:
            raise CouldNotLook(f"pm_land: queue_index {argv[0]} refused: {refusal}") from refusal
        if rc == 1:
            raise merge.Exited(1)
        if rc != 0:
            raise CouldNotLook(f"pm_land: queue_index {argv[0]} exited {rc}")

    def commit(self, reaped: str) -> str:
        """ONE pathspec commit of the queue and the copied reports; main's sha8 either way."""
        paths = [QUEUE, DETAIL, *(str(t) for _, t in self.copies)]
        if self.copies:
            merge.git(self.root, "add", "--", *(str(t) for _, t in self.copies))
        if not merge.git_out(self.root, "status", "--porcelain", "--", *paths):
            merge.out("land: nothing to commit")
            return merge.git_out(self.root, "rev-parse", "--short=8", "HEAD")
        title = str(self.pr.get("title", ""))
        message = (
            f"land: #{self.args.pr} {title} — {len(self.struck)} struck, {len(self.booked)} booked,"
            f" {reaped} reaped [docs-only]"
        )
        if merge.passthrough(self.root, "commit", "-q", "-m", message, "--", *paths) != 0:
            raise CouldNotLook("pm_land: the landing commit was refused — see above")
        return merge.git_out(self.root, "rev-parse", "--short=8", "HEAD")

    def ledger_pr(self) -> int:
        """Main's docs delta merged into `pm/ledger-<date>` and its `pm_push.sh --pr` run there."""
        branch = f"pm/ledger-{time.strftime('%Y-%m-%d')}"
        wt = worktree_of(self.root, branch)
        if wt is None:
            wt = self.root / ".claude" / "worktrees" / branch.replace("/", "-")
            exists = merge.git_out(self.root, "rev-parse", "--verify", "--quiet", branch)
            add = [str(wt), branch] if exists else ["-b", branch, str(wt), "origin/main"]
            if step(
                "ledger worktree", ["git", "-C", str(self.root), "worktree", "add", *add], self.root
            ):
                raise CouldNotLook(f"pm_land: could not make the ledger worktree {wt}")
        if not (wt / ".venv" / "bin" / "python").exists() and step(
            "ledger venv", ["uv", "sync"], wt
        ):
            raise CouldNotLook(f"pm_land: `uv sync` failed in {wt}")
        if step("ledger merge", ["git", "-C", str(wt), "merge", "--no-edit", "main"], wt) != 0:
            raise CouldNotLook(f"pm_land: main would not merge into {branch} at {wt}")
        push = "source scripts/db.sh && exec ./scripts/pm_push.sh --pr"
        return step("ledger pr", ["bash", "-c", push], wt)


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`land <pr> [--report <path>]... [--ledger-pr]`: 0 · 1 · 2."""
    try:
        if not os.environ.get("CI") and stat.S_ISFIFO(os.fstat(1).st_mode):
            raise CouldNotLook("pm_land refuses pipes — run it bare or redirect to a file")
        args = parse(list(sys.argv[1:] if argv is None else argv))
        if args is None:
            sys.stdout.write(USAGE)
            return 0
        return Land(root, args).run()
    except merge.Died as died:
        merge.err(f"!! {died.headline}")
        merge.indented(*died.lines)
        return 2
    except merge.Exited as exited:
        return exited.rc
    except CouldNotLook as cannot:
        merge.err(f"!! {cannot}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
