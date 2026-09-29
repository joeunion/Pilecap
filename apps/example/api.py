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

# golden: archive version move bulk history duplicate attach merge import begin
from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import ordered_by, searched
from apps.core.api.docs import Tag, also_refuses
from apps.core.api.pagination import ActsPagination
from apps.core.authz import may_be_named
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.core.verbs import with_allowed_acts
from apps.example.models import Widget
from apps.example.schemas import WidgetDetailOut, WidgetFilter, WidgetOut
from apps.example.selectors import Show, get_widget, list_widgets
from apps.example.services import archive_widget, restore_widget

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from typing import Any

from apps.core.api import CursorPagination
from apps.core.audit import AuditEntry
from apps.core.schemas import HistoryEntryOut
from apps.core.selectors import list_history
from apps.example.schemas import WidgetPatch
from apps.example.services import update_widget

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.core.models import Organization
from apps.core.schemas import VersionedMoveIn
from apps.core.selectors import get_organization
from apps.example.services import move_widget

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: bulk history duplicate attach merge import begin
from collections.abc import Callable
from typing import cast

from apps.core.bulk import run_bulk
from apps.core.exceptions import Invalid
from apps.core.schemas import BulkRefusalOut
from apps.core.verbs import ROADS, resolve_subject
from apps.example.schemas import WidgetBulkIn, WidgetBulkOut, WidgetBulkResultOut

# golden: bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
from ninja import Status

from apps.core.idempotency import HEADER as IDEMPOTENCY_KEY_HEADER
from apps.example.services import duplicate_widget

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.example.schemas import RepointOut, WidgetMergeIn, WidgetMergePreviewOut
from apps.example.selectors import get_widget_merge_preview
from apps.example.services import merge_widget

# golden: merge import end
# isort: split
# golden: attach merge import begin
from apps.example.selectors import list_widget_tags

# golden: attach merge import end
# isort: split
# golden: import begin
from apps.example.schemas import WidgetIn
from apps.example.services import create_widget

# golden: import end
# isort: split
from decimal import Decimal

from apps.core.api.docs import refuses
from apps.core.schemas import MeasuredBasisOut, MeasuredOut
from apps.example.models import WidgetEntry, WidgetPolicy
from apps.example.schemas import (
    WidgetEntryIn,
    WidgetEntryOut,
    WidgetPolicyIn,
    WidgetPolicyOut,
    WidgetStatsOut,
)
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget_policy,
    list_widget_entries,
    list_widget_policies,
)
from apps.example.services import (
    approve_widget,
    archive_widget_policy,
    create_widget_policy,
    delete_widget,
    record_widget_entry,
    restore_widget_policy,
)

# golden: archive version move bulk history duplicate attach merge import begin
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
@paginate(ActsPagination)
def list_widgets_route(
    request: TenantRequest,
    filters: Query[WidgetFilter],
    q: str | None = None,
    ordering: str = "-created_at",
    show: Show = "live",
) -> QuerySet[Widget]:
    """List widgets

    List widgets, newest first.

    **Which cut of the book** with `show`: `live` (the default) lists the
    widgets in use; `archived` lists only the archived ones; `all` lists both.
    Any other value is refused with `400 invalid` naming `show`. An archived
    widget carries `archived_at` and `archived_by`; a live one carries `null`
    in both.

    **What you may press** is on the wire, never for you to work out: every
    widget carries `allowed_acts` — the acts you may take on that widget as it
    stands — and the page carries its own `allowed_acts`, which holds `create`
    when you may create a widget where you are acting.

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

    * `400 invalid` — `?ordering=` or `?show=` named a value this list does
      not accept, or a filter value was malformed. The response names the
      parameter and what it accepts.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `403 forbidden` — your role here does not let you read widgets. A role
      with no read of this kind reads none of them: ask an administrator for
      the permission, or act under an organization where you hold it.
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
    actor, tenant = _acting(request)
    widgets: QuerySet[Widget] = list_widgets(tenant=tenant, org=request.org, actor=actor, show=show)
    widgets = filters.filter(widgets)
    widgets = searched(widgets, q, fields=SEARCH_FIELDS)
    return ordered_by(widgets, ordering, allowed=ORDERING, default="-created_at")


# golden: archive version move bulk history duplicate attach merge import end
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
    return get_governing_widget_policy(
        tenant=tenant, org=actor.org, policy_id=policy_id, actor=actor
    )


# golden: import begin
@router.post("/", response={201: WidgetOut}, url_name="widget-create")
def create_widget_route(request: TenantRequest, payload: WidgetIn) -> Status[Widget]:
    """Create a widget

    Create a widget.

    Send a `name` (required) and optionally `notes`, an `external_ref` — the id
    the widget has in the system it came from, unique within your organization
    — and a `policy_id`.

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

    * `400 invalid` — `name` is missing, empty or too long, you already own a
      widget with this name, or another widget in your organization already
      carries this `external_ref`. `errors` names it and nothing is created.
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
    # golden: import end
    policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=payload.policy_id)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: import begin
    widget = create_widget(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        notes=payload.notes,
        external_ref=payload.external_ref,
        # golden: import end
        policy=policy,
        # golden: import begin
    )
    return Status(201, with_allowed_acts([widget], actor)[0])


# golden: import end


def widget_stats(*, tenant: Tenant | None, org: Any, actor: Actor) -> WidgetStatsOut:
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
    # authz: the read IS asked, one hop further down than rule 41's one-step walk
    # reaches. This function is a wire shape assembled out of `list_widgets`, and
    # `list_widgets` calls `require(actor, "widget.read")` — the check lives in
    # the selector, once, and every door pays it (ADR core-27, §C6). Asking here
    # as well would be the second copy of the rule that seam exists to delete,
    # and it would ask the same question at the same node. The refusal the stats
    # route's contract promises is driven by
    # `tests/test_reads_ask.py::test_widget_stats_asks_widget_read`.
    visible = list_widgets(tenant=tenant, org=org, actor=actor)
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
    * `403 forbidden` — your role here does not let you read widgets. A role
      with no read of this kind reads none of them: ask an administrator for
      the permission, or act under an organization where you hold it.
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
    actor, tenant = _acting(request)
    return widget_stats(tenant=tenant, org=request.org, actor=actor)


@router.get("/policies/", response=list[WidgetPolicyOut], url_name="widget_policies-list")
@paginate(CursorPagination)
def list_widget_policies_route(
    request: TenantRequest, show: Show = "live"
) -> QuerySet[WidgetPolicy]:
    """List widget policies

    List the widget policies your acting organization owns.

    `show` picks the cut of the book: `live` (the default), `archived` for the
    archived policies alone, or `all`. An archived policy governs nobody.

    That means policies set on your own organization and on organizations
    beneath it. **It does not include the policy that governs you** — a policy
    an organization above you set applies to you and is not yours to list, so
    this can come back empty while your widgets are still being governed. To
    find out what governs you, call `GET /api/v1/widgets/policies/governing/`.

    Takes no filter, search or ordering parameters beyond `show`. Paged like every other list:
    `?cursor=`, `?limit=`, body
    `{"items": [...], "has_more": ..., "next_cursor": ...}`; `count` only with
    `?include_count=true`.

    Refusals you can get here:

    * `400 invalid` — `?show=` named a cut this list does not have. The
      response names it and what it accepts.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `403 forbidden` — your role here does not let you read widget policies. A role
      with no read of this kind reads none of them: ask an administrator for
      the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The split is the point (ADR core-3): resolution goes up, visibility does
    not, and a list is a discovery surface. A sub-seller under a seller that set
    a policy lists nothing and is still governed.

    No filter, no search and no ordering allow-list here, unlike the widget
    list: a policy has a name and a branch and nothing worth narrowing on yet.
    The day it does, they arrive the same declared way they did there.
    """
    actor, tenant = _acting(request)
    policies: QuerySet[WidgetPolicy] = list_widget_policies(
        tenant=tenant, org=request.org, actor=actor, show=show
    )
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
    * `403 forbidden` — your role here does not let you read widget policies. A role
      with no read of this kind reads none of them: ask an administrator for
      the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    The upward half of the pair. `InheritedDownward` on the model is what
    licenses it, and it is a declaration on the model rather than a flag on this
    route on purpose: upward *config resolution*, never upward *visibility*.
    The 404 is the selector's, the same one a missing widget gets.
    """
    actor, tenant = _acting(request)
    return get_governing_widget_policy(tenant=tenant, org=request.org, actor=actor)


@router.post(
    "/policies/{policy_id}/archive/",
    response=WidgetPolicyOut,
    url_name="widget_policy-archive",
)
@also_refuses("archive_blocked")
def archive_widget_policy_route(request: TenantRequest, policy_id: UUID) -> WidgetPolicy:
    """Archive a widget policy

    Take one widget policy out of the book. Takes no body.

    An archived policy governs nobody: `GET /api/v1/widgets/policies/governing/`
    stops answering with it, and new widgets cannot name it. It stays readable
    in `GET /api/v1/widgets/policies/?show=archived`. Pressing it again answers
    the policy unchanged.

    A policy that a widget still in use names cannot be archived — archiving
    it would leave that widget governed by nothing. The refusal names the
    widgets' list, narrowed to this policy, as the place to clear the way.

    Refusals you can get here:

    * `409 archive_blocked` — a widget in use still names this policy.
      `blocking` names the kind and the door; archive those widgets or give
      them another policy, then archive again. Nothing was written.
    * `403 forbidden` — you do not administer the organization that set this
      policy.
    * `404 not_found` — nothing has that id among the policies your acting
      organization owns.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    policy = get_widget_policy(tenant=tenant, policy_id=policy_id, org=request.org, actor=actor)
    if not may_be_named(actor, policy):
        raise NotFound()
    return archive_widget_policy(tenant=tenant, actor=actor, policy=policy)


@router.post(
    "/policies/{policy_id}/restore/",
    response=WidgetPolicyOut,
    url_name="widget_policy-restore",
)
@also_refuses("restore_blocked")
def restore_widget_policy_route(request: TenantRequest, policy_id: UUID) -> WidgetPolicy:
    """Restore a widget policy

    Put one archived widget policy back in the book, where it governs again.
    Takes no body. Pressing it again answers the policy unchanged.

    Refusals you can get here:

    * `403 forbidden` — you do not administer the organization that set this
      policy.
    * `404 not_found` — nothing has that id among the policies your acting
      organization owns.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    policy = get_widget_policy(tenant=tenant, policy_id=policy_id, org=request.org, actor=actor)
    if not may_be_named(actor, policy):
        raise NotFound()
    return restore_widget_policy(tenant=tenant, actor=actor, policy=policy)


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

    * `400 invalid` — `?widget_id=` is not a valid id. The response names it.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `403 forbidden` — your role here does not let you read ledger entries. A role
      with no read of this kind reads none of them: ask an administrator for
      the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    `WidgetEntry` declares `append_only`, so the door offers no way to rewrite
    one; `introspect` is where that is checkable — the route list for this app
    has no update or delete for entries at all.
    """
    actor, tenant = _acting(request)
    entries: QuerySet[WidgetEntry] = list_widget_entries(
        tenant=tenant, org=request.org, widget_id=widget_id, actor=actor
    )
    return entries


@router.post("/entries/", response={201: WidgetEntryOut}, url_name="widget_entry-record")
@also_refuses("archived", "merged")
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
    * `409 archived` — the widget is archived: it reads, and nothing about it
      changes until it is restored (`POST /api/v1/widgets/{id}/restore/`).
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
    widget = get_widget(tenant=tenant, widget_id=payload.widget_id, org=actor.org, actor=actor)
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


# golden: bulk history duplicate attach merge import begin
def bulk_widgets(
    *,
    tenant: Tenant,
    actor: Actor,
    verb: str,
    ids: list[UUID],
    organization_id: UUID | None = None,
    owner_id: UUID | None = None,
) -> WidgetBulkOut:
    """One verb over a selection — **one implementation, both doors**.

    Each id runs the widget's OWN single service (`archive_widget`,
    `restore_widget`, `move_widget`), so every item is authorized, audited and
    refused exactly as a single press would be, and `core.bulk.run_bulk` says
    what happened to each: `done`, `unchanged` (already where the verb would
    put it — so a retried batch does only what is left) or `refused` with the
    body a single call would have answered. An id this hat could not have
    reached is `not_found` for that item and the rest still run.

    Called by the door OUTSIDE any service of its own, so no item's refusal
    reaches another item.
    """
    if verb != "move" and (organization_id is not None or owner_id is not None):
        raise Invalid({"organization_id": ["Only a move names where the widgets go."]})

    def resolve(pk: UUID) -> Widget:
        return cast(Widget, resolve_subject(actor, "widget", pk))

    act: Callable[[Widget], Widget]
    settled: Callable[..., bool]
    if verb == "move":
        # The destination is read once, at the hat: a node outside the hat's
        # subtree refuses the whole batch `not_found` before any item runs.
        to = (
            None
            if organization_id is None
            else get_organization(
                tenant=tenant, org=actor.org, organization_id=organization_id, actor=actor
            )
        )

        def move_one(row: Widget) -> Widget:
            return move_widget(
                tenant=tenant,
                actor=actor,
                widget=row,
                organization=to or row.organization,
                owner_id=owner_id,
            )

        def already_there(row: Widget) -> bool:
            return (to is None or row.organization_id == to.pk) and (
                owner_id is None or row.owner_id == owner_id
            )

        act, settled = move_one, already_there
    elif verb == "archive":

        def archive_one(row: Widget) -> Widget:
            return archive_widget(tenant=tenant, actor=actor, widget=row)

        act, settled = archive_one, ROADS["archive"].settled["archive"]
    else:

        def restore_one(row: Widget) -> Widget:
            return restore_widget(tenant=tenant, actor=actor, widget=row)

        act, settled = restore_one, ROADS["archive"].settled["restore"]

    report = run_bulk(
        tenant=tenant, actor=actor, verb=verb, ids=ids, resolve=resolve, act=act, is_settled=settled
    )
    return WidgetBulkOut(
        verb=report.verb,
        results=[
            WidgetBulkResultOut(
                id=result.id,
                outcome=result.outcome,
                item=(
                    None
                    if result.item is None
                    else WidgetOut.from_orm(with_allowed_acts([result.item], actor)[0])
                ),
                refusal=(
                    None
                    if result.refusal is None
                    else BulkRefusalOut.model_validate(result.refusal)
                ),
            )
            for result in report.results
        ],
        done=report.done,
        unchanged=report.unchanged,
        refused=report.refused,
    )


@router.post("/bulk/", response=WidgetBulkOut, url_name="widget-bulk")
def bulk_widgets_route(request: TenantRequest, payload: WidgetBulkIn) -> WidgetBulkOut:
    """Archive, restore or move many widgets

    Run one verb — `archive`, `restore` or `move` — over up to 200 widgets,
    and hear what happened to each.

    Send `verb` and `ids`; a `move` also sends `organization_id` (and,
    optionally, `owner_id`), exactly as a single move does. Answers `200` once
    the batch is understood, with one result per id **in the order you sent
    them**: `done`, `unchanged` (it was already where the verb would put it) or
    `refused`, carrying the very refusal a single press on that widget would
    have answered. `done`, `unchanged` and `refused` count them.

    **Safe to retry.** A batch sent again does only what is left — the rest
    answer `unchanged` — and with the same `Idempotency-Key` you get the first
    answer back, byte for byte.

    A widget you cannot see — one in an organization alongside yours — is
    `refused` with `not_found`, and the others still run.

    Refusals you can get here:

    * `400 invalid` — no ids, more than 200, an id twice, or a destination on
      a verb that is not a move. `errors` names it and nothing ran.
    * `422 invalid_body` — `verb` is not one of the three, or a field is not
      one this verb takes.
    * `404 not_found` — a move's `organization_id` names an organization you
      could not have reached; nothing ran.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    return bulk_widgets(
        tenant=tenant,
        actor=actor,
        verb=payload.verb,
        ids=payload.ids,
        organization_id=getattr(payload, "organization_id", None),
        owner_id=getattr(payload, "owner_id", None),
    )


# golden: archive version move begin
@router.get("/{widget_id}/", response=WidgetDetailOut, url_name="widget-detail")
def retrieve_widget(request: TenantRequest, widget_id: UUID) -> Widget:
    """Retrieve a widget

    Fetch one widget by id, with the `tags` on it.

    You get it if your acting organization covers it — its own widgets and those
    of organizations beneath it.

    **An archived widget answers too, read-only**: `archived_at` and
    `archived_by` say when and by whom, `allowed_acts` offers only `restore`,
    and every change to it is refused with `409 archived` until it is restored.

    Anything else answers `404 not_found`: a widget in an organization alongside
    yours, one above yours, one in another tenant, and an id that names nothing
    all give the identical answer. **A 404 here is not evidence that the widget
    does not exist**, so do not build a client that reads it that way.

    Refusals you can get here:

    * `404 not_found` — nothing has that id in the part of the tenant your
      `X-Org` hat covers. A widget in a sibling branch answers this too.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `403 forbidden` — your role here does not let you read widgets. A role
      with no read of this kind reads none of them: ask an administrator for
      the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=request.org, actor=actor)
    # golden: archive version move bulk history duplicate end
    widget.tags = list_widget_tags(tenant=tenant, actor=actor, widget=widget)  # type: ignore[attr-defined]
    # golden: archive version move bulk history duplicate begin
    return with_allowed_acts([widget], actor)[0]


@router.post("/{widget_id}/archive/", response=WidgetOut, url_name="widget-archive")
@also_refuses("archive_blocked")
def archive_widget_route(request: TenantRequest, widget_id: UUID) -> Widget:
    """Archive a widget

    Take one widget out of the book. Takes no body.

    An archived widget leaves the widget list and every count, and stays
    readable: `GET` it by id, or list `?show=archived`. It answers read-only —
    every change is refused with `409 archived` until it is restored.

    **Safe to retry.** Pressing it again answers the widget unchanged — the
    same `archived_at`, the same `archived_by` — and tells nobody a second
    time.

    Refusals you can get here:

    * `409 archive_blocked` — something still in use depends on this widget.
      `blocking` names each kind and the door that clears it. Nothing was
      written.
    * `403 forbidden` — you do not administer the organization this widget
      belongs to. Archiving is an administrator's press.
    * `404 not_found` — nothing has that id where you can see. A widget in a
      sibling branch answers this too.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=request.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    return with_allowed_acts([archive_widget(tenant=tenant, actor=actor, widget=widget)], actor)[0]


@router.post("/{widget_id}/restore/", response=WidgetOut, url_name="widget-restore")
@also_refuses("restore_blocked")
# golden: archive version move bulk history duplicate attach end
@also_refuses("merged")
# golden: archive version move bulk history duplicate attach begin
def restore_widget_route(request: TenantRequest, widget_id: UUID) -> Widget:
    """Restore a widget

    Put one archived widget back in the book. Takes no body.

    It returns to the widget list with `archived_at` and `archived_by` both
    `null`, and can be changed again. **Safe to retry**: pressing it on a
    widget that is not archived answers the widget unchanged.

    Refusals you can get here:

    * `409 restore_blocked` — something this widget depends on is not there
      for it any more. `blocking` names it and the door that puts it right.
    * `403 forbidden` — you do not administer the organization this widget
      belongs to.
    * `404 not_found` — nothing has that id where you can see.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=request.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    return with_allowed_acts([restore_widget(tenant=tenant, actor=actor, widget=widget)], actor)[0]


# golden: archive end
@router.patch("/{widget_id}/", response=WidgetOut, url_name="widget-update")
@also_refuses("archived", "stale_version")
# golden: version move bulk history duplicate attach end
@also_refuses("merged")
# golden: version move bulk history duplicate attach begin
def update_widget_route(request: TenantRequest, widget_id: UUID, payload: WidgetPatch) -> Widget:
    """Update a widget

    Change a widget's name, notes or governing policy.

    **Send the `version` you read** — every widget carries one — and only the
    fields you want to change. A field you omit is left alone, and so is a field
    you send as `null` — `null` means "leave it alone" here, not "clear it", so
    **there is no way through this route to remove a widget's policy**; set a
    different one instead.

    If somebody else saved the widget after you read it, your `version` is no
    longer its version: the save is refused with `409 stale_version`, nothing is
    changed, and the refusal carries `current_version`. Read the widget again,
    show what changed, and send your edit with the new version.

    A `policy_id` your acting organization cannot reach answers `404 not_found`
    and nothing at all is written — not even the `name` you sent in the same
    body. That is the same answer an id naming no policy gets.

    Answers `200` with the widget as it now stands, and its new `version`.

    Refusals you can get here:

    * `422 invalid_body` — `version` is missing, or a field is not one this
      route takes. `errors` names it and nothing is changed.
    * `400 invalid` — a field you sent is malformed. `errors` names it and
      nothing is changed.
    * `403 forbidden` — the widget is not yours and you are not an
      administrator of this organization.
    * `404 not_found` — nothing has that id where you can see, or the
      `policy_id` names a policy you could not have reached.
    * `409 stale_version` — somebody saved the widget after you read it.
      `current_version` is its version now; nothing was written.
    * `409 archived` — the widget is archived: it reads, and nothing about it
      changes until it is restored (`POST /api/v1/widgets/{id}/restore/`).
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    # Only what was SENT reaches the service, so the history's `changed_fields`
    # names what this edit changed and nothing it left alone.
    changes: dict[str, Any] = {
        field: value
        for field, value in payload.model_dump(include={"name", "notes"}).items()
        if value is not None
    }
    # golden: version move bulk history duplicate attach merge import end
    policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=payload.policy_id)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    if policy is not None:
        changes["policy"] = policy
    # golden: version move bulk history duplicate attach merge import begin
    updated = update_widget(
        tenant=tenant, actor=actor, widget=widget, version=payload.version, **changes
    )
    return with_allowed_acts([updated], actor)[0]


# golden: version end
@router.post("/{widget_id}/move/", response=WidgetOut, url_name="widget-move")
@also_refuses("archived", "move_blocked", "stale_version")
# golden: move bulk history duplicate attach end
@also_refuses("merged")
# golden: move bulk history duplicate attach begin
def move_widget_route(request: TenantRequest, widget_id: UUID, payload: VersionedMoveIn) -> Widget:
    """Move a widget

    Re-home one widget at another organization, and hand it to another owner
    if you name one.

    Send the `version` you read, the `organization_id` it is going to and,
    optionally, an `owner_id`. Leaving `organization_id` out keeps it where it
    is, which is how you hand it to another owner without moving it. The
    organizations you may move it to are
    `GET /api/v1/organizations/?can=widget.move` — your own and those beneath
    it where you administer widgets.

    **Safe to retry**: moving it to where it already is, owned by who already
    owns it, answers the widget unchanged and tells nobody.

    A widget with a line in its ledger cannot move: its entries are recorded
    where they were written and never follow it, so the move is refused
    `409 move_blocked` naming them, and nothing moves.

    Answers `200` with the widget where it now is: `organization_name` names
    the new organization, `owner_name` the owner, and `version` is new.

    Refusals you can get here:

    * `409 move_blocked` — something recorded under this widget must stay
      where it is. `blocking` names it; nothing moved.
    * `409 stale_version` — somebody saved the widget after you read it.
      `current_version` is its version now; nothing was written.
    * `409 archived` — the widget is archived: restore it before moving it.
    * `403 forbidden` — you do not administer widgets where it lives, or where
      it is going. Moving is an administrator's press at both ends.
    * `404 not_found` — the widget, the organization or the new owner is not
      one you could have reached: a sibling branch's organization answers
      this, and so does an owner with no membership where it is going.
    * `422 invalid_body` — `version` is missing, or a field is not one this
      route takes. `errors` names it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    destination = move_destination(
        tenant=tenant, actor=actor, widget=widget, to=payload.organization_id
    )
    moved = move_widget(
        tenant=tenant,
        actor=actor,
        widget=widget,
        organization=destination,
        owner_id=payload.owner_id,
        version=payload.version,
    )
    return with_allowed_acts([moved], actor)[0]


def move_destination(
    *, tenant: Tenant, actor: Actor, widget: Widget, to: UUID | None
) -> Organization:
    """Where a move is going: the named node inside the hat's subtree, or where it is.

    Shared by both doors and by the bulk move. A node is its own reach, so a
    sibling branch's id is `not_found` from the read — never `forbidden`, which
    would tell the caller the node exists.
    """
    if to is None:
        return widget.organization
    return get_organization(tenant=tenant, org=actor.org, organization_id=to, actor=actor)


# golden: version begin
@router.get("/{widget_id}/history/", response=list[HistoryEntryOut], url_name="widget_history-list")
@paginate(CursorPagination)
def list_widget_history_route(request: TenantRequest, widget_id: UUID) -> QuerySet[AuditEntry]:
    """List a widget's history

    What happened to one widget, newest first: each thing somebody did to it,
    who did it, through which door, and which fields they sent.

    Every entry carries `at`, `verb` (`create`, `update`, `move`, `archive`,
    `restore`, …), `actor` (an `id` and a `name` when a person acted, and a
    `kind`), `door` (`rest`, `mcp`, `workflow`, …) and `changed_fields` — the
    fields the call was SENT, never their values: the history keeps no before
    and after. A refused attempt is not history and is not listed.

    Paged like every other list: `?cursor=`, `?limit=`, body
    `{"items": [...], "has_more": ..., "next_cursor": ...}`; `count` only with
    `?include_count=true`.

    Refusals you can get here:

    * `404 not_found` — nothing has that id where you can see. A widget in a
      sibling branch answers this too.
    * `403 forbidden` — your role here does not let you read widgets.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    return list_history(tenant=tenant, actor=actor, row=widget)


# golden: version move bulk history end
@router.post("/{widget_id}/duplicate/", response={201: WidgetOut}, url_name="widget-duplicate")
@also_refuses("archived", "merged")
def duplicate_widget_route(request: TenantRequest, widget_id: UUID) -> Status[Widget]:
    """Duplicate a widget

    Make a new widget from this one. Takes no body.

    The copy carries the notes and the policy of the widget it was made from,
    and its tags; it is yours, it belongs to the organization you are acting
    as, and it is called `Copy of <name>`. It starts with an empty ledger and
    is onboarded like any new widget. `duplicated_from_id` names the widget it
    was copied from. Answers `201` with the copy.

    **Safe to retry with a key**: send an `Idempotency-Key` and a repeat of the
    same press answers the first copy rather than making a second.

    Refusals you can get here:

    * `400 invalid` — you already have a widget called `Copy of <name>`:
      rename it, then copy again. `errors` names `name`; nothing is created.
    * `403 forbidden` — you may not create widgets where you are acting.
    * `404 not_found` — nothing has that id where you can see.
    * `409 archived` — the widget is archived: restore it before copying it.
    * `409 merged` — the widget was merged into another; copy that one.
      `merged_into` names it.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    copy = duplicate_widget(
        tenant=tenant,
        actor=actor,
        widget=widget,
        idempotency_key=request.headers.get(IDEMPOTENCY_KEY_HEADER, ""),
    )
    return Status(201, with_allowed_acts([copy], actor)[0])


# golden: duplicate attach end
@router.get("/{widget_id}/merge/", response=WidgetMergePreviewOut, url_name="widget_merge-detail")
def preview_widget_merge_route(
    request: TenantRequest, widget_id: UUID, into: UUID
) -> WidgetMergePreviewOut:
    """Preview a widget merge

    What merging this widget into the widget `?into=` names WOULD move — read
    before you confirm, and nothing is written.

    `repoints` lists, per kind of thing attached to a widget, its `title`
    (*Notes*, *Tags*, *Files*) and `left` — how many would leave this widget
    for the other one. The widget's ledger is not listed: its entries stay
    where they were written, and the surviving widget's ledger reads them.

    Refusals you can get here:

    * `400 invalid` — `into` names this same widget.
    * `403 forbidden` — you do not administer both widgets' organizations.
    * `404 not_found` — either widget is not one you could have reached.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    survivor = get_widget(tenant=tenant, widget_id=into, org=actor.org, actor=actor)
    return WidgetMergePreviewOut(
        loser_id=widget.pk,
        into_id=survivor.pk,
        repoints=[
            RepointOut(title=repointed.title, left=repointed.left)
            for repointed in get_widget_merge_preview(
                tenant=tenant, actor=actor, widget=widget, into=survivor
            )
        ],
    )


@router.post("/{widget_id}/merge/", response=WidgetOut, url_name="widget-merge")
@also_refuses("merge_blocked", "merged", "archived", "stale_version")
def merge_widget_route(request: TenantRequest, widget_id: UUID, payload: WidgetMergeIn) -> Widget:
    """Merge a widget into another

    Fold this widget into the widget `into_id` names, which survives. **There
    is no undo**: preview it first — a `GET` on this path names the other widget
    and answers what would move.

    Send `into_id`, the `version` of this widget and the `into_version` of the
    other — both as you read them. Everything attached to this widget (notes,
    tags, files) moves to the survivor; its ledger stays where it was written
    and the survivor's ledger reads it. This widget is archived and answers
    read-only from then on, with `merged_into_id` naming the survivor, and every
    change to it is refused `409 merged`. Answers `200` with the survivor.

    **Safe to retry**: merging the same pair again answers the survivor
    unchanged and tells nobody.

    Refusals you can get here:

    * `400 invalid` — `into_id` names this same widget.
    * `403 forbidden` — you do not administer both widgets' organizations.
    * `404 not_found` — either widget is not one you could have reached.
    * `409 merge_blocked` — something still holds this widget where it is.
      `blocking` names it; nothing was written.
    * `409 merged` — one of the two was already merged into a third widget;
      `merged_into` names where it went.
    * `409 archived` — one of the two is archived: restore it first.
    * `409 stale_version` — somebody saved one of them after you read it.
      `current_version` is its version now; nothing was written.
    * `422 invalid_body` — `into_id`, `version` or `into_version` is missing.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    survivor = get_widget(tenant=tenant, widget_id=payload.into_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget) or not may_be_named(actor, survivor):
        raise NotFound()
    merged = merge_widget(
        tenant=tenant,
        actor=actor,
        widget=widget,
        into=survivor,
        version=payload.version,
        into_version=payload.into_version,
    )
    return with_allowed_acts([merged], actor)[0]


# golden: merge import end
@router.post("/{widget_id}/approve/", response=WidgetOut, url_name="widget-approve")
@also_refuses("archived", "merged")
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
    * `409 archived` — the widget is archived: it reads, and nothing about it
      changes until it is restored (`POST /api/v1/widgets/{id}/restore/`).

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
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    return with_allowed_acts([approve_widget(tenant=tenant, actor=actor, widget=widget)], actor)[0]


@router.delete("/{widget_id}/", response={204: None}, url_name="widget-delete")
@also_refuses("archived", "merged", "merge_survivor")
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
    * `409 archived` — the widget is archived: it reads, and nothing about it
      changes until it is restored (`POST /api/v1/widgets/{id}/restore/`).
    * `409 merge_survivor` — other widgets were merged into this one and still
      point at it; archive it instead (`POST /api/v1/widgets/{id}/archive/`).
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    A delete is a write, so the reachability fence applies: `may_be_named` is
    asked out loud on the line that hands the row to the service (house rule
    26), even though `get_widget` has already narrowed to the acting
    organization's subtree and it can only agree.
    """
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    delete_widget(tenant=tenant, actor=actor, widget=widget)
    return Status(204, None)
