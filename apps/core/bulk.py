"""Bulk: the same verb over a selection, honest about every item.

`POST /<nouns>/bulk/` (`url_name` `<noun>-bulk`, twin `bulk_<noun>s`) takes a
verb and up to `MAX_ITEMS` ids and answers **200 once the envelope holds** —
`{verb, results: [{id, outcome, item?, refusal?}], done, unchanged, refused}` —
one result per id, in the order the ids were sent. The envelope's own refusals
(`invalid` for too many ids or a repeated one, `forbidden` when the actor holds
the verb nowhere) are the only non-200s.

**One transaction, on every door; a refusal is per item, a crash is the whole
batch.** `run_bulk` is NOT a service; it opens ONE `transaction.atomic()` around
its loop, and each item runs the noun's OWN per-item service, whose `@service`
atomic is a SAVEPOINT inside it. So:

* a REFUSAL at item k (a `DomainError` — an outcome, not a failure) rolls back
  item k's savepoint only, is reported with the very body a single call would
  get (`wire_refusal`) and leaves its own `outcome=error` audit row; the items
  before and after it commit with their audit rows and events (DESIGN's
  per-item honesty). All-or-nothing over REFUSALS was rejected: one blocked row
  would stall the other 199, and a face would have to lie about which moved;
* an UNHANDLED exception at item k is a failure, and it rolls back the whole
  batch and propagates (a 500): nothing happened, which is a fact the caller
  can act on — the same `Idempotency-Key` retries it, because the REST door's
  idempotency middleware drops the claim of any 5xx rather than replaying it
  (`apps/core/idempotency.py`, `_remember`);
* row locks are held to the end of the batch, bounded by `MAX_ITEMS`.

Why here and not at the door: `ATOMIC_REQUESTS` already put every REST item
inside one request transaction, while the MCP door runs under none — so a crash
at item k committed items 1..k-1 on one door and nothing on the other. One
`atomic()` in the seam makes it one contract whichever door the batch came in by.

**Retry converges** (principle 16). An item whose row is already where the verb
would put it answers `unchanged` — the road's `settled` predicate, read before
the call — so a half-done batch sent again does the half that is left, and an
`Idempotency-Key` on the door replays the whole first answer (E7).

DOES NOT COVER — declared: a selection across pages (the ids are what was sent);
a `settled` predicate that is wrong answers `done` for a no-op (the per-item
service is still idempotent, so nothing double-writes); a batch larger than a
request's budget (the trigger to make it an import-shaped run is a measured p95
over the budget at `MAX_ITEMS`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from apps.core.exceptions import DomainError, Invalid, wire_refusal

#: The most ids one batch may carry. E6's page ceiling, and DESIGN's "≥ 200".
MAX_ITEMS = 200

Outcome = Literal["done", "unchanged", "refused"]


@dataclass(frozen=True, slots=True)
class BulkResult:
    """One id's answer: what happened to it, and the row or the refusal."""

    id: Any
    outcome: Outcome
    item: Any = None
    refusal: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BulkReport:
    """The whole batch's answer, results in the order the ids were sent."""

    verb: str
    results: list[BulkResult] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(1 for r in self.results if r.outcome == "done")

    @property
    def unchanged(self) -> int:
        return sum(1 for r in self.results if r.outcome == "unchanged")

    @property
    def refused(self) -> int:
        return sum(1 for r in self.results if r.outcome == "refused")


def check_ids(ids: Sequence[Any]) -> list[Any]:
    """The envelope's own rule: 1 to `MAX_ITEMS` ids, none repeated. `invalid` naming `ids`."""
    listed = list(ids)
    if not listed:
        raise Invalid({"ids": ["Send at least one id."]})
    if len(listed) > MAX_ITEMS:
        raise Invalid(
            {
                "ids": [
                    f"A batch may carry at most {MAX_ITEMS} ids; {len(listed)} were sent. "
                    "Send the rest as a second batch."
                ]
            }
        )
    seen: set[str] = set()
    repeated = []
    for value in listed:
        key = str(value)
        if key in seen:
            repeated.append(key)
        seen.add(key)
    if repeated:
        raise Invalid({"ids": [f"Each id once; repeated: {', '.join(sorted(set(repeated)))}."]})
    return listed


def run_bulk(
    *,
    tenant: Any,
    actor: Any,
    verb: str,
    ids: Sequence[Any],
    resolve: Callable[[Any], Any],
    act: Callable[..., Any],
    is_settled: Callable[..., bool] | None = None,
    args: Mapping[str, Any] | None = None,
) -> BulkReport:
    """Run `act` over each id, in order, and say what happened to each.

        report = run_bulk(
            tenant=tenant, actor=actor, verb="archive", ids=payload.ids,
            resolve=lambda pk: resolve_subject(actor, "widget", pk),
            act=lambda row, **kw: archive_widget(tenant=tenant, actor=actor, widget=row),
            is_settled=ROADS["archive"].settled["archive"],
        )

    `resolve(id)` answers the row this actor could reach, or raises (a row it
    could not reach is `not_found`, exactly as a single call's). `is_settled(row,
    **args)` answers whether the verb has nothing to do (`unchanged`). `act(row,
    **args)` calls the noun's own per-item `@service` and answers what it
    returned (the item). Any `DomainError` from either is that item's refusal,
    in `wire_refusal`'s body; anything else is a bug and propagates.

    **One transaction around the loop** (the module's contract): `act` is the
    noun's own `@service`, so each item is a savepoint inside it — a refusal
    rolls back that item alone, and an unhandled exception rolls back the batch
    and propagates. Call it from the door, never from inside a service of your
    own, so the batch's transaction is the outermost one a refusal can reach.
    """
    from django.db import transaction

    listed = check_ids(ids)
    extra = dict(args or {})
    results: list[BulkResult] = []
    with transaction.atomic():
        for pk in listed:
            try:
                row = resolve(pk)
                if is_settled is not None and is_settled(row, **extra):
                    results.append(BulkResult(id=pk, outcome="unchanged", item=row))
                    continue
                item = act(row, **extra)
            except DomainError as exc:
                results.append(BulkResult(id=pk, outcome="refused", refusal=wire_refusal(exc)))
                continue
            results.append(BulkResult(id=pk, outcome="done", item=item))
    return BulkReport(verb=verb, results=results)
