"""`manage.py seed` — what a fresh clone gets, and what it refuses to do."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.management.commands.seed import (
    SEED_MEMBER_EMAIL,
    SEED_OWNER_EMAIL,
    SEED_PASSWORD,
)
from apps.accounts.models import ApiToken, User
from apps.accounts.services import authenticate_token
from apps.core.models import Membership, Tenant

pytestmark = pytest.mark.django_db


def _run(**options: Any) -> str:
    out = StringIO()
    # DEBUG is off under pytest, which is exactly the guard being bypassed here
    # — deliberately, and named, so the guard's own test below still means
    # something.
    call_command("seed", stdout=out, force=True, **options)
    return out.getvalue()


def test_a_fresh_database_becomes_drivable() -> None:
    """An empty database with tenancy on correctly answers nothing. This is the fix."""
    printed = _run()

    tenant = Tenant.objects.get(slug="acme")
    owner = User.objects.get(email=SEED_OWNER_EMAIL)
    member = User.objects.get(email=SEED_MEMBER_EMAIL)

    assert owner.check_password(SEED_PASSWORD)
    assert Membership.objects.get(user_id=owner.pk, tenant=tenant).role == Membership.Role.OWNER
    assert Membership.objects.get(user_id=member.pk, tenant=tenant).role == Membership.Role.MEMBER
    assert SEED_OWNER_EMAIL in printed


def test_the_printed_token_actually_works() -> None:
    printed = _run()
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))

    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved.user.email == SEED_OWNER_EMAIL
    assert resolved.tenant is not None and resolved.tenant.slug == "acme"


def test_running_it_twice_adds_a_token_and_nothing_else() -> None:
    """Idempotent where it must be, and not where re-running is the point.

    A token's plaintext is shown once, so "run seed again" is how somebody gets
    another one. Everything else is found rather than remade.
    """
    _run()
    _run()

    assert Tenant.objects.filter(slug="acme").count() == 1
    assert User.objects.filter(email=SEED_OWNER_EMAIL).count() == 1
    assert Membership.objects.filter(tenant__slug="acme").count() == 2
    assert ApiToken.objects.count() == 2


def test_it_refuses_to_seed_published_credentials_without_being_told_twice() -> None:
    """DEBUG is off under pytest, which is the same shape as a real deployment.

    `owner@example.com` with a password published in this repository is not test
    data on an internet-facing box; it is an account.
    """
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("seed", stdout=out)

    assert not User.objects.filter(email=SEED_OWNER_EMAIL).exists()
    assert not Tenant.objects.exists()


def test_it_seeds_whatever_tenant_it_is_given() -> None:
    _run(tenant="Globex")

    tenant = Tenant.objects.get(slug="globex")
    assert Membership.objects.filter(tenant=tenant).count() == 2
