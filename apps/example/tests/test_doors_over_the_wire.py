"""The doors as a real client meets them: CSRF on the REST door, parity on the wire (rule 46)."""

# golden: noun begin
from __future__ import annotations

import json

# golden: noun end
# golden: stat count begin
from decimal import Decimal

# golden: stat count end
# golden: noun begin
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.test import Client

from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.example.services import create_widget
from pilecap import Actor
from pilecap.accounts import User, issue_token, revoke_token
from pilecap.tenancy import Tenant
from pilecap.testing import (
    MCP_HEADERS,
    MCP_URL,
    actor_for,
    assert_four_doors,
    initialize,
    rpc,
    wire,
    without_personal,
)
from pilecap.testing import bearer as mint_bearer

#: House rule 46. The door pair this module answers for `apps/example`.
DOOR_PAIR = ("rest", "mcp")

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
DETAIL_URL = "/api/v1/widgets/{}/"
# golden: noun end
# golden: stat count begin
STATS_URL = "/api/v1/widgets/stats/"
# golden: stat count end
# golden: noun begin
JSON = "application/json"
PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
# golden: noun end

# The widget read shape, written out: a pin derived from the thing it pins cannot fail.
# golden: noun begin
WIDGET_KEYS = frozenset(
    {
        "id",
        "name",
        "notes",
        "owner_id",
        "owner_email",
        "tenant_id",
        "organization_id",
        "organization_slug",
        "created_at",
        "updated_at",
        # golden: noun end
        # golden: workflow onboard begin
        "onboarded_at",
        # golden: workflow onboard end
        # golden: policy begin
        "policy_id",
        # golden: policy end
        # The archive shape (`ArchivedOut`) and the per-row acts.
        # golden: noun begin
        "archived_at",
        "archived_by",
        "allowed_acts",
        # golden: noun end
        # The rest of the family: the version, the node in words, the owner in words.
        # golden: noun begin
        "version",
        # golden: noun end
        "organization_name",
        "owner_name",
        # The copy it was made from, the merge survivor, and the import's key.
        "duplicated_from_id",
        "merged_into_id",
        "external_ref",
        # When it is due, or null.
        # golden: noun begin
        # golden: field due_at begin
        "due_at",
        # golden: field due_at end
        # golden: noun end
        # golden: enum status begin
        "status",
        # golden: enum status end
        # golden: noun begin
    }
)
# golden: noun end

# The DETAIL answers the row and the words on it: `tags`.
DETAIL_KEYS = WIDGET_KEYS | {"tags"}

# golden: noun begin
# The fields `WidgetOut` marks `personal`: both doors answer them, no event carries them.
PERSONAL_KEYS = frozenset({"owner_email", "owner_name"})

# What a widget event carries: the row less the viewer's acts and the person's fields.
EVENT_KEYS = WIDGET_KEYS - {"allowed_acts"} - PERSONAL_KEYS
# golden: noun end

# golden: noun begin
# A page that always renders a form: the source of a real, server-issued CSRF token.
CSRF_SOURCE_URL = "/admin/login/"


def strict_client() -> Client:
    """A client that enforces CSRF, which the shared `api` fixture does not."""
    return Client(enforce_csrf_checks=True)


def csrf_token(client: Client) -> str:
    """A real CSRF token for this client, issued by the server."""
    client.get(CSRF_SOURCE_URL)
    return str(client.cookies[settings.CSRF_COOKIE_NAME].value)


def test_a_bearer_write_needs_no_csrf_material(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The machine door, over the wire: a token, a POST, a row. No cookie."""
    plaintext = mint_bearer(user=owner, tenant=tenant)

    response = strict_client().post(
        LIST_URL,
        data=json.dumps({"name": "Minted by a machine"}),
        content_type=JSON,
        headers={"authorization": f"Bearer {plaintext}"},
    )

    assert response.status_code == 201, response.content
    assert Widget.objects.for_tenant(tenant).filter(name="Minted by a machine").exists()


def test_a_session_write_without_a_csrf_token_is_refused(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The human door keeps the whole of CSRF; nothing here was loosened."""
    client = strict_client()
    client.force_login(owner)

    response = client.post(
        LIST_URL,
        data=json.dumps({"name": "Forged"}),
        content_type=JSON,
    )

    assert response.status_code == 403, response.content
    assert not Widget.objects.for_tenant(tenant).filter(name="Forged").exists()


def test_a_session_write_with_a_csrf_token_is_allowed(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The other half of the same property: the browser that plays by the rules."""
    client = strict_client()
    client.force_login(owner)
    token = csrf_token(client)

    response = client.post(
        LIST_URL,
        data=json.dumps({"name": "Minted by a person"}),
        content_type=JSON,
        headers={"x-csrftoken": token},
    )

    assert response.status_code == 201, response.content
    assert Widget.objects.for_tenant(tenant).filter(name="Minted by a person").exists()


# golden: noun end


# --- Door parity, on the wire -------------------------------------------------


# golden: noun begin
@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    return mint_bearer(user=owner, tenant=tenant, name="door-parity")


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None) -> Widget:
    """One committed row for both doors to answer with."""
    return create_widget(tenant=tenant, actor=owner_actor, name="Twin", notes="hello")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_key_set_on_the_wire(bearer: str, widget: Widget) -> None:
    """The same row, fetched over HTTP and over JSON-RPC: one key set, not two."""
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with wire() as client:
        over_http = await client.get(
            DETAIL_URL.format(widget.pk), headers={**bearer_header, "accept": JSON}
        )
        assert over_http.status_code == 200, over_http.text

        headers = {**MCP_HEADERS, **bearer_header}
        await initialize(client, headers, "door-parity")

        called = await client.post(
            MCP_URL,
            headers=headers,
            json=rpc(
                "tools/call",
                {"name": "get_widget", "arguments": {"widget_id": str(widget.pk)}},
                2,
            ),
        )
        assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # golden: noun end
    # The REST body first, against the written-out contract.
    assert set(rest_body) == DETAIL_KEYS
    # golden: noun begin

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same widget with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field "
        "name. Resolve a relation with a model property, not an alias "
        "(ADR example-3; `apps/comms/models.py` is the precedent)."
    )


# golden: noun end


# golden: stat count begin
# The measured-number shape, written out at both levels (ADR core-7).
STATS_KEYS = frozenset({"count"})
MEASURED_KEYS = frozenset({"value", "basis"})
BASIS_KEYS = frozenset({"formula", "inputs"})


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_agree_on_a_measured_number_and_its_basis(
    bearer: str, widget: Widget
) -> None:
    """`/widgets/stats/` and its tool: one shape, one value, one basis."""
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with wire() as client:
        over_http = await client.get(STATS_URL, headers={**bearer_header, "accept": JSON})
        assert over_http.status_code == 200, over_http.text

        headers = {**MCP_HEADERS, **bearer_header}
        await initialize(client, headers, "stats-parity")

        called = await client.post(
            MCP_URL,
            headers=headers,
            json=rpc("tools/call", {"name": "get_widget_stats", "arguments": {}}, 2),
        )
        assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # (1) the shape, against the written-out contract.
    assert set(rest_body) == STATS_KEYS
    assert set(rest_body["count"]) == MEASURED_KEYS
    assert set(rest_body["count"]["basis"]) == BASIS_KEYS

    # (2) the two doors: the key sets first.
    assert set(over_mcp) == set(rest_body)
    assert set(over_mcp["count"]) == set(rest_body["count"])
    assert set(over_mcp["count"]["basis"]) == set(rest_body["count"]["basis"])
    # Then the whole structure, verbatim: `Decimal` is a string on both sides.
    assert over_mcp == rest_body
    assert rest_body["count"]["value"] == "1", "a Decimal on the wire is a string, not a float"

    # (3) the basis is honest: the value recomputed from the inputs agrees.
    basis = rest_body["count"]["basis"]
    assert basis["formula"] == "live + archived"
    recomputed = sum(Decimal(str(value)) for value in basis["inputs"].values())
    assert recomputed == Decimal(str(rest_body["count"]["value"]))
    # And the one row this fixture made is really in there.
    assert recomputed == Decimal(1)


# golden: stat count end


# --- 3 · the read refusal, on both doors, in the same words --------------------


# golden: noun begin
@pytest.fixture
def member_bearer(tenant: Tenant, member: User) -> str:
    """A real token for the plain member — the credential both doors accept."""
    return mint_bearer(user=member, tenant=tenant, name="read-parity")


@pytest.fixture
def withheld_widget_read(tenant: Tenant, member: User) -> str:
    """A committed `withhold` of `widget.read` on the member, and its sentence."""
    from pilecap.tenancy import Grant, Membership
    from pilecap.testing import refusal_sentence

    membership = Membership.objects.get(user=member, tenant=tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="widget.read",
        effect=Grant.Effect.WITHHOLD,
    )
    return refusal_sentence("widget.read")


# golden: noun end


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    member_bearer: str, withheld_widget_read: str, widget: Widget
) -> None:
    """House rule 46, applied to the read gate."""
    sentence = withheld_widget_read
    bearer_header = {"authorization": f"Bearer {member_bearer}"}

    async with wire() as client:
        over_http = await client.get(
            DETAIL_URL.format(widget.pk), headers={**bearer_header, "accept": JSON}
        )

        headers = {**MCP_HEADERS, **bearer_header}
        await initialize(client, headers, "read-parity")

        called = await client.post(
            MCP_URL,
            headers=headers,
            json=rpc(
                "tools/call",
                {"name": "get_widget", "arguments": {"widget_id": str(widget.pk)}},
                2,
            ),
        )

    # The human door: a row INSIDE the hat's subtree, refused by capability, not hidden.
    assert over_http.status_code == 403, over_http.text
    body = over_http.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == sentence

    # The machine door: the same code and the same sentence, through `wire_refusal`.
    answered = called.json()
    rendered = json.dumps(answered)
    assert "forbidden" in rendered, rendered
    assert sentence in rendered, rendered


# --- 4 · the 401, on both doors, in the same words ----------------------------

# golden: noun begin
# The sentence a presented-but-unresolvable bearer reads, written out.
BEARER_NOT_VALID = "That bearer token is not valid."


@pytest.fixture
def revoked_bearer(tenant: Tenant, owner: User) -> str:
    """A real token for a real person, withdrawn — and still in the caller's hand."""
    actor = actor_for(user=owner, tenant=tenant)
    token, plaintext = issue_token(user=owner, tenant=tenant, name="withdrawn", actor=actor)
    revoke_token(token=token, tenant=tenant, actor=actor)
    return plaintext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_one_revoked_token_with_the_same_code_and_sentence(
    revoked_bearer: str,
) -> None:
    """House rule 46 at the door's own refusal, which has no principal behind it."""
    bearer_header = {"authorization": f"Bearer {revoked_bearer}"}

    async with wire() as client:
        over_http = await client.get(LIST_URL, headers={**bearer_header, "accept": JSON})
        over_mcp = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **bearer_header},
            json=rpc("tools/list", {}, 1),
        )

    assert over_http.status_code == 401, over_http.text
    assert over_mcp.status_code == 401, over_mcp.text
    rest_body = over_http.json()
    mcp_body = over_mcp.json()

    assert rest_body["code"] == mcp_body["code"] == "unauthenticated", (rest_body, mcp_body)
    assert rest_body["detail"] == mcp_body["detail"] == BEARER_NOT_VALID, (rest_body, mcp_body)


# golden: noun end


# --- One press, three tellings ------------------------------------------------


# golden: noun begin
async def _mcp_call(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """`initialize`, then one `tools/call`; the result's `structuredContent`."""
    await initialize(client, headers, "door-parity")
    called = await client.post(
        MCP_URL, headers=headers, json=rpc("tools/call", {"name": name, "arguments": arguments}, 2)
    )
    assert called.status_code == 200, called.text
    answered = called.json()
    assert "error" not in answered, answered
    assert not answered["result"].get("isError"), answered
    content: dict[str, Any] = answered["result"]["structuredContent"]
    return content


def _canonical(body: dict[str, Any]) -> str:
    """One byte string per body: sorted keys, the door's own separators."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _event_payload(tenant: Tenant, name: str) -> dict[str, Any]:
    """The outbox row's payload for the one event of this name, minus the spine's `v`."""
    from django.apps import apps as django_apps

    outbox = django_apps.get_model("events", "Outbox")
    rows = list(
        outbox.objects.filter(event__tenant=tenant, event__name=name).select_related("event")
    )
    assert len(rows) == 1, [row.event.name for row in rows]
    payload: dict[str, Any] = dict(rows[0].event.payload)
    assert "v" in payload
    payload.pop("v")
    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["archive", "restore"])
async def test_one_press_is_one_body_on_rest_mcp_and_the_outbox(
    bearer: str, widget: Widget, tenant: Tenant, member: User, verb: str
) -> None:
    """M4: one viewer's REST and MCP answers are one byte string; the event is the row."""
    from asgiref.sync import sync_to_async

    from apps.example.services import archive_widget
    from pilecap.testing import actor_for

    if verb == "restore":
        owner = await sync_to_async(lambda: widget.owner)()
        await sync_to_async(archive_widget)(
            tenant=tenant,
            actor=actor_for(
                user=owner, tenant=tenant, org=await sync_to_async(lambda: widget.organization)()
            ),
            widget=widget,
        )

    member_bearer = await sync_to_async(_token_for)(member, tenant)
    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        over_http = await client.post(
            f"{LIST_URL}{widget.pk}/{verb}/", headers={**bearer_header, "accept": JSON}
        )
        assert over_http.status_code == 200, over_http.text
        over_mcp = await _mcp_call(
            client,
            {**MCP_HEADERS, **bearer_header},
            f"{verb}_widget",
            {"widget_id": str(widget.pk)},
        )
        as_member = await client.get(
            f"{LIST_URL}{widget.pk}/",
            headers={"authorization": f"Bearer {member_bearer}", "accept": JSON},
        )
        assert as_member.status_code == 200, as_member.text

    rest_body: dict[str, Any] = over_http.json()
    member_body: dict[str, Any] = as_member.json()
    event = await sync_to_async(_event_payload)(tenant, f"example.widget.{verb}d")
    assert set(rest_body) == WIDGET_KEYS
    assert (verb == "archive") == (rest_body["archived_at"] is not None)
    assert rest_body["allowed_acts"], rest_body

    # One viewer, two doors: one byte string.
    assert _canonical(over_mcp) == _canonical(rest_body)
    # The event is the row, never a viewer's acts.
    assert "allowed_acts" not in event, sorted(event)
    assert set(event) == EVENT_KEYS
    assert _canonical(event) == _canonical(_as_published(rest_body))
    assert_four_doors(rest=rest_body, mcp=over_mcp, event_payload=event, out=WidgetOut)
    # A second viewer: the same row, other acts — and nothing else different.
    assert member_body.pop("tags", []) == []
    assert _canonical(_without_acts(member_body)) == _canonical(_without_acts(rest_body))
    assert member_body["allowed_acts"] != rest_body["allowed_acts"]
    assert not {"archive", "restore"} & set(member_body["allowed_acts"])


# golden: noun end
# golden: verb touch begin
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_touch_is_one_body_on_rest_mcp_and_the_outbox(
    bearer: str, widget: Widget, tenant: Tenant
) -> None:
    """The REST press and its event are one row; the MCP read answers that row byte for byte."""
    from asgiref.sync import sync_to_async

    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        over_http = await client.post(
            f"{LIST_URL}{widget.pk}/touch/", headers={**bearer_header, "accept": JSON}
        )
        assert over_http.status_code == 200, over_http.text
        over_mcp = await _mcp_call(
            client, {**MCP_HEADERS, **bearer_header}, "get_widget", {"widget_id": str(widget.pk)}
        )
    rest_body: dict[str, Any] = over_http.json()
    event = await sync_to_async(_event_payload)(tenant, "example.widget.touched")
    assert set(rest_body) == WIDGET_KEYS
    assert over_mcp.pop("tags", []) == []
    assert_four_doors(rest=rest_body, mcp=over_mcp, event_payload=event, out=WidgetOut)


# golden: verb touch end
# golden: enum status begin
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_transition_is_one_body_on_rest_mcp_and_the_outbox(
    bearer: str, widget: Widget, tenant: Tenant
) -> None:
    """The REST move and its event are one row; the MCP read answers that row byte for byte."""
    from asgiref.sync import sync_to_async

    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        over_http = await client.post(
            f"{LIST_URL}{widget.pk}/transition/",
            headers={**bearer_header, "accept": JSON},
            json={"status": "active"},
        )
        assert over_http.status_code == 200, over_http.text
        over_mcp = await _mcp_call(
            client, {**MCP_HEADERS, **bearer_header}, "get_widget", {"widget_id": str(widget.pk)}
        )
    rest_body: dict[str, Any] = over_http.json()
    event = await sync_to_async(_event_payload)(tenant, "example.widget.transitioned")
    assert rest_body["status"] == "active"
    assert over_mcp.pop("tags", []) == []
    assert_four_doors(rest=rest_body, mcp=over_mcp, event_payload=event, out=WidgetOut)


# golden: enum status end
# golden: noun begin
def _without_acts(body: dict[str, Any]) -> dict[str, Any]:
    """The row as every viewer sees it: the body minus this viewer's acts."""
    return {key: value for key, value in body.items() if key != "allowed_acts"}


def _as_published(body: dict[str, Any]) -> dict[str, Any]:
    """The row as an event carries it: no viewer's acts, no `personal` field at any depth."""
    return without_personal(WidgetOut, _without_acts(body))


def _token_for(user: User, tenant: Tenant) -> str:
    """A real bearer token for a second viewer of the same tenant."""
    return mint_bearer(user=user, tenant=tenant, name="second-viewer")


# golden: noun end


# --- 5 · The rest of the family, on both doors and the outbox --------------------


# golden: noun begin
@pytest.fixture
def branch(tenant: Tenant, owner: User) -> Any:
    from pilecap.tenancy import create_organization, root_organization

    root = root_organization(tenant=tenant)
    return create_organization(
        tenant=tenant,
        parent=root,
        name="Branch",
        slug="branch",
        actor=actor_for(user=owner, tenant=tenant, org=root),
    )


def _one_event(tenant: Tenant, name: str) -> dict[str, Any]:
    return _event_payload(tenant, name)


# golden: noun end


async def _press(
    client: httpx.AsyncClient,
    bearer_header: dict[str, str],
    verb: str,
    widget_id: str,
    version: int,
    branch_id: str,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """The REST press, and the MCP press that repeats it: (REST response, REST body, MCP body)."""
    headers = {**bearer_header, "accept": JSON}
    mcp_headers = {**MCP_HEADERS, **bearer_header}
    if verb == "update":
        rest = await client.patch(
            f"{LIST_URL}{widget_id}/", headers=headers, json={"name": "Pressed", "version": version}
        )
        body = rest.json()
        # The repeat names the version REST answered and sends nothing to change.
        mcp = await _mcp_call(
            client,
            mcp_headers,
            "update_widget",
            {"widget_id": widget_id, "version": body["version"]},
        )
    elif verb == "move":
        rest = await client.post(
            f"{LIST_URL}{widget_id}/move/",
            headers=headers,
            json={"organization_id": branch_id, "version": version},
        )
        body = rest.json()
        mcp = await _mcp_call(
            client,
            mcp_headers,
            "move_widget",
            {"widget_id": widget_id, "organization_id": branch_id, "version": body["version"]},
        )
    elif verb == "bulk":
        rest = await client.post(
            f"{LIST_URL}bulk/", headers=headers, json={"verb": "archive", "ids": [widget_id]}
        )
        body = rest.json()
        mcp = await _mcp_call(
            client, mcp_headers, "bulk_widgets", {"verb": "archive", "ids": [widget_id]}
        )
    else:
        rest = await client.get(f"{LIST_URL}{widget_id}/history/", headers=headers)
        body = rest.json()
        mcp = await _mcp_call(client, mcp_headers, "list_widget_history", {"widget_id": widget_id})
    return rest, body, mcp


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["update", "move", "bulk", "history"])
async def test_each_family_verb_is_one_body_on_rest_mcp_and_the_outbox(
    bearer: str, widget: Widget, tenant: Tenant, member: User, branch: Any, verb: str
) -> None:
    from asgiref.sync import sync_to_async

    version = await sync_to_async(lambda: widget.version)()
    member_bearer = await sync_to_async(_token_for)(member, tenant)
    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        rest, rest_body, over_mcp = await _press(
            client, bearer_header, verb, str(widget.pk), version, str(branch.pk)
        )
        assert rest.status_code == 200, rest.text
        as_owner = await client.get(
            f"{LIST_URL}{widget.pk}/", headers={**bearer_header, "accept": JSON}
        )
        as_member = await client.get(
            f"{LIST_URL}{widget.pk}/",
            headers={"authorization": f"Bearer {member_bearer}", "accept": JSON},
        )
        assert as_member.status_code == 200, as_member.text

    # One viewer, two doors: one byte string, the bulk repeat reading `unchanged`.
    if verb == "bulk":
        assert [r["outcome"] for r in rest_body["results"]] == ["done"]
        assert [r["outcome"] for r in over_mcp["results"]] == ["unchanged"]
        repeated = {
            **rest_body,
            "done": 0,
            "unchanged": 1,
            "results": [{**rest_body["results"][0], "outcome": "unchanged"}],
        }
        assert _canonical(over_mcp) == _canonical(repeated)
        row = rest_body["results"][0]["item"]
    else:
        assert _canonical(over_mcp) == _canonical(rest_body)
        row = rest_body if verb != "history" else as_owner.json()

    # The event is the row, never a viewer's acts.
    said = {
        "update": "example.widget.updated",
        "move": "example.widget.moved",
        "bulk": "example.widget.archived",
    }.get(verb)
    if said is not None:
        event = await sync_to_async(_one_event)(tenant, said)
        assert "allowed_acts" not in event, sorted(event)
        if verb == "move":
            assert event.pop("from_organization_id") == str(widget.organization_id)
            assert event["organization_id"] == str(branch.pk)
        assert set(event) == EVENT_KEYS
        assert _canonical(event) == _canonical(_as_published(row))

    # A second viewer: the same row, other acts — and nothing else different.
    owner_body = as_owner.json()
    member_body = as_member.json()
    assert set(owner_body) == DETAIL_KEYS
    assert _canonical(_without_acts(member_body)) == _canonical(_without_acts(owner_body))
    assert member_body["allowed_acts"] != owner_body["allowed_acts"]


# golden: noun begin
@pytest.fixture
def branch_admin_bearer(tenant: Tenant, owner: User) -> tuple[str, list[str]]:
    """A token for an ADMIN at A in a root/A/A1/B world, and the ids of A and A1."""
    from pilecap.accounts import create_user
    from pilecap.tenancy import Membership, add_membership, create_organization, root_organization
    from pilecap.testing import system_actor

    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
    create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=acting)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=acting)
    manager = create_user(email="a-admin@example.com", password=PASSWORD)
    add_membership(
        user=manager,
        tenant=tenant,
        organization=a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return _token_for(manager, tenant), sorted([str(a.pk), str(a1.pk)])


# golden: noun end


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_move_sheets_destinations_agree_on_both_doors(
    branch_admin_bearer: tuple[str, list[str]],
) -> None:
    """`?can=widget.move` and `list_organizations(can="widget.move")`: A and A1, on both."""
    token, expected = branch_admin_bearer
    header = {"authorization": f"Bearer {token}"}
    async with wire() as client:
        over_http = await client.get(
            "/api/v1/organizations/",
            params={"can": "widget.move"},
            headers={**header, "accept": JSON},
        )
        assert over_http.status_code == 200, over_http.text
        over_mcp = await _mcp_call(
            client, {**MCP_HEADERS, **header}, "list_organizations", {"can": "widget.move"}
        )

    assert sorted(row["id"] for row in over_http.json()["items"]) == expected
    assert sorted(row["id"] for row in over_mcp["items"]) == expected


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_partial_bulk_answers_the_same_three_outcomes_on_the_machine_door(
    tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """`bulk_widgets`: done, refused(`not_found`), done — as `POST /widgets/bulk/` answers."""
    from asgiref.sync import sync_to_async

    from pilecap.tenancy import create_organization, root_organization

    def world() -> tuple[str, list[str]]:
        from pilecap.accounts import create_user
        from pilecap.tenancy import Membership, add_membership
        from pilecap.testing import system_actor

        root = root_organization(tenant=tenant)
        acting = actor_for(user=owner, tenant=tenant, org=root)
        a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
        b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=acting)
        manager = create_user(email="a-admin@example.com", password=PASSWORD)
        add_membership(
            user=manager,
            tenant=tenant,
            organization=a,
            is_default=True,
            role=Membership.Role.ADMIN,
            actor=system_actor(tenant=tenant),
        )
        ids = [
            str(
                create_widget(
                    tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=node), name=name
                ).pk
            )
            for node, name in ((a, "first"), (b, "sibling"), (a, "third"))
        ]
        return _token_for(manager, tenant), ids

    token, ids = await sync_to_async(world)()
    async with wire() as client:
        answered = await _mcp_call(
            client,
            {**MCP_HEADERS, "authorization": f"Bearer {token}"},
            "bulk_widgets",
            {"verb": "archive", "ids": ids},
        )

    assert [r["outcome"] for r in answered["results"]] == ["done", "refused", "done"]
    assert [r["id"] for r in answered["results"]] == ids
    assert answered["results"][1]["refusal"]["code"] == "not_found"


# --- 6 · Duplicate and merge: one press, four tellings ---------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["duplicate", "merge"])
async def test_duplicate_and_merge_are_one_row_on_four_doors_for_two_viewers(
    bearer: str, widget: Widget, tenant: Tenant, owner: User, member: User, verb: str
) -> None:
    from asgiref.sync import sync_to_async

    def survivor_and_versions() -> tuple[str, int, int]:
        into = create_widget(
            tenant=tenant,
            actor=actor_for(user=owner, tenant=tenant, org=widget.organization),
            name="Survivor",
        )
        return str(into.pk), Widget.objects.get(pk=widget.pk).version, into.version

    into_id, version, into_version = (
        await sync_to_async(survivor_and_versions)() if verb == "merge" else ("", 0, 0)
    )
    member_bearer = await sync_to_async(_token_for)(member, tenant)
    header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        if verb == "duplicate":
            rest = await client.post(
                f"{LIST_URL}{widget.pk}/duplicate/",
                headers={**header, "accept": JSON, "idempotency-key": "m4-press"},
            )
            assert rest.status_code == 201, rest.text
            over_mcp = await _mcp_call(
                client,
                {**MCP_HEADERS, **header},
                "duplicate_widget",
                {"widget_id": str(widget.pk), "idempotency_key": "m4-press"},
            )
        else:
            rest = await client.post(
                f"{LIST_URL}{widget.pk}/merge/",
                headers={**header, "accept": JSON},
                json={"into_id": into_id, "version": version, "into_version": into_version},
            )
            assert rest.status_code == 200, rest.text
            over_mcp = await _mcp_call(
                client,
                {**MCP_HEADERS, **header},
                "merge_widget",
                {
                    "widget_id": str(widget.pk),
                    "into_id": into_id,
                    "version": version,
                    "into_version": into_version,
                },
            )
        row_id = rest.json()["id"]
        as_owner = await client.get(f"{LIST_URL}{row_id}/", headers={**header, "accept": JSON})
        as_member = await client.get(
            f"{LIST_URL}{row_id}/",
            headers={"authorization": f"Bearer {member_bearer}", "accept": JSON},
        )
        assert as_member.status_code == 200, as_member.text

    payload = await sync_to_async(_event_payload)(tenant, f"example.widget.{verb}d")
    if verb == "merge":
        # What is true of the EVENT and not of the row.
        assert payload.pop("loser_id") == str(widget.pk)
        repoints = payload.pop("repoints")
        assert {row["title"]: row["left"] for row in repoints} == {
            "Notes": 0,
            "Tags": 0,
            "Files": 0,
            # The worked customer surface re-points the requests about a widget.
            "Portal requests": 0,
        }
    assert set(payload) == EVENT_KEYS
    assert_four_doors(rest=rest.json(), mcp=over_mcp, event_payload=payload, out=WidgetOut)
    # The second viewer: the same row, other acts — and nothing else different.
    owner_body, member_body = as_owner.json(), as_member.json()
    assert set(owner_body) == DETAIL_KEYS
    assert _canonical(_without_acts(member_body)) == _canonical(_without_acts(owner_body))
    assert member_body["allowed_acts"] != owner_body["allowed_acts"]


# --- 7 · The due-date narrowing, on both doors --------------------------------


# golden: noun begin
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_narrow_by_due_date_and_refuse_a_naive_one_alike(
    bearer: str, tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """`?due_after=` and `list_widgets(due_after=)` answer one page; naive is refused."""
    from datetime import UTC, datetime

    from asgiref.sync import sync_to_async

    def world() -> str:
        create_widget(
            tenant=tenant, actor=owner_actor, name="Soon", due_at=datetime(2026, 10, 15, tzinfo=UTC)
        )
        late = create_widget(
            tenant=tenant, actor=owner_actor, name="Late", due_at=datetime(2026, 12, 15, tzinfo=UTC)
        )
        return str(late.pk)

    late_id = await sync_to_async(world)()
    header = {"authorization": f"Bearer {bearer}"}
    cut, naive = "2026-11-01T00:00:00Z", "2026-11-01T00:00:00"
    async with wire() as client:
        rest = await client.get(
            LIST_URL, params={"due_after": cut}, headers={**header, "accept": JSON}
        )
        over_mcp = await _mcp_call(
            client, {**MCP_HEADERS, **header}, "list_widgets", {"due_after": cut}
        )
        refused_rest = await client.get(
            LIST_URL, params={"due_before": naive}, headers={**header, "accept": JSON}
        )
        refused_mcp = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **header},
            json=rpc("tools/call", {"name": "list_widgets", "arguments": {"due_before": naive}}, 3),
        )

    assert rest.status_code == 200, rest.text
    assert [item["id"] for item in rest.json()["items"]] == [late_id]
    assert _canonical(over_mcp) == _canonical(rest.json())

    assert refused_rest.status_code == 400, refused_rest.text
    assert refused_rest.json()["code"] == "invalid"
    assert "due_before" in refused_rest.json()["errors"]
    rendered = json.dumps(refused_mcp.json())
    assert "invalid" in rendered, rendered
    assert "due_before" in rendered, rendered


# golden: noun end


# --- 8 · The due-date ordering, on both doors ---------------------------------


# golden: noun begin
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_order_by_due_date_alike_with_the_undated_last(
    bearer: str, tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """`?ordering=-due_at` and its MCP twin answer one page, undated last."""
    from datetime import UTC, datetime

    from asgiref.sync import sync_to_async

    def world() -> None:
        create_widget(tenant=tenant, actor=owner_actor, name="Undated")
        for name, month in (("Soon", 10), ("Late", 12)):
            create_widget(
                tenant=tenant,
                actor=owner_actor,
                name=name,
                due_at=datetime(2026, month, 15, tzinfo=UTC),
            )

    await sync_to_async(world)()
    header = {"authorization": f"Bearer {bearer}"}
    async with wire() as client:
        rest = await client.get(
            LIST_URL, params={"ordering": "-due_at"}, headers={**header, "accept": JSON}
        )
        over_mcp = await _mcp_call(
            client, {**MCP_HEADERS, **header}, "list_widgets", {"ordering": "-due_at"}
        )

    assert rest.status_code == 200, rest.text
    assert [item["name"] for item in rest.json()["items"]] == ["Late", "Soon", "Undated"]
    assert _canonical(over_mcp) == _canonical(rest.json())


# golden: noun end
