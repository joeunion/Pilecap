"""The measurement kit: what `manage.py zitadel_measure` asks the running build, never the suite.

It reaches Zitadel through `apps.accounts.zitadel` only (rule 27's kit exemption; ADR ident-5(a)).
"""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx

from apps.accounts import zitadel
from apps.core.log import get_logger

log = get_logger(__name__)


def deactivate_application(*, project_id: str, app_id: str) -> zitadel.Resource:
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
        zitadel._call("POST", f"/projects/{project_id}/apps/{app_id}/_deactivate", {})
    except zitadel.ZitadelError as error:
        if not zitadel._is_already_in_that_state(error):
            raise
        return zitadel.Resource(id=app_id, created=False)
    log.info("accounts.zitadel.application_deactivated", application_id=app_id)
    return zitadel.Resource(id=app_id, created=True)


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
    with zitadel._client() as client:
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
            raise zitadel.ZitadelError(
                f"Zitadel GET /oauth/v2/authorize failed: {error}"
            ) from error
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
    made = zitadel.ensure_native_application(
        project_id=project_id, name=name, redirect_uris=[redirect_uri], dev_mode=True
    )
    client_id = str(made.detail.get("clientId", ""))
    try:
        undeclared = authorize_redirect(client_id=client_id, redirect_uri=redirect_uri)
        zitadel.ensure_application_login_version(
            project_id=project_id, app_id=made.id, base_uri=base_uri
        )
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
    user = zitadel.machine_user()
    user_id = str(user.get("id", ""))
    roles = zitadel.instance_member_roles(user_id=user_id) if user_id else []
    return {
        "user_id": user_id,
        "login_name": str(user.get("preferredLoginName", "") or user.get("userName", "")),
        "roles": roles,
        "may_finalize": zitadel.LOGIN_CLIENT_ROLE in roles,
    }


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
    answer = zitadel.probe("GET", f"/{name}.swagger.json", prefix=SWAGGER_PATH)
    if not answer.ok or not answer.body:
        raise zitadel.ZitadelError(
            f"Zitadel served no readable {name} swagger document at "
            f"{SWAGGER_PATH}/{name}.swagger.json (status {answer.status})"
        )
    return answer.body


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
    made = zitadel.ensure_native_application(
        project_id=project_id, name=name, redirect_uris=[redirect_uri], dev_mode=True
    )
    client_id = str(made.detail.get("clientId", ""))
    try:
        zitadel.ensure_application_login_version(
            project_id=project_id, app_id=made.id, base_uri=base_uri
        )

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

        opened = zitadel._session_probe(
            "POST",
            zitadel.SESSIONS,
            {"checks": {"user": {"loginName": login_name}, "password": {"password": password}}},
            org_id=org_id,
        )
        if not opened.ok:
            seen["trouble"] = (
                f"POST /v2/sessions for the throwaway human answered {opened.status} "
                f"{opened.error_id or opened.text[:120]!r}"
            )
            return seen

        finished = zitadel.finalize_auth_request(
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
            ("enum", zitadel.REFUSE_ACCESS_DENIED),
            ("rfc", "access_denied"),
        ):
            fresh = _authorize_for_measurement(client_id, redirect_uri, uuid4().hex)
            if not fresh:
                seen[f"{key}_error"] = ""
                continue
            refused = zitadel.refuse_auth_request(
                request_id=fresh, reason=reason, description="a measurement"
            )
            back = str(refused.body.get("callbackUrl", ""))
            seen[f"{key}_status"] = refused.status
            seen[f"{key}_error"] = query_value(back, "error")

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
    with zitadel._client() as browser:
        try:
            first = browser.get("/oauth/v2/authorize", params=params)
        except httpx.HTTPError as error:
            raise zitadel.ZitadelError(
                f"Zitadel GET /oauth/v2/authorize failed: {error}"
            ) from error
        found["sso_cookies"] = sorted(browser.cookies.keys())
        request_id = query_value(str(first.headers.get("location", "")), "authRequest")
        if not request_id:
            found["sso_trouble"] = "the authorize answered no v2 auth request to finish"
            return found

        opened = zitadel._session_probe(
            "POST",
            zitadel.SESSIONS,
            {"checks": {"user": {"loginName": login_name}, "password": {"password": password}}},
            org_id=org_id,
        )
        finished = zitadel.finalize_auth_request(
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
            raise zitadel.ZitadelError(
                f"Zitadel GET /oauth/v2/authorize failed: {error}"
            ) from error
    back = str(again.headers.get("location", ""))
    found["sso_cookies_after"] = sorted(browser.cookies.keys())
    found["sso_code"] = bool(query_value(back, "code"))
    found["sso_error"] = query_value(back, "error")
    found["sso_sent_to_sign_in"] = bool(query_value(back, "authRequest"))
    return found


def _authorize_for_measurement(client_id: str, redirect_uri: str, verifier: str) -> str:
    """Start one authorize with PKCE and report the auth request id it answered.

    A separate helper from `authorize_redirect` above rather than a parameter
    on it: that one exists to report a `Location` for M1 to judge, and this
    one needs a code challenge because the code it is heading towards has to
    be spendable by a public client.
    """
    challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    with zitadel._client() as client:
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
            raise zitadel.ZitadelError(
                f"Zitadel GET /oauth/v2/authorize failed: {error}"
            ) from error
    return query_value(str(answer.headers.get("location", "")), "authRequest")


def _claims_of_the_code(
    *, callback: str, client_id: str, redirect_uri: str, verifier: str
) -> dict[str, Any]:
    """Spend the code and report WHICH CLAIMS came back. **Never the token.**

    M3's whole question is whether a token carries `client_id` and not `azp` —
    the claim the MCP resource server reads to know which client is calling.
    So what leaves here is claim NAMES plus those two values, and the tokens
    themselves are dropped on the floor of this function.
    """
    code = query_value(callback, "code")
    with zitadel._client() as client:
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
            raise zitadel.ZitadelError(f"Zitadel POST /oauth/v2/token failed: {error}") from error
    found: dict[str, Any] = {"token_status": exchanged.status_code}
    if exchanged.status_code != 200:
        found["trouble"] = (
            f"the token exchange answered {exchanged.status_code} {exchanged.text[:160]!r}"
        )
        return found
    body = dict(exchanged.json())
    for kind in ("access_token", "id_token"):
        claims = unverified_claims(str(body.get(kind, "")))
        found[f"{kind}_claims"] = sorted(claims)
        found[f"{kind}_client_id"] = claims.get("client_id")
        found[f"{kind}_azp"] = claims.get("azp")
    return found


def unverified_claims(token: str) -> dict[str, Any]:
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


def query_value(url: str, name: str) -> str:
    """One query parameter off a URL, or `""`."""
    return (parse_qs(urlsplit(url).query).get(name) or [""])[0]
