"""Search's writes: a tenant's documents out of every index; the engine's two announcements.

The ids to delete are read out of the engine, never Postgres (ADR search-2): the rows may be gone.
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

#: What may be logged and audited out of this module's arguments.
LOG_KEYS: frozenset[str] = frozenset({"name", "kind", "engine"})

#: Documents read back and deleted per round trip — the engine's own page ceiling.
PURGE_BATCH = 200

#: A purge never spins: past this the engine is broken, not the tenant large.
MAX_ROUNDS = 1_000


# door: called by the erasure path, where the act is authorized; a client could blind a tenant.
@service
def delete_tenant_documents(*, tenant: Tenant, actor: Actor) -> int:
    """Remove every document this tenant owns from every kind's index; returns how many.

    Idempotent: a second call finds nothing and writes nothing.
    """
    # authz: an interlock after an erasure authorized at its own door; nothing narrower to ask.
    engine = engine_module.engine()
    deleted = 0
    for label in registry.labels():
        deleted += _empty_one_kind(engine, label=label, tenant_id=tenant.pk)
    log.info("search.documents.tenant_deleted", tenant_id=str(tenant.pk), documents=deleted)
    return deleted


def _empty_one_kind(engine: SearchEngine, *, label: str, tenant_id: UUID) -> int:
    """One kind's index emptied of one tenant, confirmed round by round.

    `org_ids=None` is the one tenant-wide read here: its output is a deletion, returned to nobody.
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
# The payload carries engine names only; the failure's text stays in the log line.


# door: only the circuit that observed the transition may say the search degraded.
@service
def announce_degraded(*, tenant: Tenant, engine: str, fallback: str) -> Event:
    """Say that the primary engine stopped answering and the fallback took over (ADR core-22).

    Once per transition, by the winner of the circuit's claim — never per failing request.
    # authz: the product reporting a fact about itself; no narrower permission exists.
    """
    # payload: an engine-state event has no `Out` — two engine names, nothing per-row.
    event = emit(
        name=SEARCH_ENGINE_DEGRADED,
        tenant=tenant,
        payload={"v": V, "engine": engine, "serving": fallback},
        actor=system_actor(tenant=tenant),
    )
    log.warning("search.engine.degraded", engine=engine, serving=fallback)
    return event


# door: as its twin above; a caller who could announce a recovery could clear an alert.
@service
def announce_recovered(*, tenant: Tenant, engine: str) -> Event:
    """Say that the primary engine answered again and the product is back on it (ADR core-22).

    The verb is `recovered`: the alert census's `RECOVERY_VERBS` is closed.
    # authz: as above — the product reporting a fact about itself.
    """
    # payload: an engine-state event has no `Out` — one engine name, nothing per-row.
    event = emit(
        name=SEARCH_ENGINE_RECOVERED,
        tenant=tenant,
        payload={"v": V, "engine": engine},
        actor=system_actor(tenant=tenant),
    )
    log.info("search.engine.recovered", engine=engine)
    return event
