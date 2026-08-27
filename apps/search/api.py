"""The HTTP door onto search. **One route, every kind — and one that lists them.**

There is deliberately no per-resource search route (`/widgets/search/` and its
siblings): one door serves every registered kind, so adding a kind adds no URL,
no schema and no test — it adds a declaration in the owning app. Nor is there
any write route. Indexing is spine-fed and service-only, because a client that
could write documents could mint search results, and a search result is
something a person acts on.

The second route is `GET /search/kinds/`, and it is here because of what
an earlier field test measured: the vocabulary `?kinds=` speaks was *derived*
and *unpublished*, so a stranger who sent a name this build does not declare got
the same empty page as a stranger who searched for something nobody has — and
had no way to tell the two apart. A vocabulary a caller must send and cannot
read is a vocabulary they have to guess. Publishing it is also what makes
refusing an unknown kind honest rather than leaky: the set is public, so naming
it in a refusal gives away nothing a `GET` would not.

The route restates `auth=` on its router rather than inheriting the API default,
so reading this one file tells you what it takes to call it. It calls the
chokepoint in `selectors.py` and nothing else — the engine is fenced (house rule
33) and this module is not on its allow-list, which is the mechanical half of
"every door calls the same wall".
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and the query
# parameters come out as unresolvable forward references.

from typing import Annotated

from ninja import Router
from ninja.errors import HttpError
from ninja.params.functions import Query as QueryParam

from apps.accounts.auth import API_AUTH
from apps.core.actor import actor_from_request
from apps.core.api.docs import Tag, refuses
from apps.core.api.pagination import MAX_LIMIT, cursor_page
from apps.core.requests import TenantRequest
from apps.search import registry
from apps.search.schemas import SearchKindOut, SearchKindPage, SearchPage
from apps.search.selectors import search

# The path says what the resource is. `config.api` reads this; an app that says
# nothing is mounted under its label, and here the two agree — written down
# anyway so renaming the app never silently moves a published URL.
PREFIX = "search"

#: The scope family these routes belong to — ratified
#: (`design-agreements.md`, "Scope keys ratified: files/search/usage/devices").
#: It follows the DEFAULT half of the choosing pattern: the plural noun of the
#: section's primary resource would be "searches", which misleads — the resource
#: here is the *capability*, so the key is the capability's name. `search:read`
#: says exactly what a token holding it is trusted with, and there is no
#: `search:write` because there is no write door: indexing is the spine's.
#:
#: The key FREEZES the day a token could name it, which is today. Renaming it
#: later kills every ceiling that holds it, silently, and the token goes on
#: authenticating while being refused at every door.
TAGS = {
    "search": Tag(
        "Search",
        "Finding things by typing words. One endpoint searches everything your "
        "organization can see, across every kind of record this product has made "
        "searchable, and answers with pointers you can then fetch in full.",
        plane="everyday",
        plane_note=(
            "finding things by typing words. One endpoint covers every kind of record this "
            "product has made searchable, and answers with pointers you fetch in full through "
            "that record's own section. Everyday rather than administrative, and read-only: what "
            "a search can find is exactly what you could already page through, and nothing "
            "writes to the index through a door."
        ),
    ),
}

router = Router(tags=["search"], auth=API_AUTH)


def kind_catalogue() -> list[SearchKindOut]:
    """The published vocabulary — **one implementation, both doors**.

    It lives here rather than in `selectors.py` because it returns no queryset
    and reads no table: the population is the installed apps' own `search.py`
    declarations, which is the same registry the chokepoint narrows against and
    the same one a bad declaration is refused from at boot. `events.api
    .event_catalogue` is the shape this copies, deliberately — two vocabularies
    published two different ways is two places for one to rot.
    """
    return [SearchKindOut(kind=entry.kind, app=entry.app) for entry in registry.catalogue()]


@router.get("/kinds/", response=SearchKindPage, url_name="search_kind-list")
@refuses("forbidden", "invalid_cursor", "not_found", "rate_limited")
def list_search_kinds_route(
    request: TenantRequest,
    cursor: str = "",
    # The ceiling, PUBLISHED. This route takes its pagination
    # controls as bare parameters rather than through
    # `@paginate(CursorPagination)`, so it does not inherit the
    # `Input` schema that declares them — which is why the derived pass in
    # `apps/core/tests/test_pagination.py` found it. The refusal it already
    # inherits: `cursor_page` refuses an over-limit page for every caller,
    # both doors. `MAX_LIMIT` is imported rather than typed so the number
    # is still spelled in exactly one place.
    limit: Annotated[int | None, QueryParam(None, ge=1, le=MAX_LIMIT)] = None,
    include_count: bool = False,
) -> SearchKindPage:
    """List what can be searched

    List every kind of thing this product can find, so you can narrow a search
    to one of them.

    Returns `{"items": [{"kind": ..., "app": ...}], "has_more": ...,
    "next_cursor": ...}`, in alphabetical order, walked with `?cursor=` and
    `?limit=`. `count` arrives only with `?include_count=true`.

    Every value `kinds` accepts on the search endpoint is here, and nothing
    else is: a name that is not on this list is refused there rather than
    quietly searched for and not found. `app` says which part of the product
    owns those records — that is where you fetch one in full once a search has
    pointed at it.

    This list is generated from the running product, so it is always complete
    and current. It is the same for every customer: it describes what this
    product can search, not what you happen to have. A deployment that has made
    nothing searchable answers with an empty list, which is a true and useful
    answer — it is what tells you that no search here will ever find anything.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no account. Send `X-Tenant` naming
      one you belong to.
    * `400 invalid_cursor` — the cursor was edited, or came from a different
      endpoint. Start the walk again without one.
    * `404 not_found` — the cursor was minted for a different account.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    There is no `@paginate` on this route, for the reason its neighbour above
    gives and one of its own. The CURSOR SEAM is used directly —
    `core.api.pagination.cursor_page`, where signing, tenant-binding and the
    ordering check live — so the envelope, the refusals and the tokens are the
    seam's, exactly as they would be under the decorator. What the decorator
    would add is a THIRD schema for this page: ninja generates one from
    `list[SearchKindOut]` at mount time, the machine door answers with
    `SearchKindPage`, and two shapes describing one page is the drift rule 46
    exists to catch, invited on purpose. One schema, one call, both doors.
    """
    if request.tenant is None:
        raise HttpError(403, "No account for this request.")
    page = cursor_page(
        kind_catalogue(),
        tenant=request.tenant,
        cursor=cursor or None,
        limit=limit,
        include_count=include_count,
        ordering=("kind",),
    )
    return SearchKindPage(
        items=list(page.items),
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        count=page.count,
    )


@router.get("/", response=SearchPage, url_name="search-query")
@refuses(
    "forbidden", "invalid", "invalid_cursor", "not_found", "rate_limited", "search_unavailable"
)
def search_route(
    request: TenantRequest,
    q: str = "",
    kinds: str = "",
    cursor: str = "",
    # The ceiling, PUBLISHED. This route takes its pagination
    # controls as bare parameters rather than through
    # `@paginate(CursorPagination)`, so it does not inherit the
    # `Input` schema that declares them — which is why the derived pass in
    # `apps/core/tests/test_pagination.py` found it. The refusal it already
    # inherits: `cursor_page` refuses an over-limit page for every caller,
    # both doors. `MAX_LIMIT` is imported rather than typed so the number
    # is still spelled in exactly one place.
    limit: Annotated[int | None, QueryParam(None, ge=1, le=MAX_LIMIT)] = None,
    include_count: bool = False,
) -> SearchPage:
    """Search everything you can see

    Find things by typing words. One search covers every kind of record this
    product has made searchable, and answers with the best matches first.

    **`q`** is what you are looking for — words, part of a name, a reference
    number. An empty `q` matches everything you can see, which is a useful way
    to page through a kind.

    **Narrow** with `kinds`, a comma-separated list of the kinds
    `GET /search/kinds/` lists. Leave it out to search everything. A name that
    is not on that list is **refused** — `400 invalid`, naming what you sent and
    what this product does declare — so a typo and an empty product are never
    the same answer.

    **Pages** are `?cursor=` and `?limit=` (20 by default, 200 at most). The body
    is `{"items": [...], "has_more": ..., "next_cursor": ...}`: send the
    `next_cursor` you were given back as `?cursor=` for the following page, and
    stop when `has_more` is false. A cursor is opaque and belongs to the search
    that produced it — never build one, and never send a cursor from a different
    endpoint.

    **`count` is `null` unless you send `?include_count=true`**. When you do ask,
    it is exact, and it counts only what you can see — including when the answer
    is `0`. `null` means "nobody counted"; it never stands in for zero.

    **What you can see** depends on the organization you are acting as — the
    `X-Org` header, or your default organization if you send none. You get that
    organization's records and those of every organization beneath it, and
    nothing else: a word that appears only in a record you cannot reach produces
    no hit and adds nothing to the count.

    **Results can lag a change by seconds.** A record you just created appears
    once the change has made its way to the index. If you need a list that is
    true the instant you write it, use that record's own list endpoint — this is
    a search, and it trades a second of freshness for finding things by their
    words.

    **`engine`** in the response says which engine answered: `meili` normally,
    `postgres` while the index is unreachable, when matching is plainer and
    typos are not forgiven. What you can see does not change either way.

    **One field here is deliberately not a report of what happened, and it is
    this one.** When the answer is empty because you can see nothing — you sent
    an `X-Org` this product could not resolve for you, or you belong to no
    account — no engine is asked at all, and the page still names the engine
    this deployment searches with. That is on purpose: a page you are not
    entitled to and a page that genuinely matched nothing are the same page,
    down to the byte, so that nobody can use this endpoint to find out whether a
    record they cannot reach exists. Everything else in the body is exactly what
    it says.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no account or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `400 invalid` — `kinds` named something this product cannot search. The
      message says what you sent and lists what it does have;
      `GET /search/kinds/` is the same list.
    * `400 invalid_cursor` — the cursor was edited, or came from a different
      endpoint. Start the walk again without one.
    * `404 not_found` — the cursor was minted for a different account.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    * `503 search_unavailable` — **not** the index being down; that is answered
      from Postgres above. This means no engine could answer at all. Retry;
      nothing is wrong with your request.

    ---
    There is no `@paginate` on this route, and that is not an omission. The
    engine ranks and windows the result set — there is no queryset for the
    paginator to slice, and handing it every hit so it could would defeat the
    engine. So the CURSOR SEAM is used directly instead of the paginator that
    wraps it: `selectors.search` mints and reads its tokens through
    `core.api.pagination`'s `encode_cursor`/`decode_cursor`, which is where
    signing, tenant-binding and the ordering check live. Same envelope, same
    refusals, one implementation.

    `limit` is clamped rather than refused above the ceiling, which is what the
    seam does everywhere else: a client asking for "everything" gets the maximum
    page rather than a refusal it has to learn to handle.
    """
    if request.tenant is None:
        raise HttpError(403, "No account for this request.")
    requested = tuple(part.strip() for part in kinds.split(",") if part.strip())
    # **No `except` here, and its absence is the point.** An earlier version
    # answered an unreachable index with a bare `HttpError(503, ...)` and
    # recorded the residual: no machine-readable `code`, because registering one
    # meant editing `core.exceptions` and `config/api.py`, which that version did
    # not own. This version closes it from both ends. The common case is gone — an
    # unreachable index is a `200` answered from Postgres with
    # `engine="postgres"`, decided by the circuit in `selectors.py` where both
    # doors reach it — and the narrow case that survives (no engine answered at
    # all) is now `core.exceptions.SearchUnavailable`, a registered refusal that
    # `config/api.py` renders at 503 with `code: "search_unavailable"` like every
    # other refusal in the product. A door that caught it to shape its own body
    # would be the fourth copy of a rule with one home.
    return search(
        tenant=request.tenant,
        actor=actor_from_request(request),
        q=q,
        kinds=requested or None,
        cursor=cursor or None,
        limit=limit,
        include_count=include_count,
    )
