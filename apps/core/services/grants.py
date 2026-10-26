"""The hand-out family: roles and grants (ADR core-25, ADR core-26)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from uuid import UUID

from apps.core import bridge, events
from apps.core.actor import Actor
from apps.core.authz import (
    OWNER_ROLE,
    RESERVED_PERMISSIONS,
    VIRTUAL_KINDS,
    collection,
    defaults_for,
    grantable_permissions,
    may_be_named,
    refusal_sentence,
    require,
    role_declarations,
    vocabulary,
)
from apps.core.exceptions import Conflict, Invalid, NotFound, as_invalid
from apps.core.models import Grant, Invitation, Membership, Role, RolePermission, Tenant
from apps.core.schemas import GrantOut, MembershipOut, RoleOut, event_payload
from apps.core.service import service
from apps.core.services._hub import _landing_node, log, root_organization

# --- The hand-out family: roles and grants (ADR core-25, ADR core-26) ---------


def _publish(
    name: str, *, tenant: Tenant, out: RoleOut | MembershipOut | GrantOut, actor: Actor
) -> bool:
    """Say that something happened, in the transaction it happened in; `True` when anybody listened.

    The payload is the row's `Out` through `event_payload` (ADR core-26, rule 87).
    """
    emit = bridge.listener(bridge.EMIT)
    if emit is None:
        # `event_name`, not `event`: structlog's first argument is `event`.
        log.info("core.event.unpublished", event_name=name, tenant_id=str(tenant.pk))
        return False
    emit(name=name, tenant=tenant, payload=event_payload(out), actor=actor)
    return True


def _role_out(*, tenant: Tenant, key: str) -> RoleOut:
    """The role as the role doors answer it, read with no viewer; the write already authorized."""
    # Lazily: `core.selectors` imports this module for the root and the key.
    from apps.core.selectors import _declared_views, _delta_rows_for, _role_view

    deltas = _delta_rows_for(tenant)
    for view in _declared_views(deltas=deltas):
        if view.key == key:
            return RoleOut.of(view)
    row = Role.objects.for_tenant(tenant).get(key=key)
    return RoleOut.of(
        _role_view(
            key=str(row.key),
            name=str(row.name),
            description=str(row.description),
            kind="custom",
            rows=deltas.get(key, []),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


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
        Membership.objects.for_tenant(tenant)
        .filter(role=role_key)
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
    _publish(events.ROLE_CREATED, tenant=tenant, out=_role_out(tenant=tenant, key=key), actor=actor)
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
        out=_role_out(tenant=tenant, key=str(role.key)),
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
        events.ROLE_UPDATED, tenant=tenant, out=_role_out(tenant=tenant, key=role_key), actor=actor
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
    worn_by = Membership.objects.for_tenant(tenant).filter(role=key).count()
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
    as_it_stood = _role_out(tenant=tenant, key=key)
    RolePermission.objects.for_tenant(tenant).filter(role_key=key).delete()
    role.delete()
    _publish(events.ROLE_DELETED, tenant=tenant, out=as_it_stood, actor=actor)
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
    it through `get_membership(org=<hat>)`, so a row outside the hat's
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
        out=GrantOut.of(grant, sentence=refusal_sentence(permission)),
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
    as_it_stood = GrantOut.of(grant, sentence=refusal_sentence(str(grant.permission)))
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
    _publish(events.GRANT_DELETED, tenant=tenant, out=as_it_stood, actor=actor)
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


from apps.core.services.memberships import _refuse_handing_out, _refuse_taking_back  # noqa: E402
from apps.core.services.sockets import (  # noqa: E402
    KICK_PERMISSIONS_NARROWED,
    close_sockets_on_commit,
)
