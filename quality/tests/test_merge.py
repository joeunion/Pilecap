"""`python -m quality.djb.rituals.merge` driven over scenario repositories, a stub gate and fold."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from quality.djb.rituals import merge, publish
from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.env_strip import STRIPPED
from quality.tests.fixtures.tripwire import fingerprint, unexcused

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/merge.py",
    "quality/djb/ledger.py",
    "quality/could_not_look.py",
    "quality/djb/env.py",
    "apps/core/roads.py",
    ".gitattributes",
    "CHANGELOG.md",
    "scripts/docs_legs.sh",
    "scripts/gate_refuse.sh",
    "scripts/gate_ledger.sh",
    "scripts/db.sh",
    "scripts/pm_fold.sh",
    "scripts/check.sh",
    "scripts/pm_merge.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.merge import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
REAL = "import sys; from quality.djb.rituals.merge import main; sys.exit(main(sys.argv[1:]))"
LOOP_KEY_E = "loop-v1:" + "e" * 64
LOOP_KEY_F = "loop-v1:" + "f" * 64
CL_APPEND_BASE = """# Changelog

## [Unreleased]

- the bullet the base commit shipped

## [9.9.8]

- a shipped section, and it is history
"""
CL_APPEND_A = CL_APPEND_BASE.replace(
    "shipped\n\n## [9.9.8]", "shipped\n- lane A appended this bullet\n\n## [9.9.8]"
)
CL_APPEND_B = CL_APPEND_BASE.replace(
    "shipped\n\n## [9.9.8]", "shipped\n- lane B appended this bullet\n\n## [9.9.8]"
)
CL_SPLIT_BASE = """# Changelog

## [Unreleased]

- the bullet, naming `./scripts/gate.sh
  --fast` and then prose

## [9.9.8]

- a shipped section, and it is history
"""
CL_SPLIT_A = CL_SPLIT_BASE.replace("- the bullet, naming", "- lane A rewrote this line, naming")
CL_SPLIT_B = CL_SPLIT_BASE.replace("- the bullet, naming", "- lane B rewrote this line, naming")


@dataclass
class Run:
    """One ritual run: its exit, its combined output, and what the stubs recorded."""

    rc: int
    text: str
    gate: str
    fold: str

    def says(self, *needles: str) -> None:
        """Every needle is in the output."""
        for needle in needles:
            assert needle in self.text, f"does not say {needle!r}:\n{self.text}"

    def says_not(self, *needles: str) -> None:
        """No needle is in the output."""
        for needle in needles:
            assert needle not in self.text, f"says {needle!r} and must not:\n{self.text}"

    def before(self, first: str, then: str) -> None:
        """`first` is printed before `then`."""
        self.says(first, then)
        assert self.text.index(first) < self.text.index(then), self.text


@dataclass
class World:
    """A scenario repository: main, safe, clash and stale branches, a stub gate and a stub fold."""

    scratch: Path
    repo: Path = field(init=False)
    runs: int = 0

    def __post_init__(self) -> None:
        self.repo = self.scratch / "repo"
        self.repo.mkdir()
        for step in (
            ["init", "-q"],
            ["symbolic-ref", "HEAD", "refs/heads/main"],
            ["config", "user.email", "drive@example.invalid"],
            ["config", "user.name", "merge drive"],
            ["config", "commit.gpgsign", "false"],
        ):
            self.git(*step)
        scripts = self.repo / "scripts"
        scripts.mkdir()
        self.write_exe(
            "scripts/check.sh",
            "#!/usr/bin/env bash\n"
            'echo "STUB GATE ran with: $*"\n'
            f'printf \'%s\\n\' "$*" >>"{self.gate_log}"\n'
            'exit "${DJB_DRIVE_GATE_RC:-0}"\n',
        )
        self.write_exe(
            "scripts/pm_fold.sh",
            "#!/usr/bin/env bash\n"
            'echo "STUB FOLD ran"\n'
            f"printf 'ran\\n' >>\"{self.fold_log}\"\n"
            'echo "pm_fold: NOTHING TO FOLD. No commit was made."\n'
            "exit 0\n",
        )
        self.gate_log.write_text("")
        self.fold_log.write_text("")
        (self.repo / "shared.txt").write_text("one\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("branch", "stale")
        self.commit_on("safe", "main", "safe.txt", "safe\n", "safe change")
        self.commit_on("clash", "main", "shared.txt", "clash\n", "clash change")
        self.git("checkout", "-q", "main")
        self.commit("shared.txt", "main\n", "only on main")

    @property
    def gate_log(self) -> Path:
        return self.scratch / "gate.log"

    @property
    def fold_log(self) -> Path:
        return self.scratch / "fold.log"

    @property
    def ledger(self) -> Path:
        return self.repo / ".git" / "djb-gate-verdicts"

    def git(self, *argv: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.repo), *argv], capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
        return done.stdout.strip()

    def git_rc(self, *argv: str) -> int:
        return subprocess.run(
            ["git", "-C", str(self.repo), *argv], capture_output=True, check=False
        ).returncode

    def write_exe(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def commit(self, rel: str, text: str, subject: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.git("add", rel)
        self.git("commit", "-q", "-m", subject)

    def commit_on(self, branch: str, start: str, rel: str, text: str, subject: str) -> None:
        self.git("checkout", "-q", "-b", branch, start)
        self.commit(rel, text, subject)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def parents(self) -> int:
        return len(self.git("log", "-1", "--format=%P").split())

    def tree(self, rev: str = "HEAD") -> str:
        return self.git("rev-parse", f"{rev}^{{tree}}")

    def row(self, line: str) -> None:
        with self.ledger.open("a") as sink:
            sink.write(f"{line}\n")

    def main_read(self) -> None:
        """Main as a loop read it: a green loop row naming HEAD's tree."""
        self.row(
            f"v1 {LOOP_KEY_E} loop 2026-10-02T09:00:00Z caller=main-loop scope=mode=fast"
            f" passes=1 tree={self.tree()} env=x"
        )

    def run(
        self, *argv: str, read: bool = True, env: dict[str, str] | None = None, entry: str = ENTRY
    ) -> Run:
        """The ritual over `argv` from the repository, main read first unless `read=False`."""
        if read:
            self.main_read()
        return self.shell([sys.executable, "-c", entry, *argv], env=env)

    def piped(self, argv: str, env: dict[str, str] | None = None) -> Run:
        """The ritual inside `bash -c`, its argv already shell words."""
        self.main_read()
        line = f'"{sys.executable}" -c "$ENTRY" {argv}'
        return self.shell(["bash", "-c", line], env={**(env or {}), "ENTRY": ENTRY})

    def shell(self, argv: list[str], env: dict[str, str] | None = None) -> Run:
        self.runs += 1
        merged = {
            **os.environ,
            "DJB_GATE_LEDGER": str(self.ledger),
            "PYTHONPATH": str(ROOT),
            **(env or {}),
        }
        captured: Captured = run_to(self.scratch / f"run-{self.runs}.out", argv, self.repo, merged)
        text = captured.path.read_text(errors="replace")
        return Run(captured.rc, text, self.gate_log.read_text(), self.fold_log.read_text())

    def fold_clean(self, branch: str) -> None:
        self.git("checkout", "-q", branch)
        self.git("merge", "-q", "--no-edit", "main")
        self.git("checkout", "-q", "main")

    def fold_by_hand(self, branch: str, text: str) -> None:
        self.git("checkout", "-q", branch)
        self.git_rc("merge", "-q", "--no-edit", "main")
        (self.repo / "shared.txt").write_text(f"{text}\n")
        self.git("add", "shared.txt")
        self.git("commit", "-q", "--no-edit")
        self.git("checkout", "-q", "main")


@pytest.fixture
def world(scratch: Path) -> Callable[[], World]:
    """`world()` builds the next scenario repository under its own directory."""
    made = 0

    def build() -> World:
        nonlocal made
        made += 1
        here = scratch / f"world-{made}"
        here.mkdir()
        return World(here)

    return build


# --- the refusals ---------------------------------------------------------------------------------


def test_no_branch_named_is_refused(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.run()
    assert run.rc == 2, run.text
    run.says("no branch named")
    assert w.head() == before


def test_an_unknown_flag_is_refused(world: Callable[[], World]) -> None:
    run = world().run("--merge-it", "safe")
    assert run.rc == 2, run.text
    run.says("unknown flag")


def test_two_branches_are_refused(world: Callable[[], World]) -> None:
    run = world().run("safe", "clash")
    assert run.rc == 2, run.text
    run.says("one branch at most")


def test_a_nonexistent_branch_is_a_loud_refusal(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.run("worktree-agent-typo-safe")
    assert run.rc == 2, run.text
    run.says("names no commit", "Nothing was merged")
    assert w.head() == before
    assert run.gate == ""


def test_an_already_merged_branch_is_refused(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.run("stale")
    assert run.rc == 2, run.text
    run.says("ALREADY an ancestor", "Already up to date")
    run.says_not("Proof of merge")
    assert w.head() == before


def test_a_dirty_tree_is_refused(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    with (w.repo / "shared.txt").open("a") as sink:
        sink.write("an unsaved edit\n")
    run = w.run("safe")
    assert run.rc == 2, run.text
    run.says("uncommitted changes")
    assert w.head() == before


def test_a_piped_stdout_is_refused(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.piped("safe | cat; exit ${PIPESTATUS[0]}")
    assert run.rc == 2, run.text
    run.says("refuses pipes")
    assert w.head() == before


def test_the_ci_exemption_lets_a_piped_run_through(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.piped("safe | cat; exit ${PIPESTATUS[0]}", env={"CI": "true", "GITHUB_ACTIONS": "true"})
    assert run.rc == 0, run.text
    run.says_not("refuses pipes")
    run.says("MERGED. Proof of merge", "STUB GATE ran with: --fast")
    assert w.head() != before


def test_the_pipe_guard_reads_only_what_the_preamble_strips() -> None:
    tree = ast.parse(inspect.getsource(merge.refuse_if_piped))
    read = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("get", "getenv")
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert read, "the guard reads no environment variable — the exemption is gone"
    assert read <= set(STRIPPED), f"the guard reads {read - set(STRIPPED)}, which env_strip keeps"


def test_a_peers_merge_into_main_does_not_convict_a_drive(
    scratch_repo: Callable[..., Path], scratch: Path
) -> None:
    repo = scratch_repo()
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "-b", "worktree-agent-n454"], check=True
    )
    peer = scratch / "peer-primary"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(peer), "main"], check=True)
    before = fingerprint(repo)
    new = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "peer merge"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/heads/main", new], check=True)
    assert unexcused(repo, before, fingerprint(repo)) == []


def test_the_escape_itself_is_still_caught(scratch_repo: Callable[..., Path]) -> None:
    repo = scratch_repo()
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "-b", "worktree-agent-n454"], check=True
    )
    before = fingerprint(repo)
    for argv in (
        ["checkout", "-q", "main"],
        ["commit", "-q", "--allow-empty", "-m", "only on main"],
        ["branch", "clash"],
        ["config", "core.bare", "true"],
    ):
        subprocess.run(["git", "-C", str(repo), *argv], check=True)
    found = unexcused(repo, before, fingerprint(repo))
    assert any(d.startswith("HEAD:") for d in found), found
    assert any(d.startswith("refs/heads/clash:") for d in found), found
    assert any(d.startswith("core.bare:") for d in found), found


def test_the_real_script_refuses_a_foreign_checkout(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.run("safe", entry=REAL)
    assert run.rc == 2, run.text
    run.says("not the checkout this script lives in")
    assert w.head() == before


# --- the conflict and the clean merge ------------------------------------------------------------


def test_a_conflicting_merge_surfaces_the_conflict(world: Callable[[], World]) -> None:
    w = world()
    run = w.run("clash")
    assert run.rc == 1, run.text
    run.says("THE MERGE FAILED", "WORKING TREE: MID-MERGE", "shared.txt", "merge --abort")
    run.says_not("Proof of merge")
    assert w.git_rc("rev-parse", "--verify", "--quiet", "MERGE_HEAD") == 0
    assert run.gate == ""
    w.git("merge", "--abort")


def test_a_clean_merge_prints_the_proof_line(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.run("safe")
    assert run.rc == 0, run.text
    run.says("MERGED. Proof of merge", w.git("rev-parse", "--short", "HEAD"))
    assert w.head() != before
    assert w.parents() == 2
    assert run.gate == "--fast\n"


# --- the merge's two consults ---------------------------------------------------------------------


def consult_world(world: Callable[[], World]) -> World:
    w = world()
    w.commit(
        "scripts/tests/test_zzz_merged.sh",
        "#!/usr/bin/env bash\n# drives: safe.txt\nexit 0\n",
        "a drive",
    )
    return w


def test_the_merge_names_the_loop_row_and_the_drives_that_have_not_run(
    world: Callable[[], World],
) -> None:
    key, other = "loop-v1:" + "a" * 64, "0" * 40
    w = consult_world(world)
    tree = w.tree("safe")
    w.row(
        f"v1 {key} loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1"
        f" tree={tree} env=x box=i-zzzbox"
    )
    w.row(
        f"v1 drive-v1:zzz1 drive 2026-09-27T11:00:00Z zzz_merged exit=1 took=1 tree={tree} parts=-"
    )
    w.row(
        f"v1 drive-v1:zzz2 drive 2026-09-27T11:05:00Z zzz_merged exit=0 took=1 tree={other} parts=-"
    )
    run = w.run("safe")
    assert run.rc == 0, run.text
    run.says(
        f"loop consult: HIT — tree {tree} (safe's head) key {key} box=i-zzzbox banked"
        " 2026-09-27T10:00:00Z",
        f"drives: 1 declare this merge's files — ran green on the branch head's tree ({tree}):"
        " none; red or absent on it: zzz_merged; not recorded by any loop: none",
        "!! drives red or absent on these bytes that a loop records: zzz_merged — a finding",
    )
    assert run.gate == "--fast\n"

    w = consult_world(world)
    tree = w.tree("safe")
    w.row(
        f"v1 {key} loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1"
        f" tree={tree} env=x box=i-zzzbox"
    )
    w.row(
        f"v1 drive-v1:zzz drive 2026-09-27T09:59:00Z zzz_merged exit=0 took=1 tree={tree} parts=-"
    )
    run = w.run("safe")
    assert run.rc == 0, run.text
    run.says(
        f"drives: 1 declare this merge's files — ran green on the branch head's tree ({tree}):"
        " zzz_merged; red or absent on it: none; not recorded by any loop: none"
    )
    run.says_not("!! drives red or absent")

    w = consult_world(world)
    tree = w.tree("safe")
    run = w.run("safe")
    assert run.rc == 0, run.text
    run.says(
        f"loop consult: MISS — no loop row names tree {tree} (safe's head); the verifier's"
        " consult re-measures",
        f"drives: 1 declare this merge's files — ran green on the branch head's tree ({tree}):"
        " none; red or absent on it: none; not recorded by any loop: zzz_merged",
        "not recorded by any loop (1): no --loop runs them, so they meet these files first at"
        " the bank — information, not a finding",
    )
    run.says_not("!! drives red or absent")


def test_the_merge_splits_unrecorded_drives_from_red_or_absent_ones(
    world: Callable[[], World],
) -> None:
    loopt, bankt, key = "1" * 40, "2" * 40, "loop-v1:" + "b" * 64
    for at, red in ((loopt, True), (bankt, False)):
        w = consult_world(world)
        tree = w.tree("safe")
        w.row(
            f"v1 {key} loop 2026-09-27T08:00:00Z caller=unstated scope=mode=fast passes=1"
            f" tree={loopt} env=x"
        )
        w.row(
            f"v1 drive-v1:zzz drive 2026-09-27T08:00:00Z zzz_merged exit=0 took=1 tree={at} parts=-"
        )
        run = w.run("safe")
        assert run.rc == 0, run.text
        if red:
            run.says(
                f"drives: 1 declare this merge's files — ran green on the branch head's tree"
                f" ({tree}): none; red or absent on it: zzz_merged; not recorded by any loop: none",
                "!! drives red or absent on these bytes that a loop records: zzz_merged — a"
                " finding; run them on a box before the bank",
            )
            run.says_not("information, not a finding")
        else:
            run.says(
                f"drives: 1 declare this merge's files — ran green on the branch head's tree"
                f" ({tree}): none; red or absent on it: none; not recorded by any loop: zzz_merged",
                "not recorded by any loop (1): no --loop runs them, so they meet these files"
                " first at the bank — information, not a finding",
            )
            run.says_not("!! drives red or absent")


# --- the CHANGELOG's merge driver (the subject is `.gitattributes`) -------------------------------


def changelog_world(world: Callable[[], World], attrs: bool, base: str, a: str, b: str) -> World:
    w = world()
    if attrs:
        (w.repo / ".gitattributes").write_text((ROOT / ".gitattributes").read_text())
        w.git("add", ".gitattributes")
    (w.repo / "CHANGELOG.md").write_text(base)
    w.git("add", "CHANGELOG.md")
    w.git("commit", "-q", "-m", "the changelog, and whatever merges it")
    w.commit_on("lane-a", "main", "CHANGELOG.md", a, "lane A: a bullet under [Unreleased]")
    w.git("checkout", "-q", "main")
    w.commit("CHANGELOG.md", b, "lane B: a bullet under [Unreleased]")
    return w


def test_two_appends_to_the_changelog_merge_clean(world: Callable[[], World]) -> None:
    w = changelog_world(world, True, CL_APPEND_BASE, CL_APPEND_A, CL_APPEND_B)
    assert w.git("check-attr", "merge", "CHANGELOG.md") == "CHANGELOG.md: merge: union"
    run = w.run("lane-a")
    assert run.rc == 0, run.text
    run.says("MERGED. Proof of merge")
    run.says_not("WORKING TREE: MID-MERGE")
    assert w.git_rc("rev-parse", "--verify", "--quiet", "MERGE_HEAD") != 0
    text = (w.repo / "CHANGELOG.md").read_text()
    assert not any(line.startswith(("<<<<<<<", ">>>>>>>", "=======")) for line in text.splitlines())
    assert text.count("lane A appended this bullet") == 1
    assert text.count("lane B appended this bullet") == 1
    assert text.index("lane B appended") < text.index("lane A appended")
    assert text.count("## [Unreleased]") == 1
    assert text.count("the bullet the base commit shipped") == 1


def test_without_the_attribute_the_same_two_appends_conflict(world: Callable[[], World]) -> None:
    w = changelog_world(world, False, CL_APPEND_BASE, CL_APPEND_A, CL_APPEND_B)
    assert w.git("check-attr", "merge", "CHANGELOG.md") == "CHANGELOG.md: merge: unspecified"
    run = w.run("lane-a")
    assert run.rc == 1, run.text
    run.says("THE MERGE FAILED", "WORKING TREE: MID-MERGE", "CHANGELOG.md")
    assert w.git("status", "--porcelain", "--", "CHANGELOG.md") == "UU CHANGELOG.md"
    assert run.gate == ""
    w.git("merge", "--abort")


def test_the_union_is_a_merge_driver_and_not_a_judge(world: Callable[[], World]) -> None:
    w = changelog_world(world, True, CL_SPLIT_BASE, CL_SPLIT_A, CL_SPLIT_B)
    run = w.run("lane-a")
    assert run.rc == 0, run.text
    run.says("MERGED. Proof of merge")
    text = (w.repo / "CHANGELOG.md").read_text()
    assert text.count("rewrote this line, naming") == 2
    assert text.count("--fast` and then prose") == 1
    assert text.count("`") % 2 == 1
    with pytest.raises(publish.Refused) as flags:
        publish.changelog_flags(w.repo, "Unreleased")
    assert "ODD number of" in "\n".join(flags.value.lines)


# --- the tier, the fold, the message --------------------------------------------------------------


def test_bank_runs_the_full_gate_instead_of_fast(world: Callable[[], World]) -> None:
    w = world()
    run = w.run("safe", "--bank")
    assert run.rc == 0, run.text
    run.says("MERGED. Proof of merge", "STUB GATE ran with: --bank")
    run.says("THE FULL GATE, asked for with --bank")
    run.says_not("NOT run here: pytest")
    assert run.gate == "--bank\n"
    assert w.parents() == 2
    run.before("STUB FOLD ran", "STUB GATE ran with: --bank")
    assert run.fold == "ran\n"


def test_the_default_tier_is_still_fast(world: Callable[[], World]) -> None:
    run = world().run("safe")
    assert run.rc == 0, run.text
    run.says("STUB GATE ran with: --fast")
    run.says_not("STUB GATE ran with: --bank", "STUB FOLD ran")
    assert run.gate == "--fast\n"
    assert run.fold == ""


def test_bank_with_no_fold_is_refused(world: Callable[[], World]) -> None:
    w = world()
    w.git("rm", "-q", "-f", "scripts/pm_fold.sh")
    w.git("commit", "-q", "-m", "no fold in this checkout")
    before = w.head()
    run = w.run("safe", "--bank")
    assert run.rc == 2, run.text
    run.says("no executable fold", "THE MERGE ABOVE IS ALREADY MADE")
    run.says_not("STUB GATE ran with: --bank")
    assert run.gate == ""
    assert w.parents() == 2
    assert w.head() != before


def test_a_merge_message_file_is_used(world: Callable[[], World], scratch: Path) -> None:
    w = world()
    message = scratch / "msg.txt"
    message.write_text("Merge: the message from a file\n")
    run = w.run("safe", "-m", str(message))
    assert run.rc == 0, run.text
    assert w.git("log", "-1", "--format=%s") == "Merge: the message from a file"


def test_a_merge_message_on_stdin_is_used(world: Callable[[], World]) -> None:
    w = world()
    run = w.piped("safe -m - < <(printf 'Merge: the message from stdin\\n')")
    assert run.rc == 0, run.text
    assert w.git("log", "-1", "--format=%s") == "Merge: the message from stdin"


def test_an_unreadable_message_file_is_refused(world: Callable[[], World], scratch: Path) -> None:
    w = world()
    before = w.head()
    run = w.run("safe", "-m", str(scratch / "nope.txt"))
    assert run.rc == 2, run.text
    run.says("no such readable file")
    assert w.head() == before


# --- the exit propagation -------------------------------------------------------------------------


def test_a_red_gate_propagates(world: Callable[[], World]) -> None:
    w = world()
    run = w.run("safe", env={"DJB_DRIVE_GATE_RC": "1"})
    assert run.rc == 1, run.text
    run.says("MERGED. Proof of merge", "STUB GATE ran with: --fast")
    assert w.parents() == 2


def test_an_enforcement_broken_gate_propagates(world: Callable[[], World]) -> None:
    run = world().run("safe", env={"DJB_DRIVE_GATE_RC": "2"})
    assert run.rc == 2, run.text
    run.says("MERGED. Proof of merge")


def test_a_missing_gate_is_refused_before_the_merge(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    (w.repo / "scripts" / "check.sh").unlink()
    run = w.run("safe")
    assert run.rc == 2, run.text
    run.says("no executable gate")
    assert w.head() == before


def test_the_merge_consults_the_measured_tree_and_never_a_raw_one() -> None:
    source = inspect.getsource(merge.consult)
    assert source.count('ledger.measured_tree_of(root, f"{tip}^{{tree}}")') == 1
    assert "rev-parse" not in source


# --- the fold rule --------------------------------------------------------------------------------


def test_a_clean_fold_prints_equals(world: Callable[[], World]) -> None:
    w = world()
    w.fold_clean("safe")
    fold = w.git("rev-parse", "--short=8", "safe")
    run = w.run("safe")
    assert run.rc == 0, run.text
    run.before(f"fold {fold}: equals merge-tree", "MERGED. Proof of merge")
    run = world().run("safe")
    assert run.rc == 0, run.text
    run.says("fold: none")


def test_a_hand_fold_without_resolution_is_refused(world: Callable[[], World]) -> None:
    w = world()
    w.fold_by_hand("clash", "resolved by hand")
    fold = w.git("rev-parse", "--short=8", "clash")
    before = w.head()
    run = w.run("clash")
    assert run.rc == 2, run.text
    run.says(
        f"fold {fold}: differs from merge-tree — 1 paths: shared.txt",
        f"could not merge: fold {fold} differs from merge-tree in shared.txt; pass --resolution"
        " <file> naming each path and why",
    )
    run.says_not("MERGED. Proof of merge")
    assert w.head() == before
    assert run.gate == ""


def test_a_hand_fold_with_its_resolution_merges(world: Callable[[], World], scratch: Path) -> None:
    w = world()
    w.fold_by_hand("clash", "resolved by hand")
    fold = w.git("rev-parse", "--short=8", "clash")
    res = scratch / "resolution.txt"
    res.write_text("shared.txt — kept main's line and the branch's intent in one\n")
    run = w.run("clash", "--resolution", str(res))
    assert run.rc == 0, run.text
    run.says(f"fold {fold}: differs from merge-tree — 1 paths: shared.txt")
    run.before(
        "MERGED. Proof of merge",
        "resolution    shared.txt — kept main's line and the branch's intent in one",
    )
    assert run.gate == "--fast\n"


def test_a_resolution_must_name_exactly_the_differing_paths(
    world: Callable[[], World], scratch: Path
) -> None:
    w = world()
    w.fold_by_hand("clash", "resolved by hand")
    res = scratch / "wrong.txt"
    res.write_text("other.txt — not a path this fold touched\n")
    before = w.head()
    run = w.run("clash", "--resolution", str(res))
    assert run.rc == 2, run.text
    run.says(
        f"could not merge: --resolution {res} does not name shared.txt",
        f"could not merge: --resolution {res} names other.txt, which no fold differs in",
    )
    assert w.head() == before
    w = world()
    w.fold_by_hand("clash", "resolved by hand")
    res = scratch / "grammar.txt"
    res.write_text("shared.txt: because\n")
    run = w.run("clash", "--resolution", str(res))
    assert run.rc == 2, run.text
    run.says("is not <path> — <why>: shared.txt: because")
    w = world()
    w.fold_clean("safe")
    res = scratch / "nothing.txt"
    res.write_text("safe.txt — nothing\n")
    run = w.run("safe", "--resolution", str(res))
    assert run.rc == 2, run.text
    run.says("names safe.txt, which no fold differs in")


def test_a_hand_edit_inside_a_clean_fold_differs(world: Callable[[], World]) -> None:
    w = world()
    w.git("checkout", "-q", "safe")
    w.git("merge", "-q", "--no-edit", "--no-commit", "main")
    (w.repo / "extra.txt").write_text("slipped in\n")
    w.git("add", "extra.txt")
    w.git("commit", "-q", "--no-edit")
    w.git("checkout", "-q", "main")
    fold = w.git("rev-parse", "--short=8", "safe")
    run = w.run("safe")
    assert run.rc == 2, run.text
    run.says(f"fold {fold}: differs from merge-tree — 1 paths: extra.txt")


def test_a_merge_of_another_branch_is_not_a_fold(world: Callable[[], World]) -> None:
    w = world()
    w.commit_on("side", "stale", "side.txt", "side\n", "side change")
    w.git("checkout", "-q", "safe")
    w.git("merge", "-q", "--no-edit", "side")
    w.git("checkout", "-q", "main")
    run = w.run("safe")
    assert run.rc == 0, run.text
    run.says("fold: none")


# --- condition 1: the merge refuses while main is red or unread ---------------------------------


def test_merge_refuses_an_unread_main(world: Callable[[], World]) -> None:
    w = world()
    before = w.head()
    run = w.run("safe", read=False)
    assert run.rc == 2, run.text
    run.says(
        f"could not merge: main {w.tree()[:8]} has no green loop row and no first-parent"
        " ancestor within 60 commits, nor a merge's second parent among them, has one",
        "run ./scripts/pm_main_loop.sh and read its line, or pass --main-unmeasured <who>:<why>",
    )
    run.says_not("MERGED. Proof of merge")
    assert w.head() == before
    assert run.gate == ""


def test_merge_reads_a_green_main(world: Callable[[], World]) -> None:
    run = world().run("safe")
    assert run.rc == 0, run.text
    run.says(f"main: read — loop row {LOOP_KEY_E} banked 2026-10-02T09:00:00Z")
    run.before("main: read — loop row", "MERGED. Proof of merge")


def test_merge_admits_a_docs_only_delta(world: Callable[[], World]) -> None:
    w = world()
    w.main_read()
    read8 = w.tree()[:8]
    w.commit(".claude/skills/fixture-note.md", "a ledger line\n", "ledger")
    run = w.run("safe", read=False)
    assert run.rc == 0, run.text
    run.says(f"main: read — docs-only delta from {read8} (1 paths), loop row loop-v1:")
    w = world()
    w.main_read()
    read8 = w.tree()[:8]
    w.commit("code.txt", "code\n", "code")
    run = w.run("safe", read=False)
    assert run.rc == 2, run.text
    run.says(f"and its delta from {read8} is not docs-only (code.txt)")
    assert run.gate == ""


def train_merged(w: World) -> str:
    w.commit_on("train", "main", "train.txt", "train\n", "train")
    tree = w.tree()
    w.row(
        f"v1 {LOOP_KEY_F} loop 2026-10-02T10:00:00Z caller=box scope=mode=fast passes=1"
        f" tree={tree} env=x"
    )
    w.git("checkout", "-q", "main")
    w.commit(".claude/skills/ledger-note.md", "a ledger line\n", "ledger while the train ran")
    w.git("merge", "-q", "--no-ff", "--no-edit", "train")
    return tree


def test_merge_reads_main_through_a_trains_second_parent(world: Callable[[], World]) -> None:
    w = world()
    train8 = train_merged(w)[:8]
    w.commit(".claude/skills/fixture-note.md", "a prose line\n", "prose")
    run = w.run("safe", read=False)
    assert run.rc == 0, run.text
    run.says(f"main: read — docs-only delta from {train8} (2 paths), loop row {LOOP_KEY_F}")
    w = world()
    train8 = train_merged(w)[:8]
    w.commit("code.txt", "code\n", "code")
    run = w.run("safe", read=False)
    assert run.rc == 2, run.text
    run.says(f"and its delta from {train8} is not docs-only (code.txt)")
    assert run.gate == ""


def test_merge_admits_a_typed_sanction(world: Callable[[], World]) -> None:
    sanction = "pm:the isolation flake, re-run queued"
    run = world().run("safe", "--main-unmeasured", sanction, read=False)
    assert run.rc == 0, run.text
    run.says("main: UNMEASURED — sanction=typed:pm:the%20isolation%20flake,%20re-run%20queued")
    run.before("MERGED. Proof of merge", "main-unmeasured sanction=typed:pm:")
    run = world().run("safe", "--main-unmeasured", "pm:flaky", read=False)
    assert run.rc == 2, run.text
    run.says("the sanction's reason is 5 character(s)")
    assert run.gate == ""
    run = world().run("safe", "--main-unmeasured", "a reason with no who in it", read=False)
    assert run.rc == 2, run.text
    run.says("--main-unmeasured takes <who>:<why>")
    run = world().run("safe", "--main-unmeasured", sanction)
    assert run.rc == 2, run.text
    run.says("could not merge: --main-unmeasured was given and main is read")


def test_merge_names_the_red_main_loop_log(world: Callable[[], World]) -> None:
    w = world()
    home = w.repo / ".git" / "djb-main-loop"
    home.mkdir()
    log = home / f"main-loop-{w.git('rev-parse', '--short=8', 'HEAD')}.log"
    log.write_text(f"a red loop\nmain-loop: red {w.tree()} 812s {log}\n")
    run = w.run("safe", read=False)
    assert run.rc == 2, run.text
    run.says("main's last loop on this tree: red — ", f"/.git/djb-main-loop/{log.name}")
