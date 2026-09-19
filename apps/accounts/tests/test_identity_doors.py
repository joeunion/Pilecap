"""The adapters: what an identity provider is allowed to turn into a session.

Everything here drives `apps.accounts.adapter` with the objects allauth actually
hands it — a real `SocialLogin` carrying a real `SocialAccount` — rather than a
stand-in that agrees with the code under test. The three doors are proved
separately because they are separately wrong-able:

* **workforce** — a Google account outside the organisation's domains is refused
  and **no `User` row is written**; a fresh workforce login lands with no
  membership and sees nothing;
* **customers** — an assertion **through the platform provider** for an address
  a tenant's connection claims is provisioned just-in-time, and a refused one
  becomes a page rather than a traceback. Since W2-R5 there is no per-connection
  allauth app to arrive through: Zitadel fronts every customer IdP and
  `SsoDomain` is the router (ADR ident-6);
* **password** — `enforced` takes it away, proved through allauth's own login
  view rather than by calling the adapter method.
"""

from __future__ import annotations

from typing import Any

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.test import Client

from apps.accounts.adapter import GOOGLE_PROVIDER, SocialAccountAdapter
from apps.accounts.models import SsoConnection, SsoIdentity, User
from apps.accounts.selectors import get_platform_provider_id
from apps.accounts.services import create_user, update_sso_connection
from apps.accounts.tests.conftest import assertion
from apps.core.actor import Actor
from apps.core.middleware import resolve_tenant
from apps.core.models import Membership, Tenant

pytestmark = pytest.mark.django_db

WORKFORCE_DOMAIN = "union.studio"


@pytest.fixture
def workforce(settings: Any) -> None:
    """A deployment that has actually configured the workforce door.

    Both halves, because `config/settings/base.py` requires both: credentials
    *and* a domain list. With either missing there is no Google app at all,
    which is the "empty means off" behaviour its own test below pins.
    """
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]
    settings.SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APPS": [{"client_id": "google-client-id", "secret": "google-secret", "key": ""}],
            "SCOPE": ["profile", "email"],
        },
        "openid_connect": {},
    }


def adapter(request: HttpRequest) -> SocialAccountAdapter:
    return SocialAccountAdapter(request)


# --- Workforce: Google Workspace ---------------------------------------------


def test_a_google_account_outside_the_domains_is_refused_and_writes_no_user(
    workforce: None, login_request: HttpRequest
) -> None:
    """The refusal the whole workforce door exists for.

    **No `User` row**, and that is asserted rather than assumed: the refusal
    happens in `pre_social_login`, which allauth runs *before* the signup step
    that would have created one. A refusal that left an account behind would be
    an account nobody can see and nobody deleted.
    """
    before = User.objects.count()

    with pytest.raises(ImmediateHttpResponse) as raised:
        adapter(login_request).pre_social_login(
            login_request,
            assertion(
                provider=GOOGLE_PROVIDER,
                subject="google-1",
                email="outsider@gmail.example",
            ),
        )

    assert raised.value.response.status_code == 403
    assert User.objects.count() == before


def test_the_refusal_page_names_no_domain(workforce: None, login_request: HttpRequest) -> None:
    """It is reachable by anybody with a Google account, so everything on it is public."""
    with pytest.raises(ImmediateHttpResponse) as raised:
        adapter(login_request).pre_social_login(
            login_request,
            assertion(provider=GOOGLE_PROVIDER, subject="g", email="outsider@gmail.example"),
        )
    page = raised.value.response.content.decode()
    assert WORKFORCE_DOMAIN not in page
    assert "not part of this organisation" in page


def test_an_empty_domain_list_switches_the_provider_off(
    settings: Any, login_request: HttpRequest
) -> None:
    """Empty means *off*, not "any domain".

    This is the setting a deployment gets wrong by omission, and the failure it
    guards against looks exactly like success: everyone with a Google account
    quietly becoming a user.
    """
    settings.GOOGLE_WORKSPACE_DOMAINS = []

    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request,
            assertion(
                provider=GOOGLE_PROVIDER,
                subject="google-1",
                email=f"someone@{WORKFORCE_DOMAIN}",
            ),
        )
    assert User.objects.count() == 0


def test_an_unverified_google_address_is_refused(
    workforce: None, login_request: HttpRequest
) -> None:
    """Even inside the domain: the linking below turns a claim into an account."""
    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request,
            assertion(
                provider=GOOGLE_PROVIDER,
                subject="google-1",
                email=f"someone@{WORKFORCE_DOMAIN}",
                verified=False,
            ),
        )


def test_a_verified_workforce_address_is_allowed_through(
    workforce: None, login_request: HttpRequest
) -> None:
    """No exception, and nothing created: allauth's signup step does that next."""
    login = assertion(
        provider=GOOGLE_PROVIDER,
        subject="google-1",
        email=f"someone@{WORKFORCE_DOMAIN}",
    )
    adapter(login_request).pre_social_login(login_request, login)
    assert User.objects.count() == 0


def test_an_existing_account_is_linked_not_duplicated(
    workforce: None, login_request: HttpRequest
) -> None:
    """Somebody who had a password before the workforce door existed keeps their account."""
    existing = create_user(email=f"joe@{WORKFORCE_DOMAIN}", password="a-long-enough-password")

    login = assertion(provider=GOOGLE_PROVIDER, subject="google-9", email=f"joe@{WORKFORCE_DOMAIN}")
    adapter(login_request).pre_social_login(login_request, login)

    assert login.user is not None
    assert login.user.pk == existing.pk
    assert User.objects.count() == 1


def test_the_signup_lock_agrees_with_the_gate(workforce: None, login_request: HttpRequest) -> None:
    """`is_open_for_signup` is the second lock on the same door.

    It is not redundant: "`pre_social_login` already refused" is a claim about
    control flow, and control-flow claims stop being true when somebody adds a
    branch.
    """
    door = adapter(login_request)
    inside = assertion(provider=GOOGLE_PROVIDER, subject="g", email=f"someone@{WORKFORCE_DOMAIN}")
    outside = assertion(provider=GOOGLE_PROVIDER, subject="g", email="someone@gmail.example")

    assert door.is_open_for_signup(login_request, inside) is True
    assert door.is_open_for_signup(login_request, outside) is False


def test_a_fresh_workforce_login_lands_with_nothing(
    workforce: None, api: Client, sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """**Roles untouched.** Google says who; it does not say what they may do.

    Driven through a door rather than asserted on the model, because "sees
    nothing" is a claim about what a signed-in request returns. Acme has a
    connection configured; this person, who belongs to no tenant, gets an empty
    list rather than Acme's.
    """
    newcomer = create_user(email=f"newcomer@{WORKFORCE_DOMAIN}")

    assert Membership.objects.filter(user_id=newcomer.pk).count() == 0
    assert resolve_tenant(user=newcomer, requested_slug=None) is None
    assert list(SsoConnection.objects.for_tenant(None)) == []

    api.force_login(newcomer)
    response = api.get("/api/v1/auth/sso-connections/")
    # **403, and it used to be `200 []`** — the `accounts` read sweep. The
    # property this test exists for is unchanged and strictly stronger: this
    # person never sees Acme's connection. What moved is the sentence they
    # read. A hatless request resolves no tenant, so `effective_permissions`
    # fails closed at `frozenset()` and `sso_connection.read` is refused —
    # which is the same fact the second half of this test has always asserted
    # for the named-tenant case, now said on both roads instead of one. An
    # empty page would have read as "Acme has no identity provider", which is
    # a claim about Acme and was never true.
    assert response.status_code == 403, response.content

    # And asking for Acme by name does not help — it is now refused out loud
    # rather than answered empty (ADR core-21): a header that was sent and
    # cannot be honoured says so, because "empty" and "you asked for somewhere
    # you cannot go" are two different facts and only one of them was true.
    named = api.get("/api/v1/auth/sso-connections/", headers={"x-tenant": tenant.slug})
    assert named.status_code == 403, named.content
    assert named.json()["code"] == "addressing_header_not_honoured"


# --- Customers: a tenant's own OpenID Connect provider -----------------------


def test_an_assertion_through_a_connection_provisions_and_connects(
    login_request: HttpRequest,
    platform_provider: None,
    sso_connection: SsoConnection,
    tenant: Tenant,
) -> None:
    """The customer path end to end, from the object allauth would hand us.

    The provider is the **platform's** now (ADR ident-6): the customer's Okta
    sits behind Zitadel, so what arrives is a Zitadel assertion and the address's
    domain is what says whose person it is.
    """
    login = assertion(
        provider=get_platform_provider_id(),
        subject="okta|00u1",
        email="newcomer@acme.com",
    )
    adapter(login_request).pre_social_login(login_request, login)

    identity = SsoIdentity.objects.for_subject(connection=sso_connection, subject="okta|00u1")
    assert identity is not None
    assert login.user is not None
    assert login.user.pk == identity.user.pk
    assert Membership.objects.get(user_id=identity.user.pk, tenant=tenant).role == (
        Membership.Role.MEMBER
    )


def test_a_refused_assertion_becomes_a_page_not_a_traceback(
    login_request: HttpRequest, sso_connection: SsoConnection
) -> None:
    """A `DomainError` from the service is a 403 page for the person in front of it.

    An unverified address is refused by `_platform_login` before the router is
    even consulted, which is stricter than it was: it is the same refusal for
    everybody rather than one the customer path owned.
    """
    with pytest.raises(ImmediateHttpResponse) as raised:
        adapter(login_request).pre_social_login(
            login_request,
            assertion(
                provider=get_platform_provider_id(),
                subject="okta|00u1",
                email="newcomer@acme.com",
                verified=False,
            ),
        )
    assert raised.value.response.status_code == 403
    assert SsoIdentity.objects.for_tenant(sso_connection.tenant).count() == 0
    assert not User.objects.filter(email="newcomer@acme.com").exists()


def test_an_unknown_provider_id_is_simply_not_ours(login_request: HttpRequest) -> None:
    """No branch, no gate, no exception — allauth's own handling takes it from here."""
    adapter(login_request).pre_social_login(
        login_request,
        assertion(provider="sso-not-a-uuid", subject="x", email="x@example.com"),
    )


def test_a_disabled_connection_cannot_complete_a_login(
    login_request: HttpRequest, sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    """Disabling stops logins at the callback, not merely at the button.

    An in-flight browser holding a half-finished handshake is exactly who a
    customer disabling a connection is trying to stop, so `get_connection_for_email`
    resolves nothing and there is no connection to provision through. The person
    is not locked out of the platform — they land as an ordinary account with no
    membership, which is what somebody with no live connection *is* — and they
    reach none of the tenant's rows, because tenancy fails closed.
    """
    from apps.accounts.services import disable_sso_connection

    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )
    adapter(login_request).pre_social_login(
        login_request,
        assertion(provider=get_platform_provider_id(), subject="okta|00u1", email="x@acme.com"),
    )
    assert SsoIdentity.objects.for_tenant(sso_connection.tenant).count() == 0
    assert not Membership.objects.filter(tenant=sso_connection.tenant, user__email="x@acme.com")
    # And the claim itself is still there: disabling frees nothing for anybody
    # else to claim while this customer is mid-migration.
    assert sso_connection.email_domains == ["acme.com"]


# --- The per-connection provider resolver, retired (ADR ident-6) -------------
#
# Until W2-R5 the adapter overrode `list_apps` to build an unsaved `SocialApp`
# per `SsoConnection`, so that adding a customer's SSO was a row rather than a
# deploy. The promise is kept and the mechanism is gone: the row is materialised
# as an external provider *inside Zitadel* now, which means one place holds a
# customer's client secret instead of two, and there is no per-connection
# endpoint left in this product's urlconf at all.
#
# The three tests that lived here drove that override. What replaces them is the
# assertion that it is really gone — because a retirement nobody pins is a method
# somebody adds back.


def test_the_adapter_no_longer_resolves_providers_from_rows(
    login_request: HttpRequest, sso_connection: SsoConnection
) -> None:
    """`list_apps` is allauth's own again: our override is not in the way."""
    assert "list_apps" not in vars(SocialAccountAdapter)
    assert SocialAccountAdapter.list_apps.__qualname__.split(".")[0] != "SocialAccountAdapter"


@pytest.mark.parametrize(
    "rp_door_armed",
    [False, True],
    ids=["rp-door-unconfigured", "rp-door-armed"],
)
def test_a_connection_is_not_an_allauth_app_of_ours(
    settings: Any,
    rp_door_armed: bool,
    login_request: HttpRequest,
    sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
) -> None:
    """Nothing of a *customer's* to enumerate, in either deployment state.

    The old override contributed nothing when allauth enumerated, on purpose: a
    login page listing every tenant's connection would be a customer list
    rendered as buttons. Now there is nothing to decline — the connections are
    not apps.

    **The registered apps are forced here rather than inherited**, because two
    different questions were being answered by one assertion: "is a connection
    an app of ours" (this test's subject, and always no) and "is the browser
    relying party configured on this machine" (the environment's, and either).
    `config/settings/base.py` builds `SOCIALACCOUNT_PROVIDERS` once at import
    from `ZITADEL_CLIENT_ID` and `ZITADEL_ISSUER`, so a tree with the door
    armed — the documented production state — legitimately enumerates the
    static `zitadel` app, and asserting a flat empty list failed on correct
    code depending on whose `.env` ran the suite. Both states are pinned
    instead, and in **neither** may a connection appear.

    Google is switched off in both for the same reason: what is under test is
    the openid_connect half, not whether this machine holds workforce
    credentials.
    """
    settings.ZITADEL_CLIENT_ID = "test-client" if rp_door_armed else ""
    settings.ZITADEL_CLIENT_SECRET = (
        "test-secret" if rp_door_armed else ""  # pragma: allowlist secret
    )
    settings.SOCIALACCOUNT_PROVIDERS = {
        "google": {"APPS": [], "SCOPE": ["profile", "email"]},
        # The shape `base.py` builds, under the condition `base.py` builds it
        # under. The issuer is `config/settings/test.py`'s must-not-dial
        # address, and nothing here opens a socket.
        "openid_connect": {
            "APPS": (
                [
                    {
                        "provider_id": settings.ZITADEL_PROVIDER_ID,
                        "name": "Zitadel",
                        "client_id": settings.ZITADEL_CLIENT_ID,
                        "secret": settings.ZITADEL_CLIENT_SECRET,
                        "settings": {"server_url": settings.ZITADEL_ISSUER},
                    }
                ]
                if rp_door_armed
                else []
            ),
            "OAUTH_PKCE_ENABLED": True,
        },
    }

    # The installation's own provider is the only thing allowed to appear, and
    # only when it is configured.
    platform = [settings.ZITADEL_PROVIDER_ID] if rp_door_armed else []
    door = adapter(login_request)

    assert [app.provider_id for app in door.list_apps(login_request)] == platform
    assert [
        app.provider_id for app in door.list_apps(login_request, provider="openid_connect")
    ] == platform
    # And each connection resolves to nothing by its own id, in both states —
    # which is the property the retirement actually promises.
    for connection in (sso_connection, other_sso_connection):
        assert door.list_apps(login_request, provider=connection.provider_id) == []


# --- `enforced`, now that the password door it guarded is gone ---------------
#
# W2-R3 retired the local password form entirely (ADR ident-4): Zitadel hosts
# every interactive authentication, so there is no longer a password endpoint
# for `SsoConnection.enforced` to stand in front of. The three tests that used
# to live here drove that form; `test_password_door_retired.py` is what replaced
# them, and it asserts the stronger property — the URLs are *gone*, not
# refusing.
#
# What is left to test here is the part that survived the door: the refusal
# `AccountAdapter.pre_authenticate` raises is still correct, still says nothing
# about a customer, and is still reachable by calling it. It is kept as the belt
# for a product that reopens local accounts, and W2-R5 materialises the same
# flag as a Zitadel login policy — which is where `enforced` becomes
# load-bearing again.


def test_enforced_still_refuses_a_password_when_the_adapter_is_asked(
    login_request: HttpRequest, sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    """The refusal itself, one layer below the door that used to reach it.

    Called directly because nothing in this deployment calls it any more — which
    is exactly why it needs a test: an unexercised belt is a belt nobody notices
    has perished.
    """
    from allauth.account.adapter import get_adapter as get_account_adapter

    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=owner_actor,
        connection=sso_connection,
        enforced=True,
    )
    create_user(
        email="staff@acme.com",
        password="a-long-enough-password",  # pragma: allowlist secret
    )

    with pytest.raises(ValidationError) as refusal:
        get_account_adapter().pre_authenticate(
            login_request,
            email="staff@acme.com",
            password="a-long-enough-password",  # pragma: allowlist secret
        )

    assert "identity provider" in str(refusal.value)


def test_that_refusal_names_no_customer(
    login_request: HttpRequest, sso_connection: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    """The message was always written for an endpoint open to the internet."""
    from allauth.account.adapter import get_adapter as get_account_adapter

    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=owner_actor,
        connection=sso_connection,
        enforced=True,
    )
    create_user(
        email="staff@acme.com",
        password="a-long-enough-password",  # pragma: allowlist secret
    )

    with pytest.raises(ValidationError) as refusal:
        get_account_adapter().pre_authenticate(
            login_request,
            email="staff@acme.com",
            password="a-long-enough-password",  # pragma: allowlist secret
        )

    spoken = str(refusal.value)
    assert tenant.name not in spoken
    assert sso_connection.name not in spoken


def test_an_address_no_connection_claims_is_not_refused(
    login_request: HttpRequest, sso_connection: SsoConnection
) -> None:
    """The control. A refusal for everybody would pass both tests above."""
    from allauth.account.adapter import get_adapter as get_account_adapter

    create_user(
        email="someone@elsewhere.example",
        password="a-long-enough-password",  # pragma: allowlist secret
    )

    get_account_adapter().pre_authenticate(
        login_request,
        email="someone@elsewhere.example",
        password="a-long-enough-password",  # pragma: allowlist secret
    )
