"""The machine's gate guards — lease, host slots, pytest slots, checkout lock — one acquire."""

# does-not-cover: another machine — the lease serializes full gates on ONE MACHINE only.
# does-not-cover: CI — cross-machine CI runners were never this lease's scope.
# does-not-cover: sabotage — the TRUST CLASS is a local file one `rm` away, one export away.
# does-not-cover: a bare `pytest` — it takes no slot; only the legs the gate starts count.
# does-not-cover: fairness — waiters race for what frees; exclusivity is the property.
# does-not-cover: another host's record — never cleared, judged by machine id; waited on, refused.
# does-not-cover: an `/etc/machine-id` cloned across hosts (an image) — one id, two machines.
# does-not-cover: the mkdir/holder window — a slot without a record is held for two minutes.
# does-not-cover: `--leg`, `--census`, `--list-legs` and a dry run — they take no host slot.

from __future__ import annotations

import functools
import io
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from apps.core.roads import road
from quality.could_not_look import CouldNotLook
from quality.djb import env

DEFAULT_DIR = "/tmp"  # noqa: S108 — the lease directory every gate process and shell script agrees on
LEASE_MAX_WAIT = 3600
SLOT_MAX_WAIT = 3600
POLL = 5
ANNOUNCE = 60
#: Nominal lengths turn a holder's elapsed time into a waiter's "~N min"; nothing decides on them.
NOMINAL_FULL = 900
NOMINAL_LOOP = 240
CORES_PER_SLOT = 5
#: Seconds a holderless slot directory counts as a claim still being written.
ORPHAN_AGE = 120
LEASE_FILE = "djb-gate-lease"
SLOTS_DIR = "djb-gate-slots"
HOST_SLOTS_DIR = "djb-gate-host-slots"
#: Whole gates (`--fast`, `--loop`, full, bank) that may run at once on this machine.
HOST_SLOTS = 3
#: Seconds between a host-slot waiter's lines.
HOST_ANNOUNCE = 30
LOCK_FILE = "djb-gate-lock"
RECORD_FIELDS = "(pid mode started-utc host started-epoch checkout machine=<id>)"
#: Where a Linux machine keeps its stable id; Darwin answers `IOPlatformUUID` instead.
MACHINE_ID_FILE = "/etc/machine-id"
#: The tag a record's machine id field carries; a record without one is a legacy record.
MACHINE_TAG = "machine="
_PLATFORM_UUID = re.compile(r'"IOPlatformUUID" = "([^"]+)"')
#: The legacy records this process has already explained, so each is explained once.
_EXPLAINED: set[Path] = set()
_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:")
#: The pid a holder record names: the calling shell's under the CLI (`--pid`), else this process's.
_HOLDER_PID: int | None = None
_TOOK = re.compile(r" took=[0-9]+")


class Refused(CouldNotLook):
    """A guard that could not be taken or used: exit 2; `cause` is the line a banner prints."""

    def __init__(self, cause: str, *detail: str) -> None:
        super().__init__("\n".join((cause, *detail)))
        self.cause = cause


@dataclass
class Hold:
    """What one acquire took: its scope, the paths it holds, its wait and its share."""

    scope: str
    paths: list[Path] = field(default_factory=list)
    waited: int = 0
    total: int = 0
    workers: int = 0
    provenance: str = ""
    phrase: str = ""

    @property
    def slot(self) -> str:
        """The first slot's name (`slot-<n>`), or empty."""
        return self.paths[0].name if self.paths else ""

    def release(self) -> None:
        """Give back every path whose record names this process, and nothing else."""
        seen = set()
        for path in self.paths:
            if path in seen:
                continue
            seen.add(path)
            record = path / "holder" if self.scope in ("slot", "host") else path
            if _field(_first_line(record), 0) == str(holder_pid()):
                if self.scope in ("slot", "host"):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    _unlink(path)
        self.paths = []
        if self.scope == "slot":
            env.unset("DJB_GATE_SLOT_WORKERS")


def _streams(out: TextIO | None, err: TextIO | None) -> tuple[TextIO, TextIO]:
    return (out or sys.stdout, err or sys.stderr)


def _say(stream: TextIO, *lines: str) -> None:
    for line in lines:
        stream.write(line + "\n")
    stream.flush()


def _refuse(err: TextIO, cause: str, *detail: str) -> Refused:
    _say(err, f"!! {cause}", *detail)
    return Refused(cause, *detail)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _first_line(path: Path) -> str:
    try:
        with path.open() as handle:
            return handle.readline().rstrip("\n")
    except OSError:
        return ""


def _field(line: str, index: int) -> str:
    parts = line.split()
    return parts[index] if index < len(parts) else ""


def _seconds(name: str, default: int, err: TextIO) -> int:
    text = env.read(name, str(default)) or str(default)
    try:
        return int(text)
    except ValueError:
        raise _refuse(err, f"{name}='{text}' is not a whole number of seconds.") from None


def host() -> str:
    """This machine's short host name, as `hostname -s` prints it."""
    return socket.gethostname().split(".")[0] or "host"


def _platform_uuid() -> str:
    """Darwin's `IOPlatformUUID` from `ioreg`, or empty where there is none."""
    try:
        done = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    found = _PLATFORM_UUID.search(done.stdout)
    return found.group(1) if found else ""


@road(
    "machine_id",
    example="quality/tests/test_hold.py::test_a_dead_holder_of_this_machine_is_cleared_whatever_its_host_name_was",
)
@functools.lru_cache(maxsize=1)
def machine_id(err: TextIO | None = None) -> str:
    """This machine's id: `/etc/machine-id`, else `IOPlatformUUID`, else the host name, aloud."""
    try:
        found = Path(MACHINE_ID_FILE).read_text().strip()
    except OSError:
        found = ""
    found = found or _platform_uuid()
    if found:
        return found.split()[0]
    _, err = _streams(None, err)
    _say(
        err,
        f"  note: no machine id ({MACHINE_ID_FILE} unreadable, no IOPlatformUUID) — "
        f"the host name '{host()}' stands in",
    )
    return host()


def record_machine(line: str) -> str:
    """The machine id a holder record carries, or empty for a legacy record."""
    for word in line.split()[4:]:
        if word.startswith(MACHINE_TAG):
            return word[len(MACHINE_TAG) :]
    return ""


def is_foreign(line: str, path: Path, err: TextIO) -> bool:
    """Whether a record is another machine's: by id, else (legacy) by host name, explained once."""
    theirs = record_machine(line)
    if theirs:
        return theirs != machine_id()
    where = _field(line, 3)
    if not where or where == host():
        return False
    if path not in _EXPLAINED:
        _EXPLAINED.add(path)
        _say(
            err,
            f"  legacy record (no machine id): if this is your machine, remove {path} by hand",
        )
    return True


def holder_pid() -> int:
    """The pid this process takes and releases guards for."""
    return _HOLDER_PID or os.getpid()


def running(pid: str) -> bool:
    """Whether `kill -0 <pid>` would succeed here; another user's process answers no, as there."""
    if not pid.isdigit():
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _checkout() -> str:
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    top = done.stdout.strip()
    return top if done.returncode == 0 and top else os.getcwd()


def stamp() -> str:
    """Now, in UTC, as a holder record writes it."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def record(mode: str) -> str:
    """This process's holder record: `pid mode started-utc host started-epoch checkout machine=`."""
    return (
        f"{holder_pid()} {mode} {stamp()} {host()} {int(time.time())} {_checkout()} "
        f"{MACHINE_TAG}{machine_id()}"
    )


def lease_path(err: TextIO | None = None) -> Path:
    """The lease file under `DJB_GATE_LEASE_DIR`; refused when that is relative or no directory."""
    _, err = _streams(None, err)
    where = env.read("DJB_GATE_LEASE_DIR", DEFAULT_DIR) or DEFAULT_DIR
    if not where.startswith("/"):
        raise _refuse(
            err,
            f"DJB_GATE_LEASE_DIR is relative ('{where}'). The full-gate lease needs an",
            "   absolute machine-wide directory; a relative one resolves against",
            "   whatever directory the caller left behind.",
        )
    if not os.path.isdir(where):
        raise _refuse(
            err, f"DJB_GATE_LEASE_DIR ('{where}') is not a directory — no lease can be taken there."
        )
    return Path(where) / LEASE_FILE


def slots_dir(err: TextIO | None = None) -> Path:
    """The slot directory beside the lease: one machine-wide directory, not per repository."""
    return lease_path(err).parent / SLOTS_DIR


def host_slots_dir(err: TextIO | None = None) -> Path:
    """The host-slot directory beside the lease: keyed on the machine, never on a checkout."""
    return lease_path(err).parent / HOST_SLOTS_DIR


def lock_path(cwd: Path | None = None) -> Path | None:
    """This checkout's lock file in its git dir, or None outside a checkout."""
    done = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, capture_output=True, text=True
    )
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return Path(done.stdout.strip()) / LOCK_FILE


def holder_of(path: Path, noun: str, err: TextIO | None = None) -> str:
    """The holder line at `path`, or empty; this machine's dead holder is cleared, out loud."""
    _, err = _streams(None, err)
    if not path.is_file():
        return ""
    line = _first_line(path)
    pid = _field(line, 0)
    if is_foreign(line, path, err):
        return line
    if not running(pid):
        _say(err, f"  note: cleared a STALE {noun} — pid {pid or '<none>'} is not running ({path})")
        _unlink(path)
        return ""
    return line


def try_create(path: Path, noun: str, line: str, err: TextIO | None = None) -> bool:
    """THE ONE ACQUIRE: `line` linked into `path` only if absent; once more after a stale clear."""
    for _ in range(2):
        staged = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}")
        try:
            staged.write_text(line + "\n")
            try:
                os.link(staged, path)
                return True
            finally:
                _unlink(staged)
        except OSError:
            pass
        if holder_of(path, noun, err):
            return False
    return False


def estimate_minutes(line: str, nominal: int = NOMINAL_FULL) -> int | None:
    """Minutes left of `nominal` for a lease record's holder; None when field 5 is no epoch."""
    started = _field(line, 4)
    if not started.isdigit():
        return None
    left = max(0, nominal - (int(time.time()) - int(started)))
    return (left + 59) // 60


def holder_note(utc: str, epoch: str, nominal: int) -> str:
    """`, started 14:02Z (~9 min of a nominal 15 left)` — the record's human half, or less."""
    if not _UTC.match(utc):
        return ""
    clock = utc.split("T", 1)[1].rsplit(":", 1)[0]
    note = f", started {clock}Z"
    if not epoch.isdigit():
        return note
    left = max(0, nominal - (int(time.time()) - int(epoch)))
    return note + f" (~{(left + 59) // 60} min of a nominal {(nominal + 59) // 60} left)"


def lease_holder_phrase(line: str) -> str:
    """`pid 4123 full, started 14:02Z (…)` for a lease record; anything else verbatim."""
    pid = _field(line, 0)
    if not pid.isdigit():
        return line
    note = holder_note(_field(line, 2), _field(line, 4), NOMINAL_FULL)
    return f"pid {pid} {_field(line, 1)}{note}"


def slot_holder_phrase(line: str) -> str:
    """`pid 4123 loop (slot-1), started …` with the holder's own mode's nominal; else verbatim."""
    pid = _field(line, 1)
    if not pid.isdigit():
        return line
    mode = _field(line, 2)
    nominal = NOMINAL_FULL if mode in ("full", "bank") else NOMINAL_LOOP
    note = holder_note(_field(line, 3), _field(line, 5), nominal)
    return f"pid {pid} {mode} ({_field(line, 0)}){note}"


def try_lease(err: TextIO | None = None) -> Hold | None:
    """The lease without waiting: a `Hold`, or None while somebody else holds it."""
    path = lease_path(err)
    if try_create(path, "full-gate lease", record("full"), err):
        return Hold("lease", [path])
    return None


def acquire_lease(out: TextIO | None = None, err: TextIO | None = None) -> Hold:
    """The lease, waiting out loud up to `DJB_GATE_LEASE_MAX_WAIT`; refused at the ceiling."""
    out, err = _streams(out, err)
    ceiling = _seconds("DJB_GATE_LEASE_MAX_WAIT", LEASE_MAX_WAIT, err)
    poll = _seconds("DJB_GATE_LEASE_POLL", POLL, err)
    announce = _seconds("DJB_GATE_LEASE_ANNOUNCE", ANNOUNCE, err)
    path = lease_path(err)
    waited, due = 0, announce
    while True:
        taken = try_lease(err)
        if taken is not None:
            taken.waited = waited
            if waited:
                _say(
                    out,
                    f"- full-gate lease ACQUIRED after {waited}s of waiting (pid {holder_pid()})",
                )
            else:
                _say(
                    out,
                    f"- full-gate lease held for this MACHINE (pid {holder_pid()})"
                    " — another full gate here will WAIT, not fail",
                )
            return taken
        held = holder_of(path, "full-gate lease", err)
        if not held:
            continue
        if waited == 0:
            _say(
                out,
                "- WAITING for the machine-wide full-gate lease. This is not a hang.",
                f"   holder: {held}  {RECORD_FIELDS}",
                "   Two full gates on one machine contend for every core on it, so this run",
                "   waits for the machine rather than reporting the other gate's load as your",
                "   defect. Nothing is skipped by waiting; --fast and --loop take no lease.",
            )
            minutes = estimate_minutes(held)
            if minutes is not None:
                _say(
                    out,
                    f"   Rough estimate from the holder's elapsed time: ~{minutes} min."
                    " An estimate,",
                    "   not a promise — nothing here decides anything on it.",
                )
            _say(
                out,
                f"   Ceiling: {ceiling}s, after which this run REFUSES (exit 2)"
                " rather than overlapping.",
            )
        elif waited >= due:
            _say(
                out,
                f"  ... still waiting for the full-gate lease: {waited}s of {ceiling}s"
                f" — holder {lease_holder_phrase(held)}",
            )
            due = waited + announce
        if waited >= ceiling:
            raise _refuse(
                err,
                f"REFUSING: waited {waited}s for the machine-wide full-gate lease"
                " and it is still held.",
                f"   holder: {held}  {RECORD_FIELDS}",
                f"   lease:  {path}",
                "   Nothing was judged. This is could-not-look, not a red tree.",
                "   If that holder is gone the pid check should have cleared it — unless it was",
                "   written by another host, which this never clears on purpose.",
            )
        time.sleep(poll)
        waited += poll


def acquire_lock(
    cwd: Path | None = None, out: TextIO | None = None, err: TextIO | None = None
) -> Hold | None:
    """This checkout's lock, refused while another gate holds it; None when it cannot be written."""
    out, err = _streams(out, err)
    path = lock_path(cwd)
    if path is None:
        return None
    line = f"{holder_pid()} full {stamp()} {host()} {MACHINE_TAG}{machine_id()}"
    if try_create(path, "gate lock", line, err):
        _say(
            out,
            f"- gate lock held for this checkout (pid {holder_pid()})"
            " — --fast/--loop here will refuse until it clears",
        )
        return Hold("checkout", [path])
    held = holder_of(path, "gate lock", err)
    if held:
        raise _refuse(
            err,
            "REFUSING: a FULL gate is already running in THIS checkout.",
            f"   holder: {held}  (pid mode started-utc host)",
            "   Two full gates in one checkout plant canaries over each other.",
        )
    _say(err, f"  no gate lock taken — {path} could not be written; running anyway")
    return None


def cores(err: TextIO | None = None) -> int:
    """This machine's online core count; 2, said out loud, when it cannot be read."""
    _, err = _streams(None, err)
    count: int | None = None
    try:
        count = int(os.sysconf("SC_NPROCESSORS_ONLN"))
    except (ValueError, OSError, AttributeError):
        count = os.cpu_count()
    if not count or count < 1:
        _say(
            err,
            "  note: this machine's core count could not be read"
            " — assuming 2 for the gate semaphore",
        )
        return 2
    return count


def slots_total(err: TextIO | None = None) -> int:
    """How many pytest legs may run at once: `DJB_GATE_SLOTS`, or cores / 5, never below 1."""
    _, err = _streams(None, err)
    want = env.read("DJB_GATE_SLOTS")
    if want is None:
        return max(1, cores(err) // CORES_PER_SLOT)
    if not want.isdigit():
        raise _refuse(
            err,
            f"DJB_GATE_SLOTS='{want}' is not a positive whole number.",
            "   A ceiling this cannot read is a ceiling that would silently become the",
            "   default, which is the unbounded run the semaphore exists to stop.",
        )
    if int(want) < 1:
        raise _refuse(
            err,
            f"DJB_GATE_SLOTS='{want}' — a box with no slots can run no suite at all.",
            "   Set it to at least 1, or unset it and take the derived default.",
        )
    return int(want)


def slot_workers(total: int, err: TextIO | None = None) -> int:
    """One slot's `-n`: cores split `total` ways, never below 1 and never `auto`."""
    return max(1, cores(err) // total)


def worker_count(
    total: int,
    share: int | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> tuple[int, str, str]:
    """The `-n` this holder runs, its provenance and phrase, exported; a typed knob only narrows."""
    out, err = _streams(out, err)
    if share is None:
        share = slot_workers(total, err)
    want = env.read("DJB_GATE_SLOT_WORKERS")
    if want is None:
        env.export("DJB_GATE_SLOT_WORKERS", str(share))
        return share, "derived", f"this box's cores split {total} ways — one share per pytest slot"
    if not want.isdigit():
        raise _refuse(
            err,
            f"DJB_GATE_SLOT_WORKERS='{want}' is not a positive whole number.",
            "   The gate runs -n <this value> and apps/conftest.py's worker ceiling reads",
            "   the same variable, so a value neither can read is two worker counts.",
            f"   Unset it and take this slot's derived share of {share}.",
        )
    if int(want) < 1:
        raise _refuse(
            err,
            f"DJB_GATE_SLOT_WORKERS='{want}' — a pytest leg with no workers runs no suite at all.",
            f"   Set it to at least 1, or unset it and take this slot's derived share of {share}.",
        )
    if int(want) > share:
        raise _refuse(
            err,
            f"DJB_GATE_SLOT_WORKERS={want} is ABOVE this slot's share of {share}.",
            f"   This slot is one of {total} on a box with {cores(err)} cores, and the arithmetic",
            "   the semaphore keeps is N slots x cores/N workers = this machine's cores.",
            f"   Lower it to {share} or below, or raise DJB_GATE_SLOTS for fewer, larger slots.",
            "   Nothing was judged: no slot was taken and no suite started.",
        )
    provenance = f"typed: DJB_GATE_SLOT_WORKERS, at or below this slot's share of {share}"
    env.export("DJB_GATE_SLOT_WORKERS", str(int(want)))
    _say(out, f"  workers:    -n {want} ({provenance})")
    return int(want), provenance, provenance


def slot_holders(err: TextIO | None = None) -> list[str]:
    """One `slot-<n> <record>` per held slot; this host's dead or orphaned reclaimed aloud."""
    _, err = _streams(None, err)
    try:
        where = slots_dir(err)
        if not where.is_dir():
            return []
        total = slots_total(err)
    except Refused:
        return []
    return _holders(where, total, "gate slot", err)


def _holders(where: Path, total: int, noun: str, err: TextIO) -> list[str]:
    held: list[str] = []
    for number in range(1, total + 1):
        slot = where / f"slot-{number}"
        if not slot.is_dir():
            continue
        holder = slot / "holder"
        if not holder.is_file():
            try:
                age = time.time() - slot.stat().st_mtime
            except OSError:
                continue
            if age > ORPHAN_AGE:
                _say(
                    err,
                    f"  note: reclaimed an ORPHAN {noun} — {slot} has carried no holder record"
                    " for over two minutes",
                )
                shutil.rmtree(slot, ignore_errors=True)
            else:
                held.append(f"slot-{number} (starting — no holder record yet)")
            continue
        line = _first_line(holder)
        pid = _field(line, 0)
        if is_foreign(line, holder, err):
            held.append(f"slot-{number} {line}")
            continue
        if not running(pid):
            _say(
                err,
                f"  note: cleared a STALE {noun} — pid {pid or '<none>'} is not running ({slot})",
            )
            shutil.rmtree(slot, ignore_errors=True)
            continue
        held.append(f"slot-{number} {line}")
    return held


def render_holders(lines: Iterable[str]) -> list[str]:
    """The holder list as a waiter reads it: a bank's slots as one line naming the bank."""
    try:
        total: object = slots_total(io.StringIO())
    except Refused:
        total = "?"
    bank: list[str] = []
    rest: list[str] = []
    for line in lines:
        if not line:
            continue
        (bank if _field(line, 2) == "bank" else rest).append(line)
    shown = []
    if bank:
        shown.append(
            f"bank holds {len(bank)}/{total} slots — loops wait"
            f" (pid {_field(bank[0], 1)}, started {_field(bank[0], 3)})"
        )
    return shown + rest


def slot_estimate(lines: Iterable[str]) -> int | None:
    """Minutes until the soonest holder is due by its mode's nominal; None with no epoch."""
    best: int | None = None
    now = int(time.time())
    for line in lines:
        started = _field(line, 5)
        if not started.isdigit():
            continue
        nominal = NOMINAL_FULL if _field(line, 2) == "full" else NOMINAL_LOOP
        left = max(0, nominal - (now - int(started)))
        best = left if best is None or left < best else best
    return None if best is None else (best + 59) // 60


def try_slot(mode: str, taken: Hold, err: TextIO | None = None) -> bool:
    """One free slot added to `taken` without waiting; False when every slot is held."""
    _, err = _streams(None, err)
    return _try(slots_dir(err), slots_total(err), mode, taken, err)


def _try(where: Path, total: int, mode: str, taken: Hold, err: TextIO) -> bool:
    try:
        where.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise _refuse(
            err,
            f"the gate slot directory ('{where}') could not be created"
            " — no slot can be taken there.",
        ) from None
    for number in range(1, total + 1):
        slot = where / f"slot-{number}"
        try:
            slot.mkdir()
        except OSError:
            continue
        try:
            (slot / "holder").write_text(record(mode) + "\n")
        except OSError:
            pass
        taken.paths.append(slot)
        return True
    return False


def acquire_slot(
    mode: str = "loop",
    *,
    lease_first: bool = False,
    lease: Hold | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> Hold:
    """A pytest slot (`bank`: all), waiting aloud; THE LOCK ORDER: the lease first, then slot."""
    out, err = _streams(out, err)
    if lease_first and (lease is None or not lease.paths):
        raise _refuse(
            err,
            "LOCK ORDER BROKEN: a FULL gate reached the pytest slot without holding the",
            "   machine-wide exclusive lease. The order is LEASE FIRST, THEN SLOT — always,",
            "   so no slot holder ever waits for the lease and the deadlock cycle cannot form.",
            "   Nothing was judged.",
        )
    total = slots_total(err)
    taken = Hold("slot", total=total)
    whole, need, share = False, 1, None
    if mode == "bank":
        if env.read("DJB_BANK_SHARES_SLOTS") is not None:
            _say(
                out,
                "  bank shares the box: DJB_BANK_SHARES_SLOTS=1 — this bank takes ONE slot and",
                "              one share, exactly as a sanctioned full gate does. The loops beside",
                "              it keep theirs, and this run measures a box it is sharing.",
            )
        else:
            whole, need, share = True, total, cores(err)
    taken.workers, taken.provenance, taken.phrase = worker_count(total, share, out, err)
    ceiling = _seconds("DJB_GATE_SLOT_MAX_WAIT", SLOT_MAX_WAIT, err)
    poll = _seconds("DJB_GATE_LEASE_POLL", POLL, err)
    announce = _seconds("DJB_GATE_LEASE_ANNOUNCE", ANNOUNCE, err)
    due = announce
    me = str(holder_pid())
    while True:
        while len(taken.paths) < need and try_slot(mode, taken, err):
            pass
        held = len(taken.paths)
        if held >= need:
            if whole:
                taken.phrase = f"bank: every slot — {held}/{total}; loops wait"
                if taken.waited:
                    _say(
                        out,
                        f"- BANK COMPLETE after {taken.waited}s of waiting: it holds ALL {held}"
                        f" of {total} pytest slots (pid {me})",
                    )
                else:
                    _say(
                        out,
                        f"- pytest slots held: this BANK holds ALL {held} of {total}"
                        f" on this MACHINE (pid {me})",
                    )
                _say(
                    out,
                    "   Every --loop that arrives now waits for this run, and is told so by name.",
                    "   The escape, for a builder who cannot wait: DJB_BANK_SHARES_SLOTS=1.",
                )
            elif taken.waited:
                _say(
                    out,
                    f"- pytest SLOT ACQUIRED after {taken.waited}s of waiting"
                    f" ({taken.slot} of {total}, pid {me})",
                )
            else:
                _say(out, f"- pytest slot held: {taken.slot} of {total} on this MACHINE (pid {me})")
            return taken
        holders = slot_holders(err)
        if whole:
            holders = [line for line in holders if _field(line, 1) != me]
        if not holders:
            continue
        shown = render_holders(holders)
        if taken.waited == 0:
            if whole:
                _say(
                    out,
                    f"- WAITING for the REST of the box: this BANK holds {held} of {total}"
                    " pytest slots",
                    "   and is waiting for the rest, taking each as it frees. This is not a hang.",
                )
            else:
                _say(
                    out,
                    f"- WAITING for a pytest SLOT (all {total} are held). This is not a hang.",
                    "   This is the COUNTING semaphore, not the exclusive full-gate lease:",
                    "   somebody else's suite is running, not necessarily somebody else's push.",
                )
            _say(out, *(f"   holder: {line}" for line in shown))
            if any(line.startswith("slot-") for line in shown):
                _say(out, "   (slot  pid mode started-utc host started-epoch checkout)")
            _say(
                out,
                f"   Every pytest leg on this box takes one of {total} slots and runs",
                f"   -n {slot_workers(total, err)} instead of -n auto,"
                " so the workers all the live gates",
                "   have started total this machine's cores.",
            )
            minutes = slot_estimate(holders)
            if minutes is not None:
                _say(
                    out,
                    f"   Rough estimate from the holders' elapsed time: ~{minutes} min."
                    " An estimate,",
                    "   not a promise — nothing here decides anything on it.",
                )
            _say(
                out,
                f"   Ceiling: {ceiling}s, after which this run REFUSES (exit 2)"
                " rather than oversubscribing the box.",
            )
        elif taken.waited >= due:
            _say(
                out,
                f"  ... still waiting for a pytest slot: {taken.waited}s of {ceiling}s"
                f" — holder {slot_holder_phrase(shown[0])}",
                *(f"   holder {slot_holder_phrase(line)}" for line in shown[1:]),
            )
            due = taken.waited + announce
        if taken.waited >= ceiling:
            tail = [f"   holder: {line}" for line in shown] + [
                f"   slots:  {slots_dir(err)}",
                "   Nothing was judged. This is could-not-look, not a red tree.",
                "   If those holders are gone the pid check should have reclaimed their slots —",
                "   unless they were recorded by another host, which this never clears on purpose.",
            ]
            if whole:
                cause = (
                    f"REFUSING: this BANK waited {taken.waited}s for the rest of the box and still"
                    f" holds only {held} of {total} pytest slots."
                )
                _say(err, f"!! {cause}")
                taken.release()
                released = f"   the {held} slot(s) this run had taken were released."
                _say(err, released, *tail)
                raise Refused(cause, released, *tail)
            raise _refuse(
                err,
                f"REFUSING: waited {taken.waited}s for one of {total} pytest slots"
                " and the box is still full.",
                *tail,
            )
        time.sleep(poll)
        taken.waited += poll


def host_slots_total(err: TextIO | None = None) -> int:
    """How many whole gates may run at once on this machine: `DJB_GATE_HOST_SLOTS`, else 3."""
    _, err = _streams(None, err)
    want = env.read("DJB_GATE_HOST_SLOTS")
    if want is None:
        return HOST_SLOTS
    if not want.isdigit() or int(want) < 1:
        raise _refuse(
            err,
            f"DJB_GATE_HOST_SLOTS='{want}' is not a whole number of at least 1.",
            "   Unset it for the default of 3, or type how many gates run here at once.",
        )
    return int(want)


def ancestors() -> set[str]:
    """This process's ancestor pids from one `ps`; empty when `ps` cannot answer."""
    try:
        done = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    parent = dict(line.split()[:2] for line in done.stdout.splitlines() if len(line.split()) >= 2)
    found: set[str] = set()
    pid = str(os.getppid())
    while pid not in found and pid not in ("", "0", "1"):
        found.add(pid)
        pid = parent.get(pid, "")
    return found


def host_holder_phrase(line: str) -> str:
    """`/checkout pid 4123 fast held 2m10s` for a host-slot holder line; else verbatim."""
    pid, started = _field(line, 1), _field(line, 5)
    if not pid.isdigit():
        return line
    held = f" held {_minutes(int(time.time()) - int(started))}" if started.isdigit() else ""
    return f"{_field(line, 6) or '?'} pid {pid} {_field(line, 2)}{held}"


def _minutes(seconds: int) -> str:
    seconds = max(0, seconds)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def acquire_host_slot(
    mode: str,
    *,
    lease: Hold | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> Hold:
    """A host slot for one whole gate, waiting aloud, never refused for waiting."""
    # Invariant: THE LOCK ORDER — lease, host slot, pytest slot; a nested gate rides its ancestor's.
    out, err = _streams(out, err)
    if mode in ("full", "bank") and (lease is None or not lease.paths):
        raise _refuse(
            err,
            "LOCK ORDER BROKEN: a FULL gate reached the host slot without holding the",
            "   machine-wide exclusive lease. The order is LEASE, THEN HOST SLOT, THEN PYTEST",
            "   SLOT — always, so no slot holder ever waits for the lease. Nothing was judged.",
        )
    total = host_slots_total(err)
    where = host_slots_dir(err)
    poll = _seconds("DJB_GATE_LEASE_POLL", POLL, err)
    announce = _seconds("DJB_GATE_LEASE_ANNOUNCE", HOST_ANNOUNCE, err)
    taken = Hold("host", total=total)
    lineage: set[str] | None = None
    due = 0
    while True:
        if _try(where, total, mode, taken, err):
            if taken.waited:
                _say(out, f"- host slot ACQUIRED after {taken.waited}s: {taken.slot} of {total}")
            return taken
        holders = _holders(where, total, "host slot", err)
        if len(holders) < total:
            continue
        lineage = ancestors() if lineage is None else lineage
        rides = [line for line in holders if _field(line, 1) in lineage]
        if rides:
            _say(out, f"- host slot: riding the parent gate's {host_holder_phrase(rides[0])}")
            return Hold("host", total=total)
        if taken.waited >= due:
            _say(
                out,
                f"- WAITING for a host slot ({len(holders)} of {total} held,"
                f" DJB_GATE_HOST_SLOTS) {taken.waited}s — "
                + "; ".join(host_holder_phrase(line) for line in holders),
            )
            due = taken.waited + announce
        time.sleep(poll)
        taken.waited += poll


def nominal(
    typed: int, constant: str, rows: Iterable[str], out: TextIO | None = None
) -> tuple[int, str, str]:
    """A pass's nominal: the last `took=` among `rows`, else `typed`, printed with its source."""
    out, _ = _streams(out, None)
    took: int | None = None
    for row in rows:
        if _TOOK.search(row):
            value = row.rsplit(" took=", 1)[1].split(" ", 1)[0].strip()
            took = int(value) if value.isdigit() and int(value) > 0 else None
    if took is not None:
        seconds, provenance, why = took, "measured", "this checkout's last banked took="
    else:
        seconds, provenance, why = typed, "typed", f"typed, hold.py {constant}"
    _say(out, f"  nominal:    {(seconds + 59) // 60}m ({why})")
    return seconds, provenance, why


def hold(
    scope: str,
    *,
    on_contention: str,
    mode: str = "full",
    lease: Hold | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> Hold | None:
    """One acquire, four scopes: `lease`, `host` and `slot` (wait), `checkout` (refuse)."""
    if scope == "lease":
        return acquire_lease(out, err) if on_contention == "wait" else try_lease(err)
    if scope == "slot" and on_contention == "wait":
        return acquire_slot(
            mode, lease_first=mode in ("full", "bank"), lease=lease, out=out, err=err
        )
    if scope == "slot":
        taken = Hold("slot")
        return taken if try_slot(mode, taken, err) else None
    if scope == "host" and on_contention == "wait":
        if env.read("DJB_GATE_LEGS_DRY"):
            return Hold("host")
        return acquire_host_slot(mode, lease=lease, out=out, err=err)
    if scope == "checkout" and on_contention == "refuse":
        return acquire_lock(out=out, err=err)
    raise ValueError(f"hold: no {on_contention!r} road for the scope {scope!r}")


# --- the CLI: one verb per function `scripts/gate_lease.sh` exports, its argv/exit/stdout ---


@dataclass
class Shell:
    """The calling shell's guard globals, handed in by `gate_hold_cli` and handed back as lines."""

    lease: str = ""
    slot: str = ""
    held: str = ""
    lease_first: str = ""
    sets: dict[str, str] = field(default_factory=dict)
    exports: dict[str, str | None] = field(default_factory=dict)

    def held_paths(self) -> list[Path]:
        """The slots the shell holds, in the order taken, then `GATE_SLOT`, as it walks them."""
        seen: list[Path] = []
        for line in (*self.held.splitlines(), self.slot):
            if line and Path(line) not in seen:
                seen.append(Path(line))
        return seen

    def worker_env(self) -> None:
        """Hand back `DJB_GATE_SLOT_WORKERS` as this process left it: exported, or unset."""
        self.exports["DJB_GATE_SLOT_WORKERS"] = env.read("DJB_GATE_SLOT_WORKERS")

    def lines(self) -> str:
        """The assignments the shell evaluates after the verb returns."""
        said = [f"{name}={_quote(value)}" for name, value in self.sets.items()]
        for name, value in self.exports.items():
            said.append(f"unset {name}" if value is None else f"export {name}={_quote(value)}")
        return "".join(f"{line}\n" for line in said)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _print(out: TextIO, *lines: str) -> None:
    for line in lines:
        out.write(f"{line}\n")


def _cli_lease_path(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, str(lease_path(err)))
    return 0


def _cli_slots_dir(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, str(slots_dir(err)))
    return 0


def _cli_lease_holder(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    try:
        path = lease_path(err)
    except Refused:
        return 0
    held = holder_of(path, "full-gate lease", err)
    if held:
        _print(out, held)
    return 0


def _cli_hold_holder(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    held = holder_of(Path(args[0]), args[1] if len(args) > 1 else "", err)
    if held:
        _print(out, held)
    return 0


def _cli_hold(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    return 0 if try_create(Path(args[0]), args[1], args[2], err) else 1


def _cli_lease_try(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    taken = try_lease(err)
    if taken is None:
        return 1
    shell.sets["GATE_LEASE"] = str(taken.paths[0])
    return 0


def _cli_lease_release(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    if shell.lease:
        Hold("lease", [Path(shell.lease)]).release()
    shell.sets["GATE_LEASE"] = ""
    return 0


def _cli_lease_acquire(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    taken = acquire_lease(out, err)
    shell.sets["GATE_LEASE"] = str(taken.paths[0])
    shell.sets["GATE_LEASE_WAITED"] = str(taken.waited)
    return 0


def _cli_slot_cores(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, str(cores(err)))
    return 0


def _cli_slots_total(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, str(slots_total(err)))
    return 0


def _cli_slot_workers(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, str(slot_workers(int(args[0]), err)))
    return 0


def _cli_slot_worker_count(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    share = int(args[1]) if len(args) > 1 and args[1] else None
    workers, provenance, phrase = worker_count(int(args[0]), share, out, err)
    shell.sets.update(
        GATE_SLOT_WORKERS=str(workers),
        GATE_SLOT_WORKERS_PROV=provenance,
        GATE_SLOT_WORKERS_PHRASE=phrase,
    )
    shell.worker_env()
    return 0


def _cli_slot_line(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, record(args[0]))
    return 0


def _cli_slot_holders(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    _print(out, *slot_holders(err))
    return 0


def _cli_slot_try(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    taken = Hold("slot")
    if not try_slot(args[0], taken, err):
        return 1
    shell.sets["GATE_SLOT"] = shell.slot or str(taken.paths[0])
    shell.sets["GATE_SLOTS_HELD"] = f"{shell.held}{taken.paths[0]}\n"
    return 0


def _cli_slot_release(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    Hold("slot", shell.held_paths()).release()
    shell.sets.update(GATE_SLOTS_HELD="", GATE_SLOT="")
    shell.exports["DJB_GATE_SLOT_WORKERS"] = None
    return 0


def _cli_slot_acquire(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    shell.sets.update(GATE_SLOT_WAITED="0", GATE_SLOT="", GATE_SLOTS_HELD="")
    lease = Hold("lease", [Path(shell.lease)]) if shell.lease else None
    try:
        taken = acquire_slot(
            args[0] if args else "loop",
            lease_first=bool(shell.lease_first),
            lease=lease,
            out=out,
            err=err,
        )
    finally:
        shell.worker_env()
    shell.sets.update(
        GATE_SLOT=str(taken.paths[0]),
        GATE_SLOTS_HELD="".join(f"{path}\n" for path in taken.paths),
        GATE_SLOT_WAITED=str(taken.waited),
        GATE_SLOT_TOTAL=str(taken.total),
        GATE_SLOT_WORKERS=str(taken.workers),
        GATE_SLOT_WORKERS_PROV=taken.provenance,
        GATE_SLOT_WORKERS_PHRASE=taken.phrase,
    )
    return 0


def _cli_slot_holder_phrase(shell: Shell, args: list[str], out: TextIO, err: TextIO) -> int:
    out.write(slot_holder_phrase(args[0] if args else ""))
    return 0


@dataclass(frozen=True)
class Verb:
    """One CLI verb: its body, whether it waits (a piped stdout refused), its refusal's exit."""

    run: Callable[[Shell, list[str], TextIO, TextIO], int]
    waits: bool = False
    refused: int = 2


#: The verbs: exactly the functions `scripts/gate_lease.sh` exports, each its one wrapper line.
VERBS: dict[str, Verb] = {
    "gate_lease_path": Verb(_cli_lease_path, refused=1),
    "gate_slots_dir": Verb(_cli_slots_dir, refused=1),
    "gate_lease_holder": Verb(_cli_lease_holder),
    "gate_hold_holder": Verb(_cli_hold_holder),
    "gate_hold": Verb(_cli_hold),
    "gate_lease_try": Verb(_cli_lease_try),
    "gate_lease_release": Verb(_cli_lease_release),
    "gate_lease_acquire": Verb(_cli_lease_acquire, waits=True),
    "gate_slot_cores": Verb(_cli_slot_cores),
    "gate_slots_total": Verb(_cli_slots_total),
    "gate_slot_workers": Verb(_cli_slot_workers),
    "gate_slot_worker_count": Verb(_cli_slot_worker_count),
    "gate_slot_line": Verb(_cli_slot_line),
    "gate_slot_holders": Verb(_cli_slot_holders),
    "gate_slot_try": Verb(_cli_slot_try),
    "gate_slot_release": Verb(_cli_slot_release),
    "gate_slot_acquire": Verb(_cli_slot_acquire, waits=True),
    "gate_slot_holder_phrase": Verb(_cli_slot_holder_phrase),
}
#: The options `gate_hold_cli` hands in ahead of `--`, each the shell global it carries.
OPTIONS = ("--pid", "--lease", "--slot", "--held", "--lease-first", "--state-fd")


def _piped() -> bool:
    if env.environ().get("CI"):
        return False
    try:
        return stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m quality.djb.hold <verb> [--pid N …] [--] [args…]`: the verb's exit, or 2."""
    global _HOLDER_PID
    args = list(sys.argv[1:] if argv is None else argv)
    name = args.pop(0) if args else ""
    verb = VERBS.get(name)
    if verb is None:
        _say(sys.stderr, f"!! hold: no verb {name!r}", *(f"   {known}" for known in VERBS))
        return 2
    options: dict[str, str] = {}
    while len(args) >= 2 and args[0] in OPTIONS:
        option, value, *args = args
        options[option] = value
    if args[:1] == ["--"]:
        args.pop(0)
    _HOLDER_PID = int(options.get("--pid") or os.getppid())
    shell = Shell(
        options.get("--lease", ""),
        options.get("--slot", ""),
        options.get("--held", ""),
        options.get("--lease-first", ""),
    )
    rc = 0
    try:
        if verb.waits and _piped():
            raise _refuse(
                sys.stderr,
                f"{name} refuses pipes — run it bare or redirect to a file.",
                "   The exit status is the verdict, and a filter replaces it.",
            )
        rc = verb.run(shell, args, sys.stdout, sys.stderr)
    except Refused as refused:
        shell.sets["GATE_LAST_REFUSAL"] = refused.cause
        rc = verb.refused
    except (CouldNotLook, OSError, ValueError, IndexError) as error:
        cause = f"hold: {name} could not look — {type(error).__name__}: {error}"
        _say(sys.stderr, f"!! {cause}")
        shell.sets["GATE_LAST_REFUSAL"] = cause
        rc = 2
    finally:
        sys.stdout.flush()
        if "--state-fd" in options:
            with os.fdopen(int(options["--state-fd"]), "w") as state:
                state.write(shell.lines())
    return rc


if __name__ == "__main__":
    sys.exit(main())
