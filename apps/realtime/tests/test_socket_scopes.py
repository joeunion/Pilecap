"""The socket door's half of the token ceiling (ADR ident-7, part 4).

Driven the way `test_consumers.py` drives it — the real ASGI application, a real
`ApiToken`, the real bridge — because what is under test is what arrives on a
client's socket, and a hand-built consumer would prove the method and leave the
middleware, the groups and the fan-out untested.

**Most of it is proved over org-less events, and the last section is not.**
When this module was written the hat's own narrowing was an open question (the
acting organization on a socket), so leaning on it would have been proving
two things at once and failing for either. That question is closed — a bearer socket
resolves its hat through the same `core.middleware.resolve_org` every other door
calls — and the two narrowings now meet on one connection, which is a third
thing neither half proved. The sections divide on exactly that line: everything
above "the ceiling and the hat" isolates the credential's ceiling and nothing
else; that section holds the two of them together on purpose.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import issue_token, revoke_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.models import Organization, Tenant
from apps.realtime.bridge import push_event
from apps.realtime.consumers import TenantEventsConsumer
from apps.realtime.schemas import CLOSE_KICKED, EventMessage
from apps.realtime.tests.test_consumers import PATH, an_event, bearer_headers, opened
from apps.realtime.tests.test_hierarchy import Network, _build_network

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

#: An event nobody's branch owns, so the frame goes to the tenant group and the
#: only thing deciding whether it arrives is the credential.
WIDGET_EVENT = "example.widget.created"

#: An event from a different app, so a ceiling naming one section can be shown
#: to be silent about the other rather than silent about everything.
MESSAGE_EVENT = "comms.message.sent"


async def scoped_token(*, user: User, tenant: Tenant, scopes: list[str] | None) -> str:
    name = "socket-" + "-".join(scopes or ["wide"])
    _, plaintext = await run_db(
        issue_token,
        user=user,
        tenant=tenant,
        name=name,
        scopes=scopes,
        actor=actor_for(user=user, tenant=tenant),
    )
    return plaintext


def an_event_named(name: str) -> EventMessage:
    return EventMessage(
        name=name,
        v=1,
        payload={"id": "8f14e45f-ea1e-7c2b-8000-000000000002", "name": "A thing"},
        correlation_id="c0ffee",
        occurred_at=timezone.now(),
    )


def an_event_in_branch(name: str, organization: Organization) -> EventMessage:
    """An event one branch owns, from whichever app the name says.

    `organization_id` is on the **envelope** and not in the payload, because
    that is the field the fan-out narrows on (`bridge.group_for`): a frame
    carrying one goes to that branch's group and to no other. The name is a
    parameter so that one branch can be written to from two apps inside a
    single test — which is the whole point of the section below, where the
    group is held constant and only the family varies.
    """
    return EventMessage(
        name=name,
        v=1,
        payload={"id": "8f14e45f-ea1e-7c2b-8000-000000000003", "name": "A branch thing"},
        correlation_id="c0ffee",
        organization_id=organization.pk,
        occurred_at=timezone.now(),
    )


@pytest.fixture
def network(tenant: Tenant, owner: User) -> Network:
    """The four-node tree `test_hierarchy.py` drives, built the same way.

    Through the helper rather than as an imported fixture for the reason
    `test_credential_parity.py` gives: a function call is a dependency a reader
    can follow, where a name pytest resolves out of another module's namespace
    is not.
    """
    return _build_network(tenant=tenant, owner=owner)


async def hatted_bearer_headers(
    *, user: User, tenant: Tenant, scopes: list[str] | None, org: Organization, name: str
) -> list[tuple[bytes, bytes]]:
    """A handshake carrying both narrowings at once: a ceiling and a hat.

    The two travel independently — the ceiling on the token row the
    `Authorization` header resolves to, the hat in `X-Org` — and this is the
    only place in the suite where one handshake sets both.
    """
    _, plaintext = await run_db(
        issue_token,
        user=user,
        tenant=tenant,
        name=name,
        scopes=scopes,
        actor=actor_for(user=user, tenant=tenant),
    )
    return [*bearer_headers(str(plaintext)), (b"x-org", org.slug.encode())]


# --- the frame narrows to the credential ---------------------------------------


async def test_a_socket_whose_ceiling_names_another_section_hears_nothing(
    tenant: Tenant, owner: User
) -> None:
    """The property, and it is asserted so that it cannot pass vacuously.

    A token scoped to messaging opens a socket and a widget event is pushed to
    the tenant it is connected for. It must not arrive — and then a messaging
    event must, on the same socket, because "received nothing" is also what a
    broken connection looks like.
    """
    plaintext = await scoped_token(user=owner, tenant=tenant, scopes=["messaging:read"])

    async with opened(PATH, bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True

        await push_event(tenant_id=tenant.pk, event=an_event_named(WIDGET_EVENT))
        assert await socket.received_nothing() is True

        await push_event(tenant_id=tenant.pk, event=an_event_named(MESSAGE_EVENT))
        assert (await socket.receive_json())["name"] == MESSAGE_EVENT


async def test_a_socket_scoped_to_the_emitting_section_hears_it(
    tenant: Tenant, owner: User
) -> None:
    plaintext = await scoped_token(user=owner, tenant=tenant, scopes=["widgets:read"])

    async with opened(PATH, bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await socket.receive_json())["name"] == WIDGET_EVENT


async def test_a_write_scope_hears_its_own_section(tenant: Tenant, owner: User) -> None:
    """The owner's ruling of 2026-08-24, at the third door.

    A write scope includes its family's read, and a socket is a read — so a
    token minted `widgets:write` and nothing else hears about widgets. It is the
    same predicate the other two doors ask, which is why this is one assertion
    and not a second implementation of the rule.
    """
    plaintext = await scoped_token(user=owner, tenant=tenant, scopes=["widgets:write"])

    async with opened(PATH, bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True

        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await socket.receive_json())["name"] == WIDGET_EVENT

        # And it stays inside its own section: a write on widgets says nothing
        # about messaging, so nothing from there arrives.
        await push_event(tenant_id=tenant.pk, event=an_event_named(MESSAGE_EVENT))
        assert await socket.received_nothing() is True


async def test_a_token_with_no_ceiling_hears_everything_it_always_did(
    tenant: Tenant, owner: User
) -> None:
    """The grandfather, at the socket door.

    Every integration already holding a token opened its socket under the old
    rules, and a column added expand-only is not allowed to quietly take that
    away.
    """
    plaintext = await scoped_token(user=owner, tenant=tenant, scopes=None)

    async with opened(PATH, bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await socket.receive_json())["name"] == WIDGET_EVENT
        await push_event(tenant_id=tenant.pk, event=an_event_named(MESSAGE_EVENT))
        assert (await socket.receive_json())["name"] == MESSAGE_EVENT


async def test_a_session_socket_is_not_narrowed(tenant: Tenant, owner: User) -> None:
    """A ceiling belongs to a credential somebody handed to a machine.

    Nobody handed a browser session to anybody, so there is nothing to narrow —
    and a change that quietly narrowed the human door would have gone unnoticed
    until a screen stopped updating.
    """
    from apps.realtime.tests.test_consumers import session_headers

    async with opened(PATH, await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await socket.receive_json())["name"] == WIDGET_EVENT


# --- the kick is an instruction, never a payload (rule 36) ----------------------


async def test_the_narrowest_possible_token_is_still_kicked(tenant: Tenant, owner: User) -> None:
    """A ceiling narrows what a socket may be TOLD. It does not narrow hanging up.

    The token here is scoped to a section that emits nothing this test pushes,
    so every frame it could receive is filtered — and revoking it must still
    close the connection. A kick that a narrow ceiling could suppress would be a
    revocation the client could ignore by holding a narrow token, which is the
    exact inversion of what a revocation is for.
    """
    token, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="doomed-narrow",
        scopes=["messaging:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    async with opened(PATH, bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True
        # A widget frame is filtered out, which is what makes this socket the
        # narrow one — and then the kick still lands.
        await push_event(tenant_id=tenant.pk, event=an_event())
        assert await socket.received_nothing() is True

        await run_db(
            revoke_token,
            token=token,
            tenant=tenant,
            actor=actor_for(user=token.user, tenant=token.tenant),
        )
        closed = await socket.output()

    assert closed["type"] == "websocket.close", closed
    assert closed["code"] == CLOSE_KICKED, closed


# --- the decision itself, without a socket -------------------------------------


def test_an_app_with_no_section_cannot_be_heard_by_a_scoped_token() -> None:
    """Fail closed, said out loud.

    `apps.realtime` declares no tagged router, so no scope can name it — and a
    ceiling that cannot name a thing does not reach it. The alternative would
    let every narrow token hear from whichever app has not grown a door yet,
    which is a hole that widens as the product grows rather than closing.
    """
    consumer = TenantEventsConsumer()
    consumer.ceiling = ["widgets:read"]
    assert consumer.may_hear("realtime.something.happened") is False
    assert consumer.may_hear("example.widget.created") is True

    consumer.ceiling = None
    assert consumer.may_hear("realtime.something.happened") is True


# --- the ceiling and the hat, on one socket (ADR ident-7) --------------------------


async def test_a_hatted_bearer_socket_is_narrowed_by_its_ceiling_too(
    network: Network,
) -> None:
    """**The half an earlier test excluded.** Two narrowings, one connection, one frame each.

    The ceiling proofs above are org-less and the hat-parity proofs are
    ceiling-less, so between them nothing said what happens when a *scoped*
    token opens a socket that *did* resolve a hat. The two answer different
    questions — the hat decides which groups this connection joined, the
    ceiling decides what the credential may be told once a group has reached it
    — and a socket where either quietly disabled the other would have passed
    both existing halves.

    The branch is held constant and only the family varies, which is what makes
    this a test of the ceiling rather than a second test of the hat: all three
    frames are pushed to branch B's group, the group this socket joined because
    its `X-Org` resolved. If the hat had not resolved the socket would be in no
    branch group at all and the first assertion — the one that must *receive* —
    fails, so the test cannot pass by everything being silent.

    Nor can it pass by the socket having quietly died in the middle: the
    in-family frame is asserted again after the silence.
    """
    headers = await hatted_bearer_headers(
        user=network.rival,
        tenant=network.tenant,
        scopes=["widgets:read"],
        org=network.branch_b,
        name="hatted-widgets",
    )

    async with opened(PATH, headers) as (socket, handshake):
        assert handshake.accepted is True

        # The hat resolved: a branch-B frame reaches a socket in branch B's
        # group, and the ceiling names widgets, so it is told.
        await push_event(
            tenant_id=network.tenant.pk,
            event=an_event_in_branch(WIDGET_EVENT, network.branch_b),
        )
        assert (await socket.receive_json())["name"] == WIDGET_EVENT

        # Same branch, same group, another app: the group delivered it and the
        # ceiling refused it. This is the frame neither half of the suite saw.
        await push_event(
            tenant_id=network.tenant.pk,
            event=an_event_in_branch(MESSAGE_EVENT, network.branch_b),
        )
        assert await socket.received_nothing() is True

        # Still open, still in the branch: the silence above was the ceiling.
        await push_event(
            tenant_id=network.tenant.pk,
            event=an_event_in_branch(WIDGET_EVENT, network.branch_b),
        )
        assert (await socket.receive_json())["name"] == WIDGET_EVENT


async def test_a_hatted_bearer_socket_is_still_kicked(network: Network) -> None:
    """A hat does not make a revocation optional either.

    The twin above this section proves it for a narrow token with no hat. The
    hat is a second thing that decides what a connection receives, and "the
    kick is an instruction, never a payload" (rule 36) has to survive both: a
    revocation a client could ignore by holding a narrow token *and* standing in
    a branch would be no revocation at all.

    The socket is shown narrow first — a branch-B frame its ceiling refuses —
    so that the close cannot be mistaken for a connection that was never
    receiving anything.
    """
    token, plaintext = await run_db(
        issue_token,
        user=network.rival,
        tenant=network.tenant,
        name="doomed-hatted",
        scopes=["messaging:read"],
        actor=actor_for(user=network.rival, tenant=network.tenant),
    )
    headers = [*bearer_headers(str(plaintext)), (b"x-org", network.branch_b.slug.encode())]

    async with opened(PATH, headers) as (socket, handshake):
        assert handshake.accepted is True

        await push_event(
            tenant_id=network.tenant.pk,
            event=an_event_in_branch(WIDGET_EVENT, network.branch_b),
        )
        assert await socket.received_nothing() is True

        await run_db(
            revoke_token,
            token=token,
            tenant=network.tenant,
            actor=actor_for(user=token.user, tenant=token.tenant),
        )
        closed = await socket.output()

    assert closed["type"] == "websocket.close", closed
    assert closed["code"] == CLOSE_KICKED, closed
