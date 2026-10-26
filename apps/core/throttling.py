"""Rate limiting, in the two units that mean something here.

`architecture.md`: *ninja throttling per token and per tenant, defaults in
settings; MCP tools share the same limiter.*

Two limits, because they answer different questions:

* **per credential** (`AuthRateThrottle`, ninja's own) — "is this one client
  looping?" A runaway integration or a bad retry loop shows up here first, and
  it is the limit that protects the customer from their own script.
* **per tenant** (`TenantRateThrottle`, below) — "is this one customer using
  more than their share?" A customer with forty tokens can be under every
  per-credential limit and still be the reason everyone else is slow. This is
  the limit that protects the other tenants.

Both are counted in the shared Redis cache, so the limit is the deployment's
and not each process's — four web processes with a local counter is a limit
four times higher than the one you wrote down.

Anonymous requests fall back to the client address, which is a weak identity and
is meant to be: an unauthenticated caller has no better one, and the rate for it
is set correspondingly low.

**Every door counts into the same buckets.** The MCP mount has no `HttpRequest`
to hand a throttle, so it builds a `ScopeSubject` out of the ASGI scope and the
principal the token resolved to, and `refusal()` runs *these same throttle
objects* against it. Not a parallel implementation with the same numbers — the
same classes, therefore the same cache keys, therefore literally one bucket per
tenant across REST and MCP. A limiter a client can dodge by switching doors is
not a limiter.

**And the throttle says its numbers** (ADR core-19). A 429 told a client it had
gone too fast and nothing told it beforehand, so the only way to find the limit
was to hit it and the only strategy on offer was to hit it again. Every throttle
here RECORDS `(limit, remaining, reset)` on the request as it checks, the one
`ContextMiddleware` stamps the `X-RateLimit-*` triple from what it finds, and
the OpenAPI document documents the three off the declarations at the bottom of
this module — one writer per header, no name spelled twice.

The recorded measurement is the **binding** bucket: of the credential's and the
tenant's, the one with the least headroom left, because that is the one that
will do the refusing. Reporting the roomier of two is worse than reporting
nothing — it is advice that runs out with no warning. Which bucket bound is NOT
on the wire: that a tenant's other credentials have spent its allowance is
capacity information about somebody else's client, and one number a caller can
act on beats two they cannot.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

from django.http import HttpRequest
from ninja.throttling import AnonRateThrottle as _NinjaAnonRateThrottle
from ninja.throttling import AuthRateThrottle as _NinjaAuthRateThrottle
from ninja.throttling import BaseThrottle, SimpleRateThrottle

from apps.core.api.docs import ResponseHeader, refuses_with
from apps.core.exceptions import RateLimited
from apps.core.models import Tenant

__all__ = [
    "RATE_LIMIT_HEADER",
    "RATE_LIMIT_REMAINING_HEADER",
    "RATE_LIMIT_RESET_HEADER",
    "RESPONSE_HEADERS",
    "AnonRateThrottle",
    "AuthRateThrottle",
    "BaseThrottle",
    "RateLimit",
    "ScopeSubject",
    "TenantRateThrottle",
    "default_throttles",
    "rate_limit_headers",
    "recorded",
    "refusal",
]

#: The triple, declared once each. `Reset` is DELTA-SECONDS and not a timestamp,
#: matching `Retry-After`'s unit: a client with a wrong clock can still subtract,
#: and two units for the same idea in one response is how a retry loop ends up
#: sleeping until 1970. The IETF `RateLimit-*` draft was considered and rejected
#: (ADR core-19): its field names have churned across revisions, and adopting
#: them once it is an RFC is additive — stamp both through a window.
RATE_LIMIT_HEADER = "X-RateLimit-Limit"
RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"

#: Where a throttle leaves its measurement for the middleware. Private to this
#: module: the middleware reads it through `rate_limit_headers()` and never
#: names it, so there is one spelling of the attribute as well as of the header.
_MEASUREMENT_ATTR = "_djb_rate_limit"


@dataclass(frozen=True)
class RateLimit:
    """One bucket's state at the moment it was checked, in delta-seconds."""

    limit: int
    remaining: int
    reset: int

    @property
    def headroom(self) -> float:
        """What fraction of the allowance is left — 0.0 spent, 1.0 untouched.

        A RATIO and not the raw remaining count, because the two buckets have
        different sizes: 5 left of 20 is tighter than 8 left of 1200, and the
        one that binds is the one that runs out first.
        """
        if self.limit <= 0:
            return 0.0
        return self.remaining / self.limit

    def binds_over(self, other: RateLimit) -> bool:
        """Whether this bucket is the one that will refuse before the other.

        Ordered on more than the ratio so that two equally-tight buckets
        resolve the same way every time: a header that flickered between two
        answers on identical requests would be unusable.
        """
        return (self.headroom, self.remaining, -self.reset) < (
            other.headroom,
            other.remaining,
            -other.reset,
        )


def record(request: Any, measured: RateLimit) -> None:
    """Keep the binding bucket's measurement on the request, and only it."""
    current = getattr(request, _MEASUREMENT_ATTR, None)
    if current is None or measured.binds_over(current):
        setattr(request, _MEASUREMENT_ATTR, measured)


def recorded(request: Any) -> RateLimit | None:
    """What the throttles measured on this request, or `None` if none did."""
    found = getattr(request, _MEASUREMENT_ATTR, None)
    return found if isinstance(found, RateLimit) else None


def rate_limit_headers(request: Any) -> dict[str, str]:
    """The triple, ready to stamp — empty when nothing was counted.

    Empty rather than zeroed: a request no bucket could count against (no
    resolved tenant, an unthrottled route) has no allowance to report, and
    `X-RateLimit-Remaining: 0` there would tell a client it was at a wall that
    does not exist.
    """
    measured = recorded(request)
    if measured is None:
        return {}
    return {
        RATE_LIMIT_HEADER: str(measured.limit),
        RATE_LIMIT_REMAINING_HEADER: str(measured.remaining),
        RATE_LIMIT_RESET_HEADER: str(measured.reset),
    }


#: One atomic check-and-spend in Redis, answering `{admitted, entries, oldest score}`.
#: Scores travel as strings: a Lua number handed back is truncated to an integer.
_WINDOW_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[2])
local entries = redis.call('ZCARD', KEYS[1])
local admitted = 0
if entries < tonumber(ARGV[3]) then
  redis.call('ZADD', KEYS[1], ARGV[1], ARGV[5])
  redis.call('EXPIRE', KEYS[1], ARGV[4])
  entries = entries + 1
  admitted = 1
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
return {admitted, entries, oldest[2] or false}
"""

#: A key of its own, so a deploy over a live cache never reads ninja's list as a set.
_WINDOW_SUFFIX = ":window"

#: The in-memory cache's check-and-spend: atomic within the one process it is shared by.
_LOCAL_SPEND = threading.Lock()


@dataclass(frozen=True)
class Spent:
    """What one check did to its bucket, read inside the check."""

    admitted: bool
    entries: int
    oldest: float | None
    now: float


def _redis_client(store: Any) -> Any | None:
    """The raw client under a django-redis cache, or `None` for any other store."""
    get_client = getattr(getattr(store, "client", None), "get_client", None)
    return get_client(write=True) if callable(get_client) else None


class Recording(SimpleRateThrottle):
    """Spends from its bucket atomically, and leaves the number it measured behind.

    One throttle object serves every request thread of its operation, so the
    check is one atomic step on the store and nothing it read lives on `self`:
    the measurement goes on the request, ninja's `wait()` reads a thread-local.
    Only an `HttpRequest` is recorded on — `/mcp` hands a `ScopeSubject` and
    speaks the refusal grammar instead (ADR core-19).

    Why-not ninja's check: read, decide, write back in three steps — 399 admitted of 50.
    """

    def __init__(self, rate: str | None = None) -> None:
        super().__init__(rate)
        self._last = threading.local()

    def allow_request(self, request: HttpRequest) -> bool:
        key = self.get_cache_key(request)
        limit, duration = self.num_requests, self.duration
        if key is None or limit is None or duration is None:
            self._last.spent = None
            return True
        spent = self._spend(key, limit=limit, duration=duration)
        self._last.spent = spent
        self._record_this_bucket(request, spent, limit=limit, duration=duration)
        return spent.admitted

    def wait(self) -> float | None:
        """ninja's recommended wait, from this thread's last check.

        Read off the thread-local and never `self`: other threads keep checking.
        """
        spent: Spent | None = getattr(self._last, "spent", None)
        if spent is None or self.num_requests is None or self.duration is None:
            return None
        left = self.duration if spent.oldest is None else self.duration - (spent.now - spent.oldest)
        available = self.num_requests - spent.entries + 1
        return left / available if available > 0 else None

    def _spend(self, key: str, *, limit: int, duration: int) -> Spent:
        """Check the bucket and spend from it in one step no other check can split."""
        now = float(type(self).timer())
        client = _redis_client(self.cache)
        if client is not None:
            admitted, entries, oldest = client.register_script(_WINDOW_SCRIPT)(
                keys=[self.cache.make_key(key + _WINDOW_SUFFIX)],
                args=[repr(now), repr(now - duration), limit, duration, f"{now!r}:{uuid4().hex}"],
            )
            return Spent(
                admitted=bool(admitted),
                entries=int(entries),
                oldest=None if oldest is None else float(oldest),
                now=now,
            )
        with _LOCAL_SPEND:
            history = [at for at in self.cache.get(key, []) if at > now - duration]
            admitted = len(history) < limit
            if admitted:
                history.insert(0, now)
                self.cache.set(key, history, duration)
        return Spent(
            admitted=admitted,
            entries=len(history),
            oldest=history[-1] if history else None,
            now=now,
        )

    def _record_this_bucket(self, subject: Any, spent: Spent, *, limit: int, duration: int) -> None:
        """Measure what the check just did, and leave it on the request.

        `subject` is typed `Any` and not `HttpRequest` on purpose: the machine
        door genuinely passes something else through `allow_request`'s
        signature (`refusal()`'s cast), so the isinstance below is a real
        question and not the dead branch a narrowed annotation would make of it.
        """
        if not isinstance(subject, HttpRequest):
            return
        # A slot frees when the OLDEST entry ages out; rounded up, as `refusal()` rounds.
        reset = duration if spent.oldest is None else duration - (spent.now - spent.oldest)
        record(
            subject,
            RateLimit(
                limit=limit,
                remaining=max(limit - spent.entries, 0),
                reset=max(math.ceil(reset), 0),
            ),
        )


class AnonRateThrottle(Recording, _NinjaAnonRateThrottle):
    """ninja's anonymous-address bucket, saying its numbers."""


class AuthRateThrottle(Recording, _NinjaAuthRateThrottle):
    """ninja's per-credential bucket, saying its numbers."""


class TenantRateThrottle(Recording, SimpleRateThrottle):
    """One bucket per tenant, however many credentials it holds.

    The rate comes from `NINJA_DEFAULT_THROTTLE_RATES["tenant"]`.
    """

    scope = "tenant"

    def get_cache_key(self, request: HttpRequest) -> str | None:
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            # No tenant resolved yet — an anonymous request, or a token request
            # before its auth callback has run. The per-credential limit still
            # applies; this one has nothing to count against.
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(tenant.pk)}


def default_throttles() -> list[BaseThrottle]:
    """What `config/api.py` applies to every route, and what `/mcp` applies too.

    Declared as a function rather than a module-level list because a throttle
    reads its rate from settings when it is constructed, and settings are not
    loaded when this module is first imported.
    """
    return [AuthRateThrottle(), TenantRateThrottle()]


@dataclass(frozen=True)
class ScopeSubject:
    """What a throttle reads off a request, for a door that has no request.

    ninja's throttles ask a request three questions and no more: what
    authenticated it (`auth`, which `AuthRateThrottle` hashes), whose tenant it
    is (`tenant`, which `TenantRateThrottle` above reads), and where it came from
    (`META`, for the anonymous fallback). This answers those three, so the *same*
    throttle objects can be run against an ASGI scope.

    The alternative — a second set of throttle classes for the machine door —
    would be two formulas producing two cache keys, and a tenant would get one
    allowance per door. The whole reason this type exists is that it does not.

    `auth` is the object the API's own `ApiTokenAuth` returns (the `User`), so
    the hashed identity is the same string on both doors.
    """

    auth: Any
    tenant: Tenant | None
    # Upper case because that is the attribute a throttle reads on an
    # `HttpRequest`; a tidier name here would simply not be found.
    META: dict[str, str] = field(default_factory=dict)


def refusal(
    *,
    subject: ScopeSubject,
    throttles: Sequence[BaseThrottle] | None = None,
) -> RateLimited | None:
    """The refusal this call earns, or `None` if it is within the limits.

    Returns the domain's own `RateLimited` rather than raising, because the
    caller is an ASGI middleware that has to write a response rather than let an
    exception escape into the transport. `retry_after` is rounded **up**: a
    client told to come back in zero seconds comes back immediately and is
    refused again.
    """
    for throttle in throttles if throttles is not None else default_throttles():
        # The cast is the whole trick: `allow_request` passes its argument
        # straight to `get_cache_key`, which only ever reads the three attributes
        # `ScopeSubject` has. Nothing here touches an `HttpRequest` method.
        if not throttle.allow_request(cast(HttpRequest, subject)):
            wait = throttle.wait()
            return RateLimited(retry_after=int(wait) + 1 if wait else None)
    return None


# --- what the document says about all this ------------------------------------
#
# Declared HERE, beside the writer, and collected by
# `docs.declared_response_headers()`. Nothing in `apps/core/api/docs.py` was
# edited to make the triple appear in the contract — that is the whole shape
# this mechanism landed, and this is the first thing to arrive through it.


def _on_a_throttled_operation(
    operation: Mapping[str, Any], status: str, response: Mapping[str, Any]
) -> bool:
    """Every response of an operation the throttles run on, the 429 included.

    "Throttled" is read off the document rather than off the API's `throttle=`:
    an operation that can answer `rate_limited` is an operation a throttle
    guards, and the refusal derivation already put that fact in the document.
    So a product that narrows the throttles on one route narrows this with it,
    through the route's own `@refuses(...)` and nothing else.
    """
    return any(
        refuses_with(candidate, RateLimited.code)
        for candidate in (operation.get("responses") or {}).values()
        if isinstance(candidate, Mapping)
    )


RESPONSE_HEADERS: tuple[ResponseHeader, ...] = (
    ResponseHeader(
        name=RATE_LIMIT_HEADER,
        description=(
            "How many requests this allowance is, in the window it counts over. It is "
            "the tighter of the limits that apply to you; which one that is is not said."
        ),
        covers=_on_a_throttled_operation,
    ),
    ResponseHeader(
        name=RATE_LIMIT_REMAINING_HEADER,
        description=(
            "How many requests are left in that allowance, this one included. At `0` the "
            "next request is refused with `429 rate_limited`; slow down before then."
        ),
        covers=_on_a_throttled_operation,
    ),
    ResponseHeader(
        name=RATE_LIMIT_RESET_HEADER,
        description=(
            "How many seconds until the allowance frees a place — seconds from now, the "
            "same unit as `Retry-After`, never a timestamp."
        ),
        covers=_on_a_throttled_operation,
    ),
)
