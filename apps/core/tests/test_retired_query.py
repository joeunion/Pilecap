"""A retired query parameter is declared once, and every reader defers to it.

A list that stopped taking a query parameter declares it beside `PREFIX` and
`TAGS` — `RETIRED_QUERY: dict[str, RetiredQuery]` in its `api.py` — and three
readers read that one declaration:

* **the route** refuses it through `refuse_retired_query`, `400 invalid` naming
  the parameter to ask with instead, in the declaration's sentence;
* **the published document** marks it `deprecated: true` on every operation
  that takes the live parameter, with the same sentence as its description;
* **a product's strict-query seam** — one that refuses any query parameter a
  route does not take — asks `retired_query_of(operation)` first and lets the
  route answer, so the declared sentence is the one a caller reads on every
  tree.

`strict_query_seam` below is that product-shaped seam, planted as a middleware.
It is exported for the noun apps' own archive tests, which drive their list
both ways — bare, and behind the seam — and assert the same sentence each time.
"""

from __future__ import annotations

import copy
import importlib
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.test import Client
from django.urls import Resolver404, resolve

from apps.accounts.models import User
from apps.core.api.query import RetiredQuery, offers_query, retired_query_of
from apps.core.checks import _bound_operations
from apps.core.exceptions import Invalid, wire_refusal

#: Where the seam sits, as a dotted path `settings.MIDDLEWARE` can name.
SEAM = "apps.core.tests.test_retired_query.StrictQuerySeam"

#: The two lists the template retires `?archived=` on, by `url_name` — the
#: worked examples the population below must keep (a floor by member, not a count).
DECLARED_LISTS = {"file-list", "recipient-list"}


def _operation_for(request: HttpRequest) -> Any | None:
    """The bound API operation this request reaches, or None outside the API."""
    from config.api import api

    try:
        match = resolve(request.path_info)
    except Resolver404:
        return None
    for bound in api._get_bound_routers():
        for path_view in bound.path_operations.values():
            names = {getattr(operation, "url_name", None) for operation in path_view.operations}
            if match.url_name not in names:
                continue
            for operation in path_view.operations:
                if request.method in (operation.methods or ()):
                    return operation
    return None


class StrictQuerySeam:
    """Refuse a query parameter the route does not take, unless the route retired it.

    The product-shaped seam (a consumer's strict query): an unknown parameter is
    `400 invalid` naming it, composed through `wire_refusal` like every other
    refusal — except a parameter the route's module declared retired, which it
    leaves for the route to answer in the declaration's own sentence.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response: HttpResponse = self.get_response(request)
        return response

    def process_view(
        self, request: HttpRequest, view_func: Any, view_args: Any, view_kwargs: Any
    ) -> HttpResponse | None:
        """Answer an unknown parameter here; pass a retired or a known one to the route."""
        from config.api import status_for

        operation = _operation_for(request)
        if operation is None:
            return None
        retired = retired_query_of(operation)
        unknown = sorted(
            name
            for name in request.GET
            if name not in retired and not offers_query(operation, name)
        )
        if not unknown:
            return None
        refusal = Invalid(
            {name: [f"`{name}` is not a parameter this list takes."] for name in unknown}
        )
        return JsonResponse(wire_refusal(refusal), status=status_for(refusal))


def strict_query_seam(settings: Any) -> None:
    """Plant the product-shaped seam on this test's requests (pytest-django's `settings`)."""
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, SEAM]


def _declaration(module_name: str) -> Mapping[str, RetiredQuery]:
    declared = getattr(importlib.import_module(module_name), "RETIRED_QUERY", None)
    return declared if isinstance(declared, Mapping) else {}


def _answered() -> dict[str, dict[str, RetiredQuery]]:
    """`retired_query_of` over every bound operation, keyed by `url_name`, non-empty only."""
    return {
        str(operation.url_name): answer
        for _prefix, operation in _bound_operations()
        if (answer := retired_query_of(operation))
    }


def test_every_operation_answers_its_modules_declaration_where_it_takes_the_successor() -> None:
    """Each answer is the module's own entries, narrowed to the operation that takes `instead`."""
    for _prefix, operation in _bound_operations():
        declared = _declaration(operation.view_func.__module__)
        answer = retired_query_of(operation)
        for name, entry in answer.items():
            assert declared.get(name) is entry, (operation.url_name, name)
            assert offers_query(operation, entry.instead), (operation.url_name, name)
        for name, entry in declared.items():
            if offers_query(operation, entry.instead):
                assert answer.get(name) is entry, (operation.url_name, name)


def test_the_two_worked_lists_retire_archived_in_favour_of_show() -> None:
    """Files' document list and comms' contact list: one sentence, one declaration."""
    answered = _answered()
    assert DECLARED_LISTS <= set(answered), sorted(answered)
    sentences = {answered[name]["archived"] for name in DECLARED_LISTS}
    assert len(sentences) == 1, sentences
    (entry,) = sentences
    assert entry.instead == "show"


def test_the_document_publishes_every_retired_parameter_deprecated(api: Client, db: None) -> None:
    """The rendered document's `deprecated` query parameters ARE the declarations' answers."""
    expected = sorted(
        (retired, entry.reason)
        for answer in _answered().values()
        for retired, entry in answer.items()
    )
    document = json.loads(api.get("/api/v1/openapi.json").content)
    published = sorted(
        (parameter["name"], parameter.get("description"))
        for methods in document["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict)
        for parameter in operation.get("parameters", [])
        if parameter.get("deprecated") and parameter.get("in") == "query"
    )
    assert published == expected


def test_behind_a_strict_seam_the_route_answers_a_retired_parameter_and_the_seam_an_unknown_one(
    api: Client, owner: User, settings: Any
) -> None:
    """The two readers agree on who answers: the route for `archived`, the seam for the rest."""
    declared = _answered()["file-list"]["archived"]
    strict_query_seam(settings)
    api.force_login(owner)

    retired = api.get("/api/v1/files/?archived=true")
    assert retired.status_code == 400, retired.content
    assert retired.json()["code"] == "invalid"
    assert retired.json()["errors"] == {declared.instead: [declared.reason]}

    unknown = api.get("/api/v1/files/?frobnicate=1")
    assert unknown.status_code == 400, unknown.content
    assert unknown.json()["code"] == "invalid"
    assert set(unknown.json()["errors"]) == {"frobnicate"}

    assert api.get("/api/v1/files/?show=all&limit=5").status_code == 200


@pytest.fixture
def document_derived_unpatched() -> Iterator[None]:
    """The mount's document derived from the real declarations before a test patches one.

    `config.api` documents every bound operation ONCE, at import
    (`document_api` writes each operation's `openapi_extra`), so a test that
    patches a module's `RETIRED_QUERY` before anything imported the mount has
    its patch baked into the document for the rest of the process — the next
    test to read `openapi.json` then misses the retired parameter. This binds
    the mount first, snapshots every operation's documented extras, and
    restores them afterwards, so the patching test owns its whole effect.
    """
    snapshot = [
        (operation, copy.deepcopy(operation.openapi_extra))
        for _prefix, operation in _bound_operations()
    ]
    yield
    for operation, extra in snapshot:
        operation.openapi_extra = extra


def test_a_seam_with_no_declaration_to_read_answers_first_in_its_own_words(
    document_derived_unpatched: None,
    api: Client,
    owner: User,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The RED the declaration closes: nothing declared, and the seam's sentence is the answer."""
    monkeypatch.setattr("apps.files.api.RETIRED_QUERY", {})
    strict_query_seam(settings)
    api.force_login(owner)

    refused = api.get("/api/v1/files/?archived=true")
    assert refused.status_code == 400, refused.content
    assert set(refused.json()["errors"]) == {"archived"}, refused.json()
