"""The four seams `core` publishes for its apps' private copies: each answer and its empty case."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider

from apps.accounts.models import User
from apps.core import bridge
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.asgi_middleware import requested_slug
from apps.core.authz import is_member
from apps.core.models import Tenant
from apps.core.service import trace_id
from apps.core.surfaces import PUBLIC_BASE_URL_SETTING


@pytest.fixture
def restored_bridge() -> Iterator[None]:
    """Put back what the apps registered after a test clears the bridge."""
    saved = bridge.registered()
    yield
    bridge.clear()
    for name, fn in saved.items():
        bridge.register(name, fn)


# --- is_member ------------------------------------------------------------------


def test_a_member_is_a_member(member_actor: Actor) -> None:
    assert is_member(member_actor) is True
    assert is_member(member_actor, object()) is True


def test_a_stranger_and_the_system_are_not_members(stranger: User, tenant: Tenant) -> None:
    assert is_member(actor_for(user=stranger, tenant=tenant)) is False
    assert is_member(system_actor(tenant=tenant)) is False


# --- trace_id -------------------------------------------------------------------


def test_no_span_is_no_trace_id() -> None:
    assert trace_id() == ""


def test_a_span_is_its_trace_as_32_hex() -> None:
    tracer = TracerProvider().get_tracer("test_core_seams")
    with tracer.start_as_current_span("probe") as span:
        said = trace_id()
        assert said == format(span.get_span_context().trace_id, "032x")
    assert len(said) == 32 and int(said, 16) > 0


# --- requested_slug -------------------------------------------------------------


def _scope(headers: list[tuple[bytes, bytes]], query: bytes = b"") -> dict[str, Any]:
    return {"headers": headers, "query_string": query}


def test_a_handshake_naming_nothing_requested_nothing() -> None:
    assert requested_slug(_scope([]), "X-Tenant", "tenant") is None


def test_the_header_beats_the_query_even_when_empty() -> None:
    assert (
        requested_slug(_scope([(b"x-tenant", b"acme")], b"tenant=other"), "X-Tenant", "tenant")
        == "acme"
    )
    assert requested_slug(_scope([(b"x-tenant", b"")], b"tenant=other"), "X-Tenant", "tenant") == ""
    assert requested_slug(_scope([], b"tenant=other"), "X-Tenant", "tenant") == "other"


# --- the bridge listener --------------------------------------------------------


def test_a_registered_listener_is_the_registered_callable() -> None:
    assert bridge.listener(bridge.EMIT) is bridge.find(bridge.EMIT)
    assert bridge.listener(bridge.EMIT) is not None


def test_nobody_listening_is_none_outside_production(restored_bridge: None, settings: Any) -> None:
    bridge.clear()
    settings.BRIDGE_STRICT = False
    assert bridge.listener(bridge.EMIT) is None


def test_nobody_listening_refuses_in_production(restored_bridge: None, settings: Any) -> None:
    bridge.clear()
    settings.BRIDGE_STRICT = True
    with pytest.raises(bridge.BridgeNotRegistered):
        bridge.listener(bridge.EMIT)


# --- the base URL setting's name ----------------------------------------------------


def test_the_base_url_setting_name_is_a_setting(settings: Any) -> None:
    assert isinstance(getattr(settings, PUBLIC_BASE_URL_SETTING), str)
