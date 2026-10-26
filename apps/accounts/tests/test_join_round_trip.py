"""Rolling `accounts` back past 0011 and forward again keeps each join row in its realm."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps as django_apps

from apps.accounts.models import STAFF_REALM, SsoIdentity, User
from apps.accounts.services import create_user
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

JOIN = import_module("apps.accounts.migrations.0011_identity_home_and_join")
SURVIVE = import_module("apps.accounts.migrations.0012_join_rows_survive_a_rollback")


def _join(user: User, *, realm: str, subject: str, tenant: Tenant | None) -> None:
    SsoIdentity.objects.create(
        user=user, realm=realm, subject=subject, tenant=tenant, connection=None, email=user.email
    )


def _rows() -> list[tuple[str, str, object]]:
    joined = SsoIdentity.objects.filter(connection__isnull=True)
    return sorted(joined.values_list("realm", "subject", "tenant_id"))


@pytest.fixture
def world(tenant: Tenant) -> Tenant:
    _join(
        create_user(email="realm-only@example.com", password=None),
        realm="realm-123",
        subject="sub-tenant",
        tenant=tenant,
    )
    _join(
        create_user(email="staff@example.com", password=None),
        realm=STAFF_REALM,
        subject="sub-staff",
        tenant=None,
    )
    return tenant


def test_a_rollback_round_trip_keeps_the_tenant_realm(world: Tenant) -> None:
    SURVIVE.record_realms_for_rollback(django_apps, None)
    JOIN.write_subjects_back(django_apps, None)
    JOIN.move_subjects_into_the_join(django_apps, None)
    SURVIVE.rehome_marked_subjects(django_apps, None)

    assert _rows() == [("realm-123", "sub-tenant", world.pk), (STAFF_REALM, "sub-staff", None)]


def test_a_one_step_rollback_through_0012_keeps_the_tenant_realm(world: Tenant) -> None:
    SURVIVE.record_realms_for_rollback(django_apps, None)
    SURVIVE.rehome_marked_subjects(django_apps, None)

    assert _rows() == [("realm-123", "sub-tenant", world.pk), (STAFF_REALM, "sub-staff", None)]


def test_the_forward_is_a_no_op_on_a_database_that_never_rolled_back(world: Tenant) -> None:
    before = _rows()
    SURVIVE.rehome_marked_subjects(django_apps, None)
    assert _rows() == before


def test_0011_alone_re_spells_the_tenant_row_staff(world: Tenant) -> None:
    """The defect 0012 exists for."""
    JOIN.write_subjects_back(django_apps, None)
    JOIN.move_subjects_into_the_join(django_apps, None)
    assert ("staff", "sub-tenant", None) in _rows()
