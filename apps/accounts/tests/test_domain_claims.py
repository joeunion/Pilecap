"""A domain claim reserves a name. Verifying it is what makes it route.

**The hole this module is the fence around** (the sign-in surface review, finding F1).
`POST /api/v1/auth/sso-connections/ {"email_domains": ["example.com"]}` answers
`201` for any tenant's administrator and any domain on earth, and until this
rung that claim captured the platform sign-in for everybody at it. Driven over
the wire on the baseline, both halves:

* a person who already belonged somewhere else — `403`, "already belongs to an
  account in another workspace", locked out of a product they use by a row a
  stranger wrote;
* a person who belonged nowhere — `302`, absorbed into the claimant as a
  `member`, with an `SsoIdentity` in a tenant they have never heard of, and the
  invitation standing for them elsewhere left `pending` forever.

Neither needed a second bug. Routing on a self-asserted claim IS the hole.

The law now: `SsoDomain.verified_at` is null until an operator runs
`manage.py verify_sso_domain`; `for_domain` honours verified rows only;
`claim()` does not filter, so the name stays reserved while the tenant waits;
and `provision_sso_identity` asks the same question again for itself, because a
service that trusts its caller to have checked is one refactor away from not
checking.

**An unverified claim reads exactly like no claim at all**, and that equality is
what several cases below assert directly: the `Realm` byte for byte, the
connection lookup, the enforcement answer.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import SsoConnection, SsoDomain, SsoIdentity, User
from apps.accounts.selectors import (
    get_connection_for_email,
    get_enforcing_connection_for,
    get_realm_for_email,
)
from apps.accounts.services import (
    SsoRefused,
    create_sso_connection,
    provision_sso_identity,
    update_sso_connection,
    verify_sso_domain,
)
from apps.accounts.tests.conftest import CLIENT_ID, CLIENT_SECRET, ISSUER, provider_landed
from apps.accounts.tests.stub_issuer import StubIssuer
from apps.accounts.tests.test_rp_login import sign_in
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.services import invite_member

pytestmark = pytest.mark.django_db

REALM_URL = "/api/v1/auth/realm/"
LIST_URL = "/api/v1/auth/sso-connections/"


def _operator(tenant: Tenant) -> Actor:
    """Who verifies in production: the deployment's operator, at the shell."""
    return system_actor(tenant)


# --- F1.1 · the column ---------------------------------------------------------


def test_a_fresh_claim_is_unverified(unverified_sso_connection: SsoConnection) -> None:
    """Null is the state every claim starts in, and it is the whole of the state."""
    rows = SsoDomain.objects.for_tenant(unverified_sso_connection.tenant).filter(
        connection=unverified_sso_connection
    )
    assert [row.domain for row in rows] == ["acme.com"]
    assert all(row.verified_at is None for row in rows)
    assert unverified_sso_connection.email_domains == ["acme.com"]
    assert unverified_sso_connection.verified_domains == []


# --- F1.2 · routing honours verified rows only; claims still reserve ----------


def test_an_unverified_claim_routes_nobody(
    api: Client, unverified_sso_connection: SsoConnection
) -> None:
    """Unclaimed and claimed-but-unverified are the same answer, byte for byte.

    The three pre-auth readers are asserted together because they are one
    question asked three ways — a fix that taught one of them about
    `verified_at` and left the others is the shape this test exists to catch.
    `enforced` is turned on first so the enforcement answer is a statement about
    routing rather than about a flag nobody set.
    """
    update_sso_connection(
        tenant=unverified_sso_connection.tenant,
        actor=_operator(unverified_sso_connection.tenant),
        connection=provider_landed(unverified_sso_connection),
        enforced=True,
    )

    assert get_realm_for_email("x@acme.com") == get_realm_for_email("x@nobody.example")
    assert get_connection_for_email("x@acme.com") is None
    assert get_enforcing_connection_for("x@acme.com") is None

    claimed = api.post(REALM_URL, {"email": "x@acme.com"}, content_type="application/json")
    unclaimed = api.post(REALM_URL, {"email": "x@nobody.example"}, content_type="application/json")
    assert claimed.status_code == unclaimed.status_code == 200
    assert claimed.json() == unclaimed.json()


def test_a_claim_still_reserves_the_name_before_it_is_verified(
    unverified_sso_connection: SsoConnection, other_tenant: Tenant, stranger_actor: Actor
) -> None:
    """Reserving is the half that must NOT wait for an operator.

    A claim that could be taken while its tenant waits would make verification a
    race somebody else can win, which is worse than the hole it closes.
    """
    with pytest.raises(Conflict) as refused:
        create_sso_connection(
            tenant=other_tenant,
            actor=stranger_actor,
            name="Globex Entra",
            issuer="https://idp.globex.example",
            client_id="globex-client-id",
            client_secret="globex-client-secret",  # noqa: S106 — a fake IdP client secret the test world configures  # pragma: allowlist secret
            email_domains=["acme.com"],
            default_role=Membership.Role.MEMBER,
        )
    assert "already claimed" in refused.value.detail


def test_a_verified_claim_routes_as_before(sso_connection: SsoConnection) -> None:
    """The control: the swept fixture is a connection that answers.

    Without this, every case above would pass on a product where nothing routes
    at all — which is exactly the failure a routing change can introduce.
    """
    assert get_connection_for_email("someone@acme.com") == sso_connection
    assert get_realm_for_email("someone@acme.com") != get_realm_for_email("someone@nobody.example")


# --- F1.3 · the lockout and the absorption, over the wire ---------------------


def test_a_claim_on_a_domain_with_people_elsewhere_locks_nobody_out(
    api: Client,
    stub_issuer: StubIssuer,
    owner: User,
    stranger: User,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """R2's F1a, closed: the person signs in and lands where they belong.

    `stranger@example.com` owns `other_tenant` and holds nothing in `tenant`;
    `tenant`'s owner claims `example.com` without verifying it. On the baseline
    this sign-in was a 403 — a foreign row locking somebody out of the platform.
    """
    create_sso_connection(
        tenant=tenant,
        actor=_operator(tenant),
        name="Acme Okta",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["example.com"],
        default_role=Membership.Role.MEMBER,
    )
    held_before = Membership.objects.filter(user_id=stranger.pk).count()

    stub_issuer.email = stranger.email
    stub_issuer.subject = "sub-not-locked-out"
    response = sign_in(api)

    assert response.status_code == 302
    assert api.session.get("_auth_user_id") == str(stranger.pk)
    assert Membership.objects.filter(user_id=stranger.pk).count() == held_before
    # No CUSTOMER connection's row: the platform join is the sign-in's own.
    assert not SsoIdentity.objects.filter(user_id=stranger.pk, connection__isnull=False).exists()


def test_a_stranger_at_an_unverified_domain_is_not_absorbed(
    api: Client,
    stub_issuer: StubIssuer,
    owner: User,
    tenant: Tenant,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> None:
    """R2's F1b, closed: the newcomer takes the platform branch and A1's join.

    A tenantless person with a standing invitation in `other_tenant` signs in
    while `tenant` holds an unverified claim on their domain. On the baseline
    they were absorbed into `tenant` as a `member`, with an `SsoIdentity`, and
    their invitation stayed `pending` — the real mechanism behind the
    dropped-invitation report. Now the claim
    routes nobody, so the assertion goes down the platform branch and the
    invitation join puts them where they were invited, at the role it names.
    """
    invitation, _ = invite_member(
        tenant=other_tenant,
        email="newcomer@example.com",
        actor=_operator(other_tenant),
        role=Membership.Role.ADMIN,
    )
    create_sso_connection(
        tenant=tenant,
        actor=_operator(tenant),
        name="Acme Okta",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["example.com"],
        default_role=Membership.Role.MEMBER,
    )

    stub_issuer.email = "newcomer@example.com"
    stub_issuer.subject = "sub-not-absorbed"
    response = sign_in(api)

    assert response.status_code == 302
    newcomer = User.objects.get(email="newcomer@example.com")
    # No CUSTOMER connection's row: the platform join is the sign-in's own.
    assert not SsoIdentity.objects.filter(user_id=newcomer.pk, connection__isnull=False).exists()
    assert not Membership.objects.filter(user_id=newcomer.pk, tenant=tenant).exists()
    landed = Membership.objects.get(user_id=newcomer.pk, tenant=other_tenant)
    assert landed.role == Membership.Role.ADMIN
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED


def test_once_verified_the_claim_moved_case_is_the_documented_refusal(
    api: Client,
    stub_issuer: StubIssuer,
    owner: User,
    stranger: User,
    tenant: Tenant,
) -> None:
    """The refusal survives — behind an operator's act instead of a POST.

    `provision_sso_identity`'s third refusal is not a defect: an address that
    belongs to somebody in another workspace is not taken over silently. What
    was wrong was who could put a person in front of it. Verified, the same
    sequence refuses exactly as it documents.
    """
    connection = create_sso_connection(
        tenant=tenant,
        actor=_operator(tenant),
        name="Acme Okta",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["example.com"],
        default_role=Membership.Role.MEMBER,
    )
    verify_sso_domain(
        tenant=tenant, actor=_operator(tenant), connection=connection, domain="example.com"
    )

    stub_issuer.email = stranger.email
    stub_issuer.subject = "sub-moved-claim"
    response = sign_in(api)

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session
    # No CUSTOMER connection's row: the platform join is the sign-in's own.
    assert not SsoIdentity.objects.filter(user_id=stranger.pk, connection__isnull=False).exists()


# --- F1.4 · the public-mail refusal at the door ------------------------------


def _claim(api: Client, owner: User, domains: list[str]) -> Any:
    api.force_login(owner)
    response = api.post(
        LIST_URL,
        {
            "name": "Acme Okta",
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "email_domains": domains,
            "default_role": "member",
            "enforced": False,
        },
        content_type="application/json",
    )
    api.logout()
    return response


def test_a_public_mail_domain_is_refused_at_the_door(api: Client, owner: User) -> None:
    """`gmail.com` is not an organisation's domain, and the door says so.

    Confirmed as a `201` on the baseline. The refusal is at the door rather than
    at verification because this is the mistake somebody makes while typing,
    and the response to that request is where they will read the answer.
    """
    response = _claim(api, owner, ["gmail.com"])

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid"
    assert "gmail.com" in " ".join(body["errors"]["email_domains"])
    assert not SsoConnection.objects.filter(tenant=None).exists()
    assert SsoConnection.objects.count() == 0
    assert SsoDomain.objects.count() == 0


def test_the_refused_set_is_the_knob(api: Client, owner: User, settings: Any) -> None:
    """The list is a courtesy, not the wall — so it is configuration, and it moves.

    Both directions, because a knob asserted in one direction is a constant
    somebody spelled differently. With the list emptied, `gmail.com` is accepted
    and **routes nobody**: the wall is `verified_at`, which is what makes a
    stale list a degradation rather than a hole.
    """
    settings.SSO_REFUSED_MAIL_DOMAINS = ["acme.com"]
    assert _claim(api, owner, ["acme.com"]).status_code == 400

    settings.SSO_REFUSED_MAIL_DOMAINS = []
    accepted = _claim(api, owner, ["gmail.com"])
    assert accepted.status_code == 201
    assert accepted.json()["verified_domains"] == []
    assert get_connection_for_email("somebody@gmail.com") is None


# --- F1.5 · the verification act ----------------------------------------------


def test_verifying_a_claim_writes_verified_at_and_an_audit_row(
    unverified_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """One column, one receipt, and the receipt says who and through which door."""
    before = timezone.now()
    row = verify_sso_domain(
        tenant=tenant,
        actor=_operator(tenant),
        connection=unverified_sso_connection,
        domain="acme.com",
    )

    assert row.verified_at is not None and row.verified_at >= before
    assert get_connection_for_email("someone@acme.com") == unverified_sso_connection
    entry = AuditEntry.objects.for_tenant(tenant).get(action="accounts.verify_sso_domain")
    assert entry.outcome == AuditEntry.Outcome.OK
    assert entry.actor_kind == "system"
    assert entry.object_id == row.pk


def test_verifying_a_domain_the_connection_does_not_claim_is_not_found(
    unverified_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """Not there and not yours are one answer: this door is no existence oracle."""
    with pytest.raises(NotFound):
        verify_sso_domain(
            tenant=tenant,
            actor=_operator(tenant),
            connection=unverified_sso_connection,
            domain="somebody-else.example",
        )
    assert SsoDomain.objects.filter(verified_at__isnull=False).count() == 0


def test_a_member_may_not_verify(
    unverified_sso_connection: SsoConnection, tenant: Tenant, member_actor: Actor
) -> None:
    """The wall a self-serve door would stand behind, written before that door exists."""
    with pytest.raises(Forbidden) as refused:
        verify_sso_domain(
            tenant=tenant,
            actor=member_actor,
            connection=unverified_sso_connection,
            domain="acme.com",
        )
    assert "verify an email domain" in refused.value.detail
    assert SsoDomain.objects.get(domain="acme.com").verified_at is None


def test_verifying_twice_is_one_state_and_two_receipts(
    unverified_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """Idempotent on the column, not on the ledger — `record_identity`'s shape."""
    first = verify_sso_domain(
        tenant=tenant,
        actor=_operator(tenant),
        connection=unverified_sso_connection,
        domain="acme.com",
    )
    second = verify_sso_domain(
        tenant=tenant,
        actor=_operator(tenant),
        connection=unverified_sso_connection,
        domain="acme.com",
    )

    assert second.verified_at == first.verified_at
    assert (
        AuditEntry.objects.for_tenant(tenant)
        .filter(action="accounts.verify_sso_domain", outcome=AuditEntry.Outcome.OK)
        .count()
        == 2
    )


# --- F1.7 · a re-save keeps a verification; a removal loses it ----------------


def test_patching_the_list_keeps_a_verified_domain_verified(
    sso_connection: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    """A row that stays in the wanted set is left alone, so its column survives.

    The property is `_apply_domains`' `if domain in current: continue`, and it
    matters because the alternative — a PATCH that adds one domain silently
    un-verifying another — would make every configuration change a routing
    outage somebody has to notice.
    """
    was = SsoDomain.objects.get(domain="acme.com").verified_at
    assert was is not None

    update_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        connection=sso_connection,
        email_domains=["acme.com", "acme.co.uk"],
    )

    assert SsoDomain.objects.get(domain="acme.com").verified_at == was
    assert SsoDomain.objects.get(domain="acme.co.uk").verified_at is None
    assert sso_connection.verified_domains == ["acme.com"]


def test_removing_and_re_adding_a_domain_starts_it_unverified(
    sso_connection: SsoConnection, tenant: Tenant, owner_actor: Actor
) -> None:
    """Dropping a claim drops its verification with it — a new row is a new claim.

    The honest answer: whoever removed the domain gave up the claim, and
    whatever an operator confirmed was about the claim that no longer exists.
    """
    update_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        connection=sso_connection,
        email_domains=["acme.co.uk"],
    )
    update_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        connection=sso_connection,
        email_domains=["acme.com"],
    )

    assert SsoDomain.objects.get(domain="acme.com").verified_at is None
    assert get_connection_for_email("someone@acme.com") is None


# --- F1.8 · the service trusts no caller -------------------------------------


def test_the_service_refuses_an_unverified_domain_even_when_called_directly(
    unverified_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """`for_domain` is one belt; this is the other, and it is the service's own.

    The login flow cannot reach here with an unverified claim — but a test, a
    command or a future door can call this service directly, and a service that
    trusted its caller to have checked is one refactor away from not checking.
    """
    with pytest.raises(SsoRefused) as refused:
        provision_sso_identity(
            tenant=tenant,
            actor=system_actor(tenant),
            connection=unverified_sso_connection,
            subject="okta|newcomer",
            email="newcomer@acme.com",
            email_verified=True,
        )

    assert "outside the domains" in refused.value.detail
    assert not User.objects.filter(email="newcomer@acme.com").exists()
    assert SsoIdentity.objects.count() == 0
    assert not Membership.objects.filter(tenant=tenant, role=Membership.Role.MEMBER).exists()
    entry = AuditEntry.objects.for_tenant(tenant).get(action="accounts.provision_sso_identity")
    assert entry.outcome == AuditEntry.Outcome.ERROR
