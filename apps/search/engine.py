"""The only place in this product that speaks to Meilisearch. **House rule 33.**

One door to the index, and the fence is the rule: no module under `apps/`
outside this one imports the `meilisearch` client or names `MEILI_URL` /
`MEILI_MASTER_KEY` (`config/settings/` excepted, where the environment is read),
and nothing outside `rules.yaml`'s allow-list imports this module at all.

**Why a fence and not a convention.** An external index that does not carry the
tenant walls is a probing oracle: type a word, learn whether somebody else's row
contains it. The walls are injected by exactly one function
(`selectors.resolve_scope`), and that is only true while there is exactly one
way to reach the engine. A second module holding a client is not a style
problem — it is a second, unaudited query path with no filter on it. So the
credential is read here, the timeout is set here, and the deciding is done above
this file.

**What this module is NOT.** It writes to no model, reads no model, and does not
know what a tenant is. It takes ids and strings and returns ids and strings. The
`ScopeFilter` it receives was resolved in Postgres by somebody else; this file
turns it into a filter expression and never composes one out of anything a
client sent. `q` travels as the engine's `q` parameter and is **never**
concatenated into the filter — which is the whole of the smuggling defence, and
what the hostile-corpus probe verifies.

**The console is a window, not a door** (rule 27's posture, applied here).
Index settings are *code*: `registry.index_settings` decides them, this module
applies them, and the startup reconcile re-applies them whenever the declaration
digest moves. A setting somebody hand-edits in the Meili dashboard is overwritten
the next time the digest says so — that is a proven criterion, not a hope.

**Where the digest lives.** Meilisearch has no metadata slot on an index, so the
declaration digest is stored as a **sentinel document** under the reserved id
`__declaration__`. It carries no `tenant_id`, and every query this product makes
filters on `tenant_id`, so the sentinel is unreachable through the chokepoint by
construction rather than by being remembered — the same argument the fence
itself rests on. `state()` reads it; `apply_settings()` writes it.

**Index names are checkout-derived** (`settings.MEILI_INDEX_PREFIX`, derived
from the database name in use exactly as the cache prefix and the task queue
are, and deliberately not `PRODUCT_NAME` — this is infrastructure identity, per
ADR platform-1's compose clause). Two worktrees, and every xdist worker, therefore
write into disjoint index namespaces and parallel gates never meet in Meili any
more than they do in Postgres.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import meilisearch
from django.conf import settings
from meilisearch.errors import (
    MeilisearchApiError,
    MeilisearchCommunicationError,
    MeilisearchError,
    MeilisearchTimeoutError,
)

from apps.core.log import get_logger
from apps.search.registry import (
    ORG_ATTRIBUTE,
    TENANT_ATTRIBUTE,
    declaration_digest,
    index_settings,
)
from apps.search.types import (
    EngineHit,
    EngineHits,
    EngineUnavailable,
    IndexState,
    ScopeFilter,
    Searchable,
)

log = get_logger(__name__)

#: The engine's name on the wire (`SearchPage.engine`). A caller may surface it
#: or ignore it; what it may not do is have to guess which engine answered.
ENGINE_NAME = "meili"

#: Seconds. A search is a small round trip to a container on the same network,
#: and a hung one is a request thread that never comes back. ADR search-2's
#: declared budget for the degradation circuit is ~800 ms for connect + query;
#: this is that budget, named once, and the circuit reads it rather than re-choosing it.
QUERY_TIMEOUT_MS = 800

#: Seconds a write may take to be CONFIRMED. Writes are not on anybody's
#: request path — they are activities with a Temporal retry behind them — so
#: this is generous where the query budget is tight.
WRITE_TIMEOUT_MS = 30_000

#: The reserved document id the declaration digest is stored under. Two
#: underscores each side, which no UUID can be, so it cannot collide with a
#: row's own id.
DECLARATION_DOCUMENT_ID = "__declaration__"

#: The field on that document.
DIGEST_FIELD = "digest"

#: What a Meili index uid may contain. Anything else in a derived prefix is
#: replaced, because a prefix that produced an illegal uid would fail at the
#: first write of a fresh checkout — the least convenient possible moment.
_UID_SAFE = re.compile(r"[^A-Za-z0-9_-]")

#: The staging index a rebuild builds into before the swap.
STAGING_SUFFIX = "_staging"


def meili_url() -> str:
    """Where the index is. **Read from settings**, in this module only.

    `settings.MEILI_URL` and not the process environment, and the difference
    matters: reading the environment here made this the one
    external service in the product outside `config/settings/test.py`'s pin, so
    the suite dialled whatever the developer's `.env` happened to say — and a
    checkout pointed at an unreachable Meilisearch ran a different suite from
    CI's, which is exactly the hazard that file's own comment names ("the suite
    measures one world, and it is not the one whoever ran it happens to have").
    It surfaced as `test_the_sweeps_still_run_from_a_live_worker` dying at 22s
    with a message that named nothing.

    This is house rule 33's shape rather than an exception to it: the rule
    excepts `config/settings/` precisely so the environment can be read into a
    setting, its violation message says the pair is "read in
    apps/search/engine.py and declared in config/settings", and `guards.py`
    recorded the move as expected. What the fence protects is that *this* module
    is the only one under `apps/` that reaches the index — which is unchanged.
    """
    return str(settings.MEILI_URL).strip()


def meili_master_key() -> str:
    """The credential. Read here and named nowhere else under `apps/` (rule 33).

    Empty is legal and means an unkeyed engine — which a laptop can be and a
    deployment must not. `.env.example` ships a published dev value precisely so
    that dev and production are the same *shape*: with a key set, the engine
    requires it on every request, and a missing-key bug cannot hide until
    staging.

    Through settings for the reason `meili_url` above gives at length.
    """
    return str(settings.MEILI_MASTER_KEY).strip()


def index_prefix() -> str:
    """The per-CHECKOUT index namespace: `settings.MEILI_INDEX_PREFIX`.

    Settings derive it from the database name in use — the name parsed out of
    the assembled database URL, the one `CACHE_KEY_PREFIX` and
    `TEMPORAL_TASK_QUEUE` ride — so the invariant is one line: **two checkouts
    that cannot share a database cannot share an index**, whether the name
    arrived as `DATABASE_NAME` or only inside `DATABASE_URL`. A pinned
    `MEILI_INDEX_PREFIX` wins outright, as the other two pins do, and carries
    their hazard: a stale pin is two checkouts sharing a namespace again.

    A database name is already uid-safe in every case this repository produces
    (`djb_<branch>_<8 hex>`), and it is sanitised anyway: a product with an
    exotic database name or pin gets a legal uid rather than a 400 from Meili on
    the first write. When sanitising would have changed the name, a short hash
    of the original is appended, so two names that sanitise to the same string
    still get different prefixes.
    """
    raw = str(settings.MEILI_INDEX_PREFIX).strip()
    safe = _UID_SAFE.sub("_", raw)
    if safe == raw:
        return safe
    return f"{safe}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"


def index_name(label: str) -> str:
    """The live index for one kind: `<prefix>_<kind>`.

    **One shared index per kind, all tenants together, filtered** — not
    index-per-tenant. ADR search-2 reasons the rejection at length; the short
    version is that a thousand tenants times K kinds is thousands of index
    settings surfaces to keep reconciled, and isolation never rode the topology
    in either design. It rides the injected filter, which is why the filter is
    the thing born proven.
    """
    return f"{index_prefix()}_{label}"


def staging_index_name(label: str) -> str:
    """Where a rebuild builds, before it becomes the live one in one atomic act."""
    return f"{index_name(label)}{STAGING_SUFFIX}"


def scope_expression(scope: ScopeFilter) -> str:
    """The filter, built from resolved ids and **nothing the client sent**.

        tenant_id = "<t>" AND org_id IN ["<a>", "<b>"]      # an org-scoped kind
        tenant_id = "<t>"                                    # a tenant-scoped kind

    The values are UUIDs that came out of Postgres, rendered through `str()` on
    a `UUID` object — so there is no path by which a query string, a header or a
    body could reach this expression even if somebody wanted it to. That is the
    smuggling defence stated as code rather than as a promise.

    A closed scope (`org_ids == ()`, an unresolved hat) never reaches here: the
    chokepoint answers the empty page without calling the engine at all.
    """
    tenant = f'{TENANT_ATTRIBUTE} = "{UUID(str(scope.tenant_id))}"'
    if scope.org_ids is None:
        return tenant
    rendered = ", ".join(f'"{UUID(str(value))}"' for value in scope.org_ids)
    return f"{tenant} AND {ORG_ATTRIBUTE} IN [{rendered}]"


class MeiliEngine:
    """The default engine (ADR search-2). Satisfies `types.SearchEngine` by shape.

    Stateless apart from the client it holds, and the client is built per
    instance rather than per call so a request does not pay a connection setup
    it can share. Every method that talks to the server turns the client's three
    failure classes into one `EngineUnavailable`, because the *caller* has one
    decision to make — answer some other way — and three exception types would
    make three call sites decide it separately.
    """

    name = ENGINE_NAME

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else _build_client()

    # --- reads ----------------------------------------------------------------

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

        `limit + 1` is asked for so `has_more` is answered without a second call
        — the same trick `core.api.pagination` uses, for the same reason.

        `q` goes in as `q` and the filter goes in as `filter`. They are two
        parameters to Meilisearch and they are two parameters here; the day they
        become one string is the day a hostile `q` can widen a scope.
        """
        expression = scope_expression(scope)
        collected: list[EngineHit] = []
        total = 0
        for kind in kinds:
            response = self._search_one(
                kind=kind, q=q, expression=expression, offset=offset, limit=limit + 1
            )
            total += int(response.get("totalHits", response.get("estimatedTotalHits", 0)) or 0)
            for position, document in enumerate(response.get("hits", []) or []):
                identifier = document.get("id")
                if identifier is None or identifier == DECLARATION_DOCUMENT_ID:
                    continue
                collected.append(
                    EngineHit(
                        kind=kind,
                        id=UUID(str(identifier)),
                        label=str(document.get("label", "")),
                        # Meili returns hits already ranked and does not publish
                        # a score by default; position within the kind is the
                        # rank we can honestly report, and it is descending so a
                        # higher number is a better hit across every engine.
                        rank=float(len(kinds) * 1000 - position),
                    )
                )
        collected.sort(key=lambda hit: (-hit.rank, hit.kind, str(hit.id)))
        window = collected[:limit]
        return EngineHits(
            hits=tuple(window),
            total=total,
            offset=offset,
            has_more=(offset + len(window)) < total,
            engine=self.name,
        )

    def state(self, *, label: str) -> IndexState:
        """What this kind's index is today. The reconcile's one read per kind.

        A missing index is `exists=False` and **not** an error: on a fresh
        checkout that is the normal case, and it is the case the reconcile
        exists to fix. Anything else the server says is `EngineUnavailable`,
        because "I could not ask" and "there is nothing there" must never
        collapse into one answer — collapsing them is how a reconcile silently
        rebuilds a healthy index, or silently skips a missing one.
        """
        uid = index_name(label)
        try:
            index = self._client.get_index(uid)
        except MeilisearchApiError as error:
            if _is_index_not_found(error):
                return IndexState(label=label, exists=False)
            raise EngineUnavailable(f"Meilisearch refused a read of {uid}: {error}") from error
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable(f"Meilisearch did not answer about {uid}.") from error
        digest = ""
        try:
            document = index.get_document(DECLARATION_DOCUMENT_ID)
            digest = str(getattr(document, DIGEST_FIELD, "") or "")
        except MeilisearchApiError:
            # An index with no sentinel is an index built by something that did
            # not know about digests. It reads as "different from anything this
            # build declares", which is exactly right: rebuild it.
            digest = ""
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable(f"Meilisearch did not answer about {uid}.") from error
        documents = 0
        try:
            stats = index.get_stats()
            documents = max(int(getattr(stats, "number_of_documents", 0) or 0) - 1, 0)
        except MeilisearchError:  # pragma: no cover - stats are advisory
            documents = 0
        return IndexState(label=label, exists=True, digest=digest, documents=documents)

    # --- writes ---------------------------------------------------------------

    def apply_settings(self, *, declaration: Searchable, digest: str) -> None:
        """Make the index's settings the declaration's, and stamp the digest.

        Idempotent by construction: the settings are computed from the
        declaration every time, so applying them twice is applying the same
        value twice. That is what lets the reconcile re-apply on a digest change
        without asking what changed.

        The digest is stamped **last**, after the settings the server confirmed.
        A digest written first would say "this index matches the declaration"
        about an index that had not been changed yet, and a worker that died in
        between would leave a lie behind that no later boot would notice.
        """
        uid = index_name(declaration.label)
        index = self._ensure_index(uid)
        self._await(index.update_settings(index_settings(declaration)), uid)
        self._await(
            index.add_documents(
                [
                    {
                        "id": DECLARATION_DOCUMENT_ID,
                        DIGEST_FIELD: digest or declaration_digest(declaration),
                    }
                ]
            ),
            uid,
        )
        log.info("search.index.settings_applied", index=uid, kind=declaration.label, digest=digest)

    def upsert(self, *, label: str, documents: Sequence[dict[str, Any]]) -> None:
        """Put documents in, and **wait for the engine to confirm the task**.

        The wait is the point. An activity that returned before Meili had
        settled would report success for work the server might still reject, and
        Temporal's retry — the only thing standing between a transient failure
        and a permanently stale document — would never fire.
        """
        if not documents:
            return
        uid = index_name(label)
        index = self._ensure_index(uid)
        self._await(index.add_documents(list(documents)), uid)

    def delete(self, *, label: str, ids: Sequence[UUID]) -> None:
        """Take documents out by id, confirmed the same way."""
        if not ids:
            return
        uid = index_name(label)
        index = self._ensure_index(uid)
        self._await(index.delete_documents([str(value) for value in ids]), uid)

    def swap(self, *, label: str, staging: str) -> None:
        """Make the staging index the live one, in one atomic act.

        Meilisearch's index swap is what keeps search **answering during a
        rebuild**: queries hit the old index right up to the swap and the new one
        immediately after, and there is no window where the live index is half
        built. It is also why the backup story for the Meili volume is honestly
        "none" — the source of record is Postgres and the recovery story is this.
        """
        uid = index_name(label)
        # Meilisearch swaps two indexes that BOTH exist; the very first build of
        # a kind has no live index to swap with. Creating an empty one here is
        # what makes "create" and "rebuild" one code path — the alternative is a
        # branch exercised once per kind per deployment, which is the branch
        # nobody's test covers.
        self._ensure_index(uid)
        try:
            task = self._client.swap_indexes([{"indexes": [uid, staging]}])
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable(f"Meilisearch did not answer a swap of {uid}.") from error
        self._await(task, uid)
        log.info("search.index.swapped", index=uid, staging=staging)

    def begin_rebuild(self, *, declaration: Searchable, digest: str) -> str:
        """An empty staging index for this kind, settings applied and digest stamped.

        The staging index is **dropped first if it is there**, because the only
        way one survives a run is that a rebuild died half-way, and half a
        rebuild is worse than none: swapping it in would replace a complete
        index with a truncated one, silently, and every later boot would find a
        matching digest and leave it alone.
        """
        uid = staging_index_name(declaration.label)
        self.drop_index(uid=uid)
        self._await(self._client.create_index(uid, {"primaryKey": "id"}), uid)
        index = self._client.index(uid)
        self._await(index.update_settings(index_settings(declaration)), uid)
        self._await(
            index.add_documents([{"id": DECLARATION_DOCUMENT_ID, DIGEST_FIELD: digest}]), uid
        )
        return uid

    def stage(self, *, staging: str, documents: Sequence[dict[str, Any]]) -> None:
        """Put a batch into a staging index, confirmed like every other write."""
        if not documents:
            return
        self._await(self._client.index(staging).add_documents(list(documents)), staging)

    def drop_index(self, *, uid: str) -> None:
        """Delete an index if it is there. A missing one is not an error.

        **Meilisearch deletes asynchronously**, so "there is no such index" does
        not come back as a refusal from the call — it comes back as a TASK that
        settles `failed` with `index_not_found` on it. Measured against the
        pinned container rather than read off a doc page: a `drop_index` that
        caught only the synchronous refusal raised `EngineUnavailable` on every
        first-ever rebuild, which is the one moment the reconcile exists for.
        """
        try:
            self._await(self._client.delete_index(uid), uid, allow_missing=True)
        except MeilisearchApiError as error:
            if not _is_index_not_found(error):
                raise EngineUnavailable(f"Meilisearch refused a drop of {uid}: {error}") from error
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable(f"Meilisearch did not answer a drop of {uid}.") from error

    # --- the seams the class talks to the server through ----------------------

    def _search_one(
        self, *, kind: str, q: str, expression: str, offset: int, limit: int
    ) -> dict[str, Any]:
        uid = index_name(kind)
        try:
            return dict(
                self._client.index(uid).search(
                    q,
                    {
                        "filter": expression,
                        "offset": offset,
                        "limit": limit,
                        "attributesToRetrieve": ["id", "label"],
                    },
                )
            )
        except MeilisearchApiError as error:
            if _is_index_not_found(error):
                # A declared kind whose index has not been built yet. The
                # reconcile is what fixes it; a search meanwhile answers with
                # what the other kinds have rather than refusing everything.
                log.warning("search.index.missing", index=uid, kind=kind)
                return {"hits": [], "totalHits": 0}
            raise EngineUnavailable(f"Meilisearch refused a search of {uid}: {error}") from error
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable("Meilisearch did not answer a search.") from error

    def _ensure_index(self, uid: str) -> Any:
        try:
            return self._client.get_index(uid)
        except MeilisearchApiError as error:
            if not _is_index_not_found(error):
                raise EngineUnavailable(f"Meilisearch refused a read of {uid}: {error}") from error
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable(f"Meilisearch did not answer about {uid}.") from error
        try:
            self._await(self._client.create_index(uid, {"primaryKey": "id"}), uid)
        except EngineUnavailable:
            raise
        except MeilisearchError as error:  # pragma: no cover - a concurrent creator won
            log.info("search.index.create_raced", index=uid, error=str(error))
        return self._client.index(uid)

    def _await(self, task: Any, uid: str, *, allow_missing: bool = False) -> None:
        """Block until the server has settled the task, or say it did not.

        Every write in this module goes through here, which is what makes "the
        activity completes only on Meili task confirmation" true of the module
        rather than of whoever remembered to call `wait_for_task`. An activity
        that returned before the server had settled would report success for
        work the server might still reject, and Temporal's retry — the only
        thing standing between a transient failure and a permanently stale
        document — would never fire.

        `allow_missing` is for the one caller that means it: dropping an index
        that is not there is the goal rather than a failure, and the server says
        so with a settled-`failed` task rather than with a refusal.
        """
        task_uid = getattr(task, "task_uid", None) or getattr(task, "uid", None)
        if task_uid is None:
            return
        try:
            settled = self._client.wait_for_task(task_uid, timeout_in_ms=WRITE_TIMEOUT_MS)
        except (MeilisearchCommunicationError, MeilisearchTimeoutError) as error:
            raise EngineUnavailable(f"Meilisearch did not settle a task on {uid}.") from error
        status = str(getattr(settled, "status", "") or "")
        if not status or status == "succeeded":
            return
        failure = dict(getattr(settled, "error", None) or {})
        if allow_missing and str(failure.get("code", "")) == "index_not_found":
            return
        raise EngineUnavailable(f"Meilisearch failed a task on {uid}: {status} ({failure})")


def _build_client() -> Any:
    """The client, with the credential and the query budget on it."""
    return meilisearch.Client(
        meili_url(),
        meili_master_key() or None,
        timeout=max(QUERY_TIMEOUT_MS // 1000, 1),
    )


def _is_index_not_found(error: MeilisearchApiError) -> bool:
    """Whether this refusal is "no such index" rather than anything else.

    Read off the server's own machine-readable code and not off its prose, so a
    reworded message in a future Meilisearch does not silently turn "missing"
    into "unavailable" — which would make every fresh checkout's first reconcile
    look like an outage.
    """
    return str(getattr(error, "code", "") or "") == "index_not_found"


def engine() -> MeiliEngine:
    """The engine this deployment searches with.

    A function rather than a module-level instance so that no import builds a
    client — a test suite that never searches never opens a socket, and the
    degradation circuit adds gets one place to choose from rather than a constant
    somebody has already bound.
    """
    return MeiliEngine()
