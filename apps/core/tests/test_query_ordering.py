"""`ordered_by` keeps the promise the selector made underneath it.

This guards a real bug (ADR core-9). The bug it closes is
the kind that leaves no trace: `.order_by(wanted)` **replaces** a queryset's
ordering, so a selector promising "newest version first within a name" had that
half deleted the instant a door sorted by name, and two versions of one row came
back in whatever order the plan happened to produce. Nothing raised, nothing
logged; the list was simply sometimes wrong.

The **blast radius** is every route in the tree that calls `ordered_by`, and it
is swept here rather than by editing five apps: each caller's selector ordering
is fed in as a queryset and the resulting SQL ordering asserted. A lane that
cannot test another app's routes must not edit them, and this suite owns
`apps/core` — so the property is proven against the same querysets those routes
pass, from here.

DOES NOT COVER — declared: whether a route's *default* ordering is a good one,
and whether a selector's promise is worth making. This says only that whatever
the selector said still holds after the door has spoken.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from apps.core.api.query import ordered_by
from apps.core.exceptions import Invalid
from apps.core.tests.tree_census import source_text, source_tree
from apps.example.models import Widget

pytestmark = pytest.mark.django_db

# `updated_at` stands in for the `-version` of ADR core-9's example: a
# secondary field that is neither the requested one nor a duplicate of it.
ALLOWED = ("name", "created_at", "updated_at", "notes")


def ordering_of(queryset: Any) -> tuple[str, ...]:
    """What the queryset will actually put in its ORDER BY."""
    return tuple(queryset.query.order_by)


# --- W1R1-8: the tie-breakers survive ----------------------------------------


def test_a_secondary_sort_survives_the_door() -> None:
    """The exact case from ADR core-9: `("name", "-version")`, sorted by name.

    The requested field leads and the duplicate of it is dropped — asking for
    `name` must not produce `("name", "name", "-version")` — and `-version`,
    which is the whole promise, is still there.
    """
    promised = Widget.objects.order_by("name", "-updated_at")
    assert ordering_of(ordered_by(promised, "name", allowed=ALLOWED)) == (
        "name",
        "-updated_at",
    )


def test_a_different_field_pushes_the_whole_promise_down_one() -> None:
    """`("created_at", "name", "-version")` — nothing dropped, nothing reordered."""
    promised = Widget.objects.order_by("name", "-updated_at")
    assert ordering_of(ordered_by(promised, "created_at", allowed=ALLOWED)) == (
        "created_at",
        "name",
        "-updated_at",
    )


def test_the_requested_direction_displaces_the_incoming_one() -> None:
    """`-name` over an incoming `name`: the caller asked, and gets it once.

    Compared with the direction stripped, because `("−name", "name", …)` would
    be a queryset arguing with itself and the database would take the first.
    """
    promised = Widget.objects.order_by("name", "-updated_at")
    assert ordering_of(ordered_by(promised, "-name", allowed=ALLOWED)) == (
        "-name",
        "-updated_at",
    )


def test_a_queryset_with_no_ordering_of_its_own_is_unchanged_in_behaviour() -> None:
    """Nothing is invented: the old behaviour, for the callers that had no promise.

    `Meta.ordering` is deliberately NOT carried forward — it is a default, not
    something a selector said — so a route that sorted by one field still sorts
    by one field and its SQL is byte-for-byte what it was.
    """
    assert ordering_of(ordered_by(Widget.objects.all(), "name", allowed=ALLOWED)) == ("name",)


def test_no_ordering_asked_for_leaves_the_queryset_exactly_alone() -> None:
    promised = Widget.objects.order_by("name", "-updated_at")
    assert ordering_of(ordered_by(promised, None, allowed=ALLOWED)) == ("name", "-updated_at")


def test_the_default_is_applied_the_same_way_as_a_request() -> None:
    """A route's `default=` is a request the client did not have to make."""
    promised = Widget.objects.order_by("name", "-updated_at")
    assert ordering_of(ordered_by(promised, None, allowed=ALLOWED, default="created_at")) == (
        "created_at",
        "name",
        "-updated_at",
    )


def test_the_allow_list_still_refuses_what_the_route_did_not_name() -> None:
    """The property that was there first, and that this must not have loosened."""
    with pytest.raises(Invalid) as refused:
        ordered_by(Widget.objects.order_by("name"), "owner__password", allowed=ALLOWED)
    assert "ordering" in refused.value.errors


def test_the_duplicate_that_is_dropped_is_the_requested_field_and_only_it() -> None:
    """`created_at` over `("name", "-created_at")` -> `("created_at", "name")`.

    The requested field wins its own position and its old one goes; `name`,
    which was never in question, keeps its place behind it. Dropping *only* the
    duplicate is the whole of the rule, and this is the case that would expose
    a version of it that dropped too much or too little.
    """
    promised = Widget.objects.order_by("name", "-created_at")
    assert ordering_of(ordered_by(promised, "created_at", allowed=ALLOWED)) == (
        "created_at",
        "name",
    )


def test_a_random_ordering_is_not_carried_forward_as_a_tie_breaker() -> None:
    """`?` is a whole ordering, not a field; keeping it would re-shuffle groups."""
    assert ordering_of(ordered_by(Widget.objects.order_by("?"), "name", allowed=ALLOWED)) == (
        "name",
    )


# --- the blast radius --------------------------------------------------------
#
# Every `ordered_by` call site in the tree today, as the SHAPE of what its
# selector hands in and what its route asks for. The shapes are run against a
# `Widget` queryset — a real model, with real columns, that `apps/core`'s tests
# are allowed to build (import-linter permits `core.tests -> example` and
# nothing further; a core test may not import `comms` to borrow its columns).
# The property under test is field-name agnostic: the incoming ordering
# survives, minus a duplicate of what was asked for.
#
# The mapping from shape to call site, so it is checkable rather than implied:
#
#   ("-created_at",)                 example widgets, comms messages,
#                                    connections, accounts tokens — a single
#                                    field, and the route's default is it
#   ("name", "-<second>")            comms templates (`list_templates`) and
#                                    comms policies (`list_policies`): "newest
#                                    version first within a name", route
#                                    default `name`. THIS is the pair whose
#                                    second half a caller could silently delete
#   ("<one>",) + a different request comms recipients: ordered by channel
#                                    below, by email at the door
#   ("-created_at",) + a different    events dead letters: `BaseModel.Meta`'s
#   request                           `-created_at` below, `-dead_lettered_at`
#                                     at the door. No new SHAPE —
#                                     it is row 2 of the table with different
#                                     field names, which is the point of the
#                                     table being about shapes
#   ("path",)                        core organizations: tree order below AND
#                                    at the door, so the common case adds no
#                                    tie-breaker at all
#   ("organization__path",           core memberships: "grouped by branch, then
#    "user__email")                  by person", route default `role` — so the
#                                    ordinary request is ("role", + both), and
#                                    this is the second pair of the same shape in
#                                    the tree
#
# Asserted from here rather than by editing five apps: this suite owns
# `apps/core`, and a lane that cannot run another app's field test has no
# business editing its routes. The apology comment at `apps/comms/api.py:296`
# restating `-version` by hand is left exactly where it is — it is belt to this
# brace now, and removing it belongs to whoever owns that file.


@pytest.mark.parametrize(
    ("promise", "requested", "expected"),
    [
        (("-created_at",), "-created_at", ("-created_at",)),
        (("-created_at",), "name", ("name", "-created_at")),
        (("name", "-updated_at"), "name", ("name", "-updated_at")),
        (("name", "-updated_at"), "-name", ("-name", "-updated_at")),
        (("name", "-updated_at"), "created_at", ("created_at", "name", "-updated_at")),
        (("notes",), "name", ("name", "notes")),
    ],
)
def test_every_current_caller_shape_keeps_what_its_selector_promised(
    promise: tuple[str, ...], requested: str, expected: tuple[str, ...]
) -> None:
    allowed = sorted({entry.removeprefix("-") for entry in (*promise, requested)})
    result = ordered_by(Widget.objects.order_by(*promise), requested, allowed=allowed)
    assert ordering_of(result) == expected


# Two globs, because a door module is not always `apps/<app>/api.py`: core's
# routes live in the `api/` PACKAGE, and a census that only looked one level
# down would have reported "no new callers" while four new lists went past it
# (found by the census below failing when they did, which is it working).
DOOR_GLOBS = ("apps/*/*.py", "apps/*/api/*.py")
DOOR_NAMES = frozenset({"api.py", "mcp.py", "routes.py"})

#: The shape the table above drives, written out so a refusal can name it: the
#: promised queryset and what the client asked for, positionally, and the
#: route's own allow-list by keyword. `default=` is optional — a route's default
#: is a request the client did not have to make, which is the same shape.
CALL_SHAPE = "ordered_by(<queryset>, <ordering>, allowed=…[, default=…])"
SHAPE_KEYWORDS = frozenset({"allowed", "default"})


@dataclass(frozen=True)
class OrderedByCall:
    """One `ordered_by(...)` call site, as the SHAPE the table above is about."""

    caller: str
    line: int
    positional: int
    keywords: tuple[str, ...]

    @property
    def is_a_shape_the_table_drives(self) -> bool:
        named = set(self.keywords)
        return self.positional == 2 and "allowed" in named and named <= SHAPE_KEYWORDS


def ordered_by_call_sites(root: Path) -> list[OrderedByCall]:
    """Every `ordered_by(...)` call in every door module under `root` — DERIVED.

    This used to be a hand-typed set of file names, and the cost of that was
    paid by somebody else: a new app with a list door reddened a test in
    `apps/core` that its rung was not allowed to edit. The seeds come off the
    tree now, so a new door joins the census by existing.

    What is pinned instead is each call site's SHAPE, which is the thing the
    parametrized table above actually drives. A call of any other shape has
    never been run against that table, and it fails by name rather than
    silently widening the blast radius.

    `root` is a parameter rather than a constant so the same derivation can be
    pointed at a generated app in a temp tree — which is how
    `apps/core/tests/test_newapp.py` proves a generated list door lands in this
    census without anybody editing this file.
    """
    found: list[OrderedByCall] = []
    candidates = [
        path for pattern in DOOR_GLOBS for path in root.glob(pattern) if path.name in DOOR_NAMES
    ]
    for path in sorted(candidates):
        if "ordered_by(" not in source_text(path):
            continue
        caller = path.relative_to(root).as_posix()
        for node in ast.walk(source_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name != "ordered_by":
                continue
            found.append(
                OrderedByCall(
                    caller=caller,
                    line=node.lineno,
                    positional=len(node.args),
                    keywords=tuple(kw.arg or "**" for kw in node.keywords),
                )
            )
    return found


def test_the_shapes_above_are_the_shapes_the_tree_actually_uses() -> None:
    """The parametrize list is a claim about other files; this reads them.

    Without this, the table above is a list somebody typed once and nothing
    would notice when a sixth call site appeared with a shape nobody had
    thought about. It does not pin their FIELDS — those are those apps'
    business — it pins that every call site in the tree has a shape the table
    has actually been run against.

    THE FLOORS ARE TWO-LAYERED, and deliberately. Layer 1 is "the census
    reached something at all": an underived population is not an empty one, and
    a glob that stopped matching would otherwise leave this test green over
    nothing. Layer 2 names the populations the two globs exist for separately —
    the REST doors, the MCP doors, and the `api/` PACKAGE — because a single
    `>= 1` would be satisfied by either glob alone, which is exactly how one of
    them could go blind without anybody noticing.
    """
    root = Path(__file__).resolve().parents[3]
    calls = ordered_by_call_sites(root)

    assert calls, "no `ordered_by` call site found in the tree at all — the census went blind"
    by_rest = {call.caller for call in calls if call.caller.endswith("/api.py")}
    by_machine = {call.caller for call in calls if call.caller.endswith("/mcp.py")}
    by_package = {call.caller for call in calls if "/api/" in call.caller}
    assert by_rest, "no REST door calls `ordered_by` — the `apps/*/*.py` glob reached nothing"
    assert by_machine, "no MCP door calls `ordered_by` — the machine door left the census"
    assert by_package, (
        "no `apps/*/api/*.py` caller — the second glob reached nothing, which is the "
        "exact blindness it was added to close"
    )

    off_shape = [
        f"{call.caller}:{call.line} ({call.positional} positional, keywords {call.keywords})"
        for call in calls
        if not call.is_a_shape_the_table_drives
    ]
    assert off_shape == [], (
        "an `ordered_by` call site has a shape the table above has never been run against "
        f"(expected {CALL_SHAPE}): " + "; ".join(off_shape)
    )
