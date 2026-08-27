"""User creation has one write path, and it is this one."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import User
from apps.accounts.services import create_user, deactivate_user
from apps.core.actor import actor_for
from apps.core.exceptions import Invalid
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db


def test_create_user_normalises_the_email_and_hashes_the_password() -> None:
    user = create_user(email="Person@Example.COM", password="a-long-enough-password")
    assert user.email == "person@example.com"
    assert user.pk is not None
    assert user.password != "a-long-enough-password"  # pragma: allowlist secret
    assert user.check_password("a-long-enough-password")
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False


def test_create_user_is_the_configured_user_model() -> None:
    user = create_user(email="who@example.com", password="a-long-enough-password")
    assert isinstance(user, get_user_model())
    assert get_user_model() is User


def test_create_superuser_sets_both_flags() -> None:
    user = create_user(
        email="boss@example.com",
        password="a-long-enough-password",  # pragma: allowlist secret
        is_superuser=True,
    )
    assert user.is_staff is True
    assert user.is_superuser is True


def test_a_second_user_cannot_reuse_an_email() -> None:
    create_user(
        email="taken@example.com",
        password="a-long-enough-password",  # pragma: allowlist secret
    )
    with pytest.raises(Invalid):
        create_user(
            email="TAKEN@example.com",
            password="a-long-enough-password",  # pragma: allowlist secret
        )


def test_an_empty_email_is_refused() -> None:
    with pytest.raises(ValueError):
        create_user(email="", password="a-long-enough-password")  # pragma: allowlist secret


def test_deactivate_user_keeps_the_row(tenant: Tenant, owner: User) -> None:
    # Deactivating yourself: the self clause of
    # `policies.themselves_or_administers_the_whole_tenant`, and the shape the
    # `me/` door takes. The owner is privileged either way, which is why the
    # door tests carry the member's version of this.
    deactivate_user(user=owner, actor=actor_for(user=owner, tenant=tenant), tenant=tenant)
    owner.refresh_from_db()
    assert owner.is_active is False
    assert User.objects.filter(pk=owner.pk).exists()
