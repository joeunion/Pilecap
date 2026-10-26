"""A tenant's identity home: a realm of its own at the identity platform, made when the tenant is.

Identity option B, from the tenant's side. `core.create_tenant` asks through
`core.bridge`; this app writes the `pending` home in the creating transaction and
starts `EnsureTenantIdentityHomeWorkflow` on commit; the run makes the realm
through the realm port, grants it the platform, sets its login policy and writes
the home back `own_org`. The audit reads every tenant's realm back and prints
`n of n tenants homed`; the reconciler asks again for a tenant whose realm is
missing, pending or gone; the seed records the deployment's own staff realm.

The fake answers the way the pinned build answered on the live drive — a removed
organisation included (`FakeZitadel`'s DELETE, transcribed).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management import call_command
from temporalio.client import Client, WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from apps.accounts import realms, zitadel
from apps.accounts.events import IDENTITY_HOME_CREATED
from apps.accounts.management.commands import zitadel_seed
from apps.accounts.models import STAFF_REALM, IdentityHome
from apps.accounts.realms import zitadel as zitadel_realm
from apps.accounts.selectors import get_realm_of_assertion, get_tenant_realm
from apps.accounts.services import IDENTITY_HOME_WORKFLOW, sync_identity_home
from apps.accounts.tests import test_signin_door as door_world
from apps.accounts.tests.conftest import (
    SIGNIN_LOGIN_NAME,
    SIGNIN_PASSWORD,
    SIGNIN_USER_ID,
    FakeZitadel,
    home_tenant,
    join,
)
from apps.accounts.types import IdentityHomeApplied
from apps.core import bridge
from apps.core.actor import system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.core.services import create_tenant
from apps.core.surfaces import surface_base_urls
from apps.core.tests import test_surfaces as surface_world
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

#: How long a held activity waits on the test, and the test on it.
HOLD_SECONDS = 20


def _events(tenant: Tenant) -> Any:
    """The home events emitted for `tenant`, read by name: `accounts` may not import `events`."""
    return django_apps.get_model("events", "Event").objects.filter(
        tenant=tenant, name=IDENTITY_HOME_CREATED
    )


def home_run_id(tenant: Tenant) -> str:
    """The run's id — DERIVED from the house shape for a platform run (house rule 18)."""
    return f"platform:accounts:identity_home:{tenant.slug}"


def _realms_named(fake: FakeZitadel, tenant: Tenant) -> list[dict[str, Any]]:
    return [row for row in fake.orgs if row["name"] == zitadel_realm.realm_name(tenant)]


# --- asked for at creation ------------------------------------------------------


def test_a_new_tenant_asks_for_its_home_in_the_creating_transaction(
    recorded_workflow_starts: None,
) -> None:
    """The pending home and the platform run are written with the tenant, or not at all."""
    tenant = create_tenant(name="Initech", slug="initech", actor=system_actor())

    home = IdentityHome.objects.for_tenant(tenant).get()
    assert home.state == IdentityHome.State.PENDING
    assert home.realm_id == ""
    run = WorkflowRun.objects.get(workflow_id=home_run_id(tenant))
    assert run.type == IDENTITY_HOME_WORKFLOW
    assert run.tenant_id is None, "a realm is the deployment's configuration, a platform run"
    # Fail closed: a pending home names no realm for a sign-in to confine to.
    assert get_tenant_realm(tenant) is None


def test_the_activity_makes_grants_and_polices_the_realm_and_writes_it_back(
    instance: FakeZitadel, tenant: Tenant
) -> None:
    realm_id = home_tenant(instance, tenant)

    home = IdentityHome.objects.for_tenant(tenant).get()
    assert (home.state, home.realm_id) == (IdentityHome.State.OWN_ORG, realm_id)
    assert [row["id"] for row in _realms_named(instance, tenant)] == [realm_id]
    assert any(row["grantedOrgId"] == realm_id for row in instance.grants.values())
    # Its own policy, the password on: nobody's sign-in changed but this realm's.
    assert instance.realm_login_policies[realm_id]["allowUsernamePassword"] is True
    assert instance.org_login_policy.get("isDefault") is True, "the staff org is untouched"
    assert _events(tenant).count() == 1


def test_a_second_run_is_the_first_realm_and_says_nothing(
    instance: FakeZitadel, tenant: Tenant
) -> None:
    """Temporal delivers at least once; the port searches before it creates."""
    first = home_tenant(instance, tenant)
    second = home_tenant(instance, tenant)

    assert first == second
    assert len(_realms_named(instance, tenant)) == 1
    assert len([row for row in instance.grants.values() if row["grantedOrgId"] == first]) == 1
    assert _events(tenant).count() == 1


def test_a_production_world_with_no_bus_refuses_the_home_event(
    tenant: Tenant, settings: Any
) -> None:
    """Nobody listening for the event is a refusal in production, as core's own emits are."""
    saved = bridge.registered()
    bridge.clear()
    settings.BRIDGE_STRICT = True
    try:
        with pytest.raises(bridge.BridgeNotRegistered):
            sync_identity_home(tenant=tenant, actor=system_actor(), realm_id="realm-without-a-bus")
    finally:
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)


# --- through the machinery a deployment runs -----------------------------------


@pytest.fixture
def live_fake(monkeypatch: pytest.MonkeyPatch, settings: Any) -> FakeZitadel:
    """The fake on the worker's thread, with the deployment's project on it."""
    fake = FakeZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    project = fake.id()
    fake.projects[project] = {"id": project, "name": str(settings.ZITADEL_PROJECT_NAME)}

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test", transport=httpx.MockTransport(fake.handle)
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    return fake


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


@pytest.mark.asyncio
async def test_creating_a_tenant_homes_it_through_the_worker(
    live_fake: FakeZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`create_tenant` → the bridge → the run → `own_org`, and the run row closes."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            tenant = await run_db(create_tenant, name="Hooli", slug="hooli", actor=system_actor())
            handle = client.get_workflow_handle(
                home_run_id(tenant), result_type=IdentityHomeApplied
            )
            applied: IdentityHomeApplied = await handle.result()

    home = await run_db(lambda: IdentityHome.objects.for_tenant(tenant).get())
    run = await run_db(lambda: WorkflowRun.objects.get(workflow_id=home_run_id(tenant)))
    assert (home.state, home.realm_id) == (IdentityHome.State.OWN_ORG, applied.realm_id)
    assert run.status == WorkflowRun.Status.COMPLETED
    assert len(_realms_named(live_fake, tenant)) == 1


@pytest.mark.asyncio
async def test_a_run_that_dies_part_way_resumes_and_makes_one_realm(
    live_fake: FakeZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The realm made, the grant refused once: the retry finds the realm and ends `own_org` once.

    The platform failing between two steps is the ordinary case the retry policy
    exists for; the port's search-before-create is what keeps it to one realm.
    """
    real_grant = zitadel_realm.ZitadelRealm.grant_platform
    failures: list[str] = []

    def grant_once_refused(self: Any, *, realm: Any) -> None:
        if not failures:
            failures.append(realm.id)
            raise zitadel.ZitadelError("Zitadel POST /grants failed: connection reset")
        real_grant(self, realm=realm)

    monkeypatch.setattr(zitadel_realm.ZitadelRealm, "grant_platform", grant_once_refused)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            tenant = await run_db(
                create_tenant, name="Pied Piper", slug="piper", actor=system_actor()
            )
            await client.get_workflow_handle(
                home_run_id(tenant), result_type=IdentityHomeApplied
            ).result()

    home = await run_db(lambda: IdentityHome.objects.for_tenant(tenant).get())
    events = await run_db(lambda: _events(tenant).count())
    assert failures, "the first attempt did not fail — the case measured nothing"
    assert home.state == IdentityHome.State.OWN_ORG
    assert [row["id"] for row in _realms_named(live_fake, tenant)] == [home.realm_id]
    assert events == 1


@pytest.mark.asyncio
async def test_a_cancel_closes_the_run_as_cancelled(
    live_fake: FakeZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel is the third exit (the imports workflows' shape): the row says `cancelled`."""
    entered = threading.Event()
    released = threading.Event()
    real_ensure = zitadel_realm.ZitadelRealm.ensure_realm

    def held(self: Any, *, tenant: Any) -> Any:
        entered.set()
        released.wait(HOLD_SECONDS)
        return real_ensure(self, tenant=tenant)

    monkeypatch.setattr(zitadel_realm.ZitadelRealm, "ensure_realm", held)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            tenant = await run_db(create_tenant, name="Aviato", slug="aviato", actor=system_actor())
            handle = client.get_workflow_handle(
                home_run_id(tenant), result_type=IdentityHomeApplied
            )
            assert await asyncio.to_thread(entered.wait, HOLD_SECONDS), "the run never started"
            await handle.cancel()
            released.set()
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            described = await handle.describe()

    run = await run_db(lambda: WorkflowRun.objects.get(workflow_id=home_run_id(tenant)))
    assert described.status is not None and described.status.name == "CANCELED"
    assert (str(run.status), run.error) == ("cancelled", "")


# --- read back: the audit, the reconciler ---------------------------------------


def _audit(tenant_slug: str = "") -> tuple[int, str]:
    out = StringIO()
    try:
        call_command("zitadel_audit", tenant=tenant_slug, stdout=out)
    except SystemExit as stopped:
        return int(stopped.code or 0), out.getvalue()
    return 0, out.getvalue()


def _reconcile(**options: Any) -> str:
    """Run the reconciler narrowed to realms; a delta left open elsewhere is its exit 1."""
    out = StringIO()
    try:
        call_command("zitadel_reconcile", kind="identity_home", stdout=out, **options)
    except SystemExit as stopped:
        assert stopped.code == 1, out.getvalue()
    return out.getvalue()


def test_the_audit_counts_the_tenants_homed_from_the_population(
    instance: FakeZitadel, tenant: Tenant, other_tenant: Tenant
) -> None:
    """`n of n tenants homed` — both numbers derived, never typed."""
    for one in Tenant.objects.all():
        home_tenant(instance, one)
    homed = Tenant.objects.count()

    _status, out = _audit()

    assert f"{homed} of {homed} tenants homed" in out
    for one in Tenant.objects.all():
        realm = get_tenant_realm(one)
        assert realm is not None
        assert f"agrees      realm {one.slug} — org {realm.id}, granted" in out


def test_a_pending_tenant_is_drift_the_audit_names(instance: FakeZitadel, tenant: Tenant) -> None:
    IdentityHome.objects.filter(tenant=tenant).update(state=IdentityHome.State.PENDING, realm_id="")
    status, out = _audit(tenant.slug)

    assert status == 1
    assert f"DRIFT       realm {tenant.slug} — is pending" in out
    assert f"0 of {Tenant.objects.filter(slug=tenant.slug).count()} tenants homed" in out


def test_a_removed_realm_is_not_a_home(instance: FakeZitadel, tenant: Tenant) -> None:
    """Measured: a removed org answers 200 with no `state` — and is not a home.

    The pinned build answers `GET /admin/v1/orgs/{id}` with the org's body and
    no `state` key after `DELETE` answered 200 (held at +0/+3/+10 s); the fake
    answers the same. `facts` reads it as no realm, the audit as drift, and the
    reconciler asks for the tenant's home again.
    """
    realm_id = home_tenant(instance, tenant)
    assert zitadel.remove_organization(org_id=realm_id) is True

    realm = get_tenant_realm(tenant)
    assert realm is not None
    assert zitadel.get_organization(org_id=realm_id) is None
    assert realms.current().facts(realm=realm).exists is False
    status, out = _audit(tenant.slug)
    assert status == 1
    assert f"DRIFT       realm {tenant.slug} — org {realm_id} is gone at the platform" in out

    before = WorkflowRun.objects.filter(type=IDENTITY_HOME_WORKFLOW).count()
    assert f"realm for {tenant.slug} asked for" in _reconcile()
    assert WorkflowRun.objects.filter(type=IDENTITY_HOME_WORKFLOW).count() == before + 1


def test_the_reconciler_homes_a_tenant_that_predates_realms(
    instance: FakeZitadel, tenant: Tenant
) -> None:
    """A tree that predates the release homes its tenants at its next deploy (S.5)."""
    IdentityHome.objects.filter(tenant=tenant).delete()
    WorkflowRun.objects.filter(workflow_id=home_run_id(tenant)).delete()

    assert f"realm for {tenant.slug} asked for" in _reconcile()
    assert IdentityHome.objects.for_tenant(tenant).get().state == IdentityHome.State.PENDING
    assert WorkflowRun.objects.filter(workflow_id__startswith=home_run_id(tenant)).exists()


# --- the seed: the staff realm, the project check, the owner role, every surface -


customer_role = surface_world.customer_role
two_faces = surface_world.two_faces


def test_the_seed_records_the_staff_realm_and_the_wall_around_the_project(
    instance: FakeZitadel, settings: Any, two_faces: Any
) -> None:
    instance.instance_members[str(instance.machine["id"])] = [zitadel.LOGIN_CLIENT_ROLE]

    call_command("zitadel_seed", skip_user=True, stdout=StringIO())

    staff = IdentityHome.objects.staff()
    assert staff is not None and staff.realm_id == instance.home_org
    project = next(
        row
        for row in instance.projects.values()
        if row["name"] == str(settings.ZITADEL_PROJECT_NAME)
    )
    assert project.get("hasProjectCheck") is True
    assert zitadel_seed.INSTANCE_OWNER_ROLE in instance.instance_members[instance.machine["id"]]
    browser = next(
        row for row in instance.apps.values() if row["name"] == settings.ZITADEL_BROWSER_APP_NAME
    )
    assert browser["oidcConfig"]["redirectUris"] == [
        f"{base}{zitadel_seed.BROWSER_CALLBACK_PATH}" for base in surface_base_urls()
    ]
    assert any(
        urlsplit(uri).hostname == surface_world.CUSTOMER_HOST
        for uri in browser["oidcConfig"]["redirectUris"]
    )


def test_the_audit_declares_the_seeds_own_redirect_uris_and_the_reconciler_asks_nothing(
    instance: FakeZitadel, settings: Any, two_faces: Any
) -> None:
    """One derivation of the surfaces' base URLs, read by the seed and the audit alike.

    The audit used to declare the browser client's URIs from `PUBLIC_BASE_URL`
    alone, so a second surface's callback — registered by the seed — read as
    drift, and the reconciler re-ran the seed on every pass to write it back.
    """
    instance.instance_members[str(instance.machine["id"])] = [zitadel.LOGIN_CLIENT_ROLE]
    call_command("zitadel_seed", skip_user=True, stdout=StringIO())

    _status, out = _audit()
    assert "agrees      applications" in out
    assert "DRIFT       applications" not in out

    reconciled = StringIO()
    call_command("zitadel_reconcile", kind="applications", stdout=reconciled)
    assert "0 asked" in reconciled.getvalue()


def test_the_deployment_project_name_is_what_a_realm_is_named_after(tenant: Tenant) -> None:
    assert zitadel_realm.realm_name(tenant) == f"{settings.ZITADEL_PROJECT_NAME} {tenant.slug}"


# --- the customer never posts the accept: the join is written at sign-in -------


@pytest.mark.parametrize("confined", [True, False])
def test_an_invited_customer_joins_at_their_first_sign_in_in_their_tenants_realm(
    instance: FakeZitadel,
    homed: str,
    tenant: Tenant,
    owner: Any,
    platform_provider: None,
    login_request: Any,
    confined: bool,
) -> None:
    """The ruling: acceptance rides the sign-in adapter, and no customer posts an accept.

    `POST /invitations/accept/` belongs to a family the customer surface does not
    expose (404 there), and it needs no exposure: a person's first platform
    sign-in accepts every standing invitation for their verified address, and
    the join lands in the realm that asserted them — named by the platform when
    the sign-in was confined to the realm (the measured claim), and read off the
    one standing invitation when it was not.
    """
    from apps.accounts.adapter import REALM_CLAIM, SocialAccountAdapter
    from apps.accounts.models import SsoIdentity, User
    from apps.accounts.selectors import get_platform_provider_id
    from apps.accounts.tests.conftest import assertion
    from apps.core.models import Membership
    from apps.core.services import invite_member

    invite_member(
        tenant=tenant,
        email="grace@customer.example",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    login = assertion(
        provider=get_platform_provider_id(),
        subject="realm-subject-1",
        email="grace@customer.example",
        extra={REALM_CLAIM: homed} if confined else None,
    )
    adapter = SocialAccountAdapter(login_request)
    adapter.pre_social_login(login_request, login)
    # allauth's auto-signup hands its adapter an unsaved person (the workforce
    # wall's tests drive the same step this way).
    login.user = User(email="grace@customer.example")
    person: User = adapter.save_user(login_request, login)

    joined = SsoIdentity.objects.get(user=person, connection__isnull=True)
    assert (joined.realm, joined.tenant_id, joined.subject) == (homed, tenant.pk, "realm-subject-1")
    assert Membership.objects.filter(user=person, tenant=tenant).exists()


door = door_world.door
ours = door_world.ours


def test_a_sign_in_at_the_customer_host_audits_its_join_and_its_acceptance_as_that_door(
    homed: str,
    tenant: Tenant,
    owner: Any,
    two_faces: Any,
    door: Any,
    ours: None,
    settings: Any,
) -> None:
    """The rows a real sign-in writes say where it came in: the request's door and its surface.

    The whole road — the form at the customer host, the platform's check,
    allauth's completion, `_platform_login` — and the join it records and the
    invitation it accepts are audited as the web door at the customer surface,
    never as a shell's blank door on the staff surface.
    """
    from django.test import Client as Browser

    from apps.core.audit import AuditEntry
    from apps.core.services import invite_member

    settings.GOOGLE_WORKSPACE_DOMAINS = []
    # The invited person lives in the tenant's realm at the platform, so that is
    # the organisation the session verifies them in.
    door.org_id = homed
    invite_member(
        tenant=tenant,
        email=SIGNIN_LOGIN_NAME,
        invited_by=owner,
        role="customer",
        actor=system_actor(tenant=tenant),
    )
    browser = Browser(HTTP_HOST=surface_world.CUSTOMER_HOST)

    response = browser.post(
        door_world.LOGIN_URL,
        {
            "action": "password",
            "email": SIGNIN_LOGIN_NAME,
            "password": SIGNIN_PASSWORD,
        },
    )

    assert response.status_code == 302, response.content
    from apps.accounts.models import SsoIdentity

    joined = SsoIdentity.objects.get(subject=SIGNIN_USER_ID, connection__isnull=True)
    assert (joined.realm, joined.tenant_id) == (homed, tenant.pk)
    rows = AuditEntry.objects.filter(
        action__in=("accounts.record_identity", "core.accept_invitation")
    ).values_list("action", "door", "surface")
    assert sorted(rows) == [
        ("accounts.record_identity", "rest", "customer"),
        ("core.accept_invitation", "rest", "customer"),
    ]


def test_a_sign_in_lands_in_the_realm_the_platform_verified_whatever_a_stale_row_says(
    homed: str,
    tenant: Tenant,
    owner: Any,
    two_faces: Any,
    door: Any,
    ours: None,
    settings: Any,
) -> None:
    """A join row a rollback re-spelled `staff` does not decide where the next sign-in lands.

    The platform verified the person in the tenant's realm, and the door hands
    that realm to the adapter as the realm claim: the claim is the first arm,
    so the sign-in records the person in the tenant's realm again rather than
    reading the stale row back and changing nothing.
    """
    from allauth.socialaccount.models import SocialAccount
    from django.test import Client as Browser

    from apps.accounts.models import SsoIdentity
    from apps.accounts.selectors import get_platform_provider_id
    from apps.accounts.services import create_user
    from apps.core.services import add_membership, root_organization

    settings.GOOGLE_WORKSPACE_DOMAINS = []
    door.org_id = homed
    person = create_user(email=SIGNIN_LOGIN_NAME)
    add_membership(
        user=person,
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        role="customer",
        is_default=True,
        actor=system_actor(tenant=tenant),
    )
    join(person, SIGNIN_USER_ID, realm=STAFF_REALM)
    # The person signed in before the rollback, so allauth holds their subject too.
    SocialAccount.objects.create(
        user=person, provider=get_platform_provider_id(), uid=SIGNIN_USER_ID
    )

    landed = Browser(HTTP_HOST=surface_world.CUSTOMER_HOST).post(
        door_world.LOGIN_URL,
        {"action": "password", "email": SIGNIN_LOGIN_NAME, "password": SIGNIN_PASSWORD},
    )

    assert landed.status_code == 302, landed.content
    assert SsoIdentity.objects.filter(
        user=person, subject=SIGNIN_USER_ID, realm=homed, connection__isnull=True
    ).exists()


# --- which realm an assertion came from: one case per arm ------------------------


def test_the_realm_the_platform_names_is_the_realm(
    instance: FakeZitadel, homed: str, tenant: Tenant
) -> None:
    """A sign-in confined to a realm carries the realm's claim, and that claim decides."""
    asserted = get_realm_of_assertion(
        realm_id=homed, subject="subject-nobody-holds", email="nobody@unclaimed.example"
    )
    assert (asserted.realm, asserted.tenant) == (homed, tenant)


def test_an_unconfined_sign_in_reads_the_realm_off_the_subjects_join_row(
    instance: FakeZitadel, homed: str, tenant: Tenant, owner: Any
) -> None:
    """No claim: a subject is one account at the platform, so its join row says where it lives."""
    join(owner, "subject-in-the-tenant-realm", realm=homed)

    asserted = get_realm_of_assertion(
        realm_id="", subject="subject-in-the-tenant-realm", email="nobody@unclaimed.example"
    )
    assert (asserted.realm, asserted.tenant) == (homed, tenant)


def test_an_unconfined_sign_in_at_a_claimed_domain_lands_in_the_claiming_tenants_realm(
    instance: FakeZitadel, homed: str, tenant: Tenant, sso_connection: Any
) -> None:
    """No claim, no join row: a verified domain claim routes the address to its tenant's realm."""
    asserted = get_realm_of_assertion(
        realm_id="", subject="subject-nobody-holds", email="ada@acme.com"
    )
    assert (asserted.realm, asserted.tenant) == (homed, tenant)
