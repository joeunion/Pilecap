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
* **Demotion — REFUTED in Phase W, and the refutation EXPIRED in Phase R.** Role
  gated *verbs* and never row visibility, at the four seams that then decided
  what a connection receives, so a demoted person read exactly the same rows
  over REST and a socket that kept delivering them agreed with the REST door.
  ADR core-27 added a fifth seam — `consumers.may_hear`, against the read set —
  and role is what fills it, so a demotion to a role holding no reads now closes
  the socket. `test_a_demotion_that_narrows_a_read_closes_the_socket` replaces
  the refutation and keeps its two facts (the hat and the subtree do not move)
  executable beside the new answer, so nobody re-derives the old conclusion from
  premises that are still true.

**Why this module lives in `apps/realtime/tests` and not in `apps/core`'s.** The
rung's app is `core`, but `realtime` sits *above* both `core` and `accounts` in
the layer contract, so a test here imports the services it drives without any
`ignore_imports` line — where the same module under `apps/core/tests/` would
need a new exemption in `pyproject.toml` for a socket client it only borrows.
`test_hierarchy.py` is already the home of "the hierarchy on the socket" and
this is that subject continued, so its `Network` and `hat` helpers are reused
rather than re-derived.

Everything here drives the **real chain** — the service → `transaction.on_commit`
→ `core.bridge` → the channel layer → the consumer → the wire. The hops between
those arrows are exactly where a rename goes unnoticed until a customer notices
first.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound
from apps.core.middleware import resolve_org
from apps.core.models import Membership, Organization, Role, RolePermission, Tenant
from apps.core.services import (
    add_membership,
    apply_organization_move,
    close_tenant,
    resume_tenant,
    revoke_membership,
    set_role,
    suspend_tenant,
)
from apps.realtime.bridge import user_group
from apps.realtime.schemas import CLOSE_KICKED
from apps.realtime.selectors import list_subtree_org_ids
from apps.realtime.tests.sockets import opened
from apps.realtime.tests.test_consumers import session_headers
from apps.realtime.tests.test_hierarchy import (
    PASSWORD,
    Network,
    _build_network,
    hat,
)
from apps.realtime.tests.websocket import Handshake, Socket

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


# --- The third claim, refuted once and then expired -------------------------------


async def test_a_demotion_that_narrows_a_read_closes_the_socket(network: Network) -> None:
    """**The third claim, refuted in Phase W and expired in Phase R.**

    It is worth saying what changed, because the test this replaces was right
    when it was written. `test_a_demotion_narrows_nothing_a_socket_delivers`
    asserted that a demotion moved neither the hat nor the subtree — both still
    true — and concluded that nothing a socket delivers had narrowed. That
    conclusion depended on a fact that is now gone: `allows` used to grant every
    read verb to any membership regardless of role, so role decided verbs and
    never rows. ADR core-27 made a read a permission, and
    `consumers.may_hear` is a **fifth** seam deciding what a connection
    receives — one that role fills. Trigger 1 in `apps/realtime/bridge.py`'s
    docstring is the record of that expiry, marked FIRED rather than deleted.

    **The New Enemy Problem, which is SpiceDB's name for this window** (BVB-3).
    A connection resolves what it may hear at the handshake and caches it for
    hours; a permission shrinks; nothing tells the cache. SpiceDB closes that
    window with a ZedToken the caller carries; there is no such token here and
    the door has no per-frame read to spend, so the kick is what closes it — the
    socket is hung up on and the reconnect recomputes.

    The demotion is `admin` -> the custom `approver`, one include row and no
    reads at all, because `admin` -> `member` narrows NOTHING (a member holds
    every `<kind>.read`) and would kick nobody — correctly. The rival is the
    control: their permissions were not touched and their socket stays working,
    so "everything closed" and "the right thing closed" are told apart.

    What the reconnected connection then computes is
    `apps/realtime/tests/test_read_fanout.py::test_a_kick_then_reconnect_hears_less`;
    this half is the hang-up.
    """
    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)

    def resolved() -> tuple[str | None, set[str]]:
        org = resolve_org(user=network.manager, tenant=network.tenant, requested_slug=None)
        subtree = list_subtree_org_ids(tenant=network.tenant, org=org)
        return (str(org.pk) if org is not None else None, {str(one) for one in subtree})

    before = await run_db(resolved)

    async with (
        hat(user=network.manager, org=network.branch_a) as (socket, handshake),
        hat(user=network.rival, org=network.branch_b) as (rival, rival_handshake),
    ):
        assert [handshake.accepted, rival_handshake.accepted] == [True, True]

        def demote() -> Membership:
            Role.objects.create(tenant=network.tenant, key="approver", name="Approver")
            RolePermission.objects.create(
                tenant=network.tenant,
                role_key="approver",
                permission="widget.approve",
                effect=RolePermission.Effect.INCLUDE,
            )
            membership = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
            return set_role(
                tenant=network.tenant,
                membership=membership,
                role="approver",
                actor=owner_hat,
            )

        demoted = await run_db(demote)
        assert demoted.role == "approver"

        await assert_kicked(socket)
        await assert_still_working(rival)

    # And the hat and the subtree are STILL what they were — the Phase-W
    # argument's two facts, kept executable. What closed the socket is the read
    # set and nothing else, so a reader cannot conclude that a demotion moved
    # somebody's position in the tree.
    assert await run_db(resolved) == before


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
    """Ten reasons — five in `core`, five in `accounts` — derived below, never listed.

    A reason is the free text on the kick's log line, and a log line is a thing
    somebody greps months later during an incident. A literal at the call site
    would be one typo away from a withdrawal nobody can find again — and now
    that two apps call one seam, the reasons are also how you tell which app
    decided.

    **The population is derived from the two modules rather than listed**, and
    that is what changed here. The hand list this replaces named five
    reasons and the tree already held seven: `accounts.user.deactivated` and
    `accounts.user.identity_unlinked` were both live at call sites in
    `apps/accounts/services.py` and in neither the set nor the count, so the
    assertion `len(reasons) == 5` was green over a population of seven. A census
    that cannot notice a member being added is a census wearing a number.

    `core` holds **five** since R4-F3 — revoked, moved, the narrowing the
    socket half above answers, and the two TENANT-wide withdrawals (suspended
    and closed), which are the first reasons here that reach `tenant_group`
    rather than one person's `user_group` — and `accounts` holds five.
    """
    from apps.accounts import services as accounts_services
    from apps.core import services as core_services

    def kicks(module: Any) -> dict[str, str]:
        return {
            name: value
            for name in dir(module)
            if name.startswith("KICK_")
            for value in [getattr(module, name)]
            if isinstance(value, str)
        }

    core_reasons, accounts_reasons = kicks(core_services), kicks(accounts_services)
    assert len(core_reasons) == 5, core_reasons
    assert len(accounts_reasons) == 5, accounts_reasons
    assert core_services.KICK_PERMISSIONS_NARROWED in core_reasons.values()
    assert core_services.KICK_TENANT_SUSPENDED in core_reasons.values()
    assert core_services.KICK_TENANT_CLOSED in core_reasons.values()

    reasons = set(core_reasons.values()) | set(accounts_reasons.values())
    assert len(reasons) == 10, reasons
    assert all(reason.startswith("core.") for reason in core_reasons.values())
    assert all(reason.startswith("accounts.") for reason in accounts_reasons.values())


async def test_the_seam_was_promoted_and_not_copied() -> None:
    """`accounts` re-exports `core`'s function; there is not a second one.

    An earlier fix had to seal exactly this shape when `SENDABLE` existed twice
    and the retry path drifted from the wall. A security seam with two
    implementations is that bug waiting to be written, so the promotion is
    asserted as an identity rather than trusted to review — and rule 92 (every
    `transaction.on_commit(` site under apps/ is a declared seam) is the other
    half, which fails if a copy ever reappears.
    """
    from apps.accounts import services as accounts_services
    from apps.core import services as core_services

    assert accounts_services.close_sockets is core_services.close_sockets
    assert accounts_services.close_sockets_on_commit is core_services.close_sockets_on_commit


# --- R4-F4 · the New Enemy window at CONNECT, closed by ordering ---------------


@asynccontextmanager
async def _at(
    pattern: str, *, user: User, org: Organization
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """A live socket for this person at ONE of the routes `introspect` lists.

    `hat` opens the one route this app declares by name. The census below has to
    open whichever routes the tree declares *today*, so the path is a parameter
    and the pattern comes from the registry rather than from a literal here.
    """
    headers = await session_headers(user)
    headers = [*headers, (b"x-org", org.slug.encode())]
    async with opened(f"/{pattern}", headers=headers) as pair:
        yield pair


def _consumers_introspect_lists() -> list[dict[str, Any]]:
    """The consumer population, derived from the instrument, never typed here.

    `manage.py introspect` reports the patterns `config/asgi.py` discovered, so
    the day a fifteenth app drops a `consumers.py` it joins this census without
    anybody editing this file — which is the whole point of a population-derived
    test and the reason R4's F1 was reachable at all.
    """
    from apps.core.management.commands.introspect import _consumers_payload

    return list(_consumers_payload())


async def test_the_user_group_is_joined_before_any_read(
    network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The ordering, as a census over every consumer the tree declares.**

    A read is where a narrowing can commit underneath a handshake, and the user
    group is the only way a kick reaches this connection. So a consumer that
    reads BEFORE it joins its user group has a window whose width is the width
    of its own reads, and a write landing inside it sends a `group_send` to an
    empty group: the kick is lost and the socket accepts holding the set from
    before the write. No amount of kicking closes that from outside; the fix is
    ordering, and this is what holds it.

    **Both spies are load-bearing and both are asserted non-empty.** `group_add`
    on the live channel layer, `run_db` in the consumer's own module — which is
    the one road a consumer has to the database, `test_read_fanout.py`'s own
    observation. A trace with no read in it would pass the ordering assertion
    while proving nothing, so the read is asserted to have happened.

    The population is `introspect.consumers` and not a literal: one entry today,
    and the fifteenth app's consumer joins this test the day it lands.
    """
    from channels.layers import get_channel_layer

    entries = _consumers_introspect_lists()
    assert entries, "introspect lists no consumer, so this census is watching nothing"

    for entry in entries:
        module = importlib.import_module(str(entry["consumer"]).rsplit(".", 1)[0])
        trace: list[str] = []
        layer = get_channel_layer()
        real_group_add = layer.group_add
        real_run_db = module.run_db

        async def spy_group_add(
            group: str, channel: str, _real: Any = real_group_add, _trace: Any = trace
        ) -> Any:
            _trace.append(f"group_add:{group}")
            return await _real(group, channel)

        async def spy_run_db(
            func: Any, *args: Any, _real: Any = real_run_db, _trace: Any = trace, **kw: Any
        ) -> Any:
            _trace.append(f"run_db:{getattr(func, '__name__', repr(func))}")
            return await _real(func, *args, **kw)

        monkeypatch.setattr(layer, "group_add", spy_group_add)
        monkeypatch.setattr(module, "run_db", spy_run_db)
        try:
            async with _at(str(entry["pattern"]), user=network.manager, org=network.branch_a) as (
                _,
                handshake,
            ):
                assert handshake.accepted is True, entry
        finally:
            monkeypatch.undo()

        joins = [line for line in trace if line.startswith("group_add:")]
        reads = [line for line in trace if line.startswith("run_db:")]
        assert joins, f"{entry['consumer']} joined no group: {trace}"
        assert reads, f"{entry['consumer']} made no read, so the order proves nothing: {trace}"
        assert trace[0] == f"group_add:{user_group(network.manager.pk)}", (
            f"{entry['consumer']} reads before it joins its user group, "
            f"so a narrowing that commits during connect is kicked into an "
            f"empty group and lost: {trace}"
        )


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_narrowing_that_lands_during_connect_still_closes_the_socket(
    network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**R4's D1, re-made: the interleaving, through the `read_kinds` seam.**

    The demotion is committed from inside the read the consumer is making —
    `apps.realtime.consumers.read_kinds`, on the worker thread `run_db` put it
    on — which is the narrowest honest reproduction of "a write landed while
    this connection was resolving what it may hear". The seam is a monkeypatch
    because the window is one statement wide and nothing else can stand in it
    reliably; what is REAL is everything either side of it — `set_role`, its
    transaction, `transaction.on_commit`, `close_sockets`, `core.bridge`, the
    channel layer, the group, the consumer.

    **What the socket must do is accept and then immediately close.** Channels
    dispatches one message at a time, so a kick that arrives while `connect` is
    still running is delivered after `connect` returns: the handshake is
    accepted and the very first frame after it is the close. That is the
    correct outcome rather than a refused handshake — the client sees
    `CLOSE_KICKED`, reconnects, and recomputes under the new read set.

    On the shipped tree the kick went to `user.<pk>` before the connection had
    joined it, so the `group_send` reached an empty group, the kick was lost and
    the socket went on pinging under the set from before the demotion.
    """
    from apps.core import authz

    owner_hat = await run_db(actor_for, user=network.owner, tenant=network.tenant, org=network.hq)
    demotions: list[str] = []

    def demote_then_read(user: Any, tenant: Any, org: Any) -> Any:
        """The write lands INSIDE the read — the one-statement window, widened."""
        if not demotions:
            Role.objects.create(tenant=network.tenant, key="approver", name="Approver")
            RolePermission.objects.create(
                tenant=network.tenant,
                role_key="approver",
                permission="widget.approve",
                effect=RolePermission.Effect.INCLUDE,
            )
            membership = Membership.objects.get(user_id=network.manager.pk, tenant=network.tenant)
            with transaction.atomic():
                set_role(
                    tenant=network.tenant,
                    membership=membership,
                    role="approver",
                    actor=owner_hat,
                )
            demotions.append("approver")
        return authz.read_kinds(user, tenant, org)

    monkeypatch.setattr("apps.realtime.consumers.read_kinds", demote_then_read)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True
        assert demotions == ["approver"], "the seam never ran, so nothing was interleaved"
        await assert_kicked(socket)


async def test_disconnect_still_discards_every_group_the_connection_joined(
    network: Network,
) -> None:
    """The user group moved to the FRONT of `self.groups`, and nothing else moved.

    `AsyncConsumer.websocket_disconnect` discards everything in `self.groups`,
    so re-ordering that list is only safe while the user group is still IN it.
    A `group_add` that stopped being matched by a `group_discard` leaks a channel
    name into the layer that nothing will ever read from again — invisible on an
    in-memory layer that dies with the test, and permanent on Redis.

    Asserted as the whole set before and the empty set after, and the user group
    is asserted to be the FIRST thing joined, which is R4-F4.2's other half.
    """
    from channels.layers import get_channel_layer

    async with hat(user=network.manager, org=network.branch_a) as (_, handshake):
        assert handshake.accepted is True
        layer = get_channel_layer()
        joined = {name for name, channels in layer.groups.items() if channels}
        assert user_group(network.manager.pk) in joined, joined
        assert len(joined) >= 3, joined

    layer = get_channel_layer()
    left_behind = {name for name, channels in layer.groups.items() if channels}
    assert left_behind == set(), left_behind


# --- R4-F3 · a tenant that goes dark hangs up ---------------------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_suspending_a_tenant_closes_every_socket_in_it_and_nobody_elses(
    network: Network, other_tenant: Tenant, stranger: User
) -> None:
    """**R4's F2/D2, re-made.** A suspended tenant's live sockets kept hearing.

    `suspend_tenant` wrote a status and registered nothing: the only kick
    primitive was per PERSON (`bridge.kick_user` -> `user_group`), and a tenant
    going dark is not a fact about one person. So a connected manager heard a
    widget after the suspension and pinged back a pong, while the REST door
    answered 403 for the same credential — two doors, one question, two answers,
    for the whole life of the connection, which the bridge's own docstring
    expects to be hours. A NEW handshake was already refused (R1-F3), which is
    precisely what made the gap invisible.

    Two sockets inside the tenant, at two different hats, because the kick is
    delivered to `tenant_group` and a fix that only reached the acting branch
    would pass with one. The stranger's socket in a second tenant is the
    control that tells "everything closed" from "the right thing closed".
    """
    from apps.core.services import root_organization

    acting = await run_db(system_actor, tenant=network.tenant)
    elsewhere_root = await run_db(root_organization, tenant=other_tenant)

    async with (
        hat(user=network.manager, org=network.branch_a) as (manager, first),
        hat(user=network.owner, org=network.hq) as (owner_socket, second),
        hat(user=stranger, org=elsewhere_root) as (elsewhere, third),
    ):
        assert [first.accepted, second.accepted, third.accepted] == [True, True, True]

        def suspend() -> Tenant:
            return suspend_tenant(tenant=network.tenant, reason="unpaid invoice", actor=acting)

        assert (await run_db(suspend)).status == Tenant.Status.SUSPENDED

        await assert_kicked(manager)
        await assert_kicked(owner_socket)
        await assert_still_working(elsewhere)


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_closing_a_tenant_closes_every_socket_in_it(network: Network) -> None:
    """The terminal half, said separately because it is a different service.

    `close_tenant` is not `suspend_tenant` with another constant: it is the
    end of the relationship and it is the one that must never be the case that
    somebody is still receiving. One service calling the seam does not make its
    sibling call it, which is what the status-writer census in rule 36 is for
    and what this test is the executable half of.
    """
    acting = await run_db(system_actor, tenant=network.tenant)

    async with hat(user=network.manager, org=network.branch_a) as (manager, handshake):
        assert handshake.accepted is True

        def close() -> Tenant:
            return close_tenant(tenant=network.tenant, actor=acting)

        assert (await run_db(close)).status == Tenant.Status.CLOSED
        await assert_kicked(manager)


async def test_a_suspension_that_does_not_commit_kicks_nobody(network: Network) -> None:
    """A refused write must not announce itself by hanging a whole tenant up.

    The failure is planted inside the transaction the service's `@service`
    joined, so the status never lands — and a kick registered anywhere but
    `transaction.on_commit` would disconnect every socket in the tenant on the
    strength of a suspension that did not happen. The same proof
    `test_a_removal_that_does_not_commit_kicks_nobody` makes, one level up,
    where the blast radius is the tenant rather than the person.
    """
    acting = await run_db(system_actor, tenant=network.tenant)

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        def suspend_then_fail() -> None:
            with transaction.atomic():
                suspend_tenant(tenant=network.tenant, reason="unpaid invoice", actor=acting)
                raise RuntimeError("planted: the surrounding write failed after the suspension")

        with pytest.raises(RuntimeError):
            await run_db(suspend_then_fail)

        await assert_still_working(socket)

        def still_active() -> str:
            return str(Tenant.objects.get(pk=network.tenant.pk).status)

        assert await run_db(still_active) == Tenant.Status.ACTIVE


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_resuming_a_tenant_kicks_nobody(network: Network) -> None:
    """A widening kicks nobody, at the tenant level exactly as at the hat's.

    Nothing a socket is delivering has been taken away by a resume, and hanging
    somebody up to give them more is a reconnect storm with no security content
    — `kick_if_reads_narrowed` states the asymmetry and this is the same one.
    The socket here is opened AFTER the suspension, on a tenant whose handshake
    is refused while it is dark, so the resume has to happen first: what this
    proves is that `resume_tenant` registers no kick, not that a suspended
    tenant can connect.
    """
    acting = await run_db(system_actor, tenant=network.tenant)

    def suspend_then_resume() -> Tenant:
        suspend_tenant(tenant=network.tenant, reason="unpaid invoice", actor=acting)
        return resume_tenant(tenant=network.tenant, actor=acting)

    assert (await run_db(suspend_then_resume)).status == Tenant.Status.ACTIVE

    async with hat(user=network.manager, org=network.branch_a) as (socket, handshake):
        assert handshake.accepted is True

        def resume_again() -> Tenant:
            return resume_tenant(tenant=network.tenant, actor=acting)

        assert (await run_db(resume_again)).status == Tenant.Status.ACTIVE
        await assert_still_working(socket)
