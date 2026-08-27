"""The hierarchy on the socket: who is joined to what, and who therefore hears it.

`test_consumers.py` proves the tenant boundary — a Globex socket never sees an
Acme event. That boundary was never the whole answer, because a tenant with a
dealer network is *one tenant whose members must not see each other*: the REST
door reads an `OrgScopedModel` through `.for_tenant(t).visible_to(actor)` and
answers one branch's rows, while the socket door pushed every fanned event to
one group per tenant and answered *everybody's*. Two doors, one question, two
answers — the disagreement `architecture.md` calls a finding, and an earlier field test found it.

**The shape that closes it (ADR realtime-2).** An org-bearing event is pushed to
`org_group(tenant, org)` — the row's own branch, one group, one send — and a
consumer joins **its hat's subtree** at connect, so a hat hears its own branch
and everything under it and nothing above or beside it. Org-less events keep
going to the bare tenant group, which every consumer still joins, so the
tenant-wide contract is untouched. A flat product is a depth-one tree whose root
hat joins one org group: the depth-one property CLAUDE.md promises, paid for at
connect rather than on every push.

Every test here drives the **real chain** — `emit()` → the spine's
`push_realtime` activity → `core.bridge` → the channel layer → the consumer →
the wire — for the reason `test_spine_end_to_end.py` gives: the hops between
those arrows are where a rename goes unnoticed until a customer notices first.
Nothing here imports `apps.events`; the two apps are siblings in the layer
contract, so the spine is reached the way production reaches it.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import bridge
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from apps.realtime.bridge import kick_from_spine, kick_user, org_group, tenant_group, user_group
from apps.realtime.schemas import CLOSE_KICKED, CLOSE_NO_TENANT, CLOSE_NOT_A_COMMAND
from apps.realtime.tests.test_consumers import opened, session_headers
from apps.realtime.tests.websocket import Handshake, Socket

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

# The example app's event, as a literal: a name has to be one an app declares
# (`emit` refuses one that is not) and this app may not import that one.
EVENT_NAME = "example.widget.created"

PASSWORD = "not-a-real-password"  # pragma: allowlist secret


@dataclass(frozen=True)
class Network:
    """One tenant's tree and one person per hat, as a single fixture value.

        hq
        ├── branch-a
        │   └── leaf-a1
        └── branch-b

    `branch_b` is both *a leaf* and *the sibling branch*, which is what makes it
    the one connection that must hear nothing when `branch_a` is written to.
    """

    tenant: Tenant
    hq: Organization
    branch_a: Organization
    leaf_a1: Organization
    branch_b: Organization
    owner: User  # hat: hq (the root)
    manager: User  # hat: branch-a
    rival: User  # hat: branch-b


def _build_network(*, tenant: Tenant, owner: User) -> Network:
    hq = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=hq)
    branch_a = create_organization(
        tenant=tenant, parent=hq, name="Branch A", slug="branch-a", actor=acting
    )
    branch_b = create_organization(
        tenant=tenant, parent=hq, name="Branch B", slug="branch-b", actor=acting
    )
    leaf_a1 = create_organization(
        tenant=tenant, parent=branch_a, name="Leaf A1", slug="leaf-a1", actor=acting
    )

    manager = create_user(email="manager@example.com", password=PASSWORD)
    add_membership(
        user=manager,
        tenant=tenant,
        organization=branch_a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    rival = create_user(email="rival@example.com", password=PASSWORD)
    add_membership(
        user=rival,
        tenant=tenant,
        organization=branch_b,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return Network(
        tenant=tenant,
        hq=hq,
        branch_a=branch_a,
        leaf_a1=leaf_a1,
        branch_b=branch_b,
        owner=owner,
        manager=manager,
        rival=rival,
    )


@pytest.fixture
def network(tenant: Tenant, owner: User) -> Network:
    return _build_network(tenant=tenant, owner=owner)


def _emit_and_push(*, tenant: Tenant, actor: Actor, payload: dict[str, Any]) -> Any:
    """Say it happened, then run the dispatch's push hop. Synchronous, like both.

    The same helper `test_spine_end_to_end.py` uses, and for the same reason:
    only the Temporal *transport* stands in (the contextvar is set directly
    instead of arriving on a workflow header). Every hop that could drift —
    the bridge lookup, the envelope, the coercion, the group send — is real.
    """
    context = importlib.import_module("apps.workflows.context")
    activities = importlib.import_module("apps.events.activities")
    types = importlib.import_module("apps.events.types")

    emit = bridge.get(bridge.EMIT)
    event = emit(name=EVENT_NAME, tenant=tenant, payload=payload, actor=actor)

    context.set_principal(tenant_id=str(tenant.pk), user_id=None)
    assert activities.push_realtime(types.PushRealtime(event_id=str(event.pk))) is True
    return event


def in_branch(organization: Organization | None) -> dict[str, Any]:
    """An org-scoped row's payload, as its own `Out` schema would serialise it.

    Built as a plain body rather than through `apps.example`: what this
    derivation actually reads is `payload["organization_id"]`, and a platform
    app's tests reaching up into a domain app to produce one dictionary key
    would be a dependency taken for no reason.
    """
    body: dict[str, Any] = {"id": "8f14e45f-ea1e-7c2b-8000-000000000001", "name": "A widget"}
    if organization is not None:
        body["organization_id"] = str(organization.pk)
    return body


@asynccontextmanager
async def hat(
    *, user: User, org: Organization | None = None
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """A live socket for this person, wearing this hat.

    `X-Org` on the handshake is the same header the HTTP door reads, resolved by
    the same `core.middleware.resolve_org` — which is the property that makes
    "the hat a socket may wear" and "the hat a request may wear" one rule.
    """
    headers = await session_headers(user)
    if org is not None:
        headers = [*headers, (b"x-org", org.slug.encode())]
    async with opened(headers=headers) as pair:
        yield pair


# --- The leak, before anything closes it --------------------------------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_sibling_branchs_socket_never_sees_this_branchs_row(
    network: Network,
) -> None:
    """**The reviewer's probe.** Branch B is connected; branch A is written to.

    This is that finding's HIGH stated as a test. The rival holds a hat on branch B and
    nothing above it, so the REST door would answer them nothing for a branch-A
    row — `visible_to` is a downward prefix scan and branch A is neither their
    node nor under it. The socket door must agree.

    It cannot pass vacuously: the rival's socket is proved live first by an
    org-less event, which is tenant-wide and must arrive, and then proved silent
    for the branch-A row. "Received nothing" from a socket that was quietly
    broken would otherwise read as isolation.
    """
    manager_hat = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )

    async with hat(user=network.rival, org=network.branch_b) as (socket, handshake):
        assert handshake.accepted is True

        # Live: a tenant-wide event reaches every socket in the tenant.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(None),
        )
        assert (await socket.receive_json())["name"] == EVENT_NAME

        # Silent: a branch-A row is not theirs, on this door as on every other.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.branch_a),
        )
        assert await socket.received_nothing() is True


# --- The hierarchy, over the wire, on three live connections -----------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_branchs_event_reaches_its_ancestors_and_no_one_beside_it(
    network: Network,
) -> None:
    """Three hats, one branch written to, and each socket's frames counted.

    Root is *above* branch A, so it hears it: visibility flows down, and a
    parent seeing its children is the direction that is allowed. Branch A is the
    branch itself. Branch B is beside it — neither above nor below — and hears
    nothing, which is the same answer `visible_to` gives that hat over REST.

    The three sockets are open **at the same time** deliberately: one push, one
    `group_send`, three different outcomes decided entirely by what each
    connection joined. Run one at a time it would prove the same rule three
    times and never prove that the rule is applied per connection.
    """
    manager_hat = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )

    async with (
        hat(user=network.owner, org=network.hq) as (root_socket, root_handshake),
        hat(user=network.manager, org=network.branch_a) as (region_socket, region_handshake),
        hat(user=network.rival, org=network.branch_b) as (leaf_socket, leaf_handshake),
    ):
        assert [root_handshake.accepted, region_handshake.accepted, leaf_handshake.accepted] == [
            True,
            True,
            True,
        ]

        # An org-scoped write into the region.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.branch_a),
        )
        assert (await root_socket.receive_json())["name"] == EVENT_NAME
        assert (await region_socket.receive_json())["name"] == EVENT_NAME
        assert await leaf_socket.received_nothing() is True

        # An org-less write is tenant-wide, exactly as it has always been.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(None),
        )
        assert (await root_socket.receive_json())["name"] == EVENT_NAME
        assert (await region_socket.receive_json())["name"] == EVENT_NAME
        assert (await leaf_socket.receive_json())["name"] == EVENT_NAME


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_leaf_under_the_region_is_not_the_region(network: Network) -> None:
    """Downward only, said the other way round: a child does not hear its parent.

    `leaf_a1` sits under `branch_a`. A write to `branch_a` is the *parent's* row,
    and a hat on the leaf may not read it over REST, so it may not hear it here.
    The sibling test above proves sideways; this proves upward, and the two
    together are what "flows down only" means.
    """
    manager_hat = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )

    async with hat(user=network.manager, org=network.leaf_a1) as (socket, handshake):
        assert handshake.accepted is True

        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.branch_a),
        )
        assert await socket.received_nothing() is True

        # Live, and hearing its own: the silence above is scoping, not a corpse.
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.leaf_a1),
        )
        assert (await socket.receive_json())["name"] == EVENT_NAME


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_an_unresolved_hat_is_refused_at_the_handshake(network: Network) -> None:
    """A hat that was SENT and did not resolve refuses the handshake outright.

    `X-Org` naming a node the caller holds no membership on or above resolves to
    `None` — `core.middleware.resolve_org`'s own rule, the one all four doors
    call. **What happens next changed with ADR core-21.** The connection
    used to be accepted: a legitimate member of the tenant, joined to no branch
    group at all, hearing tenant-wide events and nothing of any branch —
    including the one they actually belong to. Empty rather than everything,
    which was fail-closed and was also silent, and silence is what a
    fat-fingered or uninterpolated `X-Org` needs told.

    So the addressing-header law reaches this door too: a sent-and-unhonourable
    header resolves NOWHERE, and `EventConsumer.connect` closes with
    `CLOSE_NO_TENANT`. Sending no `X-Org` at all is untouched — the test below
    is the half that must not move.
    """
    headers = [*await session_headers(network.rival), (b"x-org", b"branch-a")]

    async with opened(headers=headers) as (_socket, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


async def test_sending_no_hat_at_all_still_hears_the_default_branch(network: Network) -> None:
    """The omitted half of the law: a well-behaved socket sees no change."""
    manager_hat = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )
    headers = await session_headers(network.rival)

    async with opened(headers=headers) as (socket, handshake):
        assert handshake.accepted is True

        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.branch_a),  # not the rival's branch
        )
        assert await socket.received_nothing() is True

        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(None),
        )
        assert (await socket.receive_json())["name"] == EVENT_NAME


# --- What a flat product pays --------------------------------------------------------


async def test_a_depth_one_tenant_joins_a_constant_number_of_groups(
    other_tenant: Tenant, stranger: User
) -> None:
    """The depth-one property, asserted at the seam rather than argued in prose.

    A flat product's tenant is a tree of one, so its root hat's subtree is one
    node and the connection joins **three** groups: the tenant's, that one
    branch's, and the caller's own. Three is a constant — it does not grow with
    the tenant, the tree or the number of connections — which is what "a flat
    product pays nothing" has to mean once the user group exists for the kick.

    Asserted as the exact set, not a count: a count would still pass if the
    consumer joined the right *number* of wrong groups, and the group names are
    the whole security property here.
    """
    from channels.layers import get_channel_layer

    from apps.core.services import root_organization

    root = await run_db(root_organization, tenant=other_tenant)

    async with hat(user=stranger, org=root) as (_, handshake):
        assert handshake.accepted is True
        layer = get_channel_layer()
        joined = {name for name, channels in layer.groups.items() if channels}

    assert joined == {
        tenant_group(other_tenant.pk),
        org_group(other_tenant.pk, root.pk),
        user_group(stranger.pk),
    }


async def test_a_deep_hat_joins_its_whole_subtree_and_no_more(network: Network) -> None:
    """The other side of the same seam: what a non-flat hat actually joins.

    Branch A's subtree is itself plus `leaf_a1`, so a hat there joins two branch
    groups. `hq` and `branch_b` are absent — the first is above it and the
    second beside it, and neither is somewhere its rows could come from.
    """
    from channels.layers import get_channel_layer

    async with hat(user=network.manager, org=network.branch_a) as (_, handshake):
        assert handshake.accepted is True
        layer = get_channel_layer()
        joined = {name for name, channels in layer.groups.items() if channels}

    assert joined == {
        tenant_group(network.tenant.pk),
        org_group(network.tenant.pk, network.branch_a.pk),
        org_group(network.tenant.pk, network.leaf_a1.pk),
        user_group(network.manager.pk),
    }


# --- The kick primitive -------------------------------------------------------------


async def test_a_kick_closes_every_socket_that_person_has_and_nobody_elses(
    network: Network,
) -> None:
    """Two connections for one person, one for another. The pair dies.

    This is the seam revocation and erasure will call, proved as a
    primitive before it has a caller. Two sockets for the manager because a
    revocation that closed *a* connection rather than *every* connection would
    pass a single-socket test and leave the second tab receiving.

    The third socket is the control, and it is the reason this cannot pass
    vacuously: it stays open through the same kick, so "everything closed" and
    "the right things closed" are told apart.
    """
    async with (
        hat(user=network.manager, org=network.branch_a) as (first, first_handshake),
        hat(user=network.manager, org=network.branch_a) as (second, second_handshake),
        hat(user=network.rival, org=network.branch_b) as (bystander, bystander_handshake),
    ):
        assert [
            first_handshake.accepted,
            second_handshake.accepted,
            bystander_handshake.accepted,
        ] == [True, True, True]

        await kick_user(user_id=network.manager.pk, reason="token-revoked")

        for socket in (first, second):
            closed = await socket.output()
            assert closed["type"] == "websocket.close"
            assert closed["code"] == CLOSE_KICKED

        assert await bystander.received_nothing() is True
        assert bystander.alive is True


async def test_the_kick_is_on_the_bridge_under_the_name_accounts_will_look_up() -> None:
    """Registered, shaped and findable — the three things a seam has to be.

    `apps.accounts` sits below this app and cannot import the closer, so the
    name is the interface. A registration that existed only as an importable
    function would be a revocation that silently never happened, which is the
    failure `core.bridge`'s whole design exists to make loud.
    """
    assert bridge.KICK == "realtime.kick"
    assert bridge.is_registered(bridge.KICK)
    assert bridge.find(bridge.KICK) is kick_from_spine
    # Optional, like the push: a deployment without this app has no socket to
    # close, so the caller uses `find()` and no-ops rather than refusing.
    assert bridge.KICK in bridge.SHAPES


async def test_the_registered_kick_is_callable_from_a_thread_with_no_loop() -> None:
    """The caller is a plain `def` activity on the worker's thread pool.

    A coroutine function registered here would be a coroutine nobody awaits: the
    revocation would report success and every socket would stay open, which is
    strictly worse than refusing.
    """
    assert not inspect.iscoroutinefunction(kick_from_spine)
    signature = inspect.signature(kick_from_spine)
    assert [p.kind for p in signature.parameters.values()] == [
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
    ]
    assert set(signature.parameters) == {"user_id", "reason"}


async def test_a_kick_for_a_person_with_nothing_open_is_not_an_error() -> None:
    """Idempotent by construction, which is what a retrying activity needs.

    `group_send` to an empty group is a no-op, so kicking twice closes nothing
    the second time and kicking someone who never connected closes nothing at
    all. If this raised, one already-disconnected client would fail the
    revocation for every other socket that person had open.
    """
    await kick_user(user_id="0198f3a2-0000-7000-8000-0000000000ff", reason=None)


# --- Unforgeable groups, still -------------------------------------------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_asking_to_subscribe_to_a_branch_is_still_not_a_command(
    network: Network,
) -> None:
    """The door's best property survives the fix: a client cannot name a group.

    Three kinds of group exist now instead of one, which is three times the
    surface for "let me subscribe to that" — so the refusal is worth restating
    against the frame somebody would actually send. The rival asks for branch A
    by name and is closed on, exactly as any other non-ping frame is.
    """
    async with hat(user=network.rival, org=network.branch_b) as (socket, handshake):
        assert handshake.accepted is True

        await socket.send_json({"type": "subscribe", "organization": "branch-a"})
        closed = await socket.output()

    assert closed["type"] == "websocket.close"
    assert closed["code"] == CLOSE_NOT_A_COMMAND
