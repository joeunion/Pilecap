"""The selftest unit's shell drives, in order: each one's file and the sentence its red prints."""

# Invariant: the order is the selftest unit's member order; the sweep deletes rows, never moves one.

from __future__ import annotations

from typing import NamedTuple


class Drive(NamedTuple):
    """One registered drive: its name, its file, and what its red means."""

    name: str
    path: str
    red: str


#: Every shell drive the selftest unit runs, until the sweep deletes the ones a module carries.
DRIVES: tuple[Drive, ...] = (
    Drive(
        "drive_preamble",
        "scripts/tests/test_drive_preamble.sh",
        "the real-repository tripwire no longer tells a drive's escape from a peer's ordinary"
        " work. Every other drive in this leg stands on it, so a tripwire that forgives too "
        "much makes all of them vouch for less than they claim, and one that forgives too "
        "little reddens this gate for somebody else's commit.",
    ),
)
