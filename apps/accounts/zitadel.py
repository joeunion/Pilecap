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

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

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

# The **authenticated caller's own** surface, and the fourth prefix this module
# speaks. One read: which user the machine PAT belongs to. Nothing else here
# needs it, and nothing else should — it is how `ensure_instance_member_role`
# finds the user it must grant `IAM_LOGIN_CLIENT` to without any deployment
# having to write that id into `.env`, where it would be a second copy of a
# fact Zitadel already knows (first principles 9).
#
# MEASURED against the pinned build (v4.17.1): `GET /auth/v1/users/me` with the
# machine PAT answers `{"user": {"id", "userName", "machine": {...}}}` for the
# service account the PAT was minted for. The management API has no such read —
# a PAT cannot ask "who am I" on `/management/v1` at all — which is why this
# prefix exists rather than the call being folded into one of the three above.
AUTH = "/auth/v1"

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
    #: **The third state, and it is not `created`'s twin.** An `ensure_*` that
    #: RECONCILES an object it found has three honest answers — I made it, I
    #: found it and it agreed, I found it and made it agree — and a writer with
    #: only two would have to call the third one `created`, which is the one
    #: word a reader uses to decide whether a second object now exists. The
    #: seed's `updated` verb reads this.
    updated: bool = False


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
def _client(*, timeout: float | None = None) -> Iterator[httpx.Client]:
    """A client bound to this deployment's Zitadel, with the PAT attached.

    Private, and rule 27 keeps it that way: a caller that could build its own
    client could set its own timeout, log its own headers and skip everything
    below. The retry policy is deliberately **not** here — it belongs to the
    Temporal activity that calls these functions, where a retry is durable and
    visible instead of a loop nobody can see from outside the process.

    `timeout` is the ONE thing a caller may say, and it exists because the two
    populations of call here run under different clocks: a management call is a
    seed step or an activity and gets `ZITADEL_MANAGEMENT_TIMEOUT`, while a
    sign-in check is a person waiting at a form and gets the much shorter
    `ZITADEL_SIGNIN_TIMEOUT` (design I-A §3.2). It is a parameter rather than a
    second client builder for the reason `_call`'s `prefix` is one: a copy of
    this function is a second place the credential, the headers and the
    never-log-the-body rule can drift.
    """
    issuer = _issuer()
    token = _token()
    if not issuer or not token:
        raise ZitadelNotConfigured(
            "Zitadel is not configured for this deployment: ZITADEL_ISSUER and "
            "ZITADEL_PAT must both be set. ./scripts/setup.sh writes the PAT into "
            ".env from the zitadel_bootstrap volume."
        )
    if timeout is None:
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


def get_application(*, project_id: str, app_id: str) -> dict[str, Any] | None:
    """One application BY ID, as `GET /projects/{p}/apps/{a}` answers it.

    The sibling of `find_application`, and the one a writer that was handed an
    id needs: searching a project by name to re-find an application whose id
    the caller already holds is a read that can answer with a DIFFERENT object
    — two applications may share a name, and the search's first match is not
    necessarily the one the caller meant.

    MEASURED against the pinned build (v4.17.1): the answer is
    `{"app": {"id", "state", "name", "oidcConfig": {...}}}` — the same
    application shape `applications()` returns in its result list, wrapped in
    one key — and `None` here is the 404 that path answers for an id this
    project does not hold.
    """
    try:
        body = _call("GET", f"/projects/{project_id}/apps/{app_id}")
    except ZitadelError as error:
        if " 404" in str(error):
            return None
        raise
    app = body.get("app")
    return dict(app) if isinstance(app, dict) else None


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


def read_user(*, user_id: str) -> Probe:
    """`GET /v2/users/{id}` — one person, by id, **ACROSS ORGANISATIONS**.

    The sibling of `find_user` and the one that is not org-scoped. MEASURED
    on the pinned build: the management search
    (`POST /management/v1/users/_search`, which `find_user` uses) answers
    only rows in the caller's own organisation, so a person invited into a
    second org on the same instance is invisible to it — they authenticate
    and then meet an outage at the landing (V-A-W3). This read answers 200
    with `user.userId` and the same `human.email` block for a person in any
    organisation.
    """
    return probe("GET", f"/users/{user_id}", prefix=USER)


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


#: **The OIDC application config's FULL field set**, read out of the API the
#: pinned build serves: `ManagementServiceUpdateOIDCAppConfigBody` in
#: `/openapi/v2/swagger/v2/zitadel/zitadel/management.swagger.json` on
#: ghcr.io/zitadel/zitadel:v4.17.1 — **eighteen properties**, measured by
#: counting that definition's own `properties` map. The GET's shape
#: (`zitadelAppV1OIDCConfig`) carries twenty-three, and the five extra are
#: read-only — `clientId`, `version`, `noneCompliant`, `complianceProblems`,
#: `allowedOrigins` — so they are deliberately NOT here: sending a field the
#: update body does not declare is how a writer starts getting 400s on a build
#: that tightened its parser.
#:
#: The map is what an ABSENT key means and the field set derives from its keys,
#: as every sibling declaration does. Proto3 omits its zero values, so an
#: absent boolean is `False`, an absent array is `[]` and an absent Duration is
#: `"0s"`.
#:
#: **`ios` and `android` are message fields, and their zero is `None`** —
#: protojson's unset representation. That one cell is the only member of any
#: field set in this module whose absent value could not be read off the
#: swagger's type alone, so it was MEASURED instead, against the running stack:
#: `PUT /management/v1/projects/0.../apps/0.../oidc_config` with
#: `{"ios": null, "android": null}` answers `404 COMMAND-2n8uU` — "Application
#: doesn't exist" — which is the LOOKUP failing, so the body parsed. A parser
#: that had rejected the nulls would have answered 400 before reaching the
#: command. The ids in that probe name nothing and it created nothing.
#:
#: **`loginVersion` is a field we state no opinion about** and it is here for
#: the reason the login policy's five lifetimes are: so a body that carries our
#: three also carries it back byte-identical, rather than resetting a
#: deployment's login version as a side effect of fixing a redirect URI.
OIDC_APP_CONFIG_ABSENT: dict[str, Any] = {
    "redirectUris": [],
    "responseTypes": [],
    "grantTypes": [],
    "appType": "OIDC_APP_TYPE_WEB",
    "authMethodType": "OIDC_AUTH_METHOD_TYPE_BASIC",
    "postLogoutRedirectUris": [],
    "devMode": False,
    "accessTokenType": "OIDC_TOKEN_TYPE_BEARER",
    "accessTokenRoleAssertion": False,
    "idTokenRoleAssertion": False,
    "idTokenUserinfoAssertion": False,
    "clockSkew": "0s",
    "additionalOrigins": [],
    "skipNativeAppSuccessPage": False,
    "backChannelLogoutUri": "",
    "loginVersion": None,
    "ios": None,
    "android": None,
}
OIDC_APP_CONFIG_FIELDS = frozenset(OIDC_APP_CONFIG_ABSENT)


def oidc_app_config_of(application: Mapping[str, Any]) -> dict[str, Any]:
    """One application's live OIDC config, as the update body's own field set.

    The GET's extra read-only keys are dropped here rather than at each reader,
    so "what this application says" and "what a PUT may say about it" are one
    shape and a comparison between them cannot be a comparison of two
    vocabularies.
    """
    live = dict(application.get("oidcConfig") or {})
    return {key: live.get(key, absent) for key, absent in OIDC_APP_CONFIG_ABSENT.items()}


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

    **It RECONCILES what it finds, and used to pin it at birth.** Finding an
    application by name and returning its id meant every value declared here —
    the redirect URI, the post-logout URI, `devMode` — was written exactly once,
    at creation, and belonged to whoever edited the console after that. Two
    ordinary moves broke sign-in with the seed still saying `exists`: a
    deployment whose `PUBLIC_BASE_URL` changed kept the old callback and no
    other, and a one-field console edit to the redirect URI left the person
    signing in on raw JSON at the identity platform — upstream of the callback,
    so no page of ours ever renders and no remedy is offered.

    **Full body, and the idempotence is the comparison** (ADR ident-8). Zitadel's
    `PUT` is a REPLACE, so the three fields this deployment states an opinion
    about are merged over the live config and the whole of
    `OIDC_APP_CONFIG_FIELDS` is sent; when the merged body equals the live one
    nothing is written at all, which is what the run `scripts/setup.sh` makes on
    every invocation needs and what keeps the fields nobody here manages
    byte-identical.

    **The declared values WIN, including by removal.** A URI that is no longer
    declared is gone, not kept beside the new one: an application still
    accepting a callback on an origin the deployment has moved off is a redirect
    target somebody else may come to own.
    """
    existing = find_application(project_id=project_id, name=name)
    if existing is not None:
        app_id = str(existing["id"])
        client_id = str((existing.get("oidcConfig") or {}).get("clientId", ""))
        live = oidc_app_config_of(existing)
        desired = {
            **live,
            "redirectUris": list(redirect_uris),
            "postLogoutRedirectUris": list(post_logout_uris),
            "devMode": bool(dev_mode),
        }
        if desired == live:
            log.info("accounts.zitadel.application_unchanged", application_name=name, kind="web")
            return Resource(id=app_id, created=False, detail={"clientId": client_id})
        _call("PUT", f"/projects/{project_id}/apps/{app_id}/oidc_config", desired)
        log.info(
            "accounts.zitadel.application_updated",
            application_name=name,
            kind="web",
            redirect_uris=list(redirect_uris),
        )
        return Resource(id=app_id, created=False, updated=True, detail={"clientId": client_id})
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


#: **Which login UI an application sends a person to**, as Zitadel's own
#: `v1LoginVersion` message: `{"loginV1": {}}`, `{"loginV2": {"baseUri": …}}`,
#: or ABSENT, which means "whatever the instance default is" — read out of
#: `management.swagger.json` on ghcr.io/zitadel/zitadel:v4.17.1 and MEASURED
#: end to end against the running stack on 2026-09-18 with a throwaway
#: application under a throwaway project, deleted afterwards:
#:
#:   no declaration  → `GET /oauth/v2/authorize` 302s to
#:                     `/ui/login/login?authRequestID=<id>`
#:   loginV2 baseUri → 302s to `<baseUri>/login?authRequest=V2_<id>`
#:   `loginVersion: null` in a full-body PUT → the key is GONE from the next
#:                     GET, and the authorize 302 is the first shape again
#:
#: That last line is the whole of "`None` CLEARS", and it is measured rather
#: than assumed because it is the road back: the consumer locked an owner out
#: of a deployment for a morning with a v2 declaration and no way to withdraw
#: it (their ADR ident-9, amendment 4; design C-9's "the reconciler's CLEAR").
#:
#: **This product states an opinion about the field only through
#: `ensure_application_login_version`.** `ensure_web_application` carries it
#: back byte-identical — it is in `OIDC_APP_CONFIG_ABSENT` for exactly that
#: reason — so fixing a redirect URI never changes which page a person lands
#: on, and declaring a login version never changes a redirect URI.
LOGIN_V2 = "loginV2"


def login_version_declaration(base_uri: str | None) -> dict[str, Any] | None:
    """The `loginVersion` value this deployment declares, from one base URI.

    `None` in, `None` out, and that is the CLEAR: a full-body PUT carrying
    `loginVersion: null` removes the declaration and the application goes back
    to the instance default (measured above). It is deliberately NOT `{}` and
    deliberately NOT `{"loginV1": {}}` — the first is a message with no field
    set, which protojson accepts and Zitadel reads as "v1 pinned", and the
    second pins v1 on an instance whose default may one day be v2. Neither is
    "we state no opinion", which is what a deployment on the hosted page means.
    """
    if base_uri is None:
        return None
    return {LOGIN_V2: {"baseUri": base_uri}}


def login_version_of(application: Mapping[str, Any]) -> dict[str, Any] | None:
    """One application's LIVE `loginVersion`, in the same shape the writer sends.

    One shape for the declaration and the observation, for the reason
    `oidc_app_config_of` gives about the config as a whole: a comparison
    between "what we declare" and "what is there" must not be a comparison of
    two vocabularies. `None` is the absent key, which is the state a
    deployment on the hosted page declares.
    """
    live = dict(application.get("oidcConfig") or {})
    value = live.get("loginVersion")
    return dict(value) if isinstance(value, dict) else None


def login_base_uri_of(application: Mapping[str, Any]) -> str | None:
    """Where a v2-declared application sends people, for a report's own words.

    `None` covers three different states on purpose — no declaration, v1
    pinned, and v2 at the instance's own URI — because none of them is a base
    URI and a reader wanting the DECLARATION rather than the URI asks
    `login_version_of`. The judgement is made on that; this is for the line.
    """
    version = login_version_of(application)
    two = (version or {}).get(LOGIN_V2)
    if not isinstance(two, dict):
        return None
    return str(two.get("baseUri", "")) or None


def ensure_application_login_version(
    *, project_id: str, app_id: str, base_uri: str | None
) -> Resource:
    """Declare which login UI one application uses — or withdraw the declaration.

    **The whole of design C-9's writer half, and it goes BOTH ways.** A
    deployment whose front door is our own page declares
    `loginVersion.loginV2.baseUri = <PUBLIC_BASE_URL>/accounts` on the
    application people sign in through, and Zitadel appends `/login`. A
    deployment on the hosted page declares nothing — and "declares nothing" has
    to be a value this function can WRITE, not merely a call it can skip,
    because the state it has to reach is an instance where somebody else (a
    console edit, a previous `SIGN_IN_DOOR=ours`, a sibling checkout) already
    declared v2. `base_uri=None` therefore CLEARS.

    **`None` is not "no applications to declare".** The consumer paid for that
    distinction: a reconciler that expressed "clear it" as an empty list of
    applications to write ran zero iterations and left the declaration exactly
    where it was, green, with the owner still locked out. So the argument is a
    value with three readings and one of them is the withdrawal, and
    `test_none_clears_a_v2_declaration_the_console_set` is the case that keeps
    it that way.

    **Full body, and the idempotence is the comparison** (ADR ident-8).
    Zitadel's `PUT` is a REPLACE: a body carrying only `loginVersion` would
    zero every redirect URI the application has. So the declaration is merged
    over the live config, the whole of `OIDC_APP_CONFIG_FIELDS` is sent, and a
    declaration that AGREES with what is live sends no request at all — which
    is what `scripts/setup.sh` running the seed on every invocation needs.

    `updated` is the verb that carries news here, exactly as it does on
    `ensure_web_application`: something outside this codebase had declared a
    login version, and this run declared it back.
    """
    application = get_application(project_id=project_id, app_id=app_id)
    if application is None:
        raise ZitadelError(
            f"Zitadel has no application {app_id} on project {project_id}: a login "
            "version can only be declared on an application that exists. Run "
            "manage.py zitadel_seed."
        )
    live = oidc_app_config_of(application)
    desired = {**live, "loginVersion": login_version_declaration(base_uri)}
    if desired == live:
        log.info(
            "accounts.zitadel.login_version_unchanged",
            application_id=app_id,
            declared=bool(base_uri),
        )
        return Resource(id=app_id, created=False)
    _call("PUT", f"/projects/{project_id}/apps/{app_id}/oidc_config", desired)
    log.info(
        "accounts.zitadel.login_version_declared",
        application_id=app_id,
        declared=bool(base_uri),
        base_uri=base_uri or "",
    )
    return Resource(id=app_id, created=False, updated=True)


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

    Built here rather than in the template or the activity because the hosted
    half is a fact about Zitadel's own front end, and this module is the only
    one allowed to know facts about Zitadel. `INVITE_PATH` above records how it
    was measured.

    **It branches on `SIGN_IN_DOOR`** (design C-13, A5.5), and the two halves
    are the same link at two front ends:

    * `hosted` — Zitadel's own credential page, unchanged and still the
      default. `_issuer()` is where this deployment's platform lives.
    * `ours` — our entrance, which under that door is the one place a person
      ever types a password. The QUERY IS THE PLATFORM'S, deliberately
      (`userID` and `code`, the names Zitadel's own page reads): an operator
      comparing two links sees one tail, and the invite road (rung A7) reads
      the parameters the platform mints rather than a second spelling of them.

    Both values are percent-encoded on both halves. Neither can contain a
    delimiter today — an id is digits and a code is six uppercase
    alphanumerics — and that is exactly why encoding costs nothing and is
    worth having when one of them changes shape.

    `reverse` at call time rather than a literal path: `config/urls.py` owns
    where the sign-in door hangs, and a second spelling here would be the
    fourth thing that has to agree about one URL.
    """
    tail = f"?userID={quote(str(user_id), safe='')}&code={quote(str(code), safe='')}"
    if str(getattr(settings, "SIGN_IN_DOOR", "hosted")) == "ours":
        from django.urls import reverse

        base = str(getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
        return f"{base}{reverse('account_login')}{tail}"
    return f"{_issuer()}{INVITE_PATH}{tail}"


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


# --- the instance manager roles the machine credential holds ------------------
#
# A manager role is not a policy and not an object: it is what the PAT is
# ALLOWED to do, and the design depends on one of them by name.

#: **The manager role the login-v2 finalize needs, and `IAM_OWNER` does not
#: carry it.** `POST /v2/oidc/auth_requests/{id}` — the call that turns a
#: signed-in session into the OIDC code the relying party is waiting for —
#: answers `403 AUTH-AWfge` for a machine user holding every other instance
#: role there is. The consumer's whole V2-1 rung was BLOCKED on this one fact
#: and their design calls it out as the thing not to re-buy (design I-A, fact
#: 2). It is granted here, by the seed, rather than in a runbook step, because
#: a permission a deployment needs and an operator has to remember is a
#: deployment that works on the box where somebody remembered.
LOGIN_CLIENT_ROLE = "IAM_LOGIN_CLIENT"

#: **The IAM member's FULL field set** — one property, `roles` — read out of
#: `AdminServiceUpdateIAMMemberBody` in
#: `/openapi/v2/swagger/v2/zitadel/zitadel/admin.swagger.json` on
#: ghcr.io/zitadel/zitadel:v4.17.1. One field is exactly why it is declared:
#: `PUT /admin/v1/members/{userId}` REPLACES the role list, so a body carrying
#: `["IAM_LOGIN_CLIENT"]` takes `IAM_OWNER` away from the credential this
#: product administers Zitadel with — and the next seed run would then fail on
#: its first management call, with nothing left that could grant it back. The
#: full-body convention is not a nicety on this resource; it is the difference
#: between adding a role and locking the deployment out of its own instance.
IAM_MEMBER_FIELDS = frozenset({"roles"})


def instance_members() -> list[dict[str, Any]]:
    """Everyone holding a manager role on the INSTANCE, with their roles.

    MEASURED against the pinned build: `POST /admin/v1/members/_search` with an
    empty body answers `{"details": {...}, "result": [{"userId", "roles",
    "preferredLoginName", "userType", …}]}`, and a machine user appears there
    as `TYPE_MACHINE` exactly as a person appears as `TYPE_HUMAN`.
    """
    return _search("/members/_search", {}, prefix=ADMIN)


def instance_member_roles(*, user_id: str) -> list[str]:
    """The instance manager roles one user holds. Empty for a non-member.

    Empty is deliberately not `None`: "holds no manager role" and "is not a
    member" are the same thing to every reader here — the finalize refuses
    both identically — and a caller that had to tell them apart would be a
    caller asking the wrong question.
    """
    for row in instance_members():
        if str(row.get("userId", "")) == user_id:
            return [str(one) for one in (row.get("roles") or [])]
    return []


def machine_user() -> dict[str, Any]:
    """Whoever the PAT belongs to, as Zitadel itself reports it.

    The one read on the `AUTH` prefix, and the reason it exists rather than a
    `ZITADEL_MACHINE_USER_ID` key in `.env`: the id is Zitadel's fact about the
    credential, so a second copy in the environment is a copy that can be wrong
    — and a role granted to the wrong user id is a grant that reads as done and
    changes nothing (first principles 9).
    """
    body = _call("GET", "/users/me", prefix=AUTH)
    user = body.get("user")
    return dict(user) if isinstance(user, dict) else {}


def ensure_instance_member_role(*, user_id: str, role: str) -> Resource:
    """Give one user an instance manager role, keeping every role they hold.

    **Additive, and that is the whole of it.** Zitadel's update is a REPLACE of
    the role list (`IAM_MEMBER_FIELDS` says what that costs), so this reads the
    live roles, appends, and sends the union — and sends nothing at all when
    the role is already held, which is the readable idempotence every writer
    here has.

    Three states, and the third is the one a fresh instance is in for a
    person but never for the machine user: already a member with the role
    (nothing sent), already a member without it (`PUT`, the union), not a
    member at all (`POST /admin/v1/members`, which is a CREATE and so reports
    `created`).

    **Nothing is ever taken away.** There is no `roles=` parameter and no
    remove path: a reconciler that could compute a role list would eventually
    compute one without `IAM_OWNER` on the credential it is reconciling with.
    A role granted by hand in the console survives every run of this.
    """
    held = instance_member_roles(user_id=user_id)
    if role in held:
        log.info("accounts.zitadel.instance_role_unchanged", zitadel_user_id=user_id, role=role)
        return Resource(id=user_id, created=False, detail={"roles": list(held)})
    if not held:
        _call("POST", "/members", {"userId": user_id, "roles": [role]}, prefix=ADMIN)
        log.info("accounts.zitadel.instance_member_added", zitadel_user_id=user_id, role=role)
        return Resource(id=user_id, created=True, detail={"roles": [role]})
    union = [*held, role]
    _call("PUT", f"/members/{user_id}", {"roles": union}, prefix=ADMIN)
    log.info("accounts.zitadel.instance_role_granted", zitadel_user_id=user_id, role=role)
    return Resource(id=user_id, created=False, updated=True, detail={"roles": union})


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


# --- the checks: two facts about the pinned build, measured on demand --------
#
# Design I-A's measurement kit (§3.7). These are NOT dialled by the suite —
# ADR ident-5(a) is that the test suite never reaches a real instance — and
# they are not `ensure_*` either: each one goes and LOOKS at the running
# deployment and reports what it saw, for `manage.py zitadel_measure` to judge.
# They live here because everything that speaks to Zitadel lives here (house
# rule 27), and because M1 mutates: a check that needed a mutation and could
# not make one through this module would be a second door.


def deactivate_application(*, project_id: str, app_id: str) -> Resource:
    """Stop an application being able to start a login, keeping the object.

    **What a throwaway owes.** `check_login_version_redirects` below makes an
    application to measure against, and an OIDC client left active on a real
    project is a live sign-in door nobody meant to open. Deactivated rather
    than deleted for the reason `deactivate_identity_provider` gives: the
    object is the evidence a measurement was taken, and Zitadel's own audit
    log reads better with a deactivation in it than with a gap.

    Idempotent the same way its sibling is — "you asked for the state it is
    already in" is the state the caller asked for.
    """
    try:
        _call("POST", f"/projects/{project_id}/apps/{app_id}/_deactivate", {})
    except ZitadelError as error:
        if not _is_already_in_that_state(error):
            raise
        return Resource(id=app_id, created=False)
    log.info("accounts.zitadel.application_deactivated", application_id=app_id)
    return Resource(id=app_id, created=True)


def authorize_redirect(*, client_id: str, redirect_uri: str) -> str:
    """Where `GET /oauth/v2/authorize` sends a browser for one client. **A read.**

    Not through `_call`: the answer is a 302 with an empty body and the whole
    of the fact is in the `Location` header, so a helper that parsed JSON and
    raised on non-2xx would throw away the only thing being measured. The PAT
    rides along because `_client()` attaches it; this endpoint is a browser
    endpoint and ignores it, which is measured rather than assumed — the 302
    below was taken with the header on.

    `""` when the answer is not a redirect at all, because "Zitadel answered
    something else" is a fact the caller has to be able to report rather than
    an exception that hides which client it was asking about.
    """
    with _client() as client:
        try:
            response = client.get(
                "/oauth/v2/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid",
                },
            )
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel GET /oauth/v2/authorize failed: {error}") from error
    return str(response.headers.get("location", ""))


def check_login_version_redirects(*, project_id: str, base_uri: str) -> dict[str, str]:
    """**M1**: where the authorize endpoint sends a person, per login version.

    Design I-A's first measurement, and the one the whole front door rests on:
    with no declaration the person goes to Zitadel's own hosted page, and with
    `loginVersion.loginV2.baseUri` they go to OURS — which is only true if the
    pinned build honours the per-application declaration at all. The consumer
    measured it on v4.17.1; this is how a deployment measures it for itself,
    and how a version bump stops being able to break the front door silently.

    **It builds its own victim, and never touches the real Web application.**
    A throwaway OIDC client under the project, measured twice, deactivated in a
    `finally` so a failed measurement still closes the door it opened. The real
    browser client is what people sign in through: measuring on it would mean
    two live changes to the one object whose breakage locks everybody out.

    Returns the two `Location` headers, unjudged — `{"undeclared": …,
    "declared": …}` — because what counts as right is the measuring command's
    to say and a function that returned a boolean would have thrown away the
    string an operator needs to read when it is wrong.
    """
    # A NEW name every run, because `ensure_native_application` searches by
    # name first: a stable one would find the deactivated victim of the
    # previous run and measure the authorize endpoint against a client that
    # can no longer start a login.
    name = f"login-version-check-{uuid4().hex[:12]}"
    redirect_uri = f"{base_uri.rstrip('/')}/login-version-check"
    made = ensure_native_application(
        project_id=project_id, name=name, redirect_uris=[redirect_uri], dev_mode=True
    )
    client_id = str(made.detail.get("clientId", ""))
    try:
        undeclared = authorize_redirect(client_id=client_id, redirect_uri=redirect_uri)
        ensure_application_login_version(project_id=project_id, app_id=made.id, base_uri=base_uri)
        declared = authorize_redirect(client_id=client_id, redirect_uri=redirect_uri)
    finally:
        deactivate_application(project_id=project_id, app_id=made.id)
    return {"undeclared": undeclared, "declared": declared}


def check_login_client_role() -> dict[str, Any]:
    """**M2**: whether this deployment's credential may finalize a v2 login.

    `POST /v2/oidc/auth_requests/{id}` answers `403 AUTH-AWfge` for a machine
    user that holds `IAM_OWNER` and not `IAM_LOGIN_CLIENT`, which is the block
    the consumer's V2-1 rung died on. The check is a READ rather than an
    attempted finalize on purpose: a finalize needs a real auth request and a
    real session, so measuring it directly would mean signing somebody in, and
    the role is the whole of what the 403 is about.

    Returns the machine user's id, its login name, every instance role it
    holds and whether the one that matters is among them — unjudged, for the
    same reason M1's is.
    """
    user = machine_user()
    user_id = str(user.get("id", ""))
    roles = instance_member_roles(user_id=user_id) if user_id else []
    return {
        "user_id": user_id,
        "login_name": str(user.get("preferredLoginName", "") or user.get("userName", "")),
        "roles": roles,
        "may_finalize": LOGIN_CLIENT_ROLE in roles,
    }


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
    # TWO ids and a trailing segment, which is the shape `put_field_set`'s
    # last-segment rule could not see. It resolves this one by pattern.
    "/projects/{id}/apps/{id}/oidc_config": OIDC_APP_CONFIG_FIELDS,
    # ONE field, and the smallest set here is the one with the largest blast
    # radius: this PUT replaces the machine credential's instance manager
    # roles, so a body naming only the role being added removes IAM_OWNER from
    # the user every other call in this module authenticates as.
    "/members/{id}": IAM_MEMBER_FIELDS,
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
    for prefix in (MANAGEMENT, ADMIN, USER, AUTH):
        if resource.startswith(prefix):
            resource = resource[len(prefix) :]
            break
    if resource in PUT_FIELD_SETS:
        return PUT_FIELD_SETS[resource]
    head, _, tail = resource.rpartition("/")
    by_last_segment = PUT_FIELD_SETS.get(f"{head}/{{id}}") if tail else None
    if by_last_segment is not None:
        return by_last_segment
    # **Ids anywhere in the path, not only last.** The one-trailing-id rule
    # above covers `/idps/<id>`; it cannot see
    # `/projects/<id>/apps/<id>/oidc_config`, where the ids are in the middle
    # and the resource's own word is at the end. Matched segment by segment
    # against the declared templates, with `{id}` matching any one segment —
    # which is narrower than a regex over the whole path and cannot make two
    # different resources collide on a shared prefix.
    parts = resource.split("/")
    for template, fields in PUT_FIELD_SETS.items():
        shape = template.split("/")
        if len(shape) != len(parts):
            continue
        if all(want in ("{id}", got) for want, got in zip(shape, parts, strict=True)):
            return fields
    return None


# --- the measurement door ----------------------------------------------------
#
# Everything above this line is a WRITER or a read a writer needs: it asks
# Zitadel for the state a row declares, and a non-2xx is a `ZitadelError`
# because the caller was trying to make something true. A MEASUREMENT is the
# other shape entirely — `manage.py zitadel_measure` exists to find out what
# this build answers, and on this surface a `404`, a `400` and a `500` are the
# answers rather than the failures. Three of the design's eleven items ARE a
# non-2xx status (`404 Org-M0sif`, `400 INSTANCE-5M9vdd`, the WebAuthn `500`),
# so an instrument built on `_call` could only observe them as exceptions whose
# status it would have to re-parse out of a message string.
#
# So `probe` below returns the status instead of raising on it. It is still the
# one door (house rule 27): the same `_client()`, the same PAT, the same
# timeout, the same never-log-the-request-body rule. What it adds is that the
# caller is allowed to see a refusal, and it adds nothing a writer could use.
#
# It has TWO populations of caller now, and the second one is the reason this
# sentence is amended rather than left as it was: the measurement command, and
# the Session API functions at the bottom of this module. A sign-in check is
# the other place in this tree where a refusal is an ANSWER — a wrong password
# is a 4xx and the person has to be told so — and it reaches `probe` through
# `_session_probe`, under its own clock, never directly. Nothing in `apps/`
# outside this module calls `probe` itself.


@dataclass(frozen=True)
class Probe:
    """One raw answer: the status, the parsed body if there was one, the text.

    `ZitadelError` is still raised for the two things that are not answers — no
    credential, and a transport that never got one — because "the instance was
    unreachable" and "the instance said 404" are the two states an instrument
    must never blur (principle 4). Everything Zitadel actually said comes back
    here, refusals included.
    """

    method: str
    path: str
    status: int
    body: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def error_id(self) -> str:
        """Zitadel's STABLE error id, or `""`.

        The prose in `message` is translated and the numeric `code` is gRPC's
        coarse class; the id in `details[0].id` — `Org-M0sif`, `INSTANCE-5M9vdd`
        — is the thing worth pinning, which is why `ALREADY_INITIALIZED` above
        is matched on one. Read from the details block first and recovered from
        the message's own parenthesis when a build sends only that.
        """
        for detail in self.body.get("details") or []:
            if isinstance(detail, Mapping) and detail.get("id"):
                return str(detail["id"])
        message = str(self.body.get("message", ""))
        if message.endswith(")") and "(" in message:
            return message[message.rindex("(") + 1 : -1]
        return ""


def probe(
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    prefix: str = MANAGEMENT,
    org_id: str = "",
    timeout: float | None = None,
) -> Probe:
    """Ask, and report what came back — including a refusal. **Never writes intent.**

    `prefix=""` reaches a path that carries no version segment at all: the
    swagger documents this build serves, and the hosted credential page at
    `INVITE_PATH`, both of which are measured subjects.

    `org_id` sets `x-zitadel-orgid`, which is how Zitadel scopes an org-surface
    call to an org that is not the credential's own. MEASURED on the pinned
    build, and it is load-bearing rather than tidy: `POST /v2/sessions` with a
    `checks.user.userId` naming a person in another organisation answers
    `404 QUERY-Dfbg2` without it, and `201` with it — so an instrument that
    omitted the header would report the Session API as broken.

    No body is sent on a request that was given none, because a GET carrying
    `{}` is a GET some servers answer differently and every one of these paths
    is being measured for exactly what it answers.

    `timeout` is `_client`'s, unchanged: the measurement kit runs under the
    management clock and the sign-in seam below runs under its own.
    """
    with _client(timeout=timeout) as client:
        headers = {"x-zitadel-orgid": org_id} if org_id else None
        try:
            response = client.request(
                method,
                f"{prefix}{path}",
                json=dict(payload) if payload is not None else None,
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel {method} {prefix}{path} failed: {error}") from error
    body: dict[str, Any] = {}
    if response.content:
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            body = dict(parsed)
    return Probe(
        method=method,
        path=f"{prefix}{path}",
        status=response.status_code,
        body=body,
        text=response.text,
    )


#: Where this build publishes the API documents `PUT_FIELD_SETS` was read out
#: of. Not a doc page on the internet: the running container serves these, so
#: the field sets can be compared against the build that is actually installed
#: rather than against whatever the current release notes say.
SWAGGER_PATH = "/openapi/v2/swagger/v2/zitadel/zitadel"


def swagger_document(*, name: str) -> dict[str, Any]:
    """One of this build's own API documents, parsed. Raises if it is not there.

    `name` is `management` or `admin`. A document that will not parse is a
    `ZitadelError` rather than an empty dict, because an instrument comparing
    against `{}` would report every declared field set as a difference — a
    could-not-look wearing a DIFFERS.
    """
    answer = probe("GET", f"/{name}.swagger.json", prefix=SWAGGER_PATH)
    if not answer.ok or not answer.body:
        raise ZitadelError(
            f"Zitadel served no readable {name} swagger document at "
            f"{SWAGGER_PATH}/{name}.swagger.json (status {answer.status})"
        )
    return answer.body


def create_organization(*, name: str) -> Resource:
    """A NEW organisation, every time. **Not an `ensure_*`, and deliberately not.**

    Every writer above this line is idempotent by search-then-create, because
    every one of them is materialising an intent some row holds. This one holds
    no intent and must not be idempotent: it is the throwaway world
    `manage.py zitadel_measure` builds to measure an org that has never been
    configured, and a second run that FOUND the first run's org would be
    measuring an org somebody had already written a policy onto.

    MEASURED on the pinned build: `POST /management/v1/orgs` with `{"name":...}`
    answers `200` with the new org's `id` — the id is also its own
    `details.resourceOwner`, which is what makes a fresh org's inherited
    policies tell themselves apart from the instance's.
    """
    body = _call("POST", "/orgs", {"name": name})
    log.info("accounts.zitadel.organization_created", organization_name=name)
    return Resource(id=str(body.get("id", "")), created=True)


def remove_organization(*, org_id: str) -> bool:
    """Delete one organisation and everything in it. Returns whether it is gone.

    **The only destructive call in this module, and it exists for the victim
    rule**: a measurement that needs a clean org has to build its own rather
    than measure somebody's (rung-execution §2). So the caller creates one, and
    this is how it does not leave it behind.

    MEASURED on the pinned build: `DELETE /admin/v1/orgs/{id}` answers `200`,
    and the org's users go with it. `POST /admin/v1/orgs/{id}/_deactivate` —
    the gentler call an earlier draft of the measurement kit assumed — answers
    a bare `404 Not Found` on this build: the admin API routes a deactivate for
    `orgs/me` only, so deletion is the teardown there IS.

    `False` rather than an exception when the delete is refused, because the
    caller is already in a `finally` and an exception there would replace the
    measurement's own verdict with the cleanup's.
    """
    if not str(org_id).strip():
        return False
    try:
        answer = probe("DELETE", f"/orgs/{org_id}", prefix=ADMIN)
    except ZitadelError:
        return False
    if answer.ok:
        log.info("accounts.zitadel.organization_removed", zitadel_organization_id=org_id)
    return answer.ok


# --- the Session API: the surface a sign-in CHECK runs on (design C-8) -------
#
# Zitadel's fifth surface, and the second one on `USER`. Everything above this
# line either materialises an intent (`ensure_*`) or measures the build
# (`probe`). These are neither: they are the reads and writes ONE PERSON'S
# SIGN-IN makes while they are standing at a form, and they are here for the
# reason everything else is — house rule 27 fences the module, not a prefix, so
# the seam in `apps/accounts/signin.py` gets functions rather than a client.
#
# **They return `Probe`, never raise on a refusal, and that is the whole
# design.** A wrong password IS a 4xx, and a client that raised on it would
# make the seam read the status back out of an exception message — which is the
# shape that turns "your password is wrong" and "our credential expired" into
# one string. The seam's fail-closed rules need the status, the error id and
# the body separately; `Probe` is what already carries all three.
#
# **They run under the SIGN-IN clock**, not the management one: a person at a
# form waits `ZITADEL_SIGNIN_TIMEOUT` per call, and `signin.py` bounds the
# whole check with `ZITADEL_SIGNIN_DEADLINE` on top of that.
#
# **None of them logs a body.** `probe` never does, and the two request shapes
# below are the only two in this module that would carry a person's password or
# their one-time code.

#: The Session API's own path segment under `USER`. Named once so a typo is an
#: import error rather than a 404 a person reads as "your password is wrong".
SESSIONS = "/sessions"

#: Zitadel's stable error id for a WebAuthn begin that cannot produce a
#: challenge. MEASURED by `manage.py zitadel_measure` (M9) against the pinned
#: build, which answers it as a **500** — so a seam that read a 500 as an
#: outage would retry a person who simply has no passkey, and the one id is
#: what tells that apart from a platform that is down. The design's draft
#: spelled this `WEBAU-3M9si` (the consumer's build); the tree's own
#: measurement wins.
#:
#: **AND IT IS THREE CASES WEARING ONE ID, which A9's drive measured with a
#: virtual authenticator on v4.17.1 (2026-09-19):** no credential at all; a
#: credential registered against ANOTHER relying party (one bound to
#: `localhost` asked for on `127.0.0.1`, and the reverse); and a `domain`
#: neither party owns. Same status, same id, every time — the build does not
#: validate the domain at begin, it fails on "nothing to challenge" first. So
#: **this id alone can never say WHY**, and design J6's `passkey_elsewhere`
#: sentence is reached by asking `authentication_methods` what the person
#: actually owns (`signin._why_no_webauthn`). A reader who takes this
#: constant to mean "no passkey" is reading it as the consumer's K1 was
#: written and not as this build behaves.
WEBAUTHN_NO_CREDENTIAL = "WEBAU-4G8sw"

#: Zitadel's stable error id for a WebAuthn begin sent with NO user check —
#: the usernameless, discoverable-credential road design J6's entrance (a)
#: was drawn around. MEASURED by A9's drive: `POST /v2/sessions` carrying a
#: `webAuthN` challenge and no `checks.user` answers **400 `COMMAND-eeR2e`
#: "User ID missing"**, for our host and for the platform's alike. There is
#: no discoverable passkey road on this build through this door, which is why
#: `signin.passkey_begin` takes a login name.
WEBAUTHN_USER_REQUIRED = "COMMAND-eeR2e"

#: Zitadel's stable error id for a session id that no longer exists — the
#: ten-minute ceremony window having closed under a tab somebody left open.
#: The seam reads it as `ceremony_gone` and never as a refusal.
SESSION_GONE = "QUERY-SFeaa"


def signin_timeout() -> float:
    """How long ONE sign-in call may take. Read here so the seam cannot differ."""
    return float(getattr(settings, "ZITADEL_SIGNIN_TIMEOUT", 4.0))


def _session_probe(
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    org_id: str = "",
) -> Probe:
    """One Session API call, under the sign-in clock. The only caller is below."""
    return probe(method, path, payload, prefix=USER, org_id=org_id, timeout=signin_timeout())


def open_session(
    *,
    checks: Mapping[str, Any],
    challenges: Mapping[str, Any] | None = None,
    org_id: str = "",
) -> Probe:
    """`POST /v2/sessions` — begin a ceremony, and check whatever is checkable now.

    `checks` is Zitadel's own vocabulary (`{"user": {"loginName": …}}`,
    `{"password": {"password": …}}`) and is passed through rather than
    re-modelled, because the seam's job is to read the ANSWER: this module has
    no opinion about which checks a ceremony sends, and a wrapper that named
    them here would be a second vocabulary to keep in step with Zitadel's.

    **A 201 is not a verified anything** (M5, measured): a session created with
    a `user` check alone carries `factors.user` and no `factors.password`, so
    the seam reads the factors back rather than the status. That is fail-closed
    rule 1 and it lives in `signin.py`; what lives here is the note that this
    function cannot answer the question, by construction.

    `org_id` sets `x-zitadel-orgid`, and it is load-bearing rather than tidy —
    MEASURED: a `checks.user.userId` naming a person in another organisation
    answers `404 QUERY-Dfbg2` without it and `201` with it.
    """
    payload: dict[str, Any] = {"checks": dict(checks)}
    if challenges:
        payload["challenges"] = dict(challenges)
    return _session_probe("POST", SESSIONS, payload, org_id=org_id)


def read_session(*, session_id: str) -> Probe:
    """`GET /v2/sessions/{id}` — the factors, which are the only verdict there is.

    The read the fail-closed rule stands on: `session.factors.password.
    verifiedAt` is what "the password was right" means, and nothing in the
    create's own 201 says it.
    """
    return _session_probe("GET", f"{SESSIONS}/{session_id}")


def check_session(
    *,
    session_id: str,
    token: str,
    checks: Mapping[str, Any] | None = None,
    challenges: Mapping[str, Any] | None = None,
    org_id: str = "",
) -> Probe:
    """`PATCH /v2/sessions/{id}` — answer a factor, or ask for a challenge.

    **The answer's `sessionToken` is the one to carry forward, and it is not
    always there** (M8, measured, and the half the design's own sentence
    missed): a PATCH that VERIFIES something rotates the token, and a PATCH
    that verifies nothing — a challenge request — answers **no `sessionToken`
    at all** rather than the one it was sent. A ceremony that assumed a token
    in every answer would carry `None` forward on the second shape and then
    fail the next call as if the person had done something wrong.
    """
    payload: dict[str, Any] = {"sessionToken": token}
    if checks:
        payload["checks"] = dict(checks)
    if challenges:
        payload["challenges"] = dict(challenges)
    return _session_probe("PATCH", f"{SESSIONS}/{session_id}", payload, org_id=org_id)


def close_session(*, session_id: str, token: str) -> Probe:
    """`DELETE /v2/sessions/{id}` — ADR ident-10's half: what we open, we close.

    Called at EVERY exit of the ceremony, the refusals and the failures
    included, which is why it is the one function here the seam calls from a
    `finally`: a session left open is a credential-shaped object living for its
    ten-minute lifetime with nobody watching it.
    """
    return _session_probe("DELETE", f"{SESSIONS}/{session_id}", {"sessionToken": token})


def login_settings(*, org_id: str = "") -> Probe:
    """`GET /v2/settings/login` — whether this org asks for a second step.

    Read at ceremony time rather than cached, and deliberately: it is the
    org's own policy and a product that changed it in the console should see
    the change at the next sign-in, not at the next deploy. The two fields the
    seam reads are `forceMfa`/`forceMfaLocalOnly` (is a second step required)
    and `mfaInitSkipLifetime` (may the person say *Not now*, and for how long
    — a zero means the skip is not offered at all, which is why the frame's
    quiet action is conditional rather than always drawn).
    """
    query = f"?ctx.orgId={quote(org_id)}" if org_id else ""
    return _session_probe("GET", f"/settings/login{query}")


def password_complexity(*, org_id: str = "") -> Probe:
    """`GET /v2/settings/password/complexity` — the rule sentence a frame prints.

    **M11**, and the reason the Choose-your-password frame can say what the
    rules ARE instead of refusing a password and letting the person guess why.
    The answer is Zitadel's `settings` block — `minLength`, `requiresUppercase`
    and the rest — unjudged here: which of them become a sentence is the
    frame's, and a client that rendered prose would be composing copy in the
    module that holds the credential.
    """
    query = f"?ctx.orgId={quote(org_id)}" if org_id else ""
    return _session_probe("GET", f"/settings/password/complexity{query}")


def authentication_methods(*, user_id: str) -> Probe:
    """`GET /v2/users/{id}/authentication_methods` — what this person has enrolled.

    The read that decides between *One more step* and *Set up two-factor*, and
    the one that makes the `kind_unanswerable` sentence possible at all: a
    person whose only enrolled kind this deployment cannot deliver (an emailed
    code with no SMTP on the instance) has to be told that, and the alternative
    — handing off to the hosted page — is a 302 loop under login v2 (K10).
    """
    return _session_probe("GET", f"/users/{user_id}/authentication_methods")


def begin_totp_enrolment(*, user_id: str) -> Probe:
    """`POST /v2/users/{id}/totp` — the URI and secret the enrolment frame draws.

    The QR is rendered from the `uri` IN OUR TREE (design J2-c: no library, no
    fetch), and the `secret` is printed under it for a person whose camera is
    on the other device. Neither is a credential of ours and both are
    single-person, single-purpose — but both are in the answer's BODY, which
    `probe` never logs, and the seam never puts either in a log line.
    """
    return _session_probe("POST", f"/users/{user_id}/totp")


def confirm_totp_enrolment(*, user_id: str, code: str) -> Probe:
    """`POST /v2/users/{id}/totp/verify` — the six digits that finish enrolment.

    **NO UNDERSCORE, and the underscore cost a rung.** A6 reported this leg
    as unreachable head-lessly on the evidence of a 404 that every code
    produced — the current window, the two either side, and a deliberately
    wrong `000000`. The 404 was right and the reading was wrong: it is what
    this build answers for a PATH IT DOES NOT HAVE, and `/totp/_verify` is
    not a path it has. MEASURED side by side on v4.17.1, one person, one
    secret, one code:

        POST /v2/users/{id}/totp/_verify  -> 404 {"code":5,"message":"Not Found"}
        POST /v2/users/{id}/totp/verify   -> 200, and `authentication_methods`
                                             then reports …_TYPE_TOTP

    The sibling calls nearby DO carry the underscore (`/_search`,
    `/_verify` on other surfaces), which is exactly why the wrong spelling
    read as plausible. A 404 with no error id still means "we could not
    look" — `signin._judge`'s `not_on_this_build` arm is correct and stays —
    and what it was protecting against here was a typo of ours, which is
    the one thing a fail-closed reading cannot tell you.
    """
    return _session_probe("POST", f"/users/{user_id}/totp/verify", {"code": code})


# --- the invite road (design C-11; rung A7) ----------------------------------
#
# Two calls, both MEASURED against the pinned build (v4.17.1) on 2026-09-19 by
# hand, because `zitadel_measure` reaches the invite PAGE (C7), the code's
# expiry and length (C2) and the org's default redirect (M10) — but never the
# two verbs the road is actually made of. What the walk found:
#
#   POST /v2/users/{id}/invite_code/verify   {"verificationCode": "XJDXR7"}
#       200 {"details": {...}} on the live code.
#       400 COMMAND-Wgn4q "Code is invalid" — wrong, already used, or
#           superseded by a later mint. One id for all three, which is why the
#           page cannot tell them apart and does not try.
#       400 COMMAND-F5g2h "User could not be found" for an id that is not there.
#       The `_verify` spelling that the SEARCH verbs in this build use
#       answers **404** here, and so does
#       `/v2/users/human/{id}/invite_code/_verify`. The route is `verify`, and
#       it is written down because the plausible guess is the wrong one.
#       **The TOTP confirm is the same route shape and it was guessed wrong
#       anyway** — this note said so and a later rung spelled
#       `/totp/_verify`, read the 404 as "the build has no such leg", and
#       shipped an enrolment road that 503'd on a correct code. A note is
#       only a guard for whoever reads it.
#
#   POST /v2/users/{id}/password  {"newPassword": {"password", "changeRequired"}}
#       200 · 400 DOMAIN-HuJf6 "Password is too short" for one the org's
#       complexity policy refuses.
#
# **The second call carries no verification block, and that is the whole
# security shape of this road.** Zitadel's own `verificationCode` field on
# SetPassword is the PASSWORD-RESET code, not the invite code: handing it the
# invite code answers `400 COMMAND-2M9fs "Code not found"` (measured). What
# works is the machine PAT — and the PAT sets ANY person's password on a bare
# user id, with no code at all (measured on a second throwaway world). So the
# invite code is not something the platform checks on the write; it is
# something WE check before we make it, and `signin.set_invited_password` is
# the one place the two calls are allowed to happen, in that order.

#: Zitadel's stable id for "that invite code is not the live one" — wrong,
#: spent, or superseded. The seam reads it as `invite_gone`, never as an outage.
INVITE_CODE_INVALID = "COMMAND-Wgn4q"

#: And for a user id the platform does not know. Same road, same sentence: a
#: page that told a link-holder which of the two it was would be an oracle
#: over which user ids exist (the A9 posture).
INVITE_USER_UNKNOWN = "COMMAND-F5g2h"


def verify_invite_code(*, user_id: str, code: str) -> Probe:
    """`POST /v2/users/{id}/invite_code/verify` — is this link still the live one?

    **Single use.** Measured: the same code verified twice answers
    `COMMAND-Wgn4q` the second time, so this is called once, on the act, and
    never on a page render — a GET that verified would spend the code of
    anybody who opened their link and then reloaded it.
    """
    return _session_probe(
        "POST", f"/users/{user_id}/invite_code/verify", {"verificationCode": code}
    )


def set_first_password(*, user_id: str, password: str) -> Probe:
    """`POST /v2/users/{id}/password` — the password an invited person chose.

    `changeRequired` false, explicitly: they are choosing it now, and a
    deployment that asked them to change it on the next page would be asking
    twice for the one thing this screen exists to collect.

    **Never called without `verify_invite_code` answering 200 first**, for the
    reason in this section's header: the PAT authorises this write on its own.
    """
    return _session_probe(
        "POST",
        f"/users/{user_id}/password",
        {"newPassword": {"password": password, "changeRequired": False}},
    )


def read_human(*, user_id: str) -> Probe:
    """`GET /v2/users/{id}` — who the platform says a user id is.

    The read behind the invited person's address, and it is a read by ID
    because on this road there is no login name: the person has not typed
    anything yet and the link carries only what Zitadel minted.

    MEASURED shape (2026-09-19): `user.human.email.email` and
    `user.human.email.isVerified` — v2's spelling. The v1 search row
    `find_user` returns spells the same flag `isEmailVerified`, and a caller
    that read v1's name off this body would get `False` for everybody.
    """
    return _session_probe("GET", f"/users/{user_id}")


# --- Mode A: the OIDC auth request (design C-10; rung A8) --------------------
#
# The other half of the front door. Under `ours` an OIDC client's authorize
# does not land on the identity platform's page at all: with `loginVersion`
# declared (A2, A5) the platform answers the authorize with a 302 to
# `{baseUri}/login?authRequest=V2_…` — OUR page — and the sign-in is finished
# by handing the verified SESSION back to the auth request. What comes back is
# the client's own callback URL, with the code on it.
#
# MEASURED end to end against the pinned build (v4.17.1) on 2026-09-19, on a
# throwaway native client under this deployment's own project and a throwaway
# human in a throwaway organisation:
#
#   GET  /v2/oidc/auth_requests/{id}
#       200 {"authRequest": {"id", "creationDate", "clientId", "scope": [...],
#            "redirectUri", and OPTIONALLY "prompt": ["PROMPT_CREATE"|
#            "PROMPT_LOGIN"|"PROMPT_NONE"], "loginHint", "maxAge"}}
#       404 QUERY-Thee9 "Auth Request does not exist".
#       `prompt` is a LIST of enum names and is ABSENT when none was asked
#       for — not an empty list, which is why every reader here uses `or []`.
#   POST /v2/oidc/auth_requests/{id}  {"session": {"sessionId", "sessionToken"}}
#       200 {"callbackUrl": "<the client's redirectUri>?code=…&state=…"}
#       404 COMMAND-jae5P for an id that is not there,
#       400 COMMAND-Sx208nt "Auth Request has already been handled" for a
#       second finalize of one that is — a DIFFERENT id from the read's, which
#       is why both are named below rather than one being reused.
#       403 AUTH-AWfge when the machine credential lacks IAM_LOGIN_CLIENT (M2).
#   POST /v2/oidc/auth_requests/{id}  {"error": {"error", "errorDescription"}}
#       200 with a `callbackUrl` carrying `?error=…&error_description=…`.
#
# **M4, and it is the reason `REFUSE_*` below are spelled as enum members.**
# MEASURED both ways: `ERROR_REASON_ACCESS_DENIED` comes out of the callback as
# `error=access_denied`, and the RFC 6749 lowercase spelling `access_denied` —
# the one a reader of the OAuth spec would reach for — is accepted with a 200
# and DEGRADES to `error=server_error`. So the wrong spelling is not a refusal
# anybody sees here; it is a client being told the authorization server broke.

#: The auth-request surface, under `USER` (`/v2`). Named once: a typo would be
#: a 404 the door would read as "the link expired".
AUTH_REQUESTS = "/oidc/auth_requests"

#: Zitadel's stable id for "no such auth request" on the READ, and on the
#: WRITE. Two ids for one fact, measured — a door matching only one of them
#: reads the other as an outage and answers 503 for an expired link.
AUTH_REQUEST_GONE = "QUERY-Thee9"
AUTH_REQUEST_GONE_ON_WRITE = "COMMAND-jae5P"

#: And for a request that was already answered — a person who pressed the
#: browser's Back button onto a finished sign-in. Same sentence as gone: from
#: where the person stands there is nothing left to finish either way.
AUTH_REQUEST_ALREADY_HANDLED = "COMMAND-Sx208nt"

#: The one refusal reason this tree sends, in the ENUM spelling M4 measured.
#: `ERROR_REASON_ACCESS_DENIED` is what "the person did not finish signing in"
#: is in OAuth's own vocabulary, and it is the reason a client can act on.
REFUSE_ACCESS_DENIED = "ERROR_REASON_ACCESS_DENIED"

#: Zitadel's enum name for an OIDC client that asked for a registration
#: screen. ADR accounts-1: there is no sign-up door here, so the page says so
#: rather than pretending the client's request was honoured.
PROMPT_CREATE = "PROMPT_CREATE"


def read_auth_request(*, request_id: str) -> Probe:
    """`GET /v2/oidc/auth_requests/{id}` — what the client that sent them asked for.

    A read, and the page's whole knowledge of the journey it is standing in
    the middle of: which client, what scopes, whether a registration screen
    was asked for, and which address to prefill.
    """
    return _session_probe("GET", f"{AUTH_REQUESTS}/{request_id}")


def finalize_auth_request(*, request_id: str, session_id: str, session_token: str) -> Probe:
    """`POST /v2/oidc/auth_requests/{id}` — hand the verified session back.

    **The session must still be OPEN.** The answer is the client's callback
    URL with a code on it, and Zitadel mints that code against the session
    named here — so a ceremony that closed its session first (ADR ident-10's
    rule, which every other exit of `signin.py` obeys) has nothing to finalize
    with. That ordering is `signin._finish`'s, and it is the one place in this
    tree allowed to call this.

    Needs `IAM_LOGIN_CLIENT` on the machine credential, which `IAM_OWNER` does
    not carry (M2, measured): without it this answers `403 AUTH-AWfge` and the
    seam reads it as an outage, never as the person's fault.
    """
    return _session_probe(
        "POST",
        f"{AUTH_REQUESTS}/{request_id}",
        {"session": {"sessionId": session_id, "sessionToken": session_token}},
    )


def refuse_auth_request(*, request_id: str, reason: str, description: str) -> Probe:
    """`POST /v2/oidc/auth_requests/{id}` — tell the client it did not happen.

    The other half of the same verb, and it is a separate function rather than
    a flag because the two are opposite acts with opposite consequences and a
    boolean between them is one typo away from finalizing a ceremony that was
    refused.

    `reason` is an `ERROR_REASON_*` enum member (M4): the lowercase RFC
    spelling is accepted and silently degrades to `server_error` at the
    client, which is a client told we broke rather than a client told the
    person declined.
    """
    return _session_probe(
        "POST",
        f"{AUTH_REQUESTS}/{request_id}",
        {"error": {"error": reason, "errorDescription": description}},
    )


# --- M3 and M4: the Mode A round trip, measured (rung A8) --------------------


def check_mode_a(
    *,
    project_id: str,
    base_uri: str,
    login_name: str,
    password: str,
    org_id: str,
) -> dict[str, Any]:
    """**M3, M4 and M7**: the whole v2 round trip, on a throwaway client. **Unjudged.**

    One function for three items because they are one journey and one victim:
    an OIDC client has to exist and declare login v2 before either can be
    measured, and making two would be two objects on somebody's instance for
    one run.

    **It builds its own victim and never touches the real Web application**,
    for `check_login_version_redirects`'s reason and with its `finally`: the
    browser client is what every person signs in through, and a declaration
    change on it is the one breakage that locks a deployment out of its own
    front door. The throwaway is DEACTIVATED rather than deleted, so the
    instance's audit log carries the act rather than a gap.

    **No token, code or session token is in the return value.** M3 is about
    which CLAIMS a token carries, so what comes back is claim names and the
    two values the item is about; a function that handed a caller a live
    access token would be a credential in whatever that caller printed.

    Returns facts, never verdicts — `zitadel_measure` judges — with `trouble`
    naming the leg that could not be reached when one could not.
    """
    name = f"mode-a-check-{uuid4().hex[:12]}"
    redirect_uri = f"{base_uri.rstrip('/')}/mode-a-check/callback"
    seen: dict[str, Any] = {"redirect_uri": redirect_uri, "trouble": ""}
    made = ensure_native_application(
        project_id=project_id, name=name, redirect_uris=[redirect_uri], dev_mode=True
    )
    client_id = str(made.detail.get("clientId", ""))
    try:
        ensure_application_login_version(project_id=project_id, app_id=made.id, base_uri=base_uri)

        # --- M3: authorize -> session -> finalize -> token ------------------
        verifier = uuid4().hex + uuid4().hex
        request_id = _authorize_for_measurement(client_id, redirect_uri, verifier)
        seen["request_id"] = request_id
        if not request_id:
            seen["trouble"] = (
                "the authorize endpoint did not answer a v2 auth request for a client "
                "that declares loginVersion — M1 is the item that says why"
            )
            return seen

        opened = _session_probe(
            "POST",
            SESSIONS,
            {"checks": {"user": {"loginName": login_name}, "password": {"password": password}}},
            org_id=org_id,
        )
        if not opened.ok:
            seen["trouble"] = (
                f"POST /v2/sessions for the throwaway human answered {opened.status} "
                f"{opened.error_id or opened.text[:120]!r}"
            )
            return seen

        finished = finalize_auth_request(
            request_id=request_id,
            session_id=str(opened.body.get("sessionId", "")),
            session_token=str(opened.body.get("sessionToken", "")),
        )
        seen["finalize_status"] = finished.status
        seen["finalize_error_id"] = finished.error_id
        callback = str(finished.body.get("callbackUrl", ""))
        seen["callback_origin"] = callback.split("?", 1)[0]
        if not finished.ok or "code=" not in callback:
            seen["trouble"] = (
                f"the finalize answered {finished.status} "
                f"{finished.error_id or finished.text[:120]!r} — M2 is the item that "
                "says whether this credential may make one at all"
            )
            return seen

        seen |= _claims_of_the_code(
            callback=callback,
            client_id=client_id,
            redirect_uri=redirect_uri,
            verifier=verifier,
        )

        # --- M4: the refusal enum, both spellings ---------------------------
        for key, reason in (
            ("enum", REFUSE_ACCESS_DENIED),
            ("rfc", "access_denied"),
        ):
            fresh = _authorize_for_measurement(client_id, redirect_uri, uuid4().hex)
            if not fresh:
                seen[f"{key}_error"] = ""
                continue
            refused = refuse_auth_request(
                request_id=fresh, reason=reason, description="a measurement"
            )
            back = str(refused.body.get("callbackUrl", ""))
            seen[f"{key}_status"] = refused.status
            seen[f"{key}_error"] = _query_value(back, "error")

        seen |= _sso_after_finalize(
            client_id=client_id,
            redirect_uri=redirect_uri,
            login_name=login_name,
            password=password,
            org_id=org_id,
        )
        return seen
    finally:
        deactivate_application(project_id=project_id, app_id=made.id)


def _sso_after_finalize(
    *, client_id: str, redirect_uri: str, login_name: str, password: str, org_id: str
) -> dict[str, Any]:
    """**M7**: after a v2 round trip, does the BROWSER hold anything at the platform?

    The question J5's sign-out sentence rests on. Under `ours` the browser's
    only contact with the platform is the authorize redirect — the finalize is
    our server's call, on our connection — so if a person's next authorize
    still knows them, something was left in their cookie jar.

    Driven with ONE jar across three hops, which is why it is here rather
    than a `probe` in the measuring command: `_client()` mints a fresh client
    per call and keeps no cookies, and a measurement of a cookie needs the
    thing that holds cookies. A browser-shaped client, no PAT, because that
    is what a person has.

    `prompt=none` on the second authorize: the OAuth spelling of "answer
    without showing anybody anything". A code coming back means an SSO
    session exists; anything else means the person would type their password
    again, which is what the sign-out page promises.
    """
    verifier = uuid4().hex + uuid4().hex
    challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    found: dict[str, Any] = {}
    # **`_client()` held open across both hops, which is the jar.** One
    # `httpx.Client` keeps cookies for its own lifetime, so the two authorize
    # calls below share one — which is the whole measurement. The PAT rides
    # along and is ignored: `authorize_redirect` records that as measured,
    # and it is a browser endpoint. A bare client built here instead would
    # also be the one call in this module that no test could intercept.
    with _client() as browser:
        try:
            first = browser.get("/oauth/v2/authorize", params=params)
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel GET /oauth/v2/authorize failed: {error}") from error
        found["sso_cookies"] = sorted(browser.cookies.keys())
        request_id = _query_value(str(first.headers.get("location", "")), "authRequest")
        if not request_id:
            found["sso_trouble"] = "the authorize answered no v2 auth request to finish"
            return found

        opened = _session_probe(
            "POST",
            SESSIONS,
            {"checks": {"user": {"loginName": login_name}, "password": {"password": password}}},
            org_id=org_id,
        )
        finished = finalize_auth_request(
            request_id=request_id,
            session_id=str(opened.body.get("sessionId", "")),
            session_token=str(opened.body.get("sessionToken", "")),
        )
        if not finished.ok:
            found["sso_trouble"] = (
                f"the finalize answered {finished.status} {finished.error_id or ''}"
            )
            return found

        try:
            again = browser.get("/oauth/v2/authorize", params={**params, "prompt": "none"})
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel GET /oauth/v2/authorize failed: {error}") from error
    back = str(again.headers.get("location", ""))
    found["sso_cookies_after"] = sorted(browser.cookies.keys())
    found["sso_code"] = bool(_query_value(back, "code"))
    found["sso_error"] = _query_value(back, "error")
    found["sso_sent_to_sign_in"] = bool(_query_value(back, "authRequest"))
    return found


def _authorize_for_measurement(client_id: str, redirect_uri: str, verifier: str) -> str:
    """Start one authorize with PKCE and report the auth request id it answered.

    A separate helper from `authorize_redirect` above rather than a parameter
    on it: that one exists to report a `Location` for M1 to judge, and this
    one needs a code challenge because the code it is heading towards has to
    be spendable by a public client.
    """
    challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    with _client() as client:
        try:
            answer = client.get(
                "/oauth/v2/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel GET /oauth/v2/authorize failed: {error}") from error
    return _query_value(str(answer.headers.get("location", "")), "authRequest")


def _claims_of_the_code(
    *, callback: str, client_id: str, redirect_uri: str, verifier: str
) -> dict[str, Any]:
    """Spend the code and report WHICH CLAIMS came back. **Never the token.**

    M3's whole question is whether a token carries `client_id` and not `azp` —
    the claim the MCP resource server reads to know which client is calling.
    So what leaves here is claim NAMES plus those two values, and the tokens
    themselves are dropped on the floor of this function.
    """
    code = _query_value(callback, "code")
    with _client() as client:
        try:
            exchanged = client.post(
                "/oauth/v2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
                # **The one call in this module that is not JSON**, and the
                # header has to be said or `_client`'s default wins: httpx
                # form-encodes a `data=` body and then leaves the client's
                # `Content-Type: application/json` on it, and the build
                # answers `400 invalid_request "grant_type missing"` — a
                # parse failure that reads exactly like a missing parameter.
                # Measured, on the way to getting this line right.
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as error:
            raise ZitadelError(f"Zitadel POST /oauth/v2/token failed: {error}") from error
    found: dict[str, Any] = {"token_status": exchanged.status_code}
    if exchanged.status_code != 200:
        found["trouble"] = (
            f"the token exchange answered {exchanged.status_code} {exchanged.text[:160]!r}"
        )
        return found
    body = dict(exchanged.json())
    for kind in ("access_token", "id_token"):
        claims = _unverified_claims(str(body.get(kind, "")))
        found[f"{kind}_claims"] = sorted(claims)
        found[f"{kind}_client_id"] = claims.get("client_id")
        found[f"{kind}_azp"] = claims.get("azp")
    return found


def _unverified_claims(token: str) -> dict[str, Any]:
    """A JWT's payload, WITHOUT verifying it, for a measurement and nothing else.

    Unverified is correct here and nowhere else in this tree: the question is
    which claim names this build puts in a token, and verification is
    `apps/accounts/oauth.py`'s job on the door where it matters. A second
    verifier here would be a second opinion about token validity — the exact
    shape principle 9 refuses — and it would also answer the wrong question,
    because a token that failed verification still answers M3.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        parsed = json.loads(urlsafe_b64decode(payload))
    except (ValueError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _query_value(url: str, name: str) -> str:
    """One query parameter off a URL, or `""`."""
    return (parse_qs(urlsplit(url).query).get(name) or [""])[0]


# --- the reset road's one write (design J5; rung A11b) ----------------------
#
# MEASURED against the pinned build (v4.17.1) on 2026-09-19, on a throwaway
# human, with a real mail sink on the other end:
#
#   POST /v2/users/{id}/password_reset  {"sendLink": {}}
#       200 {"details": {...}} and a mail leaves the instance. An EMPTY
#       `sendLink` is the deliberate body: the channel, the template and the
#       link are the platform's, and a `notificationType` of ours would be
#       this tree having an opinion about somebody else's mail. Measured
#       three ways — `{"sendLink": {}}`, no body at all, and
#       `{"sendLink": {"notificationType": "NOTIFICATION_TYPE_Email"}}` — all
#       200, all delivered; the empty one is chosen because it says the least.
#       `{"returnCode": {}}` answers the code in the BODY and sends nothing,
#       which is M6's road and not this one: a code in our process is a
#       credential we would then have to transport.
#   404 COMMAND-SAF4f "User could not be found" for an id that is not there.
#
# **Where the mail lands is the platform's page, and that is measured too**
# (M6): `<issuer>/ui/login/password/init?authRequestID=&code=…&orgID=…&userID=…`
# with an EMPTY `authRequestID` — a mail has no application context, so the
# per-application login-v2 declaration cannot move it. The reset frame's
# sentence says so rather than implying the person comes back here to type a
# new password.

#: Zitadel's stable id for "no such person" on the reset request. Read by
#: nothing today and named anyway: the seam never reaches it, because it
#: looks the person up first and does not ask for a reset it knows will 404
#: — and a reader wondering why should find the id written down rather than
#: absent.
RESET_USER_UNKNOWN = "COMMAND-SAF4f"


def request_password_reset(*, user_id: str) -> Probe:
    """`POST /v2/users/{id}/password_reset` — ask the platform to mail its link.

    **Rule 25 is not broken here and it is worth saying why.** The product has
    exactly one sender, and this is not a second one: nothing of ours composes,
    addresses or delivers anything. What this does is tell the identity
    platform that one of ITS credentials needs resetting, and the platform
    mails its own page to its own user about its own password — the same
    division `create_invite_code` draws in the other direction, where
    `returnCode` keeps the delivery ours because the invitation is ours.
    """
    return _session_probe("POST", f"/users/{user_id}/password_reset", {"sendLink": {}})
