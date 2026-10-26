"""Reads are permissions: reach before capability, and both doors agree (ADR core-27)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.test import Client

from apps.example.api import widget_stats
from apps.example.models import Widget, WidgetEntry, WidgetPolicy
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget,
    list_widget_entries,
    list_widget_policies,
    list_widgets,
)
from apps.example.services import create_widget, create_widget_policy, record_widget_entry
from pilecap import Actor, Forbidden, NotFound, require
from pilecap.accounts import User, create_user
from pilecap.tenancy import (
    Grant,
    Membership,
    Organization,
    Tenant,
    add_membership,
    create_organization,
    root_organization,
)
from pilecap.testing import actor_for, refusal_sentence, system_actor

pytestmark = pytest.mark.django_db

JSON = "application/json"
PASSWORD = "reads-ask-pass-1234"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
LIST_URL = "/api/v1/widgets/"

# --- the world ----------------------------------------------------------------


@dataclass(frozen=True)
class Reads:
    """`root -> a -> a1` and a sibling `b`, with one of each row in each branch."""

    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    b: Organization
    reader: User
    reader_membership: Membership
    inside_widget: Widget
    outside_widget: Widget
    inside_policy: WidgetPolicy
    inside_entry: WidgetEntry

    def actor(self) -> Actor:
        """A fresh actor at A — fresh because the memo's TTL is the instance."""
        return actor_for(user=self.reader, tenant=self.tenant, org=self.a)


@pytest.fixture
def reads(tenant: Tenant, owner: User) -> Reads:
    root = root_organization(tenant=tenant)
    system = system_actor(tenant=tenant)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=system)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=system)
    b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=system)

    reader = create_user(email="reader@example.com", password=PASSWORD)
    reader_membership = add_membership(
        user=reader,
        tenant=tenant,
        organization=a,
        role=Membership.Role.MEMBER,
        is_default=True,
        actor=system,
    )
    resident = create_user(email="resident@example.com", password=PASSWORD)
    add_membership(
        user=resident, tenant=tenant, organization=a1, role=Membership.Role.MEMBER, actor=system
    )
    neighbour = create_user(email="neighbour@example.com", password=PASSWORD)
    add_membership(
        user=neighbour, tenant=tenant, organization=b, role=Membership.Role.MEMBER, actor=system
    )

    inside_actor = actor_for(user=resident, tenant=tenant, org=a1)
    outside_actor = actor_for(user=neighbour, tenant=tenant, org=b)
    inside_widget = create_widget(tenant=tenant, actor=inside_actor, name="Inside")
    outside_widget = create_widget(tenant=tenant, actor=outside_actor, name="Outside")
    inside_policy = create_widget_policy(
        tenant=tenant, actor=system_actor(tenant, a1), name="Inside policy", body="{}"
    )
    inside_entry = record_widget_entry(
        tenant=tenant, actor=inside_actor, widget=inside_widget, kind="note", note="inside"
    )
    return Reads(
        tenant=tenant,
        root=root,
        a=a,
        a1=a1,
        b=b,
        reader=reader,
        reader_membership=reader_membership,
        inside_widget=inside_widget,
        outside_widget=outside_widget,
        inside_policy=inside_policy,
        inside_entry=inside_entry,
    )


def withhold(membership: Membership, permission: str) -> Grant:
    """A raw `withhold` row. Legal until P4 lands the hand-out services."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- the grammar, at the selector ---------------------------------------------


def _list(kind: str) -> Callable[..., Any]:
    # Typed: the three selectors do not share one signature.
    lists: dict[str, Callable[..., Any]] = {
        "widget": list_widgets,
        "widget_policy": list_widget_policies,
        "widget_entry": list_widget_entries,
    }
    return lists[kind]


@pytest.mark.parametrize("kind", ["widget", "widget_policy", "widget_entry"])
def test_a_list_without_the_key_is_forbidden_and_says_the_keys_own_sentence(
    reads: Reads, kind: str
) -> None:
    """A list has no row to hide, so the only honest answers are the page and 403."""
    key = f"{kind}.read"
    withhold(reads.reader_membership, key)

    with pytest.raises(Forbidden) as refused:
        _list(kind)(tenant=reads.tenant, org=reads.a, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence(key)

    Grant.objects.filter(membership=reads.reader_membership, permission=key).delete()
    assert _list(kind)(tenant=reads.tenant, org=reads.a, actor=reads.actor()) is not None


def test_a_widget_outside_the_subtree_is_not_found_and_inside_without_the_key_is_forbidden(
    reads: Reads,
) -> None:
    """Reach before capability, asserted by the two exception TYPES."""
    withhold(reads.reader_membership, "widget.read")

    with pytest.raises(NotFound):
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.outside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        )

    with pytest.raises(Forbidden) as refused:
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.inside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        )
    assert str(refused.value.args[0]) == refusal_sentence("widget.read")

    Grant.objects.filter(membership=reads.reader_membership, permission="widget.read").delete()
    assert (
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.inside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        ).pk
        == reads.inside_widget.pk
    )
    with pytest.raises(NotFound):
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.outside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        )


def test_the_governing_policy_asks_at_the_hat_and_not_at_the_ancestor(reads: Reads) -> None:
    """The one `get_` in this app that asks with `obj=None`, and why it must."""
    system = system_actor(reads.tenant, reads.a)
    above = create_widget_policy(tenant=reads.tenant, actor=system, name="At A", body="{}")

    at_a1 = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a1)
    resolved = get_governing_widget_policy(tenant=reads.tenant, org=reads.a1, actor=at_a1)
    assert resolved.pk == reads.inside_policy.pk

    # The row an ANCESTOR owns, resolved by the same call from a node that owns nothing.
    at_b = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a)
    assert get_governing_widget_policy(tenant=reads.tenant, org=reads.a, actor=at_b).pk == above.pk

    withhold(reads.reader_membership, "widget_policy.read")
    with pytest.raises(Forbidden) as refused:
        get_governing_widget_policy(
            tenant=reads.tenant,
            org=reads.a1,
            actor=actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a1),
        )
    assert str(refused.value.args[0]) == refusal_sentence("widget_policy.read")


def test_the_system_actor_reads_everything_the_scope_shows(reads: Reads) -> None:
    """`system` passes at step 1, so the onboarding activities are untouched."""
    for kind in ("widget", "widget_policy", "widget_entry"):
        withhold(reads.reader_membership, f"{kind}.read")
    system = system_actor(reads.tenant, reads.a1)
    assert list_widgets(tenant=reads.tenant, org=reads.a1, actor=system).exists()
    assert list_widget_policies(tenant=reads.tenant, org=reads.a1, actor=system).exists()
    assert list_widget_entries(tenant=reads.tenant, org=reads.a1, actor=system).exists()
    assert (
        get_widget(
            tenant=reads.tenant, widget_id=reads.inside_widget.pk, org=reads.a1, actor=system
        ).pk
        == reads.inside_widget.pk
    )


def test_widget_stats_asks_widget_read(reads: Reads) -> None:
    """The aggregate is covered by the read key of the kind it counts."""
    withhold(reads.reader_membership, "widget.read")
    with pytest.raises(Forbidden) as refused:
        widget_stats(tenant=reads.tenant, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence("widget.read")


# --- the flat product observes nothing ----------------------------------------


def test_the_plain_member_still_reads_everything(api: Client, reads: Reads) -> None:
    """Principle 13: a product that customised nothing sees the answers it saw."""
    api.force_login(reads.reader)
    for url in (
        LIST_URL,
        f"{LIST_URL}stats/",
        f"{LIST_URL}policies/",
        f"{LIST_URL}entries/",
    ):
        response = api.get(url, headers={"X-Org": reads.a.slug})
        assert response.status_code == 200, (url, response.content)


# --- a write door pays the read once ------------------------------------------


def test_a_write_door_pays_the_read_once(
    api: Client, reads: Reads, django_assert_num_queries: Any
) -> None:
    """+3 and not +6: the memo answers the second `require` for free."""
    owner_of_it = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a)
    mine = create_widget(tenant=reads.tenant, actor=owner_of_it, name="Mine")

    # A FRESH actor: the memo's TTL is the instance.
    acting = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a)
    with django_assert_num_queries(READ_SEAM_QUERIES):
        widget = get_widget(tenant=reads.tenant, widget_id=mine.pk, org=reads.a, actor=acting)
    with django_assert_num_queries(0):
        require(acting, "widget.update", widget)

    api.force_login(reads.reader)
    response = api.patch(
        f"{LIST_URL}{mine.pk}/",
        data=json.dumps({"name": "Renamed", "version": mine.version}),
        content_type=JSON,
        headers={"X-Org": reads.a.slug},
    )
    assert response.status_code == 200, response.content
    assert response.json()["name"] == "Renamed"


# The scoped fetch, plus the three statements an actor's first resolution costs.
READ_SEAM_QUERIES = 4
