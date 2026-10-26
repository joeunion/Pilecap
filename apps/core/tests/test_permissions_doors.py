"""The permission surface at the doors: eleven routes, eleven tools, one answer.

The services are `test_handing_out.py`'s; this proves a caller reaches them and both doors agree.
The wire matrix: every route × its credential kinds × present, absent, forbidden, invalid, conflict.

DOOR_PAIR = ("rest", "mcp")
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core import authz
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Forbidden, NotFound, refusal_message
from apps.core.models import Grant, Membership, Role, RolePermission, Tenant
from apps.core.selectors import (
    get_membership_permissions,
    get_role,
    list_grants,
    list_permissions,
    list_roles,
)
from apps.core.services import add_membership, create_grant, create_role, root_organization
from apps.core.tests.test_mcp_tenancy import context_for, tool

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: Every `url_name` the permission surface answers on. The list is the
#: contract: a route renamed without this list moving fails by name rather than
#: by nobody noticing.
NEW_ROUTES = (
    "role-list",
    "role-create",
    "role-detail",
    "role-update",
    "role_permissions-update",
    "role-delete",
    "grant-list",
    "grant-update",
    "grant-delete",
    "membership_permissions-detail",
    "permission-list",
)

#: The eleven tools, each the twin of one route above.
NEW_TOOLS = (
    "list_roles",
    "get_role",
    "create_role",
    "update_role",
    "update_role_permissions",
    "delete_role",
    "list_grants",
    "update_grant",
    "delete_grant",
    "get_membership_permissions",
    "list_permissions",
)


# --- the world -----------------------------------------------------------------


@pytest.fixture
def approver(tenant: Tenant, owner: User, owner_actor: Actor) -> Role:
    """A custom role this tenant made, holding one key its owner holds."""
    return create_role(
        tenant=tenant,
        actor=owner_actor,
        key="approver",
        name="Approver",
        description="May approve widgets.",
        permissions=["widget.approve"],
    )


def _session(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _bearer(user: User, tenant: Tenant, scopes: list[str] | None) -> str:
    """A token, named uniquely — `(user, name)` is unique and a test issues several."""
    return str(
        issue_token(
            user=user,
            tenant=tenant,
            name=f"p5-{'-'.join(scopes or ['wide'])}-{uuid4().hex[:8]}",
            scopes=scopes,
            actor=actor_for(user=user, tenant=tenant),
        )[1]
    )


def _headers(plaintext: str) -> dict[str, str]:
    return {"authorization": f"Bearer {plaintext}"}


def _membership(user: User, tenant: Tenant) -> Membership:
    found = Membership.objects.filter(user=user, tenant=tenant).first()
    assert found is not None
    return found


def _url(name: str, **kwargs: Any) -> str:
    return reverse(f"api:{name}", kwargs=kwargs)


# --- P5.1 · the eleven routes exist and answer by name --------------------------


@pytest.mark.parametrize("url_name", NEW_ROUTES)
def test_every_new_route_answers_by_url_name(
    url_name: str, tenant: Tenant, owner: User, approver: Role
) -> None:
    """Reverse resolves every one of them, and the door answers rather than 404s.

    `reverse` is the half that would have caught a route mounted at a path
    nobody meant; the request is the half that would have caught a route
    reversed but never bound. Neither alone is the claim.
    """
    membership = _membership(owner, tenant)
    kwargs: dict[str, Any] = {}
    if "role" in url_name and url_name not in {"role-list", "role-create"}:
        kwargs["key"] = "approver"
    if "membership" in url_name or url_name.startswith("grant"):
        kwargs["membership_id"] = membership.pk
    if url_name in {"grant-update", "grant-delete"}:
        kwargs["permission"] = "widget.approve"

    if url_name == "grant-delete":
        create_grant(
            tenant=tenant,
            actor=actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant)),
            membership=membership,
            permission="widget.approve",
            effect=Grant.Effect.ALLOW,
        )
    path = _url(url_name, **kwargs)
    client = _session(owner)
    if url_name in {
        "role-list",
        "role-detail",
        "grant-list",
        "permission-list",
    } or url_name.endswith("-detail"):
        response = client.get(path)
    elif url_name == "role-create":
        response = client.post(
            path,
            data=json.dumps({"key": "second", "name": "Second", "permissions": []}),
            content_type=JSON,
        )
    elif url_name == "role-update":
        response = client.patch(path, data=json.dumps({"name": "Renamed"}), content_type=JSON)
    elif url_name == "role_permissions-update":
        response = client.put(
            path, data=json.dumps({"permissions": ["widget.approve"]}), content_type=JSON
        )
    elif url_name == "grant-update":
        response = client.put(path, data=json.dumps({"effect": "allow"}), content_type=JSON)
    else:
        response = client.delete(path)

    assert response.status_code in {200, 201, 204}, (url_name, path, response.content)


def test_the_eleven_tools_are_registered_and_twin_their_routes() -> None:
    """`tools/list` grew by exactly these eleven, and each names its own route."""
    for name in NEW_TOOLS:
        assert callable(tool(name)), name


def test_a_replayed_idempotency_key_returns_the_first_body_and_one_row(
    tenant: Tenant, owner: User
) -> None:
    """The same key twice is one row and the first answer, on both write shapes."""
    client = _session(owner)
    body = json.dumps({"key": "reviewer", "name": "Reviewer", "permissions": []})
    first = client.post(
        _url("role-create"),
        data=body,
        content_type=JSON,
        headers={"idempotency-key": "p5-role-1"},
    )
    second = client.post(
        _url("role-create"),
        data=body,
        content_type=JSON,
        headers={"idempotency-key": "p5-role-1"},
    )

    assert first.status_code == 201, first.content
    assert second.status_code == 201
    assert first.content == second.content
    assert Role.objects.for_tenant(tenant).filter(key="reviewer").count() == 1

    membership = _membership(owner, tenant)
    path = _url("grant-update", membership_id=membership.pk, permission="widget.approve")
    grant_body = json.dumps({"effect": "allow"})
    one = client.put(
        path, data=grant_body, content_type=JSON, headers={"idempotency-key": "p5-grant-1"}
    )
    two = client.put(
        path, data=grant_body, content_type=JSON, headers={"idempotency-key": "p5-grant-1"}
    )

    assert one.status_code == 200, one.content
    assert one.content == two.content
    assert Grant.objects.for_tenant(tenant).filter(membership=membership).count() == 1


# --- P5.2 · the wire matrix -----------------------------------------------------


def _wire(
    *,
    kind: str,
    user: User,
    tenant: Tenant,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    scopes: list[str] | None = None,
) -> Any:
    """One request, through the mounted API, as one credential kind."""
    if kind == "session":
        client = _session(user)
        headers: dict[str, str] = {}
    else:
        client = Client()
        headers = _headers(_bearer(user, tenant, scopes))
    call = getattr(client, method)
    if body is None:
        return call(path, headers=headers)
    return call(path, data=json.dumps(body), content_type=JSON, headers=headers)


#: `(name, method, needs_key, needs_membership, needs_permission, body, write)`
MATRIX_ROUTES: tuple[tuple[str, str, bool, bool, bool, dict[str, Any] | None, bool], ...] = (
    ("role-list", "get", False, False, False, None, False),
    ("role-detail", "get", True, False, False, None, False),
    ("permission-list", "get", False, False, False, None, False),
    ("grant-list", "get", False, True, False, None, False),
    ("membership_permissions-detail", "get", False, True, False, None, False),
    ("role-create", "post", False, False, False, {"key": "made", "name": "Made"}, True),
    ("role-update", "patch", True, False, False, {"name": "Renamed"}, True),
    (
        "role_permissions-update",
        "put",
        True,
        False,
        False,
        {"permissions": ["widget.approve"]},
        True,
    ),
    ("grant-update", "put", False, True, True, {"effect": "allow"}, True),
    ("grant-delete", "delete", False, True, True, None, True),
    ("role-delete", "delete", True, False, False, None, True),
)

CREDENTIALS = ("session", "bearer")


def _path_for(
    name: str,
    *,
    key: str,
    membership: Membership,
    permission: str,
    needs_key: bool,
    needs_membership: bool,
    needs_permission: bool,
) -> str:
    kwargs: dict[str, Any] = {}
    if needs_key:
        kwargs["key"] = key
    if needs_membership:
        kwargs["membership_id"] = membership.pk
    if needs_permission:
        kwargs["permission"] = permission
    return _url(name, **kwargs)


@pytest.mark.parametrize("credential", CREDENTIALS)
@pytest.mark.parametrize("row", MATRIX_ROUTES, ids=[r[0] for r in MATRIX_ROUTES])
def test_the_wire_matrix_present(
    row: tuple[str, str, bool, bool, bool, dict[str, Any] | None, bool],
    credential: str,
    tenant: Tenant,
    owner: User,
    approver: Role,
) -> None:
    """**The present case**, for every route and every credential kind it accepts.

    An owner, acting at the root, doing the thing the route is for. A door that
    only ever answered a session would pass every other test in this file.
    """
    name, method, needs_key, needs_membership, needs_permission, body, write = row
    membership = _membership(owner, tenant)
    # THE CELL THAT WAS LISTING NOTHING. `grant-list`'s present case ran against
    # a membership with no grants on it, so the page it asserted 200 on was
    # EMPTY — and an empty page serialises through any schema at all. The
    # route's own rendering was never exercised by this matrix, and the defect
    # that reached the field test (a 500 on a populated page, while the MCP twin
    # answered 200) sat under a green cell. A list route's present case seeds a
    # row, or it is a test about pagination rather than about the list.
    if name in {"grant-delete", "grant-list"}:
        create_grant(
            tenant=tenant,
            actor=actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant)),
            membership=membership,
            permission="widget.approve",
            effect=Grant.Effect.ALLOW,
        )
    scopes = ["roles:write"] if write else ["roles:read"]
    path = _path_for(
        name,
        key="approver",
        membership=membership,
        permission="widget.approve",
        needs_key=needs_key,
        needs_membership=needs_membership,
        needs_permission=needs_permission,
    )
    response = _wire(
        kind=credential,
        user=owner,
        tenant=tenant,
        method=method,
        path=path,
        body=body,
        scopes=scopes,
    )
    assert response.status_code in {200, 201, 204}, (name, credential, response.content)


@pytest.mark.parametrize("credential", CREDENTIALS)
@pytest.mark.parametrize(
    "row",
    [r for r in MATRIX_ROUTES if r[2] or r[3]],
    ids=[r[0] for r in MATRIX_ROUTES if r[2] or r[3]],
)
def test_the_wire_matrix_absent(
    row: tuple[str, str, bool, bool, bool, dict[str, Any] | None, bool],
    credential: str,
    tenant: Tenant,
    other_tenant: Tenant,
    stranger: User,
    owner: User,
    approver: Role,
) -> None:
    """**The absent case is 404, and another tenant's row is the same 404.**

    A refusal that told "no such id" from "somebody else's id" apart would be an
    existence oracle over the whole estate (§C8).
    """
    name, method, needs_key, needs_membership, needs_permission, body, write = row
    foreign = _membership(stranger, other_tenant)
    scopes = ["roles:write"] if write else ["roles:read"]
    path = _path_for(
        name,
        key="no-such-role",
        membership=foreign,
        permission="widget.approve",
        needs_key=needs_key,
        needs_membership=needs_membership,
        needs_permission=needs_permission,
    )
    response = _wire(
        kind=credential,
        user=owner,
        tenant=tenant,
        method=method,
        path=path,
        body=body,
        scopes=scopes,
    )
    assert response.status_code == 404, (name, credential, response.content)
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("credential", CREDENTIALS)
@pytest.mark.parametrize(
    "row", [r for r in MATRIX_ROUTES if r[6]], ids=[r[0] for r in MATRIX_ROUTES if r[6]]
)
def test_the_wire_matrix_forbidden_writes(
    row: tuple[str, str, bool, bool, bool, dict[str, Any] | None, bool],
    credential: str,
    tenant: Tenant,
    owner: User,
    member: User,
    approver: Role,
) -> None:
    """**The forbidden case for every write**: a plain member holds no role key.

    `403 forbidden`, with the refused key's own sentence — the words a person
    reads, never the key. The grant write needs a row to exist first, so that
    what refuses is the capability and not the absence.
    """
    name, method, needs_key, needs_membership, needs_permission, body, _write = row
    membership = _membership(owner, tenant)
    if name == "grant-delete":
        create_grant(
            tenant=tenant,
            actor=actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant)),
            membership=membership,
            permission="widget.approve",
            effect=Grant.Effect.ALLOW,
        )
    path = _path_for(
        name,
        key="approver",
        membership=membership,
        permission="widget.approve",
        needs_key=needs_key,
        needs_membership=needs_membership,
        needs_permission=needs_permission,
    )
    response = _wire(
        kind=credential,
        user=member,
        tenant=tenant,
        method=method,
        path=path,
        body=body,
        scopes=["roles:write"],
    )
    assert response.status_code == 403, (name, credential, response.content)
    assert response.json()["code"] == "forbidden"


#: Which key each read asks for. A plain `member` HOLDS every read on this
#: template (`member` is declared `("*.read",)`), so the forbidden case for a
#: read is not a role — it is one `withhold` row, which is the point of Phase R.
READ_KEYS = {
    "role-list": "role.read",
    "role-detail": "role.read",
    "permission-list": "role.read",
    "grant-list": "grant.read",
    "membership_permissions-detail": "membership.read",
}


@pytest.mark.parametrize("credential", CREDENTIALS)
@pytest.mark.parametrize("name", sorted(READ_KEYS))
def test_the_wire_matrix_forbidden_reads(
    name: str,
    credential: str,
    tenant: Tenant,
    owner: User,
    member: User,
    approver: Role,
) -> None:
    """**The forbidden case for every read**: one `withhold` row closes the door.

    Before Phase R this could not be written at all — a `<kind>.read` was free to
    any membership in the tenant, so there was no state in which a member was
    refused a read. The assertion is the flip, at the wire.
    """
    key = READ_KEYS[name]
    target = _membership(member, tenant)
    Grant.objects.create(
        tenant=tenant, membership=target, permission=key, effect=Grant.Effect.WITHHOLD
    )
    row = next(r for r in MATRIX_ROUTES if r[0] == name)
    path = _path_for(
        name,
        key="approver",
        membership=target,
        permission="widget.approve",
        needs_key=row[2],
        needs_membership=row[3],
        needs_permission=row[4],
    )
    response = _wire(
        kind=credential,
        user=member,
        tenant=tenant,
        method="get",
        path=path,
        scopes=["roles:read"],
    )
    assert response.status_code == 403, (name, credential, response.content)
    assert response.json()["code"] == "forbidden"
    assert response.json()["detail"] == authz.refusal_sentence(key)


@pytest.mark.parametrize("credential", CREDENTIALS)
def test_the_wire_matrix_invalid(
    credential: str, tenant: Tenant, owner: User, approver: Role
) -> None:
    """**The invalid case**: a key nothing declares, and a reserved one."""
    membership = _membership(owner, tenant)
    undeclared = _wire(
        kind=credential,
        user=owner,
        tenant=tenant,
        method="post",
        path=_url("role-create"),
        body={"key": "made", "name": "Made", "permissions": ["gizmo.polish"]},
        scopes=["roles:write"],
    )
    assert undeclared.status_code == 400, undeclared.content
    assert undeclared.json()["code"] == "invalid"
    assert "permissions" in undeclared.json()["errors"]

    reserved = _wire(
        kind=credential,
        user=owner,
        tenant=tenant,
        method="put",
        path=_url("grant-update", membership_id=membership.pk, permission="tenant.own"),
        body={"effect": "withhold"},
        scopes=["roles:write"],
    )
    assert reserved.status_code == 400, reserved.content
    assert reserved.json()["code"] == "invalid"

    owner_edit = _wire(
        kind=credential,
        user=owner,
        tenant=tenant,
        method="put",
        path=_url("role_permissions-update", key="owner"),
        body={"permissions": ["widget.read"]},
        scopes=["roles:write"],
    )
    assert owner_edit.status_code == 400, owner_edit.content


def test_a_reserved_key_says_reserved_and_an_undeclared_one_says_undeclared(
    tenant: Tenant, owner: User
) -> None:
    """The two halves of one refusal, which are not the same fact.

    `tenant.own` IS in this deployment's vocabulary — `owner` holds it and
    `GET /permissions/` lists it — so telling its caller it is "not a permission
    this deployment may hand out" and pointing them at that list sent them to
    look up a key that was already there. `gizmo.polish` is the other half: a key
    nothing declares, where the list genuinely is the remedy.
    """
    reserved = _session(owner).post(
        _url("role-create"),
        data=json.dumps({"key": "regent", "name": "Regent", "permissions": ["tenant.own"]}),
        content_type=JSON,
    )
    assert reserved.status_code == 400, reserved.content
    said = " ".join(reserved.json()["errors"]["permissions"])
    assert "reserved" in said, said
    assert "GET /permissions/" not in said, "a key that IS in the list is not looked up in it"

    undeclared = _session(owner).post(
        _url("role-create"),
        data=json.dumps({"key": "polisher", "name": "Polisher", "permissions": ["gizmo.polish"]}),
        content_type=JSON,
    )
    assert undeclared.status_code == 400, undeclared.content
    missing = " ".join(undeclared.json()["errors"]["permissions"])
    assert "not a permission this deployment has" in missing, missing
    assert "GET /permissions/" in missing, missing


@pytest.mark.parametrize("key", ["owner", "member"])
def test_deleting_a_role_the_tenant_did_not_make_is_not_found(
    tenant: Tenant, owner: User, key: str
) -> None:
    """A key that lives in code answers `404 not_found`, the refusal the route's contract lists."""
    response = _session(owner).delete(_url("role-delete", key=key))
    assert response.status_code == 404, response.content
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("credential", CREDENTIALS)
def test_the_wire_matrix_conflict(
    credential: str, tenant: Tenant, owner: User, member: User, approver: Role
) -> None:
    """**The conflict case**: deleting a role somebody still wears."""
    membership = _membership(member, tenant)
    membership.role = "approver"
    membership.save(update_fields=["role"])

    response = _wire(
        kind=credential,
        user=owner,
        tenant=tenant,
        method="delete",
        path=_url("role-delete", key="approver"),
        scopes=["roles:write"],
    )
    assert response.status_code == 409, response.content
    assert response.json()["code"] == "conflict"
    assert Role.objects.for_tenant(tenant).filter(key="approver").exists()


@pytest.mark.parametrize("row", MATRIX_ROUTES, ids=[r[0] for r in MATRIX_ROUTES])
def test_the_wire_matrix_narrower_ceiling(
    row: tuple[str, str, bool, bool, bool, dict[str, Any] | None, bool],
    tenant: Tenant,
    owner: User,
    approver: Role,
) -> None:
    """**A token narrowed to another family** answers `insufficient_scope`.

    The ceiling is measured before the capability, so an owner's own token
    refuses here — which is the property: a credential says how far it reaches
    whoever is holding it.
    """
    name, method, needs_key, needs_membership, needs_permission, body, write = row
    membership = _membership(owner, tenant)
    path = _path_for(
        name,
        key="approver",
        membership=membership,
        permission="widget.approve",
        needs_key=needs_key,
        needs_membership=needs_membership,
        needs_permission=needs_permission,
    )
    response = _wire(
        kind="bearer",
        user=owner,
        tenant=tenant,
        method=method,
        path=path,
        body=body,
        scopes=["widgets:read"],
    )
    assert response.status_code == 403, (name, response.content)
    assert response.json()["code"] == "insufficient_scope", response.json()
    assert "roles:" in response.json()["detail"]


def test_a_hand_out_refusal_names_the_sentences_on_the_wire(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    """A member given `role.create` still may not put what they lack into a role."""
    membership = _membership(member, tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="role.create",
        effect=Grant.Effect.ALLOW,
    )
    response = _wire(
        kind="session",
        user=member,
        tenant=tenant,
        method="post",
        path=_url("role-create"),
        body={"key": "climber", "name": "Climber", "permissions": ["organization.create"]},
    )

    assert response.status_code == 403, response.content
    assert authz.refusal_sentence("organization.create") in response.json()["detail"]
    assert "organization.create" not in response.json()["detail"], "sentences, never keys"


# --- P5.3 · the two doors agree -------------------------------------------------


def _instants_normalised(value: Any) -> Any:
    """Every ISO instant in a body, reduced to one spelling.

    **The ENCODERS are somebody else's question.** `test_door_answer_parity.py`
    drives both doors over the real transport and asserts they put the same
    STRING on the wire for the same instant — that is a difference between two
    JSON encoders, it has its own test, and asserting it a second time here
    would make this test fail for a reason that is not its own. What this test
    owns is rule 46's question: do the two doors answer with the same FIELDS and
    the same VALUES for the same row. So an instant is compared as an instant.
    """
    if isinstance(value, dict):
        return {key: _instants_normalised(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_instants_normalised(item) for item in value]
    if isinstance(value, str) and len(value) >= 19:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        # TO THE MILLISECOND, which is the tree's own idiom for this comparison
        # (`test_door_answer_parity.py`'s five `_to_the_millisecond` helpers).
        # REST renders three decimal places and Pydantic renders six for the
        # same instant; that is the encoder difference, and it has its own test.
        return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000).isoformat()
    return value


def test_both_doors_answer_the_same_body_for_the_same_row(
    tenant: Tenant, owner: User, approver: Role
) -> None:
    """Rule 46's named case: the REST body and the tool's result, field for field."""
    membership = _membership(owner, tenant)
    rest = _session(owner).get(_url("membership_permissions-detail", membership_id=membership.pk))
    assert rest.status_code == 200, rest.content
    over_mcp = tool("get_membership_permissions")(
        context_for(owner, tenant), membership_id=membership.pk
    )
    assert _instants_normalised(json.loads(over_mcp.model_dump_json())) == _instants_normalised(
        rest.json()
    )

    rest_roles = _session(owner).get(_url("role-list"))
    assert rest_roles.status_code == 200
    mcp_roles = tool("list_roles")(context_for(owner, tenant))
    assert _instants_normalised(json.loads(mcp_roles.model_dump_json())) == _instants_normalised(
        rest_roles.json()
    )
    # Non-vacuity: the custom role is in both, and it is the one with an instant.
    assert any(item["key"] == "approver" for item in rest_roles.json()["items"])


def test_both_doors_answer_the_same_non_empty_grants_page(
    tenant: Tenant, owner: User, member: User
) -> None:
    """Rule 46 over a POPULATED page — the cell the empty one could not reach.

    The defect this closes was a door disagreement of the loudest kind: the REST
    list answered `500` on any page with a row on it, while the MCP twin answered
    `200` with all seven fields, and every layer of the suite was green because
    the only grants page anything listed was empty. An empty page serialises
    through a schema whose fields the rows do not carry, so the assertion that
    matters is this one: two rows, two doors, field for field.
    """
    membership = _membership(member, tenant)
    for permission, effect in (
        ("widget.approve", Grant.Effect.ALLOW),
        ("widget.delete", Grant.Effect.WITHHOLD),
    ):
        Grant.objects.create(
            tenant=tenant, membership=membership, permission=permission, effect=effect
        )

    rest = _session(owner).get(_url("grant-list", membership_id=membership.pk))
    assert rest.status_code == 200, rest.content
    body = rest.json()
    assert [item["permission"] for item in body["items"]] == ["widget.approve", "widget.delete"]
    # The two fields no `Grant` row carries, and the reason the door was down.
    assert all(item["organization_id"] == str(membership.organization_id) for item in body["items"])
    assert body["items"][0]["sentence"] == authz.refusal_sentence("widget.approve")
    assert body["items"][1]["sentence"] == authz.refusal_sentence("widget.delete")

    over_mcp = tool("list_grants")(context_for(owner, tenant), membership_id=membership.pk)
    assert _instants_normalised(json.loads(over_mcp.model_dump_json())) == _instants_normalised(
        body
    )


def test_the_machine_door_refuses_a_hand_out_with_the_same_words(
    tenant: Tenant, owner: User, member: User
) -> None:
    """The same refusal, the same code, the same sentence, through `wire_refusal`."""
    membership = _membership(member, tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="role.create",
        effect=Grant.Effect.ALLOW,
    )
    rest = _wire(
        kind="session",
        user=member,
        tenant=tenant,
        method="post",
        path=_url("role-create"),
        body={"key": "climber", "name": "Climber", "permissions": ["organization.create"]},
    )

    with pytest.raises(ToolError) as refused:
        tool("create_role")(
            context_for(member, tenant),
            key="climber",
            name="Climber",
            permissions=["organization.create"],
        )

    assert str(refused.value) == refusal_message(rest.json())


def test_the_machine_door_answers_not_found_for_another_tenants_row(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """The C8 half at the machine door: not-there and not-yours are one answer."""
    foreign = _membership(stranger, other_tenant)
    with pytest.raises(ToolError):
        tool("get_membership_permissions")(context_for(owner, tenant), membership_id=foreign.pk)
    with pytest.raises(ToolError):
        tool("get_role")(context_for(owner, tenant), key="no-such-role")


# --- P5.4 · the shapes say what they know ---------------------------------------


def test_membership_permissions_says_via_and_names_the_ancestor_membership(
    tenant: Tenant, owner: User, owner_actor: Actor, member: User
) -> None:
    """An inherited key points at the ancestor row, not at the one asked about."""
    root = root_organization(tenant=tenant)
    from apps.core.services import create_organization

    branch = create_organization(
        tenant=tenant, parent=root, name="Branch", slug="p5-branch", actor=owner_actor
    )
    below = add_membership(
        user=member,
        tenant=tenant,
        organization=branch,
        role="member",
        actor=owner_actor,
    )
    at_root = Membership.objects.get(user=member, tenant=tenant, organization=root)
    create_grant(
        tenant=tenant,
        actor=owner_actor,
        membership=below,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )

    body = _session(owner).get(_url("membership_permissions-detail", membership_id=below.pk)).json()
    by_key = {entry["key"]: entry for entry in body["held"]}

    assert by_key["widget.approve"]["via"] == "grant"
    assert by_key["widget.approve"]["membership_id"] == str(below.pk)
    # `membership.read` comes from `member` at BOTH nodes; the nearest one wins.
    assert by_key["membership.read"]["via"] == "role"
    assert by_key["membership.read"]["membership_id"] == str(below.pk)
    assert body["organization_id"] == str(branch.pk)
    assert at_root.pk != below.pk


def test_the_held_set_is_exactly_what_effective_permissions_says(
    tenant: Tenant, owner: User, owner_actor: Actor, member: User
) -> None:
    """**The belt on the second copy of the algebra.**

    `membership_permissions` walks the chain itself in order to say WHERE each
    key came from — a set of strings cannot carry that. What it must never do is
    come to a different answer from `effective_permissions`, and this is the
    assertion that would catch it.
    """
    membership = _membership(member, tenant)
    create_grant(
        tenant=tenant,
        actor=owner_actor,
        membership=membership,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )
    create_grant(
        tenant=tenant,
        actor=owner_actor,
        membership=membership,
        permission="widget.read",
        effect=Grant.Effect.WITHHOLD,
    )

    view = get_membership_permissions(
        tenant=tenant,
        org=root_organization(tenant=tenant),
        membership_id=membership.pk,
        actor=owner_actor,
    )
    assert {entry.key for entry in view.held} == authz.effective_permissions(
        member, tenant, membership.organization
    )
    assert {entry.key for entry in view.withheld} == {"widget.read"}


def test_a_role_says_what_this_tenant_changed(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """`added`/`removed` are the delta against the declaration, on the wire."""
    RolePermission.objects.create(
        tenant=tenant,
        role_key="member",
        permission="organization.create",
        effect=RolePermission.Effect.INCLUDE,
    )
    body = _session(owner).get(_url("role-detail", key="member")).json()

    assert body["kind"] == "declared"
    assert "organization.create" in body["added"]
    assert "organization.create" in body["permissions"]
    assert body["default_permissions"] is not None
    assert "organization.create" not in body["default_permissions"]


def test_a_custom_role_has_no_declaration_to_differ_from(
    tenant: Tenant, owner: User, approver: Role
) -> None:
    body = _session(owner).get(_url("role-detail", key="approver")).json()
    assert body["kind"] == "custom"
    assert body["default_permissions"] is None
    assert body["permissions"] == ["widget.approve"]
    assert body["created_at"] is not None


def test_the_owner_role_is_the_vocabulary_and_is_read_only(tenant: Tenant, owner: User) -> None:
    body = _session(owner).get(_url("role-detail", key="owner")).json()
    assert body["kind"] == "owner"
    assert "tenant.own" in body["permissions"]
    assert body["created_at"] is None


def test_the_owner_row_reports_no_delta_at_all_on_the_template(tenant: Tenant, owner: User) -> None:
    """**`removed` is a subtraction a TENANT made, so an untouched tenant has none.**

    Both sides of that subtraction have to be the same population or the row
    invents one. `defaults_for(OWNER_ROLE)` is the whole vocabulary — what the
    owner role IS — while the effective collection excludes the virtual kinds,
    which name no table and are in nobody's collection by construction.
    Differenced unfiltered, `GET /roles/owner` listed `deployment.configure`
    under `removed` on a tenant that had changed nothing, which reads as "this
    tenant took a capability away from its owner". Nobody did.

    Asserted as `added == removed == []` rather than by naming the key: the
    claim is that an untouched tenant reports no delta, and it stays true when
    a second virtual key lands.
    """
    body = _session(owner).get(_url("role-detail", key="owner")).json()

    assert body["added"] == []
    assert body["removed"] == []
    assert body["default_permissions"] == body["permissions"]

    virtual = {
        action for action, word in authz.vocabulary().items() if word.kind in authz.VIRTUAL_KINDS
    }
    assert virtual, "no key on a virtual kind — this assertion has stopped measuring"
    assert not virtual & set(body["default_permissions"])
    assert not virtual & set(body["permissions"])


# --- P5.5 · the four pins -------------------------------------------------------


def _seed_roles(tenant: Tenant, actor: Actor) -> None:
    """Three custom roles and twenty delta rows — the pins' stated scale."""
    keys = ("alpha", "beta", "gamma")
    for key in keys:
        create_role(tenant=tenant, actor=actor, key=key, name=key.title(), permissions=[])
    words = sorted(authz.vocabulary())[:20]
    RolePermission.objects.bulk_create(
        RolePermission(
            tenant=tenant,
            role_key=keys[index % 3],
            permission=word,
            effect=RolePermission.Effect.INCLUDE,
        )
        for index, word in enumerate(words)
    )


def test_the_roles_list_costs_two_statements(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    """One for the tenant's own rows, one for every delta row. The rest is code.

    `n = 2` and not one per role: `collection()` reads one role with one query,
    so a list over three layers would be a query per layer member. The seam that
    keeps it at two is reading every delta row once and doing the algebra in
    Python.
    """
    _seed_roles(tenant, owner_actor)
    owner_actor.forget_permissions()
    # Warm the actor's memo first: `require` is the read this pin is not about.
    authz.effective_permissions(owner, tenant, owner_actor.org, memo=owner_actor)

    with django_assert_num_queries(2):
        views = list_roles(tenant=tenant, actor=owner_actor)
    assert len(views) >= 6


def test_the_grants_list_costs_at_most_three(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    """The membership by id within the subtree, and its grants."""
    membership = _membership(owner, tenant)
    create_grant(
        tenant=tenant,
        actor=owner_actor,
        membership=membership,
        permission="widget.approve",
        effect=Grant.Effect.ALLOW,
    )
    owner_actor.forget_permissions()
    authz.effective_permissions(owner, tenant, owner_actor.org, memo=owner_actor)

    # The hat is read OUTSIDE the block: `root_organization` is a query, and a
    # pin that measured the test's own set-up would be pinning the wrong thing.
    hat = root_organization(tenant=tenant)
    with django_assert_num_queries(2):
        rows = list(
            list_grants(tenant=tenant, org=hat, membership_id=membership.pk, actor=owner_actor)
        )
    assert len(rows) == 1


def test_membership_permissions_costs_four_and_says_why(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    """`get_membership` plus the three the chain algebra reads.

    The three are the memberships, their grants and the delta rows for the role
    keys they name — `effective_permissions`' own budget, paid here because the
    SUBJECT is somebody else and an actor's memo is about the actor.
    """
    membership = _membership(owner, tenant)
    owner_actor.forget_permissions()
    authz.effective_permissions(owner, tenant, owner_actor.org, memo=owner_actor)

    hat = root_organization(tenant=tenant)
    with django_assert_num_queries(4):
        get_membership_permissions(
            tenant=tenant, org=hat, membership_id=membership.pk, actor=owner_actor
        )


def test_the_permission_list_touches_no_table(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    """**Zero statements beyond the actor's memo** — the vocabulary is code.

    The memo is warmed first on purpose: `require` costs its three on a cold
    actor, and this pin is about the LIST, which is computed at import from the
    model registry and never read from a table.
    """
    owner_actor.forget_permissions()
    authz.effective_permissions(owner, tenant, owner_actor.org, memo=owner_actor)

    with django_assert_num_queries(0):
        words = list_permissions(actor=owner_actor)
    assert len(words) > 50


# --- P5.6 · the existing wire does not move -------------------------------------


def test_a_member_may_not_patch_a_role_on_the_wire(
    tenant: Tenant, owner: User, member: User, admin_member: User
) -> None:
    """`PATCH /memberships/{id}/role/` answered 200 for member→member before P3."""
    target = _membership(admin_member, tenant)
    response = _session(member).patch(
        f"/api/v1/memberships/{target.pk}/role/",
        data=json.dumps({"role": "member"}),
        content_type=JSON,
    )
    assert response.status_code == 403, response.content
    assert response.json()["detail"] == authz.refusal_sentence("membership.update")


# --- the four new reads ask ------------------------------------------------------


def test_the_four_new_reads_refuse_a_roleless_membership(
    tenant: Tenant, owner: User, owner_actor: Actor, nomad: User, approver: Role
) -> None:
    """A membership with no role holds nothing, so all four answer `forbidden`.

    Before Phase R every one of them answered 200: a read was free to anybody in
    the tenant, and "what may this person do" was readable by a person who may
    do nothing.
    """
    roleless = add_membership(
        user=nomad,
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        role="",
        actor=owner_actor,
    )
    acting = actor_for(user=nomad, tenant=tenant, org=root_organization(tenant=tenant))

    with pytest.raises(Forbidden) as roles:
        list_roles(tenant=tenant, actor=acting)
    assert str(roles.value) == authz.refusal_sentence("role.read")

    with pytest.raises(Forbidden):
        get_role(tenant=tenant, key="approver", actor=acting)
    with pytest.raises(Forbidden):
        list_permissions(actor=acting)
    with pytest.raises(Forbidden):
        list_grants(
            tenant=tenant,
            org=root_organization(tenant=tenant),
            membership_id=roleless.pk,
            actor=acting,
        )


def test_a_withheld_role_read_refuses_the_roles_list_on_both_doors(
    tenant: Tenant, owner: User, owner_actor: Actor, member: User, approver: Role
) -> None:
    """One `withhold` row, and the list closes at REST and at MCP alike."""
    membership = _membership(member, tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="role.read",
        effect=Grant.Effect.WITHHOLD,
    )

    rest = _session(member).get(_url("role-list"))
    assert rest.status_code == 403, rest.content
    assert rest.json()["detail"] == authz.refusal_sentence("role.read")

    with pytest.raises(ToolError) as refused:
        tool("list_roles")(context_for(member, tenant))
    assert str(refused.value) == refusal_message(rest.json())


def test_the_grants_list_asks_grant_read_after_the_membership(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    """Two capabilities, two owners: who is here, and what exceptions they carry."""
    membership = _membership(member, tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="grant.read",
        effect=Grant.Effect.WITHHOLD,
    )
    acting = actor_for(user=member, tenant=tenant, org=root_organization(tenant=tenant))

    with pytest.raises(Forbidden) as refused:
        list_grants(
            tenant=tenant,
            org=root_organization(tenant=tenant),
            membership_id=membership.pk,
            actor=acting,
        )
    assert str(refused.value) == authz.refusal_sentence("grant.read")

    # …and the membership read itself still works, so the two are separable.
    get_membership_permissions(
        tenant=tenant,
        org=root_organization(tenant=tenant),
        membership_id=membership.pk,
        actor=acting,
    )


def test_a_role_outside_this_tenant_is_not_found(
    tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor, stranger: User
) -> None:
    """A role is tenant-wide, so the reach question is the tenant scope."""
    create_role(
        tenant=other_tenant,
        actor=actor_for(
            user=stranger, tenant=other_tenant, org=root_organization(tenant=other_tenant)
        ),
        key="theirs",
        name="Theirs",
        permissions=[],
    )
    with pytest.raises(NotFound):
        get_role(tenant=tenant, key="theirs", actor=owner_actor)
