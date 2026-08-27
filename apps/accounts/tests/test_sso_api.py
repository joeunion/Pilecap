"""The SSO configuration door: `/api/v1/auth/sso-connections/`.

The service tests (`test_sso.py`) prove the rules. This module proves they are
the rules **a client meets** — that the door does not authorize differently, does
not widen what an `Out` says, and does not show one tenant another's rows.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import SsoConnection
from apps.accounts.services import create_sso_connection
from apps.accounts.tests.conftest import CLIENT_SECRET
from apps.core.actor import Actor
from apps.core.models import Membership, Tenant

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/auth/sso-connections/"

# One query for the connections page and one for the prefetched domains, plus
# the session, the user, the membership `TenantMiddleware` resolves the tenant
# from, the one `resolve_org` resolves the acting ORG from (the hierarchy's
# standing per-request cost), and the SAVEPOINT `ATOMIC_REQUESTS` opens with the
# RELEASE that closes it. Eight.
# Measured, not guessed — and it is a *budget*: the point is that adding a
# second connection below does not move it, which is what an N+1 on
# `email_domains` would do.
# ADR core-18 took the COUNT off this pin: the default list issues none any
# more — `has_more` comes from fetching one row more than asked for.
# `?include_count=true` puts it back, and costs exactly one more (nine).
LIST_QUERY_BUDGET = 8

# How many connections the query pin is measured at. More than one, because a
# budget measured at one row cannot tell a constant from a linear cost.
SEEDED_CONNECTIONS = 4

BODY: dict[str, Any] = {
    "name": "Acme Okta",
    "issuer": "https://idp.acme.example",
    "client_id": "acme-client-id",
    "client_secret": CLIENT_SECRET,
    "email_domains": ["acme.com", "acme.co.uk"],
    "default_role": "member",
    "enforced": False,
}


def test_an_owner_can_configure_one(api: Client, owner: Any) -> None:
    api.force_login(owner)
    response = api.post(LIST_URL, BODY, content_type="application/json")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Okta"
    assert body["email_domains"] == ["acme.co.uk", "acme.com"]
    assert body["has_client_secret"] is True
    assert body["status"] == "active"


def test_the_response_never_carries_the_secret(api: Client, owner: Any) -> None:
    """Asserted on the raw body, so a field added later cannot smuggle it out."""
    api.force_login(owner)
    raw = api.post(LIST_URL, BODY, content_type="application/json").content.decode()
    assert CLIENT_SECRET not in raw


def test_a_member_is_refused_at_the_door_with_the_same_answer(api: Client, member: Any) -> None:
    """403 from `policies.py`, not from a check the route made up.

    The door authenticates and resolves the tenant; the service authorizes. A
    route that carried its own role check would be the same violation from the
    other side — and would drift from the MCP tool and the admin.
    """
    api.force_login(member)
    response = api.post(LIST_URL, BODY, content_type="application/json")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert SsoConnection.objects.for_tenant(None).count() == 0


def test_a_member_may_still_read_the_list(
    api: Client, member: Any, sso_connection: SsoConnection
) -> None:
    """Reads are a `view`-shaped action, and the secret is not in the shape."""
    api.force_login(member)
    body = api.get(LIST_URL).json()
    assert [row["id"] for row in body["items"]] == [str(sso_connection.pk)]
    assert "client_secret" not in body["items"][0]


def test_the_list_is_scoped_to_the_acting_tenant(
    api: Client,
    owner: Any,
    sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
) -> None:
    """The test that cannot pass vacuously: two tenants, two connections, one answer."""
    api.force_login(owner)
    body = api.get(LIST_URL).json()

    assert [row["id"] for row in body["items"]] == [str(sso_connection.pk)]
    assert len(body["items"]) == 1


def test_another_tenants_connection_is_not_found_rather_than_forbidden(
    api: Client, owner: Any, other_sso_connection: SsoConnection
) -> None:
    """A 403 here would confirm the row exists, which is the whole of what is secret."""
    api.force_login(owner)
    response = api.patch(
        f"{LIST_URL}{other_sso_connection.pk}/",
        {"enforced": True},
        content_type="application/json",
    )
    assert response.status_code == 404


def test_the_list_pays_the_same_query_count_however_many_rows(
    api: Client,
    owner: Any,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
    django_assert_num_queries: Any,
) -> None:
    """`email_domains` is derived from a related table, so it is an N+1 waiting to happen.

    The budget is measured, not guessed: the page, the prefetched domains, the
    session, the user, the membership `TenantMiddleware` resolves the tenant
    from, the one `resolve_org` resolves the acting org from, and the
    `ATOMIC_REQUESTS` savepoint and its release — eight, with the `count` off by
    default since ADR core-18. What makes it a *pin*
    rather than a number is the seeded scale — a per-row query would put this
    well past the budget at four connections, and exactly at it with one.
    """
    for index in range(SEEDED_CONNECTIONS - 1):
        create_sso_connection(
            tenant=tenant,
            actor=owner_actor,
            name=f"Acme spare {index}",
            issuer=f"https://idp{index}.acme.example",
            client_id=f"spare-{index}",
            client_secret=f"spare-{index}",
            email_domains=[f"acme{index}.dev", f"acme{index}.net"],
            default_role=Membership.Role.MEMBER,
        )
    api.force_login(owner)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        response = api.get(LIST_URL)

    assert len(response.json()["items"]) == SEEDED_CONNECTIONS


def test_disabling_through_the_door_leaves_the_row(
    api: Client, owner: Any, sso_connection: SsoConnection
) -> None:
    api.force_login(owner)
    assert api.delete(f"{LIST_URL}{sso_connection.pk}/").status_code == 204

    sso_connection.refresh_from_db()
    assert sso_connection.status == SsoConnection.Status.DISABLED
    assert sso_connection.disabled_at is not None
    assert len(api.get(LIST_URL).json()["items"]) == 1


def test_an_omitted_secret_leaves_the_stored_one_alone(
    api: Client, owner: Any, sso_connection: SsoConnection
) -> None:
    """Nothing can read the secret back to re-send it, so "omitted" can only mean this."""
    api.force_login(owner)
    response = api.patch(
        f"{LIST_URL}{sso_connection.pk}/",
        {"name": "Acme Okta (renamed)"},
        content_type="application/json",
    )

    assert response.status_code == 200
    sso_connection.refresh_from_db()
    assert sso_connection.name == "Acme Okta (renamed)"
    assert sso_connection.client_secret == CLIENT_SECRET


def test_a_domain_another_tenant_claims_is_a_409(
    api: Client, owner: Any, other_sso_connection: SsoConnection
) -> None:
    """The service's `Conflict`, mapped once by `config/api.py` and not per route."""
    api.force_login(owner)
    response = api.post(
        LIST_URL,
        {**BODY, "email_domains": ["globex.com"]},
        content_type="application/json",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_a_request_with_no_tenant_is_refused_rather_than_guessed_at(
    api: Client, nomad: Any
) -> None:
    api.force_login(nomad)
    assert api.post(LIST_URL, BODY, content_type="application/json").status_code == 403
