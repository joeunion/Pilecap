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
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

from apps.core.mcp import MCP_PATH

__all__ = ["Door", "Resource", "doors", "index", "rest_resources", "template_version"]

#: The namespace `config/urls.py` mounts the ninja API under. Named once, and
#: read rather than assumed: `_api_mount()` returns None when nothing answers to
#: it, and then the REST rows are simply absent instead of the page lying.
API_NAMESPACE = "api"

#: The file that says which template version this tree was cloned from. It is a
#: file and not a setting because that is where the repository already keeps it
#: (`apps/core/tests/test_settings.py` reads the same one); a product that
#: prefers a setting may define `TEMPLATE_VERSION` and it wins.
VERSION_FILE = "TEMPLATE_VERSION"


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


def _api_route_names(mount: URLResolver) -> list[str]:
    """Every named route under the API mount, namespace included.

    Recursive, because how deeply the mount nests its routers is the mount's
    business and not something this page should depend on.
    """
    found: list[str] = []
    for entry in mount.url_patterns:
        if isinstance(entry, URLResolver):
            found.extend(_api_route_names(entry))
        elif isinstance(entry, URLPattern) and entry.name:
            found.append(f"{API_NAMESPACE}:{entry.name}")
    return found


def template_version() -> str:
    """What this deployment was cloned from — the setting, else the file.

    Read on each request rather than cached at import: this page is asked for by
    a person once in a while, a file read costs nothing at that rate, and a
    cached module-level value is one more thing that can be stale on a box
    somebody redeployed under.
    """
    configured = str(getattr(settings, "TEMPLATE_VERSION", "") or "")
    if configured:
        return configured
    try:
        return (Path(settings.BASE_DIR) / VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
    for name in _api_route_names(mount):
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
