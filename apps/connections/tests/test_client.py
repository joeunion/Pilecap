"""The outbound client: the retry policy, the headers, and what it refuses.

Everything here runs against `httpx.MockTransport`, wrapped by the real
`RetryTransport` the factory ships — so what is under test is the policy the
product runs, not a re-implementation of it in the test. Nothing opens a socket.
"""

from __future__ import annotations

import httpx
import pytest

from apps.connections.client import (
    DEFAULT_RETRIES,
    IDEMPOTENCY_HEADER,
    RetryTransport,
    base_headers,
    http_client,
    idempotency_headers,
    post_idempotent,
)
from apps.connections.models import Connection
from apps.connections.services import revoke_connection
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.core import context
from apps.core.actor import Actor
from apps.core.exceptions import Forbidden
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

# No real sleeping in a test: the backoff curve is proven by what it was asked
# to wait for, not by waiting for it.
SLEPT: list[float] = []


@pytest.fixture(autouse=True)
def _no_sleeping() -> None:
    SLEPT.clear()


def _record_sleep(seconds: float) -> None:
    SLEPT.append(seconds)


class Upstream:
    """A scripted server: answers in order, and counts what it was asked."""

    def __init__(self, *statuses: int, headers: dict[str, str] | None = None) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []
        self.headers = headers or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.statuses) - 1)
        return httpx.Response(self.statuses[index], json={"ok": True}, headers=self.headers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _client(connection: Connection, upstream: Upstream, **kwargs: object) -> httpx.Client:
    return http_client(
        connection,
        base_url="https://upstream.invalid",
        transport=upstream.transport(),
        sleep=_record_sleep,
        **kwargs,  # type: ignore[arg-type]
    )


# --- Retries ------------------------------------------------------------------


def test_a_get_that_gets_a_503_is_asked_again(connection: Connection) -> None:
    upstream = Upstream(503, 503, 200)
    with _client(connection, upstream) as client:
        response = client.get("/things")

    assert response.status_code == 200
    assert len(upstream.requests) == 3, "the original plus DEFAULT_RETRIES"
    assert DEFAULT_RETRIES == 2
    assert SLEPT == [0.25, 0.5], "the backoff doubles"


def test_retries_run_out_and_the_last_answer_is_returned(connection: Connection) -> None:
    upstream = Upstream(503)
    with _client(connection, upstream) as client:
        response = client.get("/things")

    assert response.status_code == 503, "a failure is returned, never swallowed"
    assert len(upstream.requests) == 3


def test_a_post_is_never_retried_however_bad_the_answer(connection: Connection) -> None:
    """The load-bearing one: a repeated POST is a second order, a second charge."""
    upstream = Upstream(503, 200)
    with _client(connection, upstream) as client:
        response = client.post("/things", json={"a": 1})

    assert response.status_code == 503
    assert len(upstream.requests) == 1
    assert SLEPT == []


def test_a_post_with_an_idempotency_key_is_still_not_retried_here(
    connection: Connection,
) -> None:
    """The key makes it safe for the *caller* to retry. That decision is not this
    transport's, it is the activity's — see `client.IDEMPOTENT_METHODS`."""
    upstream = Upstream(503, 200)
    with _client(connection, upstream) as client:
        response = post_idempotent(client, "/things", key="order-42", json={"a": 1})

    assert response.status_code == 503
    assert len(upstream.requests) == 1
    assert upstream.requests[0].headers[IDEMPOTENCY_HEADER] == "order-42"


def test_a_404_is_an_answer_and_is_not_retried(connection: Connection) -> None:
    upstream = Upstream(404, 200)
    with _client(connection, upstream) as client:
        assert client.get("/gone").status_code == 404
    assert len(upstream.requests) == 1


def test_retry_after_beats_the_backoff_curve(connection: Connection) -> None:
    upstream = Upstream(429, 200, headers={"Retry-After": "7"})
    with _client(connection, upstream) as client:
        assert client.get("/things").status_code == 200
    assert SLEPT == [7.0], "an upstream that says when to come back is believed"


def test_retries_can_be_turned_off_at_the_call_site(connection: Connection) -> None:
    upstream = Upstream(503, 200)
    with _client(connection, upstream, retries=0) as client:
        assert client.get("/things").status_code == 503
    assert len(upstream.requests) == 1


def test_the_transport_is_the_one_the_factory_builds(connection: Connection) -> None:
    upstream = Upstream(200)
    with _client(connection, upstream) as client:
        assert isinstance(client._transport, RetryTransport)


# --- Headers ------------------------------------------------------------------


def test_the_credential_is_attached_by_the_factory_and_by_nobody_else(
    connection: Connection,
) -> None:
    upstream = Upstream(200)
    with _client(connection, upstream) as client:
        client.get("/things")

    sent = upstream.requests[0]
    assert sent.headers["Authorization"] == "Bearer an-access-token"
    assert sent.headers["User-Agent"] == "pilecap-connections/example"
    assert sent.headers["Accept"] == "application/json"


def test_a_connection_with_no_token_sends_no_authorization_header(
    tenant: Tenant, owner_actor: Actor
) -> None:
    from apps.connections.services import create_connection

    bare = create_connection(tenant=tenant, actor=owner_actor, provider="example", name="Bare")
    upstream = Upstream(200)
    with _client(bare, upstream) as client:
        client.get("/things")

    assert "authorization" not in upstream.requests[0].headers


def test_the_correlation_id_crosses_the_boundary(connection: Connection) -> None:
    """One trace from the door through the outbound call and back again."""
    context.bind(correlation_id="corr-1")
    upstream = Upstream(200)
    with _client(connection, upstream) as client:
        client.get("/things")

    assert upstream.requests[0].headers["X-Correlation-Id"] == "corr-1"


def test_base_headers_never_carry_the_webhook_secret(connection: Connection) -> None:
    assert WEBHOOK_SECRET not in str(base_headers(connection))


# --- What it refuses ------------------------------------------------------------


def test_a_revoked_connection_cannot_be_called_through(
    tenant: Tenant, owner_actor: Actor, connection: Connection
) -> None:
    revoke_connection(tenant=tenant, actor=owner_actor, connection=connection)
    with pytest.raises(Forbidden):
        http_client(connection)


def test_an_idempotency_key_must_be_a_real_value() -> None:
    with pytest.raises(ValueError):
        idempotency_headers("   ")
    assert idempotency_headers(" order-42 ") == {IDEMPOTENCY_HEADER: "order-42"}
