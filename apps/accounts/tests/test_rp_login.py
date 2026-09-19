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

import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.socialaccount.models import SocialAccount
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.stub_issuer import StubIssuer
from apps.core.actor import actor_for, system_actor
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, invite_member

pytestmark = pytest.mark.django_db

CALLBACK_PATH = "/accounts/oidc/zitadel/login/callback/"

# The event the adapter's guard writes when an offer no longer applies. Named
# once, here, because two tests and the adapter have to agree on the string and
# a dashboard groups by it (`core.log`: the first argument is a NAME).
NOT_APPLIED_EVENT = "accounts.invitation.not_applied"


def structured(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Every structured line captured so far, parsed back from what left the process.

    Deliberately not `structlog.testing.capture_logs`, which swaps the whole
    processor chain out; this reads what stdlib logging received, which is the
    rendering a person actually queries. The `{` test is what keeps a stray
    plain-text line from a library out of the list — the idiom
    `core/tests/test_vocabulary.py` uses, for the same reason.
    """
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]


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


# --- an EXISTING person's pending invitations, honoured at sign-in -----------
#
# Everything above this line is about somebody arriving for the FIRST time, and
# that is the only case the invitation join ever covered: it ran from
# `AccountAdapter.save_user`, which fires when allauth writes a `User` row. A
# person who already has an account and is invited into a second tenant never
# reaches it — and the invitation mail says "sign in and you will land in …",
# which is the promise these cases hold the tree to.


def invited_into_a_second_tenant(
    *,
    email: str,
    inviter: User,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> tuple[Invitation, Organization]:
    """An offer of a place in a BRANCH of the second tenant, never its root.

    The branch is the point. A membership that landed at the root would satisfy
    "they are in that tenant now" while silently losing the placement the offer
    named, which is the thing ADR core-20 made the invitation carry.
    """
    hat = actor_for(user=inviter, tenant=other_tenant, org=other_root_org)
    branch = create_organization(
        tenant=other_tenant,
        parent=other_root_org,
        name="Field office",
        slug="field-office",
        actor=hat,
    )
    invitation, _token = invite_member(
        tenant=other_tenant,
        email=email,
        role=Membership.Role.ADMIN,
        organization=branch,
        invited_by=inviter,
        actor=hat,
    )
    return invitation, branch


def test_an_existing_person_who_signs_in_joins_the_tenant_they_were_invited_into(
    api: Client,
    stub_issuer: StubIssuer,
    tenant: Tenant,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> None:
    """The mail's sentence, made true for somebody who already has an account.

    `member` belongs to the first tenant already, so allauth's signup step never
    runs for them — which is exactly why the offer standing in the second tenant
    used to expire unnoticed while they signed in and out every day.
    """
    stub_issuer.email = member.email
    invitation, branch = invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )

    response = sign_in(api)

    assert response.status_code == 302
    assert Membership.objects.filter(user_id=member.pk, tenant=other_tenant).count() == 1
    joined = Membership.objects.get(user_id=member.pk, tenant=other_tenant)
    # The organization and the role are the OFFER's, not a default this file chose.
    assert joined.organization_id == branch.pk
    assert joined.role == invitation.role == Membership.Role.ADMIN
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED
    assert invitation.accepted_at is not None
    # And the place they already held is untouched.
    assert Membership.objects.filter(user_id=member.pk, tenant=tenant).count() == 1
    assert api.session.get("_auth_user_id") == str(member.pk)


def test_a_second_sign_in_does_not_double_join(
    api: Client,
    stub_issuer: StubIssuer,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> None:
    """The `accepted` state, driven: signing in twice joins once.

    This is what makes the hook safe to run on EVERY sign-in rather than on the
    one that happens to be the first: accepting moves the row out of `pending`,
    and the second pass finds nothing to do.
    """
    stub_issuer.email = member.email
    invitation, branch = invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )

    sign_in(api)
    api.logout()
    second = sign_in(api)

    assert second.status_code == 302
    assert Membership.objects.filter(user_id=member.pk, tenant=other_tenant).count() == 1
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED
    assert api.session.get("_auth_user_id") == str(member.pk)


def test_a_voided_invitation_is_left_alone_and_sign_in_still_lands(
    api: Client,
    stub_issuer: StubIssuer,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> None:
    """The `revoked` state, driven: withdrawn is withdrawn, and signing in works.

    Two halves, and the second is the one worth saying out loud: an offer that
    was taken back must not become a membership, and must not cost the person
    their sign-in either.
    """
    stub_issuer.email = member.email
    invitation, _branch = invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )
    Invitation.objects.filter(pk=invitation.pk).update(status=Invitation.Status.REVOKED)

    response = sign_in(api)

    assert response.status_code == 302
    assert not Membership.objects.filter(user_id=member.pk, tenant=other_tenant).exists()
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.REVOKED
    assert invitation.accepted_at is None
    assert api.session.get("_auth_user_id") == str(member.pk)


def test_an_expired_invitation_into_a_second_tenant_is_left_alone_and_sign_in_still_lands(
    api: Client,
    stub_issuer: StubIssuer,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> None:
    """The `expired` state, driven on the EXISTING-person road.

    The sibling above (`test_an_expired_invitation_still_lets_the_person_in`)
    drives it for somebody arriving for the first time; expiry is a state, not a
    deleted row, so the road that reads it has to be the same on both.
    """
    from datetime import timedelta

    from apps.core.time import now

    stub_issuer.email = member.email
    invitation, _branch = invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )
    Invitation.objects.filter(pk=invitation.pk).update(expires_at=now() - timedelta(days=1))

    response = sign_in(api)

    assert response.status_code == 302
    assert not Membership.objects.filter(user_id=member.pk, tenant=other_tenant).exists()
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.PENDING
    assert api.session.get("_auth_user_id") == str(member.pk)


def test_an_invitation_to_a_place_they_already_hold_does_not_cost_them_the_sign_in(
    api: Client,
    stub_issuer: StubIssuer,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The state the four above do not name, and the one the hook above CREATED.

    `invite_member` does not refuse an address that is already a member — two
    branches may each have an offer out to one person — so "invited here, then
    added here by hand, then signs in" leaves a pending offer whose acceptance
    the service correctly refuses (`Conflict`, "You are already a member of…").
    Until the join moved onto the sign-in road that refusal was unreachable
    from one, because the
    join only ever ran for an account that did not exist yet and therefore held
    nothing. Running it on every sign-in makes it reachable, and an unhandled
    refusal there is a 500 on the front door: the invitation that no longer
    applies simply does not apply, exactly as an expired one does not.

    **And the stepping over is asserted by its LOG, not only by its silence.**
    Every assertion above this line is about something that did NOT happen, and
    a bare `except: pass` in the guard satisfies all of them — the one thing
    that tells "handled, and here is which refusal" from "swallowed" is the
    line the guard writes. So the event is named, and so are the three fields a
    person reading it at three in the morning needs: which refusal, which offer,
    which tenant.
    """
    stub_issuer.email = member.email
    invitation, branch = invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )
    add_membership(
        user=member,
        tenant=other_tenant,
        organization=branch,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=other_tenant),
    )

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        response = sign_in(api)

    assert response.status_code == 302
    assert Membership.objects.filter(user_id=member.pk, tenant=other_tenant).count() == 1
    # The place they hold is the one they already held — the offer changed nothing.
    assert (
        Membership.objects.get(user_id=member.pk, tenant=other_tenant).role
        == Membership.Role.MEMBER
    )
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.PENDING
    assert api.session.get("_auth_user_id") == str(member.pk)

    stepped_over = [line for line in structured(caplog) if line.get("event") == NOT_APPLIED_EVENT]
    assert len(stepped_over) == 1, structured(caplog)
    # The refusal's own code, not a message somebody will reword.
    assert stepped_over[0]["code"] == "conflict"
    assert stepped_over[0]["invitation_id"] == str(invitation.pk)
    assert stepped_over[0]["tenant_id"] == str(other_tenant.pk)


def test_an_unexpected_failure_inside_the_join_is_not_swallowed(
    api: Client,
    stub_issuer: StubIssuer,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard's POPULATION, said out loud: refusals, and nothing else.

    A `try/except` is a claim about which failures are expected, and the claim
    is only as narrow as the class it names. `DomainError` is the refusal
    family — an offer that no longer applies — and stepping over one is the
    honest answer. Everything else is a bug, and a front door that swallows
    bugs is a front door that signs people in past a broken join and reports
    a clean 302.

    The sibling above proves the narrow half fires. This proves the wide half
    does NOT: widen the guard to `Exception` and this case is the one that
    reds, which is exactly what makes it worth its second.
    """
    stub_issuer.email = member.email
    invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )

    def the_join_breaks(**_kwargs: Any) -> None:
        raise RuntimeError("the join broke in a way nobody predicted")

    # Patched on the ADAPTER's name, which is where the call is made from: a
    # guard that has widened would catch this exactly where it catches a
    # refusal, and patching the service's own module would leave the same hole.
    monkeypatch.setattr("apps.accounts.adapter.accept_invitation", the_join_breaks)

    with pytest.raises(RuntimeError, match="nobody predicted"):
        sign_in(api)

    # And nothing was invented on the way out: no membership, no session.
    assert not Membership.objects.filter(user_id=member.pk, tenant=other_tenant).exists()


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


# --- the join is the SUBJECT's, not the address's -----------------------------
#
# Everything above resolves a returning person by the address the issuer
# asserted. An address is a label an employer can reassign, and the subject is
# the account — so an assertion carrying a fresh subject and a verified address
# that already belongs to somebody is a claim on that account, not an update to
# it. The three cases below are the three shapes that claim arrives in.


def test_a_second_subject_for_a_person_who_already_holds_one_is_refused(
    api: Client, stub_issuer: StubIssuer, owner: User
) -> None:
    """The takeover, over the wire: a new subject, somebody else's verified address.

    The owner has signed in before, so their account carries the subject the
    platform gave them. The issuer then asserts their address under a DIFFERENT
    subject — which is exactly what a party who can make the trusted issuer say
    a chosen address is verified would send. Resolving by address hands them the
    session; resolving by subject refuses, because the subject is the account.
    """
    stub_issuer.email = owner.email
    stub_issuer.subject = "sub-original"
    sign_in(api)
    api.logout()

    stub_issuer.subject = "sub-impostor"
    response = sign_in(api)

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session
    owner.refresh_from_db()
    assert owner.zitadel_sub == "sub-original"
    assert SocialAccount.objects.filter(uid="sub-impostor").count() == 0


def test_a_known_subject_signs_in_even_when_its_address_moved(
    api: Client, stub_issuer: StubIssuer, owner: User
) -> None:
    """The other half of "the subject is the account", and the reason it is safe.

    Somebody's address changes at the identity platform. The subject does not,
    so they are still the same person here and they still get in. This rung does
    NOT copy the new address onto our row — the address is a product's own field
    with its own door, and a sign-in that silently rewrote it would be a second
    writer of a fact `update_user` owns. The trigger for changing that is a
    product that wants the platform to be authoritative for addresses.
    """
    stub_issuer.email = owner.email
    stub_issuer.subject = "sub-original"
    sign_in(api)
    api.logout()

    stub_issuer.email = "renamed@example.com"
    response = sign_in(api)

    assert response.status_code == 302
    assert api.session.get("_auth_user_id") == str(owner.pk)
    owner.refresh_from_db()
    assert owner.email == "owner@example.com"
    assert User.objects.filter(email="renamed@example.com").count() == 0


def test_a_social_account_held_by_one_person_is_never_rehomed(
    api: Client, stub_issuer: StubIssuer, owner: User, member: User
) -> None:
    """The variant our own column cannot see, and the row that votes instead.

    Three tables can name a subject — `User.zitadel_sub`, `SocialAccount.uid`
    and `SsoIdentity.subject` — and the first two must agree. A row predating
    the column has a `SocialAccount` and no `zitadel_sub`, so a subject-first
    lookup finds nobody and the address road would happily link the subject to
    whoever holds the asserted address. allauth already knows whose that subject
    is; it gets a vote.
    """
    SocialAccount.objects.create(user=owner, provider="zitadel", uid="sub-x")
    assert owner.zitadel_sub is None
    stub_issuer.subject = "sub-x"
    stub_issuer.email = member.email

    response = sign_in(api)

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session
    assert SocialAccount.objects.get(uid="sub-x").user_id == owner.pk
    member.refresh_from_db()
    assert member.zitadel_sub is None


@pytest.mark.parametrize("asserted", ["an address nobody holds", "another account's address"])
def test_an_allauth_row_without_our_column_never_signs_anyone_in(
    api: Client, stub_issuer: StubIssuer, owner: User, member: User, asserted: str
) -> None:
    """allauth's row is a handle on an account, and this door decides who uses it.

    A `SocialAccount` holding the asserted subject while `User.zitadel_sub`
    holds it for nobody is refused **whatever address the assertion carried**.
    The address is what separates the two cases and it must not separate the
    answers: allauth's own `(provider, uid)` lookup runs after this adapter and
    consults none of its rules, so a subject it holds and we do not is a
    sign-in this door has to decide or lose.

    * **an address nobody holds** — the fatal one, and the reason this test
      exists. The old door found nobody by subject, found nobody by address,
      took the new-person branch and wrote nothing — and allauth then resolved
      the row and signed the bearer in AS ITS OWNER (V-R2F: 302, a session as
      `member`). Two roads produce that row: one from before the column existed,
      and one an `unlink_identity` left behind.
    * **another account's address** — the variant that was already refused, kept
      here as the sibling that makes the rule readable as one rule rather than
      two coincidences. Its own case (`…_never_rehomed`, above) asserts the row
      is not rehomed; this one asserts the answer does not depend on the
      address.
    """
    SocialAccount.objects.create(user=member, provider="zitadel", uid="sub-y")
    assert member.zitadel_sub is None
    stub_issuer.subject = "sub-y"
    stub_issuer.email = (
        "nobody-here@example.com" if asserted == "an address nobody holds" else owner.email
    )
    people_before = User.objects.count()

    response = sign_in(api)

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session
    assert User.objects.count() == people_before, "a refused sign-in creates nobody"
    assert SocialAccount.objects.get(uid="sub-y").user_id == member.pk
    member.refresh_from_db()
    owner.refresh_from_db()
    assert member.zitadel_sub is None
    assert owner.zitadel_sub is None


# --- a refused sign-in writes nothing ----------------------------------------


def test_a_deactivated_person_signing_in_writes_nothing(
    api: Client,
    stub_issuer: StubIssuer,
    member: User,
    stranger: User,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> None:
    """Switched off is switched off, and the wall has to hold at the FRONT door.

    allauth refuses an inactive account of its own accord — but it does it at
    the END, after the adapter has recorded the subject, connected a
    `SocialAccount` and honoured every standing invitation. The person never
    gets a session, so the refusal looks like it worked; what actually happened
    is that a deactivated account grew a membership, an identity join and an
    accepted invitation on the strength of a login that was refused.

    The invitation is the part that makes it more than untidiness: deactivating
    somebody is how an administrator ends their access, and an invitation
    accepted afterwards is access granted after the ending.
    """
    invitation, branch = invited_into_a_second_tenant(
        email=member.email,
        inviter=stranger,
        other_tenant=other_tenant,
        other_root_org=other_root_org,
    )
    member.is_active = False
    member.save(update_fields=["is_active"])
    stub_issuer.email = member.email
    memberships_before = Membership.objects.filter(user_id=member.pk).count()

    response = sign_in(api)

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session
    member.refresh_from_db()
    assert member.zitadel_sub is None
    assert SocialAccount.objects.filter(user_id=member.pk).count() == 0
    assert Membership.objects.filter(user_id=member.pk).count() == memberships_before
    assert not Membership.objects.filter(user_id=member.pk, tenant=other_tenant).exists()
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.PENDING


# --- A8 · Mode A does not move the RP road it rides on ------------------------


def test_the_rp_road_is_unchanged_under_ours(
    api: Client, stub_issuer: StubIssuer, settings: Any
) -> None:
    """A8.5 · turning the front door to `ours` changes NOTHING on this road.

    Mode A is a detour in the MIDDLE of this journey, not a replacement for
    it: allauth still starts the authorize, the platform still 302s a browser
    somewhere, the code still comes back to allauth's own callback, and
    `_platform_login` still makes all three of its decisions. What changes is
    only where the browser spends the middle of the trip — a page of ours
    instead of the platform's — and this stub issuer cannot model that hop,
    which is why the live walk is pasted in the rung's report and this case
    asserts the thing a test CAN: that the two ends are byte-for-byte the
    ends they were.

    Driven under both door values in one function rather than parametrised,
    so the comparison is an assertion rather than two green lines somebody
    has to notice agree.
    """
    settings.SIGN_IN_DOOR = "hosted"
    hosted = start_login(api)

    api.logout()
    settings.SIGN_IN_DOOR = "ours"
    ours = start_login(api)

    moved = {
        name: (hosted.get(name), ours.get(name))
        for name in set(hosted) | set(ours)
        # `state` and `code_challenge` are per-attempt by construction.
        if name not in ("state", "code_challenge") and hosted.get(name) != ours.get(name)
    }
    assert moved == {}, moved

    landed = sign_in(api)
    assert landed.status_code == 302
    person = User.objects.get(email=stub_issuer.email)
    assert api.session.get("_auth_user_id") == str(person.pk)
    assert person.zitadel_sub == stub_issuer.subject
