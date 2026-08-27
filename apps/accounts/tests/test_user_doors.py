"""Erasure and deactivation, driven through both doors.

Until this fix the two most consequential acts in the product — take somebody's
access away, and anonymise them for good — were reachable only from a Python
shell. `erase_user` was one of the four names in accounts' house-rule-42 census,
which is the rule's whole complaint said about the worst possible service: built,
tested, audited, and indistinguishable from never having been written by anybody
who was not holding a shell.

What this file pins:

* the doors exist and answer where the router says they do;
* **the wall is the service's**, not the door's — a member is refused the same
  way over REST and over MCP, and the two refusals are compared **byte for
  byte** rather than described as similar (E9);
* the credential really stops working: the erased person's token 401s on the
  next request, and the deactivated person's socket is asked to close through
  the SEC-R1 kick seam rather than left to notice;
* every drive leaves an audit row that names the act and the door it came
  through, and a **refused** drive leaves the refusal row `@service` writes and
  no other.

**What it deliberately does not pin** (ADO-7, and the route docstrings say it
too): whether `erase_user`'s sweep is *complete*. These tests are about the
contract of the door in front of it. Wave C deepens the sweep, and the trigger
it carries is that this file should still pass byte-unchanged afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from django.test import Client
from django.urls import reverse
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.mcp import register
from apps.accounts.models import ApiToken, User
from apps.accounts.services import (
    KICK_USER_DEACTIVATED,
    KICK_USER_ERASED,
    create_user,
    issue_token,
)
from apps.core import bridge, context
from apps.core.actor import actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import refusal_message
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, root_organization

pytestmark = pytest.mark.django_db

JSON = "application/json"
PASSWORD = "a-long-enough-password"  # pragma: allowlist secret

ME_DEACTIVATE = "/api/v1/users/me/deactivate/"
ME_ERASE = "/api/v1/users/me/erase/"
#: An authenticated GET that exists, used to ask "does this credential still
#: work" over the wire rather than by re-reading the row it was resolved from.
PROBE_URL = "/api/v1/auth/sso-connections/"


def deactivate_url(user: User) -> str:
    return f"/api/v1/users/{user.pk}/deactivate/"


def erase_url(user: User) -> str:
    return f"/api/v1/users/{user.pk}/erase/"


def body_of(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


# --- A tool call, without a transport -----------------------------------------
# The same shape `apps/comms/tests/test_mcp.py` uses, for the same reason: the
# tool functions are the door, and driving them directly is what lets a REST
# response and a tool result be compared inside one test.


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant | None, org: Organization | None = None) -> Context[Any]:
    resolved = org if org is not None else (root_organization(tenant=tenant) if tenant else None)
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=resolved)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def tool(name: str) -> Callable[..., Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    registered = server._tool_manager.get_tool(name)
    assert registered is not None, f"{name} is not registered"
    return registered.fn


@pytest.fixture
def colleague(tenant: Tenant) -> User:
    """A third person in the tenant, at `member`.

    The `member` fixture is one half of the pair every authorization test needs;
    this is the other half of the pair *this* file needs — a member acting on a
    member is the case the wall has to refuse, and `member` against `owner` would
    have proved something weaker.
    """
    user = create_user(email="colleague@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def kicks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every `close_sockets` ask, recorded, with the real seam otherwise intact.

    Only the `KICK` name is diverted — `bridge.find` still answers for every
    other registered name, so nothing else in the request changes shape. What
    this proves is that the door's write reached the seam with the right person
    and the right reason on it; that the seam then closes a *real* socket is
    driven over a real connection in `test_socket_kick.py`, which is where the
    async harness lives.
    """
    recorded: list[dict[str, Any]] = []
    real_find = bridge.find

    def record(*, user_id: UUID, reason: str) -> None:
        recorded.append({"user_id": user_id, "reason": reason})

    def find(name: str) -> Any:
        return record if name == bridge.KICK else real_find(name)

    monkeypatch.setattr(bridge, "find", find)
    return recorded


# --- The doors are where the router says they are -----------------------------


def test_the_routes_are_where_the_router_put_them(member: User) -> None:
    """Named by `url_name`, which is what house rule 3 asks a new route's test for."""
    assert reverse("api:me-deactivate") == ME_DEACTIVATE
    assert reverse("api:me-erase") == ME_ERASE
    assert reverse("api:user-deactivate", args=[member.pk]) == deactivate_url(member)
    assert reverse("api:user-erase", args=[member.pk]) == erase_url(member)


def test_the_doors_are_shut_to_a_stranger(api: Client, member: User) -> None:
    """No session, no answer — before any policy is consulted."""
    for url in (ME_DEACTIVATE, ME_ERASE, deactivate_url(member), erase_url(member)):
        response = api.post(url, data="{}", content_type=JSON)
        assert response.status_code == 401, url


# --- B-ACCT-1: the self-serve deactivation, and the kick ----------------------


def test_deactivating_myself_answers_with_the_documented_body(
    api: Client,
    tenant: Tenant,
    member: User,
    kicks: list[dict[str, Any]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    """Before this fix, this path was a JSON 404:

        {"detail": "No route under this API matches that path.",
         "code": "not_found", "remedies": [...]}

    Now it is the person, as they now stand — `is_active` false, everything else
    where it was. A `member` does it, deliberately: the self clause of
    `policies.themselves_or_administers_the_whole_tenant` is what is under test,
    and an owner would have passed through the privileged half instead.
    """
    api.force_login(member)

    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(ME_DEACTIVATE, data="{}", content_type=JSON)

    assert response.status_code == 200, response.content
    body = body_of(response)
    assert body["id"] == str(member.pk)
    assert body["email"] == member.email
    assert body["is_active"] is False
    # Nothing is anonymised and nothing is revoked: this is the reversible half.
    member.refresh_from_db()
    assert member.is_active is False
    assert member.email == "member@example.com"
    assert Membership.objects.filter(user=member, tenant=tenant).exists()

    assert kicks == [{"user_id": member.pk, "reason": KICK_USER_DEACTIVATED}]


def test_a_deactivated_persons_token_stops_working_on_the_next_request(
    api: Client, tenant: Tenant, member: User
) -> None:
    """The credential stops, and the row does not.

    `authenticate_token` reads `is_active` before it resolves anybody, so the
    token a person minted before being deactivated is inert without having been
    revoked — which is what makes the act reversible.
    """
    _, plaintext = issue_token(
        user=member, tenant=tenant, name="laptop", actor=actor_for(user=member, tenant=tenant)
    )
    api.force_login(member)
    assert api.post(ME_DEACTIVATE, data="{}", content_type=JSON).status_code == 200

    api.logout()
    refused = api.get(PROBE_URL, headers={"Authorization": f"Bearer {plaintext}"})
    assert refused.status_code == 401
    assert ApiToken.objects.filter(user=member, revoked_at__isnull=True).exists()


def test_an_admin_deactivates_a_member_of_their_tenant(
    api: Client,
    admin_member: User,
    member: User,
    kicks: list[dict[str, Any]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The admin-initiated form: the same service, the privileged half of the wall."""
    api.force_login(admin_member)

    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(deactivate_url(member), data="{}", content_type=JSON)

    assert response.status_code == 200, response.content
    assert body_of(response)["is_active"] is False
    assert kicks == [{"user_id": member.pk, "reason": KICK_USER_DEACTIVATED}]


# --- B-ACCT-2: the wall, over both doors, byte for byte -----------------------


def test_a_member_may_not_erase_a_colleague_and_both_doors_say_so_identically(
    api: Client, tenant: Tenant, member: User, colleague: User
) -> None:
    """**B-ACCT-2, and the E9 artifact.**

    One capability, two doors, one refusal — compared rather than described.
    The REST body is what `config/api.py` sent; the tool's message is what
    `core.mcp.tool_call` rendered; `refusal_message` reads the first to produce
    the second, so this assertion fails the moment either door starts composing
    a refusal of its own.

    Both people are ordinary members of one tenant, so neither the tenant wall
    nor `get_member` is what refuses here: `authz.require` inside `erase_user`
    is, which is the half a door could have taken over and must not.
    """
    api.force_login(member)
    rest = api.post(erase_url(colleague), data="{}", content_type=JSON)
    assert rest.status_code == 403, rest.content
    rest_body = body_of(rest)
    assert rest_body["code"] == "forbidden"

    with pytest.raises(ToolError) as refused:
        tool("erase_user")(context_for(member, tenant), user_id=colleague.pk)

    assert str(refused.value) == refusal_message(rest_body), "one composer, two doors"

    colleague.refresh_from_db()
    assert colleague.email == "colleague@example.com"
    assert colleague.is_active is True


def test_a_member_may_not_deactivate_a_colleague_either(
    api: Client, tenant: Tenant, member: User, colleague: User
) -> None:
    """The reversible act meets the same wall, and says the same thing both ways."""
    api.force_login(member)
    rest = api.post(deactivate_url(colleague), data="{}", content_type=JSON)
    assert rest.status_code == 403, rest.content

    with pytest.raises(ToolError) as refused:
        tool("deactivate_user")(context_for(member, tenant), user_id=colleague.pk)

    assert str(refused.value) == refusal_message(body_of(rest))
    colleague.refresh_from_db()
    assert colleague.is_active is True


def test_an_admin_erases_a_member_of_their_subtree(
    api: Client,
    tenant: Tenant,
    admin_member: User,
    member: User,
    kicks: list[dict[str, Any]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The other half of the wall: an admin at the root reaches the whole tenant."""
    _, plaintext = issue_token(
        user=member, tenant=tenant, name="doomed", actor=actor_for(user=member, tenant=tenant)
    )
    api.force_login(admin_member)

    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(erase_url(member), data="{}", content_type=JSON)

    assert response.status_code == 200, response.content
    body = body_of(response)
    assert body["email"].startswith("erased+")
    assert body["email"].endswith(".invalid")
    assert body["is_active"] is False
    assert body["is_staff"] is False
    assert kicks == [{"user_id": member.pk, "reason": KICK_USER_ERASED}]

    # The token stops authenticating, driven rather than asserted about the row.
    api.logout()
    refused = api.get(PROBE_URL, headers={"Authorization": f"Bearer {plaintext}"})
    assert refused.status_code == 401

    # The membership stays — the audit trail has to keep reading.
    assert Membership.objects.filter(user=member, tenant=tenant).exists()


def test_somebody_elses_person_is_not_found_rather_than_forbidden(
    api: Client, owner: User, stranger: User
) -> None:
    """Not-there and not-yours are one answer, at the door as in the services.

    An id nobody holds and an id belonging to another tenant's owner must be
    indistinguishable, or an owner with a supply of ids can ask this door
    whether an account exists.
    """
    api.force_login(owner)
    theirs = api.post(erase_url(stranger), data="{}", content_type=JSON)
    nobody = api.post(f"/api/v1/users/{uuid4()}/erase/", data="{}", content_type=JSON)

    assert theirs.status_code == nobody.status_code == 404
    assert body_of(theirs) == body_of(nobody)
    stranger.refresh_from_db()
    assert stranger.is_active is True


def test_the_machine_door_erases_through_the_same_service(
    tenant: Tenant, owner: User, member: User
) -> None:
    """The tool is not a second implementation: the same wall, the same result."""
    result = tool("erase_user")(context_for(owner, tenant), user_id=member.pk)

    assert result.is_active is False
    assert result.email.startswith("erased+")
    member.refresh_from_db()
    assert member.email == result.email


# --- B-ACCT-3: G3, the audit rows --------------------------------------------


def test_a_rest_erasure_is_audited_as_a_rest_erasure(
    api: Client, tenant: Tenant, admin_member: User, member: User
) -> None:
    """**B-ACCT-3.** The act, the person, the door, and the outcome."""
    api.force_login(admin_member)
    assert api.post(erase_url(member), data="{}", content_type=JSON).status_code == 200

    row = AuditEntry.objects.get(action="accounts.erase_user")
    assert row.door == "rest"
    assert row.outcome == "ok"
    assert row.actor_user_id == admin_member.pk
    assert row.tenant_id == tenant.pk
    assert row.object_id == member.pk


def test_a_rest_deactivation_is_audited_too(
    api: Client, tenant: Tenant, member: User, kicks: list[dict[str, Any]]
) -> None:
    """The act that used to leave no trail at all.

    `deactivate_user` declared no `tenant` before this fix, so `@service` filed
    nothing (`core.service._declares_tenant`) — taking a person's access away
    was less audited than giving them a token. It declares one now.
    """
    api.force_login(member)
    assert api.post(ME_DEACTIVATE, data="{}", content_type=JSON).status_code == 200

    row = AuditEntry.objects.get(action="accounts.deactivate_user")
    assert row.door == "rest"
    assert row.outcome == "ok"
    assert row.actor_user_id == member.pk
    assert row.tenant_id == tenant.pk


def test_a_machine_door_erasure_is_audited_as_mcp(
    tenant: Tenant, owner: User, member: User
) -> None:
    """The same row, with `door=mcp` on it.

    The `door` value is bound by `config/mcp.py`'s token middleware, which is
    ASGI and not in the call path of a direct tool call — so the binding is
    reproduced here with the same `context.bound` the mount uses. What that
    makes this test is a pin on the audit row's *shape*, not on the mount; the
    mount's own binding is `config/mcp.py`'s to prove, and that boundary is
    declared rather than blurred.
    """
    with context.bound(door="mcp", actor_kind="agent"):
        tool("erase_user")(context_for(owner, tenant), user_id=member.pk)

    row = AuditEntry.objects.get(action="accounts.erase_user")
    assert row.door == "mcp"
    assert row.outcome == "ok"
    assert row.actor_user_id == owner.pk


def test_a_refused_erasure_leaves_the_refusal_row_and_nothing_else(
    api: Client, tenant: Tenant, member: User, colleague: User
) -> None:
    """A refusal is a fact worth keeping, and `@service` is the one thing keeping it.

    The row is written *outside* the transaction the service rolled back, which
    is why a refused act leaves a trail at all — and there is exactly one row,
    because no door writes a second one of its own.
    """
    api.force_login(member)
    assert api.post(erase_url(colleague), data="{}", content_type=JSON).status_code == 403

    rows = list(AuditEntry.objects.filter(action="accounts.erase_user"))
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert rows[0].error_code == "forbidden"
    assert rows[0].door == "rest"
    assert rows[0].actor_user_id == member.pk


# --- The contract, and the one text behind both doors -------------------------


#: Words that mean something inside this repository and nothing to a developer
#: holding an API key. The owner's ruling of 2026-08-23: the half above the
#: `---` divider is PUBLISHED — it is the OpenAPI description and the MCP tool's
#: description — so it is written for a stranger, and everything else goes below.
#: `contract_of` is what splits them, so this list is checkable rather than a
#: habit somebody has to remember.
HOUSE_WORDS = (
    "@service",
    "services.py",
    "policies.py",
    "selectors.py",
    "manage.py",
    "house rule",
    "the door",
    "machine door",
    "org-scoped",
    "tenant-scoped",
    "for_tenant",
    "authz",
    "ADR ",
    "ADO-",
    "the rung",
    "wave C",
)


def test_the_published_half_of_every_new_route_is_written_for_a_stranger() -> None:
    """The contract half is public API documentation, not a note to a maintainer.

    A description that explains itself in this repository's own vocabulary reads
    as documentation and is not: the person meeting it has an API key and no
    checkout, and "the machine door" or "`policies.py`" is a sentence they
    cannot act on. The divider is where that material belongs, and the workshop
    halves of these four routes are full of it.

    Scoped to this app's routes on purpose. Sweeping the prose already
    published is booked separately and doing it here would make this test
    fail for somebody else's line.
    """
    from apps.accounts.api import (
        deactivate_me_route,
        deactivate_user_route,
        erase_me_route,
        erase_user_route,
    )
    from apps.core.api.docs import contract_of, workshop_half

    for route in (deactivate_me_route, erase_me_route, deactivate_user_route, erase_user_route):
        contract = contract_of(route).lower()
        assert contract, route.__name__
        found = [word for word in HOUSE_WORDS if word.lower() in contract]
        assert not found, f"{route.__name__}'s published half says {found}"
        # And the divider is earning its keep rather than being decoration: each
        # of these routes has something real to say to the next maintainer.
        assert workshop_half(route.__doc__), f"{route.__name__} has an empty workshop half"


def test_both_doors_describe_the_capability_with_one_text() -> None:
    """House rule 41's one-docstring rule, asserted here rather than relied on.

    Rule 41's check skips this app — accounts carries a whole-app exemption
    under rule 17, and the twin check rides on the same list — so the standard
    the routes are born to is pinned by this test instead of by the engine.
    """
    from apps.accounts.api import deactivate_user_route, erase_user_route
    from apps.core.api.docs import contract_of

    for name, route in (
        ("deactivate_user", deactivate_user_route),
        ("erase_user", erase_user_route),
    ):
        server: MCPServer[Any] = MCPServer(name="test", version="1")
        register(server)
        registered = server._tool_manager.get_tool(name)
        assert registered is not None
        assert registered.description == contract_of(route)
        assert contract_of(route), f"{name}'s twin has no contract half to render"
