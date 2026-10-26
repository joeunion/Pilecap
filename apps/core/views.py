"""The root page: which doors this deployment has, and where they answer.

Without it, `/` on a live box is Django's bare "Not Found" — the first thing an
owner, an operator or a third party sees, and it says nothing about a running
product. This is the index: the doors, each as a link, and the template version
this deployment was cloned from.

**It is derived, never typed.** Every href here is either `reverse()`d out of
the live URL configuration or read from a constant the mount itself reads:

* the REST door — `reverse("api:openapi-view")`, which is wherever
  `config/urls.py` hung the API's version segment, not `/api/v1/docs` spelled
  out here;
* the machine door — `apps.core.mcp.MCP_PATH`, the same constant
  `config/asgi.py` routes on;
* the human door — `reverse("account_login")`, allauth's own name;
* the two probes — `reverse("healthz")` / `reverse("readyz")`.

The consequence is the point: a door that is not mounted has no name to
reverse, so it is not on the page. That is what makes the page honest when an
app is switched off (`DJB_DISABLED_APPS`) — the widgets resource disappears
from the list because `api:widget-list` stops resolving, and nobody had to
remember to delete a line.

**A mechanism, not a front end.** A product that wants a landing page mounts
its own `path("", ...)` ahead of this one in its root URLconf; nothing here is
meant to be styled, extended or made into a design. It is the moral equivalent
of a directory listing.

The view answers without a credential, deliberately and narrowly: it names
doors and opens none. Every href on it is a public route or a route that will
itself demand a credential when it is followed, and the page reads no request
state at all — no session, no tenant, no user. Recorded in `quality/rules.yaml`
under rule 3 (`allow_unauthenticated_views`) with that reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, URLResolver, get_resolver, reverse
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.core.authz import chain_over, memberships_in
from apps.core.mcp import MCP_PATH
from apps.core.middleware import ORG_HEADER, TENANT_HEADER
from apps.core.models import Organization, Tenant
from apps.core.requests import TenantRequest

__all__ = [
    "Door",
    "Resource",
    "doors",
    "index",
    "rest_resources",
    "template_version",
    "welcome",
]

#: The namespace `config/urls.py` mounts the ninja API under. Named once, and
#: read rather than assumed: `_api_mount()` returns None when nothing answers to
#: it, and then the REST rows are simply absent instead of the page lying.
API_NAMESPACE = "api"


@dataclass(frozen=True)
class Door:
    """One row on the index: a label, where it answers, and what it is for."""

    label: str
    href: str
    what: str


@dataclass(frozen=True)
class Resource:
    """One REST prefix the API mounted.

    `href` is `None` when the prefix is only a namespace — `/api/v1/auth/` has
    `realm/` and `sso-connections/` under it and nothing AT it, so
    linking the prefix would be offering a 404. The path is still worth printing:
    it is what this deployment mounted, and the browsable contract at the REST
    door has the routes.
    """

    label: str
    path: str
    href: str | None


def _reverse(name: str) -> str | None:
    """The URL that name resolves to, or None when nothing is mounted under it."""
    try:
        return str(reverse(name))
    except NoReverseMatch:
        return None


def _api_mount() -> URLResolver | None:
    """The resolver `config/urls.py` mounted the API under, if it mounted one."""
    for entry in get_resolver().url_patterns:
        if isinstance(entry, URLResolver) and entry.namespace == API_NAMESPACE:
            return entry
    return None


def _api_route_names() -> list[str]:
    """Every named operation the API mounts, namespace included.

    Read through `apps.core.api.mount.bound_operations`, the one mount reader
    (imported inside the call: it imports `config.api` lazily), so this page
    lists exactly what every other reader of the mount reads.
    """
    from apps.core.api.mount import bound_operations

    return [f"{API_NAMESPACE}:{name}" for _path, name, _operation in bound_operations() if name]


def template_version() -> str:
    """What this deployment was cloned from — `settings.TEMPLATE_VERSION`, the file's one reader.

    The setting is unconditional (`config/settings/base.py::read_template_version`,
    the `version` road, reads the `TEMPLATE_VERSION` file once at start), so this
    page reads the setting and nothing else — a second reader of the file with a
    fallback of its own would be a second answer to one question.
    """
    return str(settings.TEMPLATE_VERSION)


def doors() -> tuple[Door, ...]:
    """The doors that are actually mounted, in the order a person reads them.

    A door whose name does not resolve is dropped rather than rendered dead: the
    page is a report on what this process mounted, so an unmounted door is an
    absent row and never a broken link.
    """
    candidates: tuple[tuple[str, str | None, str], ...] = (
        (
            "REST",
            _reverse(f"{API_NAMESPACE}:openapi-view"),
            "The HTTP contract, browsable. Every resource below is in it.",
        ),
        (
            "MCP",
            MCP_PATH,
            "The machine door: the same services, over Streamable HTTP, on a bearer token.",
        ),
        (
            "Sign in",
            _reverse("account_login"),
            "The human door.",
        ),
        (
            "Liveness",
            _reverse("healthz"),
            "Is this process up. Asked by an orchestrator, not by a person.",
        ),
        (
            "Readiness",
            _reverse("readyz"),
            "Is this process willing to be sent traffic.",
        ),
    )
    return tuple(Door(label, href, what) for label, href, what in candidates if href)


def rest_resources() -> tuple[Resource, ...]:
    """The REST prefixes this process mounted, one row each, reversed.

    Derived by reversing every argument-free route under the API mount and
    keeping the first path segment of each — so the population is whatever
    `config/api.py` discovered, and an app that is not installed contributes
    nothing because its route names do not resolve.

    A prefix is only LINKED when some route reverses to exactly the collection
    root. `/api/v1/widgets/` is a route; `/api/v1/auth/` is not — everything
    lives one level below it — and a directory listing whose rows 404 is worse
    than one that says which rows are namespaces.

    Declared limit: this says the collection root EXISTS, not that it answers
    GET. `/api/v1/tokens/` is POST-only today, so following that row gets a 405
    — a real answer from a real door, unlike a 404. Which methods a route offers
    is the ninja registry's, not the URL configuration's, and reaching into it
    from here would couple this page to the mount it is only supposed to report
    on; `/api/v1/docs` is where the methods are.
    """
    mount = _api_mount()
    if mount is None:
        return ()
    prefix = f"/{mount.pattern}"
    roots: set[str] = set()
    segments: set[str] = set()
    for name in _api_route_names():
        url = _reverse(name)
        if url is None or not url.startswith(prefix):
            continue
        roots.add(url)
        segment = url[len(prefix) :].split("/")[0]
        # `openapi.json` and `docs` are the API's own documents, listed as the
        # REST door above rather than as resources of it.
        if segment and "." not in segment and segment != "docs":
            segments.add(segment)
    return tuple(
        Resource(segment, path, path if path in roots else None)
        for segment in sorted(segments)
        for path in [f"{prefix}{segment}/"]
    )


def index(request: HttpRequest) -> HttpResponse:
    """`GET /` — the door index. No credential, no request state, no writes."""
    return render(
        request,
        "core/index.html",
        {
            "doors": doors(),
            "resources": rest_resources(),
            "version": template_version(),
        },
    )


def _roles_over(
    user: AbstractBaseUser | None, tenant: Tenant | None, org: Organization | None
) -> list[str]:
    """The role keys this person holds on `org` or an ancestor of it, sorted; `[]` for none."""
    if tenant is None or (org is not None and org.tenant_id != tenant.pk):
        return []
    return sorted({str(m.role) for m in chain_over(memberships_in(user, tenant), org)})


@login_required
@ensure_csrf_cookie
def welcome(request: TenantRequest) -> HttpResponse:
    """`GET /welcome/` — where a completed sign-in lands, and what it landed as.

    **Why this exists at all.** `LOGIN_REDIRECT_URL` used to be `"/"`, so the
    last screen of the sign-in chain was the door index: a monospace directory
    listing addressed to an operator, reached by a person who had just typed a
    password. It is the one screen of the first minute that says nothing about
    the person who just arrived, and it was the fourth of the four defects the
    entrance survey measured.

    **What it shows, and why those four facts.** Not a greeting: the four
    things a session actually IS here, which are the four things that go wrong
    invisibly. *Who* you are, *whose* data you are in (`X-Tenant` resolved
    against your memberships), *which hat* you are wearing inside that tenant
    (`X-Org`, resolved by `core.middleware.resolve_org` — the one function all
    four doors call), and *what that hat can do* (the role keys held on it or
    on an ancestor — roles inherit downwards). A person who signs in and reads "no organization
    resolved" has been told, on the first screen, the thing that would
    otherwise have shown up an hour later as an empty list with no explanation
    — because every org-scoped read fails closed on an unresolved hat, and
    fails closed by returning NOTHING rather than by refusing.

    **It is a worked example, not a landing page.** A product mounts its own
    `path("welcome/", ...)` ahead of this one — or points `PRODUCT_BASE_URL` at
    its front end, which is what `LOGIN_REDIRECT_URL` derives from — and this
    disappears without anybody deleting it. It is SHADOWED, not configured.

    **It reads, and only reads.** No service call, no write, no `emit`. The
    role lookup is one query over the person's memberships; the tenant and the hat
    were already resolved by `TenantMiddleware` before this function was
    reached, so the page reports what the request WAS rather than re-deriving
    it — which is the point of showing it at all.

    **The one place it says what to do next, and the one condition on it.** An
    unresolved tenant has two entirely different causes. On a fresh clone
    nobody has made a tenant yet and the next act is one command; on a live
    installation the reader simply has no membership, and telling *them* to
    open a shell is advice the machine would refuse (`create_first_tenant`
    raises `Conflict` the moment a tenant exists). So the page tells the two
    apart on that same predicate — `Tenant.objects.exists()` — and the command
    sentence appears only on the empty installation, addressed to the reader's
    own email. The query is the second half of an `and`, so a request that
    resolved a tenant never pays for it.

    **`ensure_csrf_cookie` is deliberate and it is this page's second job.**
    A front end bootstrapping from a session has to get `csrftoken` from
    somewhere before it can send `X-CSRFToken` on its first write, and until
    now the settings comment beside `CSRF_COOKIE_*` named that page in the
    abstract — "whatever page the front end bootstraps from" — while this tree
    mounted no such page at all. This is it: the first authenticated HTML a
    signed-in browser is guaranteed to have been handed.
    """
    # `@login_required` has already refused an anonymous request, so this is a
    # real person — but `HttpRequest.user` is typed as the union and
    # `AnonymousUser` is not an `AbstractBaseUser`, so the narrowing is written
    # out rather than asserted away with a cast.
    user = request.user if request.user.is_authenticated else None
    org = request.org
    return render(
        request,
        "core/welcome.html",
        {
            "actor_email": getattr(user, "email", ""),
            "tenant": request.tenant,
            "fresh_deployment": request.tenant is None and not Tenant.objects.exists(),
            "org": org,
            "roles": _roles_over(user, request.tenant, org),
            "tenant_header": TENANT_HEADER,
            "org_header": ORG_HEADER,
            "doors": doors(),
        },
    )
