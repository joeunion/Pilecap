"""The widget API, end to end.

These are the tests every list endpoint in a product should have a copy of:
anonymous is refused, the shape is paginated, the rows are scoped to the acting
tenant, a second tenant's rows are absent, and the query count is pinned so an
N+1 shows up as a failure rather than a slow page.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.api.pagination import MAX_LIMIT
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership, root_organization
from apps.example.models import Widget
from apps.example.services import (
    create_widget,
    create_widget_policy,
    mark_widget_onboarded,
    record_widget_entry,
)
from apps.workflows.models import WorkflowRun
from apps.workflows.services import finish_run, workflow_id

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
JSON = "application/json"

# Measured, not guessed, at ten rows: the session row + the user row (session
# authentication) + 1 SAVEPOINT (ATOMIC_REQUESTS) + the membership lookup
# TenantMiddleware makes for the tenant + the membership lookup it makes for
# the acting ORG + COUNT + the page + 1 RELEASE SAVEPOINT.
#
# The eighth is the hat, and it is the standing per-request cost of the
# hierarchy: one indexed read of "which memberships does this person hold in
# this tenant", from which both the default hat and the `X-Org` check are
# answered. It is a fixed cost, not a growing one — that is what this test
# pins. `select_related("owner", "organization")` is what keeps the page at one
# query no matter how many rows come back; take either out and this is what
# fails.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
#
# **+3 since Phase R** (ADR core-27, rule 5): the selector asks
# ``widget.read`` at the acting hat, and resolution reads three tables —
# this person's memberships in the tenant, the grants on them, and the role
# deltas for the roles on the chain. It is paid ONCE per actor instance
# whatever the number of `require`s (the PR0 memo), so a route that asked
# twice would still be +3 and not +6.
#
# **+4 for `allowed_acts`**, through the family's page (`ActsPagination`,
# `core.verbs.with_allowed_acts`): ONE query attaching every row's node, and the
# actor's collection read again — three reads — because the paginator resolves
# its own actor from the request rather than reusing the route's, so the memo
# the route's `widget.read` filled is not the one the acts ask. The seam's
# page-level `create` shares that second memo — and since `membership_for`
# reads the actor's memo too, the list's `create` predicate (`_is_member`) costs
# no read of its own (14 → 13). A fixed cost per request, never per row, which
# is the property this pin exists for.
LIST_QUERY_BUDGET = 13


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def acting_in(user: User, tenant: Tenant) -> Actor:
    """The same person, acting in a tenant they may not yet belong to.

    Several tests need a row in a *second* tenant to prove it stays invisible.
    Since a service now authorizes, the set-up has to be legitimate: the person
    genuinely joins that tenant, and the test still proves the first tenant's
    request cannot see across.
    """
    if not Membership.objects.filter(user=user, tenant=tenant).exists():
        add_membership(user=user, tenant=tenant, actor=system_actor(tenant=tenant))
    # The hat is the tenant's root: this helper is the flat case, and a test
    # about the tree names its own node (`test_network.py`).
    return actor_for(user=user, tenant=tenant, org=root_organization(tenant=tenant))


def test_list_url_is_where_the_router_put_it() -> None:
    assert reverse("api:widget-list") == LIST_URL


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
    """The envelope, and the whole of it (ADR core-18).

    `set(body)` rather than four separate lookups on purpose: the point of a
    hard cut is that `count` is not silently still there and `page` is not
    silently still accepted, and only an exact key set can say so.
    """
    for index in range(3):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")
    api.force_login(owner)
    response = api.get(LIST_URL)
    assert response.status_code == 200
    body = _body(response)
    # `allowed_acts` is the LIST's own acts (`create` where the actor may) —
    # the family's page (`ActsPagination`), not a widening of the cursor's cut.
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
    # **The refusal got stronger at Phase R and the property did not move.** A
    # person with no membership resolves no tenant, so the door refuses before
    # the selector is reached — where it used to answer an empty page. "Sees
    # nothing" is what this test is about, and 403 with no body is a stricter
    # way of seeing nothing than 200 with an empty list; the assertion below is
    # what stops the day it quietly becomes a page of somebody else's rows.
    assert response.status_code == 403, response.content
    assert "Not yours" not in response.content.decode()


def test_a_superuser_with_no_membership_sees_nothing(
    api: Client, tenant: Tenant, owner: User, root: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Not yours either")
    api.force_login(root)
    response = api.get(LIST_URL)
    # No superuser exemption, and the refusal is the same one a nobody gets —
    # see the test above for why 403 rather than an empty page.
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
    """The service raises `ValidationError`; the client must see JSON, not HTML.

    Before `config/api.py` mapped it, this route answered a duplicate name with
    an unhandled exception — a 500 and a page of HTML for a machine door.
    """
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
    """The machine door refuses `X-Tenant`, exactly as the human one does.

    The token is pinned to `tenant`; the header asks for `other_tenant`. It was
    once answered as `tenant` — a request that named a tenant it could not have,
    quietly served somebody else's scope — and then, until ADR core-21, answered
    **401** over a perfectly live credential. It is a 403 naming the header now:
    authenticated, then refused for where it asked to act.
    """
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
    """The same request on the human door: refused, and never the default's rows.

    "Sees nothing" was the old contract (ADR core-21 retired it): an empty
    page and "you named somewhere you cannot go" are two different facts, and a
    client whose header did not interpolate could not tell them apart.
    """
    create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    api.force_login(owner)
    response = api.get(LIST_URL, headers={"x-tenant": other_tenant.slug})
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "addressing_header_not_honoured"


def test_a_bad_token_is_refused(api: Client, tenant: Tenant, owner: User) -> None:
    assert api.get(LIST_URL, headers={"authorization": "Bearer nonsense"}).status_code == 401


# The same budget at five rows and at fifty — the page's size, rows carrying
# `allowed_acts`, `version`, `organization_name` and `owner_name`: every one is
# read off the row the page already selected, so none of them costs a query.
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


# House rule 3's allow-list lives in `quality/rules.yaml` (rule 3,
# `allow_unauthenticated`) and nowhere else. These tests see it from the
# published contract — operationIds — through the same `apps.core.checks`
# loader the `djb` system check enforces the registry side with, so the
# contract test, the check and the file cannot drift apart.


def test_every_route_in_the_document_declares_security(api: Client) -> None:
    from apps.core.checks import unauthenticated_operation_ids

    allowed = unauthenticated_operation_ids()
    document = _body(api.get("/api/v1/openapi.json"))
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            if operation.get("operationId") in allowed:
                continue
            assert operation.get("security"), f"{method.upper()} {path} declares no auth"


def test_the_document_declares_no_other_open_route(api: Client) -> None:
    """An equality, so a second `auth=None` anywhere in the tree fails here."""
    from apps.core.checks import unauthenticated_operation_ids

    document = _body(api.get("/api/v1/openapi.json"))
    open_routes = {
        operation["operationId"]
        for methods in document["paths"].values()
        for operation in methods.values()
        if not operation.get("security")
    }
    assert open_routes == unauthenticated_operation_ids()


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
    """ "This person did it" and "an integration they installed did it" are
    different facts, and only the token tells them apart."""
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
    """`?ordering=` straight into `.order_by()` lets a client sort by any column
    and traverse any relation. This is the refusal that stops it."""
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


def test_the_limit_has_a_ceiling(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Without a ceiling, `?limit=` is a slower way to ask for everything.

    **REFUSED rather than clamped**, and "friendlier" was the wrong
    reading: a client asking for ten thousand rows and receiving two hundred got
    no signal of any kind — no header, no field, no refusal — so one that paged
    by "I asked for everything and this is what there was" stopped at the first
    page and never knew. The friendly answer is the one that says what happened.
    """
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
    """The whole point of the rung: the product can end its own wait.

    Before this route existed the only way to signal the onboarding run was the
    Temporal CLI, so the run sat `running` until the seven-day timer expired.
    """
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
    # And no second run: signalling starts nothing, so the deterministic id
    # still names exactly one onboarding.
    assert (
        WorkflowRun.objects.for_tenant(tenant).filter(type="WidgetOnboardingWorkflow").count() == 1
    )


def test_approving_a_run_that_has_already_ended_is_a_409(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The other half: once the run is over, an approval is a `conflict`.

    Refused here, by the row, rather than by an RPC error inside an on-commit
    hook that nobody is watching — which is what Temporal would have answered.
    """
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
    """The honest answer when there is nothing to signal.

    A widget whose run has been purged (Temporal retention, a wiped table) is
    not a 500 and not a silent 200: there is no wait to end.
    """
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
    """The rule approval exists for, said as a test: nobody approves their own.

    Every other verb in this app is "a member may act on their own record".
    This one deliberately is not, and without this test the difference would be
    an accident of how `can_approve` happens to be written.
    """
    widget = create_widget(tenant=tenant, actor=member_actor, name="Mine, unapproved")
    api.force_login(member)
    assert api.post(approve_url(widget), content_type=JSON).status_code == 403


def test_an_admin_may_approve_anybodys(
    api: Client, tenant: Tenant, admin_member: User, member_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=member_actor, name="Somebody else's")
    api.force_login(admin_member)
    assert api.post(approve_url(widget), content_type=JSON).status_code == 200


# --- The hierarchy's own routes, at seeded scale ------------------------------
#
# Measured at ten rows, not guessed. Each of the three is the eight-query list
# budget above with the parts a given route does not pay for taken out, and each
# is a *fixed* cost: the point of a pin is that adding rows does not move it.

# `/stats/`: the session row + the user row + 1 SAVEPOINT (ATOMIC_REQUESTS) +
# the membership lookup for the tenant + the membership lookup for the acting
# org + the two COUNTs the basis is built from + 1 RELEASE SAVEPOINT. There is
# no page and no pagination COUNT, because the route answers with one object.
# The two COUNTs are the honest cost of an honest basis: a formula whose inputs
# are measured costs one query per input, and a subtraction that saved one would
# have made an input unmeasured.
#
# **+3 since Phase R** (ADR core-27, rule 5): the selector asks
# ``widget.read`` at the acting hat, and resolution reads three tables —
# this person's memberships in the tenant, the grants on them, and the role
# deltas for the roles on the chain. It is paid ONCE per actor instance
# whatever the number of `require`s (the PR0 memo), so a route that asked
# twice would still be +3 and not +6.
#
# The aggregate is covered by the one read key of the kind it counts: `/stats/`
# reads widgets, so it asks `widget.read` and nothing else.
STATS_QUERY_BUDGET = 11

# `/policies/`: the same five request-shaped queries, plus the pagination COUNT
# and the page. `select_related("organization")` is what keeps the page at one
# query no matter how many policies come back — `WidgetPolicyOut` reads the
# slug off the relation for every row.
#
# **+3 since Phase R** (ADR core-27, rule 5): the selector asks
# ``widget_policy.read`` at the acting hat, and resolution reads three tables —
# this person's memberships in the tenant, the grants on them, and the role
# deltas for the roles on the chain. It is paid ONCE per actor instance
# whatever the number of `require`s (the PR0 memo), so a route that asked
# twice would still be +3 and not +6.
POLICIES_QUERY_BUDGET = 10

# `/entries/`: identical in shape to the policies list, for the same reasons —
# five for the request, the COUNT, the page, the RELEASE.
#
# **+3 since Phase R** (ADR core-27, rule 5): the selector asks
# ``widget_entry.read`` at the acting hat, and resolution reads three tables —
# this person's memberships in the tenant, the grants on them, and the role
# deltas for the roles on the chain. It is paid ONCE per actor instance
# whatever the number of `require`s (the PR0 memo), so a route that asked
# twice would still be +3 and not +6.
ENTRIES_QUERY_BUDGET = 10


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
    assert body["count"]["basis"]["inputs"] == {"onboarded": "0", "pending": "10"}


def test_policies_list_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    django_assert_num_queries: Any,
    owner_actor: Actor,
) -> None:
    """One query for the page however many policies it holds — the `select_related`.

    Take `select_related("organization")` out of `list_widget_policies` and this
    is the test that fails, because `WidgetPolicyOut.organization_slug` walks
    the relation once per row.
    """
    for index in range(10):
        create_widget_policy(tenant=tenant, actor=owner_actor, name=f"Policy {index}")
    api.force_login(owner)

    with django_assert_num_queries(POLICIES_QUERY_BUDGET):
        response = api.get(reverse("api:widget_policies-list"))

    assert response.status_code == 200, response.content
    assert len(_body(response)["items"]) == 10


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


def test_the_stats_basis_moves_with_the_rows_it_measures(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The inputs are read off the table, not remembered. Onboard one and watch.

    Without this the previous test would pass against a server that always
    answered `{"onboarded": "0", "pending": n}`, which is a formula that happens
    to be right rather than a measurement.
    """
    first = create_widget(tenant=tenant, actor=owner_actor, name="First")
    create_widget(tenant=tenant, actor=owner_actor, name="Second")
    mark_widget_onboarded(tenant=tenant, actor=owner_actor, widget=first)
    api.force_login(owner)

    body = _body(api.get(reverse("api:widget_stats-detail")))

    assert body["count"]["basis"]["inputs"] == {"onboarded": "1", "pending": "1"}
    assert body["count"]["value"] == "2"
