"""`manage.py shell` binds the chain a door binds.

The stock Django `shell` bound nothing, so a service called from it ran below
no door: `create_tenant`'s workflow start asked `child_of_current` for the chain
inside its commit hook, got `ContextUnbound`, and Django logged and swallowed
it. These tests drive the command the way an operator does — `shell -c` — with
the test's own chain cleared first, so the only binding in force is the one
the command makes.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.management import call_command, get_commands

from apps.core import context

# What the code run inside the shell saw; the `-c` snippet writes into it.
SEEN: dict[str, Any] = {}

PROBE = (
    "from apps.core import context\n"
    "from apps.core.tests import test_shell_door as probe\n"
    "probe.SEEN['bound'] = context.get()\n"
    "probe.SEEN['child'] = context.child_of_current()\n"
)


@pytest.fixture
def unbound() -> Any:
    """No chain in force: the command is the only door standing above the probe."""
    SEEN.clear()
    context.clear()
    yield
    SEEN.clear()


def test_the_shell_command_is_the_core_one() -> None:
    """`manage.py shell` resolves to this app's command, not Django's stock one."""
    assert get_commands()["shell"] == "apps.core"


def test_shell_binds_a_chain_at_the_shell_door(unbound: None) -> None:
    """Code run in the shell sees a correlation chain bound with `door="shell"`."""
    call_command("shell", "--no-imports", "-c", PROBE)

    bound = SEEN["bound"]
    assert bound["door"] == "shell"
    assert bound["actor_kind"] == "system"
    assert bound["command"] == "shell"
    assert bound["request_id"]
    assert bound["correlation_id"]
    # Work caused below the door continues the shell's chain rather than refusing.
    assert SEEN["child"] == {
        "correlation_id": bound["correlation_id"],
        "causation_id": bound["correlation_id"],
    }


def test_each_shell_run_is_its_own_chain_and_leaves_none_behind(unbound: None) -> None:
    """Two runs mint two chains, and the caller's context is put back after each."""
    call_command("shell", "--no-imports", "-c", PROBE)
    first = SEEN["bound"]["correlation_id"]
    assert context.get() == {}

    call_command("shell", "--no-imports", "-c", PROBE)
    assert SEEN["bound"]["correlation_id"] != first
    assert context.get() == {}
