"""`/welcome/` — where a completed sign-in lands, and what it is allowed to be.

`LOGIN_REDIRECT_URL` was `"/"`, so the last screen of the sign-in chain was the
door index: a monospace directory listing addressed to an operator, handed to a
person who had just finished authenticating — the landing defect the entrance
survey measured at `config/settings/base.py`. This is the page that replaced it,
and there are four separate claims about it worth a test:

* it demands a credential, and an anonymous request is a redirect rather than a
  thinner render;
* it reports what the request actually RESOLVED to — the person, the tenant, the
  acting hat and the role that hat carries — which is the only reason a
  placeholder is worth shipping at all: the four facts it prints are the four
  that go wrong invisibly, and `X-Org` changing the answer is the property that
  proves it is reading the request rather than the user;
* it is SHADOWED, not configured: a product mounting its own route at the same
  path wins by ordinary URL resolution, with nothing deleted and no setting
  touched;
* it is the CSRF bootstrap page the settings comment names. That sentence used
  to name a page that did not exist anywhere in the tree — the
  reader-less-declaration class; this test is what stops it going back to naming
  nobody.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import resolve, reverse

from apps.accounts.models import User
from apps.core.actor import actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import create_organization
from apps.core.tests import shadowed_welcome_urls

pytestmark = pytest.mark.django_db

WELCOME = "/welcome/"
SHADOWING_URLCONF = "apps.core.tests.shadowed_welcome_urls"


# --- it is where sign-in lands ------------------------------------------------


def test_login_redirect_is_the_landing_and_it_resolves() -> None:
    """The setting and the mount are pinned to each other, in both directions.

    A `LOGIN_REDIRECT_URL` that resolves to nothing is a 404 after a successful
    sign-in — the one moment a person is least able to tell whether the failure
    is theirs.
    """
    assert settings.LOGIN_REDIRECT_URL == WELCOME
    assert reverse("welcome") == WELCOME
    assert resolve(WELCOME).view_name == "welcome"


def test_a_clone_with_no_front_end_pays_nothing() -> None:
    """`PRODUCT_BASE_URL` defaults to `PUBLIC_BASE_URL`, so the landing is local.

    The other half of the derivation — a product that HAS a front end and says
    where — is proved by importing the settings module under that environment,
    in `apps/core/tests/test_settings.py`, where every other settings derivation
    is proved the same way.
    """
    assert settings.PRODUCT_BASE_URL == settings.PUBLIC_BASE_URL
    assert settings.LOGIN_REDIRECT_URL == WELCOME


# --- it demands a credential --------------------------------------------------


def test_anonymous_is_redirected_to_sign_in(client: Client) -> None:
    """Not a 200 with less on it: a person who is not signed in has one move."""
    response = client.get(WELCOME)
    assert response.status_code == 302
    assert str(settings.LOGIN_URL) in response["Location"]


def test_signed_in_answers_html(client: Client, owner: User) -> None:
    client.force_login(owner)
    response = client.get(WELCOME)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")


# --- it reports what the request resolved to ----------------------------------


def test_it_names_the_person(client: Client, owner: User) -> None:
    client.force_login(owner)
    assert owner.email in client.get(WELCOME).content.decode()


def test_it_names_the_tenant_and_the_hat(
    client: Client, owner: User, tenant: Tenant, root_org: Organization
) -> None:
    """The acting hat, resolved by the one function all four doors call."""
    client.force_login(owner)
    body = client.get(WELCOME).content.decode()
    assert tenant.name in body
    assert root_org.slug in body


def test_it_names_the_role_that_hat_carries(client: Client, owner: User) -> None:
    client.force_login(owner)
    assert "<dd>owner</dd>" in client.get(WELCOME).content.decode()


def test_the_hat_follows_the_header(
    client: Client, owner: User, tenant: Tenant, root_org: Organization
) -> None:
    """`X-Org` changes the answer — so the page is reading the REQUEST.

    Without this the page could be printing the user's default membership and
    would look identical on every request, which is exactly the bug a person
    signing in and seeing the wrong branch needs the page to be able to show.

    The branch is opened through `create_organization`, never
    `Organization.objects.create`: the path is assigned by that service and
    nowhere else (house rule 24), so a hand-built node would be testing a row
    the product cannot make.
    """
    branch = create_organization(
        tenant=tenant,
        parent=root_org,
        name="Branch",
        slug="branch",
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    client.force_login(owner)
    body = client.get(WELCOME, headers={"X-Org": branch.slug}).content.decode()
    assert branch.name in body
    assert branch.slug in body
    assert root_org.slug not in body.split("Acting organization")[1].split("</dd>")[0]


def test_an_unresolved_hat_says_so_rather_than_showing_nothing(client: Client, nomad: User) -> None:
    """A person with no membership: the page says the reads are empty and why.

    This is the case the old landing could not have surfaced at all. Tenancy
    fails closed by returning NOTHING, so without a page that names it, the
    first symptom is an empty list an hour later with no explanation attached.
    """
    client.force_login(nomad)
    body = client.get(WELCOME).content.decode()
    assert "None resolved" in body


def test_it_writes_nothing(client: Client, owner: User, tenant: Tenant) -> None:
    """A landing page is a read. The membership count is the cheap witness."""
    before = Membership.objects.filter(tenant=tenant).count()
    client.force_login(owner)
    client.get(WELCOME)
    assert Membership.objects.filter(tenant=tenant).count() == before


# --- it is in the entrance's register -----------------------------------------


def test_it_extends_the_entrance_shell(client: Client, owner: User) -> None:
    """The last frame of the sign-in chain looks like the frames before it."""
    client.force_login(owner)
    body = client.get(WELCOME).content.decode()
    assert "--entrance-tokens" in body
    assert "<link" not in body


# --- it is the CSRF bootstrap page --------------------------------------------


def test_it_hands_the_browser_a_csrf_cookie(client: Client, owner: User) -> None:
    """The reader the settings comment names. Delete the decorator and this fails."""
    client.force_login(owner)
    response = client.get(WELCOME)
    assert settings.CSRF_COOKIE_NAME in response.cookies


def test_the_named_mechanism_has_a_reader() -> None:
    """A mechanism a comment names and no code uses is a defect nothing sees.

    The CSRF section of `config/settings/base.py` names `ensure_csrf_cookie`.
    Before this view existed that comment was the ONLY occurrence of the name in
    the whole tree — an instruction shipped to every clone, addressed to nobody.
    The assertion is the pairing: the settings comment names this view, and this
    view really carries the decorator.
    """
    root = Path(str(settings.BASE_DIR))
    settings_source = (root / "config" / "settings" / "base.py").read_text(encoding="utf-8")
    views_source = (root / "apps" / "core" / "views.py").read_text(encoding="utf-8")
    assert "apps.core.views.welcome" in settings_source
    assert "@ensure_csrf_cookie" in views_source


# --- it is shadowed, not configured -------------------------------------------


def test_a_product_route_at_the_same_path_wins() -> None:
    """A product's own landing page, mounted ahead of ours, is what answers.

    The whole seam: no deletion, no setting, no fork of `config/urls.py` — the
    platform's mount is simply last, and Django resolves in order.
    """
    match = resolve(WELCOME, urlconf=SHADOWING_URLCONF)
    assert match.func is shadowed_welcome_urls.product_welcome


def test_the_platform_landing_is_still_mounted_underneath() -> None:
    """Shadowed means covered, not removed: ours is still in the same list."""
    names = [getattr(pattern, "name", None) for pattern in shadowed_welcome_urls.urlpatterns]
    assert names.count("welcome") == 2


@override_settings(ROOT_URLCONF=SHADOWING_URLCONF)
def test_the_product_page_is_what_answers_over_the_wire(client: Client) -> None:
    """Through the shadowing URLconf, anonymously: the product's page, not a redirect.

    The resolver test above proves which view is BOUND; this proves the product
    actually gets its own page — including that the platform's `@login_required`
    does not intercept a route it no longer owns.
    """
    response = client.get(WELCOME)
    assert response.status_code == 200
    assert shadowed_welcome_urls.PRODUCT_BODY in response.content.decode()


def test_a_different_role_gets_a_different_page(
    client: Client, member: User, tenant: Tenant
) -> None:
    """The page reports THIS session, not a constant that happens to look right."""
    client.force_login(member)
    body = client.get(WELCOME).content.decode()
    assert "<dd>member</dd>" in body
    assert member.email in body
