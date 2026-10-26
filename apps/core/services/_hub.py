"""What two or more sections share, and what they need at import time."""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser

from apps.core import bridge
from apps.core.actor import Actor
from apps.core.exceptions import Conflict, Invalid, as_invalid
from apps.core.log import get_logger
from apps.core.models import ROOT_SEGMENT, Organization, Tenant
from apps.core.roads import road
from apps.core.service import service

log = get_logger("apps.core.services")

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


# door: no door reaches it; only this tree's own hands do — `manage.py seed` and the bootstrap
@service
# rule-13: no tenant exists to scope its audit row to until this call returns it
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
    _ask_for_an_identity_home(tenant=tenant)
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


def _ask_for_an_identity_home(*, tenant: Tenant) -> None:
    """Ask the identity app to home this tenant's sign-in realm, on commit.

    Through `core.bridge`, for `invite_member`'s reason: `accounts` sits above
    `core`, so the start is looked up by name rather than imported. `find` and
    not `get`, because until the identity app registers the name a tenant is
    still a tenant — the start is a no-op that says so on a log line, never a
    refusal to create the tenant.
    """
    ensure_home = bridge.find(bridge.ENSURE_IDENTITY_HOME)
    if ensure_home is None:
        log.info(
            "core.tenant.identity_home_not_wired",
            tenant=tenant.slug,
            detail="Nothing registered the identity-home start; the tenant has no realm yet.",
        )
        return
    ensure_home(tenant=tenant)


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


@road("tenant_root", example="apps/core/policies.py::may_archive")
# rule-16: the marked road `tenant_root`, a read every app calls by this name
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
    kind asks at the hat and resolves no node — so what asks here now is
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
    Root or hat is an open question and this is right under either
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
    hat" cannot come to mean two things one service apart. The owner's
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


from apps.core.services.memberships import add_membership  # noqa: E402
