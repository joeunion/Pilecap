"""The MCP door as an OAuth 2.1 resource server (ADR ident-3).

A third-party caller — an assistant, a scripted client — reaches `/mcp` with an
access token **Zitadel** issued, not one we did. This module is the half of that
exchange we are responsible for: taking somebody else's token and deciding, on
our own, whether it authenticates anybody here.

**`ApiToken` survives beside it** and is tried first. That is the subsumption
decision, and the reason is DX rather than sentiment: retiring it would put a
browser consent dance inside `manage.py seed`, every wire test and every CI
probe. One authenticator in an ordered list costs nothing; the trigger to retire
it is named in the ADR.

## What "validating" means here, in full

A resource server that checks a signature and stops has built a door that any
token from the same issuer opens. All five of these are load-bearing:

* **signature** against the issuer's published JWKS — the token is really
  Zitadel's;
* **issuer** — it is *our* Zitadel and not another instance;
* **audience** — it was minted **for this resource**. Without this, a token some
  other API on the same instance issued to some other client opens `/mcp`. This
  is the check people leave out, and `ZITADEL_MCP_AUDIENCE` empty means the
  OAuth door is **off** rather than open;
* **expiry**, and `nbf` if present — pyjwt enforces both once asked;
* **the subject resolves to somebody here** — `sub` → `User.zitadel_sub`, the
  one join W2-R3 wrote. A valid token for a person this deployment has never
  seen authenticates nobody.

## What is deliberately NOT in the token

**Tenant and organization are bound at request time, never read from a claim.**
The token contributes WHO. The tenant comes from the person's memberships plus
`X-Tenant`, and the acting hat from `X-Org` through the same
`core.middleware.resolve_org` the session door, the socket door and the
`ApiToken` door all call. An issue-time org claim would go stale against a tree
that changes underneath it, which is precisely the failure the hierarchy's
revalidate-every-request doctrine exists to prevent.

## Revocation, honestly

A JWT is self-contained: a token revoked at Zitadel stays cryptographically
valid here until it expires. This module does not introspect — that would be a
network round trip on every call — so the revocation window is the token's own
lifetime, and the *key*-rotation window is `ZITADEL_JWKS_CACHE_SECONDS`. Both
are recorded in `config/settings/base.py` beside the setting, as the rung's
named blind spot rather than as a surprise.
"""

from __future__ import annotations

import time
from typing import Any, NamedTuple

import httpx
import jwt
from django.conf import settings
from django.http import HttpRequest, JsonResponse

from apps.accounts.models import User
from apps.core.log import get_logger
from apps.core.middleware import resolve_tenant
from apps.core.models import Tenant

log = get_logger(__name__)

# The only signing algorithm this deployment accepts. An **allow-list, not a
# default**: `alg` travels in the token's own header, so a verifier that took
# the token's word for it is the classic JWT forgery (`alg: none`, or an RSA
# public key replayed as an HMAC secret). Zitadel signs RS256.
ALGORITHMS = ["RS256"]

# RFC 6750's error code for "the token is bad in some way". Deliberately the
# only one used: telling a caller *which* of signature, audience, issuer or
# expiry failed is telling an attacker which half of a forgery worked.
ERROR_INVALID_TOKEN = "invalid_token"

# RFC 9728. The path a 401 points at, so a client can discover the
# authorization server without being told out of band.
METADATA_PATH = "/.well-known/oauth-protected-resource"

# How long the discovery document is reused. The same window as the JWKS,
# because they are the same class of fact about the issuer.
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


class OAuthPrincipal(NamedTuple):
    """Who a validated access token turned out to be.

    No token row: an OAuth caller holds no `ApiToken`, and inventing one so the
    shapes matched would put a row in the database for a credential we did not
    issue and cannot revoke. `Principal.token` is `None` for these, which is
    what makes the audit trail able to tell the two doors apart.
    """

    user: User
    tenant: Tenant | None
    subject: str


class OAuthRefused(Exception):
    """A bearer token that looked like a JWT and did not survive validation.

    Carries the RFC 6750 `error` and a description safe to put on the wire.
    """

    def __init__(self, description: str, error: str = ERROR_INVALID_TOKEN) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


def issuer() -> str:
    return str(getattr(settings, "ZITADEL_ISSUER", "") or "").strip().rstrip("/")


def audiences() -> list[str]:
    return [str(value) for value in getattr(settings, "ZITADEL_MCP_AUDIENCE", []) or []]


def configured() -> bool:
    """Whether this deployment has an OAuth door at all.

    Both halves required. An issuer with no audience is a resource server that
    would accept every token that instance ever minted, so it is treated as no
    door rather than as an open one.
    """
    return bool(issuer()) and bool(audiences())


def looks_like_jwt(token: str) -> bool:
    """Three non-empty dot-separated segments.

    The cheap discriminator that keeps the two credentials apart. An `ApiToken`
    is `djb_<random>` and can never satisfy this, so a first-party token is
    never handed to the JWT path and a JWT is never hashed and looked up as an
    API token. It decides nothing about validity.
    """
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


def _cache_seconds() -> int:
    return int(getattr(settings, "ZITADEL_JWKS_CACHE_SECONDS", 300))


def discovery() -> dict[str, Any]:
    """The issuer's OpenID configuration, cached for the recorded window.

    Fetched rather than hard-coded: `jwks_uri` is the issuer's to move, and a
    deployment that pinned it would break silently on a Zitadel upgrade in the
    one way that looks like every token suddenly being forged.
    """
    where = issuer()
    if not where:
        raise OAuthRefused("This deployment has no identity issuer configured.")
    cached = _discovery_cache.get(where)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _cache_seconds():
        return cached[1]
    url = f"{where}/.well-known/openid-configuration"
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            response = client.get(url)
            response.raise_for_status()
            document = dict(response.json())
    except (httpx.HTTPError, ValueError) as error:
        raise OAuthRefused("The identity provider's configuration is unreachable.") from error
    _discovery_cache[where] = (now, document)
    return document


def _jwks_client() -> jwt.PyJWKClient:
    """One client per JWKS URL, keeping its own key cache.

    `lifespan` is the key-rotation window recorded in settings. The client is
    kept across requests on purpose: a fresh one per call would fetch the key
    set on every single tool invocation.
    """
    uri = str(discovery().get("jwks_uri") or "")
    if not uri:
        raise OAuthRefused("The identity provider publishes no JWKS.")
    client = _jwks_clients.get(uri)
    if client is None:
        client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=_cache_seconds())
        _jwks_clients[uri] = client
    return client


def reset_caches() -> None:
    """Forget the issuer. **Tests only** — a stub issuer per test needs it.

    Production fetches once per window; this exists so a test that starts a new
    in-process issuer on a recycled port cannot validate against the previous
    one's keys.
    """
    _discovery_cache.clear()
    _jwks_clients.clear()


def claims(token: str) -> dict[str, Any]:
    """Validate the token completely, or raise `OAuthRefused`.

    Every `options` flag below is set explicitly rather than left to pyjwt's
    defaults. The defaults happen to be right today; a verifier whose
    correctness depends on a library's default is one release away from being
    wrong, and this is the function where that matters most.
    """
    if not configured():
        raise OAuthRefused("This deployment does not accept OAuth access tokens.")
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        decoded: dict[str, Any] = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=ALGORITHMS,
            issuer=issuer(),
            audience=audiences(),
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["exp", "iss", "aud", "sub"],
            },
        )
    except OAuthRefused:
        raise
    except (jwt.PyJWTError, jwt.PyJWKClientError) as error:
        # The reason is logged, never sent: which check failed is exactly what
        # an attacker probing a forgery wants to know.
        log.info("accounts.oauth.refused", reason=type(error).__name__)
        raise OAuthRefused("That access token is not valid for this resource.") from error
    return decoded


def authenticate_bearer(*, token: str, requested_slug: str | None = None) -> OAuthPrincipal:
    """A validated access token, resolved to a person and a tenant here.

    Raises `OAuthRefused` for everything: a bad token and a good token for
    somebody this deployment has never seen are the same answer on the wire, so
    a caller cannot use the door to find out which accounts exist.

    The tenant is resolved **exactly** as it is for a session and for an
    `ApiToken` with no pin — from memberships, honouring `X-Tenant` — because a
    door that resolved it differently would be a door that could see something
    the others cannot. A person with no membership resolves to `None`, and
    tenancy failing closed is what turns that into "the tools refuse", not a
    500.
    """
    decoded = claims(token)
    subject = str(decoded.get("sub") or "")
    if not subject:
        raise OAuthRefused("That access token names no subject.")

    user = User.objects.filter(zitadel_sub=subject, is_active=True).first()
    if user is None:
        log.info("accounts.oauth.unknown_subject")
        raise OAuthRefused("That access token is not valid for this resource.")

    tenant = resolve_tenant(user=user, requested_slug=requested_slug)
    return OAuthPrincipal(user=user, tenant=tenant, subject=subject)


# --- RFC 9728: protected-resource metadata ------------------------------------
#
# The discovery chain the MCP specification leans on. A client that has never
# seen this deployment gets a 401 carrying `resource_metadata=<url>`; it fetches
# that document, learns which authorization server to talk to, and comes back
# with a token. Without it, "which AS?" is something a human has to be told, and
# a third-party client cannot bootstrap itself at all.


def metadata_url() -> str:
    """Absolute, because it goes in a header a client will fetch from elsewhere."""
    base = str(getattr(settings, "PUBLIC_BASE_URL", "")).rstrip("/")
    return f"{base}{METADATA_PATH}"


def resource_url() -> str:
    """The resource this metadata is about: the MCP endpoint itself."""
    base = str(getattr(settings, "PUBLIC_BASE_URL", "")).rstrip("/")
    return f"{base}/mcp"


def protected_resource_metadata() -> dict[str, Any]:
    """The RFC 9728 document, built from what this deployment actually uses."""
    return {
        "resource": resource_url(),
        "authorization_servers": [issuer()] if issuer() else [],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["openid", "profile", "email"],
    }


def challenge(*, error: str = "", description: str = "") -> str:
    """The `WWW-Authenticate` value a 401 from the MCP door carries.

    `resource_metadata` is the load-bearing parameter — it is the only thing
    that makes the 401 actionable rather than a dead end. The error parameters
    are added only when there was a token to reject; a request with no
    credential at all has no error to report, just a door to point at.
    """
    parts = ['Bearer realm="mcp"']
    if error:
        parts.append(f'error="{error}"')
    if description:
        parts.append(f'error_description="{description}"')
    parts.append(f'resource_metadata="{metadata_url()}"')
    return ", ".join(parts)


def protected_resource_metadata_view(request: HttpRequest) -> JsonResponse:
    """Serve RFC 9728 at the root, unauthenticated.

    **Unauthenticated on purpose**, and it is not a leak: the whole job of this
    document is to be readable by a client that has no credential yet — that is
    what "discovery" means. Everything in it is already public (the issuer is in
    every redirect; the resource URL is the endpoint being called), and a
    metadata document behind authentication is a chicken-and-egg that no
    third-party client can break.

    Mounted at the root by `config/urls.py` rather than under `/api/v1/`,
    exactly as `/healthz` is and for the same reason: a well-known URI is fixed
    by its RFC, so it inherits none of the API's versioning, throttling or
    idempotency machinery.
    """
    return JsonResponse(protected_resource_metadata())
