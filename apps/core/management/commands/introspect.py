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
import importlib
import importlib.util
import json
import re
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import models
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.management import BaseCommand

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


def _model_payload(model: type[models.Model]) -> dict[str, Any]:
    meta = model._meta
    bases = [
        _dotted(base)
        for base in model.__mro__[1:]
        if isinstance(base, type) and issubclass(base, models.Model)
    ]
    fields: list[dict[str, Any]] = [_field_payload(field) for field in meta.get_fields()]
    return {
        "app": meta.app_label,
        "name": model.__name__,
        "table": meta.db_table,
        "bases": bases,
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
    """
    from config.api import api
    from config.urls import API_PREFIX

    routes: list[dict[str, Any]] = []
    for bound in api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            for operation in path_view.operations:
                view_func = operation.view_func
                routes.append(
                    {
                        "pattern": re.sub(r"/{2,}", "/", f"/{API_PREFIX}/{bound.prefix}/{path}"),
                        "methods": sorted(operation.methods),
                        "name": f"api:{operation.url_name}" if operation.url_name else None,
                        "view": _callable_name(view_func),
                        "auth": [type(callback).__name__ for callback in operation.auth_callbacks],
                        "paginated": hasattr(view_func, "_ninja_contribute_args"),
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
    """Every workflow the worker would register."""
    from config.temporal import discovered_workflows

    return sorted(
        (
            {
                "name": getattr(workflow, "__temporal_workflow_definition").name,
                "definition": _dotted(workflow),
            }
            for workflow in discovered_workflows()
        ),
        key=lambda item: str(item["name"]),
    )


def _activities_payload() -> list[dict[str, Any]]:
    """Every activity the worker would register."""
    from config.temporal import discovered_activities

    return sorted(
        (
            {
                "name": getattr(activity, "__temporal_activity_definition").name,
                "function": _callable_name(activity),
            }
            for activity in discovered_activities()
        ),
        key=lambda item: str(item["name"]),
    )


def _policies_payload() -> list[dict[str, Any]]:
    """Every authorization policy, read from the registry `core.authz` discovered.

    An agent asking "may a member do this" reads it here rather than guessing
    from a role name — and a *missing* action is the answer too: no policy means
    the role defaults decide, and for a write that means no.

    ## Why there is no `member_default` column any more

    There was one, and **every value it ever printed was a value that never
    applied.** `core.authz.allows` consults the policy FIRST and returns; the
    `is_read(action)` role default is the branch taken only when no policy names
    the action — and every row in this section is, by construction, an action a
    policy names. So the column answered a question about the rows that are not
    here, in a table of the rows that are.

    It was found the loudest way it could be: `usage.read_report` printed
    `deny` while every role in the deployment may read the report
    (`apps/usage/policies.py`, `USAGE_READ_REPORT`). But the defect was never
    that one row — `export.read` printed `allow` and `widget.update` printed
    `deny` with exactly as little authority, and both happened to agree with
    their predicate by luck rather than by derivation. A column that is right by
    coincidence is the kind of instrument reading that stops an agent from
    looking further, which is worse than no column at all.

    ## What replaces it

    `roles` — the roles a **declaring** policy admits, read through
    `core.authz.declared_roles`, and `null` for a policy that declares none.
    That is the narrowing seam this makes visible: a product that narrows
    `USAGE_READ_REPORT` to owners and admins sees the narrowing here, in the
    instrument, on the same day it edits the declaration — where before it was
    visible only in the diff and in the app's own file.

    `decided_by` says which of the two this row is, so `null` is never read as
    "nobody knows": `declaration` means the set beside it is the rule, and
    `predicate` means the named callable is, and there is no set to publish.
    """
    from apps.core.authz import declared_roles, policies

    found: list[dict[str, Any]] = []
    for action, policy in policies().items():
        roles = declared_roles(policy)
        found.append(
            {
                "action": action,
                "policy": _callable_name(policy),
                "decided_by": "declaration" if roles is not None else "predicate",
                "roles": sorted(roles) if roles is not None else None,
            }
        )
    return sorted(found, key=lambda item: str(item["action"]))


def _events_payload() -> list[dict[str, Any]]:
    """Every event name an app declares in its `events.py`.

    Names only. What subscribes to them is data (`WebhookEndpoint` rows) and the
    realtime bridge, never code — so there is nothing else here to report.
    """
    found: list[dict[str, Any]] = []
    for config in apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module_name = f"{config.name}.events"
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
        for attribute in sorted(dir(module)):
            if attribute.startswith("_") or not attribute.isupper():
                continue
            value = getattr(module, attribute)
            if isinstance(value, str):
                found.append({"app": config.label, "constant": attribute, "name": value})
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

    Four fields, and the split between the last two is the point:

    * `boundary` — where to look: `selector`, `service`, `policy` or `door`.
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


class Command(BaseCommand):
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
            "events": _events_payload(),
            "refusals": _refusals_payload(),
            "settings": _redact(_settings_payload()),
        }
        self.stdout.write(json.dumps(payload, indent=2, sort_keys=False))
