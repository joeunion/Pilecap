"""The domain exceptions `config/api.py` maps, and the ones it deliberately does not.

Driven through `api.on_exception`, which is the same lookup a live request goes
through when a route raises — so this proves the handlers are *registered*, not
merely that they exist. Before they did, a service raising `ValidationError`
reached Django's 500 handler and answered a JSON client with a page of HTML.

Two families meet here: the domain refusals a service raises
(`apps.core.exceptions`) and the Django-native exceptions that escape from the
paths a service does not own. Both come out with the same body, because a
client should not be able to tell which of the two refused it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.test import RequestFactory

from apps.core.exceptions import (
    REFUSALS,
    Conflict,
    DomainError,
    Forbidden,
    Invalid,
    NotFound,
    RateLimited,
    Remedy,
    register_refusal,
)
from config.api import api, status_for


@pytest.fixture
def request_() -> Any:
    return RequestFactory().get("/api/v1/widgets/")


def _body(response: HttpResponse) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def test_a_validation_error_is_a_400_naming_the_fields(request_: Any) -> None:
    response = api.on_exception(request_, ValidationError({"name": ["This is too short."]}))
    assert response.status_code == 400
    body = _body(response)
    assert body["detail"] == "This is too short."
    assert body["errors"] == {"name": ["This is too short."]}


def test_a_validation_error_without_fields_still_reports_its_messages(request_: Any) -> None:
    response = api.on_exception(request_, ValidationError("Nothing about this holds."))
    assert response.status_code == 400
    assert _body(response)["errors"] == {"__all__": ["Nothing about this holds."]}


def test_an_integrity_error_is_a_409_that_does_not_repeat_the_database(request_: Any) -> None:
    response = api.on_exception(
        request_,
        IntegrityError('duplicate key value violates unique constraint "widget_unique_name"'),
    )
    assert response.status_code == 409
    detail = _body(response)["detail"]
    assert detail == "That conflicts with a row that already exists."
    assert "constraint" not in detail


def test_permission_denied_is_a_403(request_: Any) -> None:
    response = api.on_exception(request_, PermissionDenied("Not for you."))
    assert response.status_code == 403
    assert _body(response)["detail"] == "Not for you."


def test_a_missing_object_is_a_404_that_gives_nothing_away(request_: Any) -> None:
    class Thing:
        class DoesNotExist(ObjectDoesNotExist):
            pass

    for exc in (Thing.DoesNotExist("Thing 7 is not here"), Http404("No Widget matches")):
        response = api.on_exception(request_, exc)
        assert response.status_code == 404
        # AMENDED (ADR core-5): the envelope grew
        # `remedies` — label + destination, composed once server-side — and the
        # addition is deliberate and additive. `detail` and `code` are exactly
        # what they were; nothing was renamed and nothing was dropped.
        assert _body(response) == {
            "detail": "Not Found",
            "code": "not_found",
            "remedies": [
                {
                    "label": "Check which tenant you are acting in",
                    "destination": "header:X-Tenant",
                },
                {
                    "label": "Check which organization you are wearing",
                    "destination": "header:X-Org",
                },
            ],
        }


def test_everything_else_is_left_alone(request_: Any) -> None:
    with pytest.raises(RuntimeError):
        api.on_exception(request_, RuntimeError("something genuinely broke"))


# --- The domain vocabulary ---------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (Invalid({"name": ["Too short."]}), 400, "invalid"),
        (Forbidden(), 403, "forbidden"),
        (NotFound(), 404, "not_found"),
        (Conflict(), 409, "conflict"),
        (RateLimited(), 429, "rate_limited"),
    ],
)
def test_each_domain_refusal_has_its_status_and_its_code(
    request_: Any, exc: DomainError, status: int, code: str
) -> None:
    response = api.on_exception(request_, exc)
    assert response.status_code == status
    assert _body(response)["code"] == code


def test_invalid_carries_the_fields_that_failed(request_: Any) -> None:
    response = api.on_exception(request_, Invalid({"name": ["Too short.", "Also rude."]}))
    body = _body(response)
    # AMENDED (ADR core-5): `remedies` joined the
    # envelope. `errors` still says which field failed, and still says it.
    assert body["detail"] == "Too short. Also rude."
    assert body["code"] == "invalid"
    assert body["errors"] == {"name": ["Too short.", "Also rude."]}
    assert body["remedies"] == [
        {"label": "Read the failing fields and resend", "destination": "field:errors"},
        {"label": "Read the shape this endpoint accepts", "destination": "docs:openapi"},
    ]


def test_a_refusal_without_fields_carries_no_errors_key(request_: Any) -> None:
    assert "errors" not in _body(api.on_exception(request_, NotFound()))


def test_rate_limited_tells_the_caller_when_to_come_back(request_: Any) -> None:
    response = api.on_exception(request_, RateLimited(retry_after=30))
    assert response.status_code == 429
    assert response["Retry-After"] == "30"


def test_a_product_subclass_inherits_its_parents_status(request_: Any) -> None:
    """A product extends the vocabulary without editing the table.

    Two properties in one test, and they are the pair a product needs:

    * the code is **declared** — `register_refusal` runs before the class body
      closes, or `__init_subclass__` refuses the class at import;
    * the status is **inherited** — `status_for` walks the MRO, so a 409 needs
      no edit to `STATUS_FOR` and no edit to `config/api.py` at all.
    """
    register_refusal(
        code="insufficient_funds",
        boundary="service",
        remedy="Top the account up, or ask for the overdraft the product does not have.",
        fact="There is less in the account than this payment needs. Nothing was moved.",
        remedies=(Remedy("Add funds to the account", "self:account"),),
    )

    class InsufficientFunds(Conflict):
        code = "insufficient_funds"

    exc = InsufficientFunds("Not enough in the account.")
    assert status_for(exc) == 409

    response = api.on_exception(request_, exc)
    assert response.status_code == 409
    # AMENDED (ADR core-5): `remedies` in the envelope,
    # and they are the *product's* remedies, because the registry entry is the
    # product's. A subclass still costs no edit to `config/api.py`.
    assert _body(response) == {
        "detail": "Not enough in the account.",
        "code": "insufficient_funds",
        "remedies": [{"label": "Add funds to the account", "destination": "self:account"}],
    }


def test_the_registry_reaches_the_wire_as_a_code_and_nothing_else(request_: Any) -> None:
    """**AMENDED** (ADR core-5).

    The amendment, stated rather than performed silently: the original design
    pinned the envelope at exactly `{detail, code, errors?}`. ADR core-5 in
    `docs/product/architecture.md` — the ADR home — adds
    `remedies` — structured `{label, destination}` pairs composed once
    server-side so a screen and an assistant offer the same way out — and the
    addition is legal *because it is additive*:
    `detail`, `code` and `errors` are untouched, so every client pinned to the
    old three keys still reads them.

    **What this protects is unchanged, and is what this still
    asserts**: the internal `remedy` prose does not leave the building. It is
    written for whoever is *holding* the refusal — an agent, a developer, an
    integrator reading `introspect` — and it names `policies.py` and
    `Membership`. The client-facing half has its own honest fields now, which
    is exactly why the internal one has no excuse to leak.
    """
    forbidden = Forbidden()
    registered = REFUSALS[forbidden.code]
    assert registered.remedy and registered.boundary == "policy"

    body = _body(api.on_exception(request_, forbidden))
    assert set(body) == {"detail", "code", "remedies"}
    assert registered.remedy not in json.dumps(body)
    assert "remedy" not in json.dumps(body)
    # `fact` is the registry's statement about what the CODE means, not about
    # this request, so it stays off the wire too — `detail` is the request's.
    assert registered.fact not in json.dumps(body)
    assert "fact" not in json.dumps(body)
