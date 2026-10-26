"""The gate's machine guards through `quality.djb.hold`, and the shell text that wires them."""

# does-not-cover: whether the gate acquires at runtime — the wiring is read as text.
# does-not-cover: contention across machines — out of scope by construction.
# does-not-cover: whether serializing makes the gate faster or greener — no wall clock asserted.
# does-not-cover: what a caller value means, or whether a sanction's reason is any good.
# does-not-cover: the legal `--bank` — every valve case drives a refusal.
# does-not-cover: whether N slots is the right N — the arithmetic, never the ratio.
# does-not-cover: a bare `pytest` — it takes no slot, by construction.
# deleted: case_the_usage_header_and_the_parser_agree (test_cli.py) — dies with the shim
# pin: test_registry.py::test_the_usage_and_the_parser_are_one_table
# deleted: test_the_pm_push_arm_is_not_a_basename_alone — dies with the shim
# pin: test_gate_args.py::test_bank_from_a_linked_worktree_is_refused_naming_it
# deleted: test_the_wiring_in_check_sh — dies with the shim
# pin: test_modes.py::test_the_full_gate_asks_the_lease_before_the_lock_and_releases_both
# pin: test_modes.py::test_a_refused_lease_is_exit_2_and_the_lock_is_never_asked
# deleted: test_the_slot_wiring_in_check_sh — dies with the shim
# pin: test_legs_pytest_x2.py::test_the_suite_takes_one_slot_and_a_bank_takes_every_slot
# narrowed: test_the_workers_sentence_is_true_in_both_cases — its check.sh half dies with the shim
# pin: test_legs_pytest_x2.py::test_the_workers_line_carries_the_slots_own_phrase
# deleted: test_the_sanction_valve_wiring_in_check_sh — dies with the shim
# pin: test_gate_args.py::test_the_unsanctioned_full_gate_is_refused_in_the_shells_bytes
# pin: test_gate_args.py::test_ci_and_the_push_wall_are_sanctions_of_their_own
# deleted: the four gate-heartbeat tests — dies with the shim; no port (GAP, the PM's ruling)
# does-not-cover: the pass heartbeat — pytest_x2.py:4 and loop_pytest.py:3 declare it.

from __future__ import annotations

import ast
import functools
import io
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from quality.djb import env, hold
from quality.djb import ledger as verdicts
from quality.djb.rituals import push

pytestmark = pytest.mark.drives("quality/djb/hold.py", "scripts/gate_lease.sh")

ROOT = Path(__file__).resolve().parents[2]
HOST = hold.host()
KNOBS = tuple(env.NAMES)


@pytest.fixture(autouse=True)
def _own_environment() -> Iterator[None]:
    """Each case starts with no gate knob set and leaves the process environment as it found it."""
    saved = dict(os.environ)
    for name in KNOBS:
        os.environ.pop(name, None)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def lease_dir(scratch: Path) -> Callable[[], Path]:
    """`lease_dir()` points `DJB_GATE_LEASE_DIR` at a fresh scratch directory and answers it."""
    count = 0

    def fresh() -> Path:
        nonlocal count
        count += 1
        where = scratch / f"lease{count}"
        where.mkdir()
        os.environ["DJB_GATE_LEASE_DIR"] = str(where)
        return where

    return fresh


class Pids:
    """Processes a case starts as holders, killed by pid at teardown."""

    def __init__(self) -> None:
        self.started: list[subprocess.Popen[bytes]] = []

    def live(self) -> int:
        """A pid certainly running for the case's length."""
        child = subprocess.Popen(
            ["sleep", "600"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.started.append(child)
        return child.pid

    def dead(self) -> int:
        """A pid that was real and is gone, never an invented number."""
        child = subprocess.Popen(["true"])
        child.wait()
        return child.pid

    def keep(self, child: subprocess.Popen[bytes]) -> subprocess.Popen[bytes]:
        """Track a child the case started some other way."""
        self.started.append(child)
        return child


@pytest.fixture
def pids() -> Iterator[Pids]:
    """Holder processes, each killed by pid at teardown."""
    tracked = Pids()
    yield tracked
    for child in tracked.started:
        if child.poll() is None:
            child.kill()
            child.wait()


def knobs(**values: object) -> None:
    """Set gate knobs for this case."""
    for name, value in values.items():
        os.environ[name] = str(value)


def lease_record(
    pid: int, where: str = HOST, epoch: str = "", stamp: str = "", machine: str = ""
) -> str:
    """A lease holder record in the shape `hold.record` writes, with an optional epoch and id."""
    stamp = stamp or "2026-08-25T00:00:00Z"
    fields = [str(pid), "full", stamp, where] + ([epoch] if epoch else []) + ["/some/other"]
    fields += [f"machine={machine}"] if machine else []
    return " ".join(fields) + "\n"


def plant_slot(slots: Path, number: int, pid: int, where: str = HOST, mode: str = "loop") -> Path:
    """A holder planted into `slot-<number>`: pid mode started-utc host started-epoch checkout."""
    slot = slots / f"slot-{number}"
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "holder").write_text(
        f"{pid} {mode} 2026-08-30T00:00:00Z {where} {int(time.time())} /some/other/checkout\n"
    )
    return slot


def slot_pid(slots: Path, number: int) -> str:
    """The pid recorded in a slot, or empty."""
    try:
        return (slots / f"slot-{number}" / "holder").read_text().split()[0]
    except (OSError, IndexError):
        return ""


def wait_for(seconds: float, test: Callable[[], bool]) -> bool:
    """A bounded poll: true as soon as `test` is, false at the ceiling."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if test():
            return True
        time.sleep(0.2)
    return test()


def refused_text(call: Callable[[], object]) -> tuple[hold.Refused, str]:
    """Run a call that must refuse; answer the refusal and everything it said."""
    text = io.StringIO()
    with pytest.raises(hold.Refused) as caught:
        call_with(call, text)
    return caught.value, text.getvalue()


def call_with(call: Callable[[], object], text: io.StringIO) -> object:
    """Run `call` with `hold`'s default streams pointed at `text`."""
    saved = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = text
    try:
        return call()
    finally:
        sys.stdout, sys.stderr = saved


def spoken(call: Callable[[], object]) -> tuple[object, str]:
    """Run a call that must succeed; answer its result and everything it said."""
    text = io.StringIO()
    result = call_with(call, text)
    return result, text.getvalue()


def race(scratch: Path, code: str, racers: int = 6) -> int:
    """`racers` Python processes released together through one barrier; how many printed `won`."""
    # Released only once every racer has imported; none exits until every racer has tried.
    gate = scratch / f"race-{time.monotonic_ns()}"
    gate.mkdir()
    script = (
        "import os, sys, time\n"
        "from quality.djb import hold\n"
        f"gate, n = {str(gate)!r}, {racers}\n"
        "def meet(word):\n"
        "    open(os.path.join(gate, f'{word}-{os.getpid()}'), 'w').close()\n"
        "    end = time.monotonic() + 60\n"
        "    while sum(f.startswith(word) for f in os.listdir(gate)) < n:\n"
        "        if time.monotonic() > end: sys.exit(3)\n"
        "        time.sleep(0.002)\n"
        "meet('ready')\n" + code + "sys.stdout.flush()\nmeet('tried')\n"
    )
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for _ in range(racers)
    ]
    said = [child.communicate(timeout=120)[0] for child in children]
    assert [child.returncode for child in children] == [0] * racers, said
    return sum(out.count("won") for out in said)


BANK = """
import os, sys, time
from quality.djb import hold
rc, taken = 0, None
try:
    taken = hold.acquire_slot(sys.argv[1])
except hold.Refused:
    rc = 2
print(f"BANK_WORKERS={taken.workers if taken else ''}", flush=True)
print(f"BANK_PHRASE={taken.phrase if taken else ''}", flush=True)
print(f"BANK_RC={rc}", flush=True)
if rc:
    sys.exit(rc)
while os.path.exists(sys.argv[2]):
    time.sleep(1)
taken.release()
"""


def start_bank(
    scratch: Path, pids: Pids, **values: object
) -> tuple[subprocess.Popen[bytes], Path, Path]:
    """`acquire_slot("bank")` in its own process, holding what it took until its flag goes."""
    log = scratch / f"bank-{time.monotonic_ns()}.log"
    flag = log.with_suffix(".hold")
    flag.write_text("")
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    environment.update({name: str(value) for name, value in values.items()})
    with log.open("wb") as sink:
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", BANK, "bank", str(flag)],
            cwd=ROOT,
            env=environment,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    return pids.keep(child), log, flag


def bash(capture: Callable[..., object], script: str, cwd: Path) -> tuple[int, str]:
    """`script` under bash in `cwd`, through the capture fixture; its exit and its output."""
    done = capture(["bash", "-c", script], cwd=cwd)
    path = done.path  # type: ignore[attr-defined]
    return done.rc, path.read_text(errors="replace") if path.stat().st_size else ""  # type: ignore[attr-defined]


def text(path: Path) -> str:
    """A file's whole text."""
    return path.read_text(errors="replace")


# --- the lease ---------------------------------------------------------------


def test_an_uncontended_lease_is_taken_at_once(lease_dir: Callable[[], Path]) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    taken, said = spoken(hold.acquire_lease)
    assert isinstance(taken, hold.Hold)
    assert "full-gate lease held for this MACHINE" in said
    assert "WAITING" not in said
    assert lease.is_file()
    assert taken.waited == 0
    fields = lease.read_text().split()
    assert len(fields) >= 5 and fields[0] == str(os.getpid()) and fields[1] == "full"
    taken.release()
    assert not lease.exists()


def test_a_second_gate_WAITS_and_SAYS_SO(lease_dir: Callable[[], Path], pids: Pids) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    holder = pids.live()
    lease.write_text(lease_record(holder))
    knobs(DJB_GATE_LEASE_MAX_WAIT=3, DJB_GATE_LEASE_POLL=1, DJB_GATE_LEASE_ANNOUNCE=1)
    _, said = refused_text(hold.acquire_lease)
    for needle in (
        "WAITING for the machine-wide full-gate lease",
        "This is not a hang.",
        f"holder: {holder} full",
        "... still waiting for the full-gate lease",
        "REFUSING: waited",
        "Nothing was judged. This is could-not-look, not a red tree.",
    ):
        assert needle in said
    assert f"{holder} full" in lease.read_text()


def test_the_lease_wait_prints_an_estimate_too(lease_dir: Callable[[], Path], pids: Pids) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    holder = pids.live()
    lease.write_text(lease_record(holder, epoch=str(int(time.time()) - 300)))
    knobs(DJB_GATE_LEASE_MAX_WAIT=3, DJB_GATE_LEASE_POLL=1, DJB_GATE_LEASE_ANNOUNCE=1)
    _, said = refused_text(hold.acquire_lease)
    assert "Rough estimate from the holder's elapsed time: ~10 min" in said
    assert "not a promise — nothing here decides anything on it" in said
    assert "~10 min of a nominal 15 left)" in said

    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.live()))
    knobs(DJB_GATE_LEASE_MAX_WAIT=2)
    _, said = refused_text(hold.acquire_lease)
    assert "WAITING for the machine-wide full-gate lease" in said
    assert "Rough estimate" not in said
    assert "min left)" not in said

    lease = lease_dir() / hold.LEASE_FILE
    taken = hold.try_lease()
    assert taken is not None
    assert lease.read_text().split()[4].isdigit()
    taken.release()


def test_a_waiter_gets_the_lease_when_the_holder_lets_go(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.live()))
    letting_go = threading.Timer(2, lambda: lease.unlink(missing_ok=True))
    letting_go.start()
    knobs(DJB_GATE_LEASE_MAX_WAIT=30, DJB_GATE_LEASE_POLL=1, DJB_GATE_LEASE_ANNOUNCE=1)
    try:
        taken, said = spoken(hold.acquire_lease)
    finally:
        letting_go.cancel()
    assert "WAITING for the machine-wide full-gate lease" in said
    assert "full-gate lease ACQUIRED after" in said
    assert lease.is_file()
    assert isinstance(taken, hold.Hold)
    taken.release()


def test_a_dead_holders_lease_clears_itself(lease_dir: Callable[[], Path], pids: Pids) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.dead()))
    knobs(DJB_GATE_LEASE_MAX_WAIT=3, DJB_GATE_LEASE_POLL=1)
    taken, said = spoken(hold.acquire_lease)
    assert "cleared a STALE full-gate lease" in said
    assert "full-gate lease held for this MACHINE" in said
    assert isinstance(taken, hold.Hold) and taken.waited == 0
    taken.release()


def test_a_LIVE_holder_is_never_cleared(lease_dir: Callable[[], Path], pids: Pids) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    holder = pids.live()
    lease.write_text(lease_record(holder))
    taken, said = spoken(hold.try_lease)
    assert taken is None
    held, said_more = spoken(lambda: hold.holder_of(lease, "full-gate lease"))
    assert f"{holder} full" in str(held)
    assert "cleared a STALE" not in said + said_more


def test_another_hosts_lease_is_never_cleared(lease_dir: Callable[[], Path], pids: Pids) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.dead(), where="not-this-host"))
    held, said = spoken(lambda: hold.holder_of(lease, "full-gate lease"))
    assert "not-this-host" in str(held)
    assert "cleared a STALE" not in said
    assert lease.is_file()
    knobs(DJB_GATE_LEASE_MAX_WAIT=2, DJB_GATE_LEASE_POLL=1)
    _, said = refused_text(hold.acquire_lease)
    assert "written by another host" in said


OURS, THEIRS = "id-of-this-machine", "id-of-another-machine"


@pytest.fixture
def this_machine(monkeypatch: pytest.MonkeyPatch) -> str:
    """`hold.machine_id()` answers a fixed id for the case."""
    monkeypatch.setattr(hold, "machine_id", lambda err=None: OURS, raising=False)
    return OURS


def test_a_dead_holder_of_this_machine_is_cleared_whatever_its_host_name_was(
    lease_dir: Callable[[], Path], pids: Pids, this_machine: str
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.dead(), where="a-name-this-mac-had-once", machine=OURS))
    held, said = spoken(lambda: hold.holder_of(lease, "full-gate lease"))
    assert held == ""
    assert "cleared a STALE full-gate lease" in said
    assert not lease.exists()


def test_another_machines_dead_holder_is_never_cleared_even_under_this_host_name(
    lease_dir: Callable[[], Path], pids: Pids, this_machine: str
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.dead(), machine=THEIRS))
    held, said = spoken(lambda: hold.holder_of(lease, "full-gate lease"))
    assert THEIRS in str(held)
    assert "cleared a STALE" not in said
    assert lease.is_file()


def test_a_legacy_record_keeps_the_host_rule_and_says_once_how_to_clear_it(
    lease_dir: Callable[[], Path], pids: Pids, this_machine: str
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.dead(), where=f"not-{HOST}"))
    sentence = f"legacy record (no machine id): if this is your machine, remove {lease} by hand"
    held, said = spoken(lambda: hold.holder_of(lease, "full-gate lease"))
    again, said_again = spoken(lambda: hold.holder_of(lease, "full-gate lease"))
    assert f"not-{HOST}" in str(held) and held == again
    assert lease.is_file()
    assert said.count(sentence) == 1 and sentence not in said_again


def test_the_machine_id_is_the_file_then_the_platform_uuid_then_the_host_said_aloud(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = scratch / "machine-id"
    planted.write_text("0123abcd\n")
    monkeypatch.setattr(hold, "MACHINE_ID_FILE", str(planted))
    hold.machine_id.cache_clear()
    assert spoken(hold.machine_id) == ("0123abcd", "")
    monkeypatch.setattr(hold, "MACHINE_ID_FILE", str(scratch / "absent"))
    monkeypatch.setattr(hold, "_platform_uuid", lambda: "15E9BB9C-FA57")
    hold.machine_id.cache_clear()
    assert spoken(hold.machine_id) == ("15E9BB9C-FA57", "")
    monkeypatch.setattr(hold, "_platform_uuid", lambda: "")
    hold.machine_id.cache_clear()
    found, said = spoken(hold.machine_id)
    assert found == HOST and "no machine id" in said and "host name" in said
    hold.machine_id.cache_clear()


def test_every_record_this_process_writes_carries_the_machine_id(
    this_machine: str, scratch_repo: Callable[..., Path], lease_dir: Callable[[], Path]
) -> None:
    assert hold.record("loop").split()[-1] == f"machine={OURS}"
    lease_dir()
    taken, _ = spoken(lambda: hold.acquire_lock(scratch_repo("id-repo")))
    assert isinstance(taken, hold.Hold)
    assert hold._first_line(taken.paths[0]).split()[4] == f"machine={OURS}"
    taken.release()


def test_another_hosts_lock_is_never_cleared(scratch_repo: Callable[..., Path], pids: Pids) -> None:
    repo = scratch_repo("lock-repo")
    lock = repo / ".git" / hold.LOCK_FILE
    gone = pids.dead()
    lock.write_text(f"{gone} full 2026-08-25T00:00:00Z not-this-host\n")
    _, said = refused_text(lambda: hold.acquire_lock(repo))
    assert "not-this-host" in said
    assert "cleared a STALE" not in said
    assert lock.is_file()

    lock.write_text(f"{gone} full 2026-08-25T00:00:00Z {HOST}\n")
    taken, said = spoken(lambda: hold.acquire_lock(repo))
    assert "cleared a STALE gate lock" in said
    assert "gate lock held for this checkout" in said
    assert isinstance(taken, hold.Hold)
    taken.release()
    assert not lock.exists()


def test_a_lease_is_released_only_by_the_process_that_holds_it(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    lease.write_text(lease_record(pids.live()))
    hold.Hold("lease", [lease]).release()
    assert lease.is_file()


def test_exactly_one_of_two_racing_acquires_wins(
    lease_dir: Callable[[], Path], scratch: Path
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    winners = race(scratch, "print('won' if hold.try_lease() else 'lost')\n")
    assert winners == 1
    assert lease.is_file()


def test_a_relative_lease_directory_is_refused(scratch: Path) -> None:
    knobs(DJB_GATE_LEASE_DIR="some/relative/dir")
    _, said = refused_text(hold.lease_path)
    assert "DJB_GATE_LEASE_DIR is relative" in said

    knobs(DJB_GATE_LEASE_DIR=scratch / "definitely-not-there")
    _, said = refused_text(hold.lease_path)
    assert "is not a directory" in said

    knobs(DJB_GATE_LEASE_DIR="some/relative/dir")
    refusal, _ = refused_text(hold.acquire_lease)
    assert "DJB_GATE_LEASE_DIR is relative" in refusal.cause


# --- the counting semaphore ----------------------------------------------------


def test_the_slot_count_and_the_worker_share_are_derived() -> None:
    cores = hold.cores()
    total = hold.slots_total()
    workers = hold.slot_workers(total)
    assert 1 <= total <= cores
    assert workers >= 1 and total * workers <= cores
    knobs(DJB_GATE_SLOTS=7)
    assert hold.slots_total() == 7
    knobs(DJB_GATE_SLOTS=1)
    assert hold.slot_workers(hold.slots_total()) == cores
    knobs(DJB_GATE_SLOTS="bogus")
    _, said = refused_text(hold.slots_total)
    assert "is not a positive whole number" in said
    knobs(DJB_GATE_SLOTS=0)
    _, said = refused_text(hold.slots_total)
    assert "a box with no slots can run no suite at all" in said


def test_the_Nplus1th_pytest_leg_WAITS_and_SAYS_SO(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    holder = pids.live()
    plant_slot(slots, 1, holder, mode="full")
    knobs(
        DJB_GATE_SLOTS=1,
        DJB_GATE_SLOT_MAX_WAIT=3,
        DJB_GATE_LEASE_POLL=1,
        DJB_GATE_LEASE_ANNOUNCE=1,
    )
    _, said = refused_text(lambda: hold.acquire_slot("loop"))
    for needle in (
        "WAITING for a pytest SLOT",
        "This is not a hang.",
        "COUNTING semaphore, not the exclusive full-gate lease",
        f"holder: slot-1 {holder} full",
        "... still waiting for a pytest slot",
        "Rough estimate from the holders' elapsed time",
        "REFUSING: waited",
        "Nothing was judged. This is could-not-look, not a red tree.",
    ):
        assert needle in said
    assert (slots / "slot-1" / "holder").is_file()


def test_a_waiter_takes_a_slot_when_one_frees(lease_dir: Callable[[], Path], pids: Pids) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    slot = plant_slot(slots, 1, pids.live())
    freeing = threading.Timer(2, lambda: shutil.rmtree(slot, ignore_errors=True))
    freeing.start()
    knobs(
        DJB_GATE_SLOTS=1,
        DJB_GATE_SLOT_MAX_WAIT=30,
        DJB_GATE_LEASE_POLL=1,
        DJB_GATE_LEASE_ANNOUNCE=1,
    )
    try:
        taken, said = spoken(lambda: hold.acquire_slot("loop"))
    finally:
        freeing.cancel()
    assert "WAITING for a pytest SLOT" in said
    assert "pytest SLOT ACQUIRED after" in said
    assert isinstance(taken, hold.Hold)
    taken.release()


def test_a_killed_slot_holder_is_reclaimed(lease_dir: Callable[[], Path], pids: Pids) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    plant_slot(slots, 1, pids.dead())
    knobs(DJB_GATE_SLOTS=1, DJB_GATE_SLOT_MAX_WAIT=3, DJB_GATE_LEASE_POLL=1)
    taken, said = spoken(lambda: hold.acquire_slot("loop"))
    assert "cleared a STALE gate slot" in said
    assert "pytest slot held" in said
    assert isinstance(taken, hold.Hold)
    taken.release()


def test_a_foreign_hosts_slot_is_waited_on_then_refused(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    plant_slot(slots, 1, pids.dead(), where="not-this-host")
    knobs(
        DJB_GATE_SLOTS=1,
        DJB_GATE_SLOT_MAX_WAIT=2,
        DJB_GATE_LEASE_POLL=1,
        DJB_GATE_LEASE_ANNOUNCE=1,
    )
    _, said = refused_text(lambda: hold.acquire_slot("loop"))
    assert "not-this-host" in said
    assert "cleared a STALE gate slot" not in said
    assert (slots / "slot-1" / "holder").is_file()


def test_an_orphaned_mkdir_window_is_reclaimed_eventually(lease_dir: Callable[[], Path]) -> None:
    slot = lease_dir() / hold.SLOTS_DIR / "slot-1"
    slot.mkdir(parents=True)
    held, said = spoken(hold.slot_holders)
    assert "(starting — no holder record yet)" in "\n".join(held)  # type: ignore[arg-type]
    assert "reclaimed an ORPHAN" not in said

    old = time.mktime((2020, 1, 1, 0, 0, 0, 0, 0, -1))
    os.utime(slot, (old, old))
    _, said = spoken(hold.slot_holders)
    assert "reclaimed an ORPHAN gate slot" in said
    assert not slot.exists()


def test_a_slot_is_released_only_by_the_process_that_holds_it(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    slot = plant_slot(lease_dir() / hold.SLOTS_DIR, 1, pids.live())
    hold.Hold("slot", [slot]).release()
    assert (slot / "holder").is_file()


def test_exactly_N_of_many_racing_slot_acquires_win(
    lease_dir: Callable[[], Path], scratch: Path
) -> None:
    lease_dir()
    knobs(DJB_GATE_SLOTS=2)
    winners = race(
        scratch, "print('won' if hold.try_slot('loop', hold.Hold('slot')) else 'lost')\n"
    )
    assert winners == 2


# --- the bank: one caller that takes the whole box ---------------------------


def test_a_bank_takes_every_free_slot_and_waits_for_the_held_one(
    lease_dir: Callable[[], Path], pids: Pids, scratch: Path
) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    cores = hold.cores()
    decoy = pids.live()
    plant_slot(slots, 1, decoy)
    bank, log, flag = start_bank(
        scratch,
        pids,
        DJB_GATE_SLOTS=2,
        DJB_GATE_LEASE_POLL=1,
        DJB_GATE_LEASE_ANNOUNCE=1,
        DJB_GATE_SLOT_MAX_WAIT=90,
    )
    try:
        assert wait_for(20, lambda: slot_pid(slots, 2) == str(bank.pid))
        assert wait_for(20, lambda: "WAITING for the REST of the box" in text(log))
        assert "BANK_RC=" not in text(log)
        assert slot_pid(slots, 1) == str(decoy)
        shutil.rmtree(slots / "slot-1")
        assert wait_for(60, lambda: "BANK_RC=0" in text(log))
        assert slot_pid(slots, 1) == slot_pid(slots, 2) == str(bank.pid)
        said = text(log)
        assert "BANK COMPLETE after" in said
        assert "holds ALL 2 of 2" in said
        assert f"BANK_WORKERS={cores}" in said
        assert "BANK_PHRASE=bank: every slot — 2/2; loops wait" in said
    finally:
        flag.unlink(missing_ok=True)


def test_a_bank_that_shares_slots_takes_one_and_says_so(lease_dir: Callable[[], Path]) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    knobs(DJB_GATE_SLOTS=2, DJB_BANK_SHARES_SLOTS=1)
    taken, said = spoken(lambda: hold.acquire_slot("bank"))
    assert "bank shares the box: DJB_BANK_SHARES_SLOTS=1" in said
    assert "pytest slot held: slot-1 of 2" in said
    assert "holds ALL" not in said
    assert not (slots / "slot-2").exists()
    assert isinstance(taken, hold.Hold)
    taken.release()


def test_a_loop_arriving_during_a_bank_waits_naming_the_bank(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    banker = pids.live()
    plant_slot(slots, 1, banker, mode="bank")
    plant_slot(slots, 2, banker, mode="bank")
    knobs(
        DJB_GATE_SLOTS=2,
        DJB_GATE_SLOT_MAX_WAIT=3,
        DJB_GATE_LEASE_POLL=1,
        DJB_GATE_LEASE_ANNOUNCE=1,
    )
    _, said = refused_text(lambda: hold.acquire_slot("loop"))
    assert (
        f"holder: bank holds 2/2 slots — loops wait (pid {banker}, started 2026-08-30T00:00:00Z)"
        in said
    )
    assert f"holder: slot-1 {banker} bank" not in said


def test_a_released_bank_frees_every_slot(lease_dir: Callable[[], Path]) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    knobs(DJB_GATE_SLOTS=2)
    taken, said = spoken(lambda: hold.acquire_slot("bank"))
    assert "holds ALL 2 of 2" in said
    assert (slots / "slot-1").is_dir() and (slots / "slot-2").is_dir()
    assert isinstance(taken, hold.Hold)
    taken.release()
    assert not (slots / "slot-1").exists() and not (slots / "slot-2").exists()


def test_a_killed_bank_is_reclaimed_whole(
    lease_dir: Callable[[], Path], pids: Pids, scratch: Path
) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    bank, log, flag = start_bank(scratch, pids, DJB_GATE_SLOTS=2, DJB_GATE_LEASE_POLL=1)
    try:
        assert wait_for(20, lambda: "BANK_RC=0" in text(log)), text(log)
        bank.send_signal(signal.SIGTERM)
        bank.wait(timeout=20)
        knobs(DJB_GATE_SLOTS=2)
        _, said = spoken(hold.slot_holders)
        assert said.count("cleared a STALE gate slot") == 2
        assert not (slots / "slot-1").exists() and not (slots / "slot-2").exists()
    finally:
        flag.unlink(missing_ok=True)


def test_the_lock_order_is_REFUSED_not_merely_documented(lease_dir: Callable[[], Path]) -> None:
    where = lease_dir()
    _, said = refused_text(lambda: hold.acquire_slot("full", lease_first=True, lease=None))
    assert "LOCK ORDER BROKEN" in said
    assert "LEASE FIRST, THEN SLOT" in said

    lease = hold.Hold("lease", [where / hold.LEASE_FILE])
    taken, said = spoken(lambda: hold.acquire_slot("full", lease_first=True, lease=lease))
    assert "pytest slot held" in said
    assert isinstance(taken, hold.Hold)
    taken.release()


# --- the sanction valve on the full gate --------------------------------------


def valve(
    gate: Callable[..., object], checkout: Path, where: Path, *args: str, **extra: str
) -> tuple[int, str]:
    """`check.sh <args>` in a scratch checkout, its machine state in `where`; exit and output."""
    environment = {"DJB_GATE_LEASE_DIR": str(where), "DJB_GATE_CALLER": "", "CI": ""}
    environment.update(extra)
    done = gate(*args, cwd=checkout, env=environment)
    return done.rc, done.text()  # type: ignore[attr-defined]


def took_nothing(where: Path) -> None:
    """A refused run took no lease and no slot — by looking, not by its own claim."""
    assert not (where / hold.LEASE_FILE).exists()
    assert not (where / hold.SLOTS_DIR).exists()


def test_an_unsanctioned_full_gate_is_REFUSED(
    gate: Callable[..., object], checkout: Path, lease_dir: Callable[[], Path]
) -> None:
    where = lease_dir()
    rc, said = valve(gate, checkout, where, DJB_GATE_SANCTION="")
    assert rc == 2
    for needle in (
        "REFUSING an unsanctioned FULL gate",
        "the pre-push hook",
        "--bank",
        "DJB_GATE_SANCTION",
        "Nothing was judged",
    ):
        assert needle in said
    took_nothing(where)


def test_a_shapeless_sanction_is_REFUSED(
    gate: Callable[..., object], checkout: Path, lease_dir: Callable[[], Path]
) -> None:
    where = lease_dir()
    rc, said = valve(gate, checkout, where, DJB_GATE_SANCTION="nope")
    assert rc == 2
    assert "DJB_GATE_SANCTION is set but is not a sanction" in said
    assert "want: DJB_GATE_SANCTION=" in said
    took_nothing(where)

    where = lease_dir()
    rc, said = valve(gate, checkout, where, DJB_GATE_SANCTION="gate-rung:")
    assert rc == 2 and "is not a sanction" in said
    took_nothing(where)

    where = lease_dir()
    rc, said = valve(gate, checkout, where, DJB_GATE_SANCTION="")
    assert rc == 2 and "REFUSING an unsanctioned FULL gate" in said
    took_nothing(where)


def test_a_sanction_under_the_floor_is_REFUSED(
    gate: Callable[..., object], checkout: Path, lease_dir: Callable[[], Path]
) -> None:
    where = lease_dir()
    rc, said = valve(gate, checkout, where, DJB_GATE_SANCTION="x: y")
    assert rc == 2
    assert "the sanction's reason is 1 character(s)" in said
    assert "at least 12 characters" in said
    assert "Nothing was judged" in said
    took_nothing(where)


def git_dirs(tree: Path) -> tuple[str, str]:
    """A linked worktree's own git dir and its common dir, as git reports them."""
    own = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    common = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert own and common and own != common, (own, common)
    return own, common


def test_bank_from_a_LINKED_worktree_is_REFUSED(
    gate: Callable[..., object],
    checkout: Path,
    lease_dir: Callable[[], Path],
    scratch_repo: Callable[..., Path],
) -> None:
    repo = scratch_repo()
    linked = repo.parent / "repo-linked"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(linked)], check=True
    )
    own, common = git_dirs(linked)
    where = lease_dir()
    rc, said = valve(
        gate,
        checkout,
        where,
        "--bank",
        DJB_GATE_SANCTION="",
        GIT_DIR=own,
        GIT_COMMON_DIR=common,
        GIT_WORK_TREE=str(linked),
    )
    assert rc == 2
    assert "--bank from a LINKED worktree" in said
    assert "git-common-dir:" in said
    assert "DJB_GATE_SANCTION=" in said
    took_nothing(where)


def test_bank_from_a_worktree_merely_NAMED_pm_push_is_REFUSED(
    gate: Callable[..., object],
    checkout: Path,
    lease_dir: Callable[[], Path],
    scratch_repo: Callable[..., Path],
) -> None:
    repo = scratch_repo()
    decoy = repo.parent / "repo-wt" / "pm-push"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "rung-decoy", str(decoy)],
        check=True,
    )
    own, common = git_dirs(decoy)
    top = subprocess.run(
        ["git", "-C", str(decoy), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    ).stdout.strip()
    head = subprocess.run(
        ["git", "-C", str(decoy), "symbolic-ref", "-q", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert Path(top).name == "pm-push"
    assert head == "refs/heads/rung-decoy"
    where = lease_dir()
    rc, said = valve(
        gate,
        checkout,
        where,
        "--bank",
        DJB_GATE_SANCTION="",
        GIT_DIR=own,
        GIT_COMMON_DIR=common,
        GIT_WORK_TREE=str(decoy),
    )
    assert rc == 2
    for needle in ("--bank from a LINKED worktree", "HEAD:", "refs/heads/rung-decoy", "DETACHED"):
        assert needle in said
    took_nothing(where)


def test_an_unknown_flag_is_still_exit_2(
    gate: Callable[..., object], checkout: Path, lease_dir: Callable[[], Path]
) -> None:
    where = lease_dir()
    rc, said = valve(gate, checkout, where, "--bnak")
    assert rc == 2
    assert "unknown argument '--bnak'" in said
    assert "--bank" in said
    rc, said = valve(gate, checkout, where, "--fast", "--bank")
    assert rc == 2
    assert "unexpected extra arguments" in said


# --- the ledger's caller and sanction fields, through the Python writer -----------------------

SANCTION = verdicts.Sanction(
    "typed", "gate-rung", "quality/** rung — the canary self-test is the point"
)


def test_the_ledger_row_carries_the_sanction(
    scratch_repo: Callable[..., Path], scratch_ledger: Path
) -> None:
    repo = scratch_repo()
    tree = verdicts.measured_tree(repo)
    verdicts.record_full(
        repo, tree=tree, legs="ruff,mypy", caller="quality-rung", sanction=SANCTION
    )
    row = verdicts.consult(repo, tree)
    assert row is not None
    line = verdicts.format(row)
    assert "caller=quality-rung" in line
    assert (
        "sanction=typed:gate-rung:quality/**%20rung%20—%20the%20canary%20self-test%20is%20the%20point"
        in line
    )
    old = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    with scratch_ledger.open("a") as out:
        out.write(f"v1 {old} full 2026-08-20T10:00:00Z ruff,mypy caller=push-wall\n")
    honoured = verdicts.consult(repo, old)
    assert honoured is not None and honoured.get("sanction") is None


def test_the_caller_vocabulary_is_closed() -> None:
    said: list[str] = []
    for caller in ("push-wall", "quality-rung", "pm-bank", "main-loop", "unstated"):
        assert verdicts.caller_kind(caller, said.append) == caller
    assert verdicts.caller_kind("", said.append) == "unstated"
    assert verdicts.caller_kind(None, said.append) == "unstated"
    assert said == []
    assert verdicts.caller_kind("whoever", said.append) == "unstated"
    assert len(said) == 1 and "is not one of" in said[0]


def test_the_ledger_and_run_log_carry_the_caller(
    scratch_repo: Callable[..., Path], scratch_ledger: Path
) -> None:
    repo = scratch_repo()
    tree = verdicts.measured_tree(repo)
    verdicts.record_full(
        repo, tree=tree, legs="ruff,mypy", caller="quality-rung", sanction=SANCTION
    )
    row = verdicts.consult(repo, tree)
    assert row is not None and row.get("caller") == "quality-rung" and row.key == tree
    verdicts.run_note(repo, tree, "red:pytest-x2", caller="pm-bank")
    run = verdicts.last(scratch_ledger, "run", tree)
    assert run is not None and run.get("caller") == "pm-bank"
    assert verdicts.run_lookup(repo, tree) == "red:pytest-x2"


def test_a_pre_N353_line_still_parses(
    scratch_repo: Callable[..., Path], scratch_ledger: Path
) -> None:
    repo = scratch_repo()
    tree = verdicts.measured_tree(repo)
    scratch_ledger.write_text(f"v1 {tree} full 2026-08-20T10:00:00Z ruff,mypy\n")
    assert verdicts.consult(repo, tree) is not None
    (scratch_ledger.parent / "djb-gate-runs").write_text(
        f"v1 {tree} 2026-08-20T10:00:00Z killed:pytest-x2\n"
    )
    assert verdicts.run_lookup(repo, tree) == "killed:pytest-x2"


def test_the_workers_sentence_is_true_in_both_cases(lease_dir: Callable[[], Path]) -> None:
    lease_dir()
    _, _, phrase = hold.worker_count(2, out=io.StringIO())
    assert "one share per pytest slot" in phrase
    env.unset("DJB_GATE_SLOT_WORKERS")
    knobs(DJB_GATE_SLOT_WORKERS=1)
    _, _, phrase = hold.worker_count(2, out=io.StringIO())
    assert "typed: DJB_GATE_SLOT_WORKERS" in phrase and "cores split" not in phrase
    env.unset("DJB_GATE_SLOT_WORKERS")
    knobs(DJB_GATE_SLOTS=2)
    taken, _ = spoken(lambda: hold.acquire_slot("bank"))
    assert isinstance(taken, hold.Hold)
    assert "bank: every slot — 2/2; loops wait" in taken.phrase
    taken.release()


def test_the_bank_announcement_names_every_slot() -> None:
    said = push.MAC_ARM
    assert "EVERY pytest slot" in said
    assert "--loop" in said
    assert "DJB_BANK_SHARES_SLOTS=1" in said
    assert "one pytest slot" not in said


def test_the_declared_limit_is_written_down() -> None:
    said = text(Path(hold.__file__))
    for needle in (
        "ONE MACHINE",
        "cross-machine CI runners were never this lease's scope",
        "TRUST CLASS",
        "THE LOCK ORDER",
        "a bare `pytest`",
        "another host's record",
        "the mkdir/holder window",
        "one machine-wide directory, not per repository",
    ):
        assert needle in said


def test_gate_lease_sh_is_a_library_not_an_instrument() -> None:
    package = Path(hold.__file__).parent
    for module in (Path(hold.__file__), Path(env.__file__)):
        assert not module.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    assert "__main__" not in text(Path(env.__file__))
    assert text(Path(hold.__file__)).count('if __name__ == "__main__":') == 1
    reads = set()
    for module in sorted(package.glob("*.py")):
        if module.name == "env.py":
            continue
        for node in ast.walk(ast.parse(text(module))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"DJB_[A-Z0-9_]+|SECRETS_SCAN_BASE_REF", node.value):
                    reads.add(node.value)
    assert reads == set(env.NAMES), (sorted(reads), sorted(env.NAMES))
    floor = "/usr/bin/python3" if os.access("/usr/bin/python3", os.X_OK) else sys.executable
    done = subprocess.run(
        [floor, "-E", "-S", "-c", "import sys; sys.path.insert(0, '.'); import quality.djb.hold"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


# --- the holder, in words --------------------------------------------------------


def test_the_slot_wait_names_its_holder_in_words(lease_dir: Callable[[], Path], pids: Pids) -> None:
    for mode, nominal in (("full", 15), ("loop", 4)):
        slots = lease_dir() / hold.SLOTS_DIR
        holder = pids.live()
        plant_slot(slots, 1, holder, mode=mode)
        knobs(
            DJB_GATE_SLOTS=1,
            DJB_GATE_SLOT_MAX_WAIT=3,
            DJB_GATE_LEASE_POLL=1,
            DJB_GATE_LEASE_ANNOUNCE=1,
        )
        _, said = refused_text(lambda: hold.acquire_slot("loop"))
        assert "... still waiting for a pytest slot: " in said
        assert f"— holder pid {holder} {mode} (slot-1)" in said
        assert ", started 00:00Z" in said
        assert f"of a nominal {nominal} left)" in said
    verbatim = hold.slot_holder_phrase("slot-2 (starting — no holder record yet)")
    assert "slot-2 (starting" in verbatim and "pid " not in verbatim


def test_the_lease_wait_names_its_holder_in_words(
    lease_dir: Callable[[], Path], pids: Pids
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    holder = pids.live()
    lease.write_text(
        lease_record(holder, epoch=str(int(time.time()) - 300), stamp="2026-08-25T14:02:00Z")
    )
    knobs(DJB_GATE_LEASE_MAX_WAIT=3, DJB_GATE_LEASE_POLL=1, DJB_GATE_LEASE_ANNOUNCE=1)
    _, said = refused_text(hold.acquire_lease)
    assert "... still waiting for the full-gate lease: " in said
    assert f"— holder pid {holder} full, started 14:02Z (~10 min of a nominal 15 left)" in said


def test_the_pytest_leg_prints_its_nominal_and_where_it_came_from(scratch: Path) -> None:
    said = io.StringIO()
    hold.nominal(240, "NOMINAL_LOOP", [], out=said)
    assert "nominal:    4m (typed, hold.py NOMINAL_LOOP)" in said.getvalue()

    ledger = scratch / "ledger-took"
    ledger.write_text(
        "v1 deadbeef full 2026-09-01T00:00:00Z ruff caller=push-wall waited=0 took=600\n"
        "v1 cafebabe full 2026-09-02T00:00:00Z ruff caller=push-wall waited=12 took=1380\n"
    )
    said = io.StringIO()
    hold.nominal(900, "NOMINAL_FULL", ledger.read_text().splitlines(), out=said)
    assert "nominal:    23m (this checkout's last banked took=)" in said.getvalue()

    ledger.write_text("v1 deadbeef full 2026-08-20T10:00:00Z ruff,mypy caller=push-wall\n")
    said = io.StringIO()
    hold.nominal(900, "NOMINAL_FULL", ledger.read_text().splitlines(), out=said)
    assert "nominal:    15m (typed, hold.py NOMINAL_FULL)" in said.getvalue()


def test_the_full_verdict_row_records_what_the_run_COST(
    scratch_repo: Callable[..., Path], scratch_ledger: Path
) -> None:
    repo = scratch_repo()
    tree = verdicts.measured_tree(repo)
    wall = verdicts.Sanction("push-wall", "push-wall", "the push wall")
    verdicts.record_full(
        repo,
        tree=tree,
        legs="ruff,mypy",
        caller="push-wall",
        sanction=wall,
        waited=7 + 5,
        took=613,
    )
    cost = verdicts.consult(repo, tree)
    assert cost is not None and (cost.get("waited"), cost.get("took")) == ("12", "613")
    zero = "feedfacefeedfacefeedfacefeedfacefeedface"
    verdicts.record_full(repo, tree=zero, legs="ruff", caller="push-wall", sanction=wall)
    assert " waited=0 took=0" in verdicts.format(verdicts.consult(repo, zero) or cost)
    both = "0123456789012345678901234567890123456789"
    verdicts.record_full(
        repo, tree=both, legs="ruff", caller="quality-rung", sanction=SANCTION, took=42
    )
    line = verdicts.format(verdicts.consult(repo, both) or cost)
    assert "sanction=typed:gate-rung:quality/**%20rung" in line and "took=42" in line


# --- the module's own listing, and the gate-text censuses ---------------------------


def test_list_mode_is_not_a_run_that_died(capture: Callable[..., object]) -> None:
    done = capture(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:django",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-W",
            "ignore::pytest.PytestConfigWarning",
            str(Path(__file__)),
        ],
        cwd=ROOT,
    )
    listing = done.text()  # type: ignore[attr-defined]
    assert done.rc == 0, listing  # type: ignore[attr-defined]
    named = re.findall(r"::(test_[A-Za-z0-9_]+)", listing)
    assert named and len(named) == len(set(named))
    preamble = text(ROOT / "scripts" / "tests" / "drive_preamble.sh")
    assert "DRIVE_LIST_MODE" in preamble
    assert (
        'if [ "${DRIVE_OPTED_IN_TO_FINISH:-0}" = "1" ] && [ "${DRIVE_LIST_MODE:-0}" != "1" ] &&'
        in preamble
    )
    assert "IT DISARMS ONE CHECK AND NOTHING ELSE" in preamble


def test_every_in_process_banner_names_its_cause() -> None:
    inproc, missing = 0, []
    for module in ("modes.py", "loop.py"):
        lines = text(ROOT / "quality" / "djb" / module).splitlines()
        for n, line in enumerate(lines):
            if "see above" not in line:
                continue
            inproc += 1
            if not any("cause: {exc}" in x for x in lines[n + 1 : n + 4]):
                missing.append(f"{module}:{n + 1}")
    assert not missing, f"in-process banners with no cause line: {missing}"
    assert inproc >= 2


SEAM_SOURCE = re.compile(r"(^|[^A-Za-z0-9_/])\.\s[^;]*gate_refuse\.sh")
WHOLE_TREE = re.compile(r"(git clone|cp -[aRr]|rsync)")


def seam_census(drives: list[Path]) -> tuple[list[str], list[str]]:
    """The libraries that source the refusal seam, and each drive copy site's disposition."""
    libraries = []
    for library in sorted((ROOT / "scripts").glob("*.sh")):
        if library.name == "gate_refuse.sh":
            continue
        stripped = "\n".join(line.split("#", 1)[0] for line in text(library).splitlines())
        if any(SEAM_SOURCE.search(line) for line in stripped.splitlines()):
            libraries.append(library.stem)
    if not libraries:
        return [], []
    copies = re.compile(r"cp .*/(" + "|".join(map(re.escape, libraries)) + r")\.sh")
    found = []
    for drive in drives:
        body = text(drive)
        for number, line in enumerate(body.splitlines(), 1):
            if not copies.search(line):
                continue
            dest = line.rsplit(" ", 1)[-1].strip('"')
            if "/scripts/" not in dest:
                found.append(f"TEXT-TARGET {drive}:{number} {dest}")
                continue
            prefix = dest.split("/scripts/", 1)[0]
            wide = [x for x in body.splitlines() if WHOLE_TREE.search(x)]
            if f"{prefix}/scripts/gate_refuse.sh" in body:
                found.append(f"SEAM {drive}:{number} {dest}")
            elif any(prefix in x for x in wide):
                found.append(f"WHOLE-TREE {drive}:{number} {dest}")
            else:
                found.append(f"OFFENDER {drive}:{number} {dest}")
    return libraries, found


def test_every_fixture_that_copies_a_seam_library_copies_the_seam(scratch: Path) -> None:
    drives = sorted((ROOT / "scripts" / "tests").glob("*.sh")) + sorted(
        (ROOT / "deploy" / "tests").glob("*.sh")
    )
    libraries, found = seam_census(drives)
    assert libraries, "no library in scripts/ sources the refusal seam"
    assert not [x for x in found if x.startswith("OFFENDER ")]

    copy = f'cp "$ROOT/scripts/{libraries[0]}.sh" "$REPO/scripts/{libraries[0]}.sh"\n'
    planted = scratch / "planted_drive.sh"
    planted.write_text(copy)
    _, found = seam_census([planted])
    assert any(x.startswith(f"OFFENDER {planted}:") for x in found), found
    planted.write_text(copy + 'cp "$ROOT/scripts/gate_refuse.sh" "$REPO/scripts/gate_refuse.sh"\n')
    _, found = seam_census([planted])
    assert any(x.startswith(f"SEAM {planted}:") for x in found), found


# --- the CLI, and `gate_lease.sh`'s wrapper lines over it ----------------------------

LEASE_SH = ROOT / "scripts" / "gate_lease.sh"
WRAPPER = re.compile(r'^(gate_[a-z_]+)\(\) \{ gate_hold_cli (gate_[a-z_]+) "\$@"; \}$')
SOURCE = f". {ROOT}/scripts/gate_lease.sh || exit 2\n"


def cli(*argv: str) -> subprocess.CompletedProcess[str]:
    """`python -m quality.djb.hold <argv>` with both streams through pipes, outside CI."""
    return subprocess.run(
        [sys.executable, "-m", "quality.djb.hold", *argv],
        cwd=ROOT,
        env={name: value for name, value in os.environ.items() if name != "CI"},
        capture_output=True,
        text=True,
    )


def test_every_function_gate_lease_sh_exports_is_one_line_over_its_verb() -> None:
    lines = text(LEASE_SH).splitlines()
    defined, wrapped = [], {}
    for number, line in enumerate(lines):
        found = re.match(r"^([a-z_]+)\(\) *\{", line)
        if not found:
            continue
        defined.append(found.group(1))
        wrapper = WRAPPER.match(line)
        if wrapper:
            wrapped[wrapper.group(1)] = wrapper.group(2)
            assert lines[number - 1].startswith("# rule-84: superseded by quality/djb/hold.py::"), (
                lines[number - 1]
            )
    assert set(defined) - set(wrapped) == {"gate_hold_cli"}
    assert all(name == verb for name, verb in wrapped.items()), wrapped
    assert set(wrapped) == set(hold.VERBS)


def test_a_slot_taken_through_the_wrapper_is_the_shells_until_it_gives_it_back(
    capture: Callable[..., object], lease_dir: Callable[[], Path], scratch: Path
) -> None:
    slots = lease_dir() / hold.SLOTS_DIR
    knobs(DJB_GATE_SLOTS=2)
    rc, said = bash(
        capture,
        SOURCE
        + "gate_slot_acquire loop || exit 3\n"
        + 'echo "SHELL=$$ SLOT=$GATE_SLOT TOTAL=$GATE_SLOT_TOTAL"\n'
        + 'echo "WORKERS=$GATE_SLOT_WORKERS EXPORTED=$DJB_GATE_SLOT_WORKERS"\n'
        + 'awk \'{print "RECORD=" $1}\' "$GATE_SLOT/holder"\n'
        + "gate_slot_holders\n"
        + "gate_slot_release\n"
        + 'echo "AFTER=[$GATE_SLOT] [${DJB_GATE_SLOT_WORKERS-unset}]"\n',
        scratch,
    )
    assert rc == 0, said
    shell = re.search(r"SHELL=(\d+) SLOT=(\S+) TOTAL=2", said)
    assert shell, said
    assert f"RECORD={shell.group(1)}" in said
    assert f"slot-1 {shell.group(1)} loop " in said
    assert "cleared a STALE" not in said
    share = str(hold.slot_workers(2, io.StringIO()))
    assert f"WORKERS={share} EXPORTED={share}" in said
    assert "AFTER=[] [unset]" in said
    assert not (slots / "slot-1").exists()


def test_a_lease_taken_through_the_wrapper_outlives_the_cli_and_names_the_shell(
    capture: Callable[..., object], lease_dir: Callable[[], Path], scratch: Path
) -> None:
    lease = lease_dir() / hold.LEASE_FILE
    rc, said = bash(
        capture,
        SOURCE
        + "gate_lease_acquire || exit 3\n"
        + 'echo "SHELL=$$ LEASE=$GATE_LEASE WAITED=$GATE_LEASE_WAITED"\n'
        + "gate_lease_holder\n"
        + "gate_lease_release\n"
        + 'echo "AFTER=[$GATE_LEASE]"\n',
        scratch,
    )
    assert rc == 0, said
    shell = re.search(rf"SHELL=(\d+) LEASE={re.escape(str(lease))} WAITED=0", said)
    assert shell, said
    assert f"full-gate lease held for this MACHINE (pid {shell.group(1)})" in said
    assert re.search(rf"^{shell.group(1)} full ", said, re.M), said
    assert "AFTER=[]" in said and not lease.exists()


def test_a_refusal_through_the_wrapper_is_the_shells_cause_and_exit(
    capture: Callable[..., object], scratch: Path
) -> None:
    rc, said = bash(
        capture,
        SOURCE
        + "rc=0; DJB_GATE_LEASE_DIR=some/relative gate_lease_path || rc=$?\n"
        + 'echo "RC=$rc CAUSE=$GATE_LAST_REFUSAL"\n'
        + "rc=0; DJB_GATE_SLOTS=bogus gate_slots_total || rc=$?\n"
        + 'echo "RC=$rc CAUSE=$GATE_LAST_REFUSAL"\n',
        scratch,
    )
    assert rc == 0, said
    assert "RC=1 CAUSE=DJB_GATE_LEASE_DIR is relative ('some/relative')" in said
    assert "RC=2 CAUSE=DJB_GATE_SLOTS='bogus' is not a positive whole number." in said


def test_a_waiting_verb_refuses_a_pipe_and_a_reading_verb_answers_through_one(
    lease_dir: Callable[[], Path],
) -> None:
    lease_dir()
    waits = cli("gate_slot_acquire", "loop")
    assert waits.returncode == 2
    assert "!! gate_slot_acquire refuses pipes — run it bare or redirect to a file." in (
        waits.stderr
    )
    assert waits.stdout == ""
    reads = cli("gate_slots_total")
    assert reads.returncode == 0 and reads.stdout.strip().isdigit(), reads.stderr


def test_an_unknown_verb_is_exit_2_naming_every_verb() -> None:
    done = cli("gate_lease_steal")
    assert done.returncode == 2
    assert "!! hold: no verb 'gate_lease_steal'" in done.stderr
    assert all(f"   {verb}" in done.stderr for verb in hold.VERBS)


# --- the host slot ------------------------------------------------------

WAITER = """
import sys
from quality.djb import hold
taken = hold.acquire_host_slot(sys.argv[1])
print(f"TOOK {taken.slot or 'ride'}", flush=True)
"""


def plant_host(slots: Path, number: int, pid: int, held_for: int = 130) -> None:
    """A host-slot holder as `hold.record` writes one, `held_for` seconds old, from `c<n>`."""
    slot = slots / f"slot-{number}"
    slot.mkdir(parents=True, exist_ok=True)
    started = int(time.time()) - held_for
    (slot / "holder").write_text(
        f"{pid} fast 2026-10-22T00:00:00Z {HOST} {started} /checkouts/c{number}"
        f" machine={hold.machine_id()}\n"
    )


def start_waiter(
    scratch: Path, pids: Pids, mode: str = "fast"
) -> tuple[subprocess.Popen[bytes], Path]:
    """`acquire_host_slot(mode)` in its own process, its output in a log."""
    log = scratch / f"waiter-{time.monotonic_ns()}.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", WAITER, mode],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    return pids.keep(child), log


def test_the_fourth_gate_WAITS_for_a_host_slot_and_names_the_three(
    lease_dir: Callable[[], Path], pids: Pids, scratch: Path
) -> None:
    slots = lease_dir() / hold.HOST_SLOTS_DIR
    holders = [pids.live() for _ in range(3)]
    for number, pid in enumerate(holders, 1):
        plant_host(slots, number, pid)
    knobs(DJB_GATE_LEASE_POLL=1, DJB_GATE_LEASE_ANNOUNCE=1)
    waiter, log = start_waiter(scratch, pids)
    assert wait_for(30, lambda: text(log).count("WAITING for a host slot") >= 2), text(log)
    said = text(log)
    assert "(3 of 3 held, DJB_GATE_HOST_SLOTS)" in said
    for number, pid in enumerate(holders, 1):
        assert f"/checkouts/c{number} pid {pid} fast held 2m" in said, said
    assert waiter.poll() is None, "a waiter is never refused for waiting"
    assert "TOOK" not in said and "REFUSING" not in said


def test_a_dead_host_slot_holder_is_reaped_and_the_waiter_proceeds(
    lease_dir: Callable[[], Path], pids: Pids, scratch: Path
) -> None:
    slots = lease_dir() / hold.HOST_SLOTS_DIR
    holders = [pids.live() for _ in range(3)]
    for number, pid in enumerate(holders, 1):
        plant_host(slots, number, pid)
    knobs(DJB_GATE_LEASE_POLL=1, DJB_GATE_LEASE_ANNOUNCE=1)
    waiter, log = start_waiter(scratch, pids)
    assert wait_for(30, lambda: "WAITING for a host slot" in text(log)), text(log)
    victim = pids.started[1]
    victim.kill()
    victim.wait()
    assert waiter.wait(timeout=30) == 0, text(log)
    said = text(log)
    assert f"cleared a STALE host slot — pid {holders[1]} is not running" in said
    assert "host slot ACQUIRED after" in said and "TOOK slot-2" in said

    plant_host(slots, 2, pids.dead())
    taken, said = spoken(lambda: hold.acquire_host_slot("fast"))
    assert "cleared a STALE host slot" in said and "WAITING" not in said
    assert isinstance(taken, hold.Hold) and taken.slot == "slot-2"
    taken.release()
    assert not (slots / "slot-2").exists()


def test_a_gate_nested_under_a_host_slot_holder_rides_it(
    lease_dir: Callable[[], Path], pids: Pids, scratch: Path
) -> None:
    slots = lease_dir() / hold.HOST_SLOTS_DIR
    plant_host(slots, 1, os.getpid())
    knobs(DJB_GATE_HOST_SLOTS=1, DJB_GATE_LEASE_POLL=1)
    waiter, log = start_waiter(scratch, pids)
    assert waiter.wait(timeout=30) == 0, text(log)
    assert f"riding the parent gate's /checkouts/c1 pid {os.getpid()}" in text(log)
    assert "TOOK ride" in text(log)


def test_the_host_slot_keeps_THE_LOCK_ORDER(lease_dir: Callable[[], Path]) -> None:
    where = lease_dir()
    for mode in ("full", "bank"):
        _, said = refused_text(functools.partial(hold.acquire_host_slot, mode))
        assert "LOCK ORDER BROKEN" in said and "LEASE, THEN HOST SLOT, THEN PYTEST" in said
    lease = hold.Hold("lease", [where / hold.LEASE_FILE])
    taken, _ = spoken(lambda: hold.acquire_host_slot("full", lease=lease))
    assert isinstance(taken, hold.Hold) and taken.slot == "slot-1"
    taken.release()
    full = text(ROOT / "quality" / "djb" / "modes.py")
    found = [re.search(rf'hold\.hold\(\s*"{s}"', full) for s in ("lease", "host", "checkout")]
    order = [match.start() for match in found if match]
    assert len(order) == 3, found
    assert order == sorted(order), order
    assert "THE LOCK ORDER: lease, then host slot, then pytest slot" in text(LEASE_SH)


def test_every_gate_mode_takes_the_host_slot_and_gives_it_back() -> None:
    for module, function in (
        ("cli.py", "run_fast"),
        ("loop.py", "_measure"),
        ("modes.py", "run_full"),
    ):
        tree = ast.parse(text(ROOT / "quality" / "djb" / module))
        body = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        )
        said = ast.unparse(body)
        assert "hold.hold('host'" in said, (module, function)
        assert ".release()" in said, (module, function)


def test_the_host_slot_count_is_typed_or_three(lease_dir: Callable[[], Path]) -> None:
    lease_dir()
    assert hold.host_slots_total() == hold.HOST_SLOTS == 3
    knobs(DJB_GATE_HOST_SLOTS=1)
    assert hold.host_slots_total() == 1
    for bad in ("0", "lots"):
        knobs(DJB_GATE_HOST_SLOTS=bad)
        _, said = refused_text(hold.host_slots_total)
        assert "is not a whole number of at least 1" in said
    assert hold.host_slots_dir().parent == hold.lease_path().parent
