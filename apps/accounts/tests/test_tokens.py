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
from apps.core.audit import AuditEntry
from apps.core.models import Tenant
from apps.core.services import add_membership, suspend_tenant
from apps.core.surfaces import Surface, resolve_surface
from apps.core.tests import test_surfaces as surface_world
from apps.core.tests.test_surfaces import CUSTOMER_HOST, NOT_EXPOSED, STAFF_HOST

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


# --- The bearer at a surface: it authenticates anywhere, the host filters ------
#
# A token is not a cookie: it authenticates at every host (the session stance,
# `apps.core.surfaces`), and the host it is presented at still decides which
# families answer. The world is `test_surfaces.py`'s — a scratch `customer`
# surface at `customer.localhost` exposing `widgets` alone — and the token
# carries no ceiling, so what narrows it here is the surface and nothing else.

customer_role = surface_world.customer_role
two_faces = surface_world.two_faces
customer = surface_world.customer


def _bearer_client(
    user: User, tenant: Tenant, *, name: str = "surface"
) -> tuple[Client, dict[str, str]]:
    _, plaintext = issue_token(
        user=user, tenant=tenant, name=name, actor=actor_for(user=user, tenant=tenant)
    )
    return Client(), {"authorization": f"Bearer {plaintext}"}


def _widget_made_by(owner: User, tenant: Tenant) -> str:
    """One Widget, made through the staff host's own door — this app never imports the example's."""
    client, credential = _bearer_client(owner, tenant, name="the widget's maker")
    made = client.post(
        "/api/v1/widgets/",
        {"name": "W"},
        content_type="application/json",
        HTTP_HOST=STAFF_HOST,
        headers=credential,
    )
    assert made.status_code == 201, made.content
    return str(made.json()["id"])


def test_a_bearer_at_the_customer_host_reaches_only_what_that_host_exposes(
    two_faces: Surface, tenant: Tenant, owner: User, customer: User
) -> None:
    widget_id = _widget_made_by(owner, tenant)
    client, credential = _bearer_client(customer, tenant)

    notes = client.get(
        f"/api/v1/djb_notes/?subject=widget:{widget_id}",
        HTTP_HOST=CUSTOMER_HOST,
        headers=credential,
    )
    widgets = client.get("/api/v1/widgets/", HTTP_HOST=CUSTOMER_HOST, headers=credential)

    assert notes.status_code == 404, notes.content
    assert notes.json()["code"] == NOT_EXPOSED
    assert widgets.status_code == 200, widgets.content
    assert [row["id"] for row in widgets.json()["items"]] == [widget_id]
    # The acts a face is offered are the surface's too: `read` is never an act.
    assert widgets.json()["items"][0]["allowed_acts"] == []


def test_the_same_bearer_holder_at_the_staff_host_reaches_every_family(
    two_faces: Surface, tenant: Tenant, owner: User
) -> None:
    widget_id = _widget_made_by(owner, tenant)
    client, credential = _bearer_client(owner, tenant)

    notes = client.get(
        f"/api/v1/djb_notes/?subject=widget:{widget_id}", HTTP_HOST=STAFF_HOST, headers=credential
    )

    assert notes.status_code == 200, notes.content


def test_a_bearer_write_at_the_customer_host_is_audited_as_made_there(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    client, credential = _bearer_client(customer, tenant)

    refused = client.post(
        "/api/v1/widgets/",
        {"name": "From a customer"},
        content_type="application/json",
        HTTP_HOST=CUSTOMER_HOST,
        headers=credential,
    )

    # The customer role holds exactly its declaration, so the create is refused,
    # and the refusal's `outcome=error` row carries the surface it came in at.
    assert refused.status_code == 403, refused.content
    written = list(
        AuditEntry.objects.filter(
            action="example.create_widget", actor_user_id=customer.pk
        ).values_list("surface", "outcome", "object_id")
    )
    assert {surface for surface, _, _ in written} == {"customer"}
    assert {(outcome, object_id) for _, outcome, object_id in written} == {("error", None)}


def test_a_bearer_and_a_session_resolve_the_same_tenant_at_the_customer_host(
    two_faces: Surface, tenant: Tenant, owner: User
) -> None:
    """The token door resolves under the surface, as the session door does.

    `owner` is staff: the customer surface admits the `customer` role and not
    theirs, so their session there resolves no tenant. Their unpinned bearer used
    to resolve their tenant anyway — `resolve_tenant` was asked without the
    surface, so the role admission and the `membership` rule never ran — and the
    two doors disagreed about one person on one host.
    """
    _, plaintext = issue_token(
        user=owner, tenant=None, name="unpinned", actor=actor_for(user=owner, tenant=tenant)
    )

    under_the_surface = authenticate_token(plaintext=plaintext, surface=two_faces)
    at_the_staff_host = authenticate_token(plaintext=plaintext)
    assert under_the_surface is not None and at_the_staff_host is not None
    assert (under_the_surface.tenant, at_the_staff_host.tenant) == (None, tenant)

    bearer = Client().get(
        "/api/v1/widgets/",
        HTTP_HOST=CUSTOMER_HOST,
        headers={"authorization": f"Bearer {plaintext}"},
    )
    session = Client()
    session.force_login(owner)
    by_session = session.get("/api/v1/widgets/", HTTP_HOST=CUSTOMER_HOST)
    assert (bearer.status_code, bearer.json().get("code")) == (
        by_session.status_code,
        by_session.json().get("code"),
    )


@pytest.mark.parametrize(
    ("who", "host", "admitted"),
    [
        ("customer", STAFF_HOST, False),
        ("customer", CUSTOMER_HOST, True),
        ("owner", CUSTOMER_HOST, False),
        ("owner", STAFF_HOST, True),
    ],
)
def test_a_pinned_token_passes_the_surfaces_admission_exactly_as_an_unpinned_one(
    two_faces: Surface,
    tenant: Tenant,
    owner: User,
    customer: User,
    who: str,
    host: str,
    admitted: bool,
) -> None:
    """A pin is a tenant, never a role: the surface still decides who counts at its host.

    A customer's token pinned to her tenant resolves nowhere at the staff host,
    as her session does there; an owner's resolves nowhere at the customer host.
    The pinned and the unpinned token of one person answer alike on each host.
    """
    person = {"customer": customer, "owner": owner}[who]
    surface = resolve_surface(host)
    assert surface is not None
    _, pinned = issue_token(
        user=person, tenant=tenant, name="pinned", actor=actor_for(user=person, tenant=tenant)
    )
    _, unpinned = issue_token(
        user=person, tenant=None, name="unpinned", actor=actor_for(user=person, tenant=tenant)
    )

    resolved = {
        name: authenticate_token(plaintext=plaintext, surface=surface)
        for name, plaintext in (("pinned", pinned), ("unpinned", unpinned))
    }
    expected = tenant if admitted else None
    assert {name: one.tenant if one else "refused" for name, one in resolved.items()} == {
        "pinned": expected,
        "unpinned": expected,
    }
