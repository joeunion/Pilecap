"""Writes for the core app.

Tenants and memberships are rows like any other: nothing else creates them, and
nothing calls `.save()` on them outside this module. Each function is
`@service` — keyword-only, atomic, traced, logged, audited.

The one asymmetry worth stating: `create_tenant` writes no audit row, because
there is no tenant to scope it to until the moment it returns. The tenant row
itself, with its `created_at`, is the record of its own creation. Everything
that happens *inside* a tenant is audited from the first membership onwards.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# `Membership.user` is declared with `settings.AUTH_USER_MODEL` and typed here as
# `AbstractBaseUser`, so that `core` imports no app above it.
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models, transaction
from django.urls import reverse

from apps.core import bridge, mail
from apps.core.actor import Actor, system_actor
from apps.core.authz import effective_role, may_be_named, rank, require
from apps.core.exceptions import Conflict, Forbidden, Invalid, NotFound, Remedy, as_invalid
from apps.core.flags import FLAGS_KEY
from apps.core.ids import uuid7
from apps.core.log import get_logger
from apps.core.models import (
    PATH_MAX_DEPTH,
    PATH_MAX_LENGTH,
    PATH_SEPARATOR,
    ROOT_SEGMENT,
    Invitation,
    Membership,
    Organization,
    PathOverflow,
    Tenant,
    ancestor_paths,
    child_path,
    decode_path_segment,
    is_descendant_path,
    path_depth,
)
from apps.core.service import service, write_audit
from apps.core.time import in_days, is_past, now
from apps.core.types import Swept

log = get_logger(__name__)

# The allow-list for this app's log lines and audit `input`. A tenant's name and
# slug are public handles, not facts about a person; an email address is a
# person, so it is not on the list.
LOG_KEYS: frozenset[str] = frozenset(
    {"name", "slug", "role", "is_default", "status", "timezone", "locale", "enabled", "reason"}
)

# How long an invitation stands. Long enough to survive a holiday, short enough
# that a link found in an old inbox is not a way in.
INVITATION_DAYS = 14
INVITATION_TOKEN_BYTES = 32

# The workflow that carries a re-parent, named as a string because `core` may
# not import the app that defines it (`apps.workflows.workflows`). See
# `move_organization`.
MOVE_ORGANIZATION_WORKFLOW = "MoveOrganizationWorkflow"

# How many rows the subtree rewrite updates per statement. A move is rare and a
# subtree is usually small; the batch exists so that the one move that is not —
# a national distributor re-parented under a group — does not build a single
# `UPDATE ... IN (<fifty thousand ids>)`.
MOVE_BATCH_SIZE = 500

# The one refusal both the service and its activity give, said once.
TOO_DEEP = "That move would push the subtree past the depth limit."

# The slugs a tenant may not take. `"platform"` is reserved because ADR
# workflows-3 made `WorkflowRun` the deployment-wide run ledger and gave the
# null-tenant population its own first id segment
# (`apps.workflows.services.PLATFORM_SEGMENT`): a tenant wearing that slug would
# mint `platform:<app>:<noun>:<key>` ids indistinguishable from the platform's,
# and `check_workflow_id` — which decides by that segment alone — would let a
# tenant's run and the deployment's collide under one key.
#
# The guard is here, at creation, because it is the closed question: a segment
# that cannot be minted needs no reconciliation later. The value is repeated
# rather than imported because the dependency runs the other way (`core` may not
# import `workflows`; see `bridge`); `apps/core/tests/test_move_matrix.py` pins
# the two together so the repeat cannot drift.
RESERVED_TENANT_SLUGS: frozenset[str] = frozenset({"platform"})


@service
def create_tenant(
    *,
    name: str,
    slug: str,
    owner: AbstractBaseUser | None = None,
    actor: Actor,
) -> Tenant:
    """Create a tenant, **its root organization**, and optionally its first member.

    The slug is the public handle an `X-Tenant` header names.

    **The root is not optional and is not deferred.** Every tenant is a tree,
    and a tenant without a root is a tenant whose every org-scoped read returns
    nothing and whose first membership has nowhere to sit. A flat product never
    thinks about it: the root is created here, named after the tenant, and one
    node is the whole tree until somebody adds a second.

    An `owner` makes the tenant usable in the same transaction that created it:
    a tenant with no members is a tenant nobody can reach, and leaving that gap
    open is how a signup ends half-finished.

    **One slug is refused outright** — `RESERVED_TENANT_SLUGS`, above, says
    which and why. A `SlugField` would happily mint `platform`, and the run
    ledger's two populations are told apart by exactly that word.

    **`actor` is required, and it does NOT make this service audited** (ADR
    core-22, AUDIT-3's rider). ADO-5 stands unchanged: `create_tenant` declares
    no `tenant`, so `@service` writes no row for it, and the birth certificate
    is `create_first_tenant`'s. What the actor is for is the row this call
    *does* write — the owner's first `Membership` — which was landing under
    `system_actor(tenant=tenant)` whoever asked. That is a fabricated altitude
    for an act a named person had just performed at a door holding their
    session, and core-22's L1 ruling is exactly that `system` is a claim about
    who acted rather than a convenient way past the escalation wall. The
    product setting itself up (`manage.py seed`, `create_first_tenant`, the
    perf seeder) passes `system_actor(...)` and the row says so.
    """
    # authz: creating a tenant grants nothing and reaches nothing that already
    # exists — there is no subject a predicate could measure, which is why this
    # service has never called `require` and must not start. The one privileged
    # act inside it IS authorized, one layer down: the actor is forwarded to
    # `add_membership`, where the escalation wall measures it and refuses a
    # human who holds no role in a tenant that did not exist a statement ago.
    # The actor is not kept for a row here — `create_tenant` stays unaudited
    # (ADO-5, unchanged) — it is kept so the wall is handed the truth instead of
    # the fabricated `system` altitude this service used to substitute for it.
    wanted = slug.strip().lower()
    if wanted in RESERVED_TENANT_SLUGS:
        raise Invalid(
            {
                "slug": [
                    f"{wanted!r} is reserved by the platform and cannot be a tenant's slug.",
                ]
            }
        )
    tenant = Tenant(name=name.strip(), slug=wanted)
    with as_invalid():
        tenant.full_clean()
    tenant.save()
    root = _create_root_organization(tenant=tenant)
    if owner is not None:
        add_membership(
            user=owner,
            tenant=tenant,
            organization=root,
            is_default=True,
            # The caller's own actor, forwarded rather than replaced. A `system`
            # caller still lands `system`; a staff member at the admin door now
            # lands as themselves, which is what the trail was missing.
            actor=actor,
        )
    return tenant


def _create_root_organization(*, tenant: Tenant) -> Organization:
    """The tenant's one root node. **Private, and part of `create_tenant`.**

    Not a `@service` of its own, deliberately: it writes inside
    `create_tenant`'s transaction and the tenant row it hangs off is the record
    of its own creation — the same reasoning that leaves `create_tenant`
    unaudited (there is no tenant to scope an audit row to until it returns).
    Nothing else calls it; a second root is refused by the database.

    The root takes the tenant's own slug, so `X-Org: acme` and `X-Tenant: acme`
    name the same place, which is what a flat product expects and what a
    networked one starts from.
    """
    root = Organization(
        tenant=tenant,
        parent=None,
        name=tenant.name,
        slug=tenant.slug,
        path=ROOT_SEGMENT,
        depth=0,
    )
    with as_invalid():
        root.full_clean()
    root.save()
    return root


def root_organization(*, tenant: Tenant) -> Organization:
    """The tenant's root node. A read, not a write — every tenant has exactly one.

    It raises rather than returning `None` because a tenant without a root is
    not a state the product has: `create_tenant` makes one and the database
    holds the invariant. A missing root is a broken database, and saying so
    here is better than handing back a `None` that becomes an empty read three
    layers away.
    """
    root = Organization.objects.for_tenant(tenant).filter(parent__isnull=True).first()
    if root is None:
        raise Conflict(
            f"Tenant {tenant.slug!r} has no root organization. Every tenant is created with "
            "one; this row predates the hierarchy or was written around the service."
        )
    return root


def _landing_node(*, tenant: Tenant, actor: Actor | None) -> Organization:
    """Where a grant lands when the caller named no node — **ADR core-20**.

    The one function both grant doors ask, so that "an omitted placement is the
    acting hat" cannot come to mean two things one service apart. The owner's
    ruling of 2026-08-24: *"comes from where you sent it. Don't elevate out of
    context."*

    **The hat, when there is one.** A caller acting under `X-Org: a-branch` who
    says nothing about placement meant that branch — they are standing in it,
    every read they made in the same session was narrowed to it, and a grant
    that landed anywhere else would be the one act in the request that ignored
    the context. It is also the safe direction and the only one: the hat is
    revalidated against the caller's memberships on every request, so the node
    this returns is always somewhere they already stood. **A caller can only
    ever be surprised narrower.**

    **The root, when there is nobody acting.** `create_tenant`, the seed
    command and `accept_invitation`'s own call into `add_membership` all arrive
    with `actor=None`; a tenant's first membership is the whole tenant by
    definition, and there is no context to inherit. An `Actor` whose hat is
    unresolved reads the same way — `resolve_org` failing closed already refuses
    the request at the door, so this is the belt rather than the decision.

    A flat product pays nothing: its hat IS its root, so every caller gets
    exactly the node they got before this existed.
    """
    if actor is not None and actor.org is not None:
        return actor.org
    return root_organization(tenant=tenant)


# --- The organization tree ---------------------------------------------------


def _next_child_index(*, parent: Organization) -> int:
    """The lowest free segment under `parent`.

    Lowest *free* rather than "one past the highest": a network that opens and
    closes branches for twenty years would otherwise walk the segment space
    upward forever and hit the ceiling with four children left. Reusing a
    retired segment is safe because a path is not an identity — the primary key
    is, and it never moves.
    """
    used = {
        decode_path_segment(str(path).rsplit(PATH_SEPARATOR, 1)[-1])
        for path in Organization.objects.for_tenant(parent.tenant)
        .filter(parent=parent)
        .values_list("path", flat=True)
    }
    index = 0
    while index in used:
        index += 1
    return index


@service
def create_organization(
    *,
    tenant: Tenant,
    parent: Organization,
    name: str,
    slug: str,
    actor: Actor,
) -> Organization:
    """Open a new node under `parent`.

    **Authorization is ancestor-admin**: the actor must hold `admin` or better
    on `parent` or on one of its ancestors (`authz.effective_role`). A branch
    manager may open a sub-branch of their own branch and cannot open one
    beside it, which is the escalation wall said in the other direction — you
    may only add underneath yourself.

    The path is assigned here and nowhere else. The parent row is locked for the
    duration so two concurrent creates cannot pick the same segment; the unique
    constraint on `(tenant, path)` is the second line of that defence.
    """
    require(actor, "organization.create", parent)
    # The lock is on the PARENT, not on the new row: what two concurrent creates
    # contend for is the parent's set of taken segments.
    locked = Organization.objects.for_tenant(tenant).select_for_update().get(pk=parent.pk)
    try:
        path = child_path(locked.path, _next_child_index(parent=locked))
    except PathOverflow as exc:
        raise Invalid({"parent": [str(exc)]}) from exc
    organization = Organization(
        tenant=tenant,
        parent=locked,
        name=name.strip(),
        slug=slug.strip().lower(),
        path=path,
        depth=path_depth(path),
    )
    with as_invalid():
        organization.full_clean()
    organization.save()
    return organization


@service
def rename_organization(
    *,
    tenant: Tenant,
    organization: Organization,
    name: str,
    actor: Actor,
) -> Organization:
    """Change a node's display name. **The slug and the path never move here.**

    The slug is the public handle an `X-Org` header names and the path is what
    every read in the product scans on; renaming is a label change and nothing
    else. Moving a node is `move_organization`, which is a different operation
    with different authorization.
    """
    require(actor, "organization.rename", organization)
    organization.name = name.strip()
    with as_invalid():
        organization.full_clean()
    organization.save(update_fields=["name", "updated_at"])
    return organization


@service
def move_organization(
    *,
    tenant: Tenant,
    organization: Organization,
    new_parent: Organization,
    actor: Actor,
    started_by: AbstractBaseUser | None = None,
) -> Organization:
    """Re-parent a node — **the decision**. The rewrite is a workflow.

    Moving a node moves every row underneath it, in every org-scoped table,
    because visibility is computed from the path. That makes it the one
    operation in the hierarchy that is neither cheap nor instantaneous, and
    `architecture.md` rules it a **service plus a workflow**: this function
    authorizes, refuses the impossible shapes and starts a durable run;
    `apply_organization_move` — reached through the activity — takes the locks
    and rewrites the subtree in batches. A worker that dies halfway leaves the
    run to be retried rather than a half-moved tree.

    **Authorization is ancestor-admin of BOTH ends.** Admin over where it is
    coming from *and* over where it is going, because a move is a grant and a
    revocation at once: everyone above the old parent loses sight of the
    subtree, and everyone above the new one gains it. Holding one end only
    would let a branch admin pull another branch's customers underneath
    themselves.

    Refused outright: moving the root (a tenant has exactly one and it is the
    tree), moving a node under itself or under its own descendant (that is not
    a move, it is an orphaning), and any move that would push the subtree past
    the depth limit.

    The workflow id is deterministic and keyed on the moving node, so a retried
    service starts one run and not two. What that id serialises is **one intent
    at a time**, not one move ever (ADR workflows-4; the four quadrants are
    driven end to end in `apps/core/tests/test_move_matrix.py`):

    * **ask for the same move while it is live** — the same run comes back and
      one execution exists. A client that resent, a queue that redelivered, a
      person who clicked twice: all free, and a row whose process died before
      the client call is *healed* by the second ask;
    * **ask for a different parent while it is live** — `Conflict`, 409 at the
      door. Two destinations for one subtree is a second job wearing the first
      one's key, and until the digest existed the second intent was silently
      answered with the first one's run (F1) — the tree ended up where nobody
      asked and nothing said so;
    * **ask for a different parent once the move has finished** — the row
      supersedes and a fresh execution runs. This is the interlock: now that
      the workflow closes its own row (ADR workflows-5), a node whose id
      fossilised on completion could never be moved a second time;
    * **ask for the same move once it has finished** — `Conflict`. The subtree
      is already there, and re-running completed work is a decision about a new
      key rather than something this layer makes silently.

    None of that is this function's code: the digest is computed inside the
    starter for every caller, which is what makes the grammar a grammar rather
    than an option each service remembers.
    """
    require(actor, "organization.move", organization.parent)
    require(actor, "organization.move", new_parent)
    _refuse_impossible_move(organization=organization, new_parent=new_parent)

    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    build_id = bridge.get(bridge.WORKFLOW_ID)
    start(
        workflow=MOVE_ORGANIZATION_WORKFLOW,
        arg={
            "organization_id": str(organization.pk),
            "new_parent_id": str(new_parent.pk),
        },
        tenant=tenant,
        user=started_by if started_by is not None else actor.user,
        org=actor.org,
        id=build_id(tenant=tenant, app="core", noun="organization", key=str(organization.pk)),
    )
    return organization


def _refuse_impossible_move(*, organization: Organization, new_parent: Organization) -> None:
    """The four shapes that are not a move. Shared by the service and its activity."""
    if organization.is_root:
        raise Invalid(
            {"organization": ["The root is the tree; it has nowhere to move to."]},
        )
    if organization.tenant_id != new_parent.tenant_id:
        raise Invalid(
            {"new_parent": ["A node cannot move to another tenant. That is an export."]},
        )
    if is_descendant_path(new_parent.path, organization.path):
        raise Invalid(
            {"new_parent": ["A node cannot move under itself or under its own descendant."]},
        )
    # The subtree keeps its own shape; only its top moves. Its deepest node ends
    # up as far below the new parent as it currently is below the moving node,
    # plus the one level the move itself adds.
    below = _deepest_descendant_depth(organization=organization) - organization.depth
    if new_parent.depth + 1 + below > PATH_MAX_DEPTH - 1:
        raise Invalid({"new_parent": [TOO_DEEP]})


def _deepest_descendant_depth(*, organization: Organization) -> int:
    deepest = (
        Organization.objects.for_tenant(organization.tenant)
        .filter(path__startswith=organization.path + PATH_SEPARATOR)
        .order_by("-depth")
        .values_list("depth", flat=True)
        .first()
    )
    return int(deepest) if deepest is not None else organization.depth


@service
def apply_organization_move(
    *,
    tenant: Tenant,
    organization: Organization,
    new_parent: Organization,
    actor: Actor,
) -> Organization:
    """Re-parent a node and rewrite its subtree's paths. **The activity's write.**

    Called by `apps.workflows.activities.rewrite_organization_paths` and by
    nothing else. Everything about it is shaped by the fact that it is retried:

    * **Idempotent** — a second run that finds the node already under
      `new_parent` returns it untouched. Temporal guarantees an activity runs at
      least once, and a rewrite that ran twice must not shuffle the tree twice.
    * **Locked** — the node and every descendant are taken with
      `select_for_update` before anything is read for the rewrite, so a create
      landing under a node that is mid-move waits rather than writing a path
      that is about to become wrong. This is the "PROTECT during the move": the
      subtree is held for the duration of one transaction and the `@service`
      decorator is what supplies that transaction.
    * **Batched** — the descendants are rewritten `MOVE_BATCH_SIZE` at a time,
      so a large network moves in bounded statements.

    The paths are recomputed rather than string-spliced on the way in: the new
    prefix is the node's new path, and every descendant keeps its own tail.
    """
    require(actor, "organization.move", new_parent)
    _refuse_impossible_move(organization=organization, new_parent=new_parent)
    if organization.parent_id == new_parent.pk:
        return organization

    # The lock is taken over the whole subtree, in path order, before a single
    # row is rewritten. `select_for_update` on a queryset locks what it reads,
    # and reading it in one deterministic order is what keeps two concurrent
    # moves from deadlocking against each other.
    subtree = list(
        Organization.objects.for_tenant(tenant)
        .filter(
            models.Q(path=organization.path)
            | models.Q(path__startswith=organization.path + PATH_SEPARATOR)
        )
        .select_for_update()
        .order_by("path")
    )
    locked_parent = (
        Organization.objects.for_tenant(tenant).select_for_update().get(pk=new_parent.pk)
    )
    old_prefix = organization.path
    new_prefix = child_path(locked_parent.path, _next_child_index(parent=locked_parent))

    moved: list[Organization] = []
    for node in subtree:
        node.path = new_prefix + node.path[len(old_prefix) :]
        node.depth = path_depth(node.path)
        if len(node.path) > PATH_MAX_LENGTH:
            raise Invalid({"new_parent": [TOO_DEEP]})
        node.updated_at = now()
        moved.append(node)

    # The new prefix is a segment nothing holds yet, so no row in the batch can
    # collide with a row outside it and the unique `(tenant, path)` constraint
    # is never asked to hold two claims on one path mid-rewrite.
    for start in range(0, len(moved), MOVE_BATCH_SIZE):
        Organization.objects.for_tenant(tenant).bulk_update(
            moved[start : start + MOVE_BATCH_SIZE], ["path", "depth", "updated_at"]
        )
    head = moved[0]
    head.parent = locked_parent
    head.save(update_fields=["parent", "updated_at"])

    # SEC-1's MED-1, second half. The kick belongs HERE and not in
    # `move_organization`: kicking at the decision reconnects the person to the
    # same groups before the paths change, leaving the leak intact and looking
    # fixed. Who, and why only them: `_members_losing_sight_of`.
    for user_id in _members_losing_sight_of(tenant=tenant, old=old_prefix, new=new_prefix):
        close_sockets_on_commit(user_id=user_id, reason=KICK_ORGANIZATION_MOVED)
    return head


# --- The socket seam ----------------------------------------------------------
# **One home for the kick, and this is it.** P3-A1 built this pair inside
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
    `close_sockets_on_commit`, the one registration site. The one exception is a
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
        # **The blind spot says its own name.** P3-SEC-1's LOW-3: the on-commit
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

    **The one registration site in the tree for this act**, so there is one
    place to read the two decisions in it rather than one per caller — and so
    `apps/workflows/tests/test_services.py`'s on-commit survey stays a list a
    person can read.

    *On commit*, because a kick fired inside the transaction would disconnect
    somebody on the strength of a write that then rolled back — a removal that
    never happened, announced by hanging the person up.

    *`robust=True`*, because Django runs a transaction's hooks in order and a
    non-robust hook that raises takes every hook behind it down with it (W1-9,
    F3 — the scar is an unreachable Temporal cancelling an invitation email).
    The channel layer is the least reliable thing in that list, and a membership
    removal must not be able to cancel a sibling hook by failing to close a
    socket.

    What `robust=True` costs is stated rather than hidden: a kick that raises is
    logged by Django and dropped, so the write stands and the socket may not
    close. That is this seam's declared blind spot, inherited from A1 and
    unchanged by widening the caller set — LOW-3 (a dropped kick is
    unobservable) is booked to SEC-R3 and is the same gap seen from the other
    side.

    **The blind spot is observable, which is a different thing from being
    closed** (P3-SEC-1, LOW-3). `close_sockets` writes
    `core.socket.kick_failed` through `core.log` before it re-raises, so the
    dropped kick appears in the structured stream an operator actually watches —
    Django's own `django.db.backends.base` line is not our logging and nobody
    greps it. The socket may still be open; what changed is that somebody can
    know, and can go and look.

    **A named nested `def`, and never `functools.partial`.** P3 SEC-R3 proved
    that `robust=True` over a `partial` un-robusts the entire remaining hook
    chain: Django 5.2 reports the swallowed failure with
    ``f"Error calling {func.__qualname__} in on_commit() ..."``
    (`django/db/backends/base/base.py`), and a `functools.partial` has no
    `__qualname__` — so the handler whose whole job is to swallow a failing hook
    raised `AttributeError` itself, uncaught, out of `set_autocommit`, and every
    hook queued behind it never ran. Registering a partial made `robust=True`
    mean its own opposite: the one thing it was chosen to prevent, which is the
    invitation-email scar (W1-9, F3) delivered by the mechanism meant to stop
    it. A1's original registration used `partial`; a nested `def` carries a
    `__qualname__`, so the swallow works and the siblings run, and the two
    starters in `apps/workflows/services.py` already do it this way.
    """

    def kick_on_commit() -> None:
        close_sockets(user_id=user_id, reason=reason)

    transaction.on_commit(kick_on_commit, robust=True)


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
        Membership.objects.filter(tenant=tenant, organization__path__in=sorted(lost))
        .values_list("user_id", flat=True)
        .distinct()
    )


# --- Membership, and the escalation wall -------------------------------------


def _refuse_escalation(
    *,
    actor: Actor,
    tenant: Tenant,
    organization: Organization,
    role: str,
) -> None:
    """**The escalation wall.** Two refusals, and they are different refusals.

    1. **Outside your subtree.** The granter must hold a role on `organization`
       or on one of its ancestors. Holding `owner` of one branch says nothing
       about the branch next door, and a grant that reached sideways would make
       the tree decorative.
    2. **Above your own effective role.** An `admin` may make somebody an
       `admin` or a `member`, never an `owner`. Without this, one admin
       promotes themselves — or a colleague, then asks the colleague — and the
       role system has no ceiling at all.

    **The wall is keyed on the actor's KIND, and that is a re-keying with a
    reason** (ADR core-22, the L1 ruling of 2026-08-26). It used to read
    `granter is None` — and a granter was `actor.user if actor is not None else
    None`, so two very different situations arrived as the same `None`: the
    product acting for itself, and *nobody having been told who was acting*.
    The second is not an altitude, it is a missing argument, and a wall whose
    escape hatch is a parameter somebody forgot is a wall with a hole in the
    shape of forgetfulness.

    So `actor` is required at every call site now, and `kind == "system"` is
    the declared way past: the tenant's own creation, an invitation accepted at
    signup, a management command, a schedule. **A system actor is a named
    audited altitude, never an exemption** — the `AuditEntry` for that grant
    records `actor_kind=system` with no person, which is ADR core-22's third
    actor semantic said out loud, and a reviewer meeting one can tell it from a
    human grant at a glance. An exemption leaves no trace; an altitude does.

    A `human` or `agent` actor carrying no user is refused rather than waved
    through: nobody is authenticated, so there is no ceiling to measure and no
    reason to believe the grant is legitimate.
    """
    if actor.kind == "system":
        return
    granter = actor.user
    if granter is None:
        raise Forbidden(
            "This request resolved nobody, so there is no role of your own to grant "
            "beneath. Sign in, or act as the system."
        )
    held = effective_role(granter, tenant, organization)
    if held is None:
        raise Forbidden(
            "You hold no role over that part of the organization, so you may not grant one there."
        )
    if rank(role) > rank(held):
        raise Forbidden(
            f"You may not grant {role!r}: your own effective role there is {held!r}, and "
            "nobody grants above themselves."
        )


def _refuse_acting_above_yourself(
    *,
    actor: Actor,
    tenant: Tenant,
    membership: Membership,
    verb: str,
) -> None:
    """**The other half of the wall: the role being acted _on_.**

    `_refuse_escalation` bounds the role being *granted*. That is the whole
    ceiling only while the only way to change what somebody may do is to hand
    them something; it is not. An `admin` who may not *grant* `owner` could
    take the owner's hat away instead — remove the row, or set its role to
    `member` — and arrive at the same power by subtraction. So the row's
    **current** role is measured against the actor's own effective role at the
    node the membership sits on, and anything above them is refused.

    **Two roads reach it and this is the only guard on either.**
    `revoke_membership` calls it before a delete (SEC-1's MED-1) and `set_role`
    before a role change, so the predicate, the sentence and the comparison are
    one thing rather than two that agree today. The demotion road used to
    answer `200` before this guard existed.

    **Parameterised by the verb, where `_refuse_removing_the_last_owner`
    deliberately is not.** That guard's sentence is a fact about the tenant and
    a remedy, true whichever road asked. This one's sentence names the act it
    refused, and telling somebody they may not *remove* a row when they asked
    to demote it would be a refusal that describes something they never did.
    One template, one word substituted — and the tests string-compare the two
    sentences with the substitution applied, so they cannot drift into two
    grammars.

    **Keyed on `actor.kind`, exactly as `_refuse_escalation` is** and for the
    identical reason (ADR core-22, L1): `system` is the product acting for
    itself and is a named audited altitude the row records, where the old
    `acting_user is None` could not tell that apart from nobody having said who
    was acting.

    **Call it after `_refuse_escalation`, never before.** That wall refuses an
    actor who holds *no* role at the node with its own sentence; without it
    first, this one would quote an effective role of `None` at somebody who is
    simply standing outside the subtree.
    """
    if actor.kind == "system":
        return
    acting_user = actor.user
    if acting_user is None:
        raise Forbidden(
            f"This request resolved nobody, so there is no role of your own to {verb} "
            "beneath. Sign in, or act as the system."
        )
    held = effective_role(acting_user, tenant, membership.organization)
    if rank(membership.role) > rank(held):
        raise Forbidden(
            f"You may not {verb} a {membership.role!r}: your own effective role there is "
            f"{held!r}, and nobody {verb}s above themselves."
        )


@service
def add_membership(
    *,
    user: AbstractBaseUser,
    tenant: Tenant,
    organization: Organization | None = None,
    is_default: bool = False,
    role: str | None = None,
    actor: Actor,
) -> Membership:
    """Put a user somewhere in a tenant's tree.

    **`organization` omitted is the ACTING HAT, and never the root** (ADR
    core-20, the placement law; the owner's ruling of 2026-08-24). A grant comes
    from where you sent it: somebody acting under a branch's hat who names no
    node meant that branch, and landing them at the root instead is a grant
    reaching further than the context it was sent from. It used to default to
    the root unconditionally, and both halves of that were wrong at once — an owner
    acting in a branch silently placed people above it, and a branch admin, who
    holds nothing at the root, was refused by the escalation wall for a node
    they never named.

    **With no actor there is no hat, and the root is right.** `create_tenant`,
    the seed command and `accept_invitation` all reach here without one; a
    tenant's first membership is the whole tenant by definition.

    Naming a node explicitly still works and is what a network does: a
    membership at a sub-seller sees that sub-seller and everything under it, and
    nothing else. The door resolves the id through the hat's own subtree, so a
    node outside it is `not_found` rather than a placement.

    At most one membership per user is the default; asking for a second default
    moves the flag rather than tripping the constraint, because "which tenant do
    I land in" is a setting, not an error.

    **The first membership of a tenant is its owner.** Somebody has to be able
    to add the second one, and defaulting the first to `member` produces a
    tenant that nobody — including the person who just created it — can
    administer. An explicit `role` always wins.

    `actor` is the person doing the granting, when there is one, and passing it
    is what turns the escalation wall on (`_refuse_escalation`). Every door
    passes it.
    """
    # authz: the escalation wall IS the authorization here, and it is a
    # different shape from `authz.require`. `require` asks "may this actor act
    # on this object"; a grant also has a *role being granted*, and the refusal
    # is about the relationship between that role and the granter's own
    # effective one. There is no object a policy predicate could look at that
    # would carry it, so `_refuse_escalation` below is the guard — enforced on
    # every path, tested in both directions.
    where = organization if organization is not None else _landing_node(tenant=tenant, actor=actor)
    if where.tenant_id != tenant.pk:
        raise Invalid({"organization": ["That organization belongs to another tenant."]})
    if is_default:
        Membership.objects.filter(user_id=user.pk, is_default=True).update(is_default=False)
    if role is None:
        first = not Membership.objects.filter(tenant=tenant).exists()
        role = Membership.Role.OWNER if first else Membership.Role.MEMBER
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=where,
        role=role,
    )
    membership = Membership(
        user_id=user.pk,
        tenant=tenant,
        organization=where,
        is_default=is_default,
        role=role,
    )
    with as_invalid():
        membership.full_clean()
    membership.save()
    return membership


@service
def set_role(
    *,
    tenant: Tenant,
    membership: Membership,
    role: str,
    actor: Actor,
) -> Membership:
    """Change what somebody may do inside one part of a tenant.

    Audited like every other write, and that is the point: "who made them an
    admin, and when" is the question an incident review opens with. The
    escalation wall applies here exactly as it does to a fresh grant — promoting
    an existing member past your own ceiling is the same act with an extra step.

    **And the ceiling on the role being changed, shared with
    `revoke_membership`.** The wall above bounds the role being *granted*, which
    is only half a ceiling: an `admin` who may not grant `owner` could call this
    with `role="member"` on an `owner` membership instead and take the hat away
    by subtraction — no promotion anywhere, the same result. `revoke_membership`
    has refused that shape since SEC-1's MED-1 ("nobody removes above
    themselves"); this refused nothing until this predicate was shared with it. One predicate —
    `_refuse_acting_above_yourself` — one sentence template, one word of it
    changed, because a refusal that said *remove* to somebody who asked to
    demote would describe an act they never attempted.

    **Three walls, in this order, and the order is the point.** The escalation
    wall first: it is the one that refuses an actor holding nothing at this node
    at all, and it is what lets the ceiling quote a role rather than `None`.
    Then the ceiling. Then the ownerless floor, last of the three, because
    telling an `admin` that this is the tenant's last owner would answer a
    question about the owner census for somebody who may not touch the row.
    Planted both ways in `core/tests/test_role_ceiling.py`.

    **And the ownerless floor, shared with `revoke_membership`.** A demotion is
    the other road to a tenant nobody can administer: set the last `owner` to
    `member` and the row is still there, still readable, and there is no longer
    anybody who may invite, promote or close anything. `revoke_membership` has
    refused that state since SEC-1's MED-1; this refused nothing until this guard
    was added here too, and got a `200` instead. One predicate, one sentence —
    `_refuse_removing_the_last_owner` below, called from both roads, because two
    guards written separately drift and a client that branches on the words
    would get a different answer depending on which road it took.
    """
    # authz: the escalation wall, exactly as in `add_membership` — a promotion
    # is a grant with an extra step, and the rule is about the role being
    # granted rather than about an object a policy could inspect.
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=membership.organization,
        role=role,
    )
    # And the other half of the wall, `revoke_membership`'s own: the role this
    # membership *holds*. Second, never first — `_refuse_escalation` above is
    # what refuses an actor holding nothing here, with the sentence that says
    # so, and this one's sentence quotes the role it found.
    _refuse_acting_above_yourself(
        actor=actor,
        tenant=tenant,
        membership=membership,
        verb="demote",
    )
    # A role this product does not know is refused as `invalid` by `full_clean`
    # below, and saying `conflict` first would teach a caller that its typo was
    # a state problem — `MembershipRolePatch.role` is a plain `str`, so the
    # nonsense value really does reach here. Checked against the declared
    # values rather than by rank: `rank()` answers 0 for anything it does not
    # know, which is indistinguishable from a demotion.
    if role in Membership.Role.values and role != Membership.Role.OWNER:
        _refuse_removing_the_last_owner(tenant=tenant, membership=membership)
    membership.role = role
    with as_invalid():
        membership.full_clean()
    membership.save(update_fields=["role", "updated_at"])
    return membership


def _refuse_removing_the_last_owner(*, tenant: Tenant, membership: Membership) -> None:
    """A tenant with no owner is a tenant nobody can administer.

    The same invariant `apps.accounts.services.tenants_this_user_alone_owns`
    protects on the erasure path, enforced here because removal is the other
    way to reach the state: no one left who can invite a member, change a role,
    or close it — and nobody notices until they need to do one of those things.

    **Two roads reach it and this is the only guard on either.** `set_role`
    calls it before a demotion and `revoke_membership` before a delete, so the
    code, the sentence and the count are one thing rather than two that agree
    today. The sentence reads for both: a demotion *is* the last owner being
    removed — from ownership rather than from the tenant — and the remedy is
    the same either way, which is why it is not parameterised by the verb.
    The demotion road used to answer `200` before this guard covered it.

    Takes the membership *before* anything mutates it, because it reads
    `membership.role` to decide whether the row under the caller's hand is an
    owner at all. A caller that assigned the new role first would be asking
    this about a row that no longer exists.
    """
    if membership.role != Membership.Role.OWNER:
        return
    others = Membership.objects.filter(tenant=tenant, role=Membership.Role.OWNER).exclude(
        pk=membership.pk
    )
    if not others.exists():
        raise Conflict(
            "That is the tenant's last owner; promote somebody else before removing them."
        )


@dataclass(frozen=True)
class RevokedMembership:
    """What a withdrawn membership WAS, after the row is gone.

    **A death is exactly what an audit trail exists for** (ADR core-22, the L5
    ruling of 2026-08-26), and `revoke_membership` used to return `None` — so
    the row recording the most consequential act in the hierarchy named no
    object, and the one question a dispute turns on ("whose hat did you take,
    and which one was it") was answerable only from a redacted `input`.

    The pk of a deleted row is still the honest answer to "what did this act on":
    nothing points at it any more, and that is the fact. So `audit_object`
    declares the pair by hand — `core.service._object_of` cannot read it off the
    instance, because there is no instance left to read.

    The person, the branch and the role travel too, because a reader six weeks
    later is asking about a person and a place, not about a primary key.
    """

    membership_id: UUID
    user_id: UUID
    organization_id: UUID
    role: str

    @property
    def audit_object(self) -> tuple[str, UUID]:
        """The `(label, pk)` pair the seam reads. The label is `Membership`'s own."""
        return (Membership._meta.label, self.membership_id)


@service
def revoke_membership(
    *,
    tenant: Tenant,
    membership: Membership,
    actor: Actor,
) -> RevokedMembership:
    """Take somebody's place in a tenant away. **The hat withdrawal.**

    SEC-1's MED-1 found this path missing entirely: nothing outside tests and
    migrations deleted a `Membership`, so the only way to withdraw a person from
    a branch was a raw ORM delete — which is a write outside a service (rule 10),
    skips the escalation wall's mirror image, writes no audit row, and, the
    finding's own point, never reached the person's open sockets.

    **Authorization is ancestor-admin of the node the membership sits on**, the
    same question `add_membership`'s wall asks from the other side and the same
    predicate `organization.create/rename/move` use: taking a hat away is as
    much an administrative act over that branch as handing one out.

    **And a ceiling, mirroring `_refuse_escalation`.** An `admin` may remove an
    `admin` or a `member`, never an `owner`. Without it the wall is decorative:
    an admin who may not *grant* `owner` could simply remove the owner instead,
    which is the same power arriving by subtraction. It lives in
    `_refuse_acting_above_yourself` and `set_role` calls it too: the
    demotion road is the same subtraction without the row disappearing, and it
    had no ceiling at all until that predicate was shared.

    **Three refusals, in this order, and the order is the point.**
    `may_be_named` first: a membership in a branch the actor holds no hat over
    is refused `NotFound`, never `Forbidden`, because a refusal that told
    not-there from not-yours apart would confirm that this person holds a
    membership on that branch — rule 26's reachability question, which neither
    tenancy nor the policy asks (the row *is* in the tenant, and the policy is
    about the verb). Then `require`, which is the verb question over a branch
    the actor can already see, so `Forbidden` there reveals nothing. Then the
    ceiling.

    The sockets close on commit (`close_sockets_on_commit`): once the row is
    gone `core.middleware.resolve_org` resolves no hat for this person in this
    tenant, so every org group their connection joined at handshake time is a
    branch they may no longer read — and the connection would have kept
    delivering that branch's full `Out` bodies for its whole life. This is the
    first of MED-1's two real halves.
    """
    if not may_be_named(actor, membership):
        raise NotFound()
    require(actor, "membership.revoke", membership.organization)
    _refuse_acting_above_yourself(actor=actor, tenant=tenant, membership=membership, verb="remove")
    _refuse_removing_the_last_owner(tenant=tenant, membership=membership)
    user_id = membership.user_id
    # Read BEFORE the delete: `membership.pk` is set to None by Django's own
    # `Model.delete()`, so a result assembled afterwards would name nothing —
    # which is the defect this return value closes, arriving by a different road.
    died = RevokedMembership(
        membership_id=membership.pk,
        user_id=user_id,
        organization_id=membership.organization_id,
        role=membership.role,
    )
    membership.delete()
    close_sockets_on_commit(user_id=user_id, reason=KICK_MEMBERSHIP_REVOKED)
    return died


# --- Tenant configuration ----------------------------------------------------


@service
def update_tenant_settings(
    *,
    tenant: Tenant,
    values: dict[str, Any] | None = None,
    timezone: str | None = None,
    locale: str | None = None,
    actor: Actor,
) -> Tenant:
    """Change a tenant's own configuration.

    `values` is **merged** at the top level rather than replacing the column: a
    caller that meant to set one key and sent one key would otherwise silently
    delete every other. A key is removed by sending it as `None`.

    The timezone is validated against the real zone database here, because a
    typo'd `"Europe/Lisbn"` stored happily becomes a `ZoneInfoNotFoundError` at
    render time, in whichever request first tries to show somebody a date.

    **`actor` arrived with the door**: nothing outside the tree could
    reach this service before, so authorizing nobody was not reachable either.
    Measured at the tenant's **root**, not the acting hat — configuring the
    tenant is configuring the whole tenant, and a branch admin administers a
    branch. A `system` actor is the product acting for itself — the same
    reading `_refuse_escalation` gives, keyed on the KIND since ADR core-22's
    L1 ruling rather than on an actor that happened to be missing.
    """
    if actor.kind != "system":
        require(actor, "tenant.configure", root_organization(tenant=tenant))
    changed: list[str] = []
    if values is not None:
        merged = dict(tenant.settings or {})
        for key, value in values.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        tenant.settings = merged
        changed.append("settings")
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise Invalid({"timezone": [f"{timezone!r} is not a known time zone."]}) from exc
        tenant.timezone = timezone
        changed.append("timezone")
    if locale is not None:
        tenant.locale = locale
        changed.append("locale")
    if not changed:
        return tenant
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=[*changed, "updated_at"])
    return tenant


@service
def set_flag(*, tenant: Tenant, name: str, enabled: bool | None, actor: Actor) -> Tenant:
    """Turn a feature on or off for one tenant.

    `enabled=None` clears the tenant's opinion so it inherits the
    deployment-wide default again — which is what finishing a rollout looks
    like, and is a different thing from turning the feature off.

    The `actor` is handed straight to `update_tenant_settings`, which is where
    the authorization lives: a flag IS a settings key, and two checks over one
    write would be two places to get it wrong. Note that this therefore writes
    **two** audit rows, `core.set_flag` and `core.update_tenant_settings`, and
    that is the honest record — one call, two writes, both by the same actor.
    """
    flags = dict((tenant.settings or {}).get(FLAGS_KEY, {}))
    if enabled is None:
        flags.pop(name, None)
    else:
        flags[name] = bool(enabled)
    # authz: delegated, deliberately. A flag IS a settings key, and the write
    # below is the one that lands it — `update_tenant_settings` asks
    # `tenant.configure` against the tenant's root. Asking the same question
    # twice over one write would be two places to get it wrong, and the second
    # one would be the one nobody updates.
    return update_tenant_settings(tenant=tenant, values={FLAGS_KEY: flags}, actor=actor)


# --- The first tenant --------------------------------------------------------


@service
# rule-13: this service has no `tenant=` to take, and cannot. It is the one
# write in the product that PRODUCES the tenant its own audit row is about — at
# the moment it is called there are none — so the wrapper, which reads a row's
# tenant from the call, has nothing to read. The row is written explicitly
# below, onto the tenant this creates (ADR core-17, ADO-5); auditing into the
# platform population instead was considered and rejected, because the row is
# about a tenant that now exists.
def create_first_tenant(*, user: AbstractBaseUser, name: str, slug: str) -> Tenant:
    """Make the FIRST tenant of an installation, and hand it to one owner.

    ADR core-17. Before this, a real environment's first tenant was made by
    hand-driving services in a shell — `seed --force` is dev data by contract
    and refuses outside DEBUG — so the one step every deployment must take was
    the one step nothing wrote down.

    Three rows, one transaction: the tenant, its root organization, and one
    OWNER membership for `user`. All three come out of `create_tenant`, which
    already makes the root and already makes the first membership an owner
    (somebody has to be able to add the second one).

    **It refuses if ANY tenant exists**, and that is the whole safety of it. A
    command that quietly made a second tenant on a live box would be a footgun
    with a friendly name: "bootstrap" reads like "set this up", and an operator
    running it twice must get a refusal rather than a surprise.

    **The audit row rides the tenant this creates** — the birth certificate
    (ADO-5). It is written here rather than by the `@service` wrapper because
    the wrapper reads the row's tenant from the call, and this call has none to
    give: the tenant is the output. Auditing into the platform population
    instead was rejected, because the row is about a tenant that now exists.
    `create_tenant` stays unaudited, exactly as it was.

    **The name.** `manage.py bootstrap_tenant` is the ratified command name and
    it has not moved; this function is `create_first_tenant` because house rule
    16 reads a service's first word against a declared lexicon and `bootstrap`
    is not in it. Adding it would mean changing `quality/rules.yaml`, which is
    not authorised here, so the lexicon won and the command kept its name.

    `user` is resolved by the caller, as every door resolves its rows. This
    service does not create one: `accounts.create_user` is the one write path
    onto the user table and `core` may not import `accounts` (the fixed layer
    direction). On a real environment the person is already there — they signed
    in through the workforce IdP, which is what made the row — and naming
    somebody who is not is a refusal at the door, not a silent second user.
    """
    if Tenant.objects.exists():
        raise Conflict(
            "This installation already has a tenant, so there is no first one to make. "
            "Add further tenants through the product rather than through the shell."
        )
    tenant = create_tenant(name=name, slug=slug, owner=user, actor=system_actor())
    write_audit(
        action="core.create_first_tenant",
        tenant=tenant,
        actor=None,
        payload={"user_id": str(user.pk), "slug": tenant.slug},
        outcome="ok",
        result=tenant,
    )
    return tenant


# --- Tenant lifecycle --------------------------------------------------------


# door: an operator act on somebody else's tenant, not a tenant admin's own — the
# caller is the platform, and a door here would have to answer "which tenant" from
# outside every scope this product has. `manage.py` and the admin are its INTENDED
# reach and NEITHER EXISTS YET: `bootstrap_tenant` built the first-tenant command
# and never this trio, so the gap remains open. It closes when the doors named
# above get built: the first operator suspension needed in anger, or the next
# change that touches the operator surface, whichever comes first. Rule 42 counts
# this valve and prints it — it counts the MECHANISM, not a citation, which is
# exactly why a stale citation here would be invisible to the gate and had to be
# read by a person.
@service
def suspend_tenant(*, tenant: Tenant, reason: str = "", actor: Actor) -> Tenant:
    """Stop a tenant working, reversibly. Nothing is deleted.

    Suspension is what a missed invoice or an abuse report leads to, and it has
    to be undoable in one call — so it is a status and a timestamp, never a
    cascade of deletes. Every row stays exactly where it is.


    # authz: an operator act, and there is deliberately no predicate for it — a
    # tenant admin must never be able to suspend or close their own workspace to
    # escape a bill, and no role inside a tenant is above the platform. What
    # bounds it is the door, and the door valve above names them: `manage.py`,
    # whose row is `kind=system` (ADR core-22's absence iv), and the admin, whose
    # row carries the staff member because `ServiceModelAdmin.acting` already
    # resolves a request-shaped actor and `ContextMiddleware` already stamps
    # `door="admin"`. The actor is kept for the audit row — this is the single
    # most consequential thing anybody can do to a tenant, and until AUDIT-2c
    # the row said the system did it.
    """
    tenant.status = Tenant.Status.SUSPENDED
    tenant.suspended_at = now()
    if reason:
        tenant.settings = {**(tenant.settings or {}), "suspension_reason": reason}
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=["status", "suspended_at", "settings", "updated_at"])
    return tenant


# door: an operator act on somebody else's tenant, not a tenant admin's own — the
# caller is the platform, and a door here would have to answer "which tenant" from
# outside every scope this product has. `manage.py` and the admin are its INTENDED
# reach and NEITHER EXISTS YET: `bootstrap_tenant` built the first-tenant command
# and never this trio, so the gap remains open. It closes when the doors named
# above get built: the first operator suspension needed in anger, or the next
# change that touches the operator surface, whichever comes first. Rule 42 counts
# this valve and prints it — it counts the MECHANISM, not a citation, which is
# exactly why a stale citation here would be invisible to the gate and had to be
# read by a person.
@service
def resume_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    """Undo a suspension.

    # authz: an operator act, and there is deliberately no predicate for it — a
    # tenant admin must never be able to suspend or close their own workspace to
    # escape a bill, and no role inside a tenant is above the platform. What
    # bounds it is the door, and the door valve above names them: `manage.py`,
    # whose row is `kind=system` (ADR core-22's absence iv), and the admin, whose
    # row carries the staff member because `ServiceModelAdmin.acting` already
    # resolves a request-shaped actor and `ContextMiddleware` already stamps
    # `door="admin"`. The actor is kept for the audit row — this is the single
    # most consequential thing anybody can do to a tenant, and until AUDIT-2c
    # the row said the system did it.
    """
    if tenant.status == Tenant.Status.CLOSED:
        raise Conflict("A closed tenant is not resumed; that is a new decision and a new service.")
    tenant.status = Tenant.Status.ACTIVE
    tenant.suspended_at = None
    remaining = dict(tenant.settings or {})
    remaining.pop("suspension_reason", None)
    tenant.settings = remaining
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=["status", "suspended_at", "settings", "updated_at"])
    return tenant


# door: an operator act on somebody else's tenant, not a tenant admin's own — the
# caller is the platform, and a door here would have to answer "which tenant" from
# outside every scope this product has. `manage.py` and the admin are its INTENDED
# reach and NEITHER EXISTS YET: `bootstrap_tenant` built the first-tenant command
# and never this trio, so the gap remains open. It closes when the doors named
# above get built: the first operator suspension needed in anger, or the next
# change that touches the operator surface, whichever comes first. Rule 42 counts
# this valve and prints it — it counts the MECHANISM, not a citation, which is
# exactly why a stale citation here would be invisible to the gate and had to be
# read by a person.
@service
def close_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    """End a tenant. Terminal, and still not a delete.

    The rows stay. An audit trail, an invoice history and a retention obligation
    all outlive the customer relationship, and erasure is a separate operation
    with its own rules. Closing is the *business* fact; deleting is a different
    one, and conflating them loses the first.


    # authz: an operator act, and there is deliberately no predicate for it — a
    # tenant admin must never be able to suspend or close their own workspace to
    # escape a bill, and no role inside a tenant is above the platform. What
    # bounds it is the door, and the door valve above names them: `manage.py`,
    # whose row is `kind=system` (ADR core-22's absence iv), and the admin, whose
    # row carries the staff member because `ServiceModelAdmin.acting` already
    # resolves a request-shaped actor and `ContextMiddleware` already stamps
    # `door="admin"`. The actor is kept for the audit row — this is the single
    # most consequential thing anybody can do to a tenant, and until AUDIT-2c
    # the row said the system did it.
    """
    tenant.status = Tenant.Status.CLOSED
    tenant.closed_at = now()
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=["status", "closed_at", "updated_at"])
    return tenant


# --- Invitations -------------------------------------------------------------


def hash_invitation_token(plaintext: str) -> str:
    """The stored form of an invitation token. Not a service: a pure function."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def pending_invitations_for(*, email: str) -> list[Invitation]:
    """Every live invitation for an address, across tenants. A read, not a write.

    Deliberately not `for_tenant`, and this is the one query in the tree that
    legitimately crosses tenants: the person signing up has no tenant yet —
    having one is what the invitation is *for*. It is narrowed by the email
    address, which is the identity being established, and it is called from
    exactly one place: the signup adapter.
    """
    return list(
        Invitation.objects.filter(
            email=email.strip().lower(),
            status=Invitation.Status.PENDING,
            expires_at__gt=now(),
        ).select_related("tenant")
    )


# Where an invited person is sent to get their account. **The login page, not a
# signup page** (ADR ident-4): the identity platform hosts every
# interactive authentication, so signing up and signing in are one act — they
# follow this link, sign in there, and `accounts.adapter` turns the invitation
# they were sent into the membership it names.
#
# `account_signup` used to be here and no longer exists as a URL at all
# (`SOCIALACCOUNT_ONLY` removes it), so this is not a preference: reversing the
# old name raises. The mail context key keeps its own name — it still says what
# the link is *for*, and two templates and their tests read it.
INVITE_LANDING_URL = "account_login"

# The run that makes the invited person real, named as a string because `core`
# may not import the app that defines it (`apps.accounts.workflows`) — the same
# inversion `MOVE_ORGANIZATION_WORKFLOW` above and `core.mail`'s
# `SEND_EMAIL_WORKFLOW` are, and it arrives the same way, through `core.bridge`.
#
# It replaces the bare `core.mail.send_mail` this service used to call, and the
# email still goes out through exactly that mailer: the run's second activity is
# `apps.workflows.activities.send_email`, which is the activity `send_mail`
# starts. What changed is that the message now waits for the link.
PROVISION_INVITED_PERSON_WORKFLOW = "ProvisionInvitedPersonWorkflow"


# --- `invite_member`, and what happens after the row ---------------------------
#
# Out here rather than in the docstring for the reason `redact_invitations`
# gives at its own block: the docstring is inside the function and
# `service_function_length` counts it (quality/budgets.yaml). None of this is
# about the arguments, so none of it is what a caller reads first.
#
# **The person is provisioned, not just emailed** (ADR accounts-1).
# The row used to be written and a message sent pointing at a login page with no
# form, on a deployment with no door that creates a person: the invitation was
# actionable by a script and a dead end for the human it was addressed to. The
# commit now starts `ProvisionInvitedPersonWorkflow`, which makes them a
# credential-less account in the identity platform, mints the code that lets them
# set their own password, and only then sends the message — through the same
# `core.mail`-shaped payload and the same `send_email` activity as before, so
# rule 25's one sender is unchanged.
#
# **Started, not done, and deferred to commit.** The visibility row is written
# inside the service's transaction and the Temporal call is registered on
# `transaction.on_commit`, so an invitation that rolls back provisions nobody and
# emails nobody, and an identity platform that is down costs a retry rather than
# the write. The workflow id is keyed on the invitation's primary key, which is
# what makes a retried service start one run and not two — and, because "invite
# them again" creates a *new* invitation row, it is also what lets a resend
# actually resend.
#
# **The message still carries none of OUR credentials**: the `plaintext`
# invitation token goes to the caller and never into a payload, because
# `accounts.adapter` joins the membership from the address at sign-in and a
# bearer token of ours in a workflow argument would sit in Temporal's history for
# as long as retention says. What the run *does* put in history is Zitadel's
# invite code, inside the link — a different kind of thing, and ADR accounts-1 is
# where that difference is argued rather than assumed: it is single-use,
# short-lived, superseded by re-issuing, and it opens exactly one screen, the one
# where a person with no password chooses one. It confers no membership; the row
# still does.


@service
def invite_member(
    *,
    tenant: Tenant,
    email: str,
    role: str = Membership.Role.MEMBER,
    organization: Organization | None = None,
    invited_by: AbstractBaseUser | None = None,
    expires_in_days: int = INVITATION_DAYS,
    actor: Actor,
) -> tuple[Invitation, str]:
    """Offer somebody a place in a tenant. Returns the row and the token, once.

    The token is returned rather than stored, exactly as an API token is: what
    goes in the email is a bearer credential, and a leaked database should not
    hand over every outstanding invitation. Losing it means reissuing.

    **The invitation records where it was sent from** (ADR core-20, the
    placement law). `organization` omitted is the ACTING HAT and never the
    tenant's root: an offer made from a branch is an offer of a place in that
    branch. That node is written on the row, and it is where every authority
    question about this offer is asked — may you invite here at all, is the role
    you named within your own ceiling here, which standing offer does this
    supersede, and where does the membership land when it is accepted.

    A pending invitation for the same address **at the same node** is superseded
    rather than refused — "invite them again" is what somebody clicks when the
    first email went to spam, and answering that with a constraint error is a
    support ticket. Superseding tenant-wide, which is what this did until the
    placement law, let one branch silently withdraw another branch's standing
    offer to the same person.

    The person is provisioned rather than merely emailed, and the run that does
    it starts on commit — see the block above this function for both, and for
    why the message carries none of our own credentials.
    """
    # The escalation wall applies to an invitation exactly as it applies to a
    # grant, because that is what an invitation is: a grant with a delay. An
    # admin who could invite an owner would be an admin who becomes an owner as
    # soon as they use a second email address.
    #
    # BOTH QUESTIONS ARE ASKED AT THE LANDING NODE (ADR core-20). They were
    # asked at the tenant's ROOT before, and that was wrong in two
    # directions at once: it refused a branch admin for a node they never named,
    # and it let everybody else place an invitee above the hat they were acting
    # under. Two questions, and the wall below only ever asked one of them: "may
    # you grant THIS ROLE" is a ceiling, and it lets a member invite a member.
    # `require` asks whether you may invite anybody at all.
    where = organization if organization is not None else _landing_node(tenant=tenant, actor=actor)
    if where.tenant_id != tenant.pk:
        raise Invalid({"organization": ["That organization belongs to another tenant."]})
    # `system` is the declared altitude, not an actor nobody supplied (L1).
    if actor.kind != "system":
        require(actor, "invitation.create", where)
    # The wall measures the ACTOR, not `invited_by` (ADR core-22, L1). Both
    # doors pass `invited_by=actor.user`, so they were the same person all
    # along; keying on the actor is what lets `kind == "system"` be the one
    # declared way past, and `invited_by` goes back to being what it is — the
    # column this invitation records.
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=where,
        role=role,
    )
    address = email.strip().lower()
    # Superseded AT THIS NODE, never tenant-wide: two branches may each have a
    # live offer out to one person, because they are offers of two places.
    #
    # BOTH NARROWINGS, and neither is redundant. `visible_to(where)` is house
    # rule 24's seam — the caller cannot withdraw an offer standing outside
    # their own reach, whatever else this filter says — and `organization=where`
    # is the exact node, because `visible_to` is a SUBTREE read and superseding
    # a subtree would let a re-issue at a parent silently withdraw a child
    # branch's standing offer, which is the same "acting outside your context"
    # this guard closes at the other end.
    Invitation.objects.for_tenant(tenant).visible_to(where).filter(
        organization=where, email=address, status=Invitation.Status.PENDING
    ).update(status=Invitation.Status.REVOKED, updated_at=now())

    plaintext = secrets.token_urlsafe(INVITATION_TOKEN_BYTES)
    invitation = Invitation(
        tenant=tenant,
        organization=where,
        email=address,
        role=role,
        token_hash=hash_invitation_token(plaintext),
        expires_at=in_days(expires_in_days),
        invited_by_id=invited_by.pk if invited_by is not None else None,
    )
    with as_invalid():
        invitation.full_clean()
    invitation.save()

    _provision_invited_person(tenant=tenant, invitation=invitation, invited_by=invited_by)
    return invitation, plaintext


def _provision_invited_person(
    *,
    tenant: Tenant,
    invitation: Invitation,
    invited_by: AbstractBaseUser | None,
) -> None:
    """Ask for this invitation's person to be made real, and mailed a live link.

    **Not a service and deliberately not one**: it writes nothing of ours, it is
    private to this module, and it always runs inside the transaction of the
    `@service` that called it — the same shape as `accounts.services`'
    `_start_identity_sync`, for the same reason. It is a function rather than
    six more lines inside `invite_member` because the workflow's name, its
    argument shape and the four segments of its id are one contract, and a
    contract is easier to read when it is not wrapped in an escalation check.

    **The start goes through `core.bridge`, not through an import.**
    `apps.accounts` sits above `core`, so naming its workflow module here would
    be the upward import the layer contract exists to refuse.
    """
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    build_id = bridge.get(bridge.WORKFLOW_ID)
    start(
        workflow=PROVISION_INVITED_PERSON_WORKFLOW,
        arg={
            "invitation_id": str(invitation.pk),
            "email": invitation.email,
            # `message_for` is `core.mail`'s own function, so the shape that
            # crosses the boundary has one author and one test — the run's
            # second activity is the very `send_email` this mailer has always
            # started, and rule 25's allow-listed path is the path the message
            # still travels.
            "message": mail.message_for(
                to=[invitation.email],
                subject=f"You have been invited to {tenant.name}",
                template="invitation",
                context={
                    "tenant_name": tenant.name,
                    "email": invitation.email,
                    "role": Membership.Role(invitation.role).label,
                    "invited_by": (
                        getattr(invited_by, "email", "") if invited_by is not None else ""
                    ),
                    "sign_in_url": f"{settings.PUBLIC_BASE_URL}{reverse(INVITE_LANDING_URL)}",
                    # Rendered here rather than in the template: the template is
                    # replayed by a worker with no request and no tenant timezone, and
                    # a date that formats differently on a retry is a message that
                    # differs from the one the test asserted on.
                    "expires_on": invitation.expires_at.date().isoformat(),
                },
            ),
        },
        tenant=tenant,
        user=invited_by,
        # House rule 18, and the reason this service can be retried: the key is
        # the invitation's primary key, so a retried `invite_member` starts one
        # run and not two — and "invite them again", which makes a NEW row,
        # genuinely re-sends.
        id=build_id(tenant=tenant, app="accounts", noun="invite", key=str(invitation.pk)),
    )


@service
def accept_invitation(
    *,
    tenant: Tenant,
    # reach: the person accepting holds no membership yet — that is what the
    # invitation is FOR — so there is no hat `may_be_named` could measure this
    # row against, and asking would fail closed on every legitimate acceptance.
    # What names the row is the TOKEN: the caller proves reach by holding a
    # single-use secret whose hash is on the row, which is a stronger claim than
    # a subtree read, and the door looks it up by that hash and nothing else.
    # The placement is not the accepter's to choose either — it was decided by
    # whoever invited them, bounded by what THEY could reach (ADR core-20).
    invitation: Invitation,
    user: AbstractBaseUser,
    actor: Actor,
) -> Membership:
    """Turn a pending invitation into a membership.

    **`actor` is required, and it is the invitee** (ADR core-22, the L2 ruling
    of 2026-08-26). Until it existed this row recorded `kind=system` with no
    person — and for an act a person unambiguously performed that is not an
    absence, it is a FALSE STATEMENT: somebody clicked a link in an email and
    the trail said the product did it to itself. The REST door passes
    `actor_from_request(request)`; the during-signup path in
    `accounts.adapter` builds `actor_for(user=<the account just created>,
    kind="human")`, because at that instant there is a person and no request.

    # authz: the TOKEN is the authorization, and it is a stronger claim than
    # any predicate could make here — the caller proved reach by holding a
    # single-use secret whose hash is on the row, and the doors look the row up
    # by that hash and nothing else. A `require` would have to ask a question
    # about a membership the accepter does not have yet, which is what the
    # invitation is FOR, so it would fail closed on every legitimate
    # acceptance. The actor is kept for the audit row (rule 13's valve shape).

    Called from `accounts.adapter.save_user` at signup — **not from a signal**
    (house rule 4). A `post_save` receiver on `User` would be logic hidden where
    nobody looks for it, and it would fire for every user a test or a management
    command ever created.

    **The third refusal is the one somebody actually hits**: a person
    who is already in this part of the tenant clicking the invitation link
    again. The row `add_membership` would write collides with the unique
    constraint, `full_clean()` turns that into Django's own
    `ValidationError` under the `__all__` key, and the door answered
    **400 `invalid`** with the sentence *"Membership with this User, Tenant and
    Organization already exists."* — three table names, a framework key, and a
    status code saying the request was malformed when it was perfectly
    well-formed and simply already true. It is a `Conflict`, it is said in
    words, and it is checked here rather than caught below because a service
    that knows the answer should not be finding it out from a constraint.
    """
    if not invitation.is_pending:
        raise Conflict("That invitation has already been used or withdrawn.")
    if is_past(invitation.expires_at):
        raise Invalid({"invitation": ["That invitation has expired. Ask for a new one."]})
    # THE NODE THE OFFER NAMED (ADR core-20). An invitation records the hat it
    # was sent from, and the membership lands exactly there — not at the root,
    # which is what this did while the row carried no organization at all. The
    # record is what makes the offer mean something: "a place in this branch" is
    # what the person was offered, and it is what they get.
    where = invitation.organization
    if Membership.objects.filter(user_id=user.pk, tenant=tenant, organization=where).exists():
        raise Conflict(
            f"You are already a member of {tenant.name}, so there is nothing for this "
            "invitation to add. Whoever sent it can already see you on the member list.",
            remedies=(
                Remedy("You are already in — carry on where you left off", "self:membership"),
            ),
        )

    membership = add_membership(
        # The system altitude, named (ADR core-22, L1): nobody is GRANTING here
        # — the placement was decided by whoever invited them, bounded by what
        # THEY could reach, and the accepter cannot grant themselves anything.
        # The wall reads `kind == "system"` and says so on the row; passing the
        # accepter's own actor would ask it to measure a ceiling they do not
        # have and refuse every legitimate acceptance.
        user=user,
        tenant=tenant,
        organization=where,
        is_default=not Membership.objects.filter(user_id=user.pk).exists(),
        role=invitation.role,
        actor=system_actor(tenant=tenant),
    )
    invitation.status = Invitation.Status.ACCEPTED
    invitation.accepted_at = now()
    invitation.save(update_fields=["status", "accepted_at", "updated_at"])
    return membership


@service
def revoke_invitation(*, tenant: Tenant, invitation: Invitation, actor: Actor) -> Invitation:
    """Withdraw an invitation nobody has accepted.

    **`actor` arrived with the door**, for the reason
    `update_tenant_settings` gives at length: this service refused nobody
    because nothing outside the tree could reach it, and a door is what makes
    that reachable.

    **Measured at the node the offer was sent from** (ADR core-20), because that
    is where its membership lands and therefore where the authority to withdraw
    it is held. It was measured at the tenant's root until the placement law,
    which meant the branch admin who issued an offer could not withdraw their
    own — and the door's read is narrowed to the acting hat's subtree, so
    somebody else's branch's invitation is `not_found` here rather than
    `forbidden`.

    It is deliberately **not** a state check as well: revoking an invitation
    that is already revoked is the same sentence said twice, and answering the
    second one with a refusal would make a retry look like a failure.
    """
    # Reachability first, then the verb — `revoke_membership`'s order, for its
    # reason (house rule 26). An invitation standing in a branch this actor
    # holds no hat over is `NotFound` and never `Forbidden`: telling not-there
    # from not-yours apart would confirm that somebody has been invited to that
    # branch, which is exactly what the narrowing exists to keep quiet. The
    # doors already resolve the row through `get_invitation` against the hat's
    # own subtree; this is the belt to that brace, beside the write.
    # Keyed on the KIND since ADR core-22's L1 ruling. A system actor holds no
    # hat, so `may_be_named` fails closed on it by construction — which turned
    # every sweep and every command into a `NotFound` the moment `actor` became
    # required. The altitude is named here instead, and the row records it.
    if actor.kind != "system":
        if not may_be_named(actor, invitation):
            raise NotFound()
        require(actor, "invitation.revoke", invitation.organization)
    invitation.status = Invitation.Status.REVOKED
    invitation.save(update_fields=["status", "updated_at"])
    return invitation


# Where a redacted invitation address goes. `.invalid` is reserved by RFC 2606
# and can never resolve, and the two labels are what Django's `EmailValidator`
# needs — the same constant and the same two reasons as
# `apps.accounts.services.ERASED_EMAIL_DOMAIN`, repeated rather than imported
# because the dependency runs the other way (`core` may not import `accounts`).
# `apps/core/tests/test_redact_invitations.py` pins the pair so the repeat
# cannot drift.
REDACTED_EMAIL_DOMAIN = "erased.invalid"


# --- `redact_invitations`, and the valves it carries ---------------------------
#
# The long-form reasoning lives out here rather than in the docstring because
# the docstring is inside the function and `service_function_length` counts it
# (quality/budgets.yaml). **One of the three valves has come out** — the rule-16
# override — which is what a valve is for: a written-down reason with a
# stated end. The `# door:` one was expected to come out earlier and did not,
# and its own text now says why; what it said before, and what changed under it,
# is kept there rather than deleted.
#
# **The token is left alone deliberately.** `token_hash` is a SHA-256 digest and
# not a recoverable identifier — rule 15 puts `*_hash` outside the
# secret-shaped population for exactly this reason — the row is dead once its
# status is `revoked`, and blanking a `unique=True` column across several rows
# would collide.
#
# **The rule-16 valve is gone, and the name never changed.** It used to ride
# here as a counted override, because `redact` was not in rule 16's
# `service_verbs` and `quality/**` was single-writer territory this change was
# not permitted to touch. A later change added the verb and deleted the override
# in one commit, which
# is the coupling that entry records: the lexicon now holds `redact` with its
# meaning written beside it — an identifier comes OUT of a row that stays, which
# is neither `erase` (the person goes), `purge` (the rows go, on a schedule) nor
# `revoke` (an offer or a credential is withdrawn). The seam seven downstream
# rungs cite kept its name throughout.
#
# **`# reach`, and the honest thing being said here.** The criterion
# expected the valve to be counted in the gate's valve section. It is not:
# `quality/checks.py::service_reach` counts `reach_overrides` only for a
# @service that WRITES an org-scoped row AND takes a parameter ANNOTATED with an
# org-scoped model — BOTH halves, not either. The sentence is written anyway
# because it is true, and
# `test_the_reach_valve_is_written_and_is_not_counted_yet` asserts each half
# separately so a later reader cannot mistake a silent counter for a satisfied
# rule.
#
# ONE OF THE TWO HALVES HAS SINCE MOVED (ADR core-20, INV-1), which is exactly
# what that test was built to notice. `Invitation` is org-scoped now — it
# records the node it was sent from — so this service DOES write org-scoped
# rows. The other half has not moved and is the one that keeps this uncounted:
# it still takes an `email: str`, and a string is not a row `may_be_named` could
# ask about. The day somebody adds an org-scoped parameter here, the valve
# becomes a counted one with no edit to this comment.
#
# door: it IS wired now — `accounts.services.erase_user` calls it as ADR
# ident-5's fourth residue table, and that service is on REST and on MCP — but
# rule 42's census reads the calls made by DOOR MODULES (api/mcp/consumers/
# activities/receivers/commands), one hop, off their own imports. This seam is
# reached from a services.py, which is two hops, so the census cannot see it and
# scores it doorless. The valve therefore stays, and it stays for a DIFFERENT
# reason than the one it was born with: not "doorless for the length of one
# rung" but "reached through another app's service, which rule 42 does not
# walk". Removing it as originally expected makes the gate fire on `core` at
# ratchet 0 — measured, not assumed. Whether
# rule 42 should walk service-to-service calls is a rule question and belongs in
# a quality rung, not in a comment; until then this line is the honest one.
@service
def redact_invitations(
    *,
    # reach: the reference is an EMAIL STRING, not a row — `may_be_named` has no
    # subject to ask about, and the sweep is platform-wide, so no hat could
    # authorize its extent either. Not counted by the gate today; see above.
    email: str,
    actor: Actor,
    tenant: Tenant | None,
) -> Swept:
    """Take a person's address out of every invitation that holds it. **Platform-wide.**

    **It returns a `Swept`, not the rows** (ADR core-22, L6). Handing back the
    rows it had just redacted was a shape with two problems: an erasure sweep
    that returns its victims is an erasure that hands the address's neighbours
    to whoever called it, and a list is not something `core.service._object_of`
    can read, so the audit row for the most privacy-sensitive sweep in the
    product named no population at all. The typed result answers both — the
    label of what was walked, the count of what went, and nothing about who.

    Called by erasure (`accounts.erase_user`, ADR ident-5): the fourth residue
    table, and the one the erasure sweep could not reach on its own. An
    invitation is written by `core` and belongs to `core`, so accounts asking
    for it is a service call and never a write into another app's model (C3,
    house rule 10).

    **Two different things happen and it matters which is which.**

    * Every invitation holding the address — pending, accepted or revoked — has
      the address *redacted*, replaced by `redacted+<uuid7>@erased.invalid`. A
      unique replacement rather than a shared sentinel, for the reason
      `erase_user` gives about `User.email`: a shared value silently groups rows
      that have nothing to do with each other.
    * Only the ones still **pending** are additionally *voided*
      (`Status.REVOKED`), because only a pending invitation is a standing offer
      somebody could still walk through. An accepted invitation is history, and
      history is not withdrawn — the row stays, saying that an offer was made
      and taken, with nobody's address on it.

    **Platform-wide, and that is the point**: nobody knows which tenants hold an
    offer to this address — that is what an invitation to somebody with no
    account IS. `tenant` is therefore an audit-population selector and not a
    filter. Pass the tenant the erasure is being performed in and the row lands
    in that tenant's ledger; pass nothing and it lands in the platform's,
    readable through `AuditEntry.objects.for_platform()`. Exactly `erase_user`'s
    own shape, and exactly ADR core-8's declared null population.

    DOES NOT COVER — declared:

    * **an alias.** The sweep is an exact match on the normalised address, so an
      invitation sent to `jo+work@example.com` survives an erasure of
      `jo@example.com`. Alias-awareness is a per-deployment mail-routing fact,
      not something a query can know; the closed half is the address as it was
      written down.
    * **an invitation held anywhere but this table** — a product that copies the
      address into its own model erases it in its own service.
    * **the person's other rows.** This service is one residue table's answer,
      not erasure; `erase_user` composes it with the rest.
    """
    # authz: nothing an actor could be measured against exists here. A hat is
    # measured on an organization and this sweep spans every tenant on the
    # deployment by construction, so there is no org that could grant it and
    # none that could withhold it. What authorizes the act is the erasure the
    # caller is performing, checked at ITS own door (`accounts.erase_user` ->
    # `policies.themselves_or_administers_the_whole_tenant`); the actor is
    # carried here so the audit row says who asked, not so this function can
    # re-decide. A `require` here would be theatre with a made-up subject.
    address = email.strip().lower()
    if not address:
        return Swept(label=Invitation._meta.label, count=0)

    # rule-8: the platform-wide half of the invitation table, and the sibling of
    # `pending_invitations_for` above — which rules.yaml exempts for this same
    # reason. An offer made to somebody with no account belongs to no tenant the
    # caller knows, so `for_tenant` has nothing to be given: not knowing which
    # tenants hold the address IS the problem this solves. Narrowed by the
    # address being erased, and by nothing else.
    rows = list(Invitation.objects.filter(email=address).order_by("created_at"))

    for invitation in rows:
        fields = ["email", "updated_at"]
        if invitation.status == Invitation.Status.PENDING:
            invitation.status = Invitation.Status.REVOKED
            fields.append("status")
        invitation.email = f"redacted+{uuid7()}@{REDACTED_EMAIL_DOMAIN}"
        invitation.save(update_fields=fields)

    log.info("core.redact_invitations.swept", count=len(rows))
    return Swept(label=Invitation._meta.label, count=len(rows))
