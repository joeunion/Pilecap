"""The third question — "which session" — answered for the cookie door.

`core/context.py` names three questions every line has to answer: which
request, which session, which business chain. The first and the third were
bound by `ContextMiddleware` and always arrived; the second was bound there
too and **never** did, because `ContextMiddleware` is the OUTERMOST middleware
and Django's `SessionMiddleware` sits four entries below it: at the moment the
outermost bind runs, `request.session` does not exist yet, `getattr(..., None)`
is `None`, and `context.bind()` drops a `None` rather than storing it. No REST
or admin request has ever carried a `session_id`
(`deploy/observability/queries/o1-2c-the-session.sql` is O1′'s instrument for
exactly this, and it returned nothing).

The fix is a SECOND PASS, not a reorder. `ContextMiddleware` stays outermost —
it clears on the way out and binds `request_id` for everything, static files
and CORS preflights included, and the order comments in `settings/base.py` are
load-bearing. `TenantMiddleware` already runs below `SessionMiddleware` and
already re-binds `tenant_id`/`org_id`/`user_id` once the request has been
resolved; it is the middleware that CAN see the session, so it binds the
session too.

What these tests hold down:

* the bind happens after `TenantMiddleware` and equals `hash_session(key)`;
* a request with no session cookie binds nothing — `None` is the honest value
  for a token or a probe, not an invented id;
* the whole of one session's lines carry the SAME id, which is the only
  property the query cares about.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from apps.core import context
from apps.core.middleware import ContextMiddleware, TenantMiddleware

WIDGETS_URL = "/api/v1/widgets/"


def _stack(view: Callable[[HttpRequest], HttpResponse]) -> Any:
    """The real chain, in `settings.MIDDLEWARE`'s real order, around one view.

    Only the four entries that matter for this question, in the order
    `config/settings/base.py` lists them: context outermost, then the session,
    then authentication, then tenancy. Building it by hand rather than driving
    a URL is deliberate — the property under test is WHERE the bind happens,
    and a test that could not tell one order from another would prove nothing.

    Typed `Any` because Django's own middlewares declare the ASGI-capable
    `HttpResponseBase | Awaitable[...]` return, which is not the synchronous
    callable the next one up annotates — the chain is real, the annotation is
    the only thing loosened.
    """
    chain: Any = TenantMiddleware(view)
    chain = AuthenticationMiddleware(chain)
    chain = SessionMiddleware(chain)
    return ContextMiddleware(chain)


def _session_key(db: None) -> str:
    store = SessionStore()
    store["seen"] = True
    store.create()
    return str(store.session_key)


@pytest.mark.django_db
def test_a_cookie_session_is_bound_by_the_middleware_that_can_see_it() -> None:
    """After `TenantMiddleware`, `session_id` is the hash of the real key."""
    key = _session_key(None)
    seen: dict[str, Any] = {}

    def view(request: HttpRequest) -> HttpResponse:
        seen["session_id"] = context.value("session_id")
        seen["key"] = request.session.session_key
        return HttpResponse("ok")

    request = RequestFactory().get(WIDGETS_URL)
    request.COOKIES["sessionid"] = key
    _stack(view)(request)

    assert seen["key"] == key
    assert seen["session_id"] == context.hash_session(key)
    # The stored form is the hash and never the key itself: a session key is a
    # bearer credential and a log line is not the place for one.
    assert seen["session_id"] != key


@pytest.mark.django_db
def test_a_request_with_no_session_binds_nothing() -> None:
    """A token call and a health probe have no session. `None` is the answer."""
    seen: dict[str, Any] = {}

    def view(request: HttpRequest) -> HttpResponse:
        seen["session_id"] = context.value("session_id")
        return HttpResponse("ok")

    _stack(view)(RequestFactory().get(WIDGETS_URL))

    assert seen["session_id"] is None


@pytest.mark.django_db
def test_every_request_of_one_session_carries_the_same_id() -> None:
    """The query groups by `session_id`; two requests of one session are one row."""
    key = _session_key(None)
    seen: list[Any] = []

    def view(request: HttpRequest) -> HttpResponse:
        seen.append(context.value("session_id"))
        return HttpResponse("ok")

    for _ in range(3):
        request = RequestFactory().get(WIDGETS_URL)
        request.COOKIES["sessionid"] = key
        _stack(view)(request)

    assert len(set(seen)) == 1
    assert seen[0] == context.hash_session(key)
