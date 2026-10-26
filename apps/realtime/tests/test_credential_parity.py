"""One hat, three credentials, one answer: the socket door agreeing with itself.

**Why this module exists (ADR realtime-3).** House rule 17 diffs two
*registries* — REST routes against MCP tools — and proves that a capability
exists on both. That shape cannot see this class of defect: one consumer, one person,
one header, and two different sets of frames depending on which credential the
handshake carried. There is no second registry to diff, so socket parity is a
**parity test per door pair**, in the owning app's tests, and this is the first
member of that family. `apps/example/tests/test_doors_over_the_wire.py` is the
precedent for the shape; the pair here is *session cookie* against *bearer
token* (in both its forms) rather than REST against MCP.

**The defect it was born to catch.** The session stack
resolves `scope["org"]` from the session user; `TokenAuthMiddlewareASGI` then
overrode `scope["user"]` and `scope["tenant"]` and never touched
`scope["org"]` — so a bearer handshake kept the hat the session stack had
resolved for `AnonymousUser`, which is `None`. A token socket joined zero org
groups and heard no org-bearing event, while the same person's cookie socket,
wearing the same `X-Org`, heard all of them. No leak — it failed closed — but a
token that can read a branch over REST could not watch it, and two docstrings
claimed otherwise.

Every test here drives the **real chain**, exactly as `test_hierarchy.py` does:
`emit()` → the spine's `push_realtime` activity → `core.bridge` → the channel
layer → the consumer → the wire, against the application `config/asgi.py`
builds. Nothing about the credential path is stubbed: the cookie is a real
signed-in session and the token is a real `ApiToken` row.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core import context
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.models import Organization, Tenant
from apps.core.tests.wire import socket_bearer
from apps.realtime.schemas import CLOSE_NO_TENANT
from apps.realtime.selectors import list_subtree_org_ids
from apps.realtime.tests.sockets import a_ticket, opened
from apps.realtime.tests.test_consumers import session_headers
from apps.realtime.tests.test_hierarchy import (
    ORG_LESS_EVENT,
    Network,
    _build_network,
    _emit_and_push,
    in_branch,
    org_less_body,
)
from apps.realtime.tests.websocket import Handshake, Socket

#: House rule 46. The door pair this module answers for `apps/realtime`, read by
#: the gate off this module-level assignment. The population is DERIVED from the
#: doors the app has — a `consumers.py` owes the credential pair — and this is
#: the claim that it is answered here.
DOOR_PAIR = ("session", "bearer")

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

EVENT_NAME = "example.widget.created"

PATH = "/ws/events/"


@pytest.fixture
def network(tenant: Tenant, owner: User) -> Network:
    """The same four-node tree `test_hierarchy.py` drives, built the same way.

    Built through the helper rather than imported as a fixture so that this
    module's dependency on that one is a function call a reader can follow,
    not a name pytest resolves out of another module's namespace.
    """
    return _build_network(tenant=tenant, owner=owner)


# --- The three credentials, as three ways of opening the same socket ---------


async def a_token(*, user: User, tenant: Tenant, name: str) -> str:
    """A real `ApiToken` for this person, pinned to this tenant.

    `test_consumers.py`'s twin hardcodes the name, which is fine where one
    socket is opened per test and refused here where three are: `ApiToken` is
    unique per user and name, so a second `issue_token` under the same name
    raises `Invalid` and the test fails for a reason that has nothing to do
    with what it is about.
    """
    _, plaintext = await run_db(
        issue_token, user=user, tenant=tenant, name=name, actor=actor_for(user=user, tenant=tenant)
    )
    return str(plaintext)


@asynccontextmanager
async def by_session(
    *, user: User, org: Organization | None = None
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """The browser door: a real signed-in session cookie, plus `X-Org`."""
    headers = await session_headers(user)
    if org is not None:
        headers = [*headers, (b"x-org", org.slug.encode())]
    async with opened(headers=headers) as pair:
        yield pair


@asynccontextmanager
async def by_bearer(
    *, user: User, tenant: Tenant, org: Organization | None = None, name: str = "header-socket"
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """The machine door: `Authorization: Bearer <token>`, plus `X-Org`."""
    headers = socket_bearer(await a_token(user=user, tenant=tenant, name=name))
    if org is not None:
        headers = [*headers, (b"x-org", org.slug.encode())]
    async with opened(headers=headers) as pair:
        yield pair


@asynccontextmanager
async def by_query(
    *, user: User, tenant: Tenant, org: Organization | None = None, name: str = "query-socket"
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """The browser's machine door: `?ticket=` and `?org=`.

    A browser's `WebSocket` constructor cannot set request headers, so both the
    credential and the hat have to travel in the URL or a browser client can
    never wear either. The credential travels as a one-use ticket.
    """
    ticket = await a_ticket(user=user, tenant=tenant, name=name)
    path = f"{PATH}?ticket={ticket}"
    if org is not None:
        path = f"{path}&org={org.slug}"
    async with opened(path=path) as pair:
        yield pair


async def frame(socket: Socket) -> str:
    """The next push as it left the server: the text frame, unparsed.

    Byte-equality is the assertion these tests are for, and `receive_json`
    would hand back a dictionary that two different serialisations could both
    produce. What a client receives is this string.
    """
    message = await socket.output()
    assert message["type"] == "websocket.send", message
    return str(message["text"])


# --- One hat, three credentials, one envelope --------------------------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_every_credential_wearing_one_hat_receives_the_same_envelope(
    network: Network,
) -> None:
    """**The rung's criterion.** Bearer auth combined with an org-bearing push.

    One person — the rival, whose only membership is on branch B — opens three
    sockets at the same time, all three naming `X-Org: branch-b` (the query
    socket as `?org=branch-b`, which is the only form a browser has). One
    org-scoped row lands in branch B. All three frames must be byte-equal:
    the same person, wearing the same hat, watching the same branch.

    Before the fix the session socket received the envelope and the two token
    sockets received nothing at all — `receive_json` timing out was the
    absence reading.

    It cannot pass vacuously twice over: the three sockets are proved live by
    a tenant-wide event first, and the org-scoped frame is then asserted to
    carry `organization_id` (house rule 38's key — the value the fan-out
    narrowed on), so "byte-equal" cannot be three copies of a tenant-wide
    envelope.
    """
    rival_hat = await run_db(
        actor_for, user=network.rival, tenant=network.tenant, org=network.branch_b
    )

    async with (
        by_session(user=network.rival, org=network.branch_b) as (cookie, cookie_shake),
        by_bearer(user=network.rival, tenant=network.tenant, org=network.branch_b) as (
            bearer,
            bearer_shake,
        ),
        by_query(user=network.rival, tenant=network.tenant, org=network.branch_b) as (
            query,
            query_shake,
        ),
    ):
        assert [cookie_shake.accepted, bearer_shake.accepted, query_shake.accepted] == [
            True,
            True,
            True,
        ]

        # Live: a tenant-wide event reaches all three, whatever authenticated them.
        # The name is the declared ORG-LESS one since R4-F2: a widget always
        # belongs to a branch, so `emit` refuses a widget body that names none.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=rival_hat,
            name=ORG_LESS_EVENT,
            payload=org_less_body(),
        )
        for socket in (cookie, bearer, query):
            assert (await socket.receive_json())["name"] == ORG_LESS_EVENT

        # The criterion: an org-bearing push, on all three credentials.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=rival_hat,
            payload=in_branch(network.branch_b),
        )
        frames = [await frame(socket) for socket in (cookie, bearer, query)]

    assert frames[0] == frames[1] == frames[2], "the three credentials disagree on the wire"
    envelope = json.loads(frames[0])
    assert envelope["name"] == EVENT_NAME
    assert envelope["organization_id"] == str(network.branch_b.pk)


# --- Aligned, not widened ------------------------------------------------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_bearer_socket_asking_for_a_hat_it_holds_no_role_over_is_refused(
    network: Network,
) -> None:
    """A5a, on the machine door: the fix aligned the credentials, it did not widen them.

    The manager's only membership is on branch A. Asking for `X-Org: branch-b`
    — a sibling, neither their node nor under it — resolves to no hat at all,
    exactly as it does at the HTTP door, because it is the same
    `core.middleware.resolve_org` answering.

    **What happens next changed with ADR core-21.** The handshake used to
    succeed — the tenant resolved; only the hat did not — and the connection
    then heard tenant-wide events and neither branch's rows: not branch B's,
    which they asked for and may not have, and not branch A's, which they hold
    but did not ask for. Fail-closed, and silent about it. The addressing-header
    law makes it loud: a hat that was SENT and cannot be worn refuses, and on
    this transport a refusal is a closed handshake (`CLOSE_NO_TENANT`).

    It still widens nothing, and the two credentials still answer alike: the
    session half of this same request closes the same way
    (`test_hierarchy.py::test_an_unresolved_hat_is_refused_at_the_handshake`).
    """
    async with by_bearer(user=network.manager, tenant=network.tenant, org=network.branch_b) as (
        _socket,
        handshake,
    ):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_bearer_socket_with_no_org_header_wears_the_default_hat(
    network: Network,
) -> None:
    """No `X-Org` is not "no hat": it is the default membership's, on both credentials.

    The rival's default membership is branch B, so a handshake that names no
    hat wears branch B — the same answer `resolve_org` gives the HTTP door for
    a request with no header, and the same answer the cookie socket beside it
    gets. Both sockets are open at once so that one push decides both.
    """
    rival_hat = await run_db(
        actor_for, user=network.rival, tenant=network.tenant, org=network.branch_b
    )
    manager_hat = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )

    async with (
        by_session(user=network.rival) as (cookie, cookie_shake),
        by_bearer(user=network.rival, tenant=network.tenant) as (bearer, bearer_shake),
    ):
        assert [cookie_shake.accepted, bearer_shake.accepted] == [True, True]

        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=rival_hat,
            payload=in_branch(network.branch_b),
        )
        assert await frame(cookie) == await frame(bearer)

        # And neither hears a branch it does not hold.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.branch_a),
        )
        assert await cookie.received_nothing() is True
        assert await bearer.received_nothing() is True


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_bearer_socket_naming_an_org_that_does_not_exist_is_refused_alike(
    network: Network,
) -> None:
    """The other invalid `X-Org`, and it is a different branch of `resolve_org`.

    The test above asks for an organization that *exists* and belongs to
    somebody else. This asks for one that exists nowhere — `resolve_org`'s
    unknown-slug arm, which returns `None` before it ever looks at a
    membership. Both are "no hat", and both must refuse the same way, because a
    door that told a client which of the two had happened would answer "does
    this branch exist" for anyone holding any token. The anti-oracle is the
    reason the two are indistinguishable here, exactly as the HTTP door's two
    bodies are byte-identical (ADR core-21).

    **And an EMPTY `X-Org` is the third member of that set:** a
    handshake that set the header from a template that did not interpolate used
    to fall through to the query parameter and then to the default hat, which
    is the quiet answer the whole law exists to stop.
    """
    for value in (b"no-such-branch", b""):
        headers = [
            *socket_bearer(
                await a_token(
                    user=network.rival,
                    tenant=network.tenant,
                    name=f"nowhere-{len(value)}",
                )
            ),
            (b"x-org", value),
        ]
        async with opened(headers=headers) as (_socket, handshake):
            assert handshake.accepted is False, value
            assert handshake.code == CLOSE_NO_TENANT, value


async def test_a_pinned_token_naming_another_tenant_is_refused_before_any_hat(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    """The tenant pin outranks the hat, and is answered before one is resolved.

    `test_consumers.py` proves the pin on a handshake carrying no `X-Org`.
    This is the same refusal with a hat asked for as well: the tenant is judged
    first, because a hat is a place *inside* a tenant and there is no tree for
    an `X-Org` to be wrong against once the tenant itself was refused
    (`core.middleware.addressing_refusal`'s own ordering, ADR core-21).

    The close code is `CLOSE_NO_TENANT` and not `CLOSE_UNAUTHENTICATED`: the
    credential is live and it is the ADDRESS that was refused.
    """
    headers = [
        *socket_bearer(await a_token(user=owner, tenant=tenant, name="pinned")),
        (b"x-tenant", other_tenant.slug.encode()),
        (b"x-org", b"anything"),
    ]

    async with opened(headers=headers) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


# --- The context a socket-door audit row will carry --------------------------------


@pytest.fixture
def bound_at_connect(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Whatever `core.context` held while the consumer was joining its groups.

    The application runs in its own task, and `structlog`'s context variables
    are per-task, so the test's own task can never read what the middleware
    bound. The house shape for this is a spy over the function the code under
    test calls — `apps/core/tests/test_observability.py` reads a request's
    bound ids the same way — placed on the one read the consumer makes at
    connect, which is squarely inside the window the criterion is about.

    Patched by dotted path and delegating to the selector's own module: the
    consumer bound the name at import, so replacing it where *it* holds it is
    what a spy has to do, while reading the original from where it is defined
    is what keeps `mypy --strict` from being asked to re-export it.
    """
    seen: list[dict[str, Any]] = []

    def spy(**kwargs: Any) -> Any:
        seen.append(dict(context.get()))
        return list_subtree_org_ids(**kwargs)

    monkeypatch.setattr("apps.realtime.consumers.list_subtree_org_ids", spy)
    return seen


async def test_a_bearer_connect_binds_the_hat_it_resolved(
    network: Network, bound_at_connect: list[dict[str, Any]]
) -> None:
    """The audit row for a socket-door action names the hat, not just the tenant.

    `org_id` was the missing half: a token handshake used to log
    `"org_id": null, "groups": 2` however the client had dressed it, which is
    a log line that cannot answer "under which hat" months later. The other
    three keys are asserted beside it because a context that named the hat and
    called the caller a human would be just as wrong.
    """
    async with by_bearer(user=network.rival, tenant=network.tenant, org=network.branch_b) as (
        _,
        handshake,
    ):
        assert handshake.accepted is True

    assert bound_at_connect, "the consumer never reached its subtree read"
    bound = bound_at_connect[0]
    assert bound["tenant_id"] == str(network.tenant.pk)
    assert bound["org_id"] == str(network.branch_b.pk)
    assert bound["user_id"] == str(network.rival.pk)
    assert bound["actor_kind"] == "agent"
    assert bound["door"] == "socket"


async def test_a_token_that_resolves_no_hat_leaves_no_hat_bound(
    network: Network, bound_at_connect: list[dict[str, Any]]
) -> None:
    """A handshake carrying both credentials must not log the losing one's hat.

    The two middlewares read the *same* headers, and the session stack runs
    first. Here the cookie is the manager's — whose default hat is branch A —
    and the bearer token is the rival's, whose default hat is branch B. Binding
    is not the whole job: what the session stack concluded has to be *taken
    back*, or the context keeps a hat the principal it now names never wore.

    **Driven with NO `X-Org` since ADR core-21.** It used to name
    `leaf-a1` — under the manager's branch and nothing to the rival — so the
    losing credential resolved a hat and the winning one resolved none, which
    made "no hat bound" the assertion. That handshake is now refused outright
    (a sent header this principal cannot wear), so the losing-hat question has
    to be asked where a connection still happens: two default hats, and the
    bound one must be the winner's. Same defect shape, still failing loudly if
    the override goes back to being half-done.
    """
    headers = [
        *await session_headers(network.manager),
        *socket_bearer(await a_token(user=network.rival, tenant=network.tenant, name="both")),
    ]

    async with opened(headers=headers) as (_, handshake):
        assert handshake.accepted is True

    assert bound_at_connect, "the consumer never reached its subtree read"
    bound = bound_at_connect[0]
    assert bound["user_id"] == str(network.rival.pk)
    assert bound.get("org_id") == str(network.branch_b.pk), (
        "the session's hat outlived the session's user"
    )
