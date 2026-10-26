"""`manage.py sso_domains` lists the claims that route nobody, each with its verify command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import SsoConnection
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db


def _list(**options: object) -> str:
    out = StringIO()
    call_command("sso_domains", stdout=out, **options)
    return out.getvalue()


def test_unverified_lists_every_tenants_waiting_claims_and_the_command_that_verifies_each(
    unverified_sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
    tenant: Tenant,
) -> None:
    """Across tenants, at the operator's altitude; Globex's verified claim is not on the list."""
    printed = _list(unverified=True)

    assert "acme.com" in printed, printed
    assert f"manage.py verify_sso_domain --tenant {tenant.slug} --domain acme.com" in printed
    assert "globex.com" not in printed, printed


def test_without_the_flag_every_claim_is_listed_with_its_state(
    unverified_sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
) -> None:
    lines = _list().splitlines()

    assert any(line.startswith("acme.com") and "unverified" in line for line in lines), lines
    assert any(line.startswith("globex.com") and "verified " in line for line in lines), lines


def test_an_empty_list_says_so_and_exits_zero(sso_connection: SsoConnection) -> None:
    """Nothing waiting is the answer an operator hopes for, printed rather than silent."""
    assert _list(unverified=True).strip() == "no unverified domain claims"
