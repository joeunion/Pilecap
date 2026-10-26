"""One request, one actor: `actor_from_request` keeps the actor it built.

The permission memo lives on the `Actor` instance (`Actor._permission_rows`),
so two instances in one request are two caches for one fact — and the second
pays the three statements again. A route and its paginator both ask
`actor_from_request(request)`; the request keeps the first answer
(`ACTOR_ATTR`), so they share one instance and one memo.

**What differs if this is false**: the first test reds on `is`, and the
example list's query pin (`apps/example/tests/test_api.py`,
`LIST_QUERY_BUDGET`) reds with the collection read twice.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from apps.core.actor import ACTOR_ATTR, actor_from_request
from apps.core.models import Tenant


def test_two_calls_on_one_request_answer_the_same_actor() -> None:
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    first = actor_from_request(request)

    assert actor_from_request(request) is first
    assert getattr(request, ACTOR_ATTR) is first


def test_two_requests_answer_two_actors() -> None:
    one = RequestFactory().get("/")
    two = RequestFactory().get("/")
    one.user = two.user = AnonymousUser()

    assert actor_from_request(one) is not actor_from_request(two)


def test_the_first_answer_stands_after_the_request_changes() -> None:
    """The memo is per request: the door sets user, tenant and hat before any route runs.

    Attributes changed on the request after the first call are not read again —
    asserted so a reader knows the contract, not because a door does this.
    """
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    first = actor_from_request(request)

    request.user = get_user_model()(email="late@example.com")
    request.tenant = Tenant(name="Late", slug="late")  # type: ignore[attr-defined]
    request.org = None  # type: ignore[attr-defined]

    again = actor_from_request(request)
    assert again is first
    assert again.user is None
    assert again.tenant is None
