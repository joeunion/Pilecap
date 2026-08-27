"""Every way this API says no, driven, and held to one envelope.

**The property.** A refusal on `/api/v1/**` is `{detail, code}` plus `errors`
when it names fields and `remedies` when there is something to do — built by
`core.exceptions.wire_refusal` and by nothing else. `code` is the half a client
branches on, and a refusal without one is a refusal a client has to parse
English to handle.

**Why a census and not seven tests.** The holes this fix closed were not
subtle refusals in unusual corners; they were the *first two refusals every
integrator meets*. `{"detail": "Unauthorized"}` (no code) and
`{"detail": "CSRF check Failed"}` (no code, and framework vocabulary on the
wire) had sat there since the API was mounted, green the whole time, because
every test that touched them asserted the status number and stopped. So the
instrument here drives one probe per refusal CLASS and puts all of them through
one assertion — `assert_one_envelope` — which is the thing that could not have
passed vacuously on the old tree.

**The hand list is the declared weakness.** Which refusal classes exist is
enumerated below by a human, because the door's refusals are an open set and no
derivation can name them. What is derived is the other half: `remedies` is
compared against the registry's own, so a probe whose door quietly composed a
body of its own fails even though its keys look right. House rule 41's own
census re-derives the registered-code half from the document.

**Two clients, deliberately.** `django.test.Client` sets
`_dont_enforce_csrf_checks` on every request it makes, so the CSRF probe — the
one refusal that only exists when CSRF is *on* — has to speak real HTTP to the
real ASGI application, exactly as `test_auth_over_the_wire.py` does. Everything
else runs through the ordinary client, which is the shorter, faster stack and
runs every piece of middleware that matters here.

**No declared blind spots left. Both of the ones this file used to carry are
closed, and each is probed below rather than described.**

1. **ninja's schema validation was outside this envelope BY DOCTRINE — now
   CLOSED, and probed below.** It answered **422** with
   `{"detail": [{"loc", "msg", "type"}]}`: a list where every other refusal is
   an object, no `code`, and pydantic's own vocabulary on the wire. That was
   the one shape `django-conventions` §6 blessed as a second shape, which is
   why this census could only declare it rather than fail on it — the hole was
   a decision, and only a decision could close it. The owner made this decision
   on the evidence that a typo'd field name returned a
   healthy 201 for a webhook subscribed to nothing, and that agents need one
   refusal parser. `config/api.py::on_schema_validation` now recomposes it
   into this grammar: the registered code `invalid_body`, a plain-language
   sentence, the field errors under `errors` in the caller's own field names,
   and the registry's remedies. The status is still 422, because what was wrong
   was the body and not the number. **§6 no longer blesses a second shape, and
   there is no longer one.** The strictness half of the same ruling — and the
   census that keeps every request body strict — is in
   `apps/core/tests/test_strict_bodies.py`; the probes here are this census's
   own, one per shape pydantic can refuse.
2. **A wrong method answered `text/html` — now CLOSED, and probed below.**
   `GET /api/v1/tokens/` (a POST-only path) used to return ninja's
   `PathView._not_allowed()`: status 405, `Content-Type: text/html`, the words
   "Method not allowed", no `code`. That was the same defect closed elsewhere for an
   unmatched *path*, still open for an unmatched *method*, and it was found by
   this census rather than reasoned about — the first draft of the cursor probe
   pointed at a POST-only URL and got markup back. It was handed up rather than
   patched here because the seam is a second wrap of a private ninja attribute
   (`PathView._sync_view` / `._async_view`, the only place holding both the
   request and the 405), which the lead sanctioned. The wrap lives in
   `config/api.py::_speak_the_method_refusal`; the rest of the property — the
   async half, the `Allow` header, and the fact that no *operation* documents a
   405 — is in `apps/core/tests/test_method_refusal.py`. The probe here is the
   census's own: the wrong method is now one more refusal class in one envelope.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from importlib import import_module
from typing import Any
from uuid import uuid4

import httpx
import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from ninja.throttling import BaseThrottle

from apps.accounts.auth import PageTokenMissing, Unauthenticated
from apps.accounts.models import User
from apps.accounts.services import issue_token, revoke_token
from apps.core.actor import actor_for
from apps.core.exceptions import REFUSALS, Remedy
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.services import invite_member
from apps.core.throttling import AuthRateThrottle, TenantRateThrottle

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"
TOKENS = "/api/v1/tokens/"
ACCEPT = "/api/v1/invitations/accept/"
BASE_URL = "http://testserver"

#: The four keys a refusal body may carry, and no fifth. `detail` and `code`
#: always; `errors` when the refusal names fields; `remedies` when there is
#: something the caller can do — which, for a registered code, is always.
ENVELOPE_KEYS = {"detail", "code", "errors", "remedies"}

#: Vocabulary that belongs to a framework or to our own tables and must never
#: reach a caller. `__all__` is Django's non-field key; the rest are the words
#: the closed holes were spelled with, kept here so a regression is caught by
#: the census rather than by somebody reading a body six months from now.
#:
#: The last three are pydantic's, added when the 422 joined this envelope
#: (SB-1). Recomposing that refusal means translating it, not forwarding it:
#: `extra_forbidden` is pydantic naming its own rule, and a caller who is told
#: their field is "extra forbidden" has been handed the validator's vocabulary
#: instead of an answer. `config/api.py::FIELD_SENTENCES` is where the
#: translation lives, and these entries are what stops a future type falling
#: through it unnoticed.
LEAKED_VOCABULARY = (
    "__all__",
    "CSRF check Failed",
    "Unauthorized",
    "Traceback",
    "extra_forbidden",
    "Value error,",
    "pydantic",
)


def as_wire(remedies: tuple[Remedy, ...]) -> list[dict[str, str]]:
    """The registry's remedies in the shape `wire_refusal` sends them."""
    return [{"label": r.label, "destination": r.destination} for r in remedies]


def assert_one_envelope(
    body: Any,
    *,
    code: str,
    contextual_remedies: bool = False,
) -> dict[str, Any]:
    """The whole property, in one place, for every probe below.

    `contextual_remedies` says this raise site passed its own `remedies=` and so
    is deliberately not the registry's list — the valve ADR core-5 defines. It
    still has to be a non-empty list of well-formed remedies; what it does not
    have to be is equal to the default.
    """
    assert isinstance(body, dict), f"the refusal body is {type(body).__name__}, not an object"
    assert set(body) <= ENVELOPE_KEYS, f"unexpected keys on the wire: {set(body) - ENVELOPE_KEYS}"
    assert body.get("code") == code, body
    assert code in REFUSALS, f"{code!r} reached the wire without a registry entry"

    detail = body.get("detail")
    assert isinstance(detail, str) and detail.strip(), body
    for leaked in LEAKED_VOCABULARY:
        assert leaked not in json.dumps(body), f"{leaked!r} reached the wire: {body}"

    remedies = body.get("remedies")
    assert remedies, f"{code!r} arrived with no remedies — a dead end with a status code"
    for entry in remedies:
        assert set(entry) == {"label", "destination"}, entry
        assert entry["label"].strip() and entry["destination"].strip(), entry
    if not contextual_remedies:
        # The bite: a door that composed its own body would drift here first.
        assert remedies == as_wire(REFUSALS[code].remedies), body

    errors = body.get("errors")
    if errors is not None:
        assert isinstance(errors, dict) and errors, body
        for field, messages in errors.items():
            assert field != "__all__", "a framework's non-field key is not a field name"
            assert messages and all(isinstance(m, str) for m in messages), body
    return dict(body)


def refusal_of(response: Any) -> Any:
    """The parsed body, having first insisted the response really is JSON.

    `Any` rather than `HttpResponse`: the test client hands back
    `_MonkeyPatchedWSGIResponse`, which django-stubs types as its own class
    rather than as a subclass, and narrowing here would cost a `type: ignore` at
    every one of the ten call sites to say nothing true.
    """
    content_type = response.headers.get("Content-Type", "")
    assert content_type.startswith("application/json"), (
        f"a refusal on the API answered {content_type!r} — a JSON client's first "
        f"wrong guess must not come back as a page of markup: {response.content[:200]!r}"
    )
    return json.loads(response.content)


# --- the probes: one per refusal class ----------------------------------------


def test_no_credential_at_all_is_a_coded_401(api: Client, tenant: Tenant, owner: User) -> None:
    """The very first refusal an integrator meets, and it had no `code`.

    ninja answers an operation no authenticator claimed with
    `AuthenticationError`, whose default handler sends `{"detail":
    "Unauthorized"}` — one framework word, nothing to branch on, nothing to do
    about it. It is a registered refusal now.
    """
    response = api.post(WIDGETS, {"name": "nobody"}, content_type="application/json")

    assert response.status_code == 401
    assert_one_envelope(refusal_of(response), code=Unauthenticated.code)


def test_a_revoked_token_is_the_same_coded_401(api: Client, tenant: Tenant, owner: User) -> None:
    """A withdrawn credential and no credential are one answer, on purpose.

    Same code, same body: a refusal that told the two apart would tell an
    anonymous caller which strings are real tokens.
    """
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="soon-revoked", actor=actor_for(user=owner, tenant=tenant)
    )
    revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )

    response = api.get(WIDGETS, headers={"Authorization": f"Bearer {plaintext}"})

    assert response.status_code == 401
    assert_one_envelope(refusal_of(response), code=Unauthenticated.code)


def test_a_row_that_is_not_there_is_a_coded_404(api: Client, tenant: Tenant, owner: User) -> None:
    response = api.get(f"{WIDGETS}{uuid4()}/", headers=_bearer(owner, tenant))

    assert response.status_code == 404
    assert_one_envelope(refusal_of(response), code="not_found")


def test_a_path_no_route_claims_is_a_coded_404(api: Client, tenant: Tenant, owner: User) -> None:
    """The fix, re-asserted from inside the census that now owns the property."""
    response = api.get("/api/v1/no-such-resource/", headers=_bearer(owner, tenant))

    assert response.status_code == 404
    assert_one_envelope(refusal_of(response), code="not_found")


def test_a_wrong_method_on_a_real_path_is_a_coded_405(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Found by this census: the same defect for a METHOD that was fixed
    for a PATH.

    `/api/v1/tokens/` answers `POST` and nothing else. A `GET` at it used to come
    back as `text/html` reading "Method not allowed" with no `code`; it is one
    more member of this envelope now, and `refusal_of` is what would notice a
    regression to markup.

    The `Allow` header is asserted here as well as in the rung's own module,
    because the header is the half a client is allowed to parse: an envelope
    that told a caller the method was wrong without telling it which method is
    right would be a prettier dead end than the markup it replaced.
    """
    response = api.get(TOKENS, headers=_bearer(owner, tenant))

    assert response.status_code == 405
    assert "POST" in response.headers["Allow"]
    body = assert_one_envelope(refusal_of(response), code="method_not_allowed")
    assert "POST" in body["detail"] and "GET" in body["detail"], body


def test_a_cursor_this_api_never_issued_is_a_coded_400(
    api: Client, tenant: Tenant, owner: User
) -> None:
    response = api.get(f"{WIDGETS}?cursor=not-a-cursor", headers=_bearer(owner, tenant))

    assert response.status_code == 400
    assert_one_envelope(refusal_of(response), code="invalid_cursor")


def test_a_token_that_is_not_scoped_for_this_is_a_coded_403(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The ceiling wrapper (ADR ident-7), in the census that surrounds it.

    Here because this change moved the authentication path underneath it: a
    composer change that displaced or short-circuited `_guard_the_ceiling` would
    show up as this probe answering 201 rather than 403.
    """
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="read-only",
        scopes=["widgets:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    response = api.post(
        WIDGETS,
        {"name": "past the ceiling"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {plaintext}"},
    )

    assert response.status_code == 403
    assert_one_envelope(refusal_of(response), code="insufficient_scope")


def test_accepting_an_invitation_you_do_not_need_is_a_coded_409(
    api: Client, tenant: Tenant, owner: User, member: User, root_org: Organization
) -> None:
    """Criterion 2, and the ugliest body on the old tree.

    A person already in the tenant clicking their invitation link a second time
    was answered **400 `invalid`** with *"Membership with this User, Tenant and
    Organization already exists."* under the key `__all__`: three of our table
    names, a framework key, and a status code claiming the request was malformed
    when it was well-formed and merely already true.
    """
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    _, token = invite_member(
        tenant=tenant, actor=acting, email=member.email, role=Membership.Role.MEMBER
    )
    api.force_login(member)

    response = api.post(ACCEPT, {"token": token}, content_type="application/json")

    assert response.status_code == 409
    body = assert_one_envelope(refusal_of(response), code="conflict", contextual_remedies=True)
    assert "errors" not in body, "a conflict names no fields; `errors` here is the old shape"
    assert tenant.name in body["detail"]


def test_a_token_nobody_issued_is_a_coded_404(api: Client, tenant: Tenant, owner: User) -> None:
    """Not-there and not-yours are one answer, and it is envelope-shaped."""
    api.force_login(owner)

    response = api.post(
        ACCEPT, {"token": "not-an-invitation-anybody-issued"}, content_type="application/json"
    )

    assert response.status_code == 404
    assert_one_envelope(refusal_of(response), code="not_found")


def test_a_write_that_does_not_hold_is_a_coded_400_with_real_field_names(
    api: Client, tenant: Tenant, owner: User, nomad: User, root_org: Organization
) -> None:
    """A service's own `Invalid`, with `errors` keyed by a name a client can point at.

    The expired invitation, because it is the one refusal in this census that
    genuinely carries `errors` — and the key is `invitation`, a word from the
    domain, which is the half `__all__` was failing on the accept path.
    """
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    invitation, token = invite_member(
        tenant=tenant, actor=acting, email=nomad.email, role=Membership.Role.MEMBER
    )
    Invitation.objects.filter(pk=invitation.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    api.force_login(nomad)

    response = api.post(ACCEPT, {"token": token}, content_type="application/json")

    assert response.status_code == 400
    body = assert_one_envelope(refusal_of(response), code="invalid")
    assert set(body["errors"]) == {"invitation"}


def test_too_many_requests_is_a_coded_429(
    api: Client, tenant: Tenant, owner: User, tiny_limit: None
) -> None:
    api.force_login(owner)
    assert api.get(WIDGETS).status_code == 200
    assert api.get(WIDGETS).status_code == 200

    response = api.get(WIDGETS)

    assert response.status_code == 429
    assert_one_envelope(refusal_of(response), code="rate_limited")


# --- the validation class, folded in by SB-1 ----------------------------------
# The hole this file used to DECLARE, now one more refusal class inside the one
# assertion. Parametrised rather than written five times because the point is
# that every shape pydantic can refuse comes out the same door: the shape of the
# failure is pydantic's business and the shape of the ANSWER is this product's.

#: One probe per way a request body can fail to be the shape an operation
#: accepts. The unknown field leads because it is the one the ruling was made
#: for: it used to be no refusal at all.
VALIDATION_BODIES: tuple[tuple[str, Any], ...] = (
    ("an unknown field", {"name": "nightly export", "scopes": ["*"], "scope": ["*"]}),
    ("a missing field", {"scopes": ["*"]}),
    ("the wrong type", {"name": "nightly export", "scopes": "widgets:read"}),
    ("several at once", {"scopes": 7, "nonsense": True}),
    ("not an object at all", ["nightly export"]),
)


@pytest.mark.parametrize(
    ("what", "body"), VALIDATION_BODIES, ids=[probe[0] for probe in VALIDATION_BODIES]
)
def test_a_body_that_is_not_the_shape_is_a_coded_422(
    api: Client, tenant: Tenant, owner: User, what: str, body: Any
) -> None:
    """Every validation refusal, through the same assertion as every other one.

    Driven at the mint because it is a route whose body a caller genuinely gets
    wrong — and it is session-authenticated, so the refusal being measured is
    the body's and not the credential's.

    This is the assertion that could not have passed before SB-1: each of these
    came back as `{"detail": [{"loc": [...], "msg": ..., "type": ...}]}` with no
    `code`, which `assert_one_envelope` rejects at its first line (the body is a
    dict) and again at its last (pydantic's vocabulary is in
    `LEAKED_VOCABULARY`).
    """
    api.force_login(owner)

    response = api.post(TOKENS, data=json.dumps(body), content_type="application/json")

    assert response.status_code == 422, (what, response.content)
    envelope = assert_one_envelope(refusal_of(response), code="invalid_body")
    # `errors` is not optional for this class: a refusal that says the shape is
    # wrong and cannot say which field is a refusal a caller has to guess at.
    assert envelope["errors"], (what, envelope)


def test_the_unknown_field_is_named_in_the_callers_own_words(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The F6 shape, at the mint: the field is named, and named as SENT.

    `scope` is the plausible misspelling of `scopes`, which is exactly the
    failure the ruling was made for — pydantic's default dropped it, the mint
    answered 201, and the token was issued with no ceiling the caller had asked
    for. The key in `errors` is the caller's own spelling and not the schema's,
    because a caller correcting a request searches for what they typed.
    """
    api.force_login(owner)

    response = api.post(
        TOKENS,
        data=json.dumps({"name": "nightly export", "scopes": ["*"], "scope": ["*"]}),
        content_type="application/json",
    )

    envelope = assert_one_envelope(refusal_of(response), code="invalid_body")
    assert "scope" in envelope["errors"], envelope
    assert any(
        "not part of this operation" in message for message in envelope["errors"]["scope"]
    ), envelope
    # And the sentence at the top names it too, so a person reading one line
    # gets the same answer an agent reading `errors` gets.
    assert "`scope`" in envelope["detail"], envelope


# --- the one probe that needs real HTTP ---------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_session_write_without_a_page_token_is_a_coded_403(
    tenant: Tenant, owner_session: str, recorded_workflow_starts: None
) -> None:
    """The other hole, and the only probe that cannot use the test client.

    `django.test.Client` switches CSRF enforcement off, so this refusal does not
    exist for it. Over real HTTP the answer used to be `{"detail": "CSRF check
    Failed"}`: no code, and a sentence about our middleware rather than about
    the caller's request. **The refusal itself is unchanged** — the check is
    Django's, it still runs, and this write is still refused. Only the envelope
    moved.
    """
    async with wire() as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, owner_session)
        response = await client.post(WIDGETS, json={"name": "forged"})

    assert response.status_code == 403, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert_one_envelope(response.json(), code=PageTokenMissing.code)


def test_the_accept_routes_bearer_prose_stays_fixed() -> None:
    """The other half of criterion 2: prose that was corrected stays corrected.

    The accept route's contract used to claim it was "the one operation here
    that a bearer token cannot perform", which was simply false — the route asks
    only `request.user.is_authenticated`, which a token satisfies, and a field test
    accepted an invitation with one and got a 200. What is true
    is the rule-17 exemption: there is no MCP twin. This fix changed the
    refusal that route makes, which is exactly the kind of edit that invites
    somebody to "tidy" the paragraph above it back to the memory of the design.
    So the corrected sentence is pinned, and the false one is pinned out.
    """
    from apps.core.api.docs import contract_of
    from apps.core.api.routes import accept_invitation_route

    contract = contract_of(accept_invitation_route)
    assert contract

    assert "not available as an MCP tool" in contract
    assert "a bearer token cannot perform" not in contract
    # The refusals this fix reshaped are the ones the contract advertises.
    assert "409 conflict" in contract
    assert "404 not_found" in contract


# --- the codes this fix added are declared, not invented ---------------------


@pytest.mark.parametrize("code", [Unauthenticated.code, PageTokenMissing.code])
def test_a_new_code_is_registered_with_a_fact_and_structured_remedies(code: str) -> None:
    """Criterion 5. `register_refusal` enforces this at import; this says so out loud.

    The registry is the reason a code is a contract rather than a string
    somebody typed, and the two added here are the first refusals most callers
    meet — so "it has a fact and it has remedies somebody can act on" is worth
    an assertion rather than an inference from the module having imported.
    """
    refusal = REFUSALS[code]

    assert refusal.boundary == "door", "both are decided at the edge, before any service"
    assert refusal.fact.strip() and refusal.remedy.strip()
    assert refusal.remedies, "a dead end with a status code on it"
    for remedy in refusal.remedies:
        assert isinstance(remedy, Remedy)
        assert remedy.label.strip() and remedy.destination.strip()
    # The internal half stays internal: `remedy` names our plumbing and the
    # `fact` may not.
    assert "authenticate_token" not in refusal.fact
    assert "APIKeyCookie" not in refusal.fact


def test_introspect_reports_the_codes_this_rung_added() -> None:
    """The machine door onto the refusal vocabulary shows them (criterion 5)."""
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("introspect", stdout=out)
    reported = {row["code"] for row in json.loads(out.getvalue())["refusals"]}

    assert {Unauthenticated.code, PageTokenMissing.code} <= reported


# --- fixtures and plumbing ----------------------------------------------------


def _bearer(user: User, tenant: Tenant) -> dict[str, str]:
    _, plaintext = issue_token(
        user=user,
        tenant=tenant,
        name=f"census-{uuid4().hex[:8]}",
        actor=actor_for(user=user, tenant=tenant),
    )
    return {"Authorization": f"Bearer {plaintext}"}


@asynccontextmanager
async def wire() -> AsyncIterator[httpx.AsyncClient]:
    """The real ASGI application `uvicorn` serves, with nothing switched off."""
    from config.asgi import build_application

    transport = httpx.ASGITransport(app=build_application())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def owner_session(owner: User) -> str:
    """A real session, written the way `django.contrib.auth.login` writes it."""
    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session[SESSION_KEY] = str(owner.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = owner.get_session_auth_hash()
    session.save()
    return str(session.session_key)


@pytest.fixture
def tiny_limit() -> Any:
    """Two a minute in both buckets, the way `test_rate_limit_headers.py` does it.

    Constructor rates rather than settings: ninja resolves the settings table
    once, at import, so a `settings` fixture would change nothing.
    """
    from config.api import api as live_api

    cache.clear()
    replaced: list[BaseThrottle] = [AuthRateThrottle("2/min"), TenantRateThrottle("2/min")]
    originals: list[tuple[Any, list[Any]]] = []
    for bound in live_api._get_bound_routers():
        for _path, view in bound.path_operations.items():
            for operation in view.operations:
                originals.append((operation, operation.throttle_objects))
                operation.throttle_objects = replaced
    yield
    for operation, throttles in originals:
        operation.throttle_objects = throttles
    cache.clear()
