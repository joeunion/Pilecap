"""The token the machine doors authenticate with."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import ApiToken, User
from apps.accounts.services import (
    authenticate_token,
    deactivate_user,
    hash_token,
    issue_token,
    revoke_token,
)
from apps.core.actor import actor_for, system_actor
from apps.core.models import Tenant
from apps.core.services import add_membership, suspend_tenant

pytestmark = pytest.mark.django_db


def test_issue_token_returns_a_plaintext_that_is_not_stored(tenant: Tenant, owner: User) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    assert plaintext.startswith("djb_")
    assert token.key_hash == hash_token(plaintext)
    assert plaintext not in token.key_hash
    assert ApiToken.objects.filter(key_hash=plaintext).count() == 0


def test_a_token_resolves_to_its_user_and_tenant(tenant: Tenant, owner: User) -> None:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    user, resolved_tenant, _row = resolved
    assert user == owner
    assert resolved_tenant == tenant


def test_a_token_without_a_tenant_resolves_the_users_default(tenant: Tenant, owner: User) -> None:
    _, plaintext = issue_token(
        user=owner, tenant=None, name="unpinned", actor=actor_for(user=owner, tenant=None)
    )
    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[1] == tenant


def test_a_token_for_a_user_with_no_membership_resolves_to_no_tenant(nomad: User) -> None:
    _, plaintext = issue_token(
        user=nomad, tenant=None, name="homeless", actor=actor_for(user=nomad, tenant=None)
    )
    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[1] is None


def test_using_a_token_records_when(tenant: Tenant, owner: User) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    assert token.last_used_at is None
    authenticate_token(plaintext=plaintext)
    token.refresh_from_db()
    assert token.last_used_at is not None


def test_last_used_at_is_written_at_most_once_per_touch_window(
    tenant: Tenant, owner: User, django_assert_num_queries: Any
) -> None:
    """The hot path is a read. Two calls inside the window must not be two writes.

    Four queries would mean SELECT+UPDATE twice; three is SELECT+UPDATE then
    SELECT alone, which is the whole point of `ACCOUNTS_TOKEN_TOUCH_SECONDS`.
    """
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    with django_assert_num_queries(3):
        assert authenticate_token(plaintext=plaintext) is not None
        assert authenticate_token(plaintext=plaintext) is not None
    token.refresh_from_db()
    first = token.last_used_at
    assert first is not None

    # A third call, still inside the window, still does not write.
    authenticate_token(plaintext=plaintext)
    token.refresh_from_db()
    assert token.last_used_at == first


def test_last_used_at_is_written_again_once_the_window_has_passed(
    tenant: Tenant, owner: User, settings: Any
) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    authenticate_token(plaintext=plaintext)
    token.refresh_from_db()
    stale = timezone.now() - timedelta(seconds=settings.ACCOUNTS_TOKEN_TOUCH_SECONDS + 1)
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=stale)

    authenticate_token(plaintext=plaintext)
    token.refresh_from_db()
    assert token.last_used_at is not None
    assert token.last_used_at > stale


def test_a_pinned_token_authenticates_as_its_pin_whatever_the_header_asks_for(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    """It answers WHO, and never where-you-may-act (ADR core-21).

    This used to answer `None` for a mismatched header — the credential simply
    failing — and the wire then said 401 "we could not tell who is making this
    request" over a live token belonging to a real active user. The refusal is
    the DOOR's, at 403, and a door cannot say "authenticated, then refused"
    about a credential that failed. The wire half is driven in
    `apps/core/tests/test_addressing_headers.py`.
    """
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="pinned", actor=actor_for(user=owner, tenant=tenant)
    )
    mismatched = authenticate_token(plaintext=plaintext, requested_slug=other_tenant.slug)
    assert mismatched is not None
    assert mismatched[1] == tenant
    # And a header naming its own tenant is still fine.
    resolved = authenticate_token(plaintext=plaintext, requested_slug=tenant.slug)
    assert resolved is not None
    assert resolved[1] == tenant


def test_a_mismatched_tenant_header_is_still_a_use_of_the_credential(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    """The token really was presented and really did authenticate (ADR core-21).

    The other side of the ruling: "a refused request is not a use" was true
    while the credential was what failed. Now the credential works and the
    ADDRESS is what was refused, so `last_used_at` moves — a token that
    authenticated is a token that was used, and an operator hunting a live
    credential wants to see it.
    """
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="pinned", actor=actor_for(user=owner, tenant=tenant)
    )
    assert authenticate_token(plaintext=plaintext, requested_slug=other_tenant.slug) is not None
    token.refresh_from_db()
    assert token.last_used_at is not None


def test_an_unpinned_token_resolves_a_header_the_user_belongs_to(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    add_membership(user=owner, tenant=other_tenant, actor=system_actor(tenant=other_tenant))
    _, plaintext = issue_token(
        user=owner, tenant=None, name="unpinned", actor=actor_for(user=owner, tenant=None)
    )
    resolved = authenticate_token(plaintext=plaintext, requested_slug=other_tenant.slug)
    assert resolved is not None
    assert resolved[1] == other_tenant


def test_an_unpinned_token_fails_closed_on_a_header_the_user_does_not_belong_to(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    _, plaintext = issue_token(
        user=owner, tenant=None, name="unpinned", actor=actor_for(user=owner, tenant=None)
    )
    resolved = authenticate_token(plaintext=plaintext, requested_slug=other_tenant.slug)
    assert resolved is not None
    assert resolved[1] is None


def test_a_revoked_token_stops_working(tenant: Tenant, owner: User) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )
    assert authenticate_token(plaintext=plaintext) is None
    assert ApiToken.objects.filter(pk=token.pk).exists()


def test_a_deactivated_users_token_stops_working(tenant: Tenant, owner: User) -> None:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    deactivate_user(user=owner, actor=actor_for(user=owner, tenant=tenant), tenant=tenant)
    assert authenticate_token(plaintext=plaintext) is None


def test_nonsense_is_not_a_token() -> None:
    assert authenticate_token(plaintext="nonsense") is None
    assert authenticate_token(plaintext="") is None


def test_a_pinned_token_to_a_suspended_tenant_authenticates_and_resolves_nowhere(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """A dark tenant is nowhere, and a credential that points there points nowhere.

    **Authenticated, not rejected** (ADR core-21). The token is real, unrevoked
    and belongs to a live person, so answering `None` would put a false fact on
    the wire — "we could not tell who is making this request" — which is the
    exact shape the pinned branch was written to stop telling. What is untrue
    after a suspension is the ADDRESS, so the tenant resolves to nothing and
    each door says its own no.

    The touch is asserted for the same reason it is asserted for a mismatched
    header: a credential that authenticated was used, and an operator hunting a
    live token wants to see it.
    """
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="pinned", actor=actor_for(user=owner, tenant=tenant)
    )
    suspend_tenant(tenant=tenant, reason="unpaid", actor=system_actor(tenant=tenant))

    resolved = authenticate_token(plaintext=plaintext)

    assert resolved is not None, "a real credential still authenticates"
    assert resolved.user == owner
    assert resolved.tenant is None, "a suspended tenant resolves nowhere"
    token.refresh_from_db()
    assert token.last_used_at is not None

    # And the door says so, in both header cells: omitted, and naming the pin.
    bearer = f"Bearer {plaintext}"
    omitted = api.get("/api/v1/organizations/", HTTP_AUTHORIZATION=bearer)
    naming_the_pin = api.get(
        "/api/v1/organizations/", HTTP_AUTHORIZATION=bearer, HTTP_X_TENANT=tenant.slug
    )
    assert omitted.status_code == 403
    assert naming_the_pin.status_code == 403
