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
from apps.core.middleware import ContextMiddleware
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


def test_a_chain_with_no_parent_starts_one() -> None:
    chain = context.child_of_current()
    assert chain["correlation_id"]
    assert chain["causation_id"] is None


def test_headers_are_honoured_so_one_trace_stays_one_trace() -> None:
    bound = context.from_headers({"X-Request-Id": "r-1", "X-Correlation-Id": "c-1"})
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
    assert response["X-Correlation-Id"] == "c-from-the-caller"


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

    ContextMiddleware(view)(RequestFactory().get(WIDGETS_URL))
    assert context.get() == {}


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
    """The falsifier for the tolerant read, at the census that the race actually hit.

    RED before RACE-1: `FileNotFoundError: apps/zzz_vanisher_<hex>.py`, raised
    from the `ast.parse(source.read_text(...))` this census used to do. The
    plant is inert — no `print`, no `getLogger` — so the only way past it is to
    have skipped it.
    """
    with vanishing_source_file() as planted:
        test_nothing_prints_or_builds_its_own_logger()
        assert not planted.exists(), "the census never opened the plant — this drove nothing"
