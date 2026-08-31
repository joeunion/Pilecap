# Negative: a list that pages itself. It never meets `@paginate` — it declares
# `cursor` and `limit` in its own signature and calls `cursor_page` — and it is
# a legitimate shape, which three routes in this tree use for reasons their own
# docstrings give (`api:search_kind-list`, `api:search-query`, `api:meter-list`).
#
# Firing here would mean the only legal way to page is the decorator, which
# would make the seam a tax rather than a contract. The clause asks whether a
# caller can WALK, not which road the author took.


from apps.core.schemas import ListPage, PingOut


class CanaryWalkPage(ListPage):
    """One page of gadgets, from a route that pages itself."""

    items: list[PingOut]


@router.get("/walk/", response=CanaryWalkPage, url_name="gadget-walk")
def canary_gadget_walk(request, cursor: str = "", limit: int | None = None):
    """List gadgets by cursor

    Every gadget the probe app can see, walked by cursor rather than by page
    number, newest first.
    """
    return CanaryWalkPage(items=[], has_more=False, next_cursor=None, count=None)
