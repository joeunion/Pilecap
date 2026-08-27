"""How the search documents die. **A population with no table, declared anyway.**

`apps/search` owns no models and never will (`apps.py` says why at length), so
house rule 31 — every concrete model declares how its data dies — has nothing to
say about this app. That is exactly the shape the rule exists to catch one level
out: **the documents are a population of personal data, in a shared index, that
no schema mentions.** Thirty-two of this tree's tables said nothing about how
their rows end and rule 31 closed that; a population that is not a table at all
would have said nothing and not even been counted.

So the declaration lives here, in the module `apps.core.lifecycle` discovers, in
the same `Lifecycle` value type every model uses — which means it is refused at
IMPORT if it is malformed, by the same primitive, with the same sentences. A
`purged` declaration with nothing purging it does not load.

## What the declaration says

**`PURGED`, by `apps.search.services.delete_tenant_documents`.** Not `BOUNDED`,
which was the tempting answer: a document does die with its row in the ordinary
case (the spine tap removes it, `activities.index_event`), and if that were the
whole story `BOUNDED` would be honest. It is not the whole story, because the
one case that matters most is the one the tap cannot serve — a tenant erased in
one act, whose rows are gone before any event describes them, leaves every one
of its documents in the shared index, still carrying `tenant_id`, still exactly
as findable. `BOUNDED` would have declared that away.

**The belt is the hourly reconcile**, and it is worth naming because it is the
reason "eventually" is not "never": `activities.RECONCILE` rebuilds each kind's
index from Postgres every hour, so a document whose row has gone stops existing
at the next rebuild whether anybody called the purge or not. The declaration
names the purge rather than the reconcile because the purge is what makes the
disposal *prompt*, and prompt is the whole of what erasure means.

## How it reaches the census

`apps.core.lifecycle.LifecycleRegistry.declare` takes a `type[models.Model]` and
keys everything it holds on `model._meta.label`. **There is no Django model here
to hand it**, and this module never grew a fake one to squeeze through:
declaring an unmanaged model, or a stub carrying a hand-made `_meta`, would put
a table in `introspect` that no database has.

So the registry grew the entry point instead — `declare_population(name,
lifecycle, source=)`, keyed on a NAME, in its own key space so a population can
never pass as a table — and this module now registers through the same
`register(registry)` hook `apps/accounts/lifecycle.py` uses for allauth's five.
The declaration below is unchanged; what changed is that something outside this
app reads it. `apps/files` names `delete_tenant_objects` for the same shape and
adopts the seam in its own lane, which is what "one seam serving two apps" was
always going to mean.

Until that landed the declaration was read from `POPULATIONS` alone — same file,
same convention, same primitive, one reader short of the census. `POPULATIONS`
survives as the app's own statement of what it declares; `register` is what
hands it over.
"""

from __future__ import annotations

from apps.core.lifecycle import Lifecycle, LifecycleKind, LifecycleRegistry

#: Named once so the declaration, the census and any future registration all say
#: where this came from — the same discipline `apps/accounts/lifecycle.py`'s
#: `SOURCE` follows.
SOURCE = "apps/search/lifecycle.py"

#: What the population is called, in the words a reader greps. It is not a
#: `app_label.ModelName` because it is not a model; it is the thing this app
#: writes into somebody else's server.
DOCUMENTS = "search.Document"

#: The declaration itself. `Lifecycle.__post_init__` refuses it at import if the
#: dotted path is missing or is not dotted, which is the strongest tier this
#: tree has and the one every model's declaration already meets.
DOCUMENT_LIFECYCLE = Lifecycle(
    kind=LifecycleKind.PURGED,
    purged_by="apps.search.services.delete_tenant_documents",
    reason=(
        "the Meilisearch documents this app materializes from other apps' rows. A "
        "derived view and never a source of record — but a COPY, in a shared index, "
        "of text a person typed, so it outlives the row unless something takes it "
        "out. The tap removes a document when its row goes; the purge named above is "
        "what makes a tenant's whole footprint leave at the moment of erasure rather "
        "than at the hourly reconcile that would eventually rebuild it away."
    ),
    declared_for=DOCUMENTS,
)

#: The off-ORM populations this app is responsible for, by name. One today.
#: A dict rather than a single value because the shape is the same one
#: `LifecycleRegistry.populations()` returns — which is what let the day core
#: grew the name-taking entry point be a loop over this rather than a rewrite.
POPULATIONS: dict[str, Lifecycle] = {DOCUMENTS: DOCUMENT_LIFECYCLE}


def populations() -> dict[str, Lifecycle]:
    """Every population this app disposes of that no table holds. **The census.**

    A function rather than the dict itself for the reason
    `core.lifecycle.third_party_lifecycles` is one: a reader that hands back the
    module's own mutable object is a census a caller can edit.

    Still here, and it is not a second opinion: this is what the app
    DECLARES, and `core.lifecycle.declared_populations()` is what the platform
    has been HANDED — by `register` below, out of this very dict, so the two
    cannot drift apart without the loop changing.
    """
    return dict(POPULATIONS)


def register(registry: LifecycleRegistry) -> None:
    """Hand this app's off-ORM populations to the platform.

    Discovered by `apps.core.lifecycle._third_party_registry`, exactly as
    `apps/accounts/lifecycle.py`'s `register` is — nothing central is edited and
    nothing here is registered anywhere; the module has the conventional name
    and the platform looks in it.

    A loop over `POPULATIONS` rather than one hand-written call per population,
    so an app that starts writing into a second keyspace declares it in the dict
    above and this function does not change.
    """
    for name, lifecycle in POPULATIONS.items():
        registry.declare_population(name, lifecycle, source=SOURCE)
