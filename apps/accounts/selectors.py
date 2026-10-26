"""Reads for the accounts app. Nothing here writes.

Four of the five functions below run **before anybody is signed in**, which is
what makes them worth reading carefully:

* `get_realm_for_email` is home-realm discovery — the answer to "where does this
  person sign in?" for an address typed into a login box by nobody in
  particular;
* `get_enforcing_connection_for` is the other half of `enforced`: whether a password is
  still allowed for this address;
* `get_workforce_domains` and `policies.is_workforce_email` are the Google Workspace door's
  allow-list.

**What an unauthenticated caller may learn is nothing at all** (ADR ident-6).
Under ADR ident-6 every address answers `sso`, because that is now simply true: Zitadel
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

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.db.models import Exists, OuterRef, QuerySet
from django.urls import reverse

from apps.accounts import realms
from apps.accounts.models import (
    STAFF_REALM,
    FirstAdminVouch,
    IdentityHome,
    SsoConnection,
    SsoDomain,
    SsoIdentity,
    User,
    domain_of,
    normalise_domain,
)
from apps.accounts.realm import RealmRef
from apps.core.actor import Actor
from apps.core.authz import OWNER_ROLE, require
from apps.core.exceptions import NotFound
from apps.core.models import Membership, Tenant
from apps.core.selectors import list_owners_holding_at_root, list_pending_invitations_for
from apps.core.services import root_organization
from apps.core.surfaces import STAFF, Surface, absolute_url
from apps.core.time import now

# The wire vocabulary. Strings rather than an enum because they are part of the
# API contract and a client branches on them.
#
# **`get_realm_for_email` gives only `sso` now** (ADR ident-6). `password`
# stays in the vocabulary and in `RealmOut` deliberately: the schema's shape is
# a contract, a client that branches on it must keep compiling, and a product
# that reopens a local password door — which is one settings change, see
# `SOCIALACCOUNT_ONLY` in `config/settings/base.py` — needs the word back rather
# than a schema migration. A vocabulary with an unused member is cheap; a
# contract that changed shape under a client is not.
METHOD_SSO = "sso"
METHOD_PASSWORD = "password"  # noqa: S105 — the sign-in method's vocabulary member  # pragma: allowlist secret — a vocabulary member, not a credential


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
    #: The tenant realm this address signs in at, when a verified claim routes
    #: it to a tenant whose realm exists — inside the product only, like
    #: `connection`. `authorize_url` already carries its sign-in parameters.
    identity_realm: RealmRef | None = None
    #: The tenant whose switched-off connection holds the verified claim — inside the product only.
    dormant_tenant: Tenant | None = None


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


def get_platform_issuer() -> str:
    """The issuer the platform provider signs every realm's people in at."""
    return str(getattr(settings, "ZITADEL_ISSUER", "") or "").strip().rstrip("/")


def get_realm_ref(realm: str) -> RealmRef:
    """The realm a join row names, as the realm port takes it.

    A tenant realm is spelled by its id. The staff realm is spelled
    `STAFF_REALM` and its id is the one the seed recorded — `""` before it has,
    which the port reads as the platform credential's own organisation, the
    realm the staff realm IS.
    """
    if realm != STAFF_REALM:
        return RealmRef(id=realm, issuer=get_platform_issuer())
    # rule-8: the staff realm's home is the one row with NO tenant; the
    # manager method is its one read and scopes nothing because there is nothing to scope by.
    staff = IdentityHome.objects.staff()
    return RealmRef(id=staff.realm_id if staff is not None else "", issuer=get_platform_issuer())


def get_tenant_realm(tenant: Tenant) -> RealmRef | None:
    """The tenant's own realm, or `None` while its home is pending — fail closed."""
    home = IdentityHome.objects.for_tenant(tenant).first()
    if home is None or home.state != IdentityHome.State.OWN_ORG or not home.realm_id:
        return None
    return RealmRef(id=home.realm_id, issuer=get_platform_issuer())


def get_platform_login_url(
    *,
    surface: Surface | str = STAFF,
    realm: RealmRef | None = None,
    idp_hint: str = "",
    tenant: str | None = None,
) -> str:
    """Where a browser starts a sign-in. **One door, for everybody.**

    Absolute, on `surface`'s host (`core.surfaces.absolute_url`, the one URL
    seam): a face on the customer host starts its sign-in on the customer host,
    and with no surfaces bound it is the deployment's base URL joined to the path, the
    link this function always built. Absolute because the caller is often a
    front end on another origin and a relative path would resolve against its
    host.

    **`realm` confines the sign-in to one realm** — the realm port's
    `authorize_params`, carried through allauth's own `auth_params`
    pass-through, the same road `idp_hint` rides. With no realm the sign-in is
    the unconfined one it always was: a person's realm is only known here from a
    verified domain claim, and naming the staff realm for everybody else would
    refuse every tenant's invited people, who live in their tenant's realm.

    The provider id comes from settings because three things have to agree on it
    — this, the redirect URI `zitadel_seed` registers, and the login page's link
    (`config/settings/base.py`, `ZITADEL_PROVIDER_ID`).
    """
    path = reverse(
        "openid_connect_login",
        kwargs={"provider_id": str(settings.ZITADEL_PROVIDER_ID)},
    )
    base = absolute_url(path=path, surface=surface, tenant=tenant)
    params: dict[str, str] = {}
    if idp_hint:
        params["idp_hint"] = idp_hint
    if realm is not None:
        params.update(realms.current().authorize_params(realm=realm))
    if not params:
        return base
    return f"{base}?{urlencode({'auth_params': urlencode(params)})}"


# rule-16: the URL one IdP's login starts from, by the name the architecture record cites
def authorize_url_for(connection: SsoConnection, *, surface: Surface | str = STAFF) -> str:
    """Where a browser starts a login **that should jump straight to this IdP**.

    The platform's login URL, carrying the connection's Zitadel provider id as a
    hint. Under ADR ident-6 a customer's IdP is not an allauth app of ours at all — it
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
    return get_platform_login_url(
        surface=surface,
        realm=get_tenant_realm(connection.tenant),
        idp_hint=str(connection.zitadel_idp_id or "").strip(),
        tenant=connection.tenant.slug,
    )


def get_realm_for_email(email: str, *, surface: Surface | str = STAFF) -> Realm:
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
    claim = SsoDomain.objects.for_domain(domain_of(email), live=False)
    if claim is None:
        return Realm(method=METHOD_SSO, authorize_url=get_platform_login_url(surface=surface))
    connection = claim.connection
    if not connection.is_active:
        # Indistinguishable from never-claimed on the wire (ADR ident-6); the dormant tenant
        # stays inside the product, where the sign-in confines to it.
        return Realm(
            method=METHOD_SSO,
            authorize_url=get_platform_login_url(surface=surface),
            dormant_tenant=connection.tenant,
        )
    return Realm(
        method=METHOD_SSO,
        connection_id=connection.pk,
        authorize_url=authorize_url_for(connection, surface=surface),
        connection=connection,
        identity_realm=get_tenant_realm(connection.tenant),
    )


@dataclass(frozen=True)
class AssertedRealm:
    """Which realm a sign-in's assertion came from, and whose people it holds."""

    #: `STAFF_REALM`, or a tenant realm's id — the join's spelling.
    realm: str
    #: The realm's tenant; `None` for the staff realm.
    tenant: Tenant | None


def get_realm_of_assertion(*, realm_id: str, subject: str, email: str) -> AssertedRealm:
    """The realm an assertion came from: the one the platform named, else the one we know.

    **The platform names it on every real sign-in** — a confined one through
    the realm's own scope, an unconfined round trip through the resource-owner
    scope the adapter asks for, and the ours door through the organisation its
    session verified (all measured). A tenant realm's id resolves to its
    tenant; any other id is the staff realm.

    **An assertion that names none is legacy** — one minted before the claim
    was asked for — so the realm is read off what we already know, in the
    order that cannot be wrong: the join row this subject
    already has (a subject is one account at the platform); else the tenant
    realm a verified domain claim routes the address to (`get_realm_for_email`,
    the one realm lookup); else the realm of the ONE tenant whose standing
    invitation this address holds — the invitation road made the person in that
    realm; else the staff realm.
    """
    if realm_id:
        # rule-8: an assertion names its realm before anybody knows its tenant;
        # the realm id IS the lookup, and the tenant is what it finds out.
        home = IdentityHome.objects.of_realm(realm_id)
        if home is not None and home.tenant is not None:
            return AssertedRealm(realm=realm_id, tenant=home.tenant)
        return AssertedRealm(realm=STAFF_REALM, tenant=None)
    # LEGACY: only an assertion with no realm claim reaches the join row, and
    # a join row can be stale (a rollback re-spells a tenant-realm row `staff`),
    # which is why every real sign-in names its realm and never reads this arm.
    # rule-8: a platform subject is one account; the tenant is read off
    # the join row it finds, never narrowed by before the sign-in knows it.
    known = SsoIdentity.objects.of_subject(subject)
    if known is not None:
        return AssertedRealm(realm=known.realm, tenant=known.tenant)
    routed = get_realm_for_email(email)
    if routed.connection is not None and routed.identity_realm is not None:
        return AssertedRealm(realm=routed.identity_realm.id, tenant=routed.connection.tenant)
    invited = {
        found.id: tenant
        for tenant in {
            invitation.tenant for invitation in list_pending_invitations_for(email=email)
        }
        if (found := get_tenant_realm(tenant)) is not None
    }
    if len(invited) == 1:
        realm, tenant = next(iter(invited.items()))
        return AssertedRealm(realm=realm, tenant=tenant)
    return AssertedRealm(realm=STAFF_REALM, tenant=None)


def get_enforcing_connection_for(email: str) -> SsoConnection | None:
    """The active, enforcing connection claiming this address's domain, if any.

    # read-open: pre-auth, asked on a password login before any actor exists to ask a read of.
    An unauthenticated caller repeats only that SSO is required: the name is a customer's.
    """
    claim = SsoDomain.objects.for_domain(domain_of(email))
    if claim is None:
        return None
    connection = claim.connection
    if not connection.is_active or not connection.enforced:
        return None
    return connection


def list_tenants_this_user_alone_owns(*, user: User) -> list[Tenant]:
    """The tenants whose only ownership holder is this person (`list_owners_holding_at_root`).

    # read-open: the erasure guard's own read inside its transaction; no door lists it.
    """
    alone = []
    owned = Membership.objects.of(user).filter(role=OWNER_ROLE).select_related("tenant")
    for tenant in {row.tenant for row in owned}:
        holders = set(list_owners_holding_at_root(tenant=tenant).values_list("user_id", flat=True))
        if holders == {user.pk}:
            alone.append(tenant)
    return sorted(alone, key=lambda tenant: tenant.slug)


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


def list_stale_staff_joins() -> QuerySet[SsoIdentity]:
    """`staff` join rows whose subject also holds a row in a tenant's realm: a rollback's leftover.

    # read-open: the operator's reconcile at the shell, platform-wide; no door lists it.
    """
    # rule-8: the join is platform-wide; a stale row is found by its subject, never by a tenant.
    joined = SsoIdentity.objects.filter(connection__isnull=True)
    homed = joined.exclude(realm=STAFF_REALM).values("subject")
    return joined.filter(realm=STAFF_REALM, subject__in=homed).order_by("created_at")


def get_first_admin_vouch(*, email: str) -> FirstAdminVouch | None:
    """The unspent, unexpired day-zero vouch for this address, while the installation has no tenant.

    # read-open: pre-auth, the workforce wall's third vouch — no actor exists yet to ask a read of.
    """
    if Tenant.objects.exists():
        return None
    return FirstAdminVouch.objects.filter(
        email=email.strip().lower(), consumed_at__isnull=True, expires_at__gt=now()
    ).first()


def get_dormant_claim_tenant(email: str) -> Tenant | None:
    """The tenant whose switched-off connection holds the verified claim on this address's domain.

    # read-open: pre-auth, like `get_connection_for_email` — no actor exists yet to ask a read of.
    """
    return get_realm_for_email(email).dormant_tenant


def get_connection_for_email(email: str) -> SsoConnection | None:
    """The live connection claiming this address's domain, if there is one.

    **`SsoDomain` stays the router** (ADR ident-6): now a customer's
    people arrive asserted by Zitadel like everybody else, so the assertion no
    longer says which connection it came through — and the answer to "whose
    person is this" goes back to the row that always held it, the domain claim.

    A disabled connection answers `None`, so an in-flight login through one is refused.

    **It is `get_realm_for_email` and not a second read**, deliberately. The login
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
    # and `get_realm_for_email`, and neither has a principal yet. The tenancy
    # exemption rule 8 already grants this site by name is the same fact from
    # the other side.
    """
    return get_realm_for_email(email).connection


def get_workforce_domains() -> frozenset[str]:
    """The Google Workspace domains this deployment accepts, normalised.

    **Empty means the workforce provider is off**, not "any domain"
    (`config/settings/base.py`). Every caller has to read it that way, so the
    reading happens once, here.
    """
    configured = getattr(settings, "GOOGLE_WORKSPACE_DOMAINS", []) or []
    return frozenset(normalise_domain(domain) for domain in configured if normalise_domain(domain))


#: allauth's id for the retired direct Google provider. It survives only as the
#: key its leftover `SocialAccount` rows are found by.
DIRECT_GOOGLE_PROVIDER = "google"


@dataclass(frozen=True)
class DirectGoogleLinks:
    """What the retired direct Google road left behind, read before it is retired."""

    #: rows whose person already carries a Zitadel identity — safe to retire.
    retirable: int
    #: addresses of people holding a direct-road row and NO Zitadel identity yet;
    #: retiring their row would leave them no road the platform knows them by.
    unjoined: tuple[str, ...]


def get_direct_google_links() -> DirectGoogleLinks:
    """The census `retire_direct_google_links` acts on, and its dry run prints.

    Deployment-wide by construction: a `SocialAccount` is allauth's row about a
    person, not a tenant's record, and the road that wrote these was the
    installation's own workforce door.
    """
    joined = Exists(
        # rule-8: a person's identity join across every realm is the question —
        # the census is the installation's own, as its docstring says.
        SsoIdentity.objects.filter(user=OuterRef("user"), connection__isnull=True)
    )
    rows = SocialAccount.objects.filter(provider=DIRECT_GOOGLE_PROVIDER).annotate(joined=joined)
    return DirectGoogleLinks(
        retirable=rows.filter(joined=True).count(),
        unjoined=tuple(
            sorted(set(rows.filter(joined=False).values_list("user__email", flat=True)))
        ),
    )
