# census: cross-app population=apps/**/*.py,config/**/*.py for calls to the header resolvers
"""The addressing-header law, as a decision table, driven at every door.

The law (ADR core-21): **an addressing header (`X-Tenant`,
`X-Org`) that was SENT and cannot be honoured for this credential refuses —
truthfully and loudly. An OMITTED header falls back to the default membership.**

Before this module the platform said three different things about one question:

* `config/api.py` promised every authenticated route that "a tenant you hold no
  membership in reads as empty rather than as forbidden";
* `apps/accounts/api.py` promised a pinned token "can only ever act in that
  tenant, whatever `X-Tenant` a later request sends";
* the wire answered **401 "We could not tell who is making this request"** over
  a perfectly valid credential, 200 `[]` for an
  unpinned one, and the ROOT bill for an `X-Org` that was sent empty.

Three answers to one question is what "crossed contract" means. The table below
is the single answer, and it is the spec as well as the test: **every cell is
written here and driven**, so a door that comes to disagree with another door
fails by name rather than by somebody noticing.

## The table

Five header states × three credential kinds × two headers:

| sent            | answer                                              |
|-----------------|-----------------------------------------------------|
| omitted         | honoured — the default membership, exactly as before |
| valid           | honoured — that tenant, that hat                     |
| foreign         | **refused** `addressing_header_not_honoured` (403)   |
| nonexistent     | **refused**, byte-identical to foreign               |
| empty (`X-Org;`)| **SENT** — and refused                               |

The credential kind does not appear in the answer column, and that is the
ruling's whole content: a pinned token, an unpinned token and a browser session
that all send the same unhonourable header get the same refusal. The
disambiguation the earlier law recorded — unpinned answers `200 []`, pinned answers `401`
— was the defect, not the contract.

## The doors

`DOOR_COVERAGE` below is checked against a **derived** census: every module in
the tree that calls `resolve_tenant` or `resolve_org` is a door that reads an
addressing header, and every one of them has a row here or a declared reason it
is not driven. A door added tomorrow fails this module rather than shipping
uncovered (rule 40's census shape).

`session × MCP` is the one absent cell in the cross product and it is absent by
construction: the machine door takes a bearer token and there is no session to
present to it. It is named in `UNDRIVEN` below rather than left as a hole.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for, system_actor
from apps.core.middleware import AmbiguousTenant, resolve_tenant
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import create_organization
from apps.core.surfaces import IMPLICIT_STAFF, Surface, union
from apps.core.tests.test_mcp import MCP_HEADERS, running
from apps.core.tests.test_surfaces import (  # noqa: F401 — the surface world's fixtures, by name
    CUSTOMER_HOST,
    customer,
    customer_role,
    two_faces,
)
from apps.core.tests.tree_census import source_tree, vanishing_source_file

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
MCP_URL = "/mcp"
CODE = "addressing_header_not_honoured"
REFUSED_STATUS = 403

#: The five header states the table walks. `None` is "the header was not sent at
#: all"; every string — the empty one included — is a header that WAS sent.
OMITTED = "omitted"
VALID = "valid"
FOREIGN = "foreign"
NONEXISTENT = "nonexistent"
EMPTY = "empty"
STATES = (OMITTED, VALID, FOREIGN, NONEXISTENT, EMPTY)

#: The three credential kinds. A session is a person at a browser; the two token
#: kinds differ only in whether the token row carries a tenant.
SESSION = "session"
PINNED = "pinned-token"
UNPINNED = "unpinned-token"
KINDS = (SESSION, PINNED, UNPINNED)

HEADERS = ("X-Tenant", "X-Org")

#: The cells the cross product does not contain, named rather than skipped.
UNDRIVEN = {
    (SESSION, "mcp"): "the machine door takes a bearer token; there is no session to send",
    # The machine door accepts a THIRD credential kind — an OAuth 2.1
    # JWT from the identity platform, validated by `apps/accounts/oauth.py` —
    # and no row here drives it. It is not in `KINDS` because the door is OFF
    # in this suite and in any deployment that has not set
    # `ZITADEL_MCP_AUDIENCE`, so a row would drive a path that does not exist
    # on the tree it runs against.
    #
    # THE MITIGATION, which is why this is a declared gap and not an untested
    # entrance — both credential paths converge on ONE call. `config/mcp.py:431`
    # asks `addressing_refusal` after the credential has resolved and before
    # the transport is reached, and it asks it for whichever kind resolved —
    # the bearer token rows below and the JWT reach the same function with the
    # same four arguments. What is undriven is the RESOLUTION that feeds it,
    # not the law itself.
    #
    # What that leaves uncovered, stated: a JWT that resolved a tenant or org
    # DIFFERENTLY from a bearer token carrying the same claims would produce a
    # different refusal, and nothing here would see it. The trigger for driving
    # it is the first deployment that sets `ZITADEL_MCP_AUDIENCE`.
    ("oauth-jwt", "mcp"): (
        "the OAuth 2.1 JWT door is off without ZITADEL_MCP_AUDIENCE; both paths "
        "converge on the same addressing_refusal at config/mcp.py:431"
    ),
}

#: Every module that resolves an addressing header, and how the table reaches it.
#: Checked against the derived census in `test_the_header_reading_door_census_is_covered`.
DOOR_COVERAGE = {
    "apps/core/middleware.py": "rest — the session door, driven by every session row",
    "apps/accounts/auth.py": "rest — the bearer door, driven by every token row",
    "apps/accounts/services.py": "the one token resolver behind all three token doors",
    "apps/accounts/oauth.py": "the OAuth bearer, resolved into config/mcp.py's seam below",
    "config/mcp.py": "mcp — driven by every token row",
    "apps/core/asgi_middleware.py": (
        "socket (session) — apps/realtime/tests/test_addressing_headers.py, SOCKET_ROWS"
    ),
    "apps/realtime/middleware.py": (
        "socket (bearer) — apps/realtime/tests/test_addressing_headers.py, SOCKET_ROWS"
    ),
    "apps/workflows/context.py": (
        "workflow — the activity boundary; apps/workflows/tests/test_context.py drives "
        "the revoked, foreign, system and live hats"
    ),
}


def _slug_for(state: str, *, mine: str, foreign: str) -> str | None:
    """The header value this state sends, or `None` for a header never sent."""
    return {
        OMITTED: None,
        VALID: mine,
        FOREIGN: foreign,
        NONEXISTENT: "no-such-slug-anywhere",
        EMPTY: "",
    }[state]


def _honoured(state: str) -> bool:
    return state in (OMITTED, VALID)


# --- the world the table is driven against ------------------------------------


@pytest.fixture
def branch(tenant: Tenant, owner: User, root_org: Organization) -> Organization:
    """A second node under the tenant's root, so `X-Org` has somewhere valid to go."""
    from apps.core.actor import actor_for

    return create_organization(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
        name="Branch",
        slug="branch",
        parent=root_org,
    )


@pytest.fixture
def foreign_org(other_tenant: Tenant, other_root_org: Organization) -> Organization:
    """A real organization in a tenant the caller has nothing to do with."""
    return other_root_org


def _rest(
    *, kind: str, user: User, tenant: Tenant, plaintext: str, header: str, value: str | None
) -> Any:
    client = Client()
    headers: dict[str, str] = {}
    if kind == SESSION:
        client.force_login(user)
    else:
        headers["authorization"] = f"Bearer {plaintext}"
    if value is not None:
        headers[header.lower()] = value
    return client.get(LIST_URL, headers=headers)


# --- the table, at the REST door ----------------------------------------------


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("state", STATES)
def test_the_table_at_the_rest_door(
    state: str,
    kind: str,
    header: str,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    foreign_org: Organization,
) -> None:
    """One cell of the decision table, over HTTP, through the mounted API."""
    pinned = issue_token(
        user=owner, tenant=tenant, name="pinned", actor=actor_for(user=owner, tenant=tenant)
    )[1]
    unpinned = issue_token(
        user=owner, tenant=None, name="unpinned", actor=actor_for(user=owner, tenant=None)
    )[1]
    plaintext = pinned if kind == PINNED else unpinned

    if header == "X-Tenant":
        value = _slug_for(state, mine=tenant.slug, foreign=other_tenant.slug)
    else:
        value = _slug_for(state, mine=branch.slug, foreign=foreign_org.slug)

    response = _rest(
        kind=kind,
        user=owner,
        tenant=tenant,
        plaintext=plaintext,
        header=header,
        value=value,
    )

    if _honoured(state):
        assert response.status_code == 200, (state, kind, header, response.content)
        return
    assert response.status_code == REFUSED_STATUS, (state, kind, header, response.content)
    body = response.json()
    assert body["code"] == CODE, (state, kind, header, body)
    assert header in body["detail"], (state, kind, header, body)
    assert body["remedies"], body


# --- the table, at the MCP door -----------------------------------------------


def _mcp_body() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("kind", (PINNED, UNPINNED))
@pytest.mark.parametrize("state", STATES)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_table_at_the_mcp_door(
    state: str,
    kind: str,
    header: str,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    foreign_org: Organization,
) -> None:
    """The same cell, at the machine door, in the same envelope."""
    from apps.core.asyncdb import run_db
    from config.asgi import build_application

    if kind == PINNED:
        plaintext = (
            await run_db(
                issue_token,
                user=owner,
                tenant=tenant,
                name="pinned",
                actor=actor_for(user=owner, tenant=tenant),
            )
        )[1]
    else:
        plaintext = (
            await run_db(
                issue_token,
                user=owner,
                tenant=None,
                name="unpinned",
                actor=actor_for(user=owner, tenant=None),
            )
        )[1]

    if header == "X-Tenant":
        value = _slug_for(state, mine=tenant.slug, foreign=other_tenant.slug)
    else:
        value = _slug_for(state, mine=branch.slug, foreign=foreign_org.slug)

    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}
    if value is not None:
        headers[header.lower()] = value

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(MCP_URL, headers=headers, json=_mcp_body())

    if _honoured(state):
        assert response.status_code == 200, (state, kind, header, response.text)
        return
    assert response.status_code == REFUSED_STATUS, (state, kind, header, response.text)
    body = response.json()
    assert body["code"] == CODE, (state, kind, header, body)
    assert header in body["detail"], (state, kind, header, body)


# --- door parity: the same refusal, byte for byte -----------------------------


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_in_the_same_bytes(
    header: str,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    foreign_org: Organization,
) -> None:
    """Rule 17 / E9: one refusal, two doors, one body — not two equivalent ones.

    The doors reach the decision by different routes (an `HttpRequest`'s headers
    against an ASGI scope's) and compose the answer through the same
    `wire_refusal` over the same exception class, which is what makes this true
    by construction rather than by two modules agreeing. It is asserted on the
    raw bytes because that is what a client receives; a dictionary comparison
    would pass over two serialisations of one shape.
    """
    from apps.core.asyncdb import run_db
    from config.asgi import build_application

    plaintext = (
        await run_db(
            issue_token,
            user=owner,
            tenant=tenant,
            name="parity",
            actor=actor_for(user=owner, tenant=tenant),
        )
    )[1]
    value = other_tenant.slug if header == "X-Tenant" else foreign_org.slug
    credential = {"authorization": f"Bearer {plaintext}", header.lower(): value}

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                LIST_URL, headers={**credential, "accept": "application/json"}
            )
            over_rpc = await client.post(
                MCP_URL, headers={**MCP_HEADERS, **credential}, json=_mcp_body()
            )

    assert over_http.status_code == over_rpc.status_code == REFUSED_STATUS
    assert over_http.content == over_rpc.content, (over_http.text, over_rpc.text)


# --- the anti-oracle: foreign and nonexistent are one answer ------------------


@pytest.mark.parametrize("header", HEADERS)
def test_foreign_and_nonexistent_are_byte_identical(
    header: str,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    foreign_org: Organization,
) -> None:
    """A refusal that told them apart would be an existence oracle over the estate."""
    plaintext = issue_token(
        user=owner, tenant=tenant, name="oracle", actor=actor_for(user=owner, tenant=tenant)
    )[1]
    if header == "X-Tenant":
        foreign, absent = other_tenant.slug, "no-such-slug-anywhere"
    else:
        foreign, absent = foreign_org.slug, "no-such-slug-anywhere"

    first = _rest(
        kind=PINNED, user=owner, tenant=tenant, plaintext=plaintext, header=header, value=foreign
    )
    second = _rest(
        kind=PINNED, user=owner, tenant=tenant, plaintext=plaintext, header=header, value=absent
    )

    assert first.status_code == second.status_code == REFUSED_STATUS
    assert first.content == second.content, (first.content, second.content)


# --- the promise that is now true --------------------------------------------


def test_a_valid_credential_never_answers_unauthenticated(
    tenant: Tenant, other_tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """Verbatim: a pinned token plus a foreign `X-Tenant`.

    It answered `401 unauthenticated` — "We could not tell who is making this
    request" — over a live, unrevoked token belonging to a real active user.
    E9's grammar refuses a fact that is false, and that one was.
    """
    plaintext = issue_token(
        user=owner, tenant=tenant, name="f1", actor=actor_for(user=owner, tenant=tenant)
    )[1]

    response = _rest(
        kind=PINNED,
        user=owner,
        tenant=tenant,
        plaintext=plaintext,
        header="X-Tenant",
        value=other_tenant.slug,
    )

    assert response.status_code != 401, response.content
    body = response.json()
    assert body["code"] != "unauthenticated", body
    assert body["code"] == CODE, body


def test_an_omitted_header_still_falls_back_to_the_default_membership(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """The well-behaved client sees no change. This is the half that must NOT move."""
    plaintext = issue_token(
        user=owner, tenant=None, name="quiet", actor=actor_for(user=owner, tenant=None)
    )[1]
    client = Client()
    response = client.get(LIST_URL, headers={"authorization": f"Bearer {plaintext}"})
    assert response.status_code == 200, response.content

    session = Client()
    session.force_login(owner)
    assert session.get(LIST_URL).status_code == 200


# --- the derived census ------------------------------------------------------


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _modules() -> Iterator[Path]:
    root = _repository_root()
    for base in ("apps", "config"):
        for path in sorted((root / base).rglob("*.py")):
            if "/tests/" in str(path) or path.name.startswith("test_"):
                continue
            yield path


def _resolves_an_addressing_header(path: Path) -> bool:
    """True when this module CALLS one of the two resolvers.

    Derived off the call, not off a list of file names: a door added tomorrow
    that resolves `X-Tenant` shows up here the moment it is written.
    """
    return _calls_any(path, {"resolve_tenant", "resolve_org"})


def _calls_any(path: Path, wanted: set[str]) -> bool:
    """True when this module calls — or hands on, uncalled — one of `wanted`."""
    try:
        tree = source_tree(path)
    except SyntaxError:  # pragma: no cover - not a thing in this tree
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in wanted:
                return True
        # `run_db(resolve_org, ...)` and `run_db(resolve_tenant, ...)` — the
        # async doors hand the function itself rather than calling it.
        if isinstance(node, ast.Name) and node.id in wanted:
            return True
    return False


def test_the_header_reading_door_census_is_covered() -> None:
    """Every module that resolves an addressing header has a row in this table."""
    root = _repository_root()
    census = {
        str(path.relative_to(root)) for path in _modules() if _resolves_an_addressing_header(path)
    }
    # The declaring module itself is where the resolvers live, not a door.
    census.discard("apps/core/middleware.py")
    covered = set(DOOR_COVERAGE) - {"apps/core/middleware.py"}

    assert census == covered, {
        "in the tree but not in the table": sorted(census - covered),
        "in the table but not in the tree": sorted(covered - census),
    }


#: Every module that reads the HOST into a surface — the door fact the tenant is
#: resolved under — and how it is driven. Checked against the derived census in
#: `test_the_host_reading_door_census_is_covered`; a door that resolves a
#: surface tomorrow fails that test until it has a row here.
SURFACE_COVERAGE = {
    "apps/core/middleware.py": (
        "rest — the session door; apps/core/tests/test_surfaces.py drives the exact, the "
        "pattern and the unbound host, and the tenant-rule rows below"
    ),
    "apps/core/asgi_middleware.py": (
        "socket — resolved into scope['surface'] before the tenant; the join's refusal of an "
        "unexposed family is the socket rung's, driven there"
    ),
    "config/mcp.py": (
        "mcp — resolved from the Host header before the credential; "
        "apps/core/tests/test_mcp_surfaces.py drives the exposed tool, the refused tool, "
        "the listing, the unbound host and the membership-surface X-Tenant"
    ),
}


def test_the_host_reading_door_census_is_covered() -> None:
    """Every module that resolves a surface has a row in `SURFACE_COVERAGE`."""
    root = _repository_root()
    census = {
        str(path.relative_to(root)) for path in _modules() if _calls_any(path, {"resolve_surface"})
    }
    # The declaring module is where the resolver lives, not a door.
    census.discard("apps/core/surfaces.py")

    assert census == set(SURFACE_COVERAGE), {
        "in the tree but not in the table": sorted(census - set(SURFACE_COVERAGE)),
        "in the table but not in the tree": sorted(set(SURFACE_COVERAGE) - census),
    }


def test_the_undriven_cell_is_named() -> None:
    """An absent cell is declared, never silently missing."""
    assert (SESSION, "mcp") in UNDRIVEN


# --- the socket door ----------------------------------------------------------
#
# ITS ROWS ARE DRIVEN IN `apps/realtime/tests/test_addressing_headers.py`, and
# the split is the layer contract rather than a preference: `core` sits below
# `realtime` and may not import it, so the socket client and the close codes are
# unreachable from here. That module imports the table constants above — the
# legal direction — so the two halves cannot come to disagree about which cells
# exist. `SOCKET_ROWS` names the cells it owes.

SOCKET_ROWS = tuple(
    (state, header) for state in (FOREIGN, NONEXISTENT, EMPTY) for header in HEADERS
)


def test_the_registry_holds_the_code() -> None:
    """Rule 47: the code is registered, and its fact is about the header."""
    from apps.core.exceptions import refusal_for

    refusal = refusal_for(CODE)
    assert refusal is not None
    assert refusal.boundary == "door"
    assert refusal.remedies
    assert any("header:" in remedy.destination for remedy in refusal.remedies)


def test_the_code_is_published_on_every_authenticated_route() -> None:
    """Rule 47's other half: a code with no `CODE_STATUS` line drops out silently."""
    from config.api import CODE_STATUS, api

    assert CODE_STATUS[CODE] == REFUSED_STATUS
    document = api.get_openapi_schema()
    operation = document["paths"][LIST_URL]["get"]
    published = {
        code
        for response in operation.get("responses", {}).values()
        if isinstance(response, dict)
        for code in response.get("x-refusal-codes", ())
    }
    assert CODE in published, sorted(published)


def test_the_header_descriptions_say_the_ruled_behaviour() -> None:
    """Rule 41: the document IS the contract, and it used to promise the opposite."""
    from config.api import api

    document = api.get_openapi_schema()
    operation = document["paths"][LIST_URL]["get"]
    described = {
        parameter["name"]: parameter["description"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header"
    }
    assert "reads as empty" not in json.dumps(described)
    for header in HEADERS:
        assert "refused" in described[header].lower(), described[header]


def test_a_membership_is_what_makes_a_header_honourable(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """The honoured half, said about rows rather than about strings."""
    assert Membership.objects.filter(user=owner, tenant=tenant).exists()


def test_the_header_census_tolerates_a_file_that_vanishes_at_open() -> None:
    """A source file deleted between listing and open is skipped, never a `FileNotFoundError`."""
    with vanishing_source_file() as planted:
        for path in _modules():
            _resolves_an_addressing_header(path)
        assert not planted.exists(), "the census never opened the plant — this drove nothing"


# --- R1-F3 · a tenant that is not ACTIVE resolves nowhere ----------------------

#: The non-ACTIVE population, DERIVED from the enum rather than typed. A fourth
#: status declared tomorrow joins this test the day it is declared.
DARK_STATUSES = tuple(s for s in Tenant.Status if s != Tenant.Status.ACTIVE)


def _a_dark_tenant(status: Any) -> tuple[Tenant, User, str]:
    """A tenant, its only member (whose DEFAULT membership it is), and the plaintext.

    **The victim is the test's own** — never the `tenant` fixture, because a
    suspended primary fixture would red every sibling test in the module.
    """
    import uuid

    from apps.accounts.services import create_user
    from apps.core.actor import system_actor
    from apps.core.services import add_membership, create_tenant, root_organization

    suffix = uuid.uuid4().hex[:8]
    victim = create_tenant(name=f"Dark {suffix}", slug=f"dark-{suffix}", actor=system_actor())
    person = create_user(email=f"dark-{suffix}@example.com", password="dark-pass-12345")  # noqa: S106 — a throwaway password a test user is made with
    add_membership(
        user=person,
        tenant=victim,
        organization=root_organization(tenant=victim),
        is_default=True,
        role="owner",
        actor=system_actor(tenant=victim),
    )
    plaintext = issue_token(
        user=person, tenant=None, name="unpinned", actor=actor_for(user=person, tenant=None)
    )[1]
    victim.status = status
    victim.save(update_fields=["status"])
    return victim, person, str(plaintext)


def _organizations(*, kind: str, user: User, plaintext: str, slug: str | None) -> Any:
    """`GET /api/v1/organizations/` — a core route, so `_acting` speaks for it."""
    client = Client()
    headers: dict[str, str] = {}
    if kind == SESSION:
        client.force_login(user)
    else:
        headers["authorization"] = f"Bearer {plaintext}"
    if slug is not None:
        headers["x-tenant"] = slug
    return client.get("/api/v1/organizations/", headers=headers)


@pytest.mark.parametrize("status", DARK_STATUSES)
def test_a_suspended_tenant_resolves_nowhere_at_every_door(status: Any) -> None:
    """**A tenant that is not ACTIVE is a place nobody may act** (R1-F3, ADR core-21).

    `Tenant.status` had one owner and no reader: `suspend_tenant` wrote it,
    `close_tenant` wrote it, and every door went on serving the tenant as if
    nothing had happened. One predicate — `Tenant.is_active`, already on the
    model — read in `resolve_tenant`, and the existing law does the rest: a SENT
    header that cannot be honoured refuses with `addressing_header_not_honoured`
    and byte-identically to a foreign one; an OMITTED header falls through to
    the door's own no-tenant answer. No new refusal code.

    Both branches, both header states, session and unpinned token — and the
    reversal, so the operator's recovery path is driven rather than assumed.
    """
    from apps.core.actor import system_actor
    from apps.core.middleware import resolve_tenant
    from apps.core.services import resume_tenant

    victim, person, plaintext = _a_dark_tenant(status)

    # (a) the function, both branches
    assert resolve_tenant(user=person, requested_slug=victim.slug) is None
    assert resolve_tenant(user=person, requested_slug=None) is None

    # (b) the REST door — session and unpinned token, sent and omitted.
    #
    # `/api/v1/organizations/` rather than the module's `LIST_URL`: the two
    # refusals are different laws and only this one shows both. A SENT header
    # that cannot be honoured is `addressing_header_not_honoured` wherever it
    # lands, and `/widgets/` says that too — but an OMITTED header leaves the
    # request with no tenant, and a scoped list with no tenant is legitimately
    # `200 []` (the whole point of failing closed). `apps.core.api.acting` is
    # what turns "no tenant" into the door's registered answer, and core's routes
    # are the ones that call it.
    for kind in (SESSION, UNPINNED):
        sent = _organizations(kind=kind, user=person, plaintext=plaintext, slug=victim.slug)
        assert sent.status_code == REFUSED_STATUS, (status, kind, sent.content)
        assert sent.json()["code"] == CODE, sent.json()

        omitted = _organizations(kind=kind, user=person, plaintext=plaintext, slug=None)
        assert omitted.status_code == REFUSED_STATUS, (status, kind, omitted.content)
        assert omitted.json()["code"] == "no_acting_scope", omitted.json()

    # …and the write the review drove.
    client = Client()
    client.force_login(person)
    assert (
        client.put(
            "/api/v1/settings/",
            data=json.dumps({"timezone": "UTC", "locale": "en"}),
            content_type="application/json",
            headers={"x-tenant": victim.slug},
        ).status_code
        == REFUSED_STATUS
    )

    # (c) the reversal: the operator's own path never resolved a slug, so it
    # still works while the tenant is dark, and every door comes back.
    #
    # SUSPENDED only. `resume_tenant` refuses a CLOSED tenant by its own rule —
    # "a closed tenant is not resumed; that is a new decision and a new service"
    # — so the reversal is driven where the product HAS one, and the closed
    # tenant's own irreversibility is `test_platform.py`'s.
    if status != Tenant.Status.SUSPENDED:
        return
    resume_tenant(tenant=victim, actor=system_actor(tenant=victim))
    assert resolve_tenant(user=person, requested_slug=victim.slug) == victim
    assert resolve_tenant(user=person, requested_slug=None) == victim
    back = _organizations(kind=SESSION, user=person, plaintext=plaintext, slug=victim.slug)
    assert back.status_code == 200, back.content
    assert (
        _organizations(kind=SESSION, user=person, plaintext=plaintext, slug=None).status_code == 200
    )


@pytest.mark.parametrize("status", DARK_STATUSES)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_dark_tenant_resolves_nowhere_at_the_machine_door(status: Any) -> None:
    """The same claim at MCP: a sent slug refuses, an omitted one has no tenant."""
    from apps.core.asyncdb import run_db
    from config.asgi import build_application

    victim, _person, plaintext = await run_db(_a_dark_tenant, status)

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            sent = await client.post(
                MCP_URL,
                headers={
                    **MCP_HEADERS,
                    "authorization": f"Bearer {plaintext}",
                    "x-tenant": victim.slug,
                },
                json=_mcp_body(),
            )

    assert sent.status_code == REFUSED_STATUS, sent.text
    assert sent.json()["code"] == CODE, sent.json()


# --- the surface decides HOW the tenant is chosen: three rules, three rows each -
#
# `resolve_tenant(surface=)` under each of `addressed`, `host` and `membership`,
# over the scratch customer surface `test_surfaces.py` plants (the `customer`
# role, declared through `authz`'s own walk; the surface in the union the
# discovery walk would have produced). Nothing here is a file in the tree.


def _customer_in(tenant: Tenant, person: User, owner: User) -> None:
    root = Organization.objects.for_tenant(tenant).get(parent__isnull=True)
    from apps.core.services import add_membership

    add_membership(
        user=person,
        tenant=tenant,
        organization=root,
        role="customer",
        actor=actor_for(user=owner, tenant=tenant, org=root),
    )


@pytest.fixture
def by_host(
    settings: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Surface:
    """A customer surface whose tenant is named by its host: `{tenant}.customer.localhost`."""
    from apps.core import surfaces

    request.getfixturevalue("customer_role")

    surface = Surface(
        families={"widgets"}, acts={"read"}, roles={"customer"}, tenant_rule="host", screens=set()
    )
    declared = union([(SimpleNamespace(label="zzz_probe_portal"), {"customer": surface})])
    monkeypatch.setattr(surfaces, "_declared", declared)
    settings.SURFACE_HOSTS = {"staff": "localhost", "customer": "{tenant}.customer.localhost"}
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, ".customer.localhost"]
    return declared["customer"]


# `addressed` — today's rule, and the role a surface admits


def test_addressed_answers_the_default_membership_as_it_always_did(
    tenant: Tenant, owner: User
) -> None:
    assert resolve_tenant(user=owner, requested_slug=None, surface=IMPLICIT_STAFF) == tenant


def test_addressed_answers_the_tenant_the_header_names(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    assert resolve_tenant(user=owner, requested_slug="acme", surface=IMPLICIT_STAFF) == tenant
    assert resolve_tenant(user=owner, requested_slug="globex", surface=IMPLICIT_STAFF) is None


def test_the_staff_surface_does_not_admit_a_role_another_surface_names(
    request: pytest.FixtureRequest, tenant: Tenant
) -> None:
    request.getfixturevalue("two_faces")
    person = request.getfixturevalue("customer")
    from apps.core import surfaces

    staff = surfaces.by_key("staff")
    assert resolve_tenant(user=person, requested_slug=None, surface=staff) is None
    assert Client().get("/api/v1/surface/", HTTP_HOST="localhost").json()["surface"] == "staff"


# `host` — the host names the tenant


def test_host_answers_the_tenant_its_host_names(
    by_host: Surface, tenant: Tenant, owner: User
) -> None:
    person = User.objects.create_user(email="host-customer@example.com")
    _customer_in(tenant, person, owner)

    resolved = resolve_tenant(
        user=person, requested_slug=None, surface=by_host, host="acme.customer.localhost"
    )
    assert resolved == tenant


def test_host_answers_nothing_for_a_tenant_the_person_is_not_in(
    by_host: Surface, tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    person = User.objects.create_user(email="host-customer@example.com")
    _customer_in(tenant, person, owner)

    resolved = resolve_tenant(
        user=person, requested_slug=None, surface=by_host, host="globex.customer.localhost"
    )
    assert resolved is None


def test_host_refuses_a_header_that_disagrees_with_the_host(
    by_host: Surface, tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    person = User.objects.create_user(email="host-customer@example.com")
    _customer_in(tenant, person, owner)
    client = Client()
    client.force_login(person)

    agreeing = client.get(
        LIST_URL, HTTP_HOST="acme.customer.localhost", headers={"x-tenant": "acme"}
    )
    disagreeing = client.get(
        LIST_URL, HTTP_HOST="acme.customer.localhost", headers={"x-tenant": "globex"}
    )

    assert agreeing.status_code == 200, agreeing.content
    assert disagreeing.status_code == REFUSED_STATUS, disagreeing.content
    assert disagreeing.json()["code"] == CODE


# `membership` — the person's one workspace


def test_membership_answers_the_persons_one_workspace(
    request: pytest.FixtureRequest, tenant: Tenant
) -> None:
    surface = request.getfixturevalue("two_faces")
    person = request.getfixturevalue("customer")

    assert resolve_tenant(user=person, requested_slug=None, surface=surface) == tenant
    client = Client()
    client.force_login(person)
    assert client.get(LIST_URL, HTTP_HOST=CUSTOMER_HOST).status_code == 200


def test_membership_refuses_a_person_with_two_workspaces(
    request: pytest.FixtureRequest, tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    surface = request.getfixturevalue("two_faces")
    person = request.getfixturevalue("customer")
    other_owner = User.objects.create_user(email="globex-owner@example.com")
    from apps.core.services import add_membership

    root = Organization.objects.for_tenant(other_tenant).get(parent__isnull=True)
    add_membership(
        user=other_owner,
        tenant=other_tenant,
        organization=root,
        role="owner",
        actor=system_actor(tenant=other_tenant),
    )
    _customer_in(other_tenant, person, other_owner)

    with pytest.raises(AmbiguousTenant):
        resolve_tenant(user=person, requested_slug=None, surface=surface)
    client = Client()
    client.force_login(person)
    refused = client.get(LIST_URL, HTTP_HOST=CUSTOMER_HOST)
    assert refused.status_code == 400, refused.content
    assert refused.json()["code"] == "ambiguous_tenant"
    assert refused.json()["remedies"]


def test_membership_refuses_a_sent_tenant_header_even_one_that_agrees(
    request: pytest.FixtureRequest, tenant: Tenant
) -> None:
    request.getfixturevalue("two_faces")
    person = request.getfixturevalue("customer")
    client = Client()
    client.force_login(person)

    refused = client.get(LIST_URL, HTTP_HOST=CUSTOMER_HOST, headers={"x-tenant": tenant.slug})

    assert refused.status_code == REFUSED_STATUS, refused.content
    assert refused.json()["code"] == CODE
