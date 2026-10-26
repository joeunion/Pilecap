"""The one read chokepoint. **Query in, scoped page out — and no other path.**

`get_search_page()` is a *selector* and not a service, and that placement is deliberate:
a search is a read, house rule 12 puts reads in selectors, and the
ruling's intent ("a single search service always injects the filters") is
preserved exactly where it matters — **one function builds the scope, and no
other path to an engine exists.** House rule 33 is the closed half of that
sentence: `engine.py` is fenced, its allow-list names this module, and a second
caller would be a second, unfiltered query path.

## What the wall actually is

Not the index topology. ADR search-2 rejected index-per-tenant with reasons, and
isolation would not have ridden the topology in either design — it rides the
**injected filter**, resolved here:

1. the acting hat's **subtree of organization ids**, from one indexed
   prefix scan in Postgres, per request (`resolve_visible_org_ids`);
2. shaped **per kind** by whether that kind's model is org-scoped, so an
   org-scoped kind gets `tenant_id AND org_id IN [...]` and a tenant-scoped
   one gets `tenant_id` — never one shape for both, which is the class
   of defect pointed at search;
3. handed to the engine as `ScopeFilter`, which carries **resolved ids and
   nothing else**. The engine never sees the actor, the hat or a path, so an
   engine cannot get scoping wrong. It can only receive it.

`q` travels as the engine's query parameter and is never concatenated into a
filter expression (`engine.scope_expression` builds the filter out of `UUID`
objects and literally cannot see it), which is what the hostile-corpus probe
verifies from the outside.

## Fails closed, one level out from `for_tenant(None)`

`tenant=None` returns the empty page. An **unresolved hat** returns the empty
page too — the whole page, not just its org-scoped half. Answering a
tenant-scoped kind to somebody the product could not decide the acting
organization for would be a partial answer nobody asked for, and "not there" and
"not yours" are one answer here for the same reason they are one answer
everywhere else: the page is byte-identical to a page that simply matched
nothing.

## What the contract promises about freshness

**Eventually consistent, never read-your-writes.** A just-committed row appears
after its event dispatches and the engine's task settles — seconds in the
healthy case, bounded below by outbox dispatch latency. A product that needs
read-your-writes for a picker uses that resource's list endpoint, which is
Postgres and instantly true. Every convergence criterion in this app is phrased
drain-then-assert, never sleep-and-hope.

## Counts are exact, and that is an anti-oracle property

`include_count=true` returns the exact number of matches **under the injected
filter** — the engine answers it exhaustively for a filtered query. Nothing
anywhere counts what sits outside your scope, because no unfiltered query exists
to count with.

**And an empty page counts too.** Every short-circuit below used to
answer `count: null` even when the caller had asked, which contradicted the
endpoint's own published contract — "when you do ask, it is exact" — and `null`
does not mean zero: it means *not counted*. Zero is the exact number of matches
under a filter that matches nothing, so zero is what these say. The
short-circuit is about not making a round trip whose answer is already known;
it was never about declining to answer.

## The circuit: **a degraded state, never an outage**

`MeiliEngine` is the primary and `PostgresEngine` — below, in this file — is the
designed degradation. The shape ADR search-2 rules, and nothing more:

    try  →  fail over  →  cool down  →  re-probe

A timeout or a connection error inside the declared budget answers **that same
request** from Postgres and sets a short-TTL cooldown key in the cache; requests
inside the TTL skip the dead call entirely; the first request after the TTL
expires probes again. **No background health-checker, no third state, no retry
loop** — a retry brain here would fight Temporal's, and a health-checker is a
component that can itself be wrong.

**And the transitions announce themselves**: closed→open emits
`search.engine.degraded`, open→closed emits `search.engine.recovered`, each
exactly once, through `services.py` — because an event is a write and this file
never writes (house rule 12). The claim that decides who announces is one atomic
cache operation, so "transitions only" is a property of the mechanism and not of
a condition somebody remembered to write in two places.

**Why the fallback lives HERE and not in `engine.py`.** `engine.py` is the
module house rule 33 fences, and what it fences is Meilisearch: it writes to no
model, reads no model and does not know what a tenant is. The degradation engine
is the opposite of all three — it *is* the ORM — and putting it behind the fence
would make the one module that must not read customer rows the module that
reads them. It is a read, over querysets, in the app's read module, beside the
chokepoint whose scope it receives.

**What degrades, stated** (ADR search-2, and it is what the tests assert rather
than something they work around): latency — one filtered engine query becomes N
per-kind Postgres queries plus a count each, rank-merged; typo tolerance —
Meilisearch's full tolerance is gone, and **a misspelled word still finds
nothing**: an earlier rung landed `pg_trgm` and a trigram index on the adopting model's
text, so the half of that tolerance a relational engine can buy back is now
*available*, but `_ranked` below still matches on the tsvector alone and
nothing here reads the trigram index yet. An index with no reader is stated
rather than implied — the reader is a named follow-on, not a claim this
paragraph gets to make; relevance — field-weighted BM25-class ranking becomes
`ts_rank`; and prefix-as-you-type, which is gone. **What does not degrade: the
walls.** Both engines receive the same `ScopeFilter` and neither resolves one.

One thing gets BETTER, and it is the consistency note ADR search-2 asked for: a
row committed a microsecond ago is already findable through the fallback,
because there is nothing to sync. The generated column cannot be stale, which is
exactly the right property for the thing you are standing on when the synced
engine is down.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import reduce
from operator import add
from typing import Any
from uuid import UUID

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import F, QuerySet

from apps.core.api.pagination import MAX_LIMIT, decode_cursor, encode_cursor
from apps.core.authz import allows, kind_of, refusal_sentence
from apps.core.exceptions import Forbidden, SearchUnavailable
from apps.core.log import get_logger
from apps.core.models import ORG_FIELD, Organization, Tenant, subtree_q
from apps.search import engine as engine_module
from apps.search import registry, services
from apps.search.activities import display_for
from apps.search.registry import TENANT_ATTRIBUTE
from apps.search.schemas import SearchHitOut, SearchPage
from apps.search.types import (
    EngineConfiguration,
    EngineHit,
    EngineHits,
    EngineUnavailable,
    IndexState,
    ScopeFilter,
    Searchable,
    SearchEngine,
)

log = get_logger(__name__)

#: What the cursor's ordering token says. A search page is not ordered by a
#: column — the engine ranked it — so the one coordinate a cursor can name is
#: how far into the ranked result set this page starts. Naming it in the token
#: means a cursor minted for a search can never be replayed against a list door,
#: and vice versa: `decode_cursor` refuses a token minted under a different
#: ordering with its own sentence.
CURSOR_ORDERING: tuple[str, ...] = ("offset",)

#: The default page size when a caller names none. The same setting every list
#: door uses, read through the same seam, so search does not become the one
#: endpoint with its own idea of a page.
DEFAULT_LIMIT = 20

#: The Postgres text-search configuration both halves of the fallback use — the
#: `to_tsvector` config for the corpus and the `to_tsquery` config for the query.
#: **They have to be the same one**: a vector built under `english` and a query
#: parsed under `simple` disagree about stemming and stop words, and the failure
#: is a search that quietly finds less rather than an error anybody sees.
#:
#: It is a constant here because a `GeneratedField` holding a tsvector must name
#: an immutable configuration in its own expression, so the adoption migration
#: has to hard-code one — and this is the one it reads, so the column and the
#: computed path cannot come to disagree. A product that indexes another
#: language changes it here and rebuilds; there is deliberately no per-tenant
#: setting (ADR search-2's excluded list, "per-tenant index tuning").
TEXT_SEARCH_CONFIG = "english"

#: The column an adopting model declares. When a model has it, the
#: fallback reads it and Postgres can use the GIN index over it; when it does
#: not, the same vector is computed from the same declared fields on the fly —
#: the same tsquery and the same ranking function with a sequential scan under
#: it instead of an index. **Correct either way, fast only the first way**, and
#: that asymmetry is stated rather than hidden. `apps/example/models.py`'s
#: `Widget.search_vector` is the worked adopting column and the first member of
#: the declaring population, so both branches now have a model in the tree —
#: `tests/test_degradation.py` drives the computed one and
#: `apps/example/tests/test_search_adoption.py` drives the real one.
VECTOR_FIELD = "search_vector"

#: The cache key that says "do not call the primary". Short-lived on purpose:
#: it is the whole of the cooldown, and its expiry IS the re-probe.
COOLDOWN_KEY = "search:circuit:cooldown"

#: The cache key that says "we have announced a degradation and not yet
#: announced a recovery". It has **no expiry**, deliberately: the cooldown key
#: expiring every few seconds must not be mistaken for the outage ending, and a
#: flag that timed out on its own would announce the same degradation again on
#: the next failure — a pair that can be raised twice and lowered once. Its
#: whole life is one atomic `add` (the claim to announce degraded) and one
#: atomic `delete` (the claim to announce recovered).
DEGRADED_KEY = "search:circuit:degraded"

#: How long the circuit stays open before one request probes the primary again.
#: Short, because the cost of being wrong in one direction is a re-probe that
#: fails and in the other is a product searching plainly for longer than it had
#: to. `engine.QUERY_TIMEOUT_MS` is the per-call budget; this is how often that
#: budget is spent while the index is down.
COOLDOWN_SECONDS = 30


def get_engine_configuration() -> EngineConfiguration:
    """Where the index is dialled, and whether a credential is set. **No call.**

    The integrations census asks this (`apps/search/integrations.py`), and it
    asks it *here* rather than of `engine.py` because of house rule 33: the
    address and the master key are named in exactly one module under `apps/`,
    and this file is one of the four the fence lets reach it. A census module
    that read them itself would be a second door to the credential — which is
    the thing the rule is for — and the alternative, adding `integrations.py` to
    the allow-list, would widen a fence to save an indirection.

    It lives in `selectors.py` because it is a **read that returns no queryset
    and writes nothing** (house rule 12), and it is `get_`-prefixed for house
    rule 16's grammar. It reads the module's own accessor functions rather than
    the environment, so there is still exactly one place either value is read
    from.

    **It opens no socket**, deliberately — see `types.EngineConfiguration` for
    the argument. Reachability belongs to the circuit, not to an instrument that
    could hand a deploy wall a veto over a designed degradation.
    """
    return EngineConfiguration(
        address=engine_module.meili_url(),
        keyed=bool(engine_module.meili_master_key()),
    )


def list_visible_org_ids(*, tenant: Tenant | None, actor: Any) -> tuple[UUID, ...] | None:
    """The acting hat's subtree as ids, in one query; `None` when the hat is unresolved.

    Ids, never paths: a re-parented organization rewrites zero documents.
    """
    if tenant is None:
        return None
    org = actor if isinstance(actor, Organization) else getattr(actor, "org", None)
    if not isinstance(org, Organization):
        return None
    return tuple(
        Organization.objects.for_tenant(tenant).filter(subtree_q(org)).values_list("id", flat=True)
    )


def list_readable_kinds(actor: Any) -> frozenset[str]:
    """Which declared kinds this actor may READ, at their hat. **Phase R's half.**

    `list_`-prefixed because rule 16 asks every public selector to be guessable
    from its name, and outside rule 54 (d)'s population because it returns
    labels rather than a model — there is no row here to ask a read key about;
    this IS the asking.

    A search is a read of every kind it touches, so it asks the same question
    every list door asks — `<kind>.read`, through `core.authz.allows`, at the
    acting hat — once per declared kind. WHICH ROWS come back is still the
    injected `ScopeFilter`'s answer and is untouched (BVB-4: the row filter is a
    query, not a check); this decides WHETHER this kind, here.

    **It costs three statements, once, however many kinds are declared.** The
    actor carries the permission memo, so the first `allows` reads the three
    tables and every kind after it reads none. That is what makes asking
    per-kind affordable at the chokepoint instead of per-hit at the engine.

    **A model with no authorization kind is not searchable for anybody.**
    `authz_kind = None` is a model's own declaration that no door reaches a row
    of it and nobody can be given a capability over it — so there is no key to
    hold, and the honest answer is no rather than a key invented here. The
    registry already refuses an unscoped model, so on a well-formed build this
    branch is unreachable; it is written because failing closed is the only
    direction this function is allowed to fail in.
    """
    readable: set[str] = set()
    for declaration in registry.declarations():
        kind = kind_of(declaration.model)
        if kind is not None and allows(actor, f"{kind}.read"):
            readable.add(declaration.label)
    return frozenset(readable)


def _read_key_for(label: str) -> str:
    """The read key behind one declared label, for a refusal's own sentence."""
    declaration = registry.by_label(label)
    kind = kind_of(declaration.model) if declaration is not None else None
    return f"{kind}.read" if kind is not None else "read"


class PostgresEngine:
    """The degradation engine: **the rows themselves, behind the same contract.**

    Satisfies `types.SearchEngine` by shape, exactly as `MeiliEngine` does — a
    peer, never a subclass (the `comms/providers.py` precedent). It receives the
    same `ScopeFilter` and resolves nothing: the walls are the chokepoint's in
    both directions, which is why "what you can see does not change" is a
    property of the design rather than a promise two engines each have to keep.

    **One scoped query per requested kind**, over the declared text fields,
    parsed with `websearch_to_tsquery` and ranked with `ts_rank`, then
    rank-merged by the caller. Where the adopting model declares the generated
    `search_vector` column it is read and its GIN index does the work;
    where it does not, the identical vector is computed inline from the same
    declaration. The declaration is the single source in both cases — two lists
    would be two rankings that agree until somebody edits one.

    **Its `upsert` and `delete` are documented no-ops, and that is the point.**
    A generated column needs no sync, so it cannot be stale — which is exactly
    the property you want in the thing you are standing on when the synced
    engine is down. The indexer may hand this engine a batch without branching
    on which engine it is holding.

    **Its index-administration methods refuse instead.** `state`,
    `apply_settings`, `begin_rebuild`, `stage`, `swap` and `drop_index` are the
    reconcile's vocabulary, and the reconcile is Meilisearch's alone — it always
    reaches `engine.engine()`, never this. There is no index here to describe,
    no digest to compare and nothing to swap, and answering those questions with
    a plausible-looking value would let a future reconcile silently do nothing
    and report that it had. A refusal that names the reason is the honest form.
    """

    name = "postgres"

    # --- the read -------------------------------------------------------------

    def query(
        self,
        *,
        kinds: Sequence[str],
        q: str,
        scope: ScopeFilter,
        offset: int,
        limit: int,
    ) -> EngineHits:
        """One window of hits across the requested kinds, under the injected filter.

        `q` reaches Postgres as a **query object** and the scope reaches it as
        ids in the `WHERE` clause. They are two expressions here for the same
        reason they are two parameters at the other engine: the day they become
        one string is the day a hostile `q` can widen a scope.
        """
        collected: list[EngineHit] = []
        total = 0
        for kind in kinds:
            declaration = registry.by_label(kind)
            if declaration is None:
                # A label the build does not declare. `resolve_kinds` refuses
                # one before it ever reaches an engine; this is the belt for a
                # caller that did not come through it.
                continue
            hits, matched = self._one_kind(
                declaration, q=q, scope=scope, offset=offset, limit=limit
            )
            total += matched
            collected.extend(hits)
        collected.sort(key=lambda hit: (-hit.rank, hit.kind, str(hit.id)))
        window = collected[:limit]
        return EngineHits(
            hits=tuple(window),
            total=total,
            offset=offset,
            has_more=(offset + len(window)) < total,
            engine=self.name,
        )

    def _one_kind(
        self,
        declaration: Searchable,
        *,
        q: str,
        scope: ScopeFilter,
        offset: int,
        limit: int,
    ) -> tuple[list[EngineHit], int]:
        """One kind's window, and how many matched under the filter.

        A closed scope answers `([], 0)` without touching the database — `()`
        matches nothing and asking Postgres to confirm that is a round trip
        whose answer is already known, the same short-circuit the chokepoint
        makes one level up.
        """
        if scope.is_closed:
            return [], 0
        try:
            rows = self._scoped(declaration, scope=scope)
            ranked = self._ranked(rows, declaration, q=q)
            matched = ranked.count()
            window = list(ranked[offset : offset + limit])
        except DatabaseError as error:
            # The fallback failing is not the fallback's business to survive:
            # the chokepoint turns this into the one refusal a search can still
            # answer with, because "no engine answered" is genuinely different
            # from "the index is down".
            raise EngineUnavailable("Postgres did not answer a search.") from error
        hits = [
            EngineHit(
                kind=declaration.label,
                id=row.pk,
                label=display_for(declaration, row),
                rank=float(getattr(row, "djb_rank", 0.0) or 0.0),
            )
            for row in window
        ]
        return hits, matched

    def _scoped(self, declaration: Searchable, *, scope: ScopeFilter) -> QuerySet[Any]:
        """The walls, applied to this kind's own table. **Received, never decided.**

        The ids came out of `list_visible_org_ids`, which is the same indexed
        prefix scan `ScopedQuerySet.visible_to` performs — so this filter and
        that one answer with the same rows for the same hat. It is spelled as an
        `IN` over ids rather than as `.for_tenant(t).visible_to(org)` because an
        engine is handed a `ScopeFilter` and never an actor or a `Tenant`: that
        is the contract that makes an engine unable to get scoping wrong.

        Both clauses are here and neither is optional: `tenant_id` first, then
        the organization subtree whenever the kind has one. House rules 8 and 24
        read a chain rooted at a NAMED model class and cannot see a queryset
        built off `declaration.model`, so this pair is held by the sibling tests
        in `tests/test_degradation.py` — a hat that sees its own branch and its
        child's, and neither its parent's nor a neighbouring tenant's — row for
        row, rather than by anybody reading this paragraph.
        """
        rows: QuerySet[Any] = declaration.model._default_manager.filter(
            **{TENANT_ATTRIBUTE: scope.tenant_id}
        )
        if scope.org_ids is not None:
            rows = rows.filter(**{f"{ORG_FIELD}_id__in": list(scope.org_ids)})
        return rows

    def _ranked(self, rows: QuerySet[Any], declaration: Searchable, *, q: str) -> QuerySet[Any]:
        """Narrow to what matches `q`, best first. An empty `q` matches everything.

        Ordering is `-rank, pk`: the tie-break on the primary key is what makes
        a page walk stable, because `ts_rank` produces ties freely and a window
        over an unstable order silently repeats and drops rows.
        """
        if not q.strip():
            return rows.order_by("pk")
        query = SearchQuery(q, search_type="websearch", config=TEXT_SEARCH_CONFIG)
        if self._declares_column(declaration):
            matched = rows.filter(**{VECTOR_FIELD: query})
            column: QuerySet[Any] = matched.annotate(
                djb_rank=SearchRank(F(VECTOR_FIELD), query)
            ).order_by("-djb_rank", "pk")
            return column
        vector = self._computed_vector(declaration)
        matched = rows.annotate(djb_vector=vector).filter(djb_vector=query)
        computed: QuerySet[Any] = matched.annotate(djb_rank=SearchRank(vector, query)).order_by(
            "-djb_rank", "pk"
        )
        return computed

    def _declares_column(self, declaration: Searchable) -> bool:
        """Whether this model carries the generated column."""
        return any(field.name == VECTOR_FIELD for field in declaration.model._meta.concrete_fields)

    def _computed_vector(self, declaration: Searchable) -> SearchVector:
        """The same vector the column would hold, built from the same declaration.

        Declared weights are Postgres's own `setweight` labels, which is why the
        registry closed that vocabulary to `A`–`D` — a letter Meilisearch treats
        as inert is load-bearing here, and `setweight(..., 'E')` is an error from
        the database rather than a ranking nobody notices.

        A dotted declaration (`"owner.name"`) becomes a Django lookup path, so
        the field a document copies and the field this vector reads are the same
        field across a relation.
        """
        return reduce(
            add,
            (
                SearchVector(name.replace(".", "__"), weight=weight, config=TEXT_SEARCH_CONFIG)
                for name, weight in declaration.fields
            ),
        )

    # --- the writes that are no-ops, and the ones that refuse -----------------

    def upsert(self, *, label: str, documents: Sequence[dict[str, Any]]) -> None:
        """Nothing. A generated column is already what the row says."""

    def delete(self, *, label: str, ids: Sequence[UUID]) -> None:
        """Nothing. A deleted row takes its own text with it."""

    def state(self, *, label: str) -> IndexState:
        raise NotImplementedError(self._no_index("state"))

    def apply_settings(self, *, declaration: Searchable, digest: str) -> None:
        raise NotImplementedError(self._no_index("apply_settings"))

    def begin_rebuild(self, *, declaration: Searchable, digest: str) -> str:
        raise NotImplementedError(self._no_index("begin_rebuild"))

    def stage(self, *, staging: str, documents: Sequence[dict[str, Any]]) -> None:
        raise NotImplementedError(self._no_index("stage"))

    def swap(self, *, label: str, staging: str) -> None:
        raise NotImplementedError(self._no_index("swap"))

    def drop_index(self, *, uid: str) -> None:
        raise NotImplementedError(self._no_index("drop_index"))

    def _no_index(self, what: str) -> str:
        return (
            f"PostgresEngine has no index to {what} — it reads the rows themselves. The "
            "reconcile is Meilisearch's and reaches engine.engine(); a caller holding this "
            "engine and asking for index administration has the wrong engine, not the "
            "wrong argument."
        )


def _circuit_state() -> tuple[bool, bool]:
    """`(cooling_down, already_degraded)`, in **one** cache round trip.

    One `get_many` rather than two `get`s because this sits on every search:
    the healthy path must cost one network hop to the cache and nothing else,
    and two keys read separately is the same information for twice the latency.
    """
    seen = cache.get_many([COOLDOWN_KEY, DEGRADED_KEY])
    return COOLDOWN_KEY in seen, DEGRADED_KEY in seen


def _open_circuit(*, tenant: Tenant, primary: str, fallback: str) -> None:
    """Stop calling the primary for a while, and announce it **if we are first**.

    The cooldown is set unconditionally — every failing request pushes the
    window out, which is what makes an outage cost one dead round trip per TTL
    rather than one per request. The announcement is behind `cache.add`, which
    is atomic in every backend this runs on (`SETNX` in Redis, a locked write in
    locmem), so exactly one process across the fleet emits the event no matter
    how many discover the outage at once.
    """
    cache.set(COOLDOWN_KEY, True, COOLDOWN_SECONDS)
    if cache.add(DEGRADED_KEY, True, None):
        services.announce_degraded(tenant=tenant, engine=primary, fallback=fallback)


def _close_circuit(*, tenant: Tenant, primary: str) -> None:
    """Announce the recovery **if we are the one who cleared the flag**.

    `cache.delete` returns whether the key was there, and that return value is
    the claim: the process that removed the flag is the one that announces, and
    every healthy search after it removes nothing and announces nothing. On the
    normal path — the flag absent — this is not even a write, because the caller
    read the state already and only calls here when the flag was seen.
    """
    if cache.delete(DEGRADED_KEY):
        services.announce_recovered(tenant=tenant, engine=primary)


def get_search_page(
    *,
    tenant: Tenant | None,
    actor: Any,
    q: str = "",
    kinds: Sequence[str] | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    include_count: bool = False,
) -> SearchPage:
    """Search everything this actor can see, in this tenant, across the declared kinds.

    Engine-blind by construction: the caller names no engine, the engine names
    no actor, and the only thing that crosses between them is a `ScopeFilter`
    built out of ids this function resolved.

    **A kind this build does not declare refuses here** rather than narrowing to
    nothing — `registry.resolve_kinds` raises `Invalid`, both doors render it
    from the one composer, and the engine is never asked about a name nobody
    could have meant.

    **And a kind this ACTOR may not read refuses too, before the engine is
    asked** (ADR core-27, Phase R). A read is a permission now: `kinds` left out
    searches every kind you may read, and naming one you may not is `Forbidden`
    with that key's own sentence. The two refusals are different on purpose —
    `Invalid` is "no such kind anywhere", `Forbidden` is "that kind, not you" —
    because they want different actions from the caller.

    **The circuit is here and not at the door**, for the reason every other
    decision in this app is here: both doors call this function, and a failover
    written at one of them would be a failover the other did not have.
    """
    primary = engine_module.engine()
    fallback = PostgresEngine()
    # Read BEFORE the early exits below, and that ordering is load-bearing. The
    # empty page names an engine, so an empty page answered while the circuit is
    # open must name the same engine an entitled page would — otherwise "you can
    # see nothing" and "there is nothing" stop being byte-identical during an
    # outage, which is the one distinction this endpoint must never publish.
    cooling_down, already_degraded = _circuit_state()
    answering = fallback if cooling_down else primary
    # `count` is `0` and not `None` whenever the caller asked, on every branch
    # below: `None` means "not counted" and this caller counted. `engine`
    # is named even though no engine ran, and that is the ONE deliberate
    # inaccuracy in this module — see the route's contract, which states it.
    # Saying "no engine answered you" here would be a difference a client could
    # read, and the whole posture of this function is that a page you are not
    # entitled to is byte-identical to a page that matched nothing.
    empty = SearchPage(
        items=[],
        has_more=False,
        next_cursor=None,
        count=0 if include_count else None,
        engine=answering.name,
    )
    if tenant is None:
        return empty
    org_ids = list_visible_org_ids(tenant=tenant, actor=actor)
    if org_ids is None:
        # An unresolved hat. The empty page, byte-identical to a page that
        # matched nothing — see the module docstring.
        return empty

    labels = registry.resolve_kinds(kinds)

    # **Phase R: kinds ∩ readable, and the engine is never asked otherwise.**
    # The vocabulary check came first (`resolve_kinds` above) because a name
    # nobody could have meant is a different mistake from a name you may not
    # read, and the two want different actions from the caller. Then:
    #
    # * an EXPLICIT `kinds` naming a declared kind this actor may not read
    #   refuses, with that key's own sentence. The vocabulary is a published
    #   door (`GET /search/kinds/`), so naming it leaks nothing a `GET` did not
    #   already hand over — and the alternative, silently searching fewer kinds
    #   than were asked for, is exactly the shape `resolve_kinds`' own docstring
    #   records as the defect a field test found.
    # * `kinds` left OUT means "everything", and everything is everything you
    #   may read. Narrowing there is not a refusal: nobody named the kind.
    readable = list_readable_kinds(actor)
    if kinds:
        refused = [label for label in labels if label not in readable]
        if refused:
            raise Forbidden(refusal_sentence(_read_key_for(refused[0])))
    labels = tuple(label for label in labels if label in readable)
    if not labels:
        # A build that declares no searchable kind at all, or an actor who may
        # read none of the ones it declares. The SAME empty page either way, and
        # deliberately: a page you are not entitled to is byte-identical to a
        # page that matched nothing — the posture this whole module is built on.
        return empty

    size = max(min(limit or DEFAULT_LIMIT, MAX_LIMIT), 1)
    tenant_key = str(tenant.pk)
    offset = 0
    if cursor:
        keys = decode_cursor(cursor, tenant_key=tenant_key, ordering=CURSOR_ORDERING)
        offset = max(int(keys[0]), 0)

    def page_from(engine: SearchEngine) -> SearchPage:
        """This request's page, out of whichever engine is answering it.

        A closure rather than eight repeated keyword arguments at three call
        sites: the arguments are this request's, they do not change between the
        attempt and the failover, and three copies of them is three places for
        the degraded page to drift from the healthy one.
        """
        return _engine_page(
            engine,
            tenant=tenant,
            org_ids=org_ids,
            labels=labels,
            q=q,
            offset=offset,
            size=size,
            tenant_key=tenant_key,
            include_count=include_count,
        )

    if cooling_down:
        # Inside the TTL. The primary is not called at all — this is the whole
        # of what a cooldown buys, and the criterion a call counter asserts.
        return page_from(fallback)

    try:
        page = page_from(primary)
    except EngineUnavailable as unreachable:
        # The failover reaches the sink as a structured line with this
        # request's correlation id already bound, so the event below and the log
        # line are one episode rather than two coincidences.
        log.warning(
            "search.engine.unreachable",
            engine=primary.name,
            serving=fallback.name,
            reason=str(unreachable),
        )
        _open_circuit(tenant=tenant, primary=primary.name, fallback=fallback.name)
        try:
            return page_from(fallback)
        except EngineUnavailable as collapsed:
            # Both engines at once. The index being down is survivable and this
            # is not: the fallback failing means Postgres did not answer, which
            # is the only state this door can still honestly refuse in.
            raise SearchUnavailable() from collapsed

    if already_degraded:
        _close_circuit(tenant=tenant, primary=primary.name)
    return page


def _engine_page(
    engine: SearchEngine,
    *,
    tenant: Tenant,
    org_ids: tuple[UUID, ...],
    labels: Sequence[str],
    q: str,
    offset: int,
    size: int,
    tenant_key: str,
    include_count: bool,
) -> SearchPage:
    """One page out of one engine. **The same body for both of them.**

    Extracted so the circuit above chooses an engine and nothing else. A
    fallback path that assembled its own page would be a second place for the
    envelope, the merge order and the cursor arithmetic to be decided — and the
    first thing to differ between a healthy answer and a degraded one would be
    something no criterion is watching.
    """
    hits: list[SearchHitOut] = []
    total = 0
    has_more = False
    for label in labels:
        declaration = registry.by_label(label)
        if declaration is None:  # pragma: no cover - resolve_kinds only returns declared labels
            continue
        scope = registry.scope_for(tenant_id=tenant.pk, org_ids=org_ids, declaration=declaration)
        if scope.is_closed:
            # A hat that resolved to no visible organization. `()` and `None`
            # are different facts and this is the closed one: it matches
            # nothing, and asking the engine to confirm that would be a call
            # whose answer is already known.
            continue
        found = engine.query(kinds=[label], q=q, scope=scope, offset=offset, limit=size)
        total += found.total
        has_more = has_more or found.has_more
        hits.extend(
            SearchHitOut(kind=hit.kind, id=hit.id, label=hit.label, rank=hit.rank)
            for hit in found.hits
        )

    hits.sort(key=lambda hit: (-hit.rank, hit.kind, str(hit.id)))
    items = hits[:size]
    has_more = has_more or len(hits) > size
    next_cursor = (
        encode_cursor(tenant_key=tenant_key, ordering=CURSOR_ORDERING, keys=[offset + len(items)])
        if has_more and items
        else None
    )
    return SearchPage(
        items=items,
        has_more=has_more,
        next_cursor=next_cursor,
        count=total if include_count else None,
        engine=engine.name,
    )
