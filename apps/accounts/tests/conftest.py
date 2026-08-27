"""What the identity tests build their assertions out of.

An SSO test needs two things the rest of the suite does not: a tenant with a
configured identity provider, and something that looks enough like an assertion
from one that the adapter cannot tell the difference. Both are here, once, so
that a test reads as the property it is proving rather than as five lines of
set-up.

**The `SocialLogin` built here is the real class**, populated the way allauth's
own provider extractors populate it — an unsaved `SocialAccount` carrying the
provider id and the IdP's subject in `uid`, plus the `EmailAddress` list with
the verified flag on it. The adapter under test is therefore driven with the
object it will actually be given, not a stand-in that agrees with it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.http import HttpRequest
from django.test import RequestFactory

from apps.accounts import zitadel
from apps.accounts.models import SsoConnection
from apps.accounts.services import create_sso_connection
from apps.accounts.tests.stub_issuer import StubIssuer, running_issuer
from apps.core.actor import Actor
from apps.core.models import Membership, Tenant

# --- The management API, as a dictionary --------------------------------------
#
# `FakeZitadel` and the `instance` fixture live here rather than in one test
# module because three of them need the same socket now (the client's own tests,
# the federation tests, the end-to-end workflow test) and a stub copied twice is
# two stubs that drift. The class is a fixture-support object, which is what a
# `conftest.py` is for.


class _AlreadyInThatState(Exception):
    """Zitadel answering "you asked for the state it is already in", as a 400.

    A separate exception rather than a return value because it has to leave
    `_route` the way the real API leaves the socket: with a non-2xx status and a
    body naming the reason, so that `zitadel._is_already_in_that_state` is what
    is under test rather than a stub that agreed with it.
    """


class FakeZitadel:
    """The smallest thing that behaves like the management API's org surface.

    It records every request, so a test can assert **what was asked**, which is
    how "the audit changes nothing" is provable at all: the assertion is that no
    request outside the read set was ever made, not that the report looked
    read-only.
    """

    def __init__(self) -> None:
        self.projects: dict[str, dict[str, Any]] = {}
        self.apps: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.idps: dict[str, dict[str, Any]] = {}
        # W2-R5's surface: which IdPs and users have been deactivated, and which
        # external identities are linked to which Zitadel user. Kept as state
        # rather than as a call log because the properties the federation tests
        # pin are about the *result* — one object, inactive, no links left —
        # which a call log cannot tell apart from six calls that did nothing.
        self.deactivated_idps: set[str] = set()
        self.deactivated_users: set[str] = set()
        self.user_links: dict[str, list[dict[str, Any]]] = {}
        self.rotations: list[str] = []
        self.requests: list[tuple[str, str]] = []
        # The same log with the request body kept. Separate from `requests`
        # rather than replacing it, because every existing assertion reads that
        # pair and a body is only ever needed to prove an ABSENCE — "no password
        # was sent" is not provable from a path.
        self.bodies: list[tuple[str, str, dict[str, Any]]] = []
        # Which users have set credentials — `CreateInviteCode` refuses
        # those, and a test needs to be able to put a user in that state — and
        # every code minted, per user, so "a second call supersedes the first"
        # is a property a test can read rather than a claim in a docstring.
        self.initialized_users: set[str] = set()
        self.invite_codes: dict[str, list[str]] = {}
        # Zitadel's instance-wide secret generator config. Three days, which is
        # the number MEASURED off the pinned build — the fake serves the
        # real one so the email's stated deadline is tested against it.
        self.invite_code_expiry = "259200s"
        self._next = 1000

    def id(self) -> str:
        self._next += 1
        return str(self._next)

    # --- the transport -----------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace("/management/v1", "", 1)
        method = request.method
        self.requests.append((method, path))
        body = json.loads(request.content or b"{}")
        self.bodies.append((method, path, body))
        try:
            return httpx.Response(200, json=self._route(method, path, body))
        except _AlreadyInThatState as already:
            return httpx.Response(400, json={"message": str(already)})
        except KeyError:
            return httpx.Response(404, json={"message": "NotFound"})

    def _route(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if method == "GET" and path == "/orgs/me":
            return {"org": {"id": "1", "name": "TestOrg"}}
        if path == "/projects/_search":
            return self._search(self.projects, body)
        if method == "POST" and path == "/projects":
            new = self.id()
            self.projects[new] = {"id": new, "name": body["name"]}
            return {"id": new}
        if path.endswith("/apps/_search"):
            project = path.split("/")[2]
            rows = {k: v for k, v in self.apps.items() if v["projectId"] == project}
            return self._search(rows, body)
        if method == "POST" and path.endswith("/apps/oidc"):
            return self._make_app(path, body, "oidcConfig")
        if method == "POST" and path.endswith("/apps/api"):
            return self._make_app(path, body, "apiConfig")
        if path == "/users/_search":
            return {
                "result": [
                    row
                    for row in self.users.values()
                    if row["userName"] == self._username_query(body)
                ]
            }
        if method == "POST" and path == "/users/human/_import":
            new = self.id()
            self.users[new] = {"id": new, "userName": body["userName"]}
            return {"userId": new}
        if path == "/idps/templates/_search":
            return {"result": list(self.idps.values())}
        if method == "GET" and path.startswith("/idps/templates/"):
            return {"idp": self.idps[path.rsplit("/", 1)[-1]]}
        if method == "POST" and path == "/idps/generic_oidc":
            new = self.id()
            self.idps[new] = self._idp(new, body)
            return {"id": new}
        if method == "PUT" and path.startswith("/idps/generic_oidc/"):
            existing = path.rsplit("/", 1)[-1]
            self.idps[existing] = self._idp(existing, body)
            return {}
        if method == "POST" and path == "/idps/google":
            new = self.id()
            self.idps[new] = self._google_idp(new, body)
            return {"id": new}
        if method == "PUT" and path.startswith("/idps/google/"):
            existing = path.rsplit("/", 1)[-1]
            self.idps[existing] = self._google_idp(existing, body)
            return {}
        if method == "POST" and path.endswith("/_deactivate") and path.startswith("/idps/"):
            idp_id = path.split("/")[2]
            if idp_id not in self.idps:
                raise KeyError(path)
            if idp_id in self.deactivated_idps:
                # Zitadel's own answer to "it already is": a 400 naming the
                # state, not a 200. The client has to read that as success or
                # every Temporal retry fails a run that already landed.
                return self._already("Errors.Org.IDP.AlreadyDeactivated")
            self.deactivated_idps.add(idp_id)
            return {}
        if method == "POST" and path.endswith("/idps/_search"):
            user_id = path.split("/")[2]
            return {"result": list(self.user_links.get(user_id, []))}
        if method == "POST" and path.endswith("/_deactivate") and path.startswith("/users/"):
            user_id = path.split("/")[2]
            if user_id not in self.users:
                raise KeyError(path)
            if user_id in self.deactivated_users:
                return self._already("Errors.User.AlreadyInactive")
            self.deactivated_users.add(user_id)
            return {}
        if method == "DELETE" and "/idps/" in path and path.startswith("/users/"):
            _, _, user_id, _, idp_id, external = path.split("/")
            links = self.user_links.get(user_id, [])
            kept = [
                row
                for row in links
                if not (row["idpId"] == idp_id and row["providedUserId"] == external)
            ]
            if len(kept) == len(links):
                raise KeyError(path)
            self.user_links[user_id] = kept
            return {}
        # Both application kinds rotate the same way and differ by one path
        # segment, because Zitadel models a web app's configuration and an API
        # app's as two objects. Answered by one branch here for the same reason
        # `apps/accounts/zitadel.py` has two nearly identical functions: the
        # segment IS the difference, and a fake that collapsed it would let a
        # rotation aimed at the wrong config object pass.
        if method == "POST" and path.endswith("_config/_generate_client_secret"):
            app_id = path.split("/")[4]
            if app_id not in self.apps:
                raise KeyError(path)
            self.rotations.append(app_id)
            return {"clientSecret": f"rotated-{len(self.rotations)}-{app_id}"}
        # --- the v2 user surface, and the one admin read ------------
        # A different prefix, kept whole here rather than stripped in `handle`,
        # so a test can see which API a call went to. The shapes are the ones
        # the pinned build answered with, recorded in the probe.
        if method == "POST" and path == "/v2/users/human":
            new = self.id()
            self.users[new] = {"id": new, "userName": body["username"]}
            return {"userId": new}
        if method == "POST" and path.startswith("/v2/users/") and path.endswith("/invite_code"):
            user_id = path.split("/")[3]
            if user_id not in self.users:
                # Zitadel's own answer:
                # a 400 with a message, not a 404.
                return self._already("User could not be found (COMMAND-Wgvn4)")
            if user_id in self.initialized_users:
                return self._already("User is already initialized (COMMAND-EF34g)")
            # Six uppercase alphanumerics, and a NEW one each call — the real
            # API supersedes rather than returning the previous code, and a fake
            # that returned the same one would make a non-idempotent call look
            # idempotent.
            code = f"CODE{len(self.invite_codes.get(user_id, [])) + 1:02d}"
            self.invite_codes.setdefault(user_id, []).append(code)
            return {"inviteCode": code}
        if method == "POST" and path == "/admin/v1/secretgenerators/_search":
            return {
                "result": [
                    {"generatorType": "SECRET_GENERATOR_TYPE_PASSWORD_RESET", "expiry": "3600s"},
                    {
                        "generatorType": "SECRET_GENERATOR_TYPE_INVITE_CODE",
                        "expiry": self.invite_code_expiry,
                        "length": 6,
                    },
                ]
            }
        raise KeyError(path)

    @staticmethod
    def _already(code: str) -> dict[str, Any]:
        """Raised out of `handle` as a 400, the way the real API answers."""
        raise _AlreadyInThatState(code)

    def _make_app(self, path: str, body: dict[str, Any], config_key: str) -> dict[str, Any]:
        project = path.split("/")[2]
        new = self.id()
        client_id = self.id()
        self.apps[new] = {
            "id": new,
            "projectId": project,
            "name": body["name"],
            config_key: {"clientId": client_id},
        }
        return {"appId": new, "clientId": client_id, "clientSecret": f"secret-{new}"}

    def _google_idp(self, idp_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Google's template has no issuer of its own — Zitadel knows Google's."""
        return {
            "id": idp_id,
            "name": body["name"],
            "config": {"google": {"clientId": body["clientId"]}},
        }

    def _idp(self, idp_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": idp_id,
            "name": body["name"],
            "config": {"oidc": {"issuer": body["issuer"], "clientId": body["clientId"]}},
        }

    @staticmethod
    def _username_query(body: dict[str, Any]) -> str:
        for query in body.get("queries") or []:
            if "userNameQuery" in query:
                return str(query["userNameQuery"]["userName"])
        return ""

    @staticmethod
    def _search(rows: dict[str, dict[str, Any]], body: dict[str, Any]) -> dict[str, Any]:
        wanted = ""
        for query in body.get("queries") or []:
            if "nameQuery" in query:
                wanted = str(query["nameQuery"]["name"])
        result = [row for row in rows.values() if not wanted or row["name"] == wanted]
        return {"result": result}


@pytest.fixture
def instance(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    recorded_workflow_starts: None,
) -> FakeZitadel:
    """A configured client whose socket is a dictionary.

    The settings are filled in here rather than in `config/settings/test.py`,
    which blanks them on purpose: a test that wants the client has to say so,
    and everything else in the suite gets `ZitadelNotConfigured` before a socket
    is opened.

    **And no Temporal dial either** (`recorded_workflow_starts`). Since W2-R5,
    `create_sso_connection` asks for its own materialisation, so building the
    `sso_connection` fixture inside a `transaction=True` test commits and fires
    the on-commit hook. Every test in this module is about the client or a
    command and none of them is about the start, so the seam is closed once
    here, in the fixture every one of them already asks for first — which is
    what keeps the ordering right without repeating it twenty times.
    """
    fake = FakeZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    # **And the workforce door is off unless a test turns it on.** `zitadel_audit`
    # compares `GOOGLE_WORKSPACE_DOMAINS` against the instance, so a developer
    # whose `.env` configured the workforce door used to make every audit test in
    # this module report drift the fake instance was never asked to hold. Since
    # `config/settings/test.py` blanks that setting for the whole suite and
    # this line is the belt: the module that would notice first says so where the
    # fixture is read. The tests whose subject *is* the workforce door set it
    # themselves, after this.
    settings.GOOGLE_WORKSPACE_DOMAINS = []

    @contextmanager
    def stubbed() -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    return fake


ISSUER = "https://idp.acme.example"
CLIENT_ID = "acme-client-id"
CLIENT_SECRET = "acme-client-secret-nobody-should-ever-see"  # pragma: allowlist secret


@pytest.fixture
def sso_connection(tenant: Tenant, owner_actor: Actor) -> SsoConnection:
    """Acme's identity provider, claiming acme.com, not enforcing."""
    return create_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        name="Acme Okta",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["acme.com"],
        default_role=Membership.Role.MEMBER,
    )


@pytest.fixture
def other_sso_connection(other_tenant: Tenant, stranger_actor: Actor) -> SsoConnection:
    """Globex's identity provider, claiming globex.com.

    The second connection is what makes the cross-tenant tests able to fail: one
    connection can never prove that two are isolated.
    """
    return create_sso_connection(
        tenant=other_tenant,
        actor=stranger_actor,
        name="Globex Entra",
        issuer="https://idp.globex.example",
        client_id="globex-client-id",
        client_secret="globex-client-secret",  # pragma: allowlist secret
        email_domains=["globex.com"],
        default_role=Membership.Role.MEMBER,
    )


def assertion(
    *,
    provider: str,
    subject: str,
    email: str,
    verified: bool = True,
    extra: dict[str, Any] | None = None,
) -> SocialLogin:
    """One assertion from an identity provider, as allauth hands it to an adapter."""
    account = SocialAccount(
        provider=provider,
        uid=subject,
        extra_data={"email": email, "email_verified": verified, **(extra or {})},
    )
    return SocialLogin(
        account=account,
        email_addresses=[EmailAddress(email=email, verified=verified, primary=True)],
    )


@pytest.fixture
def stub_issuer(settings: Any) -> Iterator[StubIssuer]:
    """The suite's identity provider: a real OpenID Connect issuer, in process.

    Everything `config/settings/base.py` builds the `openid_connect` app from is
    re-pointed at it — the issuer, the client id, the secret — and the app list
    is rebuilt here rather than mutated, because base.py computed it once at
    import and a test that edited `ZITADEL_ISSUER` alone would leave the
    registered app pointing at the must-not-dial address it was born with.

    The cache is cleared because `allauth.socialaccount.internal.jwtkit` caches
    JWKS documents by URL: a second issuer on a recycled port would otherwise
    verify against the first one's public key.

    A test that does **not** ask for this fixture reaches no identity provider at
    all — `config/settings/test.py` pins the issuer to a dead port, pins the
    client id empty, and rebuilds `SOCIALACCOUNT_PROVIDERS` with an empty `APPS`,
    which unregisters the app entirely.
    """
    from django.core.cache import cache

    with running_issuer() as issuer:
        settings.ZITADEL_ISSUER = issuer.base_url
        settings.ZITADEL_CLIENT_ID = issuer.client_id
        settings.ZITADEL_CLIENT_SECRET = "stub-client-secret"  # pragma: allowlist secret
        settings.SOCIALACCOUNT_PROVIDERS = {
            **settings.SOCIALACCOUNT_PROVIDERS,
            "openid_connect": {
                "APPS": [
                    {
                        "provider_id": settings.ZITADEL_PROVIDER_ID,
                        "name": "Zitadel",
                        "client_id": issuer.client_id,
                        "secret": "stub-client-secret",  # pragma: allowlist secret
                        "settings": {"server_url": issuer.base_url},
                    }
                ],
                "OAUTH_PKCE_ENABLED": True,
            },
        }
        cache.clear()
        yield issuer
        cache.clear()


@pytest.fixture
def platform_provider(settings: Any) -> None:
    """Zitadel registered as the one `openid_connect` app, without a live issuer.

    The cheap half of `stub_issuer`, for tests that drive the **adapter** rather
    than the protocol. `sociallogin.connect` asks allauth for the app behind the
    provider id, and `config/settings/test.py` pins the client id empty **and
    rebuilds `SOCIALACCOUNT_PROVIDERS` with no apps in it**, so no app is
    registered at all whatever the machine's `.env` says — which is right for the
    suite and wrong for a test whose subject is what the adapter does *after* an
    assertion has arrived.

    The issuer stays on the must-not-dial address (`http://127.0.0.1:1`): nothing
    here starts a flow, so nothing here opens a socket. A test that needs the
    protocol asks for `stub_issuer` instead and gets a real one.
    """
    settings.SOCIALACCOUNT_PROVIDERS = {
        **settings.SOCIALACCOUNT_PROVIDERS,
        "openid_connect": {
            "APPS": [
                {
                    "provider_id": settings.ZITADEL_PROVIDER_ID,
                    "name": "Zitadel",
                    "client_id": "platform-client-id",
                    "secret": "platform-client-secret",  # pragma: allowlist secret
                    "settings": {"server_url": settings.ZITADEL_ISSUER},
                }
            ],
            "OAUTH_PKCE_ENABLED": True,
        },
    }


@pytest.fixture
def login_request() -> HttpRequest:
    """A request of the shape an allauth callback arrives on.

    The session is what `sociallogin.connect` and allauth's own bookkeeping
    reach for; without one they fail on a detail that has nothing to do with
    what any of these tests are about.
    """
    request = RequestFactory().get("/accounts/oidc/callback/")
    from django.contrib.sessions.backends.db import SessionStore

    request.session = SessionStore()
    return request
