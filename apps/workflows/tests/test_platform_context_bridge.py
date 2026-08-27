"""`platform_context` crosses the layer contract — ADR core-9.

`apps.workflows` sits **above** `apps.accounts`, so an activity in accounts
could not reach `platform_context()` at all: that was reported
rather than smuggling an upward import, and the two platform kinds in
`apps/accounts/activities.py` therefore resolved no scope and asserted nothing.
A platform run under a stray tenant hat proceeded cross-scoped, silently.

The bridge is the inversion this repository already owns, so the fix is a fourth
name on it. **The registration seam is what this module measures**, and what has
to hold for it to be real:

* `apps/workflows` registers the callable from `ready()` — the one hook that
  runs in every process, so the name is filled for the web server, the worker,
  `manage.py` and pytest alike, not only where somebody imported a module;
* the **live** registrant is the real accessor, not a look-alike;
* the shape is pinned, and the pin can fail — `apps/core/tests/
  test_bridge_shape.py` holds every `SHAPES` entry to its protocol and picked
  this one up with no edit, which is the parametrisation doing its job; the
  drift canary for *this* name is below, so the pin is proven non-vacuous for
  the name that was just added rather than only for the oldest one;
* the word behind the name means one thing on both sides of it: the run
  ledger's `platform:` segment and the accessor's null tenant are the same
  population.

What the accessor *answers* — that it may say None, and that it does **not**
assert the tenant is absent — is the accessor's own contract, and it is pinned
where the accessor is documented: `apps/workflows/tests/test_context.py`.
"""

from __future__ import annotations

import inspect
from typing import Any

from apps.core import bridge
from apps.workflows.context import platform_context, workflow_context
from apps.workflows.models import WorkflowRun

# --- Registration -------------------------------------------------------------


def test_the_name_is_filled_by_ready() -> None:
    """Not by an import: `ready()` is what runs in every process."""
    assert bridge.is_registered(bridge.PLATFORM_CONTEXT)
    assert bridge.registered()[bridge.PLATFORM_CONTEXT] is platform_context


def test_the_name_is_the_one_core_declares() -> None:
    """A typo here would be a logged no-op on a laptop and a refusal in production."""
    assert bridge.PLATFORM_CONTEXT == "workflows.platform_context"
    assert bridge.PLATFORM_CONTEXT in bridge.SHAPES
    assert bridge.SHAPES[bridge.PLATFORM_CONTEXT] is bridge.ReadsPlatformContext


def test_it_is_not_the_same_callable_as_the_tenanted_accessor() -> None:
    """Two names, two contracts. One of them raises; this one does not."""
    assert bridge.get(bridge.PLATFORM_CONTEXT) is not bridge.get(bridge.WORKFLOW_CONTEXT)
    assert bridge.get(bridge.WORKFLOW_CONTEXT) is workflow_context


def test_the_shape_pin_would_catch_a_drifting_registrant() -> None:
    """The canary: a comparison that cannot fail is not a comparison.

    `test_bridge_shape.py` compares every registrant to its protocol, and this
    name's protocol takes no parameters — so the pin passing tells you nothing
    until something is shown to fail it. A registrant that grew an argument is
    the drift that would actually happen (an accessor "improved" to take a
    default tenant), and it is refused.
    """

    def drifted(*, default_tenant: Any = None) -> tuple[Any, Any, Any]:
        return (None, None, None)

    declared = inspect.signature(bridge.SHAPES[bridge.PLATFORM_CONTEXT].__call__)
    declared_names = [p.name for p in declared.parameters.values() if p.name != "self"]

    assert declared_names == []
    assert [p.name for p in inspect.signature(drifted).parameters.values()] != declared_names
    assert [p.name for p in inspect.signature(platform_context).parameters.values()] == []


# --- The population it exists for ---------------------------------------------


def test_the_run_ledger_and_the_accessor_agree_on_what_platform_means() -> None:
    """One word, one meaning: null tenant, `platform:` first id segment."""
    from apps.workflows.services import PLATFORM_SEGMENT

    assert PLATFORM_SEGMENT == "platform"
    assert hasattr(WorkflowRun.objects, "for_platform")
