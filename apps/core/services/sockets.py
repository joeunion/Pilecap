"""The socket seam."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import UUID

from django.db import transaction

from apps.core import bridge
from apps.core.models import Membership, Tenant, ancestor_paths
from apps.core.roads import road
from apps.core.services._hub import log

# --- The socket seam ----------------------------------------------------------
# **One home for the kick, and this is it.** An earlier rung built this pair inside
# `apps/accounts/services.py`, where the only callers then were credential
# withdrawals (a revoked token, an erased user, the identity-revocation
# activity). SEC-1's MED-1 found the other half: *authorization* withdrawal —
# a membership removed, a subtree re-parented out from under a hat — never
# reached an open socket at all, and those writes live here, in `core`.
#
# `core` may not import `accounts` (rule 7: `core` imports nothing above it), so
# calling A1's function was never available. That left two shapes, and the one
# NOT taken is worth naming: a second `close_sockets` here, mirroring A1's,
# would have been two hand-kept copies of one act — which is precisely the root
# cause P2's SEC-R1b had to seal when `SENDABLE` existed twice and the retry
# path drifted from the wall. So the seam is **promoted** rather than
# duplicated: it lives here, in the app that sits below everything, and
# `apps/accounts/services.py` re-exports it so its own callers and vocabulary
# are unchanged. `accounts` may import `core`; the layer contract is satisfied
# in the direction it already runs.
#
# The reasons stay with their callers — the accounts reasons in accounts, the
# core reasons below — because a reason is the free text on the kick's log line
# and the app that made the decision is the app that has to be greppable for it.
KICK_MEMBERSHIP_REVOKED = "core.membership.revoked"
KICK_ORGANIZATION_MOVED = "core.organization.moved"
#: **The third withdrawal, and Phase R is what made it one.** While reads were
#: free to any membership, narrowing somebody's role took nothing away that a
#: socket was delivering — the subtree and the hat were the whole subscription.
#: Now a read is a key, so a demotion can silence a kind for somebody whose
#: socket was resolved at the handshake and has been delivering it for hours
#: (BVB-3, the New Enemy). The reconnect recomputes.
KICK_PERMISSIONS_NARROWED = "core.permissions.narrowed"
#: **The two TENANT-wide withdrawals** (R4 F2). Every reason above is a fact
#: about one person and reaches one `user_group`; these two are facts about
#: the workspace and reach `tenant_group`, because a suspension that closed
#: the sockets of whoever happened to be named would not have suspended
#: anything. Kept as two strings rather than one with a status on it: a
#: reason is what an operator greps during an incident, and "suspended" and
#: "closed" are different incidents.
KICK_TENANT_SUSPENDED = "core.tenant.suspended"
KICK_TENANT_CLOSED = "core.tenant.closed"


def close_sockets(*, user_id: UUID, reason: str) -> None:
    """Hang up on every socket this person has open. **The kick, from below.**

    Socket auth and socket *subscriptions* are both resolved once, at the
    handshake (`apps/realtime/consumers.py`), which is right for a channel that
    then stays open for hours and wrong the moment what stood behind it is
    withdrawn. Without a way in from outside, a withdrawn credential — or a
    withdrawn hat — keeps receiving until the client happens to disconnect.
    Closing the socket forces the reconnect that recomputes the groups.

    **Reached by name, never by import.** `apps.realtime` sits *above* every app
    that calls this, so `from apps.realtime...` would be the upward import
    `core.bridge` exists to invert. The name is a constant in one module and the
    dependency is declared, so the registry lookup is not a dodge of the tooling.

    **`find()` and not `get()`**, which is this name's declared shape in
    `core/bridge.py`: a deployment without the socket app has no socket to
    close, so the absence is a no-op rather than a refusal. `get()` would make a
    membership removal fail in production on a checkout that dropped
    `apps.realtime`, which is the wrong way round — the removal is the
    important half.

    **Not a `@service` and not audited here.** It writes nothing; the write that
    withdrew the credential or the hat is the audited event, and an audit row
    saying "we also closed some sockets" would be a record of a side effect
    rather than of a decision. It is idempotent by construction (a `group_send`
    to an empty group is a no-op), which is what lets a retrying activity call it.

    **Callers register it on `transaction.on_commit`** — see
    `_register_kick`, the one registration site. The one exception is a
    caller with no transaction to wait for: `apps/accounts/activities.py`'s
    identity-revocation run, which is already past every commit it depends on.
    """
    kick = bridge.find(bridge.KICK)
    if kick is None:
        log.info("core.socket.not_closed", user_id=str(user_id), reason=reason)
        return
    try:
        kick(user_id=user_id, reason=reason)
    except Exception:
        # **The blind spot says its own name.** A LOW security finding: the on-commit
        # registration is `robust=True` (deliberately — see
        # `close_sockets_on_commit`), so a kick that raises is swallowed by
        # Django's hook handler and reported through `django.db.backends.base`.
        # That is not our logging: an operator watching the structured stream
        # saw a clean withdrawal and had no signal that the person's socket
        # survived. This line is that signal, on our own name, with the person
        # on it.
        #
        # Logged **and re-raised**, not swallowed. SEC-R3 gave the reason for
        # the credential callers and it still holds for every caller this seam
        # now has (re-checked when the seam moved to `core`):
        #
        # * `apps/accounts/activities.py` calls this DIRECTLY, outside any
        #   transaction, and its Temporal retry is what eventually closes the
        #   socket — swallowing here would trade one silent failure for a worse
        #   one, because the retry would never be triggered;
        # * every other caller arrives through `close_sockets_on_commit`, where
        #   the re-raise lands in Django's robust branch, is logged there and
        #   cancels no sibling hook. The write it followed has already
        #   committed, so there is nothing to undo and nothing to retry;
        # * the re-parent registers one hook PER person losing sight, and each
        #   is its own `kick_on_commit`, so one channel-layer failure costs that
        #   one socket and not the rest of the list.
        #
        # No caller wants this exception eaten, which is why it is re-raised
        # from the seam rather than handled at three call sites differently.
        log.exception("core.socket.kick_failed", user_id=str(user_id), reason=reason)
        raise


def close_sockets_on_commit(*, user_id: UUID, reason: str) -> None:
    """Ask for the kick once the write that withdrew the access has landed.

    Registered through `_register_kick`, the one declared on-commit seam for a kick (rule 92).
    """

    def kick_on_commit() -> None:
        close_sockets(user_id=user_id, reason=reason)

    _register_kick(kick_on_commit)


def close_tenant_sockets(*, tenant_id: UUID, reason: str) -> None:
    """Hang up on every socket open on this tenant. **The kick, one level up.**

    `close_sockets` answers a withdrawal aimed at a PERSON. This answers one
    aimed at the whole workspace, and until R4 there was no way to say it:
    `suspend_tenant` and `close_tenant` wrote a status and registered
    nothing, so a darkened tenant was refused at the next HANDSHAKE and
    nowhere else — every connection already open went on hearing for the
    hours `apps/realtime/bridge.py` expects one to last, while the REST door
    answered 403 to the same credential. The handshake refusal is precisely
    what made the gap invisible: the road a reviewer walks first was closed.

    Everything else is `close_sockets`' argument unchanged one level up:
    reached by NAME through `core.bridge` because `apps.realtime` sits above
    this app; `find()` and not `get()` because a deployment without the socket
    app has no socket to close and the suspension is the important half; not a
    `@service` because it writes nothing and the status write is the audited
    decision; idempotent by construction, which is what lets a retry call it.

    Logged AND re-raised, for `close_sockets`' reason and with its cost: the
    registration is `robust=True`, so a channel layer that raises leaves the
    write standing and the sockets open, on our own name
    (`core.tenant_socket.kick_failed`) rather than in Django's.
    """
    kick = bridge.find(bridge.KICK_TENANT)
    if kick is None:
        log.info("core.tenant_socket.not_closed", tenant_id=str(tenant_id), reason=reason)
        return
    try:
        kick(tenant_id=tenant_id, reason=reason)
    except Exception:
        log.exception("core.tenant_socket.kick_failed", tenant_id=str(tenant_id), reason=reason)
        raise


def close_tenant_sockets_on_commit(*, tenant_id: UUID, reason: str) -> None:
    """Ask for the tenant-wide kick once the status that darkened it has landed.

    On commit for `close_sockets_on_commit`' reason at tenant scale, where it
    is worse: a kick fired inside the transaction would disconnect EVERY
    socket in a tenant on the strength of a suspension that then rolled back.
    A named nested `def` and never a `functools.partial`, for the reason
    `close_sockets_on_commit` records at length (P3 SEC-R3).

    House rule 36's status-writer class is the static half: every `@service`
    assigning a non-`ACTIVE` `Tenant.Status` calls this in the same body, so
    the third such service cannot be written without it.
    """

    def tenant_kick_on_commit() -> None:
        close_tenant_sockets(tenant_id=tenant_id, reason=reason)

    _register_kick(tenant_kick_on_commit)


@road("socket_kick", example="apps/core/services/sockets.py::close_sockets_on_commit")
def _register_kick(hook: Callable[[], None]) -> None:
    """Register a kick on commit, `robust=True`: a failing kick cancels no sibling hook.

    A named nested `def`, never a `functools.partial`: the robust branch reads `__qualname__`.
    """
    transaction.on_commit(hook, robust=True)


# rule-16: `kick` is this tree's own word for hanging up on a socket, not a
# coinage — `KICK_MEMBERSHIP_REVOKED` and `KICK_ORGANIZATION_MOVED` are the
# two that existed before it and `close_sockets`'s own docstring calls the
# act "the kick, from below". This is the third reason, named for the act a
# reader greps for; it is also the seam PR1.8 declares and P4's two new
# narrowing services call, so the name is a contract across rungs.
def kick_if_reads_narrowed(
    *,
    tenant: Tenant,
    user_id: UUID,
    before: Mapping[UUID, frozenset[str]],
    after: Mapping[UUID, frozenset[str]],
) -> bool:
    """Close this person's sockets when a write made their read set smaller.

    **BVB-3, the New Enemy, and it arrived with Phase R.** A socket resolves
    what it may hear once, at the handshake; the two withdrawals that existed
    before — a membership revoked, a subtree re-parented — each had their own
    kick. A read becoming a permission adds a third: a demotion, a `withhold`,
    a role's collection edited, and a channel that has been delivering a kind
    for hours goes on delivering it. Closing the socket forces the reconnect
    that recomputes.

    **A proper subset at ANY node is the trigger, and a widening is not.**
    `after[node] < before[node]` — strictly smaller — so a promotion, a new
    grant, a role gaining a key kicks nobody: nothing a socket is delivering
    has been taken away, and hanging up on somebody to give them more would be
    a reconnect storm with no security content. A node that disappears from
    `after` entirely (the membership was removed) is a narrowing to the empty
    set, and `revoke_membership`'s own kick already covers that road — this one
    fires first only when the road is a role change.

    **Idempotent, and on commit** (principle 16): it registers through
    `close_sockets_on_commit`, so a rolled-back write kicks nobody and a second
    identical call closes an already-closed socket, which a `group_send` to an
    empty group makes a no-op.

    Returns whether it kicked, so a caller's test can assert the decision
    rather than the side effect.
    """
    narrowed = any(after.get(node, frozenset()) < held for node, held in before.items() if held)
    if not narrowed:
        return False
    close_sockets_on_commit(user_id=user_id, reason=KICK_PERMISSIONS_NARROWED)
    return True


def _members_losing_sight_of(*, tenant: Tenant, old: str, new: str) -> list[UUID]:
    """Whose view of a moving subtree shrinks. **The re-parent's kick list.**

    Re-parenting is the one withdrawal that touches no membership row at all,
    so "who lost access" has to be computed from the two paths rather than read
    off a write. The answer follows from what a hat can see: a membership at
    node `N` sees `N` and everything under it, so it could see the moving node
    `X` before the move exactly when `N` was on `X`'s **old** ancestor chain,
    and can see it after exactly when `N` is on the **new** one.

    So the set that lost sight is `old ancestors - new ancestors`, and that is
    all of it:

    * **Members inside the moving subtree keep everything.** Their hat travels
      with the node — a hat at `X` or below still sees `X` and below — and the
      groups they joined are keyed on organization *ids*, which a move does not
      change. Kicking them would be the mass disconnect this function exists to
      avoid.
    * **Members above the NEW parent gain sight and are not kicked.** Their
      connect-time groups are now a strict subset of what they may see, which is
      staleness, not a leak. They see the subtree from their next reconnect —
      the same lossy contract the voluntary `X-Org` switch already declares.
    * **Members above the OLD parent, and not above the new one, lose sight**
      and are the leak: their sockets still hold an org group for every node in
      the moved subtree and would keep receiving that branch's full `Out`
      bodies for the life of the connection.

    `X` itself is on both chains whenever it is on either, so the difference
    never contains the moving node and a member at `X` is never kicked by it.

    One query, and it is bounded by the ancestor chain rather than by the size
    of the tenant: the paths are decomposed in Python (`ancestor_paths` is
    string work, not a round trip) and the memberships are fetched by an `IN`
    over a handful of paths.
    """
    lost = set(ancestor_paths(old)) - set(ancestor_paths(new))
    if not lost:
        return []
    return list(
        Membership.objects.for_tenant(tenant)
        .filter(organization__path__in=sorted(lost))
        .values_list("user_id", flat=True)
        .distinct()
    )
