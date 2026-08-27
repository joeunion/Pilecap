"""The one way this product makes an outbound call.

`requests` is not in the tree and a bare `httpx.Client()` is not either
(`django-conventions` §14): both give you a call with no timeout, no retry
policy, no correlation header and no idea which tenant it was for. Everything
external goes through `http_client(connection)`, and — with the single
documented exception of the OAuth code exchange, which the protocol makes
synchronous — it happens **inside a Temporal activity**, where a failure is a
retry rather than a 500 on somebody's request.

Four things the factory is for:

* **A timeout, always.** `httpx`'s default is five seconds on connect and none
  on read; a hung upstream with no read timeout is a worker thread that never
  comes back.
* **Retries on idempotent methods only.** See `RetryTransport`.
* **The credential, attached once**, out of the connection's encrypted
  credentials — so no caller reads them and no caller can log them.
* **The trace, carried across the boundary.** `X-Correlation-Id` and
  `traceparent` go out with the request, so the upstream's answer joins to the
  request that caused it (`architecture.md`, "Traceability").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from opentelemetry import trace

from apps.connections.models import Connection
from apps.core import context
from apps.core.exceptions import Forbidden

# Seconds. Overridable per call site, because "how long is too long" is a
# property of the upstream and not of this module.
DEFAULT_TIMEOUT = 10.0

# How many *extra* attempts a retryable response gets.
DEFAULT_RETRIES = 2

# Seconds for the first backoff; doubled per attempt.
DEFAULT_BACKOFF = 0.25

# The methods that may be repeated without asking anybody. RFC 9110's
# idempotent set minus the ones nobody sends. **POST is not here**, and adding
# it would be the bug: a retried POST that the upstream did receive is a second
# charge, a second message, a second order. A POST that is genuinely safe to
# repeat says so with an `Idempotency-Key` and is retried by the thing that owns
# the decision — the Temporal activity around the call — not silently in here.
IDEMPOTENT_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})

# The answers worth asking again: the upstream said "not now", not "no".
RETRY_STATUSES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

IDEMPOTENCY_HEADER = "Idempotency-Key"
CORRELATION_HEADER = "X-Correlation-Id"


class RetryTransport(httpx.BaseTransport):
    """Repeat an idempotent request that got a retryable answer.

    Wrapping a transport rather than looping at the call site is what makes the
    policy impossible to forget: every client the factory builds has it, and a
    caller cannot opt out by writing the call slightly differently.

    `Retry-After` is honoured when the upstream sends one, because a server that
    has told you when to come back has told you something the backoff curve
    cannot know.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport,
        *,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._retries = max(0, int(retries))
        self._backoff = float(backoff)
        self._sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 0
        while True:
            response = self._transport.handle_request(request)
            if not self._should_retry(request, response, attempt):
                return response
            # The body has to be drained before the connection can be reused,
            # and the response is being thrown away anyway.
            response.read()
            response.close()
            self._sleep(self._delay(response, attempt))
            attempt += 1

    def _should_retry(self, request: httpx.Request, response: httpx.Response, attempt: int) -> bool:
        return (
            attempt < self._retries
            and request.method.upper() in IDEMPOTENT_METHODS
            and response.status_code in RETRY_STATUSES
        )

    def _delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.strip().isdigit():
            return float(retry_after.strip())
        return float(self._backoff * (2**attempt))

    def close(self) -> None:
        self._transport.close()


def base_headers(connection: Connection) -> dict[str, str]:
    """What every request through this connection carries.

    The access token is read here and **nowhere else**, which is the point: no
    route, no activity and no product code ever holds the decrypted credential
    in a local variable it might log.
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": f"pilecap-connections/{connection.provider}",
    }
    token = connection.access_token
    if token:
        headers["Authorization"] = f"Bearer {token}"

    correlation_id = context.value("correlation_id")
    if correlation_id:
        headers[CORRELATION_HEADER] = str(correlation_id)

    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        headers["traceparent"] = (
            f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}-"
            f"{span_context.trace_flags:02x}"
        )
    return headers


def http_client(
    connection: Connection,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    base_url: str = "",
    transport: httpx.BaseTransport | None = None,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Client:
    """An `httpx.Client` bound to one tenant's connection.

    Used as a context manager, always — an un-closed client leaks a connection
    pool per call:

        with http_client(connection) as client:
            response = client.get("/v1/things")

    `transport` is how a test injects `httpx.MockTransport`; it is wrapped in
    `RetryTransport` exactly as the real one is, so what the test exercises is
    the retry policy the product ships and not a copy of it.
    """
    if connection.status == Connection.Status.REVOKED:
        # Not `NotFound`: the caller is entitled to know the connection exists
        # and is theirs. It is the *credential* that is gone, on purpose.
        raise Forbidden("This connection has been revoked.")

    resolved = base_url or _base_url_for(connection)
    inner = transport if transport is not None else httpx.HTTPTransport()
    return httpx.Client(
        base_url=resolved,
        timeout=httpx.Timeout(timeout),
        headers=base_headers(connection),
        transport=RetryTransport(inner, retries=retries, backoff=backoff, sleep=sleep),
        follow_redirects=False,
    )


def idempotency_headers(key: str) -> dict[str, str]:
    """The header that makes a POST safe to repeat.

    The value is the caller's to choose and it has one requirement: it must be
    **stable across the retries of one logical write** and different between two
    different writes. A `uuid4()` minted at the call site fails the first half —
    every retry gets a fresh key and the upstream sees three orders. Derive it
    from the thing being written (a row's primary key, an invoice number), the
    same way `workflow_id()` is derived.
    """
    stripped = str(key).strip()
    if not stripped:
        raise ValueError("An idempotency key must be a stable, non-empty value.")
    return {IDEMPOTENCY_HEADER: stripped}


def post_idempotent(
    client: httpx.Client,
    url: str,
    *,
    key: str,
    **kwargs: Any,
) -> httpx.Response:
    """`client.post`, with the idempotency key attached rather than remembered.

    A helper rather than a convention, because "remember to set the header" is
    the kind of instruction that holds for four call sites and then does not.
    """
    headers = {**dict(kwargs.pop("headers", {}) or {}), **idempotency_headers(key)}
    return client.post(url, headers=headers, **kwargs)


def _base_url_for(connection: Connection) -> str:
    """The provider's base URL, or the one stored on the connection.

    A provider that this deployment has no adapter for is not an error here —
    a connection can carry its own `base_url` (a self-hosted instance, a
    sandbox), and a client with an empty base URL still works against absolute
    URLs.
    """
    from apps.connections.providers import registered

    provider = registered().get(connection.provider)
    if provider is not None and provider.base_url:
        return str(provider.base_url)
    return str((connection.credentials or {}).get("base_url", "") or "")
