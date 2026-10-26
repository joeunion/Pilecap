"""The vocabulary every other module here speaks, and the engine contract.

Four things live here and nothing else: what an app **declares** it wants
searchable (`Searchable`), what the chokepoint **resolves** and hands down
(`ScopeFilter`), what an engine **hands back** (`EngineHit`, `EngineHits`), and
the **shape an engine has to have** (`SearchEngine`). Keeping them in `types.py`
rather than in `engine.py` is what lets `selectors.py`, `registry.py` and the
tests name them without importing the module house rule 33 fences — a selector
that had to import `engine` to spell a filter would make the fence's allow-list
the whole app.

**`ScopeFilter` carries resolved ids and nothing else.** No actor, no acting
hat, no materialized path. That is the single most load-bearing sentence in the
app: an engine that cannot see who is asking cannot get the answer wrong, it can
only receive it, and the one function that builds this value
(`selectors.resolve_scope`) is therefore the whole wall. It is also why **no
path is ever copied into a document** — the path is Postgres's private
vocabulary, and a re-parent would otherwise become a bulk rewrite of every
document under the moved node (ADR search-2, "what happens on an org MOVE").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


class EngineUnavailable(RuntimeError):
    """One engine did not answer. **Not a refusal, and deliberately not one.**

    A `DomainError` would make "the search index is down" part of the product's
    published refusal vocabulary, and it is not: ADR search-2 rules it a
    *degraded state* the system survives, and the circuit in
    `selectors.py` does exactly that — the same request that met an unreachable
    Meilisearch is answered from `PostgresEngine` at `200` with
    `engine="postgres"`, and the transition is announced on the spine.

    So this exception never reaches a door. It is the **word one engine uses to
    tell the chokepoint it could not answer**, which is a question the
    chokepoint has a plan for. The one state that has no plan — both engines
    unreachable at once, which means the database did not answer — is where the
    chokepoint raises `core.exceptions.SearchUnavailable` instead: a registered
    refusal, `503`, `code: "search_unavailable"`, rendered by the one composer
    both doors use. That closes an earlier recorded residual (a `503` with no
    machine-readable code) at the narrower place it belongs, rather than
    publishing "the index is down" as something a client has to handle.
    """


@dataclass(frozen=True, slots=True)
class Searchable:
    """One kind of thing that can be found, as the app that owns it declares it.

        # apps/example/search.py — the live worked adoption, copied here whole
        from apps.example import events
        from apps.example.models import Widget
        from apps.search.types import Searchable

        SEARCHABLES = [
            Searchable(
                model=Widget,
                label="widgets",
                fields=[("name", "A"), ("notes", "B")],
                refresh_on=(events.WIDGET_CREATED, events.WIDGET_UPDATED),
                display="name",
            ),
        ]

    **The import line is part of the example**, from an earlier field report: a
    copy-pasted body with no imports above it is a `NameError` at the first boot
    after adopting, and `search.py` is a file most people will only ever write
    once. It is also the ONE import adopting costs — a value type, no engine, no
    client — which is why the adopting app's `AppConfig.depends_on` grows
    `"search"` and nothing else changes.

    Declared in a discovered `apps/<x>/search.py` — the `events.py` / `meters.py`
    pattern — so registering a kind never edits `config/` or this app.
    `apps/example/search.py` is the worked file; read it before writing yours.

    **One declaration drives both engines.** `fields` is the Meili document's
    searchable-attribute list *in ranking order* (declaration order is the
    ranking, which is why it is a sequence and not a set) and the same list
    feeds the `search_vector` tsvector column the adopting app owns for the
    degradation engine. Two lists would be two rankings that agree until
    somebody edits one.

    **The weights are `A`, `B`, `C` or `D`, and the vocabulary is closed** —
    said here, at the surface an adopter reads, and not only in the registry
    that refuses a fifth letter. They are Postgres's four `setweight` labels,
    because that is the half of the declaration that has to be a real thing
    somewhere: Meilisearch has no weights at all, so the letter is **inert** on
    the primary engine and **load-bearing** on the fallback, where
    `setweight(..., 'E')` is an error from the database. A typo would therefore
    ship green and break on the day the circuit opens — which is the day
    everything else is already going wrong — so `registry.validate` refuses it
    at boot instead.

    **The label grammar, likewise stated here.** `label` is the kind: the tail
    of the Meilisearch index uid (`<prefix>_<label>`), the `kind` on a hit, and
    the value `?kinds=` names on the wire. It is lowercase letters, digits, `_`
    and `-`, starting with a letter or a digit — an illegal one is a 400 from
    the server at the first write of a fresh checkout, which is the least
    convenient possible moment, and a public vocabulary nobody can type. **One
    label is one index**: two kinds sharing one would interleave two document
    shapes in one place, and each rebuild would silently empty the other. It is
    public vocabulary and it freezes the day a client can send it.

    `refresh_on` names events from the emitting app's own `events.py` — never
    literals (house rule 16). The registry refuses at import time when one of
    them is not a declared event, because a name nobody publishes is a
    subscription that silently never fires: the reconcile builds the first
    document and then nothing ever refreshes it.
    """

    model: type[Any]
    label: str
    fields: Sequence[tuple[str, str]]
    refresh_on: tuple[str, ...] = ()
    #: The display string a picker shows, read off the row. A dotted path is
    #: walked, so `"owner.name"` is legal; the default is `str(row)`.
    display: str = ""


@dataclass(frozen=True, slots=True)
class SearchKind:
    """One entry in the published vocabulary: a kind, and the app that owns it.

    The catalogue's value type, kept here beside `Searchable` rather than in
    `schemas.py` for the reason every other type in this module is here: the
    registry derives it and both doors render it, and a registry that had to
    import a wire schema to say what it declares would put the vocabulary's home
    on the wrong side of the door.

    `kind` is the string `?kinds=` names and `SearchHitOut.kind` carries — one
    word for one thing, in three places. `app` is which part of the product owns
    the rows, which is what tells a stranger where to go and fetch one in full.
    """

    kind: str
    app: str


@dataclass(frozen=True, slots=True)
class EngineConfiguration:
    """How this deployment is wired to the index — **configuration, never state.**

    What the integrations census (`apps/search/integrations.py`) needs in order
    to answer "is search real here?", and deliberately nothing more. It says
    where the engine is dialled and whether a credential is set; it does **not**
    say whether anything answered.

    That omission is the whole design and it is `apps/core/health.py`'s
    reasoning one surface over: **Meilisearch being unreachable is a degraded
    state this product survives**, so a census row that went `NOT_CONFIGURED`
    the moment the container was slow would hand the deploy wall a veto over a
    designed degradation — a self-inflicted outage, bought with an instrument.
    Reachability is the circuit's question, answered per request, announced on
    the spine as `search.engine.degraded`. Configuration is this one.

    `keyed` and not `key`: nothing carries the credential out of `engine.py`,
    including into a value type, including for a report. What travels is the
    boolean somebody can act on.
    """

    address: str
    keyed: bool


@dataclass(frozen=True, slots=True)
class ScopeFilter:
    """The walls, resolved in Postgres, as ids an engine can only obey.

    `tenant_id` is always present. `org_ids` is present for an org-scoped kind
    and `None` for a tenant-scoped one — **`None` and the empty tuple are
    different facts and are said differently**: `None` means "this kind is not
    organization-scoped, so the tenant filter is the whole wall", and `()` means
    "this actor's hat resolved to no visible organization", which is the
    fail-closed case and matches nothing. Collapsing them would make an
    unresolved hat read as an unscoped kind, which is the class of defect
    pointed at search.
    """

    tenant_id: UUID
    org_ids: tuple[UUID, ...] | None = None

    @property
    def is_closed(self) -> bool:
        """Whether this filter can match anything at all. `()` cannot."""
        return self.org_ids is not None and not self.org_ids


@dataclass(frozen=True, slots=True)
class EngineHit:
    """One result, as an engine reports it. The lean document, and nothing more."""

    kind: str
    id: UUID
    label: str
    rank: float = 0.0


@dataclass(frozen=True, slots=True)
class EngineHits:
    """One window of results, plus what the engine knows about the rest.

    `total` is the **exact scoped** number of matches — Meili answers it
    exhaustively under the injected filter, which is what makes the anti-oracle
    criterion hold: there is no unfiltered query anywhere to count with, so
    nothing here can count what sits outside your scope.

    `offset` is where this window started and `has_more` is whether another one
    exists. The cursor the door mints is built from those two and nothing else
    (`selectors.get_search_page`), so a client cannot arithmetic its way anywhere.
    """

    hits: tuple[EngineHit, ...] = ()
    total: int = 0
    offset: int = 0
    has_more: bool = False
    #: Which engine answered — `"meili"` today, `"postgres"` once the degradation circuit
    #: exists. On the wire because a degradation the system survives is a state
    #: it announces (ADR search-2), never one it hides.
    engine: str = "meili"


@dataclass
class ReconcileIndexes:
    """What the reconcile schedule starts a pass with; `None` is a pass from an older schedule."""

    #: `core.retry.retry_floor_seconds()`, read on the Django side (rule 9).
    retry_floor: float | None = None


@dataclass
class ReconcileOutcome:
    """What one pass of the startup reconcile did — **or could not do**.

    Two fields, and the second is the one that matters. `outcomes` is
    `{kind: unchanged|created|rebuilt}`, the run's own report: a pass whose
    values are all `unchanged` is the healthy steady state and reads as one at a
    glance in the Temporal UI.

    `incomplete` is why the pass did not finish, and it is empty when it did.

    **It exists because the first version had nowhere to put that answer.**
    The reconcile retried an unreachable Meilisearch
    without bound — deliberately, and the reasoning was right: an index left
    un-materialised because a boot-time reconcile gave up is the silent class,
    reintroduced one layer in. What was wrong was *where* the never-give-up
    lived. Retrying inside one run means the run never completes, so the ledger
    holds an execution that is neither succeeded nor failed and nobody can tell
    "still trying" from "wedged" — and under a time-skipping server, which is
    where the machinery suite drives every declared machine, it is simply a hang.

    The converge-eventually property is unchanged and now lives where it belongs:
    **the schedule's next tick is the retry.** The pass completes, says it could
    not reach the engine, and an hour later another pass tries again — for ever,
    exactly as before, with a run row per attempt that a human can read. This is
    the same posture the search circuit takes one layer up (an unreachable
    index is a degraded state the product announces and survives, never an
    outage it dies of), and the same fix `apps/core/workflows.py`'s prober took
    for the same failure the day before.
    """

    #: `{kind label: what happened to it}`. Partial when `incomplete` is set: a
    #: pass that reconciled three kinds and could not reach the engine for the
    #: fourth says both halves, because "some of it worked" is a different fact
    #: from "none of it did" and an operator needs to be able to tell them apart.
    outcomes: dict[str, str] = field(default_factory=dict)

    #: Why the pass did not finish. Empty string when it did.
    incomplete: str = ""

    @property
    def is_complete(self) -> bool:
        return not self.incomplete


@dataclass(frozen=True, slots=True)
class IndexState:
    """What one kind's index looks like *right now*, as the engine found it.

    The digest is the whole of the startup reconcile (`design-agreements.md`):
    the declaration is the intent, the index is materialized from it, and the
    digest stored **on the index** is how
    a booting worker asks "is what is out there what this build declares?"
    without trusting a file, a runbook or anybody's memory.

    Three answers and they are three different acts:

    * `exists=False` — nothing is there. Rebuild.
    * `exists=True, digest != declared` — something is there and it was built
      from a different declaration. Re-apply the settings, and rebuild where the
      change requires it.
    * `exists=True, digest == declared` — no-op, and the criterion is that the
      no-op is *proven* (zero write calls), not assumed.
    """

    label: str
    exists: bool
    digest: str = ""
    documents: int = 0


@runtime_checkable
class SearchEngine(Protocol):
    """What an engine has to be able to do. Satisfied by shape, not by base class.

    The `comms/providers.py` precedent: a `Protocol`, so the Postgres engine
    the degradation engine adds is a peer of the Meili one rather than a subclass of it, and the
    recording fake the tests use is a peer of both without importing either.

    Every method takes the `ScopeFilter` by keyword and none of them takes an
    actor. That is the contract, not a style: **an engine receives the walls, it
    never resolves them.**
    """

    name: str

    def query(
        self,
        *,
        kinds: Sequence[str],
        q: str,
        scope: ScopeFilter,
        offset: int,
        limit: int,
    ) -> EngineHits:
        """The scoped window. `q` is a query string and never part of a filter."""
        ...

    def state(self, *, label: str) -> IndexState:
        """What this kind's index is today — the reconcile's one read."""
        ...

    def apply_settings(self, *, declaration: Searchable, digest: str) -> None:
        """Make the index's settings the declaration's, and stamp the digest."""
        ...

    def upsert(self, *, label: str, documents: Sequence[dict[str, Any]]) -> None:
        """Put documents in. Waits for the engine to confirm the task."""
        ...

    def delete(self, *, label: str, ids: Sequence[UUID]) -> None:
        """Take documents out, by id."""
        ...

    def swap(self, *, label: str, staging: str) -> None:
        """Make the staging index the live one, atomically."""
        ...

    def begin_rebuild(self, *, declaration: Searchable, digest: str) -> str:
        """Make an empty staging index for this kind and return its name."""
        ...

    def stage(self, *, staging: str, documents: Sequence[dict[str, Any]]) -> None:
        """Put documents into a staging index, confirmed."""
        ...

    def drop_index(self, *, uid: str) -> None:
        """Delete an index if it is there. A missing one is not an error."""
        ...


@dataclass
class RecordingEngine:
    """A `SearchEngine` that records instead of indexing. **Tests only.**

    It lives in `types.py` rather than in a test module for one reason: it is
    what the chokepoint's criteria are *proved against* — criterion 3 is "a
    recording fake engine shows the filter is exactly `tenant_id = <t> AND
    org_id IN [<resolved ids>]`" — and a double that the production types cannot
    see is a double that can drift from the protocol it is standing in for.
    `SearchEngine` is `runtime_checkable`, and a test asserts this satisfies it.
    """

    hits: tuple[EngineHit, ...] = ()
    total: int = 0
    name: str = "recording"
    #: Every `ScopeFilter` this engine was handed, in order. The filter probe
    #: reads this: what the engine RECEIVED is the only honest evidence about
    #: what the chokepoint injected.
    #:
    #: Named `filters` and not `scopes`, which is what it was: `.scopes` is the
    #: attribute the token-ceiling census greps for (`apps/core/tests/
    #: test_scope_readers.py`), and a test double that reads like a module
    #: consulting a permission ceiling is a false positive somebody has to
    #: dismiss every time — the wrong half of a census to teach people to ignore.
    filters: list[ScopeFilter] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    kinds_seen: list[tuple[str, ...]] = field(default_factory=list)
    states: dict[str, IndexState] = field(default_factory=dict)
    #: Every write call, as `(method, label)`. The proven no-op reads this: an
    #: empty list is the assertion, not a hope.
    writes: list[tuple[str, str]] = field(default_factory=list)
    #: Every document handed to `stage`, so a rebuild's OUTPUT is assertable and
    #: not merely its call sequence.
    staged: list[dict[str, Any]] = field(default_factory=list)
    #: Every index this engine was asked to delete. Kept apart from `writes` —
    #: see `drop_index` below.
    dropped: list[str] = field(default_factory=list)

    def query(
        self,
        *,
        kinds: Sequence[str],
        q: str,
        scope: ScopeFilter,
        offset: int,
        limit: int,
    ) -> EngineHits:
        self.filters.append(scope)
        self.queries.append(q)
        self.kinds_seen.append(tuple(kinds))
        window = self.hits[offset : offset + limit]
        total = self.total or len(self.hits)
        return EngineHits(
            hits=tuple(window),
            total=total,
            offset=offset,
            has_more=offset + len(window) < total,
            engine=self.name,
        )

    def state(self, *, label: str) -> IndexState:
        return self.states.get(label, IndexState(label=label, exists=False))

    def apply_settings(self, *, declaration: Searchable, digest: str) -> None:
        self.writes.append(("apply_settings", declaration.label))

    def upsert(self, *, label: str, documents: Sequence[dict[str, Any]]) -> None:
        self.writes.append(("upsert", label))

    def delete(self, *, label: str, ids: Sequence[UUID]) -> None:
        self.writes.append(("delete", label))

    def swap(self, *, label: str, staging: str) -> None:
        self.writes.append(("swap", label))

    def begin_rebuild(self, *, declaration: Searchable, digest: str) -> str:
        self.writes.append(("begin_rebuild", declaration.label))
        return f"{declaration.label}_staging"

    def stage(self, *, staging: str, documents: Sequence[dict[str, Any]]) -> None:
        self.writes.append(("stage", staging))
        self.staged.extend(documents)

    def drop_index(self, *, uid: str) -> None:
        # Recorded on its own list rather than in `writes`, because `writes` is
        # what the proven-no-op asserts is EMPTY and a cleanup drop is not a
        # write to an index anybody reads. Conflating them would make the
        # strongest assertion in this app the loosest one.
        self.dropped.append(uid)
