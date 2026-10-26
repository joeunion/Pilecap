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

**A retired query parameter is declared, never re-typed.** A list that stopped
accepting a parameter declares it beside `PREFIX` and `TAGS` in its `api.py` —
`RETIRED_QUERY: dict[str, RetiredQuery]`, the retired name mapped to the live
parameter to ask with instead and the one sentence a caller reads. Three readers
defer to that one declaration: the route refuses it (`refuse_retired_query`),
the published document marks it `deprecated` (`config/api.py`), and a product's
strict-query seam asks `retired_query_of` before refusing a parameter the route
does not take, so the route's own sentence is the one that answers.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from django.db.models import Model as DjangoModel
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from pydantic import BaseModel

from apps.core.exceptions import Invalid
from apps.core.roads import road

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


@dataclass(frozen=True)
class RetiredQuery:
    """A query parameter a list no longer takes: the live one to ask with, and why.

    `instead` is the name of the parameter the list takes now; `reason` is the
    one sentence a caller reads, in the refusal and in the published document
    alike. A module declares `RETIRED_QUERY: dict[str, RetiredQuery]` keyed by
    the retired name; a module with nothing retired declares nothing.
    """

    instead: str
    reason: str


#: The archive family's retired switch: `?archived=` asked for the closed rows
#: before `?show=` was the one reader of the archived cut. Every archivable list
#: that once took it declares THIS value, so the refusal is one sentence.
ARCHIVED_SWITCH = RetiredQuery(
    instead="show",
    reason=(
        "`archived` is not a parameter of this list. Send `show=archived` for the "
        "archived ones, `show=all` for both, or leave it out for the live ones."
    ),
)


def refuse_retired_query(request: HttpRequest, retired: Mapping[str, RetiredQuery]) -> None:
    """A retired query parameter is `400 invalid` naming the live one, never silently ignored.

    The refusal names the parameter to ask with instead, not the retired one: the
    caller's fix is to send `instead`, and `errors` keys the field it should
    edit. Checked in name order, so two retired parameters sent at once answer
    one refusal, the same one every time.
    """
    for name in sorted(retired):
        if name in request.GET:
            entry = retired[name]
            raise Invalid({entry.instead: [entry.reason]})


@road("takes_query", example="apps/core/api/query.py::retired_query_of")
def offers_query(operation: Any, name: str) -> bool:
    """Whether this operation takes `?<name>=` — a bare query parameter or a filter schema's field.

    Read off the bound ninja operation's parameter models, so it answers what
    the mounted route really accepts rather than what its docstring says. The
    one reader of the question: `retired_query_of` narrows a retirement with
    it, and house rules 41 and 74 (`apps/core/checks.py`) ask it of a
    documented `?name=` and of an archivable noun's `?show=`.
    """
    for param_model in getattr(operation, "models", None) or []:
        for field_name, field in getattr(param_model, "model_fields", {}).items():
            if field_name == name:
                return True
            annotation = getattr(field, "annotation", None)
            if (
                isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
                and name in annotation.model_fields
            ):
                return True
    return False


@road(
    "retired_query", example="apps/core/tests/test_retired_query.py::StrictQuerySeam.process_view"
)
def retired_query_of(operation: Any) -> dict[str, RetiredQuery]:
    """The query parameters this operation's module retired, where it takes their successor.

    Read off the module that bound the operation (`operation.view_func`'s
    module, its `RETIRED_QUERY`), narrowed to the entries whose `instead` this
    operation actually takes: a parameter retired in favour of `?show=` is
    retired on the list that takes `?show=`, not on the module's detail route.
    Empty for a module that declares none.

    A product's strict-query seam calls this before refusing a query parameter
    the route does not take, and lets the route answer instead — so the
    retired parameter's sentence is the one declared here, on every tree.
    """
    view = getattr(operation, "view_func", None)
    module_name = getattr(view, "__module__", None)
    if not module_name:
        return {}
    declared = getattr(importlib.import_module(module_name), "RETIRED_QUERY", None)
    if not isinstance(declared, Mapping):
        return {}
    return {
        str(name): entry
        for name, entry in declared.items()
        if isinstance(entry, RetiredQuery) and offers_query(operation, entry.instead)
    }
