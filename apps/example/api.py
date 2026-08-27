"""The example API — every convention a route has to satisfy, visible.

Nothing here is implicit: the router restates `auth=`, the list paginates and
declares its page size on the class, every read goes through `selectors.py`
(which narrows to `request.tenant` **and** `request.org`, and selects the
foreign keys the schema reads), and every write goes through `services.py`.

`request.org` is the acting hat `TenantMiddleware` resolved from `X-Org`, and
every read passes it. A route that passed only the tenant would hand a
sub-seller the whole tenant — house rule 24 refuses that shape in the
selector.

The route never says 404 either. `selectors.get_widget` raises `NotFound` and
`config/api.py` is the only module that turns that into a number — so the MCP
tool over the same selector refuses identically without repeating the rule.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a
# `FilterSchema` parameter comes out as an unresolvable forward reference
# ("QueryParams is not fully defined"). Every other module in the tree has the
# future import; an `api.py` that declares schema-typed query parameters does
# not.

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by, searched
from apps.core.api.docs import Tag, refuses
from apps.core.authz import may_be_named
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.core.schemas import MeasuredBasisOut, MeasuredOut
from apps.example.models import Widget, WidgetEntry, WidgetPolicy
from apps.example.schemas import (
    WidgetEntryIn,
    WidgetEntryOut,
    WidgetFilter,
    WidgetIn,
    WidgetOut,
    WidgetPatch,
    WidgetPolicyIn,
    WidgetPolicyOut,
    WidgetStatsOut,
)
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget,
    list_widget_entries,
    list_widget_policies,
    list_widgets,
)
from apps.example.services import (
    approve_widget,
    create_widget,
    create_widget_policy,
    delete_widget,
    record_widget_entry,
    update_widget,
)

# The path says what the resource is, not which app holds it. `config.api` reads
# this; an app that says nothing is mounted under its label.
PREFIX = "widgets"

# What `?ordering=` may name, and nothing else. Straight into `.order_by()` it
# would let a client sort by any column and traverse any relation — a full-table
# sort on an unindexed column at best, a read across a join at worst.
ORDERING = ("created_at", "updated_at", "name")

# What `?q=` searches. Text columns on this row; never a related table's, or the
# search becomes a join nobody sized.
SEARCH_FIELDS = ("name", "notes")

# What this app's tag is FOR, declared in the app that owns the tag and
# collected into the OpenAPI document's `tags` section by `config/api.py`'s
# discovery (ADR api-1). A reader meets the group before the routes in it, and
# house rule 41 is what notices a tag nobody described.
TAGS = {
    "widgets": Tag(
        "Widgets",
        "The worked example: one org-scoped resource end to end. Widgets show the "
        "house shapes a product copies — a filtered, searched, ordered, paginated "
        "list; a create that names a policy it must be able to reach; a verb on a "
        "sub-path rather than a settable column; an append-only ledger; and a "
        "measured count that travels with the arithmetic that produced it.",
        plane="everyday",
        plane_note=(
            "the worked example resource, and the shape every product resource follows: list it, "
            "filter it, create one, follow an id."
        ),
    ),
}

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call these routes.
router = Router(tags=["widgets"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as.

    Authentication has already guaranteed the user. The tenant has not been
    guaranteed by anything: a signed-in user with no membership resolves to
    `None`, and a write with no tenant is refused rather than guessed at.

    The **hat** rides on the actor rather than being returned beside the
    tenant, because that is where a service reads it from: `create_widget`
    takes no `organization=` argument, so there is nothing for a route to pass
    and nothing for a caller to forge.

    **Whether the actor *may* do the thing is not decided here.** The route
    resolves who is asking; `services.py` calls `authz.require`. A permission
    check in this function would be a fourth copy of the rule, one per door.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


@router.get("/", response=list[WidgetOut], url_name="widget-list")
@paginate(CursorPagination)
def list_widgets_route(
    request: TenantRequest,
    filters: Query[WidgetFilter],
    q: str | None = None,
    ordering: str = "-created_at",
) -> QuerySet[Widget]:
    """List widgets

    List widgets, newest first.

    **Narrow** with `name` — a case-insensitive substring match, not an exact
    one, so `?name=bolt` finds "Left bolt".

    **Search** with `q`, which looks in the name and the notes of each widget
    and nothing else. There is no wildcard syntax; send the words.

    **Sort** with `ordering`. It accepts `created_at`, `updated_at` or `name`,
    each optionally prefixed with `-` for descending, and the default is
    `-created_at`. Any other value is refused with `400 invalid` rather than
    quietly ignored, so you never get a page sorted by something you did not
    ask for.

    **Pages** are `?cursor=` and `?limit=` (50 by default, 200 at most). The
    body is `{"items": [...], "has_more": ..., "next_cursor": ...}`: send the
    `next_cursor` you were given back as `?cursor=` for the following page, and
    stop when `has_more` is false. A cursor is opaque — never build or edit one
    — and it is tied to the `?ordering=` it was minted under.

    **`count` is `null` unless you send `?include_count=true`**, because a total
    costs a second pass over the matches and most callers never show one. Ask
    for it when you need it; it is the exact number of matches, not the number
    on this page.

    **What you can see** depends on the organization you are acting as — the
    `X-Org` header, or your default organization if you send none. You get that
    organization's widgets and those of every organization beneath it in the
    tree. Widgets belonging to an organization alongside yours, or above it, are
    not in the list and are not counted.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Every one of the four narrowings is declared — the filter by a
    `FilterSchema`, the search and the ordering by the constants above — so
    nothing here reads `request.GET`. This is the house list shape: scoped,
    filtered, searched, ordered, paginated, and it is the shape a product
    copies.
    """
    # Scoped first, and only ever narrowed after: the type widens from
    # `ScopedQuerySet` to `QuerySet` here because filtering returns the plain
    # one, and narrowing a queryset cannot widen its tenant.
    widgets: QuerySet[Widget] = list_widgets(tenant=request.tenant, org=request.org)
    widgets = filters.filter(widgets)
    widgets = searched(widgets, q, fields=SEARCH_FIELDS)
    return ordered_by(widgets, ordering, allowed=ORDERING, default="-created_at")


def resolve_named_policy(
    *, tenant: Tenant, actor: Actor, policy_id: UUID | None
) -> WidgetPolicy | None:
    """Turn an id a client sent into the policy row it names, or `None`.

    Resolution only — **the reachability question is asked by the caller**, on
    the line above the service call, and that is not a style choice. House rule
    26 reads `may_be_named` at the site where the foreign-key target is handed
    to a `@service`; a check hidden inside a helper is a check a reviewer has to
    go and find, and one somebody can quietly stop calling. So this function
    narrows, and the door states.

    The narrowing is `governing()` — the acting hat's *ancestor chain*, which is
    what makes a **sibling** branch's policy `not_found` rather than
    `forbidden`. Not-there and not-yours are one answer here for the same reason
    they are one answer everywhere else in this app: the second sentence would
    confirm the row exists, which is the fact the scoping was hiding.

    Shared with `mcp.py`, which imports it exactly as it imports `ORDERING` and
    `SEARCH_FIELDS` — one resolution, so the two doors cannot come to disagree
    about which policies a hat may name.
    """
    if policy_id is None:
        return None
    return get_governing_widget_policy(tenant=tenant, org=actor.org, policy_id=policy_id)


@router.post("/", response={201: WidgetOut}, url_name="widget-create")
def create_widget_route(request: TenantRequest, payload: WidgetIn) -> Status[Widget]:
    """Create a widget

    Create a widget.

    Send a `name` (required) and optionally `notes` and a `policy_id`.

    The new widget belongs to the organization you are acting as — the `X-Org`
    header, or your default organization if you send none. There is no field in
    the body that sets it, so you cannot create a widget somewhere you are not a
    member.

    A `policy_id`, if you send one, must name a widget policy that organization
    can reach: one set on your own organization or on one beneath it, or one an
    organization above you set and that therefore governs you. Any other id
    answers `404 not_found` and **nothing is created** — the same answer an id
    that does not exist at all gets, so a 404 here never tells you whether the
    policy is real.

    Answers `201` with the created widget.

    Refusals you can get here:

    * `400 invalid` — `name` is missing, empty or too long. `errors` names the
      fields and nothing is created.
    * `403 forbidden` — you may not create widgets here, or the request
      resolved no acting organization.
    * `404 not_found` — the `policy_id` names a policy you could not have
      reached. A policy in a branch you hold no membership over answers
      this, not `403`.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The `may_be_named` line is the reachability fence (house rule 26), stated at
    the door rather than buried in the resolver so a reviewer can see it. The
    refusal lands on the audit trail either way.
    """
    actor, tenant = _acting(request)
    policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=payload.policy_id)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    widget = create_widget(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        notes=payload.notes,
        policy=policy,
    )
    return Status(201, widget)


def widget_stats(*, tenant: Tenant | None, org: Any) -> WidgetStatsOut:
    """The measured widget count for one hat — **one implementation, both doors**.

    It lives here rather than in `selectors.py` because it does not return a
    queryset: it returns a *wire shape*, assembled out of the one selector both
    doors already read through. And it lives here rather than being written
    twice because `mcp.py` imports it — the same way it already imports
    `ORDERING` and `SEARCH_FIELDS` — which is what makes the machine door's
    answer equal to the human door's by construction rather than by two
    functions agreeing, which is the standing reminder of what happens when
    they do not.

    **The basis is honest, and that is the whole contract** (ADR core-7). The
    formula is `onboarded + pending`, both terms are on the wire, and the value
    is their sum — so a client can check the arithmetic without a second request
    and a screen, an export and an assistant cannot come to disagree about it.
    Two `COUNT`s rather than one plus a subtraction, because a subtraction would
    make one of the two inputs unmeasured and the basis would be decorative.
    """
    visible = list_widgets(tenant=tenant, org=org)
    onboarded = visible.filter(onboarded_at__isnull=False).count()
    pending = visible.filter(onboarded_at__isnull=True).count()
    return WidgetStatsOut(
        count=MeasuredOut(
            value=Decimal(onboarded + pending),
            basis=MeasuredBasisOut(
                formula="onboarded + pending",
                inputs={"onboarded": Decimal(onboarded), "pending": Decimal(pending)},
            ),
        )
    )


@router.get("/stats/", response=WidgetStatsOut, url_name="widget_stats-detail")
def widget_stats_route(request: TenantRequest) -> WidgetStatsOut:
    """Retrieve widget statistics

    How many widgets you can see, with the arithmetic attached.

    The same set the widget list covers: your acting organization's widgets and
    those of every organization beneath it.

    The count comes back as a **measured** number rather than a bare integer.
    You get `value` (the total), `basis.formula` (the string
    `"onboarded + pending"`) and `basis.inputs` (an object with `onboarded` and
    `pending` in it), so you can check the sum without asking a second question.

    Every number in it is a JSON **string**, not a JSON number — `"7"`, not `7`
    — so that no client's float handling can change the value on the way in.
    Parse them as decimals.

    Takes no parameters.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Declared before `/{widget_id}/` so the reading order matches the matching
    order, though it would not collide either way: the detail route's parameter
    is typed `UUID`, so ninja mounts it under Django's `uuid` converter and the
    literal `stats` can never satisfy it.

    Not `@paginate`d, and that is not an omission house rule 3 should catch: it
    answers with a single object rather than a collection. The query pin in
    `tests/test_api.py` is what keeps its two `COUNT`s from becoming three.
    """
    return widget_stats(tenant=request.tenant, org=request.org)


@router.get("/policies/", response=list[WidgetPolicyOut], url_name="widget_policies-list")
@paginate(CursorPagination)
def list_widget_policies_route(request: TenantRequest) -> QuerySet[WidgetPolicy]:
    """List widget policies

    List the widget policies your acting organization owns.

    That means policies set on your own organization and on organizations
    beneath it. **It does not include the policy that governs you** — a policy
    an organization above you set applies to you and is not yours to list, so
    this can come back empty while your widgets are still being governed. To
    find out what governs you, call `GET /api/v1/widgets/policies/governing/`.

    Takes no filter, search or ordering parameters. Paged like every other list:
    `?cursor=`, `?limit=`, body
    `{"items": [...], "has_more": ..., "next_cursor": ...}`; `count` only with
    `?include_count=true`.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The split is the point (ADR core-3): resolution goes up, visibility does
    not, and a list is a discovery surface. A sub-seller under a seller that set
    a policy lists nothing and is still governed.

    No filter, no search and no ordering allow-list here, unlike the widget
    list: a policy has a name and a branch and nothing worth narrowing on yet.
    The day it does, they arrive the same declared way they did there.
    """
    policies: QuerySet[WidgetPolicy] = list_widget_policies(tenant=request.tenant, org=request.org)
    return policies


@router.post("/policies/", response={201: WidgetPolicyOut}, url_name="widget_policy-create")
def create_widget_policy_route(
    request: TenantRequest, payload: WidgetPolicyIn
) -> Status[WidgetPolicy]:
    """Create a widget policy

    Create a widget policy on your acting organization.

    Send a `name` and a `body`. The policy is created on the organization you
    are acting as — the `X-Org` header, or your default organization if you send
    none — and there is no field that names a different one.

    It then governs that organization **and every organization beneath it**.
    Those organizations cannot list it (it is not theirs) and are governed by it
    all the same; they find out what governs them by calling
    `GET /api/v1/widgets/policies/governing/`.

    Answers `201` with the created policy.

    Refusals you can get here:

    * `400 invalid` — `name` is missing, empty or too long. `errors` names the
      fields.
    * `403 forbidden` — you may not set policy for this organization, or the
      request resolved no acting organization.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    policy = create_widget_policy(tenant=tenant, actor=actor, name=payload.name, body=payload.body)
    return Status(201, policy)


@router.get(
    "/policies/governing/",
    response=WidgetPolicyOut,
    url_name="governing_widget_policy-detail",
)
# A collection-shaped path that CAN refuse `not_found` — it addresses one row
# without naming it, so the derivation cannot see it (house rule 41's valve).
@refuses("forbidden", "not_found", "rate_limited")
def get_governing_widget_policy_route(request: TenantRequest) -> WidgetPolicy:
    """Retrieve the governing widget policy

    The widget policy currently governing your acting organization.

    Answers with one policy: the nearest one set on your own organization or, if
    none is, on the closest organization above you that has set one. This is the
    only route here that reads upward, and it can return a policy that
    `GET /api/v1/widgets/policies/` will not list for you — a policy set above
    you governs you without becoming yours to see.

    `404 not_found` when no organization on that chain has set one. That is the
    normal answer for an ungoverned organization, not an error to retry.

    Takes no parameters.

    Refusals you can get here:

    * `404 not_found` — no policy governs your acting organization: neither it
      nor anything above it has one.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The upward half of the pair. `InheritedDownward` on the model is what
    licenses it, and it is a declaration on the model rather than a flag on this
    route on purpose: upward *config resolution*, never upward *visibility*.
    The 404 is the selector's, the same one a missing widget gets.
    """
    return get_governing_widget_policy(tenant=request.tenant, org=request.org)


@router.get("/entries/", response=list[WidgetEntryOut], url_name="widget_entries-list")
@paginate(CursorPagination)
def list_widget_entries_route(
    request: TenantRequest, widget_id: UUID | None = None
) -> QuerySet[WidgetEntry]:
    """List ledger entries

    List ledger entries, newest first.

    Pass `?widget_id=<uuid>` for one widget's entries, or omit it for every
    entry your acting organization can see. Paged: `?cursor=`, `?limit=`, body
    `{"items": [...], "has_more": ..., "next_cursor": ...}`; `count` only with
    `?include_count=true`.

    Entries cannot be changed or removed once written. There is no `PATCH` and
    no `DELETE` for an entry anywhere in this API, and that is the contract, not
    a missing feature — do not build a client that expects to correct one. To
    record a correction, append another entry.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `WidgetEntry` declares `append_only`, so the door offers no way to rewrite
    one; `introspect` is where that is checkable — the route list for this app
    has no update or delete for entries at all.
    """
    entries: QuerySet[WidgetEntry] = list_widget_entries(
        tenant=request.tenant, org=request.org, widget_id=widget_id
    )
    return entries


@router.post("/entries/", response={201: WidgetEntryOut}, url_name="widget_entry-record")
def record_widget_entry_route(
    request: TenantRequest, payload: WidgetEntryIn
) -> Status[WidgetEntry]:
    """Record a ledger entry

    Append one entry to a widget's ledger.

    Send `widget_id` and `kind`, and optionally `note`.

    A `widget_id` your acting organization cannot see — one belonging to an
    organization alongside yours, above yours, or in another tenant — answers
    `404 not_found` and **nothing is written**.

    `organization_slug` is optional and cannot move the entry anywhere: it is
    always recorded against the widget's **own** organization. If you send the
    slug, it must be that organization's; any other value — including one that
    names a real organization elsewhere in your tenant — is refused with
    `400 invalid` naming the `organization` field, rather than being silently
    corrected. Omit it unless you want that check.

    The entry cannot afterwards be changed or removed; there is no route that
    does either. Answers `201` with the entry.

    Refusals you can get here:

    * `400 invalid` — a field is malformed, or `organization_slug` names a
      branch that is not the widget's own. An entry takes its branch from
      its widget and nothing you send can move it.
    * `403 forbidden` — you may not add entries here, or the request resolved
      no acting organization.
    * `404 not_found` — the `widget_id` names a widget you could not have
      reached.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `may_be_named` is asked out loud on the line that passes the row to the
    service, because the row is a foreign-key target this request named (house
    rule 26). Here it can only ever agree, since `get_widget` already narrowed
    to the hat's subtree; it is written anyway, because the check that is only
    there when somebody remembered it is the check that is missing the day it
    matters.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=payload.widget_id, org=actor.org)
    if not may_be_named(actor, widget):
        raise NotFound()
    entry = record_widget_entry(
        tenant=tenant,
        actor=actor,
        widget=widget,
        kind=payload.kind,
        note=payload.note,
        organization_slug=payload.organization_slug,
    )
    return Status(201, entry)


@router.get("/{widget_id}/", response=WidgetOut, url_name="widget-detail")
def retrieve_widget(request: TenantRequest, widget_id: UUID) -> Widget:
    """Retrieve a widget

    Fetch one widget by id.

    You get it if your acting organization covers it — its own widgets and those
    of organizations beneath it.

    Anything else answers `404 not_found`: a widget in an organization alongside
    yours, one above yours, one in another tenant, and an id that names nothing
    all give the identical answer. **A 404 here is not evidence that the widget
    does not exist**, so do not build a client that reads it that way.

    Refusals you can get here:

    * `404 not_found` — nothing has that id in the part of the tenant your
      `X-Org` hat covers. A widget in a sibling branch answers this too.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_widget(tenant=request.tenant, widget_id=widget_id, org=request.org)


@router.patch("/{widget_id}/", response=WidgetOut, url_name="widget-update")
def update_widget_route(request: TenantRequest, widget_id: UUID, payload: WidgetPatch) -> Widget:
    """Update a widget

    Change a widget's name, notes or governing policy.

    Send only the fields you want to change. A field you omit is left alone, and
    so is a field you send as `null` — `null` means "leave it alone" here, not
    "clear it", so **there is no way through this route to remove a widget's
    policy**; set a different one instead.

    A `policy_id` your acting organization cannot reach answers `404 not_found`
    and nothing at all is written — not even the `name` you sent in the same
    body. That is the same answer an id naming no policy gets.

    Answers `200` with the widget as it now stands.

    Refusals you can get here:

    * `400 invalid` — a field you sent is malformed. `errors` names it and
      nothing is changed.
    * `403 forbidden` — the widget is not yours and you are not an
      administrator of this organization.
    * `404 not_found` — nothing has that id where you can see, or the
      `policy_id` names a policy you could not have reached.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org)
    policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=payload.policy_id)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    return update_widget(
        tenant=tenant,
        actor=actor,
        widget=widget,
        name=payload.name,
        notes=payload.notes,
        policy=policy,
    )


@router.post("/{widget_id}/approve/", response=WidgetOut, url_name="widget-approve")
def approve_widget_route(request: TenantRequest, widget_id: UUID) -> Widget:
    """Approve a widget

    Approve a widget that is waiting to be onboarded.

    Takes no body. Answers `200` with the widget, and an entry is appended to
    its ledger.

    There is no field anywhere that you can `PATCH` to do this, and no way to
    un-approve: approval is this route and nothing else.

    **Safe to retry.** Calling it again while the widget is still being
    onboarded answers `200` again and changes nothing further, so a client that
    never saw the first answer can simply send it a second time.

    Refusals you can get here:

    * `409 conflict` — the onboarding this would have approved has already
      ended. Retrying will not change that; read the widget instead.
    * `404 not_found` — there is no onboarding under way for this widget, or
      your acting organization cannot see it, or the id names nothing.

    A `200` means the approval was recorded. It does not mean onboarding has
    finished — read the widget's `onboarded_at`, which is set when it has.

    ---
    A POST on a sub-path rather than a PATCH that sets a field, because approval
    is a **verb and not a column**: there is nothing on the row a client could
    set to mean it, and a schema with an `approved` field would invite a client
    to set it back. 200 rather than 202 for the same reason: the row it answers
    with is the row as it stands.

    The refusals are the service's, and `config/api.py` turns those into 404 and
    409 without this route naming a number.

    The `may_be_named` line arrived when approval started **writing** — it now
    appends its own line to the widget's ledger — which put it inside house rule
    26's scope: a keyword argument that is a foreign-key target, handed to a
    service that writes an org-scoped row, is checked where a reviewer can see
    the check. `get_widget` has already narrowed to the hat's subtree, so here
    it can only agree; it is written anyway, because a fence that appears only
    when somebody remembered it is missing on the day it matters.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org)
    if not may_be_named(actor, widget):
        raise NotFound()
    return approve_widget(tenant=tenant, actor=actor, widget=widget)


@router.delete("/{widget_id}/", response={204: None}, url_name="widget-delete")
def delete_widget_route(request: TenantRequest, widget_id: UUID) -> Status[None]:
    """Delete a widget

    Delete a widget.

    Answers `204` with an empty body over HTTP. Over MCP the same call answers
    with the widget that was removed, because a tool result has no equivalent of
    an empty response — the two are the same act, told in each protocol's own
    grammar.

    A widget your acting organization cannot see answers `404 not_found`, the
    same as an id that names nothing, and nothing is removed.

    Refusals you can get here:

    * `403 forbidden` — the widget is not yours and you are not an
      administrator of this organization.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    A delete is a write, so the reachability fence applies: `may_be_named` is
    asked out loud on the line that hands the row to the service (house rule
    26), even though `get_widget` has already narrowed to the acting
    organization's subtree and it can only agree.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org)
    if not may_be_named(actor, widget):
        raise NotFound()
    delete_widget(tenant=tenant, actor=actor, widget=widget)
    return Status(204, None)
