"""Rate limiting: the refusal, and the two units it counts in.

The rates are lowered to something a test can reach rather than waited out, but
everything else is the real path — the real API, the real throttle classes, the
real exception handler that turns ninja's `Throttled` into the same body a
service's own `RateLimited` produces.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.http import HttpRequest
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.core.throttling import (
    AnonRateThrottle,
    AuthRateThrottle,
    RateLimit,
    TenantRateThrottle,
    default_throttles,
    recorded,
)

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
    per-credential limit still applies.

    **The first two answers are 403 since Phase R and the property is the same
    one, said more sharply.** A person with no membership resolves no tenant, so
    the widget list refuses them before it reads anything (ADR core-27) — and
    the throttle runs at the door, ahead of the view, so a refused request is
    still a counted request. That is exactly what has to be true: a limit that
    only counted requests it liked would be a limit somebody could exhaust for
    free by sending ones it did not.
    """
    throttle = TenantRateThrottle()

    class Bare:
        tenant = None

    assert throttle.get_cache_key(Bare()) is None  # type: ignore[arg-type]

    api.force_login(nomad)
    assert api.get(LIST_URL).status_code == 403
    assert api.get(LIST_URL).status_code == 403
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


# --- under concurrency: one shared throttle object, many threads, both stores --

THREADS = 16
PER_THREAD = 100
LIMIT = 50


def _redis_answers(url: str) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection(
            (parsed.hostname or "127.0.0.1", parsed.port or 6379), timeout=0.5
        ):
            return True
    except OSError:
        return False


@pytest.fixture(params=["local", "redis"])
def store(request: pytest.FixtureRequest, settings: Any) -> Iterator[str]:
    """Both counters the throttles run on; the Redis one under a key prefix of its own."""
    if request.param == "redis":
        if not _redis_answers(settings.CACHE_URL):
            pytest.skip(f"no Redis listening on {settings.CACHE_URL}; start the compose stack")
        settings.CACHES = {
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": settings.CACHE_URL,
                "KEY_PREFIX": f"ls-throttle-{uuid4().hex}",
                "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            }
        }
        yield "redis"
        # Never `clear()`: on Redis that is FLUSHDB over every checkout's cache.
        cast(Any, cache).delete_pattern("*")
        return
    yield "local"


def _request(*, auth: Any = None, address: str = "203.0.113.7") -> HttpRequest:
    made = RequestFactory().get("/", REMOTE_ADDR=address)
    made.auth = auth  # type: ignore[attr-defined]
    return made


def _in_threads(threads: int, work: Callable[[int], list[Any]]) -> list[list[Any]]:
    """`work(i)` on `threads` threads released together; each thread's results, in order."""
    start = threading.Barrier(threads)

    def run(index: int) -> list[Any]:
        start.wait()
        return work(index)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        return list(pool.map(run, range(threads)))


def test_one_credential_sixteen_threads_exact_count(store: str) -> None:
    """Exactly `limit` of 1600 simultaneous requests are admitted — never `limit ± threads`."""
    throttle = AuthRateThrottle(f"{LIMIT}/min")

    def spend(_index: int) -> list[bool]:
        return [throttle.allow_request(_request(auth="credential-one")) for _ in range(PER_THREAD)]

    admitted = sum(sum(one) for one in _in_threads(THREADS, spend))
    assert admitted == LIMIT, f"{store}: {admitted} admitted of a {LIMIT} allowance"


def test_headers_are_consistent_under_concurrency(store: str) -> None:
    """`Remaining` falls through every value once and never rises; `Reset` agrees."""
    throttle = AuthRateThrottle(f"{LIMIT}/min")

    def spend(_index: int) -> list[tuple[bool, RateLimit]]:
        seen = []
        for _ in range(PER_THREAD):
            made = _request(auth="credential-one")
            allowed = throttle.allow_request(made)
            measured = recorded(made)
            assert measured is not None
            seen.append((allowed, measured))
        return seen

    per_thread = _in_threads(THREADS, spend)
    for seen in per_thread:
        remaining = [measured.remaining for _allowed, measured in seen]
        assert remaining == sorted(remaining, reverse=True), f"{store}: {remaining}"
    every = [pair for seen in per_thread for pair in seen]
    admitted = sorted(measured.remaining for allowed, measured in every if allowed)
    assert admitted == list(range(LIMIT)), f"{store}: {admitted}"
    assert all(measured.remaining == 0 for allowed, measured in every if not allowed)
    resets = {measured.reset for _allowed, measured in every}
    assert max(resets) - min(resets) <= 1, f"{store}: {sorted(resets)}"
    assert all(measured.limit == LIMIT for _allowed, measured in every)


def test_anonymous_buckets_are_per_address(store: str) -> None:
    """Two addresses, eight threads each: two buckets, each admitting exactly `limit`."""
    throttle = AnonRateThrottle(f"{LIMIT}/min")
    addresses = ("198.51.100.1", "198.51.100.2")

    def spend(index: int) -> list[tuple[str, bool]]:
        address = addresses[index % 2]
        return [
            (address, throttle.allow_request(_request(address=address))) for _ in range(PER_THREAD)
        ]

    results = [pair for seen in _in_threads(THREADS, spend) for pair in seen]
    for address in addresses:
        admitted = sum(1 for at, allowed in results if at == address and allowed)
        assert admitted == LIMIT, f"{store}: {address} admitted {admitted}"
