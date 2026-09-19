"""The accounts doors: people, tokens, home-realm discovery, and SSO configuration.

Four resources, at four places in the URL space, from one app:

* `/api/v1/users/` — taking a person's access away: reversibly
  (`deactivate`) or permanently (`erase`), each in a self-serve `me/` form and
  an admin-initiated `{user_id}` form;
* `/api/v1/tokens/` — how a person gives a machine a way in, and takes it back;
* `/api/v1/auth/realm/` — where an address signs in, asked before anybody is
  signed in. The one route in this app a stranger may call;
* `/api/v1/auth/sso-connections/` — a tenant's own identity provider. The most
  privileged rows in the product, and owner-or-admin only.

**The user routes are a door onto services that already existed** (ADR
ident-6). `erase_user` and `deactivate_user` were built, tested and audited, and
before this door the only way to reach either was a Python shell — which is
house rule 42's whole complaint, and it is why `erase_user` was one of the four
names in accounts' doorless census.

**What this door does NOT claim**, stated rather than left to
be discovered: the erasure it exposes is *today's* erasure. `erase_user`
anonymises the `User` row, revokes the tokens, drops the admin keys, closes the
sockets and asks the identity platform to deactivate the account — and it does
not sweep whatever else in the tree points at that person. The **contract** is
what this door owns and it does not change when the sweep deepens: the same
route, the same body, the same refusals. Closing the residue is wave C's, and
the trigger to re-read these tests is its merge.

**The interesting rule on tokens is on the first route.** Only a signed-in
person may mint one: a token that can mint tokens is a token that cannot be
revoked — revoke it and its offspring keep working — so the machine door is
closed there even though it is open everywhere else. That is a narrowing of the
API default, which a route may do; it is not `auth=None`, which it may not.

The plaintext of a token is in the response body once. It is not stored, not
logged, and not recoverable; `manage.py issue_token` is the same operation for
someone with a shell instead of a session.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Status
from ninja.errors import HttpError
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
from apps.accounts.selectors import get_member, list_sso_connections, realm_for_email
from apps.accounts.services import (
    create_sso_connection,
    deactivate_user,
    disable_sso_connection,
    erase_user,
    issue_token,
    revoke_token,
    update_sso_connection,
)
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.docs import Tag, refuses
from apps.core.api.scopes import ceiling_from_request, effective_scopes
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.core.throttling import AnonRateThrottle, BaseThrottle

# **The root of `/api/v1/`, and deliberately.** `config/api.py` mounts one
# router per app at the app's `PREFIX`; this app owns two resources that belong
# in two different places — a token is not an auth-configuration thing, and
# `/api/v1/tokens/realm` would be a lie about what the resource is. So the
# module exposes a parent router at the root, carrying `tokens` and `auth`
# beneath it at their own prefixes. Nothing in `config/` is edited to do it.
PREFIX = ""

# What each of this app's three tags is FOR, declared beside the routers that
# carry them and collected into the OpenAPI document's `tags` section by
# `config/api.py`'s discovery (ADR api-1). Three, because this app's routers
# serve three genuinely different audiences and one heading would say so badly.
#
# THERE IS NO `accounts` TAG, deliberately. It was an umbrella over the three
# below, and because every operation carried it as well as its own, a renderer
# showed all eleven twice — once in their real section and once under a heading
# that was a copy of the other three (owner review, 2026-08-24). Removed rather
# than left behind: a tag with no operations is worse than no tag, because it is
# an empty heading somebody clicks. **The app is not the group; the resource
# is.**
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

# `auth` is restated on every router here rather than inherited from the API
# default, so that reading this one file tells you what it takes to call each.
tokens_router = Router(tags=["tokens"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as.

    Whether the actor *may* do the thing is not decided here — `services.py`
    calls `authz.require`. What is decided here is that a write with no resolved
    tenant is refused rather than guessed at.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


# --- People -------------------------------------------------------------------
# Two acts, each in two forms. The forms differ only in how the person is named:
# `me/` reads the caller off the request and cannot name anybody else, while the
# `{user_id}` form resolves a member of the acting tenant through `get_member`
# and hands the SAME service the SAME wall. That is why there are four routes
# and not one with an optional id — a route that could be pointed at anybody by
# omitting a parameter is a route whose blast radius is a typo away.

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

    * `403 forbidden` — you are signed in but the request resolved no tenant.
      Send `X-Tenant` naming one you belong to.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    Deliberately takes no body: there is nothing a caller could say about
    deactivating themselves that would change what happens, and an optional
    field is a field somebody has to be told to omit.
    """
    actor, tenant = _acting(request)
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
    * `403 forbidden` — you are signed in but the request resolved no tenant.
      Send `X-Tenant` naming one you belong to.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    ADO-7: what is erased is what `services.erase_user` erases today. Rows
    elsewhere in the tree that point at this person are wave C's sweep, and the
    contract above does not change when it lands.
    """
    actor, tenant = _acting(request)
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

    The `not_found` above is `get_member`'s and is deliberately not
    distinguishable from `Forbidden`: not-there and not-yours are one answer, or
    the refusal itself confirms that somebody else's account exists.
    """
    actor, tenant = _acting(request)
    return deactivate_user(
        user=get_member(tenant=tenant, user_id=user_id, actor=actor), actor=actor, tenant=tenant
    )


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

    ---

    ADO-7, again and on purpose: this route's contract is the rung's deliverable
    and the completeness of the sweep behind it is not. Wave C deepens
    `erase_user`; these tests should pass byte-unchanged when it does, and that
    is the trigger to re-run them.
    """
    actor, tenant = _acting(request)
    return erase_user(
        user=get_member(tenant=tenant, user_id=user_id, actor=actor), actor=actor, tenant=tenant
    )


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
    * `403 forbidden` — you are signed in, and the request resolved no tenant.
      Send `X-Tenant` naming a tenant you belong to.
    * `400 invalid` — the `name` was empty or longer than 200 characters, or
      `scopes` was missing, empty, or named something this API does not have.
      `errors` says which.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    **Through `_acting`, like every other write in this module.** It was
    the one that was not, and it read `request.tenant` straight off the request:
    a signed-in person with no resolvable tenant got a token pinned to nothing,
    and because `issue_token` declares a `tenant`, `@service` filed that mint's
    audit row in the **platform** population — the null-tenant ledger that is
    meant to hold the deployment's own actions and nothing a stranger can reach.
    "Platform means the deployment" was documentation enforced by nothing.

    The tenantless refusal is `_acting`'s sentence and not this route's, so this
    route and the SSO-configuration routes cannot come to disagree about what a
    tenantless write gets told. The behaviour change is real and was ratified —
    a tenantless session can no longer mint over the wire. `manage.py
    issue_token` still mints an unpinned token, which is the right door for it:
    it belongs to whoever has a shell, not to whoever has a cookie.

    The CSRF sentence above exists because the guide and this route
    both told a caller to sign in and mint, and neither said the session path
    needs the header, so the first mint against the guide was a 403 nobody could
    explain from the document. The mapper hole it exposed — a CSRF failure
    answering in Django's words rather than the product's — belongs to the
    authentication door and not to this route.
    """
    if authenticated_by_token(request):  # pragma: no cover - MINT_AUTH answers first
        raise SessionRequired(
            "A token cannot mint another token; sign in to do that. A token that could "
            "mint would survive being revoked, because its offspring would keep working."
        )
    actor, tenant = _acting(request)
    ceiling = ceiling_from_request(payload.scopes)
    token, plaintext = issue_token(
        user=cast(User, request.user),
        tenant=tenant,
        name=payload.name,
        # The person at the session door, so the credential's birth certificate
        # names who minted it (ADR core-22). `_acting` resolved it from
        # the request; nothing here re-derives who is calling.
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
    # `token.tenant`, never `request.tenant` (ADR core-22): the revocation is
    # recorded under the workspace the CREDENTIAL was pinned to, which is what
    # puts its death row beside its birth row. An unpinned token passes `None`
    # and lands in the platform population, exactly as its mint did. The service
    # refuses a disagreement, so this is a claim it checks rather than trusts.
    #
    # And the actor says WHO ended it. This route is reachable by both a
    # session and a bearer token — a program may revoke its own credential —
    # so `actor_from_request` is what tells `human` from `agent` here, and a
    # bearer revocation lands with the machine's id beside the person's.
    revoke_token(token=token, tenant=token.tenant, actor=actor_from_request(request))
    return Status(204, None)


# --- Home-realm discovery and SSO configuration -------------------------------
# Two very different audiences share the `/auth/` prefix and nothing else:
# `realm` is the only route in this app a stranger may call, and the
# `sso-connections` routes are the most privileged ones in the product.

auth_router = Router(tags=["auth"], auth=API_AUTH)

# What `?ordering=` may name on the connection list, and nothing else.
SSO_ORDERING = ("created_at", "updated_at", "name", "status")

# The realm route's own throttle, named at module level rather than built inline
# in the decorator. A `SimpleRateThrottle` reads its rate from settings **when it
# is constructed**, which is import time — so an inline instance is one a test
# can neither reach nor reconfigure, and "the throttle is wired up" would be a
# claim with no test behind it. Named, it is both.
#
# Typed as the base class because ninja's `throttle=` takes `list[BaseThrottle]`
# and a `list` is invariant: `list[AnonRateThrottle]` is not one.
REALM_THROTTLES: list[BaseThrottle] = [AnonRateThrottle()]


@auth_router.post(
    "/realm/",
    response=RealmOut,
    url_name="realm-discover",
    # rule-3: pre-auth realm discovery. A login form has to ask "where does this
    # address sign in?" *before* anybody is signed in — that is what home-realm
    # discovery is — so there is no credential this route could require. What
    # stands in for one is that the answer discloses nothing:
    # `selectors.realm_for_email` answers `sso` for every address (ADR ident-6),
    # returns no tenant name, no slug, no connection name and no count, and
    # cannot distinguish "no SSO here", "that connection is disabled" and "never
    # heard of that domain" — all three are byte-identical. A claimed domain
    # differs only by an opaque id and an opaque hint. See
    # `apps/accounts/selectors.py` for the full argument.
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

    Throttled per client address on top of the API's own limits, because this is
    the one route in this app anybody may call: without it, the response — one
    bit per request — is a way to walk a domain list at whatever rate the network
    allows. It does not make enumeration impossible; it makes it slow enough to
    notice, which is the honest claim.

    `method` keeps `password` in its vocabulary although nothing answers it any
    more (ADR ident-6): a client that switched on the value stays correct if a
    product ever reintroduces a local password door.
    """
    realm = realm_for_email(payload.email)
    return RealmOut(
        method=cast(Literal["sso", "password"], realm.method),
        connection_id=realm.connection_id,
        authorize_url=realm.authorize_url,
    )


def _sso_connections(request: TenantRequest) -> QuerySet[SsoConnection]:
    """The acting tenant's connections, for the LIST. Asks `sso_connection.read`.

    The read sweep put the capability inside the selector, at the tenant's
    ROOT, so the list refuses a hat that may not see the tenant's federation
    posture instead of handing it back an empty page.
    """
    actor, tenant = _acting(request)
    return list_sso_connections(tenant=tenant, actor=actor)


def _sso_connection_reach(request: TenantRequest) -> QuerySet[SsoConnection]:
    """The REACH for a detail route: tenancy only, no capability asked here.

    **Why this is not `_sso_connections`.** A `PATCH` and a `DELETE` each carry
    their own key — `sso_connection.update`, `sso_connection.disable` — asked
    by the service at the tenant's root. Resolving the row through the LIST
    selector would ask `sso_connection.read` first, so a branch administrator
    attempting a rename would be refused with *"You may not read this SSO
    connection"* when what they attempted was a write: the right status for the
    wrong reason, and the sentence is the half a person acts on. The ceiling
    itself does not move — `test_sso_role_ceiling.py` drives all five acts —
    because the service's wall is the one that was always deciding.

    **Nothing asks `sso_connection.read` on this path, and that is the point.**
    This helper is reach and nothing else; the capability for the act is the
    service's, one call later. There is no detail `GET` on this door — if one
    is ever added, it is that route's job to ask the read after this fetch,
    which is R1.1's order (reach, then capability) and what
    `selectors.get_member` does.
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
    owns, such as `acme.com`. Optionally `default_role` (the role people who
    arrive through it join at; `member` unless you say otherwise, and it never
    changes an existing membership) and `enforced` (when `true`, people in those
    domains may not sign in any other way).

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

    * `403 forbidden` — you are not an owner or administrator of this tenant, or
      the request resolved no tenant. Send `X-Tenant` naming one you belong to.
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
    actor, tenant = _acting(request)
    connection = create_sso_connection(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        issuer=payload.issuer,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        email_domains=payload.email_domains,
        protocol=payload.protocol,
        default_role=payload.default_role,
        enforced=payload.enforced,
    )
    return Status(201, connection)


@auth_router.patch(
    "/sso-connections/{connection_id}/",
    response=SsoConnectionOut,
    url_name="sso-connection-update",
)
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
    * `403 forbidden` — you are not an owner or administrator of this tenant, or
      the request resolved no tenant.
      **Measured at the tenant's root**: an administrator of one branch
      administers that branch, and may not configure the tenant's identity
      provider.
    * `400 invalid` — a field you sent is malformed, or `default_role` is above
      your own role. `errors` names the fields.
    * `409 conflict` — one of the `email_domains` is already claimed elsewhere.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
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
    * `403 forbidden` — you are not an owner or administrator of this tenant, or
      the request resolved no tenant.
      **Measured at the tenant's root**: an administrator of one branch
      administers that branch, and may not configure the tenant's identity
      provider.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    connection = get_object_or_404(_sso_connection_reach(request), pk=connection_id)
    disable_sso_connection(tenant=tenant, actor=actor, connection=connection)
    return Status(204, None)


# --- The mount ---------------------------------------------------------------
# What `config/api.py` discovers. The three routers above hang off it at their
# own prefixes, so the URL says what the resource is rather than which app holds
# it.
#
# **IT CARRIES NO TAG OF ITS OWN, and that is load-bearing.** A nested router's
# tags ACCUMULATE downward in ninja (`Router.set_api_instance`: the inherited
# tags plus the template's own), so `tags=["accounts"]` here put a SECOND tag on
# all eleven operations beneath it — and a renderer lists an operation under
# every tag it carries, so the whole app appeared twice in the navigation: once
# under its own three headings and again under an "Accounts & tokens" umbrella
# that was a copy of all three. The owner read it in review, 2026-08-24. One
# operation, one section: the specific router names the group, the mount names
# nothing, and house rule 41 now refuses a second tag anywhere.
router = Router(auth=API_AUTH)
router.add_router("/users/", users_router)
router.add_router("/tokens/", tokens_router)
router.add_router("/auth/", auth_router)
