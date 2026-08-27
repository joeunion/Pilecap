"""The browser door, driven end to end against a real OpenID Connect issuer.

The issuer is `stub_issuer.py` — in this process, on a loopback socket, signing
real RS256 tokens (ADR ident-5). What runs between the two is allauth's actual
protocol implementation: its state store, its PKCE verifier, its token exchange
over `requests`, its `jwt.decode` with issuer, audience and expiry enforced.
Nothing here patches allauth, and nothing here dials Zitadel.

The flow every test below drives is the real one, in two legs, because that is
how a browser does it:

1. `GET /accounts/oidc/zitadel/login/` → a 302 to the issuer's
   `authorization_endpoint`, carrying `state` and a PKCE `code_challenge`;
2. `GET /accounts/oidc/zitadel/login/callback/?code=…&state=…` → allauth
   exchanges the code (sending the verifier), decodes the id_token, fetches
   userinfo, and hands the assertion to `accounts.adapter`.

`state` is read back out of the first redirect rather than invented: allauth
keeps it in the session, and a test that made one up would be testing that we
can forge our own state.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.stub_issuer import StubIssuer
from apps.core.actor import system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import invite_member

pytestmark = pytest.mark.django_db

CALLBACK_PATH = "/accounts/oidc/zitadel/login/callback/"


def start_login(api: Client) -> dict[str, list[str]]:
    """Leg one. Returns the query the IdP was redirected to, parsed.

    A **POST**, because that is what a browser sends. allauth serves the login
    endpoint as an interstitial form on GET (`SOCIALACCOUNT_LOGIN_ON_GET` is off
    by default, and rightly: a GET that starts an authentication is a CSRF-shaped
    hole in a link somebody can put in an email). The page's own button posts,
    and so does this.
    """
    response = api.post(reverse("openid_connect_login", kwargs={"provider_id": "zitadel"}))
    assert response.status_code == 302, response.content
    return parse_qs(urlparse(response["Location"]).query)


def finish_login(api: Client, state: str, code: str = "stub-auth-code") -> Any:
    """Leg two: the browser coming back from the IdP with a code."""
    return api.get(CALLBACK_PATH, {"code": code, "state": state}, follow=False)


def sign_in(api: Client) -> Any:
    """Both legs, for a test whose subject is what happens afterwards."""
    params = start_login(api)
    return finish_login(api, params["state"][0])


# --- W2R3-1: the round trip ---------------------------------------------------


def test_the_authorize_redirect_carries_pkce_and_state(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """The half a network interceptor can see, asserted where it is decided."""
    params = start_login(api)

    assert params["response_type"] == ["code"]
    assert params["client_id"] == [stub_issuer.client_id]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0]
    assert params["state"][0]
    assert params["redirect_uri"][0].endswith(CALLBACK_PATH)


def test_the_login_round_trips_and_creates_the_session(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """W2R3-1: a person who was not here before ends the flow signed in."""
    response = sign_in(api)

    assert response.status_code == 302
    person = User.objects.get(email=stub_issuer.email)
    assert api.session.get("_auth_user_id") == str(person.pk)
    assert person.zitadel_sub == stub_issuer.subject
    # And they hold nothing: an IdP answers who, never what they may do.
    assert not Membership.objects.filter(user_id=person.pk).exists()


def test_the_token_exchange_sends_the_pkce_verifier(api: Client, stub_issuer: StubIssuer) -> None:
    """The other half of PKCE — the half only the issuer ever sees.

    Asserting the challenge in the redirect proves we asked for PKCE; this
    proves we completed it. A client that sent a challenge and never a verifier
    would pass the first test and be doing nothing.
    """
    sign_in(api)

    assert len(stub_issuer.token_requests) == 1
    form = stub_issuer.token_requests[0]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["stub-auth-code"]
    assert form["code_verifier"][0]
    assert form["client_id"] == [stub_issuer.client_id]


def test_a_second_login_reuses_the_user(api: Client, stub_issuer: StubIssuer) -> None:
    """W2R3-1's last clause: no duplicate, and no second identity row."""
    sign_in(api)
    first = User.objects.get(email=stub_issuer.email)

    api.logout()
    sign_in(api)

    assert User.objects.filter(email=stub_issuer.email).count() == 1
    assert User.objects.get(pk=first.pk).zitadel_sub == stub_issuer.subject
    assert api.session.get("_auth_user_id") == str(first.pk)


def test_an_existing_local_account_is_linked_not_duplicated(
    api: Client, stub_issuer: StubIssuer, owner: User
) -> None:
    """The seeded owner, the invited person, the superuser — all predate this door.

    Every one of them has to end up in their own account the first time they use
    it, which is the whole reason `_platform_login` links before allauth's
    signup step gets a chance to create a second row.
    """
    stub_issuer.email = owner.email
    stub_issuer.subject = "zitadel-subject-for-the-owner"

    sign_in(api)

    assert User.objects.filter(email=owner.email).count() == 1
    owner.refresh_from_db()
    assert owner.zitadel_sub == "zitadel-subject-for-the-owner"
    assert api.session.get("_auth_user_id") == str(owner.pk)


def test_a_subject_already_linked_elsewhere_is_refused(
    api: Client, stub_issuer: StubIssuer, owner: User, member: User
) -> None:
    """Re-pointing the join silently would be an account takeover with a step.

    The IdP asserts `member`'s address with a subject `owner` already holds. The
    honest answer is a refusal: one of those two facts is wrong, and guessing
    which is how somebody inherits somebody else's account.
    """
    owner.zitadel_sub = "a-subject-that-is-taken"
    owner.save(update_fields=["zitadel_sub"])
    stub_issuer.email = member.email
    stub_issuer.subject = "a-subject-that-is-taken"

    response = sign_in(api)

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session
    member.refresh_from_db()
    assert member.zitadel_sub is None


# --- W2R3-4: an unverified assertion is refused, with no User row -------------


def test_an_unverified_address_is_refused_and_writes_no_user(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """The A9 property, on the RP path.

    Linking on an address alone means whoever can make an IdP assert an address
    owns the account at that address. The refusal is before allauth's signup
    step — the only thing that would have written a row — so "no User" is a
    structural claim and not a cleanup.
    """
    stub_issuer.email_verified = False

    response = sign_in(api)

    assert response.status_code == 403
    assert not User.objects.filter(email=stub_issuer.email).exists()
    assert "_auth_user_id" not in api.session


def test_the_refusal_page_names_nothing_about_the_deployment(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """This page is reachable by anybody who can start a login."""
    stub_issuer.email_verified = False

    page = sign_in(api).content.decode()

    assert stub_issuer.base_url not in page
    assert stub_issuer.client_id not in page


# --- W2R3-3: invitations, through the new engine ------------------------------


def test_an_invited_address_lands_in_the_invited_tenant_at_the_invited_role(
    api: Client,
    stub_issuer: StubIssuer,
    tenant: Tenant,
    owner: User,
    root_org: Organization,
) -> None:
    """W2R3-3. The property is today's; only the door it arrives through is new."""
    invite_member(
        tenant=tenant,
        email=stub_issuer.email,
        role=Membership.Role.ADMIN,
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )

    sign_in(api)

    person = User.objects.get(email=stub_issuer.email)
    membership = Membership.objects.get(user_id=person.pk, tenant=tenant)
    assert membership.role == Membership.Role.ADMIN


def test_an_uninvited_first_login_gets_an_account_and_no_tenant(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """The other half, and the template's deliberate default.

    Self-service tenant creation is a product decision. Landing with no
    membership and — tenancy failing closed — seeing nothing is the right thing
    for a template to do.
    """
    sign_in(api)

    person = User.objects.get(email=stub_issuer.email)
    assert not Membership.objects.filter(user_id=person.pk).exists()


def test_an_expired_invitation_still_lets_the_person_in(
    api: Client,
    stub_issuer: StubIssuer,
    tenant: Tenant,
    owner: User,
    root_org: Organization,
) -> None:
    """An invitation that lapsed between the email and the login is not a refusal."""
    from datetime import timedelta

    from apps.core.models import Invitation
    from apps.core.time import now

    invitation, _token = invite_member(
        tenant=tenant,
        email=stub_issuer.email,
        role=Membership.Role.ADMIN,
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    Invitation.objects.filter(pk=invitation.pk).update(expires_at=now() - timedelta(days=1))

    sign_in(api)

    person = User.objects.get(email=stub_issuer.email)
    assert not Membership.objects.filter(user_id=person.pk).exists()


def test_the_seed_the_settings_and_the_url_agree_on_the_provider_id() -> None:
    """Three things name this string, and a disagreement is undebuggable.

    `config/settings/base.py` registers the provider under it, `zitadel_seed`
    registers a redirect URI built from it with Zitadel, and allauth mounts the
    callback at it. Get them out of step and the failure surfaces as
    `redirect_uri mismatch` on somebody else's login screen, with nothing in
    this tree pointing at the cause.
    """
    from django.conf import settings

    from apps.accounts.management.commands.zitadel_seed import BROWSER_CALLBACK_PATH

    mounted = reverse(
        "openid_connect_callback",
        kwargs={"provider_id": settings.ZITADEL_PROVIDER_ID},
    )
    assert BROWSER_CALLBACK_PATH == mounted


# --- the page itself: a button, or a sentence — never nothing ---------


def test_the_login_page_offers_the_platform_button_when_one_is_configured(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """The configured branch, over the wire.

    `stub_issuer` is what puts a provider in the list, exactly as a deployment
    that has run `./scripts/setup.sh` has one. The assertion is the *clickable
    thing*: an anchor whose href starts the flow, with the provider's name on
    it, because a link nobody can see is the dead end this closes.
    """
    page = api.get(reverse("account_login")).content.decode()

    assert reverse("openid_connect_login", kwargs={"provider_id": "zitadel"}) in page
    assert "Zitadel" in page
    # And the sentence for the OTHER case is not also on the page.
    assert "./scripts/setup.sh" not in page


def test_the_login_page_says_what_is_missing_when_nothing_is_configured(
    api: Client, settings: Any
) -> None:
    """**The bug that was recorded**: 200, a heading, and nothing under it.

    Measured on the tree this landed against — 895 bytes whose entire visible
    text was "Sign In Menu: Sign In Sign In". `SOCIALACCOUNT_ONLY` removes the
    local form, which is right, and allauth renders the provider list only when
    there is one, which is also right; between them a fresh clone served a page
    with no way in and no explanation. A page that cannot let you in has to say
    who fixes it and how.

    No `stub_issuer` here, which is what leaves the provider list empty.
    """
    settings.ZITADEL_CLIENT_ID = ""
    settings.SOCIALACCOUNT_PROVIDERS = {}

    page = api.get(reverse("account_login")).content.decode()

    assert "./scripts/setup.sh" in page
    assert "no sign-in provider configured" in page
    # Not a form, and not a signup offer: there is no local password here and
    # no signup door, and the old page implied both.
    assert "<form" not in page
    assert "sign up" not in page.lower()
