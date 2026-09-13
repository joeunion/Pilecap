"""The only place in this product that speaks to Zitadel's APIs.

Two surfaces, one door. Org-scoped administration is Zitadel's v1 management
API (`MANAGEMENT`); creating a person with no credentials and minting them an
invite code exist only on its v2 user API (`USER`); two instance-wide reads
(`ADMIN`) tell the invitation email how long its link stands and `zitadel_audit`
who this instance's mail comes from. All three are
dialled through the same `_client()` with the same machine PAT, and rule 27
fences the module rather than any one prefix — which is what keeps "one door"
true while Zitadel is mid-migration between its own versions.

**The console is a window, not a door** (ADR ident-2). Identity configuration —
which project exists, which application a browser signs in through, which
external IdP a customer's people arrive from — is written through our audited
services, onto our rows, and *materialised* here. The row is the intent; Zitadel
is the materialisation. Nothing else in the tree may reach the management API,
and house rule 27 is the closed half of that: no module outside this one names
`ZITADEL_PAT` or builds a management client, and only an activity or a
management command may import this module at all.

Why that shape, in one paragraph. A management call is external I/O with a
credential attached: it can hang, it can 429, it can half-succeed. Put it inside
a service's transaction and a Zitadel hiccup rolls back a legitimate row (C2);
spread the client across four modules and there is no longer one place that
knows the PAT is a secret. So the credential is read here, the timeout is set
here, and the retrying is done by the Temporal activity that calls these
functions — which is where a retry is a durable fact instead of a `for` loop.

**Every `ensure_*` is idempotent by search-then-create**, because that is what an
activity needs: Temporal guarantees at-least-once, so the second run of the same
input has to produce the same object rather than a second one. Each returns a
`Resource` saying which id it settled on and whether this call is what made it —
`created` is for the seed command's output and for the tests, never for control
flow that would differ between the first run and the second.

Nothing here writes to a model, reads a model, or knows what a tenant is. It is
a client: it takes strings and returns strings, and the deciding happens in the
activity and the services above it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import httpx
from django.conf import settings

from apps.core.log import get_logger

log = get_logger(__name__)

# Seconds. A management call is a small JSON round trip to a service on the same
# network; ten seconds is generous and a hung one is a worker thread that never
# comes back. Overridable by environment because "how long is too long" is a
# property of the deployment.
DEFAULT_TIMEOUT = 10.0

# Zitadel's search vocabulary. Named once so a typo is an import error rather
# than a search that quietly matches nothing — and a search that matches nothing
# is `ensure_*` creating a duplicate on every run.
EQUALS = "TEXT_QUERY_METHOD_EQUALS"

# The management API's version prefix. v1 is the surface Zitadel v4 still serves
# for org-scoped administration; the pin in `compose.yaml` is what guards us
# against it moving under our feet.
MANAGEMENT = "/management/v1"

# The **user** API's version prefix, and the second surface this module speaks.
# Zitadel is mid-migration: org-scoped administration is still v1 under
# `/management/v1`, and the person-shaped operations needed here — creating
# a human with no credentials, and minting an invite code — exist only on v2.
# Both are reached with the same machine PAT through the same `_client()`, which
# is what keeps rule 27's "one door" true across the split.
#
# MEASURED against the pinned build (v4.17.1), not read off a doc page:
# `/v2/users/{id}/invite_code` answers 400 "User could not be found" for an id
# that does not exist — parse and authorization both reached — while the
# `/v2beta/` spelling of the same path 404s. v2beta is therefore not routed
# here, and this constant is the one that is.
USER = "/v2"

# The instance-wide administration prefix. Two reads, both of them reads:
# `invite_code_lifetime`, because the number in the invitation email has to be
# Zitadel's number rather than ours, and `smtp_configuration`, because who this
# instance's mail comes from is instance-wide and no row of ours claims it.
ADMIN = "/admin/v1"

# Zitadel's id for "this person has already set credentials, so there is nothing
# to invite them to set" — the answer `CreateInviteCode` gives for a user who is
# already initialized. It is a **normal** outcome, not a failure: somebody who
# already signs in to this deployment being invited into a second tenant is the
# ordinary case, and the invitation email for them says "sign in", not "set a
# password". Matched on the stable error id rather than the prose, because the
# prose is a translated string.
ALREADY_INITIALIZED = "COMMAND-EF34g"

# Where the pinned build serves the credential-setting page, MEASURED BY
# FETCHING IT: a GET of
# `<issuer>/ui/login/user/invite?userID=<id>&code=<code>` answers 200 with the
# "Activate User" form — a `code` field pre-filled from the query string, and
# `password`/`passwordconfirm` beside it. The v2 login UI (`/ui/v2/login/...`)
# 404s on this build, so this is the shape, and it is written down here rather
# than in the email template because a template is not where a measured fact
# about somebody else's product belongs.
INVITE_PATH = "/ui/login/user/invite"


class ZitadelError(RuntimeError):
    """The management API could not be reached, or refused.

    A plain `RuntimeError` subclass and deliberately **not** a
    `core.exceptions.DomainError`: nothing here is a refusal aimed at a person.
    It is infrastructure failing, it happens inside an activity, and what should
    happen next is a Temporal retry — not a 4xx composed for a client who never
    asked for a Zitadel call in the first place.
    """


class ZitadelNotConfigured(ZitadelError):
    """No issuer or no PAT. Raised before anything is dialled.

    Separate from `ZitadelError` because the two want opposite handling: a
    transport failure is retried, and a deployment with no credential will fail
    identically forever. `zitadel_seed` and `zitadel_audit` catch this one and
    print the sentence that fixes it.
    """


@dataclass(frozen=True)
class Resource:
    """What an `ensure_*` settled on: the id, and whether this call made it.

    `detail` carries whatever else the API said that the caller may need — a
    client id and secret for a freshly created application, the stored issuer
    for an IdP — and it is empty rather than absent when the object was already
    there, because **Zitadel never shows a client secret twice**. A seed run that
    printed one on the first run and nothing on the second is telling the truth.
    """

    id: str
    created: bool
    detail: Mapping[str, Any] = field(default_factory=dict)


def configured() -> bool:
    """Whether this deployment has an issuer and a credential to use it with."""
    return bool(_issuer()) and bool(_token())


def _issuer() -> str:
    return str(getattr(settings, "ZITADEL_ISSUER", "") or "").strip().rstrip("/")


def _token() -> str:
    # The one read of the credential in this repository. Rule 27's first half is
    # exactly this line being the only one.
    return str(getattr(settings, "ZITADEL_PAT", "") or "").strip()


@contextmanager
def _client() -> Iterator[httpx.Client]:
    """A client bound to this deployment's Zitadel, with the PAT attached.

    Private, and rule 27 keeps it that way: a caller that could build its own
    client could set its own timeout, log its own headers and skip everything
    below. The retry policy is deliberately **not** here — it belongs to the
    Temporal activity that calls these functions, where a retry is durable and
    visible instead of a loop nobody can see from outside the process.
    """
    issuer = _issuer()
    token = _token()
    if not issuer or not token:
        raise ZitadelNotConfigured(
            "Zitadel is not configured for this deployment: ZITADEL_ISSUER and "
            "ZITADEL_PAT must both be set. ./scripts/setup.sh writes the PAT into "
            ".env from the zitadel_bootstrap volume."
        )
    timeout = float(getattr(settings, "ZITADEL_MANAGEMENT_TIMEOUT", DEFAULT_TIMEOUT))
    with httpx.Client(
        base_url=issuer,
        timeout=httpx.Timeout(timeout),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "pilecap-accounts/zitadel",
        },
        follow_redirects=False,
    ) as client:
        yield client


def _call(
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    prefix: str = MANAGEMENT,
) -> dict[str, Any]:
    """One call to Zitadel. Raises `ZitadelError` on anything but a 2xx.

    The response body is included in the message because Zitadel's errors are
    specific and useful (`"Errors.Project.AlreadyExists"`), and an activity that
    failed with "400" and nothing else is an activity nobody can debug from the
    Temporal UI. **The request body is not**, because it can carry a client
    secret — or an invite code.

    `prefix` is which of Zitadel's surfaces this call is on, and it defaults to
    the management one so every existing caller reads exactly as it did. It is a
    parameter rather than a second `_call_v2` because the credential, the
    timeout, the error shape and the "never log the request body" rule are the
    same on both surfaces: a second copy of this function is a second place for
    one of those four to drift.
    """
    with _client() as client:
        try:
            response = client.request(method, f"{prefix}{path}", json=dict(payload or {}))
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel {method} {prefix}{path} failed: {error}") from error
    if response.status_code >= 400:
        raise ZitadelError(
            f"Zitadel {method} {prefix}{path} answered "
            f"{response.status_code}: {response.text[:400]}"
        )
    if not response.content:
        return {}
    try:
        body = response.json()
    except ValueError as error:  # pragma: no cover - a management API that stopped being JSON
        raise ZitadelError(f"Zitadel {method} {prefix}{path} answered unparseable JSON") from error
    return dict(body) if isinstance(body, dict) else {"result": body}


def _search(
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    prefix: str = MANAGEMENT,
) -> list[dict[str, Any]]:
    """A `_search` call's result list, which Zitadel omits entirely when empty."""
    body = _call("POST", path, payload, prefix=prefix)
    result = body.get("result") or []
    return [row for row in result if isinstance(row, dict)]


def _name_query(name: str) -> dict[str, Any]:
    return {"nameQuery": {"name": name, "method": EQUALS}}


# --- reads -------------------------------------------------------------------
#
# The half `zitadel_audit` is built out of. Every one of these is a GET or a
# `_search`, so the audit command cannot change anything even if it wanted to —
# which is the property the criterion pins, not a promise in a docstring.


def organization() -> dict[str, Any]:
    """The org the machine credential belongs to. The audit report's header."""
    return dict(_call("GET", "/orgs/me").get("org") or {})


def organizations() -> list[dict[str, Any]]:
    """Every organisation on this INSTANCE. Counted by the audit, never written.

    `organization()` above is the one the credential belongs to — the org this
    deployment's seed owns and the only one anything here writes. This is the
    whole instance's list, and it exists so that a second organisation is at
    least VISIBLE: the audit's declared blind spot used to read "still
    invisible: a second organisation", and a surface nobody can even count is a
    surface nobody notices being added.

    MEASURED on the pinned build: `POST /admin/v1/orgs/_search` with an empty
    body answers `200` with `details.totalResult` and a `result` list of orgs
    carrying `id`, `name`, `state` and `primaryDomain`.

    **Its own page bound is a declared limit, not a hidden one.** `_search`
    returns the rows Zitadel put on the page it chose, so on an instance with
    more organisations than that page holds this list is short. That is
    acceptable for the one thing it is for — *is there more than one?* — and it
    is why the audit prints the count as an observation and reaches no verdict
    on it. An instance whose org count is a number anybody depends on wants a
    paging read, and that is the trigger for writing one.
    """
    return _search("/orgs/_search", {}, prefix=ADMIN)


def projects() -> list[dict[str, Any]]:
    """Every project in the credential's org."""
    return _search("/projects/_search", {})


def find_project(*, name: str) -> dict[str, Any] | None:
    for row in _search("/projects/_search", {"queries": [_name_query(name)]}):
        if str(row.get("name", "")) == name:
            return row
    return None


def applications(*, project_id: str) -> list[dict[str, Any]]:
    """Every application on a project — the browser RP, the MCP resource, …"""
    return _search(f"/projects/{project_id}/apps/_search", {})


def find_application(*, project_id: str, name: str) -> dict[str, Any] | None:
    for row in applications(project_id=project_id):
        if str(row.get("name", "")) == name:
            return row
    return None


def identity_providers() -> list[dict[str, Any]]:
    """Every org-level external IdP. The audit's comparison set for SSO rows.

    **`/idps/templates/`, not `/idps/`.** Zitadel still serves the older
    `/idps/_search`, and it answers `200` with an empty body — it lists the
    legacy IdP configurations, and a generic-OIDC provider created through
    `/idps/generic_oidc` is not one. Reading the wrong endpoint here is
    indistinguishable from "there are none", which would make `ensure_*` create
    a second provider on every run and the drift report call every row clean.
    Measured against the pinned image, not guessed.
    """
    return _search("/idps/templates/_search", {})


def find_identity_provider(*, name: str) -> dict[str, Any] | None:
    for row in identity_providers():
        if str(row.get("name", "")) == name:
            return row
    return None


def get_identity_provider(*, idp_id: str) -> dict[str, Any] | None:
    """One IdP by the id our row recorded, or `None` when it is gone.

    `None` rather than an exception on a 404 is what makes the audit able to
    report "our row names an IdP that no longer exists" as a drift line instead
    of dying in the middle of the report.
    """
    try:
        return dict(_call("GET", f"/idps/templates/{idp_id}").get("idp") or {})
    except ZitadelError:
        return None


def oidc_issuer_of(provider: Mapping[str, Any]) -> str:
    """The issuer inside an IdP template, normalised the way our rows store it.

    One function because the shape is two levels deep (`config.oidc.issuer`) and
    a reader that guessed one level would compare `""` against every row — which
    is a drift report that is silent for the wrong reason.
    """
    config = provider.get("config") or {}
    oidc = config.get("oidc") or {} if isinstance(config, Mapping) else {}
    return str(oidc.get("issuer", "") if isinstance(oidc, Mapping) else "").strip().rstrip("/")


def google_client_id_of(provider: Mapping[str, Any]) -> str:
    """The Google client id inside an IdP template, or `""`.

    `oidc_issuer_of`'s sibling, and it exists for the same reason: the shape is
    two levels deep (`config.google.clientId`) and a reader that guessed one
    level would compare `""` against everything, which is a drift report that
    is silent for the wrong reason. It is what lets `zitadel_audit` see a
    workforce door somebody re-pointed at a different Google project in the
    console — the one console change that would let strangers in and that our
    own rows say nothing about.
    """
    config = provider.get("config") or {}
    google = config.get("google") or {} if isinstance(config, Mapping) else {}
    return str(google.get("clientId", "") if isinstance(google, Mapping) else "").strip()


# --- the console's own surfaces: observed, never judged ----------------------
#
# Everything above this line has a row behind it: a `SsoConnection` names an IdP,
# the environment names the workforce door. These two have neither. They are
# configuration **no product on this instance manages through services** — which
# is precisely why rule 27's declared blind spot covered them completely, and why
# `zitadel_audit` reads them and prints them rather than comparing them.
#
# There is no intent to compare against, so there is no verdict to reach: a
# drift verdict here would need an intent row, and inventing one is rule 27's
# full materialisation machinery for a surface nothing writes (ADR ident-2's
# amendment names the trigger that would change that). Both are GETs, so the
# change-nothing property the audit already holds extends to them unchanged.


def login_policy() -> dict[str, Any]:
    """The login policy in force for the credential's **org**, or `{}`.

    MEASURED against the pinned build, not read off a doc page:
    `GET /management/v1/policies/login` answers `200` with the policy under a
    `policy` key, and the interesting field is one Zitadel only *sometimes*
    sends. When the org has no policy of its own the body carries
    `isDefault: true` and a `details.resourceOwner` that is the **instance**;
    when somebody has set an org policy the flag is **absent** and the
    `resourceOwner` is the org. So "did anybody change this org's login policy"
    is answerable from this one read, and `zitadel_audit` says which of the two
    it is rather than dumping the object.

    Not `None` on failure like `get_identity_provider`: this read has no row
    behind it, so there is no line the audit would otherwise print. The caller
    catches `ZitadelError` and says it could not look — which is a different
    sentence from "the policy is empty", and the difference matters to whoever
    reads a clean report.
    """
    return dict(_call("GET", "/policies/login").get("policy") or {})


def label_policy() -> dict[str, Any]:
    """The org's label policy, or `{}` — **and whether it is the org's own**.

    MEASURED against the pinned build by a read-only probe, not read off a doc
    page: `GET /management/v1/policies/label` answers `200` with the policy
    under a `policy` key, and — exactly like `login_policy` above — the
    interesting field is one Zitadel only *sometimes* sends. When the org has no
    policy of its own the body carries a TOP-LEVEL `isDefault: true`; when
    somebody has set one the key is absent and `details.resourceOwner` is the
    org. The flag is returned alongside the policy rather than folded into it,
    because "the org has never been branded" and "the org is branded to look
    like the default" are different facts and the audit says which.

    The colour keys are Zitadel's own — `primaryColor`, `backgroundColor`,
    `fontColor`, each with a `*Dark` twin — plus `disableWatermark`,
    `hideLoginNameSuffix` and `themeMode`. **Booleans are absent when false**
    (proto3 omits its zero values), which is measured and is why the audit
    compares with `.get(..., False)` and never on presence.

    `/policies/label/_active` is NOT this endpoint's sibling on this build: it
    answers 404, measured. The GET above returns the live policy directly.
    """
    body = _call("GET", "/policies/label")
    policy = dict(body.get("policy") or {})
    if body.get("isDefault") is not None:
        # Lifted out of the envelope so one return value carries both facts.
        policy["_isInstanceDefault"] = bool(body.get("isDefault"))
    return policy


def smtp_configuration() -> dict[str, Any]:
    """The **instance's** active SMTP sender, or `{}`.

    Instance-wide (`ADMIN`), not org-scoped: on a shared development instance
    the sender belongs to whoever configured it last, which is exactly the fact
    worth printing.

    MEASURED against the pinned build: `GET /admin/v1/smtp` answers `200` with
    the config under `smtpConfig`, carrying `senderAddress`, `senderName`,
    `host`, `state`, `description` and `id`. **It does not return the SMTP
    password**, which is what makes this safe to print at all — the report says
    who the mail comes from, never the credential it is sent with. There is a
    `POST /admin/v1/smtp/_search` that answers with the same rows in a list; the
    GET is used because one active configuration is what a reader needs and a
    `_search` would invite a report that ranks them.
    """
    return dict(_call("GET", "/smtp", prefix=ADMIN).get("smtpConfig") or {})


def find_user(*, username: str) -> dict[str, Any] | None:
    rows = _search(
        "/users/_search",
        {"queries": [{"userNameQuery": {"userName": username, "method": EQUALS}}]},
    )
    for row in rows:
        if str(row.get("userName", "")) == username:
            return row
    return None


# --- ensure_*: search, then create ------------------------------------------
#
# Each of these is what an activity calls. The contract is the same one every
# time: **the same input twice leaves one object**, and the second call reports
# `created=False`. Temporal's at-least-once delivery is not an edge case here,
# it is the normal case.


def ensure_project(*, name: str) -> Resource:
    """The project every application in this deployment hangs off."""
    existing = find_project(name=name)
    if existing is not None:
        return Resource(id=str(existing["id"]), created=False)
    body = _call("POST", "/projects", {"name": name})
    log.info("accounts.zitadel.project_created", project_name=name)
    return Resource(id=str(body.get("id", "")), created=True)


def ensure_web_application(
    *,
    project_id: str,
    name: str,
    redirect_uris: list[str],
    post_logout_uris: list[str],
    dev_mode: bool = False,
) -> Resource:
    """The browser RP: the confidential OIDC client W2-R3's login flow uses.

    `authMethodType` is BASIC — a web application keeps a secret because it has
    a server to keep it on. The native client below is the opposite case and
    says so.
    """
    existing = find_application(project_id=project_id, name=name)
    if existing is not None:
        return Resource(
            id=str(existing["id"]),
            created=False,
            detail={"clientId": str((existing.get("oidcConfig") or {}).get("clientId", ""))},
        )
    body = _call(
        "POST",
        f"/projects/{project_id}/apps/oidc",
        {
            "name": name,
            "redirectUris": redirect_uris,
            "postLogoutRedirectUris": post_logout_uris,
            "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
            "grantTypes": [
                "OIDC_GRANT_TYPE_AUTHORIZATION_CODE",
                "OIDC_GRANT_TYPE_REFRESH_TOKEN",
            ],
            "appType": "OIDC_APP_TYPE_WEB",
            "authMethodType": "OIDC_AUTH_METHOD_TYPE_BASIC",
            "version": "OIDC_VERSION_1_0",
            "devMode": dev_mode,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
            "accessTokenRoleAssertion": True,
            "idTokenRoleAssertion": True,
            "idTokenUserinfoAssertion": True,
        },
    )
    log.info("accounts.zitadel.application_created", application_name=name, kind="web")
    return Resource(
        id=str(body.get("appId", "")),
        created=True,
        detail={
            "clientId": str(body.get("clientId", "")),
            "clientSecret": str(body.get("clientSecret", "")),
        },
    )


def ensure_native_application(
    *,
    project_id: str,
    name: str,
    redirect_uris: list[str],
    dev_mode: bool = False,
) -> Resource:
    """The pre-registered public client third-party MCP callers use.

    The **DCR hedge** (ADR ident-3, shop-the-price): dynamic client registration
    is not built this cycle, and a client that cannot register itself needs one
    that already exists. `OIDC_AUTH_METHOD_TYPE_NONE` plus PKCE, because a
    client running on somebody else's laptop cannot keep a secret and pretending
    otherwise is how the secret ends up in a public repository.
    """
    existing = find_application(project_id=project_id, name=name)
    if existing is not None:
        return Resource(
            id=str(existing["id"]),
            created=False,
            detail={"clientId": str((existing.get("oidcConfig") or {}).get("clientId", ""))},
        )
    body = _call(
        "POST",
        f"/projects/{project_id}/apps/oidc",
        {
            "name": name,
            "redirectUris": redirect_uris,
            "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
            "grantTypes": [
                "OIDC_GRANT_TYPE_AUTHORIZATION_CODE",
                "OIDC_GRANT_TYPE_REFRESH_TOKEN",
            ],
            "appType": "OIDC_APP_TYPE_NATIVE",
            "authMethodType": "OIDC_AUTH_METHOD_TYPE_NONE",
            "version": "OIDC_VERSION_1_0",
            "devMode": dev_mode,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
            "accessTokenRoleAssertion": True,
        },
    )
    log.info("accounts.zitadel.application_created", application_name=name, kind="native")
    return Resource(
        id=str(body.get("appId", "")),
        created=True,
        detail={"clientId": str(body.get("clientId", ""))},
    )


def ensure_api_application(*, project_id: str, name: str) -> Resource:
    """The MCP resource: what an access token's `aud` has to name.

    An API application rather than a second OIDC client, because this object is
    not something anybody logs in *through* — it is the resource server W2-R4
    validates audiences against.
    """
    existing = find_application(project_id=project_id, name=name)
    if existing is not None:
        return Resource(
            id=str(existing["id"]),
            created=False,
            detail={"clientId": str((existing.get("apiConfig") or {}).get("clientId", ""))},
        )
    body = _call(
        "POST",
        f"/projects/{project_id}/apps/api",
        {"name": name, "authMethodType": "API_AUTH_METHOD_TYPE_BASIC"},
    )
    log.info("accounts.zitadel.application_created", application_name=name, kind="api")
    return Resource(
        id=str(body.get("appId", "")),
        created=True,
        detail={
            "clientId": str(body.get("clientId", "")),
            "clientSecret": str(body.get("clientSecret", "")),
        },
    )


def ensure_human_user(
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
) -> Resource:
    """A person who can sign in. Used by `zitadel_seed` for the dev user only.

    Real people arrive through the RP flow and are provisioned by
    `provision_sso_identity`; this exists so `./scripts/setup.sh` leaves a
    laptop with something to log in *as*.
    """
    existing = find_user(username=username)
    if existing is not None:
        return Resource(id=str(existing["id"]), created=False)
    body = _call(
        "POST",
        "/users/human/_import",
        {
            "userName": username,
            "profile": {"firstName": first_name, "lastName": last_name},
            "email": {"email": email, "isEmailVerified": True},
            "password": password,
            "passwordChangeRequired": False,
        },
    )
    log.info("accounts.zitadel.user_created", user_name=username)
    return Resource(id=str(body.get("userId", "")), created=True)


def ensure_invited_user(*, email: str, first_name: str, last_name: str) -> Resource:
    """A person who exists and **cannot yet sign in**. The invitation's first half.

    The difference from `ensure_human_user` above is the whole point: that one
    takes a password, because it is making the dev account `./scripts/setup.sh`
    leaves you to log in as. This one takes none, and there is no
    `passwordChangeRequired` to set either — the account is deliberately
    credential-less until the invited person sets their own through
    `invite_url()`. **We never see, choose or transport their password**, which
    is what makes this different in kind from mailing somebody a temporary one.

    Idempotent by search-then-create like every `ensure_*`, and the search is
    the *same* `find_user` the v1 half uses: v1 and v2 are two APIs over one
    user store, so a person created here is found by the search there. The
    second call with the same email reports `created=False` and makes nothing —
    which is what an at-least-once activity needs.

    The email is marked verified. Zitadel would otherwise want to verify it
    itself, by sending its own mail, and rule 25 says the product has exactly
    one sender: the address is already proven as well as it is going to be — an
    invitation is somebody who *has* the address being told about it by
    somebody who typed it, and the invite code lands in that inbox regardless.
    """
    existing = find_user(username=email)
    if existing is not None:
        return Resource(id=str(existing["id"]), created=False)
    body = _call(
        "POST",
        "/users/human",
        {
            "username": email,
            "profile": {"givenName": first_name, "familyName": last_name},
            "email": {"email": email, "isVerified": True},
        },
        prefix=USER,
    )
    log.info("accounts.zitadel.invited_user_created", user_name=email)
    return Resource(id=str(body.get("userId", "")), created=True)


def create_invite_code(*, user_id: str) -> str:
    """Mint the code that lets one person set their own credentials. **Returns it.**

    `returnCode` rather than `sendCode`, and that choice is rule 25 rather than
    a preference: `sendCode` has Zitadel send its own email, which would be a
    second sender in the product — one that knows nothing about consent, quiet
    hours or suppression, and whose wording no test of ours can read. Zitadel
    hands the code to us; `comms`/`core.mail` delivers it.

    **The code is in the return value and nowhere else.** It is not logged, not
    put on a row, and not in the `log.info` below — which names the user id and
    nothing more, because a credential in a log line is a credential in every
    log sink the deployment forwards to. `apps/accounts/tests/` pins that.

    **Not idempotent, and it must not pretend to be.** Measured on the pinned
    build: a second call mints a *second* code and supersedes the first. That is
    Zitadel's design — a code is single-use — so the idempotency this flow needs
    lives one level up, in the deterministic workflow id that stops a retried
    `invite_member` from starting a second run at all.

    Raises `ZitadelError` with `ALREADY_INITIALIZED` in the message when the
    person already set credentials. The caller decides what that means; see
    `is_already_initialized`.
    """
    body = _call("POST", f"/users/{user_id}/invite_code", {"returnCode": {}}, prefix=USER)
    code = str(body.get("inviteCode", ""))
    if not code:
        raise ZitadelError(
            f"Zitadel minted no invite code for user {user_id}: the response carried "
            "no `inviteCode`, which means `returnCode` was not honoured."
        )
    log.info("accounts.zitadel.invite_code_created", zitadel_user_id=user_id)
    return code


def is_already_initialized(error: ZitadelError) -> bool:
    """Whether this refusal is "they already have credentials" rather than a fault.

    Its own predicate beside `_is_already_in_that_state` rather than a fifth
    member of that tuple, because the two mean opposite things to a caller:
    `_ALREADY_STATES` is "you asked for the state it is already in", which is a
    no-op success, and this is "the thing you asked for does not apply to this
    person", which changes what the email says.
    """
    return ALREADY_INITIALIZED in str(error)


def invite_url(*, user_id: str, code: str) -> str:
    """The page where an invited person sets their password. **The email's link.**

    Built here rather than in the template or the activity because it is a fact
    about Zitadel's own front end, and this module is the only one allowed to
    know facts about Zitadel. `INVITE_PATH` above records how it was measured.

    Both values are percent-encoded. Neither can contain a delimiter today — an
    id is digits and a code is six uppercase alphanumerics — and that is exactly
    why encoding costs nothing and is worth having when one of them changes
    shape.
    """
    return (
        f"{_issuer()}{INVITE_PATH}"
        f"?userID={quote(str(user_id), safe='')}&code={quote(str(code), safe='')}"
    )


def invite_code_lifetime() -> timedelta | None:
    """How long an invite code stands, **according to Zitadel**. `None` if unreadable.

    The invitation email states a deadline, and the deadline that matters to the
    person reading it belongs to the code, not to our row. Asking Zitadel is
    what makes that number one truth instead of a constant here that drifts the
    first time an operator changes the instance's secret generator.

    Measured on the pinned build: `SECRET_GENERATOR_TYPE_INVITE_CODE` carries
    `expiry: "259200s"` — three days — and a length of six.

    `None` rather than a guess when the read fails or the generator is absent:
    the template drops the sentence rather than printing a number nobody
    checked. An email that states the wrong deadline is worse than one that
    states none.
    """
    try:
        rows = _search("/secretgenerators/_search", {}, prefix=ADMIN)
    except ZitadelError:
        return None
    for row in rows:
        if str(row.get("generatorType", "")) != "SECRET_GENERATOR_TYPE_INVITE_CODE":
            continue
        raw = str(row.get("expiry", "")).strip()
        # Zitadel serialises a protobuf Duration as seconds with a trailing `s`.
        if not raw.endswith("s"):
            return None
        try:
            return timedelta(seconds=float(raw[:-1]))
        except ValueError:
            return None
    return None


#: **The generic-OIDC provider's FULL field set**, read out of the
#: API the pinned build serves: `ManagementServiceUpdateGenericOIDCProviderBody`
#: in `/openapi/v2/swagger/v2/zitadel/zitadel/management.swagger.json` on
#: ghcr.io/zitadel/zitadel:v4.17.1. `usePkce` is the eighth, and it was the one
#: this writer omitted — so every sync sent `usePkce=false` by omission and
#: silently switched off a PKCE somebody had enabled in the console.
OIDC_IDENTITY_PROVIDER_FIELDS = frozenset(
    {
        "name",
        "issuer",
        "clientId",
        "clientSecret",
        "scopes",
        "providerOptions",
        "isIdTokenMapping",
        "usePkce",
    }
)

#: **The Google provider's FULL field set**, from the same document
#: (`ManagementServiceUpdateGoogleProviderBody`). Five fields, and the writer
#: below already sent all five — "the Google writer is clean" CONFIRMED
#: against the API rather than taken on trust. Declared anyway, because the
#: census in `apps/accounts/tests/test_zitadel_full_body.py` is a closed
#: question over a declared population: a writer with no declaration is a
#: writer the census cannot judge.
GOOGLE_IDENTITY_PROVIDER_FIELDS = frozenset(
    {
        "name",
        "clientId",
        "clientSecret",
        "scopes",
        "providerOptions",
    }
)


def ensure_oidc_identity_provider(
    *,
    name: str,
    issuer: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
    existing_id: str = "",
    use_pkce: bool | None = None,
) -> Resource:
    """A customer's IdP, materialised as an org-level generic OIDC provider.

    This is what `apply_identity_config` drives, and it is the reason the
    activity is idempotent rather than merely retried: `existing_id` is the id
    our own row already recorded, so a retry **updates** the object it made last
    time instead of creating a second provider with the same name. When the row
    carries no id — the first run, or an id Zitadel no longer knows — the search
    by name is the second net.

    `isAutoCreation` is off, deliberately. Zitadel creating its own user rows on
    a first assertion would be an IdP granting something, and JIT provisioning in
    this product is `provision_sso_identity`'s job, with its three refusals
    (`apps/accounts/services.py`).

    **`use_pkce` is `None` by default, and that is the fix.** This writer
    used to omit the key entirely, and Zitadel's `PUT` is a REPLACE — so every
    sync sent `usePkce=false` by omission and silently switched off a PKCE
    somebody had enabled in the console, on a customer's own IdP, with nothing
    anywhere saying so. `None` means "we have no opinion": the live provider's
    own value is read back and sent, so a re-sync preserves the console's
    setting instead of overwriting it, and a caller with an opinion passes a
    bool. `False` on the create branch, because a provider that does not exist
    yet has no setting to preserve and that is what Zitadel's own zero value is.
    """
    # Our row's id, then the search by name — `_settled_target` holds both nets
    # so this and the Google template below cannot drift apart. A row naming an
    # IdP somebody deleted in the console falls through to create, which is the
    # repair a re-sync is for; `zitadel_audit` is what makes it visible before
    # then.
    target = _settled_target(name=name, existing_id=existing_id)
    settled_pkce = use_pkce
    if settled_pkce is None:
        live = get_identity_provider(idp_id=target) if target else None
        oidc = ((live or {}).get("config") or {}).get("oidc") or {}
        settled_pkce = bool(oidc.get("usePkce", False)) if isinstance(oidc, Mapping) else False
    payload: dict[str, Any] = {
        "name": name,
        "issuer": issuer,
        "clientId": client_id,
        "clientSecret": client_secret,
        "scopes": scopes or ["openid", "profile", "email"],
        "isIdTokenMapping": False,
        "usePkce": settled_pkce,
        "providerOptions": {
            "isLinkingAllowed": True,
            "isCreationAllowed": True,
            "isAutoCreation": False,
            "isAutoUpdate": False,
            "autoLinking": "AUTO_LINKING_OPTION_UNSPECIFIED",
        },
    }
    if target:
        _call("PUT", f"/idps/generic_oidc/{target}", payload)
        log.info("accounts.zitadel.idp_updated", idp_name=name)
        return Resource(id=target, created=False)
    body = _call("POST", "/idps/generic_oidc", payload)
    log.info("accounts.zitadel.idp_created", idp_name=name)
    return Resource(id=str(body.get("id", "")), created=True)


def ensure_google_identity_provider(
    *,
    name: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
    existing_id: str = "",
) -> Resource:
    """The workforce door, materialised as an org-level Google provider.

    **This is the same shape a customer's IdP gets, and that is the point of
    W2-R5**: the people who build this product and the people who buy it now
    arrive through one identity platform, configured one way, from our side.
    Google is its own template in Zitadel rather than a generic OIDC provider
    because Zitadel's Google template already knows the issuer, the endpoints
    and the claim names — writing them out by hand would be three strings that
    can drift from Google's.

    **The domain restriction is not sent here, and that is deliberate**
    (ADR ident-6): `GOOGLE_WORKSPACE_DOMAINS` stays ours, enforced by
    `accounts.selectors.is_workforce_email` at the moment an assertion arrives.
    A `hd` hint in an authorize URL is a suggestion to Google, not a promise to
    us, and a restriction expressed only in somebody else's console is a
    restriction we cannot test.

    Idempotent by the same two nets as `ensure_oidc_identity_provider`: the id
    the caller recorded, then the search by name.
    """
    payload: dict[str, Any] = {
        "name": name,
        "clientId": client_id,
        "clientSecret": client_secret,
        "scopes": scopes or ["openid", "profile", "email"],
        "providerOptions": {
            "isLinkingAllowed": True,
            "isCreationAllowed": True,
            "isAutoCreation": False,
            "isAutoUpdate": False,
            "autoLinking": "AUTO_LINKING_OPTION_UNSPECIFIED",
        },
    }
    target = _settled_target(name=name, existing_id=existing_id)
    if target:
        _call("PUT", f"/idps/google/{target}", payload)
        log.info("accounts.zitadel.idp_updated", idp_name=name, kind="google")
        return Resource(id=target, created=False)
    body = _call("POST", "/idps/google", payload)
    log.info("accounts.zitadel.idp_created", idp_name=name, kind="google")
    return Resource(id=str(body.get("id", "")), created=True)


#: **The label policy's FULL field set**, read out of the API the
#: pinned build serves rather than recalled: `v1UpdateCustomLabelPolicyRequest`
#: in `/openapi/v2/swagger/v2/zitadel/zitadel/management.swagger.json` on
#: ghcr.io/zitadel/zitadel:v4.17.1, whose `properties` are exactly the eleven
#: below. This writer used to send the five colours it had a column for plus
#: `disableWatermark`, and Zitadel's PUT is a REPLACE: the five it omitted were
#: zeroed on every branding sync, invisibly, because the no-op check and
#: `zitadel_audit` both read only the keys we sent.
LABEL_POLICY_FIELDS = frozenset(
    {
        "primaryColor",
        "primaryColorDark",
        "backgroundColor",
        "backgroundColorDark",
        "warnColor",
        "warnColorDark",
        "fontColor",
        "fontColorDark",
        "hideLoginNameSuffix",
        "disableWatermark",
        "themeMode",
    }
)

#: What an absent key means on the label policy, so a merge over a live GET can
#: fill a field the answer omitted. Proto3 omits its zero values, so an absent
#: boolean is `False`; an absent colour is the empty string, which Zitadel
#: renders as "no opinion"; `themeMode`'s zero value is its own first enum
#: member. Same shape as `LOGIN_POLICY_ABSENT` below, and for the same reason:
#: the field set is derived from this map so the two cannot drift.
LABEL_POLICY_ABSENT: dict[str, Any] = {
    "primaryColor": "",
    "primaryColorDark": "",
    "backgroundColor": "",
    "backgroundColorDark": "",
    "warnColor": "",
    "warnColorDark": "",
    "fontColor": "",
    "fontColorDark": "",
    "hideLoginNameSuffix": False,
    "disableWatermark": False,
    # `v1ThemeMode`'s zero value, read off the same document: the enum is
    # UNSPECIFIED / AUTO / DARK / LIGHT with `"default": "THEME_MODE_UNSPECIFIED"`.
    # A live policy on this build answers `THEME_MODE_AUTO`, so this default is
    # reached only when Zitadel omitted the key entirely.
    "themeMode": "THEME_MODE_UNSPECIFIED",
}


#: Our column names on the left, Zitadel's on the right. The translation lives
#: HERE and nowhere else, for the reason every other name Zitadel uses is
#: translated at this edge: `models.py` stays in our vocabulary, and the day
#: Zitadel renames a key exactly one file changes.
LABEL_POLICY_COLORS = {
    "accent": "primaryColor",
    "background_color": "backgroundColor",
    "font_color": "fontColor",
    "background_color_dark": "backgroundColorDark",
    "font_color_dark": "fontColorDark",
}


def ensure_label_policy(
    *,
    accent: str,
    background_color: str = "",
    font_color: str = "",
    background_color_dark: str = "",
    font_color_dark: str = "",
    is_watermark_disabled: bool = False,
) -> Resource:
    """The hosted sign-in screen's look, made to agree with our intent row.

    The ninth `ensure_*`, and the same contract as the other eight: **the same
    input twice leaves one object**, and the second call reports
    `created=False`. What is different is that a LabelPolicy is a SINGLETON on
    the org rather than a searchable object, so there is no `find_*` to open
    with and no id to return — `Resource.id` carries the org that owns the
    policy, which is the only identifier this surface has.

    THREE MEASURED FACTS, all of them from a read-only probe plus one
    write-and-restore probe against the pinned build, and each one load-bearing:

    * **`PUT` refuses a no-op.** An unchanged update answers `400 Org-8nfSr`,
      "Private Label Policy has not been changed". An `ensure_*` that simply
      PUT every time would therefore *fail on its second call*, which is the
      exact opposite of what Temporal's at-least-once delivery needs. So this
      compares first and writes nothing when the live policy already says what
      we want — the comparison is the idempotence, not a saving.
    * **`POST` creates and `PUT` updates**, and which one applies is decided by
      the top-level `isDefault` the GET carries: present means the org has no
      policy of its own yet.
    * **The draft has to be activated.** `POST /policies/label/_activate`
      publishes it; without that call the values are stored and the login screen
      does not change, which is the failure mode that looks exactly like
      success. The sequence bumps on activation, measured.

    **And a fourth, learned the expensive way: the `PUT` is a REPLACE.** This
    writer used to build its body out of the five colours it had a column for
    plus `disableWatermark` — six of the resource's eleven keys — so
    `hideLoginNameSuffix`, `themeMode`, `warnColor`, `warnColorDark` and
    `primaryColorDark` were zeroed on every branding sync, invisibly: the no-op
    check above and `zitadel_audit` both read only the keys we sent. So the
    intent is now merged over the live GET and the WHOLE of
    `LABEL_POLICY_FIELDS` goes in one body. `apps/accounts/tests/
    test_zitadel_full_body.py` is the census that keeps it that way.

    Colours are passed through as given. Validating a hex string here would be a
    second opinion about a value `config/settings/base.py` and the entrance
    templatetag already validate, and two validators disagreeing is worse than
    one.
    """
    ours: dict[str, str] = {
        "accent": accent,
        "background_color": background_color,
        "font_color": font_color,
        "background_color_dark": background_color_dark,
        "font_color_dark": font_color_dark,
    }
    intent: dict[str, Any] = {
        LABEL_POLICY_COLORS[column]: value for column, value in ours.items() if value
    }
    intent["disableWatermark"] = bool(is_watermark_disabled)

    live = label_policy()
    is_instance_default = bool(live.pop("_isInstanceDefault", False))
    # **The full body, merged over the live one.** Booleans are
    # ABSENT when false on this API (proto3 omits zero values), so every read
    # goes through `.get` with the declared absent-value and never through key
    # presence; `LABEL_POLICY_ABSENT` is what an omitted key means, and its own
    # keys ARE `LABEL_POLICY_FIELDS`, so the two cannot drift.
    baseline: dict[str, Any] = {
        key: live.get(key, absent) for key, absent in LABEL_POLICY_ABSENT.items()
    }
    desired: dict[str, Any] = {**baseline, **intent}
    if desired == baseline and not is_instance_default:
        log.info("accounts.zitadel.label_policy_unchanged")
        return Resource(id=str((live.get("details") or {}).get("resourceOwner", "")), created=False)

    if is_instance_default:
        _call("POST", "/policies/label", desired)
        created = True
        log.info("accounts.zitadel.label_policy_created")
    else:
        _call("PUT", "/policies/label", desired)
        created = False
        log.info("accounts.zitadel.label_policy_updated")
    # Publish. A stored-but-unactivated policy is the failure that looks like
    # success, so this is not conditional on anything.
    _call("POST", "/policies/label/_activate", {})
    settled = label_policy()
    return Resource(
        id=str((settled.get("details") or {}).get("resourceOwner", "")),
        created=created,
    )


# --- the deployment's sign-in posture: instance-wide, and now reconciled -----
#
# Three surfaces that used to sit with the login policy and the SMTP sender in
# `zitadel_audit`'s observed-never-judged section, because nothing wrote them
# (ADR ident-2). Something writes them now, and the intent is the ENVIRONMENT
# rather than a row (ADR ident-8): a deployment's sign-in posture is set once
# per deployment by an operator editing `.env`, and no runtime persona changes
# it — the same shape `_apply_workforce_provider` already uses, and the reason
# no model, migration or workflow kind is added here.
#
# The compose `ZITADEL_DEFAULTINSTANCE_*` keys carry the same values and are the
# belt, not the mechanism: `DefaultInstance` applies WHEN THE INSTANCE IS
# CREATED, so on every instance that already exists — this box's, and every
# sibling's — the seed below is the only thing that closes the door.


#: **The login policy's FULL field set**, read out of the API the pinned build
#: serves: `v1UpdateLoginPolicyRequest` (admin) and `v1UpdateCustomLoginPolicyRequest`
#: (management) in the swagger documents at
#: `/openapi/v2/swagger/v2/zitadel/zitadel/` on ghcr.io/zitadel/zitadel:v4.17.1.
#: **The two carry the same seventeen properties**, measured by comparing the
#: two `properties` maps — which is what lets one declaration serve both the
#: instance's policy and an org's own, and what makes `PUT_FIELD_SETS` key on
#: the resource path without its version prefix.
#:
#: The map is what an ABSENT key means, and the field set is derived from its
#: keys so the two cannot drift. Proto3 omits its zero values, so an absent
#: boolean is `False` and an absent Duration is `"0s"` — never `""`, which is
#: not a Duration and which Zitadel refuses. `PASSWORDLESS_TYPE_NOT_ALLOWED` is
#: `v1PasswordlessType`'s declared default in the same document.
#:
#: **Every one of the five lifetimes is a field we do not manage** — the exact
#: class this convention is about. They are here so a body that carries our one
#: also carries them back byte-identical, rather than zeroing a deployment's
#: `passwordCheckLifetime` as a side effect of turning registration off.
LOGIN_POLICY_ABSENT: dict[str, Any] = {
    "allowUsernamePassword": False,
    "allowRegister": False,
    "allowExternalIdp": False,
    "forceMfa": False,
    "forceMfaLocalOnly": False,
    "hidePasswordReset": False,
    "ignoreUnknownUsernames": False,
    "allowDomainDiscovery": False,
    "disableLoginWithEmail": False,
    "disableLoginWithPhone": False,
    "passwordlessType": "PASSWORDLESS_TYPE_NOT_ALLOWED",
    "defaultRedirectUri": "",
    # A protobuf Duration zero value, not a credential; detect-secrets keys on
    # the word in the field name, so the line below is allowlisted.
    "passwordCheckLifetime": "0s",  # pragma: allowlist secret
    "externalLoginCheckLifetime": "0s",
    "mfaInitSkipLifetime": "0s",
    "secondFactorCheckLifetime": "0s",
    "multiFactorCheckLifetime": "0s",
}
LOGIN_POLICY_FIELDS = frozenset(LOGIN_POLICY_ABSENT)


#: **The lockout policy's FULL field set**, from `v1UpdateLockoutPolicyRequest`
#: in the admin swagger document on the same build. Two fields, and only one of
#: them is ours: `maxOtpAttempts` rides along so a deployment that configured it
#: keeps it (see `ensure_lockout_policy`).
LOCKOUT_POLICY_ABSENT: dict[str, Any] = {
    "maxPasswordAttempts": 0,
    "maxOtpAttempts": 0,
}
LOCKOUT_POLICY_FIELDS = frozenset(LOCKOUT_POLICY_ABSENT)


#: **The instance restrictions' FULL field set**, from `v1SetRestrictionsRequest`
#: in the admin swagger document. `allowedLanguages` is the field we do not
#: manage, and it is the reason this writer merges rather than sets: the API's
#: own description of this endpoint is "Undefined values don't change the
#: current restriction. **Zero values remove the current restriction**", so a
#: body carrying only our one opinion would be safe today and would silently
#: drop a language restriction the day somebody set one.
#:
#: The wrapper shape is Zitadel's own: `v1SelectLanguages` is `{"list": [...]}`
#: because, in the document's words, "we have to wrap the languages list into a
#: message so we can serialize empty lists". An empty list means all languages
#: are allowed, which is the state an instance with no restriction is already in.
RESTRICTIONS_ABSENT: dict[str, Any] = {
    "disallowPublicOrgRegistration": False,
    "allowedLanguages": {"list": []},
}
RESTRICTIONS_FIELDS = frozenset(RESTRICTIONS_ABSENT)


def instance_login_policy() -> dict[str, Any]:
    """The **instance's** default login policy, or `{}`.

    `login_policy()` above is the org's (`MANAGEMENT`); this is the instance's
    (`ADMIN`), and the difference is the whole of what the open door turned out
    about on this box. An org that has set a policy of its own is governed by
    it; **every org that has not — which is every org on a fresh instance — is
    governed by this one**, so this is the read that says whether a newly
    created organisation can register its own users.

    MEASURED on the pinned build: `GET /admin/v1/policies/login` answers `200`
    with the policy under a `policy` key, carrying `isDefault: true`, the five
    lifetimes, and `allowRegister` only when it is true (proto3 omits its zero
    values, which is why every read here goes through `.get` with a declared
    default and never through key presence).
    """
    return dict(_call("GET", "/policies/login", prefix=ADMIN).get("policy") or {})


def lockout_policy() -> dict[str, Any]:
    """The instance's lockout policy, or `{}`. **An absent key means 0 attempts.**

    MEASURED on the pinned build: `GET /admin/v1/policies/lockout` on a
    freshly-created instance answers `{"policy": {"details": {...},
    "isDefault": true}}` — **no `maxPasswordAttempts` key at all**, because
    proto3 omits its zero values and the image's own `defaults.yaml` ships
    `MaxPasswordAttempts: 0`. Zero is not "no limit configured yet": it IS the
    configuration, and it means a password may be guessed forever. That is
    the defect, and it reads as an empty object rather than as a number, which is
    exactly why it survived every console glance.

    **The read and the write are not the same path**, also measured: this GET is
    `/admin/v1/policies/lockout` and the update is
    `PUT /admin/v1/policies/password/lockout` (`v1UpdateLockoutPolicyRequest`).
    Both spellings are read out of the admin swagger document the running build
    serves, not recalled.
    """
    return dict(_call("GET", "/policies/lockout", prefix=ADMIN).get("policy") or {})


def restrictions() -> dict[str, Any]:
    """The instance's restrictions, or `{}` — **the public-org-registration door**.

    MEASURED on the pinned build: `GET /admin/v1/restrictions` answers
    `{"details":{}}` on an instance nobody has restricted — no
    `disallowPublicOrgRegistration` key, no `allowedLanguages` — which means
    anybody who can reach the hosted login can create an organisation and its
    first admin, bypassing invitations entirely. The image's own
    `defaults.yaml` says what the flag does: "defines if ZITADEL should expose
    the endpoint /ui/login/register/org. If it is true, the endpoint returns the
    HTTP status 404 on GET requests, and 409 on POST requests."

    Not nested under a `policy` key like the two above: the answer IS the
    resource, with a `details` block beside it.
    """
    return dict(_call("GET", "/restrictions", prefix=ADMIN))


def ensure_login_policy(*, allow_register: bool, prefix: str = ADMIN) -> Resource:
    """Whether this deployment lets people register themselves. **Full body.**

    `prefix` chooses the surface: `ADMIN` (the default) writes the INSTANCE's
    policy, which governs every org that has not set one of its own;
    `MANAGEMENT` writes the credential's own org's, for an org that has. The
    two take the same seventeen-field body on this build, measured, which is why
    this is one function with a parameter rather than two that can drift.

    **Idempotent by comparison, not by the API's forgiveness.** Every field is
    read off the live policy and sent back; only `allowRegister` is ours. When
    the merged body equals the live one, nothing is written and `created` is
    `False` — which is what an at-least-once caller needs, and which is also the
    only way the five lifetimes and `secondFactors` survive a write
    byte-identical.

    **The `PUT` refuses a no-op, MEASURED** — the same shape the label policy's
    does, and the same consequence: an unchanged body answers
    `400 INSTANCE-5M9vdd`, "Default Login Policy has not been changed". So the
    comparison above is not a saving, it IS the idempotence: a writer that `PUT`
    unconditionally would succeed on its first call and fail on its second,
    which is the call `scripts/setup.sh` makes on every run and the call
    Temporal's at-least-once delivery guarantees will happen.
    """
    live = login_policy() if prefix == MANAGEMENT else instance_login_policy()
    baseline: dict[str, Any] = {
        key: live.get(key, absent) for key, absent in LOGIN_POLICY_ABSENT.items()
    }
    desired: dict[str, Any] = {**baseline, "allowRegister": bool(allow_register)}
    owner = str((live.get("details") or {}).get("resourceOwner", ""))
    if desired == baseline:
        log.info("accounts.zitadel.login_policy_unchanged", allow_register=bool(allow_register))
        return Resource(id=owner, created=False)
    _call("PUT", "/policies/login", desired, prefix=prefix)
    log.info("accounts.zitadel.login_policy_updated", allow_register=bool(allow_register))
    return Resource(id=owner, created=True)


def ensure_lockout_policy(
    *, max_password_attempts: int, max_otp_attempts: int | None = None
) -> Resource:
    """How many wrong passwords a person gets before the account locks. **Full body.**

    The instance's policy, which every org without one of its own inherits. Zero
    means unlimited, and zero is the image's shipped default — so a deployment
    that never called this is a deployment where a password may be guessed
    forever.

    **`max_otp_attempts` defaults to `None`, meaning "keep what is live".** It
    is the second half of this two-field resource and it is not ours: a
    deployment that configured an OTP lockout keeps it, because the `PUT` is a
    REPLACE and a body carrying only our one opinion would zero it. A caller
    with an opinion passes an int and manages both.

    The read is `GET /admin/v1/policies/lockout`; the write is
    `PUT /admin/v1/policies/password/lockout`. That asymmetry is Zitadel's, it
    is measured off the admin swagger document the running build serves, and it
    is the kind of thing that turns into a 404 nobody expected.

    **This `PUT` refuses a no-op too, MEASURED**: an unchanged body answers
    `400 INSTANCE-0psjF`, "Errors.Instance.LockoutPolicy.NotChanged". So the
    comparison above is the idempotence rather than a saving, exactly as it is
    in `ensure_login_policy`. `ensure_restrictions` is the one of the three that
    ACCEPTS a no-op (200, sequence unmoved, also measured) — and it compares
    anyway, so that `created` means the same thing in all three and the seed's
    printed line can be believed.
    """
    live = lockout_policy()
    baseline: dict[str, Any] = {
        key: live.get(key, absent) for key, absent in LOCKOUT_POLICY_ABSENT.items()
    }
    # Zitadel serialises these as JSON numbers; a deployment that hand-edited
    # one into a string would otherwise make every comparison disagree forever.
    baseline = {key: int(value) for key, value in baseline.items()}
    desired: dict[str, Any] = {**baseline, "maxPasswordAttempts": int(max_password_attempts)}
    if max_otp_attempts is not None:
        desired["maxOtpAttempts"] = int(max_otp_attempts)
    owner = str((live.get("details") or {}).get("resourceOwner", ""))
    if desired == baseline:
        log.info(
            "accounts.zitadel.lockout_policy_unchanged",
            max_password_attempts=int(max_password_attempts),
        )
        return Resource(id=owner, created=False)
    _call("PUT", "/policies/password/lockout", desired, prefix=ADMIN)
    log.info(
        "accounts.zitadel.lockout_policy_updated",
        max_password_attempts=int(max_password_attempts),
    )
    return Resource(id=owner, created=True)


def ensure_restrictions(*, is_public_org_registration_disallowed: bool) -> Resource:
    """Whether a stranger may create an organisation here. **Full body.**

    A different door from `ensure_login_policy`'s: that one
    governs whether a person may register themselves into an existing
    organisation, this one governs `/ui/login/register/org`, which creates an
    ORGANISATION and its first administrator in one form. A product whose
    invitations are the way in has both doors to close, and the second one is
    invisible from the first: the org-registration page answers `200` with a
    working form on an instance whose login policy already refuses
    self-registration. Measured on this box, which is how it was found.

    `allowedLanguages` is merged from the live answer rather than set, because
    this endpoint's own description is "Undefined values don't change the
    current restriction. Zero values remove the current restriction" — so a
    partial body here is not merely a REPLACE, it is a REMOVE.
    """
    live = restrictions()
    baseline: dict[str, Any] = {
        key: live.get(key, absent) for key, absent in RESTRICTIONS_ABSENT.items()
    }
    desired: dict[str, Any] = {
        **baseline,
        "disallowPublicOrgRegistration": bool(is_public_org_registration_disallowed),
    }
    owner = str((live.get("details") or {}).get("resourceOwner", ""))
    if desired == baseline:
        log.info(
            "accounts.zitadel.restrictions_unchanged",
            disallow_public_org_registration=bool(is_public_org_registration_disallowed),
        )
        return Resource(id=owner, created=False)
    _call("PUT", "/restrictions", desired, prefix=ADMIN)
    log.info(
        "accounts.zitadel.restrictions_updated",
        disallow_public_org_registration=bool(is_public_org_registration_disallowed),
    )
    return Resource(id=owner, created=True)


def _settled_target(*, name: str, existing_id: str) -> str:
    """Which existing IdP an `ensure_*` should update, or `""` to create one.

    The two nets, in order and in one place so the generic-OIDC and the Google
    template cannot drift apart: **the id our own row recorded**, discarded when
    Zitadel no longer knows it (somebody deleted it in the console, and a
    re-sync is the repair), then **the search by name**, which is what catches
    the very first run and the run after a row lost its id.
    """
    target = existing_id.strip()
    if target and get_identity_provider(idp_id=target) is None:
        target = ""
    if target:
        return target
    found = find_identity_provider(name=name)
    return str(found["id"]) if found is not None else ""


def deactivate_identity_provider(*, idp_id: str) -> Resource:
    """Stop an external IdP being able to sign anybody in, keeping the object.

    What `disable_sso_connection` materialises. **Deactivate and not delete**,
    for the reason the service gives about the row: deleting takes the links
    between Zitadel users and that provider with it, and a customer mid-migration
    who re-enables tomorrow would find everybody unlinked.

    Idempotent the way an activity needs: deactivating an already-deactivated
    provider is Zitadel answering "precondition failed", and that is the state
    the caller asked for, so it is reported as `created=False` rather than
    raised. A provider that is simply gone is the same answer for the same
    reason — there is nothing left that can sign anybody in.
    """
    if not idp_id.strip():
        return Resource(id="", created=False)
    if get_identity_provider(idp_id=idp_id) is None:
        return Resource(id=idp_id, created=False)
    try:
        _call("POST", f"/idps/{idp_id}/_deactivate", {})
    except ZitadelError as error:
        if not _is_already_in_that_state(error):
            raise
        return Resource(id=idp_id, created=False)
    log.info("accounts.zitadel.idp_deactivated", idp_id=idp_id)
    return Resource(id=idp_id, created=True)


# Zitadel's word for "you asked for the state it is already in". A management
# API that answered 200 to a second deactivation would need none of this; it
# answers 400 with this in the body, and an activity that treated that as a
# failure would retry six times and then fail a run that had already succeeded.
_ALREADY_STATES = ("AlreadyDeactivated", "AlreadyInactive", "NotActive", "AlreadyExists")


def _is_already_in_that_state(error: ZitadelError) -> bool:
    text = str(error)
    return any(marker in text for marker in _ALREADY_STATES)


def deactivate_user(*, user_id: str) -> Resource:
    """Take a person's Zitadel account out of use. **What erasure owes.**

    An erasure that anonymised our row and left the identity platform's account
    live would be an erasure a person could sign straight back through: the
    session cookie is ours, but the *credential* is Zitadel's, and so is the
    next login. This is the other half of `services.erase_user`, reached the
    only way anything reaches the management API — an activity, through here.

    Idempotent, and both no-op cases are real: a user Zitadel has never heard of
    (an account erased before it ever signed in through the platform), and one
    that is already inactive (a retry, which is the normal case).
    """
    if not user_id.strip():
        return Resource(id="", created=False)
    try:
        _call("POST", f"/users/{user_id}/_deactivate", {})
    except ZitadelError as error:
        if _is_already_in_that_state(error) or "NotFound" in str(error) or " 404" in str(error):
            return Resource(id=user_id, created=False)
        raise
    log.info("accounts.zitadel.user_deactivated", zitadel_user_id=user_id)
    return Resource(id=user_id, created=True)


def identity_provider_links(*, user_id: str) -> list[dict[str, Any]]:
    """Every external identity linked to one Zitadel user."""
    return _search(f"/users/{user_id}/idps/_search", {})


def remove_identity_provider_links(*, user_id: str) -> int:
    """Cut every federated login route into one Zitadel account. Returns the count.

    Deactivation alone is enough to refuse a sign-in today; the links are cut as
    well because a re-activated account with its links intact is one console
    click from being somebody's way back in to an erased person's history. The
    links are what an erasure is actually erasing — the join between a person at
    Google or Okta and an account here.

    Idempotent: a link already gone is a 404, which is the state asked for.
    """
    if not user_id.strip():
        return 0
    removed = 0
    for link in identity_provider_links(user_id=user_id):
        idp_id = str(link.get("idpId", ""))
        external = str(link.get("providedUserId") or link.get("userId", ""))
        if not idp_id or not external:
            continue
        try:
            _call("DELETE", f"/users/{user_id}/idps/{idp_id}/{external}")
        except ZitadelError as error:
            if "NotFound" in str(error) or " 404" in str(error):
                continue
            raise
        removed += 1
    if removed:
        log.info("accounts.zitadel.idp_links_removed", zitadel_user_id=user_id, count=removed)
    return removed


def rotate_web_application_secret(*, project_id: str, app_id: str) -> Resource:
    """Mint a new client secret for the browser RP, and hand it back once.

    **The recovery path for the one thing `zitadel_seed` cannot do twice.**
    Zitadel shows a client secret at creation and never again, so a deployment
    that lost the secret between the seed run and `.env` had, until this, no way
    forward but deleting the application — which changes the client id, which
    invalidates every redirect URI and every `.env` that already had it right.

    `created=True` always, and it means what it says here: this call *made* a
    secret. Rotating is not idempotent and must not pretend to be — the point of
    it is that the previous secret stops working, so a second call is a second
    rotation and a second secret. The command that drives it says so before it
    runs.
    """
    body = _call(
        "POST",
        f"/projects/{project_id}/apps/{app_id}/oidc_config/_generate_client_secret",
        {},
    )
    log.info("accounts.zitadel.application_secret_rotated", application_id=app_id)
    return Resource(
        id=app_id,
        created=True,
        detail={"clientSecret": str(body.get("clientSecret", ""))},
    )


def rotate_api_application_secret(*, project_id: str, app_id: str) -> Resource:
    """Mint a new client secret for the MCP resource, and hand it back once.

    **The sibling `rotate_web_application_secret` had and this did not.**
    `ensure_api_application` prints a `clientSecret` on the run that creates it
    and Zitadel never shows it again — exactly the browser client's problem, on
    the credential a resource server validates audiences with — and there was no
    way back from losing it but deleting the application, which changes the app
    id every `.env` and every registered audience already names. A credential
    with no rotation path is one nobody dares rotate, which is the opposite of
    what a rotation path is for.

    The endpoint differs from the web one by a single path segment — `api_config`
    rather than `oidc_config` — because Zitadel models an API application's
    configuration as its own object. Everything else is deliberately identical,
    down to `created=True` meaning "this call *made* a secret": rotating is not
    idempotent and must not pretend to be, so a second call is a second
    rotation and a second secret.

    Nothing of ours is written and nothing is stored. The plaintext is in the
    return value, printed once by the command that asked for it, and then gone.
    """
    body = _call(
        "POST",
        f"/projects/{project_id}/apps/{app_id}/api_config/_generate_client_secret",
        {},
    )
    log.info("accounts.zitadel.application_secret_rotated", application_id=app_id, kind="api")
    return Resource(
        id=app_id,
        created=True,
        detail={"clientSecret": str(body.get("clientSecret", ""))},
    )


#: **The full-body convention's declared population**: every PUT-shaped
#: writer in this module, by the resource path it PUTs to, with that resource's
#: FULL field set beside it.
#:
#: Zitadel's management and admin PUTs are REPLACES, not merges. A writer whose
#: body is a strict subset of the resource's field set therefore zeroes every
#: field it left out — silently, because the writer's own no-op check and
#: `zitadel_audit` both read only the keys the writer sends. That is one shape
#: with three sightings (the label colours, the OIDC provider's `usePkce`, and a
#: sibling platform's login policy), which is why the convention is declared here
#: rather than remembered:
#: **every `ensure_*` merges its intent over the live GET and sends the whole
#: set**, and the census in `apps/accounts/tests/test_zitadel_full_body.py`
#: reads these declarations and fails by name when a body is short.
#:
#: Every set above was read out of the API this deployment actually runs —
#: `/openapi/v2/swagger/v2/zitadel/zitadel/{admin,management}.swagger.json` on
#: ghcr.io/zitadel/zitadel:v4.17.1 — never recalled from a doc page. The source
#: message name is named beside each set.
#:
#: The key is the resource path WITHOUT a version prefix, so the login policy's
#: two surfaces (the instance's on `ADMIN`, an org's on `MANAGEMENT`) share one
#: declaration — which is a measured fact, not a convenience:
#: `v1UpdateLoginPolicyRequest` and `v1UpdateCustomLoginPolicyRequest` carry the
#: same seventeen properties on this build.
PUT_FIELD_SETS: dict[str, frozenset[str]] = {
    "/policies/login": LOGIN_POLICY_FIELDS,
    "/policies/password/lockout": LOCKOUT_POLICY_FIELDS,
    "/restrictions": RESTRICTIONS_FIELDS,
    "/policies/label": LABEL_POLICY_FIELDS,
    "/idps/generic_oidc/{id}": OIDC_IDENTITY_PROVIDER_FIELDS,
    "/idps/google/{id}": GOOGLE_IDENTITY_PROVIDER_FIELDS,
}


def put_field_set(path: str) -> frozenset[str] | None:
    """The full field set a `PUT` to `path` owes, or `None` when it owes none.

    Takes the path as the transport sees it — with or without a version prefix,
    with a real id where a template carries `{id}` — because the census reads
    recorded requests and the future rule will read call sites, and both should
    ask this one function rather than each growing its own normalisation.

    `None` rather than an exception for an unknown path: `DELETE`s, `POST`s and
    the reads all come through the same log, and a resolver that raised on them
    would make the census assert about the wrong thing.
    """
    resource = path
    for prefix in (MANAGEMENT, ADMIN, USER):
        if resource.startswith(prefix):
            resource = resource[len(prefix) :]
            break
    if resource in PUT_FIELD_SETS:
        return PUT_FIELD_SETS[resource]
    head, _, tail = resource.rpartition("/")
    return PUT_FIELD_SETS.get(f"{head}/{{id}}") if tail else None
