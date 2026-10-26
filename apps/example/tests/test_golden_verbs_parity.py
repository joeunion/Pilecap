"""The family verbs' one door-parity module, fenced per verb so each copy claims its pair."""

# golden: archive version move bulk history duplicate attach merge import begin
import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.example.models import Widget
from apps.example.services import archive_widget, restore_widget
from pilecap import Actor
from pilecap.accounts import User
from pilecap.tenancy import Organization, Tenant
from pilecap.testing import MCP_HEADERS, MCP_URL, REQUEST_FIXED_QUERIES, initialize, rpc, wire
from pilecap.testing import bearer as mint_bearer

DOOR_PAIR = ("rest", "mcp")

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"
JSON = "application/json"
#: Every route the copy serves on the collection, by `url_name`, and its path under the list's.
COLLECTION_ROUTES: tuple[tuple[str, str], ...] = (
    ("widget-list", ""),
    # golden: archive version move bulk history duplicate attach merge import end
    # golden: bulk history duplicate attach merge import begin
    ("widget-bulk", "bulk/"),
    # golden: bulk history duplicate attach merge import end
    # golden: import begin
    ("widget-create", ""),
    # golden: import end
    # golden: archive version move bulk history duplicate attach merge import begin
)
#: Every route the copy serves on one row, by `url_name`, and its path under the row's.
ROW_ROUTES: tuple[tuple[str, str], ...] = (
    ("widget-detail", ""),
    ("widget-archive", "archive/"),
    ("widget-restore", "restore/"),
    # golden: archive version move bulk history duplicate attach merge import end
    # golden: version move bulk history duplicate attach merge import begin
    ("widget-update", ""),
    ("widget_history-list", "history/"),
    # golden: version move bulk history duplicate attach merge import end
    # golden: move bulk history duplicate attach merge import begin
    ("widget-move", "move/"),
    # golden: move bulk history duplicate attach merge import end
    # golden: duplicate attach merge import begin
    ("widget-duplicate", "duplicate/"),
    # golden: duplicate attach merge import end
    # golden: merge import begin
    ("widget_merge-detail", "merge/"),
    ("widget-merge", "merge/"),
    # golden: merge import end
    # golden: archive version move bulk history duplicate attach merge import begin
)


def _items(response: Any) -> list[str]:
    assert response.status_code == 200, response.content
    return [row["id"] for row in json.loads(response.content)["items"]]


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    return mint_bearer(user=owner, tenant=tenant, name="verbs-parity")


@pytest.fixture
def widget(tenant: Tenant, root_org: Organization, owner: User) -> Widget:
    """One committed row, made by hand: the noun's create is the product's own business."""
    return Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="Twin")


async def _over_both(
    bearer: str, path: str, tool: str, arguments: dict[str, Any], method: str = "GET"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The same ask over HTTP and over JSON-RPC: the two bodies the doors put on the wire."""
    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        over_http = await client.request(method, path, headers={**bearer_header, "accept": JSON})
        assert over_http.status_code == 200, over_http.text
        headers = {**MCP_HEADERS, **bearer_header}
        await initialize(client, headers, "verbs-parity")
        called = await client.post(
            MCP_URL,
            headers=headers,
            json=rpc("tools/call", {"name": tool, "arguments": arguments}, 2),
        )
        assert called.status_code == 200, called.text
    answered = called.json()
    assert "error" not in answered, answered
    assert not answered["result"].get("isError"), answered
    rest: dict[str, Any] = over_http.json()
    mcp: dict[str, Any] = answered["result"]["structuredContent"]
    return rest, mcp


def test_every_route_the_adoption_serves_is_where_its_name_says(widget: Widget) -> None:
    for name, tail in COLLECTION_ROUTES:
        assert reverse(f"api:{name}") == f"{WIDGETS_URL}{tail}"
    for name, tail in ROW_ROUTES:
        at = reverse(f"api:{name}", kwargs={"widget_id": widget.pk})
        assert at == f"{WIDGETS_URL}{widget.pk}/{tail}"


def test_the_list_reads_in_a_fixed_number_of_queries(
    api: Client,
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    django_assert_num_queries: Any,
) -> None:
    for index in range(5):
        Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name=f"w{index}")
    api.force_login(owner)
    with django_assert_num_queries(REQUEST_FIXED_QUERIES + 1):
        assert len(_items(api.get(WIDGETS_URL))) == 5


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_describe_a_widget_with_one_key_set(
    bearer: str, widget: Widget
) -> None:
    rest, mcp = await _over_both(
        bearer, f"{WIDGETS_URL}{widget.pk}/", "get_widget", {"widget_id": str(widget.pk)}
    )
    assert set(mcp) == set(rest), (sorted(set(mcp) - set(rest)), sorted(set(rest) - set(mcp)))
    assert mcp["id"] == rest["id"] == str(widget.pk)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_page_the_list_alike(bearer: str, widget: Widget) -> None:
    rest, mcp = await _over_both(bearer, WIDGETS_URL, "list_widgets", {})
    assert set(mcp) == set(rest)
    assert [row["id"] for row in mcp["items"]] == [row["id"] for row in rest["items"]]
    assert set(mcp["items"][0]) == set(rest["items"][0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_archive_alike(
    bearer: str, tenant: Tenant, root_org: Organization, owner: User, widget: Widget
) -> None:
    other = await Widget.objects.acreate(
        tenant=tenant, organization=root_org, owner=owner, name="Other"
    )
    rest, mcp = await _over_both(
        bearer,
        f"{WIDGETS_URL}{widget.pk}/archive/",
        "archive_widget",
        {"widget_id": str(other.pk)},
        method="POST",
    )
    assert set(mcp) == set(rest)
    assert rest["archived_at"] is not None and mcp["archived_at"] is not None


# golden: archive version move bulk history duplicate attach merge import end
# golden: version move bulk history duplicate attach merge import begin
def test_the_history_list_reads_in_a_fixed_number_of_queries(
    api: Client,
    tenant: Tenant,
    admin_actor: Actor,
    owner: User,
    widget: Widget,
    django_assert_num_queries: Any,
) -> None:
    for _ in range(2):
        archive_widget(tenant=tenant, actor=admin_actor, widget=widget)
        restore_widget(tenant=tenant, actor=admin_actor, widget=widget)
    api.force_login(owner)
    with django_assert_num_queries(REQUEST_FIXED_QUERIES + 2):
        answered = api.get(f"{WIDGETS_URL}{widget.pk}/history/")
    assert answered.status_code == 200, answered.content
    assert len(json.loads(answered.content)["items"]) == 4


@pytest.fixture
def trail(tenant: Tenant, admin_actor: Actor, widget: Widget) -> Widget:
    """The row archived and restored: two entries on its history for both doors to page."""
    archived = archive_widget(tenant=tenant, actor=admin_actor, widget=widget)
    return restore_widget(tenant=tenant, actor=admin_actor, widget=archived)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_page_the_history_alike(bearer: str, trail: Widget) -> None:
    rest, mcp = await _over_both(
        bearer,
        f"{WIDGETS_URL}{trail.pk}/history/",
        "list_widget_history",
        {"widget_id": str(trail.pk)},
    )
    assert set(mcp) == set(rest)
    assert len(rest["items"]) == 2
    assert mcp["items"] == rest["items"]


# golden: version move bulk history duplicate attach merge import end
