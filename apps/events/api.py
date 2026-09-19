"""The subscription door onto the event spine: endpoints, the catalogue, dead letters.

The spine has had an outbox, signed deliveries, retries and dead-lettering from
the start, and until now not one line of it was reachable by anybody who was
not holding a shell (house rule 42; the owner's ruling). This is that
surface, and it is three questions a subscriber actually asks:

* **where do you send my events** — endpoints, created, read, changed, paused,
  resumed, and given a new signing key;
* **what events are there** — the catalogue, which is *derived* from the
  installed apps' own `events.py` declarations and is therefore incapable of
  going stale; and
* **what did you fail to send me** — deliveries, the dead letters among them,
  and a way to send one again.

## The one shape to read this file for

**The signing key is answered exactly once, at the moment it is minted, and
there is no second reader anywhere.** `POST /webhook-endpoints/` and `POST
/webhook-endpoints/{id}/secret/` answer `WebhookEndpointSecretOut`; every other read of
an endpoint answers `WebhookEndpointOut`, which has **no secret field at all**.
That is not a filter somebody remembered to apply — it is a schema with nowhere
to put one, which is the difference between a rule and a habit. A subscriber
that loses the key issues a new one; a key that could be read a second time
would be a key that leaks twice, and the ADR (events-4) rejected re-reading it
behind a permission for exactly that reason.

## What is deliberately NOT here

* **No `emit` door.** A caller who could name an event name and a payload could
  publish `billing.invoice.paid` to every subscriber the tenant has, signed with
  the tenant's own key. What may be emitted lives with the write that emits it;
  `services.emit` carries the `# door:` reason.
* **No endpoint delete.** `Delivery.endpoint` is `PROTECT` on purpose: the
  deliveries are the record of what was sent to whom, and an endpoint that is
  finished with is *paused*, not erased. The absence is the contract, the same
  way the absence of an entry PATCH is in the example app.
* **No `is_active` in the PATCH body.** Pausing and resuming are verbs on their
  own sub-paths, so the audit trail says which act happened rather than that a
  column changed.

Tenancy, and why neither half of house rule 24 appears below: `Event`,
`WebhookEndpoint` and (through its event) `Delivery` are **tenant**-scoped and
not org-scoped. A subscription is a property of the whole tenant — one place its
events go — so there is no `visible_to` to chain and no `may_be_named` fence to
state (house rule 26 reads FK-target arguments to services that write *org*-
scoped rows). Said out loud rather than left as an absence a reviewer has to
infer.

The routes never say 404. `selectors.get_endpoint` and `get_delivery` raise
`NotFound` and `config/api.py` is the only module that turns that into a number,
so the MCP tool over the same selector refuses byte-identically without
repeating the rule.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a
# `FilterSchema` parameter comes out as an unresolvable forward reference.

from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by, searched
from apps.core.api.docs import Tag
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.events.events import declared_names
from apps.events.models import Delivery, WebhookEndpoint
from apps.events.schemas import (
    DeliveryFilter,
    DeliveryOut,
    EventTypeOut,
    WebhookEndpointFilter,
    WebhookEndpointIn,
    WebhookEndpointOut,
    WebhookEndpointPatch,
    WebhookEndpointSecretOut,
)
from apps.events.selectors import (
    dead_lettered,
    get_delivery,
    get_endpoint,
    list_deliveries,
    list_endpoints,
)
from apps.events.services import (
    deactivate_endpoint,
    enqueue_replay,
    issue_endpoint_secret,
    register_endpoint,
    resume_endpoint,
    update_endpoint,
)

# **The root of `/api/v1/`** (ADR api-2, the owner's 2026-08-24 ruling): the
# first path segment names a RESOURCE, never an app. This app serves four of
# them and two needed better names once the `events/` skirt came off:
# `endpoints` alone says nothing on a wire that also has OAuth endpoints, so it
# is `/webhook-endpoints/`; and a catalogue is a document where this is a
# collection, so it is `/event-types/` — which is the noun its own `url_name`
# stem (`event_type`) already used. `/deliveries/` and `/dead-letters/` are
# unchanged. House rule 32 refuses the regression.
PREFIX = ""

# What `?ordering=` may name, and nothing else. Straight into `.order_by()` it
# would let a client sort by any column and traverse any relation — a full-table
# sort on an unindexed column at best, a read across a join at worst.
ENDPOINT_ORDERING = ("created_at", "updated_at", "url")
DELIVERY_ORDERING = ("created_at", "updated_at", "delivered_at", "dead_lettered_at", "attempts")

# What `?q=` searches on the endpoint list. Text columns on this row; never a
# related table's, or the search becomes a join nobody sized. The secret is not
# among them and could not be: it is encrypted per row, so two endpoints holding
# the same key hold different ciphertext and there is nothing to match against.
ENDPOINT_SEARCH_FIELDS = ("url", "description")

# What this app's tag is FOR, declared in the app that owns the tag and
# collected into the OpenAPI document's `tags` section by `config/api.py`'s
# discovery (ADR api-1). A reader meets the group before the routes in it, and
# house rule 41 is what notices a tag nobody described.
TAGS = {
    "events": Tag(
        "Webhooks & events",
        "Webhook subscriptions and what became of them: where a tenant's events "
        "are delivered, which events exist to subscribe to, and every delivery "
        "attempt including the ones that gave up. The signing key is answered "
        "once, when it is minted, and is never readable again — every other read "
        "of an endpoint has no field for it.",
        plane="administrative",
        plane_note=(
            "webhook subscriptions: where this tenant's events are delivered, and what became of "
            "each delivery."
        ),
    ),
}

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call these routes.
router = Router(tags=["events"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as.

    Authentication has already guaranteed the user; nothing has guaranteed the
    tenant. A signed-in user with no membership resolves to `None`, and a write
    with no tenant is refused rather than guessed at.

    **Whether the actor may do the thing is not decided here** — `services.py`
    calls `authz.require`, and `policies.py` says the subscription surface is an
    owner-or-admin one. A permission check in this function would be a second
    copy of the rule, one per door.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


def with_secret(endpoint: WebhookEndpoint) -> WebhookEndpointSecretOut:
    """The endpoint **and its plaintext key** — the one shape that carries one.

    Called from exactly two places on each door: registering an endpoint, and
    issuing it a new key. Both have just come back from the service that wrote
    the encrypted column, so `endpoint.secret` here is the plaintext that was
    minted a moment ago and exists nowhere else outside the database.

    It lives in this module rather than being written twice because `mcp.py`
    imports it, the same way it imports `ENDPOINT_ORDERING`: a "shown once"
    guarantee that two doors implement separately is a guarantee one of them
    will stop implementing.
    """
    return WebhookEndpointSecretOut(
        endpoint=WebhookEndpointOut.from_orm(endpoint),
        secret=endpoint.secret,
    )


def event_catalogue() -> list[EventTypeOut]:
    """Every event name this deployment can emit — **one implementation, both doors**.

    It lives here rather than in `selectors.py` because it does not return a
    queryset: it reads no table at all. The population is the installed apps'
    own `events.py` declarations (`events.declared_names()`), which is the same
    registry `emit` validates an outbound name against and the same one
    `manage.py introspect` prints.

    **Derived, so it cannot rot.** A hand-listed catalogue is wrong the morning
    after the next app declares an event, and nothing fails — the queue's cycle-0
    finding #8, in the owner's own words. This one is a census, so the day
    `apps.orders` declares `orders.order.placed`, the catalogue has it and no
    file changed.

    It is the same for every tenant on the deployment, deliberately: the
    catalogue is the product's vocabulary, not a customer's data. Which of those
    names a given tenant has *subscribed* to is `event_names` on its endpoints.

    Sorted by name, so the page a client gets back is stable between calls and
    two pages of it do not overlap.
    """
    return sorted(
        (
            EventTypeOut(name=name, app=app_label)
            for app_label, names in declared_names().items()
            for name in names
        ),
        key=lambda entry: entry.name,
    )


# --- Endpoints ----------------------------------------------------------------


@router.get("/webhook-endpoints/", response=list[WebhookEndpointOut], url_name="endpoint-list")
@paginate(CursorPagination)
def list_endpoints_route(
    request: TenantRequest,
    filters: Query[WebhookEndpointFilter],
    q: str | None = None,
    ordering: str = "-created_at",
) -> QuerySet[WebhookEndpoint]:
    """List webhook endpoints

    List the webhook endpoints registered for the tenant you are acting in.

    Returns `{"items": [...], "has_more": ..., "next_cursor": ...}`. Walk it
    with `?cursor=` and `?limit=` (50 at a time by default, 200 at most), and
    ask for `count` with `?include_count=true` when you need a total.

    Query parameters:

    * `is_active` — `true` for endpoints that are currently receiving,
      `false` for paused ones. Omit it to get both.
    * `q` — free-text search over the endpoint URL and its description.
    * `ordering` — `created_at`, `updated_at` or `url`, optionally prefixed
      with `-` to reverse. Anything else is rejected. Defaults to
      `-created_at`.

    **Paused endpoints appear here too.** If an integration has gone quiet,
    this is where you find out that someone paused it: look at `is_active`.

    No response from this API ever contains a signing secret, including this
    one. The secret is returned only when it is created or reissued.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept.
    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: any member of the tenant may
      see where its events go. Registering, updating, pausing, resuming and
      re-keying an endpoint are the owner-or-administrator acts.
    * `403 forbidden` — your role here does not let you read webhook endpoints. A
      role with no read of this kind reads none of them: ask an administrator
      for the permission, or act under an organization where you hold it.
    * `403 forbidden` — your role here does not let you read webhook endpoints. A
      role with no read of this kind reads none of them: ask an administrator
      for the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `list_endpoints(active_only=False)` — the selector defaults to the active
    ones because the delivery fan-out wants exactly those; a door that is
    *about* the endpoints wants all of them.
    """
    actor, tenant = _acting(request)
    endpoints: QuerySet[WebhookEndpoint] = list_endpoints(
        tenant=tenant, active_only=False, actor=actor
    )
    endpoints = filters.filter(endpoints)
    endpoints = searched(endpoints, q, fields=ENDPOINT_SEARCH_FIELDS)
    return ordered_by(endpoints, ordering, allowed=ENDPOINT_ORDERING, default="-created_at")


@router.post(
    "/webhook-endpoints/", response={201: WebhookEndpointSecretOut}, url_name="endpoint-create"
)
def create_endpoint_route(
    request: TenantRequest, payload: WebhookEndpointIn
) -> Status[WebhookEndpointSecretOut]:
    """Create a webhook endpoint

    Register a URL to receive webhooks. **The signing secret is returned once, here.**

    Send:

    * `url` — where we will POST each event. Required.
    * `event_names` — the events you want. Leave it out or send `[]` to
      receive **every** event. Names must come from `GET /event-types/`.
    * `description` — a label for your own use.

    You get back `{"endpoint": {...}, "secret": "..."}`. **Save the `secret`
    now.** This is the only response that will ever contain it — reading the
    endpoint back later returns no secret field at all. If you lose it, call
    `POST /webhook-endpoints/{id}/secret/` to get a new one; that immediately
    invalidates the old one.

    You cannot choose your own secret; we generate it.

    **Verifying a delivery.** Each webhook arrives with two signature headers,
    both keyed on your secret. Check either one. Prefer `X-Signature-V2`.

    `X-Signature-V2: t=<seconds>,sha256=<hex>` — read the number after `t=`
    (Unix seconds). Join it to the **exact bytes of the request body** with a
    single `.` between them, so the bytes you hash begin
    `1750000000.{"id":` and end with the last byte of the body. Compute
    HMAC-SHA256 of that, hex-encode it, and compare it with the value after
    `sha256=` using a constant-time comparison. Then check that `t` is within
    **five minutes** of your own clock, and reject the delivery if it is not.
    Both checks must pass. The time check is the point of this header: without
    it, anyone who captured one delivery could send you the same bytes again a
    year later and they would still verify. Every attempt is signed at the
    moment it is sent, so a retry or a replay hours later carries a fresh `t`
    and passes the time check — use `X-Event-Id`, never `t`, to spot duplicates.

    `X-Signature: sha256=<hex>` — the original scheme. HMAC-SHA256 of the exact
    bytes of the request body, hex-encoded and prefixed with `sha256=`. It
    signs no timestamp, so a copy of a delivery verifies against it for as long
    as your secret lives. It is still sent on every delivery and we will not
    withdraw it without telling you first — but move to `X-Signature-V2` when
    you can.

    For either header: hash the bytes you received. Do not parse the JSON and
    re-encode it, or the signature will not match.

    Each delivery also carries `X-Event-Name`, `X-Event-Id` and
    `X-Correlation-Id`; `X-Event-Id` is stable across retries and replays, so
    use it to ignore duplicates.

    Refusals you can get here:

    * `400 invalid` — an `event_names` entry that is not in the catalogue, or a
      malformed URL. The `errors` object names the field. Nothing is created.
    * `409 conflict` — you already have an endpoint registered on that URL.
    * `403 forbidden` — you are not an owner or an administrator of the tenant.

    ---
    `Status(201, ...)` with a composed body rather than the row, because the row
    alone cannot express "and here is the key, once". `with_secret` is shared
    with `mcp.py` so the two doors cannot come to disagree about what "once"
    means.
    """
    actor, tenant = _acting(request)
    endpoint = register_endpoint(
        tenant=tenant,
        actor=actor,
        url=payload.url,
        event_names=payload.event_names,
        description=payload.description,
    )
    return Status(201, with_secret(endpoint))


@router.get(
    "/webhook-endpoints/{endpoint_id}/", response=WebhookEndpointOut, url_name="endpoint-detail"
)
def retrieve_endpoint(request: TenantRequest, endpoint_id: UUID) -> WebhookEndpoint:
    """Retrieve a webhook endpoint

    Fetch one webhook endpoint by id.

    The response never contains the signing secret — there is no field for it.
    Secrets are returned only when created or reissued.

    Refusals you can get here:

    * `404 not_found` — no such endpoint, **or** it belongs to someone else. Those
      two cases answer identically and on purpose, so that guessing ids tells
      you nothing about what exists.
    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: any member of the tenant may
      see where its events go.
    """
    actor, tenant = _acting(request)
    return get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=actor)


@router.patch(
    "/webhook-endpoints/{endpoint_id}/", response=WebhookEndpointOut, url_name="endpoint-update"
)
def update_endpoint_route(
    request: TenantRequest, endpoint_id: UUID, payload: WebhookEndpointPatch
) -> WebhookEndpoint:
    """Update a webhook endpoint

    Change an endpoint's URL, subscription list or description.

    Send only the fields you want to change; anything you leave out is kept as
    it is. Send `event_names: []` to go back to receiving every event.

    Three fields can be changed here and no others. To stop or restart
    deliveries use `POST .../pause/` and `POST .../resume/`; to replace the
    signing secret use `POST .../secret/`. There is no field on this request
    that does either of those.

    Refusals you can get here:

    * `400 invalid` — an `event_names` entry that is not in `GET /event-types/`, or a
      malformed URL. The `errors` object names the field, and nothing is
      changed.
    * `409 conflict` — another of your endpoints already uses that URL.
    * `404 not_found` — no such endpoint, or it is not yours.
    * `403 forbidden` — you are not an owner or an administrator of the tenant.

    ---
    `is_active` and `secret` are verbs on sub-paths rather than settable
    columns: a column a client can set is a column a client can set back by
    accident, and the audit trail should say which act happened rather than
    that a row changed.
    """
    actor, tenant = _acting(request)
    endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=actor)
    return update_endpoint(
        tenant=tenant,
        actor=actor,
        endpoint=endpoint,
        url=payload.url,
        event_names=payload.event_names,
        description=payload.description,
    )


@router.post(
    "/webhook-endpoints/{endpoint_id}/secret/",
    response=WebhookEndpointSecretOut,
    url_name="endpoint_secret-issue",
)
def issue_endpoint_secret_route(
    request: TenantRequest, endpoint_id: UUID
) -> WebhookEndpointSecretOut:
    """Replace a signing secret

    Replace this endpoint's signing secret. **The new one is returned once, here.**

    Send no body. You get back `{"endpoint": {...}, "secret": "..."}` — the same
    shape registering an endpoint returns, and the only other response in this
    API that contains a secret. Save it now; it is not readable again.

    **The old secret stops working immediately.** There is no grace period and
    no second valid secret: the very next delivery is signed with the new one,
    so update your receiver before or immediately after calling this. If you
    need a clean cutover with no rejected deliveries, register a second
    endpoint, move your traffic to it, then pause the first.

    Refusals you can get here:

    * `404 not_found` — no such endpoint, or it is not yours.
    * `403 forbidden` — you are not an owner or an administrator of the tenant.

    ---
    200 rather than 201: nothing was created — one endpoint has a new key.
    """
    actor, tenant = _acting(request)
    endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=actor)
    return with_secret(issue_endpoint_secret(tenant=tenant, actor=actor, endpoint=endpoint))


@router.post(
    "/webhook-endpoints/{endpoint_id}/pause/",
    response=WebhookEndpointOut,
    url_name="endpoint-pause",
)
def pause_endpoint_route(request: TenantRequest, endpoint_id: UUID) -> WebhookEndpoint:
    """Pause a webhook endpoint

    Stop sending webhooks to this endpoint. Send no body.

    The endpoint stays in your list with `is_active: false`, and its delivery
    history is kept.

    **Events that happen while it is paused are not queued up for it.** They are
    simply not sent to this endpoint, and resuming later does not backfill them.
    `GET /deliveries/?endpoint_id=…` shows what it did receive, ending where the
    pause began.

    There is no way to delete an endpoint, deliberately: deleting it would take
    the record of what was sent to it with it. Pausing is how you retire one.

    Refusals you can get here:

    * `404 not_found` — no such endpoint, or it is not yours.
    * `403 forbidden` — you are not an owner or an administrator of the tenant.
    """
    actor, tenant = _acting(request)
    endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=actor)
    return deactivate_endpoint(tenant=tenant, actor=actor, endpoint=endpoint)


@router.post(
    "/webhook-endpoints/{endpoint_id}/resume/",
    response=WebhookEndpointOut,
    url_name="endpoint-resume",
)
def resume_endpoint_route(request: TenantRequest, endpoint_id: UUID) -> WebhookEndpoint:
    """Resume a webhook endpoint

    Start sending webhooks to a paused endpoint again. Send no body.

    Deliveries resume from now on. **Nothing from the pause is backfilled** —
    those events were never sent to this endpoint and are not held anywhere for
    it. Its signing secret is unchanged, so your receiver needs no update.

    Refusals you can get here:

    * `404 not_found` — no such endpoint, or it is not yours.
    * `403 forbidden` — you are not an owner or an administrator of the tenant.

    ---
    A specific failed delivery can still be sent again through
    `POST /dead-letters/{id}/replay/`; that is a different question and a
    deliberate act with a row to point at.
    """
    actor, tenant = _acting(request)
    endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=actor)
    return resume_endpoint(tenant=tenant, actor=actor, endpoint=endpoint)


# --- The catalogue ------------------------------------------------------------


@router.get("/event-types/", response=list[EventTypeOut], url_name="event_type-list")
@paginate(CursorPagination)
def list_event_types_route(request: TenantRequest) -> list[EventTypeOut]:
    """List event types

    List every event name you can subscribe to.

    Returns `{"items": [{"name": ..., "app": ...}], "has_more": ...,
    "next_cursor": ...}`, sorted by name, walked with `?cursor=` and `?limit=`
    (50 at a time by default, 200 at most). `count` arrives only with
    `?include_count=true`.

    Every value you can put in an endpoint's `event_names` is here — anything
    else is rejected when you register or update the endpoint. Names read
    `<area>.<thing>.<what-happened>`, for example `example.widget.created`, and
    `app` tells you which part of the product emits it.

    This list is generated from the running system, so it is always the complete
    and current set. It is the same for every customer: it describes what the
    product can emit, not what you happen to have subscribed to.

    Refusals you can get here:

    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: this is the product's own
      vocabulary, the same for every customer, and any member may read it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Ordered by name in `event_catalogue()`, which is what makes paging over it
    stable; there is no ordering parameter because there is nothing else to
    order by.
    """
    return event_catalogue()


# --- Deliveries ---------------------------------------------------------------


@router.get("/deliveries/", response=list[DeliveryOut], url_name="deliveries-list")
@paginate(CursorPagination)
def list_deliveries_route(
    request: TenantRequest,
    filters: Query[DeliveryFilter],
    ordering: str = "-created_at",
) -> QuerySet[Delivery]:
    """List webhook deliveries

    List every webhook we have tried to send you, newest first.

    Returns `{"items": [...], "has_more": ..., "next_cursor": ...}`, walked
    with `?cursor=` and `?limit=`; `count` arrives only with
    `?include_count=true`. Failures are included — this is the log you read when a
    webhook did not arrive.

    Query parameters:

    * `status` — `pending` (being retried), `delivered`, `failed` (the last
      attempt failed, more are coming) or `dead` (we gave up).
    * `endpoint_id` — narrow to one endpoint.
    * `ordering` — `created_at`, `updated_at`, `delivered_at`,
      `dead_lettered_at` or `attempts`, optionally prefixed `-`. Defaults to
      `-created_at`.

    Each row is one event's delivery to one endpoint, and there is exactly one
    row per pair however many times we try. So `attempts` is the running total
    across every retry and every replay, `last_code` and `last_error` are what
    your server said the last time we asked, `delivered_at` is when it
    succeeded, and `dead_lettered_at` is when we stopped trying.

    `last_code` and `last_error` are one pair about one attempt — the most
    recent one — and they stay that way after we give up: dead-lettering
    records that we stopped, it does not rewrite what you answered. When the
    last attempt never got an answer at all (a refused connection, a timeout)
    there is no status code to show, so `last_code` is `null` and `last_error`
    names the transport failure.

    Refusals you can get here:

    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: any member of the tenant may
      do it. It is the acts that *change* a subscription — registering,
      updating, pausing, resuming, re-keying and replaying — that need an owner
      or an administrator.
    * `403 forbidden` — your role here does not let you read deliveries. A
      role with no read of this kind reads none of them: ask an administrator
      for the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `Delivery` is not tenant-scoped — it is dispatch machinery rather than the
    tenant's data — so `selectors.list_deliveries` scopes it by joining to the
    event, and that is the only way any door ever reaches one.
    """
    actor, tenant = _acting(request)
    deliveries: QuerySet[Delivery] = list_deliveries(tenant=tenant, actor=actor)
    deliveries = filters.filter(deliveries)
    return ordered_by(deliveries, ordering, allowed=DELIVERY_ORDERING, default="-created_at")


@router.get("/dead-letters/", response=list[DeliveryOut], url_name="dead_letters-list")
@paginate(CursorPagination)
def list_dead_letters_route(
    request: TenantRequest, ordering: str = "-dead_lettered_at"
) -> QuerySet[Delivery]:
    """List dead letters

    List the webhooks we gave up on — everything that needs your attention.

    Returns `{"items": [...], "has_more": ..., "next_cursor": ...}`, newest
    failure first, walked with `?cursor=` and `?limit=`; `count` arrives only
    with `?include_count=true`. `ordering` accepts the same values as
    `GET /deliveries/` and defaults to `-dead_lettered_at`.

    A delivery reaches this list after we have retried it for up to an hour
    across six attempts and it has still not been accepted. **Nothing is
    retrying it any more.** Once you have fixed whatever was wrong, send it
    again with `POST /dead-letters/{id}/replay/`.

    `last_code` and `last_error` tell you what your server said on the final
    attempt, and giving up does not rewrite them. If that attempt never reached
    you — a refused connection, a timeout — there is no status code to show:
    `last_code` is `null` and `last_error` names the transport failure instead.

    Refusals you can get here:

    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: any member of the tenant may
      do it. Sending a given-up delivery again — `POST
      /dead-letters/{id}/replay/` — is the act that needs an owner or an
      administrator.
    * `403 forbidden` — your role here does not let you read deliveries. A
      role with no read of this kind reads none of them: ask an administrator
      for the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    deliveries: QuerySet[Delivery] = dead_lettered(tenant=tenant, actor=actor)
    return ordered_by(deliveries, ordering, allowed=DELIVERY_ORDERING, default="-dead_lettered_at")


@router.post(
    "/dead-letters/{delivery_id}/replay/",
    response=DeliveryOut,
    url_name="dead_letter-replay",
)
def replay_dead_letter_route(request: TenantRequest, delivery_id: UUID) -> Delivery:
    """Replay a dead letter

    Send a given-up webhook again. Send no body.

    **This re-sends the event to every active endpoint subscribed to it, not
    just this one** — including endpoints that received it successfully the
    first time. They will see the same `X-Event-Id` again, so your receivers
    should ignore an event id they have already processed.

    The response is the delivery row as it stands the moment the replay is
    queued; the attempt itself happens shortly afterwards. Poll
    `GET /deliveries/` and watch `attempts` and `status` to see how it went.
    The row keeps its original `dead_lettered_at`, so the record that it once
    failed is not erased by a successful replay.

    Refusals you can get here:

    * `400 invalid` — this delivery was never given up on. One that is still
      `pending` or `failed` is still being retried automatically, and replaying
      it would just send a duplicate.
    * `404 not_found` — no such delivery, or it is not yours.
    * `403 forbidden` — you are not an owner or an administrator of the tenant.

    ---
    Narrowing a replay to one endpoint would be a second dispatch workflow, and
    the ADR rejected it: this is the same resume path `manage.py replay_events`
    walks (events-3's machinery), reached from a door instead of from a shell.
    """
    actor, tenant = _acting(request)
    delivery = get_delivery(tenant=tenant, delivery_id=delivery_id, actor=actor)
    return enqueue_replay(tenant=tenant, actor=actor, delivery=delivery)
