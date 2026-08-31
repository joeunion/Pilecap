# Planted: a route that ANSWERS the cursor envelope and gives nobody a way to
# ask for page two. No `@paginate`, no `cursor`, no `limit` — so the response
# carries a `next_cursor` field that no parameter can ever spend.
#
# The `list[` string-match this clause used to be could not see it: the response
# is `{items, has_more, next_cursor, count}`, which contains no `list[` anywhere.
# On this tree that match saw ZERO routes, because every real list already
# answers the envelope — the check was firing happily against a planted bare
# list and enforcing nothing at all against the registry.


from apps.core.schemas import ListPage, PingOut


class CanaryEnvelopePage(ListPage):
    """One page of pings, in the envelope shape and with no way to walk it."""

    items: list[PingOut]


@router.get("/envelope/", response=CanaryEnvelopePage, url_name="canary-envelope-list")
def canary_envelope_list(request):
    return CanaryEnvelopePage(items=[], has_more=False, next_cursor=None, count=None)
