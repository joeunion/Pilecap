"""The one HTTP API surface, assembled by discovery.

An app joins `/api/` by dropping an `api.py` that exposes `router: ninja.Router`.
Nothing here is edited when an app is added — that is the whole point: a new app
is a new file, never a change to a file two other agents are also editing.

The prefix an app is mounted under is its label, unless its `api` module names a
`PREFIX`. The example app names `widgets`, because a URL should say what the
resource is, not which app happens to hold it.

Authentication is declared once, here, as the API default: a session (the human
door) or a bearer token (the machine door). A route may narrow that; dropping it
is a house-rule violation, so every router in this repository restates `auth=`
explicitly rather than inheriting it silently.

**Domain exceptions are mapped once, here, too.** A service raises what it
means — `apps.core.exceptions.NotFound`, `Conflict`, `Forbidden`, `Invalid`,
`RateLimited` — and this module is the only one in the tree that knows which
status code each of those is. That is house rule 14 from the door's side: a
service that imported `HttpError` could only ever be called by this door, and
three of the five doors have no status codes at all.

The Django-native exceptions are mapped here too, because they escape from
places a service does not control: `full_clean()` inside the admin, a
constraint the database enforced, a `get_object_or_404` in a route. Without
that, a duplicate name is an unhandled exception and the API answers a machine
with a 500 and a page of HTML. Nothing is caught and reshaped per route.

**And an unmatched path under the API answers in JSON too.** A typo in a
URL used to fall through to Django's HTML 404 page, so a JSON client's first
wrong guess came back as a page of markup with no `code` in it — a contract
defect of exactly the same class as an unmapped exception, closed in the same
module because the refusal body has one composer.

**ninja's own `HttpError` is mapped here too, for the same reason.** Its
default handler answers `{"detail": str(exc)}` with no `code`, which
covered the two refusals a client meets *first* — "no usable credential" and a
signed-in browser write with no page token — plus every deliberate `raise
HttpError(...)` a door makes before it reaches a service. One handler on the
base class puts all of them back inside the one envelope; see `on_http_error`.
**And a wrong METHOD answers in JSON too.** `GET` on a POST-only path
used to come back as ninja's `HttpResponseNotAllowed` — status 405,
`Content-Type: text/html`, the words "Method not allowed", no `code` — the same
defect for an unmatched *method* that was already closed for an unmatched
*path*. ninja **returns** that response rather than raising it, so no exception
handler above can see it; the translation is a wrap of the two `PathView` views
that produce it, and it keeps ninja's own `Allow` header verbatim. See
`_speak_the_method_refusal`.

**And the schema-validation refusal joins the envelope too.** ninja answers
a body that does not match its schema with
`{"detail": [{"loc", "msg", "type"}]}` — a list where every other refusal is an
object, no `code`, and pydantic's own vocabulary on the wire — which
`django-conventions` §6 used to bless as "the one other shape". It was the last
hole in the envelope and it was doctrine rather than oversight, so closing it
took a ruling. `on_schema_validation` recomposes it: a registered `code`, a
plain sentence, the field errors under `errors` in the caller's own field names,
and the registry's remedies. The status is unchanged — 422 for a body, which is
what ninja already answered — because what was wrong was the body, not the
number. **There is no second shape any more.**

**The OpenAPI document is assembled here, from what is already true** (ADR
api-1). `apps.core.api.docs` holds the derivations — a route's prose off its own
docstring, its refusals off the refusal registry, its headers off the constants
that declare them, its examples off the schemas themselves — and this module is
where they are applied, because this is the module that already owns the
document and the status codes.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import ModuleType
from typing import Any, Literal

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.views.defaults import server_error
from ninja import NinjaAPI, Router, Schema
from ninja.errors import AuthenticationError, AuthorizationError, HttpError, Throttled
from ninja.errors import ValidationError as NinjaValidationError
from ninja.openapi.schema import BODY_CONTENT_TYPES
from ninja.responses import NinjaJSONEncoder

from apps.accounts.auth import API_AUTH, Unauthenticated
from apps.core import context, surfaces
from apps.core.actor import TOKEN_ATTR
from apps.core.api import docs, scopes
from apps.core.api.pagination import answers_cursor_envelope
from apps.core.api.query import retired_query_of
from apps.core.discovery import declared
from apps.core.exceptions import (
    CODE_STATUSES,
    NON_FIELD_KEY,
    REFUSALS,
    Conflict,
    DomainError,
    Forbidden,
    Invalid,
    NotFound,
    RateLimited,
    Remedy,
    bare_status_refusals,
    database_unavailable,
    is_connection_shaped,
    register_refusal,
    wire_refusal,
)
from apps.core.idempotency import HEADER as IDEMPOTENCY_HEADER
from apps.core.idempotency import METHODS as IDEMPOTENT_METHODS
from apps.core.idempotency import REPLAYED_HEADER
from apps.core.middleware import (
    ORG_HEADER,
    TENANT_HEADER,
    request_addressing_refusal,
)
from apps.core.throttling import default_throttles

# --- THE ONE ENCODER, and the contract both doors keep -------------


#: What the HTTP door actually renders every response with. Read off ninja
#: rather than chosen: `NinjaJSONEncoder` subclasses Django's, and Django's is
#: what truncates an ECMA-262 timestamp to MILLISECONDS. Naming the real class
#: — instead of a locally-chosen equivalent — is what makes "the door encoder"
#: a fact a check can read rather than a claim two modules could drift apart on.
DOOR_ENCODER: type[json.JSONEncoder] = NinjaJSONEncoder

#: An ISO-8601 instant carrying MORE precision than the door keeps. Three
#: fractional digits or fewer is already exactly what the door writes, so
#: nothing matches and nothing is touched; four or more is the divergence and
#: only the divergence. The twin of `apps/events/services._SUB_MILLISECOND`,
#: which closes the (event payload, REST body) half of the same contract by
#: the same means.
_SUB_MILLISECOND = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\.\d{4,}(?:[Zz]|[+-]\d{2}:\d{2})?$"
)


def _handed_back_to_the_encoder(value: Any) -> Any:
    """Over-precise timestamp STRINGS turned back into the instants they name.

    The encoder only ever gets to render what it is handed, and by the time a
    machine-door answer reaches this function its datetimes have stopped being
    datetimes: pydantic's `model_dump(mode="json")` has already written
    `2026-08-25T12:34:56.123456Z` where the HTTP door would write
    `2026-08-25T12:34:56.123Z`. Handing that string to `json.dumps` would leave
    it alone.

    So the string is parsed back into the instant it names and handed to the
    encoder, which renders it — **the truncation rule is never reimplemented
    here**, and the day Django changes it both doors change together. That is
    the whole reason this is a round trip rather than a three-character slice,
    and it is `apps/events/services._handed_back_to_the_encoder`'s argument,
    lifted to the seam both doors share.

    Only `_SUB_MILLISECOND` matches, so a string the door would have written
    unchanged is left byte-identical, and an opaque string that merely looks
    date-ish (`"2026-08-25"`, `"2026-08-25T12:34:56Z"`) is never rewritten.
    """
    if isinstance(value, str):
        if _SUB_MILLISECOND.match(value):
            try:
                return datetime.fromisoformat(value)
            except ValueError:  # pragma: no cover - the regex has already agreed
                return value
        return value
    if isinstance(value, dict):
        return {key: _handed_back_to_the_encoder(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_handed_back_to_the_encoder(item) for item in value]
    return value


def as_the_door_renders(payload: Any) -> Any:
    """This value as the HTTP door would have put it on the wire.

    **The one encoder, called from the one place each door reaches it** — the
    HTTP door renders through `DOOR_ENCODER` by construction (ninja does it),
    and `config/mcp.py` puts every machine-door answer through this on the way
    out. Before that, one row read through two doors carried two
    different strings for one instant: `…:56.123Z` on REST and `…:56.123456Z`
    on MCP, which is a difference between two JSON encoders and never a
    difference between two doors.

    The direction was already ruled: **the REST door's
    millisecond rendering is the truth, and everything else truncates to match**
    — settled when the (event payload, REST body) pair was closed the same way,
    so this is that ruling reaching its second pair rather than a new decision.

    Round-tripped through `json.dumps`/`json.loads` so the value that comes back
    is exactly what a client would have parsed, rather than a structure that
    merely serialises the same.
    """
    return json.loads(json.dumps(_handed_back_to_the_encoder(payload), cls=DOOR_ENCODER))


class ContractAPI(NinjaAPI):
    """The API, plus the last pass over its own document.

    Everything ninja builds from the routes is left alone; what is added is what
    ninja has no way to know — the tag descriptions each app declared, the one
    refusal shape every error body has, and an example on every schema. It is a
    subclass rather than a post-processing call at the call site because
    `/api/v1/docs`, `openapi.json` and `scripts/gen_client.sh` all reach the
    document by different routes and every one of them must get the same one.
    """

    def get_openapi_schema(self, *args: Any, **kwargs: Any) -> Any:
        schema = super().get_openapi_schema(*args, **kwargs)
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.update(docs.refusal_component())
        docs.add_examples(components)
        schema["tags"] = _tag_descriptions()
        # The write side of the header derivation, and it runs HERE rather than
        # per bound operation because the success responses are ninja's own and
        # do not exist until it has finished. One call: which headers there are,
        # and which responses each lands on, is declared beside the writers.
        docs.add_response_headers(schema)
        return _for_the_surface(schema)


def _for_the_surface(schema: dict[str, Any]) -> dict[str, Any]:
    """The document narrowed to the families the request's surface exposes.

    The surface is the one the door bound for this request (`context`, beside
    `door`), read through the same predicate the door gate asks
    (`surfaces.exposes`) — so a host's document and its doors cannot disagree
    about what it answers. Outside a request (the client generator, a test, a
    command) nothing is bound and the document is whole; on a total surface it
    is whole too, byte for byte.
    """
    bound = context.value("surface")
    surface = surfaces.declared().get(str(bound)) if bound else None
    if surface is None or surface.families is surfaces.ALL:
        return schema
    kept: dict[str, Any] = {}
    for path, item in schema.get("paths", {}).items():
        operations = {
            method: operation
            for method, operation in item.items()
            if not isinstance(operation, dict)
            or "tags" not in operation
            or surfaces.exposes(surface, _family(operation.get("tags")))
        }
        if any(
            isinstance(operation, dict) and "tags" in operation for operation in operations.values()
        ):
            kept[path] = operations
    schema["paths"] = kept
    schema["tags"] = [tag for tag in schema.get("tags", []) if tag.get("name") in surface.families]
    return schema


def _family(tags: Sequence[str] | None) -> str | None:
    """An operation's one scope family — its one tag (rule 41) — or `None` for any other count."""
    return tags[0] if tags is not None and len(tags) == 1 else None


api = ContractAPI(
    title="API",
    version="1",
    # `overview()` and not a constant: the two-planes guide renders from the
    # live TAGS registry (partition disposition D2), which cannot be walked at
    # `docs.py` import time without re-entering a half-imported `api.py`.
    description=docs.overview(),
    auth=API_AUTH,
    throttle=default_throttles(),
    docs_url="/docs",
    docs=docs.SCALAR,
    urls_namespace="api",
)


def _discover_api_modules() -> list[tuple[str, ModuleType, Router]]:
    """Every installed `apps.*` module that exposes a `router`, in app order."""
    found: list[tuple[str, ModuleType, Router]] = []
    for config, router in declared(
        "api", "router", predicate=lambda value: isinstance(value, Router)
    ):
        module = sys.modules[f"{config.name}.api"]
        prefix = str(getattr(module, "PREFIX", config.label)).strip("/")
        found.append((prefix, module, router))
    return found


def _discover_routers() -> list[tuple[str, Router]]:
    """The mount's own view of discovery: (prefix, router), in app order."""
    return [(prefix, router) for prefix, _module, router in _discover_api_modules()]


def _tag_descriptions() -> list[dict[str, str]]:
    """The document's `tags` section, collected from the apps that own the tags.

    An `api.py` declares `TAGS: dict[str, Tag]` beside its routers — the tag
    name it puts on a `Router`, and a `Tag(display, description)` saying what a
    reader should call that group and what it is for. Collected by discovery
    like everything else, so an app that grows a router does not edit this file,
    and house rule 41 is what notices a tag nobody described or nobody named.

    A bare string is still read as a description, so a product mid-upgrade
    imports; it reaches the document with no `x-displayName` and rule 41 says so.
    """
    collected: dict[str, docs.Tag | str] = {}
    for _prefix, module, _router in _discover_api_modules():
        declared = getattr(module, "TAGS", None)
        if isinstance(declared, dict):
            for name, entry in declared.items():
                collected[str(name)] = entry
    return [
        docs.tag_entry(name, collected[name])
        for name in sorted(collected)
        if getattr(collected[name], "description", collected[name])
    ]


def _retired_query_parameters(operation: Any) -> list[dict[str, Any]]:
    """The query parameters this operation retired, published `deprecated: true`.

    An `api.py` declares `RETIRED_QUERY: dict[str, RetiredQuery]` beside its
    `TAGS` — a parameter a list no longer takes, the live one to ask with
    instead, and the sentence a caller reads. Read through
    `core.api.query.retired_query_of`, the same function a product's
    strict-query seam defers to, so the document, the seam and the route's
    refusal read one declaration and cannot disagree about which operations
    retired what. `deprecated` is the standard flag every OpenAPI reader
    renders: a generated client sees the word, and a caller reads why.
    """
    return [
        {
            "name": name,
            "in": "query",
            "required": False,
            "deprecated": True,
            "description": retired.reason,
            "schema": {"type": "string"},
        }
        for name, retired in sorted(retired_query_of(operation).items())
    ]


# --- Domain exceptions, mapped once ------------------------------------------
# The one place in the tree where a domain refusal becomes a NUMBER. The body
# it carries is not composed here: `core.exceptions.wire_refusal` builds it —
# `{"detail", "code"}` always, `errors` field by field when the refusal names
# fields, and `remedies` (label + destination) offering what the caller can do
# — and `core.mcp.tool_call` renders the same body for the machine door. One
# composer, two doors; this module owns the status code and nothing else.

# --- The one refusal that is BORN here --------------------------------
# Every other refusal in `STATUS_FOR` is declared in `apps/` beside the service
# or the authenticator that raises it, and this module only says which number it
# is. This one is different, and deliberately so: nothing below the doors can
# raise it, because "you sent the wrong method" is not a thing a service can
# decide — it is decided by the router, before any route is chosen, and 405 is
# HTTP vocabulary that house rule 14 keeps above the doors. So the class lives
# where the number lives, and the registry entry sits beside it, exactly as it
# would beside a service.
#
# It is registered rather than special-cased because a registered code is what
# makes `introspect` list it, `/llms.txt` explain it, and `openapi.json`
# enumerate it in the refusal component — all three by derivation, with no edit
# anywhere else in the tree.

#: The response header that says which methods a path answers (RFC 9110 §10.2.1).
#: Declared rather than spelled, because this module both READS it — off the
#: answer ninja built — and WRITES it onto the refusal that replaces it, and two
#: spellings of one header is the fail-open house rule 40 exists for. The
#: refusal's remedy below points the caller at this value, which is what makes
#: the offer on the wire and the header on the wire one name by construction.
ALLOW_HEADER = "Allow"

register_refusal(
    code="method_not_allowed",
    boundary="door",
    remedy=(
        "The path was found and the method was not one it answers, so no route ran at "
        "all. The refusal carries an Allow header listing the methods this path does "
        "answer; read that, or look the path up in the API reference, and resend."
    ),
    fact=(
        "This path exists and does not answer that method. Nothing was read and nothing "
        "was written — the request never reached a route."
    ),
    remedies=(
        Remedy("See which methods this path answers", "header:Allow"),
        Remedy("Read the operations on this path", "docs:openapi"),
    ),
    status=405,
)


class MethodNotAllowed(DomainError):
    """The path is right and the verb is not.

    Never raised below the doors, and it has no `raise` site at all: it is
    constructed by `_speak_the_method_refusal` below, out of the answer ninja
    already built, so that a wrong method comes back in the same envelope as
    every other refusal instead of as a page of markup.
    """

    code = "method_not_allowed"
    default_detail = "That path does not answer this method."


# --- The second refusal born here: the body did not validate ----------
#
# Same reasoning as `MethodNotAllowed` above, one layer in. Nothing below the
# doors can raise this: "the JSON you sent has a field this operation does not
# have" is decided by ninja while it is parsing the request, before any route
# runs and long before a service is reached. So the class lives where the
# translation lives, and its registry entry sits beside it.
#
# It is a NARROWER `Invalid`, exactly as `InvalidCursor` is, for the same
# reason: a client that already branches on `invalid` keeps working, and the
# narrower code exists because the FIX is genuinely different. `invalid` means
# a rule about your data did not hold — a service looked and said no.
# `invalid_body` means the request never got that far: it did not match the
# shape this operation accepts, so nothing was read and nothing was written.

register_refusal(
    code="invalid_body",
    boundary="door",
    remedy=(
        "The request did not match the operation's schema, so ninja refused it before "
        "any route ran. `errors` is keyed on the caller's own field names, with the "
        "unknown ones saying so in as many words. Request bodies are STRICT here "
        '(apps/core/schemas.py::StrictIn, extra="forbid") — a field this '
        "operation does not have is a refusal rather than a silent drop, which is what "
        "stops a typo'd field name from returning a healthy 201 for a request that did "
        "nothing. Read the operation's requestBody in the API document."
    ),
    fact=(
        "The request does not match the shape this operation accepts. Nothing was read "
        "and nothing was written — no route ran at all. The answer names each field and "
        "what is wrong with it, in the names you sent, including any field that is not "
        "part of this operation: unknown fields are refused rather than ignored, so a "
        "misspelled name can never look like a success."
    ),
    remedies=(
        Remedy("Read the failing fields and resend", "field:errors"),
        Remedy("Read the shape this operation accepts", "docs:openapi"),
    ),
    # 422, and NOT folded into `Invalid`'s 400 — RFC 9110 §15.5.21. The argument
    # is at `STATUS_FOR` below, where it has always been; this is the same fact
    # said once, where the code is declared.
    status=422,
)


class InvalidBody(Invalid):
    """The request did not match the operation's schema.

    Never raised below the doors, and it has no `raise` site of its own: it is
    constructed by `on_schema_validation` out of what ninja already worked out,
    so a validation failure comes back in the same envelope as every other
    refusal instead of as pydantic's `{"detail": [{"loc", "msg", "type"}]}`.
    """

    code = "invalid_body"
    default_detail = "The request does not match the shape this operation accepts."


#: Which refusal a bare status means — `HttpError(403, …)`, ninja's own
#: `AuthenticationError` — for `on_http_error` below. DERIVED, never typed:
#: the codes are `core.exceptions.BARE_STATUS_CODES` (the one decision: the most
#: general refusal at each number) and the numbers are each code's own `status=`
#: in the registry (ADR core-23), so this table, the class fallback below and
#: the document cannot come to disagree. Every number the registry publishes
#: has an entry — a 503 included, which used to fall through to ninja's codeless
#: `{"detail": …}` — and `apps/core/tests/test_refusal_status.py` pins that no
#: status is a hole. Computed here, after `MethodNotAllowed` and `InvalidBody`
#: are defined and `Unauthenticated` imported, so every listed code has its class.
REFUSAL_FOR_STATUS: dict[int, type[DomainError]] = bare_status_refusals()

#: The class-tree fallback `status_for` walks for a code that declared no number
#: (a machine-door code that reached this door, rule 47's canary): the same
#: classes, each at its own declared status. A view of `REFUSAL_FOR_STATUS`, so
#: a product's `class InsufficientFunds(Conflict)` is a 409 without declaring
#: anything, by its base's declaration and not by a second table.
STATUS_FOR: dict[type[DomainError], int] = {
    cls: CODE_STATUSES[cls.code] for cls in REFUSAL_FOR_STATUS.values()
}


def status_for(exc: DomainError) -> int:
    """The status code for a refusal, including one a product subclassed.

    **The declaration answers first** (ADR core-23). A code that declared its own
    `status=` at its registration site gets that number, because the document is
    written off the same declaration and a wire that disagreed with the document
    is the one failure the declaration exists to make impossible: a new code whose
    class happens to subclass `Forbidden` must not answer 403 while
    `x-refusal-codes` promises what it declared.

    `STATUS_FOR` is then the fallback, walked up the MRO rather than looked up by
    exact type, so a product's `class InsufficientFunds(Conflict)` is a 409
    without declaring anything at all — and so a code that deliberately declares
    NO status (a machine-door refusal, house rule 47's canary) still becomes a
    number if it ever reaches this door. An unmapped `DomainError` is a 500: the
    service refused for a reason this door has no vocabulary for, and inventing
    one would hide it.
    """
    declared = REFUSALS.get(exc.code)
    if declared is not None and declared.status is not None:
        return declared.status
    for base in type(exc).__mro__:
        if base in STATUS_FOR:
            return STATUS_FOR[base]
    return 500


@api.exception_handler(DomainError)
def on_domain_error(request: HttpRequest, exc: DomainError) -> HttpResponse:
    """Every `apps.core.exceptions` refusal, in one place.

    The **status** is this module's decision and the **body** is not: it comes
    from `core.exceptions.wire_refusal`, the one composer the machine door
    renders from too. A body built here would be a second grammar, and the
    first thing it would drift on is the remedies — which is exactly the
    screen-versus-assistant split ADR core-5 exists to close.
    """
    body: dict[str, Any] = wire_refusal(exc)
    response = api.create_response(request, body, status=status_for(exc))
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        # Named, not spelled: the document says `Retry-After` off the same
        # constant this stamps it with, so the two cannot part company.
        response[docs.RETRY_AFTER_HEADER] = str(int(retry_after))
    return response


# --- Django's own, mapped the same way ---------------------------------------
# These escape from places a service does not own: the admin, a route's
# `get_object_or_404`, a constraint the database enforced.


@api.exception_handler(ValidationError)
def on_validation_error(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    """Django's own `ValidationError`, from a `full_clean()` outside a service.

    A service wraps its own validation (`as_invalid()`), so this handler is for
    the paths a service does not own — the admin, a form, a model method a
    product added. Same body either way; a client cannot tell which raised.
    """
    return on_domain_error(request, Invalid.from_django(exc))


@api.exception_handler(IntegrityError)
def on_integrity_error(request: HttpRequest, exc: IntegrityError) -> HttpResponse:
    """A constraint the database enforced.

    The database's own message names tables, columns and constraint names, so it
    is deliberately not passed on: a conflict is all a client is owed.

    `core.mcp.tool_call` performs the identical translation for the machine
    door: a true race is one behaviour, not one per door.
    """
    return on_domain_error(request, Conflict())


@api.exception_handler(OperationalError)
def on_operational_error(request: HttpRequest, exc: OperationalError) -> HttpResponse:
    """The database could not be reached — 503 with `Retry-After`, or nothing.

    **Half a seam on purpose, and MEASURED rather than assumed.** This handler
    sees what ninja sees, which is more than the dispatch brief expected and
    less than enough. `Operation.run` puts `_run_checks` outside its own `try`,
    but `_run_authentication` (ninja 1.6.3) carries a `try` of its own that
    routes an authenticator's exception straight back to `api.on_exception` —
    so `ApiTokenAuth`'s token lookup DOES arrive here, and a request whose first
    statement is a bearer-token read is answered by this function.

    What never arrives here is Django's middleware chain. `TenantMiddleware`
    resolves `request.user`, which resolves the lazy session, which is the first
    statement of every authenticated browser request — above ninja, before any
    operation has been chosen, where no `@api.exception_handler` is consulted.
    `api_server_error` at the bottom of this module is that half. Severing one
    and running `apps/core/tests/test_database_unavailable.py` is how the split
    was established rather than reasoned about: without `handler500` the
    middleware depth answers 500 and the other two stay green.

    Both halves hand the same refusal to `on_domain_error`, so there is one
    composer and one status table however deep the fault erupted.

    **It re-raises what it may not claim.** `is_connection_shaped` is closed over
    SQLSTATE (`core.exceptions`): class `08`, `53300`, `57P03`, or no SQLSTATE at
    all. A deadlock (`40P01`), a cancelled statement (`57014`) and a lock that
    would not wait (`55P03`) are all `OperationalError`s and all three leave
    here untouched — the connection was fine, and telling a client to retry
    would be a retry loop against a healthy server. Re-raising rather than
    answering is the same shape `test_everything_else_is_left_alone` pins for a
    `RuntimeError`: an exception this API has no vocabulary for is not given one.
    """
    if not is_connection_shaped(exc):
        raise exc
    return on_domain_error(request, database_unavailable(exc, seam="api"))


@api.exception_handler(PermissionDenied)
def on_permission_denied(request: HttpRequest, exc: PermissionDenied) -> HttpResponse:
    return on_domain_error(request, Forbidden(str(exc) or None))


@api.exception_handler(ObjectDoesNotExist)
def on_does_not_exist(request: HttpRequest, exc: ObjectDoesNotExist) -> HttpResponse:
    """A `Model.DoesNotExist` that escaped a service.

    Answered exactly like `Http404`, and with the same body: a row that is not
    in the caller's tenant must be indistinguishable from a row that does not
    exist, or the 404 becomes an existence oracle.
    """
    return on_domain_error(request, NotFound())


@api.exception_handler(Http404)
def on_http_404(request: HttpRequest, exc: Http404) -> HttpResponse:
    return on_domain_error(request, NotFound())


@api.exception_handler(HttpError)
def on_http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
    """ninja's own refusal, said in the product's one envelope.

    **The last hole in the envelope, and it was the biggest one.** ninja's
    default handler answers any `HttpError` with `{"detail": str(exc)}` — no
    `code`, no `remedies` — and three quite different callers land on it:

    * `AuthenticationError`, which every route raises when no authenticator
      returned anything. `{"detail": "Unauthorized"}` was the very first refusal
      most integrators ever saw from this API, and the only one they could not
      branch on.
    * A door that deliberately refuses before reaching a service — `raise
      HttpError(403, "No tenant for this request.")` and its dozen siblings.
      Good sentences, no `code`.
    * Anything a product adds tomorrow, which inherits the same hole.

    Registering a handler for the base class closes all three at once, and it is
    genuinely the *base*: ninja looks handlers up along `type(exc).__mro__`, so
    the `Throttled` handler below still wins for a throttle, which is why it is
    not folded in here.

    **Translated, not reshaped.** The raise site's own sentence is kept — it is
    usually better than anything a generic mapper could write — and what is
    added is the `code` and the `remedies` the registry already holds for that
    class of refusal. A status this table has no refusal for is left to ninja,
    because inventing a domain meaning for a number nobody mapped would be the
    kind of guess this whole module exists to avoid.
    """
    refusal = REFUSAL_FOR_STATUS.get(exc.status_code)
    if refusal is None:
        return api.create_response(request, {"detail": str(exc)}, status=exc.status_code)
    # `AuthenticationError` and `AuthorizationError` carry no sentence anybody
    # wrote — ninja constructs them with the bare words "Unauthorized" and
    # "Forbidden", which are the framework's placeholders and not an answer to
    # the person holding them. Dropping the message lets the registered
    # `default_detail` speak, which is where this product's plain-language
    # sentence lives (the owner's 2026-08-23 ruling: no internal vocabulary on
    # the wire). Every other `HttpError` in the tree was raised with a real
    # sentence by somebody who knew the case, and keeps it.
    detail = None if isinstance(exc, (AuthenticationError, AuthorizationError)) else str(exc)
    detail = detail or None
    # `Invalid.__init__` takes `errors` first and `detail` by keyword; the others
    # take `detail` positionally. Said with the keyword so this reads the same
    # for both and cannot silently become an `errors` dict.
    if issubclass(refusal, Invalid):
        return on_domain_error(request, refusal(detail=detail))
    return on_domain_error(request, refusal(detail))


# --- the 422 joins the envelope ----------------------------------------
#
# THE HOLE THIS CLOSES. ninja answers a schema-validation failure with
# `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` at status 422: a
# LIST where every other refusal is an object, no `code` to branch on, and
# pydantic's own vocabulary (`extra_forbidden`, `value_error`) on the wire.
# `django-conventions` §6 used to bless it as "the one other shape", which made
# it doctrine rather than an oversight — and doctrine is what the owner's
# ruling of 2026-08-24 changed. An agent integrating against this API needed
# two refusal parsers, and the second one only ever fired on the request it
# most needed to understand: the one it got wrong.
#
# TRANSLATED, NOT INVENTED — and every fact comes from ninja's own error list.
# `loc[0]` is the parameter SOURCE (`body`, `query`, `path`, `header`, …), set
# by ninja from `__ninja_param_source__`; what follows is the path to the field
# inside it. Nothing here enumerates a route, a schema or a field name.
#
# WHICH CODE, AND WHICH NUMBER. A body error is `invalid_body` at 422, because
# the request never reached a route: it was not the shape this operation
# accepts. Anything else — a `?limit=` that is not a number, a path segment that
# is not a UUID — is `invalid` at 400, the code `derived_refusals` already
# documents for a route that narrows. Two codes because they have two fixes, and
# `invalid_body` is deliberately NOT honest about a query parameter. A mixed
# failure answers `invalid_body`: a body that did not parse is the larger fact,
# and the one that used to pass silently.

#: ninja's own name for the body parameter source, off `__ninja_param_source__`.
#: Read rather than spelled twice: `_has_body` above reads the same attribute
#: through `BODY_CONTENT_TYPES`, and the document and the refusal must agree
#: about what "a body" is.
BODY_SOURCE = "body"

#: What pydantic's `type` means, said to the person holding the refusal rather
#: than to the person who wrote the validator. Only the types whose own `msg`
#: is framework vocabulary are translated; everything else keeps ninja's
#: sentence, which is usually the better one ("Input should be a valid list").
#: A type that is not here is not a gap — it falls through to `msg`.
FIELD_SENTENCES: dict[str, str] = {
    # THE ENTRY THIS TABLE EXISTS FOR. pydantic says "Extra inputs are not
    # permitted", which describes the RULE. The caller needs to be told about
    # their request: this name is not a field here, so check the spelling.
    "extra_forbidden": "This field is not part of this operation. Check the spelling.",
    "missing": "This field is required.",
    "json_invalid": "The request body is not valid JSON.",
}

#: pydantic prefixes a custom validator's message with its own error class.
#: Stripped so the sentence a validator wrote reaches the wire on its own.
_PYDANTIC_PREFIXES = ("Value error, ", "Assertion failed, ")


def _field_name(loc: Sequence[Any]) -> str:
    """The caller's own name for the thing that failed, out of ninja's `loc`.

    `("body", "payload", "url")` is `url`. The first segment is the parameter
    SOURCE and the second is the name of the view's body PARAMETER — `payload`
    in every route in this tree — which is an artefact of how the route was
    written and means nothing whatever to the person who sent the JSON. Both
    come off.

    **A body error with nothing after the parameter name is about the body
    ITSELF**, not about a field: `loc == ("body", "payload")` is what ninja
    reports when the body is not even an object. That answers `body` — the
    caller's own word for what they sent, and the word the API document uses
    (`requestBody`). It used to answer `payload`, which published the view's
    parameter name to a caller who has never seen the view; the census in
    `apps/core/tests/test_strict_bodies.py` is what caught it, by deriving the
    body-parameter names off the mount and refusing to see one on the wire.

    Every other source names its field directly — `("query", "limit")` is
    `limit` — because a query parameter has no wrapper to be inside of; and a
    source with no path at all answers with the source, for the same reason the
    body does. Django's `__all__` is deliberately NOT used here: it is a
    framework's non-field key, and this is a real part of the request with a
    real name.

    A nested path keeps its shape, dotted: `lines.0.sku`. That is the JSON
    pointer a caller can actually walk down, and it is what an agent needs to
    correct its own request without re-reading the whole schema.

    **The one assumption, and it is measured**: a body arrives as a single
    parameter (`payload: WidgetIn`), so the segment after `body` is always the
    wrapper. ninja can also FLATTEN a body declared with `Body(...)`, and there
    is no such route in this tree — the census above is what would notice one,
    because a flattened body's top-level field would arrive here named `body`.
    """
    parts = list(loc)
    source = str(parts[0]) if parts else ""
    parts = parts[1:]
    if source == BODY_SOURCE and parts:
        parts = parts[1:]
    return ".".join(str(part) for part in parts) or source or NON_FIELD_KEY


def _field_sentence(entry: Mapping[str, Any]) -> str:
    """One error, said in plain language."""
    sentence = FIELD_SENTENCES.get(str(entry.get("type", "")))
    if sentence is not None:
        return sentence
    message = str(entry.get("msg") or "").strip()
    for prefix in _PYDANTIC_PREFIXES:
        if message.startswith(prefix):
            message = message[len(prefix) :]
    return message or "This value is not valid."


def _validation_refusal(exc: NinjaValidationError) -> Invalid:
    """ninja's validation error, recomposed into the registered grammar.

    The `errors` mapping is field -> messages, which is the shape `Invalid`
    already carries and `wire_refusal` already publishes — so nothing new
    reaches the wire but the `code`, the sentence and the remedies the registry
    holds. One composer, still.
    """
    errors: dict[str, list[str]] = {}
    unknown: list[str] = []
    from_body = False
    for entry in exc.errors:
        loc = entry.get("loc") or ()
        if loc and str(loc[0]) == BODY_SOURCE:
            from_body = True
        field = _field_name(loc)
        errors.setdefault(field, []).append(_field_sentence(entry))
        if str(entry.get("type", "")) == "extra_forbidden":
            unknown.append(field)

    refusal = InvalidBody if from_body else Invalid
    return refusal(errors, detail=_validation_sentence(unknown, errors))


def _validation_sentence(unknown: Sequence[str], errors: Mapping[str, list[str]]) -> str:
    """The one human sentence at the top of the body.

    It names the unknown fields explicitly, because that is the failure a caller
    is least able to see for themselves — a missing field or a wrong type is
    visible in their own request, while a field name that is *almost* right
    looks correct until somebody reads the schema beside it.
    """
    named = ", ".join(f"`{field}`" for field in dict.fromkeys(unknown))
    if unknown and len(errors) == len(set(unknown)):
        # No article on the singular: "has no field called `x`" reads, and "has
        # no a field called `x`" does not — "no" is already the determiner, so a
        # second one is one word of nonsense at the exact place the sentence
        # names the failure. The MCP twin has said this beside its own singular
        # (`apps/core/mcp.py::_argument_sentence`); this door was the
        # neighbour that had been declining to copy it.
        subject = "field" if len(set(unknown)) == 1 else "fields"
        return (
            f"This operation has no {subject} called {named}, so the request was "
            "refused rather than carried out without it. Nothing was changed."
        )
    if unknown:
        return (
            f"The request does not match the shape this operation accepts, and it "
            f"names {named}, which this operation does not have. See `errors` for "
            "every field."
        )
    return (
        "The request does not match the shape this operation accepts. See `errors` "
        "for each field and what is wrong with it."
    )


@api.exception_handler(NinjaValidationError)
def on_schema_validation(request: HttpRequest, exc: NinjaValidationError) -> HttpResponse:
    """Every schema-validation refusal, in the one envelope.

    Registered on ninja's own `ValidationError`, which is the only thing that
    raises it — `Operation._get_values` collects every parameter model's
    pydantic failure and re-raises them as one. Answered through
    `on_domain_error` like everything else, so the status comes from
    `STATUS_FOR` — 422 for a body, 400 for a query or path parameter — and the
    BODY comes from `core.exceptions.wire_refusal`, the one composer the machine
    door renders from too. **What changed is the body, not the status line**: a
    client that already branched on ninja's 422 keeps working, and now has a
    `code` to branch on instead of a list of pydantic dictionaries to read.
    """
    return on_domain_error(request, _validation_refusal(exc))


@api.exception_handler(Throttled)
def on_throttled(request: HttpRequest, exc: Throttled) -> HttpResponse:
    """ninja's rate-limit refusal, said in the domain's vocabulary.

    Same body and same `code` a service's own `RateLimited` produces, so a
    client that handles one handles both — it does not care which layer decided
    it was going too fast.
    """
    wait = getattr(exc, "wait", None)
    return on_domain_error(request, RateLimited(retry_after=int(wait) + 1 if wait else None))


# --- Which refusal each code IS, as a number -----------------------------------
#
# **DERIVED, since ADR core-23.** Every registered refusal that declared a
# `status=` at its declaring site is in this table, and nothing else is. What
# stood here before that was a hand-appended block — one `CODE_STATUS[...] =`
# line per refusal code, each with a comment explaining that the line existed
# only because the DOCUMENT is written off this table and `_document_operation`
# silently drops a code it has no number for (house rule 47). That made
# `config/api.py` the last file a purely-domain rung still had to edit, in a
# template whose first law is that registration is by discovery; three product
# rungs in a row paid the tax, and the block grew past the line range the queue
# row cited for it while the row was being read.
#
# **House rule 14 is untouched, and this is the part worth being careful about.**
# A status code is HTTP vocabulary and this module is still the only one that
# SPEAKS one: `on_domain_error` sets the status line, `status_for` decides it,
# `REFUSAL_FOR_STATUS` translates a route that spoke HTTP back into the domain's
# word. What moved is not the speaking but the KNOWING — a per-code fact into the
# registry that already carries every other per-code fact (the boundary, the
# fact, the remedies, the wire destinations). Rule 14's scan covers `services.py`,
# `selectors.py`, `models.py` and `policies.py`, and no `register_refusal` call
# in this tree lives in one of those; the rule does not fire and needs no
# `does_not_cover` clause for this.
#
# `apps.core.api.docs` writes the document and is handed this; it never decides
# it. A code with no declared status is absent here on purpose — see
# `CODE_STATUSES` in `apps/core/exceptions.py` for the two populations that
# depend on the absence.

CODE_STATUS: Mapping[str, int] = CODE_STATUSES


# --- The mount ---------------------------------------------------------------

for _prefix, _router in _discover_routers():
    api.add_router(f"/{_prefix}/", _router)


# --- ADR api-1: the document, finished ----------------------------------------
# Run once, after the mount, over the operations ninja has bound. Everything it
# writes is derived: nothing below reads a table of route names, and adding a
# route to any app carries the whole standard with it.


def _has_body(operation: Any) -> bool:
    return any(
        getattr(model, "__ninja_param_source__", "") in BODY_CONTENT_TYPES
        for model in operation.models
    )


# --- ADR ident-7: the token's ceiling, checked once, in the door plumbing -----
#
# WHERE, AND WHY IT IS HERE AND NOT IN A ROUTE. The check needs two things at
# once: the credential, which only exists after authentication has run, and the
# operation, which only this module has a handle on. A route could see both and
# would then be the fifty-first place the rule is written; an authenticator sees
# the credential and not which operation it is about to reach. So it goes
# between them — after `_run_checks` has authenticated and throttled, before
# ninja parses the body or calls the view. Nothing below the door is reached at
# all on a refusal, which is what makes "no audit row, no write" a property of
# the shape rather than something to remember.
#
# THE SCOPE IS COMPUTED ONCE, AT MOUNT. `required_scope` is a pure function of
# the operation's tag and method, and both are fixed the moment the router is
# bound — so a mistyped tag is an ImproperlyConfigured at import rather than a
# refusal nobody can explain at three in the morning.


def _refused_for_scope(request: HttpRequest, required: str | None) -> HttpResponse | None:
    """The refusal for this request, or `None` when it may pass.

    A session request has no ceiling to be under and passes untouched: scopes
    are a property of a credential handed to a machine, and a person at a
    browser did not hand anything to anybody. A token with no ceiling passes
    for the reason its column is nullable — that is what it was promised.

    `required is None` means the operation's scope could not be derived — a
    route carrying two tags, which house rule 41 refuses and which therefore
    cannot exist on a tree the gate has passed. It is answered **closed**: no
    ceilinged token may call it. An operation nothing can place is an operation
    no ceiling can be checked against, and the safe reading of "I cannot tell"
    is not "go ahead".
    """
    token = getattr(request, TOKEN_ATTR, None)
    if token is None:
        return None
    ceiling = token.scopes
    if ceiling is None:
        return None
    if required is not None and scopes.within_ceiling(ceiling=ceiling, scope=required):
        return None
    if required is None:
        return on_domain_error(
            request,
            scopes.InsufficientScope(
                "This operation does not say which scope reaches it, so a token "
                "limited to a set of scopes cannot be checked against it. Sign in "
                "with a session, or use a token minted with no limit."
            ),
        )
    return on_domain_error(
        request,
        scopes.InsufficientScope(
            f"This token is not scoped for that. It needs {required!r}, and it "
            f"carries {', '.join(repr(held) for held in sorted(ceiling)) or 'nothing'}. "
            "Mint a token that carries it, or make this call with a session instead."
        ),
    )


def _refused_for_surface(request: HttpRequest, family: str | None) -> HttpResponse | None:
    """The refusal for an operation this request's surface does not expose, or `None`.

    Beside the ceiling check and ASKED BEFORE AUTHENTICATION: whether this host
    offers the operation at all is a fact about the address, and answering a
    credential question first would tell an anonymous caller on a customer host
    that a staff door exists behind it. 404, never 403 — the reach-refusal
    posture. A total surface exposes everything, so a product that declares no
    surface never reaches the refusal.
    """
    surface = surfaces.of_request(request)
    if surfaces.exposes(surface, family):
        return None
    if surface is None:
        return on_domain_error(request, surfaces.SurfaceUnknownHost())
    return on_domain_error(request, surfaces.does_not_expose(surface))


def _refused_for_addressing(request: HttpRequest) -> HttpResponse | None:
    """The addressing-header law at the REST door (ADR core-21).

    WHERE, AND WHY IT IS HERE. The check needs the request *after* a credential
    has resolved — `ApiTokenAuth` is what puts a token's tenant and hat on the
    request at all — and it must reach every route in every app without any of
    them being edited, because a per-app guard is how one app came to strip its
    `X-Org` before checking it while its neighbours did not. This
    seam already holds both halves for the token ceiling; the law sits beside it.

    It runs BEFORE the ceiling check, and the order is the caller's: a client
    holding a mistyped header and a narrow token would otherwise be sent to mint
    a wider token, do so, and meet the header refusal it was always going to
    meet. Where you are acting is the more basic of the two questions.
    """
    refusal = request_addressing_refusal(request)
    if refusal is None:
        return None
    return on_domain_error(request, refusal)


def _guard_the_ceiling(operation: Any) -> None:
    """Put the ceiling check between one operation's authentication and its view.

    `_run_checks` is ninja's own name for "authenticate, then throttle, then
    say whether to go on", and wrapping it is how something lands *after* the
    credential resolved without re-resolving it. The attribute is asserted
    rather than assumed: if a future ninja renames it, this fails loudly at
    import, which is the right failure for a security check — the quiet
    alternative is a wrapper that silently never runs.

    **An operation whose scope will not derive is guarded closed, not skipped.**
    Two tags on one route is a house-rule-41 violation and cannot reach a tree
    the gate has passed — but MOUNTING is not the moment to discover it. Raising
    here took the whole API down at import, which took the gate's own diagnostic
    down with it (`document_api` runs at import, the checks read the mounted
    api, and every rule's canary died at once on the one malady they exist to
    report). So the mount survives, the route answers a session, no ceilinged
    token reaches it, and rule 41 says the true thing about the true cause.
    """
    inner = getattr(operation, "_run_checks", None)
    if inner is None:  # pragma: no cover - the tripwire, not a branch
        raise RuntimeError(
            "this ninja Operation has no `_run_checks`, so the token-ceiling check "
            "has nowhere to sit between authentication and the view (ADR ident-7). "
            "Nothing is mounted rather than mounted unguarded."
        )
    required = docs.derived_scope(tags=operation.tags or [], methods=operation.methods)
    family = _family(operation.tags)

    if operation.is_async:

        async def run_checks_async(request: HttpRequest) -> Any:
            elsewhere = _refused_for_surface(request, family)
            if elsewhere is not None:
                return elsewhere
            error = await inner(request)
            if error is not None:
                return error
            addressed = _refused_for_addressing(request)
            if addressed is not None:
                return addressed
            return _refused_for_scope(request, required)

        operation._run_checks = run_checks_async
        return

    def run_checks(request: HttpRequest) -> Any:
        elsewhere = _refused_for_surface(request, family)
        if elsewhere is not None:
            return elsewhere
        error = inner(request)
        if error is not None:
            return error
        addressed = _refused_for_addressing(request)
        if addressed is not None:
            return addressed
        return _refused_for_scope(request, required)

    operation._run_checks = run_checks


# --- a wrong METHOD answers in the API's own words too ------------------
#
# WHY A WRAP AND NOT A HANDLER. `PathView._sync_view` looks the operation up by
# method and, finding none, **returns** `_not_allowed()` — an
# `HttpResponseNotAllowed` carrying `b"Method not allowed"` as `text/html`. It
# raises nothing, so no `@api.exception_handler` can ever see it, and the
# request never reaches an operation so nothing per-route can either. The only
# seam holding both the request and that response is the pair of methods that
# produced it, which is why this is a wrap of a private attribute — the second
# in this module, sanctioned on the `_guard_the_ceiling` precedent.
#
# WHAT WAS REJECTED. Middleware sniffing every response for a 405 (it would
# rewrite answers this API did not make); patching `_not_allowed` (it has no
# request in scope, so the refusal would need a second sender); patching the
# class rather than the instance (it would reach every future mount, including
# a product's own second `NinjaAPI`); and waiting for upstream.
#
# THE ANSWER IS TRANSLATED, NOT INVENTED. The methods come from ninja's own
# `Allow` set and nowhere else — this module never enumerates what a path
# answers — and the header is copied across verbatim, because the header is the
# part a client is allowed to parse and a re-rendered one is a second opinion.


def _method_sentence(allowed: Sequence[str], attempted: str) -> str:
    """The refusal's sentence, in plain words, from ninja's own set of methods.

    "That path answers POST, not GET." — and with more than one, "That path
    answers GET or POST, not DELETE."

    Sorted so the sentence is the same every time: `HttpResponseNotAllowed` is
    built from a `set`, whose order is nobody's contract. The header keeps that
    original order; only the prose is sorted.
    """
    listed = sorted({method.strip() for method in allowed if method.strip()})
    if not listed:  # pragma: no cover - a path with no operations cannot be mounted
        return "That path does not answer this method."
    if len(listed) == 1:
        answers = listed[0]
    else:
        answers = f"{', '.join(listed[:-1])} or {listed[-1]}"
    if not attempted:  # pragma: no cover - Django always sets a method
        return f"That path answers {answers}."
    return f"That path answers {answers}, not {attempted}."


def _method_refusal(request: HttpRequest, refused: HttpResponseNotAllowed) -> HttpResponse:
    """ninja's 405, said in the one envelope, with its `Allow` header intact."""
    allow = refused[ALLOW_HEADER]
    response = on_domain_error(
        request,
        MethodNotAllowed(_method_sentence(allow.split(","), (request.method or "").strip())),
    )
    # Verbatim, byte for byte. A client that already handles a 405 by reading
    # `Allow` keeps working; the body is the part that got better.
    response[ALLOW_HEADER] = allow
    return response


def _speak_the_method_refusal(path_view: Any) -> None:
    """Put the envelope around one path's wrong-method answer.

    Per INSTANCE, like the ceiling guard: assigning the wrapper on the object
    shadows the class method for this mount alone, so a product that mounts a
    second `NinjaAPI` of its own is untouched by ours.

    Both halves are wrapped rather than whichever one this path happens to use,
    because `PathView.is_async` is a property of the operations bound to it and
    a product can make an existing path async by adding one route to it. Wrapping
    the pair costs nothing and removes the class of bug where the sync door
    speaks the envelope and the async door still answers markup.
    """
    inner_sync = getattr(path_view, "_sync_view", None)
    inner_async = getattr(path_view, "_async_view", None)
    if inner_sync is None or inner_async is None:
        raise RuntimeError(
            "this ninja PathView has no `_sync_view`/`_async_view`, so the method-refusal "
            "wrap has nowhere to translate a wrong METHOD into this API's refusal envelope. "
            "ninja returns `HttpResponseNotAllowed` rather than raising, so no "
            "exception handler can stand in for this wrap. Nothing is mounted rather "
            "than mounted answering `text/html` with no code."
        )

    def sync_view(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        answer = inner_sync(request, *args, **kwargs)
        if isinstance(answer, HttpResponseNotAllowed):
            return _method_refusal(request, answer)
        return answer

    async def async_view(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        answer = await inner_async(request, *args, **kwargs)
        if isinstance(answer, HttpResponseNotAllowed):
            return _method_refusal(request, answer)
        return answer

    path_view._sync_view = sync_view
    path_view._async_view = async_view


def _document_operation(path: str, operation: Any) -> None:
    """One route's prose, refusals and headers — all four derivations, applied.

    Called for every bound operation, including the ones a product adds, which
    is why nothing here is allowed to know a route by name.
    """
    view = operation.view_func
    contract = docs.contract_of(view)
    # The docstring's first line is the NAME this operation is listed under and
    # everything below it is the prose (ADR api-1 as amended 2026-08-24). They
    # are split here rather than at the docstring, because a docstring that
    # repeated its own title would have two places to edit and one of them would
    # go stale. `or operation.summary` keeps ninja's prettified function name for
    # a route that has no docstring at all — which house rule 41 refuses anyway,
    # and refusing it with a readable document beats refusing it with a blank one.
    operation.summary = docs.title_of(contract) or operation.summary
    operation.description = docs.description_of(contract) or operation.description

    authenticated = bool(operation.auth_callbacks)
    declared = docs.declared_refusals(view)
    if declared is not None:
        # ADDITIVE over the door's own refusals. `@refuses(...)`
        # corrects what the SHAPE derivation says this route DOES; it is not a
        # claim about what the mount does to every request on the way in, and
        # all eight routes that carry one were publishing contracts that omitted
        # the 403 their own middleware can answer with.
        codes = docs.with_door_level(declared, authenticated=authenticated)
    else:
        codes = docs.derived_refusals(
            methods=operation.methods,
            has_path_params="{" in path,
            has_body=_has_body(operation),
            authenticated=authenticated,
            idempotent_methods=IDEMPOTENT_METHODS,
            # THE ONE SEAM (ADR core-24), and not `view._ninja_is_paginated`.
            # The marker says `@paginate` was applied; the question this
            # derivation is really asking is whether a caller can be handed a
            # cursor by this route, and three routes hand one out without ever
            # touching the decorator. Reading the marker meant the document
            # derived no `invalid_cursor` for those three — a refusal a
            # generated client had no branch for, which is rule 47's whole
            # defect. `answers_cursor_envelope` is the same predicate rule 3's
            # census and `introspect` read, so a route cannot be a list here and
            # not a list there.
            paginated=answers_cursor_envelope(operation),
        )
    # `@also_refuses(...)` ADDS to whichever set the route publishes — the
    # derived one or its `@refuses` one — and never replaces it.
    codes = docs.with_added(codes, view)

    by_status: dict[int, list[str]] = {}
    for code in codes:
        status = CODE_STATUS.get(code)
        if status is not None:
            by_status.setdefault(status, []).append(code)
    # The kind this operation answers for fills a registered remedy's `<noun>`
    # slot, as the raise site's `noun` fills it on the wire (one declaration).
    noun = docs.noun_of(getattr(operation, "url_name", None), path)
    responses: dict[int, Any] = {
        status: docs.refusal_response(group, noun=noun)
        for status, group in sorted(by_status.items())
    }
    if authenticated:
        # It IS a domain refusal now, so it is documented the way every
        # other one is: off the registry, through the same `refusal_response`
        # that writes the fact and the remedies. Hand-written prose here used to
        # be the only choice, and it was also the only response in the document
        # a generated client had nothing to switch on for — the body really did
        # arrive with no `code`, so the document was honest and the wire was the
        # thing that was wrong. Both are fixed, in that order.
        responses[401] = docs.refusal_response([Unauthenticated.code])

    parameters: list[dict[str, Any]] = []
    if authenticated:
        parameters.append(
            docs.header_parameter(
                name=TENANT_HEADER,
                description=(
                    "Which tenant to act in, by slug. **Omit it** and you act in your "
                    "default membership's tenant, which is the ordinary case. **Send it** "
                    "and it is honoured or the request is refused: a tenant you hold no "
                    "membership in, one that does not exist, one a pinned token may not "
                    "act in, and an empty value are all refused with "
                    "`addressing_header_not_honoured` (403) — identically, so the refusal "
                    "says nothing about what exists. Nothing is read and nothing is "
                    "written. The value is trimmed and lower-cased before it is matched, "
                    "and an empty or whitespace-only value counts as SENT."
                ),
            )
        )
        parameters.append(
            docs.header_parameter(
                name=ORG_HEADER,
                description=(
                    "Which PART of the tenant to act as, by slug — the hat you are wearing. "
                    "It must be an organization you hold a membership on, or above; roles "
                    "inherit downwards only, so naming your parent or a sibling is not "
                    "wearable. **Omit it** and you act in your default membership's own "
                    "node. **Send one you cannot wear** — or an empty value — and the "
                    "request is refused with `addressing_header_not_honoured` (403) rather "
                    "than answered under another hat. The value is trimmed and lower-cased "
                    "before it is matched, and an empty or whitespace-only value counts as "
                    "SENT."
                ),
            )
        )
    if set(operation.methods) & set(IDEMPOTENT_METHODS):
        parameters.append(
            docs.header_parameter(
                name=IDEMPOTENCY_HEADER,
                description=(
                    "A key of your choosing that makes this write safe to retry. An "
                    f"identical retry replays the first answer and carries "
                    f"`{REPLAYED_HEADER}: true`; the same key with a different body is "
                    "refused rather than executed."
                ),
            )
        )
        # The RESPONSE half of this header is not written here: it is declared
        # beside its writer and stamped onto the finished document by
        # `docs.add_response_headers` (`ContractAPI.get_openapi_schema`), with
        # every other response header, off one population.

    parameters.extend(_retired_query_parameters(operation))

    extra: dict[str, Any] = {}
    if parameters:
        extra["parameters"] = parameters
    if responses:
        extra["responses"] = responses
    # The scope line goes on the PUBLISHED description and not on
    # `operation.description`, and the distinction is load-bearing. House rule
    # 41 holds `operation.description` to being exactly what the docstring
    # derives, so that a hand-written second copy of the contract cannot exist;
    # this is not a second copy, it is a derivation — the same function the
    # door enforces with, printed where a caller reads. Putting it here keeps
    # both true: the docstring stays the only prose anybody writes, and the
    # document a client fetches says which scope each call needs.
    #
    # It goes through `docs.derived_scope`, which ANSWERS `None` where
    # `required_scope` would raise, and the difference between those two is the
    # difference between a document and a check. A route that derives nothing is
    # broken, and rule 41 is the thing that says so — but it can only say so
    # about a document that exists, so rendering skips the sentence and carries
    # on rather than taking the whole API down at import and every rule's canary
    # with it.
    #
    # And WHICH sentence is decided here too, off the operation's own
    # authenticators. A route that narrowed its `auth=` to a session-only
    # pair is reached by no bearer token at all, so the scope sentence — mint a
    # token carrying this, or widen the one you have — is a set of instructions
    # that loops. The mint route was publishing exactly that about itself. The
    # predicate reads what each authenticator publishes as its own security
    # scheme, which is the same fact ninja writes into `security`, so the footer
    # and the security block are one derivation and cannot disagree.
    extra["description"] = docs.with_required_scope(
        operation.description or "",
        docs.derived_scope(tags=operation.tags or [], methods=operation.methods),
        reachable_by_token=docs.reachable_by_token(operation.auth_callbacks),
    )
    extra.update(docs.url_name_extension(operation))
    operation.openapi_extra = {**(operation.openapi_extra or {}), **extra}


def document_api() -> None:
    """Apply ADR api-1 and ADR ident-7 to everything the mount has bound.

    One pass, because they read the same facts off the same two objects: the
    operation's tag and method, and the path's own set of methods. Idempotent;
    run once at import — the method wrap re-applied would simply see an answer
    that is no longer an `HttpResponseNotAllowed` and pass it through.
    """
    for bound in api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            full = "/".join(part for part in (bound.prefix, path) if part)
            for operation in path_view.operations:
                _document_operation(full, operation)
                _guard_the_ceiling(operation)
            # Per PATH, not per operation: which methods a path answers is a
            # property of the path, which is also why nothing below documents a
            # 405 on an operation. The 405 belongs to the URL.
            _speak_the_method_refusal(path_view)


document_api()


# --- an unmatched path under the API answers in the API's own words -----


def api_not_found(request: HttpRequest, unmatched: str = "") -> HttpResponse:
    """The JSON 404 for a path under `/api/v1/` that no route claims.

    Mounted by `config/urls.py` **after** the API, so it is only reached once
    Django's resolver has failed inside it — a registered route's own 404 still
    comes from its own refusal, byte-identical, and nothing here can shadow one.

    It answers through `on_domain_error` rather than building a body, because
    the body has one composer (`core.exceptions.wire_refusal`) and a second one
    here would be the fourth copy of the rule house rule 14 exists to prevent.
    A JSON API that serves a page of HTML to a typo has told its first-time
    caller that the contract is a suggestion.
    """
    return on_domain_error(request, NotFound("No route under this API matches that path."))


# --- the other half of the seam, above the middleware chain ----------
#
# WHY A SECOND ENTRY POINT AND NOT A SECOND SEAM. `on_operational_error` above
# owns the status and the body; so does this. Neither composes anything: both
# call `on_domain_error`, which reads `STATUS_FOR` and `wire_refusal`. What is
# doubled is the place a fault can be CAUGHT, because a fault has more than one
# place it can erupt — and that was the lead's overrule of the one-mapper frame.
# A measured 6,973 connection errors did not come from views. The first statement
# of an authenticated request is the session read `TenantMiddleware` triggers,
# and `IdempotencyMiddleware`'s replay lookup is the next — both above ninja,
# where no `@api.exception_handler` is ever consulted. (The token lookup is not
# in that list, and the difference was measured rather than assumed: ninja's
# `_run_authentication` catches for itself, so `on_operational_error` above
# reaches it. The middleware chain is what nothing inside ninja can see.)
#
# WHY `handler500` AND NOT A MIDDLEWARE. A middleware at the top of `MIDDLEWARE`
# would be the textbook answer and it is not available here: `MIDDLEWARE`
# lives in `config/settings/base.py`, a shared file this module does not own,
# and the standing rule about a shared file is not suspended because the edit
# would be one line. `handler500` needs no settings entry — Django reads it off the
# root URLconf — and it catches strictly more: `BaseHandler.load_middleware`
# wraps EVERY middleware in `convert_exception_to_response`, so a fault in the
# outermost one arrives here too, which a middleware below it could not see.
# The cost is stated below. If a later cycle wants the middleware form, the
# seam moves and neither the status table nor the composer changes.
#
# WHAT IT DELIBERATELY DOES NOT DO. It classifies; it does not widen. Anything
# `is_connection_shaped` will not claim is handed straight to Django's own
# `server_error`, byte for byte what this deployment answered before this
# function existed — a query bug still 500s, and a deadlock still 500s.


def api_server_error(request: HttpRequest) -> HttpResponse:
    """Django's last-resort handler, taught one refusal and no others.

    Mounted as `handler500` in `config/urls.py`. Django calls an error handler
    with the request alone, from inside the `except` block in
    `django.core.handlers.exception.response_for_exception` — so the exception
    is the one `sys.exc_info()` is currently handling, and reading it there is
    reading what Django is in the middle of answering, not guessing at it.

    **The cost, stated rather than discovered.** Reaching here means Django has
    already sent `got_request_exception`, so an error tracker records the outage
    and the test client's default is to re-raise at the caller. That is correct
    for an outage — it IS an incident — and it is why `apps/core/tests/`
    drives these depths with `raise_request_exception=False`: a real HTTP client
    receives the response, and the response is what the contract is about.
    """
    _, exc, _ = sys.exc_info()
    if exc is not None and is_connection_shaped(exc):
        return on_domain_error(request, database_unavailable(exc, seam="handler500"))
    return server_error(request)


# --- The face's boot question: which surface is this address? ------------------


class SurfaceOut(Schema):
    """Which surface this address is, and what the face draws on it."""

    surface: str
    screens: list[str] | Literal["*"]
    tenant_rule: str


def surface_view(request: HttpRequest) -> HttpResponse:
    """Which surface this address is: its key, its screens and how it chooses the workspace.

    The one face asks it at boot and draws that surface's screens. Unauthenticated
    because it is asked before anybody signs in, and it says only what the
    address already is — the surface's key, its screens and its tenant rule —
    never a family, a door or another surface. A host no surface is bound to
    never reaches it: the middleware answered that request already.

    A plain view under the version segment speaks the API's vocabulary like the
    catch-all beside it: a wrong method is the API's own 405, in the one
    envelope, and the mount exempts it from CSRF because it reads and writes
    nothing a forged request could reach.
    """
    if request.method not in ("GET", "HEAD"):
        return _method_refusal(request, HttpResponseNotAllowed(["GET", "HEAD"]))
    surface = surfaces.of_request(request)
    if surface is None:
        refusal = surfaces.SurfaceUnknownHost()
        return JsonResponse(wire_refusal(refusal), status=status_for(refusal))
    listed = surfaces.named(surface.screens)
    screens: list[str] | Literal["*"] = "*" if listed is None else sorted(listed)
    body = SurfaceOut(surface=surface.key, screens=screens, tenant_rule=surface.tenant_rule)
    return JsonResponse(body.model_dump())
