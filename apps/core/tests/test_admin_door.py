"""The admin door's *reads*, and how it renders a service's refusal.

Two fixes here, both about the half of the admin door an earlier wall did not
reach:

* **the changelist leak** — that earlier wall walled the admin's membership
  *writes*. It could not wall the reads: `Membership` is a `BaseModel`, not a
  `TenantScopedModel`, so it has no `ScopedManager`, so
  `ServiceModelAdmin.get_queryset`'s scoped branch falls through to `super()`
  and `/admin/core/membership/` listed every tenant's membership table to any
  staff hat. The one door where "staff act across tenants" survived.
* **the swallowed refusal** (with its Conflict and audit-preserving cases) — a
  service refusal reaching the admin door was a 500. It was correct and it was
  audited-in-intent, and it looked like an outage: an above-ceiling grant
  through the membership form raised `Forbidden` out of `changeform_view`,
  which is wrapped in `transaction.atomic`, so the refusal took the
  `AuditEntry` that recorded it down with it on the rollback. Both halves are
  the same fix: catch at the base class, render through the one composer
  (`wire_refusal`), and let the view return normally so the audit row commits.

Driven through the real admin URLs with a real staff session wherever the claim
is about clicking Save or opening a changelist, following
`apps/example/tests/test_admin.py`. The one exception is the Conflict case,
and it says why where it stands.

DOES NOT COVER — declared: message *wording*. What is pinned is that the
rendered message carries the refusal's `code` and `detail`, which is what
`refusal_message` composes for every other door; the prose around it is
`wire_refusal`'s to change. Nor does it cover a *programming* error through
the same door: `ImproperlyConfigured` from `refuse_unwired` still escapes as a
500, deliberately — it is a message for whoever wrote the subclass, and
`test_admin_wall.py` holds that line.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, system_actor
from apps.core.admin import Action, ServiceModelAdmin
from apps.core.audit import AuditEntry
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import (
    add_membership,
    create_grant,
    create_organization,
    move_organization,
    root_organization,
)

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
LIST_URL = "/admin/core/membership/"
ADD_URL = "/admin/core/membership/add/"


@pytest.fixture
def two_hatted_staff(tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User) -> User:
    """A staff member who genuinely belongs to both tenants.

    Both memberships are needed for the `X-Tenant` half of the changelist leak: a header
    naming a tenant the user does not belong to resolves to `None` rather than
    to the other tenant (`core.middleware.resolve_tenant`), so a single-tenant
    staff member could not tell "the switch works" from "the switch fails
    closed". `owner` and `stranger` are asked for first so each tenant's
    *first* membership is its own owner and these two are not.
    """
    user = create_user(email="two-hats@example.com", password=PASSWORD, is_staff=True)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    add_membership(
        user=user,
        tenant=other_tenant,
        is_default=False,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=other_tenant),
    )
    return user


def _changelist_emails(page: str, candidates: tuple[User, ...]) -> set[str]:
    """Which of these people the rendered changelist actually names.

    Read off the response body rather than off `get_queryset`, because the
    claim is about what a staff member sees on the screen — and a narrowing
    that some later `get_list_display` widened back would pass a queryset
    assertion and fail this one.
    """
    return {user.email for user in candidates if user.email in page}


# --- the changelist leak: the changelist reads the acting tenant, and only it ---


def test_the_membership_changelist_shows_only_the_acting_tenants_rows(
    api: Client,
    two_hatted_staff: User,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    stranger: User,
) -> None:
    """The other tenant's membership table is not here.

    `owner` belongs to `tenant` and `stranger` to `other_tenant`, both planted
    by the fixtures through `create_tenant`/`add_membership`. Both used to
    appear on one page.
    """
    api.force_login(two_hatted_staff)

    page = api.get(LIST_URL).content.decode()

    assert _changelist_emails(page, (owner, stranger)) == {owner.email}


def test_switching_x_tenant_changes_the_membership_changelist(
    api: Client,
    two_hatted_staff: User,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    stranger: User,
) -> None:
    """The sibling that stops the test above passing for the wrong reason.

    A narrowing hard-wired to the default membership would satisfy the first
    test and fail this one. The same person, one header apart, sees a different
    table — which is what makes the first assertion about *acting* rather than
    about *being*.
    """
    api.force_login(two_hatted_staff)

    here = api.get(LIST_URL).content.decode()
    there = api.get(LIST_URL, headers={"x-tenant": other_tenant.slug}).content.decode()

    assert _changelist_emails(here, (owner, stranger)) == {owner.email}
    assert _changelist_emails(there, (owner, stranger)) == {stranger.email}


def test_a_superuser_with_no_membership_sees_no_memberships_at_all(
    api: Client, root: User, tenant: Tenant, owner: User
) -> None:
    """Fails closed, with no superuser exemption — the tenancy's own shape.

    `root` is a superuser who belongs to nowhere, so `resolve_tenant` answers
    `None` and the read answers nothing. The alternative — "no tenant means
    every tenant" — is the exemption `ServiceModelAdmin.get_queryset`'s
    docstring exists to refuse, and it would make the empty hat the widest one
    in the product. Now the empty hat is REFUSED rather than shown an
    empty page: no hat reads `membership`, and the change half no longer renders
    what the read refuses.
    """
    root.is_staff = True
    root.save(update_fields=["is_staff"])
    api.force_login(root)

    response = api.get(LIST_URL)

    assert response.status_code == 403
    assert owner.email not in response.content.decode()


# --- the swallowed refusal: a refusal is a message, not an outage --------------


@pytest.fixture
def staff_admin(tenant: Tenant, owner: User) -> User:
    """A staff member who is only an `admin` — the ceiling the wall measures."""
    user = create_user(email="ceilinged@example.com", password=PASSWORD, is_staff=True)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def newcomer(db: None) -> User:
    """Somebody with no membership anywhere, waiting to be given one."""
    return create_user(email="newcomer-b3@example.com", password=PASSWORD)


def _messages(response: Any) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def test_an_above_ceiling_grant_through_the_admin_is_a_message_not_a_500(
    api: Client, staff_admin: User, newcomer: User, tenant: Tenant
) -> None:
    """The escalation wall's refusal, rendered.

    The same refusal `test_admin_wall.py` proves the wall raises — an `admin`
    minting an `owner` — arriving where a support agent can read it. Followed,
    because "renders the changelist again" is a redirect and then a page, and
    the criterion is about the page.
    """
    api.force_login(staff_admin)

    response = api.post(
        ADD_URL,
        data={
            "user": str(newcomer.pk),
            "tenant": str(tenant.pk),
            "organization": str(root_organization(tenant=tenant).pk),
            "role": Membership.Role.OWNER,
        },
        follow=True,
    )

    assert response.status_code == 200, response.content
    assert response.redirect_chain, "the refusal did not re-show a page at all"
    rendered = _messages(response)
    assert any("forbidden" in message for message in rendered), rendered
    assert not Membership.objects.filter(user_id=newcomer.pk, tenant=tenant).exists()


def test_the_refused_admin_save_is_still_audited(
    api: Client, staff_admin: User, newcomer: User, tenant: Tenant
) -> None:
    """The mapper did not eat the audit row along with the 500.

    This is the half that was *not* presentation. Django wraps
    `changeform_view` in `transaction.atomic`, so the `AuditEntry` the
    `@service` decorator writes on the refusal path used to be rolled back with
    everything else when `Forbidden` escaped the view — the refusal was loud on
    the console and invisible in the trail. Returning normally is what lets it
    commit.
    """
    api.force_login(staff_admin)
    AuditEntry.objects.all().delete()

    api.post(
        ADD_URL,
        data={
            "user": str(newcomer.pk),
            "tenant": str(tenant.pk),
            "organization": str(root_organization(tenant=tenant).pk),
            "role": Membership.Role.OWNER,
        },
    )

    entry = AuditEntry.objects.for_tenant(tenant).get(action="core.add_membership")
    assert entry.door == "admin"
    assert entry.outcome == AuditEntry.Outcome.ERROR
    assert entry.error_code == "forbidden"
    assert entry.actor_user_id == staff_admin.pk


# --- the Conflict case: the same grammar for a Conflict, not only for a Forbidden ---


def _request_with_messages(user: User, path: str = "/admin/") -> Any:
    """A real request a `ModelAdmin` can hang a message on.

    `RequestFactory` builds no session and no message store, and
    `messages.error` on a request without one raises rather than degrading.
    """
    request = RequestFactory().post(path)
    request.user = user
    request.session = SessionStore()
    # `setattr`, because `_messages` is the private name `MessageMiddleware`
    # writes and no request type declares it.
    setattr(request, "_messages", FallbackStorage(request))  # noqa: B010
    return request


def test_a_conflict_from_the_move_service_renders_the_same_way(
    tenant: Tenant, owner: User, owner_actor: Actor, root_org: Organization
) -> None:
    """`move_organization`'s in-flight `Conflict`, through the mapper.

    **Why this one is not driven over a URL, stated rather than hidden:** when
    this test was written the product had no admin form that moved a node —
    `OrganizationAdmin` makes `parent` read-only on purpose, re-parenting being
    a durable run rather than a dropdown — so there was no `/admin/` path that
    reached `move_organization` at all. **ADR core-10 built one**: the
    `move_to_new_parent` action, driven over its real URLs in
    `apps/core/tests/test_admin_move.py`, where the same `Conflict` is now
    asserted as a message on a real page.

    This test stays, and stays here, because it is not about that door. What
    this case was about is that the mapper is generic over `DomainError`
    rather than a `Forbidden` special case, so it is driven at the class the
    mapper lives on — the *next* subclass somebody writes, wired to a service
    that conflicts, with no `OrganizationAdmin` in the picture. The refusal is
    real: a second, different destination while the first intent is live,
    raised synchronously inside `record_run` — no Temporal server is needed to
    be told the id is taken.
    """
    first = create_organization(
        tenant=tenant, parent=root_org, name="First", slug="first", actor=owner_actor
    )
    second = create_organization(
        tenant=tenant, parent=root_org, name="Second", slug="second", actor=owner_actor
    )
    node = create_organization(
        tenant=tenant, parent=root_org, name="Node", slug="node", actor=owner_actor
    )
    move_organization(tenant=tenant, organization=node, new_parent=first, actor=owner_actor)

    class MoveAdmin(ServiceModelAdmin[Organization]):
        """The next subclass somebody writes — wired to a service that conflicts."""

        object_kwarg = "organization"

        def service_for(self, action: Action) -> Any | None:
            return move_organization

        def acting(self, request: HttpRequest) -> tuple[Actor, Tenant | None]:
            return owner_actor, tenant

        def call_service(self, service: Any, **kwargs: Any) -> None:
            service(
                tenant=tenant,
                organization=kwargs["obj"],
                new_parent=second,
                actor=owner_actor,
            )

    from django.contrib import admin as django_admin

    door = MoveAdmin(Organization, django_admin.site)
    request = _request_with_messages(owner)

    door.save_model(request, node, form=None, change=True)  # type: ignore[arg-type]

    rendered = [str(message) for message in get_messages(request)]
    assert any("conflict" in message for message in rendered), rendered
    node.refresh_from_db()
    assert node.parent_id == root_org.pk


# --- no write without the read — a superuser's hat decides what they see ---


@pytest.fixture
def hatted_superuser(tenant: Tenant, owner: User) -> tuple[User, Membership]:
    """A staff superuser whose one membership is `admin` at the root of `tenant`."""
    user = create_user(email="super-hat@example.com", password=PASSWORD, is_staff=True)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    membership = add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return user, membership


def test_a_superuser_whose_hat_withholds_the_read_gets_no_changelist_and_no_change_view(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    hatted_superuser: tuple[User, Membership],
) -> None:
    """The change half no longer renders what the read half refuses.

    Django gates a changelist on `has_view_or_change_permission`, so before this
    a superuser rendered it through the CHANGE half whatever the hat's read said.
    The withhold goes through `create_grant`, the hand-out service, never a raw row.
    """
    user, membership = hatted_superuser
    api.force_login(user)
    change_url = f"/admin/core/organization/{root_org.pk}/change/"

    assert api.get("/admin/core/organization/").status_code == 200
    assert api.get(change_url).status_code == 200

    create_grant(
        tenant=tenant,
        actor=owner_actor,
        membership=membership,
        permission="organization.read",
        effect=Grant.Effect.WITHHOLD,
    )

    assert api.get("/admin/core/organization/").status_code == 403
    assert api.get(change_url).status_code == 403
