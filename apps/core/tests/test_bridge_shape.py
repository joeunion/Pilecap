"""Every bridge name is pinned to the shape it declares, and the code wins.

`bridge.get(EMIT)` hands back `Callable[..., Any]`. That is the honest type —
`core` cannot import the app that fills the name, which is the entire reason the
bridge exists — and it is also no help: a registrant that gained a keyword, lost
one, or renamed one would break its callers at runtime, in whichever process
called it first, with a `TypeError` naming a function `core` has never heard of.
Nothing in the tree could fail earlier than that, because nothing in the tree
wrote the shape down.

`bridge.SHAPES` writes it down, one `Protocol` per name, and this module holds
the **live registry** to it with `inspect.signature`. Not a copy of the
signature, not a docstring: what the running process actually has, compared to
what `core` declares it expects.

**Annotations are deliberately not compared.** The protocols type the foreign
classes as `Any` (`tenant: Any`, not `tenant: Tenant`) because `core` may not
import them, so an annotation comparison could only ever assert `Any == Tenant`
and fail. What is compared is what drifts: the parameter names, that they are
keyword-only, which of them carry defaults and what those defaults are, and —
where it can be read cheaply — the arity of the answer.

**Code beats prose, and this is where that is enforced.** `workflow_context()`
returns a **3-tuple**; the module comment beside `WORKFLOW_CONTEXT` claimed a
pair until it was corrected, because the acting org became the third element
when the hierarchy landed and the comment did not move. The test below calls it
and counts, so the next time the two disagree the test is the one that says so.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from apps.core import bridge

# Every name `core` declares a shape for is also a name something registered in
# this process, which is the property that makes the whole module non-vacuous:
# a `SHAPES` entry nobody fills would otherwise be silently skipped.
PINNED = sorted(bridge.SHAPES)


def declared(name: str) -> inspect.Signature:
    """The shape `core` says it expects, read off the protocol's `__call__`."""
    signature = inspect.signature(bridge.SHAPES[name].__call__)
    return signature.replace(
        parameters=[p for p in signature.parameters.values() if p.name != "self"]
    )


def actual(name: str) -> inspect.Signature:
    """The shape the process actually has, read off the live registry."""
    fn = bridge.registered()[name]
    return inspect.signature(fn)


def shape(signature: inspect.Signature) -> list[tuple[str, Any, Any]]:
    """A signature reduced to the part that is a contract between two apps.

    Name, kind and default. Not the annotation — see the module docstring.
    """
    return [
        (parameter.name, parameter.kind, parameter.default)
        for parameter in signature.parameters.values()
    ]


# --- The registry fills every name that declares a shape ----------------------


def test_every_declared_shape_is_a_name_something_registered() -> None:
    """Otherwise the pins below would pass by not running."""
    registered = bridge.registered()
    assert PINNED, "no shapes declared — every test here would be vacuous"
    missing = [name for name in PINNED if name not in registered]
    assert missing == [], f"declared but nobody registered: {missing}"


def test_every_registered_name_declares_a_shape() -> None:
    """The other direction: a name added without a shape is an unpinned contract.

    This is the one that fails on the day somebody adds a sixth bridge name and
    stops there — which is exactly when the shape is cheapest to write down.
    """
    undeclared = sorted(set(bridge.registered()) - set(bridge.SHAPES))
    assert undeclared == [], f"registered with no declared shape: {undeclared}"


# --- The pin ------------------------------------------------------------------


@pytest.mark.parametrize("name", PINNED)
def test_the_registrant_has_the_shape_core_declares(name: str) -> None:
    """The whole point: a registrant that drifts fails here, not in production."""
    assert shape(actual(name)) == shape(declared(name)), (
        f"{name} is filled by a callable whose signature is not the one "
        f"apps/core/bridge.py declares for it"
    )


@pytest.mark.parametrize("name", PINNED)
def test_every_bridge_argument_is_keyword_only(name: str) -> None:
    """A cross-app call has no positional order to remember.

    Positional arguments across a boundary neither side imports are exactly the
    ones that get silently swapped, and `@service` already holds the same line
    for every write in the tree.
    """
    for parameter in actual(name).parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{name}.{parameter.name} is {parameter.kind}"
        )


def test_the_pin_would_catch_a_drifting_registrant() -> None:
    """The canary: a comparison that cannot fail is not a comparison."""

    def drifted(*, workflow: Any, arg: Any, tenant: Any, id: str) -> Any:
        """`start_workflow_on_commit` as it was before the hat and the queue."""
        return None

    assert shape(inspect.signature(drifted)) != shape(declared(bridge.START_WORKFLOW_ON_COMMIT))


# --- The 3-tuple, read from the code rather than from a comment ----------------


@pytest.mark.django_db
def test_workflow_context_answers_with_three_things(tenant: Any) -> None:
    """Tenant, user id, **hat** — and the hat is the one prose kept forgetting.

    Called for real rather than read off an annotation, so it pins the arity the
    callers actually unpack:

        tenant, user_id, org = workflow_context()

    A caller written against the 2-tuple the module comment used to describe
    would raise `ValueError: too many values to unpack` on the first activity
    that ran. That is the failure this replaces.

    **A principal is bound first, and that is new since P1 W4.** This used to
    call with nothing bound and assert `(None, None, None)`, which was cheap and
    needed no database. The registered accessor now *refuses* a run that stamped
    no tenant rather than answering `None` — a missing tenant that travelled one
    hop further became `for_tenant(None)`, which is empty rather than refused
    (an earlier finding) — so calling it unbound no longer measures arity, it measures
    the guard. Binding one real principal restores the measurement and pins one
    thing more than before: the first element is the tenant row itself.
    """
    from apps.workflows.context import reset_principal, set_principal

    read: Callable[..., Any] = bridge.get(bridge.WORKFLOW_CONTEXT)
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=None)
    try:
        answer = read()
    finally:
        reset_principal(tokens)

    assert isinstance(answer, tuple)
    assert len(answer) == 3, f"workflow_context returned {len(answer)} things, not 3"
    restored, user_id, org = answer
    assert (restored, user_id, org) == (tenant, None, None)


def test_the_declared_shape_says_three_as_well() -> None:
    """The declaration and the code agree — which is what "code wins" has to mean.

    `-> tuple[Any, Any, Any]` on `ReadsWorkflowContext` is the written half; the
    test above is the measured half. Asserting both keeps the protocol from
    quietly becoming the stale copy the module comment used to be.
    """
    from typing import get_args, get_origin, get_type_hints

    returns = get_type_hints(bridge.ReadsWorkflowContext.__call__)["return"]

    assert get_origin(returns) is tuple
    assert len(get_args(returns)) == 3
