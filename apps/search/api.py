"""The HTTP door onto search: one route for every kind, and the route that lists the kinds.

# why-not `from __future__ import annotations`: ninja reads the route signatures at import.
"""

from typing import Annotated

from ninja import Router
from ninja.params.functions import Query as QueryParam

from apps.accounts.auth import API_AUTH
from apps.core.api.acting import acting
from apps.core.api.docs import Tag, refuses
from apps.core.api.pagination import MAX_LIMIT, cursor_page
from apps.core.requests import TenantRequest
from apps.search import registry
from apps.search.schemas import SearchKindOut, SearchKindPage, SearchPage
from apps.search.selectors import get_search_page

#: Named so renaming the app never moves a published URL.
PREFIX = "search"

#: The scope family (ADR ident-7); the key froze the day a token could name it.
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
    """The published vocabulary — the registry `get_search_page` narrows against; both doors."""
    return [SearchKindOut(kind=entry.kind, app=entry.app) for entry in registry.catalogue()]


@router.get("/kinds/", response=SearchKindPage, url_name="search_kind-list")
@refuses("invalid_cursor", "no_acting_scope", "not_found", "rate_limited")
def list_search_kinds_route(
    request: TenantRequest,
    cursor: str = "",
    # The ceiling, published: bare parameters inherit no `Input` schema.
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

    **It does not shrink to what YOU may read**, and that is deliberate: a kind
    you may not read is still a kind this product has, and this list is the
    product's vocabulary rather than your entitlement. The search endpoint is
    where your entitlement applies — it searches the kinds you may read and
    refuses a kind you name and may not.

    Refusals you can get here:

    * `403 no_acting_scope` — the request resolved no account. Send `X-Tenant`
      naming one you belong to.
    * `400 invalid_cursor` — the cursor was edited, or came from a different
      endpoint. Start the walk again without one.
    * `404 not_found` — the cursor was minted for a different account.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    why-not `@paginate`: a third schema for one page; `cursor_page` is the seam both doors call.
    """
    _, tenant = acting(request)
    page = cursor_page(
        kind_catalogue(),
        tenant=tenant,
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
    "forbidden",
    "invalid",
    "invalid_cursor",
    "no_acting_scope",
    "not_found",
    "rate_limited",
    "search_unavailable",
)
def search_route(
    request: TenantRequest,
    q: str = "",
    kinds: str = "",
    cursor: str = "",
    # The ceiling, published: bare parameters inherit no `Input` schema.
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
    this one.** When the answer is empty because you can see nothing — you act
    as no organization in this account — no engine is asked at all, and the page
    still names the engine this deployment searches with. That is on purpose: a page you are not
    entitled to and a page that genuinely matched nothing are the same page,
    down to the byte, so that nobody can use this endpoint to find out whether a
    record they cannot reach exists. Everything else in the body is exactly what
    it says.

    Refusals you can get here:

    * `403 no_acting_scope` — the request resolved no account. Send `X-Tenant`
      naming one you belong to.
    * `403 forbidden` — `kinds` named a kind your role does not include reading.
      Leave `kinds` out to search everything you can read; a kind you may not
      read is simply not in the results.
    * `400 invalid` — `kinds` named something this product cannot search. The
      message says what you sent and lists what it does have;
      `GET /search/kinds/` is the same list. **`403` and `400` are different
      answers on purpose**: `400` means no such kind anywhere, `403` means that
      kind exists and is not yours.
    * `400 invalid_cursor` — the cursor was edited, or came from a different
      endpoint. Start the walk again without one.
    * `404 not_found` — the cursor was minted for a different account.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    * `503 search_unavailable` — **not** the index being down; that is answered
      from Postgres above. This means no engine could answer at all. Retry;
      nothing is wrong with your request.

    ---
    why-not `@paginate`: the engine ranks and windows the hits; there is no queryset to slice.
    """
    actor, tenant = acting(request)
    requested = tuple(part.strip() for part in kinds.split(",") if part.strip())
    return get_search_page(
        tenant=tenant,
        actor=actor,
        q=q,
        kinds=requested or None,
        cursor=cursor or None,
        limit=limit,
        include_count=include_count,
    )
