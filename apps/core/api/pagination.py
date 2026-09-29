"""The one pagination seam every list rides — cursors, not page numbers.

House rule 3: every list is `@paginate`d. The reason is not tidiness — an
unpaginated list is an endpoint whose cost is set by whoever has the most rows,
and it works fine until the first customer with fifty thousand of them.

## Why a cursor and not `?page=` (ADR core-18)

Offset paging is *wrong*, not merely slow, and that is the argument that moved
it. A list here is ordered by recency, so the churn is at the head: insert or
archive one row between page 1 and page 2 and every later offset shifts by one.
The client is not told. It silently skips a row, or reads one twice, and both
answers look exactly like a correct page. `test_the_walk_never_skips_or_repeats`
in `apps/core/tests/test_pagination.py` plants both.

A **keyset** cursor cannot do that: page 2 is not "rows 51-100", it is "rows
strictly after this one, in this order", and a row that arrives or leaves in
between changes what is *there* without changing where the walk is.

Two other things fall out of it, and they are why the change was worth a
breaking one:

* **The `count(*)` tax becomes a choice.** `has_more` is answered by fetching
  `limit + 1` rows and noticing there was an extra — no second statement. A
  client that genuinely wants a total asks with `?include_count=true` and pays
  for it deliberately. Every list used to pay on every request, including the
  many that never render a number.
* **The cursor is opaque, signed and tenant-bound.** It carries no offset a
  client can arithmetic on, so nothing outside this module has an opinion about
  what page 3 means, and the shape can change later without breaking anyone.

## What is on the wire

    {"items": [...], "has_more": true, "next_cursor": "eyJ2Ijox...", "count": null}

* **`?cursor=`** — the token the previous response's `next_cursor` gave you.
  Omit it for the first page. Never build one; it is opaque by contract.
* **`?limit=`** — how many items, `API_PAGE_SIZE` by default, `MAX_LIMIT` at
  most. Without a ceiling the parameter is just a slower way to ask for
  everything.
* **`?include_count=true`** — adds the exact scoped `count`. Off by default;
  `count` is `null` when it was not asked for, which is a different fact from
  zero and is said differently.

`?page=` and `?page_size=` are **gone**, not deprecated (the owner's ruling of
2026-08-24: "hard cut now, we aren't production"). The licence was the empty
consumer register; after the first external consumer this would have been a
versioning event.

## What the token holds, and what each part refuses

A cursor is `<payload>.<signature>`, both URL-safe base64 without padding.
The payload is compact JSON:

* `v` — the token version. A token minted by a future shape is refused rather
  than misread.
* `t` — the acting tenant's id. **A cursor from another tenant answers
  `not_found`**, never `forbidden` and never a page: the refusal that told them
  apart would confirm the walk exists. Not-there and not-yours are one answer
  here for the same reason they are everywhere else.
* `c` — **the collection the token was minted for.** A keyset is a
  position in one list; presented to a different list it is a `WHERE` clause
  over rows it has never seen, and the answer is `200 OK` with an arbitrary
  prefix of the second list silently missing — measured before this field
  existed, a `/widgets/` cursor handed to `/invitations/` returned two of three
  invitations and said nothing about the third. So it is refused with
  `invalid_cursor`, which is the promise the refusal's own published sentence
  has been making all along: *"That cursor is not one this API issued for **this
  list**."* The key is **derived, never declared by a caller** — the queryset's
  model (`example.widget`), or the item type of the one list that is not a
  queryset — so every paginated route in every app inherits the binding without
  a line of its own, and the two doors keep minting byte-identical tokens for
  one page.
* `o` — the ordering the token was minted under, as `("-created_at", "id")`.
  A cursor replayed against a *different* `?ordering=` is meaningless — the
  keyset names a position in a sequence that no longer exists — so it is
  refused with `invalid_cursor` rather than silently answering from the wrong
  place.
* `k` — the ordering key values of the last item on the page that produced it.

The signature is `salted_hmac` over the payload bytes, compared with
`hmac.compare_digest`. **A tampered cursor is a clean refusal** rather than an
arbitrary `WHERE` clause: without it, `k` is a client-controlled filter and the
ordering fields become an oracle a caller can binary-search.

## Ordering has to be total, and this module makes it so

A keyset only works if no two rows share a key. Every ordering here is extended
with the primary key as a final tiebreak (`_total_ordering`), which is what
lets `(created_at, id)` name exactly one row even when a hundred rows share a
millisecond.

**Nullable ordering fields are handled, not assumed away.** `sent_at`,
`finished_at`, `delivered_at` and `dead_lettered_at` are all in a route's
allow-list and all nullable, and a naive `WHERE sent_at < NULL` matches
nothing. `_after` follows Postgres' own default null placement — nulls first
descending, nulls last ascending — so the walk crosses the null boundary
exactly once and in the right direction.
"""

from __future__ import annotations

import hmac
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from inspect import signature
from typing import Any, get_args, overload
from uuid import UUID

from django.conf import settings
from django.db.models import Model as DjangoModel
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils.crypto import salted_hmac
from ninja import Schema
from ninja.pagination import PaginationBase
from pydantic import Field

from apps.core.exceptions import Invalid, InvalidCursor, NotFound
from apps.core.schemas import ActsPage, ListPage

#: What a caller is told when a cursor is signed, valid, and somebody else's.
#: Spelled once here because every paginated door inherits it, and worded to
#: match the promise three route docstrings already publish.
FOREIGN_CURSOR = (
    "That cursor was minted for a different account. Start the walk again without a cursor."
)

#: And what they are told when it is signed, theirs, and minted on another list.
#: A separate sentence from the ordering one below it because it is a
#: separate mistake with a separate fix: the ordering refusal says "you changed
#: `?ordering=` mid-walk", this one says "you are reading a different list".
#: Neither is an oracle — both are facts about the CURSOR, never about rows.
FOREIGN_COLLECTION = (
    "This cursor was minted for a different list. Start the walk again without a "
    "cursor, on the list you are reading."
)

#: The `c` of a walk that identifies itself some other way, and the DEFAULT of
#: the two token functions below.
#:
#: There is exactly one such caller and it is not a list of rows:
#: `apps/search/selectors.py` pages a RANKED result set, so the only coordinate
#: its cursor can name is how far into that ranking the page starts, and it
#: already declares `CURSOR_ORDERING = ("offset",)` for precisely this reason —
#: "a cursor minted for a search can never be replayed against a list door, and
#: vice versa", in its own words. Its discriminator is the ordering token, and it
#: works: an `("offset",)` cursor meets every list's ordering check.
#:
#: So the default is a value that no derivation can produce (`_collection_key`
#: never returns it), which makes a search cursor foreign to every list and every
#: list's cursor foreign to search — without search having to
#: TYPE a collection name. A declared name is the thing this design refuses:
#: derived keys cannot be forgotten and typed ones can.
UNBOUND_COLLECTION = ""

#: What a built list yields when it is empty and there is no item to read a type
#: off. Deliberately unequal to `UNBOUND_COLLECTION` and to every derived key, so
#: a cursor presented to an empty catalogue is refused rather than honoured on an
#: identity nothing could confirm. No minted token can carry it: a token is only
#: cut when a page had items.
UNIDENTIFIED_COLLECTION = "\x00unidentified"

# The ceiling on `?limit=`. A client may ask for less; nothing gets more.
MAX_LIMIT = 200

#: The token shape. Bumped when the payload's meaning changes; a token from a
#: version this build does not know is `invalid_cursor`, never a guess.
#:
#: **Bumped to 2 when the collection field `c` was added.** A version-1 token
#: has no collection in it,
#: so this build cannot tell which list it was cut on — and the honest answer to
#: a token whose meaning it cannot read is the one this field exists to give,
#: rather than a page assembled on a guess. Outstanding v1 cursors refuse with
#: `invalid_cursor` and the client starts the walk again, which is what the
#: refusal's remedies already say to do.
CURSOR_VERSION = 2

#: Domain separation for the signing key, so a cursor signature can never be
#: replayed as any other `salted_hmac` in the product.
_KEY_SALT = "apps.core.api.pagination.cursor"

DESCENDING = "-"


# --- the page a seam hands back ------------------------------------------------


@dataclass(frozen=True, slots=True)
class CursorPage[T]:
    """One page, and everything the envelope needs, for either door.

    `count` is `None` unless the caller asked for it — the whole point of the
    change is that the total costs a statement and is therefore opt-in. `None`
    means "not counted", which is not zero, and the wire says `null` rather
    than pretending otherwise.
    """

    items: list[T]
    has_more: bool
    next_cursor: str | None
    count: int | None
    #: The LIST's own acts (`core.verbs.page_acts`) — set only when the caller
    #: handed `cursor_page` an actor, and `None` otherwise.
    allowed_acts: tuple[str, ...] | None = None


# --- the token ----------------------------------------------------------------


def _b64encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return urlsafe_b64decode(text.encode("ascii") + padding.encode("ascii"))


def _signature(payload: bytes) -> str:
    return _b64encode(salted_hmac(_KEY_SALT, payload, algorithm="sha256").digest())


def _jsonable(value: Any) -> Any:
    """One ordering key value, in a form JSON can hold and the ORM can filter by.

    Deliberately narrow. A key is an ordering column, and an ordering column is
    a scalar; anything else in a cursor would be a shape somebody is about to
    start parsing.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date | UUID | Decimal):
        return str(value)
    return str(value)


def encode_cursor(
    *,
    tenant_key: str,
    collection: str = UNBOUND_COLLECTION,
    ordering: Sequence[str],
    keys: Sequence[Any],
) -> str:
    """Mint the token that names "everything strictly after this row"."""
    payload = json.dumps(
        {
            "v": CURSOR_VERSION,
            "t": tenant_key,
            "c": collection,
            "o": list(ordering),
            "k": [_jsonable(key) for key in keys],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{_b64encode(payload)}.{_signature(payload)}"


def decode_cursor(
    token: str,
    *,
    tenant_key: str,
    collection: str = UNBOUND_COLLECTION,
    ordering: Sequence[str],
) -> list[Any]:
    """The key values a token names, or a refusal saying which part failed.

    Four refusals, and they are different questions on purpose:

    * unreadable, unsigned, tampered with, or minted under a token version this
      build does not know — `invalid_cursor`. The client built or edited a
      token, and the fix is to stop doing that and follow `next_cursor`.
    * minted in **another tenant** — `not_found`. Never `forbidden`: a refusal
      that distinguished a foreign cursor from a malformed one would confirm
      that the other tenant's walk exists.
    * minted on **another collection** — `invalid_cursor`, with its own sentence.
      Checked BEFORE the ordering, because the two lists usually agree
      about ordering — the house shape is `-created_at` everywhere — and a
      caller reading a different list needs to be told THAT, not told about sort
      order.
    * minted under a **different ordering** — `invalid_cursor` too, with its own
      sentence: the token is honest and simply does not describe a position in
      the sequence being asked for.

    The tenant check stays first of the three that can tell a client something.
    Not-yours outranks anything else this function could say about a token,
    because everything below it is a fact about *this deployment's* lists, and
    saying one to somebody holding another tenant's token would be a sentence
    about a walk they cannot reach.
    """
    encoded, _, offered = token.partition(".")
    if not encoded or not offered:
        raise InvalidCursor()
    try:
        payload = _b64decode(encoded)
    except (ValueError, TypeError) as error:
        raise InvalidCursor() from error
    if not hmac.compare_digest(_signature(payload), offered):
        raise InvalidCursor()
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:  # pragma: no cover - signed, so unreachable
        raise InvalidCursor() from error
    if not isinstance(decoded, dict) or decoded.get("v") != CURSOR_VERSION:
        raise InvalidCursor()
    if decoded.get("t") != tenant_key:
        # Signed, so it IS one of ours — and it is somebody else's. Same answer
        # as any other row this tenant cannot reach.
        #
        # **And it SAYS so.** This was `raise NotFound()`, which carries
        # the class default — the bare words "Not Found" — while three route
        # docstrings promised "the cursor was minted for a different account".
        # It was the last refusal in the tree whose detail was a class fallback
        # rather than a sentence, and every paginated door inherited it: a
        # caller who pasted a colleague's cursor got a 404 that read exactly
        # like a deleted row.
        #
        # Saying which of the two it is gives nothing away. Not-there and
        # not-yours are deliberately ONE ANSWER here (`core.exceptions`, and the
        # anti-oracle argument in `core.middleware`), and this sentence keeps
        # that: it names the CURSOR as the thing that does not belong, never the
        # rows, so it is true whether or not the other account's list exists.
        raise NotFound(FOREIGN_CURSOR)
    if decoded.get("c") != collection:
        # Signed, current, theirs — and cut on a different list. Before
        # this branch the token decoded cleanly here and its `k` became a keyset
        # filter over rows it had never seen: `200 OK`, a perfectly shaped
        # envelope, and an arbitrary prefix of the list quietly absent. Silence
        # is the one answer a paginator must never give, because a client walking
        # a list has no way to notice it.
        raise InvalidCursor({"cursor": [FOREIGN_COLLECTION]})
    if list(decoded.get("o") or ()) != list(ordering):
        raise InvalidCursor(
            {
                "cursor": [
                    "This cursor was minted under a different sort order. "
                    "Start the walk again without a cursor, or keep the ordering "
                    "you started with."
                ]
            }
        )
    keys = decoded.get("k")
    if not isinstance(keys, list) or len(keys) != len(ordering):
        raise InvalidCursor()
    return list(keys)


# --- the keyset ---------------------------------------------------------------


def _term(token: str) -> tuple[str, bool]:
    """One ordering token as `(field, descending)`."""
    return (token.removeprefix(DESCENDING), token.startswith(DESCENDING))


def _total_ordering(queryset: QuerySet[Any]) -> tuple[str, ...]:
    """The queryset's own ordering, made total by the primary key.

    Read off `query.order_by` — what somebody actually asked this queryset for
    — falling back to the model's `Meta.ordering` when nothing did, because a
    queryset with no ordering at all is a database's whim and a cursor over one
    would be nonsense.

    **The `pk` is appended, and `cursor_page` then re-applies the whole tuple to
    the queryset.** That second half is not tidiness: a route ordered only by
    `-created_at` produces SQL with no tiebreak, so two rows sharing a timestamp
    come back in whatever order the plan felt like — and a cursor cut on
    `(created_at, id)` would name a position the next page's SQL does not agree
    about. The keyset and the `ORDER BY` have to be the same tuple or the walk
    is exactly the thing this module exists to prevent.

    A non-string ordering entry — an `F(...).desc()`, a `Random()` — is refused
    rather than dropped, because dropping one would silently re-sort the list.
    No route's allow-list produces one today; the day one does, it should arrive
    as this error rather than as a bug report about a list in the wrong order.
    """
    requested = tuple(getattr(queryset.query, "order_by", ()) or ())
    if not requested:
        requested = tuple(queryset.model._meta.ordering or ())
    fields: list[str] = []
    for entry in requested:
        if not isinstance(entry, str) or entry in {"?", ""}:
            raise ValueError(
                f"cursor pagination cannot encode the ordering entry {entry!r} — a cursor "
                "names a position in a sequence, and this one has no name to encode"
            )
        if _term(entry)[0] in {_term(seen)[0] for seen in fields}:
            continue
        fields.append(entry)
    pk_name = queryset.model._meta.pk.name if queryset.model._meta.pk is not None else "pk"
    if pk_name not in {_term(entry)[0] for entry in fields}:
        fields.append(pk_name)
    return tuple(fields)


def _equal(field: str, key: Any) -> Q:
    return Q(**{f"{field}__isnull": True}) if key is None else Q(**{field: key})


def _strictly_after(field: str, descending: bool, key: Any) -> Q | None:
    """Rows that come after `key` on this one column, or `None` for "nothing does".

    Postgres places nulls first for `DESC` and last for `ASC`, and Django does
    not override that, so:

    * ascending, `key` is null — everything null is level with it and everything
      non-null came before. Nothing is after: `None`.
    * ascending, `key` is a value — larger values, then the nulls at the end.
    * descending, `key` is null — the nulls lead, so every non-null row is after.
    * descending, `key` is a value — smaller values only; the nulls already went.
    """
    if descending:
        if key is None:
            return Q(**{f"{field}__isnull": False})
        return Q(**{f"{field}__lt": key})
    if key is None:
        return None
    return Q(**{f"{field}__gt": key}) | Q(**{f"{field}__isnull": True})


def _after(ordering: Sequence[str], keys: Sequence[Any]) -> Q:
    """The lexicographic "strictly after this key tuple", as one `Q`.

    `(a, b, c) > (ka, kb, kc)` expanded the long way — `a > ka`, or `a == ka and
    b > kb`, or `a == ka and b == kb and c > kc` — rather than as a row-value
    comparison, because a row-value comparison cannot express the null
    placement above and Django has no portable spelling for one.
    """
    clause = Q(pk__in=())
    for index, token in enumerate(ordering):
        field, descending = _term(token)
        after = _strictly_after(field, descending, keys[index])
        if after is None:
            continue
        branch = after
        for earlier, earlier_key in zip(ordering[:index], keys[:index], strict=True):
            branch = _equal(_term(earlier)[0], earlier_key) & branch
        clause |= branch
    return clause


def _key_values(row: Any, ordering: Sequence[str]) -> list[Any]:
    """The row's own values for each ordering column.

    A relation traversal (`owner__email`) is refused rather than read as `None`:
    `getattr` would answer `None` for one and the walk would quietly page
    through a single key value forever. No route's allow-list names one today,
    and the day one does it should arrive as this error and not as a bug report
    about a list that repeats itself.
    """
    values: list[Any] = []
    for token in ordering:
        field = _term(token)[0]
        if "__" in field:
            raise ValueError(
                f"cursor pagination cannot encode the related ordering column {field!r} — "
                "order by a column on the model itself, or add an annotation for it"
            )
        values.append(getattr(row, field))
    return values


# --- the one function both doors call ------------------------------------------


def _tenant_key(tenant: Any) -> str:
    """What a cursor is bound to. `""` for a list nothing owns."""
    return "" if tenant is None else str(getattr(tenant, "pk", tenant))


def _collection_key(rows: Any, queryset: QuerySet[Any] | None) -> str:
    """Which list this cursor belongs to — DERIVED, never declared.

    Derived and not a parameter, and that is the whole design. A `collection=`
    argument would be a line every list route in every app had to remember to
    write, checked by nothing, and a route that forgot it would be back to the
    silence this exists to end. Read off what is being paged instead, and every
    paginated route in the product inherits the binding with no edit anywhere —
    which is what lets the derived pass in `apps/core/tests/test_pagination.py`
    drive the whole census rather than a list somebody maintains.

    **The identity is the thing in the list, both times.** A queryset's is its
    model's label (`example.widget`); a built list's is its item type
    (`apps.search.schemas.SearchKindOut`), because the one such list here is a
    generated catalogue of schema objects and its rows have no model. The two
    doors therefore derive the same key for one page and go on minting
    byte-identical tokens — a route-shaped key would have made a REST cursor
    refuse on the MCP twin, which is a parity break dressed as a fix.

    An empty built list yields `UNIDENTIFIED_COLLECTION`, which no minted token
    can hold, so a cursor presented to one is refused rather than honoured on an
    identity nothing could confirm. This function never returns
    `UNBOUND_COLLECTION` either — that value belongs to the one caller that pages
    something which is not a list of rows at all.

    *Declared limit, and it is real:* two collections over ONE model share a key.
    `/deliveries/` and `/dead-letters/` are both `events.delivery`, so a cursor
    from either is accepted by the other under a matching `?ordering=`. The rows
    are the same rows in the same order and the keyset still names a real
    position in it, which is why this is a narrower hole than the
    collection-mismatch case above — but it is a hole, and it is written down
    here rather than implied.
    """
    if queryset is not None:
        meta = queryset.model._meta
        return f"{meta.app_label}.{meta.model_name}"
    first = next(iter(rows), None)
    if first is None:
        return UNIDENTIFIED_COLLECTION
    kind = type(first)
    return f"{kind.__module__}.{kind.__qualname__}"


def _sequence_after(rows: Sequence[Any], ordering: Sequence[str], keys: Sequence[Any]) -> list[Any]:
    """The in-memory twin of `_after`, for a list that was never a queryset.

    One list is built in Python rather than read (`GET /events/catalogue/`, a
    generated catalogue of event names), and it is paged by the same seam so
    that a client cannot tell which lists are rows and which are not. Keys are
    compared as the JSON round-trip left them, which is exact for the strings
    and numbers an in-memory catalogue orders by — the declared limit of this
    path, and the reason no queryset takes it.
    """
    out: list[Any] = []
    for row in rows:
        values = [_jsonable(value) for value in _key_values(row, ordering)]
        after = False
        for index, token in enumerate(ordering):
            descending = _term(token)[1]
            mine, theirs = values[index], keys[index]
            if mine == theirs:
                continue
            if mine is None:
                after = descending is False
            elif theirs is None:
                after = descending is True
            else:
                after = mine < theirs if descending else mine > theirs
            break
        if after:
            out.append(row)
    return out


@overload
def cursor_page[M: DjangoModel](
    rows: QuerySet[M],
    *,
    tenant: Any,
    cursor: str | None = ...,
    limit: int | None = ...,
    include_count: bool = ...,
    ordering: Sequence[str] | None = ...,
    actor: Any = ...,
) -> CursorPage[M]: ...


@overload
def cursor_page[T](
    rows: Sequence[T],
    *,
    tenant: Any,
    cursor: str | None = ...,
    limit: int | None = ...,
    include_count: bool = ...,
    ordering: Sequence[str] | None = ...,
    actor: Any = ...,
) -> CursorPage[T]: ...


def cursor_page(
    rows: Any,
    *,
    tenant: Any,
    cursor: str | None = None,
    limit: int | None = None,
    include_count: bool = False,
    ordering: Sequence[str] | None = None,
    actor: Any = None,
) -> CursorPage[Any]:
    """One page of `rows`, and the token that names the next one.

    Two overloads and one body, because the two callers are genuinely different
    shapes: every list door hands it a `QuerySet` of rows, and exactly one
    (`GET /events/catalogue/`) hands it a built list of schema objects. The
    overloads are what keep `page.items` typed as what went in.

    **The whole of the cursor logic in this product lives here.** REST reaches
    it through `CursorPagination` below and MCP calls it directly, which is what
    makes house rule 17's twins byte-equal by construction rather than by two
    people being careful: there is no second implementation to drift from.

    `rows` arrives already scoped and already ordered — `for_tenant(...)
    .visible_to(...)`, then the route's `ordered_by(...)`. This function narrows
    and slices and does nothing else; a paginator that could widen a scope would
    be a paginator nobody could audit (`apps/core/api/query.py` says the same
    about ordering, for the same reason).

    `limit + 1` rows are fetched and the extra one is thrown away: that is
    `has_more`, and it is why the default response issues no `COUNT` statement.
    """
    if limit is not None and limit > MAX_LIMIT:
        # THE SAME REFUSAL THE HTTP DOOR MAKES, from the other side.
        # `CursorPagination.Input` refuses an over-limit query before a route
        # runs, but the MCP door calls this function directly with whatever the
        # tool was handed — so a ceiling enforced only in the schema would be a
        # ceiling one of the two doors did not have. This is the seam both
        # doors share, which is why the refusal lives here as well.
        raise Invalid(
            {
                "limit": [
                    f"A page may carry at most {MAX_LIMIT} items; {limit} was asked for. "
                    f"Walk the list with `cursor` instead of asking for it all at once."
                ]
            }
        )
    size = max(limit or int(settings.API_PAGE_SIZE), 1)
    queryset: QuerySet[Any] | None = rows if isinstance(rows, QuerySet) else None
    if ordering is None:
        if queryset is None:
            raise ValueError("A list that is not a queryset must name its own ordering.")
        ordering = _total_ordering(queryset)
        # The keyset and the ORDER BY, made the same tuple. See `_total_ordering`:
        # a route ordered only by `-created_at` emits SQL with no tiebreak, and a
        # cursor cut on `(created_at, id)` would name a position the next page's
        # plan does not agree about.
        queryset = queryset.order_by(*ordering)
        rows = queryset

    tenant_key = _tenant_key(tenant)
    collection = _collection_key(rows, queryset)

    narrowed: QuerySet[Any] | Sequence[Any] = rows
    if cursor:
        keys = decode_cursor(
            cursor, tenant_key=tenant_key, collection=collection, ordering=ordering
        )
        narrowed = (
            queryset.filter(_after(ordering, keys))
            if queryset is not None
            else _sequence_after(list(rows), ordering, keys)
        )

    window = list(narrowed[: size + 1])
    has_more = len(window) > size
    items = window[:size]
    next_cursor = (
        encode_cursor(
            tenant_key=tenant_key,
            collection=collection,
            ordering=ordering,
            keys=_key_values(items[-1], ordering),
        )
        if has_more and items
        else None
    )
    count: int | None = None
    if include_count:
        # The one place a `COUNT` is still issued, and only because somebody
        # asked. Counted over `rows`, not over `narrowed`: a total that shrank
        # as you walked would not be a total.
        count = queryset.count() if queryset is not None else len(list(rows))
    acts: tuple[str, ...] | None = None
    if actor is not None:
        # THE ACTS, for a family noun's list (`ActsPagination`, and an MCP twin
        # that passes its actor): every item's `allowed_acts` and the list's own.
        # Here, once, so both doors answer the same acts by construction.
        from apps.core.verbs import page_acts, with_allowed_acts

        with_allowed_acts(items, actor)
        acts = page_acts(actor, queryset.model) if queryset is not None else ()
    return CursorPage(
        items=items, has_more=has_more, next_cursor=next_cursor, count=count, allowed_acts=acts
    )


# --- the REST door -------------------------------------------------------------


class CursorPagination(PaginationBase):
    """`?cursor=`, `?limit=` and `?include_count=`, over `cursor_page`.

    Thin on purpose. Everything that decides anything is in `cursor_page`, so
    the HTTP door and the MCP door are the same walk and not two walks that
    agree today.
    """

    class Input(Schema):
        cursor: str | None = None
        # `le=MAX_LIMIT`, and it does two things at once. It PUBLISHES
        # the ceiling — the schema said `{minimum: 1}` and nothing else while
        # the prose promised 200, so a generated client had no way to know the
        # number existed — and it REFUSES a request above it instead of
        # clamping.
        #
        # The clamp was the lie. `?limit=5000` came back with 200 rows and no
        # signal of any kind: no header, no field, no refusal — so a client
        # paging by "I asked for 5000 and got 200, therefore I have them all"
        # silently stopped at the first page. Refusing costs that client one
        # 400 naming the field; clamping cost it the rest of the data. (400 and
        # not 422: a query parameter is not a body, and the sibling `?limit=0`
        # refusal has always answered 400 `invalid` — two limit refusals with
        # two status codes for one class of mistake would be a worse contract
        # than the one being fixed. 422 was considered; 400 is the
        # settled answer.)
        limit: int | None = Field(None, ge=1, le=MAX_LIMIT)
        include_count: bool = False

    class Output(ListPage):
        """The envelope, and the one `@paginate` builds `Paged<Out>` out of.

        A subclass of `core.schemas.ListPage` and not a second declaration of
        its fields: the MCP `*Page` schemas inherit the same class, so the two
        doors cannot come to disagree about the envelope. Ninja requires the
        paginator to name its own `Output`, which is the only reason this is a
        class here at all.
        """

    def __init__(self, limit: int | None = None, **kwargs: Any) -> None:
        self.limit = limit
        super().__init__(**kwargs)

    def paginate_queryset(
        self,
        queryset: QuerySet[DjangoModel],
        pagination: Any,
        request: HttpRequest,
        **params: Any,
    ) -> Any:
        page = cursor_page(
            queryset,
            tenant=getattr(request, "tenant", None),
            cursor=pagination.cursor,
            limit=pagination.limit or self.limit,
            include_count=pagination.include_count,
            ordering=None if isinstance(queryset, QuerySet) else self.sequence_ordering(queryset),
        )
        return {
            self.items_attribute: page.items,
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
            "count": page.count,
        }

    #: What an in-memory catalogue is ordered by when its shape declares
    #: nothing. `GET /events/catalogue/` is the route this was written for and
    #: `name` is unique there, so it is total on its own.
    SEQUENCE_ORDERING: tuple[str, ...] = ("name",)

    @staticmethod
    def sequence_ordering(rows: Sequence[Any]) -> tuple[str, ...]:
        """The ordering of a route that returns a built list rather than rows.

        **Declared by the shape, and that is the parameterisation this function
        said it was waiting for.** It returned a hardcoded `("name",)` while
        exactly one route in the tree built its own list; the roles and
        permissions catalogues are the second and third, and neither is ordered
        by a display name — a role's `name` is renamable and not unique, so
        paging over it would skip and repeat rows the day two roles share one.

        A row class says what it is totally ordered by with a
        `cursor_ordering` class attribute; anything that declares nothing keeps
        the default. Read off the FIRST row rather than passed in, because the
        paginator is chosen by a decorator at import time and the rows are the
        only thing it holds — and an empty list has nothing to page, so the
        default is never wrong there.

        **The field it names must be TOTAL** (unique across the list). A cursor
        is the last row's key; a tie means the next page starts in the middle of
        the tied group and rows on either side of the cut are lost or repeated.
        `key` is unique in both new catalogues by construction.
        """
        if not rows:
            return CursorPagination.SEQUENCE_ORDERING
        declared = getattr(type(rows[0]), "cursor_ordering", None)
        if declared is None:
            return CursorPagination.SEQUENCE_ORDERING
        return tuple(declared)


class ActsPagination(CursorPagination):
    """`CursorPagination` for a family noun's list: every item's acts, and the list's.

        @router.get("/", response=list[WidgetOut], url_name="widget-list")
        @paginate(ActsPagination)
        def list_widgets_route(request, ...): ...

    The envelope gains `allowed_acts` (the LIST's — `create` when the actor may,
    at the hat) and every item's `allowed_acts` is set before the `Out` reads it
    (`core.verbs.with_allowed_acts`), so a face draws the create act, the empty
    state's door and each row's acts from the server's answer. The MCP twin
    passes its actor to `cursor_page` and answers an `ActsPage` — the same seam,
    so the two doors cannot disagree about who may do what.
    """

    class Output(ActsPage):
        """The envelope plus the list's own acts. See `core.schemas.ActsPage`."""

    def paginate_queryset(
        self,
        queryset: QuerySet[DjangoModel],
        pagination: Any,
        request: HttpRequest,
        **params: Any,
    ) -> Any:
        from apps.core.actor import actor_from_request

        page = cursor_page(
            queryset,
            tenant=getattr(request, "tenant", None),
            cursor=pagination.cursor,
            limit=pagination.limit or self.limit,
            include_count=pagination.include_count,
            ordering=None if isinstance(queryset, QuerySet) else self.sequence_ordering(queryset),
            actor=actor_from_request(request),
        )
        return {
            self.items_attribute: page.items,
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
            "count": page.count,
            "allowed_acts": list(page.allowed_acts or ()),
        }


# --- the one predicate three instruments read (ADR core-24) --------------------
#
# Three instruments used to answer "is this route paginated?" for themselves, off
# two different PRIVATE ninja attributes, and all three answered wrong about the
# same three routes:
#
# * rule 3's census (`apps/core/checks.py`) — `_ninja_contribute_args`;
# * the docs derivation (`config/api.py`) — `_ninja_is_paginated`;
# * `manage.py introspect`'s `paginated` column — `_ninja_contribute_args`.
#
# All three markers say the same thing: **`@paginate` was applied**. None of them
# says what a caller actually experiences, which is whether the route ANSWERS THE
# CURSOR ENVELOPE. A route may reach `cursor_page` directly and return a `*Page`
# schema — three do (`api:search_kind-list`, `api:search-query`, `api:meter-list`),
# each for a stated reason in its own docstring — and every one of those markers
# is absent on all three. So the census did not see them, the document derived no
# `invalid_cursor` for them, and `introspect` published `paginated: false` about a
# route whose body is `{items, has_more, next_cursor, count}`.
#
# The failure that matters is not the wrong column. It is that FIXING ONE LEAVES
# TWO BLIND: three private re-derivations of one fact drift apart silently, and
# nothing anywhere fails when they do. Hence one predicate, here, beside the
# envelope it is about, read by all three — sever it and all three go red at
# once, which `apps/core/tests/test_pagination_seam.py` plants and proves.
#
# It reads the RESPONSE MODEL rather than a decorator marker, because the
# response model is the thing the caller meets: `@paginate` builds its
# `Paged<X>Out` out of `CursorPagination.Output`, which is a `ListPage`, and a
# direct-cursor route declares a `*Page` schema, which is also a `ListPage`. One
# class, both roads, no list of route names anywhere.


def _annotation_members(annotation: Any) -> list[Any]:
    """An annotation flattened into the concrete types a response may be.

    `X`, `X | None` and `Union[X, Y]` all arrive here; nested unions are walked
    because `get_args` on `X | None | Y` is already flat but a `Literal` or a
    generic alias is not, and a member this cannot understand is simply not a
    class and falls out of the `issubclass` test below.
    """
    args = get_args(annotation)
    if not args:
        return [annotation]
    flattened: list[Any] = []
    for arg in args:
        flattened.extend(_annotation_members(arg) if get_args(arg) else [arg])
    return flattened


def answers_cursor_envelope(operation: Any) -> bool:
    """Whether this route's success response IS the cursor envelope.

    True for a route that carries `@paginate(CursorPagination)` and for one that
    calls `cursor_page` itself and declares a `*Page` schema, because the
    question asked is about the body a caller receives and those two are the same
    body. False for everything else, including a bare `list[X]` — an unpaginated
    list is exactly what house rule 3 is about and is not the envelope.

    Takes a ninja `Operation` — every one of the three readers already holds one
    — and reads its 2xx response models. Nothing here knows a route by name.
    """
    models = getattr(operation, "response_models", None) or {}
    for status, model in models.items():
        if not isinstance(status, int) or not (200 <= status < 300):
            continue
        field = (getattr(model, "model_fields", None) or {}).get("response")
        if field is None:
            continue
        for member in _annotation_members(field.annotation):
            if isinstance(member, type) and issubclass(member, ListPage):
                return True
    return False


def offers_pagination_controls(operation: Any) -> bool:
    """Whether a caller can actually WALK this route — `?cursor=` and `?limit=`.

    The other half of house rule 3, and a separate question from the one above:
    a route may answer the envelope and still give nobody a way to ask for page
    two, which is an envelope with a dead `next_cursor` in it. `@paginate`
    contributes both parameters off `CursorPagination.Input`; a direct-cursor
    route declares them in its own signature, which is why both roads are read.

    `_ninja_is_paginated` and not `_ninja_contribute_args`: the second is ninja's
    generic "this decorator adds arguments" marker and says nothing about
    pagination — reading it is how the census came to treat *any* contributing
    decorator as a paginator.
    """
    view = getattr(operation, "view_func", None)
    if view is None:
        return False
    if getattr(view, "_ninja_is_paginated", False):
        return True
    try:
        parameters = set(signature(view).parameters)
    except (TypeError, ValueError):  # pragma: no cover - a non-introspectable view
        return False
    return {"cursor", "limit"} <= parameters
