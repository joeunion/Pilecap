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
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.core.cache import cache
from django.http import HttpRequest
from django.test import RequestFactory

from apps.accounts import zitadel
from apps.accounts.models import SsoConnection
from apps.accounts.services import create_sso_connection, verify_sso_domain
from apps.accounts.tests.stub_issuer import StubIssuer, running_issuer
from apps.core.actor import Actor, system_actor
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


class _NotFoundHere(Exception):
    """Zitadel answering a 404 that CARRIES a reason, as it does for real.

    `handle`'s bare `KeyError` branch answers "NotFound" with nothing else,
    which is right for a path this fake simply does not route. It is wrong for
    a path it routes deliberately and refuses — the management login policy on
    an org that has none — because the whole value of that refusal is its error
    id, and a client that keys on the id is exactly what a fake answering a
    blank 404 could not test.
    """


#: The org's login policy when the org HAS one of its own, MEASURED off the
#: running v4.17.1 stack on 2026-09-07 (`GET /management/v1/policies/login`):
#: no `isDefault`, `details.resourceOwner` is the org, `allowRegister` ABSENT —
#: and the five lifetimes and the factor list present, which is the half a
#: partial PUT would zero.
ORG_LOGIN_POLICY_OWN: dict[str, Any] = {
    "details": {"sequence": "73", "resourceOwner": "387613333072707590"},
    "allowUsernamePassword": True,
    "allowExternalIdp": True,
    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
    "ignoreUnknownUsernames": True,
    # The lifetime below is a protobuf Duration (10 days), not a credential;
    # detect-secrets keys on the word in the field name, so it is allowlisted.
    "passwordCheckLifetime": "864000s",  # pragma: allowlist secret
    "externalLoginCheckLifetime": "864000s",
    "mfaInitSkipLifetime": "0s",
    "secondFactorCheckLifetime": "64800s",
    "multiFactorCheckLifetime": "43200s",
    "secondFactors": ["SECOND_FACTOR_TYPE_OTP", "SECOND_FACTOR_TYPE_U2F"],
    "allowDomainDiscovery": True,
    "disableLoginWithPhone": True,
}

#: The same endpoint on an org that has NO policy of its own — the state a
#: freshly created organisation is in, and the state every org on a fresh
#: instance is in. Zitadel answers the INSTANCE's policy with `isDefault: true`
#: and the instance as the `resourceOwner`, which is the only field that tells
#: the two apart. MEASURED against a throwaway org on the same stack.
ORG_LOGIN_POLICY_INHERITED: dict[str, Any] = {
    "details": {"sequence": "116", "resourceOwner": "387613333072642054"},
    "allowUsernamePassword": True,
    "allowRegister": True,
    "allowExternalIdp": True,
    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
    "isDefault": True,
    "passwordCheckLifetime": "864000s",  # pragma: allowlist secret
    "externalLoginCheckLifetime": "864000s",
    "mfaInitSkipLifetime": "2592000s",
    "secondFactorCheckLifetime": "64800s",
    "multiFactorCheckLifetime": "43200s",
    "secondFactors": ["SECOND_FACTOR_TYPE_OTP", "SECOND_FACTOR_TYPE_U2F"],
    "allowDomainDiscovery": True,
}


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
        self.deactivated_apps: set[str] = set()
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
        # --- the deployment's sign-in posture (ADR ident-8) -----------------
        # Three instance-wide surfaces, in the state a FRESHLY CREATED instance
        # is in — MEASURED off the running v4.17.1 stack on 2026-09-07, not
        # invented: `allowRegister: true` with the five lifetimes present,
        # a lockout policy carrying `isDefault` and **no `maxPasswordAttempts`
        # key at all**, and `GET /admin/v1/restrictions` answering `{"details":{}}`.
        #
        # These live on the shared fake rather than in one module, unlike the
        # label policy and the two console surfaces, because they are the state
        # `zitadel_seed` now writes on EVERY run: a seed test, an audit test and
        # the full-body census all need the same socket, and a stub copied three
        # times is three stubs that drift.
        #
        # **Booleans are absent when false** here as everywhere else on this
        # API: proto3 omits its zero values, so a reader keying on presence
        # passes against a fake that sent `false` and fails against Zitadel.
        self.instance_login_policy: dict[str, Any] = {
            "details": {"sequence": "19", "resourceOwner": "387613333072642054"},
            "allowUsernamePassword": True,
            "allowRegister": True,
            "allowExternalIdp": True,
            "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
            "isDefault": True,
            # The lifetime below is a protobuf Duration (10 days), not a credential;
            # detect-secrets keys on the word in the field name, so it is allowlisted.
            "passwordCheckLifetime": "864000s",  # pragma: allowlist secret
            "externalLoginCheckLifetime": "864000s",
            "mfaInitSkipLifetime": "2592000s",
            "secondFactorCheckLifetime": "64800s",
            "multiFactorCheckLifetime": "43200s",
            "secondFactors": ["SECOND_FACTOR_TYPE_OTP", "SECOND_FACTOR_TYPE_U2F"],
            "multiFactors": ["MULTI_FACTOR_TYPE_U2F_WITH_VERIFICATION"],
            "allowDomainDiscovery": True,
        }
        self.lockout_policy: dict[str, Any] = {
            "details": {"sequence": "22", "resourceOwner": "387613333072642054"},
            "isDefault": True,
        }
        self.restrictions: dict[str, Any] = {"details": {}}
        # --- the ORG's own login policy, one level down from the three above --
        # Zitadel serves ONE endpoint for two states and `isDefault` is the
        # whole discriminator, so the fake holds whichever state a test put it
        # in. The default is INHERITED because that is what a freshly created
        # organisation is, and because an inheriting org is the state in which
        # nothing here writes anything — the seed's org half leaves it alone
        # and the audit's org line defers to the instance verdict, so every
        # identity test that is about something else is unaffected by its
        # arrival. The module whose subject IS this policy puts the fake in the
        # other state (`test_zitadel_posture.py`).
        self.org_login_policy: dict[str, Any] = dict(ORG_LOGIN_POLICY_INHERITED)
        # --- the machine credential, and what it is allowed to do -----------
        # Who the PAT belongs to (`GET /auth/v1/users/me`) and which instance
        # manager roles that user holds. The state is the MEASURED one a
        # freshly set-up deployment is in: `scripts/setup.sh` makes the service
        # account an `IAM_OWNER` and nothing has ever granted it
        # `IAM_LOGIN_CLIENT`, which is exactly the state in which the login-v2
        # finalize answers 403 and every other call in this module works.
        # The `instance` fixture grants it, for the same reason it closes the
        # posture: every identity test whose subject is something else would
        # otherwise report a disagreement the fake was never asked to hold.
        self.machine: dict[str, Any] = {
            "id": "900",
            "userName": "djb-platform",
            "preferredLoginName": "djb-platform",
            "machine": {"name": "test platform service account"},
        }
        self.instance_members: dict[str, list[str]] = {"900": ["IAM_OWNER"]}
        # Every organisation on the instance, which the audit counts and never
        # inspects. One, because that is what a clone of this template has.
        self.orgs: list[dict[str, Any]] = [
            {"id": "1", "name": "TestOrg", "state": "ORG_STATE_ACTIVE"}
        ]
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
        if method == "GET" and path == "/oauth/v2/authorize":
            # The browser endpoint, answered where the query string is still
            # reachable: `_route` is handed the parsed JSON body, and this is
            # the one route whose input is the URL.
            return httpx.Response(
                302, headers={"location": self._authorize(request.url.params.get("client_id", ""))}
            )
        try:
            return httpx.Response(200, json=self._route(method, path, body))
        except _AlreadyInThatState as already:
            return httpx.Response(400, json={"message": str(already)})
        except _NotFoundHere as missing:
            return httpx.Response(404, json={"message": str(missing)})
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
        if method == "PUT" and path.endswith("/oidc_config") and path.startswith("/projects/"):
            # MEASURED against the pinned build: the body is a REPLACE of the
            # OIDC config and the response carries only a `details` block. The
            # `clientId` is NOT in the update body and is not the caller's to
            # send, so the fake keeps its own — a fake that let a short body
            # wipe the client id would hide the one thing this surface cannot
            # lose. Nothing is created: an app id nothing holds is a 404, which
            # is the real API's answer too (`COMMAND-2n8uU`).
            app_id = path.split("/")[4]
            if app_id not in self.apps:
                raise _NotFoundHere("Application doesn't exist (COMMAND-2n8uU)")
            live = self.apps[app_id].get("oidcConfig") or {}
            self.apps[app_id]["oidcConfig"] = {
                **{key: value for key, value in body.items() if value is not None},
                "clientId": live.get("clientId", ""),
            }
            return {"details": {"sequence": str(self.id())}}
        if method == "GET" and path.startswith("/projects/") and "/apps/" in path:
            # `GET /projects/{p}/apps/{a}` — the read a writer handed an id
            # makes. MEASURED: the answer wraps the same application shape the
            # search returns in one `app` key.
            app_id = path.split("/")[4]
            if app_id not in self.apps:
                raise _NotFoundHere("Application doesn't exist (COMMAND-2n8uU)")
            return {"app": self.apps[app_id]}
        if method == "POST" and path.startswith("/projects/") and path.endswith("/_deactivate"):
            app_id = path.split("/")[4]
            if app_id not in self.apps:
                raise KeyError(path)
            if app_id in self.deactivated_apps:
                return self._already("Errors.Project.App.AlreadyDeactivated")
            self.deactivated_apps.add(app_id)
            return {}
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
        # --- the ORG's own login policy, on the MANAGEMENT prefix -----------
        # The prefix is already stripped by `handle`, which is why this path is
        # bare where the instance's is spelled `/admin/v1/...` below: they are
        # two surfaces of one resource and the paths are how a test tells which
        # one a call went to.
        if method == "GET" and path == "/policies/login":
            return {"policy": self.org_login_policy}
        if method == "PUT" and path == "/policies/login":
            if self.org_login_policy.get("isDefault"):
                # MEASURED on the pinned build: the UPDATE endpoint refuses an
                # org that has no policy of its own — it does not quietly create
                # one. Modelled here rather than allowed through, because the
                # branch that keeps the seed from forking configuration into two
                # owners is only provable against a fake that refuses the way
                # the real API refuses.
                raise _NotFoundHere("Login Policy not found (Org-M0sif)")
            self.org_login_policy = {
                **{key: value for key, value in body.items() if value not in (False, "")},
                "details": self.org_login_policy["details"],
                "secondFactors": self.org_login_policy.get("secondFactors", []),
            }
            return {}
        # --- the sign-in posture, on the ADMIN prefix -----------------------
        # The paths are the ones MEASURED off the admin swagger document the
        # pinned build serves, and the read/write asymmetry on the lockout
        # policy is Zitadel's own: the GET is `/policies/lockout` and the PUT is
        # `/policies/password/lockout`. A fake that collapsed the two would let
        # a writer aimed at the wrong path pass here and 404 on the real thing.
        if method == "GET" and path == "/admin/v1/policies/login":
            return {"policy": self.instance_login_policy}
        if method == "PUT" and path == "/admin/v1/policies/login":
            self.instance_login_policy = {
                **{key: value for key, value in body.items() if value not in (False, "")},
                "details": self.instance_login_policy["details"],
                "isDefault": True,
                "secondFactors": self.instance_login_policy.get("secondFactors", []),
                "multiFactors": self.instance_login_policy.get("multiFactors", []),
            }
            return {}
        if method == "GET" and path == "/admin/v1/policies/lockout":
            return {"policy": self.lockout_policy}
        if method == "PUT" and path == "/admin/v1/policies/password/lockout":
            self.lockout_policy = {
                **{key: value for key, value in body.items() if value},
                "details": self.lockout_policy["details"],
            }
            return {}
        if method == "GET" and path == "/admin/v1/restrictions":
            return {**self.restrictions}
        if method == "PUT" and path == "/admin/v1/restrictions":
            self.restrictions = {
                **{key: value for key, value in body.items() if value not in (False, {"list": []})},
                "details": self.restrictions.get("details", {}),
            }
            return {}
        # --- the machine credential, and the instance manager roles ---------
        # `GET /auth/v1/users/me` is a FOURTH prefix and it is spelled whole
        # here for the reason the admin paths are: the prefix is how a test
        # tells which of Zitadel's surfaces a call went to.
        if method == "GET" and path == "/auth/v1/users/me":
            return {"user": dict(self.machine)}
        if method == "POST" and path == "/admin/v1/members/_search":
            return {
                "details": {"totalResult": str(len(self.instance_members))},
                "result": [
                    {
                        "userId": user_id,
                        "roles": list(roles),
                        "preferredLoginName": (
                            self.machine["preferredLoginName"]
                            if user_id == self.machine["id"]
                            else user_id
                        ),
                        "userType": "TYPE_MACHINE",
                    }
                    for user_id, roles in self.instance_members.items()
                ],
            }
        if method == "POST" and path == "/admin/v1/members":
            self.instance_members[str(body["userId"])] = [str(one) for one in body.get("roles", [])]
            return {}
        if method == "PUT" and path.startswith("/admin/v1/members/"):
            # A REPLACE, modelled as one, because the whole reason this
            # resource has a declared field set is that a short body takes
            # IAM_OWNER off the credential every other call here authenticates
            # as. A fake that merged would make that untestable — and green.
            self.instance_members[path.rsplit("/", 1)[-1]] = [
                str(one) for one in body.get("roles", [])
            ]
            return {}
        if method == "POST" and path == "/admin/v1/orgs/_search":
            # Zitadel's own envelope: `details.totalResult` beside the rows. The
            # audit reads the rows; the total is served anyway because a fake
            # that carried only what the reader wants cannot catch a reader that
            # started wanting something else.
            return {
                "details": {"totalResult": str(len(self.orgs))},
                "result": list(self.orgs),
            }
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

    def _authorize(self, client_id: str) -> str:
        """Where `/oauth/v2/authorize` sends a browser, per the app's login version.

        The two shapes MEASURED against the pinned build on 2026-09-18, with a
        throwaway application under a throwaway project that was deleted after:
        with no declaration the redirect is
        `/ui/login/login?authRequestID=<id>`; with
        `loginVersion.loginV2.baseUri` it is `<baseUri>/login?authRequest=V2_<id>`.
        The ids differ per request on the real thing and this fake mints one
        the same way, so a reader keying on the id rather than on the shape
        fails here rather than against Zitadel.
        """
        config: dict[str, Any] = {}
        for row in self.apps.values():
            if str((row.get("oidcConfig") or {}).get("clientId", "")) == client_id:
                config = dict(row.get("oidcConfig") or {})
                break
        version = config.get("loginVersion") or {}
        base_uri = str((version.get("loginV2") or {}).get("baseUri", "")) if version else ""
        if version and "loginV2" in version:
            return f"{base_uri}/login?authRequest=V2_{self.id()}"
        return f"/ui/login/login?authRequestID={self.id()}"

    @staticmethod
    def _already(code: str) -> dict[str, Any]:
        """Raised out of `handle` as a 400, the way the real API answers."""
        raise _AlreadyInThatState(code)

    def _make_app(self, path: str, body: dict[str, Any], config_key: str) -> dict[str, Any]:
        """One application, carrying the CONFIG it was created with.

        The config used to be `{"clientId": ...}` and nothing else, which made
        every reader of an application's redirect URIs — the seed's own
        reconcile, the audit's applications section — blind against this fake:
        the one thing they compare was the one thing it did not keep. It keeps
        the whole body now, minus the `name`, which is the application's and not
        its OIDC config's.
        """
        project = path.split("/")[2]
        new = self.id()
        client_id = self.id()
        config = {key: value for key, value in body.items() if key != "name"}
        self.apps[new] = {
            "id": new,
            "projectId": project,
            "name": body["name"],
            config_key: {**config, "clientId": client_id},
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
        # `usePkce` is stored because the writer reads it back: it sends
        # the live value when the caller has no opinion, so a fake that dropped
        # the field would make "a console-enabled PKCE survives a re-sync"
        # untestable — and green, which is worse.
        return {
            "id": idp_id,
            "name": body["name"],
            "config": {
                "oidc": {
                    "issuer": body["issuer"],
                    "clientId": body["clientId"],
                    "usePkce": bool(body.get("usePkce", False)),
                }
            },
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
    # **And the sign-in posture already agrees with these settings**, for
    # exactly the reason the workforce line above exists. Since ADR ident-8,
    # `zitadel_audit` compares three instance surfaces against
    # `config/settings`, and `FakeZitadel.__init__` holds the measured
    # FRESH-INSTANCE state — registration on, no lockout, org registration open,
    # because that is what a new Zitadel actually is. Left that way, every audit
    # test in every identity module would report three disagreements the fake
    # was never asked to hold, and each of those tests is about something else.
    # The module whose subject IS the closing puts the fake back
    # (`test_zitadel_posture.py`'s `fresh_instance`).
    fake.instance_login_policy.pop("allowRegister", None)
    fake.lockout_policy["maxPasswordAttempts"] = settings.ZITADEL_MAX_PASSWORD_ATTEMPTS
    fake.restrictions[
        "disallowPublicOrgRegistration"
    ] = not settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION
    # **And the machine credential already holds the login-client role**, for
    # exactly the reason the three lines above exist. Since design C-9,
    # `zitadel_audit` judges whether the PAT's user may finalize a login-v2
    # sign-in, and `FakeZitadel.__init__` holds the measured POST-SETUP state —
    # `IAM_OWNER` and nothing else, because that is what `scripts/setup.sh`
    # leaves behind. Left that way, every audit test in every identity module
    # would report a disagreement the fake was never asked to hold. The module
    # whose subject IS the grant takes it back off (`test_seed.py`,
    # `test_zitadel_reconcile.py`).
    fake.instance_members[str(fake.machine["id"])] = ["IAM_OWNER", zitadel.LOGIN_CLIENT_ROLE]

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        # `timeout` is `zitadel._client`'s own keyword since the sign-in seam
        # gave the two populations of call two clocks (design I-A §3.2). It is
        # accepted and ignored: a MockTransport never waits, so the number
        # under test is the one the CALLER passes, which is asserted where the
        # caller is (`test_signin.py`) rather than here.
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


def _verified(connection: SsoConnection) -> SsoConnection:
    """Every domain this connection claims, verified as the operator would.

    **R2-F1 (a domain claim routes nothing until it is verified): a claim routes nothing until an
    operator verifies
    it**, so a fixture that stopped here would hand every test below a
    connection that reserves a name and answers nobody — and roughly thirty
    cases across seven modules would then be testing the unverified state while
    claiming to test routing. The sweep is one call, in one place, as
    `system_actor`: the operator at the shell is exactly who verifies in
    production, and `verify_sso_domain` is exactly the service that door calls.

    The UNVERIFIED state has its own fixture below rather than being the default
    here, because a world nothing routes in is a world most of these tests
    cannot say anything in.
    """
    for domain in connection.email_domains:
        verify_sso_domain(
            tenant=connection.tenant,
            actor=system_actor(connection.tenant),
            connection=connection,
            domain=domain,
        )
    return connection


@pytest.fixture
def sso_connection(tenant: Tenant, owner_actor: Actor) -> SsoConnection:
    """Acme's identity provider, claiming acme.com **verified**, not enforcing."""
    return _verified(
        create_sso_connection(
            tenant=tenant,
            actor=owner_actor,
            name="Acme Okta",
            issuer=ISSUER,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            email_domains=["acme.com"],
            default_role=Membership.Role.MEMBER,
        )
    )


@pytest.fixture
def unverified_sso_connection(tenant: Tenant, owner_actor: Actor) -> SsoConnection:
    """The same claim, exactly as an administrator leaves it: reserved, routing nobody.

    The negative's world (R2-F1). It claims `acme.com` like its sibling above
    and differs in one column, so a test that puts the two side by side is
    reading the routing law and nothing else.
    """
    return create_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        name="Acme Okta (unverified)",
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
    return _verified(
        create_sso_connection(
            tenant=other_tenant,
            actor=stranger_actor,
            name="Globex Entra",
            issuer="https://idp.globex.example",
            client_id="globex-client-id",
            client_secret="globex-client-secret",  # pragma: allowlist secret
            email_domains=["globex.com"],
            default_role=Membership.Role.MEMBER,
        )
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


# --- the measurement surfaces -------------------------------------------------
#
# `FakeZitadel` above is the MANAGEMENT API's org surface: the writers' world,
# where everything is a 200 and a refusal is one of two special cases. The
# measurement kit (`manage.py zitadel_measure`) asks a different set of
# questions of a different set of surfaces — this build's own swagger
# documents, the org lifecycle, the Session API, the v2 settings read, and the
# hosted credential page — and on that set a `400`, a `404` and a `500` are
# ANSWERS rather than failures.
#
# So the subclass below adds those surfaces rather than editing the class above:
# every existing route keeps behaving exactly as the thirty-odd tests that read
# it expect, and the measurement tests get a socket that can answer a status
# other than 200. The shapes are the ones the pinned build answered with when
# the instrument was first driven against it on 2026-09-19, recorded in the
# probe rather than recalled.


#: What the pinned build's `/v2/settings/password/complexity` answered for an
#: org with no complexity policy of its own — MEASURED, and the exact shape the
#: Choose-your-password frame's rule sentence is composed from.
MEASURED_PASSWORD_COMPLEXITY: dict[str, Any] = {
    "minLength": "8",
    "requiresUppercase": True,
    "requiresLowercase": True,
    "requiresNumber": True,
    "requiresSymbol": True,
    "resourceOwnerType": "RESOURCE_OWNER_TYPE_INSTANCE",
}

#: Enough of the hosted Activate User form for the instrument's own test —
#: `passwordconfirm` is the field it keys on, and it keys on that one because
#: it is the field that makes the page a credential-setting page rather than
#: any other 200 the issuer might serve at that path.
MEASURED_INVITE_PAGE = (
    "<html><body><form method='post'>"
    "<input name='code' value='SJSVLS'>"
    "<input type='password' name='password'>"
    "<input type='password' name='passwordconfirm'>"
    "</form></body></html>"
)


#: Mode A's measured constants (rung A8). Where a throwaway OIDC client is
#: sent back to, who the token says signed in, and which client asked — all
#: fixture data for a socket that is a dictionary.
MEASURED_CALLBACK_URI = "http://127.0.0.1:41998/measured/callback"

#: What `returnCode` hands back for a password reset — six uppercase
#: alphanumerics, the shape the pinned build minted on 2026-09-19.
MEASURED_RESET_CODE = "BE5CIT"

#: Enough of the hosted Set Password page for M6 to key on, and it keys on the
#: title for `MEASURED_INVITE_PAGE`'s reason: that string is what makes the
#: page a credential-setting one rather than any other 200 at that path.
MEASURED_RESET_PAGE = (
    "<html><head><title>Set Password</title></head><body><form method='post'>"
    "<input name='code' value='BE5CIT'>"
    "<input type='password' name='password'>"
    "</form></body></html>"
)


def zitadel_measure_reset_path() -> str:
    """The reset landing's path, read off the measuring command's own constant.

    Imported lazily inside a function because `conftest` is collected before
    Django's app registry is ready and a management command module at import
    time is a different kind of trouble — and read at all rather than typed
    because a fake that spelled the path itself would answer a route the
    command no longer asks for, which is a green measurement of nothing.
    """
    from apps.accounts.management.commands.zitadel_measure import RESET_PATH

    return str(RESET_PATH)


MEASURED_OIDC_CLIENT_ID = "8001"
#: The subject a token carries when no session of this fake's is behind it.
#: **A FALLBACK, not the fact**: MEASURED on v4.17.1 (2026-09-21, M12), the
#: `sub` of an id_token finalized against a session IS that session's
#: `factors.user.id` — one person, one string, both doors — so `_measured_token`
#: reads the finalized session and this constant only stands in for a token
#: minted with no session in play. A fake that kept a constant here would have
#: agreed with itself whatever the build did to the join.
MEASURED_SUBJECT = "8002"


def _measured_oauth_error(sent: str) -> str:
    """M4, as one function, because two fakes model the same build.

    MEASURED against the pinned build on 2026-09-19: `ERROR_REASON_ACCESS_DENIED`
    reaches the client as `access_denied`, and EVERY other spelling — the RFC
    lowercase `access_denied` included — reaches it as `server_error`. Written
    once and imported by both fakes rather than typed twice: a build fact that
    two test worlds disagreed about is a fact one of them is wrong about.
    """
    return "access_denied" if sent == zitadel.REFUSE_ACCESS_DENIED else "server_error"


def _measured_jwt(claims: dict[str, Any]) -> str:
    """A real-SHAPED JWT with a fake signature. Three parts, base64url payload.

    Not signed, and it must not be: nothing in the kit verifies one (M3 is
    about which claim NAMES the build emits, and verification is
    `apps/accounts/oauth.py`'s job on the door where it matters), and a fake
    that signed would be a second key nobody checks.
    """
    head = urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode()
    payload = urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"{head.rstrip('=')}.{payload.rstrip('=')}.not-a-signature"


class FakeMeasuredZitadel(FakeZitadel):
    """The management fake, plus every surface `zitadel_measure` reaches.

    **Its swagger documents are BUILT from `zitadel`'s own declarations, at
    construction time, and that is deliberate on both counts.** Built from them,
    because the equality was verified live against v4.17.1 on 2026-09-19 (the
    instrument printed all seven resources `ok`), so deriving here records a
    measured agreement rather than inventing one — and a hand-copied list of
    seventy-odd property names would be a second copy of the client's own
    declaration, drifting from it the first time a rung adds a field. At
    CONSTRUCTION time, because that is what makes the plant test possible: a
    test that monkeypatches `zitadel.PUT_FIELD_SETS` after the fixture is built
    moves the declaration and not the document, which is exactly the
    disagreement the instrument exists to find.
    """

    def __init__(self) -> None:
        super().__init__()
        self.created_orgs: list[str] = []
        self.removed_orgs: list[str] = []
        self.org_own_policies: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.session_tokens: dict[str, str] = {}
        self.passworded_users: set[str] = set()
        #: Mode A's two logs (rung A8): which sessions were finalized against,
        #: and every reason spelling a refusal was sent with. Lists because
        #: "exactly once" and "in this spelling" are the properties.
        self.finalized_sessions: list[str] = []
        self.refused_reasons: list[str] = []
        #: Every call this fake was asked for, WHOLE: the method, the path with
        #: its prefix, the `x-zitadel-orgid` header and the body. The parent's
        #: `requests` log strips `/management/v1` and keeps no header, which
        #: makes "no call touched any organisation but its own" unprovable — and
        #: that is the one assertion the victim test exists to make. All four
        #: fields are needed because Zitadel names the org three different ways
        #: depending on the surface: in the path (`/admin/v1/orgs/{id}`), in the
        #: header (every management call, and `POST /v2/sessions`) and in the
        #: body (`POST /v2/users/human`).
        self.whole_calls: list[tuple[str, str, str, dict[str, Any]]] = []
        self.swagger: dict[str, dict[str, Any]] = {
            "admin": self._document("Administration API aka Admin", "admin"),
            "management": self._document("Management API", "management"),
        }

    @staticmethod
    def _definitions_for(document: str) -> dict[str, frozenset[str]]:
        """Which swagger definition lives in which of the two documents."""
        if document == "admin":
            return {
                "v1UpdateLoginPolicyRequest": zitadel.LOGIN_POLICY_FIELDS,
                "v1UpdateLockoutPolicyRequest": zitadel.LOCKOUT_POLICY_FIELDS,
                "v1SetRestrictionsRequest": zitadel.RESTRICTIONS_FIELDS,
            }
        return {
            "v1UpdateCustomLoginPolicyRequest": zitadel.LOGIN_POLICY_FIELDS,
            "v1UpdateCustomLabelPolicyRequest": zitadel.LABEL_POLICY_FIELDS,
            "ManagementServiceUpdateGenericOIDCProviderBody": (
                zitadel.OIDC_IDENTITY_PROVIDER_FIELDS
            ),
            "ManagementServiceUpdateGoogleProviderBody": zitadel.GOOGLE_IDENTITY_PROVIDER_FIELDS,
            "ManagementServiceUpdateOIDCAppConfigBody": zitadel.OIDC_APP_CONFIG_FIELDS,
        }

    def _document(self, title: str, document: str) -> dict[str, Any]:
        return {
            "info": {
                "title": title,
                "version": "1.0",
                "license": {"name": "Apache License 2.0"},
            },
            "definitions": {
                name: {"type": "object", "properties": {field: {} for field in sorted(fields)}}
                for name, fields in self._definitions_for(document).items()
            },
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            body = {}
        self.whole_calls.append((method, path, request.headers.get("x-zitadel-orgid", ""), body))
        answer = self._measured(method, path, body, request)
        if answer is not None:
            return answer
        return super().handle(request)

    def _measured(
        self, method: str, path: str, body: dict[str, Any], request: httpx.Request
    ) -> httpx.Response | None:
        """The measurement surfaces. `None` means "the parent knows this one"."""
        org = request.headers.get("x-zitadel-orgid", "")

        if method == "GET" and path.startswith("/openapi/v2/swagger/"):
            name = path.rsplit("/", 1)[-1].removesuffix(".swagger.json")
            document = self.swagger.get(name)
            if document is None:
                return httpx.Response(404, json={"message": "NotFound"})
            return httpx.Response(200, json=document)

        if method == "GET" and path == zitadel.INVITE_PATH:
            return httpx.Response(200, text=MEASURED_INVITE_PAGE)

        if method == "POST" and path == "/management/v1/orgs":
            new = self.id()
            self.created_orgs.append(new)
            self.orgs.append({"id": new, "name": body.get("name", ""), "state": "ORG_STATE_ACTIVE"})
            return httpx.Response(200, json={"id": new, "details": {"resourceOwner": new}})

        if method == "DELETE" and path.startswith("/admin/v1/orgs/"):
            removed = path.rsplit("/", 1)[-1]
            if removed not in self.created_orgs:
                # A fake that deleted anything it was asked to would make the
                # victim test unable to fail: what it has to catch is a
                # teardown aimed at an organisation this run did not create.
                return httpx.Response(403, json={"message": "not this run's organisation"})
            self.removed_orgs.append(removed)
            self.orgs = [one for one in self.orgs if one["id"] != removed]
            return httpx.Response(200, json={"details": {}})

        # The ORG's own login policy, which the parent serves from ONE shared
        # attribute. The measurement walks a specific org and then gives that
        # org a policy of its own half way through, so it is held per org here.
        if path == "/management/v1/policies/login" and org:
            own = self.org_own_policies.get(org)
            if method == "GET":
                policy = own or dict(ORG_LOGIN_POLICY_INHERITED)
                return httpx.Response(200, json={"policy": policy})
            if method == "PUT" and own is None:
                return httpx.Response(
                    404,
                    json={
                        "message": "Login Policy not found (Org-M0sif)",
                        "details": [{"id": "Org-M0sif", "message": "Login Policy not found"}],
                    },
                )
            if method == "POST":
                self.org_own_policies[org] = {
                    **{key: value for key, value in body.items() if value not in (False, "")},
                    "details": {"resourceOwner": org},
                }
                return httpx.Response(200, json={"details": {"resourceOwner": org}})

        if method == "PUT" and path == "/admin/v1/policies/login":
            baseline = {
                key: self.instance_login_policy.get(key, absent)
                for key, absent in zitadel.LOGIN_POLICY_ABSENT.items()
            }
            if body == baseline:
                return httpx.Response(
                    400,
                    json={
                        "message": "Default Login Policy has not been changed (INSTANCE-5M9vdd)",
                        "details": [
                            {
                                "id": "INSTANCE-5M9vdd",
                                "message": "Default Login Policy has not been changed",
                            }
                        ],
                    },
                )
            return None

        if method == "POST" and path == "/v2/users/human" and not body:
            return httpx.Response(
                400,
                json={
                    "code": 3,
                    "message": "invalid AddHumanUserRequest.Profile: value is required",
                },
            )

        if method == "POST" and path.startswith("/v2/users/") and path.endswith("/password"):
            self.passworded_users.add(path.split("/")[3])
            return httpx.Response(200, json={"details": {}})

        if method == "GET" and path == "/v2/settings/password/complexity":
            return httpx.Response(
                200, json={"details": {}, "settings": dict(MEASURED_PASSWORD_COMPLEXITY)}
            )

        if path == "/v2/sessions" and method == "POST":
            return self._open_session(body)

        if path.startswith("/v2/sessions/"):
            return self._one_session(method, path.rsplit("/", 1)[-1], body)

        # --- Mode A, the two legs the KIT reaches (M3, M4; rung A8) ---------
        # On this class rather than on a subclass because this class's whole
        # job is "every surface `zitadel_measure` reaches", and since A8 the
        # kit reaches these two. The DOOR's own Mode A world is
        # `FakeModeAZitadel` far below, which intercepts the auth-request
        # paths before this branch ever sees them — two fakes for two
        # questions: what the kit measures, and what a person at a page does.
        if method == "POST" and path.startswith("/v2/oidc/auth_requests/"):
            return self._measured_auth_request(path.rsplit("/", 1)[-1], body)
        if method == "POST" and path == "/oauth/v2/token":
            return self._measured_token()

        # --- the reset road's landing (M6; rung A11) -----------------------
        # Two halves, because M6 asks one question in two hops: a code from
        # the platform, and the page the mail's link built out of it.
        if method == "POST" and path.startswith("/v2/users/") and path.endswith("/password_reset"):
            return httpx.Response(
                200, json={"details": {}, "verificationCode": MEASURED_RESET_CODE}
            )
        if method == "GET" and path == zitadel_measure_reset_path():
            return httpx.Response(200, text=MEASURED_RESET_PAGE)

        return None

    def _measured_auth_request(self, request_id: str, body: dict[str, Any]) -> httpx.Response:
        """Finalize or refuse, as the kit's round trip drives them.

        No expiry, no already-handled and no session check: those are the
        DOOR's properties and `FakeModeAZitadel` holds them. What the kit
        needs from here is a callback URL to read, and — for M4 — the one
        thing the build actually does with the reason it is sent.
        """
        refusal = dict(body.get("error") or {})
        if refusal:
            shown = _measured_oauth_error(str(refusal.get("error", "")))
            self.refused_reasons.append(str(refusal.get("error", "")))
            return httpx.Response(
                200,
                json={
                    "details": {},
                    "callbackUrl": f"{MEASURED_CALLBACK_URI}?error={shown}&error_description=x",
                },
            )
        self.finalized_sessions.append(str(dict(body.get("session") or {}).get("sessionId", "")))
        return httpx.Response(
            200,
            json={
                "details": {},
                "callbackUrl": f"{MEASURED_CALLBACK_URI}?code=measured-{request_id}&state=",
            },
        )

    def _measured_token(self) -> httpx.Response:
        """`POST /oauth/v2/token` — two JWTs whose CLAIM NAMES are the measurement.

        M3 asks which claims this build puts in a token, so the fake mints
        real-shaped ones rather than a dictionary: the kit decodes them, and a
        kit that could not decode a token would pass here against a shape it
        cannot read in the field. The asymmetry is the MEASURED one — the
        access token carries `client_id` and no `azp`, the ID token carries
        both — because a fake that gave them the same claims could not tell a
        judgment that reads the access token from one that reads either.

        **The `sub` is the finalized session's own `factors.user.id`** — M12's
        measured fact, TRANSCRIBED rather than designed: this build makes the
        two doors name one person with one string, so the fake has to as well
        or M12 would read `DIFFERS` against a build that is behaving. A run
        with no session behind the token falls back to `MEASURED_SUBJECT`.
        """
        subject = MEASURED_SUBJECT
        if self.finalized_sessions:
            session = self.sessions.get(self.finalized_sessions[-1]) or {}
            subject = str((dict(session.get("factors") or {}).get("user") or {}).get("id", ""))
        return httpx.Response(
            200,
            json={
                "token_type": "Bearer",
                "expires_in": 3600,
                "access_token": _measured_jwt(
                    {
                        "iss": "http://zitadel.test",
                        "sub": subject,
                        "aud": [MEASURED_OIDC_CLIENT_ID],
                        "client_id": MEASURED_OIDC_CLIENT_ID,
                        "exp": 1,
                        "iat": 1,
                        "jti": "j",
                        "nbf": 1,
                    }
                ),
                "id_token": _measured_jwt(
                    {
                        "iss": "http://zitadel.test",
                        "sub": subject,
                        "aud": [MEASURED_OIDC_CLIENT_ID],
                        "client_id": MEASURED_OIDC_CLIENT_ID,
                        "azp": MEASURED_OIDC_CLIENT_ID,
                        "amr": ["pwd"],
                        "auth_time": 1,
                        "exp": 1,
                        "iat": 1,
                        "sid": "s",
                        "at_hash": "h",
                    }
                ),
            },
        )

    def _open_session(self, body: dict[str, Any]) -> httpx.Response:
        """201 with a token, or the 500 a WebAuthn challenge answers with.

        The WebAuthn branch is checked FIRST because that is the order the real
        build refuses in: the challenge is begun before the session exists, so a
        person with no registered credential never gets a 201 to read.
        """
        checks = dict(body.get("checks") or {})
        if "webAuthN" in dict(body.get("challenges") or {}):
            return httpx.Response(
                500,
                json={
                    "code": 13,
                    "message": "WebAuthN begin login failed (WEBAU-4G8sw)",
                    "details": [{"id": "WEBAU-4G8sw", "message": "WebAuthN begin login failed"}],
                },
            )
        asked = dict(checks.get("user") or {})
        user_id = str(asked.get("userId", ""))
        if not user_id and asked.get("loginName"):
            # **A login name resolves to an id here, as it does on the build.**
            # The kit's Mode A round trip opens its session by login name, and
            # a fake that left `factors.user.id` empty for that road made the
            # id_token's subject empty too — which would have made M12 read
            # `could not` on a world that is behaving.
            login_name = str(asked["loginName"])
            user_id = next(
                (
                    str(row.get("id", ""))
                    for row in self.users.values()
                    if str(row.get("userName", "")) == login_name
                ),
                "",
            )
        session_id = self.id()
        token = f"session-token-{session_id}-1"
        self.sessions[session_id] = {
            "id": session_id,
            # Only the USER factor, which is the whole of M5: a 2xx here is not
            # a verified password, and a fake that pre-filled `password` would
            # make the fail-closed rule untestable.
            "factors": {"user": {"id": user_id, "verifiedAt": "2026-09-19T03:13:47Z"}},
        }
        self.session_tokens[session_id] = token
        return httpx.Response(201, json={"sessionId": session_id, "sessionToken": token})

    def _one_session(self, method: str, session_id: str, body: dict[str, Any]) -> httpx.Response:
        if session_id not in self.sessions:
            return httpx.Response(
                404,
                json={
                    "message": "Session does not exist (QUERY-SFeaa)",
                    "details": [{"id": "QUERY-SFeaa", "message": "Session does not exist"}],
                },
            )
        if method == "GET":
            return httpx.Response(200, json={"session": self.sessions[session_id]})
        if method == "DELETE":
            self.sessions.pop(session_id)
            self.session_tokens.pop(session_id, None)
            return httpx.Response(200, json={"details": {}})
        if method == "PATCH":
            checks = dict(body.get("checks") or {})
            if not checks:
                # MEASURED, and it is the half the design's sentence missed: a
                # PATCH that verifies nothing answers no `sessionToken` AT ALL
                # rather than the one it was sent.
                return httpx.Response(200, json={"details": {}})
            if "password" in checks:
                self.sessions[session_id]["factors"]["password"] = {
                    "verifiedAt": "2026-09-19T03:13:49Z"
                }
            rotated = f"session-token-{session_id}-{len(self.session_tokens) + 2}"
            self.session_tokens[session_id] = rotated
            return httpx.Response(200, json={"details": {}, "sessionToken": rotated})
        return httpx.Response(405, json={"message": "NotAllowed"})


@pytest.fixture
def measured_instance(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    recorded_workflow_starts: None,
) -> FakeMeasuredZitadel:
    """`instance`, with the measurement surfaces. Same settings, same seam.

    A sibling of `instance` rather than a parameter on it, because every
    existing test that asks for `instance` should keep getting a socket that
    cannot answer a 500 — a fake that grew new refusal branches under thirty
    tests about something else is how a stub starts failing tests it has no
    opinion about.
    """
    fake = FakeMeasuredZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    fake.instance_login_policy.pop("allowRegister", None)
    fake.lockout_policy["maxPasswordAttempts"] = settings.ZITADEL_MAX_PASSWORD_ATTEMPTS
    fake.restrictions[
        "disallowPublicOrgRegistration"
    ] = not settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION
    # **A SEEDED deployment, because two measurements now need one.** M1 makes
    # its throwaway client under this deployment's own project and M2 asks
    # whether the machine credential may finalize a login — so a fake in the
    # FRESH-instance state would report `could not` and `DIFFERS` for two
    # items that are about a deployment `zitadel_seed` has already run on.
    # The project is created through the client's own `ensure_project`, so the
    # fake holds whatever shape that writer makes rather than a hand-built row.
    fake.instance_members[str(fake.machine["id"])] = ["IAM_OWNER", zitadel.LOGIN_CLIENT_ROLE]

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        # `timeout` is `zitadel._client`'s own keyword since the sign-in seam
        # gave the two populations of call two clocks (design I-A §3.2). It is
        # accepted and ignored: a MockTransport never waits, so the number
        # under test is the one the CALLER passes, which is asserted where the
        # caller is (`test_signin.py`) rather than here.
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    # The project is planted STRAIGHT INTO the fake rather than created
    # through `ensure_project`, because `FakeMeasuredZitadel` records every
    # call it is handed and the measurement kit's own closed-list test reads
    # that log: a fixture that dialled the socket would put a
    # `POST /management/v1/projects` at the head of "every write this command
    # made outside its own organisation", which is a claim about the fixture.
    seeded = fake.id()
    fake.projects[seeded] = {"id": seeded, "name": settings.ZITADEL_PROJECT_NAME}
    return fake


# --- the Session API, as a dictionary (design C-8; rung A3) ------------------
#
# A THIRD fake, and a subclass rather than a parameter, for the reason
# `FakeMeasuredZitadel` is one: a ceremony needs a person with a password, a
# set of enrolled factors, an org login policy and a queue of refusals a test
# can push — and thirty tests about something else should keep getting a
# socket with none of that in it. Appended at the end of this file so the two
# fakes above read exactly as they did.
#
# The session shapes are the ones the pinned build answered, recorded by
# `manage.py zitadel_measure` (M5, M8, M9) and re-used here rather than
# invented: a 201 whose factors carry `user` and no `password` when no
# password was checked, a PATCH that VERIFIES rotating the token and a PATCH
# that verifies nothing answering none at all, and the WebAuthn 500.

#: The one person a sign-in test signs in as, and the password they type.
#: Both are fixture data for a socket that is a dictionary — no account
#: anywhere holds either — and the password is shaped like a real one because
#: a complexity policy is one of the things the ceremony reads.
SIGNIN_LOGIN_NAME = "ada@yourco.test"
SIGNIN_PASSWORD = "Correct-Horse-Battery-7!"  # pragma: allowlist secret
SIGNIN_USER_ID = "5001"
#: The six digits the authenticator in these tests shows.
SIGNIN_FACTOR_CODE = "123456"


class FakeSignInZitadel(FakeMeasuredZitadel):
    """The Session API as one ceremony sees it, with the knobs a test needs.

    Every knob is a piece of the WORLD rather than a way to make an assertion
    pass: which factors this person enrolled, what the org's login settings
    say, and a queue of refusals the next session call answers with — which is
    how the four fail-closed rules are driven, because each of them is about a
    refusal shape and a fake with no way to refuse can only prove the happy
    road.
    """

    def __init__(self) -> None:
        super().__init__()
        self.login_name = SIGNIN_LOGIN_NAME
        self.password = SIGNIN_PASSWORD
        self.person_id = SIGNIN_USER_ID
        self.factor_code = SIGNIN_FACTOR_CODE
        #: Zitadel's own names for what this person has enrolled.
        #: **`…_PASSWORD` is always in the list**, MEASURED by hand against
        #: the pinned build on 2026-09-18 (`GET /v2/users/{id}/
        #: authentication_methods` for a person with a password and nothing
        #: else answers `authMethodTypes: ['AUTHENTICATION_METHOD_TYPE_
        #: PASSWORD']`) — so the default here is that list and not `[]`. A
        #: fake that answered an empty list would let a seam which read
        #: "non-empty means a second factor" pass here and send every person
        #: on the real build to a factor form they cannot answer.
        self.auth_methods: list[str] = ["AUTHENTICATION_METHOD_TYPE_PASSWORD"]
        #: The org's login settings, in the shape `GET /v2/settings/login`
        #: answers. `mfaInitSkipLifetime` non-zero is what makes *Not now*
        #: offerable (design J2-c).
        self.login_settings: dict[str, Any] = {"mfaInitSkipLifetime": "2592000s"}
        #: `(status, error_id)` answered by the NEXT session call, then popped.
        self.refusals: list[tuple[int, str]] = []
        #: What the seam opened and what it closed. Two lists rather than a
        #: set difference, because the property under test is "every one", and
        #: a set would hide a session closed twice and one never closed at all.
        self.opened_sessions: list[str] = []
        self.closed_sessions: list[str] = []
        #: Raised instead of answering, when a test asks for a dead socket.
        self.transport_fails = False
        #: Every reset the platform was asked for, as `(user_id, body)`. A
        #: LIST because "exactly once, and never for an address nobody has"
        #: is the property, and a set could not tell one ask from three.
        self.reset_requests: list[tuple[str, str]] = []
        #: **The instance's SMTP sender, and whether there is one at all**
        #: (A6.1). `GET /admin/v1/smtp`'s body as MEASURED for a CONFIGURED
        #: instance — `smtpConfig` carrying `senderAddress`, `senderName`,
        #: `host`, `state`, `description`, `id`, and never the password —
        #: is what a test puts here; the default is `{}`, an instance with no
        #: mail sender, because that is what a fresh stack is and it is the
        #: state in which an emailed code cannot be delivered.
        #:
        #: **The no-sender ANSWER is not measured**, only the no-sender state:
        #: nobody has taken the SMTP configuration off the pinned build to see
        #: whether it 404s or answers an empty envelope. `smtp_none_answers`
        #: is which of the two this fake plays, so the door's behaviour can be
        #: driven on both and cannot depend on the one somebody guessed.
        self.smtp: dict[str, Any] = {}
        self.smtp_none_answers: str = "empty"
        #: Refused outright, when a test asks what happens if we cannot look.
        self.smtp_unreadable = False
        #: **The relying party this person's passkey is bound to, or `None`
        #: for a person who has none.** One string rather than a list because
        #: the whole of what design J6 turns on is WHICH party a credential
        #: belongs to, and A9's drive measured the answer to be the same for
        #: nought credentials and for one bound elsewhere.
        #:
        #: MEASURED on v4.17.1 (2026-09-19) with a virtual authenticator, and
        #: this is the shape modelled below: a begin whose `domain` equals
        #: this answers **201/200** carrying
        #: `challenges.webAuthN.publicKeyCredentialRequestOptions.publicKey`
        #: with `rpId` echoing the domain and one `allowCredentials` entry; a
        #: begin whose `domain` does NOT — including the person with no
        #: credential at all, and a domain neither party owns — answers
        #: **500 `WEBAU-4G8sw`**, the same status and the same id every time.
        #: A begin with no `user` check at all answers
        #: **400 `COMMAND-eeR2e`**: there is no discoverable road here.
        self.passkey_rp: str | None = None
        #: The credential id the virtual device would hand back. Fixed, so a
        #: test can assert the assertion that came back is the one that went out.
        self.passkey_credential_id = "a9-credential"
        #: The organisation this person is in, as the session read reports it.
        self.org_id = "387613333072707590"
        #: **The emailed code is EIGHT digits, and the app's is six.** MEASURED
        #: by V-A-W3 off Mailpit: `Your sign-in code is 41470160`. The fake
        #: answered one six-digit code for every kind, so a page that capped
        #: the field at six was green here and truncated every real emailed
        #: code into a refusal.
        self.email_code = "41470160"
        #: Every code this fake has "sent", in order — a test asserts the
        #: person was really challenged rather than shown a form.
        self.codes_sent: list[tuple[str, str]] = []
        #: Which organisation each login-settings read was scoped to.
        self.login_settings_orgs: list[str] = []
        # **The management row for the person who can sign in.** Planted on
        # the world rather than by each test, because a person the Session
        # API knows and the management search does not is a state this
        # instance cannot be in — and two roads read that row: the landing's
        # assertion (`asserted_person`) and the passkey road's
        # elsewhere/none discrimination, which has no session to read an id
        # from when the begin is the thing that failed.
        self.users[SIGNIN_USER_ID] = {
            "id": SIGNIN_USER_ID,
            "userName": SIGNIN_LOGIN_NAME,
            "human": {"email": {"email": SIGNIN_LOGIN_NAME, "isEmailVerified": True}},
        }

    # --- the routes ------------------------------------------------------
    def _measured(
        self, method: str, path: str, body: dict[str, Any], request: httpx.Request
    ) -> httpx.Response | None:
        if self.transport_fails:
            raise httpx.ConnectError("the socket this test unplugged")

        if path == "/v2/sessions" and method == "POST":
            return self._signin_open(body)
        if path.startswith("/v2/sessions/"):
            return self._signin_one(method, path.rsplit("/", 1)[-1], body)
        if method == "GET" and path.endswith("/authentication_methods"):
            reported = list(self.auth_methods)
            if self.passkey_rp is not None and "AUTHENTICATION_METHOD_TYPE_PASSKEY" not in reported:
                # A registered passkey shows up here whatever it is bound to —
                # measured, and the whole basis of the elsewhere/none
                # discrimination. Derived rather than left to each test to
                # remember, so a world cannot say "has a passkey" in one place
                # and "has none" in the other.
                reported.append("AUTHENTICATION_METHOD_TYPE_PASSKEY")
            return httpx.Response(200, json={"authMethodTypes": reported})
        if method == "GET" and path == "/v2/settings/login":
            # **The org rides in the QUERY (`?ctx.orgId=`), not in a header**,
            # so the request log keyed on `x-zitadel-orgid` cannot see it —
            # which is how "the settings are read for nobody's org" stayed
            # invisible. Recorded here, where it actually travels.
            self.login_settings_orgs.append(str(request.url.params.get("ctx.orgId", "")))
            return httpx.Response(200, json={"settings": dict(self.login_settings)})
        if method == "GET" and path.startswith("/v2/users/") and path.count("/") == 3:
            # `GET /v2/users/{id}` — not org-scoped, which is the whole point
            # (V-A-W3: a person in another org authenticated and then 503'd
            # because the management search answered no rows for them).
            row = self.users.get(path.rsplit("/", 1)[-1])
            if row is None:
                return httpx.Response(404, json={"message": "User not found (QUERY-Dfbg2)"})
            # **The v2 SHAPE, not the v1 row.** MEASURED: `user.userId`,
            # `user.human.email.email` and `user.human.email.`**`isVerified`**
            # — where the v1 search row beside it spells the same fact
            # `isEmailVerified`. Translated here rather than served raw so a
            # seam that reads the v1 name off a v2 body fails in this suite
            # instead of making every person unverified in a browser.
            v1_email = dict((row.get("human") or {}).get("email") or {})
            return httpx.Response(
                200,
                json={
                    "user": {
                        "userId": row.get("id", ""),
                        "username": row.get("userName", ""),
                        "state": "USER_STATE_ACTIVE",
                        "human": {
                            "email": {
                                "email": v1_email.get("email", ""),
                                "isVerified": bool(v1_email.get("isEmailVerified")),
                            }
                        },
                    }
                },
            )
        if method == "GET" and path == "/admin/v1/smtp":
            if self.smtp_unreadable:
                return httpx.Response(503, json={"message": "the test unplugged the mail sender"})
            if self.smtp:
                return httpx.Response(200, json={"smtpConfig": dict(self.smtp)})
            if self.smtp_none_answers == "missing":
                return httpx.Response(404, json={"message": "No SMTP configuration (SMTP-4tf)"})
            return httpx.Response(200, json={})
        if method == "POST" and path.endswith("/password_reset"):
            return _reset_requests_route(self, path.split("/")[3], body)
        if method == "POST" and path.endswith("/totp/verify"):
            # **`verify`, NO UNDERSCORE** — MEASURED side by side on v4.17.1:
            # `/totp/_verify` answers 404 for every input and `/totp/verify`
            # answers 200 and enrols the factor. The fake answered the wrong
            # spelling too, so a door that called the wrong one was green
            # here and 503'd on a correct code in a browser. A fake that
            # accepts a path the platform does not have is the same defect
            # as a door that calls one.
            if str(body.get("code", "")) != self.factor_code:
                return self._signin_refusal(400, "COMMAND-8ugTs", "Invalid code")
            self.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")
            return httpx.Response(200, json={"details": {}})
        if method == "POST" and path.endswith("/totp") and path.startswith("/v2/users/"):
            return httpx.Response(
                200,
                json={
                    "uri": f"otpauth://totp/Pilecap:{self.login_name}?secret=ENROLSECRET",
                    # The fake's TOTP enrolment secret, four bytes of
                    # capitals for a socket that is a dictionary.
                    "secret": "ENROLSECRET",  # pragma: allowlist secret
                },
            )
        return super()._measured(method, path, body, request)

    # --- the sessions ----------------------------------------------------
    def _signin_refusal(self, status: int, error_id: str, message: str) -> httpx.Response:
        return httpx.Response(
            status,
            json={"message": f"{message} ({error_id})", "details": [{"id": error_id}]},
        )

    def _queued(self) -> httpx.Response | None:
        if not self.refusals:
            return None
        status, error_id = self.refusals.pop(0)
        return self._signin_refusal(status, error_id, "refused by the test's world")

    def _signin_open(self, body: dict[str, Any]) -> httpx.Response:
        queued = self._queued()
        if queued is not None:
            return queued
        checks = dict(body.get("checks") or {})
        asked = dict(body.get("challenges") or {})
        webauthn = dict(asked.get("webAuthN") or {}) if "webAuthN" in asked else None
        if webauthn is not None and not checks.get("user"):
            # The discoverable road, refused — A9's measurement, and the
            # reason `passkey_begin` takes a login name.
            return self._signin_refusal(400, "COMMAND-eeR2e", "User ID missing")
        user = dict(checks.get("user") or {})
        named = str(user.get("loginName", "") or user.get("userId", ""))
        if named not in (self.login_name, self.person_id):
            # MEASURED shape: an unknown login name is a 404 with Zitadel's own
            # id, NOT a 401 — which is what keeps "we could not look" and "that
            # is not right" on different roads (fail-closed rule 3).
            return self._signin_refusal(404, "QUERY-Dfbg2", "User not found")
        password = dict(checks.get("password") or {})
        if password and str(password.get("password", "")) != self.password:
            # MEASURED by hand against the pinned build on 2026-09-18: a wrong
            # password on the create answers `400 COMMAND-3M0fs`
            # ("Password is invalid"), NOT a 401 — which is the whole of what
            # keeps fail-closed rule 3 distinguishable from rule 1.
            return self._signin_refusal(400, "COMMAND-3M0fs", "Password is invalid")
        session_id = self.id()
        token = f"session-token-{session_id}-1"
        # The READ's own shape, MEASURED: `factors.user` carries `id`,
        # `loginName`, `displayName` and **`organizationId`** — the last is
        # what a login-settings read has to be scoped by, and a fake that
        # omitted it let a ceremony ask for the INSTANCE default and be green.
        factors: dict[str, Any] = {
            "user": {
                "id": self.person_id,
                "verifiedAt": "2026-09-19T03:13:47Z",
                "loginName": self.login_name,
                "displayName": "The Person",
                "organizationId": self.org_id,
            }
        }
        if password:
            factors["password"] = {"verifiedAt": "2026-09-19T03:13:48Z"}
        self.sessions[session_id] = {"id": session_id, "factors": factors}
        self.session_tokens[session_id] = token
        self.opened_sessions.append(session_id)
        # **THE CREATE CARRIES NO `factors` BLOCK** — MEASURED on v4.17.1
        # (2026-09-19): `POST /v2/sessions` answers `details`, `sessionId`
        # and `sessionToken`, and nothing else. The fake used to hand one
        # back on the passkey road, which is why a seam that read
        # `factors.user.id` off the create passed every test here and gave a
        # person who had just proved a passkey a 503 in a real browser
        # (V-A-W3). The id is on the READ, and that is the only place it is.
        answer: dict[str, Any] = {"sessionId": session_id, "sessionToken": token}
        if webauthn is not None:
            challenge = self._webauthn_challenge(webauthn, named=True)
            if challenge is None:
                # The session was NOT made: the begin failed as a whole, which
                # is what leaves `passkey_begin` with no id to read methods by.
                self.sessions.pop(session_id)
                self.session_tokens.pop(session_id, None)
                self.opened_sessions.pop()
                return self._webauthn_refusal()
            answer["challenges"] = challenge
        return httpx.Response(201, json=answer)

    def _webauthn_refusal(self) -> httpx.Response:
        """M9's 500, and the reading that makes it a sentence rather than a retry."""
        return self._signin_refusal(
            500, zitadel.WEBAUTHN_NO_CREDENTIAL, "WebAuthN begin login failed"
        )

    def _webauthn_challenge(self, asked: dict[str, Any], *, named: bool) -> dict[str, Any] | None:
        """The challenge block for a begin, or `None` when this build refuses.

        Three refusals and one answer, all measured (see `passkey_rp`): no
        user check is `None` with the discoverable refusal raised by the
        caller; a domain that is not what the person's credential is bound
        to — or no credential — is `None` with the 500; a match is the block.
        """
        if not named or self.passkey_rp is None:
            return None
        if str(asked.get("domain", "")) != self.passkey_rp:
            return None
        return {
            "webAuthN": {
                "publicKeyCredentialRequestOptions": {
                    "publicKey": {
                        "challenge": "YTktY2hhbGxlbmdl",
                        "rpId": self.passkey_rp,
                        "timeout": "300s",
                        "userVerification": "required",
                        "allowCredentials": [
                            {"id": self.passkey_credential_id, "type": "public-key"}
                        ],
                    }
                }
            }
        }

    def _webauthn_verified(self, sent: dict[str, Any]) -> bool:
        """Whether an assertion is the one this person's device would produce."""
        assertion = sent.get("credentialAssertionData")
        if not isinstance(assertion, dict):
            return False
        return str(assertion.get("id", "")) == self.passkey_credential_id

    def _signin_one(self, method: str, session_id: str, body: dict[str, Any]) -> httpx.Response:
        queued = self._queued()
        if queued is not None:
            return queued
        if session_id not in self.sessions:
            return self._signin_refusal(404, zitadel.SESSION_GONE, "Session does not exist")
        if method == "GET":
            return httpx.Response(200, json={"session": self.sessions[session_id]})
        if method == "DELETE":
            self.closed_sessions.append(session_id)
            self.sessions.pop(session_id)
            self.session_tokens.pop(session_id, None)
            return httpx.Response(200, json={"details": {}})
        if method != "PATCH":
            return httpx.Response(405, json={"message": "NotAllowed"})

        challenges = dict(body.get("challenges") or {})
        if "webAuthN" in challenges:
            challenge = self._webauthn_challenge(dict(challenges["webAuthN"] or {}), named=True)
            if challenge is None:
                return self._webauthn_refusal()
            return httpx.Response(200, json={"details": {}, "challenges": challenge})
        if challenges:
            for kind in ("otpEmail", "otpSms"):
                if kind in challenges:
                    # The platform really does send something here, and a
                    # fake that did not record it let a page ask for a code
                    # nobody had been told to mail (V-A-W3: Mailpit empty).
                    self.codes_sent.append((kind, self.email_code))
            # MEASURED (M8): a PATCH that verifies NOTHING answers no
            # `sessionToken` at all. The whole point of modelling it is that a
            # ceremony which wrote the answer's token unconditionally would
            # carry an empty string forward from here.
            return httpx.Response(200, json={"details": {}})
        checks = dict(body.get("checks") or {})
        for name, sent in checks.items():
            if name in ("otpEmail", "otpSms"):
                if str(dict(sent).get("code", "")) != self.email_code:
                    return self._signin_refusal(400, "COMMAND-8ugTs", "Invalid code")
                self.sessions[session_id]["factors"][name] = {"verifiedAt": "2026-09-19T03:13:49Z"}
                continue
            if name == "webAuthN":
                if not self._webauthn_verified(dict(sent)):
                    return self._signin_refusal(400, "COMMAND-3M9si", "Invalid assertion")
                self.sessions[session_id]["factors"][name] = {"verifiedAt": "2026-09-19T08:10:01Z"}
                continue
            if str(dict(sent).get("code", "")) != self.factor_code:
                return self._signin_refusal(400, "COMMAND-8ugTs", "Invalid code")
            self.sessions[session_id]["factors"][name] = {"verifiedAt": "2026-09-19T03:13:49Z"}
        rotated = f"session-token-{session_id}-{len(self.session_tokens) + 2}"
        self.session_tokens[session_id] = rotated
        return httpx.Response(200, json={"details": {}, "sessionToken": rotated})


@pytest.fixture
def signin_instance(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    recorded_workflow_starts: None,
) -> Iterator[FakeSignInZitadel]:
    """`measured_instance`, with a person who can sign in — and a clean throttle.

    The cache is cleared on the way in AND on the way out, because the seam's
    per-address limiter counts into the shared cache: a test that spent five
    tries would otherwise throttle the next test that signed in as the same
    person, and the failure would land on whichever test happened to run
    second under `-p randomly`.
    """
    fake = FakeSignInZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    fake.instance_login_policy.pop("allowRegister", None)
    fake.lockout_policy["maxPasswordAttempts"] = settings.ZITADEL_MAX_PASSWORD_ATTEMPTS

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    cache.clear()
    yield fake
    cache.clear()


# --- the INVITE road, as a dictionary (design C-11; rung A7) ------------------
#
# A FOURTH surface on the same fake rather than a fourth class: the invite road
# ends by opening a Session API session, so a test that could set a password
# but not then sign in would prove half a journey. The shapes below are the
# ones the pinned build answered on 2026-09-19, hand-measured because
# `zitadel_measure` reaches the invite PAGE (C7, M10) and the invite CODE's
# expiry (C2) but never the two calls the road is made of:
#
#   POST /v2/users/{id}/invite_code/verify  {"verificationCode": "<six>"}
#       200 on the live code · 400 COMMAND-Wgn4q "Code is invalid" on a code
#       that is wrong, used, or superseded · 400 COMMAND-F5g2h "User could not
#       be found" for an id that is not there.
#       The `_verify` spelling — the one every other v2 verb in this build
#       uses — is a **404**, so the route is `verify` and it is written down
#       here because a plausible guess is wrong.
#   POST /v2/users/{id}/password  {"newPassword": {"password", "changeRequired"}}
#       200 · 400 DOMAIN-HuJf6 "Password is too short" for one the policy
#       refuses. **No verification block**: the machine PAT authorises it.
#
# The last line is the one that shapes the fake, and it is why
# `verified_invites` exists here rather than a boolean somewhere: MEASURED, the
# PAT can set any person's password with **no code at all** (world `noverify`,
# item I). So the invite code is not a credential Zitadel checks on the write —
# it is a credential OUR seam checks on the read before it makes the write, and
# a fake that answered 200 to an unverified write could not tell a seam that
# verifies from one that does not.

#: The person a J1 test is invited as. A second human beside `SIGNIN_*`'s,
#: because the invited one must start with NO password: giving the sign-in
#: person an invite code would make "this link was already used" unreachable.
SIGNIN_INVITED_LOGIN_NAME = "grace@yourco.test"
SIGNIN_INVITED_USER_ID = "5002"
#: Six uppercase alphanumerics — the shape `zitadel_measure` C2 measured
#: (length 6) and the shape the live build minted on 2026-09-19.
SIGNIN_INVITE_CODE = "XJDXR7"


class FakeInvitedZitadel(FakeSignInZitadel):
    """The sign-in fake, plus one invited person and the two calls of the road.

    Every knob is a state of the WORLD: whether the code is still live,
    whether the person has already set a password, and what the policy refuses.
    A test makes a state and then drives the door; none of them is a way to
    make an assertion pass.
    """

    def __init__(self) -> None:
        super().__init__()
        self.invited_id = SIGNIN_INVITED_USER_ID
        self.invited_login_name = SIGNIN_INVITED_LOGIN_NAME
        self.invited_code = SIGNIN_INVITE_CODE
        #: Whether the platform says it verified the invited person's ADDRESS.
        #: A knob, because with it hard-coded true the adapter's first refusal
        #: is unreachable on this road exactly as it would be on the other.
        self.invited_address_verified = True
        #: What `authentication_methods` answers for the invited person.
        #: MEASURED: a credential-less person answers a body with **no
        #: `authMethodTypes` key at all**, not an empty list.
        self.invited_methods: list[str] = []
        #: User ids whose live code this run has verified. The write below
        #: refuses an id that is not in here — not because Zitadel does, but
        #: so that a seam which skipped the verify cannot pass.
        self.verified_invites: set[str] = set()
        #: What the invited person's password ended up as, if they set one.
        self.set_passwords: dict[str, str] = {}
        #: The shortest password this fake's policy accepts — the pinned
        #: build's own `minLength` (M11), so the refusal a test drives is the
        #: refusal the build gives.
        self.password_min_length = int(MEASURED_PASSWORD_COMPLEXITY["minLength"])
        #: The org's complexity policy as `GET /v2/settings/password/complexity`
        #: answers it. A knob rather than the parent's constant, because the
        #: rule SENTENCE on the frame is derived from it and a sentence
        #: derived from a fixed dictionary is a sentence a hard-coded string
        #: would also satisfy.
        self.password_rules: dict[str, Any] = dict(MEASURED_PASSWORD_COMPLEXITY)
        #: The v1 SEARCH row `find_user` reads — note `isEmailVerified`, which
        #: is v1's spelling of the flag v2's read calls `isVerified`. Two
        #: spellings of one fact, and the fake carries both so a seam that
        #: read the wrong one on the wrong surface fails here.
        self.users[self.invited_id] = {
            "id": self.invited_id,
            "userName": self.invited_login_name,
            "human": {
                "email": {
                    "email": self.invited_login_name,
                    "isEmailVerified": self.invited_address_verified,
                }
            },
        }

    def _measured(
        self, method: str, path: str, body: dict[str, Any], request: httpx.Request
    ) -> httpx.Response | None:
        if self.transport_fails:
            raise httpx.ConnectError("the socket this test unplugged")

        if method == "POST" and path.endswith("/invite_code/verify"):
            return self._invite_verify(path.split("/")[3], body)
        if method == "POST" and path.startswith("/v2/users/") and path.endswith("/password"):
            return self._invite_set_password(path.split("/")[3], body)
        if method == "GET" and path.endswith("/authentication_methods"):
            who = path.split("/")[3]
            if who == self.invited_id:
                answer: dict[str, Any] = {"details": {}}
                if self.invited_methods:
                    answer["authMethodTypes"] = list(self.invited_methods)
                return httpx.Response(200, json=answer)
        if method == "GET" and path.startswith("/v2/users/") and path.count("/") == 3:
            return self._read_human(path.rsplit("/", 1)[-1])
        if method == "GET" and path == "/v2/settings/password/complexity":
            if not self.password_rules:
                return httpx.Response(200, json={"details": {}})
            return httpx.Response(200, json={"details": {}, "settings": dict(self.password_rules)})
        return super()._measured(method, path, body, request)

    # --- the two calls of the road ----------------------------------------
    def _invite_verify(self, user_id: str, body: dict[str, Any]) -> httpx.Response:
        queued = self._queued()
        if queued is not None:
            return queued
        if user_id not in self.users:
            return self._signin_refusal(400, "COMMAND-F5g2h", "User could not be found")
        if user_id in self.set_passwords or user_id in self.initialized_users:
            # A person who has credentials has no live code: the same
            # `Code is invalid` a used code answers, which is why the door
            # cannot tell those two apart from the write and reads the
            # person's enrolled methods instead.
            return self._signin_refusal(400, "COMMAND-Wgn4q", "Code is invalid")
        if str(body.get("verificationCode", "")) != self.invited_code:
            return self._signin_refusal(400, "COMMAND-Wgn4q", "Code is invalid")
        self.verified_invites.add(user_id)
        return httpx.Response(200, json={"details": {}})

    def _invite_set_password(self, user_id: str, body: dict[str, Any]) -> httpx.Response:
        queued = self._queued()
        if queued is not None:
            return queued
        if user_id not in self.verified_invites:
            # NOT Zitadel's behaviour, deliberately: the live build accepts
            # this write on the PAT alone. The fake refuses it so that a seam
            # which never verified is a RED here rather than a green road that
            # lets anybody holding a user id set that person's password.
            return httpx.Response(
                599,
                json={
                    "message": (
                        "this fake refuses a password write for a user whose invite code "
                        "was never verified — the live build would accept it, and that is "
                        "the hazard this refusal exists to catch"
                    )
                },
            )
        chosen = str(dict(body.get("newPassword") or {}).get("password", ""))
        if len(chosen) < self.password_min_length:
            return self._signin_refusal(400, "DOMAIN-HuJf6", "Password is too short")
        self.set_passwords[user_id] = chosen
        self.password = chosen if user_id == self.person_id else self.password
        self.invited_methods = ["AUTHENTICATION_METHOD_TYPE_PASSWORD"]
        self.verified_invites.discard(user_id)
        return httpx.Response(200, json={"details": {}})

    def _read_human(self, user_id: str) -> httpx.Response:
        """`GET /v2/users/{id}`, in the shape measured on 2026-09-19.

        `human.email.isVerified` — v2's spelling. The v1 search row above
        spells the same fact `isEmailVerified`, and a seam that read v1's name
        off this body would get `False` for everybody, which is a refusal
        nobody could debug.
        """
        found = self.users.get(user_id)
        if found is None:
            return self._signin_refusal(404, "QUERY-Dfbg2", "User not found")
        address = str(dict(dict(found.get("human") or {}).get("email") or {}).get("email", ""))
        verified = bool(
            dict(dict(found.get("human") or {}).get("email") or {}).get("isEmailVerified")
        )
        return httpx.Response(
            200,
            json={
                "details": {},
                "user": {
                    "userId": user_id,
                    "username": found.get("userName", ""),
                    "preferredLoginName": found.get("userName", ""),
                    "state": "USER_STATE_ACTIVE",
                    "human": {
                        "email": {"email": address, "isVerified": verified},
                        "profile": {"givenName": "Grace", "familyName": "Hopper"},
                    },
                },
            },
        )

    def _signin_open(self, body: dict[str, Any]) -> httpx.Response:
        """The parent's, with the invited person's own password honoured."""
        checks = dict(body.get("checks") or {})
        user = dict(checks.get("user") or {})
        named = str(user.get("loginName", "") or user.get("userId", ""))
        chosen = self.set_passwords.get(self.invited_id, "")
        if named == self.invited_login_name and chosen:
            was_name, was_id, was_password = self.login_name, self.person_id, self.password
            self.login_name, self.person_id, self.password = (
                self.invited_login_name,
                self.invited_id,
                chosen,
            )
            try:
                return super()._signin_open(body)
            finally:
                self.login_name, self.person_id, self.password = was_name, was_id, was_password
        return super()._signin_open(body)


@pytest.fixture
def invited_instance(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    recorded_workflow_starts: None,
) -> Iterator[FakeInvitedZitadel]:
    """`signin_instance`'s world, with one invited person in it."""
    fake = FakeInvitedZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    fake.instance_login_policy.pop("allowRegister", None)
    fake.lockout_policy["maxPasswordAttempts"] = settings.ZITADEL_MAX_PASSWORD_ATTEMPTS

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    cache.clear()
    yield fake
    cache.clear()


# --- Mode A: the OIDC auth request, as a dictionary (design C-10; rung A8) ---
#
# A FIFTH surface, and a subclass again for the reason the other three are:
# a Mode A ceremony is a sign-in ceremony with one more thing on the end, and
# the tests that are about the ordinary road should keep getting a socket with
# no auth requests in it.
#
# The shapes are the ones the pinned build (v4.17.1) answered on 2026-09-19,
# measured end to end on a throwaway native client under this deployment's own
# project and a throwaway human in a throwaway organisation:
#
#   GET  /v2/oidc/auth_requests/{id}
#       200 {"authRequest": {"id", "creationDate", "clientId", "scope": [...],
#            "redirectUri"}} — with "prompt": ["PROMPT_CREATE"] and
#            "loginHint" present only when the client asked for them.
#            **`prompt` is ABSENT, not `[]`, when none was asked for.**
#       404 QUERY-Thee9.
#   POST /v2/oidc/auth_requests/{id} {"session": {...}}
#       200 {"callbackUrl": "<redirectUri>?code=…&state="}
#       404 COMMAND-jae5P · 400 COMMAND-Sx208nt (already handled)
#   POST /v2/oidc/auth_requests/{id} {"error": {...}}
#       200 {"callbackUrl": "<redirectUri>?error=…&error_description=…"}
#
# **M4 is modelled rather than described**: `ERROR_REASON_ACCESS_DENIED` comes
# out as `error=access_denied` and ANY other spelling — the RFC lowercase
# `access_denied` a reader of the OAuth spec reaches for, measured — comes out
# as `error=server_error`. A fake that echoed whatever it was sent would let a
# door ship the wrong spelling and look right here while telling every client
# in the field that the authorization server broke.
#
# **And the finalize refuses a session this fake has already closed.** The live
# build mints the client's code against the named session, so the ordering in
# `signin._finish` — finalize, THEN close (ADR ident-10) — is the whole of why
# Mode A works; a fake indifferent to it could not tell that ordering from its
# reverse.

#: The client the Mode A tests are sent by, and where it wants to be sent back.
SIGNIN_OIDC_CLIENT_ID = "9001"
SIGNIN_CALLBACK_URI = "http://127.0.0.1:41999/mcp-client/callback"
SIGNIN_AUTH_REQUEST_ID = "V2_700000000000000001"


class FakeModeAZitadel(FakeInvitedZitadel):
    """The sign-in world, with an OIDC client waiting on the other side."""

    def __init__(self) -> None:
        super().__init__()
        self.auth_request_id = SIGNIN_AUTH_REQUEST_ID
        self.oidc_client_id = SIGNIN_OIDC_CLIENT_ID
        self.callback_uri = SIGNIN_CALLBACK_URI
        #: `prompt` values the client asked for. Empty means the key is ABSENT
        #: from the read, which is what the pinned build answers.
        self.prompts: list[str] = []
        #: The address the client says it is sending, or `""` for no hint.
        self.login_hint = ""
        #: Auth requests already answered — a second finalize of one of these
        #: is `COMMAND-Sx208nt`, exactly as the build answers.
        self.handled_requests: set[str] = set()
        #: Every finalize this fake was asked for, as
        #: `(request_id, session_id, "session"|"error", detail)`. A LIST
        #: because the property several cases assert is "exactly once".
        self.finalizes: list[tuple[str, str, str, str]] = []
        #: The v1 SEARCH row the DOOR reads to build its assertion
        #: (`signin.asserted_person`). Planted here and not in
        #: `FakeSignInZitadel` because it is the door's read and not the
        #: seam's — the same reason `test_signin_door.py`'s own `door`
        #: fixture plants it — and it is needed HERE so that one world can
        #: drive both roads: Mode A, which never asks for it, and the
        #: ordinary landing beside it, which is the negative that keeps Mode
        #: A's session exception an exception.
        self.users[self.person_id] = {
            "id": self.person_id,
            "userName": self.login_name,
            "human": {"email": {"email": self.login_name, "isEmailVerified": True}},
        }

    def _measured(
        self, method: str, path: str, body: dict[str, Any], request: httpx.Request
    ) -> httpx.Response | None:
        if self.transport_fails:
            raise httpx.ConnectError("the socket this test unplugged")
        if path.startswith("/v2/oidc/auth_requests/"):
            found = path.rsplit("/", 1)[-1]
            if method == "GET":
                return self._read_auth_request(found)
            if method == "POST":
                return self._answer_auth_request(found, body)
        return super()._measured(method, path, body, request)

    def _read_auth_request(self, request_id: str) -> httpx.Response:
        queued = self._queued()
        if queued is not None:
            return queued
        if request_id != self.auth_request_id:
            return self._signin_refusal(404, "QUERY-Thee9", "Auth Request does not exist")
        found: dict[str, Any] = {
            "id": request_id,
            "creationDate": "2026-09-19T07:42:07.201397Z",
            "clientId": self.oidc_client_id,
            "scope": ["openid", "email", "profile"],
            "redirectUri": self.callback_uri,
        }
        if self.prompts:
            found["prompt"] = list(self.prompts)
        if self.login_hint:
            found["loginHint"] = self.login_hint
        return httpx.Response(200, json={"authRequest": found})

    def _answer_auth_request(self, request_id: str, body: dict[str, Any]) -> httpx.Response:
        queued = self._queued()
        if queued is not None:
            return queued
        if request_id != self.auth_request_id:
            return self._signin_refusal(404, "COMMAND-jae5P", "Auth Request does not exist")
        if request_id in self.handled_requests:
            return self._signin_refusal(
                400, "COMMAND-Sx208nt", "Auth Request has already been handled"
            )

        refusal = dict(body.get("error") or {})
        if refusal:
            self.handled_requests.add(request_id)
            self.finalizes.append((request_id, "", "error", str(refusal.get("error", ""))))
            # M4, modelled: only the ENUM spelling survives; every other one
            # degrades to `server_error` at the client.
            sent = str(refusal.get("error", ""))
            shown = "access_denied" if sent == zitadel.REFUSE_ACCESS_DENIED else "server_error"
            described = quote(str(refusal.get("errorDescription", "")), safe="")
            return httpx.Response(
                200,
                json={
                    "details": {},
                    "callbackUrl": (
                        f"{self.callback_uri}?error={shown}&error_description={described}"
                    ),
                },
            )

        session = dict(body.get("session") or {})
        session_id = str(session.get("sessionId", ""))
        if session_id not in self.sessions:
            # The ordering guard. Not an error id the build answers with —
            # the build would mint against a live session and this is a
            # session already closed — so it is shaped as one this seam reads
            # as an outage rather than as "your link expired", and the body
            # says what it is for.
            return httpx.Response(
                412,
                json={
                    "message": (
                        "this fake refuses a finalize naming a session it has already "
                        "closed — the code is minted against that session, so a seam "
                        "that closed before finalizing would have nothing to hand back"
                    )
                },
            )
        self.handled_requests.add(request_id)
        self.finalizes.append((request_id, session_id, "session", ""))
        return httpx.Response(
            200,
            json={
                "details": {},
                "callbackUrl": f"{self.callback_uri}?code=mode-a-code-{session_id}&state=",
            },
        )


@pytest.fixture
def mode_a_instance(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    recorded_workflow_starts: None,
) -> Iterator[FakeModeAZitadel]:
    """`invited_instance`'s world, with one OIDC client waiting on a callback."""
    fake = FakeModeAZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    fake.instance_login_policy.pop("allowRegister", None)
    fake.lockout_policy["maxPasswordAttempts"] = settings.ZITADEL_MAX_PASSWORD_ATTEMPTS

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    cache.clear()
    yield fake
    cache.clear()


# --- the reset road, as a dictionary (design J5; rung A11b) ------------------
#
# One route on the sign-in fake rather than a sixth class: the reset is one
# write on a person the fake already has, and what the tests need from it is
# a COUNT — was the platform asked, exactly once, and only for somebody who
# exists. The shape is the one the pinned build answered on 2026-09-19:
#
#   POST /v2/users/{id}/password_reset  {"sendLink": {}}
#       200 {"details": {...}} and a mail leaves the instance. An empty
#       `sendLink` is what this tree sends; `{"returnCode": {}}` would answer
#       `verificationCode` in the body instead and send nothing, which is
#       M6's road.
#   404 COMMAND-SAF4f for an id that is not there — never reached by the
#       seam, which looks the person up first, and modelled anyway so a seam
#       that stopped looking is a red rather than a quiet 404.


def _reset_requests_route(
    fake: FakeSignInZitadel, user_id: str, body: dict[str, Any]
) -> httpx.Response:
    """The reset write, recorded. Shared by the fakes that own a person."""
    if user_id not in fake.users:
        return fake._signin_refusal(404, "COMMAND-SAF4f", "User could not be found")
    fake.reset_requests.append((user_id, json.dumps(body, sort_keys=True)))
    return httpx.Response(200, json={"details": {}})
