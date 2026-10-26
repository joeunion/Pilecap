"""The tenancy and hierarchy doors, through the door a person uses.

Thirteen `core` services could previously be reached from nothing. These
tests are about the four properties that make the doors safe rather than merely
present:

* **the hat decides what you see** — your hat's subtree, never a
  parent's and never a sibling's, and a sibling's id is `not_found` rather than
  `forbidden` so the tree cannot be used as an existence oracle;
* **the escalation wall holds at the door** — nobody grants above their own
  effective role, and nobody grants outside the part of the tree they hold one
  in;
* **the same write, sent twice, happens once** — `Idempotency-Key`, replayed;
* **every write leaves an audit row** naming the service and the door.

Plus the one property this router owes because of how it is mounted: its auth is
inherited from the API default rather than restated, because `apps.core` may not
import `apps.accounts`, so a test pins it instead of a reader having to trust it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.services import (
    add_membership,
    create_organization,
    invite_member,
    root_organization,
)
from apps.core.tests.wire import REQUEST_FIXED_QUERIES

pytestmark = pytest.mark.django_db

ORGANIZATIONS = "/api/v1/organizations/"
MEMBERSHIPS = "/api/v1/memberships/"
INVITATIONS = "/api/v1/invitations/"
SETTINGS = "/api/v1/settings/"
FLAGS = "/api/v1/flags/"
JSON = "application/json"


def _body(response: Any) -> Any:
    assert response["Content-Type"].startswith(JSON), response["Content-Type"]
    return response.json()


@pytest.fixture
def tree(tenant: Tenant, owner: User) -> dict[str, Organization]:
    """root → branch-a → sub-a1, and root → branch-b. The shape rule 24 needs.

    Built through the service, so the materialized paths are the real ones: a
    tree assembled with `Organization.objects.create` would have no paths and
    every subtree read in these tests would pass vacuously.
    """

    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    branch_a = create_organization(
        tenant=tenant, parent=root, name="Branch A", slug="branch-a", actor=acting
    )
    sub_a1 = create_organization(
        tenant=tenant, parent=branch_a, name="Sub A1", slug="sub-a1", actor=acting
    )
    branch_b = create_organization(
        tenant=tenant, parent=root, name="Branch B", slug="branch-b", actor=acting
    )
    return {"root": root, "a": branch_a, "a1": sub_a1, "b": branch_b}


@pytest.fixture
def branch_admin(tenant: Tenant, tree: dict[str, Organization], owner: User) -> User:
    """A person who administers branch A and nothing else."""
    from apps.accounts.services import create_user

    user = create_user(email="branch-admin@example.com", password="pw-for-tests-only")  # noqa: S106 — a throwaway password a test user is made with
    add_membership(
        user=user,
        tenant=tenant,
        organization=tree["a"],
        role=Membership.Role.ADMIN,
        is_default=True,
        actor=actor_for(user=owner, tenant=tenant, org=tree["root"]),
    )
    return user


# --- the mount itself ---------------------------------------------------------


def test_every_core_route_carries_auth_even_though_the_router_inherits_it() -> None:
    """House rule 3, pinned where this router cannot restate it.

    `apps.core` may not import `apps.accounts`, so this is the one router in the
    tree that does not write `auth=API_AUTH`. It inherits the API-level default
    instead — which ninja copies onto every operation — and that is only
    trustworthy if something checks. This is the something.
    """
    from apps.core.checks import _bound_operations

    core_operations = [
        operation
        for _prefix, operation in _bound_operations()
        if str(operation.view_func.__module__).startswith("apps.core.api")
    ]

    assert len(core_operations) == 28, [op.url_name for op in core_operations]
    for operation in core_operations:
        assert operation.auth_callbacks, operation.url_name


def test_an_anonymous_caller_is_refused(api: Client) -> None:
    """The other half of the same claim, over the wire rather than the registry."""
    assert api.get(ORGANIZATIONS).status_code == 401
    assert api.post(ORGANIZATIONS, data={}, content_type=JSON).status_code == 401


# --- visibility is the hat's, downward only -----------------------------------


def test_the_list_is_the_hats_subtree_and_nothing_above_it(
    api: Client, branch_admin: User, tree: dict[str, Organization]
) -> None:
    """Branch A's admin sees A and A1. Not the root, not B."""
    api.force_login(branch_admin)

    slugs = {row["slug"] for row in _body(api.get(ORGANIZATIONS))["items"]}

    assert slugs == {"branch-a", "sub-a1"}


def test_the_owner_sees_the_whole_tree(api: Client, owner: User, tree: dict[str, Any]) -> None:
    """The sibling half of the test above: acting at the root shows everything."""
    api.force_login(owner)

    slugs = {row["slug"] for row in _body(api.get(ORGANIZATIONS))["items"]}

    assert slugs == {tree["root"].slug, "branch-a", "sub-a1", "branch-b"}


def test_a_sibling_branch_is_not_found_and_never_forbidden(
    api: Client, branch_admin: User, tree: dict[str, Organization]
) -> None:
    """The org tree must not become an existence oracle.

    Branch B exists, and branch A's admin must not be able to learn that from
    the difference between two refusals.
    """
    api.force_login(branch_admin)

    response = api.get(f"{ORGANIZATIONS}{tree['b'].pk}/")
    invented = api.get(f"{ORGANIZATIONS}{uuid4()}/")

    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"
    assert invented.status_code == 404
    assert _body(response)["detail"] == _body(invented)["detail"]


def test_a_move_naming_a_sibling_answers_not_found(
    api: Client, branch_admin: User, tree: dict[str, Organization]
) -> None:
    """Naming an unreachable organization as a move target says nothing about it."""
    api.force_login(branch_admin)

    response = api.post(
        f"{ORGANIZATIONS}{tree['a1'].pk}/move/",
        data={"new_parent_id": str(tree["b"].pk)},
        content_type=JSON,
    )

    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"
    assert Organization.objects.get(pk=tree["a1"].pk).parent_id == tree["a"].pk


def test_another_tenants_rows_are_absent(
    api: Client, owner: User, tree: dict[str, Any], other_tenant: Tenant, stranger: User
) -> None:
    """The tenant sibling test. Without it every scoping test above could pass vacuously."""
    api.force_login(owner)

    slugs = {row["slug"] for row in _body(api.get(ORGANIZATIONS))["items"]}
    other_root = root_organization(tenant=other_tenant)

    assert other_root.slug not in slugs or other_root.tenant_id == tree["root"].tenant_id
    assert all(
        Organization.objects.get(slug=slug, tenant=tree["root"].tenant).tenant_id
        == tree["root"].tenant_id
        for slug in slugs
    )


# --- the escalation wall, at the door -----------------------------------------


def test_an_admin_cannot_promote_above_their_own_role(
    api: Client, branch_admin: User, tenant: Tenant, tree: dict[str, Organization], owner: User
) -> None:
    """The wall, and the row is unchanged afterwards."""
    from apps.accounts.services import create_user

    victim = create_user(email="victim@example.com", password="pw-for-tests-only")  # noqa: S106 — a throwaway password a test user is made with
    membership = add_membership(
        user=victim,
        tenant=tenant,
        organization=tree["a"],
        role=Membership.Role.MEMBER,
        actor=actor_for(user=owner, tenant=tenant, org=tree["root"]),
    )
    api.force_login(branch_admin)

    response = api.patch(
        f"{MEMBERSHIPS}{membership.pk}/role/",
        data={"role": Membership.Role.OWNER},
        content_type=JSON,
    )

    assert response.status_code == 403
    assert _body(response)["code"] == "forbidden"
    assert Membership.objects.get(pk=membership.pk).role == Membership.Role.MEMBER


def test_a_member_may_not_invite(api: Client, member: User) -> None:
    """`invitation.create` is the check that arrived with the door.

    The escalation wall alone would have let this through: a member granting
    `member` is not granting above themselves.
    """
    api.force_login(member)

    response = api.post(
        INVITATIONS, data={"email": "new@example.com", "role": "member"}, content_type=JSON
    )

    assert response.status_code == 403
    assert _body(response)["code"] == "forbidden"
    assert not Invitation.objects.filter(email="new@example.com").exists()


def test_a_member_may_not_rewrite_the_tenants_settings(
    api: Client, member: User, tenant: Tenant
) -> None:
    """`tenant.configure`, likewise. Before the door this service refused nobody."""
    api.force_login(member)

    response = api.put(SETTINGS, data={"timezone": "Europe/Lisbon"}, content_type=JSON)

    assert response.status_code == 403
    assert _body(response)["code"] == "forbidden"
    tenant.refresh_from_db()
    assert tenant.timezone == "UTC"


def test_a_branch_admin_may_not_configure_the_whole_tenant(
    api: Client, branch_admin: User, tenant: Tenant
) -> None:
    """Administering a branch is not a licence over everybody's configuration."""
    api.force_login(branch_admin)

    response = api.put(SETTINGS, data={"locale": "pt-pt"}, content_type=JSON)

    assert response.status_code == 403
    tenant.refresh_from_db()
    assert tenant.locale == "en-us"


# --- the persona's steps, and the standards they ride on ----------------------


def test_the_persona_can_set_up_a_team(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization]
) -> None:
    """Create a branch, invite somebody, set a flag — the whole point of the rung."""
    api.force_login(owner)

    created = api.post(
        ORGANIZATIONS,
        data={"parent_id": str(tree["root"].pk), "name": "Sales", "slug": "sales"},
        content_type=JSON,
    )
    assert created.status_code == 201, created.content
    assert _body(created)["slug"] == "sales"

    invited = api.post(
        INVITATIONS, data={"email": "teammate@example.com", "role": "member"}, content_type=JSON
    )
    assert invited.status_code == 201, invited.content
    assert _body(invited)["token"], "the token is returned exactly once"
    assert _body(invited)["invitation"]["email"] == "teammate@example.com"

    flagged = api.put(f"{FLAGS}beta/", data={"enabled": True}, content_type=JSON)
    assert flagged.status_code == 200, flagged.content
    assert _body(flagged)["flags"]["beta"] is True

    cleared = api.put(f"{FLAGS}beta/", data={"enabled": None}, content_type=JSON)
    # Clearing removes the tenant's opinion. `beta` is not a flag this deployment
    # declares a default for, so once the override is gone the flag is not a
    # thing at all — which is the honest answer, and a different one from False.
    assert "beta" not in _body(cleared)["flags"]


def test_a_token_is_never_on_the_invitation_list(api: Client, owner: User, tenant: Tenant) -> None:
    """The one shape that carries a credential is the issue response, and only it."""
    api.force_login(owner)
    api.post(INVITATIONS, data={"email": "listed@example.com"}, content_type=JSON)

    page = _body(api.get(f"{INVITATIONS}?include_count=true"))

    assert page["count"] == 1
    assert "token" not in page["items"][0]


def test_every_list_is_paginated_with_its_ordering_allow_list(
    api: Client, owner: User, tree: dict[str, Any]
) -> None:
    """E6 as ADR core-18 amended it: the envelope is `{items, has_more,
    next_cursor, count}` and `ordering` refuses what it did not offer.

    The key set is asserted exactly rather than field by field, because the
    whole of a hard cut is that `page` is not silently still accepted and
    `count` is not silently still computed.
    """
    api.force_login(owner)

    for url in (ORGANIZATIONS, MEMBERSHIPS, INVITATIONS):
        page = _body(api.get(url))
        assert set(page) == {"items", "has_more", "next_cursor", "count"}, url
        assert page["count"] is None, url

        refused = api.get(f"{url}?ordering=tenant__api_tokens__key_hash")
        assert refused.status_code == 400, url
        assert _body(refused)["code"] == "invalid", url


def test_the_same_write_sent_twice_happens_once(api: Client, owner: User, tenant: Tenant) -> None:
    """E7: `Idempotency-Key`, and the first response replayed."""
    api.force_login(owner)
    key = "b-core-idempotency-1"
    payload = {"email": "once@example.com", "role": "member"}

    first = api.post(INVITATIONS, data=payload, content_type=JSON, HTTP_IDEMPOTENCY_KEY=key)
    second = api.post(INVITATIONS, data=payload, content_type=JSON, HTTP_IDEMPOTENCY_KEY=key)

    assert first.status_code == 201, first.content
    assert second.status_code == 201, second.content
    assert second.content == first.content, "the first response, replayed"
    assert second["Idempotent-Replayed"] == "true"
    assert Invitation.objects.for_tenant(tenant).filter(email="once@example.com").count() == 1


# --- the audit trail ----------------------------------------------------------


def test_every_write_leaves_an_audit_row_naming_the_service_and_the_door(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization]
) -> None:
    """G3. The action is the service's own name; the door is where it came from."""
    api.force_login(owner)
    api.post(
        ORGANIZATIONS,
        data={"parent_id": str(tree["root"].pk), "name": "Audited", "slug": "audited"},
        content_type=JSON,
    )
    api.put(SETTINGS, data={"locale": "pt-pt"}, content_type=JSON)

    rows = {
        (row.action, row.door) for row in AuditEntry.objects.for_tenant(tenant).filter(outcome="ok")
    }

    assert ("core.create_organization", "rest") in rows
    assert ("core.update_tenant_settings", "rest") in rows


def test_a_refusal_is_audited_and_writes_nothing(api: Client, member: User, tenant: Tenant) -> None:
    """The refusal is on the trail, and the row it refused is not."""
    api.force_login(member)
    api.post(INVITATIONS, data={"email": "refused@example.com"}, content_type=JSON)

    refused = AuditEntry.objects.for_tenant(tenant).filter(
        action="core.invite_member", outcome="error"
    )

    row = refused.first()
    assert row is not None
    assert row.error_code == "forbidden"
    assert not Invitation.objects.filter(email="refused@example.com").exists()


# --- accept: the session-only capability --------------------------------------


def test_an_invitation_is_accepted_in_a_session(
    api: Client, owner: User, tenant: Tenant, nomad: User
) -> None:
    """ADR core-16's REST half: the token names the invitation, the session the person."""
    _invitation, token = invite_member(
        tenant=tenant, email=nomad.email, invited_by=owner, actor=system_actor(tenant=tenant)
    )
    api.force_login(nomad)

    response = api.post(f"{INVITATIONS}accept/", data={"token": token}, content_type=JSON)

    assert response.status_code == 200, response.content
    assert _body(response)["user_id"] == str(nomad.pk)
    assert Membership.objects.filter(user=nomad, tenant=tenant).exists()


def test_a_token_that_matches_nothing_is_not_found(api: Client, nomad: User) -> None:
    api.force_login(nomad)

    response = api.post(
        f"{INVITATIONS}accept/", data={"token": "not-a-real-token"}, content_type=JSON
    )

    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"


# --- the query pins house rule 5 cannot ask for here --------------------------
# Rule 5's app half reads `apps/<app>/api.py` and core's routes live in the
# `api/` PACKAGE, so the rule counts none of these three lists and would not
# have noticed an N+1 in any of them (reported; `quality/**` is WA-1's). The
# pins are written anyway, because the reason for the rule does not go away when
# the check cannot see the file.


def _query_count(api: Client, url: str, query: str = "") -> int:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        response = api.get(f"{url}?{query}")
    assert response.status_code == 200, response.content
    return len(captured)


#: Measured after ADR core-18, and it is one LOWER than it was: the default
#: list no longer issues a `COUNT`.
#:
#: **+3 at Phase R: `<kind>.read` asked at the hat** — the memberships, their
#: grants and the delta rows for the role keys they name — and paid ONCE per
#: actor whatever the number of questions in the request (PR0's memo). It moved
#: 7 → 10, once, and the "once" is the claim: a request that asked twice would
#: have moved it to 13.
LIST_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 1  # the page

#: What the same list costs when a caller asks for the total. Exactly one more
#: statement, and the pair is the instrument: the count(*) tax the ADR removed
#: is now something a test can see arrive and leave. 8 → 9 with the read.
COUNTED_LIST_QUERY_BUDGET = 9


@pytest.mark.parametrize("url", [ORGANIZATIONS, MEMBERSHIPS, INVITATIONS])
def test_a_list_costs_a_fixed_number_of_queries(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization], url: str
) -> None:
    """Measured, not guessed: 7 at twelve rows on this tree, for all three.

    The number is the session, the user, the membership resolution and the page
    — the request's own cost, not the rows'. It used to be 8: the eighth was the
    `COUNT` every list paid whether or not the caller wanted a total, and ADR
    core-18 made it opt-in. What matters is the next test, which is the one an
    N+1 fails.
    """
    _seed(tenant, owner, tree, 12)
    api.force_login(owner)

    assert _query_count(api, url) == LIST_QUERY_BUDGET


@pytest.mark.parametrize("url", [ORGANIZATIONS, MEMBERSHIPS, INVITATIONS])
def test_a_list_costs_the_same_at_twice_the_rows(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization], url: str
) -> None:
    """The falsifier. A per-row query would make this number move; it must not.

    Doubling rather than pinning is what actually catches an N+1: a pin alone
    can be updated by whoever broke it, and a reader cannot tell a legitimate
    new query from a per-row one. This can only be made to pass by not having
    one.
    """
    _seed(tenant, owner, tree, 6)
    api.force_login(owner)
    at_six = _query_count(api, url)

    _seed(tenant, owner, tree, 6, offset=6)
    at_twelve = _query_count(api, url)

    assert at_six == at_twelve == LIST_QUERY_BUDGET


@pytest.mark.parametrize("url", [ORGANIZATIONS, MEMBERSHIPS, INVITATIONS])
def test_the_count_costs_exactly_one_statement_and_only_when_asked(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization], url: str
) -> None:
    """ADR core-18's whole argument, made observable (criterion 4).

    The count(*) tax was not slow so much as UNASKED: every list paid a second
    statement whose plan is the measured worst half, including the many callers
    that never render a total. Here it is, arriving only when somebody asks for
    it — and the default response demonstrably not paying it.
    """
    _seed(tenant, owner, tree, 12)
    api.force_login(owner)

    assert _query_count(api, url) == LIST_QUERY_BUDGET
    assert _query_count(api, url, "include_count=true") == COUNTED_LIST_QUERY_BUDGET
    assert COUNTED_LIST_QUERY_BUDGET == LIST_QUERY_BUDGET + 1


def _seed(
    tenant: Tenant, owner: User, tree: dict[str, Organization], count: int, offset: int = 0
) -> None:
    """`count` more organizations, memberships and invitations, all readable at the root."""
    from apps.accounts.services import create_user

    acting = actor_for(user=owner, tenant=tenant, org=tree["root"])
    for index in range(offset, offset + count):
        branch = create_organization(
            tenant=tenant,
            parent=tree["root"],
            name=f"Seeded {index}",
            slug=f"seeded-{index}",
            actor=acting,
        )
        person = create_user(email=f"seeded-{index}@example.com", password="pw-for-tests-only")  # noqa: S106 — a throwaway password a test user is made with
        add_membership(
            user=person,
            tenant=tenant,
            organization=branch,
            role=Membership.Role.MEMBER,
            actor=acting,
        )
        invite_member(
            tenant=tenant, email=f"invited-{index}@example.com", invited_by=owner, actor=acting
        )
