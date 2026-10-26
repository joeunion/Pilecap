"""`manage.py introspect` — the machine door onto the real schema and the real doors.

Agents read this instead of guessing: the installed apps, every model with its
table, base classes and fields — including, for a field that declares them, the
values it may hold — every URL pattern with its view, every API route
with the auth it declares, every refusal the product can make, and the
non-secret slice of settings. Every section is read from the live registry that
serves it, never from a list somebody maintains by hand. Output is JSON on
stdout and nothing else, so it can be piped straight into a tool.

Nothing whose name looks like a credential is ever printed: any key containing
KEY, SECRET, PASSWORD or TOKEN is replaced with "[redacted]", at every depth.

This is the one module under `apps/` that imports `config`, and it does so
lazily, inside the function that needs each mount. Reporting what the mounts
found is its whole job — an import-linter contract exempts it by name, with that
reason, rather than the rule being weakened for everybody.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import re
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import models
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.discovery import declared, declared_services, imported
from apps.core.management import BaseCommand
from apps.core.models import is_append_only
from apps.core.roads import road

SENSITIVE = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|PASSWD|SALT", re.IGNORECASE)
REDACTED = "[redacted]"


def _redact(value: Any) -> Any:
    """Strip anything that looks like a credential, at any depth."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            key_text = str(key)
            out[key_text] = REDACTED if SENSITIVE.search(key_text) else _redact(inner)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _dotted(obj: type[Any]) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"


def _callable_name(target: Any) -> str:
    """A name for a callable that is the SAME in every process (N167c).

    `introspect` is the instrument agents read instead of guessing, and an
    instrument whose output changes when nothing changed cannot be diffed. Four
    entries in the `urls` section used to fall back to `repr()` on a
    `functools.partial` and carry the memory addresses with them —

        functools.functools.partial(<function llms_txt at 0x125b6e020>,
                                    api=<config.api.ContractAPI object at 0x125a31670>)

    — so two runs of the same tree produced two different documents and anyone
    comparing shas had to normalise `0x…` by hand before they could compare
    anything at all. The fix is at source: nothing here ever renders an
    address, so there is nothing to normalise downstream.

    Three shapes, in order:

    * a `functools.partial` is the WRAPPED callable's name, marked — the
      wrapping is a mounting detail, but it is not nothing, so it is said
      rather than hidden. `partial(partial(f))` unwraps all the way down.
    * anything carrying `__module__` and `__qualname__` (a function, a class, a
      method) is those two joined — what it has always been.
    * anything else is named by its TYPE rather than by `repr()`, because
      `repr()` is where the addresses came from. "an instance of this class" is
      less than the repr said and all of it is true, which is the trade the
      whole section is making.
    """
    if isinstance(target, functools.partial):
        return f"{_callable_name(target.func)} (partial)"
    if isinstance(target, type):
        return _dotted(target)
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}.{qualname}"
    return f"{_dotted(type(target))} instance"


def _choices_payload(field: models.Field[Any, Any]) -> list[dict[str, Any]] | None:
    """The declared choices of one field, as DATA — never a repr.

    An agent asking "what values may this column hold" had, until this existed,
    exactly two options: guess, or go and read `models.py` — which is the
    guessing this command exists to end. `WorkflowRun.status` is the motivating
    case: `cancelled` is a real, distinct closing status (ADR workflows-7) and
    nothing an agent could read here said so.

    Three properties, all deliberate:

    * **A list of objects, in declaration order.** The order is the model's own
      and Django preserves it, so the emitted document is byte-stable across
      processes (QB-R3) without anything here sorting and thereby lying about
      what the model said.
    * **Values and labels are coerced with `str()` unless they are already a
      JSON scalar.** A label is routinely a lazy translation proxy, which
      `json.dumps` cannot serialise and whose `repr()` carries an address —
      the very thing N167c took out of this document.
    * **Grouped choices are flattened** (`flatchoices`), because the group
      heading is a form-rendering detail and the question being answered here
      is which values are legal.

    `None` — the key is absent — for a field that declares none, so the section
    stays the same size for the overwhelming majority of fields that have no
    choices to report.
    """
    declared = getattr(field, "flatchoices", None) or getattr(field, "choices", None)
    if not declared:
        return None

    def scalar(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    return [{"value": scalar(value), "label": str(label)} for value, label in declared]


def _field_payload(field: models.Field[Any, Any] | models.ForeignObjectRel) -> dict[str, Any]:
    related = getattr(field, "related_model", None)
    if isinstance(field, models.ForeignObjectRel):
        return {
            "name": field.get_accessor_name() or field.name,
            "type": "Reverse" + field.__class__.__name__,
            "related_model": related._meta.label if related is not None else None,
            "null": True,
            "unique": False,
        }
    payload: dict[str, Any] = {
        "name": field.name,
        "type": field.get_internal_type(),
        "related_model": related._meta.label if related is not None else None,
        "null": bool(field.null),
        "unique": bool(field.unique),
    }
    choices = _choices_payload(field)
    if choices is not None:
        payload["choices"] = choices
    return payload


#: The declarations a road READS beside its marker — a value rather than a
#: flag, so `introspect` reports the value: which verbs a noun runs in bulk,
#: which attachment kinds it takes, which FK a move hands over. A road that
#: comes to read a further one names it here; the marker half needs no edit.
ROAD_DECLARATIONS: tuple[str, ...] = ("bulk_verbs", "attachments", "move_owner_field")


def family_marker_names() -> frozenset[str]:
    """Every family declaration `introspect` reports: each road's marker, plus the values.

    DERIVED from `core.verbs.ROADS` — the table house rule 74 reads — so a road
    that joins the family is reported the moment it is in the table, with no
    edit here. `ANY_MARKER` is the history road's "any of the others" and is not
    a declaration a model makes.
    """
    from apps.core.verbs import ANY_MARKER, ROADS

    return frozenset(
        road.marker for road in ROADS.values() if road.marker != ANY_MARKER
    ) | frozenset(ROAD_DECLARATIONS)


def _marker_value(value: Any) -> Any:
    """`True` for a flag, the value itself (a list for a tuple) for a declaration."""
    if value is True:
        return True
    if isinstance(value, (frozenset, set)):
        return sorted(str(item) for item in value)
    if isinstance(value, (tuple, list)):
        return [str(item) for item in value]
    return str(value)


def _markers_payload(model: type[models.Model]) -> dict[str, Any]:
    """The behavioural declarations a model carries, read off the class.

    A model's `bases` already say what it INHERITS; they do not say what it has
    DECLARED, and the declarations below change how the row behaves for
    everybody who touches it:

    * **`append_only`** — rows are created and never updated or deleted (house
      rule 20). The population is the declaration, not a name.
    * **`inherited_downward`** — `governing(org)` is legal on this model, and a
      branch may NAME a row its parent owns (`core.models.InheritedDownward`).
    * **`derive_org_from`** — the FK this row's organization must equal, or
      `None` when it chooses its own (`OrgScopedModel`'s landing gate).
    * **the noun-verb family** — every road's marker in `core.verbs.ROADS`
      (`archivable`, `versioned`, `movable`, `bulk_verbs`, … as the family
      grows), each `true` when the class declares it, plus the values a road
      reads beside its marker (`ROAD_DECLARATIONS`): `bulk_verbs` and
      `attachments` as lists, `move_owner_field` as the field's name. House
      rule 74 demands a road for each marker, so this is the list of the
      noun's doors a reader should expect.

    Before this, a criterion phrased "the marker is visible in `introspect`" was
    unwritable: the payload's keys were exactly app/bases/fields/name/table, so
    the only way to answer "which models are append-only" from the instrument was
    to infer it from a base class that does not carry it.

    DERIVED, not listed: the models come from the registry, each marker is read
    off the class by the attribute the class declares, and the family's marker
    names come off `ROADS` (`family_marker_names`). What IS pinned is the set of
    marker KINDS — `apps/core/tests/test_introspect.py` holds it equal to the
    derivation and refuses a vacuous population.
    """
    markers: dict[str, Any] = {}
    if is_append_only(model):
        markers["append_only"] = True
    if getattr(model, "inherited_downward", False):
        markers["inherited_downward"] = True
    derived_from = getattr(model, "derive_org_from", None)
    if derived_from:
        markers["derive_org_from"] = str(derived_from)
    for name in sorted(family_marker_names()):
        value = getattr(model, name, None)
        if value:
            markers[name] = _marker_value(value)
    return markers


def _authz_kind_payload(model: type[models.Model]) -> tuple[str | None, str | None]:
    """A model's authorization kind, or `null` with the reason it has none.

    Two ways to be `null` and they are different facts, so the reason says
    which: a third-party table this deployment did not design, or a first-party
    model that opted out with a sentence of its own.
    """
    from apps.core.authz import kind_of

    if not model.__module__.startswith("apps."):
        return None, (
            f"not a first-party model: {model.__module__} is a table this deployment did "
            "not design, so a permission over it is one nobody could act on"
        )
    kind = kind_of(model)
    if kind is None:
        return None, str(getattr(model, "authz_kind_reason", "") or "")
    return kind, None


def _model_payload(model: type[models.Model]) -> dict[str, Any]:
    meta = model._meta
    bases = [
        _dotted(base)
        for base in model.__mro__[1:]
        if isinstance(base, type) and issubclass(base, models.Model)
    ]
    fields: list[dict[str, Any]] = [_field_payload(field) for field in meta.get_fields()]
    authz_kind, authz_kind_reason = _authz_kind_payload(model)
    return {
        "app": meta.app_label,
        "name": model.__name__,
        "table": meta.db_table,
        "bases": bases,
        "authz_kind": authz_kind,
        "authz_kind_reason": authz_kind_reason,
        "markers": _markers_payload(model),
        "fields": fields,
    }


def _view_payload(callback: Any) -> tuple[str, list[str] | None]:
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view_class is not None:
        allowed: list[str] = list(getattr(view_class, "http_method_names", []))
        methods = sorted(m.upper() for m in allowed if hasattr(view_class, m))
    else:
        methods = []
    target = view_class if view_class is not None else callback
    return _callable_name(target), methods or None


def _segment(pattern: Any) -> str:
    """One URL segment as a path, with the regex anchors taken off."""
    return str(pattern).lstrip("^").rstrip("$")


def _walk_urls(patterns: list[Any], prefix: str, namespace: str | None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for entry in patterns:
        route = prefix + _segment(entry.pattern)
        if isinstance(entry, URLResolver):
            child_namespace = entry.namespace or namespace
            found.extend(_walk_urls(list(entry.url_patterns), route, child_namespace))
        elif isinstance(entry, URLPattern):
            view, methods = _view_payload(entry.callback)
            name = entry.name
            if name and namespace:
                name = f"{namespace}:{name}"
            payload: dict[str, Any] = {
                "name": name,
                "pattern": "/" + route.lstrip("/"),
                "view": view,
            }
            if methods:
                payload["methods"] = methods
            found.append(payload)
    return found


def _routes_payload() -> list[dict[str, Any]]:
    """Every API route, read from the NinjaAPI that serves them.

    The auth column is the one that matters: a route with an empty list declares
    no authentication, and that is a house-rule violation visible from here
    without reading a single source file.

    `paginated` answers what a CALLER meets — whether the body is the cursor
    envelope — and it is read off the one seam (ADR core-24), not off a private
    ninja marker. Read off the marker it said `false` about three routes that
    answer `{items, has_more, next_cursor, count}`, and an instrument a
    criteria-writer trusts is worse than no instrument when it is confidently
    wrong. `apps/core/tests/test_pagination_seam.py` holds the column to the
    mounted behaviour.
    """
    from apps.core.api.mount import bound_operations
    from apps.core.api.pagination import answers_cursor_envelope
    from config.urls import API_PREFIX

    routes: list[dict[str, Any]] = []
    for path, url_name, operation in bound_operations():
        routes.append(
            {
                "pattern": re.sub(r"/{2,}", "/", f"/{API_PREFIX}/{path}"),
                "methods": sorted(operation.methods),
                "name": f"api:{url_name}" if url_name else None,
                "view": _callable_name(operation.view_func),
                "auth": [type(callback).__name__ for callback in operation.auth_callbacks],
                "paginated": answers_cursor_envelope(operation),
            }
        )
    return sorted(routes, key=lambda route: (str(route["pattern"]), str(route["methods"])))


def _tools_payload() -> list[dict[str, Any]]:
    """Every MCP tool, read from the server that serves them."""
    from config.mcp import server

    # `asyncio.run` is correct here and would not be inside Django: a management
    # command is a synchronous process with no event loop of its own, and this
    # is the only async call it makes. Nothing in a request, a consumer or an
    # activity may do this — see `apps.core.asyncdb`.
    tools = asyncio.run(server.list_tools())
    return sorted(
        (
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ),
        key=lambda tool: str(tool["name"]),
    )


def _consumers_payload() -> list[dict[str, Any]]:
    """Every websocket route, read from the patterns `config.asgi` discovered."""
    from config.asgi import discovered_websocket_urlpatterns

    return [
        {
            "pattern": _segment(entry.pattern),
            "name": entry.name,
            "consumer": _callable_name(entry.callback),
        }
        for entry in discovered_websocket_urlpatterns()
    ]


def _workflows_payload() -> list[dict[str, Any]]:
    """Every workflow the worker would register, read through the one discovery walk."""
    return sorted(
        (
            {
                "name": getattr(workflow, "__temporal_workflow_definition").name,
                "definition": _dotted(workflow),
            }
            for _config, workflows in declared(
                "workflows", "WORKFLOWS", predicate=lambda value: isinstance(value, list)
            )
            for workflow in workflows
        ),
        key=lambda item: str(item["name"]),
    )


def _activities_payload() -> list[dict[str, Any]]:
    """Every activity the worker would register, read through the one discovery walk."""
    return sorted(
        (
            {
                "name": getattr(activity, "__temporal_activity_definition").name,
                "function": _callable_name(activity),
            }
            for _config, activities in declared(
                "activities", "ACTIVITIES", predicate=lambda value: isinstance(value, list)
            )
            for activity in activities
        ),
        key=lambda item: str(item["name"]),
    )


def _policies_payload() -> list[dict[str, Any]]:
    """**The whole vocabulary**, not just the actions a predicate happens to name.

    An agent asking "may a member do this" reads it here rather than guessing
    from a role name — and before this section printed the vocabulary it printed
    the *policy registry*, which is a different and much smaller population: a
    key with no predicate had no row at all, so the four derived verbs of every
    kind were invisible to every instrument and an agent could only learn a
    permission existed by being refused by it.

    What each column answers:

    * `decided_by` — `derived` (the model registry produced this key and nobody
      typed it), `declared` (an app's `ACTION_PROSE` did), `reserved`
      (`core` did, and no pattern matches it).
    * `conforms` — whether the key fits `<kind>.<verb>` with a real kind and a
      verb that is not a second spelling of one of the four. A `false` here is
      **not** a refusal and changes no answer: the key is in the vocabulary and
      the policy lookup is untouched. It is the census saying which keys a later
      sweep owns.
    * `default_roles` — who holds the key by default in the CODE layer: `owner`
      always, plus every declared role whose patterns match, plus the app-side
      `DEFAULT_ROLES` additions. A tenant's custom roles are rows and are
      deliberately not here; this is the answer for a deployment nobody has
      connected to.
    * `predicate` — the dotted name of the callable that narrows the key, or
      `null`. The narrowing seam a product edits is visible here on the day it
      edits it.
    * `renamed_from` — the old keys that still answer as this one, for one
      release, with one deprecation printed per process.

    ## Why there is no `member_default` column any more

    There was one, and **every value it ever printed was a value that never
    applied.** `core.authz.allows` consults the policy FIRST and returns; the
    `is_read(action)` role default is the branch taken only when no policy names
    the action — and every row in this section was, by construction, an action a
    policy named. So the column answered a question about the rows that were not
    there, in a table of the rows that were.

    It was found the loudest way it could be: `usage.read_report` printed
    `deny` while every role in the deployment may read the report
    (`apps/usage/policies.py`, `USAGE_READ_REPORT`). But the defect was never
    that one row — `export.read` printed `allow` and `widget.update` printed
    `deny` with exactly as little authority, and both happened to agree with
    their predicate by luck rather than by derivation. A column that is right by
    coincidence is the kind of instrument reading that stops an agent from
    looking further, which is worse than no column at all. `default_roles` is
    derived from the declarations rather than from the verb, which is what the
    old column could never be.
    """
    from apps.core.authz import vocabulary

    found: list[dict[str, Any]] = []
    for action, permission in vocabulary().items():
        found.append(
            {
                "action": action,
                "kind": permission.kind,
                "verb": permission.verb,
                "app": permission.app,
                "decided_by": permission.decided_by,
                "conforms": permission.conforms,
                "non_conformance": permission.non_conformance or None,
                "sentence": permission.sentence,
                "is_read": permission.is_read,
                "default_roles": sorted(permission.default_roles),
                "predicate": (
                    _callable_name(permission.predicate)
                    if permission.predicate is not None
                    else None
                ),
                "renamed_from": sorted(permission.renamed_from) or None,
            }
        )
    return sorted(found, key=lambda item: str(item["action"]))


def _roles_payload() -> list[dict[str, Any]]:
    """Every role this deployment declares in code, with the collection it resolves to.

    `owner` is first and is not a declaration: it is the one platform role and
    its collection IS the vocabulary, present and future, so it is printed with
    the whole count rather than left out as "special".

    `collection_size` is the number of keys the role holds by default —
    patterns matched against the vocabulary plus the app-side additions — so a
    product that narrows a role sees the number move in the instrument the same
    day it edits the line. A tenant's own roles are rows in `core.Role` and are
    not here: this section is the code layer.
    """
    from apps.core.authz import (
        OWNER_ROLE,
        defaults_for,
        role_declarations,
        role_declarers,
        vocabulary,
    )

    declarers = role_declarers()
    found: list[dict[str, Any]] = [
        {
            "key": OWNER_ROLE,
            "name": "Owner",
            "app": "core",
            "declared_in": None,
            "permissions": ["*"],
            "is_default_for_new_members": False,
            "collection_size": len(vocabulary()),
        }
    ]
    for key, role in sorted(role_declarations().items()):
        found.append(
            {
                "key": key,
                "name": role.name,
                "app": declarers.get(key, ""),
                "declared_in": f"apps/{declarers.get(key, '')}/roles.py",
                "permissions": list(role.permissions),
                "is_default_for_new_members": role.is_default_for_new_members,
                "collection_size": len(defaults_for(key)),
            }
        )
    return found


def _events_payload() -> list[dict[str, Any]]:
    """Every event name an app declares in its `events.py`.

    Names only. What subscribes to them is data (`WebhookEndpoint` rows) and the
    realtime bridge, never code — so there is nothing else here to report.
    """
    found: list[dict[str, Any]] = []
    for config, module in imported("events"):
        for attribute in sorted(dir(module)):
            if attribute.startswith("_") or not attribute.isupper():
                continue
            value = getattr(module, attribute)
            if isinstance(value, str):
                found.append({"app": config.label, "constant": attribute, "name": value})
    return sorted(found, key=lambda item: str(item["name"]))


def _services_payload() -> list[dict[str, Any]]:
    """Every `@service` an installed app's `services.py` defines — the writes, by name.

    `name` is the dotted path; `tenant` and `actor` say whether the signature
    declares each keyword, which is what the audit row and the authorization
    read (a service that takes no `tenant` writes no tenant-scoped audit row —
    ADR core-8). Read from the live modules through `core.discovery`, the same
    population the gate's AST walk counts from the files.
    """
    found: list[dict[str, Any]] = []
    for config, name, function in declared_services():
        parameters = inspect.signature(inspect.unwrap(function)).parameters
        found.append(
            {
                "name": f"{config.name}.services.{name}",
                "app": config.label,
                "tenant": "tenant" in parameters,
                "actor": "actor" in parameters,
            }
        )
    return sorted(found, key=lambda item: str(item["name"]))


def _bridge_payload() -> list[dict[str, Any]]:
    """Every name registered on `core.bridge`, and the callable filling it.

    The bridge is how a lower layer calls a higher one without importing it —
    which makes it exactly the dependency an agent cannot find by reading
    imports. This is the registry itself, read live: the names the platform
    apps filled from their `AppConfig.ready()`, in this process.
    """
    from apps.core import bridge

    return sorted(
        (
            {"name": name, "provider": _callable_name(fn)}
            for name, fn in bridge.registered().items()
        ),
        key=lambda item: str(item["name"]),
    )


def _refusals_payload() -> list[dict[str, Any]]:
    """Every refusal this product can make, read from `core.exceptions`' registry.

    The question an agent otherwise answers by grepping for `raise`: what can
    this product say no with, which layer decides each one, what is true when
    it happens, and what can be done about it.

    Five fields, and the split between `remedies` and `remedy` is the point:

    * `boundary` — where to look: `selector`, `service`, `policy` or `door`.
      It is also what decides whether an idempotent retry REPLAYS this refusal
      or re-evaluates the request (ADR core-23: `boundary == "door"` means the
      key was never spent), so it is a behavioural fact and not a filing label.
    * `status` — the number the HTTP door answers this code with, and **`null`
      is a declaration too**: a code with no status is one the HTTP door never
      answers (a machine-door refusal — a tool answers one line of text, not a
      number). Derived off the registry since ADR core-23; before that
      `CODE_STATUS` was a hand-appended table in `config/api.py` and this
      instrument could not see it at all.
    * `fact` — what is TRUE, and what the client is told. `not_found`'s says
      that not-there and not-yours are one answer on purpose.
    * `remedies` — what the caller can DO, as label + destination. **These
      reach the wire**, composed once server-side, so a screen and an assistant
      offer the same way out.
    * `remedy` — the developer's advice, which lives here and **never** on the
      wire: it names `policies.py` and `X-Tenant`, and a client sent internal
      prose is a client that starts parsing it.
    """
    from apps.core.exceptions import REFUSALS

    return sorted(
        (
            {
                "code": refusal.code,
                "boundary": refusal.boundary,
                "status": refusal.status,
                "fact": refusal.fact,
                "remedies": [
                    {"label": remedy.label, "destination": remedy.destination}
                    for remedy in refusal.remedies
                ],
                "remedy": refusal.remedy,
            }
            for refusal in REFUSALS.values()
        ),
        key=lambda item: str(item["code"]),
    )


def _settings_payload() -> dict[str, Any]:
    databases: dict[str, dict[str, Any]] = {}
    for alias, config in settings.DATABASES.items():
        databases[alias] = {
            "ENGINE": config.get("ENGINE"),
            "NAME": str(config.get("NAME", "")),
        }
    return {
        "INSTALLED_APPS": list(settings.INSTALLED_APPS),
        # What this deployment switched OFF. Printed beside what it installed
        # because the two answer one question together: an agent reading a tree
        # with no widgets routes needs to know whether the app is absent or
        # merely disabled here, and an empty list is the honest answer for the
        # ordinary case.
        "DJB_DISABLED_APPS": list(getattr(settings, "DJB_DISABLED_APPS", [])),
        "AUTH_USER_MODEL": settings.AUTH_USER_MODEL,
        "DATABASES": databases,
        "DEBUG": bool(settings.DEBUG),
        "MIDDLEWARE": list(settings.MIDDLEWARE),
        "TEMPORAL_ADDRESS": settings.TEMPORAL_ADDRESS,
        "TEMPORAL_NAMESPACE": settings.TEMPORAL_NAMESPACE,
        "TEMPORAL_TASK_QUEUE": settings.TEMPORAL_TASK_QUEUE,
        "ASGI_APPLICATION": settings.ASGI_APPLICATION,
    }


@road("introspect", example="apps/core/tests/test_introspect.py::test_it_reports_the_machine_door")
class Command(BaseCommand):
    """The machine door onto the real schema and the real doors, as JSON."""

    help = (
        "Print the real apps and models, and every door — URLs, API routes, MCP tools, "
        "socket consumers, workflows, activities — as JSON."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        models_payload = sorted(
            (_model_payload(model) for model in apps.get_models()),
            key=lambda item: (str(item["app"]), str(item["name"])),
        )
        payload: dict[str, Any] = {
            "apps": sorted(config.label for config in apps.get_app_configs()),
            "models": models_payload,
            "urls": _walk_urls(list(get_resolver().url_patterns), "", None),
            "routes": _routes_payload(),
            "tools": _tools_payload(),
            "consumers": _consumers_payload(),
            "workflows": _workflows_payload(),
            "activities": _activities_payload(),
            "bridge": _bridge_payload(),
            "policies": _policies_payload(),
            "roles": _roles_payload(),
            "events": _events_payload(),
            "services": _services_payload(),
            "refusals": _refusals_payload(),
            "settings": _redact(_settings_payload()),
        }
        self.stdout.write(json.dumps(payload, indent=2, sort_keys=False))
