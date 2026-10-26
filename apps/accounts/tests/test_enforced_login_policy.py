"""`enforced` is the tenant realm's login policy — not a promise with no wall.

The consumer's case: switching `enforced` on changed nothing anywhere —
the row said it, the wire read it back, and every person it covered went on
signing in with a password. With a realm per tenant it is the realm's own login
policy (password off, the provider required), written by the configuration run
after the provider has landed, read back as the MATERIALISED fact, compared by
the audit, and released on disable and on un-enforce.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.test import Client

from apps.accounts import zitadel
from apps.accounts.activities import apply_identity_config
from apps.accounts.models import SsoConnection
from apps.accounts.schemas import SsoConnectionOut
from apps.accounts.selectors import get_realm_for_email, get_tenant_realm
from apps.accounts.services import (
    EnforcedWithoutProvider,
    create_sso_connection,
    disable_sso_connection,
    update_sso_connection,
)
from apps.accounts.tests.conftest import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeZitadel
from apps.accounts.types import KIND_SSO_CONNECTION, IdentityConfigSync
from apps.core.actor import Actor
from apps.core.audit import AuditEntry
from apps.core.models import Organization, Tenant
from apps.workflows import context as workflow_context
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

#: The two fields `enforced` decides; every other field of the policy is carried
#: back as it was (the full-body law).
DECIDED = frozenset({"allowUsernamePassword", "allowExternalIdp"})


@pytest.fixture
def acting(tenant: Tenant, root_org: Organization) -> Iterator[None]:
    """The workflow headers the interceptor would have restored for the tenant's run."""
    tokens = workflow_context.set_principal(
        tenant_id=str(tenant.pk), user_id=None, org_id=str(root_org.pk)
    )
    yield
    workflow_context.reset_principal(tokens)


def _materialise(connection: SsoConnection) -> None:
    """The configuration run's activity, as the worker would run it."""
    apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(connection.pk)))
    connection.refresh_from_db()


def _realm_policy(fake: FakeZitadel, tenant: Tenant) -> dict[str, Any]:
    realm = get_tenant_realm(tenant)
    assert realm is not None
    return fake.realm_login_policies[realm.id]


@pytest.fixture
def landed(
    instance: FakeZitadel, homed: str, acting: None, tenant: Tenant, owner_actor: Actor
) -> SsoConnection:
    """A connection whose provider has reached the tenant's realm — where a flip can begin."""
    connection = create_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        name="Acme Okta",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["acme.com"],
    )
    _materialise(connection)
    assert connection.zitadel_idp_id
    assert connection.sync_state == SsoConnection.SyncState.APPLIED
    return connection


# --- no provider, no wall ------------------------------------------------------


def test_enforcing_a_connection_with_no_provider_is_refused_and_writes_nothing(
    instance: FakeZitadel, tenant: Tenant, owner_actor: Actor, owner: Any, api: Client
) -> None:
    """RED on main: the flip succeeded and nothing anywhere changed."""
    connection = create_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        name="Acme Okta",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["acme.com"],
    )
    assert connection.zitadel_idp_id == ""
    assert connection.sync_state != SsoConnection.SyncState.APPLIED
    runs = WorkflowRun.objects.count()
    requests = len(instance.requests)

    with pytest.raises(EnforcedWithoutProvider) as refused:
        update_sso_connection(
            tenant=tenant, actor=owner_actor, connection=connection, enforced=True
        )

    connection.refresh_from_db()
    assert refused.value.code == "enforced_without_provider"
    assert connection.enforced is False
    assert WorkflowRun.objects.count() == runs, "a refused write leaves no run"
    assert len(instance.requests) == requests, "and dials nothing"
    assert (
        not AuditEntry.objects.for_tenant(tenant)
        .filter(action="accounts.update_sso_connection", outcome="ok")
        .exists()
    )

    # The REST door answers the registered refusal in the one envelope.
    api.force_login(owner)
    response = api.patch(
        f"/api/v1/auth/sso-connections/{connection.pk}/",
        {"enforced": True},
        content_type="application/json",
    )
    body = response.json()
    assert (response.status_code, body["code"]) == (409, "enforced_without_provider")
    assert body["remedies"], "the refusal says what the caller can do"


def test_the_refusal_is_registered_with_its_status_and_remedies() -> None:
    from apps.core.exceptions import CODE_STATUSES, refusal_for

    refusal = refusal_for("enforced_without_provider")
    assert refusal is not None
    assert CODE_STATUSES["enforced_without_provider"] == 409
    assert refusal.fact and refusal.remedies


# --- the flip is an intent the run materialises in the tenant's realm ----------


def test_the_flip_writes_the_realm_policy_and_nobody_elses(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    before = dict(_realm_policy(instance, tenant))
    staff_before = dict(instance.org_login_policy)

    update_sso_connection(tenant=tenant, actor=owner_actor, connection=landed, enforced=True)
    landed.refresh_from_db()
    assert landed.sync_state == SsoConnection.SyncState.PENDING
    audited = AuditEntry.objects.for_tenant(tenant).filter(
        action="accounts.update_sso_connection", outcome="ok"
    )
    assert audited.filter(input__enforced=True).exists()

    _materialise(landed)

    after = _realm_policy(instance, tenant)
    assert after.get("allowUsernamePassword", False) is False
    assert after.get("allowExternalIdp") is True
    # The negative that is the whole point: the deployment's own org kept its password.
    assert instance.org_login_policy == staff_before
    # The provider is linked on the realm's sign-in.
    realm = get_tenant_realm(tenant)
    assert realm is not None
    assert landed.zitadel_idp_id in instance.login_policy_idps[realm.id]
    # Every field `enforced` does not decide was carried back as it was.
    written = [
        body
        for method, path, body in instance.bodies
        if method == "PUT" and path == "/policies/login"
    ][-1]
    carried = zitadel.LOGIN_POLICY_FIELDS - DECIDED
    assert carried <= set(written)
    for field in carried:
        assert written[field] == before.get(field, zitadel.LOGIN_POLICY_ABSENT[field]), field


def test_the_run_refuses_to_enforce_when_the_provider_is_not_linked(
    instance: FakeZitadel,
    landed: SsoConnection,
    tenant: Tenant,
    owner_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second wall: the window between the write and the run."""
    update_sso_connection(tenant=tenant, actor=owner_actor, connection=landed, enforced=True)
    realm = get_tenant_realm(tenant)
    assert realm is not None

    def linking_nothing(*, org_id: str, idp_id: str) -> zitadel.Resource:
        return zitadel.Resource(id=idp_id, created=False)

    monkeypatch.setattr(zitadel, "link_idp_to_login_policy", linking_nothing)
    instance.login_policy_idps[realm.id] = []
    with pytest.raises(Exception, match="nothing was enforced"):
        _materialise(landed)
    assert _realm_policy(instance, tenant).get("allowUsernamePassword") is True


# --- the read-back is the materialised fact -------------------------------------


def test_the_wire_reads_false_and_pending_until_the_run_lands(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant, owner: Any, api: Client
) -> None:
    api.force_login(owner)
    url = f"/api/v1/auth/sso-connections/{landed.pk}/"

    flipped = api.patch(url, {"enforced": True}, content_type="application/json").json()
    assert (flipped["enforced"], flipped["sync_state"]) == (False, "pending")

    _materialise(landed)
    listed = api.get("/api/v1/auth/sso-connections/").json()["items"]
    row = next(one for one in listed if one["id"] == str(landed.pk))
    assert (row["enforced"], row["sync_state"]) == (True, "applied")
    assert SsoConnectionOut.from_orm(landed).enforced is True


def test_the_audit_compares_enforced_against_the_realm(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    update_sso_connection(tenant=tenant, actor=owner_actor, connection=landed, enforced=True)
    _materialise(landed)
    realm = get_tenant_realm(tenant)
    assert realm is not None

    out = StringIO()
    try:
        call_command("zitadel_audit", tenant=tenant.slug, stdout=out)
    except SystemExit:
        pass
    assert (
        f"agrees      enforced — org {realm.id} policy allowUsernamePassword=false "
        "allowExternalIdp=true" in out.getvalue()
    )

    # A console edit that gives the password back is drift, named.
    instance.realm_login_policies[realm.id]["allowUsernamePassword"] = True
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("zitadel_audit", tenant=tenant.slug, stdout=out)
    assert "DRIFT       enforced — our row says on" in out.getvalue()


# --- the sign-in names the enforcing realm --------------------------------------


def test_a_claimed_address_signs_in_confined_to_its_tenants_realm(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant
) -> None:
    from apps.accounts.tests.conftest import _verified

    _verified(landed)
    realm = get_tenant_realm(tenant)
    assert realm is not None

    claimed = get_realm_for_email("ada@acme.com")
    stranger = get_realm_for_email("ada@elsewhere.example")

    assert f"urn%253Azitadel%253Aiam%253Aorg%253Aid%253A{realm.id}" in claimed.authorize_url
    assert "urn" not in stranger.authorize_url, "an unknown address sends today's scopes"


# --- disable and un-enforce release the wall ------------------------------------


def test_un_enforcing_gives_the_password_back(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    update_sso_connection(tenant=tenant, actor=owner_actor, connection=landed, enforced=True)
    _materialise(landed)
    assert _realm_policy(instance, tenant).get("allowUsernamePassword", False) is False

    update_sso_connection(tenant=tenant, actor=owner_actor, connection=landed, enforced=False)
    _materialise(landed)

    assert _realm_policy(instance, tenant)["allowUsernamePassword"] is True


def test_disabling_detaches_the_provider_and_gives_the_password_back(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    """The release is the provider taken off the realm's sign-in, never the legacy call."""
    update_sso_connection(tenant=tenant, actor=owner_actor, connection=landed, enforced=True)
    _materialise(landed)
    realm = get_tenant_realm(tenant)
    assert realm is not None

    disable_sso_connection(tenant=tenant, actor=owner_actor, connection=landed)
    _materialise(landed)

    assert landed.zitadel_idp_id not in instance.login_policy_idps.get(realm.id, [])
    assert _realm_policy(instance, tenant)["allowUsernamePassword"] is True
    legacy = [path for method, path in instance.requests if path.endswith("/_deactivate")]
    assert not [path for path in legacy if path.startswith("/idps/")]


def test_the_legacy_deactivate_over_an_active_template_is_never_read_as_done(
    instance: FakeZitadel, landed: SsoConnection, tenant: Tenant
) -> None:
    """Measured: `400 Errors.Org.IDPConfig.NotActive (Org-BBmd0)` while the IdP is ACTIVE."""
    realm = get_tenant_realm(tenant)
    assert realm is not None
    staff_idp = zitadel.ensure_oidc_identity_provider(
        name="staff-provider", issuer=ISSUER, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
    )

    with pytest.raises(zitadel.ZitadelError, match="still"):
        zitadel.deactivate_identity_provider(idp_id=staff_idp.id)

    assert staff_idp.id not in instance.deactivated_idps
