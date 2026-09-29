"""`allowed_acts` on a paginated list: every row's acts and the list's own, at a flat cost.

The seam both doors call is `cursor_page(..., actor=...)` — the REST door
through `ActsPagination`, an MCP twin by passing its actor. The pin is house
rule 5's: the statement count at 5 rows EQUALS the count at 50, and the number
is stated here, because `allows` memoizes the actor's collection per node and a
row loop that re-asked per row would be the N+1 this exists to refuse.

`Widget` is the listed noun because the acts are the VOCABULARY's — a planted
model outside the kind registry would answer no acts and prove nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.api.pagination import ActsPagination, cursor_page
from apps.core.models import Organization, Tenant
from apps.core.schemas import ActsOut, ActsPage, ListPage

pytestmark = pytest.mark.django_db

#: Measured, not guessed (the same at 5 and at 50): the page itself; the ONE
#: query that attaches every row's node (`verbs._attach_nodes`); the actor's
#: collection at that node — memberships, grants, role keys. The list's own
#: `create` asks at the hat with the memberships the actor already holds
#: (`membership_for` reads the actor's memo), so it costs none (6 -> 5). The
#: equality across page sizes is the claim; this is its size.
PAGE_WITH_ACTS_QUERIES = 5


def _widgets(tenant: Tenant, org: Organization, owner: User, n: int) -> Any:
    from apps.example.models import Widget

    Widget.objects.bulk_create(
        [Widget(tenant=tenant, organization=org, owner=owner, name=f"w{i:03}") for i in range(n)]
    )
    return Widget.objects.for_tenant(tenant).visible_to(org)


def _count(rows: Any, tenant: Tenant, actor: Actor, n: int) -> tuple[int, Any]:
    with CaptureQueriesContext(connection) as captured:
        page = cursor_page(rows, tenant=tenant, limit=n, actor=actor)
    return len(captured), page


@pytest.mark.parametrize("n", [5, 50])
def test_the_page_costs_the_same_at_5_and_at_50_rows(
    tenant: Tenant, root_org: Organization, owner: User, admin_actor: Actor, n: int
) -> None:
    rows = _widgets(tenant, root_org, owner, n)
    queries, page = _count(rows, tenant, admin_actor, n)

    assert len(page.items) == n
    assert queries == PAGE_WITH_ACTS_QUERIES, queries
    assert all("update" in row.allowed_acts for row in page.items)
    assert page.allowed_acts == ("create",)


def test_a_member_holds_the_rows_they_may_act_on_and_nobody_holds_none(
    tenant: Tenant, root_org: Organization, owner: User, member_actor: Actor
) -> None:
    from apps.core.actor import actor_for

    rows = _widgets(tenant, root_org, owner, 3)
    page = cursor_page(rows, tenant=tenant, limit=3, actor=member_actor)
    assert all("archive" not in row.allowed_acts for row in page.items)

    nobody = actor_for(user=None, tenant=tenant, org=root_org)
    page = cursor_page(rows, tenant=tenant, limit=3, actor=nobody)
    assert all(row.allowed_acts == () for row in page.items)
    assert page.allowed_acts == ()


def test_no_actor_leaves_the_page_as_it_was(
    tenant: Tenant, root_org: Organization, owner: User
) -> None:
    rows = _widgets(tenant, root_org, owner, 2)
    page = cursor_page(rows, tenant=tenant, limit=2)
    assert page.allowed_acts is None
    assert not any(hasattr(row, "allowed_acts") for row in page.items)


def test_the_envelope_and_the_item_publish_the_acts() -> None:
    assert issubclass(ActsPagination.Output, ActsPage)
    assert issubclass(ActsPage, ListPage)
    assert "allowed_acts" in ActsPage.model_fields
    assert "allowed_acts" in ActsOut.model_fields
