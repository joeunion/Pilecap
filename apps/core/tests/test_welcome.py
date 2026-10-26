"""`/welcome/` — where a completed sign-in lands, and what it is allowed to be.

`LOGIN_REDIRECT_URL` was `"/"`, so the last screen of the sign-in chain was the
door index: a monospace directory listing addressed to an operator, handed to a
person who had just finished authenticating — the landing defect the entrance
survey measured at `config/settings/base.py`. This is the page that replaced it,
and there are four separate claims about it worth a test:

* it demands a credential, and an anonymous request is a redirect rather than a
  thinner render;
* it reports what the request actually RESOLVED to — the person, the tenant, the
  hat and the role that hat carries — which is the only reason a
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
from apps.core.actor import actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import create_organization, create_tenant
from apps.core.tests import shadowed_welcome_urls
from apps.core.tests.settings_env import _settings_module
from apps.core.tests.template_shape import IDENTITY_SHAPE, template_shape

pytestmark = pytest.mark.django_db

WELCOME = "/welcome/"
SHADOWING_URLCONF = "apps.core.tests.shadowed_welcome_urls"

#: A front end that is not this deployment, for the declared branch of the
#: landing derivation. `.example` is reserved by RFC 2606, so nothing resolves.
A_FRONT_END = "https://app.example"


# --- it is where sign-in lands ------------------------------------------------


def test_login_redirect_is_the_landing_and_it_resolves() -> None:
    """The name and the mount are pinned to each other, in both directions.

    A landing that resolves to nothing is a 404 after a successful sign-in — the
    one moment a person is least able to tell whether the failure is theirs.

    **It used to open by comparing live `LOGIN_REDIRECT_URL` against the mounted
    path, and that line was a report about the machine it ran on.** The setting
    is DERIVED from `PRODUCT_BASE_URL`, which `.env.example` invites every
    product to set, so the same green assertion was red in the first consumer's
    primary checkout the day they set it. What survives here is the half that is
    genuinely this tree's: the route exists, under the name the derivation uses.
    The derivation itself is proved under a pinned environment, below.

    (The paragraph above deliberately avoids spelling the assertion it replaced:
    the census that found it greps for that shape, and a docstring counted as a
    site is a census reporting a defect nobody can fix.)
    """
    assert reverse("welcome") == WELCOME
    assert resolve(WELCOME).view_name == "welcome"


def test_the_landing_is_local_when_no_front_end_is_declared() -> None:
    """`PRODUCT_BASE_URL` defaults to `PUBLIC_BASE_URL`, so a clone pays nothing.

    Imported under an environment that CLEARS the variable rather than asserted
    off live settings: `_settings_module` is the form every settings derivation
    in this tree is proved in, and clearing is the half that makes the answer
    the derivation's instead of the deployment's.
    """
    with _settings_module("config.settings.base", PRODUCT_BASE_URL=None) as base:
        assert base.PRODUCT_BASE_URL == base.PUBLIC_BASE_URL
        assert base.LOGIN_REDIRECT_URL == WELCOME


def test_the_landing_is_the_front_ends_origin_when_one_is_declared() -> None:
    """The other branch: a product with a front end says where, and sign-in lands there.

    The two together are what `LOGIN_REDIRECT_URL` actually promises. Neither
    can be seen from live settings, and asserting on live settings is how the
    promise came to be tested as "today's environment is today's environment".
    """
    with _settings_module("config.settings.base", PRODUCT_BASE_URL=A_FRONT_END) as base:
        assert base.PRODUCT_BASE_URL == A_FRONT_END
        assert base.LOGIN_REDIRECT_URL == A_FRONT_END


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
    """The hat, resolved by the one function all four doors call."""
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


def test_a_fresh_deployment_names_the_next_act(client: Client, nomad: User) -> None:
    """An unresolved tenant on an EMPTY installation names the command that fixes it.

    The sentence above it — "Every tenant-scoped read is empty until one is" —
    is true on both kinds of deployment and actionable on neither. On a fresh
    clone the reader is the person who just ran the installer, the reason there
    is no tenant is that nobody has made one yet, and the next act is a single
    command; leaving them to find it is the landing page describing a dead end
    it could have opened.

    **The `iff` is the whole test, and both halves are here on purpose.** The
    predicate is `Tenant.objects.exists()` — the same one `create_first_tenant`
    refuses on (`apps/core/services/tenants.py`), which is what makes the page's advice
    and the command's own refusal impossible to disagree. Told only to the
    first half, this is a helpful landing page; told to the second, it is a
    page telling a member of a live installation to go and run a shell command
    that would refuse them — so the negative is not a nicety, it is the
    criterion.

    The address is the signed-in person's own, read off the session exactly as
    the line above it is: a command they can paste, not a placeholder they have
    to translate.
    """
    # Fresh: no tenant row anywhere, which is the state a clone starts in.
    assert not Tenant.objects.exists()
    client.force_login(nomad)
    fresh = client.get(WELCOME).content.decode()
    assert "None resolved" in fresh
    assert "On a fresh deployment this is expected" in fresh
    assert f"uv run python manage.py bootstrap_tenant --email {nomad.email}" in fresh

    # Live: a tenant exists and this person simply has no membership on it.
    # `create_tenant` without an owner is the conftest's own idiom, and it
    # leaves `nomad` exactly as unresolved as the line above.
    create_tenant(name="Acme", slug="acme", actor=system_actor())
    live = client.get(WELCOME).content.decode()
    assert "None resolved" in live
    assert "bootstrap_tenant" not in live


def test_it_writes_nothing(client: Client, owner: User, tenant: Tenant) -> None:
    """A landing page is a read. The membership count is the cheap witness."""
    before = Membership.objects.filter(tenant=tenant).count()
    client.force_login(owner)
    client.get(WELCOME)
    assert Membership.objects.filter(tenant=tenant).count() == before


# --- it is in the entrance's register -----------------------------------------


def test_it_extends_the_entrance_shell(client: Client, owner: User) -> None:
    """The last frame of the sign-in chain looks like the frames before it.

    The marker is READ from the declaration (`DJB_IDENTITY_SHAPE`, key
    `entrance_marker`) rather than pinned, because "the landing renders in the
    product's ONE shell" is every product's property while the marker string is
    this template's own shape. `test_entrance_chain.token_marker` is the same
    read on the other side of the chain.
    """
    client.force_login(owner)
    body = client.get(WELCOME).content.decode()
    assert IDENTITY_SHAPE["entrance_marker"] in body
    assert "<link" not in body


# --- it is the CSRF bootstrap page --------------------------------------------


def test_it_hands_the_browser_a_csrf_cookie(client: Client, owner: User) -> None:
    """The reader the settings comment names. Delete the decorator and this fails."""
    client.force_login(owner)
    response = client.get(WELCOME)
    assert settings.CSRF_COOKIE_NAME in response.cookies


@template_shape("landing")
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
