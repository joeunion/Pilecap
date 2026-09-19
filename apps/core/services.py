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
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# `Membership.user` is declared with `settings.AUTH_USER_MODEL` and typed here as
# `AbstractBaseUser`, so that `core` imports no app above it.
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models, transaction
from django.urls import reverse

from apps.core import bridge, events, mail
from apps.core.actor import Actor, system_actor
from apps.core.authz import (
    OWNER_ROLE,
    RESERVED_PERMISSIONS,
    VIRTUAL_KINDS,
    collection,
    default_role_key,
    defaults_for,
    effective_permissions,
    effective_role,
    grantable_permissions,
    may_be_named,
    read_kinds_by_node,
    refusal_sentence,
    require,
    role_declarations,
    vocabulary,
)
from apps.core.exceptions import Conflict, Forbidden, Invalid, NotFound, Remedy, as_invalid
from apps.core.flags import FLAGS_KEY
from apps.core.ids import uuid7
from apps.core.log import get_logger
from apps.core.models import (
    PATH_MAX_DEPTH,
    PATH_MAX_LENGTH,
    PATH_SEPARATOR,
    ROOT_SEGMENT,
    Grant,
    Invitation,
    Membership,
    Organization,
    PathOverflow,
    Role,
    RolePermission,
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
    {
        "name",
        "slug",
        "role",
        "is_default",
        "status",
        "timezone",
        "locale",
        "enabled",
        "reason",
        # The hand-out family's four. A role key, a permission key and an effect
        # are vocabulary, not facts about a person — they are exactly what an
        # incident review reads off the row ("who gave whom what, and when"), and
        # a `[redacted]` in that column would make the audit trail unreadable for
        # the one question it exists to answer.
        "role_key",
        "permission",
        "effect",
        "key",
    }
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

# The ownership verb. It is `core.authz.RESERVED_PERMISSIONS`' one entry today,
# and it is named here rather than derived by `sorted(...)[0]` because "which
# key means owning this tenant" is a fact this module depends on and not a
# position in a dictionary — a second reserved key added tomorrow must not
# silently change what `_refuse_orphaning_the_tenant` counts. The registry is
# still the authority on its SENTENCE and on the refusal of every include row
# and grant that names it; `test_handing_out.py` pins the pair.
OWNERSHIP_PERMISSION = "tenant.own"


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

    **MEMOISED ON THE TENANT INSTANCE, and the memo is HERE rather than at the
    call sites.** This function was on a path nothing bounded: the tenant-wide
    READS in `events` and `connections` asked it on every call, and `emit()` ->
    `enqueue_dispatch` -> `get_event` therefore asked it inside the caller's
    transaction on every emitting write — so the cost was one indexed read per
    EVENT EMITTED, and nothing bounds how many a service emits. Putting the memo
    inside the one function every site already calls is what makes "read once"
    true of the sites that exist today and of the one written tomorrow, with no
    registry of call sites for anybody to keep up to date (principle 13).

    **The read half of that path is gone since PR5.5** — a read of a tenant-wide
    kind asks at the acting hat and resolves no node — so what asks here now is
    every WRITE of such a kind, in six apps, once per request rather than once
    per call. The memo is what makes that true and is unchanged by the decision:
    it changes how often a node is resolved, never which node a question is
    about.

    The contract — source of truth, key, lifetime, invalidation, failure — is
    declared on the carrier, `Tenant`, beside the slot, exactly as the
    permission memo's is declared on `core.actor.Actor._permission_rows`.

    **The raise remembers nothing**, deliberately: a broken database must not
    become an answer the rest of the request agrees with, so the fill is after
    the `None` check and never before it.

    **This decides nothing about WHICH node a tenant-wide read should ask at.**
    Root or acting hat is an open question and this is right under either
    answer: it makes the resolution happen once per request instead of once per
    call, and has no opinion about what the question is.
    """
    remembered = tenant._root_organization
    if remembered is not None:
        return remembered
    root = Organization.objects.for_tenant(tenant).filter(parent__isnull=True).first()
    if root is None:
        raise Conflict(
            f"Tenant {tenant.slug!r} has no root organization. Every tenant is created with "
            "one; this row predates the hierarchy or was written around the service."
        )
    tenant.remember_root(root)
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
    require(actor, "organization.update", organization)
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
    closed** (the same LOW finding). `close_sockets` writes
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


def _register_kick(hook: Callable[[], None]) -> None:
    """**The ONE `transaction.on_commit` registration for a kick, of any kind.**

    Both seams above register through this line rather than each writing their
    own, and that is principle 13 applied to the claim
    `close_sockets_on_commit`'s docstring already makes — "the one
    registration site in the tree for this act". The two decisions in it are
    read once here instead of once per kind:

    * **on commit**, because a kick fired inside the transaction disconnects
      somebody on the strength of a write that then rolls back;
    * **`robust=True`**, because Django runs hooks in order and a non-robust
      hook that raises takes every hook behind it down with it (W1-9, F3 — the
      scar is an unreachable Temporal cancelling an invitation email). The
      channel layer is the least reliable thing in that list, and a withdrawal
      must not be able to cancel a sibling hook by failing to close a socket.

    The caller passes a NAMED nested `def` and never a `functools.partial`:
    Django's robust branch formats its error with `func.__qualname__`, which a
    partial does not have, so the handler whose whole job is to swallow a
    failing hook raises `AttributeError` itself and every hook queued behind it
    never runs — `robust` delivering its exact opposite, silently (P3 SEC-R3).
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
        Membership.objects.filter(tenant=tenant, organization__path__in=sorted(lost))
        .values_list("user_id", flat=True)
        .distinct()
    )


# --- Membership, and the escalation wall -------------------------------------
#
# THE ROLE KEY, AND WHERE IT IS VALIDATED (ADR core-25). `Membership.role` and
# `Invitation.role` carried `choices` until `0018`, and a `choices` list is
# exactly the wrong instrument for a value with three layers behind it: `owner`
# is the platform's, a declared role is some app's `roles.py`, and a custom role
# is a ROW one tenant owns. The first is a constant, the second is per process,
# the third is per tenant — and a per-process list cannot hold a per-tenant row,
# so a field validating against one would have refused every custom role the
# moment the feature shipped.
#
# So the validation moved here, into the three services that write the column,
# which are the only three places that have a tenant to read the third layer
# with. The belt behind them is the deploy census (`djb.W054` in
# `apps/core/checks.py`), which asks the same question of the rows that are
# already there.


# rule-16: not a capability and not an act — this is the vocabulary RESOLUTION the
# three writers below share, and a verb in front of it would make a lookup read as
# something somebody does. It is public because `MembershipAdmin` builds its role
# field from the same three layers, and a second derivation of "what may this
# tenant name" is exactly the drift this function exists to prevent.
def known_role_keys(*, tenant: Tenant) -> frozenset[str]:
    """Every role key this tenant may name, all three layers at once.

    `owner` (the platform's one role), every key an app declares in a
    `roles.py`, and every `core.Role` row this tenant owns. **Not `""`** — the
    roleless membership is a legal state of the column and is not a key
    anybody names; the one road to it is `add_membership(role="")`, and the
    services that take a role from a caller refuse it by not finding it here.
    """
    return (
        frozenset({OWNER_ROLE})
        | frozenset(role_declarations())
        | frozenset(
            str(key) for key in Role.objects.for_tenant(tenant).values_list("key", flat=True)
        )
    )


def _refuse_unknown_role(*, tenant: Tenant, role: str, allow_roleless: bool = False) -> None:
    """`Invalid` for a role key this tenant cannot name. The replacement for `choices`.

    ANOTHER TENANT'S CUSTOM ROLE IS UNKNOWN HERE, and that is the half a
    constraint could not have given: `Role.objects.for_tenant(tenant)` is the
    scoped read, so a key that exists in a neighbouring tenant reads exactly
    like a typo, which is what it is from this tenant's side.

    The refusal names the field and lists what this tenant may actually say,
    because "that is not a role" with no list is a support ticket — and the list
    is the three layers, which is the shape the caller has to learn anyway.
    """
    if allow_roleless and role == "":
        return
    known = known_role_keys(tenant=tenant)
    if role in known:
        return
    raise Invalid(
        {
            "role": [
                f"{role!r} is not a role in this tenant. It is one of "
                f"{', '.join(sorted(known))} — `owner`, a role an app declares in its "
                "`roles.py`, or one this tenant made for itself."
            ]
        }
    )


# rule-16: not a capability and not an act — a key's display name, the replacement for
# `Membership.Role(value).label`, which was an attribute access and not a verb
# either. Public for the same reason as `known_role_keys` above: the admin and the
# invitation mail must call one another's answer, not two.
def role_label(*, tenant: Tenant, key: str) -> str:
    """What to call a role key in something a person reads.

    The declaration's `name`, a custom `Role` row's `name`, `"Owner"` for the
    platform role, and otherwise the key itself — never a `ValueError`. It
    replaces `Membership.Role(value).label`, which raised for anything outside
    the three constants and would therefore have crashed the invitation mail for
    every custom role the moment one existed.

    A key that resolves to nothing comes back as itself rather than as a blank:
    a message naming `approver` when the role has been deleted is legible, and
    a message naming nothing at all is a bug report.
    """
    if key == OWNER_ROLE:
        return "Owner"
    declared = role_declarations().get(key)
    if declared is not None:
        return declared.name
    row = Role.objects.for_tenant(tenant).filter(key=key).first()
    if row is not None:
        return str(row.name)
    return key


def _placement(*, tenant: Tenant, organization: Organization | None, actor: Actor) -> Organization:
    """The node a grant or an offer lands on (ADR core-20, the placement law).

    The node NAMED, or — when none is — the acting hat, and never the root: a
    grant comes from where you sent it, and landing somebody at the root instead
    is a grant reaching further than the context it was sent from.

    One function because `add_membership` and `invite_member` had these three
    lines each, character for character, and the placement law is one rule. A
    node belonging to another tenant is `invalid` rather than `not_found`
    because the caller named a row they can see and asked for something
    incoherent with it; the doors resolve ids through the acting hat's own
    subtree, so a node outside it never reaches here at all.
    """
    where = organization if organization is not None else _landing_node(tenant=tenant, actor=actor)
    if where.tenant_id != tenant.pk:
        raise Invalid({"organization": ["That organization belongs to another tenant."]})
    return where


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
    wanted = collection(tenant, role)

    def sentence(missing: frozenset[str]) -> str:
        """Today's rank sentence where the difference is a template's; else the list.

        **Overrule 9 lives in this function.** `test_role_ceiling.py` and
        `test_admin_wall.py` assert the old words character for character, and
        those words quote two ROLES — a thing a set comparison does not have.
        So: when the keys the granter is short of are exactly the difference
        between the role they asked to grant and the role they themselves hold,
        the old sentence is still the true and the clearest one, and it is what
        comes out. Everywhere the rank table had no answer at all — a custom
        role, a bare permission through `create_grant` — the refusal names the
        SENTENCES of what is missing, because there is no pair of role words to
        quote and a key list is not something to show a person.
        """
        if _is_a_template_difference(
            tenant=tenant, actor=actor, organization=organization, role=role, missing=missing
        ):
            held = effective_role(actor.user, tenant, organization)
            return (
                f"You may not grant {role!r}: your own effective role there is {held!r}, and "
                "nobody grants above themselves."
            )
        return _missing_sentences("You may not grant what you do not hold yourself:", missing)

    _refuse_handing_out(
        actor=actor,
        tenant=tenant,
        organization=organization,
        permissions=wanted,
        sentence=sentence,
    )


def _missing_sentences(opening: str, missing: frozenset[str]) -> str:
    """The refusal a set comparison can make: the missing keys' own SENTENCES.

    Sentences and never keys, sorted. `widget.approve` is a word for this
    codebase; "You may not approve that widget." is what the person reading the
    refusal is actually short of, and it is already written down — every key in
    the vocabulary carries its own, derived or declared. A key the vocabulary
    does not know cannot reach here (both callers validate first), and
    `refusal_sentence` falls back to a generic line if one ever does.
    """
    return " ".join([opening, *sorted(refusal_sentence(key) for key in missing)])


def _is_a_template_difference(
    *,
    tenant: Tenant,
    actor: Actor,
    organization: Organization,
    role: str,
    missing: frozenset[str],
) -> bool:
    """Whether this shortfall is exactly "one template role minus another".

    The rank table's whole expressible vocabulary was `owner > admin > member`,
    and every sentence it ever produced described one of those three pairs. So
    the honest test for "would the old wall have said this" is not "is the
    missing key `tenant.own`" — that is only the admin-granting-owner pair — but
    "is the missing set the difference between the two role collections the old
    sentence would have named". A member granting `admin` is short of a hundred
    keys, and `test_role_ceiling.py::test_the_granted_role_is_judged_before_the_held_one`
    asserts it still hears `You may not grant 'admin':`.

    **Both words have to be template words**, and that is the half that keeps
    the new refusal from being swallowed. `rank()` knew three keys; a tenant's
    own role was not one of them, so the old wall said *nothing at all* about a
    custom role — that silence is the hole P4 closes, and quoting the old
    sentence for a custom role would be putting the old words on a refusal the
    old wall never made. So a custom key on either side falls through to the
    key-list sentence, which is the one that actually says what is missing.

    Returns False when the granter holds no role at all — there is no second
    word for the sentence to quote, and `_refuse_handing_out` has already
    refused that case with its own sentence before this is ever asked.
    """
    held_role = effective_role(actor.user, tenant, organization)
    if held_role is None:
        return False
    template = {OWNER_ROLE} | set(role_declarations())
    if role not in template or held_role not in template:
        return False
    return bool(missing) and missing == collection(tenant, role) - collection(tenant, held_role)


def _refuse_handing_out(
    *,
    actor: Actor,
    tenant: Tenant,
    organization: Organization,
    permissions: frozenset[str],
    sentence: Callable[[frozenset[str]], str] | None = None,
) -> None:
    """**Nobody hands out what they do not hold.** The hand-out rule, as a set.

    `permissions` is what this act would give somebody — a role's whole
    collection, the keys a role gained, the one key a grant names. Every one of
    them must already be in the granter's own effective set **at the node the
    act lands on**, and the difference is the refusal.

    **Why a set and not a rank.** `_refuse_escalation` used to compare
    `rank(role) > rank(held)` over a three-word table. A tenant's own role is a
    fourth word with no rank at all — `rank("approver")` is `0` — so it sorted
    BELOW `member` and everybody could hand it out, whatever its collection
    said. The measured hole on this tree: a plain member holding
    `membership.create` by grant assigned a custom `approver` carrying
    `organization.create`, a key that member does not hold, and the membership
    was written. A set comparison has no such blind spot, because it never asks
    how big a role is — only whether you already hold every piece of it.

    The two altitudes are unchanged from the rank wall and for the reasons ADR
    core-22's L1 ruling gives: `system` is a named audited altitude and passes;
    a `human` or `agent` actor carrying no user is refused, because nobody is
    authenticated and there is no set to measure.

    **When the thing is absent:** an empty effective set at the node is its own
    refusal with its own sentence — the granter is standing outside the subtree
    entirely, and telling them which keys they are short of would describe the
    smaller of two problems.
    """
    if actor.kind == "system":
        return
    granter = actor.user
    if granter is None:
        raise Forbidden(
            "This request resolved nobody, so there is no role of your own to grant "
            "beneath. Sign in, or act as the system."
        )
    held = effective_permissions(granter, tenant, organization, memo=actor)
    if not held:
        raise Forbidden(
            "You hold no role over that part of the organization, so you may not grant one there."
        )
    missing = frozenset(permissions) - held
    if not missing:
        return
    raise Forbidden(
        sentence(missing)
        if sentence is not None
        else _missing_sentences("You may not hand out what you do not hold yourself:", missing)
    )


def _refuse_taking_back(
    *,
    actor: Actor,
    tenant: Tenant,
    membership: Membership,
    verb: str,
) -> None:
    """**The other half of the wall: what the person being acted _on_ holds.**

    `_refuse_handing_out` bounds what an act *gives*. That is the whole ceiling
    only while the only way to change what somebody may do is to hand them
    something; it is not. An `admin` who may not *grant* `owner` could take the
    owner's hat away instead — remove the row, or set its role to `member` — and
    arrive at the same power by subtraction. So what the target **currently
    holds** at the node their membership sits on is measured against what the
    actor holds there, and anything the target has that the actor does not is
    refused.

    **A set difference, for the reason `_refuse_handing_out` gives.** It used to
    be `rank(membership.role) > rank(held)`, which could only compare three
    words and sorted every custom role below `member`. The set has no such
    blind spot, and where the difference is exactly a template pair's the
    sentence is still the old one — `_is_a_template_difference` is where that
    decision is made and why.

    **Four roads reach it and this is the only guard on any of them.**
    `revoke_membership` calls it before a delete (SEC-1's MED-1), `set_role`
    before a role change, and `create_grant`/`delete_grant` before a withhold
    lands or an allow is withdrawn — so the predicate, the sentence and the
    comparison are one thing rather than four that agree today. The demotion
    road used to answer `200` before this guard existed.

    **Parameterised by the verb, where `_refuse_orphaning_the_tenant`
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
    where = membership.organization
    held_by_them = effective_permissions(membership.user, tenant, where)
    missing = held_by_them - effective_permissions(acting_user, tenant, where, memo=actor)
    if not missing:
        return
    if _is_a_template_difference(
        tenant=tenant, actor=actor, organization=where, role=str(membership.role), missing=missing
    ):
        held = effective_role(acting_user, tenant, where)
        raise Forbidden(
            f"You may not {verb} a {membership.role!r}: your own effective role there is "
            f"{held!r}, and nobody {verb}s above themselves."
        )
    raise Forbidden(
        _missing_sentences(
            f"You may not {verb} somebody who holds what you do not:",
            missing,
        )
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
    where = _placement(tenant=tenant, organization=organization, actor=actor)
    if is_default:
        Membership.objects.filter(user_id=user.pk, is_default=True).update(is_default=False)
    if role is None:
        first = not Membership.objects.filter(tenant=tenant).exists()
        # THE FIRST MEMBERSHIP IS STILL THE OWNER, and everybody after it gets
        # whatever role this deployment declared as the default — `member` on
        # the template, `""` in a product that deleted it. `Membership.Role`'s
        # constants are no longer this column's `choices`, so the second half
        # reads the declaration rather than an enum member: a product that
        # renamed its entry-level role would otherwise have got `member`, a key
        # its own `roles.py` no longer holds.
        role = OWNER_ROLE if first else default_role_key()
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=where,
        role=role,
    )
    # THE CAPABILITY, AND IT IS SECOND — behind the escalation wall, not in
    # front of it. Putting somebody in a tenant is `membership.create` at the
    # node it lands on, and until the vocabulary had a key for it this service
    # authorized nothing at all: the wall bounds the role being GRANTED, and
    # for a member granting `member` that comparison is `1 > 1` — false — so a
    # plain member could add people, against this route's own published
    # contract. The wall still speaks first, and deliberately: it is the one
    # that refuses an actor holding NOTHING here, and the one that refuses a
    # request nobody is behind, each with its own sentence saying which.
    # Standing before capability, exactly as `set_role` orders its three.
    require(actor, "membership.create", where)
    # THE KEY, AFTER THE WALL. **Standing is judged before the payload is
    # believed** — the tree's own ruling, pinned in
    # `test_role_ceiling.py`'s
    # `test_a_role_this_product_does_not_know_does_not_get_you_past_the_ceiling`:
    # somebody who holds nothing over this node hears that, and not a spelling
    # lesson about a value they were never entitled to grant anyway.
    #
    # `""` is legal here and only here: a membership that holds nothing beyond
    # its grants is a state the system reaches (`accept_invitation` of an offer
    # that named no role, a deployment with no default declared), and it is
    # never a state a caller asks a door for.
    _refuse_unknown_role(tenant=tenant, role=role, allow_roleless=True)
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
    `_refuse_taking_back` — one sentence template, one word of it
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
    `_refuse_orphaning_the_tenant` below, called from both roads, because two
    guards written separately drift and a client that branches on the words
    would get a different answer depending on which road it took.
    """
    # REACH, AND IT IS FIRST (R1-F4): reach before capability. A membership
    # the actor could not have named — another tenant's row, or one in a sibling
    # branch — is `NotFound`, never a wall's sentence: not-there and not-yours are
    # one answer, and a `Forbidden` quoting "no role over that part" about a row
    # they cannot see would confirm the row exists. `revoke_membership` has
    # asked this first since SEC-1's MED-1; this asked it never, so
    # `Membership.objects.get(pk=<another tenant's row>)` + `set_role` wrote
    # that tenant's data (the R1 review's shell sequence).
    if not may_be_named(actor, membership):
        raise NotFound()
    # The escalation wall — a promotion is a grant with an extra step, and the
    # rule is about the role being granted rather than about an object a
    # predicate could inspect. FIRST OF THE WALLS: it is the one that refuses an
    # actor holding nothing at this node, with the sentence that says so.
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=membership.organization,
        role=role,
    )
    # THE CAPABILITY, second: changing what somebody may do here is
    # `membership.update` at the node their membership sits on. Behind the
    # escalation wall for that wall's own reason, and in front of the ceiling so
    # that somebody who may not touch this row at all hears that rather than a
    # sentence quoting the role of the person they reached for.
    require(actor, "membership.update", membership.organization)
    # And the other half of the wall, `revoke_membership`'s own: the role this
    # membership *holds*. Third, never first — `_refuse_escalation` above is
    # what refuses an actor holding nothing here, with the sentence that says
    # so, and this one's sentence quotes the role it found.
    _refuse_taking_back(
        actor=actor,
        tenant=tenant,
        membership=membership,
        verb="demote",
    )
    # THE KEY, AND IT IS THIRD — after both walls and before the floor, which is
    # exactly where the `role in Membership.Role.values` half of the old guard
    # sat. **Standing is judged before the payload is believed**
    # (`test_role_ceiling.py`'s
    # `test_a_role_this_product_does_not_know_does_not_get_you_past_the_ceiling`):
    # an admin reaching for an owner's row hears the ceiling whatever value they
    # put in it, because that answer is about the actor and does not depend on
    # what they sent. And it is BEFORE the floor for the floor's own stated
    # reason — answering `conflict` to a typo would teach a caller that their
    # spelling mistake was a state problem.
    #
    # `""` is refused here: the roleless membership is a state the system
    # reaches through `add_membership`, never one a door sets, and a caller who
    # meant "take one thing away" wants a withhold, not a blank.
    _refuse_unknown_role(tenant=tenant, role=role)
    # THE WRITE, the narrowing kick, the event and the ownerless floor — all
    # four in `_write_role_and_kick`, because the floor now measures the state
    # the write LEAVES and therefore has to sit on the write's own side of the
    # line. The order and the reasons are that function's docstring.
    return _write_role_and_kick(tenant=tenant, membership=membership, role=role, actor=actor)


def _write_role_and_kick(
    *, tenant: Tenant, membership: Membership, role: str, actor: Actor
) -> Membership:
    """Set the role, and hang up on the person if their reads just shrank.

    **Split out of `set_role` so the measurement brackets the write and only
    the write.** `before` is read AFTER the three walls rather than at the top
    of the caller: a refused call must not pay for a comparison nobody will
    make. `after` is read INSIDE the transaction, so the comparison is against
    the row this call actually wrote, and the kick itself is registered on
    commit — a rollback hangs up on nobody.

    Three statements each way whatever the shape of the tree
    (`core.authz.read_kinds_by_node`), and the decision is
    `kick_if_reads_narrowed`'s, which is where the rule is written down.

    **The event and the ownerless floor are here too, and both belong on this
    side of the line.** The event is inside the transaction the write happened
    in (ADR core-26). The floor measures the state the write LEAVES — a caller
    that ran it before the write would be asking about a row that no longer
    exists — so it is the last thing this function does and a `Conflict` from it
    rolls the write back with the service's own transaction.

    **A refused call leaves the caller's instance as it found it.** The
    transaction puts the ROW back; the `Membership` object the caller handed in
    is Python and no transaction reaches it, so a refusal raised after
    `membership.role = role` would hand back an instance claiming a role the
    database never got. Not theoretical tidiness: the next guard the caller runs
    — `revoke_membership`'s floor, which reads `membership.role` — would then
    measure the value of a write that did not happen, and wave through the
    removal of the tenant's last owner.
    """
    previous = str(membership.role)
    before = read_kinds_by_node(membership.user, tenant)
    try:
        membership.role = role
        with as_invalid():
            membership.full_clean()
        membership.save(update_fields=["role", "updated_at"])
        kick_if_reads_narrowed(
            tenant=tenant,
            user_id=membership.user_id,
            before=before,
            after=read_kinds_by_node(membership.user, tenant),
        )
        _publish(
            events.MEMBERSHIP_UPDATED,
            tenant=tenant,
            payload={
                "tenant_id": str(tenant.pk),
                "organization_id": str(membership.organization_id),
                "membership_id": str(membership.pk),
                "role": role,
            },
            actor=actor,
        )
        _refuse_orphaning_the_tenant(tenant=tenant, was_owner=previous == OWNER_ROLE)
    except Exception:
        membership.role = previous
        raise
    return membership


def _refuse_orphaning_the_tenant(*, tenant: Tenant, was_owner: bool) -> None:
    """A tenant with no owner is a tenant nobody can administer. **After the write.**

    The same invariant `apps.accounts.services.tenants_this_user_alone_owns`
    protects on the erasure path, enforced here because removal is the other
    way to reach the state: no one left who can invite a member, change a role,
    or close it — and nobody notices until they need to do one of those things.

    **It reads the STATE THE CALL LEAVES BEHIND, not the row under the caller's
    hand, and that is the change.** The old guard counted rows whose `role`
    column read `owner` and ran *before* the write, which answered the question
    only while the column was the whole story. It is not: ownership is
    `tenant.own`, a reserved key `owner` alone carries and a `withhold` grant
    can take away. So this asks the question the tenant actually cares about —
    *is there still somebody on the root holding `tenant.own`?* — and asks it
    after the write, inside the service's transaction, so a `Conflict` rolls
    the write back and nothing partial survives.

    **One query, not a resolution per person.** `tenant.own` is reserved: no
    pattern matches it, no `RolePermission` include row may add it and no
    `allow` grant may name it, so `owner` is the only role that carries it and
    the holders are exactly the root memberships with `role = "owner"` and no
    `withhold` of the key. That is the whole algebra, expressed as one
    `exclude(...)` rather than an `effective_permissions` call per membership.

    **On the root, deliberately.** An owner of one branch owns that branch; a
    tenant whose only owner sat under a sub-organization would be a tenant
    nobody could administer at the top, which is the state this refuses. The
    door that can create such an owner is `add_membership` with a node named,
    and it is a legitimate thing to do — this floor simply does not count it.

    **`was_owner` is the trigger, and it is read before the write.** The floor
    refuses a TRANSITION — a tenant that had somebody on top and does not any
    more — never a state it merely found. A tenant with no root owner is a
    legitimate state the system reaches (a tenant mid-setup, a tenant whose tree
    is administered from a branch), and a floor that refused every write in one
    would refuse a demotion that has nothing to do with ownership and cannot
    make anything worse. So the caller says whether the row under its hand was
    an owner, from the value it read before it wrote, and a call that could not
    have removed ownership never asks the question at all.

    Two roads reach it and this is the only guard on either: `set_role` after a
    demotion and `revoke_membership` after a delete, so the code, the sentence
    and the count are one thing rather than two that agree today. The sentence
    reads for both — a demotion *is* the last owner being removed, from
    ownership rather than from the tenant — which is why it is not
    parameterised by the verb.

    **The two services that are NOT callers, said so a reader does not go
    looking.** `create_grant` cannot reach this state: `tenant.own` is reserved,
    so a withhold naming it is `Invalid` before any write. `set_role_collection`
    cannot either: `owner` is refused at its own door, and no other role's
    collection carries the ownership verb. `delete_role` cannot: a role deletion
    names no owner, because `owner` is not a row.
    """
    if not was_owner:
        return
    root = root_organization(tenant=tenant)
    withheld = (
        Grant.objects.for_tenant(tenant)
        .filter(permission=OWNERSHIP_PERMISSION, effect=Grant.Effect.WITHHOLD)
        .values("membership_id")
    )
    holders = Membership.objects.filter(tenant=tenant, organization=root, role=OWNER_ROLE).exclude(
        pk__in=withheld
    )
    if not holders.exists():
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
    `_refuse_taking_back` and `set_role` calls it too: the
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
    require(actor, "membership.delete", membership.organization)
    _refuse_taking_back(actor=actor, tenant=tenant, membership=membership, verb="remove")
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
    was_owner = died.role == OWNER_ROLE
    membership.delete()
    # THE OWNERLESS FLOOR, after the delete for `_refuse_orphaning_the_tenant`'s
    # own stated reason: it reads the state this call leaves behind, and a
    # `Conflict` here rolls the delete back with the whole service transaction.
    _refuse_orphaning_the_tenant(tenant=tenant, was_owner=was_owner)
    close_sockets_on_commit(user_id=user_id, reason=KICK_MEMBERSHIP_REVOKED)
    return died


# --- The hand-out family: roles and grants (ADR core-25, ADR core-26) ---------


def _event_bus() -> Callable[..., Any] | None:
    """`events.emit`, resolved at call time through `core.bridge`, or `None`.

    `core` sits BELOW `apps/events` (rule 7), so this is a registry lookup and
    never an import — `apps/example/services.py::_event_bus` is the same
    function one layer up, and the two agree deliberately.

    **`find()` first, then `get()` once.** `get()` never returns `None` — with
    nothing registered it hands back a logging no-op — so a caller that wanted
    to know whether anybody was listening could not find out from it. Asking
    `get()` afterwards is a different question, and only production answers it:
    there an absent registration is `BridgeNotRegistered` and the caller's
    transaction rolls back, because a deployment quietly dropping every event on
    the floor is the failure `core.bridge` exists to refuse. Everywhere else it
    is the no-op, and the `None` is what makes the caller log and carry on.
    """
    found = bridge.find(bridge.EMIT)
    if found is not None:
        return found
    # Production refuses here; every other environment falls through to `None`.
    bridge.get(bridge.EMIT)
    return None


def _publish(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Actor) -> bool:
    """Say that something happened, in the transaction it happened in.

    The payload shape per name is `apps/core/events.py`'s docstring — v1, flat,
    `tenant_id` always and `organization_id` wherever the row belongs to one
    part of the tenant (rule 38). It is assembled at the call site rather than
    read off a schema because `core`'s read schemas for these rows are P5's;
    when they land the assembly moves behind them, exactly as `WidgetOut` is
    what `apps/example` publishes.

    Returns whether anybody was listening, which is a fact worth having in a
    test and a log line worth having in a tree where the bus is not mounted.
    """
    emit = _event_bus()
    if emit is None:
        # `event_name`, not `event`: structlog's own first argument is called
        # `event`, and a log line that shadows it is a `TypeError` at 2am.
        log.info("core.event.unpublished", event_name=name, tenant_id=str(tenant.pk))
        return False
    emit(name=name, tenant=tenant, payload=payload, actor=actor)
    return True


def _refuse_undeclared_permissions(*, field: str, permissions: Iterable[str]) -> None:
    """`Invalid` for anything outside the vocabulary, a reserved key, or a virtual kind.

    Three refusals under one name because they are one question from the
    caller's side — *may this string appear in a collection or on a grant?* —
    and the answer has to name the offending key whichever it is. `tenant.own`
    is the reserved half: it is in the vocabulary, `owner` holds it, and nothing
    else may ever hand it out, which is the whole of the ceiling the rank table
    used to enforce. A key on a VIRTUAL kind is the third: it is in the
    vocabulary too, and it is in nobody's collection by construction
    (`grantable_permissions`), so a row carrying it would be a row that grants
    nothing while reading as though it grants something.
    """
    words = vocabulary()
    offenders = sorted(
        key
        for key in permissions
        if key not in words or key in RESERVED_PERMISSIONS or words[key].kind in VIRTUAL_KINDS
    )
    if offenders:
        raise Invalid({field: [_undeclared_or_reserved(key) for key in offenders]})


def _undeclared_or_reserved(key: str) -> str:
    """The sentence for one offending key — and the three halves say DIFFERENT things.

    One sentence for both used to read *"not a permission this deployment may
    hand out"* whatever the reason, and for the reserved half that is not true:
    `tenant.own` IS a permission this deployment has — it is in the vocabulary,
    `owner` holds it, and `GET /permissions/` lists it — which made the remedy
    the sentence offered ("look it up in the list") send the reader to a list
    the key is already in. A caller who mistyped a key and a caller who tried to
    hand out ownership need to be told two different things.
    """
    if key in RESERVED_PERMISSIONS:
        return (
            f"{key}: reserved to the `owner` role — no role and no grant may name it, "
            "because ownership is the one capability that cannot be handed out sideways"
        )
    word = vocabulary().get(key)
    if word is not None and word.kind in VIRTUAL_KINDS:
        return (
            f"{key}: `{word.kind}` is a VIRTUAL kind — it names no table, so there is no "
            "row for anybody to be given authority over and no role or grant may carry "
            "this key. Who may perform it is decided by its policy predicate alone"
        )
    return f"{key}: not a permission this deployment has — `GET /permissions/` lists them"


def _expand_patterns(*, field: str, permissions: Iterable[str]) -> frozenset[str]:
    """Patterns to KEYS, at write time. `"*.read"` is 36 rows, not one row.

    A role declared in code keeps its patterns (`DeclaredRole.permissions`) and
    re-matches them against the vocabulary on every read, which is what makes
    `("*.read",)` still mean "may read everything" in a deployment with three
    more apps in it. A tenant's own role cannot work that way: its collection is
    rows, and a row holding `*.read` would either have to be matched at read
    time — a second matching layer — or silently gain keys as apps are added,
    which is a widening nobody asked for. So the expansion happens once, here,
    and the rows are keys.

    A pattern that matches nothing is `Invalid` naming the pattern: it is
    almost always a typo, and a role silently created with an empty collection
    is a support ticket a month later.

    **The population matched is `grantable_permissions()`, not the whole
    vocabulary** — the one exclusion, shared with `collection()` and
    `defaults_for()`. Reserved keys were already out; virtual kinds are out for
    the same reason one layer along: a key on a kind with no table is decided by
    its predicate and belongs in nobody's collection, so `"*"`, `"*.configure"`
    and `deployment.*` must not expand to one. They did, and the two ways it
    broke are both writes: an owner calling `create_role(permissions=["*"])`
    was refused by `_refuse_handing_out` (the expansion held a key
    `collection(OWNER_ROLE)` does not), and a `system` actor — which passes the
    wall by design — WROTE the include row, re-inverting the escalation wall for
    that role permanently. A literal virtual key is not silently dropped here:
    it falls through as written and `_refuse_undeclared_permissions` says so in
    a sentence, because a caller who typed one asked a question and deserves the
    answer.
    """
    grantable = grantable_permissions()
    expanded: set[str] = set()
    empty: list[str] = []
    for entry in permissions:
        if not any(character in entry for character in "*?["):
            expanded.add(entry)
            continue
        matched = {
            key for key in grantable if key not in RESERVED_PERMISSIONS and fnmatchcase(key, entry)
        }
        if not matched:
            empty.append(entry)
        expanded |= matched
    if empty:
        raise Invalid(
            {field: [f"{pattern}: matches no permission in this deployment" for pattern in empty]}
        )
    return frozenset(expanded)


def _refuse_a_key_the_code_layer_owns(*, key: str) -> None:
    """`owner` and every declared role belong to code, not to a tenant's table.

    A `Role` row wearing one of those keys would be a second opinion about a
    collection the code already answers, and `collection()` reads the code layer
    first — so the row would be a delta nobody could see and a name nobody could
    edit. The collision is refused here rather than by a constraint because the
    other half of the population is not a table (the `Role` docstring says so).
    """
    if key == OWNER_ROLE or key in role_declarations():
        raise Invalid(
            {
                "key": [
                    f"{key!r} is already a role this deployment declares in code. "
                    "Change what it holds with a role delta, or choose another key."
                ]
            }
        )


def _kick_the_holders_of(*, tenant: Tenant, role_key: str) -> None:
    """Hang up on everybody wearing this role key, because its reads just shrank.

    **One query and an over-kick, declared.** `set_role_collection` can take a
    read away from a role thousands of people hold, and computing
    `read_kinds_by_node` per person to find out whose set actually moved would
    be three statements each. The role lost the key; everybody holding the role
    is affected unless a grant of their own puts it back, and reconnecting is
    cheap where being wrong is not. So the kick is per holder of the key and the
    over-kick — the person whose own `allow` grant restores it — is accepted and
    said here rather than discovered.

    Idempotent and on commit, like every other kick (principle 16).
    """
    for user_id in (
        Membership.objects.filter(tenant=tenant, role=role_key)
        .values_list("user_id", flat=True)
        .distinct()
    ):
        close_sockets_on_commit(user_id=user_id, reason=KICK_PERMISSIONS_NARROWED)


def _kick_if_a_read_was_taken(*, tenant: Tenant, membership: Membership, permission: str) -> None:
    """The one-person half of P4.8: a `.read` key withdrawn closes their sockets.

    A socket resolved what it may hear once, at the handshake (ADR core-27). A
    withhold landing on a read key, or an `allow` of one being deleted, is the
    New Enemy window; closing the connection forces the reconnect that
    recomputes. A write key moves nothing a socket is delivering, so it kicks
    nobody — the same asymmetry `kick_if_reads_narrowed` states.
    """
    word = vocabulary().get(permission)
    if word is None or not word.is_read:
        return
    close_sockets_on_commit(user_id=membership.user_id, reason=KICK_PERMISSIONS_NARROWED)


@service
def create_role(
    *,
    tenant: Tenant,
    actor: Actor,
    key: str,
    name: str,
    description: str = "",
    permissions: Iterable[str] = (),
) -> Role:
    """Make a role this tenant owns, holding exactly what somebody put in it.

    The third layer (ADR core-25). `owner` is the platform's one role and
    `admin`/`member` are declarations in an app's `roles.py`; a tenant that
    needs "Approver" makes one of these, and its collection is assembled
    entirely out of `RolePermission` include rows.

    **Authorized at the ROOT, and that is not an oversight.** A role is
    tenant-wide — `Role` is `TenantScopedModel` and not `OrgScopedModel`,
    because resolving one through `governing()` would be a tree walk on every
    `require` — so the node the capability is measured at is the top of the
    tree. A branch admin may hand out what they hold on their branch (that is
    `create_grant`); they may not mint a word the whole tenant now speaks.

    **And bounded by the maker's own set, at their hat.** `_refuse_handing_out`
    measures the collection against what the actor holds *where they are
    standing*: a role is tenant-wide, but the authority to put `widget.approve`
    in one comes from holding `widget.approve`, and holding it in one branch is
    holding it. `"*.read"` and its siblings are expanded to keys first, so what
    the wall measures is what the rows will say.
    """
    require(actor, "role.create", root_organization(tenant=tenant))
    _refuse_a_key_the_code_layer_owns(key=key)
    wanted = _expand_patterns(field="permissions", permissions=permissions)
    _refuse_undeclared_permissions(field="permissions", permissions=wanted)
    _refuse_handing_out(
        actor=actor,
        tenant=tenant,
        organization=_landing_node(tenant=tenant, actor=actor),
        permissions=wanted,
    )
    role = Role(tenant=tenant, key=key, name=name, description=description)
    with as_invalid():
        role.full_clean()
    role.save()
    RolePermission.objects.for_tenant(tenant).bulk_create(
        RolePermission(
            tenant=tenant,
            role_key=key,
            permission=permission,
            effect=RolePermission.Effect.INCLUDE,
        )
        for permission in sorted(wanted)
    )
    _publish(
        events.ROLE_CREATED,
        tenant=tenant,
        payload={
            "tenant_id": str(tenant.pk),
            "role_key": key,
            "name": name,
            "permissions": sorted(wanted),
        },
        actor=actor,
    )
    log.info("core.role.created", role_key=key, permission_count=len(wanted))
    return role


@service
def update_role(
    *,
    tenant: Tenant,
    actor: Actor,
    role: Role,
    name: str | None = None,
    description: str | None = None,
) -> Role:
    """Rename a tenant's own role. **The key never moves** (§D10).

    A membership, a pending invitation and every delta row join on `key`, so
    renaming the display name is a one-column write and renaming the key would
    be a migration of three tables nobody asked for. `name` is the renamable
    half by construction.

    A row whose key belongs to the code layer is refused rather than edited: it
    should not exist (`create_role` refuses to make one), and editing it would
    be maintaining a second opinion about a collection the declaration answers.
    """
    require(actor, "role.update", root_organization(tenant=tenant))
    _refuse_a_key_the_code_layer_owns(key=str(role.key))
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    with as_invalid():
        role.full_clean()
    role.save(update_fields=["name", "description", "updated_at"])
    _publish(
        events.ROLE_UPDATED,
        tenant=tenant,
        payload={"tenant_id": str(tenant.pk), "role_key": str(role.key), "name": str(role.name)},
        actor=actor,
    )
    return role


@service
def set_role_collection(
    *,
    tenant: Tenant,
    actor: Actor,
    role_key: str,
    permissions: Iterable[str] = (),
) -> list[RolePermission]:
    """Say what a role holds in this tenant, as a whole set rather than a diff.

    **Two shapes under one service, because a caller has one question.** A
    CUSTOM role's collection *is* its include rows, so the wanted set is written
    as includes and everything else is deleted. A DECLARED role has a code layer
    underneath it, so what is stored is the DELTA — an include row for each key
    the tenant added, an exclude row for each one it took away — and a
    deployment that later widens the declaration widens this tenant too, which
    is the property a stored snapshot would have thrown away.

    **`owner` is refused.** It IS the vocabulary (present and future, the
    reserved verb included), so a delta on it is a ceiling disappearing quietly.

    **Both directions are walled.** Keys ADDED must be ones the actor holds
    (`_refuse_handing_out`); keys REMOVED must be too, because taking a
    capability away from everybody who holds this role is a take-back at scale —
    an admin who may not withhold `tenant.own` from one owner must not reach the
    same place by editing the role out from under them.
    """
    require(actor, "role.update", root_organization(tenant=tenant))
    if role_key == OWNER_ROLE:
        raise Invalid(
            {
                "role_key": [
                    "`owner` is the whole vocabulary by definition and holds no delta. "
                    "Withhold a key from one person instead."
                ]
            }
        )
    wanted = _expand_patterns(field="permissions", permissions=permissions)
    _refuse_undeclared_permissions(field="permissions", permissions=wanted)
    declared = role_key in role_declarations()
    if not declared and not Role.objects.for_tenant(tenant).filter(key=role_key).exists():
        raise NotFound()
    base = defaults_for(role_key) if declared else frozenset()
    held_now = collection(tenant, role_key)
    added = wanted - held_now
    removed = held_now - wanted
    where = _landing_node(tenant=tenant, actor=actor)
    _refuse_handing_out(actor=actor, tenant=tenant, organization=where, permissions=added)
    _refuse_handing_out(actor=actor, tenant=tenant, organization=where, permissions=removed)

    RolePermission.objects.for_tenant(tenant).filter(role_key=role_key).delete()
    rows = [
        RolePermission(
            tenant=tenant,
            role_key=role_key,
            permission=permission,
            effect=RolePermission.Effect.INCLUDE,
        )
        for permission in sorted(wanted - base)
    ] + [
        RolePermission(
            tenant=tenant,
            role_key=role_key,
            permission=permission,
            effect=RolePermission.Effect.EXCLUDE,
        )
        for permission in sorted(base - wanted)
    ]
    written = RolePermission.objects.for_tenant(tenant).bulk_create(rows)
    if any(key in vocabulary() and vocabulary()[key].is_read for key in removed):
        _kick_the_holders_of(tenant=tenant, role_key=role_key)
    _publish(
        events.ROLE_UPDATED,
        tenant=tenant,
        payload={
            "tenant_id": str(tenant.pk),
            "role_key": role_key,
            "permissions": sorted(wanted),
        },
        actor=actor,
    )
    log.info(
        "core.role.collection_set",
        role_key=role_key,
        permission_count=len(wanted),
    )
    return written


@dataclass(frozen=True)
class DeletedRole:
    """What a deleted role WAS, after the row is gone. `RevokedMembership`'s shape."""

    role_id: UUID
    key: str
    name: str

    @property
    def audit_object(self) -> tuple[str, UUID]:
        """The `(label, pk)` pair the audit seam reads off a row that no longer exists."""
        return (Role._meta.label, self.role_id)


@service
def delete_role(*, tenant: Tenant, actor: Actor, role: Role) -> DeletedRole:
    """Remove a tenant's own role, and the delta rows that named it.

    **Refused while anybody still wears the key**, membership or pending
    invitation. `Membership.role` and `Invitation.role` are strings and not
    foreign keys — two of the three role layers are code, so half the keys those
    columns name have no row to point at — which means the database cannot
    protect this and the service has to. A role deleted out from under a
    membership would leave that person holding nothing, silently, which is a
    withdrawal nobody performed.

    The cascade is here rather than in the schema for the same reason: the
    `RolePermission` join is the key, not a foreign key.

    **Not a caller of the ownerless floor.** A role deletion names no owner —
    `owner` is not a row and cannot be deleted — so there is no road from here
    to a tenant with nobody on top.
    """
    require(actor, "role.delete", root_organization(tenant=tenant))
    key = str(role.key)
    worn_by = Membership.objects.filter(tenant=tenant, role=key).count()
    # rule-24: a role is TENANT-WIDE (`Role` is `TenantScopedModel`, not
    # `OrgScopedModel` — resolving one through `governing()` would be a tree walk
    # on every `require`), so "is anybody still being offered this key" is a
    # tenant-wide question by construction. Narrowing it with `visible_to` would
    # let a branch admin delete a role a sibling branch's pending invitation
    # still names, which is the exact orphaning this refusal exists to prevent —
    # a COUNT of rows nobody is shown, never a listing.
    offered_to = (
        Invitation.objects.for_tenant(tenant)  # rule-24: tenant-wide by construction, see above
        .filter(role=key, status=Invitation.Status.PENDING)
        .count()
    )
    if worn_by or offered_to:
        raise Conflict(
            f"{key!r} is still held by {worn_by} membership(s) and offered by "
            f"{offered_to} pending invitation(s). Move them to another role first."
        )
    died = DeletedRole(role_id=role.pk, key=key, name=str(role.name))
    RolePermission.objects.for_tenant(tenant).filter(role_key=key).delete()
    role.delete()
    _publish(
        events.ROLE_DELETED,
        tenant=tenant,
        payload={"tenant_id": str(tenant.pk), "role_key": key},
        actor=actor,
    )
    return died


@service
def create_grant(
    *,
    tenant: Tenant,
    actor: Actor,
    membership: Membership,
    permission: str,
    effect: str = Grant.Effect.ALLOW,
) -> Grant:
    """Give one person one capability in one place, or take one away.

    The bottom layer, and the one an administrator reaches for when a role is
    the wrong size for one person. `allow` adds a key the role does not carry;
    `withhold` removes one it does, and beats everything — "forbid overrides
    permit" — because the alternative is a subtraction somebody undoes by being
    given something.

    **An UPSERT on `(membership, permission)`** (principle 16). Every door is
    at-least-once; the same hand-out arriving twice is one row with the last
    effect on it, not a constraint violation the caller has to interpret.

    **Which wall depends on the direction.** An `allow` is a hand-out, bounded
    by what the granter holds. A `withhold` is a take-back, bounded by what the
    TARGET holds — the ceiling, with the verb `restrict`.

    **Reach is the door's.** The membership arrives resolved; the door fetches
    it through `get_membership(org=<hat>)`, so a row outside the acting hat's
    subtree is `not_found` before this service is reached (§C8). What this
    service asserts is the tenancy half, which is its own to assert — a
    membership belonging to another tenant is incoherent with the `tenant`
    argument and is `invalid`, never a silent write into somebody else's data.
    """
    # REACH, FIRST (R1-F4 supersedes P4.4's recorded sentence). This refused a
    # foreign membership with `Invalid("That membership belongs to another
    # tenant.")`, which answers a question the caller may not ask: a refusal
    # that tells another tenant's row apart from a nonexistent id is an
    # existence oracle (§C8). `may_be_named` folds both into `NotFound`, and it
    # covers the sibling-branch case the tenancy comparison never saw.
    if not may_be_named(actor, membership):
        raise NotFound()
    require(actor, "grant.create", membership.organization)
    _refuse_undeclared_permissions(field="permission", permissions=[permission])
    if effect == Grant.Effect.WITHHOLD:
        _refuse_taking_back(actor=actor, tenant=tenant, membership=membership, verb="restrict")
    else:
        _refuse_handing_out(
            actor=actor,
            tenant=tenant,
            organization=membership.organization,
            permissions=frozenset({permission}),
        )
    grant, _created = Grant.objects.for_tenant(tenant).update_or_create(
        tenant=tenant,
        membership=membership,
        permission=permission,
        defaults={"effect": effect},
    )
    if effect == Grant.Effect.WITHHOLD:
        _kick_if_a_read_was_taken(tenant=tenant, membership=membership, permission=permission)
    _publish(
        events.GRANT_CREATED,
        tenant=tenant,
        payload={
            "tenant_id": str(tenant.pk),
            "organization_id": str(membership.organization_id),
            "membership_id": str(membership.pk),
            "permission": permission,
            "effect": effect,
        },
        actor=actor,
    )
    log.info("core.grant.created", permission=permission, effect=effect)
    return grant


@dataclass(frozen=True)
class RevokedGrant:
    """What a withdrawn grant WAS, after the row is gone. `RevokedMembership`'s shape.

    `effect` travels because a reader six weeks later cannot tell the two
    withdrawals apart without it: removing an `allow` narrows what that person
    may do, removing a `withhold` widens it.
    """

    grant_id: UUID
    membership_id: UUID
    organization_id: UUID
    permission: str
    effect: str

    @property
    def audit_object(self) -> tuple[str, UUID]:
        """The `(label, pk)` pair the audit seam reads off a row that no longer exists."""
        return (Grant._meta.label, self.grant_id)


@service
def delete_grant(*, tenant: Tenant, actor: Actor, grant: Grant) -> RevokedGrant:
    """Withdraw an exception. **Which wall applies depends on which way it pointed.**

    Removing an `allow` takes a capability away from somebody, so it is a
    take-back and the ceiling measures it. Removing a `withhold` GIVES a
    capability back, so it is a hand-out and the granter must hold what they are
    restoring — which is the case the rank table could not have seen at all,
    because a withhold names a permission and not a role.
    """
    membership = grant.membership
    # REACH, FIRST (R1-F4) — the grant is named through its membership, so the
    # membership is what has to be reachable.
    if not may_be_named(actor, membership):
        raise NotFound()
    require(actor, "grant.delete", membership.organization)
    if grant.effect == Grant.Effect.WITHHOLD:
        _refuse_handing_out(
            actor=actor,
            tenant=tenant,
            organization=membership.organization,
            permissions=frozenset({str(grant.permission)}),
        )
    else:
        _refuse_taking_back(actor=actor, tenant=tenant, membership=membership, verb="restrict")
    died = RevokedGrant(
        grant_id=grant.pk,
        membership_id=membership.pk,
        organization_id=membership.organization_id,
        permission=str(grant.permission),
        effect=str(grant.effect),
    )
    grant.delete()
    if died.effect == Grant.Effect.ALLOW:
        # The third narrowing road. PR1.8's rule is about a read set shrinking
        # and not about which service shrank it, so an `allow` of a read key
        # being withdrawn kicks exactly as a withhold landing does.
        _kick_if_a_read_was_taken(tenant=tenant, membership=membership, permission=died.permission)
    _publish(
        events.GRANT_DELETED,
        tenant=tenant,
        payload={
            "tenant_id": str(tenant.pk),
            "organization_id": str(membership.organization_id),
            "membership_id": str(membership.pk),
            "permission": died.permission,
            "effect": died.effect,
        },
        actor=actor,
    )
    return died


# door: reached only from `manage.py rename_permission`, which is the right and
# only door for it. Renaming a permission across EVERY tenant at once is an
# operator act at an altitude no tenant persona holds — there is no actor, no
# tenant and no node for a route to authorize against — and the precedent is
# `bootstrap_tenant` and `create_first_tenant` beside it. A REST or MCP door here
# would be a credential-holder inside one tenant rewriting the vocabulary of all
# of them.
@service
# rule-13: it declares no `tenant` ON PURPOSE. `@service` writes its audit row per
# tenant, and this call is the deployment acting on its own vocabulary across
# every tenant at once; one row per tenant claiming an actor nobody was would be
# worse than the command's own printed counts.
def rename_permission_rows(*, old: str, new: str) -> dict[str, int]:
    """Move every row naming a renamed permission onto its successor. **Deployment-wide.**

    The rename table (`RENAMED_PERMISSIONS`, per app) keeps an old key ANSWERING
    after a sweep renames it — `resolve_renamed` maps it at `require` time — so
    nothing breaks the day the rename lands. What it does not do is move the
    tenant's own rows: a `Grant` or a `RolePermission` still says the old word,
    and the vocabulary census will report it as a key naming nothing forever.
    This is the one writer that moves them.

    **It declares no `tenant`, so it writes no audit row, and that is the
    honest shape**: it is the deployment's own maintenance act across every
    tenant at once, and one row per tenant claiming an actor nobody was would be
    worse than the command's own output. The shell door
    (`manage.py rename_permission`) prints the counts, and `AuditEntry` is not
    where a schema migration of the permission vocabulary belongs.
    """
    # authz: there is no actor and no tenant — this is the deployment acting on
    # its own vocabulary across every tenant at once, reachable only from a
    # management command (an operator altitude no tenant persona holds, the
    # `bootstrap_tenant` precedent). A `require` here would have to invent both
    # an actor and a node, and the thing being authorized is the operator's
    # shell access.
    moved = {
        # rule-8: DELIBERATELY UNSCOPED, and that is the whole act. A permission
        # key is the deployment's vocabulary, not one tenant's data: the sweep
        # that renamed it renamed it for everybody, so a `for_tenant` here would
        # move one tenant's rows and leave every other tenant's naming a word
        # nothing answers. There is no tenant argument to scope BY — the caller
        # is a management command with no tenant and no actor.
        "grants": Grant.objects.filter(permission=old).update(permission=new),
        # rule-8: the same act on the other table, for the same reason.
        "role_permissions": RolePermission.objects.filter(permission=old).update(permission=new),
    }
    log.info("core.permission.renamed", permission=old, key=new, **moved)
    return moved


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
        require(actor, "tenant.update", root_organization(tenant=tenant))
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
    # **And the sockets already open are hung up on** (R4 F2, house rule 36).
    # A suspension is refused at the next HANDSHAKE and nowhere else, so
    # without this every live connection went on hearing for the life of the
    # connection while the REST door answered 403 to the same credential.
    close_tenant_sockets_on_commit(tenant_id=tenant.pk, reason=KICK_TENANT_SUSPENDED)
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
    # The terminal half of the same sentence (R4 F2, house rule 36). Closing
    # is the one act after which it must never be the case that somebody is
    # still receiving, and a sibling service calling the seam does not make
    # this one call it.
    close_tenant_sockets_on_commit(tenant_id=tenant.pk, reason=KICK_TENANT_CLOSED)
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
    address, which is the identity being established. THREE callers reach it,
    all of them `accounts.adapter`'s and all of them through
    `accept_pending_invitations`: `AccountAdapter.save_user` and
    `SocialAccountAdapter.save_user`, the two signup hooks, where a person
    arriving for the first time is matched against the offers waiting for them,
    and `_platform_login`, which runs on every platform sign-in so that an offer
    made after the account existed is still found. Running it more than once is
    safe rather than doubled: accepting moves the row out of `PENDING`, so the
    next pass finds nothing.
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


def _invited_role(*, tenant: Tenant, role: str | None) -> str:
    """The role key an offer names: the caller's, or whatever a new member gets.

    A function and not a default argument, because a default argument is
    evaluated at import and the role declarations are discovered after the apps
    load. `None` and `""` are different answers and a reader has to be able to
    tell them apart: `None` is "whatever this deployment gives a new member",
    `""` is an offer of a place and no role — which is what a deployment
    declaring no default role has to make, and is refused otherwise.

    The validation is here, before the wall, and not after it as `set_role`'s
    is: the ordering `set_role` keeps is pinned by a test about the CEILING on a
    role somebody already holds, and an invitation has no such row to be above.
    An unknown key here is a malformed offer, and saying so first is the cheaper
    answer.
    """
    resolved = default_role_key() if role is None else role
    _refuse_unknown_role(tenant=tenant, role=resolved, allow_roleless=not default_role_key())
    return resolved


@service
def invite_member(
    *,
    tenant: Tenant,
    email: str,
    role: str | None = None,
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
    where = _placement(tenant=tenant, organization=organization, actor=actor)
    role = _invited_role(tenant=tenant, role=role)
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
                    # `role_label`, never `Membership.Role(value).label`: the
                    # enum holds three keys and a tenant may have made a fourth,
                    # so the old form raised `ValueError` inside the activity
                    # that sends the mail — a custom role's invitation would
                    # have failed to send with a stack trace and no message.
                    "role": role_label(tenant=tenant, key=invitation.role),
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


def _refuse_a_role_that_stopped_existing(*, tenant: Tenant, invitation: Invitation) -> None:
    """The role an offer named may be gone by the time somebody clicks the link.

    A role is a KEY now and two of its three layers can be withdrawn — a tenant
    deletes a custom `Role` row, a product removes a declaration from its
    `roles.py` and deploys — while this row goes on naming it. Landing the
    membership anyway would put somebody in a tenant holding a role that
    resolves to nothing, which reads to them as a broken account and to an
    administrator as a person who is simply there.

    **`Conflict` and not `Invalid`**: the request is perfectly well-formed and
    the accepter chose none of this. The state changed underneath an offer they
    were handed, and the remedy is somebody re-issuing it — which is what the
    sentence says, because "invalid role" would tell the one person in this
    exchange who typed nothing that they typed something wrong.

    `""` is not this case: an offer that named no role is an offer of a place
    and nothing more, and that is a membership `add_membership` writes.
    """
    if invitation.role == "" or invitation.role in known_role_keys(tenant=tenant):
        return
    raise Conflict(
        "The role this invitation named no longer exists in this organization, so there "
        "is nothing for it to make you. Ask whoever invited you to send a new one.",
        remedies=(Remedy("Ask for a new invitation", "self:invitation"),),
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
    `actor_from_request(request)`; the arrival path in `accounts.adapter` builds
    `actor_for(user=<the person arriving>, kind="human")`, because at that
    instant there is a person and no request.

    # authz: the TOKEN is the authorization, and it is a stronger claim than
    # any predicate could make here — the caller proved reach by holding a
    # single-use secret whose hash is on the row, and the doors look the row up
    # by that hash and nothing else. A `require` would have to ask a question
    # about a membership the accepter does not have yet, which is what the
    # invitation is FOR, so it would fail closed on every legitimate
    # acceptance. The actor is kept for the audit row (rule 13's valve shape).

    Called from `accounts.adapter` when a person arrives — **not from a signal**
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
    _refuse_a_role_that_stopped_existing(tenant=tenant, invitation=invitation)
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
