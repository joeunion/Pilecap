"""There is one credential store, and it is not this one (ADR ident-4).

Zitadel hosts every interactive authentication, including the passwords
of local users, and the owner closed the A-vs-B: two credential stores is the
shape where "disable this person" has to be done twice and is done once.

What that means concretely is asserted here rather than described: the login
POST is refused, and the URLs that could set or reset a password **do not
exist**. The second half is the stronger one. A URL that exists and refuses is
one `if` away from being a door again; a URL that does not resolve cannot be
reopened by accident, and `reverse()` raising is what a future change trips over.

`test_auth_over_the_wire.py` carries the other half of this criterion — the four
V1 CSRF probes — and is deliberately **not touched** by this change. Its subject is
`API_AUTH` and the session cookie, both of which this change leaves alone; that
it still passes unmodified is the regression net, and editing it to make it pass
would have cut the net.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import NoReverseMatch, reverse

from apps.accounts.models import SsoConnection
from apps.accounts.services import create_user
from apps.accounts.tests.stub_issuer import StubIssuer
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

# The login URL survives, GET-only: the page is how somebody reaches the IdP.
LOGIN_URL = "/accounts/login/"

# Every URL that could take, set or reset a local password. Each one used to
# resolve; none of them may now.
RETIRED_URL_NAMES = [
    "account_signup",
    "account_change_password",
    "account_set_password",
    "account_reset_password",
]


def test_posting_a_correct_password_is_refused_and_creates_no_session(api: Client) -> None:
    """The account is real and the password is right. That is the point.

    Answering "that password was correct" for an account whose authentication
    has moved elsewhere is most of what moving it was for.
    """
    person = create_user(email="staff@example.com", password="a-long-enough-password")

    response = api.post(
        LOGIN_URL,
        {"login": person.email, "password": "a-long-enough-password"},  # pragma: allowlist secret
    )

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session


def test_the_login_page_still_answers_a_get(api: Client) -> None:
    """GET survives on purpose: it is the page that offers the way in.

    Retiring the form is not retiring the page. Somebody arriving at
    `/accounts/login/` has to find a door, and a 404 there would be a product
    with no visible entrance.
    """
    assert api.get(LOGIN_URL).status_code == 200


@pytest.mark.parametrize("url_name", RETIRED_URL_NAMES)
def test_the_password_urls_do_not_exist(url_name: str) -> None:
    """Not "refuse" — *gone*. `SOCIALACCOUNT_ONLY` takes them out of the urlconf."""
    with pytest.raises(NoReverseMatch):
        reverse(url_name)


def test_the_login_page_offers_the_identity_provider(api: Client, stub_issuer: StubIssuer) -> None:
    """A page with no form and no button is a dead end.

    Asserted through the rendered page rather than through settings, because
    what a person can click is the property — and this is what fails the day the
    provider registration silently stops resolving.
    """
    page = api.get(LOGIN_URL).content.decode()

    assert "/accounts/oidc/zitadel/login/" in page


def test_the_page_does_not_enumerate_customer_connections(
    api: Client,
    stub_issuer: StubIssuer,
    sso_connection: SsoConnection,
    tenant: Tenant,
) -> None:
    """A login page listing every tenant's IdP is a customer list as buttons.

    `SocialAccountAdapter.list_apps` contributes nothing while allauth is
    enumerating, and this is the assertion that keeps it that way now that there
    is a static provider beside the per-connection ones.
    """
    page = api.get(LOGIN_URL).content.decode()

    assert sso_connection.name not in page
    assert sso_connection.provider_id not in page
    assert tenant.name not in page
