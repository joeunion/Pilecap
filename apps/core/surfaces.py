"""Surfaces — one product, several audiences, one set of records.

A **surface** is a host name and what that host exposes: which scope families
its doors answer, which family acts a face is offered there, which role keys may
enter, how the workspace is chosen, and which screens the one face draws. Staff
at `sales.<domain>` and customers at `customer.<domain>` are two surfaces of one
product: one database, one set of services, two answers to "what may be done
from here".

**The declaration is code, the binding is environment.** A product declares its
surfaces in an app of its own — `apps/<label>/surfaces.py` exporting
`SURFACES: dict[str, Surface]` — and the one discovery walk finds it
(`core.discovery.declared`, the `discover` road), exactly as `roles.py` and
`policies.py` are found. Which host answers as which surface is
`settings.SURFACE_HOSTS` (`staff=sales.example.com,customer=...`), so moving a
staging host never edits code.

**A product that declares nothing is exactly what it was.** The platform's
`staff` surface is implicit and total — every family, every act, every role,
the tenant by header, every screen — and with `SURFACE_HOSTS` unset every host
the deployment admits is that one surface. Nothing new is refused and nothing
on the wire moves.

**The surface is a DOOR fact.** It is read once per request, from the host, by
`resolve_surface`, in the same middleware that resolves the tenant and the hat;
it rides on the request, the actor, the bound context and the audit row; and it
narrows what a door answers. No service asks it: a service that branched on the
audience would be a second permission system, and the one that exists is
`core.authz`.

**Every URL the system builds for a person goes through `absolute_url`**, with
the surface of the role the link is for (`surface_for_role`), so a customer's
invitation lands on the customer host and a staff member's on the staff host.

Imports nothing above `core`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.http.request import split_domain_port

from apps.core.exceptions import NotFound, Remedy, register_refusal
from apps.core.roads import road

TenantRule = Literal["addressed", "host", "membership"]

#: The three ways a surface chooses the workspace. `addressed`: the caller says
#: which (`X-Tenant`, today's rule). `host`: the host names it, through a
#: `{tenant}` slot in the surface's host. `membership`: the person's one
#: membership among the roles the surface admits.
TENANT_RULES: tuple[str, ...] = ("addressed", "host", "membership")

#: The platform's own surface, implicit and total until a product declares it.
STAFF = "staff"

#: Where a product declares its surfaces, and the name it exports.
DECLARATION_MODULE = "surfaces"
DECLARATION_ATTRIBUTE = "SURFACES"

#: The slot a host may carry for a surface whose tenant is named by its host.
TENANT_SLOT = "{tenant}"

#: The setting the staff host's base URL is read from, for a message that names it to an operator.
PUBLIC_BASE_URL_SETTING = "PUBLIC_BASE_URL"

#: The header a proxy we run names the client's address in — read by
#: `request_host` only when `USE_X_FORWARDED_HOST` says such a proxy exists
#: (rule 40: a header is read by its declared name).
FORWARDED_HOST_HEADER = "X-Forwarded-Host"

SURFACE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class _All:
    """The total value: every member of an open population, present and future.

    A singleton rather than a set of today's members, because a surface that
    exposes everything must go on exposing the family an app adds next month
    without anybody editing its declaration.
    """

    _instance: _All | None = None

    def __new__(cls) -> _All:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __contains__(self, item: object) -> bool:
        return True

    def __repr__(self) -> str:
        return "ALL"

    def __reduce__(self) -> str:
        return "ALL"


ALL = _All()

#: A declared population: a set of names (a frozenset once declared), or `ALL`.
Members = AbstractSet[str] | _All


def named(members: Members) -> frozenset[str] | None:
    """The names a population lists, or `None` for `ALL` — the total value lists none."""
    return None if isinstance(members, _All) else frozenset(members)


def _members(value: Any, *, name: str) -> Members:
    """A declared population as a frozenset, or `ALL` — never a bare string."""
    if isinstance(value, _All):
        return value
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ValueError(
            f"Surface.{name} is a set of names or ALL; got {value!r}. One name is still "
            f"a set — {{{value!r}}}."
        )
    return frozenset(str(item) for item in value)


@dataclass(frozen=True)
class Surface:
    """What one host exposes: families, acts, roles, the tenant rule, the screens.

    Every field is a closed question over a population the tree declares — a
    family is a `TAGS` key, an act a family verb, a role a declared role key, a
    screen a route-table row — or `ALL`. `key` is stamped by `declared()` from
    the dict the declaration sits in; a product never types it.
    """

    families: Members
    acts: Members
    roles: Members
    tenant_rule: TenantRule
    screens: Members
    key: str = field(default="")

    def __post_init__(self) -> None:
        for name in ("families", "acts", "roles", "screens"):
            object.__setattr__(self, name, _members(getattr(self, name), name=name))
        if self.tenant_rule not in TENANT_RULES:
            raise ValueError(
                f"Surface.tenant_rule is one of {', '.join(TENANT_RULES)}; "
                f"got {self.tenant_rule!r}."
            )


#: The implicit staff surface: every family, act, role and screen, the tenant by
#: header. Materialised by `declared()` whenever no app declares `staff`.
IMPLICIT_STAFF = Surface(ALL, ALL, ALL, "addressed", ALL, key=STAFF)


# --- The declarations ---------------------------------------------------------

_declared: Mapping[str, Surface] | None = None


def union(found: Iterable[tuple[Any, Mapping[Any, Any]]]) -> Mapping[str, Surface]:
    """Every app's `SURFACES` merged into one map, refused where two disagree.

    `found` is the discovery walk's answer — `(AppConfig, dict)` pairs — so a
    refusal names WHICH apps declared the thing it refuses. Two apps declaring
    one key, or one role named by two declared surfaces, is `ImproperlyConfigured`:
    a role belongs to one surface, which is what makes `surface_for_role` a
    function. The implicit total `staff` joins when nobody declared `staff`.
    """
    surfaces: dict[str, Surface] = {}
    declarer: dict[str, str] = {}
    claimed: dict[str, str] = {}
    for config, declared_here in found:
        label = str(getattr(config, "label", config))
        for raw_key, surface in declared_here.items():
            key = str(raw_key)
            where = f"apps/{label}/{DECLARATION_MODULE}.py"
            if not SURFACE_KEY.match(key):
                raise ImproperlyConfigured(
                    f"{where} declares the surface {key!r}; a surface key is lower case "
                    "with a letter first."
                )
            if not isinstance(surface, Surface):
                raise ImproperlyConfigured(
                    f"{where} declares {key!r} as {type(surface).__name__}; a surface is "
                    "`apps.core.surfaces.Surface(...)`."
                )
            if surface.key and surface.key != key:
                raise ImproperlyConfigured(
                    f"{where} declares {key!r} with key={surface.key!r}; leave `key` out — "
                    "the dict key is the surface's name."
                )
            if key in surfaces:
                raise ImproperlyConfigured(
                    f"The surface {key!r} is declared twice — by apps/{declarer[key]}/ and "
                    f"by apps/{label}/. One surface has one declaration."
                )
            for role in sorted(named(surface.roles) or ()):
                if role in claimed:
                    raise ImproperlyConfigured(
                        f"The role {role!r} is admitted by two surfaces, {claimed[role]!r} "
                        f"and {key!r}. A role belongs to one surface."
                    )
                claimed[role] = key
            surfaces[key] = replace(surface, key=key)
            declarer[key] = label
    if STAFF not in surfaces:
        surfaces[STAFF] = IMPLICIT_STAFF
    return MappingProxyType(surfaces)


def declared() -> Mapping[str, Surface]:
    """Every surface this product declared, by key, with the implicit total `staff`."""
    global _declared
    if _declared is None:
        from apps.core.discovery import declared as discover

        _declared = union(discover(DECLARATION_MODULE, DECLARATION_ATTRIBUTE, refuse_shape=True))
    return _declared


def forget_declarations() -> None:
    """Drop the memoised union; the next read walks the apps again. Tests only."""
    global _declared
    _declared = None


def by_key(key: str) -> Surface:
    """The declared surface named `key`; `ImproperlyConfigured` when nothing declares it."""
    known = declared()
    if key not in known:
        raise ImproperlyConfigured(
            f"No app declares the surface {key!r}; the declared ones are "
            f"{', '.join(sorted(known))}."
        )
    return known[key]


def surface_hosts() -> Mapping[str, str]:
    """`settings.SURFACE_HOSTS`, each key checked against the declarations.

    Empty when unset: the deployment answers at every admitted host as `staff`.
    A key naming a surface nobody declared is refused by name rather than
    resolving nowhere, which would read as a host that answers nothing.
    """
    hosts: Mapping[str, str] = getattr(settings, "SURFACE_HOSTS", None) or {}
    for key in hosts:
        by_key(key)
    return hosts


def _host_pattern(host: str) -> re.Pattern[str]:
    escaped = re.escape(host).replace(re.escape(TENANT_SLOT), r"(?P<tenant>[a-z0-9][a-z0-9-]*)")
    return re.compile(escaped)


def _bindings(host: str) -> Iterator[tuple[str, re.Match[str] | None]]:
    """Every bound surface this host matches — exact names first, then patterns."""
    name, _port = split_domain_port(host)
    bound = surface_hosts()
    for key, pattern in bound.items():
        if TENANT_SLOT not in pattern and name == pattern:
            yield key, None
    for key, pattern in bound.items():
        if TENANT_SLOT in pattern:
            match = _host_pattern(pattern).fullmatch(name)
            if match is not None:
                yield key, match


@road(
    "request_host",
    example="apps/core/tests/test_surfaces.py::test_the_socket_and_machine_doors_read_the_host_the_http_door_reads",
)
def request_host(headers: Iterable[tuple[bytes, bytes]]) -> str:
    """The host an ASGI request was addressed to: what `request.get_host()` answers on HTTP.

    The socket and MCP doors have no Django request to ask, so they ask this,
    and the three doors answer one host: `X-Forwarded-Host` when
    `USE_X_FORWARDED_HOST` is on and the header was sent, `Host` otherwise —
    Django's own order (`HttpRequest._get_raw_host`), value and port as sent.
    The port is stripped once, where every door's host is matched
    (`_bindings`), not here. With the setting off a forwarded host is IGNORED:
    a client cannot choose its audience with a header no proxy of ours set.
    """
    # Declared beside the other request headers in `core.middleware`, which
    # imports this module — so it is read at call time, never at import.
    from apps.core.middleware import HOST_HEADER

    names = (
        (FORWARDED_HOST_HEADER, HOST_HEADER) if settings.USE_X_FORWARDED_HOST else (HOST_HEADER,)
    )
    sent: dict[bytes, bytes] = {}
    for key, value in headers:
        sent.setdefault(
            key.lower(), value
        )  # the first of a repeated header, as the doors always read it
    for name in names:
        found = sent.get(name.lower().encode("latin-1"))
        if found is not None:
            return found.decode("latin-1")
    return ""


@road(
    "resolve_surface",
    example=(
        "apps/example_portal/tests/test_api.py"
        "::test_the_customer_host_answers_its_surface_and_its_screens"
    ),
)
def resolve_surface(host: str) -> Surface | None:
    """The surface a host answers as; `None` when the hosts are bound and this is none of them.

    Called ONCE per request, by the doors that resolve the tenant, before they
    resolve it — the host is read nowhere else. The port is stripped; an exact
    host in `SURFACE_HOSTS` wins, then a `{tenant}` pattern. With `SURFACE_HOSTS`
    unset every admitted host is `staff`. With it set, a host that matches
    nothing is `None` and the door refuses it — never a fall back to `staff`,
    which would hand an unconfigured name the staff doors.
    """
    if not surface_hosts():
        return by_key(STAFF)
    for key, _match in _bindings(host):
        return by_key(key)
    return None


def tenant_from_host(host: str, bound_to: Surface) -> str | None:
    """The tenant slug a `host`-rule surface's `{tenant}` slot captured from `host`."""
    for key, match in _bindings(host):
        if key == bound_to.key and match is not None:
            return match.group("tenant")
    return None


def of_request(request: HttpRequest) -> Surface | None:
    """The surface a door resolved for this request.

    A request no middleware resolved (a door driven below the stack) is `staff`
    only while no hosts are bound; with hosts bound it is `None` and every door
    refuses it, because an unresolved audience is not the staff audience.
    """
    resolved = getattr(request, "surface", None)
    if isinstance(resolved, Surface):
        return resolved
    return None if surface_hosts() else by_key(STAFF)


def exposes(surface: Surface | None, family: str | None) -> bool:
    """Does this surface answer an operation of this scope family? Unresolved: no."""
    if surface is None:
        return False
    if surface.families is ALL:
        return True
    return family is not None and family in surface.families


def acts(key: str) -> Members:
    """The family acts the surface named `key` offers; nothing for a key nobody declared."""
    known = declared().get(key)
    return known.acts if known is not None else frozenset()


def claimed_elsewhere(surface: Surface) -> frozenset[str]:
    """The role keys another surface names — the ones a total surface does not admit."""
    return frozenset(
        role
        for key, other in declared().items()
        if key != surface.key
        for role in named(other.roles) or ()
    )


@road(
    "surface_for_role",
    example=(
        "apps/example_portal/tests/test_api.py"
        "::test_the_customer_role_belongs_to_the_customer_surface"
    ),
)
def surface_for_role(role_key: str) -> Surface:
    """The surface a role belongs to: the declared one that names it, else `staff`.

    A role belongs to one surface — `union` refuses two naming it — so this is a
    function, and it is how a link built for a person lands on their host.
    """
    for candidate in declared().values():
        if role_key in (named(candidate.roles) or ()):
            return candidate
    return by_key(STAFF)


@road(
    "absolute_url",
    example="apps/core/tests/test_surfaces.py::test_a_customer_invitation_lands_on_the_customer_host",
)
def absolute_url(*, path: str, surface: Surface | str, tenant: str | None = None) -> str:
    """The full URL of `path` on `surface`'s host — every link the system sends is built here.

    The host is the surface's binding in `SURFACE_HOSTS`; the scheme and the
    port are `PUBLIC_BASE_URL`'s. With no hosts bound — and for `staff` when
    only other surfaces are bound — it is `PUBLIC_BASE_URL` joined to `path`,
    exactly the link the deployment built before surfaces. A surface whose host
    carries a `{tenant}` slot needs `tenant`; a surface with no host at all while
    others are bound is `ImproperlyConfigured`, because the only other answer is
    a customer's link on the staff host.
    """
    key = surface if isinstance(surface, str) else surface.key
    bound = surface_hosts()
    host = bound.get(key)
    if host is None:
        if not bound or key == STAFF:
            return f"{settings.PUBLIC_BASE_URL}{path}"
        raise ImproperlyConfigured(
            f"The surface {key!r} has no host in SURFACE_HOSTS, so a link built for it "
            f"has nowhere to land. Bind it: SURFACE_HOSTS=...,{key}=<host>."
        )
    if TENANT_SLOT in host:
        if not tenant:
            raise ValueError(
                f"The surface {key!r} is named by its host ({host!r}); a link for it needs "
                "the tenant slug."
            )
        host = host.replace(TENANT_SLOT, tenant)
    base = urlsplit(settings.PUBLIC_BASE_URL)
    port = f":{base.port}" if base.port else ""
    return f"{base.scheme or 'https'}://{host}{port}{path}"


def surface_base_urls() -> list[str]:
    """Every base URL a browser signs in from: the deployment default, then each bound surface.

    Built by `absolute_url`, so a surface's base is the one every link to it is
    built with. The identity platform's browser client registers a callback at
    each of these (`zitadel_seed`) and the drift report declares the same list
    (`zitadel_audit`) — one derivation, two readers, so the two cannot come to
    disagree about which hosts may finish a sign-in. A `{tenant}` host is left
    out: the platform matches redirect URIs exactly, so a pattern registers
    nothing (a product with a host-rule surface registers its tenants' hosts).
    """
    bases = [str(settings.PUBLIC_BASE_URL).rstrip("/")]
    for key, host in surface_hosts().items():
        if TENANT_SLOT not in host:
            bases.append(absolute_url(path="", surface=key).rstrip("/"))
    return list(dict.fromkeys(bases))


# --- The refusals -------------------------------------------------------------
#
# Registered HERE, beside the resolver that decides them (E9: a refusal is
# declared beside its raise site). Both are the reach-refusal posture (rule 26):
# a customer host is not an oracle for the staff door map, so neither names a
# family, a route or another surface's host.

register_refusal(
    code="surface_does_not_expose",
    boundary="door",
    remedy=(
        "The operation's scope family is not in the families the request's surface "
        "declares (`apps/<label>/surfaces.py`). Either the caller is on the wrong host "
        "for this operation, or the product meant this surface to offer the family and "
        "its declaration should name it. Check `SURFACE_HOSTS` for which host is which."
    ),
    fact=(
        "There is no such operation at this address. What one address offers is not "
        "what another offers, and an operation this address does not offer answers "
        "exactly as one that does not exist, so nothing here says what exists elsewhere. "
        "Nothing was read and nothing was written."
    ),
    remedies=(Remedy("Read what this address offers", "docs:openapi"),),
    status=404,
)


class SurfaceDoesNotExpose(NotFound):
    """The operation's family is not one this host's surface exposes. 404, never 403."""

    code = "surface_does_not_expose"
    default_detail = "There is no such operation at this address."


register_refusal(
    code="surface_unknown_host",
    boundary="door",
    remedy=(
        "`SURFACE_HOSTS` is set and the request's host matches none of its bindings, "
        "so no surface answers it. Bind the host to a surface, or send the request to "
        "a host that is bound; an unbound host is never treated as the staff surface."
    ),
    fact=(
        "This address is not one this product answers at. Nothing was read and nothing was written."
    ),
    remedies=(Remedy("Use the address you were given for this product", "self:address"),),
    status=404,
)


class SurfaceUnknownHost(NotFound):
    """The hosts are bound and this request's host is none of them."""

    code = "surface_unknown_host"
    default_detail = "This address is not one this product answers at."


def does_not_expose(surface: Surface) -> SurfaceDoesNotExpose:
    """The refusal for an operation `surface` does not offer, naming that surface alone."""
    return SurfaceDoesNotExpose(
        remedies=(
            Remedy("Read what this address offers", "docs:openapi"),
            Remedy("Ask which surface this address is", f"surface:{surface.key}"),
        ),
    )
