"""The tenancy and hierarchy doors: the org tree, memberships, invitations, config.

Every capability here already existed as a service and could be reached from
nothing (rule 42's census carried thirteen doorless `core` services). These are
the doors, and they are thin by construction: unpack the schema, resolve the
rows through `selectors.py`, hand them to the service that owns the write.

**Why these routers do not restate `auth=`, and they are the only ones that do
not.** Every other app writes `Router(tags=[...], auth=API_AUTH)` so that
reading one file tells you what it takes to call its routes. `API_AUTH` lives in
`apps.accounts.auth`, and **`apps.core` may not import `apps.accounts`** — the
layer contract in `pyproject.toml` is a hard one (`import-linter` breaks the
build on it), and `core` is the layer everything else is built on. There are
only three ways out of that and two of them are worse: a bridge registration
would have to be written in `apps/accounts/apps.py`, which is another rung's
territory this wave; a string-path import would dodge the very tooling the
bridge docstring says must not be dodged. So they inherit the API-level
default `config/api.py` sets, which ninja copies onto every operation that
declares none — `operation.auth_callbacks` is therefore non-empty, which is what
house rule 3 reads. `apps/core/tests/test_api_tenancy.py` pins it: every
operation under this prefix carries auth callbacks, and an anonymous caller gets
401. Inheritance that is proven is not inheritance that is silent.

**What is NOT here.** Suspending, resuming and closing a tenant are operator
acts on somebody else's tenant, and they carry a `# door:` valve in
`services.py` saying so. Creating a tenant is the bootstrap's job.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate — the same note `apps/example/api.py` carries. ninja builds a
# Pydantic model out of a route's signature at import time; with postponed
# evaluation every annotation is a string, and a `FilterSchema` parameter comes
# out as an unresolvable forward reference ("QueryParams is not fully defined").
# Every other module in the tree has the future import; an api module that
# declares schema-typed query parameters does not.

from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.core.actor import Actor, actor_from_request
from apps.core.api.docs import Tag
from apps.core.api.pagination import CursorPagination
from apps.core.api.query import ordered_by, searched
from apps.core.exceptions import NotFound
from apps.core.flags import enabled_for
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.requests import TenantRequest
from apps.core.schemas import (
    FlagIn,
    FlagsOut,
    InvitationAcceptIn,
    InvitationFilter,
    InvitationIn,
    InvitationIssuedOut,
    InvitationOut,
    MembershipFilter,
    MembershipIn,
    MembershipOut,
    MembershipRolePatch,
    OrganizationFilter,
    OrganizationIn,
    OrganizationMoveIn,
    OrganizationOut,
    OrganizationPatch,
    TenantSettingsIn,
    TenantSettingsOut,
)
from apps.core.selectors import (
    get_invitation,
    get_membership,
    get_organization,
    list_invitations,
    list_memberships,
    list_organizations,
)
from apps.core.services import (
    accept_invitation,
    add_membership,
    create_organization,
    hash_invitation_token,
    invite_member,
    move_organization,
    rename_organization,
    revoke_invitation,
    revoke_membership,
    set_flag,
    set_role,
    update_tenant_settings,
)

# **The root of `/api/v1/`** (ADR api-2, the owner's 2026-08-24 ruling): the
# first path segment names a RESOURCE, never an app. The routers below already
# carry their resources in their own route paths — `/organizations/`, `/memberships/`,
# `/invitations/`, `/settings/`, `/flags/` — so flattening is an empty PREFIX
# and not a route rewrite. `core` was the honest app name and a dishonest URL:
# nobody calling this API has a concept called "core", and an app label on the
# wire is internal taxonomy the caller has to learn in order to ignore.
# House rule 32 refuses the regression.
PREFIX = ""

# What `?ordering=` may name on each list, and nothing else. Straight into
# `.order_by()` a client could sort by any column and traverse any relation.
ORGANIZATION_ORDERING = ("created_at", "updated_at", "name", "path", "depth")
MEMBERSHIP_ORDERING = ("created_at", "updated_at", "role")
INVITATION_ORDERING = ("created_at", "updated_at", "email", "expires_at")

# What `?q=` searches. Text columns on the row itself; never a related table's.
ORGANIZATION_SEARCH_FIELDS = ("name", "slug")
INVITATION_SEARCH_FIELDS = ("email",)

# **FOUR scope families, not one** (the owner's rulings of 2026-08-24: first the
# split off `core`, then the three-way split of what that left). A tag key is
# the family a scoped token is narrowed to, so `core` — an app label nobody
# calling this API has a concept of — would have handed "read the org tree" and
# "rewrite the tenant's configuration" out as one ceiling.
#
# THE THREE-WAY SPLIT, and what made it earn itself. `organizations` was TAG-1's
# deliberate deferral: three resources under one key, waiting for a persona that
# demonstrated wanting them apart. FT-1′ was that persona (readouts.md,
# 2026-08-24) — from the seat, "the narrowest token that does the job" was still
# a token that could create an organization, grant a role and issue an
# invitation, because all three were bought with the one string. So they are
# three families: the tree, the role grants, and the invitation lifecycle.
#
# THE KEYS ARE MEANING-NAMED, which is the EXCEPTION and not the default — the
# choosing pattern is in `django-conventions` §6, and this is its third
# invocation after `messaging` and `tenant-settings`. `memberships:write` on a
# credential travelling without its API is a string nobody can place; `roles`
# says what is being trusted, and the owner's own reason is a domain one — under
# ONC certification the access-control vocabulary IS role-based, so `roles:write`
# maps one-to-one onto the language the certified product is audited in.
# `org-structure` is the same move: `organizations:write` reads like "may touch
# anything about organizations", which is exactly the ceiling being retired.
#
# KEY IS NOT PATH. The routes below still spell `/organizations/`,
# `/memberships/` and `/invitations/` — a URL says what the resource is, a tag
# key says what a credential is trusted with, and the two answer different
# questions. Nothing moved.
#
# AND A KEY FREEZES the day a token could name it — see
# `apps/core/api/scopes.py::FROZEN_FAMILIES`. This split is recorded there as
# the sanctioned migration and is the LAST cheap rename this vocabulary gets.
TAGS = {
    "org-structure": Tag(
        "Organizational structure",
        "A tenant's organization tree: the branches, divisions or franchisees it "
        "is divided into, how they nest, and what each one is called. Reads are "
        "narrowed to the subtree your `X-Org` hat covers and writes are bounded "
        "by the role you hold over the branch they land in — so a branch manager "
        "reshapes their own branch and cannot see or rename anything outside it. "
        "Who belongs to which branch is a different section: see **Roles & "
        "members**.",
        plane="administrative",
        plane_note=(
            "the tenant's organization tree: its branches, how they nest, and what each one is "
            "called. The structure only; who is in it is `roles`."
        ),
    ),
    "roles": Tag(
        "Roles & members",
        "Who belongs to which part of the tenant, and as what. Granting, "
        "changing and removing a person's role — the access-control decisions "
        "themselves, kept apart from the tree they are made against so a "
        "credential trusted to reshape the structure is not thereby trusted to "
        "promote anybody. Nobody grants above their own ceiling, and a role is "
        "bounded at the branch it lands in.",
        plane="administrative",
        plane_note=(
            "who belongs to which part of the tenant, and as what. Kept apart from the tree it "
            "is granted against, so a credential trusted to reshape the structure is not thereby "
            "trusted to promote anybody."
        ),
    ),
    "invitations": Tag(
        "Invitations",
        "Bringing somebody into the tenant: issuing an invitation at a branch "
        "and a role, revoking one, and the link that accepts it. An invitation "
        "records the branch it was issued from and the membership lands exactly "
        "there, so an invitation can never be a way to place somebody above the "
        "person who sent it. Accepting is a browser act — the link names the "
        "invitation and the session names the person — and it is the one "
        "capability here with no machine-door twin.",
        plane="administrative",
        plane_note=(
            "bringing somebody in: issuing an invitation at a branch and a role, revoking one, "
            "and the link that accepts it."
        ),
    ),
    "tenant-settings": Tag(
        "Tenant settings",
        "The tenant's own configuration: its name, time zone and locale, the "
        "free-form `settings` object your application keeps its own "
        "configuration in, and the feature flags that turn product behaviour on "
        "and off. Configuration applies to everybody in the tenant, so changing "
        "any of it asks for `admin` or `owner` over the tenant as a whole "
        "rather than over one branch of it.",
        plane="administrative",
        plane_note=(
            "the tenant's name, time zone, locale, feature switches and the free-form settings "
            "object."
        ),
    ),
}

# **One app, four sections, and no operation in two of them.** The shape is the
# one `apps/accounts/api.py` already uses for its three: each specific router
# names its own group, and the mount at the bottom of this file names NOTHING.
# ninja ACCUMULATES a nested router's tags downward (`Router.set_api_instance`:
# the inherited tags plus the template's own), so a tag on the mount would put a
# second one on every operation beneath it and print the whole app twice in the
# navigation — the owner read exactly that on `accounts`, 2026-08-24, and house
# rule 41 refuses it now. The mount stays bare so this cannot come back.
#
# FOUR ROUTERS RATHER THAN PER-ROUTE TAGS, which is the same reason there were
# two: an operation's tag is what bounds the credential that reaches it, and a
# tag written route by route is a tag somebody forgets on the fifth route. The
# router is the declaration; a route below it says nothing about its family.
#
# No router restates `auth=` — see the module docstring; all four inherit the
# API-level default that `config/api.py` sets.
org_structure_router = Router(tags=["org-structure"])
roles_router = Router(tags=["roles"])
invitations_router = Router(tags=["invitations"])
settings_router = Router(tags=["tenant-settings"])


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as.

    The same shape every app's door uses. Authentication has guaranteed the
    user; nothing has guaranteed the tenant, because a signed-in person with no
    membership resolves to `None` — and a write with no tenant is refused rather
    than guessed at.

    Whether the actor *may* do the thing is not decided here: `services.py`
    calls `authz.require`. A permission check in this function would be a second
    copy of the rule, one per door.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


def _hat(actor: Actor) -> Organization:
    """The acting organization, refused rather than defaulted when there is none.

    Every read below is a subtree read and every subtree needs a root to start
    from. `visible_to(None)` and its siblings already fail closed by returning
    nothing, but an empty list is a confusing way to say "you sent no hat" — so
    the doors say it.
    """
    if actor.org is None:
        raise HttpError(403, "This request resolved no acting organization.")
    return actor.org


# --- Organizations ------------------------------------------------------------


@org_structure_router.get(
    "/organizations/", response=list[OrganizationOut], url_name="organization-list"
)
@paginate(CursorPagination)
def list_organizations_route(
    request: TenantRequest,
    filters: Query[OrganizationFilter],
    q: str | None = None,
    ordering: str = "path",
) -> QuerySet[Organization]:
    """List organizations

    List the organizations you can see, in tree order.

    You get your acting organization — the one the `X-Org` request header names
    — and every organization beneath it. Organizations above yours, and those in
    other branches, are not returned at all.

    Narrow the list with `name` (matches part of a name) or `depth` (an exact
    level in the tree). Search names and slugs with `q`. Sort with `ordering`,
    which accepts `created_at`, `updated_at`, `name`, `path` or `depth`, each
    optionally prefixed with `-` to reverse it; any other value is rejected with
    `invalid` and the response lists what you may sort by. Walk it with
    `?cursor=` and `?limit=`.

    The default sort is `path`, which returns the list in tree order — every
    organization after the one it hangs from — so you can build a tree from a
    single response without a second request.

    Returns `{"items": [...], "has_more": ..., "next_cursor": ...}`. Send the
    `next_cursor` back as `?cursor=` for the next page and stop when `has_more`
    is false; `count` is `null` unless you send `?include_count=true`.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `path` and `depth` are on the ordering allow-list because a client sorting a
    tree wants them; they are on no `In` schema, because the services own those
    columns (house rule 24) and a client that could sort by one must still not
    be able to set it.
    """
    actor, tenant = _acting(request)
    organizations: QuerySet[Organization] = list_organizations(tenant=tenant, org=_hat(actor))
    organizations = filters.filter(organizations)
    organizations = searched(organizations, q, fields=ORGANIZATION_SEARCH_FIELDS)
    return ordered_by(organizations, ordering, allowed=ORGANIZATION_ORDERING, default="path")


@org_structure_router.get(
    "/organizations/{organization_id}/",
    response=OrganizationOut,
    url_name="organization-detail",
)
def get_organization_route(request: TenantRequest, organization_id: UUID) -> Organization:
    """Retrieve an organization

    Fetch one organization by id.

    The organization must be your acting organization or one beneath it.
    Anything else — a different branch, a different tenant, an id that matches
    nothing at all — answers `not_found`.

    That is deliberate and it is the same answer in all three cases: telling
    "no such organization" apart from "not yours" would confirm that an
    organization with that id exists, which is exactly what you are not
    entitled to know.

    Refusals you can get here:

    * `404 not_found` — that organization is outside the part of the tree you
      can see, or nothing has that id. The two answer identically on
      purpose, so a guessed id tells you nothing.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    return get_organization(tenant=tenant, org=_hat(actor), organization_id=organization_id)


@org_structure_router.post(
    "/organizations/", response={201: OrganizationOut}, url_name="organization-create"
)
def create_organization_route(
    request: TenantRequest, payload: OrganizationIn
) -> Status[Organization]:
    """Create an organization

    Create an organization under a parent you administer.

    Send `parent_id`, `name` and `slug`. There is no way to create an
    organization with no parent: every tenant already has exactly one root, made
    when the tenant was, and the rest of the tree hangs off it.

    `slug` is the handle you will later put in the `X-Org` header to act as this
    organization. It must be unique within your tenant; a duplicate answers
    `400 invalid` with the clash named in `errors`, and nothing is created.

    The parent must be your acting organization or one beneath it, and you must
    hold the `admin` or `owner` role over it — held on that organization, or on
    any organization above it.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed, that `slug` is already
      taken in this tenant, or the tree would go deeper than its limit.
      `errors` names the clash; nothing is created.
    * `403 forbidden` — you do not hold `admin` or `owner` over that
      organization, held on it or on one above it. Ask somebody who does.
    * `404 not_found` — the `parent_id` is outside the part of the tree you
      can see, or nothing has that id.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The parent is resolved through the selector before the service is called, so
    a sibling branch's id can never reach `create_organization` at all: the
    reachability question is answered on the way in rather than inside the
    write.
    """
    actor, tenant = _acting(request)
    parent = get_organization(tenant=tenant, org=_hat(actor), organization_id=payload.parent_id)
    return Status(
        201,
        create_organization(
            tenant=tenant,
            parent=parent,
            name=payload.name,
            slug=payload.slug,
            actor=actor,
        ),
    )


@org_structure_router.patch(
    "/organizations/{organization_id}/",
    response=OrganizationOut,
    url_name="organization-update",
)
def rename_organization_route(
    request: TenantRequest, organization_id: UUID, payload: OrganizationPatch
) -> Organization:
    """Rename an organization

    Rename an organization.

    Send `name`. That is the only thing this changes.

    The slug is not renameable here: it is the value clients put in the `X-Org`
    header, so changing it would break every stored header, saved link and
    script pointed at this organization. Moving an organization to a different
    parent is a separate operation — `POST /organizations/{id}/move/`.

    You must hold `admin` or `owner` over this organization, held on it or on
    any organization above it.

    Refusals you can get here:

    * `400 invalid` — `name` was empty or longer than 255 characters.
    * `403 forbidden` — you do not hold `admin` or `owner` over that
      organization, held on it or on one above it. Ask somebody who does.
    * `404 not_found` — that organization is outside the part of the tree you
      can see, or nothing has that id. The two answer identically on
      purpose, so a guessed id tells you nothing.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    organization = get_organization(tenant=tenant, org=_hat(actor), organization_id=organization_id)
    return rename_organization(
        tenant=tenant, organization=organization, name=payload.name, actor=actor
    )


@org_structure_router.post(
    "/organizations/{organization_id}/move/",
    response=OrganizationOut,
    url_name="organization-move",
)
def move_organization_route(
    request: TenantRequest, organization_id: UUID, payload: OrganizationMoveIn
) -> Organization:
    """Move an organization

    Move an organization, and everything under it, to a new parent.

    Send `new_parent_id`. Everything beneath the organization moves with it.

    **The move is accepted here and completes shortly afterwards.** The
    organization returned by this call is the organization as it stands *now*,
    with its old position — re-read it to see the new one. Large subtrees take
    longer than small ones.

    You must hold `admin` or `owner` over **both** ends: the organization's
    current parent and the new parent. Either one you do not administer answers
    `forbidden`, and either one outside the part of the tree you can see answers
    `not_found`.

    Four moves are impossible and answer `invalid`: moving the root, moving
    across tenants, moving an organization underneath itself or underneath one
    of its own descendants, and any move that would make the tree deeper than
    its limit. Asking for a second move of the same organization while the first
    is still running is refused rather than queued behind the first.

    Refusals you can get here:

    * `400 invalid` — the move is one of the four that cannot happen: moving
      the root, moving across tenants, moving an organization under itself
      or under one of its own descendants, or a move that would make the
      tree deeper than its limit.
    * `403 forbidden` — you do not hold `admin` or `owner` over BOTH ends —
      the current parent and the new one.
    * `404 not_found` — either end is outside the part of the tree you can
      see.
    * `409 conflict` — a move of this organization is already running. Wait
      for it to finish; re-read the organization to see where it landed.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    A POST on a sub-path rather than a PATCH that sets `parent_id`, because a
    move is a verb with a durable run behind it: `apply_organization_move` takes
    `select_for_update` over the whole subtree and rewrites its materialized
    paths in batches. Both ends resolve through the selector before the service
    sees them, which is what makes a sibling branch `not_found` rather than
    `forbidden` on the way in.
    """
    actor, tenant = _acting(request)
    hat = _hat(actor)
    organization = get_organization(tenant=tenant, org=hat, organization_id=organization_id)
    new_parent = get_organization(tenant=tenant, org=hat, organization_id=payload.new_parent_id)
    return move_organization(
        tenant=tenant,
        organization=organization,
        new_parent=new_parent,
        actor=actor,
        started_by=actor.user,
    )


# --- Memberships --------------------------------------------------------------


@roles_router.get("/memberships/", response=list[MembershipOut], url_name="membership-list")
@paginate(CursorPagination)
def list_memberships_route(
    request: TenantRequest,
    filters: Query[MembershipFilter],
    ordering: str = "role",
) -> QuerySet[Membership]:
    """List memberships

    List the people who belong to the organizations you can see.

    Covers your acting organization and everything beneath it. Each entry says
    which person (`user_id`, `user_email`), which organization
    (`organization_id`) and what role they hold there.

    Narrow with `role` or `organization_id`. Sort with `ordering`, which accepts
    `created_at`, `updated_at` or `role`, each optionally prefixed with `-`; any
    other value is rejected. Walk it with `?cursor=` and `?limit=`.

    There is no free-text search on this list. To find one person, filter by
    role or organization and walk the list, or fetch the membership by id.

    Returns `{"items": [...], "has_more": ..., "next_cursor": ...}`. Send the
    `next_cursor` back as `?cursor=` for the next page and stop when `has_more`
    is false; `count` is `null` unless you send `?include_count=true`.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    No `q` because the only column worth searching is the address, which lives
    on the user row rather than this one, and a search that reached across that
    join is a join nobody sized.
    """
    actor, tenant = _acting(request)
    memberships: QuerySet[Membership] = list_memberships(tenant=tenant, org=_hat(actor))
    memberships = filters.filter(memberships)
    return ordered_by(memberships, ordering, allowed=MEMBERSHIP_ORDERING, default="role")


@roles_router.post("/memberships/", response={201: MembershipOut}, url_name="membership-create")
def add_membership_route(request: TenantRequest, payload: MembershipIn) -> Status[Membership]:
    """Add a membership

    Give a person a role in one of your organizations.

    Send `user_id`, `role`, and optionally `organization_id`. **Omit it and the
    membership is created on the organization you are acting in** — the one
    `X-Org` names, or your default organization when you send no `X-Org`. It is
    never created at the top of the tenant on your behalf: a grant is made where
    you sent it from. Set `is_default` if this should be the membership used
    when the person names no organization.

    Roles are `owner`, `admin` and `member`, in that order of seniority.

    **You cannot grant a role above your own.** An `admin` may make somebody an
    `admin` or a `member`, never an `owner`, and nobody can grant a role in a
    part of the tree they hold no role over. Both answer `forbidden`, and the
    message says which of the two it was so you can tell "wrong place" from
    "too senior".

    A `user_id` that matches nobody answers `not_found`, and so does an
    `organization_id` outside the part of the tree you can see.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed, or `role` is not one
      this product knows. `errors` names the fields.
    * `403 forbidden` — you do not administer that organization, or the `role`
      you asked for is higher than your own there. Nobody grants above
      themselves.
    * `404 not_found` — the person or the organization is outside the part of
      the tree you can see, or nothing has that id.
    * `409 conflict` — that person already holds a membership on that
      organization. Change the role instead.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The escalation wall lives in `_refuse_escalation`, beside the write it
    guards, so the MCP twin gets the same two refusals for the same two reasons
    without a second copy of the rule.
    """
    actor, tenant = _acting(request)
    hat = _hat(actor)
    organization = (
        get_organization(tenant=tenant, org=hat, organization_id=payload.organization_id)
        if payload.organization_id is not None
        else None
    )
    user = get_user_model().objects.filter(pk=payload.user_id).first()
    if user is None:
        raise NotFound()
    return Status(
        201,
        add_membership(
            user=user,
            tenant=tenant,
            organization=organization,
            is_default=payload.is_default,
            role=payload.role,
            actor=actor,
        ),
    )


@roles_router.patch(
    "/memberships/{membership_id}/role/",
    response=MembershipOut,
    url_name="membership-update",
)
def set_role_route(
    request: TenantRequest, membership_id: UUID, payload: MembershipRolePatch
) -> Membership:
    """Change a member's role

    Change the role someone holds.

    Send `role` — one of `owner`, `admin` or `member`.

    The same ceiling applies as when granting a role in the first place: you
    cannot set a role above the one you hold yourself over that organization,
    and you cannot change a membership in a part of the tree you hold no role
    over. Both answer `forbidden`.

    Demoting the tenant's last `owner` is refused too: a tenant with no owner
    is a tenant nobody can administer.

    A membership outside the organizations you can see answers `not_found`,
    which is also the answer for an id that matches nothing.

    Refusals you can get here:

    * `400 invalid` — `role` is not one this product knows.
    * `403 forbidden` — you do not administer that organization, or the new
      role is above your own there, or the membership you are changing is
      already above your own.
    * `404 not_found` — that membership is outside the part of the tree you
      can see, or nothing has that id.
    * `409 conflict` — it is the last `owner` membership in the tenant.
      Promote somebody else first.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    membership = get_membership(tenant=tenant, org=_hat(actor), membership_id=membership_id)
    return set_role(tenant=tenant, membership=membership, role=payload.role, actor=actor)


@roles_router.delete(
    "/memberships/{membership_id}/",
    response={204: None},
    url_name="membership-delete",
)
def revoke_membership_route(request: TenantRequest, membership_id: UUID) -> tuple[int, None]:
    """Remove a membership

    Remove a person's membership.

    Answers `204` with no body: there is no membership left to return.

    Any WebSocket connections that person has open are closed as part of this,
    so access ends immediately rather than when they next reload.

    You must hold `admin` or `owner` over the organization the membership sits
    on, and you cannot remove somebody more senior than you are — both answer
    refused. Removing the tenant's last `owner` is refused too: a tenant
    with no owner is a tenant nobody can administer.

    A membership outside the organizations you can see answers `not_found`.

    Refusals you can get here:

    * `403 forbidden` — you do not administer that organization, or the
      membership is above your own role there. Nobody removes above
      themselves.
    * `404 not_found` — that membership is outside the part of the tree you
      can see, or nothing has that id.
    * `409 conflict` — it is the last `owner` membership in the tenant. Make
      somebody else an owner first.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    membership = get_membership(tenant=tenant, org=_hat(actor), membership_id=membership_id)
    revoke_membership(tenant=tenant, membership=membership, actor=actor)
    return 204, None


# --- Invitations --------------------------------------------------------------


@invitations_router.get("/invitations/", response=list[InvitationOut], url_name="invitation-list")
@paginate(CursorPagination)
def list_invitations_route(
    request: TenantRequest,
    filters: Query[InvitationFilter],
    q: str | None = None,
    ordering: str = "-created_at",
) -> QuerySet[Invitation]:
    """List invitations

    List the invitations issued inside the part of the tree you are acting in.

    Each entry says who was invited, **into which organization**, as what role,
    how the invitation stands (`pending`, `accepted` or `revoked`), when it
    expires and, if it was taken up, when.

    **`X-Org` narrows this list.** An invitation records the organization it was
    sent from, and you see the ones at or below your acting organization —
    so a branch manager sees their own branch's offers and not the branch beside
    them. Send `X-Org` naming a node you belong to, or omit it and act in your
    default organization.

    Narrow with `status`, `email` or `organization_id`. Search addresses with
    `q`. Sort with
    `ordering`, which accepts `created_at`, `updated_at`, `email` or
    `expires_at`, each optionally prefixed with `-`; any other value answers
    `invalid`. Walk it with `?cursor=` and `?limit=`.

    **Invitation tokens are never on this response.** A pending invitation's
    token is a credential — whoever holds it becomes a member — so it is
    returned only once, by the call that issues it. If you have lost one, issue
    a new invitation; nothing will show you the old one again.

    Returns `{"items": [...], "has_more": ..., "next_cursor": ...}`. Send the
    `next_cursor` back as `?cursor=` for the next page and stop when `has_more`
    is false; `count` is `null` unless you send `?include_count=true`.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Narrowed by the acting organization since ADR core-20 gave an invitation a
    landing node. It was tenant-wide while the row carried none — a read that
    can only ever have got narrower, which is the placement law's own direction.
    """
    actor, tenant = _acting(request)
    invitations: QuerySet[Invitation] = list_invitations(tenant=tenant, org=_hat(actor))
    invitations = filters.filter(invitations)
    invitations = searched(invitations, q, fields=INVITATION_SEARCH_FIELDS)
    return ordered_by(invitations, ordering, allowed=INVITATION_ORDERING, default="-created_at")


@invitations_router.post(
    "/invitations/", response={201: InvitationIssuedOut}, url_name="invitation-create"
)
def invite_member_route(request: TenantRequest, payload: InvitationIn) -> Status[Any]:
    """Invite a person

    Invite a person into one of your organizations. Returns the invitation and
    its token.

    Send `email` and, optionally, `role` (defaults to `member`) and
    `organization_id`.

    **Omit `organization_id` and the invitation is placed in the organization
    you are acting in** — the one `X-Org` names, or your default organization
    when you send no `X-Org`. It is never placed at the top of the tenant on
    your behalf: an invitation sent from a branch is an offer of a place in that
    branch, and when the person accepts, that is exactly where their membership
    lands. Name an `organization_id` to place it somewhere else inside the part
    of the tree you can see; a node outside that answers `not_found`.

    **The `token` in the response is the only copy that will ever exist.** Only
    a hash of it is stored, so nothing here can show it to you again. Put it in
    the link you send the invitee. If you lose it, issue a new invitation.

    An invitation email is also sent for you.

    Inviting somebody who already has a pending invitation **in the same
    organization** replaces that invitation rather than failing — the older one
    is withdrawn and the new token is the one that works. An invitation standing
    in a different organization is untouched: two branches may each have a live
    offer out to the same person, because they are offers of two places.

    Two separate permissions apply and both answer `forbidden`, and **both are
    asked about the organization the invitation is placed in**: you must hold
    `admin` or `owner` there to invite anybody at all, and you cannot invite
    somebody at a role above your own there.

    Refusals you can get here:

    * `400 invalid` — the `email` is missing or malformed, or `role` is not
      one this product knows. `errors` names the fields.
    * `403 forbidden` — you are not an owner or an administrator of the
      organization this invitation is placed in, or the `role` you asked for is
      above your own there.
    * `404 not_found` — the `organization_id` is outside the part of the tree
      you can see, or nothing has that id.
    * `409 conflict` — that address already has an invitation waiting in that
      organization, or already belongs to it.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The mail goes out through `comms` on commit, so a refused write sends
    nothing at all.

    ADR core-20. The placement is resolved here exactly the way
    `POST /memberships/` resolves its own — through `get_organization` against
    the acting hat's subtree — because they are the same act with a delay, and
    two doors that resolved a node two different ways would disagree about who
    can be placed where the first time one of them was edited.
    """
    actor, tenant = _acting(request)
    hat = _hat(actor)
    organization = (
        get_organization(tenant=tenant, org=hat, organization_id=payload.organization_id)
        if payload.organization_id is not None
        else None
    )
    invitation, token = invite_member(
        tenant=tenant,
        email=payload.email,
        role=payload.role,
        organization=organization,
        invited_by=actor.user,
        actor=actor,
    )
    return Status(
        201,
        InvitationIssuedOut(invitation=InvitationOut.from_orm(invitation), token=token),
    )


# Declared BEFORE the by-id route below: ninja mounts `{invitation_id}` with a
# string converter, so `/invitations/accept/` would otherwise be matched as an
# invitation whose id is the word "accept" — a 405, not a 404, which is the
# most confusing possible answer. Reading order matches matching order.
@invitations_router.post(
    "/invitations/accept/", response=MembershipOut, url_name="invitation-accept"
)
def accept_invitation_route(request: TenantRequest, payload: InvitationAcceptIn) -> Membership:
    """Accept an invitation

    Redeem an invitation token and become a member of the tenant that sent it.

    Send the `token` from the invitation link, and nothing else. **Nothing in
    the request says who is accepting** — whoever your credential identifies
    becomes the member, and there is no way to accept on somebody else's behalf.
    So the person joining has to be signed in themselves, whether that is a
    browser session or their own bearer token.

    You do not need to be a member of the tenant that invited you; that is the
    point. The invitation is looked up across the whole product by its token.

    **You land exactly where the invitation was sent from.** An invitation
    records the organization it was issued in, and that is the organization your
    membership is created on — not the top of the tenant. Nothing in this
    request can change it: the placement was decided by the person who invited
    you, bounded by what they themselves could reach.

    Returns the membership that was created — the person, the organization and
    the role the invitation named.

    **This capability is not available as an MCP tool**, and it is the only one
    that is not: accepting is the moment a person joins, and an agent acting for
    somebody who has not joined yet has nobody to act for.

    Refusals you can get here:

    * `403 forbidden` — nobody is signed in. Sign the person in, then retry.
    * `404 not_found` — that token matches no invitation waiting to be accepted.
    * `409 conflict` — the invitation has already been accepted, or was
      withdrawn.
    * `400 invalid` — the invitation has expired. Ask for a new one.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    ADR core-16. Accepting with the token's own user would be a bootstrap circle
    — the token predates the membership the invitation creates — and accepting
    on a named user's behalf is an impersonation shape, so the machine door
    simply does not carry this one. `quality/rules.yaml` records it as rule 17's
    single capability-level exemption.

    **The old contract half said "the one operation here that a bearer token
    cannot perform", and that was false**: this route asks only
    `request.user.is_authenticated`, which `ApiTokenAuth` satisfies, and a
    bearer token accepting an invitation gets a 200. What is true is the
    rule-17 exemption above — no MCP twin — and that is what it now says. The
    failure mode is the one this method exists to catch: a sentence about the
    door written from a memory of the design rather than from the code three
    lines below it.

    The lookup is by hash of the plaintext, over pending rows in every tenant,
    because somebody accepting an invitation is by definition not yet a member
    of the tenant that sent it.
    """
    user = request.user
    if not user.is_authenticated:
        raise HttpError(403, "Accepting an invitation needs a signed-in person.")
    token_hash = hash_invitation_token(payload.token)
    invitation = (
        Invitation.objects.filter(token_hash=token_hash, status=Invitation.Status.PENDING)
        .select_related("tenant")
        .first()
    )
    if invitation is None:
        raise NotFound()
    return accept_invitation(
        tenant=invitation.tenant,
        invitation=invitation,
        user=user,
        actor=actor_from_request(request),
    )


@invitations_router.delete(
    "/invitations/{invitation_id}/",
    response=InvitationOut,
    url_name="invitation-delete",
)
def revoke_invitation_route(request: TenantRequest, invitation_id: UUID) -> Invitation:
    """Withdraw an invitation

    Withdraw an invitation, so its token stops working.

    Answers with the invitation itself rather than an empty body: it is still
    listed after this, with `status` moved to `revoked`, and seeing the new
    status is more useful than seeing nothing.

    Withdrawing an invitation that is already withdrawn succeeds and changes
    nothing, so a retry after a timeout is safe.

    **You must hold `admin` or `owner` over the organization the invitation was
    sent from** — the one it will place its person in. An invitation issued
    outside the part of the tree you are acting in is not visible here at all,
    and answers `not_found` rather than `forbidden`, as does one belonging to
    another tenant.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      organization this invitation is placed in.
    * `404 not_found` — no invitation you can see has that id.
    * `409 conflict` — it has already been accepted, so there is nothing left
      to withdraw.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    invitation = get_invitation(tenant=tenant, org=_hat(actor), invitation_id=invitation_id)
    return revoke_invitation(tenant=tenant, invitation=invitation, actor=actor)


# --- The tenant's own configuration -------------------------------------------


@settings_router.get("/settings/", response=TenantSettingsOut, url_name="settings-detail")
def get_settings_route(request: TenantRequest) -> Tenant:
    """Retrieve tenant settings

    Read this tenant's configuration.

    Returns the tenant's `name`, `slug` and `status`, the `timezone` and
    `locale` used to render dates and text for its people, and `settings` — a
    free-form JSON object your application can keep its own configuration in.

    Feature flags are not included here. They resolve against deployment-wide
    defaults as well as this tenant's overrides, so they answer a different
    question; read them from `GET /flags/`.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `timezone` and `locale` are columns rather than `settings` keys because the
    product renders with them: a typo in a JSON key would be a silently wrong
    timestamp, where a typo'd column is a refusal.
    """
    _actor, tenant = _acting(request)
    return tenant


@settings_router.put("/settings/", response=TenantSettingsOut, url_name="settings-update")
def update_settings_route(request: TenantRequest, payload: TenantSettingsIn) -> Tenant:
    """Update tenant settings

    Change this tenant's configuration.

    Send any of `values`, `timezone` and `locale`; anything you leave out is
    left alone.

    **`values` is merged, not replaced.** Send one key and one key changes;
    every other key in `settings` survives. To remove a key, send it with the
    value `null`.

    `timezone` must be a name from the IANA time zone database, such as
    `Europe/Lisbon`. Anything else is refused rather than being stored
    and failing later when a date is rendered.

    You must hold `admin` or `owner` over the tenant as a whole — not merely
    over the organization you are acting as.
    Configuration applies to everybody in the tenant, so administering one
    branch of it is not enough.

    Refusals you can get here:

    * `400 invalid` — a value is outside what the setting accepts. `errors`
      names the fields and nothing is changed.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant, or the request resolved no tenant.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    return update_tenant_settings(
        tenant=tenant,
        values=payload.values,
        timezone=payload.timezone,
        locale=payload.locale,
        actor=actor,
    )


@settings_router.get("/flags/", response=FlagsOut, url_name="flags-detail")
def get_flags_route(request: TenantRequest) -> FlagsOut:
    """List feature flags

    Read every feature flag for this tenant, resolved.

    Returns `{"flags": {"<name>": true|false, ...}}` covering every flag this
    deployment declares, whether or not this tenant has an opinion about it — a
    flag the tenant has not set resolves to the deployment's default.

    Flags turn product behaviour on and off. They are not permissions, and they
    are not a substitute for one: everything about who may do what is decided by
    roles.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `core/flags.py` says the same thing at greater length, and the reason is
    that using a flag as a permission is how a rollout becomes a security
    boundary nobody tested.
    """
    _actor, tenant = _acting(request)
    return FlagsOut(flags=enabled_for(tenant))


@settings_router.put("/flags/{name}/", response=FlagsOut, url_name="flags-update")
def set_flag_route(request: TenantRequest, name: str, payload: FlagIn) -> FlagsOut:
    """Set a feature flag

    Turn one feature flag on or off for this tenant, or clear it.

    Send `{"enabled": true}` or `{"enabled": false}` to set the flag for this
    tenant.

    **Send `{"enabled": null}` to clear it.** That is not the same as `false`:
    it removes this tenant's override so the flag follows the deployment-wide
    default again, which is what finishing a rollout looks like.

    Answers with the whole resolved flag map, so you can see the state you are
    now in without a second request.

    You must hold `admin` or `owner` over the tenant as a whole, or the answer
    is `forbidden`.

    Refusals you can get here:

    * `400 invalid` — the body was not `{"value": true}`, `{"value": false}`
      or `{"value": null}`.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant, or the request resolved no tenant.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    return FlagsOut(
        flags=enabled_for(set_flag(tenant=tenant, name=name, enabled=payload.enabled, actor=actor))
    )


# --- The mount ---------------------------------------------------------------
# What `config/api.py` discovers. All four routers above hang off it at the
# EMPTY prefix, because each route already spells its own resource segment
# (`/organizations/`, `/memberships/`, `/invitations/`, `/settings/`) and
# `PREFIX = ""` puts them at the root of `/api/v1/`: splitting the file into
# sections moved no path and renamed no `url_name` — not when it became two and
# not when the three-way split made it four. It carries no tag of its own, and
# that is load-bearing — see the note beside the routers.
router = Router()
router.add_router("", org_structure_router)
router.add_router("", roles_router)
router.add_router("", invitations_router)
router.add_router("", settings_router)
