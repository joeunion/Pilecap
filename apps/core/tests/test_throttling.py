"""Rate limiting: the refusal, and the two units it counts in.

The rates are lowered to something a test can reach rather than waited out, but
everything else is the real path — the real API, the real throttle classes, the
real exception handler that turns ninja's `Throttled` into the same body a
service's own `RateLimited` produces.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.core.throttling import AuthRateThrottle, TenantRateThrottle, default_throttles

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"


@pytest.fixture(autouse=True)
def _empty_bucket() -> Any:
    """Counters live in the cache, so a test that inherits one is a flake."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tiny_limit() -> Any:
    """Two requests a minute, on the live API's own operations.

    The rate is passed to the constructor rather than set in Django settings:
    ninja validates `NINJA_DEFAULT_THROTTLE_RATES` into its own settings object
    once, at import, so changing the Django setting mid-test changes nothing.
    (That the shipped values *do* reach ninja is proved separately, below.)
    """
    from config.api import api

    replaced: list[Any] = [AuthRateThrottle("2/min"), TenantRateThrottle("2/min")]
    originals: list[tuple[Any, list[Any]]] = []
    for bound in api._get_bound_routers():
        for _path, view in bound.path_operations.items():
            for operation in view.operations:
                originals.append((operation, operation.throttle_objects))
                operation.throttle_objects = replaced
    yield
    for operation, throttles in originals:
        operation.throttle_objects = throttles


def test_going_too_fast_is_a_429_with_the_domain_body(
    api: Client, owner: User, tenant: Tenant, tiny_limit: Any
) -> None:
    api.force_login(owner)
    assert api.get(LIST_URL).status_code == 200
    assert api.get(LIST_URL).status_code == 200

    refused = api.get(LIST_URL)
    assert refused.status_code == 429
    body = json.loads(refused.content)
    assert body["code"] == "rate_limited"
    assert body["detail"]
    # A client that is told when to come back stops hammering.
    assert int(refused.headers["Retry-After"]) >= 1


def test_the_tenant_bucket_is_shared_by_everybody_in_it(
    api: Client, owner: User, member: User, tenant: Tenant, tiny_limit: Any
) -> None:
    """A customer with forty tokens can be under every per-credential limit and
    still be the reason everybody else is slow. This is the limit for that."""
    api.force_login(owner)
    assert api.get(LIST_URL).status_code == 200
    assert api.get(LIST_URL).status_code == 200

    second = Client()
    second.force_login(member)
    # A different credential, so the per-credential bucket is empty — but the
    # same tenant, and that bucket is not.
    assert second.get(LIST_URL).status_code == 429


def test_a_request_with_no_tenant_is_not_counted_against_one(
    api: Client, nomad: User, tiny_limit: Any
) -> None:
    """Nothing to count against is not the same as a free pass: the
    per-credential limit still applies."""
    throttle = TenantRateThrottle()

    class Bare:
        tenant = None

    assert throttle.get_cache_key(Bare()) is None  # type: ignore[arg-type]

    api.force_login(nomad)
    assert api.get(LIST_URL).status_code == 200
    assert api.get(LIST_URL).status_code == 200
    assert api.get(LIST_URL).status_code == 429


def test_the_shipped_rates_reach_ninja_and_are_generous_enough_to_leave_on(
    settings: Any,
) -> None:
    """Two claims: the settings are actually wired, and they are livable.

    A limit people turn off in production is not a limit, so the shipped
    numbers are deliberately loose enough that only a loop hits them.
    """
    rates = settings.NINJA_DEFAULT_THROTTLE_RATES
    assert set(rates) == {"auth", "tenant", "anon", "user"}
    # What ninja actually resolved, not what Django was told.
    assert AuthRateThrottle().rate == rates["auth"]
    assert TenantRateThrottle().rate == rates["tenant"]
    assert [type(one).__name__ for one in default_throttles()] == [
        "AuthRateThrottle",
        "TenantRateThrottle",
    ]
    for scope, rate in rates.items():
        count, _, _period = str(rate).partition("/")
        assert int(count) >= 60, f"{scope} is tight enough that somebody will disable it"
