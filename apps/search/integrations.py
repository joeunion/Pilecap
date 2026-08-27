"""What this app tells the integrations census. **One row: the search index.**

`apps/core/integrations.py` owns the mechanism — the value type, the registry,
the discovered `register(registry)` hook, the four surfaces (setup epilogue,
`manage.py integrations`, the deploy wall, the standing prober) — and each app
owns the FACT of whether its own integration is real. An earlier attempt found that
`apps/core` *cannot* declare this one: house rule 33 puts `MEILI_URL` and
`MEILI_MASTER_KEY` in one module under `apps/` and a census row has to print the
variable name as its remedy, so the row is this app's to make. That is
the platform-concern boundary working, not a gap.

**Where the fact is read from, and why not from here.** This module names
neither variable and imports neither the engine nor the client: it asks
`selectors.get_engine_configuration()`, which is one of the four modules rule 33
lets reach `engine.py`. Adding this file to the fence's allow-list would have
been the shorter diff and the wrong one — a fence widened to save an
indirection is a fence that gets widened again.

**Why the row is `declared` and never `live`.** Every other live-probed row in
the census answers a question whose bad answer means something is broken.
"Meilisearch did not respond" does not mean that here: search degrades to
Postgres by design (ADR search-2), announces the transition on the spine, and
comes back on its own. `apps/core/health.py` refuses a `meili` readiness member
for exactly this reason — a member there would convert a designed degradation
into a self-inflicted outage — and a *live* row here would do the same thing to
the deploy wall, which refuses a release on anything not `CONFIGURED`. So this
row reports how the deployment is WIRED. Whether the engine is answering right
now is the circuit's question, and it is answered per request, for free, on the
path that already cares.

**What it cannot see, declared** (the census's own discipline):

* **Whether the address is the right one.** A `MEILI_URL` pointing at a
  reachable engine belonging to another deployment reads as configured here.
  The index prefix is derived per checkout, so the damage is bounded to a shared
  server rather than a shared index — but this row would not say so.
* **Whether the credential is the right one.** `keyed` is "a key is set", not "a
  key that works": proving the second is a call, and this row does not make one.
* **Whether anything is declared searchable.** A deployment can be perfectly
  configured and declare no `Searchable` at all, in which case search finds
  nothing and is working correctly. `GET /search/kinds/` is the door that
  answers that, and it answers it per request rather than per deploy.
"""

from __future__ import annotations

from apps.core.integrations import (
    PROBE_DECLARED,
    Integration,
    IntegrationRegistry,
    IntegrationStatus,
)
from apps.search import selectors

#: What the census stamps every row below with, so a reader can see which module
#: made the claim. A constant rather than a literal for the reason every other
#: `declared_by` in this census is one: the string is printed at four surfaces.
SOURCE = "apps/search/integrations.py"

#: The census key for the index. Stable, and chosen once: a runbook, an alert
#: and the deploy wall all name it, and it does not move when the title does.
SEARCH_INDEX = "search-index"


def register(registry: IntegrationRegistry) -> None:
    """Declare the search index, as this deployment currently stands.

    Discovered by `core.integrations.declaring_modules()` — the walk reads a
    filename off `get_app_configs()` and never a list — so this app joined the
    census the moment the file existed, with no edit anywhere else. That is the
    owner's criterion for the whole instrument, and this module is one of its
    proofs.
    """
    configuration = selectors.get_engine_configuration()
    if configuration.keyed:
        registry.declare(
            Integration(
                key=SEARCH_INDEX,
                title="Search index (Meilisearch)",
                status=IntegrationStatus.CONFIGURED,
                detail=(
                    f"dialled at {configuration.address} with a master key set. "
                    "An unreachable engine is a degraded state, not an outage: "
                    "search falls back to Postgres full-text and says so on the "
                    "spine."
                ),
                probe=PROBE_DECLARED,
            ),
            source=SOURCE,
        )
        return
    registry.declare(
        Integration(
            key=SEARCH_INDEX,
            title="Search index (Meilisearch)",
            status=IntegrationStatus.NOT_CONFIGURED,
            detail=(
                f"dialled at {configuration.address} with no master key, so the "
                "engine is unkeyed: anything that can reach that address can read "
                "and rewrite every tenant's documents."
            ),
            remedy=(
                "set MEILI_MASTER_KEY in .env to the value the engine was started "
                "with (compose.yaml passes it to the container; .env.example ships "
                "a published development value, and production injects a real one). "
                "With a key set, the engine requires it on every request, so dev "
                "and production are the same shape."
            ),
            probe=PROBE_DECLARED,
        ),
        source=SOURCE,
    )
