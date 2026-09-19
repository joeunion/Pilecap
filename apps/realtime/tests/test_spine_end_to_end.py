"""One event, from `emit()` to a client's socket, with nothing in between faked.

`test_consumers.py` proves the socket door and `apps/events` proves the spine;
what neither can prove alone is the **join** — that a service saying something
happened ends up on the wire of a client that is connected, and only of the
right one. That join is four hops, and every one of them is a place a rename or
a signature drift would go unnoticed until a customer noticed first:

    services.emit()  →  Event + Outbox row
                     →  the spine's `push_realtime` activity
                     →  core.bridge["realtime.push"]  (a name, not an import)
                     →  the channel layer  →  the consumer  →  the socket

**Nothing here imports `apps.events`.** The two apps are siblings in the layer
contract and neither may import the other, so this test reaches the spine the
way the production code does: `core.bridge` for `emit`, and the app registry
for the model. The activity module itself is reached with `importlib`, which is
the same runtime lookup `apps/connections/services` uses and, deliberately, not
something `import-linter` has to be told to forgive.

The one thing standing in is the Temporal *transport*: in production the tenant
arrives on the workflow's headers and the interceptor unpacks it into the
contextvar this reads back. Here the contextvar is set directly, and
`recorded_workflow_starts` lets `emit`'s own on-commit start record its run
without dialling a server (this is a `transaction=True` module, so
that commit is real). Both are the transport; the chain under test — bridge
lookup, envelope, coercion, group send, consumer — is real all the way down,
and `push_realtime` is called here explicitly rather than waited for, which is
the hop that matters.

The socket client is `apps/realtime/tests/websocket.py` rather than
`channels.testing.WebsocketCommunicator`: importing anything under
`channels.testing` runs an `__init__` that imports `daphne`, which this
repository does not install (see that module's docstring).
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from django.apps import apps as django_apps

from apps.accounts.models import User
from apps.core import bridge
from apps.core.actor import Actor
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.realtime.schemas import EventMessage
from apps.realtime.tests.test_consumers import opened, session_headers

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

# The example app's event, because a name has to be one an app declares —
# `emit` refuses one that is not (`apps.events.events.check_name`).
EVENT_NAME = "example.widget.created"


def _emit_and_push(*, tenant: Tenant, actor: Actor, payload: dict[str, Any]) -> Any:
    """Say it happened, then run the dispatch's push hop. Synchronous, like both.

    Returns the `Event` row, so the caller can assert the socket saw the event
    that was actually written rather than one that merely looks like it.
    """
    context = importlib.import_module("apps.workflows.context")
    activities = importlib.import_module("apps.events.activities")
    types = importlib.import_module("apps.events.types")

    # **The branch the row landed in** (house rule 59). `emit` refuses a widget
    # event that names no `organization_id`: an absent key is stamped NULL and
    # the fan-out reads NULL as tenant-wide, so the subject's own row would go
    # to every socket in the tenant. Stamped HERE rather than at the two call
    # sites because this function runs on the worker thread `run_db` put it on,
    # which is the only place a synchronous `root_organization` belongs.
    body = {"organization_id": str(root_organization(tenant=tenant).pk), **payload}
    emit = bridge.get(bridge.EMIT)
    event = emit(name=EVENT_NAME, tenant=tenant, payload=body, actor=actor)

    # What `TenantContextInterceptor` does with the workflow's headers. The
    # activity reads it back through `core.bridge`, which is the hop being
    # exercised; only the header transport is absent.
    context.set_principal(tenant_id=str(tenant.pk), user_id=None)
    assert activities.push_realtime(types.PushRealtime(event_id=str(event.pk))) is True
    return event


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_an_emitted_event_arrives_on_a_connected_socket(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The whole chain, once, for the tenant that owns the event."""
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True

        event = await run_db(
            _emit_and_push,
            tenant=tenant,
            actor=owner_actor,
            payload={"id": "w-1", "name": "A widget"},
        )
        received = await socket.receive_json()

    # It validates as the socket contract, and it is the row that was written.
    message = EventMessage.model_validate(received)
    assert message.name == EVENT_NAME
    assert message.payload["name"] == "A widget"
    assert message.correlation_id == event.correlation_id

    # The same body a webhook subscriber would have been signed and sent: one
    # serialisation of one fact, which is what door parity means here.
    stored = await run_db(django_apps.get_model("events", "Event").objects.get, pk=event.pk)
    assert message.payload == stored.payload


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_another_tenants_socket_never_sees_it(
    tenant: Tenant,
    other_tenant: Tenant,
    owner_actor: Actor,
    stranger: User,
) -> None:
    """The sibling that cannot pass vacuously: a real socket, and nothing on it.

    The stranger is connected and accepted — this is not "the socket was
    closed" dressed up as isolation — and the event is emitted into the other
    tenant. Group membership is by tenant id and a client never names a group,
    so there is no way for this to arrive; that is the property, and this is
    what proves it.
    """
    async with opened(headers=await session_headers(stranger)) as (socket, handshake):
        assert handshake.accepted is True

        await run_db(
            _emit_and_push,
            tenant=tenant,
            actor=owner_actor,
            payload={"id": "w-1", "name": "Not theirs"},
        )

        assert await socket.received_nothing() is True
