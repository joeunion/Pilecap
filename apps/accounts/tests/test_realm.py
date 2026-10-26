"""Home-realm discovery, through the door a login form calls it from.

`POST /api/v1/auth/realm/` is the one route in this app a stranger may call, so
the tests here are as much about **what it does not say** as about what it does.
The equality assertions on the response body are deliberate: a test that only
checked `method` would keep passing on the day somebody helpfully added the
tenant's name to the payload.

**Every address answers `sso`** (ADR ident-6). That is not a
loosening: it is what happens when there stops being a second door. What the
answer still must not do is tell three cases apart — a domain a live connection
claims is the only one that gets a hint, and unclaimed, disabled and
never-heard-of are byte-identical.

**And the realm itself, one level down** (identity option B): the identity realm
port (`apps.accounts.realm.IdentityRealm`) and its Zitadel adapter, driven over
`FakeZitadel`, whose organisations, grants, per-org login policies, links and
`x-zitadel-orgid` scoping are transcribed from the adapter's live drive against
the pinned stack. Every operation is driven twice, because the property each
one owes an at-least-once caller is that the second call leaves what the first
did.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from allauth.socialaccount.providers.openid_connect.provider import OpenIDConnectProvider
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts import realms, zitadel
from apps.accounts.api import REALM_THROTTLES
from apps.accounts.models import SsoConnection
from apps.accounts.realm import IdentityRealm, LoginPolicy, ProviderRef, RealmRef
from apps.accounts.realms.zitadel import SIGN_IN_SCOPES, ZitadelRealm, realm_name
from apps.accounts.selectors import authorize_url_for, get_platform_login_url
from apps.accounts.services import disable_sso_connection, sync_identity_config
from apps.accounts.tests.conftest import FakeZitadel
from apps.accounts.types import KIND_SSO_CONNECTION, IdentityConfigApplied
from apps.core.actor import Actor
from apps.core.exceptions import Invalid
from apps.core.models import Tenant
from apps.core.surfaces import Surface
from apps.core.tests.test_surfaces import CUSTOMER_HOST, STAFF_HOST, customer_role, two_faces
from apps.core.throttling import AnonRateThrottle

pytestmark = pytest.mark.django_db

#: The realm port is this module's subject, measured from a tenant with no
#: realm yet — the `instance` fixture leaves its tenants un-homed here.
HOMES_ITS_OWN_REALMS = True

REALM_URL = "/api/v1/auth/realm/"


def _post(api: Client, email: str) -> Any:
    return api.post(REALM_URL, {"email": email}, content_type="application/json")


def test_the_route_is_where_the_router_put_it() -> None:
    """Named, so remounting the router does not silently move the contract."""
    assert reverse("api:realm-discover") == REALM_URL


def test_an_address_in_a_claimed_domain_is_sent_to_its_provider(
    api: Client, sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    """The platform door, carrying the hint that skips Zitadel's provider picker.

    The hint is the connection's **Zitadel** id, put on the row by the activity,
    so it only exists once the materialisation has landed — which is why the
    outcome is recorded here rather than assumed.
    """
    sync_identity_config(
        tenant=sso_connection.tenant,
        actor=owner_actor,
        connection=sso_connection,
        applied=IdentityConfigApplied(
            kind=KIND_SSO_CONNECTION,
            key=str(sso_connection.pk),
            resource_id="387100000000000009",
        ),
    )

    response = _post(api, "someone@acme.com")

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sso"
    assert body["connection_id"] == str(sso_connection.pk)
    assert body["authorize_url"] == (
        f"{get_platform_login_url()}?auth_params=idp_hint%3D387100000000000009"
    )


def test_the_answer_says_nothing_about_the_tenant(
    api: Client, sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """The whole security argument for `auth=None` on this route, as an assertion.

    Stated as an exact key set plus a substring sweep, because the failure this
    guards against is additive: somebody returning the connection's name to make
    a nicer button, and turning a login box into a customer directory.
    """
    body = _post(api, "someone@acme.com").json()

    assert set(body) == {"method", "connection_id", "authorize_url"}
    rendered = str(body)
    assert tenant.name not in rendered
    assert tenant.slug not in rendered
    assert sso_connection.name not in rendered
    assert sso_connection.issuer not in rendered
    assert sso_connection.client_id not in rendered


def test_an_address_with_no_connection_gets_the_platform_door(
    api: Client, sso_connection: SsoConnection
) -> None:
    """Which is where everybody signs in — there is no second door to route to."""
    body = _post(api, "someone@elsewhere.example").json()
    assert body == {
        "method": "sso",
        "connection_id": None,
        "authorize_url": get_platform_login_url(),
    }


def test_a_domain_nobody_has_ever_claimed_is_indistinguishable_from_one_without_sso(
    api: Client, sso_connection: SsoConnection, other_tenant: Tenant
) -> None:
    """Both are the plain platform door, byte for byte.

    If "we have never heard of that domain" and "that customer has no SSO" gave
    different answers, the route would enumerate the customer list one guess at
    a time.
    """
    never_seen = _post(api, "someone@no-such-domain.example").json()
    known_without_sso = _post(api, "stranger@example.com").json()
    assert (
        never_seen
        == known_without_sso
        == {
            "method": "sso",
            "connection_id": None,
            "authorize_url": get_platform_login_url(),
        }
    )


def test_a_disabled_connection_is_indistinguishable_from_no_connection(
    api: Client, sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    """The third member of the negative set, and the one that leaks if it differs.

    A customer mid-migration keeps their domain claims (`disable_sso_connection`
    says why), so the row is still there and still claiming acme.com. What a
    stranger gets back must not say so.
    """
    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )
    assert _post(api, "someone@acme.com").json() == _post(api, "nobody@nowhere.example").json()


def test_it_needs_no_credential(api: Client, sso_connection: SsoConnection) -> None:
    """The point of the `rule-3` override: a login form has nobody signed in yet."""
    assert _post(api, "someone@acme.com").status_code == 200


def test_rubbish_in_is_a_400_not_a_500(api: Client) -> None:
    assert api.post(REALM_URL, {}, content_type="application/json").status_code == 422


def test_it_is_throttled(api: Client, sso_connection: SsoConnection) -> None:
    """A one-bit answer per request is a domain list at network speed without this.

    The throttle instance is reconfigured rather than the settings, because a
    `SimpleRateThrottle` reads its rate once, when it is constructed — which is
    import time. Reconfiguring the object is the only way to assert on the
    wiring rather than on a copy of it.
    """
    # The list is typed as the base class (ninja's `throttle=` is invariant);
    # the object in it is the rate throttle, which is what has the two knobs.
    throttle = cast(AnonRateThrottle, REALM_THROTTLES[0])
    original = (throttle.num_requests, throttle.duration)
    throttle.num_requests, throttle.duration = 2, 60
    cache.clear()
    try:
        assert _post(api, "a@acme.com").status_code == 200
        assert _post(api, "b@acme.com").status_code == 200
        refused = _post(api, "c@acme.com")
        assert refused.status_code == 429
        # The same body shape a service's own `RateLimited` produces, so a client
        # that handles one handles both.
        assert refused.json()["code"] == "rate_limited"
        assert refused["Retry-After"]
    finally:
        throttle.num_requests, throttle.duration = original
        cache.clear()


# --- the identity realm port, and its Zitadel adapter ---------------------------

#: THE instrument for the port's size, and the one place in this module a typed
#: list is the right tool: a new member on the port is the change a reviewer
#: must read, so it reds here by name rather than riding in unseen. The list is
#: the port's operations as the design names them (the ruled bound); the test
#: derives the port's actual members and compares.
PORT_OPERATIONS = sorted(
    [
        "ensure_realm",
        "grant_platform",
        "set_login_policy",
        "attach_provider",
        "detach_provider",
        "provision_person",
        "deactivate_person",
        "authorize_params",
        "facts",
    ]
)

# Re-exported so pytest finds the core module's fixtures here without a second
# copy of them: the customer surface declared and its host bound.
__all__ = ["customer_role", "two_faces"]


@pytest.fixture
def adapter(instance: FakeZitadel, settings: Any) -> ZitadelRealm:
    """The Zitadel adapter over the fake, with the deployment's project made."""
    zitadel.ensure_project(name=settings.ZITADEL_PROJECT_NAME)
    return ZitadelRealm()


@pytest.fixture
def realm(adapter: ZitadelRealm, tenant: Tenant) -> RealmRef:
    return adapter.ensure_realm(tenant=tenant)


def _requests(fake: FakeZitadel, method: str, path: str) -> int:
    return sum(1 for sent in fake.requests if sent == (method, path))


def _blind_once(read: Callable[..., Any]) -> Callable[..., Any]:
    """`read`, answering `None` the first time: the search that lost a race to a create."""
    calls: list[None] = []

    def blind(**kwargs: Any) -> Any:
        calls.append(None)
        return None if len(calls) == 1 else read(**kwargs)

    return blind


def test_the_port_is_exactly_its_operations() -> None:
    """A member is added by editing `PORT_OPERATIONS` too, where a reviewer sees it."""
    members = sorted(
        name
        for name, value in vars(IdentityRealm).items()
        if not name.startswith("_") and callable(value)
    )
    assert members == PORT_OPERATIONS


def test_the_deployment_runs_the_zitadel_adapter_unless_it_names_another(settings: Any) -> None:
    assert isinstance(realms.current(), ZitadelRealm)
    assert isinstance(ZitadelRealm(), IdentityRealm)

    for wrong in ("builtins.object", "apps.accounts.realms.zitadel.ZitadelRealmm"):
        settings.IDENTITY_REALM_ADAPTER = wrong
        with pytest.raises(ImproperlyConfigured, match="IDENTITY_REALM_ADAPTER"):
            realms.current()


def test_a_tenant_twice_is_one_realm(
    adapter: ZitadelRealm, instance: FakeZitadel, tenant: Tenant, settings: Any
) -> None:
    """Search, then create: the second run finds the first run's organisation."""
    before = len(instance.orgs)

    first = adapter.ensure_realm(tenant=tenant)
    second = adapter.ensure_realm(tenant=tenant)

    assert first == second
    assert len(instance.orgs) == before + 1
    assert first.issuer == zitadel.issuer() == "http://zitadel.test"
    assert zitadel.find_organization(name=realm_name(tenant)) == {
        "id": first.id,
        "name": f"{settings.ZITADEL_PROJECT_NAME} {tenant.slug}",
        "state": "ORG_STATE_ACTIVE",
    }


def test_a_realm_whose_create_lost_a_race_is_the_winners(
    instance: FakeZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second net: a create answered `409 V3-DKcYh` searches again and adopts."""
    made = zitadel.ensure_organization(name="raced")
    monkeypatch.setattr(zitadel, "find_organization", _blind_once(zitadel.find_organization))

    again = zitadel.ensure_organization(name="raced")

    assert again.id == made.id and again.created is False
    assert [row["name"] for row in instance.orgs].count("raced") == 1


def test_the_platform_granted_twice_is_one_grant(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second grant is refused by Zitadel (`409 V3-DKcYh`), which is the state asked for."""
    adapter.grant_platform(realm=realm)
    adapter.grant_platform(realm=realm)
    # The race: the search misses, the create is refused, the grant is found.
    monkeypatch.setattr(zitadel, "project_grant", _blind_once(zitadel.project_grant))
    adapter.grant_platform(realm=realm)

    granted = [row for row in instance.grants.values() if row["grantedOrgId"] == realm.id]
    assert len(granted) == 1
    assert adapter.facts(realm=realm).granted is True


def test_the_project_check_is_switched_on_with_the_whole_body(
    adapter: ZitadelRealm, instance: FakeZitadel, settings: Any
) -> None:
    """The whole field set sent, the name kept; the second call sends nothing."""
    project = zitadel.find_project(name=settings.ZITADEL_PROJECT_NAME)
    assert project is not None
    path = f"/projects/{project['id']}"

    first = zitadel.set_project_check(project_id=str(project["id"]))
    second = zitadel.set_project_check(project_id=str(project["id"]))

    (sent,) = [body for method, where, body in instance.bodies if (method, where) == ("PUT", path)]
    assert set(sent) == zitadel.PROJECT_FIELDS
    assert sent["name"] == settings.ZITADEL_PROJECT_NAME and sent["hasProjectCheck"] is True
    assert (first.updated, second.updated) == (True, False)
    assert zitadel.get_project(project_id=str(project["id"]))["hasProjectCheck"] is True


def test_a_realm_is_given_its_own_policy_with_the_other_fields_carried(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel
) -> None:
    """The create carries every inherited field and both factor lists; ours are the two."""
    inherited = dict(instance.instance_login_policy)
    home = dict(instance.org_login_policy)

    adapter.set_login_policy(
        realm=realm, policy=LoginPolicy(password_allowed=False, provider_required=True)
    )

    own = instance.realm_login_policies[realm.id]
    ours = {"allowUsernamePassword", "allowExternalIdp"}
    for key, absent in zitadel.LOGIN_POLICY_ABSENT.items():
        if key not in ours:
            assert own.get(key, absent) == inherited.get(key, absent), key
    for key in zitadel.LOGIN_POLICY_FACTOR_LISTS:
        assert own[key] == inherited[key], key
    assert own.get("allowUsernamePassword", False) is False
    assert own["allowExternalIdp"] is True
    assert instance.org_login_policy == home, "the staff org's policy moved"


def test_a_realms_policy_flips_by_update_and_a_repeat_writes_nothing(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel
) -> None:
    enforced = LoginPolicy(password_allowed=False, provider_required=True)
    released = LoginPolicy(password_allowed=True, provider_required=False)
    adapter.set_login_policy(realm=realm, policy=enforced)

    adapter.set_login_policy(realm=realm, policy=released)
    adapter.set_login_policy(realm=realm, policy=released)

    assert _requests(instance, "POST", "/policies/login") == 1
    assert _requests(instance, "PUT", "/policies/login") == 1
    assert adapter.facts(realm=realm).policy == released


@pytest.mark.parametrize(
    "policy",
    [
        LoginPolicy(password_allowed=False, provider_required=False),
        LoginPolicy(password_allowed=True, provider_required=True),
    ],
    ids=["admits-nobody", "required-and-optional"],
)
def test_a_policy_that_is_not_one_of_the_two_is_refused_before_anything_is_dialled(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel, policy: LoginPolicy
) -> None:
    sent = len(instance.requests)

    with pytest.raises(Invalid) as refused:
        adapter.set_login_policy(realm=realm, policy=policy)

    assert refused.value.code == "invalid" and "policy" in refused.value.errors
    assert len(instance.requests) == sent


def test_a_provider_attached_twice_is_one_provider_in_the_realm_and_one_link(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel, sso_connection: SsoConnection
) -> None:
    adapter.set_login_policy(
        realm=realm, policy=LoginPolicy(password_allowed=True, provider_required=False)
    )

    first = adapter.attach_provider(realm=realm, connection=sso_connection)
    second = adapter.attach_provider(realm=realm, connection=sso_connection)

    assert first == second
    assert instance.login_policy_idps[realm.id] == [first.id]
    assert zitadel.get_identity_provider(idp_id=first.id, org_id=realm.id)
    # The realm's provider is the realm's: the staff org cannot see it.
    assert zitadel.get_identity_provider(idp_id=first.id) is None
    assert adapter.facts(realm=realm).providers == (first,)


def test_a_provider_is_not_attached_to_a_realm_that_still_inherits(
    adapter: ZitadelRealm, realm: RealmRef, sso_connection: SsoConnection
) -> None:
    """The link is refused and said so; nothing forks the realm a policy on the way."""
    with pytest.raises(zitadel.ZitadelError, match="ensure_login_policy"):
        adapter.attach_provider(realm=realm, connection=sso_connection)

    assert adapter.facts(realm=realm).policy is None


def test_a_provider_detached_twice_is_unlinked_and_kept(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel, sso_connection: SsoConnection
) -> None:
    adapter.set_login_policy(
        realm=realm, policy=LoginPolicy(password_allowed=False, provider_required=True)
    )
    provider = adapter.attach_provider(realm=realm, connection=sso_connection)

    adapter.detach_provider(realm=realm, provider=provider)
    adapter.detach_provider(realm=realm, provider=provider)

    assert adapter.facts(realm=realm).providers == ()
    assert provider.id in instance.idps


def test_a_person_provisioned_twice_is_one_person_in_the_realm(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel
) -> None:
    """One person; a fresh link each time (Zitadel supersedes the code) — the named exception."""
    first = adapter.provision_person(
        realm=realm, email="pat@acme.com", names=("Pat", "Lee"), surface="staff"
    )
    second = adapter.provision_person(
        realm=realm, email="pat@acme.com", names=("Pat", "Lee"), surface="staff"
    )

    assert first.subject == second.subject
    assert first.set_credentials_url != second.set_credentials_url
    assert first.set_credentials_url.startswith(f"http://zitadel.test{zitadel.INVITE_PATH}?")
    assert zitadel.find_user(username="pat@acme.com", org_id=realm.id)
    assert zitadel.find_user(username="pat@acme.com") is None, "the staff org sees the person"


def test_a_person_with_credentials_gets_no_link(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel
) -> None:
    person = adapter.provision_person(
        realm=realm, email="pat@acme.com", names=("Pat", "Lee"), surface="staff"
    )
    instance.initialized_users.add(person.subject)

    again = adapter.provision_person(
        realm=realm, email="pat@acme.com", names=("Pat", "Lee"), surface="staff"
    )

    assert again.subject == person.subject and again.set_credentials_url == ""


def test_the_credential_link_lands_on_the_surface_the_person_was_invited_to(
    adapter: ZitadelRealm, realm: RealmRef, settings: Any, two_faces: Surface
) -> None:
    """Under our own entrance the link is built by the one URL builder, on the surface's host."""
    settings.SIGN_IN_DOOR = "ours"

    customer = adapter.provision_person(
        realm=realm, email="kim@acme.com", names=("Kim", "Ray"), surface=two_faces.key
    )
    staff = adapter.provision_person(
        realm=realm, email="sam@acme.com", names=("Sam", "Ray"), surface="staff"
    )

    link = urlsplit(customer.set_credentials_url)
    assert (link.hostname, link.path) == (CUSTOMER_HOST, reverse("account_login"))
    assert urlsplit(staff.set_credentials_url).hostname == STAFF_HOST


def test_a_person_deactivated_twice_is_deactivated_in_their_realm(
    adapter: ZitadelRealm, realm: RealmRef, instance: FakeZitadel
) -> None:
    """The realm is named on the call: without it the person is not found, and stays live."""
    person = adapter.provision_person(
        realm=realm, email="pat@acme.com", names=("Pat", "Lee"), surface="staff"
    )

    unnamed = zitadel.deactivate_user(user_id=person.subject)
    assert person.subject not in instance.deactivated_users, unnamed

    adapter.deactivate_person(realm=realm, subject=person.subject)
    adapter.deactivate_person(realm=realm, subject=person.subject)

    assert person.subject in instance.deactivated_users


def test_the_sign_in_request_is_confined_to_the_realm(
    adapter: ZitadelRealm, realm: RealmRef
) -> None:
    """The org scope rides beside the scopes allauth would have asked for itself."""
    params = adapter.authorize_params(realm=realm)

    assert params == {"scope": f"openid profile email urn:zitadel:iam:org:id:{realm.id}"}
    default = OpenIDConnectProvider.__new__(OpenIDConnectProvider).get_default_scope()
    assert list(SIGN_IN_SCOPES) == default


def test_the_facts_read_a_whole_realm_back(
    adapter: ZitadelRealm, realm: RealmRef, sso_connection: SsoConnection
) -> None:
    """Before the home workflow's steps a realm exists and nothing else; after, all of it."""
    bare = adapter.facts(realm=realm)
    assert (bare.exists, bare.granted, bare.policy, bare.providers) == (True, False, None, ())

    enforced = LoginPolicy(password_allowed=False, provider_required=True)
    adapter.grant_platform(realm=realm)
    adapter.set_login_policy(realm=realm, policy=enforced)
    provider = adapter.attach_provider(realm=realm, connection=sso_connection)

    whole = adapter.facts(realm=realm)
    assert (whole.exists, whole.granted, whole.policy, whole.providers) == (
        True,
        True,
        enforced,
        (ProviderRef(id=provider.id),),
    )


def test_a_realm_the_platform_no_longer_holds_is_said_not_to_exist(
    adapter: ZitadelRealm,
) -> None:
    gone = RealmRef(id="424242", issuer=zitadel.issuer())

    facts = adapter.facts(realm=gone)

    assert (facts.exists, facts.granted, facts.policy, facts.providers) == (False, False, None, ())


def test_a_connection_link_lands_on_a_staff_host_named_by_its_tenant(
    sso_connection: SsoConnection,
) -> None:
    """A `{tenant}`-slot staff host gets the connection's tenant, never a `ValueError`."""
    with override_settings(SURFACE_HOSTS={"staff": "{tenant}.staff.example.test"}):
        url = authorize_url_for(sso_connection)

    assert urlsplit(url).hostname == f"{sso_connection.tenant.slug}.staff.example.test"
