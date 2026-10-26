"""The organization tree."""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser

from apps.core import bridge
from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import Invalid, as_invalid
from apps.core.models import (
    PATH_MAX_DEPTH,
    PATH_MAX_LENGTH,
    PATH_SEPARATOR,
    Organization,
    PathOverflow,
    Tenant,
    child_path,
    decode_path_segment,
    is_descendant_path,
    path_depth,
    subtree_q,
)
from apps.core.service import service
from apps.core.services._hub import MOVE_BATCH_SIZE, MOVE_ORGANIZATION_WORKFLOW, TOO_DEEP
from apps.core.time import now

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
        .filter(subtree_q(organization))
        .order_by("-depth")
        .values_list("depth", flat=True)
        .first()
    )
    return int(deepest) if deepest is not None else organization.depth


# door: no door reaches it; only the move workflow's own activity does, after `move_organization`
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
        .filter(subtree_q(organization))
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


from apps.core.services.sockets import (  # noqa: E402
    KICK_ORGANIZATION_MOVED,
    _members_losing_sight_of,
    close_sockets_on_commit,
)
