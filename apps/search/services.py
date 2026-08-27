"""The write half of the chokepoint: **taking documents OUT, and saying so.**

`selectors.search` is the read wall — one function builds the scope, and no
other path to an engine exists (house rule 33). This is its opposite number and
it exists for one reason the read wall cannot serve: **an index is a copy, and a
copy that outlives its original is a leak that no filter can close.**

## Why erasure needs a door into the engine at all

Every ordinary disappearance is already handled and handled better: a row that
is deleted or archived emits an event, the spine hands it to
`activities.index_event`, and the document goes — built from the row, so the tap
converges whatever order events arrive in. Nothing here is needed for that.

What the tap cannot do is act on rows that were never touched. When a **tenant**
is erased, the documents describing that tenant's rows are still in the shared
index, still carrying `tenant_id`, and still exactly as findable as they were —
by anybody the filter lets in. The rows may have gone in one statement, the
events may never have been emitted, and the hourly reconcile would eventually
rebuild each index from Postgres and drop them. "Eventually" is the wrong word
in a sentence about erasure.

So `delete_tenant_documents` is the interlock: **name the tenant, and its
documents leave every kind's index now, confirmed by the engine**, rather than
within the reconcile's hour.

## Why the ids are read out of the engine rather than out of Postgres

Because the rows may already be gone. A purge that walked Postgres to find out
what to delete from Meilisearch would delete exactly the documents whose rows
still exist — which is the complement of what erasure needs. The index is
therefore its own source of truth about what it holds: this reads the tenant's
documents back under a `tenant_id`-only filter, deletes what it was handed, and
asks again until the engine says there are none. It converges, it is idempotent,
and a second run over an already-empty tenant makes one read and no writes.

## The one honest wrinkle, stated

`@service` wraps this in a transaction, and the engine is not in it. A failure
part-way leaves some documents deleted and rolls the audit row back, so the
ledger says nothing happened while something did. That is the right way round of
the two: the alternative is an audit row claiming a purge that did not finish.
The caller's remedy is to run it again — which is safe, because this converges —
and the reconcile is the belt underneath either way.

## The other two writes here, and why they are writes at all

`announce_degraded` and `announce_recovered` write no document and touch no
index. What they write is an **event** — and an event is a write, which is why
they are here and not in `selectors.py` beside the circuit that calls them
(house rule 12: selectors never write).

They exist because ADR search-2 makes one sentence load-bearing: *a degradation
the system survives is a state it announces, never just tolerates.* The circuit
in `selectors.py` decides WHEN the state changed — it holds the cache keys and
wins or loses the transition claim — and these two say so. Splitting it that way
is deliberate: the claim has to be atomic and cheap and sits on the read path,
and the announcement has to be transactional and audited and sits on the write
path. One function doing both would have to choose which of the two it was.

**Called only by the winner of the transition claim.** Neither of these
re-checks anything: by the time either is reached, exactly one process has
already established that the state moved. That is what makes "transitions only,
never per request" a property of the mechanism rather than of a condition
somebody remembered to write twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.core.actor import Actor, system_actor
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.service import service
from apps.events.models import Event
from apps.events.services import emit
from apps.search import engine as engine_module
from apps.search import registry
from apps.search.events import SEARCH_ENGINE_DEGRADED, SEARCH_ENGINE_RECOVERED, V
from apps.search.types import ScopeFilter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.search.types import SearchEngine

log = get_logger(__name__)

#: What may be logged and audited out of this module's arguments. `tenant` and
#: `actor` are redacted to their labels by `@service` anyway; naming `kind` lets
#: an audit row say WHICH indexes were emptied, which is the one fact somebody
#: reading the trail six months later actually wants. `engine` joins it for the
#: two announcements below, for the same reason: "which engine" is the whole
#: content of a degradation, and an audit row that hid it would say only that
#: something happened.
LOG_KEYS: frozenset[str] = frozenset({"name", "kind", "engine"})

#: How many documents are read back and deleted per round trip. The engine's own
#: page ceiling is the natural size — larger asks Meilisearch for a window it
#: will clamp anyway, smaller pays more round trips for the same work.
PURGE_BATCH = 200

#: A stop, so a purge can never become a spin. Reached only if the engine keeps
#: handing back documents it has confirmed deleting, which is a broken engine
#: and not a large tenant: each round removes `PURGE_BATCH` of them, so this
#: allows two hundred thousand documents per kind before it gives up and says
#: so rather than looping in a worker for ever.
MAX_ROUNDS = 1_000


# door: not reachable by a client, on purpose. A caller who could empty a
# tenant's index could blind that tenant's own search without touching a row —
# findable by nobody, with nothing in Postgres to show for it, until the
# reconcile's next hour quietly put it back. This is called by the erasure path,
# which is where the act is authorized, and the hourly reconcile is the belt
# underneath it.
@service
def delete_tenant_documents(*, tenant: Tenant, actor: Actor) -> int:
    """Remove every document this tenant owns, from every kind's index. **Now.**

    Returns how many documents were deleted, across all kinds, so a caller and
    an audit reader can both see whether there was anything there.

    Idempotent: a second call finds nothing and writes nothing. That is what
    makes it safe as a retry and safe as a belt — the rebuild-after-erasure
    criterion is that re-running converges rather than resurrecting, and the
    reason it converges is that the documents are gone from the source too.

    The `actor` is carried so the audit row can say who did this, never so that
    this function can decide anything: it holds no permission of its own.
    """
    # authz: an interlock rather than a capability, and it asks nothing because
    # there is nothing narrower to ask. Whoever calls this has just erased the
    # tenant, and that act was authorized at its own door; "may you delete the
    # search documents of a tenant you have already erased" has one answer.
    engine = engine_module.engine()
    deleted = 0
    for label in registry.labels():
        deleted += _empty_one_kind(engine, label=label, tenant_id=tenant.pk)
    log.info("search.documents.tenant_deleted", tenant_id=str(tenant.pk), documents=deleted)
    return deleted


def _empty_one_kind(engine: SearchEngine, *, label: str, tenant_id: UUID) -> int:
    """One kind's index, emptied of one tenant, confirmed round by round.

    The filter is `tenant_id` alone — `org_ids=None`, which says "this read is
    not narrowed by an organization" and is the ONE place in this app that is
    deliberately tenant-wide. It is legal here for the same reason
    `activities._rows` is unscoped: nothing is being returned to anybody. The
    output of this function is a deletion, and the widest thing it can reach is
    the tenant whose documents it was asked to remove.
    """
    scope = ScopeFilter(tenant_id=tenant_id, org_ids=None)
    removed = 0
    for _round in range(MAX_ROUNDS):
        window = engine.query(kinds=[label], q="", scope=scope, offset=0, limit=PURGE_BATCH)
        ids = [hit.id for hit in window.hits]
        if not ids:
            return removed
        engine.delete(label=label, ids=ids)
        removed += len(ids)
        log.info("search.documents.deleted", kind=label, documents=len(ids))
    raise RuntimeError(
        f"emptying {label!r} of tenant {tenant_id} did not converge in {MAX_ROUNDS} rounds — "
        "the engine is still returning documents it has confirmed deleting. Something is "
        "wrong with the index, not with the tenant."
    )


# --- The circuit's two announcements -----------------------------------------
#
# **What the payload carries, and what it must not.** Two engine names, and
# nothing about the failure. An index uid or a client's error string would put
# this deployment's infrastructure vocabulary on a customer's webhook endpoint;
# the reason belongs in the structured log line the circuit writes beside the
# call, where operators are, and the sink joins the two by `correlation_id`.
#
# **Which tenant an announcement names** is `events.py`'s honest wrinkle: the
# one whose request observed the transition, because a dead index is
# deployment-wide and `emit` is per-tenant. The consumer this exists for is the
# operator, through ClickStack's saved search over the event stream, where one
# event is one alert.
#


# door: deliberately unreachable from outside. There is no route, tool or
# command that should let a caller ASSERT that this deployment's search
# degraded — an announcement anybody can make is an alert nobody can trust, and
# this one pages a human. The only honest caller is the circuit that observed
# the state change; `tests/test_chaos_drill.py` reaches it through a real outage.
@service
def announce_degraded(*, tenant: Tenant, engine: str, fallback: str) -> Event:
    """Say that the primary engine stopped answering and the fallback took over.

    **It returns the `Event` it wrote** (ADR core-22). A ruling asked whether
    each self-report writes a row of ours:
    this one does, and this module's own docstring already said so — "what they
    write is an **event** — and an event is a write, which is why they are here
    and not in `selectors.py`". So it leaves absence (vii): the audit row names
    `events.Event` and the event's id, and a reader can join the announcement to
    the payload that went out with it instead of taking the trail's word for it.

    Emitted **once per transition**, by the one process that won the claim in
    `selectors`' circuit — never per failing request, and never by a re-probe
    that finds the index still down. A cooldown expiring every thirty seconds
    would otherwise put one event on the spine per re-probe, and an alert that
    fires all night is an alert somebody turns off.

    # authz: nobody did this. It is the product reporting a fact about itself,
    # observed on a read path that had already authorised its own read; there is
    # no narrower permission than "may the platform say that it degraded".
    """
    event = emit(
        name=SEARCH_ENGINE_DEGRADED,
        tenant=tenant,
        payload={"v": V, "engine": engine, "serving": fallback},
        actor=system_actor(tenant=tenant),
    )
    log.warning("search.engine.degraded", engine=engine, serving=fallback)
    return event


# door: unreachable from outside for the same reason its twin above is, and the
# reason is sharper on this half: a caller who could announce a recovery could
# CLEAR somebody else's alert while the index was still down.
@service
def announce_recovered(*, tenant: Tenant, engine: str) -> Event:
    """Say that the primary engine answered again and the product is back on it.

    **It returns the `Event` it wrote** (ADR core-22). A ruling asked whether
    each self-report writes a row of ours:
    this one does, and this module's own docstring already said so — "what they
    write is an **event** — and an event is a write, which is why they are here
    and not in `selectors.py`". So it leaves absence (vii): the audit row names
    `events.Event` and the event's id, and a reader can join the announcement to
    the payload that went out with it instead of taking the trail's word for it.

    The other half of the pair, and it may not be spelled anything else: the
    alert census's `RECOVERY_VERBS` is a closed one-element tuple, so a pair
    whose recovery half was `restored` would declare a degradation the alert
    surface cannot lower.

    # authz: as above — the product reporting a fact about itself.
    """
    event = emit(
        name=SEARCH_ENGINE_RECOVERED,
        tenant=tenant,
        payload={"v": V, "engine": engine},
        actor=system_actor(tenant=tenant),
    )
    log.info("search.engine.recovered", engine=engine)
    return event
