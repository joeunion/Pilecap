"""The cursor seam, and the correctness claim that bought it (ADR core-18).

`page`/`page_size` were not replaced because they were slow. They were replaced
because **an offset page is wrong under concurrent writes** and says nothing
about it. A list here is newest-first, so the churn is at the head, where it is
most likely:

* a row **inserted** above the window pushes everything down, so the next
  offsets land on rows the last page already returned — **duplicates**;
* a row **removed** above the window pulls everything up, so the next offsets
  land past rows nobody has read — **skips**.

Both look exactly like a correct page. That claim had never been proven on this
tree — the ADR says so in its own `Absent:` line — so it is proven here, both
ways round, against the ordering this product actually ships.
`test_an_offset_walk_repeats_a_row_under_a_concurrent_insert` and
`test_an_offset_walk_skips_a_row_under_a_concurrent_delete` are the victims:
they page the same rows the offset way and demonstrate the defect. The two
`test_the_cursor_walk_survives_*` tests then run the identical scenarios through
`cursor_page` and do not.

Most of what follows is over `core.Organization` because `core` owns the seam and
this is `core`'s test module. The property is about the paginator, not about
organizations: a queryset ordered `-created_at` with an `id` tiebreak is the
house list shape, and every other list in the product rides the same code.

**The exception is the cross-COLLECTION section at the foot of this file**,
which cannot be written over one model: the claim is that a cursor cut on one
list is refused by another, so it needs two lists — and two that agree about
everything a cursor used to carry, or the ordering check would answer first and
the test would pass having proven nothing. `example.Widget` beside
`core.Invitation` is that pair on this tree.

**The tenant's root organization is a visible row too**, so a tree seeded with
twelve branches walks thirteen. Nothing here asserts a bare number where that
matters; the claims are about what the walk *contains*.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.core.actor import actor_for, system_actor
from apps.core.api.pagination import (
    CURSOR_VERSION,
    FOREIGN_CURSOR,
    MAX_LIMIT,
    _b64decode,
    _b64encode,
    _signature,
    cursor_page,
    encode_cursor,
)
from apps.core.exceptions import REFUSALS, InvalidCursor, NotFound, wire_refusal
from apps.core.models import Organization, Tenant
from apps.core.selectors import list_organizations
from apps.core.services import create_organization, invite_member, root_organization

# `core`'s own tests drive the worked example app — the exemption is declared in
# `pyproject.toml`'s layer contract by name, and this is the reason it is there:
# the cross-COLLECTION claim below needs two lists that agree about everything a
# cursor used to carry, and `example.Widget` beside `core.Invitation` is the
# pair this tree actually has.
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

ORGANIZATIONS = "/api/v1/organizations/"
RECENCY = ("-created_at", "id")


# --- the world ----------------------------------------------------------------


def _seed(*, tenant: Tenant, owner: User, count: int, offset: int = 0) -> list[Organization]:
    """`count` organizations under the tenant's root, through the service.

    Through `create_organization` rather than `Organization.objects.create`
    because the materialized paths have to be real: a tree assembled by hand has
    no paths, every subtree read in this file would pass vacuously, and the walk
    would be over a set nothing in the product can produce.
    """
    root = root_organization(tenant=tenant)
    actor = actor_for(user=owner, tenant=tenant, org=root)
    return [
        create_organization(
            tenant=tenant,
            parent=root,
            name=f"Branch {index:03d}",
            slug=f"branch-{index:03d}",
            actor=actor,
        )
        for index in range(offset, offset + count)
    ]


def _rows(tenant: Tenant, _owner: User) -> Any:
    """The list every door reads: scoped, hatted, newest first.

    `system_actor` because this file measures the PAGINATOR, not the permission:
    a human actor here would make every cursor case depend on a role, and the
    read gate has its own file (`test_reads_ask.py`).
    """
    return list_organizations(
        tenant=tenant,
        org=root_organization(tenant=tenant),
        actor=system_actor(tenant=tenant),
    ).order_by(*RECENCY)


def _walk(tenant: Tenant, owner: User, *, limit: int) -> list[str]:
    """Every id a cursor walk yields, following `next_cursor` to the end."""
    seen: list[str] = []
    cursor: str | None = None
    for _hop in range(200):  # a bound, so a broken walk fails rather than hangs
        page = cursor_page(_rows(tenant, owner), tenant=tenant, cursor=cursor, limit=limit)
        seen.extend(str(row.pk) for row in page.items)
        if not page.has_more:
            return seen
        cursor = page.next_cursor
    raise AssertionError("the walk did not terminate")


def _offset_walk(tenant: Tenant, owner: User, *, size: int, between: Any = None) -> list[str]:
    """The walk the retired paginator did — `queryset[start : start + size]`.

    Kept here, in the test that indicts it, rather than left in the product: it
    is the thing ADR core-18 removed and the only honest way to demonstrate why.
    """
    seen: list[str] = []
    start = 0
    for hop in range(200):
        window = list(_rows(tenant, owner)[start : start + size])
        seen.extend(str(row.pk) for row in window)
        if len(window) < size:
            return seen
        start += size
        if between is not None and hop == 0:
            between()
    raise AssertionError("the walk did not terminate")


# --- the envelope -------------------------------------------------------------


def test_the_envelope_is_the_ratified_one(api: Client, tenant: Tenant, owner: User) -> None:
    """Criterion 1. The baseline was `{"items": [...], "count": n}`; this replaced it.

    Asserted as an exact key set: half a hard cut — `count` still computed, or
    an extra key nobody meant — passes every field-by-field check there is.
    """
    _seed(tenant=tenant, owner=owner, count=3)
    api.force_login(owner)

    body = json.loads(api.get(ORGANIZATIONS).content)

    assert set(body) == {"items", "has_more", "next_cursor", "count"}
    assert body["count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_page_and_page_size_name_nothing_any_more(api: Client, tenant: Tenant, owner: User) -> None:
    """The hard cut, in the way a client can observe it.

    `?page=2` used to answer the second page and `?page_size=1` used to answer
    one row. Neither is a parameter now, so both are ignored like any other
    unknown query string — the answer is the first page, at the default size.
    The contract says so where a client reads it: no operation in the exported
    document declares either name. This pins the behaviour behind that.
    """
    _seed(tenant=tenant, owner=owner, count=4)
    api.force_login(owner)

    first = json.loads(api.get(f"{ORGANIZATIONS}?limit=2").content)
    asked_for_page_two = json.loads(api.get(f"{ORGANIZATIONS}?limit=2&page=2").content)
    asked_for_a_page_size = json.loads(api.get(f"{ORGANIZATIONS}?page_size=1").content)

    assert first["has_more"] is True
    assert [row["id"] for row in asked_for_page_two["items"]] == [
        row["id"] for row in first["items"]
    ]
    assert len(asked_for_a_page_size["items"]) > 1, "`page_size` is not a control any more"


# --- the walk: the correctness claim, planted both ways -----------------------


def test_the_walk_never_skips_or_repeats(tenant: Tenant, owner: User) -> None:
    """Criterion 2, the still case: 120 seeded rows, 50 at a time, no loss."""
    made = _seed(tenant=tenant, owner=owner, count=120)

    seen = _walk(tenant, owner, limit=50)

    assert len(seen) == len(set(seen)), "the walk returned a row twice"
    assert len(seen) == _rows(tenant, owner).count(), "the walk did not reach every row"
    assert {str(row.pk) for row in made} <= set(seen)


def test_an_offset_walk_repeats_a_row_under_a_concurrent_insert(
    tenant: Tenant, owner: User
) -> None:
    """THE VICTIM. The defect ADR core-18 was ratified on, made to happen.

    Twelve rows, four at a time, one row created after the first page is read.
    Newest-first puts the newcomer at position 0, so every later row shifts DOWN
    by one and the next window starts one row earlier than it should — the last
    row of page 1 comes back as the first row of page 2. A client inserting each
    row it reads writes one of them twice; a client summing gets a wrong number;
    nothing in either response says anything happened.
    """
    _seed(tenant=tenant, owner=owner, count=12)

    def insert_between_pages() -> None:
        _seed(tenant=tenant, owner=owner, count=1, offset=100)

    seen = _offset_walk(tenant, owner, size=4, between=insert_between_pages)

    assert len(seen) != len(set(seen)), "the plant did not take: the offset walk repeated nothing"


def test_an_offset_walk_skips_a_row_under_a_concurrent_delete(tenant: Tenant, owner: User) -> None:
    """THE OTHER VICTIM. The same defect from the other side, and the worse one.

    A row removed above the window pulls everything after it UP by one, so the
    next offsets land past a row nobody has read. It is never returned, the
    response looks exactly like a correct page, and the client has no way to
    know it is now working from an incomplete set.
    """
    made = _seed(tenant=tenant, owner=owner, count=12)

    def delete_between_pages() -> None:
        # Straight to the manager, deliberately: this is the OTHER writer racing
        # the reader, not a capability the door offers.
        Organization.objects.filter(pk=made[-1].pk).delete()

    seen = _offset_walk(tenant, owner, size=4, between=delete_between_pages)

    survivors = {str(row.pk) for row in made[:-1]}
    assert survivors - set(seen), "the plant did not take: the offset walk lost nothing"


def test_the_cursor_walk_survives_the_same_concurrent_insert(tenant: Tenant, owner: User) -> None:
    """Criterion 2, the moving case. The identical scenario, and nothing repeats.

    A cursor names a position, not a count, so a row arriving above it cannot
    move it. The newcomer is not behind the in-flight walk and appears at its
    recency position on a fresh one — which is the honest behaviour, said out
    loud rather than hidden.
    """
    made = _seed(tenant=tenant, owner=owner, count=12)

    page = cursor_page(_rows(tenant, owner), tenant=tenant, limit=4)
    seen = [str(row.pk) for row in page.items]
    cursor = page.next_cursor

    newcomer = _seed(tenant=tenant, owner=owner, count=1, offset=100)[0]

    for _hop in range(200):
        page = cursor_page(_rows(tenant, owner), tenant=tenant, cursor=cursor, limit=4)
        seen.extend(str(row.pk) for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor

    assert len(seen) == len(set(seen)), "the in-flight walk repeated a row"
    assert {str(row.pk) for row in made} <= set(seen), "the in-flight walk lost a row"
    assert str(newcomer.pk) not in seen, "a row created above the cursor is not behind it"
    assert _walk(tenant, owner, limit=4)[0] == str(newcomer.pk), "and a fresh walk finds it first"


def test_the_cursor_walk_survives_the_same_concurrent_delete(tenant: Tenant, owner: User) -> None:
    """The delete side, twice over: a row removed above the cursor, and the anchor itself.

    The keyset is a value, not a pointer — `WHERE (created_at, id) < (...)` is
    still a perfectly good predicate when the row it was read from is gone — so
    neither deletion can move the walk past anything unread.
    """
    made = _seed(tenant=tenant, owner=owner, count=12)

    page = cursor_page(_rows(tenant, owner), tenant=tenant, limit=4)
    seen = [str(row.pk) for row in page.items]
    anchor = page.items[-1]
    cursor = page.next_cursor

    # One above the window (already read) and the anchor the cursor was cut from.
    Organization.objects.filter(pk__in=[made[-1].pk, anchor.pk]).delete()

    for _hop in range(200):
        page = cursor_page(_rows(tenant, owner), tenant=tenant, cursor=cursor, limit=4)
        seen.extend(str(row.pk) for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor

    assert len(seen) == len(set(seen))
    unread_and_alive = {str(row.pk) for row in made} - set(seen[:4]) - {str(anchor.pk)}
    unread_and_alive -= {str(made[-1].pk)}
    assert unread_and_alive <= set(seen), "the cursor walk skipped a surviving row"


def test_rows_sharing_a_timestamp_still_walk(tenant: Tenant, owner: User) -> None:
    """The tiebreak, which is what makes `(created_at, id)` a total order.

    Every row is forced to one instant, so `created_at` alone names no position
    at all and the walk would either loop or lose most of the table. `id` is
    what saves it. The declared blind spot is that the order WITHIN one instant
    is arbitrary — not that it is unstable.
    """
    made = _seed(tenant=tenant, owner=owner, count=20)
    Organization.objects.filter(tenant=tenant).update(created_at=timezone.now())

    seen = _walk(tenant, owner, limit=5)

    assert len(seen) == len(set(seen))
    assert {str(row.pk) for row in made} <= set(seen)


# --- the token: what each part refuses ----------------------------------------


def test_a_tampered_cursor_is_refused_rather_than_obeyed(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Criterion 3. Without the signature, `k` is a client-controlled WHERE clause."""
    _seed(tenant=tenant, owner=owner, count=4)
    api.force_login(owner)

    minted = json.loads(api.get(f"{ORGANIZATIONS}?limit=2").content)["next_cursor"]
    assert minted
    payload, _, signature = minted.partition(".")
    edited = json.loads(_b64decode(payload))
    edited["k"] = ["1970-01-01T00:00:00+00:00", "00000000-0000-0000-0000-000000000000"]
    reissued = _b64encode(json.dumps(edited, separators=(",", ":"), sort_keys=True).encode())

    refused = api.get(f"{ORGANIZATIONS}?cursor={reissued}.{signature}")

    assert refused.status_code == 400, refused.content
    assert json.loads(refused.content)["code"] == "invalid_cursor"


@pytest.mark.parametrize("token", ["not-a-cursor", "a.b", "eyJ2IjoxfQ", "eyJ2IjoxfQ.", ".zzzz"])
def test_a_cursor_that_was_never_minted_here_is_refused(
    api: Client, tenant: Tenant, owner: User, token: str
) -> None:
    """Every shape of "I made this up" answers the same way."""
    _seed(tenant=tenant, owner=owner, count=2)
    api.force_login(owner)

    refused = api.get(f"{ORGANIZATIONS}?cursor={token}")

    assert refused.status_code == 400, refused.content
    assert json.loads(refused.content)["code"] == "invalid_cursor"


def test_an_empty_cursor_starts_the_walk_rather_than_refusing(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """`?cursor=` with nothing after it is indistinguishable from not sending it."""
    _seed(tenant=tenant, owner=owner, count=2)
    api.force_login(owner)

    assert api.get(f"{ORGANIZATIONS}?cursor=").status_code == 200


def test_a_cursor_from_another_tenant_is_not_found_and_not_forbidden(
    tenant: Tenant, other_tenant: Tenant
) -> None:
    """Criterion 3, the anti-oracle half.

    The token is genuine — signed by this deployment, well-formed, current
    version — and it belongs to somebody else. `not_found`, exactly as a row in
    another tenant does: a refusal that told a foreign cursor from a forged one
    would confirm the other tenant's walk exists.
    """
    theirs = encode_cursor(
        tenant_key=str(other_tenant.pk),
        # The RIGHT collection, so nothing but the tenant is wrong and this pins
        # the tenant branch rather than whichever check happens to run first
        # (a check above pins the tenant branch specifically).
        collection="core.organization",
        ordering=RECENCY,
        keys=["2026-08-23T09:30:00+00:00", "00000000-0000-0000-0000-000000000000"],
    )

    with pytest.raises(NotFound) as refused:
        cursor_page(
            Organization.objects.for_tenant(tenant).order_by(*RECENCY),
            tenant=tenant,
            cursor=theirs,
        )

    # It SPEAKS. This raise carried the class default — the bare words
    # "Not Found" — while three route docstrings promised "the cursor was minted
    # for a different account", so a caller who pasted a colleague's cursor got a
    # refusal indistinguishable from a deleted row. It was the last refusal in
    # the tree whose detail was a fallback rather than a sentence.
    #
    # The anti-oracle property above is untouched by saying it: the sentence
    # names the CURSOR as the thing that does not belong and never the rows, so
    # it is equally true whether or not the other tenant's list exists.
    assert refused.value.detail == FOREIGN_CURSOR
    assert refused.value.detail != NotFound.default_detail


def test_a_cursor_minted_under_another_ordering_is_refused(tenant: Tenant, owner: User) -> None:
    """A keyset names a position in ONE sequence. Replayed against another it means nothing.

    Refused rather than obeyed: filtering `name > "Branch 001"` on a list now
    sorted by `-created_at` returns a page that looks fine and is arbitrary.
    """
    _seed(tenant=tenant, owner=owner, count=4)
    by_name = cursor_page(
        Organization.objects.for_tenant(tenant).order_by("name", "id"), tenant=tenant, limit=2
    )
    assert by_name.next_cursor is not None

    with pytest.raises(InvalidCursor):
        cursor_page(
            Organization.objects.for_tenant(tenant).order_by(*RECENCY),
            tenant=tenant,
            cursor=by_name.next_cursor,
            limit=2,
        )


def test_a_cursor_from_a_token_version_this_build_does_not_know_is_refused(
    tenant: Tenant,
) -> None:
    """A build that met a shape it does not understand says so instead of guessing."""
    payload = json.dumps(
        {
            "v": CURSOR_VERSION + 1,
            "t": str(tenant.pk),
            "o": list(RECENCY),
            "k": [None, None],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    ahead = f"{_b64encode(payload)}.{_signature(payload)}"

    with pytest.raises(InvalidCursor):
        cursor_page(
            Organization.objects.for_tenant(tenant).order_by(*RECENCY),
            tenant=tenant,
            cursor=ahead,
        )


def test_the_refusal_says_the_same_thing_through_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """E9. The registry composes the body once and the doors render that one body."""
    _seed(tenant=tenant, owner=owner, count=2)
    api.force_login(owner)

    over_http = json.loads(api.get(f"{ORGANIZATIONS}?cursor=nonsense").content)
    composed = wire_refusal(InvalidCursor())

    assert over_http["code"] == composed["code"] == "invalid_cursor"
    assert over_http["detail"] == composed["detail"]
    assert over_http["remedies"] == composed["remedies"]
    assert REFUSALS["invalid_cursor"].fact
    assert REFUSALS["invalid_cursor"].remedies


# --- the count, and the tax that is now a choice ------------------------------


def test_the_count_is_exact_and_only_arrives_when_asked(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Criterion 4. Equal to the scoped count, and absent by default."""
    _seed(tenant=tenant, owner=owner, count=7)
    api.force_login(owner)

    default = json.loads(api.get(f"{ORGANIZATIONS}?limit=2").content)
    asked = json.loads(api.get(f"{ORGANIZATIONS}?limit=2&include_count=true").content)

    assert default["count"] is None
    assert asked["count"] == _rows(tenant, owner).count()
    assert len(asked["items"]) == 2


def test_the_count_counts_the_whole_match_not_the_page(tenant: Tenant, owner: User) -> None:
    """And it does not shrink as the walk advances — it is a total, or it is nothing."""
    _seed(tenant=tenant, owner=owner, count=9)

    first = cursor_page(_rows(tenant, owner), tenant=tenant, limit=3, include_count=True)
    second = cursor_page(
        _rows(tenant, owner), tenant=tenant, cursor=first.next_cursor, limit=3, include_count=True
    )

    assert first.count == second.count == len(_walk(tenant, owner, limit=3))


# --- the ceiling ---------------------------------------------------------------


def test_an_over_limit_page_is_refused_rather_than_silently_clamped(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The clamp was the lie, and this is the sentence that replaces it.

    `?limit=5000` used to come back with 200 rows and **no signal of any kind** —
    no header, no field, no refusal — so a client paging by "I asked for
    everything and got 200, therefore that is everything" stopped at the first
    page and never knew. Refusing costs that client one refusal naming the
    field; clamping cost it the rest of the data.

    400 and `invalid`, not 422: this is a QUERY parameter, and it is the same
    answer its neighbour below gives for `?limit=0`. Two limit refusals
    answering two different status codes for one class of mistake would be a
    worse contract than the one being fixed.
    """
    _seed(tenant=tenant, owner=owner, count=3)
    api.force_login(owner)

    refused = api.get(f"{ORGANIZATIONS}?limit={MAX_LIMIT * 100}")

    assert refused.status_code == 400, refused.content
    body = json.loads(refused.content)
    assert body["code"] == "invalid"
    assert "limit" in body["errors"], body
    assert str(MAX_LIMIT) in json.dumps(body), "the refusal does not say what the ceiling IS"


def _declared_maximum(parameter: dict[str, Any]) -> Any:
    """The ceiling a parameter publishes, wherever pydantic put it.

    `limit` is `int | None`, so the constraint lands inside the non-null branch
    of an `anyOf` rather than on the parameter's own schema. Reading both is the
    difference between a census and a test that passes because it looked in the
    wrong place.
    """
    schema = parameter["schema"]
    if "maximum" in schema:
        return schema["maximum"]
    for branch in schema.get("anyOf", []):
        if "maximum" in branch:
            return branch["maximum"]
    return None


def test_every_paginated_route_publishes_the_ceiling(api: Client) -> None:
    """The other half of the over-limit refusal, as ONE DERIVED PASS over every paginated route.

    The schema published `{minimum: 1}` and nothing else while the prose
    promised 200 — so every client had to discover the ceiling by hitting it,
    which is exactly what the silent clamp made impossible.

    Derived from the live document rather than from a list of paths: every
    paginated route inherits `CursorPagination.Input`, so a route that somehow
    did not would be a second pagination seam, and that is the finding this pass
    exists to make rather than something to keep a list of.
    """
    from config.api import api as the_api

    document = the_api.get_openapi_schema()
    checked: list[str] = []
    missing: list[str] = []
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            names = {one["name"] for one in operation.get("parameters", [])}
            if "cursor" not in names or "limit" not in names:
                continue
            limit = next(one for one in operation["parameters"] if one["name"] == "limit")
            where = f"{method.upper()} {path}"
            checked.append(where)
            if _declared_maximum(limit) != MAX_LIMIT:
                missing.append(where)

    assert checked, "no paginated operation was found; this pass proves nothing"
    assert missing == [], (
        f"these paginated routes do not publish the {MAX_LIMIT}-item ceiling: "
        f"{missing}. Every one of them should inherit "
        "`CursorPagination.Input`; one that does not is a second pagination seam."
    )


def test_a_zero_limit_is_refused_because_it_has_no_answer(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    refused = api.get(f"{ORGANIZATIONS}?limit=0")

    # 400 and `invalid` since SB-1. A QUERY parameter that does not validate is
    # not the same refusal as a body that is not the right shape — the request
    # reached the operation, the narrowing it asked for has no answer — so it
    # keeps the code `derived_refusals` already documents for a route that
    # narrows, and it is now inside the one envelope rather than being pydantic's
    # own list of dictionaries.
    assert refused.status_code == 400, refused.content
    body = json.loads(refused.content)
    assert body["code"] == "invalid", body
    assert "limit" in body["errors"], body


# --- the collection a cursor was minted for -----------------------------------
#
# A cursor already carried WHOSE walk it was (`t`) and WHICH ORDER it walked in
# (`o`). It did not carry WHAT IT WAS WALKING, so a token minted on one list and
# presented to another decoded cleanly and became a `WHERE` clause over rows it
# had never seen: `200 OK`, an envelope that looks perfect, and an arbitrary
# prefix of the second list silently missing. Measured on the baseline tree, a
# `/widgets/` cursor handed to `/invitations/` returned 2 of 3 invitations and
# said nothing about the third.
#
# The refusal's own published sentence has promised otherwise all along — "That
# cursor is not one this API issued for **this list**" — and `GET
# /search/kinds/` publishes it in prose as "the cursor was edited, or came from
# a different endpoint". The seam simply never asked the question.
#
# **The pair is deliberate.** `/widgets/` and `/invitations/` both default to
# `-created_at` and both take a plain pk tiebreak, so the two tokens are
# byte-comparable in every field the seam used to check: same tenant, same
# version, same ordering. Two lists whose orderings happened to differ would be
# caught by the ordering check and would prove nothing about collections.

WIDGETS = "/api/v1/widgets/"
INVITATIONS = "/api/v1/invitations/"

#: The collection key the seam derives for a queryset of `core.Invitation` —
#: spelled once here so a test that plants a foreign key cannot accidentally
#: plant the real one.
INVITATION_COLLECTION = "core.invitation"


def _populate(tenant: Tenant, owner: User, *, count: int = 3) -> None:
    """Widgets and invitations, the same number of each, through their services."""
    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    for index in range(count):
        create_widget(tenant=tenant, actor=acting, name=f"Widget {index:03d}")
        invite_member(
            tenant=tenant,
            email=f"invitee-{index:03d}@example.com",
            organization=root,
            invited_by=owner,
            actor=acting,
        )


def _tool(name: str) -> Any:
    """One tool off a server carrying BOTH doors' registrations.

    `test_mcp_tenancy.tool` registers `core` alone, and the pair this claim needs
    straddles two apps — so the server is assembled here the way `config.mcp`
    assembles the mounted one, by calling each app's `register`.
    """
    from mcp.server import MCPServer

    from apps.core.mcp import register as register_core
    from apps.example.mcp import register as register_example

    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register_core(server)
    register_example(server)
    return server._tool_manager._tools[name].fn  # noqa: SLF001


def test_a_cursor_from_another_collection_is_refused_rather_than_obeyed(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The human door, driven end to end.

    The harm is MEASURED rather than described: the whole invitations list is
    read first, so the assertion can say how many rows the crossed cursor hid.
    """
    _populate(tenant, owner)
    api.force_login(owner)

    minted = json.loads(api.get(f"{WIDGETS}?limit=1").content)
    assert minted["has_more"] is True, minted
    token = minted["next_cursor"]

    whole = json.loads(api.get(INVITATIONS).content)
    assert len(whole["items"]) > 1, "the invitations list is too short to hide anything"

    crossed = api.get(f"{INVITATIONS}?cursor={token}")

    assert crossed.status_code == 400, (
        f"a cursor minted on {WIDGETS} was OBEYED by {INVITATIONS}: "
        f"{crossed.status_code} with {len(json.loads(crossed.content)['items'])} of "
        f"{len(whole['items'])} rows, and no word about the rest"
    )
    body = json.loads(crossed.content)
    assert body["code"] == "invalid_cursor", body
    # And for the RIGHT reason: an ordering mismatch answers `invalid_cursor`
    # too, so a test that stopped at the code would pass on a seam that had
    # merely started disagreeing about sort order.
    assert "different list" in json.dumps(body), body


def test_the_machine_door_refuses_a_foreign_collection_cursor_too(
    tenant: Tenant, owner: User
) -> None:
    """The same walk, the same token, the other door — house rule 17.

    Both doors call `cursor_page` and neither owns cursor code of its own, so
    this proves the question is asked in the one seam rather than that two
    implementations agree today. The tools are called as functions with the
    principal the token middleware would have left, which is how every MCP test
    in `core` drives one.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    from apps.core.tests.test_mcp_tenancy import context_for

    _populate(tenant, owner)
    ctx = context_for(owner, tenant)

    page = _tool("list_widgets")(ctx, limit=1)
    assert page.next_cursor

    with pytest.raises(ToolError) as refused:
        _tool("list_invitations")(ctx, cursor=page.next_cursor)

    assert "invalid_cursor" in str(refused.value), str(refused.value)
    assert "different list" in str(refused.value), str(refused.value)


def test_a_cursor_is_still_good_on_the_collection_that_minted_it(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The other direction, because a seam that refused everything would pass above.

    The same token, on its own list, walks — and the walk is complete: every
    widget arrives exactly once across the two pages.
    """
    _populate(tenant, owner, count=4)
    api.force_login(owner)

    first = json.loads(api.get(f"{WIDGETS}?limit=2").content)
    second = api.get(f"{WIDGETS}?limit=2&cursor={first['next_cursor']}")

    assert second.status_code == 200, second.content
    ids = [row["id"] for row in first["items"]] + [
        row["id"] for row in json.loads(second.content)["items"]
    ]
    assert len(ids) == len(set(ids)) == 4


def test_a_foreign_tenant_cursor_still_answers_not_found_on_the_wire(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    """The pin: the collection check did not move the anti-oracle answer. 404, and it still speaks.

    The token names the RIGHT collection and the right ordering, so nothing but
    the tenant is wrong — which is what makes this a pin on the tenant branch
    rather than on whichever check happens to run first.
    """
    _populate(tenant, owner, count=2)
    api.force_login(owner)
    theirs = encode_cursor(
        tenant_key=str(other_tenant.pk),
        collection=INVITATION_COLLECTION,
        ordering=RECENCY,
        keys=["2026-08-23T09:30:00+00:00", "00000000-0000-0000-0000-000000000000"],
    )

    refused = api.get(f"{INVITATIONS}?cursor={theirs}")

    assert refused.status_code == 404, refused.content
    body = json.loads(refused.content)
    assert body["code"] == "not_found", body
    assert body["detail"] == FOREIGN_CURSOR, body


def test_a_foreign_ordering_cursor_still_answers_invalid_cursor_on_the_wire(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The other pin: the ordering refusal keeps its own sentence, and its 400.

    Same tenant, same collection, different `?ordering=` — so this is the branch
    below the new one, and it is still reachable.
    """
    _seed(tenant=tenant, owner=owner, count=3)
    api.force_login(owner)
    by_name = json.loads(api.get(f"{ORGANIZATIONS}?ordering=name&limit=1").content)
    assert by_name["next_cursor"]

    refused = api.get(f"{ORGANIZATIONS}?ordering=depth&cursor={by_name['next_cursor']}")

    assert refused.status_code == 400, refused.content
    body = json.loads(refused.content)
    assert body["code"] == "invalid_cursor", body
    assert "different sort order" in json.dumps(body), body


def _query_seeds(*, tenant: Tenant, owner: User) -> dict[str, dict[str, str]]:
    """The REQUIRED query parameters a paginated list needs to answer at all, by route.

    The twin of `_path_seeds` in `test_published_examples_at_the_door.py`. A list
    read only through its subject (`/djb_notes/?subject=<kind>:<id>`) refuses a
    request with no subject before it reads the cursor, so driving it bare would
    measure the missing parameter and never the cursor seam. Such a route is
    driven WITH its seed; a paginated route with a required query parameter and
    no row here fails the census by name rather than dropping out of it.
    """
    root = root_organization(tenant=tenant)
    subject = create_widget(
        tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=root), name="Subject"
    )
    return {
        "/api/v1/djb_notes/": {"subject": f"widget:{subject.pk}"},
        "/api/v1/djb_tag_links/": {"subject": f"widget:{subject.pk}"},
    }


#: The attachment kinds the seeded subject must take for `_query_seeds` to drive
#: its routes — planted by the census for its own run until the worked example
#: declares them (`Widget.attachments`).
_SEEDED_ATTACHMENTS = ("notes", "tags")


def _required_query(path: str) -> set[str]:
    """The query parameters the live document marks required on `path`'s GET."""
    from config.api import api as the_api

    operation = the_api.get_openapi_schema()["paths"][path].get("get", {})
    return {
        str(one["name"])
        for one in operation.get("parameters", [])
        if one.get("in") == "query" and one.get("required")
    }


def _paginated_collection_routes() -> list[str]:
    """Every paginated operation the mount holds that a walk can be driven at.

    Derived from the live document, exactly as `test_every_paginated_route_
    publishes_the_ceiling` derives it: the population is house rule 3's census,
    so a list route added in any app is driven here without anybody adding a
    line. Operations with a path parameter are excluded because driving one
    needs a row this pass has no business creating — declared, not dropped
    quietly, and named again in the module's blind spots.
    """
    from config.api import api as the_api

    document = the_api.get_openapi_schema()
    found: list[str] = []
    for path, operations in document["paths"].items():
        for operation in operations.values():
            names = {one["name"] for one in operation.get("parameters", [])}
            if "cursor" not in names or "limit" not in names:
                continue
            if "{" in path:
                continue
            found.append(path)
    return sorted(found)


def test_every_paginated_route_refuses_a_cursor_from_another_collection(
    api: Client, tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONE DERIVED PASS: the seam is inherited, so every list inherits the refusal.

    Driven, not inspected. Each route is handed a genuine token — signed by this
    deployment, this tenant, this token version, this ordering — naming a
    collection that does not exist, and every one of them has to answer
    `invalid_cursor` and say WHY. The collection sentence is the distinguishing
    assertion: an ordering mismatch answers `invalid_cursor` too, so a pass that
    checked only the code would go green for the wrong reason on every route in
    the list.

    Nothing here is seeded on purpose. The refusal is decided before a row is
    read, so an empty collection refuses exactly as a full one does — which is
    the property that lets one pass drive twenty-odd lists in twenty-odd apps
    without knowing what any of them holds.
    """
    api.force_login(owner)
    foreign = encode_cursor(
        tenant_key=str(tenant.pk),
        collection="nowhere.nothing",
        ordering=RECENCY,
        keys=["2026-08-23T09:30:00+00:00", "00000000-0000-0000-0000-000000000000"],
    )

    # The seeded subject is a widget, and a widget takes an attachment only once
    # the worked example declares it; until then the census plants the
    # declaration for its own run. A no-op the day `Widget.attachments` names them.
    declared = tuple(getattr(Widget, "attachments", ()) or ())
    missing = tuple(kind for kind in _SEEDED_ATTACHMENTS if kind not in declared)
    if missing:
        monkeypatch.setattr(Widget, "attachments", (*declared, *missing), raising=False)
    seeds = _query_seeds(tenant=tenant, owner=owner)

    routes = _paginated_collection_routes()
    obeyed: list[str] = []
    for path in routes:
        seeded = seeds.get(path, {})
        unseeded = sorted(_required_query(path) - set(seeded))
        if unseeded:
            obeyed.append(
                f"{path} requires {unseeded} and `_query_seeds` has no row for it, so "
                "its cursor refusal cannot be driven"
            )
            continue
        query = urlencode({**seeded, "cursor": foreign})
        answer = api.get(f"{path}?{query}")
        body = json.loads(answer.content or b"{}")
        if answer.status_code != 400 or body.get("code") != "invalid_cursor":
            obeyed.append(f"{path} -> {answer.status_code} {body.get('code')!r}")
        elif "different list" not in json.dumps(body):
            obeyed.append(f"{path} -> invalid_cursor for the WRONG reason: {body!r}")

    assert routes, "no paginated collection route was found; this pass proves nothing"
    assert obeyed == [], (
        "these paginated routes do not refuse a cursor minted for another "
        f"collection: {obeyed}. Every one of them reaches `cursor_page`, so one "
        "that does not is a second pagination seam."
    )


def test_the_refusal_a_crossed_cursor_gets_is_in_the_published_document(api: Client) -> None:
    """Rule 47, for the code this check made newly reachable.

    This raises an EXISTING code from a new place rather than adding one, which
    is the cheap half of rule 47 — but "cheap" is not "checked", and a refusal a
    generated client has no branch for is the whole defect that rule exists for.
    So: every paginated operation the mount holds publishes `invalid_cursor` on
    its 400, derived off the same census the drive above uses.

    `derived_refusals` adds the code off `@paginate` at the mount rather than off
    a list of route names, which is why this passes for routes in apps that have
    never heard of this file — and why it would fail loudly if that derivation
    were ever replaced by a list.
    """
    from config.api import api as the_api

    document = the_api.get_openapi_schema()
    silent: list[str] = []
    checked = 0
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            names = {one["name"] for one in operation.get("parameters", [])}
            if "cursor" not in names or "limit" not in names:
                continue
            checked += 1
            published: set[str] = set()
            for response in operation.get("responses", {}).values():
                published |= set(response.get("x-refusal-codes") or ())
            if "invalid_cursor" not in published:
                silent.append(f"{method.upper()} {path} -> {sorted(published)}")

    assert checked, "no paginated operation was found; this pass proves nothing"
    assert silent == [], (
        "these paginated operations can answer `invalid_cursor` and do not say so "
        f"in the document: {silent}"
    )


def test_the_search_walk_and_a_list_walk_are_foreign_to_each_other(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The one caller that pages something which is not rows, pinned both ways.

    `apps/search/selectors.py` calls the token layer directly — a search page is
    ranked, not ordered by a column, so it cannot go through `cursor_page` — and
    it takes `UNBOUND_COLLECTION` by default. That default is a value no
    derivation can produce, which is what makes these two directions refuse.

    Pinned here rather than in `apps/search` because the property is the SEAM's:
    the day somebody gives `decode_cursor` a different default, this is what says
    so, and it says so from the module that owns the decision.
    """
    _populate(tenant, owner)
    api.force_login(owner)

    minted = json.loads(api.get(f"{WIDGETS}?limit=1").content)
    assert minted["next_cursor"]
    unbound = encode_cursor(
        tenant_key=str(tenant.pk),
        ordering=("offset",),
        keys=[1],
    )

    # A list's cursor, offered to the search walk.
    into_search = api.get(f"/api/v1/search/?q=widget&cursor={minted['next_cursor']}")
    assert into_search.status_code == 400, into_search.content
    assert json.loads(into_search.content)["code"] == "invalid_cursor"

    # And the search walk's own, offered to a list.
    into_list = api.get(f"{INVITATIONS}?cursor={unbound}")
    assert into_list.status_code == 400, into_list.content
    assert json.loads(into_list.content)["code"] == "invalid_cursor"


def test_an_empty_built_list_refuses_a_cursor_rather_than_guessing(tenant: Tenant) -> None:
    """A catalogue with nothing in it has no item to be identified by.

    So it takes `UNIDENTIFIED_COLLECTION`, which no minted token can carry, and a
    cursor presented to it is refused. Fail-closed, and the same shape
    `for_tenant(None)` and `visible_to(None)` already take.
    """
    minted = encode_cursor(
        tenant_key=str(tenant.pk),
        collection="apps.core.tests.test_pagination.Named",
        ordering=("name",),
        keys=["a"],
    )

    with pytest.raises(InvalidCursor):
        cursor_page([], tenant=tenant, cursor=minted, ordering=("name",))
