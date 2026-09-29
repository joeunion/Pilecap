"""Reads over the tenancy and hierarchy rows — composition both doors share.

House rule 12: nothing here writes, and nothing here returns a wire shape. A
selector hands back a queryset or a row, and `api/routes.py` and `mcp.py` turn
it into schemas — which is what lets the two doors answer with the same rows by
construction rather than by two functions agreeing.

**Why the narrowing is written out here rather than through `visible_to`.**
`ScopedQuerySet.visible_to` filters on an `organization` foreign key, and the
three models below do not have one in the shape it expects:

* `Organization` **is** the node — it has no `organization` column, and
  `visible_to` raises `TypeError` on it by design. Its subtree read is the same
  indexed prefix scan `visible_to` performs, expressed on the row's own `path`.
* `Membership` is person × tenant × org × role and inherits `BaseModel`, not
  `TenantScopedModel`, so it carries no scoped manager at all. Its reads name
  the tenant explicitly and narrow by the hat's subtree through the related
  organization's path.
`Invitation` is the exception that proves the paragraph: it **is** org-scoped
since ADR core-20 — it records the node it was sent from — so its two reads go
through `visible_to` like any other org-scoped read, with no prefix scan written
out here at all.

Every one of them **fails closed on an unresolved hat**, the same way
`for_tenant(None)` and `visible_to(None)` do: no hat reads an empty table, never
the table.

**And since Phase R every one of them ASKS** (ADR core-27, §C6): `actor` is a
required keyword — never optional, because an `actor=None` default is a read
that fails open the first time a caller forgets — and the selector calls
`require(actor, "<kind>.read", ...)` exactly once. **Two questions, two owners,
and they are never merged** (rule 24, BVB-4): `for_tenant`/`visible_to`/the
prefix scan decide WHICH rows, and `require` decides WHETHER this kind, here.
No selector below filters rows by permission.

**Where the question is asked differs between a list and a get, and the order
is the rule** (reach before capability — the ruling `architecture.md` records):

* a `list_` asks at the **acting hat** (`obj=None` → `where_of` → `actor.org`)
  BEFORE it builds the queryset. A list has no row to hide, so the only honest
  answers are the page and `forbidden`.
* a `get_` asks **after the scoped fetch**, with `obj=row`, at the row's own
  node. Outside the subtree the fetch has already raised `NotFound` and the
  capability is never consulted — "not there" and "not yours" stay one answer
  (§C8); inside it, without the key, the answer is `Forbidden`, which is what
  every capability has answered on every door since day one.

A `system` actor passes at `allows` step 1, so activities, commands and the seed
are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import F, Q, QuerySet

from apps.core.actor import Actor
from apps.core.authz import (
    OWNER_ROLE,
    RESERVED_PERMISSIONS,
    Permission,
    defaults_for,
    grantable_permissions,
    memberships_in,
    refusal_sentence,
    require,
    role_declarations,
    vocabulary,
)

# The one assembler of a role's collection out of its delta rows, reached by its
# private name on purpose. `collection()` is the public seam and it reads ONE
# role with ONE query; a list over three layers would be a query per role, and
# the three-statement budget these selectors are pinned to is the reason this
# seam exists at all (`authz._collection_from_rows`' own docstring says so).
from apps.core.authz import _collection_from_rows as collection_from_rows
from apps.core.exceptions import NotFound
from apps.core.models import (
    PATH_SEPARATOR,
    Grant,
    Invitation,
    Membership,
    Organization,
    Role,
    RolePermission,
    Tenant,
    is_descendant_path,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.audit import AuditEntry
    from apps.core.models import ScopedQuerySet


def _subtree(org: Organization | None) -> Q:
    """Everything at or below `org`, as a `Q` over an organization `path`.

    One indexed `LIKE 'prefix.%'` plus an equality, which is exactly what
    `ScopedQuerySet.visible_to` does — restated here because the models below
    reach the path by three different routes and the alternative is three
    slightly different prefix scans.
    """
    if org is None:
        # An impossible predicate rather than `Q()`: an empty `Q` would widen
        # the read to the whole tenant, which is the failure this exists to
        # prevent. Callers already refuse a `None` hat; this is the belt.
        return Q(pk__in=[])
    return Q(path=org.path) | Q(path__startswith=org.path + PATH_SEPARATOR)


# --- the scoped reads, without the capability -----------------------------------
#
# **Why these three exist rather than `get_` calling `list_`.** Before Phase R a
# `get_` was a `list_` with one more filter, and that was exactly right: one
# scoping rule, written once. Now the two ask the capability at DIFFERENT nodes —
# a list at the hat, a get at the row — so a `get_` reaching through its `list_`
# would ask twice and ask the first one in the wrong place, turning a row a
# branch may read into a refusal about the hat. The SCOPING is still written
# once; it is these three functions, and the two public shapes differ only in
# where they ask.
#
# Nothing here is public and nothing here authorizes. A caller outside this
# module reaches a scoped read through the six that ask.


def _organizations_in(*, tenant: Tenant | None, org: Organization | None) -> QuerySet[Organization]:
    """The hat's subtree, scoped and ordered. No capability asked."""
    return Organization.objects.for_tenant(tenant).filter(_subtree(org)).order_by("path")


def _memberships_in(*, tenant: Tenant | None, org: Organization | None) -> QuerySet[Membership]:
    """Every membership inside the hat's subtree, scoped. No capability asked."""
    if tenant is None or org is None:
        return Membership.objects.none()
    subtree = Q(organization__path=org.path) | Q(
        organization__path__startswith=org.path + PATH_SEPARATOR
    )
    return (
        Membership.objects.filter(tenant=tenant)
        .filter(subtree)
        .select_related("user", "organization")
        .order_by("organization__path", "user__email")
    )


def _invitations_in(
    *, tenant: Tenant | None, org: Organization | None
) -> ScopedQuerySet[Invitation]:
    """Every invitation inside the hat's subtree, scoped. No capability asked."""
    return Invitation.objects.for_tenant(tenant).visible_to(org).order_by("-created_at")


def list_organizations(
    *, tenant: Tenant | None, org: Organization | None, actor: Actor
) -> QuerySet[Organization]:
    """The nodes this hat covers: its own and its descendants'.

    Never a parent's and never a sibling's — visibility flows downward only, and
    the org tree is the one place where "I can see it" and "I can act on it" are
    most tempting to widen.
    """
    # THE CAPABILITY, at the hat, BEFORE the queryset: a list has no row to
    # hide, so somebody without `organization.read` here hears that rather than
    # an empty page that looks like an empty tenant.
    require(actor, "organization.read")
    # `for_tenant(None)` already returns nothing and `_subtree(None)` is an
    # impossible predicate, so both halves fail closed without an early return
    # — and the read goes through the scoped manager, which is what house rule 8
    # is watching for.
    return _organizations_in(tenant=tenant, org=org)


def list_organizations_where(
    organizations: QuerySet[Organization], *, actor: Actor, can: str
) -> QuerySet[Organization]:
    """The nodes of `organizations` at which this actor may `can` — `?can=<kind>.<verb>`.

    The move sheet's destinations (and any "where may I do this" picker): the
    same list the hat already sees, narrowed to the nodes where
    `allows(actor, can, node)` answers yes — the data half AND the key's
    predicate, asked AT that node (`where_of` reads an `Organization` as its own
    node). No per-noun destinations read exists, and none is needed.

    **An unknown key is refused `invalid` naming `can`**, never answered with an
    empty page: a misspelled key and "you may do this nowhere" must not look
    the same. Asked once per node the hat covers; `allows` memoizes the
    collection per node on the actor, so the cost is the subtree's size, not a
    query per node per request twice.
    """
    from apps.core.authz import allows, resolve_renamed
    from apps.core.exceptions import Invalid

    # The list it narrows asked this already; asked again here so the narrowing
    # is a read in its own right wherever it is called from (memoized: free).
    require(actor, "organization.read")
    key = resolve_renamed(can.strip())
    if key not in vocabulary():
        raise Invalid(
            {
                "can": [
                    f"{can!r} is not a permission this product has. Send a key from "
                    "the vocabulary — `<kind>.<verb>`, as `GET /permissions/` lists them."
                ]
            }
        )
    nodes = list(organizations.order_by().only("pk", "path", "tenant_id"))
    return organizations.filter(pk__in=[node.pk for node in nodes if allows(actor, key, node)])


# read-open: a row's history is authorized by the ROW's own `<kind>.read`, asked
# below at the row's node — the entries answer only what happened to that row.
def list_history(*, tenant: Tenant | None, actor: Actor, row: Any) -> QuerySet[AuditEntry]:
    """What happened to THIS row, newest first — the History card's read.

    **Over the audit trail, and nothing else** (no second table: the trail is
    already written by `@service` for every successful call, with the row it
    returned as `object_id`). Only `ok` rows: a refused attempt is a security
    fact for the audit reader, not for everybody who may read the row. The
    answer is a queryset for the one paginator; each entry reads as
    `core.schemas.HistoryEntryOut` (`verb`, `actor`, `door`, `changed_fields`).

    **Reach first, then the read**: a row this actor could not have named — a
    sibling branch's, another tenant's — is `NotFound`, never `Forbidden`
    (C8); a reachable row whose kind this actor may not read is `Forbidden`.
    Served by `auditentry_object_history` (tenant, object_id, -created_at).

    DOES NOT COVER — declared: acts on a CHILD row (a ledger line files under
    its own id, not its parent's); `changed_fields` means "sent", not "differed"
    (the trail keeps the keys a call was given, never before- and after-values,
    so a version cannot be restored from it).
    """
    from apps.core.audit import AuditEntry
    from apps.core.authz import kind_of, may_be_named
    from apps.core.models import is_org_scoped

    if tenant is None or getattr(row, "tenant_id", None) != tenant.pk:
        raise NotFound()
    if isinstance(row, Organization):
        # A node is its own reach: within the hat's subtree, as
        # `get_organization` reads it — a sibling branch is not found.
        hat = actor.org
        if hat is None or not is_descendant_path(row.path, hat.path):
            raise NotFound()
    elif is_org_scoped(type(row)) and not may_be_named(actor, row):
        raise NotFound()
    kind = kind_of(type(row))
    if kind is not None:
        require(actor, f"{kind}.read", row)
    return (
        AuditEntry.objects.for_tenant(tenant)
        .filter(object_id=row.pk, outcome=AuditEntry.Outcome.OK)
        .select_related("actor_user")
        .order_by("-created_at", "-id")
    )


def get_organization(
    *, tenant: Tenant | None, org: Organization | None, organization_id: UUID, actor: Actor
) -> Organization:
    """One node by id, from within this hat's subtree.

    A node in a sibling branch — or in another tenant — answers `not_found` and
    never `forbidden`: a refusal that told those two apart would confirm the row
    exists, which is the fact the scoping was hiding.
    """
    found = _organizations_in(tenant=tenant, org=org).filter(pk=organization_id).first()
    if found is None:
        raise NotFound()
    # REACH FIRST, then capability: the fetch above is what makes a sibling
    # branch `not_found`, and this line is what makes a node inside the subtree
    # `forbidden` when the hat holds no `organization.read`. An `Organization`
    # IS its own node, so the question is asked there and not at the hat.
    require(actor, "organization.read", found)
    return found


def list_memberships(
    *, tenant: Tenant | None, org: Organization | None, actor: Actor
) -> QuerySet[Membership]:
    """Who belongs to the part of the tenant this hat covers.

    `select_related` on both the user and the organization because the wire
    shape carries the person's address and the branch's id — without it this is
    two extra queries per row, and the query pin in the tests is what makes that
    a failure rather than a slow page.
    """
    require(actor, "membership.read")
    return _memberships_in(tenant=tenant, org=org)


def get_membership(
    *, tenant: Tenant | None, org: Organization | None, membership_id: UUID, actor: Actor
) -> Membership:
    """One membership by id, from within this hat's subtree. `not_found` otherwise.

    Reach before capability: outside the subtree the fetch answers `not_found`;
    inside it, `membership.read` is asked at the node the row names.
    """
    found = _memberships_in(tenant=tenant, org=org).filter(pk=membership_id).first()
    if found is None:
        raise NotFound()
    require(actor, "membership.read", found)
    return found


def list_invitations(
    *, tenant: Tenant | None, org: Organization | None, actor: Actor
) -> ScopedQuerySet[Invitation]:
    """Every invitation issued inside this hat's subtree, newest first.

    **Narrowed by the hat since ADR core-20.** An invitation records the node it
    was sent from, so it IS held on a branch, and a list that showed every
    branch's offers would tell a branch manager who the branch beside them is
    hiring. This read was tenant-wide while the row carried no organization; the
    change can only ever surprise a caller *narrower*, which is the placement
    law's own safety property.

    `visible_to` is the seam, exactly as house rule 24 requires — the one
    predicate every org-scoped read in the product goes through, rather than a
    prefix scan written out here. It fails closed on an unresolved hat: no hat
    reads an empty table, never the table.
    """
    require(actor, "invitation.read")
    return _invitations_in(tenant=tenant, org=org)


def get_invitation(
    *, tenant: Tenant | None, org: Organization | None, invitation_id: UUID, actor: Actor
) -> Invitation:
    """One invitation by id, from within this hat's subtree. `not_found` otherwise.

    Another branch's invitation is `not_found` and never `forbidden`: the tree's
    answer to "outside what you can see" is that it is not there, so a caller
    cannot map the shape of a subtree they hold nothing on by reading which ids
    refuse differently.
    """
    found = _invitations_in(tenant=tenant, org=org).filter(pk=invitation_id).first()
    if found is None:
        raise NotFound()
    require(actor, "invitation.read", found)
    return found


# --- The permission surface: roles, grants and the vocabulary (P5) ------------
#
# **Three layers in one list, and that is why these return VIEWS.** A role is
# `owner` (the vocabulary itself), a role an app declared in its `roles.py`, or
# a row this tenant made — and a UI that had to fetch three shapes and merge
# them would be a fourth opinion about what a role is. The dataclasses below are
# the merge, done once, in the one module both doors read. They are not wire
# shapes (rule 12): `schemas.py` turns them into `RoleOut`, and the MCP twin
# turns the same objects into the same schema.


@dataclass(frozen=True)
class RoleView:
    """One role, from whichever layer owns it, with its effective collection.

    `permissions` is what somebody holding this role in THIS tenant may do —
    the code layer plus the tenant's include rows minus its exclude rows.
    `default_permissions` is the declaration's own half and is `None` for a
    custom role, which has no code layer to differ from; `added` and `removed`
    are the difference, so a reader can see what this tenant changed without
    computing it.
    """

    key: str
    name: str
    description: str
    kind: str
    permissions: frozenset[str]
    default_permissions: frozenset[str] | None
    added: frozenset[str]
    removed: frozenset[str]
    is_default_for_new_members: bool
    created_at: Any = None
    updated_at: Any = None


@dataclass(frozen=True)
class HeldPermission:
    """One key somebody holds here, and WHERE it came from.

    `via` is `role` when the membership's own role carries it, `grant` when a
    row on that membership does, and `inherited` when it arrives from a
    membership further up the chain — in which case `membership_id` names that
    ancestor row rather than the one asked about. "Why can this person do that"
    is the question every permissions screen opens with, and a set of strings
    cannot answer it.
    """

    key: str
    sentence: str
    via: str
    membership_id: UUID


@dataclass(frozen=True)
class MembershipPermissionsView:
    """Everything one membership holds at its own node, and what was taken away.

    `withheld` is separate rather than subtracted-and-forgotten: a withhold is a
    decision somebody made and the screen that hides it is the screen where
    "why has this stopped working" has no answer.
    """

    membership_id: UUID
    organization_id: UUID
    held: tuple[HeldPermission, ...]
    withheld: tuple[HeldPermission, ...]


def _delta_rows_for(tenant: Tenant | None) -> dict[str, list[tuple[str, str]]]:
    """Every `RolePermission` row in this tenant, grouped by role key. ONE query.

    The whole tenant rather than one role at a time, because `list_roles` builds
    a collection for every layer and `collection()` is one query each — three
    custom roles and two declared ones would be five statements for a list that
    owes two.
    """
    rows: dict[str, list[tuple[str, str]]] = {}
    if tenant is None:
        return rows
    for role_key, effect, permission in (
        RolePermission.objects.for_tenant(tenant)
        .values_list("role_key", "effect", "permission")
        .order_by()
    ):
        rows.setdefault(str(role_key), []).append((str(effect), str(permission)))
    return rows


def _role_view(
    *,
    key: str,
    name: str,
    description: str,
    kind: str,
    rows: list[tuple[str, str]],
    is_default_for_new_members: bool = False,
    created_at: Any = None,
    updated_at: Any = None,
) -> RoleView:
    """Assemble one view out of the code layer and this tenant's delta rows.

    **Both sides of the subtraction are GRANTABLE keys**, or `removed` reports a
    subtraction nobody made. `defaults_for(OWNER_ROLE)` is the whole vocabulary
    — it answers what the owner role IS — while `collection_from_rows` answers
    what an owner may be handed, which excludes the virtual kinds (a kind with
    no table names no row anybody can be given authority over). Differencing the
    two unfiltered put `deployment.configure` in the owner row's `removed` on
    `GET /roles/`, which reads as "this tenant took a capability away from its
    owner" and no tenant did. One `&` against `grantable_permissions()` — the
    one place the exclusion lives — and the two sides are the same population
    again.
    """
    effective = collection_from_rows(key, rows)
    declared = (
        defaults_for(key) & grantable_permissions() if kind in {"owner", "declared"} else None
    )
    return RoleView(
        key=key,
        name=name,
        description=description,
        kind=kind,
        permissions=effective,
        default_permissions=declared,
        added=frozenset(effective - declared) if declared is not None else frozenset(),
        removed=frozenset(declared - effective) if declared is not None else frozenset(),
        is_default_for_new_members=is_default_for_new_members,
        created_at=created_at,
        updated_at=updated_at,
    )


def _declared_views(*, deltas: dict[str, list[tuple[str, str]]]) -> list[RoleView]:
    """`owner` and every role an app declares, in key order. No query."""
    views = [
        _role_view(
            key=OWNER_ROLE,
            name="Owner",
            description=(
                "The tenant itself. Holds every permission this deployment "
                "declares, present and future, and is the only role that may "
                "make somebody else an owner."
            ),
            kind="owner",
            rows=[],
        )
    ]
    for key, declaration in sorted(role_declarations().items()):
        views.append(
            _role_view(
                key=key,
                name=declaration.name,
                description=declaration.description,
                kind="declared",
                rows=deltas.get(key, []),
                is_default_for_new_members=declaration.is_default_for_new_members,
            )
        )
    return views


def list_roles(*, tenant: Tenant | None, actor: Actor) -> list[RoleView]:
    """Every role this tenant can name, from all three layers. **Two statements.**

    One for the tenant's own `Role` rows and one for every `RolePermission` row
    in the tenant; the declared layer is code and costs nothing. Ordered by key,
    which is unique across the three layers by construction —
    `create_role` refuses a key `owner` or a declaration already owns — and is
    therefore total enough to page over.
    """
    require(actor, "role.read")
    deltas = _delta_rows_for(tenant)
    views = _declared_views(deltas=deltas)
    if tenant is not None:
        for row in Role.objects.for_tenant(tenant).order_by("key"):
            views.append(
                _role_view(
                    key=str(row.key),
                    name=str(row.name),
                    description=str(row.description),
                    kind="custom",
                    rows=deltas.get(str(row.key), []),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
    return sorted(views, key=lambda view: view.key)


def get_role(*, tenant: Tenant | None, key: str, actor: Actor) -> RoleView:
    """One role by key, from whichever layer owns it. `not_found` otherwise.

    A role is tenant-wide rather than held on a node, so there is no subtree to
    be outside of: the reach question is the tenant scope, and a key this tenant
    cannot name is simply not there.
    """
    require(actor, "role.read")
    for view in list_roles(tenant=tenant, actor=actor):
        if view.key == key:
            return view
    raise NotFound()


def list_grants(
    *, tenant: Tenant | None, org: Organization | None, membership_id: UUID, actor: Actor
) -> QuerySet[Grant]:
    """The exceptions standing on one membership. Reach, then two capabilities.

    `get_membership` answers `not_found` for a row outside the hat's subtree and
    asks `membership.read` at the row's own node; `grant.read` is then asked for
    the grants themselves, because "who is in this branch" and "what exceptions
    do they carry" are two things a credential can be trusted with separately.
    """
    membership = get_membership(tenant=tenant, org=org, membership_id=membership_id, actor=actor)
    require(actor, "grant.read", membership)
    return (
        Grant.objects.for_tenant(tenant)
        .filter(membership=membership)
        .select_related("membership")
        # THE ROW FACT THE WIRE SHAPE NEEDS, carried on the queryset rather than
        # assembled per row. A grant is positional — it says WHERE as well as
        # WHAT — and the node it stands at is its membership's. Annotated and not
        # materialised because the page is cut by a keyset cursor over this
        # queryset: a door that built a list instead would mint its cursor under
        # a different collection key from the one the MCP twin mints, and a token
        # issued by one door would be refused by the other (`_collection_key`,
        # `apps/core/api/pagination.py`). The SENTENCE, which is a wire word
        # rather than a row fact, stays in the doors where rule 12 puts it.
        .annotate(organization_id=F("membership__organization_id"))
        .order_by("permission")
    )


def get_membership_permissions(
    *, tenant: Tenant | None, org: Organization | None, membership_id: UUID, actor: Actor
) -> MembershipPermissionsView:
    """**The one read every permissions screen needs**: what this person may do here.

    Four statements: `get_membership`, then the three
    `effective_permissions` reads — the chain, its grants, and the delta rows
    for the role keys it names. The algebra is the same one `authz` performs and
    the belt is `test_permissions_doors.py`, which asserts the `held` set equals
    `effective_permissions` exactly; what this adds is the `via` column, which a
    set of strings cannot carry and which is the substance of the screen.

    No second capability beyond `membership.read`: the answer is about the
    membership, and a caller who may read the row may read what it means.
    """
    membership = get_membership(tenant=tenant, org=org, membership_id=membership_id, actor=actor)
    at = membership.organization
    chain = [
        row
        for row in memberships_in(membership.user, tenant)
        if is_descendant_path(at.path, row.organization.path)
    ]
    grants: dict[Any, list[tuple[str, str]]] = {}
    for row_id, permission, effect in (
        Grant.objects.for_tenant(tenant)
        .filter(membership__in=chain)
        .values_list("membership_id", "permission", "effect")
    ):
        grants.setdefault(row_id, []).append((str(permission), str(effect)))
    deltas = _delta_rows_for(tenant)

    words = vocabulary()
    sources: dict[str, HeldPermission] = {}
    withheld: dict[str, HeldPermission] = {}
    reserved = set(RESERVED_PERMISSIONS)
    for row in sorted(chain, key=lambda m: len(m.organization.path), reverse=True):
        # NEAREST FIRST — the longest path on the chain is the deepest node, and
        # `setdefault` below keeps the first writer. A key the membership's own
        # role carries is `role`; the same key arriving from a membership two
        # levels up is `inherited`, and attributing it to the ancestor when the
        # row in front of you already has it would point the screen at the wrong
        # row.
        own = row.pk == membership.pk
        for key in collection_from_rows(str(row.role), deltas.get(str(row.role), [])):
            sources.setdefault(
                key,
                HeldPermission(
                    key=key,
                    sentence=refusal_sentence(key),
                    via="role" if own else "inherited",
                    membership_id=row.pk,
                ),
            )
        for permission, effect in grants.get(row.pk, []):
            if effect == Grant.Effect.ALLOW and permission not in reserved:
                sources[permission] = HeldPermission(
                    key=permission,
                    sentence=refusal_sentence(permission),
                    via="grant" if own else "inherited",
                    membership_id=row.pk,
                )
            elif effect == Grant.Effect.WITHHOLD:
                withheld[permission] = HeldPermission(
                    key=permission,
                    sentence=refusal_sentence(permission),
                    via="grant" if own else "inherited",
                    membership_id=row.pk,
                )

    held = tuple(
        sorted(
            (found for key, found in sources.items() if key not in withheld and key in words),
            key=lambda found: found.key,
        )
    )
    return MembershipPermissionsView(
        membership_id=membership.pk,
        organization_id=membership.organization_id,
        held=held,
        withheld=tuple(sorted(withheld.values(), key=lambda found: found.key)),
    )


def list_permissions(*, actor: Actor) -> list[Permission]:
    """Every key this deployment declares. **No database statement at all.**

    The vocabulary is computed at import from the model registry and the apps'
    own prose, so listing it touches no table — which is what makes it the one
    read a role editor can call on every keystroke. The capability is
    `role.read`: this list is what a role's collection is chosen FROM, and the
    person choosing is the person editing roles.
    """
    require(actor, "role.read")
    return sorted(vocabulary().values(), key=lambda word: word.action)
