"""The only place in this product that speaks to Zitadel's APIs.

Two surfaces, one door. Org-scoped administration is Zitadel's v1 management
API (`MANAGEMENT`); creating a person with no credentials and minting them an
invite code exist only on its v2 user API (`USER`); one instance-wide read
(`ADMIN`) tells the invitation email how long its link stands. All three are
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

# The instance-wide administration prefix. One read only (`invite_code_lifetime`
# below), because the number in the invitation email has to be Zitadel's number
# rather than ours.
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


def ensure_oidc_identity_provider(
    *,
    name: str,
    issuer: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
    existing_id: str = "",
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
    """
    payload: dict[str, Any] = {
        "name": name,
        "issuer": issuer,
        "clientId": client_id,
        "clientSecret": client_secret,
        "scopes": scopes or ["openid", "profile", "email"],
        "isIdTokenMapping": False,
        "providerOptions": {
            "isLinkingAllowed": True,
            "isCreationAllowed": True,
            "isAutoCreation": False,
            "isAutoUpdate": False,
            "autoLinking": "AUTO_LINKING_OPTION_UNSPECIFIED",
        },
    }
    # Our row's id, then the search by name — `_settled_target` holds both nets
    # so this and the Google template below cannot drift apart. A row naming an
    # IdP somebody deleted in the console falls through to create, which is the
    # repair a re-sync is for; `zitadel_audit` is what makes it visible before
    # then.
    target = _settled_target(name=name, existing_id=existing_id)
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
