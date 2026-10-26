"""**The A9 matrix, re-proven against the engine put underneath it.**

Twenty-two rows, enumerated by the cycle plan (`docs/product/cycles/`)
and numbered here the way it numbers them. Each one is a property the identity
system had before and has to still have after — because ADR ident-6
replaced the machinery under every one of them: customers arrive through Zitadel
now, the per-connection allauth apps are gone, home-realm discovery answers one
thing, and erasure reaches the identity platform.

**Why one file and not a note in twenty-two others.** The matrix is the artefact:
a property that is proved somewhere is not the same as a property somebody can
*count*. When the next rung changes the engine again, this is the list it has to
walk. Several rows have older twins in `test_sso.py`, `test_identity_doors.py`,
`test_realm.py` and `test_rp_login.py` — those keep running and are named in the
row that owes them; what is written here is the row against the new engine.

Nothing here dials anything (ADR ident-5): the platform's assertions are built
by hand, the management API is `conftest.FakeZitadel`'s dictionary, and the
issuer stays on the must-not-dial address.
"""

from __future__ import annotations

import inspect
import json
import pathlib
from collections.abc import Callable
from importlib import import_module
from typing import Any

import pytest
import yaml
from allauth.core.exceptions import ImmediateHttpResponse
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import NoReverseMatch, reverse

from apps.accounts import services as accounts_services
from apps.accounts.adapter import (
    AccountAdapter,
    SocialAccountAdapter,
)
from apps.accounts.models import STAFF_REALM, SsoConnection, SsoDomain, SsoIdentity, User
from apps.accounts.policies import is_workforce_email
from apps.accounts.selectors import (
    get_connection_for_email,
    get_enforcing_connection_for,
    get_platform_login_url,
    get_platform_provider_id,
)
from apps.accounts.services import (
    SsoRefused,
    authenticate_token,
    create_sso_connection,
    create_user,
    disable_sso_connection,
    ensure_membership,
    erase_user,
    issue_token,
    provision_sso_identity,
    record_identity,
    sync_workforce_identity_config,
    update_sso_connection,
)
from apps.accounts.tests.conftest import CLIENT_SECRET, FakeZitadel, assertion, provider_landed
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Forbidden, Invalid
from apps.core.models import Membership, Organization, Tenant
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db

WORKFORCE_DOMAIN = "union.studio"
REALM_URL = "/api/v1/auth/realm/"
LIST_URL = "/api/v1/auth/sso-connections/"


@pytest.fixture
def workforce(settings: Any) -> None:
    """A deployment that has configured the workforce door — both halves of it.

    The credentials feed the Google IdP materialised inside Zitadel; the domain
    list is the wall the platform door applies. No allauth app is registered for
    Google: its people arrive through the platform provider like everybody's.
    """
    settings.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]


@pytest.fixture
def operator_actor(tenant: Tenant, root_org: Organization) -> Actor:
    """A platform operator: the deployment's own administrator, not a customer's.

    `identity_platform.configure` is `is_superuser` and not a role, because the
    role vocabulary is *within* a tenant by construction (`policies.py` says
    why). The tenant is here only because a `WorkflowRun` needs one.
    """
    return actor_for(
        user=create_user(email="operator@example.com", password=None, is_superuser=True),
        tenant=tenant,
        kind="human",
        org=root_org,
    )


def adapter(request: Any) -> SocialAccountAdapter:
    return SocialAccountAdapter(request)


def platform_assertion(*, email: str, subject: str = "zitadel|1", verified: bool = True) -> Any:
    """One assertion from Zitadel, which is now how everybody arrives."""
    return assertion(
        provider=get_platform_provider_id(), subject=subject, email=email, verified=verified
    )


def sso(*, connection: SsoConnection, subject: str, email: str, verified: bool = True) -> Any:
    """Run one assertion through the service the way `_customer_login` does."""
    return provision_sso_identity(
        tenant=connection.tenant,
        actor=system_actor(connection.tenant),
        connection=connection,
        subject=subject,
        email=email,
        email_verified=verified,
    )


# --- 1 ------------------------------------------------------------------------


def test_row_01_a_wrong_domain_refusal_writes_no_user_row(
    workforce: None, login_request: Any, sso_connection: SsoConnection
) -> None:
    """Both halves: the workforce door and a customer's connection.

    The refusal has to land **before** anything that creates a row, not after,
    because a `User` written and then refused is an account that exists with
    nobody able to say why.
    """
    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request,
            platform_assertion(email="stranger@gmail.com", subject="zitadel|stranger"),
        )
    assert not User.objects.filter(email="stranger@gmail.com").exists()

    with pytest.raises(SsoRefused):
        sso(connection=sso_connection, subject="okta|1", email="someone@not-acme.example")
    assert not User.objects.filter(email="someone@not-acme.example").exists()


# --- 2 ------------------------------------------------------------------------


def test_row_02_an_unverified_address_is_refused_at_every_door(
    workforce: None, login_request: Any, sso_connection: SsoConnection
) -> None:
    """An IdP that has not verified an address has asserted a profile field.

    Honouring it means whoever can make an IdP claim an address owns the local
    account at it. Every door, one answer — the workforce's Google now arriving
    through the platform provider like everybody else.
    """
    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request,
            platform_assertion(email=f"someone@{WORKFORCE_DOMAIN}", verified=False),
        )
    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request,
            platform_assertion(email="someone@elsewhere.example", verified=False),
        )
    with pytest.raises(SsoRefused):
        sso(connection=sso_connection, subject="okta|1", email="a@acme.com", verified=False)

    assert not User.objects.filter(email__contains="someone@").exists()
    assert not User.objects.filter(email="a@acme.com").exists()


# --- 3 ------------------------------------------------------------------------


def test_row_03_a_refusal_names_no_domain_and_no_customer(
    workforce: None, login_request: Any, sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """These pages are reachable by anybody with an account anywhere.

    A message that named the allowed domains would be a configuration dump; one
    that named the tenant would turn a login refusal into a customer directory.
    """
    with pytest.raises(ImmediateHttpResponse) as refused:
        adapter(login_request).pre_social_login(
            login_request,
            platform_assertion(email="stranger@gmail.com", subject="zitadel|stranger"),
        )
    page = refused.value.response.content.decode()
    assert refused.value.response.status_code == 403
    assert WORKFORCE_DOMAIN not in page
    assert tenant.name not in page
    assert tenant.slug not in page

    with pytest.raises(SsoRefused) as service_refused:
        sso(connection=sso_connection, subject="okta|1", email="x@not-acme.example")
    detail = service_refused.value.detail
    assert "acme.com" not in detail
    assert tenant.name not in detail
    assert sso_connection.name not in detail


# --- 4 ------------------------------------------------------------------------


def test_row_04_an_empty_workforce_domain_list_is_the_provider_off(
    settings: Any,
    tenant: Tenant,
    operator_actor: Actor,
    instance: FakeZitadel,
    login_request: Any,
) -> None:
    """Empty means OFF, not "allow any" — and ADR ident-6 carries that into Zitadel.

    A deployment that set credentials and forgot the domain list would otherwise
    let anybody with a Google account create a user here, and the failure would
    look exactly like success. The new half: the materialisation refuses too,
    rather than putting an unrestricted Google provider in Zitadel that this
    product then refuses everybody at.
    """
    settings.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = []

    assert is_workforce_email("anybody@anywhere.example") is False
    assert is_workforce_email(f"someone@{WORKFORCE_DOMAIN}") is False

    with pytest.raises(Invalid):
        sync_workforce_identity_config(tenant=tenant, actor=operator_actor)
    assert instance.idps == {}

    # And the door itself FAILS CLOSED: with no workforce domain configured, the
    # platform mints no stranger — not even one at the address the door would
    # have admitted had it been on.
    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request, platform_assertion(email=f"someone@{WORKFORCE_DOMAIN}")
        )
    assert not User.objects.filter(email=f"someone@{WORKFORCE_DOMAIN}").exists()


# --- 5 ------------------------------------------------------------------------


def test_row_05_an_existing_account_is_linked_never_duplicated(
    workforce: None, login_request: Any, platform_provider: None
) -> None:
    """Somebody who predates a door does not get a second account the first time
    they use it — the seeded owner, an invitee, a superuser."""
    existing = create_user(email=f"already@{WORKFORCE_DOMAIN}", password=None)

    platform = platform_assertion(email=f"already@{WORKFORCE_DOMAIN}", subject="zitadel|7")
    adapter(login_request).pre_social_login(login_request, platform)
    assert platform.user is not None
    assert platform.user.pk == existing.pk

    assert User.objects.filter(email=f"already@{WORKFORCE_DOMAIN}").count() == 1


# --- 6 ------------------------------------------------------------------------


def test_row_06_a_fresh_workforce_login_lands_with_nothing(
    workforce: None, login_request: Any
) -> None:
    """An IdP answers *who*, never *what they may do*.

    No membership, and — tenancy failing closed with no superuser exemption —
    nothing visible until somebody invites them.
    """
    adapter(login_request).pre_social_login(
        login_request,
        platform_assertion(email=f"new@{WORKFORCE_DOMAIN}", subject="zitadel|new"),
    )
    newcomer = create_user(email=f"new@{WORKFORCE_DOMAIN}", password=None)

    assert Membership.objects.filter(user_id=newcomer.pk).count() == 0
    assert list(SsoConnection.objects.for_tenant(None)) == []


# --- 7 ------------------------------------------------------------------------


def test_row_07_jit_lands_at_default_role_and_never_demotes(
    sso_connection: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    """Three properties in one row, because they are one mechanism.

    A role is data and the connection's data says one role — for a **new**
    membership. Somebody promoted to admin by a human must not be demoted by
    their next login, which is `ensure_membership`'s asymmetry and the reason it
    is not an upsert.
    """
    first = sso(connection=sso_connection, subject="okta|1", email="newcomer@acme.com")
    membership = Membership.objects.get(user_id=first.user.pk, tenant=tenant)
    assert membership.role == Membership.Role.MEMBER

    from apps.core.services import set_role

    set_role(tenant=tenant, actor=owner_actor, membership=membership, role=Membership.Role.ADMIN)

    second = sso(connection=sso_connection, subject="okta|1", email="newcomer@acme.com")
    assert second.pk == first.pk
    assert SsoIdentity.objects.for_tenant(tenant).count() == 1
    membership.refresh_from_db()
    assert membership.role == Membership.Role.ADMIN


# --- 8 ------------------------------------------------------------------------


def test_row_08_the_first_login_and_its_refusals_are_audited_as_the_system(
    sso_connection: SsoConnection,
) -> None:
    """Nobody clicked it, so nobody is named — and the refusal survives its rollback."""
    sso(connection=sso_connection, subject="okta|1", email="newcomer@acme.com")
    ok = AuditEntry.objects.for_tenant(sso_connection.tenant).get(
        action="accounts.provision_sso_identity", outcome="ok"
    )
    assert ok.actor_kind == "system"
    assert ok.actor_user_id is None

    with pytest.raises(SsoRefused):
        sso(connection=sso_connection, subject="okta|2", email="x@not-acme.example")
    assert (
        AuditEntry.objects.for_tenant(sso_connection.tenant)
        .filter(action="accounts.provision_sso_identity", outcome="error")
        .exists()
    )


# --- 9 ------------------------------------------------------------------------


def test_row_09_one_subject_through_two_connections_is_two_isolated_identities(
    sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """The subject lookup never crosses connections, and the rows never meet.

    Zitadel fronting both IdPs does not change this: the identity is keyed on
    (connection, subject), and a subject is only ever meaningful inside the
    connection that asserted it.
    """
    here = sso(connection=sso_connection, subject="shared-subject", email="a@acme.com")
    there = sso(connection=other_sso_connection, subject="shared-subject", email="b@globex.com")

    assert here.pk != there.pk
    assert here.user.pk != there.user.pk
    assert here.tenant_id == tenant.pk
    assert there.tenant_id == other_tenant.pk
    looked_up = SsoIdentity.objects.for_subject(connection=sso_connection, subject="shared-subject")
    assert looked_up is not None
    assert looked_up.pk == here.pk
    assert SsoIdentity.objects.for_tenant(tenant).count() == 1


# --- 10 -----------------------------------------------------------------------


def test_row_10_enforced_refuses_a_password_before_it_is_checked(
    sso_connection: SsoConnection, owner_actor: Actor, login_request: Any
) -> None:
    """**Pre-check**, and that is the whole property.

    Checking the password first and refusing afterwards would make this endpoint
    answer "that password was right" for an account a customer has deliberately
    taken out of password reach. The door it guarded is gone entirely
    (`test_password_door_retired.py` asserts the URLs do not resolve, which is
    stronger); the belt is kept for a product that reopens one, and ADR ident-6 leaves
    the flag as the row a Zitadel login policy is materialised from.
    """
    update_sso_connection(
        tenant=sso_connection.tenant,
        actor=owner_actor,
        connection=provider_landed(sso_connection),
        enforced=True,
    )
    assert get_enforcing_connection_for("anyone@acme.com") == sso_connection

    with pytest.raises(ValidationError):
        AccountAdapter(login_request).pre_authenticate(
            login_request,
            email="anyone@acme.com",
            password="not-even-looked-at",  # noqa: S106 — a throwaway password a test user is made with  # pragma: allowlist secret
        )

    with pytest.raises(NoReverseMatch):
        reverse("account_signup")

    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )
    assert get_enforcing_connection_for("anyone@acme.com") is None


# --- 11 -----------------------------------------------------------------------


def test_row_11_realm_discovery_leaks_nothing(
    api: Client, sso_connection: SsoConnection, owner_actor: Actor, tenant: Tenant
) -> None:
    """The one route a stranger may call, and what it may not say.

    Under the new engine every address answers `sso`, so the three negative cases
    are not merely similar — they are the same three keys with the same three
    values, and the assertion is equality rather than a field-by-field walk.
    """
    claimed = api.post(REALM_URL, {"email": "someone@acme.com"}, content_type="application/json")
    assert claimed.status_code == 200
    body = claimed.json()
    assert set(body) == {"method", "connection_id", "authorize_url"}
    assert body["method"] == "sso"
    rendered = json.dumps(body)
    for secret in (tenant.name, tenant.slug, sso_connection.name, sso_connection.issuer):
        assert secret not in rendered

    def answer(email: str) -> Any:
        return api.post(REALM_URL, {"email": email}, content_type="application/json").json()

    never = answer("nobody@never-heard-of.example")
    without = answer("stranger@example.com")
    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )
    disabled = answer("someone@acme.com")

    assert never == without == disabled
    assert never == {
        "method": "sso",
        "connection_id": None,
        "authorize_url": get_platform_login_url(),
    }
    # Unauthenticated, and rubbish is a 4xx rather than a traceback.
    assert api.post(REALM_URL, {}, content_type="application/json").status_code == 422


# --- 12 -----------------------------------------------------------------------


def test_row_12_the_client_secret_never_leaves_the_column_except_to_the_management_api(
    api: Client, owner: User, sso_connection: SsoConnection, owner_actor: Actor, tenant: Tenant
) -> None:
    """Four claims, and the fourth is ADR ident-6's.

    Ciphertext at rest; no door returns it; an omitted secret leaves the stored
    one; and the workflow that materialises a connection **carries no secret** —
    the argument is a kind and a key, and the value is read from the row inside
    the activity. A secret in a workflow argument is a secret in Temporal's
    history, in the web UI, for the retention period.
    """
    from django.db import connection as db

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT metadata FROM accounts_ssoconnection WHERE id = %s", [str(sso_connection.pk)]
        )
        stored = str(cursor.fetchone()[0])
    assert CLIENT_SECRET not in stored

    api.force_login(owner)
    listed = api.get(LIST_URL, headers={"x-tenant": tenant.slug})
    assert CLIENT_SECRET not in listed.content.decode()
    assert listed.json()["items"][0]["has_client_secret"] is True

    update_sso_connection(
        tenant=tenant, actor=owner_actor, connection=sso_connection, name="Renamed"
    )
    sso_connection.refresh_from_db()
    assert sso_connection.client_secret == CLIENT_SECRET

    runs = WorkflowRun.objects.for_tenant(tenant)
    assert runs.exists()
    for run in runs:
        assert CLIENT_SECRET not in run.workflow_id


# --- 13 -----------------------------------------------------------------------


def test_row_13_a_domain_belongs_to_one_connection_across_every_tenant(
    api: Client, owner: User, tenant: Tenant, other_tenant: Tenant, stranger_actor: Actor
) -> None:
    """The service refuses, the database refuses, and the 409 names no tenant."""
    create_sso_connection(
        tenant=other_tenant,
        actor=stranger_actor,
        name="Globex",
        issuer="https://idp.globex.example",
        client_id="globex",
        client_secret="globex-secret",  # noqa: S106 — a fake IdP client secret the test world configures  # pragma: allowlist secret
        email_domains=["contested.example"],
    )

    api.force_login(owner)
    response = api.post(
        LIST_URL,
        {
            "name": "Acme",
            "issuer": "https://idp.acme.example",
            "client_id": "acme",
            "client_secret": "acme-secret",  # pragma: allowlist secret
            "email_domains": ["contested.example"],
        },
        content_type="application/json",
        headers={"x-tenant": tenant.slug},
    )
    assert response.status_code == 409
    body = response.content.decode()
    assert "contested.example" in body
    assert other_tenant.name not in body
    assert other_tenant.slug not in body

    from django.db import IntegrityError, transaction

    theirs = SsoConnection.objects.for_tenant(other_tenant).get()
    with pytest.raises(IntegrityError), transaction.atomic():
        SsoDomain.objects.create(tenant=tenant, connection=theirs, domain="contested.example")


# --- 14 -----------------------------------------------------------------------


def test_row_14_saml_is_refused_with_the_reason(tenant: Tenant, owner_actor: Actor) -> None:
    """A sentence, not a connection that never authenticates.

    The refusal points at where the decision is recorded and what turning it on
    costs. ADR ident-6 did not change it: Zitadel speaks SAML, but nothing in this
    product writes a SAML IdP config yet, and saying otherwise would be the
    dishonest half of "federation is done".
    """
    with pytest.raises(Invalid) as refused:
        create_sso_connection(
            tenant=tenant,
            actor=owner_actor,
            name="Acme SAML",
            issuer="https://idp.acme.example",
            client_id="acme",
            client_secret="secret",  # noqa: S106 — a fake IdP client secret the test world configures  # pragma: allowlist secret
            email_domains=["acme.com"],
            protocol=SsoConnection.Protocol.SAML,
        )
    assert "SAML" in refused.value.detail
    assert not SsoConnection.objects.for_tenant(tenant).exists()


# --- 15 -----------------------------------------------------------------------


def test_row_15_another_tenants_connection_is_404_never_403(
    api: Client, owner: User, tenant: Tenant, other_sso_connection: SsoConnection
) -> None:
    """A 403 would confirm the row exists. Not-there and not-yours are one answer."""
    api.force_login(owner)
    response = api.patch(
        f"{LIST_URL}{other_sso_connection.pk}/",
        {"name": "mine now"},
        content_type="application/json",
        headers={"x-tenant": tenant.slug},
    )
    assert response.status_code == 404


# --- 16 -----------------------------------------------------------------------


def test_row_16_the_header_and_the_hat_are_the_same_answer_at_every_door(
    tenant: Tenant, other_tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """A pinned token acts as its pin; an unpinned one resolves memberships;
    and the hat is one function, not four.

    The OAuth door's twin lives in `test_mcp_oauth.py` and runs
    unchanged — ApiToken survived subsumption (ADR ident-3), so this row's
    machinery is the one thing the engine change did not touch, and that is what is asserted.

    **The mismatched-tenant half moved doors** (ADR core-21): this service
    answers WHO and returns the pin, and the request is refused at the door for
    WHERE it asked to act. The refusal is driven over the wire, at both doors,
    in `apps/core/tests/test_addressing_headers.py`.
    """
    pinned, plaintext = issue_token(
        user=owner, tenant=tenant, name="pinned", actor=actor_for(user=owner, tenant=tenant)
    )
    mismatched = authenticate_token(plaintext=plaintext, requested_slug=other_tenant.slug)
    assert mismatched is not None and mismatched.tenant == tenant
    resolved = authenticate_token(plaintext=plaintext, requested_slug=tenant.slug)
    assert resolved is not None and resolved.tenant == tenant

    _, floating = issue_token(
        user=owner, tenant=None, name="floating", actor=actor_for(user=owner, tenant=None)
    )
    unpinned = authenticate_token(plaintext=floating, requested_slug=None)
    assert unpinned is not None and unpinned.tenant == tenant

    # One `resolve_org`, imported by every door rather than reimplemented in each.
    from apps.core import middleware

    for door in ("apps.accounts.auth", "apps.core.asgi_middleware", "config.mcp"):
        module = import_module(door)
        assert module.resolve_org is middleware.resolve_org, door


# --- 17 -----------------------------------------------------------------------


def test_row_17_a_member_may_not_configure_and_the_door_says_the_same(
    api: Client,
    member: User,
    tenant: Tenant,
    member_actor: Actor,
    admin_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """The strictest policy in the repository, and the door must not soften it.

    A member who could edit a connection could point the tenant's login at an
    identity provider they control and walk back in as an owner.
    """
    refusals: list[Callable[[], object]] = [
        lambda: create_sso_connection(
            tenant=tenant,
            actor=member_actor,
            name="Mine",
            issuer="https://idp.example",
            client_id="c",
            client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
            email_domains=["mine.example"],
        ),
        lambda: update_sso_connection(
            tenant=tenant, actor=member_actor, connection=sso_connection, name="Mine"
        ),
        lambda: disable_sso_connection(
            tenant=tenant, actor=member_actor, connection=sso_connection
        ),
    ]
    for call in refusals:
        with pytest.raises(Forbidden):
            call()

    api.force_login(member)
    refused = api.patch(
        f"{LIST_URL}{sso_connection.pk}/",
        {"name": "Mine"},
        content_type="application/json",
        headers={"x-tenant": tenant.slug},
    )
    assert refused.status_code == 403

    # And the other half: `Forbidden` for everybody would be a passing test and a
    # broken product.
    assert (
        update_sso_connection(
            tenant=tenant, actor=admin_actor, connection=sso_connection, name="Renamed"
        ).name
        == "Renamed"
    )


# --- 18 -----------------------------------------------------------------------


def test_row_18_a_disabled_connection_cannot_sign_anybody_in_and_keeps_its_claims(
    login_request: Any, sso_connection: SsoConnection, owner_actor: Actor
) -> None:
    """Disabling stops the login and frees nothing.

    Deleting the claims would let another tenant take the domain while this one
    is mid-migration, and would take the record of who arrived through it too.

    With the connection off, nobody claims the address, so a person who is new
    here meets the workforce wall and is refused outright — no account, no
    identity, no membership — unless the deployment's own workforce or an
    invitation vouches for them.
    """
    disable_sso_connection(
        tenant=sso_connection.tenant, actor=owner_actor, connection=sso_connection
    )

    assert get_connection_for_email("someone@acme.com") is None
    with pytest.raises(ImmediateHttpResponse):
        adapter(login_request).pre_social_login(
            login_request, platform_assertion(email="someone@acme.com")
        )
    assert not User.objects.filter(email="someone@acme.com").exists()
    assert SsoIdentity.objects.for_tenant(sso_connection.tenant).count() == 0
    assert not Membership.objects.filter(
        tenant=sso_connection.tenant, user__email="someone@acme.com"
    ).exists()

    sso_connection.refresh_from_db()
    assert sso_connection.email_domains == ["acme.com"]
    # The row is still there and still this tenant's. `for_domain` answers `None`
    # because it only routes to a live connection — which is the same fact from
    # the other side: nobody else may claim acme.com while this row holds it.
    assert (
        SsoDomain.objects.for_tenant(sso_connection.tenant)
        .filter(domain="acme.com", connection=sso_connection)
        .exists()
    )
    assert SsoDomain.objects.for_domain("acme.com") is None
    assert SsoDomain.objects.claim("acme.com") is not None


# --- 19 -----------------------------------------------------------------------


def test_row_19_the_signup_lock_agrees_with_the_gate(workforce: None, login_request: Any) -> None:
    """Two locks on one door, and they must not disagree.

    `pre_social_login` has already refused everything it is going to refuse — but
    "already refused" is a claim about control flow, and a control-flow claim is
    the kind that stops being true when somebody adds a branch.
    """
    gate = adapter(login_request)

    outside = platform_assertion(email="stranger@gmail.com", subject="zitadel|1")
    assert gate.is_open_for_signup(login_request, outside) is False
    with pytest.raises(ImmediateHttpResponse):
        gate.pre_social_login(login_request, outside)

    inside = platform_assertion(email=f"new@{WORKFORCE_DOMAIN}", subject="zitadel|2")
    assert gate.is_open_for_signup(login_request, inside) is True
    gate.pre_social_login(login_request, inside)

    unverified = platform_assertion(email="someone@elsewhere.example", verified=False)
    assert gate.is_open_for_signup(login_request, unverified) is False
    with pytest.raises(ImmediateHttpResponse):
        gate.pre_social_login(login_request, unverified)


# --- 20 -----------------------------------------------------------------------


def test_row_20_erasure_revokes_the_identity_platform_account(
    tenant: Tenant, owner_actor: Actor, member: User
) -> None:
    """**W2R5-20, the property the new engine owes.**

    The tokens were ours and the session was ours; the credential is Zitadel's,
    and so is the next login. An erasure that stopped at our own rows would be an
    erasure the person signs straight back through — and with `SOCIALACCOUNT_ONLY`
    that is now the only way anybody signs in at all.

    **The one plan-named legal edit to a frozen net** (cycle P2, rung B2, ADR
    ident-7). The property above is unchanged and so are the anonymisation
    asserts; what moved is *whose ledger the run is recorded in*. This row used
    to pin `for_tenant(tenant)` at
    `f"{tenant.slug}:accounts:identity_revocation:{member.pk}"`, and that pin was
    the only thing holding the borrow in place: `_a_tenant_of` picked any tenant
    the person belonged to and recorded the revocation there, so a workspace's
    audit ledger claimed a revocation of a credential it never owned. Its own
    docstring declared that blind spot and named this successor. The credential
    is Zitadel's — that argument already won — so the run is the platform's,
    for everybody, and no tenant's ledger carries it.
    """
    record_identity(
        realm=STAFF_REALM,
        user=member,
        subject="zitadel-user-9001",
        tenant=None,
        actor=system_actor(tenant=None),
    )

    erase_user(user=member, actor=owner_actor, tenant=tenant)

    workflow_id = f"platform:accounts:identity_revocation:{member.pk}"
    run = WorkflowRun.objects.for_platform().get(workflow_id=workflow_id)
    assert run.tenant_id is None
    assert run.status == WorkflowRun.Status.RUNNING
    # The tenant the erasure was performed in does not carry it, and that is the
    # half the old pin had backwards.
    assert not WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=workflow_id)
    member.refresh_from_db()
    assert member.email.startswith("erased+")
    assert member.is_active is False
    # The deterministic id is what makes a retried erasure one revocation.
    assert (
        WorkflowRun.objects.for_platform()
        .filter(workflow_id__contains="identity_revocation")
        .count()
        == 1
    )


# --- 21 -----------------------------------------------------------------------


CHANGED_ENGINE = {
    "create_sso_connection",
    "update_sso_connection",
    "disable_sso_connection",
    "provision_sso_identity",
    "erase_user",
}
UNCHANGED = {"issue_token", "authenticate_token", "ensure_membership", "create_user"}


def test_row_21_the_changed_set_is_exactly_what_the_plan_named(
    tenant: Tenant, owner: User, owner_actor: Actor, member: User
) -> None:
    """**W2R5-21**: the enumeration honoured, in both directions.

    The five that changed engine are the five that reach the identity platform
    now — three configuration writes, the claims source, and the erasure. The
    four beside them are untouched, and "untouched" is asserted as behaviour
    rather than as a diff: none of them starts a run, and each still answers what
    it always answered. Their own tests run unmodified; this is the row that says
    the *set* is closed.
    """
    for name in CHANGED_ENGINE | UNCHANGED:
        assert callable(getattr(accounts_services, name)), name

    # Every place in this module that can start a materialisation run, found by
    # reading the source rather than by remembering — a fourth caller added
    # quietly is exactly the thing the enumeration exists to catch.
    starters = {
        name
        for name, function in vars(accounts_services).items()
        if inspect.isfunction(function)
        and name != "_start_identity_run"
        and "_start_identity_run(" in (inspect.getsource(function) or "")
    }
    assert starters == {
        "sync_identity_config",
        "sync_workforce_identity_config",
        # `erase_user`'s half, kept private so that the revocation cannot be
        # asked for except by erasing somebody.
        "_revoke_identity_platform_access",
        # The branding starter (landed 2026-09-04): the sixth, and the first one
        # the deployment's own look rides on. Added here rather than left for
        # this census to catch by silently reddening — a fourth (now fifth)
        # caller added quietly is exactly what W2R5-21 exists to refuse.
        "set_identity_branding",
        # A tenant's realm (identity option B): asked for when the tenant is
        # created, through `core.bridge`, and by the reconciler for a tenant
        # with none — one private starter both roads call.
        "_ask_for_a_realm",
    }

    before = WorkflowRun.objects.count()
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="unchanged", actor=actor_for(user=owner, tenant=tenant)
    )
    assert authenticate_token(plaintext=plaintext, requested_slug=tenant.slug) is not None
    assert (
        ensure_membership(user=member, tenant=tenant, role=Membership.Role.MEMBER).role
        == Membership.Role.MEMBER
    )
    assert create_user(email="untouched@example.com", password=None).is_active is True
    assert WorkflowRun.objects.count() == before


# --- 22 -----------------------------------------------------------------------


ACCOUNTS_SCOPE_ENTRIES = {
    ("3", "allow_unauthenticated", "api:realm-discover"),
    ("8", "exemptions", "apps/accounts/selectors.py::get_realm_for_email"),
    ("8", "exemptions", "apps/accounts/selectors.py::get_enforcing_connection_for"),
    ("8", "exemptions", "apps/accounts/services.py::_apply_domains"),
    ("8", "exemptions", "apps/accounts/services.py::provision_sso_identity"),
    ("13", "exemptions", "apps/accounts/services.py::touch_token"),
    ("27", "allow_import", "apps/accounts/activities.py"),
    ("27", "allow_import", "apps/accounts/management/commands/zitadel_seed.py"),
    ("27", "allow_import", "apps/accounts/management/commands/zitadel_audit.py"),
    # Added 2026-09-07 with the first-identity door (ADR ident-9), deliberately
    # and as the conversation this census exists to force. The command mints the
    # deployment's first Zitadel human before any tenant exists, so there is no
    # service to route it through and no persona a runtime door could
    # authenticate — the fourth member of the `zitadel_*` shell-door family, and
    # the reason is beside the entry in `quality/rules.yaml`.
    ("27", "allow_import", "apps/accounts/management/commands/zitadel_first_admin.py"),
    # Added 2026-09-30 with the identity realm port (identity option B), the
    # conversation held and ruled before the line landed: the port's Zitadel
    # adapter composes the client's idempotent writers for a tenant's realm,
    # and its callers are the activities and commands already on the list.
    ("27", "allow_import", "apps/accounts/realms/zitadel.py"),
    # The measurement kit, out of the production client (rule 27 allow-list).
    ("27", "allow_import", "apps/accounts/zitadel_measure_kit.py"),
    # R2-E1's allow-lists, 2026-09-16: the modules that may route the home realm
    # and write the identity join — the owner-ratified R2 fix set.
    ("56", "allow_router", "apps/accounts/selectors.py"),
    ("56", "allow_router", "apps/accounts/models.py"),
    ("56", "allow_claim", "apps/accounts/services.py"),
    ("56", "allow_claim", "apps/accounts/management/commands/verify_sso_domain.py"),
    ("57", "allow_column", "apps/accounts/services.py"),
    ("57", "allow_connect", "apps/accounts/adapter.py"),
    # Added with the sign-in door (design C-13), deliberately and as the
    # conversation this census exists to force. `/accounts/login/` is the one
    # URL a person reaches BEFORE they hold a credential, so there is none it
    # could demand; it is also not a new opening, because allauth's own login
    # view answered that path unauthenticated at every deployment before this
    # mount and under the default door still does — the shadow changed which
    # callable answers, not who may knock. The reason is beside the entry in
    # `quality/rules.yaml`, and rule 3's set equality is what would notice the
    # view being deleted and this record outliving it.
    ("3", "allow_unauthenticated_views", "sign-in"),
}


def test_row_22_this_rung_bought_no_new_exemption() -> None:
    """**W2R5-22**, the half a gate run cannot state.

    The gate proves the rules pass. It cannot prove that they pass *because the
    code is right* rather than because somebody widened a scope to let it
    through — that is a diff question, and a diff nobody diffs is a ratchet
    nobody holds. So the accounts-shaped entries in `quality/rules.yaml` are
    written out here as a set: adding one is a failing test with the entry named
    in the output, which is the conversation it should have been.

    LEX-1 owns the whole-cycle version of this claim; this is the app's share of
    it, and it is the one a builder can break by accident.
    """
    rules = yaml.safe_load(pathlib.Path("quality/rules.yaml").read_text())["rules"]
    found: set[tuple[str, str, str]] = set()
    for rule in rules:
        for key, value in (rule.get("scope") or {}).items():
            if not isinstance(value, list):
                continue
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                text = json.dumps(entry)
                if "apps/accounts" not in text and "accounts_api" not in text:
                    continue
                if "path" in entry:
                    name = entry["path"]
                    if entry.get("function"):
                        name = f"{name}::{entry['function']}"
                else:
                    name = str(entry.get("url_name", text))
                found.add((str(rule["id"]), key, name))

    assert found == ACCOUNTS_SCOPE_ENTRIES
