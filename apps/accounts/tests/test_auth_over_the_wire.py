"""`API_AUTH` as the four kinds of caller actually meet it, over a real request.

`django.test.Client` sets `_dont_enforce_csrf_checks` on every request it makes,
so the entire suite drives a stack with CSRF switched off — which is how a
bearer `POST` could answer **403 "CSRF check Failed"** over the wire while every
test in the tree was green (queue V4). Nothing here uses it. This builds the
real ASGI application `uvicorn` serves and speaks HTTP to it through
`httpx.ASGITransport`, exactly as `apps/core/tests/test_mcp.py` drives the
machine door: real middleware, real `CsrfViewMiddleware`, real session cookie,
real token.

**The four probes, and the fifth that provoked the change.** ninja runs the
authenticators in `API_AUTH` order and stops at the first that returns
something; `ninja.security.APIKeyCookie._get_key` **raises** `HttpError(403)`
when its CSRF check fails rather than declining, and `_run_authentication` turns
any exception into the response. So the cookie authenticator answers for callers
that never sent a cookie unless it declines first:

* **no credential at all** → 401. It was 403 "CSRF check Failed", which tells an
  anonymous client to go and find a CSRF token when what it needs is to
  authenticate, and implies a session it does not have. This is R1.
* **bearer, no cookie** → 201. The machine door; a token is not a cookie, so
  there is no cross-site request to forge (this is queue V1's regression, said
  here beside its siblings).
* **bad bearer** → 401, not a 403 about a cookie it never sent.
* **session, no CSRF token** → 403. Unchanged, and the whole point: this is the
  attack CSRF exists for.
* **session + CSRF token** → 201. The browser that plays by the rules.

The two session probes build their cookies the way the framework does —
`SessionStore` with the auth keys `login()` writes, and a server-issued
`csrftoken` fetched over the same connection. Nothing is forged in a way a
browser could not be.

This module names no domain app. It drives `/api/v1/widgets/` as a URL, because
authentication happens before any route function runs and the widget router is
the one write route the template always mounts — and `accounts` sits *below*
`apps.example` in the layer contract, so importing it here would cost an
exemption for a property that has nothing to do with widgets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant

# `transaction=True` because the request commits: the widget route's service
# registers work on `transaction.on_commit`, and a test that never commits would
# be driving a shorter stack than the wire does. `recorded_workflow_starts`
# (apps/conftest.py) is what keeps that commit from dialling Temporal.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

WIDGETS_URL = "/api/v1/widgets/"
BASE_URL = "http://testserver"

# Any GET through `CsrfViewMiddleware` leaves the cookie behind; the admin login
# page is the one page always mounted in this tree. Nothing about the admin is
# under test — it is a source of a real, server-issued token, which is the only
# kind worth asserting against.
CSRF_SOURCE_URL = "/admin/login/"


@asynccontextmanager
async def wire() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client speaking to the real application, with nothing switched off."""
    from config.asgi import build_application

    application = build_application()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real `ApiToken` for a real user with a real membership.

    A fixture rather than a line in the test body, and not for tidiness: the
    tests are `async def`, and the ORM refuses a synchronous query from inside a
    running event loop. Fixtures run outside it — the same shape
    `apps/core/tests/test_mcp.py` uses.
    """
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="over-the-wire", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def owner_session(owner: User) -> str:
    """A real session for the owner, written the way `django.contrib.auth.login` writes it.

    Not a shortcut past anything under test: the three keys below are exactly
    what `login()` puts in the session, and `AuthenticationMiddleware` reads
    them back through the ordinary code path. What this avoids is only the
    sign-in *form*, which belongs to allauth and is proved elsewhere.
    """
    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session[SESSION_KEY] = str(owner.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = owner.get_session_auth_hash()
    session.save()
    return str(session.session_key)


async def csrf_token(client: httpx.AsyncClient) -> str:
    """A CSRF token this server issued to this client, on this connection."""
    await client.get(CSRF_SOURCE_URL)
    token = client.cookies.get(settings.CSRF_COOKIE_NAME)
    assert token, "the server issued no CSRF cookie; the session probes would be void"
    return str(token)


def widget(name: str) -> dict[str, Any]:
    return {"name": name}


# --- R1: the caller with no credential at all --------------------------------


async def test_a_write_with_no_credential_at_all_is_a_401(
    tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """R1-1. Today's answer, before the second decline, was 403 "CSRF check Failed".

    That is the absent-answer this test is shaped around: a 403 says the caller
    is known and refused, and the message sends them looking for a token for a
    session they do not have. There is nothing to CSRF-protect when there is no
    cookie, so `SessionCookieAuth` declines and ninja reaches the end of
    `API_AUTH`.
    """
    async with wire() as client:
        response = await client.post(WIDGETS_URL, json=widget("nothing at all"))

    assert response.status_code == 401, response.text
    assert "CSRF" not in response.text


async def test_a_read_with_no_credential_at_all_is_a_401(tenant: Tenant, owner: User) -> None:
    """The same property on a safe method, where CSRF was never in play.

    A GET was already 401 — `CsrfViewMiddleware` exempts safe methods — so this
    is the half that did not change, and it is here so the pair says the door
    now answers one way about authentication rather than two.
    """
    async with wire() as client:
        response = await client.get(WIDGETS_URL)

    assert response.status_code == 401, response.text


# --- R1-2: the four probes ----------------------------------------------------


async def test_bearer_without_a_cookie_writes(bearer: str, recorded_workflow_starts: None) -> None:
    """The machine door. Queue V1's regression, kept beside its siblings."""
    async with wire() as client:
        response = await client.post(
            WIDGETS_URL,
            json=widget("Minted by a machine"),
            headers={"authorization": f"Bearer {bearer}"},
        )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Minted by a machine"


async def test_a_bad_bearer_is_a_401_not_a_403_about_a_cookie(
    tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """The token was rejected; nothing about a cookie was ever relevant."""
    async with wire() as client:
        response = await client.post(
            WIDGETS_URL,
            json=widget("Minted by nobody"),
            headers={"authorization": "Bearer djb_this-is-not-a-real-token"},
        )

    assert response.status_code == 401, response.text
    assert "CSRF" not in response.text


async def test_a_session_write_without_a_csrf_token_is_refused(
    tenant: Tenant, owner_session: str, recorded_workflow_starts: None
) -> None:
    """Unchanged, and the reason the other three declines are safe.

    A browser attaches its session cookie by itself, which is exactly the
    credential a cross-site form post rides on. This is that request, and it
    stays refused.
    """
    async with wire() as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, owner_session)
        response = await client.post(WIDGETS_URL, json=widget("Forged"))

    assert response.status_code == 403, response.text


async def test_a_session_write_with_a_csrf_token_writes(
    tenant: Tenant, owner_session: str, recorded_workflow_starts: None
) -> None:
    """The human door, playing by the rules."""
    async with wire() as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, owner_session)
        token = await csrf_token(client)
        response = await client.post(
            WIDGETS_URL,
            json=widget("Minted by a person"),
            headers={"x-csrftoken": token},
        )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Minted by a person"


# --- The decline is about the cookie, not about the method --------------------


async def test_a_cookie_that_is_not_a_session_is_still_nothing(
    tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """`SESSION_COOKIE_NAME` is a setting, so the decline reads the setting.

    A `POST` rather than a `GET`, because the `GET` was already 401 and would
    pass on the unfixed tree. A caller with *some* cookie — an analytics id, a
    consent banner, another Django application's session on the same domain —
    still has no session for this product, and must get the same 401 as the
    caller with none. Reading `request.COOKIES` for a hard-coded `"sessionid"`
    would have made this a 403 for every product that renamed the cookie.
    """
    async with wire() as client:
        client.cookies.set("some_other_products_sessionid", "irrelevant")
        response = await client.post(WIDGETS_URL, json=widget("nothing that counts"))

    assert response.status_code == 401, response.text
