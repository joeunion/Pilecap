"""`membership_for` reads the memberships the actor already caches.

Every "is this person a member here" predicate (`_is_member` in comms, the
example, files, tags, notes, exports, imports, workflows) calls
`core.authz.membership_for`, and a page's `allowed_acts` asks the predicate
once per ROW. It read the membership table on every call, so a list's
statements grew with its rows. It reads the actor's own memo now — the same
raw rows `effective_permissions` caches (`_memo_box`) — so a page costs the
same at 5 rows as at 50.

Measured through the real path: `with_allowed_acts` over a page of widgets
whose `widget.approve` key is, for this test only, a member predicate — the
shape comms' recipients and files' documents carry — at 5, 20 and 50 rows,
each with a FRESH actor so every count starts cold.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.authz import membership_for, reset_policies
from apps.core.models import Organization, Tenant
from apps.core.verbs import with_allowed_acts
from apps.example import policies as example_policies
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db


def _is_member(actor: Actor, obj: Any = None) -> bool:
    """The member predicate every app's `_is_member` is: one `membership_for` per call."""
    return membership_for(actor) is not None


@pytest.fixture
def member_predicate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(example_policies.POLICIES, "widget.approve", _is_member)
    reset_policies()
    yield
    monkeypatch.undo()
    reset_policies()


def _page_statements(tenant: Tenant, owner: User, root: Organization, rows: int) -> int:
    writer = actor_for(user=owner, tenant=tenant, org=root)
    for n in range(rows - Widget.objects.for_tenant(tenant).count()):
        create_widget(tenant=tenant, actor=writer, name=f"crate {rows}-{n}")
    page = list(Widget.objects.for_tenant(tenant).select_related("organization", "owner")[:rows])
    reader = actor_for(user=owner, tenant=tenant, org=root)  # a fresh actor: a cold memo
    with CaptureQueriesContext(connection) as captured:
        with_allowed_acts(page, reader)
    assert all("approve" in row.allowed_acts for row in page)  # type: ignore[attr-defined]
    return len(captured.captured_queries)


@pytest.mark.usefixtures("member_predicate")
def test_a_page_of_acts_costs_the_same_at_5_20_and_50_rows(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    counts = [_page_statements(tenant, owner, root_org, rows) for rows in (5, 20, 50)]
    assert counts[0] == counts[1] == counts[2], counts


def test_membership_for_reads_the_table_once_per_actor(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    actor = actor_for(user=owner, tenant=tenant, org=root_org)
    with CaptureQueriesContext(connection) as captured:
        first = [membership_for(actor) for _ in range(10)]
    assert len(captured.captured_queries) == 1, captured.captured_queries
    assert all(found is not None and found == first[0] for found in first)
    # The one invalidation is the actor's own.
    actor.forget_permissions()
    with CaptureQueriesContext(connection) as again:
        membership_for(actor)
    assert len(again.captured_queries) == 1
