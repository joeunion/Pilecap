"""Authorization withdrawal reaches the socket, made permanent.

`test_socket_kick.py` in `apps/accounts` covers the **credential** half: a token
revoked, a user erased, an identity revoked. An earlier finding found the other half
missing entirely. Socket auth *and* socket subscriptions are both resolved once,
at the handshake, so a person whose **hat** was withdrawn mid-connection kept
receiving the old subtree's full `Out` bodies — including
`MessageOut.recipient_email` — for the whole life of the connection, which the
bridge's own docstring expects to be hours. The REST door refuses them on their
very next request; the socket did not.

**The finding was three claims and only two of them were true.** That distinction is
the point of this module, so it is stated here rather than left in a report:

* **Membership removal — real, and closed here.** Once the row is gone
  `resolve_org` resolves no hat for that person in that tenant, so every org
  group their connection holds is a branch they may no longer read.
* **Re-parenting — real, and closed here.** A move withdraws visibility without
  touching a single membership row, so nothing above the old parent sees it
  coming.
* **Demotion — REFUTED.** Role gates *verbs*, never row visibility, at all four
  seams that decide what a connection receives. A demoted person reads exactly
  the same rows over REST, so a socket that keeps delivering them AGREES with
  the REST door. `test_a_demotion_narrows_nothing_a_socket_delivers` is the
  refutation, kept executable so the claim cannot rot back into a assumption.

**Why this module lives in `apps/realtime/tests` and not in `apps/core`'s.** The
rung's app is `core`, but `realtime` sits *above* both `core` and `accounts` in
the layer contract, so a test here imports the services it drives without any
`ignore_imports` line — where the same module under `apps/core/tests/` would
need a new exemption in `pyproject.toml` for a socket client it only borrows.
`test_hierarchy.py` is already the home of "the hierarchy on the socket" and
this is that subject continued, so its `Network`, `hat` and `_emit_and_push`
helpers are reused rather than re-derived.

Everything here drives the **real chain** — the service → `transaction.on_commit`
→ `core.bridge` → the channel layer → the consumer → the wire. The hops between
those arrows are exactly where a rename goes unnoticed until a customer notices
first.
"""

from __future__ import annotations

import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound
from apps.core.middleware import resolve_org
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import (
    add_membership,
    apply_organization_move,
    revoke_membership,
    set_role,
)
from apps.realtime.schemas import CLOSE_KICKED
from apps.realtime.selectors import list_subtree_org_ids
from apps.realtime.tests.test_hierarchy import (
    EVENT_NAME,
    PASSWORD,
    Network,
    _build_network,
    _emit_and_push,
    hat,
    in_branch,
)
from apps.realtime.tests.websocket import Socket

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

PING = {"type": "ping"}
PONG = {"type": "pong"}


@pytest.fixture
def network(tenant: Tenant, owner: User) -> Network:
    """The same tree `test_hierarchy` builds, from the same builder.

    A fixture is module-local to the module that declares it, so this is a
    second `@pytest.fixture` over the *one* `_build_network` rather than a
    second tree — the shape (`hq` -> `branch-a` -> `leaf-a1`, `hq` ->
    `branch-b`) is what both modules reason about and a copy of it here would
    be free to drift.
    """
    return _build_network(tenant=tenant, owner=owner)


async def assert_kicked(socket: Socket) -> None:
    """The close frame this socket must have received, and its code."""
    closed = await socket.output()
    assert closed["type"] == "websocket.close", closed
    assert closed["code"] == CLOSE_KICKED, closed


async def assert_still_working(socket: Socket) -> None:
    """Open is not enough — a ping must come back a pong.

    "Still open" from a task that has not noticed it is dead yet would read as
    survival. The round trip is what makes it a claim about a *working*
    connection, and it is the same control the rollback proof uses elsewhere.
    """
    assert await socket.received_nothing() is True
    assert socket.alive is True
    await socket.send_json(PING)
    assert await socket.receive_json() == PONG


# --- First half: a membership removed ----------------------------------------------


async def test_removing_a_membership_closes_that_persons_sockets(
    network: Network,
) -> None:
    """**The first probe, inverted into a regression.**

    An earlier probe printed `PROBE: after membership deletion the socket STILL received:
    example.widget.created`. It could, because nothing deleted a membership
    through a service at all — the withdrawal had no path, so it had no kick.

    The rival's socket is the control and it is what stops this passing
    vacuously: it stays open and working through the same removal, so
    "everything closed" and "the right thing closed" are told apart.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def membership_of(user: User) -> Membership:
        return Membership.objects.get(user_id=user.pk, tenant=network.tenant)

    doomed = await run_db(membership_of, network.manager)

    async with (
        hat(user=network.manager, org=network.branch_a) as (manager, manager_handshake),
        hat(user=network.rival, org=network.branch_b) as (rival, rival_handshake),
    ):
        assert [manager_handshake.accepted, rival_handshake.accepted] == [True, True]

        await run_db(
            revoke_membership,
            tenant=network.tenant,
            membership=doomed,
            actor=owner_hat,
        )

        await assert_kicked(manager)
        await assert_still_working(rival)


async def test_the_removal_itself_is_a_real_audited_write(network: Network) -> None:
    """The row is gone and the trail says who took it away.

    The kick is a side effect; the removal is the decision, and a security fix
    that closed the socket while leaving the membership in place would be the
    worst of both. `@service` writes the audit row — this asserts it names the
    actor, so "who removed them, and when" is answerable months later.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def remove_and_reread() -> tuple[bool, AuditEntry | None]:
        doomed = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
        revoke_membership(tenant=network.tenant, membership=doomed, actor=owner_hat)
        still_there = Membership.objects.filter(
            user_id=network.manager.pk, tenant=network.tenant
        ).exists()
        entry = (
            AuditEntry.objects.for_tenant(network.tenant)
            .filter(action__endswith="revoke_membership")
            .order_by("-created_at")
            .first()
        )
        return still_there, entry

    still_there, entry = await run_db(remove_and_reread)
    assert still_there is False
    assert entry is not None
    assert entry.actor_user_id == network.owner.pk


async def test_a_removal_that_does_not_commit_kicks_nobody(network: Network) -> None:
    """A refused write must not announce itself by hanging the person up.

    The failure is planted *inside* the transaction the service's `@service`
    joined, so the whole thing rolls back: the membership survives and the
    socket must be exactly as it was. A kick registered anywhere but
    `transaction.on_commit` would fire here — a side effect outside the
    transaction, which is the class this criterion exists to catch.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        def remove_then_fail() -> None:
            with transaction.atomic():
                doomed = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
                revoke_membership(tenant=network.tenant, membership=doomed, actor=owner_hat)
                raise RuntimeError("planted: the surrounding write failed after the removal")

        with pytest.raises(RuntimeError):
            await run_db(remove_then_fail)

        await assert_still_working(socket)

        def survived() -> bool:
            return Membership.objects.filter(
                user_id=network.manager.pk, tenant=network.tenant
            ).exists()

        assert await run_db(survived) is True


async def test_a_removal_the_actor_may_not_make_kicks_nobody(network: Network) -> None:
    """A refusal is not a withdrawal, so it closes nothing.

    **Three refusals, and they are deliberately different refusals.**

    * *Out of reach* — the rival administers branch B and nothing above it, so
      the manager's branch-A membership is `NotFound`: a `Forbidden` would
      confirm that this person holds a membership on a branch the rival cannot
      see at all (rule 26).
    * *Above the ceiling* — an `admin` of branch A **can** reach a membership at
      leaf-A1, which is under them, and is still refused `Forbidden` when that
      membership is an `owner`. This is the escalation wall's mirror image: an
      admin who may not *grant* `owner` must not be able to remove one either,
      or the wall is walked around by subtraction instead of by grant.
    * *Upward is not reachable at all* — the manager asking for the tenant
      owner's membership at hq gets `NotFound` rather than the ceiling's
      `Forbidden`, because reachability is asked first and hq is above them.
      The order of the two guards is itself the property: swapping them would
      turn "there is somebody above you" into a discoverable fact.

    The socket stays open and working through all three.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)
    rival_hat = await run_db(
        actor_for, user=network.rival, tenant=network.tenant, org=network.branch_b
    )
    manager_hat = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )

    def build() -> tuple[Membership, Membership, Membership]:
        # An owner sitting UNDER the manager: reachable, and outranking them.
        deputy = create_user(email="deputy@example.com", password=PASSWORD)
        beneath = add_membership(
            user=deputy,
            tenant=network.tenant,
            organization=network.leaf_a1,
            is_default=True,
            role=Membership.Role.OWNER,
            actor=owner_hat,
        )
        return (
            Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant),
            beneath,
            Membership.objects.get(user_id=network.owner.pk, tenant=network.tenant),
        )

    manager_membership, deputy_membership, owner_membership = await run_db(build)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        # Out of reach: branch A is neither the rival's node nor under it.
        with pytest.raises(NotFound):
            await run_db(
                revoke_membership,
                tenant=network.tenant,
                membership=manager_membership,
                actor=rival_hat,
            )

        # Reachable, but above the ceiling: an admin may not remove an owner.
        with pytest.raises(Forbidden):
            await run_db(
                revoke_membership,
                tenant=network.tenant,
                membership=deputy_membership,
                actor=manager_hat,
            )

        # Upward: not reachable, so this is NotFound and not the ceiling.
        with pytest.raises(NotFound):
            await run_db(
                revoke_membership,
                tenant=network.tenant,
                membership=owner_membership,
                actor=manager_hat,
            )

        await assert_still_working(socket)

        def all_survived() -> int:
            return Membership.objects.filter(
                pk__in=[
                    manager_membership.pk,
                    deputy_membership.pk,
                    owner_membership.pk,
                ]
            ).count()

        assert await run_db(all_survived) == 3


async def test_the_last_owner_may_not_be_removed(network: Network) -> None:
    """A tenant with no owner is a tenant nobody can administer.

    The same invariant `erase_user` protects, reached the other way. Nobody
    notices the state until they need to invite a member or change a role, by
    which time the only remedy is a database console.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def own_membership() -> Membership:
        return Membership.objects.get(user_id=network.owner.pk, tenant=network.tenant)

    theirs = await run_db(own_membership)
    with pytest.raises(Conflict):
        await run_db(revoke_membership, tenant=network.tenant, membership=theirs, actor=owner_hat)


# --- Second half: a subtree re-parented ---------------------------------------------


async def test_re_parenting_closes_only_the_sockets_that_lost_sight(
    network: Network,
) -> None:
    """**The subtlest half**, and the one where a wrong answer is a leak
    *or* a mass disconnect.

    `leaf-a1` moves from `branch-a` to `branch-b`. Four hats are connected and
    the move sorts them into exactly two groups:

    * **branch-a's manager LOSES sight.** `leaf-a1` was under their node and is
      not any more, yet their connection still holds `org_group(leaf-a1)` from
      the handshake and would keep delivering that branch's rows. Kicked.
    * **hq's owner keeps it** — the root is an ancestor of `leaf-a1` before and
      after, so nothing about their view changed.
    * **the resident of leaf-a1 keeps it** — their hat travels with the node,
      and the groups are keyed on organization *ids*, which a move does not
      change. Kicking them would be the mass disconnect.
    * **branch-b's rival GAINS sight** and is deliberately not kicked. Their
      connect-time groups are now a strict subset of what they may see, which is
      staleness rather than a leak — the same lossy contract the voluntary
      `X-Org` switch already declares.

    Three controls to one kick, because "who was closed" is only half the
    property and the expensive half to get wrong is the other one.
    """

    def add_resident() -> User:
        person = create_user(email="resident@example.com", password=PASSWORD)
        add_membership(
            user=person,
            tenant=network.tenant,
            organization=network.leaf_a1,
            is_default=True,
            role=Membership.Role.ADMIN,
            actor=system_actor(tenant=network.tenant),
        )
        return person

    resident = await run_db(add_resident)
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    async with (
        hat(user=network.manager, org=network.branch_a) as (manager, manager_handshake),
        hat(user=network.owner, org=network.hq) as (chief, chief_handshake),
        hat(user=resident, org=network.leaf_a1) as (inside, inside_handshake),
        hat(user=network.rival, org=network.branch_b) as (rival, rival_handshake),
    ):
        assert [
            manager_handshake.accepted,
            chief_handshake.accepted,
            inside_handshake.accepted,
            rival_handshake.accepted,
        ] == [True, True, True, True]

        await run_db(
            apply_organization_move,
            tenant=network.tenant,
            organization=network.leaf_a1,
            new_parent=network.branch_b,
            actor=owner_hat,
        )

        # The one who lost sight.
        await assert_kicked(manager)
        # The three who did not.
        for survivor in (chief, inside, rival):
            await assert_still_working(survivor)


async def test_a_move_that_does_not_commit_kicks_nobody(network: Network) -> None:
    """Rollback honesty for the re-parent, the same shape as the removal's.

    The re-parent registers its kicks from inside `apply_organization_move`'s
    transaction, which is where the paths are rewritten. A planted failure after
    the rewrite must take the kicks down with the paths — otherwise a move that
    never happened disconnects the very people it would have affected, and the
    tree still says it did not happen.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        def move_then_fail() -> None:
            with transaction.atomic():
                apply_organization_move(
                    tenant=network.tenant,
                    organization=network.leaf_a1,
                    new_parent=network.branch_b,
                    actor=owner_hat,
                )
                raise RuntimeError("planted: the surrounding write failed after the move")

        with pytest.raises(RuntimeError):
            await run_db(move_then_fail)

        await assert_still_working(socket)

        def parent_of_leaf() -> Organization:
            return Organization.objects.for_tenant(network.tenant).get(pk=network.leaf_a1.pk)

        assert (await run_db(parent_of_leaf)).parent_id == network.branch_a.pk


# --- The third claim, refuted ---------------------------------------------------


async def test_a_demotion_narrows_nothing_a_socket_delivers(network: Network) -> None:
    """**The third claim, and it is wrong.** The socket stays open on purpose.

    An earlier probe printed `PROBE: after demotion the socket STILL received:
    example.widget.created` and read it as the same leak as the other two. It is
    not. Role gates *verbs*; it has no part in deciding what a connection
    receives, at any of the four seams that decide it:

    * the consumer's group set is `tenant_group + org_group per subtree id +
      user_group` (`apps/realtime/consumers.py`);
    * the subtree comes from `list_subtree_org_ids`, a pure path prefix scan
      that takes `tenant` and `org` and no role (`apps/realtime/selectors.py`);
    * the hat comes from `resolve_org`, which reads `Membership.organization`
      and never `Membership.role` (`apps/core/middleware.py`);
    * `visible_to` is path-based (`apps/core/models.py`).

    So this test asserts the *reason* and not merely the behaviour: the hat and
    the subtree the consumer would compute on a fresh reconnect are **identical
    before and after** the demotion. There is nothing to narrow, the socket
    agrees with the REST door, and kicking here would drop a live connection to
    enforce a narrowing that does not exist.

    The trigger that would reverse this is recorded where the next reader will
    look — `apps/realtime/bridge.py`'s module docstring — and the seam is
    already built, so reversing it is one guarded line in `set_role`.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def resolved() -> tuple[str | None, set[str]]:
        org = resolve_org(user=network.manager, tenant=network.tenant, requested_slug=None)
        subtree = list_subtree_org_ids(tenant=network.tenant, org=org)
        return (str(org.pk) if org is not None else None, {str(one) for one in subtree})

    before = await run_db(resolved)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        def demote() -> Membership:
            membership = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
            return set_role(
                tenant=network.tenant,
                membership=membership,
                role=Membership.Role.MEMBER,
                actor=owner_hat,
            )

        demoted = await run_db(demote)
        assert demoted.role == Membership.Role.MEMBER

        # The socket is untouched, and still working.
        await assert_still_working(socket)

        # And it is untouched for a reason: a fresh connection would join
        # exactly the same groups, so nothing was left over-subscribed.
        assert await run_db(resolved) == before

        # The proof that this is not vacuous: the branch-A row still arrives,
        # which is what the REST door would still answer this person too.
        manager_hat = await run_db(
            actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
        )
        await run_db(
            _emit_and_push,
            tenant=network.tenant,
            actor=manager_hat,
            payload=in_branch(network.branch_a),
        )
        assert (await socket.receive_json())["name"] == EVENT_NAME


async def test_a_promotion_does_not_close_the_socket_either(network: Network) -> None:
    """A widening leaves the connect-time groups a subset of what may now be seen.

    Stated separately from the demotion because it is true for a *different*
    reason, and a reader who only saw the demotion test could conclude that role
    writes are exempt by accident rather than by argument. Even in a product
    that one day gates row visibility by role, a promotion still needs no kick:
    under-subscribed is staleness, and staleness rides the reconnect seam.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def demote_first() -> None:
        membership = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
        set_role(
            tenant=network.tenant,
            membership=membership,
            role=Membership.Role.MEMBER,
            actor=owner_hat,
        )

    await run_db(demote_first)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        def promote() -> Membership:
            membership = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
            return set_role(
                tenant=network.tenant,
                membership=membership,
                role=Membership.Role.ADMIN,
                actor=owner_hat,
            )

        assert (await run_db(promote)).role == Membership.Role.ADMIN
        await assert_still_working(socket)


# --- The seam, and the deployment that has no socket app ----------------------


async def test_a_removal_still_happens_where_the_socket_app_is_not_installed(
    network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout without `apps.realtime` must still be able to remove somebody.

    `find()` and not `get()`, which is the difference between "optional" and
    "required" on the bridge and is what `core/bridge.py` documents this name
    as. The removal is the important half: a deployment that dropped the socket
    app has no socket to close, and an authorization withdrawal that started
    failing in production because of that would be the wrong way round.
    """
    from apps.core import bridge

    monkeypatch.setitem(bridge._registry, bridge.KICK, None)
    monkeypatch.delitem(bridge._registry, bridge.KICK)

    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def remove_and_check() -> bool:
        doomed = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
        revoke_membership(tenant=network.tenant, membership=doomed, actor=owner_hat)
        return Membership.objects.filter(user_id=network.manager.pk, tenant=network.tenant).exists()

    assert await run_db(remove_and_check) is False


async def test_the_kick_reasons_are_constants_and_distinct() -> None:
    """Three reasons, three greppable strings, no literal at a call site.

    A reason is the free text on the kick's log line, and a log line is a thing
    somebody greps months later during an incident. A literal at the call site
    would be one typo away from a withdrawal nobody can find again — and now
    that two apps call one seam, the reasons are also how you tell which app
    decided.
    """
    from apps.accounts import services as accounts_services
    from apps.core import services as core_services

    reasons = {
        core_services.KICK_MEMBERSHIP_REVOKED,
        core_services.KICK_ORGANIZATION_MOVED,
        accounts_services.KICK_TOKEN_REVOKED,
        accounts_services.KICK_USER_ERASED,
        accounts_services.KICK_IDENTITY_REVOKED,
    }
    assert len(reasons) == 5
    assert core_services.KICK_MEMBERSHIP_REVOKED.startswith("core.")
    assert accounts_services.KICK_TOKEN_REVOKED.startswith("accounts.")


async def test_the_seam_was_promoted_and_not_copied() -> None:
    """`accounts` re-exports `core`'s function; there is not a second one.

    An earlier fix had to seal exactly this shape when `SENDABLE` existed twice
    and the retry path drifted from the wall. A security seam with two
    implementations is that bug waiting to be written, so the promotion is
    asserted as an identity rather than trusted to review — and the on-commit
    survey in `apps/workflows/tests/test_services.py` is the other half, which
    fails if a copy ever reappears.
    """
    from apps.accounts import services as accounts_services
    from apps.core import services as core_services

    assert accounts_services.close_sockets is core_services.close_sockets
    assert accounts_services.close_sockets_on_commit is core_services.close_sockets_on_commit
