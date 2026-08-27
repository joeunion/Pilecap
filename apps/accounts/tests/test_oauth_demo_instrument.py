"""The live-run instrument has to be able to fail.

`scripts/oauth_demo.py` is the only thing that ever drives the OAuth door
end to end against the real Zitadel, and its verdict is what a cycle's identity
claim rests on. At the first live run it printed

    [OK  ] mcp tools/call create_widget
           widget id=None name=None

over a tool that had **refused** — the caller held no membership. MCP carries a
tool's refusal in the *result* (`isError: true`), not in the JSON-RPC envelope,
so the demo's envelope check passed and the refusal was certified as a write.
An instrument that smiles at a refusal proves nothing, and it proves nothing
about the one leg nobody re-checks by hand.

What is asserted here is the demo's **result handling**, driven directly:
`check_result` on a planted refusal exits nonzero and prints the refusal's code
and message; on a real answer it returns the result and says nothing. The live
half — that Zitadel's own tokens open the door — stays in the real end-to-end
run against Zitadel, and this module is the regression that keeps the
instrument honest between those runs.

DOES NOT COVER — declared: the transport. Nothing here posts to `/mcp`, so a
demo that stopped calling `check_result` at all would still pass this module;
`post`'s single call site is the seam, and reading it is the check. Nor does it
cover the four legs before the door, which fail loudly on their own.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DEMO_PATH = Path(__file__).resolve().parents[3] / "scripts" / "oauth_demo.py"

# The text `apps/core/mcp.py:acting_tenant` refuses a tenantless caller with,
# and the shape `tool_call` renders every domain
# refusal in: `<code>: <detail>`, then whatever remedies the registry offers.
# Copied as a literal rather than composed, because what is under test is a
# *client* reading a wire format it does not own; composing it from our own
# helpers would only prove that we agree with ourselves.
REFUSAL_TEXT = (
    "no_tenant: This token resolves to no tenant, so there is nothing to act in."
    " — you can: Check which tenant you are acting in [header:X-Tenant]"
)


def load_demo() -> ModuleType:
    """Import `scripts/oauth_demo.py` by path.

    It is a script rather than a package member on purpose (it runs outside
    Django, with no settings module), so there is no import to write — the file
    is loaded the way `python scripts/oauth_demo.py` loads it, minus the
    `__main__` guard. Nothing at its module level does I/O.
    """
    spec = importlib.util.spec_from_file_location("oauth_demo_under_test", DEMO_PATH)
    assert spec is not None and spec.loader is not None, DEMO_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo() -> ModuleType:
    return load_demo()


def refused_result() -> dict[str, Any]:
    """The shape our own MCP door puts on the wire for a refused tool call."""
    return {
        "content": [{"type": "text", "text": REFUSAL_TEXT}],
        "isError": True,
    }


def written_result() -> dict[str, Any]:
    """The shape a real `create_widget` answers with."""
    return {
        "content": [{"type": "text", "text": '{"id": "0f9d…", "name": "oauth-demo"}'}],
        "structuredContent": {
            "id": "0f9d3a12-0000-4000-8000-000000000001",
            "name": "oauth-demo 2026-08-21 09:00:00",
            "notes": "written by OAuth",
        },
    }


# --- B4-3: a refusal stops the demo, loudly ----------------------------------


def test_a_refused_tool_call_exits_nonzero_and_names_the_refusal(
    demo: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exact failure from the docstring above, now a failure.

    Both halves are asserted because both are what an operator acts on: the
    **code** is what says which wall was hit (`no_tenant`, not "something went
    wrong"), and the **detail** is the sentence that says what to do about it.
    A nonzero exit with an unreadable line would be half a fix.
    """
    with pytest.raises(SystemExit) as exited:
        demo.check_result("mcp tools/call create_widget", refused_result())

    assert exited.value.code == 1

    printed = capsys.readouterr().out
    assert "[FAIL]" in printed
    assert "mcp tools/call create_widget" in printed
    assert "REFUSED" in printed
    assert "no_tenant" in printed
    assert "nothing to act in" in printed
    # And it must not have said the thing that made the original refusal look like a success.
    assert "[OK" not in printed


def test_an_error_shaped_result_without_the_flag_is_still_a_refusal(demo: ModuleType) -> None:
    """`isError` is the flag the protocol defines; it is not the only shape seen.

    A door-level refusal renders as the REST body — `{detail, code}` — and a tool
    that nested a JSON-RPC error put it under `error`. Neither sets `isError`,
    and reading either as an answer costs exactly what reading the first one
    cost. The extra arms cost nothing, so they are there.
    """
    body_shaped = {
        "structuredContent": {"code": "forbidden", "detail": "This actor may not do that."}
    }
    nested = {"error": {"code": -32000, "message": "tool exploded"}}

    assert demo.refusal_in(body_shaped) is not None
    assert "forbidden" in str(demo.refusal_in(body_shaped))
    assert demo.refusal_in(nested) is not None
    assert "tool exploded" in str(demo.refusal_in(nested))


def test_an_unparseable_refusal_is_still_a_refusal_and_is_printed_whole(demo: ModuleType) -> None:
    """A refusal we cannot read is a refusal, and the operator gets the bytes.

    The failure mode being avoided is an instrument that decides a shape it does
    not recognise must be fine.
    """
    opaque: dict[str, Any] = {"isError": True}
    detail = demo.refusal_in(opaque)
    assert detail is not None
    assert json.loads(str(detail)) == opaque


# --- B4-3: the happy path is untouched ---------------------------------------


def test_a_real_result_passes_through_unchanged_and_says_nothing(
    demo: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of the criterion: nothing new fires on a successful call.

    `check_result` returns the *same* object, because `post` hands its value
    straight on to the leg that reads `structuredContent` — a check that
    reshaped a result would break the demo in a way no live run would explain.
    """
    result = written_result()

    assert demo.check_result("mcp tools/call create_widget", result) is result
    assert demo.refusal_in(result) is None
    assert capsys.readouterr().out == ""


def test_initialize_and_tools_list_results_are_not_read_as_refusals(demo: ModuleType) -> None:
    """The two legs before the write, which carry neither flag nor error shape.

    Listed because `check_result` sits on every result, not only the write's: a
    detector with a false positive here would fail the demo before it ever
    reached the criterion.
    """
    initialized = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "djb", "version": "1"}}
    listing = {"tools": [{"name": "create_widget"}, {"name": "list_widgets"}]}

    assert demo.refusal_in(initialized) is None
    assert demo.refusal_in(listing) is None


# --- B4-4: the usage block names the prerequisite ----------------------------


def test_the_usage_block_names_the_audience_prerequisite(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The usage-block audience prerequisite, pinned where it cannot drift back out.

    `ZITADEL_MCP_AUDIENCE` is set on the *server*, so no flag on this client can
    stand in for it, and empty means the OAuth door is off rather than open — a
    fresh clone that misses it gets a 401 at leg 5 with nothing naming the cause.
    Asserted in both places it is written, because two different people read
    them: the file's usage block, and `--help` for whoever never opens the file.
    """
    doc = demo.__doc__ or ""
    assert "ZITADEL_MCP_AUDIENCE" in doc
    assert "off" in doc.lower()

    monkeypatch.setattr(sys, "argv", ["oauth_demo.py", "--help"])
    with pytest.raises(SystemExit) as exited:
        demo.main()

    assert exited.value.code == 0
    printed = capsys.readouterr().out
    assert "ZITADEL_MCP_AUDIENCE" in printed
    assert "OFF" in printed
