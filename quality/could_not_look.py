"""The one "could not look" in Python: `CouldNotLook`, and the one sentence it exits with.

An instrument that could not read its input, could not trust it, or could not
get as far as judging raises `CouldNotLook`; its entry point catches it and
calls `exit_could_not_look(message)`, which prints `!! COULD NOT LOOK: <message>`
on stderr and exits 2. That is the shell's `gate_die`
(`scripts/gate_refuse.sh`) in the other language: `!!` is exit 2, exit 2 is
"never got as far as judging", and it outranks a pass. An instrument that
LOOKED and found something wrong exits 1 by its own verdict path, never
through here.

A program keeps its own name for the class where its callers already spell it
(`from quality.could_not_look import CouldNotLook as CannotLook`): one class,
so `except CouldNotLook` catches every instrument's refusal and nothing else.
A refusal that needs to carry more than its sentence subclasses it
(`quality/check_v1.py::RunnerRefused` carries the class of the refusal).

Standard library only, and `apps.core.roads` is itself standard library only:
the scripts under `scripts/` import this with nothing but the checkout root on
`sys.path`, under any Python 3 a laptop or a box runs them with.
"""

from __future__ import annotations

import sys
from typing import NoReturn

from apps.core.roads import road

#: The leader every could-not-look sentence opens with — `!!` is exit 2's.
LEADER = "!! COULD NOT LOOK: "


# The Python mirror of `scripts/gate_refuse.sh::gate_die`, pinned equal by
# `quality/tests/test_refusal_seam.py::test_the_python_mirror_says_it_alike`.
# rule-84: mirror of gate_die in Python — one exit-2 word, pinned by the test named above
@road("could_not_look", example="scripts/test_impact.py::read_collected")
class CouldNotLook(Exception):
    """An instrument could not look: exit 2, never a pass and never a finding."""


def exit_could_not_look(message: str) -> NoReturn:
    """Print `!! COULD NOT LOOK: <message>` on stderr and exit 2."""
    print(f"{LEADER}{message}", file=sys.stderr)
    raise SystemExit(2)


#: How many of a tool's last non-blank lines a refusal carries, and how wide each may be.
SAID_LINES = 5
SAID_WIDTH = 300
#: The leader of each line a refusal quotes from the tool it ran.
SAID = "   the tool said: "


@road(
    "tool_said",
    example="quality/tests/test_refusal_seam.py::test_a_refusal_quotes_the_tools_last_lines",
)
def tool_said(output: str | bytes | None, *, lines: int = SAID_LINES) -> str:
    """The tool's own last lines, one `the tool said:` each, bounded; "" when it said nothing."""
    text = output.decode(errors="replace") if isinstance(output, bytes) else output or ""
    kept = [line.rstrip() for line in text.splitlines() if line.strip()][-lines:]
    return "".join(f"\n{SAID}{line[:SAID_WIDTH]}" for line in kept)
