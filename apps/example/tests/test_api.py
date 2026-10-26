"""The widget API, end to end."""

# golden: noun begin
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

from apps.example.models import Widget
from apps.example.services import (
    create_widget,
)
from pilecap import Actor, AuditEntry
from pilecap.accounts import User, issue_token
from pilecap.tenancy import Membership, Tenant, add_membership, root_organization
from pilecap.testing import (
    MAX_LIMIT,
    REQUEST_FIXED_QUERIES,
    actor_for,
    system_actor,
)

# golden: noun end
# isort: split
# golden: workflow onboard begin
from pilecap.testing import WorkflowRun, finish_run
from pilecap.workflows import workflow_id

# golden: workflow onboard end
# isort: split
# golden: policy begin
from apps.example.services import create_widget_policy

# golden: policy end
# isort: split
# golden: child entry begin
from apps.example.services import record_widget_entry

# golden: child entry end
# golden: noun begin
pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
JSON = "application/json"

# The fixed request cost plus the page; measured flat at 5, 10 and 50 rows.
LIST_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 1


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def acting_in(user: User, tenant: Tenant) -> Actor:
    """The same person, acting in a tenant they may not yet belong to."""
    if not Membership.objects.filter(user=user, tenant=tenant).exists():
        add_membership(user=user, tenant=tenant, actor=system_actor(tenant=tenant))
    # The hat is the tenant's root: this helper is the flat case.
    return actor_for(user=user, tenant=tenant, org=root_organization(tenant=tenant))


def test_list_url_is_where_the_router_put_it() -> None:
    assert reverse("api:widget-list") == LIST_URL


#: Each other door the noun mounts, by its route name, and its path under the list URL.
DOORS = {
    "widget-create": "",
    "widget-detail": "{id}/",
    "widget-update": "{id}/",
    "widget-delete": "{id}/",
    "widget-archive": "{id}/archive/",
    "widget-restore": "{id}/restore/",
    "widget_history-list": "{id}/history/",
}


@pytest.mark.parametrize(("url_name", "tail"), DOORS.items())
def test_every_door_is_where_the_router_put_it(url_name: str, tail: str) -> None:
    """Each route reverses, by the name a client and rule 3 know it by, to the path tests call."""
    widget_id = uuid4()
    kwargs = {"widget_id": widget_id} if "{id}" in tail else {}
    assert reverse(f"api:{url_name}", kwargs=kwargs) == LIST_URL + tail.format(id=widget_id)


# golden: noun end
# golden: verb touch begin
def test_a_touch_answers_the_widget_seen_now(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Seen")
    api.force_login(owner)
    touched = api.post(reverse("api:widget-touch", kwargs={"widget_id": widget.pk}))
    assert touched.status_code == 200, touched.content
    assert _body(touched)["id"] == str(widget.pk)
    assert Widget.objects.for_tenant(tenant).get(pk=widget.pk).updated_at > widget.updated_at


# golden: verb touch end
# golden: enum status begin
def test_status_moves_by_its_own_press_and_never_by_a_patch(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Staged")
    api.force_login(owner)
    patched = api.patch(
        f"{LIST_URL}{widget.pk}/",
        data=json.dumps({"status": "active", "version": widget.version}),
        content_type=JSON,
    )
    assert patched.status_code == 422, patched.content
    assert "status" in _body(patched)["errors"]
    url = reverse("api:widget-transition", kwargs={"widget_id": widget.pk})
    moved = api.post(url, data=json.dumps({"status": "active"}), content_type=JSON)
    assert moved.status_code == 200, moved.content
    assert _body(moved)["status"] == "active"
    again = api.post(url, data=json.dumps({"status": "active"}), content_type=JSON)
    assert again.status_code == 409, again.content
    assert _body(again)["code"] == "conflict"


# golden: enum status end
# golden: stat count begin
# `/stats/`: the fixed request cost plus the two COUNTs its basis is built from (ADR core-7).
STATS_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 2


def test_stats_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    django_assert_num_queries: Any,
    owner_actor: Actor,
) -> None:
    """The measured number costs two COUNTs and no more, at any number of rows."""
    for index in range(10):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Counted {index}")
    api.force_login(owner)

    with django_assert_num_queries(STATS_QUERY_BUDGET):
        response = api.get(reverse("api:widget_stats-detail"))

    assert response.status_code == 200, response.content
    body = _body(response)
    assert body["count"]["value"] == "10"
    assert body["count"]["basis"]["inputs"] == {"live": "10", "archived": "0"}


def test_the_stats_basis_moves_with_the_rows_it_measures(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The inputs are read off the table, not remembered. Archive one and watch."""
    first = create_widget(tenant=tenant, actor=owner_actor, name="First")
    create_widget(tenant=tenant, actor=owner_actor, name="Second")
    api.force_login(owner)
    archived = api.post(reverse("api:widget-archive", kwargs={"widget_id": first.pk}))
    assert archived.status_code == 200, archived.content

    body = _body(api.get(reverse("api:widget_stats-detail")))

    assert body["count"]["basis"]["inputs"] == {"live": "1", "archived": "1"}
    assert body["count"]["value"] == "2"


# golden: stat count end
# golden: noun begin
def test_anonymous_cannot_list(api: Client) -> None:
    assert api.get(LIST_URL).status_code == 401


def test_anonymous_cannot_create(api: Client) -> None:
    response = api.post(LIST_URL, data=json.dumps({"name": "nope"}), content_type=JSON)
    assert response.status_code == 401


def test_authenticated_create_returns_201_and_owns_the_row(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    response = api.post(
        LIST_URL,
        data=json.dumps({"name": "First widget", "notes": "hello"}),
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["name"] == "First widget"
    assert body["owner_email"] == owner.email
    widget = Widget.objects.get(pk=body["id"])
    assert widget.owner_id == owner.pk
    assert widget.tenant_id == tenant.pk
    assert widget.notes == "hello"


def test_the_list_is_paginated(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The envelope, and the whole of it (ADR core-18)."""
    for index in range(3):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")
    api.force_login(owner)
    response = api.get(LIST_URL)
    assert response.status_code == 200
    body = _body(response)
    # `allowed_acts` is the LIST's own acts (`create` where the actor may).
    assert set(body) == {"items", "has_more", "next_cursor", "count", "allowed_acts"}
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["count"] is None
    assert len(body["items"]) == 3


def test_the_count_is_null_until_it_is_asked_for(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """`null` is "not counted", which is a different fact from zero."""
    for index in range(3):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")
    api.force_login(owner)
    assert _body(api.get(LIST_URL))["count"] is None
    assert _body(api.get(LIST_URL, {"include_count": "true"}))["count"] == 3


def test_the_limit_is_the_one_on_the_class(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    for index in range(3):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")
    api.force_login(owner)
    body = _body(api.get(LIST_URL, {"limit": 2}))
    assert len(body["items"]) == 2
    assert body["has_more"] is True
    assert body["next_cursor"] is not None


def test_another_tenants_rows_are_absent_even_when_the_user_owns_them(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    mine = create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    theirs = create_widget(tenant=other_tenant, actor=acting_in(owner, other_tenant), name="Theirs")
    api.force_login(owner)
    body = _body(api.get(LIST_URL))
    returned = {row["id"] for row in body["items"]}
    assert returned == {str(mine.pk)}
    assert str(theirs.pk) not in returned


def test_the_header_switches_tenant(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    add_membership(user=owner, tenant=other_tenant, actor=system_actor(tenant=other_tenant))
    create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    theirs = create_widget(tenant=other_tenant, actor=acting_in(owner, other_tenant), name="Theirs")
    api.force_login(owner)
    body = _body(api.get(LIST_URL, headers={"x-tenant": other_tenant.slug}))
    assert {row["id"] for row in body["items"]} == {str(theirs.pk)}


def test_a_user_with_no_membership_sees_nothing(
    api: Client, tenant: Tenant, owner: User, nomad: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Not yours")
    api.force_login(nomad)
    response = api.get(LIST_URL)
    # No membership resolves no tenant, so the door refuses before the selector.
    assert response.status_code == 403, response.content
    assert "Not yours" not in response.content.decode()


def test_a_superuser_with_no_membership_sees_nothing(
    api: Client, tenant: Tenant, owner: User, root: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Not yours either")
    api.force_login(root)
    response = api.get(LIST_URL)
    # No superuser exemption: the refusal is the same one a nobody gets.
    assert response.status_code == 403, response.content
    assert "Not yours either" not in response.content.decode()


def test_a_user_with_no_membership_cannot_create(api: Client, nomad: User) -> None:
    api.force_login(nomad)
    response = api.post(LIST_URL, data=json.dumps({"name": "Homeless"}), content_type=JSON)
    assert response.status_code == 403
    assert Widget.objects.count() == 0


def test_detail_of_another_tenants_widget_is_a_404(
    api: Client, other_tenant: Tenant, owner: User, stranger: User, stranger_actor: Actor
) -> None:
    theirs = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    api.force_login(owner)
    assert api.get(f"{LIST_URL}{theirs.pk}/").status_code == 404


def test_update_goes_through_the_service(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Before")
    api.force_login(owner)
    response = api.patch(
        f"{LIST_URL}{widget.pk}/",
        data=json.dumps({"name": "After", "version": widget.version}),
        content_type=JSON,
    )
    assert response.status_code == 200, response.content
    widget.refresh_from_db()
    assert widget.name == "After"


def test_a_duplicate_name_is_a_400_with_the_field_errors(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The service raises `ValidationError`; the client must see JSON, not HTML."""
    create_widget(tenant=tenant, actor=owner_actor, name="Only one")
    api.force_login(owner)
    response = api.post(LIST_URL, data=json.dumps({"name": "Only one"}), content_type=JSON)
    assert response.status_code == 400, response.content
    assert response.headers["content-type"].startswith(JSON)
    body = _body(response)
    assert body["detail"]
    assert body["errors"]
    assert Widget.objects.count() == 1


def test_delete_removes_the_row(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Doomed")
    api.force_login(owner)
    assert api.delete(f"{LIST_URL}{widget.pk}/").status_code == 204
    assert Widget.objects.count() == 0


def test_a_bearer_token_is_the_machine_door_into_the_same_rows(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    mine = create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    create_widget(tenant=other_tenant, actor=acting_in(owner, other_tenant), name="Theirs")
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    body = _body(api.get(LIST_URL, headers={"authorization": f"Bearer {plaintext}"}))
    assert {row["id"] for row in body["items"]} == {str(mine.pk)}


def test_a_pinned_token_with_a_mismatched_tenant_header_is_refused(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The machine door refuses `X-Tenant`, exactly as the human one does."""
    add_membership(user=owner, tenant=other_tenant, actor=system_actor(tenant=other_tenant))
    create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="pinned", actor=actor_for(user=owner, tenant=tenant)
    )
    response = api.get(
        LIST_URL,
        headers={"authorization": f"Bearer {plaintext}", "x-tenant": other_tenant.slug},
    )
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "addressing_header_not_honoured"


def test_a_session_with_a_tenant_header_it_does_not_belong_to_is_refused(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The same request on the human door: refused, and never the default's rows."""
    create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    api.force_login(owner)
    response = api.get(LIST_URL, headers={"x-tenant": other_tenant.slug})
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "addressing_header_not_honoured"


def test_a_bad_token_is_refused(api: Client, tenant: Tenant, owner: User) -> None:
    assert api.get(LIST_URL, headers={"authorization": "Bearer nonsense"}).status_code == 401


# The same budget at five rows and at fifty: no per-row field costs a query.
@pytest.mark.parametrize("rows", [5, 10, 50])
def test_list_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    django_assert_num_queries: Any,
    owner_actor: Actor,
    rows: int,
) -> None:
    for index in range(rows):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")
    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        response = api.get(LIST_URL)
    assert response.status_code == 200
    assert len(_body(response)["items"]) == rows
    assert all(item["allowed_acts"] for item in _body(response)["items"])


def test_the_openapi_document_and_the_docs_page_are_served(api: Client) -> None:
    schema = api.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    assert "/api/v1/widgets/" in _body(schema)["paths"]
    assert api.get("/api/v1/docs").status_code == 200


# golden: noun end


# House rule 3's allow-list, seen from the published contract.


# golden: noun begin
def test_every_route_in_the_document_declares_security(api: Client) -> None:
    from pilecap.testing import unauthenticated_operation_ids

    allowed = unauthenticated_operation_ids()
    document = _body(api.get("/api/v1/openapi.json"))
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            if operation.get("operationId") in allowed:
                continue
            assert operation.get("security"), f"{method.upper()} {path} declares no auth"


def test_the_document_declares_no_other_open_route(api: Client) -> None:
    """An equality, so a second `auth=None` anywhere in the tree fails here."""
    from pilecap.testing import unauthenticated_operation_ids

    document = _body(api.get("/api/v1/openapi.json"))
    open_routes = {
        operation["operationId"]
        for methods in document["paths"].values()
        for operation in methods.values()
        if not operation.get("security")
    }
    assert open_routes == unauthenticated_operation_ids()


# golden: noun end


# --- Authorization, through the door ----------------------------------------


def test_a_member_cannot_delete_another_members_widget(
    api: Client, tenant: Tenant, owner_actor: Actor, member: User
) -> None:
    """403, and the row is still there. The refusal comes from the service."""
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Not yours")
    api.force_login(member)

    response = api.delete(f"{LIST_URL}{theirs.pk}/")
    assert response.status_code == 403, response.content
    assert _body(response)["code"] == "forbidden"
    assert Widget.objects.filter(pk=theirs.pk).exists()


# golden: noun begin
def test_an_admin_can_delete_another_members_widget(
    api: Client, tenant: Tenant, owner_actor: Actor, admin_member: User
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Moderated")
    api.force_login(admin_member)

    assert api.delete(f"{LIST_URL}{theirs.pk}/").status_code == 204
    assert not Widget.objects.filter(pk=theirs.pk).exists()


def test_a_member_can_delete_their_own(api: Client, tenant: Tenant, member: User) -> None:
    mine = create_widget(
        tenant=tenant,
        actor=actor_for(user=member, tenant=tenant, org=root_organization(tenant=tenant)),
        name="Mine",
    )
    api.force_login(member)
    assert api.delete(f"{LIST_URL}{mine.pk}/").status_code == 204


# golden: noun end


def test_a_member_cannot_rename_another_members_widget(
    api: Client, tenant: Tenant, owner_actor: Actor, member: User
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Before")
    api.force_login(member)

    response = api.patch(
        f"{LIST_URL}{theirs.pk}/",
        data=json.dumps({"name": "After", "version": theirs.version}),
        content_type=JSON,
    )
    assert response.status_code == 403, response.content
    theirs.refresh_from_db()
    assert theirs.name == "Before"


def test_a_write_through_the_door_leaves_an_audit_row_naming_the_door(
    api: Client, tenant: Tenant, owner: User
) -> None:
    AuditEntry.objects.all().delete()
    api.force_login(owner)
    response = api.post(LIST_URL, data=json.dumps({"name": "Audited"}), content_type=JSON)
    assert response.status_code == 201, response.content

    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget")
    assert entry.door == "rest"
    assert entry.actor_kind == "human"
    assert entry.actor_user_id == owner.pk
    assert entry.request_id
    assert entry.correlation_id
    assert str(entry.object_id) == _body(response)["id"]


def test_the_machine_door_records_the_token_it_came_in_on(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Only the token tells a person from an integration they installed."""
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    AuditEntry.objects.all().delete()

    response = api.post(
        LIST_URL,
        data=json.dumps({"name": "By the robot"}),
        content_type=JSON,
        headers={"authorization": f"Bearer {plaintext}"},
    )
    assert response.status_code == 201, response.content

    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget")
    assert entry.actor_kind == "agent"
    assert entry.actor_user_id == owner.pk
    assert entry.actor_token_id == token.pk


# --- The list standard ------------------------------------------------------


# golden: noun begin
def test_the_filter_narrows_by_name(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Blue widget")
    create_widget(tenant=tenant, actor=owner_actor, name="Red widget")
    api.force_login(owner)

    body = _body(api.get(LIST_URL, {"name": "blue"}))
    assert [row["name"] for row in body["items"]] == ["Blue widget"]
    assert len(body["items"]) == 1


def test_q_searches_the_fields_the_route_named(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Alpha", notes="about turbines")
    create_widget(tenant=tenant, actor=owner_actor, name="Beta", notes="about kettles")
    api.force_login(owner)

    body = _body(api.get(LIST_URL, {"q": "turbines"}))
    assert [row["name"] for row in body["items"]] == ["Alpha"]


def test_ordering_is_an_allow_list_and_says_what_it_allows(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """`?ordering=` never reaches `.order_by()` unchecked: an unknown column is refused."""
    create_widget(tenant=tenant, actor=owner_actor, name="Second")
    create_widget(tenant=tenant, actor=owner_actor, name="First")
    api.force_login(owner)

    ascending = _body(api.get(LIST_URL, {"ordering": "name"}))
    assert [row["name"] for row in ascending["items"]] == ["First", "Second"]

    descending = _body(api.get(LIST_URL, {"ordering": "-name"}))
    assert [row["name"] for row in descending["items"]] == ["Second", "First"]

    refused = api.get(LIST_URL, {"ordering": "owner__password"})
    assert refused.status_code == 400
    body = _body(refused)
    assert body["code"] == "invalid"
    assert "name" in body["errors"]["ordering"][0]


def test_the_default_order_is_newest_first(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Older")
    newer = create_widget(tenant=tenant, actor=owner_actor, name="Newer")
    api.force_login(owner)

    body = _body(api.get(LIST_URL))
    assert body["items"][0]["id"] == str(newer.pk)


def test_due_date_orders_both_ways_with_the_undated_last(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """`?ordering=due_at` and `-due_at` sort by due date; undated widgets come last."""
    from datetime import UTC, datetime

    create_widget(tenant=tenant, actor=owner_actor, name="Undated")
    for name, month in (("Middle", 11), ("Soonest", 10), ("Latest", 12)):
        create_widget(
            tenant=tenant,
            actor=owner_actor,
            name=name,
            due_at=datetime(2026, month, 15, tzinfo=UTC),
        )
    api.force_login(owner)

    def walked(ordering: str) -> list[str]:
        names: list[str] = []
        params: dict[str, Any] = {"ordering": ordering, "limit": 2}
        while True:
            page = _body(api.get(LIST_URL, params))
            names += [row["name"] for row in page["items"]]
            if not page["has_more"]:
                return names
            params["cursor"] = page["next_cursor"]

    assert walked("due_at") == ["Soonest", "Middle", "Latest", "Undated"]
    assert walked("-due_at") == ["Latest", "Middle", "Soonest", "Undated"]

    refused = api.get(LIST_URL, {"ordering": "due"})
    assert refused.status_code == 400
    assert "due_at" in _body(refused)["errors"]["ordering"][0]


def test_the_limit_has_a_ceiling(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Without a ceiling, `?limit=` is a slower way to ask for everything."""
    for index in range(5):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")
    api.force_login(owner)

    refused = api.get(LIST_URL, {"limit": 10_000})

    assert refused.status_code == 400, refused.content
    assert refused.json()["code"] == "invalid"
    assert "limit" in refused.json()["errors"]
    assert str(MAX_LIMIT) in refused.content.decode()

    # And the ceiling itself still holds for a request that asks within it.
    body = _body(api.get(LIST_URL, {"limit": MAX_LIMIT}))
    assert len(body["items"]) == 5


def test_the_list_url_carries_the_version(api: Client) -> None:
    """A breaking change is a `v2` beside `v1`, which needs `v1` in the path."""
    assert LIST_URL.startswith("/api/v1/")
    assert reverse("api:widget-list") == LIST_URL


# golden: noun end
# golden: workflow onboard begin


# --- Approval: the door that ends a wait -------------------------------------


def approve_url(widget: Widget) -> str:
    return f"{LIST_URL}{widget.pk}/approve/"


def onboarding_run(tenant: Tenant, widget: Widget) -> WorkflowRun:
    """The visibility row `create_widget` wrote, found by the id it derived."""
    return WorkflowRun.objects.for_tenant(tenant).get(
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk))
    )


def test_approve_url_is_where_the_router_put_it() -> None:
    assert reverse("api:widget-approve", args=["00000000-0000-0000-0000-000000000000"]) == (
        f"{LIST_URL}00000000-0000-0000-0000-000000000000/approve/"
    )


def test_anonymous_cannot_approve(api: Client, tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Guarded")
    assert api.post(approve_url(widget)).status_code == 401


def test_an_owner_approves_and_gets_the_row_back(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The product can end its own wait."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Waiting on a person")
    assert onboarding_run(tenant, widget).status == WorkflowRun.Status.RUNNING

    api.force_login(owner)
    response = api.post(approve_url(widget), content_type=JSON)

    assert response.status_code == 200, response.content
    assert _body(response)["id"] == str(widget.pk)


def test_approving_twice_while_the_run_is_going_is_not_a_conflict(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """A client that retried a request it never saw the answer to is not punished."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Approved twice")
    api.force_login(owner)

    first = api.post(approve_url(widget), content_type=JSON)
    second = api.post(approve_url(widget), content_type=JSON)

    assert (first.status_code, second.status_code) == (200, 200), second.content
    # And no second run: signalling starts nothing.
    assert (
        WorkflowRun.objects.for_tenant(tenant).filter(type="WidgetOnboardingWorkflow").count() == 1
    )


def test_approving_a_run_that_has_already_ended_is_a_409(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The other half: once the run is over, an approval is a `conflict`."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Too late")
    finish_run(
        tenant=tenant,
        workflow_id=onboarding_run(tenant, widget).workflow_id,
        status=WorkflowRun.Status.COMPLETED,
    )

    api.force_login(owner)
    response = api.post(approve_url(widget), content_type=JSON)

    assert response.status_code == 409, response.content
    assert _body(response)["code"] == "conflict"


def test_a_widget_with_no_run_at_all_is_a_404(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The honest answer when there is nothing to signal."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Runless")
    onboarding_run(tenant, widget).delete()

    api.force_login(owner)
    response = api.post(approve_url(widget), content_type=JSON)

    assert response.status_code == 404, response.content
    assert _body(response)["code"] == "not_found"


def test_a_stranger_tenants_widget_cannot_be_approved(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    """404, not 403: a refusal that distinguished them would confirm the row."""
    theirs = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    api.force_login(owner)
    response = api.post(approve_url(theirs), content_type=JSON)
    assert response.status_code == 404, response.content


def test_a_plain_member_may_not_approve(
    api: Client, tenant: Tenant, member: User, owner_actor: Actor
) -> None:
    """403 rather than 404: the member can see the row, they just may not do this."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Not theirs to approve")
    api.force_login(member)
    response = api.post(approve_url(widget), content_type=JSON)
    assert response.status_code == 403, response.content
    assert _body(response)["code"] == "forbidden"


def test_a_member_may_not_approve_even_their_own(
    api: Client, tenant: Tenant, member: User, member_actor: Actor
) -> None:
    """The rule approval exists for, said as a test: nobody approves their own."""
    widget = create_widget(tenant=tenant, actor=member_actor, name="Mine, unapproved")
    api.force_login(member)
    assert api.post(approve_url(widget), content_type=JSON).status_code == 403


def test_an_admin_may_approve_anybodys(
    api: Client, tenant: Tenant, admin_member: User, member_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=member_actor, name="Somebody else's")
    api.force_login(admin_member)
    assert api.post(approve_url(widget), content_type=JSON).status_code == 200


# golden: workflow onboard end
# golden: policy begin
# `/policies/`: the fixed request cost plus the page; `select_related` keeps the page one query.
POLICIES_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 1
# golden: policy end

# golden: child entry begin
# `/entries/`: the fixed request cost plus the page.
ENTRIES_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 1
# golden: child entry end


# golden: policy begin
def test_policies_list_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    django_assert_num_queries: Any,
    owner_actor: Actor,
) -> None:
    """One query for the page however many policies it holds — the `select_related`."""
    for index in range(10):
        create_widget_policy(tenant=tenant, actor=owner_actor, name=f"Policy {index}")
    api.force_login(owner)

    with django_assert_num_queries(POLICIES_QUERY_BUDGET):
        response = api.get(reverse("api:widget_policies-list"))

    assert response.status_code == 200, response.content
    assert len(_body(response)["items"]) == 10


def test_the_policy_routes_are_mounted_where_they_say() -> None:
    """The policy paths, pinned by name: house rule 3 reads the names a test proves."""
    policies = reverse("api:widget_policies-list")
    policy_id = "00000000-0000-0000-0000-000000000001"
    assert reverse("api:widget_policy-create") == policies
    assert reverse("api:governing_widget_policy-detail") == f"{policies}governing/"
    archive = reverse("api:widget_policy-archive", kwargs={"policy_id": policy_id})
    assert archive == f"{policies}{policy_id}/archive/"


# golden: policy end
# golden: child entry begin
def test_entries_list_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    django_assert_num_queries: Any,
    owner_actor: Actor,
) -> None:
    """The same pin on the ledger, for the same reason and against the same N+1."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Subject")
    for index in range(10):
        record_widget_entry(tenant=tenant, actor=owner_actor, widget=widget, note=f"line {index}")
    api.force_login(owner)

    with django_assert_num_queries(ENTRIES_QUERY_BUDGET):
        response = api.get(reverse("api:widget_entries-list"))

    assert response.status_code == 200, response.content
    assert len(_body(response)["items"]) == 10


def test_the_entry_routes_are_mounted_where_they_say() -> None:
    """The ledger paths, pinned by name: house rule 3 reads the names a test proves."""
    assert reverse("api:widget_entry-record") == reverse("api:widget_entries-list")


# golden: child entry end
# --- The due date over the human door -----------------------------------------


# golden: noun begin
# golden: field due_at begin
DUE_AT_WIRE = "2026-11-02T17:00:00Z"
LATER_DUE_AT_WIRE = "2026-12-01T09:30:00Z"


def test_due_at_is_created_patched_and_cleared_over_rest(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    created = api.post(
        LIST_URL, data=json.dumps({"name": "Due", "due_at": DUE_AT_WIRE}), content_type=JSON
    )
    assert created.status_code == 201, created.content
    body = _body(created)
    assert body["due_at"] == DUE_AT_WIRE

    changed = api.patch(
        f"{LIST_URL}{body['id']}/",
        data=json.dumps({"due_at": LATER_DUE_AT_WIRE, "version": body["version"]}),
        content_type=JSON,
    )
    assert changed.status_code == 200, changed.content
    assert _body(changed)["due_at"] == LATER_DUE_AT_WIRE

    cleared = api.patch(
        f"{LIST_URL}{body['id']}/",
        data=json.dumps({"clear_due_at": True, "version": _body(changed)["version"]}),
        content_type=JSON,
    )
    assert cleared.status_code == 200, cleared.content
    assert _body(cleared)["due_at"] is None
    assert Widget.objects.for_tenant(tenant).get(pk=body["id"]).due_at is None


# golden: field due_at end


def test_a_due_date_with_an_offset_is_answered_in_utc(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    created = api.post(
        LIST_URL, data=json.dumps({"name": "Due", "due_at": DUE_AT_WIRE}), content_type=JSON
    )
    body = _body(created)
    changed = api.patch(
        f"{LIST_URL}{body['id']}/",
        data=json.dumps({"due_at": "2026-12-01T09:30:00+01:00", "version": body["version"]}),
        content_type=JSON,
    )
    assert changed.status_code == 200, changed.content
    assert _body(changed)["due_at"] == "2026-12-01T08:30:00Z"


def test_the_list_filters_by_due_date_both_ways(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    from datetime import UTC, datetime

    early = create_widget(
        tenant=tenant, actor=owner_actor, name="Early", due_at=datetime(2026, 10, 15, tzinfo=UTC)
    )
    late = create_widget(
        tenant=tenant, actor=owner_actor, name="Late", due_at=datetime(2026, 12, 15, tzinfo=UTC)
    )
    create_widget(tenant=tenant, actor=owner_actor, name="Undated")
    api.force_login(owner)

    before = _body(api.get(LIST_URL, {"due_before": "2026-11-01T00:00:00Z"}))
    assert [item["id"] for item in before["items"]] == [str(early.pk)]
    after = _body(api.get(LIST_URL, {"due_after": "2026-11-01T00:00:00Z"}))
    assert [item["id"] for item in after["items"]] == [str(late.pk)]


@pytest.mark.parametrize("value", ["2026-11-02T17:00:00", "next tuesday"])
def test_a_naive_or_malformed_due_date_is_refused_naming_the_field(
    api: Client, tenant: Tenant, owner: User, value: str
) -> None:
    api.force_login(owner)
    created = api.post(
        LIST_URL, data=json.dumps({"name": "Due", "due_at": value}), content_type=JSON
    )
    assert created.status_code == 422, created.content
    assert _body(created)["code"] == "invalid_body"
    assert "due_at" in _body(created)["errors"]
    assert not Widget.objects.for_tenant(tenant).exists()

    listed = api.get(LIST_URL, {"due_before": value})
    assert listed.status_code == 400, listed.content
    assert _body(listed)["code"] == "invalid"
    assert "due_before" in _body(listed)["errors"]


# golden: noun end
