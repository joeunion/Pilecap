"""Home-realm discovery, through the door a login form calls it from.

`POST /api/v1/auth/realm/` is the one route in this app a stranger may call, so
the tests here are as much about **what it does not say** as about what it does.
The equality assertions on the response body are deliberate: a test that only
checked `method` would keep passing on the day somebody helpfully added the
tenant's name to the payload.

**Every address answers `sso` since W2-R5** (ADR ident-6). That is not a
loosening: it is what happens when there stops being a second door. What the
answer still must not do is tell three cases apart — a domain a live connection
claims is the only one that gets a hint, and unclaimed, disabled and
never-heard-of are byte-identical.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.accounts.api import REALM_THROTTLES
from apps.accounts.models import SsoConnection
from apps.accounts.selectors import get_platform_login_url
from apps.accounts.services import disable_sso_connection, sync_identity_config
from apps.accounts.types import KIND_SSO_CONNECTION, IdentityConfigApplied
from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.throttling import AnonRateThrottle

pytestmark = pytest.mark.django_db

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
