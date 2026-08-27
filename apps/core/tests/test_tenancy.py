"""Tenancy, at the level it is decided: memberships and the resolution rule.

The API side of the same rules is proved in `apps/example/tests/test_api.py`,
through the door a client actually uses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db.utils import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from apps.accounts.models import User
from apps.core.actor import system_actor
from apps.core.exceptions import Invalid
from apps.core.middleware import TenantMiddleware, resolve_tenant
from apps.core.models import Membership, Organization, Tenant
from apps.core.requests import TenantRequest
from apps.core.services import add_membership, create_tenant, root_organization

pytestmark = pytest.mark.django_db


def test_create_tenant_lowercases_the_slug() -> None:
    tenant = create_tenant(name="  Acme Industries ", slug="  ACME  ", actor=system_actor())
    assert tenant.name == "Acme Industries"
    assert tenant.slug == "acme"


def test_a_slug_is_unique() -> None:
    create_tenant(name="One", slug="taken", actor=system_actor())
    with pytest.raises(Invalid):
        create_tenant(name="Two", slug="taken", actor=system_actor())


def test_a_user_joins_a_tenant_once(tenant: Tenant, nomad: User) -> None:
    add_membership(user=nomad, tenant=tenant, actor=system_actor(tenant=tenant))
    with pytest.raises(Invalid):
        add_membership(user=nomad, tenant=tenant, actor=system_actor(tenant=tenant))


def test_a_second_default_membership_moves_the_flag(
    tenant: Tenant, other_tenant: Tenant, nomad: User
) -> None:
    first = add_membership(
        user=nomad, tenant=tenant, is_default=True, actor=system_actor(tenant=tenant)
    )
    second = add_membership(
        user=nomad, tenant=other_tenant, is_default=True, actor=system_actor(tenant=other_tenant)
    )
    first.refresh_from_db()
    assert first.is_default is False
    assert second.is_default is True
    assert Membership.objects.filter(user=nomad, is_default=True).count() == 1


def test_the_database_refuses_two_defaults_for_one_user(
    tenant: Tenant, other_tenant: Tenant, nomad: User
) -> None:
    add_membership(user=nomad, tenant=tenant, is_default=True, actor=system_actor(tenant=tenant))
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=nomad, tenant=other_tenant, is_default=True)


def test_anonymous_resolves_to_no_tenant() -> None:
    assert resolve_tenant(user=AnonymousUser(), requested_slug=None) is None


def test_a_user_resolves_to_their_default_tenant(tenant: Tenant, owner: User) -> None:
    assert resolve_tenant(user=owner, requested_slug=None) == tenant


def test_a_user_without_a_membership_resolves_to_nothing(nomad: User) -> None:
    assert resolve_tenant(user=nomad, requested_slug=None) is None


def test_a_superuser_without_a_membership_resolves_to_nothing(root: User) -> None:
    assert root.is_superuser is True
    assert resolve_tenant(user=root, requested_slug=None) is None


def test_the_header_switches_to_another_tenant_the_user_belongs_to(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    add_membership(user=owner, tenant=other_tenant, actor=system_actor(tenant=other_tenant))
    assert resolve_tenant(user=owner, requested_slug="globex") == other_tenant


def test_the_header_naming_a_tenant_the_user_is_not_in_resolves_to_nothing(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    assert resolve_tenant(user=owner, requested_slug="globex") is None


def _recorder(seen: list[Tenant | None]) -> Callable[[HttpRequest], HttpResponse]:
    """A view that only writes down which tenant the middleware resolved."""

    def view(request: HttpRequest) -> HttpResponse:
        seen.append(cast(TenantRequest, request).tenant)
        return HttpResponse("ok")

    return view


def test_the_middleware_puts_the_tenant_on_the_request(tenant: Tenant, owner: User) -> None:
    seen: list[Tenant | None] = []
    request = RequestFactory().get("/")
    request.user = owner
    TenantMiddleware(_recorder(seen))(request)
    assert seen == [tenant]


def test_the_middleware_honours_the_header(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    add_membership(user=owner, tenant=other_tenant, actor=system_actor(tenant=other_tenant))
    seen: list[Tenant | None] = []
    request = RequestFactory().get("/", headers={"x-tenant": other_tenant.slug})
    request.user = owner
    TenantMiddleware(_recorder(seen))(request)
    assert seen == [other_tenant]


# --- The hat, at the level it is decided ------------------------------------


def _org_recorder(seen: list[Organization | None]) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        seen.append(cast(TenantRequest, request).org)
        return HttpResponse("ok")

    return view


def test_the_middleware_puts_the_acting_org_on_the_request(tenant: Tenant, owner: User) -> None:
    """The default hat is the default membership's own node — the root, here."""
    seen: list[Organization | None] = []
    request = RequestFactory().get("/")
    request.user = owner
    TenantMiddleware(_org_recorder(seen))(request)
    assert seen == [root_organization(tenant=tenant)]


def test_an_anonymous_request_gets_no_hat() -> None:
    seen: list[Organization | None] = []
    request = RequestFactory().get("/", headers={"x-org": "acme"})
    request.user = AnonymousUser()
    TenantMiddleware(_org_recorder(seen))(request)
    assert seen == [None]


def test_visible_to_none_is_empty_and_refuses_a_model_it_cannot_scope(
    tenant: Tenant, owner: User
) -> None:
    """Both halves of the contract `visible_to` carries.

    Empty for an unresolved hat — the fail-closed shape `for_tenant` already
    has — and a loud refusal for a model that has no organization at all,
    because silently answering "everything" there would be the failure this
    exists to prevent, wearing the name of the thing that prevents it.

    The unscopable model is `AuditEntry`, which is tenant-scoped and carries an
    `acting_org` (a fact about the request) rather than an `organization` (a
    fact about the row). It used to be `Invitation`, until ADR core-20 gave an
    invitation the node it was sent from and moved it out of this population —
    which is the right way for this test to have gone red.
    """
    from apps.core.audit import AuditEntry
    from apps.example.models import Widget

    assert Widget.objects.for_tenant(tenant).visible_to(None).count() == 0
    with pytest.raises(TypeError):
        AuditEntry.objects.for_tenant(tenant).visible_to(root_organization(tenant=tenant))
