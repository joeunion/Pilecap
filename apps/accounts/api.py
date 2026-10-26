"""The accounts doors: people, tokens, home-realm discovery, and SSO configuration.

Only a signed-in person may mint a token: a token that could mint would survive its own revocation.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Status
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH, MINT_AUTH, SessionRequired, authenticated_by_token
from apps.accounts.models import ApiToken, SsoConnection, User
from apps.accounts.schemas import (
    RealmIn,
    RealmOut,
    SsoConnectionIn,
    SsoConnectionOut,
    SsoConnectionPatch,
    TokenIn,
    TokenIssuedOut,
    UserOut,
)
from apps.accounts.selectors import get_member, get_realm_for_email, list_sso_connections
from apps.accounts.services import (
    create_sso_connection,
    deactivate_user,
    disable_sso_connection,
    erase_user,
    issue_token,
    revoke_token,
    update_sso_connection,
)
from apps.core.actor import actor_from_request
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.acting import acting
from apps.core.api.docs import Tag, also_refuses, refuses
from apps.core.api.scopes import ceiling_from_request, effective_scopes
from apps.core.requests import TenantRequest
from apps.core.surfaces import STAFF, of_request
from apps.core.throttling import AnonRateThrottle, BaseThrottle

# The root of `/api/v1/`: this app's resources live at three prefixes of their own.
PREFIX = ""

# One tag per resource, never one per app (ADR api-1).
TAGS = {
    "users": Tag(
        "People",
        "Taking a person's access away. **Deactivation is reversible and "
        "erasure is not**: deactivating switches an account off and changes "
        "nothing else, while erasing replaces the person's email address with "
        "an unreachable one and cannot be undone by anybody. Each act has two "
        "routes — `/users/me/...` acts on you and can name nobody else, and "
        "`/users/{user_id}/...` acts on someone in the tenant you are "
        "signed in to. Both routes behave identically and allow the same "
        "callers: you, over your own account, or an administrator of your "
        "whole tenant. Nothing here deletes an account, so records that "
        "refer to the person keep reading correctly afterwards.",
        plane="administrative",
        plane_note=(
            "taking a person's access away: deactivation, which is reversible, and erasure, "
            "which is not. You may always act on your own account."
        ),
    ),
    "tokens": Tag(
        "API tokens",
        "Bearer tokens, so a program can call this API as you. Minted from a "
        "signed-in browser session and pinned to the tenant you were acting in, "
        "shown **exactly once**, and revoked by a route that keeps the record so "
        "what the token did is still attributable. There is no route that reads "
        "a token back.",
        plane="everyday",
        plane_note=(
            "your own API tokens: mint one, revoke one. Nothing reads a token's secret back; you "
            "can only ever revoke your own."
        ),
    ),
    "auth": Tag(
        "Sign-in & identity providers",
        "Where an email address signs in, asked before anybody is signed in — "
        "and the tenant's own identity-provider configuration, which decides who "
        "may join it and at what role. That makes it the most powerful thing in "
        "this API, and it is owner-or-administrator only. No client secret is "
        "ever in a response.",
        plane="administrative",
        plane_note=(
            "how this tenant signs people in, and which identity providers it trusts. `POST "
            "/auth/realm/` answers before anybody is signed in: it says where an email address "
            "should go."
        ),
    ),
}

tokens_router = Router(tags=["tokens"], auth=API_AUTH)


# --- People: `me/` names only the caller; `{user_id}` resolves a member through `get_member` ---

users_router = Router(tags=["users"], auth=API_AUTH)


@users_router.post("/me/deactivate/", response=UserOut, url_name="me-deactivate")
def deactivate_me_route(request: TenantRequest) -> User:
    """Deactivate your account

    Switch your own account off. This can be undone.

    Send no body. Everything currently signed in as you stops working
    immediately: your browser session ends, every API token you hold starts
    answering `401`, and any open WebSocket connection is closed rather than
    left running until it happens to drop.

    Nothing is deleted and your email address is unchanged. Your API tokens are
    not revoked — they start working again if an administrator switches your
    account back on, and you sign back in to the same tenant. There is no
    route that switches an account back on; ask an administrator.

    Use `POST /users/me/erase/` instead if you want the change to be permanent.

    Returns your account: `is_active` is now `false` and everything else is as
    it was.

    Refusals you can get here:

    * `403 no_acting_scope` — you are signed in but the request resolved no tenant.
      Send `X-Tenant` naming one you belong to.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return deactivate_user(user=cast(User, request.user), actor=actor, tenant=tenant)


@users_router.post("/me/erase/", response=UserOut, url_name="me-erase")
def erase_me_route(request: TenantRequest) -> User:
    """Erase your account

    Erase your own account. **This cannot be undone by anybody.**

    Send no body. Your email address is replaced with an unreachable
    `erased+<random>@erased.invalid` address, your password is made unusable,
    every API token you hold is revoked for good, any admin access you had is
    removed, your open WebSocket connections are closed, and your account with
    the identity provider you sign in through is switched off. You cannot sign
    in again, and neither can anybody acting as you.

    Your account record and your tenant memberships are kept. That is
    deliberate: records elsewhere that say who did something — who approved a
    refund, who changed a setting — have to keep reading correctly, and deleting
    the account would turn every one of them into a dangling reference. The
    account cannot be used regardless.

    Returns your account with the anonymised address on it, which is your
    confirmation that the erasure happened.

    Refusals you can get here:

    * `409 conflict` — you are the only owner of a tenant, and erasing you
      would leave it with nobody who can administer it. The message names each
      tenant. Make somebody else an owner there first, then retry.
    * `403 no_acting_scope` — you are signed in but the request resolved no tenant.
      Send `X-Tenant` naming one you belong to.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return erase_user(user=cast(User, request.user), actor=actor, tenant=tenant)


@users_router.post("/{user_id}/deactivate/", response=UserOut, url_name="user-deactivate")
def deactivate_user_route(request: TenantRequest, user_id: UUID) -> User:
    """Deactivate a person's account

    Switch someone's account off. This can be undone.

    Send no body; `user_id` in the path is the person. The same thing happens to
    them as when they switch their own account off: their browser session ends,
    their API tokens start answering `401` without being revoked, and their open
    WebSocket connections are closed. Nothing is deleted and their email address
    is unchanged, so the change can be reversed by switching the account back on.

    **Who may call this:** you, over your own account, or an administrator or
    owner of the whole tenant you are signed in to. Administrators of one
    part of a larger tenant cannot switch off people in another part —
    switching an account off affects the person everywhere, so it takes
    tenant-wide authority.

    Returns the person's account: `is_active` is now `false`.

    Refusals you can get here:

    * `404 not_found` — nobody with that id belongs to the tenant you are
      signed in to. You get this whether or not such an account exists anywhere,
      so it is not a way to check. If you meant somebody in a different
      tenant, send `X-Tenant` naming that one.
    * `403 forbidden` — the person is in your tenant, but you are neither
      them nor an administrator of the whole tenant. Ask an owner or
      administrator to do it.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    Not-there and not-yours are one answer (`get_member`).
    """
    actor, tenant = acting(request)
    user = get_member(tenant=tenant, user_id=user_id, actor=actor)
    return deactivate_user(user=user, actor=actor, tenant=tenant)


@users_router.post("/{user_id}/erase/", response=UserOut, url_name="user-erase")
def erase_user_route(request: TenantRequest, user_id: UUID) -> User:
    """Erase a person's account

    Erase someone's account. **This cannot be undone by anybody.**

    Send no body; `user_id` in the path is the person. Their email address is
    replaced with an unreachable `erased+<random>@erased.invalid` address, their
    password is made unusable, every API token they hold is revoked for good,
    any admin access is removed, their open WebSocket connections are closed,
    and their account with the identity provider is switched off. Neither they
    nor anybody acting as them can sign in again.

    Their account record and tenant memberships are kept, so records
    elsewhere that say who did something keep reading correctly. The account
    cannot be used regardless.

    **Who may call this:** you, over your own account, or an administrator or
    owner of the whole tenant you are signed in to. Administrators of one
    part of a larger tenant cannot erase people in another part — an erasure
    reaches the person in every tenant they belong to and with the identity
    provider as well, so it takes tenant-wide authority.

    Returns the person's account with the anonymised address on it, which is
    your confirmation that the erasure happened.

    Refusals you can get here:

    * `409 conflict` — the person is the only owner of a tenant, and erasing
      them would leave it with nobody who can administer it. The message names
      each tenant. Make somebody else an owner there first, then retry.
    * `404 not_found` — nobody with that id belongs to the tenant you are
      signed in to. You get this whether or not such an account exists anywhere,
      so it is not a way to check.
    * `403 forbidden` — the person is in your tenant, but you are neither
      them nor an administrator of the whole tenant.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    user = get_member(tenant=tenant, user_id=user_id, actor=actor)
    return erase_user(user=user, actor=actor, tenant=tenant)


# --- Tokens -------------------------------------------------------------------


def _own_tokens(request: TenantRequest) -> QuerySet[ApiToken]:
    """The only way this table is read through the door: the caller's own rows.

    `ApiToken` is not tenant-scoped — a token may be pinned to a tenant or
    resolve one per request — so the narrowing that matters is the user.
    """
    return ApiToken.objects.filter(user=cast(User, request.user))


@tokens_router.post("/", auth=MINT_AUTH, response={201: TokenIssuedOut}, url_name="token-create")
@refuses(
    "session_required",
    "invalid",
    "forbidden",
    "no_acting_scope",
    "idempotency_key_reuse",
    "in_progress",
    "rate_limited",
)
def create_token(request: TenantRequest, payload: TokenIn) -> Status[TokenIssuedOut]:
    """Mint an API token

    Create a bearer token for yourself, so a program can call this API as you.

    **You must be signed in with a browser session to call this, and the request
    needs a CSRF token** — send the `csrftoken` cookie's value in the
    `X-CSRFToken` header, as you would for any other session-authenticated
    write. A bearer token cannot mint another bearer token: a token that could
    would survive being revoked, because its offspring would keep working.

    **So no token reaches this, and no scope changes that.** A bearer token here
    is refused `session_required` — before anything looks at what the token
    carries, because looking would produce the wrong answer: "your token needs a
    wider scope" would be true of no token at all, and the wider token would
    have to be minted here, by a token, which is the thing that is refused. If
    you are holding a token and you need another one, there are two doors that
    mint and neither of them is this one from where you are standing: a
    signed-in browser session, and the shell command on a machine that runs this
    deployment.

    Send a `name` — anything you will recognise later in a list of tokens, such
    as `"nightly export"` — and `scopes`, which says what the token is allowed
    to reach.

    **`scopes` has no default and leaving it out is refused.** A token you are
    about to paste into somebody else's software should be as narrow as the job
    needs, and a default would quietly make it as wide as you are. Send a list
    of names, each one a section of this API followed by `:read` or `:write` —
    `"widgets:read"`, `"tenant-settings:write"`. The sections are the headings
    this reference page groups operations under, and every operation says which
    scope it needs in its own description; `/llms.txt` lists the whole
    vocabulary in one place. Two forms are refused rather than guessed at: an
    empty list (a token that can do nothing is a mistake, not a narrow one),
    and a name this deployment does not have. If the token really should be
    able to do everything you can, say so out loud: send `["*"]`.

    **Within a section, the write scope includes the read.** Asking for
    `"widgets:write"` gets you reading widgets as well, so you do not have to
    remember the pair — and `effective_scopes` in the response shows you both,
    so what the token can do is on the screen rather than in your head. It
    works one way only, and never across sections: a read scope never allows a
    write, and `"widgets:write"` says nothing at all about any other section.

    The response tells you two things about what you asked for. `scopes` is
    what the token carries — `null` when you sent `["*"]`, meaning no limit.
    `effective_scopes` is the part of it your own role can back today, so a
    scope you asked for that is missing from that list is one the role
    underneath will refuse anyway, and you find that out here rather than in a
    log six hours later.

    A scope only ever narrows. It cannot grant: your role and the rules on each
    record still decide, so a token scoped to a section you are not allowed to
    write to is refused exactly as you would be.

    **The token is in the response, once.** Nothing reads it back: there is no
    route that returns it, and it is stored only as a hash, so if you lose it
    you mint another and revoke this one. Send it on later requests as
    `Authorization: Bearer <token>`.

    The token is pinned to the tenant you are acting in when you mint it — the
    one `X-Tenant` names, or your default. It can only ever act in that tenant.
    A later request that sends no `X-Tenant` acts in the pin, which is the
    ordinary way to use it; a later request that sends `X-Tenant` naming a
    *different* tenant is refused with `403 addressing_header_not_honoured`,
    never quietly answered as the pin — the token authenticated, and what was
    refused is where it asked to act.

    Returns `201` with the token's `id`, `name`, `tenant_id`, `created_at`,
    `scopes`, `effective_scopes` and the `token` itself. `last_used_at` and
    `revoked_at` are `null` on a token this new.

    Refusals you can get here:

    * `403 session_required` — you called with a bearer token instead of a
      browser session. No token can make this call, so there is no wider one to
      go and mint; sign in, or ask somebody with a shell on the server.
    * `403 no_acting_scope` — you are signed in, and the request resolved no tenant.
      Send `X-Tenant` naming a tenant you belong to.
    * `400 invalid` — the `name` was empty or longer than 200 characters, or
      `scopes` was missing, empty, or named something this API does not have.
      `errors` says which.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    A tenantless session is refused (`acting`): a token pinned to nothing would audit as platform.
    """
    if authenticated_by_token(request):  # pragma: no cover - MINT_AUTH answers first
        raise SessionRequired(
            "A token cannot mint another token; sign in to do that. A token that could "
            "mint would survive being revoked, because its offspring would keep working."
        )
    actor, tenant = acting(request)
    ceiling = ceiling_from_request(payload.scopes)
    token, plaintext = issue_token(
        user=cast(User, request.user),
        tenant=tenant,
        name=payload.name,
        # The minter, so the birth row names who minted it (ADR core-22).
        actor=actor,
        scopes=ceiling,
    )
    return Status(
        201,
        TokenIssuedOut(
            id=token.pk,
            name=token.name,
            tenant_id=token.tenant_id,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
            revoked_at=token.revoked_at,
            scopes=token.scopes,
            token=plaintext,
            effective_scopes=effective_scopes(
                user=actor.user,
                tenant=tenant,
                org=actor.org,
                scopes=token.scopes,
            ),
        ),
    )


@tokens_router.delete("/{token_id}/", response={204: None}, url_name="token-revoke")
def revoke(request: TenantRequest, token_id: UUID) -> Status[None]:
    """Revoke an API token

    Stop one of your own API tokens working, immediately and permanently.

    `token_id` in the path is the token. You can only revoke your own: a token
    belonging to anybody else answers `404`, whether or not it exists.

    It takes effect at once: the next request carrying that token answers `401`.
    Every WebSocket connection you currently have open is closed as well — all
    of them, not only the ones this token opened, because a connection that was
    already authenticated would otherwise keep receiving until the client hung
    up. Reconnect with a credential that still works. There is no route that
    un-revokes a token; mint a new one.

    The token's record is kept, so anything it did is still attributable
    afterwards. Nothing about it can be read back, and the secret never could
    be.

    Send no body. Answers `204` with an empty body.

    You may call this with the token you are revoking. That is deliberate: a
    program that discovers its own credential has leaked can disable it without
    finding a person, and doing so reaches nothing else.

    Refusals you can get here:

    * `404 not_found` — no token of yours has that id.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    token = get_object_or_404(_own_tokens(request), pk=token_id)
    # The pinned tenant puts the death row beside the birth row (ADR core-22).
    revoke_token(token=token, tenant=token.tenant, actor=actor_from_request(request))
    return Status(204, None)


# --- Home-realm discovery (anonymous) and SSO configuration (owner-or-admin) ---

auth_router = Router(tags=["auth"], auth=API_AUTH)

# What `?ordering=` may name on the connection list, and nothing else.
SSO_ORDERING = ("created_at", "updated_at", "name", "status")

# Named so a test can reach it; typed as the base because `list` is invariant.
REALM_THROTTLES: list[BaseThrottle] = [AnonRateThrottle()]


@auth_router.post(
    "/realm/",
    response=RealmOut,
    url_name="realm-discover",
    # rule-3: pre-auth realm discovery has no credential to require; the answer discloses
    # nothing — `get_realm_for_email` is byte-identical for every unclaimed address (ADR ident-6).
    auth=None,
    throttle=REALM_THROTTLES,
)
def discover_realm(request: HttpRequest, payload: RealmIn) -> RealmOut:
    """Find where an address signs in

    Ask where an email address should be sent to sign in, before anybody is
    signed in.

    **This route takes no credential** — a login form has to answer this
    question before it has one. Send `{"email": "..."}` and you get back:

    * `authorize_url` — where to send the person's browser. Always present.
    * `method` — always `sso`; every sign-in goes through the same provider.
    * `connection_id` — present only when the address's domain belongs to an
      identity provider one of our customers has configured, in which case
      `authorize_url` already carries a hint that skips the provider chooser.

    The answer deliberately tells you nothing else. An address whose domain
    nobody has claimed, an address whose provider has been switched off, and an
    address nobody has ever heard of all get the same reply, so this cannot be
    used to discover which companies use this product.

    It is rate-limited per calling address more tightly than the rest of the
    API, for the same reason.

    Refusals you can get here:

    * `400 invalid` — the `email` was missing, empty or longer than 320
      characters.
    * `429 rate_limited` — you are asking too fast. Wait for the `Retry-After`
      seconds and try again.

    ---

    Throttled per address: the one anonymous route, so enumeration is slowed, not prevented.
    `method` keeps `password` in its vocabulary for a product that restores the door (ADR ident-6).
    """
    realm = get_realm_for_email(payload.email, surface=of_request(request) or STAFF)
    return RealmOut(
        method=cast(Literal["sso", "password"], realm.method),
        connection_id=realm.connection_id,
        authorize_url=realm.authorize_url,
    )


def _sso_connections(request: TenantRequest) -> QuerySet[SsoConnection]:
    """The acting tenant's connections, for the LIST. Asks `sso_connection.read` at the root."""
    actor, tenant = acting(request)
    return list_sso_connections(tenant=tenant, actor=actor)


def _sso_connection_reach(request: TenantRequest) -> QuerySet[SsoConnection]:
    """The REACH for a detail route: tenancy only, no capability asked here.

    Not the list selector: that would ask `sso_connection.read` before the write's own key.
    """
    return SsoConnection.objects.for_tenant(request.tenant).prefetch_related("domains")


@auth_router.get(
    "/sso-connections/",
    response=list[SsoConnectionOut],
    url_name="sso-connection-list",
)
@paginate(CursorPagination)
def list_sso_connections_route(
    request: TenantRequest,
    ordering: str = "-created_at",
) -> QuerySet[SsoConnection]:
    """List identity providers

    List the identity providers configured for the tenant you are acting in.

    An identity provider is what lets a company sign its own people in to this
    product with their own login. This is the tenant's list of them, newest
    first by default; `?ordering=` accepts `created_at`, `updated_at`, `name` or
    `status`, each with `-` in front of it for descending.

    Paginated with `?cursor=` and `?limit=`:
    `{"items": [...], "has_more": ..., "next_cursor": ...}`, and `count` only
    when you send `?include_count=true`.

    **No client secret is ever in a response**, from this route or any other.
    Each entry carries `has_client_secret` so you can see that one is stored
    without seeing it.

    `status` is `active` or `disabled`; a disabled provider signs nobody in but
    keeps its record and its claim on its email domains.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return ordered_by(
        _sso_connections(request), ordering, allowed=SSO_ORDERING, default="-created_at"
    )


@auth_router.post(
    "/sso-connections/",
    response={201: SsoConnectionOut},
    url_name="sso-connection-create",
)
def create_sso_connection_route(
    request: TenantRequest, payload: SsoConnectionIn
) -> Status[SsoConnection]:
    """Add an identity provider

    Configure an OpenID Connect provider so a tenant's people can sign in with
    their own company login.

    **Only an owner or an administrator of the tenant may call this.** It is the
    strictest permission in this API: whoever configures a provider decides who
    may become a member of the tenant and at what role.

    Send the provider's `issuer` URL, its `client_id` and `client_secret`, a
    `name` you will recognise, and `email_domains` — the domains this provider
    owns, such as `acme.com`. Optionally `default_role` (the role key people who
    arrive through it join at; the deployment's default role unless you say
    otherwise, and it never changes an existing membership) and `enforced` (when
    `true`, people in those domains may not sign in any other way).

    **An email domain belongs to exactly one provider across the whole
    product.** Claiming one somebody else already has is refused.

    **Claiming a domain reserves it; it does not route anybody yet.** Nobody
    signs in through this provider until an operator of this deployment confirms
    that your organisation owns the domain — ask them to, and they will tell you
    when it is done. Public mail providers such as `gmail.com` are refused here
    outright: an identity provider claims the domains its organisation owns.

    **`default_role` may not be higher than your own role in the tenant.** A
    provider is a grant that happens later, so an administrator cannot configure
    one that turns arrivals into owners.

    The secret is stored encrypted and no route returns it. The response
    reports `has_client_secret: true` instead.

    Returns `201` with the provider. `protocol` is `oidc`; nothing else is
    accepted. `verified_domains` is empty until an operator verifies, and it is
    the list that says which of your `email_domains` route a sign-in today.

    Refusals you can get here:

    * `403 no_acting_scope` — the request resolved no tenant. Send `X-Tenant`
      naming one you belong to.
    * `403 forbidden` — you are not an owner or administrator of this tenant.
      **Measured at the tenant's root**: an administrator of one branch
      administers that branch, and may not configure the tenant's identity
      provider.
    * `400 invalid` — a field is missing or malformed, or `protocol` was
      anything but `oidc`. `errors` names the fields.
    * `409 conflict` — one of the `email_domains` is already claimed.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connection = create_sso_connection(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        issuer=payload.issuer,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        email_domains=payload.email_domains,
        protocol=payload.protocol,
        default_role=payload.default_role or "",
        enforced=payload.enforced,
    )
    return Status(201, connection)


@auth_router.patch(
    "/sso-connections/{connection_id}/",
    response=SsoConnectionOut,
    url_name="sso-connection-update",
)
@also_refuses("enforced_without_provider")
def update_sso_connection_route(
    request: TenantRequest, connection_id: UUID, payload: SsoConnectionPatch
) -> SsoConnection:
    """Update an identity provider

    Change the settings of one identity provider this tenant has configured.

    `connection_id` in the path is the provider. **Owner or administrator of the
    tenant only**, like creating one.

    Send only the fields you are changing — `name`, `issuer`, `client_id`,
    `client_secret`, `email_domains`, `default_role`, `enforced`. Anything you
    leave out is left alone, and **leaving out `client_secret` keeps the stored
    one**: it is the only thing omitting it can mean, since nothing can read it
    back to re-send it.

    Sending `email_domains` **replaces** the list rather than adding to it, and
    the same one-domain-one-provider rule applies. A domain you keep keeps its
    verification; one you remove and send again later starts unverified, and an
    operator has to confirm it before it routes anybody again.

    Returns the provider as it now is. No secret is ever in the response.
    `verified_domains` says which of the claims route today.

    Refusals you can get here:

    * `404 not_found` — no provider with that id belongs to the tenant you are
      acting in.
    * `403 no_acting_scope` — the request resolved no tenant.
    * `403 forbidden` — you are not an owner or administrator of this tenant.
      **Measured at the tenant's root**: an administrator of one branch
      administers that branch, and may not configure the tenant's identity
      provider.
    * `400 invalid` — a field you sent is malformed, or `default_role` is above
      your own role. `errors` names the fields.
    * `409 conflict` — one of the `email_domains` is already claimed elsewhere.
    * `409 enforced_without_provider` — you switched `enforced` on before this
      provider was set up at the identity platform; requiring it now would leave
      its people no way to sign in. Read the provider back until `sync_state` is
      `applied`, then switch it on.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    `enforced` in the answer is what the identity platform has applied, not only
    what you asked for: it reads `false` with `sync_state` `pending` until the
    change lands.
    """
    actor, tenant = acting(request)
    connection = get_object_or_404(_sso_connection_reach(request), pk=connection_id)
    return update_sso_connection(
        tenant=tenant,
        actor=actor,
        connection=connection,
        name=payload.name,
        issuer=payload.issuer,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        email_domains=payload.email_domains,
        default_role=payload.default_role,
        enforced=payload.enforced,
    )


@auth_router.delete(
    "/sso-connections/{connection_id}/",
    response={204: None},
    url_name="sso-connection-disable",
)
def disable_sso_connection_route(request: TenantRequest, connection_id: UUID) -> Status[None]:
    """Disable an identity provider

    Stop an identity provider signing anybody in, without deleting it.

    `connection_id` in the path is the provider. **Owner or administrator of the
    tenant only.** Send no body; answers `204` with an empty body.

    From then on, a sign-in through that provider is refused — including one
    already in flight — and if it was `enforced`, that stops applying, so the
    people it covered can sign in another way instead of being locked out.

    **The provider's record and its claim on its email domains are kept.**
    Deleting them would free those domains for somebody else to claim while this
    tenant is halfway through moving, and would take with them the record of who
    arrived through the provider. It still appears in the list, with `status`
    `disabled`. There is no route that re-enables one; configure a new provider.

    Refusals you can get here:

    * `404 not_found` — no provider with that id belongs to the tenant you are
      acting in.
    * `403 no_acting_scope` — the request resolved no tenant.
    * `403 forbidden` — you are not an owner or administrator of this tenant.
      **Measured at the tenant's root**: an administrator of one branch
      administers that branch, and may not configure the tenant's identity
      provider.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connection = get_object_or_404(_sso_connection_reach(request), pk=connection_id)
    disable_sso_connection(tenant=tenant, actor=actor, connection=connection)
    return Status(204, None)


# --- The mount: no tag of its own — nested ninja tags accumulate, and rule 41 refuses two ---
router = Router(auth=API_AUTH)
router.add_router("/users/", users_router)
router.add_router("/tokens/", tokens_router)
router.add_router("/auth/", auth_router)
