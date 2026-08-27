"""The headers this platform puts ON a response, documented off their writers.

The contract used to describe every header a caller SENDS and none of the
four it RECEIVES: `X-Request-Id` and `X-Correlation-Id` on every answer,
`Idempotent-Replayed` on a replayed write, `Retry-After` on a refusal for going
too fast. A client learned about them from somebody's network tab, which is the
same defect class as an undocumented refusal and was invisible for the same
reason — nothing fails when documentation is missing.

What these tests assert is not "the four are there". It is that the document
and the DERIVATION are the same thing, in both directions: every header the
declarations cover is documented, and nothing else is. A census, not a
checklist — so a fifth header declared beside its writer arrives documented
with no edit to `docs.py`, and a header stamped without a declaration is caught
by the CORS half rather than shipping invisible.
"""

from __future__ import annotations

import ast
import json
import types
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.test import Client

from apps.core.api import docs
from apps.core.api.docs import (
    RESPONSE_HEADERS,
    RETRY_AFTER_HEADER,
    ResponseHeader,
    add_response_headers,
    declared_response_headers,
    llms_text,
    on_every_response,
)
from apps.core.idempotency import HEADER as IDEMPOTENCY_HEADER
from apps.core.idempotency import REPLAYED_HEADER
from apps.core.middleware import CORRELATION_ID_HEADER, REQUEST_ID_HEADER
from config.api import api

#: The sentence the owner's Stripe-standard ruling asks for, once. It is
#: asserted rather than described because it is the whole reason a caller keeps
#: the id: a request id nobody was told to quote is a column in a log nobody
#: ever searches.
REPORTING_SENTENCE = "Include this id when reporting a problem."


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The document as `gen_client.sh`, `/api/v1/docs` and `openapi.json` read it."""
    rendered: dict[str, Any] = json.loads(json.dumps(api.get_openapi_schema()))
    return rendered


#: (path, method, status, operation, response) — one row per documented answer.
Row = tuple[str, str, str, dict[str, Any], dict[str, Any]]


def _responses(document: dict[str, Any]) -> list[Row]:
    """Every (path, method, status, operation, response) in the document."""
    found: list[Row] = []
    for path, path_item in sorted(document["paths"].items()):
        for method, operation in sorted(path_item.items()):
            if not isinstance(operation, dict):
                continue
            for status, response in sorted((operation.get("responses") or {}).items()):
                if isinstance(response, dict):
                    found.append((path, method, str(status), operation, response))
    return found


# --- the census: derivation and document are one question ---------------------


def test_the_documented_headers_are_exactly_what_the_declarations_cover(
    document: dict[str, Any],
) -> None:
    """Both directions, which is what makes it a census.

    A one-directional check ("everything declared is documented") passes on a
    document that has documented something nobody stamps; the other direction
    alone passes on a document that has quietly dropped one.
    """
    declared = declared_response_headers()
    assert declared, "the population is empty — the walk found no declarations at all"
    for path, method, status, operation, response in _responses(document):
        expected = {
            header.name for header in declared if header.covers(operation, status, response)
        }
        assert set(response.get("headers") or {}) == expected, f"{method.upper()} {path} {status}"


def test_every_response_documents_the_request_and_correlation_ids(
    document: dict[str, Any],
) -> None:
    """The two the context middleware stamps unconditionally, on the way out."""
    rows = _responses(document)
    assert rows
    for path, method, status, _operation, response in rows:
        documented = set(response.get("headers") or {})
        assert {REQUEST_ID_HEADER, CORRELATION_ID_HEADER} <= documented, (
            f"{method.upper()} {path} {status}"
        )


def test_a_write_documents_the_replay_header_and_a_read_does_not(
    document: dict[str, Any],
) -> None:
    write = document["paths"]["/api/v1/widgets/"]["post"]
    assert REPLAYED_HEADER in write["responses"]["201"]["headers"]
    assert (
        REPORTING_SENTENCE
        not in write["responses"]["201"]["headers"][REPLAYED_HEADER]["description"]
    )
    read = document["paths"]["/api/v1/widgets/"]["get"]
    for response in read["responses"].values():
        assert REPLAYED_HEADER not in (response.get("headers") or {})


def test_the_replay_header_is_documented_only_where_a_write_can_be_replayed(
    document: dict[str, Any],
) -> None:
    """The coverage rule, over the whole document rather than one route."""
    for path, method, status, operation, response in _responses(document):
        replayable = docs.reads_header(operation, IDEMPOTENCY_HEADER) and int(status) < 400
        documented = REPLAYED_HEADER in (response.get("headers") or {})
        assert documented is replayable, f"{method.upper()} {path} {status}"


def test_the_rate_limit_refusal_documents_retry_after(document: dict[str, Any]) -> None:
    """And nothing else does — `Retry-After` on a 200 would be advice about nothing."""
    seen = 0
    for path, method, status, _operation, response in _responses(document):
        refuses_rate_limit = docs.refuses_with(response, "rate_limited")
        documented = RETRY_AFTER_HEADER in (response.get("headers") or {})
        assert documented is refuses_rate_limit, f"{method.upper()} {path} {status}"
        seen += int(refuses_rate_limit)
    assert seen, "no response in the document enumerates rate_limited"


# --- the sentence, and the two renderings that must agree ---------------------


def test_the_request_id_tells_the_caller_to_quote_it(document: dict[str, Any]) -> None:
    for _path, _method, _status, _operation, response in _responses(document):
        assert REPORTING_SENTENCE in response["headers"][REQUEST_ID_HEADER]["description"]


@pytest.mark.django_db
def test_llms_txt_renders_the_same_header_text_as_the_document(
    client: Client, document: dict[str, Any]
) -> None:
    """WA-1-2's discipline: one source, two renderings, never two texts.

    The flat rendering is built by lifting the document's own sentences, so the
    assertion is equality with the document rather than the presence of a
    string somebody typed in both files.
    """
    text = llms_text(api)
    described = {
        name: spec["description"]
        for _p, _m, _s, _op, response in _responses(document)
        for name, spec in (response.get("headers") or {}).items()
    }
    assert described
    for name, description in described.items():
        assert f"{name}: {description}" in text
    assert REPORTING_SENTENCE in text

    response = client.get("/llms.txt")
    assert response.status_code == 200
    assert REPORTING_SENTENCE in response.content.decode()


def test_llms_txt_states_the_response_headers_per_operation(document: dict[str, Any]) -> None:
    """Every operation's own line, so an agent reading the flat file knows too."""
    text = llms_text(api)
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            names = sorted(
                {
                    name
                    for response in (operation.get("responses") or {}).values()
                    if isinstance(response, dict)
                    for name in (response.get("headers") or {})
                }
            )
            assert names, f"{method.upper()} {path}"
            assert "response headers: " + ", ".join(names) + "." in text


# --- the population is the imported constants ---------------------------------


def _declaration_source() -> ast.Assign:
    """The `RESPONSE_HEADERS = (...)` statement in `docs.py`, parsed."""
    tree = ast.parse(Path(docs.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "RESPONSE_HEADERS":
            assert node.value is not None
            return ast.Assign(targets=[node.target], value=node.value)
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "RESPONSE_HEADERS" for target in node.targets
        ):
            return node
    raise AssertionError("docs.py declares no RESPONSE_HEADERS")


def test_no_header_name_in_the_derivation_is_a_string_literal() -> None:
    """HDR-A-3, checked at the source and not by eye.

    A literal here is a SECOND spelling of a name that already exists at its
    writer, and a second spelling is the whole of rule 40's finding: the two
    agree until somebody renames one, and then the stamp and the document
    disagree with nothing raised anywhere.
    """
    declaration = _declaration_source()
    names = [
        keyword.value
        for call in ast.walk(declaration)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "name"
    ]
    assert len(names) == len(RESPONSE_HEADERS)
    for value in names:
        assert isinstance(value, ast.Name), ast.dump(value)


def test_every_declared_name_is_its_writers_constant() -> None:
    assert {header.name for header in RESPONSE_HEADERS} == {
        REQUEST_ID_HEADER,
        CORRELATION_ID_HEADER,
        REPLAYED_HEADER,
        RETRY_AFTER_HEADER,
    }


# --- the CORS census: stamped and exposed are one list ------------------------


def test_cors_exposes_exactly_the_stamped_population() -> None:
    """The mirror check: a header stamped but not exposed is invisible cross-origin.

    `CORS_EXPOSE_HEADERS` and the stamped population agree on main today. This
    is what makes the agreement a census rather than a coincidence — the next
    header declared beside its writer fails here until it is exposed, which is
    the moment somebody can still fix it for nothing.
    """
    stamped = {header.name.lower() for header in declared_response_headers()}
    assert set(settings.CORS_EXPOSE_HEADERS) == stamped


# --- order independence: a writer joins with no edit here ---------------------


def test_a_writer_declared_elsewhere_joins_the_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The criterion that makes this a derivation instead of a list.

    A module that stamps a header declares it beside the constant that names
    it; the walk finds it. Nothing in `docs.py` is edited, and nothing had to
    hand-promise the name in advance.
    """
    module = types.ModuleType("apps.zzz_response_header_probe")
    module.RESPONSE_HEADERS = (  # type: ignore[attr-defined]
        ResponseHeader(
            name="X-Probe-Header",
            description="Planted by a test, from a module docs.py has never heard of.",
            covers=on_every_response,
        ),
    )
    import sys

    monkeypatch.setitem(sys.modules, "apps.zzz_response_header_probe", module)

    assert "X-Probe-Header" in {header.name for header in declared_response_headers()}

    schema: dict[str, Any] = {
        "paths": {"/probe": {"get": {"responses": {"200": {"description": "ok"}}}}}
    }
    add_response_headers(schema)
    documented = schema["paths"]["/probe"]["get"]["responses"]["200"]["headers"]
    assert str(documented["X-Probe-Header"]["description"]).startswith("Planted by a test")


def test_the_walk_ignores_a_module_that_declares_something_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `RESPONSE_HEADERS` that is not a tuple of declarations is not a finding.

    The walk reads other people's modules, so it has to be incurious about what
    it finds there: a product with its own `RESPONSE_HEADERS` meaning something
    else gets no document and no exception.
    """
    module = types.ModuleType("apps.zzz_response_header_noise")
    module.RESPONSE_HEADERS = ("X-Not-A-Declaration",)  # type: ignore[attr-defined]
    import sys

    monkeypatch.setitem(sys.modules, "apps.zzz_response_header_noise", module)

    assert "X-Not-A-Declaration" not in {h.name for h in declared_response_headers()}
