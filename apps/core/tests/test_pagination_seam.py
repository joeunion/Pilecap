"""The one pagination predicate, and the three instruments that read it.

ADR core-24. Three instruments used to answer "is this route paginated?" for
themselves, off two different private ninja attributes:

* rule 3's census — `apps/core/checks.py`, `_ninja_contribute_args`;
* the docs derivation — `config/api.py`, `_ninja_is_paginated`;
* `manage.py introspect`'s `paginated` column — `_ninja_contribute_args`.

All three markers mean "`@paginate` was applied", and all three were wrong about
the same three routes: `api:search_kind-list`, `api:search-query` and
`api:meter-list` reach `cursor_page` directly and answer
`{items, has_more, next_cursor, count}` without ever meeting the decorator.

**The class this module closes is not the wrong column. It is fix-one-leave-two-
blind.** One fact re-derived in three private places drifts apart silently, and
nothing anywhere fails when it does — so the tests below are written so that
SEVERING THE SEAM REDS ALL THREE READERS, not one. That property was
plant-verified when this landed (`answers_cursor_envelope` stubbed to the old
marker test: three distinct failures, one per reader) and it is what the module
exists to keep.

The plant is a route this module builds itself — a direct-cursor list on a
throwaway `NinjaAPI` — because a destructive demonstration creates its own
victim and never borrows a mounted one.
"""

from __future__ import annotations

from typing import Any

import pytest
from ninja import NinjaAPI, Router, Schema

from apps.accounts.auth import API_AUTH
from apps.core.api.pagination import answers_cursor_envelope, offers_pagination_controls
from apps.core.checks import _bound_operations, _is_list_response
from apps.core.management.commands.introspect import _routes_payload
from apps.core.schemas import ListPage

#: The routes that answer the envelope WITHOUT the decorator. Named rather than
#: derived on purpose: this is the red population the seam was built for, and a
#: derived version of it would be the seam checking itself.
DIRECT_CURSOR_ROUTES = {"api:search_kind-list", "api:search-query", "api:meter-list"}


class ProbePage(ListPage):
    """A `*Page` schema for the planted route — the direct-cursor shape."""

    items: list[str]


class ProbeOut(Schema):
    """A NON-list response, for the negative: seen by no reader."""

    name: str


@pytest.fixture(scope="module")
def planted() -> Any:
    """A direct-cursor list route, built here and mounted nowhere.

    `@paginate` is deliberately absent and `cursor`/`limit` are declared by hand,
    which is exactly the shape the three mounted routes have. Its tag is one the
    tree already declares so the documentation derivation has a scope to derive.
    """
    api = NinjaAPI(urls_namespace="r7-pagination-seam-probe", auth=API_AUTH)
    router = Router(tags=["widgets"], auth=API_AUTH)

    @router.get("/planted/", response=ProbePage, url_name="planted-list")
    def planted_list(request: Any, cursor: str = "", limit: int | None = None) -> ProbePage:
        """Planted list

        A direct-cursor list that never met `@paginate`, built for one test run.
        """
        raise NotImplementedError

    api.add_router("/probe", router)
    return _only_operation(api)


@pytest.fixture(scope="module")
def planted_singular() -> Any:
    """The negative: a route that answers ONE of something. No reader sees it."""
    api = NinjaAPI(urls_namespace="r7-pagination-seam-negative", auth=API_AUTH)
    router = Router(tags=["widgets"], auth=API_AUTH)

    @router.get("/planted-one/", response=ProbeOut, url_name="planted-detail")
    def planted_detail(request: Any) -> ProbeOut:
        """Planted detail

        One of something, which is not a list and not an envelope.
        """
        raise NotImplementedError

    api.add_router("/probe", router)
    return _only_operation(api)


def _only_operation(api: NinjaAPI) -> Any:
    operations = [
        operation
        for bound in api._get_bound_routers()
        for path_view in bound.path_operations.values()
        for operation in path_view.operations
    ]
    assert len(operations) == 1, f"the probe api bound {len(operations)} operations, not one"
    return operations[0]


def _refusal_codes(operation: Any) -> set[str]:
    """The codes the docs derivation published for this operation's 400."""
    responses = (operation.openapi_extra or {}).get("responses") or {}
    return set((responses.get(400) or {}).get("x-refusal-codes") or [])


# --- the seam itself -----------------------------------------------------------


def test_the_seam_sees_a_direct_cursor_route(planted: Any) -> None:
    """The predicate reads the RESPONSE, so the decorator's absence is irrelevant."""
    view = planted.view_func
    assert not getattr(view, "_ninja_is_paginated", False)
    assert not hasattr(view, "_ninja_contribute_args")
    assert answers_cursor_envelope(planted) is True
    assert offers_pagination_controls(planted) is True


def test_the_seam_sees_nothing_in_a_singular_route(planted_singular: Any) -> None:
    """The negative, stated as its own assertion rather than as an absence."""
    assert answers_cursor_envelope(planted_singular) is False
    assert offers_pagination_controls(planted_singular) is False


# --- reader 1: rule 3's census (apps/core/checks.py) ---------------------------


def test_rule_threes_list_population_holds_the_direct_cursor_routes() -> None:
    """The census sees a list, and the population it sees is not empty.

    Before the seam this population was **zero members**. Every list in this tree
    already answers the cursor envelope, and the census tested for a `list[`
    annotation — so `djb.E030` was enforcing nothing whatsoever against the real
    registry while its canary went on firing happily against a planted bare list.
    An instrument that cannot fail on the tree it watches is the class the seam
    closes; the floor below is what keeps it closed.
    """
    population = {
        f"api:{operation.url_name}"
        for _prefix, operation in _bound_operations()
        if _is_list_response(operation)
    }
    assert len(population) >= 20, (
        f"rule 3's list population is {len(population)} routes. It is a census over "
        "every mounted list; a population this small means `_is_list_response` has "
        "stopped recognising the envelope and E030 is watching nothing."
    )
    assert DIRECT_CURSOR_ROUTES <= population, (
        "these routes answer the cursor envelope and rule 3's census does not see "
        f"them: {sorted(DIRECT_CURSOR_ROUTES - population)}"
    )


def test_the_census_reads_the_seam_and_not_a_decorator_marker() -> None:
    """Bound, both directions: the census's answer IS the seam's answer.

    Without this the census could drift back to reading `_ninja_contribute_args`
    and stay green, because on a tree where every list happens to be
    `@paginate`d the two answers coincide. They coincide today for 22 of 25.
    """
    for _prefix, operation in _bound_operations():
        if answers_cursor_envelope(operation):
            assert _is_list_response(operation), (
                f"api:{operation.url_name} answers the cursor envelope and rule 3's "
                "census does not count it as a list"
            )


# --- reader 2: the docs derivation (config/api.py) -----------------------------


def test_the_document_derives_the_cursor_refusal_for_a_direct_cursor_route(
    planted: Any,
) -> None:
    """`invalid_cursor` is published because the route can ISSUE a cursor.

    A route that hands out a `next_cursor` can be handed a bad one back, and a
    refusal a generated client has no branch for is rule 47's whole defect. The
    derivation used to read `_ninja_is_paginated`, so it published nothing of the
    kind for the three routes that issue cursors without the decorator.

    Driven through `config.api._document_operation` — the same call
    `document_api()` makes over every mounted operation — against a route this
    test planted, so nothing mounted is disturbed.
    """
    from config.api import _document_operation

    assert _refusal_codes(planted) == set(), "the probe operation arrived pre-documented"
    _document_operation("probe/planted/", planted)
    assert "invalid_cursor" in _refusal_codes(planted), (
        "the docs derivation published no `invalid_cursor` for a route that issues "
        f"cursors; it published {sorted(_refusal_codes(planted))}"
    )


def test_the_document_derives_no_cursor_refusal_for_a_singular_route(
    planted_singular: Any,
) -> None:
    """The negative half: a route that issues no cursor promises no cursor refusal."""
    from config.api import _document_operation

    _document_operation("probe/planted-one/", planted_singular)
    assert "invalid_cursor" not in _refusal_codes(planted_singular)


# --- reader 3: introspect's `paginated` column ---------------------------------


def test_introspect_reports_the_mounted_behaviour_not_the_decorator() -> None:
    """THE CARRIED CRITERION (VERIFY-F4), asserted against the live mount.

    "introspect's `paginated` column agrees with the mounted behaviour — a route
    whose 2xx model carries the cursor envelope reports `paginated: true` whether
    the envelope came from `@paginate` or a direct `cursor_page` call."

    The three named routes are the population that used to report `false`. This
    is the strongest witness available for this reader: not a planted operation
    but the document three real doors actually serve.
    """
    reported = {
        str(route["name"]): bool(route["paginated"]) for route in _routes_payload() if route["name"]
    }
    wrong = sorted(name for name in DIRECT_CURSOR_ROUTES if not reported.get(name))
    assert not wrong, (
        f"these routes answer the cursor envelope and introspect calls them "
        f"unpaginated: {wrong}. A criteria-writer reads this column."
    )
    assert sum(reported.values()) >= 20, (
        "introspect reports almost nothing as paginated; the column has stopped reading the seam."
    )


def test_introspects_column_is_the_seam_over_every_route() -> None:
    """Bound to the seam, route by route — the same tie as the census's above."""
    seam = {
        f"api:{operation.url_name}": answers_cursor_envelope(operation)
        for _prefix, operation in _bound_operations()
        if operation.url_name
    }
    reported = {
        str(route["name"]): bool(route["paginated"]) for route in _routes_payload() if route["name"]
    }
    disagree = sorted(name for name, value in seam.items() if reported.get(name) != value)
    assert not disagree, (
        f"introspect's `paginated` column disagrees with the seam on: {disagree}. "
        "One fact, one predicate — a second derivation here is how the three "
        "readers drifted apart in the first place."
    )
