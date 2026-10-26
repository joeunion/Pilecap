"""Tenant resolution and context binding for HTTP — the first door.

Two middlewares, in this order:

`ContextMiddleware` binds the ambient facts (house rule 20): `request_id` from
`X-Request-Id` or freshly minted, `correlation_id` from `X-Correlation-Id` or
freshly minted, and `door` — `admin` under `/admin/`, `rest` everywhere else,
because "the same service, called from the admin" is the question that keeps
coming up. It runs outermost so that anything raised by anything below it is
logged with the context still bound, and on the way out it puts back what was
there on the way in, so nothing leaks into the next request on the same thread.

**The session is bound lower down, and deliberately.** `session_id` is the
third of the three ids `core/context.py` promises, and outermost is above
`SessionMiddleware`: `request.session` does not exist yet up here, so the pass
`ContextMiddleware` makes at it binds `None` and `context.bind` drops it —
which is how every REST and admin line in the sink came to carry no session at
all (O1-2(c); `deploy/observability/queries/o1-2c-the-session.sql`). The answer
is a second pass rather than a reorder, because this one's position is what
gets a `request_id` onto a static file, a CORS preflight and anything raised
below: `TenantMiddleware`, which already runs after the session and already
re-binds what the request turned out to be, binds it there.

`TenantMiddleware` then answers "on whose behalf is this request acting", from
`Membership` rows alone:

* anonymous                                  -> None
* an `X-Tenant: <slug>` the user belongs to  -> that tenant
* otherwise the user's default membership    -> that tenant
* otherwise                                  -> None

An `X-Tenant` naming a tenant the user does not belong to resolves to None, not
to the default: a request that asked for a tenant it cannot have is refused
rather than quietly answered with somebody else's data. There is no superuser
exemption — a superuser without a membership reads nothing, which is what
"fails closed" means.

Then, **after** the tenant and never before it, the same middleware answers
"which hat are they wearing" — `request.org`:

* no tenant                                        -> None
* an `X-Org: <slug>` they hold a role over         -> that organization
* otherwise their default membership's own org     -> that organization
* otherwise                                        -> None

"Hold a role over" is the hierarchy's whole rule: a membership **on** that node
or on one of its **ancestors** (`authz.effective_role`). Roles inherit
downwards, so a group owner may put on a branch's hat; nothing inherits upward
or sideways, so a branch admin naming the group — or a sibling — gets `None`
and reads nothing. **Revalidated on every request**, from rows, never from a
session: a hat that survived a revoked membership would be the leak this exists
to prevent.

## The addressing-header law (ADR core-21)

`X-Tenant` and `X-Org` are **addressing** headers: they say WHERE the caller is
acting, as opposed to `Authorization`, which says WHO it is. Both halves of the
law are stated by `addressing_refusal` below and by nothing else:

* **An OMITTED header falls back to the default membership.** Untouched, and it
  is the half that must not move: a well-behaved client sees no change.
* **A SENT header that cannot be honoured for this credential REFUSES** — with
  `addressing_header_not_honoured`, out loud, rather than resolving to `None`
  and reading as empty. A template header that did not interpolate, silently
  answered with somebody else's data or with nothing at all, is the
  misconfiguration-masking class closed for `X-Org` and closed here
  for both. There is no "the pin wins quietly" third answer: a pinned token
  asked for another tenant is refused, not answered as its pin.
* **Sent means sent, empty included.** `X-Org;` — curl's sent-but-empty form —
  is a header this caller put on the request, so it is answered rather than
  ignored. The value is trimmed and lower-cased before it is matched,
  and that boundary is declared in the header's own description.
* **Foreign, nonexistent and unreachable are one answer, byte-identical.** The
  refusal fires because the slug is not one this credential can act in, never
  because of what exists — so it is no oracle over the estate. It echoes
  nothing the caller did not itself assert, which is why the body names the
  header and never the slug.

`resolve_tenant` and `resolve_org` keep returning `None` — they are the
resolution, not the refusal — and every door asks `addressing_refusal` for the
second half. A door with no body to carry a refusal in (the socket handshake)
resolves nowhere and closes, which is the same law said in the only vocabulary
that transport has.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import Resolver404, resolve

from apps.core import context
from apps.core.authz import chain_over
from apps.core.exceptions import (
    REFUSALS,
    DomainError,
    Forbidden,
    Invalid,
    Remedy,
    register_refusal,
    wire_refusal,
)
from apps.core.models import Membership, Organization, Tenant
from apps.core.roads import road
from apps.core.surfaces import (
    Surface,
    SurfaceUnknownHost,
    claimed_elsewhere,
    named,
    resolve_surface,
    tenant_from_host,
)

TENANT_HEADER = "X-Tenant"
ORG_HEADER = "X-Org"
#: The header the socket door reads the host from. The HTTP door asks Django's
#: own reader, which validates the host against `ALLOWED_HOSTS`; an ASGI scope
#: has no such reader, so the name is declared here, once (rule 40).
HOST_HEADER = "Host"
REQUEST_ID_HEADER = "X-Request-Id"
#: The correlation chain's header on HTTP, declared here once — every door that
#: speaks HTTP, inbound and outbound (the REST and admin door, the MCP door, an
#: outbound webhook, a connection's client). Temporal carries the same chain
#: under its own spelling, `apps.core.headers.CORRELATION_HEADER`, because a
#: Temporal header is a lowercase, namespaced key and not an HTTP field. Two
#: transports, two spellings, one constant each.
CORRELATION_ID_HEADER = "X-Correlation-Id"
#: The credential header, declared HERE — once, at the bottom of the layering —
#: because four things above read it and every one of them is above `core`:
#: `accounts.auth` (the token door), `core.idempotency` (the claim is scoped to
#: the credential that made it), `config.mcp` (the machine door's bearer) and
#: `realtime.middleware` (the socket handshake's). It used to be declared twice,
#: in `accounts` and in `idempotency`, because `core` may not import `accounts`
#: (house rule 7, the fixed layer direction) — two spellings of one value, which
#: is precisely the shape rule 40 exists to close. Downward imports, one home.
AUTHORIZATION_HEADER = "Authorization"

# `core` is below `accounts` and does not import it; the user is typed as the
# base class every user model derives from, and looked up by primary key.
ActingUser = AbstractBaseUser | AnonymousUser | None


def was_sent(requested_slug: str | None) -> bool:
    """Did this request SEND the header at all?

    `None` is the header's absence; **every string is a header that was sent**,
    the empty one included. Truthiness is what got this wrong: `X-Org;` (curl's
    sent-but-empty form) and a template header that did not interpolate both
    arrive as `""`, and reading that as "not sent" handed the caller the default
    hat's whole bill under a header they had explicitly set. One
    predicate, so no door can spell "sent" a second way.
    """
    return requested_slug is not None


def resolve_tenant(
    *,
    user: ActingUser,
    requested_slug: str | None,
    surface: Surface | None = None,
    host: str = "",
) -> Tenant | None:
    """The resolution rule, without a request — so the socket side can share it.

    **The surface decides HOW the tenant is chosen** (`surface.tenant_rule`), and
    which memberships count at all — a membership whose role the surface does
    not admit resolves nothing there, the same silence as a dark tenant's:

    * `addressed` — today's rule, below, unchanged: `X-Tenant` or the default.
    * `host` — the slug the surface's `{tenant}` host slot captured from `host`.
      A sent `X-Tenant` that disagrees is the addressing refusal, asked by the
      door exactly as it is for any other unhonoured header.
    * `membership` — the person's ONE workspace among the admitted memberships.
      None is `None`; two is `AmbiguousTenant`, because picking one would put the
      person somewhere they did not choose. `X-Tenant` is not read at all: the
      door refuses a sent one (`addressing_refusal`).

    `surface=None` is the doors that do not resolve a surface yet (the token and
    machine doors) and reads as the implicit staff surface's `addressed`.

    Resolution only: it answers `None` for anything it cannot honour and says
    nothing about whether that is a refusal. `addressing_refusal` is the half
    that decides, and every door asks it (the addressing-header law, above).

    **A tenant that is not ACTIVE is a place nobody may act** (R1-F3). It
    resolves exactly like a tenant you hold no membership in: `addressing_refusal`
    then says so for a sent header, and the door's own no-tenant answer says so
    for an omitted one (ADR core-21) — one law, one function, three doors, and
    no new refusal code. `Tenant.status` had one owner
    (`suspend_tenant`/`resume_tenant`/`close_tenant`) and, until this line, no
    reader at all: a suspended tenant was fully alive on REST, MCP and the
    socket. The predicate is `Tenant.is_active`, read here and at
    `accounts.services.authenticate_token`'s pinned branch, never a second
    spelling of `ACTIVE`.

    It costs no statement: the row is already loaded by `select_related`.

    The operator's own recovery path does not come through here —
    `suspend_tenant` and `resume_tenant` take the `Tenant` ROW, from the admin
    or from `manage.py` — so a dark tenant can still be resumed (principle 19).
    """
    if user is None or not user.is_authenticated:
        return None
    memberships = _admitted(Membership.objects.of(user).select_related("tenant"), surface)
    rule = surface.tenant_rule if surface is not None else "addressed"
    if rule == "membership":
        return _the_one_workspace(memberships)
    if rule == "host":
        slug = tenant_from_host(host, surface) if surface is not None else None
        if not slug:
            return None
        return _active(memberships.filter(tenant__slug=slug).first())
    if was_sent(requested_slug):
        wanted = str(requested_slug).strip().lower()
        # A sent-but-empty slug matches no tenant, and it must NOT fall through
        # to the default: the caller named somewhere, and nowhere is not the
        # default. The query is skipped because `slug` is non-empty by
        # construction, not because the header was ignored.
        if not wanted:
            return None
        membership = memberships.filter(tenant__slug=wanted).first()
        return _active(membership)
    membership = memberships.filter(is_default=True).first()
    return _active(membership)


def _admitted(memberships: QuerySet[Membership], surface: Surface | None) -> QuerySet[Membership]:
    """The memberships whose role this surface admits — every one, for a total surface.

    A surface naming its roles admits those; a total one (`ALL`) admits every
    role no OTHER surface names, because a role belongs to one surface. With no
    surface declared that is every membership, and the query is untouched.
    """
    if surface is None:
        return memberships
    admitted = named(surface.roles)
    if admitted is None:
        claimed = claimed_elsewhere(surface)
        # role-value: a surface admits the role KEYS a product declared for it —
        # which memberships count at this host, never how much authority one holds
        return memberships.exclude(role__in=claimed) if claimed else memberships
    # role-value: a surface admits the role KEYS a product declared for it —
    # which memberships count at this host, never how much authority one holds
    return memberships.filter(role__in=admitted)


def _the_one_workspace(memberships: QuerySet[Membership]) -> Tenant | None:
    """The one ACTIVE tenant among these memberships; `AmbiguousTenant` for two or more."""
    tenants = {m.tenant_id: m.tenant for m in memberships if m.tenant.is_active}
    if len(tenants) > 1:
        raise AmbiguousTenant()
    return next(iter(tenants.values()), None)


def _active(membership: Membership | None) -> Tenant | None:
    """The membership's tenant, or `None` when there is none or it is dark.

    One function for the two branches, so "not ACTIVE" cannot come to mean two
    things depending on whether a header was sent.
    """
    if membership is None:
        return None
    tenant = membership.tenant
    return tenant if tenant.is_active else None


@road("resolve_hat", example="apps/core/middleware.py::TenantMiddleware.__call__")
def resolve_org(
    *,
    user: ActingUser,
    tenant: Tenant | None,
    requested_slug: str | None,
) -> Organization | None:
    """The hat from `X-Org`, revalidated — one function, so every door shares it.

    Fails closed at every step: no user, no tenant, an unknown slug, or a slug
    the user holds no role over all resolve to `None`, and `None` makes every
    org-scoped read empty.

    **It also fills the tenant-root memo when the hat it resolved IS the root.**
    This is the one function all four doors call, so it is the one place that
    reliably holds an `Organization` before any service runs — and in a flat
    product the hat is always the root, while in a networked one it is the root
    for everybody administering the whole tenant. Handing it to
    `Tenant.remember_root` costs a `parent_id is None` test and saves the
    request's first tenant-wide read a second fetch of the row already in hand.
    `remember_root` is the judge of whether the node qualifies; nothing here
    takes the resolution's word for it. The contract is declared on `Tenant`.
    """
    if user is None or not user.is_authenticated or tenant is None:
        return None
    memberships = list(
        Membership.objects.for_tenant(tenant).of(user).select_related("organization")
    )
    if not memberships:
        return None
    if was_sent(requested_slug):
        slug = str(requested_slug).strip().lower()
        if not slug:
            # Sent and empty. Not the default — see `was_sent`.
            return None
        wanted = Organization.objects.for_tenant(tenant).filter(slug=slug).first()
        if wanted is None:
            return None
        # On it, or under it. Nothing upward, nothing sideways — the same
        # prefix test `visible_to` uses, asked of the hat instead of the rows.
        holds = any(chain_over(memberships, wanted))
        if not holds:
            return None
        tenant.remember_root(wanted)
        return wanted
    default = next((m for m in memberships if m.is_default), memberships[0])
    tenant.remember_root(default.organization)
    return default.organization


# --- The addressing-header law, as a refusal (ADR core-21) --------------------
#
# Registered HERE, beside the two constants it is about and the two resolvers it
# is the second half of, for the reason the whole grammar is declared beside its
# raise site: this module is where the product decides which tenant and which
# hat a request is acting under, and the fact and the remedies are about that
# decision. `config/api.py` adds nothing but the number.
#
# ONE code for both headers, deliberately. The failure is the same failure —
# "you named somewhere you cannot act" — and a client branching on two codes
# would write the same handler twice. WHICH header it was is in `detail`, which
# is the half that changes per request; the code is the half that does not.


register_refusal(
    code="addressing_header_not_honoured",
    boundary="door",
    remedy=(
        "The credential is fine and the addressing header is not. The caller sent "
        f"`{TENANT_HEADER}` or `{ORG_HEADER}` naming somewhere this credential cannot act "
        "— a slug that is not theirs, one that does not exist, one their hat does not "
        "cover, or an empty value from a template that did not interpolate. Check the "
        "caller's Membership rows for the slug it sent before assuming the header is "
        "wrong; and remember an omitted header is legal and falls back to the default "
        "membership, so 'send nothing' is a real answer for a client that does not care."
    ),
    fact=(
        "You are who you say you are, and this request named a place it cannot act in. "
        "An address you hold no membership in, one that does not exist, one your acting "
        "organization does not cover, and an empty value are all answered exactly the "
        "same way — the refusal is about what you asked for, never about what exists, so "
        "it confirms nothing. Nothing was read and nothing was written. Leaving the "
        "header out is different and still works: it acts in your default membership."
    ),
    remedies=(
        Remedy(
            "Name a tenant you hold a membership in, or send no such header",
            f"header:{TENANT_HEADER}",
        ),
        Remedy(
            "Name an organization you hold a role on, or above — roles inherit downwards only",
            f"header:{ORG_HEADER}",
        ),
        Remedy("Check which memberships you actually hold", "self:membership"),
    ),
    # 403, its base class's, declared here rather than appended to a table under
    # `config/` (ADR core-23). The number was always right on the wire — what
    # this line buys is the DOCUMENT, which is written off the code and used to
    # need a `config/api.py` edit to hear about a refusal declared in `apps/`.
    status=403,
)


class AddressingHeaderNotHonoured(Forbidden):
    """A sent addressing header this credential cannot be given.

    A `Forbidden`, so the one mapper answers it 403 by walking the class tree —
    the same construction `InsufficientScope` and `SessionRequired` use. **403
    and not 401 is the whole point of this refusal**: the credential authenticated, and
    the 401 it used to get said "we could not tell who is making this request"
    over a live token belonging to a real, active user. E9's grammar refuses a
    fact that is false, and that one was.
    """

    code = "addressing_header_not_honoured"
    default_detail = (
        "This request named a place it cannot act in. Send an address you hold, or send "
        "none and act in your default membership."
    )


# --- A surface that chooses the workspace by membership, and a person with two -
#
# Registered here, beside `resolve_tenant`, which is where it is decided: on a
# surface whose tenant rule is `membership` the workspace is the person's ONE
# membership among the roles that surface admits, and a person with two has not
# chosen. Picking one would act somewhere they did not ask to be.

register_refusal(
    code="ambiguous_tenant",
    boundary="door",
    remedy=(
        "The request's surface chooses the tenant by membership, and this person holds "
        "admitted memberships in more than one active tenant. A surface that must serve "
        "such people binds a `{tenant}` host (tenant rule `host`) so each address names "
        "one; otherwise the person signs in at an address that names their workspace."
    ),
    fact=(
        "You belong to more than one workspace that this address serves, and this "
        "address chooses the workspace for you rather than letting you name it, so it "
        "cannot tell which one you mean. Nothing was read and nothing was written."
    ),
    remedies=(Remedy("Sign in at the address that names your workspace", "self:address"),),
    status=400,
)


class AmbiguousTenant(Invalid):
    """A `membership` surface met a person with admitted memberships in two tenants."""

    code = "ambiguous_tenant"
    default_detail = (
        "You belong to more than one workspace this address serves. Sign in at the "
        "address that names the one you mean."
    )


def _not_honoured(header: str) -> AddressingHeaderNotHonoured:
    """The refusal, naming the header and **never** the slug.

    Naming the slug back would be harmless in itself — it is the caller's own
    assertion — but it would make the foreign and the nonexistent refusal two
    different bodies, and "byte-identical whatever exists" is the anti-oracle
    property that matters here. The header is what the caller has to fix; the slug
    is already in their own request.
    """
    return AddressingHeaderNotHonoured(
        f"The `{header}` header on this request names somewhere this credential cannot "
        "act, so nothing was read and nothing was written. Send one you hold, or leave "
        "the header out and act in your default membership."
    )


def _unhonoured(sent: str | None, resolved_slug: str | None) -> bool:
    """Was a header sent, and did the resolution land somewhere else?

    The test is on the ANSWER rather than on the reason: a slug that resolved to
    nothing and a slug that resolved to something other than what was asked for
    are the same failure, and asking it this way is what makes a pinned token
    asked for another tenant fall out of the same line as a session naming a
    tenant it has no membership in.
    """
    if not was_sent(sent):
        return False
    return resolved_slug != str(sent).strip().lower()


def addressing_refusal(
    *,
    requested_tenant: str | None,
    tenant: Tenant | None,
    requested_org: str | None,
    org: Organization | None,
    surface: Surface | None = None,
) -> AddressingHeaderNotHonoured | None:
    """The law, in one function. `None` means every sent header was honoured.

    Asked by every door after it has resolved, and by nothing else — the doors
    differ in how they SAY a refusal (a JSON body, a closed handshake) and not
    in what they refuse.

    The tenant is judged first because a hat is a place *inside* a tenant: a
    request that named a tenant it cannot have has no tree for its `X-Org` to
    be wrong against, and answering about the hat first would name the second
    mistake to somebody who has not yet been told about the first.

    **On a `membership` surface `X-Tenant` is never honourable**: the person's
    workspace is theirs, not the caller's to name, so a sent one — even one that
    names the right tenant — is refused rather than quietly ignored.
    """
    chooses_by_membership = surface is not None and surface.tenant_rule == "membership"
    if chooses_by_membership and was_sent(requested_tenant):
        return _not_honoured(TENANT_HEADER)
    if _unhonoured(requested_tenant, getattr(tenant, "slug", None)):
        return _not_honoured(TENANT_HEADER)
    if _unhonoured(requested_org, getattr(org, "slug", None)):
        return _not_honoured(ORG_HEADER)
    return None


def request_addressing_refusal(request: HttpRequest) -> AddressingHeaderNotHonoured | None:
    """`addressing_refusal` for an `HttpRequest` that has been resolved.

    Read off the request rather than re-resolved, so it costs no query and
    cannot disagree with what the door actually acted on: `request.tenant` and
    `request.org` are whatever authentication left there, whichever of the two
    HTTP doors did the leaving.
    """
    return addressing_refusal(
        requested_tenant=request.headers.get(TENANT_HEADER),
        tenant=getattr(request, "tenant", None),
        requested_org=request.headers.get(ORG_HEADER),
        org=getattr(request, "org", None),
        surface=getattr(request, "surface", None),
    )


class ContextMiddleware:
    """Binds `request_id`, `correlation_id` and `door` for the request.

    Outermost, and it puts back on the way out exactly what was there on the
    way in — `core.context.bound`'s shape, and the workflow door's: contextvars
    are per-task, but a synchronous Django worker thread outlives the request it
    just served, and a stale `tenant_id` on the next request's log lines is
    worse than none. A worker thread starts empty and every request leaves it
    empty; a caller that served the request in its own context (a test, an
    in-process call) keeps the chain it had, so the work it does next is still
    bound.

    The `session_id` pass below is the one that fires for a request that never
    reaches `SessionMiddleware` — a static file served by WhiteNoise, a CORS
    preflight — where the honest answer is that there is no session. For every
    request that does reach it, `TenantMiddleware` binds the real one.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        previous = context.get()
        context.clear()
        bound = context.from_headers(
            {
                REQUEST_ID_HEADER: request.headers.get(REQUEST_ID_HEADER, ""),
                CORRELATION_ID_HEADER: request.headers.get(CORRELATION_ID_HEADER, ""),
            }
        )
        session = getattr(request, "session", None)
        context.bind(
            **bound,
            session_id=context.hash_session(getattr(session, "session_key", None)),
            door="admin" if request.path.startswith("/admin/") else "rest",
        )
        try:
            response = self.get_response(request)
            # Handed back so a client (and a browser network tab) can quote the
            # id when reporting what went wrong.
            response[REQUEST_ID_HEADER] = str(context.value("request_id"))
            response[CORRELATION_ID_HEADER] = str(context.value("correlation_id"))
            # And what the throttles measured on the way in (ADR core-19). One
            # stamper, and the names arrive with the values so this file never
            # spells a header the throttles also spell. `rate_limit_headers`
            # answers empty for a request no bucket counted, so an unthrottled
            # path is untouched rather than told it has an allowance of zero.
            #
            # THE IMPORT IS DEFERRED, and it is a cycle and not a preference:
            # `core.api.docs` imports THIS module for its two id constants, and
            # `core.throttling` imports `core.api.docs` for the declaration
            # that documents its triple. A module-scope import here closes that
            # ring and neither order can be satisfied. Read inside the call —
            # `docs._mcp_path()`'s shape, for `docs._mcp_path()`'s reason —
            # where every module is long since loaded.
            from apps.core.throttling import rate_limit_headers

            for name, value in rate_limit_headers(request).items():
                response[name] = value
            return response
        finally:
            context.clear()
            context.bind(**previous)


#: The headers a signed door never reads: a bearer, and the two addresses.
SIGNED_DOOR_UNREAD_HEADERS = (AUTHORIZATION_HEADER, TENANT_HEADER, ORG_HEADER)

#: The refusal a signed door answers when one of those headers is sent.
SignedDoorRefusal = Callable[[Sequence[str]], DomainError]

_SIGNED_DOORS: dict[str, SignedDoorRefusal] = {}


def declare_signed_door(*, url_name: str, refusal: SignedDoorRefusal) -> None:
    """Declare a rule-3 allow-listed route whose signature is its credential; no tenant resolves."""
    from django.core.exceptions import ImproperlyConfigured

    from apps.core.checks import unauthenticated_url_names

    if url_name not in unauthenticated_url_names():
        raise ImproperlyConfigured(
            f"{url_name!r} is not on rule 3's `allow_unauthenticated` list in "
            "quality/rules.yaml, so it cannot be declared a signed door."
        )
    _SIGNED_DOORS[url_name] = refusal


def _signed_door(request: HttpRequest) -> SignedDoorRefusal | None:
    """The declared signed door this request is for, by its route's name, or `None`."""
    try:
        match = resolve(request.path_info, getattr(request, "urlconf", None))
    except Resolver404:
        return None
    return _SIGNED_DOORS.get(match.view_name)


class TenantMiddleware:
    """Sets `request.tenant` and `request.org` before any view or route sees it.

    And binds what the request turned out to be — tenant, hat, user, and the
    session, which only exists this far down the stack.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        # The host, read ONCE for the request and nowhere else: which surface
        # this address is decides which memberships count and how the tenant is
        # chosen, so it is resolved first. An unbound host answers here, before
        # anything is resolved against it.
        host = request.get_host()
        surface = resolve_surface(host)
        if surface is None:
            return _refused_here(SurfaceUnknownHost())
        request.surface = surface  # type: ignore[attr-defined]
        signed = _signed_door(request)
        if signed is not None:
            sent = [name for name in SIGNED_DOOR_UNREAD_HEADERS if name in request.headers]
            if sent:
                return _refused_here(signed(sent))
            # The connection names the tenant; nothing on the request may.
            request.tenant = None  # type: ignore[attr-defined]
            request.org = None  # type: ignore[attr-defined]
            context.bind(surface=surface.key)
            return self.get_response(request)
        # `apps.core.requests.TenantRequest` is the declared shape of a request
        # past this point; `HttpRequest` itself has no `tenant` attribute.
        try:
            tenant = resolve_tenant(
                user=user,
                requested_slug=request.headers.get(TENANT_HEADER),
                surface=surface,
                host=host,
            )
        except AmbiguousTenant as refusal:
            return _refused_here(refusal)
        request.tenant = tenant  # type: ignore[attr-defined]
        # Strictly after the tenant: a hat is a place *inside* a tenant, so an
        # `X-Org` resolved before `X-Tenant` would be resolved against the wrong
        # tree — or against no tree at all.
        org = resolve_org(
            user=user,
            tenant=tenant,
            requested_slug=request.headers.get(ORG_HEADER),
        )
        request.org = org  # type: ignore[attr-defined]
        signed_in = user is not None and user.is_authenticated
        context.bind(
            tenant_id=str(tenant.pk) if tenant is not None else None,
            org_id=str(org.pk) if org is not None else None,
            user_id=str(user.pk) if user is not None and signed_in else None,
            actor_kind="human" if signed_in else None,
            surface=surface.key,
            # The session, bound HERE and not above, because here is where it
            # exists: `ContextMiddleware` runs outermost, above
            # `SessionMiddleware`, so its own pass sees no `request.session`
            # and binds nothing. A request with no session cookie — a token
            # call, a probe — binds `None`, which `context.bind` drops: no
            # session is the honest answer, never an invented id.
            session_id=context.hash_session(
                getattr(getattr(request, "session", None), "session_key", None)
            ),
        )
        return self.get_response(request)


def _refused_here(refusal: DomainError) -> HttpResponse:
    """A refusal this middleware decides, in the one body every door sends.

    The body is `wire_refusal`'s and the number is the one the code declared, so
    a refusal answered here reads exactly like one a route answered — no route
    has been reached yet, which is the point: neither refusal may depend on one.
    """
    # Every code this module answers declared its number where it registered;
    # one that declared none is the `error` base's answer, 500 — never a guess.
    declared = REFUSALS[refusal.code].status
    return JsonResponse(wire_refusal(refusal), status=declared or 500)
