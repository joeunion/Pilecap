"""A verified domain claim on a disabled connection confines its people to their tenant's realm."""

from __future__ import annotations

from typing import Any

import pytest
from allauth.core.exceptions import ImmediateHttpResponse

from apps.accounts.adapter import REALM_CLAIM
from apps.accounts.models import STAFF_REALM, SsoConnection, SsoIdentity
from apps.accounts.selectors import (
    get_dormant_claim_tenant,
    get_platform_provider_id,
    get_tenant_realm,
)
from apps.accounts.services import disable_sso_connection
from apps.accounts.tests.conftest import FakeZitadel, assertion
from apps.accounts.tests.test_a9_matrix import adapter, platform_assertion, sso
from apps.core.actor import Actor

pytestmark = pytest.mark.django_db

PERSON = "someone@acme.com"


@pytest.fixture
def dormant(sso_connection: SsoConnection, owner_actor: Actor) -> SsoConnection:
    """The tenant's person provisioned through the connection, then the connection switched off."""
    sso(connection=sso_connection, subject="zitadel|acme-1", email=PERSON)
    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )
    return sso_connection


def test_the_claim_names_its_tenant_while_the_connection_is_off(dormant: SsoConnection) -> None:
    assert get_dormant_claim_tenant(PERSON) == dormant.tenant
    assert get_dormant_claim_tenant("someone@elsewhere.example") is None


def test_a_staff_realm_sign_in_for_a_dormant_claim_is_refused_and_writes_nothing(
    login_request: Any, platform_provider: None, dormant: SsoConnection
) -> None:
    with pytest.raises(ImmediateHttpResponse) as refused:
        adapter(login_request).pre_social_login(
            login_request, platform_assertion(email=PERSON, subject="zitadel|fresh")
        )
    assert b"switched off" in refused.value.response.content
    assert not SsoIdentity.objects.filter(realm=STAFF_REALM, subject="zitadel|fresh").exists()


def test_the_tenants_own_realm_is_not_refused_by_the_dormant_claim(
    instance: FakeZitadel, login_request: Any, platform_provider: None, dormant: SsoConnection
) -> None:
    realm = get_tenant_realm(dormant.tenant)
    assert realm is not None
    signed_in = assertion(
        provider=get_platform_provider_id(),
        subject="zitadel|in-realm",
        email=PERSON,
        extra={REALM_CLAIM: realm.id},
    )
    adapter(login_request).pre_social_login(login_request, signed_in)
    assert signed_in.user is not None
    assert signed_in.user.email == PERSON
