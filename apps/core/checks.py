"""Django system checks for the house rules — the strongest enforcement tier.

These read the REAL registries, never source: the model registry (rules 2, 15),
the live ninja API (rule 3), the admin site (rule 21), the discovered policy
registry (rule 13's model half), the MCP tool manager against the route table
(rule 17 — door parity), and each app's directory shape (rule 11). They run on
every `manage.py` call and as a gate leg (`manage.py check --tag djb`); the
quality gate treats their errors as violations.

Allow-lists and exemptions are DATA, in `quality/rules.yaml`, each with a
reason — a judgement somebody wrote down, in the one file the gate
consistency-checks, never an edit to the check.

No check here touches the database; `--tag djb` runs without one.
"""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from django.apps import AppConfig, apps
from django.conf import settings
from django.core.checks import CheckMessage, Error, register
from django.db import models

DJB = "djb"

# Module names an app may use for the canonical jobs (house rule 11). A file
# doing one of these jobs under another name is where business logic hides.
CANONICAL_MODULES = {
    "__init__",
    "apps",
    "models",
    "services",
    "selectors",
    "schemas",
    "api",
    "mcp",
    "workflows",
    "activities",
    "consumers",
    "events",
    "policies",
    "admin",
    "types",
    "urls",
    # A DISCOVERY MODULE is canonical everywhere, not per app.
    # `apps/<x>/search.py` is the filename `apps.search.registry`'s discovery
    # seam requires of EVERY adopting app (`registry.DECLARATION_MODULE`), the
    # way `events.py` above is required of every emitting app — so recording it
    # once per app in rules.yaml would re-import the one-shared-file-every-app-
    # edits collision the discovery pattern exists to avoid, and leave the
    # documented adoption path boot-refused (djb.E011) until somebody edits
    # quality/. The precedent and the argument are rule 11's `extra_modules`
    # comment about `lifecycle`, which names this promotion as the wanted fix;
    # `lifecycle` itself stays listed per app until a rung owning both files
    # moves it, so this promotion is the only shape change here.
    "search",
    # The same promotion, the same argument, one rung later (INTEG-1, P7).
    # `apps/<x>/integrations.py::register(registry)` is the filename
    # `apps.core.integrations.census` requires of EVERY app that talks to
    # something outside this process — the integrations census is DERIVED and
    # the owner's criterion on it is that a new integration reaches all four
    # surfaces with NO EDIT TO ANY LIST. Recording it per app in rules.yaml
    # would make the adoption of a no-list census require a list edit, which is
    # the criterion failing in the file that enforces it. `core` is exempt from
    # the novel-name half already and holds the primitive
    # (`apps/core/integrations.py`); this entry is for the apps that will
    # declare through it.
    "integrations",
}
BANNED_MODULES = {"utils", "helpers", "logic", "misc", "common", "lib", "managers"}

MONEY_NAMES = re.compile(r"(amount|price|cost|rate|quantity|qty|total|balance|fee)", re.IGNORECASE)


@cache
def _rules() -> dict[str, dict[str, Any]]:
    """quality/rules.yaml by rule id. Missing file → empty, and E000 says so."""
    path = Path(settings.BASE_DIR) / "quality" / "rules.yaml"
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    return {str(rule["id"]): rule for rule in loaded.get("rules", [])}


def _scope(rule_id: str) -> dict[str, Any]:
    rule = _rules().get(rule_id) or {}
    scope = rule.get("scope") or {}
    return scope if isinstance(scope, dict) else {}


def unauthenticated_url_names() -> set[str]:
    """Rule 3's allow-list: the routes that may answer without a credential.

    The single source of truth is `quality/rules.yaml`; the tests that used to
    carry their own copies (`test_introspect`, `test_api`) defer to this.
    """
    return {
        str(entry["url_name"])
        for entry in _scope("3").get("allow_unauthenticated") or []
        if entry.get("url_name")
    }


def unauthenticated_operation_ids() -> set[str]:
    """The same allow-list as OpenAPI sees it — operationIds, for contract tests."""
    return {
        str(entry["operation_id"])
        for entry in _scope("3").get("allow_unauthenticated") or []
        if entry.get("operation_id")
    }


def _local_app_configs() -> list[AppConfig]:
    return [config for config in apps.get_app_configs() if config.name.startswith("apps.")]


def _local_models() -> list[type[models.Model]]:
    return [model for config in _local_app_configs() for model in config.get_models()]


def _model_file(model: type[Any]) -> str:
    try:
        return str(Path(inspect.getfile(model)).relative_to(settings.BASE_DIR))
    except (TypeError, ValueError, OSError):
        return model.__module__


# --- rule 2: every concrete model inherits BaseModel ---------------------------


@register(DJB)
def check_model_bases(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    from apps.core.models import BaseModel

    found: list[CheckMessage] = []
    for model in _local_models():
        if model._meta.proxy:
            continue
        if not issubclass(model, BaseModel):
            found.append(
                Error(
                    f"{model._meta.label} ({_model_file(model)}) does not inherit "
                    "core.models.BaseModel — every concrete model carries the UUIDv7 pk, "
                    "created_at and updated_at (house rule 2).",
                    obj=model._meta.label,
                    id="djb.E002",
                )
            )
    return found


# --- rule 15: field policies ---------------------------------------------------


@register(DJB)
def check_field_policies(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    found: list[CheckMessage] = []
    exempt = {str(x) for x in _scope("15").get("field_exemptions") or []}
    for model in _local_models():
        for field_obj in model._meta.get_fields():
            if not isinstance(field_obj, models.Field):
                continue
            label = f"{model._meta.label}.{field_obj.name}"
            if label in exempt:
                continue
            where = f"{label} ({_model_file(model)})"
            if isinstance(field_obj, models.FloatField) and MONEY_NAMES.search(field_obj.name):
                found.append(
                    Error(
                        f"{where} is a FloatField on a money/quantity name — use "
                        "DecimalField(max_digits=19, decimal_places=4) and an ISO-4217 currency "
                        "(house rule 15).",
                        obj=label,
                        id="djb.E015",
                    )
                )
            if type(field_obj) is models.DateTimeField and not field_obj.name.endswith("_at"):
                found.append(
                    Error(
                        f"{where}: a DateTimeField's name ends `_at` (house rule 15).",
                        obj=label,
                        id="djb.E015",
                    )
                )
            if type(field_obj) is models.DateField and not field_obj.name.endswith("_on"):
                found.append(
                    Error(
                        f"{where}: a DateField's name ends `_on` (house rule 15).",
                        obj=label,
                        id="djb.E015",
                    )
                )
            if isinstance(field_obj, models.BooleanField) and field_obj.name in (
                "is_deleted",
                "deleted",
            ):
                found.append(
                    Error(
                        f"{where}: no `is_deleted` booleans — use `archived_at` if the product "
                        "needs soft deletion (house rule 15).",
                        obj=label,
                        id="djb.E015",
                    )
                )
            remote = getattr(field_obj, "remote_field", None)
            if remote is not None and getattr(remote, "on_delete", None) is models.DO_NOTHING:
                found.append(
                    Error(
                        f"{where}: on_delete=DO_NOTHING leaves dangling rows — PROTECT by default, "
                        "CASCADE only for owned children (house rule 15).",
                        obj=label,
                        id="djb.E015",
                    )
                )
    return found


# --- rule 3: every route declares auth; every list is paginated ----------------


def _bound_operations() -> list[tuple[str, Any]]:
    """(mount label, operation) straight off the live NinjaAPI registry.

    The lazy import of `config` mirrors `introspect`: reporting on what the
    mounts found is the job, and pyproject's import-linter contracts exempt
    this module by name for exactly that reason.
    """
    from config.api import api

    out: list[tuple[str, Any]] = []
    for bound in api._get_bound_routers():
        for _path, path_view in bound.path_operations.items():
            for operation in path_view.operations:
                out.append((str(bound.prefix), operation))
    return out


def answers_cursor_envelope(operation: Any) -> bool:
    """The ADR core-24 seam, reached the way this module reaches `config.api`.

    Imported inside the call rather than at the top of the file: `checks.py` is
    imported from `AppConfig.ready()`, and `apps.core.api.pagination` pulls in
    schemas and the refusal registry — a module-level import here would run that
    while the app registry is still populating. Reporting on what the mounts
    found is this module's job, which is the same reason `_bound_operations`
    imports `config.api` where it does.
    """
    from apps.core.api.pagination import answers_cursor_envelope as seam

    return seam(operation)


def offers_pagination_controls(operation: Any) -> bool:
    """The seam's other half — `?cursor=` and `?limit=`. Lazy for the same reason."""
    from apps.core.api.pagination import offers_pagination_controls as seam

    return seam(operation)


def _is_list_response(operation: Any) -> bool:
    """Every route that answers MANY of something — both shapes it can take.

    The `list[` string-match below is the BARE list: `response=list[WidgetOut]`,
    an endpoint whose cost is set by whoever has the most rows. It used to be the
    whole population, and on this tree that population is EMPTY — every list here
    already answers the cursor envelope, so `djb.E030` was enforcing nothing at
    all against the real registry while its canary went on firing against a
    planted bare list. An envelope route that gives a caller no way to ask for
    page two is exactly the ADR core-18 deviation rule 3 exists to refuse, and
    nothing saw it.

    So the population is the union, and `answers_cursor_envelope` (ADR core-24)
    is the half that reads the envelope — the same predicate the docs derivation
    and `introspect` read, so the three cannot come to disagree about which
    routes are lists.
    """
    if answers_cursor_envelope(operation):
        return True
    model = (getattr(operation, "response_models", None) or {}).get(200)
    if model is None:
        return False
    response_field = getattr(model, "model_fields", {}).get("response")
    if response_field is None:
        return False
    return "list[" in str(response_field.annotation).replace("typing.List", "list")


@register(DJB)
def check_route_auth(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    found: list[CheckMessage] = []
    allowed = unauthenticated_url_names()
    for _prefix, operation in _bound_operations():
        url_name = f"api:{operation.url_name}" if operation.url_name else None
        view = operation.view_func
        where = f"{view.__module__}.{view.__name__}"
        if not operation.auth_callbacks and url_name not in allowed:
            found.append(
                Error(
                    f"route {url_name or where} ({where}) declares no auth and is not on the "
                    "rules.yaml allow-list — every route carries an explicit auth=; the only "
                    "legitimate auth=None is a signature-verifying inbound webhook (house rule 3).",
                    obj=url_name or where,
                    id="djb.E003",
                )
            )
        if "GET" in operation.methods and _is_list_response(operation):
            if not offers_pagination_controls(operation):
                found.append(
                    Error(
                        f"list route {url_name or where} ({where}) offers no pagination "
                        "controls — an unpaginated list is a slower way to ask for "
                        "everything, and an envelope with no `?cursor=` behind it is a "
                        "`next_cursor` nobody can spend (house rule 3). Either "
                        "`@paginate(CursorPagination)` it, or take `cursor` and `limit` "
                        "and call `apps.core.api.pagination.cursor_page` yourself.",
                        obj=url_name or where,
                        id="djb.E030",
                    )
                )
    return found


# --- rule 3, third clause: the plain Django views ------------------------------
#
# The two clauses above read the live ninja
# registry, and a plain Django view is in neither registry it can see: at one
# point, `config/urls.py` mounted SIX first-party views outside the API — the
# door index, `/healthz`, `/readyz`, the RFC 9728 metadata document, `/llms.txt`
# and the JSON 404 — of which four were recorded only in a docstring somebody
# would have to go and read, and nothing refused the next unrecorded one. A view
# added at the root answers exactly as well with a reason as without one, which
# is the shape rule 41's own preamble describes: documentation decays silently.
#
# THE POPULATION IS DERIVED, and the exclusions are one mechanism rather than a
# hand list: a pattern counts when the module its callback was DEFINED in is
# under `apps.` or `config.`. That is what puts ninja's 86 operations (module
# `ninja.operation`), its three document views, `django.contrib.admin`,
# allauth's flow and every `TemplateView` outside this clause without naming any
# of them — and it is why the check unwraps `functools.partial` first: the
# `/llms.txt` mount is a bound partial, and reading the wrapper's module would
# have said `functools` and quietly dropped a first-party open view out of the
# census.
#
# It is a SET EQUALITY in both directions. A live view with no recorded reason
# is what this rule exists to catch; a recorded key with no live view is a stale
# exemption, which is the other way an allow-list rots.


def unauthenticated_view_names() -> set[str]:
    """Rule 3's second allow-list: plain Django views that answer without one.

    A separate key from `allow_unauthenticated` on purpose: that one is
    the ninja registry's and two tests assert set-equality against the live
    routes, so a Django view put in it fails both.
    """
    return {
        str(entry["url_name"])
        for entry in _scope("3").get("allow_unauthenticated_views") or []
        if entry.get("url_name")
    }


def _unwrap(view: Any) -> Any:
    """The function a URL pattern really routes to, past any `functools.partial`."""
    seen = 0
    while isinstance(view, functools.partial) and seen < 5:
        view = view.func
        seen += 1
    return view


def first_party_plain_views() -> dict[str, str]:
    """{url_name: dotted view} for every non-ninja view this deployment mounts.

    Read off `get_resolver()` — the live URL configuration, the same registry
    `reverse()` uses — so a product that mounts its own landing page is in the
    population the day it does, without editing anything here.
    """
    from django.urls import URLResolver, get_resolver

    found: dict[str, str] = {}

    def walk(resolver: URLResolver, namespace: str) -> None:
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                walk(entry, namespace + (f"{entry.namespace}:" if entry.namespace else ""))
                continue
            view = _unwrap(entry.callback)
            module = str(getattr(view, "__module__", ""))
            if not (module.startswith("apps.") or module.startswith("config.")):
                continue
            name = f"{namespace}{entry.name}" if entry.name else ""
            found[name] = f"{module}.{getattr(view, '__qualname__', view)}"

    walk(get_resolver(), "")
    return found


@register(DJB)
def check_plain_view_auth(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    found: list[CheckMessage] = []
    live = first_party_plain_views()
    recorded = unauthenticated_view_names()
    views = {
        str(entry["url_name"]): str(entry.get("view", ""))
        for entry in _scope("3").get("allow_unauthenticated_views") or []
        if entry.get("url_name")
    }
    for name, where in sorted(live.items()):
        if name in recorded:
            if views.get(name) and views[name] != where:
                found.append(
                    Error(
                        f"rule 3 records `{name}` as {views[name]} and this deployment mounts "
                        f"{where} under that name — the reason was written about a different "
                        "view (house rule 3).",
                        obj=name,
                        id="djb.E031",
                    )
                )
            continue
        found.append(
            Error(
                f"plain Django view {name or '(unnamed)'} ({where}) is mounted outside the API "
                "and is not recorded in rule 3's `allow_unauthenticated_views` — a view that "
                "answers without a credential is a decision somebody writes down, with the "
                "reason, in quality/rules.yaml. If it authenticates, it needs its own key and "
                "this clause needs the one-line amendment its does_not_cover names "
                "(house rule 3).",
                obj=name or where,
                id="djb.E031",
            )
        )
    for name in sorted(recorded - set(live)):
        found.append(
            Error(
                f"rule 3 records `{name}` in `allow_unauthenticated_views` and this deployment "
                "mounts no first-party plain view by that name — a stale exemption outlives the "
                "thing it excused and reads as a judgement somebody still holds (house rule 3).",
                obj=name,
                id="djb.E031",
            )
        )
    return found


# --- rule 17: door parity ------------------------------------------------------

_VERB_TOOLS = {
    "list": ("list_{noun}s", "list_{noun}"),
    "detail": ("get_{noun}",),
    "create": ("create_{noun}",),
    "update": ("update_{noun}", "set_{noun}"),
    "delete": ("delete_{noun}", "remove_{noun}"),
}


def _tools_by_app() -> dict[str, set[str]]:
    from config.mcp import server

    by_app: dict[str, set[str]] = {}
    # The tool manager's synchronous listing: the same registry the async
    # `list_tools` serves, without needing an event loop inside a check.
    for tool in server._tool_manager.list_tools():
        module = getattr(tool.fn, "__module__", "")
        parts = module.split(".")
        if len(parts) >= 2 and parts[0] == "apps":
            by_app.setdefault(parts[1], set()).add(tool.name)
    return by_app


@register(DJB)
def check_door_parity(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    found: list[CheckMessage] = []
    scope = _scope("17")
    exempt_apps = {str(x.get("app")) for x in scope.get("exemptions") or [] if x.get("app")}
    exempt_routes = {
        str(x.get("url_name")) for x in scope.get("exemptions") or [] if x.get("url_name")
    }
    tools = _tools_by_app()
    for _prefix, operation in _bound_operations():
        view = operation.view_func
        module_parts = str(view.__module__).split(".")
        if len(module_parts) < 3 or module_parts[0] != "apps" or module_parts[2] != "api":
            continue
        app_label = module_parts[1]
        url_name = str(operation.url_name or "")
        if (
            app_label in exempt_apps
            or url_name in exempt_routes
            or f"api:{url_name}" in exempt_routes
        ):
            continue
        noun, _, verb = url_name.rpartition("-")
        candidates = [t.format(noun=noun) for t in _VERB_TOOLS.get(verb, ())] or [
            f"{verb}_{noun}",
            f"{noun}_{verb}",
        ]
        app_tools = tools.get(app_label, set())
        if not any(c in app_tools for c in candidates):
            found.append(
                Error(
                    f"REST capability {url_name!r} (apps/{app_label}/api.py) has no MCP tool "
                    f"(looked for {', '.join(candidates)} in apps/{app_label}/mcp.py) and no "
                    "rules.yaml exemption — a capability on REST is on MCP unless exempted "
                    "with the reason (house rule 17).",
                    obj=url_name,
                    id="djb.E017",
                )
            )
    return found


# --- rule 32: the first path segment names a resource, never an app ------------
#
# ADR api-2, and the owner's ruling behind it (design-agreements.md, 2026-08-24):
# "an app label in a path is internal taxonomy on the wire". `/api/v1/core/...`
# asked every caller to learn which module of ours happens to serve a thing, in
# order to type it and then ignore it.
#
# WHY A RULE AND NOT A REVIEW. The leak has no failure mode. `PREFIX = "events"`
# answers exactly as well as `PREFIX = ""`; nothing 500s, no test goes red, and
# the cost lands on a stranger reading the document months later. Four groups
# drifted into it over five cycles with a code review on every one — and the
# ruling's own sentence says why the tripwire has to exist now rather than
# later: after the first external consumer, moving a URL is a versioning event.
#
# BOTH POPULATIONS ARE CLOSED, which is what makes this a rule at all. The app
# labels come off the app registry — every installed `apps.*` config — so an app
# added tomorrow is in the population with no edit here. The paths come off the
# live mount, so a route bound any way ninja binds one is seen. Nothing is a
# hand-list, and neither side can be quietly narrowed to make a violation pass.
#
# THE ONE VALVE, and why it is not a hole. A1 names an app as the PLURAL OF ITS
# AGGREGATE, so a domain app's label legitimately coincides with its best
# resource name — `apps/connections` serves `/connections/`, and refusing that
# would be refusing the naming convention that produced it. `allowed_label_paths`
# declares the coincidence, one entry per label with its reason, and everything
# outside it still refuses: `core`, `comms`, `events` and `workflows` are
# INFRASTRUCTURE names and never resources, which is the class this rule keeps
# catching.


def allowed_label_paths() -> set[str]:
    """Rule 32's valve: app labels that are legitimately also resource names.

    The single source of truth is `quality/rules.yaml`, like every other
    allow-list in this module — a judgement somebody wrote down, with the
    reason, in the one file the gate consistency-checks.
    """
    return {
        str(entry["label"])
        for entry in _scope("32").get("allowed_label_paths") or []
        if entry.get("label")
    }


def _mounted_paths() -> list[tuple[str, Any]]:
    """(mounted path, operation) for every bound operation — the document's paths.

    The same walk `config.api.document_api` uses to apply ADR api-1, for the
    same reason: how deeply the mount nests its routers is the mount's business,
    and the only thing that is anybody else's is the path that comes out.

    Normalised to the spelling the document shows, because this path ends up in
    a REFUSAL a person has to act on. The mount joins a prefix that already has
    its slashes to a path that has its own — `/connections/` + `/` — so the raw
    join reads `//connections///`, which is a correct answer nobody can search
    for. Segments in, one slash between, a trailing slash when the route had one.
    """
    from config.api import api

    out: list[tuple[str, Any]] = []
    for bound in api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            segments = [part for part in f"{bound.prefix}/{path}".split("/") if part]
            trailing = "/" if str(path).endswith("/") or not segments else ""
            full = "/" + "/".join(segments) + trailing
            for operation in path_view.operations:
                out.append((full, operation))
    return out


def _first_segment(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    return parts[0] if parts else ""


@register(DJB)
def check_resource_first_paths(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Refuse a mounted route whose first path segment is an installed app label.

    One finding per offending SEGMENT rather than per route: the fix is one
    `PREFIX` line, and fifty findings naming fifty routes would bury it.

    **The finding names the api module, not only the path**, and that is
    load-bearing twice. A person reading it has to know which file to edit, and
    a path alone does not say — the segment is what the mount composed, and the
    line that composed it is somewhere else. And the gate's own negative probe
    recognises a false positive by finding the PLANTED APP in the message: a
    refusal that named only the path would let a planted negative fire without
    the harness noticing, which is a negative that cannot fail.
    """
    labels = {config.label for config in _local_app_configs()}
    valved = allowed_label_paths()
    offenders: dict[str, list[str]] = {}
    modules: dict[str, set[str]] = {}
    for path, operation in _mounted_paths():
        segment = _first_segment(path)
        if segment in labels and segment not in valved:
            offenders.setdefault(segment, []).append(path)
            dotted = str(getattr(operation.view_func, "__module__", ""))
            if dotted:
                modules.setdefault(segment, set()).add(dotted.replace(".", "/") + ".py")
    found: list[CheckMessage] = []
    for segment, paths in sorted(offenders.items()):
        example = sorted(paths)[0]
        where = ", ".join(sorted(modules.get(segment, set()))) or "an api module"
        found.append(
            Error(
                f"the path segment {segment!r} is an installed app label, and "
                f"{len(paths)} mounted route(s) put it first — for example {example}, "
                f"from {where}. The first path segment names a RESOURCE, never an app: "
                'set that module\'s PREFIX to the resource (or to "" when the route '
                "paths already say it), or declare the coincidence in rules.yaml under "
                "rule 32's allowed_label_paths with the reason (ADR api-2, house "
                "rule 32).",
                obj=example,
                id="djb.E032",
            )
        )
    return found


# --- rule 21: admin goes through services --------------------------------------


@register(DJB)
def check_admin_inherits_service_admin(
    app_configs: Any = None, **kwargs: Any
) -> list[CheckMessage]:
    from django.contrib import admin

    from apps.core.admin import ServiceModelAdmin
    from apps.core.models import TenantScopedModel

    found: list[CheckMessage] = []
    for model, model_admin in admin.site._registry.items():
        if not model.__module__.startswith("apps."):
            continue
        if not issubclass(model, TenantScopedModel):
            continue
        if not isinstance(model_admin, ServiceModelAdmin):
            found.append(
                Error(
                    f"{type(model_admin).__name__} on scoped model {model._meta.label} does not "
                    "inherit core.admin.ServiceModelAdmin — a raw ModelAdmin writes with "
                    "obj.save(), skips the tenant filter, the services and the audit row "
                    "(house rule 21).",
                    obj=model._meta.label,
                    id="djb.E021",
                )
            )
    return found


# --- rule 11: the canonical file shape -----------------------------------------


@register(DJB)
def check_canonical_shape(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    found: list[CheckMessage] = []
    scope = _scope("11")
    exempt_apps = {str(x) for x in scope.get("exempt_apps") or []}
    extra = {
        str(app): {str(m) for m in mods} for app, mods in (scope.get("extra_modules") or {}).items()
    }
    for config in _local_app_configs():
        label = config.label
        app_dir = Path(config.path)
        for path in sorted(app_dir.glob("*.py")):
            stem = path.stem
            rel = str(path.relative_to(settings.BASE_DIR))
            if stem in BANNED_MODULES:
                found.append(
                    Error(
                        f"{rel}: `{stem}.py` is a name business logic hides behind — the job it "
                        "does has a canonical file (services, selectors, models, …) "
                        "(house rule 11).",
                        obj=rel,
                        id="djb.E011",
                    )
                )
                continue
            if label in exempt_apps:
                continue
            if stem in CANONICAL_MODULES or stem in extra.get(label, set()):
                continue
            found.append(
                Error(
                    f"{rel}: not a canonical module name for an app — use the canonical file "
                    "for the job, or record the extra module for this app in rules.yaml "
                    "rule 11 with the reason (house rule 11).",
                    obj=rel,
                    id="djb.E011",
                )
            )
    return found


# --- rule 13 (model half): a scoped model's writes have a policy ----------------


@register(DJB)
def check_scoped_write_policies(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    from apps.core.authz import policies
    from apps.core.models import TenantScopedModel

    found: list[CheckMessage] = []
    exempt = {str(x.get("model")) for x in _scope("13").get("policy_exemptions") or []}
    nouns = {action.split(".", 1)[0] for action in policies()}
    for model in _local_models():
        if model._meta.proxy or not issubclass(model, TenantScopedModel):
            continue
        if model._meta.abstract or model is TenantScopedModel:
            continue
        label = model._meta.label
        if label in exempt:
            continue
        name = model.__name__.lower()
        # A policy noun may write the model's name with underscores
        # (sso_connection for SsoConnection), so the comparison strips them —
        # the merge that brought SsoConnection in proved the bare suffix match
        # only passed by colliding with another app's `connection` noun.
        flats = {noun.replace("_", "") for noun in nouns}
        if not any(name == flat or name.endswith(flat) for flat in flats):
            found.append(
                Error(
                    f"scoped model {label} ({_model_file(model)}) has no write policy — no "
                    f"`{name}.*` action in any policies.py, so authz.require can only refuse; "
                    "add the app's policies.py entry or record the exemption in rules.yaml "
                    "(house rule 13).",
                    obj=label,
                    id="djb.E013",
                )
            )
    return found


# --- rule 41: the OpenAPI document is the contract, complete --------------------
#
# ADR api-1. Read off the LIVE document and the live tool registry rather than
# out of source, for the same reason rules 3 and 17 are: the contract a client
# meets is the one ninja built, and a docstring that never reached it is not
# documentation. Everything the rule requires is DERIVED by
# `apps/core/api/docs.py` and applied in `config/api.py`, so a violation here is
# one of the things a builder can fix in their own app: a route with no
# docstring, a title that is really a sentence, maintainer archaeology above the
# divider, a tag nobody described or nobody named, an `@refuses` code the
# registry does not hold, or an MCP tool that was given words of its own.
#
# THE ONE COUNT, AND WHY IT IS A RATCHET. Everything above is a closed question
# with a ceiling of zero. Declared field examples are not: 2026-08-24 declared
# the persona arc's schemas and left the rest shape-grade deliberately, so the
# census is recorded in `rules.yaml` under rule 41's scope and may shrink and
# never grow. What that buys is the thing worth having — a NEW field arriving
# with `"string"` in the published document fails the gate on the day it lands.


def _api_documentation_pass_ran(operations: list[tuple[str, Any]]) -> bool:
    """Whether `config.api.document_api()` has touched these operations at all.

    A tripwire on the pass itself: without it every route would fail this check
    for a reason no builder caused, and the report would name fifty-one innocent
    functions instead of the one import that went missing.
    """
    from apps.core.api.docs import contract_of, title_of

    for _prefix, operation in operations:
        contract = contract_of(operation.view_func)
        if contract and operation.summary == title_of(contract):
            return True
    return False


def _twin_tools() -> dict[str, Any]:
    """Every MCP tool by name, with the object that carries its description."""
    from config.mcp import server

    return {tool.name: tool for tool in server._tool_manager.list_tools()}


@register(DJB)
def check_contract_documentation(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    from apps.core.api.docs import (
        contract_of,
        declared_refusals,
        description_of,
        example_census,
        mechanical_tells,
        title_faults,
        title_of,
    )
    from apps.core.exceptions import REFUSALS
    from config.api import api

    found: list[CheckMessage] = []
    operations = _bound_operations()
    if operations and not _api_documentation_pass_ran(operations):
        return [
            Error(
                "no bound operation carries the summary its own docstring derives — "
                "`config.api.document_api()` did not run, so the OpenAPI document is "
                "ninja's defaults and not the product's contract (ADR api-1, house "
                "rule 41).",
                obj="config/api.py",
                id="djb.E041",
            )
        ]

    document = api.get_openapi_schema()
    described_tags = {
        str(entry.get("name")): str(entry.get("description") or "")
        for entry in (document.get("tags") or [])
    }
    displayed_tags = {
        str(entry.get("name")): str(entry.get("x-displayName") or "")
        for entry in (document.get("tags") or [])
    }
    tools = _twin_tools()
    exempt_apps = {str(x.get("app")) for x in _scope("17").get("exemptions") or [] if x.get("app")}
    #: Every tag any operation carries, with one route that carries it — so the
    #: finding can point at something a reader can go and look at.
    faulty_tags: dict[str, str] = {}

    for _prefix, operation in operations:
        view = operation.view_func
        where = f"{view.__module__}.{view.__name__}"
        url_name = str(operation.url_name or "")
        contract = contract_of(view)
        if not contract:
            found.append(
                Error(
                    f"route {url_name or where} ({where}) has no contract docstring, so the "
                    "OpenAPI document describes it with a prettified function name and "
                    "nothing else. The docstring IS the documentation: its first line is "
                    "the summary, everything above a `---` line is the description, and "
                    "the MCP twin renders the same half (house rule 41, ADR api-1).",
                    obj=url_name or where,
                    id="djb.E041",
                )
            )
            continue
        title = title_of(contract)
        if operation.summary != title or operation.description != description_of(contract):
            found.append(
                Error(
                    f"route {url_name or where} ({where}) carries a summary or description "
                    "that is not the one its docstring derives — a hand-written "
                    "`summary=`/`description=` is a second copy of the contract and the "
                    "first place the two doors drift (house rule 41).",
                    obj=url_name or where,
                    id="djb.E041",
                )
            )

        # The TITLE clause (the owner's ruling of 2026-08-24). A navigation
        # sidebar shows summaries, and before this check existed a summary here was the
        # opening SENTENCE — so the sidebar was a column of sentences, some of
        # them with literal `**` in them, which is what the owner was looking at
        # when he ruled. A title is a name: short, plain, no full stop.
        for fault in title_faults(title):
            found.append(
                Error(
                    f"route {url_name or where} ({where}) has a title that {fault} — the "
                    "docstring's FIRST LINE is the name this operation is listed under, "
                    f"and the sentence belongs in the paragraph below it: {title!r} "
                    "(house rule 41, ADR api-1).",
                    obj=url_name or where,
                    id="djb.E041",
                )
            )

        # The MECHANICAL-TELLS clause. The contract
        # half is what a stranger with an API key reads; these four shapes are
        # notes to a maintainer, and every one of them shipped on the wire
        # before this check existed. The rest of the plain-language bar is review's and
        # rule 41 says so in `does_not_cover`.
        for tell in mechanical_tells(contract):
            found.append(
                Error(
                    f"route {url_name or where} ({where}) publishes {tell} above the `---` "
                    "divider — the contract half is what a caller with an API key reads, "
                    "and none of that is something they can act on. Move it below the "
                    "divider, where the next maintainer will find it (house rule 41).",
                    obj=url_name or where,
                    id="djb.E041",
                )
            )

        # ONE OPERATION, ONE SECTION (owner review, 2026-08-24). A renderer
        # lists an operation under EVERY tag it carries, so a second tag is not
        # extra metadata — it is the same operation printed twice in the
        # navigation, and a reader who finds it in one place has no way to know
        # the other entry is the same thing rather than a sibling capability.
        # This is a shape and therefore gateable, unlike whether the group a tag
        # names is the right group.
        tags = [str(tag) for tag in operation.tags or []]
        if len(tags) > 1:
            found.append(
                Error(
                    f"route {url_name or where} ({where}) carries {len(tags)} tags "
                    f"({', '.join(repr(tag) for tag in tags)}) — a reader meets it once "
                    "per tag, so the whole group appears twice in the navigation. Give "
                    "it exactly one, the specific one; a parent router's tags ACCUMULATE "
                    "onto every operation beneath it, which is usually where the second "
                    "one comes from (house rule 41, ADR api-1).",
                    obj=url_name or where,
                    id="djb.E041",
                )
            )

        # A tag is a property of the GROUP, not of each route in it, so it is
        # collected here and reported once below. Reported per operation it
        # would say the same thing eleven times for one missing declaration and
        # bury the ten other findings underneath it.
        for tag in tags:
            faulty_tags.setdefault(tag, url_name or where)

        declared = declared_refusals(view)
        for code in declared or ():
            if code not in REFUSALS:
                found.append(
                    Error(
                        f"route {url_name or where} ({where}) declares `@refuses({code!r})`, "
                        "which is not in the refusal registry — the document would teach a "
                        "code the wire never speaks. Register it beside the class that "
                        "raises it (house rule 41).",
                        obj=url_name or where,
                        id="djb.E041",
                    )
                )
        responses = (operation.openapi_extra or {}).get("responses") or {}
        enumerated = [
            code
            for body in responses.values()
            for code in (body.get("x-refusal-codes") or ())
            if isinstance(body, dict)
        ]
        if not enumerated:
            found.append(
                Error(
                    f"route {url_name or where} ({where}) enumerates no refusal at all — "
                    "every route can be refused, and a document that says otherwise "
                    "teaches a client to treat one as a bug (house rule 41).",
                    obj=url_name or where,
                    id="djb.E041",
                )
            )
        for code in enumerated:
            if code not in REFUSALS:
                found.append(
                    Error(
                        f"route {url_name or where} ({where}) documents the refusal code "
                        f"{code!r}, which the registry does not hold (house rule 41).",
                        obj=url_name or where,
                        id="djb.E041",
                    )
                )

        # The one-docstring rule, across the two doors. Only for a pair that
        # exists: whether a tool SHOULD exist is house rule 17's question, and
        # answering it twice would put two rules on one finding.
        module_parts = str(view.__module__).split(".")
        if len(module_parts) >= 3 and module_parts[0] == "apps" and module_parts[2] == "api":
            if module_parts[1] in exempt_apps:
                continue
            noun, _, verb = url_name.rpartition("-")
            candidates = [t.format(noun=noun) for t in _VERB_TOOLS.get(verb, ())] or [
                f"{verb}_{noun}",
                f"{noun}_{verb}",
            ]
            for name in candidates:
                tool = tools.get(name)
                if tool is None:
                    continue
                if str(tool.description or "") != contract:
                    found.append(
                        Error(
                            f"MCP tool {name!r} describes itself differently from its REST "
                            f"twin {url_name or where} — one capability, two texts. Write "
                            f"`description=contract_of({view.__name__})` so the doors cannot "
                            "drift (house rule 41, ADR api-1).",
                            obj=name,
                            id="djb.E041",
                        )
                    )
                break

    for tag, carrier in sorted(faulty_tags.items()):
        if not described_tags.get(tag):
            found.append(
                Error(
                    f"tag {tag!r} (carried by {carrier}) has no description in "
                    "the OpenAPI document — declare it in the owning app's "
                    "`api.py` as `TAGS = {...}`, which `config/api.py` collects by "
                    "discovery. A blank heading is a group of routes nobody can tell "
                    "apart (house rule 41).",
                    obj=tag,
                    id="djb.E041",
                )
            )
        elif not displayed_tags.get(tag):
            found.append(
                Error(
                    f"tag {tag!r} (carried by {carrier}) has no display name — "
                    "declare it as `Tag('Human name', '...')` in the owning app's "
                    "`TAGS`. The wire name is a slug a client turns into a namespace; "
                    "the navigation a person reads should say what the group IS "
                    "(house rule 41, ADR api-1).",
                    obj=tag,
                    id="djb.E041",
                )
            )

    schemas = (document.get("components") or {}).get("schemas") or {}
    for name, node in schemas.items():
        if isinstance(node, dict) and "example" not in node:
            found.append(
                Error(
                    f"schema {name!r} carries no example — examples are synthesised from "
                    "each schema's own types by `apps.core.api.docs.add_examples`, so one "
                    "without is that pass having stopped covering it (house rule 41).",
                    obj=str(name),
                    id="djb.E041",
                )
            )

    # The DECLARED-EXAMPLE census, and it is a ratchet rather than a ceiling of
    # zero (the owner's ruling of 2026-08-24). A synthesised example is always
    # shaped right and never says anything: `"channel": "channel"`. Declaring
    # one is a call to `core.schemas.example(...)` on the field. 2026-08-24
    # declared the persona arc — tokens, organizations, memberships,
    # invitations, widgets, messages, endpoints, runs — and left the rest at
    # shape grade deliberately, so the number below is what that left and it may
    # only fall. What it buys is the thing that matters: a NEW undeclared field
    # pushes the count past the ratchet and fails the gate the day it lands.
    ceiling = _scope("41").get("undeclared_example_fields")
    if ceiling is not None:
        _declared, undeclared = example_census(schemas)
        if len(undeclared) > int(ceiling):
            fresh = sorted(undeclared)
            found.append(
                Error(
                    f"example census: {len(undeclared)} schema fields carry no declared "
                    f"example, past the recorded {ceiling} — a field whose example is "
                    "synthesised reads as its own type in the published document "
                    '(`"channel": "channel"`). Declare it with '
                    "`Field(..., json_schema_extra=example(...))` from `core.schemas`, or "
                    "lower another. The backlog may shrink and never grow; raising the "
                    "number in `quality/rules.yaml` is a diff a reviewer reads. Fields: "
                    + ", ".join(fresh[:20])
                    + (" ..." if len(fresh) > 20 else ""),
                    obj="quality/rules.yaml",
                    id="djb.E041",
                )
            )
    return found


# --- rule 41's other half: the document's own top-level keys --------------------
#
# Forty-seven rules cover the document's OPERATIONS and its refusal codes, and
# nothing covered the document ITSELF. Its top level is where a contract says
# which OpenAPI version it speaks, who it is, and — in `servers` — where it can
# be reached; every one of those is a thing a generated client reads before it
# reads a single route, and every one of them could appear, vanish or change
# meaning with no check anywhere noticing.
#
# `servers` is why this is worth a census rather than a shrug. It ships EMPTY
# here, and empty is correct: a template has no deploy URL, and inventing one
# would be worse than saying nothing. But "correct" and "silently empty" are not
# the same thing, and until this key was declared nobody could tell which of the
# two the template was doing. Now it is said, with the reason, in the one file
# the gate consistency-checks — which is also what makes a product that DOES
# have a URL notice the day it ships without one.
#
# Set equality, both directions, because both rots are real: an undeclared key
# is something the mount grew that nobody decided, and a declared key that is
# gone is a contract element the document stopped publishing while its reason
# went on sitting in `rules.yaml` saying it was there.


def declared_top_level_keys() -> dict[str, str]:
    """Rule 41's document census: `{key: reason}`, from `quality/rules.yaml`."""
    return {
        str(entry["key"]): str(entry.get("reason") or "")
        for entry in _scope("41").get("openapi_top_level_keys") or []
        if entry.get("key")
    }


def top_level_key_faults(document: Mapping[str, Any]) -> list[str]:
    """The two-directional diff, as sentences. Empty is the passing answer.

    Split out from the check so the vanished-key direction can be driven against
    a document that is missing one — the live mount always builds a complete
    document, so that arm would otherwise be a branch no test could reach.
    """
    declared = declared_top_level_keys()
    if not declared:
        return []
    live = set(document)
    faults = [
        f"the OpenAPI document carries a top-level key {key!r} that rule 41's "
        "`openapi_top_level_keys` census does not declare — a contract element "
        "nobody decided is a contract element nobody owns. Declare it in "
        "`quality/rules.yaml` with the reason it is there, or stop publishing it"
        for key in sorted(live - set(declared))
    ]
    faults += [
        f"rule 41 declares a top-level key {key!r} the OpenAPI document no longer "
        "carries — the reason recorded for it in `quality/rules.yaml` now describes "
        "something that is not published. Restore the key or retire its line"
        for key in sorted(set(declared) - live)
    ]
    return faults


@register(DJB)
def check_document_top_level(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    from config.api import api

    return [
        Error(f"{fault} (house rule 41, ADR api-1).", obj="quality/rules.yaml", id="djb.E042")
        for fault in top_level_key_faults(api.get_openapi_schema())
    ]


# --- the engine's own tripwire --------------------------------------------------


@register(DJB)
def check_rules_file_present(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """These checks read their allow-lists from quality/rules.yaml; without it
    every exemption silently becomes 'nothing is exempt' — say so instead."""
    if _rules():
        return []
    return [
        Error(
            "quality/rules.yaml is missing or empty — the djb checks' allow-lists and "
            "exemptions live there; without it enforcement is running blind.",
            obj="quality/rules.yaml",
            id="djb.E000",
        )
    ]
