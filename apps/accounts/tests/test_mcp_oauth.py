"""The MCP door as an OAuth 2.1 resource server, driven over the wire.

W2R4-1 through W2R4-4. Everything here builds the **real ASGI application** and
speaks Streamable HTTP to `/mcp` through an in-process transport, exactly as
`apps/core/tests/test_mcp.py` does for the first-party door. Nothing is patched:
the middleware is the middleware, the verifier in `apps/accounts/oauth.py` is
the verifier, and the token is a real RS256 JWT signed by a real key.

**No test here dials Zitadel** (ADR ident-5). `config/settings/test.py` pins
`ZITADEL_ISSUER` at `http://127.0.0.1:1` — a port nothing may listen on — so a
test that reached the real instance would hang rather than pass quietly. The
issuer under these tests is `stub_issuer`: a genuine OpenID Connect issuer in
this process, serving discovery and a JWKS over a real socket and signing real
tokens. What that leaves unproven is exactly one thing — whether *Zitadel's*
tokens carry the claims this verifier demands — and that is what
`scripts/oauth_demo.py` exists to prove against the live container.

**The audience is the axis the suite is built around.** A resource server that
checks signature, issuer and expiry and not audience has built a door that any
token from the instance opens, and it passes every test that does not think to
mint a token for somebody else. So the acceptance case names
`ZITADEL_MCP_AUDIENCE` and one refusal changes only that claim.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from importlib import import_module
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY

from apps.accounts import oauth
from apps.accounts.models import User
from apps.accounts.services import issue_token, record_zitadel_identity
from apps.accounts.tests.stub_issuer import StubIssuer, sign_jwt, wrongly_signed
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.middleware import ORG_HEADER
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running

# `transaction=True` because the tool's service commits: `create_widget`
# registers work on `transaction.on_commit`, and a test that never committed
# would drive a shorter stack than the wire does. `recorded_workflow_starts`
# (apps/conftest.py) is what keeps that commit from dialling Temporal.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

BASE_URL = "http://testserver"
MCP_URL = "/mcp"

# The audience this deployment's tokens must name. An arbitrary string here
# standing in for the id Zitadel gives the MCP API application: what is under
# test is that the value is *checked*, not what it is.
AUDIENCE = "mcp-resource-id"

# The Zitadel subject the `owner` is joined to. `User.zitadel_sub` is the one
# column that turns "a valid token" into "somebody here" (W2-R3's join).
SUBJECT = "zitadel-subject-owner"

# A widget is created by name over the tool door. `apps.example` is deliberately
# **not imported**: `accounts` sits below it in the layer contract, and this
# module is about authentication rather than about widgets. The tool is named as
# a string and the write is proved through the audit row, which is `core`'s.
WRITE_TOOL = "create_widget"

# The REST half of the hat comparison. A URL rather than an import, for the same
# reason the tool is a string: `apps.example` sits above `accounts`.
WIDGETS_URL = "/api/v1/widgets/"

# Any GET through `CsrfViewMiddleware` leaves the cookie behind, and the admin
# login page is the one page always mounted in this tree. Nothing about the
# admin is under test — it is a source of a real, server-issued token.
CSRF_SOURCE_URL = "/admin/login/"

# The person with a Zitadel identity and no membership anywhere. A separate
# subject from `SUBJECT` because `User.zitadel_sub` is unique.
NOMAD_SUBJECT = "zitadel-subject-nomad"


# --- the wire -----------------------------------------------------------------


def rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def result(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    assert "error" not in payload, payload
    got: dict[str, Any] = payload["result"]
    return got


async def initialize(client: httpx.AsyncClient, headers: dict[str, str]) -> httpx.Response:
    return await client.post(
        MCP_URL,
        headers=headers,
        json=rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "oauth-test", "version": "1"},
            },
        ),
    )


async def write_a_widget(
    client: httpx.AsyncClient, headers: dict[str, str], name: str
) -> httpx.Response:
    return await client.post(
        MCP_URL,
        headers=headers,
        json=rpc(
            "tools/call",
            {"name": WRITE_TOOL, "arguments": {"name": name}},
            request_id=3,
        ),
    )


# --- the issuer, and the tokens it mints --------------------------------------


@pytest.fixture
def resource_server(settings: Any, stub_issuer: StubIssuer) -> Iterator[StubIssuer]:
    """The stub issuer, with this deployment configured to accept its tokens.

    `stub_issuer` already re-points `ZITADEL_ISSUER`; what this adds is the
    audience — without which `oauth.configured()` is False and the door is
    **off** rather than open, which is the deliberate design and would make
    every acceptance test here fail closed for the wrong reason.

    The caches are cleared on both sides of the test: `oauth` keeps the
    discovery document and one `PyJWKClient` per JWKS URL for the recorded
    window, and a second stub on a recycled port would otherwise be verified
    against the first one's public key.
    """
    settings.ZITADEL_MCP_AUDIENCE = [AUDIENCE]
    oauth.reset_caches()
    yield stub_issuer
    oauth.reset_caches()


def access_token(
    issuer: StubIssuer,
    *,
    subject: str = SUBJECT,
    audience: str = AUDIENCE,
    lifetime: int = 300,
    wrong_key: bool = False,
) -> str:
    """One access token, as Zitadel would mint it, with one knob per refusal.

    Signed with the key the stub's JWKS publishes unless `wrong_key` says
    otherwise — a token that is well-formed in every way except the one under
    test is the only kind that proves a check is running.
    """
    now = int(time.time())
    claims = {
        "iss": issuer.base_url,
        "aud": audience,
        "sub": subject,
        "iat": now - 10,
        "exp": now + lifetime,
    }
    return wrongly_signed(claims) if wrong_key else sign_jwt(claims)


@pytest.fixture
def oauth_user(owner: User) -> User:
    """The `owner`, joined to a Zitadel subject through the one writer.

    `record_zitadel_identity` rather than `owner.zitadel_sub = ...`: the service
    is the only thing that writes this column (house rule 10 and W2-R3's ADR),
    and a test that wrote it directly would be proving the door against a join
    the product cannot actually make.
    """
    return record_zitadel_identity(
        user=owner, subject=SUBJECT, tenant=None, actor=system_actor(tenant=None)
    )


@pytest.fixture
def api_token(tenant: Tenant, owner: User) -> str:
    """A first-party `ApiToken` for the same person. The other credential.

    A fixture rather than a line in the body because these tests are `async def`
    and the ORM refuses a synchronous query inside a running event loop.
    """
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="beside-oauth", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def nomad_oauth_user(nomad: User) -> User:
    """Somebody Zitadel knows and this product has no membership for.

    `nomad` (apps/conftest.py) is a real, saved user in no tenant at all — the
    exact state a first sign-in through Zitadel leaves somebody in, before an
    invitation is accepted.
    """
    return record_zitadel_identity(
        user=nomad, subject=NOMAD_SUBJECT, tenant=None, actor=system_actor(tenant=None)
    )


@pytest.fixture
def child_org(tenant: Tenant, root_org: Organization, owner_actor: Actor) -> Organization:
    """A node under the root, for the hat to actually mean something.

    A depth-one tree cannot prove `X-Org` resolves anything: the only answer
    available is the root, which is also what an absent header produces. The
    header has to be able to select a node the default would not.
    """
    return create_organization(
        tenant=tenant, parent=root_org, name="Branch", slug="branch", actor=owner_actor
    )


@pytest.fixture
def owner_session(owner: User) -> str:
    """A real session for the same person, written the way `login()` writes it.

    The three keys below are exactly what `django.contrib.auth.login` puts in
    the session, and `AuthenticationMiddleware` reads them back through the
    ordinary path. What this skips is only the sign-in *form*, which belongs to
    allauth and is proved in `test_rp_login.py`.
    """
    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session[SESSION_KEY] = str(owner.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = owner.get_session_auth_hash()
    session.save()
    return str(session.session_key)


def count_audit(tenant: Tenant) -> int:
    """How many rows this tenant's trail holds, read the way rule 8 demands."""
    return int(AuditEntry.objects.for_tenant(tenant).count())


def latest_audit(tenant: Tenant) -> AuditEntry:
    """The last thing that happened in this tenant, read the way rule 8 demands."""
    entry = AuditEntry.objects.for_tenant(tenant).order_by("-created_at", "-pk").first()
    assert entry is not None, "nothing was audited at all"
    return entry


# --- W2R4-1: a Zitadel token reaches the door, and the write is audited --------


async def test_an_oauth_access_token_reaches_the_mcp_door_and_the_write_is_audited(
    resource_server: StubIssuer,
    tenant: Tenant,
    oauth_user: User,
    recorded_workflow_starts: None,
) -> None:
    """The headline. A token this product did not issue opens the machine door.

    Three legs in one test on purpose: `initialize` proves the transport took
    the credential, `tools/list` proves the principal reached the tool registry,
    and the **write** is the criterion — a read could be answered by a door that
    authenticated nobody, and only a write leaves a row saying who it thought
    was calling.

    The audit assertions are the load-bearing half. `door=mcp` and
    `actor_kind=agent` are what the criterion names, and `actor_token is
    None` is the fact that distinguishes this door from the first-party one:
    an OAuth caller holds no `ApiToken`, and inventing a row so the shapes
    matched would put a credential in the database that we neither issued nor
    can revoke.
    """
    from config.asgi import build_application

    application = build_application()
    token = access_token(resource_server)
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            started = await initialize(client, headers)
            assert started.status_code == 200, started.text
            assert result(started)["serverInfo"]["name"] == "pilecap"

            listing = await client.post(
                MCP_URL, headers=headers, json=rpc("tools/list", {}, request_id=2)
            )
            assert listing.status_code == 200, listing.text
            assert WRITE_TOOL in {tool["name"] for tool in result(listing)["tools"]}

            written = await write_a_widget(client, headers, "Minted through OAuth")

    assert written.status_code == 200, written.text
    assert result(written)["structuredContent"]["name"] == "Minted through OAuth"

    entry = await run_db(latest_audit, tenant)
    assert entry.door == "mcp"
    assert entry.actor_kind == AuditEntry.Kind.AGENT
    assert entry.actor_user_id == oauth_user.pk
    # No `ApiToken` behind an OAuth call, and the trail says so.
    assert entry.actor_token_id is None


# --- W2R4-3: the join — `ApiToken` survives beside it -------------------------


async def test_an_api_token_still_writes_with_the_oauth_door_configured(
    resource_server: StubIssuer,
    tenant: Tenant,
    oauth_user: User,
    api_token: str,
    recorded_workflow_starts: None,
) -> None:
    """The subsumption decision, as a test (ADR ident-3).

    OAuth 2.1 was allowed to *join* the door, not to replace it: `manage.py
    seed`, `issue_token`, the wire tests and every CI probe hold an `ApiToken`,
    and retiring it would have put a browser consent dance inside each of them.

    `resource_server` is requested deliberately — the OAuth door is **on** for
    this test. That is the configuration in which subsumption could break the
    first-party door, and a test that proved `ApiToken` works with OAuth
    switched off would prove nothing about the join at all.

    `actor_token is not None` is the other half of the pair above: the two
    credentials are distinguishable in the trail, which is what stops "the
    door still works" from hiding "the door stopped telling them apart".
    """
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {api_token}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            written = await write_a_widget(client, headers, "Minted by the first party")

    assert written.status_code == 200, written.text
    assert result(written)["structuredContent"]["name"] == "Minted by the first party"

    entry = await run_db(latest_audit, tenant)
    assert entry.door == "mcp"
    assert entry.actor_user_id == oauth_user.pk
    assert entry.actor_token_id is not None


async def test_a_jwt_is_never_looked_up_as_an_api_token(
    resource_server: StubIssuer, tenant: Tenant, oauth_user: User
) -> None:
    """The two paths cannot shadow each other, proved from the other side.

    An `ApiToken` is `djb_<random>` and can never have three dot-separated
    segments; an OAuth access token always does. This asserts the discriminator
    itself, because the ordering it protects is invisible in a passing
    end-to-end test: if `authenticate_token` ever started hashing a JWT and
    finding something, the acceptance test above would still be green while a
    first-party token row had silently become reachable by a stranger's JWT.
    """
    assert oauth.looks_like_jwt(access_token(resource_server))

    _, plaintext = await run_db(
        issue_token,
        user=oauth_user,
        tenant=tenant,
        name="discriminator",
        actor=actor_for(user=oauth_user, tenant=tenant),
    )
    assert not oauth.looks_like_jwt(plaintext)


# --- W2R4-2: the discovery chain — a 401 a stranger can act on ----------------


async def test_a_401_from_the_mcp_door_points_at_the_protected_resource_metadata(
    resource_server: StubIssuer,
) -> None:
    """The refusal has to be actionable, or DCR-less bootstrapping is impossible.

    A third-party client that has never seen this deployment knows one thing:
    the URL it was told to call. `WWW-Authenticate` carrying
    `resource_metadata=` is the whole bridge from that to a token — it names the
    document, the document names the authorization server, the authorization
    server mints the token. Without the parameter the 401 is a dead end and the
    only way to learn the AS is for a human to be told out of band.

    Two probes, because they take different branches: a call with **no**
    credential has nothing to report but the door, and a call with a **bad** one
    also carries RFC 6750's `error="invalid_token"`. Both must carry the
    pointer.
    """
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            bare = await client.post(MCP_URL, headers=MCP_HEADERS, json=rpc("tools/list", {}))
            refused = await client.post(
                MCP_URL,
                headers={**MCP_HEADERS, "authorization": "Bearer djb_not-a-real-token"},
                json=rpc("tools/list", {}, request_id=2),
            )

    for response in (bare, refused):
        assert response.status_code == 401, response.text
        challenge = response.headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        assert f'resource_metadata="{oauth.metadata_url()}"' in challenge
        assert oauth.METADATA_PATH in challenge

    # The error code appears only where there was a token to reject. A caller
    # that sent no credential has committed no error, and saying it did would
    # send them looking for a fault in a token they never had.
    assert 'error="invalid_token"' not in bare.headers["www-authenticate"]
    assert 'error="invalid_token"' in refused.headers["www-authenticate"]


async def test_the_mcp_401_body_is_the_registry_refusal_and_keeps_the_pointer(
    resource_server: StubIssuer,
) -> None:
    """The remaining half: the machine door's first refusal is on-registry.

    The 401 body used to be hand-built here — `{"detail": "A bearer token is
    required."}` — a good human sentence with **no `code`** and **no
    `remedies`**, which is the same hole closed on the REST door. An agent
    meeting this refusal had nothing to branch on but the wording, and no
    structured next step at all.

    It is composed by `wire_refusal` now, on the `unauthenticated` code
    `apps/accounts/auth.py` already registers — the SAME code a REST caller
    gets, not a twin minted for this door, because one refusal answered two ways
    is the drift the one composer exists against.

    **And the header survives**, which is the half this test exists to pin
    together with the body: the discovery chain above and the refusal envelope
    are two properties of one response, and a rung that fixed either by dropping
    the other would pass one of these tests and break the door.
    """
    from apps.accounts.auth import Unauthenticated
    from apps.core.exceptions import wire_refusal
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            bare = await client.post(MCP_URL, headers=MCP_HEADERS, json=rpc("tools/list", {}))
            refused = await client.post(
                MCP_URL,
                headers={**MCP_HEADERS, "authorization": "Bearer djb_not-a-real-token"},
                json=rpc("tools/list", {}, request_id=2),
            )

    for response in (bare, refused):
        assert response.status_code == 401, response.text
        body = response.json()
        # The envelope, not a sentence: a code to branch on and remedies to act
        # on, and the keys are the ones every other refusal in the product uses.
        assert body["code"] == Unauthenticated.code == "unauthenticated"
        assert set(body) <= {"detail", "code", "errors", "remedies"}
        assert body["detail"], "the human half is still there"
        assert body["remedies"], "a refusal with no next step is a dead end"
        for remedy in body["remedies"]:
            assert set(remedy) == {"label", "destination"}
        # And the discovery pointer, unmoved.
        challenge = response.headers["www-authenticate"]
        assert f'resource_metadata="{oauth.metadata_url()}"' in challenge

    # The two doors say the same thing about the same refusal. Compared against
    # the composer's own output rather than against a literal, so this cannot
    # pass while the registry and the wire disagree.
    assert bare.json()["remedies"] == wire_refusal(Unauthenticated())["remedies"]
    # The detail stays the SPECIFIC one this door knows — which of the two
    # unauthenticated shapes happened — rather than the registry's general
    # sentence.
    assert bare.json()["detail"] == "A bearer token is required."
    assert refused.json()["detail"] == "That bearer token is not valid."


async def test_the_protected_resource_metadata_resolves_and_names_the_issuer(
    resource_server: StubIssuer,
) -> None:
    """RFC 9728, served at the root, unauthenticated, and pointing at the AS.

    The second link in the chain. It is fetched here with **no credential at
    all** — deliberately, because that is the only state a discovering client is
    ever in, and a metadata document behind authentication is a chicken-and-egg
    no third-party client can break.

    `authorization_servers` naming the issuer is the fact the whole rung turns
    on: a client follows it to `/.well-known/openid-configuration` and finds the
    authorize and token endpoints there. It is asserted against
    `oauth.issuer()` rather than a literal so that it cannot pass while
    disagreeing with the verifier — the document and the validator have to be
    reading the same setting or the door advertises one issuer and accepts
    another.
    """
    from config.asgi import build_application

    application = build_application()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.get(oauth.METADATA_PATH)

    assert response.status_code == 200, response.text
    document = response.json()
    assert document["authorization_servers"] == [resource_server.base_url]
    assert document["authorization_servers"] == [oauth.issuer()]
    assert document["resource"].endswith(MCP_URL)
    assert document["bearer_methods_supported"] == ["header"]


async def test_the_whole_discovery_chain_walks_from_a_401_to_the_authorization_server(
    resource_server: StubIssuer,
) -> None:
    """The chain end to end, as a stranger's client actually walks it.

    Each leg's input is the previous leg's output and nothing else — no literal
    from this file is fed in after the initial `/mcp` call. That is the property
    worth testing: the three legs agreeing pairwise in three separate tests can
    still leave a chain a client cannot follow, because what breaks it is a URL
    built one way in the header and read another way in the document.
    """
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            refusal = await client.post(MCP_URL, headers=MCP_HEADERS, json=rpc("tools/list", {}))
            assert refusal.status_code == 401, refusal.text

            # Leg 1: pull the metadata URL out of the header, the way a client
            # parses it, and fetch that path.
            challenge = refusal.headers["www-authenticate"]
            pointer = challenge.split('resource_metadata="', 1)[1].split('"', 1)[0]
            metadata = await client.get(httpx.URL(pointer).path)
            assert metadata.status_code == 200, metadata.text

            issuer_url = metadata.json()["authorization_servers"][0]

    # Leg 2: the authorization server it names, asked for its own metadata.
    # A **second client**, with no ASGI transport: `ASGITransport` answers every
    # URL from the application regardless of host, so asking it for the issuer's
    # document would have got a 404 from Django and called it a broken chain.
    # This one goes over a real socket to the stub issuer, which is what proves
    # the URL is fetchable rather than merely well-formed.
    async with httpx.AsyncClient() as outward:
        configuration = await outward.get(f"{issuer_url}/.well-known/openid-configuration")

    assert configuration.status_code == 200, configuration.text
    document = configuration.json()
    assert document["issuer"] == issuer_url
    # The two endpoints a client needs to complete the dance. Their presence is
    # what makes the chain finish somewhere useful rather than merely resolve.
    assert document["authorization_endpoint"]
    assert document["token_endpoint"]


# --- W2R4-2: the refusals — each one knob away from the acceptance case -------


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        # The classic forgery: a token carrying the right `kid`, well-formed in
        # every respect, signed with a key the JWKS does not publish.
        ("signature", {"wrong_key": True}),
        # **The check people leave out.** Without it, a token this instance
        # minted for some other API opens `/mcp`. It is the reason
        # `ZITADEL_MCP_AUDIENCE` empty means the door is off rather than open.
        ("audience", {"audience": "some-other-api"}),
        # Already dead on arrival. `exp` in the past, `iat` older still, so the
        # only thing wrong with it is the one thing under test.
        ("expiry", {"lifetime": -120}),
    ],
)
async def test_a_token_that_fails_one_check_is_refused(
    resource_server: StubIssuer,
    tenant: Tenant,
    oauth_user: User,
    label: str,
    kwargs: dict[str, Any],
) -> None:
    """One knob per refusal, against the real verifier and the real JWKS.

    Each token differs from the accepted one in exactly one respect, which is
    the only construction that proves a *particular* check is running: a token
    that is wrong in three ways is refused by a verifier implementing one of
    them.

    The refusal says `invalid_token` and nothing else — deliberately. Telling a
    caller which of signature, audience, issuer or expiry failed is telling
    somebody probing a forgery which half of it worked, and RFC 6750 gives one
    code for exactly that reason. So the assertion is on the wire behaviour and
    the pointer, never on a reason string.
    """
    from config.asgi import build_application

    application = build_application()
    token = access_token(resource_server, **kwargs)
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}
    # Building the fixtures audits — creating the tenant, adding the membership.
    # The claim is that this call adds nothing, not that the trail is empty, and
    # a bare `== 0` would have been a test of the fixtures.
    before = await run_db(count_audit, tenant)

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await write_a_widget(client, headers, f"refused on {label}")

    assert response.status_code == 401, f"{label}: {response.text}"
    challenge = response.headers["www-authenticate"]
    assert 'error="invalid_token"' in challenge
    assert f'resource_metadata="{oauth.metadata_url()}"' in challenge
    # And nothing landed. A 401 that had already written is not a refusal.
    assert await run_db(count_audit, tenant) == before


async def test_a_token_for_a_subject_this_deployment_has_never_seen_is_refused(
    resource_server: StubIssuer, tenant: Tenant, owner: User
) -> None:
    """A perfectly valid token authenticates nobody without the join.

    `owner` rather than `oauth_user`: the person exists here and simply has no
    `zitadel_sub` recorded, which is the realistic shape of this failure — a
    real person, a real token, and no `User.zitadel_sub` row joining them.

    It answers **exactly** what a forged token answers, and that is the point:
    a door that distinguished "bad token" from "unknown person" would be an
    oracle for which accounts exist, answerable by anybody holding any valid
    token from the instance.
    """
    from config.asgi import build_application

    application = build_application()
    token = access_token(resource_server, subject="somebody-who-never-signed-in")
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await write_a_widget(client, headers, "nobody here")

    assert response.status_code == 401, response.text
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


async def test_a_token_for_a_person_with_no_membership_refuses_rather_than_500s(
    resource_server: StubIssuer, nomad_oauth_user: User, recorded_workflow_starts: None
) -> None:
    """Fail closed, in the tools, with nothing bursting into flame.

    The person is real, the token is valid, the join is made — and they hold no
    membership anywhere, so `resolve_tenant` gives `None`. That is the state
    tenancy fails closed on, and the criterion is precise about what it must
    look like: the tools **refuse**, they do not 500, and they certainly do not
    write.

    A 200 with a JSON-RPC error rather than a 401, and correctly so: the
    credential authenticated somebody. What they lack is a tenant, which is a
    refusal by the tool and not by the door — the same shape an `ApiToken`
    holder with no membership gets, because it is the same code path.
    """
    from config.asgi import build_application

    application = build_application()
    token = access_token(resource_server, subject=NOMAD_SUBJECT)
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            started = await initialize(client, headers)
            response = await write_a_widget(client, headers, "no tenant to put it in")

    # The door let them in: the token was valid and named somebody real.
    assert started.status_code == 200, started.text
    # And then the tool refused, without a 500 and without writing.
    assert response.status_code == 200, response.text
    payload = response.json()
    refusal = payload.get("result", {})
    assert refusal.get("isError") is True, payload
    assert "no_tenant" in str(refusal).lower() or "tenant" in str(refusal).lower(), payload


# --- W2R4-3: the hat rides the OAuth actor exactly as it rides a session ------


async def test_x_org_rides_an_oauth_call_exactly_as_it_rides_a_session(
    resource_server: StubIssuer,
    tenant: Tenant,
    oauth_user: User,
    child_org: Organization,
    owner_session: str,
    recorded_workflow_starts: None,
) -> None:
    """The fourth door wears the same hat the first one does.

    `X-Org` is revalidated on every request by `core.middleware.resolve_org` —
    one function, called by the session door, the socket door, the `ApiToken`
    door and now this one. The whole reason the org is **not** a token claim is
    that a claim goes stale against a tree that moves underneath it, and the
    only way that design is worth anything is if every credential resolves the
    same header to the same node.

    So this drives the same person, in the same tenant, naming the same
    organization, through two entirely different credentials — a Zitadel access
    token at `/mcp` and a Django session with a CSRF token at `/api/v1/widgets/`
    — and compares the **audit rows**. Comparing responses would prove the two
    doors answered; comparing `acting_org` proves they agreed about who the
    caller was standing as, which is the fact authorization is computed from.

    A difference here would be the finding the platform's doctrine exists to
    prevent: a hat that means one thing to a browser and another to an agent.
    """
    from config.asgi import build_application

    application = build_application()
    token = access_token(resource_server)
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}", ORG_HEADER: child_org.slug}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            written = await write_a_widget(client, headers, "Worn by an agent")
    assert written.status_code == 200, written.text
    agent_entry = await run_db(latest_audit, tenant)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, owner_session)
        await client.get(CSRF_SOURCE_URL)
        csrf = client.cookies.get(settings.CSRF_COOKIE_NAME)
        assert csrf, "the server issued no CSRF cookie; the session half would be void"
        posted = await client.post(
            WIDGETS_URL,
            json={"name": "Worn by a person"},
            headers={"x-csrftoken": str(csrf), ORG_HEADER: child_org.slug},
        )
    assert posted.status_code == 201, posted.text
    human_entry = await run_db(latest_audit, tenant)

    # The two credentials, the same header, the same node.
    assert agent_entry.acting_org_id == child_org.pk
    assert human_entry.acting_org_id == child_org.pk
    assert agent_entry.acting_org_id == human_entry.acting_org_id
    # Same person, same tenant, and the doors still distinguishable in the trail.
    assert agent_entry.actor_user_id == human_entry.actor_user_id == oauth_user.pk
    # `core.context.Door`'s own vocabulary: the machine door and the HTTP API.
    assert agent_entry.door == "mcp"
    assert human_entry.door == "rest"
