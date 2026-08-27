"""The first tenant of an installation, and the from-zero path that reaches it.

Two things are held down here and they are different.

**The command** (`manage.py bootstrap_tenant`): three rows in one transaction,
a refusal the second time, and an audit row that rides the tenant it just made
rather than the platform population — the birth certificate (ADR core-17).
`create_tenant` stays unaudited; nothing about it moved.

**The tenantless-mint fold.** Minting a token before any tenant
exists was reported to break on the audit row's not-null tenant. It was disproved — the row is
`Tenant | None` by design (ADR core-8's declared platform population) — but the
disproof was run against a repro that had drifted, and what it left behind was a
path nobody pins: *from zero*. So the last test here walks it end to end on a
database with no tenants at all, and it is **green at birth by design**. That is
what a regression pin is: the disproof is the evidence it pins, and the day the
platform population stops being nullable this file says so instead of a
production shell doing it.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Organization, Tenant

pytestmark = pytest.mark.django_db

PASSWORD = "bootstrap-tests-only"  # pragma: allowlist secret


def _run(**options: Any) -> str:
    out = io.StringIO()
    call_command("bootstrap_tenant", stdout=out, **options)
    return out.getvalue()


@pytest.fixture
def person(db: None) -> User:
    """Somebody who has signed in once and belongs to nothing yet.

    Which is the real state of the first person on a new installation: the
    identity provider made their record, and there is no tenant for them to be a
    member of.
    """
    return create_user(email="founder@yourcompany.com", password=PASSWORD)


# --- B-CORE2-1: it makes the first tenant ------------------------------------


def test_it_creates_one_tenant_its_root_and_one_owner(person: User) -> None:
    """Three rows, and the membership is an owner rather than a member."""
    assert not Tenant.objects.exists()

    printed = _run(email=person.email)

    tenant = Tenant.objects.get()
    root = Organization.objects.for_tenant(tenant).get()
    membership = Membership.objects.get()

    assert root.parent_id is None
    assert root.depth == 0
    assert membership.user_id == person.pk
    assert membership.tenant_id == tenant.pk
    assert membership.organization_id == root.pk
    assert membership.role == Membership.Role.OWNER
    assert membership.is_default is True
    assert tenant.slug in printed and person.email in printed


def test_the_audit_row_rides_the_tenant_it_created(person: User) -> None:
    """The birth certificate. Not the platform population.

    The `@service` wrapper takes an audit row's tenant from the call, and this
    call has none to give — so a row on the created tenant is the thing that had
    to be arranged rather than assumed, and it is the thing this asserts.
    """
    _run(email=person.email)
    tenant = Tenant.objects.get()

    row = AuditEntry.objects.for_tenant(tenant).get(action="core.create_first_tenant")

    assert row.tenant_id == tenant.pk
    assert row.door == "shell"
    assert row.outcome == "ok"
    assert row.object_type == "core.Tenant"
    assert row.object_id == tenant.pk
    assert not AuditEntry.objects.for_platform().filter(action="core.create_first_tenant").exists()


def test_create_tenant_is_still_unaudited(person: User) -> None:
    """The other half of the ADR: only the bootstrap writes a row, and only one."""
    _run(email=person.email)

    assert not AuditEntry.objects.filter(action="core.create_tenant").exists()
    assert AuditEntry.objects.filter(action="core.create_first_tenant").count() == 1


def test_the_name_and_slug_default_from_the_address(person: User) -> None:
    """An operator who types only an email still gets something readable."""
    _run(email=person.email)

    tenant = Tenant.objects.get()
    assert tenant.name == "yourcompany"
    assert tenant.slug == "yourcompany"


def test_the_name_and_slug_can_be_named(person: User) -> None:
    _run(email=person.email, name="Your Company Ltd", slug="yourco")

    tenant = Tenant.objects.get()
    assert tenant.name == "Your Company Ltd"
    assert tenant.slug == "yourco"


# --- B-CORE2-2: the refusal ---------------------------------------------------


def test_a_second_run_refuses_and_creates_nothing(person: User) -> None:
    """The safety of the whole command. Row counts are the assertion."""
    _run(email=person.email)
    before = (
        Tenant.objects.count(),
        Organization.objects.count(),
        Membership.objects.count(),
        AuditEntry.objects.count(),
    )

    with pytest.raises(CommandError) as refused:
        _run(email=person.email)

    assert "already has a tenant" in str(refused.value)
    assert (
        Tenant.objects.count(),
        Organization.objects.count(),
        Membership.objects.count(),
        AuditEntry.objects.count(),
    ) == before


def test_it_refuses_an_address_nobody_has(db: None) -> None:
    """A typo'd workforce email mints nothing, and the message says what to do.

    This is the mitigation for the blind spot the plan names: nothing can check
    that the address is the RIGHT person, so the command refuses an unknown one
    outright rather than creating a second account nobody asked for.
    """
    with pytest.raises(CommandError) as refused:
        _run(email="typo@yourcompany.com")

    assert "no account for typo@yourcompany.com" in str(refused.value)
    assert not Tenant.objects.exists()


def test_a_reserved_slug_is_refused(person: User) -> None:
    """`platform` is how the run ledger tells its two populations apart."""
    with pytest.raises(CommandError):
        _run(email=person.email, slug="platform")

    assert not Tenant.objects.exists()


# --- The tenantless-mint fold, pinned from zero --------------------------------


def test_from_zero_a_token_mints_tenantless_and_then_pins(person: User) -> None:
    """The whole path the stale repro fell out of, walked on a database with
    no tenants at all.

    Green at birth, deliberately. Three claims, in order:

    1. **before there is any tenant**, minting a token for a person who belongs
       to nothing succeeds — the token pins to no tenant, and the audit row it
       writes lands in the platform population (`tenant=None`), which is a
       declared population and not an accident;
    2. `bootstrap_tenant` then makes the first tenant;
    3. **the same mint now pins**, because the person has a default membership
       to resolve — which is the difference bootstrapping makes, said as a
       before-and-after rather than as prose.
    """
    assert not Tenant.objects.exists()

    # Through the SHELL, not by calling the service: `door` is bound by
    # `core.management.BaseCommand`, so a test that called the function directly
    # would assert `door=""` and prove nothing about the path an operator walks.
    minted = io.StringIO()
    call_command("issue_token", email=person.email, name="from-zero", scopes=["*"], stdout=minted)
    assert minted.getvalue()

    platform_rows = AuditEntry.objects.for_platform().filter(action="accounts.issue_token")
    assert platform_rows.count() == 1
    first = platform_rows.get()
    assert first.tenant_id is None
    assert first.door == "shell"

    _run(email=person.email)
    tenant = Tenant.objects.get()

    again = io.StringIO()
    call_command(
        "issue_token",
        email=person.email,
        name="after-bootstrap",
        tenant=tenant.slug,
        scopes=["*"],
        stdout=again,
    )
    pinned = AuditEntry.objects.for_tenant(tenant).filter(action="accounts.issue_token")
    assert pinned.count() == 1
    assert pinned.get().tenant_id == tenant.pk
    # And the platform row is still exactly one: bootstrapping did not reach
    # back and re-home history that was true when it was written.
    assert platform_rows.count() == 1
