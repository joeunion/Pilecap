# census: cross-app population=apps/**/*.py,config/**/*.py for rule 19's loggers and prints
"""One sink, and the context that makes it queryable.

The load-bearing test is `test_the_middleware_binds_the_four_ids_a_query_needs`:
drive a real request through the real middleware stack and prove that by the
time a selector runs, `request_id`, `tenant_id`, `trace_id` and `door` are all
bound. Those four are what turn "the logs" into "the logs for this request,
this tenant, this trace, this door", and not one of them is passed by any
caller — which is the property. A version of this that bound them by hand in
the test would prove nothing.
"""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.test import Client, RequestFactory
from opentelemetry import trace

from apps.accounts.models import User
from apps.core import context
from apps.core.log import get_logger
from apps.core.middleware import CORRELATION_ID_HEADER, REQUEST_ID_HEADER, ContextMiddleware
from apps.core.models import Tenant
from apps.core.observability import _add_trace_ids, configure, get_tracer
from apps.core.tests.tree_census import source_tree, vanishing_source_file

ROOT = Path(__file__).resolve().parents[3]
SCANNED = (ROOT / "apps", ROOT / "config")
WIDGETS_URL = "/api/v1/widgets/"

log = get_logger(__name__)


@pytest.fixture(autouse=True)
def clean_context() -> Iterator[None]:
    context.clear()
    yield
    context.clear()


# --- The context ------------------------------------------------------------


def _emitted(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    """The last line as it actually left the process: parsed back from JSON.

    Deliberately not `structlog.testing.capture_logs`, which swaps the whole
    processor chain out — including `merge_contextvars`, which is the thing
    under test. This reads what stdlib logging received, so the assertion is
    against the real rendering.
    """
    parsed: dict[str, Any] = json.loads(caplog.records[-1].getMessage())
    return parsed


def test_bound_values_reach_a_log_line_nobody_passed_them_to(
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure()
    context.bind(tenant_id="t-1", door="rest")
    with caplog.at_level(logging.INFO):
        log.info("example.widget.created", widget_id="w-1")

    line = _emitted(caplog)
    assert line["event"] == "example.widget.created"
    assert line["tenant_id"] == "t-1"
    assert line["door"] == "rest"
    assert line["widget_id"] == "w-1"


def test_a_line_written_inside_a_span_carries_the_trace_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The join between a log search and a trace waterfall."""
    configure()
    context.bind(request_id="r-1", tenant_id="t-1")
    with caplog.at_level(logging.INFO):
        with get_tracer("test").start_as_current_span("probe"):
            log.info("example.probe")

    line = _emitted(caplog)
    assert line["request_id"] == "r-1"
    assert line["tenant_id"] == "t-1"
    assert len(line["trace_id"]) == 32
    assert len(line["span_id"]) == 16


def test_clear_takes_everything_with_it() -> None:
    context.bind(tenant_id="t-1")
    context.clear()
    assert context.get() == {}


def test_bound_puts_back_what_was_there() -> None:
    context.bind(tenant_id="t-1")
    with context.bound(tenant_id="t-2", door="shell"):
        assert context.value("tenant_id") == "t-2"
    assert context.get() == {"tenant_id": "t-1"}


def test_none_is_not_bound_rather_than_bound_as_none() -> None:
    context.bind(tenant_id=None, door="rest")
    assert context.get() == {"door": "rest"}


def test_a_session_key_is_hashed_and_never_stored_in_the_clear() -> None:
    hashed = context.hash_session("a-real-session-key")
    assert hashed is not None
    assert "a-real-session-key" not in hashed
    assert hashed == context.hash_session("a-real-session-key")
    assert context.hash_session(None) is None


def test_a_child_continues_the_chain_and_names_its_parent() -> None:
    context.bind(correlation_id="c-1")
    assert context.child_of_current() == {"correlation_id": "c-1", "causation_id": "c-1"}


def test_below_a_door_with_nothing_bound_the_chain_refuses_to_restart() -> None:
    """House rule 20: a correlation id is minted at a door and nowhere else.

    Work reached with no chain bound has no door above it, and minting one here
    would restart the business chain the join key exists to join — so the
    child-minter refuses, naming the doors that bind.
    """
    context.clear()
    with pytest.raises(context.ContextUnbound) as refused:
        context.child_of_current()
    assert "door" in str(refused.value)


def test_headers_are_honoured_so_one_trace_stays_one_trace() -> None:
    bound = context.from_headers({REQUEST_ID_HEADER: "r-1", CORRELATION_ID_HEADER: "c-1"})
    assert bound["request_id"] == "r-1"
    assert bound["correlation_id"] == "c-1"


def test_missing_headers_are_minted_rather_than_left_blank() -> None:
    bound = context.from_headers({})
    assert bound["request_id"] and bound["correlation_id"]
    assert bound["request_id"] != bound["correlation_id"]


# --- Tracing ----------------------------------------------------------------


def test_tracing_is_on_even_with_nowhere_to_export_to() -> None:
    """A laptop still gets real ids, which is exactly where they are read."""
    configure()
    with get_tracer("test").start_as_current_span("probe"):
        assert trace.get_current_span().get_span_context().is_valid


def test_the_processor_puts_the_span_ids_on_the_line() -> None:
    configure()
    with get_tracer("test").start_as_current_span("probe"):
        inside = _add_trace_ids(None, "info", {"event": "example.probe"})
    outside = _add_trace_ids(None, "info", {"event": "example.probe"})

    assert len(str(inside["trace_id"])) == 32
    assert len(str(inside["span_id"])) == 16
    # No span, no ids — rather than sixteen zeroes, which look like an id.
    assert "trace_id" not in outside


# --- A real request ---------------------------------------------------------


@pytest.mark.django_db
def test_the_middleware_binds_the_four_ids_a_query_needs(
    api: Client, owner: User, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure()
    api.force_login(owner)
    captured: list[dict[str, Any]] = []

    from apps.example import selectors

    original = selectors.list_widgets

    def spy(**kwargs: Any) -> Any:
        entry = dict(context.get())
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            entry["trace_id"] = format(span_context.trace_id, "032x")
        captured.append(entry)
        return original(**kwargs)

    monkeypatch.setattr(selectors, "list_widgets", spy)
    monkeypatch.setattr("apps.example.api.list_widgets", spy)

    with get_tracer("test").start_as_current_span("request"):
        assert api.get(WIDGETS_URL).status_code == 200

    assert captured, "the selector was never reached"
    bound = captured[0]
    assert bound["request_id"]
    assert bound["correlation_id"]
    assert bound["tenant_id"] == str(tenant.pk)
    assert bound["user_id"] == str(owner.pk)
    assert bound["actor_kind"] == "human"
    assert bound["door"] == "rest"
    assert bound["trace_id"]


@pytest.mark.django_db
def test_a_request_hands_its_ids_back_to_the_client(api: Client, owner: User) -> None:
    """So a bug report can quote an id instead of a timestamp."""
    api.force_login(owner)
    response = api.get(WIDGETS_URL, headers={"x-correlation-id": "c-from-the-caller"})
    assert response["X-Request-Id"]
    assert response[CORRELATION_ID_HEADER] == "c-from-the-caller"


def test_the_admin_path_binds_a_different_door() -> None:
    """`door` is what answers "the same service — but called from where?"."""
    seen: dict[str, Any] = {}

    def view(request: Any) -> Any:
        seen.update(context.get())
        from django.http import HttpResponse

        return HttpResponse("ok")

    factory = RequestFactory()
    ContextMiddleware(view)(factory.get("/admin/example/widget/"))
    assert seen["door"] == "admin"

    seen.clear()
    ContextMiddleware(view)(factory.get(WIDGETS_URL))
    assert seen["door"] == "rest"


def test_the_context_does_not_survive_into_the_next_request() -> None:
    """A worker thread outlives the request it served; a stale tenant_id on the
    next request's log lines is worse than none at all."""

    def view(request: Any) -> Any:
        context.bind(tenant_id="t-1")
        from django.http import HttpResponse

        return HttpResponse("ok")

    context.clear()
    ContextMiddleware(view)(RequestFactory().get(WIDGETS_URL))
    assert context.get() == {}


def test_the_door_puts_back_the_chain_it_was_called_under() -> None:
    """An in-process caller (a test, a command) keeps its own chain across a request."""

    def view(request: Any) -> Any:
        context.bind(tenant_id="t-1")
        from django.http import HttpResponse

        return HttpResponse("ok")

    context.clear()
    context.bind(correlation_id="the-callers-chain")
    ContextMiddleware(view)(RequestFactory().get(WIDGETS_URL))
    assert context.get() == {"correlation_id": "the-callers-chain"}


async def _socket_door(scope_extra: dict[str, Any]) -> None:
    """Drive the socket door's resolver once, with an inner app that binds a tenant."""
    from django.contrib.auth.models import AnonymousUser

    from apps.core.asgi_middleware import TenantMiddlewareASGI

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        context.bind(tenant_id="t-1")

    scope = {
        "type": "websocket",
        "path": "/ws/events/",
        "headers": [(b"host", b"testserver")],
        "query_string": b"",
        "user": AnonymousUser(),
        **scope_extra,
    }
    await TenantMiddlewareASGI(inner)(scope, None, None)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_socket_door_leaves_an_empty_task_empty() -> None:
    """The socket door's twin of the HTTP door's pin: nothing survives the connection."""
    context.clear()
    await _socket_door({})
    assert context.get() == {}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_socket_door_puts_back_the_chain_it_was_called_under() -> None:
    """An in-process caller keeps its own chain across a socket connection.

    RED on the baseline: the door `clear()`ed on the way out, so the caller's
    `correlation_id` was gone after the connection closed.
    """
    context.clear()
    context.bind(correlation_id="the-callers-chain")
    await _socket_door({})
    assert context.get() == {"correlation_id": "the-callers-chain"}
    context.clear()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_machine_door_puts_back_the_chain_it_was_called_under(
    owner: Any, tenant: Any
) -> None:
    """The MCP door's twin: a resolved tool call leaves the caller's chain as it found it.

    RED on the baseline: `config/mcp.py`'s token door `clear()`ed on the way out.
    """
    from apps.accounts.services import issue_token
    from apps.core.actor import actor_for
    from apps.core.asyncdb import run_db
    from config.mcp import TokenAuthMiddleware

    _, bearer = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="chain",
        actor=actor_for(user=owner, tenant=tenant),
    )
    reached: list[dict[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        reached.append(context.get())
        context.bind(tenant_id="t-1")

    scope = {
        "type": "http",
        "path": "/mcp",
        "method": "POST",
        "headers": [(b"host", b"testserver"), (b"authorization", f"Bearer {bearer}".encode())],
        "query_string": b"",
    }
    context.clear()
    context.bind(correlation_id="the-callers-chain")
    await TokenAuthMiddleware(inner)(scope, None, None)
    assert reached and reached[0]["door"] == "mcp", reached
    assert context.get() == {"correlation_id": "the-callers-chain"}
    context.clear()


# --- House rule 19 ----------------------------------------------------------


def _forbidden_logging(source: Path) -> list[str]:
    tree = source_tree(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            found.append("print")
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "getLogger",
            "basicConfig",
        }:
            found.append(f"logging.{node.func.attr}")
    return found


def test_nothing_prints_or_builds_its_own_logger() -> None:
    """House rule 19: `core/log.py` is the only logger and `core/observability.py`
    the only configuration.

    `observability.py` is the one exemption, because attaching the OTel handler
    to the root logger is the whole of its job.
    """
    exempt = {ROOT / "apps" / "core" / "observability.py"}
    checked = 0
    for directory in SCANNED:
        for source in sorted(directory.rglob("*.py")):
            if source in exempt or "/migrations/" in str(source) or "/tests/" in str(source):
                continue
            checked += 1
            assert _forbidden_logging(source) == [], f"{source} logs outside core.log"
    assert checked > 20, "the scan found almost nothing — it would pass vacuously"


def test_the_logging_census_tolerates_a_file_that_vanishes_at_open() -> None:
    """The logging census skips a source file deleted between listing and open.

    The plant is inert — no `print`, no `getLogger` — so the only way past it is to have skipped it.
    """
    with vanishing_source_file() as planted:
        test_nothing_prints_or_builds_its_own_logger()
        assert not planted.exists(), "the census never opened the plant — this drove nothing"


def test_the_workflow_door_mints_a_chain_for_a_run_that_carries_none() -> None:
    """A run started with no headers (a Schedule's) is a door with no chain handed to it.

    The workflow door is where the activity's work begins, so it mints exactly
    one chain when its headers carry none — and an activity that emits or
    starts work reaches `child_of_current` under it instead of `ContextUnbound`.
    """
    import asyncio
    from types import SimpleNamespace

    from apps.workflows.context import _ActivityInbound

    seen: dict[str, object] = {}

    class _Activity:
        async def execute_activity(self, input: object) -> None:
            seen.update(context.child_of_current())

    context.clear()
    door = _ActivityInbound(_Activity())  # type: ignore[arg-type]
    asyncio.run(door.execute_activity(SimpleNamespace(headers={})))  # type: ignore[arg-type]
    assert seen["correlation_id"], seen
    assert context.get() == {}, "the door put back exactly what was there"


def test_every_trace_carries_the_template_version_the_tree_ships() -> None:
    """`service.version` is the `TEMPLATE_VERSION` file's line, never a typed default."""
    from pathlib import Path

    from django.conf import settings

    from apps.core.observability import _resource

    shipped = (Path(settings.BASE_DIR) / "TEMPLATE_VERSION").read_text().strip()
    assert _resource().attributes["service.version"] == shipped
