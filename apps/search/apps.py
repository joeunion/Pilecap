from typing import Any

from django.apps import AppConfig


class SearchConfig(AppConfig):
    """Find the thing. One chokepoint, one fence, and no tables of its own.

    Search is where scoping quietly dies (ADR search-2): an external index that
    does not carry the walls is a probing oracle — you type a word, and it tells
    you whether somebody else's row contains it. So the centre of gravity of
    this app is not the engine. It is the **filter injection**: one function
    resolves `tenant_id` and the visible organization ids in Postgres, per
    request, and hands the engine ids it did not choose. The engine never sees
    the actor, the hat or a materialized path, so an engine cannot get scoping
    wrong — only receive it.

    **This app declares no models and owns no tables, and that is a design
    decision rather than an omission** (house rule 31 has nothing to declare
    here). Two populations could have been rows and deliberately are not:

    * the **documents** live in Meilisearch, which is a derived view of
      Postgres and never a source of record. They are declared a purged
      population in `apps/search/lifecycle.py`, beside the callable that
      empties them (`services.delete_tenant_documents`) — as a NAMED
      population rather than through `LifecycleRegistry.declare`, which keys
      everything it holds on `model._meta.label` and has nothing to key this
      on. That module says what the missing seam is and why this app does not
      invent a table to fit through the existing one;
    * the **tsvector column** the degradation engine reads belongs to the
      *adopting* app's model, with that app's own migration. A central
      projection table would be a shadow authorization copy, which ADR
      search-1 rejected and search-2 did not reinstate.

    So `apps/search/migrations/` does not exist, on purpose. A rung that finds
    itself running `makemigrations search` has been asked for the wrong thing.

    `depends_on` names two apps and both are load-bearing:

    * `core` — the tenant, the organization tree whose subtree scan produces
      the visible-org-id list, and the `Actor` every door hands in;
    * `accounts` — the authenticators the REST router restates and the
      principal the MCP door resolves.

    * `events` — **joined with the tap.** The spine fans every committed
      event out to a third leg beside `push_realtime`, and this app fills the
      bridge name that leg looks up. The import is one constant — the bridge
      NAME, from `apps/events/activities.py`, where ADR search-2 puts it because
      no ingredient may touch `apps/core` — and importing it rather than
      re-spelling the string is the whole reason bridge names are constants: a
      typo would be a silent no-op on a laptop and a search index that quietly
      stopped moving in production.

    **`ready()` does the two things a registry needs doing once per process.**

    First it **refuses a bad declaration**, before anything can index under one.
    `ImproperlyConfigured` out of `ready()` stops the process — the strongest
    tier, and the one `apps.usage.meters` and `core.lifecycle` already use for
    their own vocabularies. It is here rather than in a system check because a
    check is quieter: a kind declared over a field that does not exist would
    index `None` for ever, in a running worker, and the only tell would be
    somebody saying "search never finds that".

    Then it **registers the indexer** on `core.bridge`. `ready()` is the one
    hook that runs in every process — the web server, the Temporal worker,
    `manage.py`, pytest — which is exactly the property a runtime registry
    needs; a bridge filled from a module import would be filled only in the
    processes that happened to import that module. The order matters: a
    deployment whose declarations are wrong must not have a working tap.
    """

    name = "apps.search"
    verbose_name = "Search"
    depends_on: tuple[str, ...] = ("core", "accounts", "events")

    def ready(self, **kwargs: Any) -> None:
        from apps.core import bridge
        from apps.events.activities import SEARCH_INDEX_EVENT, IndexesSearchDocuments
        from apps.search import registry
        from apps.search.activities import index_event

        registry.validate()
        # The shape is declared into `SHAPES` here rather than written into
        # `apps/core/bridge.py`, and the two lines are deliberately adjacent.
        # `core`'s own test holds every registered name to a declared shape AND
        # every declared shape to a live registrant, so a shape hand-written in
        # `core` would fail the second half in every checkout that ships without
        # this app. Declared by the registrant, they arrive and leave together —
        # and the pin `apps/core/tests/test_bridge_shape.py` gives every other
        # bridge name comes free.
        bridge.SHAPES.setdefault(SEARCH_INDEX_EVENT, IndexesSearchDocuments)
        bridge.register(SEARCH_INDEX_EVENT, index_event)
