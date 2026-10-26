"""The `fake_clock` fixture: `date +%s` and `sleep` on the stub PATH read and advance one file."""

from __future__ import annotations

import os
import shlex
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.stub_path import StubPath

#: How long a writer waits on the clock's lock before it says so rather than spinning on.
LOCK_WAIT_S = 10
# Every shell writer of a clock calls this: one writer at a time, the new value renamed into place.
ADVANCE_SH = r"""_clock_advance() {
    local c="$1" n tries=0
    until /bin/mkdir "$c.lock" 2>/dev/null; do
        tries=$((tries + 1))
        if [ "$tries" -gt 1000 ]; then
            printf 'fake_clock: %s.lock held past 10s\n' "$c" >&2
            exit 2
        fi
        /bin/sleep 0.01
    done
    n=$(( $(cat "$c" 2>/dev/null || echo 0) + ${2:-0} ))
    printf '%s\n' "$n" >"$c.$$"
    /bin/mv -f "$c.$$" "$c"
    /bin/rmdir "$c.lock"
    printf '%s\n' "$n"
}
"""
_SLEEP = """#!/usr/bin/env bash
{advance}_clock_advance {clock} "${{1:-0}}" >/dev/null
exit 0
"""
# Only `+%s` is the subject's clock; every other format is real time.
_DATE = """#!/usr/bin/env bash
for a in "$@"; do
    if [ "$a" = "+%s" ]; then cat {clock}; exit 0; fi
done
exec /bin/date "$@"
"""


@dataclass(frozen=True)
class FakeClock:
    """Epoch seconds in one file: the subject's `sleep` advances it, its `date +%s` reads it."""

    file: Path

    def now(self) -> int:
        """The clock; `CouldNotLook` when the file does not hold a whole number."""
        text = self.file.read_text().strip() if self.file.is_file() else ""
        if not text.isdigit():
            raise CouldNotLook(f"fake_clock: {self.file} holds {text!r}, not epoch seconds")
        return int(text)

    def advance(self, seconds: int) -> int:
        """Move the clock forward; `CouldNotLook` on a negative step — a clock never runs back."""
        if seconds < 0:
            raise CouldNotLook(f"fake_clock: a step of {seconds}s runs the clock backwards")
        lock = self.file.with_name(f"{self.file.name}.lock")
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise CouldNotLook(f"fake_clock: {lock} held past {LOCK_WAIT_S}s") from None
                time.sleep(0.01)
        try:
            now = self.now() + seconds
            self.set(now)
        finally:
            lock.rmdir()
        return now

    def set(self, value: int) -> None:
        """Put `value` on the clock whole: a sibling file renamed over it, never a truncation."""
        temp = self.file.with_name(f"{self.file.name}.{os.getpid()}.{threading.get_ident()}")
        temp.write_text(f"{value}\n")
        os.replace(temp, self.file)


def plant_clock(stubs: StubPath, file: Path, start: int) -> FakeClock:
    """Write `start` to `file` and plant `sleep` and `date` reading it on `stubs`."""
    clock = FakeClock(file)
    clock.set(start)
    quoted = shlex.quote(str(file))
    stubs.plant("sleep", _SLEEP.format(advance=ADVANCE_SH, clock=quoted))
    stubs.plant("date", _DATE.format(clock=quoted))
    return clock


@pytest.fixture
def fake_clock(scratch: Path, stub_path: StubPath) -> FakeClock:
    """A clock started at the real epoch, its `sleep` and `date` planted on `stub_path`."""
    return plant_clock(stub_path, scratch / "clock", int(time.time()))
