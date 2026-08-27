"""The JSON 404 has to survive CSRF, and only a strict client can see it.

`django.test.Client` sets `_dont_enforce_csrf_checks` on every request it makes,
so the existing tests in `test_contract_docs.py` never meet
`CsrfViewMiddleware` at all. That is why they were green while the wire was not:
a cookieless `POST` to a path under `/api/v1/` that no route claims — a typo, a
retired spelling like `/api/v1/auth/realm` — was answered by
`CsrfViewMiddleware` with Django's HTML CSRF page, **before** the catch-all view
ever ran. A JSON client's first bad guess came back as markup with a 403 on it,
which is both the wrong status and the wrong language.

`Client(enforce_csrf_checks=True)` is the whole difference, exactly as
`apps/example/tests/test_doors_over_the_wire.py` uses it for the doors.

The fix is `csrf_exempt` on the mount in `config/urls.py`: the catch-all answers
404 to everything and touches nothing, so there is no state for a forged
cross-site request to change. The ninja API mounted ahead of it is already
exempt at the middleware level (ninja marks its own view `csrf_exempt` and does
the session door's CSRF check inside `SessionAuth`), so the catch-all was the
one plain Django view under the version segment — see
`test_the_catch_all_is_the_only_plain_view_under_the_api_prefix` below, which
holds that fact still.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver

from config import urls as root_urls

JSON = "application/json"

# The verifier's exact request (D2's stranger-run): a retired spelling, no
# trailing slash, no cookie jar, no credential of any kind.
RETIRED_SPELLING = "/api/v1/auth/realm"


def strict_client() -> Client:
    """A client that enforces CSRF, which the shared `api` fixture does not."""
    return Client(enforce_csrf_checks=True)


@pytest.mark.django_db
def test_a_cookieless_post_to_an_unmatched_path_answers_the_apis_json_404() -> None:
    """The red one. Pre-fix: 403 and `text/html` from `CsrfViewMiddleware`."""
    response = strict_client().post(RETIRED_SPELLING, data="{}", content_type=JSON)

    assert response.status_code == 404, response.content[:400]
    assert response["Content-Type"].startswith(JSON), response.content[:400]
    body = response.json()
    assert body["code"] == "not_found"
    assert body["detail"]
    assert body["remedies"]


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_every_unsafe_verb_on_an_unmatched_path_answers_json(method: str) -> None:
    """Not just POST: CSRF guards every unsafe method, so every one was HTML."""
    client = strict_client()
    call = getattr(client, method)
    response = call("/api/v1/nope/deeper/still", data="{}", content_type=JSON)

    assert response.status_code == 404, response.content[:400]
    assert response["Content-Type"].startswith(JSON), response.content[:400]
    assert response.json()["code"] == "not_found"


@pytest.mark.django_db
def test_the_html_csrf_page_is_gone_from_the_answer() -> None:
    """The property said the other way round: no markup, no 403, on the wire."""
    response = strict_client().post(RETIRED_SPELLING, data="{}", content_type=JSON)

    assert response.status_code != 403
    assert b"<html" not in response.content.lower()
    assert b"CSRF" not in response.content


@pytest.mark.django_db
def test_a_registered_route_still_does_its_own_csrf_under_a_strict_client() -> None:
    """The exemption is the catch-all's alone; the session door keeps all of CSRF.

    An unauthenticated write to a *registered* route is refused 401 by the
    API's own auth — in JSON — and nothing here loosened that. The sibling that
    proves the session door still refuses a token-less cookie write lives in
    `apps/example/tests/test_doors_over_the_wire.py`.
    """
    response = strict_client().post("/api/v1/widgets/", data="{}", content_type=JSON)

    assert response.status_code == 401, response.content[:400]
    assert response["Content-Type"].startswith(JSON)


@pytest.mark.django_db
def test_outside_the_api_django_still_answers_for_itself() -> None:
    """The exemption did not leak past the version segment."""
    response = strict_client().post("/definitely-not-the-api", data="{}", content_type=JSON)

    assert response.status_code in (403, 404)
    assert not response["Content-Type"].startswith(JSON)


def _views_under(prefix: str) -> list[Any]:
    """Every callable the root urlconf hangs under `prefix`, resolvers included."""
    found: list[Any] = []
    for entry in root_urls.urlpatterns:
        if not str(entry.pattern).startswith(prefix):
            continue
        if isinstance(entry, URLResolver):
            found.append(entry)
        elif isinstance(entry, URLPattern):
            found.append(entry.callback)
    return found


def test_the_catch_all_is_the_only_plain_view_under_the_api_prefix() -> None:
    """Criterion 5, held by a test rather than by a reading done once.

    Two things hang under the version segment: the ninja API (a resolver, whose
    own view ninja marks `csrf_exempt` and which checks CSRF inside
    `SessionAuth`), and this catch-all. If a third plain view is ever mounted
    here, it inherits the very defect this module closed — so this fails and says so.
    """
    under = _views_under(root_urls.API_PREFIX)
    resolvers = [entry for entry in under if isinstance(entry, URLResolver)]
    views = [entry for entry in under if not isinstance(entry, URLResolver)]

    assert len(resolvers) == 1, "the ninja API is no longer the one resolver under /api/v1/"
    assert len(views) == 1, f"a second plain view is mounted under the API prefix: {views}"
    assert getattr(views[0], "csrf_exempt", False) is True, (
        "the catch-all under the API prefix is not csrf_exempt; a cookieless "
        "unsafe request to a typo will come back as Django's HTML CSRF page"
    )
