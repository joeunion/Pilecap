"""The push bridge, and the promise its dotted path makes.

`apps/events` reaches this function through `core.bridge`'s runtime registry
(`architecture.md`, "the doors and the event spine"), which resolves it by
name — so the name is the interface, and a rename that a type checker cannot
see is exactly the kind of break a test has to catch.
"""

from __future__ import annotations

import importlib
import inspect
from uuid import UUID

import pytest
from django.utils import timezone

from apps.core import bridge
from apps.realtime.bridge import (
    GROUP_PREFIX,
    MESSAGE_TYPE,
    push_event,
    push_from_spine,
    tenant_group,
)
from apps.realtime.schemas import EventMessage

REGISTRY_PATH = "apps.realtime.bridge.push_event"
REGISTRY_NAME = "realtime.push"


def test_the_registry_finds_push_event_where_it_promises_to() -> None:
    """The exact path `core.bridge` will register under `realtime.push`."""
    module_path, _, attribute = REGISTRY_PATH.rpartition(".")
    found = getattr(importlib.import_module(module_path), attribute)

    assert found is push_event
    # Awaitable, because the channel layer is and the caller is an activity.
    assert inspect.iscoroutinefunction(found)
    # Keyword-only, so a caller cannot get the tenant and the event the wrong
    # way round — the failure that would push one tenant's data to another.
    signature = inspect.signature(found)
    assert [p.kind for p in signature.parameters.values()] == [
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
    ]
    assert set(signature.parameters) == {"tenant_id", "event"}


def test_this_app_filled_the_registry_name_the_spine_looks_up() -> None:
    """`AppConfig.ready()` is what makes the spine's `find()` answer.

    Registered, not merely importable: a `bridge.py` nobody registered is a
    push that silently never happens, which is the failure this repository's
    whole registry design exists to make loud.
    """
    assert bridge.is_registered(REGISTRY_NAME)
    assert bridge.find(REGISTRY_NAME) is push_from_spine
    assert REGISTRY_NAME == bridge.REALTIME_PUSH


def test_the_registered_entry_is_callable_from_a_thread_with_no_loop() -> None:
    """The caller is a plain `def` activity on the worker's thread pool.

    A coroutine function registered here would be a coroutine nobody awaits:
    the dispatch would report `pushed=True` and nothing would reach a socket.
    """
    assert not inspect.iscoroutinefunction(push_from_spine)
    signature = inspect.signature(push_from_spine)
    assert [p.kind for p in signature.parameters.values()] == [
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
    ]
    assert set(signature.parameters) == {"tenant_id", "event"}


def test_a_group_is_named_for_the_tenant_id_and_nothing_else() -> None:
    tenant_id = UUID("018f3a2b-0000-7000-8000-00000000abcd")

    assert tenant_group(tenant_id) == f"{GROUP_PREFIX}.{tenant_id}"
    assert tenant_group(str(tenant_id)) == tenant_group(tenant_id)


def test_the_channel_layer_message_names_this_apps_handler() -> None:
    """Channels turns the dot into an underscore to find the consumer method."""
    from apps.realtime.consumers import TenantEventsConsumer

    assert hasattr(TenantEventsConsumer, MESSAGE_TYPE.replace(".", "_"))


@pytest.mark.asyncio
async def test_a_push_with_nobody_listening_is_not_an_error() -> None:
    """A socket is a live channel: an event nobody is connected for is not a loss.

    Durability is the outbox's job. If this raised, one disconnected client
    would fail the dispatch workflow for every other subscriber.
    """
    await push_event(
        tenant_id=UUID("018f3a2b-0000-7000-8000-00000000abcd"),
        event=EventMessage(name="example.widget.created", payload={}, occurred_at=timezone.now()),
    )
