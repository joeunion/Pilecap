"""ADR core-19: the throttle says its numbers, so a client can back off before 429.

A 429 was documented and nothing on a *successful* response let a caller
see the wall coming — so the only way to discover the limit was to hit it, and
the only strategy available was to hit it again. The throttle already knows the
three numbers; this is them reaching the wire.

Two claims are load-bearing and both are asserted by driving the real API rather
than by inspecting a function: the numbers are TRUE (`Remaining` decrements as
requests are spent), and they describe the BUCKET THAT WILL REFUSE — the binding
one — because a header reporting the roomier of two buckets is worse than no
header at all. It would be advice that runs out without warning.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.core.api.docs import RETRY_AFTER_HEADER, declared_response_headers
from apps.core.exceptions import RateLimited, wire_refusal
from apps.core.models import Tenant
from apps.core.throttling import (
    RATE_LIMIT_HEADER,
    RATE_LIMIT_REMAINING_HEADER,
    RATE_LIMIT_RESET_HEADER,
    AuthRateThrottle,
    ScopeSubject,
    TenantRateThrottle,
    default_throttles,
    rate_limit_headers,
    recorded,
)
from config.api import api

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"

TRIPLE = (RATE_LIMIT_HEADER, RATE_LIMIT_REMAINING_HEADER, RATE_LIMIT_RESET_HEADER)


@pytest.fixture(autouse=True)
def _empty_bucket() -> Any:
    """Counters live in the cache, so a test that inherits one is a flake."""
    cache.clear()
    yield
    cache.clear()


def _with_rates(credential: str, tenant_rate: str) -> Any:
    """The live API's operations, throttled at rates a test can reach.

    Constructor rates rather than settings, for `test_throttling.py`'s reason:
    ninja resolves the settings table once, at import.
    """
    replaced: list[Any] = [AuthRateThrottle(credential), TenantRateThrottle(tenant_rate)]
    originals: list[tuple[Any, list[Any]]] = []
    for bound in api._get_bound_routers():
        for _path, view in bound.path_operations.items():
            for operation in view.operations:
                originals.append((operation, operation.throttle_objects))
                operation.throttle_objects = replaced
    return replaced, originals


@pytest.fixture
def tiny_limit() -> Any:
    """Two a minute in both buckets — neither binds over the other by design."""
    _replaced, originals = _with_rates("2/min", "2/min")
    yield
    for operation, throttles in originals:
        operation.throttle_objects = throttles


@pytest.fixture
def tenant_binds() -> Any:
    """The tenant bucket smaller than the credential one, so it is what refuses."""
    _replaced, originals = _with_rates("20/min", "3/min")
    yield
    for operation, throttles in originals:
        operation.throttle_objects = throttles


# --- HDR-B-1: the numbers exist, and they are true ----------------------------


def test_a_passing_request_carries_the_triple_as_integers(
    api: Client, owner: User, tenant: Tenant, tiny_limit: Any
) -> None:
    api.force_login(owner)
    response = api.get(LIST_URL)

    assert response.status_code == 200
    for name in TRIPLE:
        assert name in response.headers, name
        assert response.headers[name].lstrip("-").isdigit(), (name, response.headers[name])
    assert int(response.headers[RATE_LIMIT_HEADER]) == 2


def test_remaining_decrements_across_two_requests_on_one_credential(
    api: Client, owner: User, tenant: Tenant, tiny_limit: Any
) -> None:
    """The observable. A number that does not move is a number nobody can use."""
    api.force_login(owner)
    first = api.get(LIST_URL)
    second = api.get(LIST_URL)

    assert (first.status_code, second.status_code) == (200, 200)
    assert int(first.headers[RATE_LIMIT_REMAINING_HEADER]) == 1
    assert int(second.headers[RATE_LIMIT_REMAINING_HEADER]) == 0
    # Delta-seconds, matching Retry-After's unit: no clock-skew ambiguity, and a
    # window that has been touched has a real number of seconds left in it.
    assert 0 < int(second.headers[RATE_LIMIT_RESET_HEADER]) <= 60


# --- HDR-B-2: the binding bucket, and only it ---------------------------------


def test_the_headers_report_the_bucket_that_will_actually_refuse(
    api: Client, owner: User, tenant: Tenant, tenant_binds: Any
) -> None:
    """Twenty a minute per credential, three per tenant — three is the truth.

    Which bucket binds is not named on the wire: that a tenant's *other*
    credentials have used its allowance is capacity information about somebody
    else's client, and one number a caller can act on beats two they cannot.
    """
    api.force_login(owner)
    response = api.get(LIST_URL)

    assert response.status_code == 200
    assert int(response.headers[RATE_LIMIT_HEADER]) == 3
    assert int(response.headers[RATE_LIMIT_REMAINING_HEADER]) == 2
    for name in TRIPLE:
        assert "tenant" not in response.headers[name].lower()


def test_the_binding_bucket_is_recomputed_per_request(
    api: Client, owner: User, member: User, tenant: Tenant, tenant_binds: Any
) -> None:
    """A second credential in the same tenant spends the tenant's bucket too.

    The credential bucket is untouched at 20; the tenant bucket is what shrinks,
    and it is what the second client is told about.
    """
    api.force_login(owner)
    assert api.get(LIST_URL).status_code == 200
    assert api.get(LIST_URL).status_code == 200

    second = Client()
    second.force_login(member)
    response = second.get(LIST_URL)

    assert response.status_code == 200
    assert int(response.headers[RATE_LIMIT_HEADER]) == 3
    assert int(response.headers[RATE_LIMIT_REMAINING_HEADER]) == 0


# --- HDR-B-3: the refusal keeps its grammar -----------------------------------


def test_a_driven_429_carries_the_triple_and_retry_after(
    api: Client, owner: User, tenant: Tenant, tiny_limit: Any
) -> None:
    api.force_login(owner)
    assert api.get(LIST_URL).status_code == 200
    assert api.get(LIST_URL).status_code == 200
    refused = api.get(LIST_URL)

    assert refused.status_code == 429
    for name in TRIPLE:
        assert name in refused.headers, name
    assert int(refused.headers[RATE_LIMIT_REMAINING_HEADER]) == 0
    assert int(refused.headers[RATE_LIMIT_RESET_HEADER]) >= 1
    assert int(refused.headers[RETRY_AFTER_HEADER]) >= 1


def test_the_429_body_is_still_the_one_composers_refusal(
    api: Client, owner: User, tenant: Tenant, tiny_limit: Any
) -> None:
    """House rule 14 and E9: the numbers arrive beside the grammar, never instead.

    Compared against `wire_refusal` itself — the composer both doors render —
    so this fails the day a header is added by catching the exception and
    building a body here.
    """
    api.force_login(owner)
    api.get(LIST_URL)
    api.get(LIST_URL)
    refused = api.get(LIST_URL)

    body = json.loads(refused.content)
    expected = wire_refusal(RateLimited(retry_after=int(body.get("retry_after") or 1)))
    assert body == expected


def test_the_machine_door_speaks_the_refusal_and_carries_no_numbers(
    tenant: Tenant, owner: User
) -> None:
    """ADR core-19's recorded rejection, asserted rather than believed.

    A tool call is not an HTTP exchange with a response-header surface, so the
    refusal grammar is the whole channel there — and it is the SAME composer
    writing it, which is what keeps the two doors saying one thing. The
    mechanism that makes `/mcp` headerless is here rather than in a policy: a
    throttle hands its measurement to the request it was given, and the machine
    door's `ScopeSubject` is not one, so there is nothing to stamp and no way
    for a later edit to start stamping by accident.
    """
    refusal = wire_refusal(RateLimited(retry_after=7))
    assert refusal["code"] == "rate_limited"
    assert refusal["remedies"]

    subject = ScopeSubject(auth=owner, tenant=tenant)
    for throttle in default_throttles():
        throttle.allow_request(cast(Any, subject))
    assert recorded(subject) is None
    assert rate_limit_headers(subject) == {}

    stamped = {header.name for header in declared_response_headers()}
    assert set(TRIPLE) <= stamped


# --- HDR-B-4: stamped and exposed are one list --------------------------------


def test_the_three_names_join_cors_expose_headers() -> None:
    """HDR-A's census is what makes this a fact rather than an intention.

    A header the server stamps and CORS does not expose is a header a browser
    cannot read — the server telling the truth to nobody. The census in
    `test_response_headers.py` fails until this is true, which is why the two
    landed together.
    """
    exposed = set(settings.CORS_EXPOSE_HEADERS)
    assert {name.lower() for name in TRIPLE} <= exposed


# --- HDR-B-5: the documentation arrived by derivation -------------------------


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    rendered: dict[str, Any] = json.loads(json.dumps(api.get_openapi_schema()))
    return rendered


def test_the_document_carries_the_triple_on_every_throttled_operation(
    document: dict[str, Any],
) -> None:
    """No `docs.py` edit made this true: the declaration lives beside the throttle."""
    seen = 0
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            throttled = any(
                "rate_limited" in (response.get("x-refusal-codes") or ())
                for response in (operation.get("responses") or {}).values()
                if isinstance(response, dict)
            )
            if not throttled:
                continue
            seen += 1
            for status, response in operation["responses"].items():
                documented = set(response.get("headers") or {})
                assert set(TRIPLE) <= documented, f"{method.upper()} {path} {status}"
    assert seen, "no operation in the document is throttled"


def test_the_429_response_documents_the_triple_and_retry_after(
    document: dict[str, Any],
) -> None:
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            for status, response in (operation.get("responses") or {}).items():
                if "rate_limited" not in (response.get("x-refusal-codes") or ()):
                    continue
                documented = set(response.get("headers") or {})
                assert set(TRIPLE) | {RETRY_AFTER_HEADER} <= documented, (
                    f"{method.upper()} {path} {status}"
                )
