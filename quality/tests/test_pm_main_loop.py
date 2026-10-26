"""`python -m quality.djb.rituals.main_loop` driven over scratch primaries with a stub box client.

does-not-cover: a real box — the stub answers `up`, `push`, `loop`, `wait`, `fetch` and `down`.
does-not-cover: the box's gate writing `caller=` — the stub writes the caller its `loop` was handed.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.tests.conftest import REAL_TIME_CEILING_S
from quality.tests.fixtures.capture import run_to

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/main_loop.py",
    "quality/djb/ledger.py",
    "scripts/pm_main_loop.sh",
    "scripts/bash_only.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.main_loop import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
STRIPPED = ("CI", "DJB_GATE_LEDGER", "DJB_GATE_CALLER", "GIT_DIR", "GIT_WORK_TREE", "PYTHONPATH")
STUB = '''\
"""The stub box client: records its argv, its checkout's base, the caller it was handed."""

import os
import subprocess
import sys
import time
from pathlib import Path

REC = Path({rec!r})
argv = sys.argv[1:]
with (REC / "argv").open("a") as fh:
    fh.write(" ".join(argv) + "\\n")


def base():
    done = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "refs/djb/base"], capture_output=True, text=True
    )
    (REC / "base").write_text((done.stdout.strip() if done.returncode == 0 else "none") + "\\n")


sub = argv[0] if argv else ""
if sub == "up":
    base()
    rc = int(os.environ.get("STUB_UP_RC", "0"))
    if rc:
        print("verifier_box: no capacity", file=sys.stderr)
        sys.exit(rc)
    print("claimed i-stub0001 (warm, 3m)")
    print("instance   i-stub0001   c7g.4xlarge   market: spot   az us-east-1a")
elif sub == "push":
    base()
elif sub == "loop":
    (REC / "caller").write_text(os.environ.get("DJB_GATE_CALLER", "") + "\\n")
    print(f"gate detached on {{argv[1]}} as pid 4242")
elif sub == "wait":
    if os.environ.get("STUB_WAIT_HANG"):
        time.sleep(60)
    rc = int(os.environ.get("STUB_WAIT_RC", "0"))
    print(f"--- last 40 lines of ~/verify/main-loop/{{argv[2]}}.log ---")
    print("the box's loop output")
    print(f"--- gate exit {{rc}} ---")
    if rc == 0:
        caller = (REC / "caller").read_text().strip() if (REC / "caller").is_file() else ""
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{{tree}}"], capture_output=True, text=True
        ).stdout.strip()
        with open(os.environ["DJB_GATE_LEDGER"], "a") as fh:
            fh.write(
                f"v1 loop-v1:{{'c' * 64}} loop 2026-10-02T12:00:00Z caller={{caller or 'unread'}}"
                f" scope=mode=fast passes=1 tree={{tree}} env=x box={{argv[1]}}\\n"
            )
    sys.exit(rc)
elif sub == "fetch":
    Path(argv[3]).write_text("the box's loop output\\n")
elif sub == "down":
    pass
else:
    print(f"stub box: unknown command {{sub!r}}", file=sys.stderr)
    sys.exit(2)
'''


@dataclass
class World:
    """A scratch primary on main: its stub box's record, its ledger, its home and two shas."""

    repo: Path
    rec: Path
    ledger: Path
    home: Path
    sha_s: str
    sha_c1: str
    out: Path = Path()
    rc: int = -1

    def git(self, *argv: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.repo), *argv], capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    def commit(self, path: str, text: str, message: str) -> str:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as fh:
            fh.write(text)
        self.git("add", path)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def env(self, **extra: str) -> dict[str, str]:
        kept = {k: v for k, v in os.environ.items() if k not in STRIPPED}
        return {
            **kept,
            "PYTHONPATH": str(ROOT),
            "DJB_GATE_LEDGER": str(self.ledger),
            "DJB_MAIN_LOOP_HOME": str(self.home),
            **extra,
        }

    def argv(self, *args: str) -> list[str]:
        return [sys.executable, "-P", "-c", ENTRY, *args]

    def run(self, *args: str, **extra: str) -> World:
        self.out = self.repo.parent / f"out-{len(list(self.repo.parent.glob('out-*')))}.log"
        done = run_to(self.out, self.argv(*args), self.repo, self.env(**extra))
        self.rc = done.rc
        return self

    def text(self) -> str:
        return self.out.read_text(errors="replace")

    def last(self, fields: int) -> list[str]:
        return self.text().splitlines()[-1].split()[:fields]

    def calls(self) -> list[str]:
        return (self.rec / "argv").read_text().splitlines()

    def base(self) -> str:
        return (self.rec / "base").read_text().strip()

    def rows(self, needle: str) -> int:
        return sum(needle in line for line in self.ledger.read_text().splitlines())

    def row(self, tree: str, caller: str, box: str) -> None:
        with self.ledger.open("a") as fh:
            fh.write(
                f"v1 loop-v1:{'d' * 64} loop 2026-10-02T11:00:00Z caller={caller}"
                f" scope=mode=fast passes=1 tree={tree} env=x box={box}\n"
            )


@pytest.fixture
def world(scratch: Path, scratch_repo: Callable[..., Path]) -> World:
    """A primary: the stub box, a code commit, a merged lane and a docs commit, on main."""
    rec = scratch / "rec"
    rec.mkdir()
    (rec / "argv").write_text("")
    ledger = scratch / "ledger"
    ledger.write_text("")
    repo = scratch_repo("repo", "main-loop")
    w = World(repo, rec, ledger, scratch / "home", "", "")
    for package in ("quality", "quality/djb", "quality/djb/box"):
        (repo / package).mkdir(parents=True, exist_ok=True)
        (repo / package / "__init__.py").write_text("")
    (repo / "quality/djb/box/__main__.py").write_text(STUB.format(rec=str(rec)))
    w.git("add", "quality")
    w.git("commit", "-q", "-m", "scripts")
    w.sha_s = w.git("rev-parse", "HEAD")
    w.sha_c1 = w.commit("code.txt", "code\n", "code")
    w.git("checkout", "-q", "-b", "lane")
    w.commit("lane.txt", "lane\n", "lane")
    w.git("checkout", "-q", "main")
    w.git("merge", "-q", "--no-ff", "--no-edit", "lane")
    w.commit(".claude/skills/fixture-note.md", "a ledger line\n", "ledger")
    return w


def test_main_loop_refuses_a_dirty_primary(world: World) -> None:
    with (world.repo / "code.txt").open("a") as fh:
        fh.write("an unsaved edit\n")
    world.run()
    assert world.rc == 2, world.text()
    assert "uncommitted changes" in world.text()
    assert "Nothing was launched" in world.text()
    assert world.calls() == []


def test_main_loop_prints_its_verdict_line(world: World) -> None:
    sha8 = world.git("rev-parse", "--short=8", "main")
    tree = world.git("rev-parse", "main^{tree}")
    log = world.home / f"main-loop-{sha8}.log"
    world.run()
    assert world.rc == 0, world.text()
    calls = world.calls()
    assert "up --for main-loop" in calls
    assert f"loop i-stub0001 --log main-loop-{sha8}" in calls
    assert f"wait i-stub0001 main-loop-{sha8}" in calls
    assert "down i-stub0001" in calls
    assert world.last(3) == ["main-loop:", "green", tree]
    assert world.text().splitlines()[-1].split()[4] == str(log)
    assert log.read_text().splitlines()[-1].split()[:3] == ["main-loop:", "green", tree]
    assert world.base() == world.sha_c1
    assert "main-loop: row v1 loop-v1:" in world.text()
    assert world.rows(" caller=main-loop ") == 1 and world.rows(f" tree={tree} ") == 1
    assert world.git("for-each-ref", "refs/djb/base") == ""


def test_main_loop_red_is_red_and_the_box_goes_down(world: World) -> None:
    tree = world.git("rev-parse", "main^{tree}")
    world.run(STUB_WAIT_RC="1")
    assert world.rc == 1, world.text()
    assert world.last(3) == ["main-loop:", "red", tree]
    assert "down i-stub0001" in world.calls()
    assert world.rows(f" tree={tree} ") == 0


def test_main_loop_interrupted_downs_its_box(world: World) -> None:
    world.out = world.repo.parent / "interrupted.log"
    with world.out.open("wb") as sink:
        proc = subprocess.Popen(
            world.argv(),
            cwd=world.repo,
            env=world.env(STUB_WAIT_HANG="1"),
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not any(c.startswith("wait ") for c in world.calls()):
            time.sleep(0.2)
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            rc = proc.wait(timeout=REAL_TIME_CEILING_S + 10)
        finally:
            if proc.poll() is None:
                proc.kill()
    assert time.monotonic() - started < REAL_TIME_CEILING_S, (
        "the interrupt waited behind the hung wait"
    )
    assert rc == 2, world.text()
    assert "down i-stub0001" in world.calls()
    assert "main-loop: could-not-look" in world.text()


def test_main_loop_base_is_the_last_tree_its_loop_read(world: World) -> None:
    world.row(world.git("rev-parse", f"{world.sha_s}^{{tree}}"), "main-loop", "i-old")
    world.run()
    assert world.rc == 0, world.text()
    assert world.base() == world.sha_s
    short = world.git("rev-parse", "--short=8", world.sha_s)
    assert (
        f"base       {short} (the newest row-named tree on the first-parent line or a merge's"
        " second parent)"
    ) in world.text()


def test_main_loop_base_is_a_trains_second_parent(world: World) -> None:
    world.git("checkout", "-q", "-b", "train", "main")
    train = world.commit("train.txt", "train\n", "train")
    world.git("checkout", "-q", "main")
    world.commit(".claude/skills/ledger-note.md", "a ledger line while the train ran\n", "ledger")
    world.git("merge", "-q", "--no-ff", "--no-edit", "train")
    world.commit(".claude/skills/fixture-note.md", "a prose line\n", "prose")
    world.row(world.git("rev-parse", f"{train}^{{tree}}"), "box", "i-train")
    world.run()
    assert world.rc == 0, world.text()
    assert world.base() == train
    short = world.git("rev-parse", "--short=8", train)
    assert (
        f"base       {short} (the newest row-named tree on the first-parent line or a merge's"
        " second parent)"
    ) in world.text()


def test_main_loop_with_a_named_box_leaves_it_up(world: World) -> None:
    world.run("--box", "i-given01")
    assert world.rc == 0, world.text()
    calls = world.calls()
    assert not any(c.startswith("up ") for c in calls)
    assert "push i-given01" in calls
    assert not any(c.startswith("down ") for c in calls)
    assert world.base() == world.sha_c1


def test_main_loop_a_box_that_will_not_come_up_could_not_look(world: World) -> None:
    world.run(STUB_UP_RC="2")
    assert world.rc == 2, world.text()
    assert "main-loop: could-not-look" in world.text()
    calls = world.calls()
    assert not any(c.startswith("loop ") for c in calls)
    assert not any(c.startswith("down ") for c in calls)


def test_main_loop_refuses_a_piped_stdout(world: World) -> None:
    command = "set -o pipefail; " + shlex.join(world.argv()) + " | cat"
    world.out = world.repo.parent / "piped.log"
    world.rc = run_to(world.out, ["bash", "-c", command], world.repo, world.env()).rc
    assert world.rc == 2, world.text()
    assert "refuses pipes" in world.text()
    assert world.calls() == []
