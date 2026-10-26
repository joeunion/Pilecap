"""The fake clock under concurrent writers: no reader sees a torn file, no step is lost."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.fake_clock import plant_clock
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives("quality/tests/fixtures/fake_clock.py")

START = 1_700_000_000
SLEEPERS = 32
READS = 200
ADVANCERS = 8


def test_concurrent_sleeps_never_tear_the_clock_and_lose_no_step(
    scratch: Path, stub_path: StubPath
) -> None:
    clock = plant_clock(stub_path, scratch / "clock", START)
    torn: list[str] = []

    def advance() -> None:
        clock.advance(1)

    sleepers = [
        subprocess.Popen(["sleep", "1"], env={"PATH": stub_path.path}) for _ in range(SLEEPERS)
    ]
    advancers = [threading.Thread(target=advance) for _ in range(ADVANCERS)]
    for thread in advancers:
        thread.start()
    for _ in range(READS):
        try:
            clock.now()
        except CouldNotLook as seen:
            torn.append(str(seen))
    codes = [sleeper.wait(timeout=60) for sleeper in sleepers]
    for thread in advancers:
        thread.join(timeout=60)
    assert codes == [0] * SLEEPERS, codes
    assert not torn, f"{len(torn)} of {READS} reads torn: {torn[0]}"
    assert clock.now() == START + SLEEPERS + ADVANCERS, clock.now() - START
