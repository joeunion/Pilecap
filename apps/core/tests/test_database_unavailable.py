"""Slot exhaustion is a 503 with retry semantics — at every depth it can erupt.

**What paid for this file.** Under staged load, 6,973 of its
7,040 errors were the database refusing a connection: `psycopg` raised
`OperationalError`, nothing classified it, and every one of them came back as a
bare HTTP 500 — at the exact moment a client should have been told to back off.
3,340 of them were counted in a single ladder step. A 500 says "this request was
a bug"; a 503 with `Retry-After` says "come back in a moment", which was the
truth, and only one of those two makes a client behave.

**The depths, and why one seam could not have been enough.** Under real slot
exhaustion the *first* database touch of a request is not the view's query. It
is the session load that `TenantMiddleware` triggers — above ninja, before any
operation has been chosen, where **no `@api.exception_handler` is ever
consulted**. So this module drives the fault at each depth separately, and the
split between the two seams was established by severing each and re-running
this file rather than by reading ninja's source:

* **middleware** — an authed request whose session read hits the fault;
* **auth** — a bearer request whose token lookup hits it;
* **route** — a request whose first *view* query hits it;
* **MCP** — the machine door's twin, which has no status codes at all.

All four answer with the body `core.exceptions.wire_refusal` composed and the
status `config/api.py`'s one table holds. There is one composer and one status
table; what varies is only which seam handed the refusal to them.

**The negatives are criteria, not decoration.** A classifier that answers 503 to
"the database said no" instead of to "the database could not be reached" would
turn every deadlock and every query bug into a retry loop against a healthy
server. `40P01`, `57014`, `55P03`, `ProgrammingError` and `IntegrityError` are
each pinned here to the answer they gave.

DOES NOT COVER — declared:

* the **socket door**. A consumer's connect-time database touch is outside every
  seam here (there is no ninja and no `handler500` on the websocket path); the
  ADR names it as the trigger to revisit.
* the **workflow worker**. An activity's `OperationalError` is Temporal's to
  retry and is not an HTTP answer at all.
* **which real faults present with no SQLSTATE.** The classifier's
  sqlstate-absent leg is pinned here for the shapes injected below (a bare
  `psycopg.OperationalError`, and `PoolTimeout`'s shape). A managed-database
  failover may present a shape nobody here enumerated; RELOAD-1's live run is
  the only honest instrument for that.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import psycopg
import pytest
from django.db import IntegrityError, OperationalError, ProgrammingError, connection
from django.db.backends.utils import CursorWrapper
from django.test import Client, RequestFactory
from mcp.server.mcpserver.exceptions import ToolError
from psycopg import errors as pg

from apps.accounts.models import User
from apps.core.exceptions import (
    REFUSALS,
    DatabaseUnavailable,
    is_connection_shaped,
    refusal_message,
    sqlstate_of,
)
from apps.core.models import Organization, Tenant
from apps.core.tests.test_refusal_wire import mcp_context, tool
from config.api import CODE_STATUS, api

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"

POOL_TIMEOUT_MESSAGE = "couldn't get a connection after 30.00 sec"


def pool_timeout() -> Exception:
    """What POOL-1's bounded pool raises at ITS exhaustion.

    **Resolved at runtime, not imported.** `psycopg_pool` arrives with POOL-1's
    lockfile and the two rungs are in the same wave, so a static import here
    would be a test that cannot run until a sibling merges — and a `type: ignore`
    for the missing module would become an UNUSED ignore, and a mypy error, the
    day it lands. Once the package is on the tree this returns the real class.

    Until then the stand-in is not an approximation of anything. `PoolTimeout`
    subclasses `psycopg.OperationalError` and carries no SQLSTATE — nothing was
    ever asked of a server, so there is no code for one to have sent — and that
    shape is the entirety of what `is_connection_shaped` reads. Nothing in the
    classifier imports `psycopg_pool` either; the two rungs meet by shape.
    """
    if importlib.util.find_spec("psycopg_pool") is not None:  # pragma: no cover
        real: Any = importlib.import_module("psycopg_pool").PoolTimeout
        return cast(Exception, real(POOL_TIMEOUT_MESSAGE))

    class PoolTimeout(psycopg.OperationalError):
        """`psycopg_pool.PoolTimeout`'s shape, for a tree that has not got it yet."""

    return PoolTimeout(POOL_TIMEOUT_MESSAGE)


# --- Driving the fault -------------------------------------------------------


def as_delivered(exc: Exception) -> Exception:
    """`exc` as Django's own wrapper hands it to application code.

    Not a convenience: it is the difference between what this test asserts about
    and what production sees. `psycopg.errors.TooManyConnections` never reaches
    a view — `BaseDatabaseWrapper.wrap_database_errors` catches it and re-raises
    `django.db.OperationalError(*args)` with the psycopg error as `__cause__`,
    and the Django class carries no SQLSTATE at all. A classifier tested against
    the psycopg exception directly would pass here and read `None` in
    production, which is exactly how it would answer 503 to a deadlock.
    """
    try:
        with connection.wrap_database_errors:
            raise exc
    except Exception as delivered:  # noqa: BLE001 - every driver error, re-delivered
        return delivered


@contextmanager
def every_statement_raises(exc: Exception) -> Iterator[None]:
    """Slot exhaustion, at the seam every query in the process goes through.

    `CursorWrapper._execute` is where a statement meets the driver, and the
    `wrap_database_errors` block is kept so the exception arrives *wrapped*,
    exactly as it would from a real refusal. Nothing reaches Postgres, so the
    test's own transaction is not poisoned and the fixtures survive.
    """
    original = CursorWrapper._execute  # type: ignore[attr-defined]

    def _execute(self: Any, sql: Any, params: Any, *ignored: Any) -> Any:
        with self.db.wrap_database_errors:
            raise exc

    CursorWrapper._execute = _execute  # type: ignore[attr-defined]
    try:
        yield
    finally:
        CursorWrapper._execute = original  # type: ignore[attr-defined]


def too_many_connections() -> Exception:
    return as_delivered(pg.TooManyConnections("sorry, too many clients already"))


def body_of(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def assert_is_the_refusal(body: dict[str, Any]) -> None:
    """The one body, whichever seam composed it."""
    assert body["code"] == "database_unavailable"
    assert body["detail"]
    assert body["remedies"], "a refusal with no remedies is a dead end with a status code"
    # The registry's internal prose is for whoever is holding the refusal and
    # never travels; it names the pool and the slot count.
    assert "remedy" not in body


@pytest.fixture
def uncaught_door() -> Client:
    """A client for the depth where Django records an uncaught exception.

    A fault above the ninja mount reaches `handler500` only after Django has
    sent `got_request_exception`, and the test client's default is to re-raise
    that at the caller instead of handing back the response. A real HTTP client
    gets the response; so does this one.

    **Every other depth in this file deliberately uses the strict client.** That
    is not a convenience — it is an assertion: a fault ninja can see is answered
    *inside* ninja, with no uncaught exception registered, so an outage does not
    also become one error-tracker event per request on top of the 503. Remove
    `@api.exception_handler(OperationalError)` and those tests stop returning a
    response at all, which is the plant-verify for the second seam.
    """
    return Client(raise_request_exception=False)


def assert_retry_after(response: Any) -> None:
    header = response.headers["Retry-After"]
    assert int(header) >= 1, "a Retry-After a client cannot wait for is not retry semantics"


# --- Depth 1: the middleware chain, above ninja entirely ---------------------


def test_a_fault_in_the_middleware_chain_answers_503(
    uncaught_door: Client, owner: User, tenant: Tenant, root_org: Organization
) -> None:
    """The depth that carried the majority of LOAD-1b's 6,973 errors.

    `TenantMiddleware` reads `request.user`, which resolves the lazy session,
    which is the request's first statement. No route has been chosen, no ninja
    operation exists, and `@api.exception_handler` is not in the picture — the
    only seam holding both this request and this exception is `handler500`.
    Severing `handler500` in `config/urls.py` fails THIS test with `500 == 503`
    and leaves every other test in this file green; that is the plant-verify
    that says the two entry points are two and not one.

    `raise_request_exception=False` because Django's uncaught-exception signal
    fires for a fault this deep whatever the response ends up being, and the
    test client's default is to re-raise it at the caller. What a real HTTP
    client receives is the response, which is what is asserted.
    """
    uncaught_door.force_login(owner)

    with every_statement_raises(pg.TooManyConnections("sorry, too many clients already")):
        response = uncaught_door.get(WIDGETS)

    assert response.status_code == 503
    assert_retry_after(response)
    assert_is_the_refusal(body_of(response))


# --- Depth 2: authentication, inside ninja but outside its try ---------------


def test_a_fault_in_token_auth_answers_503(monkeypatch: pytest.MonkeyPatch, client: Client) -> None:
    """`ApiTokenAuth`'s lookup is a bearer request's first statement.

    A depth the dispatch expected to be outside ninja and which measurement put
    inside it: `Operation.run` does call `_run_checks` before its own `try`, but
    `_run_authentication` (ninja 1.6.3) carries a `try` of its own that hands an
    authenticator's exception to `api.on_exception`. So this one is answered by
    `on_operational_error`, and it stays green when `handler500` is severed —
    which is the evidence, and is why the correction is written down here rather
    than repeated as the brief had it.
    """

    def boom(**kwargs: Any) -> None:
        raise too_many_connections()

    monkeypatch.setattr("apps.accounts.auth.authenticate_token", boom)

    response = client.get(WIDGETS, headers={"Authorization": "Bearer irrelevant"})

    assert response.status_code == 503
    assert_retry_after(response)
    assert_is_the_refusal(body_of(response))


# --- Depth 3: the view's own query, below ninja ------------------------------


def test_a_fault_in_a_view_query_answers_503(
    monkeypatch: pytest.MonkeyPatch, client: Client, owner: User, root_org: Organization
) -> None:
    """The depth a mapper seam alone could see — and it still has to be right."""

    def boom(**kwargs: Any) -> None:
        raise too_many_connections()

    monkeypatch.setattr("apps.example.api.list_widgets", boom)
    client.force_login(owner)

    response = client.get(WIDGETS)

    assert response.status_code == 503
    assert_retry_after(response)
    assert_is_the_refusal(body_of(response))


# --- Depth 4: the machine door, which has no status codes at all -------------


def test_the_machine_door_says_the_same_thing(
    monkeypatch: pytest.MonkeyPatch,
    client: Client,
    owner: User,
    tenant: Tenant,
    root_org: Organization,
) -> None:
    """One refusal, two doors, one grammar — the E9 criterion shape.

    The MCP rendering is string-compared against the REST body's own fields, so
    the two cannot come to describe one outage differently. `tool_call` used to
    let this escape as a traceback, which is what an assistant would have shown
    a person during the outage.
    """

    def boom(**kwargs: Any) -> None:
        raise too_many_connections()

    monkeypatch.setattr("apps.example.api.list_widgets", boom)
    monkeypatch.setattr("apps.example.mcp.list_widgets", boom)

    client.force_login(owner)
    rest = body_of(client.get(WIDGETS))

    with pytest.raises(ToolError) as raised:
        tool("list_widgets")(ctx=mcp_context(owner, tenant, root_org))

    assert str(raised.value) == refusal_message(rest)
    assert str(raised.value).startswith("database_unavailable: ")


# --- The pool's own exhaustion -----------------------------------------------


def test_a_pool_timeout_is_in_the_caught_set() -> None:
    """The bounded pool answers 503, not a 30-second hang and then a 500.

    `PoolTimeout` carries no SQLSTATE — nothing was ever asked of a server — so
    it is caught by the classifier's connection-establishment leg rather than by
    a code. That leg is the judgment call this test pins down.
    """
    delivered = as_delivered(pool_timeout())

    assert sqlstate_of(delivered) is None
    assert is_connection_shaped(delivered)


def test_a_network_refusal_with_no_sqlstate_is_in_the_caught_set() -> None:
    """`psycopg.connect()` against a box that is not answering. Same leg."""
    delivered = as_delivered(
        psycopg.OperationalError("connection failed: Connection refused\n\tIs the server running?")
    )

    assert sqlstate_of(delivered) is None
    assert is_connection_shaped(delivered)


# --- The classifier, stated closed -------------------------------------------


@pytest.mark.parametrize(
    ("exc", "sqlstate"),
    [
        (pg.TooManyConnections("sorry, too many clients already"), "53300"),
        (pg.CannotConnectNow("the database system is starting up"), "57P03"),
        (pg.ConnectionFailure("server closed the connection unexpectedly"), "08006"),
        (pg.ConnectionException("connection exception"), "08000"),
        (pg.SqlclientUnableToEstablishSqlconnection("could not connect"), "08001"),
    ],
)
def test_the_caught_sqlstates(exc: psycopg.Error, sqlstate: str) -> None:
    delivered = as_delivered(exc)
    assert sqlstate_of(delivered) == sqlstate
    assert is_connection_shaped(delivered)


@pytest.mark.parametrize(
    ("exc", "sqlstate"),
    [
        # A deadlock is not "come back later" — it is "this pair of transactions
        # cannot both proceed", and one of them already lost. Retrying it as a
        # 503 would be a retry loop against a perfectly healthy database.
        (pg.DeadlockDetected("deadlock detected"), "40P01"),
        # The statement timed out. The connection is fine; the query is not.
        (pg.QueryCanceled("canceling statement due to statement timeout"), "57014"),
        # A lock the caller would not wait for. Same reasoning.
        (pg.LockNotAvailable("could not obtain lock on row"), "55P03"),
    ],
)
def test_the_operational_errors_that_stay_500(exc: psycopg.Error, sqlstate: str) -> None:
    delivered = as_delivered(exc)
    assert sqlstate_of(delivered) == sqlstate
    assert not is_connection_shaped(delivered)


def test_a_query_bug_is_not_connection_shaped() -> None:
    """`ProgrammingError` is not even an `OperationalError`. Belt, stated."""
    delivered = as_delivered(pg.UndefinedColumn('column "nope" does not exist'))

    assert isinstance(delivered, ProgrammingError)
    assert not isinstance(delivered, OperationalError)
    assert not is_connection_shaped(delivered)


# --- The negatives, at the door, unchanged -----------------------------------


@pytest.fixture
def request_() -> Any:
    return RequestFactory().get(WIDGETS)


def test_a_deadlock_still_reaches_the_500_path(request_: Any) -> None:
    """Unchanged: no handler claims it, so it escapes exactly as it did.

    The same assertion shape `test_api_errors.py::test_everything_else_is_left_alone`
    makes about a `RuntimeError` — an exception this API has no vocabulary for
    is re-raised, not answered.
    """
    with pytest.raises(OperationalError):
        api.on_exception(request_, as_delivered(pg.DeadlockDetected("deadlock detected")))


def test_a_programming_error_still_reaches_the_500_path(request_: Any) -> None:
    with pytest.raises(ProgrammingError):
        api.on_exception(request_, as_delivered(pg.UndefinedColumn('column "nope" does not exist')))


def test_an_integrity_error_is_still_a_409(request_: Any) -> None:
    """The regression pin for the one negative that has an answer of its own."""
    response = api.on_exception(request_, IntegrityError("duplicate key value"))
    assert response.status_code == 409
    assert body_of(response)["code"] == "conflict"


def test_a_deadlock_over_the_wire_is_still_a_500(
    uncaught_door: Client, owner: User, tenant: Tenant, root_org: Organization
) -> None:
    """The negative at the depth that matters most: above ninja, where the new
    seam lives. A `handler500` that classified by exception *type* rather than
    by SQLSTATE would turn this one 503 and nobody would notice for a cycle."""
    uncaught_door.force_login(owner)

    with every_statement_raises(pg.DeadlockDetected("deadlock detected")):
        response = uncaught_door.get(WIDGETS)

    assert response.status_code == 500
    assert "Retry-After" not in response.headers


# --- The registration, and what it owes the document -------------------------


def test_the_refusal_is_registered_with_its_fact_and_remedies() -> None:
    """E9's import-time tier: a bare string would have been refused at import."""
    refusal = REFUSALS["database_unavailable"]

    assert refusal.boundary == "door"
    assert refusal.fact
    assert refusal.remedy
    assert refusal.remedies
    assert all(remedy.label and remedy.destination for remedy in refusal.remedies)


def test_the_code_carries_its_status_into_the_document() -> None:
    """Rule 47: a new code with no `CODE_STATUS` line drops out of
    `x-refusal-codes` silently, and the document stops describing the API."""
    assert CODE_STATUS["database_unavailable"] == 503


def test_introspect_reports_the_refusal() -> None:
    from apps.core.management.commands.introspect import _refusals_payload

    codes = {entry["code"] for entry in _refusals_payload()}
    assert "database_unavailable" in codes


def test_the_refusal_carries_a_retry_after_a_client_can_wait_for() -> None:
    assert DatabaseUnavailable().retry_after >= 1
    assert DatabaseUnavailable(retry_after=7).retry_after == 7


# --- The operator's instrument (rule 19) -------------------------------------


def test_each_503_writes_one_structured_line(
    monkeypatch: pytest.MonkeyPatch,
    client: Client,
    owner: User,
    root_org: Organization,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """RELOAD-1 composes err% out of this. A count of back-offs that has to be
    grepped out of prose is a count nobody produces during an incident."""

    def boom(**kwargs: Any) -> None:
        raise too_many_connections()

    monkeypatch.setattr("apps.example.api.list_widgets", boom)
    client.force_login(owner)

    with caplog.at_level(logging.WARNING):
        response = client.get(WIDGETS)

    assert response.status_code == 503
    lines = [
        cast(dict[str, Any], json.loads(record.getMessage()))
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]
    unavailable = [line for line in lines if line.get("event") == "core.database.unavailable"]
    assert len(unavailable) == 1
    # The SQLSTATE is what tells slot exhaustion apart from a failover in the
    # same census, and `seam` is what says how deep the fault erupted — the half
    # the bound context could not know. `door` arrives on the line without
    # anybody passing it, from `ContextMiddleware`.
    assert unavailable[0]["sqlstate"] == "53300"
    assert unavailable[0]["seam"] == "api"
    assert unavailable[0]["door"] == "rest"
