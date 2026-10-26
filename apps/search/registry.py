"""What this deployment declares searchable, and the digest that materializes it.

Three jobs — discovery, the digest, and the refusal that stands in front of both.

**Discovery.** An app says what of its own is findable by exposing
`SEARCHABLES: list[Searchable]` in a discovered `apps/<x>/search.py` — the
`events.py` / `meters.py` pattern, and the reason registering a kind never edits
`config/`, `pyproject.toml` or this app. One agent per app can add a kind in
parallel because no shared file is touched.

**The digest, and why it is the interesting half.** Rule 27's shape applied to
search (`design-agreements.md`, "Search
materializes from its declarations"): *the declaration is the intent; the index
is materialized from it.* So each kind's index stores the digest of the
declaration that built it, and a booting worker asks one question per kind —
does what is out there match what this build declares?

* nothing there → rebuild;
* there, different digest → re-apply the settings and rebuild;
* there, same digest → **no-op**, and the criterion is that the no-op is
  proven by a write count of zero rather than assumed.

That is what demotes `manage.py search_reindex` from *the* way indexes get
built to the **manual backstop**, exactly as `zitadel_seed` was demoted by the
identity reconcile. A materializer whose only trigger is a human remembering is
the silent class of `operating-protocol.md`'s intent-materialization lens; this
one converges at a moment that always happens.

**What the digest covers is exactly what a rebuild would change**, and nothing
else. It covers the label, the field list *in order* (order is the ranking), the
display expression, and the scope shape (org-scoped kinds carry `org_id` as a
filterable attribute and tenant-scoped ones do not). It deliberately does **not**
cover the model's module path or the `refresh_on` names: moving a model between
modules changes no document, and changing which events refresh a kind changes
what happens *next*, never what is already in the index. A digest that moved for
reasons a rebuild cannot fix would train everybody to ignore it.

`DIGEST_VERSION` is the other half of that honesty: when the way this app builds
documents or settings changes, every index is stale even though no declaration
moved, and bumping the constant is how a build says so.

**The refusal (`validate`), and why it is a boot refusal.** Everything above
takes the declaration at its word, and every way a declaration can be wrong is
a way search *silently* stops working: a field that is not on the model indexes
`None` for ever, a `refresh_on` name nobody publishes is a subscription that
never fires, a weight outside Postgres's four is inert on Meilisearch and an
error on the fallback engine. None of them raises anything at the moment it is
written and none of them shows up in a query result — the index exists, the
requests succeed, and nothing is found. So the whole vocabulary is validated
once, from `SearchConfig.ready()`, and a bad declaration stops the process
(the strongest tier — `apps.usage.meters.validate_declared_meters` and
`core.lifecycle.Lifecycle` are the two siblings that already refuse this way).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from django.apps import apps as django_apps
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured

from apps.core.discovery import declared, imported
from apps.core.exceptions import Invalid, Remedy
from apps.core.models import is_org_scoped
from apps.search.types import ScopeFilter, Searchable, SearchKind

#: The module an app declares its searchables in. Discovered, never registered.
DECLARATION_MODULE = "search"

#: The attribute discovery reads out of it.
DECLARATION_ATTRIBUTE = "SEARCHABLES"

#: Bumped when the DOCUMENT or the SETTINGS this app builds change shape, so
#: that every index goes stale and rebuilds even though no app edited a
#: declaration. Without it, a build that started indexing one more attribute
#: would answer old queries from old documents for ever, and the only tell would
#: be a user saying "it used to find that".
DIGEST_VERSION = 1

#: The two filterable attributes, and there are deliberately only two. Both are
#: ids resolved in Postgres per request. **No materialized path is ever
#: filterable, because no path is ever in a document** — see `types.ScopeFilter`.
TENANT_ATTRIBUTE = "tenant_id"
ORG_ATTRIBUTE = "org_id"

#: The weights a declared field may carry, and the vocabulary is closed.
#:
#: They are Postgres's four `setweight` labels, because that is the half of the
#: declaration that has to be a real thing somewhere: the same `fields` list
#: feeds the degradation engine's `search_vector` tsvector column, and
#: `setweight(..., 'E')` is an error from the database rather than a ranking
#: nobody notices. Meilisearch has no weights at all — declaration ORDER is its
#: ranking — so the letter is inert on the primary engine and load-bearing on
#: the fallback, which is exactly the sort of asymmetry a typo hides in until
#: the day the circuit opens.
WEIGHTS: tuple[str, ...] = ("A", "B", "C", "D")

#: What a label may contain. It becomes the tail of a Meilisearch index uid
#: (`engine.index_name`), and an illegal one is a 400 from the server at the
#: first write of a fresh checkout — the least convenient possible moment to
#: find out, and the reason this is a boot refusal instead.
_LABEL_SAFE = re.compile(r"\A[a-z0-9][a-z0-9_-]*\Z")

#: The module an app declares its EVENT names in. `refresh_on` is validated
#: against it: house rule 16 says an event name is a constant in one file per
#: app and never a literal at a call site, and a `refresh_on` entry naming a
#: string no app declares is a subscription that silently never fires.
EVENTS_MODULE = "events"


def declarations() -> tuple[Searchable, ...]:
    """Every `Searchable` the installed apps declare, in app order; import errors are raised."""
    return tuple(
        searchable
        for _config, declared_here in declared(
            DECLARATION_MODULE, DECLARATION_ATTRIBUTE, predicate=_is_sequence
        )
        for searchable in declared_here
    )


def _is_sequence(value: Any) -> bool:
    """The shape a discovered `SEARCHABLES` takes."""
    return isinstance(value, (list, tuple))


def declared_event_names(app_label: str) -> frozenset[str]:
    """Every module-level UPPER_CASE string `apps/<app_label>/events.py` declares (rule 16)."""
    for config, module in imported(EVENTS_MODULE):
        if config.label == app_label:
            return frozenset(
                value
                for name, value in vars(module).items()
                if name.isupper() and not name.startswith("_") and isinstance(value, str)
            )
    return frozenset()


def refresh_map(
    declarations_: Sequence[Searchable] | None = None,
) -> dict[str, tuple[Searchable, ...]]:
    """Event name -> the kinds that asked to be refreshed by it.

    The indexer's whole routing table, built from the declarations and nothing
    else. An event no kind subscribed to resolves to `()` and the indexer says
    so with a no-op rather than a lookup failure — the spine fans **every**
    committed event at this leg, and most of them are nobody's business here.
    """
    found: dict[str, list[Searchable]] = {}
    for declaration in declarations() if declarations_ is None else tuple(declarations_):
        for name in declaration.refresh_on:
            found.setdefault(name, []).append(declaration)
    return {name: tuple(kinds) for name, kinds in found.items()}


def searchables_for_event(name: str) -> tuple[Searchable, ...]:
    """The kinds one event name refreshes. Empty is the ordinary answer."""
    return refresh_map().get(name, ())


def validate(declarations_: Sequence[Searchable] | None = None) -> tuple[Searchable, ...]:
    """Refuse the whole vocabulary if any declaration is a promise nobody kept.

    Called from `SearchConfig.ready()`, so a bad declaration **stops the
    process at boot** rather than surfacing months later as a kind that quietly
    indexes nothing. `ImproperlyConfigured` out of `ready()` is the strongest
    tier this tree has for a declaration and it is the one its two siblings
    already use: `apps.usage.meters.validate_declared_meters` for the meter
    vocabulary, `core.lifecycle.Lifecycle` and `core.exceptions.register_refusal`
    for theirs. A `manage.py check` would be quieter and would let a wrong
    declaration ride in a running worker until somebody remembered to run it.

    **Why each of these is a boot refusal and not a warning**, because the
    tempting answer to all of them is "skip that kind and carry on":

    * a **missing field** builds a document whose text is `None` for the
      attribute a picker searches on — the kind exists, the index exists, and
      it finds nothing, for ever, with no error anywhere;
    * a **bad weight** is inert on Meilisearch and an error from Postgres, so
      it ships green and breaks on the day the degradation circuit opens
      — which is the day everything else is already going wrong;
    * an **undeclared `refresh_on` name** is a subscription that never fires:
      the first document is written by the startup reconcile and then nothing
      ever updates it, which reads as "search is stale" long after the deploy
      that caused it;
    * an **unscoped model** has no `tenant_id` to put in the document, and a
      document with no tenant is one the injected filter cannot exclude. That
      is the probing oracle this whole app is shaped around not being;
    * a **duplicate or illegal label** is two kinds writing into one index, or
      an index uid Meilisearch refuses on the first write of a fresh checkout.

    Returns what it validated, so a caller that wants both does not walk twice.
    """
    found = declarations() if declarations_ is None else tuple(declarations_)
    seen: dict[str, Searchable] = {}
    for declaration in found:
        _refuse_bad_label(declaration, seen)
        seen[declaration.label] = declaration
        _refuse_unscoped_model(declaration)
        _refuse_bad_fields(declaration)
        _refuse_undeclared_events(declaration)
    return found


def _where(declaration: Searchable) -> str:
    """Which declaration is being complained about, in the words a reader greps.

    The MODEL's app rather than the declaration's, because a `Searchable` is
    discovered out of `apps/<x>/search.py` and the app that owns the model is
    the app that owns the file in every case discovery can produce.
    """
    model = declaration.model
    app_label = getattr(getattr(model, "_meta", None), "app_label", "?")
    name = getattr(model, "__name__", repr(model))
    return f"apps/{app_label}/search.py's Searchable({name}, label={declaration.label!r})"


def _refuse_bad_label(declaration: Searchable, seen: dict[str, Searchable]) -> None:
    label = declaration.label
    if not _LABEL_SAFE.match(label or ""):
        raise ImproperlyConfigured(
            f"{_where(declaration)} declares a label that cannot be an index name: "
            f"{label!r}. A label is lowercase letters, digits, `_` and `-`, starting "
            f"with a letter or a digit — it becomes the tail of the Meilisearch index "
            f"uid (`<prefix>_<label>`) and the value `?kinds=` names on the wire, so an "
            f"illegal one is a 400 from the server at the first write of a fresh "
            f"checkout and a public vocabulary nobody can type."
        )
    if label in seen:
        raise ImproperlyConfigured(
            f"{_where(declaration)} declares the label {label!r}, which "
            f"{_where(seen[label])} already declares. **One label is one index**, so "
            f"two kinds sharing one would interleave two document shapes in one place "
            f"with one settings surface — and each rebuild would silently empty the "
            f"other. A label is the kind: pick a different one."
        )


def _refuse_unscoped_model(declaration: Searchable) -> None:
    meta = getattr(declaration.model, "_meta", None)
    fields = {field.name for field in getattr(meta, "concrete_fields", ())}
    if "tenant" in fields or "tenant_id" in fields:
        return
    raise ImproperlyConfigured(
        f"{_where(declaration)} declares a model that carries no tenant. A searchable "
        f"model is a `TenantScopedModel` or an `OrgScopedModel`, because the document "
        f"stamps `tenant_id` and the injected filter is how one tenant's search stops "
        f"at their own rows. A document with no tenant is one no filter can exclude, "
        f"which is the probing oracle this app exists not to be (ADR search-2)."
    )


def _refuse_bad_fields(declaration: Searchable) -> None:
    if not declaration.fields:
        raise ImproperlyConfigured(
            f"{_where(declaration)} declares no fields. A kind with nothing searchable "
            f"is an index that answers every query with nothing; declare the text a "
            f"person would type, in ranking order."
        )
    for name, weight in declaration.fields:
        if weight not in WEIGHTS:
            raise ImproperlyConfigured(
                f"{_where(declaration)} weights the field {name!r} {weight!r}, which is "
                f"not one of {', '.join(WEIGHTS)}. The letters are Postgres's four "
                f"`setweight` labels — inert on Meilisearch, where declaration ORDER is "
                f"the ranking, and an error from the database on the degradation engine. "
                f"A weight that only breaks once the circuit has opened is a "
                f"weight that breaks on the worst possible day."
            )
        if "." in name or "__" in name:
            raise ImproperlyConfigured(
                f"{_where(declaration)} declares the searchable field {name!r}. A "
                f"searchable field is a CONCRETE column on the model itself, not a walk "
                f"across a relation: the same list builds the `search_vector` generated "
                f"column the degradation engine reads, and a generated column can "
                f"only reference its own table. Denormalise what you want searched onto "
                f"the row, or search the related kind. (`display` may be dotted; this "
                f"is the one that cannot be.)"
            )
        try:
            field = declaration.model._meta.get_field(name)
        except FieldDoesNotExist:
            available = ", ".join(
                sorted(one.name for one in declaration.model._meta.concrete_fields)
            )
            raise ImproperlyConfigured(
                f"{_where(declaration)} declares the searchable field {name!r}, which "
                f"the model does not have. The columns it does have: {available}. A "
                f"kind declared over a field that is not there indexes `None` for it — "
                f"the index exists, the queries run, and nothing is ever found, with no "
                f"error anywhere to say why."
            ) from None
        if not getattr(field, "concrete", False):
            raise ImproperlyConfigured(
                f"{_where(declaration)} declares {name!r}, which is a relation and not "
                f"a column on this table. Searchable fields are text on the row itself "
                f"— see the dotted-path refusal above for the reason."
            )


def _refuse_undeclared_events(declaration: Searchable) -> None:
    installed = {
        config.label for config in django_apps.get_app_configs() if config.name.startswith("apps.")
    }
    for name in declaration.refresh_on:
        app_label = name.split(".")[0] if "." in name else ""
        if app_label not in installed:
            raise ImproperlyConfigured(
                f"{_where(declaration)} refreshes on {name!r}, and no installed app is "
                f"labelled {app_label!r}. An event name is `<app>.<noun>.<past-verb>` "
                f"(house rule 16) and its first segment is the app that publishes it."
            )
        declared = declared_event_names(app_label)
        if name not in declared:
            raise ImproperlyConfigured(
                f"{_where(declaration)} refreshes on {name!r}, which "
                f"apps/{app_label}/events.py does not declare. Import the constant from "
                f"that module instead of writing the string — house rule 16 exists "
                f"because a name that is a literal at one call site and a constant at "
                f"another is a subscription that silently never fires: the reconcile "
                f"builds the first document and then nothing ever refreshes it."
            )


def labels() -> tuple[str, ...]:
    """Every declared kind. What `?kinds=` may name, and the whole of it."""
    return tuple(declaration.label for declaration in declarations())


#: What a caller is told to do about a kind this build does not declare. The
#: `route:` kind names the operation by its `url_name`, so the remedy promises
#: no URL a product may not have and still says "call this one" (ADR core-5)
#: — which is the whole difference between a refusal a stranger can act on
#: and one that only tells them they were wrong.
UNKNOWN_KIND_REMEDIES: tuple[Remedy, ...] = (
    Remedy("List the kinds this product can search", "route:search_kind-list"),
    Remedy("Read the search contract", "docs:openapi"),
)


def catalogue(declarations_: Sequence[Searchable] | None = None) -> tuple[SearchKind, ...]:
    """The public vocabulary: every kind this build declares, and who owns it.

    **Derived, so it cannot rot** — the same argument `events.api.event_catalogue`
    makes about event names, and the same shape: the population is read off the
    installed apps' own `search.py` modules at request time, so the day an app
    declares a kind the catalogue has it and no file here changed.

    It is the same for every tenant on the deployment, deliberately: this is the
    product's vocabulary, not a customer's data. **Which is also what makes
    refusing an unknown kind safe** (`resolve_kinds`, below): a set that any
    member may list is not a set a refusal can leak.

    Sorted by kind, so a page of it is stable between calls and two pages of it
    do not overlap.
    """
    found = declarations() if declarations_ is None else tuple(declarations_)
    return tuple(
        sorted(
            (
                SearchKind(
                    kind=declaration.label,
                    app=str(
                        getattr(getattr(declaration.model, "_meta", None), "app_label", "") or ""
                    ),
                )
                for declaration in found
            ),
            key=lambda entry: entry.kind,
        )
    )


def by_label(label: str) -> Searchable | None:
    """One declaration, or `None`. Never raises: the door decides what a miss is."""
    for declaration in declarations():
        if declaration.label == label:
            return declaration
    return None


def resolve_kinds(requested: Sequence[str] | None) -> tuple[str, ...]:
    """Which kinds a request means. **A name this build does not declare refuses.**

    `None` or empty means every declared kind — the one door serves them all
    (ADR search-2 rejected per-model search routes for exactly this reason).

    **This used to drop an undeclared kind silently**, on the argument that
    saying "`invoices` is not a kind here" tells a caller which kinds exist
    somewhere — the not-there-is-not-yours posture, one level out. A field test
    measured what that bought and what it cost: a stranger sent
    `?kinds=widgets` because the route's own worked example said to, got
    `items: []` eight times over twenty-four seconds, and had **no way to tell
    "no such kind" from "no matches"**. The two answers need different actions
    from them and the product gave one answer to both.

    The argument for dropping died with `GET /search/kinds/`: the vocabulary is
    a published door now, the same for every customer, readable by any member —
    so a refusal that names it leaks nothing that a `GET` did not already hand
    over. What is left is only the cost, and the cost is a caller who cannot
    tell a typo from an empty product.

    **One bad name refuses the whole list** rather than searching the rest.
    Searching what it understood and dropping the remainder is the shape that
    made that invisible in the first place: a `200` with fewer results than were
    asked for, and nothing in it saying which half was ignored.
    """
    declared = labels()
    if not requested:
        return declared
    wanted = [str(kind).strip() for kind in requested if str(kind).strip()]
    if not wanted:
        return declared
    unknown = [kind for kind in wanted if kind not in declared]
    if unknown:
        raise Invalid(
            {"kinds": [_unknown_kind_sentence(unknown, declared)]}, remedies=UNKNOWN_KIND_REMEDIES
        )
    return tuple(label for label in declared if label in wanted)


def _unknown_kind_sentence(unknown: Sequence[str], declared: Sequence[str]) -> str:
    """What the caller is told, in the caller's own field name.

    It names what THEY sent first — a typo is found by seeing it quoted back —
    and then the whole vocabulary, because the whole vocabulary is short, public
    and derived. A build that declares nothing says so rather than printing an
    empty list, which reads as a bug in the refusal rather than as a fact about
    the deployment.
    """
    named = ", ".join(repr(kind) for kind in unknown)
    if declared:
        return (
            f"{named} is not a kind this product can search. The kinds it declares are: "
            f"{', '.join(declared)}. Send one of those in `kinds`, or leave `kinds` out "
            f"to search all of them."
        )
    return (
        f"{named} is not a kind this product can search: this deployment declares no "
        f"searchable kinds at all, so there is nothing `kinds` can name. Leave it out."
    )


def is_org_scoped_kind(declaration: Searchable) -> bool:
    """Whether this kind's rows are organization-scoped, off the model itself.

    Read from the model rather than declared, because a second opinion about
    what a model is, is a second opinion that can be wrong. This is what makes
    the injected filter **per-kind aware**: an org-scoped kind gets
    `tenant_id = t AND org_id IN [...]` and a tenant-scoped one gets
    `tenant_id = t`, and a one-shape-fits-all injection would go org-blind on
    exactly the half that needs it (an earlier lesson, pointed at search).
    """
    return is_org_scoped(declaration.model)


def scope_for(
    *, tenant_id: UUID, org_ids: tuple[UUID, ...], declaration: Searchable
) -> ScopeFilter:
    """The filter one kind is searched under. **Per kind, never one shape for all.**

    It lives here rather than in `selectors.py` because the thing it branches on
    lives here: whether a kind is organization-scoped is read off the model, and
    the filter shape and the index's `filterableAttributes` have to agree — an
    index that cannot filter on `org_id` and a filter that names it are the same
    bug seen from two sides.

    `org_ids` is dropped on a tenant-scoped kind rather than passed and ignored:
    the engine receives `None`, which says "this kind carries no organization",
    and the empty tuple keeps its own separate meaning of "the hat resolved to
    nothing".
    """
    if is_org_scoped_kind(declaration):
        return ScopeFilter(tenant_id=tenant_id, org_ids=org_ids)
    return ScopeFilter(tenant_id=tenant_id, org_ids=None)


def filterable_attributes(declaration: Searchable) -> tuple[str, ...]:
    """The attributes the engine may filter on. Ids only, and never a path."""
    if is_org_scoped_kind(declaration):
        return (TENANT_ATTRIBUTE, ORG_ATTRIBUTE)
    return (TENANT_ATTRIBUTE,)


def searchable_attributes(declaration: Searchable) -> tuple[str, ...]:
    """The text attributes, in declaration order. **Order is the ranking.**"""
    return tuple(name for name, _weight in declaration.fields)


def index_settings(declaration: Searchable) -> dict[str, Any]:
    """The settings an index must have to serve this declaration.

    Returned as data rather than applied here, for the reason rule 33 exists:
    this module knows what an index should be, `engine.py` is the only module
    that may say so to Meilisearch. It is also what makes "settings are code"
    checkable — the same value is digested, applied and compared.
    """
    scope_columns = [TENANT_ATTRIBUTE]
    if is_org_scoped_kind(declaration):
        scope_columns.append(ORG_ATTRIBUTE)
    return {
        "searchableAttributes": list(searchable_attributes(declaration)),
        "filterableAttributes": list(filterable_attributes(declaration)),
        "displayedAttributes": ["id", "label", *scope_columns, *searchable_attributes(declaration)],
    }


def declaration_digest(declaration: Searchable) -> str:
    """The fingerprint of everything a rebuild would materialize. Stable, sorted.

    `json.dumps` with `sort_keys` and no whitespace, so the digest is a property
    of the declaration and not of how this file happens to be written today —
    a digest that moved when somebody reformatted a dict would rebuild every
    index on a whitespace change.

    The field list keeps its ORDER inside the digest (it is the ranking) while
    the surrounding keys are sorted, which is the one place order matters and
    the one place it is preserved.
    """
    payload = {
        "version": DIGEST_VERSION,
        "label": declaration.label,
        "fields": [[name, weight] for name, weight in declaration.fields],
        "display": declaration.display,
        "settings": index_settings(declaration),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
