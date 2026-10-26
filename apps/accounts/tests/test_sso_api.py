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
from apps.accounts.services import create_sso_connection, verify_sso_domain
from apps.accounts.tests.conftest import CLIENT_SECRET
from apps.core.actor import Actor, system_actor
from apps.core.models import Membership, Tenant
from apps.core.tests.unclaimed import unclaimed_role
from apps.core.tests.wire import REQUEST_FIXED_QUERIES

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/auth/sso-connections/"

#: The fixed request cost, then the page and the prefetched domains — constant in the row count.
LIST_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 2

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
    """`email_domains` is a related table: at four connections a per-row read would show."""
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


# --- which of the claims actually route (a domain claim routes nothing until it is verified)
# -----------------------


def test_a_fresh_connection_reports_no_verified_domains(api: Client, owner: Any) -> None:
    """The `201` says what was claimed AND what routes, and they are not the same.

    Claiming reserves a name; an operator verifying it is what makes the
    platform sign-in answer for it. A client that only ever saw `email_domains`
    would have no way to tell "configured" from "working", which is the state a
    tenant's administrator sits in while they wait.
    """
    api.force_login(owner)
    response = api.post(LIST_URL, BODY, content_type="application/json")

    assert response.status_code == 201
    body = response.json()
    assert body["email_domains"] == ["acme.co.uk", "acme.com"]
    assert body["verified_domains"] == []


def test_a_verified_domain_appears_in_verified_domains(
    api: Client, owner: Any, tenant: Tenant
) -> None:
    """One of the two claims verified: the lists differ, and the difference is readable."""
    api.force_login(owner)
    created = api.post(LIST_URL, BODY, content_type="application/json").json()
    connection = SsoConnection.objects.get(pk=created["id"])
    verify_sso_domain(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        domain="acme.com",
    )

    listed = api.get(LIST_URL).json()["items"]
    row = next(item for item in listed if item["id"] == created["id"])
    assert row["email_domains"] == ["acme.co.uk", "acme.com"]
    assert row["verified_domains"] == ["acme.com"]


# --- the wire's `enforced` is what the realm's policy says, released included --


def _materialised(connection_id: str, tenant: Tenant, root_org: Any) -> None:
    """The configuration run as the worker runs it: the activity under the tenant's headers, closed.

    Closed as the workflow's own `_finish` closes it, because a run that stayed
    `running` would make a later ask with the same key the same live run — and
    hide the refusal a landed run's key meets.
    """
    from unittest.mock import patch

    from apps.accounts.activities import apply_identity_config
    from apps.accounts.types import KIND_SSO_CONNECTION, IdentityConfigSync
    from apps.workflows import context as workflow_context
    from apps.workflows.models import WorkflowRun
    from apps.workflows.services import finish_run

    tokens = workflow_context.set_principal(
        tenant_id=str(tenant.pk), user_id=None, org_id=str(root_org.pk)
    )
    try:
        # A worker thread's connection hygiene, stood down on the test's own thread.
        with patch("apps.accounts.activities.close_old_connections", lambda: None):
            apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=connection_id))
    finally:
        workflow_context.reset_principal(tokens)
    running = WorkflowRun.objects.for_tenant(tenant).filter(
        workflow_id__contains=f":identity_config:{connection_id}-",
        status=WorkflowRun.Status.RUNNING,
    )
    for workflow_id in running.values_list("workflow_id", flat=True):
        finish_run(tenant=tenant, workflow_id=workflow_id, status=WorkflowRun.Status.COMPLETED)


def _read_back(api: Client, connection_id: str) -> tuple[bool, str, str]:
    listed = api.get(LIST_URL).json()["items"]
    row = next(one for one in listed if one["id"] == connection_id)
    return row["enforced"], row["sync_state"], row["status"]


@pytest.mark.parametrize("release", ["disable", "un-enforce"])
def test_a_released_wall_reads_enforced_false_once_the_release_lands(
    api: Client, owner: Any, tenant: Tenant, root_org: Any, instance: Any, release: str
) -> None:
    """`enforced` on the wire is the materialised fact — so a released wall reads `false`.

    Disabling a connection, or switching `enforced` off, asks a run that takes the
    provider off the realm's sign-in and gives the password back. Once that run
    has landed the realm no longer requires the provider, and the read-back says
    so rather than repeating the row's standing intent.
    """
    api.force_login(owner)
    created = api.post(LIST_URL, {**BODY, "enforced": False}, content_type="application/json")
    connection_id = created.json()["id"]
    _materialised(connection_id, tenant, root_org)
    url = f"{LIST_URL}{connection_id}/"
    assert api.patch(url, {"enforced": True}, content_type="application/json").status_code == 200
    _materialised(connection_id, tenant, root_org)
    assert _read_back(api, connection_id) == (True, "applied", "active")

    if release == "disable":
        assert api.delete(url).status_code == 204
    else:
        assert (
            api.patch(url, {"enforced": False}, content_type="application/json").status_code == 200
        )
    # The release asked its own run — even where it returns to the intent the
    # connection was created with, whose run landed long ago.
    assert _read_back(api, connection_id)[1] == "pending"
    _materialised(connection_id, tenant, root_org)

    enforced, sync_state, _status = _read_back(api, connection_id)
    assert (enforced, sync_state) == (False, "applied")
    if release == "un-enforce":
        # And the wall goes back up when asked again, through a run of its own.
        assert (
            api.patch(url, {"enforced": True}, content_type="application/json").status_code == 200
        )
        assert _read_back(api, connection_id)[1] == "pending"
        _materialised(connection_id, tenant, root_org)
        assert _read_back(api, connection_id) == (True, "applied", "active")


def test_a_tenant_role_key_arrives_through_the_door(
    api: Client, owner: Any, tenant: Any, owner_actor: Any
) -> None:
    """`default_role` is the open role key the column holds, not a three-word enum on the wire."""
    from apps.core.services import create_role

    auditor = unclaimed_role("auditor")
    create_role(tenant=tenant, actor=owner_actor, key=auditor, name="Auditor")
    api.force_login(owner)
    response = api.post(
        LIST_URL, {**BODY, "default_role": auditor}, content_type="application/json"
    )
    assert response.status_code == 201, response.content
    assert response.json()["default_role"] == auditor


def test_an_unsaid_default_role_is_the_deployments_default(api: Client, owner: Any) -> None:
    from apps.core.authz import default_role_key

    api.force_login(owner)
    body = {key: value for key, value in BODY.items() if key != "default_role"}
    response = api.post(LIST_URL, body, content_type="application/json")
    assert response.status_code == 201, response.content
    assert response.json()["default_role"] == default_role_key()


# --- the PATCH answers the row as the next read finds it ----------------


def test_a_patch_that_drops_a_verified_domain_answers_what_the_next_read_finds(
    api: Client, owner: Any, tenant: Tenant
) -> None:
    """The PATCH body equals the list's row for the same connection, whole."""
    api.force_login(owner)
    created = api.post(LIST_URL, BODY, content_type="application/json").json()
    connection = SsoConnection.objects.get(pk=created["id"])
    verify_sso_domain(
        tenant=tenant, actor=system_actor(tenant), connection=connection, domain="acme.com"
    )

    patched = api.patch(
        f"{LIST_URL}{connection.pk}/",
        {"email_domains": ["acme.co.uk"]},
        content_type="application/json",
    )
    assert patched.status_code == 200, patched.content
    listed = api.get(LIST_URL).json()["items"]
    row = next(item for item in listed if item["id"] == created["id"])

    assert patched.json() == row
    assert row["email_domains"] == ["acme.co.uk"]
    assert row["verified_domains"] == []
