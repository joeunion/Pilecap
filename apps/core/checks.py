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

No check in the `djb` tag touches the database; `--tag djb` runs without one.
The one exception is registered under `deploy` instead and therefore is NOT in
that tag: `djb.W054` reads a deployment's own rows, says so when it cannot, and
runs only under `manage.py check --deploy`.
"""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any, get_args

import yaml
from django.apps import AppConfig, apps
from django.conf import settings
from django.core.checks import CheckMessage, Error, Info, Warning, register
from django.db import models

from apps.core.reach import extended_scope
from apps.core.reach import road as reach_road
from apps.core.verbs import (
    HOOK_MODULES,
    TOOL_FORMS,
    UnderivableName,
    derive_tool_name,
    door_url_name,
    split_url_name,
)

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
    # comment about `lifecycle`, which names this promotion as the wanted fix.
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
    # The same promotion again, and the same argument. `apps/<x>/roles.py`
    # exposing `ROLES` is the filename `core.authz.role_declarations()`
    # requires of EVERY app that declares a role, exactly as `policies.py`
    # above is required of every app that declares a permission — and the roles
    # are the half a PRODUCT is most likely to write first. `core` is exempt
    # from this check's novel-name half, so `apps/core/roles.py` would have
    # been legal either way; what this entry buys is that a product's own
    # `apps/<x>/roles.py` is not `djb.E011` on sight, with the adoption path
    # documented and boot-refused until somebody edits `quality/`.
    "roles",
    # `apps/<x>/surfaces.py` exposing `SURFACES`, by the same promotion and the
    # same argument as `roles` above: `core.surfaces.declared()` requires the
    # filename of every app that declares a surface, and a product's first
    # customer face must not be `djb.E011` on sight.
    "surfaces",
    # The SDK's discovered page lists both (`quality/sdk/reference.py::DISCOVERED`,
    # pinned a subset of this set by `quality/tests/test_sdk_reference.py`).
    "meters",
    "lifecycle",
    # THE NOUN-VERB FAMILY'S HOOKS, by the same promotion and the same argument,
    # and DERIVED rather than typed: `core.verbs.HOOK_MODULES` is the closed tuple
    # the family's walk reads (`archive_blockers.py`, `merge_repointers.py`,
    # `importers.py`, …), so the day a hook kind joins the tuple it is canonical
    # here in the same commit. A child app registering a blocker against its
    # parent's noun is the documented adoption path, and it must not be
    # boot-refused as a novel module name.
    *HOOK_MODULES,
}
BANNED_MODULES = {"utils", "helpers", "logic", "misc", "common", "lib", "managers"}

MONEY_NAMES = re.compile(r"(amount|price|cost|rate|quantity|qty|total|balance|fee)", re.IGNORECASE)


@cache
def _rules() -> dict[str, dict[str, Any]]:
    """quality/rules.yaml by rule id; an absent file reads as no rules at all.

    No check id of its own says the file is missing: no house rule owns that
    question, and a check no rule owns is a check nothing censuses. An empty
    answer makes every allow-list here read as "nothing is exempt", so a
    missing file reds the checks that carry exemptions rather than passing them.
    """
    path = Path(settings.BASE_DIR) / "quality" / "rules.yaml"
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    return {str(rule["id"]): rule for rule in loaded.get("rules", [])}


def _scope(rule_id: str) -> dict[str, Any]:
    """A rule's scope, its product-reachable lists joined by the drawer's (`apps.core.reach`)."""
    rule = _rules().get(rule_id) or {}
    if not isinstance(rule.get("scope") or {}, dict):
        return {}
    return extended_scope(Path(settings.BASE_DIR), rule)


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


def field_name_policy(field_class: type[models.Field[Any, Any]], name: str) -> str | None:
    """Rule 15's sentence a field of `field_class` named `name` breaks, or None when it keeps it."""
    if field_class is models.DateTimeField and not name.endswith("_at"):
        return "a DateTimeField's name ends `_at` (house rule 15)."
    if field_class is models.DateField and not name.endswith("_on"):
        return "a DateField's name ends `_on` (house rule 15)."
    if issubclass(field_class, models.BooleanField) and name in ("is_deleted", "deleted"):
        return (
            "no `is_deleted` booleans — use `archived_at` if the product needs soft deletion "
            "(house rule 15)."
        )
    return None


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
            if broken := field_name_policy(type(field_obj), field_obj.name):
                found.append(Error(f"{where}: {broken}", obj=label, id="djb.E015"))
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
    """(mounted path, operation) for every operation the live API mounts.

    Read through `apps.core.api.mount.bound_operations`, the one mount reader,
    imported inside the call: this module is imported from `AppConfig.ready()`,
    and the mount reader imports `config.api` where it does.
    """
    from apps.core.api.mount import bound_operations

    return [(path, operation) for path, _name, operation in bound_operations()]


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
                    "legitimate auth=None is a signature-verifying inbound webhook, or a route "
                    "recorded in `allow_unauthenticated` with the reason it is open; "
                    f"{reach_road('3')} (house rule 3).",
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


def authenticated_view_names() -> set[str]:
    """Rule 3's third key: plain Django views that DEMAND a credential.

    THE ONE-LINE AMENDMENT rule 3's `does_not_cover` named in advance, arriving
    with the view that triggered it. The clause cannot tell an authenticated
    plain view from an open one — there is no `auth=` on a Django view to read
    and no registry that knows — so it demanded that every first-party plain
    view be recorded, and until now every one of them was genuinely open and one
    key was enough. `apps.core.views.welcome` is the first that is not: it is
    `@login_required`, an anonymous request to it is a redirect, and putting it
    in `allow_unauthenticated_views` would have recorded a reason that is false.

    A separate key rather than a flag on the existing entries, for the reason
    the existing entries are separate from the ninja allow-list: the two
    populations are asserted about differently, the reasons answer different
    questions ("why may anybody read this" against "what does this demand"), and
    a name in both keys is itself a finding.
    """
    return {
        str(entry["url_name"])
        for entry in _scope("3").get("authenticated_views") or []
        if entry.get("url_name")
    }


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
    open_names = unauthenticated_view_names()
    credentialed = authenticated_view_names()
    recorded = open_names | credentialed
    views = {
        str(entry["url_name"]): str(entry.get("view", ""))
        for key in ("allow_unauthenticated_views", "authenticated_views")
        for entry in _scope("3").get(key) or []
        if entry.get("url_name")
    }
    for name in sorted(open_names & credentialed):
        found.append(
            Error(
                f"rule 3 records `{name}` in BOTH `allow_unauthenticated_views` and "
                "`authenticated_views` — a view either demands a credential or it does not, "
                "and two reasons for one view means one of them is now false (house rule 3).",
                obj=name,
                id="djb.E031",
            )
        )
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
                "and is recorded in neither of rule 3's plain-view keys — put it in "
                "`allow_unauthenticated_views` with the reason it may be read without a "
                "credential, or in `authenticated_views` with what it demands. Which of the two "
                f"it is is a decision somebody writes down; {reach_road('3')} (house rule 3).",
                obj=name or where,
                id="djb.E031",
            )
        )
    for name in sorted(recorded - set(live)):
        found.append(
            Error(
                f"rule 3 records `{name}` in its plain-view keys and this deployment mounts no "
                "first-party plain view by that name — a stale entry outlives the thing it "
                "described and reads as a judgement somebody still holds (house rule 3).",
                obj=name,
                id="djb.E031",
            )
        )
    return found


# --- rule 17: door parity ------------------------------------------------------

#: A VIEW of `apps.core.verbs.TOOL_FORMS` — the one table — kept only because
#: the self-test's negative fixture `quality/negative/17/paired_tool.py` imports
#: this name to name its probe tools. Nothing in this module reads it: rule 17
#: and rule 41 ask `derive_tool_name`. It goes when that fixture asks the
#: derivation instead.
_VERB_TOOLS: dict[str, tuple[str, ...]] = {
    verb: (form.replace("{plural}", "{noun}s"),) for verb, form in TOOL_FORMS.items()
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
    from apps.core.mcp import twin_of
    from config.mcp import server

    tools = _tools_by_app()
    tools_by_name = {tool.name: tool for tool in server._tool_manager.list_tools()}
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
        try:
            expected = derive_tool_name(url_name)
        except UnderivableName as refused:
            found.append(Error(f"{refused} (house rule 17).", obj=url_name, id="djb.E017"))
            continue
        app_tools = tools.get(app_label, set())
        if expected in app_tools:
            continue
        # A twin by the contract it publishes (`twin_of`, rule 41's identity) is
        # still the capability on the machine door — its NAME differing from the
        # derivation is `apps/core/tests/test_tool_names.py`'s census, which names
        # every such pair and pins the list so it can only shrink.
        twin = twin_of(operation, tools_by_name.values())
        if twin is not None and twin.name in app_tools:
            continue
        found.append(
            Error(
                f"REST capability {url_name!r} (apps/{app_label}/api.py) has no MCP tool "
                f"(looked for {expected!r}, the name its url_name derives, in "
                f"apps/{app_label}/mcp.py) and no rules.yaml exemption — a capability on REST "
                "is on MCP unless exempted with the reason (house rule 17).",
                obj=url_name,
                id="djb.E017",
            )
        )
    return found


# --- rule 74: a noun that declares a family marker carries the whole road -------
#
# The noun-verb family's one rule, over one table: `core.verbs.ROADS` says which
# routes each marker demands, and this check reads the live ninja registry for
# them. A noun that declared `Archivable` and drew only half the road — an
# archive with no restore, a restore with no `ArchivedOut` on its answer, a list
# nobody can ask for the archived cut of — is a half-built noun, and the half
# that is missing is the half a person needs on the day they need it. Its MCP
# twins are rule 17's question, derived from the same `url_name`s, so the two
# rules together demand both doors without either restating the other.
#
# BOTH POPULATIONS ARE CLOSED: the nouns are the model registry's declared
# markers (`verbs.declared_models`), the routes are the live mount. Nothing here
# is a list.

#: The `url_name` verbs whose 200 answers the noun itself — each must be an
#: `ArchivedOut` for an archivable noun, so a face can draw the band from any of
#: them.
_ANSWERS_THE_NOUN = ("detail", "archive", "restore")


def _response_schema(operation: Any) -> Any:
    """The schema a route answers on success (200, else 201), or None."""
    for status in (200, 201):
        model = (getattr(operation, "response_models", None) or {}).get(status)
        if model is None:
            continue
        field = getattr(model, "model_fields", {}).get("response")
        return getattr(field, "annotation", None)
    return None


def _offers_query(operation: Any, name: str) -> bool:
    """Whether a route accepts `?<name>=` — the `takes_query` road, reached lazily.

    The body lives once, in `apps.core.api.query.offers_query`; imported inside
    the call for `answers_cursor_envelope`'s reason (this module is imported
    from `AppConfig.ready()`, and `apps.core.api` pulls in the routes).
    """
    from apps.core.api.query import offers_query

    return offers_query(operation, name)


def _list_names(noun: str) -> set[str]:
    """The `url_name`s a noun's list may carry — the `pluralize` road's forms, as a set."""
    from apps.core.verbs import _list_forms

    return set(_list_forms(noun))


def _body_schemas(operation: Any) -> list[Any]:
    """The request-body schemas a route takes (ninja's body param models, unwrapped)."""
    from pydantic import BaseModel

    found: list[Any] = []
    for param_model in getattr(operation, "models", None) or []:
        if getattr(param_model, "__ninja_param_source__", None) != "body":
            continue
        for field in getattr(param_model, "model_fields", {}).values():
            annotation = getattr(field, "annotation", None)
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                found.append(annotation)
    return found


def _requires(schema: Any, name: str) -> bool:
    field = getattr(schema, "model_fields", {}).get(name)
    return field is not None and field.is_required()


def _versioned_findings(model: Any, noun: str, operations: dict[str, Any]) -> list[CheckMessage]:
    """A `Versioned` noun's writes that edit it carry `version` REQUIRED; its answer carries it."""
    found: list[CheckMessage] = []
    label = model._meta.label
    for verb in ("update", "move", "merge"):
        door = door_url_name(model, verb, noun)
        operation = operations.get(door)
        if operation is None:
            continue
        bodies = _body_schemas(operation)
        if not any(_requires(schema, "version") for schema in bodies):
            names = ", ".join(getattr(s, "__name__", str(s)) for s in bodies) or "no body"
            found.append(
                Error(
                    f"`{door}` takes {names}, which does not REQUIRE `version`: {label} "
                    "is `Versioned`, so every write that edits it names the version it was "
                    "made against — inherit `core.schemas.VersionedIn` (house rule 74).",
                    obj=door,
                    id="djb.E074",
                )
            )
        schema = _response_schema(operation)
        if not (isinstance(schema, type) and "version" in getattr(schema, "model_fields", {})):
            found.append(
                Error(
                    f"`{door}` answers {getattr(schema, '__name__', schema)!r}, which "
                    f"carries no `version`: {label} is `Versioned`, so the answer hands back "
                    "the version the next write names — inherit `core.schemas.VersionedOut` "
                    "(house rule 74).",
                    obj=door,
                    id="djb.E074",
                )
            )
    return found


def _bulk_findings(model: Any, noun: str, operations: dict[str, Any]) -> list[CheckMessage]:
    """Every verb a noun lists in `bulk_verbs` has its own single road."""
    found: list[CheckMessage] = []
    for verb in getattr(model, "bulk_verbs", ()) or ():
        door = door_url_name(model, verb, noun)
        if door not in operations:
            found.append(
                Error(
                    f"{model._meta.label} lists {verb!r} in `bulk_verbs` and has no "
                    f"`{door}` route: a bulk verb runs the noun's OWN single verb per "
                    "item, so the single road comes first (house rule 74).",
                    obj=door,
                    id="djb.E074",
                )
            )
    return found


def _system_policy_findings(model: Any, noun: str) -> list[CheckMessage]:
    """An archivable noun's archive and restore keys carry a `@refuses_system` policy.

    Without the pair the keys have no predicate, so `allows` step 1 waves the
    system actor through and a workflow may archive a person's row on its own
    say-so — the exemption the archive road exists to close.
    """
    from apps.core.authz import policies, refusing_system

    registry = policies()
    refusing = refusing_system()
    found: list[CheckMessage] = []
    for verb in ("archive", "restore"):
        action = f"{noun}.{verb}"
        predicate = registry.get(action)
        if predicate is None or predicate not in refusing:
            has = (
                "no policy"
                if predicate is None
                else "a policy that did not declare `@refuses_system`"
            )
            found.append(
                Error(
                    f"{model._meta.label} is archivable and `{action}` has {has}: "
                    "the system actor would be waved through. Declare the pair in the app's "
                    f'`policies.py` — `POLICIES = {{"{noun}.archive": may_archive, '
                    f'"{noun}.restore": may_archive}}` (`core.policies.may_archive`) '
                    "(house rule 74).",
                    obj=action,
                    id="djb.E074",
                )
            )
    return found


def _no_body_findings(model: Any, noun: str, operations: dict[str, Any]) -> list[CheckMessage]:
    """An archivable noun's archive and restore routes take NO body.

    The press is the whole request: a route that declares a body — even an
    empty `{}` one — answers 422 to a bodiless press, a door disagreement with
    every other adopter, and publishes `invalid_body` for a refusal nothing can
    earn.
    """
    found: list[CheckMessage] = []
    for verb in ("archive", "restore"):
        door = door_url_name(model, verb, noun)
        operation = operations.get(door)
        if operation is None:
            continue
        bodies = _body_schemas(operation)
        if bodies:
            names = ", ".join(getattr(schema, "__name__", str(schema)) for schema in bodies)
            found.append(
                Error(
                    f"`{door}` takes a body ({names}): {model._meta.label} is "
                    "archivable, and its archive and restore routes take none — the press "
                    "is the whole request, and a body turns a bodiless press into a 422 "
                    "(house rule 74).",
                    obj=door,
                    id="djb.E074",
                )
            )
    return found


def _merge_fk_findings(model: Any, noun: str) -> list[CheckMessage]:
    """Every foreign key INTO a mergeable noun is re-pointed or declared kept.

    The population is the ORM's own relation registry, hidden relations
    included (a `related_name="+"` FK still names the loser after a merge):
    each is either re-pointed by its owning app's `merge_repointers.py`
    (`REPOINTERS[noun]`) or listed in the noun's `merge_keeps` — by reverse
    accessor or by `app.Model.field` — with the reason it stays on the loser.
    """
    from apps.core.verbs import hook

    repointing_apps = {
        config.label for config, declared in hook("merge_repointers") if noun in declared
    }
    keeps: dict[str, str] = dict(getattr(model, "merge_keeps", {}) or {})
    found: list[CheckMessage] = []
    for relation in model._meta.get_fields(include_hidden=True):
        if not getattr(relation, "auto_created", False) or getattr(relation, "concrete", True):
            continue
        field = getattr(relation, "field", None)
        related = getattr(relation, "related_model", None)
        if field is None or related is None or getattr(field, "many_to_many", False):
            continue
        if related is model and field.name in ("merged_into", "duplicated_from"):
            continue
        where = f"{related._meta.label}.{field.name}"
        accessor = relation.get_accessor_name() if not relation.hidden else None
        if where in keeps or (accessor is not None and accessor in keeps):
            continue
        if related._meta.app_label in repointing_apps:
            continue
        found.append(
            Error(
                f"{where} points at {model._meta.label}, which is mergeable, and nothing "
                f"re-points it or keeps it: declare `REPOINTERS[{noun!r}]` in "
                f"apps/{related._meta.app_label}/merge_repointers.py, or list it in "
                f"`{model.__name__}.merge_keeps` with the reason it stays on the loser "
                "(house rule 74).",
                obj=where,
                id="djb.E074",
            )
        )
    return found


def _duplicate_findings(model: Any, noun: str) -> list[CheckMessage]:
    """Every concrete editable field is in `copies` or `resets` — a closed question."""
    from apps.core.verbs import duplicate_fields, owned_children

    declared = getattr(model, "duplicate", None)
    copies = tuple(getattr(declared, "copies", ()) or ())
    resets = tuple(getattr(declared, "resets", ()) or ())
    classified = set(copies) | set(resets)
    children = set(owned_children(model))
    fields = duplicate_fields(model)
    door = door_url_name(model, "duplicate", noun)
    found: list[CheckMessage] = []
    for name in fields:
        if name not in classified:
            found.append(
                Error(
                    f"{model._meta.label}.{name} is neither copied nor reset by "
                    f"`{model.__name__}.duplicate`: a duplicate must say which side every "
                    "field is on — add it to `copies` or `resets` (house rule 74).",
                    obj=door,
                    id="djb.E074",
                )
            )
    for name in sorted(classified - set(fields) - children):
        found.append(
            Error(
                f"`{model.__name__}.duplicate` names {name!r}, which is not a field of "
                f"{model._meta.label} it could copy or reset, nor an owned child "
                "(house rule 74).",
                obj=door,
                id="djb.E074",
            )
        )
    return found


def _attach_findings(operations: dict[str, Any]) -> list[CheckMessage]:
    """A noun that takes tags answers them: its detail's `Out` carries `tags`.

    The population is every model declaring `tags` in `attachments` — a
    declaration, whatever other marker the noun carries.
    """
    from apps.core.authz import kind_of
    from apps.core.verbs import declared_models

    found: list[CheckMessage] = []
    for model in declared_models("attachments"):
        if model._meta.abstract or "tags" not in tuple(model.attachments or ()):  # type: ignore[attr-defined]
            continue
        noun = kind_of(model)
        door = door_url_name(model, "detail", noun) if noun else ""
        operation = operations.get(door) if noun else None
        if operation is None:
            continue
        schema = _response_schema(operation)
        if isinstance(schema, type) and "tags" in getattr(schema, "model_fields", {}):
            continue
        found.append(
            Error(
                f"`{door}` answers {getattr(schema, '__name__', schema)!r}, which "
                f"carries no `tags`: {model._meta.label} lists `tags` in `attachments`, so "
                "the record answers the words on it (house rule 74).",
                obj=door,
                id="djb.E074",
            )
        )
    return found


def _importer_findings(operations: dict[str, Any]) -> list[CheckMessage]:
    """Every `IMPORTERS` key names a noun with a create road — an import is creates."""
    from apps.core.authz import kind_registry
    from apps.core.verbs import hook

    found: list[CheckMessage] = []
    kinds = kind_registry()
    for config, declared in hook("importers"):
        for noun in declared:
            door = door_url_name(kinds.get(noun), "create", noun)
            if door in operations:
                continue
            found.append(
                Error(
                    f"apps/{config.label}/importers.py imports {noun!r} and there is no "
                    f"`{door}` route: an import applies the noun's own creates, so "
                    "the single create road comes first (house rule 74).",
                    obj=door,
                    id="djb.E074",
                )
            )
    return found


def _bare_archived_at_findings() -> list[CheckMessage]:
    """A field named `archived_at` on a class that never declared `Archivable`.

    A hand-built archive half: the list hides nothing (`for_tenant()` only
    hides what the mixin declared), no restore road is demanded, and the face
    draws a band for a state nothing enforces.
    """
    from django.apps import apps as django_apps

    from apps.core.models import ARCHIVED_AT, is_archivable

    found: list[CheckMessage] = []
    for model in django_apps.get_models():
        if model._meta.abstract or not model.__module__.startswith("apps."):
            continue
        if is_archivable(model):
            continue
        if any(field.name == ARCHIVED_AT for field in model._meta.concrete_fields):
            found.append(
                Error(
                    f"{model._meta.label} ({_model_file(model)}) carries `{ARCHIVED_AT}` and "
                    "never declared `Archivable`: declare the mixin "
                    "(`class Noun(OrgScopedModel, Archivable)`) so the book hides what it "
                    "archives and the road is demanded (house rule 74).",
                    obj=model._meta.label,
                    id="djb.E074",
                )
            )
    return found


def _marker_word(marker: str) -> str:
    """The marker as a reader names it: `*` is "a family marker"."""
    from apps.core.verbs import ANY_MARKER

    return "a family marker" if marker == ANY_MARKER else marker


@register(DJB)
def check_noun_verb_roads(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Rule 74. Every family marker a noun declares brings its whole road."""
    from apps.core.authz import kind_of, vocabulary
    from apps.core.schemas import ArchivedOut
    from apps.core.verbs import ROADS, road_population

    words = _derived_or_none(vocabulary)
    if words is None:
        return []
    operations = {
        str(operation.url_name or ""): operation for _prefix, operation in _bound_operations()
    }
    found: list[CheckMessage] = []
    for family_verb, road in ROADS.items():
        for model in road_population(road):
            if model._meta.abstract or not model.__module__.startswith("apps."):
                continue
            label = model._meta.label
            noun = kind_of(model)
            if noun is None:
                found.append(
                    Error(
                        f"{label} ({_model_file(model)}) declares `{road.marker}` and opted "
                        "out of the vocabulary (`authz_kind = None`), so its "
                        f"{family_verb} road has no key to authorize and no noun to route "
                        "(house rule 74).",
                        obj=label,
                        id="djb.E074",
                    )
                )
                continue
            demanded = road.url_names(noun, model)
            for url_name in demanded:
                if url_name not in operations:
                    found.append(
                        Error(
                            f"{label} ({_model_file(model)}) declares "
                            f"`{_marker_word(road.marker)}` and has no `{url_name}` route: the "
                            f"{family_verb} road is {', '.join(demanded)}, both doors "
                            "(rule 17 derives the MCP twin from the same url_name) "
                            "(house rule 74).",
                            obj=url_name,
                            id="djb.E074",
                        )
                    )
            for verb in road.grants:
                action = f"{noun}.{verb}"
                if action not in words:
                    found.append(
                        Error(
                            f"{label} declares `{road.marker}` and the vocabulary holds no "
                            f"`{action}` — the derivation stopped reading the road "
                            "(house rule 74).",
                            obj=action,
                            id="djb.E074",
                        )
                    )
            if road.marker == "versioned":
                found.extend(_versioned_findings(model, noun, operations))
            if road.marker == "bulk_verbs":
                found.extend(_bulk_findings(model, noun, operations))
            if road.marker == "mergeable":
                found.extend(_merge_fk_findings(model, noun))
            if road.marker == "duplicable":
                found.extend(_duplicate_findings(model, noun))
            if road.marker != "archivable":
                continue
            found.extend(_system_policy_findings(model, noun))
            found.extend(_no_body_findings(model, noun, operations))
            for verb in _ANSWERS_THE_NOUN:
                door = door_url_name(model, verb, noun)
                operation = operations.get(door)
                if operation is None:
                    continue
                schema = _response_schema(operation)
                if not (isinstance(schema, type) and issubclass(schema, ArchivedOut)):
                    found.append(
                        Error(
                            f"`{door}` answers {getattr(schema, '__name__', schema)!r}, "
                            f"which does not subclass `ArchivedOut`: {label} is archivable, so "
                            "every answer that is the noun carries `archived_at` and "
                            "`archived_by` — the archived face's band reads them "
                            "(house rule 74).",
                            obj=door,
                            id="djb.E074",
                        )
                    )
            for list_name in sorted(_list_names(noun) & set(operations)):
                if not _offers_query(operations[list_name], "show"):
                    found.append(
                        Error(
                            f"`{list_name}` takes no `?show=`: {label} is archivable, so its "
                            "list is the live book by default and `?show=archived` is the one "
                            "reader of the archived cut (`archived_only()`) "
                            "(house rule 74).",
                            obj=list_name,
                            id="djb.E074",
                        )
                    )
    found.extend(_importer_findings(operations))
    found.extend(_attach_findings(operations))
    found.extend(_bare_archived_at_findings())
    return found


# --- rule 85: every surface declaration is a closed question over the tree -----
#
# A surface (`apps/core/surfaces.py`) is a host and what it exposes, declared by
# an app in its `surfaces.py`. Every field names members of a population the
# tree already declares — a family is a `TAGS` key, a role a `roles.py` key, an
# act a verb, a screen a route-table row — so a word nobody declared is a
# door that answers nothing, a role nobody can hold, a button nobody offers,
# a page the face never draws. Nothing on the wire refuses it: the declaration
# is accepted as written and the surface is quietly narrower than it reads.
#
# THE TWO COLLISIONS ARE THE SEAM'S OWN SENTENCES. Two apps declaring one key
# and one role on two surfaces are refused by `core.surfaces.union` the first
# time the map is read; this check feeds it the declarations one at a time, so
# every collision is reported (not only the first), in the seam's words, and
# the boot refusal stays behind it. The populations are read through their own
# roads: `families()`, `role_declarations()`, the vocabulary and `ROADS`, and
# the route table through house rule 71's reader.


def _surface_field_findings(
    where: str, key: str, field: str, members: Any, known: frozenset[str] | None, what: str
) -> list[CheckMessage]:
    """One `djb.E085` per member of a declared field that its population does not hold."""
    from apps.core.surfaces import named

    if known is None:
        return []
    return [
        Error(
            f"{where} declares the surface {key!r}; its {field} name {member!r}, which {what} "
            "— every field of a surface is a closed question over the tree (house rule 85).",
            obj=f"{where}::{key}",
            id="djb.E085",
        )
        for member in sorted((named(members) or frozenset()) - known)
    ]


@register(DJB)
def check_surfaces(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Rule 85. Every surface declaration is a closed question over the tree."""
    from django.core.exceptions import ImproperlyConfigured

    from apps.core import surfaces
    from apps.core.api.mount import route_table_paths
    from apps.core.api.scopes import families
    from apps.core.authz import role_declarations, vocabulary
    from apps.core.discovery import declared as discover
    from apps.core.verbs import ROADS

    module, attribute = surfaces.DECLARATION_MODULE, surfaces.DECLARATION_ATTRIBUTE
    try:
        found = discover(module, attribute, refuse_shape=True)
    except ImproperlyConfigured as refused:
        return [Error(f"{str(refused).rstrip('.')} (house rule 85).", obj=attribute, id="djb.E085")]
    messages: list[CheckMessage] = []
    # One declaration at a time through the seam's own union, so every
    # collision is refused in its words, not only the first.
    accepted: list[tuple[Any, dict[Any, Any]]] = []
    # A REFUSED declaration still claims its key. It stands in the union as a
    # surface admitting no role — so it can collide only by key — and a second
    # app declaring the same key is refused on this pass, in the seam's words,
    # rather than accepted until somebody fixes the first finding.
    claimed: list[tuple[Any, dict[Any, Any]]] = []
    for config, declared_here in found:
        for key, surface in declared_here.items():
            one = (config, {key: surface})
            try:
                surfaces.union([*accepted, *claimed, one])
            except ImproperlyConfigured as refused:
                where = f"apps/{config.label}/{module}.py"
                messages.append(
                    Error(
                        f"{where}: {str(refused).rstrip('.')} (house rule 85).",
                        obj=f"{where}::{key}",
                        id="djb.E085",
                    )
                )
                taken = {str(k) for _, held in (*accepted, *claimed) for k in held}
                claims = (
                    isinstance(surface, surfaces.Surface)
                    and surfaces.SURFACE_KEY.match(str(key)) is not None
                    and str(key) not in taken
                )
                if claims:
                    claimed.append((config, {key: replace(surface, roles=frozenset(), key="")}))
                continue
            accepted.append(one)
    words = _derived_or_none(vocabulary)
    roles = _derived_or_none(role_declarations)
    screens = route_table_paths()
    populations = (
        ("families", frozenset(families()), "no app's `TAGS` declares"),
        ("roles", None if roles is None else frozenset(roles), "no app's `roles.py` declares"),
        (
            "acts",
            None if words is None else frozenset(p.verb for p in words.values()) | set(ROADS),
            "is no verb of the permission vocabulary and no family road",
        ),
        (
            "screens",
            frozenset() if screens is None else screens,
            "no row of the face's route table carries"
            + (" (this tree has no route table)" if screens is None else ""),
        ),
    )
    for config, declaration in accepted:
        ((key, surface),) = declaration.items()
        where = f"apps/{config.label}/{module}.py"
        for field, known, what in populations:
            members = getattr(surface, field)
            messages.extend(_surface_field_findings(where, str(key), field, members, known, what))
    declared = surfaces.union(accepted)
    for bound in sorted(getattr(settings, "SURFACE_HOSTS", None) or {}):
        if bound not in declared:
            messages.append(
                Error(
                    f"SURFACE_HOSTS binds the surface {bound!r}, which no app declares — the "
                    f"declared ones are {', '.join(sorted(declared))}; a host bound to a surface "
                    "nobody declared answers nothing (house rule 85).",
                    obj="SURFACE_HOSTS",
                    id="djb.E085",
                )
            )
    return messages


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


def _module_file(dotted: str) -> str:
    """The file a dotted module path names, spelled the way a person opens it.

    `apps.djb_notes.schemas` → `apps/djb_notes/schemas.py`. The mount's refusals
    name files rather than modules because the fix is an edit, and one spelling
    here keeps rule 32's and rule 83's sentences naming a file the same way.
    """
    return dotted.replace(".", "/") + ".py"


def _mounted_paths() -> list[tuple[str, Any]]:
    """(mounted path, operation) for every bound operation — the document's paths.

    The path `apps.core.api.mount.bound_operations` spells — the one the
    document shows, because it ends up in a REFUSAL a person has to act on.
    """
    return _bound_operations()


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
                modules.setdefault(segment, set()).add(_module_file(dotted))
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


# --- rule 83: one app per path, one app per family ----------------------------
# The mount (`config/api.py`) binds each discovered router under its `PREFIX`
# or its label and asks nobody whether the path is taken: django-ninja 1.6.3
# refuses NOTHING on a duplicate. Two modules binding one path give one URL
# pattern per module, Django's resolver answers with whichever was discovered
# first — for every method, so a method only the later module binds answers
# 405 — and the published document describes the other. Nothing 500s and no
# test goes red; a product that grows its own `notes` app beside a platform
# app mounted at `/notes/` simply stops answering, silently.
#
# WHAT COLLIDES, READ OFF THE MECHANISM rather than off the word "prefix".
# Seven routers share the root prefix "" and answer side by side, so a guard on
# the prefix would refuse the tree itself. What collides is ONE PATH PATTERN
# bound by TWO MODULES — compared with the parameter names erased, because
# `/x/{a}/` and `/x/{b}/` are one Django pattern — and ONE TAG KEY declared by
# TWO APPS, because a tag is a scope family and one key across two apps is one
# token ceiling that reaches both.
#
# AND TWO THINGS THE KEY DOES NOT SEE, both measured on the published document.
# ONE DISPLAY TITLE CARRIED BY TWO APPS' KEYS: the mount emits each key's
# `Tag.display` as its heading and compares none, so `djb_notes` and a
# product's `probe_notes` both titled "Notes" are two families under one
# heading a reader cannot tell apart. ONE SCHEMA NAME DEFINED BY TWO MODULES:
# django-ninja publishes one component per class `__name__` and neither raises
# nor mangles on a second, so the class discovered last describes every route
# of both apps. A scope family is a `TAGS` key and nothing else
# (`apps/core/api/scopes.py`, `families()`), so there is no third "family"
# clause to hold: two keys are two families by construction.
#
# ALL FOUR POPULATIONS ARE CLOSED: the paths off the live mount
# (`_mounted_paths`), the tags and their display titles off each app's `TAGS`
# (the same discovery the scope census reads) and each bound operation's own
# tags, the schema classes off each bound operation's request and response
# models. No hand list, no valve — the shape is corrected, or one of the two
# apps takes a word of its own.


def _path_pattern(path: str) -> str:
    """The pattern a mounted path binds, parameter names erased."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def _app_label_of(dotted: str) -> str:
    config = apps.get_containing_app_config(dotted)
    return str(config.label) if config is not None else dotted


def _schema_classes(annotation: Any, into: set[type]) -> None:
    """Add every Pydantic class `annotation` reaches, nested fields included.

    A route's request and response models are ninja's wrappers around the
    classes an app wrote (`response: list[NoteOut]`), and the document publishes
    a component for each class those reach — so the walk follows `list[...]`,
    `X | None` and every nested field until it has seen each class once.
    """
    from pydantic import BaseModel

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in into:
            return
        into.add(annotation)
        for field in annotation.model_fields.values():
            _schema_classes(field.annotation, into)
        return
    for argument in get_args(annotation):
        _schema_classes(argument, into)


def _display_title_findings() -> list[CheckMessage]:
    """Refuse one `Tag.display` carried by the keys of two apps, naming every key.

    The heading is what a reader of the document meets, human or agent; two
    families under one heading are one section describing either. A bare-string
    `TAGS` entry has no display (rule 41's finding) and is skipped here.
    """
    from apps.core.api.scopes import _tag_declarations_by_app

    carriers: dict[str, set[tuple[str, str]]] = {}
    for label, declared in _tag_declarations_by_app().items():
        for key, entry in declared.items():
            display = str(getattr(entry, "display", "") or "")
            if display:
                carriers.setdefault(display, set()).add((key, label))
    found: list[CheckMessage] = []
    for display, keys in sorted(carriers.items()):
        if len({label for _, label in keys}) < 2:
            continue
        sides = " and ".join(f"{key!r} (apps/{label})" for key, label in sorted(keys))
        found.append(
            Error(
                f"the display title {display!r} is carried by tag keys {sides}; one word "
                "for two families is one heading a reader cannot tell apart — give the "
                "newer one a display of its own (house rule 83).",
                obj=display,
                id="djb.E083",
            )
        )
    return found


def _schema_name_findings(operations: list[Any]) -> list[CheckMessage]:
    """Refuse one schema class name defined by two modules, naming both files.

    The population is every class an installed app defines that a bound
    operation's request or response models reach; ninja's own generated
    wrappers belong to no app and are not in it.
    """
    reached: set[type] = set()
    for operation in operations:
        roots = [*(operation.models or ()), *(operation.response_models or {}).values()]
        for root in roots:
            _schema_classes(root, reached)
    defined: dict[str, set[str]] = {}
    for cls in reached:
        if apps.get_containing_app_config(cls.__module__) is not None:
            defined.setdefault(cls.__name__, set()).add(cls.__module__)
    found: list[CheckMessage] = []
    for name, modules in sorted(defined.items()):
        if len(modules) < 2:
            continue
        files = " and ".join(_module_file(dotted) for dotted in sorted(modules))
        found.append(
            Error(
                f"the schema name {name!r} is defined by {files}; django-ninja publishes "
                "ONE component under that name and describes both apps' routes by "
                "whichever was discovered last — rename one (house rule 83).",
                obj=name,
                id="djb.E083",
            )
        )
    return found


@register(DJB)
def check_one_app_per_path_and_family(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Refuse two owners of one path, tag key, display title or schema name.

    One finding per path pattern, per tag key, per display title and per schema
    name, each naming BOTH sides — the modules for a path or a schema, the apps
    for a tag or a title — for the reason rule 32's finding names its module: a
    person has to know which file to edit, and the gate's negative probe
    recognises a false positive by the planted app's name.
    """
    from apps.core.api.scopes import _tag_declarations_by_app

    bound: dict[str, dict[str, set[str]]] = {}
    spelled: dict[str, str] = {}
    tag_apps: dict[str, set[str]] = {}
    operations: list[Any] = []
    for path, operation in _mounted_paths():
        operations.append(operation)
        dotted = str(getattr(operation.view_func, "__module__", ""))
        pattern = _path_pattern(path)
        spelled.setdefault(pattern, path)
        methods = bound.setdefault(pattern, {}).setdefault(dotted, set())
        methods.update(str(method) for method in (operation.methods or ()))
        for tag in operation.tags or ():
            tag_apps.setdefault(str(tag), set()).add(_app_label_of(dotted))
    for label, declared in _tag_declarations_by_app().items():
        for tag in declared:
            tag_apps.setdefault(str(tag), set()).add(label)

    found: list[CheckMessage] = []
    for pattern, modules in sorted(bound.items()):
        if len(modules) < 2:
            continue
        path = spelled[pattern]
        verbs = ", ".join(sorted({m for methods in modules.values() for m in methods}))
        sides = " and ".join(
            f"{_module_file(dotted)} ({', '.join(sorted(methods))})"
            for dotted, methods in sorted(modules.items())
        )
        found.append(
            Error(
                f"{verbs} {path} is answered by {sides}; the mount serves whichever was "
                "discovered first and the document describes the other, silently — give "
                "the newer module a PREFIX of its own (or a route path whose first segment "
                'is its own word when PREFIX is "") (house rule 83).',
                obj=path,
                id="djb.E083",
            )
        )
    for tag, owners in sorted(tag_apps.items()):
        if len(owners) < 2:
            continue
        found.append(
            Error(
                f"the tag {tag!r} is declared by apps {' and '.join(sorted(owners))}; a tag "
                "is a scope family, and one key across two apps is one token ceiling that "
                "reaches both — give the newer router (and its TAGS entry) a key of its own "
                "(house rule 83).",
                obj=tag,
                id="djb.E083",
            )
        )
    found.extend(_display_title_findings())
    found.extend(_schema_name_findings(operations))
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
                    "for the job, or record the extra module for this app in rule 11's "
                    f"`extra_modules` with the reason; {reach_road('11')} (house rule 11).",
                    obj=rel,
                    id="djb.E011",
                )
            )
    return found


# --- rule 13 (model half): a scoped model's writes have a policy ----------------


@register(DJB)
def check_scoped_write_policies(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Every scoped model has a write action somebody can be given. **Three ways now.**

    THE PREMISE MOVED UNDER THIS CHECK (ADR core-25), and the sentence it used
    to print became false: *"no `role.*` action in any policies.py, so
    authz.require can only refuse"*. Since the vocabulary is derived, every
    first-party model IS a kind and carries `<kind>.create/read/update/delete`
    with no `policies.py` entry anywhere — measured on this tree:
    `role.create` is `decided_by=derived`, has no predicate, and
    `defaults_for("admin")` and `defaults_for("owner")` both contain it, so
    `require` allows rather than only refusing. Left as it was, this check
    reported a cause it could not prove against **every model added to any app
    after the vocabulary landed**, which is a tripwire on arrival rather than on
    a defect.

    So the question is asked three ways, in the order they cost:

    1. **The kind's derived verbs.** `kind_of(model)` yields a kind whose
       `create` is in the vocabulary — the model has write actions, by
       derivation, and nobody had to type anything.
    2. **A declared opt-out.** `authz_kind = None` means "this is not a kind",
       and `core.authz._own_kind` already refuses that declaration without an
       `authz_kind_reason` beside it, so the sentence is guaranteed present and
       lives in the model's own file. That is the same judgement a `rules.yaml`
       exemption records, sourced from the member's own declaration.
    3. **A policy noun, or a recorded exemption** — the original question,
       unchanged, for anything the first two do not answer.

    DOES NOT COVER — declared: whether the service that writes the model
    requires the right kind. That is rule 13's kind-mismatch clause and it is
    read by AST, not here.
    """
    from apps.core.authz import kind_of, policies, vocabulary
    from apps.core.models import AUTHZ_KIND_DERIVED, TenantScopedModel

    found: list[CheckMessage] = []
    exempt = {str(x.get("model")) for x in _scope("13").get("policy_exemptions") or []}
    # GUARDED like the vocabulary below it, and for the same reason: discovering
    # the policy registry walks every app's `policies.py`, so a product with one
    # malformed declaration used to take the whole check pass down from this
    # line — a traceback where `djb.E025` should have been. `policies` is a
    # forced derivation in `check_vocabulary_is_derivable` so the finding keeps
    # an owner (that function says why the pair is one change).
    declared = _derived_or_none(policies)
    if declared is None:
        return []
    nouns = {action.split(".", 1)[0] for action in declared}
    # GUARDED, and `_derived_or_none` argues why the guard rather than a
    # registration order. While the vocabulary will not derive, the first of
    # this check's three questions has no answer and the other two would be
    # judging models against half a premise, so it stops: `djb.E025` owns that
    # finding and runs beside this one under every tag that selects either.
    words = _derived_or_none(vocabulary)
    if words is None:
        return []
    # `kind_of` cannot raise once `vocabulary()` has returned: deriving it walks
    # `kind_registry_of(first_party_models())`, which calls `kind_of` on every
    # first-party model first. The guard above is the whole of it.
    for model in _local_models():
        if model._meta.proxy or not issubclass(model, TenantScopedModel):
            continue
        if model._meta.abstract or model is TenantScopedModel:
            continue
        label = model._meta.label
        if label in exempt:
            continue
        kind = kind_of(model)
        if kind is not None and f"{kind}.create" in words:
            continue
        if getattr(model, "authz_kind", AUTHZ_KIND_DERIVED) is None:
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


#: A query parameter a contract docstring documents: `?name=` opening a backticked
#: span (`?show=archived`, `?cursor=<token>`). Only the backticked form is read —
#: prose that merely mentions a question mark is not a promise.
_DOCUMENTED_QUERY = re.compile(r"`\?([a-z_][a-z0-9_]*)=")

#: A passage that documents a parameter as REFUSED is not a promise the route
#: takes it: a refusal bullet (`* `400 invalid` — … `?archived=` was sent`), or a
#: sentence saying so (`There is no `?archived=` — it is refused`).
_REFUSED_PARAMETER = re.compile(r"\b(refused|no longer accepted|there is no)\b", re.IGNORECASE)
_REFUSAL_BULLET = re.compile(r"^\s*\*\s+`\d{3}\b")


def _passages(contract: str) -> list[str]:
    """The contract as passages: a bullet with its continuation lines, or a paragraph."""
    passages: list[list[str]] = []
    for line in contract.splitlines():
        if not line.strip():
            passages.append([])
            continue
        if line.lstrip().startswith("* ") or not passages:
            passages.append([line])
        else:
            passages[-1].append(line)
    return ["\n".join(chunk) for chunk in passages if chunk]


def _documented_queries(contract: str) -> list[str]:
    """The query parameters a contract promises, in order, refusals set aside."""
    found: list[str] = []
    for passage in _passages(contract):
        if _REFUSAL_BULLET.match(passage) or _REFUSED_PARAMETER.search(passage):
            continue
        for name in _DOCUMENTED_QUERY.findall(passage):
            if name not in found:
                found.append(name)
    return found


def _sibling_list_offers(url_name: str, name: str, by_name: dict[str, Any]) -> bool:
    """Whether the same noun's LIST declares `?name=` — a record's route may point there.

    An archive route saying "find it again under `?show=archived`" documents
    its noun's list, not itself; the list is found by the noun's `url_name`
    forms, the same ones rule 74 demands `?show=` of.
    """
    try:
        noun = split_url_name(url_name)[0]
    except UnderivableName:
        return False
    return any(
        _offers_query(by_name[list_name], name)
        for list_name in _list_names(noun)
        if list_name in by_name
    )


@register(DJB)
def check_contract_documentation(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    from apps.core.api.docs import (
        added_refusals,
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
    by_name = {str(operation.url_name or ""): operation for _prefix, operation in operations}

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

        # A documented query parameter exists on the route: a backticked
        # `?name=` in the contract names a parameter this operation declares.
        # A replace-all once pasted `?can=` onto a route that takes none, and
        # only a human reading the document caught it.
        for name in _documented_queries(contract or ""):
            if not _offers_query(operation, name) and not _sibling_list_offers(
                url_name, name, by_name
            ):
                found.append(
                    Error(
                        f"route {url_name or where} ({where}) documents `?{name}=` and "
                        f"declares no `{name}` query parameter: a caller who sends it is "
                        "ignored (or refused), and the contract said it would work "
                        "(house rule 41).",
                        obj=url_name or where,
                        id="djb.E041",
                    )
                )

        declared = declared_refusals(view)
        for code in (*(declared or ()), *added_refusals(view)):
            if code not in REFUSALS:
                found.append(
                    Error(
                        f"route {url_name or where} ({where}) declares {code!r} "
                        "(`@refuses` / `@also_refuses`), "
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
            try:
                candidates = [derive_tool_name(url_name)]
            except UnderivableName:
                candidates = []
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


# --- rule 54: the vocabulary is one shape (ADR core-25) -------------------------
#
# TWO CHECKS AND THEY ARE DIFFERENT TIERS, because they answer different
# questions about different things.
#
# `check_vocabulary_is_derivable` is an ERROR over CODE, and it runs on every
# `manage.py` call. The things it forces are the ones that make the vocabulary
# underivable rather than wrong: two models claiming one kind, an
# `authz_kind_of` naming a foreign key that is not `CASCADE`, a malformed
# `policies.py`, two apps declaring one role key, a rename pointing at a key
# nothing declares, two roles marked as the default. None of those is a
# judgement — each one means a permission key would mean a different thing
# depending on import order, and no answer is better than an arbitrary one.
#
# `check_roles_are_keys` (`djb.W054`) is a WARNING over DATA, and it runs only
# under `--deploy`. It reads rows, so it needs a database and the rest of this
# module does not; and what it finds is a deployment's own history rather than a
# defect in the tree — a membership left on a role somebody deleted is a real
# problem for one tenant and no reason for anybody's `manage.py` to stop.


def _derived_or_none[T](derive: Callable[[], T]) -> T | None:
    """A forced derivation's answer, or `None` when this deployment cannot derive it.

    **THE ORDERING DJANGO DOES NOT OFFER.** Every check in this module that
    reads the permission vocabulary asks through here, because the obvious
    alternative — "register `djb.E025` ahead of the checks that read it" — is
    not something the framework can promise. `django.core.checks.registry`
    holds `self.registered_checks = set()` and `run_checks` iterates what
    `get_checks()` builds out of that set, so the run order is a hash order:
    it would appear to work on one machine, under one interpreter, and
    reorder silently on the next. The guard does not depend on an ordering
    nobody is offering.

    **What it buys, measured.** Before this, a kind collision planted on
    `core.AuditEntry` made `manage.py check`, `check --tag djb` and
    `check --deploy` all die with an unhandled `ImproperlyConfigured` out of
    `check_scoped_write_policies` — a traceback, no `(djb.E025)` line, and
    every forced derivation after the first reporting nothing at all, because
    the check that owns the finding never got to run. The safety was real and
    the grammar was not.

    **One finding, one owner.** A blinded check returns nothing rather than a
    second copy of E025's sentence under its own id: the same fact reported by
    two checks is noise, and `check_vocabulary_is_derivable` is guaranteed to
    run beside every caller here — it carries the same `djb` tag, so no tag
    selection can pick a reader without picking the owner, and a bare
    `manage.py check` runs both. E025's own message says that the readers went
    quiet, so the silence is declared rather than discovered (§I).

    DOES NOT COVER — declared: an `ImproperlyConfigured` raised for a reason
    that has nothing to do with the vocabulary would also be swallowed here and
    reported by E025's forcing loop instead, which is the right answer for
    every case this module can produce and a wrong one for a case it cannot.
    """
    from django.core.exceptions import ImproperlyConfigured

    try:
        return derive()
    except ImproperlyConfigured:
        return None


@register(DJB)
def check_vocabulary_is_derivable(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Force the vocabulary and the role declarations at BOOT, not at the first `require`.

    Everything `core.authz` refuses at discovery — a kind two models both claim,
    an `authz_kind_of` whose foreign key is not `CASCADE`, one role key declared
    by two apps, a rename onto a key nobody declares, two roles both marked as
    the default — used to be refused lazily, at the first call to `require()`.
    That is a 500 on somebody's request, in production, for a mistake that was
    in the tree before it was deployed, and the traceback names one model while
    the reader needs both.

    Forcing them here is the cheapest place the mistake can be found after the
    file is saved: every `manage.py` command runs the check framework, so does
    the gate (`manage.py check --tag djb`), and `check --deploy` runs everything
    a plain `check` does plus the deployment set.

    **Why a check and not `CoreConfig.ready()`**, which would be stronger: a
    failure in `ready()` is an `ImproperlyConfigured` traceback out of
    `django.setup()`, which takes `manage.py` down with it — including the
    commands somebody would use to FIX the collision — and it names one model in
    a stack trace rather than two findings a reviewer can read side by side.
    This check reports in the house grammar, with an id a product can grep,
    beside every other finding from the same run, and still exits non-zero.
    DOES NOT COVER — declared: the ASGI and Temporal worker boots do not run the
    check framework, so a deployment that never runs `manage.py check` can serve
    with an underivable vocabulary and meet it at the first `require()` after
    all. The gate leg and `check --deploy` are the two places it is caught
    before that, and both are in the road to production.
    """
    from django.core.exceptions import ImproperlyConfigured

    from apps.core import authz

    found: list[CheckMessage] = []
    forced: tuple[tuple[str, Any], ...] = (
        ("the authorization kinds", authz.kind_registry),
        # THE POLICY REGISTRY IS FORCED HERE TOO, and that is the half that
        # makes guarding its reader safe. `check_scoped_write_policies` asks
        # `policies()` through `_derived_or_none` like its siblings, so a broken
        # `policies.py` no longer tracebacks out of the check pass — but a guard
        # with no owner would turn the traceback into SILENCE, which is worse:
        # none of the other four derivations has to fail for `policies()` to,
        # and the check that went quiet would be the only thing that noticed.
        # Guarding the reader and forcing the derivation are one change.
        ("the policy registry", authz.policies),
        ("the permission vocabulary", authz.vocabulary),
        ("the role declarations", authz.role_declarations),
        ("the default role for new members", authz.default_role_key),
    )
    for what, derive in forced:
        try:
            derive()
        except ImproperlyConfigured as exc:
            # THE SILENCE SENTENCE IS MEASURED, NOT ASSUMED. Not every
            # underivable thing here silences the guarded readers: two roles
            # marked as the default breaks `default_role_key()` while
            # `vocabulary()` and `role_declarations()` both answer, so rule 13's
            # model half and the role census are working normally and telling
            # the reader otherwise would send them hunting for a second defect.
            # So the sentence is appended only when the readers really are
            # silent, and it is the readers themselves that are asked.
            silenced = (
                _derived_or_none(authz.vocabulary) is None
                or _derived_or_none(authz.role_declarations) is None
            )
            text = (
                f"{what} cannot be derived, so every permission key in this deployment "
                f"is ambiguous: {exc}"
            )
            if silenced:
                text += (
                    " While this stands, every other check that reads the vocabulary reports "
                    "NOTHING rather than reporting clean — rule 13's model half and the "
                    "`--deploy` role census included (`_derived_or_none` in this module says "
                    "why). Fix this finding and run `check` again."
                )
            found.append(Error(text, obj="apps/core/authz.py", id="djb.E025"))
            # The five are ordered so that the first failure is the nearest
            # cause: the kinds and the policies feed the vocabulary, which feeds
            # the renames. A second message about a derivation that could never
            # have run on top of a broken first one would be noise wearing a
            # finding's clothes.
            break
    return found


def _role_census_rows() -> tuple[list[CheckMessage], bool]:
    """The `djb.W054` findings over this deployment's rows, and whether it could look.

    Split out of the check so a test can call it without `call_command`, and so
    the could-not-look half has one place to be true. The boolean is `False`
    when the tables are not there — an unmigrated database is not a deployment
    with clean data, and the check says which it met.
    """
    from django.db import DatabaseError

    from apps.core.authz import (
        OWNER_ROLE,
        RESERVED_PERMISSIONS,
        role_declarations,
        vocabulary,
    )
    from apps.core.models import Grant, Invitation, Membership, Role, RolePermission, Tenant

    # GUARDED, like every other reader in this module (`_derived_or_none`). A
    # census that cannot say what a legal role or a legal permission IS cannot
    # judge a row against either, and `--deploy` runs the plain checks too, so
    # `djb.E025` is already in the same output saying why. Reported as a
    # could-not-look rather than as clean, which is what the boolean is for.
    declarations = _derived_or_none(role_declarations)
    words = _derived_or_none(vocabulary)
    if declarations is None or words is None:
        return ([], False)
    declared = set(declarations)
    grantable = set(words) - set(RESERVED_PERMISSIONS)
    found: list[CheckMessage] = []

    def warn(text: str, obj: str) -> None:
        found.append(Warning(f"{text} (house rule 54 (b), ADR core-25).", obj=obj, id="djb.W054"))

    try:
        slugs = dict(Tenant.objects.values_list("id", "slug"))
        custom: dict[Any, set[str]] = {}
        for tenant_id, key in Role.objects.values_list("tenant_id", "key"):
            custom.setdefault(tenant_id, set()).add(str(key))

        # (1) Memberships and pending invitations name a role this tenant has.
        # One warning per (tenant, value), with the count: a tenant with forty
        # memberships on a deleted role has one problem, not forty.
        counts: dict[tuple[Any, str, str], int] = {}
        pairs = [
            ("membership", Membership.objects.values_list("tenant_id", "role")),
            (
                "pending invitation",
                Invitation.objects.filter(status=Invitation.Status.PENDING).values_list(
                    "tenant_id", "role"
                ),
            ),
        ]
        for noun, rows in pairs:
            for tenant_id, value in rows.iterator(chunk_size=2000):
                role = str(value or "")
                if role in ({OWNER_ROLE, ""} | declared | custom.get(tenant_id, set())):
                    continue
                counts[(tenant_id, role, noun)] = counts.get((tenant_id, role, noun), 0) + 1
        for (tenant_id, role, noun), count in sorted(
            counts.items(),
            key=lambda item: (str(slugs.get(item[0][0], "")), item[0][1], item[0][2]),
        ):
            slug = slugs.get(tenant_id, tenant_id)
            warn(
                f"tenant {slug!s} has {count} {noun}(s) on the role {role!r}, which is not "
                "`owner`, not a key any app declares in a `roles.py`, and not a `core.Role` "
                "row this tenant owns — it resolves to no permissions at all",
                f"core.Tenant:{slug}",
            )

        # (2) A stored permission that is not in the vocabulary, or is reserved.
        # Both are rows that can never fire: the first names nothing, and the
        # second names the one key no grant and no role may carry.
        stored = [
            ("core.Grant", Grant.objects.values_list("tenant_id", "permission")),
            ("core.RolePermission", RolePermission.objects.values_list("tenant_id", "permission")),
        ]
        for label, rows in stored:
            seen: dict[tuple[Any, str], int] = {}
            for tenant_id, permission in rows.iterator(chunk_size=2000):
                if str(permission) in grantable:
                    continue
                seen[(tenant_id, str(permission))] = seen.get((tenant_id, str(permission)), 0) + 1
            for (tenant_id, permission, *_), count in sorted(
                seen.items(), key=lambda item: (str(slugs.get(item[0][0], "")), item[0][1])
            ):
                slug = slugs.get(tenant_id, tenant_id)
                why = (
                    "is reserved — `owner` is its only holder and no row may name it"
                    if permission in RESERVED_PERMISSIONS
                    else "is in no app's vocabulary, so it can never be matched"
                )
                warn(
                    f"tenant {slug!s} holds {count} {label} row(s) naming {permission!r}, which "
                    f"{why}",
                    f"{label}:{slug}",
                )

        # (3) `exclude` subtracts from a DECLARED collection, and a custom role
        # has none to subtract from — the row would be storing a difference from
        # the empty set.
        excludes: dict[tuple[Any, str], int] = {}
        for tenant_id, role_key in RolePermission.objects.filter(
            effect=RolePermission.Effect.EXCLUDE
        ).values_list("tenant_id", "role_key"):
            if str(role_key) in declared:
                continue
            excludes[(tenant_id, str(role_key))] = excludes.get((tenant_id, str(role_key)), 0) + 1
        for (tenant_id, role_key), count in sorted(
            excludes.items(), key=lambda item: (str(slugs.get(item[0][0], "")), item[0][1])
        ):
            slug = slugs.get(tenant_id, tenant_id)
            warn(
                f"tenant {slug!s} holds {count} `exclude` row(s) on the role {role_key!r}, which "
                "no app declares — an exclusion only means something against a declared "
                "collection, and a custom role's collection is the rows themselves",
                f"core.RolePermission:{slug}",
            )
    except DatabaseError as exc:
        # COULD NOT LOOK, said out loud — and at `Info`, which is the whole
        # judgement in this branch. The gate's own `check --deploy` leg runs
        # production settings against a throwaway environment with no database
        # by design ("the point is the SETTINGS, not the secrets" —
        # `scripts/check.sh`), so an unreachable database there is the leg
        # working, not a deployment with bad rows. A `Warning` would redden it
        # under `--fail-level WARNING` and turn a settings probe into a database
        # probe; returning `[]` would let this census report clean while reading
        # nothing, which is the failure mode §I exists to forbid. `Info` prints
        # the sentence and fails nothing, and the sentence says what was not
        # read.
        return (
            [
                Info(
                    "the role census read no rows — this deployment's database was not "
                    f"reachable, so it is reporting NOTHING rather than reporting clean: {exc}",
                    obj="apps/core/checks.py",
                    id="djb.W054",
                )
            ],
            False,
        )
    return found, True


@register(DJB, deploy=True)
def check_roles_are_keys(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """`djb.W054` — every stored role and permission names something this deployment has.

    The belt behind the service refusals (rule 54 (b)). `add_membership`,
    `set_role` and `invite_member` refuse a role key the tenant cannot name, and
    the six permission services refuse a permission outside the vocabulary — but
    a deployment accumulates rows over time and the CODE moves underneath them:
    a product removes `admin` from its `roles.py`, a tenant deletes a custom
    role, an app is uninstalled and takes its keys with it. Every one of those
    leaves rows that are still perfectly valid strings and resolve to nothing.

    **A warning and `--deploy`-only, deliberately.** What it finds is one
    deployment's data, not a defect in the tree: it must not stop a developer's
    `manage.py`, and it is not something the gate can measure, because the gate
    has no product's rows. DOES NOT COVER — declared: nothing stops a deploy on
    a warning. It is printed where somebody is looking at a deployment, and the
    `0018` census is the hard refusal for the one case that cannot be allowed to
    pass silently — a value that was legal under `choices` and is a key now.

    The fourth clause reads CODE rather than rows and is here anyway, because a
    `DEFAULT_ROLES` entry naming an undeclared role is the same defect one layer
    up: an app offering a capability to a role nobody declares offers it to
    nobody. It is import-tolerant by construction — a platform app must still
    import in a product that deleted `member`, so this is a census and never a
    refusal at discovery.
    """
    from apps.core.authz import _discover_default_roles, role_declarations

    # DJANGO'S OWN IDIOM FOR "WAS I OFFERED A DATABASE". `manage.py check`
    # passes the `--database` aliases through as `databases`, and every
    # database-reading check in Django skips when the set is empty. The gate's
    # `check --deploy` leg offers none on purpose — it is a settings probe — so
    # without this the census spends ten seconds failing to connect on every
    # builder's `--loop` before printing that it saw nothing. An operator who
    # wants the rows asks for them: `manage.py check --deploy --database default`.
    found: list[CheckMessage] = []
    if kwargs.get("databases"):
        found, _looked = _role_census_rows()
    else:
        found = [
            Info(
                "the role census read no rows — this run offered it no database. Ask for "
                "them with `--database default`; without that this check reports only the "
                "code half below (house rule 54 (b), ADR core-25).",
                obj="apps/core/checks.py",
                id="djb.W054",
            )
        ]
    # The code half, guarded for the same reason as the row half above: a
    # `DEFAULT_ROLES` entry can only be judged against the declarations, and
    # the declarations are one of the things `djb.E025` forces.
    declarations = _derived_or_none(role_declarations)
    if declarations is None:
        return found
    declared = set(declarations)
    for action, roles in sorted(_discover_default_roles().items()):
        for role_key in sorted(set(roles) - declared):
            found.append(
                Warning(
                    f"a DEFAULT_ROLES entry offers {action!r} to the role {role_key!r}, which no "
                    "app declares in a `roles.py` — the capability is offered to nobody "
                    "(house rule 54 (b), ADR core-25).",
                    obj=action,
                    id="djb.W054",
                )
            )
    return found
