"""The noun-verb family's one seam: the marker walk, the hook walk, and the roads.

Every verb the family ships — archive and restore first, then move, bulk,
history, duplicate, merge, import and attach — is the same three moves over a
noun a product declared:

* **A declaration on the model** — a class attribute read off the registry, the
  way `append_only`, `inherited_downward` and `derive_org_from` already are.
  `declared_models(attr)` is that walk, once.
* **A hook a child app drops beside itself** — a conventionally named module
  (`archive_blockers.py`, `merge_repointers.py`, …) exporting one dict. The
  parent asks core; core walks every installed app; no parent imports a child
  (A2/A3). `core.discovery.declared(module, attribute)` is that walk, once —
  the walk `core.authz` does for `policies.py` and `roles.py` too, so the
  family and the vocabulary share one (principle 13).
* **A road the noun's doors must carry** — `ROADS`, the table house rule 74
  reads: which routes a marker demands, by `url_name`.

**The hook modules are a CLOSED tuple** (`HOOK_MODULES`). A walk is only ever
asked for a name in it, so a module an app happens to call `frobnicate_blockers`
is never imported by anything here, and a new hook kind is a visible edit to
this file rather than a string somebody typed at a call site (§ I: closed
populations from declarations).

A hook module a product writes under a name OUTSIDE the tuple is never walked
here — and it is not silent: `HOOK_MODULES` is also what house rule 11's
canonical-module census admits (`apps/core/checks.py`, `CANONICAL_MODULES`),
so `apps/<x>/frobnicate_blockers.py` is refused at boot as a module the app
shape does not recognise (djb.E011), naming the file.

DOES NOT COVER — declared: a marker set on a model after the class body
(`Model.archivable = True` at runtime), which the registry walk sees and the
source rules do not.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.apps import AppConfig
from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured
from django.db import models

# The walk lives in `core.discovery`; the family's readers (and every app that
# imported it from here) reach it through this name.
from apps.core.discovery import declared as declared
from apps.core.lexicon import UNCOUNTABLE as lexicon_uncountable
from apps.core.lexicon import inflected
from apps.core.roads import road
from apps.core.schemas import SHOW_WORDS

#: Every hook module the family walks, and nothing else. Each is a per-app file
#: exporting ONE dict; which attribute is the caller's (`BLOCKERS`,
#: `REPOINTERS`, `IMPORTERS`). The order is the order the verbs landed.
HOOK_MODULES: tuple[str, ...] = (
    "archive_blockers",
    "restore_blockers",
    "move_blockers",
    "merge_blockers",
    "merge_repointers",
    "importers",
)

#: The attribute each hook module exports. One name per module, so the digest
#: can serialize a population without being told which attribute to read.
HOOK_ATTRIBUTES: Mapping[str, str] = {
    "archive_blockers": "BLOCKERS",
    "restore_blockers": "BLOCKERS",
    "move_blockers": "BLOCKERS",
    "merge_blockers": "BLOCKERS",
    "merge_repointers": "REPOINTERS",
    "importers": "IMPORTERS",
}


def hook(module: str) -> list[tuple[AppConfig, dict[Any, Any]]]:
    """A family hook's declarations — `declared` over a name IN the closed tuple.

    A name outside `HOOK_MODULES` is `ValueError` before anything is imported:
    the tuple is the population, and a caller cannot widen it by spelling.
    """
    if module not in HOOK_MODULES:
        raise ValueError(
            f"{module!r} is not a family hook module; the walk reads only "
            f"{', '.join(HOOK_MODULES)} (apps.core.verbs.HOOK_MODULES)."
        )
    return declared(module, HOOK_ATTRIBUTES[module], refuse_shape=True)


def declared_hooks() -> dict[str, list[str]]:
    """Per app label, the hook modules it declares — names only, sorted.

    The partition digest's `verbs` section: a product app that drops an
    `archive_blockers.py` changes which platform tests could answer
    differently, so the population is part of the skip key.
    """
    by_app: dict[str, list[str]] = {}
    for module in HOOK_MODULES:
        for config, _ in hook(module):
            by_app.setdefault(config.label, []).append(module)
    return {label: sorted(modules) for label, modules in sorted(by_app.items())}


def declared_models(attr: str, *, registry: Any = None) -> list[type[models.Model]]:
    """Every model in the product whose class declares `attr` truthy. **Discovered.**

    The marker walk: `archivable`, and — as the family lands — `movable`,
    `versioned`, `mergeable`, `duplicable`. An attribute lookup, as
    `is_append_only` is: the declaration is the fact and it is inherited, so a
    subclass that meant otherwise says `<attr> = False` in its own body.
    `registry` is an app registry to ask instead of the global one — a test's
    `isolate_apps` registry, which is how `core` proves the walk against a
    planted model.
    """
    source = registry if registry is not None else django_apps
    return [model for model in source.get_models() if getattr(model, attr, False)]


def door_url_name(model: type[Any] | None, verb: str, noun: str) -> str:
    """The door that serves `verb` on `noun`: its `act_doors` entry, else `<noun>-<verb>`.

    A noun whose door for a verb is mounted under another name declares it on
    the class — `act_doors = {"<verb>": "<url_name>"}` (files' `replace` is
    `version-add`) — and this is the one reader of that declaration: house
    rule 74 demands the door it names, and `allowed_acts` offers the act where
    it is mounted, so the two can never disagree about which door serves an
    act. `model` is `None` where no class exists yet to declare anything (a
    copy's noun before its model is written), and the derived name answers.
    """
    declared: dict[str, str] = dict(getattr(model, "act_doors", {}) or {})
    return declared.get(verb) or f"{noun}-{verb}"


@road("family_doors", example="apps/example/models.py::Widget")
@dataclass(frozen=True, slots=True)
class Road:
    """What one marker demands of a noun's doors (house rule 74).

    `routes` are the `url_name`s the noun's REST door must carry: a bare verb
    means the door `door_url_name` answers for it — `<noun>-<verb>`, or the one
    the noun declares in `act_doors` — and an entry holding `{noun}` is a
    template used as written (`{noun}_history-list`). Each is paired on the machine door by rule
    17's derivation. `grants` are the verbs the marker adds to the kind's
    vocabulary (`<kind>.<verb>`, derived by `core.authz.family_verbs`) — a road
    whose routes run other verbs (bulk) or only read (history) grants nothing.
    `settled` answers "is this verb already done to this row" for the idempotent
    early return and the bulk contract's `unchanged`.

    `marker` is the class attribute a model declares truthy; `ANY_MARKER` means
    "any other road's marker" — the history road, which every family noun owes.
    """

    marker: str
    routes: tuple[str, ...]
    settled: Mapping[str, Callable[[Any], bool]]
    grants: tuple[str, ...] = ()

    def url_names(self, noun: str, model: type[Any] | None = None) -> tuple[str, ...]:
        """The `url_name`s this road demands of `noun`, in road order, read through `model`."""
        return tuple(
            route.format(noun=noun) if "{noun}" in route else door_url_name(model, route, noun)
            for route in self.routes
        )


@road("show", example="apps/core/tests/test_tool_names.py::test_shown_cuts_the_book")
def shown(queryset: Any, show: str) -> Any:
    """The cut of an archivable book `show` names — `live`, `archived` or `all` — else `invalid`.

    Applied AFTER `for_tenant(...).visible_to(...)`: both widenings only take
    `for_tenant()`'s live exclusion back out, so the tenant and the hat narrow
    the archived cut exactly as they narrow the live one. An unknown word is
    refused naming `show`, never read as `live` — a mistyped `?show=archvied`
    answering the live book is a list that looks right and is not.
    """
    from apps.core.exceptions import Invalid

    if show not in SHOW_WORDS:
        raise Invalid({"show": [f"Show one of: {', '.join(SHOW_WORDS)}."]})
    if show == "archived":
        return queryset.archived_only()
    if show == "all":
        return queryset.including_archived()
    return queryset


def _is_archived(row: Any) -> bool:
    return getattr(row, "archived_at", None) is not None


def _is_live(row: Any) -> bool:
    return getattr(row, "archived_at", None) is None


#: The history road's marker: a noun declaring ANY other road's marker owes it.
ANY_MARKER = "*"

#: The markers that do NOT, alone, owe the history road. An archive-only noun
#: reads its archive on its own row (`archived_at`, `archived_by`), and the
#: archive road landed on nouns before history existed; the first OTHER family
#: verb a noun adopts brings the history card with it.
HISTORY_NOT_OWED_FOR: frozenset[str] = frozenset({"archivable"})

#: The roads, by family verb. House rule 74 reads this table and nothing else:
#: a marker a model declares demands exactly the routes its road lists, and the
#: vocabulary derives exactly the verbs its road grants.
ROADS: Mapping[str, Road] = {
    "archive": Road(
        marker="archivable",
        routes=("archive", "restore"),
        settled={"archive": _is_archived, "restore": _is_live},
        grants=("archive", "restore"),
    ),
    # A `Versioned` noun's update route carries `version` REQUIRED in its body
    # and in its answer (rule 74's update clause reads the schemas).
    "version": Road(marker="versioned", routes=("update",), settled={}),
    "move": Road(marker="movable", routes=("move",), settled={}, grants=("move",)),
    # Bulk runs the noun's OWN verbs per item, so it grants nothing; every verb
    # a noun lists in `bulk_verbs` must have its single road too.
    "bulk": Road(marker="bulk_verbs", routes=("bulk",), settled={}),
    "history": Road(marker=ANY_MARKER, routes=("{noun}_history-list",), settled={}),
    # A merge's apply and its dry run (`GET /<nouns>/{id}/merge/?into=`), and
    # the `<kind>.merge` key both ends are asked.
    "merge": Road(
        marker="mergeable",
        routes=("merge", "{noun}_merge-detail"),
        settled={},
        grants=("merge",),
    ),
    # A duplicate IS a create (`<kind>.create` at the hat), so it grants
    # no key of its own; `allowed_acts` offers it where the door exists.
    "duplicate": Road(marker="duplicable", routes=("duplicate",), settled={}),
}


def road_population(road: Road, *, registry: Any = None) -> list[type[models.Model]]:
    """The models a road binds: its marker's declarers, or every family noun."""
    if road.marker != ANY_MARKER:
        return declared_models(road.marker, registry=registry)
    found: list[type[models.Model]] = []
    for other in ROADS.values():
        if other.marker == ANY_MARKER or other.marker in HISTORY_NOT_OWED_FOR:
            continue
        found.extend(m for m in declared_models(other.marker, registry=registry) if m not in found)
    return found


# --- archive and restore: the row half every noun's service pair calls ---------
#
# The per-noun `@service` owns the transaction, the authorization and the event
# (A3: the write stays in the noun's app, and `core` sits below `events` so it
# cannot emit). What every pair shares is below: the lock, the idempotent early
# return, the blocker walk and the two columns — so an adopting noun's service
# is the same eight lines whatever the noun is.


def _require_archivable(model: type[models.Model]) -> None:
    from apps.core.models import is_archivable

    if not is_archivable(model):
        raise TypeError(
            f"{model.__name__} has not declared `Archivable`; there is nothing to archive. "
            "A noun joins the archive by declaring the mixin (apps.core.models.Archivable)."
        )


def _every_row(model: type[models.Model], tenant: Any) -> Any:
    """`for_tenant(tenant)`, widened to archived rows when the model has them."""
    from apps.core.models import is_archivable

    read = model.objects.for_tenant(tenant)  # type: ignore[attr-defined]
    return read.including_archived() if is_archivable(model) else read


def _locked(tenant: Any, row: Any) -> Any:
    """The row, re-read under `SELECT … FOR UPDATE`, archived or not (E8)."""
    return _every_row(type(row), tenant).select_for_update().get(pk=row.pk)


@road("archive", example="apps/example/services.py::archive_widget")
def archive_row(*, tenant: Any, actor: Any, row: Any, noun: str) -> tuple[Any, bool]:
    """Take `row` out of the book; `restore_row` is its pair. `(row, whether this call changed it)`.

        @service
        def archive_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
            if not may_be_named(actor, widget):
                raise NotFound()
            require(actor, "widget.archive", widget)
            widget, changed = archive_row(tenant=tenant, actor=actor, row=widget, noun="widget")
            if changed:
                emit(name=WIDGET_ARCHIVED, tenant=tenant, payload=..., actor=actor)
            return widget

    **Called inside the noun's service's transaction** (`@service` opens it):
    the row is re-read under a row lock, so two presses serialize. **Idempotent**
    (principle 16): a row already archived is returned unchanged with
    `changed=False`, keeping the FIRST press's date and archiver — the second
    press emits nothing. Otherwise every child app's `archive_blockers.py` is
    asked (`core.blockers`), and any live child is `ArchiveBlocked` naming
    every blocker — nothing written, nothing cascaded. `archived_by` is the
    acting person, or `NULL` when the product acts for itself.
    """
    from apps.core.blockers import blockers_for
    from apps.core.exceptions import ArchiveBlocked
    from apps.core.time import now

    _require_archivable(type(row))
    locked = _locked(tenant, row)
    if locked.archived_at is not None:
        return locked, False
    held = blockers_for("archive", noun, tenant=tenant, obj=locked)
    if held:
        raise ArchiveBlocked(noun=noun, blocking=held)
    locked.archived_at = now()
    locked.archived_by = _person(actor)
    locked.save(update_fields=["archived_at", "archived_by", "updated_at"])
    return locked, True


def restore_row(*, tenant: Any, actor: Any, row: Any, noun: str) -> tuple[Any, bool]:
    """Put `row` back in the book. `(the row, whether this call changed it)`.

    The mirror of `archive_row`: locked, idempotent (a live row is returned
    unchanged), `restore_blockers.py` asked and `RestoreBlocked` raised over
    whatever holds it, both columns cleared — a live row carries neither. A
    merged loser refuses `merged`: it is archived as a tombstone, and a restore
    would put a second copy of its survivor back in the book.
    """
    from apps.core.blockers import blockers_for
    from apps.core.exceptions import RestoreBlocked

    _require_archivable(type(row))
    locked = _locked(tenant, row)
    if locked.archived_at is None:
        return locked, False
    _refuse_merged(locked, noun=noun)
    held = blockers_for("restore", noun, tenant=tenant, obj=locked)
    if held:
        raise RestoreBlocked(noun=noun, blocking=held)
    locked.archived_at = None
    locked.archived_by = None
    locked.save(update_fields=["archived_at", "archived_by", "updated_at"])
    return locked, True


def require_live(row: Any, *, noun: str) -> None:
    """Refuse a write on an archived row with `archived`, naming the noun's restore.

    An archived row's READS answer (read-only); every write other than its
    restore calls this first. A row of a model that is not archivable is always
    live. A MERGED loser (`Mergeable.merged_into` set) refuses `merged` instead,
    naming its survivor — it is archived too, and restoring it is not the way
    back (there is no unmerge).
    """
    from apps.core.exceptions import Archived

    _refuse_merged(row, noun=noun)
    if getattr(row, "archived_at", None) is not None:
        raise Archived(noun=noun)


def require_no_merged_losers(row: Any, *, noun: str) -> None:
    """Refuse deleting a merge's SURVIVOR with `merge_survivor`, naming the noun's archive.

    Earlier losers' tombstones name the survivor (`merged_into`, PROTECT), so a
    delete would fail in the database as a generic `conflict` saying something
    that did not happen. The noun's delete service calls this first; a row of a
    model that is not mergeable, or a survivor of nothing, passes.
    """
    from apps.core.exceptions import MergeSurvivor
    from apps.core.models import is_mergeable

    model = type(row)
    if not is_mergeable(model):
        return
    # rule-24: an existence probe by primary key over the tenant's losers of a
    # row the caller already reached — the delete's own reach is the authority.
    if _every_row(model, row.tenant).filter(merged_into=row).exists():
        raise MergeSurvivor(noun=noun)


def _refuse_merged(row: Any, *, noun: str) -> None:
    """`merged`, naming the survivor, when `row` is a merged-away loser.

    Its own helper because only a `Mergeable` noun can ever answer it: house
    rule 41's reach reads the codes a `core.verbs` function raises IN ITS OWN
    BODY, so `require_live` and `restore_row` publish `archived` and
    `restore_blocked` to every adopter, and `merged` stays a Mergeable noun's
    route's own declaration (`@also_refuses("merged")`) — declared in rule 41's
    blind spot, never guessed onto every archivable noun's document.
    """
    from apps.core.exceptions import Merged

    merged_into = getattr(row, "merged_into_id", None)
    if merged_into is not None:
        raise Merged(noun=noun, merged_into=merged_into)


def _person(actor: Any) -> Any:
    """The acting person, or `None` when the product acts for itself."""
    user = getattr(actor, "user", None)
    return user if getattr(user, "pk", None) is not None else None


# --- move: the row half every noun's `move_<noun>` calls ---------------------------


def derived_children(model: type[models.Model]) -> list[tuple[type[models.Model], str]]:
    """`(child model, fk name)` for every model whose `derive_org_from` names `model`.

    **Discovered**: the rows that take their organization from this one say so
    with `derive_org_from` (`core.models.OrgScopedModel`'s landing gate), so the
    set a move must carry along is the registry's, never a list.
    """
    found: list[tuple[type[models.Model], str]] = []
    for candidate in model._meta.apps.get_models():
        declared = getattr(candidate, "derive_org_from", None)
        if not declared:
            continue
        field = candidate._meta.get_field(declared)
        target = getattr(field, "related_model", None)
        if isinstance(target, type) and issubclass(model, target):
            found.append((candidate, declared))
    return found


def _move_plan(
    model: type[models.Model], pks: list[Any], tenant: Any
) -> tuple[list[tuple[type[models.Model], list[Any]]], list[Any]]:
    """(the mutable rows to carry along, by model; the append-only blockers).

    Walked down the derivation to its leaves before anything is written, so a
    ledger three levels down refuses the move with nothing moved.
    """
    from apps.core import authz
    from apps.core.exceptions import Blocker
    from apps.core.models import is_append_only

    carry: list[tuple[type[models.Model], list[Any]]] = []
    blocked: list[Blocker] = []
    for child, fk in derived_children(model):
        rows = _every_row(child, tenant).filter(**{f"{fk}__in": pks})
        if is_append_only(child):
            if rows.exists():
                kind = authz.kind_of(child) or child._meta.model_name or "row"
                plural = str(child._meta.verbose_name_plural)
                blocked.append(
                    Blocker(
                        noun=kind,
                        door=_list_door(kind, fk, pks[0]),
                        label=(
                            f"Its {plural} are recorded where they were written and "
                            "cannot move with it"
                        ),
                    )
                )
            continue
        child_pks = list(rows.values_list("pk", flat=True))
        if not child_pks:
            continue
        carry.append((child, child_pks))
        deeper, deeper_blocked = _move_plan(child, child_pks, tenant)
        carry.extend(deeper)
        blocked.extend(deeper_blocked)
    return carry, blocked


# --- One name per capability: the url_name's two halves, its plural, its tool ---
#
# A capability has ONE name, its `url_name` (`<noun>-<verb>`), and everything else
# that names it is derived: the noun and the verb (`split_url_name`), the noun's
# plural (`plural`), and the machine door's tool (`derive_tool_name`). Before
# these, rule 17, rule 41, the document writer and the blocker's list door each
# split and pluralised for themselves — two splitters disagreeing on six names
# (`sso-connection-list` is `sso-connection` + `list`, not `sso` + …) and four
# pluralisers. ADR api-2: "url_names do not move — rule 17 derives the expected
# MCP tool names from them"; this is that derivation.


class UnderivableName(ValueError):
    """A `url_name` this grammar cannot split, so no tool name can be derived from it."""


#: A verb is one lowercase word — `<noun>-<verb>`'s right half never carries a
#: hyphen, which is what makes the LAST hyphen the split.
_VERB = re.compile(r"^[a-z][a-z0-9_]*$")


@road("url_name_split", example="apps/core/checks.py::check_door_parity")
def split_url_name(url_name: str) -> tuple[str, str]:
    """`(noun, verb)` — split at the LAST hyphen: a noun may carry hyphens, a verb never does."""
    name = url_name.removeprefix("api:")
    noun, separator, verb = name.rpartition("-")
    if not separator or not noun or not _VERB.match(verb):
        raise UnderivableName(
            f"{url_name!r} is not `<noun>-<verb>` — a capability's url_name names the thing "
            "and then, after its last hyphen, the one word done to it"
        )
    return noun, verb


#: Words with no plural of their own (`apps.core.lexicon` holds them beside the inflection).
UNCOUNTABLE: frozenset[str] = lexicon_uncountable


@road("pluralize", example="apps/core/verbs.py::_list_door")
def plural(noun: str) -> str:
    """The plural of a noun — the ONE answer: `-ies`, `-es` after a hiss, else `-s`; a plural stays.

    Only the last `_`-segment is inflected (`widget_entry` → `widget_entries`).
    A word in `UNCOUNTABLE` is its own plural, and so is a word that already
    reads as one (`apps.core.lexicon.looks_plural` — `dead_letters` stays,
    `status` and `address` do not), which is what lets a list's url_name name
    its noun in either number and still derive one tool name.
    """
    return inflected(noun)


#: How a CRUD verb's tool is named, by the url_name's verb; every other verb — a
#: family verb (`archive`, `move`, `merge`, `duplicate`, `restore`) or a noun's
#: own (`approve`, `issue`) — is `<verb>_<noun>`. `{plural}` is `plural(noun)`,
#: which leaves a noun the url_name already names in the plural as written
#: (`dead_letters-list`). Rule 17 re-derives every bound pair against this table
#: (`apps/core/tests/test_tool_names.py`), which is what makes it legal to type.
TOOL_FORMS: Mapping[str, str] = {
    "list": "list_{plural}",
    "detail": "get_{noun}",
    "create": "create_{noun}",
    "update": "update_{noun}",
    "delete": "delete_{noun}",
    # The bulk road's one door acts on a selection, so its tool is plural.
    "bulk": "bulk_{plural}",
}


@road(
    "tool_name",
    example="apps/core/tests/test_tool_names.py::test_every_tool_name_is_the_derivation",
)
def derive_tool_name(url_name: str) -> str:
    """The MCP tool a capability's `url_name` names — the one name its twin carries."""
    noun, verb = split_url_name(url_name)
    noun = noun.replace("-", "_")
    form = TOOL_FORMS.get(verb, "{verb}_{noun}")
    return form.format(noun=noun, plural=plural(noun), verb=verb)


def _list_forms(kind: str) -> list[str]:
    """The `url_name`s a kind's list may carry, in the order tried: the kind, then its plural."""
    return [f"{form}-list" for form in dict.fromkeys((kind, plural(kind)))]


def mounted_operations() -> dict[str, Any]:
    """`{url_name: ninja operation}` over every operation the API mounts.

    Read through `apps.core.api.mount.bound_operations`, the one mount reader
    (imported inside the call — it imports `config.api` lazily, and this module
    is imported while the registry populates). Not cached: a blocker is a rare
    answer, and the mount is a module-level object.
    """
    from apps.core.api.mount import bound_operations

    return {name: operation for _path, name, operation in bound_operations() if name}


def _list_door(kind: str, fk: str, parent_pk: Any) -> str:
    """The blocking child's list door, **read off the mount** — never composed.

    The first of the kind's list forms that is mounted (`widget_entries-list`),
    narrowed by the parameter that list actually declares for the parent —
    `?<fk>_id=` or `?<fk>=`, whichever it takes. A kind with no mounted list is
    named without a query (`route:<kind>-list`): the door says which list to
    look in, and a reader with no such list has no narrower one to be sent to.
    """
    operations = mounted_operations()
    for name in _list_forms(kind):
        operation = operations.get(name)
        if operation is None:
            continue
        # The `takes_query` road: imported here, inside the call, because
        # `apps.core.api` pulls in the routes and this module loads under them.
        from apps.core.api.query import offers_query

        for parameter in (f"{fk}_id", fk):
            if offers_query(operation, parameter):
                return f"route:{name}?{parameter}={parent_pk}"
        return f"route:{name}"
    return f"route:{kind}-list"


@road("move", example="apps/example/services.py::move_widget")
def rehome(
    row: Any,
    organization: Any,
    *,
    owner: Any = None,
    noun: str | None = None,
) -> tuple[Any, bool]:
    """Move `row` to `organization` (and hand it to `owner`). `(the row, changed)`.

        @service
        def move_widget(*, tenant, actor, widget, organization, version):
            ...reach both ends, require "widget.move" at both...
            widget, changed = rehome(widget, organization)
            if changed:
                emit(name=WIDGET_MOVED, ...)

    **Called inside the noun's service's transaction.** The row is re-read
    under a row lock. **Idempotent** (principle 16): already there (and already
    that owner's) → the row unchanged, `changed=False`. Otherwise every MUTABLE
    row that derives its organization from it — and theirs, to the leaves —
    moves with it, in the same transaction; an APPEND-ONLY derived row with any
    row present is `MoveBlocked` naming it, and so is anything a child app's
    `move_blockers.py` answers — refused before anything is written, so nothing
    moves. A destination in another tenant is `NotFound` (the service's reach
    check is the first line of defence; this is the belt).

    The owner axis moves only when the noun declares `move_owner_field` and
    `owner` is given; an `owner` named for a noun that declares none is
    `invalid` naming `owner_id` — refused, never silently ignored. Every write
    names `updated_at`, so a `Versioned` row and its children all take a new
    version (house rule 76).
    """
    from apps.core import authz
    from apps.core.blockers import blockers_for
    from apps.core.exceptions import Invalid, MoveBlocked, NotFound
    from apps.core.time import now

    model = type(row)
    if not getattr(model, "movable", False):
        raise TypeError(
            f"{model.__name__} has not declared `Movable`; a noun joins the move verb by "
            "declaring the mixin (apps.core.models.Movable)."
        )
    tenant = row.tenant
    if getattr(organization, "tenant_id", None) != row.tenant_id:
        raise NotFound()
    noun = noun or authz.kind_of(model) or model._meta.model_name or "row"
    owner_field: str | None = getattr(model, "move_owner_field", None)
    if owner is not None and owner_field is None:
        # Never silently ignored: a caller that named an owner believes it was
        # handed over, and a 200 with the owner unchanged is the lie.
        raise Invalid(
            {"owner_id": [f"A {noun} has no owner to hand over; move it without naming one."]}
        )
    locked = _locked(tenant, row)
    moves_node = locked.organization_id != organization.pk
    moves_owner = (
        owner_field is not None
        and owner is not None
        and getattr(locked, f"{owner_field}_id", None) != owner.pk
    )
    if not moves_node and not moves_owner:
        return locked, False
    carry: list[tuple[type[models.Model], list[Any]]] = []
    if moves_node:
        carry, held = _move_plan(model, [locked.pk], tenant)
        held = [*held, *blockers_for("move", noun, tenant=tenant, obj=locked)]
        if held:
            raise MoveBlocked(noun=noun, blocking=held)
    stamp = now()
    fields = ["updated_at"]
    if moves_node:
        locked.organization = organization
        fields.append("organization")
        for child, pks in carry:
            _every_row(child, tenant).filter(pk__in=pks).update(
                organization=organization, updated_at=stamp
            )
    if moves_owner and owner_field is not None:
        setattr(locked, owner_field, owner)
        fields.append(owner_field)
    locked.save(update_fields=fields)
    return locked, True


# --- merge: the row half every noun's `merge_<noun>` calls -------------------------


@dataclass(frozen=True, slots=True)
class Repointed:
    """One repointer's answer to a merge: its title and the rows that LEFT the loser."""

    title: str
    left: int


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    """What `merge_rows` did: the survivor, the loser, whether it changed, what left."""

    survivor: Any
    loser: Any
    changed: bool
    repoints: tuple[Repointed, ...] = ()


def repointers_for(noun: str) -> list[tuple[str, Repointer]]:
    """`(declaring app label, repointer)` for `noun`: every `"*"` entry, then the noun's own.

    **Discovered** through the closed hook tuple (`merge_repointers`). An entry
    that is not a `Repointer` is `ImproperlyConfigured` naming the file — a
    repointer that quietly counted for nothing is a merge that leaves rows on a
    tombstone.
    """
    found: list[tuple[str, Repointer]] = []
    for key in ("*", noun):
        for config, repointers in hook("merge_repointers"):
            entry = repointers.get(key)
            if entry is None:
                continue
            if not isinstance(entry, Repointer):
                raise ImproperlyConfigured(
                    f"apps/{config.label}/merge_repointers.py: `REPOINTERS[{key!r}]` is "
                    f"{type(entry).__name__}, not a core.verbs.Repointer."
                )
            found.append((config.label, entry))
    return found


def merge_counts(*, tenant: Any, loser: Any, noun: str) -> tuple[Repointed, ...]:
    """The dry run: per repointer, how many rows WOULD leave the loser. Read-only."""
    return tuple(
        Repointed(title=repointer.title, left=int(repointer.count(tenant=tenant, loser=loser)))
        for _label, repointer in repointers_for(noun)
    )


@road("merge", example="apps/example/services.py::merge_widget")
def merge_rows(*, tenant: Any, actor: Any, loser: Any, into: Any, noun: str) -> MergeOutcome:
    """Fold `loser` into `into` (the survivor). **Called inside the noun's service's transaction.**

        @service
        def merge_widget(*, tenant, actor, widget, into, version=None, into_version=None):
            ...reach both, require "widget.merge" on both, versions on both...
            outcome = merge_rows(tenant=tenant, actor=actor, loser=widget, into=into,
                                 noun="widget")
            if outcome.changed:
                emit(name=WIDGET_MERGED, ...)  # repoints from outcome.repoints

    Both rows are re-read under a row lock **in pk order** (two merges of one
    pair in opposite directions cannot deadlock). Then, in order:

    * the SAME row, or two different nouns → `invalid` naming `into`;
    * the loser ALREADY merged into this survivor → unchanged (`changed=False`,
      principle 16: a retried press converges); merged into another → `merged`;
    * a survivor (or loser) that is archived → `archived` (restore it first);
      one that is itself merged away → `merged`, naming where it went;
    * a child app's `merge_blockers.py` → `merge_blocked`, nothing written;
    * every repointer for the noun (`repointers_for`) re-points ITS rows through
      its own service, and answers what left (`Repointed`);
    * every earlier loser merged into THIS loser is re-pointed at the survivor
      (a chain is never two hops);
    * the loser is archived (`archived_by` the acting person) with
      `merged_into` naming the survivor. Every write names `updated_at`.

    The per-noun service owns the authorization, the versions and the event
    (`core` sits below `events`).
    """
    from apps.core.blockers import blockers_for
    from apps.core.exceptions import Archived, Invalid, MergeBlocked, Merged
    from apps.core.models import is_mergeable
    from apps.core.time import now

    model = type(loser)
    if not is_mergeable(model):
        raise TypeError(
            f"{model.__name__} has not declared `Mergeable`; a noun joins the merge verb by "
            "declaring the mixin (apps.core.models.Mergeable)."
        )
    if type(into) is not model:
        raise Invalid({"into": ["A merge joins two records of one kind."]})
    if loser.pk == into.pk:
        raise Invalid({"into": ["A record cannot be merged into itself."]})
    locked = {row.pk: _locked(tenant, row) for row in sorted((loser, into), key=_pk_order)}
    gone, kept = locked[loser.pk], locked[into.pk]
    if gone.merged_into_id == kept.pk:
        return MergeOutcome(survivor=kept, loser=gone, changed=False)
    for row in (gone, kept):
        if row.merged_into_id is not None:
            raise Merged(noun=noun, merged_into=row.merged_into_id)
        if row.archived_at is not None:
            raise Archived(noun=noun)
    held = blockers_for("merge", noun, tenant=tenant, obj=gone)
    if held:
        raise MergeBlocked(noun=noun, blocking=held)
    repoints = tuple(
        Repointed(
            title=repointer.title,
            left=int(repointer.repoint(tenant=tenant, actor=actor, loser=gone, survivor=kept)),
        )
        for _label, repointer in repointers_for(noun)
    )
    stamp = now()
    _every_row(model, tenant).filter(merged_into=gone).update(merged_into=kept, updated_at=stamp)
    gone.archived_at = stamp
    gone.archived_by = _person(actor)
    gone.merged_into = kept
    gone.save(update_fields=["archived_at", "archived_by", "merged_into", "updated_at"])
    return MergeOutcome(survivor=kept, loser=gone, changed=True, repoints=repoints)


def _pk_order(row: Any) -> str:
    return str(row.pk)


# --- duplicate: the row half every noun's `duplicate_<noun>` calls -----------------

#: The columns the family and the platform own on every noun — never a
#: duplicate's `copies` or `resets` question: identity, tenancy, placement,
#: time, and the archive, merge and duplicate markers' own columns.
DUPLICATE_PLATFORM_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "tenant",
        "organization",
        "created_at",
        "updated_at",
        "archived_at",
        "archived_by",
        "merged_into",
        "duplicated_from",
        "duplicate_key",
    }
)


def duplicate_fields(model: type[models.Model]) -> list[str]:
    """The noun's concrete editable fields a `Duplicate` declaration must classify.

    Every concrete field except the platform keys and generated columns — the
    closed population house rule 74's duplicate clause asks about.
    """
    found: list[str] = []
    for field in model._meta.concrete_fields:
        if field.name in DUPLICATE_PLATFORM_FIELDS or getattr(field, "generated", False):
            continue
        if not getattr(field, "editable", True):
            continue
        found.append(field.name)
    return found


def owned_children(model: type[models.Model]) -> dict[str, Any]:
    """`{reverse accessor: relation}` for every one-to-many child that CASCADEs from `model`."""
    found: dict[str, Any] = {}
    for relation in model._meta.related_objects:
        if not relation.one_to_many or relation.on_delete is not models.CASCADE:
            continue
        accessor = relation.get_accessor_name()
        if accessor:
            found[accessor] = relation
    return found


@road("duplicate", example="apps/example/services.py::duplicate_widget")
def duplicate_row(
    *,
    tenant: Any,
    row: Any,
    organization: Any = None,
    idempotency_key: str = "",
    fill: Mapping[str, Any] | None = None,
) -> tuple[Any, bool]:
    """Save `row` as a new row of its noun. `(the copy, whether this call made it)`.

        @service
        def duplicate_widget(*, tenant, actor, widget, idempotency_key=""):
            ...reach the source, require "widget.create" at the hat...
            copy, created = duplicate_row(tenant=tenant, row=widget,
                                          organization=actor.org,
                                          idempotency_key=idempotency_key,
                                          fill={"owner": actor.user,
                                                "name": f"Copy of {widget.name}"})
            if created:
                emit(name=WIDGET_DUPLICATED, ...)

    **Called inside the noun's service's transaction.** The noun's
    `duplicate = Duplicate(copies=…, resets=…)` decides: every field in
    `copies` is carried across; every field in `resets` is left at the model's
    default; the platform keys are the copy's own — a new id, the source's
    tenant, the HAT's organization for an org-scoped noun (a duplicate
    is a create, ADR core-20), live, `duplicated_from` the source.

    **`fill` is what the noun's service decides for a reset field**, set on
    the copy BEFORE its one save: the owner is the person who pressed, the name
    is the product's "copy" word. Every key must be named in `resets` — a
    copied field is the source's, and a field the declaration does not classify
    is not the service's to set — or it is `TypeError`. A reset field left
    unfilled takes the model's default, which a NOT NULL field without one does
    not have.

    **The copy is validated before it is saved** (`full_clean()` under
    `as_invalid()`): a reset NOT NULL field nobody filled, or a copy that
    collides with a row on a unique constraint (a unique name per owner, say),
    is `invalid` naming the field — or `__all__` for a constraint over several —
    with nothing written, never a database error a door would answer 500.

    **Children.** A `copies` entry that names a CASCADE child's reverse
    accessor copies those child rows onto the copy (each with the copy's
    organization when it derives it); an append-only child NEVER copies — a
    ledger is the source's history, not the copy's — and naming one in
    `copies` is `ImproperlyConfigured`. A child not named does not copy.

    **Idempotent by key** (principle 16): a non-empty `idempotency_key` names
    the press; a repeat with the same key and source answers the FIRST copy
    with `created=False` — the `(tenant, duplicated_from, duplicate_key)`
    partial unique constraint is the guarantee, and a racing second press
    that hits it re-reads the winner.
    """
    from django.db import IntegrityError, transaction

    from apps.core.exceptions import as_invalid
    from apps.core.models import is_append_only, is_duplicable, is_org_scoped

    model = type(row)
    if not is_duplicable(model):
        raise TypeError(
            f"{model.__name__} has not declared `Duplicable`; a noun joins the duplicate verb "
            "by declaring the mixin (apps.core.models.Duplicable)."
        )
    declared = model.duplicate
    filled = dict(fill or {})
    stray = sorted(set(filled) - set(declared.resets))
    if stray:
        raise TypeError(
            f"{model.__name__}.duplicate: `fill` names {', '.join(stray)}, which "
            f"`resets` does not ({', '.join(declared.resets) or 'nothing'}). A service fills "
            "only what the declaration starts again; a copied field is the source's."
        )
    children = owned_children(model)
    for name in declared.copies:
        relation = children.get(name)
        if relation is not None and is_append_only(relation.related_model):
            raise ImproperlyConfigured(
                f"{model.__name__}.duplicate copies {name!r}, an append-only child: a ledger is "
                "the source's history, not the copy's, and never copies."
            )

    def first_copy() -> Any:
        if not idempotency_key:
            return None
        return (
            _every_row(model, tenant)
            .filter(duplicated_from=row, duplicate_key=idempotency_key)
            .order_by("created_at")
            .first()
        )

    existing = first_copy()
    if existing is not None:
        return existing, False
    copy = model(tenant=row.tenant)
    for name in declared.copies:
        if name in children:
            continue
        field = model._meta.get_field(name)
        attname = getattr(field, "attname", name)
        setattr(copy, attname, getattr(row, attname))
    for name, value in filled.items():
        setattr(copy, name, value)
    if is_org_scoped(model):
        copy.organization = organization if organization is not None else row.organization
    copy.duplicated_from = row
    copy.duplicate_key = idempotency_key
    with as_invalid():
        copy.full_clean()
    try:
        with transaction.atomic():
            copy.save()
    except IntegrityError:
        winner = first_copy()
        if winner is None:
            raise
        return winner, False
    for name in declared.copies:
        relation = children.get(name)
        if relation is not None:
            _copy_children(relation, source=row, copy=copy, tenant=tenant)
    return copy, True


def _copy_children(relation: Any, *, source: Any, copy: Any, tenant: Any) -> None:
    """Copy every child row of `source` along `relation` onto `copy`."""
    from apps.core.models import is_org_scoped

    child = relation.related_model
    fk = relation.field
    skip = {"id", "created_at", "updated_at", fk.name}
    for original in _every_row(child, tenant).filter(**{fk.name: source}):
        clone = child()
        for field in child._meta.concrete_fields:
            if field.name in skip or getattr(field, "generated", False):
                continue
            setattr(clone, field.attname, getattr(original, field.attname))
        setattr(clone, fk.name, copy)
        if is_org_scoped(child) and getattr(child, "derive_org_from", None) == fk.name:
            clone.organization = copy.organization
        clone.save()


# --- the per-row answers the face reads -----------------------------------------


#: The mounted `url_name`s, per URL resolver — the mount is static after boot,
#: so one walk answers every row's question. Keyed on the resolver so a test
#: that swaps `ROOT_URLCONF` reads its own mount.
_MOUNTED: dict[int, frozenset[str]] = {}


def mounted_url_names() -> frozenset[str]:
    """Every route name the live URL configuration mounts, namespaces stripped.

    **The road an act needs.** `allowed_acts` offers a verb only where its door
    exists: the ninja mount registers each operation's `url_name` on the URL
    configuration, so the question is read off the one registry every door is
    reversed through — never a list, and never `config` imported from `core`.
    """
    from django.urls import URLPattern, URLResolver, get_resolver

    resolver = get_resolver()
    known = _MOUNTED.get(id(resolver))
    if known is not None:
        return known
    names: set[str] = set()

    def walk(patterns: Any) -> None:
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns)
            elif isinstance(pattern, URLPattern) and pattern.name:
                names.add(pattern.name)

    walk(resolver.url_patterns)
    _MOUNTED[id(resolver)] = frozenset(names)
    return _MOUNTED[id(resolver)]


def allowed_acts(actor: Any, row: Any) -> tuple[str, ...]:
    """The verbs this actor may press on THIS row, in vocabulary order.

    Every verb `V` with `<kind>.V` in the vocabulary — the four derived, the
    family's, the kind's declared transitions — except `read` and `create`
    (neither is an act on a row that exists), for which `allows(actor,
    "<kind>.V", row)` answers yes AND the row's state admits `V`: an archived
    row admits only `restore`; a live row never `restore`. The server's answer
    per row, never the client's guess: a face draws exactly these (DESIGN's
    `allowed_acts`), so authority is resolved once, here.

    **An act is offered only where a door exists — and the door is LOOKED UP,
    never assumed.** The vocabulary also holds keys no person presses — a
    workflow's own key (`widget.onboard`) — so a verb is offered only when its
    door's `url_name` is mounted (`mounted_url_names`): the one `door_url_name`
    answers — the noun's `act_doors = {"<verb>": "<url_name>"}` declaration when
    the door is mounted under another name (files' `replace` is `version-add`),
    else `<kind>-<V>` — the same lookup house rule 74 demands the door by.
    The declaration sits on the noun because the act is the noun's and so is
    the route that serves it; rule 17 derives the machine twin from the same
    name, so the one mount decides both doors. `duplicate` is offered on a live
    `Duplicable` row with its door when the actor may CREATE at the hat — a
    duplicate is a create.

    **An act is offered only where the actor's SURFACE offers it**
    (`core.surfaces`, `Surface.acts`): a face on a read-only surface is never
    offered a press that surface's doors would not answer. The implicit staff
    surface offers every act, so a product with one face sees no difference.

    DOES NOT COVER — declared: an MCP-only tool under a rule-17 exemption is not
    a road for an act.
    """
    from apps.core import authz, surfaces
    from apps.core.models import is_archivable, is_duplicable

    offered = surfaces.acts(getattr(actor, "surface", surfaces.STAFF))
    kind = authz.kind_of(type(row))
    if kind is None or getattr(row, "merged_into_id", None) is not None:
        # A merged-away row is a tombstone: every write refuses `merged`.
        return ()
    mounted = mounted_url_names()
    archived = is_archivable(type(row)) and getattr(row, "archived_at", None) is not None
    acts: list[str] = []
    for action, permission in authz.vocabulary().items():
        verb = permission.verb
        if permission.kind != kind or verb in ("read", "create") or verb in acts:
            continue
        if archived and verb != "restore":
            continue
        if not archived and verb == "restore":
            continue
        if door_url_name(type(row), verb, kind) not in mounted:
            continue
        if verb not in offered:
            continue
        if authz.allows(actor, action, row):
            acts.append(verb)
    if (
        not archived
        and "duplicate" in offered
        and is_duplicable(type(row))
        and door_url_name(type(row), "duplicate", kind) in mounted
        and f"{kind}.create" in authz.vocabulary()
        and authz.allows(actor, f"{kind}.create")
    ):
        acts.append("duplicate")
    return tuple(acts)


def with_allowed_acts[R](rows: list[R], actor: Any) -> list[R]:
    """Set `allowed_acts` on every row — the per-row answer a face draws. Same list back.

    The one hook both a detail (a list of one) and a page call, so an `Out`
    that inherits `core.schemas.ActsOut` reads the same attribute however the
    row arrived; a resolver would die inside a `Page` (the conventions' gotcha).
    **Its cost does not grow with the page**: `allows` memoizes the actor's
    collection per NODE on the actor, so rows at the same few nodes cost the
    same at 5 rows as at 50 — the list's query pin says so (rule 5).

    **The price, measured** (`apps/core/tests/test_allowed_acts_page.py`):
    a page with acts is **6 statements, flat at 5 rows and at 50** — (1) the
    page itself; (2) ONE query attaching every row's node (`_attach_nodes`);
    (3)–(5) the actor's collection at the rows' node — its memberships, its
    grants, its roles' keys; (6) the memberships at the hat for the
    list's own `create` (`page_acts`; grants and role keys are memoized).
    Rows spread over k nodes add a collection per extra node, never per row.

    DOES NOT COVER — declared: a key's PREDICATE that queries per row pays per
    row (`may_archive` on a TENANT-scoped noun reads the tenant's root once per
    call); the org-scoped nouns the family ships are memoized end to end.
    """
    _attach_nodes(rows)
    for row in rows:
        row.allowed_acts = allowed_acts(actor, row)  # type: ignore[attr-defined]
    return rows


def _attach_nodes(rows: list[Any]) -> None:
    """Cache every org-scoped row's `organization` with ONE query for the page.

    `allows` asks at `where_of(actor, row)` — the row's node — and reading
    `row.organization` off a row that was not `select_related` is a query per
    row. A list that forgot the join would pay the N+1 here; this pays one.
    """
    from apps.core.models import Organization, is_org_scoped

    pending: dict[Any, list[Any]] = {}
    for row in rows:
        model = type(row)
        if not is_org_scoped(model):
            continue
        field = model._meta.get_field("organization")
        if field.is_cached(row) or row.organization_id is None:
            continue
        pending.setdefault(row.organization_id, []).append(row)
    if not pending:
        return
    for node in Organization.objects.filter(pk__in=list(pending)):
        for row in pending[node.pk]:
            type(row)._meta.get_field("organization").set_cached_value(row, node)


def page_acts(actor: Any, model: type[models.Model]) -> tuple[str, ...]:
    """The acts the LIST offers, not any row: today `create`, when the actor may, at the hat.

    A face draws the list's *New* act and its empty state's door from this and
    never from a guess (DESIGN's §5 / §14): `allows(actor, "<kind>.create")`
    asked with no row, which `where_of` reads as the hat — the node a
    create would land at (ADR core-20's placement law).
    """
    from apps.core import authz

    kind = authz.kind_of(model)
    if kind is None or f"{kind}.create" not in authz.vocabulary():
        return ()
    return ("create",) if authz.allows(actor, f"{kind}.create") else ()


@road("attach", example="apps/djb_notes/selectors.py::get_subject")
def resolve_subject(actor: Any, kind: str, subject_id: Any) -> Any:
    """The row a `(kind, id)` pointer names, if this actor could have reached it.

    The one resolver every polymorphic reference passes through (an attached
    note's subject, a bulk item's id): the kind registry names the model; the
    row is read `for_tenant(actor.tenant)` — **archived rows included**, since a
    subject's archive does not unmake what points at it — then `visible_to` the
    hat and `may_be_named` (C8). Anything that fails any step is
    `NotFound`, never `Forbidden`: a row in a sibling branch and a row that does
    not exist are one answer, deliberately, because a refusal that told them
    apart would confirm the row exists. An unknown kind is `NotFound` too.
    """
    from django.core.exceptions import ObjectDoesNotExist, ValidationError

    from apps.core import authz
    from apps.core.exceptions import NotFound
    from apps.core.models import is_archivable, is_org_scoped

    model = authz.kind_registry().get(kind)
    tenant = getattr(actor, "tenant", None)
    manager: Any = getattr(model, "objects", None)
    if model is None or tenant is None or not hasattr(manager, "for_tenant"):
        raise NotFound()
    read = manager.for_tenant(tenant)
    if is_archivable(model):
        read = read.including_archived()
    if is_org_scoped(model):
        read = read.visible_to(actor)
    try:
        row = read.get(pk=subject_id)
    except (ObjectDoesNotExist, ValidationError, ValueError, TypeError):
        raise NotFound() from None
    if is_org_scoped(model) and not authz.may_be_named(actor, row):
        raise NotFound()
    return row


# --- the subject seam: one parser, one reader, one landing law (ADR attach-1) ---
#
# An attachment (a note, a file, a tag link) names its subject as `<kind>:<id>`.
# Before this seam every owner parsed it and asked the questions in its own
# order — notes and tags the kind first, files the row first — so one pointer
# was `invalid` at one door and `not_found` at the next. The order here is the
# contract: the shape, then the kind (published vocabulary — saying "a widget
# takes no notes" leaks nothing), then the row (`resolve_subject`, C8 —
# `not_found`, never `forbidden`, for anything this actor could not reach).

#: Between a subject's kind and its id.
SUBJECT_SEPARATOR = ":"

#: The field every subject refusal names, on every door.
SUBJECT_FIELD = "subject"


# No Widget example: Widget does not adopt this road yet, so the example is a core test.
@road(
    "subject_parse",
    example="apps/core/tests/test_attach_conformance.py::test_a_malformed_pointer_is_invalid_naming_subject",
)
def parse_subject(text: str) -> tuple[str, UUID]:
    """`<kind>:<id>` into `(kind, UUID)`, or `invalid` naming `subject` — the id checked."""
    from apps.core.exceptions import Invalid

    kind, separator, raw_id = (text or "").strip().partition(SUBJECT_SEPARATOR)
    if not separator or not kind or not raw_id:
        raise Invalid(
            {SUBJECT_FIELD: ["Name the subject as <kind>:<id> — for example widget:<id>."]}
        )
    try:
        return kind, UUID(raw_id)
    except ValueError:
        raise Invalid({SUBJECT_FIELD: [f"{raw_id!r} is not an id."]}) from None


def takes(model: Any, attachment: str) -> bool:
    """Whether `model` lists `attachment` (`notes`, `files`, `tags`) in its `attachments`."""
    return attachment in tuple(getattr(model, "attachments", ()) or ())


# No Widget example: Widget does not adopt this road yet, so the example is a core test.
@road(
    "subject_read",
    example="apps/core/tests/test_attach_conformance.py::test_every_owner_refuses_in_the_seam_s_order_or_is_counted",
)
def subject_for(actor: Any, text: str, *, attachment: str) -> Any:
    """The row `<kind>:<id>` names, if its kind takes `attachment` and this actor can reach it.

    Three answers, in this order: a malformed pointer → `invalid` naming
    `subject`; a kind that does not declare `attachment` (or no kind at all) →
    `invalid` naming `subject`; a row this actor could not have reached →
    `not_found` (`resolve_subject`).
    """
    from apps.core import authz
    from apps.core.exceptions import Invalid

    kind, subject_id = parse_subject(text)
    model = authz.kind_registry().get(kind)
    if model is None or not takes(model, attachment):
        raise Invalid({SUBJECT_FIELD: [f"A {kind} does not take {attachment}."]})
    return resolve_subject(actor, kind, subject_id)


# No Widget example: Widget does not adopt this road yet, so the example is a core test.
@road(
    "landing",
    example="apps/core/tests/test_attach_conformance.py::test_landing_for_follows_the_law",
)
def landing_for(subject: Any, actor: Any) -> Any:
    """Where an attachment on `subject` lives: its organization, else the acting hat (attach-1).

    An organization is its own landing; an org-scoped subject lands at its
    organization; a TENANT-WIDE subject has none, so the attachment lands at
    the ACTING HAT — never the root, because visibility is down-only and a
    root-landed row is one its own branch author could not read back. No hat is
    `no_acting_scope`, the door's one word for it.
    """
    from apps.core.api.acting import require_hat
    from apps.core.models import Organization, is_org_scoped

    if isinstance(subject, Organization):
        return subject
    if is_org_scoped(type(subject)):
        return subject.organization
    return require_hat(actor)


# --- the declared shapes the later verbs' hook modules export -------------------
#
# Seams, in the tree before the changes that fill them (§ I+): an app's
# `merge_repointers.py` exports `REPOINTERS: dict[noun | "*", Repointer]` and an
# app's `importers.py` exports `IMPORTERS: dict[noun, Importer]`, both found by
# `hook()` through the closed tuple above.


@dataclass(frozen=True, slots=True)
class Repointer:
    """How one app re-points ITS rows from a merged loser to the survivor.

    `title` is the human name of what moves (*Notes*). An app's
    `merge_repointers.py` exports `REPOINTERS = {noun | "*": Repointer(...)}`;
    `"*"` answers for every noun (the polymorphic attach owners). **The seven
    promises every repointer keeps** — asserted once, across every declared
    repointer, by `apps/core/tests/test_repointer_conformance.py`:

    1. **Counts.** `count(*, tenant, loser)` answers the rows that will LEAVE
       the loser — moved, or collapsed onto a unique pair the survivor already
       holds; `repoint(*, tenant, actor, loser, survivor)` answers the rows that
       LEFT. On a world that did not move between the two calls they are equal.
    2. **Safety.** `repoint` re-resolves BOTH rows for the actor
       (`core.authz.may_be_named`, `core.verbs.resolve_subject`): an unreachable
       row is `NotFound` with zero rows changed and no event — it trusts no
       caller, the merge included.
    3. **Events.** One `<app>.<kind>.moved` per MOVED row, inside the merge's
       transaction; a COLLAPSED row emits its owner's own leaving event (a
       `.deleted`), never `.moved`. The merge's own `<app>.<noun>.merged`
       carries `repoints: [{title, left}]` from the APPLY's answers, never the
       dry run's.
    4. **Population.** Tenant-wide — `for_tenant(t).including_archived()`, no
       `visible_to`: an attachment does not follow its subject's moves, so the
       loser's rows sit wherever the subject lived when they were filed, and a
       narrowed read would under-count what the merge moves. The read carries
       house rule 24's own valve comment, naming the merge's two-record
       authorization.
    5. **Version.** Every moving write stamps `updated_at` (house rule 76's
       form on every repointer, `Versioned` or not), so a re-pointed row never
       reads as untouched to anything that syncs on it.
    6. **Authorization is the merge's.** The noun's service required
       `<noun>.merge` on the loser and on the survivor before any repointer
       runs; the repointer's service is `# door:`-fenced and `# authz:`-valved
       naming that (`apps/files/services.py`'s `move_attached_files`).
    7. **A kind the noun does not take is a no-op.** A `"*"` owner answers for
       every noun a merge can join, and a mergeable noun need not take every
       attachment the tree has an owner for: where the noun's `attachments`
       does not name the owner's word, `count` and `repoint` both answer 0 —
       never a refusal that stops the merge.

    Both callables go through the owning app's OWN services (C3): a merge never
    writes another app's row from outside it.
    """

    title: str
    count: Callable[..., int]
    repoint: Callable[..., int]


@road("import_rows", example="apps/example/importers.py::apply")
@dataclass(frozen=True, slots=True)
class Importer:
    """How one noun is imported: its row schema, its natural key, its apply.

    `row` is a `StrictIn` schema whose fields are the file's header;
    `natural_key(*, tenant, actor, row)` finds the existing row a file row
    means (or `None`), read-only; `apply(*, tenant, actor, row)` calls the
    noun's OWN services and answers `(obj, "created" | "updated" |
    "unchanged")`.

    **Both are asked at the run's hat** — `actor.org` is where the file was
    staged and where it is applied — so `natural_key` looks exactly where
    `apply` will: the preview's `update` is a promise the apply keeps, never a
    tenant-wide guess the apply then contradicts with a create (or a refusal).
    The plain form is for `apply` to find its row by calling `natural_key`.
    """

    row: type[Any]
    natural_key: Callable[..., Any]
    apply: Callable[..., tuple[Any, str]]
