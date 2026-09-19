"""Reads for the accounts app. Nothing here writes.

Four of the five functions below run **before anybody is signed in**, which is
what makes them worth reading carefully:

* `realm_for_email` is home-realm discovery — the answer to "where does this
  person sign in?" for an address typed into a login box by nobody in
  particular;
* `sso_enforced_for` is the other half of `enforced`: whether a password is
  still allowed for this address;
* `workforce_domains` and `is_workforce_email` are the Google Workspace door's
  allow-list.

**What an unauthenticated caller may learn is nothing at all** (ADR ident-6).
Since W2-R5 every address answers `sso`, because that is now simply true: Zitadel
hosts every interactive authentication, including the passwords of local users,
so *everybody* signs in at the same door. What differs is only whether the URL
carries a hint at which federated provider to jump straight to — and a claimed
domain's hint is an opaque Zitadel id.

Unclaimed, disabled and never-heard-of are byte-identical answers, which is the
property that matters: a login box has to say *something*, and "no such tenant"
is a customer list anybody can enumerate one guess at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from django.urls import reverse

from apps.accounts.models import (
    SsoConnection,
    SsoDomain,
    User,
    domain_of,
    normalise_domain,
)
from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.core.services import root_organization

# The wire vocabulary. Strings rather than an enum because they are part of the
# API contract and a client branches on them.
#
# **`realm_for_email` gives only `sso` now** (ADR ident-6, W2-R5). `password`
# stays in the vocabulary and in `RealmOut` deliberately: the schema's shape is
# a contract, a client that branches on it must keep compiling, and a product
# that reopens a local password door — which is one settings change, see
# `SOCIALACCOUNT_ONLY` in `config/settings/base.py` — needs the word back rather
# than a schema migration. A vocabulary with an unused member is cheap; a
# contract that changed shape under a client is not.
METHOD_SSO = "sso"
METHOD_PASSWORD = "password"  # pragma: allowlist secret — a vocabulary member, not a credential


@dataclass(frozen=True)
class Realm:
    """Where an address signs in, and nothing more than that.

    `method` is `sso` for every address (ADR ident-6). `connection_id` is the
    opaque id of the connection claiming this address's domain, or `None` when
    no live connection claims it; `authorize_url` is where the browser goes, and
    it is the platform's login endpoint either way.
    """

    method: str
    connection_id: UUID | None = None
    authorize_url: str = ""
    #: The row behind `connection_id`, for callers **inside** the product. It is
    #: not on `RealmOut` and never crosses the wire: `api.discover_realm` builds
    #: the response field by field, and the three fields above are the whole of
    #: what a stranger is told. It is here so that the login box and the login
    #: *adapter* consult one router rather than two reads that can disagree
    #: about which connection owns a domain.
    connection: SsoConnection | None = None


def get_platform_provider_id() -> str:
    """The provider id Zitadel is registered under, from settings.

    Read at call time rather than imported as a constant so a test — and a
    deployment that renames it — changes one setting and every branch that
    branches on it follows. `config/settings/base.py` says why three things have
    to agree on this string, and `get_platform_login_url` below is one of them.

    **It lives here rather than in the adapter** (R2F2), because the adapter is
    no longer the only caller: `services.unlink_zitadel_identity` takes the
    person's platform `SocialAccount` rows with the column, and it has to mean
    the same provider the door means. Two definitions of a string three things
    already have to agree on is the whole risk; reads live in selectors, which
    is where both callers can reach one.
    """
    return str(getattr(settings, "ZITADEL_PROVIDER_ID", "zitadel"))


def get_platform_login_url() -> str:
    """Where a browser starts a sign-in. **One door, for everybody.**

    Absolute, from `PUBLIC_BASE_URL`, because the caller is often a front end on
    another origin and a relative path would resolve against *its* host. The
    same reason `core.mail` builds invitation links from that setting: the code
    that builds the link frequently has no request to ask.

    The provider id comes from settings because three things have to agree on it
    — this, the redirect URI `zitadel_seed` registers, and the login page's link
    (`config/settings/base.py`, `ZITADEL_PROVIDER_ID`).
    """
    path = reverse(
        "openid_connect_login",
        kwargs={"provider_id": str(settings.ZITADEL_PROVIDER_ID)},
    )
    return f"{str(settings.PUBLIC_BASE_URL).rstrip('/')}{path}"


def authorize_url_for(connection: SsoConnection) -> str:
    """Where a browser starts a login **that should jump straight to this IdP**.

    The platform's login URL, carrying the connection's Zitadel provider id as a
    hint. Since W2-R5 a customer's IdP is not an allauth app of ours at all — it
    is an external provider inside Zitadel — so there is no per-connection
    endpoint left to send anybody to, and the routing decision that used to be
    expressed as a URL is now expressed as a hint on the one URL.

    **`auth_params` is allauth's own pass-through**, not a private arrangement:
    `OAuth2Provider.get_auth_params_from_request` parses this query parameter and
    merges it into the authorize request, so `idp_hint` reaches Zitadel's
    authorize endpoint, which is what reads it. Nothing here needs a view of our
    own, and that is why the retirement of `list_apps` costs no door.

    A connection whose materialisation has not landed yet has no id to hint
    with, and gets the plain platform URL: Zitadel will ask the person to pick,
    which is a worse experience and a correct one.
    """
    base = get_platform_login_url()
    hint = str(connection.zitadel_idp_id or "").strip()
    if not hint:
        return base
    return f"{base}?{urlencode({'auth_params': urlencode({'idp_hint': hint})})}"


def realm_for_email(email: str) -> Realm:
    """Home-realm discovery: where this address signs in.

    One indexed read of `SsoDomain`, whatever the answer, so the work done is
    the same for an address with a connection and one without. That is the
    "constant-time-ish" the contract asks for and the honest description of it:
    the query plan is identical, the branch after it is not timed, and this is
    not a defence against an attacker measuring nanoseconds — it is a defence
    against the far more likely leak, which is a *response* that differs.

    **Every address answers `sso`** (ADR ident-6). It is not a widening of what
    is disclosed, it is the disappearance of the thing that was disclosed: there
    is no second door left to be routed to, so the answer stops being a routing
    decision about *this address* and becomes a constant. A claimed domain adds
    the hint that skips Zitadel's provider picker; an unclaimed one, a disabled
    one and one nobody has ever heard of are the same three bytes.
    """
    claim = SsoDomain.objects.for_domain(domain_of(email))
    if claim is None:
        return Realm(method=METHOD_SSO, authorize_url=get_platform_login_url())
    connection = claim.connection
    if not connection.is_active:
        # True, and deliberately indistinguishable from never-claimed: with the
        # connection disabled, those people sign in at the platform door like
        # everybody else, and saying so more precisely would say whose domain it
        # is.
        return Realm(method=METHOD_SSO, authorize_url=get_platform_login_url())
    return Realm(
        method=METHOD_SSO,
        connection_id=connection.pk,
        authorize_url=authorize_url_for(connection),
        connection=connection,
    )


def sso_enforced_for(email: str) -> SsoConnection | None:
    """The active, enforcing connection claiming this address's domain, if any.

    The answer to "may this person still use a password?", asked by
    `accounts.adapter.AccountAdapter` on every password login. Returns the
    connection so the caller can build the link to send them to — and callers on
    the unauthenticated side must repeat nothing from it except the fact that
    SSO is required, because a connection's name is a customer's name.
    """
    claim = SsoDomain.objects.for_domain(domain_of(email))
    if claim is None:
        return None
    connection = claim.connection
    if not connection.is_active or not connection.enforced:
        return None
    return connection


def get_member(*, tenant: Tenant | None, user_id: UUID, actor: Actor) -> User:
    """A person the acting tenant can see, by id, or `NotFound`.

    **How every door resolves a `{user_id}` before handing it to a service.**
    `User` is not a tenant-scoped model — a person can belong to several tenants
    and to none — so there is no `for_tenant` to lean on, and the narrowing that
    stands in for it is a membership in the tenant the caller is acting in.

    `NotFound` for all three of "no such person", "a person in somebody else's
    tenant" and "a person with no membership anywhere", byte-identically: a door
    that told them apart would answer "does this account exist" to anybody
    holding a session and a supply of ids. That is the same not-there ≡
    not-yours rule `may_be_named` follows, one layer up.

    It is a read and it decides nothing about the verb: whether the caller may
    *do* the thing to the person they resolved is `policies.py`'s, asked by the
    service. This only answers "could you have got hold of that reference" —
    and, since the read sweep, "and may you read a person at all".
    """
    found = (
        User.objects.filter(pk=user_id, memberships__tenant=tenant).first()
        if tenant is not None
        else None
    )
    if found is None:
        raise NotFound()
    # REACH FIRST, then the capability: the membership filter above is what
    # makes somebody else's person `not_found`, and this line is what makes a
    # person inside the acting tenant `forbidden` to a hat holding no
    # `user.read`. A read that never asked was a read every door inherited for
    # free (rule 54 (d)).
    #
    # hat-scoped: the third argument is the ROW. A `User` names no organization
    # — a person belongs to several tenants and to none — so there is no node in
    # the row to resolve, and the node this question belongs at IS the acting
    # hat: the reach is "holds a membership in the tenant I am acting in", which
    # is the filter above and not a place in the tree.
    require(actor, "user.read", found)
    return found


def list_sso_connections(*, tenant: Tenant | None, actor: Actor) -> QuerySet[SsoConnection]:
    """A tenant's connections, with their claimed domains already fetched.

    `prefetch_related` rather than a second query per row: `SsoConnectionOut`
    reads `email_domains`, which is derived from the `SsoDomain` rows, so a list
    without it is an N+1 that only shows up once a customer has more than one
    connection.

    **The capability is asked at the ROOT, before the queryset** — the same node
    the four writing keys have used since R1-F1, and for the same reason. A
    connection is the TENANT's identity: `sso_connection` names no organization,
    so it is a tenant-wide kind, and rule 55's whole law is that a tenant-wide
    kind is asked at a node the caller resolved rather than at the acting hat —
    where a branch administrator holds `*` and would read the tenant's whole
    federation posture off a hat that owns none of it. An earlier draft of this
    line asked at the hat on the argument that seeing is weaker than changing;
    the PM ruled against it, and the ruling is the right one: the list names
    every provider the tenant federates with and the domains each one claims,
    which is the configuration itself and not a signpost to it.

    A list has no row to hide, so somebody without the key hears the refusal
    rather than an empty page that reads as a tenant with no identity provider
    at all.
    """
    if tenant is None:
        # hat-scoped: there is no tenant, so there is no root to name — and no
        # hat either. `effective_permissions(user, None, ...)` is `frozenset()`,
        # so this refuses whoever asked, which is the same fail-closed answer
        # `for_tenant(None)` gives one line down, said a step earlier and out
        # loud. The branch exists because the node above is resolved from a
        # tenant, and `None` has no root; it is not a second policy.
        require(actor, "sso_connection.read")
    else:
        require(actor, "sso_connection.read", root_organization(tenant=tenant))
    return SsoConnection.objects.for_tenant(tenant).prefetch_related("domains")


def get_connection_for_email(email: str) -> SsoConnection | None:
    """The live connection claiming this address's domain, if there is one.

    **`SsoDomain` stays the router** (ADR ident-6): after W2-R5 a customer's
    people arrive asserted by Zitadel like everybody else, so the assertion no
    longer says which connection it came through — and the answer to "whose
    person is this" goes back to the row that always held it, the domain claim.

    A disabled connection answers `None`, which is what makes an in-flight login
    through one refused rather than honoured, exactly as
    `SsoConnectionManager.by_provider_id` did for the per-connection door this
    replaces.

    **It is `realm_for_email` and not a second read**, deliberately. The login
    box and the login itself must not be able to disagree about which connection
    owns a domain — a discrepancy there is a person sent to one identity provider
    and provisioned into another tenant — and one function answering both is the
    only version of that guarantee that cannot rot. It also keeps the pre-auth
    cross-tenant read to the single site rule 8 already exempts by name.

    # read-open: there is nobody to ask. This answers "whose person is this
    # address" BEFORE anybody has signed in — it is the home-realm question the
    # login box asks of a stranger — so there is no actor, no tenant and no
    # membership for `sso_connection.read` to be asked against. A door that
    # calls this must ask first; the two callers are the adapter's login road
    # and `realm_for_email`, and neither has a principal yet. The tenancy
    # exemption rule 8 already grants this site by name is the same fact from
    # the other side.
    """
    return realm_for_email(email).connection


def workforce_domains() -> frozenset[str]:
    """The Google Workspace domains this deployment accepts, normalised.

    **Empty means the workforce provider is off**, not "any domain"
    (`config/settings/base.py`). Every caller has to read it that way, so the
    reading happens once, here.
    """
    configured = getattr(settings, "GOOGLE_WORKSPACE_DOMAINS", []) or []
    return frozenset(normalise_domain(domain) for domain in configured if normalise_domain(domain))


def is_workforce_email(email: str) -> bool:
    """Whether the workforce door may admit this address at all."""
    domains = workforce_domains()
    if not domains:
        return False
    return domain_of(email) in domains
