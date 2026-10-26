"""The engine's budget sentences, parsed: the one reader the fold and the tidy both import."""

from __future__ import annotations

import re

#: The engine's one summary line's lead (`check_budgets`' run, recomposed by the reader).
SUMMARY = "### budget-check: "
#: The two sentence ends that are followed by a pasteable line: the RAISE and the NEW SUBJECT.
PASTE_ENDS = ("The line to paste, verbatim:", "in quality/budgets.yaml:")
#: The LOWERING sentence's end: the fold applies the line after it, the tidy only prints it.
LOWER_END = "a human may commit the lower number:"
RECORD = re.compile(r": [0-9]+[ \t]*$")

Record = tuple[str, str, str]


def summary_lines(text: str) -> int:
    """How many summary lines the run printed; exactly one is the only shape read."""
    return sum(1 for line in text.splitlines() if line.startswith(SUMMARY))


def claimed(text: str, want: str) -> str:
    """The count the engine stated it wrote under `want`, or '' (`budget_notes_claimed`)."""
    found: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if words[:2] == ["###", "budget-check:"]:
            found += [v for n, _, v in (w.partition("=") for w in words[2:]) if n == want]
    return "\n".join(found)


def records(text: str, ends: tuple[str, ...], leader: tuple[str, ...]) -> list[Record]:
    """The record line after each sentence ending in `ends` whose first words are `leader`."""
    found: list[Record] = []
    section = ""
    pending = False
    for line in text.splitlines():
        if line.endswith(ends):
            words = line.split()
            pending = tuple(words[: len(leader)]) == leader and len(words) > len(leader)
            section = words[len(leader)] if pending else section
            continue
        if not pending:
            continue
        pending = False
        tail = RECORD.search(line)
        if not line.startswith("  ") or tail is None:
            continue
        found.append((section, line[2 : tail.start()], line[tail.start() + 2 :].rstrip(" \t")))
    return found


def pastables(text: str) -> list[Record]:
    """The RAISE and the NEW SUBJECT records: the tidy's half of the engine's sentences."""
    return records(text, PASTE_ENDS, ("budget:",))


def lowerings(text: str) -> list[Record]:
    """The LOWERING records: `(section, key, number)`, the fold's to apply."""
    return records(text, (LOWER_END,), ("budget", "note:"))


#: The worked example's re-record sentence: the tidy's own, written from the measurement (gate-5).
FOLLOW = "budget follow:"

Follow = tuple[str, str, str, str]


def follows(text: str, apps: tuple[str, ...]) -> list[Follow]:
    """`(section, key, recorded, measured)` per follow line whose key is under `apps`."""
    found: list[Follow] = []
    for line in text.splitlines():
        words = line.split()
        if line.startswith(FOLLOW) and len(words) == 6 and words[3].startswith(apps):
            if re.fullmatch(r"[0-9]+", words[4]) and re.fullmatch(r"[0-9]+", words[5]):
                found.append((words[2], words[3], words[4], words[5]))
    return found
