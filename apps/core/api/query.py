"""Ordering and search, the two query parameters every list shares.

Both are helpers rather than magic, and both are **allow-listed**, which is the
whole point:

* `ordered_by` refuses a field the route did not name. `?ordering=` straight
  into `.order_by()` lets a client sort by any column and traverse any relation
  (`owner__password`, `tenant__api_tokens__key_hash`) — a full-table sort on an
  unindexed column at best, and a way to read across a join at worst. The
  allow-list is the route's declaration of what it is willing to sort by. It
  also **keeps the selector's own ordering as tie-breakers** rather than
  replacing it, so a promise made below the door survives the door.
* `searched` puts `q` into the fields the route named, with `icontains`, and
  nowhere else.

Neither of them narrows to a tenant. That is deliberate: they take a queryset
that is already `for_tenant(...)`, and a helper that could widen a scope would
be a helper nobody could audit.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models import Model as DjangoModel
from django.db.models import Q, QuerySet

from apps.core.exceptions import Invalid

DESCENDING = "-"

# `.order_by("?")` is "random", and it is a whole ordering rather than a field:
# carrying it forward as a tie-breaker would re-shuffle every group.
RANDOM = "?"


def _tie_breakers(queryset: QuerySet[Any], requested: str) -> tuple[str, ...]:
    """The incoming queryset's own ordering, minus a duplicate of `requested`.

    Read off `query.order_by` — the ordering somebody **asked for** on this
    queryset — and deliberately not off `Meta.ordering`, which is a default
    rather than a promise. A selector that wrote `.order_by("name", "-version")`
    said something; a model's `Meta` saying `["-created_at"]` did not, and
    appending it here would change the SQL of every list route in the tree for
    no property anybody claimed.

    Compared by field name with the direction stripped, so `-name` displaces an
    incoming `name`: the caller asked for a direction and gets it, once.
    Non-string entries (an `F(...).desc()`, a `Random()`) are carried through
    untouched, because they are orderings this helper has no business editing.
    """
    existing = tuple(getattr(queryset.query, "order_by", ()) or ())
    out: list[str] = []
    for entry in existing:
        if not isinstance(entry, str) or entry == RANDOM:
            continue
        if entry.removeprefix(DESCENDING) == requested:
            continue
        out.append(entry)
    return tuple(out)


def ordered_by[M: DjangoModel](
    queryset: QuerySet[M],
    ordering: str | None,
    *,
    allowed: Sequence[str],
    default: str | None = None,
) -> QuerySet[M]:
    """Apply `?ordering=`, from the route's allow-list, or the default.

    A leading `-` reverses, as everywhere else in Django. Anything the route did
    not name is `Invalid` with the allowed values in the message — a client that
    is told what it may sort by can fix its own call.

    **The selector's ordering survives, as tie-breakers** (ADR core-9).
    `.order_by(wanted)` *replaces* a queryset's ordering outright, so a selector
    promising `("name", "-version")` — newest version first within a name — had
    that promise silently deleted the moment a door sorted by name, and two
    versions of one row came back in whatever order the database felt like that
    day. A promise a client cannot see is broken is not a contract.

    So the requested field leads and whatever the incoming queryset already
    ordered by follows it, with **only a duplicate of the requested field
    dropped** — by field name, so asking for `-name` displaces an incoming
    `name` rather than fighting it. Nothing is invented: a queryset with no
    ordering of its own is ordered by exactly what was asked for, which is what
    every caller already got.

    A route that must genuinely *replace* the ordering says so with a parameter
    of its own; there is none today because nothing has needed one.
    """
    wanted = (ordering or default or "").strip()
    if not wanted:
        return queryset
    field = wanted.removeprefix(DESCENDING)
    if field not in allowed:
        raise Invalid(
            {"ordering": [f"Order by one of: {', '.join(sorted(allowed))}."]},
        )
    return queryset.order_by(wanted, *_tie_breakers(queryset, field))


def searched[M: DjangoModel](
    queryset: QuerySet[M],
    q: str | None,
    *,
    fields: Sequence[str],
) -> QuerySet[M]:
    """Apply `?q=` across the fields the route named.

    Case-insensitive `contains` across a handful of text columns: enough for the
    search box a product ships on day one, and deliberately not a search engine.
    When it stops being enough, the answer is Postgres full-text search on a
    `SearchVectorField` — a bigger decision than a helper should make quietly.
    """
    term = (q or "").strip()
    if not term or not fields:
        return queryset
    matches = Q()
    for field in fields:
        matches |= Q(**{f"{field}__icontains": term})
    return queryset.filter(matches)
