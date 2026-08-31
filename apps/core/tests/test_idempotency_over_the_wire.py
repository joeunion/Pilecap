"""The idempotency scope, driven over real HTTP rather than through `Client`.

`django.test.Client` sets `_dont_enforce_csrf_checks` on every request it makes,
so a session-authenticated write through it never meets `CsrfViewMiddleware` —
and the walk this module is about *is* a session-authenticated write. So it
speaks HTTP to the real application through `httpx.ASGITransport`, the same way
`apps/accounts/tests/test_auth_over_the_wire.py` and `apps/core/tests/test_mcp.py`
do: the whole middleware stack, in order, with nothing switched off.

**What the walk is** (N100a-1). One person with memberships in two tenants and
one session credential posts the same body under the same `Idempotency-Key`
twice, sending no `X-Tenant` either time. Between the two calls their default
membership moves from the first tenant to the second. Nothing the client sends
changes; the tenant the door resolves does.

Before the fix, the second call was answered `201 Idempotent-Replayed: true`
carrying the *first* tenant's widget — one hat handed the other hat's body,
because `scope_for` hashed the header's spelling (`""` twice) instead of the
resolved tenant. After it, the second call is the fresh request it always was.

The same walk was run against a real uvicorn process on the baseline and again
after the change; this module is that walk where CI can keep running it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for, system_actor
from apps.core.idempotency import HEADER, REPLAYED_HEADER, IdempotencyRecord
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership
from apps.example.models import Widget

# `transaction=True` because the request commits: the widget route's service
# registers work on `transaction.on_commit`, and a test that never committed
# would be driving a shorter stack than the wire does. `recorded_workflow_starts`
# (apps/conftest.py) is what keeps that commit from dialling Temporal.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

WIDGETS_URL = "/api/v1/widgets/"
BASE_URL = "http://testserver"
CSRF_SOURCE_URL = "/admin/login/"
TENANT_HEADER = "X-Tenant"


@asynccontextmanager
async def wire() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client speaking to the real application, with nothing switched off."""
    from config.asgi import build_application

    transport = httpx.ASGITransport(app=build_application())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def two_hats(owner: User, tenant: Tenant, other_tenant: Tenant) -> User:
    """One person, memberships in two tenants, the first one their default.

    A fixture and not a line in the test body because the tests are `async def`
    and the ORM refuses a synchronous query from inside a running event loop.
    """
    add_membership(
        user=owner, tenant=other_tenant, is_default=False, actor=system_actor(tenant=other_tenant)
    )
    return owner


@pytest.fixture
def session_cookie(two_hats: User) -> str:
    """A real session, written the way `django.contrib.auth.login` writes it.

    Not a shortcut past anything under test: these three keys are exactly what
    `login()` puts in the session and `AuthenticationMiddleware` reads them back
    through the ordinary code path. What it skips is the sign-in *form*, which
    belongs to allauth and is proved elsewhere.
    """
    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session[SESSION_KEY] = str(two_hats.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = two_hats.get_session_auth_hash()
    session.save()
    return str(session.session_key)


@pytest.fixture
def unpinned_token(two_hats: User) -> str:
    """A bearer token with no tenant pin — it resolves its tenant like a person."""
    _, plaintext = issue_token(
        user=two_hats,
        tenant=None,
        name="over-the-wire-unpinned",
        actor=actor_for(user=two_hats, tenant=None),
    )
    return plaintext


async def csrf_token(client: httpx.AsyncClient) -> str:
    """A CSRF token this server issued to this client, on this connection."""
    await client.get(CSRF_SOURCE_URL)
    token = client.cookies.get(settings.CSRF_COOKIE_NAME)
    assert token, "the server issued no CSRF cookie; the session probes would be void"
    return str(token)


async def post_widget(
    client: httpx.AsyncClient,
    *,
    name: str,
    key: str,
    session: str | None = None,
    bearer: str | None = None,
    tenant_slug: str | None = None,
    page_token: bool = True,
) -> httpx.Response:
    """One write, spelled the way a real client spells it.

    `page_token=False` is the broken-credential spelling this module is about: a real
    session cookie and no `X-CSRFToken`, which is what a browser client sends
    when its token has rotated or its page was served before the cookie was.
    """
    headers: dict[str, str] = {HEADER: key}
    if tenant_slug is not None:
        headers[TENANT_HEADER] = tenant_slug
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if session is not None:
        client.cookies.set(settings.SESSION_COOKIE_NAME, session)
        token = await csrf_token(client)
        if page_token:
            headers["X-CSRFToken"] = token
    return await client.post(WIDGETS_URL, json={"name": name}, headers=headers)


@sync_to_async
def flip_default_membership(*, user: User, tenant: Tenant) -> None:
    """Move which tenant this person lands in when they name none.

    `add_membership`'s own rule applied to a membership that already exists: at
    most one membership per user is the default, and asking for a second moves
    the flag. Nothing here grants a role, so the escalation wall is untouched.
    """
    Membership.objects.filter(user_id=user.pk, is_default=True).update(is_default=False)
    Membership.objects.filter(user_id=user.pk, tenant=tenant).update(is_default=True)


@sync_to_async
def widgets_in(tenant: Tenant) -> int:
    return int(Widget.objects.for_tenant(tenant).count())


@sync_to_async
def record_tenants(key: str) -> list[Any]:
    return sorted(
        str(value)
        for value in IdempotencyRecord.objects.filter(key=key).values_list("tenant_id", flat=True)
    )


async def test_a_flipped_default_is_a_fresh_request_not_the_other_hats_body(
    session_cookie: str,
    two_hats: User,
    tenant: Tenant,
    other_tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    """N100a-1, over the wire. The red walk, and what it answers now.

    On the baseline the second response carried `Idempotent-Replayed: true` and
    the first tenant's widget id — proven against a running uvicorn before this
    module existed. Here it is the fresh 201 in the second tenant it always
    should have been.
    """
    async with wire() as client:
        first = await post_widget(client, name="Same body", key="wire-flip", session=session_cookie)
        assert first.status_code == 201, first.text
        assert first.headers.get(REPLAYED_HEADER) is None
        assert first.json()["tenant_id"] == str(tenant.pk)

        await flip_default_membership(user=two_hats, tenant=other_tenant)

        second = await post_widget(
            client, name="Same body", key="wire-flip", session=session_cookie
        )

    assert second.status_code == 201, second.text
    assert second.headers.get(REPLAYED_HEADER) is None
    assert second.json()["tenant_id"] == str(other_tenant.pk)
    assert second.json()["id"] != first.json()["id"]

    # One widget in each tenant, and the first tenant's record left as it was.
    assert await widgets_in(tenant) == 1
    assert await widgets_in(other_tenant) == 1
    assert await record_tenants("wire-flip") == sorted([str(tenant.pk), str(other_tenant.pk)])


async def test_the_single_tenant_client_that_never_sends_the_header_still_replays(
    session_cookie: str,
    owner: User,
    tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    """N100a-3, over the wire. The branch the steer refused to take.

    Refusing an absent `X-Tenant` would have closed the hole by making an
    optional header mandatory — every client that never needed it breaks. Two
    identical writes, no header either time, one row and a replay.
    """
    async with wire() as client:
        first = await post_widget(
            client, name="Only one", key="wire-single", session=session_cookie
        )
        assert first.status_code == 201, first.text

        second = await post_widget(
            client, name="Only one", key="wire-single", session=session_cookie
        )

    assert second.status_code == 201, second.text
    assert second.headers[REPLAYED_HEADER] == "true"
    assert second.json() == first.json()
    assert await widgets_in(tenant) == 1


async def test_a_bearer_that_names_no_tenant_gets_its_own_answer_per_hat(
    unpinned_token: str,
    two_hats: User,
    tenant: Tenant,
    other_tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    """Part 2 criterion (2), over the wire: the last population, closed.

    The walk the report pasted against a running uvicorn: a bearer credential
    that sends **no** `X-Tenant` either time, with the default membership moved
    between the calls. On efde532 the second response came back
    `Idempotent-Replayed: true` carrying the first hat's widget, because the
    tenant that credential lands in is decided inside the view off an
    `ApiToken` row `core` may not read. The seam — `register_tenant_resolver`,
    registered by `AccountsConfig.ready()` — is what lets the scope know it in
    time.
    """
    async with wire() as client:
        first = await post_widget(client, name="Machine", key="wire-blind", bearer=unpinned_token)
        assert first.status_code == 201, first.text
        assert first.headers.get(REPLAYED_HEADER) is None
        assert first.json()["tenant_id"] == str(tenant.pk)

        await flip_default_membership(user=two_hats, tenant=other_tenant)

        second = await post_widget(client, name="Machine", key="wire-blind", bearer=unpinned_token)

    assert second.status_code == 201, second.text
    assert second.headers.get(REPLAYED_HEADER) is None
    assert second.json()["tenant_id"] == str(other_tenant.pk)
    assert second.json()["id"] != first.json()["id"]

    assert await widgets_in(tenant) == 1
    assert await widgets_in(other_tenant) == 1
    assert await record_tenants("wire-blind") == sorted([str(tenant.pk), str(other_tenant.pk)])


async def test_a_bearer_token_switching_hats_by_header_gets_two_answers(
    unpinned_token: str,
    tenant: Tenant,
    other_tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    """N100a-2, the machine door, over the wire.

    The token authenticates *inside* the view, so this middleware has to decide
    whether to claim or replay before anybody knows who is calling. `X-Tenant`
    names the hat, the scope carries that tenant as a row, and the stored FK is
    what stops the record crossing when the third call comes back to the first.
    """
    async with wire() as client:
        first = await post_widget(
            client, name="Robot", key="wire-hats", bearer=unpinned_token, tenant_slug=tenant.slug
        )
        assert first.status_code == 201, first.text
        assert first.headers.get(REPLAYED_HEADER) is None

        second = await post_widget(
            client,
            name="Robot",
            key="wire-hats",
            bearer=unpinned_token,
            tenant_slug=other_tenant.slug,
        )
        assert second.status_code == 201, second.text
        assert second.headers.get(REPLAYED_HEADER) is None
        assert second.json()["tenant_id"] == str(other_tenant.pk)

        again = await post_widget(
            client, name="Robot", key="wire-hats", bearer=unpinned_token, tenant_slug=tenant.slug
        )

    assert again.headers[REPLAYED_HEADER] == "true"
    assert again.json() == first.json()
    assert await widgets_in(tenant) == 1
    assert await widgets_in(other_tenant) == 1


async def test_a_fixed_credential_reaches_the_write_its_key_was_refused_for(
    session_cookie: str,
    owner: User,
    tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    """The poisoned-key case reproduced over the wire — **ADR core-23**.

    A signed-in browser write with no `X-CSRFToken` is refused
    `403 page_token_missing` (`apps/accounts/auth.py`), before any route runs and
    with nothing written. The client fixes the credential and retries with the
    identical key and body — the exact retry `Idempotency-Key` exists to make
    safe.

    **The red, on the baseline:** the second call came back `403` with
    `Idempotent-Replayed: true`, and the widget could not be created under that
    key for the record's whole TTL. The credential is outside the fingerprint
    (`method + path + raw body`), so the key never named the thing that was
    wrong; the refusal was the door's, and the door refused before the key was
    spent.
    """
    async with wire() as client:
        refused = await post_widget(
            client,
            name="After the fix",
            key="wire-fixed-fault",
            session=session_cookie,
            page_token=False,
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "page_token_missing"
        assert refused.headers.get(REPLAYED_HEADER) is None

        retried = await post_widget(
            client, name="After the fix", key="wire-fixed-fault", session=session_cookie
        )

    assert retried.status_code == 201, retried.text
    assert retried.headers.get(REPLAYED_HEADER) is None
    assert await widgets_in(tenant) == 1

    # And the key now holds the answer it should always have held: the write.
    async with wire() as client:
        again = await post_widget(
            client, name="After the fix", key="wire-fixed-fault", session=session_cookie
        )
    assert again.status_code == 201, again.text
    assert again.headers[REPLAYED_HEADER] == "true"
    assert again.json() == retried.json()
    assert await widgets_in(tenant) == 1
